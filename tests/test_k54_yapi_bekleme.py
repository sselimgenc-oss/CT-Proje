"""K-54 (kullanıcı kararı 09.11): yeni seçim yapısı (radar_surum; K-66: v3) yayımlanana kadar motor eski yapının kadrosunu UYGULAMAZ (saha boş, kasa nakitte)."""
from pathlib import Path

from copytrade.canli import motor as mt
from tests.test_canli_motor import SAAT, kadro, kayitlar, kur, satir

ROOT = Path(__file__).resolve().parents[1]


def test_radar_surum_dosyasi_v5_ve_donem_yeni():
    assert mt.radar_surum_oku() == "v5"                                                                       # K-85 (21.11): sade seçim v5; eski v4 / v3 kadrosu uygulanmaz
    assert (ROOT / "copytrade/canli/DONEM").read_text(encoding="utf-8").strip() == "2026-11-21T07:30:00Z"     # K-85 (21.11 10:30 TSİ): yeni sanal dönem 1.000 $; eski dönem verisi git geçmişinde


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
    assert sum("yeni seçim yapısı bekleniyor" in x.lower() for x in tgp.gonderilen) == 0          # Telegram sadeleştirme (20.11): rutin bilgi gitmez (kayıt var)
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


def test_sure_sn_yoksa_bos_kadroda_cikmaz_kadro_gelince_normal_calismaya_gecer(tmp_path, monkeypatch):
    """Sunucu `--sure-sn` vermez: boş/eski kadroda süreç çıkış 0 ile BİTMEZ (systemd yeniden başlatmaz, güncelleme geri alınırdı); kadro gelene dek bekler, gelince aynı süreçte dinleyiciyi başlatır.
    GERÇEK kurallar (`K86_GEVSEK` değil): `load_rules_asil`."""
    import asyncio

    from copytrade.kurallar import load_rules_asil
    asil = load_rules_asil()
    m, _, saat, _ = kur(tmp_path, kurallar={k: v for k, v in asil.items() if k.startswith(("canli_", "kopya_", "net_yon")) or k == "radar_saha_max"})
    m.radar_surum_gerekli = "v5"
    bos = {**kadro([], saat() - SAAT), "radar_surum": "v4"}                    # eski sürüm: uygulanmaz
    m.kadro_oku = lambda: bos
    uyunan, basladi = [], []

    async def uyku(sn):
        uyunan.append(sn)
        saat.ms += int(sn * 1000)
        if len(uyunan) == 6:
            m.kadro_oku = lambda: {**kadro([satir(1, 1)], saat() - SAAT), "radar_surum": "v5"}

    class SahteDin:
        def __init__(self, *a, **k):
            pass

        def durdur(self):
            pass

        async def calis(self):
            basladi.append(sorted(m.saha.uyeler))

        def ozet(self):
            return {"genel": {}}
    monkeypatch.setattr(mt, "CanliDinleyici", SahteDin)
    ozet = asyncio.run(mt.calis(m, None, uyku=uyku))
    assert len(uyunan) == 6 and len(basladi) == 1 and len(m.saha.uyeler) == 1          # 6 yoklama boyunca çıkmadı; kadro gelince dinleyici başladı
    assert not ozet.get("bekleme_vardiyasi") and kayitlar(tmp_path, "bekleme_bitti_kadro_geldi")
    assert m.saat_ms() > 0 and all(u == max(1.0, float(m.rules["canli_kadro_aralik_sn"])) for u in uyunan)
