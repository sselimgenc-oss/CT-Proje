"""Dolgu 429 koruması için küçük gerçek veri denemesi (kural 1): listedeki TÜM adreslerin `userFillsByTime` dolgusu tek turda, varsayılan `Ayar` ile (0,5 sn aralık, 3 yeniden deneme).
Çıktı: süre, hata sayısı, hata türleri, kurtarılan dolum. `--eski-davranis`: karşılaştırma için eski desen (aralık yok, yeniden deneme yok, art arda). Yalnız halka açık veri; adres yazılmaz.

Kullanım: python -m copytrade.dolgu_deneme [--liste copytrade/izleme_listesi.yaml] [--pencere-dk 60] [--ilk N] [--eski-davranis]"""
from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
import time
from pathlib import Path

from copytrade.dinleyici import Ayar, Dinleyici, hata_turu, liste_oku, rest_dolumlar, rest_post_fabrikasi


def korumali(liste, post, pencere_dk: int) -> dict:
    din = Dinleyici(liste, [], None, post, Path(tempfile.mkdtemp()), Ayar())

    async def kos() -> float:
        simdi = din.saat_ms()
        t = time.monotonic()
        din._dolgu_baslat((simdi - pencere_dk * 60_000, simdi))
        await din._dolgu_gorevi
        return time.monotonic() - t
    sure = asyncio.run(kos())
    g = din.olcum.genel
    return {"adres": len(liste), "sure_sn": round(sure, 1), "kurtarilan_dolum": g.get("dolgu", 0), "dolgu_hata": g.get("dolgu_hata", 0), "dolgu_hata_tur": g["dolgu_hata_tur"],
            "dolgu_yeniden_deneme": g["dolgu_yeniden_deneme"], "dolgu_bekleyen": g["dolgu_bekleyen"]}


def eski_desen(liste, post, pencere_dk: int) -> dict:
    simdi = int(time.time() * 1000)
    hata: dict[str, int] = {}
    kurtarilan, t = 0, time.monotonic()
    for i in liste:
        try:
            kurtarilan += len(rest_dolumlar(post, i.adres, simdi - pencere_dk * 60_000, simdi))
        except Exception as e:  # noqa: BLE001 - karşılaştırma sayacı
            hata[hata_turu(e)] = hata.get(hata_turu(e), 0) + 1
    return {"adres": len(liste), "sure_sn": round(time.monotonic() - t, 1), "kurtarilan_dolum": kurtarilan, "dolgu_hata": sum(hata.values()), "dolgu_hata_tur": hata}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--liste", type=Path, default=Path("copytrade/izleme_listesi.yaml"))
    ap.add_argument("--pencere-dk", type=int, default=60)
    ap.add_argument("--ilk", type=int, default=0, help="yalnız ilk N adres (yerel duman denemesi)")
    ap.add_argument("--eski-davranis", action="store_true", help="korumasız eski deseni de çalıştır (korumalı turdan 90 sn sonra)")
    a = ap.parse_args(argv)
    liste = liste_oku(a.liste)[: a.ilk or None]
    post = rest_post_fabrikasi()
    sonuc = {"pencere_dk": a.pencere_dk, "korumali": korumali(liste, post, a.pencere_dk)}
    if a.eski_davranis:
        time.sleep(90)          # hız sınırı kovasının dolması için
        sonuc["eski_desen"] = eski_desen(liste, post, a.pencere_dk)
    print(json.dumps(sonuc, ensure_ascii=False, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
