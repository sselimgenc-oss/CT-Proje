"""Ölçüm (aşama 5): her (adres, T) için dondurulmuş kurallar + kollar + sonraki 4 hafta kopya oynatması. Ağ YOK: yalnız diskteki önbellek.

Repo parçaları (salt içe aktarma, değişiklik yok): secim_d.portfolio_olculeri / seri_birlestir (K-65 perp pnl + toplam hesap serisi),
radar_tarama.islem_olculeri, kalicilik_testi.SaatlikMum (saatlik mum, likidite), kopya_v5.hesapla + PaydaSerisi (bizim boyut), izleme_motoru /
kopya_v2 (eylem, işaret, saatlik mum), gecmis_funding.FundingOnbellegi, olcut.martingale_ratio / perp_fills.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
import types
from typing import Any

sys.path.insert(0, os.environ.get("WF_REPO") or str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402

from copytrade import boyut, kalicilik_testi, kopya_v2, kopya_v5, radar_tarama, secim_d  # noqa: E402
from copytrade import izleme_motoru as im  # noqa: E402
from copytrade.gecmis_funding import FundingOnbellegi  # noqa: E402
from copytrade.kurallar import load_rules  # noqa: E402
from copytrade.olcut import martingale_ratio  # noqa: E402
from copytrade.olcut import perp_fills as _perp_fills  # noqa: E402


def perp_fills(fills: list[dict]) -> list[dict]:
    """olcut.perp_fills + '#NNNN' (sonuç/olay piyasaları; perp değil, mum/funding yok, kopyalanamaz) dolumları atılır."""
    return [f for f in _perp_fills(fills) if not str(f.get("coin", "")).startswith("#")]

import hl  # noqa: E402

HOUR = 3_600_000
GUN = 24 * HOUR
HAFTA = 7 * GUN

# ------------------------------------------------------------------------ DONDURULMUŞ eşikler (KURALLAR_DONDURULDU.md ile aynı)
K = {
    "hesap_A": 50_000.0, "hesap_D": 10_000.0,
    "hafta_n": 12, "pozitif_hafta_min": 8, "dusus_90g_max": 0.20,
    "devir_max": 25.0, "tutma_min_saat": 0.5,
    "kaldirac_max": 5.0, "coin_max": 8, "likit_pay_min": 1.0,
    "islem56_min": 6, "islem28_min": 3,
    "atlanan_pay_max": 0.20,
    "kopya_getiri_min": 0.0, "koruma_min": 0.5,
    "veto_zarar_ekleme_oran": 0.40,
    "pencere_kisa": 28 * GUN, "pencere_uzun": 56 * GUN, "ileri": 28 * GUN,
}
KOLLAR = ("A", "B", "C", "D")


# ------------------------------------------------------------------------ önbellek kaynakları
class OnbellekMumIstemci:
    """SaatlikMum'un `client.candles` yüzeyi: coin başına diskteki 1 sa seri (aşama 4). Eksik coin → [] (sayılır)."""

    def __init__(self):
        self.seri: dict[str, list[dict]] = {}
        self.eksik: set[str] = set()

    def candles(self, coin: str, start_ms: int, end_ms: int, interval: str = "1h") -> list[dict]:
        if coin not in self.seri:
            d = hl.oku("mum", coin.replace(":", "_").replace("/", "_"))
            if d is None:
                self.eksik.add(coin)
            self.seri[coin] = (d or {}).get("mumlar", [])
        return [c for c in self.seri[coin] if start_ms <= int(c["t"]) <= end_ms]


class OnbellekFundingIstemci:
    """FundingOnbellegi'nin `client.info(fundingHistory)` yüzeyi: coin başına diskteki tüm seri."""

    def __init__(self):
        self.seri: dict[str, list[dict]] = {}

    def info(self, payload: dict, weight: int = 20) -> Any:
        coin = payload["coin"]
        if coin not in self.seri:
            d = hl.oku("funding", coin.replace(":", "_").replace("/", "_"))
            self.seri[coin] = (d or {}).get("satirlar", [])
        s, e = int(payload["startTime"]), int(payload["endTime"])
        return [r for r in self.seri[coin] if s <= int(r["time"]) <= e]


