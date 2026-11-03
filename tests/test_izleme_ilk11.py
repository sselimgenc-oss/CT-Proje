"""İzleme motoru İlk 11 eklemeleri (A2 PR-2): `ilk11_form_ham`, `ilk11_gecerli_saat`, `--liste`, `durum.json` kırpması (tam geçmiş `motor.json`'da)."""
from __future__ import annotations

import json

import pandas as pd
import pytest
import yaml

from copytrade import izleme_motoru as m
from copytrade import kopya_v3
from copytrade.kurallar import load_rules
from test_izleme import ADDRESS, NOW, T0, Client, project

RULES = load_rules()


def v3_islem(gun_once, gecerli=True, sonuc=1.0):
    kapanis = NOW - pd.Timedelta(days=gun_once)
    return {'coin': 'BTC', 'acilis': m.iso(kapanis - pd.Timedelta(hours=1)), 'kapanis': m.iso(kapanis), 'sonuc_usd': sonuc,
            'getiri': sonuc / 20, 'neden': 'trader', 'gecerli': gecerli}


def trader_with(islemler):
    return {'id': 'T1', 'sanal_kopya_v3': {'surum': 'v3', 'bakiye_usd': 1000.0, 'kapanan_islemler': islemler}}


# ------------------------------------------------------------------------------------------------ kırpma
def test_kirpma_pencere_ve_son_6_gecerli_kurali():
    """30 günlük pencere (now − 30 g, now]; pencere dışı 31. gün düşer. Pencere dışı olsa da SON 6 GEÇERLİ işlem kalır; geçersiz eski işlem kalmaz."""
    eski_gecerli = [v3_islem(40 + i, True) for i in range(8)]                    # 8 eski geçerli: yalnız en yeni 6'sı kalır
    eski_gecersiz = [v3_islem(35, False)]
    yeni = [v3_islem(29.9), v3_islem(5, False), v3_islem(0.5)]
    sinirda = [v3_islem(30, False)]                                              # tam 30 g önce: pencere (açık alt sınır) dışı, geçersiz -> düşer
    t = trader_with(eski_gecerli + eski_gecersiz + sinirda + yeni)
    kirpilmis = m.durum_icin_kirp(t, NOW, RULES)
    kalan = kirpilmis['sanal_kopya_v3']['kapanan_islemler']
    assert kirpilmis['sanal_kopya_v3']['kapanan_islemler_toplam'] == 13
    # pencere içi 3 + pencere dışı SON 6 geçerli (yaş: 40..45 gün en yeni 6 -> yaşları 40,41,...,45) — pencere içi geçerli olanlar da "son 6 geçerli"ye sayılır
    pencere_ici_gecerli = sum(1 for x in yeni if x['gecerli'])
    assert pencere_ici_gecerli == 2
    # son 6 geçerli = 2 pencere içi + en yeni 4 eski geçerli (yaş 40..43)
    eski_kalan = [x for x in kalan if x in eski_gecerli]
    assert len(eski_kalan) == 4 and eski_kalan == eski_gecerli[:4]
    assert all(x in kalan for x in yeni) and v3_islem(35, False) not in kalan and sinirda[0] not in kalan
    assert len(kalan) == 4 + 3
    # giriş nesnesi değişmez (tam geçmiş korunur)
    assert len(t['sanal_kopya_v3']['kapanan_islemler']) == 13 and 'kapanan_islemler_toplam' not in t['sanal_kopya_v3']


def test_kirpma_6_gecerli_islem_30_gunden_eskiyse_yine_yayimlanir_ve_yoksa_dokunmaz():
    t = trader_with([v3_islem(60 + i) for i in range(6)])
    assert len(m.durum_icin_kirp(t, NOW, RULES)['sanal_kopya_v3']['kapanan_islemler']) == 6
    assert m.durum_icin_kirp({'id': 'x'}, NOW, RULES) == {'id': 'x'}
    yer_tutucu = {'sanal_kopya_v3': {'surum': 'v3', 'durum': 'hesaplanamadi'}}
    assert m.durum_icin_kirp(yer_tutucu, NOW, RULES) == yer_tutucu
    assert m.durum_icin_kirp(trader_with([]), NOW, RULES)['sanal_kopya_v3']['kapanan_islemler'] == []


