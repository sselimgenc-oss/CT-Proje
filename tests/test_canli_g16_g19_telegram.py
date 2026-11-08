"""Proje denetimi 2026-11-08 (docs/DENETIM_PROJE_2026-11-08.md): G-16 (Telegram komutları), G-18 (alarm teslimi + M-3), G-19 (HL hata metni, agent süresi),
S-13 (atlanan sinyal metni, tek ATLA_TR), S-22 (kip etiketi, "kapalı"). Elle hesaplanmış altın örnekler; ağsız (sahte Telegram / borsa)."""
from __future__ import annotations

import json
import sys
import time
import types

import pytest

from copytrade.canli import telegram as tg
from tests.test_canli_motor import CHAT, RULES, SAAT, T0, TOKEN, SahteHL, SahteTG, Saat, adr, kadro, kayitlar, kur, kur_kip, mt, olay, satir, tg_mesaj, yu
from tests.test_canli_yurutucu import SahteExchange, dolu, meta_post


# ================================================================================================ G-16: komutlar
def test_g16_komut_adi_ilk_sozcuk_kapat_hemen_yurutulur(tmp_path):
    assert tg.komut_adi("/kapat hemen") == "/kapat" and tg.komut_adi("  /DURUM@sg_bot  şimdi") == "/durum" and tg.komut_adi("") == ""
    tgp = SahteTG([tg_mesaj(1, "/kapat hemen")])
    m, hl, saat, _ = kur(tmp_path, tgp=tgp)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    m.dakika()
    assert m.risk.dur and any(k["olay"] == "dur" and k["neden"] == "komut" for k in kayitlar(tmp_path))          # "/kapat hemen" = /kapat: YÜRÜTÜLDÜ
    assert "🛑 /kapat alındı (sanal · deneme parası): tüm pozisyonlar reduce-only kapatılıyor; bitince ayrı mesaj gelecek." in tgp.gonderilen
    assert m.hesap.sz(adr(1), "BTC") == 0.0


def test_g16_bilinmeyen_komut_yanit_alir_yurutulmez():
    t = tg.Telegram(TOKEN, CHAT, SahteTG([tg_mesaj(1, "/stop"), tg_mesaj(2, "/yardim lütfen")]))
    assert t.komutlari_al() == []
    assert t.gonderilen == ["❓ Bilinmeyen komut: /stop. Geçerli komutlar: /dur /devam /kapat /durum\n"
                            "❓ Bilinmeyen komut: /yardim. Geçerli komutlar: /dur /devam /kapat /durum"]
    t.post.guncellemeler.append(tg_mesaj(1, "/stop"))                     # aynı update yeniden gelse ikinci yanıt yok
    t.komutlari_al()
    assert len(t.gonderilen) == 1


def test_g16_15_dakikadan_eski_komut_yurutulmez_ama_yanit_alir():
    simdi = 1_800_000_000.0
    t = tg.Telegram(TOKEN, CHAT, SahteTG([tg_mesaj(1, "/kapat", tarih=simdi - 3600),          # motor 2 saattir açık; komut 60 dk önce (dakika döngüsü takılı kalmış gibi)
                                          tg_mesaj(2, "/durum", tarih=simdi - 14 * 60)]),     # 14 dk: sınır içinde → yürütülür
                    baslangic_s=simdi - 7200, saat_s=lambda: simdi)
    assert t.komutlari_al() == ["/durum"]
    assert t.gonderilen == ["📭 /kapat 60 dk önce geldi, 15 dk sınırını aştı; İŞLENMEDİ. Hâlâ istiyorsan yeniden gönder."]
    # motor kapalıyken gelen (başlangıçtan önce): §5 örneği birebir
    t2 = tg.Telegram(TOKEN, CHAT, SahteTG([tg_mesaj(5, "/kapat", tarih=simdi - 23 * 60)]), baslangic_s=simdi - 60, saat_s=lambda: simdi)
    assert t2.komutlari_al() == [] and t2.gonderilen == ["📭 /kapat 23 dk önce geldi, motor o sırada kapalıydı; İŞLENMEDİ. Hâlâ istiyorsan yeniden gönder."]


