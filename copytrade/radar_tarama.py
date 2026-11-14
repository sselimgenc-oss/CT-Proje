"""Radar taraması: R0 evren + R1 kopyalanabilirlik (docs/RADAR_V1.md §2–3, görev T2). Salt okunur: yalnız herkese açık Hyperliquid verisi.

Akış: lider tablosu → `evren` (R0, hafta getirisine göre ilk N; K‑31) → vault süzgeci → her aday için son 7 günün dolumları → `islem_olculeri` + kopya oynatma
(`kopya_v4.hesapla`, 1 dk gecikme + maliyet, pencere başında BOŞ) → `degerlendir` (R1 kuralları sırayla) → `radar/<tarih>/havuz.json`.

Kural 7 (tek yer): HL istekleri yalnız `tarama.PublicClient`; işlem eşleme `olcut.closed_round_trips`, kaldıraç `olcut.effective_leverage_detail`;
kopya oynatma `kopya_v4.hesapla`; yürütme/işaret mumları `izleme_motoru.execution_candles` / `mark_candles` / `copy_actions`; maliyet `kurallar.yaml`.

Birimler (docs/VERI_SOZLESMESI.md "Radar havuzu (R0/R1)"): oranlar kesirdir (0,10 = %10); `*_usd` trader hesabı ölçeğidir (`trader_$`) ya da — kopya alanlarında —
1.000 $ sanal kopya kasası ölçeğidir (`kopya_$`); zaman UTC ms; süre saat, gecikme dakika.

B8 (08.11 seçim denetimi): kopya oynatmasında trader hesap paydası ZAMANA BAĞLI (`payda_oku`: `portfolio` accountValueHistory; emir anındaki son değer; okunamazsa sabit `hesap_usd`).
`--payda-yan-yana`: eski sabit paydalı sayılar `*_eski` alanlarında (kural 6). `max_kaldirac` (R1/4) paydası değişmedi (koşu anı `hesap_usd`; R‑3 ayrı iş).

    python -m copytrade.radar_tarama --cikti radar --aday-sayisi 20
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

from copytrade import izleme_motoru as im
from copytrade import kopya_v2, kopya_v3, kopya_v4, kopya_v5, radar_form
from copytrade.defter import HOUR
from copytrade.izleme_liste import perp_dex_names
from copytrade.kurallar import load_rules
from copytrade.olcut import closed_round_trips, effective_leverage_detail, is_hip3, perp_fills
from copytrade.tarama import KAPI_YENIDEN_BEKLEME, PublicClient, RateLimiter, RateLimitError, _address, _window

MINUTE = 60_000
SEMA = "radar-havuz-v1"
KOPYA_TARZ = "intraday"                 # kopya_v3 çıkış kuralları (E3) için tarz; radar henüz tarz sınıflamaz (kurallar.yaml golge_v2.intraday)
NEDENLER = ("veri_hatasi", "payda_yok", "devir_yuksek", "vault", "dolum_fazla", "islem_az", "tutma_kisa", "kisa_islem_fazla", "kaldirac_yuksek",
            "likidite_dusuk", "kopya_zarar", "kopya_koruma_dusuk", "kopya_islem_az", "sans_riski", "akil_sagligi", "zaman_yok")        # ucuzdan pahalıya ölçüm sırası (lider kararı 2026-11-04)
DOLUM_KURALI = 5                  # NEDENLER içinde dolum tabanlı kurallar (islem_az … likidite_dusuk): bunlardan biri başarısızsa kopya oynatılmaz
SAYISAL = ("hesap_usd", "hafta_pnl_usd", "ay_pnl_usd", "trader_getiri_7g", "islem_sayisi", "medyan_tutma_saat", "kisa_islem_payi", "max_kaldirac", "likit_pay",
           "kopya_getiri_7g", "ayna_getiri_7g", "kopya_koruma", "devir_hafta", "kopya_alt20", "fiyatsiz_eylem", "yaklasik_fiyat_eylem", "v4_kopya_getiri_7g", "v5_onceki_kopya_getiri_7g",
           "kopya_kazanc_gun_orani", "kopya_dusus", "yayilma", "kopya_getiri_72s", "hype_payi",
           "net_yatirma_usd", "yatirma_payi",        # `kopya_kazanc_gun_orani` … `hype_payi` yalnız `gecti` satırlarında (R2 girdisi); son ikisi T6 §2 (bilgi; kapıyı değiştirmez)
           "payda_nokta", "payda_bas_usd", "payda_son_oran",                          # B8 (bilgi): zamana bağlı payda serisi
           "kopya_islem_sayisi", "yuvarlanan_pay", "oransal_ayna", "koruma_boyut",    # B3/B12 (bilgi; kapıyı değiştirmez)
           "g_t_istat",                                                               # B14 (bilgi; `sans_riski` kapısı `kopya_alt20`'dedir)
           "kopya_getiri_7g_eski", "ayna_getiri_7g_eski", "kopya_koruma_eski", "kopya_alt20_eski")       # B8 yan yana (yalnız `--payda-yan-yana`): sabit payda ile eski sayılar
ESKI_ALANLAR = ("kopya_getiri_7g", "ayna_getiri_7g", "kopya_koruma", "kopya_alt20")     # `--payda-yan-yana`: bu alanlar sabit paydayla da hesaplanıp `_eski` ekiyle yazılır
PAYDA_DONEMLERI = ("week", "month", "allTime")       # portfolio dönemleri, inceden kabaya (tüm hesap; `perp*` dönemleri yalnız perp olduğundan kullanılmaz)
HATALAR = (RateLimitError, requests.RequestException, ValueError, KeyError, TypeError)


# ------------------------------------------------------------------------------------------------------------------------------ R0
def _sayi(deger: Any) -> float | None:
    try:
        sayi = float(deger)
    except (TypeError, ValueError):
        return None
    return sayi if math.isfinite(sayi) else None


def ay_pnl(satir: dict) -> float | None:
    """Lider tablosu satırının 30 günlük (`month`) pnl'i ($); pencere satırda HİÇ yoksa None (kapı uygulanmaz, ölçülemez ≠ başarısız)."""
    for item in satir.get("windowPerformances", []) or []:
        pencere, degerler = (item if isinstance(item, (list, tuple)) and len(item) == 2 else (item.get("window") if isinstance(item, dict) else None, item))
        if isinstance(degerler, dict) and str(pencere).lower() in ("month", "30d"):
            return _sayi(degerler.get("pnl"))
    for k, v in satir.items():
        if str(k).lower().replace("_", "") in ("monthpnl", "30dpnl"):
            return _sayi(v)
    return None


def ay_kapisi(satir: dict, rules: dict) -> bool:
    """v1.1 (K-53) S1: `radar_ay_pnl_pozitif` açıksa 30 günlük pnl > 0 gerekir (tek haftada parlayanı ayıklar); pencere yoksa geçer. Kapalıysa her zaman geçer."""
    if not bool(rules.get("radar_ay_pnl_pozitif", False)):
        return True
    a = ay_pnl(satir)
    return a is None or a > 0


