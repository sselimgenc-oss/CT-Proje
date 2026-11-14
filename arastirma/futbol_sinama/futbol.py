"""Futbol yapısı sınaması (yalnız bilgi): her T'de temiz adaylardan kura ile N kişilik eşit ağırlıklı kadro, farklı slot boyutlarında 4 hafta kopya getirisi.

Boru hattı `arastirma/secim_dogrulama` (salt içe aktarma). Birimler (hepsi ORAN; 0,012 = %1,2):
  getiri / dusus (uye_getiri.csv, ham_sonuclar.csv) = SLOT ölçeği oranı (hesapla getirisi × 5; kasa = 5 × slot), kadro_getiri = kadro kasası (N × slot) oranı.
  Tarihler UTC ms. t_index 0..10 = T1..T11. T12 ve 'bugün' ölçülmez.
"""
from __future__ import annotations

import argparse
import copy
import csv
import gzip
import hashlib
import json
import multiprocessing as mp
import os
import statistics
import sys
import time
import traceback
from collections import Counter
from pathlib import Path

import numpy as np

KOK_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(KOK_REPO))
sys.path.insert(0, str(KOK_REPO / "arastirma" / "secim_dogrulama"))

import hl  # noqa: E402
import olcum  # noqa: E402
from copytrade import kopya_v5, secim_d  # noqa: E402

GUN = olcum.GUN
ILERI = 28 * GUN
OLCEK = 5.0                                     # kasa(=5×slot) oranı → slot oranı
TOHUM = 20261111
CEKILIS = 1000
NLER = (3, 5, 8, 11)
SLOTLAR = (100, 150, 200)
HAVUZLAR = ("ornek700", "genis")
SURUM = 2
NEDEN_ALAN = {"min_emir_yuvarlandi": "ac_yuv", "min_emir_atlandi": "ac_atl", "slot_tavani": "ac_slot_tavani", "hesap_yok": "ac_hesap_yok", "tavan_kirpildi": "ac_tavan_kirpildi"}
EP_ALAN = ("epizot_toplam", "epizot_acildi", "epizot_ilk_yuvarlandi", "epizot_hic_acilmadi_min", "epizot_hic_acilmadi_tavan", "epizot_hic_acilmadi_diger")
AC_ALAN = ("ac_toplam", "ac_yuv", "ac_atl", "ac_slot_tavani", "ac_hesap_yok", "ac_tavan_kirpildi", "ac_diger") + EP_ALAN + ("ideal_top", "ideal_atl")
EPS = 1e-9


def onbellek_anahtari(slotlar) -> str:
    """Önbellek geçerliliği: sürüm + slot listesi + kurallar.yaml sha256."""
    h = hashlib.sha256((KOK_REPO / "copytrade" / "kurallar.yaml").read_bytes()).hexdigest()
    return f"{SURUM}|{','.join(map(str, slotlar))}|{h}"


