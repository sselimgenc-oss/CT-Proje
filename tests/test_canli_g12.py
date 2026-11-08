"""G-1 + G-12 (DENETIM_PROJE_2026-11-08): emir zaman aşımı "belirsiz" → `orderStatus(cloid)` ile çözüm (deftere TEK kez), dakikalık görevin sessiz ölmemesi, bekçi.
Ağsız; gerçek kip YALNIZ sahte borsa (`BorsaSim`) ile sınanır, ÇALIŞTIRILMAZ. Sayılar elle hesaplanmıştır:
- Kasa 1.000 $, trader hesabı 100.000 $, trader 300 BTC × 100 $ açar (oran 0,30) → emir 27,27 $ → ask 100 → sz = 27,27 / 100 = 0,27273 BTC (5 hane).
- IOC limit = 100 × 1,005 = 100,5 $. `orderStatus` ortalama fiyat vermez: defter limitPx ile YAKLAŞIK (100,5; kesin değer mutabakatta).
- Ücret (HL `fee` bulunamadı → tahmin): 0,27273 × 100,5 × 0,00045 = 0,01233421 $.
"""
import asyncio
import errno
import threading
import time
import types

import pytest
import requests

from copytrade.canli import motor as mt
from copytrade.canli import yurutucu as yu
from tests.test_canli_motor import RULES, Saat, kayitlar, kur, olay, adr
from tests.test_canli_t4b import BorsaSim, Cokus, kur_gercek

SZ = 0.27273
LIMIT = 100.5
UCRET = 0.27273 * 100.5 * 0.00045                    # 0,01233421 $


@pytest.fixture(autouse=True)
def _maske_temizle():
    yield
    mt.MASKE.clear()


class ZamanAsimiBorsa(BorsaSim):
    """`order` isteği gider, yanıt gelmez (SDK `requests.ReadTimeout`). `ulasti=True`: HL emri aldı ve doldurdu (pozisyon açılır, `orderStatus(cloid)` → filled); False: HL hiç görmedi (unknownOid).
    `asili`: yalnız ilk N emir zaman aşımına düşer, sonrakiler normal."""

    def __init__(self, ulasti=True, asili=1, **k):
        super().__init__(**k)
        self.ulasti, self.asili = ulasti, asili

    def order(self, coin, is_buy, sz, px, tif, reduce_only, cloid=None):
        if self.asili <= 0:
            return super().order(coin, is_buy, sz, px, tif, reduce_only, cloid=cloid)
        self.asili -= 1
        if self.ulasti:
            super().order(coin, is_buy, sz, px, tif, reduce_only, cloid=cloid)
            dolan = self.siparisler[-1]["dolan"]
            self.durumlar[str(cloid)] = {"status": "order", "order": {"order": {"coin": coin, "side": "B" if is_buy else "A", "limitPx": str(px), "sz": "0.0", "origSz": str(dolan), "oid": 9},
                                                                        "status": "filled"}}
        raise requests.exceptions.ReadTimeout("HTTPSConnectionPool: Read timed out. (read timeout=10)")

    def orderstatus_say(self):
        return sum(1 for y in self.istekler if y["type"] == "orderStatus")


