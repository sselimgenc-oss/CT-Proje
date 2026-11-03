"""İzleme listesi okuma/doğrulama (YAML). pandas/numpy GEREKTİRMEZ: `izleme_motoru` ve sunucudaki dinleyici (`dinleyici.py`, yalnız PyYAML) aynı kodu kullanır (kural 7)."""
from __future__ import annotations

import math
import re
from datetime import datetime
from pathlib import Path

import yaml

STYLES = {'intraday', 'swing'}
KOLLAR = {'oda', 'kontrol', 'taban', 'elle', 'referans_oda', 'referans_kontrol', 'cikarilan', 'havuz'}


def load_list(path: Path) -> list[dict]:
    rows = yaml.safe_load(path.read_text(encoding='utf-8'))
    if isinstance(rows, dict) and set(rows) == {'traderlar'}:
        rows = rows['traderlar']
    if not isinstance(rows, list):
        raise ValueError('İzleme listesi YAML listesi olmalı (boş liste: []).')
    ids, addresses = set(), set()
    for row in rows:
        required = {'id', 'adres', 'takma_ad', 'durum', 't0'}
        optional = {'tarz', 'kol', 'kollar', 'secim', 'cikarilma_tarihi',
                    'takim', 'snapshot_id', 'form_puani', 'takim_hafta'}
        if not isinstance(row, dict) or not required <= set(row) or set(row) - required - optional:
            raise ValueError('İzleme satırında yalnız id, adres, takma_ad, durum, t0 ve tanımlı isteğe bağlı alanlar olmalı.')
        if 'kol' in row and row['kol'] not in KOLLAR:
            raise ValueError('Geçersiz kol.')
        if 'tarz' in row and row['tarz'] not in STYLES:
            raise ValueError('Geçersiz tarz (intraday | swing).')
        if 'takim' in row and row['takim'] not in {'ilk11', 'yedek11', 'paf'}:
            raise ValueError('Geçersiz takım (ilk11 | yedek11 | paf).')
        if 'snapshot_id' in row and (not isinstance(row['snapshot_id'], str) or not re.fullmatch(r'[0-9a-f]{64}', row['snapshot_id'])):
            raise ValueError('Geçersiz snapshot_id.')
        if 'form_puani' in row and (isinstance(row['form_puani'], bool) or not isinstance(row['form_puani'], (int, float)) or not math.isfinite(row['form_puani']) or not 0 <= row['form_puani'] <= 100):
            raise ValueError('Geçersiz form_puani (0..100).')
        if 'takim_hafta' in row and (not isinstance(row['takim_hafta'], str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', row['takim_hafta'])):
            raise ValueError('Geçersiz takim_hafta (YYYY-MM-DD).')
        if not isinstance(row['id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]+', row['id']):
            raise ValueError('Geçersiz trader id.')
        if not isinstance(row['adres'], str) or not re.fullmatch(r'0x[0-9a-fA-F]{40}', row['adres']):
            raise ValueError('Geçersiz halka açık trader adresi.')
        if not isinstance(row['takma_ad'], str) or not row['takma_ad'].strip():
            raise ValueError('Takma ad boş olamaz.')
        if row['durum'] not in {'kopyala', 'izlemede', 'durdu'}:
            raise ValueError('Geçersiz izleme durumu.')
        row['t0'] = str(row['t0'])
        try:
            datetime.fromisoformat(row['t0'])
        except ValueError as error:
            raise ValueError('Geçersiz t0.') from error
        if row['id'] in ids or row['adres'].lower() in addresses:
            raise ValueError('Tekrarlanan trader id/adres.')
        ids.add(row['id']); addresses.add(row['adres'].lower())
    return rows


def perp_dex_names(response: object) -> list[str]:
    """Return every public HIP-3 dex name exactly once, in API order."""
    if not isinstance(response, list):
        raise ValueError('Geçersiz perpDexs yanıtı.')
    names: list[str] = []
    for dex in response:
        if dex is None:
            continue
        if not isinstance(dex, dict) or not isinstance(dex.get('name'), str) or not dex['name']:
            raise ValueError('Geçersiz perpDexs dex adı.')
        if dex['name'] not in names:
            names.append(dex['name'])
    return names
