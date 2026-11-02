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


def test_eksik_mum_sonraki_saat_tamamlanirsa_sayilan_dolum_hesaba_girer(tmp_path):
    """Atlanan hedef önbelleğe girmez: mum sonradan gelince aynı dolum bir sonraki saatte hesaplanır, durum `tamam` olur."""
    root = project(tmp_path)
    m.run(root, root / 'out', MumsuzSaat(), NOW)
    t = trader_of(m.run(root, root / 'out', Client(), NOW + pd.Timedelta(hours=1)))
    assert t['veri_durumu'] == 'tamam' and t['sanal_kopya']['bakiye_usd'] == pytest.approx(1000 - 102 * .00095)
    assert 'fiyatsiz_eylem' not in t['sanal_kopya']


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


def test_veri_durumu_belirle_oncelik_perp_bos_fiyatsiz_bayat_tamam():
    belirle = m.veri_durumu_belirle
    assert belirle(1000, {}, {}, 0) == ('tamam', '')
    assert belirle(1000, {'isaret_eksik': 2}, {}, 0)[0] == 'bayat'
    assert belirle(1000, {'isaret_eksik': 2}, {'fiyatsiz_eylem': 3}, 0) == ('fiyatsiz', '3 dolum için mum fiyatı eksik (atlandı, sayıldı)')
    assert belirle(1000, {}, {}, 4)[0] == 'fiyatsiz' and belirle(1000, {'fiyatsiz_eylem': 2}, {}, 0)[0] == 'fiyatsiz'
    assert belirle(0, {'isaret_eksik': 2}, {'fiyatsiz_eylem': 3}, 4)[0] == 'perp_bos'
