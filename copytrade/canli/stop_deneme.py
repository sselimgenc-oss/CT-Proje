"""K-64: borsada duran felaket stopunun HYPERLIQUID TESTNET denemesi (gerçek para YOK).

Kullanım (sunucuda ya da kendi bilgisayarında; anahtar yalnız ortam değişkeninde, ekrana/kayda yazılmaz):
    HL_AG=testnet HL_HESAP_ADRESI=0x... HL_API_CUZDAN_ANAHTARI=... python -m copytrade.canli.stop_deneme
Adımlar: (1) küçük BTC long (IOC, ~15 $) → (2) %22 aşağıda reduce-only stop → (3) açık emirlerde görüldü mü → (4) stop yenileme (önce yeni, sonra eski iptal)
→ (5) stop iptal → (6) pozisyon reduce-only kapanış → (7) borsada pozisyon 0 ve açık emir 0. Her adım GEÇTİ/KALDI yazar; çıkış kodu 0 = hepsi geçti.
HL_AG=testnet değilse ÇALIŞMAZ (mainnet'e asla emir göndermez).
"""
from __future__ import annotations

import os
import sys
import time

import requests

from copytrade.canli import borsa_stop as bs
from copytrade.canli.yurutucu import gercek_yurutucu_olustur
from copytrade.kurallar import load_rules

INFO = "https://api.hyperliquid-testnet.xyz/info"


def post(y: dict):
    r = requests.post(INFO, json=y, timeout=10)
    r.raise_for_status()
    return r.json()


def poz(adres: str, coin: str) -> float:
    for p in post({"type": "clearinghouseState", "user": adres}).get("assetPositions", []):
        if p["position"]["coin"] == coin:
            return float(p["position"]["szi"])
    return 0.0


def acik(adres: str) -> list[dict]:
    return post({"type": "openOrders", "user": adres})


def main() -> int:
    if (os.environ.get("HL_AG") or "").strip().lower() != "testnet":
        print("HL_AG=testnet değil: deneme yalnız testnet'te çalışır, çıkılıyor.")
        return 2
    adres = (os.environ.get("HL_HESAP_ADRESI") or "").strip()
    rules = {**load_rules(), "canli_hip3_kopya": False}
    y = gercek_yurutucu_olustur(post, rules)
    sonuc: list[tuple[str, bool, str]] = []

    def adim(ad: str, ok: bool, ek: str = "") -> bool:
        sonuc.append((ad, ok, ek))
        print(f"{'GEÇTİ' if ok else 'KALDI'}  {ad}  {ek}")
        return ok

    coin = "BTC"
    once = poz(adres, coin)
    if not adim("başlangıçta BTC pozisyonu yok", abs(once) < 1e-12, f"sz={once}"):
        return 1
    d = y.emir(coin, "B", 15.0)
    if not adim("1) küçük long açıldı", d.durum in ("dolu", "kismi") and d.sz > 0, f"durum={d.durum} sz={d.sz} px={d.px} neden={d.neden}"):
        return 1
    sz, giris = d.sz, d.px
    oid1, neden, tetik1 = y.stop_koy(coin, True, sz, giris * 0.78, bs.stop_cloid())
    adim("2) stop kondu", oid1 is not None, f"oid={oid1} tetik={tetik1} neden={neden}")
    time.sleep(2)
    a = acik(adres)
    e = next((x for x in a if str(x.get("oid")) == str(oid1)), None)
    adim("3) stop açık emirlerde", e is not None and bs.bizim_mi(e.get("cloid")), f"{ {k: (e or {}).get(k) for k in ('coin', 'side', 'sz', 'cloid')} }")
    oid2, neden2, tetik2 = y.stop_koy(coin, True, sz, giris * 0.77, bs.stop_cloid())
    iptal1 = y.stop_iptal(coin, oid1) if oid1 is not None else False
    time.sleep(2)
    a = acik(adres)
    adim("4) yenileme: yeni var, eski yok", oid2 is not None and iptal1 and any(str(x.get("oid")) == str(oid2) for x in a) and not any(str(x.get("oid")) == str(oid1) for x in a),
         f"oid2={oid2} tetik2={tetik2} neden={neden2}")
    adim("5) stop iptal", oid2 is not None and y.stop_iptal(coin, oid2))
    k = y.emir(coin, "A", sz * (giris or 1) * 1.05, reduce_only=True, acik_sz=sz)
    adim("6) pozisyon kapatıldı", k.durum in ("dolu", "kismi"), f"durum={k.durum} sz={k.sz} neden={k.neden}")
    time.sleep(2)
    son, acik_son = poz(adres, coin), acik(adres)
    adim("7) borsada pozisyon 0 ve açık emir 0", abs(son) < 1e-12 and not acik_son, f"sz={son} acik={len(acik_son)}")
    hepsi = all(ok for _, ok, _ in sonuc)
    print("SONUÇ:", "HEPSİ GEÇTİ" if hepsi else "SORUN VAR (çıktıyı lidere gönderin; anahtar satırı yok)")
    return 0 if hepsi else 1


if __name__ == "__main__":
    sys.exit(main())