def test_g16_offset_yalniz_komutlar_bitince_kalici(tmp_path):
    tgp = SahteTG([tg_mesaj(10, "/dur")])
    m, hl, saat, _ = kur(tmp_path, tgp=tgp)
    m.baslat()
    motor_json = lambda: json.loads((tmp_path / "durum" / "motor.json").read_text(encoding="utf-8"))        # noqa: E731
    komutlar = m.tg.komutlari_al()                                        # `dakika`: ağ okuması kilitsiz
    assert komutlar == ["/dur"] and m.tg.offset == 11 and m.tg.kalici_offset == 0
    m.durum_yaz()                                                         # olay iş parçacığı araya girip motor.json yazarsa: offset İLERLEMEZ
    assert motor_json()["tg_offset"] == 0
    # burada çökme olursa: yeniden açılışta komut tekrar okunur, yürütülmez ama "İŞLENMEDİ" yanıtı gider (iz bırakmadan kaybolmaz)
    simdi = time.time()
    t2 = tg.Telegram(TOKEN, CHAT, SahteTG([tg_mesaj(10, "/dur", tarih=simdi - 120)]), baslangic_s=simdi, saat_s=lambda: simdi)
    t2.offset = motor_json()["tg_offset"]
    assert t2.komutlari_al() == [] and len(t2.gonderilen) == 1 and "/dur 2 dk önce geldi, motor o sırada kapalıydı; İŞLENMEDİ" in t2.gonderilen[0]
    m._komutlar(komutlar)                                                 # komut yürütüldü → onay → kalıcı
    assert m.risk.acilis_durdu["elle_dur"] and m.tg.kalici_offset == 11
    m.durum_yaz()
    assert motor_json()["tg_offset"] == 11


def test_g16_dakika_akisi_offset_ve_hata_halinde_de_onay(tmp_path):
    tgp = SahteTG([tg_mesaj(3, "/durum")])
    m, hl, saat, _ = kur(tmp_path, tgp=tgp)
    m.baslat()
    m.durum_metni = lambda: (_ for _ in ()).throw(RuntimeError("x"))     # komut yürütme hata verse de (adım hatası) offset onaylanır: aynı komut sonsuza dek tekrar okunmaz
    m.dakika()
    assert m.tg.kalici_offset == 4 and json.loads((tmp_path / "durum" / "motor.json").read_text(encoding="utf-8"))["tg_offset"] == 4
    assert any(k["olay"] == "adim_hata" and k["adim"] == "telegram" for k in kayitlar(tmp_path))


# ================================================================================================ G-18: teslim, 🚨, tampon, M-3
def _sahte_post(hatalar):
    """İlk len(hatalar) çağrıda sırayla istisna atar / yanıt döner; sonra başarı."""
    cagrilar = []

    def post(url, yuk):
        cagrilar.append(yuk.get("text"))
        if len(cagrilar) <= len(hatalar):
            h = hatalar[len(cagrilar) - 1]
            if isinstance(h, Exception):
                raise h
            return h
        return {"ok": True}
    return post, cagrilar


def test_g18_onemli_mesaj_3_kez_yeniden_denenir_2_5_15():
    post, cagrilar = _sahte_post([ConnectionError("a"), ConnectionError("b")])
    bekle, kayit = [], []
    t = tg.Telegram(TOKEN, CHAT, post, uyku=bekle.append, kayit=kayit.append)
    assert t.gonder(tg.alarm("ALARM: x", "y")) is True and len(cagrilar) == 3 and bekle == [2.0, 5.0] and t.hata_sayisi == 0
    post, cagrilar = _sahte_post([ConnectionError()] * 9)
    bekle = []
    t = tg.Telegram(TOKEN, CHAT, post, uyku=bekle.append, kayit=kayit.append)
    assert t.gonder(tg.alarm("ALARM: x", "y")) is False and len(cagrilar) == 4 and bekle == [2.0, 5.0, 15.0] and t.hata_sayisi == 1      # 1 + 3 deneme
    assert [k["deneme"] for k in kayit if k["olay"] == "telegram_hata"] == [4]
    post, cagrilar = _sahte_post([ConnectionError()] * 9)                  # önemsiz mesaj: tek deneme
    bekle = []
    t = tg.Telegram(TOKEN, CHAT, post, uyku=bekle.append)
    assert t.gonder("🧾 Son 1 saat …") is False and len(cagrilar) == 1 and bekle == []
    post, cagrilar = _sahte_post([ConnectionError()] * 9)                  # eşzamanlı yol (test/--kontrol; uyku verilmedi): bekleme yok, tek deneme
    t = tg.Telegram(TOKEN, CHAT, post)
    assert t.gonder(tg.alarm("ALARM: x", "y")) is False and len(cagrilar) == 1


