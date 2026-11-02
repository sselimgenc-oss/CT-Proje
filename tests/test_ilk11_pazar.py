"""İlk 11 Pazar işi (copytrade/ilk11_pazar.py): şartname §6.6 altın örnekleri 13, 15, 16, 18, 19 + uçtan uca (sentetik kapı + gerçek git deposu)."""
from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest
import yaml

from copytrade import ilk11, ilk11_pazar as pz
from copytrade.ilk11_veri import snapshot_json, snapshot_olustur
from copytrade.izleme_motoru import load_list
from copytrade.kapi import HESAP_SURUMU
from copytrade.kurallar import RULES as KURALLAR_YOLU, load_rules

RULES = load_rules()
PAZAR1 = datetime(2026, 11, 1, 10, 7, tzinfo=UTC)          # Pazar 13:07 TSİ
PAZAR2 = datetime(2026, 11, 8, 10, 7, tzinfo=UTC)
AS_OF1 = pz.pazar_as_of(PAZAR1)
AS_OF2 = pz.pazar_as_of(PAZAR2)


def adres(i: int) -> str:
    return "0x" + f"{i:040x}"


def kapi_satiri(i: int, katman="izleme_adayi", **over) -> dict:
    """i. aday: her alan i ile tek yönlü değişir (sabit sütun yok)."""
    satir = {"address": adres(i), "katman": katman, "satir_kaynagi": "bu_kosu", "evren_disi": False, "hata": None, "tarz": "intraday" if i % 2 else "swing",
             "kapi_gecikme_dk": 30 if i % 2 else 120, "gecikme_30dk_net": 0.01 * i, "gecikme_120dk_net": 0.012 * i, "now_ms": int(AS_OF1.timestamp() * 1000) - 86_400_000,
             "ilk11_ay_roi": 0.005 * i, "ilk11_hafta_roi": 0.001 * i, "hesap_degeri_bugun": 6000.0 + 4000.0 * i, "ilk11_dusus_30g": 0.5 - 0.004 * i,
             "kazanma_orani": 0.3 + 0.005 * i, "gunluk_islem_sikligi": 0.5 + 0.03 * i, "median_holding_hours": 1.0 + 0.2 * i, "median_leverage": 0.1 + 0.03 * i,
             "ilk11_tutarli_30g": 0.2 + 0.006 * i}
    return {**satir, **over}


def kapi_yaz(kok: Path, tarih: str, satirlar: list[dict], **durum) -> Path:
    klasor = kok / "copytrade/kapi" / tarih
    klasor.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(satirlar).to_csv(klasor / "sonuc.csv", index=False)
    (klasor / "durum.json").write_text(json.dumps({"durum": "tamam", "kapsam": 1.0, "hesap": HESAP_SURUMU, **durum}))
    return klasor


@pytest.fixture
def dal(tmp_path):
    kok = tmp_path / "kapi-dali"
    kapi_yaz(kok, "2026-10-31", [kapi_satiri(i) for i in range(1, 61)])
    return kok


# ------------------------------------------------------------------------------------------------ yardımcılar
def test_pazar_as_of_takvimden_cron_gecikmesi_sonucu_degistirmez():
    assert AS_OF1.isoformat() == "2026-11-01T13:00:00+03:00" and AS_OF1.weekday() == 6
    for gecikme in ("2026-11-01T10:00:00", "2026-11-01T10:07:00", "2026-11-01T18:07:00", "2026-11-02T09:00:00", "2026-11-07T20:00:00"):
        assert pz.pazar_as_of(datetime.fromisoformat(gecikme).replace(tzinfo=UTC)) == AS_OF1
    assert pz.pazar_as_of(datetime(2026, 11, 1, 9, 59, tzinfo=UTC)).isoformat() == "2026-10-25T13:00:00+03:00"      # 12:59 TSİ: henüz önceki Pazar
    with pytest.raises(ValueError):
        pz.pazar_as_of(datetime(2026, 11, 1, 10, 0))


def test_golden_13_terfi_kapisi_son_6_gecerli_sonuc_usd():
    kapi = ilk11.yedekten_terfi_kapisi([{"sonuc": x, "gecerli": True} for x in (3, -1, 2, -1, 1, -1)])
    assert (kapi["toplam"], kapi["kazanma_orani"], kapi["en_iyi_haric_toplam"], kapi["gecti"]) == (3, 0.5, 0, False)
    kapi = ilk11.yedekten_terfi_kapisi([{"sonuc": x, "gecerli": True} for x in (3, -1, 2, -1, 2, -1)])
    assert (kapi["toplam"], kapi["en_iyi_haric_toplam"], kapi["gecti"]) == (4, 1, True)


