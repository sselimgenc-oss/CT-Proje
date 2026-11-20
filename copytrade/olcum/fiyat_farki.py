"""HL ↔ Binance USDⓈ-M fiyat farkı ölçümü (Binance hazırlığı 5a; kabul ölçütü: en az 3 gün, biri hafta sonu → varsayılan 96 sa; docs/binance-arastirma.md "Fable görüşü").

Soru: trader'ın HL dolum fiyatı ile ~0,6 sn sonraki Binance fiyatı arasındaki fark, HL'deki bugünkü kaymamızdan (kayma_trader: medyan 0,4 bp, p90 6,6 bp) belirgin küçük mü?
Ayrıca sunucudan Binance'e erişilebiliyor mu (451/403)?

Bağımsız tek süreç; bot motoruna (copytrade/canli/motor.py) DOKUNMAZ, motorun dosyalarına YAZMAZ:
- Motorun durum/ ve kayit/ dizinlerini yalnız OKUR (hesap.json açık pozisyon coinleri; kayit/<gün>.jsonl `emir` olayları, kuyruk gibi: HL'ye ek abonelik açılmaz).
- Binance anahtarsız genel uç: ilk bağlantıda REST bookTicker ile erişim denenir (HTTP durum + gövde kaydı); sonra WebSocket `<sym>@bookTicker`, WS kurulamazsa REST yedek (sembol başına yoklama).
  403/451 → "erişim yok" kaydı + TEK ⚠️ Telegram + çıkış kodu 3 (yeniden deneme döngüsü yok; systemd RestartPreventExitStatus=3).
- Çıktı (ayrı alt dizin): <cikti>/<gün>.jsonl; olaylar: `baslat`, `erisim`, `fark` (her trader dolumu), `mid` (dakikada bir HL allMids ↔ Binance orta fiyat), `bitis`.
- `--ozet`: majör / altcoin / TradFi(HIP-3) grupları AYRI (n, medyan, ortalama, p90, p95), coin bazında, HL kaymamızla karşılaştırma, erişim durumu,
  sonunda otomatik değerlendirme GEÇ / GRİ / DUR (eşikler kurallar.yaml `fiyat_farki_*`, kullanıcı onayı bekliyor) → markdown (<cikti>/OZET.md + stdout).

Fark işareti: maliyet gibi, pozitif = bizim için kötü. Alışta (B) (Binance ask − trader_px) / trader_px, satışta (A) (trader_px − Binance bid) / trader_px; bp = 1e-4.
`fark_bp` = t0 + `--hedef-ms` (varsayılan 600 ms) anındaki fiyatla; `fark_t0_bp` = t0 anındaki fiyatla (borsalar arası taban fark, gecikme sürüklenmesi hariç).
Zaman: Binance örnek zamanı olay saati `E` (Binance saati; HL dolum zamanı da borsa saati). Her örnek için o anda yürürlükteki son kote alınır (en yakın GEÇMİŞ örnek); `bn_yas_ms` = örnek ile hedef anı farkı.
Bellek: sembol başına sınırlı halka tampon (zaman + adet), tek süreç.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

BINANCE_REST = "https://fapi.binance.com"
BINANCE_WS = "wss://fapi.binance.com/stream"
HL_INFO = "https://api.hyperliquid.xyz/info"
ERISIM_YOK_KODLARI = (403, 451)
CIKIS_ERISIM_YOK = 3
BP = 1e4
TAMPON_SN = 90                 # sembol başına örnek saklama süresi
TAMPON_ADET = 3000             # ... ve üst sınır (bellek)
BEKLEME_PAY_MS = 250           # hedef anından sonra bu kadar bekle (WS gecikmesi payı)
ESKI_SINIR_MS = 30_000         # bu kadar eski kote "eski" işaretlenir
YAKIN_ILERI_MS = 1_500         # geçmişte örnek yoksa ileriye bu kadar bakılır
BEKLEYEN_SINIR_MS = 60_000     # hedef anından bu kadar sonra hâlâ örnek yoksa "yok" yaz

# HIP-3 → Binance sembolü (docs/binance-arastirma.md bölüm 1b). (sembol | None, doğrulandı mı)
# Doğrulanmamışlar False: dayanak varlık / sembol eşleşmesi kesin değil. None = Binance karşılığı yok.
HIP3_ESLEME: dict[str, tuple[str | None, bool]] = {
    "xyz:NVDA": ("NVDAUSDT", True),
    "xyz:SNDK": ("SNDKUSDT", False),        # bir haber SANDUSDT diyor; döküm SNDKUSDT
    "xyz:SPCX": ("SPCXUSDT", False),        # HL tarafı bire bir mi doğrulanmadı
    "io:NVDA": ("NVDAUSDT", True),
    "xyz:GOOGL": ("GOOGLUSDT", True),
    "xyz:META": ("METAUSDT", True),
    "xyz:MSFT": ("MSFTUSDT", True),
    "xyz:AMZN": ("AMZNUSDT", True),
    "xyz:XYZ100": (None, False),            # Binance karşılığı yok / emin değil
    "xyz:BE": ("BEUSDT", False),
    "io:SNDK": ("SNDKUSDT", False),
    "xyz:MU": ("MUUSDT", True),
    "xyz:DRAM": ("DRAMUSDT", False),
    "xyz:INTC": ("INTCUSDT", True),
    "xyz:ANT": ("ANTHROPICUSDT", False),    # Anthropic pre-IPO; sembol doğrulanmadı
    "xyz:PLTR": ("PLTRUSDT", True),
    "xyz:AMD": ("AMDUSDT", True),
    "xyz:SOXL": ("SOXLUSDT", False),
}


def binance_sembol(coin: str) -> tuple[str | None, bool]:
    """HL coin → (Binance sembolü | None, doğrulandı mı). HIP-3 için sabit sözlük; bilinmeyen HIP-3 için varsayılan ad (doğrulanmamış);
    ana dex: `kXXX` → `1000XXX`, aksi aynı ad + USDT (spot/`@` → None)."""
    coin = str(coin)
    if coin in HIP3_ESLEME:
        return HIP3_ESLEME[coin]
    if coin.startswith("@") or "/" in coin:
        return None, False
    if ":" in coin:
        return coin.split(":", 1)[1].upper() + "USDT", False
    return ("1000" + coin[1:] if coin.startswith("k") and len(coin) > 1 else coin).upper() + "USDT", True


def gun(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d")


def fark_bp(yon: str, tr_px: float, bid: float, ask: float) -> float | None:
    """Yön düzeltilmiş maliyet bp'si: alışta ask, satışta bid; pozitif = bizim için kötü."""
    if not tr_px or tr_px <= 0:
        return None
    if yon == "B":
        return (ask - tr_px) / tr_px * BP
    if yon == "A":
        return (tr_px - bid) / tr_px * BP
    return None


