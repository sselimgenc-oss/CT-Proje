"""Radar taraması, K-85 sade seçim (kullanıcı kararı 21.11). Salt okunur: yalnız herkese açık Hyperliquid verisi (gizli anahtar yok).

Akış (ucuzdan pahalıya): lider tablosu (tüm evren; hesap değeri ≥ `radar_min_hesap_usd`, 30 g pnl > 0, 7 g getiri ≥ `radar_min_getiri_7g`) → `portfolio` (30 g pnl/düşüş, 90 g pnl, son 4 hafta)
→ 30 günlük dolumlar (coin listesi payları, kapanan işlem, açılış, tutma, kaldıraç, en büyük kazanç) → vault süzgeci → kopya oynatma (`kopya_v5`, 30 g pencere, yalnız listedeki coinler)
→ sıra = 30 g getiri / max(30 g düşüş, `radar_siralama_dusus_taban`) → `radar/<tarih>/havuz.json`. Kadro: `radar_kadro.py`.

Kural 7 (tek yer): HL istekleri yalnız `tarama.PublicClient`; işlem eşleme `olcut.closed_round_trips`, kaldıraç `olcut.effective_leverage_detail`; kopya oynatma `kopya_v5.hesapla`; maliyet `kurallar.yaml`.
Kapanan işlem = coin başına sıfırdan sıfıra (ya da işaret değiştirene) episod; pencere başında açık pozisyon kapanınca sayılır, tutma süresi bilinmez ve medyana girmez.
Birimler: oranlar kesirdir (0,10 = %10); `*_usd` trader hesabı; kopya alanları `radar_kasa_usd` ölçeğindedir (slot ölçeği = × `kopya_slot_kat`); zaman UTC ms; süre saat.

Dayanıklılık: `--ilerleme DIZIN` verilirse her adayın sonucu `ilerleme-<gün>.jsonl`'e yazılır; koşu kesilirse aynı gün yeniden başlatılınca (aynı `kosu_ms`) biten adaylar yeniden çekilmez. Bellek: dolumlar adaydan sonra atılır,
mum önbelleği yalnız listedeki coinler için.

    python -m copytrade.radar_tarama --cikti radar --onceki-kadro onceki.json --ilerleme /var/lib/sg-sanal/radar-ilerleme
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

import pandas as pd
import requests

from copytrade import boyut, kopya_v3, kopya_v5, radar_kadro
from copytrade import izleme_motoru as im
from copytrade.defter import HOUR
from copytrade.kurallar import load_rules
from copytrade.olcut import closed_round_trips, effective_leverage_detail, perp_fills
from copytrade.tarama import KAPI_YENIDEN_BEKLEME, PublicClient, RateLimiter, RateLimitError, _address, _window

MINUTE = 60_000
GUN = 24 * HOUR
SEMA = "radar-havuz-v2"
KOPYA_TARZ = "intraday"                 # kopya_v3 çıkış kuralları için tarz (kurallar.yaml golge_v2.intraday)
NEDENLER = ("veri_hatasi", "payda_yok", "ay_pnl", "pnl_90g", "hafta_karli", "dusus_yuksek", "getiri_7g_dusuk", "dolum_fazla", "coin_hacim", "coin_kar", "kar_tek_islem",
            "islem_az", "acilis_fazla", "tutma_kisa", "kaldirac_yuksek", "vault", "kopya_zarar", "kopya_koruma_dusuk", "zaman_yok")       # ucuzdan pahalıya ölçüm sırası
ASAMA_PORTFOY, ASAMA_DOLUM, ASAMA_KOPYA = 1, 2, 3
SAYISAL = ("hesap_usd", "hafta_pnl_usd", "ay_pnl_usd", "getiri_7g", "pnl_30g", "getiri_30g", "dusus_30g", "pnl_90g", "hafta_karli", "tek_islem_haric_pnl", "coin_hacim_pay", "coin_kar_pay",
           "islem_sayisi", "acilis_hafta", "medyan_tutma_saat", "max_kaldirac", "kopya_getiri_30g", "ayna_getiri_30g", "kopya_koruma", "giris_getiri", "skor")
HATALAR = (RateLimitError, requests.RequestException, ValueError, KeyError, TypeError)
VERI_NEDENLERI = radar_kadro.VERI_NEDENLERI
radar_kasa = boyut.radar_kasa                     # tek yer `boyut.radar_kasa`


def _sayi(deger: Any) -> float | None:
    try:
        sayi = float(deger)
    except (TypeError, ValueError):
        return None
    return sayi if math.isfinite(sayi) else None


# ------------------------------------------------------------------------------------------------------------------------------ R0: evren (lider tablosu, ek istek yok)
def ay_pnl(satir: dict) -> float | None:
    """Lider tablosu satırının 30 günlük (`month`) pnl'i ($); satırda pencere yoksa None."""
    for item in satir.get("windowPerformances", []) or []:
        pencere, degerler = (item if isinstance(item, (list, tuple)) and len(item) == 2 else (item.get("window") if isinstance(item, dict) else None, item))
        if isinstance(degerler, dict) and str(pencere).lower() in ("month", "30d"):
            return _sayi(degerler.get("pnl"))
    for k, v in satir.items():
        if str(k).lower().replace("_", "") in ("monthpnl", "30dpnl"):
            return _sayi(v)
    return None


def getiri_7g(hesap_usd: float, hafta_pnl_usd: float) -> float | None:
    """7 gün getirisi = hafta pnl / (hesap − hafta pnl) (yatırma/çekme pnl'i etkilemez). Payda ≤ 0 → None."""
    payda = hesap_usd - hafta_pnl_usd
    return None if payda <= 0 else hafta_pnl_usd / payda


