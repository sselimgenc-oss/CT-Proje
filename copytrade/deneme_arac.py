"""Kural 1 küçük gerçek veri denemeleri için yardımcılar (eski `ilk11_deneme` modülünden kalan genel parçalar, T1).

Deneme iş akışları (`izleme_deneme.yml`, `gecikme_kar_deneme.yml`) çağırır; üretim verisine yazmaz.

- ``liste``: ana izleme listesinden verilen `id`'leri olduğu gibi seçip küçük bir deneme listesi yazar.
- ``durum-ozeti``: izleme `durum.json`'dan trader başına veri durumu, sağlık ışığı, hesap ($, trader ölçeği), v3 ve olay özeti + süre tahmini.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

SAATLIK_BUTCE_DK = 55      # tek koşu için yaklaşık süre bütçesi (dk); tahmin bunu aşarsa uyarı yazılır


def sure_tahmini(n: int, ilk_sn: float | None, artimli_sn: float | None, hedef_trader: int | None = None) -> list[str]:
    """İlk okuma ve artımlı koşu süreleri AYRI. ``hedef_trader`` verilirse o sayıya doğrusal tahmin; yoksa yalnız ölçülen süre yazılır."""
    out = []
    for ad, sn in (("ilk okuma", ilk_sn), ("artımlı koşu", artimli_sn)):
        if sn:
            satir = f"- {ad}: {n} trader {sn:.0f} sn (trader başı ≈ {sn / max(1, n):.0f} sn)"
            if hedef_trader:
                satir += f" → {hedef_trader} trader ≈ {sn / max(1, n) * hedef_trader / 60:.0f} dk"
            out.append(satir)
    if hedef_trader and artimli_sn and artimli_sn / max(1, n) * hedef_trader / 60 > SAATLIK_BUTCE_DK:
        out.append(f"- **UYARI:** artımlı koşu tahmini {SAATLIK_BUTCE_DK} dk bütçesini aşıyor")
    return out or ["- süre ölçülmedi"]


def liste_sec(kaynak: Path, idler: list[str], cikti: Path) -> list[dict]:
    """Ana izleme listesinden verilen kimlikleri (`id`) olduğu gibi (adres, t0, tarz …) seçip deneme listesi yazar."""
    satirlar = yaml.safe_load(kaynak.read_text(encoding="utf-8"))["traderlar"]
    bulunan = {r["id"]: r for r in satirlar}
    eksik = [i for i in idler if i not in bulunan]
    if eksik:
        raise ValueError(f"listede olmayan kimlik: {eksik}")
    secilen = [bulunan[i] for i in idler]
    cikti.mkdir(parents=True, exist_ok=True)
    (cikti / "izleme_listesi.yaml").write_text(yaml.safe_dump({"traderlar": secilen}, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return secilen


def durum_ozeti(durum: Path, sure_sn: float | None, artimli_sn: float | None, hedef_trader: int | None = None) -> str:
    """Trader başına `veri_durumu`, sağlık ışığı, hesap, v3 özeti + süre tahmini (gerçek veri denemesi)."""
    d = json.loads(durum.read_text(encoding="utf-8"))
    out = ["### Trader durumları", "", "| id | gecerli | veri_durumu | neden | ışık | hesap (perp) $ | v3 bakiye $ | v3 fiyatsız | v3 kapanan | mum eksik (hedef/önbellekten) | olay |",
           "|---|---|---|---|---|---|---|---|---|---|---|"]
    olay: dict[str, int] = {}
    for e in d.get("olaylar", []):
        olay[e["trader"]] = olay.get(e["trader"], 0) + 1
    for t in d["traderlar"]:
        v3 = t.get("sanal_kopya_v3") or {}
        nedenler = t["saglik"].get("nedenler") or ["—"]
        out.append(f"| {t['id']} | {t['gecerli']} | {t.get('veri_durumu')} | {t.get('veri_durumu_neden', '')} | {t['saglik']['isik']} ({nedenler[0]}) | "
                   f"{t.get('hesap_degeri', 0):.0f} | {v3.get('bakiye_usd', '—')} | {v3.get('fiyatsiz_eylem', '—')} | {len(v3.get('kapanan_islemler') or [])}/{v3.get('kapanan_islemler_toplam', '—')} | "
                   f"{(t.get('mum_eksik') or {}).get('hedef', '—')}/{(t.get('mum_eksik') or {}).get('onbellekten', '—')} | {olay.get(t['id'], 0)} |")
    oz = d.get("olay_ozeti") or {}
    out += ["", f"olay özeti: toplam {oz.get('toplam', '—')}, yayımlanan {oz.get('yayimlanan', '—')}, taşan {oz.get('tasan', '—')} (taşan olaylar olay_tasan.jsonl → veri dalı arşivi)"]
    for tid, toplam in sorted((oz.get("trader_basina") or {}).items()):
        out.append(f"- olay {tid}: yayın {olay.get(tid, 0)} / taşan→arşiv {toplam - olay.get(tid, 0)} / toplam {toplam}")
    return "\n".join(out + ["", "### İzleme süresi", ""] + sure_tahmini(len(d["traderlar"]), sure_sn, artimli_sn, hedef_trader)) + "\n"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    alt = ap.add_subparsers(dest="komut", required=True)
    ls = alt.add_parser("liste")
    ls.add_argument("--kaynak", type=Path, required=True)
    ls.add_argument("--idler", required=True, help="virgülle ayrılmış izleme listesi kimlikleri")
    ls.add_argument("--cikti", type=Path, required=True)
    ds = alt.add_parser("durum-ozeti")
    ds.add_argument("--durum", type=Path, required=True)
    ds.add_argument("--sure-sn", type=float, default=None)
    ds.add_argument("--artimli-sn", type=float, default=None)
    ds.add_argument("--hedef-trader", type=int, default=None, help="süre tahmininin doğrusal ölçekleneceği trader sayısı")
    a = ap.parse_args(argv)
    if a.komut == "liste":
        print(json.dumps([r["id"] for r in liste_sec(a.kaynak, [i.strip() for i in a.idler.split(",") if i.strip()], a.cikti)]))
    else:
        print(durum_ozeti(a.durum, a.sure_sn, a.artimli_sn, a.hedef_trader))


if __name__ == "__main__":
    main()