# ================================================================================================ G-1: belirsiz → orderStatus
def test_g1_asili_emir_zaman_asimi_belirsiz_orderstatus_filled_deftere_tek_kez(tmp_path, monkeypatch):
    """Emir HL'de doldu ama yanıt zaman aşımına düştü → `belirsiz` (red DEĞİL): defter 0, niyet açık, yeni açılış durur. Zaman aşımı süresi (10 sn) dolmadan sorgu yok.
    Sonraki dakika `orderStatus` filled → defter 0,27273 BTC @ 100,5, ücret 0,01233 $; bayrak kalkar. Tekrar dakika ve yeniden başlatma: ikinci uygulama/sorgu/emir YOK."""
    sim = ZamanAsimiBorsa(ulasti=True)
    m, sim, saat, tgp = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    s = m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    assert s[0].karar == "belirsiz" and s[0].neden == "sdk_hatasi: ReadTimeout"
    assert sim.poz["BTC"] == pytest.approx(SZ) and m.hesap.sz(adr(1), "BTC") == 0.0                        # borsada açık, defterde henüz yok
    assert len(m.hesap.belirsiz) == 1 and len(m.niyet.sonucsuz()) == 1 and m.risk.acilis_durdu["belirsiz"] is True
    assert m.sayac["red"] == 0 and m.sayac["belirsiz"] == 1 and any("emir sonucu belirsiz" in x for x in tgp.gonderilen)
    m.dakika()                                                                                              # aynı an: zaman aşımı (10 sn) dolmadı → sorgu yok
    assert sim.orderstatus_say() == 0 and m.hesap.sz(adr(1), "BTC") == 0.0
    saat.ms += 60_000
    m.dakika()
    p = m.hesap.poz[adr(1)]["BTC"]
    assert sim.orderstatus_say() == 1 and p.sz == pytest.approx(SZ) and p.giris == pytest.approx(LIMIT)
    assert m.hesap.ucret[adr(1)] == pytest.approx(UCRET, abs=1e-9) and m.hesap.belirsiz == {} and m.risk.acilis_durdu["belirsiz"] is False
    assert m.niyet.sonucsuz() == [] and m.risk.acilis_durdu.get("mutabakat") is False                     # borsa 0,27273 = defter 0,27273
    c = kayitlar(tmp_path, "belirsiz_cozuldu")
    assert len(c) == 1 and c[0]["durum"] == "filled" and c[0]["uygulanan_sz"] == pytest.approx(SZ) and c[0]["ucret"] == pytest.approx(UCRET, abs=1e-9)
    saat.ms += 60_000
    m.dakika()
    assert sim.orderstatus_say() == 1 and m.hesap.sz(adr(1), "BTC") == pytest.approx(SZ)                  # ikinci kez uygulanmadı
    m2, _, _, _ = kur_gercek(tmp_path, monkeypatch, sim, saat=saat)                                        # yeniden başlatma
    m2.baslat()
    assert m2.hesap.sz(adr(1), "BTC") == pytest.approx(SZ) and sim.orderstatus_say() == 1 and len(sim.siparisler) == 1
    assert m2.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat)) == []                      # aynı dolum: ikinci emir yok


def test_g1_orderstatus_emir_yok_dolmadi_pozisyon_yok(tmp_path, monkeypatch):
    """İstek HL'ye hiç ulaşmadı (`unknownOid`): dolmadı sayılır → defter 0, borsa 0, niyet kapanır, bayrak kalkar; red sayacı değil `belirsiz` sayacı."""
    sim = ZamanAsimiBorsa(ulasti=False)
    m, sim, saat, _ = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    saat.ms += 60_000
    m.dakika()
    assert sim.orderstatus_say() == 1 and m.hesap.sz(adr(1), "BTC") == 0.0 and not sim.poz.get("BTC") and "BTC" not in m.hesap.poz.get(adr(1), {})
    assert m.hesap.belirsiz == {} and m.niyet.sonucsuz() == [] and m.risk.acilis_durdu["belirsiz"] is False
    assert kayitlar(tmp_path, "belirsiz_cozuldu")[0]["durum"] == "emir_yok" and kayitlar(tmp_path, "belirsiz_cozuldu")[0]["uygulanan_sz"] == 0.0


def test_g1_orderstatus_hatasi_girdi_kalir_sonraki_dakika_cozulur(tmp_path, monkeypatch):
    """`orderStatus` ağ hatası: girdi kalır (deneme 1), açılış durur; sonraki dakika sorgu başarılı → deftere bir kez."""
    sim = ZamanAsimiBorsa(ulasti=True)
    m, sim, saat, _ = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    asil = sim.post

    def bozuk(y):
        if y["type"] == "orderStatus":
            raise requests.exceptions.ConnectionError("ağ yok")
        return asil(y)
    m.post = bozuk
    saat.ms += 60_000
    m.dakika()
    assert m.hesap.sz(adr(1), "BTC") == 0.0 and list(m.hesap.belirsiz.values())[0]["deneme"] == 1 and m.risk.acilis_durdu["belirsiz"] is True
    assert kayitlar(tmp_path, "belirsiz_sorgu_hata")[0]["tur"] == "ConnectionError"
    m.post = asil
    saat.ms += 60_000
    m.dakika()
    assert m.hesap.sz(adr(1), "BTC") == pytest.approx(SZ) and m.hesap.belirsiz == {} and m.risk.acilis_durdu["belirsiz"] is False