def evren(satirlar: list[dict], rules: dict | None = None, aday_tavan: int | None = None) -> tuple[list[dict], int, int]:
    """R0 (K‑31): lider tablosu satırlarından aday listesi. Ön filtre: hafta başı sermaye `accountValue − hafta pnl ≥ radar_min_hesap_usd` (trader_$; yatırma şişirmesini önler),
    hafta `pnl > 0`, hafta `vlm > 0`; sıra `trader_getiri_7g` (= pnl / (accountValue − pnl)) AZALAN (eşitlikte adres), ilk `aday_tavan` (varsayılan `radar_aday_tavan`) alınır.
    Eksik / sayı olmayan alanlı satır evrene girmez. Döner: (adaylar, evren_toplam = ön filtreyi geçen kişi, evren_kesilen = tavan nedeniyle dışarıda kalan)."""
    rules = rules or load_rules()
    tavan = int(rules["radar_aday_tavan"] if aday_tavan is None else aday_tavan)
    esik = float(rules["radar_min_hesap_usd"])
    gecenler = []
    for satir in satirlar:
        adres = _address(satir)
        hesap = _sayi(satir.get("accountValue", satir.get("account_value")))
        pnl, vlm = _sayi(_window(satir, "week", "pnl")), _sayi(_window(satir, "week", "vlm"))
        if adres and hesap is not None and pnl is not None and vlm is not None and hesap - pnl >= esik and pnl > 0 and vlm > 0 and ay_kapisi(satir, rules):
            gecenler.append({"adres": adres, "hesap_usd": hesap, "hafta_pnl_usd": pnl, "hafta_vlm_usd": vlm, "ay_pnl_usd": ay_pnl(satir)})
    gecenler.sort(key=lambda a: (-(a["hafta_pnl_usd"] / (a["hesap_usd"] - a["hafta_pnl_usd"])), a["adres"]))
    return gecenler[:tavan], len(gecenler), max(0, len(gecenler) - tavan)


def tutma_adaylari(satirlar: list[dict], onceki_adresler: list[str], secilen: set[str], rules: dict | None = None) -> list[dict]:
    """v1.1 (K-53, kullanıcı kararı 09.11) nedene bağlı çıkış: önceki kadronun bugün R0 ilk `radar_aday_tavan` DIŞINDA kalan üyeleri de R1'den geçirilir; geçen kadroda kalır,
    yalnız gerçekten kötüleşen (R1'den kalan) düşer. `radar_tutma_onceki_kadro` false → []. Lider tablosunda olmayan ya da hafta başı sermayesi `radar_min_hesap_usd` altında /
    hafta hacmi 0 olan adres alınmaz (ölçülemez → eskisi gibi kadro dışı). Hafta pnl > 0 şartı ARANMAZ (sonuç R1 kopya oynatmasıyla belli olur); 30 g pnl > 0 (S1, `ay_kapisi`) ARANIR.
    Sıra = `onceki_adresler` sırası."""
    rules = rules or load_rules()
    if not bool(rules.get("radar_tutma_onceki_kadro", False)):
        return []
    esik = float(rules["radar_min_hesap_usd"])
    tablo: dict[str, dict] = {}
    for satir in satirlar:
        adres = _address(satir)
        hesap = _sayi(satir.get("accountValue", satir.get("account_value")))
        pnl, vlm = _sayi(_window(satir, "week", "pnl")), _sayi(_window(satir, "week", "vlm"))
        if adres and hesap is not None and pnl is not None and vlm is not None and hesap - pnl >= esik and vlm > 0 and ay_kapisi(satir, rules):
            tablo[adres.lower()] = {"adres": adres, "hesap_usd": hesap, "hafta_pnl_usd": pnl, "hafta_vlm_usd": vlm, "ay_pnl_usd": ay_pnl(satir), "tutma": True}
    cikti, gorulen = [], {x.lower() for x in secilen}
    for a in onceki_adresler:
        a = str(a).lower()
        if a in tablo and a not in gorulen:
            cikti.append(tablo[a])
            gorulen.add(a)
    return cikti


# ------------------------------------------------------------------------------------------------------------------------------ B8: zamana bağlı trader hesap paydası
def payda_noktalari(portfolio: Any, bit_ms: int) -> list[tuple[int, float]]:
    """Hyperliquid `portfolio` yanıtından (`[[dönem, {accountValueHistory: [[ms, "değer"], …], …}], …]`) trader hesap değeri noktaları (UTC ms, trader_$), `bit_ms`'e kadar (dahil).
    İnce dönem önce: `week` noktalarının tamamı; `month` yalnız alınmış en eski noktadan ÖNCEKİler; `allTime` yalnız ondan da öncekiler (pencere başı haftadan eskiyse — isabet — kaba değer).
    Değeri sayı olmayan / ≤ 0 nokta atılır. Biçim tanınmazsa boş liste."""
    try:
        donemler = dict(portfolio or [])
    except (TypeError, ValueError):
        return []
    noktalar: list[tuple[int, float]] = []
    for donem in PAYDA_DONEMLERI:
        sinir = min((t for t, _ in noktalar), default=None)        # şimdiye kadar alınan en eski nokta
        for nokta in (donemler.get(donem) or {}).get("accountValueHistory") or []:
            try:
                t, v = int(nokta[0]), _sayi(nokta[1])
            except (TypeError, ValueError, IndexError):
                continue
            if v is not None and v > 0 and t <= bit_ms and (sinir is None or t < sinir):
                noktalar.append((t, v))
    return sorted(noktalar)


def payda_oku(client: Any, adres: str, hesap_usd: float, bas_ms: int, bit_ms: int, rules: dict) -> tuple[Any, dict]:
    """B8 (08.11 seçim denetimi): kopya oynatmasının trader hesap paydası. `radar_payda_zaman` true → `portfolio` hesap değeri geçmişinden `kopya_v5.PaydaSerisi` (her emir yürütme
    anındaki, o ana kadarki son değere oranlanır; canlı motor da o anki hesap değerini kullanır). Okunamazsa / seri boşsa / istemci `portfolio` sunmuyorsa SABİT `hesap_usd`'ye düşer.
    Döner (payda, bilgi): bilgi = {`payda_kaynak`: "portfolio" | "sabit" (kural kapalı) | "sabit_yedek" (okunamadı), `payda_nokta` (seri nokta sayısı), `payda_bas_usd` (pencere başındaki değer, trader_$),
    `payda_son_oran` (bit_ms'deki seri değeri / `hesap_usd`; lider tablosu ile portfolio tanımlarının akıl sağlığı kontrolü, ≈ 1 beklenir)}. Okuma hatası satırı `veri_hatasi` YAPMAZ."""
    bos = {"payda_kaynak": "sabit", "payda_nokta": None, "payda_bas_usd": None, "payda_son_oran": None}
    if not bool(rules.get("radar_payda_zaman", True)):
        return hesap_usd, bos
    oku = getattr(client, "portfolio", None)
    try:
        if oku is None:
            raise ValueError("istemci portfolio sunmuyor")
        seri = kopya_v5.PaydaSerisi(payda_noktalari(oku(adres), bit_ms))
    except (*HATALAR, AttributeError):
        return hesap_usd, {**bos, "payda_kaynak": "sabit_yedek"}
    return seri, {"payda_kaynak": "portfolio", "payda_nokta": len(seri), "payda_bas_usd": seri(bas_ms),
                  "payda_son_oran": seri(bit_ms) / hesap_usd if hesap_usd > 0 else None}


def yuvarlanan_pay(kayit: list) -> float | None:
    """B3 (bilgi): kopya açılışlarının (`ac` kararı, emir > 0) `radar_min_emir_usd`'ye YUKARI yuvarlananların (`min_emir_yuvarlandi`) payı; açılış yoksa None. `kayit` = `kopya_v5.boyutlayici` karar listesi."""
    acilis = [k for k in kayit if k[0] == "ac" and k[2] > 0]
    return sum(1 for k in acilis if k[1] == "min_emir_yuvarlandi") / len(acilis) if acilis else None


# ------------------------------------------------------------------------------------------------------------------------------ R1 ölçüleri
def trader_getiri_7g(hesap_usd: float, hafta_pnl_usd: float) -> float | None:
    """Trader'ın son 7 gün getirisi (oran) = hafta pnl / (hesap − hafta pnl). Yatırma/çekme pnl'i etkilemez. Payda ≤ 0 → None (`payda_yok`)."""
    payda = hesap_usd - hafta_pnl_usd
    return None if payda <= 0 else hafta_pnl_usd / payda