def test_run_durum_json_kirpilir_motor_json_tam_gecmisi_tutar(tmp_path, monkeypatch):
    """31. gündeki (ve eski geçersiz) işlem durum.json'da yok ama motor.json'da var; sınırın içindekiler iki dosyada da var."""
    eski_gecersiz, eski_gecerli, yeni = v3_islem(31, False, -2.0), v3_islem(31.5, True, 3.0), v3_islem(2, True, 1.0)
    gercek = kopya_v3.hesapla

    def sahte(*a, **k):
        return {**gercek(*a, **k), 'kapanan_islemler': [eski_gecersiz, eski_gecerli, yeni]}
    monkeypatch.setattr(kopya_v3, 'hesapla', sahte)
    root = project(tmp_path)
    sonuc = m.run(root, root / 'out', Client(), NOW)
    durum = json.loads((root / 'out/durum.json').read_text())
    motor = json.loads((root / 'out/motor.json').read_text())
    yayin = durum['traderlar'][0]['sanal_kopya_v3']
    tam = motor['traderlar']['T1']['son_trader']['sanal_kopya_v3']['kapanan_islemler']
    assert tam == [eski_gecersiz, eski_gecerli, yeni]                              # kalıcı kayıt: silinmeden
    assert yayin['kapanan_islemler'] == [eski_gecerli, yeni] and yayin['kapanan_islemler_toplam'] == 3   # eski geçerli son-6 kuralıyla kalır, geçersiz düşer
    assert sonuc['traderlar'][0]['sanal_kopya_v3']['kapanan_islemler'] == yayin['kapanan_islemler']


# ------------------------------------------------------------------------------------------------ form_ham / gecerli_saat / liste
def test_run_ilk11_form_ham_ve_gecerli_saat_yayimlanir(tmp_path):
    root, client = project(tmp_path), Client()
    bir = m.run(root, root / 'out', client, NOW)['traderlar'][0]
    form = bir['ilk11_form_ham']
    assert set(form) == {'alanlar', 'alan_kaynagi', 'pencere_bitis', 'dolu_alan'}
    assert form['pencere_bitis'] == '2026-10-27T12:00:00Z' and form['alanlar']['hesap'] is None
    assert bir['hesap_degeri'] == 1000.0 and form['alan_kaynagi']['hesap'] == 'akil_sagligi_ihlali:1000'    # 5.000 $ altı: aralık dışı, kullanılmaz
    assert list(form['alanlar']) == ['golge', 'ay_roi', 'hafta_roi', 'hesap', 'dusus', 'kazanma', 'siklik', 'tutma', 'kaldirac', 'tutarli']
    assert form['alanlar']['siklik'] == 0.0 and form['dolu_alan'] == sum(v is not None for v in form['alanlar'].values())
    assert bir['ilk11_gecerli_saat'] == {'baslangic': str(T0.date()), 'saat': 2, 'son_saat': '2026-10-27T12:00:00Z'}
    # aynı 2 saatlik kovadaki ikinci koşu yeniden saymaz (13:00 dahil); sonraki kova 2 saat ekler
    assert m.run(root, root / 'out', client, NOW + pd.Timedelta(minutes=20))['traderlar'][0]['ilk11_gecerli_saat']['saat'] == 2
    assert m.run(root, root / 'out', client, NOW + pd.Timedelta(hours=1))['traderlar'][0]['ilk11_gecerli_saat']['saat'] == 2
    iki = m.run(root, root / 'out', client, NOW + pd.Timedelta(hours=2))['traderlar'][0]
    assert iki['ilk11_gecerli_saat']['saat'] == 4 and iki['ilk11_form_ham']['pencere_bitis'] == '2026-10-27T14:00:00Z'
    motor = json.loads((root / 'out/motor.json').read_text())
    assert motor['traderlar']['T1']['ilk11_gecerli_saat']['saat'] == 4             # kalıcı sayaç motor.json'da