def test_g1_sonuc_yazildi_defter_kaydedilmeden_cokme_yeniden_baslatmada_tek_kez(tmp_path, monkeypatch):
    """Çözüm sonuç satırını yazdı (fsync), defter (`hesap.json`) kaydedilmeden süreç öldü. Yeniden başlatma: `hesap.json` hâlâ belirsiz girdisini taşır; yazılmış sonuç kullanılır
    (ikinci `orderStatus` yok), defter 0,27273 — çift uygulama ve kayıp yok."""
    sim = ZamanAsimiBorsa(ulasti=True)
    m, sim, saat, _ = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    saat.ms += 60_000

    def coktur():
        raise Cokus()
    m._dolum_yaz = coktur
    with pytest.raises(Cokus):
        m.belirsiz_coz(saat())
    assert sim.orderstatus_say() == 1 and [x["t"] for x in m.niyet.satirlar()][-1] == "sonuc"
    m2, _, _, _ = kur_gercek(tmp_path, monkeypatch, sim, saat=saat)
    assert len(m2.hesap.belirsiz) == 1 and m2.hesap.sz(adr(1), "BTC") == 0.0                              # diskteki defter: çözüm öncesi
    m2.baslat()
    assert m2.hesap.sz(adr(1), "BTC") == pytest.approx(SZ) and m2.hesap.belirsiz == {} and sim.orderstatus_say() == 1
    m3, _, _, _ = kur_gercek(tmp_path, monkeypatch, sim, saat=saat)
    m3.baslat()
    assert m3.hesap.sz(adr(1), "BTC") == pytest.approx(SZ)                                                 # üçüncü süreç: yine tek kez


def test_g1_belirsiz_kapanis_borsa_teyidi_yereli_temizlediyse_ters_pozisyon_acilmaz(tmp_path, monkeypatch):
    """Açık 0,27273 BTC; trader kapatır, reduce-only kapanış emri HL'de dolar ama yanıt zaman aşımı → belirsiz. Kapanış teyidi borsada 0 görür, yereli mark'ta temizler.
    Sonraki dakika `orderStatus` filled 0,27273: reduce-only dolum defterdeki pozisyondan (0) fazla uygulanmaz → defter 0 (−0,27273 short DEĞİL)."""
    sim = ZamanAsimiBorsa(ulasti=True, asili=0)
    m, sim, saat, _ = kur_gercek(tmp_path, monkeypatch, sim)
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    assert m.hesap.sz(adr(1), "BTC") == pytest.approx(SZ)
    sim.asili = 1
    s = m.olay_isle(olay("a:2", adr(1), "BTC", "A", 300, 100.0, 300.0, saat))
    assert s[0].karar == "belirsiz" and sim.poz["BTC"] == 0.0 and m.hesap.sz(adr(1), "BTC") == 0.0 and len(m.hesap.belirsiz) == 1
    assert len(sim.siparisler) == 2                                                                        # borsa 0 görüldü: ikinci kapanış emri yok
    saat.ms += 60_000
    m.dakika()
    assert m.hesap.sz(adr(1), "BTC") == 0.0 and m.hesap.belirsiz == {} and kayitlar(tmp_path, "belirsiz_cozuldu")[0]["uygulanan_sz"] == 0.0
    assert not m.kapanis_kuyrugu and len(sim.siparisler) == 2


def test_g1_sanal_kipte_belirsiz_yok_orderstatus_sorulmaz(tmp_path):
    """Sanal kip davranışı değişmez: yürütücü "belirsiz" döndürse bile sonuç satırı hemen yazılır, `hesap.belirsiz` boş, `orderStatus` hiç sorulmaz."""
    m, hl, saat, _ = kur(tmp_path)

    class Sanal:
        kip = "sanal"

        def hazirla(self, coin):
            return None

        def emir(self, coin, yon, usd, reduce_only=False, acik_sz=None, bant=None, cloid=None):
            return yu.Dolum(coin, yon, usd, reduce_only=reduce_only, durum="belirsiz", neden="sdk_hatasi: X")
    m.yurutucu = Sanal()
    m.baslat()
    m.olay_isle(olay("a:1", adr(1), "BTC", "B", 300, 100.0, 0.0, saat))
    saat.ms += 60_000
    m.dakika()
    assert m.hesap.belirsiz == {} and m.niyet.sonucsuz() == [] and not any(y["type"] == "orderStatus" for y in hl.istekler)
    assert "belirsiz" not in m.risk.acilis_durdu and m.hesap.sz(adr(1), "BTC") == 0.0


# ================================================================================================ G-12b: dakikalık görev ölmez
def test_g12b_dakika_durum_yaz_hatasi_adim_korumasinda_alarm(tmp_path):
    """`durum_yaz` disk dolu (ENOSPC) → `dakika` istisna FIRLATMAZ; `adim_hata` (adim durum_yaz) + Telegram alarmı (saatte bir)."""
    m, hl, saat, tgp = kur(tmp_path)
    m.baslat()

    def dolu():
        raise OSError(errno.ENOSPC, "No space left on device")
    m.durum_yaz = dolu
    m.dakika()
    m.dakika()
    h = [x for x in kayitlar(tmp_path, "adim_hata") if x["adim"] == "durum_yaz"]
    assert len(h) == 2 and h[0]["tur"] == "OSError" and sum("durum diske yazılamıyor" in x for x in tgp.gonderilen) == 1


