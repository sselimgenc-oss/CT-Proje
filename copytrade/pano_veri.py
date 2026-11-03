"""Pano verisi (Faz 2, docs/FAZ2_PANO.md): `izleme/durum.json` + `ilk11/izleme_listesi.yaml` + `ilk11/<son>/snapshot.json` -> `pano.json`.

Panonun JS kodu HİÇBİR ŞEY hesaplamaz; tüm hesap burada yapılır (AGENTS kural 7). Biçim `pano/ornek_veri.json` ile aynıdır (üç takım: İlk 11, Yedek 11, PAF).
Motorda olmayan alan `null` yazılır, uydurulmaz (pano "—" gösterir). Sözleşme: docs/VERI_SOZLESMESI.md §10 (alan, birim, ölçek).

    python -m copytrade.pano_veri --durum izleme/durum.json --liste ilk11/izleme_listesi.yaml --ilk11 ilk11 --cikti pano.json
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

BAZ_USD = 1000.0                      # sanal kopya ölçeği
BAYAT_DK = 120                        # durum.json bundan eskiyse tazelik.bayat
KAPANAN_LIMIT = 20                    # pano "son kapananlar" satır sayısı
SERI_LIMIT = 30                       # seri nokta sayısı (gün)
TAKIMLAR = (("ilk11", "İlk 11"), ("yedek11", "Yedek 11"), ("paf", "PAF"))
NEDEN = {"trader": "trader_kapatti", "zarar_kes": "stop", "likidasyon": "tasfiye"}      # motor -> pano kodu; `kar_al` panoda karşılığı yok -> null


def _z(iso: Any) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sayi(deger: Any) -> float | None:
    if isinstance(deger, bool) or deger is None:
        return None
    try:
        sayi = float(deger)
    except (TypeError, ValueError):
        return None
    return sayi if sayi == sayi and sayi not in (float("inf"), float("-inf")) else None


def _yuvarla(deger: float | None, hane: int) -> float | None:
    return None if deger is None else round(deger, hane)


def _toplam(degerler: list[float | None]) -> float | None:
    """Biri bile eksikse toplam `None` (eksik alan sessizce sıfır sayılmaz)."""
    return None if not degerler or any(v is None for v in degerler) else sum(degerler)       # type: ignore[arg-type]


def _oran(pay: float | None, payda: float | None) -> float | None:
    return None if pay is None or payda is None or payda == 0 else pay / payda


def v3_gecerli(trader: dict) -> dict | None:
    v3 = trader.get("sanal_kopya_v3")
    if not isinstance(v3, dict) or v3.get("durum") == "hesaplanamadi" or v3.get("yer_tutucu"):
        return None
    return v3 if _sayi(v3.get("bakiye_usd")) is not None and _sayi(v3.get("baslangic_usd")) else None


def acik_islemler(trader: dict) -> list[dict]:
    """Açık işlemler: YALNIZ trader'ın pozisyon bilgisi (coin, yön, kaldıraç, trader, açılış). Açık KOPYA pozisyonu henüz motorda yok (v3 listelemiyor); trader pozisyonunu
    1.000 $'a oranlayıp $ / K/Z üretmek kullanıcıyı yanıltır (lider kararı 2026-11-03) → tüm $ alanları ve `kz_oran` `null`."""
    cikti = []
    for poz in trader.get("pozisyonlar") or []:
        cikti.append({"coin": poz.get("coin"), "yon": poz.get("yon"), "kaldirac": _sayi(poz.get("kaldirac")), "trader": trader.get("takma_ad"), "acilis": poz.get("acilis") or None,
                      "teminat_usd": None, "buyukluk_usd": None, "giris": None, "son": None, "kz_usd": None, "kz_oran": None, "likidasyona_uzaklik_oran": None})
    return cikti


