"""K-75 (kullanıcı kararı 20.11): SANAL kipte kaçan açılış telafisi + yeniden başlatmada kapanış yakalama. Ağsız; elle hesaplanmış altın örnekler.
Kasa 1.000 → slot 90,909 $; trader hesap 100.000 $, 300 BTC × 100 $ = 30.000 $ (oran 0,30) → hedef 27,27 $ (tek emir tavanı 1,5 × slot)."""
from __future__ import annotations

import pytest

from copytrade.canli import motor as mt
from copytrade.kurallar import load_rules
from tests.test_canli_motor import SAAT, SahteHL, adr, kayitlar, kur, olay


@pytest.fixture(autouse=True)
def _maske_temizle():
    yield
    mt.MASKE.clear()


class HLGiris(SahteHL):
    """`clearinghouseState` pozisyonlarına `entryPx` ekler (trader ortalama giriş fiyatı)."""
    def __init__(self, *a, giris=None, **k):
        super().__init__(*a, **k)
        self.giris = giris or {}

    def __call__(self, y):
        r = super().__call__(y)
        if y["type"] == "clearinghouseState":
            for ap in r["assetPositions"]:
                c = ap["position"]["coin"]
                if c in self.giris:
                    ap["position"]["entryPx"] = str(self.giris[c])
        return r


def _acilis_dolumu(saat, adres=1, coin="BTC", sz=300.0, once_ms=3 * SAAT, bas=0.0, px="100"):
    return {"time": saat() - once_ms, "coin": coin, "px": px, "sz": str(sz), "side": "B", "startPosition": str(bas), "tid": 1, "dir": "Open Long"}


def _hazir(tmp_path, giris=100.0, poz=300.0, dolumlar="varsayilan", **kurallar):
    hl = HLGiris(pozlar={adr(1): {"BTC": poz}}, giris={"BTC": giris})
    m, hl, saat, tgp = kur(tmp_path, hl=hl, kurallar=kurallar)
    hl.rest = {adr(1): [_acilis_dolumu(saat)] if dolumlar == "varsayilan" else dolumlar}
    m.baslat()
    m._tgp = tgp
    return m, hl, saat


def _telafi_emirleri(tmp_path):
    return [e for e in kayitlar(tmp_path, "emir") if e["boyut_neden"] == "kacan_telafi"]


def test_yaml_varsayilanlari():
    r = load_rules()
    assert r["sanal_kacan_acilis_telafi"] is True and r["kacan_telafi_kayma"] == 0.01 and r["kacan_telafi_max_saat"] == 24


def test_kayma_icinde_acilir_boyut_normal_yolla_ve_kayit(tmp_path):
    """Trader girişi 100, mark 100 (kayma 0) → telafi: 27,27 $ (hedef tabanlı, normal açılışla aynı); emir `boyut_neden` kacan_telafi; `açıldı` Telegram mesajı."""
    m, hl, saat = _hazir(tmp_path)
    assert m.hesap.sz(adr(1), "BTC") == 0.0
    m.dakika()
    e = _telafi_emirleri(tmp_path)
    assert len(e) == 1 and e[0]["eylem"] == "ac" and e[0]["usd_istenen"] == pytest.approx(27.2727, abs=1e-3) and e[0]["telafi_boyut_neden"] == "tamam"
    assert e[0]["telafi_trader_giris"] == 100.0 and e[0]["telafi_kayma"] == 0.0 and e[0]["telafi_yas_sa"] == pytest.approx(3.0)
    assert m.hesap.sz(adr(1), "BTC") == pytest.approx(0.272727, abs=1e-5)
    assert any(x["karar"] == "emir" for x in kayitlar(tmp_path, "kacan_telafi"))
    assert any(x.startswith("🟢 BTC LONG açıldı") for x in m._tgp.gonderilen)


def test_sinirda_acar_yuzde_1_aleyhte(tmp_path):
    """Long: trader girişi 99, mark 100 → kayma +%1,0101 (aleyhimize) → AÇILMAZ; giriş 99,01 → +%0,99 → açılır; lehimize (giriş 105 → −%4,8) açılır."""
    m, _, _ = _hazir(tmp_path / "a", giris=99.0)
    m.dakika()
    assert m.hesap.sz(adr(1), "BTC") == 0.0
    m2, _, _ = _hazir(tmp_path / "b", giris=99.01)
    m2.dakika()
    assert m2.hesap.sz(adr(1), "BTC") > 0
    m3, _, _ = _hazir(tmp_path / "c", giris=105.0)
    m3.dakika()
    assert m3.hesap.sz(adr(1), "BTC") > 0


