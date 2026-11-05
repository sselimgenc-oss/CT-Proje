"""T4b gerçek kip öncesi güvenlik maddeleri (lider kararı 05.11 akşam): #2 kısmi/iptal dolum miktarı, #3 atomik yazım + niyet oynatma + ÇÖKME testi, #6 kuyruktan düşen olay → `poz_tr`,
#7 `funding_oran_yok` sayacı. Ağsız; gerçek kip yalnız sahte borsa (`BorsaSim`) ile. Sayılar elle hesaplanmıştır."""
import asyncio
import json
import os

import pytest

from copytrade.canli import motor as mt
from copytrade.canli import niyet as ny
from tests.test_canli_motor import SAAT, adr, kayitlar, kur, olay
from tests.test_canli_t4b import BorsaSim, Cokus, kur_gercek  # noqa: F401 (Cokus: BaseException çökme benzetimi)


@pytest.fixture(autouse=True)
def _maske_temizle():
    yield
    mt.MASKE.clear()


def _niyet_kur(m, saat, eylem, yon, usd, kimlik="z:1"):
    cloid = ny.cloid_uret(kimlik, eylem)
    m.niyet.niyet_yaz(kimlik=kimlik, eylem=eylem, adres=adr(1), coin="BTC", yon=yon, usd=usd, reduce_only=eylem != "ac", cloid=cloid, ms=saat())
    return cloid


def _durum(sim, cloid, durum, orig, kalan, px="100"):
    sim.durumlar[cloid] = {"status": "order", "order": {"order": {"coin": "BTC", "side": "A", "limitPx": px, "sz": str(kalan), "origSz": str(orig), "oid": 9}, "status": durum}}


def _yeniden(tmp_path, monkeypatch, sim, saat):
    m2, *_ = kur_gercek(tmp_path, monkeypatch, sim, saat=saat)
    return m2


# ================================================================================================ #2 kısmi / iptal dolum
def test_iptal_edilmis_kismi_dolum_deftere_kismi_olarak_islenir_kalan_kuyruga(tmp_path, monkeypatch):
    """Defterde 0,5 BTC long. Azalt niyeti 40 $ (reduce-only satış). orderStatus: `canceled`, origSz 0,20, sz 0,05 → dolan 0,15 (limit 100 $) = 15 $. Defter 0,5 − 0,15 = 0,35.
    Kalan 40 − 15 = 25 $ ≥ 10 $ → kuyruğa: hedef 0,35 − 25/100 = 0,10 BTC. `kismi` sayacı 1."""
    sim = BorsaSim()
    m, sim, saat, _ = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    m.hesap.uygula(adr(1), "BTC", "B", 0.5, 100.0, 0.0, saat())
    cloid = _niyet_kur(m, saat, "azalt", "A", 40.0)
    m.durum_yaz()
    _durum(sim, cloid, "canceled", 0.20, 0.05)
    m2 = _yeniden(tmp_path, monkeypatch, sim, saat)
    m2.baslat()
    assert m2.hesap.sz(adr(1), "BTC") == pytest.approx(0.35)
    assert m2.sayac["kismi"] == 1
    e = m2.kapanis_kuyrugu[f"{adr(1)}|BTC"]
    assert e["tur"] == "azalt" and e["hedef_sz"] == pytest.approx(0.10) and not e.get("eksik")
    k = kayitlar(tmp_path, "niyet_sonucsuz")[-1]
    assert k["durum"] == "canceled" and k["dolan_sz"] == pytest.approx(0.15) and k["dolum"] == "kismi"


def test_kismi_azaltma_kalan_10_dolar_altindaysa_atlanir(tmp_path, monkeypatch):
    """Azalt 24 $; dolan 0,15 × 100 = 15 $ → kalan 9 $ < 10 $ (HL reduce-only alt sınırı): kuyruğa GİRMEZ, `min_nosyonel` sayılır, `kismi_azaltma_atlandi` kaydı."""
    sim = BorsaSim()
    m, sim, saat, _ = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    m.hesap.uygula(adr(1), "BTC", "B", 0.5, 100.0, 0.0, saat())
    cloid = _niyet_kur(m, saat, "azalt", "A", 24.0)
    m.durum_yaz()
    _durum(sim, cloid, "canceled", 0.20, 0.05)
    m2 = _yeniden(tmp_path, monkeypatch, sim, saat)
    m2.baslat()
    assert m2.hesap.sz(adr(1), "BTC") == pytest.approx(0.35)
    assert m2.kapanis_kuyrugu == {} and m2.sayac["min_nosyonel"] == 1
    assert kayitlar(tmp_path, "kismi_azaltma_atlandi")[-1]["kalan_usd"] == pytest.approx(9.0)


