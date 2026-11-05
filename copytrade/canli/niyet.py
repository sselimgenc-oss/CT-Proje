"""Çift emir koruması (K‑37 §3): emirden ÖNCE `durum/niyet.jsonl`'e niyet yazılır (fsync), emirden SONRA sonuç satırı eklenir.

Satırlar: `{"t":"niyet","kimlik","eylem","adres","coin","yon","usd","reduce_only","cloid","ms"}` ve `{"t":"sonuc","cloid","durum","ms",...}`.
`cloid` = sha256(dolum kimliği + "|" + eylem)'in ilk 16 baytı (hex, "0x" önekli; deterministik): aynı dolum aynı eylem için aynı cloid → HL ikinci emri `orderStatus(cloid)` ile tanır.
Yeniden başlatmada: kimlikler `islenen`e katılır (çift emir yok); sonucu yazılmamış niyetler gerçek kipte `orderStatus(cloid)` ile çözülür, sanal kipte "sonucsuz" kaydedilir (emir tekrarlanmaz).
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


def cloid_uret(kimlik: str, eylem: str) -> str:
    return "0x" + hashlib.sha256(f"{kimlik}|{eylem}".encode()).digest()[:16].hex()


class Niyet:
    def __init__(self, yol: Path) -> None:
        self.yol = yol

    def _ekle(self, satir: dict) -> None:
        self.yol.parent.mkdir(parents=True, exist_ok=True)
        with self.yol.open("a", encoding="utf-8") as f:
            f.write(json.dumps(satir, ensure_ascii=False, separators=(",", ":")) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def niyet_yaz(self, **alanlar) -> None:
        self._ekle({"t": "niyet", **alanlar})

    def sonuc_yaz(self, cloid: str, durum: str, ms: int, **alanlar) -> None:
        self._ekle({"t": "sonuc", "cloid": cloid, "durum": durum, "ms": ms, **alanlar})

    def satirlar(self) -> list[dict]:
        if not self.yol.is_file():
            return []
        cikti = []
        for ham in self.yol.read_text(encoding="utf-8").splitlines():
            try:
                cikti.append(json.loads(ham))
            except ValueError:
                continue                                # yarım satır (çökme): atla
        return cikti

    def kimlikler(self) -> list[str]:
        return [x["kimlik"] for x in self.satirlar() if x.get("t") == "niyet" and x.get("kimlik")]

    def sonucsuz(self) -> list[dict]:
        sonuclu = {x["cloid"] for x in self.satirlar() if x.get("t") == "sonuc"}
        return [x for x in self.satirlar() if x.get("t") == "niyet" and x["cloid"] not in sonuclu]

    def sikistir(self, son_n: int) -> None:
        """Dosya şişmesin: sonuçlu eski satırlar atılır (son `son_n` niyet + sonucsuzlar kalır)."""
        s = self.satirlar()
        niyetler = [x for x in s if x.get("t") == "niyet"]
        if len(niyetler) <= 2 * son_n:
            return
        tut = {x["cloid"] for x in niyetler[-son_n:]} | {x["cloid"] for x in self.sonucsuz()}
        yeni = [x for x in s if x.get("cloid") in tut]
        gecici = self.yol.with_suffix(".tmp")
        gecici.write_text("".join(json.dumps(x, ensure_ascii=False, separators=(",", ":")) + "\n" for x in yeni), encoding="utf-8")
        gecici.replace(self.yol)
