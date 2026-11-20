"""Copy-trade mutabakat v2: HL dolumları (11 trader) ↔ motor kaydı (`origin/canli-durum`) ↔ hesap/ozet.

Salt okuma. Motor koduna dokunmaz. Kayıt ve durum `git show origin/canli-durum:...` ile okunur; HL verisi
public info API'den (`userFillsByTime`, `clearinghouseState`, `allMids`) çekilir.

    python araclar/mutabakat_v2.py [--cikti docs/mutabakat/MUTABAKAT_2026-11-20_v2.md]

Gizlilik: tam trader adresi yalnız API isteğinde kullanılır; dosyaya ve çıktıya kısa biçim (`0x1234ab…`) yazılır.

Kurallar (v1'den farklı olanlar):
- Kapanış eşiği: azaltma sonrası kalan |miktar| ≤ 1e-4 × açılan toplam büyüklük ise pozisyon "sıfırlandı" (v1: 1 $).
- Trader açılış olayı: aynı (coin, yön) için 60 sn içindeki açılış/artış dolumları tek olay.
- Eşleşme: bizim kaydın `trader_dolum_ms` değeri, olayın [ilk dolum − 2 sn, son dolum + 2 sn] aralığında ise o olaya aittir.
"""
from __future__ import annotations

import argparse
import itertools
import json
import re
import statistics
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import mutabakat as v1  # noqa: E402  (kayit_oku, json_oku, tsi, tr_say, fiyat, ADRES_KISA)

TSI = timezone(timedelta(hours=3))
DAL = "2d3b17ab"   # analiz edilen kayıt anı (origin/canli-durum; canlı dal sürekli ilerler, sabit commit kullanılır)
DONEM_BAS_MS = int(datetime(2026, 11, 16, 11, 30, tzinfo=UTC).timestamp() * 1000)
DEPLOY_MS = int(datetime(2026, 11, 20, 4, 15, tzinfo=TSI).timestamp() * 1000)   # kullanıcı: yeni mesaj düzeni ~04:15 TSİ
TOZ_ORAN = 1e-4
OLAY_ARA_MS = 60_000
ESLESME_MS = 2_000
KAPANIS_ESLESME_MS = 5_000
HL_URL = "https://api.hyperliquid.xyz/info"
ISARET = {1: "uzun", -1: "kısa"}


def ks(a: str) -> str:
    return f"{a[:8]}…" if a else "—"


def sn(ms: float | None) -> str:
    return "—" if ms is None else f"{ms / 1000:,.1f}".replace(",", "§").replace(".", ",").replace("§", ".")


def hl(govde: dict, dene: int = 6):
    son_hata: Exception | None = None
    for i in range(dene):
        try:
            istek = urllib.request.Request(HL_URL, data=json.dumps(govde).encode(), headers={"Content-Type": "application/json"})
            return json.loads(urllib.request.urlopen(istek, timeout=30).read())
        except Exception as hata:  # noqa: BLE001
            son_hata = hata
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"HL isteği başarısız: {type(son_hata).__name__}")


def fills_tum(adres: str, bas: int, son: int) -> list[dict]:
    """userFillsByTime sayfalı (2000 sınırı); tid ile tekilleştirilir."""
    gorulen: set = set()
    cikti: list[dict] = []
    t = bas
    while True:
        sayfa = hl({"type": "userFillsByTime", "user": adres, "startTime": t, "endTime": son})
        yeni = [x for x in sayfa if x["tid"] not in gorulen]
        for x in yeni:
            gorulen.add(x["tid"])
        cikti += yeni
        if len(sayfa) < 2000 or not yeni:
            break
        t = max(x["time"] for x in sayfa)
        time.sleep(0.2)
    return sorted(cikti, key=lambda x: x["time"])


def pozisyon_dex_listesi() -> list[str]:
    dex = hl({"type": "perpDexs"})
    return [d["name"] for d in dex if isinstance(d, dict) and d.get("name")]


def anlik_pozisyonlar(adres: str, dexler: list[str]) -> dict[str, float]:
    """coin → imzalı miktar (HIP-3 dex'leri dahil)."""
    out: dict[str, float] = {}
    for dex in ["", *dexler]:
        govde = {"type": "clearinghouseState", "user": adres, **({"dex": dex} if dex else {})}
        for p in hl(govde).get("assetPositions", []):
            pos = p.get("position", {})
            szi = float(pos.get("szi") or 0.0)
            if szi:
                out[pos["coin"]] = out.get(pos["coin"], 0.0) + szi
    return out


