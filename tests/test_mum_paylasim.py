"""Mum isteği tekilleştirme (hesap DEĞİŞMEZ): sahte API, elle hesaplı istek sayıları."""
from __future__ import annotations

from copytrade.mum_paylasim import MumPaylasimi, SINIR

DK, SA = 60_000, 3_600_000


class Api:
    """Her dakika (veya saat) için mum üretir; t ∈ [başlangıç, bitiş], aralık sınırlarına hizalı t'ler (gerçek API gibi başlangıçtan SONRAKİ ilk sınır)."""
    def __init__(self, mum_yok=()):
        self.cagrilar, self.mum_yok = [], set(mum_yok)

    def candles(self, coin, start, end, interval='1m'):
        self.cagrilar.append((coin, start, end, interval))
        adim = DK if interval == '1m' else SA
        ilk = -(-start // adim) * adim
        return [{'t': t, 'o': str(100 + (t // adim) % 7)} for t in range(ilk, end + 1, adim) if (coin, t) not in self.mum_yok][:SINIR]

    def info(self, payload, weight=20):
        return 'info-aynen'


def test_ayni_istek_ikinci_kez_api_ye_gitmez_ve_ayni_sonuc():
    api, p = Api(), MumPaylasimi(Api())
    a = api.candles('BTC', 600 * DK, 700 * DK)
    ilk, ikinci = p.candles('BTC', 600 * DK, 700 * DK), p.candles('BTC', 600 * DK, 700 * DK)
    assert ilk == a == ikinci and len(p._istemci.cagrilar) == 1 and p.istek == 1 and p.paylasilan == 1


def test_hizali_alt_aralik_kapsayan_tam_yanittan_suzulur_api_ile_ayni():
    """Elle: [600dk, 700dk] yanıtı 101 mum; [650dk, 660dk] hizalı alt aralık -> 11 mum (650..660 dahil), API çağrısı eklenmez ve doğrudan API cevabıyla birebir."""
    p = MumPaylasimi(Api())
    p.candles('BTC', 600 * DK, 700 * DK)
    alt = p.candles('BTC', 650 * DK, 660 * DK)
    assert len(alt) == 11 and alt == Api().candles('BTC', 650 * DK, 660 * DK) and p.istek == 1 and p.paylasilan == 1


def test_hizasiz_baslangic_bos_sonuc_api_ye_sorulur_dolu_sonuc_paylasilir():
    """Isaretleme penceresi (şimdi − 15 dk, hizasız): süzme BOŞSA API'ye sorulur (sunucu başlangıcı içeren mumu döndürebilir); doluysa paylaşılır."""
    api = Api(mum_yok={('BTC', t) for t in range(690 * DK, 701 * DK, DK)})      # 690..700 dk arasında mum yok (likit olmayan coin)
    p = MumPaylasimi(api)
    p.candles('BTC', 600 * DK, 700 * DK)
    dolu = p.candles('BTC', 685 * DK + 17, 700 * DK)                              # 686..689 dk mumları var -> paylaşılır
    assert [c['t'] for c in dolu] == [686 * DK, 687 * DK, 688 * DK, 689 * DK] and p.istek == 1
    bos = p.candles('BTC', 692 * DK + 17, 700 * DK)                               # süzme boş -> API'ye gider
    assert bos == [] and p.istek == 2


def test_kesilmis_yanit_5000_mum_yeniden_kullanilmaz_ve_farkli_coin_aralik_ayri():
    p = MumPaylasimi(Api())
    p.candles('BTC', 0, (SINIR + 10) * DK)                                        # 5.000'e kesilir (SINIR) -> tam sayılmaz
    p.candles('BTC', 100 * DK, 200 * DK)
    assert p.istek == 2 and p.paylasilan == 0
    p.candles('ETH', 0, 100 * DK)
    p.candles('ETH', 0, 100 * SA, interval='1h')
    assert p.istek == 4 and p.paylasilan == 0                                     # farklı coin ve farklı aralık (1m / 1h) karışmaz


def test_diger_cagrilar_aynen_iletilir():
    assert MumPaylasimi(Api()).info({'type': 'meta'}) == 'info-aynen'


def test_iki_trader_ayni_coin_ayni_dolum_api_istegi_yarilanir_sonuc_ayni(tmp_path):
    """Uçtan uca (run): aynı dolumlarla iki trader. Paylaşımsız mum isteği 4 olurdu (trader başına yürütme + tasfiye); şimdi 2 (ikinci trader aynı pencereleri paylaşır). İki traderın v1 ve v3 sonucu tek-trader koşusuyla birebir."""
    from copytrade import izleme_motoru as m
    from test_izleme import ADDRESS, NOW, T0, Client, project
    (tmp_path / 'tek').mkdir()
    (tmp_path / 'iki').mkdir()
    tek = project(tmp_path / 'tek')
    c1 = Client()
    sonuc1 = m.run(tek, tek / 'out', c1, NOW)['traderlar'][0]
    iki = project(tmp_path / 'iki', rows=[{'id': 'T1', 'adres': ADDRESS, 'takma_ad': 'A', 'durum': 'izlemede', 't0': str(T0.date())},
                                          {'id': 'T2', 'adres': '0x' + '2' * 40, 'takma_ad': 'B', 'durum': 'izlemede', 't0': str(T0.date())}])
    c2 = Client()
    sonuc2 = m.run(iki, iki / 'out', c2, NOW)['traderlar']
    assert c1.candle_reads == 2 and c2.candle_reads == 2 and c2.mark_reads == 0          # tek traderda yürütme 1 + tasfiye (1 sa) 1 = 2; iki traderda paylaşımsız 4 olurdu; işaret yürütme yanıtından
    for t in sonuc2:
        assert t['sanal_kopya'] == sonuc1['sanal_kopya'] and t['sanal_kopya_v3'] == sonuc1['sanal_kopya_v3']
