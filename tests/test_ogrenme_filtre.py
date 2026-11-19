"""CT ortak öğrenme parça 2: karne/drift raporu, ML filtresi (yalnız atlar, model yoksa geçirir), eğitim takvimi ve veri koruması. Ağsız."""
import json
from datetime import datetime, timezone

import pytest

from copytrade.canli import ogrenme_adaptor as oa
from copytrade.canli import pano
from copytrade.canli.hesap import Hesap
from copytrade.ortak_ogrenme.kayit import Aday, aday_to_dict
from tests.test_canli_motor import SAAT, adr, kayitlar, kur, olay

GUN = 86_400_000


def ms(g, s=12, ay=1):
    return int(datetime(2027, ay, g, s, tzinfo=timezone.utc).timestamp() * 1000)


def yeni(tmp_path, **kural):
    olaylar, mesajlar = [], []
    o = oa.Ogrenme({**kural}, tmp_path / "ogr", "sanal", lambda: ms(19), olaylar.append, mesajlar.append)
    return o, olaylar, mesajlar


def yaz_adaylar(o, alias, n, ozellik_fn, r_fn, ilk_ms=None):
    ilk = ilk_ms or ms(1)
    for i in range(n):
        a = Aday(id=f"{alias}:{i}", proje="CT", kurulum=alias, enstruman="BTC/USD", varlik_sinifi="kripto", yon="long",
                 ts=datetime.fromtimestamp((ilk + i * 3_600_000) / 1000, tz=timezone.utc), alindi=True, r=r_fn(i), seans="open", ozellikler=ozellik_fn(i))
        oa._ekle_satir(o.adaylar_yolu, aday_to_dict(a))


def ayrik(o, alias, n=60):
    """trader_kaldirac 10 → kayıp, 2 → kazanç (ayrılabilir, dengeli): yüksek kaldıraçlı açılış düşük puan alır."""
    yaz_adaylar(o, alias, n, lambda i: {"trader_kaldirac": 2.0 if i % 2 else 10.0}, lambda i: 1.0 if i % 2 else -1.0)


@pytest.fixture(autouse=True)
def _numpy():
    pytest.importorskip("numpy")


# ---------------------------------------------------------------- filtre: veri koruması, eğitim, atlama
def test_az_veri_egitilmez_ve_model_yoksa_her_sey_gecer(tmp_path):
    o, olaylar, _ = yeni(tmp_path)
    alias = oa.takma_ad(adr(1))
    ayrik(o, alias, n=49)                                                        # ogrenme_filtre_min_n = 50
    o.filtre_egit(ms(19))
    assert not (o.filtre_dizin).exists() and not [e for e in olaylar if e["olay"] == "ml_filtre_egitildi"]
    assert o.filtre_kontrol(adr(1), "BTC", ms(19), {"trader_kaldirac": 10.0}) is None
    assert [e for e in olaylar if e["olay"] == "ml_filtre_yok"][0]["neden"] == "model_yok_ya_da_suresi_dolmus"
    o.filtre_kontrol(adr(1), "ETH", ms(19, 13), {"trader_kaldirac": 10.0})
    assert len([e for e in olaylar if e["olay"] == "ml_filtre_yok"]) == 1       # 6 saat içinde tekrar yazılmaz


def test_egitilir_dusuk_puan_atlanir_yuksek_gecer(tmp_path):
    o, olaylar, _ = yeni(tmp_path)
    alias = oa.takma_ad(adr(1))
    ayrik(o, alias)
    o.filtre_egit(ms(19))
    ev = [e for e in olaylar if e["olay"] == "ml_filtre_egitildi"]
    assert len(ev) == 1 and ev[0]["n_egitim"] == 60 and ev[0]["taban_oran"] == 0.5
    assert list(o.filtre_dizin.glob("*.json")) and "0x" not in "".join(p.read_text() for p in o.filtre_dizin.glob("*.json"))
    skip = o.filtre_kontrol(adr(1), "BTC", ms(19), {"trader_kaldirac": 10.0})
    assert skip and skip["puan"] < skip["esik"]
    assert o.filtre_kontrol(adr(1), "ETH", ms(19), {"trader_kaldirac": 2.0}) is None
    assert [e for e in olaylar if e["olay"] == "ml_filtre_atla"][0]["kurulum"] == alias
    assert o.filtre_kontrol(adr(2), "BTC", ms(19), {"trader_kaldirac": 10.0}) is None      # başka trader: modeli yok → geçer


