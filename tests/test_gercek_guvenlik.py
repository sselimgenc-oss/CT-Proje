"""Gerçek kip güvenlik düzeltmeleri (09.11 dış denetim): K‑22 açılış HL tavanı, kadro deposu, Telegram grup yetkisi, S-6 açıklanmayan HL sıçraması,
bekçi ↔ uzun kapanış döngüsü, mutabakat yarışı, `calis()` uçtan uca. Ağsız; sahte HL / WS / saat. Altın örnekler elle hesaplandı (docstring'lerde)."""
import asyncio
import json

import pytest

from copytrade.canli import motor as mt
from copytrade.canli import telegram as tg
from copytrade.kurallar import load_rules
from tests.test_canli_motor import CHAT, TOKEN, SahteHL, SahteTG, SahteWS, adr, kayitlar, kur, olay, tg_mesaj, userfills
from tests.test_canli_t4b import HLADR, BorsaSim, kur_gercek

RULES = load_rules()


@pytest.fixture(autouse=True)
def _maske_temizle():
    yield
    mt.MASKE.clear()


# ================================================================================================ 1. K‑22 açılış tuzağı
def _acilis(monkeypatch, hl_deger):
    monkeypatch.setenv("CANLI_KASA_USD", "1000")
    monkeypatch.setenv("HL_HESAP_ADRESI", adr(7))
    monkeypatch.setattr(mt, "api_cuzdan_dogrula", lambda post, ortam, turet=None: {"tamam": True})
    return mt.acilis_hl_denetle(RULES, "gercek", SahteHL(hesap=hl_deger), {})


def test_k22_kurallar_hl_tavani_1500_kasa_siniri_1000_ayri():
    assert RULES["canli_hl_deger_ust_usd"] == 1500 and RULES["canli_kasa_ust_usd"] == 1000 and mt.hl_deger_ust(RULES) == 1500.0
    assert mt.hl_deger_ust({"canli_kasa_ust_usd": 1000}) == 1000.0                     # anahtar yoksa eski (sıkı) davranış


def test_k22_karli_gunden_sonra_hl_1012_motor_kasa_1000_ile_baslar(monkeypatch):
    """Altın örnek: CANLI_KASA_USD 1.000, HL 1.012 $ (kârlı gün). ESKİ: 1.012 > 1.000 → KipHatasi (çıkış 3, systemd yeniden başlatmaz, açık pozisyon yönetimsiz).
    YENİ: 1.012 ≤ 1.500 → başlar; etkin kasa = min(1.000, 1.012) = 1.000 (K‑22 kasa sınırı aynı)."""
    kasa, hl = _acilis(monkeypatch, 1012.0)
    assert kasa == 1000.0 and hl == 1012.0
    kasa, hl = _acilis(monkeypatch, 1500.0)                                                  # sınırın tam üstü değil: geçer
    assert kasa == 1000.0 and hl == 1500.0


def test_k22_hl_1501_kip_hatasi(monkeypatch):
    with pytest.raises(mt.KipHatasi, match=r"1501 \$ > sınır 1500 \$"):
        _acilis(monkeypatch, 1501.0)


def test_k22_kontrol_hl_1012_tamam_etkin_kasa_1000(monkeypatch):
    ortam = {"HL_API_CUZDAN_ANAHTARI": "gizli", "HL_HESAP_ADRESI": adr(7), "CANLI_KASA_USD": "1000"}
    r = mt.kontrol(RULES, "gercek", SahteHL(hesap=1012.0), lambda: None, tg.Telegram(TOKEN, CHAT, SahteTG()), ortam=ortam, turet=lambda k: adr(9))
    assert r["hl_hesap_degeri"] == 1012.0 and r["hl_deger_siniri_ok"] is True and r["etkin_kasa_usd"] == 1000.0 and r["kasa_siniri_ok"] is True
    r = mt.kontrol(RULES, "gercek", SahteHL(hesap=1501.0), lambda: None, tg.Telegram(TOKEN, CHAT, SahteTG()), ortam=ortam, turet=lambda k: adr(9))
    assert r["hl_deger_siniri_ok"] is False and r["tamam"] is False


# ================================================================================================ 2. kadro deposu
def test_kadro_deposu_ct_proje():
    assert RULES["canli_kadro_repo"] == "sselimgenc-oss/CT-Proje"
    assert mt.kadro_url(RULES, "radar") == "https://raw.githubusercontent.com/sselimgenc-oss/CT-Proje/radar/radar/son/kadro.json"


# ================================================================================================ 3. Telegram grup yetkisi
GRUP = "-1001234567890"


