"""Haftalık kadro (kullanıcı kararı 16.11; Fable önerisi + mantık denetimi): kadro pazardan pazara değişir; hafta içi yalnız güvenlik çıkışları; pazar değişiminde yedeğe inenin
pozisyonları trader'a bırakılır (en çok `canli_inen_saat`), kadroda hiç olmayan hemen kapanır; inenlere slot stopu. Üretim kuralları (`load_rules_asil`; conftest testlerde kapatır)."""
import copytrade.kurallar as _k
from copytrade.canli import kadro as kd

R = _k.load_rules_asil()
SAAT, GUN = 3_600_000, 86_400_000
T0 = 1_800_000_000_000                       # 2027-01-15 Cuma 08:00 UTC → hafta (pazar) 2027-01-10; sonraki pazar T0 + 2 gün
PAZAR = T0 + 2 * GUN


def adr(i: int) -> str:
    return "0x" + f"{i:040x}"


def satir(i, sira, form=50.0, kald=3.0):
    return {"adres": adr(i), "sira": sira, "katman": "ilk11" if sira <= 11 else "yedek", "form": form, "bilesenler": {}, "kopya_getiri_7g": 0.01, "max_kaldirac": kald}


def kadro(satirlar, kosu_ms, eski=None):
    return {"sema": "radar-kadro-v1", "kosu_ms": kosu_ms, "kasa_usd": 10000.0, "satirlar": satirlar, "soguyan": [], "eski_uye_neden": eski or {},
            "korelasyon": {"adresler": [], "gun_sayisi": 8, "matris": []}}


def kurulu():
    s = kd.Saha(R, 10000.0)
    assert s.n == 11 and s.haftalik
    s.degerlendir(kadro([satir(i, i) for i in range(1, 21)], T0), T0 + SAAT)
    assert set(s.uyeler) == {adr(i) for i in range(1, 12)} and s.hafta["hafta"] == "2027-01-10"
    return s