def test_g18_429_retry_after_kadar_beklenir_tavan_60():
    post, cagrilar = _sahte_post([tg.CokIstek(30)])
    bekle = []
    assert tg.Telegram(TOKEN, CHAT, post, uyku=bekle.append).gonder(tg.alarm("ALARM: x", "y")) and bekle == [30.0]          # max(2, 30)
    post, cagrilar = _sahte_post([{"ok": False, "error_code": 429, "parameters": {"retry_after": 7}}])     # 200 gövdesinde 429
    bekle = []
    assert tg.Telegram(TOKEN, CHAT, post, uyku=bekle.append).gonder("🧾 bilgi") and bekle == [7.0] and len(cagrilar) == 2      # önemsiz mesaj da 429'da bir kez
    post, cagrilar = _sahte_post([tg.CokIstek(500)])
    bekle = []
    assert tg.Telegram(TOKEN, CHAT, post, uyku=bekle.append).gonder(tg.alarm("ALARM: x", "y")) and bekle == [60.0]          # tavan


def test_g18_varsayilan_post_429_retry_after_okur(monkeypatch):
    class Yanit:
        status_code = 429

        def json(self):
            return {"ok": False, "error_code": 429, "parameters": {"retry_after": 3}}
    monkeypatch.setitem(sys.modules, "requests", types.SimpleNamespace(post=lambda url, json, timeout: Yanit()))
    with pytest.raises(tg.CokIstek) as e:
        tg.varsayilan_post("https://x/sendMessage", {})
    assert e.value.retry_after == 3.0


def test_g18_gercek_kip_dolmayan_emir_sesli_altin_ornek():
    a = "0x1234567890abcdef"
    m = tg.msg_emir(a, "BTC", "A", 27.30, None, None, "red", "gercek", "kapat", "hl_err: User or API Wallet 0xabc does not exist.")
    assert m == ("🚨 [GERÇEK] EMİR REDDEDİLDİ — BTC kapat 27,30 $\n"
                 "neden: hl_err: User or API Wallet 0xabc does not exist.\n"
                 "Kapanış daha geniş bantla yeniden denenecek; olmazsa kuyruğa alınır ve dakikada bir denenir. Tekrarlarsa: /kapat ya da HL web.\n"
                 "↳ Trader 0x123456… · SAT")
    gece = tg.Telegram(TOKEN, CHAT, SahteTG(), sessiz_utc=(21, 5), saat_s=lambda: 1_800_000_000 - 1_800_000_000 % 86400 + 2 * 3600)     # 02:00 UTC
    assert not gece.sessiz_mi(m) and gece.sessiz_mi("🟢 BTC AL: 27 $")                                     # 🚨 gece de sesli; dolu emir sessiz
    assert tg.msg_emir(a, "ETH", "B", 11.0, None, None, "kismi", "gercek", "ac").startswith("🚨 [GERÇEK] EMİR KISMEN DOLDU — ETH ac 11,00 $\nPozisyon açılmadı")
    assert tg.msg_emir(a, "BTC", "A", 272.73, 100.0, None, "dolmadi", "sanal", "kapat").startswith("⚠️ BTC SAT: emir tam dolmadı (dolmadi)")      # sanal değişmez
    assert tg.msg_emir(a, "BTC", "B", 27.3, 100.0, None, "dolu", "gercek", "ac").startswith("🟢 BTC AL: 27,3 $ (GERÇEK PARA)")


