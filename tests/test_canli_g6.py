"""G6 (Y3): gerçek kipte API cüzdanı doğrulaması. Ağsız; sahte `post` + ENJEKTE türetme (eth_account gerekmez). Yanıt biçimleri gerçek HL `userRole` / `extraAgents` çıktısından
(2026-11-06, herkese açık hesap; adresler burada sahte): agent → {"role":"agent","data":{"user":<ana hesap>}}; ana hesap → {"role":"user"}; extraAgents → [{"name","address","validUntil"}]."""
import json

from copytrade.canli import motor as mt
from copytrade.canli import telegram as tg
from tests.test_canli_motor import CHAT, RULES, TOKEN, SahteHL, SahteTG, adr, n_kadro

HESAP, AGENT = adr(7), adr(9)
ANAHTAR = "gizli-anahtar-xyz"
ORTAM = {"HL_API_CUZDAN_ANAHTARI": ANAHTAR, "HL_HESAP_ADRESI": HESAP, "CANLI_KASA_USD": "300"}


def hl_300():
    return SahteHL(hesap=300.0)


def kont(post, ortam=None, turet=lambda k: AGENT, kip="gercek"):
    return mt.kontrol(RULES, kip, post, lambda: n_kadro(3), tg.Telegram(TOKEN, CHAT, SahteTG()), ortam=ORTAM if ortam is None else ortam, turet=turet)


def test_dogru_agent_ve_300_usd_tamam_anahtar_adres_rapora_yazilmaz():
    r = kont(hl_300())
    assert r["tamam"] is True and r["ana_anahtar"] is False and r["agent_dogrulandi"] is True and r["api_cuzdan_tamam"] is True and r["hl_deger_siniri_ok"] is True
    ham = json.dumps(r)
    assert ANAHTAR not in ham and HESAP not in ham and AGENT not in ham


def test_ana_anahtar_ret():
    r = kont(hl_300(), turet=lambda k: HESAP.upper().replace("0X", "0x"))                       # büyük/küçük harf farkı eşitliği bozmaz
    assert r["ana_anahtar"] is True and r["tamam"] is False and r["agent_dogrulandi"] is False and "ana cüzdan" in r["api_cuzdan_neden"]


def test_agent_degil_ret():
    h = hl_300()
    h.agent_sahibi = None                                                                         # userRole -> {"role": "user"}
    r = kont(h)
    assert r["tamam"] is False and r["agent_dogrulandi"] is False and r["api_cuzdan_neden"] == "agent doğrulanamadı"


def test_agent_baska_hesaba_bagli_ret():
    h = hl_300()
    h.agent_sahibi = adr(5)
    assert kont(h)["tamam"] is False


def test_userrole_bozuk_bicim_savunmaci_extraagents_yedegi():
    class Bozuk(SahteHL):
        extra = None

        def __call__(self, y):
            if y["type"] == "userRole":
                return {"beklenmeyen": 1}
            if y["type"] == "extraAgents":
                assert y["user"] == HESAP                                                          # yedek yöntem ana hesabı sorar
                return self.extra
            return super().__call__(y)
    b = Bozuk(hesap=300.0)
    assert kont(b)["agent_dogrulandi"] is False                                                   # extraAgents None -> doğrulanamadı
    b.extra = [{"name": "x", "address": adr(3), "validUntil": 1}, {"name": "IMS", "address": AGENT.upper().replace("0X", "0x"), "validUntil": 4102444800000}]
    r = kont(b)
    assert r["agent_dogrulandi"] is True and r["tamam"] is True


def test_adres_bicimi_gecersiz_ayri_neden_ana_anahtar_yaniltmaz():
    r = kont(hl_300(), ortam={**ORTAM, "HL_HESAP_ADRESI": HESAP[2:]}, turet=lambda k: HESAP)                # 0x'siz hesap + ana anahtar
    assert r["tamam"] is False and r["api_cuzdan_neden"] == "adres biçimi geçersiz" and HESAP[2:] not in json.dumps(r)
    for kotu in ("0x123", "0x" + "g" * 40):
        assert kont(hl_300(), turet=lambda k, kotu=kotu: kotu)["api_cuzdan_neden"] == "adres biçimi geçersiz"


def test_extraagents_validuntil_gecerli_kabul_dolmus_veya_yok_ret():
    class Ex(SahteHL):
        vu: dict = {}

        def __call__(self, y):
            if y["type"] == "userRole":
                return {"role": "user"}
            if y["type"] == "extraAgents":
                return [{"name": "IMS", "address": AGENT, **self.vu}]
            return super().__call__(y)
    e = Ex(hesap=300.0)
    for vu, beklenen in (({"validUntil": 2_000}, True), ({"validUntil": 1_000}, False), ({"validUntil": 999}, False), ({}, False), ({"validUntil": "x"}, False), ({"validUntil": None}, False)):
        e.vu = vu
        assert mt.api_cuzdan_dogrula(e, ORTAM, lambda k: AGENT, simdi_ms=1_000)["agent_dogrulandi"] is beklenen, vu


