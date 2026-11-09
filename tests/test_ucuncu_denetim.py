"""Üçüncü dış denetim (09.11): Y-1 (yarım DUR), Y-2 (belirsizde merdiven durur), Y-5 (ikinci motor / yabancı emir), Y-7 (limit fiyat ızgarası) ve mutasyon boşlukları.
Ağsız; gerçek kip YALNIZ sahte borsa (`BorsaSim`) ile sınanır, ÇALIŞTIRILMAZ. Sayılar elle hesaplanmıştır:
- Kasa 1.000 $, 11 slot → slot 90,909 $; trader hesabı 100.000 $.
- BTC: trader 300 × 100 $ = 30.000 $ (oran 0,30) → 27,27 $ / ask 100 = 0,27273 BTC (szDecimals 5).
- ETH: trader 15 × 2.000 $ = 30.000 $ (oran 0,30) → 27,27 $ / ask 2.000 = 0,013636 → 4 hane 0,0136 ETH.
- Kapanış limitleri (bant %0,5, satış yukarı yuvarlanır): BTC bid 99,9 × 0,995 = 99,4005 → tick 0,1 → 99,5; ETH bid 1.999 × 0,995 = 1.989,005 → tick 0,1 → 1.989,1.
"""
from __future__ import annotations

import json
import os
import random
from decimal import Decimal

import pytest

from copytrade.canli import motor as mt
from copytrade.canli import risk as rk
from copytrade.canli import yurutucu as yu
from tests.test_canli_g12 import ZamanAsimiBorsa
from tests.test_canli_motor import RULES, SahteHL, SahteTG, adr, kayitlar, kur, olay
from tests.test_canli_t4b import BorsaSim, Cokus, kur_gercek
from tests.test_g15_g22_acilis import HESAP, _main_kur

BTC_SZ, ETH_SZ = 0.27273, 0.0136


@pytest.fixture(autouse=True)
def _maske_temizle():
    yield
    mt.MASKE.clear()


def _iki_pozisyon(m, saat):
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    m.olay_isle(olay("a:2", adr(1), "ETH", "B", 15, 2000.0, 0.0, saat))


def _dur_yarida_olsun(m, monkeypatch):
    """DUR tetiklenir: DUR dosyası (kapanis_bekliyor) yazılır, ilk kapanış emrinden ÖNCE süreç ölür (kuyruk boş)."""
    def ol(*a, **k):
        raise Cokus()
    monkeypatch.setattr(m, "_adres_kapat", ol)
    with pytest.raises(Cokus):
        m.dur_tetikle("zirve_dusus")


# ================================================================================================ Y-1: yarım DUR
def test_y1_altin_dur_yarim_kaldi_yeniden_baslatma_ilk_dakikada_iki_pozisyonu_kapatir_alarm(tmp_path, monkeypatch):
    sim = BorsaSim()
    m, sim, saat, _ = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    _iki_pozisyon(m, saat)
    assert sim.poz == {"BTC": pytest.approx(BTC_SZ), "ETH": pytest.approx(ETH_SZ)} and len(sim.siparisler) == 2
    _dur_yarida_olsun(m, monkeypatch)
    dur = json.loads((tmp_path / "durum" / "DUR").read_text(encoding="utf-8"))
    assert dur["kapanis_bekliyor"] is True and len(sim.siparisler) == 2 and not m.kapanis_kuyrugu      # hiç kapanış emri gitmedi
    tgp2 = SahteTG()
    m2, *_ = kur_gercek(tmp_path, monkeypatch, sim, saat=saat, tgp=tgp2)
    m2.baslat()
    assert m2.risk.dur and m2.dur_bekliyor and sorted(m2.kapanis_kuyrugu) == [f"{adr(1)}|BTC", f"{adr(1)}|ETH"]
    assert any(x.startswith("🛑") and "DUR yarım kalmıştı: zirve_dusus" in x and "2 açık pozisyon kapanış kuyruğuna alındı" in x for x in tgp2.gonderilen)
    k = kayitlar(tmp_path, "dur_yeniden_kapanis")
    assert len(k) == 1 and k[0]["neden"] == "zirve_dusus" and k[0]["kuyruk"] == 2 and k[0]["yerel_poz"] == 2 and k[0]["borsa_acik"] is None
    m2.dakika()                                                                                    # ilk dakikalık adım (aynı an: geri çekilme beklemesi yok)
    kapat = sim.siparisler[2:]
    assert [(x["coin"], x["is_buy"], x["reduce_only"]) for x in kapat] == [("BTC", False, True), ("ETH", False, True)]
    assert kapat[0]["sz"] == pytest.approx(BTC_SZ) and kapat[0]["px"] == pytest.approx(99.5) and kapat[1]["sz"] == pytest.approx(ETH_SZ) and kapat[1]["px"] == pytest.approx(1989.1)
    assert sim.poz["BTC"] == pytest.approx(0.0, abs=1e-9) and sim.poz["ETH"] == pytest.approx(0.0, abs=1e-9) and not any(m2.hesap.poz.values())
    assert m2.dur_istendi and not m2.dur_bekliyor and json.loads((tmp_path / "durum" / "DUR").read_text(encoding="utf-8"))["kapanis_bekliyor"] is False


