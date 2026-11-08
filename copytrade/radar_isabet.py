"""Seçim isabeti (docs/RADAR_V1.md §7b; görev T6 §1): 7 gün önceki `havuz.json` + `kadro.json` için ARADA geçen 7 günün kopya getirisi (`sonraki_7g`) ve seçimin işe yarayıp yaramadığı.
Yalnız ÖLÇER: eşik, ağırlık ve karar kodu değişmez; ek motor/emir yok.

Kural 7 (tek yer): kopya getirisi `radar_tarama.Baglam.kopya_oynat` → `kopya_v5` ile hesaplanır (R1/6 ile AYNI oynatma: `radar_kopya_gecikme_dk` gecikme + maliyet, aynı slot,
pencere başında BOŞ). **Trader hesap paydası (B8, 08.11):** R1 ile aynı `radar_tarama.payda_oku` — ölçüm penceresinin `portfolio` hesap değeri geçmişi (emir anındaki değer); okunamazsa
havuz satırındaki `hesap_usd` (sabit, eski davranış; satırda `payda_kaynak`). Burada yeni getiri hesabı YOKTUR; yalnız gruplama, özet ve sıra korelasyonu.

**Gruplar:** (i) `ilk11` (o günün kadrosunda `katman == ilk11`); (ii) `havuz_geri` (R1 havuzunda `gecti` olup İlk 11 dışındakiler; Yedek dahil); (iii) `elenen` (kopya aşamasına varıp
— `kopya_getiri_7g` dolu — R1'den elenenler; en çok `isabet_elenen_ust` = 30 kişi, SABİT TOHUMLA rastgele; tohum = YYYYMMDD sayısı, dosyaya yazılır).
**Ek gruplar (denetim B6/B9, 08.11; YALNIZ BİLGİ — K‑46 karar kuralı yalnız `havuz`/`elenen` ile; ek gruplar `havuz`, `ic` ve farklara GİRMEZ):** (iv) `ilk11_fiili` (o günün ilk kadrosundan
FİİLEN sahaya oturan ilk 11; canlı motor kaydı `canli-durum` `kayit/*.jsonl`, `saha_fiili`); (v) `kor_kirpildi` (kadro üyesi olup o gün korelasyon kuralıyla saha girişi atlananlar; aynı kayıt);
(vi) `cikanlar` (önceki kadroda olup bu kadroda olmayanlar: kadro `eski_uye_neden`; alan yoksa önceki günün `kadro.json`'u ile fark); (vii) `evren_ornek30` (havuzun TÜM taranan
satırlarından sabit tohumla 30 kişi; tohum = YYYYMMDD + 1). Ek adresler ana gruplardan SONRA ölçülür; bütçe/okuma eksikleri `eksik_ek`'e yazılır (`eksik` ana gruplar içindir).
**Kötü senaryo (K‑37):** aynı ölçüm kayma ×`isabet_kotu_kayma_carpan` (2) ve gecikme `isabet_kotu_gecikme_dk` (3 dk) ile; sütun adları `_kotu` ile biter.

**Çıktı `radar/<havuz tarihi>/isabet.json`** (docs/VERI_SOZLESMESI.md "Radar isabet"): oranlar kesirdir (0,02 = %2), kopya_$ = 1.000 $ sanal kasa ölçeğinde getiri; zaman UTC ms.
Süre bütçesi `isabet_butce_dk` (30): aşılırsa kalanlar ölçülmez, `eksik: true` yazılır ve tarama işi bozulmaz (çıkış kodu 0, ama hata/eksik dosyada ve günlükte görünür).
**Hangi kadro (denetim R-1):** motor (K‑39) günün İLK kadrosunu uygular; ölçülen de odur: `kadro_ilk.json` + `havuz_ilk.json` → yoksa veri dalı geçmişindeki ilk yayım → yoksa güncel
`kadro.json` (`kadro_kaynagi`: "ilk" | "ilk_git" | "son"). **R-7:** beklenmeyen her hata `ISABET HATASI` satırıyla basılır, çıkış 0 (kadro yayımı engellenmez).

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
ANA_GRUPLAR = ("ilk11", "havuz_geri", "elenen")
EK_GRUPLAR = ("ilk11_fiili", "kor_kirpildi", "cikanlar", "evren_ornek30")     # B6/B9 (08.11): YALNIZ bilgi
EVREN_ORNEK = 30                       # `evren_ornek30` kişi sayısı (adı gereği sabit)
DURUM_DALI = "canli-durum"             # canlı motorun (1.000 $ sanal seri) durum/kayıt veri dalı
HATALAR = radar_tarama.HATALAR


# ------------------------------------------------------------------------------------------------------------------------------ saf fonksiyonlar
def tohum_uret(tarih: str) -> int:
    """Havuz tarihinden (YYYY-MM-DD) sabit tohum: 20261104. Kodda başka sayı sabiti yok; aynı gün aynı seçim."""
    return int(tarih.replace("-", ""))


def gruplari_sec(havuz: dict, kadro: dict, tarih: str, elenen_ust: int = 30, ek: dict | None = None) -> dict:
    """{`gruplar`: {ilk11, havuz_geri, elenen: [adres]}, `form`: {adres: form}, `tohum`}. `elenen`: kopya aşamasına varıp (kopya_getiri_7g dolu) `gecti=False` olanlar; aday listesi adres sırasına göre
    SIRALANIR, sonra `random.Random(tohum).sample` ile en çok `elenen_ust` kişi seçilir (taşınabilir: aynı girdi aynı seçim). `ek` (`ek_gruplari_sec` çıktısı) verilirse bilgi grupları eklenir."""
    form = {s["adres"]: s.get("form") for s in kadro.get("satirlar", [])}
    ilk11 = [s["adres"] for s in kadro.get("satirlar", []) if s.get("katman") == "ilk11"]
    ilk_set = set(ilk11)
    geri = [r["adres"] for r in havuz["satirlar"] if r.get("gecti") and r["adres"] not in ilk_set]
    adaylar = sorted(r["adres"] for r in havuz["satirlar"] if not r.get("gecti") and r.get("kopya_getiri_7g") is not None)
    tohum = tohum_uret(tarih)
    elenen = sorted(random.Random(tohum).sample(adaylar, min(int(elenen_ust), len(adaylar))))
    secim = {"gruplar": {"ilk11": ilk11, "havuz_geri": geri, "elenen": elenen}, "form": form, "tohum": tohum, "elenen_aday_sayisi": len(adaylar)}
    if ek is not None:                                                     # B6/B9 bilgi grupları: ana grupların seçimini DEĞİŞTİRMEZ (yalnız eklenir)
        secim["gruplar"].update(ek["gruplar"])
        secim["ek_kaynak"] = ek["kaynak"]
    return secim


def saha_fiili(kayitlar: list[dict], kadro: dict, bas_ms: int, bit_ms: int, ilk_n: int = 11) -> tuple[list[str], list[str], dict]:
    """B9 (bilgi): canlı motor kaydından (`kayit/<gün>.jsonl` olayları, `zaman_ms` UTC ms) kadro penceresinde [bas_ms, bit_ms) FİİLİ saha. Döner (ilk11_fiili, kor_kirpildi, bilgi).
    Pencere başındaki saha = `bas_ms`'ten önceki son `kapanis` olayının `ozet.uyeler`'i + o olay ile `bas_ms` arasındaki `saha_giris` (ekle) / `saha_dus` (çıkar); `kapanis` yoksa boş saha
    (`bilgi.saha_bas_bilinen` false). `ilk11_fiili` = pencerede sahada bulunan KADRO üyelerinden ilk `ilk_n`: önce pencere başında sahada olanlar (kadro `sira` artan), sonra pencere içi
    `saha_giris` sırasıyla (tekrar sayılmaz). Kadroda olmayan saha üyesi (önceki kadrodan kalan, motorun `kadro_disi` ile indireceği) sayılmaz. `kor_kirpildi` = pencerede `kor_kirpildi`
    olayı olan kadro üyeleri (adres sırası, tekil)."""
    kadro_sira = {r["adres"]: r.get("sira", 10 ** 6) for r in kadro.get("satirlar", [])}
    olaylar = sorted((o for o in kayitlar if isinstance(o.get("zaman_ms"), int | float)), key=lambda o: o["zaman_ms"])
    once = [o for o in olaylar if o["zaman_ms"] < bas_ms]
    kapanis = [i for i, o in enumerate(once) if o.get("olay") == "kapanis" and isinstance((o.get("ozet") or {}).get("uyeler"), list)]
    saha: set[str] = set(once[kapanis[-1]]["ozet"]["uyeler"]) if kapanis else set()
    for o in once[(kapanis[-1] + 1) if kapanis else 0:]:
        if o.get("olay") == "saha_giris":
            saha.add(o.get("adres"))
        elif o.get("olay") == "saha_dus":
            saha.discard(o.get("adres"))
    oturan = sorted((a for a in saha if a in kadro_sira), key=lambda a: (kadro_sira[a], a))
    kor: set[str] = set()
    pencere = [o for o in olaylar if bas_ms <= o["zaman_ms"] < bit_ms]
    for o in pencere:
        a = o.get("adres")
        if a not in kadro_sira:
            continue
        if o.get("olay") == "saha_giris" and a not in oturan:
            oturan.append(a)
        elif o.get("olay") == "kor_kirpildi":
            kor.add(a)
    return oturan[:ilk_n], sorted(kor), {"saha_bas_bilinen": bool(kapanis), "kayit_olay": len(pencere), "oturan_toplam": len(oturan)}


def cikanlar_sec(kadro: dict, onceki_kadro: dict | None = None) -> tuple[list[str], str | None]:
    """B6 (bilgi): önceki kadroda olup bu kadroda olmayanlar. Kaynak 1: kadro `eski_uye_neden` anahtarları (radar_kadro yazar; sıra = önceki `sira`) → "eski_uye_neden";
    alan yoksa (eski kadro) `onceki_kadro` (önceki günün `kadro.json`'u) ile fark (önceki `sira` artan) → "onceki_kadro"; ikisi de yoksa ([], None)."""
    if isinstance(kadro.get("eski_uye_neden"), dict):
        return list(kadro["eski_uye_neden"]), "eski_uye_neden"
    if onceki_kadro and onceki_kadro.get("satirlar") is not None:
        bugun = {r["adres"] for r in kadro.get("satirlar", [])}
        return [r["adres"] for r in sorted(onceki_kadro["satirlar"], key=lambda r: r.get("sira", 0)) if r["adres"] not in bugun], "onceki_kadro"
    return [], None


def evren_ornegi(havuz: dict, tarih: str, k: int = EVREN_ORNEK) -> tuple[list[str], int, int]:
    """B6 (bilgi): havuzun TÜM taranan satırlarından (R0 evreni; `gecti` ne olursa olsun) sabit tohumlu `k` kişi. Tohum = `tohum_uret(tarih) + 1` (elenen seçiminden ayrı dizi);
    aday listesi adres sırasına göre sıralanır, seçilenler sıralı döner. Döner (adresler, tohum, aday sayısı)."""
    adaylar = sorted({r["adres"] for r in havuz.get("satirlar", [])})
    tohum = tohum_uret(tarih) + 1
    return sorted(random.Random(tohum).sample(adaylar, min(int(k), len(adaylar)))), tohum, len(adaylar)


def ek_gruplari_sec(havuz: dict, kadro: dict, tarih: str, kayitlar: list[dict] | None = None, onceki_kadro: dict | None = None, ilk_n: int = 11,
                    bas_ms: int | None = None, durum_dali: str | None = None) -> dict:
    """Ek gruplar (B6/B9, YALNIZ bilgi). `kayitlar` None → canlı kayıt okunamadı: `ilk11_fiili` ve `kor_kirpildi` boş, `saha_kaynak` None (İlk 11 ile doldurulmaz: o zaten `ilk11` grubu).
    Saha penceresi = [kadro `kosu_ms`, + 24 sa) (`bas_ms` verilmezse kadro, o da yoksa havuz `kosu_ms`)."""
    bas = int(bas_ms if bas_ms is not None else kadro.get("kosu_ms") or havuz["kosu_ms"])
    if kayitlar is None:
        fiili, kor, sb = [], [], {"saha_bas_bilinen": None, "kayit_olay": None, "oturan_toplam": None}
    else:
        fiili, kor, sb = saha_fiili(kayitlar, kadro, bas, bas + GUN_MS, ilk_n)
    cik, cik_kaynak = cikanlar_sec(kadro, onceki_kadro)
    evren, evren_tohum, evren_aday = evren_ornegi(havuz, tarih)
    return {"gruplar": {"ilk11_fiili": fiili, "kor_kirpildi": kor, "cikanlar": cik, "evren_ornek30": evren},
            "kaynak": {"saha_kaynak": durum_dali if kayitlar is not None else None, "saha_bas_ms": bas, "saha_bit_ms": bas + GUN_MS, **sb,
                       "cikanlar_kaynak": cik_kaynak, "evren_tohum": evren_tohum, "evren_aday_sayisi": evren_aday}}


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
                   hata: str | None = None, kadro_kaynagi: str | None = None, eksik_ek: bool | None = None) -> dict:
    """Saf montaj. `olcum`: {adres: {"sonraki_7g": float|None, "sonraki_7g_kotu": float|None, "hata": str|None}} (ölçülmeyen adres yok). `eksik`: bütçe/okuma nedeniyle ölçülemeyen adres var.
    `kadro_kaynagi` (R-1): "ilk" (kadro_ilk.json) | "ilk_git" (veri dalı geçmişindeki ilk yayım) | "son" (güncel kadro.json; günün ilk kadrosu olmayabilir) | None (bilinmiyor)."""
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
            satirlar.append({"adres": a, "grup": ad, "form": form.get(a), "sonraki_7g": o.get("sonraki_7g"), "sonraki_7g_kotu": o.get("sonraki_7g_kotu"), "hata": o.get("hata"),
                             "payda_kaynak": o.get("payda_kaynak")})

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
    return {"sema": SEMA, "tarih": tarih, "kadro_kaynagi": kadro_kaynagi, "kadro_kosu_ms": kadro.get("kosu_ms"), "havuz_kosu_ms": havuz["kosu_ms"], "pencere_bas_ms": bas_ms, "pencere_bit_ms": bit_ms, "pencere_tam": pencere_tam,
            "pencere_gun": (bit_ms - bas_ms) / GUN_MS, "tohum": secim["tohum"], "elenen_aday_sayisi": secim["elenen_aday_sayisi"], "eksik": eksik, "hata": hata, "sure_dk": sure_dk,
            "gruplar": ozet, "havuz": {**havuz_iyi, **{f"{k}_kotu": v for k, v in havuz_kotu.items()}},
            "ic": ic_iyi, "ic_kotu": ic_kotu, "ic_n": ic_n,
            "fark_ilk11_havuz": _fark(ilk, havuz_iyi), "fark_ilk11_havuz_kotu": _fark(ilk_k, havuz_kotu),
            "fark_ilk11_elenen": _fark(ilk, elenen), "fark_ilk11_elenen_kotu": _fark(ilk_k, elenen_k),
            "satirlar": satirlar,
            **({"ek_gruplar": [g for g in EK_GRUPLAR if g in gruplar], "ek_kaynak": secim.get("ek_kaynak"), "eksik_ek": eksik_ek} if any(g in gruplar for g in EK_GRUPLAR) else {})}