def test_kurallar_ve_hafta_anahtari():
    assert R["canli_haftalik_kadro"] is True and R["canli_inen_saat"] == 72 and R["canli_inen_tavan_oran"] == 0.15
    assert kd.Saha.hafta_anahtari(T0) == "2027-01-10" and kd.Saha.hafta_anahtari(PAZAR) == "2027-01-17" and kd.Saha.hafta_anahtari(PAZAR // GUN * GUN - 1) == "2027-01-10"


def test_hafta_ici_radar_elemesi_cikis_degil_uyari():
    s = kurulu()
    satirlar = [satir(i, i - 1) for i in range(2, 21)] + [satir(30, 20)]                 # adr(1) bugün R1'den elendi, adr(5) form sırası 25
    satirlar = [x if x["adres"] != adr(5) else satir(5, 25) for x in satirlar]
    karar, durum = s.degerlendir(kadro(satirlar, T0 + GUN, {adr(1): "r1:kopya_zarar"}), T0 + GUN + SAAT)
    assert durum == "ok" and not [k for k in karar if k.tur == "dus"] and len(s.uyeler) == 11
    assert {(k.adres, k.neden) for k in karar if k.tur == "uyari"} == {(adr(1), "radar_eledi:r1:kopya_zarar"), (adr(5), "form_sirasi:25")}


def test_hafta_ici_kaldirac_elemesi_guvenlik_cikisi_ve_bos_yer_bugunku_kadroda_olanla_dolar():
    s = kurulu()
    satirlar = [satir(i, i - 1) for i in range(2, 21) if i != 12]                          # adr(1) kaldıraçtan elendi; adr(12) (haftanın 1. yedeği) bugün radarda yok
    karar, _ = s.degerlendir(kadro(satirlar, T0 + GUN, {adr(1): "r1:kaldirac_yuksek", adr(12): "r1:kopya_zarar"}), T0 + GUN + SAAT)
    assert [(k.adres, k.neden, k.sonuc) for k in karar if k.tur == "dus"] == [(adr(1), "kaldirac_ihlali", True)]
    assert [k.adres for k in karar if k.tur == "giris"] == [adr(13)]                       # haftanın sırası, ama bugün elenen adr(12) atlanır
    assert len(s.uyeler) == 11 and adr(1) in s.bekleme


def test_hafta_ici_slot_stopu_calisir_bos_yer_haftanin_sirasiyla():
    s = kurulu()
    karar = s.anlik(T0 + 2 * SAAT, lambda a: 700.0 if a == adr(3) else 909.0)
    assert [(k.tur, k.adres) for k in karar] == [("dus", adr(3)), ("inen_kapat", adr(3))]
    karar, _ = s.degerlendir(kadro([satir(i, i) for i in range(1, 21)], T0), T0 + 3 * SAAT)
    assert [k.adres for k in karar if k.tur == "giris"] == [adr(12)] and len(s.uyeler) == 11


def test_pazar_degisimi_yedege_inen_izlenir_elenen_ve_kadro_disi_hemen_kapanir():
    s = kurulu()
    yeni = [satir(i, i) for i in range(1, 9)] + [satir(21, 9), satir(22, 10), satir(23, 11), satir(9, 12)]   # adr(9) yedeğe indi; adr(10) R1'den elendi; adr(11) kadroda yok
    karar, _ = s.degerlendir(kadro(yeni, PAZAR + SAAT, {adr(10): "r1:kopya_zarar", adr(11): "r0_disi"}), PAZAR + 2 * SAAT)
    dus = {(k.adres, k.neden, k.sonuc) for k in karar if k.tur == "dus"}
    assert dus == {(adr(9), "hafta_yedege", False), (adr(10), "hafta_elendi", True), (adr(11), "hafta_kadro_disi", False)}
    assert {k.adres for k in karar if k.tur == "inen_kapat"} == {adr(10), adr(11)}          # yedeğe inen kapatılmaz (trader'a bırakılır)
    assert set(s.inen) == {adr(9)} and adr(10) in s.bekleme and adr(11) not in s.bekleme
    assert [k.adres for k in karar if k.tur == "giris"] == [adr(21), adr(22), adr(23)] and len(s.uyeler) == 11
    assert [k.neden for k in karar if k.tur == "hafta_degisimi"] == ["2027-01-17"] and s.hafta["hafta"] == "2027-01-17"
    assert s.inenleri_kapat(PAZAR + 2 * SAAT + 71 * SAAT) == [] and [k.adres for k in s.inenleri_kapat(PAZAR + 2 * SAAT + 72 * SAAT)] == [adr(9)]


def test_hafta_yeniden_baslatmada_korunur_ayni_hafta_degisim_yok():
    s = kurulu()
    s2 = kd.Saha(R, 10000.0, s.to_json())
    karar, _ = s2.degerlendir(kadro([satir(i, i) for i in range(12, 32)], T0 + GUN), T0 + GUN + SAAT)       # ertesi gün tamamen farklı kadro: hafta içi değişim yok
    assert not [k for k in karar if k.tur in ("dus", "giris", "hafta_degisimi")] and set(s2.uyeler) == {adr(i) for i in range(1, 12)}


def test_inen_slot_stopu():
    s = kurulu()
    s.degerlendir(kadro([satir(i, i) for i in range(1, 11)] + [satir(21, 11), satir(11, 12)], PAZAR + SAAT), PAZAR + 2 * SAAT)
    assert set(s.inen) == {adr(11)}
    karar = s.anlik(PAZAR + 3 * SAAT, lambda a: 700.0 if a == adr(11) else 909.0)
    assert [(k.tur, k.adres, k.neden) for k in karar] == [("inen_kapat", adr(11), "inen_slot_dusus")] and not s.inen and adr(11) in s.bekleme


# ---------------------------------------------------------------------------------------------------------------- motor: inen ters yön / tavan (Fable açık 2, 7)
def _motor_iki_trader(tmp_path):
    from tests.test_canli_motor import adr as a_, kadro as k_, kur, olay, satir as s_
    k = k_([s_(1, 1), s_(2, 2)], 0)
    m, hl, saat, _ = kur(tmp_path, kadro_=k)
    k["kosu_ms"] = saat() - 3_600_000
    m.baslat()
    m.rules["canli_haftalik_kadro"] = True
    m.saha.rules["canli_haftalik_kadro"] = True
    m.olay_isle(olay("a:1", a_(1), "BTC", "B", 300, 100.0, 0.0, saat))                   # T1 BTC long
    assert m.hesap.sz(a_(1), "BTC") > 0
    m.saha.uyeler.pop(a_(1))
    m.saha.inen[a_(1)] = {"inis_ms": saat(), "neden": "hafta_yedege"}                   # T1 pazar değişiminde yedeğe indi: pozisyonu trader'a bırakıldı
    return m, saat, a_, olay


def test_inen_ters_yon_pozisyonu_kapanir_yeni_kadronun_acilisi_engellenmez(tmp_path):
    m, saat, a_, olay = _motor_iki_trader(tmp_path)
    s = m.olay_isle(olay("b:1", a_(2), "BTC", "A", 300, 100.0, 0.0, saat))              # sahadaki T2 BTC short açar
    assert [(x.eylem, x.karar) for x in s] == [("ac", "emir")]
    assert m.hesap.sz(a_(1), "BTC") == 0.0 and m.hesap.sz(a_(2), "BTC") < 0


def test_inen_toplam_tavani_asilinca_en_zarardaki_inen_kapanir(tmp_path):
    m, saat, a_, _ = _motor_iki_trader(tmp_path)
    m.rules["canli_inen_tavan_oran"] = 0.001                                              # kasa 1.000 × 0,001 = 1 $ < T1'in BTC nosyoneli
    m._inen_tavan(saat())
    assert not m.saha.inen and m.hesap.sz(a_(1), "BTC") == 0.0