def on_eleme(satir: dict, rules: dict) -> tuple[dict | None, str | None]:
    """Lider tablosu satırı → (aday, None) ya da (None, neden). Neden: `eksik_alan`, `hesap_dusuk`, `ay_pnl`, `getiri_7g_dusuk` (ek istek yapılmadan)."""
    adres = _address(satir)
    hesap = _sayi(satir.get("accountValue", satir.get("account_value")))
    hafta = _sayi(_window(satir, "week", "pnl"))
    if not adres or hesap is None or hafta is None:
        return None, "eksik_alan"
    aday = {"adres": adres, "hesap_usd": hesap, "hafta_pnl_usd": hafta, "ay_pnl_usd": ay_pnl(satir), "getiri_7g": getiri_7g(hesap, hafta)}
    if hesap < float(rules["radar_min_hesap_usd"]):
        return aday, "hesap_dusuk"
    if aday["ay_pnl_usd"] is None or aday["ay_pnl_usd"] <= 0:
        return aday, "ay_pnl"
    if aday["getiri_7g"] is None or aday["getiri_7g"] < float(rules["radar_min_getiri_7g"]) - 1e-12:
        return aday, "getiri_7g_dusuk"
    return aday, None


def evren(satirlar: list[dict], rules: dict | None = None) -> tuple[list[dict], dict[str, int]]:
    """Tüm lider tablosu → (adaylar adres sırasıyla, ön eleme nedeni sayımı). Aday sayısına tavan YOK (tam evren)."""
    rules = rules or load_rules()
    adaylar, sayim = [], {}
    for satir in satirlar:
        aday, neden = on_eleme(satir, rules)
        if neden is None:
            adaylar.append(aday)
        else:
            sayim[neden] = sayim.get(neden, 0) + 1
    adaylar.sort(key=lambda a: a["adres"])
    return adaylar, dict(sorted(sayim.items()))


# ------------------------------------------------------------------------------------------------------------------------------ portfolio: 30 g / 90 g / hafta / düşüş + kopya paydası
def _seri(portfolio: Any, donem: str, alan: str) -> list[tuple[int, float]]:
    try:
        donemler = dict(portfolio or [])
    except (TypeError, ValueError):
        return []
    cikti = []
    for nokta in (donemler.get(donem) or {}).get(alan) or []:
        try:
            t, v = int(nokta[0]), _sayi(nokta[1])
        except (TypeError, ValueError, IndexError):
            continue
        if v is not None:
            cikti.append((t, v))
    return sorted(cikti)


def _deger_at(seri: list[tuple[int, float]], t: int) -> float:
    """`t` anında ya da öncesindeki son nokta (t ilk noktadan önceyse ilk nokta). Seri boş olmamalı."""
    onceki = [v for tt, v in seri if tt <= t]
    return onceki[-1] if onceki else seri[0][1]


def portfoy_olculeri(portfolio: Any, hesap_usd: float, kosu_ms: int, rules: dict) -> dict:
    """`portfolio` yanıtından (yatırma/çekmeden arınmış pnl serisi): `pnl_30g`, `getiri_30g` (= pnl / dönem başı sermaye), `dusus_30g` (özsermaye eğrisinin zirveden en büyük düşüşü),
    `pnl_90g` (allTime serisinden; hesap 90 günden gençse None = ölçülemez, kural uygulanmaz), `hafta_karli` (son 4 haftanın kârlı sayısı; seri 28 günü kapsamıyorsa None).
    Özsermaye eğrisi = dönem başı sermaye + (pnl_t − pnl_0); dönem başı sermaye = hesap değeri − 30 g pnl. Seri yoksa tüm alanlar None."""
    bos = {"pnl_30g": None, "getiri_30g": None, "dusus_30g": None, "pnl_90g": None, "hafta_karli": None}
    pnl = _seri(portfolio, "month", "pnlHistory")
    if len(pnl) < 2:
        return bos
    pnl_30 = pnl[-1][1] - pnl[0][1]
    bas = hesap_usd - pnl_30
    if bas <= 0:
        return {**bos, "pnl_30g": pnl_30}
    zirve, dusus = bas, 0.0
    for _, v in pnl:
        ozs = bas + (v - pnl[0][1])
        zirve = max(zirve, ozs)
        dusus = max(dusus, (zirve - ozs) / zirve if zirve > 0 else 0.0)
    hafta = None
    if pnl[0][0] <= kosu_ms - 28 * GUN + GUN:               # seri en az ~28 günü kapsar (1 gün tolerans)
        sinirlar = [kosu_ms - (4 - i) * 7 * GUN for i in range(5)]
        hafta = sum(1 for i in range(4) if _deger_at(pnl, sinirlar[i + 1]) - _deger_at(pnl, sinirlar[i]) > 0)
    tum = _seri(portfolio, "allTime", "pnlHistory")
    p90 = None
    if tum and tum[0][0] <= kosu_ms - 90 * GUN:
        p90 = tum[-1][1] - _deger_at(tum, kosu_ms - 90 * GUN)
    return {"pnl_30g": pnl_30, "getiri_30g": pnl_30 / bas, "dusus_30g": dusus, "pnl_90g": p90, "hafta_karli": hafta}


def payda_noktalari(portfolio: Any, bit_ms: int) -> list[tuple[int, float]]:
    """`portfolio` hesap değeri noktaları (UTC ms, trader_$), `bit_ms`'e kadar; ince dönem önce, kaba dönem yalnız daha eski noktaları ekler (month → allTime). Biçim tanınmazsa boş."""
    noktalar: list[tuple[int, float]] = []
    for donem in ("week", "month", "allTime"):
        sinir = min((t for t, _ in noktalar), default=None)
        for t, v in _seri(portfolio, donem, "accountValueHistory"):
            if v > 0 and t <= bit_ms and (sinir is None or t < sinir):
                noktalar.append((t, v))
    return sorted(noktalar)


