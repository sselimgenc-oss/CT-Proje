"""K-79 (kullanıcı kararı 20.11): işlem mesajları saatlik TEK özet; uyarılar anında. Bir saatte 5 açılış + 3 kapanış → tek mesaj; uyarı anında; boş saat mesajsız; özet net K/Z'si pano tanımıyla aynı;
gerçek kipte de aynı (tasfiye/stop/risk uyarıları anında kalır); tg_mesaj kayıtları sürer."""
from __future__ import annotations

import pytest

from copytrade.canli import pano, telegram as tg
from tests.test_canli_motor import RULES, SAAT, SahteHL, adr, kadro, kayitlar, kur, olay, satir

COINLER = ("BTC", "ETH", "SOL", "BTC", "ETH")


def _sekiz_islem(tmp_path, **kw):
    """5 trader × 1 açılış (5 açılış) + ilk 3'ü tam kapanış (3 kapanış), hepsi aynı saat içinde."""
    k = kadro([satir(i, i) for i in range(1, 6)], 1_800_000_000_000 - SAAT)
    m, hl, saat, tgp = kur(tmp_path, kadro_=k, kasa=10_000.0, **kw)
    m.baslat()
    px = {"BTC": 100.0, "ETH": 2000.0, "SOL": 100.0}
    for i, c in enumerate(COINLER, start=1):
        m.olay_isle(olay(f"a:{i}", adr(i), c, "B", 300, px[c], 0.0, saat))
    m.piyasa_oku(saat())
    for i in (1, 2, 3):
        m.olay_isle(olay(f"k:{i}", adr(i), COINLER[i - 1], "A", 300, px[COINLER[i - 1]], 300.0, saat))
    return m, hl, saat, tgp


def _ozetler(tgp):
    return [x for x in tgp.gonderilen if x.startswith("🧾 Son ")]


def test_bir_saatte_5_acilis_3_kapanis_tek_mesaj(tmp_path):
    m, hl, saat, tgp = _sekiz_islem(tmp_path)
    assert m._say_gun["ac"] == 5 and m._say_gun["kapat"] == 3
    assert [x for x in tgp.gonderilen if " açıldı · trader " in x or " kapandı · trader " in x] == [] and _ozetler(tgp) == []          # saat dolmadan HİÇ işlem mesajı yok
    assert len([k for k in kayitlar(tmp_path, "tg_mesaj") if k.get("tur") == "islem_satiri"]) == 8                                       # tek tek kayıt sürer (tg_mesaj)
    saat.ms += SAAT
    m.emir_ozeti(saat())
    oz = _ozetler(tgp)
    assert len(oz) == 1 and oz[0].startswith("🧾 Son 1 saat: 8 emir (5 açılış, 3 kapanış)")
    satirlar = oz[0].splitlines()
    assert len(satirlar) <= 5 and any(x.startswith("🟢 Açılan: ") for x in satirlar) and any("Kapanan: " in x for x in satirlar)
    m.emir_ozeti(saat() + SAAT)
    assert len(_ozetler(tgp)) == 1                                                                   # tampon boşaldı: aynı saat için ikinci mesaj yok


def test_ozet_net_kz_pano_tanimiyla_ayni(tmp_path):
    """Özet net K/Z = penceredeki tam kapanan pozisyonların net toplamı = pano KAPANAN `net` (gerçekleşen − her dolumun ücreti, giriş/artırma ücreti dahil; `hesap.dolum_net`)."""
    m, hl, saat, tgp = _sekiz_islem(tmp_path)
    kayit = kayitlar(tmp_path)
    for e in kayit:
        e.setdefault("zaman_ms", e.get("emir_ms") or 0)
    pano_net = pano.kapanan_ozeti(pano.kapanan_islemler(kayit))["net"]
    ozet_net = tg.net_kz(m._emir_tampon)
    assert ozet_net == pytest.approx(pano_net, abs=1e-5) and ozet_net != 0.0                      # kayıt pnl_usd'yi 6 hanede yuvarlar
    assert ozet_net == pytest.approx(sum(net for ls in m.hesap.kapanan.values() for _, net in ls), abs=1e-9)                              # defter (K-77 poz_net) ile de aynı
    saat.ms += SAAT
    m.emir_ozeti(saat())
    assert f"net {tg.tr_isaretli(ozet_net)} $" in _ozetler(tgp)[0]


