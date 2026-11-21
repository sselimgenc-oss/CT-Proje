"""Alınmayan sinyal kaydı (counterfactual): yalnız muhasebe. Elle hesaplanmış altın örnekler; ağsız."""
import json

import pytest

from copytrade.canli import izleme
from copytrade.canli import pano
from copytrade.canli import telegram as tg
from tests.test_canli_motor import SAAT, adr, kayitlar, kur, olay

HIP3 = "xyz:GOLD"


def hazir(tmp_path, **k):
    m, hl, saat, tgp = kur(tmp_path, **k)
    m.baslat()
    m.hesap_tr[adr(1)] = {"deger": 100_000.0, "ms": saat()}
    return m, saat, tgp


def test_altin_hayali_pnl():
    assert izleme.hayali_pnl("B", 100.0, 100.0, 110.0) == pytest.approx(10.0)
    assert izleme.hayali_pnl("A", 100.0, 100.0, 110.0) == pytest.approx(-10.0)
    assert izleme.hayali_pnl("B", 100.0, 0.0, 110.0) == 0.0


def test_atlanan_acilis_hayali_pozisyon_ve_trader_kapaninca_kapanir(tmp_path):
    m, saat, _ = hazir(tmp_path)
    s = m.olay_isle(olay("a:1", adr(1), HIP3, "B", 300, 100.0, 0.0, saat))
    assert [(x.karar, x.neden) for x in s] == [("atlandi", "liste_disi")]
    assert m.hesap.sz(adr(1), HIP3) == 0.0                          # karar yolu değişmedi: emir yok
    # hedef = slot (1000/11) × 30.000 / 100.000 = 27,2727 $
    k = m.karsi_olgu[f"{adr(1)}|{HIP3}"]
    assert k["hayali_usd"] == pytest.approx(1000 / 11 * 0.3) and k["yon"] == "B" and k["giris"] == 100.0
    m.marks[HIP3] = 110.0
    m.karsi_olgu_adimi(saat())
    assert m.karsi_olgu[f"{adr(1)}|{HIP3}"]["son_pnl"] == pytest.approx(1000 / 11 * 0.3 * 0.1)      # 2,7273 $
    saat.ms += 2 * SAAT
    m.olay_isle(olay("a:2", adr(1), HIP3, "A", 300, 110.0, 300.0, saat))                     # trader kapatır
    m.karsi_olgu_adimi(saat())
    assert not m.karsi_olgu
    e = kayitlar(tmp_path, "karsi_olgu_kapandi")[0]
    assert (e["coin"], e["neden"], e["yon"], e["kapanis"]) == (HIP3, "liste_disi", "B", "trader_kapadi")
    assert e["hayali_usd"] == pytest.approx(27.27, abs=0.01) and e["pnl_usd"] == pytest.approx(2.7273, abs=1e-4) and e["sure_sa"] == pytest.approx(2.0)
    assert m.karsi_olgu_gun["liste_disi"] == [1, pytest.approx(2.7273, abs=1e-4)]


def test_kisa_yon_ve_sure_dolunca_kapanir(tmp_path):
    m, saat, _ = hazir(tmp_path)
    m.olay_isle(olay("a:1", adr(1), HIP3, "A", 300, 100.0, 0.0, saat))
    m.marks[HIP3] = 90.0                                              # kısa, fiyat düştü → kâr
    m.karsi_olgu_adimi(saat() + 71 * SAAT)
    assert len(m.karsi_olgu) == 1                                     # 72 saat dolmadı
    m.karsi_olgu_adimi(saat() + 72 * SAAT)
    e = kayitlar(tmp_path, "karsi_olgu_kapandi")[0]
    assert e["yon"] == "A" and e["kapanis"] == "sure_doldu" and e["pnl_usd"] == pytest.approx(1000 / 11 * 0.3 * 0.1, abs=1e-4) and e["sure_sa"] == pytest.approx(72.0)