def payda_oku(portfolio: Any, hesap_usd: float, bit_ms: int, rules: dict) -> Any:
    """Kopya oynatmasının trader hesap paydası: `radar_payda_zaman` açık ve seri varsa `kopya_v5.PaydaSerisi` (emir anındaki değer), yoksa sabit `hesap_usd`."""
    if not bool(rules.get("radar_payda_zaman", True)):
        return hesap_usd
    noktalar = payda_noktalari(portfolio, bit_ms)
    return kopya_v5.PaydaSerisi(noktalar) if noktalar else hesap_usd


# ------------------------------------------------------------------------------------------------------------------------------ dolum ölçüleri
def acilis_sayisi(fills: list[dict]) -> int:
    """Açılış sayısı: coin pozisyonunun sıfırdan çıkması ya da işaret değiştirmesi (pencere başında zaten açık olan pozisyon açılış sayılmaz)."""
    konum: dict[str, float] = {}
    n = 0
    for f in sorted(fills, key=lambda x: int(x["time"])):
        coin = str(f["coin"])
        once = float(f["startPosition"]) if f.get("startPosition") not in (None, "") else konum.get(coin, 0.0)
        yon = -1.0 if str(f.get("side")) in {"A", "Sell", "sell"} else 1.0
        sonra = once + yon * float(f["sz"])
        konum[coin] = sonra
        if abs(sonra) > 1e-12 and (abs(once) < 1e-12 or once * sonra < 0):
            n += 1
    return n


def dolum_olculeri(dolumlar: list[dict], hesap_usd: float, pnl_30g: float | None, rules: dict, pencere_gun: float | None = None) -> dict:
    """Pencere perp dolumlarından seçim ölçüleri. Tüm coinlerden: `coin_hacim_pay` (nosyonelin listedeki coinlerdeki payı), `coin_kar_pay` (kapanan işlemlerin net kârının listedeki
    coinlerdeki payı; toplam kâr ≤ 0 ise None), `tek_islem_haric_pnl` (30 g pnl − en büyük kazanan kapanan işlem), `max_kaldirac`. YALNIZ listedeki coinlerden: `islem_sayisi` (kapanan),
    `acilis_hafta`, `medyan_tutma_saat` (süresi bilinenler; yoksa None)."""
    liste = {str(c) for c in rules["radar_coinler"]}
    gun = float(rules["radar_pencere_gun"] if pencere_gun is None else pencere_gun)
    nosyonel: dict[str, float] = {}
    for f in dolumlar:
        nosyonel[str(f["coin"])] = nosyonel.get(str(f["coin"]), 0.0) + abs(float(f["px"]) * float(f["sz"]))
    toplam = sum(nosyonel.values())
    liste_dolum = [f for f in dolumlar if str(f["coin"]) in liste]
    tum_islem = closed_round_trips(dolumlar)
    liste_islem = [t for t in tum_islem if t["coin"] in liste]
    toplam_kar = sum(t["net_pnl"] for t in tum_islem)
    sureler = [t["holding_hours"] for t in liste_islem if t["holding_hours"] is not None]
    kazanclar = [t["net_pnl"] for t in tum_islem if t["net_pnl"] > 0]
    _, azami, _ = effective_leverage_detail(dolumlar, hesap_usd) if dolumlar and hesap_usd > 0 else (None, None, 0)
    return {"coin_hacim_pay": sum(v for c, v in nosyonel.items() if c in liste) / toplam if toplam > 0 else None,
            "coin_kar_pay": sum(t["net_pnl"] for t in liste_islem) / toplam_kar if toplam_kar > 0 else None,
            "tek_islem_haric_pnl": None if pnl_30g is None else pnl_30g - (max(kazanclar) if kazanclar else 0.0),
            "max_kaldirac": azami, "islem_sayisi": len(liste_islem), "acilis_hafta": acilis_sayisi(liste_dolum) / (gun / 7.0) if dolumlar else 0.0,
            "medyan_tutma_saat": float(statistics.median(sureler)) if sureler else None}


def kopya_olculeri(sonuc: dict | None, rules: dict | None = None) -> dict:
    """Kopya oynatma sonucundan: `kopya_getiri_30g`, `ayna_getiri_30g` (kasa ölçeği), `kopya_koruma` = kopya / ayna (ayna ≤ 0 ya da yok → None), `kopya_slot_kat` = kasa / slot."""
    rules = rules or load_rules()
    bos = {"kopya_getiri_30g": None, "ayna_getiri_30g": None, "kopya_koruma": None, "kopya_slot_kat": None}
    if not sonuc or sonuc.get("durum") == "hesaplanamadi":
        return bos
    getiri, ayna = _sayi(sonuc.get("getiri")), _sayi((sonuc.get("ayna") or {}).get("getiri"))
    kasa, slot = _sayi(sonuc.get("baslangic_usd")) or radar_kasa(rules), _sayi(sonuc.get("slot_usd"))
    return {"kopya_getiri_30g": getiri, "ayna_getiri_30g": ayna, "kopya_koruma": None if getiri is None or ayna is None or ayna <= 0 else getiri / ayna,
            "kopya_slot_kat": kasa / slot if slot else None}


def skor_hesapla(getiri_30g: float | None, dusus_30g: float | None, rules: dict) -> float | None:
    """Sıra = 30 g getiri / max(30 g düşüş, `radar_siralama_dusus_taban`)."""
    if getiri_30g is None or dusus_30g is None:
        return None
    return getiri_30g / max(dusus_30g, float(rules["radar_siralama_dusus_taban"]))


