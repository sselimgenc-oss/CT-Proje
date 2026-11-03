"""Kapı yeniden koşusu (`--yeniden-dene-gun`): bir günün `hata` dolu satırlarını (ör. 14–16 UTC `HTTPError: 500`) yeniden hesaplar ve mevcut `sonuc.csv` ile BAYT BAYT birleştirir.

Kurallar (lider kararı):
- Yalnız o günün `hata` dolu satırları yeniden koşulur; sonuçlar mevcut `sonuc.csv`'ye birleşir: yalnız o satırlar değişir, DİĞER SATIRLAR BAYT BAYT AYNI kalır
  (metin kayıt düzeyinde değiştirilir; dosya pandas ile yeniden yazılmaz).
- `hesap` sürümü ve `kod_hash` (dosyadaki tüm satırlar) çalışan koddakiyle AYNI değilse koşu REDDEDİLİR (farklı hesap sürümü/kodu tek dosyada karışmaz).
- Ardından `durum.json` yeniden hesaplanır (hatali_satir / hatali_oran dahil), RAPOR.md ve günlük getiri dosyası güncellenir.
- Ağ yalnız halka açık Hyperliquid + Binance listesi; yeniden koşu satırları ilk koşunun `now_ms` değeriyle (satırda kayıtlı) hesaplanır.

Not (BHY): `finalize` çoklu test düzeltmesini (adım 7, `bhy_q`) TÜM aile üzerinden hesaplar; yeniden koşulan satır ailede yer alırsa diğer satırların taze `bhy_q`/`adim7`/`sinif` değeri
değişebilir. Kural gereği diğer satırlar DEĞİŞTİRİLMEZ; fark `durum.json` → `yeniden_kosu.finalize_farkli_diger_satir` (adet) ile açıkça yazılır.
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


def surum_kontrol(tablo: pd.DataFrame) -> None:
    """Dosyadaki TÜM satırlar çalışan kodun hesap sürümü ve kod hash'iyle üretilmiş olmalı; değilse reddedilir."""
    for sutun, beklenen in (("hesap", kapi.HESAP_SURUMU), ("kod_hash", kapi.HESAP_KOD_HASH)):
        if sutun not in tablo or tablo[sutun].isna().any():
            raise YenidenKosuReddedildi(f"reddedildi: sonuc.csv'de `{sutun}` eksik")
        bulunan = sorted(set(tablo[sutun].astype(str)))
        if bulunan != [beklenen]:
            raise YenidenKosuReddedildi(f"reddedildi: `{sutun}` uyuşmuyor (dosya: {', '.join(v[:16] + '…' if sutun == 'kod_hash' else v for v in bulunan)}; "
                                        f"çalışan kod: {beklenen[:16] + '…' if sutun == 'kod_hash' else beklenen})")


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