def ozet_md(i: dict) -> str:
    """İş özeti / pano satırı kaynağı: grup n / ortalama / medyan / kâr oranı, IC ve farklar (normal ve kötü)."""
    f = lambda v: "—" if v is None else f"{v:+.4f}"            # noqa: E731
    c = [f"### Seçim isabeti {i['tarih']} (pencere {i['pencere_gun']:.2f} gün{'' if i['pencere_tam'] else ' — KISMİ, tam 7 gün değil'}{', EKSİK' if i['eksik'] else ''}; kadro kaynağı {i.get('kadro_kaynagi') or '?'})", "",
         "| grup | seçilen | n | ortalama | medyan | kâr oranı | ortalama (kötü) |", "|---|---|---|---|---|---|---|"]
    for ad in (*ANA_GRUPLAR, *(g for g in EK_GRUPLAR if g in i["gruplar"])):
        g = i["gruplar"][ad]
        c.append(f"| {ad}{' (bilgi)' if ad in EK_GRUPLAR else ''} | {g['secilen']} | {g['n']} | {f(g['ortalama'])} | {f(g['medyan'])} | {'—' if g['kar_orani'] is None else format(g['kar_orani'], '.2f')} | {f(g['ortalama_kotu'])} |")
    c += ["", f"IC (form ↔ sonraki_7g, n={i['ic_n']}): {f(i['ic'])} (kötü {f(i['ic_kotu'])}) · İlk 11 − havuz: {f(i['fark_ilk11_havuz'])} (kötü {f(i['fark_ilk11_havuz_kotu'])}) · "
          f"İlk 11 − elenen: {f(i['fark_ilk11_elenen'])} (kötü {f(i['fark_ilk11_elenen_kotu'])}) · tohum {i['tohum']}", ""]
    if i.get("ek_kaynak"):
        e = i["ek_kaynak"]
        c += [(f"Ek gruplar (B6/B9, yalnız bilgi; karar kuralına girmez): saha kaynağı {e.get('saha_kaynak') or 'yok'}, çıkanlar kaynağı {e.get('cikanlar_kaynak') or 'yok'}, "
               f"evren tohumu {e.get('evren_tohum')} ({e.get('evren_aday_sayisi')} aday){', EKSİK' if i.get('eksik_ek') else ''}"), ""]
    return "\n".join(c)


