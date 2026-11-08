"""Denetim düzeltmeleri (DENETIM_DEVIR_2026-11-06 G-5, M-1, M-2; DENETIM_PROJE_2026-11-08 S-2, S-3, S-7, S-8). Ağsız; gerçek kip YALNIZ sahte borsa (`BorsaSim`) ile.
Sayılar elle hesaplanmıştır (altın örnekler; hesap açıklaması her testin belgesinde)."""
import json

import pytest

from copytrade.canli import hesap as hs
from copytrade.canli import kadro as kd
from copytrade.canli import motor as mt
from copytrade.canli import telegram as tg
from copytrade.canli import yurutucu as yu
from tests.test_canli_motor import CHAT, SAAT, TOKEN, SahteHL, SahteTG, Saat, adr, kadro, kayitlar, kur, n_kadro, satir
from tests.test_canli_t4b import HLADR, RULES, BorsaSim


@pytest.fixture(autouse=True)
def _maske_temizle():
    yield
    mt.MASKE.clear()


def kur_g(tmp_path, monkeypatch, sim, ayar, etkin=None, k=None, saat=None, tgp=None):
    """Gerçek kip Motor (sahte borsa). `main` ile aynı kurallar: `canli_kasa_usd` = etkin (min(ayar, HL)), `canli_kasa_ayar_usd` = ayar."""
    monkeypatch.setenv("HL_HESAP_ADRESI", HLADR)
    rules = {**RULES, "canli_kasa_usd": ayar if etkin is None else etkin, "canli_kasa_ayar_usd": ayar}
    saat = saat or Saat()
    tgp = tgp or SahteTG()
    k = k or kadro([satir(1, 1)], saat() - SAAT)
    for s in k["satirlar"]:
        sim.trader_poz.setdefault(s["adres"], {})
    m = mt.Motor(rules, yu.GercekYurutucu(sim, sim.post, rules), sim.post, tg.Telegram(TOKEN, CHAT, tgp), tmp_path / "durum", tmp_path / "kayit", lambda: k, saat)
    return m, saat, tgp


def ozdeslik(h: hs.Hesap, marks: dict) -> float:
    """özsermaye = kasa + realize − ücret + funding + açık K/Z + kapanmis_net (elle açılmış hâli)."""
    return h.kasa_usd + sum(h.realize.values()) - sum(h.ucret.values()) + sum(h.funding.values()) + h.gerceklesmemis(None, marks) + h.kapanmis_net


# ================================================================================================ G-5
def test_g5_gercek_zararla_yeniden_baslatma_zarari_iki_kez_saymaz_bayrak_yok(tmp_path, monkeypatch):
    """Altın örnek: kasa 300 (ayar 300, HL 300 → ofset 0). Bir işlem −20 $ realize (ücret 0). HL 280. Yeniden başlatma: `main` etkin kasa = min(300, 280) = 280 verir.
    ESKİ: hesap.kasa_usd = 280 + realize −20 → yerel 260 ↔ HL 280 − ofset 0 = 280 → fark 20 $ > 300 × %1 = 3 $ → kalıcı mutabakat bayrağı.
    YENİ: kasa = dönem başı 300 (kalıcı) → yerel 300 − 20 = 280 = HL 280 → fark 0, bayrak YOK; getiri 280/300 − 1 = −%6,67."""
    sim = BorsaSim(deger=300.0)
    m, saat, _ = kur_g(tmp_path, monkeypatch, sim, 300.0)
    m.baslat()
    m.dakika()
    assert m.hl_ofset == pytest.approx(0.0) and m.kasa == 300.0
    m.hesap.realize[adr(1)] = -20.0                                                              # kapanmış bir işlemin zararı (pozisyon yok)
    sim.deger = 280.0
    m.durum_yaz()
    m.kilit_yaz(True)
    saat.ms += 120_000
    m2, saat, _ = kur_g(tmp_path, monkeypatch, sim, 300.0, etkin=280.0, saat=saat)
    assert m2.kasa == 300.0 and m2.hesap.kasa_usd == 300.0 and m2.kasa_ayar == 300.0
    assert m2.yerel_ozsermaye() == pytest.approx(280.0) and ozdeslik(m2.hesap, {}) == pytest.approx(280.0)
    m2.baslat()
    m2.dakika()
    assert m2.ozsermaye() == pytest.approx(280.0) and not m2.risk.acilis_durdu.get("mutabakat") and not kayitlar(tmp_path, "mutabakat_alarm")
    assert m2.ozet()["getiri"] == pytest.approx(280 / 300 - 1)
    assert m2.saha.slot == pytest.approx(300 / 11)                                              # slot dönem kasasından: yeniden başlatma slotu küçültmez