def test_kalici_ve_en_cok_500_acik(tmp_path):
    m, saat, _ = hazir(tmp_path)
    m.olay_isle(olay("a:1", adr(1), HIP3, "B", 300, 100.0, 0.0, saat))
    m.durum_yaz()
    kayitli = json.loads((tmp_path / "durum" / "motor.json").read_text())["karsi_olgu"]
    assert list(kayitli) == [f"{adr(1)}|{HIP3}"]
    for i in range(600):
        m.karsi_olgu[f"x{i}|C{i}"] = {"yon": "B", "hayali_usd": 1.0, "giris": 1.0, "neden": "n", "ms": saat(), "son_pnl": 0.0}
    n = len(m.karsi_olgu)
    m.olay_isle(olay("a:3", adr(1), "xyz:SILVER", "B", 300, 100.0, 0.0, saat))
    assert len(m.karsi_olgu) == n                                     # sınır aşılmaz: yeni eklenmez


def test_hata_karar_yolunu_bozmaz(tmp_path):
    m, saat, _ = hazir(tmp_path)

    def patla(*a, **k):
        raise RuntimeError("boom")
    m._karsi_olgu_ac = patla
    s = m.olay_isle(olay("a:1", adr(1), HIP3, "B", 300, 100.0, 0.0, saat))
    assert s[0].neden == "liste_disi"
    assert kayitlar(tmp_path, "karsi_olgu_hata")[0]["tur"] == "RuntimeError"