def degerlendir(satir: dict, rules: dict | None = None, asama: int = ASAMA_KOPYA) -> tuple[bool, str | None]:
    """Seçim kuralları SIRAYLA (ucuzdan pahalıya); ilk başarısızın kodu `neden`. `asama`: 1 portfolio, 2 + dolum, 3 + kopya. Ölçü None (veri yok) = başarısız (yalnız `pnl_90g` None = ölçülemez, geçer).
    Sınırlar dahil (≥ / ≤); `kopya_zarar` için kopya getirisi > 0 gerekir."""
    rules = rules or load_rules()

    def kotu(deger: float | None, kosul) -> bool:
        return deger is None or not kosul(deger)

    sirali = (
        (ASAMA_PORTFOY, "payda_yok", satir.get("getiri_30g") is None),
        (ASAMA_PORTFOY, "ay_pnl", kotu(satir.get("pnl_30g"), lambda v: v > 0)),
        (ASAMA_PORTFOY, "pnl_90g", satir.get("pnl_90g") is not None and satir["pnl_90g"] <= 0),
        (ASAMA_PORTFOY, "hafta_karli", kotu(satir.get("hafta_karli"), lambda v: v >= int(rules["radar_min_hafta_karli"]))),
        (ASAMA_PORTFOY, "dusus_yuksek", kotu(satir.get("dusus_30g"), lambda v: v <= float(rules["radar_max_dusus_30g"]) + 1e-12)),
        (ASAMA_PORTFOY, "getiri_7g_dusuk", kotu(satir.get("getiri_7g"), lambda v: v >= float(rules["radar_min_getiri_7g"]) - 1e-12)),
        (ASAMA_DOLUM, "coin_hacim", kotu(satir.get("coin_hacim_pay"), lambda v: v >= float(rules["radar_coin_hacim_pay_min"]) - 1e-12)),
        (ASAMA_DOLUM, "coin_kar", kotu(satir.get("coin_kar_pay"), lambda v: v >= float(rules["radar_coin_kar_pay_min"]) - 1e-12)),
        (ASAMA_DOLUM, "kar_tek_islem", kotu(satir.get("tek_islem_haric_pnl"), lambda v: v > 0)),
        (ASAMA_DOLUM, "islem_az", kotu(satir.get("islem_sayisi"), lambda v: v >= int(rules["radar_min_islem"]))),
        (ASAMA_DOLUM, "acilis_fazla", kotu(satir.get("acilis_hafta"), lambda v: v <= float(rules["radar_max_acilis_hafta"]) + 1e-12)),
        (ASAMA_DOLUM, "tutma_kisa", kotu(satir.get("medyan_tutma_saat"), lambda v: v >= float(rules["radar_min_medyan_tutma_saat"]) - 1e-12)),
        (ASAMA_DOLUM, "kaldirac_yuksek", kotu(satir.get("max_kaldirac"), lambda v: v <= float(rules["radar_max_kaldirac"]) + 1e-12)),
        (ASAMA_KOPYA, "kopya_zarar", kotu(satir.get("kopya_getiri_30g"), lambda v: v > 0)),
        (ASAMA_KOPYA, "kopya_koruma_dusuk", kotu(satir.get("kopya_koruma"), lambda v: v >= float(rules["radar_kopya_koruma_min"]) - 1e-12)),
    )
    if satir.get("hata"):
        return False, "veri_hatasi"
    for a, kod, basarisiz in sirali:
        if a <= asama and basarisiz:
            return False, kod
    return True, None


# ------------------------------------------------------------------------------------------------------------------------------ piyasa verisi + kopya oynatma
class MumOnbellegi:
    """`PublicClient.candles` ile aynı yüzey; her coinin dakikalık (HL yalnız son 5.000 dakikayı verir), 5 dakikalık (5.000 mum sınırı: 30 gün için parçalı çekilir) ve saatlik serisini koşu boyunca
    BİR kez çeker. Bellek: yalnız (t, açılış, kapanış) üçlüleri; yalnız listedeki coinler istenir."""

    DAKIKA_SINIRI = 4999
    PARCA_MUM = 4900

    def __init__(self, client: Any, kosu_ms: int, pencere_bas_ms: int):
        self.client, self.kosu_ms, self.pencere_bas_ms = client, kosu_ms, pencere_bas_ms
        self.seriler: dict[tuple[str, str], list[tuple[int, float, float | None]]] = {}

    def _cek(self, coin: str, aralik: str, bas: int, bit: int) -> list[dict]:
        if aralik != "5m":
            return self.client.candles(coin, bas, bit, interval=aralik)
        adim, satirlar, imlec = self.PARCA_MUM * 5 * MINUTE, [], bas
        while imlec < bit:
            satirlar += self.client.candles(coin, imlec, min(bit, imlec + adim), interval="5m")
            imlec += adim
        return satirlar

    def _seri(self, coin: str, aralik: str) -> list[tuple[int, float, float | None]]:
        anahtar = (coin, aralik)
        if anahtar not in self.seriler:
            bas = self.kosu_ms - self.DAKIKA_SINIRI * MINUTE if aralik == "1m" else self.pencere_bas_ms // HOUR * HOUR
            satirlar = self._cek(coin, aralik, bas, self.kosu_ms)
            tekil = {int(c["t"]): (int(c["t"]), float(c["o"]), _sayi(c.get("c"))) for c in satirlar if _sayi(c.get("o")) is not None}
            self.seriler[anahtar] = [tekil[t] for t in sorted(tekil)]
        return self.seriler[anahtar]

    def candles(self, coin: str, start_ms: int, end_ms: int, interval: str = "1m") -> list[dict]:
        return [{"t": t, "o": o, **({"c": k} if k is not None else {})} for t, o, k in self._seri(coin, interval) if start_ms <= t <= end_ms]

    def info(self, payload: dict, weight: int = 20) -> Any:
        return self.client.info(payload, weight=weight)