def test_g5_bos_dizinde_kasa_min_ayar_hl(tmp_path, monkeypatch):
    """Boş durum dizini (ilk dönem): kasa = etkin = min(ayar 300, HL 290) = 290 (K‑35 davranışı aynı)."""
    sim = BorsaSim(deger=290.0)
    m, _, _ = kur_g(tmp_path, monkeypatch, sim, 300.0, etkin=290.0)
    assert m.kasa == 290.0 and m.hesap.kasa_usd == 290.0


# ================================================================================================ S-2
def test_s2_zirve_dur_sonrasi_dur_silinip_yeniden_baslatilinca_zirve_guncel_ozsermayeye_kurulur(tmp_path):
    """Sanal, kasa 1.000: kapanan zararlar −210 $ → özsermaye 790, zirve 1.000 → düşüş %21 ≥ %20 → DUR (pozisyon yok: hemen durur, `DUR` yazılır).
    Operatör `DUR`'u silip yeniden başlatır: zirve 1.000 → 790 kurulur (`zirve_yenilendi` kaydı); 60 sn sonraki dakikada düşüş 0 → yeniden DUR YOK.
    ESKİ: zirve 1.000 kalırdı → 60 sn sonra yeniden DUR."""
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    m.hesap.kapanmis_net = -210.0
    saat.ms += 60_000
    m.dakika()
    assert m.risk.dur and m.dur_istendi and (tmp_path / "durum" / "DUR").exists() and m.risk.zirve == pytest.approx(1000.0)
    m.durum_yaz()
    m.kilit_yaz(True)
    (tmp_path / "durum" / "DUR").unlink()                                                        # lider onayı: elle silindi
    saat.ms += 60_000
    m2, _, _, _ = kur(tmp_path, hl=hl, saat=saat)
    m2.baslat()
    assert not m2.risk.dur and m2.risk.zirve == pytest.approx(790.0)
    k = kayitlar(tmp_path, "zirve_yenilendi")
    assert k and k[0]["eski_zirve"] == pytest.approx(1000.0) and k[0]["yeni_zirve"] == pytest.approx(790.0)
    saat.ms += 60_000
    m2.dakika()
    assert not m2.risk.dur and not m2.dur_istendi and not (tmp_path / "durum" / "DUR").exists()
    assert json.loads((tmp_path / "durum" / "risk.json").read_text())["zirve"] == pytest.approx(790.0)
    m2.hesap.kapanmis_net = -210.0 - 158.0                                                       # yeni zirve 790'dan %20 = 158 $ → yeniden DUR (koruma sürüyor)
    saat.ms += 60_000
    m2.dakika()
    assert m2.risk.dur and m2.risk.dur_neden == "zirve_dusus"


def test_s2_dur_dosyasi_duruyorsa_zirve_degismez_ve_baslamaz(tmp_path):
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    m.hesap.kapanmis_net = -210.0
    saat.ms += 60_000
    m.dakika()
    m.durum_yaz()
    m.kilit_yaz(True)
    m2, _, _, _ = kur(tmp_path, hl=hl, saat=saat)
    with pytest.raises(mt.KipHatasi, match="DUR dosyası var"):
        m2.baslat()
    assert m2.risk.zirve == pytest.approx(1000.0) and not kayitlar(tmp_path, "zirve_yenilendi")


def test_s2_risk_zirve_yenile_birim():
    r = mt.Risk(RULES, 1000.0, {"zirve": 1000.0, "gun": "2027-01-15", "gun_basi": 1000.0})
    assert r.zirve_yenile(790.0) == 1000.0 and r.zirve == 790.0
    r.ozsermaye_isle(790.0, 1_800_000_000_000)
    assert not r.dur and r.zirve == 790.0


