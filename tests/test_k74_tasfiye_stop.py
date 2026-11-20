"""K-74 (taslak): sanal tasfiye kaydı/mesajı + `dinamik_stop` bayrağı (elle hesaplanmış altın örnekler)."""
import pytest

from copytrade.canli import borsa_stop as bs
from copytrade.canli import hesap as hs
from copytrade.canli import pano
from copytrade.canli.hesap import Hesap, Poz, dinamik_stop_orani, tasfiye_mesafe
from tests.test_canli_motor import adr, kayitlar, kur, olay


def test_altin_ornek_dinamik_stop_oranlari():
    # giriş 100, kaldıraç 3
    assert hs.tasfiye_fiyati(False, 100.0, 3.0, 3.0) == pytest.approx(114.2857, abs=1e-4)
    assert dinamik_stop_orani(False, 100.0, 3.0, 3.0, 0.20, 0.03) == pytest.approx(0.112857, abs=1e-6)       # 111,2857
    assert 100 * (1 + dinamik_stop_orani(False, 100.0, 3.0, 3.0, 0.20, 0.03)) == pytest.approx(111.2857, abs=1e-4)
    assert hs.tasfiye_fiyati(False, 100.0, 3.0, 5.0) == pytest.approx(121.2121, abs=1e-4)
    assert dinamik_stop_orani(False, 100.0, 3.0, 5.0, 0.20, 0.03) == pytest.approx(0.182121, abs=1e-6)
    assert dinamik_stop_orani(False, 100.0, 3.0, 20.0, 0.20, 0.03) == 0.20                                 # azami 20: değişmez
    assert hs.tasfiye_fiyati(True, 100.0, 3.0, 3.0) == pytest.approx(80.0, abs=1e-9)
    assert tasfiye_mesafe(True, 100.0, 3.0, 3.0) == pytest.approx(0.20)
    assert dinamik_stop_orani(True, 100.0, 3.0, 3.0, 0.20, 0.03) == pytest.approx(0.17)
    assert dinamik_stop_orani(True, 100.0, 3.0, 3.0, 0.22, 0.01) == pytest.approx(0.19)                    # gerçek borsa stopu: min(0,22; 0,20−0,01)


def _kur_short(tmp_path, dinamik, azami=3.0, mark="112"):
    m, hl, saat, tgp = kur(tmp_path, kurallar={"canli_slot_dusus_oran": 0.9, "dinamik_stop": dinamik})
    m.baslat()
    m.hesap.maks_kaldirac["SOL"] = azami
    hl.pozlar[adr(1)] = {"SOL": -500.0}
    assert m.olay_isle(olay("a:1", adr(1), "SOL", "A", 500, 100.0, 0.0, saat))[0].karar == "emir"
    assert m.hesap.sz(adr(1), "SOL") < 0
    hl.mids["SOL"] = mark
    hl.kitaplar["SOL"] = {"levels": [[{"px": mark, "sz": "100000"}], [{"px": mark, "sz": "100000"}]]}
    return m, hl, saat, tgp


def test_dinamik_stop_acik_azami3_short_yuzde_11_3te_kapanir(tmp_path):
    m, hl, saat, tgp = _kur_short(tmp_path, True, mark="111")            # +%11: henüz değil
    p = m.hesap.poz[adr(1)]["SOL"]
    girisi = p.giris
    hl.mids["SOL"] = str(girisi * 1.11)
    m.dakika()
    assert m.hesap.sz(adr(1), "SOL") < 0
    hl.mids["SOL"] = str(girisi * 1.1129)                                  # > %11,2857
    m.dakika()
    assert m.hesap.sz(adr(1), "SOL") == 0.0
    assert any(x["olay"] == "felaket_stop" for x in kayitlar(tmp_path))
    em = [x for x in kayitlar(tmp_path, "emir") if x.get("reduce_only")]
    assert em and em[-1]["boyut_neden"] == "tasfiye_koruma_stop"                 # daraltılmış stop ayrı neden
    assert not any("Neden: tasfiye koruması stopu" in x for x in tgp.gonderilen)                       # K-79: ayrı "kapandı" mesajı yok (kayıtta tek tek metin var), saatlik özette "stopla kapanan" satırı
    assert any("Neden: tasfiye koruması stopu" in k["metin"] for k in kayitlar(tmp_path, "tg_mesaj") if k.get("tur") == "islem_satiri")
    saat.ms += 3_600_000
    m.emir_ozeti(saat())
    oz = [x for x in tgp.gonderilen if x.startswith("🧾 Son ")]
    assert len(oz) == 1 and "🛑 Stopla kapanan: SOL " in oz[0] and "(tasfiye koruması stopu)" in oz[0]


