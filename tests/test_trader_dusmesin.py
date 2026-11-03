"""A4-1 / K-14: tek bir eksik yüzünden trader takipten düşmez; trader başına `veri_durumu` (tamam | fiyatsiz | perp_bos | okuma_hatasi | bayat).

Not: izleme listesindeki `durum` (kopyala | izlemede | durdu) alanı ZATEN trader sözlüğünde olduğundan yeni kod `veri_durumu` adını taşır.
Fixture: tests/test_izleme.py (`Client`: tek BTC dolumu, 10:00'da 1 BTC alış @100; NOW = 12:00; tarz bilinmiyor -> 30 dk gecikme -> yürütme hedefi 10:30).
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

from copytrade import izleme_motoru as m
from copytrade.defter import sabit_tutar_egrisi
from copytrade.kurallar import load_rules
from test_izleme import ADDRESS, NOW, T0, Client, fill, project

TUTAR_1000 = sabit_tutar_egrisi(load_rules())(1000.0)
HEDEF_BAS = m.millis(m.timestamp('2026-10-27T10:30:00Z'))


class MumsuzSaat(Client):
    """10:30 hedefinden sonraki bir saat boyunca HİÇ mum yok (hem 1 dk hem 1 sa isteklerinde): ne hedef ne ona 1 aralık içinde yakın mum bulunur."""

    def candles(self, coin, start, end, interval='1m'):
        return [c for c in super().candles(coin, start, end, interval) if not HEDEF_BAS <= int(c['t']) <= HEDEF_BAS + 61 * m.MINUTE]


class MumHic(Client):
    def candles(self, coin, start, end, interval='1m'):
        return []


def trader_of(sonuc, kimlik='T1'):
    return next(t for t in sonuc['traderlar'] if t['id'] == kimlik)


def test_tamam_durumu_normal_okumada(tmp_path):
    root = project(tmp_path)
    t = trader_of(m.run(root, root / 'out', Client(), NOW))
    assert (t['veri_durumu'], t['veri_durumu_neden'], t['gecerli']) == ('tamam', '', True) and t['durum'] == 'izlemede'     # listedeki `durum` korunur


def test_eksik_1_dk_mum_trader_dusmez_fiyatsiz_v3_sonucu_ve_eksik_sayisi_elle(tmp_path):
    """Tek dolum (10:00, hedef 10:30) ve hedef civarında mum yok: v1'de dolum atlanır (1), v3'te `fiyatsiz_eylem` = 1 (copy_ledger sayar); kopya hiç açmadığından
    v3 bakiyesi 1.000 $; trader geçerli, olaylar (açılış) yine üretilir."""
    root = project(tmp_path)
    sonuc = m.run(root, root / 'out', MumsuzSaat(), NOW)
    t = trader_of(sonuc)
    assert t['gecerli'] is True and t['veri_durumu'] == 'fiyatsiz' and '1 dolum' in t['veri_durumu_neden']
    assert t['sanal_kopya']['fiyatsiz_eylem'] == 1 and t['sanal_kopya']['bakiye_usd'] == 1000 and 'atlandı' in t['sanal_kopya']['not']
    v3 = t['sanal_kopya_v3']
    assert v3['fiyatsiz_eylem'] == 1 and v3['bakiye_usd'] == pytest.approx(1000.0) and v3['kapanan_islemler'] == [] and 'durum' not in v3
    assert [e['tur'] for e in sonuc['olaylar']] == ['acilis'] and sonuc['olaylar'][0]['trader'] == 'T1'
    assert json.loads((root / 'out/durum.json').read_text())['traderlar'][0]['veri_durumu'] == 'fiyatsiz'


def test_tum_mumlar_eksik_iki_dolum_hepsi_sayilir_trader_yine_dusmez(tmp_path):
    root = project(tmp_path)
    client = MumHic([fill('2026-10-27T10:00:00Z', 1, 'B', 1, 0, 100), fill('2026-10-27T11:00:00Z', 2, 'A', 1, 1, 110)])
    t = trader_of(m.run(root, root / 'out', client, NOW))
    assert t['gecerli'] is True and t['veri_durumu'] == 'fiyatsiz'
    assert t['sanal_kopya']['fiyatsiz_eylem'] == 2 and t['sanal_kopya_v3']['fiyatsiz_eylem'] == 2
    assert t['sanal_kopya_v3']['bakiye_usd'] == pytest.approx(1000.0) and t['sanal_kopya']['bakiye_usd'] == 1000


class GecikmeliMum(MumsuzSaat):
    """`mum_var` açılana kadar hedef mumu yok; kaç kez API'ye (1 dk / 1 sa, işaretleme hariç) sorulduğunu sayar."""
    mum_var = False
    hedef_sorgu = 0

    def candles(self, coin, start, end, interval='1m'):
        self.hedef_sorgu += int(start == HEDEF_BAS and interval == '1m')
        if self.mum_var:
            return Client.candles(self, coin, start, end, interval)
        return super().candles(coin, start, end, interval)