# ================================================================================================ S-3
def test_s3_kasa_300_500_slot_tabanlari_ve_mutabakat_yeniden_kurulur_slot_dusus_yok(tmp_path, monkeypatch):
    """Gerçek kip, 11 üye, kasa 300 → slot 27,2727. Üye 1'in kapanan işlemi −2 $ → yerel 298 = HL 298 (ofset 0). Pozisyon yok.
    Kullanıcı 200 $ yatırır (HL 498) ve CANLI_KASA_USD = 500 yapar. Yeniden başlatma (etkin = min(500, 498) = 498 → kasa 498):
      - slot = 498 / 11 = 45,2727; 11 üyenin tabanı 45,2727 (ESKİ: taban 27,27, eşik slot × 0,9 = 40,7 → 11 üye `slot_dusus`la inerdi);
      - eski net −2 $ `kapanmis_net`e: özsermaye = 498 + (−2) = 496; özdeşlik tutar;
      - ofset yeniden kurulur: HL 498 − yerel 496 = 2 (ESKİ: yatırma ledger'dan ofsete +200 → 200 $ kalıcı mutabakat farkı);
      - zirve = gün başı = 496."""
    k = n_kadro(11)
    sim = BorsaSim(deger=300.0)
    saat = Saat()
    k["kosu_ms"] = saat() - SAAT
    m, saat, _ = kur_g(tmp_path, monkeypatch, sim, 300.0, k=k, saat=saat)
    m.baslat()
    assert len(m.saha.uyeler) == 11 and all(v == pytest.approx(300 / 11) for v in m.hesap.slot_bas.values())
    m.hesap.realize[adr(1)] = -2.0
    sim.deger = 298.0
    m.dakika()
    assert m.hl_ofset == pytest.approx(0.0)
    m.durum_yaz()
    m.kilit_yaz(True)
    sim.deger = 498.0
    saat.ms += 120_000
    m2, saat, _ = kur_g(tmp_path, monkeypatch, sim, 500.0, etkin=498.0, k=k, saat=saat)
    assert m2.kasa == 498.0 and m2.hesap.kasa_usd == 498.0 and m2.saha.slot == pytest.approx(498 / 11)
    assert all(v == pytest.approx(498 / 11) for v in m2.hesap.slot_bas.values()) and len(m2.hesap.slot_bas) == 11
    assert m2.hesap.kapanmis_net == pytest.approx(-2.0) and m2.hesap.realize[adr(1)] == 0.0
    assert m2.yerel_ozsermaye() == pytest.approx(496.0) and ozdeslik(m2.hesap, {}) == pytest.approx(496.0)
    assert m2.hl_ofset is None and m2.ledger_son_ms is None and m2.risk.zirve == pytest.approx(496.0) and m2.risk.gun_basi == pytest.approx(496.0)
    m2.baslat()
    m2.dakika()
    assert len(m2.saha.uyeler) == 11 and not kayitlar(tmp_path, "saha_dus")
    assert m2.hl_ofset == pytest.approx(2.0) and not m2.risk.acilis_durdu.get("mutabakat") and not m2.risk.dur
    d = kayitlar(tmp_path, "donem_yenilendi")
    assert len(d) == 1 and d[0]["eski_kasa_usd"] == 300.0 and d[0]["yeni_kasa_usd"] == 498.0 and d[0]["eski_ozsermaye"] == pytest.approx(298.0) and d[0]["uye"] == 11
    assert kayitlar(tmp_path, "kasa_degisti")[0]["yeni_usd"] == 500.0


def test_s3_kasa_500_300_zirve_dusus_ve_gunluk_kayip_sayilmaz(tmp_path, monkeypatch):
    """500 → 300 (pozisyonsuz, 200 $ çekildi): yeni dönem zirve/gün başı 300 → düşüş 0, DUR yok, günlük kayıp yok (ESKİ: zirve 500 → −%40 → DUR)."""
    sim = BorsaSim(deger=500.0)
    m, saat, _ = kur_g(tmp_path, monkeypatch, sim, 500.0)
    m.baslat()
    m.dakika()
    m.durum_yaz()
    m.kilit_yaz(True)
    sim.deger = 300.0
    saat.ms += 120_000
    m2, saat, _ = kur_g(tmp_path, monkeypatch, sim, 300.0, saat=saat)
    m2.baslat()
    m2.dakika()
    assert m2.kasa == 300.0 and m2.risk.zirve == pytest.approx(300.0) and not m2.risk.dur and not m2.risk.acilis_durdu.get("gunluk_kayip")
    assert not m2.risk.acilis_durdu.get("mutabakat") and m2.hl_ofset == pytest.approx(0.0)


def test_s3_acik_pozisyonla_kasa_degisikligi_hala_reddedilir_donem_yenilenmez(tmp_path, monkeypatch):
    sim = BorsaSim(deger=300.0)
    m, saat, _ = kur_g(tmp_path, monkeypatch, sim, 300.0)
    m.baslat()
    m.hesap.uygula(adr(1), "BTC", "B", 0.1, 100.0, 0.0, saat())
    m.durum_yaz()
    m.kilit_yaz(True)
    m2, saat, _ = kur_g(tmp_path, monkeypatch, sim, 500.0, saat=saat)
    assert m2._donem_eski is None
    with pytest.raises(mt.KipHatasi, match="açık pozisyon var"):
        m2.baslat()
    assert not kayitlar(tmp_path, "donem_yenilendi")