def test_g18_gercek_kip_emir_mesajlari_tamponda_birlesir(tmp_path):
    class Gercek:
        kip = "gercek"

        def __init__(self):
            self.n = 0

        def hazirla(self, coin):
            return None

        def emir(self, coin, yon, usd, reduce_only=False, acik_sz=None, bant=None, cloid=None):
            self.n += 1
            if self.n == 2:
                return yu.Dolum(coin, yon, usd, reduce_only=reduce_only, durum="red", neden="hl_err: Invalid nonce")
            return yu.Dolum(coin, yon, usd, usd_dolan=usd, sz=usd / 100, px=100.0, reduce_only=reduce_only, durum="dolu")
    zamanlar = []
    tgp = SahteTG()
    t = tg.Telegram(TOKEN, CHAT, tgp, zamanlayici=lambda sn, f: zamanlar.append((sn, f)) or "z")
    saat = Saat()
    m = mt.Motor(RULES, Gercek(), SahteHL(), t, tmp_path / "durum", tmp_path / "kayit", lambda: kadro([satir(1, 1), satir(2, 2)], T0), saat)
    assert 2 <= float(RULES["canli_telegram_gercek_tampon_sn"]) <= 3 and t.tampon_sn == float(RULES["canli_telegram_gercek_tampon_sn"])
    m.baslat()
    once = len(tgp.gonderilen)
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    m.olay_isle(olay("a:2", adr(2), "ETH", "B", 300, 2000.0, 0.0, saat))
    assert len(tgp.gonderilen) == once and len(zamanlar) == 1 and zamanlar[0][0] == t.tampon_sn          # tek zamanlayıcı, henüz mesaj yok
    zamanlar[0][1]()                                                                                       # 2,5 sn doldu
    yeni = tgp.gonderilen[once:]
    assert len(yeni) == 1
    satirlar = yeni[0].splitlines()
    assert satirlar[0].startswith("🚨 [GERÇEK] EMİR REDDEDİLDİ — ETH ac ") and satirlar[0].endswith(" · hl_err: Invalid nonce")
    assert satirlar[1] == "🧾 Son birkaç saniyede 2 emir (GERÇEK PARA)" and not t.sessiz_mi(yeni[0])
    m.olay_isle(olay("a:3", adr(1), "BTC", "B", 300, 100.0, 300.0, saat))
    m.emir_ozeti(m.saat_ms(), zorla=True)                                                                  # vardiya sonu: tampon beklemeden gider
    assert len(tgp.gonderilen) == once + 2 and tgp.gonderilen[-1].startswith("🟢 BTC AL")


def test_m3_kapanis_pozisyonla_kirpilip_tamami_dolarsa_dolu_altin_ornek():
    # açık 0,27273 BTC; motor kapanışta kalan × mk × 1,05 = 0,27273 × 99,9 × 1,05 = 28,6079 $ ister → sz = 28,6079 / 99,9 = 0,28636 → pozisyonla 0,27273'e kırpılır
    istek = 0.27273 * 99.9 * 1.05
    ex = SahteExchange(dolu("0.27273", "99.8"))
    d = yu.GercekYurutucu(ex, meta_post, RULES).emir("BTC", "A", istek, reduce_only=True, acik_sz=0.27273)
    assert ex.cagrilar[0]["sz"] == 0.27273 and d.usd_dolan == pytest.approx(27.218454) and d.usd_dolan < istek * 0.999
    assert d.durum == "dolu"                                                                  # 27,22 $ < 28,61 $ ama pozisyonun TAMAMI kapandı (eskiden "kismi")
    k = yu.GercekYurutucu(SahteExchange(dolu("0.2", "99.8")), meta_post, RULES).emir("BTC", "A", istek, reduce_only=True, acik_sz=0.27273)
    assert k.durum == "kismi"                                                                 # 0,2 < 0,27273: gerçekten kısmi
    a = yu.GercekYurutucu(SahteExchange(dolu("0.1", "99.8")), meta_post, RULES).emir("BTC", "A", 15.0, reduce_only=True, acik_sz=0.27273)
    assert a.durum == "kismi"                                                                 # azaltma (kırpılmadı): 9,98 $ < 15 $ → kısmi kalır
    # sanal: defter 99,9'da 0,2 + 99'da 0,5; bant %2 → 0,27273 tamamı dolar (0,2 × 99,9 + 0,07273 × 99 = 27,1803 $ < 28,61 $) → DOLU
    kitap = lambda y: {"levels": [[{"px": "99.9", "sz": "0.2"}, {"px": "99", "sz": "0.5"}], [{"px": "100", "sz": "1"}]]}       # noqa: E731
    s = yu.SanalYurutucu(kitap, {**RULES, "canli_ioc_bant": 0.02}).emir("BTC", "A", istek, reduce_only=True, acik_sz=0.27273)
    assert s.sz == pytest.approx(0.27273) and s.usd_dolan == pytest.approx(27.180270) and s.durum == "dolu"
    s2 = yu.SanalYurutucu(kitap, RULES).emir("BTC", "A", istek, reduce_only=True, acik_sz=0.27273)        # bant %0,5: yalnız 0,2 → kısmi
    assert s2.sz == pytest.approx(0.2) and s2.durum == "kismi"