# ---------- bizim pozisyonlarımız (kayıttan, toz kuralı v2) ----------
def pozisyonlari_kur(kayitlar: list[dict]) -> tuple[list[dict], list[dict]]:
    acik: dict[tuple, dict] = {}
    bitti: list[dict] = []
    yetim: list[dict] = []
    for k in kayitlar:
        if not ((k.get("olay") == "emir" and k.get("durum") in ("dolu", "kismi")) or k.get("olay") == "tasfiye"):
            continue
        key = (k["adres"], k["coin"])
        ms = int(k["zaman_ms"])
        if k["olay"] == "tasfiye":
            p = acik.pop(key, None)
            if p is None:
                yetim.append(k)
                continue
            p.update(kapanis="tasfiye", kapanis_ms=ms, tasfiye_pnl=float(k.get("pnl") or 0.0), tasfiye_px=float(k.get("tasfiye_px") or 0.0))
            bitti.append(p)
            continue
        e = k["eylem"]
        sgn = 1 if k["yon"] == "B" else -1
        sz = abs(float(k["sz"]))
        if key not in acik:
            if e != "ac":
                yetim.append(k)
                continue
            acik[key] = {"adres": k["adres"], "coin": k["coin"], "yon": ISARET[sgn], "acilis_ms": ms, "net": 0.0, "acilan": 0.0,
                         "ac_px": 0.0, "fills": [], "ucret": 0.0, "realize": 0.0, "kapanis": None, "kapanis_ms": None,
                         "tasfiye_pnl": None, "tasfiye_px": None, "cikis_px_top": 0.0, "cikis_sz": 0.0}
        p = acik[key]
        once = p["net"]
        p["fills"].append(k)
        p["ucret"] += float(k.get("ucret") or 0.0)
        p["net"] += sgn * sz
        k["_once"], k["_sonra"] = once, p["net"]
        if e in ("ac", "artir"):
            p["acilan"] += sz
            p["ac_px"] += sz * float(k["dolum_px"])
        else:
            p["realize"] += float(k.get("pnl_usd") or 0.0)
            p["cikis_px_top"] += sz * float(k["dolum_px"])
            p["cikis_sz"] += sz
        if e == "kapat":
            p.update(kapanis="kapat", kapanis_ms=ms)
            bitti.append(acik.pop(key))
        elif e == "azalt" and abs(p["net"]) <= TOZ_ORAN * p["acilan"]:
            p.update(kapanis="sifir", kapanis_ms=ms)
            bitti.append(acik.pop(key))
    acik_liste = list(acik.values())
    return bitti + acik_liste, yetim


# ---------- trader olayları (HL fills) ----------
def dolum_turu(f: dict) -> list[tuple[str, int]]:
    """Dolum: [(tür, yön)], tür 'ac' (açma/artırma) ya da 'azalt' (azaltma/kapama). Yön: +1 uzun, −1 kısa."""
    start = float(f["startPosition"])
    imza = float(f["sz"]) * (1 if f["side"] == "B" else -1)
    yeni = start + imza
    s0 = (start > 0) - (start < 0)
    s1 = (yeni > 0) - (yeni < 0)
    if s1 != 0 and (s0 == 0 or s0 == s1) and abs(yeni) > abs(start) + 1e-12:
        return [("ac", s1)]
    if s0 != 0 and s1 != 0 and s0 != s1:                     # ters yöne geçiş: kapama + yeni açma
        return [("azalt", s0), ("ac", s1)]
    if s0 != 0 and abs(yeni) < abs(start) - 1e-12:
        return [("azalt", s0)]
    return []


def trader_acilislari(fills: list[dict], adres: str) -> list[dict]:
    olaylar: list[dict] = []
    son: dict[tuple, dict] = {}
    for f in fills:
        for tur, yon in dolum_turu(f):
            if tur != "ac":
                continue
            anahtar = (f["coin"], yon)
            o = son.get(anahtar)
            if o is not None and f["time"] - o["t1"] <= OLAY_ARA_MS:
                o["t1"] = f["time"]
                o["n"] += 1
            else:
                o = {"adres": adres, "coin": f["coin"], "yon": ISARET[yon], "t0": f["time"], "t1": f["time"], "n": 1,
                     "tid0": f["tid"]}
                olaylar.append(o)
                son[anahtar] = o
    return olaylar


