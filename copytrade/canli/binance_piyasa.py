"""Binance USDⓈ-M Futures PUBLIC piyasa verisi (K-81, Aşama A kâğıt; anahtarsız, imzasız uçlar) + HL `post` uyarlayıcısı.

Uçlar (hepsi GET, anahtar yok; DOĞRULANMADI: Binance dokümanı bu ortamdan okunamadı, adlar docs/binance-plan.md §2-4'ten):
`/fapi/v1/exchangeInfo` (durum, tick, adım, min nosyonel) · `/fapi/v1/premiumIndex` (mark, son fonlama oranı) · `/fapi/v1/fundingInfo` (8 saatten farklı aralıklar) ·
`/fapi/v1/depth` (defter) · `/fapi/v1/ticker/bookTicker` (en iyi alış/satış; erişim testi). WebSocket yok: ~75 emir/gün için REST yeter, 451 yönetimi de basit kalır.
Erişim: 403/451 -> `BinanceErisimYok` (sunucu konumu kısıtı); diğer ağ/HTTP hataları -> `BinanceHata`. `kesinti_sn()` son başarıdan beri geçen süre (bekçi buna bakar).

`piyasa_post(hl_post, piyasa, tablo)`: motorun HL `post`unun yerine geçer. YALNIZ fiyat/fonlama okumaları Binance'e yönlenir (`allMids` -> eşlemeli coinlerde Binance mark; `metaAndAssetCtxs` -> eşlemeli
coinlerde Binance fonlaması, SAATLİK orana çevrilmiş); trader/kadro/HL durumu okumaları (clearinghouseState, userFills, perpDexs, meta, candleSnapshot, ...) AYNEN HL'ye gider. Motor kodu bu yolla
değişmeden iki borsada çalışır; HL yürütücüsünün yolu bu modülü hiç içe aktarmaz (HL davranışı değişmez)."""
from __future__ import annotations

import math
import time
from typing import Any, Callable

from copytrade.canli.binance_eslesme import EslemeTablosu

BINANCE_REST = "https://fapi.binance.com"
ERISIM_YOK_KODLARI = (403, 451)


class BinanceErisimYok(RuntimeError):
    """403/451: sunucu konumu Binance Futures'a kapalı (kalıcı sayılır)."""


class BinanceHata(RuntimeError):
    """Geçici ağ / HTTP / ayrıştırma hatası."""


def http_get_varsayilan(url: str, params: dict | None = None, timeout: float = 8.0) -> tuple[int, str]:
    import requests
    r = requests.get(url, params=params, timeout=timeout)
    return r.status_code, r.text


