"""CT haftalık veri paketi (`copytrade/canli/hafta_paketi.py`): altın çıktı, eksik girdi uyarıları, Pazar-bir-kez koruması, kanca, yayım betikleri. Ağsız (radar okuyucu sahte)."""
from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from copytrade.canli import gunluk_ozet as go
from copytrade.canli import hafta_paketi as hp
from copytrade.canli import motor as mt
from tests.test_gunluk_ozet import _motor

ROOT = Path(__file__).resolve().parent.parent
PAZAR = date(2026, 11, 23)                                               # rapor günü Pazartesi


@pytest.fixture(autouse=True)
def _maske_temizle():
    yield
    mt.MASKE.clear()


def _ms(y, a, g, s, d=0):                                          # UTC -> ms
    return int(datetime(y, a, g, s, d, tzinfo=UTC).timestamp() * 1000)


OZET = {"sema": "ortak.gunluk_ozet.v1", "uretim": "2026-11-22T18:05:00Z", "gun": "2026-11-22", "mod": "sanal",
        "kasa": {"baslangic": 10000.0, "simdi": 10050.0, "gun_pnl": 5.0, "toplam_pnl": 50.0, "zirveden_dusus_yuzde": 0.7},
        "islem": {"acik_pozisyon": 12},
        "ogrenme": {"aktif_ders": 2, "yeni_ders": 0, "emekli_ders": 1, "filtre_aktif": True, "filtre_atlanan": 4, "filtre_karsi_olgu_pnl": -3.5, "ders_kucultulen": 2, "ders_engellenen": 1},
        "saglik": {"hata_sayisi_gun": 0, "ram_mb": 90.0, "ram_tepe_mb": 120.5, "disk_bos_gb": 60.0, "yeniden_baslama_1s": 1, "oom_son": False},
        "kopya_kalite": {"n": 40, "gecikme_ms_medyan": 500.0, "gecikme_ms_p90": 900.0, "kayma_bps_medyan": 0.1, "kayma_bps_p90": 2.0}}
REJIM = {"tablolar": {"rejim_1d": [{"etiket": "range", "n": 4, "kazanan": 3, "isabet_yuzde": 75.0, "toplam_pnl": 8.0, "ortalama_pnl": 2.0}], "rejim_4h": [], "duygu": []}}
SECIM = {"toplu": {"durum": "tamam", "gun_n": 3, "rho_ort": 0.12, "p": 0.31},
         "gunler": [{"gun": "2026-11-21", "durum": "tamam", "kopyalanan_n": 5, "kadro_n": 11, "rho": 0.2, "p": 0.2, "toplam_net_pnl": 4.0}]}
KURAL = {"vurgu": {"slot_tavani": {"olay_adedi": 900, "trader_sayisi": 8, "toplam_karsi_olgu_pnl": 12.5, "karsi_olgu_kapanan_pnl": 10.0, "karsi_olgu_acik_pnl": 2.5, "hayali_nosyonel": 5000.0}},
         "satirlar": [{"neden": "slot_tavani", "olay_adedi": 900, "trader_sayisi": 8, "toplam_karsi_olgu_pnl": 12.5, "hayali_nosyonel": 5000.0}]}
RADAR = [{"tarih": "2026-11-21", "gruplar": {"ilk11": {"n": 10, "ortalama": 0.01, "kar_orani": 0.6}},
          "rastgele_karsilastirma": {"durum": "tamam", "rastgele_medyan": 0.002, "yuzdelik": 80.0, "p": 0.2}}]
GECMIS = {"2026-11-16": {"oz": 10000.0, "filtre_atlanan": 3, "filtre_kp": 1.0, "ders_kucultulen": 1, "ders_engellenen": 0, "kk_n": 30, "gecikme_med": 480.0, "gecikme_p90": 800.0,
                         "kayma_med": 0.0, "kayma_p90": 1.0, "ram_tepe": 100.0, "rb": {"10": 0, "11": 1}, "oom": False, "oom_olculdu": True}}


