"""Pano ve bekleme vardiyası (kullanıcı onayı 14.11, Fable denetimi): bekleme vardiyasında ozet.json + dönem serisi, dönem boyu slot/emir/doluluk kayıtları
(`durum/donem_seri.json`), kadro kasası uyarısı yalnız güncel kadroda; pano bölümleri (dönem eğrisi, trader katkısı, İlk 11 ↔ Yedek, giriş/çıkış, doluluk, huni, atlanan oranı, isabet)."""
from __future__ import annotations

import asyncio
import json

import pytest

from copytrade.canli import motor as mt
from copytrade.canli.kadro import Karar
from tests.test_canli_motor import GUN, SAAT, T0, adr, kadro, kayitlar, kur, olay, satir
from tests.test_denetim_1411 import DONEM, DONEM_MS, BtcHL


# ================================================================================================ bekleme vardiyası (madde 6)
def test_bekleme_vardiyasi_her_yoklamada_ozet_donem_serisi_ve_btc_donem_yazar(tmp_path):
    """Saha boş (kadroda 0 kişi): 900 sn vardiya, 300 sn aralık → 4 yoklama (0, 300, 600, 900 sn), 3 uyku. Her uykudan önce ozet.json yazılmış ve yazıldı anı ilerlemiş olmalı.
    Doluluk (elle): 3 adım × 300.000 ms = 900.000 ms süre; sahada 0 → slot_ms 0; kapasite = saha_n × 900.000; nakit payı 1 → nakit_ms 900.000."""
    hl = BtcHL({"1m": [{"t": DONEM_MS, "o": "80000"}]}, mids={"BTC": "80800", "ETH": "2000", "SOL": "100"})
    m, _, saat, _ = kur(tmp_path, hl=hl, kasa=10_000.0)
    m.donem, m.radar_surum_gerekli = DONEM, "v3"
    bos = {**kadro([], saat() - SAAT), "radar_surum": "v3", "kasa_usd": 10_000.0}
    m.kadro_oku = lambda: bos
    yazilan = []

    async def uyku(sn):
        yazilan.append(json.loads((tmp_path / "durum" / "ozet.json").read_text(encoding="utf-8"))["yazildi_ms"])
        saat.ms += 300_000

    ozet = asyncio.run(mt.bekleme_vardiyasi(m, 900, uyku=uyku))
    assert ozet["bekleme_vardiyasi"] is True and ozet["kadro_geldi"] is False
    assert len(yazilan) == 3 and yazilan == sorted(yazilan) and len(set(yazilan)) == 3                # vardiya sonunu beklemeden, her yoklamada
    seri = json.loads((tmp_path / "durum" / "donem_seri.json").read_text(encoding="utf-8"))
    assert seri["btc_donem_fiyat"] == 80000.0 and seri["gunler"][-1]["btc"] == 80800.0 and seri["gunler"][-1]["ozsermaye_usd"] == 10_000.0
    dl = seri["doluluk"]
    assert dl["sure_ms"] == 900_000 and dl["slot_ms"] == 0 and dl["kapasite_ms"] == m.saha.n * 900_000 and dl["nakit_ms"] == pytest.approx(900_000)
    assert ozet["btc_al_tut_getiri"] == pytest.approx(0.01)                                             # BTC al-tut kıyası bekleme vardiyasında da


def test_doluluk_vardiya_boslugunu_saymaz(tmp_path):
    m, _, saat, _ = kur(tmp_path, kasa=10_000.0)
    m.donem = DONEM
    m.donem_seri_guncelle(saat())
    saat.ms += 6 * 60_000                                                                               # 6 dk > 5 dk adım sınırı: sayılmaz
    m.donem_seri_guncelle(saat())
    saat.ms += 60_000
    m.donem_seri_guncelle(saat())
    assert m.donem_seri["doluluk"]["sure_ms"] == 60_000


