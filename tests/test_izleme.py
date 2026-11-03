"""İş A: ağsız yanıtlar, kalıcı arşiv ve sözleşme kabul testleri."""
import copy
import json
import os
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from copytrade import izleme_motoru as m
from copytrade.kararlar import merge
from copytrade.kapi import delayed_copy

ROOT = Path(__file__).resolve().parents[1]
ADDRESS = '0x' + '1' * 40
NOW = m.timestamp('2026-10-27T12:00:00Z')
T0 = m.timestamp('2026-10-27')


def fill(t='2026-10-27T10:00:00Z', tid=1, side='B', size=1, before=0, price=100, coin='BTC', oid=None):
    return {'time': m.millis(t), 'tid': tid, 'oid': str(tid if oid is None else oid), 'coin': coin, 'side': side, 'sz': str(size),
            'startPosition': str(before), 'px': str(price), 'closedPnl': '0', 'fee': '0'}


def test_shared_order_fixture_has_one_event_for_multi_fill_order():
    fixture = json.loads((ROOT / 'tests/fixtures/olaylar.json').read_text())
    events = m.fill_events(fixture['trader'], fixture['fills'], fixture['account'], [])
    actual = [{key: event[key] for key in ('id', 'tur', 'coin', 'yon')} for event in events]
    assert actual == fixture['expected']
    assert all(event['coin'] != '@1' for event in events)


def test_first_health_value_does_not_emit_light_event(tmp_path):
    root, client = project(tmp_path), Client()
    result = m.run(root, root / 'out', client, NOW)
    assert all(event['tur'] != 'isik' for event in result['olaylar'])


def test_one_trader_error_retains_its_last_successful_payload(tmp_path):
    rows = [
        {'id': 'T1', 'adres': ADDRESS, 'takma_ad': 'Bir', 'durum': 'izlemede', 't0': str(T0.date())},
        {'id': 'T2', 'adres': '0x' + '2' * 40, 'takma_ad': 'İki', 'durum': 'izlemede', 't0': str(T0.date())},
    ]
    root = project(tmp_path, rows)
    class SometimesBroken(Client):
        broken = False
        def fills(self, address, start):
            if self.broken and address == rows[1]['adres']:
                raise RuntimeError('429 kısa hata')
            return super().fills(address, start)
    client = SometimesBroken()
    first = m.run(root, root / 'out', client, NOW)
    client.broken = True
    result = m.run(root, root / 'out', client, NOW + pd.Timedelta(hours=1))
    old = next(trader for trader in first['traderlar'] if trader['id'] == 'T2')
    retained = next(trader for trader in result['traderlar'] if trader['id'] == 'T2')
    assert retained['hesap_degeri'] == old['hesap_degeri']
    assert retained['saglik']['nedenler'][-1] == 'veri hatası: 429 kısa hata'
    assert retained['gecerli'] is False
    assert retained['veri_zamani'] == old['veri_zamani']


def test_first_run_error_is_published_as_invalid_trader(tmp_path, capsys):
    rows = [
        {'id': 'T1', 'adres': ADDRESS, 'takma_ad': 'Bir', 'durum': 'izlemede', 't0': str(T0.date())},
        {'id': 'T2', 'adres': '0x' + '2' * 40, 'takma_ad': 'İki', 'tarz': 'swing', 'durum': 'izlemede', 't0': str(T0.date())},
    ]
    root = project(tmp_path, rows)
    class FirstReadBroken(Client):
        def fills(self, address, start):
            if address == rows[1]['adres']:
                raise RuntimeError('ilk yanıt yok')
            return super().fills(address, start)
    result = m.run(root, root / 'out', FirstReadBroken(), NOW)
    broken = next(trader for trader in result['traderlar'] if trader['id'] == 'T2')
    assert {k: broken[k] for k in ('id', 'adres', 'tarz', 'veri_zamani', 'gecerli', 'saglik', 'pozisyonlar')} == {
        'id': 'T2', 'adres': rows[1]['adres'], 'tarz': 'swing', 'veri_zamani': None, 'gecerli': False,
        'saglik': {'isik': 'sari', 'nedenler': ['veri hatası: ilk yanıt yok']}, 'pozisyonlar': []}
    # Yer tutucu, sağlam trader ile aynı anahtarları taşımalı.
    healthy = next(trader for trader in result['traderlar'] if trader['id'] == 'T1')
    assert set(healthy) - {'kopya_paydasi'} <= set(broken)
    assert 'T2: veri hatası: ilk yanıt yok' in capsys.readouterr().out


def test_hourly_fallback_marks_virtual_copy_approximate(tmp_path):
    root, client = project(tmp_path), Client()
    config = root / 'copytrade/izleme_listesi.yaml'
    config.write_text(config.read_text().replace('2026-10-27', '2026-10-01'))
    old = fill('2026-10-01T10:00Z')
    client.rows = [old]
    now = m.timestamp('2026-10-27T12:00Z')
    result = m.run(root, root / 'out', client, now)
    assert result['traderlar'][0]['sanal_kopya']['not'] == 'yaklaşık fiyat'


