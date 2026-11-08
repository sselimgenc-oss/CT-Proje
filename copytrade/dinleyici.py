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
import socket
import statistics
import sys
import threading
import time
import urllib.error
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

from copytrade.hl_public_adapter import DEFAULT_INFO_URL, DEFAULT_WS_URL, HyperliquidPublicAdapter
from copytrade.izleme_liste import load_list, perp_dex_names
from copytrade.kurallar import load_rules
from copytrade.risk_defter import KararGunlugu, RiskDefteri

REST_SAYFA = 2000                      # userFillsByTime tek yanıtta en çok bu kadar dolum döner (API sınırı; eşik değil)
ADRES = re.compile(r"0x[0-9a-fA-F]{40}")
SAAT_MS = 3_600_000


# ------------------------------------------------------------------------------------------------ liste ve istatistik
@dataclass(frozen=True)
class Izlenen:
    ad: str          # takma ad (özette görünen); adres özete ASLA yazılmaz
    adres: str       # küçük harf
    takim: str = ""  # ilk11 | yedek11 | paf | "" (listede `takim` yoksa boş; H5 risk kapısı yalnız ilk11 için niyet üretir)


def liste_oku(yol: Path) -> list[Izlenen]:
    """İzleme listesi (K-12.8: ilk11 / yedek11 / paf + referans kolları; `izleme_motoru.load_list` yeniden kullanılır). Dosya yok ya da boşsa BAŞLAMAZ (fail-closed)."""
    if not yol.is_file():
        raise ValueError(f"izleme listesi yok: {yol} (fail-closed)")
    satirlar = load_list(yol)
    if not satirlar:
        raise ValueError("izleme listesi boş (fail-closed)")
    adlar = [r["takma_ad"] for r in satirlar]
    return [Izlenen(r["takma_ad"] if adlar.count(r["takma_ad"]) == 1 else f"{r['takma_ad']}-{r['id']}", r["adres"].lower(), r.get("takim", "")) for r in satirlar]


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
    dolgu: int = 0                                            # kopma sonrası REST dolgusuyla kurtarılan dolum (kaynak=dolgu)
    dolgu_gecikme: list[float] = field(default_factory=list)  # saniye: dolum zamanı -> dolgunun aldığı an (canlı gecikmeden AYRI)

    def ozet(self) -> dict[str, Any]:
        g = self.gecikme
        return {"n": len(g), "gecikme_medyan_sn": None if not g else round(statistics.median(g), 3),
                "gecikme_p95_sn": None if not g else round(p_sira(g, 0.95), 3), "gecikme_max_sn": None if not g else round(max(g), 3),
                "kacan": self.kacan, "kacan_sinif": dict(sorted(self.kacan_sinif.items())), "snapshot": self.snapshot, "negatif_gecikme": self.negatif,
                "dolgu": self.dolgu, "dolgu_gecikme_max_sn": None if not self.dolgu_gecikme else round(max(self.dolgu_gecikme), 3)}


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
    coin: str = ""       # H5: dolum ayrıntısı (risk kapısı için). px $/coin, sz coin miktarı, yon "B"=alış "A"=satış (izlenen adresin tarafı), bas_poz = dolum öncesi işaretli pozisyon
    px: float | None = None
    sz: float | None = None
    yon: str = ""
    bas_poz: float | None = None    # yalnız userFills / REST `startPosition`; trades kanalında YOK (None)


def _tam_sayi(deger: Any) -> int | None:
    try:
        return int(deger)
    except (TypeError, ValueError):
        return None


def _sayi(deger: Any) -> float | None:
    try:
        x = float(deger)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def trades_olaylari(mesaj: dict, izlenen: dict[str, Izlenen], alma_ms: int) -> list[Olay]:
    """`trades` kanalı: her işlemdeki `users: [alıcı, satıcı]` içinden izlenen adresler. Bir işlem iki izlenen adresi de içeriyorsa iki olay."""
    cikti = []
    for t in mesaj.get("data") or []:
        users, tid, zaman = t.get("users"), t.get("tid"), _tam_sayi(t.get("time"))
        if not isinstance(users, list) or tid is None or zaman is None:
            continue
        kucuk = [str(u).lower() for u in users]
        for adres in set(kucuk):
            if adres in izlenen:
                # `users` = [alıcı, satıcı]; aynı adres iki tarafta (kendi kendine işlem) ise net etki yok: yön boş
                yon = "" if kucuk.count(adres) > 1 else ("B" if kucuk and kucuk[0] == adres else "A")
                coin = str(t.get("coin", ""))
                cikti.append(Olay(f"{adres}:{tid}", izlenen[adres].ad, adres, zaman, alma_ms, "trades", False, coin, coin, _sayi(t.get("px")), _sayi(t.get("sz")), yon))
    return cikti


