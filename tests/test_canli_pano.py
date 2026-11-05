"""Günlük rapor `pano/OZET.md` (T6 §3): saf fonksiyon, elle hesaplanmış altın örnek. Yeni hesap yok: motorun yazdığı değerler biçimlenir."""
import json

import pytest

from copytrade.canli import pano

SAAT = 3_600_000
GUN = 24 * SAAT
SIMDI = 1_800_000_000_000 + 10 * SAAT          # gün başı + 10 sa
A1, A2 = "0x" + "11" * 20, "0x" + "22" * 20


def kayit(olay, dt_sa, **k):
    return {"zaman_ms": SIMDI - int(dt_sa * SAAT), "olay": olay, **k}


OZET = {"kip": "sanal", "vardiya": "42", "kasa_usd": 1000.0, "ozsermaye_usd": 1012.5, "getiri": 0.0125, "saha": 10, "saha_n": 11, "inen": 1, "sure_dk": 255.0,
        "dinleyici": {"kopma": 1, "yeniden_baglanma": 1}, "rest_429": 0,
        "acik": [{"adres": A1, "coin": "BTC", "sz": 0.5, "giris": 100.0, "mark": 110.0, "usd": 55.0, "kz_usd": 5.0}, {"adres": A2, "coin": "ETH", "sz": -1.0, "giris": 2000.0, "mark": 2010.0, "usd": 2010.0, "kz_usd": -10.0}]}
RISK = {"gun_basi": 1000.0, "zirve": 1025.0}
GECMIS = [{"gun": "2026-11-08", "ozsermaye": 990.0}, {"gun": "2026-11-14", "ozsermaye": 1005.0}]


def gunler():
    from datetime import UTC, datetime
    return datetime.fromtimestamp(SIMDI / 1000, UTC).date().isoformat()


def test_pano_altin_ornek_sayilar():
    """Özsermaye 1.012,5; gün başı 1.000 → gün +%1,25; zirve 1.025 → düşüş (1025 − 1012,5)/1025 = %1,22; 24 sa: 3 emir (2 dolu, 1 red), kayma [0,001; 0,003] → p50 (n//2 = 1. indeks) 0,3%, max 0,3%;
    ücret 0,01 + 0,02 + 0 = 0,03 $; funding −0,05 − 0,07 = −0,12 $; 25 sa önceki olay dışarıda."""
    kayitlar = [kayit("emir", 2, durum="dolu", kayma_trader=0.001, ucret=0.01), kayit("emir", 3, durum="kismi", kayma_trader=0.003, ucret=0.02), kayit("emir", 4, durum="red", kayma_trader=None, ucret=0.0),
                kayit("emir", 25, durum="dolu", kayma_trader=0.9, ucret=9.0), kayit("funding", 1, funding_usd=-0.05), kayit("funding", 5, funding_usd=-0.07),
                kayit("saha_giris", 6, adres=A1, neden="ilk_gun"), kayit("saha_dus", 7, adres=A2, neden="islem_yok"),
                kayit("risk", 3, tur="gunluk_kayip"), kayit("vardiya_boslugu", 8, dk=45.0)]
    isabet = {"tarih": "2026-11-05", "pencere_gun": 7.0, "pencere_tam": True, "eksik": False, "ic": 0.31, "fark_ilk11_havuz": 0.004, "fark_ilk11_elenen": 0.02,
              "gruplar": {"ilk11": {"n": 11}, "havuz_geri": {"n": 3}, "elenen": {"n": 30}}}
    md, yeni = pano.pano_olustur(OZET, RISK, {}, kayitlar, [isabet], GECMIS, SIMDI)
    assert "| 1.000,00 $ | 1.012,50 $ | +%1,25 | " in md and "| +%1,25 | −%1,22 |" in md                    # gün +%1,25; toplam +%1,25; zirveden düşüş −%1,22
    assert "emir 3 · dolum 2 · kayma p50 +%0,30 / max +%0,30 (n=2)" in md and "funding −0,12 $ · ücret 0,03 $" in md
    assert "| 0x111111… | BTC | L | 55,00 $ | +5,00 $ |" in md and "| 0x222222… | ETH | S | 2.010,00 $ | −10,00 $ |" in md
    assert "giriş 0x111111… — ilk_gun" in md and "çıkış 0x222222… — islem_yok" in md and "`risk` gunluk_kayip" in md and "boşluk 45.0 dk" in md and "REST 429 0" in md
    assert "| 2026-11-05 | 7.0 gün | +0.31 | +%0,40 | +%2,00 | 11/3/30 |" in md
    assert yeni[-1] == {"gun": gunler(), "ozsermaye": 1012.5} and len(yeni) == 3


