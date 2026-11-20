#!/usr/bin/env python3
"""K-80 60 dk bekçi sayacı (yalnız standart kütüphane; sanal_bekci.sh çağırır): kayit/<UTC gün>.jsonl içinde `epoch` sn'den beri sağlık olaylarını sayar, tek satır JSON yazar.

Sayılanlar: bekci_tetik (motor bekçisi süreci öldürdü), telegram_hata + 429 yeniden denemeleri (telegram_yeniden, tur CokIstek), hata (adim_hata + olay_hata + defter_hata).
Kullanım: python3 sanal_bekci_say.py <kayit_dizin> <epoch_sn>"""
import json
import sys
import time
from pathlib import Path


def say(kayit_dizin: Path, epoch_sn: float) -> dict[str, int]:
    out = {"bekci_tetik": 0, "telegram": 0, "hata": 0}
    ms0 = epoch_sn * 1000
    gunler = {time.strftime("%Y-%m-%d", time.gmtime(t)) for t in (epoch_sn, time.time())}
    for gun in sorted(gunler):
        yol = kayit_dizin / f"{gun}.jsonl"
        try:
            satirlar = yol.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for satir in satirlar:
            try:
                o = json.loads(satir)
            except ValueError:
                continue
            if not isinstance(o, dict) or float(o.get("zaman_ms") or 0) < ms0:
                continue
            ad = o.get("olay")
            if ad == "bekci_tetik":
                out["bekci_tetik"] += 1
            elif ad == "telegram_hata" or (ad == "telegram_yeniden" and o.get("tur") == "CokIstek"):
                out["telegram"] += 1
            elif ad in ("adim_hata", "olay_hata", "defter_hata"):
                out["hata"] += 1
    return out


if __name__ == "__main__":
    try:
        print(json.dumps(say(Path(sys.argv[1]), float(sys.argv[2]))))
    except Exception:                                  # noqa: BLE001 - sayaç okunamazsa bekçi geri DÖNMEZ (boş çıktı)
        print("{}")