# ------------------------------------------------------------------------------------------------------------------------------ ağ
def getiri_al(sonuc: dict) -> float | None:
    """`kopya_oynat` sonucundan kopya getirisi (oran). `hesaplanamadi` → None."""
    if sonuc.get("durum") == "hesaplanamadi":
        return None
    return radar_tarama._sayi(sonuc.get("getiri"))


def olc(client: Any, havuz: dict, kadro: dict, secim: dict, rules: dict, bas_ms: int, bit_ms: int, log: Callable[[str], None] = print, saat: Callable[[], float] = time.monotonic,
        eksik_ek_kutu: dict | None = None) -> tuple[dict, bool]:
    """Her seçilen adres için normal ve kötü senaryo `sonraki_7g`. Döner (ölçüm, eksik). Piyasa verisi (mum, hacim, azami kaldıraç) iki senaryoda ORTAK (bir kez çekilir).
    Sıra: önce ana gruplar, sonra (varsa) ek bilgi gruplarının henüz ölçülmemiş adresleri; `eksik` yalnız ana grup adresleri içindir, ek adreslerin eksiği `eksik_ek_kutu["eksik_ek"]`'e yazılır.
    Havuzda olmayan adres (ör. `cikanlar`'da `r0_disi`) için sabit payda yedeği yoktur: portfolio okunamazsa `hata: "hesap_yok"`."""
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
    adresler = [a for g in ANA_GRUPLAR for a in secim["gruplar"][g]]
    ana = set(adresler)
    for g in EK_GRUPLAR:
        for a in secim["gruplar"].get(g, []):
            if a not in ana and a not in adresler:
                adresler.append(a)
    eksik_ek = False
    for sira, adres in enumerate(adresler, 1):
        if saat() - baslangic >= butce:
            kalan = adresler[sira - 1:]
            eksik = eksik or any(a in ana for a in kalan)
            eksik_ek = eksik_ek or any(a not in ana for a in kalan)
            log(f"UYARI: isabet zaman bütçesi ({rules['isabet_butce_dk']} dk) aşıldı; kalan {len(kalan)} adres ölçülmedi")
            break
        satir = {"sonraki_7g": None, "sonraki_7g_kotu": None, "hata": None, "payda_kaynak": None}
        try:
            dolumlar = client.fills(adres, bas_ms, max_rows=int(rules["radar_dolum_tavan"]), end_ms=bit_ms)
            if len(dolumlar) >= int(rules["radar_dolum_tavan"]):
                satir["hata"] = "dolum_fazla"
            else:
                dolumlar = [f for f in perp_fills(dolumlar) if bas_ms <= int(f["time"]) < bit_ms]
                if not dolumlar:
                    satir["sonraki_7g"] = satir["sonraki_7g_kotu"] = 0.0          # pencerede işlem yok → kopya getirisi 0 (ölçüldü)
                else:
                    payda, bilgi = radar_tarama.payda_oku(client, adres, hesap.get(adres, 0.0), bas_ms, bit_ms, rules)     # B8: R1 ile aynı zamana bağlı payda (okunamazsa sabit hesap_usd)
                    satir["payda_kaynak"] = bilgi["payda_kaynak"]
                    if adres not in hesap and bilgi["payda_kaynak"] != "portfolio":
                        satir["hata"] = "hesap_yok"                                   # havuz dışı (ek grup) adres: sabit payda yedeği yok
                    else:
                        satir["sonraki_7g"] = getiri_al(iyi.kopya_oynat(dolumlar, payda))
                        satir["sonraki_7g_kotu"] = getiri_al(kotu.kopya_oynat(dolumlar, payda))
                        if satir["sonraki_7g"] is None or satir["sonraki_7g_kotu"] is None:
                            satir["hata"] = "hesaplanamadi"
        except HATALAR as hata:
            satir["hata"] = type(hata).__name__
        olcum[adres] = satir
        log(f"[{sira}/{len(adresler)}] {adres[:10]}… sonraki_7g {satir['sonraki_7g']} kötü {satir['sonraki_7g_kotu']} {satir['hata'] or ''}")
        if satir["hata"]:
            if adres in ana:
                eksik = True
            else:
                eksik_ek = True
    if eksik_ek_kutu is not None:
        eksik_ek_kutu["eksik_ek"] = eksik_ek
    return olcum, eksik