def test_y1_defter_bos_borsada_yetim_varsa_kapanis_modunda_acilir_borsa_duzse_baslamaz(tmp_path, monkeypatch):
    """Gerçek kip: DUR yarım, defter boş ama HL'de defter dışı 0,05 ETH → eskiden çıkış 3 (pozisyon açıkta kalırdı). Şimdi kapanış modu + alarm; ilk dakika G-2 yolu kapatır, motor durur.
    Borsa da düzse davranış aynı: DUR dosyası silinmeden AÇILMAZ."""
    sim = BorsaSim()
    m, sim, saat, _ = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    m._dur_yaz_atomik("komut", saat(), True)
    m.durum_yaz()
    sim.poz["ETH"] = 0.05
    tgp2 = SahteTG()
    m2, *_ = kur_gercek(tmp_path, monkeypatch, sim, saat=saat, tgp=tgp2)
    m2.baslat()
    assert m2.dur_bekliyor and not m2.kapanis_kuyrugu and any("borsada defter dışı açık pozisyon var" in x for x in tgp2.gonderilen)
    assert kayitlar(tmp_path, "dur_yeniden_kapanis")[0]["borsa_acik"] is True
    m2.dakika()
    assert sim.poz["ETH"] == pytest.approx(0.0, abs=1e-9) and sim.siparisler[-1]["reduce_only"] and m2.dur_istendi
    m3, *_ = kur_gercek(tmp_path, monkeypatch, sim, saat=saat)
    with pytest.raises(mt.KipHatasi, match="DUR dosyası var"):
        m3.baslat()


def test_y1_sanal_kip_ayni_yarim_dur_ilk_dakikada_kapanir(tmp_path, monkeypatch):
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    _iki_pozisyon(m, saat)
    assert m.hesap.sz(adr(1), "BTC") > 0 and m.hesap.sz(adr(1), "ETH") > 0
    _dur_yarida_olsun(m, monkeypatch)
    m2, *_ = kur(tmp_path, hl=hl, saat=saat)
    m2.baslat()
    assert len(m2.kapanis_kuyrugu) == 2
    m2.dakika()
    assert not any(m2.hesap.poz.values()) and m2.dur_istendi and len(kayitlar(tmp_path, "emir")) == 4


# ================================================================================================ Y-2: belirsizde merdiven durur
def _kapanis_niyetleri(m):
    return [x for x in m.niyet.satirlar() if x.get("t") == "niyet" and x.get("eylem") == "kapat"]


def test_y2_kapanis_merdiveni_ilk_belirsizde_durur_cozulunce_kuyruk_kapatir(tmp_path, monkeypatch):
    """Açık 0,27273 BTC; trader kapatır; her kapanış emri zaman aşımına düşüyor (HL emri hiç görmedi). Eskiden merdiven 5 emir verip 5 çözülmemiş cloid biriktirirdi.
    Şimdi: 1 emir, 1 belirsiz, girdi kuyrukta (eksik alarmı yok). Aynı dakika (10 sn dolmadı): yeni emir YOK. +60 sn: `orderStatus` → emir yok → kuyruk kapatır (borsa 0)."""
    sim = ZamanAsimiBorsa(ulasti=False, asili=0)
    m, sim, saat, tgp = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    sim.asili = 5
    s = m.olay_isle(olay("a:2", adr(1), "BTC", "A", 300, 100.0, 300.0, saat))
    assert s[0].karar == "belirsiz" and len(_kapanis_niyetleri(m)) == 1 and len(m.hesap.belirsiz) == 1
    b = list(m.hesap.belirsiz.values())[0]
    assert (b["adres"], b["coin"]) == (adr(1), "BTC") and list(m.kapanis_kuyrugu) == [f"{adr(1)}|BTC"] and m.sayac["kapanis_eksik"] == 0
    assert kayitlar(tmp_path, "kapanis_belirsiz_durdu")[0]["coin"] == "BTC" and not any("kapanış EKSİK" in x for x in tgp.gonderilen)
    m.dakika()
    assert len(_kapanis_niyetleri(m)) == 1 and sim.asili == 4                                     # belirsiz çözülmeden kuyruk beklemede
    sim.asili = 0
    saat.ms += 60_000
    m.dakika()
    assert m.hesap.belirsiz == {} and len(_kapanis_niyetleri(m)) == 2 and sim.poz["BTC"] == pytest.approx(0.0, abs=1e-9)
    assert m.hesap.sz(adr(1), "BTC") == pytest.approx(0.0, abs=1e-9) and not m.kapanis_kuyrugu