# ------------------------------------------------------------------------ kayıt: boyut.hedef_emir sarmalayıcı (olcum._AtlananKayit + 'ac' sayımı)
class Sayac(olcum._AtlananKayit):
    """olcum._AtlananKayit + eylem='ac' kararlarının neden kodu dökümü + POZİSYON DÜZEYİ epizot ölçüsü. oynat() bunu `atlanan=True` ile kurar; son örnek `Sayac.son`'da.

    Epizot = trader'ın bir coinde düz→açık→düz dönemi. `hedef_emir` coin/trader pozisyonu almaz; çağıran `kopya_v5.boyutlayici.isle`'nin yerel
    değişkenleri (coin, before_leader, sonra) çerçeveden okunur. Yeni epizot: 'ac' çağrısında trader öncesi pozisyon 0 ya da ters dönüş (sonra·önce<0);
    aynı epizotta sonraki 'ac'/'artir' çağrıları ona eklenir. Kararı hiç olmayan (fiyatsız vb.) epizot sayılmaz."""
    son = None

    def __init__(self):
        super().__init__()
        self.ac = Counter()
        self.ep: dict[str, dict] = {}        # coin → şu anki epizot
        self.epler: list[dict] = []
        Sayac.son = self

    def _epizot(self, coin, yeni):
        if yeni or coin not in self.ep:
            self.ep[coin] = {"acildi": False, "ilk_yuv": False, "red": Counter()}
            self.epler.append(self.ep[coin])
        return self.ep[coin]

    def hedef_emir(self, eylem, once, sonra, hesap, biz, slot, fiyat, rules=None, toplam=None):
        emir, neden = super().hedef_emir(eylem, once, sonra, hesap, biz, slot, fiyat, rules, toplam)
        if eylem == "ac":
            self.ac["toplam"] += 1
            self.ac[NEDEN_ALAN.get(neden, "ac_diger")] += 1
        if eylem in ("ac", "artir"):
            fr = sys._getframe(1).f_locals
            if "coin" not in fr or "before_leader" not in fr:
                raise RuntimeError("Sayac: çağıran boyutlayici.isle olmalı (coin/before_leader yok)")
            bl = float(fr["before_leader"])
            yeni = eylem == "ac" and (abs(bl) < EPS or float(fr.get("sonra", 0.0)) * bl < 0)
            e = self._epizot(fr["coin"], yeni)
            if emir > 0:
                if not e["acildi"]:
                    e["acildi"], e["ilk_yuv"] = True, neden == "min_emir_yuvarlandi"
            else:
                e["red"][neden] += 1
        return emir, neden

    def ozet(self) -> dict:
        o = {k: self.ac[k] if k != "ac_toplam" else self.ac["toplam"] for k in ("ac_toplam", "ac_yuv", "ac_atl", "ac_slot_tavani", "ac_hesap_yok", "ac_tavan_kirpildi", "ac_diger")}
        o.update({k: 0 for k in EP_ALAN})
        o["epizot_toplam"] = len(self.epler)
        for e in self.epler:
            if e["acildi"]:
                o["epizot_acildi"] += 1
                o["epizot_ilk_yuvarlandi"] += bool(e["ilk_yuv"])
                continue
            r = e["red"]
            grup = Counter({"min": r["min_emir_atlandi"], "tavan": r["slot_tavani"], "diger": sum(r.values()) - r["min_emir_atlandi"] - r["slot_tavani"]})
            ad = max(("min", "tavan", "diger"), key=lambda k: (grup[k], k == "min", k == "tavan"))   # ağırlıklı neden; eşitlikte min > tavan > diğer
            o[f"epizot_hic_acilmadi_{ad}"] += 1
        return o


def kural_slot(rules: dict, slot: float) -> dict:
    """Bellekte kopya: kasa = 5×slot, slot alt sınırı = slot → N=5, slot_usd = slot. kurallar.yaml değişmez."""
    return {**rules, "canli_kasa_usd": 5.0 * float(slot), "radar_canli_slot_min_usd": float(slot)}


def oynat_slot(kay, tum, payda, T: int, slot: float) -> dict:
    """olcum.oynat ile AYNI yol; yalnız kural kopyası slota göre. Getiri/düşüş slot oranı."""
    k2 = copy.copy(kay)
    k2.rules = kural_slot(kay.rules, slot)
    Sayac.son = None
    r = olcum.oynat(tum, payda, k2, T, T + ILERI, atlanan=True)
    s = Sayac.son
    o = s.ozet() if s else {k: 0 for k in AC_ALAN}
    return {"getiri": r["getiri"] * OLCEK, "dusus": r["dusus"] * OLCEK, "islem": r["islem"], "durum": r["durum"],
            "tasfiye": bool(r.get("tasfiye", False)), "fiyatsiz": int(r.get("fiyatsiz", 0)), **o,
            "ideal_top": s.toplam if s else 0.0, "ideal_atl": s.atlanan if s else 0.0}


# ------------------------------------------------------------------------ saf yardımcılar (testli)
def temiz(r: dict) -> bool:
    """Seçim temiz adayı: k50 ∧ çıkarılmadı ∧ kapılar geçti ∧ veto yok (kural 2 / t sıralaması yok)."""
    return bool(r.get("k50") and not r.get("cikarildi") and r.get("kapi_gecti") and r.get("veto") is None)