def test_m3_motor_tam_kapanis_kismi_sayilmaz(tmp_path):
    m, hl, saat, tgp = kur(tmp_path)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    m.olay_isle(olay("a:2", adr(1), "BTC", "A", 300, 100.0, 300.0, saat))                 # trader kapattı → motor kalan × mk × 1,05 ister
    kap = [k for k in kayitlar(tmp_path, "emir") if k["eylem"] == "kapat"]
    assert len(kap) == 1 and kap[0]["usd_istenen"] > kap[0]["usd_dolan"] and kap[0]["durum"] == "dolu" and m.sayac["kismi"] == 0


# ================================================================================================ G-19
def test_g19_ust_duzey_hl_err_neden_ve_ham():
    metin = "User or API Wallet 0xabc does not exist."
    d = yu.GercekYurutucu(SahteExchange({"status": "err", "response": metin}), meta_post, RULES).emir("BTC", "B", 11.0)
    assert d.durum == "red" and d.neden == f"hl_err: {metin}" and d.ham == {"status": "err", "response": metin} and d.sz == 0
    uzun = yu.GercekYurutucu(SahteExchange({"status": "err", "response": "x" * 500}), meta_post, RULES).emir("BTC", "B", 11.0)
    assert uzun.neden == "hl_err: " + "x" * 160

    class ClientError(Exception):
        error_message = "Insufficient margin"
    c = yu.GercekYurutucu(SahteExchange(hata=ClientError(400, None, "Insufficient margin")), meta_post, RULES).emir("BTC", "B", 11.0)
    assert c.durum == "red" and c.ham == {"istisna": "ClientError", "metin": "Insufficient margin"}


def test_g19_red_ham_yanit_emir_kaydina_300_karakter(tmp_path):
    ham = {"status": "err", "response": "Invalid nonce: " + "z" * 600}

    class Gercek:
        kip = "gercek"

        def hazirla(self, coin):
            return None

        def emir(self, coin, yon, usd, reduce_only=False, acik_sz=None, bant=None, cloid=None):
            return yu.Dolum(coin, yon, usd, reduce_only=reduce_only, durum="red", neden="hl_err: Invalid nonce", ham=ham)
    m = mt.Motor(RULES, Gercek(), SahteHL(), tg.Telegram("", "", ortam={}), tmp_path / "durum", tmp_path / "kayit", lambda: kadro([satir(1, 1)], T0), Saat())
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, Saat()))
    e = kayitlar(tmp_path, "emir")[0]
    assert e["red_neden"] == "hl_err: Invalid nonce" and len(e["ham"]) == 300 and e["ham"].startswith('{"status": "err", "response": "Invalid nonce: zzz')


