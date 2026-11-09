

from copytrade.izleme_motoru import mutabakat_raporu, timestamp


def addr(char):
    return '0x' + char * 40














def test_yetim_pozisyon_hesap_sicramasindan_once_gelir():
    now = timestamp('2026-10-29T00:00:00Z')
    fill = {'coin': 'BTC', 'time': 1, 'side': 'B', 'sz': '1', 'startPosition': '0'}
    report = mutabakat_raporu([fill], [{'assetPositions': []}], now, onceki_hesap_degeri=100.0, hesap_degeri=200.0)
    assert report['saglik']['isik'] == 'kirmizi'


def test_mutabakat_saglik_isigi_altin_ornekleri():
    now = timestamp('2026-10-29T00:00:00Z')
    fill = {'coin': 'BTC', 'time': 1, 'side': 'B', 'sz': '1', 'startPosition': '0'}
    green = mutabakat_raporu([fill], [{'assetPositions': [{'position': {'coin': 'BTC', 'szi': '1'}}]}], now)
    red = mutabakat_raporu([fill], [{'assetPositions': []}], now)
    yellow = mutabakat_raporu([], [{'assetPositions': ['bozuk']}], now)
    assert (green['saglik'], red['saglik'], yellow['saglik']) == (
        {'isik': 'yesil', 'neden': 'mutabakat uyumlu'}, {'isik': 'kirmizi', 'neden': 'yetim pozisyon'}, {'isik': 'sari', 'neden': 'bozuk mutabakat satırı'})