def test_terfi_kapisi_girdisi_izleme_kapanan_islemlerinden_takim_hafta_sonrasi_gecerli_ve_as_of_oncesi():
    def islem(acilis, kapanis, sonuc, gecerli=True):
        return {"coin": "BTC", "acilis": acilis, "kapanis": kapanis, "sonuc_usd": sonuc, "getiri": sonuc / 20, "neden": "trader", "gecerli": gecerli}
    trader = {"adres": adres(1), "gecerli": True, "veri_zamani": "2026-11-08T09:23:00Z", "son_perp_dolum": "2026-11-07T00:00:00Z",
              "ilk11_form_ham": {"alanlar": dict.fromkeys(ilk11.KALDIRAC_ALANLARI, 1.0), "alan_kaynagi": {}, "dolu_alan": 10},
              "sanal_kopya_v3": {"kapanan_islemler": [
                  islem("2026-10-30T00:00:00Z", "2026-11-02T00:00:00Z", 9.0),                  # takim_hafta (2026-11-01 10:00Z) ÖNCESİ açıldı: sayılmaz
                  islem("2026-11-02T00:00:00Z", "2026-11-03T00:00:00Z", 1.0),
                  islem("2026-11-02T00:00:00Z", "2026-11-04T00:00:00Z", 5.0, gecerli=False),   # geçersiz: sayılmaz
                  islem("2026-11-05T00:00:00Z", "2026-11-06T00:00:00Z", -2.0),
                  islem("2026-11-07T00:00:00Z", "2026-11-09T00:00:00Z", 7.0)]}}               # as_of (11-08) sonrası kapandı: sayılmaz
    satir = pz.form_satiri({"id": adres(1), "grup": "yedek11", "takim_hafta": "2026-11-01"}, trader, AS_OF2.astimezone(UTC), None, 0.4, RULES)
    assert [x["sonuc"] for x in satir["paper_sonuclari"]] == [1.0, -2.0]
    assert satir["gecerli_gozlem_suresi"] is None and satir["kapi_puani"] == 0.4              # sayaç başlangıcı takim_hafta ile eşleşmiyor -> bilinmiyor


# ------------------------------------------------------------------------------------------------ 15 uygunluk
def test_golden_15_kapi_klasoru_8_gun_eski_reddedilir_7_gun_kabul(tmp_path):
    kok = tmp_path / "d"
    kapi_yaz(kok, "2026-10-24", [kapi_satiri(1)])                                            # as_of 2026-11-01 − 8 gün
    k = pz.kapi_sec(kok, AS_OF1, RULES)
    assert k["gun_farki"] == 8 and k["eski"] is True
    with pytest.raises(pz.GirdiHatasi, match="kapı verisi eski"):
        pz._ilk_secim_akisi(k, AS_OF1, "2026-11-01", kok / "ilk11/2026-11-01", kok, kok, pz._akis_oku(kok), PAZAR1, None, False, RULES, KURALLAR_YOLU)
    kapi_yaz(kok, "2026-10-25", [kapi_satiri(1)])                                            # 7 gün: sınırda kabul
    k = pz.kapi_sec(kok, AS_OF1, RULES)
    assert k["tarih"] == "2026-10-25" and k["gun_farki"] == 7 and k["eski"] is False


def test_kapi_sec_eksik_koşu_kapsam_ve_hesap_surumu_reddeder_en_yeni_uygunu_alir(tmp_path):
    kok = tmp_path / "d"
    kapi_yaz(kok, "2026-10-30", [kapi_satiri(1)])
    kapi_yaz(kok, "2026-10-31", [kapi_satiri(1)], durum="eksik")
    assert pz.kapi_sec(kok, AS_OF1, RULES)["tarih"] == "2026-10-30"                           # eksik koşu atlanır
    kapi_yaz(kok, "2026-10-31", [kapi_satiri(1)], kapsam=0.97)
    assert pz.kapi_sec(kok, AS_OF1, RULES)["tarih"] == "2026-10-30"                           # kapsam < 0,98
    kapi_yaz(kok, "2026-10-31", [kapi_satiri(1)], hesap="eski-surum")
    assert pz.kapi_sec(kok, AS_OF1, RULES)["tarih"] == "2026-10-30"
    kapi_yaz(kok, "2026-11-05", [kapi_satiri(1)])                                            # as_of SONRASI klasör kullanılmaz
    assert pz.kapi_sec(kok, AS_OF1, RULES)["tarih"] == "2026-10-30"
    with pytest.raises(pz.GirdiHatasi, match="kapı klasörü yok"):
        pz.kapi_sec(tmp_path / "bos", AS_OF1, RULES)


def test_golden_15_satir_uygunlugu_neden_kodlari():
    ok = kapi_satiri(1)
    assert pz.satir_uygunlugu(ok, AS_OF1, RULES) == (True, None)
    assert pz.satir_uygunlugu({**ok, "satir_kaynagi": "onceki_dosya_ayni_hesap"}, AS_OF1, RULES) == (False, "eski_satir")
    assert pz.satir_uygunlugu({**ok, "katman": "yok"}, AS_OF1, RULES) == (False, "katman_yok")
    assert pz.satir_uygunlugu({**ok, "katman": float("nan")}, AS_OF1, RULES) == (False, "katman_yok")
    assert pz.satir_uygunlugu({**ok, "evren_disi": True}, AS_OF1, RULES) == (False, "evren_disi")
    assert pz.satir_uygunlugu({**ok, "evren_disi": "True"}, AS_OF1, RULES) == (False, "evren_disi")           # CSV'den metin
    assert pz.satir_uygunlugu({**ok, "hata": "KeyError: x"}, AS_OF1, RULES) == (False, "hata")
    assert pz.satir_uygunlugu({**ok, "hata": float("nan")}, AS_OF1, RULES) == (True, None)
    # satir_kaynagi sütunu yoksa now_ms ≥ as_of − 7 gün
    eski = {k: v for k, v in ok.items() if k != "satir_kaynagi"}
    assert pz.satir_uygunlugu(eski, AS_OF1, RULES) == (True, None)
    assert pz.satir_uygunlugu({**eski, "now_ms": int(AS_OF1.timestamp() * 1000) - 8 * 86_400_000}, AS_OF1, RULES) == (False, "eski_satir")
    assert pz.satir_uygunlugu({k: v for k, v in eski.items() if k != "now_ms"}, AS_OF1, RULES) == (False, "eski_satir")
    assert pz.satir_uygunlugu({**ok, "katman": "kopyalanabilir"}, AS_OF1, RULES) == (True, None)