def test_yuzde_1_5_aleyhte_acilmaz(tmp_path):
    """Trader girişi 98,5, mark 100 → +%1,52 aleyhimize: emir yok; atlama kaydı `kayma_fazla`; sonraki senkronda aynı neden tekrar yazılmaz."""
    m, _, saat = _hazir(tmp_path, giris=98.5)
    m.dakika()
    assert m.hesap.sz(adr(1), "BTC") == 0.0 and not kayitlar(tmp_path, "emir")
    a = kayitlar(tmp_path, "kacan_telafi_atlandi")
    assert len(a) == 1 and a[0]["neden"] == "kayma_fazla" and a[0]["kayma"] == pytest.approx(100 / 98.5 - 1, abs=1e-5)
    saat.ms += 600_000
    m.dakika()
    assert len(kayitlar(tmp_path, "kacan_telafi_atlandi")) == 1


def test_short_yon_kayma_isareti(tmp_path):
    """Short trader (girişi 100): mark 98,5 → bizim satışımız trader'dan %1,5 DÜŞÜK = aleyhimize → açılmaz; mark 101 (trader'dan yüksek sattık) = lehimize → açılır."""
    hl = HLGiris(mids={"BTC": "98.5", "ETH": "2000", "SOL": "100"}, pozlar={adr(1): {"BTC": -300.0}}, giris={"BTC": 100.0})
    m, hl, saat, _ = kur(tmp_path / "s", hl=hl)
    hl.rest = {adr(1): [{**_acilis_dolumu(saat), "side": "A"}]}
    m.baslat()
    m.dakika()
    assert m.hesap.sz(adr(1), "BTC") == 0.0
    hl2 = HLGiris(mids={"BTC": "101", "ETH": "2000", "SOL": "100"}, pozlar={adr(1): {"BTC": -300.0}}, giris={"BTC": 100.0})
    m2, hl2, saat2, _ = kur(tmp_path / "s2", hl=hl2)
    hl2.rest = {adr(1): [{**_acilis_dolumu(saat2), "side": "A"}]}
    m2.baslat()
    m2.dakika()
    assert m2.hesap.sz(adr(1), "BTC") < 0


def test_pozisyon_24_saatten_eski_acilmaz(tmp_path):
    """Pencerede (24 sa) açılış dolumu yok: hiç dolum yok ya da açılış 25 sa önce → pozisyon eski, telafi yok."""
    m, hl, saat = _hazir(tmp_path / "a", dolumlar=[])
    m.dakika()
    assert m.hesap.sz(adr(1), "BTC") == 0.0 and kayitlar(tmp_path / "a", "kacan_telafi_atlandi")[0]["neden"] == "pozisyon_eski"
    m2, hl2, saat2 = _hazir(tmp_path / "b")
    hl2.rest = {adr(1): [_acilis_dolumu(saat2, once_ms=25 * SAAT)]}
    m2.dakika()
    assert m2.hesap.sz(adr(1), "BTC") == 0.0 and kayitlar(tmp_path / "b", "kacan_telafi_atlandi")[0]["neden"] == "pozisyon_eski"
    m3, hl3, saat3 = _hazir(tmp_path / "c")
    hl3.rest = {adr(1): [_acilis_dolumu(saat3, once_ms=23 * SAAT)]}
    m3.dakika()
    assert m3.hesap.sz(adr(1), "BTC") > 0


def test_artirilmis_pozisyonun_yasi_ilk_acilistan(tmp_path):
    """Açılış 5 sa önce, artırma 1 sa önce (startPosition 100): yaş = 5 sa → açılır; yaş telafi_yas_sa alanında."""
    hl = HLGiris(pozlar={adr(1): {"BTC": 300.0}}, giris={"BTC": 100.0})
    m, hl, saat, _ = kur(tmp_path, hl=hl)
    hl.rest = {adr(1): [_acilis_dolumu(saat, sz=100.0, once_ms=5 * SAAT), {**_acilis_dolumu(saat, sz=200.0, once_ms=1 * SAAT, bas=100.0), "tid": 2}]}
    m.baslat()
    m.dakika()
    assert _telafi_emirleri(tmp_path)[0]["telafi_yas_sa"] == pytest.approx(5.0)