def test_tam_dolan_filled_dolu_sayilir_kismi_degil_ve_dolmayan_kapat_kuyruga_girer(tmp_path, monkeypatch):
    """filled + sz 0 → `dolu`, `kismi` sayacı 0, kuyruk boş. Hiç dolmamış (`canceled`, dolan 0) KAPAT niyeti: defter değişmez, pozisyon açıkta → kapanış kuyruğuna (tam kapanış)."""
    sim = BorsaSim()
    m, sim, saat, _ = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    m.hesap.uygula(adr(1), "BTC", "B", 0.5, 100.0, 0.0, saat())
    c1 = _niyet_kur(m, saat, "azalt", "A", 10.0, "z:1")
    m.durum_yaz()
    _durum(sim, c1, "filled", 0.10, 0.0)
    m2 = _yeniden(tmp_path, monkeypatch, sim, saat)
    m2.baslat()
    assert m2.hesap.sz(adr(1), "BTC") == pytest.approx(0.40) and m2.sayac["kismi"] == 0 and m2.kapanis_kuyrugu == {}
    assert kayitlar(tmp_path, "niyet_sonucsuz")[-1]["dolum"] == "dolu"
    c2 = _niyet_kur(m2, saat, "kapat", "A", 42.0, "z:2")
    m2.durum_yaz()
    _durum(sim, c2, "canceled", 0.40, 0.40)
    m3 = _yeniden(tmp_path, monkeypatch, sim, saat)
    m3.baslat()
    assert m3.hesap.sz(adr(1), "BTC") == pytest.approx(0.40) and m3.kapanis_kuyrugu[f"{adr(1)}|BTC"]["tur"] == "kapat"


# ================================================================================================ #3 atomik yazım + çökme
def test_yaz_atomik_dosya_ve_dizin_fsync_yapar(tmp_path, monkeypatch):
    cagri = []
    gercek = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (cagri.append(fd), gercek(fd))[1])
    mt._yaz(tmp_path / "x" / "hesap.json", {"a": 1})
    assert len(cagri) == 2                                                 # dosya + dizin
    assert json.loads((tmp_path / "x" / "hesap.json").read_text()) == {"a": 1} and not list((tmp_path / "x").glob("*.tmp"))


def _coktur_noktasi(m, nokta, monkeypatch):
    """Çökme noktaları: (a) sonuç satırı yazıldı, durum dosyaları HİÇ yazılmadı; (b) motor.json yazıldı, hesap.json yazılmadı; (c) hesap.json geçici dosyası yazıldı, os.replace'ten ÖNCE."""
    if nokta == "dosyalar_once":
        def f():
            raise Cokus()
        monkeypatch.setattr(m, "_dolum_yaz", f)
    elif nokta == "motor_sonra_hesap_once":
        asil = mt._yaz

        def y(yol, veri):
            if yol.name == "hesap.json":
                raise Cokus()
            return asil(yol, veri)
        monkeypatch.setattr(mt, "_yaz", y)
    else:
        gercek = os.replace

        def r(a, b, *x, **k):
            if str(b).endswith("hesap.json"):
                raise Cokus()
            return gercek(a, b, *x, **k)
        monkeypatch.setattr(os, "replace", r)


