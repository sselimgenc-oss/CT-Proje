"""Walk-forward seçim doğrulaması — sürdürülebilir boru hattı (aşama 1–6, T12 kilidi).

    GitHub Actions: .github/workflows/secim_dogrulama.yml (5 sa dilimler, durum artifact ile taşınır). Yerel: python -u calistir.py (WF_VERI = veri dizini)
    python calistir.py --deneme 20          # küçük duman testi (ayrı klasör: deneme/)
    python calistir.py --t12-ac A,B          # (insan kararı) kilitli T12'yi verilen kollar için aç, raporu yenile

Yeniden başlatma kaldığı yerden sürer: her adres/uç diskte (cache/), ölçümler cache/olcum/.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import random
import sys
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path

import hl

KOK = Path(os.environ.get("WF_VERI") or Path(__file__).resolve().parent)   # veri dizini (Actions: geri yüklenen durum)
REPO = os.environ.get("WF_REPO") or str(Path(__file__).resolve().parents[2])   # copytrade paketi (depo kökü)
HOUR = 3_600_000
GUN = 24 * HOUR
HAFTA = 7 * GUN
DOLUM_TAVAN = 10_000            # adres başına en çok dolum (aşılırsa en yeni kısım tutulur; kapsam dışı T'ler çıkarılır)
ORNEK50, ORNEK10, TOHUM = 700, 300, 20261111
ISCI = 4


def ms_tarih(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%d")


def ms_saat(ms: float) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%d %H:%M UTC")


# ------------------------------------------------------------------------------------------------ durum (DURUM.md)
class Durum:
    def __init__(self, yol: Path, ayar: dict):
        self.yol, self.ayar = yol, ayar
        self.asama, self.yapilan, self.toplam, self.hata_n, self.not_ = "-", 0, 0, 0, ""
        self.son_hata: str | None = None
        self.t_asama = time.time()
        self.yapilan_bas = 0
        self.son_yaz = 0.0
        self.tahmin: dict[str, float] = {}
        self.istemci: hl.Istemci | None = None
        self.gecmis: list[str] = []
        self.ek: dict[str, str] = {}

    def asama_bas(self, ad: str, toplam: int, yapilan: int = 0, not_: str = ""):
        if self.asama != "-":
            self.gecmis.append(f"{self.asama}: bitti {ms_saat(time.time() * 1000)}")
        self.asama, self.toplam, self.yapilan, self.not_ = ad, toplam, yapilan, not_
        self.yapilan_bas, self.t_asama = yapilan, time.time()
        self.yaz(zorla=True)

    def ilerle(self, n: int = 1, hata: str | None = None):
        self.yapilan += n
        if hata:
            self.hata_n += 1
            self.son_hata = f"{ms_saat(time.time() * 1000)} — {hata}"
        self.yaz()

    def eta_asama(self) -> float | None:
        bitti = self.yapilan - self.yapilan_bas
        gecen = time.time() - self.t_asama
        if bitti <= 0 or gecen <= 5:
            return None
        return (self.toplam - self.yapilan) * gecen / bitti

    def yaz(self, zorla: bool = False):
        if not zorla and time.time() - self.son_yaz < 30:
            return
        self.son_yaz = time.time()
        e = self.eta_asama()
        kalan_sonraki = sum(v for k, v in self.tahmin.items() if k > self.asama[:1])
        toplam_eta = (e or 0) + kalan_sonraki
        st = self.istemci.stats if self.istemci else {}
        hiz = self.istemci.kova.hiz() if self.istemci else 0
        s = ["# DURUM — walk-forward seçim doğrulaması", "",
             f"- Güncelleme: {ms_saat(time.time() * 1000)}  (PID {os.getpid()})",
             f"- Aşama: **{self.asama}** — {self.yapilan}/{self.toplam} {self.not_}",
             f"- Aşama ETA: {'?' if e is None else f'{e / 3600:.1f} sa'} · Toplam kalan ETA (tahmin): {toplam_eta / 3600:.1f} sa"
             + (f" → bitiş ≈ {ms_saat((time.time() + toplam_eta) * 1000)}" if toplam_eta else ""),
             f"- HL: istek {st.get('istek', 0)}, 429 {st.get('429', 0)}, 5xx {st.get('5xx', 0)}, ağ {st.get('ag', 0)}, hata {st.get('hata', 0)}; ortalama ağırlık/dk {hiz:.0f} (anlık sınır {self.istemci.kova.oran * 60 if self.istemci else 0:.0f}, tavan {hl.AGIRLIK_DK})",
             f"- Adres hataları (bu aşama dahil toplam): {self.hata_n}",
             f"- Son hata: {self.son_hata or '-'}", "",
             f"- Çapa (şimdi): {ms_saat(self.ayar['simdi'])}; T1…T12: {', '.join(ms_tarih(t) for t in self.ayar['tarihler'])} (T12 kilitli)",
             "- Sonraki aşamalar tahmini (sa): " + (", ".join(f"{k}: {v / 3600:.1f}" for k, v in sorted(self.tahmin.items())) or "-"), ""]
        if self.gecmis:
            s += ["## Geçmiş", *[f"- {g}" for g in self.gecmis], ""]
        for baslik, metin in self.ek.items():
            s += [f"## {baslik}", metin, ""]
        tmp = self.yol.with_suffix(".tmp")
        tmp.write_text("\n".join(s) + "\n", encoding="utf-8")
        tmp.replace(self.yol)


# ------------------------------------------------------------------------------------------------ ayar (çapa)
def ayar_oku(klasor: Path) -> dict:
    p = klasor / "ayar.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    simdi = int(time.time() * 1000) // HOUR * HOUR
    t12 = simdi // GUN * GUN - 28 * GUN
    tarihler = [t12 - (11 - i) * HAFTA for i in range(12)]
    a = {"simdi": simdi, "tarihler": tarihler, "dolum_bas": tarihler[0] - 56 * GUN - GUN, "mum_bas": tarihler[0] - 56 * GUN - 7 * GUN,
         "olusturma": ms_saat(time.time() * 1000)}
    p.write_text(json.dumps(a, indent=1), encoding="utf-8")
    return a


# ------------------------------------------------------------------------------------------------ aşama 1: lider tablosu + meta
def asama1(ist: hl.Istemci, durum: Durum) -> tuple[list[dict], dict]:
    durum.asama_bas("1 lider tablosu + meta", 2)
    lb = hl.oku("tek", "leaderboard")
    if lb is None:
        rows = ist.leaderboard()
        lb = {"zaman": int(time.time() * 1000), "satirlar": rows}
        hl.yaz("tek", "leaderboard", lb)
    durum.ilerle()
    meta = hl.oku("tek", "meta")
    if meta is None:
        sys.path.insert(0, REPO)
        from copytrade import izleme_motoru as im
        from copytrade.izleme_liste import perp_dex_names
        dexler = perp_dex_names(ist.info({"type": "perpDexs"}, weight=20))
        meta = {"dexler": dexler, "azami": im.azami_kaldirac_oku(ist, dexler)}
        hl.yaz("tek", "meta", meta)
    durum.ilerle()
    return lb["satirlar"], meta


def pencere(satir: dict, ad: str, alan: str) -> float:
    try:
        return float(dict(satir.get("windowPerformances") or [])[ad][alan])
    except (KeyError, TypeError, ValueError):
        return 0.0


def evren_kur(rows: list[dict]) -> tuple[list[str], dict]:
    """Hayatta kalma yanlılığını azaltmak için: bugün ≥ 10k (ve ömür hacmi > 0) + bugün < 10k olup ömür perp pnl ≤ −10k ya da ömür hacmi ≥ 50M $ olanlar."""
    u1, u2 = [], []
    for r in rows:
        a = str(r.get("ethAddress", "")).lower()
        if not a.startswith("0x"):
            continue
        try:
            av = float(r.get("accountValue") or 0)
        except ValueError:
            continue
        vlm, pnl = pencere(r, "allTime", "vlm"), pencere(r, "allTime", "pnl")
        if av >= 10_000 and vlm > 0:
            u1.append((-av, a))
        elif av < 10_000 and (pnl <= -10_000 or vlm >= 50e6):
            u2.append((-vlm, a))
    adres = [a for _, a in sorted(u1)] + [a for _, a in sorted(u2)]
    bilgi = {"lider_tablosu": len(rows), "bugun_10k_ustu_islemli": len(u1), "bugun_10k_alti_buyuk_zarar_ya_da_hacim": len(u2), "evren": len(adres)}
    return adres, bilgi


# ------------------------------------------------------------------------------------------------ aşama 2: portfolio
def tahmin_guncelle(adresler: list[str], durum: Durum, ayar: dict | None) -> None:
    """Rastgele sıralı aşama 2 sürerken: okunan portfolio'lardan dolum setinin (aşama 3) boyutu ve süresi tahmini."""
    if not ayar:
        return
    import olcum
    okunan = [a for a in adresler if hl.var_mi("portfolio", a)]
    orn = random.Random(1).sample(okunan, min(1500, len(okunan)))
    kural = olcum.load_rules()
    n_aday = 0
    for a in orn:
        pf = hl.oku("portfolio", a)
        try:
            n_aday += olcum.dolum_gerekli(olcum.portfolio_tarihleri(pf, ayar["tarihler"] + [ayar["simdi"]], kural))
        except Exception:  # noqa: BLE001
            pass
    oran = n_aday / max(len(orn), 1)
    set_n = oran * len(adresler) + ORNEK50 + ORNEK10
    w = ORT_DOLUM_AGIRLIK
    durum.tahmin["3"] = set_n * w / (hl.AGIRLIK_DK * 0.9) * 60
    durum.tahmin["4"] = 500 * 450 / (hl.AGIRLIK_DK * 0.9) * 60
    durum.tahmin["5"] = set_n * 2.0 / ISCI
    durum.ek["Tahmin (aşama 2 örnekleminden)"] = (f"- {len(orn)} okunmuş portfolio'da ucuz kural adayı oranı {oran:.3f} → dolum seti ≈ {set_n:.0f} adres "
                                                  f"(× ~{w} ağırlık/adres ≈ {durum.tahmin['3'] / 3600:.1f} sa); mum+funding ≈ {durum.tahmin['4'] / 3600:.1f} sa; ölçüm ≈ {durum.tahmin['5'] / 3600:.1f} sa")
    durum.yaz(zorla=True)


