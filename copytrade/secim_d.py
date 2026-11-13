"""Seçim yapısı D — sabit kadro, yalnız risk çıkışı (K-55, kullanıcı kararı 09.11; ön kayıt `docs/ONKAYIT_SECIM_2026-11-09.md` §1 D + B evreni).

Ön kaydın "fark kanıtlanamazsa en sade" sırasında ilk sıradaki yapı teoride seçildi (kullanıcı geriye dönük sınamayı beklemek istemedi). Günlük koşu (`radar.yml`):
1. **Üye denetimi (her gün):** önceki v2 kadrosunun üyeleri için `portfolio` + son `secim_islem_yok_gun` gün dolumu → çıkış yalnız risk nedeniyle:
   pnl GİRİŞİMİZDEN beri zirvesinden ≥ `secim_cikis_zirve_dusus` × giriş hesabı; `secim_islem_yok_gun` gün işlem yok; aylık kontrolde iki ay üst üste zarar. (Slot stop ve kaldıraç motorda.)
   Çıkan ve motorun cezalandırdığı adresler `canli_bekleme_gun` boyunca aday olmaz (`cikanlar_gecmis`). secim_d çıkışı motora K-39 ile (iki UTC günü) yansır; arada slot stop korur.
2. **Doldurma (ilk koşu ve ayın ilk koşusu):** lider tablosunun tamamı → ucuz ön filtre (hesap ≥ `secim_min_hesap_usd`, ay pnl > 0, ay hacmi > 0) → `portfolio` (B evreni):
   son `secim_hafta_sayisi` haftanın ≥ `secim_pozitif_hafta_min`'i pnl > 0, 90 g pnl > 0, 90 g pnl düşüşü ≤ `secim_dusus_90g_max` × hesap → haftalık getiri t-istatistiğine göre
   azalan ilk `secim_aday_ust` kişi için son `secim_kopya_gun` günün dolumları (B kapıları): medyan tutma ≥ 1 sa, kaldıraç ≤ 20x, likit pay ≥ %80, haftalık devir ≤ 100,
   kopya (gecikmesiz + tam maliyet, saatlik işaret) getirisi > 0 ve koruma ≥ 0,5 → boş koltuklar t sırasıyla dolar. Boş kalan koltuk nakit.
3. Çıktı: `radar/<tarih>/havuz.json` (`secim-d-havuz-v1`, ölçüler) + `kadro.json` (`radar-kadro-v1` biçimi, `radar_surum: v2`; motor K-54 ile yalnız bunu uygular).
Değiştirme YOK (sıra değişimi çıkış nedeni değil). Eşikler `kurallar.yaml` `secim_*`; kodda sayı yok.
**D+ (K-56, Fable önerisi, kullanıcı onayı 09.11):** kopya kapısına A'dan kopya işlem ≥ `radar_min_kopya_islem` ve kısa işlem payı ≤ `radar_kisa_islem_payi_max`, C'den aktif coin
≤ `secim_aktif_coin_max`; çıkışa girişimizden beri trader pnl düşüşü ≥ `secim_cikis_giris_dusus` × giriş hesabı, E'den aylık kontrolde iki ay üst üste BİZİM slot net K/Z'si < 0
(motor `durum/hesap.json`: realize − ücret + funding; okunamazsa trader 30 g pnl yedeği), motor sahadan cezayla düşürdüyse (`saha.json` bekleme) kadrodan da düşer (döngü yok);
kadro `korelasyon` matrisi 28 g günlük kopya getirilerinden (benzerlik kuralı motorda çalışır). Boyut (N 5, 200 $, tavan 1,5×, 5,5 $ altı açılmaz) `kurallar.yaml`/`boyut.py`.
**K-65 (veri_surum 2):** pnl serisi yalnız PERP (`perpAllTime` + `perpMonth` + `perpWeek` birleşik, taze kuyruk; hesap değeri toplam seriden); en yeni pnl noktası
`secim_veri_azami_yas_saat`'ten eski aday `veri_bayat`. Kopya kapısına gelen aday ve üyede hesap değeri motor tanımıyla da okunur (tüm perp dex + spot USDC); seri
`secim_payda_azami_fark`'tan fazla saparsa motor değeri kullanılır (`payda_duzeltildi`). Geçici güvenlik vetoları (kapılardan sonra): ömür perp pnl ≤ 0 (`veto_omur_zarar`),
zarara ekleme payı ≥ `secim_veto_zarara_ekleme_oran` (`veto_zarara_ekleme`); kapı + veto geçen aday < `secim_veto_min_aday` ise o koşu askıda (`veto_askida`). Vetolu üye çıkar,
yeri aynı koşuda dolar; motor bu çıkışları K-61 gibi hemen uygular.

    python -m copytrade.secim_d --cikti radar --onceki-kadro onceki.json
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from copytrade import boyut, kalicilik_testi, kopya_v5, radar_form, radar_tarama
from copytrade.defter import HOUR
from copytrade.kurallar import load_rules
from copytrade.olcut import martingale_ratio, perp_fills
from copytrade.tarama import _address, _window

GUN = 24 * HOUR
HAFTA = 7 * GUN
SURUM = "v2"
HAVUZ_SEMA = "secim-d-havuz-v1"
VERI_SURUM = 2                                                              # K-65: perp pnl + taze birleşik seri + motor paydası (1 = toplam allTime pnl)
PNL_PERP = ("perpAllTime", "perpMonth", "perpWeek")                        # kabadan inceye (yalnız perp pnl: spot pnl kopyalanamaz)
PNL_TOPLAM = ("allTime", "month", "week")                                   # perp dönemleri yoksa (eski biçim) yedek
HESAP_DONEM = ("allTime", "month", "week")                                  # hesap değeri TOPLAM seriden (perp* accountValueHistory birleşik hesapta 0 olabilir)
ANINDA_VETO = ("veto_omur_zarar", "veto_zarara_ekleme")                     # K-65 veto çıkışları (motor K-61 gibi hemen uygular)
HARIC_YOL = Path(__file__).resolve().parent / "radar" / "HARIC"     # elle çıkarma listesi (kullanıcı kararı; satır: adres  # neden, tarih)


def haric_oku(yol: Path = HARIC_YOL) -> set[str]:
    """Kullanıcının elle çıkardığı adresler (küçük harf). Dosya yoksa boş. `#` sonrası açıklama."""
    if not yol.exists():
        return set()
    return {x.split("#", 1)[0].strip().lower() for x in yol.read_text(encoding="utf-8").splitlines() if x.split("#", 1)[0].strip()}


# ------------------------------------------------------------------------------------------------------------------------------ saf ölçüler
def portfolio_serisi(portfolio: Any, alan: str, donem: str = "allTime") -> list[tuple[int, float]]:
    """HL `portfolio` yanıtından bir dönemin (`allTime`) `pnlHistory` / `accountValueHistory` noktaları [(ms, $)], zaman artan; biçim tanınmazsa []."""
    try:
        veri = dict(portfolio or []).get(donem) or {}
    except (TypeError, ValueError):
        return []
    out = []
    for nokta in veri.get(alan) or []:
        try:
            t, v = int(nokta[0]), float(nokta[1])
        except (TypeError, ValueError, IndexError):
            continue
        if math.isfinite(v):
            out.append((t, v))
    return sorted(out)


def deger(seri: list[tuple[int, float]], t: int) -> float | None:
    """t anında ya da öncesindeki son değer; t ilk noktadan önceyse None."""
    once = [v for z, v in seri if z <= t]
    return once[-1] if once else None


def seri_birlestir(portfolio: Any, donemler: tuple[str, ...], alan: str, goreli: bool) -> list[tuple[int, float]]:
    """K-65 tazelik: dönemleri kabadan inceye tek seride birleştirir; ince dönemin noktaları kendi ilk noktasından itibaren kaba serinin yerini alır (allTime seyrek, son noktası günler eski olabilir).
    `goreli` (pnlHistory): her dönem kendi başından sayar → ince dönem, birleşik serinin EN YENİ noktasında (ortak zaman) ona oturtulur (fark eklenir; seviye allTime'dan gelir);
    ince dönem o zamandan sonra başlıyorsa ilk noktası birleşik serinin o andaki değerine oturtulur. Hesap değeri (mutlak) aynen alınır."""
    birlesik: list[tuple[int, float]] = []
    for donem in donemler:
        ince = portfolio_serisi(portfolio, alan, donem)
        if not ince:
            continue
        if not birlesik:
            birlesik = ince
            continue
        fark = 0.0
        if goreli:
            ta, kv = birlesik[-1]
            iv = deger(ince, ta)
            if iv is not None:
                fark = kv - iv
            else:
                kv0 = deger(birlesik, ince[0][0])
                fark = (kv0 if kv0 is not None else 0.0) - ince[0][1]
        bas = ince[0][0]
        birlesik = [p for p in birlesik if p[0] < bas] + [(t, v + fark) for t, v in ince]
    return birlesik


def pnl_serisi(portfolio: Any) -> tuple[list[tuple[int, float]], str]:
    """K-65: kümülatif PERP pnl serisi (perpAllTime + perpMonth + perpWeek birleşik). Perp dönemleri yoksa (eski biçim) toplam seri; döner (seri, kaynak "perp" | "toplam")."""
    perp = seri_birlestir(portfolio, PNL_PERP, "pnlHistory", True)
    if perp:
        return perp, "perp"
    return seri_birlestir(portfolio, PNL_TOPLAM, "pnlHistory", True), "toplam"


def portfolio_olculeri(portfolio: Any, t_ms: int, rules: dict) -> dict:
    """B evreni ölçüleri (t'ye kadar): hesap, haftalık pnl/hesap dizisi (son `secim_hafta_sayisi`), pozitif hafta, 90 g pnl, 90 g pnl düşüşü/hesap, t-istatistiği, 30 g pnl,
    zirve düşüşü (kümülatif pnl zirvesinden bugüne / hesap). Veri yetersizse ilgili alan None.
    K-65: pnl yalnız perp (`pnl_serisi`), hesap toplam seriden (allTime + month + week birleşik); `omur_perp_pnl` = t'deki ömür boyu perp pnl, `veri_yas_saat` = t − en yeni pnl noktası (saat)."""
    pnl, kaynak = pnl_serisi(portfolio)
    hesap_s = seri_birlestir(portfolio, HESAP_DONEM, "accountValueHistory", False)
    hesap = deger(hesap_s, t_ms)
    n = int(rules["secim_hafta_sayisi"])
    haftalik = []
    for k in range(n, 0, -1):
        a, b = t_ms - k * HAFTA, t_ms - (k - 1) * HAFTA
        pa, pb, ha = deger(pnl, a), deger(pnl, b), deger(hesap_s, a)
        if pa is None or pb is None or not ha or ha <= 0:
            continue
        haftalik.append((pb - pa) / ha)
    p_t, p_90, p_30 = deger(pnl, t_ms), deger(pnl, t_ms - 90 * GUN), deger(pnl, t_ms - 30 * GUN)
    son90 = [v for z, v in pnl if t_ms - 90 * GUN <= z <= t_ms]
    dusus90, zirve = None, None
    if son90 and hesap and hesap > 0:
        tepe, en = son90[0], 0.0
        for v in son90:
            tepe = max(tepe, v)
            en = max(en, tepe - v)
        dusus90 = en / hesap
        tum = [v for z, v in pnl if z <= t_ms]
        zirve = (max(tum) - tum[-1]) / hesap if tum else None
    t_ist = None
    if len(haftalik) >= 2 and statistics.stdev(haftalik) > 0:
        t_ist = statistics.fmean(haftalik) / (statistics.stdev(haftalik) / math.sqrt(len(haftalik)))
    son_ms = max((z for z, _ in pnl if z <= t_ms), default=None)
    return {"hesap_usd": hesap, "pnl_kum": p_t, "hafta_sayisi": len(haftalik), "pozitif_hafta": sum(1 for x in haftalik if x > 0), "pnl_90g": None if p_t is None or p_90 is None else p_t - p_90,
            "pnl_30g": None if p_t is None or p_30 is None else p_t - p_30, "dusus_90g": dusus90, "zirve_dusus": zirve, "t_istat": t_ist,
            "pnl_kaynak": kaynak, "omur_perp_pnl": p_t, "veri_son_ms": son_ms, "veri_yas_saat": None if son_ms is None else (t_ms - son_ms) / HOUR}


def evren_kapisi(o: dict, rules: dict) -> str | None:
    """B evreni: ilk başarısız kuralın kodu ya da None (geçti)."""
    if not o.get("hesap_usd") or o["hesap_usd"] < float(rules["secim_min_hesap_usd"]):
        return "hesap_az"
    if o.get("veri_yas_saat") is None or o["veri_yas_saat"] > float(rules["secim_veri_azami_yas_saat"]) + 1e-12:      # K-65: en yeni pnl noktası eski → ölçüler bugünü göstermez
        return "veri_bayat"
    if o["hafta_sayisi"] < int(rules["secim_hafta_sayisi"]):
        return "gecmis_kisa"
    if o["pozitif_hafta"] < int(rules["secim_pozitif_hafta_min"]):
        return "istikrarsiz"
    if o["pnl_90g"] is None or o["pnl_90g"] <= 0:
        return "pnl_90g"
    if o["dusus_90g"] is None or o["dusus_90g"] > float(rules["secim_dusus_90g_max"]) + 1e-12:
        return "dusus_90g"
    if o["t_istat"] is None:
        return "t_yok"
    return None


def kopya_kapisi(dolumlar: list[dict], hesap: float, payda: Any, mum: Any, t0: int, t1: int, likit: set[str], azami: dict | None, rules: dict,
                 seri_zorla: bool = False) -> dict:
    """B kapıları (son `secim_kopya_gun` gün): R1 dolum ölçüleri + gecikmesiz/tam maliyetli kopya (kalicilik_testi.hafta_satiri ile aynı yaklaşım). Döner ölçüler + `neden` (None = geçti).
    `seri_zorla` (K-65 eki 13.11): ucuz kapı düşse de kopya canlandırması yapılır (üyenin benzerlik serisi `kopya_gunluk` için; `neden` yine ucuz kapının nedenidir)."""
    d = [f for f in perp_fills(dolumlar) if t0 <= int(f["time"]) < t1]
    if not d:
        return {"neden": "islem_yok"}
    hafta = (t1 - t0) / HAFTA
    o = radar_tarama.islem_olculeri(d, hesap, likit, rules)
    o["devir_hafta"] = sum(abs(float(f["px"]) * float(f["sz"])) for f in d) / hesap / hafta if hesap > 0 else None
    o["aktif_coin"] = len({str(f["coin"]) for f in d})
    ucuz = (("tutma_kisa", o.get("medyan_tutma_saat"), lambda v: v >= float(rules["radar_min_medyan_tutma_saat"])),
            ("kisa_islem_fazla", o.get("kisa_islem_payi"), lambda v: v <= float(rules["radar_kisa_islem_payi_max"])),           # D+ (A)
            ("coin_fazla", o.get("aktif_coin"), lambda v: v <= int(rules["secim_aktif_coin_max"])),                                # D+ (C)
            ("kaldirac_yuksek", o.get("max_kaldirac"), lambda v: v <= float(rules["radar_max_kaldirac"])),
            ("likidite_dusuk", o.get("likit_pay"), lambda v: v >= float(rules["radar_likit_pay_min"])),
            ("devir_yuksek", o.get("devir_hafta"), lambda v: v <= float(rules["radar_max_devir_hafta"])))
    o["neden"] = next((k for k, v, f in ucuz if v is None or not f(v)), None)
    if o["neden"] is not None and not seri_zorla:                           # ucuz kapı düştüyse pahalı kopya canlandırması yapılmaz (süre)
        return o
    ucuz_neden = o["neden"]
    s = kalicilik_testi.hafta_satiri("0x" + "0" * 40, d, hesap, payda, mum, t0, t1, likit, azami, rules)
    o.update({"kopya_getiri": s.get("kopya_getiri_7g"), "kopya_islem": s.get("kopya_islem_sayisi"), "kopya_koruma": s.get("kopya_koruma"), "kopya_gunluk": s.get("kopya_gunluk")})
    kural = (("kopya_zarar", o.get("kopya_getiri"), lambda v: v > 0),
             ("kopya_koruma_dusuk", o.get("kopya_koruma"), lambda v: v >= float(rules["radar_kopya_koruma_min"])),
             ("kopya_islem_az", o.get("kopya_islem"), lambda v: v >= int(rules["radar_min_kopya_islem"])))                           # D+ (A)
    o["neden"] = ucuz_neden or next((k for k, v, f in kural if v is None or not f(v)), None)
    return o


def motor_hesap_oku(client: Any, adres: str, dexler: list[str] | None) -> float | None:
    """K-65 ortak payda: canlı motorun trader hesap değeri TANIMI (`canli/motor.py` `hesap_degeri_oku`, K-35) — tüm perp dex `marginSummary.accountValue` + spot USDC.
    Aynı fonksiyon çağrılır (kural 7: hesap tek yerde). Dex listesi bilinmiyorsa None."""
    from copytrade.canli.motor import hesap_degeri_oku                     # tembel içe aktarma: motor modülü ağırdır
    return hesap_degeri_oku(lambda yuk: client.info(yuk, weight=2), adres, dexler)


def payda_karar(seri: float | None, motor: float | None, rules: dict) -> dict:
    """K-65: portfolio serisinin hesap değeri ↔ motor tanımı. |seri / motor − 1| > `secim_payda_azami_fark` (ya da seri yok) → motor değeri kullanılır (`payda_duzeltildi`); aday REDDEDİLMEZ.
    Motor okunamadıysa seri aynen (`payda_duzeltildi` false, oran None)."""
    if motor is None or not math.isfinite(float(motor)) or motor <= 0:
        return {"seri_hesap_usd": seri, "motor_hesap_usd": motor, "payda_oran": None, "payda_duzeltildi": False}
    oran = seri / motor if seri is not None and seri > 0 else None
    duz = oran is None or abs(oran - 1.0) > float(rules["secim_payda_azami_fark"]) + 1e-12
    return {"seri_hesap_usd": seri, "motor_hesap_usd": motor, "payda_oran": oran, "payda_duzeltildi": duz}


def payda_uygula(o: dict, karar: dict) -> dict:
    """Düzeltme varsa ölçüleri yerinde motor paydasına çevirir: `hesap_usd` = motor; hesaba bölünmüş düşüşler (90 g, zirve) seri/motor ile ölçeklenir. Karar alanları `o`ya yazılır."""
    o.update(karar)
    if karar["payda_duzeltildi"]:
        seri, motor = karar["seri_hesap_usd"], float(karar["motor_hesap_usd"])
        if seri is not None and seri > 0:
            for alan in ("dusus_90g", "zirve_dusus"):
                if o.get(alan) is not None:
                    o[alan] = o[alan] * float(seri) / motor
        o["hesap_usd"] = motor
    return o


def zarara_ekleme(dolumlar: list[dict], t0: int, t1: int, rules: dict) -> tuple[float, int]:
    """K-65 veto (b) ölçüsü: [t0, t1) perp dolumlarında zarardaki pozisyona aynı yönde ekleme payı ve ekleme sayısı (`olcut.martingale_ratio`, `martingale_min_adverse`)."""
    d = [f for f in perp_fills(dolumlar) if t0 <= int(f["time"]) < t1]
    return martingale_ratio(d, float(rules["martingale_min_adverse"]))


def veto_kodu(omur_pnl: float | None, oran: float | None, sayi: int | None, rules: dict) -> str | None:
    """K-65 geçici güvenlik kuralı: (a) ömür boyu perp pnl ≤ 0 → `veto_omur_zarar`; (b) ekleme ≥ `martingale_min_additions` VE pay ≥ `secim_veto_zarara_ekleme_oran` → `veto_zarara_ekleme`.
    Ölçülemeyen ölçü vetolamaz (None)."""
    if omur_pnl is not None and omur_pnl <= 0:
        return "veto_omur_zarar"
    if sayi is not None and oran is not None and sayi >= int(rules["martingale_min_additions"]) and oran >= float(rules["secim_veto_zarara_ekleme_oran"]) - 1e-12:
        return "veto_zarara_ekleme"
    return None


def uye_cikis(o: dict, son_islem_ms: int | None, simdi: int, ay_kontrol: bool, ay_negatif: int, rules: dict, giris: dict | None = None,
              slot_ay_net: float | None = None) -> tuple[str | None, int]:
    """Üye için risk çıkışı (yalnız bunlar; sıra çıkış nedeni değil). Döner (neden | None, yeni ay_negatif sayacı).
    `giris` = {hesap_usd, pnl_kum} (girişteki); `slot_ay_net` = bizim slotun son aylık kontrolden beri net K/Z'si ($; None → trader 30 g pnl yedeği)."""
    if o.get("zirve_dusus") is not None and o["zirve_dusus"] >= float(rules["secim_cikis_zirve_dusus"]) - 1e-12:
        return "zirve_dusus", ay_negatif
    if giris and giris.get("hesap_usd") and giris.get("pnl_kum") is not None and o.get("pnl_kum") is not None:
        if (giris["pnl_kum"] - o["pnl_kum"]) / float(giris["hesap_usd"]) >= float(rules["secim_cikis_giris_dusus"]) - 1e-12:
            return "giris_dusus", ay_negatif
    if son_islem_ms is None or simdi - son_islem_ms >= int(rules["secim_islem_yok_gun"]) * GUN:
        return "islem_yok", ay_negatif
    if ay_kontrol:
        olcu = slot_ay_net if slot_ay_net is not None else o.get("pnl_30g")
        ay_negatif = ay_negatif + 1 if (olcu is not None and olcu < 0) else 0
        if ay_negatif >= 2:
            return "ay_negatif", ay_negatif
    return None, ay_negatif


def slot_net(hesap: dict | None, adres: str) -> float | None:
    """Motor `durum/hesap.json`'dan bu üyenin girişten beri gerçekleşmiş net K/Z'si (realize − ücret + funding); kayıt yoksa None."""
    if not hesap or adres not in (hesap.get("realize") or {}):
        return None
    return float(hesap["realize"].get(adres, 0.0)) - float((hesap.get("ucret") or {}).get(adres, 0.0)) + float((hesap.get("funding") or {}).get(adres, 0.0))


def _sayi_mi(x: Any) -> bool:
    try:
        float(x)
        return True
    except (TypeError, ValueError):
        return False


def doldurma_mi(onceki: dict | None, simdi: int) -> bool:
    """İlk koşu (v2 kadro yok), ayın ilk koşusu (önceki kadronun `doldurma_ay`'ı bu ay değil) ya da kadro tamamen boş
    (09.11 dal denemesi: ilk doldurma 0/5 kaldı → ay sonuna dek boş beklenmez; kısmen dolu kadroda boş slot ay başına dek nakit, K-33)."""
    ay = datetime.fromtimestamp(simdi / 1000, UTC).strftime("%Y-%m")
    return not onceki or onceki.get("radar_surum") != SURUM or onceki.get("doldurma_ay") != ay or not onceki.get("satirlar")


def on_filtre(satirlar: list[dict], rules: dict) -> list[dict]:
    """Lider tablosundan ucuz ön filtre (portfolio çağrısından önce): hesap ≥ eşik, 30 g pnl > 0, 30 g hacim > 0. Hesap azalan (bütçe kesilirse büyükler ölçülmüş olur)."""
    out = []
    for s in satirlar:
        a, h = _address(s), radar_tarama._sayi(s.get("accountValue", s.get("account_value")))
        ap, av = radar_tarama.ay_pnl(s), _window(s, "month", "vlm")
        if a and h is not None and h >= float(rules["secim_min_hesap_usd"]) and ap is not None and ap > 0 and av > 0:
            out.append({"adres": a, "hesap_usd": h})
    return sorted(out, key=lambda x: (-x["hesap_usd"], x["adres"]))


def kadro_yaz(uyeler: list[dict], simdi: int, rules: dict, doldurma_ay: str, cikanlar: dict[str, str]) -> dict:
    kasa = float(rules["canli_kasa_usd"])
    satirlar = [{"adres": u["adres"], "sira": i, "katman": "ilk11", "form": u.get("t_istat") or 0.0, "bilesenler": {}, "kopya_getiri_7g": u.get("kopya_getiri"),
                 "max_kaldirac": u.get("max_kaldirac"), "giris_ms": u.get("giris_ms"), "ay_negatif": u.get("ay_negatif", 0), "giris_hesap_usd": u.get("giris_hesap_usd"),
                 "giris_pnl_kum": u.get("giris_pnl_kum"), "zirve_pnl": u.get("zirve_pnl"), "sicil_onceki": u.get("sicil_onceki"), "kopya_gunluk": u.get("kopya_gunluk")} for i, u in enumerate(uyeler, 1)]
    kor = radar_form.korelasyon([{"adres": u["adres"], "kopya_gunluk": u.get("kopya_gunluk")} for u in uyeler]) if uyeler else {"adresler": [], "gun_sayisi": 0, "matris": []}
    return {"sema": "radar-kadro-v1", "radar_surum": SURUM, "secim_yapi": "D", "kosu_ms": simdi, "kasa_usd": kasa, "slot_usd": boyut.slot_usd(kasa, rules),
            "saha_n": boyut.saha_sayisi(kasa, rules), "gecti_sayisi": len(uyeler), "soguyan": [], "satirlar": satirlar, "korelasyon": kor,
            "doldurma_ay": doldurma_ay, "cikanlar": cikanlar}


# ------------------------------------------------------------------------------------------------------------------------------ koşu (ağ)
def _motor_payda(client: Any, adres: str, dexler: list[str] | None, o: dict, rules: dict) -> dict:
    """Motor tanımıyla hesap değerini okur (yalnız kopya kapısına gelen aday ve üye: istek sayısı) ve `payda_uygula` ile `o`ya işler. Okuma hatası seçimi bozmaz (seri kullanılır)."""
    try:
        motor = motor_hesap_oku(client, adres, dexler)
        hata = None
    except Exception as h:                                                  # noqa: BLE001 — yalnız payda düzeltmesi; okunamazsa seri değeri (eski davranış), hata türü kaydedilir
        motor, hata = None, type(h).__name__
    payda_uygula(o, payda_karar(o.get("hesap_usd"), motor, rules))
    if hata:
        o["motor_hesap_hata"] = hata
    return o


def _bos_veto(o: dict | None = None, rules: dict | None = None) -> dict:
    omur = (o or {}).get("omur_perp_pnl")
    return {"omur_perp_pnl": omur, "zarara_ekleme_oran": None, "zarara_ekleme_sayi": None, "veto": veto_kodu(omur, None, None, rules) if rules else None}


def kos(client: Any, simdi: int, onceki: dict | None, rules: dict, log=print, saat=time.monotonic, canli: dict | None = None,
        haric: set[str] | None = None) -> tuple[dict, dict]:
    """Döner (havuz, kadro). `canli` = {"hesap": motor durum/hesap.json, "saha": durum/saha.json} (D+ slot sicili ve motor düşürmesi; yoksa yedekler).
    `haric` = kullanıcının elle çıkardığı adresler (`copytrade/radar/HARIC`): üyeyse `elle_cikarildi` ile çıkar, aday olmaz; boşalan yer AYNI koşuda doldurulur.
    K-65 vetoları (kapılardan sonra): bu koşuda kapıları + iki vetoyu geçen aday < `secim_veto_min_aday` ise vetolar askıya alınır (eski davranış). Üye vetosu: doldurma koşusunda bu koşunun
    sayısıyla, değilse önceki kadronun `veto_havuz` sayısıyla (bilinmiyorsa uygulanır) karar verilir; vetoyla çıkan üyenin yeri elle çıkarma gibi AYNI koşuda doldurulur."""
    haric = {x.lower() for x in (haric or set())}
    t0_kos = saat()
    n = boyut.saha_sayisi(float(rules["canli_kasa_usd"]), rules)
    kopya_bas = simdi - int(rules["secim_kopya_gun"]) * GUN
    b = radar_tarama.Baglam(client, simdi, kopya_bas, rules)
    b.piyasa_oku()
    likit, mum = b.likit_coinler(), kalicilik_testi.SaatlikMum(client, kopya_bas, simdi)
    ay = datetime.fromtimestamp(simdi / 1000, UTC).strftime("%Y-%m")
    doldur = doldurma_mi(onceki, simdi)
    ay_kontrol = doldur and bool(onceki) and onceki.get("radar_surum") == SURUM
    veto_acik, veto_min = bool(rules["secim_veto_acik"]), int(rules["secim_veto_min_aday"])
    onceki_veto = (onceki or {}).get("veto_havuz") or {}
    goc = int((onceki or {}).get("veri_surum") or 1) < VERI_SURUM           # K-65: önceki kadro TOPLAM pnl ile yazıldı → üyenin giriş/zirve pnl'i perp seriden yeniden kurulur
    tavan = int(rules["radar_dolum_tavan"])
    satirlar: list[dict] = []
    uyeler, cikanlar, olcu = [], {}, []
    bekleyen: dict[str, str] = {}                                           # risk çıkışı olmayan ama veto kodu taşıyan üyeler (adres → kod); karar aşağıda
    uye_satir: dict[str, dict] = {}
    tarama: dict = {"on_filtre": 0, "olculen": 0, "portfolio_hata": 0, "hata_tur": {}, "butce_disi": 0}        # F14: denenen / hata / bütçe dışı sayaçları
    canli = canli or {}
    bekleme = {a for a, bit in ((canli.get("saha") or {}).get("bekleme") or {}).items() if _sayi_mi(bit) and float(bit) > simdi}   # denetim 4: süresi dolmuş ceza sayılmaz
    gecmis = {a: int(t) for a, t in ((onceki or {}).get("cikanlar_gecmis") or {}).items() if simdi - int(t) < int(rules["canli_bekleme_gun"]) * GUN}
    for u in (onceki or {}).get("satirlar", []) if (onceki or {}).get("radar_surum") == SURUM else []:
        a = u["adres"]
        if a.lower() in haric:                                              # kullanıcı kararı (10.11): elle çıkarma; yakın çıkan sayılır, geri girmez
            cikanlar[a] = "elle_cikarildi"
            gecmis[a] = simdi
            satirlar.append({"adres": a, "tur": "uye", "neden": "elle_cikarildi"})
            log(f"çıkış {a[:10]}… elle_cikarildi")
            continue
        if a in bekleme:                                                    # D+: motor cezayla düşürdü → kadrodan da düşer (31 g sonra geri girme döngüsü yok)
            cikanlar[a] = "motor_dustu"
            gecmis[a] = simdi
            satirlar.append({"adres": a, "tur": "uye", "neden": "motor_dustu"})
            log(f"çıkış {a[:10]}… motor_dustu")
            continue
        try:
            pf = client.portfolio(a)
            o = portfolio_olculeri(pf, simdi, rules)
            d = perp_fills(client.fills(a, simdi - int(rules["secim_islem_yok_gun"]) * GUN, max_rows=tavan, end_ms=simdi))
            son = max((int(f["time"]) for f in d), default=None)
        except radar_tarama.HATALAR as h:
            log(f"UYARI: üye {a[:10]}… okunamadı ({type(h).__name__}); kadroda kalır")
            uyeler.append({**u, "t_istat": u.get("form"), "kopya_getiri": u.get("kopya_getiri_7g")})
            satirlar.append({"adres": a, "tur": "uye", **_bos_veto(), "neden": None, "hata": type(h).__name__})
            continue
        _motor_payda(client, a, b.dexler, o, rules)
        if goc and u.get("giris_ms") is not None:                          # K-65 göç: giriş ve zirve pnl'i perp seriden (çıkış ölçüsü aynı tabanda kalsın)
            seri, _ = pnl_serisi(pf)
            gp = deger(seri, int(u["giris_ms"]))
            if gp is not None:
                zp = max([v for z, v in seri if int(u["giris_ms"]) <= z <= simdi] + [gp])
                u = {**u, "giris_pnl_kum": gp, "zirve_pnl": zp}
                o["veri_gocu"] = True
        if o.get("pnl_kum") is not None and u.get("giris_hesap_usd"):            # denetim 1: zirve GİRİŞİMİZDEN beri (tüm-zaman tepesi değil)
            zp = max(float(u.get("zirve_pnl") if u.get("zirve_pnl") is not None else (u.get("giris_pnl_kum") or o["pnl_kum"])), float(o["pnl_kum"]))
            o["zirve_pnl"], o["zirve_dusus"] = zp, (zp - float(o["pnl_kum"])) / float(u["giris_hesap_usd"])
        else:
            o["zirve_dusus"] = None
        vo = _bos_veto(o, rules)
        try:                                                                # veto (b): kopya kapısıyla aynı pencere (son `secim_kopya_gun` gün)
            z_oran, z_sayi = zarara_ekleme(client.fills(a, kopya_bas, max_rows=tavan * 4, end_ms=simdi), kopya_bas, simdi, rules)
            vo.update({"zarara_ekleme_oran": z_oran, "zarara_ekleme_sayi": z_sayi, "veto": veto_kodu(o.get("omur_perp_pnl"), z_oran, z_sayi, rules)})
        except radar_tarama.HATALAR as h:
            vo["zarara_ekleme_hata"] = type(h).__name__
        sicil = slot_net(canli.get("hesap"), a)
        ay_net = None if sicil is None else sicil - float(u.get("sicil_onceki") or 0.0)
        giris = {"hesap_usd": u.get("giris_hesap_usd"), "pnl_kum": u.get("giris_pnl_kum")}
        neden, ayn = uye_cikis(o, son, simdi, ay_kontrol, int(u.get("ay_negatif") or 0), rules, giris, ay_net)
        satir = {"adres": a, "tur": "uye", **o, **vo, "neden": neden}
        satirlar.append(satir)
        if neden:
            cikanlar[a] = neden
            gecmis[a] = simdi
            log(f"çıkış {a[:10]}… {neden}")
        else:
            yeni_sicil = sicil if (ay_kontrol and sicil is not None) else u.get("sicil_onceki")
            uyeler.append({**u, **o, "t_istat": u.get("form"), "kopya_getiri": u.get("kopya_getiri_7g"), "ay_negatif": ayn, "sicil_onceki": yeni_sicil})
            if vo["veto"]:
                bekleyen[a], uye_satir[a] = vo["veto"], satir

    veto: dict = {"acik": veto_acik, "min_aday": veto_min, "sayi": None, "askida": None, "kaynak": None, "uye_kaynak": None, "uye_sayi": None}

    def veto_cikar(kodlar: dict[str, str]) -> None:
        """Vetolu üyeleri çıkarır (yakın çıkan sayılır; yer aynı koşuda dolar)."""
        for a, kod in kodlar.items():
            cikanlar[a] = kod
            gecmis[a] = simdi
            uye_satir[a]["neden"] = kod
            log(f"çıkış {a[:10]}… {kod}")
        uyeler[:] = [x for x in uyeler if x["adres"] not in kodlar]

    if "elle_cikarildi" in cikanlar.values():                                # elle çıkarılan yer ay başını beklemez
        doldur = True
    if veto_acik and bekleyen and not doldur:                               # doldurmasız gün: en son bilinen havuz sayısı (yoksa veto yine uygulanır, kaydedilir)
        onceki_sayi = onceki_veto.get("sayi")
        veto.update({"uye_kaynak": "onceki" if onceki_sayi is not None else "bilinmiyor", "uye_sayi": onceki_sayi})
        if onceki_sayi is None or int(onceki_sayi) >= veto_min:
            veto_cikar(bekleyen)
            doldur = True                                                   # vetoyla boşalan yer elle çıkarma gibi AYNI koşuda dolar
        bekleyen = {}
    ertelenen = dict(bekleyen) if veto_acik else {}                         # doldurma koşusu: üye vetosu bu koşunun aday sayısıyla verilir
    if doldur and (len(uyeler) < n or ertelenen):
        tablo = client.leaderboard()
        dislanan = {u["adres"] for u in uyeler} | set(cikanlar) | set(gecmis) | bekleme | haric                  # denetim 4: cezalı / yakın zamanda çıkan aday olmaz
        aday = [x for x in on_filtre(tablo, rules) if x["adres"] not in dislanan]
        log(f"doldurma: boş {n - len(uyeler)}, lider tablosu {len(tablo)}, ön filtre {len(aday)}")
        butce = float(rules["secim_butce_dk"]) * 60
        tarama.update({"on_filtre": len(aday)})
        for i, x in enumerate(aday, 1):
            if saat() - t0_kos > butce:
                log(f"UYARI: süre bütçesi doldu; {len(aday) - i + 1} adres ölçülmedi")
                tarama["butce_disi"] = len(aday) - i + 1
                break
            try:
                pf = client.portfolio(x["adres"])
                o = portfolio_olculeri(pf, simdi, rules)
            except radar_tarama.HATALAR as h:                               # F14 (denetim 10.11): okuma hatası sayılır (havuz.json `tarama`)
                tarama["portfolio_hata"] += 1
                tarama["hata_tur"][type(h).__name__] = tarama["hata_tur"].get(type(h).__name__, 0) + 1
                continue
            tarama["olculen"] += 1
            neden = evren_kapisi(o, rules)
            if neden is None:
                olcu.append({"adres": x["adres"], **o, "_pf": pf})
            if i % 200 == 0:
                log(f"[{i}/{len(aday)}] B evreni {len(olcu)}; {(saat() - t0_kos) / 60:.1f} dk")
        olcu.sort(key=lambda o: (-o["t_istat"], o["adres"]))
        bos_eski = n - len(uyeler)                                          # vetosuz (askıda) senaryo: bekleyen üyeler kalır
        bos_yeni = bos_eski + len(ertelenen)
        log(f"B evreni: {len(olcu)} kişi; kopya kapısı t sırasıyla, boş {bos_eski}" + (f" (vetoyla {bos_yeni}; veto havuzu ≥ {veto_min} aranır)" if veto_acik else "")
            + f" (en çok {rules['secim_aday_ust']})")
        gecen: list[tuple[dict, dict]] = []                                 # kapıları geçenler (havuz satırı, üye kaydı), t sırasıyla

        def yeter() -> bool:
            if len(gecen) < bos_eski:
                return False
            return not veto_acik or sum(1 for s_, _ in gecen if s_["veto"] is None) >= max(bos_yeni, veto_min)

        kopya_butce = butce + float(rules["secim_kopya_butce_dk"]) * 60          # denetim 2: kopya kapısı döngüsünün de süre sınırı var (iş zaman aşımı 180 dk)
        for o in olcu[: int(rules["secim_aday_ust"])]:
            if yeter():
                break
            if saat() - t0_kos > kopya_butce:
                log("UYARI: kopya kapısı süre bütçesi doldu; kalan adaylar ölçülmedi")
                break
            pf = o.pop("_pf", None)
            a = o["adres"]
            vo = _bos_veto(o, rules)
            try:
                d = client.fills(a, kopya_bas, max_rows=tavan * 4, end_ms=simdi)
                if len(d) >= tavan * 4:
                    satirlar.append({"adres": a, "tur": "aday", **o, **vo, "neden": "dolum_fazla"})
                    continue
                _motor_payda(client, a, b.dexler, o, rules)                 # K-65: yalnız kopya kapısına gelen aday için durum okuması
                if o["payda_duzeltildi"] and (ne := evren_kapisi(o, rules)):  # motor paydasıyla evren kapısı yeniden (hesap / düşüş oranları)
                    satirlar.append({"adres": a, "tur": "aday", **o, **vo, "neden": ne})
                    continue
                try:
                    noktalar = radar_tarama.payda_noktalari(pf, simdi)
                    if o["payda_duzeltildi"] and o.get("seri_hesap_usd"):    # seri motor tanımından saptı: seri şekli korunur, seviye motor değerine ölçeklenir
                        k_ = float(o["motor_hesap_usd"]) / float(o["seri_hesap_usd"])
                        noktalar = [(t_, v_ * k_) for t_, v_ in noktalar]
                    payda = kopya_v5.PaydaSerisi(noktalar)
                except (*radar_tarama.HATALAR, AttributeError):
                    payda = o["hesap_usd"]
                k = kopya_kapisi(d, o["hesap_usd"], payda, mum, kopya_bas, simdi, likit, b.azami_kaldirac, rules)
                z_oran, z_sayi = zarara_ekleme(d, kopya_bas, simdi, rules)
            except radar_tarama.HATALAR as h:
                satirlar.append({"adres": a, "tur": "aday", **o, **vo, "neden": "veri_hatasi", "hata": type(h).__name__})
                continue
            vo.update({"zarara_ekleme_oran": z_oran, "zarara_ekleme_sayi": z_sayi, "veto": veto_kodu(o.get("omur_perp_pnl"), z_oran, z_sayi, rules)})
            satir = {"adres": a, "tur": "aday", **o, **k, **vo}
            satirlar.append(satir)
            if k["neden"] is None:
                gecen.append((satir, {"adres": a, **o, **k, "giris_ms": simdi, "ay_negatif": 0, "giris_hesap_usd": o["hesap_usd"], "giris_pnl_kum": o.get("pnl_kum"),
                                      "zirve_pnl": o.get("pnl_kum"), "sicil_onceki": 0.0}))
        sayi = sum(1 for s_, _ in gecen if s_["veto"] is None)
        aktif = veto_acik and sayi >= veto_min
        veto.update({"sayi": sayi, "askida": veto_acik and not aktif, "kaynak": "bu_kosu"})
        if veto_acik and not aktif:
            log(f"UYARI: veto havuzu {sayi} < {veto_min}: vetolar bu koşu askıda (eski davranış)")
        if ertelenen:
            veto.update({"uye_kaynak": "bu_kosu", "uye_sayi": sayi})
            if aktif:
                veto_cikar(ertelenen)
        for satir, yeni in gecen:
            if aktif and satir["veto"]:
                satir["neden"], satir["secildi"] = satir["veto"], False
                continue
            satir["secildi"] = len(uyeler) < n
            if satir["secildi"]:
                uyeler.append(yeni)
                log(f"giriş {yeni['adres'][:10]}… t {yeni['t_istat']:.2f}, kopya {yeni['kopya_getiri']:+.4f}")
        for u in uyeler:                                                    # denetim 3: benzerlik matrisi aynı 28 g penceresiyle (kalan üyelerin serisi yenilenir)
            if u.get("giris_ms") == simdi:
                continue
            try:                                                            # K-65 eki (13.11): seri ucuz kapıdan bağımsız (üye kapıya takılsa da ölçülür); okunamazsa önceki seri korunur
                d = client.fills(u["adres"], kopya_bas, max_rows=tavan * 4, end_ms=simdi)
                u["kopya_gunluk"] = kopya_kapisi(d, float(u.get("hesap_usd") or u.get("giris_hesap_usd") or 0.0) or 1.0, float(u.get("hesap_usd") or 1.0), mum,
                                                 kopya_bas, simdi, likit, b.azami_kaldirac, rules, seri_zorla=True).get("kopya_gunluk")
            except radar_tarama.HATALAR:
                pass
    for o in olcu:
        o.pop("_pf", None)
    havuz = {"sema": HAVUZ_SEMA, "veri_surum": VERI_SURUM, "kosu_ms": simdi, "pencere_bas_ms": kopya_bas, "doldurma": doldur, "satirlar": satirlar, "tarama": tarama,
             "veto": veto, "veto_askida": veto["askida"] is True, "veto_sayi": veto["sayi"]}
    kadro = kadro_yaz(uyeler, simdi, rules, ay if doldur else (onceki or {}).get("doldurma_ay", ay), cikanlar)
    kadro["cikanlar_gecmis"] = gecmis
    kadro["veri_surum"] = VERI_SURUM
    kadro["veto_havuz"] = ({"sayi": veto["sayi"], "askida": veto["askida"], "kosu_ms": simdi} if veto["kaynak"] == "bu_kosu" else onceki_veto) or None
    return havuz, kadro


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cikti", type=Path, default=Path("radar"))
    ap.add_argument("--onceki-kadro", type=Path, default=None)
    ap.add_argument("--canli-hesap", type=Path, default=None, help="D+: motor durum/hesap.json (slot sicili)")
    ap.add_argument("--canli-saha", type=Path, default=None, help="D+: motor durum/saha.json (cezalı düşenler)")
    a = ap.parse_args(argv)
    rules = load_rules()
    onceki = json.loads(a.onceki_kadro.read_text(encoding="utf-8")) if a.onceki_kadro else None
    simdi = int(time.time() * 1000)
    canli = {k: json.loads(p.read_text(encoding="utf-8")) for k, p in (("hesap", a.canli_hesap), ("saha", a.canli_saha)) if p and p.exists()}
    havuz, kadro = kos(radar_tarama.radar_istemcisi(rules=rules), simdi, onceki, rules, canli=canli, haric=haric_oku())
    klasor = a.cikti / datetime.fromtimestamp(simdi / 1000, UTC).date().isoformat()
    klasor.mkdir(parents=True, exist_ok=True)
    for ad, veri in (("havuz.json", havuz), ("kadro.json", kadro)):
        gecici = klasor / (ad + ".tmp")
        gecici.write_text(json.dumps(veri, ensure_ascii=False, indent=1, allow_nan=False, default=str) + "\n", encoding="utf-8")
        gecici.replace(klasor / ad)
    print(f"seçim D: kadro {len(kadro['satirlar'])}/{kadro['saha_n']} (doldurma {havuz['doldurma']}), çıkan {len(kadro['cikanlar'])} → {klasor}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
