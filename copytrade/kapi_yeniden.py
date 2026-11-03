"""Kapı yeniden koşusu (`--yeniden-dene-gun`): bir günün `hata` dolu satırlarını (ör. 14–16 UTC `HTTPError: 500`) yeniden hesaplar ve mevcut `sonuc.csv` ile BAYT BAYT birleştirir.

Kurallar (lider kararı):
- Yalnız o günün `hata` dolu satırları yeniden koşulur; sonuçlar mevcut `sonuc.csv`'ye birleşir: yalnız o satırlar değişir, DİĞER SATIRLAR BAYT BAYT AYNI kalır
  (metin kayıt düzeyinde değiştirilir; dosya pandas ile yeniden yazılmaz).
- `hesap` sürümü ve `kod_hash` (dosyadaki tüm satırlar) çalışan koddakiyle AYNI değilse koşu REDDEDİLİR (farklı hesap sürümü/kodu tek dosyada karışmaz).
- Ardından `durum.json` yeniden hesaplanır (hatali_satir / hatali_oran dahil), RAPOR.md ve günlük getiri dosyası güncellenir.
- Ağ yalnız halka açık Hyperliquid + Binance listesi; yeniden koşu satırları ilk koşunun `now_ms` değeriyle (satırda kayıtlı) hesaplanır.

Hash istisnası (lider kararı 2026-11-03, tek seferlik, YALNIZ açık girdiyle `--hash-istisnasi` / iş akışı `hash_istisnasi`): kod hash'i farklı dosya, ancak önce
11-03'te başarılı olmuş (hata boş, `asama1` Geçti) 20 satır YENİ kodla yeniden hesaplanıp satır başı ham sütunların HEPSİ bayt bayt aynı çıkarsa işlenir; tek fark → durur,
hiçbir şey yazılmaz. `hesap` sürümü her durumda aynı olmalıdır. Varsayılan davranış reddetmektir.

BHY ailesi (lider kararı): bayt kuralı yalnız satır başı HAM sütunlar içindir. `bhy_q` ve ona bağlı karar sütunları (`FINAL_SUTUNLAR`) aile değişince TÜM satırlar için
yeniden hesaplanır (eski q'lar eksik aileyle hesaplanmıştı); değişen hücreler yerinde değiştirilir, ham sütunlar dokunulmaz. `finalize_farkli_diger_satir` artık hata işareti değil, bilgidir.
"""
from __future__ import annotations

import csv
import io
import json
import re
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from copytrade import kapi
from copytrade.kurallar import load_rules
from copytrade.tarama import KAPI_YENIDEN_BEKLEME, PublicClient, RateLimiter

FINAL_SUTUNLAR = ("bhy_q", "adim7", "sinif", "katman", "neden", "genc_aday", "gecmis_gun")     # finalize'ın tüm aileye bağlı hesapladığı sütunlar
KONTROL_DISI = FINAL_SUTUNLAR + ("kod_hash", "satir_kaynagi", "evren_disi")                       # kontrol örneğinde karşılaştırılmayan sütunlar (HAM olmayan / kasıtlı farklı)
KONTROL_DISI_ONEK = "sure_"                                                                       # süre / telemetri sütunları (duvar saati, önbellek isabeti): hesap değil, bayt bayt aynı olamaz
HASH_ISTISNASI_METNI = "kapi-5xx yeniden deneme; hesap mantığı değişmedi"
KONTROL_ORNEK = 20


class YenidenKosuReddedildi(RuntimeError):
    """Hesap sürümü / kod hash'i uyuşmuyor ya da satırlar bayt düzeyinde korunamıyor: sonuç dosyasına DOKUNULMAZ."""


def kayitlar(metin: str) -> list[str]:
    """CSV metnini kayıtlara böler (tırnak içindeki satır sonları kaydı bölmez); `''.join(kayitlar(m)) == m`."""
    parcalar = re.findall(r"[^\n]*\n|[^\n]+", metin)
    sonuc, birikim = [], ""
    for parca in parcalar:
        birikim += parca
        if birikim.count('"') % 2 == 0:
            sonuc.append(birikim)
            birikim = ""
    if birikim:
        sonuc.append(birikim)
    return sonuc


def kayit_adresi(kayit: str) -> str:
    return next(csv.reader(io.StringIO(kayit)))[0]