def bootstrap_alt(getiriler: list[float], tekrar: int, yuzdelik: float, tohum: int) -> float | None:
    """Kopya işlem getirilerinden (oran, kopya_$ kasasına göre) `tekrar` yeniden örnekleme (yerine koymalı, n kadar); her örneğin TOPLAMININ `yuzdelik` alt yüzdeliği.
    Sabit tohum: aynı girdi aynı sonuç. İşlem yoksa None."""
    if not getiriler:
        return None
    dizi = np.asarray(getiriler, dtype=float)
    secim = np.random.default_rng(tohum).integers(0, len(dizi), size=(int(tekrar), len(dizi)))
    return float(np.quantile(dizi[secim].sum(axis=1), float(yuzdelik)))


def t_istat(getiriler: list[float]) -> float | None:
    """B14 (bilgi): `bootstrap_alt`'a giren AYNI işlem başı getiri dizisinin t istatistiği = ortalama / (s / √n); s örneklem std (n − 1). n < 2 ya da s = 0 → None. Birimsiz."""
    if len(getiriler) < 2:
        return None
    s = statistics.stdev(getiriler)
    return None if s == 0 else statistics.fmean(getiriler) / (s / math.sqrt(len(getiriler)))


def adres_tohumu(adres: str) -> int:
    """Adresten türetilen sabit bootstrap tohumu (kodda sayı sabiti yok; aynı adres aynı sonuç)."""
    govde = adres.lower().removeprefix("0x")[:16]
    try:
        return int(govde, 16)
    except ValueError:
        return sum(ord(c) for c in govde)


def islem_olculeri(fills: list[dict], hesap_usd: float, likit: set[str], rules: dict | None = None) -> dict:
    """Pencere dolumlarından R1/1–5 ölçüleri. `islem_sayisi`: pencerede KAPANAN round trip (pencere başında açık pozisyonun kapanışı dahil; tutma süresi bilinmez ve
    medyan / kısa işlem payına girmez). `kisa_islem_payi`: tutma süresi `radar_kisa_islem_dk`'dan KISA işlemlerin, süresi bilinenler içindeki payı.
    `max_kaldirac`: o anki toplam pozisyon değeri / hesap değeri (`hesap_usd`, koşu anındaki hesap değeri; olcut.effective_leverage_detail).
    `likit_pay`: nosyonelin (px × sz, tüm perp dolumları) `likit` coinlerdeki payı."""
    rules = rules or load_rules()
    perp = perp_fills(fills)
    islemler = closed_round_trips(perp)
    sureler = [t["holding_hours"] for t in islemler if t["holding_hours"] is not None]
    kisa_saat = float(rules["radar_kisa_islem_dk"]) / 60.0
    nosyonel = {}
    for f in perp:
        nosyonel[str(f["coin"])] = nosyonel.get(str(f["coin"]), 0.0) + abs(float(f["px"]) * float(f["sz"]))
    toplam = sum(nosyonel.values())
    _, azami, _ = effective_leverage_detail(perp, hesap_usd) if perp and hesap_usd > 0 else (None, None, 0)
    return {"islem_sayisi": len(islemler),
            "medyan_tutma_saat": float(statistics.median(sureler)) if sureler else None,
            "kisa_islem_payi": sum(1 for s in sureler if s < kisa_saat) / len(sureler) if sureler else None,
            "max_kaldirac": azami,
            "likit_pay": sum(v for c, v in nosyonel.items() if c in likit) / toplam if toplam > 0 else None}


def hip3_nosyonel_pay(fills: list[dict]) -> float | None:
    """Bilgi alanı (K‑43 adayı): perp dolumlarının nosyonelinde (px × sz) HIP‑3 (`dex:COIN`) payı, 0–1 oran; nosyonel 0 ise None. Kadro/kapılara girmez."""
    perp = perp_fills(fills)
    toplam = sum(abs(float(f["px"]) * float(f["sz"])) for f in perp)
    return sum(abs(float(f["px"]) * float(f["sz"])) for f in perp if is_hip3(str(f["coin"]))) / toplam if toplam > 0 else None


def kopya_olculeri(sonuc: dict | None, adres: str, rules: dict | None = None) -> dict:
    """Kopya oynatma sonucundan R1/6–9 ölçüleri (kopya_$ = kopya kasası ölçeği, `canli_kasa_usd`; K‑28/K‑32). `sonuc` = `Baglam.kopya_oynat` çıktısı: kopya (1 dk gecikme + maliyet) ve `ayna`
    (gecikmesiz, maliyetsiz; aynı slot). `kopya_koruma` = kopya getirisi / ayna getirisi (ayna ≤ 0 ya da yok → None: `kopya_koruma_dusuk`). Sonuç yok / hesaplanamadı → kopya alanları None.
    Bilgi (B3/B12; kapıya girmez): `kopya_islem_sayisi` = bootstrap'a giren kapanan kopya işlemi sayısı; `yuvarlanan_pay` (sonuçtaki); `oransal_ayna` = `sonuc["oransal_ayna"]` getirisi
    (yoksa None); `koruma_boyut` = ayna / oransal_ayna (oransal ≤ 0 ya da yok → None). B14 (bilgi; kapıya girmez): `g_t_istat` = `t_istat(islem)` — bootstrap'ın kullandığı AYNI dizi."""
    rules = rules or load_rules()
    bos = {"kopya_getiri_7g": None, "ayna_getiri_7g": None, "kopya_koruma": None, "kopya_alt20": None, "fiyatsiz_eylem": None, "yaklasik_fiyat_eylem": None,
           "v4_kopya_getiri_7g": None, "v5_onceki_kopya_getiri_7g": None, "kopya_islem_sayisi": None, "yuvarlanan_pay": None, "oransal_ayna": None, "koruma_boyut": None,
           "g_t_istat": None}
    if not sonuc:
        return bos
    v4 = _sayi((sonuc.get("v4") or {}).get("getiri"))
    v5o = _sayi((sonuc.get("v5_onceki") or {}).get("getiri"))
    if sonuc.get("durum") == "hesaplanamadi":
        return {**bos, "fiyatsiz_eylem": sonuc.get("fiyatsiz_eylem"), "yaklasik_fiyat_eylem": sonuc.get("yaklasik_fiyat_eylem"), "v4_kopya_getiri_7g": v4, "v5_onceki_kopya_getiri_7g": v5o}
    getiri = _sayi(sonuc.get("getiri"))
    ayna = _sayi((sonuc.get("ayna") or {}).get("getiri"))
    kasa = _sayi(sonuc.get("baslangic_usd")) or float(rules["canli_kasa_usd"])
    islem = [t["sonuc_usd"] / kasa for t in sonuc.get("kapanan_islemler") or [] if t.get("gecerli") is not False and _sayi(t.get("sonuc_usd")) is not None]
    oransal = _sayi((sonuc.get("oransal_ayna") or {}).get("getiri"))
    return {"kopya_getiri_7g": getiri, "ayna_getiri_7g": ayna,
            "kopya_koruma": None if getiri is None or ayna is None or ayna <= 0 else getiri / ayna,
            "kopya_islem_sayisi": len(islem), "yuvarlanan_pay": sonuc.get("yuvarlanan_pay"), "oransal_ayna": oransal,
            "koruma_boyut": None if ayna is None or oransal is None or oransal <= 0 else ayna / oransal,
            "kopya_alt20": bootstrap_alt(islem, int(rules["radar_bootstrap_tekrar"]), float(rules["radar_bootstrap_alt_yuzdelik"]), adres_tohumu(adres)),
            "g_t_istat": t_istat(islem),                                  # B14 bilgi: aynı `islem` dizisi; karar `kopya_alt20`'de (kural 5: eşik değişmez)
            "fiyatsiz_eylem": sonuc.get("fiyatsiz_eylem"), "yaklasik_fiyat_eylem": sonuc.get("yaklasik_fiyat_eylem"), "v4_kopya_getiri_7g": v4, "v5_onceki_kopya_getiri_7g": v5o}