def test_adaylari_hazirla_yalniz_katman_adaylari_ve_sayac():
    tablo = pd.DataFrame([kapi_satiri(1), kapi_satiri(2, katman="yok"), kapi_satiri(3, satir_kaynagi="onceki_dosya_ayni_hesap"), kapi_satiri(4, katman=None)])
    adaylar, sayac = pz.adaylari_hazirla(tablo, AS_OF1, RULES)
    assert [(a["id"], a["uygun"], a["uygunluk_nedeni"]) for a in adaylar] == [(adres(1), True, None), (adres(3), False, "eski_satir")]
    assert sayac == {"toplam_satir": 4, "katman_yok": 2}
    with pytest.raises(pz.GirdiHatasi, match="yinelenen"):
        pz.adaylari_hazirla(pd.DataFrame([kapi_satiri(1), kapi_satiri(1)]), AS_OF1, RULES)


# ------------------------------------------------------------------------------------------------ 16 az aday, 19 determinizm
def ilk(dal_, adet, deneme=False, kapi_extra=None):
    kok = dal_
    tablo = pd.DataFrame([kapi_satiri(i) for i in range(1, adet + 1)])
    adaylar, _ = pz.adaylari_hazirla(tablo, AS_OF1, RULES)
    kapi = {"tarih": "2026-10-31", "klasor": kapi_yaz(kok, "2026-10-31", [kapi_satiri(i) for i in range(1, adet + 1)])}
    return adaylar, pz.ilk_secim(adaylar, AS_OF1, pz.kaynak_surumu_kapi(kapi, KURALLAR_YOLU), RULES, deneme)


def test_golden_16_49_uygun_kapasite_bos_1_uyari_paf_27_ve_10_uygun_yayin_yok(dal):
    adaylar, sonuc = ilk(dal, 49)
    snap = sonuc["snapshot"]
    assert snap is not None and snap["secim_adedi"] == 49 and snap["uyari"] and 50 - snap["secim_adedi"] == 1
    assert [sum(r["takim"] == g for r in snap["kadro"]) for g in ("ilk11", "yedek11", "paf")] == [11, 11, 27]
    _, sonuc = ilk(dal, 11)
    assert sonuc["snapshot"] is not None and sum(r["takim"] == "paf" for r in sonuc["snapshot"]["kadro"]) == 0          # 11 uygun: İlk 11 dolar, uyarılı yayın
    _, sonuc = ilk(dal, 10)
    assert sonuc["snapshot"] is None and any("10 < 11" in p for p in sonuc["problemler"])
    _, deneme = ilk(dal, 10, deneme=True)
    assert deneme["snapshot"] is not None                                                                                # --deneme: yayın eşiği uygulanmaz


def test_golden_19_snapshot_deterministik_tek_alan_degisimi_farkli_kimlik_ve_tahrif_reddi(dal):
    _, bir = ilk(dal, 60)
    _, iki = ilk(dal, 60)
    assert bir["snapshot"]["snapshot_id"] == iki["snapshot"]["snapshot_id"] and snapshot_json(bir["snapshot"]) == snapshot_json(iki["snapshot"])
    tablo = [kapi_satiri(i) for i in range(1, 61)]
    tablo[7] = kapi_satiri(8, ilk11_ay_roi=0.1234)                                           # tek alan
    kapi_yaz(dal, "2026-10-31", tablo)
    adaylar, _ = pz.adaylari_hazirla(pd.DataFrame(tablo), AS_OF1, RULES)
    kapi = {"tarih": "2026-10-31", "klasor": dal / "copytrade/kapi/2026-10-31"}
    degisik = pz.ilk_secim(adaylar, AS_OF1, pz.kaynak_surumu_kapi(kapi, KURALLAR_YOLU), RULES, False)["snapshot"]
    assert degisik["snapshot_id"] != bir["snapshot"]["snapshot_id"]
    kurcalanmis = json.loads(snapshot_json(bir["snapshot"]))
    kurcalanmis["adaylar"][0]["alanlar"]["ay_roi"] = 99.0
    with pytest.raises(ValueError, match="snapshot_id ile uyuşmuyor"):
        snapshot_json(kurcalanmis)


