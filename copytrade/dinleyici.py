"""H2 — anlık dinleyici (dry-run). docs/GOREV_H2_DINLEYICI.md, K-17/K-18.

YALNIZ halka açık Hyperliquid verisi: emir, anahtar, cüzdan, imza kodu YOK; sunucuda secret yok. Ölçülen: algılama gecikmesi (dolum zamanı -> bizim aldığımız an),
kaçan dolum (REST ile karşılaştırma), kopma / yeniden bağlanma / yeniden başlama. Çıktı: saatlik `ozet.json` (adres yok, yalnız takma ad).

Kaynaklar: BİRİNCİL `trades` kanalı (coin başına; her işlemde `users: [alıcı, satıcı]`, izlenen adresler bu alandan süzülür); ÇAPRAZ KONTROL `userFills`
(ilk `userfills_adet` adres; HL IP başına kullanıcıya özgü abonelikte sınır koyabilir); HAKEM her 10 dk REST `userFillsByTime`: REST'te olup dinleyicinin görmediği = kaçan.
Aynı dolum iki kanaldan gelirse tek sayılır (`{adres}:{tid}`); `isSnapshot` (abonelikte gelen geçmiş) dolumları kabul ve gecikmeden ayrı sayılır.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import re
import signal
import statistics
import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

from copytrade.hl_public_adapter import DEFAULT_INFO_URL, DEFAULT_WS_URL, HyperliquidPublicAdapter
from copytrade.izleme_liste import load_list, perp_dex_names

REST_SAYFA = 2000                      # userFillsByTime tek yanıtta en çok bu kadar dolum döner (API sınırı; eşik değil)
ADRES = re.compile(r"0x[0-9a-fA-F]{40}")
SAAT_MS = 3_600_000


# ------------------------------------------------------------------------------------------------ liste ve istatistik
@dataclass(frozen=True)
class Izlenen:
    ad: str          # takma ad (özette görünen); adres özete ASLA yazılmaz
    adres: str       # küçük harf


def liste_oku(yol: Path) -> list[Izlenen]:
    """İzleme listesi (K-12.8: ilk11 / yedek11 / paf + referans kolları; `izleme_motoru.load_list` yeniden kullanılır). Dosya yok ya da boşsa BAŞLAMAZ (fail-closed)."""
    if not yol.is_file():
        raise ValueError(f"izleme listesi yok: {yol} (fail-closed)")
    satirlar = load_list(yol)
    if not satirlar:
        raise ValueError("izleme listesi boş (fail-closed)")
    adlar = [r["takma_ad"] for r in satirlar]
    return [Izlenen(r["takma_ad"] if adlar.count(r["takma_ad"]) == 1 else f"{r['takma_ad']}-{r['id']}", r["adres"].lower()) for r in satirlar]


def p_sira(degerler: list[float], q: float) -> float | None:
    """En yakın sıra yöntemi: sıra = ceil(q · n), değer = sıralı listenin o sırasındaki elemanı (q=0,95: [0,4; 0,6; 1,0; 2,0; 5,0] -> 5,0)."""
    if not degerler:
        return None
    sirali = sorted(degerler)
    return sirali[max(1, math.ceil(q * len(sirali))) - 1]


@dataclass
class TraderOlcum:
    gecikme: list[float] = field(default_factory=list)      # saniye
    kacan: int = 0
    snapshot: int = 0
    negatif: int = 0                                          # alma anı < dolum zamanı (saat kayması); gecikme örneğine GİRMEZ
    kacan_sinif: dict[str, int] = field(default_factory=dict)  # REST'te olup görülmeyen: sınıf -> adet (spot | hip3 | abonesiz_perp | gercek); `kacan` = gercek

    def ozet(self) -> dict[str, Any]:
        g = self.gecikme
        return {"n": len(g), "gecikme_medyan_sn": None if not g else round(statistics.median(g), 3),
                "gecikme_p95_sn": None if not g else round(p_sira(g, 0.95), 3), "gecikme_max_sn": None if not g else round(max(g), 3),
                "kacan": self.kacan, "kacan_sinif": dict(sorted(self.kacan_sinif.items())), "snapshot": self.snapshot, "negatif_gecikme": self.negatif}


@dataclass(frozen=True)
class Olay:
    kimlik: str
    ad: str
    adres: str
    zaman_ms: int
    alma_ms: int
    kaynak: str          # trades | userFills | rest
    snapshot: bool = False
    abone: str = ""      # abonelik anahtarı: trades için coin, userFills için "userFills:<adres>" (abonelikten ÖNCEKİ dolum = canlı değil)


def _tam_sayi(deger: Any) -> int | None:
    try:
        return int(deger)
    except (TypeError, ValueError):
        return None


def trades_olaylari(mesaj: dict, izlenen: dict[str, Izlenen], alma_ms: int) -> list[Olay]:
    """`trades` kanalı: her işlemdeki `users: [alıcı, satıcı]` içinden izlenen adresler. Bir işlem iki izlenen adresi de içeriyorsa iki olay."""
    cikti = []
    for t in mesaj.get("data") or []:
        users, tid, zaman = t.get("users"), t.get("tid"), _tam_sayi(t.get("time"))
        if not isinstance(users, list) or tid is None or zaman is None:
            continue
        for adres in {str(u).lower() for u in users}:
            if adres in izlenen:
                cikti.append(Olay(f"{adres}:{tid}", izlenen[adres].ad, adres, zaman, alma_ms, "trades", False, str(t.get("coin", ""))))
    return cikti


def userfills_olaylari(mesaj: dict, izlenen: dict[str, Izlenen], alma_ms: int) -> list[Olay]:
    veri = mesaj.get("data") or {}
    adres = str(veri.get("user", "")).lower()
    if adres not in izlenen:
        return []
    snapshot = veri.get("isSnapshot") is True
    return [Olay(f"{adres}:{f['tid']}", izlenen[adres].ad, adres, int(f["time"]), alma_ms, "userFills", snapshot, f"userFills:{adres}")
            for f in veri.get("fills") or [] if f.get("tid") is not None and _tam_sayi(f.get("time")) is not None]


class Olcum:
    """Saatlik pencere + toplam; tekilleştirme; sayaçlar. Saf (ağ yok)."""

    def __init__(self, izlenenler: list[Izlenen]) -> None:
        self.adlar = [i.ad for i in izlenenler]
        self.toplam = {ad: TraderOlcum() for ad in self.adlar}
        self.saat = {ad: TraderOlcum() for ad in self.adlar}
        self.gorulen: dict[str, int] = {}            # kimlik -> dolum zamanı (REST karşılaştırması ve tekilleştirme)
        self.genel = {"kopma": 0, "yeniden_baglanma": 0, "yeniden_baslama": 0, "error": 0, "subscription_response": 0, "tekrar": 0,
                      "trades_mesaj": 0, "userfills_mesaj": 0, "ping": 0, "abonelik_oncesi_snapshot_gibi": 0, "gecikme_60sn_ustu": 0,
                      "rest_abonelik_oncesi_atlanan": 0}
        self.abone: dict[str, int] = {}              # abonelik anahtarı -> aboneliğin gönderildiği an (ms); bundan ÖNCEKİ dolum canlı olay sayılmaz
        self.abone_coinler: set[str] = set()         # trades kanalına abone olunan coin evreni (sınıflama için)
        self.ilk_abone_bitis_ms = 0                  # ilk bağlantıda son aboneliğin gönderildiği an: REST hakem penceresi bundan önceyi kapsamaz
        self.son_mesaj_ms = 0                        # son alınan WS mesajının anı (kopma aralığının başlangıcı)
        self.kopma_bas_ms: int | None = None         # açık kopma: yeniden abonelik bitene kadar
        self.kopma_araliklari: list[tuple[int, int]] = []   # [son mesaj, yeniden abonelik bitişi]: bu aralıktaki REST'te-olup-görülmeyen dolum = `kopma_araligi`

    def olay(self, o: Olay) -> bool:
        """Yeni dolum ise True. Tekrar (aynı `{adres}:{tid}`) sayılır ama ikinci kez ölçülmez. Snapshot: kabul ve gecikme örneği YOK."""
        if o.kimlik in self.gorulen:
            self.genel["tekrar"] += 1
            return False
        self.gorulen[o.kimlik] = o.zaman_ms
        if not o.snapshot and o.zaman_ms < self.abone.get(o.abone, 0):
            o = replace(o, snapshot=True)           # abonelikten önce gerçekleşmiş: sunucu abonelik anında geçmişi gönderir (trades kanalı dahil)
            self.genel["abonelik_oncesi_snapshot_gibi"] += 1
        if not o.snapshot and o.alma_ms - o.zaman_ms > 60_000:
            self.genel["gecikme_60sn_ustu"] += 1
        for pencere in (self.toplam, self.saat):
            t = pencere[o.ad]
            if o.snapshot:
                t.snapshot += 1
            elif o.alma_ms < o.zaman_ms:
                t.negatif += 1
            else:
                t.gecikme.append((o.alma_ms - o.zaman_ms) / 1000)
        return True

    def rest_karsilastir(self, ad: str, adres: str, rest_dolumlar: list[dict], simdi_ms: int, tolerans_ms: int) -> int:
        """REST'te olup görülmeyen = kaçan. Karşılaştırma aralığı [ilk bağlantının aboneliği, şimdi − tolerans]: öncesi dinleyicinin kapsamı dışıdır (sayılmaz).
        Kaçan dolum sınıflanır: `spot` (`@N` / `…/USDC`), `hip3` (`dex:COIN`), `abonesiz_perp` (abone olunan coin evreninde yok), `gercek` (evrende var, görülmedi).
        `kacan` YALNIZ gerçek kaçandır; açıklanmış sınıflar `kacan_sinif` içinde ayrı yazılır. Kaçan dolum görülmüş sayılır: ikinci kez sayılmaz."""
        gercek = 0
        for f in rest_dolumlar:
            if f.get("tid") is None or _tam_sayi(f.get("time")) is None or int(f["time"]) > simdi_ms - tolerans_ms:
                continue
            if int(f["time"]) < self.ilk_abone_bitis_ms:
                self.genel["rest_abonelik_oncesi_atlanan"] += 1
                continue
            kimlik = f"{adres}:{f['tid']}"
            if kimlik not in self.gorulen:
                self.gorulen[kimlik] = int(f["time"])
                sinif = self.kacan_sinifi(str(f.get("coin", "")), int(f["time"]))
                for pencere in (self.toplam, self.saat):
                    pencere[ad].kacan_sinif[sinif] = pencere[ad].kacan_sinif.get(sinif, 0) + 1
                if sinif == "gercek":
                    gercek += 1
        for pencere in (self.toplam, self.saat):
            pencere[ad].kacan += gercek
        return gercek

    def kacan_sinifi(self, coin: str, zaman_ms: int = 0) -> str:
        if coin.startswith("@") or "/" in coin:
            return "spot"
        if self.abone_coinler and coin not in self.abone_coinler:
            return "hip3" if ":" in coin else "abonesiz_perp"          # abone evreninde olmayan (yeni listelenen / evren dışı) coin
        if any(bas <= zaman_ms <= bit for bas, bit in self.kopma_araliklari):
            return "kopma_araligi"          # bağlantı kopukken / yeniden abone olunurken olan dolum: gerçek ama açıklanmış kayıp (yeniden bağlanınca REST ile tamamlanması gerekir)
        return "gercek"

    def temizle(self, simdi_ms: int, saklama_ms: int = 2 * SAAT_MS) -> None:
        self.gorulen = {k: z for k, z in self.gorulen.items() if z >= simdi_ms - saklama_ms}

    def saati_sifirla(self) -> None:
        self.saat = {ad: TraderOlcum() for ad in self.adlar}

    def ozet(self, simdi_ms: int, baslangic_ms: int) -> dict[str, Any]:
        iso = lambda ms: datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")      # noqa: E731
        return {"surum": 1, "uretildi": iso(simdi_ms), "olcum_basladi": iso(baslangic_ms), "genel": dict(self.genel),
                "saat": {ad: t.ozet() for ad, t in self.saat.items()}, "toplam": {ad: t.ozet() for ad, t in self.toplam.items()},
                "negatif_gecikme_toplam": sum(t.negatif for t in self.toplam.values()),
                "saat_kaymasi_uyarisi": any(t.negatif for t in self.toplam.values())}


def ozet_yaz(yol: Path, ozet: dict[str, Any]) -> None:
    """Atomik yazım. Adres içermez (testli)."""
    metin = json.dumps(ozet, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if ADRES.search(metin):
        raise ValueError("ozet.json adres içeremez")
    yol.parent.mkdir(parents=True, exist_ok=True)
    gecici = yol.with_suffix(".tmp")
    gecici.write_text(metin, encoding="utf-8")
    gecici.replace(yol)


# ------------------------------------------------------------------------------------------------ REST (sayfalı)
def rest_dolumlar(post: Callable[[dict], Any], adres: str, bas_ms: int, bit_ms: int) -> list[dict]:
    """`userFillsByTime` sayfalı: tam sayfa (2000) dönerse son dolumun zamanından devam (tekilleştirme çağıranda)."""
    sonuc: list[dict] = []
    bas = bas_ms
    while bas <= bit_ms:
        sayfa = post({"type": "userFillsByTime", "user": adres, "startTime": bas, "endTime": bit_ms})
        if not isinstance(sayfa, list):
            raise ValueError("userFillsByTime yanıtı liste olmalı")
        sonuc += sayfa
        if len(sayfa) < REST_SAYFA:
            break
        son = max(int(f["time"]) for f in sayfa)
        if son <= bas:
            raise ValueError("sayfalama ilerlemiyor")
        bas = son
    return sonuc


# ------------------------------------------------------------------------------------------------ dinleyici
@dataclass
class Ayar:
    userfills_adet: int = 10
    ping_sn: float = 25.0
    rest_aralik_sn: float = 600.0
    rest_tolerans_ms: int = 120_000
    ozet_aralik_sn: float = 3600.0
    alma_zaman_asimi_sn: float = 60.0
    geri_cekilme_ilk_sn: float = 1.0
    geri_cekilme_max_sn: float = 30.0
    sure_sn: float | None = None


class Dinleyici:
    """WS kanalları + REST hakem + saatlik özet. `baglan()` bir WS nesnesi (send/recv/close) döndürür; `post` REST yükünü yanıtlar (tests sahte verir)."""

    def __init__(self, izlenenler: list[Izlenen], coinler: list[str], baglan: Callable[[], Awaitable[Any]], post: Callable[[dict], Any], cikti: Path,
                 ayar: Ayar | None = None, saat_ms: Callable[[], int] | None = None, mono: Callable[[], float] | None = None, onceki_baslama: int = 0) -> None:
        if not izlenenler:
            raise ValueError("izlenen adres listesi boş (fail-closed)")
        self.izlenen = {i.adres: i for i in izlenenler}
        if len(self.izlenen) != len(izlenenler):
            raise ValueError("adresler benzersiz olmalı")
        self.liste, self.coinler, self.baglan, self.post, self.cikti = izlenenler, coinler, baglan, post, cikti
        self.ayar = ayar or Ayar()
        self.saat_ms = saat_ms or (lambda: int(time.time() * 1000))
        self.mono = mono or time.monotonic
        self.olcum = Olcum(izlenenler)
        self.olcum.genel["yeniden_baslama"] = onceki_baslama
        self.baslangic_ms = self.saat_ms()
        self._dur = asyncio.Event()

    def durdur(self) -> None:
        self._dur.set()

    async def _abone_ol(self, ws: Any) -> None:
        self.olcum.abone_coinler = set(self.coinler)
        for coin in self.coinler:
            await ws.send(json.dumps({"method": "subscribe", "subscription": {"type": "trades", "coin": coin}}, separators=(",", ":")))
            self.olcum.abone[coin] = self.saat_ms()
        for i in self.liste[: self.ayar.userfills_adet]:
            await ws.send(json.dumps({"method": "subscribe", "subscription": {"type": "userFills", "user": i.adres}}, separators=(",", ":")))
            self.olcum.abone[f"userFills:{i.adres}"] = self.saat_ms()
        if not self.olcum.ilk_abone_bitis_ms:
            self.olcum.ilk_abone_bitis_ms = self.saat_ms()
        if self.olcum.kopma_bas_ms is not None:
            self.olcum.kopma_araliklari.append((self.olcum.kopma_bas_ms, self.saat_ms()))
            self.olcum.kopma_bas_ms = None

    def mesaj_isle(self, ham: str | bytes) -> None:
        alma = self.saat_ms()                                   # alma anı: mesaj çözülmeden ÖNCE damgalanır
        self.olcum.son_mesaj_ms = alma
        mesaj = json.loads(ham.decode("utf-8") if isinstance(ham, bytes) else ham)
        kanal = mesaj.get("channel") if isinstance(mesaj, dict) else None
        if kanal == "trades":
            self.olcum.genel["trades_mesaj"] += 1
            olaylar = trades_olaylari(mesaj, self.izlenen, alma)
        elif kanal == "userFills":
            self.olcum.genel["userfills_mesaj"] += 1
            olaylar = userfills_olaylari(mesaj, self.izlenen, alma)
        elif kanal == "error":
            self.olcum.genel["error"] += 1
            return
        elif kanal == "subscriptionResponse":
            self.olcum.genel["subscription_response"] += 1
            return
        else:
            return                                               # pong ve diğer kontrol çerçeveleri
        for o in olaylar:
            self.olcum.olay(o)

    async def rest_karsilastir(self) -> None:
        simdi = self.saat_ms()
        bas = simdi - int(2 * self.ayar.rest_aralik_sn * 1000)
        for i in self.liste:
            dolumlar = await asyncio.to_thread(rest_dolumlar, self.post, i.adres, bas, simdi)
            self.olcum.rest_karsilastir(i.ad, i.adres, dolumlar, simdi, self.ayar.rest_tolerans_ms)
        self.olcum.temizle(simdi)

    def ozet_yaz(self) -> None:
        ozet_yaz(self.cikti / "ozet.json", self.olcum.ozet(self.saat_ms(), self.baslangic_ms))

    async def _oturum(self, ws: Any) -> None:
        son_ping = son_rest = son_ozet = self.mono()
        while not self._dur.is_set():
            if self.ayar.sure_sn is not None and self.mono() - self._t0 >= self.ayar.sure_sn:
                return
            try:
                ham = await asyncio.wait_for(ws.recv(), timeout=min(self.ayar.ping_sn, 1.0))
            except asyncio.TimeoutError:
                ham = None
            if ham is not None:
                self.mesaj_isle(ham)
            simdi = self.mono()
            if simdi - son_ping >= self.ayar.ping_sn:
                await ws.send(json.dumps({"method": "ping"}))
                self.olcum.genel["ping"] += 1
                son_ping = simdi
            if simdi - son_rest >= self.ayar.rest_aralik_sn:
                await self.rest_karsilastir()
                son_rest = simdi
            if simdi - son_ozet >= self.ayar.ozet_aralik_sn:
                self.ozet_yaz()
                self.olcum.saati_sifirla()
                son_ozet = simdi

    async def calis(self) -> dict[str, Any]:
        self._t0 = self.mono()
        bekleme, baglandi = self.ayar.geri_cekilme_ilk_sn, 0
        try:
            while not self._dur.is_set() and not (self.ayar.sure_sn is not None and self.mono() - self._t0 >= self.ayar.sure_sn):
                ws = None
                try:
                    ws = await self.baglan()
                    baglandi += 1
                    if baglandi > 1:
                        self.olcum.genel["yeniden_baglanma"] += 1
                    await self._abone_ol(ws)
                    bekleme = self.ayar.geri_cekilme_ilk_sn
                    await self._oturum(ws)
                except asyncio.CancelledError:
                    raise
                except Exception:        # noqa: BLE001 - her bağlantı/akış hatası kopma sayılır; ayrıntı (sağlayıcı metni) yazılmaz
                    self.olcum.genel["kopma"] += 1
                    if self.olcum.kopma_bas_ms is None:
                        self.olcum.kopma_bas_ms = self.olcum.son_mesaj_ms or self.saat_ms()
                    try:
                        await asyncio.wait_for(self._dur.wait(), timeout=bekleme)
                    except asyncio.TimeoutError:
                        pass
                    bekleme = min(self.ayar.geri_cekilme_max_sn, bekleme * 2)
                finally:
                    if ws is not None:
                        try:
                            await ws.close()
                        except Exception:  # noqa: BLE001
                            pass
        finally:
            await self.rest_karsilastir_guvenli()
            self.ozet_yaz()
        return self.olcum.ozet(self.saat_ms(), self.baslangic_ms)

    async def rest_karsilastir_guvenli(self) -> None:
        try:
            await self.rest_karsilastir()
        except Exception:                # noqa: BLE001 - kapanışta REST hatası özeti engellemesin
            self.olcum.genel["error"] += 1


# ------------------------------------------------------------------------------------------------ gerçek taşıma
def rest_post_fabrikasi(info_url: str = DEFAULT_INFO_URL, zaman_asimi: float = 20.0) -> Callable[[dict], Any]:
    return lambda yuk: HyperliquidPublicAdapter._post_json(info_url, yuk, zaman_asimi)


async def ws_baglan(ws_url: str = DEFAULT_WS_URL) -> Any:
    try:
        from websockets.asyncio.client import connect
    except ImportError as hata:
        raise RuntimeError("websockets paketi kurulmalı: pip install -r requirements-dinleyici.txt") from hata
    return await connect(ws_url, open_timeout=20, ping_interval=None, max_size=2 ** 24)       # ping uygulama düzeyinde (HL {"method":"ping"})


def coin_listesi(post: Callable[[dict], Any]) -> list[str]:
    """Abone olunacak coin evreni = izleme motorunun kopyaladığı evren (kural 7): ana perp dex + HER HIP-3 dex'in perp coin'leri (`dex:COIN`).
    Motor `perp_fills` ile yalnız SPOT'u dışarıda bırakır (`olcut.asset_class`); spot kopyalanmadığı için abone olunmaz, REST'te görülürse `kacan_sinif.spot` olarak yalnız sayılır."""
    meta = post({"type": "meta"})
    coinler = [u["name"] for u in meta["universe"] if not u.get("isDelisted")]
    for dex in perp_dex_names(post({"type": "perpDexs"})):
        coinler += [u["name"] for u in post({"type": "meta", "dex": dex})["universe"] if not u.get("isDelisted") and u["name"] not in coinler]
    return coinler


def baslama_sayaci(durum_yolu: Path) -> int:
    """`Restart=on-failure` sonrası yeniden başlama sayısı: durum dosyasında kalıcı sayaç (ilk başlatmada 0)."""
    onceki = json.loads(durum_yolu.read_text(encoding="utf-8")).get("baslama", 0) if durum_yolu.exists() else None
    sayi = 0 if onceki is None else int(onceki) + 1
    durum_yolu.parent.mkdir(parents=True, exist_ok=True)
    durum_yolu.write_text(json.dumps({"baslama": sayi}), encoding="utf-8")
    return sayi


# ------------------------------------------------------------------------------------------------ adım 0
async def adim0(izlenenler: list[Izlenen], coinler: list[str], baglan: Callable[[], Awaitable[Any]], sure_sn: float, mono: Callable[[], float] | None = None) -> dict[str, Any]:
    """5 dk'lık keşif: (a) ilk 11 adresin `userFills` aboneliğine sunucu yanıtı (IP başına kullanıcı sınırı gerçek mi); (b) `trades` kanalında `users` alanı var mı
    ve izlenen adreslerin dolumu görünüyor mu. Adresler çıktıdan çıkarılır (takma ad); sağlayıcı hata metni adres maskelenerek kısaltılır."""
    mono = mono or time.monotonic
    ws = await baglan()
    izl = {i.adres: i for i in izlenenler}
    maske = lambda s: ADRES.sub(lambda m: izl[m.group(0).lower()].ad if m.group(0).lower() in izl else "0x…", s)[:200]      # noqa: E731
    sonuc: dict[str, Any] = {"abonelik": [], "trades": {"mesaj": 0, "islem": 0, "users_alanli_islem": 0, "izlenen_isabet": 0, "izlenen_adlar": []},
                             "userfills_mesaj": 0, "error": 0}
    try:
        for i in izlenenler[:11]:
            await ws.send(json.dumps({"method": "subscribe", "subscription": {"type": "userFills", "user": i.adres}}, separators=(",", ":")))
            sonuc["abonelik"].append({"ad": i.ad, "sira": len(sonuc["abonelik"]) + 1, "yanit": None})
        for coin in coinler:
            await ws.send(json.dumps({"method": "subscribe", "subscription": {"type": "trades", "coin": coin}}, separators=(",", ":")))
        bitis, isabet = mono() + sure_sn, set()
        while mono() < bitis:
            try:
                ham = await asyncio.wait_for(ws.recv(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            m = json.loads(ham)
            kanal = m.get("channel")
            if kanal == "error":
                sonuc["error"] += 1
                sonuc.setdefault("hata_metinleri", []).append(maske(str(m.get("data"))))
            elif kanal == "subscriptionResponse":
                s = json.dumps(m.get("data"))
                for ab in sonuc["abonelik"]:
                    if ab["yanit"] is None and izlenenler[ab["sira"] - 1].adres in s.lower():
                        ab["yanit"] = "ok"
            elif kanal == "userFills":
                sonuc["userfills_mesaj"] += 1
            elif kanal == "trades":
                sonuc["trades"]["mesaj"] += 1
                for t in m.get("data") or []:
                    sonuc["trades"]["islem"] += 1
                    if isinstance(t.get("users"), list):
                        sonuc["trades"]["users_alanli_islem"] += 1
                        for u in t["users"]:
                            if str(u).lower() in izl:
                                sonuc["trades"]["izlenen_isabet"] += 1
                                isabet.add(izl[str(u).lower()].ad)
        sonuc["trades"]["izlenen_adlar"] = sorted(isabet)
    finally:
        await ws.close()
    hatali = sonuc["error"]
    sonuc["yorum"] = {"userfills_11_adres_hata_sayisi": hatali, "trades_users_alani_var": sonuc["trades"]["users_alanli_islem"] > 0,
                      "izlenen_dolum_gorundu": sonuc["trades"]["izlenen_isabet"] > 0}
    return sonuc


# ------------------------------------------------------------------------------------------------ CLI
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("komut", choices=["calis", "adim0"])
    ap.add_argument("--liste", type=Path, required=True, help="izleme listesi YAML (ilk11/izleme_listesi.yaml ya da copytrade/izleme_listesi.yaml)")
    ap.add_argument("--cikti", type=Path, default=Path(os.environ.get("STATE_DIRECTORY", "/var/lib/sg-dinleyici")))
    ap.add_argument("--sure-sn", type=float, default=None, help="calis: toplam süre (varsayılan sonsuz); adim0: dinleme süresi (varsayılan 300)")
    ap.add_argument("--userfills-adet", type=int, default=10)
    args = ap.parse_args(argv)
    izlenenler = liste_oku(args.liste)
    post = rest_post_fabrikasi()
    coinler = coin_listesi(post)
    if args.komut == "adim0":
        sonuc = asyncio.run(adim0(izlenenler, coinler, ws_baglan, args.sure_sn or 300.0))
        args.cikti.mkdir(parents=True, exist_ok=True)
        (args.cikti / "adim0.json").write_text(json.dumps(sonuc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(json.dumps(sonuc, ensure_ascii=False, indent=1))
        return 0

    async def kos() -> dict[str, Any]:
        d = Dinleyici(izlenenler, coinler, ws_baglan, post, args.cikti, Ayar(userfills_adet=args.userfills_adet, sure_sn=args.sure_sn),
                      onceki_baslama=baslama_sayaci(args.cikti / "durum.json"))
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, d.durdur)
        return await d.calis()
    ozet = asyncio.run(kos())
    print(json.dumps({"kopma": ozet["genel"]["kopma"], "yeniden_baglanma": ozet["genel"]["yeniden_baglanma"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