def test_kararlar_merges_last_decision_without_personal_fields(tmp_path):
    path = tmp_path / 'kararlar.jsonl'
    rows = merge(path, [
        {'olay_id': 'T1-1-acilis', 'zaman': '2026-10-27T10:00:00Z', 'karar': 'acti', 'neden': 'diger', 'not': ''},
        {'olay_id': 'T1-1-acilis', 'zaman': '2026-10-27T10:01:00Z', 'karar': 'atladi', 'neden': 'gec_gordum', 'not': ''},
    ])
    assert rows == [{'olay_id': 'T1-1-acilis', 'zaman': '2026-10-27', 'karar': 'atladi', 'neden': 'gec_gordum', 'not': ''}]
    with pytest.raises(ValueError):
        merge(path, [{'olay_id': 'x', 'zaman': 'now', 'karar': 'acti', 'neden': 'diger', 'not': '', 'tutar': '1'}])
    # Altın örnek: eski bakiye_yok kaydı tarihe indirgenir ve gizlilik nedeniyle diger olur.
    assert merge(tmp_path / 'legacy.jsonl', [
        {'olay_id': 'T1-2-acilis', 'zaman': '2026-10-27T10:02:03Z', 'karar': 'atladi', 'neden': 'bakiye_yok', 'not': ''},
    ]) == [{'olay_id': 'T1-2-acilis', 'zaman': '2026-10-27', 'karar': 'atladi', 'neden': 'diger', 'not': ''}]
    with pytest.raises(ValueError, match='etiketi'):
        merge(tmp_path / 'etiket.jsonl', [{'olay_id': 'x', 'zaman': '2026-10-27', 'karar': 'acti', 'neden': 'diger', 'not': 'serbest'}])


def position(size=1, coin='BTC', value=100):
    return {'position': {'coin': coin, 'szi': str(size), 'entryPx': '100', 'positionValue': str(value),
                         'leverage': {'value': 2}, 'unrealizedPnl': '1'}}


def portfolio():
    days = pd.date_range('2026-07-01', '2026-10-28', freq='1D', tz='UTC')
    return [['perpAllTime', {'pnlHistory': [[m.millis(t), str(i * .2)] for i, t in enumerate(days)],
                             'accountValueHistory': [[m.millis(t), '1000'] for t in days]}]]


class Client:
    def __init__(self, fills=None):
        self.rows = fills if fills is not None else [fill()]
        self.calls = []
        self.positions = [position()]
        self.account = 1000
        self.spot = []                       # spotClearinghouseState bakiyeleri: [{'coin': 'USDC', 'total': '123'}]
        self.portfolio_reads = 0
        self.candle_reads = 0
        self.mark_reads = 0
        self.dexes = [None]
        self.funding = []

    def info(self, payload, weight=20):
        self.calls.append(copy.deepcopy(payload))
        if payload['type'] == 'perpDexs':
            return self.dexes
        if payload['type'] == 'clearinghouseState':
            return {'marginSummary': {'accountValue': str(self.account if not payload.get('dex') else 0)},
                    'assetPositions': self.positions if not payload.get('dex') else [position(coin='xyz:CL', value=50)]}
        if payload['type'] == 'spotClearinghouseState':
            return {'balances': self.spot}
        if payload['type'] == 'userFunding':
            return [x for x in self.funding if payload['startTime'] <= x['time'] <= payload['endTime']]
        raise AssertionError(payload)

    def fills(self, address, start):
        self.calls.append({'type': 'userFillsByTime', 'user': address, 'startTime': start})
        return [copy.deepcopy(f) for f in self.rows if int(f['time']) >= start]

    def portfolio(self, address):
        self.portfolio_reads += 1
        return portfolio()

    def candles(self, coin, start, end, interval='1m'):
        assert interval in {'1m', '1h'}
        if end - start <= 15 * m.MINUTE:        # işaretleme (açık pozisyonun son 1 dk mumu): her koşuda yenilenir, önbelleğe girmez
            self.mark_reads += 1
        else:
            self.candle_reads += 1
        return [{'t': t, 'o': '102'} for t in range(start, end + 1, m.MINUTE)]


def project(tmp_path, rows=None):
    (tmp_path / 'copytrade').mkdir()
    rows = rows if rows is not None else [{'id': 'T1', 'adres': ADDRESS, 'takma_ad': 'Test',
                                         'durum': 'izlemede', 't0': str(T0.date())}]
    (tmp_path / 'copytrade/izleme_listesi.yaml').write_text(yaml.safe_dump({'traderlar': rows}))
    return tmp_path


def test_empty_list_writes_contract_and_never_uses_network(tmp_path):
    root = project(tmp_path, [])
    class NoNetwork:
        def __getattr__(self, name):
            raise AssertionError(name)
    result = m.run(root, root / 'out', NoNetwork(), NOW)
    assert result == {'surum': 1, 'uretildi': '2026-10-27T12:00:00Z', 'kaynak': 'hyperliquid', 'traderlar': [],
                      'kasa_egri': {'oda': [], 'kontrol': []}, 'olaylar': []}
    assert json.loads((root / 'out/durum.json').read_text()) == result


def test_uses_current_main_list_without_changing_it():
    path = ROOT / 'copytrade/izleme_listesi.yaml'
    before = path.read_bytes()
    rows = m.load_list(path)
    ids = [row['id'] for row in rows]
    assert ids and len(set(ids)) == len(ids)
    assert all(row['durum'] == 'izlemede' for row in rows)
    assert path.read_bytes() == before


