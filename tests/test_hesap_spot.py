"""A2-4: İlk 11 `hesap` alanı İ (kapı) ve F (izleme) için AYNI tanım: ana + HIP-3 + spot USDC (kural 7).

Gerçek veri bulgusu (deneme 41477749941): 0x0cd16f3f İ 14.405 $ ↔ F 4.352 $ — F spot USDC'yi saymıyordu, 5.000 $ altına düşüp `akil_sagligi_ihlali` oluyordu.
Sentetik eşdeğer: perp (ana + HIP-3) 4.352 $, spot USDC 10.053 $ -> toplam 14.405 $ (elle: 4.352 + 10.053).
"""
from __future__ import annotations

import pandas as pd
import pytest

from copytrade import izleme_motoru as m
from copytrade import kapi
from test_izleme import NOW, Client, project

SPOT = [{'coin': 'USDC', 'total': '10053'}, {'coin': 'HYPE', 'total': '500'}]       # USDC dışı bakiye sayılmaz


def calistir(tmp_path, client):
    root = project(tmp_path)
    return m.run(root, root / 'out', client, NOW)['traderlar'][0]


def test_golden_F_hesap_spot_usdc_dahil_ve_kapi_tanimiyla_ayni(tmp_path):
    client = Client()
    client.account, client.spot = 4352, SPOT
    kapi_toplam = kapi.total_account_value(client, 'x', [])                      # İ: kapı tanımı (account_value_parts)
    assert kapi_toplam == 4352 + 10053 == 14405
    t = calistir(tmp_path, client)
    assert t['hesap_degeri'] == 4352                                             # perp hesap değeri (olaylar / hesap payı) değişmedi
    assert t['hesap_degeri_toplam'] == kapi_toplam == 14405
    form = t['ilk11_form_ham']
    assert form['alanlar']['hesap'] == 14405 and form['alan_kaynagi']['hesap'] == 'traderlar.hesap_degeri_toplam'   # 5.000 $ altı ihlal YOK


def test_spot_yoksa_toplam_perpe_esit_ve_kucuk_hesap_hala_aralik_disi(tmp_path):
    t = calistir(tmp_path, Client())                                             # perp 1.000 $, spot yok -> toplam 1.000 $ (< 5.000 $: ihlal, beklenen)
    assert t['hesap_degeri_toplam'] == 1000 and t['ilk11_form_ham']['alan_kaynagi']['hesap'] == 'akil_sagligi_ihlali:1000'


class SpotOkunamaz(Client):
    def info(self, payload, weight=20):
        if payload['type'] == 'spotClearinghouseState':
            raise RuntimeError('spot 429')
        return super().info(payload, weight)


def test_spot_okuma_hatasi_trader_dusurmez_yalniz_hesap_alani_eksik(tmp_path):
    client = SpotOkunamaz()
    client.account = 20000
    t = calistir(tmp_path, client)
    assert t['gecerli'] is True and t['hesap_degeri_toplam'] is None and t['hesap_degeri'] == 20000
    assert t['ilk11_form_ham']['alanlar']['hesap'] is None and t['ilk11_form_ham']['alan_kaynagi']['hesap'] is None   # eksik (35), ihlal değil
    assert 'sanal_kopya_v3' in t and t['sanal_kopya_v3']['bakiye_usd'] > 0


def test_spot_usdc_tek_yerde_account_value_parts_davranisi_degismedi():
    client = Client()
    client.account, client.spot = 6000, [{'coin': 'USDC', 'total': '999'}, {'coin': 'MAX', 'total': '1073320.26'}]
    assert kapi.spot_usdc(client, 'x') == 999.0
    assert kapi.account_value_parts(client, 'x', []) == {'ana': 6000.0, 'hip3': 0.0, 'spot_usdc': 999.0}
    client.spot = []
    assert kapi.spot_usdc(client, 'x') == 0.0
