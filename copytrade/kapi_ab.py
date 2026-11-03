"""A/B teşhisi: kapı hesabının iki kod sürümünde AYNI girdiyle aynı sonucu verdiğinin kanıtı (lider kararı 2026-11-03).

Yeniden koşu `kod_hash` farklıysa reddedilir (istisna yok); "hesap değişmedi" kanıtı burada üretilir: eski kod (ör. `main` çalışma ağacı) ve yeni kod AYNI adresleri
AYNI API yanıtlarıyla değerlendirir. API yanıtları bir kez çekilir ve iki koda aynen verilir (`TekrarIstemci`; canlı `portfolio` ucu her çağrıda değiştiği için
iki ayrı çekim karşılaştırılamaz). Karşılaştırma dışı sütunlar KODDA açık sabittir: `KONTROL_DISI`.

    python -m copytrade.kapi_ab --eski-kok /yol/main_calisma_agaci --sonuc sonuc.csv --basarili 8 --hatali 4

Hatalı satırlarda (HTTP 500 vb.) hata da bir kez alınır ve iki koda aynı hata verilir: `hata` metinleri karşılaştırılır.
"""
from __future__ import annotations

import argparse
import copy
import importlib
import json
import sys
import tempfile
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pandas as pd

KONTROL_DISI = ("sure_",)                       # süre / telemetri sütun önekleri: duvar saati ve önbellek sayacı, hesap değildir
KONTROL_DISI_SUTUN = ("kod_hash",)              # iki sürümde kasıtlı olarak farklı


def kontrol_disi(sutun: str) -> bool:
    return sutun in KONTROL_DISI_SUTUN or sutun.startswith(KONTROL_DISI)


class TekrarIstemci:
    """Gerçek istemciyi sarar: her (yöntem, argüman) çağrısı bir kez yapılır, yanıt (ya da hata) iki koda da aynen verilir."""

    def __init__(self, gercek: Any):
        self._gercek, self._kayit, self.cagri = gercek, {}, Counter()

    def __getattr__(self, ad: str) -> Any:
        oz = getattr(self._gercek, ad)
        if not callable(oz):
            return oz

        def sar(*args: Any, **kwargs: Any) -> Any:
            anahtar = (ad, repr(args), repr(sorted(kwargs.items())))
            if anahtar not in self._kayit:
                self.cagri[ad] += 1
                try:
                    self._kayit[anahtar] = ("ok", oz(*args, **kwargs))
                except Exception as hata:
                    self._kayit[anahtar] = ("hata", hata)
            durum, deger = self._kayit[anahtar]
            if durum == "hata":
                raise deger
            return copy.deepcopy(deger)
        return sar


def modul_yukle(kok: Path) -> ModuleType:
    """`kok` altındaki `copytrade.kapi` modülünü AYRI bir kopya olarak yükler (çalışan paketi bozmaz)."""
    saklanan = {ad: m for ad, m in sys.modules.items() if ad == "copytrade" or ad.startswith("copytrade.")}
    for ad in saklanan:
        del sys.modules[ad]
    sys.path.insert(0, str(kok))
    try:
        return importlib.import_module("copytrade.kapi")
    finally:
        sys.path.remove(str(kok))
        for ad in [ad for ad in sys.modules if ad == "copytrade" or ad.startswith("copytrade.")]:
            del sys.modules[ad]
        sys.modules.update(saklanan)


def cift_kos(eski: Any, yeni: Any, istemci: Any, satir: dict, semboller: set[str], rules: dict) -> dict[str, Any]:
    """Tek adresi iki kodla, AYNI istemci yanıtlarıyla değerlendirir; `KONTROL_DISI` dışındaki sütun farklarını döner."""
    now_ms = int(satir["now_ms"])
    now = datetime.fromtimestamp(now_ms / 1000, UTC)
    start = int((now - timedelta(days=int(rules["fills_lookback_days"]))).timestamp() * 1000)
    start_200 = int((now - timedelta(days=int(rules["mum_pencere_gun"]))).timestamp() * 1000)
    lider = {"address": satir["address"], "accountValue": float(satir["account_value"]), "kaynak": str(satir.get("kaynak", "leaderboard"))}
    sonuc = []
    for modul in (eski, yeni):
        onbellek = modul.CandleCache(istemci, start_200, now_ms)
        sonuc.append(modul.evaluate_address(dict(lider), istemci, onbellek, now, start, start_200, semboller, rules, False,
                                            log=lambda *_: None, dexes=modul.hip3_dex_names(istemci), gunluk={}))
    e, y = sonuc
    sutunlar = sorted(c for c in set(e) | set(y) if not kontrol_disi(c))
    farkli = [c for c in sutunlar if repr(e.get(c)) != repr(y.get(c))]
    return {"adres": lider["address"], "hatali": "hata" in e or "hata" in y, "karsilastirilan_sutun": len(sutunlar), "fark": farkli,
            "ornek": {c: [repr(e.get(c)), repr(y.get(c))] for c in farkli[:5]}}