class StubMotor:
    """`/tmp/.../periyodik.py` yeniden üretimi: 2. `dakika` çağrısı OSError (ENOSPC) fırlatır."""

    def __init__(self, tmp_path, hata_sira=(2,)):
        self.n, self.hata_sira = 0, set(hata_sira)
        self.dur_istendi = False
        self.durum_dizin = tmp_path
        self.saha = types.SimpleNamespace(uyeler=[])
        self.kayitlar, self.cikis_kodu = [], 0
        self.tg = types.SimpleNamespace(gonderilen=[], gonder=lambda metin: self.tg.gonderilen.append(metin))

    def kayit(self, o):
        self.kayitlar.append(o)

    def ozet(self):
        return {}

    def pano_ek(self):
        return {}

    def saat_ms(self):
        return 0

    def dakika(self):
        self.n += 1
        if self.n in self.hata_sira:
            raise OSError(errno.ENOSPC, "No space left on device")


def test_g12b_periyodik_tek_istisnada_olmez_kayit_alarm_nabiz_yalniz_basarida():
    """Eskiden: 2. çağrıdaki istisna görevi öldürüyordu (1 sn'de 2 çağrı). Şimdi: görev sürer (≥ 5 çağrı), `adim_hata` (adim dakika) + alarm; bekçi nabzı yalnız başarılı çağrıda."""
    import tempfile
    from pathlib import Path
    m = StubMotor(Path(tempfile.mkdtemp()))
    nabizlar = []
    bekci = types.SimpleNamespace(nabiz=lambda: nabizlar.append(m.n))
    din = types.SimpleNamespace(izle_ekle=lambda a: None, durdur=lambda: None, ozet=lambda: {"genel": {}})

    async def kos():
        durdur = asyncio.Event()
        t = asyncio.create_task(mt._periyodik(m, durdur, din, aralik_sn=0.01, bekci=bekci))
        while m.n < 5:
            await asyncio.sleep(0.01)
        assert not t.done()
        durdur.set()
        await t
    asyncio.run(kos())
    h = [x for x in m.kayitlar if x.get("olay") == "adim_hata"]
    assert h[0] == {"olay": "adim_hata", "adim": "dakika", "tur": "OSError", "mesaj": "[Errno 28] No space left on device", "ardisik": 1} and len(h) == 1
    assert 2 not in nabizlar and {1, 3, 4} <= set(nabizlar) and sum("dakikalık bakım hata verdi" in x for x in m.tg.gonderilen) == 1


def test_g12b_gorev_beklenmedik_biterse_motor_durur_cikis_kodu_1():
    """Periyodik görev yakalanmamış istisnayla biterse (ör. dinleyici `izle_ekle` hatası): `_gorev_bitti` kayıt + alarm + dinleyici durdurulur + `durdur` set + `cikis_kodu` 1.
    Olağan bitişte (DUR: `durdur` set, istisna yok) çıkış kodu 0 kalır."""
    import tempfile
    from pathlib import Path
    m = StubMotor(Path(tempfile.mkdtemp()), hata_sira=())
    m.saha.uyeler = [adr(1)]
    durdurulan = []

    def izle_ekle(a):
        raise RuntimeError("abone olunamadı")
    din = types.SimpleNamespace(izle_ekle=izle_ekle, durdur=lambda: durdurulan.append(1), ozet=lambda: {"genel": {}})

    async def kos():
        durdur = asyncio.Event()
        t = asyncio.create_task(mt._periyodik(m, durdur, din, aralik_sn=0.01))
        t.add_done_callback(lambda g: mt._gorev_bitti(m, durdur, din, "periyodik", g))
        await asyncio.wait_for(durdur.wait(), timeout=2)
        return t
    t = asyncio.run(kos())
    assert isinstance(t.exception(), RuntimeError) and m.cikis_kodu == 1 and durdurulan == [1]
    assert [x for x in m.kayitlar if x.get("olay") == "gorev_bitti"][0]["tur"] == "RuntimeError" and any("motor görevi durdu" in x for x in m.tg.gonderilen)
    m2 = StubMotor(Path(tempfile.mkdtemp()), hata_sira=())
    m2.dur_istendi = True
    din2 = types.SimpleNamespace(izle_ekle=lambda a: None, durdur=lambda: None, ozet=lambda: {"genel": {}})

    async def kos2():
        durdur = asyncio.Event()
        t = asyncio.create_task(mt._periyodik(m2, durdur, din2, aralik_sn=0.01))
        t.add_done_callback(lambda g: mt._gorev_bitti(m2, durdur, din2, "periyodik", g))
        await t
        await asyncio.sleep(0)
    asyncio.run(kos2())
    assert m2.cikis_kodu == 0 and not any(x.get("olay") == "gorev_bitti" for x in m2.kayitlar)


