"""D+ kadrosunun dolumlarını tek sanal kasa üzerinde, zaman sırasıyla oynatır.

Girdi JSON: {"uyeler": [{"adres": "...", "hesap_usd": 1000,
"dolumlar": [{"time": 1, "coin": "BTC", "side": "B", "sz": 1, "px": 100}]}],
"son_fiyatlar": {"BTC": 110}}. Dolumlar yürütme fiyatındadır; gecikme ve
funding modellenmez. Bitiş değerlemesi son_fiyatlar (yoksa son dolum fiyatı).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from copytrade import boyut
from copytrade.canli.hesap import Hesap
from copytrade.canli.motor import eylem_belirle
from copytrade.canli.risk import Risk
from copytrade.kurallar import load_rules


def _oynat(uyeler: list[dict], olaylar: list[tuple[int, int, int, dict]], rules: dict, ortak: bool, son_fiyatlar: dict) -> dict:
    kasa = float(rules["canli_kasa_usd"])
    slot = kasa / 5
    hesap = Hesap(kasa, float(rules["canli_marj_kaldirac"]))
    for uye in uyeler:
        hesap.slot_ac(uye["adres"], slot)
    risk = Risk(rules, kasa)
    paydalar = {u["adres"]: float(u["hesap_usd"]) for u in uyeler}
    trader_poz: dict[tuple[str, str], float] = {}
    marks: dict[str, float] = {}
    kirpma: dict[str, float] = {}
    sayi: dict[str, int] = {}
    for zaman, _, _, f in olaylar:
        adres, coin = f["adres"], str(f["coin"])
        px, sz = float(f["px"]), float(f["sz"])
        if px <= 0 or sz <= 0 or f["side"] not in ("B", "A"):
            raise ValueError("dolum px/sz/side geçersiz")
        marks[coin] = px
        once = trader_poz.get((adres, coin), 0.0)
        sonra = once + (sz if f["side"] == "B" else -sz)
        trader_poz[(adres, coin)] = sonra
        biz = hesap.sz(adres, coin)
        for eylem in eylem_belirle(once, sonra, biz):
            acilis = eylem in ("ac", "artir")
            yon = "B" if sonra > 0 else "A"
            if acilis and ortak and hesap.ters_yonlu_var(adres, coin, yon, marks, float(rules["canli_kapanis_toz_usd"])):
                neden, kesinti = "ters_netlesme", 0.0
            else:
                toplam = sum(abs(p.sz) * marks.get(c, p.giris) for c, p in hesap.poz[adres].items())
                emir, neden = boyut.hedef_emir(eylem, 0.0 if eylem == "ac" else once,
                                               0.0 if eylem == "kapat" else sonra,
                                               paydalar[adres],
                                               abs(biz) * px, slot, px, rules, toplam)
                if acilis:
                    sinirsiz, _ = boyut.hedef_emir(eylem, 0.0 if eylem == "ac" else once, sonra,
                                                   paydalar[adres], abs(biz) * px, slot, px, rules, 0.0)
                    if sinirsiz > emir and neden == "slot_tavani":
                        kirpma[neden] = kirpma.get(neden, 0.0) + sinirsiz - emir
                        sayi[neden] = sayi.get(neden, 0) + 1
                kesinti = emir
                if ortak and acilis and emir > 0:
                    izin, red = risk.acilis_izni(adres, coin, eylem == "ac" and abs(biz) < 1e-12, zaman)
                    if not izin:
                        neden, kesinti = red, 0.0
                        kirpma[red] = kirpma.get(red, 0.0) + emir
                        sayi[red] = sayi.get(red, 0) + 1
                    else:
                        kesinti, red = risk.coin_tavani(kesinti, hesap.brut_coin(coin, marks))
                        if red:
                            kirpma[red] = kirpma.get(red, 0.0) + emir - kesinti
                            sayi[red] = sayi.get(red, 0) + 1
                        emir_marj = kesinti
                        if kesinti:
                            kesinti, red = risk.marj_kirp(kesinti, hesap.marj_toplam(), hesap.ozsermaye(marks))
                            if red:
                                kirpma[red] = kirpma.get(red, 0.0) + emir_marj - kesinti
                                sayi[red] = sayi.get(red, 0) + 1
                if kesinti > 0:
                    yon_islem = yon if acilis else ("A" if biz > 0 else "B")
                    maliyet = kesinti * (float(rules["maliyet_taker"]) + float(rules["maliyet_kayma"]))
                    hesap.uygula(adres, coin, yon_islem, kesinti / px, px, maliyet, zaman)
                    if ortak and eylem == "ac" and acilis:
                        risk.yeni_coin_kaydet(adres, coin, zaman)
            if ortak and acilis and neden == "ters_netlesme":
                # Karşı yönde açılacak nosyoneli boyut kaynağından ölç.
                emir, _ = boyut.hedef_emir(eylem, 0.0 if eylem == "ac" else once, sonra,
                                           paydalar[adres],
                                           abs(biz) * px, slot, px, rules,
                                           sum(abs(p.sz) * marks.get(c, p.giris) for c, p in hesap.poz[adres].items()))
                kirpma[neden] = kirpma.get(neden, 0.0) + emir
                sayi[neden] = sayi.get(neden, 0) + 1
            biz = hesap.sz(adres, coin)
            once = 0.0 if eylem == "kapat" and once * sonra < 0 else once
    marks.update({k: float(v) for k, v in son_fiyatlar.items()})
    return {"net_usd": hesap.ozsermaye(marks) - kasa, "kirpma_usd": kirpma, "kirpma_adet": sayi}


def oynat(uyeler: list[dict], son_fiyatlar: dict | None = None, rules: dict | None = None) -> dict:
    """Beş üyenin ortak ve bağımsız slot sonucunu karşılaştırır; getiriler kasa oranıdır."""
    rules = rules or load_rules()
    if len(uyeler) != 5 or len({u["adres"] for u in uyeler}) != 5:
        raise ValueError("D+ için beş farklı trader gerekli")
    if float(rules["canli_kasa_usd"]) != 1000 or boyut.slot_usd(1000, rules) != 200:
        raise ValueError("D+ yapılandırması 1.000 $ / 5 × 200 $ olmalı")
    if any(float(u["hesap_usd"]) <= 0 for u in uyeler):
        raise ValueError("trader hesap değeri pozitif olmalı")
    olaylar = sorted((int(f["time"]), i, j, {**f, "adres": u["adres"]})
                    for i, u in enumerate(uyeler) for j, f in enumerate(u.get("dolumlar", [])))
    bitis = son_fiyatlar or {}
    ortak = _oynat(uyeler, olaylar, rules, True, bitis)
    bagimsiz = [_oynat([u, *[{"adres": x["adres"], "hesap_usd": x["hesap_usd"]} for x in uyeler if x is not u]],
                       [o for o in olaylar if o[3]["adres"] == u["adres"]], rules, False, bitis)["net_usd"]
                for u in uyeler]
    toplam = sum(bagimsiz) / float(rules["canli_kasa_usd"])
    portfoy = ortak["net_usd"] / float(rules["canli_kasa_usd"])
    return {"uye_getirileri_toplami": toplam, "portfoy_getirisi": portfoy, "fark": toplam - portfoy,
            "kirpma_usd": ortak["kirpma_usd"], "kirpma_adet": ortak["kirpma_adet"]}


def markdown(sonuc: dict) -> str:
    satirlar = ["# D+ ortak portföy oynatması", "", "| Ölçü | Değer |", "|---|---:|",
                f"| Üye getirileri toplamı | {sonuc['uye_getirileri_toplami']:.4%} |",
                f"| Portföy getirisi | {sonuc['portfoy_getirisi']:.4%} |",
                f"| Fark | {sonuc['fark']:.4%} |", "", "| Kural | Kırpılan $ | Olay |", "|---|---:|---:|"]
    satirlar += [f"| {k} | {v:.2f} | {sonuc['kirpma_adet'][k]} |" for k, v in sorted(sonuc["kirpma_usd"].items())]
    return "\n".join(satirlar) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("girdi", type=Path)
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--md", type=Path, required=True)
    args = parser.parse_args()
    veri = json.loads(args.girdi.read_text(encoding="utf-8"))
    sonuc = oynat(veri["uyeler"], veri.get("son_fiyatlar"))
    args.json.write_text(json.dumps(sonuc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.md.write_text(markdown(sonuc), encoding="utf-8")


if __name__ == "__main__":
    main()