@pytest.mark.parametrize('change', [dict(id='T1'), dict(adres=ADDRESS), dict(durum='canli'), dict(t0='wrong')])
def test_invalid_or_duplicate_watchlist_rejected(tmp_path, change):
    row = {'id': 'T2', 'adres': '0x' + '2' * 40, 'takma_ad': 'Test-2', 'durum': 'izlemede', 't0': '2026-10-27'}
    row.update(change)
    first = {'id': 'T1', 'adres': ADDRESS, 'takma_ad': 'Test', 'durum': 'izlemede', 't0': '2026-10-27'}
    root = project(tmp_path, [first, row])
    with pytest.raises((ValueError, TypeError)):
        m.load_list(root / 'copytrade/izleme_listesi.yaml')


def test_incremental_overlap_daily_portfolio_and_repeatable_ledger(tmp_path):
    root = project(tmp_path)
    client = Client()
    one = m.run(root, root / 'out', client, NOW)
    two = m.run(root, root / 'out', client, NOW + pd.Timedelta(hours=2))
    first, second = one['traderlar'][0], two['traderlar'][0]
    # son_isaret/payda_yontemi/payda_okuma_sayisi koşuyla ilerler (işaret zamanı, hesap_serisi okuma sayısı); sayılar aynı kalmalı.
    drop = lambda t: {k: ({a: b for a, b in v.items() if a != 'son_isaret'} if k == 'sanal_kopya'
                          else {a: b for a, b in v.items() if a not in ('payda_yontemi', 'payda_okuma_sayisi')} if k == 'sanal_kopya_v2'
                          else v)
                      for k, v in t.items() if k not in ('veri_zamani', 'ilk11_gecerli_saat', 'ilk11_form_ham')}
    assert drop(first) == drop(second)
    assert second['veri_zamani'] == '2026-10-27T14:00:00Z'
    # Koşuyla ilerlemesi BEKLENEN yeni alanlar karşılaştırmadan düşürülmedi, değişimleri ayrıca doğrulanır: saatlik geçerlilik sayacı +1,
    # form alanı yalnız pencere_bitis'te (okuma zamanı) farklıdır.
    assert (first['ilk11_gecerli_saat']['saat'], second['ilk11_gecerli_saat']['saat']) == (2, 4)      # K-18: 2 saatlik koşu = 2 saat
    assert (first['ilk11_gecerli_saat']['son_saat'], second['ilk11_gecerli_saat']['son_saat']) == ('2026-10-27T12:00:00Z', '2026-10-27T14:00:00Z')
    assert (first['ilk11_form_ham']['pencere_bitis'], second['ilk11_form_ham']['pencere_bitis']) == ('2026-10-27T12:00:00Z', '2026-10-27T14:00:00Z')
    assert {k: v for k, v in first['ilk11_form_ham'].items() if k != 'pencere_bitis'} == {k: v for k, v in second['ilk11_form_ham'].items() if k != 'pencere_bitis'}
    assert one['olaylar'] == two['olaylar']
    assert client.portfolio_reads == 2  # sağlık eğrisi saatlik yenilenir
    # yürütme mumu (v1) önbellekten (sabit 1); v2'nin saatlik tasfiye mumu her koşuda bir artımlı okuma ekler (+1/koşu, kendi önbelleği ayrı).
    assert client.candle_reads == 3 and client.mark_reads == 2       # işaret her koşuda bir kez
    starts = [x['startTime'] for x in client.calls if x['type'] == 'userFillsByTime']
    assert starts[-1] == client.rows[-1]['time']  # inclusive boundary is deduplicated
    saved = json.loads((root / 'out/motor.json').read_text())
    assert len(saved['traderlar']['T1']['fills']) == 1
    assert two['traderlar'][0]['sanal_kopya']['bakiye_usd'] == pytest.approx(1000 - 102 * .00095)
    client.rows.append(fill('2026-10-27T12:30:00Z', 2, 'A', 1, 1, 110))
    client.positions = []
    three = m.run(root, root / 'out', client, NOW + pd.Timedelta(hours=2))
    assert len([e for e in three['olaylar'] if e['tur'] == 'acilis']) == 1
    assert len([e for e in three['olaylar'] if e['tur'] == 'kapanis']) == 1
    opened = next(e for e in three['olaylar'] if e['tur'] == 'acilis')
    assert opened['sanal_sonuc']['durum'] == 'kapandi'
    assert opened['sanal_sonuc']['net_yuzde'] == pytest.approx(-.0019)
    m.run(root, root / 'out', client, NOW + pd.Timedelta(days=1))
    assert client.portfolio_reads == 4


def test_pinned_scale_does_not_rewrite_prior_copy_pnl(tmp_path):
    root, client = project(tmp_path), Client()
    first = m.run(root, root / 'out', client, NOW)
    client.account = 2000
    second = m.run(root, root / 'out', client, NOW + pd.Timedelta(hours=1))
    strip = lambda p: {k: v for k, v in p.items() if k != 'son_isaret'}                             # son_isaret koşuyla ilerler; sayılar yeniden yazılmamalı
    assert strip(first['traderlar'][0]['sanal_kopya']) == strip(second['traderlar'][0]['sanal_kopya'])