def test_filtre_atlamisti_saygi(tmp_path):
    """Trader açılışı rejim filtresiyle atlanmıştı (`son_atla` = rejim_ters, açılıştan SONRA) → telafi açmaz; `gec_acilis` ile atlanan ise telafi edilir."""
    m, _, saat = _hazir(tmp_path / "a")
    m.son_atla[f"{adr(1)}|BTC"] = ["rejim_ters", saat() - 2 * SAAT]
    m.dakika()
    assert m.hesap.sz(adr(1), "BTC") == 0.0
    assert kayitlar(tmp_path / "a", "kacan_telafi_atlandi")[0]["neden"] == "filtre_atlamisti:rejim_ters"
    m2, _, saat2 = _hazir(tmp_path / "b")
    m2.son_atla[f"{adr(1)}|BTC"] = ["gec_acilis", saat2() - 2 * SAAT]
    m2.dakika()
    assert m2.hesap.sz(adr(1), "BTC") > 0 and f"{adr(1)}|BTC" not in m2.son_atla
    m3, _, saat3 = _hazir(tmp_path / "c")                                      # açılıştan ÖNCEKİ (eski pozisyon dönemine ait) atlama yok sayılır
    m3.son_atla[f"{adr(1)}|BTC"] = ["rejim_ters", saat3() - 10 * SAAT]
    m3.dakika()
    assert m3.hesap.sz(adr(1), "BTC") > 0


def test_hip3_eski_atlamasi_yeniden_denenir(tmp_path):
    """K-73 öncesi `hip3_atlandi` atlaması telafiye engel değildir (açılış yine güncel kurallardan geçer)."""
    m, _, saat = _hazir(tmp_path)
    m.son_atla[f"{adr(1)}|BTC"] = ["hip3_atlandi", saat() - 2 * SAAT]
    m.dakika()
    assert m.hesap.sz(adr(1), "BTC") > 0


def test_k73_filtreleri_telafide_de_gecerli(tmp_path):
    """Filtre kaydı olmasa bile açılış yolundaki K-73 filtreleri telafide aynen çalışır (aynı `_emir_isle`): rejim ters → emir yok; nedeni `son_atla`ya yazılır, sonraki senkron tekrar denemez."""
    m, _, saat = _hazir(tmp_path)
    m.rejim_anlik = {"gecerli_son_ms": saat() + 10_000_000, "rejimler": {"BTC": {"1d": "trend_down", "4h": "trend_down"}}}
    m.dakika()
    assert m.hesap.sz(adr(1), "BTC") == 0.0
    assert [x for x in kayitlar(tmp_path, "emir_yok") if x["neden"] == "rejim_ters"] and m.son_atla[f"{adr(1)}|BTC"][0] == "rejim_ters"
    saat.ms += 600_000
    m.dakika()
    assert len([x for x in kayitlar(tmp_path, "emir_yok") if x["neden"] == "rejim_ters"]) == 1


def test_gercek_kipte_telafi_yok(tmp_path):
    """Gerçek kip: bayrak true olsa bile `kacan_telafi` 0 döner, ağ okuması bile yapılmaz."""
    m, hl, saat = _hazir(tmp_path)
    m.kip = "gercek"
    n = len(hl.istekler)
    assert m.kacan_telafi(saat()) == 0 and len(hl.istekler) == n and not _telafi_emirleri(tmp_path)


def test_bayrak_kapaliysa_yok(tmp_path):
    m, _, _ = _hazir(tmp_path, sanal_kacan_acilis_telafi=False)
    m.dakika()
    assert m.hesap.sz(adr(1), "BTC") == 0.0


def test_zaten_tutulan_pozisyona_dokunmaz_ve_tekrar_acmaz(tmp_path):
    m, _, saat = _hazir(tmp_path)
    m.dakika()
    sz = m.hesap.sz(adr(1), "BTC")
    saat.ms += 600_000
    m.dakika()
    assert m.hesap.sz(adr(1), "BTC") == pytest.approx(sz) and len(_telafi_emirleri(tmp_path)) == 1