def on_eleme(aday: dict, vlm: float, rules: dict | None = None) -> str | None:
    """Dolum ÇEKİLMEDEN bilinen elemeler (lider tablosundan): `payda_yok` (trader getirisi paydası ≤ 0), `devir_yuksek` (hafta vlm / hesap > `radar_max_devir_hafta`; tam sınır geçer)."""
    rules = rules or load_rules()
    if trader_getiri_7g(aday["hesap_usd"], aday["hafta_pnl_usd"]) is None:
        return "payda_yok"
    if aday["hesap_usd"] <= 0 or vlm / aday["hesap_usd"] > float(rules["radar_max_devir_hafta"]):
        return "devir_yuksek"
    return None


def degerlendir(satir: dict, rules: dict | None = None, yalniz_dolum: bool = False) -> tuple[bool, str | None]:
    """R1 kuralları SIRAYLA (ucuzdan pahalıya: devir → dolum tabanlı 1–5 → kopya tabanlı); ilk başarısızın kodu `neden`. Sınırlar DAHİL (tam 10 işlem, 1,0 sa, %25, 20x, %80, %50,
    100 kat geçer); `sans_riski` için alt yüzdelik tam 0 ELENİR (> 0 gerekir). Ölçü None (veri yok) = kural başarısız. `hata` doluysa `veri_hatasi`.
    `yalniz_dolum=True`: yalnız devir + dolum tabanlı kurallar (kopya oynatmadan önce; geçerse kopya oynatılır)."""
    rules = rules or load_rules()

    def basarisiz(deger: float | None, kosul) -> bool:
        return deger is None or not kosul(deger)

    sirali = (
        ("devir_yuksek", basarisiz(satir.get("devir_hafta"), lambda v: v <= float(rules["radar_max_devir_hafta"]))),
        ("islem_az", basarisiz(satir.get("islem_sayisi"), lambda v: v >= int(rules["radar_min_islem"]))),
        ("tutma_kisa", basarisiz(satir.get("medyan_tutma_saat"), lambda v: v >= float(rules["radar_min_medyan_tutma_saat"]))),
        ("kisa_islem_fazla", basarisiz(satir.get("kisa_islem_payi"), lambda v: v <= float(rules["radar_kisa_islem_payi_max"]))),
        ("kaldirac_yuksek", basarisiz(satir.get("max_kaldirac"), lambda v: v <= float(rules["radar_max_kaldirac"]))),
        ("likidite_dusuk", basarisiz(satir.get("likit_pay"), lambda v: v >= float(rules["radar_likit_pay_min"]))),
        ("kopya_zarar", basarisiz(satir.get("kopya_getiri_7g"), lambda v: v > 0)),
        ("kopya_koruma_dusuk", basarisiz(satir.get("kopya_koruma"), lambda v: v >= float(rules["radar_kopya_koruma_min"]))),
        ("kopya_islem_az", int(rules.get("radar_min_kopya_islem", 0) or 0) > 0                            # v1.1 (K-53) S2: kopya kapanan işlem ≥ N (bootstrap 2–4 işlemle anlamsız)
         and basarisiz(satir.get("kopya_islem_sayisi"), lambda v: v >= int(rules["radar_min_kopya_islem"]))),
        ("sans_riski", basarisiz(satir.get("kopya_alt20"), lambda v: v > 0)),
        ("akil_sagligi", basarisiz(satir.get("kopya_getiri_7g"), lambda v: v <= float(rules["radar_akil_sagligi_getiri_max"]))
         or not (satir.get("hesap_usd") or 0) > 0),
    )
    if satir.get("hata"):
        return False, "veri_hatasi"
    for kod, basarisiz_mi in sirali[:1 + DOLUM_KURALI if yalniz_dolum else len(sirali)]:
        if basarisiz_mi:
            return False, kod
    return True, None


# ------------------------------------------------------------------------------------------------------------------------------ para hareketi (T6 §2, K‑37; yalnız bilgi)
def net_yatirma(ledger: list[dict], bas_ms: int, bit_ms: int) -> float:
    """Pencere içi (`bas_ms` ≤ zaman ≤ `bit_ms`) `userNonFundingLedgerUpdates` satırlarından net dış para girişi (trader_$) = Σ `deposit.usdc` − Σ `withdraw.usdc`. Diğer türler (iç transfer, spot/perp
    sınıf geçişi, vault, alt hesap) sayılmaz; sayı olmayan ya da pencere dışı satır yok sayılır. Yatırma `hafta_pnl_usd`'yi etkilemez ama hesap değerini şişirir; payda hafta başı sermayedir."""
    net = 0.0
    for satir in ledger or []:
        delta = satir.get("delta") or {}
        zaman, tutar = _sayi(satir.get("time")), _sayi(delta.get("usdc"))
        if zaman is None or tutar is None or not bas_ms <= zaman <= bit_ms:
            continue
        if delta.get("type") == "deposit":
            net += tutar
        elif delta.get("type") == "withdraw":
            net -= tutar
    return net


def yatirma_payi(net_usd: float, hesap_usd: float, hafta_pnl_usd: float) -> float | None:
    """net yatırma / hafta başı sermaye (`hesap − hafta pnl`; oran, 0,2 = %20). Sermaye ≤ 0 → None."""
    sermaye = hesap_usd - hafta_pnl_usd
    return None if sermaye <= 0 else net_usd / sermaye


def para_hareketi_ekle(client: Any, satirlar: list[dict], bas_ms: int, bit_ms: int, rules: dict, log=print, saat=time.monotonic, baslangic: float | None = None) -> int:
    """Havuzdaki (`zaman_yok` hariç) herkes için `net_yatirma_usd` ve `yatirma_payi` yazar. Okuma hatası alanı None bırakır (tarama bozulmaz). Süre bütçesi aşılırsa kalanlar atlanır. Döner: okunan sayı."""
    butce, t0 = float(rules["radar_zaman_butcesi_dk"]) * 60.0, saat() if baslangic is None else baslangic
    okunan = 0
    for s in satirlar:
        if s.get("neden") == "zaman_yok":
            continue
        if saat() - t0 >= butce:
            log("UYARI: para hareketi okuması zaman bütçesi nedeniyle durdu")
            break
        try:
            net = net_yatirma(client.non_funding_ledger(s["adres"], bas_ms), bas_ms, bit_ms)
        except HATALAR:
            continue
        s["net_yatirma_usd"], s["yatirma_payi"] = net, yatirma_payi(net, s["hesap_usd"], s["hafta_pnl_usd"])
        okunan += 1
    return okunan


def yatirma_isaretli(satirlar: list[dict], esik: float) -> list[dict]:
    """`yatirma_payi` > `esik` olan satırlar (rapor işareti; kapı değildir)."""
    return [s for s in satirlar if s.get("yatirma_payi") is not None and s["yatirma_payi"] > esik]


# ------------------------------------------------------------------------------------------------------------------------------ piyasa verisi + kopya oynatma
class MumOnbellegi:
    """`PublicClient.candles` ile aynı yüzey; her coinin dakikalık (Hyperliquid yalnız son 5.000 dakikayı verir), 5 dakikalık ve saatlik serisini koşu boyunca BİR kez çeker, sonraki
    çağrıları dilimden yanıtlar. Böylece mevcut hazırlayıcılar (`izleme_motoru.execution_candles` / `mark_candles`, `kopya_v2.saatlik_mumlar`) DEĞİŞMEDEN kullanılır
    ve aynı coini kullanan yüzlerce aday API'yi yeniden yormaz. Bellek: yalnız (t, açılış, kapanış) üçlüleri (5 dk yürütme fiyatı kapanışı da okur)."""

    DAKIKA_SINIRI = 4999            # execution_candles ile aynı: 1 dk mum geçmişi sınırı (dakika)

    def __init__(self, client: Any, kosu_ms: int, pencere_bas_ms: int):
        self.client, self.kosu_ms, self.pencere_bas_ms = client, kosu_ms, pencere_bas_ms
        self.seriler: dict[tuple[str, str], list[tuple[int, float, float | None]]] = {}

    def _seri(self, coin: str, aralik: str) -> list[tuple[int, float]]:
        anahtar = (coin, aralik)
        if anahtar not in self.seriler:
            if aralik == "1m":
                bas = self.kosu_ms - self.DAKIKA_SINIRI * MINUTE
            else:                                                                  # 5 dk (5.000 mum ≈ 17 gün) ve 1 sa: pencerenin tamamı
                bas = self.pencere_bas_ms // HOUR * HOUR
            satirlar = self.client.candles(coin, bas, self.kosu_ms, interval=aralik)
            self.seriler[anahtar] = sorted((int(c["t"]), float(c["o"]), _sayi(c.get("c"))) for c in satirlar if _sayi(c.get("o")) is not None)
        return self.seriler[anahtar]

    def candles(self, coin: str, start_ms: int, end_ms: int, interval: str = "1m") -> list[dict]:
        return [{"t": t, "o": o, **({"c": k} if k is not None else {})} for t, o, k in self._seri(coin, interval) if start_ms <= t <= end_ms]

    def info(self, payload: dict, weight: int = 20) -> Any:
        return self.client.info(payload, weight=weight)