def test_fills_at_same_millisecond_are_all_retained(tmp_path):
    root, client = project(tmp_path), Client()
    m.run(root, root / 'out', client, NOW)
    client.rows += [fill(tid=2, before=1, size=.5)]
    result = m.run(root, root / 'out', client, NOW)
    assert {e['tur'] for e in result['olaylar']} >= {'acilis', 'buyutme'}
    assert len(json.loads((root / 'out/motor.json').read_text())['traderlar']['T1']['fills']) == 2


def test_address_or_t0_rebinding_cannot_overwrite_history(tmp_path):
    root, client = project(tmp_path), Client()
    m.run(root, root / 'out', client, NOW)
    path = root / 'out/durum.json'
    before = path.read_bytes()
    config = root / 'copytrade/izleme_listesi.yaml'
    config.write_text(config.read_text().replace('2026-10-27', '2026-10-26'))
    with pytest.raises(ValueError, match='adres/t0'):
        m.run(root, root / 'out', client, NOW)
    assert path.read_bytes() == before


@pytest.mark.parametrize('before,size,side,kinds', [
    (0, 1, 'B', ['acilis']), (1, 1, 'A', ['kapanis']),
    (1, .25, 'B', []), (1, .251, 'B', ['buyutme']),
    (1, .25, 'A', []), (1, .251, 'A', ['azaltma']),
    (-1, .3, 'A', ['buyutme']), (-1, .3, 'B', ['azaltma']),
    (1, 2, 'A', ['kapanis', 'acilis']),
])
def test_fill_events_strict_size_threshold_and_flip(before, size, side, kinds):
    f = fill(before=before, size=size, side=side)
    events = m.fill_events('T1', [f], 1000, [])
    assert [e['tur'] for e in events] == kinds
    assert events == m.fill_events('T1', [f], 1000, [])
    assert len({e['id'] for e in events}) == len(events)
    for event in events:
        assert ('sanal_sonuc' in event) == (event['tur'] in {'acilis', 'buyutme'})


def test_copy_execution_delay_cost_funding_and_event_net():
    opening = fill()
    closing = fill('2026-10-27T11:00:00Z', 2, 'A', 1, 1, 500)  # source price is never execution price
    events = {e['id']: e for e in m.fill_events('T1', [opening, closing], 1000, [])}
    funding = [{'time': m.millis('2026-10-27T10:45:00Z'), 'delta': {'coin': 'BTC', 'usdc': '-.5'}}]
    candles = {'BTC': [{'t': m.millis('2026-10-27T10:30:00Z'), 'o': 100},
                       {'t': m.millis('2026-10-27T11:30:00Z'), 'o': 110}]}
    pending = m.copy_results([opening], {}, [], 1000, T0, m.timestamp('2026-10-27T10:29:00Z'), events)
    assert pending['bakiye_usd'] == 1000
    result = m.copy_results([opening, closing], candles, funding, 1000, T0, NOW, events)
    expected = 1000 + 10 - 210 * .00095 - .5
    assert result['bakiye_usd'] == pytest.approx(expected)
    opened = next(e for e in events.values() if e['tur'] == 'acilis')
    assert opened['sanal_sonuc'] == {'durum': 'kapandi', 'net_yuzde': pytest.approx((expected - 1000) / 100),
                                    'kapanis': '2026-10-27T11:30:00Z'}
    reference, _ = delayed_copy([opening, closing], candles, 1000, 30, funding)
    assert result['getiri'] == pytest.approx(float(reference.sum()))


def test_partial_close_keeps_open_event_until_final_exit():
    fills = [fill(), fill('2026-10-27T11:00Z', 2, 'A', .5, 1), fill('2026-10-27T11:20Z', 3, 'A', .5, .5)]
    events = {e['id']: e for e in m.fill_events('T1', fills, 1000, [])}
    candles = {'BTC': [{'t': f['time'] + 30 * m.MINUTE, 'o': 100} for f in fills]}
    m.copy_results(fills[:2], candles, [], 1000, T0, NOW, events)
    assert events[m.event_id('T1', m.order_id(fills[0]), 'acilis')]['sanal_sonuc']['durum'] == 'acik'
    m.copy_results(fills, candles, [], 1000, T0, NOW, events)
    assert events[m.event_id('T1', m.order_id(fills[0]), 'acilis')]['sanal_sonuc']['durum'] == 'kapandi'


def test_order_event_aggregates_partial_fills_until_all_order_quantity_closes():
    """Altın örnek: oid=1 ile 1+1 BTC açılır, 1 BTC kapansa da olay açık; ikinci BTC kapanınca net 9,6105 / 200 = %4,80525."""
    fills = [fill('2026-10-27T10:00Z', 1, 'B', 1, 0, 100, oid=1),
             fill('2026-10-27T10:01Z', 2, 'B', 1, 1, 100, oid=1),
             fill('2026-10-27T11:00Z', 3, 'A', 1, 2, 110, oid=2),
             fill('2026-10-27T11:01Z', 4, 'A', 1, 1, 100, oid=3)]
    events = {e['id']: e for e in m.fill_events('T1', fills, 1000, [])}
    opening = events['T1-1-acilis']
    assert opening['fiyat'] == pytest.approx(100)
    assert opening['hesap_payi'] == pytest.approx(.2)
    candles = {'BTC': [{'t': f['time'] + 30 * m.MINUTE, 'o': [100, 100, 110, 100][i]} for i, f in enumerate(fills)]}
    m.copy_results(fills[:3], candles, [], 1000, T0, NOW, events)
    assert opening['sanal_sonuc']['durum'] == 'acik'
    m.copy_results(fills, candles, [], 1000, T0, NOW, events)
    assert opening['sanal_sonuc'] == {'durum': 'kapandi', 'net_yuzde': pytest.approx(9.6105 / 200),
                                      'kapanis': '2026-10-27T11:31:00Z'}


