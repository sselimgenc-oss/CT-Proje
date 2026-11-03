"""Veri dalı olay arşivi (A4-2): `durum.json.olaylar` yalnız son 200 olayı yayımlar; taşanlar `olay_tasan.jsonl` olarak yazılır ve burada KALICI arşive eklenir.

Kullanım: python olay_arsivle.py <olay_tasan.jsonl> <olay_arsivi.jsonl>. Arşiv eklemeli ve kimlik başına tekildir (`id`); satırlar (zaman, id) artan sıralıdır; mevcut kayıt
asla silinmez ya da değiştirilmez (aynı `id` varsa ilk kayıt kalır). Yalnız standart kütüphane (veri dalı checkout'unda çalışır)."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def oku(yol: Path) -> list[dict]:
    if not yol.is_file():
        return []
    return [json.loads(satir) for satir in yol.read_text(encoding="utf-8").splitlines() if satir.strip()]


def birlestir(mevcut: list[dict], yeni: list[dict]) -> list[dict]:
    kayitlar = {olay["id"]: olay for olay in yeni}
    kayitlar.update({olay["id"]: olay for olay in mevcut})          # mevcut arşiv öncelikli: değişmez
    return sorted(kayitlar.values(), key=lambda o: (o["zaman"], o["id"]))


def main(argv: list[str]) -> int:
    tasan, arsiv = Path(argv[1]), Path(argv[2])
    sonuc = birlestir(oku(arsiv), oku(tasan))
    gecici = arsiv.with_suffix(".tmp")
    gecici.write_text("".join(json.dumps(o, ensure_ascii=False, sort_keys=True) + "\n" for o in sonuc), encoding="utf-8")
    gecici.replace(arsiv)
    print(f"olay arşivi: {len(sonuc)} olay")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