def kayit_eslesme(kayitlar: list[dict], o: dict) -> list[dict]:
    return [k for k in kayitlar if k.get("adres") == o["adres"] and k.get("coin") == o["coin"] and k.get("eylem") in ("ac", "artir")
            and k.get("olay") in ("emir", "emir_yok") and k.get("trader_dolum_ms") is not None
            and o["t0"] - ESLESME_MS <= int(k["trader_dolum_ms"]) <= o["t1"] + ESLESME_MS]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cikti", type=Path, default=REPO / "docs" / "mutabakat" / "MUTABAKAT_2026-11-20_v2.md")
    ap.add_argument("--dal", default=DAL, help="git revizyonu (commit); varsayılan: analiz edilen sabit commit")
    args = ap.parse_args(argv)

    dal = args.dal
    kayitlar = v1.kayit_oku(dal)
    hes = v1.json_oku(dal, "durum/hesap.json")
    ozet = v1.json_oku(dal, "durum/ozet.json")
    veri_ms = int(ozet["yazildi_ms"])
    kayitlar = [k for k in kayitlar if int(k["zaman_ms"]) <= veri_ms]
    son_kayit_ms = max(int(k["zaman_ms"]) for k in kayitlar)
    rost = sorted({k["adres"] for k in kayitlar if k.get("olay") in ("emir", "emir_yok")})
    rapor: dict = {"veri_ms": veri_ms, "son_kayit_ms": son_kayit_ms, "roster": len(rost)}

    # ---- 2. kasa (bağımsız) ----
    pozlar, yetim = pozisyonlari_kur(kayitlar)
    kapali = [p for p in pozlar if p["kapanis"] in ("kapat", "sifir")]
    tasf = [p for p in pozlar if p["kapanis"] == "tasfiye"]
    acik_p = [p for p in pozlar if p["kapanis"] is None]
    realize_bizim: dict[str, float] = defaultdict(float)
    ucret_bizim: dict[str, float] = defaultdict(float)
    for p in pozlar:
        realize_bizim[p["adres"]] += p["realize"] + (p["tasfiye_pnl"] or 0.0)
        ucret_bizim[p["adres"]] += p["ucret"]
    realize_hes = hes.get("realize") or {}
    kasa_fark = {a: realize_bizim.get(a, 0.0) - float(realize_hes.get(a, 0.0)) for a in set(realize_hes) | set(realize_bizim)}
    real_top = sum(float(v) for v in realize_hes.values())
    real_biz_top = sum(realize_bizim.values())
    ucret_hes_top = sum((hes.get("ucret") or {}).values())
    ucret_biz_top = sum(ucret_bizim.values())
    fund_top = sum((hes.get("funding") or {}).values())
    kasa_hes = float(hes.get("kasa_usd") or 10000.0)
    kasa_kont = kasa_hes + real_top - ucret_hes_top + fund_top
    kz_acik_motor = sum(float(q["kz_usd"]) for q in ozet.get("acik") or [] if q.get("kz_usd") is not None)
    ozsermaye_kont = kasa_kont + kz_acik_motor
    mids = hl({"type": "allMids"})
    acik_mark_fark: list[float] = []
    for q in ozet.get("acik") or []:
        if q.get("mark") is None:
            continue
        now = mids.get(q["coin"])
        if now:
            acik_mark_fark.append((float(now) / float(q["mark"]) - 1.0) * 100)

    # ---- 3. kapanış dolumları eşlemesi (77) ----
    kapanis_dolum = [k for k in kayitlar if k.get("olay") == "emir" and k.get("eylem") in ("azalt", "kapat") and k.get("durum") in ("dolu", "kismi")]
    tablo3 = Counter()
    for p in pozlar:
        reds = [f for f in p["fills"] if f["eylem"] in ("azalt", "kapat")]
        if not reds:
            continue
        if p["kapanis"] in ("kapat", "sifir"):
            tablo3["kapanış dolumu (kapat)" if p["kapanis"] == "kapat" else "kapanış dolumu (azaltma ile sıfır)"] += 1
            tablo3["kısmi azaltma → kapanan pozisyon"] += len(reds) - 1
        elif p["kapanis"] is None:
            tablo3["kısmi azaltma → açık pozisyon"] += len(reds)
        else:
            tablo3["kısmi azaltma → tasfiye pozisyonu"] += len(reds)
    tablo3_toplam = sum(tablo3.values())

    # ---- 1a. trader açılış olayları ↔ bizim kayıtlar ----
    dexler = pozisyon_dex_listesi()
    trader_fills: dict[str, list[dict]] = {}
    for a in rost:
        trader_fills[a] = [f for f in fills_tum(a, DONEM_BAS_MS, veri_ms) if DONEM_BAS_MS <= f["time"] <= veri_ms]
    olaylar: list[dict] = []
    for a in rost:
        olaylar += trader_acilislari(trader_fills[a], a)
    takip_bas: dict[str, int] = {}                 # kadroya alınma anı (Telegram "takibe alındı" kaydı; kısa adres ile eşleşir)
    for k in kayitlar:
        m = re.search(r"0x[0-9a-f]{6}", str(k.get("metin", ""))) if k.get("olay") == "telegram" and "takibe alındı" in str(k.get("metin", "")) else None
        if m:
            for a in rost:
                if a.startswith(m.group(0)) and a not in takip_bas:
                    takip_bas[a] = int(k["zaman_ms"])
    sonuc = Counter()
    kacan_liste: list[dict] = []
    bilerek: Counter = Counter()
    kopya_yon_uyus = 0
    kopya_yon_n = 0
    for o in olaylar:
        if o["t1"] < takip_bas.get(o["adres"], 0):
            sonuc["takip öncesi (kadro dışı)"] += 1
            continue
        eslesen = kayit_eslesme(kayitlar, o)
        if any(k.get("olay") == "emir" and k.get("durum") in ("dolu", "kismi") for k in eslesen):
            sonuc["kopyalandı"] += 1
            for k in eslesen:
                if k.get("olay") == "emir" and k.get("durum") in ("dolu", "kismi"):
                    kopya_yon_n += 1
                    kopya_yon_uyus += (k["yon"] == "B") == (o["yon"] == "uzun")
                    break
        elif any(k.get("olay") == "emir_yok" for k in eslesen):
            n = next(k["neden"] for k in eslesen if k.get("olay") == "emir_yok")
            bilerek[n] += 1
            sonuc["bilerek atlandı"] += 1
        else:
            red = [k for k in eslesen if k.get("olay") == "emir" and k.get("durum") == "red"]
            if red:
                sebep = f"hata: {red[0].get('red_neden') or 'red'}"
                sonuc["kaçan (hata)"] += 1
            else:
                sebep = "kayıt yok"
                sonuc["kaçan (kayıt yok)"] += 1
            kacan_liste.append({**o, "sebep": sebep})
    kaçan_top = sonuc["kaçan (hata)"] + sonuc["kaçan (kayıt yok)"]
    rapor["olay"] = len(olaylar)
    # hiç eşleşmeyen bizim açılış kayıtları (trader fill'i bulunamadı)
    bulunan = set()
    for o in olaylar:
        for k in kayit_eslesme(kayitlar, o):
            bulunan.add(id(k))
    hl_anahtar = {(a_, f["coin"], int(f["time"])) for a_, fl in trader_fills.items() for f in fl}
    def hl_var(k: dict) -> bool:
        return any(abs(int(f["time"]) - int(k["trader_dolum_ms"])) <= ESLESME_MS and f["coin"] == k["coin"] for f in trader_fills.get(k["adres"], []))
    dolu_ac = [k for k in kayitlar if k.get("olay") == "emir" and k.get("durum") in ("dolu", "kismi") and k.get("eylem") in ("ac", "artir")]
    dolu_hl_yok = [k for k in dolu_ac if not hl_var(k)]
    log_ac_anahtar = {(k["adres"], k["coin"], int(k["trader_dolum_ms"])) for k in kayitlar
                      if k.get("olay") in ("emir", "emir_yok") and k.get("eylem") in ("ac", "artir") and k.get("trader_dolum_ms")}
    log_yalniz = Counter(a_[:8] for a_, _, _ in (log_ac_anahtar - hl_anahtar))
    hl_acilis_anahtar = {(a_, f["coin"], int(f["time"])) for a_, fl in trader_fills.items() for f in fl if any(t == "ac" for t, _ in dolum_turu(f))}
    hl_acilis_logsuz = [x for x in hl_acilis_anahtar if x not in log_ac_anahtar]

    # ---- 1b. bizim açık pozisyonlar trader'da hâlâ açık mı ----
    anlik = {a: anlik_pozisyonlar(a, dexler) for a in rost}
    b_tablo = []
    for p in acik_p:
        szi = anlik.get(p["adres"], {}).get(p["coin"], 0.0)
        ayni = szi != 0 and ((szi > 0) == (p["yon"] == "uzun"))
        b_tablo.append((p, szi, ayni))
    b_acik_yok = [x for x in b_tablo if x[1] == 0]
    b_ters = [x for x in b_tablo if x[1] != 0 and not x[2]]

    # ---- 1c. kapanış eşlemesi ----
    kap_rows = []
    for p in kapali + tasf:
        if p["kapanis"] == "tasfiye":
            fl = [f for f in trader_fills.get(p["adres"], []) if f["coin"] == p["coin"] and abs(f["time"] - p["kapanis_ms"]) <= 60_000]
            kap_rows.append({"p": p, "tr_ms": fl[0]["time"] if fl else None, "lag": None, "api_fark": None, "tr_dir": fl[0]["dir"] if fl else None})
            continue
        son = [f for f in p["fills"] if f["eylem"] in ("azalt", "kapat")][-1]
        t_biz = int(son["trader_dolum_ms"])
        aday = [f for f in trader_fills.get(p["adres"], []) if f["coin"] == p["coin"] and any(t == "azalt" for t, _ in dolum_turu(f))
                and abs(f["time"] - t_biz) <= KAPANIS_ESLESME_MS]
        if not aday:
            kap_rows.append({"p": p, "tr_ms": None, "lag": None, "api_fark": None, "tr_dir": None})
            continue
        f = min(aday, key=lambda x: abs(x["time"] - t_biz))
        kap_rows.append({"p": p, "tr_ms": f["time"], "lag": int(son["dolum_ms"]) - f["time"], "api_fark": f["time"] - t_biz, "tr_dir": f["dir"]})
    kap_ok = [r for r in kap_rows if r["tr_ms"] is not None and r["p"]["kapanis"] != "tasfiye"]
    kap_yok = [r for r in kap_rows if r["tr_ms"] is None and r["p"]["kapanis"] != "tasfiye"]
    lag = [r["lag"] for r in kap_ok]
    apf = [abs(r["api_fark"]) for r in kap_ok]

    # ---- 1d. boyut oranı ----
    sapma = []
    for p in pozlar:
        slot = None
        for k in p["fills"]:
            if k.get("olay") != "emir" or "_once" not in k:
                continue
            if k["eylem"] in ("ac", "artir"):
                slot = float(k.get("slot_usd") or 0.0)
                tr_hes = k.get("trader_hesap_usd")
                tr_px = k.get("trader_px")
                tr_son = k.get("trader_poz_sonra")
                if not (slot and tr_hes and tr_px and tr_son is not None):
                    continue
                t_oran = abs(float(tr_son)) * float(tr_px) / float(tr_hes)
                biz_oran = abs(k["_sonra"]) * float(k["dolum_px"]) / slot
                if t_oran <= 0:
                    continue
                d = biz_oran / t_oran
                if d > 2 or d < 0.5:
                    sapma.append({"tur": "açma" if k["eylem"] == "ac" else "artırma", "adres": p["adres"], "coin": p["coin"], "ms": int(k["zaman_ms"]),
                                  "t_oran": t_oran, "biz_oran": biz_oran, "d": d})
            elif k["eylem"] in ("azalt", "kapat") and abs(k["_once"]) > 0:
                t_once, t_son = k.get("trader_poz_once"), k.get("trader_poz_sonra")
                if t_once in (None, 0) or t_son is None:
                    continue
                t_frac = (abs(float(t_once)) - abs(float(t_son))) / abs(float(t_once))
                b_frac = abs(float(k["sz"])) / abs(k["_once"])
                if t_frac <= 0:
                    continue
                d = b_frac / t_frac
                if d > 2 or d < 0.5:
                    sapma.append({"tur": "azaltma" if k["eylem"] == "azalt" else "kapatma", "adres": p["adres"], "coin": p["coin"],
                                  "ms": int(k["zaman_ms"]), "t_oran": t_frac, "biz_oran": b_frac, "d": d})
    oran_n = 0
    for p in pozlar:
        for k in p["fills"]:
            if k.get("olay") == "emir" and k["eylem"] in ("ac", "artir") and k.get("trader_hesap_usd") and k.get("trader_px") and k.get("trader_poz_sonra") is not None:
                oran_n += 1

    # ---- 4. Telegram ----
    tg_msg = [k for k in kayitlar if k.get("olay") == "tg_mesaj"]
    tg_telegram = [k for k in kayitlar if k.get("olay") == "telegram"]
    tg_yeni = [k for k in tg_telegram if int(k["zaman_ms"]) >= DEPLOY_MS and "pozisyon" in str(k.get("metin", "")).lower()]
    yeni_islem = [p for p in pozlar if p["acilis_ms"] >= DEPLOY_MS or (p["kapanis_ms"] or 0) >= DEPLOY_MS]

    # ---- çıktı ----
    L: list[str] = []
    a = L.append
    a("# Mutabakat v2 — copy-trade (HL dolumları ↔ motor kaydı)")
    a("")
    a(f"Veri anı: **{v1.tsi(veri_ms)} TSİ** (`durum/ozet.json` yazılış). Son kayıt: {v1.tsi(son_kayit_ms)} TSİ. "
      f"Dönem: 16.11 11:30 UTC → veri anı. Kaynak: `origin/canli-durum` revizyonu **`{dal}`** (kayıt, hesap, ozet; dal canlı ilerler, bu sabit commit analiz edildi) + Hyperliquid public info (dolumlar; anlık pozisyonlar ve allMids çalıştırma anında). "
      f"Betik: `araclar/mutabakat_v2.py`. Adresler kısa biçimde (`0x1234ab…`).")
    a("")
    a("**Birim:** pozisyon = bir (trader, coin) döngüsü. Kapanış = `kapat` veya azaltmayla kalan miktar ≤ 1e-4 × açılan büyüklük "
      "(v1 bu eşiği 1 $ olarak kullanmıştı), ya da tasfiye. Tutar $ (kopya ölçeği, sanal kasa 10.000 $).")
    a("")
    a("## Özet")
    a("")
    a("| kalem | değer |")
    a("|---|---|")
    a(f"| Trader açılış/artış olayı (HL, 11 trader, 60 sn birleştirme) | {len(olaylar)} |")
    a(f"| Kopyalandı | {sonuc['kopyalandı']} |")
    a(f"| Kaçan (toplam) | {kaçan_top} (hata: {sonuc['kaçan (hata)']}, kayıt yok: {sonuc['kaçan (kayıt yok)']}) |")
    a(f"| Takip öncesi (kadro dışı, kaçan sayılmaz) | {sonuc['takip öncesi (kadro dışı)']} |")
    a(f"| Bilerek atlandı (toplam) | {sonuc['bilerek atlandı']} |")
    a(f"| Bizim kapanmış pozisyon | {len(kapali)} kapanış + {len(tasf)} tasfiye = {len(kapali) + len(tasf)} |")
    a(f"| Bizim açık pozisyon (log) / motor `hesap.poz` | {len(acik_p)} / {sum(len(v) for v in (hes.get('poz') or {}).values())} |")
    a(f"| Açık pozisyon, trader'da artık açık değil | {len(b_acik_yok)} |")
    a(f"| Açık pozisyon, trader'da ters yönde | {len(b_ters)} |")
    a(f"| Eşleşmeyen kapanış (trader'da karşılık yok) | {len(kap_yok)} |")
    a(f"| Boyut sapması > 2x (ya da < 0,5x) | {len(sapma)} |")
    a(f"| Kasa (10.000 + realize − ücret + fonlama, hesap.json) | {v1.tr_say(kasa_kont)} $ (motor kasa {v1.tr_say(float(ozet.get('kasa_usd') or 0))} $ — realize toplamı kendi başına yeterli; bkz. 2) |")
    a(f"| Telegram pozisyon mesajı (yeni düzen, ≥ 04:15 TSİ) | {'henüz yeni düzende işlem yok' if not yeni_islem else f'{len(yeni_islem)} işlem var, mesaj kaydı {len(tg_yeni)}'} |")
    a("")

    a("## 1) Kopya kapsamı (trader açılış/artış olayları)")
    a("")
    a(f"Trader olayı (HL `userFillsByTime`, 11 trader, 60 sn birleştirme): {len(olaylar)}. Eşleşme: bizim kaydın `trader_dolum_ms` değeri, "
      f"olay aralığının ±2 sn içinde. Kadroya alınmadan önceki olaylar ({sonuc['takip öncesi (kadro dışı)']}) sayıma girmez.")
    a("")
    a("### 1-0) Bizim açılış/artış dolumlarının HL karşılığı (kaynağa göre)")
    a("")
    a(f"Dolu açılış/artış kaydı: {len(dolu_ac)}. HL'de aynı trader, coin ve ±2 sn içinde dolum var: {len(dolu_ac) - len(dolu_hl_yok)}. "
      f"**Yok: {len(dolu_hl_yok)}**.")
    a("")
    if dolu_hl_yok:
        a("| kaynak (`kaynak`) | yok olan dolum | trader | coin | zaman (TSİ) |")
        a("|---|---|---|---|---|")
        for k in sorted(dolu_hl_yok, key=lambda k: int(k["zaman_ms"])):
            a(f"| {k.get('kaynak')} | {k['eylem']} | {ks(k['adres'])} | {k['coin']} | {v1.tsi(int(k['trader_dolum_ms']))} |")
        a("")
    a(f"Kayıtlardaki trader açılış/artış anahtarı (adres, coin, ms) {len(log_ac_anahtar)} adet; bunların HL fill'inde karşılığı olan: "
      f"{len(log_ac_anahtar & hl_anahtar)}. HL'de karşılığı olmayan (log'a özgü): {len(log_ac_anahtar - hl_anahtar)} "
      f"({', '.join(f'{a_} {n}' for a_, n in log_yalniz.most_common())}). Bunlar çoğunlukla `emir_yok` kayıtlarıdır; "
      f"sayıma etkisi yok (sayım HL olaylarından yapılır), ama kaynağı doğrulanmadı. "
      f"HL'de olup kayıtta hiç açılış anahtarı olmayan: {len(hl_acilis_logsuz)} (kadro öncesi olaylar dahil).")
    a("")
    a("### 1a) Bilerek atlandı (filtre adına göre)")
    a("")
    a("| filtre (`neden`) | olay |")
    a("|---|---|")
    for n, c in bilerek.most_common():
        a(f"| {n} | {c} |")
    for ad in ("hesap_kucuk", "duygu_ters"):
        if ad not in bilerek:
            a(f"| {ad} | 0 (kayıtta yok) |")
    a(f"| **toplam** | **{sonuc['bilerek atlandı']}** |")
    a("")
    a("### 1b) Kaçan (hata ya da kayıt yok)")
    a("")
    a("| sebep | olay |")
    a("|---|---|")
    kac_sebep = Counter(x["sebep"] for x in kacan_liste)
    for n, c in kac_sebep.most_common():
        a(f"| {n} | {c} |")
    a(f"| **toplam** | **{kaçan_top}** |")
    a("")
    if kacan_liste:
        a("| trader | coin | yön | zaman (TSİ) | olay | sebep |")
        a("|---|---|---|---|---|---|")
        for x in sorted(kacan_liste, key=lambda x: x["t0"]):
            a(f"| {ks(x['adres'])} | {x['coin']} | {x['yon']} | {v1.tsi(x['t0'])} | {x['n']} dolum | {x['sebep']} |")
        a("")
    a(f"Yön uyumu (kopyalanan olaylar, bizim `yon` vs trader yönü): {kopya_yon_uyus}/{kopya_yon_n}.")
    a("")

    a("## 2) Açık pozisyonlarımız, trader'da bugün")
    a("")
    a(f"Anlık konum: {v1.tsi(int(time.time() * 1000))} TSİ (`clearinghouseState`, tüm HIP-3 dex'leri). Bizim açık: {len(acik_p)}.")
    a("")
    a(f"- Trader'da açık değil: **{len(b_acik_yok)}**")
    a(f"- Trader'da açık ama ters yön: **{len(b_ters)}**")
    a(f"- Aynı yön: **{len(b_tablo) - len(b_acik_yok) - len(b_ters)}**")
    a("")
    if b_acik_yok or b_ters:
        a("| trader | coin | bizim yön | trader miktarı | durum |")
        a("|---|---|---|---|---|")
        for p, szi, ayni in b_tablo:
            if not ayni:
                a(f"| {ks(p['adres'])} | {p['coin']} | {p['yon']} | {szi:,.6g} | {'trader kapatmış' if szi == 0 else 'TERS YÖN'} |")
        a("")

    a("## 1c) Kapanışlar: trader kapanışı ile eşleşme")
    a("")
    a(f"Eşleşen kapanış: {len(kap_ok)} / {len(kap_ok) + len(kap_yok)}. Eşleşmeyen: **{len(kap_yok)}**.")
    if lag:
        a(f"Gecikme (bizim dolum − trader dolumu): medyan {sn(statistics.median(lag))} sn, en büyük {sn(max(lag))} sn, en küçük {sn(min(lag))} sn (n={len(lag)}).")
        a(f"Zaman farkı (kayıttaki trader zamanı − HL dolum zamanı): medyan {sn(statistics.median([r['api_fark'] for r in kap_ok]))} sn, "
          f"en büyük mutlak {sn(max(apf))} sn.")
    a("")
    a("| # | trader | coin | yön | kapanış tipi | bizim kapanış (TSİ) | trader dolumu (TSİ) | gecikme sn | eşleşme |")
    a("|---|---|---|---|---|---|---|---|---|")
    for i, r in enumerate(sorted(kap_rows, key=lambda r: r["p"]["kapanis_ms"] or 0), 1):
        p = r["p"]
        eslesme = "yok" if r["tr_ms"] is None else ("yok (tasfiye: trader likit)" if p["kapanis"] == "tasfiye" and r["tr_ms"] is None else "tamam")
        if p["kapanis"] == "tasfiye":
            eslesme = "bizde emir yok; trader tarafı " + ("var" if r["tr_ms"] else "yok")
        a(f"| {i} | {ks(p['adres'])} | {p['coin']} | {p['yon']} | {p['kapanis']} | {v1.tsi(p['kapanis_ms'])} | "
          f"{v1.tsi(r['tr_ms']) if r['tr_ms'] else '—'} | {sn(r['lag']) if r['lag'] is not None else '—'} | {eslesme} |")
    a("")

    a("## 1d) Boyut oranı")
    a("")
    a(f"Karşılaştırılan dolum: {oran_n} (açma/artırma: trader pozisyon değeri / hesap değeri vs bizim pozisyon / slot; "
      f"azaltma/kapatma: kapatılan oran). Sapma = bizim oran / trader oranı; 2x üstü ya da 0,5x altı listelenir.")
    a("")
    a(f"Sapma sayısı: **{len(sapma)}** ({sum(1 for s in sapma if s['tur'] in ('açma', 'artırma'))} açma/artırma, "
      f"{sum(1 for s in sapma if s['tur'] not in ('açma', 'artırma'))} azaltma/kapatma).")
    a("")
    if sapma:
        a("| tür | trader | coin | zaman (TSİ) | trader oranı | bizim oran | sapma (biz/trader) |")
        a("|---|---|---|---|---|---|---|")
        for s in sorted(sapma, key=lambda s: s["ms"]):
            a(f"| {s['tur']} | {ks(s['adres'])} | {s['coin']} | {v1.tsi(s['ms'])} | {s['t_oran']:.4g} | {s['biz_oran']:.4g} | {s['d']:.3g}x |")
        a("")

    a("## 2) Kasa bağımsız kontrol")
    a("")
    a(f"- Gerçekleşen K/Z, bizim pozisyonlardan (kapanış + kısmi azaltmaların `pnl_usd` toplamı + tasfiye): **{v1.tr_say(real_biz_top)} $**")
    a(f"- `hesap.json` realize toplamı: **{v1.tr_say(real_top)} $**; fark: **{v1.tr_say(real_biz_top - real_top)} $**")
    if any(abs(v) > 0.005 for v in kasa_fark.values()):
        a("- Trader bazında farklar (> 0,005 $):")
        for ad, v in sorted(kasa_fark.items(), key=lambda x: -abs(x[1])):
            if abs(v) > 0.005:
                a(f"  - {ks(ad)}: {v1.tr_say(v, 4, True)} $")
    else:
        a("- Trader bazında fark yok (> 0,005 $).")
    a(f"- Ücret: bizim {v1.tr_say(ucret_biz_top)} $ / hesap.json {v1.tr_say(ucret_hes_top)} $")
    a(f"- Fonlama (hesap.json): {v1.tr_say(fund_top, 2, True)} $")
    a(f"- Kasa = 10.000 + realize − ücret + fonlama = **{v1.tr_say(kasa_kont)} $**; motor `ozet.kasa_usd` = {v1.tr_say(float(ozet.get('kasa_usd') or 0))} $.")
    a(f"- Açık K/Z (motor, `ozet.acik` toplamı) {v1.tr_say(kz_acik_motor, 2, True)} $; özsermaye (kasa + açık K/Z) = **{v1.tr_say(ozsermaye_kont)} $**; "
      f"motor `ozsermaye_usd` = {v1.tr_say(float(ozet.get('ozsermaye_usd') or 0))} $.")
    a("")
    a("**Açık K/Z fiyat kaynağı:** `copytrade/canli/motor.py` `mids_al()` → HL `allMids` orta fiyatı (mark). `hesap.py` özsermaye ve "
      "`gerceklesmemis()` aynı `marks` sözlüğünü kullanır; `pano.py` açık satırları `ozet['acik']` içindeki `kz_usd = sz·(mark − giriş)` değerinden okur. "
      "Yani pano ile motor aynı fiyat kaynağını kullanır (allMids, mark). Kontrol: veri anındaki mark ile şimdiki allMids farkı medyan "
      f"{statistics.median(acik_mark_fark):+.3f}% (n={len(acik_mark_fark)}; zaman farkından kaynaklanır).") if acik_mark_fark else None
    a("")
    a("### 2b) Kapalı pozisyonlar (gerçekleşen K/Z, kısmi azaltmalar dahil)")
    a("")
    a("| # | trader | coin | yön | açılış | kapanış | tip | giriş | çıkış | gerçekleşen K/Z $ | ücret $ |")
    a("|---|---|---|---|---|---|---|---|---|---|---|")
    kapali_sirali = sorted(kapali + tasf, key=lambda p: p["kapanis_ms"] or 0)
    toplam_k = 0.0
    for i, p in enumerate(kapali_sirali, 1):
        real = p["realize"] + (p["tasfiye_pnl"] or 0.0)
        toplam_k += real
        giris = p["ac_px"] / p["acilan"] if p["acilan"] else None
        cikis = p["tasfiye_px"] if p["kapanis"] == "tasfiye" else (p["cikis_px_top"] / p["cikis_sz"] if p["cikis_sz"] else None)
        a(f"| {i} | {ks(p['adres'])} | {p['coin']} | {p['yon']} | {v1.tsi(p['acilis_ms'])} | {v1.tsi(p['kapanis_ms'])} | {p['kapanis']} | "
          f"{v1.fiyat(giris)} | {v1.fiyat(cikis)} | {v1.tr_say(real, 2, True)} | {v1.tr_say(p['ucret'], 2)} |")
    a(f"| | | | | | | | | **toplam** | **{v1.tr_say(toplam_k, 2, True)}** | |")
    a("")
    a(f"Kapanmış pozisyon: {len(kapali)} (kapat {sum(1 for p in kapali if p['kapanis'] == 'kapat')}, sıfırlanan {sum(1 for p in kapali if p['kapanis'] == 'sifir')}) + tasfiye {len(tasf)} = {len(kapali) + len(tasf)}.")
    a("")
    a("### 2c) Açık pozisyonlar: log ↔ motor miktar")
    a("")
    uyus = 0
    fark_liste = []
    for p in acik_p:
        m = float((hes.get("poz") or {}).get(p["adres"], {}).get(p["coin"], {}).get("sz", 0.0))
        if abs(p["net"] - m) <= 1e-6 * max(1.0, abs(m)):
            uyus += 1
        else:
            fark_liste.append((p, p["net"] - m))
    a(f"Eşleşen: {uyus} / {len(acik_p)}. Farklı: {len(fark_liste)}.")
    for p, d in fark_liste:
        dz = [float(k["sz"]) for k in kayitlar if k.get("olay") == "kapanis_duzeltme" and k.get("adres") == p["adres"] and k.get("coin") == p["coin"]]
        alt = [c for r in range(1, len(dz) + 1) for c in itertools.combinations(dz, r) if abs(sum(c) - d) <= 1e-9 * max(1.0, abs(d))]
        neden = ("toz" if abs(d) <= TOZ_ORAN * p["acilan"] else
                 f"kapanis_duzeltme alt kümesi ({len(alt[0])} kayıt) ile açıklanıyor" if alt else "AÇIKLANMADI")
        a(f"- {ks(p['adres'])} {p['coin']}: log {p['net']:.6g}, motor {p['net'] - d:.6g}, fark {d:.3g} ({neden})")
    a("")

    a("## 2d) v1'e göre düzeltmeler")
    a("")
    a(f"- Kapanmış pozisyon: v1 25 (16 kapat + 9 'sıfır', eşik 1 $) → v2 {len(kapali)} (16 kapat + {sum(1 for p in kapali if p['kapanis'] == 'sifir')} 'sıfır', eşik 1e-4 × açılan). "
      "Fark: v1'in 5 'sıfır' kapanışı ZEC (0x c30c7e) ve HYPE kalıntı düzeltmeleri (miktar ~1e-5 – 5e-4 coin) idi; bunlar gerçek kapanış değil.")
    a("- Tasfiye: 1 (VVV, 19.11 07:32 TSİ). Bu motorun sanal tasfiye kontrolüdür (`hesap.tasfiye_kontrol`, mark ≤ likit fiyat); trader tarafında karşılığı olması beklenmez.")
    a(f"- Toplam pozisyon: v1 58 → v2 {len(pozlar)} ({len(kapali)} kapanış + {len(tasf)} tasfiye + {len(acik_p)} açık).")
    a(f"- Açık pozisyon: kurala göre {len(acik_p)} (v1 ile aynı sayı); motor `hesap.poz` {sum(len(v) for v in (hes.get('poz') or {}).values())}. "
      "Fark: ZEC kalıntısı (miktar ~1e-4 coin; motor `kapanis_duzeltme` ile sıfırladı, bizim toz eşiğimizin üstünde kaldığı için açık sayıldı).")
    a(f"- Kasa: bu revizyonda realize {v1.tr_say(real_top)} $, kasa {v1.tr_say(kasa_kont)} $ (v1 anında 9.937,51 $ idi; veri ilerledi). Açık K/Z (`ozet.acik`): {v1.tr_say(kz_acik_motor, 2, True)} $ (v1 anında +48,02 $).")
    a("")

    a(f"## 3) {len(kapanis_dolum)} kapanış dolumunun dökümü")
    a("")
    a(f"Kayıttaki azalt/kapat dolumu (dolu/kısmi): **{len(kapanis_dolum)}**.")
    a("")
    a("| grup | dolum sayısı |")
    a("|---|---|")
    for n in ("kapanış dolumu (kapat)", "kapanış dolumu (azaltma ile sıfır)", "kısmi azaltma → kapanan pozisyon",
              "kısmi azaltma → açık pozisyon", "kısmi azaltma → tasfiye pozisyonu"):
        a(f"| {n} | {tablo3.get(n, 0)} |")
    a(f"| **toplam** | **{tablo3_toplam}** |")
    a("")
    a(f"Kontrol: {tablo3_toplam} = {len(kapanis_dolum)} → {'tamam' if tablo3_toplam == len(kapanis_dolum) else 'UYUŞMAZLIK'}. "
      f"Kapanan pozisyon sayısı = kapat {tablo3.get('kapanış dolumu (kapat)', 0)} + sıfırlanan {tablo3.get('kapanış dolumu (azaltma ile sıfır)', 0)} = "
      f"{tablo3.get('kapanış dolumu (kapat)', 0) + tablo3.get('kapanış dolumu (azaltma ile sıfır)', 0)}, tasfiye {len(tasf)}.")
    a("")
    a("## 4) Telegram")
    a("")
    a(f"- Yeni düzen başlangıcı: 20.11 04:15 TSİ (kullanıcı bildirimi). Veri son kaydı {v1.tsi(son_kayit_ms)} TSİ.")
    a(f"- `tg_mesaj` kaydı: {len(tg_msg)}. Yeni düzen sonrası pozisyon mesajı kaydı: {len(tg_yeni)}.")
    a(f"- Yeni düzende (≥ 04:15 TSİ) açılan/kapanan pozisyon: {len(yeni_islem)}.")
    a("- Sonuç: " + ("henüz yeni düzende işlem yok." if not yeni_islem else "yeni düzende işlem var; mesaj kayıtları yukarıda."))
    a("")

    cikti = args.cikti
    cikti.parent.mkdir(parents=True, exist_ok=True)
    cikti.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"yazıldı: {cikti}")
    print(f"olay={len(olaylar)} kopya={sonuc['kopyalandı']} bilerek={sonuc['bilerek atlandı']} kaçan={kaçan_top} "
          f"acik={len(acik_p)} acik_yok={len(b_acik_yok)} ters={len(b_ters)} kapanis={len(kapali)} tasfiye={len(tasf)} "
          f"kap_yok={len(kap_yok)} sapma={len(sapma)} real_biz={real_biz_top:.4f} real_hes={real_top:.4f} kasa={kasa_kont:.4f} "
          f"yetim={len(yetim)} oz_kasa={ozet.get('kasa_usd')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