def kapanan_islemler(trader: dict) -> list[dict]:
    """`sanal_kopya_v3.kapanan_islemler` (1.000 $ sabit tutar ölçeği); yalnız `gecerli` olanlar. `ana_para_usd` = sonuc_usd / getiri (getiri = sonuc / açılan toplam $)."""
    v3 = trader.get("sanal_kopya_v3")
    cikti = []
    for islem in (v3.get("kapanan_islemler") if isinstance(v3, dict) else None) or []:
        if islem.get("gecerli") is False:
            continue
        sonuc, getiri = _sayi(islem.get("sonuc_usd")), _sayi(islem.get("getiri"))
        cikti.append({"coin": islem.get("coin"), "yon": None, "kaldirac": None, "trader": trader.get("takma_ad"), "acilis": islem.get("acilis"), "kapanis": islem.get("kapanis"),
                      "neden": NEDEN.get(str(islem.get("neden"))), "ana_para_usd": _yuvarla(_oran(sonuc, getiri), 4), "kz_usd": _yuvarla(sonuc, 4), "kz_oran": _yuvarla(getiri, 6)})
    return cikti


def _egri_topla(egriler: list[list]) -> list[tuple[str, float]]:
    """Gün bazında toplam: yalnız TÜM üyelerde değeri olan günler (eksik gün için değer uydurulmaz)."""
    gun_sozluk = [{str(g): float(v) for g, v in e} for e in egriler]
    if not gun_sozluk:
        return []
    ortak = sorted(set.intersection(*(set(s) for s in gun_sozluk)))
    return [(g, sum(s[g] for s in gun_sozluk)) for g in ortak]


def _donem_orani(egri: list[tuple[str, float]], geri: int) -> float | None:
    """Son gün değeri / TAM `geri` gün önceki gün değeri − 1; o gün seride yoksa `None` (komşu günle yaklaşıklama yok)."""
    if not egri:
        return None
    hedef = (datetime.fromisoformat(egri[-1][0]) - timedelta(days=geri)).date().isoformat()
    onceki = next((v for g, v in egri if g == hedef), None)
    return _oran(egri[-1][1] - onceki, onceki) if onceki is not None else None