def test_ilk_secim_akil_sagligi_ve_doluluk_kapisi_yayini_engeller(dal):
    satirlar = [kapi_satiri(i, ilk11_ay_roi=(1805.0 if i <= 3 else 0.005 * i)) for i in range(1, 61)]     # 3/60 = %5: sınırda geçer
    kapi_yaz(dal, "2026-10-31", satirlar)
    adaylar, _ = pz.adaylari_hazirla(pd.DataFrame(satirlar), AS_OF1, RULES)
    kapi = {"tarih": "2026-10-31", "klasor": dal / "copytrade/kapi/2026-10-31"}
    kaynak = pz.kaynak_surumu_kapi(kapi, KURALLAR_YOLU)
    assert pz.ilk_secim(adaylar, AS_OF1, kaynak, RULES, False)["snapshot"] is not None
    satirlar = [kapi_satiri(i, ilk11_ay_roi=(1805.0 if i <= 4 else 0.005 * i)) for i in range(1, 61)]     # 4/60 > %5
    adaylar, _ = pz.adaylari_hazirla(pd.DataFrame(satirlar), AS_OF1, RULES)
    sonuc = pz.ilk_secim(adaylar, AS_OF1, kaynak, RULES, False)
    assert sonuc["snapshot"] is None and any(p.startswith("ay_roi:") for p in sonuc["problemler"])
    satirlar = [kapi_satiri(i, kazanma_orani=(None if i <= 7 else 0.5 + 0.001 * i)) for i in range(1, 61)]   # 7/60 eksik: doluluk %88,3 < %90
    adaylar, _ = pz.adaylari_hazirla(pd.DataFrame(satirlar), AS_OF1, RULES)
    sonuc = pz.ilk_secim(adaylar, AS_OF1, kaynak, RULES, False)
    assert sonuc["snapshot"] is None and any(p.startswith("kazanma:") and "doluluk" in p for p in sonuc["problemler"])


# ------------------------------------------------------------------------------------------------ uçtan uca ilk seçim
def test_ilk_secim_uctan_uca_dosyalar_akis_liste_ve_idempotans(dal, tmp_path):
    cikti = tmp_path / "cikti"
    taban = tmp_path / "main_liste.yaml"
    taban.write_text(yaml.safe_dump({"traderlar": [
        {"id": "R1", "adres": adres(3), "takma_ad": "r001", "durum": "izlemede", "t0": "2026-10-28", "kol": "oda", "kollar": ["oda", "taban"]},
        {"id": "R2", "adres": adres(900), "takma_ad": "r002", "durum": "izlemede", "t0": "2026-10-28", "kol": "kontrol", "kollar": ["kontrol"]},
        {"id": "P1", "adres": adres(901), "takma_ad": "p001", "durum": "izlemede", "t0": "2026-10-28", "kol": "taban", "kollar": ["taban"]}]}))
    assert pz.calistir(dal, cikti, PAZAR1, taban_liste=taban) == 0
    hedef = cikti / "ilk11/2026-11-01"
    assert {p.name for p in hedef.iterdir()} == {"snapshot.json", "alanlar.csv", "plan.json", "akis.json", "RAPOR.md"}
    snap = json.loads((hedef / "snapshot.json").read_text())
    assert snapshot_json(snap) and snap["sema"] == "ilk11-pazar-v1" and snap["as_of"] == "2026-11-01T13:00:00+03:00"
    assert [sum(r["takim"] == g for r in snap["kadro"]) for g in ("ilk11", "yedek11", "paf")] == [11, 11, 28]
    assert set(snap["kaynak_surumu"]) == {"kapi", "kapi_sonuc_sha256", "kapi_durum_sha256", "ilk11_alanlar", "kurallar"}
    assert snap["kaynak_surumu"]["kurallar"] == pz.sha256_dosya(KURALLAR_YOLU)
    assert snap["kaynak_surumu"]["kapi_sonuc_sha256"] == pz.sha256_dosya(dal / "copytrade/kapi/2026-10-31/sonuc.csv")
    csv = pd.read_csv(hedef / "alanlar.csv")
    assert len(csv) == 60 and csv["puan"].notna().all() and set(ilk11.KALDIRAC_ALANLARI) <= set(csv.columns)
    assert (csv["puan"].max() < 100) and (csv["puan"].min() > 0) and csv["ay_roi"].nunique() > 1
    # en yüksek puanlı aday kadro ilk sırasında; kadro puanı CSV ile aynı
    ilk_kadro = snap["kadro"][0]
    assert csv.set_index("adres").loc[ilk_kadro["id"], "puan"] == pytest.approx(ilk_kadro["puan"])
    akis = json.loads((hedef / "akis.json").read_text())
    assert akis == {"deneme_sayisi": 1, "snapshot_id": snap["snapshot_id"], "son_basarisiz_at": None, "basarili": True}
    assert json.loads((cikti / "son.json").read_text())["ilk11"] == {"tarih": "2026-11-01", "snapshot_id": snap["snapshot_id"], "sema": "ilk11-pazar-v1"}
    rapor = (hedef / "RAPOR.md").read_text()
    assert "YAYIMLANDI" in rapor and "ilk11" in rapor.lower() and "| golge |" in rapor and "uygun evren **60**" in rapor
    # izleme listesi: kadro 50 + referans kolları; eski pilot kolu (taban) yok; aynı adres tek satır
    liste = load_list(cikti / "ilk11/izleme_listesi.yaml")
    by = {r["adres"]: r for r in liste}
    kadro_adresleri = {r["id"] for r in snap["kadro"]}
    beklenen_referans = {adres(900)} | ({adres(3)} - kadro_adresleri)          # referans satırı kadroda değilse ayrıca kalır, kadrodaysa tek satır
    assert len(liste) == 50 + len(beklenen_referans) and adres(900) in by and adres(901) not in by and "takim" not in by[adres(900)]
    assert (by[adres(900)]["id"], by[adres(900)]["t0"], by[adres(900)]["kol"], by[adres(900)]["kollar"]) == ("R2", "2026-10-28", "referans_kontrol", ["referans_kontrol"])
    assert {r["adres"] for r in liste if "takim" in r} == kadro_adresleri
    if adres(3) in kadro_adresleri:
        assert by[adres(3)]["id"] == "R1" and by[adres(3)]["t0"] == "2026-10-28" and by[adres(3)]["kollar"] == ["referans_oda"]     # tek satır, id / t0 korunur, oda -> referans_oda
    else:
        assert (by[adres(3)]["kol"], by[adres(3)]["kollar"]) == ("referans_oda", ["referans_oda"])
    yeni = next(r for r in liste if r["adres"] not in {adres(3), adres(900)})
    assert yeni["t0"] == "2026-11-01" and yeni["snapshot_id"] == snap["snapshot_id"] and yeni["takim_hafta"] == "2026-11-01" and yeni["id"].startswith("K")
    # idempotans: aynı Pazar ikinci koşu hiçbir şey değiştirmez (tamamla)
    once = {p.name: p.read_bytes() for p in hedef.iterdir()}
    assert pz.calistir(dal, cikti, PAZAR1, taban_liste=taban) == 0 and pz.calistir(cikti, cikti, PAZAR1 + pd.Timedelta(hours=2).to_pytimedelta(), taban_liste=taban) == 0
    assert {p.name: p.read_bytes() for p in hedef.iterdir()} == once