def git_oku(dal: str, yol: str, rev: str | None = None) -> dict | None:
    """Veri dalından (`origin/<dal>`; `rev` verilirse o commit'ten) JSON okur; yoksa None."""
    s = subprocess.run(["git", "show", f"{rev or 'origin/' + dal}:{yol}"], capture_output=True, text=True)
    return json.loads(s.stdout) if s.returncode == 0 and s.stdout.strip() else None


def git_ilk_commit(dal: str, yol: str) -> str | None:
    """`origin/<dal>` geçmişinde `yol`'a dokunan EN ESKİ commit (günün ilk yayımı); geçmiş yoksa / dosya hiç yoksa None. Tam geçmiş gerekir (radar.yml `fetch-depth: 0`)."""
    s = subprocess.run(["git", "log", "--reverse", "--format=%H", f"origin/{dal}", "--", yol], capture_output=True, text=True)
    satirlar = s.stdout.split() if s.returncode == 0 else []
    return satirlar[0] if satirlar else None


def kayit_oku(dal: str, bas_ms: int, gun_sayisi: int = 1) -> list[dict] | None:
    """Canlı motor kaydı (`origin/<dal>:kayit/<YYYY-MM-DD>.jsonl`, UTC gün dosyaları): `bas_ms`'in gününden bir önceki günden (pencere başındaki sahayı kurmak için son `kapanis`)
    pencere sonu gününe kadar. Hiçbir dosya okunamazsa None (dal yok / sığ checkout); bozuk satır atlanır."""
    gun0 = datetime.fromtimestamp(bas_ms / 1000, UTC).date()
    olaylar: list[dict] = []
    bulundu = False
    for k in range(-1, gun_sayisi + 1):
        s = subprocess.run(["git", "show", f"origin/{dal}:kayit/{(gun0 + timedelta(days=k)).isoformat()}.jsonl"], capture_output=True, text=True, check=False)
        if s.returncode != 0:
            continue
        bulundu = True
        for satir in s.stdout.splitlines():
            try:
                o = json.loads(satir)
            except json.JSONDecodeError:
                continue
            if isinstance(o, dict):
                olaylar.append(o)
    return olaylar if bulundu else None