def test_s3_hesap_donem_yenile_birim_ve_pozisyonla_ret():
    h = hs.Hesap(300.0)
    h.slot_ac("a", 300 / 11)
    h.slot_ac("b", 300 / 11)
    h.realize["a"], h.ucret["a"], h.funding["b"] = -2.0, 0.5, 0.25
    h.kapanmis_net = 1.0
    once = h.ozsermaye({})                                                                       # 300 − 2 − 0,5 + 0,25 + 1 = 298,75
    assert once == pytest.approx(298.75)
    eski = h.donem_yenile(500.0, 500 / 11)
    assert eski["kasa_usd"] == 300.0 and eski["ozsermaye"] == pytest.approx(298.75)
    assert h.kasa_usd == 500.0 and h.kapanmis_net == pytest.approx(1.0 - 2.0 - 0.5 + 0.25) and h.ozsermaye({}) == pytest.approx(498.75)
    assert h.slot_bas == {"a": pytest.approx(500 / 11), "b": pytest.approx(500 / 11)} and h.slot_ozsermaye("a", {}) == pytest.approx(500 / 11)
    h.uygula("a", "BTC", "B", 0.1, 100.0, 0.0, 0)
    with pytest.raises(ValueError):
        h.donem_yenile(300.0, 300 / 11)


def test_s3_saha_anlik_uyenin_kendi_tabanina_gore():
    """Kasa 500 (slot 45,45; eşik 40,9). Üye tabanı 27,27, slot özsermayesi 27,0 (−%1): tabanı verilirse düşmez; verilmezse (eski) `slot_dusus`. Tabanından −%10 = 24,545 → düşer."""
    s = kd.Saha(RULES, 500.0)
    s.uyeler = {adr(1): {"giris_ms": 0, "giris_sira": 1, "sira_ust": 0, "son_islem_ms": None}}
    taban = {adr(1): 300 / 11}
    assert s.anlik(10, lambda a: 27.0, None, slot_bas=taban.get) == []
    s2 = kd.Saha(RULES, 500.0)
    s2.uyeler = dict(s.uyeler)
    assert [k.neden for k in s2.anlik(10, lambda a: 27.0, None)] == ["slot_dusus"]
    assert [k.neden for k in s.anlik(10, lambda a: 300 / 11 * 0.9, None, slot_bas=taban.get)] == ["slot_dusus"]


# ================================================================================================ M-1
def test_m1_geri_giren_uyenin_eski_defteri_kapanmis_nete_tasinir_ozdeslik_korunur():
    """Altın örnek: kasa 1.000; üye A 1 BTC @100 alır (ücret 0,05), 0,5'ini @90 satar (ücret 0,05) → realize −5, ücret 0,1; kalan 0,5 BTC açık (kapanış teyit edilmedi).
    Mark 95: açık K/Z 0,5 × (95 − 100) = −2,5 → özsermaye 1.000 − 5 − 0,1 − 2,5 = 992,4. A sahaya geri girer (slot 50): ESKİ: realize/ücret sıfırlanır → 997,5 (5,1 $ hayalet kâr).
    YENİ: −5,1 `kapanmis_net`e; özsermaye 992,4 kalır; yeni slot özsermayesi 50 + (−2,5) = 47,5."""
    h = hs.Hesap(1000.0)
    h.slot_ac("A", 90.0)
    h.uygula("A", "BTC", "B", 1.0, 100.0, 0.05, 0)
    h.uygula("A", "BTC", "A", 0.5, 90.0, 0.05, 1)
    marks = {"BTC": 95.0}
    assert h.ozsermaye(marks) == pytest.approx(992.4)
    h.slot_ac("A", 50.0)
    assert h.ozsermaye(marks) == pytest.approx(992.4) and ozdeslik(h, marks) == pytest.approx(992.4)
    assert h.kapanmis_net == pytest.approx(-5.1) and h.realize["A"] == 0.0 and h.ucret["A"] == 0.0 and h.sz("A", "BTC") == pytest.approx(0.5)
    assert h.slot_ozsermaye("A", marks) == pytest.approx(47.5)
    h.uygula("A", "BTC", "A", 0.5, 95.0, 0.0, 2)                                                  # kalan sonradan kapanır: −2,5 yeni slota realize
    assert h.ozsermaye(marks) == pytest.approx(992.4) and h.realize["A"] == pytest.approx(-2.5)