def test_ilk_secim_kapi_eski_ise_kirmizi_hicbir_snapshot_yazilmaz(tmp_path):
    kok = tmp_path / "d"
    kapi_yaz(kok, "2026-10-20", [kapi_satiri(i) for i in range(1, 61)])
    assert pz.calistir(kok, kok, PAZAR1) == 1
    hedef = kok / "ilk11/2026-11-01"
    assert [p.name for p in hedef.iterdir()] == ["RAPOR.md"] and "kapı verisi eski" in (hedef / "RAPOR.md").read_text()
    assert not (kok / "son.json").exists() and not (kok / "ilk11/izleme_listesi.yaml").exists()


def test_ilk_secim_kalite_hatasi_rapor_ve_csv_yazar_snapshot_yazmaz(tmp_path):
    kok = tmp_path / "d"
    kapi_yaz(kok, "2026-10-31", [kapi_satiri(i, ilk11_ay_roi=1805.0) for i in range(1, 61)])
    assert pz.calistir(kok, kok, PAZAR1) == 1
    hedef = kok / "ilk11/2026-11-01"
    assert {p.name for p in hedef.iterdir()} == {"RAPOR.md", "alanlar.csv"} and "YAYIMLANMADI" in (hedef / "RAPOR.md").read_text()
    assert "akil_sagligi_ihlali:1805" in (hedef / "alanlar.csv").read_text()


def test_deneme_yalniz_cikti_yazar_iki_kosuda_ayni_snapshot_id(dal, tmp_path):
    kok = tmp_path / "d"
    kapi_yaz(kok, "2026-10-31", [kapi_satiri(i) for i in range(1, 6)])                         # 5 kişilik evren (yayın eşiği uygulanmaz)
    kimlikler = []
    for n in (1, 2):
        cikti = tmp_path / f"c{n}"
        assert pz.calistir(kok, cikti, PAZAR1, deneme=True) == 0
        assert {p.name for p in (cikti / "ilk11/2026-11-01").iterdir()} == {"snapshot.json", "alanlar.csv", "plan.json", "RAPOR.md"}
        assert not (cikti / "son.json").exists() and not (cikti / "ilk11/izleme_listesi.yaml").exists()
        kimlikler.append(json.loads((cikti / "ilk11/2026-11-01/snapshot.json").read_text())["snapshot_id"])
    assert kimlikler[0] == kimlikler[1] and "DENEME" in (tmp_path / "c1/ilk11/2026-11-01/RAPOR.md").read_text()


def test_gecici_kadro_onceki_kadro_sayilmaz_ilk_gercek_kosu_ilk_secimdir(dal, tmp_path):
    cikti = dal                                                                                  # önceki kadro aynı dalda
    gecici = dal / "ilk11/2026-10-25"
    gecici.mkdir(parents=True)
    govde = {"sema": pz.GECICI_SEMA, "as_of": "2026-10-25T13:00:00+03:00", "kadro": [{"id": adres(1), "takim": "ilk11", "puan": 50.0}]}
    import hashlib
    kimlik = "1d92dd25" + hashlib.sha256(json.dumps(govde, sort_keys=True).encode()).hexdigest()[8:]
    (gecici / "snapshot.json").write_text(json.dumps({"snapshot_id": kimlik, **govde}))
    (gecici / "akis.json").write_text(json.dumps({"deneme_sayisi": 1, "snapshot_id": kimlik, "son_basarisiz_at": None, "basarili": True}))
    assert pz.onceki_snapshot_bul(dal / "ilk11", AS_OF1) is None                                 # geçici sema / kimlik atlanır
    assert pz.calistir(dal, cikti, PAZAR1) == 0
    assert json.loads((dal / "ilk11/2026-11-01/snapshot.json").read_text())["sema"] == "ilk11-pazar-v1"        # form değil, ilk seçim


# ------------------------------------------------------------------------------------------------ form
GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=GIT_ENV).stdout.strip()


def izleme_deposu(tmp_path: Path, surumler: list[tuple[str, dict]]) -> Path:
    repo = tmp_path / "izleme-dali"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "izleme").mkdir()
    for etiket, durum in surumler:
        (repo / "izleme/durum.json").write_text(json.dumps(durum))
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", etiket)
    return repo