def test_eksik_mum_negatif_onbellek_6_saat_sonra_bir_kez_yeniden_denenir_sayilir(tmp_path):
    """K-18 altın örnek: hedef mum 10:30 yok. Saat 12:00 (NOW): API'ye sorulur (okuma 1), negatif kayıt yazılır. +1 saat ve +5 saat: API'ye SORULMAZ (okuma hâlâ 1),
    trader `fiyatsiz`, `mum_eksik` = {hedef 1, onbellekten 1}, neden metni önbelleği söyler. +6 saat: yeniden sorulur (okuma 2); mum gelmişse hesaba girer, `tamam`, kayıt silinir."""
    root = project(tmp_path)
    client = GecikmeliMum()
    t0 = trader_of(m.run(root, root / 'out', client, NOW))
    assert t0['veri_durumu'] == 'fiyatsiz' and t0['mum_eksik'] == {'hedef': 1, 'onbellekten': 0} and client.hedef_sorgu == 1
    saved = json.loads((root / 'out/motor.json').read_text())['traderlar']['T1']
    assert saved['mum_eksik'] == {'BTC': {str(HEDEF_BAS): m.millis(NOW)}}
    for saat in (1, 5):
        t = trader_of(m.run(root, root / 'out', client, NOW + pd.Timedelta(hours=saat)))
        assert t['veri_durumu'] == 'fiyatsiz' and t['mum_eksik'] == {'hedef': 1, 'onbellekten': 1} and 'negatif önbellekten' in t['veri_durumu_neden']
        assert client.hedef_sorgu == 1                                                      # API'ye yeniden sorulmadı
    client.mum_var = True
    t6 = trader_of(m.run(root, root / 'out', client, NOW + pd.Timedelta(hours=6)))
    assert client.hedef_sorgu == 2 and t6['veri_durumu'] == 'tamam' and t6['mum_eksik'] == {'hedef': 0, 'onbellekten': 0}
    assert t6['sanal_kopya']['bakiye_usd'] == pytest.approx(1000 - 102 * .00095) and 'fiyatsiz_eylem' not in t6['sanal_kopya']
    assert json.loads((root / 'out/motor.json').read_text())['traderlar']['T1']['mum_eksik'] == {}


def test_eksik_mum_6_saat_sonra_hala_yoksa_kayit_tazelenir_kalici_atlama_yok(tmp_path):
    root = project(tmp_path)
    client = GecikmeliMum()
    m.run(root, root / 'out', client, NOW)
    t = trader_of(m.run(root, root / 'out', client, NOW + pd.Timedelta(hours=6)))
    assert client.hedef_sorgu == 2 and t['veri_durumu'] == 'fiyatsiz' and t['mum_eksik'] == {'hedef': 1, 'onbellekten': 0}       # yeniden denendi, hâlâ yok
    saved = json.loads((root / 'out/motor.json').read_text())['traderlar']['T1']
    assert saved['mum_eksik'] == {'BTC': {str(HEDEF_BAS): m.millis(NOW + pd.Timedelta(hours=6))}}                                   # kayıt tazelendi
    m.run(root, root / 'out', client, NOW + pd.Timedelta(hours=7))
    assert client.hedef_sorgu == 2                                                                                            # 6 saat dolmadan yine sorulmaz
    client.mum_var = True
    assert trader_of(m.run(root, root / 'out', client, NOW + pd.Timedelta(hours=12)))['veri_durumu'] == 'tamam'                    # kalıcı atlama yok


def test_execution_candles_negatif_birim_altin_ornek():
    """Elle: now=T; negatif {BTC: {hedef: T-5 sa}} -> sorulmaz, eksik'te onbellek True; T-6 sa -> sorulur."""
    f = fill()
    hedef = f['time'] + 30 * m.MINUTE
    client = Client()
    simdi = hedef + 5 * 60 * m.MINUTE
    eksik, negatif = [], {'BTC': {str(hedef): simdi - 5 * 60 * m.MINUTE}}
    candles, _ = m.execution_candles(client, [f], {}, simdi, eksik=eksik, negatif=negatif)
    assert client.candle_reads == 0 and candles == {} and eksik == [{'coin': 'BTC', 'hedef': hedef, 'onbellek': True}]
    eksik, negatif = [], {'BTC': {str(hedef): simdi - 6 * 60 * m.MINUTE}}
    candles, _ = m.execution_candles(client, [f], {}, simdi, eksik=eksik, negatif=negatif)
    assert client.candle_reads == 1 and candles['BTC'][0]['o'] == 102 and eksik == [] and negatif == {}