def test_hafta_getirisi_gecmisten_ve_yetersiz_gecmis():
    """7 gün önceki nokta 1.000, şimdi 1.012,5, kasa 1.000 → +%1,25; geçmiş 7 günden kısaysa None."""
    from datetime import UTC, datetime, timedelta
    bugun = datetime.fromtimestamp(SIMDI / 1000, UTC).date()
    g = [{"gun": (bugun - timedelta(days=8)).isoformat(), "ozsermaye": 900.0}, {"gun": (bugun - timedelta(days=7)).isoformat(), "ozsermaye": 1000.0}, {"gun": (bugun - timedelta(days=1)).isoformat(), "ozsermaye": 1005.0}]
    assert pano.hafta_getirisi(g, 1012.5, SIMDI, 1000.0) == pytest.approx(0.0125)
    assert pano.hafta_getirisi(g[2:], 1012.5, SIMDI, 1000.0) is None and pano.hafta_getirisi([], 1012.5, SIMDI, 1000.0) is None


def test_isabet_yoksa_ilk_olcum_yazilir_acik_pozisyon_yoksa_ve_hesap_json_yedegi():
    md, _ = pano.pano_olustur({**OZET, "acik": []}, {}, {}, [], [], [], SIMDI)
    assert "ilk ölçüm 2026-11-12" in md and "açık pozisyon yok" in md and "değişiklik yok" in md and "olay yok" in md and "(geçmiş < 7 gün)" in md
    # ozet'te 'acik' yoksa hesap.json'dan (mark yok → K/Z —)
    ozet = {k: v for k, v in OZET.items() if k != "acik"}
    md2, _ = pano.pano_olustur(ozet, RISK, {"poz": {A1: {"BTC": {"sz": 0.5, "giris": 100.0}}}}, [], [], [], SIMDI)
    assert "| 0x111111… | BTC | L | 50,00 $ | — |" in md2


def test_gecmis_gunde_bir_nokta_ve_en_cok_15_gun():
    g = pano.gecmis_guncelle([], 1000.0, SIMDI)
    assert pano.gecmis_guncelle(g, 1010.0, SIMDI + SAAT) == [{"gun": gunler(), "ozsermaye": 1010.0}]          # aynı gün: güncellenir
    uzun = [{"gun": f"2026-10-{i:02d}", "ozsermaye": 1000.0} for i in range(1, 21)]
    assert len(pano.gecmis_guncelle(uzun, 1000.0, SIMDI)) == 15


def test_cli_dosyalari_yazar_ozet_yoksa_yazmaz(tmp_path, capsys):
    (tmp_path / "durum").mkdir()
    assert pano.main(["--durum", str(tmp_path / "durum"), "--kayit", str(tmp_path / "kayit"), "--cikti", str(tmp_path / "p/OZET.md"), "--gecmis", str(tmp_path / "p/gecmis.json")]) == 0
    assert not (tmp_path / "p").exists() and "ozet.json yok" in capsys.readouterr().err
    (tmp_path / "durum/ozet.json").write_text(json.dumps(OZET), encoding="utf-8")
    (tmp_path / "durum/risk.json").write_text(json.dumps(RISK), encoding="utf-8")
    (tmp_path / "kayit").mkdir()
    (tmp_path / "kayit/2026-01-01.jsonl").write_text(json.dumps({"zaman_ms": 1, "olay": "emir"}) + "\n{bozuk\n", encoding="utf-8")
    assert pano.main(["--durum", str(tmp_path / "durum"), "--kayit", str(tmp_path / "kayit"), "--cikti", str(tmp_path / "p/OZET.md"), "--gecmis", str(tmp_path / "p/gecmis.json")]) == 0
    assert (tmp_path / "p/OZET.md").read_text(encoding="utf-8").startswith("# Canlı rapor") and json.loads((tmp_path / "p/gecmis.json").read_text(encoding="utf-8"))[-1]["ozsermaye"] == 1012.5