def userfills_olaylari(mesaj: dict, izlenen: dict[str, Izlenen], alma_ms: int) -> list[Olay]:
    veri = mesaj.get("data") or {}
    adres = str(veri.get("user", "")).lower()
    if adres not in izlenen:
        return []
    snapshot = veri.get("isSnapshot") is True
    return [Olay(f"{adres}:{f['tid']}", izlenen[adres].ad, adres, int(f["time"]), alma_ms, "userFills", snapshot, f"userFills:{adres}",
                 str(f.get("coin", "")), _sayi(f.get("px")), _sayi(f.get("sz")), str(f.get("side", "")), _sayi(f.get("startPosition")))
            for f in veri.get("fills") or [] if f.get("tid") is not None and _tam_sayi(f.get("time")) is not None]


class Olcum:
    """Saatlik pencere + toplam; tekilleştirme; sayaçlar. Saf (ağ yok)."""

    def __init__(self, izlenenler: list[Izlenen]) -> None:
        self.adlar = [i.ad for i in izlenenler]
        self.toplam = {ad: TraderOlcum() for ad in self.adlar}
        self.saat = {ad: TraderOlcum() for ad in self.adlar}
        self.gorulen: dict[str, int] = {}            # kimlik -> dolum zamanı (REST karşılaştırması ve tekilleştirme)
        self.snapshot_gorulen: set[str] = set()       # G-17b: YALNIZ snapshot (abonelik öncesi) olarak görülen kimlikler: dolgu bunları atlamaz (kopukken olan dolum emir üretebilsin)
        self.genel = {"kopma": 0, "yeniden_baglanma": 0, "yeniden_baslama": 0, "error": 0, "subscription_response": 0, "tekrar": 0,
                      "trades_mesaj": 0, "userfills_mesaj": 0, "ping": 0, "abonelik_oncesi_snapshot_gibi": 0, "gecikme_60sn_ustu": 0,
                      "rest_abonelik_oncesi_atlanan": 0}
        self.abone: dict[str, int] = {}              # abonelik anahtarı -> aboneliğin gönderildiği an (ms); bundan ÖNCEKİ dolum canlı olay sayılmaz
        self.abone_coinler: set[str] = set()         # trades kanalına abone olunan coin evreni (sınıflama için)
        self.ilk_abone_bitis_ms = 0                  # ilk bağlantıda son aboneliğin gönderildiği an: REST hakem penceresi bundan önceyi kapsamaz
        self.son_mesaj_ms = 0                        # son alınan WS mesajının anı (kopma aralığının başlangıcı)
        self.kopma_bas_ms: int | None = None         # açık kopma: yeniden abonelik bitene kadar
        self.dolgu_yeni: list[tuple[str, dict]] = []  # H5: dolguyla kurtarılan dolumlar (takma ad, REST dolumu); Dinleyici risk defterine verip boşaltır
        self.kopma_araliklari: list[tuple[int, int]] = []   # [son mesaj, yeniden abonelik bitişi]: bu aralıktaki REST'te-olup-görülmeyen dolum = `kopma_araligi`

    def snapshot_mi(self, o: Olay) -> bool:
        """Kanalın snapshot dediği ya da abonelikten ÖNCE gerçekleşmiş dolum: canlı olay değildir (H5: niyet üretilmez, yalnız trader pozisyonu izlenir)."""
        return o.snapshot or o.zaman_ms < self.abone.get(o.abone, 0)

    def olay(self, o: Olay) -> bool:
        """Yeni dolum ise True. Tekrar (aynı `{adres}:{tid}`) sayılır ama ikinci kez ölçülmez. Snapshot: kabul ve gecikme örneği YOK."""
        if o.kimlik in self.gorulen:
            self.genel["tekrar"] += 1
            return False
        self.gorulen[o.kimlik] = o.zaman_ms
        if not o.snapshot and self.snapshot_mi(o):
            o = replace(o, snapshot=True)           # abonelikten önce gerçekleşmiş: sunucu abonelik anında geçmişi gönderir (trades kanalı dahil)
            self.genel["abonelik_oncesi_snapshot_gibi"] += 1
        if o.snapshot:
            self.snapshot_gorulen.add(o.kimlik)
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

    def dolgu(self, ad: str, adres: str, rest_dolumlar: list[dict], bas_ms: int, simdi_ms: int) -> int:
        """Kopma sonrası REST dolgusu: [bas_ms, simdi_ms] aralığında REST'te olup henüz görülmeyen perp dolumları `kaynak=dolgu` olarak kaydeder (görülmüş sayılır:
        sonraki REST hakem bunları kaçan saymaz). Gecikme = simdi − dolum zamanı, canlı gecikme örneğine GİRMEZ. Spot kopyalanmaz: atlanır. Döner: kurtarılan adet."""
        kurtarilan = 0
        for f in rest_dolumlar:
            if f.get("tid") is None or _tam_sayi(f.get("time")) is None:
                continue
            zaman = int(f["time"])
            kimlik = f"{adres}:{f['tid']}"
            coin = str(f.get("coin", ""))
            canli_goruldu = kimlik in self.gorulen and kimlik not in self.snapshot_gorulen      # G-17b: yalnız CANLI görülen atlanır; snapshot'ta görülen (kopukken olmuş) dolum dolguyla emir üretir
            if not bas_ms <= zaman <= simdi_ms or canli_goruldu or coin.startswith("@") or "/" in coin:
                continue
            self.gorulen[kimlik] = zaman
            self.snapshot_gorulen.discard(kimlik)
            self.dolgu_yeni.append((ad, f))
            kurtarilan += 1
            for pencere in (self.toplam, self.saat):
                pencere[ad].dolgu += 1
                pencere[ad].dolgu_gecikme.append(max(0, simdi_ms - zaman) / 1000)
        return kurtarilan

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
        self.snapshot_gorulen &= self.gorulen.keys()

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