def _f(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


class BinancePiyasa:
    """Önbellekli public okuyucu. `get(url, params) -> (http_kodu, metin)` enjekte edilir (testte sahte). İş parçacığı güvenli sayılır (önbellek yazımları atomik atama)."""

    def __init__(self, rules: dict, get: Callable[[str, dict | None], tuple[int, str]] | None = None, saat_ms: Callable[[], int] | None = None, taban: str = BINANCE_REST) -> None:
        self.rules = rules
        self._get = get or http_get_varsayilan
        self.saat_ms = saat_ms or (lambda: int(time.time() * 1000))
        self.taban = taban
        self.sayac = {"istek": 0, "hata": 0, "erisim_yok": 0}
        self.son_basari_ms: int | None = None
        self.ilk_hata_ms: int | None = None                  # kesinti başlangıcı (başarıyla sıfırlanır)
        self.son_hata: str = ""
        self._bilgi: tuple[int, dict] | None = None
        self._mark: tuple[int, dict] | None = None
        self._aralik: tuple[int, dict] | None = None
        self.fonlama_kaynak: str = "yok"                     # "binance" | "hl_yedek" (son metaAndAssetCtxs uyarlaması)

    # ---------------------------------------------------------------- HTTP
    def _json(self, yol: str, params: dict | None = None) -> Any:
        import json as _json
        self.sayac["istek"] += 1
        try:
            kod, metin = self._get(self.taban + yol, params)
        except Exception as hata:                            # noqa: BLE001 - ağ
            self._basarisiz(f"{type(hata).__name__}")
            raise BinanceHata(f"ağ hatası: {type(hata).__name__}") from hata
        if kod in ERISIM_YOK_KODLARI:
            self.sayac["erisim_yok"] += 1
            self._basarisiz(f"http_{kod}")
            raise BinanceErisimYok(f"HTTP {kod}: Binance Futures bu konumdan erişilemez")
        if kod != 200:
            self._basarisiz(f"http_{kod}")
            raise BinanceHata(f"HTTP {kod}")
        try:
            veri = _json.loads(metin)
        except ValueError as hata:
            self._basarisiz("json")
            raise BinanceHata("yanıt JSON değil") from hata
        self.son_basari_ms, self.ilk_hata_ms, self.son_hata = self.saat_ms(), None, ""
        return veri

    def _basarisiz(self, neden: str) -> None:
        self.sayac["hata"] += 1
        self.son_hata = neden
        if self.ilk_hata_ms is None:
            self.ilk_hata_ms = self.saat_ms()

    def kesinti_sn(self) -> float:
        """Kesintisiz başarısızlık süresi (sn); son istek başarılıysa 0."""
        return 0.0 if self.ilk_hata_ms is None else max(0.0, (self.saat_ms() - self.ilk_hata_ms) / 1000.0)

    def durum(self) -> dict:
        return {"istek": self.sayac["istek"], "hata": self.sayac["hata"], "erisim_yok": self.sayac["erisim_yok"], "kesinti_sn": round(self.kesinti_sn(), 1), "son_hata": self.son_hata,
                "son_basari_ms": self.son_basari_ms, "fonlama_kaynak": self.fonlama_kaynak}

    def _taze(self, onbellek: tuple[int, dict] | None, ttl_sn: float) -> dict | None:
        return onbellek[1] if onbellek is not None and self.saat_ms() - onbellek[0] < ttl_sn * 1000 else None

    # ---------------------------------------------------------------- exchangeInfo
    def bilgi_tablosu(self) -> dict[str, dict]:
        """sembol -> {durum, tick, step, min_qty, min_nosyonel}; yalnız USDT PERPETUAL. TTL `binance_kagit_bilgi_ttl_sn`."""
        t = self._taze(self._bilgi, float(self.rules.get("binance_kagit_bilgi_ttl_sn", 3600)))
        if t is not None:
            return t
        veri = self._json("/fapi/v1/exchangeInfo")
        tablo: dict[str, dict] = {}
        for s in veri.get("symbols") or []:
            if "PERPETUAL" not in str(s.get("contractType") or "PERPETUAL") or s.get("quoteAsset") not in (None, "USDT"):         # PERPETUAL ve (varsa) TRADIFI_PERPETUAL; vadeli (CURRENT_QUARTER...) hariç. TradFi contractType adı DOĞRULANMADI
                continue
            tick = step = min_qty = min_n = None
            for f in s.get("filters") or []:
                ft = f.get("filterType")
                if ft == "PRICE_FILTER":
                    tick = _f(f.get("tickSize"))
                elif ft == "LOT_SIZE":
                    step, min_qty = _f(f.get("stepSize")), _f(f.get("minQty"))
                elif ft == "MIN_NOTIONAL":
                    min_n = _f(f.get("notional") if f.get("notional") is not None else f.get("minNotional"))
            if s.get("symbol") and tick and step:
                tablo[str(s["symbol"])] = {"durum": str(s.get("status", "")), "tick": tick, "step": step, "min_qty": min_qty or step, "min_nosyonel": min_n or 0.0}
        if not tablo:
            raise BinanceHata("exchangeInfo boş / tanınmayan biçim")
        self._bilgi = (self.saat_ms(), tablo)
        return tablo

    def bilgi(self, sembol: str) -> dict | None:
        return self.bilgi_tablosu().get(sembol)

    # ---------------------------------------------------------------- mark + fonlama
    def mark_tablosu(self) -> dict[str, dict]:
        """sembol -> {mark, fonlama (son oran, aralık başına), sonraki_ms}. TTL `binance_kagit_mark_ttl_sn`."""
        t = self._taze(self._mark, float(self.rules.get("binance_kagit_mark_ttl_sn", 10)))
        if t is not None:
            return t
        veri = self._json("/fapi/v1/premiumIndex")
        if isinstance(veri, dict):
            veri = [veri]
        tablo: dict[str, dict] = {}
        for r in veri or []:
            mk = _f(r.get("markPrice"))
            if r.get("symbol") and mk and mk > 0:
                tablo[str(r["symbol"])] = {"mark": mk, "fonlama": _f(r.get("lastFundingRate")), "sonraki_ms": int(_f(r.get("nextFundingTime")) or 0)}
        if not tablo:
            raise BinanceHata("premiumIndex boş / tanınmayan biçim")
        self._mark = (self.saat_ms(), tablo)
        return tablo

    def fonlama_araliklari(self) -> dict[str, float]:
        """sembol -> fonlama aralığı (saat). `fundingInfo` yalnız 8 saatten farklı olanları verir; yoksa `binance_fonlama_varsayilan_saat` (8). Okunamazsa boş (varsayılan geçerli)."""
        t = self._taze(self._aralik, 3600.0)
        if t is not None:
            return t
        try:
            veri = self._json("/fapi/v1/fundingInfo")
        except BinanceErisimYok:
            raise
        except BinanceHata:
            return self._aralik[1] if self._aralik is not None else {}
        sonuc = {str(r["symbol"]): float(r["fundingIntervalHours"]) for r in (veri or []) if isinstance(r, dict) and r.get("symbol") and (_f(r.get("fundingIntervalHours")) or 0) > 0}
        self._aralik = (self.saat_ms(), sonuc)
        return sonuc

    def saatlik_fonlama(self, sembol: str, mark_tablo: dict[str, dict] | None = None) -> float | None:
        """Aralık başına son oran / aralık saati = HL biçimi SAATLİK oran (yaklaşık: gerçek Binance ödemesi 8 saatte bir; motor saatlik tahakkuk eder, toplam aynı, zamanlama farklı)."""
        m = (mark_tablo or self.mark_tablosu()).get(sembol)
        if not m or m.get("fonlama") is None:
            return None
        saat = self.fonlama_araliklari().get(sembol) or float(self.rules.get("binance_fonlama_varsayilan_saat", 8))
        return float(m["fonlama"]) / saat

    # ---------------------------------------------------------------- defter / bookTicker
    def defter(self, sembol: str) -> dict:
        """{bids: [(px, qty)] azalan, asks: [(px, qty)] artan, ms}. Boş taraf mümkündür (çağıran 'bos_defter' der)."""
        veri = self._json("/fapi/v1/depth", {"symbol": sembol, "limit": int(self.rules.get("binance_kagit_derinlik_limit", 20))})
        try:
            bids = [(float(p), float(q)) for p, q in veri["bids"] if float(q) > 0]
            asks = [(float(p), float(q)) for p, q in veri["asks"] if float(q) > 0]
        except (KeyError, TypeError, ValueError) as hata:
            self._basarisiz("depth_bicim")
            raise BinanceHata("depth yanıt biçimi") from hata
        return {"bids": sorted(bids, key=lambda x: -x[0]), "asks": sorted(asks), "ms": self.saat_ms()}

    def book_ticker(self, sembol: str) -> tuple[float, float]:
        r = self._json("/fapi/v1/ticker/bookTicker", {"symbol": sembol})
        b, a = _f(r.get("bidPrice")), _f(r.get("askPrice"))
        if not b or not a:
            raise BinanceHata("bookTicker biçimi")
        return b, a

    def erisim_testi(self) -> str:
        """'ok' | 'yok' (403/451) | 'hata' (geçici). Açılışta çağrılır: exchangeInfo + bilgi tablosu da ısınır."""
        try:
            self.bilgi_tablosu()
            return "ok"
        except BinanceErisimYok:
            return "yok"
        except BinanceHata:
            return "hata"


# -------------------------------------------------------------------------------------------------------- HL post uyarlayıcısı
def piyasa_post(hl_post: Callable[[dict], Any], piyasa: BinancePiyasa, tablo: EslemeTablosu) -> Callable[[dict], Any]:
    """Motorun `post`u (Binance kâğıt süreci). `allMids`: HL orta fiyatları taban, eşlemeli (dogrulandi) coinlerde Binance MARK (HL birimine: × carpan). Binance mark okunamazsa istisna YUKARI çıkar
    (motor `mark_okuma_hata` yazar, önceki mark'lar kalır: HL fiyatı Binance defterine karışmaz). Eşlemeli ama Binance'te olmayan (delist) coin çıktıdan düşer. `metaAndAssetCtxs`: eşlemeli coinlerde
    `funding` = Binance saatlik oran; Binance okunamazsa HL fonlaması aynen kalır ve `piyasa.fonlama_kaynak = "hl_yedek"` (kayıt/özet işaretler)."""
    def post(yuk: dict) -> Any:
        tip = yuk.get("type")
        if tip == "allMids":
            mids = dict(hl_post(yuk))
            marklar = piyasa.mark_tablosu()
            for coin in list(mids):
                esl, _ = tablo.coz(coin)
                if esl is None or not esl.dogrulandi:
                    continue
                m = marklar.get(esl.binance)
                if m is None:
                    del mids[coin]
                else:
                    mids[coin] = str(m["mark"] * esl.carpan)
            return mids
        if tip == "metaAndAssetCtxs":
            r = hl_post(yuk)
            try:
                meta, ctxs = r[0], r[1]
                marklar = piyasa.mark_tablosu()
                yeni = []
                kaynak = "binance"
                for u, c in zip(meta["universe"], ctxs):
                    c = dict(c)
                    esl, _ = tablo.coz(str(u.get("name")))
                    if esl is not None and esl.dogrulandi:
                        oran = piyasa.saatlik_fonlama(esl.binance, marklar)
                        if oran is not None:
                            c["funding"] = repr(oran)
                    yeni.append(c)
                piyasa.fonlama_kaynak = kaynak
                return [meta, yeni, *r[2:]]
            except (BinanceErisimYok, BinanceHata):
                piyasa.fonlama_kaynak = "hl_yedek"               # Binance fonlaması yok: HL değeri (işaretli kaynak)
                return r
        return hl_post(yuk)
    post.stats = getattr(hl_post, "stats", None)             # type: ignore[attr-defined]
    post.istemci = getattr(hl_post, "istemci", None)         # type: ignore[attr-defined]
    post.piyasa = piyasa                                     # type: ignore[attr-defined]
    return post
