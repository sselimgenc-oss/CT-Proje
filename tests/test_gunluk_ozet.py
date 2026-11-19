"""Ortak günlük özet `durum/paylasim/gunluk_ozet_v1.json` (ortak.gunluk_ozet.v1): alanlar, sayımlar, takma ad, adres sızıntısı yok, mod, zamanlama, hata yutma, yayım betikleri."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from copytrade.canli import gunluk_ozet as go
from copytrade.canli import motor as mt
from copytrade.canli import telegram as tg
from copytrade.canli.ogrenme_adaptor import takma_ad
from tests.test_canli_motor import adr, kadro, kur, satir

ROOT = Path(__file__).resolve().parent.parent
ANAHTARLAR = ["sema", "proje", "uretim", "gun", "mod", "kasa", "islem", "hesaplar", "ogrenme", "rejim", "drift_uyari", "limitler", "saglik", "notlar"]


@pytest.fixture(autouse=True)
def _maske_temizle():
    yield
    mt.MASKE.clear()


def _motor(tmp_path):
    k = kadro([satir(1, 1), satir(2, 2)], 0)
    m, _hl, saat, _ = kur(tmp_path, kadro_=k)
    k["kosu_ms"] = saat() - 3_600_000
    m.baslat()
    return m, saat


def _emir(m, a, eylem, pnl, ucret=0.1, durum="dolu"):
    m.kayit({"olay": "emir", "adres": adr(a), "coin": "BTC", "eylem": eylem, "durum": durum, "pnl_usd": pnl, "ucret": ucret})


def test_sema_ve_sayimlar(tmp_path):
    m, saat = _motor(tmp_path)
    _emir(m, 1, "ac", None)
    _emir(m, 1, "ac", None, durum="red")                          # dolmadı: sayılmaz
    _emir(m, 1, "kapat", 5.0)
    _emir(m, 2, "kapat", -2.0)
    _emir(m, 2, "azalt", 1.0)                                      # azaltma kapanış sayılmaz
    m.kayit({"olay": "emir_yok", "adres": adr(1), "coin": "ETH"})
    m.kayit({"olay": "adim_hata", "adim": "x"})
    o = go.olustur(m, {})
    assert list(o)[:len(ANAHTARLAR)] == ANAHTARLAR and o["sema"] == "ortak.gunluk_ozet.v1" and o["proje"] == "CT" and o["mod"] == "sanal"
    assert o["islem"] == {"gun_acilan": 1, "gun_kapanan": 2, "kazanan": 1, "kaybeden": 1, "acik_pozisyon": 0, "alinmayan_sinyal": 1}
    assert o["saglik"]["hata_sayisi_gun"] == 1 and o["saglik"]["son_nabiz"] == o["uretim"]
    h = {x["ad"]: x for x in o["hesaplar"]}
    assert set(h) == {takma_ad(adr(1)), takma_ad(adr(2))}
    assert h[takma_ad(adr(1))]["gun_pnl"] == pytest.approx(5.0 - 0.2) and h[takma_ad(adr(1))]["islem"] == 2
    assert h[takma_ad(adr(2))]["gun_pnl"] == pytest.approx(-2.0 + 1.0 - 0.2)
    assert o["kasa"]["baslangic"] == 1000.0 and o["kasa"]["simdi"] == 1000.0 and o["kasa"]["toplam_pnl"] == 0.0
    assert o["limitler"]["kaldirac_tavan"] == 5 and o["limitler"]["durdu_mu"] is False and o["limitler"]["gunluk_kayip_yuzde"] > 0
    assert o["rejim"] is None and o["drift_uyari"] is False and len(o["notlar"]) <= 5


def test_adres_sizintisi_yok_ve_dur_notu_maskelenir(tmp_path):
    m, _ = _motor(tmp_path)
    _emir(m, 1, "kapat", 1.0)
    m.risk.dur, m.risk.dur_neden = True, f"elle {adr(7)}"
    s = json.dumps(go.olustur(m, {}), ensure_ascii=False)
    assert "0x" not in s and "[gizli]" in s
    assert go.olustur(m, {})["limitler"]["durdu_mu"] is True


def test_kasa_alanlari_gun_pnl_ve_dusus(tmp_path):
    m, saat = _motor(tmp_path)
    m.risk.ozsermaye_isle(1000.0, saat())
    m.risk.zirve = 1100.0
    m.hesap.kapanmis_net = -50.0                                   # özsermaye 950
    m.risk.ozsermaye_isle(950.0, saat())
    k = go.olustur(m, {})["kasa"]
    assert k["simdi"] == 950.0 and k["toplam_pnl"] == -50.0 and k["gun_pnl"] == -50.0 and k["zirveden_dusus_yuzde"] == pytest.approx(13.64)


def test_rejim_drift_ogrenme(tmp_path):
    m, _ = _motor(tmp_path)
    m.rejim_anlik = {"rejimler": {"BTC": {"4h": "trend_yukari"}}}
    m.kopya_drift = {"ETH": {"bas_ms": 1, "aktif": True}}
    o = go.olustur(m, {})
    assert o["rejim"] == "trend_yukari" and o["drift_uyari"] is True
    assert o["ogrenme"]["filtre_aktif"] is True and o["ogrenme"]["aktif_ders"] is None             # ders.json yok → null
    gun = o["gun"]
    (m.ogrenme.dizin).mkdir(parents=True, exist_ok=True)
    m.ogrenme.ders_yolu.write_text(json.dumps({"a": {"status": "alive", "born": gun}, "b": {"status": "alive", "born": "2000-01-01"}, "c": {"status": "retired", "born": "2000-01-01"}}), encoding="utf-8")
    etki = ("filtre_atlanan", "filtre_karsi_olgu_pnl", "ders_kucultulen", "ders_engellenen")      # öğrenme etkisi alanları ayrı testte (aşağıda)
    assert {k: v for k, v in go.olustur(m, {})["ogrenme"].items() if k != "filtre_aktif" and k not in etki} == {"aktif_ders": 2, "yeni_ders": 1, "emekli_ders": 1}


def test_ogrenme_etki_sayimlari_ve_ozet_alanlari(tmp_path):
    m, _ = _motor(tmp_path)
    for _ in range(3):
        m.kayit({"olay": "ml_filtre_atla", "kurulum": "T_aaaaaa", "coin": "BTC"})
    m.kayit({"olay": "karsi_olgu_kapandi", "neden": "ml_filtre_atla", "pnl_usd": -10.0})
    m.kayit({"olay": "karsi_olgu_kapandi", "neden": "ml_filtre_atla", "pnl_usd": -2.5})
    m.kayit({"olay": "karsi_olgu_kapandi", "neden": "hip3_atlandi", "pnl_usd": 50.0})          # ML değil: sayılmaz
    m.kayit({"olay": "emir_yok", "neden": "ders_emekli", "eylem": "ac"})
    m.kayit({"olay": "emir_yok", "neden": "ders_emekli", "eylem": "artir"})
    m.kayit({"olay": "emir_yok", "neden": "bant_ici", "eylem": "ac"})                          # ders değil: sayılmaz
    beklenen = {"filtre_atlanan": 3, "filtre_karsi_olgu_pnl": -12.5, "ders_kucultulen": None, "ders_engellenen": 2}
    assert go.gunluk_etki(m) == beklenen
    og = go.olustur(m, {})["ogrenme"]
    assert {k: og[k] for k in beklenen} == beklenen and og["filtre_aktif"] is True


def test_ogrenme_etki_kapanmamis_karsi_olgu_null(tmp_path):
    m, _ = _motor(tmp_path)
    m.kayit({"olay": "ml_filtre_atla", "kurulum": "T_aaaaaa", "coin": "BTC"})                  # skip var, kapanan karşı-olgu yok
    assert go.gunluk_etki(m)["filtre_karsi_olgu_pnl"] is None and go.gunluk_etki(m)["filtre_atlanan"] == 1


def test_ogrenme_satiri_ve_gunluk_rapor(tmp_path):
    assert tg.ogrenme_satiri({"filtre_atlanan": 3, "filtre_karsi_olgu_pnl": -12.0, "ders_kucultulen": None, "ders_engellenen": 0}) == "🧠 Öğrenme: filtre 3 sinyal atladı (karşı-olgu −12,00 $)"
    assert tg.ogrenme_satiri({"filtre_atlanan": 0, "filtre_karsi_olgu_pnl": None, "ders_kucultulen": None, "ders_engellenen": 1}) == "🧠 Öğrenme: ders 1 işlemi engelledi"
    assert tg.ogrenme_satiri({"filtre_atlanan": 0, "filtre_karsi_olgu_pnl": None, "ders_kucultulen": None, "ders_engellenen": 0}) is None
    assert tg.ogrenme_satiri(None) is None
    ozet = {"filtre_atlanan": 3, "filtre_karsi_olgu_pnl": -12.0, "ders_kucultulen": None, "ders_engellenen": 0}
    metin = tg.msg_gunluk("sanal", 1000.0, 1000.0, 1000.0, 0, 1, 11, [], None, None, ozet)
    assert "🧠 Öğrenme: filtre 3 sinyal atladı (karşı-olgu −12,00 $)" in metin.splitlines()
    assert "Öğrenme" not in tg.msg_gunluk("sanal", 1000.0, 1000.0, 1000.0, 0, 1, 11, [], None, None, None)
    assert "Öğrenme" not in tg.msg_gunluk("sanal", 1000.0, 1000.0, 1000.0, 0, 1, 11, [], None, None, {"filtre_atlanan": 0, "filtre_karsi_olgu_pnl": None, "ders_kucultulen": None, "ders_engellenen": 0})


@pytest.mark.parametrize("kip,ortam,beklenen", [
    ("gercek", {"SUNUCU_MOD": "deneme"}, "canli"), ("sanal", {}, "sanal"), ("sanal", {"SUNUCU_MOD": "deneme"}, "deneme"),
    ("sanal", {"SUNUCU_MOD": "uretim", "VERI_DALI": "canli-durum"}, "sanal"), ("sanal", {"VERI_DALI": "canli-durum"}, "sanal"), ("sanal", {"VERI_DALI": "canli-durum-deneme"}, "deneme"),
])
def test_mod(kip, ortam, beklenen):
    assert go.mod_belirle(kip, ortam) == beklenen


def test_durum_yaz_yazar_saatlik_ve_gunluk_rapor_aninda(tmp_path):
    m, saat = _motor(tmp_path)
    yol = tmp_path / "durum" / "paylasim" / "gunluk_ozet_v1.json"
    m.durum_yaz()
    ilk = json.loads(yol.read_text(encoding="utf-8"))
    assert ilk["proje"] == "CT"
    yol.unlink()
    m.durum_yaz()
    assert not yol.exists()                                        # < 1 saat, rapor günü değişmedi: yazılmaz
    m._ozet_gunu = "2099-01-01"                                    # günlük Telegram raporu gönderildi
    m.durum_yaz()
    assert yol.exists()
    yol.unlink()
    saat.ms += 3_600_000 + 1000
    m.durum_yaz()
    assert yol.exists()


def test_hata_yutulur_ve_kayit(tmp_path, monkeypatch):
    m, _ = _motor(tmp_path)
    monkeypatch.setattr(go, "olustur", lambda *a, **k: 1 / 0)
    m._gunluk_ozet_yazim = None
    assert go.yaz_gerekirse(m) is False
    m.durum_yaz()                                                  # yükseltmez
    assert m.kayit.sayac.get("gunluk_ozet_hata", 0) >= 1


def test_yayim_betikleri_dosyayi_kopyalar():
    for yol in (".github/scripts/canli_yayimla.sh", "deploy/sanal_yayimla.sh"):
        s = (ROOT / yol).read_text(encoding="utf-8")
        assert "kadro_yon_v1.json" in s and "gunluk_ozet_v1.json" in s


def test_saglik_kaynak_alanlari_eklendi(tmp_path):
    m, _ = _motor(tmp_path)
    o = go.olustur(m)
    assert {"ram_mb", "ram_tepe_mb", "disk_bos_gb", "yuk_1dk"} <= set(o["saglik"]) and {"son_nabiz", "hata_sayisi_gun"} <= set(o["saglik"])
    m.durum_yaz()
    assert "kaynak" in json.loads((m.durum_dizin / "motor.json").read_text(encoding="utf-8"))