def test_telegram_grup_sohbetinde_uye_komutu_kabul_bot_ve_yabanci_sohbet_ret():
    """TELEGRAM_CHAT_ID grup (negatif): from.id kullanıcının kimliğidir (≠ grup). ESKİ: tüm komutlar yetkisiz. YENİ: grup üyesi kabul, bot ve başka sohbet ret."""
    bot = tg_mesaj(3, "/dur", chat=GRUP, kimden=777)
    bot["message"]["from"]["is_bot"] = True
    t = tg.Telegram(TOKEN, GRUP, SahteTG([tg_mesaj(1, "/durum", chat=GRUP, kimden=555), tg_mesaj(2, "/dur", chat=CHAT), bot]))
    assert t.komutlari_al() == ["/durum"] and t.yetkisiz_sayisi == 2


def test_telegram_ozel_sohbette_from_id_hala_zorunlu():
    t = tg.Telegram(TOKEN, CHAT, SahteTG([tg_mesaj(1, "/dur", kimden=999), tg_mesaj(2, "/durum"), tg_mesaj(3, "/dur", chat=GRUP, kimden=int(CHAT))]))
    assert t.komutlari_al() == ["/durum"] and t.yetkisiz_sayisi == 2


# ================================================================================================ 4. S-6 açıklanmayan HL sıçraması
def test_s6_transfer_benzeri_dusus_dur_bir_okuma_ertelenir_sonra_dur(tmp_path, monkeypatch):
    """Altın örnek: kasa 1.000, HL 1.000, yerel 1.000 → ofset 0. HL 750 (ledger'da yatırma/çekme yok; ör. `send`), yerel 1.000 sabit:
    açıklanmayan = (750 − 1.000) − (1.000 − 1.000) = −250 $; |−250| > 1.000 × 0,10 = 100 → `hl_sicrama` + mutabakat bayrağı + alarm; zirve düşüşü %25 ≥ %20 AMA DUR YOK (ertelendi).
    Sonraki okuma HL yine 750: açıklanmayan 0 → erteleme kalkar → DUR (zirve_dusus)."""
    m, sim, saat, tgp = kur_gercek(tmp_path, monkeypatch, BorsaSim(deger=1000.0))
    m.baslat()
    m.dakika()
    assert m.hl_ofset == pytest.approx(0.0) and not kayitlar(tmp_path, "hl_sicrama")
    sim.deger = 750.0
    saat.ms += 60_000
    m.dakika()
    s = kayitlar(tmp_path, "hl_sicrama")
    assert len(s) == 1 and s[0]["aciklanmayan_usd"] == pytest.approx(-250.0) and s[0]["esik_usd"] == pytest.approx(100.0)
    assert not m.risk.dur and not (tmp_path / "durum" / "DUR").exists() and m.risk.acilis_durdu["mutabakat"] is True
    assert any("açıklanamayan sıçrama" in x for x in tgp.gonderilen) and kayitlar(tmp_path, "risk_ertelendi")
    saat.ms += 60_000
    m.dakika()
    assert m.risk.dur and m.risk.dur_neden == "zirve_dusus"


def test_s6_esik_alti_degisim_ve_yerel_defterle_aciklanan_kayip_hemen_dur(tmp_path, monkeypatch):
    """(a) HL 1.000 → 905: açıklanmayan −95 ≤ 100 → sıçrama yok. (b) Yerel defter de −250 realize (gerçek kayıp), HL 750: açıklanmayan (750 − 905) − (750 − 1.000) = +95 ≤ 100
    → erteleme YOK, zirve düşüşü %25 → DUR aynı adımda (gerçek kayıpta fren gecikmez)."""
    m, sim, saat, _ = kur_gercek(tmp_path, monkeypatch, BorsaSim(deger=1000.0))
    m.baslat()
    m.dakika()
    sim.deger = 905.0
    saat.ms += 60_000
    m.dakika()
    assert not kayitlar(tmp_path, "hl_sicrama") and not m.risk.dur
    m.hesap.realize[adr(1)] = -250.0
    sim.deger = 750.0
    saat.ms += 60_000
    m.dakika()
    assert not kayitlar(tmp_path, "hl_sicrama") and not kayitlar(tmp_path, "risk_ertelendi") and m.risk.dur


def test_s6_sanal_kip_etkilenmez(tmp_path):
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    for _ in range(3):
        saat.ms += 60_000
        m.dakika()
    assert m._hl_onceki is None and not kayitlar(tmp_path, "hl_sicrama") and not kayitlar(tmp_path, "risk_ertelendi")


# ================================================================================================ 5. bekçi ↔ uzun kapanış döngüsü
class YavasBorsa(BorsaSim):
    """Her emir sahte monotonik saati 50 sn ilerletir (yavaş HL: emir zaman aşımı 10 sn + yeniden denemeler)."""

    def __init__(self, saat_s, **k):
        super().__init__(**k)
        self.saat_s = saat_s

    def order(self, *a, **k):
        self.saat_s[0] += 50.0
        return super().order(*a, **k)