class Baglam:
    """Koşu boyunca adaylar arasında paylaşılan piyasa verisi (kural 7: veri bir kez çekilir)."""

    def __init__(self, client: Any, kosu_ms: int, pencere_bas_ms: int, rules: dict, v4_yan_yana: bool = False, payda_yan_yana: bool = False):
        self.client, self.kosu_ms, self.pencere_bas_ms, self.rules = client, kosu_ms, pencere_bas_ms, rules
        self.v4_yan_yana = v4_yan_yana                       # bilgi: aynı dolumları kopya_v4 (sabit tutar) ile de oynat (v4 ↔ v5 yan yana; hesabı/kararı değiştirmez)
        self.payda_yan_yana = payda_yan_yana                 # B8 bilgi: kopya + ayna SABİT paydayla da oynatılır (`*_eski` alanları; eski ↔ yeni karşılaştırması)
        self.gecikme_dk = int(rules["radar_kopya_gecikme_dk"])
        self.mum = MumOnbellegi(client, kosu_ms, pencere_bas_ms)
        self.hacim: dict[str, float] = {}          # coin -> 24 sa nosyonel hacim ($)
        self.azami_kaldirac: dict[str, float] | None = None
        self.son_girdi: dict | None = None            # son kopya_oynat'ın mum girdileri (R2 72 sa oynatması yeniden kullanır)
        self._hareket: dict[str, dict] | None = None   # H için coin hareketleri (koşu başına en çok bir kez, yalnız `gecti` aday çıkarsa)
        self.dexler: list[str] | None = None           # perp dex adları (piyasa_oku; K-65: seçimde motor tanımıyla trader hesap değeri okuması)

    def piyasa_oku(self) -> None:
        """Perp dex listesi, coin başına 24 sa hacim (`metaAndAssetCtxs.dayNtlVlm`) ve HL azami kaldıracı (v4 sınırı)."""
        dexler = perp_dex_names(self.client.info({"type": "perpDexs"}, weight=2))
        self.dexler = dexler
        for dex in ["", *dexler]:
            veri = self.client.info({"type": "metaAndAssetCtxs", **({"dex": dex} if dex else {})}, weight=20)
            meta, ctx = veri[0], veri[1]
            for birim, bilgi in zip(meta.get("universe") or [], ctx):
                hacim = _sayi(bilgi.get("dayNtlVlm"))
                if birim.get("name") and hacim is not None:
                    self.hacim[str(birim["name"])] = hacim
        self.azami_kaldirac = im.azami_kaldirac_oku(self.client, dexler)

    def likit_coinler(self) -> set[str]:
        esik = float(self.rules["radar_likit_coin_hacim_usd"])
        return {c for c, v in self.hacim.items() if v >= esik}

    def kopya_oynat(self, dolumlar: list[dict], trader_hesap_usd: Any, ek: bool = False, eski_payda: float | None = None) -> dict:
        """Tek adayın pencere dolumlarını `kopya_v5` ile İKİ kez oynatır (K‑28/K‑32; ikisi de pencere başında BOŞ, aynı slot, `trader_hesap_usd` = oranın paydası):
        **kopya** = `radar_kopya_gecikme_dk` gecikme + maliyet (`kurallar.yaml` taker + kayma); mumlar `MumOnbellegi`'nden (coin başına bir kez), son ≈ 3,5 gün 1 dk mum,
        daha eskisi 5 dk mumun yönümüze KÖTÜ fiyatı (`yaklasik_fiyat_eylem`); eksik hedef `fiyatsiz_eylem`, fiyat uydurulmaz. **ayna** = gecikmesiz (trader'ın dolum fiyatı), maliyetsiz.
        `v4_yan_yana` açıksa `v4` = aynı kopya, `kopya_v4` (sabit tutar) ile (yalnız rapor). `trader_hesap_usd`: sabit sayı ya da `kopya_v5.PaydaSerisi` (B8).
        `ek` (radar taraması; bilgi, B3): `yuvarlanan_pay` (kopyanın açılış kararlarından) ve `oransal_ayna` = ayna, `radar_min_emir_usd` = 0 ile (asgari emre yuvarlama/atlama YOK; tavanlar aynen).
        `eski_payda` verilirse (B8 yan yana) `eski` = aynı kopya + ayna SABİT bu paydayla (`kopya_olculeri` ile aynı biçim)."""
        t0, simdi = pd.Timestamp(self.pencere_bas_ms, unit="ms", tz="UTC"), pd.Timestamp(self.kosu_ms, unit="ms", tz="UTC")
        dolumlar = kopya_v5.hip3_ayikla(dolumlar, bool(self.rules.get("radar_hip3_kopya", True)))     # K‑43 adayı: false ise HIP‑3 için mum da çekilmez; varsayılan true = aynen
        yerel: dict = {}
        mum, _ = im.execution_candles(self.mum, dolumlar, yerel, self.kosu_ms, self.gecikme_dk, [], {}, eski_aralik="5m")
        yaklasik = sum(1 for f in dolumlar if (yerel.get(str(f["coin"]), {}).get(str(kopya_v3.hedef_ms(int(f["time"]), self.gecikme_dk))) or {}).get("yaklasik"))
        eylemler = im.copy_actions(dolumlar)
        isaret = im.mark_candles(self.mum, eylemler, self.kosu_ms)
        saatlik = kopya_v2.saatlik_mumlar(self.mum, {}, dolumlar, im.open_copy_coins(eylemler), self.kosu_ms)
        yurutme = {coin: {int(c["t"]): float(c["o"]) for c in rows} for coin, rows in mum.items()}
        kayit: list | None = [] if ek else None
        sonuc = kopya_v5.hesapla(dolumlar, saatlik, isaret, yurutme, [], t0, simdi, self.gecikme_dk, KOPYA_TARZ, self.rules,
                                 azami_kaldirac=self.azami_kaldirac, trader_hesap_usd=trader_hesap_usd, kayit=kayit)
        sifir = {**self.rules, "maliyet_taker": 0.0, "maliyet_kayma": 0.0}
        sonuc["ayna"] = kopya_v5.hesapla(dolumlar, saatlik, isaret, {}, [], t0, simdi, 0, KOPYA_TARZ, sifir, azami_kaldirac=self.azami_kaldirac, trader_hesap_usd=trader_hesap_usd)
        if ek:
            sonuc["yuvarlanan_pay"] = yuvarlanan_pay(kayit or [])
            sonuc["oransal_ayna"] = kopya_v5.hesapla(dolumlar, saatlik, isaret, {}, [], t0, simdi, 0, KOPYA_TARZ, {**sifir, "radar_min_emir_usd": 0.0},
                                                     azami_kaldirac=self.azami_kaldirac, trader_hesap_usd=trader_hesap_usd)
        if eski_payda is not None:
            eski = kopya_v5.hesapla(dolumlar, saatlik, isaret, yurutme, [], t0, simdi, self.gecikme_dk, KOPYA_TARZ, self.rules, azami_kaldirac=self.azami_kaldirac, trader_hesap_usd=float(eski_payda))
            eski["ayna"] = kopya_v5.hesapla(dolumlar, saatlik, isaret, {}, [], t0, simdi, 0, KOPYA_TARZ, sifir, azami_kaldirac=self.azami_kaldirac, trader_hesap_usd=float(eski_payda))
            sonuc["eski"] = eski
        self.son_girdi = {"saatlik": saatlik, "isaret": isaret, "yurutme": yurutme}
        if self.v4_yan_yana:
            sonuc["v5_onceki"] = kopya_v5.hesapla(dolumlar, saatlik, isaret, yurutme, [], t0, simdi, self.gecikme_dk, KOPYA_TARZ, self.rules, azami_kaldirac=self.azami_kaldirac,
                                                  trader_hesap_usd=trader_hesap_usd, k35=False)          # K‑35 ÖNCESİ kural (v4 emir/trader tavanı + coin başına slot tavanı): önce/sonra karşılaştırması
            sonuc["v4"] = kopya_v4.hesapla(dolumlar, saatlik, isaret, yurutme, [], t0, simdi, self.gecikme_dk, KOPYA_TARZ, self.rules, azami_kaldirac=self.azami_kaldirac)
        return {**sonuc, "yaklasik_fiyat_eylem": yaklasik}


    def hareket(self, log=print) -> dict[str, dict]:
        if self._hareket is None:
            coinler = sorted(c for c in self.hacim if ":" not in c)       # builder dex coinleri (`xyz:AAPL` …) candleSnapshot'ta mum vermez ve hız sınırını boşuna harcar: H yalnız ana HL perp coinleri
            log(f"H: {len(coinler)}/{len(self.hacim)} ana perp coini için saatlik mum okunuyor (trend coin)")
            self._hareket = radar_form.coin_hareketleri(self.client, coinler, self.kosu_ms, self.pencere_bas_ms, self.rules, log)
        return self._hareket

    def form_girdileri(self, dolumlar: list[dict], sonuc: dict, trader_hesap_usd: Any, log=print) -> dict:
        """R2 ham girdileri (yalnız `gecti` adaylar için; docs/VERI_SOZLESMESI.md "Radar havuzu"): günlük kopya getirisi serisi → İ1; kopya düşüşü → İ2; yayılma → Y; son 72 sa kopya getirisi
        (aynı dolumlar, kopya_v5, pencere = son `radar_soguyor_saat` saat, başlangıçta BOŞ); hype payı → H."""
        kasa = float(sonuc.get("baslangic_usd") or self.rules["canli_kasa_usd"])
        gunluk = radar_form.gunluk_getiriler(sonuc.get("egri") or [], kasa)
        t72 = pd.Timestamp(self.kosu_ms - int(self.rules["radar_soguyor_saat"]) * HOUR, unit="ms", tz="UTC")
        g = self.son_girdi or {}
        son72 = kopya_v5.hesapla(dolumlar, g.get("saatlik", {}), g.get("isaret", {}), g.get("yurutme", {}), [], t72, pd.Timestamp(self.kosu_ms, unit="ms", tz="UTC"),
                                 self.gecikme_dk, KOPYA_TARZ, self.rules, azami_kaldirac=self.azami_kaldirac, trader_hesap_usd=trader_hesap_usd)
        return {"kopya_gunluk": gunluk, "kopya_kazanc_gun_orani": radar_form.kazanc_gun_orani(gunluk), "kopya_dusus": _sayi(sonuc.get("dusus")),
                "yayilma": radar_form.yayilma(sonuc.get("kapanan_islemler") or []),
                "kopya_getiri_72s": 0.0 if son72.get("durum") == "hesaplanamadi" else _sayi(son72.get("getiri")),
                "hype_payi": radar_form.hype_payi(closed_round_trips(perp_fills(dolumlar)), self.hareket(log), self.rules)}