def kontrol_uyesi(r: dict) -> bool:
    return bool(r.get("ornek50") and r.get("k50") and not r.get("cikarildi"))


def kura(adaylar: list[str], T: int) -> list[str]:
    """Adrese göre sırala, tohumla karıştır; ilk N = kadro (iç içe)."""
    a = sorted(adaylar)
    rng = np.random.default_rng([TOHUM, int(T)])
    return [a[i] for i in rng.permutation(len(a))]


def kadro_getirisi(uyeler: list[float], n: int) -> tuple[float, float | None]:
    """(kasa oranı = toplam/N [boş koltuk 0], dolu koltuk ortalaması | None)."""
    if len(uyeler) > n:
        raise ValueError("üye sayısı N'den büyük")
    return sum(uyeler) / n, (sum(uyeler) / len(uyeler) if uyeler else None)


def yuzdelik(deger: float, cekilis) -> float:
    c = np.asarray(cekilis)
    return float(np.mean(c < deger) + 0.5 * np.mean(c == deger))


_IDX: dict = {}


def cekilis_idx(tohum: list[int], havuz_n: int, k: int):
    """Yerine koymadan k kişilik CEKILIS çekiliş indeksleri; slot/havuzdan bağımsız (eşli). Havuz < k ise None."""
    if k < 1 or havuz_n < k:
        return None
    a = (tuple(tohum), havuz_n, k)
    if a not in _IDX:
        rng = np.random.default_rng(tohum)
        _IDX[a] = np.argsort(rng.random((CEKILIS, havuz_n)), axis=1)[:, :k]
    return _IDX[a]


def cekilis_ort(h: list[float], tohum: list[int], k: int):
    idx = cekilis_idx(tohum, len(h), k)
    return None if idx is None else np.asarray(h)[idx].mean(axis=1)


def t_ayir(T: int, tarihler: list[int]) -> int:
    """T1–T11 kilidi: T12 (index 11) ve sonrası ölçülemez."""
    assert len(tarihler) >= 12, "ayar.json en az 12 tarih içermeli"
    ok = tarihler[:11]
    assert T in ok, f"T {T} T1–T11 dışında (T12 ve bugün ölçülmez)"
    return ok.index(T)


# ------------------------------------------------------------------------ işçi: bir adres için sınıflandırma + oynatma
_KAY = None
_AYAR = None


def _isci_kur(ayar):
    global _KAY, _AYAR
    olcum._AtlananKayit = Sayac
    _AYAR = ayar
    meta = hl.oku("tek", "meta") or {}
    _KAY = olcum.Kaynak(ayar["mum_bas"], ayar["simdi"], meta.get("azami"))


class _Baglam:
    """Adres başına tembel yükleme: portfolio, dolum, payda, portfolio ölçüleri."""

    def __init__(self, adres):
        self.adres = adres
        self._y = False

    def yukle(self):
        if self._y:
            return
        self._y = True
        a = self.adres
        self.pf, self.dk = hl.oku("portfolio", a), hl.oku("dolum", a)
        hs = secim_d.seri_birlestir(self.pf, secim_d.HESAP_DONEM, "accountValueHistory", False)
        try:
            self.payda = kopya_v5.PaydaSerisi(hs)
        except ValueError:
            self.payda = None
        dk = self.dk
        self.tum = olcum.perp_fills(dk["dolumlar"]) if dk and dk.get("dolumlar") is not None else None
        if self.tum is not None:
            self.tum.sort(key=lambda f: (int(f["time"]), int(f.get("tid") or 0)))

    def yeniden_kapilar(self, T: int, kay) -> dict:
        """adres_olc'taki dolum yeterliliği + kapilar() (kural 2'yi geçmediği için önbellekte kapıları yok)."""
        self.yukle()
        p = olcum.portfolio_tarihleri(self.pf, [T], kay.rules)[T]
        if not p["k50"]:
            return {"k50": False}
        if self.tum is None:
            return {"k50": True, "cikarildi": "dolum_yok" if self.dk is None else "dolum_hata"}
        if int(self.dk.get("kapsam_bas", 0)) > T - olcum.K["pencere_uzun"] or self.payda is None:
            return {"k50": True, "cikarildi": "dolum_gecmisi_yetmez" if self.payda is not None else "payda_yok"}
        return {"k50": True, **olcum.kapilar(self.tum, p, self.payda, kay, T)}


