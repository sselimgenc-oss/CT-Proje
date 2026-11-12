"""Duman testi: N adres, 2 tarih (T1, T11) + bugün; uçtan uca (çekme → ölçüm → rapor). Ayrı ölçüm klasörü (cache/deneme_olcum), çıktı DENEME_RAPOR.md."""
from __future__ import annotations

import json
import random
import time

import calistir as c
import hl
import rapor


def kos(n: int) -> int:
    ayar = c.ayar_oku(c.KOK)
    durum = c.Durum(c.KOK / "DENEME_DURUM.md", ayar)
    ist = hl.Istemci()
    durum.istemci = ist
    rows, meta = c.asama1(ist, durum)
    adresler, bilgi = c.evren_kur(rows)
    ilk = adresler[: bilgi["bugun_10k_ustu_islemli"]]
    r = random.Random(7)
    # aktif ve ≥ 50k hesaplardan örnek (rapor tabloları dolsun)
    aktif = {str(x["ethAddress"]).lower() for x in rows if c.pencere(x, "month", "vlm") > 5e5 and float(x.get("accountValue") or 0) >= 5e4}
    secim = r.sample(sorted(a for a in ilk if a in aktif), n)
    t0 = time.time()
    c.asama2(ist, secim, durum)
    tarihler = [ayar["tarihler"][0], ayar["tarihler"][10]]
    ornek = {"s50": secim, "s10": secim}
    c.asama3(ist, secim, ayar, durum)
    c.asama4(ist, secim, ayar, durum)
    t1 = time.time()
    ayar2 = {**ayar, "tarihler": tarihler}
    hatali = c.asama5(secim, ayar2, ornek, durum, tarihler, uc="deneme_olcum")
    t2 = time.time()
    rapor.uret(c.KOK, ayar, ornek, secim, {"deneme_adres": n, "tarih": [rapor.tarih(t) for t in tarihler]}, tur="tur1", uc="deneme_olcum", tarihler=tarihler,
               cikti_ad="DENEME_RAPOR.md")
    print(json.dumps({"adres": n, "hatali_olcum": hatali, "cekme_sn": round(t1 - t0), "olcum_sn": round(t2 - t1), "istek": ist.stats, "agirlik": ist.kova.toplam}, ensure_ascii=False))
    return 0