def takim_uret(takim_ad: str, uyeler: list[dict], durum_traderlar: dict[str, dict], kadro_toplam: int | None, ref: datetime) -> dict:
    veriler = [(u, durum_traderlar[u["adres"].lower()]) for u in uyeler if u["adres"].lower() in durum_traderlar]
    v3li = [(u, t, v3_gecerli(t)) for u, t in veriler]
    v3li = [(u, t, v) for u, t, v in v3li if v is not None]
    kadro_dolu = len(v3li)
    # kopya `t0`'da başlar: t0 > bugün olan üye henüz başlamamıştır (açık / kapanan / kasa toplamlarına GİRMEZ; trader pozisyonu kopya işlemi değildir)
    v3li = [(u, t, v) for u, t, v in v3li if not t.get("t0") or str(t["t0"])[:10] <= ref.date().isoformat()]
    var = bool(v3li)
    baslangic = sum(_sayi(v["baslangic_usd"]) for _, _, v in v3li) if var else None
    bakiye = sum(_sayi(v["bakiye_usd"]) for _, _, v in v3li) if var else None
    egri = _egri_topla([v.get("egri") or [] for _, _, v in v3li]) if var else []
    acik = [a for _, t, _ in v3li for a in acik_islemler(t)]
    acik.sort(key=lambda a: str(a["acilis"] or ""), reverse=True)
    kapanan_tum = [k for _, t, _ in v3li for k in kapanan_islemler(t)]
    kapanan_tum.sort(key=lambda k: str(k["kapanis"] or ""), reverse=True)
    bugun = ref.date().isoformat()
    son24 = [k for k in kapanan_tum if (z := _z(k["kapanis"])) and ref - timedelta(hours=24) < z <= ref]
    kazanc = [k["kz_usd"] for k in kapanan_tum if k["kz_usd"] is not None]
    getiriler = [k["kz_oran"] for k in kapanan_tum if k["kz_oran"] is not None]
    kazan_g = [g for k in kapanan_tum if (g := k["kz_oran"]) is not None and (k["kz_usd"] or 0) > 0]
    kayip_g = [g for k in kapanan_tum if (g := k["kz_oran"]) is not None and (k["kz_usd"] or 0) <= 0]
    teminat = _toplam([a["teminat_usd"] for a in acik]) if var else None          # `acik` $ alanları null olduğundan None
    kz_acik = _toplam([a["kz_usd"] for a in acik]) if var else None
    kayip_toplam = sum(-x for x in kazanc if x <= 0)
    degisim = None if bakiye is None else bakiye - baslangic
    # seriler
    bakiye_seri = egri[-SERI_LIMIT:]
    zirve, dusus, gunluk, onceki = None, [], [], None
    for g, v in egri:
        zirve = v if zirve is None else max(zirve, v)
        dusus.append((g, v / zirve - 1))
        gunluk.append((g, None if not onceki else v / onceki - 1))
        onceki = v
    metrik = {"bugun_oran": _yuvarla(None if len(egri) < 2 else _oran(egri[-1][1] - egri[-2][1], egri[-2][1]), 6),
              "hafta_oran": _yuvarla(_donem_orani(egri, 7), 6), "ay_oran": _yuvarla(_donem_orani(egri, 30), 6),
              "toplam_oran": _yuvarla(_oran(degisim, baslangic), 6),
              "maruziyet_oran": _yuvarla(_oran(teminat, bakiye), 6),
              "kazanma_orani": _yuvarla(_oran(sum(1 for x in kazanc if x > 0), len(kazanc)), 6),
              "kar_faktoru": _yuvarla(_oran(sum(x for x in kazanc if x > 0), kayip_toplam) if kayip_toplam > 0 else None, 6),
              "ort_kazanc_oran": _yuvarla(sum(kazan_g) / len(kazan_g) if kazan_g else None, 6),
              "ort_kayip_oran": _yuvarla(sum(kayip_g) / len(kayip_g) if kayip_g else None, 6),
              "beklenti_oran": _yuvarla(sum(getiriler) / len(getiriler) if getiriler else None, 6),
              "islem_sayisi": len(kapanan_tum) if var else None}
    ozet = {"nakit_usd": None, "acik_teminat_usd": _yuvarla(teminat, 4), "acik_islem": len(acik) if var else None, "acik_kz_usd": _yuvarla(kz_acik, 4),
            "bugun_acilan": (sum(1 for a in acik if str(a["acilis"] or "")[:10] == bugun) + sum(1 for k in kapanan_tum if str(k["acilis"] or "")[:10] == bugun)) if var else None,
            "bugun_kapanan": sum(1 for k in kapanan_tum if str(k["kapanis"] or "")[:10] == bugun) if var else None,
            "islem_basi_usd": None, "son24_islem": len(son24) if var else None,
            "son24_kazanma_orani": _yuvarla(_oran(sum(1 for k in son24 if (k["kz_usd"] or 0) > 0), len(son24)), 6),
            "kadro_dolu": kadro_dolu, "kadro_toplam": kadro_toplam}
    traderlar = []
    for u, t, v in v3li:
        k = kapanan_islemler(t)
        traderlar.append({"ad": t.get("takma_ad"), "islem": len(k), "kazanma_orani": _yuvarla(_oran(sum(1 for x in k if (x["kz_usd"] or 0) > 0), len(k)), 6),
                          "net_oran": _yuvarla(_sayi(v.get("getiri")), 6), "son_islem": max((str(x["kapanis"]) for x in k if x["kapanis"]), default=None)})
    return {"ad": takim_ad,
            "kasa": {"baslangic_usd": _yuvarla(baslangic, 4), "bakiye_usd": _yuvarla(bakiye, 4), "degisim_usd": _yuvarla(degisim, 4),
                     "degisim_oran": _yuvarla(_oran(degisim, baslangic), 6), "egri": [[f"{g}T00:00:00Z", round(v, 4)] for g, v in egri[-SERI_LIMIT:]],
                     "olcek_notu": f"{len(v3li)} × 1.000 $ sanal (trader başına)" if var else None},
            "ozet": ozet, "metrik": metrik,
            "seriler": {"kumulatif_kz": [[g, round(v - baslangic, 4)] for g, v in bakiye_seri], "bakiye": [[g, round(v, 4)] for g, v in bakiye_seri],
                        "dusus": [[g, round(d, 6)] for g, d in dusus[-SERI_LIMIT:]], "gunluk_kz": [[g, round(d, 6)] for g, d in gunluk[-SERI_LIMIT:] if d is not None]},
            "traderlar": traderlar, "acik": acik, "kapanan": kapanan_tum[:KAPANAN_LIMIT]}