def test_y2_belirsiz_sorgusu_5_kez_bozuksa_kuyruk_engeli_kalkar(tmp_path, monkeypatch):
    m, sim, saat, _ = kur_gercek(tmp_path, monkeypatch, BorsaSim())
    m.hesap.belirsiz = {"0x01": {"ms": 0, "deneme": 4, "adres": adr(1), "coin": "BTC"}, "0x02": {"ms": 0, "deneme": 5, "adres": adr(1), "coin": "ETH"}}
    assert m._belirsiz_coinler() == {(adr(1), "BTC")}
    m.niyet.niyet_yaz(kimlik="k", eylem="kapat", adres=adr(2), coin="SOL", yon="A", usd=1.0, reduce_only=True, cloid="0x03", ms=0)
    m.hesap.belirsiz = {"0x03": {"ms": 0, "deneme": 0}}                                            # eski biçim: adres/coin niyetten
    assert m._belirsiz_coinler() == {(adr(2), "SOL")}


# ================================================================================================ Y-5: ikinci motor / yabancı açık emir
def test_y5_yabanci_acik_emir_reddedilir_bilinen_cloid_gecer(tmp_path):
    h = SahteHL()
    yol = tmp_path / "niyet.jsonl"
    mt.Niyet(yol).niyet_yaz(kimlik="k", eylem="ac", adres=adr(1), coin="BTC", yon="B", usd=10.0, reduce_only=False, cloid="0x" + "ab" * 16, ms=0)
    mt.yabanci_emir_denetle(h, HESAP, yol)                                                        # açık emir yok
    h.acik_emirler = [{"coin": "BTC", "oid": 1, "cloid": "0x" + "AB" * 16}]
    mt.yabanci_emir_denetle(h, HESAP, yol)                                                        # bizim (büyük/küçük harf farkı önemsiz)
    for yabanci in ({"coin": "ETH", "oid": 2, "cloid": "0x" + "cd" * 16}, {"coin": "ETH", "oid": 3}, {"coin": "ETH", "oid": 4, "cloid": None}):
        h.acik_emirler = [{"coin": "BTC", "oid": 1, "cloid": "0x" + "ab" * 16}, yabanci]
        with pytest.raises(mt.KipHatasi, match="niyet kaydında olmayan 1 açık emir var \\(ETH\\)"):
            mt.yabanci_emir_denetle(h, HESAP, yol)
    with pytest.raises(mt.KipHatasi):
        mt.yabanci_emir_denetle(h, HESAP, tmp_path / "yok.jsonl")                                 # niyet dosyası yok: hiçbir emir bizim değil

    def bozuk(y):
        return {"hata": 1} if y["type"] == "openOrders" else h(y)
    with pytest.raises(mt.HlOkunamadi):
        mt.yabanci_emir_denetle(bozuk, HESAP, yol)


def test_y5_main_yabanci_emir_varsa_cikis_3_motor_kurulmaz(monkeypatch, tmp_path):
    h = SahteHL(hesap=300.0)
    h.acik_emirler = [{"coin": "BTC", "oid": 7, "cloid": "0x" + "ee" * 16}]
    TabanTg, olustu = _main_kur(monkeypatch, h)
    assert mt.main(["--durum-dizin", str(tmp_path / "durum")]) == 3
    assert not olustu and "niyet kaydında olmayan 1 açık emir" in TabanTg.ornekler[0].gonderilen[0]


