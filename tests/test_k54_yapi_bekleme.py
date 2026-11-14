"""K-54 (kullanıcı kararı 09.11): yeni seçim yapısı (radar_surum v2) yayımlanana kadar motor eski yapının kadrosunu UYGULAMAZ (saha boş, kasa nakitte)."""
from pathlib import Path

from copytrade.canli import motor as mt
from tests.test_canli_motor import SAAT, kadro, kayitlar, kur, satir

ROOT = Path(__file__).resolve().parents[1]


def test_radar_surum_dosyasi_v2_ve_donem_yeni():
    assert mt.radar_surum_oku() == "v2"
    assert (ROOT / "copytrade/canli/DONEM").read_text(encoding="utf-8").strip() == "2026-11-14T09:00:00Z"     # K-65 eki (14.11 12:00 TSİ): birleşik hesap paydası (emir teminatı) düzeltmesi sonrası yeni sanal dönem 600 $ / 3; eski dönem verisi git geçmişinde arşivli


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


def test_v2_bes_satirli_kadro_ilk_gun_bes_giris_cikan_k39_ile_duser(tmp_path):
    """Denetim 10: secim_d biçiminde 5 satırlık v2 kadrosu → ilk gün 5 giriş; bir üye kadrodan çıkınca iki farklı UTC gününde yoksa (K-39) motor düşürür."""
    m, _, saat, _ = kur(tmp_path, kurallar={"canli_islem_yok_saat": 1_000_000})   # işlem-yok düşmesi bu testin konusu değil
    m.radar_surum_gerekli = "v2"
    k1 = {**kadro([satir(i, i, 3.0) for i in range(1, 6)], saat() - SAAT), "radar_surum": "v2", "korelasyon": {"adresler": [], "gun_sayisi": 0, "matris": []}}
    m._kadro_uygula((True, k1), saat())
    assert len(m.saha.uyeler) == 5
    k2 = {**k1, "kosu_ms": k1["kosu_ms"] + 24 * SAAT, "satirlar": k1["satirlar"][:4]}
    k3 = {**k1, "kosu_ms": k1["kosu_ms"] + 48 * SAAT, "satirlar": k1["satirlar"][:4]}
    m._kadro_uygula((True, k2), k2["kosu_ms"] + SAAT)
    assert len(m.saha.uyeler) == 5                                           # ilk gün: yalnız işaretlenir
    m._kadro_uygula((True, k3), k3["kosu_ms"] + SAAT)
    assert len(m.saha.uyeler) == 4                                           # ikinci UTC günü: kadro_disi düşme


def test_bekleme_vardiyasi_cokmez_kadro_gelince_erken_biter(tmp_path):
    """09.11 18:01Z olayı: v2 kadro yokken saha boş → `calis` KipHatasi ile çöktü, vardiya zinciri koptu. Artık bekleme vardiyası: kadroyu yoklar, temiz biter."""
    import asyncio
    m, _, saat, _ = kur(tmp_path)
    m.radar_surum_gerekli = "v2"
    eski = {**kadro([satir(1, 1)], saat() - SAAT), "radar_surum": "v1.1"}
    m.kadro_oku = lambda: eski
    uyunan = []

    async def uyku(sn):
        uyunan.append(sn)
        if len(uyunan) == 2:
            m.kadro_oku = lambda: {**eski, "radar_surum": "v2"}

    ozet = asyncio.run(mt.calis(m, sure_sn=0))                               # süre 0: tek yoklama, gerçek uyku yok
    assert ozet["bekleme_vardiyasi"] is True
    ozet = asyncio.run(mt.bekleme_vardiyasi(m, 3600, uyku=uyku))
    assert ozet["kadro_geldi"] is True and len(uyunan) == 2 and len(m.saha.uyeler) == 1
    assert kayitlar(tmp_path, "bekleme_vardiyasi") and kayitlar(tmp_path, "bekleme_bitti_kadro_geldi")