class Baglam:
    """Koşu boyunca adaylar arasında paylaşılan piyasa verisi (kural 7: veri bir kez çekilir)."""

    def __init__(self, client: Any, kosu_ms: int, pencere_bas_ms: int, rules: dict, kasa_usd: float | None = None):
        self.client, self.kosu_ms, self.pencere_bas_ms, self.rules = client, kosu_ms, pencere_bas_ms, rules
        self.kasa_usd = radar_kasa(rules, kasa_usd)
        self.gecikme_dk = int(rules["radar_kopya_gecikme_dk"])
        self.mum = MumOnbellegi(client, kosu_ms, pencere_bas_ms)
        self.hacim: dict[str, float] = {}
        self.azami_kaldirac: dict[str, float] | None = None
        self._funding: dict[str, list[dict]] = {}
        self.funding_hata = 0

    def piyasa_oku(self) -> None:
        """Ana perp dex: coin başına 24 sa hacim (`metaAndAssetCtxs.dayNtlVlm`; sığ coin tavanı) ve HL azami kaldıracı. Kopya yalnız listedeki (ana dex) coinlerde olduğundan builder dex'leri okunmaz."""
        veri = self.client.info({"type": "metaAndAssetCtxs"}, weight=20)
        for birim, bilgi in zip(veri[0].get("universe") or [], veri[1]):
            hacim = _sayi(bilgi.get("dayNtlVlm"))
            if birim.get("name") and hacim is not None:
                self.hacim[str(birim["name"])] = hacim
        self.azami_kaldirac = im.azami_kaldirac_oku(self.client, [])

    def funding_satirlari(self, coinler: set[str]) -> list[dict]:
        """Pencerenin HL `fundingHistory` satırları, coin başına koşuda BİR kez (500 satırlık sayfalarla; 30 gün saatlik ≈ 720 satır). Okuma hatası → o coin için boş (`funding_hata`)."""
        for coin in sorted(c for c in coinler if c not in self._funding and not c.startswith("@")):
            satirlar: list[dict] = []
            try:
                bas = self.pencere_bas_ms
                while True:
                    sayfa = [x for x in (self.client.info({"type": "fundingHistory", "coin": coin, "startTime": bas, "endTime": self.kosu_ms}, weight=20) or []) if isinstance(x, dict)]
                    satirlar += sayfa
                    if len(sayfa) < 500:
                        break
                    bas = int(sayfa[-1]["time"]) + 1
                self._funding[coin] = satirlar
            except HATALAR:
                self._funding[coin] = []
                self.funding_hata += 1
        return [x for c in sorted(coinler) for x in self._funding.get(c, [])]

    def kopya_oynat(self, dolumlar: list[dict], trader_hesap_usd: Any, bas_ms: int | None = None) -> dict:
        """Dolumları `kopya_v5` ile İKİ kez oynatır (pencere başında BOŞ, aynı slot): **kopya** = `radar_kopya_gecikme_dk` gecikme + maliyet; **ayna** = gecikmesiz, maliyetsiz. `bas_ms` verilirse pencere
        o andan başlar (girişten beri sonuç; yalnız ondan sonraki dolumlar). Mum/fiyat yoksa fiyat uydurulmaz (`fiyatsiz_eylem`). Sığ coin tavanı ve funding motorla aynı."""
        bas = self.pencere_bas_ms if bas_ms is None else max(int(bas_ms), self.pencere_bas_ms)
        dolumlar = [f for f in dolumlar if int(f["time"]) >= bas]
        t0, simdi = pd.Timestamp(bas, unit="ms", tz="UTC"), pd.Timestamp(self.kosu_ms, unit="ms", tz="UTC")
        yerel: dict = {}
        mum, _ = im.execution_candles(self.mum, dolumlar, yerel, self.kosu_ms, self.gecikme_dk, [], {}, eski_aralik="5m")
        yaklasik = sum(1 for f in dolumlar if (yerel.get(str(f["coin"]), {}).get(str(kopya_v3.hedef_ms(int(f["time"]), self.gecikme_dk))) or {}).get("yaklasik"))
        eylemler = im.copy_actions(dolumlar)
        isaret = im.mark_candles(self.mum, eylemler, self.kosu_ms)
        from copytrade import kopya_v2
        saatlik = kopya_v2.saatlik_mumlar(self.mum, {}, dolumlar, im.open_copy_coins(eylemler), self.kosu_ms)
        yurutme = {coin: {int(c["t"]): float(c["o"]) for c in rows} for coin, rows in mum.items()}
        fon = self.funding_satirlari({str(f["coin"]) for f in dolumlar})
        hc = self.hacim or None
        sonuc = kopya_v5.hesapla(dolumlar, saatlik, isaret, yurutme, fon, t0, simdi, self.gecikme_dk, KOPYA_TARZ, self.rules,
                                 azami_kaldirac=self.azami_kaldirac, trader_hesap_usd=trader_hesap_usd, kasa_usd=self.kasa_usd, hacim=hc)
        sifir = {**self.rules, "maliyet_taker": 0.0, "maliyet_kayma": 0.0}
        sonuc["ayna"] = kopya_v5.hesapla(dolumlar, saatlik, isaret, {}, fon, t0, simdi, 0, KOPYA_TARZ, sifir, azami_kaldirac=self.azami_kaldirac,
                                         trader_hesap_usd=trader_hesap_usd, kasa_usd=self.kasa_usd, hacim=hc)
        return {**sonuc, "yaklasik_fiyat_eylem": yaklasik}