def test_bekci_dur_kapanis_dongusu_her_denemede_beslenir(tmp_path, monkeypatch):
    """DUR: 1 coin, 5 bant denemesinin hiçbiri dolmaz; her emir 50 sn → döngü 250 sn > bekçi sınırı 180 sn. Besleme olmasa bekçi tetiklenir (os._exit(1) kapanışın ortasında);
    beslemeyle son nabız son denemede → tetik yok."""
    saat_s = [0.0]
    sim = YavasBorsa(saat_s, deger=1000.0, doluluk=(1.0, 0.0))
    m, sim, saat, _ = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    cikis: list[int] = []
    bekci = mt.Bekci(m, 180, saat=lambda: saat_s[0], cik=cikis.append, alarm_bekle_sn=0.1)
    beslemesiz = mt.Bekci(m, 180, saat=lambda: saat_s[0], cik=cikis.append, alarm_bekle_sn=0.1)
    m.bekci_nabiz = bekci.nabiz
    bekci.nabiz()
    beslemesiz.nabiz()
    t0 = saat_s[0]
    m.dur_tetikle("komut")
    assert saat_s[0] - t0 == pytest.approx(250.0) and len(sim.siparisler) == 6                 # 1 açılış + 5 kapanış denemesi
    assert bekci.kontrol() is False and cikis == []
    assert beslemesiz.kontrol() is True and cikis == [1]                                       # eski davranış: kapanış sürerken süreç öldürülürdü


# ================================================================================================ 6. mutabakat yarışı
def test_mutabakat_kilit_disi_hl_okumasindan_sonra_dolum_sahte_alarm_vermez(tmp_path, monkeypatch):
    """HL anlık görüntüsü (BTC 0) kilit dışında alınır; hemen ardından tüketici iş parçacığı bir açılış işler (borsa + defter BTC 0,27273 ≈ 27,27 $ > kasa × %1 = 10 $).
    ESKİ: eski görüntü (0) ↔ yeni defter (0,27273) → sahte `mutabakat_alarm` + açılış durur. YENİ: imza değişti → HL kilit altında yeniden okunur → fark yok."""
    m, sim, saat, tgp = kur_gercek(tmp_path, monkeypatch, BorsaSim(deger=1000.0))
    m.baslat()
    m.dakika()
    asil = m.hl_oku
    yaris = {"bir": True}

    def hl_oku_yaris():
        r = asil()
        if yaris["bir"]:
            yaris["bir"] = False
            m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))           # okumadan SONRA gelen dolum
        return r
    monkeypatch.setattr(m, "hl_oku", hl_oku_yaris)
    saat.ms += 60_000
    m.dakika()
    assert sim.poz["BTC"] == pytest.approx(0.27273, abs=1e-5) and m.hesap.sz(adr(1), "BTC") == pytest.approx(0.27273, abs=1e-5)
    assert kayitlar(tmp_path, "mutabakat_yeniden_okuma") and not kayitlar(tmp_path, "mutabakat_alarm") and not m.risk.acilis_durdu.get("mutabakat")


# ================================================================================================ 7. calis() uçtan uca
def test_calis_kisa_vardiya_olay_isler_durum_yazar_temiz_biter(tmp_path):
    """Sanal kip, sahte HL + WS + saat. WS bir canlı userFills (trader 300 BTC alış, hesap 100.000 $) verir → emir (27,27 $ ≈ 0,27273 BTC); `sure_sn` 1 sn dolunca
    temiz kapanış: `kapanis` kaydı, ozet.json, motor.json, kilit bırakıldı, bekçi tetiklenmedi."""
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    hl.pozlar[adr(1)] = {"BTC": 300.0}                                                       # REST senkronu dolumdan sonraki trader pozisyonunu görür (kapatma yok)
    ws = [SahteWS([userfills(adr(1), 1, saat())], "bekle")]

    async def baglan():
        if not ws:
            return SahteWS([], "bekle")
        return ws.pop(0)
    ozet = asyncio.run(mt.calis(m, sure_sn=1.0, ws=baglan, cikti=tmp_path / "dinleyici"))
    emir = kayitlar(tmp_path, "emir")
    assert len(emir) == 1 and emir[0]["coin"] == "BTC" and m.hesap.sz(adr(1), "BTC") == pytest.approx(0.27273, abs=1e-5)
    assert kayitlar(tmp_path, "kapanis") and not kayitlar(tmp_path, "bekci_tetik") and not kayitlar(tmp_path, "gorev_bitti")
    assert json.loads((tmp_path / "durum" / "ozet.json").read_text(encoding="utf-8"))["kip"] == ozet["kip"] == "sanal"
    assert (tmp_path / "durum" / "motor.json").exists() and json.loads((tmp_path / "durum" / "kilit.json").read_text(encoding="utf-8"))["birakildi"] is True
    assert getattr(m, "cikis_kodu", 0) == 0 and m.bekci_nabiz is not None