def test_yaml_dinamik_stop_kullanici_onayiyla_acik():
    import yaml
    from pathlib import Path
    assert yaml.safe_load(Path("copytrade/kurallar.yaml").read_text(encoding="utf-8"))["dinamik_stop"] is True


def test_dinamik_stop_kapali_ayni_pozisyon_yuzde_11_3te_kapanmaz(tmp_path):
    m, hl, saat, tgp = _kur_short(tmp_path, False)
    p = m.hesap.poz[adr(1)]["SOL"]
    hl.mids["SOL"] = str(p.giris * 1.1129)
    m.dakika()
    assert m.hesap.sz(adr(1), "SOL") < 0                                    # bugünkü davranış: %20'ye dek açık
    assert not any(x["olay"] == "felaket_stop" for x in kayitlar(tmp_path))


def test_borsa_stop_hedefleri_bayrak_kapali_ayni_acik_dinamik(tmp_path):
    poz = {"a": {"X": Poz(-10.0, 100.0, 0, 3.0)}}
    marks = {"X": 100.0}
    assert bs.hedefler(poz, marks, 0.22, 10.0)["X"]["tetik"] == pytest.approx(122.0)                       # eski
    fn = lambda c, uzun, g: dinamik_stop_orani(uzun, g, 3.0, 3.0, 0.22, 0.01)                              # noqa: E731
    assert bs.hedefler(poz, marks, 0.22, 10.0, fn)["X"]["tetik"] == pytest.approx(100 * (1 + 0.142857142857 - 0.01), abs=1e-6)
    poz5 = {"a": {"X": Poz(-10.0, 100.0, 0, 3.0)}}
    fn5 = lambda c, uzun, g: dinamik_stop_orani(uzun, g, 3.0, 5.0, 0.22, 0.01)                             # noqa: E731
    assert bs.hedefler(poz5, marks, 0.22, 10.0, fn5)["X"]["tetik"] == pytest.approx(100 * (1 + 0.212121212 - 0.01), abs=1e-6)


def test_artirma_ortalama_giris_degisince_stop_yeniden_hesaplanir():
    h = Hesap(1000.0, 3.0, {"X": 3.0})
    h.slot_ac("a", 100.0)
    h.uygula("a", "X", "A", 1.0, 100.0, 0.0, 1)
    p = h.poz["a"]["X"]
    s1 = 100 * (1 + dinamik_stop_orani(False, p.giris, 3.0, 3.0, 0.20, 0.03))
    h.uygula("a", "X", "A", 1.0, 110.0, 0.0, 2)
    assert p.giris == pytest.approx(105.0)
    s2 = p.giris * (1 + dinamik_stop_orani(False, p.giris, 3.0, 3.0, 0.20, 0.03))
    assert s2 == pytest.approx(s1 * 1.05)


def test_tasfiye_emir_kaydi_telegram_kapandi_ve_alarm(tmp_path):
    m, hl, saat, tgp = _kur_short(tmp_path, False)
    p = m.hesap.poz[adr(1)]["SOL"]
    giris, sz = p.giris, abs(p.sz)
    liq = hs.tasfiye_fiyati(False, giris, p.kaldirac, 3.0)
    hl.mids["SOL"] = str(liq * 1.01)
    m.dakika()
    assert m.hesap.sz(adr(1), "SOL") == 0.0
    emirler = [x for x in kayitlar(tmp_path) if x["olay"] == "emir" and x.get("boyut_neden") == "tasfiye"]
    assert len(emirler) == 1
    e = emirler[0]
    assert e["eylem"] == "kapat" and e["reduce_only"] and e["durum"] == "dolu" and e["yon"] == "B" and e["adres"] == adr(1) and e["coin"] == "SOL"
    assert e["dolum_px"] == pytest.approx(liq) and e["sz"] == pytest.approx(sz) and e["pnl_usd"] == pytest.approx(sz * (giris - liq), abs=1e-5)
    assert not any("kapandı" in x and "Neden: tasfiye" in x for x in tgp.gonderilen)                    # K-79: ayrı "kapandı" yok; saatlik özette satır
    assert any("kapandı" in k["metin"] and "Neden: tasfiye" in k["metin"] for k in kayitlar(tmp_path, "tg_mesaj") if k.get("tur") == "islem_satiri")
    assert any(x.startswith("💥 Tasfiye (sanal)") and "Senden bir şey gerekmiyor." in x for x in tgp.gonderilen)       # tasfiye ALARMI anında gider
    saat.ms += 3_600_000
    m.emir_ozeti(saat())
    assert any(x.startswith("🧾 Son ") and "🛑 Stopla kapanan: SOL " in x and "(tasfiye)" in x for x in tgp.gonderilen)
    # pano: KAPANAN nedeni Tasfiye
    satirlar = pano.kapanan_islemler([{"olay": "emir", **{k: v for k, v in e.items() if k != "olay"}}], 0.2)
    assert satirlar and satirlar[0]["neden"] == "Tasfiye" and satirlar[0]["net"] == pytest.approx(e["pnl_usd"])