def test_motor_pano_ek_acik_pozisyon_kz_ve_rest_sayaclari(tmp_path):
    """BTC long 2 @100, mark 110 → usd 220, K/Z +20; ETH short 1 @2000, mark 1990 → usd 1.990, K/Z +10 (short kâr). `post.stats` sayaçları aktarılır."""
    from tests.test_canli_motor import SahteHL, adr, kur
    hl = SahteHL()
    hl.stats = {"istek": 120, "429": 2, "5xx": 0}
    m, _, saat, _ = kur(tmp_path, hl=hl)
    m.baslat()
    m.hesap.uygula(adr(1), "BTC", "B", 2.0, 100.0, 0.0, saat())
    m.hesap.uygula(adr(1), "ETH", "A", 1.0, 2000.0, 0.0, saat())
    m.marks.update({"BTC": 110.0, "ETH": 1990.0})
    ek = m.pano_ek()
    acik = {p["coin"]: p for p in ek["acik"]}
    assert acik["BTC"]["usd"] == pytest.approx(220.0) and acik["BTC"]["kz_usd"] == pytest.approx(20.0)
    assert acik["ETH"]["usd"] == pytest.approx(1990.0) and acik["ETH"]["kz_usd"] == pytest.approx(10.0) and acik["ETH"]["sz"] == -1.0
    assert ek["rest_istek"] == 120 and ek["rest_429"] == 2
    ozet_md, _ = pano.pano_olustur({**OZET, **ek}, RISK, {}, [], [], [], SIMDI)
    assert "| 0x000000… | ETH | S | 1.990,00 $ | +10,00 $ |" in ozet_md and "REST 429 2" in ozet_md


def test_html_pano_turkce_biçim_ve_kacis(tmp_path):
    from copytrade.canli import pano
    ozet = {"kip": "sanal", "kasa_usd": 1000.0, "ozsermaye_usd": 1012.5, "getiri": 0.0125, "saha": 9, "saha_n": 11, "dinleyici": {"kopma": 1}, "rest_429": 0,
            "acik": [{"adres": "0xabc<script>12345", "coin": "BTC", "sz": 0.5, "usd": 1234.0, "kz_usd": -3.5}]}
    h = pano.html_olustur(ozet, {"gun_basi": 1000.0, "zirve": 1020.0}, {}, [], [{"gun": "2026-11-01", "ozsermaye": 1000.0}], 1_793_900_000_000)
    assert "1.012,50 $" in h and "+%1,25" in h and "1.234,00 $" in h and "−3,50 $" in h and "<polyline" in h and "0xabc<sc" not in h and "0xabc&lt;sc" in h and "TSİ" in h and "GERÇEK PARA" not in h
    assert "GERÇEK PARA" in pano.html_olustur({**ozet, "kip": "gercek"}, {}, {}, [], [], 1_793_900_000_000)