def onceki_kadro_oku(dal: str, tarih: str) -> dict | None:
    """`cikanlar` yedeği: önceki UTC gününün güncel `kadro.json`'u (o günün son tam kadrosu; ertesi günün ilk koşusundaki `--onceki-kadro` ile aynı dosya)."""
    onceki = (datetime.fromisoformat(tarih).date() - timedelta(days=1)).isoformat()
    return git_oku(dal, f"radar/{onceki}/kadro.json")


def gun_oku(dal: str, tarih: str, log: Callable[[str], None] = print) -> tuple[dict | None, dict | None, str | None]:
    """Ölçülen günün (havuz, kadro, kadro_kaynagi). Denetim R-1: motor (K‑39) günün İLK kadrosunu uygular; isabet de onu ölçmeli.
    Sıra: (1) `kadro_ilk.json` + `havuz_ilk.json` (radar_yayimla.sh günün ilk yayımında yazar) → "ilk"; (2) yoksa (eski günler) veri dalı geçmişinde `kadro.json`'a dokunan
    ilk commit'teki kadro + havuz → "ilk_git"; (3) o da yoksa güncel `kadro.json` + `havuz.json` → "son". Havuz her zaman kadroyla AYNI koşudan alınır (gruplar, hesap_usd, pencere başı)."""
    k = f"radar/{tarih}"
    kadro = git_oku(dal, f"{k}/kadro_ilk.json")
    if kadro:
        havuz = git_oku(dal, f"{k}/havuz_ilk.json")
        if havuz:
            return havuz, kadro, "ilk"
        log(f"UYARI: {k}/kadro_ilk.json var ama havuz_ilk.json yok; ilk kadro git geçmişinden kurulacak")
    sha = git_ilk_commit(dal, f"{k}/kadro.json")
    if sha:
        kadro, havuz = git_oku(dal, f"{k}/kadro.json", sha), git_oku(dal, f"{k}/havuz.json", sha)
        if kadro and havuz:
            return havuz, kadro, "ilk_git"
    return git_oku(dal, f"{k}/havuz.json"), git_oku(dal, f"{k}/kadro.json"), "son"