def test_gunluk_ozet_ve_ozet_md_satiri(tmp_path):
    metin = tg.msg_gunluk("sanal", 1000.0, 1000.0, 1000.0, 0, 1, 11, [], None, {"liste_disi": [2, 3.5], "min_alti": [1, -1.0]})
    assert "Alınmayan sinyal" in metin and "3 kapandı" in metin and "+2,50 $" in metin and "coin listesi dışı 2/+3,50" in metin and "liste_disi" not in metin and "min_alti" not in metin      # 19.11 orkestratör: günlük mesajda kod adı yok, sade etiket
    assert "Alınmayan" not in tg.msg_gunluk("sanal", 1000.0, 1000.0, 1000.0, 0, 1, 11, [], None, None)
    simdi = 1_800_000_000_000
    ev = [{"olay": "karsi_olgu_kapandi", "zaman_ms": simdi - 1000, "neden": "liste_disi", "pnl_usd": 3.5}, {"olay": "karsi_olgu_kapandi", "zaman_ms": simdi - 2000, "neden": "min_alti", "pnl_usd": -1.0}]
    md, _ = pano.pano_olustur({"kasa_usd": 1000.0, "ozsermaye_usd": 1000.0}, {}, {}, ev, [], [], simdi)
    assert "Alınmayan sinyaller" in md and "2 kapandı" in md and "liste_disi 1" in md
    m, saat, tgp = hazir(tmp_path)
    m.karsi_olgu_gun = {"liste_disi": [1, 2.0]}
    gun_ms = (saat() // 86_400_000 + 1) * 86_400_000 + (int(m.rules["canli_ozet_saat_utc"]) + 1) * 3_600_000
    m._gunluk_ozet(gun_ms)
    assert any("Alınmayan sinyal" in x for x in m.tg.gonderilen) and m.karsi_olgu_gun == {}


def _hedef_sabit(m, usd=100.0):
    """Hedef nosyoneli sabit (test): her coin için hayali pozisyon açılabilsin; trader durumu bağımsız."""
    m._hedef_usd = lambda adres, coin, mk: usd


def _saat_basi(saat):
    """Şu anın bir sonraki tam saat başı (ms): kova sınırı testleri için."""
    return (saat() // SAAT + 1) * SAAT


def test_slot_tavani_ayni_saatte_tek_kayit(tmp_path):
    m, saat, _ = hazir(tmp_path)
    _hedef_sabit(m)
    h0 = _saat_basi(saat)
    saat.ms = h0 + 60_000                                             # saat başından 1 dk sonra
    o = olay("a:1", adr(1), HIP3, "B", 300, 100.0, 0.0, saat)
    for _ in range(3):
        m._karsi_olgu_ac(o, adr(1), "slot_tavani")
    assert len(m.karsi_olgu) == 1
    assert list(m.karsi_olgu) == [f"{adr(1)}|{HIP3}|slot_tavani|{h0 // SAAT}"]


def test_slot_tavani_sonraki_saatte_ikinci_kayit(tmp_path):
    m, saat, _ = hazir(tmp_path)
    _hedef_sabit(m)
    h0 = _saat_basi(saat)
    o = olay("a:1", adr(1), HIP3, "B", 300, 100.0, 0.0, saat)
    saat.ms = h0 + 60_000
    m._karsi_olgu_ac(o, adr(1), "slot_tavani")
    m._karsi_olgu_ac(o, adr(1), "slot_tavani")
    saat.ms = h0 + SAAT + 60_000                                      # bir sonraki saat dilimi
    m._karsi_olgu_ac(o, adr(1), "slot_tavani")
    assert len(m.karsi_olgu) == 2


def test_diger_neden_hala_adres_coin_basina_tek_kayit(tmp_path):
    m, saat, _ = hazir(tmp_path)
    _hedef_sabit(m)
    h0 = _saat_basi(saat)
    o = olay("a:1", adr(1), HIP3, "B", 300, 100.0, 0.0, saat)
    for dilim in range(3):
        saat.ms = h0 + dilim * SAAT + 60_000
        m._karsi_olgu_ac(o, adr(1), "liste_disi")
    assert list(m.karsi_olgu) == [f"{adr(1)}|{HIP3}"]                 # 2 parçalı anahtar, tek kayıt


def test_sik_azami_sinirı_ve_diger_neden_etkilenmez(tmp_path):
    m, saat, _ = hazir(tmp_path, kurallar={"karsi_olgu_sik_azami": 2})
    _hedef_sabit(m)
    for coin in (HIP3, "xyz:SILVER", "xyz:OIL"):                       # üçü de aynı saat dilimi
        m._karsi_olgu_ac(olay("a:1", adr(1), coin, "B", 300, 100.0, 0.0, saat), adr(1), "slot_tavani")
    assert len(m.karsi_olgu) == 2                                     # sık azami 2: üçüncüsü eklenmez
    m._karsi_olgu_ac(olay("a:1", adr(1), HIP3, "B", 300, 100.0, 0.0, saat), adr(1), "liste_disi")
    assert f"{adr(1)}|{HIP3}" in m.karsi_olgu and len(m.karsi_olgu) == 3   # sık dolsa da diğer neden yazılır


def test_sik_kapanis_ve_eski_iki_parcali_anahtar(tmp_path):
    m, saat, _ = hazir(tmp_path)
    _hedef_sabit(m)
    m.poz_tr[adr(1)] = {HIP3: 5.0}                                    # trader pozisyonda: açık kalır
    m._karsi_olgu_ac(olay("a:1", adr(1), HIP3, "B", 300, 100.0, 0.0, saat), adr(1), "slot_tavani")
    m.karsi_olgu_adimi(saat())
    assert len(m.karsi_olgu) == 1
    m.poz_tr[adr(1)] = {HIP3: 0.0}                                    # trader kapattı → 4 parçalı anahtar kapanır
    m.karsi_olgu_adimi(saat())
    assert not m.karsi_olgu
    e = kayitlar(tmp_path, "karsi_olgu_kapandi")[0]
    assert (e["coin"], e["neden"], e["kapanis"]) == (HIP3, "slot_tavani", "trader_kapadi")
    # eski (2 parçalı) kalıcı anahtar hâlâ yüklenip kapanır
    m.karsi_olgu[f"{adr(1)}|{HIP3}"] = {"yon": "B", "hayali_usd": 10.0, "giris": 100.0, "neden": "liste_disi", "ms": saat(), "son_pnl": 0.0}
    m.karsi_olgu_adimi(saat())
    assert not m.karsi_olgu
    assert kayitlar(tmp_path, "karsi_olgu_kapandi")[1]["coin"] == HIP3