ORT_DOLUM_AGIRLIK = 350          # duman testinde (20 aktif ≥ 50k hesap) ortalama 5.8k dolum ≈ 350 ağırlık


def asama2(ist: hl.Istemci, adresler: list[str], durum: Durum, ayar: dict | None = None) -> list[str]:
    eksik = [a for a in adresler if not hl.var_mi("portfolio", a)]
    random.Random(TOHUM).shuffle(eksik)                 # rastgele sıra: kısmi ilerleme tarafsız boyut tahmini verir
    durum.asama_bas("2 portfolio", len(adresler), len(adresler) - len(eksik))
    hatali = []
    if ayar and len(adresler) - len(eksik) > 300:
        tahmin_guncelle(adresler, durum, ayar)
    for tur in (1, 2):
        for i, a in enumerate(eksik, 1):
            try:
                hl.yaz("portfolio", a, ist.portfolio(a))
                durum.ilerle()
                if i in (300, 1000) or i % 3000 == 0:
                    tahmin_guncelle(adresler, durum, ayar)
            except Exception as h:  # noqa: BLE001
                hatali.append(a)
                durum.ilerle(0, f"portfolio {a[:10]}…: {h}")
        eksik, hatali = hatali, []
        if not eksik:
            break
    return eksik


# ------------------------------------------------------------------------------------------------ portfolio özeti (paralel)
def _po_isci(arg):
    a, tarihler = arg
    import olcum
    pf = hl.oku("portfolio", a)
    if pf is None:
        return a, None
    try:
        po = olcum.portfolio_tarihleri(pf, tarihler, olcum.load_rules())
    except Exception:  # noqa: BLE001
        return a, None
    return a, {str(T): {k: v[k] for k in ("r1_A", "r1_D", "r2", "k50", "k10")} for T, v in po.items()}