def yuzdelik(degerler: list[float], p: float) -> float | None:
    """Doğrusal aradeğerlemeli yüzdelik (p: 0–100); boş liste → None."""
    if not degerler:
        return None
    s = sorted(degerler)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * p / 100.0
    a = int(k)
    b = min(a + 1, len(s) - 1)
    return s[a] + (s[b] - s[a]) * (k - a)


class Tampon:
    """Sembol → son kote örnekleri (ms, bid, ask), zaman sıralı; zaman ve adet sınırlı."""

    def __init__(self) -> None:
        self.d: dict[str, deque[tuple[int, float, float]]] = {}

    def ekle(self, sym: str, ms: int, bid: float, ask: float) -> None:
        q = self.d.setdefault(sym, deque(maxlen=TAMPON_ADET))
        if q and q[-1][1] == bid and q[-1][2] == ask:
            return
        if q and ms < q[-1][0]:                    # sıra dışı (REST/WS karışımı): sona ekleme, sırala
            q.append((ms, bid, ask))
            ss = sorted(q)
            q.clear()
            q.extend(ss)
        else:
            q.append((ms, bid, ask))
        sinir = q[-1][0] - TAMPON_SN * 1000
        while len(q) > 1 and q[0][0] < sinir:
            q.popleft()

    def kote(self, sym: str, ms: int) -> tuple[int, float, float] | None:
        """`ms` anında yürürlükteki kote: en yakın GEÇMİŞ örnek; yoksa `YAKIN_ILERI_MS` içindeki ilk gelecek örnek."""
        q = self.d.get(sym)
        if not q:
            return None
        onceki = None
        for o in q:
            if o[0] <= ms:
                onceki = o
            else:
                if onceki is None and o[0] - ms <= YAKIN_ILERI_MS:
                    return o
                break
        return onceki

    def son_ms(self, sym: str) -> int | None:
        q = self.d.get(sym)
        return q[-1][0] if q else None


def _yaz_satir(yol: Path, olay: dict) -> None:
    yol.parent.mkdir(parents=True, exist_ok=True)
    with yol.open("a", encoding="utf-8") as f:
        f.write(json.dumps(olay, ensure_ascii=False, separators=(",", ":")) + "\n")


class KayitKuyrugu:
    """Motorun kayit/<gün>.jsonl dosyalarını SALT OKUR (kuyruk): açılışta dosya SONUNDAN başlar, yalnız tam satırları döndürür."""

    def __init__(self, dizin: Path) -> None:
        self.dizin = Path(dizin)
        self.ofset: dict[Path, int] = {}
        self.kalan: dict[Path, bytes] = {}
        self._ilk = True

    def _yollar(self, simdi_ms: int) -> list[Path]:
        return [self.dizin / f"{gun(simdi_ms - 86_400_000)}.jsonl", self.dizin / f"{gun(simdi_ms)}.jsonl"]

    def oku(self, simdi_ms: int) -> list[dict]:
        sonuc: list[dict] = []
        for yol in self._yollar(simdi_ms):
            try:
                boyut = yol.stat().st_size
            except OSError:
                continue
            if yol not in self.ofset:
                self.ofset[yol] = boyut if self._ilk else 0      # açılışta mevcut içerik atlanır; sonradan doğan (yeni gün) dosya baştan okunur
                self.kalan[yol] = b""
                continue
            if boyut < self.ofset[yol]:
                self.ofset[yol], self.kalan[yol] = 0, b""
            if boyut == self.ofset[yol]:
                continue
            try:
                with yol.open("rb") as f:
                    f.seek(self.ofset[yol])
                    veri = f.read(min(boyut - self.ofset[yol], 8_000_000))
            except OSError:
                continue
            self.ofset[yol] += len(veri)
            tampon = self.kalan.get(yol, b"") + veri
            *satirlar, self.kalan[yol] = tampon.split(b"\n")
            for s in satirlar:
                if b'"emir"' not in s:
                    continue
                try:
                    o = json.loads(s)
                except ValueError:
                    continue
                if isinstance(o, dict) and o.get("olay") == "emir":
                    sonuc.append(o)
        self._ilk = False
        return sonuc


def baslangic_coinleri(durum_dizin: Path, kayit_dizin: Path, simdi_ms: int, ekstra: list[str] | None = None) -> list[str]:
    """Salt okuma: durum/hesap.json açık pozisyon coinleri + bugün/dün kayit `emir` coinleri + elle verilenler."""
    coinler: dict[str, None] = {}
    try:
        h = json.loads((Path(durum_dizin) / "hesap.json").read_text(encoding="utf-8"))
        for cs in (h.get("poz") or {}).values():
            for c in cs:
                coinler[str(c)] = None
    except (OSError, ValueError, AttributeError):
        pass
    for g in (gun(simdi_ms - 86_400_000), gun(simdi_ms)):
        try:
            with (Path(kayit_dizin) / f"{g}.jsonl").open("rb") as f:
                for s in f:
                    if b'"emir"' in s:
                        try:
                            o = json.loads(s)
                        except ValueError:
                            continue
                        if o.get("olay") == "emir" and o.get("coin"):
                            coinler[str(o["coin"])] = None
        except OSError:
            continue
    for c in ekstra or []:
        coinler[c] = None
    return list(coinler)