def test_perp_hesap_degeri_sifir_v3_ve_olaylar_surer_v1_yer_tutucu(tmp_path):
    root = project(tmp_path)
    client = Client()
    client.account = 0
    sonuc = m.run(root, root / 'out', client, NOW)
    t = trader_of(sonuc)
    assert t['gecerli'] is True and t['veri_durumu'] == 'perp_bos' and 'hesap değeri 0' in t['veri_durumu_neden']
    assert t['sanal_kopya']['yer_tutucu'] is True and t['sanal_kopya']['bakiye_usd'] == 1000 and t['sanal_kopya']['egri'] == []
    assert t['sanal_kopya_v2']['durum'] == 'hesaplanamadi' and 'perp hesap değeri 0' in t['sanal_kopya_v2']['neden']
    v3 = t['sanal_kopya_v3']
    assert 'durum' not in v3 and v3['bakiye_usd'] == pytest.approx(1000 - TUTAR_1000 * 0.00095) and v3['fiyatsiz_eylem'] == 0     # 1.000 $ kopya: sabit tutar açılış maliyeti (mum 102, işaret 102: K/Z 0)
    assert [e['tur'] for e in sonuc['olaylar']] == ['acilis'] and sonuc['olaylar'][0]['hesap_payi'] == 0.0
    assert t['saglik']['isik'] != 'bilinmiyor'                                                      # sağlık paydası var: yalnız hesap sıfır
    # Sıfır hesap kopya paydasını SIFIRA sabitlemez: sonraki saat hesap pozitifse v1 gerçek paydayla çalışır
    assert 'kopya_paydasi' not in json.loads((root / 'out/motor.json').read_text())['traderlar']['T1']
    client.account = 1000
    sonra = trader_of(m.run(root, root / 'out', client, NOW + pd.Timedelta(hours=1)))
    assert sonra['veri_durumu'] == 'tamam' and 'yer_tutucu' not in sonra['sanal_kopya'] and sonra['sanal_kopya']['bakiye_usd'] == pytest.approx(1000 - 102 * .00095)
    assert json.loads((root / 'out/motor.json').read_text())['traderlar']['T1']['kopya_paydasi'] == 1000


class SaglikPaydasiYok(Client):
    def portfolio(self, address):
        self.portfolio_reads += 1
        return [['perpAllTime', {'pnlHistory': [], 'accountValueHistory': [[m.millis(m.timestamp('2026-10-01')), '0']]}]]


def test_saglik_paydasi_yoksa_isik_bilinmiyor_takip_surer_sonraki_saat_toparlanir(tmp_path):
    root = project(tmp_path)
    t = trader_of(m.run(root, root / 'out', SaglikPaydasiYok(), NOW))
    assert t['gecerli'] is True and t['saglik']['isik'] == 'bilinmiyor' and t['saglik']['nedenler'][0].startswith('sağlık paydası yok:')
    assert t['veri_durumu'] == 'tamam' and t['sanal_kopya']['bakiye_usd'] == pytest.approx(1000 - 102 * .00095)       # dolumlar işlendi
    assert t['egri'] == [] and t['form']['skor'] == 0.0
    saved = json.loads((root / 'out/motor.json').read_text())['traderlar']['T1']
    assert saved['saglik_paydasi'] is None and 'saglik_paydasi_t0' not in saved                      # sabitlenmedi: yeniden denenir
    iyi = trader_of(m.run(root, root / 'out', Client(), NOW + pd.Timedelta(hours=1)))
    assert iyi['saglik']['isik'] in {'yesil', 'sari', 'kirmizi'} and iyi['egri'] != []
    assert json.loads((root / 'out/motor.json').read_text())['traderlar']['T1']['saglik_paydasi'] == 1000


class Biri(Client):
    kirik = False

    def fills(self, address, start):
        if self.kirik:
            raise RuntimeError('429 ağ hatası')
        return super().fills(address, start)


