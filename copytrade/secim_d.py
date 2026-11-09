"""Seçim yapısı D — sabit kadro, yalnız risk çıkışı (K-55, kullanıcı kararı 09.11; ön kayıt `docs/ONKAYIT_SECIM_2026-11-09.md` §1 D + B evreni).

Ön kaydın "fark kanıtlanamazsa en sade" sırasında ilk sıradaki yapı teoride seçildi (kullanıcı geriye dönük sınamayı beklemek istemedi). Günlük koşu (`radar.yml`):
1. **Üye denetimi (her gün):** önceki v2 kadrosunun üyeleri için `portfolio` + son `secim_islem_yok_gun` gün dolumu → çıkış yalnız risk nedeniyle:
   hesap pnl'i zirveden ≥ `secim_cikis_zirve_dusus` × hesap; `secim_islem_yok_gun` gün işlem yok; aylık kontrolde 30 g pnl < 0 iki ay üst üste. (Slot stop %15 ve kaldıraç motorda: `canli_slot_dusus_oran`.)
2. **Doldurma (ilk koşu ve ayın ilk koşusu):** lider tablosunun tamamı → ucuz ön filtre (hesap ≥ `secim_min_hesap_usd`, ay pnl > 0, ay hacmi > 0) → `portfolio` (B evreni):
   son `secim_hafta_sayisi` haftanın ≥ `secim_pozitif_hafta_min`'i pnl > 0, 90 g pnl > 0, 90 g pnl düşüşü ≤ `secim_dusus_90g_max` × hesap → haftalık getiri t-istatistiğine göre
   azalan ilk `secim_aday_ust` kişi için son `secim_kopya_gun` günün dolumları (B kapıları): medyan tutma ≥ 1 sa, kaldıraç ≤ 20x, likit pay ≥ %80, haftalık devir ≤ 100,
   kopya (gecikmesiz + tam maliyet, saatlik işaret) getirisi > 0 ve koruma ≥ 0,5 → boş koltuklar t sırasıyla dolar. Boş kalan koltuk nakit.
3. Çıktı: `radar/<tarih>/havuz.json` (`secim-d-havuz-v1`, ölçüler) + `kadro.json` (`radar-kadro-v1` biçimi, `radar_surum: v2`; motor K-54 ile yalnız bunu uygular).
Değiştirme YOK (sıra değişimi çıkış nedeni değil). Eşikler `kurallar.yaml` `secim_*`; kodda sayı yok.

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

from copytrade import boyut, kalicilik_testi, kopya_v5, radar_tarama
from copytrade.defter import HOUR
from copytrade.kurallar import load_rules
from copytrade.olcut import perp_fills
from copytrade.tarama import _address, _window

GUN = 24 * HOUR
HAFTA = 7 * GUN
SURUM = "v2"
HAVUZ_SEMA = "secim-d-havuz-v1"


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


def portfolio_olculeri(portfolio: Any, t_ms: int, rules: dict) -> dict:
    """B evreni ölçüleri (t'ye kadar): hesap, haftalık pnl/hesap dizisi (son `secim_hafta_sayisi`), pozitif hafta, 90 g pnl, 90 g pnl düşüşü/hesap, t-istatistiği, 30 g pnl,
    zirve düşüşü (kümülatif pnl zirvesinden bugüne / hesap). Veri yetersizse ilgili alan None."""
    pnl, hesap_s = portfolio_serisi(portfolio, "pnlHistory"), portfolio_serisi(portfolio, "accountValueHistory")
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
    return {"hesap_usd": hesap, "hafta_sayisi": len(haftalik), "pozitif_hafta": sum(1 for x in haftalik if x > 0), "pnl_90g": None if p_t is None or p_90 is None else p_t - p_90,
            "pnl_30g": None if p_t is None or p_30 is None else p_t - p_30, "dusus_90g": dusus90, "zirve_dusus": zirve, "t_istat": t_ist}


def evren_kapisi(o: dict, rules: dict) -> str | None:
    """B evreni: ilk başarısız kuralın kodu ya da None (geçti)."""
    if not o.get("hesap_usd") or o["hesap_usd"] < float(rules["secim_min_hesap_usd"]):
        return "hesap_az"
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


def kopya_kapisi(dolumlar: list[dict], hesap: float, payda: Any, mum: Any, t0: int, t1: int, likit: set[str], azami: dict | None, rules: dict) -> dict:
    """B kapıları (son `secim_kopya_gun` gün): R1 dolum ölçüleri + gecikmesiz/tam maliyetli kopya (kalicilik_testi.hafta_satiri ile aynı yaklaşım). Döner ölçüler + `neden` (None = geçti)."""
    d = [f for f in perp_fills(dolumlar) if t0 <= int(f["time"]) < t1]
    if not d:
        return {"neden": "islem_yok"}
    hafta = (t1 - t0) / HAFTA
    o = radar_tarama.islem_olculeri(d, hesap, likit, rules)
    o["devir_hafta"] = sum(abs(float(f["px"]) * float(f["sz"])) for f in d) / hesap / hafta if hesap > 0 else None
    s = kalicilik_testi.hafta_satiri("0x" + "0" * 40, d, hesap, payda, mum, t0, t1, likit, azami, rules)
    o.update({"kopya_getiri": s.get("kopya_getiri_7g"), "kopya_islem": s.get("kopya_islem_sayisi")})
    o["kopya_koruma"] = s.get("kopya_koruma")
    kural = (("tutma_kisa", o.get("medyan_tutma_saat"), lambda v: v >= float(rules["radar_min_medyan_tutma_saat"])),
             ("kaldirac_yuksek", o.get("max_kaldirac"), lambda v: v <= float(rules["radar_max_kaldirac"])),
             ("likidite_dusuk", o.get("likit_pay"), lambda v: v >= float(rules["radar_likit_pay_min"])),
             ("devir_yuksek", o.get("devir_hafta"), lambda v: v <= float(rules["radar_max_devir_hafta"])),
             ("kopya_zarar", o.get("kopya_getiri"), lambda v: v > 0),
             ("kopya_koruma_dusuk", o.get("kopya_koruma"), lambda v: v >= float(rules["radar_kopya_koruma_min"])))
    o["neden"] = next((k for k, v, f in kural if v is None or not f(v)), None)
    return o


def uye_cikis(o: dict, son_islem_ms: int | None, simdi: int, ay_kontrol: bool, ay_negatif: int, rules: dict) -> tuple[str | None, int]:
    """Üye için risk çıkışı (yalnız bunlar; sıra çıkış nedeni değil). Döner (neden | None, yeni ay_negatif sayacı)."""
    if o.get("zirve_dusus") is not None and o["zirve_dusus"] >= float(rules["secim_cikis_zirve_dusus"]) - 1e-12:
        return "zirve_dusus", ay_negatif
    if son_islem_ms is None or simdi - son_islem_ms >= int(rules["secim_islem_yok_gun"]) * GUN:
        return "islem_yok", ay_negatif
    if ay_kontrol:
        ay_negatif = ay_negatif + 1 if (o.get("pnl_30g") is not None and o["pnl_30g"] < 0) else 0
        if ay_negatif >= 2:
            return "ay_pnl_negatif", ay_negatif
    return None, ay_negatif


def doldurma_mi(onceki: dict | None, simdi: int) -> bool:
    """İlk koşu (v2 kadro yok) ya da ayın ilk koşusu (önceki kadronun `doldurma_ay`'ı bu ay değil)."""
    ay = datetime.fromtimestamp(simdi / 1000, UTC).strftime("%Y-%m")
    return not onceki or onceki.get("radar_surum") != SURUM or onceki.get("doldurma_ay") != ay


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
                 "max_kaldirac": u.get("max_kaldirac"), "giris_ms": u.get("giris_ms"), "ay_negatif": u.get("ay_negatif", 0)} for i, u in enumerate(uyeler, 1)]
    return {"sema": "radar-kadro-v1", "radar_surum": SURUM, "secim_yapi": "D", "kosu_ms": simdi, "kasa_usd": kasa, "slot_usd": boyut.slot_usd(kasa, rules),
            "saha_n": boyut.saha_sayisi(kasa, rules), "gecti_sayisi": len(uyeler), "soguyan": [], "satirlar": satirlar, "korelasyon": {"adresler": [], "gun_sayisi": 0, "matris": []},
            "doldurma_ay": doldurma_ay, "cikanlar": cikanlar}