def test_m1_yeni_uyede_slot_ac_degismez():
    h = hs.Hesap(1000.0)
    h.slot_ac("B", 90.0)
    assert h.kapanmis_net == 0.0 and h.ozsermaye({}) == 1000.0


# ================================================================================================ M-2
def test_m2_ayni_adim_ust_uste_3_hata_telegram_alarmi_basarida_sayac_sifirlanir(tmp_path, monkeypatch):
    m, _, saat, tgp = kur(tmp_path)
    m.baslat()
    durum = {"hata": True}

    def bozuk(simdi, hl=None):
        if durum["hata"]:
            raise RuntimeError("mutabakat bozuk")

    monkeypatch.setattr(m, "_mutabakat", bozuk)
    baslik = "ALARM: 'mutabakat' adımı hata veriyor"
    for i in range(2):
        saat.ms += 60_000
        m.dakika()
    assert not any(baslik in x for x in tgp.gonderilen) and m._adim_ardisik["mutabakat"] == 2
    saat.ms += 60_000
    m.dakika()
    assert sum(baslik in x for x in tgp.gonderilen) == 1 and kayitlar(tmp_path, "adim_hata")[-1]["ardisik"] == 3
    saat.ms += 60_000
    m.dakika()                                                                                    # 4. hata: yeni alarm yok (60'ın katlarında tekrar)
    assert sum(baslik in x for x in tgp.gonderilen) == 1
    durum["hata"] = False
    saat.ms += 60_000
    m.dakika()
    assert "mutabakat" not in m._adim_ardisik
    durum["hata"] = True
    for i in range(2):
        saat.ms += 60_000
        m.dakika()
    assert sum(baslik in x for x in tgp.gonderilen) == 1                                          # sayaç sıfırlandı: 2 hata alarm değil


# ================================================================================================ S-7
def test_s7_tasfiye_fiyati_azami_kaldirac_10_altin_ornek():
    """3x long @100, azami kaldıraç 10 → mmr = 1/20 = 0,05 → tasfiye 100 × (1 − 1/3) / 0,95 = 70,175439 (−%29,82). 20x varsayımı: mmr 0,025 → 68,376068 (−%31,62).
    3x short @100, azami 10 → 100 × (1 + 1/3) / 1,05 = 126,984127."""
    assert hs.tasfiye_fiyati(True, 100.0, 3.0, 10.0) == pytest.approx(70.175439, abs=1e-6)
    assert hs.tasfiye_fiyati(True, 100.0, 3.0, None) == pytest.approx(68.376068, abs=1e-6)
    assert hs.tasfiye_fiyati(False, 100.0, 3.0, 10.0) == pytest.approx(126.984127, abs=1e-6)
    h = hs.Hesap(1000.0, 3.0, {"BTC": 10.0})
    h.slot_ac("A", 90.0)
    h.uygula("A", "BTC", "B", 1.0, 100.0, 0.0, 0)
    assert h.tasfiye_kontrol({"BTC": 70.2}, 1) == []
    ev = h.tasfiye_kontrol({"BTC": 70.1}, 2)
    assert len(ev) == 1 and ev[0]["tasfiye_px"] == pytest.approx(70.175439, abs=1e-6) and ev[0]["pnl"] == pytest.approx(-29.824561, abs=1e-6)
    h20 = hs.Hesap(1000.0, 3.0)
    h20.uygula("A", "BTC", "B", 1.0, 100.0, 0.0, 0)
    assert h20.tasfiye_kontrol({"BTC": 70.1}, 2) == []                                             # eski 20x varsayımı: tasfiye olmazdı (iyimser)


class MetaHL(SahteHL):
    def __init__(self, *a, meta_hata=False, **k):
        super().__init__(*a, **k)
        self.meta_hata = meta_hata

    def __call__(self, y):
        if y["type"] == "meta":
            self.istekler.append(y)
            if self.meta_hata:
                raise ConnectionError("meta yok")
            return {"universe": [{"name": "BTC", "szDecimals": 5, "maxLeverage": 40}, {"name": "ETH", "szDecimals": 4, "maxLeverage": 25},
                                 {"name": "SOL", "szDecimals": 2, "maxLeverage": 10}, {"name": "ESKI", "szDecimals": 2, "maxLeverage": 3, "isDelisted": True}]}
        return super().__call__(y)


