"""İlk 11 puanının 10 ham alanının TEK hesap yeri (docs/ILK11_SECIM_SARTNAME.md §3, §5.2; AGENTS kural 7).

Saf modül: ağ ve dosya yok. Kapı (ilk seçim, `kapi.evaluate_address`) ve izleme motoru (haftalık form) alanları BURADAKİ fonksiyonlarla
üretir; mevcut hesapları çağırır, kopyalamaz (`kapi.twr_chain`, `olcut.closed_round_trips`, `olcut.kazanma_orani`,
`olcut.effective_leverage_detail`, `secim.puan`, `ilk11.golge_ozeti`). Ağırlık / dönüşüm / yüzdelik `copytrade/ilk11.py`'de kalır (değişmez);
burada yalnız HAM alan üretilir. Tüm sayısal sınırlar `kurallar.yaml` `ilk11_*` anahtarlarından okunur.

Birimler (docs/VERI_SOZLESMESI.md §6): getiri / oran = kesir (0,012 = %1,2); `hesap` $ (trader hesabı); `tutma` **dakika**; `kaldirac` x;
`siklik` adet/gün; zaman UTC. Eksik / akıl sağlığı dışı alan = ``None`` (puanlamada 35).
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

import pandas as pd

from copytrade import olcut, secim
from copytrade.ilk11 import KALDIRAC_ALANLARI, golge_ozeti
from copytrade.kurallar import load_rules

MS = pd.Timedelta(milliseconds=1)
IHLAL_ONEKI = "akil_sagligi_ihlali:"
DAKIKA_SAAT = 60.0     # birim dönüşümü (saat -> dakika), eşik değil


# --------------------------------------------------------------------------------------------- portfolio pencereleri

def _sayi(value: Any) -> float | None:
    """Sayı ya da sayı metni -> float; None / bool / NaN / sonsuz / çözülemeyen -> None (CSV'den gelen NaN dahil)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _seri(points: Any) -> pd.Series:
    """HL ``[[ms, "değer"], ...]`` -> zaman indeksli (UTC) artan seri; sayısal olmayan nokta atılır."""
    items: dict[pd.Timestamp, float] = {}
    for point in points or []:
        value = _sayi(point[1]) if len(point) > 1 else None
        if value is not None:
            items[pd.to_datetime(int(point[0]), unit="ms", utc=True)] = value
    return pd.Series(items, dtype=float).sort_index()


def _pencere_verisi(portfolio: Any, pencere: str) -> tuple[pd.Series, pd.Series] | None:
    """``portfolio`` (HL ``[[ad, {accountValueHistory, pnlHistory}], ...]``) içinden ``pencere`` ("week" / "month") için (PnL, hesap değeri)
    serileri. PnL < 2 nokta ya da hesap değeri yoksa ``None`` (ölçülemez)."""
    periods = {name: value for name, value in portfolio if isinstance(value, dict)} if portfolio else {}
    data = periods.get(pencere) or {}
    pnl, values = _seri(data.get("pnlHistory")), _seri(data.get("accountValueHistory"))
    if len(pnl) < 2 or values.empty:
        return None
    return pnl, values


def _zincir(portfolio: Any, pencere: str, gun: int) -> pd.Series | None:
    """Son noktadan geriye ``gun`` gün için ``kapi.twr_chain`` özsermaye serisi (Modified Dietz; yatırma/çekme getiri sayılmaz).

    Pencere (son − gün, son]; zincirin tabanı, ``son − gün`` anında ya da ondan önceki SON noktadır (`twr_chain` taban noktasını `since`'ten
    kesin önceki alır; `+1 ms` ile tam sınırdaki nokta da taban olur, sınırın dışındaki PnL sayılmaz). Taban yoksa (geçmiş pencereden kısa)
    ilk nokta taban olur."""
    from copytrade import kapi    # kapi bu modülü de içe aktarır: döngüyü çağrı anına ertele

    veri = _pencere_verisi(portfolio, pencere)
    if veri is None:
        return None
    pnl, values = veri
    since = pnl.index[-1] - pd.Timedelta(days=int(gun)) + MS
    chain = kapi.twr_chain(pnl, values, since)
    return None if chain is None else chain["equity"]


def pencere_getiri(portfolio: Any, pencere: str, gun: int) -> float | None:
    """Zaman ağırlıklı getiri (oran): zincirin son özsermayesi − 1. ``None``: pencerede < 2 nokta."""
    equity = _zincir(portfolio, pencere, gun)
    return None if equity is None else float(equity.iloc[-1] - 1.0)


def pencere_dusus(portfolio: Any, pencere: str, gun: int) -> float | None:
    """Aynı zincirde zirveden en büyük düşüş: ``max(1 − özsermaye / önceki zirve)``, oran, pozitif büyüklük (0,25 = %25)."""
    equity = _zincir(portfolio, pencere, gun)
    return None if equity is None else float((1.0 - equity / equity.cummax()).max())


def pozitif_gun_orani(portfolio: Any, pencere: str, gun: int) -> float | None:
    """ΔPnL > 0 olan gün / ΔPnL ≠ 0 olan gün (oran). Günler UTC; günün PnL'i o günün SON ``pnlHistory`` noktasıdır (nokta olmayan gün
    önceki değeri taşır, ΔPnL = 0 sayılır -> paydaya girmez). Pencere = son noktanın günü dahil son ``gun`` takvim günü; ilk günün farkı
    için taban, pencereden önceki son günün PnL'idir (taban yoksa o gün atlanır). Aktif (ΔPnL ≠ 0) gün yoksa ``None``."""
    veri = _pencere_verisi(portfolio, pencere)
    if veri is None:
        return None
    pnl = veri[0]
    son_gun = pnl.index[-1].normalize()
    gunluk = pnl.groupby(pnl.index.normalize()).last()
    gunluk = gunluk.reindex(pd.date_range(gunluk.index[0], son_gun, freq="D")).ffill()
    fark = gunluk.diff()
    pencere_farki = fark[fark.index > son_gun - pd.Timedelta(days=int(gun))].dropna()
    aktif = pencere_farki[pencere_farki != 0]
    return None if aktif.empty else float((aktif > 0).mean())


def kapi_bilgi_sutunlari(portfolio: Any, rules: dict | None = None) -> dict[str, float | None]:
    """Kapı `sonuc.csv` bilgi sütunları (K-12.11; adım / eşik kullanmaz): ``portfolio`` zaten çekilmiştir, yeni istek yok."""
    rules = rules or load_rules()
    ay, hafta = int(rules["ilk11_form_pencere_gun"]), int(rules["ilk11_hafta_pencere_gun"])
    return {"ilk11_ay_roi": pencere_getiri(portfolio, "month", ay), "ilk11_hafta_roi": pencere_getiri(portfolio, "week", hafta),
            "ilk11_dusus_30g": pencere_dusus(portfolio, "month", ay), "ilk11_tutarli_30g": pozitif_gun_orani(portfolio, "month", ay)}


# --------------------------------------------------------------------------------------------- akıl sağlığı

def _deger_metni(value: float) -> str:
    """İhlal değerinin kararlı metni: tam sayı ise ``1805``, değilse ``repr``."""
    if math.isinf(value):
        return "inf" if value > 0 else "-inf"
    return str(int(value)) if float(value).is_integer() else repr(float(value))


def akil_sagligi(alanlar: Mapping[str, Any], kaynaklar: Mapping[str, str | None] | None = None, rules: dict | None = None,
                 tur: str = "ilk") -> tuple[dict[str, float | None], dict[str, str | None]]:
    """§3.1: aralık dışı değer KULLANILMAZ -> ``None`` + ``alan_kaynagi[alan] = "akil_sagligi_ihlali:<değer>"``.

    ``tur``: "ilk" (ilk seçim, kapı satırı) ya da "form" (haftalık form); yalnız `golge` aralığını ayırır (`ilk11_saglik.golge_ilk` /
    `golge_form`). `kaldirac` aralığı mevcut `saglik_max_kaldirac`'tır. Eksik (``None`` / NaN) alan ihlal değildir: ``None`` kalır ve kaynağı
    ``None`` olur. Döner: (temiz alanlar, kaynaklar), ikisi de `KALDIRAC_ALANLARI` sırasında."""
    rules = rules or load_rules()
    aralik, alt_disla = rules["ilk11_saglik"], set(rules["ilk11_saglik_alt_disla"])
    kaynaklar = kaynaklar or {}
    temiz: dict[str, float | None] = {}
    yeni: dict[str, str | None] = {}
    for alan in KALDIRAC_ALANLARI:
        ham = alanlar.get(alan)
        sayi = _sayi(ham)
        if sayi is None and isinstance(ham, (int, float)) and not isinstance(ham, bool) and math.isinf(ham):
            temiz[alan], yeni[alan] = None, IHLAL_ONEKI + _deger_metni(float(ham))
            continue
        if sayi is None:
            temiz[alan], yeni[alan] = None, None
            continue
        if alan == "kaldirac":
            alt, ust = 0.0, float(rules["saglik_max_kaldirac"])
        else:
            alt, ust = (float(x) for x in aralik[f"golge_{tur}" if alan == "golge" else alan])
        dis = sayi < alt or sayi > ust or (alan in alt_disla and sayi <= alt)
        if dis:
            temiz[alan], yeni[alan] = None, IHLAL_ONEKI + _deger_metni(sayi)
        else:
            temiz[alan], yeni[alan] = sayi, kaynaklar.get(alan) or alan
    return temiz, yeni


def ihlal_mi(kaynak: str | None) -> bool:
    return isinstance(kaynak, str) and kaynak.startswith(IHLAL_ONEKI)


def doluluk_ozeti(alanlar: Sequence[Mapping[str, Any]], kaynaklar: Sequence[Mapping[str, str | None]]) -> dict[str, dict[str, int]]:
    """Aday listesi için alan başına {toplam, dolu, eksik, ihlal}. ``eksik`` ihlal HARİÇ boş alandır (ihlal ayrı sayılır)."""
    out = {alan: {"toplam": len(alanlar), "dolu": 0, "eksik": 0, "ihlal": 0} for alan in KALDIRAC_ALANLARI}
    for values, sources in zip(alanlar, kaynaklar):
        for alan in KALDIRAC_ALANLARI:
            if ihlal_mi(sources.get(alan)):
                out[alan]["ihlal"] += 1
            elif values.get(alan) is None:
                out[alan]["eksik"] += 1
            else:
                out[alan]["dolu"] += 1
    return out


def saglik_sorunlari(ozet: Mapping[str, Mapping[str, int]], rules: dict | None = None) -> list[str]:
    """Bir alanda ihlal / aday > ``saglik_max_hata_orani`` ise o alan sorunludur (koşu kırmızı, snapshot yayımlanmaz). Boş liste = geçti."""
    limit = float((rules or load_rules())["saglik_max_hata_orani"])
    return [f"{alan}: {v['ihlal']}/{v['toplam']} aday akıl sağlığı aralığı dışında (%{100 * v['ihlal'] / v['toplam']:.1f} > %{100 * limit:.0f})"
            for alan, v in ozet.items() if v["toplam"] and v["ihlal"] / v["toplam"] > limit]


def doluluk_sorunlari(ozet: Mapping[str, Mapping[str, int]], rules: dict | None = None) -> list[str]:
    """Bir alanda dolu / aday < ``ilk11_min_doluluk`` ise o alan yetersizdir (snapshot yayımlanmaz). Boş liste = geçti."""
    limit = float((rules or load_rules())["ilk11_min_doluluk"])
    return [f"{alan}: doluluk {v['dolu']}/{v['toplam']} (%{100 * v['dolu'] / v['toplam']:.1f} < %{100 * limit:.0f})"
            for alan, v in ozet.items() if v["toplam"] and v["dolu"] / v["toplam"] < limit]


# --------------------------------------------------------------------------------------------- ilk seçim (kapı satırı)

def ilk_alanlar(satir: Mapping[str, Any], rules: dict | None = None) -> tuple[dict[str, float | None], dict[str, str | None]]:
    """Kapı `sonuc.csv` satırından 10 ham alan (İ, ilk seçim) ve kaynakları; akıl sağlığı uygulanmış halde döner.

    `golge` = `secim.puan(satir)` (tarzın kapı gecikmesindeki net, seçim v1.3 ile aynı); `tutma` = ``median_holding_hours × 60`` (dakika);
    `hesap` = ``hesap_degeri_bugun`` (leaderboard `account_value` DEĞİL); `ay_roi` / `hafta_roi` leaderboard `roi` DEĞİL, kapının
    `ilk11_*` bilgi sütunlarıdır. Satırdaki NaN eksik sayılır."""
    row = {k: (None if v is None or (isinstance(v, float) and math.isnan(v)) else v) for k, v in satir.items()}
    delay = _sayi(row.get("kapi_gecikme_dk"))
    golge_sutun = f"gecikme_{int(delay)}dk_net" if delay is not None else None
    tutma_saat = _sayi(row.get("median_holding_hours"))
    ham = {"golge": secim.puan(row), "ay_roi": _sayi(row.get("ilk11_ay_roi")), "hafta_roi": _sayi(row.get("ilk11_hafta_roi")),
           "hesap": _sayi(row.get("hesap_degeri_bugun")), "dusus": _sayi(row.get("ilk11_dusus_30g")),
           "kazanma": _sayi(row.get("kazanma_orani")), "siklik": _sayi(row.get("gunluk_islem_sikligi")),
           "tutma": None if tutma_saat is None else tutma_saat * DAKIKA_SAAT, "kaldirac": _sayi(row.get("median_leverage")),
           "tutarli": _sayi(row.get("ilk11_tutarli_30g"))}
    kaynak = {"golge": golge_sutun, "ay_roi": "ilk11_ay_roi", "hafta_roi": "ilk11_hafta_roi", "hesap": "hesap_degeri_bugun",
              "dusus": "ilk11_dusus_30g", "kazanma": "kazanma_orani", "siklik": "gunluk_islem_sikligi",
              "tutma": "median_holding_hours*60", "kaldirac": "median_leverage", "tutarli": "ilk11_tutarli_30g"}
    if ham["hesap"] is not None and ham["hesap"] <= 0:
        ham["hesap"] = None                              # "≤ 0 / yok -> None" (ihlal değil, eksik)
    return akil_sagligi(ham, kaynak, rules, "ilk")


# --------------------------------------------------------------------------------------------- haftalık form (izleme)

def _zaman(value: Any) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        raise ValueError("zaman dilimi (UTC) içermeli")
    return stamp.tz_convert("UTC")


def form_ham_30g(fills: Sequence[Mapping[str, Any]] | None, portfolio: Any, hesap: Any, v3: Mapping[str, Any] | None,
                 now: datetime | pd.Timestamp | str, rules: dict | None = None) -> dict[str, Any]:
    """Haftalık form (F) 10 ham alanı: izleme motorunun her saat zaten çektiği veriden, ``now``'dan geriye 30 gün.

    ``fills``: trader dolumları (HL ``userFillsByTime`` biçimi; ``None`` = alınamadı, ``[]`` = alındı, dolum yok); ``portfolio``: HL
    `portfolio`; ``hesap``: trader hesap değeri ($, izlemenin `hesap_degeri_toplam` = ana + HIP-3 + spot USDC; kapının `hesap_degeri_bugun` ile AYNI tanım); ``v3``: ``sanal_kopya_v3`` sonucu (``kapanan_islemler``);
    ``now``: okuma zamanı (`veri_zamani`, UTC). Kapanış zamanı pencerede ((now − 30 g, now]) olan işlemler sayılır; `tutma` yalnız açılışı
    bilinen işlemlerden. Döner: ``{alanlar, alan_kaynagi, pencere_bitis (UTC ISO), dolu_alan}`` (`ilk11_form_ham`)."""
    rules = rules or load_rules()
    bitis = _zaman(now)
    gun = int(rules["ilk11_form_pencere_gun"])
    bas = bitis - pd.Timedelta(days=gun)
    ham: dict[str, float | None] = dict.fromkeys(KALDIRAC_ALANLARI)
    kaynak: dict[str, str | None] = {}

    # golge: v3 kapanan işlemlerinin büzülmüş ortalaması (yalnız geçerli, kapanışı pencerede)
    getiriler: list[float] = []
    for islem in (v3 or {}).get("kapanan_islemler") or []:
        kapanis = _zaman(islem["kapanis"]) if islem.get("kapanis") else None
        getiri = _sayi(islem.get("getiri"))
        if islem.get("gecerli") is True and getiri is not None and kapanis is not None and bas < kapanis <= bitis:
            getiriler.append(getiri)
    ham["golge"] = golge_ozeti(getiriler)["buzulmus_ortalama"]
    kaynak["golge"] = "sanal_kopya_v3.kapanan_islemler"

    ham["ay_roi"], kaynak["ay_roi"] = pencere_getiri(portfolio, "month", gun), "portfolio.month"
    ham["hafta_roi"], kaynak["hafta_roi"] = pencere_getiri(portfolio, "week", int(rules["ilk11_hafta_pencere_gun"])), "portfolio.week"
    ham["dusus"], kaynak["dusus"] = pencere_dusus(portfolio, "month", gun), "portfolio.month"
    ham["tutarli"], kaynak["tutarli"] = pozitif_gun_orani(portfolio, "month", gun), "portfolio.month"
    hesap_sayi = _sayi(hesap)
    ham["hesap"] = hesap_sayi if hesap_sayi is not None and hesap_sayi > 0 else None
    kaynak["hesap"] = "traderlar.hesap_degeri_toplam"

    if fills is not None:
        perp = olcut.perp_fills(list(fills))
        islemler = [r for r in olcut.closed_round_trips(perp) if bas < r["close_time"] <= bitis]
        ham["kazanma"] = olcut.kazanma_orani(islemler)
        ham["siklik"] = len(islemler) / gun
        tutma = [r["holding_hours"] for r in islemler if r["holding_hours"] is not None]
        ham["tutma"] = float(pd.Series(tutma).median()) * DAKIKA_SAAT if tutma else None
        pencere_dolumlari = [f for f in perp if bas < pd.to_datetime(int(f["time"]), unit="ms", utc=True) <= bitis]
        seri = _hesap_serisi(portfolio)
        medyan, _, _ = olcut.effective_leverage_detail(pencere_dolumlari, seri if seri is not None else (ham["hesap"] or 0))
        ham["kaldirac"] = medyan
    for alan, ad in (("kazanma", "closed_round_trips"), ("siklik", "closed_round_trips"), ("tutma", "closed_round_trips"),
                     ("kaldirac", "effective_leverage_detail")):
        kaynak[alan] = ad

    temiz, kaynaklar = akil_sagligi(ham, kaynak, rules, "form")
    return {"alanlar": temiz, "alan_kaynagi": kaynaklar, "pencere_bitis": bitis.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "dolu_alan": sum(v is not None for v in temiz.values())}


def _hesap_serisi(portfolio: Any) -> pd.Series | None:
    """Kaldıraç paydası: portfolio ``allTime.accountValueHistory`` (kapının `account_history`'siyle aynı)."""
    from copytrade import kapi
    serie = kapi.account_history(portfolio)
    return serie if serie is not None and len(serie) else None