def test_okuma_hatasi_onceki_veri_korunur_ve_isaretlenir(tmp_path):
    satir = {'id': 'T1', 'adres': ADDRESS, 'takma_ad': 'Bir', 'durum': 'izlemede', 't0': str(T0.date())}
    root = project(tmp_path, [satir, {**satir, 'id': 'T2', 'adres': '0x' + '2' * 40, 'takma_ad': 'İki'}])
    client = Biri()
    ilk = m.run(root, root / 'out', client, NOW)
    eski = trader_of(ilk, 'T1')
    assert eski['veri_durumu'] == 'tamam'

    class T1Kirik(Client):
        def fills(self, address, start):
            if address == ADDRESS:
                raise RuntimeError('429 ağ hatası')
            return super().fills(address, start)
    sonra = trader_of(m.run(root, root / 'out', T1Kirik(), NOW + pd.Timedelta(hours=1)), 'T1')
    assert sonra['veri_durumu'] == 'okuma_hatasi' and '429' in sonra['veri_durumu_neden'] and sonra['gecerli'] is False
    assert sonra['sanal_kopya_v3'] == eski['sanal_kopya_v3'] and sonra['veri_zamani'] == eski['veri_zamani'] and sonra['durum'] == 'izlemede'


def test_hic_okunmamis_trader_yer_tutucu_okuma_hatasi_ve_v1_yer_tutucu(tmp_path):
    rows = [{'id': 'T1', 'adres': ADDRESS, 'takma_ad': 'Bir', 'durum': 'izlemede', 't0': str(T0.date())},
            {'id': 'T2', 'adres': '0x' + '2' * 40, 'takma_ad': 'İki', 'durum': 'izlemede', 't0': str(T0.date())}]
    root = project(tmp_path, rows)

    class IkinciKirik(Client):
        def fills(self, address, start):
            if address == rows[1]['adres']:
                raise RuntimeError('ilk yanıt yok')
            return super().fills(address, start)
    kirik = trader_of(m.run(root, root / 'out', IkinciKirik(), NOW), 'T2')
    assert kirik['veri_durumu'] == 'okuma_hatasi' and kirik['veri_durumu_neden'] == 'ilk yanıt yok'
    assert kirik['sanal_kopya']['yer_tutucu'] is True and kirik['sanal_kopya_v3']['yer_tutucu'] is True and kirik['gecerli'] is False


def test_veri_durumu_belirle_oncelik_perp_bos_fiyatsiz_tamam():
    belirle = m.veri_durumu_belirle
    assert belirle(1000, {}, {}, 0) == ('tamam', '')
    assert belirle(1000, {'isaret_eksik': 2}, {}, 0) == ('tamam', '')                       # eski v1 sayacı artık durumu belirlemez; coin listesi belirler
    assert belirle(1000, {}, {}, 0, ['ETH', 'SOL']) == ('fiyatsiz', 'işaret fiyatı eksik: ETH, SOL')       # işaret eksiği = FİYAT eksiği
    assert belirle(1000, {}, {'fiyatsiz_eylem': 3}, 0) == ('fiyatsiz', '3 dolum için mum fiyatı eksik (atlandı, sayıldı)')
    assert belirle(1000, {}, {'fiyatsiz_eylem': 3}, 0, ['ETH'])[1] == '3 dolum için mum fiyatı eksik (atlandı, sayıldı); işaret fiyatı eksik: ETH'
    assert belirle(1000, {}, {}, 4)[0] == 'fiyatsiz' and belirle(1000, {'fiyatsiz_eylem': 2}, {}, 0)[0] == 'fiyatsiz'
    assert belirle(0, {}, {'fiyatsiz_eylem': 3}, 4, ['ETH'])[0] == 'perp_bos'


def test_bayat_veri_zamani_uretildiden_120_dk_ve_daha_eskiyse_ve_oncelikler_korunur():
    """Altın örnek: yayın anı 12:00. veri_zamani 09:00 (3 sa = 180 dk > 120) -> bayat; 11:00 (1 sa) -> değil; tam 120 dk (10:00) -> değil (sınır dahil değil)."""
    uretildi = m.timestamp('2026-10-27T12:00:00Z')
    tamam = {'id': 'T1', 'veri_durumu': 'tamam', 'veri_durumu_neden': '', 'veri_zamani': '2026-10-27T09:00:00Z'}
    eski = m.bayat_isle(tamam, uretildi)
    assert (eski['veri_durumu'], eski['veri_durumu_neden']) == ('bayat', 'veri 180 dk eski (> 120 dk)') and tamam['veri_durumu'] == 'tamam'       # girdi değişmez
    assert m.bayat_isle({**tamam, 'veri_zamani': '2026-10-27T11:00:00Z'}, uretildi)['veri_durumu'] == 'tamam'
    assert m.bayat_isle({**tamam, 'veri_zamani': '2026-10-27T10:00:00Z'}, uretildi)['veri_durumu'] == 'tamam'
    for durum in ('okuma_hatasi', 'perp_bos', 'fiyatsiz'):                                          # öncelik: bayat bunları ezmez
        assert m.bayat_isle({**tamam, 'veri_durumu': durum}, uretildi)['veri_durumu'] == durum
    assert m.bayat_isle({**tamam, 'veri_zamani': None}, uretildi)['veri_durumu'] == 'tamam'          # hiç okunmamış yer tutucu zaten okuma_hatasi