def test_userrole_hata_atarsa_ret_istisna_sizmaz():
    class Hata(SahteHL):
        def __call__(self, y):
            if y["type"] in ("userRole", "extraAgents"):
                raise ConnectionError("x")
            return super().__call__(y)
    r = kont(Hata(hesap=300.0))
    assert r["tamam"] is False and r["agent_dogrulandi"] is False


def test_hl_degeri_1501_usd_ret_k22_1200_usd_gecer():
    """K‑22 (09.11): HL değer tavanı `canli_hl_deger_ust_usd` = 1.500 $ (kasa sınırı 1.000 $ ayrı). 1.501 $ → ret; 1.200 $ → geçer (eskiden ret: kârlı günden sonra kontrol takılırdı)."""
    r = kont(SahteHL(hesap=1501.0))
    assert r["hl_hesap_degeri"] == 1501.0 and r["hl_deger_siniri_ok"] is False and r["tamam"] is False and r["agent_dogrulandi"] is True
    r = kont(SahteHL(hesap=1200.0))
    assert r["hl_hesap_degeri"] == 1200.0 and r["hl_deger_siniri_ok"] is True and r["etkin_kasa_usd"] == 300.0


def test_turetme_basarisiz_veya_eth_account_yok_tamam_false_neden():
    def yok(k):
        raise ImportError("eth_account")
    r = kont(hl_300(), turet=yok)
    assert r["tamam"] is False and "türetilemedi (ImportError)" in r["api_cuzdan_neden"] and ANAHTAR not in json.dumps(r)
    try:
        import eth_account  # noqa: F401
    except ImportError:                                                                           # varsayılan türetme: eth_account yoksa hata değil tamam=false
        r2 = mt.kontrol(RULES, "gercek", hl_300(), lambda: n_kadro(3), tg.Telegram(TOKEN, CHAT, SahteTG()), ortam=ORTAM)
        assert r2["tamam"] is False and "türetilemedi" in r2["api_cuzdan_neden"]


def test_sanal_kip_etkilenmez():
    h = hl_300()
    r = kont(h, ortam={}, kip="sanal")
    assert r["tamam"] is True and "ana_anahtar" not in r and all(i["type"] != "userRole" for i in h.istekler)


def _main_kur(monkeypatch, post, turet):
    from tests.test_g1_alarm import SahteTg as TabanTg

    class SahteTg(TabanTg):
        ornekler: list = []
        offset, kayit, maske = 0, None, []

    monkeypatch.setattr(TabanTg, "ornekler", [])                                                   # taban sınıf kendi listesine ekler; testler arası sızmasın
    monkeypatch.setattr(mt.tg, "Telegram", SahteTg)
    monkeypatch.setattr(mt, "rest_post_olustur", lambda rules: post)
    monkeypatch.setattr(mt, "kip_belirle", lambda rules, istenen=None, ortam=None: "gercek")
    monkeypatch.setattr(mt, "kasa_belirle", lambda rules, kip, ortam=None: (300.0, "ortam"))
    monkeypatch.setenv("HL_API_CUZDAN_ANAHTARI", ANAHTAR)
    monkeypatch.setenv("HL_HESAP_ADRESI", HESAP)
    monkeypatch.setattr(mt, "anahtardan_adres", turet)
    olustu = []
    monkeypatch.setattr(mt, "gercek_yurutucu_olustur", lambda post, rules: olustu.append(1))
    return TabanTg, olustu


def test_main_ana_anahtar_cikis_3_emir_yolu_kurulmaz_alarm(monkeypatch, tmp_path):
    TabanTg, olustu = _main_kur(monkeypatch, hl_300(), lambda k: HESAP)                           # türetilen adres = ana hesap
    assert mt.main(["--kip", "gercek", "--durum-dizin", str(tmp_path / "durum")]) == 3
    assert not olustu
    mesaj = TabanTg.ornekler[0].gonderilen[0]
    assert "ana cüzdan" in mesaj and ANAHTAR not in mesaj


def test_main_agent_degil_cikis_3(monkeypatch, tmp_path):
    h = hl_300()
    h.agent_sahibi = None
    _, olustu = _main_kur(monkeypatch, h, lambda k: AGENT)
    assert mt.main(["--kip", "gercek", "--durum-dizin", str(tmp_path / "durum")]) == 3 and not olustu


def test_main_hl_degeri_1501_cikis_3(monkeypatch, tmp_path):
    _, olustu = _main_kur(monkeypatch, SahteHL(hesap=1501.0), lambda k: AGENT)
    assert mt.main(["--kip", "gercek", "--durum-dizin", str(tmp_path / "durum")]) == 3 and not olustu


def test_k64_main_hl_ag_ayarliysa_gercek_motor_baslamaz(monkeypatch, tmp_path):
    TabanTg, olustu = _main_kur(monkeypatch, hl_300(), lambda k: AGENT)
    monkeypatch.setenv("HL_AG", "testnet")                                                          # testnet yalnız stop_deneme içindir
    assert mt.main(["--kip", "gercek", "--durum-dizin", str(tmp_path / "durum")]) == 3 and not olustu
    assert "HL_AG" in TabanTg.ornekler[0].gonderilen[0]