def surum_kontrol(tablo: pd.DataFrame, hash_istisnasi: bool = False) -> bool:
    """Dosyadaki TÜM satırlar çalışan kodun hesap sürümüyle üretilmiş olmalı; kod hash'i de aynı olmalı, yalnız `hash_istisnasi` açıksa farklı hash'e izin verilir
    (o zaman kontrol örneği zorunludur). Dönüş: kod hash'i farklı mı (istisna kullanılıyor mu)."""
    farkli = False
    for sutun, beklenen in (("hesap", kapi.HESAP_SURUMU), ("kod_hash", kapi.HESAP_KOD_HASH)):
        if sutun not in tablo or tablo[sutun].isna().any():
            raise YenidenKosuReddedildi(f"reddedildi: sonuc.csv'de `{sutun}` eksik")
        bulunan = sorted(set(tablo[sutun].astype(str)))
        if bulunan == [beklenen]:
            continue
        if sutun == "kod_hash" and hash_istisnasi:
            farkli = True
            continue
        raise YenidenKosuReddedildi(f"reddedildi: `{sutun}` uyuşmuyor (dosya: {', '.join(v[:16] + '…' if sutun == 'kod_hash' else v for v in bulunan)}; "
                                    f"çalışan kod: {beklenen[:16] + '…' if sutun == 'kod_hash' else beklenen})"
                                    + ("; tek seferlik istisna için `--hash-istisnasi` (kontrol örneği şartıyla)" if sutun == "kod_hash" else ""))
    return farkli


def bayt_birlestir(eski_metin: str, hedefler: dict[str, str]) -> str:
    """Eski CSV metninde `hedefler` (adres -> yeni kayıt metni) kayıtlarını yerinde değiştirir; diğer kayıtlar AYNEN kalır."""
    cikti, kalan = [], dict(hedefler)
    for kayit in kayitlar(eski_metin):
        adres = kayit_adresi(kayit)
        cikti.append(kalan.pop(adres) if adres in kalan else kayit)
    if kalan:
        raise YenidenKosuReddedildi(f"reddedildi: {len(kalan)} adres dosyada bulunamadı")
    return "".join(cikti)


def _esit(a: pd.Series, b: pd.Series) -> pd.Series:
    """Hücre eşitliği; sayılarda CSV gidiş-dönüşünün son hane gürültüsü (örn. 0,3229156948558537 ↔ …375) fark sayılmaz."""
    a, b = a.reset_index(drop=True), b.reset_index(drop=True)
    sayi = pd.api.types.is_numeric_dtype(a) and pd.api.types.is_numeric_dtype(b)
    esit = pd.Series(np.isclose(a.astype(float), b.astype(float), rtol=1e-12, atol=0.0, equal_nan=True), index=a.index) if sayi else (a == b)
    return esit | (a.isna() & b.isna())


def _hucre(deger: Any, tur: Any) -> Any:
    """Değeri sütunun CSV biçimine uydurur (float sütunu: "12.0" biçimi korunur; boş → None)."""
    if deger is None or (not isinstance(deger, (list, dict)) and pd.isna(deger)):
        return None
    if tur.kind == "f" and isinstance(deger, (int, float, np.integer, np.floating)) and not isinstance(deger, (bool, np.bool_)):
        return float(deger)
    return deger


def _yaz(alanlar: list[str]) -> str:
    cikti = io.StringIO()
    csv.writer(cikti, lineterminator="\n").writerow(alanlar)
    return cikti.getvalue()


def _alanlar(kayit: str) -> list[str]:
    return next(csv.reader(io.StringIO(kayit)))


class _MumKaydi:
    """İstemci sarmalayıcı: `candleSnapshot` hatasında hangi coin'in düştüğünü ADRES bazında kaydeder (rapor için); istemcinin davranışını değiştirmez."""

    def __init__(self, istemci: Any):
        self._istemci, self.adres, self.hatalar = istemci, None, {}

    def __getattr__(self, ad: str) -> Any:
        return getattr(self._istemci, ad)

    def candles(self, coin: str, *args: Any, **kwargs: Any) -> Any:
        try:
            return self._istemci.candles(coin, *args, **kwargs)
        except Exception as hata:
            self.hatalar.setdefault(self.adres, {})[coin] = f"{type(hata).__name__}: {str(hata)[:60]}"
            raise


