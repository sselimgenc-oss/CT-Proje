"""Yürütücü: ortak arayüz `emir(coin, yon, usd, reduce_only, acik_sz) -> Dolum`; iki arka uç (K‑29, docs/GOREV_T4 §1).

- `SanalYurutucu`: cüzdan YOK. Emir anında HL `l2Book` alınır, bizim tutarımızla defter yürünür (IOC: en iyi karşı fiyat ± `canli_ioc_bant` bandı dışındaki kısım dolmaz), dolum fiyatı = yürünen
  ortalama, ücret = taker (`maliyet_taker`; kayma ayrıca eklenmez: defter yürüyüşü kaymayı zaten taşır).
- `GercekYurutucu`: HL resmi Python SDK; coin başına İZOLE 3x, IOC limit, azaltma/kapama reduce‑only; dolmayan kısım yeniden denenmez. Anahtar YALNIZ ortam değişkeninden; yoksa kurulamaz.
  Bu modül gerçek kipi KURAR ve testle (sahte `exchange`) sınar; ÇALIŞTIRMAZ (Actions'ta asla; T5'te sunucuda, kullanıcı onayıyla).

Birimler: `usd` kasa ölçeğinde $ (nosyonel), `sz` coin miktarı (işaretsiz; yön `yon`: `B` alış / `A` satış), `px` $/coin, `kayma_oran` = (dolum − referans) / referans, ALIŞTA pozitif = kötü (satışta işaret çevrilir).
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from copytrade.kurallar import load_rules

TIF_IOC = {"limit": {"tif": "Ioc"}}


@dataclass
class Dolum:
    coin: str
    yon: str                      # B | A
    usd_istenen: float
    usd_dolan: float = 0.0
    sz: float = 0.0
    px: float | None = None       # yürünen ortalama fiyat
    ucret: float = 0.0            # $ (taker)
    referans_px: float | None = None      # en iyi karşı fiyat (emir anı)
    kayma_oran: float | None = None
    reduce_only: bool = False
    durum: str = "dolmadi"        # dolu | kismi | dolmadi | red
    neden: str = ""
    ham: dict = field(default_factory=dict)

    @property
    def dolu_mu(self) -> bool:
        return self.sz > 0


class Yurutucu(Protocol):
    kip: str

    def emir(self, coin: str, yon: str, usd: float, reduce_only: bool = False, acik_sz: float | None = None) -> Dolum: ...
    def hazirla(self, coin: str) -> None: ...


def _sayi(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def kayma(yon: str, referans: float | None, dolum_px: float | None) -> float | None:
    """İşaretli kayma: alışta (dolum − referans) / referans, satışta (referans − dolum) / referans → pozitif = bizim aleyhimize."""
    if not referans or not dolum_px:
        return None
    ham = (dolum_px - referans) / referans
    return ham if yon == "B" else -ham


def defter_yuru(seviyeler: list[dict], yon: str, usd: float, bant: float, acik_sz: float | None = None) -> tuple[float, float, float]:
    """Karşı defteri yürür. `seviyeler`: karşı taraf (alışta ask artan, satışta bid azalan) [{px, sz}]. En iyi fiyattan ± `bant` dışındaki seviye dolmaz.
    Döner (sz, usd_dolan, referans_px = en iyi karşı fiyat). `acik_sz`: reduce‑only tavanı (coin; None = sınırsız)."""
    if not seviyeler:
        return 0.0, 0.0, 0.0
    en_iyi = float(seviyeler[0]["px"])
    sinir = en_iyi * (1 + bant) if yon == "B" else en_iyi * (1 - bant)
    kalan_usd = float(usd)
    sz_kalan = math.inf if acik_sz is None else max(0.0, float(acik_sz))
    toplam_sz = toplam_usd = 0.0
    for s in seviyeler:
        px, sz = float(s["px"]), float(s["sz"])
        if (yon == "B" and px > sinir + 1e-12) or (yon == "A" and px < sinir - 1e-12) or kalan_usd <= 1e-9 or sz_kalan <= 1e-15:
            break
        al = min(sz, kalan_usd / px, sz_kalan)
        toplam_sz += al
        toplam_usd += al * px
        kalan_usd -= al * px
        sz_kalan -= al
    return toplam_sz, toplam_usd, en_iyi


class SanalYurutucu:
    """Cüzdansız yürütme: `post` = HL info (`l2Book`); defterin kendisi tüketilmez (yalnız hesap)."""
    kip = "sanal"

    def __init__(self, post: Callable[[dict], Any], rules: dict | None = None) -> None:
        self.post = post
        self.rules = rules or load_rules()

    def hazirla(self, coin: str) -> None:
        return None                                   # izole 3x marj hesabı defterde (hesap.py); borsa ayarı yok

    def emir(self, coin: str, yon: str, usd: float, reduce_only: bool = False, acik_sz: float | None = None) -> Dolum:
        d = Dolum(coin, yon, float(usd), reduce_only=reduce_only)
        try:
            kitap = self.post({"type": "l2Book", "coin": coin})
            bids, asks = kitap["levels"][0], kitap["levels"][1]
        except Exception as hata:                      # noqa: BLE001 - defter okunamadı: emir YOK (uydurma fiyat yok)
            d.durum, d.neden = "red", f"l2Book okunamadi: {type(hata).__name__}"
            return d
        sz, dolan, referans = defter_yuru(asks if yon == "B" else bids, yon, usd, float(self.rules["canli_ioc_bant"]), acik_sz if reduce_only else None)
        d.referans_px = referans or None
        if sz <= 0:
            d.neden = "band_disi_ya_da_bos_defter"
            return d
        d.sz, d.usd_dolan, d.px = sz, dolan, dolan / sz
        d.ucret = dolan * float(self.rules["maliyet_taker"])
        d.kayma_oran = kayma(yon, referans, d.px)
        d.durum = "dolu" if dolan >= usd - 1e-6 else "kismi"
        return d


class AnahtarYok(RuntimeError):
    """Gerçek kip için ortam değişkenleri eksik: motor BAŞLAMAZ."""


def tick_yuvarla(px: float, sz_decimals: int) -> float:
    """HL perp fiyat kuralı: en çok 5 anlamlı basamak ve en çok (6 − szDecimals) ondalık."""
    return round(float(f"{px:.5g}"), max(0, 6 - int(sz_decimals)))


class GercekYurutucu:
    """HL resmi SDK ile emir. `exchange`: `hyperliquid.exchange.Exchange` benzeri (`update_leverage`, `order`); `post`: info. Testte sahte nesneler verilir."""
    kip = "gercek"

    def __init__(self, exchange: Any, post: Callable[[dict], Any], rules: dict | None = None) -> None:
        self.exchange, self.post = exchange, post
        self.rules = rules or load_rules()
        self._sz_dec: dict[str, int] | None = None
        self._ayarli: set[str] = set()

    def _sz_decimals(self, coin: str) -> int:
        if self._sz_dec is None:
            meta = self.post({"type": "meta"})
            self._sz_dec = {u["name"]: int(u["szDecimals"]) for u in meta["universe"]}
        return self._sz_dec[coin]

    def hazirla(self, coin: str) -> None:
        """Coin başına izole marj + `canli_marj_kaldirac`x (ilk emirden önce, bir kez)."""
        if coin in self._ayarli:
            return
        yanit = self.exchange.update_leverage(int(self.rules["canli_marj_kaldirac"]), coin, False)        # is_cross=False → izole
        if not isinstance(yanit, dict) or yanit.get("status") != "ok":
            raise RuntimeError(f"update_leverage reddedildi: {coin}")
        self._ayarli.add(coin)

    def emir(self, coin: str, yon: str, usd: float, reduce_only: bool = False, acik_sz: float | None = None) -> Dolum:
        d = Dolum(coin, yon, float(usd), reduce_only=reduce_only)
        try:
            self.hazirla(coin)
            kitap = self.post({"type": "l2Book", "coin": coin})
            seviyeler = kitap["levels"][1 if yon == "B" else 0]
            en_iyi = float(seviyeler[0]["px"])
            bant = float(self.rules["canli_ioc_bant"])
            limit = tick_yuvarla(en_iyi * (1 + bant) if yon == "B" else en_iyi * (1 - bant), self._sz_decimals(coin))
            sz = round(float(usd) / en_iyi, self._sz_decimals(coin))
            if reduce_only and acik_sz is not None:
                sz = min(sz, round(abs(acik_sz), self._sz_decimals(coin)))
            if sz <= 0:
                d.durum, d.neden = "red", "sz_sifir"
                return d
            d.referans_px = en_iyi
            yanit = self.exchange.order(coin, yon == "B", sz, limit, TIF_IOC, reduce_only)
        except Exception as hata:                      # noqa: BLE001 - SDK/ağ hatası kaydedilir, motor çökmez
            d.durum, d.neden = "red", f"sdk_hatasi: {type(hata).__name__}"
            return d
        d.ham = yanit if isinstance(yanit, dict) else {"yanit": str(yanit)[:200]}
        try:
            durum = yanit["response"]["data"]["statuses"][0]
        except (KeyError, IndexError, TypeError):
            d.durum, d.neden = "red", "yanit_bicimi"
            return d
        if "filled" in durum:
            d.sz, d.px = float(durum["filled"]["totalSz"]), float(durum["filled"]["avgPx"])
            d.usd_dolan = d.sz * d.px
            d.ucret = d.usd_dolan * float(self.rules["maliyet_taker"])             # tahmini; kesin ücret `userFills` / mutabakattan
            d.kayma_oran = kayma(yon, en_iyi, d.px)
            d.durum = "dolu" if d.usd_dolan >= usd * 0.999 else "kismi"
        elif "error" in durum:
            d.durum, d.neden = "red", str(durum["error"])[:160]
        else:
            d.durum, d.neden = "dolmadi", "dolmadi"                                  # IOC: resting olmamalı; yeniden denenmez
        return d


def gercek_yurutucu_olustur(post: Callable[[dict], Any], rules: dict | None = None, ortam: dict | None = None) -> GercekYurutucu:
    """Anahtarları ortamdan okur (`HL_API_CUZDAN_ANAHTARI` = para çekme yetkisiz API cüzdanı, `HL_HESAP_ADRESI` = ana hesap, açık). Biri yoksa `AnahtarYok`. SDK içe aktarması burada (tembel):
    testte kullanılmaz. ANAHTAR ASLA günlüğe/ayrıntıya yazılmaz."""
    ortam = os.environ if ortam is None else ortam
    anahtar, hesap = (ortam.get("HL_API_CUZDAN_ANAHTARI") or "").strip(), (ortam.get("HL_HESAP_ADRESI") or "").strip()
    if not anahtar or not hesap:
        raise AnahtarYok("HL_API_CUZDAN_ANAHTARI ve HL_HESAP_ADRESI gerekli (gercek kip)")
    try:
        from eth_account import Account
        from hyperliquid.exchange import Exchange
        from hyperliquid.utils import constants
    except ImportError as hata:
        raise RuntimeError("hyperliquid-python-sdk kurulmalı: pip install -r requirements-canli.txt") from hata
    return GercekYurutucu(Exchange(Account.from_key(anahtar), constants.MAINNET_API_URL, account_address=hesap), post, rules)