# ------------------------------------------------------------------------------------------------------------------------------ koşu (ağ)
def kos(client: Any, simdi: int, onceki: dict | None, rules: dict, log=print, saat=time.monotonic) -> tuple[dict, dict]:
    """Döner (havuz, kadro)."""
    t0_kos = saat()
    n = boyut.saha_sayisi(float(rules["canli_kasa_usd"]), rules)
    kopya_bas = simdi - int(rules["secim_kopya_gun"]) * GUN
    b = radar_tarama.Baglam(client, simdi, kopya_bas, rules)
    b.piyasa_oku()
    likit, mum = b.likit_coinler(), kalicilik_testi.SaatlikMum(client, kopya_bas, simdi)
    ay = datetime.fromtimestamp(simdi / 1000, UTC).strftime("%Y-%m")
    doldur = doldurma_mi(onceki, simdi)
    ay_kontrol = doldur and bool(onceki) and onceki.get("radar_surum") == SURUM
    satirlar: list[dict] = []
    uyeler, cikanlar = [], {}
    for u in (onceki or {}).get("satirlar", []) if (onceki or {}).get("radar_surum") == SURUM else []:
        a = u["adres"]
        try:
            pf = client.portfolio(a)
            o = portfolio_olculeri(pf, simdi, rules)
            d = perp_fills(client.fills(a, simdi - int(rules["secim_islem_yok_gun"]) * GUN, max_rows=int(rules["radar_dolum_tavan"]), end_ms=simdi))
            son = max((int(f["time"]) for f in d), default=None)
        except radar_tarama.HATALAR as h:
            log(f"UYARI: üye {a[:10]}… okunamadı ({type(h).__name__}); kadroda kalır")
            uyeler.append(dict(u))
            continue
        neden, ayn = uye_cikis(o, son, simdi, ay_kontrol, int(u.get("ay_negatif") or 0), rules)
        satirlar.append({"adres": a, "tur": "uye", **o, "neden": neden})
        if neden:
            cikanlar[a] = neden
            log(f"çıkış {a[:10]}… {neden}")
        else:
            uyeler.append({**u, **o, "t_istat": u.get("form"), "kopya_getiri": u.get("kopya_getiri_7g"), "ay_negatif": ayn})
    if doldur and len(uyeler) < n:
        tablo = client.leaderboard()
        aday = [x for x in on_filtre(tablo, rules) if x["adres"] not in {u["adres"] for u in uyeler} and x["adres"] not in cikanlar]
        log(f"doldurma: boş {n - len(uyeler)}, lider tablosu {len(tablo)}, ön filtre {len(aday)}")
        butce = float(rules["secim_butce_dk"]) * 60
        olcu = []
        for i, x in enumerate(aday, 1):
            if saat() - t0_kos > butce:
                log(f"UYARI: süre bütçesi doldu; {len(aday) - i + 1} adres ölçülmedi")
                break
            try:
                o = portfolio_olculeri(client.portfolio(x["adres"]), simdi, rules)
            except radar_tarama.HATALAR:
                continue
            neden = evren_kapisi(o, rules)
            if neden is None:
                olcu.append({"adres": x["adres"], **o})
            if i % 200 == 0:
                log(f"[{i}/{len(aday)}] B evreni {len(olcu)}; {(saat() - t0_kos) / 60:.1f} dk")
        olcu.sort(key=lambda o: (-o["t_istat"], o["adres"]))
        log(f"B evreni: {len(olcu)} kişi; kopya kapısına ilk {rules['secim_aday_ust']}")
        for o in olcu[: int(rules["secim_aday_ust"])]:
            if len(uyeler) >= n:
                break
            a = o["adres"]
            try:
                d = client.fills(a, kopya_bas, max_rows=int(rules["radar_dolum_tavan"]) * 4, end_ms=simdi)
                if len(d) >= int(rules["radar_dolum_tavan"]) * 4:
                    satirlar.append({"adres": a, "tur": "aday", **o, "neden": "dolum_fazla"})
                    continue
                try:
                    payda = kopya_v5.PaydaSerisi(radar_tarama.payda_noktalari(client.portfolio(a), simdi))
                except (*radar_tarama.HATALAR, AttributeError):
                    payda = o["hesap_usd"]
                k = kopya_kapisi(d, o["hesap_usd"], payda, mum, kopya_bas, simdi, likit, b.azami_kaldirac, rules)
            except radar_tarama.HATALAR as h:
                satirlar.append({"adres": a, "tur": "aday", **o, "neden": "veri_hatasi", "hata": type(h).__name__})
                continue
            satirlar.append({"adres": a, "tur": "aday", **o, **k})
            if k["neden"] is None:
                uyeler.append({"adres": a, **o, **k, "giris_ms": simdi, "ay_negatif": 0})
                log(f"giriş {a[:10]}… t {o['t_istat']:.2f}, kopya {k['kopya_getiri']:+.4f}")
    havuz = {"sema": HAVUZ_SEMA, "kosu_ms": simdi, "pencere_bas_ms": kopya_bas, "doldurma": doldur, "satirlar": satirlar}
    return havuz, kadro_yaz(uyeler, simdi, rules, ay if doldur else (onceki or {}).get("doldurma_ay", ay), cikanlar)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cikti", type=Path, default=Path("radar"))
    ap.add_argument("--onceki-kadro", type=Path, default=None)
    a = ap.parse_args(argv)
    rules = load_rules()
    onceki = json.loads(a.onceki_kadro.read_text(encoding="utf-8")) if a.onceki_kadro else None
    simdi = int(time.time() * 1000)
    havuz, kadro = kos(radar_tarama.radar_istemcisi(rules=rules), simdi, onceki, rules)
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