def test_html_pano_kadro_sekmesi_ilk11_yedek_ve_bize_verdigi(tmp_path):
    from copytrade.canli import pano
    a1, a2, a3 = "0xaaaa111122223333", "0xbbbb111122223333", "0xcccc111122223333"
    kadro = {"kosu_ms": 1_793_863_000_000, "satirlar": [
        {"adres": a1, "sira": 1, "katman": "ilk11", "form": 75.0, "kopya_getiri_7g": 0.014, "max_kaldirac": 5.0},
        {"adres": a2, "sira": 2, "katman": "ilk11", "form": 60.0, "kopya_getiri_7g": 0.01, "max_kaldirac": 7.0},
        {"adres": a3, "sira": 12, "katman": "yedek", "form": 30.0, "kopya_getiri_7g": 0.005, "max_kaldirac": 9.0}]}
    ozet = {"kip": "sanal", "kasa_usd": 1000.0, "ozsermaye_usd": 1000.0, "acik": [{"adres": a1, "coin": "BTC", "sz": 1.0, "usd": 100.0, "kz_usd": -2.0}]}
    hesap = {"realize": {a1: 5.0}, "ucret": {a1: 1.0}, "slot_bas": {a1: 90.0}}
    saha = {"uyeler": {a1: {"giris_ms": 1_793_800_000_000}}, "inen": {}}
    h = pano.html_olustur(ozet, {}, hesap, [{"olay": "emir", "adres": a1, "zaman_ms": 1_793_850_000_000, "coin": "BTC", "yon": "B", "durum": "dolu"}], [], 1_793_900_000_000, kadro, saha)
    assert 'SAHADA' in h and 'BEKLİYOR' in h and 'YEDEK' in h and "YEDEKLER" in h
    assert "+2,00 $" in h and "Emir sayısı" in h                                                      # a1 net = 5 − 1 + (−2) = +2,00 $


def test_html_pano_kadro_funding_dahil_bilinmeyen_kz_tire_kadro_disi_ve_mutabakat():
    from copytrade.canli import pano
    a1, a2, a3 = "0xaaaa111122223333", "0xbbbb111122223333", "0xdddd111122223333"
    kadro = {"kosu_ms": 1_793_863_000_000, "satirlar": [{"adres": a1, "sira": 1, "katman": "ilk11", "form": 75.0, "kopya_getiri_7g": 0.014, "max_kaldirac": 5.0}]}
    ozet = {"kip": "sanal", "kasa_usd": 1000.0, "ozsermaye_usd": 1000.0, "acik": [{"adres": a1, "coin": "BTC", "sz": 1.0, "usd": 100.0, "kz_usd": -2.0},
                                                                              {"adres": a2, "coin": "ETH", "sz": 1.0, "usd": 50.0, "kz_usd": None}]}
    hesap = {"realize": {a1: 5.0, a2: 1.0, a3: 0.0}, "ucret": {a1: 1.0, a2: 0.0, a3: 0.0}, "funding": {a1: -0.5}, "slot_bas": {a1: 90.0, a2: 90.0, a3: 90.0}, "kapanmis_net": 0.25}
    saha = {"uyeler": {a1: {}, a2: {}}, "inen": {a3: {"inis_ms": 1}}}
    h = pano.html_olustur(ozet, {}, hesap, [], [], 1_793_900_000_000, kadro, saha)
    assert "+1,50 $" in h                                  # a1 net = 5 − 1 − 0,5 + (−2) = +1,50 (funding dahil)
    assert "0xbbbb11" in h and "0xdddd11" in h and "İNİYOR" in h and "Radar listesinde yok" in h   # radar listesinde olmayan sahada/inen üyeler de görünür
    assert "bazı K/Z bilinmiyor" in h and "kapanmış slotlar" in h                           # a2'nin açık K/Z'si bilinmiyor → 0 sayılmaz, toplam eksik işaretli


def test_pano_bayat_ozet_yazilmaz(tmp_path, capsys):
    import json as _j
    from copytrade.canli import pano
    (tmp_path / "durum").mkdir()
    (tmp_path / "durum" / "ozet.json").write_text(_j.dumps({"vardiya": "111", "kasa_usd": 1000.0, "ozsermaye_usd": 1000.0}))
    rc = pano.main(["--durum", str(tmp_path / "durum"), "--kayit", str(tmp_path / "kayit"), "--gecmis", str(tmp_path / "g.json"), "--cikti", str(tmp_path / "OZET.md"), "--html", str(tmp_path / "index.html"), "--vardiya", "222"])
    assert rc == 0 and not (tmp_path / "OZET.md").exists() and not (tmp_path / "index.html").exists() and "bayat" in capsys.readouterr().err