@pytest.mark.parametrize("nokta", ["dosyalar_once", "motor_sonra_hesap_once", "hesap_gecici_yazildi_replace_once"])
def test_cokme_dolum_sonrasi_durum_yazimi_arasinda_yeniden_baslatinca_hesap_tutarli(tmp_path, monkeypatch, nokta):
    """Trader 300 BTC açar → 27,27 $ = 0,27273 BTC (sz 5 hane). Emir borsada DOLDU, sonuç satırı yazıldı; sonra çökme (üç farklı nokta). Yeniden başlatınca hesap.json'daki işaretçiden sonraki
    sonuçlu niyet oynatılır: defter 0,27273 (kayıp yok); ikinci kez yeniden başlatmada AYNI değer (çift uygulama yok); ikinci emir yok; hesap.json her zaman geçerli JSON."""
    sim = BorsaSim()
    m, sim, saat, _ = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    m.durum_yaz()
    with monkeypatch.context() as mp:
        _coktur_noktasi(m, nokta, mp)
        with pytest.raises(Cokus):
            m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    json.loads((tmp_path / "durum" / "hesap.json").read_text())                 # yarım/bozuk dosya yok
    assert json.loads((tmp_path / "durum" / "hesap.json").read_text())["poz"] == {adr(1): {}}                      # henüz pozisyon yok (disk eski durumda)
    assert len(sim.siparisler) == 1 and [x["t"] for x in m.niyet.satirlar()] == ["niyet", "sonuc"]
    m2 = _yeniden(tmp_path, monkeypatch, sim, saat)
    m2.baslat()
    assert m2.hesap.sz(adr(1), "BTC") == pytest.approx(0.27273, abs=1e-9)
    assert kayitlar(tmp_path, "niyet_oynatildi")[-1]["sz"] == pytest.approx(0.27273)
    assert m2.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat)) == [] and len(sim.siparisler) == 1
    m3 = _yeniden(tmp_path, monkeypatch, sim, saat)
    m3.baslat()
    assert m3.hesap.sz(adr(1), "BTC") == pytest.approx(0.27273, abs=1e-9)         # ikinci yeniden başlatma: çift uygulama YOK
    assert m3.hesap.son_niyet_cloid == ny.cloid_uret("a:1", "ac")


def test_normal_calismada_isaretci_ilerler_yeniden_baslatma_cift_uygulamaz(tmp_path, monkeypatch):
    """Açılış (0,27273) + trader azaltması sonrası hesap.json her dolumda yazılır; işaretçi son niyet. Temiz yeniden başlatma: aynı defter (oynatma yok)."""
    sim = BorsaSim()
    m, sim, saat, _ = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    h = json.loads((tmp_path / "durum" / "hesap.json").read_text())             # durum_yaz çağrılmadan bile diskte
    assert h["son_niyet_cloid"] == ny.cloid_uret("a:1", "ac") and h["poz"][adr(1)]["BTC"]["sz"] == pytest.approx(0.27273)
    m.olay_isle(olay("a:2", adr(1), "BTC", "A", 150, 100.0, 300.0, saat))
    sz = m.hesap.sz(adr(1), "BTC")
    assert sz < 0.27273 and json.loads((tmp_path / "durum" / "motor.json").read_text())["islenen"][-1] == "a:2"
    m2 = _yeniden(tmp_path, monkeypatch, sim, saat)
    m2.baslat()
    assert m2.hesap.sz(adr(1), "BTC") == pytest.approx(sz) and not kayitlar(tmp_path, "niyet_oynatildi")


def test_eski_bicim_hesap_json_gecis_gecmisi_oynatmaz(tmp_path):
    """`son_niyet_cloid` alanı olmayan eski hesap.json: işaretçi niyet dosyasının sonuna çekilir; geçmiş niyetler deftere ikinci kez işlenmez."""
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    sz = m.hesap.sz(adr(1), "BTC")
    assert sz > 0
    yol = tmp_path / "durum" / "hesap.json"
    h = json.loads(yol.read_text())
    del h["son_niyet_cloid"]
    yol.write_text(json.dumps(h))
    m2, *_ = kur(tmp_path, saat=saat)
    m2.baslat()
    assert m2.hesap.sz(adr(1), "BTC") == pytest.approx(sz)