def test_midnight_cost_is_booked_on_execution_day():
    f = fill('2026-10-26T23:45Z')
    now = m.timestamp('2026-10-27T01:00Z')
    candles = {'BTC': [{'t': f['time'] + 30 * m.MINUTE, 'o': 100}]}
    result = m.copy_results([f], candles, [], 1000, m.timestamp('2026-10-26'), now, {})
    assert result['egri'][0] == ['2026-10-26', 1000]
    assert result['egri'][1][1] == pytest.approx(999.905)


def test_exact_candle_required_and_cache_survives_window_rollover():
    client, cache = Client(), {}
    f = fill()
    candles, approximate = m.execution_candles(client, [f], cache, m.millis(NOW))
    assert candles['BTC'][0]['o'] == 102
    assert not approximate
    m.execution_candles(client, [f], cache, m.millis(NOW) + 10 * m.DAY)
    assert client.candle_reads == 1
    candles, approximate = m.execution_candles(client, [f], {}, m.millis(NOW) + 10 * m.DAY)
    assert approximate and candles['BTC'][0]['o'] == 102
    # K-14: hedef dakikada mum yoksa (31. dakikadaki mum hedef değildir, "sonraki fiyat" asla kullanılmaz) hedef ATLANIR, sayılır, önbelleğe girmez; trader düşmez.
    client.candles = lambda *args, **kwargs: [{'t': f['time'] + 31 * m.MINUTE, 'o': 999}]
    cache, eksik = {}, []
    candles, approximate = m.execution_candles(client, [f], cache, m.millis(NOW), eksik=eksik)
    assert candles == {} and cache == {} and eksik == [{'coin': 'BTC', 'hedef': f['time'] + 30 * m.MINUTE}] and not approximate


def test_failure_preserves_last_successful_payloads(tmp_path):
    root, client = project(tmp_path), Client()
    m.run(root, root / 'out', client, NOW)
    previous = {p.name: p.read_bytes() for p in (root / 'out').iterdir()}
    client.rows.append(fill('2026-10-27T12:00Z', 2, 'B', 1, 1))
    client.fills = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('ağ hatası'))      # okuma hatası (eksik mum artık trader'ı düşürmez, K-14)
    with pytest.raises(RuntimeError, match='Tüm trader'):
        m.run(root, root / 'out', client, NOW + pd.Timedelta(hours=1))
    assert previous == {p.name: p.read_bytes() for p in (root / 'out').iterdir()}


def test_hip3_positions_and_actual_account_leverage(tmp_path):
    root, client = project(tmp_path), Client()
    client.dexes = [{'name': 'xyz'}, {'name': 'flx'}, {'name': 'xyz'}]
    client.positions = [position(value=4000)]
    result = m.run(root, root / 'out', client, NOW)
    trader = result['traderlar'][0]
    assert trader['hesap_degeri'] == 1000
    assert trader['saglik']['isik'] == 'sari'  # gross notional / account, not the 2x setting
    assert {p['coin'] for p in trader['pozisyonlar']} == {'BTC', 'xyz:CL'}
    assert next(p for p in trader['pozisyonlar'] if p['coin'] == 'xyz:CL')['sinif'] == 'emtia'
    states = [call for call in client.calls if call['type'] == 'clearinghouseState']
    assert states == [
        {'type': 'clearinghouseState', 'user': ADDRESS},
        {'type': 'clearinghouseState', 'user': ADDRESS, 'dex': 'xyz'},
        {'type': 'clearinghouseState', 'user': ADDRESS, 'dex': 'flx'},
    ]


def test_invalid_perp_dex_response_is_not_silently_ignored():
    with pytest.raises(ValueError, match='perpDexs'):
        m.perp_dex_names({'name': 'xyz'})
    with pytest.raises(ValueError, match='dex adı'):
        m.perp_dex_names([{'name': ''}])


def test_portfolio_uses_pnl_not_deposits():
    data = portfolio()
    denominator = m.health_denominator(data, T0)
    curve = m.portfolio_curve(data, NOW, denominator)
    data[0][1]['accountValueHistory'][-1][1] = '100000000'
    changed = m.portfolio_curve(data, NOW, denominator)
    pd.testing.assert_series_equal(curve, changed)  # robust median ignores one deposit
    assert (curve.diff().dropna() > 0).all()


def test_health_denominator_is_the_t0_value_not_a_later_median():
    data = portfolio()
    data[0][1]['accountValueHistory'][0][1] = '500'
    data[0][1]['accountValueHistory'][-1][1] = '9000'
    assert m.health_denominator(data, T0) == pytest.approx(1000)


def history(live=None):
    daily = np.r_[np.tile([.002, -.001, .001, 0], 20), live if live is not None else [.001]]
    return pd.Series(np.r_[0, daily.cumsum()], index=pd.date_range('2026-08-07', periods=len(daily) + 1, tz='UTC'))