def siniflandir(adres: str, T: int, ornek50: bool, onb_row: dict | None, ctx: _Baglam, kay) -> dict:
    """Önbellekteki satırı kullan; yalnız ornek50 dışı + ilgili olmayan + k50 satırlarda kapıları yeniden hesapla."""
    if onb_row is None:
        raise KeyError(f"cache/olcum satırı yok: {adres} {T}")
    assert bool(onb_row.get("ornek50")) == ornek50, f"ornek50 uyuşmuyor {adres}"
    if onb_row.get("ilgili"):
        src, r = "onbellek", onb_row
    elif ornek50 or not onb_row.get("k50"):
        return {"ornek50": ornek50, "k50": bool(onb_row.get("k50")), "cikarildi": None, "kapi_gecti": False, "veto": None, "kaynak": "onbellek_ilgisiz"}
    else:
        src, r = "yeniden", ctx.yeniden_kapilar(T, kay)
    o = {"ornek50": ornek50, "k50": bool(r.get("k50")), "cikarildi": r.get("cikarildi"), "kapi_gecti": bool(r.get("kapi_gecti", False)),
         "veto": r.get("veto"), "kaynak": src}
    if ornek50 and src == "onbellek":     # kural: ornek700 temiz aday == olcum kol["C"]
        assert temiz(o) == bool((onb_row.get("kol") or {}).get("C", False)), f"kol C uyuşmuyor {adres} {T}"
    return o


def _yaz_onb(yol: Path, d: dict):
    yol.parent.mkdir(parents=True, exist_ok=True)
    tmp = yol.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(d, f)
    os.replace(tmp, yol)


def _isci(arg):
    adres, tler, ornek50, onb_dir, slotlar, genis_yeniden = arg
    yol = Path(onb_dir) / f"{adres}.json.gz"
    t0 = time.time()
    try:
        if yol.exists():
            try:
                with gzip.open(yol, "rt", encoding="utf-8") as f:
                    d = json.load(f)
                if d.get("anahtar") == onbellek_anahtari(slotlar) and all(str(T) in d["T"] for T in tler):
                    return adres, d, None, 0.0
            except (OSError, ValueError, EOFError):
                pass
        tum_onb = (hl.oku("olcum", adres) or {}).get("T")
        if tum_onb is None:
            raise KeyError("cache/olcum yok")
        ctx = _Baglam(adres)
        out = {}
        for T in tler:
            row = siniflandir(adres, T, ornek50, tum_onb.get(str(T)), ctx, _KAY) if (ornek50 or genis_yeniden) else None
            if row is None:
                continue
            row["oyna"] = bool(temiz(row) or kontrol_uyesi(row))
            if row["oyna"]:
                ctx.yukle()
                if ctx.tum is None or ctx.payda is None:
                    raise RuntimeError("temiz/kontrol üyesi için dolum/payda yok")
                row["slot"] = {str(s): oynat_slot(_KAY, ctx.tum, ctx.payda, T, s) for s in slotlar}
            out[str(T)] = row
        d = {"anahtar": onbellek_anahtari(slotlar), "adres": adres, "T": out}
        _yaz_onb(yol, d)
        return adres, d, None, time.time() - t0
    except Exception as h:  # noqa: BLE001 — hata adres bazında SAYILIR ve özete yazılır
        return adres, None, f"{type(h).__name__}: {h} | {traceback.format_exc()[-300:]}", time.time() - t0


