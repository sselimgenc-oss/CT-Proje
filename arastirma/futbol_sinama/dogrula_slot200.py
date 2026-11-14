"""Gerçek veri sınaması: slot=200 yeniden oynatma == cache/olcum ileri.getiri*5 (|fark| < 1e-9). Kullanım: python dogrula_slot200.py [--veri DIR] [--n 30]"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import futbol as f  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--veri", default=os.environ.get("WF_VERI"))
ap.add_argument("--n", type=int, default=30)
a = ap.parse_args()
f.hl.KOK = Path(a.veri)
f.hl.CACHE = f.hl.KOK / "cache"
ayar = json.load(open(f.hl.KOK / "ayar.json"))
ornek = json.load(open(f.hl.KOK / "ornek.json"))
tler = ayar["tarihler"][:11]
f._isci_kur(ayar)
secilen, bos = [], 0
for i, ad in enumerate(ornek["s50"]):
    d = (f.hl.oku("olcum", ad) or {}).get("T", {})
    for T in tler:
        r = d.get(str(T))
        if r and r.get("ileri") and r["ileri"].get("durum") == "olculdu" and r["ileri"]["islem"] > 0 and (i + tler.index(T)) % 11 == 0:
            secilen.append((ad, T, r["ileri"]["getiri"] * 5))
    if len(secilen) >= a.n:
        break
bas, enb, sayi = time.time(), 0.0, 0
for ad, T, beklenen in secilen:
    ctx = f._Baglam(ad)
    ctx.yukle()
    x = f.oynat_slot(f._KAY, ctx.tum, ctx.payda, T, 200)
    fark = abs(x["getiri"] - beklenen)
    enb = max(enb, fark)
    sayi += 1
    print(f"{ad[:10]} T{tler.index(T) + 1} yeni={x['getiri']:+.6f} eski={beklenen:+.6f} fark={fark:.2e}")
    assert fark < 1e-9, "EŞİT DEĞİL"
print(f"{sayi} (adres,T) eşit; en büyük fark {enb:.2e}; {time.time() - bas:.1f} sn")