# ------------------------------------------------------------------------------------------------ REST hatası türü ve istek aralığı
def hata_turu(hata: BaseException) -> str:
    """REST hatasının SINIFI (adres / URL / sağlayıcı metni YOK): `HTTP 429`, `Timeout`, `Ağ (URLError)`, `Geçersiz yanıt` ya da istisna sınıf adı."""
    if isinstance(hata, urllib.error.HTTPError):
        return f"HTTP {hata.code}"
    if isinstance(hata, (TimeoutError, socket.timeout)):
        return "Timeout"
    if isinstance(hata, urllib.error.URLError):
        return "Timeout" if isinstance(hata.reason, (TimeoutError, socket.timeout)) or "timed out" in str(hata.reason).lower() else "Ağ (URLError)"
    if isinstance(hata, ValueError):
        return "Geçersiz yanıt"
    return ADRES.sub("0x…", type(hata).__name__)


class IstekAralik:
    """İstekler arası en az `ara_sn`: iş parçacığı güvenli, YER AYIRIR (kilit beklerken tutulmaz). Senkron (`bekle`, `to_thread` içinden) ve asenkron (`abekle`) kullanım aynı sayacı paylaşır."""

    def __init__(self, ara_sn: float) -> None:
        self.ara_sn, self._kilit, self._son = ara_sn, threading.Lock(), float("-inf")

    def _yer_ayir(self) -> float:
        with self._kilit:
            simdi = time.monotonic()
            baslangic = max(simdi, self._son + self.ara_sn)
            self._son = baslangic
            return baslangic - simdi

    def bekle(self) -> None:
        time.sleep(self._yer_ayir())

    async def abekle(self) -> None:
        await asyncio.sleep(self._yer_ayir())


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
    baslangic_bekleme_sn: tuple[float, ...] = (2.0, 5.0, 15.0)    # H5b: başlangıç pozisyonu okuması hata verirse yeniden denemeden önce bekleme (sn); 3 yeniden deneme
    rest_dolum_ara_sn: float = 1.5                                # `userFillsByTime` (dolgu, hakem; sayfalar dahil) ardışık istekleri arası en az (sn; ağırlık ≥ 20 → ≈ 13-15 ağırlık/sn, HL sınırı 20/sn)
    rest_poz_ara_sn: float = 0.5                                  # `clearinghouseState` (H5b başlangıç pozisyonu; ağırlık 2) ardışık istekleri arası en az (sn)
    kapanis_sinir_sn: float = 60.0                                # kapanıştaki son hakem turu için en fazla süre (sn); yetişmeyen adresler `genel.kapanis_atlanan`
    rest_bekleme_sn: tuple[float, ...] = (2.0, 5.0, 15.0)         # dolgu / hakem: 429-ağ hatasında yeniden denemeden önce bekleme (sn); 3 yeniden deneme
    baslangic_yeniden_sn: float = 300.0                           # H5b: 3 yeniden deneme de başarısızsa o adres için arka plan deneme aralığı (sn)