def _dosyalar(d: Path, **ekle):
    d.mkdir(parents=True, exist_ok=True)
    for ad, v in {"gunluk_ozet_v1.json": OZET, "rejim_sonuc_v1.json": REJIM, "secim_gercek_v1.json": SECIM, "kural_maliyet_v1.json": KURAL, **ekle}.items():
        if v is not None:
            (d / ad).write_text(json.dumps(v), encoding="utf-8")


def test_altin_cikti_tam_girdi(tmp_path):
    _dosyalar(tmp_path)
    md = hp.olustur(tmp_path, PAZAR, RADAR, GECMIS)
    assert md.startswith("# CT haftalık veri paketi — 2026-11-23\n")
    basliklar = [s for s in md.splitlines() if s.startswith("## ")]
    assert [b[:5] for b in basliklar] == [f"## {i})" for i in range(1, 9)]
    assert "| sanal | 10000.00 | 10050.00 | +50.00 | +50.00 | 0.70 | 12 |" in md                      # haftalık = 10050 - 10000
    assert "| 2026-11-21 | 10 | +1.00 | 0.60 | +0.20 | 80 | 0.200 |" in md                            # radar
    assert "ρ = +0.120" in md and "| Rejim 1g | range | 4 | 75.0 | +8.00 | +2.00 |" in md
    assert md.index("**Slot tavanı:** 900 olay") < md.index("| slot_tavani |")                         # slot tavanı satırı ilk
    assert "| hafta (1 gün kayıtlı) | 3 | +1.00 | 1 | 0 |" in md and "| bugün | 4 | -3.50 | 2 | 1 |" in md
    assert "| 120.5 | 1 | yok |" in md
    assert "Kasa geçmişi 1/8 gün" in md                                                                 # kısmi geçmiş uyarısı
    assert "0x" not in md


def test_eksik_girdi_uyarilari(tmp_path):
    _dosyalar(tmp_path, **{"rejim_sonuc_v1.json": None, "secim_gercek_v1.json": None, "kural_maliyet_v1.json": None, "gunluk_ozet_v1.json": None})
    md = hp.olustur(tmp_path, PAZAR, None, {})
    for parca in ("gunluk_ozet_v1.json okunamadı", "radar verisi okunamadı", "secim_gercek_v1.json yok", "rejim_sonuc_v1.json yok", "kural_maliyet_v1.json yok"):
        assert parca in md
    assert len([s for s in md.splitlines() if s.startswith("## ")]) == 8                                # her bölüm yine de var
    assert "Eksik girdi yok" not in md
    assert "son 8 günde isabet dosyası yok" in hp.olustur(tmp_path, PAZAR, [], {})


def test_adres_maskelenir(tmp_path):
    _dosyalar(tmp_path, **{"kural_maliyet_v1.json": {"vurgu": {}, "satirlar": [{"neden": "x_0xabcdef1234", "olay_adedi": 1, "trader_sayisi": 1, "toplam_karsi_olgu_pnl": 0, "hayali_nosyonel": 0}]}})
    md = hp.olustur(tmp_path, PAZAR, RADAR, {})
    assert "0xabcdef" not in md and "[gizli]" in md


def test_pazar_tarihi_ve_cumartesi_bir_kez(tmp_path):
    assert hp.pazar_tarihi(_ms(2026, 11, 22, 18)) == PAZAR                                              # Paz 21:00 TSİ
    assert hp.pazar_tarihi(_ms(2026, 11, 23, 5)) == PAZAR                                               # Pzt 08:00 TSİ
    assert hp.yazilacak_mi(_ms(2026, 11, 22, 17, 59), tmp_path) is None                                 # 20:59 TSİ: erken
    assert hp.yazilacak_mi(_ms(2026, 11, 21, 18), tmp_path) is None                                     # Cumartesi
    assert hp.yazilacak_mi(_ms(2026, 11, 23, 12), tmp_path) is None                                     # Pazartesi 15:00 TSİ: geç
    assert hp.yazilacak_mi(_ms(2026, 11, 22, 18, 0), tmp_path) == PAZAR
    assert hp.yazilacak_mi(_ms(2026, 11, 23, 4), tmp_path) == PAZAR                                     # yakalama (Pazartesi 07:00 TSİ)
    (tmp_path / "CT_HAFTA_2026-11-23.md").write_text("x", encoding="utf-8")
    assert hp.yazilacak_mi(_ms(2026, 11, 22, 19), tmp_path) is None                                     # haftada bir