# ------------------------------------------------------------------------------------------------------------------------------ koşu
def _bos_satir(aday: dict) -> dict:
    s = {k: None for k in SAYISAL}
    s.update({"adres": aday["adres"], "hesap_usd": aday.get("hesap_usd"), "hafta_pnl_usd": aday.get("hafta_pnl_usd"), "ay_pnl_usd": aday.get("ay_pnl_usd"), "getiri_7g": aday.get("getiri_7g"),
              "kopya_slot_kat": None, "gecti": False, "neden": None, "hata": None})
    return s


def dolum_cek(client: Any, adres: str, bas_ms: int, bit_ms: int, rules: dict) -> list[dict]:
    """Pencere dolumları: en çok `radar_dolum_tavan` satır (tavana ulaşılırsa pencere kesik sayılır; çağıran `dolum_fazla` der)."""
    return client.fills(adres, bas_ms, max_rows=int(rules["radar_dolum_tavan"]), end_ms=bit_ms)


def kopyalanabilirlik(aday: dict, baglam: Baglam, portfolio: Any, dolum_getir, vault_mi: Any = None, giris_ms: int | None = None) -> dict:
    """Tek adayın satırı, ucuzdan pahalıya: portfolio kuralları → dolum çekimi + dolum kuralları → vault → kopya oynatma ve kopya kuralları. Ölçülmeyen alan `null`; ölçülenler elense de yazılır.
    `dolum_getir()` dolumları döndürür (istek hatası yükselir → `veri_hatasi`). `giris_ms` (kadro üyesi): girişten beri kopya sonucu `giris_getiri` (slot ölçeği)."""
    rules = baglam.rules
    satir = _bos_satir(aday)
    satir.update(portfoy_olculeri(portfolio, aday["hesap_usd"], baglam.kosu_ms, rules))
    satir["skor"] = skor_hesapla(satir["getiri_30g"], satir["dusus_30g"], rules)
    satir["gecti"], satir["neden"] = degerlendir(satir, rules, ASAMA_PORTFOY)
    if satir["neden"]:
        return satir
    try:
        ham = dolum_getir()
    except HATALAR as hata:
        return {**satir, "gecti": False, "neden": "veri_hatasi", "hata": im.data_error_reason(hata)}
    perp = perp_fills(ham or [])
    if len(perp) >= int(rules["radar_dolum_tavan"]) or len(ham or []) >= int(rules["radar_dolum_tavan"]):
        return {**satir, "gecti": False, "neden": "dolum_fazla"}
    dolumlar = [f for f in perp if baglam.pencere_bas_ms <= int(f["time"]) < baglam.kosu_ms]
    satir.update(dolum_olculeri(dolumlar, aday["hesap_usd"], satir["pnl_30g"], rules))
    satir["gecti"], satir["neden"] = degerlendir(satir, rules, ASAMA_DOLUM)
    if satir["neden"]:
        return satir
    if vault_mi is not None:
        try:
            if vault_mi():
                return {**satir, "gecti": False, "neden": "vault"}
        except HATALAR as hata:
            return {**satir, "gecti": False, "neden": "veri_hatasi", "hata": im.data_error_reason(hata)}
    liste = {str(c) for c in rules["radar_coinler"]}
    kopya_dolum = [f for f in dolumlar if str(f["coin"]) in liste]            # kopya yalnız listedeki coinlerde
    payda = payda_oku(portfolio, aday["hesap_usd"], baglam.kosu_ms, rules)
    try:
        sonuc = baglam.kopya_oynat(kopya_dolum, payda)
        satir.update(kopya_olculeri(sonuc, rules))
        if giris_ms is not None:
            g = kopya_olculeri(baglam.kopya_oynat(kopya_dolum, payda, bas_ms=giris_ms), rules)
            satir["giris_getiri"] = None if g["kopya_getiri_30g"] is None else g["kopya_getiri_30g"] * float(g["kopya_slot_kat"] or 1.0)
    except HATALAR as hata:
        return {**satir, "gecti": False, "neden": "veri_hatasi", "hata": im.data_error_reason(hata)}
    satir["gecti"], satir["neden"] = degerlendir(satir, rules, ASAMA_KOPYA)
    return satir


class Ilerleme:
    """Kesilen koşunun kaldığı yerden sürmesi için adres başına sonuç günlüğü (`ilerleme-<gün>.jsonl`). Kesin sonuçlar (`veri_hatasi` / `zaman_yok` hariç) yeniden çekilmez;
    ilk satır koşunun `kosu_ms`'ini tutar (pencere aynı kalsın). Dizin None ise hiçbir şey yazılmaz. Eski günlerin dosyaları silinir."""

    def __init__(self, dizin: Path | None, gun: str):
        self.dizin, self.gun = dizin, gun
        self.yol = dizin / f"ilerleme-{gun}.jsonl" if dizin else None
        self.satirlar: dict[str, dict] = {}
        self.kosu_ms: int | None = None
        if self.yol is not None:
            self.dizin.mkdir(parents=True, exist_ok=True)
            for eski in self.dizin.glob("ilerleme-*.jsonl"):
                if eski != self.yol:
                    eski.unlink(missing_ok=True)
            if self.yol.exists():
                for satir in self.yol.read_text(encoding="utf-8").splitlines():
                    try:
                        k = json.loads(satir)
                    except ValueError:
                        continue                                              # yarım yazılmış son satır
                    if "kosu_ms" in k:
                        self.kosu_ms = int(k["kosu_ms"])
                    elif isinstance(k.get("satir"), dict) and k["satir"].get("neden") not in ("veri_hatasi", "zaman_yok"):
                        self.satirlar[str(k["satir"]["adres"])] = k["satir"]

    def baslat(self, kosu_ms: int) -> int:
        """Kayıtlı `kosu_ms` varsa onu, yoksa verileni yazıp döndürür."""
        if self.kosu_ms is not None:
            return self.kosu_ms
        self.kosu_ms = kosu_ms
        if self.yol is not None:
            self.yol.write_text(json.dumps({"kosu_ms": kosu_ms}) + "\n", encoding="utf-8")
        return kosu_ms

    def yaz(self, satir: dict) -> None:
        if self.yol is not None:
            with self.yol.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"satir": satir}, ensure_ascii=False, allow_nan=False) + "\n")