@pytest.mark.parametrize('leverage,martingale,last,expected,reason', [
    (2.9, False, m.millis(NOW), 'yesil', 'normal'),
    (3, False, m.millis(NOW), 'sari', '3–10'),
    (10, False, m.millis(NOW), 'sari', '3–10'),
    (10.01, False, m.millis(NOW), 'kirmizi', '> 10'),
    (1, True, m.millis(NOW), 'kirmizi', 'martingale'),
    (1, False, m.millis(NOW) - 30 * m.DAY, 'sari', 'işlem yok'),
])
def test_health_leverage_martingale_inactivity(leverage, martingale, last, expected, reason):
    h = history()
    result = m.health(h, h.index[-1], NOW, leverage, martingale, last)
    assert result['isik'] == expected
    assert any(reason in x for x in result['nedenler'])


def check_shape(actual, examples):
    if actual is None:
        assert any(example is None for example in examples)
    elif isinstance(actual, dict):
        # v1.4 may add contract fields while the static v1.3 example remains a lower bound.
        matching = [e for e in examples if isinstance(e, dict) and set(e).issubset(actual)]
        assert matching, actual.keys()
        for key in set().union(*(set(e) for e in matching)):
            check_shape(actual[key], [e[key] for e in matching if key in e])
    elif isinstance(actual, list):
        pool = [x for e in examples if isinstance(e, list) for x in e]
        for item in actual:
            check_shape(item, pool)
    else:
        assert any(isinstance(actual, type(e)) or isinstance(actual, (int, float)) and isinstance(e, (int, float))
                   for e in examples if e is not None), (actual, examples)


def test_nonempty_status_matches_example_keys_types_and_event_variants(tmp_path):
    root, client = project(tmp_path), Client()
    result = m.run(root, root / 'out', client, NOW, symbols={'BTCUSDT'})
    example = json.loads((ROOT / 'tests/fixtures/ornek_durum.json').read_text())
    check_shape(result, [example])
    assert result['traderlar'][0]['pozisyonlar'][0]['binance'] == 'var'
    assert result['traderlar'][0]['kapi']['sinif'] == 'Yetersiz'
    assert result['traderlar'][0]['gecerli'] is True
    assert result['traderlar'][0]['veri_zamani'] == '2026-10-27T12:00:00Z'
    assert json.loads((root / 'out/durum.json').read_text()) == result


def test_future_t0_does_not_copy_or_create_trade_events(tmp_path):
    root, client = project(tmp_path), Client()
    config = root / 'copytrade/izleme_listesi.yaml'
    config.write_text(config.read_text().replace('2026-10-27', '2026-10-28'))
    result = m.run(root, root / 'out', client, NOW)
    assert result['traderlar'][0]['sanal_kopya']['bakiye_usd'] == 1000
    assert result['traderlar'][0]['sanal_kopya']['egri'] == []
    assert all(e['tur'] == 'isik' for e in result['olaylar'])
    assert client.candle_reads == 0