def test_y5_hesap_kilidi_adresli_baska_durum_dizini_ayni_hesap_cikis_3(monkeypatch, tmp_path):
    assert mt.hesap_kilidi_adi(" 0xABcd/../x ") == "motor-0xabcdx.lock" and mt.hesap_kilidi_adi(HESAP) == f"motor-{HESAP}.lock"
    fd = mt.hesap_kilidi_al(tmp_path, HESAP)
    try:
        assert (tmp_path / f"motor-{HESAP}.lock").read_text().strip() == str(os.getpid())
        with pytest.raises(mt.KipHatasi, match="hesap kilidi dolu"):
            mt.hesap_kilidi_al(tmp_path, HESAP)
        os.close(mt.hesap_kilidi_al(tmp_path, adr(8)))                                            # başka hesap serbest
        TabanTg, olustu = _main_kur(monkeypatch, SahteHL(hesap=300.0))
        assert mt.main(["--durum-dizin", str(tmp_path / "durum2")]) == 3                          # ayrı durum dizini, aynı hesap
        assert not olustu and "bu HL hesabını kullanıyor" in TabanTg.ornekler[0].gonderilen[0]
    finally:
        os.close(fd)


# ================================================================================================ Y-7: limit fiyat ızgarası
def _hl_gecerli(px: float, dec: int) -> bool:
    d = Decimal(repr(px))
    if d == d.to_integral_value():
        return True                                                                               # tam sayı fiyat her zaman geçerli
    t = d.normalize().as_tuple()
    return -t.exponent <= 6 - dec and len(t.digits) <= 5


def test_y7_altin_buyuk_fiyatta_tam_sayi_adim_ve_en_iyi_fiyat_siniri():
    """123.456 $ (≥ 100.000: tam sayı adım 1). Bant 0,00001: alış 123.456 × 1,00001 = 123.457,23 → 123.457 (eskiden adım 10 → 123.450 < ask: IOC dolmazdı);
    satış 123.456 × 0,99999 = 123.454,77 → 123.455 (eskiden 123.460 > bid). Izgara dışı en iyi fiyat 0,1234567 (szDecimals 0, adım 0,00001), bant 0:
    alış tabanı 0,12345 < en iyi → 0,12346; satış tavanı 0,12346 > en iyi → 0,12345."""
    assert yu.limit_yuvarla(123456 * 1.00001, 5, "B", 123456.0) == 123457.0 and yu.limit_yuvarla(123456 * 0.99999, 5, "A", 123456.0) == 123455.0
    assert yu.limit_yuvarla(0.1234567, 0, "B", 0.1234567) == 0.12346 and yu.limit_yuvarla(0.1234567, 0, "A", 0.1234567) == 0.12345
    assert yu.limit_yuvarla(100 * 1.005, 5, "B", 100.0) == 100.5 and yu.limit_yuvarla(99.9 * 0.995, 5, "A", 99.9) == 99.5     # olağan bant: değişmedi


def test_y7_ozellik_fuzz_alis_ask_ustu_satis_bid_alti_ve_hl_kurali():
    """20.000 rastgele (fiyat 1e‑6…1e6, szDecimals 0…5, bant 0…%2): limit HL ızgarasında, alış ≥ en iyi ask, satış ≤ en iyi bid ve bant en çok bir tick aşılır."""
    r = random.Random(7)
    for _ in range(20_000):
        dec = r.randint(0, 5)
        en_iyi = yu._izgara(10 ** r.uniform(-6, 6), dec, True)
        bant = r.choice([0.0, 1e-5, 1e-4, 1e-3, 0.005, 0.01, 0.02])
        for yon in "BA":
            ham = en_iyi * (1 + bant) if yon == "B" else en_iyi * (1 - bant)
            lim = yu.limit_yuvarla(ham, dec, yon, en_iyi)
            assert _hl_gecerli(lim, dec), (lim, dec)
            assert (lim >= en_iyi if yon == "B" else lim <= en_iyi), (yon, en_iyi, bant, lim)
            assert (lim <= max(ham, en_iyi) * (1 + 1e-9) if yon == "B" else lim >= min(ham, en_iyi) * (1 - 1e-9)), (yon, en_iyi, bant, lim)


def test_y7_gercek_yurutucu_limiti_en_iyi_fiyatla_sinirlar():
    from tests.test_canli_yurutucu import SahteExchange, dolu

    def post(y):
        if y["type"] == "meta":
            return {"universe": [{"name": "BTC", "szDecimals": 5}]}
        return {"levels": [[{"px": "123455", "sz": "1"}], [{"px": "123456", "sz": "1"}]]}
    ex = SahteExchange(dolu("0.0001", "123456"))
    yu.GercekYurutucu(ex, post, RULES).emir("BTC", "B", 12.3456, bant=0.00001)
    yu.GercekYurutucu(ex, post, RULES).emir("BTC", "A", 12.3455, bant=0.00001)
    assert [c["px"] for c in ex.cagrilar] == [123457.0, 123454.0]                                 # 123.455 × 0,99999 = 123.453,77 → 123.454 ≤ bid


