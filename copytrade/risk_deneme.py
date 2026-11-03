"""H5 kural 1 denemesi: kayıtlı/örnek olay akışını (ağ YOK) `Dinleyici.mesaj_isle` üzerinden risk defterine oynatır; `ozet.json` risk bloğunu ve karar satırlarını yazar.

Kullanım: python -m copytrade.risk_deneme [--akis akis.jsonl] [--cikti klasor]
Akış satırı: {"alma_ms": int, "mesaj": <WS çerçevesi>}; --akis yoksa yerleşik örnek (2 trader, 12 olay) oynatılır. Gerçek sunucu denemesini lider kullanıcıyla yapar.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from copytrade.dinleyici import Dinleyici, Izlenen
from copytrade.kurallar import load_rules
from copytrade.risk_defter import GUN_MS, KararGunlugu, RiskDefteri

T = 20_000 * GUN_MS
A, B = "0x" + "a" * 40, "0x" + "b" * 40


def _tr(tid, ms, coin, yon, sz, px, adres):
    karsi = "0x" + "9" * 40
    return {"channel": "trades", "data": [{"coin": coin, "side": yon, "px": str(px), "sz": str(sz), "time": ms, "tid": tid, "users": [adres, karsi] if yon == "B" else [karsi, adres]}]}


def _uf(tid, ms, coin, yon, sz, px, bas, adres):
    return {"channel": "userFills", "data": {"isSnapshot": False, "user": adres, "fills": [{"coin": coin, "px": str(px), "sz": str(sz), "side": yon, "time": ms, "tid": tid, "startPosition": str(bas)}]}}


def ornek_akis() -> list[dict]:
    s = 1000
    return [
        {"alma_ms": T + 1 * s + 400, "mesaj": _tr(1, T + 1 * s, "BTC", "B", 0.5, 60000, A)},               # A açılış (trades)
        {"alma_ms": T + 1 * s + 900, "mesaj": _uf(1, T + 1 * s, "BTC", "B", 0.5, 60000, 0, A)},            # aynı dolum userFills'ten: tekrar
        {"alma_ms": T + 5 * s + 300, "mesaj": _uf(2, T + 5 * s, "ETH", "B", 10, 3000, 0, A)},              # A ikinci coin
        {"alma_ms": T + 9 * s + 300, "mesaj": _uf(3, T + 9 * s, "SOL", "B", 100, 150, 0, A)},              # A üçüncü coin
        {"alma_ms": T + 20 * s + 20_000, "mesaj": _uf(4, T + 20 * s, "BTC", "B", 0.5, 60100, 0.5, A)},     # 20 sn geç: ekleme -> gec_sinyal
        {"alma_ms": T + 30 * s + 300, "mesaj": _uf(5, T + 30 * s, "BTC", "B", 5, 60100, 1.0, A)},          # büyük ekleme (x5): emir_limiti
        {"alma_ms": T + 40 * s + 300, "mesaj": _tr(6, T + 40 * s, "DOGE", "B", 1000, 0.2, B)},             # B yedek: yalnız ölçülür
        {"alma_ms": T + 50 * s + 300, "mesaj": _uf(7, T + 50 * s, "AVAX", "A", 3, 30, 3, A)},              # miras kapanış (kopya yok)
        {"alma_ms": T + 60 * s + 100, "mesaj": _tr(8, T + 60 * s, "BTC", "B", 0.01, 54000, "0x" + "7" * 40)},   # izlenmeyen: BTC fiyatı düşer (−%10)
        {"alma_ms": T + 70 * s + 300, "mesaj": _uf(9, T + 70 * s, "BTC", "A", 0.25, 54000, 1.0, A)},       # A BTC'nin 1/4'ünü kapatır (kopya payı kapanır)
        {"alma_ms": T + 80 * s + 300, "mesaj": _uf(10, T + 80 * s, "ETH", "A", 10, 3000, 10, A)},          # ETH tam kapanış
        {"alma_ms": T + 90 * s + 300, "mesaj": _uf(11, T + 90 * s, "BTC", "A", 0.75, 54000, 0.75, A)},     # BTC tam kapanış
    ]


def oynat(akis: list[dict], cikti: Path) -> dict:
    kural = load_rules()
    saat = [T]
    liste = [Izlenen("aaaa", A, "ilk11"), Izlenen("bbbb", B, "yedek11")]
    risk = RiskDefteri({"aaaa"}, kural, baslangic_ms=T)
    din = Dinleyici(liste, ["BTC", "ETH", "SOL", "AVAX", "DOGE"], None, lambda y: [], cikti, saat_ms=lambda: saat[0], risk=risk, risk_gunlugu=KararGunlugu(cikti))
    for satir in akis:
        saat[0] = int(satir["alma_ms"])
        din.mesaj_isle(json.dumps(satir["mesaj"]))
    din.ozet_yaz()
    return din.ozet()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--akis", type=Path, default=None)
    ap.add_argument("--cikti", type=Path, default=None)
    a = ap.parse_args(argv)
    akis = [json.loads(s) for s in a.akis.read_text(encoding="utf-8").splitlines() if s.strip()] if a.akis else ornek_akis()
    cikti = a.cikti or Path(tempfile.mkdtemp(prefix="risk_deneme_"))
    ozet = oynat(akis, cikti)
    print(json.dumps(ozet["risk"], ensure_ascii=False, indent=1, sort_keys=True))
    for satir in (cikti / "risk_kararlari.jsonl").read_text(encoding="utf-8").splitlines():
        k = json.loads(satir)
        print(f'{k["trader"]} {k["coin"]:5} {k["aksiyon"]:5} {"KABUL" if k["kabul"] else "RET  "} {k["notional_usd"]:>9} $  gecikme={k["gecikme_sn"]}s  {",".join(k["nedenler"])}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