# ================================================================================================ dönem boyu slot ve emir kayıtları (madde 9 b/c/d/g)
def test_donem_slot_kaydi_giris_cikis_net_ve_emir_sayaci(tmp_path):
    """Kasa 1.000 → slot 90,909 $. adr(1) girer (katman ilk11), BTC 100'den açar (emir 27,27 $; ücret 0,01227 $). BTC mark 110 → açık K/Z = 0,27273 × 10 = 2,7273 $ → net ≈ 2,715 $.
    Düşme (slot, sonuçla) → çıkış kaydı; slot kapanınca kayıt silinmez (kalıcı). Emir sayacı: 1 emir; 1 atlanan (spot)."""
    m, hl, saat, _ = kur(tmp_path, kurallar={"canli_telegram_sanal_ozet_dk": 0})
    m.donem = DONEM
    m.baslat()
    assert [(r["adres"], r["katman"], r["giris_ms"], r["cikis_ms"]) for r in m.donem_seri["slotlar"]] == [(adr(1), "ilk11", saat(), None)]
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    m.olay_isle(olay("a:2", adr(1), "@107", "B", 5, 1.0, 0.0, saat))                                   # spot: atlanır
    hl.mids["BTC"] = "110"
    m.piyasa_oku(saat())
    m.donem_seri_guncelle(saat())
    r = m.donem_seri["slotlar"][0]
    beklenen = m.hesap.slot_ozsermaye(adr(1), m.marks) - m.hesap.slot_bas[adr(1)]
    assert r["net_usd"] == pytest.approx(beklenen, abs=1e-3) and r["net_usd"] == pytest.approx(2.7273 - 0.0123, abs=2e-3)
    sy = m.donem_seri["emir_sayac"]
    assert sy["emir"] == 1 and sy["atlanan"] == 1 and sy["yuvarlanan"] == 0 and sum(sy["atlama_neden"].values()) == 1
    saat.ms += SAAT
    m.karar_uygula([Karar("dus", adr(1), "slot", True)], saat())
    assert (r["cikis_neden"], r["sonuc"], r["cikis_ms"]) == ("slot", True, saat())
    m.durum_yaz()
    seri = json.loads((tmp_path / "durum" / "donem_seri.json").read_text(encoding="utf-8"))
    assert seri["slotlar"][0]["cikis_neden"] == "slot" and seri["emir_sayac"]["emir"] == 1