def test_kanca_yazar_bir_kez_ve_hata_yutulur(tmp_path, monkeypatch):
    m, saat = _motor(tmp_path)
    cagri = []
    monkeypatch.setattr(hp, "radar_oku", lambda rules, bitis, **k: cagri.append(bitis) or RADAR)
    saat.ms = _ms(2026, 11, 22, 18, 30)
    m._gunluk_ozet_yazim = None
    assert go.yaz_gerekirse(m) is True
    p = tmp_path / "durum" / "paylasim"
    assert (p / "CT_HAFTA_2026-11-23.md").read_text(encoding="utf-8").startswith("# CT haftalık veri paketi — 2026-11-23")
    assert (p / "CT_HAFTA_son.md").read_text(encoding="utf-8") == (p / "CT_HAFTA_2026-11-23.md").read_text(encoding="utf-8")
    assert (tmp_path / "durum" / "hafta_gecmis.json").exists() and len(cagri) == 1
    m._gunluk_ozet_yazim = None
    saat.ms += 3_600_000 + 1000
    go.yaz_gerekirse(m)
    assert len(cagri) == 1                                                                              # ikinci kez yazılmadı
    (p / "CT_HAFTA_2026-11-23.md").unlink()
    monkeypatch.setattr(hp, "olustur", lambda *a, **k: 1 / 0)
    m._gunluk_ozet_yazim = None
    assert go.yaz_gerekirse(m) is True                                                                  # günlük özet bozulmaz
    assert m.kayit.sayac.get("hafta_paketi_hata", 0) >= 1


def test_radar_oku_ag_hatasi_none(monkeypatch):
    import requests

    def patla(*a, **k):
        raise requests.ConnectionError("x")
    monkeypatch.setattr(requests, "get", patla)
    assert hp.radar_oku({"canli_kadro_repo": "a/b", "canli_kadro_dali": "radar"}, PAZAR) is None


def test_radar_oku_404_atlanir_ve_dosya_okunur(monkeypatch):
    import requests

    class R:
        def __init__(self, kod, d=None):
            self.status_code, self._d = kod, d

        def raise_for_status(self):
            pass

        def json(self):
            return self._d
    monkeypatch.setattr(requests, "get", lambda url, timeout: R(200, {"tarih": url.split("/")[-2]}) if "2026-11-21" in url else R(404))
    assert hp.radar_oku({"canli_kadro_repo": "a/b", "canli_kadro_dali": "radar"}, PAZAR) == [{"tarih": "2026-11-21"}]


def test_yayim_betikleri_hafta_dosyalarini_kopyalar():
    for yol in (".github/scripts/canli_yayimla.sh", "deploy/sanal_yayimla.sh"):
        assert "CT_HAFTA_*.md" in (ROOT / yol).read_text(encoding="utf-8")


def test_d11_haftalik_pnl_tam_7_gunu_kapsar_taban_pencereden_onceki_gun_sonu(tmp_path):
    _dosyalar(tmp_path)
    g = {"2026-11-15": {"oz": 9900.0}, "2026-11-16": {"oz": 10000.0}}                 # pencere Pzt 16 .. Paz 22; taban = Paz 15 gün sonu
    md = hp.olustur(tmp_path, PAZAR, RADAR, g)
    assert "| sanal | 10000.00 | 10050.00 | +50.00 | +150.00 |" in md                 # 10050 − 9900 (7 tam gün), 10000 değil
    assert "2026-11-15 sonrası" in md