# ------------------------------------------------------------------------------------------------------------------------------ koşu
def _bos_satir(aday: dict, vlm: float, rules: dict) -> dict:
    getiri = trader_getiri_7g(aday["hesap_usd"], aday["hafta_pnl_usd"])
    return {"adres": aday["adres"], "hesap_usd": aday["hesap_usd"], "hafta_pnl_usd": aday["hafta_pnl_usd"], "ay_pnl_usd": aday.get("ay_pnl_usd"), "trader_getiri_7g": getiri,
            "islem_sayisi": None, "medyan_tutma_saat": None, "kisa_islem_payi": None, "max_kaldirac": None, "likit_pay": None,
            "kopya_getiri_7g": None, "ayna_getiri_7g": None, "kopya_koruma": None,
            "devir_hafta": vlm / aday["hesap_usd"] if aday["hesap_usd"] > 0 else None,
            "kopya_alt20": None, "fiyatsiz_eylem": None, "yaklasik_fiyat_eylem": None, "v4_kopya_getiri_7g": None, "v5_onceki_kopya_getiri_7g": None, "kopya_gunluk": None, "kopya_kazanc_gun_orani": None, "kopya_dusus": None, "yayilma": None,
            "kopya_getiri_72s": None, "hype_payi": None, "hip3_nosyonel_pay": None, "net_yatirma_usd": None, "yatirma_payi": None,
            "payda_kaynak": None, "payda_nokta": None, "payda_bas_usd": None, "payda_son_oran": None, "kopya_islem_sayisi": None, "yuvarlanan_pay": None, "oransal_ayna": None, "koruma_boyut": None,
            "g_t_istat": None, "gecti": False, "neden": None, "hata": None}


def kopyalanabilirlik(aday: dict, dolumlar: list[dict] | None, hata: str | None, baglam: Baglam) -> dict:
    """R1: tek adayın satırı, ucuzdan pahalıya: `veri_hatasi` (istek hatası) → `payda_yok` / `devir_yuksek` (lider tablosundan) → `dolum_fazla` (dolum sayısı ≥ `radar_dolum_tavan`;
    dolum alanları null) → dolum tabanlı kurallar 1–5 → (hepsi geçtiyse) kopya oynatma ve kalan kurallar. Ölçülmeyen alan `null`; ölçülenler elense de yazılır."""
    rules = baglam.rules
    satir = _bos_satir(aday, aday["hafta_vlm_usd"], rules)
    if hata:
        return {**satir, "neden": "veri_hatasi", "hata": hata}
    on = on_eleme(aday, aday["hafta_vlm_usd"], rules)
    if on:
        return {**satir, "neden": on}
    if len(dolumlar or []) >= int(rules["radar_dolum_tavan"]):
        return {**satir, "neden": "dolum_fazla"}
    dolumlar = [f for f in perp_fills(dolumlar or []) if baglam.pencere_bas_ms <= int(f["time"]) < baglam.kosu_ms]
    satir.update(islem_olculeri(dolumlar, aday["hesap_usd"], baglam.likit_coinler(), rules))
    satir["hip3_nosyonel_pay"] = hip3_nosyonel_pay(dolumlar)
    satir["gecti"], satir["neden"] = degerlendir(satir, rules, yalniz_dolum=True)
    if satir["neden"]:
        return satir                                                       # dolum tabanlı kural başarısız: kopya oynatılmaz (kopya alanları null)
    payda, payda_bilgi = payda_oku(baglam.client, aday["adres"], aday["hesap_usd"], baglam.pencere_bas_ms, baglam.kosu_ms, rules)      # B8: zamana bağlı payda (okunamazsa sabit)
    satir.update(payda_bilgi)
    try:
        sonuc = baglam.kopya_oynat(dolumlar, payda, ek=True, eski_payda=aday["hesap_usd"] if baglam.payda_yan_yana else None)
    except HATALAR as hata_:
        return {**satir, "gecti": False, "neden": "veri_hatasi", "hata": im.data_error_reason(hata_)}
    satir.update(kopya_olculeri(sonuc, aday["adres"], rules))
    satir["gecti"], satir["neden"] = degerlendir(satir, rules)
    if "eski" in sonuc:                                                    # B8 yan yana (bilgi): sabit paydayla aynı kurallar
        eski = {k: kopya_olculeri(sonuc["eski"], aday["adres"], rules)[k] for k in ESKI_ALANLAR}
        satir.update({f"{k}_eski": v for k, v in eski.items()})
        satir["gecti_eski"], satir["neden_eski"] = degerlendir({**satir, **eski}, rules)
    if satir["gecti"]:                                                     # R2 ham girdileri (T3): yalnız radar havuzundaki adaylar için
        try:
            satir.update(baglam.form_girdileri(dolumlar, sonuc, payda))
        except HATALAR as hata_:
            return {**satir, "gecti": False, "neden": "veri_hatasi", "hata": im.data_error_reason(hata_)}
    return satir