def test_gecerli_saat_takim_hafta_degisince_sifirlanir_ve_hatali_okuma_saymaz(tmp_path):
    satir = {'id': 'T1', 'adres': ADDRESS, 'takma_ad': 'Test', 'durum': 'izlemede', 't0': str(T0.date()), 'takim': 'paf', 'takim_hafta': '2026-10-25'}
    root, client = project(tmp_path, [satir]), Client()
    assert m.run(root, root / 'out', client, NOW)['traderlar'][0]['ilk11_gecerli_saat']['baslangic'] == '2026-10-25'

    class Bozuk(Client):
        def fills(self, address, start):
            raise RuntimeError('429')
    with pytest.raises(RuntimeError, match='Tüm trader'):                               # tek trader hatalı -> yayın yok, sayaç ilerlemez
        m.run(root, root / 'out', Bozuk(), NOW + pd.Timedelta(hours=1))
    saved = json.loads((root / 'out/motor.json').read_text())['traderlar']['T1']['ilk11_gecerli_saat']
    assert saved['saat'] == 2
    yeni = {**satir, 'takim_hafta': '2026-11-01'}
    (root / 'copytrade/izleme_listesi.yaml').write_text(yaml.safe_dump({'traderlar': [yeni]}))
    sonuc = m.run(root, root / 'out', client, NOW + pd.Timedelta(hours=2))['traderlar'][0]['ilk11_gecerli_saat']
    assert sonuc == {'baslangic': '2026-11-01', 'saat': 2, 'son_saat': '2026-10-27T14:00:00Z'}


def test_liste_parametresi_alternatif_listeyi_okur(tmp_path):
    root = project(tmp_path, [{'id': 'T1', 'adres': ADDRESS, 'takma_ad': 'Ana', 'durum': 'izlemede', 't0': str(T0.date())}])
    alternatif = tmp_path / 'baska' / 'izleme_listesi.yaml'
    alternatif.parent.mkdir()
    alternatif.write_text(yaml.safe_dump({'traderlar': [{'id': 'K1', 'adres': '0x' + '3' * 40, 'takma_ad': 'Kadro', 'durum': 'izlemede', 't0': str(T0.date()),
                                                         'takim': 'ilk11', 'takim_hafta': '2026-11-01'}]}))
    sonuc = m.run(root, root / 'out', Client(), NOW, liste=alternatif)
    assert [t['id'] for t in sonuc['traderlar']] == ['K1'] and sonuc['traderlar'][0]['takim'] == 'ilk11'
    assert [t['id'] for t in m.run(root, root / 'out2', Client(), NOW)['traderlar']] == ['T1']        # varsayılan değişmedi


def test_form_ham_hatasi_izleme_okumasini_dusurmez(tmp_path, monkeypatch):
    from copytrade import ilk11_alanlar

    def patlak(*a, **k):
        raise KeyError('bozuk')
    monkeypatch.setattr(ilk11_alanlar, 'form_ham_30g', patlak)
    root = project(tmp_path)
    trader = m.run(root, root / 'out', Client(), NOW)['traderlar'][0]
    assert trader['gecerli'] is True and trader['ilk11_form_ham'] == {'hata': "'bozuk'"}


def test_gecerli_saat_24_saatte_12_kosu_24_saat_ayni_kovada_bir_kez_k18():
    """Altın örnek (K-18): izleme 2 saatte bir. 24 saatte 12 koşu -> 24 saat (saat/24 = 1 gün); aynı 2 saatlik kovada ikinci koşu (20 dk sonra) yeniden saymaz."""
    satir = {'id': 'T1', 't0': '2026-10-27'}
    saved: dict = {}
    for k in range(12):
        sonuc = m.gecerli_saat_say(saved, satir, NOW + pd.Timedelta(hours=2 * k, minutes=23))
    assert (sonuc['saat'], sonuc['saat'] / 24) == (24, 1.0)
    assert m.gecerli_saat_say(saved, satir, NOW + pd.Timedelta(hours=22, minutes=43))['saat'] == 24        # aynı kova (22:00-24:00): tekrar sayılmaz
    assert m.gecerli_saat_say(saved, satir, NOW + pd.Timedelta(hours=24, minutes=1))['saat'] == 26         # sonraki kova +2