def havuz_yaz(sonuc: dict, cikti: Path) -> Path:
    klasor = cikti / datetime.fromtimestamp(sonuc["kosu_ms"] / 1000, UTC).date().isoformat()
    klasor.mkdir(parents=True, exist_ok=True)
    gecici = klasor / "havuz.json.tmp"
    gecici.write_text(json.dumps(sonuc, ensure_ascii=False, indent=1, allow_nan=False) + "\n", encoding="utf-8")
    gecici.replace(klasor / "havuz.json")
    return klasor / "havuz.json"


def kos(client: Any, kosu_ms: int, cikti: Path, rules: dict | None = None, log=print, saat=time.monotonic, onceki: dict | None = None, donem: str | None = None,
        ilerleme_dizin: Path | None = None, kasa_usd: float | None = None, zorla: bool = False, aday_sayisi: int | None = None) -> dict:
    """Tarama + yazım. Kadro değişim günü değilse (ve ilk kurulum değilse) tarama YAPILMAZ: boş havuz (`tarama: false`) yazılır, kadro aynen sürer. Süre `radar_zaman_butcesi_dk`'yı aşınca kalan
    adaylar `zaman_yok` (koşu eksik). `aday_sayisi` yalnız küçük deneme içindir. Döner: havuz.json sözlüğü."""
    rules = rules or load_rules()
    baslangic = saat()
    uyeler = {str(s["adres"]): s.get("giris_ms") for s in radar_kadro.aktif_uyeler(onceki, donem, rules)}
    gerekli, sebep = radar_kadro.tarama_gerekli(onceki, donem, kosu_ms, rules)
    if not gerekli and not zorla:
        log(f"tarama gerekmiyor ({sebep}); kadro aynen sürer")
        temel = {"sema": SEMA, "kosu_ms": kosu_ms, "kasa_usd": radar_kasa(rules, kasa_usd), "donem": donem}
        return havuz_sonucu({**temel, "tarama": False, "tarama_sebep": sebep, "evren_toplam": 0, "on_eleme": {}, "satirlar": []}, cikti)
    ilerleme = Ilerleme(ilerleme_dizin, datetime.fromtimestamp(kosu_ms / 1000, UTC).date().isoformat())
    kosu_ms = ilerleme.baslat(kosu_ms)
    pencere_bas = kosu_ms - int(float(rules["radar_pencere_gun"])) * GUN
    temel = {"sema": SEMA, "kosu_ms": kosu_ms, "pencere_bas_ms": pencere_bas, "kasa_usd": radar_kasa(rules, kasa_usd), "donem": donem}
    tablo = client.leaderboard()
    adaylar, on_say = evren(tablo, rules)
    if aday_sayisi:
        adaylar = adaylar[:aday_sayisi]
    toplam = len(tablo)
    gorulen = {a["adres"].lower() for a in adaylar}
    satirlar: list[dict] = []
    liste_tablo = {_address(r).lower(): r for r in tablo}
    for adres in uyeler:                                                      # üyeler her koşuda ölçülür (süzgeçten düşse de: çıkış kararı için)
        if adres.lower() in gorulen:
            continue
        r = liste_tablo.get(adres.lower())
        aday, neden = on_eleme(r, rules) if r is not None else (None, "liste_disi")
        if aday is not None and neden is not None:
            satirlar.append({**_bos_satir(aday), "neden": neden})
        elif aday is None:
            satirlar.append({**_bos_satir({"adres": adres}), "neden": neden})
    adaylar = sorted(adaylar, key=lambda a: (a["adres"] not in uyeler, a["adres"]))        # üyeler önce (zaman bütçesi kesmesin)
    baglam = Baglam(client, kosu_ms, pencere_bas, rules, kasa_usd=kasa_usd)
    baglam.piyasa_oku()
    log(f"R0: lider tablosu {toplam}, aday {len(adaylar)}, ön eleme {on_say}; üye {len(uyeler)}; ilerlemeden {len(ilerleme.satirlar)} sonuç")
    butce_sn = float(rules["radar_zaman_butcesi_dk"]) * 60.0
    for sira, aday in enumerate(adaylar, 1):
        adres, etiket = aday["adres"], f"[{sira}/{len(adaylar)}] {aday['adres'][:10]}…"
        eski = ilerleme.satirlar.get(adres)
        if eski is not None and adres not in uyeler:
            satirlar.append(eski)
            continue
        if saat() - baslangic >= butce_sn:
            satirlar.append({**_bos_satir(aday), "neden": "zaman_yok"})
            continue
        t_aday = saat()
        try:
            portfolio = client.portfolio(adres)
        except HATALAR as hata:
            satir = {**_bos_satir(aday), "neden": "veri_hatasi", "hata": im.data_error_reason(hata)}
        else:
            satir = kopyalanabilirlik(aday, baglam, portfolio, lambda adres=adres: dolum_cek(client, adres, pencere_bas, kosu_ms, rules),
                                      vault_mi=lambda adres=adres: bool(client.vault_details(adres)), giris_ms=uyeler.get(adres) if adres in uyeler else None)
        satirlar.append(satir)
        ilerleme.yaz(satir)
        log(f"{etiket} gecti {satir['gecti']} ({satir['neden']}{': ' + satir['hata'] if satir.get('hata') else ''}); {saat() - t_aday:.0f} sn (toplam {(saat() - baslangic) / 60:.1f} dk)")
    zaman_yok = sum(1 for x in satirlar if x["neden"] == "zaman_yok")
    if zaman_yok:
        log(f"UYARI: zaman bütçesi ({rules['radar_zaman_butcesi_dk']} dk) aşıldı; {zaman_yok} aday `zaman_yok` (yeniden koşuda kaldığı yerden sürer)")
    sonuc = {**temel, "bitis_ms": kosu_ms + int((saat() - baslangic) * 1000), "tarama": True, "tarama_sebep": sebep, "evren_toplam": toplam, "on_eleme": on_say, "funding_hata": baglam.funding_hata,
             "satirlar": satirlar}
    istatistik = getattr(client, "stats", {})
    log(f"bitti: gecti {sum(1 for s in satirlar if s['gecti'])}/{len(satirlar)}; süre {(saat() - baslangic) / 60:.1f} dk; istek {istatistik.get('istek', '—')}, 429 {istatistik.get('429', '—')}")
    return havuz_sonucu(sonuc, cikti)