# ================================================================================================ mutasyon boşlukları
def test_mut_gunluk_kayip_paydasi_gun_basi_kasa_degil():
    """Kasa 1.000 $, gün başı 800 $: kayıp (800 − 760) / 800 = %5 → bayrak; 761 → %4,875 → yok. Payda kasa olsaydı 760'ta %4 (bayrak yok).
    Gün başı 1.200 $: 1.150 → (50 / 1.200) %4,17 → yok (payda kasa olsaydı %5 → bayrak)."""
    g = rk.gun(1_800_000_000_000)
    r = rk.Risk(RULES, 1000.0, {"zirve": 800.0, "gun": g, "gun_basi": 800.0})
    assert r.ozsermaye_isle(761.0, 1_800_000_000_000) == [] and not r.acilis_durdu.get("gunluk_kayip")
    assert r.ozsermaye_isle(760.0, 1_800_000_000_000) == ["gunluk_kayip"] and r.acilis_durdu["gunluk_kayip"] is True
    r2 = rk.Risk(RULES, 1000.0, {"zirve": 1200.0, "gun": g, "gun_basi": 1200.0})
    assert r2.ozsermaye_isle(1150.0, 1_800_000_000_000) == [] and not r2.acilis_durdu.get("gunluk_kayip")
    assert r2.ozsermaye_isle(1140.0, 1_800_000_000_000) == ["gunluk_kayip"]                      # 60 / 1.200 = %5


@pytest.mark.parametrize("orig, beklenen_yerel, beklenen_uygulanan", [(0.4, 0.0, BTC_SZ), (0.1, BTC_SZ - 0.1, 0.1)])
def test_mut_belirsiz_reduce_only_kismi_kirpma(tmp_path, monkeypatch, orig, beklenen_yerel, beklenen_uygulanan):
    """Defter 0,27273 BTC uzun; belirsiz reduce-only satış `orderStatus` filled. origSz 0,4 > defter → uygulanan min(0,4; 0,27273) = 0,27273, defter 0 (−0,12727 kısa DEĞİL).
    origSz 0,1 < defter → uygulanan 0,1, defter 0,17273 (kırpma tüm pozisyonu silmez)."""
    m, sim, saat, _ = kur_gercek(tmp_path, monkeypatch, BorsaSim())
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    c = "0x" + "11" * 16
    m.niyet.niyet_yaz(kimlik="t:1", eylem="azalt", adres=adr(1), coin="BTC", yon="A", usd=40.0, reduce_only=True, cloid=c, ms=saat())
    m.hesap.belirsiz[c] = {"ms": saat(), "deneme": 0, "adres": adr(1), "coin": "BTC"}
    sim.durumlar[c] = {"status": "order", "order": {"order": {"coin": "BTC", "side": "A", "limitPx": "99.5", "sz": "0.0", "origSz": str(orig), "oid": 5}, "status": "filled"}}
    saat.ms += 60_000
    assert m.belirsiz_coz(saat()) == 1
    assert m.hesap.sz(adr(1), "BTC") == pytest.approx(beklenen_yerel, abs=1e-9)
    k = kayitlar(tmp_path, "belirsiz_cozuldu")[-1]
    assert k["dolan_sz"] == pytest.approx(orig) and k["uygulanan_sz"] == pytest.approx(beklenen_uygulanan)


def test_y1_defter_bos_borsa_okunamazsa_kapanis_modu_duz_teyidi_beklenir(tmp_path, monkeypatch):
    """DUR yarım, defter boş, HL `clearinghouseState` okunamıyor → çıkış 3 DEĞİL (pozisyon açıkta olabilir): kapanış modu + "borsa okunamadı" alarmı; motor borsa düz görülene dek durmaz."""
    sim = BorsaSim()
    m, sim, saat, _ = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    m._dur_yaz_atomik("komut", saat(), True)
    m.durum_yaz()
    asil = sim.post

    def kopuk(y):
        if y["type"] == "clearinghouseState" and y["user"] == "0x" + "ab" * 20:
            raise ConnectionError("ag")
        return asil(y)
    tgp2 = SahteTG()
    m2, *_ = kur_gercek(tmp_path, monkeypatch, sim, saat=saat, tgp=tgp2)
    m2.post = kopuk
    m2.baslat()
    assert m2.dur_bekliyor and kayitlar(tmp_path, "dur_yeniden_kapanis")[0]["borsa_acik"] is None and any("borsa okunamadı (düz teyidi yok)" in x for x in tgp2.gonderilen)
    m2.dakika()
    assert m2.dur_bekliyor and not m2.dur_istendi
    m2.post = asil
    saat.ms += 60_000
    m2.dakika()
    assert m2.dur_istendi
