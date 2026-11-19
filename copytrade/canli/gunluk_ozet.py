"""Ortak günlük özet (`ortak.gunluk_ozet.v1`): `durum/paylasim/gunluk_ozet_v1.json` (orkestratör okur; haftalık karşılaştırma). YALNIZ BİLGİ: karar/emir yoluna girmez.

Yazım: motorun `durum_yaz()` çağrısındaki tek satırlık kanca `yaz_gerekirse(motor)` ile; (a) günlük Telegram raporu gönderildiği dakikada (21:00 TSİ = `canli_ozet_saat_utc` 18 UTC),
(b) en geç her saatte bir (`SAATLIK_MS`). Hata dışarı çıkmaz. Bilinmeyen alan `null` (alan atlanmaz). Adres/anahtar/e-posta YOK: hesaplar `ogrenme_adaptor.takma_ad` (T_xxxxxx) ile adlanır;
çıktıda `0x...` kalıntısı maskelenir.

`mod`: gerçek kip → "canli"; sunucu (`SUNUCU_MOD=deneme` ya da `VERI_DALI` canli-durum-deneme) → "deneme"; diğer sanal (Actions `canli-durum`, sunucu `uretim`) → "sanal".
(Ortam değişkenleri `/etc/sg-sanal-mod.env`'den sunucu servisine, Actions'ta iş akışından gelir; belirsizse "sanal".)

Sayım kaynağı: bugünün (UTC) `kayit/<tarih>.jsonl` dosyası (`emir`, `emir_yok`, `adim_hata` olayları); durum: motorun belleği. Birimler: para USD (kasa ölçeğinde), yüzdeler yüzde (2,1 = %2,1), zaman ISO UTC.
`hesaplar[].gun_pnl` = bugün GERÇEKLEŞEN K/Z − ücret (açık pozisyon değişimi yok); `toplam_pnl` = slot girişinden beri net (`slot_ozsermaye − slot_bas`, gerçekleşmemiş dahil); `islem` = bugün dolan emir sayısı.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from copytrade.canli import kaynak, rejim_sonuc, secim_gercek
from copytrade.canli import sert_sinirlar as sert
from copytrade.canli.ogrenme_adaptor import takma_ad

SEMA = "ortak.gunluk_ozet.v1"
SAATLIK_MS = 3_600_000
DOSYA = "gunluk_ozet_v1.json"
_ADRES = re.compile(r"0x[0-9a-fA-F]+")
_DOLU = ("dolu", "kismi")


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def mod_belirle(kip: str, ortam: dict | None = None) -> str:
    """kip "gercek" → "canli"; sunucu deneme (SUNUCU_MOD=deneme ya da VERI_DALI canli-durum-deneme) → "deneme"; aksi "sanal"."""
    if kip == "gercek":
        return "canli"
    e = os.environ if ortam is None else ortam
    if str(e.get("SUNUCU_MOD", "")).strip() == "deneme" or str(e.get("VERI_DALI", "")).strip() == "canli-durum-deneme":
        return "deneme"
    return "sanal"


def _gunluk_kayitlar(motor: Any, gun: str) -> list[dict]:
    """Bugünün kayıt satırları (bozuk satır atlanır; dosya yoksa boş)."""
    yol = Path(motor.kayit.dizin) / f"{gun}.jsonl"
    satirlar: list[dict] = []
    try:
        with yol.open(encoding="utf-8") as f:
            for s in f:
                try:
                    o = json.loads(s)
                except ValueError:
                    continue
                if isinstance(o, dict):
                    satirlar.append(o)
    except OSError:
        pass
    return satirlar


def _say(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") else None


def ogrenme_etki(kayitlar: list[dict]) -> dict:
    """Öğrenme katmanının bugünkü etkisi (YALNIZ OKUMA; günlük kayıt satırlarından, yeni sayım mantığı yok):
    - `filtre_atlanan`: `ml_filtre_atla` olayı sayısı (ML filtresinin atladığı açılış sinyalleri).
    - `filtre_karsi_olgu_pnl`: bugün KAPANAN `karsi_olgu_kapandi` kayıtlarından neden `ml_filtre_atla` olanların `pnl_usd` toplamı ($, hayali). Kapanış anahtarı (adres|coin) kayıtta yok; neden ile eşleşir. Hiç kapanan yoksa null.
    - `ders_kucultulen`: dolan (`usd_dolan` > 0) açılış/artırma `emir` kayıtlarından `ders_carpan` < 1 olanların sayısı (ders slotu küçülttü). Alanı taşıyan kayıt yoksa (eski kayıtlar) null.
    - `ders_engellenen`: `emir_yok` olaylarında neden `ders_emekli` olan (emekli dersle engellenen açılış) sayısı."""
    filtre = sum(1 for k in kayitlar if k.get("olay") == "ml_filtre_atla")
    pnl = [_say(k.get("pnl_usd")) for k in kayitlar if k.get("olay") == "karsi_olgu_kapandi" and k.get("neden") == "ml_filtre_atla"]
    kapali = [p for p in pnl if p is not None]
    carpanli = [_say(k.get("ders_carpan")) for k in kayitlar if k.get("olay") == "emir" and "ders_carpan" in k and (_say(k.get("usd_dolan")) or 0.0) > 0]
    carpanli = [c for c in carpanli if c is not None]
    engel = sum(1 for k in kayitlar if k.get("olay") == "emir_yok" and k.get("neden") == "ders_emekli")
    return {"filtre_atlanan": filtre, "filtre_karsi_olgu_pnl": round(sum(kapali), 2) if kapali else None, "ders_kucultulen": sum(1 for c in carpanli if c < 1.0) if carpanli else None, "ders_engellenen": engel}


def _medyan(v: list[float]) -> float | None:
    if not v:
        return None
    s = sorted(v)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _p90(v: list[float]) -> float | None:
    """En yakın sıra yöntemi: ceil(0,9 × n)-inci küçük değer (tam sayı aritmetiği)."""
    if not v:
        return None
    s = sorted(v)
    return s[max(0, (9 * len(s) + 9) // 10 - 1)]


def _kalite_grup(satirlar: list[dict]) -> dict:
    """Dolan (`usd_dolan` > 0) `emir` satırları için gecikme/görme/kayma özeti. Eksik zaman/kayma olan satır o metrikte atlanır. Veri yoksa null."""
    dolu = [k for k in satirlar if k.get("olay") == "emir" and (_say(k.get("usd_dolan")) or 0.0) > 0]
    gecikme, gorme, kayma = [], [], []
    for k in dolu:
        tdm = _say(k.get("trader_dolum_ms"))
        dm = _say(k.get("dolum_ms"))
        gm = _say(k.get("gorme_ms"))
        kt = _say(k.get("kayma_trader"))
        if tdm is not None and dm is not None:
            gecikme.append(dm - tdm)
        if tdm is not None and gm is not None:
            gorme.append(gm - tdm)
        if kt is not None:
            kayma.append(kt * 10000)
    r1 = lambda v: None if v is None else round(v, 1)                    # noqa: E731
    return {"n": len(dolu), "gecikme_ms_medyan": r1(_medyan(gecikme)), "gecikme_ms_p90": r1(_p90(gecikme)),
            "gorme_ms_medyan": r1(_medyan(gorme)), "kayma_bps_medyan": r1(_medyan(kayma)), "kayma_bps_p90": r1(_p90(kayma))}


def kopya_kalite(kayitlar: list[dict]) -> dict:
    """Kopya gecikme ve kayma özeti (YALNIZ BİLGİ; karar/eşik değiştirmez). Girdi: çağıranın seçtiği kayıt satırları (günlük ya da 24 sa).
    - `gecikme_ms` = dolum_ms − trader_dolum_ms (bizim dolumumuz, trader dolumundan kaç ms sonra).
    - `gorme_ms` = gorme_ms − trader_dolum_ms (trader dolumunu bizim kaç ms sonra gördüğümüz).
    - `kayma_bps` = kayma_trader × 10000; + = trader fiyatından aleyhe (motor tanımı: alımda (dolum−trader)/trader, satımda ters işaret).
    - `ac_artir` / `azalt_kapat`: aynı metrikler, eylem gruplarına göre.
    Yalnız dolan emirler (usd_dolan > 0). p90: en yakın sıra. Veri yoksa ilgili alanlar null."""
    return {**_kalite_grup(kayitlar), "ac_artir": _kalite_grup([k for k in kayitlar if k.get("eylem") in ("ac", "artir")]),
            "azalt_kapat": _kalite_grup([k for k in kayitlar if k.get("eylem") in ("azalt", "kapat")])}


def gunluk_etki(motor: Any) -> dict:
    """Bugünün (UTC gün) öğrenme etkisi: Telegram günlük raporu için. Hata yutulur; hata olursa tüm alanlar null/0."""
    try:
        gun = datetime.fromtimestamp(int(motor.saat_ms()) / 1000, UTC).date().isoformat()
        return ogrenme_etki(_gunluk_kayitlar(motor, gun))
    except Exception:                                                # noqa: BLE001
        return {"filtre_atlanan": 0, "filtre_karsi_olgu_pnl": None, "ders_kucultulen": None, "ders_engellenen": 0}


def _ogrenme(motor: Any, gun: str, kayitlar: list[dict]) -> dict:
    og = getattr(motor, "ogrenme", None)
    bos = {"aktif_ders": None, "yeni_ders": None, "emekli_ders": None, "filtre_aktif": False, **ogrenme_etki(kayitlar)}
    if og is None or not getattr(og, "aktif", False):
        return bos
    try:
        ham = json.loads(Path(og.ders_yolu).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        ham = None
    sonuc = {**bos, "filtre_aktif": bool(og.k.get("ogrenme_filtre_aktif"))}
    if isinstance(ham, dict):
        durumlar = [v for v in ham.values() if isinstance(v, dict)]
        sonuc["aktif_ders"] = sum(1 for v in durumlar if v.get("status") == "alive")
        sonuc["emekli_ders"] = sum(1 for v in durumlar if v.get("status") == "retired")
        sonuc["yeni_ders"] = sum(1 for v in durumlar if str(v.get("born", ""))[:10] == gun)
    return sonuc


def _rejim_btc(motor: Any) -> str | None:
    z = ((getattr(motor, "rejim_anlik", None) or {}).get("rejimler") or {}).get("BTC") or {}
    r = z.get("4h") or (getattr(motor, "rejim_4h_son", None) or {}).get("BTC")
    return str(r) if r else None


def _drift_uyari(motor: Any) -> bool:
    if any(isinstance(v, dict) and v.get("aktif") for v in (getattr(motor, "kopya_drift", None) or {}).values()):
        return True
    og = getattr(motor, "ogrenme", None)
    satirlar = og.pano() if og is not None else None
    return any(isinstance(r, dict) and r.get("drift") == "uyari" for r in (satirlar or []))


def _kaynak_saglik(motor: Any) -> dict:
    """Sunucu kaynak alanları (yeni, ek): ram_mb, ram_tepe_mb, disk_bos_gb, yuk_1dk; ölçülemeyen None. Hata yutulur."""
    try:
        o = kaynak.olc(getattr(motor, "durum_dizin", None))
    except Exception:                                                  # noqa: BLE001
        o = {}
    return {k: o.get(k) for k in ("ram_mb", "ram_tepe_mb", "disk_bos_gb", "yuk_1dk")}


def olustur(motor: Any, ortam: dict | None = None) -> dict:
    """Günlük özet sözlüğü (saf okuma; durum değiştirmez)."""
    simdi = int(motor.saat_ms())
    gun = datetime.fromtimestamp(simdi / 1000, UTC).date().isoformat()
    kayitlar = _gunluk_kayitlar(motor, gun)
    dolu = [k for k in kayitlar if k.get("olay") == "emir" and k.get("durum") in _DOLU]
    kapanis = [k for k in dolu if k.get("eylem") == "kapat" and _say(k.get("pnl_usd")) is not None]
    oz = float(motor.ozsermaye())
    kasa = float(motor.kasa)
    risk = motor.risk
    gun_pnl = round(oz - float(risk.gun_basi), 2) if getattr(risk, "gun", None) == gun else None
    dusus = round((float(risk.zirve) - oz) / float(risk.zirve) * 100, 2) if float(risk.zirve) > 0 else None
    hesaplar = []
    for adres in sorted(motor.saha.uyeler):
        satir = [k for k in dolu if k.get("adres") == adres]
        so = motor.hesap.slot_ozsermaye(adres, motor.marks)
        gerc = sum(_say(k.get("pnl_usd")) or 0.0 for k in satir)
        ucr = sum(_say(k.get("ucret")) or 0.0 for k in satir)
        hesaplar.append({"ad": takma_ad(adres), "gun_pnl": round(gerc - ucr, 2),
                         "toplam_pnl": None if so is None else round(so - float(motor.hesap.slot_bas[adres]), 2), "islem": len(satir)})
    yaml_kayip = _say(motor.rules.get("canli_gunluk_kayip_oran"))
    drift = _drift_uyari(motor)
    durdu = bool(risk.dur)
    notlar: list[str] = []
    if durdu:
        notlar.append(f"DUR aktif: {risk.dur_neden or 'bilinmiyor'}")
    kapali = sorted(a for a, v in risk.acilis_durdu.items() if v)
    if kapali:
        notlar.append("yeni açılış kapalı: " + ", ".join(kapali))
    if drift:
        notlar.append("drift uyarısı aktif")
    notlar.append("hesaplar.gun_pnl = bugün gerçekleşen K/Z - ücret (açık pozisyon değişimi yok)")
    veri = {
        "sema": SEMA, "proje": "CT", "uretim": _iso(simdi), "gun": gun, "mod": mod_belirle(motor.kip, ortam),
        "kasa": {"baslangic": round(kasa, 2), "simdi": round(oz, 2), "gun_pnl": gun_pnl, "toplam_pnl": round(oz - kasa, 2), "zirveden_dusus_yuzde": dusus},
        "islem": {"gun_acilan": sum(1 for k in dolu if k.get("eylem") == "ac"), "gun_kapanan": len(kapanis),
                  "kazanan": sum(1 for k in kapanis if _say(k["pnl_usd"]) > 0), "kaybeden": sum(1 for k in kapanis if _say(k["pnl_usd"]) < 0),
                  "acik_pozisyon": sum(len(c) for c in motor.hesap.poz.values()), "alinmayan_sinyal": sum(1 for k in kayitlar if k.get("olay") == "emir_yok")},
        "hesaplar": hesaplar, "ogrenme": _ogrenme(motor, gun, kayitlar), "rejim": _rejim_btc(motor), "drift_uyari": drift,
        "limitler": {"gunluk_kayip_yuzde": round((yaml_kayip if yaml_kayip is not None else sert.GUNLUK_KAYIP_UST_ORAN) * 100, 2), "kaldirac_tavan": sert.KALDIRAC_UST, "durdu_mu": durdu,
                     "kaldirac_ayar": _say(motor.rules.get("canli_marj_kaldirac"))},
        "saglik": {"son_nabiz": _iso(simdi), "hata_sayisi_gun": sum(1 for k in kayitlar if k.get("olay") == "adim_hata"), **_kaynak_saglik(motor)},
        "notlar": notlar[:5],
        "kopya_kalite": kopya_kalite(kayitlar),
    }
    return json.loads(_ADRES.sub("[gizli]", json.dumps(veri, ensure_ascii=False)))


def _yaz(yol: Path, veri: dict) -> None:
    yol.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(yol.parent), prefix=".go-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(veri, f, ensure_ascii=False, indent=1)
        os.replace(tmp, yol)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def yaz_gerekirse(motor: Any, ortam: dict | None = None) -> bool:
    """`durum_yaz()` kancası: günlük rapor gönderildiyse (motor `_ozet_gunu` değişti) ya da son yazımdan ≥ 1 saat geçtiyse yazar. Hata yutulur (kayıt `gunluk_ozet_hata`). Döner: yazıldı mı."""
    try:
        simdi = int(motor.saat_ms())
        son = getattr(motor, "_gunluk_ozet_yazim", None)            # (ms, ozet_gunu) — süreç içi; yeniden başlatmada hemen yazar
        if son is not None and simdi - son[0] < SAATLIK_MS and getattr(motor, "_ozet_gunu", None) == son[1]:
            return False
        _yaz(Path(motor.durum_dizin) / "paylasim" / DOSYA, olustur(motor, ortam))
        try:                                                         # rejim/duygu x sonuç raporu (aynı an; kendi hatası günlük özeti bozmaz)
            rejim_sonuc.yaz(motor)
        except Exception as hata:                                    # noqa: BLE001
            motor.kayit({"olay": "rejim_sonuc_hata", "tur": type(hata).__name__})
        try:                                                         # kadro seçimi x gerçek PnL (form sırası Spearman; yalnız bilgi)
            secim_gercek.yaz(motor)
        except Exception as hata:                                    # noqa: BLE001
            motor.kayit({"olay": "secim_gercek_hata", "tur": type(hata).__name__})
        motor._gunluk_ozet_yazim = (simdi, getattr(motor, "_ozet_gunu", None))
        return True
    except Exception as hata:                                        # noqa: BLE001
        try:
            motor.kayit({"olay": "gunluk_ozet_hata", "tur": type(hata).__name__})
        except Exception:                                            # noqa: BLE001
            pass
        return False