class Kaynak:
    def __init__(self, bas_ms: int, bit_ms: int, azami: dict | None, rules: dict | None = None):
        self.rules = rules or load_rules()
        self.mumc = OnbellekMumIstemci()
        self.mum = kalicilik_testi.SaatlikMum(self.mumc, bas_ms, bit_ms)
        self.fon = FundingOnbellegi(OnbellekFundingIstemci())
        self.azami = azami


# ------------------------------------------------------------------------ atlanan hacim (kural 6) için boyut kaydı
class _AtlananKayit:
    """`kopya_v5.boyut` yerine geçici sarmalayıcı: her `hedef_emir` kararında İDEAL emir ($; min emir kuralı olmasaydı) ve sonucu kaydeder."""

    def __init__(self):
        self.toplam = 0.0
        self.atlanan = 0.0
        self.mod = types.SimpleNamespace(slot_usd=boyut.slot_usd, saha_sayisi=boyut.saha_sayisi, hedef_emir=self.hedef_emir)

    def hedef_emir(self, eylem, once, sonra, hesap, biz, slot, fiyat, rules=None, toplam=None):
        emir, neden = boyut.hedef_emir(eylem, once, sonra, hesap, biz, slot, fiyat, rules, toplam)
        tavan = float(rules["radar_slot_tavan_carpan"]) * float(slot)
        ideal = emir
        if neden == "min_emir_atlandi" and hesap > 0 and fiyat > 0:
            hedef = min(float(slot) * abs(float(sonra)) * float(fiyat) / float(hesap), tavan)
            b = abs(float(biz))
            ideal = hedef if eylem == "ac" else (max(0.0, hedef - b) if eylem == "artir" else max(0.0, b - hedef))
            self.atlanan += ideal
        self.toplam += ideal
        return emir, neden

    def pay(self) -> float | None:
        return self.atlanan / self.toplam if self.toplam > 0 else None


# ------------------------------------------------------------------------ kopya oynatma (bizim boyut, gecikmesiz + tam maliyet + funding)
def oynat(d: list[dict], payda: Any, kay: Kaynak, t0: int, t1: int, maliyetli: bool = True, atlanan: bool = False) -> dict:
    """[t0, t1) perp dolumlarını kopya_v5 ile oynatır (pencere başında boş; kalicilik_testi.hafta_satiri ile aynı yaklaşım). Döner getiri (kasa oranı), düşüş, işlem sayısı, atlanan pay."""
    rules = kay.rules
    d = kopya_v5.hip3_ayikla([f for f in d if t0 <= int(f["time"]) < t1], bool(rules.get("radar_hip3_kopya", True)))
    if not d:
        return {"getiri": 0.0, "dusus": 0.0, "islem": 0, "atlanan_pay": None, "durum": "islem_yok"}
    eylemler = im.copy_actions(d)
    isaret = im.mark_candles(kay.mum, eylemler, t1)
    saatlik = kopya_v2.saatlik_mumlar(kay.mum, {}, d, im.open_copy_coins(eylemler), t1)
    oranlar = kay.fon.oku({str(f["coin"]) for f in d}, t0, t1)
    r = rules if maliyetli else {**rules, "maliyet_taker": 0.0, "maliyet_kayma": 0.0}
    a, b = pd.Timestamp(t0, unit="ms", tz="UTC"), pd.Timestamp(t1, unit="ms", tz="UTC")
    kayit = _AtlananKayit() if atlanan else None
    eski = kopya_v5.boyut
    try:
        if kayit:
            kopya_v5.boyut = kayit.mod
        s = kopya_v5.hesapla(d, saatlik, isaret, {}, oranlar, a, b, 0, radar_tarama.KOPYA_TARZ, r, azami_kaldirac=kay.azami, trader_hesap_usd=payda)
    finally:
        kopya_v5.boyut = eski
    if s.get("durum") == "hesaplanamadi":
        return {"getiri": 0.0, "dusus": 0.0, "islem": 0, "atlanan_pay": kayit.pay() if kayit else None, "durum": "yurutulebilir_yok"}
    islem = [t for t in s.get("kapanan_islemler") or [] if t.get("gecerli") is not False and t.get("sonuc_usd") is not None]
    return {"getiri": float(s["getiri"]), "dusus": float(s.get("dusus") or 0.0), "islem": len(islem), "atlanan_pay": kayit.pay() if kayit else None,
            "fiyatsiz": int(s.get("fiyatsiz_eylem") or 0), "tasfiye": bool(s.get("tasfiye")), "durum": "olculdu"}