def test_g19_ajan_suresi_gunluk_7_gun_uyari(tmp_path, monkeypatch):
    m, saat = kur_kip(tmp_path, "gercek")
    simdi = saat()
    agent = "0x" + "a" * 40
    istekler = []

    def post(y):
        istekler.append(y["type"])
        assert y["type"] == "extraAgents" and y["user"] == "0x" + "b" * 40
        return [{"name": "sg", "address": agent.upper().replace("0X", "0x"), "validUntil": simdi + 5 * 86_400_000}]
    monkeypatch.setenv("HL_API_CUZDAN_ANAHTARI", "gizli-anahtar")
    monkeypatch.setenv("HL_HESAP_ADRESI", "0x" + "b" * 40)
    m.post, m.ajan_turet = post, (lambda anahtar: agent)
    okuma = m.ajan_suresi_oku(simdi)
    assert okuma == {"durum": "bulundu", "valid_until": simdi + 5 * 86_400_000} and "gizli" not in json.dumps(okuma)
    assert m.ajan_suresi_oku(simdi + 3600_000) is None and istekler == ["extraAgents"]          # günde bir
    tgp = m.tg.post
    m.ajan_suresi_uygula(okuma, simdi)
    al = [x for x in tgp.gonderilen if "API cüzdanı süresi" in x]
    assert len(al) == 1 and al[0].startswith("🚨 ALARM: API cüzdanı süresi (GERÇEK PARA)\n") and "süresi 5.0 gün sonra bitiyor" in al[0]
    m.ajan_suresi_uygula({"durum": "bulundu", "valid_until": simdi + 8 * 86_400_000}, simdi)       # 8 gün: alarm yok
    m.ajan_suresi_uygula({"durum": "bulundu", "valid_until": simdi - 1}, simdi)                    # doldu
    assert len([x for x in tgp.gonderilen if "API cüzdanı süresi" in x]) == 2 and "süresi DOLDU" in tgp.gonderilen[-1]
    m.ajan_suresi_uygula({"durum": "listede_yok", "agent_rol": False}, simdi)
    assert "API cüzdanı HL'de yok" in tgp.gonderilen[-1]
    n = len(tgp.gonderilen)
    m.ajan_suresi_uygula({"durum": "listede_yok", "agent_rol": True}, simdi)                       # userRole hâlâ agent: alarm yok
    m.ajan_suresi_uygula({"durum": "okunamadi", "tur": "ConnectionError"}, simdi)
    assert len(tgp.gonderilen) == n and len(kayitlar(tmp_path, "ajan_suresi")) == 6


def test_g19_ajan_suresi_sanal_kipte_okunmaz(tmp_path):
    m, hl, saat, _ = kur(tmp_path)
    m.post = lambda y: (_ for _ in ()).throw(AssertionError(y))
    assert m.ajan_suresi_oku(saat()) is None


def test_g19_ajan_bitis_oku_listede_yoksa_userrole():
    agent, hesap = "0x" + "a" * 40, "0x" + "b" * 40
    ortam = {"HL_API_CUZDAN_ANAHTARI": "k", "HL_HESAP_ADRESI": hesap}
    post = lambda y: [] if y["type"] == "extraAgents" else {"role": "agent", "data": {"user": hesap}}       # noqa: E731
    assert mt.ajan_bitis_oku(post, ortam, lambda k: agent) == {"durum": "listede_yok", "agent_rol": True}
    post2 = lambda y: [] if y["type"] == "extraAgents" else {"role": "user"}                                # noqa: E731
    assert mt.ajan_bitis_oku(post2, ortam, lambda k: agent) == {"durum": "listede_yok", "agent_rol": False}
    assert mt.ajan_bitis_oku(post, {}, lambda k: agent)["durum"] == "okunamadi"


# ================================================================================================ S-13
def test_s13_bolum5_ornekleri_birebir():
    a = "0x8730ab" + "0" * 34
    assert tg.atlanan_satirlari({"inen_trader": 86, "min_emir_atlandi": 21}, 86, {"inen_trader": {a: 86}, "min_emir_atlandi": {a: 21}}) == [
        "⏭️ Kopyalanmayan trader dolumu: 107 (≈86 ayrı işlem)",
        "   • kural gereği 107: 86 ayrılan trader 0x8730ab… (yeni alım yok) · 21 çok küçük (< 11 $)",
        "   • kaçırılan 0 (geç görülen / veri yok)"]
    assert tg.atlanan_satirlari({"gec_acilis": 180, "slot_tavani": 100, "min_emir_atlandi": 61}, 32) == [
        "⚠️ Kopyalanmayan trader dolumu: 341 (≈32 ayrı işlem)",
        "   • kural gereği 161",
        "   • KAÇIRILAN 180: geç görülen açılış"]
    assert tg.atlanan_satirlari({"gec_acilis": 3, "trader_hesap_yok": 2}, 4)[2] == "   • KAÇIRILAN 5: 3 geç görülen açılış · 2 trader hesabı okunamadı"
    assert tg.atlanan_satirlari({}) == []