def trader_durum(kimlik: str, adr: str, sira: int, uretildi: str, **over) -> dict:
    """sira büyüdükçe form iyileşir. Dönüşümler (`ilk11.hazirla_kaldirac_alanlari`) sıra korunacak biçimde seçildi: siklik ≤ 1 (puan = x), tutma 2–4,5 dk
    (puan = (dk − 2)/3), kaldıraç ≤ 1,6x (puan x ile artar), hesap < 505.000 $; dusus düşük iyi. Böylece form yüzdeliği tam sıradır."""
    alanlar = {"golge": 0.01 * sira, "ay_roi": 0.005 * sira, "hafta_roi": 0.001 * sira, "hesap": 6000.0 + 4000.0 * sira, "dusus": 0.5 - 0.004 * sira,
               "kazanma": 0.3 + 0.005 * sira, "siklik": 0.016 * sira, "tutma": 2.0 + 0.05 * sira, "kaldirac": 0.1 + 0.03 * sira, "tutarli": 0.2 + 0.006 * sira}
    t = {"id": kimlik, "adres": adr, "gecerli": True, "veri_zamani": uretildi, "son_perp_dolum": "2026-11-07T08:00:00Z",
         "ilk11_form_ham": {"alanlar": alanlar, "alan_kaynagi": {k: k for k in alanlar}, "pencere_bitis": uretildi, "dolu_alan": 10},
         "ilk11_gecerli_saat": {"baslangic": "2026-11-01", "saat": 168, "son_saat": uretildi}, "sanal_kopya_v3": {"kapanan_islemler": []}}
    return {**t, **over}


def durum_olustur(snap1: dict, uretildi: str) -> dict:
    """Kadro sıralaması (snapshot.kadro) boyunca form AZALIR: en iyi İlk 11 üyesi en yüksek formu alır."""
    n = len(snap1["kadro"])
    return {"surum": 1, "uretildi": uretildi, "kaynak": "hyperliquid",
            "traderlar": [trader_durum(f"T{i}", r["id"], n - i, uretildi) for i, r in enumerate(snap1["kadro"])]}


def ilk_calistir(dal, cikti=None):
    cikti = cikti or dal
    assert pz.calistir(dal, cikti, PAZAR1) == 0
    return json.loads((cikti / "ilk11/2026-11-01/snapshot.json").read_text())


def test_izleme_durum_sec_git_gecmisinden_as_of_oncesi_en_son_surum(tmp_path):
    sürümler = [("a", {"uretildi": "2026-11-08T08:23:00Z", "traderlar": [], "n": 1}), ("b", {"uretildi": "2026-11-08T09:23:00Z", "traderlar": [], "n": 2}),
                ("c", {"uretildi": "2026-11-08T11:23:00Z", "traderlar": [], "n": 3})]          # c as_of (10:00Z) SONRASI
    repo = izleme_deposu(tmp_path, sürümler)
    durum, sha = pz.izleme_durum_sec(repo, AS_OF2.astimezone(UTC))
    assert durum["n"] == 2 and sha == git(repo, "rev-parse", "HEAD~1")
    assert pz.izleme_durum_sec(repo, AS_OF2.astimezone(UTC))[1] == sha                           # tekrar: aynı girdi
    with pytest.raises(pz.GirdiHatasi, match="sürümü yok"):
        pz.izleme_durum_sec(repo, datetime(2026, 11, 8, 7, 0, tzinfo=UTC))
    with pytest.raises(pz.GirdiHatasi):
        pz.izleme_durum_sec(tmp_path, AS_OF2.astimezone(UTC))                                    # git deposu değil