def test_pano_toplam_nasil_olusuyor_tasfiye_bir_kez():
    """realize zaten tasfiye K/Z'sini içerir; 'Kapanışlar' = realize − tasfiye, 'Zorla kapanma' = tasfiye → toplamları realize'i aşmaz."""
    h = Hesap(1000.0, 3.0, {"X": 3.0})
    h.slot_ac("a", 100.0)
    h.uygula("a", "X", "A", 1.0, 100.0, 0.0, 1)
    h.uygula("a", "X", "B", 1.0, 99.0, 0.0, 2)                              # +1 normal kapanış
    h.uygula("a", "X", "A", 1.0, 100.0, 0.0, 3)
    ev = h.tasfiye_kontrol({"X": 120.0}, 4)
    assert len(ev) == 1 and ev[0]["pnl"] == pytest.approx(-(100 / 3 * 0 + 14.2857), abs=1e-3)
    gerc = sum(h.realize.values())
    tasf = sum(x["pnl"] for x in h.tasfiyeler)
    assert gerc == pytest.approx(1.0 + ev[0]["pnl"]) and (gerc - tasf) + tasf == pytest.approx(gerc)


def _em(ms, reduce, sz, eylem, pnl=None, neden="", yon="B", px=100.0):
    return {"olay": "emir", "zaman_ms": ms, "adres": "a", "coin": "X", "durum": "dolu", "reduce_only": reduce, "sz": sz, "eylem": eylem, "yon": yon,
            "pnl_usd": pnl, "boyut_neden": neden, "dolum_px": px, "trader_px": px, "ucret": 0.0}


def test_kapanan_pozisyon_azaltmalarla_sifira_inince_ve_tasfiyede_kapanmis_sayilir():
    kayit = [_em(1, False, 10.0, "ac"), _em(2, True, 4.0, "azalt", 2.0, "tamam", "A"), _em(3, True, 6.0, "azalt", 3.0, "tamam", "A"),      # azalt + azalt → 0 = 1 pozisyon, +5
             _em(4, False, 10.0, "ac", yon="A"), _em(5, True, 10.0, "kapat", -8.0, "tasfiye", "B", 114.0)]                              # tasfiye = 1 pozisyon, −8
    satirlar = pano.kapanan_islemler(kayit)
    assert [r["kapat"] for r in sorted(satirlar, key=lambda r: r["ms"])] == [False, True, True]
    oz = pano.kapanan_ozeti(satirlar)
    assert oz["poz"] == 2 and oz["kapanis"] == 3 and oz["kazanma"] == pytest.approx(0.5)                                              # +5 kazanç, −8 kayıp
    assert oz["ort_kazanc"] == pytest.approx(5.0) and oz["ort_kayip"] == pytest.approx(-8.0)


def test_kapanan_kismi_azaltma_pozisyonu_bitirmez():
    satirlar = pano.kapanan_islemler([_em(1, False, 10.0, "ac"), _em(2, True, 4.0, "azalt", 2.0, "tamam", "A")])
    assert pano.kapanan_ozeti(satirlar)["poz"] == 0


def test_tg_mesaj_kaydi_tam_metin_yapisal_alan_ve_gizli_deger_yok(tmp_path):
    m, hl, saat, tgp = _kur_short(tmp_path, False)
    p = m.hesap.poz[adr(1)]["SOL"]
    hl.mids["SOL"] = str(hs.tasfiye_fiyati(False, p.giris, p.kaldirac, 3.0) * 1.01)
    m.dakika()
    kl = [x for x in kayitlar(tmp_path) if x["olay"] == "tg_mesaj"]
    kapandi = [x for x in kl if "kapandı" in x["metin"] and x.get("neden") == "tasfiye"]
    assert len(kapandi) == 1 and kapandi[0]["adres"] == adr(1) and kapandi[0]["coin"] == "SOL" and kapandi[0]["yon"] == "B" and kapandi[0]["pnl"] < 0
    assert kapandi[0]["tur"] == "islem_satiri" and kapandi[0]["bastirildi"] is True and kapandi[0]["gonderildi"] is False and "sessiz" in kapandi[0] and "seviye" in kapandi[0]     # K-79: tek tek kayıt sürer, ayrı mesaj gitmez
    assert any(x["metin"].startswith("💥 Tasfiye (sanal)") and "Senden bir şey gerekmiyor." in x["metin"] for x in kl)
    ham = "\n".join(str(x) for x in kl)
    from tests.test_canli_motor import TOKEN, CHAT
    assert str(TOKEN) not in ham and str(CHAT) not in ham