# ------------------------------------------------------------------------ toplama
def _t_satiri(havuz: str, N: int, slot: int, T: int, ti: int, adaylar: list[str], kontrol: list[str], rec: dict) -> dict:
    s = str(slot)
    sira = kura(adaylar, T)
    uyeler = sira[:N]
    g = [rec[a][str(T)]["slot"][s]["getiri"] for a in uyeler]
    kadro, dolu = kadro_getirisi(g, N)
    h = [rec[a][str(T)]["slot"][s]["getiri"] for a in kontrol]
    ac = {k: sum(rec[a][str(T)]["slot"][s][k] for a in uyeler) for k in AC_ALAN}
    cik_k = sum(1 for d in rec.values() if str(T) in d and d[str(T)]["ornek50"] and d[str(T)]["k50"] and d[str(T)]["cikarildi"])
    cik_a = cik_k if havuz == "ornek700" else sum(1 for d in rec.values() if str(T) in d and d[str(T)]["k50"] and d[str(T)]["cikarildi"])
    c = cekilis_ort(h, [TOHUM, N, ti], N)
    cd = cekilis_ort(h, [TOHUM, 1000 + len(uyeler), ti], len(uyeler)) if uyeler else None
    return {"havuz": havuz, "N": N, "slot": slot, "T": T, "t_index": ti, "aday_n": len(adaylar), "kadro_n": len(uyeler), "bos_koltuk": N - len(uyeler),
            "kadro_getiri": kadro, "dolu_getiri": dolu,
            "yuzdelik": None if c is None else yuzdelik(kadro, c), "dolu_yuzdelik": None if (cd is None or dolu is None) else yuzdelik(dolu, cd),
            "cikarilan_aday": cik_a, "cikarilan_kontrol": cik_k,
            "ac_toplam": ac["ac_toplam"], "ac_yuvarlanan": ac["ac_yuv"], "ac_atlanan": ac["ac_atl"], "ac_slot_tavani": ac["ac_slot_tavani"], "ac_hesap_yok": ac["ac_hesap_yok"],
            "ac_tavan_kirpildi": ac["ac_tavan_kirpildi"], "ac_diger": ac["ac_diger"], **{k: ac[k] for k in EP_ALAN}, "ideal_top": ac["ideal_top"], "ideal_atl": ac["ideal_atl"],
            "kontrol_n": len(h), "kontrol_ortanca": statistics.median(h) if h else None, "_c": c, "_cd": cd}


def _orta(x):
    x = [v for v in x if v is not None]
    return statistics.median(x) if x else None


def _ort(x):
    x = [v for v in x if v is not None]
    return statistics.fmean(x) if x else None


def _pay(a, b):
    return a / b if b else None