def test_s13_tek_sozluk_motor_nedenleri_ve_esik():
    from copytrade.canli import pano
    assert not hasattr(pano, "ATLA_ETIKET") and pano.ATLA_TR is tg.ATLA_TR
    assert f"< {float(RULES['radar_min_emir_usd']):g} $" in tg.ATLA_TR["min_emir_atlandi"]           # etiket eşiği kurallarla aynı (11 $)
    risk_nedenleri = {"dur", "patlama_freni", "gunluk_kayip", "mutabakat", "elle_dur", "kasa_siniri", "belirsiz", "kapanis_eksik"}
    motor_nedenleri = {"gec_acilis", "spot_atlandi", "hip3_atlandi", "inen_trader", "ters_netlesme", "trader_hesap_yok", "min_emir_atlandi", "slot_tavani", "hesap_yok",
                       "coin_tavani", "marj_yok", "min_nosyonel"}
    assert (risk_nedenleri | motor_nedenleri) <= set(tg.ATLA_TR)


def test_s13_motor_ayri_islem_sayisi_adres_coin_saniye(tmp_path):
    m, hl, saat, tgp = kur(tmp_path)
    m.baslat()
    m.olay_isle(olay("a:4", adr(1), "@142", "B", 300, 100.0, 0.0, saat, yas_ms=1000))
    m.olay_isle(olay("a:5", adr(1), "@142", "B", 100, 100.0, 300.0, saat, yas_ms=1000))         # aynı saniye: aynı işlem
    m.olay_isle(olay("a:6", adr(1), "@142", "B", 100, 100.0, 400.0, saat, yas_ms=3000))         # farklı saniye
    saat.ms += SAAT
    m.emir_ozeti(saat())
    oz = [x for x in tgp.gonderilen if "Kopyalanmayan trader dolumu" in x]
    assert len(oz) == 1 and "⏭️ Kopyalanmayan trader dolumu: 3 (≈2 ayrı işlem)\n   • kural gereği 3: 3 spot coin\n   • kaçırılan 0 (geç görülen / veri yok)" in oz[0]
    assert m._atla_islem == set() and m._atla_adres == {}


# ================================================================================================ S-22
def test_s22_telegram_komut_kapali_turkce_yazim():
    for d in ("kapali", "kapalı", "KAPALI", "KAPALİ", " Kapalı "):
        assert tg.komut_kapali_mi(d), d
    for d in ("", "açık", "acik", "kapalidegil"):
        assert not tg.komut_kapali_mi(d), d
    cagri = []
    t = tg.Telegram("T", "5", lambda u, y: cagri.append(u) or {"ok": True, "result": []}, ortam={"TELEGRAM_KOMUT": "kapalı"})
    assert t.komut_kapali and t.komutlari_al() == [] and cagri == []


def test_s22_alarm_basligina_kip_etiketi(tmp_path):
    t = tg.Telegram(TOKEN, CHAT, SahteTG())
    t.kip = "gercek"
    t.gonder(tg.alarm("ALARM: kasa sınırı aşıldı", "Kasa 1.200 $."))
    assert t.gonderilen[-1] == "🚨 ALARM: kasa sınırı aşıldı (GERÇEK PARA)\n━━━━━━━━━━━━━━\nKasa 1.200 $."
    t.gonder(tg.msg_durum("gercek", 300.0, 300.0, 9, 11, 0, 0, 0, False))              # başlıkta kip zaten var: dokunulmaz
    assert t.gonderilen[-1].startswith("📊 Anlık durum (GERÇEK PARA)\n") and t.gonderilen[-1].count("GERÇEK PARA") == 1
    t.gonder("🟢 düz mesaj")
    assert t.gonderilen[-1] == "🟢 düz mesaj"
    m, hl, saat, tgp = kur(tmp_path)
    assert m.tg.kip == "sanal"
    m.tg.gonder(tg.alarm("DUR: komut", "x", "🛑"))
    assert tgp.gonderilen[-1].startswith("🛑 DUR: komut (sanal · deneme parası)\n")