def test_stopla_kapanan_ayri_vurgulu_satir(tmp_path):
    emirler = [{"adres": "0xf43a34aaaaaaaa", "coin": c, "yon": "A", "usd": 20.0, "durum": "dolu", "eylem": "kapat", "kapandi": True, "kz": kz, "neden_kod": n}
               for c, kz, n in (("BTC", 1.5, "tam_kapanis"), ("ETH", -4.2, "felaket_stop"), ("SOL", -1.1, "iz_suren_koruma"), ("ADA", -9.0, "tasfiye"))]
    m = tg.msg_sanal_saatlik(0, SAAT, 60, emirler, {})
    s = m.splitlines()
    assert any(x.startswith("✅ Kapanan: BTC +1,50 $") for x in s)
    assert any(x.startswith("🛑 Stopla kapanan: ETH −4,20 $ (stop) · SOL −1,10 $ (iz süren koruma) · ADA −9,00 $ (tasfiye)") for x in s)
    assert f"net {tg.tr_isaretli(1.5 - 4.2 - 1.1 - 9.0)} $" in s[0]


def test_uyari_aninda_gider_ozeti_beklemez(tmp_path):
    m, hl, saat, tgp = _sekiz_islem(tmp_path)
    once = len(tgp.gonderilen)
    m.tg.gonder(tg.alarm("ALARM: kasa sınırı aşıldı", "Kasa 1.200 $ > sınır 1.000 $.\nYeni pozisyon açılmıyor."))
    m.tg.gonder(tg.msg_limit_yaklasti(0.04, 0.05, 9_600.0), "WARN")
    assert len(tgp.gonderilen) == once + 2 and tgp.gonderilen[once].startswith("🚨") and _ozetler(tgp) == []                          # özet saat dolmadı; uyarılar hemen
    assert m.tg.bastirilan.isdisjoint({"islem_ozeti"}) and "ALARM" not in " ".join(tg.BASTIRILAN_TURLER)


def test_tasfiye_alarmi_aninda_kapanis_satiri_ozette(tmp_path):
    from tests.test_k74_tasfiye_stop import _kur_short, hs
    m, hl, saat, tgp = _kur_short(tmp_path, False)
    p = m.hesap.poz[adr(1)]["SOL"]
    hl.mids["SOL"] = str(hs.tasfiye_fiyati(False, p.giris, p.kaldirac, 3.0) * 1.01)
    m.dakika()
    assert any(x.startswith("💥 Tasfiye (sanal)") for x in tgp.gonderilen) and _ozetler(tgp) == []                                    # alarm anında; "kapandı" satırı özette
    saat.ms += SAAT
    m.emir_ozeti(saat())
    assert any("🛑 Stopla kapanan: SOL " in x and "(tasfiye)" in x for x in _ozetler(tgp))


def test_bos_saat_mesajsiz(tmp_path):
    m, hl, saat, tgp = kur(tmp_path)
    m.baslat()
    for _ in range(3):
        saat.ms += SAAT
        m.emir_ozeti(saat())
    m.emir_ozeti(saat(), zorla=True)
    assert _ozetler(tgp) == [] and not [x for x in tgp.gonderilen if x.startswith("🧾")]                                              # işlem yok → "sistem çalışıyor" dahil HİÇ mesaj
    assert tg.msg_sanal_saatlik(0, SAAT, 60, [], {"x": 1}) == ""


def test_gercek_kipte_de_saatlik_tek_ozet_sorunlu_emir_aninda(tmp_path):
    from copytrade.canli import yurutucu as yu
    from copytrade.canli import motor as mt
    from tests.test_canli_motor import CHAT, TOKEN, SahteTG, Saat, T0

    class Gercek:
        kip = "gercek"

        def __init__(self):
            self.n = 0

        def hazirla(self, coin):
            return None

        def emir(self, coin, yon, usd, reduce_only=False, acik_sz=None, bant=None, cloid=None):
            self.n += 1
            if self.n == 3:
                return yu.Dolum(coin, yon, usd, reduce_only=reduce_only, durum="red", neden="hl_err: x")
            return yu.Dolum(coin, yon, usd, usd_dolan=usd, sz=usd / 100, px=100.0, reduce_only=reduce_only, durum="dolu")
    tgp, saat = SahteTG(), Saat()
    t = tg.Telegram(TOKEN, CHAT, tgp)
    m = mt.Motor(RULES, Gercek(), SahteHL(), t, tmp_path / "durum", tmp_path / "kayit", lambda: kadro([satir(i, i) for i in range(1, 4)], T0), saat)
    assert float(RULES["canli_telegram_gercek_ozet_dk"]) == 60
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    m.olay_isle(olay("a:2", adr(2), "BTC", "B", 300, 100.0, 0.0, saat))
    m.olay_isle(olay("a:3", adr(3), "BTC", "B", 300, 100.0, 0.0, saat))                       # reddedilen: gerçek parada hemen 🚨
    assert [x for x in tgp.gonderilen if x.startswith("🚨 [GERÇEK] EMİR REDDEDİLDİ")] and not [x for x in tgp.gonderilen if " açıldı · trader " in x]
    assert _ozetler(tgp) == []
    saat.ms += SAAT
    m.emir_ozeti(saat())
    oz = _ozetler(tgp)
    assert len(oz) == 1 and "GERÇEK PARA" in oz[0] and "2 açılış" in oz[0]