def test_form_uctan_uca_hareketler_bosluk_doldurma_liste_ve_yeniden_uretim(dal, tmp_path):
    snap1 = ilk_calistir(dal)
    kapi_yaz(dal, "2026-11-07", [kapi_satiri(i) for i in range(1, 61)])                          # taze kapı: boş PAF doldurma mümkün
    repo = izleme_deposu(tmp_path, [("s1", durum_olustur(snap1, "2026-11-08T09:23:00Z")),
                                    ("s2", {**durum_olustur(snap1, "2026-11-08T11:23:00Z")})])         # s2 as_of sonrası: seçilmez
    cikti = tmp_path / "cikti2"
    assert pz.calistir(dal, cikti, PAZAR2, izleme_dali=repo) == 0
    hedef = cikti / "ilk11/2026-11-08"
    snap = json.loads((hedef / "snapshot.json").read_text())
    assert snapshot_json(snap) and snap["sema"] == "ilk11-form-v1" and snap["as_of"] == "2026-11-08T13:00:00+03:00"
    assert snap["kaynak_surumu"]["izleme"].startswith(git(repo, "rev-parse", "HEAD~1")) and snap["kaynak_surumu"]["onceki_snapshot"] == snap1["snapshot_id"]
    # Elle hesap: 50 üyede form tam sıra; yüzdelik p = 100·(j + 0,5)/50 (j = alttan sıra, 0..49). p < 40 ⇔ j ≤ 19 -> 20 üye, hepsi kadronun en
    # düşük formlu SON 20'si = PAF (PAF 28 üye: sıra 22..49); PAF'tan 20 çıkış. Boş PAF: 28 − 20 = 8 dolu -> 20 yer, ama kadro dışı uygun yalnız 60 − 50 = 10 aday.
    plan = json.loads((hedef / "plan.json").read_text())
    cikanlar = [m for m in plan["degisiklik_plani"] if m["sonra"] == "kadrodisi"]
    assert len(cikanlar) == 20 and all(m["once"] == "paf" and m["neden"] == "geçerli Pazar formu <40" for m in cikanlar)
    assert len(plan["boslugu_dolduranlar"]) == 10 and all(g["grup"] == "paf" for g in plan["boslugu_dolduranlar"])
    sayim = {g: sum(r["grup"] == g for r in plan["kadro_sonrasi"]) for g in ("ilk11", "yedek11", "paf")}
    assert sayim == {"ilk11": 11, "yedek11": 11, "paf": 18}
    uyeler1 = {r["id"] for r in snap1["kadro"]}
    assert {g["id"] for g in plan["boslugu_dolduranlar"]}.isdisjoint(uyeler1)
    assert all(r["takim_hafta"] == "2026-11-08" for r in plan["kadro_sonrasi"] if r["id"] not in uyeler1)
    assert all(r["takim_hafta"] == "2026-11-01" for r in plan["kadro_sonrasi"] if r["id"] in uyeler1)          # takim_hafta = kadroya SON giriş
    # önceki aktif bilinmiyor (önceki snapshot ilk seçim): iki Pazar hareketsizlik kararı yok; gerekçe açıklamada
    assert all(a["bu_pazar_aktif"] is True and a["onceki_pazar_aktif"] is None and a["bu_pazar_gecerli"] is True for a in snap["adaylar"])
    assert (hedef / "akis.json").exists() and json.loads((cikti / "son.json").read_text())["ilk11"]["sema"] == "ilk11-form-v1"
    liste = load_list(cikti / "ilk11/izleme_listesi.yaml")
    assert len([r for r in liste if "takim" in r]) == 40 and all(r["snapshot_id"] == snap["snapshot_id"] for r in liste if "takim" in r)
    assert all(0 <= r["form_puani"] <= 100 for r in liste if "form_puani" in r)
    assert len({r["id"] for r in liste}) == len(liste)
    # aynı girdi -> aynı snapshot_id (başka dizinde sıfırdan üretim)
    cikti_b = tmp_path / "cikti_b"
    assert pz.calistir(dal, cikti_b, PAZAR2 + pd.Timedelta(hours=2).to_pytimedelta(), izleme_dali=repo) == 0
    assert json.loads((cikti_b / "ilk11/2026-11-08/snapshot.json").read_text())["snapshot_id"] == snap["snapshot_id"]
    # yeniden deneme senaryosu: akis.json başarısız -> 2 saat sonra aynı kimlikle yeniden dene
    assert pz.main(["--kapi-dali", str(cikti), "--now", "2026-11-08T12:30:00Z", "--basarisiz-isaretle"]) == 0
    akis = json.loads((hedef / "akis.json").read_text())
    assert akis["basarili"] is False and akis["deneme_sayisi"] == 2 and akis["snapshot_id"] == snap["snapshot_id"]


def test_form_kapi_eski_ise_hareketler_uygulanir_bosluk_doldurulmaz_cikis_kodu_2(dal, tmp_path):
    snap1 = ilk_calistir(dal)                                                                    # kapı 2026-10-31: PAZAR2'ye göre 8 gün eski
    repo = izleme_deposu(tmp_path, [("s1", durum_olustur(snap1, "2026-11-08T09:23:00Z"))])
    cikti = tmp_path / "c"
    assert pz.calistir(dal, cikti, PAZAR2, izleme_dali=repo) == 2
    hedef = cikti / "ilk11/2026-11-08"
    plan = json.loads((hedef / "plan.json").read_text())
    assert len(plan["boslugu_dolduranlar"]) == 0 and len(plan["kadro_sonrasi"]) == 30
    snap = json.loads((hedef / "snapshot.json").read_text())
    assert "kapı verisi eski" in snap["uyari"] and all(a["kapi_puani"] is None for a in snap["adaylar"])