def po_ozet(adresler: list[str], tarihler_bugun: list[int], durum: Durum, klasor: Path) -> dict:
    p = klasor / "po_ozet.json"
    eski = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    eksik = [a for a in adresler if a not in eski and hl.var_mi("portfolio", a)]
    durum.asama_bas("2b portfolio özeti (ucuz kurallar)", len(adresler), len(adresler) - len(eksik))
    with mp.Pool(ISCI) as havuz:
        for i, (a, po) in enumerate(havuz.imap_unordered(_po_isci, [(a, tarihler_bugun) for a in eksik], chunksize=50), 1):
            eski[a] = po
            durum.ilerle()
            if i % 2000 == 0:
                p.write_text(json.dumps(eski), encoding="utf-8")
    p.write_text(json.dumps(eski), encoding="utf-8")
    return eski


# ------------------------------------------------------------------------------------------------ aşama 3: dolumlar
def dolum_cek(ist: hl.Istemci, a: str, bas: int, bit: int) -> dict:
    """Önce [bas, bit] artan; ilk sayfa doluysa (yoğun hesap) yeniden eskiye haftalık-uyarlanır parçalarla, DOLUM_TAVAN'a dek (en yeni kısım tutulur)."""
    ilk, kes = ist.dolum_aralik(a, bas, bit, tavan=2000)
    if not kes:
        return {"bas": bas, "bit": bit, "kapsam_bas": bas, "kesildi": False, "dolumlar": ilk}
    ts = [int(f["time"]) for f in ilk]
    yogunluk = len(ilk) / max(max(ts) - bas, HOUR)                     # dolum/ms (alt sınır tahmini)
    parca = max(GUN, min(14 * GUN, int(1800 / max(yogunluk, 1e-12)) // GUN * GUN))
    out, seen, kapsam, kesildi, ust = [], set(), bit, False, bit
    while ust > bas:
        alt = max(bas, ust - parca)
        d, k = ist.dolum_aralik(a, alt, ust, tavan=DOLUM_TAVAN - len(out) + 2000)
        for f in d:
            key = str(f.get("tid"))
            if key not in seen:
                seen.add(key); out.append(f)
        if k or len(out) >= DOLUM_TAVAN:
            kesildi = True
            if k:                                       # parça tamamlanmadı: kapsam bu parçanın ÜST sınırı (parçanın eski kısmı eksik)
                kapsam = ust
                out = [f for f in out if int(f["time"]) >= ust]
            else:
                kapsam = alt
            break
        kapsam, ust = alt, alt
    return {"bas": bas, "bit": bit, "kapsam_bas": kapsam, "kesildi": kesildi, "dolumlar": sorted(out, key=lambda f: int(f["time"]))}


ATILAN = ("hash", "feeToken", "twapId", "builderFee", "cloid")


def asama3(ist: hl.Istemci, adresler: list[str], ayar: dict, durum: Durum) -> list[str]:
    eksik = [a for a in adresler if not hl.var_mi("dolum", a)]
    durum.asama_bas("3 dolumlar", len(adresler), len(adresler) - len(eksik))
    w0 = ist.kova.toplam
    hatali = []
    for tur in (1, 2):
        for i, a in enumerate(eksik, 1):
            try:
                d = dolum_cek(ist, a, ayar["dolum_bas"], ayar["simdi"])
                d["dolumlar"] = [{k: v for k, v in f.items() if k not in ATILAN} for f in d["dolumlar"]]
                hl.yaz("dolum", a, d)
                durum.ilerle()
            except Exception as h:  # noqa: BLE001
                hatali.append(a)
                durum.ilerle(0, f"dolum {a[:10]}…: {h}")
            if i % 25 == 0 and tur == 1:
                agirlik = (ist.kova.toplam - w0) / i
                durum.tahmin["3"] = 0
                durum.ek["Aşama 3 ölçümü"] = (f"- Adres başına ortalama ağırlık: {agirlik:.0f} → kalan {len(eksik) - i} adres ≈ "
                                               f"{(len(eksik) - i) * agirlik / hl.AGIRLIK_DK / 60:.1f} sa (hız sınırıyla)")
        eksik, hatali = hatali, []
        if not eksik:
            break
    return eksik


# ------------------------------------------------------------------------------------------------ aşama 4: mum + funding
def asama4(ist: hl.Istemci, adresler: list[str], ayar: dict, durum: Durum) -> None:
    sys.path.insert(0, REPO)
    from copytrade.olcut import is_hip3
    from olcum import perp_fills
    p = KOK / "coinler.json"
    if p.exists() and json.loads(p.read_text())["n"] == len(adresler):
        coinler = json.loads(p.read_text())["coinler"]
    else:
        cs = set()
        durum.asama_bas("4a coin listesi", len(adresler))
        for a in adresler:
            d = hl.oku("dolum", a)
            if d:
                cs |= {str(f["coin"]) for f in perp_fills(d["dolumlar"])}
            durum.ilerle()
        coinler = sorted(cs)
        p.write_text(json.dumps({"n": len(adresler), "coinler": coinler}), encoding="utf-8")
    isler = [("mum", c) for c in coinler] + [("funding", c) for c in coinler if not is_hip3(c)]
    eksik = [(u, c) for u, c in isler if not hl.var_mi(u, c.replace(":", "_").replace("/", "_"))]
    durum.asama_bas("4 mum + funding", len(isler), len(isler) - len(eksik))
    for u, c in eksik:
        anahtar = c.replace(":", "_").replace("/", "_")
        try:
            if u == "mum":
                rows = ist.candles(c, ayar["mum_bas"], ayar["simdi"], "1h")
                hl.yaz("mum", anahtar, {"coin": c, "mumlar": [{"t": int(r["t"]), "o": r["o"], "c": r["c"], "v": r["v"]} for r in rows]})
            else:
                out, imlec = [], ayar["mum_bas"]
                while True:
                    sf = ist.info({"type": "fundingHistory", "coin": c, "startTime": imlec, "endTime": ayar["simdi"]}, weight=20) or []
                    out += [{"time": int(r["time"]), "fundingRate": r["fundingRate"]} for r in sf]
                    if len(sf) < 500:
                        break
                    imlec = int(sf[-1]["time"]) + 1
                hl.yaz("funding", anahtar, {"coin": c, "satirlar": out})
            durum.ilerle()
        except Exception as h:  # noqa: BLE001
            durum.ilerle(0, f"{u} {c}: {h}")


# ------------------------------------------------------------------------------------------------ aşama 5: ölçüm (paralel, önbellekten)
_KAY = None


def _olc_isci(arg):
    global _KAY
    a, ayar, ornek50, ornek10, ileri, uc = arg
    import olcum
    try:
        if _KAY is None:
            meta = hl.oku("tek", "meta") or {}
            _KAY = olcum.Kaynak(ayar["mum_bas"], ayar["simdi"], meta.get("azami"))
        pf = hl.oku("portfolio", a)
        dk = hl.oku("dolum", a)
        tarihler = ayar["tarihler"] + [ayar["simdi"]]
        t0 = time.time()
        r = olcum.adres_olc(a, pf, dk, tarihler, ayar["simdi"], ornek50, ornek10, _KAY, set(ileri))
        hl.yaz(uc, a, {"adres": a, "sure": time.time() - t0, "T": {str(k): v for k, v in r.items()}})
        return a, None
    except Exception as h:  # noqa: BLE001
        return a, f"{type(h).__name__}: {h} | {traceback.format_exc()[-400:]}"


def asama5(adresler: list[str], ayar: dict, ornek: dict, durum: Durum, ileri: list[int], uc: str = "olcum", isci: int = ISCI) -> list[str]:
    eksik = [a for a in adresler if not hl.var_mi(uc, a)]
    durum.asama_bas(f"5 ölçüm ({uc})", len(adresler), len(adresler) - len(eksik))
    hatali = []
    isler = [(a, ayar, a in ornek["s50"], a in ornek["s10"], ileri, uc) for a in eksik]
    with mp.Pool(isci, maxtasksperchild=200) as havuz:
        for a, h in havuz.imap_unordered(_olc_isci, isler, chunksize=2):
            if h:
                hatali.append(a)
                (KOK / "olcum_hatalari.log").open("a", encoding="utf-8").write(f"{a} {h}\n")
            durum.ilerle(1, f"ölçüm {a[:10]}…: {h[:150]}" if h else None)
    return hatali


# ------------------------------------------------------------------------------------------------ ana akış
def ornek_sec(po: dict, tarihler: list[int]) -> dict:
    k50 = sorted(a for a, v in po.items() if v and any(v[str(T)]["k50"] for T in tarihler))
    k10 = sorted(a for a, v in po.items() if v and any(v[str(T)]["k10"] for T in tarihler))
    r = random.Random(TOHUM)
    s50 = r.sample(k50, min(ORNEK50, len(k50)))
    s10 = r.sample(k10, min(ORNEK10, len(k10)))
    return {"k50_herhangi": len(k50), "k10_herhangi": len(k10), "s50": s50, "s10": s10}


def calistir(a) -> int:
    klasor = KOK
    ayar = ayar_oku(klasor)
    durum = Durum(klasor / "DURUM.md", ayar)
    ist = hl.Istemci()
    durum.istemci = ist
    tarihler, simdi = ayar["tarihler"], ayar["simdi"]
    rows, meta = asama1(ist, durum)
    evren_p = klasor / "evren.json"
    if evren_p.exists():
        ev = json.loads(evren_p.read_text())
    else:
        adresler, bilgi = evren_kur(rows)
        ev = {"bilgi": bilgi, "adresler": adresler}
        evren_p.write_text(json.dumps(ev), encoding="utf-8")
    adresler = ev["adresler"]
    n = len(adresler)
    durum.tahmin = {"2": (n - sum(1 for x in adresler if hl.var_mi("portfolio", x))) * 20 / hl.AGIRLIK_DK * 60, "3": 0, "4": 0, "5": 0}
    asama2(ist, adresler, durum, ayar)
    durum.tahmin.pop("2", None)
    po = po_ozet(adresler, tarihler + [simdi], durum, klasor)
    ornek_p = klasor / "ornek.json"
    if ornek_p.exists():
        ornek = json.loads(ornek_p.read_text())
    else:
        ornek = ornek_sec(po, tarihler)
        ornek_p.write_text(json.dumps(ornek), encoding="utf-8")
    aday = sorted(a for a, v in po.items() if v and any(x["r1_D"] and x["r2"] for x in v.values()))
    dolum_set = list(dict.fromkeys(ornek["s50"] + ornek["s10"] + aday))
    boy = {**ev["bilgi"], "portfolio_okunan": sum(1 for v in po.values() if v), "k50_herhangi_T": ornek["k50_herhangi"], "k10_herhangi_T": ornek["k10_herhangi"],
           "ornek50": len(ornek["s50"]), "ornek10": len(ornek["s10"]), "ucuz_kural_adayi_(>=10k ve kural2, herhangi T)": len(aday), "dolum_seti": len(dolum_set)}
    (klasor / "boyutlar.json").write_text(json.dumps(boy, indent=1, ensure_ascii=False), encoding="utf-8")
    durum.tahmin = {"3": len([x for x in dolum_set if not hl.var_mi("dolum", x)]) * ORT_DOLUM_AGIRLIK / (hl.AGIRLIK_DK * 0.9) * 60,
                    "4": 600 * 300 / hl.AGIRLIK_DK * 60, "5": len(dolum_set) * 4.0 / ISCI}
    durum.ek["Boyutlar (evren ve örneklem)"] = "\n".join(f"- {k}: {v}" for k, v in boy.items())
    asama3(ist, dolum_set, ayar, durum)
    durum.tahmin.pop("3", None)
    asama4(ist, dolum_set, ayar, durum)
    durum.tahmin.pop("4", None)
    ileri = tarihler[:11]                                           # T12 KİLİTLİ: ileri ölçüm yok
    asama5(dolum_set, ayar, ornek, durum, ileri)
    durum.tahmin.pop("5", None)
    import rapor
    durum.asama_bas("6 rapor", 1)
    acilacak = rapor.uret(klasor, ayar, ornek, dolum_set, boy, tur="tur1")
    if acilacak:
        durum.asama_bas(f"7 T12 açılıyor ({','.join(acilacak)})", 1)
        t12_ac(klasor, ayar, ornek, dolum_set, boy, acilacak, durum)
    durum.asama_bas("BİTTİ — RAPOR.md hazır", 1, 1)
    return 0


def t12_ac(klasor, ayar, ornek, dolum_set, boy, kollar, durum):
    import rapor
    (klasor / "t12_acik.json").write_text(json.dumps({"kollar": kollar, "zaman": ms_saat(time.time() * 1000)}), encoding="utf-8")
    asama5(dolum_set, ayar, ornek, durum, [ayar["tarihler"][11]], uc="olcum_t12")
    rapor.uret(klasor, ayar, ornek, dolum_set, boy, tur="son", t12_kollar=kollar)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deneme", type=int, default=0, help="duman testi: N adres, 2 tarih")
    ap.add_argument("--t12-ac", default=None)
    a = ap.parse_args()
    if a.deneme:
        import deneme
        return deneme.kos(a.deneme)
    if a.t12_ac:
        ayar = ayar_oku(KOK)
        ornek = json.loads((KOK / "ornek.json").read_text())
        po = json.loads((KOK / "po_ozet.json").read_text())
        aday = sorted(x for x, v in po.items() if v and any(y["r1_D"] and y["r2"] for y in v.values()))
        dolum_set = list(dict.fromkeys(ornek["s50"] + ornek["s10"] + aday))
        boy = json.loads((KOK / "boyutlar.json").read_text())
        d = Durum(KOK / "DURUM.md", ayar)
        t12_ac(KOK, ayar, ornek, dolum_set, boy, a.t12_ac.split(","), d)
        return 0
    try:
        return calistir(a)
    except Exception:
        (KOK / "DURUM.md").open("a", encoding="utf-8").write(f"\n\n## ÇÖKTÜ {ms_saat(time.time() * 1000)}\n```\n{traceback.format_exc()[-3000:]}\n```\n")
        raise


if __name__ == "__main__":
    sys.exit(main())