def calistir(root: Path, gun: str, *, en_fazla: int | None = None, client: Any = None, degerlendir: Callable[..., dict] | None = None,
             semboller: set[str] | None = None, rules: dict | None = None, log: Callable[[str], None] = print,
             hash_istisnasi: bool = False, kontrol_ornek: int = KONTROL_ORNEK) -> dict[str, Any]:
    """Bir günün hatalı satırlarını yeniden koşar, `sonuc.csv`'yi bayt bayt birleştirir, `durum.json`/RAPOR.md/gunluk.csv.gz'yi günceller. Özet sözlüğü döner."""
    rules = rules or load_rules()
    degerlendir = degerlendir or kapi.evaluate_address
    cikti = root / "kapi" / gun
    yol = cikti / "sonuc.csv"
    if not yol.is_file():
        raise YenidenKosuReddedildi(f"reddedildi: {yol} yok")
    eski_metin = yol.read_bytes().decode("utf-8")
    tablo = pd.read_csv(io.StringIO(eski_metin), low_memory=False, float_precision="round_trip", dtype={"kod_hash": str, "hesap": str})
    istisna = surum_kontrol(tablo, hash_istisnasi)
    hatali = tablo[tablo["hata"].notna()] if "hata" in tablo else tablo.iloc[0:0]
    hedef_adresler = [str(a) for a in hatali["address"]][: en_fazla or None]
    ozet: dict[str, Any] = {"gun": gun, "hatali_once": len(hatali), "denenen": len(hedef_adresler), "duzelen": 0, "hala_hatali": 0, "finalize_farkli_diger_satir": 0}
    if not hedef_adresler:
        log(f"{gun}: hata dolu satır yok; yapılacak bir şey yok.")
        return ozet
    client = client or PublicClient(limiter=RateLimiter(1000), yeniden_bekleme=KAPI_YENIDEN_BEKLEME)
    if semboller is None:
        with tempfile.TemporaryDirectory() as gecici:
            semboller, _ = kapi.write_binance_universe(Path(gecici))
    dexes = kapi.hip3_dex_names(client)
    kayit = _MumKaydi(client)
    baslik = list(tablo.columns)
    turler = tablo.dtypes
    adres_satir = tablo.set_index(tablo["address"].astype(str), drop=False)
    onbellekler: dict[int, Any] = {}

    def kos(adres: str, gunluk: dict) -> dict:
        eski = adres_satir.loc[adres]
        now_ms = int(eski["now_ms"])
        now = datetime.fromtimestamp(now_ms / 1000, UTC)
        start = int((now - timedelta(days=int(rules["fills_lookback_days"]))).timestamp() * 1000)
        start_200 = int((now - timedelta(days=int(rules["mum_pencere_gun"]))).timestamp() * 1000)
        onbellek = onbellekler.setdefault(now_ms, kapi.CandleCache(kayit, start_200, now_ms))
        lider = {"address": adres, "accountValue": float(eski["account_value"]), "kaynak": str(eski.get("kaynak", "leaderboard"))}
        kayit.adres = adres
        return degerlendir(lider, kayit, onbellek, now, start, start_200, semboller, rules, False, dexes=dexes, gunluk=gunluk)

    eski_kayit = {kayit_adresi(k): k for k in kayitlar(eski_metin)[1:]}
    orijinal_hashler = sorted(str(v) for v in tablo["kod_hash"].dropna().unique())

    def metin_satiri(adres: str, deger_al: Callable[[str], Any]) -> list[str]:
        """Bir adresin yeni satırının CSV alanları: sütun biçimi tabloyla aynı (float sütunu "12.0"), eksik sütun boş."""
        satir = pd.DataFrame([[_hucre(deger_al(c), turler[c]) for c in baslik]], columns=baslik, dtype=object)
        return _alanlar(kayitlar(satir.to_csv(index=False, lineterminator="\n"))[1])

    # ---- Hash istisnası: kontrol örneği (önce 20 başarılı satır yeni kodla yeniden hesaplanır; ham sütunlar bayt bayt aynı olmalı)
    kontrol_sayi = kontrol_ayni = 0
    if istisna:
        uygun = tablo[(tablo["hata"].isna() if "hata" in tablo else True) & (tablo["asama1"] == "Geçti")]
        eskiler = uygun[uygun["kod_hash"].astype(str) != kapi.HESAP_KOD_HASH]
        adaylar = sorted(str(a) for a in (eskiler if len(eskiler) else uygun)["address"])
        if not adaylar:
            raise YenidenKosuReddedildi("reddedildi: hash istisnası için kontrol örneği yok (başarılı, analize girmiş satır bulunamadı)")
        secim = [adaylar[int(i * len(adaylar) / min(kontrol_ornek, len(adaylar)))] for i in range(min(kontrol_ornek, len(adaylar)))]
        karsilastir = [j for j, c in enumerate(baslik) if c not in KONTROL_DISI and not c.startswith(KONTROL_DISI_ONEK)]
        log(f"hash istisnası: {len(secim)} başarılı satır yeni kodla yeniden hesaplanıp ham sütunlar karşılaştırılıyor")
        for sira, adres in enumerate(secim, 1):
            log(f"[kontrol {sira}/{len(secim)}] {adres}")
            yeni_satir = kos(adres, {})
            kontrol_sayi += 1
            yeni_alan, eski_alan = metin_satiri(adres, lambda c, y=yeni_satir: y.get(c)), _alanlar(eski_kayit[adres])
            farkli = [baslik[j] for j in karsilastir if yeni_alan[j] != eski_alan[j]]
            if farkli:
                ornek = ", ".join(f"{c}: {eski_alan[baslik.index(c)]!r} → {yeni_alan[baslik.index(c)]!r}" for c in farkli[:5])
                raise YenidenKosuReddedildi(f"reddedildi: kontrol örneği tutmadı ({adres}: {len(farkli)} ham sütun farklı — {ornek}); hesap mantığı aynı sayılamaz, hiçbir şey yazılmadı")
            kontrol_ayni += 1
        log(f"hash istisnası: kontrol {kontrol_ayni}/{kontrol_sayi} satırda ham sütunlar bayt bayt aynı")

    # ---- Hatalı satırları yeniden koş
    gunluk: dict[str, pd.Series] = {}
    yeni_satirlar: list[dict] = []
    for sira, adres in enumerate(hedef_adresler, 1):
        log(f"[{sira}/{len(hedef_adresler)}] {adres}")
        yeni_satirlar.append(kos(adres, gunluk))
    yeni = pd.DataFrame(yeni_satirlar)
    hedef_maske = tablo["address"].astype(str).isin(hedef_adresler)
    diger_tablo = tablo[~hedef_maske].copy()
    # finalize'ın kendi ürettiği `neden` (kayıtlı sınıf/adımlardan) eski aileye göre bayat olabilir: yalnız o durumda yeniden üretilsin (ham `veri hatası` vb. nedenler korunur)
    if "neden" in diger_tablo:
        for i, satir in diger_tablo[diger_tablo["neden"].notna()].iterrows():
            if str(satir["neden"]) == kapi.fail_reason(satir, rules):
                diger_tablo.at[i, "neden"] = np.nan
    birlesik = pd.concat([diger_tablo, yeni], ignore_index=True)
    son = kapi.finalize(birlesik, rules).set_index("address")
    fazla = [c for c in son.columns if c not in baslik and son.loc[hedef_adresler, c].notna().any()]
    if fazla:
        raise YenidenKosuReddedildi(f"reddedildi: yeni satırlar dosyada olmayan sütun üretti ({', '.join(fazla)}); diğer satırlar bayt bayt korunamaz")

    # ---- DİĞER satırlar: ham sütunlar dokunulmaz; BHY ailesine bağlı sütunlar (FINAL_SUTUNLAR) TÜM satırlar için yeniden hesaplanır, değişen hücreler yerinde değişir
    diger = tablo.loc[~hedef_maske].set_index("address")
    fark = {c: ~_esit(diger[c], son.loc[diger.index, c]).to_numpy() for c in FINAL_SUTUNLAR if c in diger and c in son.columns}
    diger_degisen = np.zeros(len(diger), dtype=bool)
    for maske in fark.values():
        diger_degisen |= maske
    cikti_tablo = tablo.astype(object)                    # yalnız metin üretimi için: sütun türü çakışması olmadan hücreler yazılır
    indeks = {str(a): i for i, a in zip(tablo.index, tablo["address"])}
    for adres in hedef_adresler:
        i = indeks[adres]
        for sutun in baslik:
            if sutun == "address":
                continue
            if sutun in ("satir_kaynagi", "evren_disi"):
                continue        # `satir_kaynagi` "bu_kosu" KALIR: İlk 11 uygunluğu (şartname §2.3) bunu şart koşar; yeniden koşu izi durum.json `yeniden_kosu`da. Evren üyeliği değişmez
            cikti_tablo.loc[i, sutun] = _hucre(son.loc[adres, sutun], turler[sutun]) if sutun in son.columns else None
    degisen_hucre: dict[str, list[int]] = {}
    for konum, adres in enumerate(diger.index):
        for sutun, maske in fark.items():
            if maske[konum]:
                cikti_tablo.loc[indeks[str(adres)], sutun] = _hucre(son.loc[adres, sutun], turler[sutun])
                degisen_hucre.setdefault(str(adres), []).append(baslik.index(sutun))
    cikti_metin = cikti_tablo.to_csv(index=False, lineterminator="\n")
    yeni_kayit = {kayit_adresi(k): k for k in kayitlar(cikti_metin)[1:]}
    hedefler = {adres: yeni_kayit[adres] for adres in hedef_adresler}
    for adres, sutunlar in degisen_hucre.items():
        eski_alan, yeni_alan = _alanlar(eski_kayit[adres]), _alanlar(yeni_kayit[adres])
        if _yaz(eski_alan) != eski_kayit[adres]:
            raise YenidenKosuReddedildi(f"reddedildi: {adres} kaydı yeniden yazılırken bayt biçimi korunamıyor")
        for j in sutunlar:
            eski_alan[j] = yeni_alan[j]
        hedefler[adres] = _yaz(eski_alan)
    yeni_metin = bayt_birlestir(eski_metin, hedefler)
    # Doğrulama: hedef olmayan satırlarda FINAL_SUTUNLAR dışındaki (ham) hücreler bayt bayt aynı olmalı
    final_indeks = {baslik.index(c) for c in FINAL_SUTUNLAR if c in baslik}
    ham_fark = 0
    for eski_k, yeni_k in zip(kayitlar(eski_metin), kayitlar(yeni_metin)):
        adres = kayit_adresi(eski_k)
        if eski_k != yeni_k and adres not in set(hedef_adresler):
            a, b = _alanlar(eski_k), _alanlar(yeni_k)
            ham_fark += int(any(x != y for j, (x, y) in enumerate(zip(a, b)) if j not in final_indeks))
    if ham_fark:
        raise YenidenKosuReddedildi(f"reddedildi: {ham_fark} hedef olmayan satırda ham sütun değişti (olmamalı); dosyaya yazılmadı")
    cikti_tablo = pd.read_csv(io.StringIO(yeni_metin), low_memory=False, float_precision="round_trip", dtype={"kod_hash": str, "hesap": str})     # analiz (sanity / durum / rapor) için gerçek türler
    sorunlar = kapi.sanity_check(cikti_tablo, rules)
    if sorunlar:
        raise kapi.SanityError(f"{gun}: yeniden koşu sonrası akıl sağlığı kapısı tutmadı, dosyaya yazılmaz:\n- " + "\n- ".join(sorunlar))
    yol.write_bytes(yeni_metin.encode("utf-8"))
    # BHY ailesi değişim raporu (PR / durum.json): bhy_q'su değişen satır sayısı, katman / adım 7 / sınıf kararı değişenler (eski → yeni)
    bhy_degisen = int(fark["bhy_q"].sum()) if "bhy_q" in fark else 0
    karar_degisen = []
    for konum, adres in enumerate(diger.index):
        ayrinti = {c: [None if pd.isna(diger.iloc[konum][c]) else diger.iloc[konum][c], None if pd.isna(son.loc[adres, c]) else son.loc[adres, c]]
                   for c in ("katman", "adim7", "sinif") if c in fark and fark[c][konum]}
        if ayrinti:
            karar_degisen.append({"adres": str(adres), **{c: [str(v[0]), str(v[1])] for c, v in ayrinti.items()}})
    # durum.json yeniden hesaplanır
    durum_yolu = cikti / "durum.json"
    eski_durum = json.loads(durum_yolu.read_text(encoding="utf-8")) if durum_yolu.is_file() else {}
    durum = kapi.run_status(int(eski_durum.get("parca_biten", 0)), eski_durum.get("parca_beklenen"), int(eski_durum.get("islenen", len(cikti_tablo))),
                            eski_durum.get("evren"), "tam", rules, kapi.hatali_satir_say(cikti_tablo), kapi.aday_say(cikti_tablo), len(cikti_tablo))
    for anahtar in ("kapsanan", "evren_disi_satir", "eski_hesap_satir", "kod_hash_orijinal", "kod_hash_yeniden", "hash_istisnasi", "kontrol_ornek", "kontrol_ayni"):
        if anahtar in eski_durum:
            durum[anahtar] = eski_durum[anahtar]
    if istisna:             # bu koşu istisna kullandı: kayıt (önceki istisna kaydı varsa orijinal hash korunur)
        durum.update({"kod_hash_orijinal": eski_durum.get("kod_hash_orijinal") or (orijinal_hashler[0] if len(orijinal_hashler) == 1 else orijinal_hashler),
                      "kod_hash_yeniden": kapi.HESAP_KOD_HASH, "hash_istisnasi": HASH_ISTISNASI_METNI, "kontrol_ornek": kontrol_sayi, "kontrol_ayni": kontrol_ayni})
    mum = kapi.mum_ozeti(cikti_tablo)
    if mum:
        durum["mum_ozeti"] = mum
    hashler = sorted(str(v) for v in cikti_tablo["kod_hash"].dropna().unique())
    durum.update({"hesap": kapi.HESAP_SURUMU, "kod_hashler": hashler, "kod_hash_farkli": len(hashler) > 1,
                  "satir_kaynagi": cikti_tablo["satir_kaynagi"].value_counts().to_dict() if "satir_kaynagi" in cikti_tablo else {}, "kapi_sorunlari": []})
    hedef_son = cikti_tablo[cikti_tablo["address"].astype(str).isin(hedef_adresler)]
    hala = hedef_son[hedef_son["hata"].notna()] if "hata" in hedef_son else hedef_son.iloc[0:0]
    ayrinti_hata = [{"adres": str(r["address"]), "hata": str(r["hata"]),
                     "coin_hatalari": kayit.hatalar.get(str(r["address"]), {}),
                     "diyez_coin": any(str(c).startswith("#") for c in kayit.hatalar.get(str(r["address"]), {}))} for _, r in hala.iterrows()]
    ozet.update({"hala_hatali": len(hala), "finalize_farkli_diger_satir": int(diger_degisen.sum()), "bhy_q_degisen_satir": bhy_degisen,
                 "karar_degisen": karar_degisen, "ham_sutun_farki_diger_satir": ham_fark, "hala_hatali_ayrinti": ayrinti_hata,
                 "kontrol_ornek": kontrol_sayi, "kontrol_ayni": kontrol_ayni})
    ozet["duzelen"] = ozet["denenen"] - ozet["hala_hatali"]
    durum["yeniden_kosu"] = {**{k: ozet[k] for k in ("gun", "hatali_once", "denenen", "duzelen", "hala_hatali", "finalize_farkli_diger_satir", "bhy_q_degisen_satir",
                                                    "ham_sutun_farki_diger_satir")},
                             "karar_degisen": karar_degisen, "yeniden_kosan_adresler": sorted(hedef_adresler), "hala_hatali_ayrinti": ayrinti_hata}
    durum_yolu.write_text(json.dumps(durum, ensure_ascii=False, indent=1), encoding="utf-8")
    kapi.rapor_yaz(cikti, cikti_tablo, durum, eski_durum.get("evren"), eski_durum.get("parca_beklenen"), hashler)
    if gunluk:
        yol_g = cikti / "gunluk.csv.gz"
        parcalar = ([pd.read_csv(yol_g, index_col=0, parse_dates=True)] if yol_g.exists() else []) + [pd.DataFrame(gunluk)]
        birlesik_g = pd.concat(parcalar, axis=1)
        birlesik_g = birlesik_g.loc[:, ~birlesik_g.columns.duplicated(keep="last")].sort_index()
        birlesik_g.to_csv(yol_g, compression="gzip")
    ozet["durum"] = durum["durum"]
    ozet["hatali_satir"], ozet["hatali_oran_aday"], ozet["hatali_oran_evren"] = durum["hatali_satir"], durum["hatali_oran_aday"], durum["hatali_oran_evren"]
    log(json.dumps({k: v for k, v in ozet.items() if k not in ("karar_degisen", "hala_hatali_ayrinti")}, ensure_ascii=False))
    return ozet
