"""Worker'ın GET /gecikme'de ölçtüğü gerçek algılama gecikmesini okur, oda genelinde özet üretir ve

Bu, ``copytrade/saglik_hatti.py``'deki ``acik_pozisyon_yasi_dk_medyan``'dan ayrıdır: burada ölçülen, trader'ın
gerçek Hyperliquid dolum zamanı ile Worker'ın onu görmesi arasındaki **gerçek** süre (Worker dakikalık çalıştığı
için aynı mantıkla `copytrade/kararlar.py`'nin izlediği "Worker'dan açık veriye aktar" desenini izler).

Worker, D1 yazma kotası için trader başına yalnız **en son** gecikme örneğini tutar (`son_gecikme`); uzun süre
işlem yapmayan bir trader'ın eski örneği D1'de kalıcı olarak durur. İkinci denetimin bulduğu gibi, bunu filtresiz
oda medyanına katmak yanıltıcıdır (eski bir örnek "güncel hız" gibi görünür) — ``ozet()`` bu yüzden ``pencere_dk``
içinde kalan (yakın zamanda güncellenmiş) örnekleri ayırır; eski örnekler ``n_toplam``'a girer ama medyana girmez.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd

# Worker dakikalık çalışıyor; bir saatlik izleme turunda güncellenmemiş örnek "taze" sayılmaz.
PENCERE_DK_VARSAYILAN = 120.0


def ozet(rows: list[dict], simdi: str | None = None, pencere_dk: float = PENCERE_DK_VARSAYILAN) -> dict:
    """Saf fonksiyon: Worker'dan gelen ``{trader, gecikme_dk, zaman}`` satırlarından oda genelinde özet üretir.

    ``zaman`` (örneğin Worker'ın o gecikmeyi kaydettiği an) ``simdi``'den ``pencere_dk`` dakikadan daha eskiyse
    örnek sayılır (``n_toplam``) ama medyan/maks'a girmez — eski, artık güncellenmeyen bir trader'ın tek
    örneğinin oda genelindeki "gerçek algılama hızı" ölçüsünü bozmaması için.
    """
    simdi_ts = pd.Timestamp(simdi) if simdi else pd.Timestamp.now(tz='UTC')
    n_toplam = len(rows)
    taze: list[float] = []
    for row in rows:
        deger = row.get('gecikme_dk')
        zaman = row.get('zaman')
        if deger is None or not zaman:
            continue
        try:
            yas_dk = (simdi_ts - pd.Timestamp(zaman)).total_seconds() / 60.0
        except (ValueError, TypeError):
            continue
        if 0 <= yas_dk <= pencere_dk:
            taze.append(float(deger))
    if not taze:
        return {'n': 0, 'n_toplam': n_toplam, 'gecikme_dk_medyan': None, 'gecikme_dk_maks': None}
    return {
        'n': len(taze),
        'n_toplam': n_toplam,
        'gecikme_dk_medyan': float(pd.Series(taze).median()),
        'gecikme_dk_maks': float(max(taze)),
    }


def fetch(url: str) -> list[dict]:
    # Cloudflare varsayılan Python-urllib kimliğini 403 ile reddediyor; açık bir User-Agent gerekir.
    request = Request(url, headers={'User-Agent': 'sg-arge-izleme/1.0', 'Accept': 'application/json'})
    with urlopen(request, timeout=20) as response:  # nosec B310: URL is a reviewed GitHub variable.
        data = json.load(response)
    if not isinstance(data, list):
        raise ValueError('Worker gecikme yanıtı liste olmalı.')
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    rows = fetch(args.url)
    simdi = datetime.now(UTC).isoformat()
    result = {**ozet(rows, simdi), 'uretildi': simdi, 'trader_detay': rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