def calistir(client: Any, havuz: dict, kadro: dict, tarih: str, simdi_ms: int, rules: dict, kismi: bool = False, log: Callable[[str], None] = print,
             saat: Callable[[], float] = time.monotonic, kadro_kaynagi: str | None = None, kayitlar: list[dict] | None = None, onceki_kadro: dict | None = None,
             durum_dali: str | None = None) -> dict | None:
    """Tek havuz için isabet. Pencere = [havuz.kosu_ms, min(simdi, kosu_ms + 7 gün)]. Tam 7 gün dolmadıysa `kismi` yoksa None (ölçülmez); `kismi` ile ölçülür ve `pencere_tam: false` yazılır."""
    bas = int(havuz["kosu_ms"])
    tam_bit = bas + int(rules["isabet_pencere_gun"]) * GUN_MS
    pencere_tam = simdi_ms >= tam_bit
    if not pencere_tam and not kismi:
        log(f"isabet: {tarih} havuzu için 7 gün dolmadı (bitiş {datetime.fromtimestamp(tam_bit / 1000, UTC):%Y-%m-%d %H:%M} UTC); ölçülmedi")
        return None
    bit = min(simdi_ms, tam_bit)
    t0 = saat()
    ek = ek_gruplari_sec(havuz, kadro, tarih, kayitlar, onceki_kadro, int(rules["radar_kadro_ilk"]), durum_dali=durum_dali)
    secim = gruplari_sec(havuz, kadro, tarih, int(rules["isabet_elenen_ust"]), ek=ek)
    hata = None
    kutu: dict = {"eksik_ek": False}
    try:
        olcum, eksik = olc(client, havuz, kadro, secim, rules, bas, bit, log, saat, kutu)
    except HATALAR as h:                                                  # piyasa verisi okunamadı: tarama bozulmaz; eksik + hata dosyada
        olcum, eksik, hata = {}, True, type(h).__name__
        kutu["eksik_ek"] = True
        log(f"UYARI: isabet ölçümü yapılamadı ({hata})")
    return isabet_olustur(tarih, havuz, kadro, secim, olcum, bas, bit, pencere_tam, eksik, (saat() - t0) / 60.0, hata, kadro_kaynagi=kadro_kaynagi, eksik_ek=kutu["eksik_ek"])