def havuz_sonucu(sonuc: dict, cikti: Path) -> dict:
    havuz_yaz(sonuc, cikti)
    return sonuc


def ozet_md(sonuc: dict) -> str:
    """İş özeti: tarama yapıldı mı, `gecti` sayısı, neden dağılımı, sayısal sütunların n / min / medyan / max'ı."""
    satirlar = sonuc["satirlar"]
    gun = datetime.fromtimestamp(sonuc["kosu_ms"] / 1000, UTC).date()
    if not sonuc.get("tarama"):
        return f"### Radar havuzu {gun}\n\ntarama yapılmadı ({sonuc.get('tarama_sebep')}); kadro aynen sürer.\n"
    nedenler: dict[str, int] = {}
    for s in satirlar:
        nedenler[s["neden"] or "gecti"] = nedenler.get(s["neden"] or "gecti", 0) + 1
    cikti = [f"### Radar havuzu {gun}", "", f"satır {len(satirlar)}, gecti **{sum(1 for s in satirlar if s['gecti'])}**, lider tablosu {sonuc['evren_toplam']}, ön eleme {sonuc.get('on_eleme')}", "",
             "| neden | adet |", "|---|---|", *[f"| {k} | {v} |" for k, v in sorted(nedenler.items(), key=lambda kv: -kv[1])], "",
             "| sütun | n | min | medyan | max |", "|---|---|---|---|---|"]
    for sutun in SAYISAL:
        degerler = [s[sutun] for s in satirlar if s.get(sutun) is not None]
        cikti.append(f"| {sutun} | {len(degerler)} | " + (f"{min(degerler):.6g} | {statistics.median(degerler):.6g} | {max(degerler):.6g} |" if degerler else "— | — | — |"))
    return "\n".join(cikti) + "\n"


def radar_istemcisi(session=None, sleep=time.sleep, rules: dict | None = None) -> PublicClient:
    """Radar için `PublicClient`: nazik hız sınırı (`radar_api_agirlik_dk`) + HL 5xx / ağ hatasında en çok 3 yeniden deneme (`KAPI_YENIDEN_BEKLEME`); sonra `veri_hatasi`. 429: 5 yeniden deneme + `Retry-After`."""
    rules = rules or load_rules()
    return PublicClient(session=session, limiter=RateLimiter(limit=int(rules["radar_api_agirlik_dk"]), sleep=sleep), sleep=sleep, yeniden_bekleme=KAPI_YENIDEN_BEKLEME)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cikti", type=Path, default=Path("radar"))
    ap.add_argument("--ozet-md", type=Path, default=None, help="iş özetini bu dosyaya da yaz")
    ap.add_argument("--onceki-kadro", type=Path, default=None, help="önceki kadro.json (üyeler, yasak listesi, dönem; yoksa ilk kurulum)")
    ap.add_argument("--donem", default=None, help="dönem başı (UTC ISO); varsayılan copytrade/canli/DONEM")
    ap.add_argument("--ilerleme", type=Path, default=None, help="kesilirse kaldığı yerden sürmek için ilerleme dizini (kalıcı bir yer)")
    ap.add_argument("--zorla", action="store_true", help="kontrol günü olmasa da tara")
    ap.add_argument("--aday-sayisi", type=int, default=None, help="YALNIZ deneme: ilk N aday")
    args = ap.parse_args(argv)
    rules = load_rules()
    onceki = json.loads(args.onceki_kadro.read_text(encoding="utf-8")) if args.onceki_kadro else None
    sonuc = kos(radar_istemcisi(rules=rules), int(time.time() * 1000), args.cikti, rules, onceki=onceki, donem=args.donem or radar_kadro.donem_oku(), ilerleme_dizin=args.ilerleme,
                zorla=args.zorla, aday_sayisi=args.aday_sayisi)
    ozet = ozet_md(sonuc)
    print(ozet)
    if args.ozet_md:
        args.ozet_md.write_text(ozet, encoding="utf-8")


if __name__ == "__main__":
    main()