def test_golden_18_form_gecerlilik_ve_aktiflik():
    uye = {"id": adres(1), "grup": "paf", "takim_hafta": "2026-11-01"}
    as_of_utc = AS_OF2.astimezone(UTC)
    taze = "2026-11-08T09:30:00Z"

    def satir(trader, onceki=None):
        return pz.form_satiri(uye, trader, as_of_utc, onceki, None, RULES)

    def trader(dolu=10, uretildi=taze, **over):
        alanlar = {a: (1.0 if i < dolu else None) for i, a in enumerate(ilk11.KALDIRAC_ALANLARI)}
        return trader_durum("T1", adres(1), 5, uretildi, **{"ilk11_form_ham": {"alanlar": alanlar, "alan_kaynagi": {}, "dolu_alan": dolu}, **over})
    assert satir(trader())["bu_pazar_gecerli"] is True
    assert satir(trader(dolu=8))["bu_pazar_gecerli"] is True                                    # 8/10: sınırda geçerli
    assert satir(trader(dolu=7))["bu_pazar_gecerli"] is False                                   # 7 alan dolu -> hareket yok
    assert satir(trader(uretildi="2026-11-08T07:00:00Z"))["bu_pazar_gecerli"] is False          # veri 3 saat eski (> 120 dk)
    assert satir(trader(uretildi="2026-11-08T08:00:00Z"))["bu_pazar_gecerli"] is True           # tam 120 dk: sınırda geçerli
    assert satir(trader(gecerli=False))["bu_pazar_gecerli"] is False
    assert satir(trader(ilk11_form_ham={"hata": "x"}))["bu_pazar_gecerli"] is False
    assert satir(None)["bu_pazar_gecerli"] is False and satir(None)["bu_pazar_aktif"] is None
    # aktif: son 7 gün içinde (as_of − 7 g, as_of] tek perp dolumu -> true; yalnız spot (perp dolumu yok) -> false; okuma geçersizse bilinmiyor
    assert satir(trader(son_perp_dolum="2026-11-02T10:00:01Z"))["bu_pazar_aktif"] is True
    assert satir(trader(son_perp_dolum="2026-11-01T10:00:00Z"))["bu_pazar_aktif"] is False      # tam 7 gün önce: aralık dışı (açık alt sınır)
    assert satir(trader(son_perp_dolum=None))["bu_pazar_aktif"] is False
    assert satir(trader(gecerli=False))["bu_pazar_aktif"] is None
    assert satir(trader(), onceki=False)["onceki_pazar_aktif"] is False and satir(trader())["onceki_pazar_aktif"] is None
    # iki ardışık hareketsiz Pazar: pazar_gecis PAF'ı kadro dışına alır; bilinmeyen -> hareket yok (ilk11 modülü, değişmez)
    rows = [{**satir(trader(son_perp_dolum=None), onceki=False), "form_puani": 55.0}]
    assert ilk11.pazar_gecis(rows, "2026-11-08")["degisiklik_plani"][0]["neden"] == "iki ardışık Pazar hareketsiz"
    rows = [{**satir(trader(son_perp_dolum=None), onceki=None), "form_puani": 55.0}]
    assert ilk11.pazar_gecis(rows, "2026-11-08")["degisiklik_plani"] == []


def test_form_yedek_terfi_kapisi_kapanan_islemlerle_uctan_uca(dal, tmp_path):
    """Yedek üyenin son 6 geçerli işlemi kapıyı geçerse ve form ≥ 60 ise İlk 11'e terfi eder; İlk 11'den biri form < 40 ile düşünce yer açılır."""
    snap1 = ilk_calistir(dal)
    kadro = snap1["kadro"]
    durum = durum_olustur(snap1, "2026-11-08T09:23:00Z")
    by = {t["adres"]: t for t in durum["traderlar"]}
    ilk11_uye = next(r for r in kadro if r["takim"] == "ilk11")
    yedek = next(r for r in kadro if r["takim"] == "yedek11")
    en_kotu = {"golge": -0.9, "ay_roi": -0.9, "hafta_roi": -0.9, "hesap": 5001.0, "dusus": 0.9, "kazanma": 0.0, "siklik": 0.0, "tutma": 1.0, "kaldirac": 190.0, "tutarli": 0.0}
    en_iyi = {"golge": 0.9, "ay_roi": 0.9, "hafta_roi": 0.9, "hesap": 400000.0, "dusus": 0.0, "kazanma": 0.99, "siklik": 1.0, "tutma": 5.0, "kaldirac": 4.0, "tutarli": 0.99}
    yedek_kotu = [r for r in kadro if r["takim"] == "yedek11"][1]
    by[ilk11_uye["id"]]["ilk11_form_ham"]["alanlar"] = en_kotu
    by[yedek_kotu["id"]]["ilk11_form_ham"]["alanlar"] = en_kotu
    by[yedek["id"]]["ilk11_form_ham"]["alanlar"] = en_iyi
    by[yedek["id"]]["sanal_kopya_v3"]["kapanan_islemler"] = [
        {"coin": "BTC", "acilis": f"2026-11-0{2 + i}T00:00:00Z", "kapanis": f"2026-11-0{2 + i}T06:00:00Z", "sonuc_usd": s, "getiri": s / 20, "neden": "trader", "gecerli": True}
        for i, s in enumerate([3, -1, 2, -1, 2, -1])]
    repo = izleme_deposu(tmp_path, [("s1", durum)])
    kapi_yaz(dal, "2026-11-07", [kapi_satiri(i) for i in range(1, 61)])
    cikti = tmp_path / "c"
    assert pz.calistir(dal, cikti, PAZAR2, izleme_dali=repo) == 0
    plan = json.loads((cikti / "ilk11/2026-11-08/plan.json").read_text())
    hareketler = {m["id"]: (m["once"], m["sonra"]) for m in plan["degisiklik_plani"]}
    # Zincir (pazar_gecis, değişmez): kötü yedek -> paf (PAF'ta çıkışlarla yer açıldı), kötü İlk 11 -> yedek, en iyi yedek -> İlk 11 (terfi kapısı geçti:
    # son 6 sonuç [3,-1,2,-1,2,-1]: toplam 4, kazanma 0,5, en iyi hariç 1 > 0)
    assert hareketler[yedek_kotu["id"]] == ("yedek11", "paf")
    assert hareketler[ilk11_uye["id"]] == ("ilk11", "yedek11")
    assert hareketler[yedek["id"]] == ("yedek11", "ilk11")
    sonra = {r["id"]: r["grup"] for r in plan["kadro_sonrasi"]}
    assert sonra[yedek["id"]] == "ilk11" and list(sonra.values()).count("ilk11") == 11