# ================================================================================================ kadro kasası uyarısı yalnız güncel kadroda (madde 7)
def test_kadro_kasa_farkli_yalniz_guncel_kadroda(tmp_path):
    m, _, saat, tgp = kur(tmp_path, kasa=1000.0)
    m.donem = mt.datetime.fromtimestamp((saat() - SAAT) / 1000, mt.UTC).isoformat().replace("+00:00", "Z")     # dönem başı = şimdi − 1 sa
    eski = {**kadro([satir(1, 1)], saat() - 2 * SAAT), "kasa_usd": 10_000.0}                                  # dönem başından önceki koşu
    m._kadro_kasa_denetle(eski, saat())
    bayat = {**kadro([satir(1, 1)], saat() - 40 * SAAT), "kasa_usd": 10_000.0}
    m._kadro_kasa_denetle(bayat, saat())
    assert not kayitlar(tmp_path, "kadro_kasa_farkli")
    guncel = {**kadro([satir(1, 1)], saat() - SAAT // 2), "kasa_usd": 10_000.0}
    m._kadro_kasa_denetle(guncel, saat())
    assert len(kayitlar(tmp_path, "kadro_kasa_farkli")) == 1
    assert T0 and GUN                                                                                   # içe aktarılan sabitler kullanılır


# ================================================================================================ pano (madde 7, 8, 9)
from copytrade.canli import pano  # noqa: E402

DS = {"donem": DONEM, "bas_ms": DONEM_MS, "kasa_usd": 10_000.0, "btc_donem_fiyat": 80_000.0,
      "gunler": [{"gun": "2027-01-15", "ozsermaye_usd": 10_100.0, "btc": 80_800.0}, {"gun": "2027-01-16", "ozsermaye_usd": 10_250.0, "btc": 79_200.0}],
      "slotlar": [{"adres": adr(1), "katman": "ilk11", "giris_ms": DONEM_MS, "giris_neden": "bos_slot", "cikis_ms": DONEM_MS + 6 * SAAT, "cikis_neden": "slot", "sonuc": True, "net_usd": -50.0},
                  {"adres": adr(2), "katman": "ilk11", "giris_ms": DONEM_MS, "giris_neden": "bos_slot", "cikis_ms": None, "cikis_neden": None, "sonuc": None, "net_usd": 200.0},
                  {"adres": adr(3), "katman": "yedek", "giris_ms": DONEM_MS + 7 * SAAT, "giris_neden": "bos_slot", "cikis_ms": None, "cikis_neden": None, "sonuc": None, "net_usd": 100.0}],
      "doluluk": {"sure_ms": 10 * SAAT, "slot_ms": 11 * 10 * SAAT * 0.75, "kapasite_ms": 11 * 10 * SAAT, "nakit_ms": 4 * SAAT, "son_ms": T0},
      "emir_sayac": {"emir": 30, "atlanan": 10, "yuvarlanan": 3, "atlama_neden": {"spot_atlandi": 10}}}
KADRO = {"kosu_ms": T0, "saha_n": 5, "satirlar": [], "huni": {"evren": 2457, "aday": 900, "islem_yeterli": 140, "islem_esik": 10, "gecen": 12, "kadro": 12,
                                                               "neden": {"islem_az": 600, "kopya_zarar": 200, "sans_riski": 88}}}


def test_pano_donem_ozetleri_altin_ornek():
    """Elle: katkı İlk 11 = −50 + 200 = +150 $ (2 slot), Yedek = +100 $ (1 slot), toplam +250 $ (= özsermaye 10.250 − kasa 10.000).
    Doluluk 0,75; nakit 4 / 10 = 0,40. Atlanan 10 / (30 + 10) = 0,25; yuvarlanan 3 / 30 = 0,10.
    Eğri: dönem başı (10.000, BTC 10.000, hedef 10.000); 15.01 gün sonu (= 16.01 00:00, dönem başından 17 sa) motor 10.100, BTC 10.000 × 80.800 / 80.000 = 10.100,
    hedef 10.000 × 1,04^(17/24/30); 16.01 (şimdi T0 + 2 gün sınırında) motor 10.250, BTC 9.900."""
    so = pano.slot_ozeti(DS)
    assert so["katman"] == {"ilk11": {"n": 2, "net": 150.0}, "yedek": {"n": 1, "net": 100.0}} and so["toplam"] == 250.0
    assert [r["adres"] for r in so["trader"]] == [adr(2), adr(3), adr(1)]
    assert pano.doluluk_ozeti(DS) == (pytest.approx(0.75), pytest.approx(0.40), pytest.approx(10 / 24))
    at, yv, _ = pano.emir_orani(DS)
    assert at == pytest.approx(0.25) and yv == pytest.approx(0.10)
    nok = pano.egri_noktalari(DS, 0.04, T0 + 3 * GUN)
    assert nok[0] == (DONEM_MS, 10_000.0, 10_000.0, 10_000.0)
    assert nok[1][1:3] == (10_100.0, pytest.approx(10_100.0)) and nok[1][3] == pytest.approx(10_000 * 1.04 ** (17 / 24 / 30))
    assert nok[2][1:3] == (10_250.0, pytest.approx(9_900.0))
    assert pano.emir_orani({}) == (None, None, {}) and pano.doluluk_ozeti({})[0] is None and pano.egri_noktalari({}, 0.04, T0) == []


def test_pano_html_donem_sekmesi_ve_kaldirilanlar():
    ozet = {"kip": "sanal", "kasa_usd": 10_000.0, "ozsermaye_usd": 10_250.0, "getiri": 0.025, "acik": [], "saha": 3, "saha_n": 5, "donem": DONEM}
    isabet = [{"tarih": "2027-01-08", "pencere_gun": 7.0, "pencere_tam": True, "ic": 0.12, "fark_ilk11_havuz": 0.01, "fark_ilk11_elenen": 0.03,
               "gruplar": {"ilk11": {"n": 11}, "havuz_geri": {"n": 5}, "elenen": {"n": 30}}}]
    h = pano.html_olustur(ozet, {}, {}, [], [], T0 + GUN, KADRO, {"uyeler": {}, "inen": {}}, donem_seri=DS, isabetler=isabet)
    assert "İçgörüler" not in h and "Bu hafta" not in h and "Hype yakalama" not in h                           # madde 8
    assert "SAHADA (0/5)" in h and "KADRO <em>0/5</em>" in h and "/11" not in h                               # madde 7: saha_n
    assert 'class="sirit" style="--sm:2;--sk:4"' in h                                                          # 8 hücre: telefon 2, masaüstü 4 (boş kutu yok)
    assert "Dönem eğrisi" in h and "<polyline" in h and "BTC al-tut" in h and "%4/ay hedef" in h               # 9a
    assert "Trader katkısı" in h and "sahada" in h and "+200,00 $" in h                                        # 9b
    assert "İlk 11</b> · 2 slot" in h and "Yedek</b> · 1 slot" in h                                           # 9c
    assert "➖ çıkış" in h and "(sonuçla)" in h                                                                # 9d
    assert "%75" in h and "%40" in h                                                                           # 9e
    assert "Evren · <b>2457</b>" in h and "≥10 işlem · <b>140</b>" in h and "islem_az" in h                    # 9f
    assert "atlanan sinyal <b>%25" in h and "yuvarlanan emir <b>%10" in h                                      # 9g
    assert "+0.12" in h and "İLK11−HAVUZ" in h                                                                 # 9h
    bos = pano.html_olustur({**ozet, "donem": None}, {}, {}, [], [], T0, None, None)
    assert "dönem eğrisi ilk UTC gün" in bos and "kadroda huni özeti yok" in bos and "henüz ölçüm yok" in bos and "2026-11-12" not in bos


def test_pano_bu_hafta_yalniz_farkliysa_ve_serit_sutunu():
    assert pano.serit(["<i></i>"] * 9).startswith('<div class="sirit" style="--sm:3;--sk:3"')
    assert pano.serit(["<i></i>"] * 4, "g3").startswith('<div class="sirit g3" style="--sm:2;--sk:4"')
    gecmis = [{"gun": "2027-01-05", "ozsermaye": 10_000.0}, {"gun": "2027-01-08", "ozsermaye": 10_100.0}]
    ozet = {"kip": "sanal", "kasa_usd": 10_000.0, "ozsermaye_usd": 10_300.0, "getiri": 0.03, "acik": []}
    h = pano.html_olustur(ozet, {}, {}, [], gecmis, T0, None, None)                                           # 7 gün önce 10.100 → hafta +%2 ≠ toplam +%3
    assert "Bu hafta" in h and 'style="--sm:3;--sk:3"' in h


def test_pano_md_donem_bolumu():
    md, _ = pano.pano_olustur({"kip": "sanal", "kasa_usd": 10_000.0, "ozsermaye_usd": 10_250.0, "donem": DONEM}, {}, {}, [], [], [], T0, DS, KADRO)
    assert "## Dönem (kalıcı seri)" in md and "İlk 11 2 slot +150,00 $" in md and "Yedek 1 slot +100,00 $" in md
    assert "saha doluluğu %75" in md and "atlanan sinyal %25" in md and "evren 2457 → aday 900 → ≥10 işlem 140 → geçen 12" in md
    assert "ilk ölçüm ≈ 2027-01-22" in md


# ================================================================================================ M-04 + M-05 (kullanıcı kararı 14.11; yalnız rapor)
def test_m04_maruziyet_ozeti_altin_ornek_ve_motor_birikimi(tmp_path):
    """Elle: 10 sa ölçüm; brüt 4.000 $ × 6 sa + 0 × 4 sa → ortalama 2.400 $ (kasa 10.000'in %24'ü); |net| 1.000 $ × 6 sa → 600 $. Özsermaye 10.120 → kullanılan sermaye getirisi 120 / 2.400 = %5."""
    ds = {"doluluk": {"sure_ms": 10 * SAAT, "brut_ms": 4000.0 * 6 * SAAT, "net_ms": 1000.0 * 6 * SAAT}}
    mo = pano.maruziyet_ozeti(ds, 10_120.0, 10_000.0)
    assert mo["brut"] == pytest.approx(2400.0) and mo["brut_oran"] == pytest.approx(0.24) and mo["net"] == pytest.approx(600.0) and mo["sermaye_getirisi"] == pytest.approx(0.05)
    assert pano.maruziyet_ozeti({}, 1.0, 1.0)["sermaye_getirisi"] is None
    m, hl, saat, _ = kur(tmp_path, kurallar={"canli_telegram_sanal_ozet_dk": 0})                # motor: 0,27273 BTC × 100 = 27,27 $ brüt; 2 dk
    m.donem = DONEM
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    m.donem_seri_guncelle(saat())
    brut = m.hesap.brut_toplam(m.marks)
    saat.ms += 120_000
    m.donem_seri_guncelle(saat())
    dl = m.donem_seri["doluluk"]
    assert dl["brut_ms"] == pytest.approx(brut * 120_000) and dl["net_ms"] == pytest.approx(brut * 120_000)        # tek uzun: |net| = brüt
    m.donem_kilit("gunluk_kayip", saat())
    assert m.donem_seri["kilitler"] == [{"ms": saat(), "tur": "gunluk_kayip"}]


def test_m05_pano_karar_kutusu_isabet_ozeti_ve_kilit_isareti():
    ozet = {"kip": "sanal", "kasa_usd": 10_000.0, "ozsermaye_usd": 10_250.0, "getiri": 0.025, "acik": [], "donem": DONEM, "aylik_esdeger": 0.06, "aylik_hedef": 0.04,
            "btc_al_tut_getiri": -0.01, "hedef_gecer": True}
    isabet = [{"tarih": "2027-01-08", "ic": 0.2, "fark_ilk11_havuz": 0.01, "fark_ilk11_elenen": -0.01}, {"tarih": "2027-01-09", "ic": 0.0, "fark_ilk11_havuz": 0.03, "fark_ilk11_elenen": 0.03}]
    ds = {**DS, "kilitler": [{"ms": DONEM_MS + 20 * SAAT, "tur": "gunluk_kayip"}], "doluluk": {**DS["doluluk"], "brut_ms": 2500.0 * 10 * SAAT, "net_ms": 500.0 * 10 * SAAT}}
    h = pano.html_olustur(ozet, {}, {}, [], [], T0 + GUN, KADRO, None, donem_seri=ds, isabetler=isabet)
    i_karar, i_isabet = h.index("31.12 karar kutusu"), h.index("Seçim isabeti <span>özet")
    assert 0 < i_isabet - i_karar < 2500 and "GEÇİYOR" in h                                                  # karar kutusunun hemen yanında
    assert "2 ölçüm · ortalama IC <b>+0.10</b>" in h and "(2/2 pozitif)" in h and "(1/2 pozitif)" in h        # (0,2 + 0) / 2; havuz farkı 2/2, elenen 1/2 pozitif
    assert 'stroke="#ff5d5d" stroke-width="1"' in h and "Kilit olayı: 1" in h and "gölge eğri hesaplanmadı" in h
    assert "kullanılan sermaye getirisi <b>+%10,00" in h                                                    # 250 / 2.500