def hucre_ozeti(satirlar: list[dict]) -> dict:
    """Bir (havuz, N, slot) hücresinin T1–T11 özeti."""
    n = len(satirlar)
    kg = [s["kadro_getiri"] for s in satirlar]
    dg = [s["dolu_getiri"] for s in satirlar]
    dolu_t = [s for s in satirlar if s["kadro_n"] > 0]
    ctlr = [(s["kadro_getiri"], s["_c"]) for s in satirlar if s["_c"] is not None]
    birlesik = None
    if ctlr:
        ort = float(np.mean([k for k, _ in ctlr]))
        null = np.mean(np.asarray([c for _, c in ctlr]), axis=0)
        birlesik = yuzdelik(ort, null)
    dd = [(s["dolu_getiri"], s.get("_cd")) for s in satirlar if s["dolu_getiri"] is not None and s.get("_cd") is not None]
    birlesik_dolu = yuzdelik(float(np.mean([k for k, _ in dd])), np.mean(np.asarray([c for _, c in dd]), axis=0)) if dd else None   # aynı çekiliş i, T ortalaması
    ac_t, ac_y, ac_a = (sum(s[k] for s in satirlar) for k in ("ac_toplam", "ac_yuvarlanan", "ac_atlanan"))
    E = {k: sum(s[k] for s in satirlar) for k in EP_ALAN}
    hic = E["epizot_hic_acilmadi_min"] + E["epizot_hic_acilmadi_tavan"] + E["epizot_hic_acilmadi_diger"]
    N = satirlar[0]["N"]
    return {"havuz": satirlar[0]["havuz"], "N": N, "slot": satirlar[0]["slot"], "t_sayisi": n,
            "kadro_ortanca": _orta(kg), "kadro_ortalama": _ort(kg), "kadro_kucuk_m5_pay": sum(v < -0.05 for v in kg) / n,
            "dolu_ortanca": _orta(dg), "dolu_ortalama": _ort(dg), "dolu_kucuk_m5_pay": _pay(sum(v < -0.05 for v in dg if v is not None), len(dolu_t)),
            "yuzdelik_ortanca": _orta([s["yuzdelik"] for s in satirlar]), "dolu_yuzdelik_ortanca": _orta([s["dolu_yuzdelik"] for s in satirlar]),
            "birlesik_yuzdelik": birlesik, "dolu_birlesik_yuzdelik": birlesik_dolu,
            "yuvarlanan_ac_pay": _pay(ac_y, ac_t), "atlanan_ac_pay": _pay(ac_a, ac_t), "ac_toplam": ac_t,
            "ac_tavan_pay": _pay(sum(s["ac_slot_tavani"] for s in satirlar), ac_t), "ac_hesap_yok_pay": _pay(sum(s["ac_hesap_yok"] for s in satirlar), ac_t),
            "ac_tavan_kirpildi_pay": _pay(sum(s["ac_tavan_kirpildi"] for s in satirlar), ac_t), "ac_diger_pay": _pay(sum(s["ac_diger"] for s in satirlar), ac_t),
            **E, "yuvarlanan_poz_pay": _pay(E["epizot_ilk_yuvarlandi"], E["epizot_acildi"]), "atlanan_poz_pay": _pay(hic, E["epizot_toplam"]),
            "atlanan_poz_min_pay": _pay(E["epizot_hic_acilmadi_min"], E["epizot_toplam"]), "atlanan_poz_tavan_pay": _pay(E["epizot_hic_acilmadi_tavan"], E["epizot_toplam"]),
            "ideal_atlanan_pay": _pay(sum(s["ideal_atl"] for s in satirlar), sum(s["ideal_top"] for s in satirlar)),
            "bos_koltuk_orani": sum(s["aday_n"] < N for s in satirlar) / n, "bos_koltuk_payi_ort": _ort([s["bos_koltuk"] / N for s in satirlar]),
            "aday_ort": _ort([s["aday_n"] for s in satirlar]), "kontrol_ortanca_ort": _ort([s["kontrol_ortanca"] for s in satirlar])}


def topla(rec: dict, tarihler: list[int], tler: list[int]) -> dict:
    """rec: {adres: {str(T): satır}} → ham satırlar, hücre özeti, üye satırları, kontrol açılış payları."""
    ti = {T: t_ayir(T, tarihler) for T in tler}
    ham, uye = [], []
    for T in tler:
        kont = sorted(a for a, d in rec.items() if str(T) in d and kontrol_uyesi(d[str(T)]))
        ad = {"ornek700": sorted(a for a, d in rec.items() if str(T) in d and d[str(T)]["ornek50"] and temiz(d[str(T)])),
              "genis": sorted(a for a, d in rec.items() if str(T) in d and temiz(d[str(T)]))}
        for hv, adaylar in ad.items():
            for N in NLER:
                for slot in SLOTLAR:
                    ham.append(_t_satiri(hv, N, slot, T, ti[T], adaylar, kont, rec))
        for a, d in rec.items():
            r = d.get(str(T))
            if r and r.get("oyna"):
                for s, x in sorted(r["slot"].items(), key=lambda z: int(z[0])):
                    uye.append({"adres": a, "T": T, "slot": int(s), "ornek700_aday": bool(r["ornek50"] and temiz(r)), "genis_aday": temiz(r), "kontrol": kontrol_uyesi(r),
                                "kaynak": r["kaynak"], **{k: x[k] for k in ("getiri", "dusus", "islem", "tasfiye", "fiyatsiz", "ac_toplam", "ac_yuv", "ac_atl", "durum", *EP_ALAN)}})
    hucre = []
    for hv in HAVUZLAR:
        for N in NLER:
            for slot in SLOTLAR:
                hucre.append(hucre_ozeti([s for s in ham if s["havuz"] == hv and s["N"] == N and s["slot"] == slot]))
    kont_ac = {}
    for slot in SLOTLAR:
        u = [x for x in uye if x["slot"] == slot and x["kontrol"]]
        t = sum(x["ac_toplam"] for x in u)
        kont_ac[str(slot)] = {"uye_T": len(u), "ac_toplam": t, "yuvarlanan_pay": _pay(sum(x["ac_yuv"] for x in u), t), "atlanan_pay": _pay(sum(x["ac_atl"] for x in u), t),
                         "yuvarlanan_poz_pay": _pay(sum(x["epizot_ilk_yuvarlandi"] for x in u), sum(x["epizot_acildi"] for x in u)),
                         "atlanan_poz_pay": _pay(sum(x["epizot_hic_acilmadi_min"] + x["epizot_hic_acilmadi_tavan"] + x["epizot_hic_acilmadi_diger"] for x in u), sum(x["epizot_toplam"] for x in u))}
    return {"ham": ham, "hucre": hucre, "uye": uye, "kontrol_ac": kont_ac}