def test_tek_sinif_egitilmez(tmp_path):
    o, olaylar, _ = yeni(tmp_path)
    yaz_adaylar(o, oa.takma_ad(adr(1)), 60, lambda i: {"trader_kaldirac": 3.0}, lambda i: 1.0)
    o.filtre_egit(ms(19))
    assert not o.filtre_dizin.exists() and [e for e in olaylar if e["olay"] == "ml_filtre_egitilmedi"]


def test_model_suresi_dolunca_filtre_kendiliginden_kapanir(tmp_path):
    o, olaylar, _ = yeni(tmp_path)
    ayrik(o, oa.takma_ad(adr(1)))
    o.filtre_egit(ms(19))
    assert o.filtre_kontrol(adr(1), "BTC", ms(19), {"trader_kaldirac": 10.0})
    assert o.filtre_kontrol(adr(1), "BTC", ms(19) + 22 * GUN, {"trader_kaldirac": 10.0}) is None       # 21 gün doldu: geçirir
    assert [e for e in olaylar if e["olay"] == "ml_filtre_yok"]


def test_egitim_takvimi_haftalik_ve_hafta_degisiminde(tmp_path):
    o, olaylar, _ = yeni(tmp_path)
    ayrik(o, oa.takma_ad(adr(1)))
    egitildi = lambda: len([e for e in olaylar if e["olay"] == "ml_filtre_egitildi"])      # noqa: E731
    o.filtre_egit(ms(19))
    assert egitildi() == 1
    o.filtre_egit(ms(19) + 3 * GUN)
    assert egitildi() == 1                                                       # 3 gün < 7: yeniden eğitilmez
    o.filtre_egit(ms(19) + 8 * GUN)
    assert egitildi() == 2                                                       # 8 gün ≥ 7 (21 günlük son kullanmadan çok önce)
    o.hafta_degisti()
    o.filtre_egit(ms(19) + 9 * GUN)
    assert egitildi() == 3 and o.uyg["egit_zorla"] is False                      # kadro değişimi zorlar, bayrak düşer
    assert (o.filtre_dizin / f"{oa.takma_ad(adr(1))}.prev.json").exists()        # önceki model yedeği


def test_numpy_yoksa_filtre_kapali_motor_calisir(tmp_path, monkeypatch):
    o, olaylar, _ = yeni(tmp_path)
    ayrik(o, oa.takma_ad(adr(1)))
    monkeypatch.setattr(oa.Ogrenme, "_filtre_modul", staticmethod(lambda: None))
    o.adim(ms(19))
    assert not o.filtre_dizin.exists() and not [e for e in olaylar if e["olay"] == "ogrenme_hata"]
    assert o.filtre_kontrol(adr(1), "BTC", ms(19), {"trader_kaldirac": 10.0}) is None
    assert [e for e in olaylar if e["olay"] == "ml_filtre_yok"][0]["neden"] == "numpy_yok"


def test_filtre_kapatma_anahtari_ve_gercek_kip(tmp_path):
    o, _, _ = yeni(tmp_path, ogrenme_filtre_aktif=False)
    ayrik(o, oa.takma_ad(adr(1)))
    o.filtre_egit(ms(19))
    assert not o.filtre_dizin.exists() and o.filtre_kontrol(adr(1), "BTC", ms(19), {"trader_kaldirac": 10.0}) is None
    g = oa.Ogrenme({}, tmp_path / "g", "gercek", lambda: ms(19))
    assert g.filtre_kontrol(adr(1), "BTC", ms(19), {}) is None


# ---------------------------------------------------------------- eğitim satırı: yalnız karar anı özellikleri (sızıntı yok)
def test_aday_ozellikleri_karar_ani_ve_sonuc_bilgisi_icermez(tmp_path):
    o, _, _ = yeni(tmp_path)
    h = Hesap(1000.0, 3.0)
    h.dinleyici = o.dolum
    o.filtre_kontrol(adr(1), "BTC", ms(15, 8), {"trader_hesap_usd": 100_000.0, "trader_poz_usd": 30_000.0, "trader_kaldirac": 4.0})
    h.uygula(adr(1), "BTC", "B", 1.0, 100.0, 0.0, ms(15, 8))
    h.uygula(adr(1), "BTC", "A", 1.0, 110.0, 0.0, ms(15, 10))
    a = json.loads(o.adaylar_yolu.read_text(encoding="utf-8"))
    assert a["ozellikler"] == {"kaldirac": 3.0, "saat_utc": 8.0, "hafta_gunu": 4.0, "hafta_sonu": 0.0, "trader_hesap_log10": 5.0, "trader_poz_oran": 0.3, "trader_kaldirac": 4.0}
    assert "maks_nosyonel_usd" not in a["ozellikler"] and a["cikis"]["maks_nosyonel_usd"] == 100.0       # sonuç sonrası bilgi yalnız `cikis`te