def test_son_atlama_nedeni_motor_json_ile_kalici(tmp_path):
    """Atlama nedeni (`son_atla`) `motor.json`.da kalıcıdır: yeniden başlatmada filtre atlamasına saygı sürer."""
    m, hl, saat = _hazir(tmp_path, giris=98.5)
    m.dakika()                                                                     # kayma fazla → açılmadı
    m.son_atla[f"{adr(1)}|BTC"] = ["slot_tavani", saat()]
    m.durum_yaz()
    m2, _, _, _ = kur(tmp_path, hl=hl, saat=saat)
    assert m2.son_atla[f"{adr(1)}|BTC"][0] == "slot_tavani"


# ---------------------------------------------------------------- kapanış yakalama (yeniden başlatma)
def test_yeniden_baslatmada_trader_kapattiysa_ilk_dakikada_kapanir(tmp_path):
    """Trader biz kapalıyken (dolum kaçtı, 60 dk penceresinden eski) kapattı: yeni süreç ilk `dakika()`'da (senkron aralığı beklenmez, `_son` boş) REST'te pozisyon 0 görür → `senkron_kapanis` + teyitli kapanış."""
    hl = HLGiris(pozlar={adr(1): {"BTC": 300.0}}, giris={"BTC": 100.0})
    m, hl, saat, _ = kur(tmp_path, hl=hl)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    assert m.hesap.sz(adr(1), "BTC") > 0
    m.durum_yaz()
    saat.ms += 3 * SAAT                                                            # biz kapalıyız; trader bu sürede kapattı
    hl.pozlar = {adr(1): {}}
    m2, _, _, _ = kur(tmp_path, hl=hl, saat=saat)
    m2.baslat()
    m2.dakika()                                                                    # yeniden başlatmanın ilk dakikası
    assert m2.hesap.sz(adr(1), "BTC") == pytest.approx(0.0, abs=1e-9)
    assert kayitlar(tmp_path, "senkron_kapanis")
    k = [e for e in kayitlar(tmp_path, "emir") if e["eylem"] == "kapat"]
    assert k and k[-1]["reduce_only"] is True and k[-1]["boyut_neden"] != "kacan_telafi"


# ---------------------------------------------------------------- 429 düzeltmesi: önbellek, bütçe, geri çekilme
class HLSay(HLGiris):
    """`userFillsByTime` çağrılarını sayar; `hata429` doluysa o okumalarda RateLimitError fırlatır."""
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.dolum_okuma = 0
        self.hata429 = False

    def __call__(self, y):
        if y["type"] == "userFillsByTime":
            self.dolum_okuma += 1
            if self.hata429:
                raise mt.RateLimitError("429")
        return super().__call__(y)


def _say_hazir(tmp_path, pozlar=None, **kurallar):
    pozlar = pozlar or {"BTC": 300.0}
    hl = HLSay(pozlar={adr(1): pozlar}, giris={"BTC": 100.0, "ETH": 2000.0, "SOL": 100.0})
    m, hl, saat, _ = kur(tmp_path, hl=hl, kurallar=kurallar)
    hl.rest = {adr(1): [_acilis_dolumu(saat, coin=c) for c in pozlar]}
    m.baslat()
    for c in pozlar:                                                   # filtre atlaması: yaş okunur ama pozisyon AÇILMAZ (sayımlar sonraki senkronlarda da geçerli kalsın)
        m.son_atla[f"{adr(1)}|{c}"] = ["rejim_ters", saat() + 10**9]
    hl.dolum_okuma = 0
    return m, hl, saat


def test_yaml_telafi_429_varsayilanlari():
    r = load_rules()
    assert r["kacan_telafi_okuma_max"] == 3 and r["kacan_telafi_geri_cekil_sn"] == 300 and r["kacan_telafi_dolum_ttl_dk"] == 30


def test_yas_onbellek_ikinci_senkronda_okuma_yok(tmp_path):
    """Pozisyon açık kaldıkça yaş önbellekten gelir: ikinci senkronda ek dolum okuması YOK."""
    m, hl, saat = _say_hazir(tmp_path)
    m.kacan_telafi(saat())
    ilk = hl.dolum_okuma
    assert ilk == 1
    for ms in (600_000, 1_200_000):
        m.kacan_telafi(saat() + ms)
    assert hl.dolum_okuma == ilk


