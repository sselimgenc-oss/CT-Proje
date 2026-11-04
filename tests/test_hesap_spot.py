"""A2-4: izleme `hesap_degeri_toplam` tanımı: ana + HIP-3 + spot USDC (kural 7; `hl_ortak.spot_usdc` tek yer).

Gerçek veri bulgusu (deneme 41477749941): 0x0cd16f3f İ 14.405 $ ↔ F 4.352 $ — F spot USDC'yi saymıyordu, 5.000 $ altına düşüp `akil_sagligi_ihlali` oluyordu.
Sentetik eşdeğer: perp (ana + HIP-3) 4.352 $, spot USDC 10.053 $ -> toplam 14.405 $ (elle: 4.352 + 10.053).
"""
from __future__ import annotations

import pandas as pd
import pytest

from copytrade import izleme_motoru as m
from copytrade import hl_ortak
from test_izleme import NOW, Client, project

SPOT = [{'coin': 'USDC', 'total': '10053'}, {'coin': 'HYPE', 'total': '500'}]       # USDC dışı bakiye sayılmaz


def calistir(tmp_path, client):
    root = project(tmp_path)
    return m.run(root, root / 'out', client, NOW)['traderlar'][0]


def test_golden_hesap_toplam_spot_usdc_dahil(tmp_path):
    client = Client()
    client.account, client.spot = 4352, SPOT
    beklenen = 4352 + hl_ortak.spot_usdc(client, 'x')                            # elle: 4.352 + 10.053
    assert beklenen == 14405
    t = calistir(tmp_path, client)
    assert t['hesap_degeri'] == 4352                                             # perp hesap değeri (olaylar / hesap payı) değişmedi
    assert t['hesap_degeri_toplam'] == beklenen == 14405


def test_spot_yoksa_toplam_perpe_esit(tmp_path):
    t = calistir(tmp_path, Client())                                             # perp 1.000 $, spot yok -> toplam 1.000 $
    assert t['hesap_degeri_toplam'] == 1000


class SpotOkunamaz(Client):
    def info(self, payload, weight=20):
        if payload['type'] == 'spotClearinghouseState':
            raise RuntimeError('spot 429')
        return super().info(payload, weight)


def test_spot_okuma_hatasi_trader_dusurmez_yalniz_toplam_eksik(tmp_path):
    client = SpotOkunamaz()
    client.account = 20000
    t = calistir(tmp_path, client)
    assert t['gecerli'] is True and t['hesap_degeri_toplam'] is None and t['hesap_degeri'] == 20000
    assert 'sanal_kopya_v3' in t and t['sanal_kopya_v3']['bakiye_usd'] > 0


def test_spot_usdc_yalniz_usdc_sayar():
    client = Client()
    client.account, client.spot = 6000, [{'coin': 'USDC', 'total': '999'}, {'coin': 'MAX', 'total': '1073320.26'}]
    assert hl_ortak.spot_usdc(client, 'x') == 999.0
    client.spot = []
    assert hl_ortak.spot_usdc(client, 'x') == 0.0
