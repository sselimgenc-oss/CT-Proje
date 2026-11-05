"""Seçim isabeti (docs/RADAR_V1.md §7b; görev T6 §1): 7 gün önceki `havuz.json` + `kadro.json` için ARADA geçen 7 günün kopya getirisi (`sonraki_7g`) ve seçimin işe yarayıp yaramadığı.
Yalnız ÖLÇER: eşik, ağırlık ve karar kodu değişmez; ek motor/emir yok.

Kural 7 (tek yer): kopya getirisi `radar_tarama.Baglam.kopya_oynat` → `kopya_v5` ile hesaplanır (R1/6 ile AYNI oynatma: `radar_kopya_gecikme_dk` gecikme + maliyet, aynı slot,
pencere başında BOŞ, `trader_hesap_usd` = havuz satırındaki hesap değeri). Burada yeni getiri hesabı YOKTUR; yalnız gruplama, özet ve sıra korelasyonu.

**Gruplar:** (i) `ilk11` (o günün kadrosunda `katman == ilk11`); (ii) `havuz_geri` (R1 havuzunda `gecti` olup İlk 11 dışındakiler; Yedek dahil); (iii) `elenen` (kopya aşamasına varıp
— `kopya_getiri_7g` dolu — R1'den elenenler; en çok `isabet_elenen_ust` = 30 kişi, SABİT TOHUMLA rastgele; tohum = YYYYMMDD sayısı, dosyaya yazılır).
**Kötü senaryo (K‑37):** aynı ölçüm kayma ×`isabet_kotu_kayma_carpan` (2) ve gecikme `isabet_kotu_gecikme_dk` (3 dk) ile; sütun adları `_kotu` ile biter.

**Çıktı `radar/<havuz tarihi>/isabet.json`** (docs/VERI_SOZLESMESI.md "Radar isabet"): oranlar kesirdir (0,02 = %2), kopya_$ = 1.000 $ sanal kasa ölçeğinde getiri; zaman UTC ms.
Süre bütçesi `isabet_butce_dk` (30): aşılırsa kalanlar ölçülmez, `eksik: true` yazılır ve tarama işi bozulmaz (çıkış kodu 0, ama hata/eksik dosyada ve günlükte görünür).

    python -m copytrade.radar_isabet --cikti radar --veri-dali radar            # bugün − 7 gün (radar.yml)
    python -m copytrade.radar_isabet --cikti radar --veri-dali radar-deneme --tarih 2026-11-04 --kismi   # deneme: pencere henüz tam 7 gün değil
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from copytrade import radar_tarama
from copytrade.defter import HOUR
from copytrade.kurallar import load_rules
from copytrade.olcut import perp_fills

SEMA = "radar-isabet-v1"
GUN_MS = 24 * HOUR
HATALAR = radar_tarama.HATALAR


# ------------------------------------------------------------------------------------------------------------------------------ saf fonksiyonlar
def tohum_uret(tarih: str) -> int:
    """Havuz tarihinden (YYYY-MM-DD) sabit tohum: 20261104. Kodda başka sayı sabiti yok; aynı gün aynı seçim."""
    return int(tarih.replace("-", ""))


def gruplari_sec(havuz: dict, kadro: dict, tarih: str, elenen_ust: int = 30) -> dict:
    """{`gruplar`: {ilk11, havuz_geri, elenen: [adres]}, `form`: {adres: form}, `tohum`}. `elenen`: kopya aşamasına varıp (kopya_getiri_7g dolu) `gecti=False` olanlar; aday listesi adres sırasına göre
    SIRALANIR, sonra `random.Random(tohum).sample` ile en çok `elenen_ust` kişi seçilir (taşınabilir: aynı girdi aynı seçim)."""
    form = {s["adres"]: s.get("form") for s in kadro.get("satirlar", [])}
    ilk11 = [s["adres"] for s in kadro.get("satirlar", []) if s.get("katman") == "ilk11"]
    ilk_set = set(ilk11)
    geri = [r["adres"] for r in havuz["satirlar"] if r.get("gecti") and r["adres"] not in ilk_set]
    adaylar = sorted(r["adres"] for r in havuz["satirlar"] if not r.get("gecti") and r.get("kopya_getiri_7g") is not None)
    tohum = tohum_uret(tarih)
    elenen = sorted(random.Random(tohum).sample(adaylar, min(int(elenen_ust), len(adaylar))))
    return {"gruplar": {"ilk11": ilk11, "havuz_geri": geri, "elenen": elenen}, "form": form, "tohum": tohum, "elenen_aday_sayisi": len(adaylar)}


def grup_ozeti(degerler: list[float]) -> dict:
    """n / ortalama / medyan / kârda olanların oranı (> 0). Boş grup → n 0, diğerleri None."""
    if not degerler:
        return {"n": 0, "ortalama": None, "medyan": None, "kar_orani": None}
    return {"n": len(degerler), "ortalama": sum(degerler) / len(degerler), "medyan": float(statistics.median(degerler)), "kar_orani": sum(1 for d in degerler if d > 0) / len(degerler)}


def _sirala(x: list[float]) -> list[float]:
    """Ortalama sıra (eşitlikte ortalama): 1..n."""
    idx = sorted(range(len(x)), key=lambda i: x[i])
    sira = [0.0] * len(x)
    i = 0
    while i < len(idx):
        j = i
        while j + 1 < len(idx) and x[idx[j + 1]] == x[idx[i]]:
            j += 1
        for k in range(i, j + 1):
            sira[idx[k]] = (i + j) / 2 + 1
        i = j + 1
    return sira


def spearman(x: list[float], y: list[float]) -> float | None:
    """Spearman sıra korelasyonu (Pearson(sıra)); n < 3 ya da bir taraf sabitse None."""
    if len(x) != len(y) or len(x) < 3:
        return None
    rx, ry = _sirala(x), _sirala(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    sxx, syy = sum((a - mx) ** 2 for a in rx), sum((b - my) ** 2 for b in ry)
    if sxx == 0 or syy == 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(rx, ry)) / (sxx * syy) ** 0.5


def _fark(a: dict, b: dict, anahtar: str = "ortalama") -> float | None:
    return None if a.get(anahtar) is None or b.get(anahtar) is None else a[anahtar] - b[anahtar]


def isabet_olustur(tarih: str, havuz: dict, kadro: dict, secim: dict, olcum: dict[str, dict], bas_ms: int, bit_ms: int, pencere_tam: bool, eksik: bool, sure_dk: float,
                   hata: str | None = None) -> dict:
    """Saf montaj. `olcum`: {adres: {"sonraki_7g": float|None, "sonraki_7g_kotu": float|None, "hata": str|None}} (ölçülmeyen adres yok). `eksik`: bütçe/okuma nedeniyle ölçülemeyen adres var."""
    gruplar, form = secim["gruplar"], secim["form"]
    ozet: dict[str, dict] = {}
    satirlar = []
    for ad, adresler in gruplar.items():
        ol = [olcum.get(a) or {} for a in adresler]
        iyi = [o["sonraki_7g"] for o in ol if o.get("sonraki_7g") is not None]
        kotu = [o["sonraki_7g_kotu"] for o in ol if o.get("sonraki_7g_kotu") is not None]
        g, gk = grup_ozeti(iyi), grup_ozeti(kotu)
        ozet[ad] = {**g, "secilen": len(adresler), "olculemeyen": len(adresler) - len(iyi), **{f"{k}_kotu": v for k, v in gk.items()}}
        for a in adresler:
            o = olcum.get(a) or {}
            satirlar.append({"adres": a, "grup": ad, "form": form.get(a), "sonraki_7g": o.get("sonraki_7g"), "sonraki_7g_kotu": o.get("sonraki_7g_kotu"), "hata": o.get("hata")})

    def havuz_grubu(anahtar_getiri: str) -> dict:                       # R1 havuzunun tamamı = İlk 11 ∪ geri kalan
        return grup_ozeti([s[anahtar_getiri] for s in satirlar if s["grup"] in ("ilk11", "havuz_geri") and s[anahtar_getiri] is not None])

    havuz_iyi, havuz_kotu = havuz_grubu("sonraki_7g"), havuz_grubu("sonraki_7g_kotu")
    ic_satir = [s for s in satirlar if s["grup"] in ("ilk11", "havuz_geri") and s["form"] is not None]

    def ic(anahtar: str) -> tuple[float | None, int]:
        cift = [(s["form"], s[anahtar]) for s in ic_satir if s[anahtar] is not None]
        return spearman([c[0] for c in cift], [c[1] for c in cift]), len(cift)

    ic_iyi, ic_n = ic("sonraki_7g")
    ic_kotu, _ = ic("sonraki_7g_kotu")
    ilk, ilk_k = ozet["ilk11"], {k[:-5]: v for k, v in ozet["ilk11"].items() if k.endswith("_kotu")}
    elenen, elenen_k = ozet["elenen"], {k[:-5]: v for k, v in ozet["elenen"].items() if k.endswith("_kotu")}
    return {"sema": SEMA, "tarih": tarih, "havuz_kosu_ms": havuz["kosu_ms"], "pencere_bas_ms": bas_ms, "pencere_bit_ms": bit_ms, "pencere_tam": pencere_tam,
            "pencere_gun": (bit_ms - bas_ms) / GUN_MS, "tohum": secim["tohum"], "elenen_aday_sayisi": secim["elenen_aday_sayisi"], "eksik": eksik, "hata": hata, "sure_dk": sure_dk,
            "gruplar": ozet, "havuz": {**havuz_iyi, **{f"{k}_kotu": v for k, v in havuz_kotu.items()}},
            "ic": ic_iyi, "ic_kotu": ic_kotu, "ic_n": ic_n,
            "fark_ilk11_havuz": _fark(ilk, havuz_iyi), "fark_ilk11_havuz_kotu": _fark(ilk_k, havuz_kotu),
            "fark_ilk11_elenen": _fark(ilk, elenen), "fark_ilk11_elenen_kotu": _fark(ilk_k, elenen_k),
            "satirlar": satirlar}


def ozet_md(i: dict) -> str:
    """İş özeti / pano satırı kaynağı: grup n / ortalama / medyan / kâr oranı, IC ve farklar (normal ve kötü)."""
    f = lambda v: "—" if v is None else f"{v:+.4f}"            # noqa: E731
    c = [f"### Seçim isabeti {i['tarih']} (pencere {i['pencere_gun']:.2f} gün{'' if i['pencere_tam'] else ' — KISMİ, tam 7 gün değil'}{', EKSİK' if i['eksik'] else ''})", "",
         "| grup | seçilen | n | ortalama | medyan | kâr oranı | ortalama (kötü) |", "|---|---|---|---|---|---|---|"]
    for ad in ("ilk11", "havuz_geri", "elenen"):
        g = i["gruplar"][ad]
        c.append(f"| {ad} | {g['secilen']} | {g['n']} | {f(g['ortalama'])} | {f(g['medyan'])} | {'—' if g['kar_orani'] is None else format(g['kar_orani'], '.2f')} | {f(g['ortalama_kotu'])} |")
    c += ["", f"IC (form ↔ sonraki_7g, n={i['ic_n']}): {f(i['ic'])} (kötü {f(i['ic_kotu'])}) · İlk 11 − havuz: {f(i['fark_ilk11_havuz'])} (kötü {f(i['fark_ilk11_havuz_kotu'])}) · "
          f"İlk 11 − elenen: {f(i['fark_ilk11_elenen'])} (kötü {f(i['fark_ilk11_elenen_kotu'])}) · tohum {i['tohum']}", ""]
    return "\n".join(c)


# ------------------------------------------------------------------------------------------------------------------------------ ağ
def getiri_al(sonuc: dict) -> float | None:
    """`kopya_oynat` sonucundan kopya getirisi (oran). `hesaplanamadi` → None."""
    if sonuc.get("durum") == "hesaplanamadi":
        return None
    return radar_tarama._sayi(sonuc.get("getiri"))


def olc(client: Any, havuz: dict, kadro: dict, secim: dict, rules: dict, bas_ms: int, bit_ms: int, log: Callable[[str], None] = print, saat: Callable[[], float] = time.monotonic) -> tuple[dict, bool]:
    """Her seçilen adres için normal ve kötü senaryo `sonraki_7g`. Döner (ölçüm, eksik). Piyasa verisi (mum, hacim, azami kaldıraç) iki senaryoda ORTAK (bir kez çekilir)."""
    kotu_kurallar = {**rules, "radar_kopya_gecikme_dk": int(rules["isabet_kotu_gecikme_dk"]), "maliyet_kayma": float(rules["maliyet_kayma"]) * float(rules["isabet_kotu_kayma_carpan"])}
    iyi = radar_tarama.Baglam(client, bit_ms, bas_ms, rules)
    iyi.piyasa_oku()
    kotu = radar_tarama.Baglam(client, bit_ms, bas_ms, kotu_kurallar)
    kotu.hacim, kotu.azami_kaldirac, kotu.mum = iyi.hacim, iyi.azami_kaldirac, iyi.mum
    hesap = {r["adres"]: float(r["hesap_usd"]) for r in havuz["satirlar"]}
    butce = float(rules["isabet_butce_dk"]) * 60.0
    baslangic = saat()
    olcum: dict[str, dict] = {}
    eksik = False
    adresler = [a for g in ("ilk11", "havuz_geri", "elenen") for a in secim["gruplar"][g]]
    for sira, adres in enumerate(adresler, 1):
        if saat() - baslangic >= butce:
            eksik = True
            log(f"UYARI: isabet zaman bütçesi ({rules['isabet_butce_dk']} dk) aşıldı; kalan {len(adresler) - sira + 1} adres ölçülmedi")
            break
        satir = {"sonraki_7g": None, "sonraki_7g_kotu": None, "hata": None}
        try:
            dolumlar = client.fills(adres, bas_ms, max_rows=int(rules["radar_dolum_tavan"]), end_ms=bit_ms)
            if len(dolumlar) >= int(rules["radar_dolum_tavan"]):
                satir["hata"] = "dolum_fazla"
            else:
                dolumlar = [f for f in perp_fills(dolumlar) if bas_ms <= int(f["time"]) < bit_ms]
                if not dolumlar:
                    satir["sonraki_7g"] = satir["sonraki_7g_kotu"] = 0.0          # pencerede işlem yok → kopya getirisi 0 (ölçüldü)
                else:
                    satir["sonraki_7g"] = getiri_al(iyi.kopya_oynat(dolumlar, hesap[adres]))
                    satir["sonraki_7g_kotu"] = getiri_al(kotu.kopya_oynat(dolumlar, hesap[adres]))
                    if satir["sonraki_7g"] is None or satir["sonraki_7g_kotu"] is None:
                        satir["hata"] = "hesaplanamadi"
        except HATALAR as hata:
            satir["hata"] = type(hata).__name__
        olcum[adres] = satir
        log(f"[{sira}/{len(adresler)}] {adres[:10]}… sonraki_7g {satir['sonraki_7g']} kötü {satir['sonraki_7g_kotu']} {satir['hata'] or ''}")
        if satir["hata"]:
            eksik = True
    return olcum, eksik


def git_oku(dal: str, yol: str) -> dict | None:
    """Veri dalından (`origin/<dal>`) JSON okur; yoksa None."""
    s = subprocess.run(["git", "show", f"origin/{dal}:{yol}"], capture_output=True, text=True)
    return json.loads(s.stdout) if s.returncode == 0 and s.stdout.strip() else None


def calistir(client: Any, havuz: dict, kadro: dict, tarih: str, simdi_ms: int, rules: dict, kismi: bool = False, log: Callable[[str], None] = print,
             saat: Callable[[], float] = time.monotonic) -> dict | None:
    """Tek havuz için isabet. Pencere = [havuz.kosu_ms, min(simdi, kosu_ms + 7 gün)]. Tam 7 gün dolmadıysa `kismi` yoksa None (ölçülmez); `kismi` ile ölçülür ve `pencere_tam: false` yazılır."""
    bas = int(havuz["kosu_ms"])
    tam_bit = bas + int(rules["isabet_pencere_gun"]) * GUN_MS
    pencere_tam = simdi_ms >= tam_bit
    if not pencere_tam and not kismi:
        log(f"isabet: {tarih} havuzu için 7 gün dolmadı (bitiş {datetime.fromtimestamp(tam_bit / 1000, UTC):%Y-%m-%d %H:%M} UTC); ölçülmedi")
        return None
    bit = min(simdi_ms, tam_bit)
    t0 = saat()
    secim = gruplari_sec(havuz, kadro, tarih, int(rules["isabet_elenen_ust"]))
    hata = None
    try:
        olcum, eksik = olc(client, havuz, kadro, secim, rules, bas, bit, log, saat)
    except HATALAR as h:                                                  # piyasa verisi okunamadı: tarama bozulmaz; eksik + hata dosyada
        olcum, eksik, hata = {}, True, type(h).__name__
        log(f"UYARI: isabet ölçümü yapılamadı ({hata})")
    return isabet_olustur(tarih, havuz, kadro, secim, olcum, bas, bit, pencere_tam, eksik, (saat() - t0) / 60.0, hata)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cikti", type=Path, default=Path("radar"))
    ap.add_argument("--veri-dali", default="radar", help="havuz/kadro okunan veri dalı (origin/<dal>): radar | radar-deneme")
    ap.add_argument("--tarih", default=None, help="ölçülecek havuz tarihi (YYYY-MM-DD); varsayılan bugün − isabet_pencere_gun")
    ap.add_argument("--kismi", action="store_true", help="DENEME: 7 gün dolmamış pencereyi de ölç (`pencere_tam: false`)")
    ap.add_argument("--ozet-md", type=Path, default=None)
    args = ap.parse_args(argv)
    rules = load_rules()
    simdi = int(time.time() * 1000)
    tarih = args.tarih or (datetime.fromtimestamp(simdi / 1000, UTC).date() - timedelta(days=int(rules["isabet_pencere_gun"]))).isoformat()
    havuz, kadro = git_oku(args.veri_dali, f"radar/{tarih}/havuz.json"), git_oku(args.veri_dali, f"radar/{tarih}/kadro.json")
    if not havuz or not kadro:
        print(f"isabet: origin/{args.veri_dali} dalında radar/{tarih}/ havuz+kadro yok (ilk ölçüm 2026-11-12); atlandı")
        return 0
    try:
        sonuc = calistir(radar_tarama.radar_istemcisi(rules=rules), havuz, kadro, tarih, simdi, rules, args.kismi)
    except Exception as hata:                                             # noqa: BLE001 — tarama işi bozulmaz; hata dosyada ve günlükte görünür
        print(f"UYARI: isabet adımı hata verdi: {type(hata).__name__}: {str(hata)[:200]}", file=sys.stderr)
        sonuc = None
        if havuz:
            secim = gruplari_sec(havuz, kadro, tarih, int(rules["isabet_elenen_ust"]))
            sonuc = isabet_olustur(tarih, havuz, kadro, secim, {}, int(havuz["kosu_ms"]), simdi, False, True, 0.0, type(hata).__name__)
    if sonuc is None:
        return 0
    klasor = args.cikti / tarih
    klasor.mkdir(parents=True, exist_ok=True)
    gecici = klasor / "isabet.json.tmp"
    gecici.write_text(json.dumps(sonuc, ensure_ascii=False, indent=1, allow_nan=False) + "\n", encoding="utf-8")
    gecici.replace(klasor / "isabet.json")
    md = ozet_md(sonuc)
    print(md)
    if args.ozet_md:
        args.ozet_md.write_text(md, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
