"""Canlı motor (T4; K‑29): tek süreç, iki kip (sanal / gerçek), TEK kod yolu. docs/GOREV_T4_CANLI_MOTOR.md, docs/RADAR_V1.md §5–§6.

Akış: `dinleyici.py` WebSocket (trades + userFills; İlk 11'in sahadaki adresleri) → tekilleştirilmiş dolum (`Olay`) → trader pozisyon izleyicisi → `boyut.hedef_emir` (tek boyutlandırma) → risk (`risk.py`)
→ yürütücü (`yurutucu.py`: sanal l2Book yürüyüşü / gerçek HL SDK) → hesap (`hesap.py`) → kayıt JSONL + Telegram. Saha kararları `kadro.py` (kadro.json, her 5 dk).

Kip güvencesi (G4): varsayılan SANAL. `gercek` YALNIZ sunucu ortamında `CANLI_KIP=gercek` + `HL_API_CUZDAN_ANAHTARI`/`HL_HESAP_ADRESI` ile (`kurallar.yaml canli_kip` yalnız `sanal`; depodan gerçek kip açılamaz) ve ASLA GitHub Actions'ta (`GITHUB_ACTIONS=true` + `CANLI_*` → ret).
Kasa: sanal kip `canli_kasa_usd` (yaml) ya da `--sanal-kasa-usd` (yalnız sanal; 0 < kasa ≤ `canli_sanal_kasa_ust_usd` (K-66: 10.000 $); ayrı durum dizini/veri dalı, ör. 300 $ paralel seri `canli-durum-300`); gerçek kip `CANLI_KASA_USD` ortam değişkeni ($, zorunlu; üst sınır `canli_kasa_ust_usd` = 1.500 $ — AGENTS.md, K-72): sınır aşılırsa yeni açılış yok + alarm.
T4b (K‑37): kapanış teyidi + yeniden deneme (`kapanis_kuyrugu`), emir öncesi niyet kaydı + cloid (`niyet.py`), gerçek kipte risk temeli HL özsermayesi, sanal kipte funding, gecikmiş AÇILIŞ yok
(`gec_acilis`: olay yaşı > `canli_olay_stale_sn`; kapanış/azaltma yaşa bakmaz), öncelikli kuyruk (kapat/azalt önce), kendi hesap adresimiz kayıt/Telegram'a yazılmaz.
`DUR` dosyası varken motor başlamaz (elle silinmeden yeniden açılmaz).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import re
import shutil
import signal
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from copytrade import boyut
from copytrade.canli import telegram as tg
from copytrade.canli.hesap import Hesap, dinamik_stop_orani
from copytrade.canli.kadro import Karar, Saha, kadro_taze_mi
from copytrade.canli.mutabakat import poz_farki, sanal_tutarlilik
from copytrade.canli.niyet import Niyet, cloid_uret
from copytrade.canli.ogrenme_adaptor import Ogrenme
from copytrade.canli import borsa_stop, izleme
from copytrade.canli import haber, rejim, rejim_sonuc, secim_gercek
from copytrade.canli import gunluk_ozet, kaynak
from copytrade.canli import sert_sinirlar as sert
from copytrade.canli.borsa_stop import BorsaStop
from copytrade.canli.risk import Risk, coin_tavan_usd, gun
from copytrade.canli.yurutucu import AnahtarYok, Dolum, SanalYurutucu, Yurutucu, gercek_yurutucu_olustur, ucret_eslestir
from copytrade.dinleyici import Ayar, Dinleyici, Izlenen, Olay, clearinghouse_ayristir, clearinghouse_giris_pxleri, clearinghouse_pozisyonlari, clearinghouse_yuk, coin_listesi, rest_dolumlar, rest_post_fabrikasi, ws_baglan
from copytrade.hl_ortak import spot_usdc
from copytrade.izleme_liste import perp_dex_names
from copytrade.kurallar import load_rules
from copytrade.coin_sinif import asset_class
from copytrade.tarama import KAPI_YENIDEN_BEKLEME, PublicClient, RateLimiter, RateLimitError, ledger_sayfala

EPS = 1e-12
DAKIKA = 60_000
SON_ATLA_MAX = 3000          # adet (K-75: "adres|coin" başına son açılış atlama nedeni; aşılırsa en eskiler düşer)
TELAFI_YENIDEN_DENE = ("gec_acilis", "trader_hesap_yok", "hesap_yok", "hip3_atlandi")      # K-75 (hip3_atlandi: K-73 öncesi kalan atlama; açılış yine güncel HIP-3 kuralından geçer): bu nedenlerle atlanan açılış "kaçmış" sayılır (kural/filtre değil, veri/zaman) → telafi edilebilir; diğer atlama nedenlerine saygı gösterilir
SNAP_SAKLA = 50_000          # adet (yalnız snapshot görülen dolum kimlikleri, bellekte; HL userFills snapshot'ı adres başına ≤ 2000 dolum × 10 adres + trades snapshot'ları)


ADIM_ALARM_ARDISIK = 3                     # M-2: aynı dakikalık adım üst üste bu kadar hata verirse Telegram alarmı
KUYRUK_GERI_DK = (1, 2, 4, 8, 16, 30)      # S-8: kapanış kuyruğu yeniden deneme aralıkları (dk; üstel, tavan 30)
AGIRLIK = {"allMids": 2, "l2Book": 2, "clearinghouseState": 2, "perpDexs": 20, "orderStatus": 2, "meta": 20, "metaAndAssetCtxs": 20, "userFillsByTime": 20, "spotClearinghouseState": 2, "userRole": 60}          # HL info istek ağırlıkları (belge); bilinmeyen 20


class GuvenliLimiter(RateLimiter):
    """Birden çok iş parçacığı (olay işleme, dakikalık bakım, dinleyici REST) aynı hız sınırını paylaşır: `acquire` kilitli (sıraya girer).
    2. denetim O-3: PAYLAŞILAN 429 SOĞUMASI — herhangi bir istemci 429 alınca `sogut(sn)` çağırır; soğuma bitmeden hiçbir iş parçacığı istek atmaz (normal istemci bekler; "hızlı" istemci, kilit altı okumalar,
    `azami_bekleme` verdiği için BEKLEMEDEN `RateLimitError` alır). Saat/uyku taban sınıfın `clock`/`sleep`ı (testte enjekte)."""

    def __init__(self, *a: Any, **k: Any) -> None:
        super().__init__(*a, **k)
        self._kilit = threading.Lock()
        self._soguma_bit = 0.0                 # `clock()` zaman ekseninde soğumanın bitişi
        self._soguma_kilit = threading.Lock()

    def sogut(self, sn: float) -> None:
        with self._soguma_kilit:
            self._soguma_bit = max(self._soguma_bit, self.clock() + max(0.0, float(sn)))

    def soguma_kalan(self) -> float:
        with self._soguma_kilit:
            return max(0.0, self._soguma_bit - self.clock())

    def acquire(self, weight: int, azami_bekleme: float | None = None, soguma_atla: bool = False) -> None:
        kalan = 0.0 if soguma_atla else self.soguma_kalan()
        if kalan > 0:
            if azami_bekleme is not None:
                raise RateLimitError(f"paylaşılan 429 soğuması sürüyor ({kalan:.1f} sn): hızlı okuma beklemeden vazgeçti")
            self.sleep(kalan)                  # bir kez bekler (soğuma o arada uzarsa taban sınıf zaten ağırlık bütçesini bekler)
        if azami_bekleme is None:
            with self._kilit:
                super().acquire(weight)
            return
        if not self._kilit.acquire(timeout=azami_bekleme):             # başka iş parçacığı ağırlık bütçesi için uyuyor: hızlı okuma sırada beklemez
            raise RateLimitError("istemci tarafı hız sınırı kilidi meşgul: hızlı okuma beklemeden vazgeçti")
        try:
            super().acquire(weight, azami_bekleme)
        finally:
            self._kilit.release()


def rest_post_olustur(rules: dict, istemci: PublicClient | None = None) -> Callable[[dict], Any]:
    """Motorun TÜM REST istekleri (kural 7: `tarama.PublicClient`): ortak ağırlık sınırı `canli_api_agirlik_dk`, 429 (5 yeniden deneme, `Retry-After`) ve 5xx / ağ hatasında 3 yeniden deneme.
    Duman testinde (gerçek HL) açılışta ardışık `clearinghouseState` okumaları HTTP 429 aldı → bu sınırlayıcı eklendi.
    Kilit altı okumalar için KISA MERDİVENLİ eş: `rest_post_hizli_olustur` (2. denetim O-3)."""
    c = istemci or PublicClient(limiter=GuvenliLimiter(limit=int(rules["canli_api_agirlik_dk"])), yeniden_bekleme=KAPI_YENIDEN_BEKLEME)

    def post(yuk: dict) -> Any:
        return c.info(yuk, weight=AGIRLIK.get(str(yuk.get("type")), 20))
    post.stats = getattr(c, "stats", None)                 # type: ignore[attr-defined] — rapor için istek / 429 sayaçları (T6 §3)
    post.istemci = c                                        # type: ignore[attr-defined] — hızlı eşin oturum/sınırlayıcıyı paylaşması için
    return post


def rest_post_hizli_olustur(post: Callable[[dict], Any]) -> Callable[[dict], Any]:
    """`rest_post_olustur` sonucunun oturumunu ve (paylaşılan 429 soğumalı) sınırlayıcısını kullanan KISA MERDİVENLİ eş (429'da ≤ 2 sn bir deneme, ağda ≤ 1 sn bir deneme, 4 sn zaman aşımı; soğuma sürüyorsa
    BEKLEMEDEN hata): motorun KİLİT ALTI okumaları için (`Motor.post_hizli`). Test sahtesi (`istemci` yok) → aynı `post`."""
    c = getattr(post, "istemci", None)
    if not isinstance(c, PublicClient):
        return post
    return rest_post_olustur({}, PublicClient(session=c.session, limiter=c.limiter, sleep=c.sleep, hizli=True))


def hesap_soyutlama(post: Callable[[dict], Any], adres: str) -> str:
    """HL hesap tipi (`userAbstraction`): "unifiedAccount" | "portfolioMargin" | klasik ("default", "disabled", "dexAbstraction", None …). Okuma hatası istisna (kısmi payda yok)."""
    r = post({"type": "userAbstraction", "user": adres})
    return str(r) if r is not None else ""


def portfolio_son_deger(post: Callable[[dict], Any], adres: str) -> float:
    """HL `portfolio` gün serisinin son `accountValue` noktası (HL'nin kendi özsermaye tanımı). Yoksa ValueError."""
    for pencere, veri in post({"type": "portfolio", "user": adres}) or []:
        if pencere == "day" and (veri or {}).get("accountValueHistory"):
            return float(veri["accountValueHistory"][-1][1])
    raise ValueError("portfolio: gün serisi yok")


def anlik_kaldirac_hesapla(poz: dict[str, float] | None, marks: dict[str, float], hesap_usd: float | None) -> float | None:
    """Trader'ın anlık kaldıracı (x) = açık perp nosyoneli (Σ |boyut| × mark) / trader hesap değeri (`hesap_degeri_oku` ile AYNI payda: perp accountValue + spot USDC).
    Yalnız bilgi/kayıt (işlem etkisi yok). Pozisyon listesi, payda ya da herhangi bir coinin mark'ı yoksa None (bilinmiyor; 0 sayılmaz). Pozisyonsuz hesap = 0,0x."""
    if poz is None or not hesap_usd or hesap_usd <= 0 or not math.isfinite(hesap_usd):
        return None
    notional = 0.0
    for coin, sz in poz.items():
        if not sz:
            continue
        mark = marks.get(coin)
        if not mark:
            return None
        notional += abs(float(sz)) * float(mark)
    return notional / hesap_usd


def hesap_degeri_oku(post: Callable[[dict], Any], adres: str, dexler: list[str] | None) -> float | None:
    """G-6: `dexler` None (dex listesi bilinmiyor) → None (kısmi toplam YOK; çağıran hesabı bilinmiyor sayar). Hesap değeri ($), hesap tipine göre (K-65 eki 13.11, Fable denetimi):
    - klasik: TÜM perp dex'lerin `marginSummary.accountValue` toplamı + spot USDC `total` (K‑35 tek payda; radar lider tablosu `accountValue` ile aynı tanım);
    - birleşik (`unifiedAccount`): perp hesabı spot USDC'nin içinde — yalnız USDC `total` (HL `portfolio` değeriyle aynı; 14.11 düzeltmesi: `hold` bekleyen emir
      teminatını da içerir, `total − hold` pozisyonsuz ama emirli hesapta ~0 veriyordu — 0xfc76… 213.155 $ yerine 0,09 $);
    - portföy marjı (`portfolioMargin`; teminat USDC dışı, USDC borçlu olabilir): HL `portfolio` gün serisinin son değeri.
    Herhangi bir okuma başarısızsa istisna (kısmi toplam dönmez: oran paydası eksik olursa emirler şişer)."""
    if dexler is None:
        return None
    soyut = hesap_soyutlama(post, adres)
    if soyut == "portfolioMargin":
        deger = portfolio_son_deger(post, adres)
    else:
        durum = post({"type": "spotClearinghouseState", "user": adres}) or {}
        spot = sum(float(b.get("total", 0) or 0) for b in durum.get("balances", []) if str(b.get("coin")) == "USDC")
        if soyut == "unifiedAccount":
            deger = spot
        else:
            toplam = 0.0
            for dex in ["", *dexler]:
                toplam += float(post(clearinghouse_yuk(adres, dex))["marginSummary"]["accountValue"])
            deger = toplam + spot
    if not math.isfinite(deger) or deger <= 0:                  # 2. denetim D-10: NaN/inf/≤ 0 geçersiz (`not hesap_usd` NaN'ı geçirirdi; oran paydası bu değerle bölünür)
        raise ValueError("hesap değeri geçersiz")
    return deger


class KipHatasi(RuntimeError):
    """Kip kuralı ihlali (gerçek kip Actions'ta / ayar yok): motor BAŞLAMAZ."""


class DurumBozuk(KipHatasi):
    """Denetim-2 (K1): durum dosyası VAR ama okunamıyor (bozuk/yarım/dict değil) ya da motor.json var, hesap.json yok (defter kaybı). Gerçek kipte motor BAŞLAMAZ: boş defterle açılış
    borsa stoplarını iptal ettirir, pozisyonlar korumasız kalır. Elle onarım gerekir (hesap.json için son sağlam kopya: hesap.json.bak). Sanal kipte BAŞLAMA engellenmez (alarm + kayıt; bkz. Motor)."""


class HlOkunamadi(KipHatasi):
    """G-15: açılışta HL okuması (ağ, zaman aşımı, 5xx, 429, bozuk yanıt) başarısız — GEÇİCİ neden. `main` artan beklemeyle yeniden dener, olmazsa `CIKIS_GECICI` (75) ile çıkar
    (systemd `Restart=on-failure` yeniden başlatır). Kalıcı nedenler (DUR, kip uyumsuzluğu, ana anahtar, kasa sınırı, agent listede yok, çift süreç) `KipHatasi` → `CIKIS_KALICI` (3)."""


CIKIS_KALICI = 3             # kalıcı neden: systemd yeniden BAŞLATMAZ (`RestartPreventExitStatus=3`) + OnFailure alarmı
CIKIS_GECICI = 75            # EX_TEMPFAIL: geçici HL/ağ okuma hatası; systemd artan beklemeyle (30 sn → 10 dk) yeniden başlatır
ACILIS_BEKLEME_SN: tuple[float, ...] = (15.0, 45.0, 120.0)     # sn: açılış HL okumasında yeniden denemeler arası bekleme (PublicClient'ın kendi 5/15/45 sn denemelerine EK)
SAAT_SAPMA_SINIR_MS = 2000   # ms: `--kontrol` sunucu saati ile HL sunucu saati (l2Book `time`) farkı sınırı (gidiş-dönüş yarısı düşülerek)
_GECICI_HATALAR: tuple[type[BaseException], ...] = (HlOkunamadi, OSError, RateLimitError)       # OSError: requests ağ/zaman aşımı istisnaları dahil


def kasa_ust(rules: dict, kip: str) -> float:
    """Kasa üst sınırı ($): GERÇEK kip `canli_kasa_ust_usd` (1.500 $ sert sınır, K‑72); sanal kip `canli_sanal_kasa_ust_usd` (K-66: 10.000 $, yalnız sanal; anahtar yoksa gerçek sınır)."""
    gercek = float(rules["canli_kasa_ust_usd"])
    if kip == "gercek":
        return sert.etkin_kasa_ust(rules)                  # K-72: min(yaml, 1.500 $ sert sabit)
    return float(rules.get("canli_sanal_kasa_ust_usd", gercek))


def sanal_kasa_dogrula(rules: dict, kip: str, sanal_kasa: Any) -> float:
    """`--sanal-kasa-usd` ($): YALNIZ sanal kipte, sonlu ve 0 < kasa ≤ `kasa_ust(rules, "sanal")` (K-66). Gerçek kipte / sınır dışında KipHatasi (gerçek kip kasası yalnız sunucuda `CANLI_KASA_USD`, ≤ 1.000 $)."""
    if kip != "sanal":
        raise KipHatasi("--sanal-kasa-usd yalnız sanal kipte kullanılabilir (gerçek kip kasası yalnız sunucu ortamından)")
    try:
        kasa = float(sanal_kasa)
    except (TypeError, ValueError) as hata:
        raise KipHatasi(f"--sanal-kasa-usd sayı değil: {str(sanal_kasa)[:20]}") from hata
    ust = kasa_ust(rules, "sanal")
    if not math.isfinite(kasa) or kasa <= 0 or kasa > ust + 1e-9:
        raise KipHatasi(f"--sanal-kasa-usd 0 < kasa <= {ust:g} $ olmalı: {str(sanal_kasa)[:20]}")
    return kasa


def kasa_belirle(rules: dict, kip: str, ortam: dict | None = None, sanal_kasa: float | None = None) -> tuple[float, str]:
    """Ayarlı kasa ($) ve kaynağı. Sanal kip: `sanal_kasa` (`--sanal-kasa-usd`) verildiyse o → "arg"; yoksa `canli_kasa_usd` (yaml) → "yaml"; `CANLI_KASA_USD` YOK SAYILIR (sanal seri 1.000 $ kalır).
    Gerçek kip: `sanal_kasa` verilirse KipHatasi; `CANLI_KASA_USD` ortam değişkeni ZORUNLU, 0 < kasa ≤ `canli_kasa_ust_usd` (G4; K‑22) → "ortam". Aksi halde KipHatasi."""
    ortam = os.environ if ortam is None else ortam
    if sanal_kasa is not None:
        return sanal_kasa_dogrula(rules, kip, sanal_kasa), "arg"
    if kip != "gercek":
        return float(rules["canli_kasa_usd"]), "yaml"
    try:
        sert.gercek_kip_dogrula(rules)                     # K-72: yaml sert sınırı aşarsa gerçek kip başlamaz
    except ValueError as hata:
        raise KipHatasi(f"sert sınır aşıldı: {hata}") from hata
    ham = str(ortam.get("CANLI_KASA_USD", "")).strip()
    if not ham:
        raise KipHatasi("gercek kip için CANLI_KASA_USD ortam değişkeni ($) gerekli")
    try:
        kasa = float(ham)
    except ValueError as hata:
        raise KipHatasi(f"CANLI_KASA_USD sayı değil: {ham[:20]}") from hata
    ust = kasa_ust(rules, "gercek")
    if not math.isfinite(kasa) or kasa <= 0 or kasa > ust + 1e-9:
        raise KipHatasi(f"CANLI_KASA_USD 0 < kasa <= {ust:g} $ olmalı: {ham[:20]}")
    return kasa, "ortam"


def etkin_kasa(rules: dict, kip: str, post: Callable[[dict], Any], ortam: dict | None = None, sanal_kasa: float | None = None) -> tuple[float, float | None]:
    """Kullanılan kasa: sanal kip `canli_kasa_usd` (yaml); GERÇEK kip min(`CANLI_KASA_USD` ortamı, HL hesap değeri) (K‑35; hesapta daha fazla olsa da ayarın üstü kullanılmaz). Döner (etkin kasa, HL hesap değeri | None)."""
    ortam = os.environ if ortam is None else ortam
    kasa, _ = kasa_belirle(rules, kip, ortam, **({} if sanal_kasa is None else {"sanal_kasa": sanal_kasa}))          # bayrak yoksa çağrı birebir eskisi
    if kip != "gercek":
        return kasa, None
    try:
        dexler = perp_dex_names(post({"type": "perpDexs"}))
        hl = hesap_degeri_oku(post, ortam["HL_HESAP_ADRESI"], dexler)
    except Exception as hata:                              # noqa: BLE001
        raise HlOkunamadi(f"HL hesap değeri okunamadı ({type(hata).__name__}): gerçek kipte kasa belirlenemez") from hata          # G-15: geçici (KipHatasi alt sınıfı)
    return min(kasa, hl), hl


def hl_deger_ust(rules: dict) -> float:
    """K‑22 (09.11): gerçek kip AÇILIŞ ve `--kontrol` HL hesap değeri tavanı ($) = `canli_hl_deger_ust_usd` (1.500). Kasa sınırı (`canli_kasa_ust_usd` = 1.000) AYRI ve değişmez: etkin kasa = min(CANLI_KASA_USD, HL) ≤ 1.000.
    Ayrım nedeni: kârlı günden sonra (HL 1.012 $) yeniden başlatma çıkış 3 ile kalıcı reddedilir ve açık pozisyonlar yönetimsiz kalırdı. Anahtar yoksa eski davranış (kasa sınırı)."""
    return float(rules.get("canli_hl_deger_ust_usd", rules["canli_kasa_ust_usd"]))


def anahtardan_adres(anahtar: str) -> str:
    """API cüzdan anahtarından adres türetir (`eth_account`; tembel içe aktarma). Yoksa ImportError. Anahtar/adres hiçbir yere yazılmaz."""
    from eth_account import Account
    return str(Account.from_key(anahtar).address)


_ADRES_RE = re.compile(r"0x[0-9a-f]{40}")


def _gecerli_ms(valid_until: Any, simdi_ms: int) -> bool:
    """extraAgents `validUntil` (ms): yoksa/geçersizse/süresi dolmuşsa (şimdi ≥ validUntil) False."""
    if isinstance(valid_until, bool) or not isinstance(valid_until, (int, float)) or not math.isfinite(valid_until):
        return False
    return simdi_ms < valid_until


def _kucuk(x: Any) -> str:
    return str(x or "").strip().lower()


def api_cuzdan_dogrula(post: Callable[[dict], Any], ortam: dict, turet: Callable[[str], str] | None = None, simdi_ms: int | None = None) -> dict:
    """G6 (Y3): gerçek kipte API cüzdanı doğrulaması — EMİR GÖNDERMEZ. Döner yalnız bool/sabit metin: {"ana_anahtar", "agent_dogrulandi", "tamam", "neden"}; anahtar ve adresler ASLA döndürülmez.
    (1) anahtardan türetilen adres == `HL_HESAP_ADRESI` → ana cüzdan anahtarı (para çekme yetkisi riski) → ret. Türetme yapılamazsa (eth_account yok/anahtar bozuk) → ret.
    (2) HL `userRole` (gerçek biçim: `{"role":"agent","data":{"user":<ana hesap>}}`) agent ve bağlı hesap == `HL_HESAP_ADRESI`; bulunamazsa ikinci yöntem `extraAgents` listesi (`[{"name","address","validUntil"}]`).
    Hiçbiri doğrulamazsa "agent doğrulanamadı" → ret."""
    r: dict[str, Any] = {"ana_anahtar": False, "agent_dogrulandi": False, "tamam": False, "neden": None, "hl_okunamadi": False}       # G-15: hl_okunamadi = iki yöntem de HL'den yanıt alamadı (geçici)
    anahtar, hesap = str(ortam.get("HL_API_CUZDAN_ANAHTARI") or "").strip(), _kucuk(ortam.get("HL_HESAP_ADRESI"))
    if not anahtar or not hesap:
        r["neden"] = "anahtar veya hesap adresi yok"
        return r
    try:
        agent = _kucuk((turet or anahtardan_adres)(anahtar))
        if not agent:
            raise ValueError("boş adres")
    except Exception as hata:                              # noqa: BLE001 - ImportError dahil; hata metni anahtar içerebilir: yalnız tür adı
        r["neden"] = f"anahtardan adres türetilemedi ({type(hata).__name__})"
        return r
    if not _ADRES_RE.fullmatch(agent) or not _ADRES_RE.fullmatch(hesap):
        r["neden"] = "adres biçimi geçersiz"                # adresin kendisi mesaja YAZILMAZ
        return r
    if agent == hesap:
        r["ana_anahtar"] = True
        r["neden"] = "ana cüzdan anahtarı kullanılıyor (para çekme yetkisiz API cüzdanı gerekli)"
        return r
    yanit_alindi = False                                   # G-15: HL'den en az bir geçerli biçimli yanıt geldi mi (gelmediyse "agent yok" DEĞİL, "HL okunamadı": geçici)
    try:
        rol = post({"type": "userRole", "user": agent})
        veri = rol.get("data") if isinstance(rol, dict) else None
        yanit_alindi = isinstance(rol, dict) and "role" in rol
        if isinstance(rol, dict) and rol.get("role") == "agent" and isinstance(veri, dict) and _kucuk(veri.get("user")) == hesap:
            r["agent_dogrulandi"] = True
    except Exception:                                      # noqa: BLE001 - ikinci yönteme düş
        pass
    if not r["agent_dogrulandi"]:
        try:
            liste = post({"type": "extraAgents", "user": str(ortam.get("HL_HESAP_ADRESI") or "").strip()})
            su_an = int(time.time() * 1000) if simdi_ms is None else simdi_ms
            yanit_alindi = yanit_alindi or isinstance(liste, list)
            if isinstance(liste, list) and any(isinstance(a, dict) and _kucuk(a.get("address")) == agent and _gecerli_ms(a.get("validUntil"), su_an) for a in liste):
                r["agent_dogrulandi"] = True
        except Exception:                                  # noqa: BLE001
            pass
    if not r["agent_dogrulandi"]:
        r["hl_okunamadi"] = not yanit_alindi
        r["neden"] = "agent doğrulanamadı" if yanit_alindi else "HL okunamadı (agent denetimi yapılamadı)"
        return r
    r["tamam"] = True
    return r


def ajan_bitis_oku(post: Callable[[dict], Any], ortam: dict, turet: Callable[[str], str] | None = None) -> dict:
    """G-19: API cüzdanının (agent) HL `extraAgents` listesindeki `validUntil`'i (ms, UTC). EMİR GÖNDERMEZ; anahtar/adres DÖNMEZ.
    Döner {"durum": "bulundu", "valid_until": ms | None} | {"durum": "listede_yok", "agent_rol": bool} | {"durum": "okunamadi", "tur": hata türü}."""
    anahtar, hesap = str(ortam.get("HL_API_CUZDAN_ANAHTARI") or "").strip(), str(ortam.get("HL_HESAP_ADRESI") or "").strip()
    if not anahtar or not hesap:
        return {"durum": "okunamadi", "tur": "anahtar_yok"}
    try:
        agent = _kucuk((turet or anahtardan_adres)(anahtar))
        liste = post({"type": "extraAgents", "user": hesap})
    except Exception as hata:                              # noqa: BLE001 - hata metni anahtar içerebilir: yalnız tür adı
        return {"durum": "okunamadi", "tur": type(hata).__name__}
    for a in liste if isinstance(liste, list) else []:
        if isinstance(a, dict) and _kucuk(a.get("address")) == agent:
            vu = a.get("validUntil")
            return {"durum": "bulundu", "valid_until": int(vu) if isinstance(vu, (int, float)) and not isinstance(vu, bool) and math.isfinite(vu) else None}
    try:                                                   # listede yoksa: userRole hâlâ agent diyorsa süresiz/başka yolla onaylı (alarm yok)
        rol = post({"type": "userRole", "user": agent})
        veri = rol.get("data") if isinstance(rol, dict) else None
        agent_rol = isinstance(rol, dict) and rol.get("role") == "agent" and isinstance(veri, dict) and _kucuk(veri.get("user")) == _kucuk(hesap)
    except Exception:                                      # noqa: BLE001
        return {"durum": "okunamadi", "tur": "userRole"}
    return {"durum": "listede_yok", "agent_rol": bool(agent_rol)}


def kip_belirle(rules: dict, istenen: str | None = None, ortam: dict | None = None) -> str:
    """`sanal` (varsayılan) | `gercek`. `gercek` YALNIZ `CANLI_KIP=gercek` ortamıyla + anahtarlar + GitHub Actions DEĞİL; `kurallar.yaml canli_kip` yalnız `sanal` olabilir.
    Aksi halde KipHatasi (sessizce sanala DÜŞMEZ: yanlış beklenti)."""
    ortam = os.environ if ortam is None else ortam
    if str(rules.get("canli_kip", "sanal")).strip().lower() != "sanal":
        raise KipHatasi("kurallar.yaml canli_kip yalnız sanal olabilir; gercek kip depodan açılamaz (sunucuda CANLI_KIP=gercek)")
    if ortam.get("GITHUB_ACTIONS") == "true" and any(str(k).startswith("CANLI_") for k in ortam):
        raise KipHatasi("GitHub Actions'ta CANLI_* ortam değişkeni olamaz (kip/kasa yalnız sunucu ortamından)")
    ortam_kip = str(ortam.get("CANLI_KIP", "")).strip().lower()
    if ortam_kip not in ("", "sanal", "gercek"):
        raise KipHatasi(f"bilinmeyen CANLI_KIP: {ortam_kip[:20]}")
    kip = (istenen or ortam_kip or "sanal").strip().lower()
    if kip not in ("sanal", "gercek"):
        raise KipHatasi(f"bilinmeyen kip: {kip}")
    if kip == "gercek":
        if ortam.get("GITHUB_ACTIONS") == "true":
            raise KipHatasi("gercek kip GitHub Actions'ta çalışmaz")
        if ortam_kip != "gercek":
            raise KipHatasi("gercek kip için CANLI_KIP=gercek ortam değişkeni gerekli")
        if not (ortam.get("HL_API_CUZDAN_ANAHTARI") and ortam.get("HL_HESAP_ADRESI")):
            raise AnahtarYok("HL_API_CUZDAN_ANAHTARI ve HL_HESAP_ADRESI gerekli")
    return kip


def eylem_belirle(once: float, sonra: float, biz_sz: float) -> list[str]:
    """Trader dolumu (işaretli pozisyon önce → sonra) ve bizim pozisyonumuz → yürütülecek eylem sırası (`boyut.hedef_emir` eylemleri): kapat | azalt | ac | artir.
    Ters dönüş = [kapat (varsa), ac]. Bizde pozisyon yokken trader azaltıyorsa eylem yok.
    G-3: bizim pozisyon trader'ın SONRAKİ yönüne TERS ise (kaçan ters dönüş) önce reduce-only kapat, sonra hedefe göre aç → ters yönde reduce-only OLMAYAN emir hiç gitmez."""
    if abs(sonra) < EPS:
        return ["kapat"] if abs(biz_sz) > EPS else []
    if abs(biz_sz) > EPS and biz_sz * sonra < 0:
        return ["kapat", "ac"]
    if once * sonra < 0:
        return (["kapat"] if abs(biz_sz) > EPS else []) + ["ac"]
    if abs(sonra) > abs(once) + EPS:
        return ["ac"] if abs(biz_sz) < EPS else ["artir"]
    return ["azalt"] if abs(biz_sz) > EPS else []


def coin_sinifi(coin: str) -> str:
    """K‑42: 'spot' | 'hip3' (`dex:COIN`) | 'perp'. Tek kaynak `coin_sinif.asset_class` (numpy gerektirmez) (spot ve `dex:` ayrımı); burada yalnız üç sınıfa indirgenir."""
    sinif = asset_class(coin)
    return "spot" if sinif == "spot" else "perp" if sinif == "kripto" else "hip3"


@dataclass
class Sonuc:
    adres: str
    coin: str
    eylem: str
    karar: str                 # emir | atlandi | engel | red
    neden: str = ""
    dolum: Dolum | None = None


class Kayit:
    """Günlük JSONL (`kayit/<tarih>.jsonl`): her olay tek satır; yazma hatası motoru durdurmaz."""

    def __init__(self, dizin: Path, saat_ms: Callable[[], int]) -> None:
        self.dizin, self.saat_ms = dizin, saat_ms
        self.sayac: dict[str, int] = {}
        self._onarildi: set[Path] = set()                  # D-7: bu süreçte yarım son satırı denetlenen günlük dosyaları

    def _yarim_onar(self, yol: Path) -> None:
        """D-7: çökme son satırı '\n'siz bıraktıysa yeni satır ona YAPIŞMASIN (`niyet._ekle` deseni): dosya başına süreçte bir kez bakılır."""
        if yol in self._onarildi:
            return
        self._onarildi.add(yol)
        with yol.open("a+b") as f:
            if f.seek(0, os.SEEK_END) > 0:
                f.seek(-1, os.SEEK_END)
                if f.read(1) != b"\n":
                    f.write(b"\n")

    def __call__(self, olay: dict) -> None:
        ms = self.saat_ms()
        olay = {"zaman_ms": ms, **olay}
        self.sayac[olay.get("olay", "?")] = self.sayac.get(olay.get("olay", "?"), 0) + 1
        try:
            self.dizin.mkdir(parents=True, exist_ok=True)
            yol = self.dizin / f"{gun(ms)}.jsonl"
            self._yarim_onar(yol)
            with yol.open("a", encoding="utf-8") as f:
                f.write(maskele(json.dumps(olay, ensure_ascii=False, separators=(",", ":"), default=str)) + "\n")
        except OSError:
            self.sayac["yazma_hatasi"] = self.sayac.get("yazma_hatasi", 0) + 1


MASKE: list[str] = []          # kayıt/durum/Telegram çıktılarında gizlenecek değerler (gerçek kipte kendi HL hesap adresimiz; K‑37 §10)


def maskele(metin: str) -> str:
    for m in MASKE:
        metin = re.sub(re.escape(m), "[hesap]", metin, flags=re.I)
    return metin


def _yedekle(yol: Path) -> None:
    """Denetim-2: yazımdan ÖNCE mevcut SAĞLAM (geçerli JSON nesnesi) dosya `<ad>.bak` olur (atomik); bozuk dosya sağlam yedeği ezmez. Hata sessiz (yedek yardımcıdır)."""
    try:
        if not yol.is_file():
            return
        eski = yol.read_text(encoding="utf-8")
        if isinstance(json.loads(eski), dict):
            bak = yol.with_name(yol.name + ".bak")
            gb = bak.with_name(bak.name + ".tmp")
            gb.write_text(eski, encoding="utf-8")
            os.replace(gb, bak)
    except (OSError, ValueError):
        pass


def _iso_z(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _yaz(yol: Path, veri: Any) -> None:
    yol.parent.mkdir(parents=True, exist_ok=True)
    gecici = yol.with_suffix(yol.suffix + ".tmp")
    with gecici.open("w", encoding="utf-8") as f:                      # ATOMİK (K‑37 t4b #3): geçici dosya + fsync + os.replace + dizin fsync (çökmede yarım dosya ya da kayıp yeniden adlandırma yok)
        f.write(maskele(json.dumps(veri, ensure_ascii=False, indent=1, sort_keys=True)) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(gecici, yol)
    try:
        dfd = os.open(yol.parent, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:                                                    # dizin fsync desteklenmeyen dosya sistemi: dosya fsync'i yine yapıldı
        pass


def _oku(yol: Path) -> dict | None:
    try:
        return json.loads(yol.read_text(encoding="utf-8")) if yol.is_file() else None
    except (OSError, ValueError):
        return None


def _oku_siki(yol: Path) -> dict | None:
    """Denetim-2: dosya yoksa None; VAR ama okunamıyor / geçerli JSON nesnesi değilse DurumBozuk (bozukluk "dosya yok" sayılmaz)."""
    if not yol.is_file():
        return None
    try:
        veri = json.loads(yol.read_text(encoding="utf-8"))
    except (OSError, ValueError) as hata:
        raise DurumBozuk(f"{yol.name} okunamadı ({type(hata).__name__}): elle onarın (hesap.json için son sağlam kopya: hesap.json.bak); motor başlamadı") from hata
    if not isinstance(veri, dict):
        raise DurumBozuk(f"{yol.name} geçerli bir nesne değil ({type(veri).__name__}): elle onarın; motor başlamadı")
    return veri


def bot_durdu_gonder(tgram: tg.Telegram, durum_dizin: Path, neden: str, acik: int, stop_durumu: str, ek: str = "", son: str | None = None, senden: str | None = None) -> None:
    """🔴 Bot durdu: sesli (CRIT), 6 saatlik tekrar sınırı yok; `durum/tg_bot_durdu` işareti yazılır → bot yeniden çalışınca `baslat` tek 'Düzeldi' yollar. Hata dışarı çıkmaz."""
    try:
        kw = {"senden": senden} if senden else {}
        tgram.gonder(tg.msg_bot_durdu(neden, acik, stop_durumu, ek, son=son, **kw))                 # 🔴 öneki → CRIT (sesli); anahtar = metin (aynı metin 5 dk içinde bir kez)
        (Path(durum_dizin) / "tg_bot_durdu").write_text(f"{int(time.time())}\n{tg.BOT_NEDEN_TR.get(neden, tg.sade_ad(neden))}\n")      # 1. satır: başlangıç (epoch sn); 2. satır: neden (alarm_ikinci.sh)
    except Exception:                                      # noqa: BLE001 - mesaj/işaret hatası çıkışı değiştirmez
        pass


def durumdan_acik_poz(durum_dizin: Path) -> int | None:
    """Motor yokken (çökme sonrası) diskteki defterden açık pozisyon sayısı; okunamazsa None."""
    try:
        d = json.loads((Path(durum_dizin) / "hesap.json").read_text(encoding="utf-8"))
        return sum(len(c) for c in (d.get("poz") or {}).values())
    except Exception:                                      # noqa: BLE001
        return None


class Motor:
    """Olay işleme + periyodik görevler. `post`: HL info (REST); `yurutucu`: emir arka ucu; `kadro_oku()`: kadro.json sözlüğü ya da None; `saat_ms`: enjekte (testte sahte)."""

    def __init__(self, rules: dict, yurutucu: Yurutucu, post: Callable[[dict], Any], telegram: tg.Telegram, durum_dizin: Path, kayit_dizin: Path,
                 kadro_oku: Callable[[], dict | None], saat_ms: Callable[[], int] | None = None, vardiya_id: str = "yerel",
                 post_hizli: Callable[[dict], Any] | None = None) -> None:
        self.rules, self.yurutucu, self.post, self.tg = rules, yurutucu, post, telegram
        self._post_hizli = post_hizli                              # O-3: KİLİT ALTI REST okumaları kısa merdivenli istemciyle (verilmezse `post` izlenir: testler/sahte)
        self.durum_dizin, self.kadro_oku = durum_dizin, kadro_oku
        self.saat_ms = saat_ms or (lambda: int(time.time() * 1000))
        self.kayit = Kayit(kayit_dizin, self.saat_ms)
        self.tg.kayit = self.kayit
        self.kip = yurutucu.kip
        self.radar_surum_gerekli: str | None = None                # K-54: `copytrade/canli/RADAR_SURUM` (main() okur); None = her kadro uygulanır
        self.donem: str | None = None                              # BTC al-tut kıyası: `copytrade/canli/DONEM` (UTC ISO; main() okur); None = kıyas yok ("—")
        self.tg.kip = self.kip                                                      # S-22: alarm başlıklarına kip etiketi
        self.tg.tampon_sn = float(rules.get("canli_telegram_gercek_tampon_sn", 0) or 0) if self.kip == "gercek" else 0.0      # G-18: gerçek kip emir mesajı birleştirme
        self.vardiya_id = vardiya_id
        self.kasa = float(rules["canli_kasa_usd"])
        self.kasa_ayar = float(rules.get("canli_kasa_ayar_usd", self.kasa))        # G5: ayarlı kasa ($; gerçek kip CANLI_KASA_USD). `kasa` etkin (min(ayar, HL değeri)) ve oynak; uyuşmazlık denetimi ayara bakar
        self.dur_dosyasi = durum_dizin / "DUR"
        self.durum_bozuk: list[str] = []                           # Denetim-2: sanal kipte okunamayan durum dosyaları (baslat: alarm + kayıt); gerçek kipte DurumBozuk ile BAŞLAMAZ

        def oku(ad: str) -> dict | None:
            yol = durum_dizin / ad
            try:
                return _oku_siki(yol)
            except DurumBozuk:
                if self.kip == "gercek":
                    raise
                self.durum_bozuk.append(ad)                        # sanal: Actions vardiya zincirini kilitlememek için başlar (alarm + kayıt); bozuk dosya `.bozuk` olarak saklanır
                try:
                    shutil.copy2(yol, yol.with_name(ad + ".bozuk"))
                except OSError:
                    pass
                return None
        m = oku("motor.json") or {}
        h = oku("hesap.json")
        if self.kip == "gercek" and m and h is None:
            raise DurumBozuk("motor.json var, hesap.json yok: defter kaybı; elle mutabakat gerekli (hesap.json.bak varsa kontrol edin); motor başlamadı")
        self.hesap = Hesap.from_json(h) if h else Hesap(self.kasa, float(rules["canli_marj_kaldirac"]))
        self._hesap_yok = h is None                                                # hesap.json hiç yok: niyet dosyasındaki eski dolumlar yeni deftere OYNATILMAZ (hayalet pozisyon)
        self._oynat_gecis = h is not None and "son_niyet_cloid" not in h          # eski biçim hesap.json: geçiş (işaretçi = niyet dosyasının sonu, geçmiş oynatılmaz)
        self._kayitli_kip = str(m.get("kip") or "sanal")                           # G5: motor.json yoksa/eski biçimse (kip alanı yok) sanal sayılır
        self._kayitli_kasa_ayar = m.get("kasa_ayar_usd")                           # G5: gerçek kipte son kabul edilen ayarlı kasa; yoksa karşılaştırma yok
        self._durum_var = bool(m) or h is not None
        kasa_degisti = h is not None and self._kayitli_kasa_ayar is not None and abs(float(self._kayitli_kasa_ayar) - self.kasa_ayar) > 1e-9
        self._donem_eski: dict | None = None
        if h is not None and self.kip == "gercek" and self._kayitli_kip == "gercek" and not kasa_degisti:
            self.kasa = float(self.hesap.kasa_usd)               # G-5: kasa = DÖNEMİN başlangıç sermayesi (kalıcı). Zararla yeniden başlatmada min(ayar, HL) ile EZİLMEZ (zarar realize'da zaten var; iki kez sayılmaz)
        elif kasa_degisti and not any(self.hesap.poz.values()):
            self._donem_eski = self.hesap.donem_yenile(self.kasa, boyut.slot_usd(self.kasa, rules))      # S-3: yeni dönem (yalnız pozisyonsuz; G5 kuralı): slot tabanları yeni slota, eski net kapanmis_net'e
        else:
            self.hesap.kasa_usd = self.kasa                      # boş dizin / sanal kip (kasa sabit) / açık pozisyonla kasa değişikliği (baslat reddeder): eski davranış
        self.saha = Saha(rules, self.kasa, oku("saha.json") if self.kip == "gercek" else _oku(durum_dizin / "saha.json"))          # 2. denetim O-2: gerçek kipte bozuk saha.json DurumBozuk (boş saha → defterdeki pozisyonlar sahipsiz kalırdı)
        self.risk = Risk(rules, self.kasa, oku("risk.json"))
        self.borsa_stop = BorsaStop(oku("borsa_stop.json"))             # K-64: borsada duran felaket stopları (yalnız gerçek kip kullanır)
        if self.kip == "gercek":
            self.borsa_stop.kalici_yaz = lambda: _yaz(durum_dizin / "borsa_stop.json", self.borsa_stop.to_json())      # Denetim-6 (O3): stop cloid'i gönderimden ÖNCE diske
        if self._donem_eski is not None:
            self.risk.donem_yenile(self.hesap.ozsermaye({}))     # S-3: zirve / gün başı yeni dönem özsermayesine (500 → 300 geçişi zirve düşüşü sayılmaz)
        self._islenen: dict[str, None] = {}                     # işlenen (canlı) dolum kimlikleri, ekleme sırasıyla; G-14: sınır ADRES BAŞINA (`canli_islenen_adres_sakla`), tek yoğun adres diğerlerini düşürmez
        self._islenen_adres: dict[str, deque[str]] = {}
        for k in m.get("islenen", []):
            self._islenen_ekle(str(k))
        self._snap: dict[str, tuple[float, float]] = {}        # G-14/G-17b: yalnız snapshot (canlı değil) görülen kimlik -> (önce, sonra); aynı dolum sonra dolgu/rest ile gelirse poz_tr ikinci kez değişmez, emir bu değerlerle
        self.poz_tr: dict[str, dict[str, float]] = {a: dict(c) for a, c in (m.get("poz_tr") or {}).items()}       # trader işaretli pozisyonları (coin birimi)
        self.hesap_tr: dict[str, dict] = dict(m.get("hesap_tr") or {})                                              # adres -> {deger, ms}
        self.kaldirac_tr: dict[str, dict] = dict(m.get("kaldirac_tr") or {})                                          # adres -> {anlik_kaldirac, hesap_usd, ms}: yalnız pano/bilgi (işlem etkisi yok)
        self._golge_acik: dict[str, list[str]] = {a: list(k) for a, k in (m.get("golge_acik") or {}).items()}          # adres -> şu an doğru olan gölge kuralları (yalnız durum değişiminde kayıt)
        self.donem_seri: dict = _oku(durum_dizin / "donem_seri.json") or {}     # F-06: dönem boyu UTC gün sonu özsermaye + BTC serisi (pano 15 gün kırpmasından bağımsız, kalıcı)
        self.btc_donem: dict | None = m.get("btc_donem")          # BTC al-tut: {donem, bas_ms, fiyat, kaynak, okundu_ms}; dönem başında BİR kez okunur, motor.json'da kalıcı
        self.rejim_anlik: dict = m.get("rejim_anlik") or {}          # ML rejim etiketi (rejim.py): son okuma {gecerli_son_ms, rejimler}; kayıt + sanalda açılış filtresi (K-73 sanal_rejim_filtre)
        self.haber_anlik: dict = m.get("haber_anlik") or {}          # haber/duygu etiketi (haber.py): önbellek; kayıt + sanalda açılış filtresi (K-73 sanal_haber_filtre)
        self.rejim_4h_son: dict = m.get("rejim_4h_son") or {}        # coin -> son kaydedilen 4h rejimi (`rejim_degisti` tekilleştirme)
        self.son_olay_ms: int = int(m.get("son_olay_ms", 0))
        self._poz_tr_ms: dict[tuple[str, str], int] = {}              # (adres, coin) -> poz_tr'yi son güncelleyen trader dolum zamanı (kuyruktan düşen olayın geç uygulanması yeniyi ezmesin)
        for k, v in (m.get("poz_tr_ms") or {}).items():               # G-14: kalıcı (yeniden başlatmada snapshot'taki eski dolum poz_tr'yi ezmesin)
            a, _, c = str(k).partition("|")
            self._poz_tr_ms[(a, c)] = int(v)
        self._poz_tr_senk_ms: dict[str, int] = {a: int(v) for a, v in (m.get("poz_tr_senk_ms") or {}).items()}   # adres -> son REST pozisyon okumasının anı (ms, UTC); coin kaydı yoksa eşik budur
        if m and "poz_tr_senk_ms" not in m:                           # G-14 geçişi (eski biçim motor.json): poz_tr en az son işlenen dolum kadar taze sayılır
            self._poz_tr_senk_ms = {a: self.son_olay_ms for a in self.poz_tr}
        self.mutabakat_tutan: dict[str, dict] = {k: dict(v) for k, v in (m.get("mutabakat_tutan") or {}).items() if isinstance(v, dict)}      # Denetim-4: çözümde konan mutabakat notları (anahtar -> {coin, ms, neden}); borsa=defter teyidine dek bayrak kalkmaz
        self.sahipsiz_ilk: dict[str, dict] = {k: dict(v) for k, v in (m.get("sahipsiz_ilk") or {}).items() if isinstance(v, dict) and v.get("ms") is not None}      # 2. denetim O-2: defterde pozisyonu olup ne `uyeler` ne `inen`de olan adres -> {ms (ilk görülme), son (son tarama)}
        self.yetim_ilk: dict[str, dict] = {k: dict(v) for k, v in (m.get("yetim_ilk") or {}).items() if isinstance(v, dict)}      # Denetim-5 (K-68): defter dışı borsa fazlası, coin -> {ms (ilk görülme), mark (o andaki mark; stop referansı, SABİT), sz (son işaretli fazla)}; kesintisiz sürerse `canli_yetim_kapat_sn` sonra kapatılır
        self._hl_maks_kaldirac: dict[str, float] = {}               # Denetim-4: gerçek kip kaldıraç süzgeci için HL coin başına azami kaldıraç (yalnız bellek)
        self.baslama_ms: int = self.saat_ms()
        self.karsi_olgu: dict[str, dict] = {k: dict(v) for k, v in (m.get("karsi_olgu") or {}).items() if isinstance(v, dict)}       # alınmayan sinyal (yalnız kayıt): "adres|coin" -> {yon, hayali_usd, giris, neden, ms, son_pnl}
        self.karsi_olgu_gun: dict[str, list[float]] = {k: [float(x) for x in v] for k, v in (m.get("karsi_olgu_gun") or {}).items() if isinstance(v, list) and len(v) == 2}      # günlük özet: neden -> [adet, hayali K/Z $]
        self.kopya_drift: dict[str, dict] = {k: dict(v) for k, v in (m.get("kopya_drift") or {}).items() if isinstance(v, dict)}        # coin -> {bas_ms, aktif}: eşik üstü drift (yalnız uyarı)
        self.kopya_drift_tg_ms: dict[str, int] = {k: int(v) for k, v in (m.get("kopya_drift_tg_ms") or {}).items()}                  # coin -> son Telegram uyarısı (hız sınırı)
        self.son_atla: dict[str, list] = {k: [str(v[0]), int(v[1])] for k, v in (m.get("son_atla") or {}).items() if isinstance(v, list) and len(v) == 2}      # K-75: "adres|coin" -> [son açılış/artırma atlama nedeni, ms]; kaçan açılış telafisi filtre atlamasına saygı gösterir
        self._telafi_log: dict[str, str] = {}                           # K-75: "adres|coin" -> son kaydedilen telafi atlama nedeni (aynı neden her senkronda yeniden yazılmaz; yalnız bellek)
        self._telafi_yas: dict[str, tuple[int, int | None, bool]] = {}   # K-75 429 düzeltmesi: "adres|coin" -> (trader poz yönü işareti, açılış ms | None, bilinen_mi); pozisyon açıkken açılış anı değişmez (kapanınca/ters dönünce silinir)
        self._telafi_dolum: dict[str, tuple[int, list[dict]]] = {}      # adres -> (okuma ms, dolumlar): REST dolum geçmişi TTL önbelleği (`kacan_telafi_dolum_ttl_dk`)
        self._telafi_geri_bit_ms: int = 0                               # telafi geri çekilmesi bitiş (ms; yalnız telafi durur, kopya hızı etkilenmez)
        self._telafi_ardisik_429: int = 0                               # ardışık 429 sayısı (başarılı okumada sıfırlanır)
        self.marks: dict[str, float] = {}
        self.mark_ms: dict[str, int] = {}
        self.sayac = {"emir": 0, "dolu": 0, "kismi": 0, "dolmadi": 0, "red": 0, "atlandi": 0, "engel": 0, "gec_goruldu": 0, "gec_acilis": 0, "kapanis_eksik": 0, "min_nosyonel": 0, "funding_oran_yok": 0}
        self.kayma_trader: list[float] = []
        self.kayma_ref: list[float] = []
        self.dur_istendi = False
        self._son: dict[str, float] = {}
        self._ozet_gunu: str | None = m.get("ozet_gunu")
        self._ozet_oz: float | None = m.get("ozet_oz")              # önceki günlük özetteki özsermaye ("dünün sonucu" bundan hesaplanır)
        self._ozet_emir = int(m.get("ozet_emir", 0))               # önceki özetten beri emir sayısı
        self._poz_ozet: dict[str, dict] = {}                      # "adres|coin" -> {tutar (açılış+artırmalar $), artir, azalt, pnl}: kapandı mesajı (toplam tutar, % toplam tutara göre); yalnız bellek
        self._say_gun: dict[str, int] = {"ac": 0, "artir": 0, "azalt": 0, "kapat": 0}      # günlük rapor: dolu emir sayıları (eyleme göre)
        self._kopya_fark: list[float] = []                         # günlük rapor: |bizim dolum fiyatı / trader fiyatı − 1| (kopya sapması)
        self._gecikme: list[float] = []                            # günlük rapor: trader dolumu → bizim dolum (sn)
        self._islem_pen: dict[str, Any] = {"bas": None, "n": 0, "ac": 0, "kapat": 0, "net": 0.0}      # saatlik işlem-mesajı üst sınırı penceresi
        self._kesinti: dict | None = None                         # önceki oturum "Bot durdu" demişse: {"sn": kapalı kalma süresi}; Düzeldi `kesinti_duzeldi_bildir`de
        self._hafta_gunu: str | None = m.get("hafta_gunu")         # haftalık özet (Pazar 18:10 UTC = 21:10 TSİ): son gönderim günü; yalnız RAPOR, işlem mantığına girmez
        self._hafta_taban: dict | None = m.get("hafta_taban")      # {oz, btc, emir}: önceki haftalık özetteki özsermaye / BTC mark / emir sayacı
        self._emir_tampon: list[dict] = []                 # Telegram: emirler dakikalık adımda TEK özet mesajına toplanır
        self._atla_tampon: dict[str, int] = {}             # Telegram sanal saatlik özet: pencerede atlanan sinyaller (neden -> adet)
        self._atla_islem: set[tuple[str, str, int]] = set()  # S-13: atlanan dolumların ayrı işlemleri (adres, coin, trader_dolum_ms // 1000)
        self._atla_adres: dict[str, dict[str, int]] = {}  # S-13: neden -> {adres: adet} (ör. tek ayrılan trader adresi mesajda gösterilir)
        self._ozet_pencere_bas: int = self.baslama_ms      # saatlik özet penceresinin başı (motor saati); kalıcı DEĞİL (çökmede tampon kaybolabilir)
        self.kor_kirpildi: list[dict] = []
        self._boyut_girdi: dict | None = None                  # son _emir_isle boyut girdileri (emir kaydına eklenir, sonra silinir)
        self._kor_imza: dict[str, tuple] = {}                  # aday -> son kor_kirpildi imzası (tekrar kaydı önler)
        self.atlanan_trader: dict[str, dict[str, int]] = {"spot_atlandi": {}, "hip3_atlandi": {}}      # K‑42 bilgi: neden -> {adres: adet}
        self.neden_say: dict[str, int] = {}          # boyut / risk nedenleri sayacı (slot_tavani, marj_yok, coin_tavani …)
        self.niyet = Niyet(durum_dizin / "niyet.jsonl")
        self.ogrenme = Ogrenme(rules, durum_dizin / "ogrenme", self.kip, self.saat_ms, self.kayit, self.tg.gonder)      # ortak öğrenme (docs/ORTAK_OGRENME_CT.md): yalnız sanal kip; dersler yalnız riski azaltır
        if self.ogrenme.aktif:
            self.hesap.dinleyici = self.ogrenme.dolum
        if self._oynat_gecis:
            nl = [x["cloid"] for x in self.niyet.satirlar() if x.get("t") == "niyet"]
            self.hesap.son_niyet_cloid = nl[-1] if nl else None
        for k in self.niyet.kimlikler():                       # emir öncesi yazılmış kimlikler de "işlendi": çökme sonrası çift emir yok (K‑37 §3)
            self._islenen_ekle(k)
        self.kapanis_kuyrugu: dict[str, dict] = {k: dict(v) for k, v in (m.get("kapanis_kuyrugu") or {}).items()}      # "adres|coin" -> {tur, hedef_sz, neden, deneme, ms}
        self.dur_bekliyor: bool = bool(m.get("dur_bekliyor", False))
        self.hl_ofset: float | None = m.get("hl_ofset")          # gerçek kip: HL hesap değeri − yerel özsermaye (ilk okuma); risk temeli = HL değeri − ofset
        self.ledger_son_ms: int | None = m.get("ledger_son_ms")   # gerçek kip: kendi hesabımızın yatırma/çekme kaydında en son işlenen satırın zamanı (ms, UTC)
        self._hl_onceki = self._onceki_oku(m.get("hl_onceki")) if self.kip == "gercek" else None            # K-1 (2. denetim): sıçrama hafızası diskten (yeniden başlatmada son kayıtlı HL − ofset / yerel özsermaye ile kıyas)
        self._hl_sicrama = bool(m.get("hl_sicrama", False)) if self.kip == "gercek" else False
        self._hl_sicrama_ms = int(m.get("hl_sicrama_ms", 0) or 0) if self.kip == "gercek" else 0
        if self._donem_eski is not None:                          # S-3: yeni dönemde ofset ilk HL okumasında yeniden kurulur (kasa artırımı için yapılan yatırma ofsete İKİNCİ kez girmez → kalıcı 200 $ mutabakat farkı yok)
            self.hl_ofset, self.ledger_son_ms = None, None
            self._hl_onceki, self._hl_sicrama = None, False
        if self.kip == "gercek":
            self.risk.bayrak("ofset", False)                      # K-1: diskteki bayrak BAYAT sayılır; açılışta (`ilk_mutabakat`) temizlenip yeniden değerlendirilir
            self.risk.bayrak("kapanis_modu", False)               # D-11: aynı (açılışta `_motor_calistir` yeniden belirler)
            self.risk.bayrak("hl_okunamiyor", False)              # O-1: aynı (HL okuması açılışta zaten yapılmıştır; `ilk_mutabakat` yeniden değerlendirir)
        self.hl_oz: float | None = None
        self.hl_oz_ms: int = 0
        self._hl_son_okuma: tuple | None = None                         # Denetim-8 (D5): (son hl_oku sonucu, okumanın başladığı saat_ms)
        self.son_funding_saat: int | None = m.get("son_funding_saat")
        self._funding_bekleyen: list[tuple[int, int, list]] = []       # F07: oran okunamayan saatlerin pozisyon görüntüleri (saat, kapsanan saat sayısı, [(adres, coin, sz, mark)])
        self.son_funding_ms: int | None = m.get("son_funding_ms")                  # G7 gerçek kip: işlenen en son `userFunding` satırının zamanı (ms, UTC); alan yoksa ilk bakımda "şimdi" (geçmiş okunmaz)
        self.funding_kimlik: list[str] = list(m.get("funding_kimlik") or [])       # G7: son işlenen satırların "time:coin" anahtarları (çift sayım yok)
        self.funding_gercek_usd = float(m.get("funding_gercek_usd", 0.0))          # G7: HL'den işlenen gerçek funding toplamı ($, HL hesabı = kasa ölçeği; + alınan / − ödenen)
        self.ucret_gercek_usd = float(m.get("ucret_gercek_usd", 0.0))              # G7: HL `fee` ile deftere yazılan gerçek ücret toplamı ($)
        self.ucret_bekleyen: list[dict] = [dict(x) for x in (m.get("ucret_bekleyen") or []) if isinstance(x, dict)]     # Denetim-6 (O9): tahmini ücretle deftere yazılmış gerçek dolumlar (cloid, adres, coin, oid, ms, kayit_ms, tahmin); dakikalık bakım kilit dışında gerçek ücretle düzeltir
        self.ucret_tahmin_say = int(m.get("ucret_tahmin_say", 0))                  # G7: gerçek ücret bulunamayıp tahmin (`maliyet_taker`) kullanılan dolum sayısı
        self.kuyruk_gecikme: deque[float] = deque(maxlen=20000)
        self.en_buyuk_emir: dict = {}
        self._son_olay_coin: dict[tuple[str, str], int] = {}
        self._senkron_okuma_ms = 0
        self.tg.offset = max(self.tg.offset, int(m.get("tg_offset", 0)))
        sahip = os.environ.get("HL_HESAP_ADRESI", "").strip()
        if sahip:
            MASKE[:] = [sahip]
            self.tg.maske = [sahip]
        if hasattr(yurutucu, "saat_ms"):
            yurutucu.saat_ms = self.saat_ms
        self._kaynak: dict | None = None            # sunucu kaynak ölçümü (kaynak.olc); dakikada en çok bir yenilenir, motor.json'da "kaynak"
        self._filtre_hata_zaman: dict[str, list[int]] = {}   # sanal filtre hata türü -> son hata zamanları (ms; 1 saatlik pencere, uyarı için)
        self._adim_ardisik: dict[str, int] = {}   # M-2: dakikalık adım adı -> üst üste hata sayısı (başarıda silinir)
        self._lock = threading.RLock()            # olay işleme (tüketici iş parçacığı) ile dakikalık bakım aynı durumu değiştirir: tek seferde biri

    @property
    def post_hizli(self) -> Callable[[dict], Any]:
        return self._post_hizli or self.post

    @post_hizli.setter
    def post_hizli(self, f: Callable[[dict], Any] | None) -> None:
        self._post_hizli = f

    # ------------------------------------------------------------------ kilit (vardiya devri: çift emir yok)
    def kilit_al(self) -> None:
        """`durum/kilit.json`: başka bir vardiya `canli_kilit_dk` içinde nabız attıysa BAŞLAMAZ (çift emir yok). Temiz kapanışta bırakılır; çökme/zaman aşımında nabız eskir ve sonraki vardiya devralır."""
        k = _oku(self.durum_dizin / "kilit.json") or {}
        devral = str(getattr(self, "devral_vardiya", "") or "")
        if devral and str(k.get("vardiya")) == devral and not k.get("birakildi"):
            # İş akışı kilit sahibi koşunun BİTTİĞİNİ doğruladı (gh api completed ya da zincir tetiği + concurrency kuyruğu): ölmüş vardiyanın bırakılmamış kilidi devralınır. YALNIZ bu kimlik; başka sahip → eski kural.
            self.kayit({"olay": "kilit_devralindi", "onceki": devral, "vardiya": self.vardiya_id})
            k = {**k, "birakildi": True}
        if k.get("vardiya") not in (None, self.vardiya_id) and not k.get("birakildi") and self.saat_ms() - int(k.get("nabiz_ms", 0)) < float(self.rules["canli_kilit_dk"]) * DAKIKA:
            mesaj = f"başka vardiya aktif ({k.get('vardiya')}); kilit {self.rules['canli_kilit_dk']} dk içinde nabız attı"
            self.kayit({"olay": "vardiya_baslamadi", "neden": mesaj, "vardiya": self.vardiya_id})
            self.tg.gonder(tg.alarm("ALARM: tur başlayamadı", f"Vardiya {self.vardiya_id} BAŞLAMADI: {mesaj}\nSistem şu an işlem kopyalamıyor."))
            raise KipHatasi(mesaj)
        nabiz = int(k.get("nabiz_ms", 0))
        if k and nabiz and (self.saat_ms() - nabiz) > float(self.rules["canli_bosluk_dk"]) * DAKIKA and k.get("vardiya") != self.vardiya_id:
            bosluk = (self.saat_ms() - nabiz) / DAKIKA
            self.kayit({"olay": "vardiya_boslugu", "dk": round(bosluk, 1), "onceki": k.get("vardiya")})
            self.tg.gonder(tg.alarm("ALARM: kesinti oldu", f"Turlar arasında vardiya boşluğu {bosluk:.0f} dk oldu (önceki vardiya {k.get('vardiya')}).\nKaçan işlemler geriye dönük tamamlanıyor."))
        self.kilit_yaz(False)

    def kilit_yaz(self, birakildi: bool) -> None:
        _yaz(self.durum_dizin / "kilit.json", {"vardiya": self.vardiya_id, "nabiz_ms": self.saat_ms(), "birakildi": birakildi})

    # ------------------------------------------------------------------ kalıcılık
    def durum_yaz(self) -> None:
        d = self.durum_dizin
        if not getattr(self, "_kilit_birakildi", False):
            self.kilit_yaz(False)
        self._hesap_yaz()
        _yaz(d / "saha.json", self.saha.to_json())
        _yaz(d / "risk.json", self.risk.to_json())
        if self.kip == "gercek":
            _yaz(d / "borsa_stop.json", self.borsa_stop.to_json())
        if self._aralik_mi("kaynak", int(self.saat_ms()), 60):
            try:
                self._kaynak = {**kaynak.olc(d), "olc_ms": int(self.saat_ms())}
            except Exception:                                          # noqa: BLE001  ölçüm hiçbir zaman durum yazımını bozmaz
                self._kaynak = None
        _yaz(d / "motor.json", self._motor_json())
        if self.donem_seri:
            _yaz(d / "donem_seri.json", self.donem_seri)
        self.niyet.sikistir(int(self.rules["canli_islenen_sakla"]))
        try:                                                           # paylaşım verisi (salt okur, bilgi amaçlı): hata dakika döngüsüne ve durum yazımına ASLA yansımaz
            _yaz(d / "paylasim" / "kadro_yon_v1.json", self.kadro_yon_ozet(self.saat_ms()))
        except Exception as hata:                                      # noqa: BLE001
            self.kayit({"olay": "kadro_yon_yazim_hata", "tur": type(hata).__name__})
        gunluk_ozet.yaz_gerekirse(self)                                # ortak günlük özet (paylasim/gunluk_ozet_v1.json; saatlik + günlük rapor anı; hata yutulur)

    def kadro_yon_ozet(self, simdi: int) -> dict:
        """Kopya kadrosunun (YALNIZ saha üyeleri) coin bazında toplu pozisyon yönü; başka projelerin okuması için (`durum/paylasim/kadro_yon_v1.json`, veri dalında `durum/paylasim/`).
        Şema `ct.kadro_yon.v1` (docs/PAYLASIM_KADRO_YON.md). Alanlar:
        sema, uretildi_utc (ISO8601 Z), kadro_surumu (kadro.json `radar_surum`; yoksa null), kadro_kosu_utc (kadro.json `kosu_ms` ISO Z; yoksa null),
        saha_trader_sayisi (int, inen hariç), kip ("sanal"/"gercek"),
        coinler: [{coin, long_trader, short_trader, net_yon ("long"/"short"/"notr": trader sayısı çoğunluğu, eşitse nominal işareti, o da 0 ise notr),
        nominal_long_usd, nominal_short_usd, net_nominal_usd (trader pozisyon büyüklüğü × mark, $; mark yoksa null), veri_yasi_sn (trader pozisyon okumalarının en eskisi, sn; bilinmiyorsa null)}] — |net_nominal_usd| azalan (null sonda),
        notlar. Trader adresi, bizim bakiye/özsermaye/kasa, emir bilgisi İÇERMEZ. Trader pozisyonlarının toplamıdır; bizim pozisyonumuz değildir; yatırım tavsiyesi değildir."""
        uyeler = set(self.saha.uyeler)
        coinler: dict[str, dict] = {}
        for adres in uyeler:
            for coin, sz in (self.poz_tr.get(adres) or {}).items():
                if not sz:
                    continue
                c = coinler.setdefault(coin, {"lt": 0, "st": 0, "nl": 0.0, "ns": 0.0, "ms": []})
                mark = self.marks.get(coin)
                if sz > 0:
                    c["lt"] += 1
                else:
                    c["st"] += 1
                if mark:
                    c["nl" if sz > 0 else "ns"] += abs(sz) * mark
                ms = self._poz_tr_ms.get((adres, coin)) or self._poz_tr_senk_ms.get(adres)
                if ms:
                    c["ms"].append(int(ms))
        satirlar = []
        for coin, c in coinler.items():
            net = round(c["nl"] - c["ns"], 2) if self.marks.get(coin) else None
            if c["lt"] != c["st"]:
                yon = "long" if c["lt"] > c["st"] else "short"
            else:
                yon = "long" if (net or 0) > 0 else "short" if (net or 0) < 0 else "notr"
            satirlar.append({"coin": coin, "long_trader": c["lt"], "short_trader": c["st"], "net_yon": yon,
                             "nominal_long_usd": round(c["nl"], 2) if self.marks.get(coin) else None,
                             "nominal_short_usd": round(c["ns"], 2) if self.marks.get(coin) else None,
                             "net_nominal_usd": net,
                             "veri_yasi_sn": round(max(0, simdi - min(c["ms"])) / 1000, 1) if c["ms"] else None})
        satirlar.sort(key=lambda r: (r["net_nominal_usd"] is None, -abs(r["net_nominal_usd"] or 0), r["coin"]))
        kd = self._son_kadro or {}
        kosu = kd.get("kosu_ms")
        return {"sema": "ct.kadro_yon.v1", "uretildi_utc": _iso_z(simdi),
                "kadro_surumu": str(kd["radar_surum"]) if kd.get("radar_surum") is not None else None,
                "kadro_kosu_utc": _iso_z(int(kosu)) if kosu else None,
                "saha_trader_sayisi": len(uyeler), "kip": self.kip, "coinler": satirlar,
                "notlar": "Trader pozisyonlarının toplamı (kopya kadrosu). Bizim hesabımızın pozisyonu DEĞİL. Yatırım tavsiyesi değil."}

    def _motor_json(self) -> dict:
        return {"islenen": self.islenen, "poz_tr": self.poz_tr, "poz_tr_ms": {f"{a}|{c}": ms for (a, c), ms in self._poz_tr_ms.items()}, "poz_tr_senk_ms": self._poz_tr_senk_ms, "hesap_tr": self.hesap_tr, "kaldirac_tr": self.kaldirac_tr, "golge_acik": self._golge_acik, "son_olay_ms": self.son_olay_ms,
                "ozet_gunu": self._ozet_gunu, "ozet_oz": self._ozet_oz, "ozet_emir": self._ozet_emir, "hafta_gunu": self._hafta_gunu, "hafta_taban": self._hafta_taban, "kip": self.kip, "kasa_usd": self.kasa, "kasa_ayar_usd": self.kasa_ayar, "vardiya": self.vardiya_id, "yazildi_ms": self.saat_ms(),
                "kapanis_kuyrugu": self.kapanis_kuyrugu, "dur_bekliyor": self.dur_bekliyor, "hl_ofset": self.hl_ofset, "ledger_son_ms": self.ledger_son_ms, "hl_onceki": list(self._hl_onceki) if self._hl_onceki else None, "hl_sicrama": self._hl_sicrama, "hl_sicrama_ms": self._hl_sicrama_ms, "son_funding_saat": self.son_funding_saat, "tg_offset": self.tg.kalici_offset,
                "son_funding_ms": self.son_funding_ms, "funding_kimlik": self.funding_kimlik[-500:], "funding_gercek_usd": self.funding_gercek_usd, "ucret_gercek_usd": self.ucret_gercek_usd, "ucret_tahmin_say": self.ucret_tahmin_say,
                "ucret_bekleyen": self.ucret_bekleyen[-500:], "btc_donem": self.btc_donem, "mutabakat_tutan": self.mutabakat_tutan, "yetim_ilk": self.yetim_ilk, "sahipsiz_ilk": self.sahipsiz_ilk,
                "rejim_anlik": self.rejim_anlik, "rejim_4h_son": self.rejim_4h_son, "haber_anlik": self.haber_anlik, "son_atla": self.son_atla,
                "karsi_olgu": self.karsi_olgu, "karsi_olgu_gun": self.karsi_olgu_gun, "kopya_drift": self.kopya_drift, "kopya_drift_tg_ms": self.kopya_drift_tg_ms, "kaynak": self._kaynak}

    def _hesap_yaz(self) -> None:
        """hesap.json atomik yazılır; gerçek kipte önce son sağlam sürüm `hesap.json.bak` (Denetim-2)."""
        yol = self.durum_dizin / "hesap.json"
        if self.kip == "gercek":
            _yedekle(yol)
        _yaz(yol, self.hesap.to_json())

    def _dolum_yaz(self) -> None:
        """Her emir sonucundan SONRA (t4b #3): `motor.json` önce, `hesap.json` (son uygulanan niyet işaretçisiyle) SON; ikisi de atomik. Aralarında çökme olursa açılışta işaretçiden sonraki sonuçlu niyetler oynatılır."""
        _yaz(self.durum_dizin / "motor.json", self._motor_json())
        self._hesap_yaz()

    @property
    def islenen(self) -> list[str]:
        """İşlenen kimlikler (ekleme sırası; adres başına en çok `canli_islenen_adres_sakla`)."""
        return list(self._islenen)

    def _islenen_ekle(self, kimlik: str) -> None:
        """G-14: kimlik `{adres}:{tid}` → adres kovası; kova sınırı aşılırsa YALNIZ o adresin en eskisi düşer (34 adres ortak 5000'i paylaşmaz)."""
        if kimlik in self._islenen:
            return
        self._islenen[kimlik] = None
        kova = self._islenen_adres.setdefault(kimlik.rsplit(":", 1)[0], deque())
        kova.append(kimlik)
        while len(kova) > int(self.rules.get("canli_islenen_adres_sakla", 2000)):
            self._islenen.pop(kova.popleft(), None)

    def _gorulduysa_isaretle(self, kimlik: str) -> bool:
        """Dolum kimliği daha önce işlendiyse True (çift emir yok: yeniden başlatmada da). Kimliksiz olay tekilleştirilemez (False)."""
        if not kimlik:
            return False
        if kimlik in self._islenen:
            return True
        self._islenen_ekle(kimlik)
        return False

    # ------------------------------------------------------------------ yardımcılar
    def mark(self, coin: str, yedek: float | None = None) -> float | None:
        return self.marks.get(coin) or yedek

    def ucret_oku(self, simdi: int) -> list | None:
        """Denetim-6 (O9; ağ, KİLİT DIŞI): tahmini ücretle yazılmış dolumlar varsa tek `userFillsByTime` okuması (en eski bekleyenden 5 sn öncesinden). Okunamazsa None (bekleyenler kalır, sonraki dakika)."""
        bekleyen = list(self.ucret_bekleyen)
        adres = os.environ.get("HL_HESAP_ADRESI", "").strip()
        if self.kip != "gercek" or not bekleyen or not adres:
            return None
        try:
            r = self.post({"type": "userFillsByTime", "user": adres, "startTime": max(0, min(int(b.get("ms") or 0) for b in bekleyen) - 5000)})
        except Exception as hata:                          # noqa: BLE001
            self.kayit({"olay": "ucret_okuma_hata", "tur": type(hata).__name__})
            return None
        return r if isinstance(r, list) else None

    def ucret_uygula(self, satirlar: list | None, simdi: int) -> None:
        """Denetim-6 (O9; kilit altında, ağ yok): bekleyen tahmini ücretleri HL `fee` ile düzeltir. Düzeltme `hesap.ucret_duzelt` ile özdeşliği korur (özsermaye −Δ); `motor.json` (bekleyen listesi) ÖNCE,
        `hesap.json` SONRA yazılır (çökmede çift düzeltme yok, en kötü ihtimal tahmin kalır). 30 dk içinde eşleşmeyen kayıt düşer (tahmin kalır; `ucret_tahmin_say` o dolumu saymaya devam eder)."""
        if not self.ucret_bekleyen:
            return
        kalan: list[dict] = []
        duzeltilen = 0
        for b in self.ucret_bekleyen:
            gercek = ucret_eslestir(satirlar, b["coin"], b.get("oid"), b.get("cloid")) if satirlar is not None else None
            if gercek is None:
                if simdi - int(b.get("kayit_ms", simdi)) < 1_800_000:
                    kalan.append(b)
                else:
                    self.kayit({"olay": "ucret_duzeltme_vazgec", "cloid": b.get("cloid"), "coin": b.get("coin")})
                continue
            delta = gercek - float(b.get("tahmin", 0.0))
            self.hesap.ucret_duzelt(b["adres"], delta)
            self.ucret_gercek_usd += gercek
            self.ucret_tahmin_say = max(0, self.ucret_tahmin_say - 1)
            duzeltilen += 1
            self.kayit({"olay": "ucret_duzeltildi", "cloid": b.get("cloid"), "adres": b["adres"], "coin": b["coin"], "tahmin": b.get("tahmin"), "gercek": gercek, "fark": delta})
        self.ucret_bekleyen = kalan
        if duzeltilen:
            self._dolum_yaz()

    def mark_taze_mi(self, coin: str, simdi: int) -> bool:
        """Denetim-6 (O5): coinin mark'ı `canli_mark_stale_sn`den eski değil mi (hiç yoksa taze değil). Gerçek kipte açılış/artırma ve mutabakat kullanır (kapanış serbest)."""
        yas = simdi - self.mark_ms.get(coin, -10**15)
        return yas <= float(self.rules["canli_mark_stale_sn"]) * 1000

    def trader_hesap_usd(self, adres: str, simdi_ms: int, zorla: bool = False, taze_sart: bool = False) -> float | None:
        """Trader hesap değeri (oran paydası, K‑35): tüm perp dex `accountValue` toplamı + spot USDC (`hesap_degeri_oku`). Önbellekteki değer kullanılır (yenileme `dakika()` içinde kilit dışında,
        `canli_hesap_okuma_sn`); önbellek yoksa ya da `zorla` ise burada okunur. Okunamazsa önceki değer; hiç yoksa None (açılış atlanır).
        F10 (denetim 10.11): `taze_sart` (açılış/artırma) iken önbellek `canli_hesap_azami_yas_sn`'den eskiyse burada yeniden okunur; okunamazsa None (bayat paydayla büyük emir açılmaz)."""
        c = self.hesap_tr.get(adres)
        bayat = bool(c) and simdi_ms - int(c.get("ms") or 0) > float(self.rules.get("canli_hesap_azami_yas_sn", 1800)) * 1000
        if c and not zorla and not (taze_sart and bayat):
            return float(c["deger"])
        try:
            deger = hesap_degeri_oku(self.post_hizli, adres, self._dexler())
            self.hesap_tr[adres] = {"deger": deger, "ms": simdi_ms}
            return deger
        except Exception as hata:                          # noqa: BLE001
            self.kayit({"olay": "hesap_okuma_hata", "adres": adres, "tur": type(hata).__name__, "bayat": bayat})
            if taze_sart and bayat:
                return None
            return float(c["deger"]) if c else None

    def hesap_oku(self) -> dict[str, float]:
        """Saha + inen adreslerin hesap değerleri (REST; kilitsiz). Okunamayan adres atlanır (önceki önbellek kalır)."""
        sonuc: dict[str, float] = {}
        for adres in [*self.saha.uyeler, *self.saha.inen]:
            try:
                sonuc[adres] = hesap_degeri_oku(self.post, adres, self._dexler())
            except Exception as hata:                      # noqa: BLE001
                self.kayit({"olay": "hesap_okuma_hata", "adres": adres, "tur": type(hata).__name__})
        return sonuc

    def hesap_uygula(self, degerler: dict[str, float], simdi: int) -> None:
        for adres, d in degerler.items():
            self.hesap_tr[adres] = {"deger": d, "ms": simdi}

    GOLGE_KURALLAR = (("A_hesap_5k", "golge_hesap_alt_usd"), ("B_kaldirac_5x", "golge_kaldirac_uyari"), ("B_kaldirac_20x", "golge_kaldirac_cikar"))

    def golge_kural_adimi(self, simdi: int) -> None:
        """Gölge kurallar (Fable; K-73: sanalda `sanal_golge_kurallar_etkin` ile açılış kararını etkiler (`_sanal_acilis_filtresi`), gerçek kipte yalnız kayıt): her dakika saha + inen traderlar için anlık kaldıraç ve hesap değeri `kaldirac_tr`ye yazılır (pano gösterir);
        A: hesap < `golge_hesap_alt_usd`; B1: kaldıraç > `golge_kaldirac_uyari`; B2: kaldıraç > `golge_kaldirac_cikar`. `golge_kural` olayı yalnız kural başladığında/bittiğinde (durum değişimi) yazılır.
        Veri bilinmiyorsa (hesap/pozisyon/mark yok) o kuralın durumu değişmez."""
        adresler = [*self.saha.uyeler, *self.saha.inen]
        for adres in list(self._golge_acik):
            if adres not in adresler:
                del self._golge_acik[adres]
        for adres in adresler:
            c = self.hesap_tr.get(adres)
            hesap = float(c["deger"]) if c and c.get("deger") is not None else None
            kald = anlik_kaldirac_hesapla(self.poz_tr.get(adres), self.marks, hesap)
            self.kaldirac_tr[adres] = {"anlik_kaldirac": kald, "hesap_usd": hesap, "ms": simdi}
            acik = self._golge_acik.get(adres, [])
            yeni = list(acik)
            for kural, anahtar in self.GOLGE_KURALLAR:
                esik = self.rules.get(anahtar)
                deger = hesap if kural == "A_hesap_5k" else kald
                if esik is None or deger is None:
                    continue
                dogru = deger < float(esik) if kural == "A_hesap_5k" else deger > float(esik)
                if dogru and kural not in yeni:
                    yeni.append(kural)
                    durum = "basladi"
                elif not dogru and kural in yeni:
                    yeni.remove(kural)
                    durum = "bitti"
                else:
                    continue
                self.kayit({"olay": "golge_kural", "kural": kural, "adres": adres, "hesap_usd": hesap, "anlik_kaldirac": kald, "esik": float(esik), "durum": durum})
            if yeni:
                self._golge_acik[adres] = yeni
            else:
                self._golge_acik.pop(adres, None)
        for adres in [a for a in self.kaldirac_tr if a not in adresler]:
            del self.kaldirac_tr[adres]

    def rejim_adimi(self, simdi: int) -> None:
        """ML rejim etiketi (kayıt; sanalda K-73 `sanal_rejim_filtre` açılış filtresi için okunur): `rejim_okuma_dk` dakikada bir okunur; adres boşsa hiç ağ çağrısı yok.
        4h rejimi değiştiğinde coin başına `rejim_degisti` olayı (son kaydedilenle karşılaştırılır). Okuma hatası/bayat veri → önbellek boş (etiket None)."""
        url = str(self.rules.get("rejim_kaynak_url") or "").strip()
        if not url or not self._aralik_mi("rejim", simdi, float(self.rules.get("rejim_okuma_dk", 30)) * 60):
            return
        self.rejim_anlik = rejim.oku_tam(url, simdi_ms=simdi)
        for coin, z in (self.rejim_anlik.get("rejimler") or {}).items():
            r4 = z.get("4h")
            if r4 is None or self.rejim_4h_son.get(coin) == r4:
                continue
            self.kayit({"olay": "rejim_degisti", "coin": coin, "onceki": self.rejim_4h_son.get(coin), "yeni": r4, "1d": z.get("1d")})
            self.rejim_4h_son[coin] = r4

    def haber_adimi(self, simdi: int) -> None:
        """Haber/duygu etiketi (kayıt; sanalda `_sanal_acilis_filtresi` haber/duygu ile açılışı atlatır, gerçek kipte yalnız kayıt): `haber_okuma_dk` dakikada bir; sınıf değişince `duygu_degisti`. Mantık haber.py'de."""
        if not self.rules.get("haber_aktif") or not self._aralik_mi("haber", simdi, float(self.rules.get("haber_okuma_dk", 60)) * 60):
            return
        self.haber_anlik, olaylar = haber.guncelle(self.rules, self.haber_anlik, simdi)
        for o in olaylar:
            self.kayit(o)

    def trader_pozlari_oku(self, adres: str, dexler: list[str] | None = None) -> bool:
        try:
            okuma_ms = self.saat_ms()
            self.poz_tr[adres] = clearinghouse_pozisyonlari(self.post_hizli, adres, dexler if dexler is not None else self._dexler())
            self._poz_tr_senk_isaretle(adres, okuma_ms)
            return True
        except Exception as hata:                          # noqa: BLE001
            self.kayit({"olay": "poz_okuma_hata", "adres": adres, "tur": type(hata).__name__})
            return False

    def trader_son_islem_oku(self, adres: str, simdi_ms: int) -> None:
        """B15 (RADAR §5 "72 sa yeni işlem yok"): sayaç trader'ın SON dolumundan başlar, giriş anından değil. Girişte son `canli_islem_yok_saat` saatin dolumları REST'le okunur
        (`userFillsByTime`): en yeni dolumun `time`'ı (ms, UTC) saha kaydına yazılır; pencerede dolum yoksa son dolum ≤ pencere başı → pencere başı yazılır (ilk günlük
        kontrolde düşer). Okuma hatası → yazılmaz (bilinmiyor: sayaç giriş anından; `son_islem_okuma_hata` kaydı)."""
        if adres not in self.saha.uyeler:
            return
        bas = int(simdi_ms - float(self.rules["canli_islem_yok_saat"]) * 3_600_000)
        try:
            satirlar = self.post_hizli({"type": "userFillsByTime", "user": adres, "startTime": bas}) or []
            zamanlar = [int(r["time"]) for r in satirlar if isinstance(r, dict) and r.get("time") is not None]
        except Exception as hata:                          # noqa: BLE001
            self.kayit({"olay": "son_islem_okuma_hata", "adres": adres, "tur": type(hata).__name__})
            return
        self.saha.islem_gordu(adres, max(zamanlar) if zamanlar else bas)

    def _dexler(self) -> list[str]:
        """HIP-3 perp dex adları. Başarılı okuma süreç boyunca önbellekte; HATA önbelleğe ALINMAZ (G-6): istisna yükselir, bir sonraki çağrı yeniden okur.
        Çağıranlar hatayı yakalar (hesap değeri bilinmiyor → açılış `trader_hesap_yok`; pozisyon okunamadı) — eksik dex listesiyle kısmi toplam/pozisyon ASLA üretilmez."""
        if getattr(self, "_dex_adlari", None) is None:
            self._dex_adlari = perp_dex_names(self.post_hizli({"type": "perpDexs"}))
        return self._dex_adlari

    def _dexler_guvenli(self) -> list[str]:
        """Yalnız dinleyici kurulumu için (arka plan okuması; kısmi liste yalnız HIP-3 aboneliğini eksik bırakır): hata → [] (önbelleğe alınmaz)."""
        try:
            return self._dexler()
        except Exception as hata:                          # noqa: BLE001
            self.kayit({"olay": "perp_dex_okuma_hata", "tur": type(hata).__name__})
            return []

    # ------------------------------------------------------------------ olay işleme (çekirdek)
    def olay_isle(self, o: Olay, canli: bool = True) -> list[Sonuc]:
        with self._lock:
            return self._olay_isle(o, canli)

    def kapanis_mi(self, o: Olay) -> bool:
        """Kuyruk önceliği için: dolum trader pozisyonunu azaltıyor / kapatıyor / ters çeviriyor mu (kapat/azalt önce işlenir)."""
        once = o.bas_poz if o.bas_poz is not None else self.poz_tr.get(o.adres, {}).get(o.coin, 0.0)
        sonra = once + (o.sz if o.yon == "B" else -o.sz) if o.sz is not None else once
        return once * sonra < 0 or abs(sonra) < abs(once) - EPS

    def _poz_tr_esik(self, adres: str, coin: str, canli: bool) -> int:
        """G-14: bundan ESKİ dolum poz_tr'yi değiştirmez (ms, UTC). Her olay için: bu coinde son uygulanan dolumun zamanı. Canlı OLMAYAN olay (snapshot / abonelik öncesi) için ayrıca
        adresin son REST pozisyon okumasının anı: okumadan önceki dolum REST değerinde zaten var (snapshot'taki eski dolum yeniden uygulanıp poz_tr'yi ezmesin)."""
        ms = self._poz_tr_ms.get((adres, coin), 0)
        return ms if canli else max(ms, self._poz_tr_senk_ms.get(adres, 0))

    def _poz_tr_senk_isaretle(self, adres: str, okuma_ms: int) -> None:
        """REST okuması poz_tr[adres]'i yazdı: canlı olmayan olay eşiği = okuma anı (kalıcı, `motor.json` `poz_tr_senk_ms`)."""
        self._poz_tr_senk_ms[adres] = max(self._poz_tr_senk_ms.get(adres, 0), okuma_ms)

    def _poz_tr_guncelle(self, o: Olay, canli: bool) -> tuple[float, float, bool]:
        """G-14: dolum eşikten (`_poz_tr_esik`) eskiyse poz_tr'ye DOKUNMAZ (REST okuması/sonraki dolum onu zaten içeriyor); karar için (önce, sonra) türetilir:
        `bas_poz` varsa (userFills/REST `startPosition`) ondan, yoksa mevcut poz_tr'den geriye. Döner (önce, sonra, uygulandı_mı)."""
        if o.zaman_ms < self._poz_tr_esik(o.adres, o.coin, canli):
            d = o.sz if o.yon == "B" else -o.sz
            if o.bas_poz is not None:
                return o.bas_poz, o.bas_poz + d, False
            simdi_poz = self.poz_tr.get(o.adres, {}).get(o.coin, 0.0)
            return simdi_poz - d, simdi_poz, False
        once, sonra = self._poz_tr_isle(o)
        return once, sonra, True

    def _poz_tr_isle(self, o: Olay) -> tuple[float, float]:
        """Trader pozisyon tablosunu (`poz_tr`) dolumla günceller; döner (önce, sonra) işaretli coin miktarı."""
        once = o.bas_poz if o.bas_poz is not None else self.poz_tr.get(o.adres, {}).get(o.coin, 0.0)
        sonra = once + (o.sz if o.yon == "B" else -o.sz)
        self.poz_tr.setdefault(o.adres, {})[o.coin] = 0.0 if abs(sonra) < 1e-9 else sonra
        if abs(sonra) < 1e-9:
            self.poz_tr[o.adres].pop(o.coin, None)
        self._poz_tr_ms[(o.adres, o.coin)] = max(self._poz_tr_ms.get((o.adres, o.coin), 0), o.zaman_ms)
        return once, sonra

    def dusen_isle(self, o: Olay) -> None:
        """Kuyruk taşınca düşen olay (t4b #6): emir üretilmez ama trader pozisyon tablosu güncellenir (600 sn senkronu beklenmez). Daha yeni bir dolum zaten işlendiyse atlanır."""
        with self._lock:
            if not o.adres or not o.coin or o.sz is None or o.px is None or o.yon not in ("B", "A"):
                return
            if o.zaman_ms < self._poz_tr_esik(o.adres, o.coin, True):
                return
            if o.kimlik in self._snap or self._gorulduysa_isaretle(o.kimlik):        # aynı ms'deki FARKLI dolum uygulanır; aynı kimlik (işlenmiş / snapshot'ta uygulanmış / düşmüş) ikinci kez sayılmaz
                return
            self._poz_tr_isle(o)
            self.kayit({"olay": "dusen_olay_poz_tr", "adres": o.adres, "coin": o.coin, "yon": o.yon, "sz": o.sz})

    def _olay_isle(self, o: Olay, canli: bool = True) -> list[Sonuc]:
        """Tekilleştirilmiş trader dolumu → emir(ler). `canli=False` (snapshot / abonelik öncesi): yalnız trader pozisyon izleyicisi güncellenir. SENKRON (ağ I/O içerir); motor tek tüketiciyle sırayla çağırır.
        Yaş kuralı (K‑37 §5): AÇILIŞ/artırma olay yaşı (trader dolumu → işleme anı, kuyruk beklemesi dahil) > `canli_olay_stale_sn` ise emir YOK (`gec_acilis`); yakalama trader'ın sonraki dolumunda K‑36
        hedef tabanlı artırmayla kendiliğinden olur. KAPANIŞ/azaltma yaşa bakmaz (pozisyon açıkta kalmasın); 60 dk penceresinden eski kapanışlar senkronda trader pozisyonu 0 görülünce kapatılır."""
        adres = o.adres
        sonuclar: list[Sonuc] = []
        if not adres or not o.coin or o.sz is None or o.px is None or o.yon not in ("B", "A"):
            return sonuclar
        if o.kimlik and o.kimlik in self._islenen:
            return sonuclar
        onceki = self._snap.get(o.kimlik) if o.kimlik else None
        if not canli and onceki is not None:                       # aynı dolum ikinci kanaldan / ikinci snapshot'tan: bir kez
            return sonuclar
        simdi = self.saat_ms()
        if onceki is not None:                                     # G-17b: snapshot'ta poz_tr'ye zaten işlendi (ya da eşikten eski bulundu); canlı/dolgu kopyası emri o değerlerle üretir
            (once, sonra), uygulandi = onceki, False
            del self._snap[o.kimlik]
        else:
            once, sonra, uygulandi = self._poz_tr_guncelle(o, canli)     # G-14: eşikten eski dolum poz_tr'yi DEĞİŞTİRMEZ
        if canli:
            self._gorulduysa_isaretle(o.kimlik)
        elif o.kimlik:                                             # snapshot kimliği `islenen`e girmez (sonra dolgu ile emir üretebilsin); sınırlı bellek
            self._snap[o.kimlik] = (once, sonra)
            if len(self._snap) > SNAP_SAKLA:
                del self._snap[next(iter(self._snap))]
        if uygulandi:
            self._son_olay_coin[(adres, o.coin)] = simdi
        self.son_olay_ms = max(self.son_olay_ms, o.zaman_ms)
        if adres in self.saha.uyeler:
            self.saha.islem_gordu(adres, o.zaman_ms)
        if not canli or (adres not in self.saha.uyeler and adres not in self.saha.inen):
            return sonuclar
        gec = o.kaynak in ("dolgu", "rest") or simdi - o.zaman_ms > float(self.rules["canli_olay_stale_sn"]) * 1000
        if gec:
            self.sayac["gec_goruldu"] += 1
        biz_sz = self.hesap.sz(adres, o.coin)
        for eylem in eylem_belirle(once, sonra, biz_sz):
            s = self._emir_isle(o, adres, eylem, once, sonra, biz_sz, simdi, gec)
            sonuclar.append(s)
            biz_sz = self.hesap.sz(adres, o.coin)
            once = 0.0 if eylem == "kapat" and once * sonra < 0 else once          # ters dönüşte açılış parçası sıfırdan
            if eylem == "kapat" and abs(biz_sz) > EPS and biz_sz * sonra < 0:      # G-3: ters pozisyon kapanmadı (kuyrukta) → ters yönde açılış YOK (net küçülme / ters emir olmasın)
                break
        return sonuclar

    def _hip3_acik(self) -> bool:
        """HIP-3 (`dex:COIN`) açılışı kopyalanır mı: sanalda `sanal_hip3_kopya` (kullanıcı kararı 19.11 gece: sanalda her özellik açık), gerçekte HER ZAMAN `canli_hip3_kopya` (varsayılan false)."""
        if self.kip == "sanal":
            return bool(self.rules.get("sanal_hip3_kopya", False))
        return bool(self.rules.get("canli_hip3_kopya", False))

    def _sanal_acilis_filtresi(self, adres: str, coin: str, yon_long: bool, simdi: int) -> tuple[str | None, float]:
        """K-73 (kullanıcı kararı 19.11 gece): YALNIZ sanal kip, YALNIZ açılış/artırma. Döner (atlama nedeni | None, slot çarpanı). Kapanış/azaltma için ÇAĞRILMAZ; gerçek kipte (neden None, 1.0).
        Bayraklar `kurallar.yaml`: sanal_rejim_filtre, sanal_haber_filtre (+ sanal_haber_min_baslik), sanal_duygu_filtre (+ duygu_ust/duygu_alt), sanal_golge_kurallar_etkin. Bilinmeyen veri (etiket/haber/hesap yok) = atlama yok."""
        if self.kip != "sanal":
            return None, 1.0
        r = self.rules
        try:
            if r.get("sanal_rejim_filtre", False):
                z = rejim.coin_rejimi(self.rejim_anlik, coin, simdi) or {}
                ters = "trend_down" if yon_long else "trend_up"
                if z.get("1d") == ters and z.get("4h") == ters:
                    return "rejim_ters", 1.0
            if r.get("sanal_haber_filtre", False):
                h = (haber.emir_alanlari(self.haber_anlik, coin, simdi).get("haber") or {}).get(coin) or {}
                if h.get("ton") == ("negatif" if yon_long else "pozitif") and int(h.get("adet_24s") or 0) >= int(r.get("sanal_haber_min_baslik", 2)):
                    return "haber_ters", 1.0
            if r.get("sanal_duygu_filtre", False):
                d = haber.duygu_ozet(self.haber_anlik, simdi)                      # yok/bayat = None = atlama yok
                if d is not None:
                    v = float(d["deger"])
                    if (yon_long and v >= float(r.get("duygu_ust", 75))) or (not yon_long and v <= float(r.get("duygu_alt", 25))):
                        return "duygu_ters", 1.0
            if r.get("sanal_golge_kurallar_etkin", False):
                acik = self._golge_acik.get(adres, [])
                if "A_hesap_5k" in acik:
                    return "hesap_kucuk", 1.0
                if "B_kaldirac_20x" in acik:
                    return "kaldirac_cok_yuksek", 1.0
                if "B_kaldirac_5x" in acik:
                    return None, 0.5
        except Exception as hata:                      # noqa: BLE001
            self.kayit({"olay": "sanal_filtre_hata", "tur": type(hata).__name__, "mesaj": str(hata)[:160]})          # filtre hatası açılışı engellemez; tekrarlarsa Telegram uyarısı
            self._filtre_hata_uyar(type(hata).__name__, simdi)
        return None, 1.0

    def _filtre_hata_uyar(self, tur: str, simdi: int) -> None:
        """Aynı filtre hatası 1 saatte >= 3 kez olursa Telegram ⚠️ uyarısı (aynı uyarı en çok 6 saatte bir). Hata açılışı engellemez."""
        z = [t for t in self._filtre_hata_zaman.get(tur, []) if simdi - t < 3_600_000] + [simdi]
        self._filtre_hata_zaman[tur] = z
        if len(z) >= 3 and self._aralik_mi("filtre_hata_uyari:" + tur, simdi, 6 * 3600):
            self.tg.gonder(tg.msg_filtre_hata(len(z)), "WARN", "sanal_filtre_hata:" + tur)

    def _emir_isle(self, o: Olay, adres: str, eylem: str, once: float, sonra: float, biz_sz: float, simdi: int, gec: bool, telafi: dict | None = None) -> Sonuc:
        acilis = eylem in ("ac", "artir")
        if acilis and simdi - o.zaman_ms > float(self.rules["canli_olay_stale_sn"]) * 1000:
            self.sayac["gec_acilis"] += 1
            return self._atla(o, adres, eylem, "atlandi", "gec_acilis")
        if acilis and (ders_engel := self.ogrenme.acilis_engeli(adres)):      # ortak öğrenme: dersle emekli trader'ın YENİ açılışı yok (kapanış/azaltma serbest)
            return self._atla(o, adres, eylem, "engel", ders_engel)
        if acilis:                                                  # K‑42: spot (`@N`, `A/B`) ve HIP‑3 (`dex:COIN`) açılışı/artırması kopyalanmaz; kapanış/azaltma ASLA engellenmez
            sinif = coin_sinifi(o.coin)
            if sinif == "spot":
                self.atlanan_trader["spot_atlandi"][adres] = self.atlanan_trader["spot_atlandi"].get(adres, 0) + 1
                return self._atla(o, adres, eylem, "atlandi", "spot_atlandi")
            if sinif == "hip3" and not self._hip3_acik():
                self.atlanan_trader["hip3_atlandi"][adres] = self.atlanan_trader["hip3_atlandi"].get(adres, 0) + 1
                return self._atla(o, adres, eylem, "atlandi", "hip3_atlandi")
            if self.kip == "gercek" and not self.mark_taze_mi(o.coin, simdi):          # Denetim-6 (O5): gerçek kipte bayat mark'la AÇILIŞ/artırma yok (kapanış serbest)
                return self._atla(o, adres, eylem, "engel", "mark_eski")
            kn = self.kaldirac_yetersiz(o.coin)                     # Denetim-4a: gerçek kipte HL azami kaldıracı < `canli_min_azami_kaldirac` → açılış/artırma yok (kapanış serbest)
            if kn:
                return self._atla(o, adres, eylem, "atlandi", kn)
        inen = adres in self.saha.inen and adres not in self.saha.uyeler
        if acilis and inen:
            return self._atla(o, adres, eylem, "engel", "inen_trader")
        if acilis:
            self._inen_ters_kapat(adres, o.coin, "B" if sonra > 0 else "A", simdi)
        if acilis and self.hesap.ters_yonlu_var(adres, o.coin, "B" if sonra > 0 else "A", self.marks, float(self.rules["canli_kapanis_toz_usd"])):          # K‑41: başka trader'dan ters yönlü kopya pozisyonu var → net küçülmesin, açılış yok
            return self._atla(o, adres, eylem, "atlandi", "ters_netlesme")
        golge_carpan = None
        if acilis and self.kip == "sanal":                          # K-73: sanalda rejim/haber/duygu/gölge kurallar işlem etkiler (yalnız SKIP/KÜÇÜLT; kapanış/azaltma hiç girmez)
            f_neden, golge_carpan = self._sanal_acilis_filtresi(adres, o.coin, sonra > 0, simdi)
            if f_neden:
                return self._atla(o, adres, eylem, "atlandi", f_neden)
        yeni_coin = eylem == "ac" and abs(biz_sz) < EPS            # bizim için taze pozisyon (patlama freni sayacı)
        if acilis:
            izin, neden = self.risk.acilis_izni(adres, o.coin, yeni_coin, simdi)
            if not izin:
                return self._atla(o, adres, eylem, "engel", neden)
        slot = self.hesap.slot_bas.get(adres, self.saha.slot)
        ders_carpan = self.ogrenme.agirlik(adres) if acilis else None
        if ders_carpan is not None:
            slot = slot * ders_carpan                              # ortak öğrenme: [0.5, 1.0] çarpan, yalnız açılış/artırma boyutu
        if golge_carpan is not None and golge_carpan != 1.0:
            slot = slot * golge_carpan                             # K-73 B5: trader kaldıracı > golge_kaldirac_uyari → yeni açılış/artırma boyutu x0.5 (yalnız sanal)
        mk = self.mark(o.coin, o.px)
        biz_usd = abs(biz_sz) * (mk or o.px)
        hesap_usd = self.trader_hesap_usd(adres, simdi, taze_sart=eylem in ("ac", "artir")) if eylem in ("ac", "artir", "azalt") else 0.0
        if eylem in ("ac", "artir") and not hesap_usd:
            return self._atla(o, adres, eylem, "atlandi", "trader_hesap_yok")
        trader_once, trader_sonra = (0.0, sonra) if eylem == "ac" else ((once, 0.0) if eylem == "kapat" else (once, sonra))
        slot_toplam = sum(abs(p.sz) * (self.mark(c, p.giris) or p.giris) for c, p in self.hesap.poz.get(adres, {}).items())       # trader'ın TÜM coinlerdeki kopya nosyoneli (K‑35)
        emir_usd, neden = boyut.hedef_emir(eylem, trader_once, trader_sonra, hesap_usd or 0.0, biz_usd, slot, o.px, self.rules, slot_toplam, bant=True)
        hedef = (min(float(slot) * abs(trader_sonra) * o.px / hesap_usd, float(self.rules["radar_slot_tavan_carpan"]) * float(slot)) if hesap_usd and o.px > 0 else None)
        self._boyut_girdi = {"trader_poz_once": trader_once, "trader_poz_sonra": trader_sonra, "trader_hesap_usd": hesap_usd or None, "slot_usd": slot,        # elle denetim (VERI_SOZLESMESI): boyut girdileri
                             "biz_poz_usd": biz_usd, "biz_slot_toplam_usd": slot_toplam, "hedef_usd": hedef, "ders_carpan": ders_carpan, "golge_carpan": golge_carpan}
        if emir_usd <= 0:
            return self._atla(o, adres, eylem, "atlandi", neden)
        if acilis and self.ogrenme.filtre_kontrol(adres, o.coin, simdi, {"trader_hesap_usd": hesap_usd, "trader_poz_usd": abs(trader_sonra) * o.px,      # ortak öğrenme ML filtresi: yalnız ATLAR (counterfactual'a `_atla` yazar)
                                                  "trader_kaldirac": (self.kaldirac_tr.get(adres) or {}).get("anlik_kaldirac")}):
            return self._atla(o, adres, eylem, "atlandi", "ml_filtre_atla")
        if acilis:
            emir_usd, kn = self.risk.coin_tavani(emir_usd, self.hesap.brut_coin(o.coin, self.marks))
            if emir_usd <= 0:
                return self._atla(o, adres, eylem, "engel", kn)
            neden = kn or neden
            emir_usd, sn = self.risk.sig_coin_kirp(emir_usd, biz_usd, self.coin_hacmi(o.coin), slot)                          # K-62 sığ coin tavanı (trader başına)
            if emir_usd <= 0:
                return self._atla(o, adres, eylem, "engel", sn)
            neden = sn or neden
            emir_usd, mn = self.risk.marj_kirp(emir_usd, self.hesap.marj_toplam(), self.ozsermaye())                      # K‑35 toplam marj tavanı
            if emir_usd <= 0:
                return self._atla(o, adres, eylem, "engel", mn)
            neden = mn or neden
        yon = ("B" if sonra > 0 else "A") if acilis else ("A" if biz_sz > 0 else "B")
        if acilis:
            self.son_atla.pop(f"{adres}|{o.coin}", None)           # K-75: emir verildi → eski atlama nedeni geçersiz
        if telafi is not None and acilis:                          # K-75: kaçan açılış telafisi: boyut TÜM kurallardan geçti (aynı yol); kayıtta neden "kacan_telafi", asıl boyut nedeni ayrı alanda
            if self._boyut_girdi is not None:
                self._boyut_girdi.update({**telafi, "telafi_boyut_neden": neden})
            neden = "kacan_telafi"
        if eylem == "kapat":                                       # trader tam kapanış: teyitli kapanış (yeniden deneme merdiveni, K‑37 §1)
            sonuc = self._kapat_coin(adres, o.coin, neden, simdi, o)
            return sonuc[1] or Sonuc(adres, o.coin, eylem, "atlandi", "kapanis_yok")
        s = self._yurut(o, adres, eylem, yon, emir_usd, not acilis, abs(biz_sz) if not acilis else None, neden, gec, simdi)
        if yeni_coin and s.karar == "emir":                        # O1: patlama freni yalnız GERÇEKTEN açılan farklı coinleri sayar (emir sonrası)
            self.risk.yeni_coin_kaydet(adres, o.coin, simdi)
        if eylem == "azalt":                                       # kısmi dolum kalırsa bir sonraki dakikada yeniden dene
            hedef = biz_sz - (1 if biz_sz > 0 else -1) * min(emir_usd / (mk or o.px), abs(biz_sz))
            self._azalt_kuyruga(adres, o.coin, hedef, neden, simdi, mk or o.px)
        return s

    def _hedef_usd(self, adres: str, coin: str, mk: float) -> float | None:
        """Kopya hedefi ($, işaretli; `boyut.hedef_emir` ile aynı mantık: slot × trader nosyonel / trader hesap, coin tavanı `radar_slot_tavan_carpan` × slot). Ağ yok: önbellekteki hesap değeri; bilinmiyorsa None."""
        c = self.hesap_tr.get(adres)
        hesap = float(c["deger"]) if c and c.get("deger") else 0.0
        poz = self.poz_tr.get(adres, {}).get(coin, 0.0)
        if hesap <= 0 or mk <= 0:
            return None
        slot = float(self.hesap.slot_bas.get(adres, self.saha.slot))
        usd = min(slot * abs(poz) * mk / hesap, float(self.rules["radar_slot_tavan_carpan"]) * slot)
        return usd if poz > 0 else -usd

    def _karsi_olgu_ac(self, o: Olay, adres: str, neden: str) -> None:
        """Alınmayan sinyal (counterfactual; YALNIZ KAYIT): atlanan açılış/artırma için "hayali pozisyon" (hedef − mevcut kopya, işaretli yönde). (adres, coin) başına tek kayıt (ilk atlanan kalır); en çok 500 açık.
        `karsi_olgu_sik_nedenler` (ör. slot_tavani; YALNIZ KAYIT): anahtar `adres|coin|neden|kova` (kova = saat/`karsi_olgu_sik_aralik_dk` dilimi) → (adres, coin) başına dilim başına bir kayıt; bu nedenlerin toplam kaydı `karsi_olgu_sik_azami` ile sınırlı, genel 500 sınırı aynen geçerli."""
        sik_nedenler = set(self.rules.get("karsi_olgu_sik_nedenler") or [])
        if neden in sik_nedenler:
            kova = int(self.saat_ms() // (float(self.rules["karsi_olgu_sik_aralik_dk"]) * 60_000))
            anahtar = f"{adres}|{o.coin}|{neden}|{kova}"
            sik_acik = sum(1 for v in self.karsi_olgu.values() if v.get("neden") in sik_nedenler)
            if anahtar in self.karsi_olgu or sik_acik >= int(self.rules["karsi_olgu_sik_azami"]) or len(self.karsi_olgu) >= 500:
                return
        else:
            anahtar = f"{adres}|{o.coin}"
            if anahtar in self.karsi_olgu or len(self.karsi_olgu) >= 500:
                return
        mk = self.mark(o.coin, o.px) or o.px
        hedef = self._hedef_usd(adres, o.coin, mk)
        if not hedef:
            return
        yon = "B" if hedef > 0 else "A"
        biz = self.hesap.sz(adres, o.coin) * mk
        usd = abs(hedef) - (abs(biz) if biz * hedef > 0 else 0.0)
        if usd <= 0:
            return
        self.karsi_olgu[anahtar] = {"yon": yon, "hayali_usd": usd, "giris": mk, "neden": neden, "ms": self.saat_ms(), "son_pnl": 0.0}

    def karsi_olgu_adimi(self, simdi: int) -> None:
        """Dakikalık (YALNIZ KAYIT): hayali pozisyonları mark'a göre değerler; trader o coini kapatınca (poz_tr 0 / ters yön) ya da `karsi_olgu_azami_saat` dolunca kapatır → `karsi_olgu_kapandi`."""
        azami = float(self.rules.get("karsi_olgu_azami_saat", 72)) * 3_600_000
        for anahtar in list(self.karsi_olgu):
            k = self.karsi_olgu[anahtar]
            parca = anahtar.split("|")                                  # 2 parçalı (adres|coin) ve 4 parçalı (adres|coin|neden|kova) anahtar: ikisi de okunur
            adres, coin = parca[0], parca[1]
            mk = self.marks.get(coin)
            if mk:
                k["son_pnl"] = izleme.hayali_pnl(k["yon"], k["hayali_usd"], k["giris"], mk)
            poz = self.poz_tr.get(adres, {}).get(coin, 0.0)
            bitti = abs(poz) < 1e-9 or (poz > 0) != (k["yon"] == "B")
            kapanis = "trader_kapadi" if bitti else ("sure_doldu" if simdi - int(k["ms"]) >= azami else None)
            if kapanis is None:
                continue
            del self.karsi_olgu[anahtar]
            g = self.karsi_olgu_gun.setdefault(str(k["neden"]), [0.0, 0.0])
            g[0] += 1
            g[1] += k["son_pnl"]
            self.kayit({"olay": "karsi_olgu_kapandi", "coin": coin, "neden": k["neden"], "yon": k["yon"], "hayali_usd": round(k["hayali_usd"], 2), "pnl_usd": round(k["son_pnl"], 4),
                        "sure_sa": round((simdi - int(k["ms"])) / 3_600_000, 2), "kapanis": kapanis})

    def _ideal_kopya(self) -> dict[str, float]:
        """İdeal kopya nosyoneli (coin -> işaretli $): CT'nin KENDİ kurallarıyla tutacağı pozisyon: saha traderlarının hedefleri; kural gereği açılmayanlar (HIP-3/spot, eski pozisyon = bizim görmediğimiz dolumla oluşmamış, K-41 ters yön) ve yönü çelişen belirsiz coinler HARİÇ. Motorun UYGULADIĞI sınırlarla: coin başına 3 × slot (`_hedef_usd`), min emir (`radar_min_emir_yuvarla_alt` altı açılmaz, 11 $ altı 11 $'a),
        sığ coin tavanı (K-62), trader başına slot toplam tavanı (K-35; orantılı küçültme), coin brüt tavanı (`coin_tavan_usd`), toplam marj tavanı (özsermaye × `canli_marj_kaldirac`; orantılı küçültme). Ağ yok; YALNIZ okuma."""
        r = self.rules
        minimum, alt = float(r["radar_min_emir_usd"]), float(r.get("radar_min_emir_yuvarla_alt", 0.0) or 0.0)
        hip3_acik = self._hip3_acik()
        aday: dict[str, list[tuple[str, float, bool]]] = {}          # coin -> [(adres, işaretli $, bizde ledger kaydı var mı)]
        for adres in self.saha.uyeler:
            slot = float(self.hesap.slot_bas.get(adres, self.saha.slot))
            for coin in self.poz_tr.get(adres, {}):
                mk = self.marks.get(coin)
                h = self._hedef_usd(adres, coin, mk) if mk else None
                if not h:
                    continue
                tutulu = abs(self.hesap.sz(adres, coin)) > EPS
                if not tutulu and ((sinif := coin_sinifi(coin)) == "spot" or (sinif == "hip3" and not hip3_acik)):
                    continue                                          # kural gereği açılmaz (K-42): ideal değil
                if not tutulu and (adres, coin) not in self._poz_tr_ms:
                    continue                                          # trader pozisyonu bizim izlediğimiz bir dolumla oluşmadı (eski pozisyon): kopyalanmaz
                u = abs(h)
                if u < minimum - 1e-9:
                    u = 0.0 if u < alt - 1e-9 else minimum
                u = boyut.sig_coin_kirp(r, u, 0.0, self.coin_hacmi(coin), slot)[0]
                if u > 0:
                    aday.setdefault(coin, []).append((adres, u if h > 0 else -u, tutulu))
        hedefler_tr: dict[str, dict[str, float]] = {}
        for coin, liste in aday.items():
            if any(t for _, _, t in liste):                           # K-41: bizde tutulan yönün tersindeki trader pozisyonu kopyalanmaz (net küçülmesin) → ideale girmez
                tutulan = sum(self.hesap.sz(a_, coin) * (self.marks.get(coin) or 1.0) for a_, _, t in liste if t)
                yon = 1.0 if tutulan >= 0 else -1.0
                liste = [x for x in liste if x[2] or x[1] * yon > 0]
            elif len({x[1] > 0 for x in liste}) > 1:
                continue                                              # hiç tutulmuyor ve yönler çelişiyor: kimin kopyalanacağı belirsiz → bu coin izlenmez (alarm yok)
            for adres, v, _ in liste:
                hedefler_tr.setdefault(adres, {})[coin] = v
        ideal: dict[str, float] = {}
        for adres, hedefler in hedefler_tr.items():
            slot = float(self.hesap.slot_bas.get(adres, self.saha.slot))
            toplam, tavan = sum(abs(v) for v in hedefler.values()), float(r["radar_slot_tavan_carpan"]) * slot
            olcek = min(1.0, tavan / toplam) if toplam > 0 else 1.0
            for coin, v in hedefler.items():
                ideal[coin] = ideal.get(coin, 0.0) + v * olcek
        tavan_coin = coin_tavan_usd(r, self.kasa)
        for coin in ideal:
            if abs(ideal[coin]) > tavan_coin:
                ideal[coin] = tavan_coin if ideal[coin] > 0 else -tavan_coin
        marj = sum(abs(v) for v in ideal.values()) / float(r["canli_marj_kaldirac"])
        oz = self.ozsermaye()
        if marj > oz > 0:
            ideal = {c: v * oz / marj for c, v in ideal.items()}
        return ideal

    def kopya_drift_adimi(self, simdi: int) -> None:
        """Kopya drift alarmı (YALNIZ UYARI): coin başına bizim nosyonel ↔ ideal kopya (saha traderlarının hedef toplamı); drift > `kopya_drift_esik` `kopya_drift_sure_dk` dk sürerse `kopya_drift` kaydı +
        saatlik özette TEK satır (coin başına `kopya_drift_tg_saat` saatte en çok bir; ayrı Telegram mesajı YOK, önem INFO); düzelince `kopya_drift_bitti`. İdeal nosyonel < `kopya_drift_min_usd` ise izlenmez."""
        esik, sure = float(self.rules.get("kopya_drift_esik", 0.25)), float(self.rules.get("kopya_drift_sure_dk", 30)) * DAKIKA
        min_usd = float(self.rules.get("kopya_drift_min_usd", 50))
        ideal = self._ideal_kopya()
        biz: dict[str, float] = {}
        for cs in self.hesap.poz.values():
            for coin, p in cs.items():
                biz[coin] = biz.get(coin, 0.0) + p.sz * (self.marks.get(coin) or p.giris)
        for coin in set(self.kopya_drift) | set(ideal):
            i, b = ideal.get(coin, 0.0), biz.get(coin, 0.0)
            drift = izleme.drift_orani(b, i, min_usd)
            kd = self.kopya_drift.get(coin)
            r = self.rules                                        # bant: motorun emir vermediği fark (`bant_ici`) drift sayılmaz (artırma / azaltma bandı)
            bant = max(float(r["canli_bant_usd"]), float(r["canli_bant_oran"]) * abs(i)) if abs(b) < abs(i) else max(float(r["canli_bant_azalt_usd"]), float(r["canli_bant_azalt_oran"]) * abs(i))
            if abs(i) >= min_usd and drift > esik and abs(b - i) >= bant:
                if kd is None:
                    kd = self.kopya_drift[coin] = {"bas_ms": simdi, "aktif": False}
                if not kd["aktif"] and simdi - int(kd["bas_ms"]) >= sure:
                    kd["aktif"] = True
                    dk = round((simdi - int(kd["bas_ms"])) / DAKIKA)
                    self.kayit({"olay": "kopya_drift", "coin": coin, "biz_usd": round(b, 2), "ideal_usd": round(i, 2), "drift": round(drift, 3), "sure_dk": dk})
                if kd["aktif"]:
                    kd["drift"] = round(drift, 3)                 # saatlik özet satırı için güncel oran
            elif kd is not None:
                del self.kopya_drift[coin]
                if kd["aktif"]:
                    self.kayit({"olay": "kopya_drift_bitti", "coin": coin, "biz_usd": round(b, 2), "ideal_usd": round(i, 2), "drift": round(drift, 3), "sure_dk": round((simdi - int(kd["bas_ms"])) / DAKIKA)})

    def _drift_adaylari(self, simdi: int) -> dict[str, float]:
        """Saatlik özet satırına girecek aktif drift'ler (coin -> oran): son satırdan beri `kopya_drift_tg_saat` saat geçmiş olanlar. Okuma; durum değiştirmez."""
        aralik = float(self.rules.get("kopya_drift_tg_saat", 6)) * 3_600_000
        return {c: float(kd.get("drift", 0.0)) for c, kd in self.kopya_drift.items() if kd.get("aktif") and simdi - self.kopya_drift_tg_ms.get(c, -10**15) >= aralik}

    def _say_neden(self, neden: str) -> None:
        if neden and neden not in ("tamam", "tam_kapanis"):
            self.neden_say[neden] = self.neden_say.get(neden, 0) + 1

    def _atla(self, o: Olay, adres: str, eylem: str, karar: str, neden: str) -> Sonuc:
        self._boyut_girdi = None
        self.sayac[karar] += 1
        self._say_neden(neden)
        self.donem_emir_say("atlanan", neden)
        if self.kip == "sanal":
            self._atla_tampon[neden] = self._atla_tampon.get(neden, 0) + 1
            self._atla_islem.add((adres, o.coin, int(o.zaman_ms) // 1000))
            ad = self._atla_adres.setdefault(neden, {})
            ad[adres] = ad.get(adres, 0) + 1
        if eylem in ("ac", "artir") and neden != "bant_ici":              # K-75: son açılış atlama nedeni (kaçan açılış telafisi filtre/kural atlamasına saygı gösterir; kalıcı)
            self.son_atla[f"{adres}|{o.coin}"] = [neden, self.saat_ms()]
            if len(self.son_atla) > SON_ATLA_MAX:
                for k in sorted(self.son_atla, key=lambda x: self.son_atla[x][1])[:len(self.son_atla) - SON_ATLA_MAX]:
                    del self.son_atla[k]
        self.kayit({"olay": "emir_yok", "adres": adres, "coin": o.coin, "eylem": eylem, "karar": karar, "neden": neden, "trader_dolum_ms": o.zaman_ms, "gorme_ms": o.alma_ms,
                    "yas_ms": self.saat_ms() - o.zaman_ms})
        if eylem == "ac" and neden in tg.KACIRILAN_NEDENLER:          # kaçırılan (geç görülen / veri yok) = eksik kopya → sessiz bilgi; kural gereği atlananlar gönderilmez
            self._kopya_hata("ac", adres, o.coin, tg.atla_etiket(neden))
        if eylem in ("ac", "artir") and neden != "bant_ici":
            try:
                self._karsi_olgu_ac(o, adres, neden)
            except Exception as hata:                      # noqa: BLE001
                self.kayit({"olay": "karsi_olgu_hata", "tur": type(hata).__name__, "mesaj": str(hata)[:160]})       # yalnız muhasebe: karar yolunu ASLA etkilemez
        return Sonuc(adres, o.coin, eylem, karar, neden)

    def _yurut(self, o: Olay, adres: str, eylem: str, yon: str, usd: float, reduce_only: bool, acik_sz: float | None, neden: str, gec: bool, simdi: int,
               bant: float | None = None, kimlik: str | None = None) -> Sonuc:
        self._say_neden(neden)
        self.donem_emir_say("emir")
        if neden == "min_emir_yuvarlandi":
            self.donem_emir_say("yuvarlanan")
        kimlik = kimlik if kimlik is not None else (o.kimlik or f"x:{adres}:{o.coin}:{simdi}")
        cloid = cloid_uret(kimlik, eylem)
        emir_ms = self.saat_ms()
        self.niyet.niyet_yaz(kimlik=kimlik, eylem=eylem, adres=adres, coin=o.coin, yon=yon, usd=round(float(usd), 6), reduce_only=reduce_only, cloid=cloid, ms=emir_ms)      # ÖNCE yaz (fsync), SONRA emir
        ek: dict[str, Any] = {}
        if bant is not None:
            ek["bant"] = bant
        if self.kip == "gercek":
            ek["cloid"] = cloid
        d = self.yurutucu.emir(o.coin, yon, usd, reduce_only, acik_sz, **ek)
        dolum_ms = self.saat_ms()
        belirsiz = d.durum == "belirsiz" and self.kip == "gercek"
        if belirsiz:                                        # G-1: emir HL'ye ulaşmış olabilir → sonuç satırı YAZILMAZ (niyet açık kalır), "red" sayılmaz; `belirsiz_coz` orderStatus(cloid) ile çözer
            self.hesap.belirsiz[cloid] = {"ms": emir_ms, "deneme": 0, "adres": adres, "coin": o.coin}
            self.risk.bayrak("belirsiz", True)              # çözülene dek yeni açılış/artırma yok (kapanış serbest)
            self.sayac["belirsiz"] = self.sayac.get("belirsiz", 0) + 1
            self.tg.gonder(tg.alarm("ALARM: emir sonucu belirsiz", f"{o.coin} {eylem} emrine borsa yanıtı alınamadı ({d.neden}).\nEmir durumu borsadan sorgulanıp deftere işlenecek; o zamana dek yeni pozisyon açılmıyor."))
        else:
            self.niyet.sonuc_yaz(cloid, d.durum, dolum_ms, sz=d.sz, px=d.px, ucret=d.ucret)
        self.sayac["emir"] += 1
        if not belirsiz:
            self.sayac[d.durum if d.durum in self.sayac else "red"] += 1
        if d.neden == "min_nosyonel":
            self.sayac["min_nosyonel"] += 1
            self._say_neden("min_nosyonel")
        kayma_trader = None
        if d.px and o.px:
            ham = (d.px - o.px) / o.px
            kayma_trader = ham if yon == "B" else -ham
        onceki_poz = self.hesap.poz.get(adres, {}).get(o.coin)
        onceki_sz, onceki_giris = (float(onceki_poz.sz), float(onceki_poz.giris)) if onceki_poz is not None else (0.0, 0.0)       # uygula() Poz'u yerinde değiştirir: Telegram için önce al
        onceki_ctx = onceki_poz.giris_ctx if onceki_poz is not None and abs(onceki_poz.sz) > 1e-12 else None      # kapanış kaydına taşınacak giriş damgası (uygula pozisyonu siler)
        pnl = None                                          # pano §C3: bu dolumun gerçekleşen K/Z'si (ücret hariç; yalnız azaltma/kapanışta anlamlı)
        if d.dolu_mu:
            try:
                pnl = self.hesap.uygula(adres, o.coin, yon, d.sz, d.px, d.ucret, dolum_ms)
                if onceki_poz is None or abs(onceki_poz.sz) <= 1e-12:           # yeni pozisyon: giriş anı rejim/duygu damgası (yalnız bilgi)
                    yeni_poz = self.hesap.poz.get(adres, {}).get(o.coin)
                    if yeni_poz is not None:
                        yeni_poz.giris_ctx = rejim_sonuc.giris_ctx(self.rejim_anlik, self.haber_anlik, o.coin, dolum_ms)
                        onceki_ctx = yeni_poz.giris_ctx
            except ValueError as hata:                      # defter reddi: kayda geçer, motor çökmez
                self.kayit({"olay": "defter_hata", "adres": adres, "coin": o.coin, "hata": str(hata)[:120]})
            if self.kip == "gercek":                        # G7: gerçek fee mi tahmin mi (sanal kip değişmez)
                if getattr(d, "ucret_gercek", False):
                    self.ucret_gercek_usd += d.ucret
                else:
                    self.ucret_tahmin_say += 1
                    self.kayit({"olay": "ucret_tahmin", "adres": adres, "coin": o.coin, "cloid": cloid, "ucret": d.ucret})
                    if getattr(d, "ucret_tahmini", False):          # Denetim-6 (O9): gerçek ücret kilit dışında, dakikalık bakımda düzeltilir
                        self.ucret_bekleyen.append({"cloid": cloid, "adres": adres, "coin": o.coin, "oid": d.oid, "ms": int(d.emir_ms or dolum_ms), "kayit_ms": dolum_ms, "tahmin": d.ucret})
            if kayma_trader is not None:
                self.kayma_trader.append(kayma_trader)
            if d.kayma_oran is not None:
                self.kayma_ref.append(d.kayma_oran)
            if d.usd_dolan > self.en_buyuk_emir.get("usd", 0.0):
                self.en_buyuk_emir = {"usd": d.usd_dolan, "coin": o.coin, "eylem": eylem, "boyut_neden": neden, "adres": adres}
        self.hesap.son_niyet_cloid = cloid
        self._dolum_yaz()                                   # t4b #3: her sonuçtan sonra atomik (motor.json, hesap.json)
        self.kayit({"olay": "emir", "kip": self.kip, "adres": adres, "coin": o.coin, "eylem": eylem, "yon": yon, "usd_istenen": usd, "usd_dolan": d.usd_dolan, "sz": d.sz,
                    "reduce_only": reduce_only, "pnl_usd": (round(pnl, 6) if pnl is not None else None), "durum": d.durum, "red_neden": d.neden, "boyut_neden": neden, "trader_px": o.px, "trader_dolum_ms": o.zaman_ms, "gorme_ms": o.alma_ms,
                    "emir_ms": emir_ms, "dolum_ms": dolum_ms, "referans_px": d.referans_px, "dolum_px": d.px, "kayma_ref": d.kayma_oran, "kayma_trader": kayma_trader, "ucret": d.ucret,
                    "gec_goruldu": gec, "kaynak": o.kaynak, "bant": bant, "cloid": cloid, "giris_ctx": onceki_ctx, "rejim": rejim.coin_rejimi(self.rejim_anlik, o.coin, self.saat_ms()), **haber.emir_alanlari(self.haber_anlik, o.coin, self.saat_ms()), "funding_usd": round(self.hesap.funding.get(adres, 0.0), 6),
                    **({"defter": d.defter} if self.kip == "gercek" and getattr(d, "defter", None) else {}),       # S-12: emir anı defteri (yalnız gerçek kip; gercek_sanal_karsilastir)
                    **({"ham": maskele(json.dumps(d.ham, ensure_ascii=False, default=str))[:300]} if d.durum in ("red", "belirsiz") and d.ham else {}),       # G-19: red → HL ham yanıtı (300 karakter)
                    **{k: (round(v, 8) if isinstance(v, float) else v) for k, v in (self._boyut_girdi or {}).items()}})
        self._boyut_girdi = None
        self._ozet_emir += 1
        e = {"adres": adres, "coin": o.coin, "yon": yon, "usd": d.usd_dolan or usd, "px": d.px, "kayma": kayma_trader, "durum": d.durum, "eylem": eylem, "neden": d.neden}
        acildi = d.dolu_mu and eylem == "ac"
        kapandi = d.dolu_mu and abs(onceki_sz) > 1e-12 and abs(getattr(self.hesap.poz.get(adres, {}).get(o.coin), "sz", 0.0)) <= 1e-12
        gecikme_sn = (dolum_ms - o.zaman_ms) / 1000.0 if (d.dolu_mu and o.kaynak != "kapat" and o.zaman_ms) else None
        ozet = None
        if d.dolu_mu:                                       # günlük rapor sayaçları + pozisyon toplamı (kapandı mesajı)
            self._say_gun[eylem] = self._say_gun.get(eylem, 0) + 1
            if kayma_trader is not None:
                self._kopya_fark.append(abs(kayma_trader))
            if gecikme_sn is not None and gecikme_sn >= 0:
                self._gecikme.append(gecikme_sn)
            kz_dolum = float(pnl or 0.0) - (float(d.ucret or 0.0) if not acildi and eylem != "artir" else 0.0)   # pano ile aynı: kapanış/azaltma dolumunun neti (gerçekleşen − o dolumun ücreti)
            anahtar_poz = f"{adres}|{o.coin}"
            if acildi:
                ozet = self._poz_ozet[anahtar_poz] = {"tutar": float(d.usd_dolan or usd), "artir": 0, "azalt": 0, "pnl": 0.0}
            else:
                ozet = self._poz_ozet.get(anahtar_poz) or {"tutar": abs(onceki_sz) * onceki_giris, "artir": 0, "azalt": 0, "pnl": 0.0}
                if eylem == "artir":
                    ozet["tutar"] += float(d.usd_dolan or usd)
                    ozet["artir"] += 1
                elif eylem == "azalt":
                    ozet["azalt"] += 1
                self._poz_ozet[anahtar_poz] = ozet
            ozet["pnl"] += kz_dolum
            if kapandi:
                self._poz_ozet.pop(anahtar_poz, None)
        if belirsiz:                                        # alarm yukarıda gitti; sonuç `belirsiz_coz`da bildirilir
            pass
        elif acildi or kapandi:                             # kullanıcı standardı: açıldı/kapandı AYRI kısa mesaj (trader adı + giriş/tutar/stop ya da K/Z + neden)
            self._acilis_kapanis_mesaji(acildi, adres, o.coin, yon, d, onceki_giris, pnl, neden, o, gecikme_sn, ozet)
            if self.kip == "sanal":
                self._emir_tampon.append(e)                 # saatlik özet (bastırılan tür `emir_ozeti`) tutarlı kalsın
        elif self.kip == "gercek":                          # gerçek parada dolu olmayan emir hemen bildirilir (🚨 sesli; G-18 tampon); dolu artırma/azaltma bastırılır (kayda yazılır)
            if d.dolu_mu:
                self.kayit({"olay": "tg_bastirildi", "tur": "emir_artir_azalt", "metin": f"{o.coin} {eylem} {e['usd']:.2f} $"})
            else:
                self.tg.tampona(e, lambda liste: tg.msg_emir_ozeti(self.kip, liste, 0))
        else:
            self._emir_tampon.append(e)
        if not d.dolu_mu and not belirsiz and eylem == "ac":
            self._kopya_hata("ac", adres, o.coin, "emir reddedildi" if d.durum == "red" else "emir dolmadı")
        return Sonuc(adres, o.coin, eylem, "emir" if d.dolu_mu else ("belirsiz" if belirsiz else "red"), d.neden or neden, d)

    def _acilis_kapanis_mesaji(self, acildi: bool, adres: str, coin: str, yon: str, d: Any, onceki_giris: float, pnl: float | None, neden: str, o: Olay | None = None,
                               gecikme_sn: float | None = None, ozet: dict | None = None) -> None:
        """Telegram (SESSİZ): pozisyon AÇILDI (giriş (trader fiyatı · fark) · tutar · stop [· N sn geç]) / KAPANDI ($, %, neden; artırma varsa toplam tutar). Gecikme eki yalnız `canli_olay_stale_sn` aşılınca.
        Saatlik üst sınır (`canli_telegram_islem_saat_max`, varsayılan 10): aşılanlar o saatin sonunda tek satırda (`_islem_toplu`). Hata motoru durdurmaz."""
        try:
            if acildi:
                p = self.hesap.poz.get(adres, {}).get(coin)
                giris = float(d.px or 0.0) or float(p.giris if p is not None else 0.0)
                oran = float(self.rules.get("canli_felaket_stop_oran", 0) or 0)
                oran = self._stop_orani(coin, yon == "B", giris, oran, 0.03) if oran > 0 else oran
                stop = (giris * (1 - oran) if yon == "B" else giris * (1 + oran)) if oran > 0 and giris > 0 else None
                gec_ek = gecikme_sn if (gecikme_sn is not None and gecikme_sn > float(self.rules.get("canli_olay_stale_sn", 120))) else None
                self._islem_mesaji(tg.msg_acildi(adres, coin, yon, giris, float(d.usd_dolan), stop, self.kip, float(o.px) if o is not None and o.px else None, gec_ek), True, 0.0,
                                   {"adres": adres, "coin": coin, "yon": yon, "pnl": 0.0, "neden": "ac"})
            else:
                toplam = float(ozet["tutar"]) if ozet else (abs(float(d.sz)) * onceki_giris if d.sz else 0.0)
                kz = float(ozet["pnl"]) if ozet else float(pnl or 0.0)
                self._islem_mesaji(tg.msg_kapandi(adres, coin, kz, (kz / toplam) if toplam > 0 else None, neden, self.kip, toplam, int(ozet["artir"]) if ozet else 0, int(ozet["azalt"]) if ozet else 0), False, kz,
                                   {"adres": adres, "coin": coin, "yon": yon, "pnl": round(kz, 6), "neden": neden})
        except Exception as hata:                           # noqa: BLE001 - mesaj hatası emri/defteri etkilemez
            self.kayit({"olay": "tg_mesaj_hata", "tur": type(hata).__name__})

    def _islem_mesaji(self, metin: str, acildi: bool, kz: float, alan: dict | None = None) -> None:
        simdi = self.saat_ms()
        p = self._islem_pen
        if p["bas"] is None or simdi - int(p["bas"]) >= 3_600_000:
            self._islem_toplu(simdi)
            p = self._islem_pen = {"bas": simdi, "n": 0, "ac": 0, "kapat": 0, "net": 0.0}
        if p["n"] < int(self.rules.get("canli_telegram_islem_saat_max", 10)):
            p["n"] += 1
            self.tg.gonder(metin, alan=alan)
        else:
            p["ac" if acildi else "kapat"] += 1
            p["net"] += kz
            self.kayit({"olay": "tg_mesaj", "tur": "islem_saat_siniri", "anahtar": None, "seviye": "INFO", "sessiz": False, "metin": metin, "gonderildi": False, "bastirildi": True, **(alan or {})})
            self.kayit({"olay": "tg_bastirildi", "tur": "islem_saat_siniri", "metin": metin[:120]})

    def _islem_toplu(self, simdi: int, zorla: bool = False) -> None:
        """Saat dolunca (ya da vardiya sonunda `zorla`) üst sınırı aşan işlemler TEK satırda: '+7 işlem daha: 4 açılış, 3 kapanış, net −2,10 $'."""
        p = self._islem_pen
        if p["bas"] is None or not (zorla or simdi - int(p["bas"]) >= 3_600_000) or (p["ac"] + p["kapat"]) == 0:
            return
        self.tg.gonder(tg.msg_islem_toplu(int(p["ac"]), int(p["kapat"]), float(p["net"])))
        self._islem_pen = {"bas": None, "n": 0, "ac": 0, "kapat": 0, "net": 0.0}

    def _kopya_hata(self, tur: str, adres: str, coin: str, neden: str) -> None:
        """Sessiz bilgi (6 saatte bir, anahtar tür|adres|coin): 'Trader açtı, biz açamadık: <neden>' / 'Trader kapattı, biz kapatamadık: <neden>'. YALNIZ hata/eksik kopya (kural gereği atlananlar için gönderilmez)."""
        try:
            self.tg.uyar(f"kopya_{tur}|{adres}|{coin}", tg.msg_kopya_hata(tur, coin, adres, neden), "INFO")
        except Exception:                                   # noqa: BLE001
            pass

    # ------------------------------------------------------------------ kapanış teyidi (K‑37 §1)
    def _mark_kapanis(self, adres: str, coin: str) -> float:
        p = self.hesap.poz.get(adres, {}).get(coin)
        return self.mark(coin, p.giris if p else None) or (p.giris if p else 0.0)

    def _kalan_sz(self, adres: str, coin: str) -> tuple[float, bool]:
        """Kapatılacak işaretli miktar. Sanal: yerel defter. Gerçek: borsa pozisyonu (tüm dex) − diğer adreslerin yerel payı (tek HL hesabı!). Döner (sz, borsadan_mi)."""
        yerel = self.hesap.sz(adres, coin)
        if self.kip != "gercek":
            return yerel, False
        try:
            hl = clearinghouse_pozisyonlari(self.post_hizli, os.environ.get("HL_HESAP_ADRESI", ""), self._dexler())
        except Exception as hata:                          # noqa: BLE001
            self.kayit({"olay": "kapanis_borsa_okuma_hata", "tur": type(hata).__name__})
            return yerel, False
        if abs(yerel) > EPS and abs(hl.get(coin, 0.0)) <= EPS:        # Denetim-1: boş/eksik pozisyon yanıtı tek okumayla "borsa 0" sayılmaz (defter emirsiz silinir, stop iptal olurdu)
            mk0 = self._mark_kapanis(adres, coin)
            if not mk0 or abs(yerel) * mk0 > float(self.rules["canli_kapanis_toz_usd"]):
                try:
                    hl2: dict[str, float] | None = clearinghouse_pozisyonlari(self.post_hizli, os.environ.get("HL_HESAP_ADRESI", ""), self._dexler())
                except Exception as hata:                  # noqa: BLE001
                    self.kayit({"olay": "kapanis_borsa_okuma_hata", "tur": type(hata).__name__, "asama": "teyit"})
                    hl2 = None
                if hl2 is None or abs(hl2.get(coin, 0.0)) > EPS:      # ikinci okuma teyit etmedi: defterden SİLME; mutabakat bayrağı + alarm
                    self.risk.bayrak("mutabakat", True)
                    self.kayit({"olay": "bos_okuma_teyitsiz", "adres": adres, "coin": coin, "yerel_sz": yerel, "ikinci_okuma": None if hl2 is None else hl2.get(coin, 0.0)})
                    if self._aralik_mi("bos_okuma_alarm", self.saat_ms(), 600):
                        self.tg.gonder(tg.alarm("ALARM: borsa pozisyon okuması tutarsız", f"{coin}: defterde {yerel:g} var, borsa okuması boş döndü ama ikinci okuma teyit etmedi.\n"
                                                "Defter silinmedi, stop iptal edilmedi; yeni açılış durdu (mutabakat)."))
                    if hl2 is None:
                        return yerel, False
                    hl = hl2                                # ikinci okuma pozisyonu gösteriyor: ona göre devam (kapanış emri borsadaki gerçek miktara kırpılır)
        diger = sum(c[coin].sz for a, c in self.hesap.poz.items() if a != adres and coin in c)
        self._kalan_hl = {"coin": coin, "hl": hl.get(coin, 0.0), "diger": diger}
        return self._kirp(yerel, hl.get(coin, 0.0) - diger), True

    @staticmethod
    def _kirp(yerel: float, k: float) -> float:
        """G-13: borsadaki pay `k` (= HL − diğer adreslerin yerel payı) yerel pozisyonla işaret ve büyüklükte kırpılır. `yerel·k ≤ 0` → 0 (kapatılacak bir şey yok: borsa
        payı yok ya da ters); değilse işaret `yerel`'in, büyüklük `min(|k|, |yerel|)`. Böylece kapanış emri ASLA pozisyonu büyütecek yönde ya da yerel paydan büyük gitmez."""
        if yerel * k <= 0:
            return 0.0
        return math.copysign(min(abs(k), abs(yerel)), yerel)

    def _harici_kapanis(self, adres: str, coin: str, kalan: float, mk: float, simdi: int, neden: str) -> None:
        """G-13: gerçek kipte borsadaki pay yerel defterden belirgin küçük (HL tasfiye / ADL / elle kapatma). Fark emir göndermeden yerel defterden mark ile düşülür
        (`_yerel_temizle`; K/Z realize'a geçer → özdeşlik korunur), kayıt + sayaç + Telegram alarmı. Kuyruğa girmez (sonsuz yeniden deneme yok)."""
        yerel = self.hesap.sz(adres, coin)
        fark = abs(yerel) - abs(kalan)
        if fark <= EPS or (mk and fark * mk <= float(self.rules["canli_kapanis_toz_usd"])):
            return
        bilgi = getattr(self, "_kalan_hl", None) or {}
        hl = bilgi.get("hl") if bilgi.get("coin") == coin else None
        self.sayac["harici_kapanis"] = self.sayac.get("harici_kapanis", 0) + 1
        self.kayit({"olay": "harici_kapanis", "adres": adres, "coin": coin, "yerel_sz": yerel, "borsa_pay_sz": kalan, "hl_sz": hl, "mark": mk, "usd": round(fark * (mk or 0.0), 6), "neden": neden})
        self.tg.gonder(tg.alarm("ALARM: borsada pozisyon yok (harici kapanış)",
                                f"{coin} (trader {tg.kisa(adres)}): defter {yerel:g}, borsadaki pay {kalan:g} (HL {hl if hl is not None else '?'}).\n"
                                f"Fark ({fark:g} {coin}) borsa dışında kapanmış (tasfiye/ADL/elle); emir gönderilmedi, defterden mark {mk:g} ile düşüldü."))

    def _yerel_temizle(self, adres: str, coin: str, mk: float, simdi: int, neden: str) -> None:
        """Borsa/toz teyidi: pozisyon 0 → yerel defterde kalan toz varsa mark'ta kapatılır (ücretsiz)."""
        sz = self.hesap.sz(adres, coin)
        if abs(sz) > EPS and mk:
            try:
                self.hesap.uygula(adres, coin, "A" if sz > 0 else "B", abs(sz), mk, 0.0, simdi)
            except ValueError:
                pass
            self.kayit({"olay": "kapanis_duzeltme", "adres": adres, "coin": coin, "sz": sz, "neden": neden})

    def _kapat_coin(self, adres: str, coin: str, neden: str, simdi: int, o: Olay | None = None, bantlar: list[float] | None = None, baslangic: int = 0) -> tuple[bool, Sonuc | None]:
        """Adresin tek coindeki pozisyonunu reduce‑only kapatır: IOC sonrası kalan varsa TAZE defterle yeniden dener (en çok `len(bantlar)` = 5; bant %0,5 → %1 → %2).
        Gerçek kipte her denemeden sonra borsa pozisyonu okunur; "kapandı" yalnız kalan ≈ 0 iken yazılır. Teyit yoksa `kapanis_kuyrugu`na (alarm + dakikalık yeniden deneme) girer. Döner (teyitli, son Sonuc)."""
        bantlar = bantlar or [float(x) for x in self.rules["canli_kapanis_bantlari"]]
        toz = float(self.rules["canli_kapanis_toz_usd"])
        son: Sonuc | None = None
        bekle = False
        for i in range(baslangic, len(bantlar) + 1):
            if self.bekci_nabiz is not None:               # bekçi: uzun kapanış döngüsü (DUR, çok coin, yavaş HL) ilerlediği sürece süreç öldürülmez; tek deneme asılırsa yine tetiklenir
                self.bekci_nabiz()
            kalan, borsadan = self._kalan_sz(adres, coin)
            mk = self._mark_kapanis(adres, coin) or (o.px if o else 0.0) or 0.0
            if abs(kalan) < EPS or (mk and abs(kalan) * mk <= toz):
                if borsadan:
                    self._harici_kapanis(adres, coin, kalan, mk, simdi, neden)
                self._yerel_temizle(adres, coin, mk, simdi, neden)
                self.kapanis_kuyrugu.pop(f"{adres}|{coin}", None)
                return True, son
            if i >= len(bantlar):
                break
            if (son is not None and son.karar == "belirsiz") or (adres, coin) in self._belirsiz_coinler():      # Y-2: bu coinde sonucu belirsiz emir varken YENİ emir yok (borsa teyidi yukarıda okundu)
                bekle = True
                break
            yon = "A" if kalan > 0 else "B"
            fake = Olay("", adres, adres, simdi, simdi, "kapat", False, "", coin, mk, abs(kalan), yon, None)
            kimlik = f"kapat:{adres}:{coin}:{self.saat_ms()}:{i}:{neden[:12]}"
            son = self._yurut(fake, adres, "kapat", yon, abs(kalan) * mk * 1.05, True, abs(kalan), neden, False, simdi, bant=bantlar[i], kimlik=kimlik)
        if bekle:                                            # Y-2: merdiven durur; çözüm `belirsiz_coz` (orderStatus(cloid), G-1), kalan kapanış kuyruğu (çözülene dek beklenir)
            self.kayit({"olay": "kapanis_belirsiz_durdu", "adres": adres, "coin": coin, "neden": neden})
            self._eksik_ekle(adres, coin, "kapat", 0.0, neden, simdi, deneme=0)
            return False, son
        self._eksik_ekle(adres, coin, "kapat", 0.0, neden, simdi, deneme=len(bantlar))
        return False, son

    def _eksik_ekle(self, adres: str, coin: str, tur: str, hedef_sz: float, neden: str, simdi: int, deneme: int = 0) -> None:
        anahtar = f"{adres}|{coin}"
        yeni = anahtar not in self.kapanis_kuyrugu
        e = self.kapanis_kuyrugu.setdefault(anahtar, {"tur": tur, "hedef_sz": hedef_sz, "neden": neden, "deneme": 0, "ms": simdi})
        e["deneme"] = max(int(e.get("deneme", 0)), deneme)
        if tur == "kapat":
            e["tur"], e["hedef_sz"] = "kapat", 0.0
        if deneme >= len(self.rules["canli_kapanis_bantlari"]) and (yeni or not e.get("eksik")):
            e["eksik"] = True
            if neden in ("tam_kapanis", "trader_kapali_senkron"):
                self._kopya_hata("kapat", adres, coin, "kapanış emri doldurulamadı, yeniden deneniyor")
            self.sayac["kapanis_eksik"] += 1
            self.kayit({"olay": "kapanis_eksik", "adres": adres, "coin": coin, "neden": neden})
            self.tg.gonder(tg.alarm("ALARM: pozisyon kapanmadı", f"kapanış EKSİK: {coin} (trader {tg.kisa(adres)}) {len(self.rules['canli_kapanis_bantlari'])} denemede kapanmadı ({neden}).\nArtan aralıklarla (1 → 30 dk) yeniden denenecek, yeni pozisyon açılmıyor."))

    def _lot_adim(self, coin: str) -> float | None:
        """2. denetim O-5: gerçek kipte coinin lot adımı (yürütücünün szDecimals'ı); sanalda / bilinmiyorsa None (lot kuralı yok)."""
        f = getattr(self.yurutucu, "lot_adim", None)
        if self.kip != "gercek" or f is None:
            return None
        try:
            return f(coin)
        except Exception:                              # noqa: BLE001
            return None

    def _azalt_kuyruga(self, adres: str, coin: str, hedef_sz: float, neden: str, simdi: int, mk: float) -> None:
        kalan = self.hesap.sz(adres, coin) - hedef_sz
        if abs(kalan) * mk > float(self.rules["canli_kapanis_toz_usd"]) and kalan * self.hesap.sz(adres, coin) > 0:
            adim = self._lot_adim(coin)
            if adim is not None and abs(kalan) < adim / 2 - 1e-12:           # O-5: kalıntı yarım lotun altında: borsada emir verilemez (0 lot → `sz_sifir`); kuyruğa alınmaz, `kapanis_eksik` doğmaz
                self.kayit({"olay": "azalt_lot_alti", "adres": adres, "coin": coin, "kalan_sz": abs(kalan), "lot": adim})
                return
            self._eksik_ekle(adres, coin, "azalt", hedef_sz, neden, simdi, deneme=0)

    def _kuyruk_geri_cekil(self, anahtar: str, simdi: int) -> None:
        """S-8: başarısız kuyruk denemesinden sonra üstel geri çekilme (1, 2, 4, 8, 16, 30, 30 … dk); girdi başına UTC günlük deneme sayacı; tavan (`canli_kuyruk_gunluk_tavan`, varsayılan 24)
        aşılınca o gün bir kez alarm (yeniden deneme 30 dk aralıkla sürer: pozisyon açıkta bırakılmaz)."""
        e = self.kapanis_kuyrugu.get(anahtar)
        if e is None:
            return
        k = int(e.get("geri_sayac", 0)) + 1
        e["geri_sayac"] = k
        bekle_dk = 1 if (self.risk.dur or self.dur_bekliyor) else KUYRUK_GERI_DK[min(k, len(KUYRUK_GERI_DK)) - 1]     # DUR kapanışı sürerken geri çekilme yok: dakikada bir dene
        e["sonraki_ms"] = simdi + bekle_dk * DAKIKA
        g = gun(simdi)
        if e.get("gun") != g:
            e["gun"], e["gun_deneme"] = g, 0
        e["gun_deneme"] = int(e.get("gun_deneme", 0)) + 1
        tavan = int(self.rules.get("canli_kuyruk_gunluk_tavan", 24))
        if e["gun_deneme"] >= tavan and e.get("tavan_alarm_gun") != g:
            e["tavan_alarm_gun"] = g
            adres, coin = anahtar.split("|", 1)
            self.kayit({"olay": "kuyruk_gunluk_tavan", "adres": adres, "coin": coin, "deneme": e["gun_deneme"], "tur": e.get("tur")})
            self.tg.gonder(tg.alarm("ALARM: kapanış bugün de olmadı", f"{coin} (trader {tg.kisa(adres)}) {e.get('tur')} bugün {e['gun_deneme']} denemede tamamlanmadı (günlük tavan {tavan}).\n"
                                    "30 dk aralıkla denenmeye devam ediyor; borsayı elle kontrol edin."))

    def _belirsiz_coinler(self) -> set[tuple[str, str]]:
        """Y-2: çözülmemiş belirsiz emirlerin (adres, coin) kümesi. `orderStatus` 5 kez sorgulanamadıysa (`deneme` ≥ 5) engel kalkar: reduce-only kapanış pozisyonu aşamaz,
        sorgu kalıcı bozuksa kapanış sonsuza dek beklemesin. Eski girdilerde adres/coin yoksa niyet dosyasından okunur."""
        kume: set[tuple[str, str]] = set()
        eksik = [c for c, b in self.hesap.belirsiz.items() if int(b.get("deneme", 0)) < 5 and not (b.get("adres") and b.get("coin"))]
        niyetler = {x["cloid"]: x for x in self.niyet.satirlar() if x.get("t") == "niyet"} if eksik else {}
        for c, b in self.hesap.belirsiz.items():
            if int(b.get("deneme", 0)) >= 5:
                continue
            n = b if (b.get("adres") and b.get("coin")) else niyetler.get(c) or {}
            if n.get("adres") and n.get("coin"):
                kume.add((str(n["adres"]), str(n["coin"])))
        return kume

    def _kuyruk_isle(self, simdi: int) -> None:
        """Dakikalık: kısmi kalan azaltma/kapanışları yeniden dener; eksik olanlar için alarm; DUR beklemesi bitince motoru durdurur.
        S-8: her girdi `sonraki_ms`e kadar beklenir (üstel geri çekilme, `_kuyruk_geri_cekil`): kilit altında her dakika ağ/emir beklemesi olmaz."""
        toz = float(self.rules["canli_kapanis_toz_usd"])
        bekleyen = self._belirsiz_coinler()
        for anahtar, e in list(self.kapanis_kuyrugu.items()):
            if simdi < int(e.get("sonraki_ms", 0)):
                continue
            adres, coin = anahtar.split("|", 1)
            if (adres, coin) in bekleyen:                    # Y-2: bu coinde sonucu belirsiz emir var → önce `belirsiz_coz` (deneme sayılmaz, geri çekilme yok)
                continue
            mk = self._mark_kapanis(adres, coin)
            if e["tur"] == "kapat":
                ok, _ = self._kapat_coin(adres, coin, str(e.get("neden", "kuyruk")), simdi, None, baslangic=0)
                if not ok and anahtar in self.kapanis_kuyrugu:
                    self.kapanis_kuyrugu[anahtar]["deneme"] = int(self.kapanis_kuyrugu[anahtar].get("deneme", 0)) + 1
                    self._kuyruk_geri_cekil(anahtar, simdi)
            else:
                yerel = self.hesap.sz(adres, coin)
                fark = yerel - float(e["hedef_sz"])
                if abs(yerel) < EPS or fark * yerel <= 0 or abs(fark) * (mk or 0.0) <= toz:
                    self.kapanis_kuyrugu.pop(anahtar, None)
                    continue
                yon = "A" if yerel > 0 else "B"
                fake = Olay("", adres, adres, simdi, simdi, "kapat", False, "", coin, mk, abs(fark), yon, None)
                s = self._yurut(fake, adres, "azalt", yon, abs(fark) * mk * 1.001, True, abs(yerel), str(e.get("neden", "kuyruk")), False, simdi, bant=float(self.rules["canli_kapanis_bantlari"][0]),
                                kimlik=f"azalt:{adres}:{coin}:{self.saat_ms()}")
                if s.neden in ("min_nosyonel", "sz_sifir"):      # kalan küçük kısmi azaltma: HL reddeder / lot altı (0 lot) emir verilemez; bırak (O-5)
                    self.kapanis_kuyrugu.pop(anahtar, None)
                    continue
                fark2 = self.hesap.sz(adres, coin) - float(e["hedef_sz"])
                if fark2 * yerel <= 0 or abs(fark2) * (mk or 0.0) <= toz:                 # hedefe ulaşıldı
                    self.kapanis_kuyrugu.pop(anahtar, None)
                    continue
                e["deneme"] = int(e.get("deneme", 0)) + 1
                if e["deneme"] >= len(self.rules["canli_kapanis_bantlari"]):
                    self._eksik_ekle(adres, coin, "azalt", float(e["hedef_sz"]), str(e.get("neden", "")), simdi, deneme=e["deneme"])
                self._kuyruk_geri_cekil(anahtar, simdi)
        eksik = [k for k, v in self.kapanis_kuyrugu.items() if v.get("eksik")]
        self.risk.bayrak("kapanis_eksik", bool(eksik))
        if eksik and self._aralik_mi("kapanis_alarm", simdi, 60):
            self.tg.gonder(tg.alarm("ALARM: pozisyonlar hâlâ kapanmadı", f"kapanış eksik: {len(eksik)} pozisyon ({', '.join(k.split('|')[1] + ' ' + tg.kisa(k.split('|')[0]) for k in eksik[:5])}).\nYeniden deneniyor."))
        self._dur_bitir_mi()

    def _borsa_fazla(self, simdi: int) -> dict[str, float] | None:
        """G-2: gerçek kipte borsada (clearinghouseState, tüm dex) defterin KARŞILAMADIĞI pay: coin → işaretli sz (= `_kirp(hl, hl − defter toplamı)`; toz üstü).
        Defterde hiç olmayan coin (ör. elle açılmış ETH) tamamıyla buraya düşer. Okuma hatası → None (düz SAYILMAZ)."""
        try:
            hl = clearinghouse_pozisyonlari(self.post_hizli, os.environ.get("HL_HESAP_ADRESI", ""), self._dexler())
        except Exception as hata:                          # noqa: BLE001
            self.kayit({"olay": "borsa_yetim_okuma_hata", "tur": type(hata).__name__})
            return None
        if any(abs(v) > EPS and not self.mark(c) for c, v in hl.items()):
            self.mids_uygula(self.mids_al(), simdi)
        toz = float(self.rules["canli_kapanis_toz_usd"])
        fazla: dict[str, float] = {}
        for coin, v in hl.items():
            f = self._kirp(v, v - sum(c[coin].sz for c in self.hesap.poz.values() if coin in c))
            mk = self.mark(coin)
            if abs(f) > EPS and (not mk or abs(f) * mk > toz):
                fazla[coin] = f
        return fazla

    def _borsa_yetim_kapat(self, neden: str, simdi: int, coinler: set[str] | None = None) -> dict[str, float] | None:
        """G-2: DUR / `/kapat` için borsadaki defter dışı payı reduce-only IOC ile kapatır (bant merdiveni; her turdan sonra borsa yeniden okunur). Yerel deftere dokunmaz
        (defterde olmayan pozisyon). Döner: kalan fazla ({} = borsa düz) ya da None (borsa okunamadı). `coinler` verilirse (Denetim-5 yetim süre kapatması) yalnız o coinler kapatılır/döner."""
        bantlar = [float(x) for x in self.rules["canli_kapanis_bantlari"]]
        fazla: dict[str, float] | None = None
        belirsiz: set[str] = set()                         # Y-2: yanıtı belirsiz kalan coine bu çağrıda ikinci emir yok (sonraki dakika borsa yeniden okunur)
        for i in range(len(bantlar) + 1):
            fazla = self._borsa_fazla(simdi)
            if fazla and coinler is not None:
                fazla = {c: v for c, v in fazla.items() if c in coinler}
            if not fazla or i >= len(bantlar):
                break
            for coin, sz in fazla.items():
                if coin in belirsiz:
                    continue
                mk = self.mark(coin)
                if not mk:
                    self.kayit({"olay": "borsa_yetim_mark_yok", "coin": coin, "sz": sz})
                    continue
                yon = "A" if sz > 0 else "B"
                cloid = cloid_uret(f"yetim:{coin}:{self.saat_ms()}:{i}:{neden[:12]}", "kapat")
                try:
                    d = self.yurutucu.emir(coin, yon, abs(sz) * mk * 1.05, True, abs(sz), bant=bantlar[i], cloid=cloid)
                except Exception as hata:                  # noqa: BLE001 - bir coinin hatası diğerlerini durdurmaz; sonraki tur / dakika yeniden dener
                    self.kayit({"olay": "borsa_yetim_emir_hata", "coin": coin, "tur": type(hata).__name__})
                    continue
                self.kayit({"olay": "borsa_yetim_kapat", "coin": coin, "sz_istenen": sz, "yon": yon, "durum": d.durum, "sz": d.sz, "px": d.px, "ucret": d.ucret, "red_neden": d.neden,
                            "bant": bantlar[i], "cloid": cloid, "neden": neden})
                if d.durum == "belirsiz":
                    belirsiz.add(coin)
        if fazla:
            self.kayit({"olay": "borsa_yetim_kaldi", "fazla": fazla, "neden": neden})
        return fazla

    def _dur_bitir_mi(self) -> None:
        if self.dur_bekliyor and not self.kapanis_kuyrugu and not any(self.hesap.poz.values()):
            if self.kip == "gercek":                       # G-2: "tümü kapandı" yalnız BORSA düzken (defter dışı pozisyon dahil)
                fazla = self._borsa_yetim_kapat("dur_bekliyor", self.saat_ms())
                if fazla != {}:
                    if self._aralik_mi("borsa_yetim_alarm", self.saat_ms(), 60):
                        self.tg.gonder(tg.alarm("ALARM: borsa düzleşmedi", "Defter boş ama borsada açık pozisyon var: "
                                                + (", ".join(f"{c} {v:g}" for c, v in list(fazla.items())[:5]) if fazla else "borsa okunamadı") + ".\nYeniden deneniyor; motor henüz durmadı."))
                    return
            self.dur_bekliyor = False
            self.dur_istendi = True
            self._dur_yaz_atomik(self.risk.dur_neden or "dur", self.saat_ms(), False)
            self.kayit({"olay": "dur_tamam"})
            self._bot_durdu_bildir(self.risk.dur_neden or "dur", 0)
            self.durum_yaz()

    # ------------------------------------------------------------------ saha kararlarının uygulanması
    def karar_uygula(self, kararlar: list[Karar], simdi: int) -> None:
        for k in kararlar:
            if k.tur == "giris":
                self._kor_imza.pop(k.adres, None)
                self._kozmetik("slot_net_guncelle", self._slot_net_guncelle, k.adres)           # pano (14.11): eski slot kaydı (yeniden giriş) son netini alır
                self.hesap.slot_ac(k.adres, self.saha.slot)
                self._kozmetik("donem_slot_giris", self.donem_slot_giris, k.adres, k.neden, simdi)
                self.trader_pozlari_oku(k.adres)
                self.trader_son_islem_oku(k.adres, simdi)
                self.trader_hesap_usd(k.adres, simdi, zorla=True)
                giris_hesap = (self.hesap_tr.get(k.adres) or {}).get("deger")
                if giris_hesap is not None and k.adres in self.saha.uyeler:        # pano §C1: trader hesap değeri GİRİŞTE bir kez saklanır (canlı kopya koruması = bizim slot getirimiz ↔ trader'ın hesap getirisi)
                    self.saha.uyeler[k.adres]["hesap_giris_usd"] = float(giris_hesap)
                self.kayit({"olay": "saha_giris", "adres": k.adres, "neden": k.neden, "yerine": k.yerine, "slot_usd": self.saha.slot})
                self.tg.gonder(tg.msg_saha("giriş", k.adres, k.neden + (f" (yerine {tg.kisa(k.yerine)})" if k.yerine else "")), tur="saha_giris")      # panoda; Telegram'a gitmez (tg.BASTIRILAN_TURLER)
            elif k.tur == "dus":
                self.kayit({"olay": "saha_dus", "adres": k.adres, "neden": k.neden, "sonuc": k.sonuc})
                self._kozmetik("donem_slot_cikis", self.donem_slot_cikis, k.adres, k.neden, k.sonuc, simdi)       # kozmetik: istisnası sonraki kararları (inen_kapat) atlatmaz (2. denetim O-2)
                self.tg.gonder(tg.msg_saha("çıkış", k.adres, f"{k.neden}{' (sonuçla, 14 gün bekleme)' if k.sonuc else ' (sonuç dışı)'}"), tur="saha_cikis")
            elif k.tur == "inen_kapat":
                self._adres_kapat(k.adres, "inen_24sa" if not k.neden.startswith("inen_") else k.neden, simdi)
                self._kozmetik("slot_net_guncelle", self._slot_net_guncelle, k.adres)           # pano (14.11): slot silinmeden son net
                self.hesap.slot_kapat(k.adres)
            elif k.tur == "uyari":                                               # haftalık kadro (16.11): hafta içi form/radar uyarısı; çıkış YOK
                self.kayit({"olay": "saha_uyari", "adres": k.adres, "neden": k.neden})
                self.tg.gonder(tg.msg_saha("uyarı", k.adres, k.neden), tur="saha_uyari")
            elif k.tur == "hafta_degisimi":
                self.ogrenme.hafta_degisti()                                     # ortak öğrenme: "emekli" kayıtları haftalık kadro değişiminde biter
                self.kayit({"olay": "hafta_degisimi", "hafta": k.neden, "saha": list(self.saha.uyeler), "inen": list(self.saha.inen)})
                self.tg.gonder(f"🔄 Haftalık kadro değişti\nSahada {len(self.saha.uyeler)} trader var" + (f"; {len(self.saha.inen)} trader yedeğe indi, pozisyonları kapanana kadar izleniyor." if self.saha.inen else ".") + f"\n{tg.SENDEN_YOK}")
            elif k.tur == "giris_atlandi":
                imza = (self.saha.son_kosu_ms, tuple(sorted(k.saha if k.saha is not None else (k.kor_kirpildi or []))))
                if self._kor_imza.get(k.adres) != imza:                          # B11: imza = (kadro koşusu, adayın karşılaştığı TAM saha); değiştirmede üye başına değişen `kalan` imzaya girmez → aynı durum bir kez yazılır
                    self._kor_imza[k.adres] = imza
                    self.kor_kirpildi.append({"adres": k.adres, "uyeler": k.kor_kirpildi})
                    self.kayit({"olay": "kor_kirpildi", "adres": k.adres, "uyeler": k.kor_kirpildi})

    def _adres_kapat(self, adres: str, neden: str, simdi: int) -> int:
        """Adresin tüm açık kopya pozisyonlarını reduce‑only, teyitli kapatır (yeniden deneme merdiveni). Döner: TEYİTLİ kapanan coin sayısı."""
        sayi = 0
        for coin in list(self.hesap.poz.get(adres, {})):
            ok, _ = self._kapat_coin(adres, coin, neden, simdi)
            sayi += 1 if ok else 0
        return sayi

    def _dur_yaz_atomik(self, neden: str, ms: int, kapanis_bekliyor: bool) -> bool:
        """`durum/DUR`: geçici dosya + fsync + os.replace. Hata sessiz geçilmez: kayıt olayı + Telegram alarmı."""
        try:
            self.dur_dosyasi.parent.mkdir(parents=True, exist_ok=True)
            gecici = self.dur_dosyasi.with_name(self.dur_dosyasi.name + ".tmp")
            with open(gecici, "w", encoding="utf-8") as f:
                f.write(json.dumps({"neden": neden, "ms": ms, "kapanis_bekliyor": kapanis_bekliyor}) + "\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(gecici, self.dur_dosyasi)
            try:                                                   # D-6: dizin fsync (elektrik kesintisinde yeniden adlandırma kaybolup `risk.json`da dur_dosya=True kalırsa açılış "operatör sildi" sayardı)
                dfd = os.open(self.dur_dosyasi.parent, os.O_RDONLY)
                try:
                    os.fsync(dfd)
                finally:
                    os.close(dfd)
            except OSError:                                        # dizin fsync desteklenmeyen dosya sistemi: dosya fsync'i yapıldı
                pass
            return True
        except OSError as hata:
            self.kayit({"olay": "dur_yazim_hata", "neden": neden, "tur": type(hata).__name__})
            self.tg.gonder(tg.alarm("Durdurma kilidi yazılamadı", f"Durdurma kilidi diske yazılamadı ({type(hata).__name__}); risk kaydında durdurma açık, yeni işlem yok.", "🚨", senden="Bana haber ver, ben bakarım."))
            return False

    def _borsa_acik_mi(self) -> bool | None:
        """Y-1: kendi HL hesabımızda (tüm perp dex) açık pozisyon var mı. Okunamazsa None (çağıran güvenli tarafı seçer: kapanış modu)."""
        try:
            hl = clearinghouse_pozisyonlari(self.post_hizli, os.environ.get("HL_HESAP_ADRESI", ""), self._dexler())
        except Exception as hata:                          # noqa: BLE001
            self.kayit({"olay": "borsa_yetim_okuma_hata", "tur": type(hata).__name__})
            return None
        return any(abs(v) > EPS for v in hl.values())

    def _dur_kapanis_kuyrukla(self, neden: str, borsa_acik: bool | None, simdi: int) -> None:
        """Y-1: DUR yarım kalmış (süreç kapanışlar bitmeden öldü). Defterdeki TÜM açık pozisyonlar hemen denenecek şekilde kapanış kuyruğuna alınır (`sonraki_ms` 0: ilk dakikalık
        adımda reduce-only kapanış emri); defter dışı borsa pozisyonu defter boşalınca `_dur_bitir_mi` (G-2) ile kapatılır. Kayıt `dur_yeniden_kapanis` + Telegram alarmı."""
        sayi = 0
        for adres, coinler in self.hesap.poz.items():
            for coin in coinler:
                self._eksik_ekle(adres, coin, "kapat", 0.0, f"dur:{neden}", simdi, deneme=0)
                sayi += 1
        for e in self.kapanis_kuyrugu.values():
            e.pop("sonraki_ms", None)                       # eski geri çekilme beklemesi (≤ 30 dk) DUR'da uygulanmaz
        self.kayit({"olay": "dur_yeniden_kapanis", "neden": neden, "kuyruk": len(self.kapanis_kuyrugu), "yerel_poz": sayi, "borsa_acik": borsa_acik})
        ek = "; borsada defter dışı açık pozisyon var" if borsa_acik else ("; borsa okunamadı (düz teyidi yok)" if borsa_acik is None and not sayi else "")
        self.tg.gonder(tg.alarm(f"DUR yarım kalmıştı: {tg.sade_ad(neden)}", f"Motor yeniden başladı; {sayi} açık pozisyon kapanış kuyruğuna alındı{ek}.\nYeni pozisyon açılmıyor; hepsi kapanınca motor durur.", "🛑"))

    def dur_tetikle(self, neden: str) -> None:
        """Tüm pozisyonları reduce‑only kapat (teyitli), `DUR` yaz, alarm. Motor ancak TÜM pozisyonlar teyitli 0 olunca durur; düzleşmeyen varsa `kapanis_kuyrugu` dakikalık yeniden dener
        ve yeni açılış yapılmaz (`risk.dur`). Elle silinmeden yeniden açılmaz."""
        simdi = self.saat_ms()
        self.risk.dur_ver(neden)
        self.dur_bekliyor = True
        if self._dur_yaz_atomik(neden, simdi, True):                                            # DUR dosyası kapanışlardan ÖNCE (kapanış istisnası DUR'u etkilemesin)
            self.risk.dur_dosya = True                                                          # Denetim-3: dosya yazıldı (operatör silerse bu "elle devam"; yazılmadıysa `_dur_kurtar` yeniden dener)
        kapatilan = 0
        for a in list(self.hesap.poz):
            try:
                kapatilan += self._adres_kapat(a, f"dur:{neden}", simdi)
            except Exception as hata:                                                           # noqa: BLE001 - kapanış hatası DUR'u bozmaz; kalan pozisyon dakikalık yeniden denenir
                self.kayit({"olay": "dur_kapanis_hata", "adres": a, "tur": type(hata).__name__})
        kalan = sum(len(c) for c in self.hesap.poz.values())
        fazla: dict[str, float] | None = {}
        if self.kip == "gercek":                                                                # G-2: defterde OLMAYAN borsa pozisyonları da kapatılır; "kapandı" yalnız borsa düzken
            try:
                fazla = self._borsa_yetim_kapat(f"dur:{neden}", simdi)
            except Exception as hata:                                                           # noqa: BLE001
                self.kayit({"olay": "dur_kapanis_hata", "adres": "borsa", "tur": type(hata).__name__})
                fazla = None
        duz = kalan == 0 and fazla == {}
        if duz and self.kip == "gercek":
            try:
                self.borsa_stop_esitle(self.acik_emir_oku(), simdi)                              # K-64: pozisyon kalmadı → borsa stopları iptal
            except Exception as hata:                                                           # noqa: BLE001
                self.kayit({"olay": "borsa_stop_hata", "hatalar": [{"islem": "dur_iptal", "tur": type(hata).__name__}]})
        if duz:
            self._dur_yaz_atomik(neden, simdi, False)
        self.kayit({"olay": "dur", "neden": neden, "kapatilan": kapatilan, "kalan": kalan, "borsa_fazla": fazla})
        if duz:
            self._bot_durdu_bildir(neden, 0, kapatilan)
            self._dur_bitir_mi()
        else:
            ek = "" if fazla == {} else (f"; borsada defter dışı açık: {', '.join(f'{c} {v:g}' for c, v in list(fazla.items())[:5])}" if fazla else "; borsa okunamadı (düz teyidi yok)")
            self._bot_durdu_bildir(neden, int(kalan) + (len(fazla) if fazla else 0), kapatilan, ek)
        self.durum_yaz()

    def _stop_durumu(self, acik: int, calisiyor: bool = True) -> str:
        """Bot durdu mesajı için stop durumu (sade): açık pozisyon yoksa 'gerekmiyor'; gerçek kipte borsa stopları / stopsuz coin sayısı; sanal kipte yazılım stopu (bot kapalıyken çalışmaz)."""
        if acik <= 0:
            return "gerekmiyor (pozisyon yok)"
        if self.kip == "gercek":
            sayi = len(getattr(self.borsa_stop, "korumasiz", {}) or {})
            return "borsada duruyor" if sayi == 0 else f"{sayi} coinde borsa stopu eksik"
        return "yazılım stopu aktif" if calisiyor else "bot kapalıyken yazılım stopu çalışmıyor"

    def _bot_durdu_bildir(self, neden: str, acik: int, kapatilan: int | None = None, ek: str = "", calisiyor: bool = True, son: str | None = None, senden: str | None = None) -> None:
        """Ayrı 🔴 'Bot durdu' mesajı: sesli, 6 saat tekrar sınırına takılmaz (doğrudan `gonder`); kalıcı işaret `durum/tg_bot_durdu` → bot yeniden çalışınca tek 'Düzeldi' (`baslat`)."""
        bot_durdu_gonder(self.tg, self.dur_dosyasi.parent, neden, acik, self._stop_durumu(acik, calisiyor), ek, son, senden)

    def kesinti_duzeldi_bildir(self, once: dict[str, int]) -> None:
        """Açılış yetişmesinden (`kacanlari_tamamla`) SONRA: bot durmuşsa TEK Düzeldi (kesinti süresi + o sürede olanlar). `once`: yetişmeden önceki `_say_gun`. Kesintide kaçan işlem varsa mesaj SESLİ."""
        k, self._kesinti = self._kesinti, None
        if not k:
            return
        fark = {x: self._say_gun.get(x, 0) - once.get(x, 0) for x in ("ac", "artir", "azalt", "kapat")}
        top = sum(fark.values())
        metin = tg.msg_duzeldi_kesinti(round(k["sn"] / 60), fark["ac"], fark["kapat"], top - fark["ac"] - fark["kapat"])
        self.tg.gonder(metin, "CRIT" if top else "INFO")

    def acik_poz_sayisi(self) -> int:
        return sum(len(c) for c in self.hesap.poz.values())

    # ------------------------------------------------------------------ periyodik görevler
    def mids_al(self) -> dict[str, float] | None:
        """Ana dex + her HIP‑3 dex `allMids` (ağ; kilitsiz çağrılır). Hata: None (önceki markalar kalır, `mark_eski` mutabakatı yakalar)."""
        sonuc: dict[str, float] = {}
        try:
            for dex in ["", *self._dexler()]:
                mids = self.post({"type": "allMids", **({"dex": dex} if dex else {})})
                for coin, v in mids.items():
                    try:
                        x = float(v)
                    except (TypeError, ValueError):
                        continue
                    if math.isfinite(x) and x > 0:                  # Denetim-8 (D3): inf/NaN mark yok sayılır
                        sonuc[coin] = x
            return sonuc
        except Exception as hata:                          # noqa: BLE001
            self.kayit({"olay": "mark_okuma_hata", "tur": type(hata).__name__})
            return sonuc or None

    def mids_uygula(self, mids: dict[str, float] | None, simdi: int) -> None:
        for coin, x in (mids or {}).items():
            self.marks[coin], self.mark_ms[coin] = x, simdi

    def piyasa_oku(self, simdi: int) -> None:
        self.mids_uygula(self.mids_al(), simdi)

    def maks_kaldirac_tablosu(self) -> tuple[dict[str, float], list[str]]:
        """HL `meta` evreni (ana dex + HIP‑3 dex'leri) → {coin: azami kaldıraç}; HIP‑3 adları `dex:COIN`. Döner (tablo, hata_dex). Ağ, kilitsiz; hata istisna atmaz."""
        okunan: dict[str, float] = {}
        hata_dex: list[str] = []
        try:
            dexler = ["", *[x for x in self._dexler() if x]]
        except Exception as hata:                          # noqa: BLE001 - dex listesi yoksa yalnız ana dex
            dexler, hata_dex = [""], [f"dex_listesi:{type(hata).__name__}"]
        for dex in dexler:
            try:
                meta = self.post({"type": "meta", "dex": dex} if dex else {"type": "meta"}) or {}
                for u in meta.get("universe") or []:
                    ad, ml = u.get("name"), u.get("maxLeverage")
                    if ad and ml and not u.get("isDelisted"):
                        okunan[str(ad) if not dex or ":" in str(ad) else f"{dex}:{ad}"] = float(ml)
            except Exception as hata:                      # noqa: BLE001 - tasfiye 20x yedeğiyle sürer
                hata_dex.append(f"{dex or 'ana'}:{type(hata).__name__}")
        return okunan, hata_dex

    def kaldirac_yetersiz(self, coin: str) -> str | None:
        """Denetim-4a (kullanıcı kararı 17.11, K-67): GERÇEK kipte HL azami kaldıracı `canli_min_azami_kaldirac`ten küçük coinde AÇILIŞ/artırma yok (izole 3x'te azami 3 olan coin −%20'de tasfiye olur;
        stoplar %20/%22). Döner: None (serbest) | "kaldirac_dusuk" | "kaldirac_bilinmiyor" (tablo okunamadı / coin yok: güvenli taraf, açılış yok; kapanış serbest). Sanal kip ve eşik ≤ 0: süzgeç yok."""
        esik = float(self.rules.get("canli_min_azami_kaldirac", 0) or 0)
        if self.kip != "gercek" or esik <= 0:
            return None
        ml = self._hl_maks_kaldirac.get(coin)
        if ml is None:
            return "kaldirac_bilinmiyor"
        return "kaldirac_dusuk" if ml < esik - 1e-9 else None

    def maks_kaldirac_oku(self) -> int:
        """S-7 (sanal tasfiye): HL `meta` evreni (ana dex + HIP‑3 dex'leri) → coin başına `maxLeverage` → `hesap.maks_kaldirac` (açılışta bir kez; ağ, kilitsiz).
        HIP‑3 adları `dex:COIN` biçimindedir (önek yoksa eklenir). Okunamazsa eski değerler kalır, bilinmeyen coin için `tasfiye_fiyati` 20x varsayar (kayıt: `maks_kaldirac_okunamadi`). Döner: okunan coin sayısı."""
        okunan, hata_dex = self.maks_kaldirac_tablosu()
        self.hesap.maks_kaldirac.update(okunan)
        if hata_dex or not okunan:
            self.kayit({"olay": "maks_kaldirac_okunamadi", "hata": hata_dex, "okunan": len(okunan), "yedek_kaldirac": 20})
        return len(okunan)

    def kaldirac_tablosu_uygula(self, tablo: dict[str, float] | None) -> None:
        if tablo:
            self._hl_maks_kaldirac.update(tablo)

    def senkron_oku(self) -> dict[str, dict[str, float]]:
        """Saha + inen adreslerin gerçek açık pozisyonları (REST; kilitsiz). Okunamayan adres atlanır."""
        sonuc: dict[str, dict[str, float]] = {}
        self._senkron_okuma_ms = self.saat_ms()
        for adres in [*self.saha.uyeler, *self.saha.inen]:
            try:
                sonuc[adres] = clearinghouse_pozisyonlari(self.post, adres, self._dexler())
            except Exception as hata:                      # noqa: BLE001
                self.kayit({"olay": "poz_okuma_hata", "adres": adres, "tur": type(hata).__name__})
        return sonuc

    def senkron_uygula(self, okunan: dict[str, dict[str, float]]) -> int:
        """Trader pozisyon izleyicisini REST gerçeğine eşitler (WS kaçırması / kayma düzeltme); fark `poz_senkron` olarak kaydedilir. Okumadan SONRA bir dolum işlenen coin atlanır (eski okuma yeni olayı ezmesin).
        K‑37 §5: bizde pozisyon olup trader'ın REST pozisyonu 0 ise (60 dk penceresinden eski kapanış kaçmış) teyitli kapatılır. Döner: düzeltilen adres sayısı."""
        duzeltilen = 0
        simdi = self.saat_ms()
        for adres, gercek in okunan.items():
            izlenen = self.poz_tr.get(adres, {})
            yeni_olay = {c for (a, c), ms in self._son_olay_coin.items() if a == adres and ms > self._senkron_okuma_ms}
            gercek = {**{c: v for c, v in gercek.items() if c not in yeni_olay}, **{c: izlenen[c] for c in yeni_olay if c in izlenen}}
            spot = {c for c in {*izlenen, *gercek, *self.hesap.poz.get(adres, {})} if coin_sinifi(c) == "spot"}      # S-9: REST (clearinghouseState) spot bakiyesi okumaz → spot coin senkronda görünmez; izlenen değer korunur, kapanış/fark yok
            gercek = {**{c: v for c, v in gercek.items() if c not in spot}, **{c: izlenen[c] for c in spot if c in izlenen}}
            fark = {c: (izlenen.get(c, 0.0), gercek.get(c, 0.0)) for c in {*izlenen, *gercek} if abs(izlenen.get(c, 0.0) - gercek.get(c, 0.0)) > 1e-9 * max(1.0, abs(gercek.get(c, 0.0)))}
            if fark:
                self.kayit({"olay": "poz_senkron", "adres": adres, "fark": {c: list(v) for c, v in list(fark.items())[:10]}})
                duzeltilen += 1
            self.poz_tr[adres] = dict(gercek)
            self._poz_tr_senk_isaretle(adres, self._senkron_okuma_ms)          # G-14: okumadan eski snapshot dolumu bu değeri artık ezemez
            for coin in list(self.hesap.poz.get(adres, {})):
                if coin in yeni_olay or coin in spot:
                    continue
                g, i = gercek.get(coin, 0.0), izlenen.get(coin, 0.0)
                if abs(g) < EPS:
                    self.kayit({"olay": "senkron_kapanis", "adres": adres, "coin": coin})
                    self._kapat_coin(adres, coin, "trader_kapali_senkron", simdi)
                elif g * self.hesap.sz(adres, coin) < 0:                                    # G-3: trader ters döndü (kaçan dönüş), bizimki eski yönde → reduce-only kapat
                    self.kayit({"olay": "senkron_ters_kapanis", "adres": adres, "coin": coin, "trader": g, "biz": self.hesap.sz(adres, coin)})
                    self._kapat_coin(adres, coin, "trader_ters_senkron", simdi)
                elif g * i > 0 and abs(g) < abs(i) - 1e-9 * max(1.0, abs(g)) and g * self.hesap.sz(adres, coin) > 0:
                    self._senkron_azalt(adres, coin, i, g, simdi)                       # S-1: kaçan kısmi azaltma (trader küçüldü, izlenen büyük kaldı)
        return duzeltilen

    # ------------------------------------------------------------------ K-75: kaçan açılış telafisi (yalnız sanal)
    def _telafi_log_yaz(self, adres: str, coin: str, neden: str, **ek: Any) -> None:
        """Telafi atlama nedeni değişince bir kez kaydedilir (her 10 dk'lık senkronda aynı satır tekrarlanmaz)."""
        anahtar = f"{adres}|{coin}"
        if self._telafi_log.get(anahtar) != neden:
            self._telafi_log[anahtar] = neden
            self.kayit({"olay": "kacan_telafi_atlandi", "adres": adres, "coin": coin, "neden": neden, **ek})

    def _telafi_dolumlar(self, adres: str, simdi: int, pencere_ms: int, ttl_ms: int, taze_zorla: bool) -> tuple[list[dict], bool]:
        """Trader dolum geçmişi: TTL içindeki önbellek (REST yok) ya da yeni okuma. Döner (dolumlar, rest_okundu_mu)."""
        c = self._telafi_dolum.get(adres)
        if c is not None and not taze_zorla and simdi - c[0] < ttl_ms:
            return c[1], False
        dolumlar = rest_dolumlar(self.post_hizli, adres, simdi - pencere_ms, simdi)
        self._telafi_dolum[adres] = (simdi, dolumlar)
        return dolumlar, True

    @staticmethod
    def _dolumdan_acilis(dolumlar: list[dict], coin: str, simdi: int, pencere_ms: int) -> tuple[int | None, bool]:
        acilis: int | None = None
        for f in sorted((x for x in dolumlar if str(x.get("coin", "")) == coin and int(x["time"]) >= simdi - pencere_ms), key=lambda x: int(x["time"])):
            bas = f.get("startPosition")
            if bas is None:
                return None, False
            bas, sz = float(bas), float(f["sz"])
            son = bas + (sz if str(f.get("side")) == "B" else -sz)
            if abs(bas) < 1e-9 or bas * son < 0:
                acilis = int(f["time"])
        return acilis, True

    def _trader_poz_acilis_ms(self, adres: str, coin: str, simdi: int, pencere_ms: int) -> tuple[int | None, bool, bool]:
        """Trader'ın coindeki ŞU ANKİ pozisyonunun açılış anı (son sıfırdan açılış / yön değişimi dolumu), son `pencere_ms` içinde. Döner (ms | None, bilinen_mi, rest_okundu_mu).
        bilinen=False: dolumlarda `startPosition` yok (yaş bilinmiyor). Pencerede o coinde açılış dolumu yoksa (None, True): pozisyon pencereden eski. Dolumlar adres başına TTL'li önbellekten gelir;
        önbellekten açılış bulunamazsa (pozisyon yeni açılmış olabilir) bir kez taze okunur. Okuma hatası istisna olarak yükselir."""
        ttl = int(float(self.rules.get("kacan_telafi_dolum_ttl_dk", 30)) * 60_000)
        dolumlar, okundu = self._telafi_dolumlar(adres, simdi, pencere_ms, ttl, False)
        acilis, bilinen = self._dolumdan_acilis(dolumlar, coin, simdi, pencere_ms)
        if not okundu and bilinen and acilis is None:
            dolumlar, okundu = self._telafi_dolumlar(adres, simdi, pencere_ms, ttl, True)
            acilis, bilinen = self._dolumdan_acilis(dolumlar, coin, simdi, pencere_ms)
        return acilis, bilinen, okundu

    def _telafi_hiz_siniri_soguma(self) -> bool:
        """Paylaşılan REST sınırlayıcısında (`GuvenliLimiter`) 429 soğuması sürüyorsa telafi okuması en düşük öncelikli: hiç denemez."""
        lim = getattr(getattr(self.post, "istemci", None), "limiter", None)
        f = getattr(lim, "soguma_kalan", None)
        try:
            return bool(f and f() > 0)
        except Exception:                                  # noqa: BLE001
            return False

    def _telafi_geri_cekil(self, adres: str, asama: str, simdi: int) -> None:
        """429: yalnız telafi durur (`kacan_telafi_geri_cekil_sn`, ardışık 429'da ikiye katlanır, tavan 1 sa); backoff başına TEK olay."""
        taban = float(self.rules.get("kacan_telafi_geri_cekil_sn", 300))
        self._telafi_ardisik_429 += 1
        sn = min(taban * 2 ** (self._telafi_ardisik_429 - 1), 3600.0)
        self._telafi_geri_bit_ms = simdi + int(sn * 1000)
        self.kayit({"olay": "kacan_telafi_geri_cekil", "adres": adres, "asama": asama, "sn": sn, "ardisik": self._telafi_ardisik_429})

    def kacan_telafi(self, simdi: int) -> int:
        """K-75 (kullanıcı kararı 20.11; YALNIZ sanal kip, bayrak `sanal_kacan_acilis_telafi`): saha traderının açık pozisyonunu biz tutmuyorsak (aynı coin; bizde sıfır) ve açılış kaçmışsa (yeniden başlatma, `gec_acilis`,
        60 dk pencere dışı) AYNI açılış yolundan (`_emir_isle`: tüm filtre/tavan/ders/ML kuralları geçerli; boyut hedef tabanlı) açar. Koşullar: (1) güncel mark, trader giriş fiyatına göre bizim aleyhimize
        en çok `kacan_telafi_kayma` (long: mark/giriş−1, short: 1−mark/giriş; lehimize sınırsız); (2) trader pozisyon yaşı ≤ `kacan_telafi_max_saat` (dolumlardan; okunamazsa atlanır, `startPosition` yoksa bilinmiyor = serbest);
        (3) son açılış atlama nedeni (`son_atla`) `TELAFI_YENIDEN_DENE` dışındaysa (filtre/kural: rejim, haber, slot_tavani, ...) SAYGI gösterilir, açılmaz (pozisyon açılışından önceki eski atlama yok sayılır). Kayıt: emir `boyut_neden`
        "kacan_telafi" (+ `telafi_*` alanları). Senkron adımında (`dakika`; ilk dakika başlatmada hemen) çağrılır; kilit altında. Döner: verilen emir sayısı."""
        r = self.rules
        if self.kip != "sanal" or not r.get("sanal_kacan_acilis_telafi", False):
            return 0
        ust = float(r.get("kacan_telafi_kayma", 0.01))
        pencere = int(float(r.get("kacan_telafi_max_saat", 24)) * 3_600_000)
        taze = float(r["canli_olay_stale_sn"]) * 1000
        if simdi < self._telafi_geri_bit_ms or self._telafi_hiz_siniri_soguma():           # 429 geri çekilmesi / paylaşılan soğuma: telafi bu senkronda hiç REST okumaz
            return 0
        butce = int(r.get("kacan_telafi_okuma_max", 3))                                      # senkron başına yaş/dolum REST okuma bütçesi; kalan adaylar sonraki senkrona
        okuma = 0
        sayi = 0
        for anahtar in list(self._telafi_yas):
            a_, c_ = anahtar.split("|", 1)
            if self.poz_tr.get(a_, {}).get(c_, 0.0) * self._telafi_yas[anahtar][0] <= 0:
                self._telafi_yas.pop(anahtar, None)                                              # trader pozisyonu kapandı / yön değiştirdi: yaş önbelleği geçersiz
        for adres in list(self.saha.uyeler):
            aday: list[tuple[str, float, float]] = []
            for coin, poz in list(self.poz_tr.get(adres, {}).items()):
                if abs(poz) < EPS or abs(self.hesap.sz(adres, coin)) > EPS or coin_sinifi(coin) == "spot":
                    continue
                if simdi - self._son_olay_coin.get((adres, coin), -10**15) <= taze:                  # taze dolum: normal yol (zaten karar verdi / verecek)
                    continue
                mk = self.marks.get(coin)
                if not mk:
                    continue
                aday.append((coin, poz, float(mk)))
            if not aday:
                continue
            try:
                girisler = clearinghouse_giris_pxleri(self.post_hizli, adres, self._dexler())
            except RateLimitError:
                self._telafi_geri_cekil(adres, "giris_px", simdi)
                return sayi
            except Exception as hata:                      # noqa: BLE001
                self.kayit({"olay": "kacan_telafi_hata", "adres": adres, "asama": "giris_px", "tur": type(hata).__name__})
                continue
            for coin, poz, mk in aday:
                try:
                    giris = girisler.get(coin)
                    if not giris:
                        self._telafi_log_yaz(adres, coin, "giris_px_yok")
                        continue
                    kayma = (mk / giris - 1.0) * (1.0 if poz > 0 else -1.0)                         # + = bizim aleyhimize (long daha pahalı / short daha ucuz)
                    if kayma > ust + 1e-12:
                        self._telafi_log_yaz(adres, coin, "kayma_fazla", kayma=round(kayma, 6), trader_giris=giris, mark=mk)
                        continue
                    yk = f"{adres}|{coin}"
                    isr = 1 if poz > 0 else -1
                    onb = self._telafi_yas.get(yk)
                    if onb is not None and onb[0] == isr:
                        _, acilis_ms, bilinen = onb
                    else:
                        if okuma >= butce:                 # bütçe doldu: aday sonraki senkronda (sessiz)
                            continue
                        try:
                            acilis_ms, bilinen, okundu = self._trader_poz_acilis_ms(adres, coin, simdi, pencere)
                        except RateLimitError:
                            self._telafi_geri_cekil(adres, "yas", simdi)
                            return sayi
                        except Exception as hata:          # noqa: BLE001
                            self.kayit({"olay": "kacan_telafi_hata", "adres": adres, "coin": coin, "asama": "yas", "tur": type(hata).__name__})
                            continue
                        if okundu:
                            okuma += 1
                            self._telafi_ardisik_429 = 0
                        self._telafi_yas[yk] = (isr, acilis_ms, bilinen)
                    if bilinen and acilis_ms is None:
                        self._telafi_log_yaz(adres, coin, "pozisyon_eski")
                        continue
                    son = self.son_atla.get(f"{adres}|{coin}")
                    if son and son[0] not in TELAFI_YENIDEN_DENE and (acilis_ms is None or son[1] >= acilis_ms):
                        self._telafi_log_yaz(adres, coin, "filtre_atlamisti:" + son[0])
                        continue
                    yas_sa = round((simdi - acilis_ms) / 3_600_000, 2) if acilis_ms is not None else None
                    o = Olay(f"telafi:{adres}:{coin}:{simdi}", adres[:12], adres, simdi, simdi, "telafi", False, "", coin, mk, abs(poz), "B" if poz > 0 else "A", 0.0)
                    s = self._emir_isle(o, adres, "ac", 0.0, poz, 0.0, simdi, False,
                                        telafi={"telafi_trader_giris": giris, "telafi_kayma": round(kayma, 6), "telafi_yas_sa": yas_sa})
                    self._telafi_log.pop(f"{adres}|{coin}", None)
                    self.kayit({"olay": "kacan_telafi", "adres": adres, "coin": coin, "yon": "B" if poz > 0 else "A", "trader_giris": giris, "mark": mk, "kayma": round(kayma, 6), "yas_sa": yas_sa,
                                "karar": s.karar, "neden": s.neden})
                    if s.karar == "emir":
                        sayi += 1
                except Exception as hata:                  # noqa: BLE001
                    self.kayit({"olay": "kacan_telafi_hata", "adres": adres, "coin": coin, "asama": "emir", "tur": type(hata).__name__, "mesaj": str(hata)[:160]})
        return sayi

    def _senkron_azalt(self, adres: str, coin: str, izlenen: float, gercek: float, simdi: int) -> None:
        """S-1: REST trader pozisyonu izlenenden küçük (aynı yön) → normal hedef tabanlı azaltma yolu (K‑38, `boyut.hedef_emir` `azalt`, reduce-only). Hedef zaten karşılanıyorsa emir yok."""
        mk = self.mark(coin)
        if not mk:
            self.kayit({"olay": "senkron_azalt_atlandi", "adres": adres, "coin": coin, "neden": "mark_yok"})
            return
        sahte = Olay(f"senkron:{adres}:{coin}:{simdi}", adres[:12], adres, simdi, simdi, "senkron", False, "", coin, mk, abs(izlenen - gercek), "A" if izlenen > 0 else "B", izlenen)
        biz_sz = self.hesap.sz(adres, coin)
        s = self._emir_isle(sahte, adres, "azalt", izlenen, gercek, biz_sz, simdi, True)
        self.kayit({"olay": "senkron_azalt", "adres": adres, "coin": coin, "trader_once": izlenen, "trader_sonra": gercek, "karar": s.karar, "neden": s.neden})

    def yerel_ozsermaye(self) -> float:
        return self.hesap.ozsermaye(self.marks)

    def ozsermaye(self) -> float:
        """Risk temeli (K‑37 §2). Sanal: yerel defter (funding dahil). GERÇEK: HL `accountValue` (tüm perp dex + spot USDC) − ofset (ofset = ilk okumada HL değeri − yerel özsermaye; kasa < hesap ise
        fazla bakiye riske girmez). HL değeri `3 × canli_mutabakat_sn`den eskiyse yerel değer kullanılır (mutabakat zaten alarm verir)."""
        yerel = self.yerel_ozsermaye()
        if self.kip == "gercek" and self._ofset_dogrulanmadi:
            return yerel                                       # K-1: ofset (yatırma/çekme) doğrulanmadı → risk yerel defterle (çekimden etkilenmez); yalnız açılış bayrağı `ofset` kapalı
        if self.kip == "gercek" and self.hl_oz is not None and self.hl_ofset is not None and self.saat_ms() - self.hl_oz_ms <= 3 * float(self.rules["canli_mutabakat_sn"]) * 1000:
            return self.hl_oz - self.hl_ofset
        return yerel

    def hl_oku(self, hizli: bool = False) -> tuple[dict[str, float], float] | None:
        """Gerçek kip (ağ; kilitsiz): HL pozisyonları (tüm dex) + hesap değeri (tüm perp dex + spot USDC). Okumanın BAŞLADIĞI an (`saat_ms`) değerle birlikte saklanır (`hl_oz_ms`: Denetim-8 D5 — döngü başı
        değil; aradaki mevduat/çekim ledger satırı hl_oz_ms'ten sonra ise sonraki okumaya kalır, sahte özsermaye düşüşü olmaz)."""
        adres = os.environ.get("HL_HESAP_ADRESI", "")
        bas = self.saat_ms()
        try:
            dexler = self._dexler()
            post = self.post_hizli if hizli else self.post                     # `hizli`: KİLİT ALTI okuma (`_mutabakat` yeniden okuması; O-3)
            sonuc = clearinghouse_pozisyonlari(post, adres, dexler), hesap_degeri_oku(post, adres, dexler)
        except Exception as hata:                          # noqa: BLE001
            self.kayit({"olay": "hl_okuma_hata", "tur": type(hata).__name__})
            return None
        self._hl_son_okuma = (sonuc, bas)
        return sonuc

    def _hl_okuma_ms(self, hl: tuple | None, simdi: int) -> int:
        """`hl` bu motorun son `hl_oku` sonucuysa okumanın başladığı an; değilse (dışarıdan verilen) `simdi`."""
        son = self._hl_son_okuma
        return son[1] if son is not None and hl is not None and son[0] is hl else simdi

    def hl_uygula(self, deger: float, simdi: int, okuma_ms: int | None = None) -> bool:
        """HL hesap değerini uygular. Denetim-8 (D3): NaN/inf/negatif değer UYGULANMAZ (karşılaştırmaları sessizce geçerdi): kayıt + alarm (bir kez) + AYRI `hl_deger` açılış bayrağı (mutabakat bayrağı aynı
        dakikada yeniden hesaplanıp silinirdi); geçerli değer gelince bayrak kalkar. Döner: geçerli mi. `okuma_ms` (D5): okumanın gerçek zamanı (yoksa `simdi`)."""
        try:
            d = float(deger)
        except (TypeError, ValueError):
            d = math.nan
        if not math.isfinite(d) or d < 0:
            if not self.risk.acilis_durdu.get("hl_deger"):
                self.risk.bayrak("hl_deger", True)
                self.kayit({"olay": "hl_deger_gecersiz", "deger": str(deger)[:24]})
                self.tg.uyar("hl_deger", tg.alarm("ALARM: HL hesap değeri geçersiz", "HL'den gelen hesap değeri sayı değil / negatif. Yeni pozisyon açılmıyor; değer düzelince kalkar."))
            return False
        if self.risk.acilis_durdu.get("hl_deger"):
            self.risk.bayrak("hl_deger", False)
            self.kayit({"olay": "hl_deger_duzeldi"})
            self.tg.duzeldi("hl_deger", tg.duzeldi_metni("HL hesap değeri", "Yeni pozisyonlar yeniden serbest."))
        self.hl_oz, self.hl_oz_ms = d, (simdi if okuma_ms is None else okuma_ms)
        if self.hl_ofset is None:
            self.hl_ofset = d - self.yerel_ozsermaye()
        return True

    def ledger_oku(self, simdi: int) -> list[dict] | None:
        """Gerçek kip (ağ; kilitsiz): kendi hesabımızın `userNonFundingLedgerUpdates` satırları (sayfalı), `ledger_son_ms`ten sonrası. İlk çağrıda yalnız başlangıç anı sabitlenir (ilk ofset zaten ilk HL okumasından)."""
        if self.ledger_son_ms is None:
            self.ledger_son_ms = simdi
            self._ledger_okundu = True                     # ilk kurulum: ofset zaten bu HL okumasından; doğrulanacak bir şey yok
            return None
        try:
            sonuc = ledger_sayfala(self.post, os.environ.get("HL_HESAP_ADRESI", ""), self.ledger_son_ms + 1)
        except Exception as hata:                          # noqa: BLE001
            self._ledger_okundu = False
            self.kayit({"olay": "ledger_okuma_hata", "tur": type(hata).__name__})
            return None
        self._ledger_okundu = True
        return sonuc

    # Hesap değerini (perp + spot USDC) DEĞİŞTİREN ledger türleri (2. denetim K-1 eki). Yön, satırdaki `user` (gönderen) / `destination` (alan) adresinin kendi adresimizle eşleşmesinden; eşleşme yoksa
    # sayılmaz (atlanan olarak kaydedilir, açıklanamayan fark `_hl_sicrama_denetle`ye kalır). `accountClassTransfer` (perp ↔ spot) toplam hesap değerini değiştirmez; `vault*`/`rewardsClaim` alan biçimi doğrulanmadığı için SAYILMAZ.
    LEDGER_DIS_PARA = ("deposit", "withdraw")
    LEDGER_TRANSFER = ("internalTransfer", "subAccountTransfer", "send", "spotTransfer")

    def _ledger_net(self, s: dict) -> float | None:
        """Ledger satırının HESABIMIZ üzerindeki net USDC etkisi ($; + giren / − çıkan); sayılmayan / yönü bilinmeyen / USDC olmayan satır: None."""
        d = s.get("delta") or {}
        tur = d.get("type")
        try:
            if tur in self.LEDGER_DIS_PARA:
                tutar = float(d.get("usdc") or 0.0)
                return tutar if tur == "deposit" else -tutar
            if tur in self.LEDGER_TRANSFER:
                if tur in ("send", "spotTransfer") and str(d.get("token", "USDC")).split(":")[0] != "USDC":
                    return None                                     # USDC olmayan token hesap değerine (perp + spot USDC) girmez
                tutar = float(d.get("usdc") if d.get("usdc") is not None else d.get("amount") or 0.0)
                ben = os.environ.get("HL_HESAP_ADRESI", "").strip().lower()
                gonderen, alan = str(d.get("user") or "").lower(), str(d.get("destination") or "").lower()
                if not ben or gonderen == alan:
                    return None
                if alan == ben:
                    return tutar
                if gonderen == ben:
                    return -tutar
        except (TypeError, ValueError):
            return None
        return None

    def ofset_yenile(self, satirlar: list[dict] | None, simdi: int) -> bool:
        """#5: yeni yatırma/çekme (`deposit`/`withdraw`) ve (2. denetim K-1 eki) hesap değerini değiştiren transfer satırları (`internalTransfer`/`subAccountTransfer`/`send`/`spotTransfer` USDC; yön `user`/`destination`) görülünce
        `hl_ofset += net` (net = giren − çıkan, HL hesabı $). HL − yerel FARKI KORUNUR (birikmiş gerçek funding/kayma/ücret farkı silinmez; günlük/zirve freni ve mutabakat bayrağı çalışmaya devam eder). Yalnız HL değeri okunmadan
        ÖNCE gerçekleşmiş satırlar (`zaman ≤ hl_oz_ms`) işlenir; sonrakiler bir sonraki okumaya kalır. Yönü/tutarı belirlenemeyen ya da hesap değerini değiştirmeyen türler (`accountClassTransfer`, `vault*` …) sayılmaz,
        yalnız `ofset_atlanan_tur` olarak kaydedilir (bilgi); açıklanamayan fark `_hl_sicrama_denetle`ye kalır. HL hesabında kasa ayarı kadar para tutulursa ofset 0 olur."""
        if self.kip != "gercek" or not satirlar or self.hl_oz is None or self.ledger_son_ms is None or self.hl_ofset is None:
            return False
        yeni: list[tuple[dict, float]] = []
        atlanan: dict[str, int] = {}
        for s in satirlar:
            z, tur = s.get("time"), (s.get("delta") or {}).get("type")
            if not isinstance(z, (int, float)) or not self.ledger_son_ms < z <= self.hl_oz_ms:
                continue
            net_s = self._ledger_net(s) if tur in (*self.LEDGER_DIS_PARA, *self.LEDGER_TRANSFER) else None
            if net_s is not None:
                yeni.append((s, net_s))
            else:
                atlanan[str(tur)] = atlanan.get(str(tur), 0) + 1
        if atlanan:
            self.kayit({"olay": "ofset_atlanan_tur", "turler": atlanan})
        if not yeni:
            self.ledger_son_ms = int(max([self.ledger_son_ms] + [s["time"] for s in satirlar if isinstance(s.get("time"), (int, float)) and s["time"] <= self.hl_oz_ms]))
            return False
        net = sum(n for _, n in yeni)
        eski = self.hl_ofset
        self.hl_ofset = eski + net
        self.ledger_son_ms = int(max(s["time"] for s in satirlar if isinstance(s.get("time"), (int, float)) and s["time"] <= self.hl_oz_ms))
        self.kayit({"olay": "ofset_yenilendi", "eski": eski, "yeni": self.hl_ofset, "net_usd": net, "satir": len(yeni)})
        return True

    _ofset_dogrulanmadi = False                             # K-1: ofset (yatırma/çekme kaydı) henüz doğrulanmadı → risk yerel defterle, açılış bayrağı `ofset`
    _ledger_okundu = True                                   # son `ledger_oku` başarılı mı (ilk kurulum dahil)
    _ledger_hata_say = 0                                    # ardışık başarısız ledger okuması (3'te alarm, sonra saatte bir)

    @staticmethod
    def _onceki_oku(v: Any) -> tuple[float, float] | None:
        try:
            a, b = float(v[0]), float(v[1])
        except (TypeError, ValueError, IndexError, KeyError):
            return None
        return (a, b) if math.isfinite(a) and math.isfinite(b) else None

    def _ofset_bayrak(self, aktif: bool) -> None:
        self._ofset_dogrulanmadi = aktif
        self.risk.bayrak("ofset", aktif)

    def _ofset_adimi(self, ledger: list[dict] | None, denendi: bool, simdi: int) -> None:
        """K-1 (2. denetim; yalnız gerçek kip): ledger satırlarını ofsete uygular (`ofset_yenile`), sonra ofset doğrulanmışlığını yönetir. Bu turda ledger okunmadıysa (`denendi` False) durum değişmez. Ledger okundu
        (boş liste dahil; HL değeri daha önce okunmuş olmalı: ofset o değerle tutarlı) → doğrulandı: `ofset` açılış bayrağı kalkar, risk yeniden HL − ofset temelinde. Ledger okunamadı → doğrulanmadı: risk yerel defterle sürer (ertelenmez), açılış bayrağı `ofset` (DUR yok);
        3. ardışık başarısızlıkta alarm, sonra saatte bir."""
        if self.kip != "gercek":
            return
        self.ofset_yenile(ledger, simdi)
        if not denendi or self.hl_oz is None:
            return
        if self._ledger_okundu:
            self._ledger_hata_say = 0
            if self._ofset_dogrulanmadi or self.risk.acilis_durdu.get("ofset"):
                self._ofset_bayrak(False)
                self.kayit({"olay": "ofset_dogrulandi", "ofset": self.hl_ofset})
                self.tg.duzeldi("ofset", tg.duzeldi_metni("yatırma/çekme kaydı okunuyor", "Yeni pozisyonlar yeniden serbest."))
            return
        self._ledger_hata_say += 1
        if not self._ofset_dogrulanmadi:
            self.kayit({"olay": "ofset_dogrulanmadi", "ardisik": self._ledger_hata_say})
        self._ofset_bayrak(True)
        if self._ledger_hata_say >= 3:
            self.tg.uyar("ofset", tg.alarm("ALARM: yatırma/çekme kaydı okunamıyor", f"Hesap hareketi okuması {self._ledger_hata_say} kez üst üste başarısız; yatırma/çekme doğrulanamıyor.\n"
                                           "Yeni pozisyon açılmıyor; risk yerel defterle sürüyor. Okuma düzelince kendiliğinden kalkar."))

    def funding_bekliyor(self, simdi: int) -> bool:
        return self.kip == "sanal" and self.son_funding_saat is not None and simdi // 3_600_000 > self.son_funding_saat and any(self.hesap.poz.values())

    def funding_oku(self) -> dict[str, float] | None:
        """Sanal kip (ağ; kilitsiz): `metaAndAssetCtxs` (ana dex + her HIP‑3 dex) coin başına GÜNCEL saatlik funding oranı (oran: 0,0001 = %0,01 / saat). Hata: None."""
        oranlar: dict[str, float] = {}
        try:
            for dex in ["", *self._dexler()]:
                meta, ctxs = self.post({"type": "metaAndAssetCtxs", **({"dex": dex} if dex else {})})[:2]
                for u, c in zip(meta["universe"], ctxs):
                    try:
                        oranlar[str(u["name"])] = float(c["funding"])
                    except (KeyError, TypeError, ValueError):
                        continue
            return oranlar
        except Exception as hata:                          # noqa: BLE001
            self.kayit({"olay": "funding_okuma_hata", "tur": type(hata).__name__})
            return None

    def funding_uygula(self, oranlar: dict[str, float] | None, simdi: int) -> float:
        """Sanal funding (K‑37 §2): her tam saatte açık pozisyon başına `−sz × mark × oran` (long pozitif oranda öder; `defter.py` ile aynı işaret/birim). Saat başından sonraki ilk dakikalık bakımda,
        o anki pozisyon ve mark ile uygulanır (yeniden başlatmada kaçan saatler için en çok 24 kez, güncel oranla). Oran okunamazsa saat ilerlemez, sonraki dakika yeniden denenir. Döner: toplam funding ($)."""
        saat = simdi // 3_600_000
        if self.kip != "sanal":
            return 0.0
        if self.son_funding_saat is None or not any(self.hesap.poz.values()):          # pozisyon yokken geçen saatlerde funding yok
            self.son_funding_saat = saat
            self._funding_bekleyen = []
            return 0.0
        bekleyen = self._funding_bekleyen
        son_kapsanan = bekleyen[-1][0] if bekleyen else self.son_funding_saat
        if saat > son_kapsanan:
            # F07 (denetim 10.11): saat sınırını geçen ilk bakımda pozisyonun anlık görüntüsü alınır (oran okunamasa da). Oran sonra gelince her saat KENDİ
            # görüntüsüyle hesaplanır; arada değişen pozisyon (ör. 1 → 10 BTC) geçmiş saatlere uygulanmaz.
            goruntu = [(a, c, p.sz, self.marks.get(c) or p.giris) for a, cs in self.hesap.poz.items() for c, p in cs.items()]
            bekleyen.append((saat, saat - son_kapsanan, goruntu))
        self._funding_bekleyen = bekleyen
        n = min(24, sum(k for _, k, _ in bekleyen))
        if n <= 0 or oranlar is None:
            return 0.0
        toplam = 0.0
        kalan = 24
        for _, k, goruntu in bekleyen:
            k = min(k, kalan)
            kalan -= k
            for adres, coin, sz, mk in goruntu:
                oran = oranlar.get(coin)
                if oran is None:                               # t4b #7: sessiz atlama yok; sayaç + kayıt
                    self.sayac["funding_oran_yok"] += 1
                    self.kayit({"olay": "funding_oran_yok", "coin": coin, "adres": adres, "saat": saat})
                    continue
                f = -sz * mk * oran * k
                self.hesap.funding_isle(adres, f)
                toplam += f
        self.son_funding_saat = saat
        self._funding_bekleyen = []
        self.kayit({"olay": "funding", "saat": saat, "saat_adet": n, "funding_usd": toplam, "toplam_funding_usd": self.hesap.funding_toplam()})
        return toplam

    def funding_gercek_oku(self, simdi: int) -> list[dict] | None:
        """G7 gerçek kip (ağ; kilitsiz; en çok saatte bir): kendi hesabımızın `userFunding` satırları (sayfalı, 500/sayfa), `son_funding_ms`ten sonrası. İşaretçi yoksa (eski motor.json / ilk açılış)
        yalnız başlangıç anı sabitlenir, geçmiş funding OKUNMAZ (ilk ofset zaten ilk HL okumasından). Hata → None, işaretçi ve saat ilerlemez (sonraki dakika yeniden dener)."""
        if self.kip != "gercek" or simdi - self._son.get("funding_gercek", 0) < 3_600_000:
            return None
        if self.son_funding_ms is None:
            self.son_funding_ms, self._son["funding_gercek"] = simdi, simdi
            return None
        try:
            imlec, sonuc, gorulen = self.son_funding_ms + 1, [], set()
            for _ in range(40):
                sf = self.post({"type": "userFunding", "user": os.environ.get("HL_HESAP_ADRESI", ""), "startTime": imlec}) or []
                anahtarlar = [(x.get("time"), (x.get("delta") or {}).get("coin")) for x in sf]
                yeni = [x for x, k in zip(sf, anahtarlar) if k not in gorulen]
                gorulen.update(anahtarlar)
                sonuc += yeni
                if len(sf) < 500 or not yeni:
                    break
                imlec = max(int(x["time"]) for x in sf)
            self._son["funding_gercek"] = simdi
            return sonuc
        except Exception as hata:                          # noqa: BLE001
            self.kayit({"olay": "funding_okuma_hata", "tur": type(hata).__name__, "kip": "gercek"})
            return None

    def funding_gercek_uygula(self, satirlar: list[dict] | None, simdi: int) -> float:
        """G7: her `funding` satırının `usdc` tutarı ($, + alınan / − ödenen) o coindeki yerel pozisyonlara `|sz|` payıyla dağıtılır (`hesap.funding_isle`; sanal funding ile aynı yer ve işaret). Yerelde o coinde
        pozisyon yoksa (kapanmış) tutar `kapanmis_net`e yazılır (özsermaye sürekliliği; `funding_dagitilmadi` kaydı). İdempotent: `son_funding_ms` ve `time:coin` anahtarı. Döner: işlenen toplam ($)."""
        if self.kip != "gercek" or not satirlar or self.son_funding_ms is None:
            return 0.0
        toplam, en_yeni = 0.0, self.son_funding_ms
        for x in sorted(satirlar, key=lambda r: r.get("time") or 0):
            dl, z = x.get("delta") or {}, x.get("time")
            anahtar = f"{z}:{dl.get('coin')}"
            try:
                usdc = float(dl.get("usdc"))
            except (TypeError, ValueError):
                continue
            if dl.get("type") != "funding" or not isinstance(z, (int, float)) or not math.isfinite(usdc) or z < self.son_funding_ms or anahtar in self.funding_kimlik:
                continue
            coin = str(dl.get("coin"))
            paylar = {a: abs(c[coin].sz) for a, c in self.hesap.poz.items() if coin in c and abs(c[coin].sz) > 1e-12}
            if paylar:
                t = sum(paylar.values())
                for a, w in paylar.items():
                    self.hesap.funding_isle(a, usdc * w / t)
            else:
                self.hesap.kapanmis_net += usdc
                self.kayit({"olay": "funding_dagitilmadi", "coin": coin, "usdc": usdc, "time": z})
            self.funding_kimlik.append(anahtar)
            self.funding_gercek_usd += usdc
            toplam += usdc
            en_yeni = max(en_yeni, int(z))
        self.son_funding_ms = en_yeni
        if toplam:
            self.kayit({"olay": "funding_gercek", "funding_usd": toplam, "toplam_funding_gercek_usd": self.funding_gercek_usd, "satir": len(satirlar)})
        return toplam

    def dakika(self) -> None:
        """Dakikalık bakım: mark, tasfiye (sanal), özsermaye riski, anlık saha kuralları, inen kapama, mutabakat, kadro, trader pozisyon senkronu, Telegram komutları, günlük özet.
        Ağ okumaları (allMids, kadro, pozisyon) KİLİT DIŞINDA yapılır (olay işleme gecikmesin); durum değişimi kilit altında. Bir adımın hatası diğerlerini atlatmaz."""
        simdi = self.saat_ms()
        mids = self.mids_al()
        kadro = self._kadro_al(simdi)
        yenile = self._aralik_mi("senkron", simdi, float(self.rules["canli_hesap_okuma_sn"]))
        senkron = self.senkron_oku() if yenile else None
        hesaplar = self.hesap_oku() if yenile else {}
        komutlar = self.tg.komutlari_al()                      # ağ: kilitsiz
        hl_zamani = self.kip == "gercek" and simdi - self._son.get("mutabakat", 0) >= float(self.rules["canli_mutabakat_sn"]) * 1000
        self._hl_okuma_imza = self._poz_imza() if hl_zamani else None          # mutabakat yarışı: HL okumasından ÖNCEKİ yerel pozisyonlar
        hl = self.hl_oku() if hl_zamani else None
        ucretler = self.ucret_oku(simdi)                                           # Denetim-6 (O9): gerçek ücret düzeltmesi için okuma (kilit dışı)
        oranlar = self.funding_oku() if self.funding_bekliyor(simdi) else None
        stop_acik = self.acik_emir_oku() if self.kip == "gercek" and self._aralik_mi("borsa_stop", simdi, float(self.rules["canli_borsa_stop_sn"])) else False     # K-64
        hacimler = self.hacim_oku() if self._aralik_mi("hacim", simdi, 3600 if self._coin_hacim else 300) else None     # K-62: saatte bir (veri yoksa 5 dk'da bir dene)
        kaldirac = (self.maks_kaldirac_tablosu()[0] if self.kip == "gercek" and float(self.rules.get("canli_min_azami_kaldirac", 0) or 0) > 0
                    and self._aralik_mi("kaldirac_tablo", simdi, 3600 if self._hl_maks_kaldirac else 60) else None)       # Denetim-4a: azami kaldıraç tablosu (saatte bir; boşsa dakikada bir)
        fgercek = self.funding_gercek_oku(simdi)                                # G7: gerçek kip, saatte bir; sanalda None
        denendi = bool(hl) or (self.kip == "gercek" and self._ofset_dogrulanmadi)
        ledger = self.ledger_oku(simdi) if denendi else None      # gerçek kip: yatırma/çekme kaydı (#5); ofset doğrulanmadıysa HL koşulundan bağımsız HER dakika denenir (K-1)
        ajan = self.ajan_suresi_oku(simdi)                                       # G-19: gerçek kip, günde bir: API cüzdanı `validUntil`
        btc = self.btc_donem_oku(simdi)                                          # BTC al-tut kıyası: dönem başı BTC fiyatı (yalnız eksikse; salt okur info)
        with self._lock:
            self.mids_uygula(mids, simdi)
            if hacimler:
                self._coin_hacim = hacimler
            self.kaldirac_tablosu_uygula(kaldirac)
            if self.son_funding_saat is None:
                self.son_funding_saat = simdi // 3_600_000
            adimlar: list[tuple[str, Callable[[], None]]] = [
                ("belirsiz", lambda: self.belirsiz_coz(simdi)),                    # G-1: sonucu belirsiz emirler risk/mutabakattan ÖNCE deftere
                ("ucret_duzelt", lambda: self.ucret_uygula(ucretler, simdi)),      # Denetim-6 (O9): tahmini ücret → HL fee (okuma kilit dışında yapıldı)
                ("tasfiye", lambda: self._tasfiye(simdi)), ("funding", lambda: self.funding_uygula(oranlar, simdi)), ("funding_gercek", lambda: self.funding_gercek_uygula(fgercek, simdi)),
                ("hl_ozsermaye", lambda: self.hl_uygula(hl[1], simdi, self._hl_okuma_ms(hl, simdi)) if hl else None), ("ofset", lambda: self._ofset_adimi(ledger, denendi, simdi)),
                ("hl_sicrama", lambda: self._hl_sicrama_denetle(simdi) if hl else None), ("risk", lambda: self._risk(simdi)), ("felaket_stop", lambda: self._felaket_stop(simdi)), ("iz_suren", lambda: self._iz_suren_koruma(simdi)),
                ("borsa_stop", lambda: self.borsa_stop_esitle(stop_acik, simdi) if stop_acik is not False else None), ("anlik_saha", lambda: self._anlik(simdi)),
                ("inen", lambda: self.karar_uygula(self.saha.inenleri_kapat(simdi), simdi)), ("sahipsiz", lambda: self._sahipsiz_tara(simdi)),
                ("hl_izle", lambda: self._hl_izle(hl_zamani, hl, simdi)), ("mutabakat", lambda: self._mutabakat(simdi, hl)), ("kapanis_kuyrugu", lambda: self._kuyruk_isle(simdi)),
                ("kadro", lambda: self._kadro_uygula(kadro, simdi)), ("senkron", lambda: (self.senkron_uygula(senkron), self.hesap_uygula(hesaplar, simdi)) if senkron is not None else None),
                ("kacan_telafi", lambda: self.kacan_telafi(simdi) if senkron is not None else None),                   # K-75 (yalnız sanal, bayraklı): senkrondan SONRA (kapanışlar önce, hesap değerleri taze)
                ("telegram", lambda: self._komutlar(komutlar)), ("ajan_suresi", lambda: self.ajan_suresi_uygula(ajan, simdi)), ("ozet", lambda: self._gunluk_ozet(simdi)), ("haftalik", lambda: self._haftalik_ozet(simdi)),
                ("emir_ozeti", lambda: self.emir_ozeti(simdi)), ("btc_donem", lambda: self.btc_donem_uygula(btc)), ("donem_seri", lambda: self.donem_seri_guncelle(simdi)),
                ("ogrenme", lambda: self.ogrenme.adim(simdi)), ("tur_kaydi", lambda: self._tur_kaydi(simdi)), ("golge_kural", lambda: self.golge_kural_adimi(simdi)), ("karsi_olgu", lambda: self.karsi_olgu_adimi(simdi)), ("kopya_drift", lambda: self.kopya_drift_adimi(simdi)),          # yalnız kayıt + pano verisi; karar yolunda değil
                ("haber", lambda: self.haber_adimi(simdi)), ("rejim", lambda: self.rejim_adimi(simdi)),                        # ML rejim etiketi: sanalda açılış filtresi (sanal_rejim_filtre), gerçek kipte yalnız kayıt
                ("durum_yaz", self.durum_yaz),                                     # G-12b: disk dolu / salt okunur → dakikalık görev ölmez; kayıt + alarm
            ]
            for ad, f in adimlar:
                try:
                    f()
                    self._adim_ardisik.pop(ad, None)
                except Exception as hata:                  # noqa: BLE001
                    n = self._adim_ardisik[ad] = self._adim_ardisik.get(ad, 0) + 1
                    self.kayit({"olay": "adim_hata", "adim": ad, "tur": type(hata).__name__, "mesaj": str(hata)[:160], "ardisik": n})
                    if ad == "durum_yaz" and self._aralik_mi("durum_yaz_alarm", simdi, 3600):
                        self.tg.gonder(tg.alarm("ALARM: durum diske yazılamıyor", f"Dakikalık durum kaydı başarısız ({type(hata).__name__}).\nYeniden başlatmada son durum kaybolabilir.", senden="Bana haber ver, ben bakarım."))
                    elif ad != "durum_yaz" and (n == ADIM_ALARM_ARDISIK or (n > ADIM_ALARM_ARDISIK and n % 60 == 0)):      # M-2: aynı adım üst üste 3 kez → alarm (sonra saatte bir)
                        self.tg.gonder(tg.alarm(f"ALARM: '{tg.sade_ad(ad)}' adımı hata veriyor", f"Dakikalık '{tg.sade_ad(ad)}' adımı üst üste {n} kez başarısız ({type(hata).__name__}).\n"
                                                "Bu adımın koruması çalışmıyor olabilir; bekçi gerekirse motoru yeniden başlatır."))

    def _btc_donem_gecerli(self) -> dict | None:
        b = self.btc_donem
        return b if b and self.donem and b.get("donem") == self.donem and b.get("fiyat") else None

    def btc_donem_oku(self, simdi: int) -> dict | None:
        """Başarı ölçütü kıyası (31.12: ayda ≥ %4 VE BTC al-tut'tan iyi): dönem (`self.donem`) başındaki BTC fiyatı. Yalnız henüz kayıtlı değilse ve 5 dk'da bir denenir (ağ; kilitsiz; salt okur info).
        Kaynak sırası: dönem başını içeren 1 dk mumun açılışı (`mum_1m`) → 1 sa mum (`mum_1h`; 1 dk mum ~3,5 günden eskiyse) → dönem başından en çok 15 dk sonra güncel BTC mid (`mid`). Yoksa None (pano "—")."""
        if not self.donem or self._btc_donem_gecerli() or not self._aralik_mi("btc_donem", simdi, 300):
            return None
        bas = donem_ms(self.donem)
        if bas is None or simdi < bas:
            return None
        for aralik, adim in (("1m", 60_000), ("1h", 3_600_000)):
            try:
                mumlar = self.post({"type": "candleSnapshot", "req": {"coin": "BTC", "interval": aralik, "startTime": bas - adim, "endTime": bas + 10 * adim}}) or []
            except Exception as hata:                      # noqa: BLE001
                self.kayit({"olay": "btc_donem_hata", "tur": type(hata).__name__})
                return None
            for mm in sorted(mumlar, key=lambda x: int(x.get("t", 0))):
                t = int(mm.get("t", 0))
                if t + adim <= bas:                             # dönem başından önce biten mum
                    continue
                try:
                    px = float(mm["o"])                          # dönem başını içeren (ya da ondan sonraki ilk) mumun açılışı
                except (KeyError, TypeError, ValueError):
                    continue
                if px > 0:
                    return {"donem": self.donem, "bas_ms": bas, "fiyat": px, "kaynak": f"mum_{aralik}", "mum_ms": t, "okundu_ms": simdi}
        mid = self.marks.get("BTC")
        if mid and simdi - bas <= 15 * 60_000:
            return {"donem": self.donem, "bas_ms": bas, "fiyat": float(mid), "kaynak": "mid", "okundu_ms": simdi}
        return None

    def btc_donem_uygula(self, okuma: dict | None) -> None:
        if okuma is None or self._btc_donem_gecerli():
            return
        self.btc_donem = okuma
        self.kayit({"olay": "btc_donem", **okuma})

    DOLULUK_ADIM_MAX_MS = 5 * DAKIKA            # doluluk birikiminde iki güncelleme arası en çok bu kadar sayılır (vardiya boşluğu sayılmaz)

    def _ds(self) -> dict | None:
        """Bu dönemin `donem_seri` sözlüğü (dönem değiştiyse sıfırdan); dönem yoksa None."""
        if not self.donem:
            return None
        if self.donem_seri.get("donem") != self.donem:
            self.donem_seri = {"donem": self.donem, "bas_ms": None, "kasa_usd": self.kasa, "btc_donem_fiyat": None, "gunler": []}
        return self.donem_seri

    def _katman(self, adres: str) -> str | None:
        for r in (self._son_kadro or {}).get("satirlar") or []:
            if r.get("adres") == adres:
                return r.get("katman")
        return None

    def _slot_kaydi(self, adres: str) -> dict | None:
        """Adresin dönemdeki SON slot kaydı (pano: trader katkısı / giriş-çıkış geçmişi)."""
        ds = self._ds()
        for r in reversed((ds or {}).get("slotlar") or []):
            if r.get("adres") == adres:
                return r
        return None

    def _slot_net_guncelle(self, adres: str) -> None:
        """Slot kaydının net K/Z'si ($) = slot özsermayesi − slot tabanı (realize − ücret + funding + açık K/Z). Slot defterde yoksa dokunulmaz (son değer kalır)."""
        r = self._slot_kaydi(adres)
        oz = self.hesap.slot_ozsermaye(adres, self.marks)
        if r is not None and oz is not None and adres in self.hesap.slot_bas:
            r["net_usd"] = round(oz - float(self.hesap.slot_bas[adres]), 4)

    def donem_slot_giris(self, adres: str, neden: str, simdi: int) -> None:
        """Pano (14.11): dönem boyu slot kaydı [{adres, katman (ilk11/yedek/None), giris_ms, giris_neden, cikis_ms, cikis_neden, sonuc, net_usd}] — kalıcı (`donem_seri.json`), 14 günlük kayıt penceresinden bağımsız."""
        ds = self._ds()
        if ds is None:
            return
        ds.setdefault("slotlar", []).append({"adres": adres, "katman": self._katman(adres), "giris_ms": simdi, "giris_neden": neden, "cikis_ms": None, "cikis_neden": None,
                                            "sonuc": None, "net_usd": 0.0})

    def donem_slot_cikis(self, adres: str, neden: str, sonuc: bool, simdi: int) -> None:
        r = self._slot_kaydi(adres)
        if r is not None and r.get("cikis_ms") is None:
            self._slot_net_guncelle(adres)
            r["cikis_ms"], r["cikis_neden"], r["sonuc"] = simdi, neden, bool(sonuc)

    def donem_kilit(self, tur: str, simdi: int) -> None:
        """M-05 (pano, 14.11): dönem boyu risk kilidi olayları [{ms, tur}] (günlük kayıp/sert fren, zirve düşüşü, felaket stopu); panoda dönem eğrisinde işaretlenir. En çok 500 kayıt."""
        ds = self._ds()
        if ds is None:
            return
        k = ds.setdefault("kilitler", [])
        k.append({"ms": int(simdi), "tur": str(tur)})
        del k[:-500]

    def donem_emir_say(self, tur: str, neden: str | None = None) -> None:
        """Pano (14.11) dönem boyu emir sayacı: `emir` (gönderilen), `atlanan` (`emir_yok`), `yuvarlanan` (min emre yuvarlanan gönderilen), `atlama_neden` {neden: adet}."""
        ds = self._ds()
        if ds is None:
            return
        sy = ds.setdefault("emir_sayac", {"emir": 0, "atlanan": 0, "yuvarlanan": 0, "atlama_neden": {}})
        sy[tur] = int(sy.get(tur, 0)) + 1
        if tur == "atlanan" and neden:
            sy["atlama_neden"][neden] = int(sy["atlama_neden"].get(neden, 0)) + 1

    def donem_seri_guncelle(self, simdi: int) -> None:
        """F-06 (14.11 denetim): `durum/donem_seri.json` = {donem, bas_ms, kasa_usd, btc_donem_fiyat, gunler: [{gun (UTC), ozsermaye_usd, btc}]}. Her dakika o UTC gününün kaydı
        güncellenir: gün bitince son değer = gün sonu. Dönem değişince seri sıfırdan başlar. Dönem yoksa yazılmaz.
        Pano 14.11 ekleri: `slotlar` (açık slotların net K/Z'si her güncellemede; dönem başında sahada olan üye `giris_neden` "donem_basi" ile eklenir), `doluluk` {sure_ms, slot_ms
        (Σ sahadaki üye × süre), kapasite_ms (Σ saha_n × süre), nakit_ms (Σ nakit payı × süre; nakit payı = 1 − min(1, brüt pozisyon / özsermaye)), brut_ms / net_ms (M-04: Σ brüt $ / |net| $ × süre),
        son_ms}; adım ≤ 5 dk sayılır. `kilitler` (M-05) `donem_kilit` ile."""
        if self._ds() is None:
            return
        for adres in self.hesap.slot_bas:
            if self._slot_kaydi(adres) is None:
                self.donem_slot_giris(adres, "donem_basi", simdi)
            self._slot_net_guncelle(adres)
        dl = self.donem_seri.setdefault("doluluk", {"sure_ms": 0, "slot_ms": 0.0, "kapasite_ms": 0.0, "nakit_ms": 0.0, "son_ms": None})
        if dl.get("son_ms") is not None and 0 < simdi - int(dl["son_ms"]) <= self.DOLULUK_ADIM_MAX_MS:
            dt = simdi - int(dl["son_ms"])
            oz = self.ozsermaye()
            brut = self.hesap.brut_toplam(self.marks)
            nakit = 1.0 - min(1.0, max(0.0, brut / oz)) if oz > 0 else 0.0
            net = abs(sum(p.sz * (self.marks.get(c) or p.giris) for cs in self.hesap.poz.values() for c, p in cs.items()))
            dl["brut_ms"] = float(dl.get("brut_ms") or 0.0) + brut * dt              # M-04: zaman ağırlıklı brüt maruziyet ($ × ms)
            dl["net_ms"] = float(dl.get("net_ms") or 0.0) + net * dt                 # M-04: zaman ağırlıklı |net uzun − kısa| ($ × ms)
            dl["sure_ms"] = int(dl["sure_ms"]) + dt
            dl["slot_ms"] = float(dl["slot_ms"]) + len(self.saha.uyeler) * dt
            dl["kapasite_ms"] = float(dl["kapasite_ms"]) + int(self.saha.n) * dt
            dl["nakit_ms"] = float(dl["nakit_ms"]) + nakit * dt
        dl["son_ms"] = simdi
        b = self._btc_donem_gecerli()
        if b:
            self.donem_seri["bas_ms"], self.donem_seri["btc_donem_fiyat"] = b["bas_ms"], b["fiyat"]
        self.donem_seri["kasa_usd"] = self.kasa
        g = gun(simdi)
        satir = {"gun": g, "ozsermaye_usd": round(self.ozsermaye(), 4), "btc": self.marks.get("BTC")}
        gunler = self.donem_seri.setdefault("gunler", [])
        if gunler and gunler[-1].get("gun") == g:
            gunler[-1] = satir
        else:
            gunler.append(satir)

    def btc_kiyas(self, getiri: float | None) -> dict[str, Any]:
        """Aynı dönemde BTC al-tut getirisi = güncel BTC mid / dönem başı fiyat − 1; `btc_fark` = motor getirisi − BTC al-tut (oran farkı). Veri yoksa None.
        F-06: `donem_gun` (dönem başından gün, kesirli), `aylik_esdeger` = (1 + getiri)^(30 / gün) − 1 (`aylik_esdeger`), `hedef_gecer` = aylık ≥ `basari_aylik_hedef` (%4) VE getiri > BTC al-tut."""
        b = self._btc_donem_gecerli()
        simdi_px = self.marks.get("BTC")
        al_tut = (float(simdi_px) / float(b["fiyat"]) - 1) if b and simdi_px else None
        bas_ms = donem_ms(self.donem)
        gun_sayi = (self.saat_ms() - bas_ms) / 86_400_000 if bas_ms is not None else None
        aylik = aylik_esdeger(getiri, gun_sayi)
        hedef = float(self.rules.get("basari_aylik_hedef", 0.04))
        return {"donem": self.donem, "btc_donem_fiyat": b["fiyat"] if b else None, "btc_fiyat": simdi_px, "btc_al_tut_getiri": al_tut,
                "btc_fark": (getiri - al_tut) if al_tut is not None and getiri is not None else None,
                "donem_gun": gun_sayi, "aylik_esdeger": aylik, "aylik_hedef": hedef,
                "hedef_gecer": None if aylik is None or al_tut is None or getiri is None else bool(aylik >= hedef and getiri > al_tut)}

    def _tur_kaydi(self, simdi: int) -> None:
        """Pano özsermaye/düşüş grafiği için ~15 dk'da bir `tur` kaydı (özsermaye $). Karar mantığına girmez."""
        if self._aralik_mi("tur_kaydi", simdi, 14 * 60):
            self.kayit({"olay": "tur", "ozsermaye_usd": round(self.ozsermaye(), 4)})

    def _aralik_mi(self, ad: str, simdi: int, sn: float) -> bool:
        if simdi - self._son.get(ad, 0) >= sn * 1000:
            self._son[ad] = simdi
            return True
        return False

    def emir_ozeti(self, simdi: int, zorla: bool = False) -> None:
        """Biriken emirleri tek Telegram mesajı olarak gönderir (`canli_telegram_emir_ozet_sn` aralığında; vardiya sonunda `zorla`)."""
        self._islem_toplu(simdi, zorla)
        if zorla:
            self.tg.tampon_bosalt()                      # G-18: gerçek kip emir tamponu vardiya sonunda beklemeden gider
        dk = float(self.rules.get("canli_telegram_sanal_ozet_dk", 0) or 0)
        if self.kip == "sanal" and dk > 0:
            return self._saatlik_ozet(simdi, dk, zorla)
        sn = float(self.rules["canli_telegram_emir_ozet_sn"])
        if not self._emir_tampon or not (zorla or self._aralik_mi("emir_ozeti", simdi, sn)):
            return
        emirler, self._emir_tampon = self._emir_tampon, []
        self.tg.gonder(tg.msg_emir_ozeti(self.kip, emirler, sn / 60.0), tur="emir_ozeti")

    def _saatlik_ozet(self, simdi: int, dk: float, zorla: bool) -> None:
        """SANAL kip: emirler `canli_telegram_sanal_ozet_dk` dakikalık pencerede TEK mesajda (pencere motor saatinden). Emir yoksa mesaj yok. `zorla` (vardiya sonu): kalan pencere hemen gider."""
        bas = self._ozet_pencere_bas
        if not zorla and simdi - bas < dk * DAKIKA:
            return
        emirler, atlanan = self._emir_tampon, self._atla_tampon
        self._emir_tampon, self._atla_tampon = [], {}
        self._ozet_pencere_bas = simdi
        islem, adresler = len(self._atla_islem), self._atla_adres
        self._atla_islem, self._atla_adres = set(), {}
        adaylar = self._drift_adaylari(simdi)
        if adaylar:                                                     # kopya sapması satırı artık mesajda yok (yalnız bilgi): kayda yazılır, damga ilerler (6 saatte bir)
            self.kayit({"olay": "tg_bastirildi", "tur": "kopya_sapmasi", "metin": tg.drift_satiri(adaylar)})
            for c in adaylar:
                self.kopya_drift_tg_ms[c] = simdi
        metin = tg.msg_sanal_saatlik(bas, simdi, round((simdi - bas) / DAKIKA) if zorla else dk, emirler, atlanan,
                                     (self.ozsermaye(), self.risk.gun_basi, self.kasa) if emirler else None, islem, adresler, "")
        if metin:
            self.tg.gonder(metin, tur="emir_ozeti")
        elif not zorla:                                                 # emirsiz "sistem çalışıyor" mesajı bastırılır; kayda `tg_bastirildi` yazılır
            self.tg.gonder(tg.msg_sanal_saatlik_bos(bas, simdi, dk, atlanan, (self.ozsermaye(), self.risk.gun_basi, self.kasa), islem, adresler, ""), tur="saatlik_bos")

    def _tasfiye(self, simdi: int) -> None:
        if self.kip != "sanal":
            return                                         # gerçek kipte tasfiyeyi HL yapar; mutabakat farkı yakalar
        for e in self.hesap.tasfiye_kontrol(self.marks, simdi):
            self.kayit({"olay": "tasfiye", **e})
            self._tasfiye_emri(e, simdi)
            self.tg.gonder(tg.alarm("Tasfiye (sanal)", f"{e['coin']} pozisyonu (trader {tg.kisa(e['adres'])}) {e['tasfiye_px']:.6g} fiyatında tasfiye oldu (piyasa {e['mark']:.6g}). Pozisyon kapandı, kayıt yazıldı.", "💥"))

    def _tasfiye_emri(self, e: dict, simdi: int) -> None:
        """Sanal tasfiye = normal kapanış gibi görünür: `emir` kaydı (kapanış, neden tasfiye; pano/mutabakat görür) + standart 'kapandı' Telegram mesajı. Defter `tasfiye_kontrol`de zaten düşülmüştür.
        Hata motoru durdurmaz."""
        try:
            adres, coin, sz, px, pnl = e["adres"], e["coin"], float(e.get("sz") or 0.0), float(e["tasfiye_px"]), float(e["pnl"])
            uzun = e.get("yon") == "uzun"
            yon = "A" if uzun else "B"
            self._dolum_yaz()
            self.kayit({"olay": "emir", "kip": self.kip, "adres": adres, "coin": coin, "eylem": "kapat", "yon": yon, "usd_istenen": sz * px, "usd_dolan": sz * px, "sz": sz, "reduce_only": True,
                        "pnl_usd": round(pnl, 6), "durum": "dolu", "red_neden": None, "boyut_neden": "tasfiye", "emir_ms": simdi, "dolum_ms": simdi, "referans_px": e.get("mark"), "dolum_px": px,
                        "ucret": 0.0, "kaynak": "tasfiye"})
            self._ozet_emir += 1
            self._say_gun["kapat"] = self._say_gun.get("kapat", 0) + 1
            ozet = self._poz_ozet.pop(f"{adres}|{coin}", None)
            giris = float(e.get("giris") or 0.0)
            toplam = float(ozet["tutar"]) if ozet else sz * giris
            kz = (float(ozet["pnl"]) if ozet else 0.0) + pnl
            self._islem_mesaji(tg.msg_kapandi(adres, coin, kz, (kz / toplam) if toplam > 0 else None, "tasfiye", self.kip, toplam, int(ozet["artir"]) if ozet else 0, int(ozet["azalt"]) if ozet else 0), False, kz,
                               {"adres": adres, "coin": coin, "yon": yon, "pnl": round(kz, 6), "neden": "tasfiye"})
        except Exception as hata:                           # noqa: BLE001
            self.kayit({"olay": "tasfiye_emir_hata", "tur": type(hata).__name__})

    _zirve_yenile = False
    bekci_nabiz: Callable[[], None] | None = None          # `calis` bekçinin `nabiz`ını bağlar (kapanış döngüsü her denemede besler)
    _hl_sicrama = False                                     # S-6: son HL okumasında açıklanmayan özsermaye sıçraması var mı
    _hl_sicrama_ms = 0
    _hl_onceki: tuple[float, float] | None = None           # S-6: önceki HL okumasında (HL − ofset, yerel özsermaye) $
    _mutabakat_tamam_ms: int | None = None                 # Denetim-8 (O4): `_mutabakat` sonuna kadar çalıştığı an (ilk_mutabakat tamamlandı mı)
    _hl_okuma_imza: tuple | None = None                     # `dakika`: HL kilit dışında okunmadan hemen önceki yerel pozisyon imzası (`_mutabakat` tüketir)

    def _poz_imza(self) -> tuple:
        """Yerel defter pozisyon imzası (adres, coin, sz): HL kilit dışında okunurken defter değişti mi (mutabakat yarışı)."""
        with self._lock:
            return tuple(sorted((a, c, p.sz) for a, cs in self.hesap.poz.items() for c, p in cs.items()))

    def _hl_sicrama_denetle(self, simdi: int) -> None:
        """S-6 (yalnız gerçek kip; her yeni HL okumasından sonra, ofset adımından SONRA, risk adımından ÖNCE): açıklanmayan = Δ(HL − ofset) − Δ(yerel özsermaye) ($, iki ardışık okuma arası).
        Yerel defter dolum/mark/funding değişimini içerir; köprü yatırma/çekme ofsette. Geriye kalan büyük fark ledger'da sayılmayan transfer (internalTransfer/send/subAccountTransfer),
        HL tasfiyesi vb. |açıklanmayan| > kasa × `canli_hl_sicrama_oran` (0,10) → mutabakat bayrağı + alarm ve BU okumada özsermaye riski (günlük/zirve → DUR) ertelenir. Sonraki okuma
        sıçramasızsa erteleme kalkar: düşüş gerçekse DUR o adımda olur."""
        if self.kip != "gercek" or self.hl_oz is None or self.hl_ofset is None or self._ofset_dogrulanmadi:
            return                                                                              # K-1: ofset doğrulanmadıysa HL − ofset anlamsız (karşılaştırma yapılmaz, önceki okuma korunur)
        net, yerel = self.hl_oz - self.hl_ofset, self.yerel_ozsermaye()
        onceki, self._hl_onceki = self._hl_onceki, (net, yerel)
        self._hl_sicrama = False
        if onceki is None:
            return
        aciklanmayan = (net - onceki[0]) - (yerel - onceki[1])
        esik = self.kasa * float(self.rules.get("canli_hl_sicrama_oran", 0.10))
        if abs(aciklanmayan) <= esik:
            return
        self._hl_sicrama, self._hl_sicrama_ms = True, simdi
        self.risk.bayrak("mutabakat", True)
        self.kayit({"olay": "hl_sicrama", "aciklanmayan_usd": round(aciklanmayan, 4), "esik_usd": round(esik, 4), "hl_net_usd": round(net, 4), "yerel_usd": round(yerel, 4)})
        self.tg.gonder(tg.alarm("ALARM: HL özsermayesinde açıklanamayan sıçrama", f"İki okuma arasında {tg.tr_sayi(aciklanmayan)} $ (sınır {tg.tr_sayi(esik)} $); işlem/yatırma/çekme açıklamıyor.\n"
                                "Yeni pozisyon açılmıyor; risk freni bir okuma ertelendi.", senden="Hyperliquid hesabına bakıp transfer ya da tasfiye var mı kontrol edebilirsin; bana da haber ver."))

    def _risk(self, simdi: int) -> None:
        self._dur_kurtar(simdi)
        oz = self.ozsermaye()
        if self._zirve_yenile:                                                                  # S-2: DUR sonrası ilk risk adımı (gerçek kipte HL − ofset temeli artık okunmuş olabilir)
            self._zirve_yenile = False
            if abs(oz - self.risk.zirve) > 1e-9:
                eski = self.risk.zirve_yenile(oz)
                self.kayit({"olay": "zirve_yenilendi", "eski_zirve": eski, "yeni_zirve": oz, "gerekce": "dur_sonrasi_ilk_risk"})
        if self.risk.kasa_siniri_asildi(self.kasa, kasa_ust(self.rules, self.kip)):
            self.tg.uyar("kasa_siniri", tg.alarm("ALARM: kasa sınırı aşıldı", f"Başlangıç sermayesi (kasa) {tg.tr_sayi(self.kasa, 0)} $ > izin verilen üst sınır {tg.tr_sayi(kasa_ust(self.rules, self.kip), 0)} $.\nYeni pozisyon açılmıyor."))
        else:
            self.tg.duzeldi("kasa_siniri", tg.duzeldi_metni("kasa sınırı", "Kasa sınırın altına indi; yeni pozisyonlar serbest."))
        if self._hl_sicrama and simdi - self._hl_sicrama_ms <= 3 * float(self.rules["canli_mutabakat_sn"]) * 1000:      # S-6: açıklanmayan sıçrama → bu okumada DUR yok (bayrak + alarm verildi)
            self.kayit({"olay": "risk_ertelendi", "neden": "hl_sicrama", "ozsermaye": oz})
            return
        olaylar = self.risk.ozsermaye_isle(oz, simdi)
        sinir = float(self.rules["canli_gunluk_kayip_oran"])
        kayip = (self.risk.gun_basi - oz) / self.risk.gun_basi if self.risk.gun_basi > 0 else 0.0
        if 0.8 * sinir - 1e-12 <= kayip < sinir - 1e-12 and self._gunluk80_gun != self.risk.gun:       # %80 eşiği: günde bir uyarı
            self._gunluk80_gun = self.risk.gun
            self.kayit({"olay": "gunluk_kayip_yaklasti", "kayip": round(kayip, 5), "sinir": sinir})
            self.tg.gonder(tg.msg_limit_yaklasti(kayip, sinir, oz), "WARN")
        for ev in olaylar:
            try:
                self.kayit({"olay": "risk", "tur": ev, "ozsermaye": oz})
            except Exception as hata:                                                           # noqa: BLE001 - kayıt hatası DUR/kapanışı engellemez (Denetim-3 O1)
                self._kayit_hata("risk_kayit", hata)
            if ev == "zirve_dusus":
                self.dur_tetikle("zirve_dusus")
            elif ev == "gunluk_kapat":                                                          # K-62: günlük sert fren — hepsi kapanır, DUR değil (ertesi gün sürer)
                self.risk.bayrak("gunluk_kayip", True)
                kapanan = sum(self._adres_kapat(a, "gunluk_kapat", simdi) for a in list(self.hesap.poz))
                kalan = sum(len(c) for c in self.hesap.poz.values())
                self.kayit({"olay": "gunluk_kapat", "kapanan": kapanan, "kalan": kalan, "ozsermaye": oz})
                self.tg.gonder(tg.alarm("ALARM: günlük sert fren", f"Bugünkü kayıp %{float(self.rules['canli_gunluk_kapat_oran']) * 100:.0f} sınırına ulaştı (özsermaye {tg.tr_sayi(oz)} $).\n"
                                        f"{kapanan} pozisyon kapatıldı{f', {kalan} kapanmadı (yeniden denenecek)' if kalan else ''}. Bugün yeni pozisyon açılmıyor; yarın (UTC) normal devam.", "🛑"))
            else:
                self.tg.gonder(tg.alarm("ALARM: günlük kayıp sınırı", f"Bugünkü kayıp %{float(self.rules['canli_gunluk_kayip_oran']) * 100:.0f} sınırına ulaştı (özsermaye {tg.tr_sayi(oz)} $).\nBugün yeni pozisyon açılmıyor; {sum(len(c) for c in self.hesap.poz.values())} açık pozisyon izlenmeye devam ediyor (trader kapatınca ya da kural gerektirince kapanır)."))
            try:                                                                                # kozmetik (pano işareti): koruyucu işlemden SONRA ve izole; istisnası DUR/kapanışı kaybettirmez
                self.donem_kilit(ev, simdi)
            except Exception as hata:                                                           # noqa: BLE001
                self._kayit_hata("donem_kilit", hata)

    _gunluk80_gun = None                                    # günlük kayıp %80 uyarısının son verildiği gün (günde bir)
    kapanis_modu = False                                    # D-11 (K-70): gerçek kip, HL > `canli_hl_deger_ust_usd` iken açık pozisyonla başlatıldı → YALNIZ kapanış (yeni açılış yok; kapanış/stop/trader kapanış takibi çalışır)
    _hl_ardisik = 0                                         # O-1: ardışık başarısız HL okuması (gerçek kip)
    HL_ARDISIK_ESIK = 3                                     # K-70: 3 ardışık okuma (≈ 3 dk) → `hl_okunamiyor` açılış bayrağı + alarm (saatte bir)
    SAHIPSIZ_TARAMA_KOPUK_MS = 3 * DAKIKA                   # taramalar arası bu kadar boşluk "kesintisiz" sayılmaz (yeniden başlatma / vardiya boşluğu)

    def _hl_izle(self, zamani: bool, hl: tuple | None, simdi: int) -> None:
        """2. denetim O-1 (yalnız gerçek kip; HL okuması yapılan dakikalarda): ardışık `HL_ARDISIK_ESIK` HL okuma hatasında `hl_okunamiyor` açılış bayrağı + alarm (saatte bir). Risk yerel defterle sürerdi (HL'deki tasfiye/ADL/çekim
        görünmez) ve açılışlar devam ederdi. Başarılı okuma sayacı sıfırlar, bayrağı kaldırır. Risk/DUR ertelenmez; yalnız yeni açılış durur."""
        if self.kip != "gercek" or not zamani:
            return
        if hl is None:
            self._hl_ardisik += 1
            if self._hl_ardisik >= self.HL_ARDISIK_ESIK:
                if not self.risk.acilis_durdu.get("hl_okunamiyor"):
                    self.kayit({"olay": "hl_okunamiyor", "ardisik": self._hl_ardisik})
                self.risk.bayrak("hl_okunamiyor", True)
                self.tg.uyar("hl_okunamiyor", tg.alarm("ALARM: HL okunamıyor", f"{self._hl_ardisik} ardışık HL okuması başarısız. Risk yerel defterle sürüyor; yeni pozisyon açılmıyor (okuma düzelince kalkar)."))
            return
        self._hl_ardisik = 0
        if self.risk.acilis_durdu.get("hl_okunamiyor"):
            self.risk.bayrak("hl_okunamiyor", False)
            self.kayit({"olay": "hl_okunuyor"})
            self.tg.duzeldi("hl_okunamiyor", tg.duzeldi_metni("HL okuması", "Yeni pozisyonlar yeniden serbest."))

    def _sahipsiz_tara(self, simdi: int) -> None:
        """2. denetim O-2 (K-70; her iki kip): defterde açık pozisyonu olup ne `saha.uyeler` ne `saha.inen`de olan adres ("sahipsiz": kozmetik adım istisnası / saha durumu kaybı sonrası trader'ı izlenmeyen pozisyon; olayı atlanır,
        senkron bakmaz). İlk görülmede alarm + kayıt; `canli_yetim_kapat_sn` (600 sn, K-68) KESİNTİSİZ sürerse pozisyonlar reduce-only kapatılır (kapanış kuyruğundaki / belirsiz emirli coinler hariç; kapanış tutmazsa
        mevcut kapanış kuyruğuna girer, her dakika emir yağmaz). Durum `motor.json`'da kalıcı; taramalar arası > 3 dk boşluk (yeniden başlatma) kesintiyi böler. DUR/DUR beklemesinde DUR zaten hepsini kapatır."""
        if self.risk.dur or self.dur_bekliyor:
            return
        kuyrukta = {tuple(k.split("|", 1)) for k in self.kapanis_kuyrugu}
        sahipsiz = {a: [c for c, p in cs.items() if abs(p.sz) > EPS] for a, cs in self.hesap.poz.items() if a not in self.saha.uyeler and a not in self.saha.inen}
        sahipsiz = {a: cs for a, cs in sahipsiz.items() if cs}
        for a in [a for a in self.sahipsiz_ilk if a not in sahipsiz]:
            ilk = self.sahipsiz_ilk.pop(a)
            self.kayit({"olay": "sahipsiz_bitti", "adres": a, "sure_sn": round((simdi - int(ilk.get("ms", simdi))) / 1000)})
        sinir_ms = float(self.rules["canli_yetim_kapat_sn"]) * 1000
        for a, coinler in sahipsiz.items():
            y = self.sahipsiz_ilk.get(a)
            if y is None or simdi - int(y.get("son", y.get("ms", simdi))) > self.SAHIPSIZ_TARAMA_KOPUK_MS:
                yeni = y is None
                self.sahipsiz_ilk[a] = {"ms": simdi, "son": simdi}
                if yeni:
                    self.kayit({"olay": "sahipsiz_pozisyon", "adres": a, "coinler": coinler[:10], "kapat_sn": sinir_ms / 1000})
                    self.tg.gonder(tg.alarm("ALARM: sahipsiz pozisyon", f"{tg.kisa(a)} adresi sahada/yedekte değil ama defterde {len(coinler)} açık pozisyonu var ({', '.join(coinler[:5])}).\n"
                                            f"{sinir_ms / 60000:g} dk içinde düzelmezse reduce-only kapatılacak."))
                continue
            y["son"] = simdi
            if simdi - int(y["ms"]) < sinir_ms:
                continue
            belirsiz, genel = self._belirsiz_coin_kumesi()
            hedef = [c for c in coinler if not genel and c not in belirsiz and (a, c) not in kuyrukta]
            if not hedef:
                continue
            kapanan = []
            for c in hedef:
                ok, _ = self._kapat_coin(a, c, "sahipsiz_pozisyon", simdi)
                if ok:
                    kapanan.append(c)
            self.kayit({"olay": "sahipsiz_kapat", "adres": a, "denenen": hedef, "kapanan": kapanan})
            self.tg.gonder(tg.alarm("ALARM: sahipsiz pozisyon kapatıldı" if len(kapanan) == len(hedef) else "ALARM: sahipsiz pozisyon kapanmadı", f"{tg.kisa(a)}: {len(kapanan)}/{len(hedef)} pozisyon kapatıldı"
                                    f"{'' if len(kapanan) == len(hedef) else '; kalanlar kapanış kuyruğunda yeniden denenecek'}."))

    def _kozmetik(self, ad: str, f: Callable[..., Any], *a: Any) -> None:
        """2. denetim O-2/D-5: pano/kayıt amaçlı (kozmetik) çağrı; istisnası koruyucu işlemleri (kapanış, saha kararları) kesmez: kayıt `risk_yan_adim_hata` ve sürer."""
        try:
            f(*a)
        except Exception as hata:                                                               # noqa: BLE001
            self._kayit_hata(ad, hata)

    def _kayit_hata(self, ad: str, hata: Exception) -> None:
        try:
            self.kayit({"olay": "risk_yan_adim_hata", "adim": ad, "tur": type(hata).__name__})
        except Exception:                                                                       # noqa: BLE001 - kayıt da çalışmıyorsa sessiz (asıl iş sürer)
            pass

    def _dur_kurtar(self, simdi: int) -> None:
        """Denetim-3 (O1): `risk.dur` açık ama `durum/DUR` hiç yazılmadı/görülmedi (kozmetik adım istisnası, DUR yazım hatası, çökme) → pozisyonlar açık kalırdı. DUR yeniden tetiklenir
        (yazım + reduce-only kapanış). DUR dosyası bir kez yazıldıysa (`dur_dosya`) ve operatör sildiyse DOKUNULMAZ (elle devam yolu). En çok 5 dk'da bir denenir."""
        r = self.risk
        if not r.dur or r.dur_dosya or self.dur_dosyasi.exists():
            if r.dur and self.dur_dosyasi.exists():
                r.dur_dosya = True
            return
        if not self._aralik_mi("dur_kurtarma", simdi, 300):
            return
        neden = r.dur_neden or "dur_kurtarma"
        self.kayit({"olay": "dur_kurtarma", "neden": neden, "dur_bekliyor": self.dur_bekliyor})
        self.tg.gonder(tg.alarm("ALARM: DUR kurtarılıyor", f"Risk kaydında durdurma ({tg.sade_ad(neden)}) açık ama durdurma kilidi yok (yazım hatası / çökme olabilir).\nDurdurma yeniden başlatılıyor: pozisyonlar kapatılacak.", "🛑"))
        self.dur_tetikle(neden)

    def _iz_suren_koruma(self, simdi: int) -> None:
        """K-73/8: YALNIZ sanal kip, `sanal_iz_suren`. Pozisyonun girişe göre (yön, mark) en yüksek kârı `Poz.zirve_kar`da tutulur (hesap.json, yeniden başlatmada kalır).
        Zirve >= `iz_basabas_oran` (%15) -> stop girişe (başa baş); zirve >= `iz_kilit_oran` (%30) -> stop `iz_kilit_seviye` (+%15) kâra. Kâr stopa inerse pozisyon kapanır (neden `iz_suren_koruma`); trader sahada kalır.
        Sabit kâr al YOK; K-62 felaket stopu (%20) aynen sürer."""
        if self.kip != "sanal" or not self.rules.get("sanal_iz_suren", False):
            return
        basabas, kilit, seviye = float(self.rules.get("iz_basabas_oran", 0.15)), float(self.rules.get("iz_kilit_oran", 0.30)), float(self.rules.get("iz_kilit_seviye", 0.15))
        degisti = False
        for adres in list(self.hesap.poz):
            for coin, p in list(self.hesap.poz.get(adres, {}).items()):
                mk = self.marks.get(coin)
                if not mk or not p.giris or not p.sz:
                    continue
                kar = (mk - p.giris) / p.giris if p.sz > 0 else (p.giris - mk) / p.giris
                if kar > p.zirve_kar:
                    p.zirve_kar, degisti = kar, True
                stop = seviye if p.zirve_kar >= kilit - 1e-12 else 0.0 if p.zirve_kar >= basabas - 1e-12 else None
                if stop is not None and kar <= stop + 1e-12:
                    ok, _ = self._kapat_coin(adres, coin, "iz_suren_koruma", simdi)
                    self.kayit({"olay": "iz_suren_koruma", "adres": adres, "coin": coin, "giris": p.giris, "mark": mk, "kar": kar, "zirve_kar": p.zirve_kar, "stop_kar": stop, "kapandi": bool(ok)})
        if degisti:
            self._hesap_yaz()                                    # zirve yeniden başlatmada kaybolmasın

    def _stop_orani(self, coin: str, uzun: bool, giris: float, ust: float, pay: float, kaldirac: float | None = None) -> float:
        """K-74 (taslak): `dinamik_stop` açıksa min(`ust`, tasfiye mesafesi − `pay`); kapalıysa (varsayılan) `ust` aynen. Azami kaldıraç: sanal defter tablosu, yoksa gerçek kip HL tablosu, yoksa 20 (formül yedeği)."""
        if not self.rules.get("dinamik_stop") or giris <= 0:
            return ust
        azami = self.hesap.maks_kaldirac.get(coin) or self._hl_maks_kaldirac.get(coin)
        return dinamik_stop_orani(uzun, giris, kaldirac or self.hesap.kaldirac, azami, ust, pay)

    def _felaket_stop(self, simdi: int) -> None:
        """K-62 felaket stopu: pozisyon ortalama girişten `canli_felaket_stop_oran` kadar aleyhe gittiyse (mark ile) o pozisyon kapanır. Trader sahada kalır (slot kuralı ayrıca işler).
        Gerçek kipte borsada duran tetik emri ayrıca gerekir (bot çökmesine karşı); bu, motor ayaktayken çalışan yazılım katmanıdır."""
        oran = float(self.rules.get("canli_felaket_stop_oran", 0) or 0)
        if oran <= 0:
            return
        for adres in list(self.hesap.poz):
            for coin, p in list(self.hesap.poz.get(adres, {}).items()):
                mk = self.marks.get(coin)
                if not mk or not p.giris or not p.sz:
                    continue
                aleyhe = (p.giris - mk) / p.giris if p.sz > 0 else (mk - p.giris) / p.giris
                oran_p = self._stop_orani(coin, p.sz > 0, p.giris, oran, 0.03, p.kaldirac)         # K-74: bayrak kapalıyken `oran` aynen
                if aleyhe >= oran_p - 1e-12:
                    neden_k = "tasfiye_koruma_stop" if oran_p < oran - 1e-9 else "felaket_stop"        # K-74: tasfiyeye göre daraltılmış stop ayrı neden (Telegram/pano'da açık)
                    ok, _ = self._kapat_coin(adres, coin, neden_k, simdi)
                    self.kayit({"olay": "felaket_stop", "adres": adres, "coin": coin, "giris": p.giris, "mark": mk, "aleyhe": aleyhe, "kapandi": bool(ok)})
                    self._kozmetik("donem_kilit", self.donem_kilit, "felaket_stop", simdi)          # D-5: kozmetik; istisnası aynı dakikadaki diğer stop ihlallerini ertelemez
                    self.tg.gonder(tg.alarm("ALARM: felaket stopu", f"{tg.kisa(adres)} {coin} pozisyonu girişten %{aleyhe * 100:.0f} aleyhe gitti, "
                                            f"{'kapatıldı' if ok else 'kapatılamadı (yeniden denenecek)'}.", "🛑"))

    def acik_emir_oku(self) -> list[dict] | None:
        """K-64 (ağ; kilitsiz): kendi HL hesabımızın tüm perp dex'lerdeki açık emirleri (`openOrders`). Hata: None (eşitleme kayıp/yetim taraması yapmaz)."""
        adres = os.environ.get("HL_HESAP_ADRESI", "")
        try:
            liste: list[dict] = []
            for dex in ["", *self._dexler()]:
                r = self.post({"type": "openOrders", "user": adres, **({"dex": dex} if dex else {})})
                if not isinstance(r, list):
                    raise ValueError("openOrders yanıtı geçersiz")
                liste += r
            return liste
        except Exception as hata:                          # noqa: BLE001
            self.kayit({"olay": "acik_emir_okuma_hata", "tur": type(hata).__name__})
            return None

    def _stop_kayip_teyit(self, coin: str, yerel_net: float) -> tuple[str, float | None]:
        """Denetim-1 (O2): borsa stopu açık emirlerde görünmüyor. Borsadaki net pozisyon aynı yönde ve (≥ %98) aynı miktarda duruyorsa "duruyor" (stop dışarıda iptal/sorunlu; pozisyon
        KAPATILMAZ); küçülmüş/kapanmış/ters → "kucuk" (mevcut tetiklendi akışı); okunamadı → "bilinmiyor" (kapatılmaz). Döner (durum, borsa_sz)."""
        try:
            hl = clearinghouse_pozisyonlari(self.post_hizli, os.environ.get("HL_HESAP_ADRESI", ""), self._dexler())
        except Exception as hata:                          # noqa: BLE001
            self.kayit({"olay": "borsa_stop_kayip_okuma_hata", "tur": type(hata).__name__, "coin": coin})
            return "bilinmiyor", None
        v = float(hl.get(coin, 0.0))
        if v * yerel_net > 0 and abs(v) >= 0.98 * abs(yerel_net):
            return "duruyor", v
        return "kucuk", v

    def borsa_stop_esitle(self, acik: list[dict] | None, simdi: int) -> None:
        """K-64: gerçek kipte borsada duran felaket stoplarını net pozisyonlarla eşitler. Kaybolan (tetiklenmiş) stopun coinindeki yerel pozisyonlar borsa teyitli
        kapanış yoluyla temizlenir (`_kapat_coin` → borsa 0 ise G-13 harici kapanış + defter düzeltmesi). Hata → kayıt + saatte bir alarm; motor durmaz."""
        if self.kip != "gercek" or not hasattr(self.yurutucu, "stop_koy"):
            return
        bs_oran = float(self.rules["canli_borsa_stop_oran"])
        oran_fn = (lambda c, uzun, giris: self._stop_orani(c, uzun, giris, bs_oran, 0.01)) if self.rules.get("dinamik_stop") else None     # K-74 (taslak): coin başına min(%22, tasfiye mesafesi − %1); bayrak kapalı → None (eski)
        hedef = borsa_stop.hedefler(self.hesap.poz, self.marks, bs_oran, float(self.rules.get("canli_min_nosyonel_usd", 10)), oran_fn)     # defter temelli (K-64)
        hedef.update(borsa_stop.yetim_hedefler(self.yetim_ilk, self.marks, float(self.rules["canli_borsa_stop_oran"]), float(self.rules.get("canli_min_nosyonel_usd", 10))))      # Denetim-5 (K-68): defter dışı fazla için SABİT (ilk görülen mark) referanslı ek stop
        olay = self.borsa_stop.esitle(hedef, acik, self.yurutucu)
        yeniden = False
        for c in olay["kayip"]:
            if borsa_stop.yetim_mi(c):                           # yetim stopu tetiklendi / dışarıda iptal: kapatma `_yetim_izle`nin işi; alarm + kayıt
                self.kayit({"olay": "borsa_stop_kayip", "coin": borsa_stop.coin_adi(c), "yetim": True})
                self.tg.gonder(tg.alarm("ALARM: yetim pozisyon stopu kayboldu", f"{borsa_stop.coin_adi(c)} için defter dışı fazla stopu açık emirlerde yok (tetiklenmiş olabilir). Yetim durumu mutabakatla yeniden değerlendirilir.", "🛑"))
                continue
            adresler = [a for a, cs in self.hesap.poz.items() if c in cs]
            self.kayit({"olay": "borsa_stop_kayip", "coin": c, "yerel_acik": bool(adresler)})
            if not adresler:                                      # pozisyon zaten kapalı: HL reduce-only stopu kendisi düşürmüş olabilir; alarm yok
                continue
            durum, hl_sz = self._stop_kayip_teyit(c, sum(self.hesap.poz[a][c].sz for a in adresler))
            if durum != "kucuk":                              # Denetim-1 (O2): borsada pozisyon HÂLÂ duruyor (ya da okunamadı) → KAPATMA; stop yeniden kurulur + alarm
                self.kayit({"olay": "borsa_stop_kayip_poz_duruyor" if durum == "duruyor" else "borsa_stop_kayip_teyitsiz", "coin": c, "hl_sz": hl_sz})
                self.tg.gonder(tg.alarm("ALARM: borsa stopu kayboldu, pozisyon borsada duruyor" if durum == "duruyor" else "ALARM: borsa stopu kayboldu, pozisyon okunamadı",
                                        f"{c} için borsadaki felaket stopu açık emirlerde yok; " + (f"borsada pozisyon hâlâ {hl_sz:g}. Kapatılmadı, stop yeniden kuruluyor." if durum == "duruyor"
                                                                                                    else "borsa pozisyonu okunamadığı için kapatılmadı; stop bir sonraki eşitlemede yeniden kurulacak."), "🛑"))
                yeniden = yeniden or durum == "duruyor"
                continue
            self.tg.gonder(tg.alarm("ALARM: borsa stopu tetiklendi / kayboldu", f"{c} için borsadaki felaket stopu açık emirlerde yok (tetiklenmiş olabilir).\n"
                                    "Pozisyon borsadan teyitle temizleniyor; stop yeniden kurulacak.", "🛑"))
            for adres in adresler:
                self._kapat_coin(adres, c, "borsa_stop", simdi)
        if yeniden:                                           # stopsuz an uzamasın: hemen yeniden kur (açık emir okuması yok → yalnız koy/iptal)
            ek = self.borsa_stop.esitle(hedef, None, self.yurutucu)
            for ad in ("konan", "hata"):
                olay[ad].extend(ek[ad])
        for ad in ("konan", "iptal", "yetim", "konan_belirsiz", "benimsenen"):
            for x in olay[ad]:
                self.kayit({"olay": f"borsa_stop_{ad}", **x})
        if olay["hata"]:
            self.kayit({"olay": "borsa_stop_hata", "hatalar": olay["hata"][:10]})
            if self._aralik_mi("borsa_stop_alarm", simdi, 3600):
                self.tg.gonder(tg.alarm("ALARM: borsa stopu kurulamadı", f"{len(olay['hata'])} stop işlemi başarısız ({olay['hata'][0].get('coin')}: {olay['hata'][0].get('neden') or olay['hata'][0].get('islem')}).\n"
                                        "Her dakika yeniden deneniyor; motor ayaktayken yazılım stopu (%20) çalışıyor."))
        self._stopsuz_denetle(hedef, simdi)

    def _stopsuz_denetle(self, hedef: dict[str, dict], simdi: int) -> None:
        """K-65 (kullanıcı kararı 11.11: acil durumda kapatma sistemde): stop beklenen coin `canli_borsa_stop_korumasiz_sn` boyunca borsada stopsuz kaldıysa
        o coindeki pozisyonlar kapatılır (`borsa_stop_korumasiz`) ve `canli_borsa_stop_ceza_sn` boyunca yeni açılış/artırma durur (`stop_korumasiz` bayrağı). Kapanış serbest."""
        bs_ = self.borsa_stop
        sinir_ms = float(self.rules["canli_borsa_stop_korumasiz_sn"]) * 1000
        stopsuz = {c for c in hedef if c not in bs_.stoplar and not borsa_stop.yetim_mi(c)}      # yetim stopunun kapatması `_yetim_izle` (K-68) ile; K-65 stopsuz sayacı yalnız defter pozisyonları için
        bs_.korumasiz = {c: t for c, t in bs_.korumasiz.items() if c in stopsuz}
        for c in stopsuz:
            bs_.korumasiz.setdefault(c, simdi)
        for c, ilk in sorted(bs_.korumasiz.items()):
            if simdi - ilk < sinir_ms:
                continue
            adresler = [a for a, cs in self.hesap.poz.items() if c in cs]
            dk = int((simdi - ilk) / 60000)
            self.kayit({"olay": "borsa_stop_korumasiz_kapat", "coin": c, "sure_dk": dk, "adres_sayisi": len(adresler)})
            self.tg.gonder(tg.alarm("ALARM: stopsuz pozisyon kapatıldı", f"{c} için borsa stopu {dk} dk kurulamadı; pozisyon otomatik kapatılıyor.\n"
                                    f"Yeni açılış {float(self.rules['canli_borsa_stop_ceza_sn']) / 3600:g} saat durduruldu (kapanışlar serbest).", "🛑"))
            del bs_.korumasiz[c]
            bs_.ceza_ms = simdi
            for adres in adresler:
                self._kapat_coin(adres, c, "borsa_stop_korumasiz", simdi)
        ceza = bs_.ceza_ms is not None and simdi - bs_.ceza_ms < float(self.rules["canli_borsa_stop_ceza_sn"]) * 1000
        self.risk.bayrak("stop_korumasiz", ceza)

    def hacim_oku(self) -> dict[str, float] | None:
        """K-62 (ağ; kilitsiz): `metaAndAssetCtxs` (ana dex + HIP-3 dex) coin başına 24 sa nosyonel hacim (`dayNtlVlm`, $). Hata: None (önceki değer kalır)."""
        hacim: dict[str, float] = {}
        try:
            for dex in ["", *self._dexler()]:
                meta, ctxs = self.post({"type": "metaAndAssetCtxs", **({"dex": dex} if dex else {})})[:2]
                for u, c in zip(meta["universe"], ctxs):
                    try:
                        hacim[str(u["name"])] = float(c["dayNtlVlm"])
                    except (KeyError, TypeError, ValueError):
                        continue
            return hacim
        except Exception as hata:                          # noqa: BLE001
            self.kayit({"olay": "hacim_okuma_hata", "tur": type(hata).__name__})
            return None

    def coin_hacmi(self, coin: str) -> float | None:
        """K-62: hacim verisi hiç yoksa None (sığ sınırı uygulanmaz); veri var ama coin yoksa 0 (sığ sayılır)."""
        return None if not self._coin_hacim else float(self._coin_hacim.get(coin, 0.0))

    def _anlik(self, simdi: int) -> None:
        self.karar_uygula(self.saha.anlik(simdi, lambda a: self.hesap.slot_ozsermaye(a, self.marks), self._son_kadro, slot_bas=self.hesap.slot_bas.get), simdi)
        self._inen_tavan(simdi)

    def _inen_nosyonel(self, adres: str) -> float:
        return sum(abs(p.sz) * (self.mark(c, p.giris) or p.giris) for c, p in self.hesap.poz.get(adres, {}).items())

    def _inen_tavan(self, simdi: int) -> None:
        """Fable denetimi 16.11 (açık 1/7): trader'a bırakılan (inen) pozisyonların toplam nosyoneli kasa × `canli_inen_tavan_oran`'ı aşarsa, slotuna göre EN ZARARDAKİ inen trader'ın
        pozisyonları kapatılır (tavan altına inene kadar)."""
        if not self.saha.haftalik:
            return
        tavan = float(self.rules["canli_inen_tavan_oran"]) * float(self.kasa)
        while self.saha.inen and sum(self._inen_nosyonel(a) for a in self.saha.inen) > tavan + 1e-9:
            def kz(a: str) -> float:
                ozs = self.hesap.slot_ozsermaye(a, self.marks)
                return (ozs if ozs is not None else 0.0) - float(self.hesap.slot_bas.get(a) or self.saha.slot)
            adres = min(self.saha.inen, key=kz)
            del self.saha.inen[adres]
            self.kayit({"olay": "inen_tavan_kapat", "adres": adres, "tavan_usd": tavan})
            self.karar_uygula([Karar("inen_kapat", adres, "inen_tavan")], simdi)

    def _inen_ters_kapat(self, adres: str, coin: str, yon: str, simdi: int) -> None:
        """Fable denetimi 16.11 (açık 2): sahadaki trader bir coinde açılış yaparken, aynı coinde TERS yönde yalnız INEN (trader'a bırakılmış) bir pozisyon varsa o inen pozisyon kapatılır;
        böylece K‑41 ters netleşme yeni kadronun açılışını engellemez."""
        if not self.saha.haftalik:
            return
        isaret = 1.0 if yon == "B" else -1.0
        for a in list(self.saha.inen):
            p = self.hesap.poz.get(a, {}).get(coin)
            if a != adres and p is not None and p.sz * isaret < -EPS:
                self.kayit({"olay": "inen_ters_kapat", "adres": a, "coin": coin, "acan": adres})
                self._kapat_coin(a, coin, "inen_ters", simdi)

    _son_kadro: dict | None = None
    _eksik_imza: tuple | None = None
    _kasa_uyari: float | None = None              # D-01: son uyarı verilen kadro kasası (aynı fark için tekrar uyarı yok)
    _coin_hacim: dict[str, float] = {}                    # K-62: coin → 24 sa nosyonel hacim ($); `dakika` saatte bir yeniler (örnek başına atanır)

    def _mutabakat_tut(self, coin: str | None, neden: str, simdi: int) -> None:
        """Denetim-4 (Kaçırılan-3): belirsiz emir çözümünde konan mutabakat bayrağı, `_mutabakat`ın her dakika yeniden hesabıyla (fark 10 $ eşiğinin altındaysa) sessizce silinmesin.
        Gerçek kipte not kaydedilir; ilgili coinde (coin yoksa tüm coinlerde) borsa = defter teyidi (fark ≤ `canli_kapanis_toz_usd`) gelene kadar bayrak kalır. Sanal kip: eski davranış (yalnız bayrak)."""
        self.risk.bayrak("mutabakat", True)
        if self.kip == "gercek":
            self.mutabakat_tutan[f"{neden}:{coin or '*'}"] = {"coin": coin, "neden": neden, "ms": simdi}

    def _mutabakat_tutan_sorunlar(self, bizim: dict[str, float], hl_poz: dict[str, float], simdi: int) -> list[dict]:
        """Teyit gelen notları siler (kayıt), kalanları `cozum_teyidi_bekliyor` sorunu olarak döner (bayrak kalkmaz)."""
        if not self.mutabakat_tutan:
            return []
        toz = float(self.rules["canli_kapanis_toz_usd"])

        def esit(coin: str) -> bool:
            fark = abs(float(hl_poz.get(coin, 0.0)) - float(bizim.get(coin, 0.0)))
            if fark < 1e-12:
                return True
            mk = self.marks.get(coin)
            return bool(mk) and fark * mk <= toz
        kalan: list[dict] = []
        for anahtar, n in list(self.mutabakat_tutan.items()):
            coin = n.get("coin")
            tamam = esit(coin) if coin else all(esit(c) for c in {*bizim, *hl_poz})
            if tamam:
                del self.mutabakat_tutan[anahtar]
                self.kayit({"olay": "mutabakat_not_temizlendi", "anahtar": anahtar, "coin": coin, "bekleme_dk": round((simdi - int(n.get("ms", simdi))) / 60000, 1)})
            else:
                kalan.append({"neden": "cozum_teyidi_bekliyor", "coin": coin, "not": n.get("neden"), "bizim": bizim.get(coin, 0.0) if coin else None, "hl": hl_poz.get(coin, 0.0) if coin else None})
        return kalan

    def _belirsiz_coin_kumesi(self) -> tuple[set[str], bool]:
        """Denetim-5 (K-68): belirsiz (sonucu bilinmeyen) emri ya da sonuçsuz niyeti olan coinler. Döner (coinler, genel): adres/coin bilgisi olmayan girdi varsa genel=True (hiçbir coin kapatılmaz).
        `_belirsiz_coinler`den farkı: `deneme` ≥ 5 olan belirsizler de sayılır (yetim kapatma kesin zemin ister)."""
        coinler: set[str] = set()
        genel = False
        for b in self.hesap.belirsiz.values():
            if b.get("coin"):
                coinler.add(str(b["coin"]))
            else:
                genel = True
        for n in self.niyet.sonucsuz():
            if n.get("coin"):
                coinler.add(str(n["coin"]))
            else:
                genel = True
        return coinler, genel

    def _yetim_izle(self, bizim: dict[str, float], hl_poz: dict[str, float], sorunlar: list[dict], simdi: int) -> None:
        """Denetim-5 / K-68 (kullanıcı kararı): defter dışı borsa fazlası (`poz_farki` sorunu olan coinde `_kirp(hl, hl − defter)` ≠ 0: borsada defterin karşılamadığı pay; `yetim` = defterde hiç olmayan coin,
        `fark` = aynı coinde borsa fazlası) `canli_yetim_kapat_sn` KESİNTİSİZ sürerse reduce-only, borsa teyitli kapatılır (`_borsa_yetim_kapat`, yalnız o coinler). Eşik geçtikten sonra her mutabakat turunda
        (dakikada bir) yeniden denenir. Coinde belirsiz emir / sonuçsuz niyet varken kapatılmaz. Durum (ilk görülme, o andaki mark, son fazla) `motor.json`'da kalıcıdır; mark stop referansıdır (`borsa_stop_esitle`).
        Tespitte ve kapatmada Telegram alarmı + kayıt. Yalnız gerçek kip (çağıran)."""
        aday = {s["coin"] for s in sorunlar if s.get("coin") and s.get("neden") in ("yetim", "fark", "mark_yok")}
        fazla: dict[str, float] = {}
        for coin in aday:
            f = self._kirp(float(hl_poz.get(coin, 0.0)), float(hl_poz.get(coin, 0.0)) - float(bizim.get(coin, 0.0)))
            if abs(f) > EPS:
                fazla[coin] = f
        for coin in [c for c in self.yetim_ilk if c not in fazla]:
            ilk = self.yetim_ilk.pop(coin)
            self.kayit({"olay": "yetim_bitti", "coin": coin, "sure_sn": round((simdi - int(ilk.get("ms", simdi))) / 1000)})
        for coin, f in fazla.items():
            y = self.yetim_ilk.get(coin)
            mk = self.mark(coin)
            if y is None:
                self.yetim_ilk[coin] = {"ms": simdi, "mark": mk or None, "sz": f}
                sn = float(self.rules["canli_yetim_kapat_sn"])
                self.kayit({"olay": "yetim_tespit", "coin": coin, "sz": f, "mark": mk, "kapat_sn": sn})
                self.tg.gonder(tg.alarm("ALARM: defter dışı borsa pozisyonu", f"{coin}: borsada defterin karşılamadığı {f:g} var (mark {mk if mk else 'yok'}).\n"
                                        f"Borsa stopu bu miktar için de kurulur; {sn / 60:g} dk içinde düzelmezse reduce-only kapatılacak. Yeni açılış durdu."))
            else:
                y["sz"] = f
                if not y.get("mark") and mk:
                    y["mark"] = mk                                    # ilk görülmede mark yoktuysa ilk bilinen mark (bir kez; sonra sabit)
        sinir_ms = float(self.rules["canli_yetim_kapat_sn"]) * 1000
        vadesi = {c for c, y in self.yetim_ilk.items() if simdi - int(y.get("ms", simdi)) >= sinir_ms}
        if not vadesi:
            return
        belirsiz, genel = self._belirsiz_coin_kumesi()
        hedef = {c for c in vadesi if not genel and c not in belirsiz}
        for c in sorted(vadesi - hedef):
            self.kayit({"olay": "yetim_kapat_ertelendi", "coin": c, "neden": "belirsiz_emir"})
        if not hedef:
            return
        kalan = self._borsa_yetim_kapat("yetim_sure", simdi, hedef)
        if kalan is None:
            self.kayit({"olay": "yetim_kapat_okunamadi", "coinler": sorted(hedef)})
            return
        kapanan = sorted(c for c in hedef if c not in kalan)
        for c in kapanan:
            self.yetim_ilk.pop(c, None)
        self.kayit({"olay": "yetim_kapat", "denenen": sorted(hedef), "kapanan": kapanan, "kalan": kalan})
        if kapanan:
            self.tg.gonder(tg.alarm("Defter dışı borsa pozisyonu kapatıldı", f"{', '.join(kapanan)}: {sinir_ms / 60000:g} dk düzelmediği için reduce-only kapatıldı (borsa teyitli).", "🛑"))
        if kalan and self._aralik_mi("yetim_kapat_alarm", simdi, 300):
            self.tg.gonder(tg.alarm("ALARM: defter dışı pozisyon kapanmadı", f"{', '.join(f'{c} {v:g}' for c, v in list(kalan.items())[:5])} kapatılamadı; her dakika yeniden deneniyor."))

    def _mutabakat(self, simdi: int, hl: tuple[dict[str, float], float] | None = None) -> None:
        """Gerçek kip: HL ↔ yerel defter. `hl` kilit DIŞINDA okunduysa `_hl_okuma_imza` (`dakika`) o andaki yerel pozisyonlardır; kilit altında defter farklıysa (arada dolum / kapanış) HL kilit altında
        YENİDEN okunur (aksi hâlde eski HL anlık görüntüsü yeni defterle karşılaştırılıp sahte mutabakat alarmı + açılış durması olurdu)."""
        if not self._aralik_mi("mutabakat", simdi, float(self.rules["canli_mutabakat_sn"])):
            return
        imza, self._hl_okuma_imza = self._hl_okuma_imza, None
        if self.kip == "gercek":
            if hl is not None and imza is not None and imza != self._poz_imza():
                self.kayit({"olay": "mutabakat_yeniden_okuma"})
                hl = self.hl_oku(hizli=True)
                if hl is None:
                    return
            hl = hl or self.hl_oku(hizli=True)
            if hl is None:
                return
            hl_poz, hl_deger = hl
            hl_gecerli = self.hl_uygula(hl_deger, simdi, self._hl_okuma_ms(hl, simdi))
            bizim: dict[str, float] = {}
            for coinler in self.hesap.poz.values():
                for c, p in coinler.items():
                    bizim[c] = bizim.get(c, 0.0) + p.sz
            sorunlar = poz_farki(bizim, hl_poz, self.marks, self.kasa, float(self.rules["canli_mutabakat_oran"]))
            if not hl_gecerli:                                                                 # Denetim-8 (D3): geçersiz HL değeri → özsermaye karşılaştırması yapılamaz (sorun + ayrı `hl_deger` bayrağı)
                sorunlar = [*sorunlar, {"neden": "hl_deger_gecersiz"}]
            elif not self._ofset_dogrulanmadi:                                                   # K-1: ofset doğrulanmadıysa özsermaye karşılaştırması anlamsız (`ofset` bayrağı açılışı zaten kapatır)
                fark = abs((hl_deger - (self.hl_ofset or 0.0)) - self.yerel_ozsermaye())          # yerel defter ↔ HL özsermaye farkı (K‑37 §2)
                if fark > self.kasa * float(self.rules["canli_mutabakat_oran"]):
                    sorunlar = [*sorunlar, {"neden": "ozsermaye_farki", "fark_usd": fark}]
            if self._hl_sicrama:
                sorunlar = [*sorunlar, {"neden": "hl_sicrama"}]
            sorunlar = [*sorunlar, *self._mutabakat_tutan_sorunlar(bizim, hl_poz, simdi)]
            eski = sorted({c for cs in self.hesap.poz.values() for c in cs if not self.mark_taze_mi(c, simdi)})          # Denetim-6 (O5): açık coinde eski mark → yazılım stopu / tavan / boyut bayat fiyatla çalışırdı; açılış durur
            if eski:
                sorunlar = [*sorunlar, {"neden": "mark_eski", "coinler": eski[:10]}]
            self._yetim_izle(bizim, hl_poz, sorunlar, simdi)
        else:
            sorunlar = sanal_tutarlilik(self.hesap, self.marks, self.mark_ms, simdi, float(self.rules["canli_mark_stale_sn"]))
        onceki = bool(self.risk.acilis_durdu.get("mutabakat"))
        self._mutabakat_tamam_ms = simdi
        self.risk.bayrak("mutabakat", bool(sorunlar))
        if sorunlar and not onceki:
            self.kayit({"olay": "mutabakat_alarm", "sorunlar": sorunlar[:10]})
            self.tg.gonder(tg.alarm("ALARM: kayıtlar uyuşmuyor (mutabakat)", f"{len(sorunlar)} sorun bulundu ({tg.sade_ad(sorunlar[0].get('neden'))}).\nYeni pozisyon açılmıyor."))
        elif not sorunlar and onceki:
            self.kayit({"olay": "mutabakat_duzeldi"})
            self.tg.gonder(tg.duzeldi_metni("kayıtlar uyuşuyor (mutabakat)", "Yeni pozisyonlar yeniden serbest."), "INFO")

    def _kadro_al(self, simdi: int) -> tuple[bool, dict | None]:
        """Aralık dolduysa `kadro.json` okunur (ağ; kilitsiz). Döner (okundu, kadro|None)."""
        if not self._aralik_mi("kadro", simdi, float(self.rules["canli_kadro_aralik_sn"])):
            return False, None
        try:
            return True, self.kadro_oku()
        except Exception as hata:                          # noqa: BLE001
            self.kayit({"olay": "kadro_okuma_hata", "tur": type(hata).__name__})
            return True, None

    def _kadro_uygula(self, okuma: tuple[bool, dict | None], simdi: int) -> None:
        okundu, kadro = okuma
        if not okundu:
            return
        gerekli = self.radar_surum_gerekli
        if gerekli and kadro is not None and str(kadro.get("radar_surum")) != str(gerekli):
            # K-54 (kullanıcı kararı 09.11): yeni seçim yapısı (radar_surum = gerekli) yayımlanana kadar eski yapının kadrosu UYGULANMAZ: saha boş, kasa nakitte, günde bir kayıt + bilgi
            if self.saha.alarm_gunu != gun(simdi):
                self.saha.alarm_gunu = gun(simdi)
                self.kayit({"olay": "kadro_surum_bekleniyor", "gerekli": str(gerekli), "gelen": kadro.get("radar_surum")})
                self.tg.gonder(tg.alarm("BİLGİ: yeni seçim yapısı bekleniyor", f"Gelen kadro sürümü {kadro.get('radar_surum') or 'yok'}, gereken {gerekli}. Trader alınmıyor; kasa nakitte.", "ℹ️"))
            kadro = None
            if self._son_kadro is not None and str(self._son_kadro.get("radar_surum")) != str(gerekli):
                self._son_kadro = None
            if self._son_kadro is None:
                return
        if kadro is not None:
            self._son_kadro = kadro
            try:                                               # yalnız bilgi: günün ilk11 form puanı (secim_gercek raporu için)
                secim_gercek.kadro_kaydet(self, kadro, simdi)
            except Exception as hata:                          # noqa: BLE001
                self.kayit({"olay": "secim_gercek_hata", "tur": type(hata).__name__})
            self._kadro_kasa_denetle(kadro, simdi)
        kararlar, durum = self.saha.degerlendir(self._son_kadro, simdi)
        eksik = self.saha.eksik if durum == "ok" else None
        imza = (self.saha.son_kosu_ms, eksik["saha"]) if eksik else None
        if eksik and imza != self._eksik_imza:                 # saha hep dolu (14.11): uygun aday kalmadı → kayıt (kadro koşusu + doluluk başına bir kez); pano "saha x/11, uygun aday yok"
            self.kayit({"olay": "saha_eksik", **eksik})
        self._eksik_imza = imza
        if durum != "ok":
            self.kayit({"olay": "kadro_" + durum})
            if self.saha.alarm_gunu != gun(simdi):
                self.saha.alarm_gunu = gun(simdi)
                self.tg.gonder(tg.alarm(f"ALARM: {durum}", "Takip edilen trader listesi olduğu gibi kalır, yeni trader girmez."))
        self.karar_uygula(kararlar, simdi)

    def _kadro_kasa_denetle(self, kadro: dict, simdi: int | None = None) -> None:
        """D-01 (14.11 denetim): kadro.json `kasa_usd` (radar oynatma kasası, `radar_kasa_usd`) motorun kasasından farklıysa seçim başka ölçekte yapılmıştır (ör. 1.000 $'da küçük
        açılışlar atlanır, 10.000 $'da açılır). YALNIZ bilgi: farklı her kasa değeri için bir kez kayıt + uyarı; motor durmaz, kadro yine uygulanır.
        Pano 14.11: yalnız GÜNCEL kadro için (taze: `canli_kadro_eski_saat` içinde VE koşusu dönem başından sonra); dönem öncesi / bayat kadro uyarı üretmez (yeni radar koşusu beklenir)."""
        simdi = self.saat_ms() if simdi is None else simdi
        bas = donem_ms(self.donem)
        if not kadro_taze_mi(kadro, simdi, self.rules)[0] or (bas is not None and int(kadro.get("kosu_ms") or 0) < bas):
            return
        k = kadro.get("kasa_usd")
        try:
            k = float(k) if k is not None else None
        except (TypeError, ValueError):
            k = None
        if k is None or abs(k - float(self.kasa)) <= 0.5 or self._kasa_uyari == k:
            return
        self._kasa_uyari = k
        self.kayit({"olay": "kadro_kasa_farkli", "kadro_kasa_usd": k, "motor_kasa_usd": float(self.kasa)})
        self.tg.gonder(tg.alarm("UYARI: kadro kasası farklı", f"Radar kadrosu {tg.tr_sayi(k, 0)} $ kasa ölçeğinde seçildi; motor kasası {tg.tr_sayi(float(self.kasa), 0)} $.\n"
                                "Kadro uygulanıyor, durdurma yok.", "⚠️", senden="Bana haber ver, ayarları eşitleyelim."))

    def _kadro(self, simdi: int) -> None:
        self._kadro_uygula(self._kadro_al(simdi), simdi)

    def _komutlar(self, komutlar: list[str]) -> None:
        """Telegram komutları. G-16: bitince (hata olsa da) offset kalıcı olur (`tg.onayla`); öncesinde motor.json partiden önceki offset'i taşır."""
        try:
            self._komutlari_yurut(komutlar)
        finally:
            self.tg.onayla()

    def ajan_suresi_oku(self, simdi: int) -> dict | None:
        """G-19 (ağ, kilitsiz): yalnız GERÇEK kipte, günde bir (`canli_ajan_kontrol_sn`) API cüzdanı `validUntil` okuması. Sanal kipte None."""
        if self.kip != "gercek" or not self._aralik_mi("ajan_suresi", simdi, float(self.rules.get("canli_ajan_kontrol_sn", 86400))):
            return None
        return ajan_bitis_oku(self.post, dict(os.environ), getattr(self, "ajan_turet", None))

    def ajan_suresi_uygula(self, okuma: dict | None, simdi: int) -> None:
        """G-19: bitişe `canli_ajan_uyari_gun` (7) gün ya da daha az kaldıysa (ya da cüzdan HL'de artık agent değilse) ALARM; her okumada kayıt. Süre dolunca her emir — kapanışlar da — reddedilir."""
        if okuma is None:
            return
        self.kayit({"olay": "ajan_suresi", **okuma})
        esik_gun = float(self.rules.get("canli_ajan_uyari_gun", 7))
        if okuma.get("durum") == "bulundu" and okuma.get("valid_until") is not None:
            kalan_gun = (int(okuma["valid_until"]) - simdi) / 86_400_000
            if kalan_gun <= esik_gun:
                tarih = datetime.fromtimestamp(int(okuma["valid_until"]) / 1000, UTC).strftime("%d.%m.%Y %H:%M UTC")
                durum = "süresi DOLDU" if kalan_gun <= 0 else f"süresi {kalan_gun:.1f} gün sonra bitiyor"
                self.tg.uyar("api_cuzdani_doldu" if kalan_gun <= 0 else "api_cuzdani_yakin", tg.alarm("ALARM: API cüzdanı süresi", f"HL API cüzdanının {durum} ({tarih}).\nSüre dolunca her emir (kapanışlar da) reddedilir.", senden="Bana haber ver; yeni anahtarı birlikte oluşturalım."))
        elif okuma.get("durum") == "listede_yok" and not okuma.get("agent_rol"):
            self.tg.uyar("api_cuzdani_yok", tg.alarm("ALARM: API cüzdanı HL'de yok", "API cüzdanı HL listesinde bulunamadı (süresi dolmuş ya da iptal edilmiş olabilir). Emirler reddedilir.", senden="Bana haber ver; acil durumda Hyperliquid sitesinden pozisyonları elle kapatabilirsin."))

    def _komutlari_yurut(self, komutlar: list[str]) -> None:
        """Standart komut adları (`tg.KOMUTLAR`); riskli olanlar (/durdur /devam /hepsini_kapat) buraya YALNIZ iki adımlı onaydan sonra gelir (`tg.komutlari_al`). Eski adlar eş ad."""
        for k in komutlar:
            k = tg.ESKI_AD.get(k, k)
            if k in tg.IKI_ADIMLI:
                self.kayit({"olay": "komut_yurutuldu", "komut": k})            # denetim izi: onaylanan komutun uygulanışı
            if k == "/hepsini_kapat":                                          # eski /kapat: tüm pozisyonları kapat, motor durur (DUR dosyası)
                self.tg.gonder(tg.msg_kapat_alindi(self.kip))                  # G-16: anında alındı yanıtı (kapanış sonucu ayrı mesajla)
                self.dur_tetikle("komut")
            elif k == "/durdur":                                               # eski /dur: yalnız yeni giriş/artırma durur; çıkış/azaltma serbest, pozisyonlar trader'ı izlemeye devam eder
                self._duraklat(True)
            elif k == "/devam":
                self._duraklat(False)
            elif k == "/durum":
                self.tg.gonder(self.durum_metni())
            elif k == "/rapor":                                                # günlük raporu hemen gönder (özet durumunu/sayaçlarını DEĞİŞTİRMEZ)
                self.tg.gonder(self._gunluk_metin())

    def _duraklat(self, ac: bool) -> None:
        """Elle duraklatma (`risk.acilis_durdu['elle_dur']`; kalıcı: `risk.json`). Kapanış/azaltma `acilis_izni`nden geçmediği için DURAKLATMADAN etkilenmez."""
        if not ac and self.risk.dur:
            self._bot_durdu_bildir("elle kapatıldı (/hepsini_kapat); /devam bunu açmaz", self.acik_poz_sayisi(), calisiyor=False)
            return
        self.risk.bayrak("elle_dur", ac)
        self.kayit({"olay": "elle_dur" if ac else "elle_devam"})
        self.tg.gonder(tg.alarm("Yeni işlemler duraklatıldı", "Yeni pozisyon açılmaz, artırılmaz; açık pozisyonlar izlenmeye devam eder.", "⏸️", senden="Açmak istediğinde /devam yaz (kod ister).") if ac
                       else tg.alarm("Duraklatma kaldırıldı", self._devam_govde(), "▶️", senden=None))
        self.durum_yaz()

    def _devam_govde(self) -> str:
        """`/devam` yanıtı: başka bir açılış engeli (günlük kayıp, mutabakat, kasa sınırı, kapanış eksik...) sürüyorsa yeni işlemlerin hâlâ KAPALI olduğunu söyler (yanıltmaz)."""
        diger = sorted(k for k, v in self.risk.acilis_durdu.items() if v and k != "elle_dur")
        return "Motor normal çalışıyor." if not diger else f"Duraklatma kalktı ama yeni işlemler hâlâ kapalı: {', '.join(diger)}."

    def durum_metni(self) -> str:
        oz = self.ozsermaye()
        return tg.msg_durum(self.kip, oz, self.kasa, len(self.saha.uyeler), self.saha.n, len(self.saha.inen), sum(len(c) for c in self.hesap.poz.values()), self.sayac["emir"], bool(self.risk.dur), False, self.risk_bayraklari())

    def risk_bayraklari(self) -> list[str]:
        """`/durum` için etkin risk bayrakları: `acilis_durdu` içinde açık olanlar + süren patlama freni (`fren`)."""
        b = sorted(k for k, v in self.risk.acilis_durdu.items() if v)
        if any(bitis > self.saat_ms() for bitis in self.risk.fren_bitis.values()):
            b.append("fren")
        return b

    def pano_ek(self) -> dict[str, Any]:
        """`ozet.json`a rapor (`pano/OZET.md`, T6 §3) için eklenen alanlar: açık pozisyonlar (mark'lı; K/Z = sz × (mark − giriş)) ve REST istek / 429 sayaçları. Yeni hesap değil: defter + mark biçimi."""
        acik = []
        for adres, coinler in self.hesap.poz.items():
            for coin, p in coinler.items():
                mk = self.marks.get(coin) or p.giris
                acik.append({"adres": adres, "coin": coin, "sz": p.sz, "giris": p.giris, "mark": mk, "usd": abs(p.sz) * mk, "kz_usd": p.sz * (mk - p.giris)})
        stats = getattr(self.post, "stats", None) or {}
        return {"acik": acik, "rest_istek": stats.get("istek"), "rest_429": stats.get("429"), "ogrenme": self.ogrenme.pano(), "duygu": haber.duygu_ozet(self.haber_anlik, self.saat_ms())}

    def _gunluk_metin(self) -> str:
        """Günlük rapor metni (`/rapor` ve zamanlı özet ortak; durum değiştirmez)."""
        oz = self.ozsermaye()
        return tg.msg_gunluk(self.kip, self.kasa, oz, self._ozet_oz if self._ozet_oz is not None else self.kasa, self._ozet_emir, len(self.saha.uyeler), self.saha.n,
                             self.pano_ek()["acik"], self.hesap.funding_toplam() if self.kip == "sanal" else None, self.karsi_olgu_gun or None, gunluk_ozet.gunluk_etki(self),
                             dur=bool(self.risk.dur), bayraklar=self.risk_bayraklari(), saglik=self._gunluk_saglik(),
                             kopya_fark=(sum(self._kopya_fark) / len(self._kopya_fark)) if self._kopya_fark else None, gecikme_sn=(sum(self._gecikme) / len(self._gecikme)) if self._gecikme else None,
                             artir=self._say_gun["artir"], azalt=self._say_gun["azalt"], guncelleme=gunluk_ozet.guncelleme_bugun())

    def _gunluk_saglik(self) -> list[str]:
        """Günlük raporun sağlık satırı için YALNIZ sorunlar (boşsa satır çıkmaz): bu oturumdaki Telegram gönderim hataları, borsa 429 sınırı."""
        sorunlar = []
        if self.tg.hata_sayisi:
            sorunlar.append(f"Telegram gönderim hatası {self.tg.hata_sayisi}")
        if (r429 := self.pano_ek()["rest_429"]):
            sorunlar.append(f"borsa istek sınırı (429) {r429}")
        return sorunlar

    def _gunluk_ozet(self, simdi: int) -> None:
        d = datetime.fromtimestamp(simdi / 1000, UTC)
        if d.hour < int(self.rules["canli_ozet_saat_utc"]) or self._ozet_gunu == d.date().isoformat():
            return
        self._ozet_gunu = d.date().isoformat()
        oz = self.ozsermaye()
        self.tg.gonder(self._gunluk_metin())
        self.karsi_olgu_gun = {}
        self._ozet_oz, self._ozet_emir = oz, 0
        self._kopya_fark, self._gecikme, self._say_gun = [], [], {"ac": 0, "artir": 0, "azalt": 0, "kapat": 0}

    def haftalik_metin(self) -> str:
        """Haftalık özet (yalnız rapor): hafta K/Z, BTC kıyası, emir sayısı, slot K/Z'ye göre en iyi/en kötü trader (şu anki slotta; slot girişinden beri, ücret/funding dahil)."""
        oz, btc = self.ozsermaye(), self.marks.get("BTC")
        taban = self._hafta_taban or {}
        slotlar = []
        for adres in self.saha.uyeler:
            so = self.hesap.slot_ozsermaye(adres, self.marks)
            if so is not None:
                slotlar.append((adres, so - self.hesap.slot_bas[adres]))
        simdi = self.saat_ms()
        try:                                                                  # yalnız bilgi: rejim satırı hata verirse haftalık özet yine gider
            rejim = rejim_sonuc.topla(rejim_sonuc.kayitlari_oku(Path(self.kayit.dizin), simdi), simdi)["rejim_1d"]
        except Exception:                                                     # noqa: BLE001
            rejim = None
        return tg.msg_haftalik(self.kip, self.kasa, oz, taban.get("oz"), btc, taban.get("btc"), self.sayac["emir"] - int(taban.get("emir", 0)), slotlar, rejim=rejim, acik_poz=self.acik_poz_sayisi())

    def _haftalik_ozet(self, simdi: int) -> None:
        d = datetime.fromtimestamp(simdi / 1000, UTC)
        if d.weekday() != 6 or (d.hour, d.minute) < (18, 10) or self._hafta_gunu == d.date().isoformat():
            return
        self._hafta_gunu = d.date().isoformat()
        self.tg.gonder(self.haftalik_metin())
        self._hafta_taban = {"oz": self.ozsermaye(), "btc": self.marks.get("BTC"), "emir": self.sayac["emir"]}

    # ------------------------------------------------------------------ özet
    def ozet(self) -> dict[str, Any]:
        ort = lambda x: (sum(x) / len(x)) if x else None            # noqa: E731
        simdi = self.saat_ms()
        oz = self.ozsermaye()
        return {"kip": self.kip, "vardiya": self.vardiya_id, "sure_dk": (simdi - self.baslama_ms) / DAKIKA, "kasa_usd": self.kasa, "ozsermaye_usd": oz, "getiri": oz / self.kasa - 1,
                **self.btc_kiyas(oz / self.kasa - 1),
                "saha": len(self.saha.uyeler), "saha_n": self.saha.n, "inen": len(self.saha.inen), "saha_eksik_neden": (self.saha.eksik or {}).get("neden"),
                "r1_gecen": (self._son_kadro or {}).get("gecti_sayisi"), "slot_usd": self.saha.slot, "emir": dict(self.sayac),
                "ortalama_kayma_trader": ort(self.kayma_trader), "ortalama_kayma_ref": ort(self.kayma_ref), "kayma_n": len(self.kayma_trader), "acik_pozisyon": sum(len(c) for c in self.hesap.poz.values()),
                "brut_usd": self.hesap.brut_toplam(self.marks), "tasfiye": len(self.hesap.tasfiyeler), "dur": self.risk.dur, "kayit_sayac": dict(self.kayit.sayac), "telegram_hata": self.tg.hata_sayisi,
                "kor_kirpildi": len(self.kor_kirpildi), "neden_say": dict(sorted(self.neden_say.items())), "slot_tavani": self.neden_say.get("slot_tavani", 0),
                "marj_yok": self.neden_say.get("marj_yok", 0), "uyeler": sorted(self.saha.uyeler),
                "gec_acilis": self.sayac["gec_acilis"], "kapanis_eksik": self.sayac["kapanis_eksik"], "kapanis_kuyrugu": len(self.kapanis_kuyrugu), "min_nosyonel": self.sayac["min_nosyonel"],
                "funding_usd": self.hesap.funding_toplam(), "funding_gercek_usd": self.funding_gercek_usd, "ucret_gercek_usd": self.ucret_gercek_usd, "ucret_tahmin_say": self.ucret_tahmin_say, "funding_oran_yok": self.sayac["funding_oran_yok"], "kuyruk_gecikme_ms": self.gecikme_ozeti(), "en_buyuk_emir": dict(self.en_buyuk_emir),
                "min_emir_say": {k: v for k, v in sorted(self.neden_say.items()) if k.startswith("min_emir")},
                "ters_netlesme": self.neden_say.get("ters_netlesme", 0),
                "spot_atlandi": self.neden_say.get("spot_atlandi", 0), "hip3_atlandi": self.neden_say.get("hip3_atlandi", 0),
                "trader_atlanan": {k: dict(sorted(v.items())) for k, v in self.atlanan_trader.items()}}

    def gecikme_ozeti(self) -> dict[str, float | int | None]:
        g = sorted(self.kuyruk_gecikme)
        return {"n": len(g), "p50": g[len(g) // 2] if g else None, "max": g[-1] if g else None}

    # ------------------------------------------------------------------ açılış
    def kip_uyumu_denetle(self) -> None:
        """G5: durum dizinindeki kayıtlı kip ile geçerli kip farklıysa BAŞLAMAZ. Gerçek kipte ayarlı kasa değiştiyse yalnız açık pozisyon yokken kabul (`kasa_degisti` kaydı).
        Sanal kipte `--sanal-kasa-usd` ile (kaynak "arg") kayıtlı kasa farklıysa ya da bilinmiyorsa BAŞLAMAZ (ör. 300 $ koşusu 1.000 $ serisinin durum dizinine yazamaz). Kaynak yaml iken davranış değişmez."""
        if not self._durum_var:
            return                                                                              # boş dizin: serbest
        neden = None
        if self._kayitli_kip != self.kip:
            neden = ("sanal durum dizininde gerçek kip açılmaz" if self.kip == "gercek" else "gerçek durum dizininde sanal kip açılmaz")
        elif self.kip == "sanal" and self.rules.get("canli_kasa_kaynagi") == "arg" and (self._kayitli_kasa_ayar is None or abs(float(self._kayitli_kasa_ayar) - self.kasa_ayar) > 1e-9):
            eski = "bilinmiyor" if self._kayitli_kasa_ayar is None else f"{float(self._kayitli_kasa_ayar):g} $"
            neden = f"sanal kasa {self.kasa_ayar:g} $ (--sanal-kasa-usd) durum dizinindeki kasa ({eski}) ile uyuşmuyor: ayrı durum dizini / veri dalı gerekli"
        elif self.kip == "gercek" and self._kayitli_kasa_ayar is not None and abs(float(self._kayitli_kasa_ayar) - self.kasa_ayar) > 1e-9:
            if any(self.hesap.poz.values()):
                neden = f"kasa ayarı değişti ({float(self._kayitli_kasa_ayar):g} → {self.kasa_ayar:g} $) ama açık pozisyon var: önce pozisyonlar kapatılmalı"
            else:
                self.kayit({"olay": "kasa_degisti", "eski_usd": float(self._kayitli_kasa_ayar), "yeni_usd": self.kasa_ayar, "vardiya": self.vardiya_id})
        if neden:
            self.kayit({"olay": "vardiya_baslamadi", "neden": neden, "vardiya": self.vardiya_id})
            raise KipHatasi(neden)

    def baslat(self) -> None:
        """Açılış: kip/kasa uyumu (G5); DUR varsa BAŞLAMAZ; kasa sınırı; kadro ilk okuması (saha kurulumu); saha üyelerinin pozisyon/hesap okuması; markları al."""
        self.kip_uyumu_denetle()
        if self.durum_bozuk:                                                                     # Denetim-2: sanal kipte bozuk durum dosyası → kâğıt sonuçlar sessizce sıfırlanmaz: kayıt + alarm
            self.kayit({"olay": "durum_bozuk", "dosyalar": list(self.durum_bozuk), "kip": self.kip})
            self.tg.gonder(tg.alarm("ALARM: durum dosyası bozuk", f"{', '.join(self.durum_bozuk)} okunamadı; bozuk kopya '.bozuk' olarak saklandı, ilgili durum SIFIRDAN başladı.\n"
                                    "Sanal kip: motor sürüyor; veri dalındaki durumu kontrol edin."))
        if self._donem_eski is not None:
            e = self._donem_eski
            self.kayit({"olay": "donem_yenilendi", "eski_kasa_usd": e["kasa_usd"], "yeni_kasa_usd": self.kasa, "eski_ozsermaye": e["ozsermaye"], "ozsermaye": self.hesap.ozsermaye({}),
                        "kapanmis_net": self.hesap.kapanmis_net, "slot_usd": self.saha.slot, "uye": len(e["slot_bas"])})
        if self.dur_dosyasi.exists() and self.risk.dur:
            self.risk.dur_dosya = True
        if not self.dur_dosyasi.exists() and self.risk.dur and self.kip == "gercek" and not self.risk.dur_dosya:
            # Denetim-3: DUR dosyası HİÇ yazılmamış (kozmetik adım istisnası / yazım hatası / çökme) — operatör silmedi. Sessiz sıfırlama (zirve de sıfırlanır) DUR'u kaybettirirdi:
            # DUR korunur, ilk risk adımında `_dur_kurtar` yeniden tetikler.
            self.kayit({"olay": "dur_korundu", "neden": self.risk.dur_neden, "gerekce": "DUR dosyası hiç yazılmamış; risk.dur korunuyor"})
            self.tg.gonder(tg.alarm("ALARM: DUR korunuyor", f"Risk kaydında durdurma ({tg.sade_ad(self.risk.dur_neden)}) açık ama durdurma kilidi hiç yazılmamış; sıfırlanmadı.\nİlk risk adımında pozisyonlar kapatılacak.", "🛑"))
        elif not self.dur_dosyasi.exists() and self.risk.dur:                                    # DUR dosyası tek yetkili: dosya yoksa risk.json'daki bayat dur sıfırlanır
            self.kayit({"olay": "dur_sifirlandi", "neden": self.risk.dur_neden, "gerekce": "DUR dosyası yok"})
            self.risk.dur, self.risk.dur_neden, self.risk.dur_dosya = False, None, False
            eski = self.risk.zirve_yenile(self.yerel_ozsermaye())                               # S-2: operatör DUR'u silip yeniden başlattı → zirve GÜNCEL özsermayeye (yoksa 60 sn'de yeniden DUR)
            self._zirve_yenile = True                                                            # gerçek kipte ilk risk adımında HL temelli özsermayeyle bir kez daha kurulur
            self.kayit({"olay": "zirve_yenilendi", "eski_zirve": eski, "yeni_zirve": self.risk.zirve, "gerekce": "dur_sonrasi_yeniden_baslatma"})
        isaret = self.dur_dosyasi.parent / "tg_bot_durdu"
        if isaret.exists() and not self.risk.dur and not self.dur_dosyasi.exists():                 # bot durmuştu, yeniden çalışıyor: TEK "Düzeldi" (yetişme sonrası `kesinti_duzeldi_bildir`)
            try:
                bas = float((isaret.read_text() or "0").strip().split()[0])
            except (OSError, ValueError, IndexError):
                bas = 0.0
            self._kesinti = {"sn": max(0.0, time.time() - bas) if bas > 1e9 else 0.0}
            for ad in ("tg_bot_durdu", "tg_bot_durdu_2"):
                try:
                    (self.dur_dosyasi.parent / ad).unlink()
                except OSError:
                    pass
        dur_yarim: dict | None = None
        if self.dur_dosyasi.exists():
            dur = _oku(self.dur_dosyasi) or {}
            borsa_acik: bool | None = None
            if dur.get("kapanis_bekliyor") and not any(self.hesap.poz.values()) and self.kip == "gercek":
                borsa_acik = self._borsa_acik_mi()                                               # Y-1: defter boş ama borsada açık (defter dışı) pozisyon kalmış olabilir
            bekliyor = bool(dur.get("kapanis_bekliyor")) and (any(self.hesap.poz.values()) or (self.kip == "gercek" and borsa_acik is not False))     # borsa okunamadı → kapanış modu (düz teyidi `_dur_bitir_mi`)
            if not bekliyor:
                raise KipHatasi("DUR dosyası var: elle silinmeden yeniden açılmaz")
            self.risk.dur_ver(dur.get("neden", "dur"))                                          # DUR yarım kaldı (pozisyon açıkta): yalnız kapanış modunda başla
            self.dur_bekliyor = True
            dur_yarim = {"neden": str(dur.get("neden", "dur")), "borsa_acik": borsa_acik}
        for adres in self.saha.gecis_silinen:                                                    # K‑39 tek seferlik geçiş: 05.11'de aynı gün ikinci kadro yüzünden verilen bekleme silindi
            self.kayit({"olay": "bekleme_silindi", "adres": adres, "neden": "K-39"})
        self.saha.gecis_silinen = []
        if self.kasa > kasa_ust(self.rules, self.kip) + 1e-9:                                    # gerçek kip 1.000 $ (AGENTS.md), sanal kip K-66 sanal sınırı
            raise KipHatasi(f"kasa {self.kasa} $ > sınır {kasa_ust(self.rules, self.kip):g} $ ({self.kip} kip; AGENTS.md)")
        self.kilit_al()
        simdi = self.saat_ms()
        if self.kapanis_modu:
            self.risk.bayrak("kapanis_modu", True)                 # D-11: `acilis_izni` her yeni açılışı/artırmayı reddeder; kapanış/azaltma buradan geçmez
            self.kayit({"olay": "kapanis_modu", "kasa": self.kasa})
            self.tg.gonder(tg.alarm("ALARM: yalnız kapanış modu", f"HL hesap değeri sınırı ({hl_deger_ust(self.rules):g} $) aştı ve açık pozisyon var: motor başladı ama YENİ POZİSYON AÇMIYOR.\n"
                                    "Kapanış, borsa stopu ve trader kapanış takibi çalışır. Kârı çekip motoru yeniden başlatın.", "🛑"))
        self.niyetleri_coz(simdi)
        if dur_yarim is not None:
            self._dur_kapanis_kuyrukla(dur_yarim["neden"], dur_yarim["borsa_acik"], simdi)
        self.piyasa_oku(simdi)
        if self.kip == "sanal":
            self.maks_kaldirac_oku()                                                             # S-7: sanal tasfiye coin başına azami kaldıraçla (gerçek kipte tasfiyeyi HL yapar)
        elif float(self.rules.get("canli_min_azami_kaldirac", 0) or 0) > 0:
            self.kaldirac_tablosu_uygula(self.maks_kaldirac_tablosu()[0])                       # Denetim-4a: gerçek kip kaldıraç süzgeci tablosu
        self._son["kadro"] = 0
        for adres in list(self.saha.uyeler):                                                     # B15 geçişi: düzeltmeden önce girmiş, o günden beri dolum görülmemiş üyenin son dolumu bir kez okunur
            if self.saha.uyeler[adres].get("son_islem_ms") is None:
                self.trader_son_islem_oku(adres, simdi)
        self._kadro(simdi)
        for adres in [*self.saha.uyeler, *self.saha.inen]:
            if adres not in self.poz_tr:
                self.trader_pozlari_oku(adres)
        self.durum_yaz()

    def _dolum_satirlari_oku(self, bas_ms: int) -> list | None:
        """Denetim-8 (D4; ağ): kendi hesabımızın `userFillsByTime` satırları (`bas_ms`'den 5 sn önce başlar). Hata/biçim bozuk → None (çağıran limitPx + mutabakat notuna düşer)."""
        adres = os.environ.get("HL_HESAP_ADRESI", "").strip()
        if not adres:
            return None
        try:
            r = self.post_hizli({"type": "userFillsByTime", "user": adres, "startTime": max(0, int(bas_ms) - 5000)})
        except Exception as hata:                          # noqa: BLE001
            self.kayit({"olay": "dolum_okuma_hata", "tur": type(hata).__name__})
            return None
        return r if isinstance(r, list) else None

    @staticmethod
    def _gercek_dolum(satirlar: list | None, coin: str, cloid: str, oid: Any = None) -> tuple[float, float, float | None] | None:
        """Denetim-8 (D4; saf): cloid (ya da oid) eşleşen dolum satırlarından (sz toplamı, sz ağırlıklı ortalama px, fee toplamı | None). Eşleşme/geçerli sayı yoksa None."""
        try:
            es = [f for f in (satirlar or []) if isinstance(f, dict) and f.get("coin") == coin
                  and ((cloid and str(f.get("cloid") or "").lower() == str(cloid).lower()) or (oid is not None and f.get("oid") == oid))]
            sz = sum(float(f["sz"]) for f in es)
            if not es or not math.isfinite(sz) or sz <= 0:
                return None
            px = sum(float(f["sz"]) * float(f["px"]) for f in es) / sz
            fee = sum(float(f["fee"]) for f in es if f.get("fee") is not None) if any(f.get("fee") is not None for f in es) else None
            return (sz, px, fee) if math.isfinite(px) and px > 0 else None
        except (KeyError, TypeError, ValueError):
            return None

    def niyetleri_coz(self, simdi: int) -> int:
        """Çökmeden kalan sonucu yazılmamış niyetler (K‑37 §3) ve yeniden oynatma (t4b #2/#3). Gerçek kip: `orderStatus(cloid)`; emir varsa dolan miktar (`origSz − sz`) DURUMDAN BAĞIMSIZ kullanılır
        (`filled`, `canceled` …): > 0 ise sonuç satırına yazılır (limit fiyatla YAKLAŞIK; kesin değer mutabakatta), `sz > 0` kalmışsa ya da iptal edilmişse "kismi" sayılır. Emir yoksa niyet iptal. Sanal kip: `sonucsuz`,
        emir TEKRARLANMAZ. Ardından `hesap.json`daki son uygulanan niyetten sonraki sonuçlu niyetler deftere oynatılır (çift uygulama yok, kayıp yok). Kısmi kalan AZALTMA < `canli_min_nosyonel_usd` ise atlanır
        (HL <10 $ reduce‑only), değilse kapanış kuyruğuna girer; kısmi KAPANIŞ kuyruğa girer. Döner: çözülen niyet sayısı."""
        sayi = 0
        belirsiz_eklendi = 0
        takip: list[tuple[dict, float, float]] = []                  # (niyet, dolan sz, limit px): kısmi kalan için izleme
        satirlar_n: list[list | None] = [None]                       # Denetim-8 (D4): userFillsByTime yanıtı (tek okuma, tembel)
        for n in self.niyet.sonucsuz():
            if n["cloid"] in self.hesap.belirsiz:              # G-1: belirsiz emir — işaretçi zaten geçti; `belirsiz_coz` deftere doğrudan (bir kez) uygular
                continue
            durum = "sonucsuz"
            ek: dict[str, Any] = {}
            if self.kip == "gercek":
                try:
                    r = self.post_hizli({"type": "orderStatus", "user": os.environ.get("HL_HESAP_ADRESI", ""), "oid": n["cloid"]})
                    if (r or {}).get("status") == "order":
                        emir = r["order"]
                        durum = str(emir.get("status", "?"))
                        e = emir.get("order", {})
                        kalan_sz = float(e.get("sz", 0))
                        dolan = float(e.get("origSz", 0)) - kalan_sz
                        px = float(e.get("limitPx", 0))
                        kismi = dolan > 0 and (durum != "filled" or kalan_sz > EPS)
                        if dolan > 0 and n.get("adres") and n.get("coin"):
                            ucret_n = 0.0
                            if satirlar_n[0] is None:                                    # Denetim-8 (D4): çökme sonrası çözümde fiyat/ücret önce userFillsByTime'dan (cloid eşleşmesi); tek okuma
                                satirlar_n[0] = self._dolum_satirlari_oku(min([int(x.get("ms", simdi)) for x in self.niyet.sonucsuz()] or [simdi]))
                            g = self._gercek_dolum(satirlar_n[0], n["coin"], n["cloid"], e.get("oid"))
                            if g is not None:
                                px = g[1]
                                if g[2] is not None:
                                    ucret_n = g[2]
                                    self.ucret_gercek_usd += g[2]
                            else:                                                        # bulunamadı: limitPx (en kötü bant fiyatı) YAKLAŞIK; borsa=defter teyidine dek mutabakat notu
                                self.kayit({"olay": "dolum_px_yaklasik", "cloid": n["cloid"], "coin": n["coin"], "limit_px": px})
                                self._mutabakat_tut(n["coin"], "dolum_px_yaklasik", simdi)
                            ek = {"sz": dolan, "px": px, "ucret": ucret_n, "dolum": "kismi" if kismi else "dolu"}
                        if kismi:
                            self.sayac["kismi"] += 1
                        if n.get("eylem") in ("azalt", "kapat") and (kismi or durum != "filled"):
                            takip.append((n, max(dolan, 0.0), px))
                    else:
                        durum = "emir_yok_iptal"
                        self._takip_ekle(takip, n)
                except Exception as hata:                  # noqa: BLE001
                    # Denetim-4 (Kaçırılan-4): orderStatus HATA verdi = emrin dolup dolmadığı BİLİNMİYOR. "Çözüldü" yazılmaz (dolmuş emir yetim kalırdı): niyet AÇIK kalır, belirsiz emir olarak
                    # dakikalık `belirsiz_coz` yeniden sorar; çözülene dek yeni açılış durur (belirsiz bayrağı + coin kilidi) ve mutabakat notu borsa=defter teyidine dek kalır.
                    if n.get("adres") and n.get("coin"):
                        self.hesap.belirsiz[n["cloid"]] = {"ms": int(n.get("ms", 0)), "deneme": 1, "adres": n["adres"], "coin": n["coin"]}
                        self.risk.bayrak("belirsiz", True)
                        self.sayac["belirsiz"] = self.sayac.get("belirsiz", 0) + 1
                        belirsiz_eklendi += 1
                        self.kayit({"olay": "niyet_coz_hata", "cloid": n["cloid"], "adres": n["adres"], "coin": n["coin"], "eylem": n.get("eylem"), "tur": type(hata).__name__})
                        self._mutabakat_tut(n["coin"], "niyet_coz_hata", simdi)
                        self._takip_ekle(takip, n)                                      # azalt/kapat: kuyruk girdisi (belirsiz coin kilidi çözülene dek yeni emri bekletir)
                        self.tg.gonder(tg.alarm("ALARM: emir sonucu sorgulanamadı", f"{n['coin']} {n.get('eylem')} emrinin durumu açılışta okunamadı ({type(hata).__name__}).\n"
                                                "Her dakika yeniden sorulacak; çözülene dek yeni pozisyon açılmıyor."))
                        continue
                    durum = f"orderstatus_hata:{type(hata).__name__}"                # adres/coin yok (bozuk niyet): eski yol
                    self._mutabakat_tut(n.get("coin"), "niyet_coz_hata", simdi)
                    self._takip_ekle(takip, n)
            self.niyet.sonuc_yaz(n["cloid"], f"cozuldu:{durum}", simdi, **ek)
            self.kayit({"olay": "niyet_sonucsuz", "kip": self.kip, "kimlik": n.get("kimlik"), "eylem": n.get("eylem"), "coin": n.get("coin"), "cloid": n["cloid"], "durum": durum,
                        "dolan_sz": ek.get("sz"), "dolum": ek.get("dolum")})
            sayi += 1
        oynatilan = self._oynat(simdi)
        for n, dolan, px in takip:
            self._kismi_takip(n, dolan, px, simdi)
        if sayi or oynatilan or belirsiz_eklendi:
            self._dolum_yaz()
        return sayi + self.belirsiz_coz(simdi)

    def belirsiz_coz(self, simdi: int) -> int:
        """G-1/G-12a: sonucu belirsiz emirler (`hesap.belirsiz`; yalnız gerçek kip: SDK zaman aşımı / bağlantı hatası emir gönderildikten SONRA). Açılışta ve her dakika (ilk adım) çağrılır.
        Emir anından en az `canli_emir_zaman_asimi_sn` sonra `orderStatus(cloid)` sorulur: emir varsa dolan miktar (`origSz − sz`; fiyat limitPx, YAKLAŞIK — kesin değer mutabakatta; ücret HL `fee`
        bulunursa o, yoksa `maliyet_taker` tahmini) deftere TEK kez uygulanır; emir yoksa (`unknownOid`) dolmadı sayılır. Sorgu hata verirse girdi kalır, sonraki dakika yeniden denenir (yeni açılış
        `belirsiz` bayrağıyla durur, kapanış serbest). Sonuç satırı yazılıp defter kaydedilemeden çökülmüşse yazılmış sonuç kullanılır (ikinci sorgu ve çift uygulama yok). reduce‑only dolum defterdeki
        pozisyondan fazla uygulanmaz (kapanış teyidi borsada 0 görüp yerel pozisyonu zaten temizlemiş olabilir). Azalt/kapat tam dolmadıysa kalan kapanış kuyruğuna girer. Döner: çözülen sayı."""
        if not self.hesap.belirsiz:
            if self.risk.acilis_durdu.get("belirsiz"):
                self.risk.bayrak("belirsiz", False)
            return 0
        satirlar = self.niyet.satirlar()
        niyetler = {x["cloid"]: x for x in satirlar if x.get("t") == "niyet"}
        sonuclar = {x["cloid"]: x for x in satirlar if x.get("t") == "sonuc"}
        bekle_ms = float(self.rules.get("canli_emir_zaman_asimi_sn", 10)) * 1000
        sayi = 0
        takip: list[tuple[dict, float, float]] = []
        satirlar_b: list[list | None] = [None]                       # Denetim-8 (D4): userFillsByTime yanıtı (tek okuma, tembel)
        for cloid, b in list(self.hesap.belirsiz.items()):
            n = niyetler.get(cloid)
            if n is None or not n.get("adres") or not n.get("coin"):          # niyet satırı yok (bozulma): uygulanamaz → borsa ile mutabakat
                self.hesap.belirsiz.pop(cloid, None)
                self.kayit({"olay": "belirsiz_niyet_yok", "cloid": cloid})
                self._mutabakat_tut(b.get("coin") or (n or {}).get("coin"), "belirsiz_niyet_yok", simdi)
                continue
            r = sonuclar.get(cloid)
            if r is None:
                if self.kip != "gercek":
                    durum, dolan, px, kalan_sz, ucret = "sonucsuz", 0.0, 0.0, 0.0, 0.0
                else:
                    if simdi - int(b.get("ms", 0)) < bekle_ms:
                        continue
                    try:
                        y = self.post_hizli({"type": "orderStatus", "user": os.environ.get("HL_HESAP_ADRESI", ""), "oid": cloid})
                    except Exception as hata:                  # noqa: BLE001 - ağ yok: girdi kalır, sonraki dakika yeniden
                        b["yok_say"] = 0
                        b["deneme"] = int(b.get("deneme", 0)) + 1
                        self.kayit({"olay": "belirsiz_sorgu_hata", "cloid": cloid, "coin": n["coin"], "deneme": b["deneme"], "tur": type(hata).__name__})
                        if b["deneme"] == 5:
                            self.tg.gonder(tg.alarm("ALARM: belirsiz emir çözülemiyor", f"{n['coin']} {n.get('eylem')} emrinin durumu {b['deneme']} kez sorgulanamadı.\nYeni pozisyon açılmıyor; her dakika yeniden deneniyor."))
                        continue
                    durum, dolan, px, kalan_sz, ucret = "emir_yok", 0.0, 0.0, 0.0, 0.0
                    if not (isinstance(y, dict) and y.get("status") in ("order", "unknownOid")):
                        # 2. denetim O-4: hata / boş / beklenmeyen biçim "emir yok" DEĞİLDİR: girdi çözülmemiş kalır (yeni açılış durur), sonraki dakika yeniden sorulur
                        b["yok_say"] = 0
                        b["deneme"] = int(b.get("deneme", 0)) + 1
                        self.kayit({"olay": "belirsiz_sorgu_bicim", "cloid": cloid, "coin": n["coin"], "deneme": b["deneme"], "yanit": str(y)[:120]})
                        if b["deneme"] == 5:
                            self.tg.gonder(tg.alarm("ALARM: belirsiz emir çözülemiyor", f"{n['coin']} {n.get('eylem')} emrinin durumu {b['deneme']} kez anlaşılır biçimde sorgulanamadı.\nYeni pozisyon açılmıyor; her dakika yeniden deneniyor."))
                        continue
                    if y.get("status") == "unknownOid":
                        b["yok_say"] = int(b.get("yok_say", 0)) + 1                       # açık `unknownOid` yanıtı; kesinleşmesi için İKİ ardışık okuma (geç işlenen emir için pay)
                        if b["yok_say"] < 2:
                            self.kayit({"olay": "belirsiz_emir_yok_ilk", "cloid": cloid, "coin": n["coin"]})
                            continue
                    if y.get("status") == "order":
                        emir = y["order"]
                        durum = str(emir.get("status", "?"))
                        e = emir.get("order", {})
                        kalan_sz = float(e.get("sz", 0))
                        dolan = max(0.0, float(e.get("origSz", 0)) - kalan_sz)
                        px = float(e.get("limitPx", 0))
                        if dolan > 0:
                            if satirlar_b[0] is None:                                    # Denetim-8 (D4): gerçek fiyat + ücret userFillsByTime'dan (cloid/oid eşleşmesi; tek okuma)
                                satirlar_b[0] = self._dolum_satirlari_oku(min([int(v.get("ms", simdi)) for v in self.hesap.belirsiz.values()] or [simdi]))
                            g = self._gercek_dolum(satirlar_b[0], n["coin"], cloid, e.get("oid"))
                            if g is not None:
                                px = g[1]
                            else:                                                        # bulunamadı: limitPx YAKLAŞIK + mutabakat notu
                                self.kayit({"olay": "dolum_px_yaklasik", "cloid": cloid, "coin": n["coin"], "limit_px": px})
                                self._mutabakat_tut(n["coin"], "dolum_px_yaklasik", simdi)
                            gercek = g[2] if g is not None else None
                            ucret = gercek if gercek is not None else dolan * px * float(self.rules["maliyet_taker"])
                            if gercek is not None:
                                self.ucret_gercek_usd += gercek
                            else:
                                self.ucret_tahmin_say += 1
                self.niyet.sonuc_yaz(cloid, f"cozuldu:{durum}", simdi, sz=dolan, px=px, ucret=ucret, belirsiz=True, kalan_sz=kalan_sz)      # ÖNCE sonuç (fsync), SONRA defter
            else:
                durum = str(r.get("durum", "")).removeprefix("cozuldu:")
                dolan, px, ucret, kalan_sz = float(r.get("sz") or 0.0), float(r.get("px") or 0.0), float(r.get("ucret") or 0.0), float(r.get("kalan_sz") or 0.0)
            uygulanan = dolan
            if dolan > 0 and n.get("reduce_only"):
                yerel = self.hesap.sz(n["adres"], n["coin"])
                azaltir = (yerel > EPS and n["yon"] == "A") or (yerel < -EPS and n["yon"] == "B")
                uygulanan = min(dolan, abs(yerel)) if azaltir else 0.0
            if uygulanan > EPS and px > 0:
                try:
                    self.hesap.uygula(n["adres"], n["coin"], n["yon"], uygulanan, px, ucret * uygulanan / dolan, simdi)
                except ValueError as hata:
                    self.kayit({"olay": "defter_hata", "adres": n["adres"], "coin": n["coin"], "hata": str(hata)[:120]})
            else:
                uygulanan = 0.0
            self.hesap.belirsiz.pop(cloid, None)
            sayi += 1
            self.kayit({"olay": "belirsiz_cozuldu", "kip": self.kip, "cloid": cloid, "adres": n["adres"], "coin": n["coin"], "eylem": n.get("eylem"), "yon": n.get("yon"), "durum": durum,
                        "dolan_sz": dolan, "uygulanan_sz": uygulanan, "px": px, "ucret": ucret})
            self.tg.gonder(tg.alarm("Belirsiz emir çözüldü", f"{n['coin']} {n.get('eylem')}: borsada {f'doldu {dolan:.6g}' if dolan > 0 else 'dolmadı'} ({durum}); deftere işlendi.", "✅"))
            if n.get("eylem") in ("azalt", "kapat") and (dolan <= 0 or kalan_sz > EPS or durum != "filled"):
                if dolan > 0:
                    takip.append((n, dolan, px))
                else:
                    self._takip_ekle(takip, n)
        for n, dolan, px in takip:
            self._kismi_takip(n, dolan, px, simdi)
        self.risk.bayrak("belirsiz", bool(self.hesap.belirsiz))
        if sayi:
            self._dolum_yaz()
        return sayi

    def _takip_ekle(self, takip: list, n: dict) -> None:
        """Emir hiç görülmedi / durum okunamadı: azalt/kapat niyeti yeniden kuyruğa alınır (dolan 0). Sınır: kuyruk girdisi `deneme` ile alarmlı eksik olur; ilk deneme yeni kimlik/cloid ile (`_kuyruk_isle`)."""
        if n.get("eylem") in ("azalt", "kapat") and n.get("adres") and n.get("coin"):
            p = self.hesap.poz.get(n["adres"], {}).get(n["coin"])
            px = self.mark(n["coin"], p.giris if p else None) or 0.0
            takip.append((n, 0.0, px))

    def _oynat(self, simdi: int) -> int:
        """`hesap.json`daki `son_niyet_cloid`'den SONRAKİ sonuçlu niyetleri (sz > 0) deftere uygular ve işaretçiyi ilerletir (t4b #3). İşaretçi niyet dosyasında yoksa oynatılmaz, mutabakat bayrağı kalkar."""
        satirlar = self.niyet.satirlar()
        niyetler = [x for x in satirlar if x.get("t") == "niyet"]
        sonuc = {x["cloid"]: x for x in satirlar if x.get("t") == "sonuc"}
        sira = [x["cloid"] for x in niyetler]
        isaret = self.hesap.son_niyet_cloid
        if isaret is None and self._hesap_yok:
            self._hesap_yok = False
            if niyetler:                                   # güvenli taraf: oynatma YOK, işaretçi dosya sonuna, mutabakat bayrağı (borsa ile uzlaştırılır)
                self.hesap.son_niyet_cloid = sira[-1]
                self.kayit({"olay": "oynat_hesap_yok", "niyet_say": len(niyetler)})
                self.risk.bayrak("mutabakat", True)
            return 0
        if isaret is None:
            bas = 0
        elif isaret in sira:
            bas = sira.index(isaret) + 1
        else:
            self.kayit({"olay": "oynat_isaretci_yok", "cloid": isaret})
            self.risk.bayrak("mutabakat", True)
            return 0
        sayi = 0
        for n in niyetler[bas:]:
            r = sonuc.get(n["cloid"])
            self.hesap.son_niyet_cloid = n["cloid"]
            if r is None:
                continue
            sz, px = float(r.get("sz") or 0.0), float(r.get("px") or 0.0)
            if sz <= 0 or not n.get("adres") or not n.get("coin"):
                continue
            try:
                self.hesap.uygula(n["adres"], n["coin"], n["yon"], sz, px, float(r.get("ucret") or 0.0), int(r.get("ms", simdi)))
                sayi += 1
            except ValueError as hata:
                self.kayit({"olay": "defter_hata", "adres": n["adres"], "coin": n["coin"], "hata": str(hata)[:120]})
            self.kayit({"olay": "niyet_oynatildi", "cloid": n["cloid"], "adres": n["adres"], "coin": n["coin"], "yon": n["yon"], "sz": sz, "px": px})
        return sayi

    def _kismi_takip(self, n: dict, dolan: float, px: float, simdi: int) -> None:
        """Kısmi dolan / dolmayan reduce‑only niyetin kalanı (t4b #2). AZALT: kalan nosyonel < `canli_min_nosyonel_usd` ise atlanır (`min_nosyonel`), değilse hedefe doğru kuyruğa. KAPAT: pozisyon kaldıysa kuyruğa."""
        adres, coin = n["adres"], n["coin"]
        yerel = self.hesap.sz(adres, coin)
        if abs(yerel) < EPS or px <= 0:
            return
        if n["eylem"] == "kapat":
            if abs(yerel) * px > float(self.rules["canli_kapanis_toz_usd"]):
                self._eksik_ekle(adres, coin, "kapat", 0.0, "niyet_kismi", simdi)
            return
        kalan_usd = float(n.get("usd", 0.0)) - dolan * px
        if kalan_usd <= 0:
            return
        if kalan_usd < float(self.rules.get("canli_min_nosyonel_usd", 10)):
            self.sayac["min_nosyonel"] += 1
            self._say_neden("min_nosyonel")
            self.kayit({"olay": "kismi_azaltma_atlandi", "adres": adres, "coin": coin, "kalan_usd": round(kalan_usd, 6)})
            return
        hedef = yerel - (1 if yerel > 0 else -1) * kalan_usd / px
        if hedef * yerel < 0:
            hedef = 0.0
        self._eksik_ekle(adres, coin, "azalt", hedef, "niyet_kismi", simdi)

    def ilk_mutabakat(self) -> None:
        """Denetim-8 (O4; gerçek kip, `calis` başında, kaçan dolumlar oynatılmadan önce): yalnız mark + HL okuma + mutabakat + borsa stop eşitleme (tam `dakika` değil). Eski sorun: motor kapalıyken
        tetiklenen stop → borsada 0, defterde pozisyon; bayat `biz_sz` ile oynatılan açılış yanlış boyutlanırdı. Mutabakat TAMAMLANMAZSA (HL okunamadı) açılış bayrağı kalır; mutabakat sonucu
        sorunsa bayrak yine kalır; yalnız temiz mutabakat bayrağı kaldırır. Her adım ayrı korunur (hata kayıt + bayrak, motor düşmez)."""
        simdi = self.saat_ms()
        self._mutabakat_tamam_ms = None
        mids = self.mids_al()
        self._hl_okuma_imza = self._poz_imza()
        hl = self.hl_oku()
        if self.kip == "gercek":
            self._ofset_bayrak(True)                       # K-1: açılışta ofset doğrulanmamış sayılır (diskteki bayrak bayat); HL + ledger okununca kalkar
        ledger = self.ledger_oku(simdi) if (hl and self.kip == "gercek") else None             # K-1: motor kapalıyken yapılan yatırma/çekme ofsete açılışta girer
        stop_acik = self.acik_emir_oku() if self._aralik_mi("borsa_stop", simdi, float(self.rules["canli_borsa_stop_sn"])) else False
        with self._lock:
            self.mids_uygula(mids, simdi)
            if self.kip == "gercek" and hl:
                for ad, f in (("ilk_hl_ozsermaye", lambda: self.hl_uygula(hl[1], simdi, self._hl_okuma_ms(hl, simdi))), ("ilk_ofset", lambda: self._ofset_adimi(ledger, True, simdi)),
                              ("ilk_hl_sicrama", lambda: self._hl_sicrama_denetle(simdi))):          # mutabakat karşılaştırmasından ÖNCE: ofset yenilenir, son kayıtlı özsermaye ile kıyas
                    try:
                        f()
                    except Exception as hata:              # noqa: BLE001
                        self.kayit({"olay": "adim_hata", "adim": ad, "tur": type(hata).__name__, "mesaj": str(hata)[:160], "ardisik": 1})
            for ad, f in (("ilk_mutabakat", lambda: self._mutabakat(simdi, hl)), ("ilk_borsa_stop", lambda: self.borsa_stop_esitle(stop_acik, simdi) if stop_acik is not False else None)):
                try:
                    f()
                except Exception as hata:                  # noqa: BLE001
                    self.kayit({"olay": "adim_hata", "adim": ad, "tur": type(hata).__name__, "mesaj": str(hata)[:160], "ardisik": 1})
            if self.kip == "gercek":
                self._hl_izle(True, hl, simdi)             # O-1: açılıştaki HL okuması da ardışık sayaca girer
            if self._mutabakat_tamam_ms is None:           # mutabakat çalışmadı / tamamlanmadı: açılış kapalı kalır
                self.risk.bayrak("mutabakat", True)
                self.kayit({"olay": "ilk_mutabakat_yok"})
            else:
                self.kayit({"olay": "ilk_mutabakat", "acilis_acik": not self.risk.acilis_durdu.get("mutabakat")})
            self.durum_yaz()

    def kacanlari_tamamla(self, bas_ms: int | None = None) -> int:
        """Açılışta REST ile kaçan dolumları tamamlar (`gec_goruldu`): her saha/inen adresi için `bas_ms`'den şimdiye. Pencere `canli_kacan_pencere_dk` ile sınırlıdır."""
        simdi = self.saat_ms()
        baslangic = max(bas_ms or self.son_olay_ms or simdi, simdi - int(self.rules["canli_kacan_pencere_dk"]) * DAKIKA)
        sayi = 0
        for adres in [*self.saha.uyeler, *self.saha.inen]:
            try:
                dolumlar = rest_dolumlar(self.post, adres, baslangic, simdi)
            except Exception as hata:                      # noqa: BLE001
                self.kayit({"olay": "kacan_okuma_hata", "adres": adres, "tur": type(hata).__name__})
                continue
            for f in sorted(dolumlar, key=lambda x: int(x["time"])):
                coin = str(f.get("coin", ""))
                if coin.startswith("@") or "/" in coin or f.get("tid") is None:
                    continue
                o = Olay(f"{adres}:{f['tid']}", adres, adres, int(f["time"]), simdi, "rest", False, "", coin, float(f["px"]), float(f["sz"]), str(f["side"]),
                         float(f["startPosition"]) if f.get("startPosition") is not None else None)
                if self.olay_isle(o, True):
                    sayi += 1
        self.kayit({"olay": "kacan_tamamlandi", "adet": sayi, "bas_ms": baslangic})
        return sayi


# ---------------------------------------------------------------------------------------------------- dinleyici köprüsü
class CanliDinleyici(Dinleyici):
    """`dinleyici.Dinleyici` (kural 7: WS, tekilleştirme, kopma → REST dolgu) + motor kuyruğu. Taban sınıfın risk kancası (`risk_isle`) motor kuyruğuna bağlanır; dinamik adres ekleme (`izle_ekle`)."""

    def __init__(self, kuyruk: asyncio.Queue, *a: Any, **k: Any) -> None:
        super().__init__(*a, **k)
        self.kuyruk = kuyruk
        self.ad_adres = {i.ad: i.adres for i in self.liste}

    def izle_ekle(self, adres: str) -> None:
        if adres in self.izlenen:
            return
        i = Izlenen(adres[:12], adres)
        self.izlenen[adres] = i
        self.liste.append(i)
        self.ad_adres[i.ad] = adres
        from copytrade.dinleyici import TraderOlcum
        self.olcum.adlar.append(i.ad)
        self.olcum.toplam[i.ad], self.olcum.saat[i.ad] = TraderOlcum(), TraderOlcum()

    def risk_isle(self, o: Olay, canli: bool, simdi_ms: int, kaynak: str | None = None) -> None:       # type: ignore[override]
        adres = o.adres or self.ad_adres.get(o.ad, "")
        self.kuyruk.put_nowait((replace(o, adres=adres), bool(canli and not self.olcum.snapshot_mi(o))))


class OncelikliKuyruk:
    """Motor olay kuyruğu (K‑37 §6): iki FIFO — kapat/azalt (öncelikli) ve ac/artir. `canli_kuyruk_max` dolarsa AÇILIŞLAR düşer (sayılır, alarm), kapanışlar kalır (gerekirse en eski açılış atılır).
    `asyncio.Queue` uyumlu arayüz: `put_nowait((olay, canli))`, `await get()`, `get_nowait()`, `empty()`, `qsize()`. `son_giris_ms`: son çekilen öğenin kuyruğa girdiği an (bekleme ölçümü)."""

    def __init__(self, kapanis_mi: Callable[[Olay], bool], maks: int = 10000, saat_ms: Callable[[], int] | None = None) -> None:
        self.kapanis_mi, self.maks = kapanis_mi, int(maks)
        self.saat_ms = saat_ms or (lambda: int(time.time() * 1000))
        self._kapat: deque = deque()
        self._ac: deque = deque()
        self._bekleyen: dict[tuple[str, str], list] = {}      # (adres, coin) -> [bekleyen sayısı, atandığı kuyruk]: aynı anahtarın olayları TEK kuyrukta kalır (sıra bozulmaz)
        self._olay = asyncio.Event()
        self.dusen_acilis = 0
        self.dusenler: deque[Olay] = deque()                  # düşen açılış olayları: tüketici bunlarla trader pozisyon tablosunu günceller (t4b #6)
        self.son_giris_ms = 0

    def qsize(self) -> int:
        return len(self._kapat) + len(self._ac)

    def empty(self) -> bool:
        return self.qsize() == 0

    def put_nowait(self, oge: tuple[Olay, bool]) -> None:
        kapanis = bool(self.kapanis_mi(oge[0]))
        if self.qsize() >= self.maks:
            if not kapanis:
                self.dusen_acilis += 1
                self.dusenler.append(oge[0])
                return
            if self._ac:
                dusen = self._ac.popleft()[1][0]
                self._birak(dusen)
                self.dusen_acilis += 1
                self.dusenler.append(dusen)
        anahtar = (oge[0].adres, oge[0].coin)
        kayit = self._bekleyen.get(anahtar)
        if kayit is None:                                  # öncelik yalnız FARKLI (adres, coin) arasında; aynı anahtar FIFO (ac → kapat sırası bozulursa hayalet pozisyon kalır)
            kayit = self._bekleyen[anahtar] = [0, self._kapat if kapanis else self._ac]
        kayit[0] += 1
        kayit[1].append((self.saat_ms(), oge))
        self._olay.set()

    def _birak(self, olay: Olay) -> None:
        anahtar = (olay.adres, olay.coin)
        kayit = self._bekleyen.get(anahtar)
        if kayit is not None:
            kayit[0] -= 1
            if kayit[0] <= 0:
                del self._bekleyen[anahtar]

    def get_nowait(self) -> tuple[Olay, bool]:
        kuyruk = self._kapat or self._ac
        if not kuyruk:
            raise asyncio.QueueEmpty
        self.son_giris_ms, oge = kuyruk.popleft()
        self._birak(oge[0])
        return oge

    async def get(self) -> tuple[Olay, bool]:
        while self.empty():
            self._olay.clear()
            await self._olay.wait()
        return self.get_nowait()


async def _tuketici(motor: Motor, kuyruk: asyncio.Queue | OncelikliKuyruk, durdur: asyncio.Event) -> None:
    dusen_bilinen = 0
    while not durdur.is_set():
        try:
            o, canli = await asyncio.wait_for(kuyruk.get(), timeout=1.0)
        except asyncio.TimeoutError:
            continue
        giris = getattr(kuyruk, "son_giris_ms", 0)
        if giris:
            motor.kuyruk_gecikme.append(max(0, motor.saat_ms() - giris))
        for d_olay in list(getattr(kuyruk, "dusenler", ())):            # t4b #6: düşen olay emir üretmez ama trader pozisyon tablosunu günceller
            try:
                kuyruk.dusenler.remove(d_olay)
                await asyncio.to_thread(motor.dusen_isle, d_olay)
            except Exception as hata:                      # noqa: BLE001
                motor.kayit({"olay": "olay_hata", "tur": type(hata).__name__, "mesaj": str(hata)[:160]})
        dusen = getattr(kuyruk, "dusen_acilis", 0)
        if dusen > dusen_bilinen:
            motor.kayit({"olay": "kuyruk_tasti", "dusen_acilis": dusen})
            motor.tg.gonder(tg.alarm("ALARM: olay kuyruğu doldu", f"{dusen - dusen_bilinen} yeni pozisyon açılışı düşürüldü (kapanışlar korunur)."))
            dusen_bilinen = dusen
        try:
            await asyncio.to_thread(motor.olay_isle, o, canli)
        except Exception as hata:                          # noqa: BLE001 - tek dolum hatası motoru düşürmez
            motor.kayit({"olay": "olay_hata", "tur": type(hata).__name__, "mesaj": str(hata)[:160]})


class Bekci:
    """G-12 bekçi: dakikalık bakımın İLERLEDİĞİNİ izler (`nabiz()` her başarılı `dakika` sonunda). Son nabızdan `sinir_sn` (`canli_bekci_sn`) geçtiyse — `dakika` kilitte ya da ağda asılı, sürekli hata
    veriyor ya da olay döngüsü donmuş — kayıt + Telegram alarmı (en çok `alarm_bekle_sn` beklenir) ve `cik(1)`. Varsayılan `os._exit`: asılı iş parçacığı olsa da süreç biter, systemd yeniden başlatır.
    Saat (`saat`, sn; varsayılan `time.monotonic`) ve çıkış (`cik`) enjekte edilir (test). Ayrı iş parçacığında koşar (`calistir`): olay döngüsü dursa da çalışır."""

    def __init__(self, motor: Any, sinir_sn: float, saat: Callable[[], float] = time.monotonic, cik: Callable[[int], Any] = os._exit, alarm_bekle_sn: float = 10.0) -> None:
        self.motor, self.sinir_sn, self.saat, self.cik, self.alarm_bekle_sn = motor, float(sinir_sn), saat, cik, float(alarm_bekle_sn)
        self.son = saat()
        self.tetiklendi = False

    def nabiz(self) -> None:
        self.son = self.saat()

    def kontrol(self) -> bool:
        """True: tetiklendi (alarm + çıkış çağrıldı)."""
        gecen = self.saat() - self.son
        if self.tetiklendi or gecen < self.sinir_sn:
            return False
        self.tetiklendi = True
        try:                                               # kilit "bitti": süreç ölüyor, zincirle gelen sonraki vardiya (tetikleyen kendi kilidi) hemen devralır. Önce bayrak: asılı ana iş parçacığı kilidi yeniden "aktif" yazmasın.
            self.motor._kilit_birakildi = True
            self.motor.kilit_yaz(True)
        except Exception:                                  # noqa: BLE001 - disk dolu olabilir: çıkış yine olur (sahip-koşu denetimi yedekte)
            pass
        try:
            acik = self.motor.acik_poz_sayisi()
            metin = tg.msg_bot_durdu(f"motor dondu ({gecen:.0f} sn'dir bakım bitmedi)", acik, self.motor._stop_durumu(acik, False), son="Yeni işlem açılmıyor; sistem motoru kendiliğinden yeniden başlatıyor.", senden=tg.SENDEN_YOK)
        except Exception:                                  # noqa: BLE001
            metin = tg.msg_bot_durdu(f"motor dondu ({gecen:.0f} sn'dir bakım bitmedi)", 0, "bilinmiyor", son="Yeni işlem açılmıyor; sistem motoru kendiliğinden yeniden başlatıyor.", senden=tg.SENDEN_YOK)

        def bildir() -> None:
            try:
                self.motor.kayit({"olay": "bekci_tetik", "gecen_sn": round(gecen, 1), "sinir_sn": self.sinir_sn})
            except Exception:                              # noqa: BLE001 - disk dolu olabilir: çıkış yine olur
                pass
            try:
                self.motor.tg.gonder(metin)
                try:
                    (self.motor.dur_dosyasi.parent / "tg_bot_durdu").write_text(f"{int(time.time())}\nmotor dondu\n")
                except Exception:                          # noqa: BLE001
                    pass
                havuz = getattr(self.motor.tg, "_havuz", None)
                if havuz is not None:
                    havuz.shutdown(wait=True)              # arka plan gönderimi bitsin (çıkış onu öldürmeden)
            except Exception:                              # noqa: BLE001
                pass
        t = threading.Thread(target=bildir, daemon=True, name="bekci-alarm")
        t.start()
        t.join(self.alarm_bekle_sn)                        # Telegram asılı kalsa da çıkış gecikmez
        self.cik(1)
        return True

    def calistir(self, durdur: threading.Event, aralik_sn: float = 5.0) -> None:
        while not durdur.wait(aralik_sn):
            if self.kontrol():
                return


def _gorev_bitti(motor: Motor, durdur: asyncio.Event, dinleyici: Any, ad: str, gorev: asyncio.Task) -> None:
    """G-12b: tüketici / periyodik görev `durdur` gelmeden biterse (yakalanmamış istisna) sessiz ölüm yok: kayıt + alarm + motor durdurulur ve `main` çıkış kodu 1 döner (systemd yeniden başlatır)."""
    hata = None if gorev.cancelled() else gorev.exception()
    if hata is None and durdur.is_set():
        return                                             # olağan bitiş (DUR / süre / SIGTERM)
    motor.cikis_kodu = 1
    try:
        motor.kayit({"olay": "gorev_bitti", "gorev": ad, "tur": type(hata).__name__ if hata else "beklenmedik", "mesaj": str(hata)[:160] if hata else ""})
        neden_g = f"'{tg.sade_ad(ad)}' görevi beklenmedik biçimde bitti ({type(hata).__name__ if hata else 'beklenmedik'})"
        son_g = "Yeni işlem açılmıyor; sistem motoru kendiliğinden yeniden başlatıyor."
        try:
            motor._bot_durdu_bildir(neden_g, motor.acik_poz_sayisi(), calisiyor=False, son=son_g, senden=tg.SENDEN_YOK)
        except AttributeError:                                 # sahte/eksik motor: yine de kısa mesaj
            motor.tg.gonder(tg.msg_bot_durdu(neden_g, 0, "bilinmiyor", son=son_g, senden=tg.SENDEN_YOK))
    finally:
        try:
            dinleyici.durdur()
        finally:
            durdur.set()


async def _periyodik(motor: Motor, durdur: asyncio.Event, dinleyici: CanliDinleyici, aralik_sn: float = 30.0, bekci: Bekci | None = None) -> None:
    ardisik_hata = 0
    while not durdur.is_set():
        try:                                                # G-12b: tek istisna görevi öldürmez; ilerleme yoksa bekçi süreci yeniden başlatır
            await asyncio.to_thread(motor.dakika)
            ardisik_hata = 0
            if bekci is not None:
                bekci.nabiz()
        except Exception as hata:                           # noqa: BLE001
            ardisik_hata += 1
            motor.kayit({"olay": "adim_hata", "adim": "dakika", "tur": type(hata).__name__, "mesaj": str(hata)[:160], "ardisik": ardisik_hata})
            if ardisik_hata == 1 or ardisik_hata % 20 == 0:
                motor.tg.gonder(tg.alarm("ALARM: dakikalık bakım hata verdi", f"{type(hata).__name__}: {str(hata)[:120]} (üst üste {ardisik_hata}).\nYeniden deneniyor; ilerleme olmazsa bekçi motoru yeniden başlatır."))
        try:                                               # pano (15 dk'lık yayım) taze `durum/ozet.json` ister: vardiya boyunca her döngüde yazılır (B7); hata motoru durdurmaz
            _yaz(motor.durum_dizin / "ozet.json", {**motor.ozet(), **motor.pano_ek(), "dinleyici": dinleyici.ozet()["genel"], "yazildi_ms": motor.saat_ms()})
        except Exception as hata:                           # noqa: BLE001
            motor.kayit({"olay": "ozet_yazma_hata", "tur": type(hata).__name__, "mesaj": str(hata)[:120]})
        for adres in motor.saha.uyeler:
            dinleyici.izle_ekle(adres)
        if motor.dur_istendi:
            dinleyici.durdur()
            durdur.set()
            return
        try:
            await asyncio.wait_for(durdur.wait(), timeout=aralik_sn)
        except asyncio.TimeoutError:
            pass


def bekleme_yaz(motor: Motor, simdi: int, kadro_geldi: bool = False) -> None:
    """Pano 14.11: bekleme vardiyasında da (saha boş / kadro bekleniyor) her yoklamada (`canli_kadro_aralik_sn` ≤ 15 dk'lık yayım aralığı) dönem bakımı ve `ozet.json`:
    BTC dönem başı fiyatı (`btc_donem_oku`), mark (BTC al-tut kıyası), `donem_seri_guncelle` (eğri + boş saha doluluğu), `tur` kaydı ve durum dosyaları; yayım betiği panoyu bundan üretir.
    Hata vardiyayı durdurmaz (kayıt)."""
    try:
        mids = motor.mids_al() if motor._aralik_mi("bekleme_mids", simdi, 60) else None
        btc = motor.btc_donem_oku(simdi)
        with motor._lock:
            motor.mids_uygula(mids, simdi)
            motor.btc_donem_uygula(btc)
            motor.donem_seri_guncelle(simdi)
            motor._tur_kaydi(simdi)
            motor.durum_yaz()
        _yaz(motor.durum_dizin / "ozet.json", {**motor.ozet(), **motor.pano_ek(), "bekleme_vardiyasi": True, "kadro_geldi": kadro_geldi, "yazildi_ms": motor.saat_ms()})
    except Exception as hata:                               # noqa: BLE001
        motor.kayit({"olay": "ozet_yazma_hata", "tur": type(hata).__name__, "mesaj": str(hata)[:120]})


async def bekleme_vardiyasi(motor: Motor, sure_sn: float | None, uyku: Callable[[float], Any] = asyncio.sleep) -> dict:
    """K-54: yeni sürüm kadrosu (radar_surum_gerekli) henüz yok ve saha boş → izlenecek adres yoktur. Motor çökmez (09.11 18:01Z olayı: vardiya
    zinciri koptu); vardiya boyunca kadroyu aralıkla yoklar, uygun kadro gelince erken ve temiz biter (sonraki vardiya adreslerle başlar). 14.11: her yoklamada `bekleme_yaz`
    (ozet.json + dönem serisi + BTC dönem fiyatı) — pano vardiya sonunu beklemez."""
    motor.kayit({"olay": "bekleme_vardiyasi", "gerekli": str(motor.radar_surum_gerekli)})
    bitis = motor.saat_ms() + int((sure_sn or 0) * 1000)
    aralik = max(1.0, float(motor.rules["canli_kadro_aralik_sn"]))
    kadro_geldi = False
    while True:
        simdi = motor.saat_ms()
        try:
            motor._kadro_uygula((True, motor.kadro_oku()), simdi)
        except Exception as hata:                           # noqa: BLE001
            motor.kayit({"olay": "kadro_okuma_hata", "tur": type(hata).__name__})
        bekleme_yaz(motor, simdi, kadro_geldi)
        if motor.saha.uyeler or (motor._son_kadro or {}).get("satirlar"):
            kadro_geldi = True
            motor.kayit({"olay": "bekleme_bitti_kadro_geldi", "uye": len(motor.saha.uyeler)})
            break
        if simdi >= bitis:
            break
        await uyku(min(aralik, max(1.0, (bitis - simdi) / 1000)))
    ozet = {**motor.ozet(), **motor.pano_ek(), "bekleme_vardiyasi": True, "kadro_geldi": kadro_geldi, "yazildi_ms": motor.saat_ms()}
    motor.kayit({"olay": "kapanis", "ozet": ozet})
    _yaz(motor.durum_dizin / "ozet.json", ozet)
    motor.durum_yaz()
    motor._kilit_birakildi = True
    motor.kilit_yaz(True)
    return ozet


async def calis(motor: Motor, sure_sn: float | None = None, ws: Callable[[], Any] = ws_baglan, cikti: Path | None = None) -> dict:
    """Ana döngü: dinleyici + tüketici + periyodik görevler; `sure_sn` dolunca (vardiya) ya da DUR/SIGTERM ile biter. Son özet `kayit`'a ve `durum/ozet.json`'a yazılır."""
    oncelik = [*motor.saha.uyeler, *motor.saha.inen]                      # userFills aboneliği ilk `userfills_adet` adrese: önce saha/inen
    adaylar = [s["adres"] for s in ((motor._son_kadro or {}).get("satirlar") or [])]
    adresler = list(dict.fromkeys([*oncelik, *adaylar]))
    if not adresler and motor.radar_surum_gerekli:
        return await bekleme_vardiyasi(motor, sure_sn)
    if not adresler:
        raise KipHatasi("izlenecek adres yok (kadro okunamadı, saha boş)")
    liste = [Izlenen(a[:12], a) for a in adresler]
    coinler = coin_listesi(motor.post)
    kuyruk = OncelikliKuyruk(motor.kapanis_mi, int(motor.rules["canli_kuyruk_max"]), motor.saat_ms)
    cikti = cikti or (motor.durum_dizin / "dinleyici")
    din = CanliDinleyici(kuyruk, liste, coinler, ws, motor.post, cikti, Ayar(userfills_adet=10, sure_sn=sure_sn), saat_ms=motor.saat_ms, dex_adlari=motor._dexler_guvenli())
    durdur = asyncio.Event()
    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: (din.durdur(), durdur.set()))
    except (NotImplementedError, RuntimeError):
        pass
    if motor.kip == "gercek":
        motor.ilk_mutabakat()                              # Denetim-8 (O4): kaçan dolumlar oynatılmadan ÖNCE borsa mutabakatı + borsa stop eşitlemesi (tam `dakika` değil); geçene kadar açılış kapalı
    once = dict(motor._say_gun)
    motor.kacanlari_tamamla()
    motor.kesinti_duzeldi_bildir(once)
    bekci = Bekci(motor, float(motor.rules.get("canli_bekci_sn", 180)))
    motor.bekci_nabiz = bekci.nabiz                       # kapanış döngüsü (DUR / kuyruk) her denemede besler
    bekci_dur = threading.Event()
    threading.Thread(target=bekci.calistir, args=(bekci_dur,), daemon=True, name="bekci").start()
    gorevler = [asyncio.create_task(_tuketici(motor, kuyruk, durdur)), asyncio.create_task(_periyodik(motor, durdur, din, bekci=bekci))]
    for ad, gorev in zip(("tuketici", "periyodik"), gorevler):
        gorev.add_done_callback(lambda g, ad=ad: _gorev_bitti(motor, durdur, din, ad, g))
    try:
        await din.calis()
    finally:
        durdur.set()
        await asyncio.gather(*gorevler, return_exceptions=True)
        motor.emir_ozeti(motor.saat_ms(), zorla=True)
        ozet = {**motor.ozet(), **motor.pano_ek(), "dinleyici": din.ozet()["genel"], "yazildi_ms": motor.saat_ms()}
        motor.kayit({"olay": "kapanis", "ozet": ozet})
        _yaz(motor.durum_dizin / "ozet.json", ozet)
        motor.durum_yaz()
        motor._kilit_birakildi = True
        motor.kilit_yaz(True)                              # temiz kapanış: sonraki vardiya hemen devralır
        bekci_dur.set()                                    # kapanış asılı kalırsa bekçi buraya gelinmeden süreci bitirir
    return ozet


# ---------------------------------------------------------------------------------------------------- kontrol ve CLI
def kadro_url(rules: dict, dal: str | None = None) -> str:
    return f"https://raw.githubusercontent.com/{rules['canli_kadro_repo']}/{dal or rules['canli_kadro_dali']}/radar/son/kadro.json"


def http_kadro_oku(rules: dict, dal: str | None = None, deneme: int = 3, bekle_sn: float = 2.0) -> dict | None:
    """O9: geçici ağ/5xx hatasında `deneme` kez dener (kısa bekleme); 404 = kadro yok (None, yeniden denenmez); kalıcı hata son denemede yükselir."""
    import requests
    for i in range(deneme):
        try:
            r = requests.get(kadro_url(rules, dal), timeout=20)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError, ValueError) as hata:
            kalici = isinstance(hata, requests.HTTPError) and getattr(hata.response, "status_code", 500) < 500 and getattr(hata.response, "status_code", 500) != 429
            if i == deneme - 1 or kalici:
                raise
            time.sleep(bekle_sn * (i + 1))
    return None


# ---------------------------------------------------------------------------------------------------- açılış güvenceleri (G-15, G-20, G-21)
ORTAM_DOSYALARI = ("/etc/sg-canli.env", "/etc/sg-canli-telegram.env")          # sunucu ortam dosyaları (deploy/kurulum.md); systemd EnvironmentFile


def ortam_izin_zorunlu(yollar: tuple[str, ...] | None = None) -> None:
    """Denetim-8: gerçek kip açılışında ortam dosyalarının izni 600/400 olmalı (grup/diğerleri okuyabiliyorsa API anahtarı sızar). Var olan her dosya `ortam_dosyasi.izin_denetle` ile denetlenir; sorun → `KipHatasi`
    (kalıcı çıkış 3, motor BAŞLAMAZ). Dosya yoksa atlanır (ortam başka yoldan verilmiş; `--kontrol` ayrıca denetler). Yalnız gerçek kip çağırır: sanal/Actions etkilenmez."""
    from copytrade.canli.ortam_dosyasi import izin_denetle
    sorunlar: list[str] = []
    for y in (ORTAM_DOSYALARI if yollar is None else yollar):
        yol = Path(y)
        if yol.exists():
            sorunlar += [f"{yol.name}: {x}" for x in izin_denetle(yol)]
    if sorunlar:
        raise KipHatasi("ortam dosyası izni güvensiz, motor başlamadı: " + "; ".join(sorunlar[:3]))


def durum_dizin_dogrula(dizin: Path, kip: str) -> None:
    """G-21: gerçek kipte durum dizini MUTLAK yol olmalı (çalışma dizinine göre göreli bir yol, aynı agent cüzdanla ayrı defterli ikinci bir süreç açtırabilir). Aksi halde KipHatasi (çıkış 3)."""
    if kip == "gercek" and not Path(dizin).is_absolute():
        raise KipHatasi(f"gercek kipte --durum-dizin mutlak yol olmalı (verilen: {str(dizin)[:80]})")


def _flock_al(yol: Path, kilitli_mesaj: str) -> int:
    import fcntl
    try:
        yol.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(yol, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as hata:
        raise KipHatasi(f"{yol.name} açılamadı ({type(hata).__name__}): durum dizini izinlerini kontrol edin") from hata
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as hata:                                        # BlockingIOError: başka süreç tutuyor
        os.close(fd)
        raise KipHatasi(kilitli_mesaj) from hata
    os.ftruncate(fd, 0)
    os.write(fd, f"{os.getpid()}\n".encode())
    return fd


def motor_kilidi_al(dizin: Path) -> int:
    """G-21: `<durum-dizin>/motor.lock` üzerinde `fcntl.flock(LOCK_EX | LOCK_NB)`. Kilit, dönen dosya tanımlayıcısı açık kaldıkça sürer (süreç ölünce çekirdek bırakır: bayat kilit olmaz).
    Başka bir süreç tutuyorsa ya da dosya açılamıyorsa KipHatasi (çıkış 3: ikinci motor AÇILMAZ)."""
    return _flock_al(Path(dizin) / "motor.lock", "başka bir motor süreci bu durum dizinini kullanıyor (motor.lock kilitli): ikinci motor açılmaz")


def hesap_kilidi_adi(adres: str) -> str:
    """Y-5: hesap kilidi dosya adı `motor-<adres>.lock` (adres küçük harf; yalnız 0x + onaltılık, başka karakter atılır)."""
    return "motor-" + re.sub(r"[^0-9a-fx]", "", str(adres).strip().lower())[:42] + ".lock"


def hesap_kilidi_al(ust_dizin: Path, adres: str) -> int:
    """Y-5: HL HESABI başına kilit: durum dizininin ÜST dizininde (systemd: `/var/lib/sg-canli`) `motor-<adres>.lock`, `flock`. Aynı sunucuda aynı hesapla BAŞKA bir durum dizini
    (`--durum-dizin`) kullanan ikinci gerçek motor da açılmaz (çıkış 3). Başka sunucudaki motor yakalanmaz: ona karşı açılışta yabancı açık emir denetimi (`yabanci_emir_denetle`)."""
    return _flock_al(Path(ust_dizin) / hesap_kilidi_adi(adres), "başka bir motor süreci bu HL hesabını kullanıyor (hesap kilidi dolu): ikinci motor açılmaz")


def yabanci_emir_denetle(post: Callable[[dict], Any], adres: str, niyet_yolu: Path) -> None:
    """Y-5: gerçek kip açılışı. Kendi HL hesabımızdaki (tüm perp dex) AÇIK emirler okunur (`openOrders`); motor yalnız IOC verdiğinden açık emir beklenmez. `cloid`'i niyet kaydımızda
    (`niyet.jsonl`) OLMAYAN (ya da cloid'siz) açık emir varsa = başka motor / elle emir → KipHatasi (çıkış 3, açık mesaj). Okuma/biçim hatası `HlOkunamadi` (geçici, 75)."""
    bilinen = {str(x.get("cloid") or "").lower() for x in Niyet(Path(niyet_yolu)).satirlar() if x.get("t") == "niyet"}
    try:
        dexler = perp_dex_names(post({"type": "perpDexs"}))
    except (TypeError, ValueError, KeyError) as hata:
        raise HlOkunamadi(f"perpDexs okunamadı ({type(hata).__name__})") from hata
    yabanci: list[dict] = []
    for dex in ["", *dexler]:
        liste = post({"type": "openOrders", "user": adres, **({"dex": dex} if dex else {})})
        if not isinstance(liste, list):
            raise HlOkunamadi("openOrders yanıtı geçersiz")
        yabanci += [e for e in liste if not isinstance(e, dict) or not e.get("cloid") or (str(e.get("cloid")).lower() not in bilinen and not borsa_stop.bizim_mi(e.get("cloid")))]      # K-64: borsa stopu önekli emirler bizim
    if yabanci:
        ornek = ", ".join(str((e or {}).get("coin", "?")) for e in yabanci[:3] if isinstance(e, dict))
        raise KipHatasi(f"HL hesabında motorun niyet kaydında olmayan {len(yabanci)} açık emir var ({ornek}): ikinci motor ya da elle emir olabilir. "
                        "Emirleri kontrol edip iptal edin, başka motor çalışmadığından emin olun; sonra yeniden başlatın")


def motor_kilidi_tutuluyor(dizin: Path) -> bool | None:
    """SALT OKUNUR: `<durum-dizin>/motor.lock` başka bir süreçte kilitli mi (çalışan motor var mı). Dosya yoksa False; açılamazsa None. Dosya/dizin OLUŞTURMAZ."""
    import fcntl
    yol = Path(dizin) / "motor.lock"
    if not yol.is_file():
        return False
    try:
        fd = os.open(yol, os.O_RDONLY)
    except OSError:
        return None
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        except OSError:
            return None
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


def durum_incele(dizin: Path, kip: str, kasa_ayar: float | None = None) -> dict:
    """G-20 `--kontrol`: ASIL durum dizinini SALT OKUNUR inceler (dosya yazmaz, dizin oluşturmaz). Kurallar `Motor.kip_uyumu_denetle` / `baslat` ile aynı: kayıtlı kip ≠ geçerli kip → uyumsuz;
    gerçek kipte ayarlı kasa değişmiş ve yerel açık pozisyon var → uyumsuz. Ayrıca `DUR` dosyası, `risk.json` `acilis_durdu.mutabakat`, yerel açık pozisyon sayısı, `motor.lock` tutuluyor mu."""
    dizin = Path(dizin)
    m, h, rk = _oku(dizin / "motor.json"), _oku(dizin / "hesap.json"), _oku(dizin / "risk.json") or {}
    durum_var = bool(m) or h is not None
    kayitli_kip = str((m or {}).get("kip") or "sanal") if durum_var else None
    acik = 0
    for coinler in ((h or {}).get("poz") or {}).values():
        for p in (coinler or {}).values() if isinstance(coinler, dict) else []:
            try:
                acik += abs(float((p or {}).get("sz") or 0.0)) > EPS
            except (TypeError, ValueError, AttributeError):
                acik += 1                                                   # okunamayan pozisyon kaydı: açık say (güvenli taraf)
    neden = None
    if durum_var and kayitli_kip != kip:
        neden = "sanal durum dizininde gerçek kip açılmaz (dizini arşivleyin: deploy/kurulum.md)" if kip == "gercek" else "gerçek durum dizininde sanal kip açılmaz"
    elif durum_var and kip == "gercek" and kasa_ayar is not None and (m or {}).get("kasa_ayar_usd") is not None and abs(float(m["kasa_ayar_usd"]) - float(kasa_ayar)) > 1e-9 and acik:
        neden = f"kasa ayarı değişti ({float(m['kasa_ayar_usd']):g} → {float(kasa_ayar):g} $) ama açık pozisyon var"
    return {"dizin": str(dizin), "dizin_var": dizin.is_dir(), "durum_var": durum_var, "kayitli_kip": kayitli_kip, "kip_uyumu": neden is None, "kip_neden": neden,
            "dur": (dizin / "DUR").exists(), "mutabakat": bool((rk.get("acilis_durdu") or {}).get("mutabakat")), "risk_dur": bool(rk.get("dur")), "yerel_acik_poz": acik,
            "motor_calisiyor": motor_kilidi_tutuluyor(dizin)}


def hl_acik_say(post: Callable[[dict], Any], adres: str, dexler: list[str]) -> tuple[int, int]:
    """G-20: kendi HL hesabımızda (tüm perp dex) açık pozisyon ve açık (bekleyen) emir SAYISI. Okuma ya da biçim hatası istisna yükseltir (kısmi sayı dönmez)."""
    poz = emir = 0
    for dex in ["", *dexler]:
        poz += sum(1 for v in clearinghouse_ayristir(post(clearinghouse_yuk(adres, dex))).values() if abs(v) > EPS)
        liste = post({"type": "openOrders", "user": adres, **({"dex": dex} if dex else {})})
        if not isinstance(liste, list):
            raise ValueError("openOrders yanıtı geçersiz")
        emir += len(liste)
    return poz, emir


def saat_sapmasi(post: Callable[[dict], Any], saat_ms: Callable[[], int] | None = None, sinir_ms: float | None = None) -> dict:
    """G-20: sunucu saati − HL sunucu saati (ms; `l2Book` yanıtındaki `time`, istek gidiş-dönüşünün ortası ile). + = sunucu ileride. `ok`: |sapma| − gidiş_dönüş/2 ≤ sınır."""
    saat_ms = saat_ms or (lambda: int(time.time() * 1000))
    sinir = SAAT_SAPMA_SINIR_MS if sinir_ms is None else sinir_ms
    t0 = saat_ms()
    kitap = post({"type": "l2Book", "coin": "BTC"})
    t1 = saat_ms()
    hl = kitap.get("time") if isinstance(kitap, dict) else None
    if isinstance(hl, bool) or not isinstance(hl, (int, float)) or not math.isfinite(hl):
        raise ValueError("l2Book yanıtında time yok")
    sapma, gd = (t0 + t1) / 2 - float(hl), t1 - t0
    return {"sapma_ms": int(round(sapma)), "gidis_donus_ms": int(gd), "sinir_ms": sinir, "ok": abs(sapma) - gd / 2 <= sinir}


def telegram_deneme(tgram: tg.Telegram, kip: str) -> bool:
    """G-20: gerçek bir `sendMessage` (deneme). Gönderildiyse True. Token yoksa False (gönderim denenmez)."""
    if not tgram.acik:
        return False
    kip_metni = "GERÇEK PARA" if kip == "gercek" else "sanal"
    try:
        return bool(tgram.gonder(f"🚨 DENEME — açılış kontrolü ({kip_metni} kipi): bu mesaj geldiyse Telegram çalışıyor. Emir gönderilmedi."))
    except Exception:                                      # noqa: BLE001 - hata metninde URL (token) olabilir: yazılmaz
        return False


def kontrol(rules: dict, kip: str, post: Callable[[dict], Any], kadro_oku: Callable[[], dict | None], tgram: tg.Telegram, ortam: dict | None = None, turet: Callable[[str], str] | None = None,
            sanal_kasa: float | None = None, durum_dizin: Path | None = None, saat_ms: Callable[[], int] | None = None) -> dict:
    """`--kontrol` (T5 açılış kontrolü): anahtar, bakiye, HL bağlantısı, kadro okuma, Telegram — EMİR GÖNDERMEZ, durum dizinine YAZMAZ. Döner rapor; `tamam` zorunluların hepsi geçtiyse True.
    G-20: `durum_dizin` verilirse ASIL durum dizini salt okunur incelenir (`durum`: kip uyumu, DUR, mutabakat, yerel açık pozisyon, çalışan motor). Gerçek kipte ek zorunlular:
    kadro `taze`, HL hesabında açık emir 0 (IOC dışında bekleyen emir olmaz) ve durum dizini boşsa açık pozisyon 0, saat sapması ≤ `SAAT_SAPMA_SINIR_MS`, gerçek Telegram deneme mesajı gitti, mutabakat bayrağı kapalı."""
    ortam = os.environ if ortam is None else ortam
    saat_ms = saat_ms or (lambda: int(time.time() * 1000))
    try:
        kasa, kaynak = kasa_belirle(rules, kip, ortam, **({} if sanal_kasa is None else {"sanal_kasa": sanal_kasa}))
        kasa_hata = None
    except KipHatasi as hata:
        kasa, kaynak, kasa_hata = float(rules["canli_kasa_usd"]), "yaml", str(hata)
    r: dict[str, Any] = {"kip": kip, "kasa_usd": kasa, "kasa_kaynagi": kaynak}          # kaynak: "ortam" (gerçek kip CANLI_KASA_USD) | "yaml" (sanal) | "arg" (sanal, --sanal-kasa-usd)
    if kasa_hata:
        r["kasa_hata"] = kasa_hata
    r["kasa_siniri_ok"] = kasa_hata is None and r["kasa_usd"] <= kasa_ust(rules, kip)
    r["anahtar"] = bool(ortam.get("HL_API_CUZDAN_ANAHTARI")) and bool(ortam.get("HL_HESAP_ADRESI"))        # değerler ASLA yazılmaz
    try:
        r["hl_baglanti"] = len(post({"type": "meta"})["universe"]) > 0
    except Exception as hata:                              # noqa: BLE001
        r["hl_baglanti"], r["hl_hata"] = False, type(hata).__name__
    r["bakiye_usd"] = r["hl_hesap_degeri"] = None
    r["etkin_kasa_usd"] = r["kasa_usd"]
    dexler: list[str] | None = None
    if r["anahtar"] and ortam.get("HL_HESAP_ADRESI"):
        try:
            dexler = perp_dex_names(post({"type": "perpDexs"}))
            hl = hesap_degeri_oku(post, ortam["HL_HESAP_ADRESI"], dexler)
            r["bakiye_usd"] = r["hl_hesap_degeri"] = hl                        # tüm perp dex + spot USDC (K‑35)
            r["etkin_kasa_usd"] = min(r["kasa_usd"], hl) if kip == "gercek" else r["kasa_usd"]      # gerçek kip: min(ayar, HL hesap değeri)
        except Exception as hata:                          # noqa: BLE001
            r["bakiye_hata"] = type(hata).__name__
    try:
        k = kadro_oku()
        r["kadro"] = {"var": k is not None, "taze": bool(k) and kadro_taze_mi(k, saat_ms(), rules)[0], "satir": len((k or {}).get("satirlar", [])), "kosu_ms": (k or {}).get("kosu_ms")}
    except Exception as hata:                              # noqa: BLE001
        r["kadro"] = {"var": False, "taze": False, "hata": type(hata).__name__}
    r["telegram"] = {"yapilandirildi": tgram.acik}
    r["emir_gonderildi"] = False
    zorunlu = [r["kasa_siniri_ok"], r["hl_baglanti"], r["kadro"].get("var")]
    if durum_dizin is not None:
        r["durum"] = durum_incele(Path(durum_dizin), kip, None if kasa_hata else kasa)
        zorunlu += [r["durum"]["kip_uyumu"], not r["durum"]["dur"]]
    if kip == "gercek":
        ap = api_cuzdan_dogrula(post, ortam, turet) if r["anahtar"] else {"ana_anahtar": False, "agent_dogrulandi": False, "tamam": False, "neden": "anahtar yok"}
        r["ana_anahtar"], r["agent_dogrulandi"], r["api_cuzdan_tamam"], r["api_cuzdan_neden"] = ap["ana_anahtar"], ap["agent_dogrulandi"], ap["tamam"], ap["neden"]       # yalnız bool/sabit metin
        r["hl_deger_siniri_ok"] = r["hl_hesap_degeri"] is not None and r["hl_hesap_degeri"] <= hl_deger_ust(rules) + 1e-9          # K‑22: hesap değeri ≤ `canli_hl_deger_ust_usd` (1.500 $); kasa ayrıca ≤ 1.000 $
        r["hl_acik_poz"] = r["hl_acik_emir"] = None
        if r["anahtar"] and dexler is not None:
            try:
                r["hl_acik_poz"], r["hl_acik_emir"] = hl_acik_say(post, ortam["HL_HESAP_ADRESI"], dexler)
            except Exception as hata:                      # noqa: BLE001
                r["hl_acik_hata"] = type(hata).__name__
        durum_bos = not (r.get("durum") or {}).get("durum_var")
        r["hl_acik_ok"] = r["hl_acik_emir"] == 0 and r["hl_acik_poz"] is not None and (r["hl_acik_poz"] == 0 or not durum_bos)      # boş durum dizini + HL'de pozisyon = motorun bilmediği yetim
        try:
            r["saat"] = saat_sapmasi(post, saat_ms)
        except Exception as hata:                          # noqa: BLE001
            r["saat"] = {"ok": False, "hata": type(hata).__name__}
        r["telegram"]["deneme_gonderildi"] = telegram_deneme(tgram, kip)
        zorunlu += [r["anahtar"], r["bakiye_usd"] is not None, tgram.acik, r["api_cuzdan_tamam"], r["hl_deger_siniri_ok"], r["kadro"].get("taze"), r["hl_acik_ok"], r["saat"]["ok"],
                    r["telegram"]["deneme_gonderildi"]]
        if "durum" in r:
            zorunlu.append(not r["durum"]["mutabakat"])
    r["tamam"] = all(bool(x) for x in zorunlu)
    return r


def baslamadi_alarmi(tgram: tg.Telegram, hata: object, kod: int = CIKIS_KALICI) -> None:
    """Vardiya `kilit_al` öncesi başlayamadı: stderr'e ek olarak Telegram alarmı (kanal kapalıysa yalnız kayda yazılır). `kod` 75 = geçici (systemd yeniden dener)."""
    if any(str(hata) in m for m in tgram.gonderilen):             # kilit_al zaten alarm gönderdi: çift mesaj yok
        return
    ek = " (geçici: HL/ağ okunamadı); systemd artan beklemeyle yeniden deneyecek. Motor şu an çalışmıyor." if kod == CIKIS_GECICI else "; motor çalışmıyor."
    try:
        tgram.gonder(tg.alarm("Vardiya BAŞLAMADI", f"{str(hata)[:300]}\nÇıkış kodu {kod}{ek}"))
    except Exception as e:                                          # noqa: BLE001 - alarm hatası çıkış kodunu değiştirmez
        print(f"Telegram alarmı gönderilemedi: {type(e).__name__}", file=sys.stderr)


RADAR_SURUM_DOSYA = Path(__file__).with_name("RADAR_SURUM")


def radar_surum_oku(yol: Path = RADAR_SURUM_DOSYA) -> str | None:
    """K-54: motorun uygulayacağı kadronun `radar_surum`'u (dosyanın ilk boş olmayan, `#` ile başlamayan satırı). Dosya yok / boş → None (her kadro)."""
    try:
        satirlar = [x.strip() for x in yol.read_text(encoding="utf-8").splitlines()]
    except OSError:
        return None
    return next((x for x in satirlar if x and not x.startswith("#")), None)


DONEM_DOSYA = Path(__file__).with_name("DONEM")


def donem_ms(donem: str | None) -> int | None:
    """Dönem başı (UTC ISO) → UTC ms; yok/bozuk → None."""
    if not donem:
        return None
    try:
        return int(datetime.fromisoformat(donem.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def aylik_esdeger(getiri: float | None, gun_sayi: float | None, en_az_gun: float = 1.0) -> float | None:
    """F-06 başarı ölçütü (31.12: ayda ≥ %4 VE BTC al-tut'tan iyi): dönem getirisi R, geçen gün d → aylık eşdeğer = (1 + R)^(30 / d) − 1.
    d < `en_az_gun` (1 gün; çok kısa sürede üs patlar) ya da R ≤ −1 / veri yok → None. Altın: R = 0,02, d = 15 → 1,02² − 1 = 0,0404."""
    if getiri is None or gun_sayi is None or gun_sayi < en_az_gun or getiri <= -1:
        return None
    return (1.0 + float(getiri)) ** (30.0 / float(gun_sayi)) - 1.0


def donem_oku(yol: Path = DONEM_DOSYA) -> str | None:
    """Sanal dönem başlangıcı (UTC ISO, ör. 2026-11-14T15:15:00Z; `.github/scripts/donem_geri.sh` ile aynı dosya). Yok / boş / bozuk → None (BTC kıyası "—")."""
    try:
        metin = yol.read_text(encoding="utf-8").strip()
        datetime.fromisoformat(metin.replace("Z", "+00:00"))
    except (OSError, ValueError):
        return None
    return metin or None


def _baslamadi(tgram: tg.Telegram, hata: object, kod: int) -> int:
    print(f"BAŞLAMADI{' (geçici)' if kod == CIKIS_GECICI else ''}: {hata}", file=sys.stderr)
    baslamadi_alarmi(tgram, hata, kod)
    return kod


def acilis_yeniden_dene(is_: Callable[[], Any], bekle: tuple[float, ...] | None = None, uyu: Callable[[float], Any] = time.sleep, bildir: Callable[[str], Any] | None = None) -> Any:
    """G-15: açılış HL okumaları. Geçici hata (`HlOkunamadi`, ağ `OSError`, 429 sonrası `RateLimitError`) → `bekle` (varsayılan `ACILIS_BEKLEME_SN`) sırasıyla bekleyip yeniden dener;
    tükenirse `HlOkunamadi` yükselir (çıkış 75). Kalıcı `KipHatasi` ve diğer istisnalar HEMEN yükselir."""
    bekle = ACILIS_BEKLEME_SN if bekle is None else bekle
    son: HlOkunamadi | None = None
    for i in range(len(bekle) + 1):
        try:
            return is_()
        except _GECICI_HATALAR as hata:
            son = hata if isinstance(hata, HlOkunamadi) else HlOkunamadi(f"HL okunamadı ({type(hata).__name__})")
        if i < len(bekle):
            if bildir:
                bildir(f"{son} — {bekle[i]:g} sn sonra yeniden denenecek ({i + 1}/{len(bekle)})")
            uyu(bekle[i])
    assert son is not None
    raise son


def _borsada_pozisyon_var(post: Callable[[dict], Any]) -> bool:
    """D-11: kendi HL hesabımızda (tüm perp dex) açık pozisyon var mı. Okunamazsa `HlOkunamadi` (geçici: yeniden denenir; belirsizlikte açılış tavanı reddi kalıcı sayılmaz)."""
    try:
        hl = clearinghouse_pozisyonlari(post, os.environ.get("HL_HESAP_ADRESI", ""), perp_dex_names(post({"type": "perpDexs"})))
    except Exception as hata:                              # noqa: BLE001
        raise HlOkunamadi(f"HL pozisyonları okunamadı ({type(hata).__name__}): kapanış modu kararı verilemedi") from hata
    return any(abs(v) > EPS for v in hl.values())


def acilis_hl_denetle(rules: dict, kip: str, post: Callable[[dict], Any], sk: dict, niyet_yolu: Path | None = None, kapanis_modu_izni: bool = False) -> tuple[float, float | None]:
    """Açılışın HL'ye bağlı adımları (bir deneme): gerçek kipte API cüzdanı (G6) + etkin kasa + HL değer sınırı (K‑22) + (Y-5, `niyet_yolu` verilirse) yabancı açık emir yok.
    Kalıcı ret `KipHatasi`; HL okunamadı `HlOkunamadi` (G-15). 2. denetim D-11 (K-70): `kapanis_modu_izni` iken HL değeri tavanı aşıyorsa ve borsada AÇIK POZİSYON varsa reddedilmez
    (çağıran `hl_deger > hl_deger_ust` ile "yalnız kapanış modu" kurar); pozisyon yoksa bugünkü ret (çıkış 3) kalır."""
    if kip == "gercek":                                    # G6: emirden önce API cüzdanı doğrulaması (ana anahtar / agent değil → başlamaz)
        dogrulama = api_cuzdan_dogrula(post, os.environ)
        if not dogrulama["tamam"]:
            if dogrulama.get("hl_okunamadi"):
                raise HlOkunamadi(f"API cüzdanı denetlenemedi: {dogrulama['neden']}")
            raise KipHatasi(f"API cüzdanı doğrulanamadı: {dogrulama['neden']}")
    kasa, hl_deger = etkin_kasa(rules, kip, post, **sk)
    if kip == "gercek" and hl_deger is not None and hl_deger > hl_deger_ust(rules) + 1e-9 and kapanis_modu_izni and _borsada_pozisyon_var(post):
        return kasa, hl_deger                                  # D-11: açık pozisyon yönetimsiz kalmasın → yalnız kapanış modunda başla (yeni açılış yok)
    if kip == "gercek" and hl_deger is not None and hl_deger > hl_deger_ust(rules) + 1e-9:          # HL tavanı 1.500 $ (kasa yine ≤ 1.000 $: min(ayar, HL))
        raise KipHatasi(f"HL hesap değeri {hl_deger:.0f} $ > sınır {hl_deger_ust(rules):g} $ (K‑22): kârı çekin ya da kullanıcı kararı")
    if kip == "gercek" and niyet_yolu is not None:
        yabanci_emir_denetle(post, os.environ.get("HL_HESAP_ADRESI", ""), niyet_yolu)
    return kasa, hl_deger


def _motor_calistir(args: argparse.Namespace, rules: dict, kip: str, post: Callable[[dict], Any], kadro_oku: Callable[[], dict | None], tgram: tg.Telegram, sk: dict,
                    post_hizli: Callable[[dict], Any] | None = None) -> int:
    """Açılış + ana döngü. Çıkış kodları: 0 temiz; 1 beklenmedik (systemd yeniden başlatır); 3 kalıcı (yeniden başlatılmaz); 75 geçici HL/ağ (yeniden başlatılır) — G-15."""
    post_hizli = post_hizli or post

    def bildir(m: str) -> None:
        print(f"açılış: {m}", file=sys.stderr)
    try:
        if kip == "gercek" and (os.environ.get("HL_AG") or "").strip():
            raise KipHatasi("HL_AG ayarlı: motor yalnız ana ağda çalışır (testnet yalnız `copytrade.canli.stop_deneme` içindir); HL_AG satırını ortamdan kaldırın")      # K-64
        kasa, hl_acilis = acilis_yeniden_dene(lambda: acilis_hl_denetle(rules, kip, post, sk, Path(args.durum_dizin) / "niyet.jsonl", kapanis_modu_izni=True), bildir=bildir)
        kapanis_modu = kip == "gercek" and hl_acilis is not None and hl_acilis > hl_deger_ust(rules) + 1e-9          # D-11: HL > 1.500 $ ve açık pozisyon var (yoksa denetle zaten reddetti)
        try:
            rules = {**rules, "canli_kasa_ayar_usd": kasa_belirle(rules, kip, **sk)[0], "canli_kasa_usd": kasa}
            if sk:
                rules["canli_kasa_kaynagi"] = "arg"                     # G5: Motor sanal kasa uyumunu denetler (bayraksız koşuda anahtar yok, davranış aynı)
            boyut.saha_sayisi(kasa, rules)
        except ValueError as hata:                                      # D-9: ValueError YALNIZ kasa/boyut ayarında kalıcıdır (3)
            raise KipHatasi(f"kasa/boyut ayarı geçersiz: {hata}") from hata
    except HlOkunamadi as hata:
        return _baslamadi(tgram, hata, CIKIS_GECICI)
    except KipHatasi as hata:
        return _baslamadi(tgram, hata, CIKIS_KALICI)
    except ValueError as hata:                                          # D-9: HL ayrıştırma vb. beklenmeyen ValueError (geçici HL bozukluğu servisi kalıcı durdurmasın): geçici (75)
        return _baslamadi(tgram, HlOkunamadi(f"açılışta beklenmeyen ayrıştırma hatası ({type(hata).__name__})"), CIKIS_GECICI)
    try:
        yur: Yurutucu = acilis_yeniden_dene(lambda: gercek_yurutucu_olustur(post_hizli, rules), bildir=bildir) if kip == "gercek" else SanalYurutucu(post_hizli, rules)
    except HlOkunamadi as hata:
        return _baslamadi(tgram, hata, CIKIS_GECICI)
    except AnahtarYok as hata:
        return _baslamadi(tgram, hata, CIKIS_KALICI)
    except (RuntimeError, ValueError) as hata:                     # SDK kurulu değil / anahtar biçimi bozuk: metin anahtar içerebilir, yalnız tür adı
        return _baslamadi(tgram, KipHatasi(f"gerçek yürütücü kurulamadı ({type(hata).__name__})"), CIKIS_KALICI)
    try:
        motor = Motor(rules, yur, post, tgram, args.durum_dizin, args.kayit_dizin or (args.durum_dizin / "kayit"), kadro_oku, vardiya_id=args.vardiya, **({"post_hizli": post_hizli} if post_hizli is not post else {}))
        motor.devral_vardiya = str(args.devral_vardiya or "")
    except DurumBozuk as hata:                                      # Denetim-2: bozuk/eksik durum (gerçek kip) → kalıcı çıkış + alarm; stop iptali hiç çağrılmaz
        return _baslamadi(tgram, hata, CIKIS_KALICI)
    motor.kapanis_modu = kapanis_modu
    motor.radar_surum_gerekli = radar_surum_oku()
    motor.donem = donem_oku()
    try:
        motor.baslat()
    except HlOkunamadi as hata:
        return _baslamadi(tgram, hata, CIKIS_GECICI)
    except KipHatasi as hata:
        return _baslamadi(tgram, hata, CIKIS_KALICI)
    except _GECICI_HATALAR as hata:                                 # açılış okumalarında ağ hatası: geçici (systemd yeniden başlatır)
        return _baslamadi(tgram, HlOkunamadi(f"açılışta HL okunamadı ({type(hata).__name__})"), CIKIS_GECICI)
    ozet = asyncio.run(calis(motor, args.sure_sn))
    print(json.dumps(ozet, ensure_ascii=False, indent=1, default=str))
    return int(getattr(motor, "cikis_kodu", 0))           # G-12b: görev beklenmedik bittiyse 1 (systemd yeniden başlatır)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kontrol", action="store_true", help="emir göndermeden anahtar/bakiye/HL/kadro/Telegram/durum dizini kontrolü (durum dizinine YAZMAZ); rapor stdout'a")
    ap.add_argument("--rapor", type=Path, default=None, help="--kontrol raporunun yazılacağı dosya (gerçek kipte varsayılan: yazılmaz; sanal kipte <durum-dizin>/kontrol.json)")
    ap.add_argument("--kip", choices=["sanal", "gercek"], default=None, help="varsayılan kurallar.yaml canli_kip (sanal)")
    ap.add_argument("--durum-dizin", type=Path, default=Path(os.environ.get("STATE_DIRECTORY", "durum")), help="gerçek kipte MUTLAK yol zorunlu (G-21)")
    ap.add_argument("--kayit-dizin", type=Path, default=None)
    ap.add_argument("--sure-sn", type=float, default=None, help="vardiya süresi (sn); varsayılan sonsuz")
    ap.add_argument("--kadro-dali", default=None, help="kadro.json veri dalı (varsayılan canli_kadro_dali; dal doğrulamasında radar-deneme)")
    ap.add_argument("--vardiya", default="yerel")
    ap.add_argument("--devral-vardiya", default="", help="iş akışının BİTMİŞ doğruladığı önceki vardiya kimliği: kilit sahibi bu ise (bırakılmamış olsa da) kilit devralınır; boş = devralma yok")
    ap.add_argument("--sanal-kasa-usd", type=float, default=None, help="yalnız sanal kip: kasa $ (0 < kasa <= canli_sanal_kasa_ust_usd; K-66); varsayılan kurallar.yaml canli_kasa_usd. Ayrı --durum-dizin ile (G5)")
    args = ap.parse_args(argv)
    rules = load_rules()
    tgram = tg.Telegram(arka_plan=not args.kontrol, sessiz_utc=(int(rules["canli_telegram_sessiz_bas_utc"]), int(rules["canli_telegram_sessiz_bit_utc"])))
    try:
        kip = kip_belirle(rules, args.kip)
        tgram.kip = kip                                    # S-22: açılış alarmlarında da kip etiketi
        if args.sanal_kasa_usd is not None:
            sanal_kasa_dogrula(rules, kip, args.sanal_kasa_usd)          # gerçek kipte / sınır dışında erken ret (kontrol dahil)
        if not args.kontrol:
            durum_dizin_dogrula(args.durum_dizin, kip)                   # G-21: gerçek kipte mutlak yol
    except (KipHatasi, AnahtarYok) as hata:
        print(f"BAŞLAMADI: {hata}", file=sys.stderr)
        if not args.kontrol:
            baslamadi_alarmi(tgram, hata)
        return CIKIS_KALICI
    sk = {} if args.sanal_kasa_usd is None else {"sanal_kasa": args.sanal_kasa_usd}      # bayrak yoksa çağrılar birebir eskisi (1.000 $ seri değişmez)
    post = rest_post_olustur(rules)
    kadro_oku = lambda: http_kadro_oku(rules, args.kadro_dali)          # noqa: E731
    if args.kontrol:
        rapor = kontrol(rules, kip, post, kadro_oku, tgram, durum_dizin=args.durum_dizin, **sk)
        hedef = args.rapor if args.rapor is not None else (None if kip == "gercek" else args.durum_dizin / "kontrol.json")     # G-20: gerçek kipte asıl durum dizinine YAZILMAZ
        if hedef is not None:
            try:
                _yaz(hedef, rapor)
            except OSError as hata:                                     # salt okunur birimde (sg-canli-kontrol) yazılamaz: rapor yine stdout'ta
                print(f"kontrol raporu dosyaya yazılamadı ({type(hata).__name__}); stdout'a yazılıyor", file=sys.stderr)
        print(json.dumps(rapor, ensure_ascii=False, indent=1))
        return 0 if rapor["tamam"] else 1
    kilit_fd: int | None = None
    hesap_fd: int | None = None
    try:
        if kip == "gercek":
            try:
                ortam_izin_zorunlu()                                      # Denetim-8: ortam dosyası izni 600 değilse başlama
                kilit_fd = motor_kilidi_al(args.durum_dizin)              # G-21: aynı durum dizininde ikinci gerçek süreç → 3
                adres = os.environ.get("HL_HESAP_ADRESI", "").strip()
                if adres:
                    hesap_fd = hesap_kilidi_al(Path(args.durum_dizin).parent, adres)      # Y-5: aynı hesap, başka durum dizini → 3
            except KipHatasi as hata:
                return _baslamadi(tgram, hata, CIKIS_KALICI)
        try:
            return _motor_calistir(args, rules, kip, post, kadro_oku, tgram, sk, rest_post_hizli_olustur(post))
        except Exception as hata:                                       # noqa: BLE001 - beklenmedik: iz günlüğe, kısa alarm (yalnız tür adı), 1 (systemd yeniden başlatır)
            import traceback
            traceback.print_exc()
            try:
                acik = durumdan_acik_poz(Path(args.durum_dizin))
                bot_durdu_gonder(tgram, Path(args.durum_dizin), f"beklenmedik hata ({type(hata).__name__})", acik or 0,
                                 "gerekmiyor (pozisyon yok)" if acik == 0 else ("borsada duruyor" if kip == "gercek" else "bot kapalıyken yazılım stopu çalışmıyor") if acik else "bilinmiyor",
                                 son="Yeni işlem açılmıyor; sistem motoru kendiliğinden yeniden başlatıyor.", senden=tg.SENDEN_YOK)
            except Exception:                                           # noqa: BLE001
                pass
            return 1
    finally:
        for fd in (hesap_fd, kilit_fd):
            if fd is not None:
                os.close(fd)


if __name__ == "__main__":
    sys.exit(main())