def test_g12b_main_gorev_olunce_sifir_olmayan_cikis_kodu(tmp_path, monkeypatch):
    """`main` → `calis` bitince `motor.cikis_kodu` döner: görev beklenmedik bittiyse 1 (systemd `Restart=on-failure` yeniden başlatır; 3 = başlamadı, yeniden başlatılmaz)."""
    class M:
        def __init__(self, *a, **k):
            self.cikis_kodu = 0

        def baslat(self):
            return None

    async def calis(motor, sure_sn=None):
        motor.cikis_kodu = 1                                                   # `_gorev_bitti` etkisi
        return {}
    monkeypatch.setattr(mt, "Motor", M)
    monkeypatch.setattr(mt, "calis", calis)
    monkeypatch.setattr(mt, "kip_belirle", lambda rules, istenen=None: "sanal")
    monkeypatch.setattr(mt, "etkin_kasa", lambda rules, kip, post, **k: (1000.0, None))
    assert mt.main(["--durum-dizin", str(tmp_path / "durum")]) == 1


# ================================================================================================ bekçi
class Saatci:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_bekci_180_sn_ilerleme_yoksa_alarm_ve_cikis_1_nabiz_sifirlar():
    """Sınır 180 sn: 179 sn → yok; nabız → sayaç sıfırlanır; nabızdan 180 sn sonra → kayıt `bekci_tetik` + Telegram alarmı + `cik(1)`; bir kez."""
    saat, cikis = Saatci(), []
    m = types.SimpleNamespace(kayitlar=[], tg=types.SimpleNamespace(gonderilen=[]))
    m.kayit = m.kayitlar.append
    m.tg.gonder = m.tg.gonderilen.append
    b = mt.Bekci(m, RULES["canli_bekci_sn"], saat=saat, cik=cikis.append, alarm_bekle_sn=1.0)
    assert RULES["canli_bekci_sn"] == 180
    saat.t += 179
    assert b.kontrol() is False and cikis == []
    b.nabiz()
    saat.t += 179.9
    assert b.kontrol() is False
    saat.t += 0.1
    assert b.kontrol() is True and cikis == [1]
    assert m.kayitlar == [{"olay": "bekci_tetik", "gecen_sn": 180.0, "sinir_sn": 180.0}] and "motor dondu" in m.tg.gonderilen[0]
    saat.t += 500
    assert b.kontrol() is False and cikis == [1]                               # tek sefer


def test_bekci_asili_dakika_periyodik_ile_tetiklenir():
    """Uçtan uca: `dakika` asılı (G-12a: zaman aşımsız emir kilidi tutar) → `_periyodik` nabız atamaz; bekçi iş parçacığı sınırı geçince `cik(1)`."""
    saat, cikis = Saatci(), []
    serbest = threading.Event()
    m = types.SimpleNamespace(kayitlar=[], tg=types.SimpleNamespace(gonderilen=[]), dur_istendi=False, saha=types.SimpleNamespace(uyeler=[]))
    m.kayit = m.kayitlar.append
    m.tg.gonder = m.tg.gonderilen.append
    m.dakika = lambda: serbest.wait(5)
    b = mt.Bekci(m, 180, saat=saat, cik=cikis.append, alarm_bekle_sn=1.0)
    durdur_b = threading.Event()
    th = threading.Thread(target=b.calistir, args=(durdur_b, 0.01), daemon=True)
    th.start()
    din = types.SimpleNamespace(izle_ekle=lambda a: None, durdur=lambda: None, ozet=lambda: {"genel": {}})

    async def kos():
        durdur = asyncio.Event()
        t = asyncio.create_task(mt._periyodik(m, durdur, din, aralik_sn=0.01, bekci=b))
        await asyncio.sleep(0.05)
        saat.t += 181                                                           # dakika hâlâ dönmedi
        for _ in range(200):
            if cikis:
                break
            await asyncio.sleep(0.01)
        serbest.set()
        durdur.set()
        await t
    asyncio.run(kos())
    th.join(1)
    assert cikis == [1] and m.kayitlar[0]["olay"] == "bekci_tetik" and not th.is_alive()