def test_pano_b_duzeltmeleri_dd_koşan_azami_ilk_gun_cubugu_isaretli_fark_olcek_etiketleri():
    from copytrade.canli import pano
    kasa = 1000.0
    ozet = {"kip": "sanal", "kasa_usd": kasa, "ozsermaye_usd": 990.0, "getiri": -0.01, "vardiya": "9", "saha": 9, "saha_n": 11}
    gecmis = [{"gun": "2026-11-03", "ozsermaye": 1010.0}, {"gun": "2026-11-04", "ozsermaye": 1005.0}, {"gun": "2026-11-05", "ozsermaye": 990.0}]
    kayit = [{"olay": "emir", "zaman_ms": 1_793_899_000_000, "coin": "BTC", "yon": "B", "eylem": "ac", "durum": "dolu", "usd_dolan": 11.0, "kayma_trader": 0.0002},
             {"olay": "emir", "zaman_ms": 1_793_898_000_000, "coin": "ETH", "yon": "A", "eylem": "azalt", "durum": "dolu", "usd_dolan": 12.0, "kayma_trader": -0.0001},
             {"olay": "emir", "zaman_ms": 1_793_897_000_000, "coin": "SOL", "yon": "B", "eylem": "ac", "durum": "dolu", "usd_dolan": 11.0, "kayma_trader": None}]
    h = pano.html_olustur(ozet, {"gun_basi": 1005.0, "zirve": 1010.0}, {}, kayit, gecmis, 1_793_900_000_000)
    # B1: dd = koşan azami (başlangıç kasa 1000): 1010 → 0 %, 1005 → −0,495 %, 990 → −1,980 %
    assert "−%1,98" in h
    # B2: ilk gün çubuğu: 1010 − 1000 = +10 (yeşil), −5, −15 → 3 çubuk
    import re
    assert len(re.findall(r'<rect[^>]*fill="#3ddc84"', h)) == 1 and len(re.findall(r'<rect[^>]*fill="#ff5d5d"', h)) == 2
    # B3: kasa taban çizgisi (kesikli), min/max etiketi, x ekseni etiketleri
    assert "stroke-dasharray" in h and "en düşük 990,00 $ · en yüksek 1.010,00 $" in h and "kesikli çizgi: başlangıç 1.000,00 $" in h and "03.11" in h
    # B4: işaretli fark: aleyhe (+2,0 bp, kırmızı) / lehe (−1,0 bp, yeşil) / yok (—)
    assert '<td class="sg eks">+2,0 bp</td>' in h and '<td class="sg art">−1,0 bp</td>' in h and '<td class="sg so">—</td>' in h


def test_pano_veri_zamani_motorun_yazdigi_an_bayat_ozeti_taze_gostermez():
    from copytrade.canli import pano
    ozet = {"kip": "sanal", "kasa_usd": 1000.0, "ozsermaye_usd": 1000.0, "getiri": 0.0, "vardiya": "5", "yazildi_ms": 1_793_800_000_000}      # motor 16:26 UTC'de yazdı (donmuş olabilir)
    h = pano.html_olustur(ozet, {}, {}, [], [], 1_793_900_000_000)                                                                            # pano ~28 sa sonra üretildi
    assert 'data-ms="1793800000000"' in h                              # bayatlık motorun yazdığı ana göre (üretim anına göre değil)