def test_s7_motor_sanal_acilista_meta_maxleverage_okur(tmp_path):
    m, hl, _, _ = kur(tmp_path, hl=MetaHL())
    m.baslat()
    assert m.hesap.maks_kaldirac == {"BTC": 40.0, "ETH": 25.0, "SOL": 10.0} and not kayitlar(tmp_path, "maks_kaldirac_okunamadi")
    m.durum_yaz()
    assert json.loads((tmp_path / "durum" / "hesap.json").read_text())["maks_kaldirac"]["SOL"] == 10.0


def test_s7_meta_okunamazsa_20x_yedek_ve_kayit(tmp_path):
    m, hl, _, _ = kur(tmp_path, hl=MetaHL(meta_hata=True))
    m.baslat()
    k = kayitlar(tmp_path, "maks_kaldirac_okunamadi")
    assert m.hesap.maks_kaldirac == {} and len(k) == 1 and k[0]["yedek_kaldirac"] == 20


# ================================================================================================ S-8
def test_s8_kapanis_kuyrugu_ustel_geri_cekilme_ve_gunluk_tavan_alarmi(tmp_path, monkeypatch):
    """Kapanmayan girdi: denemeler 1, 2, 4, 8, 16, 30, 30 dk arayla; aradaki dakikalarda deneme (ağ/emir) YOK. Günlük tavan 3 → 3. denemede bir kez alarm."""
    m, _, saat, tgp = kur(tmp_path, kurallar={"canli_kuyruk_gunluk_tavan": 3})
    m.baslat()
    saat.ms = (saat() // 86_400_000 + 1) * 86_400_000 + 60_000                                     # UTC gün başı + 1 dk: 7 deneme (91 dk) aynı günde
    cagri: list[int] = []
    monkeypatch.setattr(m, "_kapat_coin", lambda adres, coin, neden, simdi, o=None, bantlar=None, baslangic=0: (cagri.append(simdi), (False, None))[1])
    t0 = saat()
    m.kapanis_kuyrugu[f"{adr(1)}|BTC"] = {"tur": "kapat", "hedef_sz": 0.0, "neden": "test", "deneme": 5, "ms": t0, "eksik": True}
    araliklar = []
    for _ in range(7):
        e = m.kapanis_kuyrugu[f"{adr(1)}|BTC"]
        hedef = int(e.get("sonraki_ms", saat()))
        n = len(cagri)
        if "sonraki_ms" in e:                                                                     # ilk deneme hemen (sonraki dakika); sonrakiler: vakti gelmeden deneme yok
            saat.ms = hedef - 1
            m._kuyruk_isle(saat())
            assert len(cagri) == n
        saat.ms = hedef
        m._kuyruk_isle(saat())
        assert len(cagri) == n + 1
        araliklar.append((m.kapanis_kuyrugu[f"{adr(1)}|BTC"]["sonraki_ms"] - hedef) // 60_000)
    assert araliklar == [1, 2, 4, 8, 16, 30, 30]
    baslik = "ALARM: kapanış bugün de olmadı"
    assert sum(baslik in x for x in tgp.gonderilen) == 1                                          # günde bir kez
    k = kayitlar(tmp_path, "kuyruk_gunluk_tavan")
    assert k and k[0]["deneme"] == 3


def test_s8_tavan_alarmi_gunde_bir_kez(tmp_path, monkeypatch):
    m, _, saat, tgp = kur(tmp_path, kurallar={"canli_kuyruk_gunluk_tavan": 2})
    m.baslat()
    monkeypatch.setattr(m, "_kapat_coin", lambda *a, **k: (False, None))
    anahtar = f"{adr(1)}|BTC"
    m.kapanis_kuyrugu[anahtar] = {"tur": "kapat", "hedef_sz": 0.0, "neden": "test", "deneme": 5, "ms": saat(), "eksik": True}
    saat.ms = (saat() // 86_400_000 + 1) * 86_400_000 + 60_000                                     # UTC gün başı + 1 dk: 5 deneme (1+2+4+8 = 15 dk) aynı günde
    for _ in range(5):
        saat.ms = max(saat(), int(m.kapanis_kuyrugu[anahtar].get("sonraki_ms", 0)))
        m._kuyruk_isle(saat())
    assert sum("ALARM: kapanış bugün de olmadı" in x for x in tgp.gonderilen) == 1 and m.kapanis_kuyrugu[anahtar]["gun_deneme"] == 5