def test_sanal_kip_cokme_sonucsuz_niyet_oynatilmaz_emir_tekrarlanmaz(tmp_path):
    """Sanal kip: emir çağrısı sırasında çökme (sonuç satırı yok) → `sonucsuz`; defter değişmez; aynı dolum ikinci emir üretmez (K-37 §3 korunur)."""
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    m.durum_yaz()
    asil = m.yurutucu.emir

    def coktur(*a, **k):
        asil(*a, **k)
        raise Cokus()
    m.yurutucu.emir = coktur
    with pytest.raises(Cokus):
        m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    m2, *_ = kur(tmp_path, saat=saat)
    m2.baslat()
    assert m2.hesap.sz(adr(1), "BTC") == 0.0 and m2.sayac["emir"] == 0 and kayitlar(tmp_path, "niyet_sonucsuz")[-1]["durum"] == "sonucsuz"


# ================================================================================================ #6 kuyruktan düşen olay → poz_tr
def test_kuyruktan_dusen_olay_trader_pozisyon_tablosunu_gunceller(tmp_path):
    """Kuyruk 1 öğe. ETH açılışı doluyken BTC açılışı (300) düşer; tüketici `dusen_isle` ile `poz_tr[BTC] = 300` yazar, emir üretmez. Daha yeni dolum zaten işlendiyse (zaman damgası eski) ezmez."""
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    kuyruk = mt.OncelikliKuyruk(m.kapanis_mi, 1, saat)
    kuyruk.put_nowait((olay("a:1", adr(1), "ETH", "B", 10, 2000.0, 0.0, saat), True))
    dusen = olay("a:2", adr(1), "BTC", "B", 300, 100.0, 0.0, saat)
    kuyruk.put_nowait((dusen, True))
    assert list(kuyruk.dusenler) == [dusen] and kuyruk.dusen_acilis == 1
    m.dusen_isle(dusen)
    assert m.poz_tr[adr(1)]["BTC"] == 300.0 and m.sayac["emir"] == 0 and kayitlar(tmp_path, "dusen_olay_poz_tr")
    # eski zaman damgalı düşen olay, daha yeni işlenmiş duruma ezmez
    m.poz_tr[adr(1)]["BTC"] = 120.0
    m._poz_tr_ms[(adr(1), "BTC")] = dusen.zaman_ms + 10_000
    m.dusen_isle(dusen)
    assert m.poz_tr[adr(1)]["BTC"] == 120.0


def test_tuketici_dusen_olaylari_poz_trye_isler(tmp_path):
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()

    async def kos():
        kuyruk = mt.OncelikliKuyruk(m.kapanis_mi, 1, saat)
        kuyruk.put_nowait((olay("a:1", adr(1), "ETH", "B", 10, 2000.0, 0.0, saat), True))
        kuyruk.put_nowait((olay("a:2", adr(1), "SOL", "B", 5, 100.0, 0.0, saat), True))          # taştı: düşer
        durdur = asyncio.Event()
        gorev = asyncio.create_task(mt._tuketici(m, kuyruk, durdur))
        await asyncio.sleep(0.3)
        durdur.set()
        await gorev
    asyncio.run(kos())
    assert m.poz_tr[adr(1)]["SOL"] == 5.0 and m.poz_tr[adr(1)]["ETH"] == 10.0


# ================================================================================================ #7 funding_oran_yok
def test_funding_orani_okunamayan_coin_sayilir_ve_ozete_yazilir(tmp_path):
    """BTC oranı var (long 2 BTC, mark 100, +0,0001 → −0,02 $), SOL oranı yok: SOL atlanır AMA `funding_oran_yok` = 1, kayıt satırı, ozet.json alanı."""
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    simdi = saat()
    m.hesap.uygula(adr(1), "BTC", "B", 2.0, 100.0, 0.0, simdi)
    m.hesap.uygula(adr(1), "SOL", "B", 1.0, 100.0, 0.0, simdi)
    m.son_funding_saat = simdi // 3_600_000 - 1
    toplam = m.funding_uygula({"BTC": 0.0001}, simdi)
    assert toplam == pytest.approx(-0.02) and m.sayac["funding_oran_yok"] == 1
    assert kayitlar(tmp_path, "funding_oran_yok")[-1]["coin"] == "SOL" and m.ozet()["funding_oran_yok"] == 1