# ---------------------------------------------------------------------------------------------- §C 1-6 (lider denetimi): yeni hesap yok, yalnız mevcut kayıtlar; elle hesaplanmış altın örnekler
def _c_veri():
    a1, a2 = "0x" + "a1" * 20, "0x" + "b2" * 20
    kadro = {"kosu_ms": 1_793_863_000_000, "satirlar": [{"adres": a1, "sira": 1, "katman": "ilk11", "form": 75.0, "kopya_getiri_7g": 0.014, "max_kaldirac": 5.0,
                                                          "bilesenler": {"G": 100.0, "K": 46.0, "I1": 61.0, "I2": 38.0, "Y": 61.0, "H": 84.0}},
                                                         {"adres": a2, "sira": 2, "katman": "ilk11", "form": 60.0, "kopya_getiri_7g": 0.01, "max_kaldirac": 7.0}]}
    ozet = {"kip": "sanal", "kasa_usd": 1000.0, "ozsermaye_usd": 1004.0, "getiri": 0.004, "vardiya": "9", "acik": [
        {"adres": a1, "coin": "BTC", "sz": 1.0, "usd": 200.0, "kz_usd": 3.0}, {"adres": a1, "coin": "ETH", "sz": -1.0, "usd": 100.0, "kz_usd": -1.0}]}
    hesap = {"kaldirac": 3.0, "realize": {a1: 4.0}, "ucret": {a1: 0.5}, "funding": {a1: -0.1}, "slot_bas": {a1: 100.0}}
    saha = {"uyeler": {a1: {"giris_ms": 1_793_800_000_000, "hesap_giris_usd": 100_000.0}}, "inen": {}}
    kayit = [
        {"olay": "emir", "zaman_ms": 1_793_890_000_000, "adres": a1, "coin": "BTC", "yon": "A", "eylem": "azalt", "reduce_only": True, "pnl_usd": 5.0, "ucret": 0.5, "durum": "dolu", "usd_dolan": 100.0, "kayma_trader": 0.001},
        {"olay": "emir", "zaman_ms": 1_793_891_000_000, "adres": a1, "coin": "ETH", "yon": "B", "eylem": "kapat", "reduce_only": True, "pnl_usd": -2.0, "ucret": 0.1, "durum": "dolu", "usd_dolan": 50.0, "kayma_trader": -0.0004},
        {"olay": "emir", "zaman_ms": 1_793_892_000_000, "adres": a1, "coin": "SOL", "yon": "B", "eylem": "ac", "reduce_only": False, "pnl_usd": None, "ucret": 0.2, "durum": "dolu", "usd_dolan": 20.0, "kayma_trader": 0.0},
        {"olay": "funding", "zaman_ms": 1_793_893_000_000, "funding_usd": -0.1},
        {"olay": "emir_yok", "zaman_ms": 1_793_894_000_000, "neden": "min_emir_atlandi"}, {"olay": "emir_yok", "zaman_ms": 1_793_894_100_000, "neden": "min_emir_atlandi"},
        {"olay": "emir_yok", "zaman_ms": 1_793_894_200_000, "neden": "slot_tavani"}]
    return a1, a2, kadro, ozet, hesap, saha, kayit


def test_pano_c1_canli_kopya_korumasi_ve_c6_kadro_kartlari():
    from copytrade.canli import pano
    a1, a2, kadro, ozet, hesap, saha, kayit = _c_veri()
    # a1 net = realize 4 − ücret 0,5 + funding (−0,1) + açık K/Z (3 − 1 = 2) = +5,4 $ → slot 100 $ ⇒ bizim getiri +%5,40; trader hesabı 100.000 → 103.000 ⇒ +%3,00; koruma = 5,4 / 3 = 1,8
    h = pano.html_olustur(ozet, {}, hesap, kayit, [], 1_793_900_000_000, kadro, saha, {a1: {"deger": 103_000.0, "ms": 1}}, {a1: {"yatirma_payi": 0.3, "kopya_koruma": 0.75}, a2: {"yatirma_payi": 0.05}})
    assert "+%5,40" in h and "+%3,00" in h and ">1,80<" in h                      # C1: bizim getiri / trader getirisi / koruma oranı
    assert "⚠ +%30,00" in h and "0,75" in h                                       # C6: yatirma_payi 0,3 > 0,2 ⇒ ⚠; radar koruma
    assert "Güven ayarlı getiri" in h and "Hype yakalama" in h                    # C6: form bileşenleri
    assert f'href="https://app.hyperliquid.xyz/explorer/address/{a1}"' in h       # C6: trader sayfası bağlantısı (yalnız geçerli 42 karakterli adres)
    h2 = pano.html_olustur(ozet, {}, hesap, kayit, [], 1_793_900_000_000, kadro, {"uyeler": {a1: {"giris_ms": 1}}, "inen": {}}, None, None)
    assert "girişte kaydedilmemiş" in h2                                          # eski üyede giriş hesabı yok → "—"