def varsayilan_tarih(simdi_ms: int, rules: dict, dal: str, geri_gun: int = 3) -> str:
    """Ölçülecek havuz tarihi: penceresi (`kosu_ms` + 7 gün) DOLMUŞ ve `isabet.json` henüz yazılmamış en eski havuz (son `geri_gun` gün içinde); yoksa bugün − 7.
    Koşu geç başladıysa (kosu_ms 07:19) tam 7. gündeki sabah koşusunda pencere dolmamış olabilir; ölçüm ertesi gün yakalanır (Opus denetimi, 05.11)."""
    bugun = datetime.fromtimestamp(simdi_ms / 1000, UTC).date()
    pencere = int(rules["isabet_pencere_gun"])
    for k in range(geri_gun, -1, -1):
        t = (bugun - timedelta(days=pencere + k)).isoformat()
        havuz = git_oku(dal, f"radar/{t}/havuz.json")
        if havuz and not git_oku(dal, f"radar/{t}/isabet.json") and simdi_ms >= int(havuz["kosu_ms"]) + pencere * GUN_MS:
            return t
    return (bugun - timedelta(days=pencere)).isoformat()


def main(argv: list[str] | None = None) -> int:
    """Denetim R-7: isabet adımı radar.yml'de yayımdan ÖNCE koşar (yayım önceki günlerin isabet.json'larını taşır); burada beklenmeyen bir hata o günün kadrosunun yayımını
    ENGELLEMEMELİ. Her hata yakalanır, açık bir `ISABET HATASI` satırı (+ Actions `::error::` notu) basılır ve çıkış 0 döner. Hata sessizce yutulmaz."""
    try:
        return _main(argv)
    except Exception as hata:                                             # noqa: BLE001 — kadro yayımı engellenmez; hata günlükte ve iş özetinde görünür
        mesaj = f"ISABET HATASI (kadro yayımı engellenmedi): {type(hata).__name__}: {str(hata)[:300]}"
        print(mesaj, file=sys.stderr)
        print(f"::error title=ISABET HATASI::{mesaj}")
        return 0


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cikti", type=Path, default=Path("radar"))
    ap.add_argument("--veri-dali", default="radar", help="havuz/kadro okunan veri dalı (origin/<dal>): radar | radar-deneme")
    ap.add_argument("--tarih", default=None, help="ölçülecek havuz tarihi (YYYY-MM-DD); varsayılan bugün − isabet_pencere_gun")
    ap.add_argument("--kismi", action="store_true", help="DENEME: 7 gün dolmamış pencereyi de ölç (`pencere_tam: false`)")
    ap.add_argument("--durum-dali", default=DURUM_DALI, help="ek gruplar (ilk11_fiili, kor_kirpildi) için canlı motor kayıt dalı (origin/<dal>); okunamazsa bu iki grup boş")
    ap.add_argument("--ozet-md", type=Path, default=None)
    args = ap.parse_args(argv)
    rules = load_rules()
    simdi = int(time.time() * 1000)
    tarih = args.tarih or varsayilan_tarih(simdi, rules, args.veri_dali)
    havuz, kadro, kaynak = gun_oku(args.veri_dali, tarih)
    if not havuz or not kadro:
        print(f"isabet: origin/{args.veri_dali} dalında radar/{tarih}/ havuz+kadro yok (ilk ölçüm 2026-11-12); atlandı")
        return 0
    print(f"isabet: radar/{tarih}/ kadro kaynağı {kaynak} (kadro kosu_ms {kadro.get('kosu_ms')}, havuz kosu_ms {havuz.get('kosu_ms')})")
    kayitlar = kayit_oku(args.durum_dali, int(kadro.get("kosu_ms") or havuz["kosu_ms"]))                   # B9 bilgi: fiili saha; None → ek saha grupları boş
    onceki_kadro = None if isinstance(kadro.get("eski_uye_neden"), dict) else onceki_kadro_oku(args.veri_dali, tarih)
    print(f"isabet: ek gruplar — canlı kayıt origin/{args.durum_dali}: {'yok' if kayitlar is None else f'{len(kayitlar)} olay'}; "
          f"önceki kadro yedeği {'gerekmedi (eski_uye_neden)' if isinstance(kadro.get('eski_uye_neden'), dict) else ('var' if onceki_kadro else 'yok')}")
    try:
        sonuc = calistir(radar_tarama.radar_istemcisi(rules=rules), havuz, kadro, tarih, simdi, rules, args.kismi, kadro_kaynagi=kaynak, kayitlar=kayitlar, onceki_kadro=onceki_kadro,
                         durum_dali=args.durum_dali)
    except Exception as hata:                                             # noqa: BLE001 — tarama işi bozulmaz; hata dosyada ve günlükte görünür
        print(f"UYARI: isabet adımı hata verdi: {type(hata).__name__}: {str(hata)[:200]}", file=sys.stderr)
        secim = gruplari_sec(havuz, kadro, tarih, int(rules["isabet_elenen_ust"]))
        sonuc = isabet_olustur(tarih, havuz, kadro, secim, {}, int(havuz["kosu_ms"]), simdi, False, True, 0.0, type(hata).__name__, kadro_kaynagi=kaynak)
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