# ------------------------------------------------------------------------ portfolio (ucuz) ölçüleri
def portfolio_tarihleri(pf: Any, tarihler: list[int], rules: dict) -> dict[int, dict]:
    out = {}
    for T in tarihler:
        o = secim_d.portfolio_olculeri(pf, T, rules)
        h = o.get("hesap_usd")
        r2 = (o["hafta_sayisi"] >= K["hafta_n"] and o["pozitif_hafta"] >= K["pozitif_hafta_min"]
              and o.get("dusus_90g") is not None and o["dusus_90g"] <= K["dusus_90g_max"] + 1e-12)
        p30 = o.get("pnl_30g")
        out[T] = {"hesap": h, "t": o.get("t_istat"), "pozitif_hafta": o["pozitif_hafta"], "hafta_sayisi": o["hafta_sayisi"], "dusus_90g": o.get("dusus_90g"),
                  "pnl_30g": p30, "omur_pnl": o.get("omur_perp_pnl"), "r2": bool(r2),
                  "r1_A": bool(h and h >= K["hesap_A"]), "r1_D": bool(h and h >= K["hesap_D"]),
                  "k50": bool(h and h >= K["hesap_A"] and p30 is not None and p30 > 0),
                  "k10": bool(h and h >= K["hesap_D"] and p30 is not None and p30 > 0)}
    return out


def dolum_gerekli(po: dict[int, dict]) -> bool:
    """Aşama 3 ucuz süzgeç: herhangi bir T'de (bugün dahil) hesap ≥ 10k ve kural 2 (D ⊇ A adayları)."""
    return any(v["r1_D"] and v["r2"] for v in po.values())


# ------------------------------------------------------------------------ bir adres, tüm T'ler
def adres_olc(adres: str, pf: Any, dk: dict | None, tarihler: list[int], simdi: int, ornek50: bool, ornek10: bool, kay: Kaynak,
              ileri_tarihler: set[int]) -> dict:
    """Döner {T: satır}. `ileri_tarihler`: sonraki 4 hafta ölçülecek T'ler (T12 kilitliyken hariç; bugün hiç)."""
    rules = kay.rules
    po = portfolio_tarihleri(pf, tarihler, rules)
    hesap_s = secim_d.seri_birlestir(pf, secim_d.HESAP_DONEM, "accountValueHistory", False)
    try:
        payda = kopya_v5.PaydaSerisi(hesap_s)
    except ValueError:
        payda = None
    tum = perp_fills(dk["dolumlar"]) if dk and dk.get("dolumlar") is not None else None
    if tum is not None:
        tum.sort(key=lambda f: (int(f["time"]), int(f.get("tid") or 0)))
    out = {}
    for T in tarihler:
        p = po[T]
        ilgili = (p["r1_D"] and p["r2"]) or (ornek50 and p["k50"]) or (ornek10 and p["k10"])
        satir = {**p, "ornek50": ornek50, "ornek10": ornek10, "ilgili": bool(ilgili)}
        if not ilgili:
            out[T] = satir
            continue
        # dolum geçmişi yeterliliği: [T − 56 g, T + 28 g) (bugün için [T − 56 g, T))
        gereken_bas = T - K["pencere_uzun"]
        if tum is None:
            satir["cikarildi"] = "dolum_yok" if dk is None else "dolum_hata"
            out[T] = satir
            continue
        if int(dk.get("kapsam_bas", 0)) > gereken_bas or payda is None:
            satir["cikarildi"] = "dolum_gecmisi_yetmez" if payda is not None else "payda_yok"
            out[T] = satir
            continue
        satir.update(kapilar(tum, p, payda, kay, T))
        g = satir.get("kapi_gecti", False)
        veto = satir.get("veto")
        satir["kol"] = {"A": bool(p["r1_A"] and p["r2"] and g), "B": bool(p["r1_A"] and p["r2"] and g and veto is None),
                        "C": bool(ornek50 and p["k50"] and g and veto is None), "D": bool(p["r1_D"] and p["r2"] and g)}
        lazim = any(satir["kol"].values()) or (ornek50 and p["k50"]) or (ornek10 and p["k10"])
        if T in ileri_tarihler and lazim:
            satir["ileri"] = oynat(tum, payda, kay, T, T + K["ileri"])
        out[T] = satir
    return out


