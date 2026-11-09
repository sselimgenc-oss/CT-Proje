"""K-54 (kullanıcı kararı 09.11): yeni seçim yapısı (radar_surum v2) yayımlanana kadar motor eski yapının kadrosunu UYGULAMAZ (saha boş, kasa nakitte)."""
from pathlib import Path

from copytrade.canli import motor as mt
from tests.test_canli_motor import SAAT, kadro, kayitlar, kur, satir

ROOT = Path(__file__).resolve().parents[1]


def test_radar_surum_dosyasi_v2_ve_donem_yeni():
    assert mt.radar_surum_oku() == "v2"
    assert (ROOT / "copytrade/canli/DONEM").read_text(encoding="utf-8").strip() == "2026-11-09T18:01:00Z"     # 21:01 TSİ: eski yapı verisi panodan kalkar (git geçmişinde arşivli)


def test_radar_surum_oku_yorum_bos_yok(tmp_path):
    p = tmp_path / "RADAR_SURUM"
    assert mt.radar_surum_oku(p) is None
    p.write_text("# açıklama\n\n v3 \n", encoding="utf-8")
    assert mt.radar_surum_oku(p) == "v3"
    p.write_text("# yalnız yorum\n", encoding="utf-8")
    assert mt.radar_surum_oku(p) is None


def test_eski_surum_kadro_uygulanmaz_v2_uygulanir(tmp_path):
    m, _, saat, tgp = kur(tmp_path)
    m.radar_surum_gerekli = "v2"
    eski = {**kadro([satir(i, i, 90 - i) for i in range(1, 6)], saat() - SAAT), "radar_surum": "v1.1"}
    m._kadro_uygula((True, eski), saat())
    m._kadro_uygula((True, {k: v for k, v in eski.items() if k != "radar_surum"}), saat())      # alan yok (v1) da uygulanmaz
    assert m.saha.uyeler == {} and m._son_kadro is None
    bekle = kayitlar(tmp_path, "kadro_surum_bekleniyor")
    assert len(bekle) == 1 and bekle[0]["gerekli"] == "v2" and bekle[0]["gelen"] == "v1.1"          # günde bir kayıt
    assert sum("yeni seçim yapısı bekleniyor" in x for x in tgp.gonderilen) == 1
    yeni = {**eski, "radar_surum": "v2"}
    m._kadro_uygula((True, yeni), saat())
    assert len(m.saha.uyeler) == 5 and m._son_kadro is yeni
    m._kadro_uygula((True, eski), saat())                                   # sonradan gelen eski sürüm, uygulanan v2'yi bozmaz
    assert m._son_kadro is yeni and len(m.saha.uyeler) == 5


def test_kapali_iken_her_kadro_uygulanir(tmp_path):
    m, _, saat, _ = kur(tmp_path)
    assert m.radar_surum_gerekli is None
    m._kadro_uygula((True, kadro([satir(1, 1)], saat() - SAAT)), saat())
    assert len(m.saha.uyeler) == 1