def calistir(root: Path, gun: str, *, en_fazla: int | None = None, client: Any = None, degerlendir: Callable[..., dict] | None = None,
             semboller: set[str] | None = None, rules: dict | None = None, log: Callable[[str], None] = print) -> dict[str, Any]:
    """Bir günün hatalı satırlarını yeniden koşar, `sonuc.csv`'yi bayt bayt birleştirir, `durum.json`/RAPOR.md/gunluk.csv.gz'yi günceller. Özet sözlüğü döner."""
    rules = rules or load_rules()
    degerlendir = degerlendir or kapi.evaluate_address
    cikti = root / "kapi" / gun
    yol = cikti / "sonuc.csv"
    if not yol.is_file():
        raise YenidenKosuReddedildi(f"reddedildi: {yol} yok")
    eski_metin = yol.read_bytes().decode("utf-8")
    tablo = pd.read_csv(io.StringIO(eski_metin), low_memory=False, float_precision="round_trip")
    surum_kontrol(tablo)
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
    gunluk: dict[str, pd.Series] = {}
    yeni_satirlar: list[dict] = []
    onbellekler: dict[int, Any] = {}
    for sira, adres in enumerate(hedef_adresler, 1):
        eski = hatali[hatali["address"].astype(str) == adres].iloc[0]
        now_ms = int(eski["now_ms"])
        now = datetime.fromtimestamp(now_ms / 1000, UTC)
        start = int((now - timedelta(days=int(rules["fills_lookback_days"]))).timestamp() * 1000)
        start_200 = int((now - timedelta(days=int(rules["mum_pencere_gun"]))).timestamp() * 1000)
        onbellek = onbellekler.setdefault(now_ms, kapi.CandleCache(client, start_200, now_ms))
        lider = {"address": adres, "accountValue": float(eski["account_value"]), "kaynak": str(eski.get("kaynak", "leaderboard"))}
        log(f"[{sira}/{len(hedef_adresler)}] {adres}")
        yeni_satirlar.append(degerlendir(lider, client, onbellek, now, start, start_200, semboller, rules, False, dexes=dexes, gunluk=gunluk))
    yeni = pd.DataFrame(yeni_satirlar)
    # finalize tüm aile üzerinde (adım 7 / BHY): hedef satırlar için yeni değerleri bunlardan al
    hedef_maske = tablo["address"].astype(str).isin(hedef_adresler)
    birlesik = pd.concat([tablo[~hedef_maske], yeni], ignore_index=True)
    son = kapi.finalize(birlesik, rules).set_index("address")
    baslik = list(tablo.columns)
    fazla = [c for c in son.columns if c not in baslik and son.loc[hedef_adresler, c].notna().any()]
    if fazla:
        raise YenidenKosuReddedildi(f"reddedildi: yeni satırlar dosyada olmayan sütun üretti ({', '.join(fazla)}); diğer satırlar bayt bayt korunamaz")
    turler = tablo.dtypes
    cikti_tablo = tablo.astype(object)                    # yalnız metin üretimi için: sütun türü çakışması olmadan hedef satırlar yazılır
    indeks = {str(a): i for i, a in zip(tablo.index, tablo["address"])}
    for adres in hedef_adresler:
        i = indeks[adres]
        for sutun in baslik:
            if sutun == "address":
                continue
            if sutun in ("satir_kaynagi", "evren_disi"):
                continue        # `satir_kaynagi` "bu_kosu" KALIR: İlk 11 uygunluğu (şartname §2.3) bunu şart koşar; yeniden koşu izi durum.json `yeniden_kosu`da. Evren üyeliği değişmez
            elif sutun in son.columns:
                deger = son.loc[adres, sutun]
                if pd.isna(deger):
                    deger = None
                elif turler[sutun].kind == "f" and isinstance(deger, (int, float, np.integer, np.floating)) and not isinstance(deger, bool):
                    deger = float(deger)                        # float sütunu: "12.0" biçimi korunur
                cikti_tablo.loc[i, sutun] = deger
            else:
                cikti_tablo.loc[i, sutun] = None
    # Diğer satırların finalize farkı (BHY ailesi büyüdüyse): DEĞİŞTİRİLMEZ, yalnız sayılır
    diger = tablo.loc[~hedef_maske].set_index("address")
    fark = np.zeros(len(diger), dtype=bool)
    for sutun in FINAL_SUTUNLAR:
        if sutun in diger and sutun in son.columns:
            fark |= ~_esit(diger[sutun], son.loc[diger.index, sutun]).to_numpy()
    # Bayt birleştirme: hedef kayıtlar tam tablonun CSV çıktısından alınır; diğer kayıtlar eski metinden AYNEN
    cikti_metin = cikti_tablo.to_csv(index=False, lineterminator="\n")
    hedef_kume = set(hedef_adresler)
    hedef_kayit = {kayit_adresi(k): k for k in kayitlar(cikti_metin) if kayit_adresi(k) in hedef_kume}
    yeni_metin = bayt_birlestir(eski_metin, hedef_kayit)
    cikti_tablo = pd.read_csv(io.StringIO(yeni_metin), low_memory=False, float_precision="round_trip")     # analiz (sanity / durum / rapor) için gerçek türler
    sorunlar = kapi.sanity_check(cikti_tablo, rules)
    if sorunlar:
        raise kapi.SanityError(f"{gun}: yeniden koşu sonrası akıl sağlığı kapısı tutmadı, dosyaya yazılmaz:\n- " + "\n- ".join(sorunlar))
    yol.write_bytes(yeni_metin.encode("utf-8"))
    # durum.json yeniden hesaplanır
    durum_yolu = cikti / "durum.json"
    eski_durum = json.loads(durum_yolu.read_text(encoding="utf-8")) if durum_yolu.is_file() else {}
    durum = kapi.run_status(int(eski_durum.get("parca_biten", 0)), eski_durum.get("parca_beklenen"), int(eski_durum.get("islenen", len(cikti_tablo))),
                            eski_durum.get("evren"), "tam", rules, kapi.hatali_satir_say(cikti_tablo), len(cikti_tablo))
    for anahtar in ("kapsanan", "evren_disi_satir", "eski_hesap_satir"):
        if anahtar in eski_durum:
            durum[anahtar] = eski_durum[anahtar]
    mum = kapi.mum_ozeti(cikti_tablo)
    if mum:
        durum["mum_ozeti"] = mum
    hashler = sorted(str(v) for v in cikti_tablo["kod_hash"].dropna().unique())
    durum.update({"hesap": kapi.HESAP_SURUMU, "kod_hashler": hashler, "kod_hash_farkli": len(hashler) > 1,
                  "satir_kaynagi": cikti_tablo["satir_kaynagi"].value_counts().to_dict() if "satir_kaynagi" in cikti_tablo else {}, "kapi_sorunlari": []})
    ozet.update({"hala_hatali": int(cikti_tablo.loc[hedef_maske, "hata"].notna().sum()) if "hata" in cikti_tablo else 0,
                 "finalize_farkli_diger_satir": int(fark.sum())})
    ozet["duzelen"] = ozet["denenen"] - ozet["hala_hatali"]
    durum["yeniden_kosu"] = {**{k: ozet[k] for k in ("gun", "hatali_once", "denenen", "duzelen", "hala_hatali", "finalize_farkli_diger_satir")},
                             "yeniden_kosan_adresler": sorted(hedef_adresler)}
    durum_yolu.write_text(json.dumps(durum, ensure_ascii=False, indent=1), encoding="utf-8")
    kapi.rapor_yaz(cikti, cikti_tablo, durum, eski_durum.get("evren"), eski_durum.get("parca_beklenen"), hashler)
    if gunluk:
        yol_g = cikti / "gunluk.csv.gz"
        parcalar = ([pd.read_csv(yol_g, index_col=0, parse_dates=True)] if yol_g.exists() else []) + [pd.DataFrame(gunluk)]
        birlesik_g = pd.concat(parcalar, axis=1)
        birlesik_g = birlesik_g.loc[:, ~birlesik_g.columns.duplicated(keep="last")].sort_index()
        birlesik_g.to_csv(yol_g, compression="gzip")
    ozet["durum"] = durum["durum"]
    ozet["hatali_satir"], ozet["hatali_oran"] = durum["hatali_satir"], durum["hatali_oran"]
    log(json.dumps(ozet, ensure_ascii=False))
    return ozet