def esit_aralikli(adresler: list[str], n: int) -> list[str]:
    adresler = sorted(adresler)
    n = min(n, len(adresler))
    return [adresler[int(i * len(adresler) / n)] for i in range(n)]


def karsilastir(eski: Any, yeni: Any, istemci: Any, tablo: pd.DataFrame, basarili: int, hatali: int, semboller: set[str], rules: dict,
                log: Any = print) -> dict[str, Any]:
    ok = tablo[(tablo["hata"].isna() if "hata" in tablo else True) & (tablo["asama1"] == "Geçti")]
    bozuk = tablo[tablo["hata"].notna()] if "hata" in tablo else tablo.iloc[0:0]
    secim = esit_aralikli([str(a) for a in ok["address"]], basarili) + esit_aralikli([str(a) for a in bozuk["address"]], hatali)
    ayrinti = []
    for sira, adres in enumerate(secim, 1):
        satir = tablo[tablo["address"].astype(str) == adres].iloc[0].to_dict()
        sonuc = cift_kos(eski, yeni, istemci, satir, semboller, rules)
        log(f"[{sira}/{len(secim)}] {adres[:12]}… {'hatalı' if sonuc['hatali'] else 'başarılı'} — {len(sonuc['fark'])} sütun farkı {sonuc['fark']}")
        ayrinti.append(sonuc)
    return {"karsilastirilan_adres": len(ayrinti), "basarili": sum(not a["hatali"] for a in ayrinti), "hatali": sum(a["hatali"] for a in ayrinti),
            "fark_olan_adres": sum(bool(a["fark"]) for a in ayrinti), "fark_toplam_sutun": sum(len(a["fark"]) for a in ayrinti),
            "kontrol_disi": list(KONTROL_DISI) + list(KONTROL_DISI_SUTUN), "ayrinti": ayrinti}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--eski-kok", type=Path, required=True, help="eski kodun çalışma ağacı (ör. main'in git worktree'si)")
    parser.add_argument("--sonuc", type=Path, required=True, help="gün sonuc.csv (adresler, now_ms, account_value buradan)")
    parser.add_argument("--basarili", type=int, default=8)
    parser.add_argument("--hatali", type=int, default=4)
    parser.add_argument("--cikti", type=Path, help="özeti JSON olarak yaz")
    args = parser.parse_args(argv)
    from copytrade import kapi as yeni_kapi
    from copytrade.kurallar import load_rules
    from copytrade.tarama import KAPI_YENIDEN_BEKLEME, PublicClient, RateLimiter
    eski = modul_yukle(args.eski_kok)
    tablo = pd.read_csv(args.sonuc, low_memory=False, float_precision="round_trip", dtype={"kod_hash": str, "hesap": str})
    istemci = TekrarIstemci(PublicClient(limiter=RateLimiter(1000), yeniden_bekleme=KAPI_YENIDEN_BEKLEME))
    with tempfile.TemporaryDirectory() as gecici:
        semboller, _ = yeni_kapi.write_binance_universe(Path(gecici))
    print(f"eski kod hash {eski.HESAP_KOD_HASH[:12]}…, yeni kod hash {yeni_kapi.HESAP_KOD_HASH[:12]}…")
    ozet = karsilastir(eski, yeni_kapi, istemci, tablo, args.basarili, args.hatali, semboller, load_rules())
    ozet["gercek_istek_yontem_sayisi"] = dict(istemci.cagri)
    print(json.dumps({k: v for k, v in ozet.items() if k != "ayrinti"}, ensure_ascii=False))
    if args.cikti:
        args.cikti.write_text(json.dumps(ozet, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