def kapilar(tum: list[dict], p: dict, payda: Any, kay: Kaynak, T: int) -> dict:
    """Kurallar 3–7 + iki veto (yalnız T'ye kadarki veri)."""
    rules = kay.rules
    hesap = p["hesap"] or 0.0
    b28, b56 = T - K["pencere_kisa"], T - K["pencere_uzun"]
    d28 = [f for f in tum if b28 <= int(f["time"]) < T]
    o: dict = {"neden": None, "veto": None}
    # vetolar (her zaman ölçülür; B ve C'de uygulanır)
    oran, sayi = martingale_ratio(d28, float(rules["martingale_min_adverse"])) if d28 else (0.0, 0)
    o.update({"zarara_ekleme_oran": oran, "zarara_ekleme_sayi": sayi})
    if p.get("omur_pnl") is not None and p["omur_pnl"] <= 0:
        o["veto"] = "veto_omur_zarar"
    elif sayi >= int(rules["martingale_min_additions"]) and oran >= K["veto_zarar_ekleme_oran"] - 1e-12:
        o["veto"] = "veto_zarara_ekleme"
    if not d28 or hesap <= 0:
        o.update({"neden": "islem_yok", "kapi_gecti": False})
        return o
    coinler = {str(f["coin"]) for f in d28}
    likit = kay.mum.likit_coinler(coinler, b28, T, rules)
    io = radar_tarama.islem_olculeri(d28, hesap, likit, rules)
    o.update({"devir": sum(abs(float(f["px"]) * float(f["sz"])) for f in d28) / hesap / 4.0, "tutma_saat": io.get("medyan_tutma_saat"),
              "kaldirac": io.get("max_kaldirac"), "aktif_coin": len(coinler), "likit_pay": io.get("likit_pay")})
    ucuz = (("devir_yuksek", o["devir"], lambda v: v <= K["devir_max"] + 1e-12),
            ("tutma_kisa", o["tutma_saat"], lambda v: v >= K["tutma_min_saat"] - 1e-12),
            ("kaldirac_yuksek", o["kaldirac"], lambda v: v <= K["kaldirac_max"] + 1e-12),
            ("coin_fazla", o["aktif_coin"], lambda v: v <= K["coin_max"]),
            ("likit_degil", o["likit_pay"], lambda v: v >= K["likit_pay_min"] - 1e-9))
    o["neden"] = next((k for k, v, f in ucuz if v is None or not f(v)), None)
    if o["neden"]:
        o["kapi_gecti"] = False
        return o
    u = oynat(tum, payda, kay, b56, T, atlanan=True)
    k = oynat(tum, payda, kay, b28, T)
    ay = oynat(tum, payda, kay, b28, T, maliyetli=False)
    koruma = k["getiri"] / ay["getiri"] if ay["getiri"] > 0 else None
    o.update({"islem56": u["islem"], "islem28": k["islem"], "atlanan_pay": u["atlanan_pay"], "kopya28": k["getiri"], "ayna28": ay["getiri"], "koruma": koruma})
    kural = (("kopya_islem_az", (u["islem"], k["islem"]), lambda v: v[0] >= K["islem56_min"] and v[1] >= K["islem28_min"]),
             ("atlanan_fazla", u["atlanan_pay"], lambda v: v <= K["atlanan_pay_max"] + 1e-12),
             ("kopya_zarar", k["getiri"], lambda v: v > K["kopya_getiri_min"]),
             ("koruma_dusuk", koruma, lambda v: v >= K["koruma_min"] - 1e-12))
    o["neden"] = next((kk for kk, v, f in kural if v is None or not f(v)), None)
    o["kapi_gecti"] = o["neden"] is None
    return o