class Dinleyici:
    """WS kanalları + REST hakem + saatlik özet. `baglan()` bir WS nesnesi (send/recv/close) döndürür; `post` REST yükünü yanıtlar (tests sahte verir)."""

    def __init__(self, izlenenler: list[Izlenen], coinler: list[str], baglan: Callable[[], Awaitable[Any]], post: Callable[[dict], Any], cikti: Path,
                 ayar: Ayar | None = None, saat_ms: Callable[[], int] | None = None, mono: Callable[[], float] | None = None, onceki_baslama: int = 0,
                 risk: RiskDefteri | None = None, risk_gunlugu: KararGunlugu | None = None, dur_yolu: Path | None = None, dex_adlari: list[str] | None = None) -> None:
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
        self.risk, self.risk_gunlugu, self.dur_yolu = risk, risk_gunlugu, dur_yolu      # H5: dry-run risk kapısı (None = kapalı)
        self.dex_adlari = list(dex_adlari or [])
        if risk is not None:
            self.olcum.genel.update({"baslangic_poz_okundu": 0, "baslangic_poz_hata": 0, "baslangic_poz_yeniden_deneme": 0, "baslangic_poz_arka_plan": 0, "baslangic_poz_bekleyen": 0})
        self._bas_gorevler: dict[str, asyncio.Task] = {}
        self._aralik_dolum = IstekAralik(self.ayar.rest_dolum_ara_sn)       # iki ayrı sayaç: istek türüne göre ağırlık farklı
        self._aralik_poz = IstekAralik(self.ayar.rest_poz_ara_sn)
        self._dolgu_bekleyen: dict[str, int] = {}                # takma ad -> doldurulamayan en eski kopma aralığı başlangıcı (ms): kopma aralığı UNUTULMAZ
        self._dolgu_gorevi: asyncio.Task | None = None
        self._hakem_gorevi: asyncio.Task | None = None
        self.olcum.genel.update({"dolgu_yeniden_deneme": 0, "dolgu_bekleyen": 0, "dolgu_hata_tur": {}, "hakem_yeniden_deneme": 0, "hakem_hata": 0, "hakem_hata_tur": {},
                                 "rest_tur_atlanan": 0, "kapanis_atlanan": 0})
        if risk is not None:
            self.olcum.genel["baslangic_poz_hata_tur"] = {}

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

    def _bas_baslat(self) -> None:
        """H5b: her (yeniden) bağlanmada İlk 11 adreslerinin açık pozisyonlarını ARKA PLANDA okur (WS akışı ve ölçüm ASLA beklemez). Önceki turun görevleri iptal edilir."""
        if self.risk is None:
            return
        self._bas_iptal()
        for i in self.liste:
            if i.ad in self.risk.ilk11:
                self._bas_gorevler[i.ad] = asyncio.create_task(self._bas_adres(i))

    def _bas_iptal(self) -> list[asyncio.Task]:
        gorevler = list(self._bas_gorevler.values())
        for g in gorevler:
            g.cancel()
        self._bas_gorevler.clear()
        return gorevler

    def _rest_uyari(self, kaynak: str, ad: str, tur: str) -> None:
        """Her REST hatası journal'a TEK satır uyarı: yalnız kaynak, takma ad ve hata türü (adres / URL / sağlayıcı metni YOK)."""
        print(f"UYARI REST hatası kaynak={kaynak} trader={ad} tur={tur}", file=sys.stderr, flush=True)

    def _hata_say(self, onek: str, tur: str) -> None:
        d = self.olcum.genel[f"{onek}_hata_tur"]
        d[tur] = d.get(tur, 0) + 1

    def _rest_post(self, yuk: dict) -> Any:
        """`to_thread` içinden (`userFillsByTime`): istekler arası en az `rest_dolum_ara_sn` (dolgu + hakem ORTAK sayaç), sonra gerçek post."""
        self._aralik_dolum.bekle()
        return self.post(yuk)

    async def _bas_oku(self, i: Izlenen) -> tuple[bool, str | None]:
        """Bir adres için tüm dex'leri sırayla okur; hepsi başarılıysa risk defterine verir. Hata (429, ağ, geçersiz yanıt) -> (False, hata türü); kısmi sonuç uygulanmaz."""
        pozlar: dict[str, float] = {}
        okuma: dict[str, int] = {}
        try:
            for dex in ["", *self.dex_adlari]:
                await self._aralik_poz.abekle()
                okuma[dex] = self.saat_ms()
                pozlar.update(clearinghouse_ayristir(await asyncio.to_thread(self.post, clearinghouse_yuk(i.adres, dex))))
        except asyncio.CancelledError:
            raise
        except Exception as hata:       # noqa: BLE001 - ağ / 429 / yanıt hatası: çağıran yeniden dener
            tur = hata_turu(hata)
            self._rest_uyari("baslangic_poz", i.ad, tur)
            return False, tur
        self.risk.baslangic_ayarla(i.ad, pozlar, okuma)
        self.olcum.genel["baslangic_poz_okundu"] += 1
        return True, None

    async def _bas_adres(self, i: Izlenen) -> None:
        """Okuma + en çok 3 yeniden deneme (2 / 5 / 15 sn bekleyerek). Hepsi başarısızsa `baslangic_poz_hata` +1 ve o adres her 5 dk'da arka planda yeniden denenir;
        başarılı olana dek YALNIZ o adres için `lider_pozisyon_varsayimi` geçerlidir (defter bilinen saymaz)."""
        genel, bekleyen = self.olcum.genel, False
        try:
            ok, tur = await self._bas_oku(i)
            if ok:
                return
            for bekle in self.ayar.baslangic_bekleme_sn:
                genel["baslangic_poz_yeniden_deneme"] += 1
                await asyncio.sleep(bekle)
                ok, tur = await self._bas_oku(i)
                if ok:
                    return
            genel["baslangic_poz_hata"] += 1
            self._hata_say("baslangic_poz", tur or "Bilinmiyor")
            genel["baslangic_poz_bekleyen"] += 1
            bekleyen = True
            while True:
                await asyncio.sleep(self.ayar.baslangic_yeniden_sn)
                genel["baslangic_poz_arka_plan"] += 1
                if (await self._bas_oku(i))[0]:
                    return
        finally:
            if bekleyen:
                genel["baslangic_poz_bekleyen"] -= 1

    def risk_isle(self, o: Olay, canli: bool, simdi_ms: int, kaynak: str | None = None) -> None:
        """H5: yeni (tekilleştirilmiş) dolumu risk defterine verir; karar satırları günlüğe yazılır. Risk hatası dinlemeyi/ölçümü ASLA durdurmaz."""
        if self.risk is None:
            return
        try:
            if self.dur_yolu is not None:
                self.risk.dur_aktif = self.dur_yolu.exists()
            kararlar = self.risk.isle(ad=o.ad, coin=o.coin, yon=o.yon, sz=o.sz, px=o.px, bas_poz=o.bas_poz, zaman_ms=o.zaman_ms, simdi_ms=simdi_ms,
                                      kaynak=kaynak or o.kaynak, canli=canli and not self.olcum.snapshot_mi(o))
            if self.risk_gunlugu is not None:
                for k in kararlar:
                    self.risk_gunlugu.yaz(k)
        except Exception:        # noqa: BLE001 - risk katmanı ölçümü bozmasın; sayılır
            self.olcum.genel["risk_hata"] = self.olcum.genel.get("risk_hata", 0) + 1

    def mesaj_isle(self, ham: str | bytes) -> None:
        alma = self.saat_ms()                                   # alma anı: mesaj çözülmeden ÖNCE damgalanır
        self.olcum.son_mesaj_ms = alma
        mesaj = json.loads(ham.decode("utf-8") if isinstance(ham, bytes) else ham)
        kanal = mesaj.get("channel") if isinstance(mesaj, dict) else None
        if kanal == "trades":
            self.olcum.genel["trades_mesaj"] += 1
            olaylar = trades_olaylari(mesaj, self.izlenen, alma)
            if self.risk is not None and self.risk.pozlar:
                for t in mesaj.get("data") or []:
                    px = _sayi(t.get("px"))
                    if px is not None and isinstance(t, dict):
                        self.risk.fiyat(str(t.get("coin", "")), px, alma)         # açık kopya pozisyonu olan coin'in son işlem fiyatı
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
        for o in sorted(olaylar, key=lambda x: x.zaman_ms):
            if self.olcum.olay(o):
                self.risk_isle(o, True, alma)

    async def _rest_dolum_al(self, i: Izlenen, bas_fn: Callable[[int], int], onek: str) -> tuple[list[dict] | None, int, str | None]:
        """Bir adresin `userFillsByTime` dolumları: her istek arası ≥ `rest_dolum_ara_sn` (dolgu + hakem ortak), 429-ağ hatasında en çok 3 yeniden deneme (2 / 5 / 15 sn). `to_thread` korunur.
        Döner (dolumlar, bitiş_ms, None) ya da (None, bitiş_ms, SON hata türü). Her hata journal'a tek satır uyarı olarak yazılır."""
        tur, bit = "Bilinmiyor", self.saat_ms()
        for k in range(len(self.ayar.rest_bekleme_sn) + 1):
            if k:
                self.olcum.genel[f"{onek}_yeniden_deneme"] += 1
                await asyncio.sleep(self.ayar.rest_bekleme_sn[k - 1])
            bit = self.saat_ms()
            try:
                return await asyncio.to_thread(rest_dolumlar, self._rest_post, i.adres, bas_fn(bit), bit), bit, None
            except Exception as hata:       # noqa: BLE001 - ağ / 429 / yanıt hatası
                tur = hata_turu(hata)
                self._rest_uyari(onek, i.ad, tur)
        return None, bit, tur

    def _dolgu_baslat(self, aralik: tuple[int, int] | None = None) -> None:
        """H2b / 429 koruması: kopma aralığını ARKA PLANDA doldurur (WS akışı beklemez). Doldurulamayan adres `_dolgu_bekleyen`de kalır (en eski başlangıçla) ve sonraki REST turunda yeniden denenir."""
        if aralik is not None:
            for i in self.liste:
                self._dolgu_bekleyen[i.ad] = min(self._dolgu_bekleyen.get(i.ad, aralik[0]), aralik[0])
        self.olcum.genel["dolgu_bekleyen"] = len(self._dolgu_bekleyen)
        if self._dolgu_gorevi is not None:
            self._dolgu_gorevi.cancel()               # yarım kalan iş güvenli: bekleyen kaydı yalnız başarıda silinir
        if self._dolgu_bekleyen:
            self._dolgu_gorevi = asyncio.create_task(self.dolgu())

    async def dolgu(self) -> None:
        """Bekleyen kopma aralıklarını adres adres doldurur. 3 yeniden deneme de başarısızsa `genel.dolgu_hata` +1 (+ `dolgu_hata_tur`), adres bekleyenlerde kalır."""
        genel = self.olcum.genel
        for i in list(self.liste):
            bas = self._dolgu_bekleyen.get(i.ad)
            if bas is None:
                continue
            dolumlar, bit, tur = await self._rest_dolum_al(i, lambda _bit, b=bas: b, "dolgu")
            if dolumlar is None:
                genel["dolgu_hata"] = genel.get("dolgu_hata", 0) + 1
                self._hata_say("dolgu", tur or "Bilinmiyor")
                continue
            if self._dolgu_bekleyen.get(i.ad) == bas:
                del self._dolgu_bekleyen[i.ad]
            genel["dolgu_bekleyen"] = len(self._dolgu_bekleyen)
            genel["dolgu"] = genel.get("dolgu", 0) + self.olcum.dolgu(i.ad, i.adres, dolumlar, bas, bit)
            yeni, self.olcum.dolgu_yeni = sorted(self.olcum.dolgu_yeni, key=lambda x: int(x[1]["time"])), []
            for ad, f in yeni:       # H5: dolgu geç gelir -> girişler `gec_sinyal` ile reddedilir, çıkışlar serbest
                adres = next((x.adres for x in self.liste if x.ad == ad), "")
                self.risk_isle(Olay(f"{adres}:{f['tid']}" if adres else "", ad, adres, int(f["time"]), bit, "dolgu", False, "", str(f.get("coin", "")), _sayi(f.get("px")),
                                    _sayi(f.get("sz")), str(f.get("side", "")), _sayi(f.get("startPosition"))), True, bit)       # kimlik: motor aynı dolumu snapshot'tan tanır (poz_tr bir kez)

    def _hakem_baslat(self) -> None:
        """REST hakem turunu ARKA PLANDA başlatır (WS akışı beklemez). Önceki tur sürüyorsa bu tur atlanır (`genel.rest_tur_atlanan`). Doldurulamayan dolgu varsa onu da yeniden dener."""
        if self._hakem_gorevi is not None and not self._hakem_gorevi.done():
            self.olcum.genel["rest_tur_atlanan"] += 1
            return
        if self._dolgu_bekleyen and (self._dolgu_gorevi is None or self._dolgu_gorevi.done()):
            self._dolgu_baslat()
        self._hakem_gorevi = asyncio.create_task(self.rest_karsilastir())

    async def rest_karsilastir(self, yeniden: bool = True) -> None:
        """REST hakem: her adres için son 2 tur penceresi. Adres hatası (3 yeniden deneme sonrası) `genel.hakem_hata` (+ `hakem_hata_tur`); o adresin penceresi sonraki turda (pencere 2 tur) yeniden kapsanır.
        ASLA istisna yükseltmez (eski davranış: tek 429 oturumu kopma sayıyordu). `yeniden=False`: KAPANIŞ turu — bekleme/yeniden deneme yok ve en fazla `kapanis_sinir_sn`;
        yetişmeyen adresler `genel.kapanis_atlanan` (servis durdurma süresi aşılmasın)."""
        dolgu = self._dolgu_gorevi
        if yeniden and dolgu is not None and not dolgu.done():
            await asyncio.wait({dolgu})       # önce dolgu: hakem aynı aralıktaki dolumları "kopma aralığı kaçanı" diye görülmüş işaretlemesin (dolgu onları kurtaracak)
        eski = self.ayar
        if not yeniden:
            self.ayar = replace(eski, rest_bekleme_sn=())
        dongu = asyncio.get_running_loop()
        son = None if yeniden else dongu.time() + eski.kapanis_sinir_sn
        try:
            for sira, i in enumerate(self.liste):
                kalan = None if son is None else son - dongu.time()
                if kalan is not None and kalan <= 0:
                    self.olcum.genel["kapanis_atlanan"] += len(self.liste) - sira
                    break
                try:
                    dolumlar, bit, tur = await asyncio.wait_for(self._rest_dolum_al(i, lambda b: b - int(2 * eski.rest_aralik_sn * 1000), "hakem"), timeout=kalan)
                except asyncio.TimeoutError:      # sınır bu adresin ortasında doldu: bu ve kalan adresler atlanır
                    self.olcum.genel["kapanis_atlanan"] += len(self.liste) - sira
                    break
                if dolumlar is None:
                    self.olcum.genel["hakem_hata"] += 1
                    self._hata_say("hakem", tur or "Bilinmiyor")
                    continue
                self.olcum.rest_karsilastir(i.ad, i.adres, dolumlar, bit, eski.rest_tolerans_ms)
        finally:
            self.ayar = eski
        self.olcum.temizle(self.saat_ms())

    def ozet(self) -> dict[str, Any]:
        o = self.olcum.ozet(self.saat_ms(), self.baslangic_ms)
        if self.risk is not None:
            if self.dur_yolu is not None:
                self.risk.dur_aktif = self.dur_yolu.exists()
            o["risk"] = self.risk.ozet()
        return o

    def ozet_yaz(self) -> None:
        ozet_yaz(self.cikti / "ozet.json", self.ozet())

    async def _oturum(self, ws: Any) -> None:
        son_ping = son_rest = son_ozet = son_alma = self.mono()
        while not self._dur.is_set():
            if self.ayar.sure_sn is not None and self.mono() - self._t0 >= self.ayar.sure_sn:
                return
            try:
                ham = await asyncio.wait_for(ws.recv(), timeout=min(self.ayar.ping_sn, self.ayar.alma_zaman_asimi_sn, 1.0))
            except asyncio.TimeoutError:
                ham = None
            simdi = self.mono()
            if ham is not None:
                son_alma = simdi
                self.mesaj_isle(ham)
            elif simdi - son_alma >= self.ayar.alma_zaman_asimi_sn:        # G-17a: yarı açık TCP (send hata vermez, recv hiç dönmez); normalde saniyede 11-60 mesaj gelir
                self.olcum.genel["alma_zaman_asimi"] = self.olcum.genel.get("alma_zaman_asimi", 0) + 1
                raise ConnectionError(f"{self.ayar.alma_zaman_asimi_sn:g} sn mesaj yok (sessiz kopma)")
            if simdi - son_ping >= self.ayar.ping_sn:
                await ws.send(json.dumps({"method": "ping"}))
                self.olcum.genel["ping"] += 1
                son_ping = simdi
            if simdi - son_rest >= self.ayar.rest_aralik_sn:
                self._hakem_baslat()
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
                    onceki_aralik = len(self.olcum.kopma_araliklari)
                    await self._abone_ol(ws)
                    if len(self.olcum.kopma_araliklari) > onceki_aralik:
                        self._dolgu_baslat(self.olcum.kopma_araliklari[-1])       # H2b: kopmada kaçan işlem = kayıp -> REST ile tamamla (ARKA PLANDA; kopma aralığı bekleyende saklanır)
                    self._bas_baslat()                                            # H5b: trader'ın açık pozisyonları, ARKA PLANDA (dolgudan SONRA başlar: REST gerçektir)
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
            try:
                isler = [*self._bas_iptal(), *(g for g in (self._dolgu_gorevi, self._hakem_gorevi) if g is not None)]
                for g in isler:
                    g.cancel()
                await asyncio.gather(*isler, return_exceptions=True)
                await self.rest_karsilastir_guvenli()
            finally:
                self.ozet_yaz()               # son özet HER durumda yazılır (kapanış turu hata verse / iptal edilse de)
        return self.ozet()

    async def rest_karsilastir_guvenli(self) -> None:
        try:
            await self.rest_karsilastir(yeniden=False)
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
    return await connect(ws_url, open_timeout=20, ping_interval=20, ping_timeout=20, max_size=2 ** 24)       # uygulama pingi (HL {"method":"ping"}) + G-17a: WS protokol pingi (yanıtsız bağlantı kapanır → kopma yolu)