def _aday_olabilir(adres: str, tler: list[int]) -> bool:
    """Hatalı adres olası aday mı: önbellek satırı okunamıyorsa ya da herhangi T'de k50 ise (kapılar kararı bilinmez) evet."""
    d = (hl.oku("olcum", adres) or {}).get("T")
    return d is None or any((d.get(str(T)) or {}).get("k50") for T in tler)


def csv_yaz(yol: Path, satirlar: list[dict], kolonlar: list[str] | None = None):
    if kolonlar is None:
        kolonlar = [k for k in satirlar[0] if not k.startswith("_")] if satirlar else []
    with open(yol, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=kolonlar, extrasaction="ignore")
        w.writeheader()
        w.writerows(satirlar)


# ------------------------------------------------------------------------ ana akış
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--veri", default=os.environ.get("WF_VERI"))
    ap.add_argument("--cikti", default=str(Path(__file__).resolve().parent))
    ap.add_argument("--isci", type=int, default=os.cpu_count() or 2)
    ap.add_argument("--deneme", action="store_true", help="yalnız T1 + ilk 50 kontrol adresi + T1 adayları (+ 40 ornek50-dışı örnek); çıktı deneme_ önekli")
    a = ap.parse_args(argv)
    if not a.veri:
        sys.exit("--veri ya da WF_VERI gerekli")
    hl.KOK = Path(a.veri)
    hl.CACHE = hl.KOK / "cache"
    ayar = json.load(open(hl.KOK / "ayar.json"))
    ornek = json.load(open(hl.KOK / "ornek.json"))
    tarihler = ayar["tarihler"]
    tler = tarihler[:11]
    for T in tler:
        t_ayir(T, tarihler)
    s50 = set(ornek["s50"])
    adresler = sorted(p.name[: -len(".json.gz")] for p in (hl.CACHE / "dolum").glob("*.json.gz"))
    on = "deneme_" if a.deneme else ""
    onb_dir = hl.KOK.parent / ("futbol_onbellek_deneme" if a.deneme else "futbol_onbellek")
    genis_set = set(adresler)
    if a.deneme:
        tler = tler[:1]
        ilk50 = [x for x in ornek["s50"] if x in genis_set][:50]
        aday = set()
        for x in adresler:
            d = (hl.oku("olcum", x) or {}).get("T", {}).get(str(tler[0]))
            if d and d.get("ilgili") and temiz(d):
                aday.add(x)
        diger = [x for x in adresler if x not in s50 and x not in aday][:40]
        adresler = sorted(set(ilk50) | aday | set(diger))
        print(f"deneme: {len(adresler)} adres (kontrol 50, aday {len(aday)}, örnek {len(diger)})")
    isler = [(x, tler, x in s50, str(onb_dir), SLOTLAR, True) for x in adresler]
    rec, hata, sure = {}, {}, []
    bas = time.time()
    with mp.Pool(a.isci, initializer=_isci_kur, initargs=(ayar,), maxtasksperchild=200) as hv:
        for i, (x, d, h, s) in enumerate(hv.imap_unordered(_isci, isler, chunksize=2), 1):
            if h:
                hata[x] = h
            else:
                rec[x] = d["T"]
                sure.append(s)
            if i % 100 == 0:
                print(f"{i}/{len(isler)} ({time.time() - bas:.0f} sn, hata {len(hata)})", flush=True)
    print(f"işçi bitti: {len(rec)} adres, hata {len(hata)}, {time.time() - bas:.0f} sn")
    sonuc = topla(rec, tarihler, tler)
    out = Path(a.cikti)
    out.mkdir(parents=True, exist_ok=True)
    csv_yaz(out / f"{on}ham_sonuclar.csv", sonuc["ham"], ["havuz", "N", "slot", "T", "aday_n", "kadro_n", "bos_koltuk", "kadro_getiri", "dolu_getiri", "yuzdelik",
                                                           "dolu_yuzdelik", "cikarilan_aday", "cikarilan_kontrol", "ac_toplam", "ac_yuvarlanan", "ac_atlanan", "ac_slot_tavani", "ac_hesap_yok",
                                                           "ac_tavan_kirpildi", "ac_diger", *EP_ALAN, "ideal_top", "ideal_atl", "kontrol_n", "kontrol_ortanca"])
    csv_yaz(out / f"{on}hucre_ozet.csv", sonuc["hucre"])
    csv_yaz(out / f"{on}uye_getiri.csv", sonuc["uye"], ["adres", "T", "slot", "ornek700_aday", "genis_aday", "kontrol", "kaynak", "getiri", "dusus", "islem", "tasfiye", "fiyatsiz", "ac_toplam", "ac_yuv", "ac_atl", "durum", *EP_ALAN])
    cik = Counter()
    kaynak = Counter()
    for x, d in rec.items():
        for T, r in d.items():
            kaynak[r["kaynak"]] += 1
            if r["k50"] and r["cikarildi"]:
                cik[f"{'ornek50' if r['ornek50'] else 'diger'}:{r['cikarildi']}"] += 1
    uyari = []
    riskli = sorted(x for x in hata if x in s50 or _aday_olabilir(x, tler))
    s10 = set(ornek["s10"])
    bilesim = lambda kume: {"ornek50": len(kume & s50), "s10_ornek50_degil": len((kume & s10) - s50), "diger": len(kume - s50 - s10), "toplam": len(kume)}  # noqa: E731
    genis_aday = {x["adres"] for x in sonuc["uye"] if x["genis_aday"]}
    if hata:
        uyari.append(f"{len(hata)} adres hatalı (havuzlardan hariç)")
    for hv in HAVUZLAR:
        kucuk = sorted({s["T"] for s in sonuc["ham"] if s["havuz"] == hv and s["N"] == 11 and s["slot"] == 100 and s["kontrol_n"] < 11})
        if kucuk:
            uyari.append(f"kontrol havuzu < 11: {kucuk}")
    json.dump({"boyutlar": {"adres": len(adresler), "adres_ok": len(rec), "tler": tler, "nler": NLER, "slotlar": SLOTLAR, "ham_satir": len(sonuc["ham"]),
                            "uye_satir": len(sonuc["uye"]), "ort_adres_sn": statistics.fmean(sure) if sure else None, "toplam_sn": time.time() - bas},
               "satir_kaynagi": dict(kaynak), "cikarilan_k50_satir": dict(cik), "kontrol_ac_pay_slot": sonuc["kontrol_ac"],
               "genis_bilesim_adres": bilesim(set(rec)), "genis_aday_bilesim_adres": bilesim(genis_aday), "ornek700_aday_adres": len({x["adres"] for x in sonuc["uye"] if x["ornek700_aday"]}),
               "riskli_hata_adres_sayisi": len(riskli), "hata_adres_sayisi": len(hata), "hata_ornek": dict(list(hata.items())[:5]), "uyarilar": uyari},
              open(out / f"{on}ozet.json", "w"), ensure_ascii=False, indent=1)
    print("yazıldı:", out)
    if riskli:
        print(f"HATA: ornek700 ya da olası aday adreslerde işçi hatası: {len(riskli)}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