class Olcum:
    """Çekirdek (eşzamansız olmayan): örnek tamponu, bekleyen dolumlar, çıktı yazımı. Testler bunu doğrudan sürer."""

    def __init__(self, cikti_dizin: Path, hedef_ms: int = 600, saat_ms: Callable[[], int] | None = None) -> None:
        self.cikti = Path(cikti_dizin)
        self.hedef_ms = hedef_ms
        self.saat_ms = saat_ms or (lambda: int(time.time() * 1000))
        self.tampon = Tampon()
        self.coin_sym: dict[str, str | None] = {}
        self.dogrulandi: dict[str, bool] = {}
        self.bekleyen: list[dict] = []
        self.yeni_semboller: list[str] = []        # WS'e yeni abone olunacaklar (asenkron katman boşaltır)
        self.gecikme_ms: deque[int] = deque(maxlen=200)
        self.say = {"fark": 0, "ornek_yok": 0, "atlanan": 0}

    # ---- yazım
    def yaz(self, olay: dict, ms: int | None = None) -> None:
        ms = int(ms if ms is not None else self.saat_ms())
        _yaz_satir(self.cikti / f"{gun(ms)}.jsonl", {"olay_ms": ms, **olay})

    # ---- coin
    def coin_ekle(self, coin: str) -> str | None:
        if coin in self.coin_sym:
            return self.coin_sym[coin]
        sym, ok = binance_sembol(coin)
        self.coin_sym[coin], self.dogrulandi[coin] = sym, ok
        if sym and sym not in self.tampon.d:
            self.tampon.d[sym] = deque(maxlen=TAMPON_ADET)
            self.yeni_semboller.append(sym)
        return sym

    def semboller(self) -> list[str]:
        return sorted({s for s in self.coin_sym.values() if s})

    # ---- örnek
    def ornek(self, sym: str, ms: int, bid: float, ask: float, alis_ms: int | None = None) -> None:
        if not (bid > 0 and ask > 0):
            return
        self.tampon.ekle(sym, ms, bid, ask)
        if alis_ms is not None:
            self.gecikme_ms.append(int(alis_ms - ms))

    def ws_mesaj(self, ham: str | bytes, alis_ms: int) -> None:
        """Birleşik akış mesajı: {"stream": "...@bookTicker", "data": {"s","b","a","E","T"}}. Bozuk mesaj sessizce atlanır."""
        try:
            m = json.loads(ham)
            d = m.get("data", m)
            if d.get("e") not in (None, "bookTicker"):
                return
            sym, bid, ask = str(d["s"]).upper(), float(d["b"]), float(d["a"])
        except (ValueError, KeyError, TypeError, AttributeError):
            return
        try:
            ms = int(d.get("E") or d.get("T") or alis_ms)
        except (TypeError, ValueError):
            ms = alis_ms
        if abs(ms - alis_ms) > 10_000:             # Binance saati ile yerel saat çok ayrışmış: yerel alış saati
            ms = alis_ms
        self.ornek(sym, ms, bid, ask, alis_ms)

    # ---- dolum
    def emir_isle(self, o: dict) -> None:
        """Motorun `emir` olayı → bekleyen ölçüm (trader fiyatı ve zamanı varsa)."""
        try:
            t0, px = int(o["trader_dolum_ms"]), float(o["trader_px"])
        except (KeyError, TypeError, ValueError):
            self.say["atlanan"] += 1
            return
        coin, yon = str(o.get("coin") or ""), str(o.get("yon") or "")
        if not coin or yon not in ("B", "A") or px <= 0 or t0 <= 0:
            self.say["atlanan"] += 1
            return
        self.coin_ekle(coin)
        self.bekleyen.append({"o": o, "t0": t0, "px": px, "coin": coin, "yon": yon})

    def bekleyenleri_isle(self, simdi_ms: int | None = None) -> int:
        simdi = int(simdi_ms if simdi_ms is not None else self.saat_ms())
        kalan, islenen = [], 0
        for b in self.bekleyen:
            hedef = b["t0"] + self.hedef_ms
            sym = self.coin_sym.get(b["coin"])
            if sym is None:
                self._yaz_fark(b, None, None, "binance_eslesme_yok")
                islenen += 1
                continue
            if simdi < hedef + BEKLEME_PAY_MS:
                kalan.append(b)
                continue
            k600, k0 = self.tampon.kote(sym, hedef), self.tampon.kote(sym, b["t0"])
            if k600 is None and simdi < hedef + BEKLEYEN_SINIR_MS and not self.tampon.d.get(sym):
                kalan.append(b)                       # henüz hiç örnek gelmedi (yeni abonelik): kısa süre bekle
                continue
            self._yaz_fark(b, k600, k0, None if k600 else "binance_ornek_yok")
            islenen += 1
        self.bekleyen = kalan
        return islenen

    def _yaz_fark(self, b: dict, k600: tuple | None, k0: tuple | None, neden: str | None) -> None:
        o, coin, yon, px, t0 = b["o"], b["coin"], b["yon"], b["px"], b["t0"]
        sym = self.coin_sym.get(coin)
        kayma = o.get("kayma_trader")
        satir: dict[str, Any] = {
            "olay": "fark", "t0_ms": t0, "coin": coin, "sym": sym, "sym_dogrulandi": self.dogrulandi.get(coin), "yon": yon, "eylem": o.get("eylem"), "kaynak": o.get("kaynak"),
            "durum": o.get("durum"), "tr_px": px, "bizim_px": o.get("dolum_px"),
            "hl_kayma_bp": round(float(kayma) * BP, 4) if isinstance(kayma, (int, float)) else None,
            "hedef_ms": self.hedef_ms, "fark_bp": None, "fark_t0_bp": None, "neden": neden,
        }
        if k600:
            bid, ask = k600[1], k600[2]
            satir.update(fark_bp=_yuv(fark_bp(yon, px, bid, ask)), bn_bid=bid, bn_ask=ask, bn_yas_ms=(b["t0"] + self.hedef_ms) - k600[0],
                         bn_spread_bp=_yuv((ask - bid) / ((ask + bid) / 2) * BP), bn_eski=((b["t0"] + self.hedef_ms) - k600[0]) > ESKI_SINIR_MS)
        if k0:
            satir["fark_t0_bp"] = _yuv(fark_bp(yon, px, k0[1], k0[2]))
        self.say["fark" if k600 else "ornek_yok"] += 1
        self.yaz(satir, t0 + self.hedef_ms)

    # ---- mid
    def mid_yaz(self, hl_mids: dict[str, float], ms: int | None = None) -> None:
        ms = int(ms if ms is not None else self.saat_ms())
        c: dict[str, dict] = {}
        for coin, sym in self.coin_sym.items():
            hl = hl_mids.get(coin)
            k = self.tampon.kote(sym, ms) if sym else None
            if hl is None or k is None or ms - k[0] > ESKI_SINIR_MS:
                continue
            bn = (k[1] + k[2]) / 2
            c[coin] = {"hl": hl, "bn": bn, "bp": _yuv((bn - hl) / hl * BP)}
        if c:
            gk = sorted(self.gecikme_ms)
            self.yaz({"olay": "mid", "coinler": c, "ws_gecikme_ms": gk[len(gk) // 2] if gk else None}, ms)


def _yuv(x: float | None) -> float | None:
    return round(x, 4) if x is not None else None


# ---------------------------------------------------------------- ağ katmanı (testte sahte enjekte edilir)
def rest_get(url: str, params: dict | None = None, timeout: float = 10.0) -> tuple[int, str]:
    import requests
    r = requests.get(url, params=params, timeout=timeout)
    return r.status_code, r.text


def hl_post(yuk: dict) -> Any:
    import requests
    r = requests.post(HL_INFO, json=yuk, timeout=10)
    r.raise_for_status()
    return r.json()


def telegram_post_varsayilan(url: str, yuk: dict) -> dict:
    from copytrade.canli.telegram import varsayilan_post
    return varsayilan_post(url, yuk)


def telegram_uyari(metin: str, post: Callable[[str, dict], Any] | None = None, env: dict | None = None) -> bool:
    """TEK ⚠️ mesaj. Token/chat yalnız ortamdan; yoksa sessiz (False). Hata yutulur; token hiçbir yere yazılmaz."""
    e = os.environ if env is None else env
    token, chat = e.get("TELEGRAM_BOT_TOKEN"), e.get("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return False
    try:
        (post or telegram_post_varsayilan)(f"https://api.telegram.org/bot{token}/sendMessage", {"chat_id": chat, "text": f"[CT] {metin}"})
        return True
    except Exception:                                      # noqa: BLE001
        return False


def erisim_kontrol(olcum: Olcum, sym: str, get: Callable = rest_get) -> str:
    """İlk bağlantı: REST bookTicker. Dönüş: "ok" | "yok" (403/451) | "hata" (ağ hatası / başka kod; yine de WS denenir). Durum kodu + gövde kaydedilir."""
    try:
        kod, govde = get(f"{BINANCE_REST}/fapi/v1/ticker/bookTicker", {"symbol": sym})
    except Exception as e:                                 # noqa: BLE001
        olcum.yaz({"olay": "erisim", "kanal": "rest", "durum": "hata", "http": None, "tur": type(e).__name__, "sembol": sym})
        return "hata"
    durum = "ok" if kod == 200 else ("yok" if kod in ERISIM_YOK_KODLARI else "hata")
    olcum.yaz({"olay": "erisim", "kanal": "rest", "durum": durum, "http": kod, "govde": str(govde)[:300], "sembol": sym})
    if kod == 200:
        try:
            d = json.loads(govde)
            olcum.ornek(sym, int(d.get("time") or olcum.saat_ms()), float(d["bidPrice"]), float(d["askPrice"]))
        except (ValueError, KeyError, TypeError):
            pass
    return durum


class ErisimYok(Exception):
    def __init__(self, kod: int) -> None:
        super().__init__(f"HTTP {kod}")
        self.kod = kod


def _ws_durum_kodu(e: BaseException) -> int | None:
    r = getattr(e, "response", None)
    kod = getattr(r, "status_code", None)
    return kod if isinstance(kod, int) else None


async def ws_oturum(olcum: Olcum, baglan: Callable, bitis_ms: int) -> None:
    """Tek WS oturumu. `baglan(url)` async bağlam yöneticisi döndürür. 403/451 el sıkışma → ErisimYok."""
    semboller = olcum.semboller()
    akis = "/".join(f"{s.lower()}@bookTicker" for s in semboller)
    olcum.yeni_semboller.clear()
    try:
        cm = baglan(f"{BINANCE_WS}?streams={akis}")
        async with cm as ws:
            olcum.yaz({"olay": "erisim", "kanal": "ws", "durum": "ok", "http": 101, "semboller": len(semboller)})
            gonderilen = 1
            while olcum.saat_ms() < bitis_ms:
                if olcum.yeni_semboller:
                    yeni, olcum.yeni_semboller[:] = list(olcum.yeni_semboller), []
                    gonderilen += 1
                    await ws.send(json.dumps({"method": "SUBSCRIBE", "params": [f"{s.lower()}@bookTicker" for s in yeni], "id": gonderilen}))
                try:
                    ham = await asyncio.wait_for(ws.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                olcum.ws_mesaj(ham, olcum.saat_ms())
    except ErisimYok:
        raise
    except Exception as e:                                 # noqa: BLE001
        kod = _ws_durum_kodu(e)
        if kod in ERISIM_YOK_KODLARI:
            olcum.yaz({"olay": "erisim", "kanal": "ws", "durum": "yok", "http": kod})
            raise ErisimYok(kod) from e
        raise


def rest_yoklama(olcum: Olcum, get: Callable = rest_get) -> None:
    """REST yedek: izlenen her sembol için bookTicker (sembol başına tek istek)."""
    for sym in olcum.semboller():
        try:
            kod, govde = get(f"{BINANCE_REST}/fapi/v1/ticker/bookTicker", {"symbol": sym})
            if kod in ERISIM_YOK_KODLARI:
                raise ErisimYok(kod)
            if kod != 200:
                continue
            d = json.loads(govde)
            olcum.ornek(sym, olcum.saat_ms(), float(d["bidPrice"]), float(d["askPrice"]))
        except ErisimYok:
            raise
        except Exception:                                  # noqa: BLE001
            continue


async def calistir(args: argparse.Namespace, *, get: Callable = rest_get, baglan: Callable | None = None, hl: Callable = hl_post,
                   telegram: Callable[[str, dict], Any] | None = None, env: dict | None = None, saat_ms: Callable[[], int] | None = None) -> int:
    saat = saat_ms or (lambda: int(time.time() * 1000))
    olcum = Olcum(Path(args.cikti_dizin), args.hedef_ms, saat)
    simdi = saat()
    bitis = simdi + int(args.sure_saat * 3600 * 1000)
    for c in baslangic_coinleri(Path(args.durum_dizin), Path(args.kayit_dizin), simdi, args.coin):
        olcum.coin_ekle(c)
    semboller = olcum.semboller()
    olcum.yaz({"olay": "baslat", "coinler": {c: [olcum.coin_sym[c], olcum.dogrulandi[c]] for c in olcum.coin_sym}, "sure_saat": args.sure_saat, "hedef_ms": args.hedef_ms})
    if not semboller:
        semboller = ["BTCUSDT"]
        olcum.coin_ekle("BTC")
    durum = erisim_kontrol(olcum, semboller[0], get)
    if durum == "yok":
        telegram_uyari("⚠️ Binance fiyat farkı ölçümü: sunucudan Binance'e erişim yok (HTTP 403/451). Ölçüm yapılamadı, kapandı.", telegram, env)
        olcum.yaz({"olay": "bitis", "neden": "erisim_yok"})
        return CIKIS_ERISIM_YOK
    if baglan is None:
        import websockets.asyncio.client as wsc
        baglan = wsc.connect
    kuyruk = KayitKuyrugu(Path(args.kayit_dizin))
    dur = asyncio.Event()
    hata_ard = 0
    son_mid = 0
    uyari_gitti = False

    async def kuyruk_dongusu() -> None:
        while not dur.is_set():
            for o in kuyruk.oku(saat()):
                olcum.emir_isle(o)
            olcum.bekleyenleri_isle(saat())
            await asyncio.sleep(0.2)

    async def mid_dongusu() -> None:
        nonlocal son_mid
        while not dur.is_set():
            if saat() - son_mid >= 60_000:
                son_mid = saat()
                try:
                    mids: dict[str, float] = {}
                    dexler = sorted({c.split(":", 1)[0] for c in olcum.coin_sym if ":" in c})
                    for dex in ["", *dexler]:
                        r = await asyncio.to_thread(hl, {"type": "allMids", **({"dex": dex} if dex else {})})
                        for k, v in (r or {}).items():
                            try:
                                mids[k] = float(v)
                            except (TypeError, ValueError):
                                pass
                    olcum.mid_yaz(mids, saat())
                except Exception as e:                    # noqa: BLE001
                    olcum.yaz({"olay": "mid_hata", "tur": type(e).__name__})
            await asyncio.sleep(1.0)

    async def binance_dongusu() -> int:
        nonlocal hata_ard, uyari_gitti
        while saat() < bitis and not dur.is_set():
            try:
                await ws_oturum(olcum, baglan, bitis)
                hata_ard = 0
            except ErisimYok as e:
                if not uyari_gitti:
                    uyari_gitti = True
                    telegram_uyari(f"⚠️ Binance fiyat farkı ölçümü: WebSocket erişimi yok (HTTP {e.kod}). Ölçüm yapılamadı, kapandı.", telegram, env)
                olcum.yaz({"olay": "bitis", "neden": "erisim_yok"})
                return CIKIS_ERISIM_YOK
            except Exception as e:                        # noqa: BLE001
                hata_ard += 1
                olcum.yaz({"olay": "ws_hata", "tur": type(e).__name__, "ardisik": hata_ard})
                if hata_ard >= 3:                         # REST yedek: 5 dk yokla, sonra WS'i yeniden dene
                    olcum.yaz({"olay": "rest_yedek", "sure_s": 300})
                    t_son = saat() + 300_000
                    while saat() < min(t_son, bitis) and not dur.is_set():
                        try:
                            await asyncio.to_thread(rest_yoklama, olcum, get)
                        except ErisimYok as e2:
                            olcum.yaz({"olay": "bitis", "neden": "erisim_yok", "http": e2.kod})
                            return CIKIS_ERISIM_YOK
                        await asyncio.sleep(1.0)
                    if hata_ard >= 12:
                        olcum.yaz({"olay": "bitis", "neden": "ws_kurulamadi"})
                        return 1
                else:
                    await asyncio.sleep(min(30.0, 2.0 ** hata_ard))
        return 0

    gorevler = [asyncio.create_task(kuyruk_dongusu()), asyncio.create_task(mid_dongusu())]
    ana = asyncio.create_task(binance_dongusu())
    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, ana.cancel)
            except (NotImplementedError, RuntimeError):
                pass
    except RuntimeError:
        pass
    kod = 0
    try:
        kod = await ana
    except asyncio.CancelledError:
        kod = 0
    finally:
        dur.set()
        for g in gorevler:
            g.cancel()
        olcum.bekleyenleri_isle(saat() + 10_000)
        if kod == 0:
            olcum.yaz({"olay": "bitis", "neden": "sure_doldu_ya_da_durduruldu", **olcum.say})
    return kod


# ---------------------------------------------------------------- özet
def _satirlari_oku(dizin: Path, gunler: list[str] | None = None) -> list[dict]:
    sonuc: list[dict] = []
    for yol in sorted(Path(dizin).glob("????-??-??.jsonl")):
        if gunler and yol.stem not in gunler:
            continue
        try:
            for s in yol.read_text(encoding="utf-8").splitlines():
                try:
                    o = json.loads(s)
                except ValueError:
                    continue
                if isinstance(o, dict):
                    sonuc.append(o)
        except OSError:
            continue
    return sonuc


def _f(x: float | None, n: int = 2) -> str:
    return "-" if x is None else f"{x:.{n}f}"


def _istat(v: list[float]) -> dict:
    mut = [abs(x) for x in v]
    return {"n": len(v), "med": yuzdelik(v, 50), "p90": yuzdelik(v, 90), "p95": yuzdelik(v, 95), "p99": yuzdelik(v, 99), "ort": (sum(v) / len(v)) if v else None,
            "mut_med": yuzdelik(mut, 50), "mut_p90": yuzdelik(mut, 90)}


MAJORLER = frozenset({"BTC", "ETH", "SOL", "XRP", "BNB"})
GRUP_ADLARI = {"majör": "Majör (BTC, ETH, SOL, XRP, BNB)", "altcoin": "Altcoin", "tradfi": "TradFi (HIP-3: xyz:/io:)"}


def grup_adi(coin: str) -> str:
    """majör (sabit liste) | tradfi (HIP-3, `dex:` önekli) | altcoin (kalan)."""
    if ":" in coin:
        return "tradfi"
    return "majör" if coin.upper() in MAJORLER else "altcoin"


ESIK_VARSAYILAN = {"fiyat_farki_gec_medyan_bp": 1.0, "fiyat_farki_gec_p90_bp": 10.0, "fiyat_farki_gec_ortalama_bp": 1.5, "fiyat_farki_dur_medyan_bp": 2.0,
                   "fiyat_farki_dur_p90_bp": 15.0, "fiyat_farki_dur_ortalama_bp": 3.0, "fiyat_farki_min_dolum": 300, "fiyat_farki_min_gun": 3,
                   "fiyat_farki_min_coin": 15, "fiyat_farki_grup_min_dolum": 30}


def esikler(rules: dict | None = None) -> dict:
    """kurallar.yaml `fiyat_farki_*` anahtarları (yoksa varsayılan). KULLANICI ONAYI BEKLENİYOR."""
    if rules is None:
        try:
            from copytrade.kurallar import load_rules
            rules = load_rules()
        except Exception:                                  # noqa: BLE001
            rules = {}
    return {k: type(v)(rules.get(k, v)) for k, v in ESIK_VARSAYILAN.items()}


def siniflandir(i: dict, e: dict, min_n: int | None = None) -> str:
    """İstatistik sözlüğü (`_istat`) → "KARAR YOK" (n < asgari) | "DUR" | "GEÇ" | "GRİ". DUR önce: herhangi bir DUR koşulu yeterli."""
    if i["n"] < (e["fiyat_farki_grup_min_dolum"] if min_n is None else min_n) or i["med"] is None:
        return "KARAR YOK"
    if i["med"] > e["fiyat_farki_dur_medyan_bp"] or i["p90"] > e["fiyat_farki_dur_p90_bp"] or i["ort"] > e["fiyat_farki_dur_ortalama_bp"]:
        return "DUR"
    if i["med"] <= e["fiyat_farki_gec_medyan_bp"] and i["p90"] <= e["fiyat_farki_gec_p90_bp"] and i["ort"] <= e["fiyat_farki_gec_ortalama_bp"]:
        return "GEÇ"
    return "GRİ"


def degerlendir(i: dict, n_dolum: int, n_gun: int, n_coin: int, e: dict) -> str:
    """Genel hüküm: asgari örnek (dolum, gün, coin) sağlanmadıysa "ÖRNEK YETERSİZ", yoksa `siniflandir`."""
    if n_dolum < e["fiyat_farki_min_dolum"] or n_gun < e["fiyat_farki_min_gun"] or n_coin < e["fiyat_farki_min_coin"]:
        return "ÖRNEK YETERSİZ"
    return siniflandir(i, e, 1)


def ozet_hazirla(satirlar: list[dict], e: dict | None = None) -> dict:
    e = e or esikler()
    fark = [s for s in satirlar if s.get("olay") == "fark"]
    ok = [s for s in fark if s.get("fark_bp") is not None]
    erisim = [s for s in satirlar if s.get("olay") == "erisim"]
    son_erisim = erisim[-1] if erisim else None
    ilk_rest = next((e for e in erisim if e.get("kanal") == "rest"), None)
    yok = any(e.get("durum") == "yok" for e in erisim)
    coinler: dict[str, dict] = {}
    for c in sorted({s["coin"] for s in fark}):
        sc = [s for s in ok if s["coin"] == c]
        coinler[c] = {"n": len([s for s in fark if s["coin"] == c]), "olculen": len(sc), "fark": _istat([s["fark_bp"] for s in sc]),
                      "hl": _istat([s["hl_kayma_bp"] for s in sc if s.get("hl_kayma_bp") is not None]),
                      "spread_med": yuzdelik([s["bn_spread_bp"] for s in sc if s.get("bn_spread_bp") is not None], 50),
                      "sym": sc[0]["sym"] if sc else next((s["sym"] for s in fark if s["coin"] == c), None),
                      "dogrulandi": next((s.get("sym_dogrulandi") for s in fark if s["coin"] == c), None)}
    ayni = [s for s in ok if s.get("hl_kayma_bp") is not None]
    gruplar = {}
    for g in GRUP_ADLARI:
        sg = [s for s in ok if grup_adi(s["coin"]) == g]
        ig = _istat([s["fark_bp"] for s in sg])
        gruplar[g] = {**ig, "coin": len({s["coin"] for s in sg}), "hl_med": yuzdelik([s["hl_kayma_bp"] for s in sg if s.get("hl_kayma_bp") is not None], 50), "hukum": siniflandir(ig, e)}
    n_gun, n_coin = len({gun(int(s["t0_ms"])) for s in ok if s.get("t0_ms")}), len({s["coin"] for s in ok})
    genel = _istat([s["fark_bp"] for s in ok])
    mid: dict[str, list[float]] = {}
    for s in satirlar:
        if s.get("olay") == "mid":
            for c, v in (s.get("coinler") or {}).items():
                if v.get("bp") is not None:
                    mid.setdefault(c, []).append(v["bp"])
    gecikme = [s["ws_gecikme_ms"] for s in satirlar if s.get("olay") == "mid" and s.get("ws_gecikme_ms") is not None]
    neden: dict[str, int] = {}
    for s in fark:
        if s.get("neden"):
            neden[s["neden"]] = neden.get(s["neden"], 0) + 1
    return {
        "erisim": {"yok": yok, "ilk_rest": ilk_rest, "son": son_erisim},
        "dolum_sayisi": len(fark), "olculen": len(ok), "nedenler": neden,
        "fark": _istat([s["fark_bp"] for s in ok]), "fark_t0": _istat([s["fark_t0_bp"] for s in fark if s.get("fark_t0_bp") is not None]),
        "hl_tum": _istat([s["hl_kayma_bp"] for s in fark if s.get("hl_kayma_bp") is not None]),
        "hl_ayni": _istat([s["hl_kayma_bp"] for s in ayni]), "fark_ayni": _istat([s["fark_bp"] for s in ayni]),
        "gruplar": gruplar, "esikler": e, "n_gun": n_gun, "n_coin": n_coin, "hukum": degerlendir(genel, len(ok), n_gun, n_coin, e),
        "coinler": coinler, "mid": {c: _istat(v) for c, v in sorted(mid.items())},
        "ws_gecikme_med": yuzdelik([float(g) for g in gecikme], 50),
        "ilk_ms": min((s.get("olay_ms", 0) for s in satirlar), default=None), "son_ms": max((s.get("olay_ms", 0) for s in satirlar), default=None),
    }


def ozet_markdown(o: dict, simdi_ms: int | None = None) -> str:
    sat: list[str] = []
    ek = o["erisim"]
    simdi = simdi_ms if simdi_ms is not None else int(time.time() * 1000)
    sat.append("# HL ↔ Binance fiyat farkı ölçümü: özet")
    sat.append("")
    sat.append(f"Üretildi: {datetime.fromtimestamp(simdi / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC. Birim bp (0,01 %); pozitif = bizim için kötü (alışta Binance ask, satışta bid).")
    sat.append("")
    sat.append("## Erişim")
    ilk = ek.get("ilk_rest")
    if ilk is None:
        sat.append("- Erişim kaydı yok (ölçüm hiç başlamadı).")
    else:
        sat.append(f"- İlk REST denemesi: **{ilk.get('durum')}**, HTTP {ilk.get('http')}" + (f", gövde: `{str(ilk.get('govde'))[:120]}`" if ilk.get("durum") != "ok" else ""))
    if ek.get("yok"):
        sat.append("- **Binance'e erişim YOK (403/451)**; ölçüm yapılamadı.")
    elif ek.get("son"):
        sat.append(f"- Son erişim kaydı: {ek['son'].get('kanal')} {ek['son'].get('durum')} (HTTP {ek['son'].get('http')}).")
    if o.get("ws_gecikme_med") is not None:
        sat.append(f"- WS gecikmesi (yerel alış − Binance olay saati) medyan: {o['ws_gecikme_med']:.0f} ms.")
    sat.append("")
    sat.append("## Genel")
    sat.append(f"- Trader dolumu: {o['dolum_sayisi']}; Binance fiyatı ile ölçülen: {o['olculen']}" + (f"; ölçülemeyenler: {', '.join(f'{k}={v}' for k, v in o['nedenler'].items())}" if o["nedenler"] else ""))
    sat.append("")
    sat.append("| Ölçüt | n | medyan | p90 | p99 | ortalama | |medyan| | |p90| |")
    sat.append("|---|---|---|---|---|---|---|---|")
    for ad, k in (("Binance farkı, t0+hedef (fark_bp)", "fark"), ("Binance farkı, t0 anı (fark_t0_bp)", "fark_t0"), ("HL kaymamız, aynı dolumlar", "hl_ayni"), ("HL kaymamız, tüm dolumlar", "hl_tum")):
        i = o[k]
        sat.append(f"| {ad} | {i['n']} | {_f(i['med'])} | {_f(i['p90'])} | {_f(i['p99'])} | {_f(i['ort'])} | {_f(i['mut_med'])} | {_f(i['mut_p90'])} |")
    sat.append("")
    fm, hm, f9, h9 = o["fark_ayni"]["med"], o["hl_ayni"]["med"], o["fark_ayni"]["p90"], o["hl_ayni"]["p90"]
    sat.append(f"Karşılaştırma (aynı dolumlar, n={o['fark_ayni']['n']}): Binance farkı medyan {_f(fm)} bp / p90 {_f(f9)} bp; HL kaymamız medyan {_f(hm)} bp / p90 {_f(h9)} bp (referans: medyan 0,4 / p90 6,6). "
               f"Oran Binance/HL: medyan {_f(fm / hm if fm is not None and hm else None)}x, p90 {_f(f9 / h9 if f9 is not None and h9 else None)}x. Yorum bu belgede yapılmaz.")
    sat.append("")
    sat.append("## Gruplar (yön düzeltilmiş bp, aleyhimize +)")
    sat.append("")
    sat.append("| Grup | coin | n | medyan | ortalama | p90 | p95 | HL kayma medyan | Hüküm |")
    sat.append("|---|---|---|---|---|---|---|---|---|")
    for g, ad in GRUP_ADLARI.items():
        v = o["gruplar"][g]
        sat.append(f"| {ad} | {v['coin']} | {v['n']} | {_f(v['med'])} | {_f(v['ort'])} | {_f(v['p90'])} | {_f(v['p95'])} | {_f(v['hl_med'])} | {v['hukum']} |")
    sat.append("")
    sat.append(f"\"KARAR YOK\": grupta {o['esikler']['fiyat_farki_grup_min_dolum']}'dan az ölçülmüş dolum.")
    sat.append("")
    sat.append("## Coin bazında")
    sat.append("")
    sat.append("| Coin | Binance sembolü | n | ölçülen | fark medyan | fark p90 | HL kayma medyan | HL kayma p90 | Binance spread medyan |")
    sat.append("|---|---|---|---|---|---|---|---|---|")
    for c, v in o["coinler"].items():
        sembol = (v["sym"] or "yok") + ("" if v["dogrulandi"] else " (doğrulanmadı)")
        sat.append(f"| {c} | {sembol} | {v['n']} | {v['olculen']} | {_f(v['fark']['med'])} | {_f(v['fark']['p90'])} | {_f(v['hl']['med'])} | {_f(v['hl']['p90'])} | {_f(v['spread_med'])} |")
    sat.append("")
    if o["mid"]:
        sat.append("## Dakikalık orta fiyat farkı (Binance mid − HL mid, işaretli bp)")
        sat.append("")
        sat.append("| Coin | n | medyan | p90 | |medyan| | |p90| |")
        sat.append("|---|---|---|---|---|---|")
        for c, i in o["mid"].items():
            sat.append(f"| {c} | {i['n']} | {_f(i['med'])} | {_f(i['p90'])} | {_f(i['mut_med'])} | {_f(i['mut_p90'])} |")
        sat.append("")
    e = o["esikler"]
    sat.append("## Otomatik değerlendirme")
    sat.append("")
    sat.append(f"- Ölçüt (kurallar.yaml `fiyat_farki_*`; kullanıcı onayı bekliyor): GEÇ = medyan ≤ {e['fiyat_farki_gec_medyan_bp']} bp VE p90 ≤ {e['fiyat_farki_gec_p90_bp']} bp VE ortalama ≤ {e['fiyat_farki_gec_ortalama_bp']} bp; "
               f"DUR = medyan > {e['fiyat_farki_dur_medyan_bp']} VEYA p90 > {e['fiyat_farki_dur_p90_bp']} VEYA ortalama > {e['fiyat_farki_dur_ortalama_bp']} bp; arası GRİ.")
    sat.append(f"- Asgari örnek: ≥{e['fiyat_farki_min_dolum']} eşleşmiş dolum (var: {o['olculen']}), ≥{e['fiyat_farki_min_gun']} gün (var: {o['n_gun']}), ≥{e['fiyat_farki_min_coin']} coin (var: {o['n_coin']}).")
    sat.append(f"- **Genel hüküm (tüm gruplar birlikte): {o['hukum']}**")
    for g, ad in GRUP_ADLARI.items():
        sat.append(f"- {ad}: {o['gruplar'][g]['hukum']} (n={o['gruplar'][g]['n']})")
    return "\n".join(sat) + "\n"


def ozet_yaz(cikti_dizin: Path, gunler: list[str] | None = None) -> str:
    md = ozet_markdown(ozet_hazirla(_satirlari_oku(cikti_dizin, gunler)))
    Path(cikti_dizin).mkdir(parents=True, exist_ok=True)
    (Path(cikti_dizin) / "OZET.md").write_text(md, encoding="utf-8")
    return md


def ana(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="HL ↔ Binance fiyat farkı ölçümü (salt okur; motora dokunmaz)")
    p.add_argument("--durum-dizin", default="durum")
    p.add_argument("--kayit-dizin", default="kayit")
    p.add_argument("--cikti-dizin", default="durum/olcum/fiyat_farki")
    p.add_argument("--sure-saat", type=float, default=96.0)
    p.add_argument("--hedef-ms", type=int, default=600)
    p.add_argument("--coin", action="append", default=[], help="ek HL coin (tekrarlanabilir)")
    p.add_argument("--ozet", action="store_true", help="çıktıdan markdown özet üret (<cikti>/OZET.md + stdout) ve çık")
    p.add_argument("--gun", action="append", help="özet için yalnız bu gün(ler) YYYY-AA-GG")
    a = p.parse_args(argv)
    if a.ozet:
        sys.stdout.write(ozet_yaz(Path(a.cikti_dizin), a.gun))
        return 0
    return asyncio.run(calistir(a))


if __name__ == "__main__":
    sys.exit(ana())