def kos(client: Any, kosu_ms: int, cikti: Path, aday_sayisi: int | None = None, rules: dict | None = None, log=print, saat=time.monotonic, v4_yan_yana: bool = False,
        kural_ust: dict | None = None, payda_yan_yana: bool = False, onceki_adresler: list[str] | None = None) -> dict:
    """R0 + R1 + yazım. `aday_sayisi` verilirse `radar_aday_tavan` yerine o (küçük deneme). Ucuzdan pahalıya: lider tablosundan elemeler (`payda_yok`, `devir_yuksek`) dolum
    ÇEKİLMEDEN; sonra `vault`; sonra dolum (en çok `radar_dolum_tavan`). Süre `radar_zaman_butcesi_dk`'yı aşınca kalan adaylar `zaman_yok`. Döner: havuz.json sözlüğü."""
    rules = rules or load_rules()
    baslangic = saat()
    butce_sn = float(rules["radar_zaman_butcesi_dk"]) * 60.0
    pencere_bas = kosu_ms - int(rules["radar_pencere_saat"]) * HOUR
    tablo = client.leaderboard()
    adaylar, toplam, kesilen = evren(tablo, rules, aday_sayisi)
    tutma = tutma_adaylari(tablo, onceki_adresler or [], {a["adres"] for a in adaylar}, rules)   # v1.1 (K-53): önce ölçülür (zaman bütçesi bunları kesmesin)
    adaylar = [*tutma, *adaylar]
    tutma_adres = {a["adres"] for a in tutma}
    baglam = Baglam(client, kosu_ms, pencere_bas, rules, v4_yan_yana, payda_yan_yana)
    baglam.piyasa_oku()
    log(f"R0: evren {toplam} kişi, aday {len(adaylar)} (tutma {len(tutma)}), kesilen {kesilen}; likit coin {len(baglam.likit_coinler())}/{len(baglam.hacim)}")
    satirlar = []
    for sira, aday in enumerate(adaylar, 1):
        adres, etiket = aday["adres"], f"[{sira}/{len(adaylar)}] {aday['adres'][:10]}…"
        t_aday = saat()
        if t_aday - baslangic >= butce_sn:
            satirlar.append({**_bos_satir(aday, aday["hafta_vlm_usd"], rules), "neden": "zaman_yok"})
            continue
        on = on_eleme(aday, aday["hafta_vlm_usd"], rules)
        if on:
            satirlar.append({**_bos_satir(aday, aday["hafta_vlm_usd"], rules), "neden": on})
            log(f"{etiket} {on} (dolum çekilmedi)")
            continue
        dolumlar, hata = None, None
        try:
            if client.vault_details(adres):
                satirlar.append({**_bos_satir(aday, aday["hafta_vlm_usd"], rules), "neden": "vault"})
                log(f"{etiket} vault")
                continue
            dolumlar = client.fills(adres, pencere_bas, max_rows=int(rules["radar_dolum_tavan"]), end_ms=kosu_ms)
        except HATALAR as hata_:
            hata = im.data_error_reason(hata_)
        satir = kopyalanabilirlik(aday, dolumlar, hata, baglam)
        satirlar.append(satir)
        log(f"{etiket} dolum {len(dolumlar or [])}, işlem {satir['islem_sayisi']}, gecti {satir['gecti']} ({satir['neden']}{': ' + satir['hata'] if satir.get('hata') else ''}); {saat() - t_aday:.0f} sn (toplam {(saat() - baslangic) / 60:.1f} dk)")
    for x in satirlar:                                                     # v1.1 (K-53) bilgi: R0 ilk N dışından, önceki kadro üyesi olduğu için ölçüldü
        x["tutma"] = x["adres"] in tutma_adres
    okunan = para_hareketi_ekle(client, satirlar, pencere_bas, kosu_ms, rules, log, saat, baslangic)
    log(f"para hareketi: {okunan}/{len(satirlar)} adres okundu; yatırma payı > {rules['para_hareketi_isaret_payi']}: {len(yatirma_isaretli(satirlar, float(rules['para_hareketi_isaret_payi'])))} kişi")
    if payda_yan_yana:                                                     # kopya oynatmasına varmayan satırda payda karara girmez: eski = yeni
        for x in satirlar:
            if "gecti_eski" not in x:
                x.update({f"{k}_eski": x.get(k) for k in ESKI_ALANLAR})
                x["gecti_eski"], x["neden_eski"] = x["gecti"], x["neden"]
    zaman_yok = sum(1 for x in satirlar if x["neden"] == "zaman_yok")
    if zaman_yok:
        log(f"UYARI: zaman bütçesi ({rules['radar_zaman_butcesi_dk']} dk) aşıldı; {zaman_yok} aday `zaman_yok`")
    sonuc = {"sema": SEMA, "kosu_ms": kosu_ms, "pencere_bas_ms": pencere_bas, "evren_toplam": toplam, "evren_kesilen": kesilen,
             **({"kural_ust": kural_ust} if kural_ust else {}), **({"payda_yan_yana": True} if payda_yan_yana else {}), "satirlar": satirlar}
    klasor = cikti / datetime.fromtimestamp(kosu_ms / 1000, UTC).date().isoformat()
    klasor.mkdir(parents=True, exist_ok=True)
    gecici = klasor / "havuz.json.tmp"
    gecici.write_text(json.dumps(sonuc, ensure_ascii=False, indent=1, allow_nan=False) + "\n", encoding="utf-8")
    gecici.replace(klasor / "havuz.json")
    istatistik = getattr(client, "stats", {})
    log(f"bitti: gecti {sum(1 for s in sonuc['satirlar'] if s['gecti'])}/{len(adaylar)}; süre {(saat() - baslangic) / 60:.1f} dk; "
        f"istek {istatistik.get('istek', '—')}, 429 {istatistik.get('429', '—')}, ağırlık {getattr(getattr(client, 'limiter', None), 'weight_used', '—')}")
    return sonuc


def ozet_md(sonuc: dict) -> str:
    """İş özeti: `gecti` sayısı, neden dağılımı, her sayısal sütunun n / min / medyan / max'ı (kabul kanıtı; gerçek veriyle akıl sağlığı kontrolü)."""
    satirlar = sonuc["satirlar"]
    nedenler: dict[str, int] = {}
    for s in satirlar:
        nedenler[s["neden"] or "gecti"] = nedenler.get(s["neden"] or "gecti", 0) + 1
    cikti = [f"### Radar havuzu {datetime.fromtimestamp(sonuc['kosu_ms'] / 1000, UTC).date()}", "",
             f"satır {len(satirlar)}, gecti **{sum(1 for s in satirlar if s['gecti'])}**, evren_toplam {sonuc['evren_toplam']}, evren_kesilen {sonuc['evren_kesilen']}", "",
             "| neden | adet |", "|---|---|", *[f"| {k} | {v} |" for k, v in sorted(nedenler.items(), key=lambda kv: -kv[1])], "",
             "| sütun | n | min | medyan | max |", "|---|---|---|---|---|"]
    for sutun in SAYISAL:
        degerler = [s[sutun] for s in satirlar if s.get(sutun) is not None]
        cikti.append(f"| {sutun} | {len(degerler)} | " + (f"{min(degerler):.6g} | {statistics.median(degerler):.6g} | {max(degerler):.6g} |" if degerler else "— | — | — |"))
    gecen = sum(1 for s in satirlar if s["gecti"])
    if gecen < 11:
        cikti += ["", f"⚠ UYARI: gecti {gecen} < 11 → kadro 11'den az; saha dolmayabilir (otomatik true'ya dönülmez, lider karar verir)."]
    cikti += payda_ozeti(satirlar)
    esik = float(load_rules()["para_hareketi_isaret_payi"])
    isaretli = yatirma_isaretli(satirlar, esik)
    cikti += ["", f"Para hareketi (bilgi): `yatirma_payi` > {esik:g} olan **{len(isaretli)}** kişi" + (": " + ", ".join(f"{x['adres'][:10]}… ({x['yatirma_payi']:+.2f}{', gecti' if x['gecti'] else ''})" for x in isaretli[:15]) if isaretli else "")]
    return "\n".join(cikti) + "\n"