# ---------------------------------------------------------------- karne + drift
def test_karne_pano_ve_drift_uyarisi_bir_kez(tmp_path):
    o, olaylar, mesaj = yeni(tmp_path)
    alias = "T_aaaaaa"
    yaz_adaylar(o, alias, 20, lambda i: {}, lambda i: -1.5)                      # 20. işlemde CUSUM alarmı
    o.karne_guncelle(ms(19))
    satir = o.pano()[0]
    assert satir["kurulum"] == alias and satir["alinan"] == 20 and satir["ort_r"] == -1.5 and satir["drift"] == "uyari" and satir["filtre"] is False
    assert satir["kasa"] == pytest.approx(1000 * 0.985 ** 20, abs=0.01)
    assert json.loads(o.karne_yolu.read_text(encoding="utf-8"))["karne"][alias]["alinan"] == 20
    assert [e["olay"] for e in olaylar].count("kurulum_drift") == 1 and len(mesaj) == 1 and "UYARI" in mesaj[0] and alias in mesaj[0]
    o.karne_guncelle(ms(19, 14))
    assert [e["olay"] for e in olaylar].count("kurulum_drift") == 1 and len(mesaj) == 1        # aynı alarm tekrar bildirilmez
    md, _ = pano.pano_olustur({"kasa_usd": 1000.0, "ozsermaye_usd": 1000.0, "ogrenme": o.pano()}, {}, {}, [], [], [], ms(19))
    assert "## Ortak öğrenme karnesi" in md and alias in md and "uyari" in md and "0x" not in md


def test_adim_hata_sarmasi_alt_adimlar_ayri(tmp_path, monkeypatch):
    o, olaylar, _ = yeni(tmp_path)

    def patla(*a):
        raise RuntimeError("boom")
    monkeypatch.setattr(o, "degerlendir", patla)
    cagri = []
    monkeypatch.setattr(o, "karne_guncelle", lambda s: cagri.append(s))
    o.adim(ms(19))
    assert [e["asama"] for e in olaylar if e["olay"] == "ogrenme_hata"] == ["degerlendirme"] and cagri == [ms(19)]      # ders hatası karneyi engellemez


# ---------------------------------------------------------------- motor entegrasyonu
def test_motor_ml_filtresi_atlar_karsi_olguya_yazar_kapanis_serbest(tmp_path):
    """Trader adr(1): Cuma açılışları (hafta_sonu=0) hep kayıp, hafta sonu kazanç → model kurulur. Motor Cuma 09:00'da açılışı ATLAR; sayaç/`emir_yok`/alınmayan sinyal kaydı oluşur."""
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    o = m.ogrenme
    alias = oa.takma_ad(adr(1))
    yaz_adaylar(o, alias, 60, lambda i: {"hafta_sonu": 1.0 if i % 2 else 0.0}, lambda i: 1.0 if i % 2 else -1.0)
    o.filtre_egit(saat())
    s = m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    assert s[0].karar == "atlandi" and s[0].neden == "ml_filtre_atla" and m.hesap.sz(adr(1), "BTC") == 0.0
    assert kayitlar(tmp_path, "ml_filtre_atla") and f"{adr(1)}|BTC" in m.karsi_olgu and m.karsi_olgu[f"{adr(1)}|BTC"]["neden"] == "ml_filtre_atla"
    assert m.sayac["emir"] == 0
    # filtre kapatılınca aynı açılış geçer: filtre yalnız atlar, boyutu değiştirmez (golden: 27,2727 $)
    o.k["ogrenme_filtre_aktif"] = False
    m.olay_isle(olay("a:2", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    assert kayitlar(tmp_path, "emir")[0]["usd_istenen"] == pytest.approx(27.2727, abs=1e-4)
    # açık pozisyonun KAPANIŞI hiçbir koşulda filtrelenmez
    o.k["ogrenme_filtre_aktif"] = True
    k = m.olay_isle(olay("a:3", adr(1), "BTC", "A", 300, 100.0, 300.0, saat))
    assert k[0].eylem == "kapat" and k[0].karar == "emir"


def test_motor_pano_ek_ogrenme_satiri(tmp_path):
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    assert m.pano_ek()["ogrenme"] is None
    yaz_adaylar(m.ogrenme, "T_bbbbbb", 3, lambda i: {}, lambda i: 1.0)
    m.ogrenme.karne_guncelle(saat())
    assert m.pano_ek()["ogrenme"][0]["kurulum"] == "T_bbbbbb"
    assert SAAT > 0