def pano_uret(durum: dict, liste: dict, snapshot: dict | None, simdi: datetime | None = None) -> dict:
    """Saf fonksiyon: motor çıktıları -> `pano.json` sözlüğü. `uretildi` = kaynak `durum.json`'un üretim zamanı (pano 2 saatten eskiyse uyarır)."""
    simdi = simdi or datetime.now(UTC)
    kaynak = _z(durum.get("uretildi"))
    ref = kaynak or simdi
    tr = {str(t.get("adres", "")).lower(): t for t in durum.get("traderlar") or [] if t.get("adres")}
    uyeler: dict[str, list[dict]] = {k: [] for k, _ in TAKIMLAR}
    for satir in liste.get("traderlar") or []:
        if satir.get("takim") in uyeler and satir.get("adres"):
            uyeler[satir["takim"]].append(satir)
    toplam = {k: (sum(1 for s in snapshot.get("kadro") or [] if s.get("takim") == k) if snapshot else None) for k, _ in TAKIMLAR}
    yas = None if kaynak is None else (simdi - kaynak).total_seconds() / 60
    return {"surum": 1, "uretildi": _iso(kaynak) if kaynak else None, "dinleyici": None,
            "tazelik": {"kaynak_uretildi": _iso(kaynak) if kaynak else None, "pano_uretildi": _iso(simdi), "yas_dk": None if yas is None else round(yas, 1),
                        "esik_dk": BAYAT_DK, "bayat": True if yas is None else yas > BAYAT_DK},
            "olcek": {"kasa_ve_kapanan": "1.000 $ sanal kopya, sabit tutar (sanal_kopya_v3), trader başına; takım değeri üyelerin TOPLAMI",
                      "acik_islemler": "Açık kopya pozisyonu henüz motorda yok; yalnız trader'ın pozisyon bilgisi gösterilir ($ alanları yok)"},
            "takimlar": [takim_uret(ad, uyeler[k], tr, toplam[k], ref) for k, ad in TAKIMLAR]}


def son_snapshot(ilk11: Path) -> dict | None:
    adaylar = sorted(p for p in ilk11.glob("*/snapshot.json"))
    return json.loads(adaylar[-1].read_text(encoding="utf-8")) if adaylar else None


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--durum", type=Path, required=True)
    ap.add_argument("--liste", type=Path, required=True)
    ap.add_argument("--ilk11", type=Path, required=True, help="içinde <tarih>/snapshot.json olan klasör")
    ap.add_argument("--cikti", type=Path, default=Path("pano.json"))
    args = ap.parse_args(argv)
    veri = pano_uret(json.loads(args.durum.read_text(encoding="utf-8")), yaml.safe_load(args.liste.read_text(encoding="utf-8")) or {}, son_snapshot(args.ilk11))
    args.cikti.write_text(json.dumps(veri, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{args.cikti}: " + ", ".join(f"{t['ad']} {t['ozet']['kadro_dolu']}/{t['ozet']['kadro_toplam']}" for t in veri["takimlar"]) + f"; bayat={veri['tazelik']['bayat']}")


if __name__ == "__main__":
    main()
