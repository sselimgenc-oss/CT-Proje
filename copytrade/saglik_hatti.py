
"""Veri hattı sağlığı için saf ölçü ve eşik fonksiyonları.

Mevcut durum.json alanları (mutabakat, işaret eksikliği, veri geçerliliği, performans ışığı) kol düzeyinde
(varsayılan "oda") tek kayda toplanır; hiçbir yeni ölçüm hesaplamaz, hiçbir pozisyonu/kopyayı etkilemez —
yalnız rapor. ``olc()`` saf ölçü fonksiyonu, ``kontrol()`` saf eşik fonksiyonudur.

**Kasıtlı olarak İÇERMEZ:** veri tazeliği/bayatlık kontrolü. Bu modül `durum.json` içindeki (geçmişte üretilmiş)
alanları okur; yayım anında hesaplanan bir "şu an"a göre tazelik burada her zaman ~0 döner ve durmuş bir akışı
anında kendi gerçek saatiyle yaptığı mevcut kontrolündedir (`worker/src/index.js` `checkStateAlerts`, 3 saatlik
eşik) — tek yerde (AGENTS.md kural 7), tekrarlanmaz.
"""

from __future__ import annotations

import pandas as pd

ODA_KOLU = 'oda'

ESIKLER = {
    'yetim_golge_orani_kirmizi': 0.10,
    'veri_hata_orani_kirmizi': 0.20,
    'veri_hata_orani_sari': 0.10,
    'isaret_eksik_toplam_sari': 3,
}

# Bir pozisyonun açılışı `uretildi`den bu kadar eskiyse "yakın zamanda açılmış" sayılmaz (yaş ölçüsüne girmez).
POZISYON_YASI_TAVAN_DK = 180.0


def _kol_uyeleri(traderlar: list[dict], kol: str) -> list[dict]:
    return [t for t in traderlar if kol in (t.get('kollar') or [t.get('kol')])]


def _dakika(onceki, sonraki) -> float | None:
    try:
        fark = (pd.Timestamp(sonraki) - pd.Timestamp(onceki)).total_seconds() / 60.0
    except (ValueError, TypeError):
        return None
    return fark if fark >= 0 else None


def olc(durum: dict, kol: str = ODA_KOLU) -> dict:
    """Tek kol için sağlık ölçüsü. ``durum``: ``docs/VERI_SOZLESMESI.md`` şemasındaki üst düzey sözlük.

    ``acik_pozisyon_yasi_dk_medyan``: son `POZISYON_YASI_TAVAN_DK` dakika içinde açılmış kol pozisyonlarının
    `uretildi`ye göre medyan yaşı (dk). Bu **pozisyon yaşıdır, gerçek sinyal/algılama gecikmesi değildir** —
    trader'ın gerçek işlem zamanı ile Worker'ın onu ne zaman gördüğü arasındaki fark ayrıca ölçülmeli (henüz yok).
    """
    uyeler = _kol_uyeleri(durum.get('traderlar') or [], kol)
    n = len(uyeler)
    if n == 0:
        return {
            'kol': kol, 'n': 0, 'yetim_golge_orani': None,
            'isaret_eksik_toplam': 0, 'veri_hata_orani': None, 'kirmizi_sayisi': 0, 'sari_sayisi': 0,
            'acik_pozisyon_yasi_dk_medyan': None,
        }

    uretildi = durum.get('uretildi')

    yetim_toplam = sum(int((t.get('veri_kalitesi') or {}).get('mutabakat', {}).get('yetim') or 0) for t in uyeler)
    mutabakat_satir_toplam = sum(int((t.get('veri_kalitesi') or {}).get('mutabakat', {}).get('toplam') or 0) for t in uyeler)
    yetim_golge_orani = (yetim_toplam / mutabakat_satir_toplam) if mutabakat_satir_toplam else None

    isaret_eksik_toplam = sum(int((t.get('sanal_kopya') or {}).get('isaret_eksik') or 0) for t in uyeler)
    hata_sayisi = sum(1 for t in uyeler if t.get('gecerli') is False)
    veri_hata_orani = hata_sayisi / n

    kirmizi_sayisi = sum(1 for t in uyeler if (t.get('saglik') or {}).get('isik') == 'kirmizi')
    sari_sayisi = sum(1 for t in uyeler if (t.get('saglik') or {}).get('isik') == 'sari')

    yaslar: list[float] = []
    if uretildi:
        for t in uyeler:
            for p in (t.get('pozisyonlar') or []):
                acilis = p.get('acilis')
                if not acilis:
                    continue
                yas = _dakika(acilis, uretildi)
                if yas is not None and yas <= POZISYON_YASI_TAVAN_DK:
                    yaslar.append(yas)
    acik_pozisyon_yasi_dk_medyan = float(pd.Series(yaslar, dtype='float64').median()) if yaslar else None

    return {
        'kol': kol, 'n': n,
        'yetim_golge_orani': yetim_golge_orani,
        'isaret_eksik_toplam': isaret_eksik_toplam,
        'veri_hata_orani': veri_hata_orani,
        'kirmizi_sayisi': kirmizi_sayisi,
        'sari_sayisi': sari_sayisi,
        'acik_pozisyon_yasi_dk_medyan': acik_pozisyon_yasi_dk_medyan,
    }


def kontrol(olcu: dict, esikler: dict | None = None) -> dict:
    """Saf fonksiyon: ölçüden ışık + neden listesi üretir (kırmızı nedenler sarıdan önce).

    Veri tazeliğini **kasıtlı olarak değerlendirmez** — bkz. modül docstring'i; Worker'ın kendi tazelik
    alarmıyla birleştirilmeli, bu ışığın yerine geçmemeli.
    """
    e = {**ESIKLER, **(esikler or {})}

    if olcu['n'] == 0:
        return {'isik': 'sari', 'nedenler': ['kol boş']}

    kirmizi: list[str] = []
    sari: list[str] = []

    yetim = olcu['yetim_golge_orani']
    if yetim is not None and yetim >= e['yetim_golge_orani_kirmizi']:
        kirmizi.append(f"yetim gölge payı %{yetim * 100:.0f}")

    hata = olcu['veri_hata_orani']
    if hata is not None and hata >= e['veri_hata_orani_kirmizi']:
        kirmizi.append(f"veri hatası payı %{hata * 100:.0f}")
    elif hata is not None and hata >= e['veri_hata_orani_sari']:
        sari.append(f"veri hatası payı %{hata * 100:.0f}")

    if olcu['isaret_eksik_toplam'] >= e['isaret_eksik_toplam_sari']:
        sari.append(f"işaret eksik: {olcu['isaret_eksik_toplam']}")

    isik = 'kirmizi' if kirmizi else 'sari' if sari else 'yesil'
    return {'isik': isik, 'nedenler': kirmizi + sari}