# ================================================================================================ lider denetimi düzeltmeleri
def test_hesap_json_yoksa_dolu_niyet_dosyasi_oynatilmaz_mutabakat_bayragi(tmp_path):
    """hesap.json silindi ama niyet.jsonl dolu (eski dolum sonuçlu): yeni defter BOŞ kalır (hayalet pozisyon yok), `mutabakat` bayrağı kalkar, `oynat_hesap_yok` kaydı; ikinci başlatmada tekrar oynatma yok."""
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    assert m.hesap.sz(adr(1), "BTC") > 0 and any(x["t"] == "sonuc" for x in m.niyet.satirlar())
    (tmp_path / "durum" / "hesap.json").unlink()
    m2, *_ = kur(tmp_path, saat=saat)
    m2.baslat()
    assert m2.hesap.sz(adr(1), "BTC") == 0.0 and m2.risk.acilis_durdu.get("mutabakat")
    assert kayitlar(tmp_path, "oynat_hesap_yok")[-1]["niyet_say"] == 1 and not kayitlar(tmp_path, "niyet_oynatildi")


def test_bos_durumda_ilk_baslatma_bayrak_kaldirmaz(tmp_path):
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    assert not m.risk.acilis_durdu.get("mutabakat") and not kayitlar(tmp_path, "oynat_hesap_yok")


@pytest.mark.parametrize("hata", [False, True])
def test_emir_yok_ya_da_durum_okunamadi_azalt_yeniden_kuyruga_girer(tmp_path, monkeypatch, hata):
    """Azalt 40 $ (defter 0,5 BTC, giriş 100): `orderStatus` emri bulamadı (unknownOid) ya da hata verdi → dolan 0, azalt kuyruğa: hedef 0,5 − 40/100 = 0,10; hata halinde ayrıca mutabakat bayrağı.
    Kuyruk girdisi `deneme` ile sınırlı (bantlar sonunda alarmlı `eksik`); yeniden deneme yeni kimlik/cloid ile (`_kuyruk_isle`)."""
    sim = BorsaSim()
    m, sim, saat, _ = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    m.hesap.uygula(adr(1), "BTC", "B", 0.5, 100.0, 0.0, saat())
    _niyet_kur(m, saat, "azalt", "A", 40.0)
    c2 = ny.cloid_uret("z:2", "kapat")
    m.durum_yaz()
    if hata:
        asil = sim.post

        def post(y):
            if y["type"] == "orderStatus":
                raise RuntimeError("ag")
            return asil(y)
        sim.post = post
    m2 = _yeniden(tmp_path, monkeypatch, sim, saat)
    m2.baslat()
    e = m2.kapanis_kuyrugu[f"{adr(1)}|BTC"]
    assert e["tur"] == "azalt" and e["hedef_sz"] == pytest.approx(0.10) and e["deneme"] == 0
    assert bool(m2.risk.acilis_durdu.get("mutabakat")) is hata and len(sim.siparisler) == 0
    assert c2 not in [x.get("cloid") for x in m2.niyet.satirlar()]


def test_dusen_isle_ayni_ms_farkli_dolum_uygulanir_ayni_kimlik_tek_sayilir(tmp_path):
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    a = olay("d:1", adr(1), "BTC", "B", 100, 100.0, 0.0, saat)
    b = olay("d:2", adr(1), "BTC", "B", 50, 100.0, None, saat)                 # aynı ms, farklı kimlik: delta eklenir
    m.dusen_isle(a)
    m.dusen_isle(b)
    m.dusen_isle(b)                                                            # aynı kimlik ikinci kez: sayılmaz
    assert m.poz_tr[adr(1)]["BTC"] == 150.0


def test_niyet_sikistir_atomik_fsync_ve_icerik(tmp_path, monkeypatch):
    n = ny.Niyet(tmp_path / "niyet.jsonl")
    for i in range(30):
        c = ny.cloid_uret(str(i), "ac")
        n.niyet_yaz(kimlik=str(i), eylem="ac", adres="a", coin="BTC", yon="B", usd=1.0, reduce_only=False, cloid=c, ms=i)
        n.sonuc_yaz(c, "dolu", i)
    cagri = []
    gercek = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (cagri.append(fd), gercek(fd))[1])
    n.sikistir(5)
    assert len(cagri) == 2 and len(n.kimlikler()) == 5 and n.kimlikler()[-1] == "29" and not list(tmp_path.glob("*.tmp"))