def test_run_tasinan_eski_yuk_okuma_hatasi_kalir_taze_okuma_tamam(tmp_path):
    root = project(tmp_path)
    ilk = trader_of(m.run(root, root / 'out', Client(), NOW))
    assert ilk['veri_durumu'] == 'tamam'
    # 3 saat sonra okuma başarısız: taşınan yük okuma_hatasi (bayat değil: öncelik)
    satir = {'id': 'T9', 'adres': '0x' + '9' * 40, 'takma_ad': 'Dokuz', 'durum': 'izlemede', 't0': str(T0.date())}
    (root / 'copytrade/izleme_listesi.yaml').write_text(__import__('yaml').safe_dump({'traderlar': [{'id': 'T1', 'adres': ADDRESS, 'takma_ad': 'Test', 'durum': 'izlemede', 't0': str(T0.date())}, satir]}))

    class Yalniz9Saglam(Client):
        def fills(self, address, start):
            if address == ADDRESS:
                raise RuntimeError('429')
            return super().fills(address, start)
    sonuc = m.run(root, root / 'out', Yalniz9Saglam(), NOW + pd.Timedelta(hours=3))
    assert trader_of(sonuc, 'T1')['veri_durumu'] == 'okuma_hatasi' and trader_of(sonuc, 'T9')['veri_durumu'] == 'tamam'


def test_uc_ozeti_altin_ornek():
    """Elle: önce candleSnapshot 2/40, userFillsByTime 1/20; sonra candleSnapshot 5/130, userFillsByTime 1/20, portfolio 1/20 -> fark: candleSnapshot 3/90, portfolio 1/20 (userFillsByTime 0 -> yazılmaz); ağırlığa göre sıralı."""
    once = {'candleSnapshot': [2, 40], 'userFillsByTime': [1, 20]}
    simdi = {'candleSnapshot': [5, 130], 'userFillsByTime': [1, 20], 'portfolio': [1, 20]}
    assert m.uc_ozeti(simdi, once) == 'candleSnapshot 3/90, portfolio 1/20' and m.uc_ozeti({}, {}) == '—'


def test_a43a_v3_fiyat_hedefi_ham_dolumlar_icin_cekilir_devralinan_kapatma_fiyatsiz_kalmaz(tmp_path):
    """A4-3a altın örnek. Dolum 1 (10:00, satış 4, startPosition +10): devralınan pozisyonu KAPATIR -> `copy_actions` süzgecinde düşer (yeni pozisyon açmaz) ama v3 ham dolumu kullanır;
    yürütme hedefi 10:30 (30 dk). Dolum 2 (11:00 alış 1, hedef 11:30 > NOW 12:00 değil: 11:30 <= 12:00 olgun). Eski kod yalnız dolum 2'nin hedefini çekiyordu (1 dk mum aralığı 11:30'dan başlar):
    10:30 fiyatı yok -> v3 `fiyatsiz_eylem` 1. Yeni kod ham dolumların hedefini çeker: 2 hedef, fiyatsız 0, durum `tamam`."""
    root = project(tmp_path)
    client = Client([fill('2026-10-27T10:00:00Z', 1, 'A', 4, 10, 100), fill('2026-10-27T11:00:00Z', 2, 'B', 1, 6, 110)])
    assert [a['tid'] for a in m.copy_actions(client.rows)] == [2]                                    # dolum 1 süzgeçte düştü (girdi doğrulaması)
    t = trader_of(m.run(root, root / 'out', client, NOW))
    v3 = t['sanal_kopya_v3']
    assert v3.get('fiyatsiz_eylem', 0) == 0 and t['veri_durumu'] == 'tamam'
    hedefler = sorted(int(x) for x in json.loads((root / 'out/motor.json').read_text())['traderlar']['T1']['mumlar']['BTC'])
    assert hedefler == [m.millis(m.timestamp('2026-10-27T10:30:00Z')), m.millis(m.timestamp('2026-10-27T11:30:00Z'))]