def test_pano_c2_c3_c4_c5_atlanan_kapanan_maliyet_maruziyet():
    from copytrade.canli import pano
    a1, a2, kadro, ozet, hesap, saha, kayit = _c_veri()
    h = pano.html_olustur(ozet, {}, hesap, kayit, [], 1_793_900_000_000, kadro, saha)
    # C2: min_emir_atlandi ×2, slot_tavani ×1 → %67 / %33
    assert "<b>2</b> × Emir 11 $ alt sınırının altında kaldı" in h and "<b>1</b> × Slot tavanı doldu" in h and "%67" in h
    # C3: iki kapanış dolumu: net +5,0 − 0,5 = +4,5 (kâr) ve −2,0 − 0,1 = −2,1 (zarar) → 2 adet, kazanma %50, ort. kâr 4,50 $, ort. zarar −2,10 $, kâr faktörü 4,5 / 2,1 = 2,14, net +2,40 $
    assert '<td>TOPLAM</td><td class="sg">2</td><td class="sg">%50</td><td class="sg art">4,50 $</td><td class="sg eks">−2,10 $</td><td class="sg">2,14</td><td class="sg art">+2,40 $</td>' in h
    # C4: ücret 0,5 + 0,1 + 0,2 = 0,8; kayma = 0,001 × 100 + (−0,0004 × 50) + 0 = 0,1 − 0,02 = 0,08; funding −0,1 ⇒ maliyet = 0,8 + 0,08 − (−0,1) = 0,98; net 1004 − 1000 = +4,00; brüt = 4,98
    assert "−0,80 $" in h and "−0,08 $" in h and "−0,10 $" in h and "+4,98 $" in h and "Toplam maliyet 0,98 $" in h
    # C5: uzun 200, kısa 100 ⇒ net +100; brüt 300 = %30 kasa; teminat 300 / 3 = 100 = %10 özsermaye (1004); BTC 200 / (0,30 × 1000 = 300) = %67 doluluk
    assert "+100,00 $" in h and "%30" in h and "~100,00 $ (3x)" in h and "width:67%" in h


def test_pano_kadro_motorun_uyguladigi_ilk_kadro_satiri():
    from copytrade.canli import pano
    a1, a2, kadro, ozet, hesap, saha, kayit = _c_veri()
    ilk = 1_793_863_000_000                                                       # kadro["kosu_ms"] = en son kadro
    saha_ayni = {**saha, "gun_kadro": {"gun": "2026-11-05", "kadro": {"kosu_ms": ilk}}}
    h1 = pano.html_olustur(ozet, {}, hesap, kayit, [], 1_793_900_000_000, kadro, saha_ayni)
    assert "Motor bugün" in h1 and "kadrosunu uyguluyor." in h1 and "ikinci kadro" not in h1
    saha_ilk = {**saha, "gun_kadro": {"gun": "2026-11-05", "kadro": {"kosu_ms": ilk - 6 * 3_600_000}}}              # motor 6 saat önceki (ilk) kadroyu uyguluyor
    h2 = pano.html_olustur(ozet, {}, hesap, kayit, [], 1_793_900_000_000, kadro, saha_ilk)
    assert "günün ilk kadrosu" in h2 and "en son kadro" in h2 and "saha kararlarını değiştirmez" in h2
    assert "Motor bugün" not in pano.html_olustur(ozet, {}, hesap, kayit, [], 1_793_900_000_000, kadro, saha)       # gun_kadro yoksa satır yok