def test_yas_onbellek_pozisyon_kapaninca_gecersiz(tmp_path):
    """Trader pozisyonu 0'a inince (ya da yön değiştirince) önbellek silinir: yeniden açılınca taze okunur."""
    m, hl, saat = _say_hazir(tmp_path, kacan_telafi_dolum_ttl_dk=0)
    m.kacan_telafi(saat())
    assert hl.dolum_okuma == 1 and f"{adr(1)}|BTC" in m._telafi_yas
    m.poz_tr[adr(1)]["BTC"] = 0.0
    m.kacan_telafi(saat() + 1000)
    assert f"{adr(1)}|BTC" not in m._telafi_yas
    m.poz_tr[adr(1)]["BTC"] = -300.0                                   # ters yön
    m.kacan_telafi(saat() + 2000)
    assert hl.dolum_okuma == 2 and m._telafi_yas[f"{adr(1)}|BTC"][0] == -1


def test_dolum_ttl_onbellegi_ayni_adreste_ikinci_coin_icin_okumaz(tmp_path):
    """Aynı adresin iki coini: dolum geçmişi tek okunur (TTL içinde)."""
    m, hl, saat = _say_hazir(tmp_path, pozlar={"BTC": 300.0, "ETH": 5.0})
    m.kacan_telafi(saat())
    assert hl.dolum_okuma == 1


def test_senkron_basina_butce_3(tmp_path):
    """Dolum önbelleği kapalı (TTL 0), 4 aday coin → senkron başına en çok 3 okuma (varsayılan); kalan sonraki senkronda okunur."""
    m, hl, saat = _say_hazir(tmp_path, pozlar={"BTC": 300.0, "ETH": 5.0, "SOL": 300.0, "DOGE": 1000.0}, kacan_telafi_dolum_ttl_dk=0)
    m.marks["DOGE"] = 0.1
    hl.giris["DOGE"] = 0.1
    m.kacan_telafi(saat())
    assert hl.dolum_okuma == 3 and len(m._telafi_yas) == 3
    m.kacan_telafi(saat() + 600_000)
    assert hl.dolum_okuma == 4 and len(m._telafi_yas) == 4            # ilk üçü önbellekten; yalnız kalan 1 okundu


def test_429_geri_cekil_300_sonra_600_basari_sifirlar(tmp_path):
    """429 → telafi 300 sn durur (tek olay, aday başına değil); süre dolunca yine 429 → 600 sn; başarı sayacı sıfırlar (sonraki 429 yine 300)."""
    m, hl, saat = _say_hazir(tmp_path, pozlar={"BTC": 300.0, "ETH": 5.0, "SOL": 300.0}, kacan_telafi_dolum_ttl_dk=0)
    t0 = saat()
    hl.hata429 = True
    m.kacan_telafi(t0)
    gc = kayitlar(tmp_path, "kacan_telafi_geri_cekil")
    assert len(gc) == 1 and gc[0]["sn"] == 300 and hl.dolum_okuma == 1                  # sıkı döngü yok: ilk 429'da durdu
    m.kacan_telafi(t0 + 299_000)
    assert hl.dolum_okuma == 1 and len(kayitlar(tmp_path, "kacan_telafi_geri_cekil")) == 1   # geri çekilme sürüyor: okuma yok
    m.kacan_telafi(t0 + 301_000)
    gc = kayitlar(tmp_path, "kacan_telafi_geri_cekil")
    assert len(gc) == 2 and gc[1]["sn"] == 600 and hl.dolum_okuma == 2
    hl.hata429 = False
    m.kacan_telafi(t0 + 301_000 + 599_000)
    assert hl.dolum_okuma == 2                                                          # 600 sn dolmadı
    m.kacan_telafi(t0 + 301_000 + 601_000)
    assert hl.dolum_okuma > 2 and m._telafi_ardisik_429 == 0                            # başarı: sıfırlandı
    hl.hata429 = True
    m._telafi_yas.clear()
    t1 = t0 + 2_000_000
    m.kacan_telafi(t1)
    assert kayitlar(tmp_path, "kacan_telafi_geri_cekil")[-1]["sn"] == 300


def test_geri_cekil_tavan_1_saat(tmp_path):
    m, hl, saat = _say_hazir(tmp_path, kacan_telafi_dolum_ttl_dk=0)
    hl.hata429 = True
    t = saat()
    for _ in range(8):
        t = max(t, m._telafi_geri_bit_ms) + 1
        m.kacan_telafi(t)
    assert [e["sn"] for e in kayitlar(tmp_path, "kacan_telafi_geri_cekil")][-1] == 3600