def clearinghouse_yuk(adres: str, dex: str = "") -> dict[str, Any]:
    yuk: dict[str, Any] = {"type": "clearinghouseState", "user": adres}
    if dex:
        yuk["dex"] = dex
    return yuk


def clearinghouse_ayristir(yanit: Any) -> dict[str, float]:
    """`clearinghouseState` yanıtı -> {coin: işaretli miktar (coin birimi, + long / − short)}. Bozuk yanıt ValueError."""
    if not isinstance(yanit, dict) or not isinstance(yanit.get("assetPositions"), list):
        raise ValueError("clearinghouseState yanıtı geçersiz")
    sonuc: dict[str, float] = {}
    for ap in yanit["assetPositions"]:
        poz = ap.get("position") if isinstance(ap, dict) else None
        miktar = _sayi(poz.get("szi")) if isinstance(poz, dict) else None
        if miktar is None or not poz.get("coin"):
            raise ValueError("clearinghouseState pozisyonu geçersiz")
        sonuc[str(poz["coin"])] = sonuc.get(str(poz["coin"]), 0.0) + miktar
    return sonuc


def clearinghouse_pozisyonlari(post: Callable[[dict], Any], adres: str, dex_adlari: list[str]) -> dict[str, float]:
    """H5b (eşzamanlı, bekleme/yeniden deneme YOK): ana perp dex + her HIP-3 dex. Herhangi bir çağrı ya da yanıt bozuksa istisna YÜKSELTİR (kısmi sonuç dönmez).
    Dinleyici bunu kullanmaz (arka plan okuması `Dinleyici._bas_oku`); araç / deneme içindir. Spot kopyalanmadığı için okunmaz."""
    sonuc: dict[str, float] = {}
    for dex in ["", *dex_adlari]:
        sonuc.update(clearinghouse_ayristir(post(clearinghouse_yuk(adres, dex))))
    return sonuc


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
    ap.add_argument("--risk-tum-liste", action="store_true", help="YALNIZ DENEME: listedeki herkes 'ilk11 sayılır' (pilot listede `takim: ilk11` yoksa); üretimde kullanılmaz")
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
        kural = load_rules()
        ilk11 = {i.ad for i in izlenenler if args.risk_tum_liste or i.takim == "ilk11"}
        dur_yolu = Path(str(kural["risk_dry_run"]["dur_dosyasi"]).replace("$STATE_DIRECTORY", str(args.cikti)))
        risk = RiskDefteri(ilk11, kural, baslangic_ms=int(time.time() * 1000))
        try:
            dexler = perp_dex_names(post({"type": "perpDexs"}))
        except Exception:        # noqa: BLE001 - dex listesi okunamazsa yalnız ana dex (coin_listesi zaten aynı çağrıyı yaptı)
            dexler = []
        d = Dinleyici(izlenenler, coinler, ws_baglan, post, args.cikti, Ayar(userfills_adet=args.userfills_adet, sure_sn=args.sure_sn),
                      onceki_baslama=baslama_sayaci(args.cikti / "durum.json"), risk=risk, risk_gunlugu=KararGunlugu(args.cikti), dur_yolu=dur_yolu, dex_adlari=dexler)
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, d.durdur)
        return await d.calis()
    ozet = asyncio.run(kos())
    print(json.dumps({"kopma": ozet["genel"]["kopma"], "yeniden_baglanma": ozet["genel"]["yeniden_baglanma"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