def payda_ozeti(satirlar: list[dict]) -> list[str]:
    """B8 kabul kanıtı (iş özeti): payda kaynağı dağılımı ve — `--payda-yan-yana` koşusunda — eski (sabit payda) ↔ yeni (zamana bağlı) `gecti` sayıları, kararı değişen adresler ve
    `kopya_getiri_7g` farkının (yeni − eski) dağılımı."""
    kaynak: dict[str, int] = {}
    for s in satirlar:
        if s.get("payda_kaynak"):
            kaynak[s["payda_kaynak"]] = kaynak.get(s["payda_kaynak"], 0) + 1
    c = ["", "Payda (B8): " + (", ".join(f"{k} {v}" for k, v in sorted(kaynak.items())) or "kopya oynatmasına varan satır yok")]
    if not any("gecti_eski" in s for s in satirlar):
        return c
    yeni, eski = {s["adres"] for s in satirlar if s["gecti"]}, {s["adres"] for s in satirlar if s.get("gecti_eski")}
    fark = [s["kopya_getiri_7g"] - s["kopya_getiri_7g_eski"] for s in satirlar if s.get("kopya_getiri_7g") is not None and s.get("kopya_getiri_7g_eski") is not None]
    c += [f"**Eski (sabit payda) ↔ yeni (zamana bağlı):** gecti eski {len(eski)} → yeni {len(yeni)}; ikisinde de {len(yeni & eski)}; yalnız yeni {len(yeni - eski)}; yalnız eski {len(eski - yeni)}",
          f"kopya_getiri_7g yeni − eski: n {len(fark)}" + (f", min {min(fark):+.6g}, medyan {statistics.median(fark):+.6g}, max {max(fark):+.6g}" if fark else "")]
    degisen = [s for s in satirlar if bool(s["gecti"]) != bool(s.get("gecti_eski"))]
    if degisen:
        c += ["", "| adres | gecti eski → yeni | neden eski → yeni | kopya_getiri_7g eski → yeni | payda_bas_usd / hesap_usd |", "|---|---|---|---|---|"]
        f = lambda v: "—" if v is None else f"{v:.6g}"                    # noqa: E731
        for s in degisen[:30]:
            oran = s["payda_bas_usd"] / s["hesap_usd"] if s.get("payda_bas_usd") and s.get("hesap_usd") else None
            c.append(f"| {s['adres'][:10]}… | {s.get('gecti_eski')} → {s['gecti']} | {s.get('neden_eski')} → {s['neden']} | {f(s.get('kopya_getiri_7g_eski'))} → {f(s.get('kopya_getiri_7g'))} | {f(oran)} |")
    return c


def radar_istemcisi(session=None, sleep=time.sleep, rules: dict | None = None) -> PublicClient:
    """Radar için `PublicClient`: radar hız sınırı (`radar_api_agirlik_dk`) + HL 5xx / ağ hatasında en çok 3 yeniden deneme, artan bekleme (`KAPI_YENIDEN_BEKLEME` 5/15/45 sn); sonra `veri_hatasi`.
    429 ilkesi değişmez (5 yeniden deneme + `Retry-After`)."""
    rules = rules or load_rules()
    return PublicClient(session=session, limiter=RateLimiter(limit=int(rules["radar_api_agirlik_dk"]), sleep=sleep), sleep=sleep, yeniden_bekleme=KAPI_YENIDEN_BEKLEME)


def kural_ust_uygula(rules: dict, atamalar: list[str]) -> tuple[dict, dict]:
    """YALNIZ deneme koşusu için (elle `--kural-ust`; günlük `radar.yml`'de YOK): `anahtar=deger` atamaları `radar_*` anahtarlarının üstüne yazılır (değer, mevcut değerin türüne çevrilir).
    Döner: (yeni kurallar, uygulanan {anahtar: değer}); `radar_` ile başlamayan / bilinmeyen anahtar ValueError (donmuş kuralları kazara değiştirme)."""
    yeni, uygulanan = dict(rules), {}
    for atama in atamalar:
        anahtar, ayrac, deger = atama.partition("=")
        anahtar = anahtar.strip()
        if not ayrac or not anahtar.startswith("radar_") or anahtar not in rules:
            raise ValueError(f"kural_ust 'radar_<anahtar>=<değer>' olmalı ve anahtar kurallar.yaml'da bulunmalı: {atama!r}")
        eski = rules[anahtar]
        if isinstance(eski, bool):                                    # bool("false") True olurdu
            if deger.strip().lower() not in ("true", "false"):
                raise ValueError(f"kural_ust bool değeri true|false olmalı: {atama!r}")
            yeni[anahtar] = uygulanan[anahtar] = deger.strip().lower() == "true"
            continue
        yeni[anahtar] = uygulanan[anahtar] = type(eski)(float(deger)) if isinstance(eski, int) else type(eski)(deger)
    return yeni, uygulanan


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cikti", type=Path, default=Path("radar"))
    ap.add_argument("--aday-sayisi", type=int, default=None, help="7 gün getiriye göre ilk N aday (varsayılan: kurallar.yaml radar_aday_tavan)")
    ap.add_argument("--ozet-md", type=Path, default=None, help="özet tabloyu bu dosyaya da yaz (iş özeti için)")
    ap.add_argument("--v4-yan-yana", action="store_true", help="bilgi: kopya oynatmayı kopya_v4 (sabit tutar) ile de yap, `v4_kopya_getiri_7g` alanına yaz")
    ap.add_argument("--payda-yan-yana", action="store_true", help="bilgi (B8): kopya + ayna SABİT paydayla da oynatılır; `*_eski`, `gecti_eski`, `neden_eski` alanları ve özette eski ↔ yeni")
    ap.add_argument("--onceki-kadro", type=Path, default=None, help="v1.1 (K-53): önceki kadro.json; üyeleri R0 dışına düşse de R1'den geçirilir (`radar_tutma_onceki_kadro`)")
    ap.add_argument("--kural-ust", action="append", default=[], metavar="radar_x=deger", help="YALNIZ deneme: radar_* kuralının üstüne yaz (havuz.json `kural_ust` alanında görünür)")
    args = ap.parse_args(argv)
    rules, kural_ust = kural_ust_uygula(load_rules(), args.kural_ust)
    if kural_ust:
        print(f"UYARI: deneme koşusu, kural üstüne yazma: {kural_ust}")
    onceki = [str(x["adres"]) for x in json.loads(args.onceki_kadro.read_text(encoding="utf-8")).get("satirlar", [])] if args.onceki_kadro else None
    sonuc = kos(radar_istemcisi(rules=rules), int(time.time() * 1000), args.cikti, args.aday_sayisi, rules, v4_yan_yana=args.v4_yan_yana, kural_ust=kural_ust,
               payda_yan_yana=args.payda_yan_yana, onceki_adresler=onceki)
    ozet = ozet_md(sonuc)
    print(ozet)
    if args.ozet_md:
        args.ozet_md.write_text(ozet, encoding="utf-8")


if __name__ == "__main__":
    main()