def git(cwd, *args):
    return subprocess.run(['git', '-C', str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


def test_publication_creates_orphan_and_preserves_worker_decisions(tmp_path):
    remote, checkout = tmp_path / 'remote.git', tmp_path / 'checkout'
    remote.mkdir(); checkout.mkdir()
    git(remote, 'init', '--bare')
    git(checkout, 'init')
    git(checkout, 'config', 'user.name', 'Test')
    git(checkout, 'config', 'user.email', 'test@example.com')
    git(checkout, 'remote', 'add', 'origin', str(remote))
    (checkout / 'source.py').write_text('source must stay off data branch')
    git(checkout, 'add', '.')
    git(checkout, 'commit', '-m', 'source')
    (checkout / 'izleme').mkdir()
    for name in ['motor.json', 'durum.json']:
        (checkout / 'izleme' / name).write_text('{}')
    command = ['bash', str(ROOT / '.github/scripts/izleme_yayimla.sh')]
    subprocess.run(command, cwd=checkout, env={**os.environ, 'GITHUB_ACTIONS': 'true'}, check=True, capture_output=True)
    assert git(checkout, 'rev-list', '--count', 'HEAD') == '1'
    assert not (checkout / 'source.py').exists()
    (checkout / 'izleme/kararlar.jsonl').write_text('{"olay_id":"public-test"}\n')
    git(checkout, 'add', '.')
    git(checkout, 'commit', '-m', 'worker decision')
    git(checkout, 'push', 'origin', 'copytrade-izleme')
    (checkout / 'izleme/durum.json').write_text('{"uretildi":"next"}')
    subprocess.run(command, cwd=checkout, env={**os.environ, 'GITHUB_ACTIONS': 'true'}, check=True, capture_output=True)
    assert (checkout / 'izleme/kararlar.jsonl').read_text() == '{"olay_id":"public-test"}\n'
    assert json.loads((checkout / 'izleme/durum.json').read_text())['uretildi'] == 'next'
    assert git(checkout, 'rev-parse', 'HEAD') == git(remote, 'rev-parse', 'refs/heads/copytrade-izleme')


def test_closing_pre_t0_position_never_opens_inverse_copy():
    inherited_close = fill(side='A', before=5, size=5)
    assert m.copy_actions([inherited_close]) == []
    flip = fill(side='A', before=5, size=7)
    actions = m.copy_actions([flip])
    assert float(actions[0]['sz']) == 2
    assert float(actions[0]['startPosition']) == 0


def test_current_two_trader_list_runs_offline(tmp_path):
    (tmp_path / 'copytrade').mkdir()
    (tmp_path / 'copytrade/izleme_listesi.yaml').write_bytes((ROOT / 'copytrade/izleme_listesi.yaml').read_bytes())
    result = m.run(tmp_path, tmp_path / 'out', Client(), NOW)
    expected = [row['id'] for row in m.load_list(ROOT / 'copytrade/izleme_listesi.yaml')]
    assert [t['id'] for t in result['traderlar']] == expected
    example = json.loads((ROOT / 'tests/fixtures/ornek_durum.json').read_text())
    check_shape(result, [example])
    assert all(t['sanal_kopya']['bakiye_usd'] == 1000 for t in result['traderlar'])


def test_event_feed_is_recent_200_with_stable_archive(tmp_path):
    root, client = project(tmp_path), Client([])
    output = root / 'out'
    output.mkdir()
    events = {str(i): {'id': str(i), 'zaman': m.at_ms(m.millis(NOW) - i * m.MINUTE),
                      'trader': 'retained', 'tur': 'isik'} for i in range(250)}
    (output / 'motor.json').write_text(json.dumps({'surum': 1, 'traderlar': {}, 'olaylar': events}))
    result = m.run(root, output, client, NOW)
    assert len(result['olaylar']) == 200
    assert '249' not in {e['id'] for e in result['olaylar']}
    assert len(json.loads((output / 'motor.json').read_text())['olaylar']) == 250


# ---------------------------------------------------------------- v1.3: tarza göre gecikme
def styled_row(**extra):
    return {'id': 'T1', 'adres': ADDRESS, 'takma_ad': 'Test', 'durum': 'izlemede', 't0': str(T0.date()), **extra}


@pytest.mark.parametrize('style,delay', [('intraday', 30), ('swing', 120)])
def test_style_from_list_sets_delay_and_status_label(tmp_path, style, delay):
    root = project(tmp_path, [styled_row(tarz=style)])
    trader = m.run(root, root / 'out', Client(), NOW)['traderlar'][0]
    assert trader['tarz'] == style and trader['sanal_kopya']['gecikme_dk'] == delay


def test_style_falls_back_to_gate_result_then_unknown_with_30_minutes(tmp_path):
    root = project(tmp_path, [styled_row()])
    unknown = m.run(root, root / 'out', Client(), NOW)['traderlar'][0]
    assert unknown['tarz'] == 'bilinmiyor' and unknown['sanal_kopya']['gecikme_dk'] == 30
    day = root / 'copytrade/kapi/2026-10-27'
    day.mkdir(parents=True)
    (day / 'sonuc.csv').write_text(f'address,sinif,tarz\n{ADDRESS.upper().replace("0X", "0x")},Yetersiz,swing\n')
    (root / 'out/motor.json').unlink(); (root / 'out/durum.json').unlink()
    from_gate = m.run(root, root / 'out', Client(), NOW)['traderlar'][0]
    assert from_gate['tarz'] == 'swing' and from_gate['sanal_kopya']['gecikme_dk'] == 120
    # listedeki tarz kapı sonucundan önceliklidir
    (root / 'out/motor.json').unlink(); (root / 'out/durum.json').unlink()
    config = root / 'copytrade/izleme_listesi.yaml'
    config.write_text(yaml.safe_dump({'traderlar': [styled_row(tarz='intraday')]}))
    assert m.run(root, root / 'out', Client(), NOW)['traderlar'][0]['sanal_kopya']['gecikme_dk'] == 30


@pytest.mark.parametrize('change', [dict(tarz='scalp'), dict(tarz='hızlı'), dict(baska='x')])
def test_invalid_style_or_extra_key_rejected(tmp_path, change):
    root = project(tmp_path, [styled_row(**change)])
    with pytest.raises(ValueError):
        m.load_list(root / 'copytrade/izleme_listesi.yaml')


def test_copy_results_delay_parameter_controls_execution_time():
    """Altın örnek (elle): 1 BTC / 1000 $ hesap, fiyat 100, maliyet %0,095 → bakiye 1000 × (1 − 0,001 × 100 × 0,00095) = 999,905."""
    opening = fill()                                    # 10:00, long 1 BTC
    events = {e['id']: e for e in m.fill_events('T1', [opening], 1000, [])}
    candles = {'BTC': [{'t': m.millis('2026-10-27T10:30:00Z'), 'o': 100}, {'t': m.millis('2026-10-27T12:00:00Z'), 'o': 100}]}
    at = lambda hhmm: m.timestamp(f'2026-10-27T{hhmm}:00Z')
    expected = 1000 * (1 - .001 * 100 * .00095)
    assert m.copy_results([opening], candles, [], 1000, T0, at('10:45'), events, False, 30)['bakiye_usd'] == pytest.approx(expected)
    assert m.copy_results([opening], candles, [], 1000, T0, at('10:45'), events, False, 120)['bakiye_usd'] == 1000   # 12:00'den önce işlem yok
    assert m.copy_results([opening], candles, [], 1000, T0, at('12:00'), events, False, 120)['bakiye_usd'] == pytest.approx(expected)
    assert m.copy_results([opening], candles, [], 1000, T0, at('12:00'), events, False, 120)['gecikme_dk'] == 120


def test_acik_zarar_sonuca_girer_denetim_probu():
    """Altın örnek (denetim probu): 10 BTC, giriş 100, işaret 50 → toplam −%50,095 (açık −%50 + maliyet %0,095). Eski yol −%0,095 gösteriyordu."""
    opening = fill(size=10)
    candles = {'BTC': [{'t': m.millis('2026-10-27T10:30:00Z'), 'o': 100}, {'t': m.millis('2026-10-27T11:59:00Z'), 'o': 50}]}
    result = m.copy_results([opening], candles, [], 1000, T0, NOW, {})
    assert result['gerceklesen'] == pytest.approx(-0.00095)               # maliyet: 1000 × (0,045% + 0,05%) / 1000
    assert result['acik'] == pytest.approx(-0.5)                          # 10 × (50 − 100) / 1000
    assert result['toplam'] == pytest.approx(-0.50095)
    assert result['bakiye_usd'] == pytest.approx(1000 * (1 - 0.50095)) and result['getiri'] == pytest.approx(-0.50095)
    assert result['son_isaret'] == '2026-10-27T11:59:00Z' and result['isaret_eksik'] == 0
    assert result['egri'][-1][1] == pytest.approx(499.05)


def test_kapali_pozisyonda_acik_sifir_gerceklesen_toplam():
    opening, closing = fill(), fill('2026-10-27T11:00:00Z', 2, 'A', 1, 1, 500)
    candles = {'BTC': [{'t': m.millis('2026-10-27T10:30:00Z'), 'o': 100}, {'t': m.millis('2026-10-27T11:30:00Z'), 'o': 110}]}
    result = m.copy_results([opening, closing], candles, [], 1000, T0, NOW, {})
    assert result['acik'] == 0 and result['son_isaret'] is None
    assert result['gerceklesen'] == pytest.approx(result['toplam']) == pytest.approx((10 - 210 * .00095) / 1000)


def test_canli_yol_kanonik_defterle_ayni_sonucu_verir():
    """Sözleşme: canlı ``copy_results`` ile ``defter.copy_ledger`` (aynı dolum, aynı yürütme fiyatı, aynı işaret) toplamda ayrışmaz."""
    from copytrade.defter import Market, copy_ledger
    fills = [fill('2026-10-27T09:00:00Z', 1, 'B', 2, 0, 100), fill('2026-10-27T09:40:00Z', 2, 'B', 1, 2, 104, oid=2),
             fill('2026-10-27T10:30:00Z', 3, 'A', 1.5, 3, 120, oid=3), fill('2026-10-27T10:50:00Z', 4, 'B', 1, 1.5, 90, coin='ETH', oid=4)]
    exec_prices = [100, 104, 120, 90]
    candles = {'BTC': [], 'ETH': []}
    for f, price in zip(fills, exec_prices):
        candles[f['coin']].append({'t': f['time'] + 30 * m.MINUTE, 'o': price})
    candles['BTC'].append({'t': m.millis('2026-10-27T11:58:00Z'), 'o': 130})
    candles['ETH'].append({'t': m.millis('2026-10-27T11:57:00Z'), 'o': 80})
    live = m.copy_results(fills, candles, [], 1000, T0, NOW, {})
    marked = [dict(f, _execution_time=f['time'] + 30 * m.MINUTE, _execution_price=p) for f, p in zip(fills, exec_prices)]
    canonical = copy_ledger(marked, Market(candles), 1000, 30, m.millis(T0), m.millis(NOW))
    assert live['toplam'] == pytest.approx(canonical['net']) and live['acik'] == pytest.approx(canonical['unrealized_end'])
    assert live['gerceklesen'] == pytest.approx(canonical['realized'])
    # elle: BTC 3 → 1,5 kapanır (+1,5 × 20 = 30; ort. giriş (200 + 104) / 3 = 101,333…) ve ETH 1 @90 açık
    assert canonical['unrealized_end'] == pytest.approx((1.5 * (130 - (2 * 100 + 1 * 104) / 3) + 1 * (80 - 90)) / 1000)


def test_canli_kosu_acik_pozisyonu_son_dakika_mumuyla_isaretler(tmp_path):
    """Uçtan uca: yürütme mumu 102, son 1 dk mum 50 → açık K/Z = 1 × (50 − 102) / 1000 = −%5,2; maliyet 102 × 0,095% / 1000."""
    class Falling(Client):
        def candles(self, coin, start, end, interval='1m'):
            if end - start <= 15 * m.MINUTE:
                self.mark_reads += 1
                return [{'t': end - m.MINUTE, 'o': '50'}]
            return super().candles(coin, start, end, interval)
    root, client = project(tmp_path), Falling()
    paper = m.run(root, root / 'out', client, NOW)['traderlar'][0]['sanal_kopya']
    assert paper['acik'] == pytest.approx(-0.052) and paper['gerceklesen'] == pytest.approx(-102 * .00095 / 1000)
    assert paper['toplam'] == pytest.approx(-0.052 - 102 * .00095 / 1000) and paper['son_isaret'] == '2026-10-27T11:59:00Z'
    assert client.mark_reads == 1


def test_health_blind_keeps_leverage_and_staleness():
    h = history([-.05])
    result = m.health(h, h.index[-1], NOW, 10.01, False, m.millis(NOW) - 30 * m.DAY, performans_konisi=False)
    assert result['isik'] == 'kirmizi'
    assert result['nedenler'] == ['gerçek kaldıraç > 10x', 'son 30 günde işlem yok']
