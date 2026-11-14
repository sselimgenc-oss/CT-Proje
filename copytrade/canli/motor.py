"""Canlı motor (T4; K‑29): tek süreç, iki kip (sanal / gerçek), TEK kod yolu. docs/GOREV_T4_CANLI_MOTOR.md, docs/RADAR_V1.md §5–§6.

Akış: `dinleyici.py` WebSocket (trades + userFills; İlk 11'in sahadaki adresleri) → tekilleştirilmiş dolum (`Olay`) → trader pozisyon izleyicisi → `boyut.hedef_emir` (tek boyutlandırma) → risk (`risk.py`)
→ yürütücü (`yurutucu.py`: sanal l2Book yürüyüşü / gerçek HL SDK) → hesap (`hesap.py`) → kayıt JSONL + Telegram. Saha kararları `kadro.py` (kadro.json, her 5 dk).

Kip güvencesi (G4): varsayılan SANAL. `gercek` YALNIZ sunucu ortamında `CANLI_KIP=gercek` + `HL_API_CUZDAN_ANAHTARI`/`HL_HESAP_ADRESI` ile (`kurallar.yaml canli_kip` yalnız `sanal`; depodan gerçek kip açılamaz) ve ASLA GitHub Actions'ta (`GITHUB_ACTIONS=true` + `CANLI_*` → ret).
Kasa: sanal kip `canli_kasa_usd` (yaml) ya da `--sanal-kasa-usd` (yalnız sanal; 0 < kasa ≤ `canli_sanal_kasa_ust_usd` (K-66: 10.000 $); ayrı durum dizini/veri dalı, ör. 300 $ paralel seri `canli-durum-300`); gerçek kip `CANLI_KASA_USD` ortam değişkeni ($, zorunlu; üst sınır `canli_kasa_ust_usd` = 1.000 $ — AGENTS.md): sınır aşılırsa yeni açılış yok + alarm.
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
from copytrade.canli.hesap import Hesap
from copytrade.canli.kadro import Karar, Saha, kadro_taze_mi
from copytrade.canli.mutabakat import poz_farki, sanal_tutarlilik
from copytrade.canli.niyet import Niyet, cloid_uret
from copytrade.canli import borsa_stop
from copytrade.canli.borsa_stop import BorsaStop
from copytrade.canli.risk import Risk, gun
from copytrade.canli.yurutucu import AnahtarYok, Dolum, SanalYurutucu, Yurutucu, gercek_yurutucu_olustur
from copytrade.dinleyici import Ayar, Dinleyici, Izlenen, Olay, clearinghouse_ayristir, clearinghouse_pozisyonlari, clearinghouse_yuk, coin_listesi, rest_dolumlar, rest_post_fabrikasi, ws_baglan
from copytrade.hl_ortak import spot_usdc
from copytrade.izleme_liste import perp_dex_names
from copytrade.kurallar import load_rules
from copytrade.coin_sinif import asset_class
from copytrade.tarama import KAPI_YENIDEN_BEKLEME, PublicClient, RateLimiter, RateLimitError, ledger_sayfala

EPS = 1e-12
DAKIKA = 60_000
SNAP_SAKLA = 50_000          # adet (yalnız snapshot görülen dolum kimlikleri, bellekte; HL userFills snapshot'ı adres başına ≤ 2000 dolum × 10 adres + trades snapshot'ları)


ADIM_ALARM_ARDISIK = 3                     # M-2: aynı dakikalık adım üst üste bu kadar hata verirse Telegram alarmı
KUYRUK_GERI_DK = (1, 2, 4, 8, 16, 30)      # S-8: kapanış kuyruğu yeniden deneme aralıkları (dk; üstel, tavan 30)
AGIRLIK = {"allMids": 2, "l2Book": 2, "clearinghouseState": 2, "perpDexs": 20, "orderStatus": 2, "meta": 20, "metaAndAssetCtxs": 20, "userFillsByTime": 20, "spotClearinghouseState": 2, "userRole": 60}          # HL info istek ağırlıkları (belge); bilinmeyen 20


class GuvenliLimiter(RateLimiter):
    """Birden çok iş parçacığı (olay işleme, dakikalık bakım, dinleyici REST) aynı hız sınırını paylaşır: `acquire` kilitli (sıraya girer)."""

    def __init__(self, *a: Any, **k: Any) -> None:
        super().__init__(*a, **k)
        self._kilit = threading.Lock()

    def acquire(self, weight: int) -> None:
        with self._kilit:
            super().acquire(weight)


def rest_post_olustur(rules: dict, istemci: PublicClient | None = None) -> Callable[[dict], Any]:
    """Motorun TÜM REST istekleri (kural 7: `tarama.PublicClient`): ortak ağırlık sınırı `canli_api_agirlik_dk`, 429 (5 yeniden deneme, `Retry-After`) ve 5xx / ağ hatasında 3 yeniden deneme.
    Duman testinde (gerçek HL) açılışta ardışık `clearinghouseState` okumaları HTTP 429 aldı → bu sınırlayıcı eklendi."""
    c = istemci or PublicClient(limiter=GuvenliLimiter(limit=int(rules["canli_api_agirlik_dk"])), yeniden_bekleme=KAPI_YENIDEN_BEKLEME)

    def post(yuk: dict) -> Any:
        return c.info(yuk, weight=AGIRLIK.get(str(yuk.get("type")), 20))
    post.stats = getattr(c, "stats", None)                 # type: ignore[attr-defined] — rapor için istek / 429 sayaçları (T6 §3)
    return post


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
        return portfolio_son_deger(post, adres)
    durum = post({"type": "spotClearinghouseState", "user": adres}) or {}
    spot = sum(float(b.get("total", 0) or 0) for b in durum.get("balances", []) if str(b.get("coin")) == "USDC")
    if soyut == "unifiedAccount":
        return spot
    toplam = 0.0
    for dex in ["", *dexler]:
        toplam += float(post(clearinghouse_yuk(adres, dex))["marginSummary"]["accountValue"])
    return toplam + spot


class KipHatasi(RuntimeError):
    """Kip kuralı ihlali (gerçek kip Actions'ta / ayar yok): motor BAŞLAMAZ."""


class HlOkunamadi(KipHatasi):
    """G-15: açılışta HL okuması (ağ, zaman aşımı, 5xx, 429, bozuk yanıt) başarısız — GEÇİCİ neden. `main` artan beklemeyle yeniden dener, olmazsa `CIKIS_GECICI` (75) ile çıkar
    (systemd `Restart=on-failure` yeniden başlatır). Kalıcı nedenler (DUR, kip uyumsuzluğu, ana anahtar, kasa sınırı, agent listede yok, çift süreç) `KipHatasi` → `CIKIS_KALICI` (3)."""


CIKIS_KALICI = 3             # kalıcı neden: systemd yeniden BAŞLATMAZ (`RestartPreventExitStatus=3`) + OnFailure alarmı
CIKIS_GECICI = 75            # EX_TEMPFAIL: geçici HL/ağ okuma hatası; systemd artan beklemeyle (30 sn → 10 dk) yeniden başlatır
ACILIS_BEKLEME_SN: tuple[float, ...] = (15.0, 45.0, 120.0)     # sn: açılış HL okumasında yeniden denemeler arası bekleme (PublicClient'ın kendi 5/15/45 sn denemelerine EK)
SAAT_SAPMA_SINIR_MS = 2000   # ms: `--kontrol` sunucu saati ile HL sunucu saati (l2Book `time`) farkı sınırı (gidiş-dönüş yarısı düşülerek)
_GECICI_HATALAR: tuple[type[BaseException], ...] = (HlOkunamadi, OSError, RateLimitError)       # OSError: requests ağ/zaman aşımı istisnaları dahil


def kasa_ust(rules: dict, kip: str) -> float:
    """Kasa üst sınırı ($): GERÇEK kip `canli_kasa_ust_usd` (1.000 $, K‑22/K‑26; değişmez); sanal kip `canli_sanal_kasa_ust_usd` (K-66: 10.000 $, yalnız sanal; anahtar yoksa gerçek sınır)."""
    gercek = float(rules["canli_kasa_ust_usd"])
    if kip == "gercek":
        return gercek
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
    ham = str(ortam.get("CANLI_KASA_USD", "")).strip()
    if not ham:
        raise KipHatasi("gercek kip için CANLI_KASA_USD ortam değişkeni ($) gerekli")
    try:
        kasa = float(ham)
    except ValueError as hata:
        raise KipHatasi(f"CANLI_KASA_USD sayı değil: {ham[:20]}") from hata
    ust = float(rules["canli_kasa_ust_usd"])
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

    def __call__(self, olay: dict) -> None:
        ms = self.saat_ms()
        olay = {"zaman_ms": ms, **olay}
        self.sayac[olay.get("olay", "?")] = self.sayac.get(olay.get("olay", "?"), 0) + 1
        try:
            self.dizin.mkdir(parents=True, exist_ok=True)
            with (self.dizin / f"{gun(ms)}.jsonl").open("a", encoding="utf-8") as f:
                f.write(maskele(json.dumps(olay, ensure_ascii=False, separators=(",", ":"), default=str)) + "\n")
        except OSError:
            self.sayac["yazma_hatasi"] = self.sayac.get("yazma_hatasi", 0) + 1


MASKE: list[str] = []          # kayıt/durum/Telegram çıktılarında gizlenecek değerler (gerçek kipte kendi HL hesap adresimiz; K‑37 §10)


def maskele(metin: str) -> str:
    for m in MASKE:
        metin = re.sub(re.escape(m), "[hesap]", metin, flags=re.I)
    return metin


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


class Motor:
    """Olay işleme + periyodik görevler. `post`: HL info (REST); `yurutucu`: emir arka ucu; `kadro_oku()`: kadro.json sözlüğü ya da None; `saat_ms`: enjekte (testte sahte)."""

    def __init__(self, rules: dict, yurutucu: Yurutucu, post: Callable[[dict], Any], telegram: tg.Telegram, durum_dizin: Path, kayit_dizin: Path,
                 kadro_oku: Callable[[], dict | None], saat_ms: Callable[[], int] | None = None, vardiya_id: str = "yerel") -> None:
        self.rules, self.yurutucu, self.post, self.tg = rules, yurutucu, post, telegram
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
        m = _oku(durum_dizin / "motor.json") or {}
        h = _oku(durum_dizin / "hesap.json")
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
        self.saha = Saha(rules, self.kasa, _oku(durum_dizin / "saha.json"))
        self.risk = Risk(rules, self.kasa, _oku(durum_dizin / "risk.json"))
        self.borsa_stop = BorsaStop(_oku(durum_dizin / "borsa_stop.json"))             # K-64: borsada duran felaket stopları (yalnız gerçek kip kullanır)
        if self._donem_eski is not None:
            self.risk.donem_yenile(self.hesap.ozsermaye({}))     # S-3: zirve / gün başı yeni dönem özsermayesine (500 → 300 geçişi zirve düşüşü sayılmaz)
        self._islenen: dict[str, None] = {}                     # işlenen (canlı) dolum kimlikleri, ekleme sırasıyla; G-14: sınır ADRES BAŞINA (`canli_islenen_adres_sakla`), tek yoğun adres diğerlerini düşürmez
        self._islenen_adres: dict[str, deque[str]] = {}
        for k in m.get("islenen", []):
            self._islenen_ekle(str(k))
        self._snap: dict[str, tuple[float, float]] = {}        # G-14/G-17b: yalnız snapshot (canlı değil) görülen kimlik -> (önce, sonra); aynı dolum sonra dolgu/rest ile gelirse poz_tr ikinci kez değişmez, emir bu değerlerle
        self.poz_tr: dict[str, dict[str, float]] = {a: dict(c) for a, c in (m.get("poz_tr") or {}).items()}       # trader işaretli pozisyonları (coin birimi)
        self.hesap_tr: dict[str, dict] = dict(m.get("hesap_tr") or {})                                              # adres -> {deger, ms}
        self.donem_seri: dict = _oku(durum_dizin / "donem_seri.json") or {}     # F-06: dönem boyu UTC gün sonu özsermaye + BTC serisi (pano 15 gün kırpmasından bağımsız, kalıcı)
        self.btc_donem: dict | None = m.get("btc_donem")          # BTC al-tut: {donem, bas_ms, fiyat, kaynak, okundu_ms}; dönem başında BİR kez okunur, motor.json'da kalıcı
        self.son_olay_ms: int = int(m.get("son_olay_ms", 0))
        self._poz_tr_ms: dict[tuple[str, str], int] = {}              # (adres, coin) -> poz_tr'yi son güncelleyen trader dolum zamanı (kuyruktan düşen olayın geç uygulanması yeniyi ezmesin)
        for k, v in (m.get("poz_tr_ms") or {}).items():               # G-14: kalıcı (yeniden başlatmada snapshot'taki eski dolum poz_tr'yi ezmesin)
            a, _, c = str(k).partition("|")
            self._poz_tr_ms[(a, c)] = int(v)
        self._poz_tr_senk_ms: dict[str, int] = {a: int(v) for a, v in (m.get("poz_tr_senk_ms") or {}).items()}   # adres -> son REST pozisyon okumasının anı (ms, UTC); coin kaydı yoksa eşik budur
        if m and "poz_tr_senk_ms" not in m:                           # G-14 geçişi (eski biçim motor.json): poz_tr en az son işlenen dolum kadar taze sayılır
            self._poz_tr_senk_ms = {a: self.son_olay_ms for a in self.poz_tr}
        self.baslama_ms: int = self.saat_ms()
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
        if self._oynat_gecis:
            nl = [x["cloid"] for x in self.niyet.satirlar() if x.get("t") == "niyet"]
            self.hesap.son_niyet_cloid = nl[-1] if nl else None
        for k in self.niyet.kimlikler():                       # emir öncesi yazılmış kimlikler de "işlendi": çökme sonrası çift emir yok (K‑37 §3)
            self._islenen_ekle(k)
        self.kapanis_kuyrugu: dict[str, dict] = {k: dict(v) for k, v in (m.get("kapanis_kuyrugu") or {}).items()}      # "adres|coin" -> {tur, hedef_sz, neden, deneme, ms}
        self.dur_bekliyor: bool = bool(m.get("dur_bekliyor", False))
        self.hl_ofset: float | None = m.get("hl_ofset")          # gerçek kip: HL hesap değeri − yerel özsermaye (ilk okuma); risk temeli = HL değeri − ofset
        self.ledger_son_ms: int | None = m.get("ledger_son_ms")   # gerçek kip: kendi hesabımızın yatırma/çekme kaydında en son işlenen satırın zamanı (ms, UTC)
        if self._donem_eski is not None:                          # S-3: yeni dönemde ofset ilk HL okumasında yeniden kurulur (kasa artırımı için yapılan yatırma ofsete İKİNCİ kez girmez → kalıcı 200 $ mutabakat farkı yok)
            self.hl_ofset, self.ledger_son_ms = None, None
        self.hl_oz: float | None = None
        self.hl_oz_ms: int = 0
        self.son_funding_saat: int | None = m.get("son_funding_saat")
        self._funding_bekleyen: list[tuple[int, int, list]] = []       # F07: oran okunamayan saatlerin pozisyon görüntüleri (saat, kapsanan saat sayısı, [(adres, coin, sz, mark)])
        self.son_funding_ms: int | None = m.get("son_funding_ms")                  # G7 gerçek kip: işlenen en son `userFunding` satırının zamanı (ms, UTC); alan yoksa ilk bakımda "şimdi" (geçmiş okunmaz)
        self.funding_kimlik: list[str] = list(m.get("funding_kimlik") or [])       # G7: son işlenen satırların "time:coin" anahtarları (çift sayım yok)
        self.funding_gercek_usd = float(m.get("funding_gercek_usd", 0.0))          # G7: HL'den işlenen gerçek funding toplamı ($, HL hesabı = kasa ölçeği; + alınan / − ödenen)
        self.ucret_gercek_usd = float(m.get("ucret_gercek_usd", 0.0))              # G7: HL `fee` ile deftere yazılan gerçek ücret toplamı ($)
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
        self._adim_ardisik: dict[str, int] = {}   # M-2: dakikalık adım adı -> üst üste hata sayısı (başarıda silinir)
        self._lock = threading.RLock()            # olay işleme (tüketici iş parçacığı) ile dakikalık bakım aynı durumu değiştirir: tek seferde biri

    # ------------------------------------------------------------------ kilit (vardiya devri: çift emir yok)
    def kilit_al(self) -> None:
        """`durum/kilit.json`: başka bir vardiya `canli_kilit_dk` içinde nabız attıysa BAŞLAMAZ (çift emir yok). Temiz kapanışta bırakılır; çökme/zaman aşımında nabız eskir ve sonraki vardiya devralır."""
        k = _oku(self.durum_dizin / "kilit.json") or {}
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
        _yaz(d / "hesap.json", self.hesap.to_json())
        _yaz(d / "saha.json", self.saha.to_json())
        _yaz(d / "risk.json", self.risk.to_json())
        if self.kip == "gercek":
            _yaz(d / "borsa_stop.json", self.borsa_stop.to_json())
        _yaz(d / "motor.json", self._motor_json())
        if self.donem_seri:
            _yaz(d / "donem_seri.json", self.donem_seri)
        self.niyet.sikistir(int(self.rules["canli_islenen_sakla"]))

    def _motor_json(self) -> dict:
        return {"islenen": self.islenen, "poz_tr": self.poz_tr, "poz_tr_ms": {f"{a}|{c}": ms for (a, c), ms in self._poz_tr_ms.items()}, "poz_tr_senk_ms": self._poz_tr_senk_ms, "hesap_tr": self.hesap_tr, "son_olay_ms": self.son_olay_ms,
                "ozet_gunu": self._ozet_gunu, "ozet_oz": self._ozet_oz, "ozet_emir": self._ozet_emir, "kip": self.kip, "kasa_usd": self.kasa, "kasa_ayar_usd": self.kasa_ayar, "vardiya": self.vardiya_id, "yazildi_ms": self.saat_ms(),
                "kapanis_kuyrugu": self.kapanis_kuyrugu, "dur_bekliyor": self.dur_bekliyor, "hl_ofset": self.hl_ofset, "ledger_son_ms": self.ledger_son_ms, "son_funding_saat": self.son_funding_saat, "tg_offset": self.tg.kalici_offset,
                "son_funding_ms": self.son_funding_ms, "funding_kimlik": self.funding_kimlik[-500:], "funding_gercek_usd": self.funding_gercek_usd, "ucret_gercek_usd": self.ucret_gercek_usd, "ucret_tahmin_say": self.ucret_tahmin_say,
                "btc_donem": self.btc_donem}

    def _dolum_yaz(self) -> None:
        """Her emir sonucundan SONRA (t4b #3): `motor.json` önce, `hesap.json` (son uygulanan niyet işaretçisiyle) SON; ikisi de atomik. Aralarında çökme olursa açılışta işaretçiden sonraki sonuçlu niyetler oynatılır."""
        _yaz(self.durum_dizin / "motor.json", self._motor_json())
        _yaz(self.durum_dizin / "hesap.json", self.hesap.to_json())

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

    def trader_hesap_usd(self, adres: str, simdi_ms: int, zorla: bool = False, taze_sart: bool = False) -> float | None:
        """Trader hesap değeri (oran paydası, K‑35): tüm perp dex `accountValue` toplamı + spot USDC (`hesap_degeri_oku`). Önbellekteki değer kullanılır (yenileme `dakika()` içinde kilit dışında,
        `canli_hesap_okuma_sn`); önbellek yoksa ya da `zorla` ise burada okunur. Okunamazsa önceki değer; hiç yoksa None (açılış atlanır).
        F10 (denetim 10.11): `taze_sart` (açılış/artırma) iken önbellek `canli_hesap_azami_yas_sn`'den eskiyse burada yeniden okunur; okunamazsa None (bayat paydayla büyük emir açılmaz)."""
        c = self.hesap_tr.get(adres)
        bayat = bool(c) and simdi_ms - int(c.get("ms") or 0) > float(self.rules.get("canli_hesap_azami_yas_sn", 1800)) * 1000
        if c and not zorla and not (taze_sart and bayat):
            return float(c["deger"])
        try:
            deger = hesap_degeri_oku(self.post, adres, self._dexler())
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

    def trader_pozlari_oku(self, adres: str, dexler: list[str] | None = None) -> bool:
        try:
            okuma_ms = self.saat_ms()
            self.poz_tr[adres] = clearinghouse_pozisyonlari(self.post, adres, dexler if dexler is not None else self._dexler())
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
            satirlar = self.post({"type": "userFillsByTime", "user": adres, "startTime": bas}) or []
            zamanlar = [int(r["time"]) for r in satirlar if isinstance(r, dict) and r.get("time") is not None]
        except Exception as hata:                          # noqa: BLE001
            self.kayit({"olay": "son_islem_okuma_hata", "adres": adres, "tur": type(hata).__name__})
            return
        self.saha.islem_gordu(adres, max(zamanlar) if zamanlar else bas)

    def _dexler(self) -> list[str]:
        """HIP-3 perp dex adları. Başarılı okuma süreç boyunca önbellekte; HATA önbelleğe ALINMAZ (G-6): istisna yükselir, bir sonraki çağrı yeniden okur.
        Çağıranlar hatayı yakalar (hesap değeri bilinmiyor → açılış `trader_hesap_yok`; pozisyon okunamadı) — eksik dex listesiyle kısmi toplam/pozisyon ASLA üretilmez."""
        if getattr(self, "_dex_adlari", None) is None:
            self._dex_adlari = perp_dex_names(self.post({"type": "perpDexs"}))
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

    def _emir_isle(self, o: Olay, adres: str, eylem: str, once: float, sonra: float, biz_sz: float, simdi: int, gec: bool) -> Sonuc:
        acilis = eylem in ("ac", "artir")
        if acilis and simdi - o.zaman_ms > float(self.rules["canli_olay_stale_sn"]) * 1000:
            self.sayac["gec_acilis"] += 1
            return self._atla(o, adres, eylem, "atlandi", "gec_acilis")
        if acilis:                                                  # K‑42: spot (`@N`, `A/B`) ve HIP‑3 (`dex:COIN`) açılışı/artırması kopyalanmaz; kapanış/azaltma ASLA engellenmez
            sinif = coin_sinifi(o.coin)
            if sinif == "spot":
                self.atlanan_trader["spot_atlandi"][adres] = self.atlanan_trader["spot_atlandi"].get(adres, 0) + 1
                return self._atla(o, adres, eylem, "atlandi", "spot_atlandi")
            if sinif == "hip3" and not bool(self.rules.get("canli_hip3_kopya", False)):
                self.atlanan_trader["hip3_atlandi"][adres] = self.atlanan_trader["hip3_atlandi"].get(adres, 0) + 1
                return self._atla(o, adres, eylem, "atlandi", "hip3_atlandi")
        inen = adres in self.saha.inen and adres not in self.saha.uyeler
        if acilis and inen:
            return self._atla(o, adres, eylem, "engel", "inen_trader")
        if acilis and self.hesap.ters_yonlu_var(adres, o.coin, "B" if sonra > 0 else "A", self.marks, float(self.rules["canli_kapanis_toz_usd"])):          # K‑41: başka trader'dan ters yönlü kopya pozisyonu var → net küçülmesin, açılış yok
            return self._atla(o, adres, eylem, "atlandi", "ters_netlesme")
        yeni_coin = eylem == "ac" and abs(biz_sz) < EPS            # bizim için taze pozisyon (patlama freni sayacı)
        if acilis:
            izin, neden = self.risk.acilis_izni(adres, o.coin, yeni_coin, simdi)
            if not izin:
                return self._atla(o, adres, eylem, "engel", neden)
        slot = self.hesap.slot_bas.get(adres, self.saha.slot)
        mk = self.mark(o.coin, o.px)
        biz_usd = abs(biz_sz) * (mk or o.px)
        hesap_usd = self.trader_hesap_usd(adres, simdi, taze_sart=eylem in ("ac", "artir")) if eylem in ("ac", "artir", "azalt") else 0.0
        if eylem in ("ac", "artir") and not hesap_usd:
            return self._atla(o, adres, eylem, "atlandi", "trader_hesap_yok")
        trader_once, trader_sonra = (0.0, sonra) if eylem == "ac" else ((once, 0.0) if eylem == "kapat" else (once, sonra))
        slot_toplam = sum(abs(p.sz) * (self.mark(c, p.giris) or p.giris) for c, p in self.hesap.poz.get(adres, {}).items())       # trader'ın TÜM coinlerdeki kopya nosyoneli (K‑35)
        emir_usd, neden = boyut.hedef_emir(eylem, trader_once, trader_sonra, hesap_usd or 0.0, biz_usd, slot, o.px, self.rules, slot_toplam)
        hedef = (min(float(slot) * abs(trader_sonra) * o.px / hesap_usd, float(self.rules["radar_slot_tavan_carpan"]) * float(slot)) if hesap_usd and o.px > 0 else None)
        self._boyut_girdi = {"trader_poz_once": trader_once, "trader_poz_sonra": trader_sonra, "trader_hesap_usd": hesap_usd or None, "slot_usd": slot,        # elle denetim (VERI_SOZLESMESI): boyut girdileri
                             "biz_poz_usd": biz_usd, "biz_slot_toplam_usd": slot_toplam, "hedef_usd": hedef}
        if emir_usd <= 0:
            return self._atla(o, adres, eylem, "atlandi", neden)
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

    def _say_neden(self, neden: str) -> None:
        if neden and neden not in ("tamam", "tam_kapanis"):
            self.neden_say[neden] = self.neden_say.get(neden, 0) + 1

    def _atla(self, o: Olay, adres: str, eylem: str, karar: str, neden: str) -> Sonuc:
        self._boyut_girdi = None
        self.sayac[karar] += 1
        self._say_neden(neden)
        if self.kip == "sanal":
            self._atla_tampon[neden] = self._atla_tampon.get(neden, 0) + 1
            self._atla_islem.add((adres, o.coin, int(o.zaman_ms) // 1000))
            ad = self._atla_adres.setdefault(neden, {})
            ad[adres] = ad.get(adres, 0) + 1
        self.kayit({"olay": "emir_yok", "adres": adres, "coin": o.coin, "eylem": eylem, "karar": karar, "neden": neden, "trader_dolum_ms": o.zaman_ms, "gorme_ms": o.alma_ms,
                    "yas_ms": self.saat_ms() - o.zaman_ms})
        return Sonuc(adres, o.coin, eylem, karar, neden)

    def _yurut(self, o: Olay, adres: str, eylem: str, yon: str, usd: float, reduce_only: bool, acik_sz: float | None, neden: str, gec: bool, simdi: int,
               bant: float | None = None, kimlik: str | None = None) -> Sonuc:
        self._say_neden(neden)
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
        pnl = None                                          # pano §C3: bu dolumun gerçekleşen K/Z'si (ücret hariç; yalnız azaltma/kapanışta anlamlı)
        if d.dolu_mu:
            try:
                pnl = self.hesap.uygula(adres, o.coin, yon, d.sz, d.px, d.ucret, dolum_ms)
            except ValueError as hata:                      # defter reddi: kayda geçer, motor çökmez
                self.kayit({"olay": "defter_hata", "adres": adres, "coin": o.coin, "hata": str(hata)[:120]})
            if self.kip == "gercek":                        # G7: gerçek fee mi tahmin mi (sanal kip değişmez)
                if getattr(d, "ucret_gercek", False):
                    self.ucret_gercek_usd += d.ucret
                else:
                    self.ucret_tahmin_say += 1
                    self.kayit({"olay": "ucret_tahmin", "adres": adres, "coin": o.coin, "cloid": cloid, "ucret": d.ucret})
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
                    "gec_goruldu": gec, "kaynak": o.kaynak, "bant": bant, "cloid": cloid, "funding_usd": round(self.hesap.funding.get(adres, 0.0), 6),
                    **({"defter": d.defter} if self.kip == "gercek" and getattr(d, "defter", None) else {}),       # S-12: emir anı defteri (yalnız gerçek kip; gercek_sanal_karsilastir)
                    **({"ham": maskele(json.dumps(d.ham, ensure_ascii=False, default=str))[:300]} if d.durum in ("red", "belirsiz") and d.ham else {}),       # G-19: red → HL ham yanıtı (300 karakter)
                    **{k: (round(v, 8) if isinstance(v, float) else v) for k, v in (self._boyut_girdi or {}).items()}})
        self._boyut_girdi = None
        self._ozet_emir += 1
        e = {"adres": adres, "coin": o.coin, "yon": yon, "usd": d.usd_dolan or usd, "px": d.px, "kayma": kayma_trader, "durum": d.durum, "eylem": eylem, "neden": d.neden}
        if belirsiz:                                        # alarm yukarıda gitti; sonuç `belirsiz_coz`da bildirilir
            pass
        elif self.kip == "gercek":                          # gerçek parada emir hemen bildirilir; G-18: `canli_telegram_gercek_tampon_sn` içindeki emirler TEK mesajda; dolu olmayan 🚨 (sesli)
            self.tg.tampona(e, lambda liste: tg.msg_emir_ozeti(self.kip, liste, 0))
        else:
            self._emir_tampon.append(e)
        return Sonuc(adres, o.coin, eylem, "emir" if d.dolu_mu else ("belirsiz" if belirsiz else "red"), d.neden or neden, d)

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
            hl = clearinghouse_pozisyonlari(self.post, os.environ.get("HL_HESAP_ADRESI", ""), self._dexler())
        except Exception as hata:                          # noqa: BLE001
            self.kayit({"olay": "kapanis_borsa_okuma_hata", "tur": type(hata).__name__})
            return yerel, False
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
            self.sayac["kapanis_eksik"] += 1
            self.kayit({"olay": "kapanis_eksik", "adres": adres, "coin": coin, "neden": neden})
            self.tg.gonder(tg.alarm("ALARM: pozisyon kapanmadı", f"kapanış EKSİK: {coin} (trader {tg.kisa(adres)}) {len(self.rules['canli_kapanis_bantlari'])} denemede kapanmadı ({neden}).\nArtan aralıklarla (1 → 30 dk) yeniden denenecek, yeni pozisyon açılmıyor."))

    def _azalt_kuyruga(self, adres: str, coin: str, hedef_sz: float, neden: str, simdi: int, mk: float) -> None:
        kalan = self.hesap.sz(adres, coin) - hedef_sz
        if abs(kalan) * mk > float(self.rules["canli_kapanis_toz_usd"]) and kalan * self.hesap.sz(adres, coin) > 0:
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
                if s.neden == "min_nosyonel":                    # kalan küçük kısmi azaltma: HL reddeder; bırak
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
            hl = clearinghouse_pozisyonlari(self.post, os.environ.get("HL_HESAP_ADRESI", ""), self._dexler())
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

    def _borsa_yetim_kapat(self, neden: str, simdi: int) -> dict[str, float] | None:
        """G-2: DUR / `/kapat` için borsadaki defter dışı payı reduce-only IOC ile kapatır (bant merdiveni; her turdan sonra borsa yeniden okunur). Yerel deftere dokunmaz
        (defterde olmayan pozisyon). Döner: kalan fazla ({} = borsa düz) ya da None (borsa okunamadı)."""
        bantlar = [float(x) for x in self.rules["canli_kapanis_bantlari"]]
        fazla: dict[str, float] | None = None
        belirsiz: set[str] = set()                         # Y-2: yanıtı belirsiz kalan coine bu çağrıda ikinci emir yok (sonraki dakika borsa yeniden okunur)
        for i in range(len(bantlar) + 1):
            fazla = self._borsa_fazla(simdi)
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
            self.tg.gonder(tg.alarm("Motor durdu", "Tüm pozisyonlar kapandı (borsada teyitli 0).\nYeniden açmak için `durum/DUR` dosyası elle silinmeli.", "🛑"))
            self.durum_yaz()

    # ------------------------------------------------------------------ saha kararlarının uygulanması
    def karar_uygula(self, kararlar: list[Karar], simdi: int) -> None:
        for k in kararlar:
            if k.tur == "giris":
                self._kor_imza.pop(k.adres, None)
                self.hesap.slot_ac(k.adres, self.saha.slot)
                self.trader_pozlari_oku(k.adres)
                self.trader_son_islem_oku(k.adres, simdi)
                self.trader_hesap_usd(k.adres, simdi, zorla=True)
                giris_hesap = (self.hesap_tr.get(k.adres) or {}).get("deger")
                if giris_hesap is not None and k.adres in self.saha.uyeler:        # pano §C1: trader hesap değeri GİRİŞTE bir kez saklanır (canlı kopya koruması = bizim slot getirimiz ↔ trader'ın hesap getirisi)
                    self.saha.uyeler[k.adres]["hesap_giris_usd"] = float(giris_hesap)
                self.kayit({"olay": "saha_giris", "adres": k.adres, "neden": k.neden, "yerine": k.yerine, "slot_usd": self.saha.slot})
                self.tg.gonder(tg.msg_saha("giriş", k.adres, k.neden + (f" (yerine {tg.kisa(k.yerine)})" if k.yerine else "")))
            elif k.tur == "dus":
                self.kayit({"olay": "saha_dus", "adres": k.adres, "neden": k.neden, "sonuc": k.sonuc})
                self.tg.gonder(tg.msg_saha("çıkış", k.adres, f"{k.neden}{' (sonuçla, 14 gün bekleme)' if k.sonuc else ' (sonuç dışı)'}"))
            elif k.tur == "inen_kapat":
                self._adres_kapat(k.adres, "inen_24sa", simdi)
                self.hesap.slot_kapat(k.adres)
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
            return True
        except OSError as hata:
            self.kayit({"olay": "dur_yazim_hata", "neden": neden, "tur": type(hata).__name__})
            self.tg.gonder(tg.alarm("DUR dosyası YAZILAMADI", f"`durum/DUR` yazılamadı ({type(hata).__name__}). Risk kaydı `dur` açık; sunucuyu kontrol et.", "🚨"))
            return False

    def _borsa_acik_mi(self) -> bool | None:
        """Y-1: kendi HL hesabımızda (tüm perp dex) açık pozisyon var mı. Okunamazsa None (çağıran güvenli tarafı seçer: kapanış modu)."""
        try:
            hl = clearinghouse_pozisyonlari(self.post, os.environ.get("HL_HESAP_ADRESI", ""), self._dexler())
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
        self.tg.gonder(tg.alarm(f"DUR yarım kalmıştı: {neden}", f"Motor yeniden başladı; {sayi} açık pozisyon kapanış kuyruğuna alındı{ek}.\nYeni pozisyon açılmıyor; hepsi kapanınca motor durur.", "🛑"))

    def dur_tetikle(self, neden: str) -> None:
        """Tüm pozisyonları reduce‑only kapat (teyitli), `DUR` yaz, alarm. Motor ancak TÜM pozisyonlar teyitli 0 olunca durur; düzleşmeyen varsa `kapanis_kuyrugu` dakikalık yeniden dener
        ve yeni açılış yapılmaz (`risk.dur`). Elle silinmeden yeniden açılmaz."""
        simdi = self.saat_ms()
        self.risk.dur_ver(neden)
        self.dur_bekliyor = True
        self._dur_yaz_atomik(neden, simdi, True)                                                # DUR dosyası kapanışlardan ÖNCE (kapanış istisnası DUR'u etkilemesin)
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
            self.tg.gonder(tg.alarm(f"DUR: {neden}", f"{kapatilan} pozisyon kapatıldı, motor durdu.\nYeniden açmak için `durum/DUR` dosyası elle silinmeli.", "🛑"))
            self._dur_bitir_mi()
        else:
            ek = "" if fazla == {} else (f"; borsada defter dışı açık: {', '.join(f'{c} {v:g}' for c, v in list(fazla.items())[:5])}" if fazla else "; borsa okunamadı (düz teyidi yok)")
            self.tg.gonder(tg.alarm(f"DUR: {neden}", f"{kapatilan} pozisyon kapandı, {kalan} pozisyon DÜZLEŞMEDİ{ek}.\nYeniden denenecek; hepsi kapanınca motor durur.", "🛑"))
        self.durum_yaz()

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
                    if x > 0:
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

    def maks_kaldirac_oku(self) -> int:
        """S-7 (sanal tasfiye): HL `meta` evreni (ana dex + HIP‑3 dex'leri) → coin başına `maxLeverage` → `hesap.maks_kaldirac` (açılışta bir kez; ağ, kilitsiz).
        HIP‑3 adları `dex:COIN` biçimindedir (önek yoksa eklenir). Okunamazsa eski değerler kalır, bilinmeyen coin için `tasfiye_fiyati` 20x varsayar (kayıt: `maks_kaldirac_okunamadi`). Döner: okunan coin sayısı."""
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
        self.hesap.maks_kaldirac.update(okunan)
        if hata_dex or not okunan:
            self.kayit({"olay": "maks_kaldirac_okunamadi", "hata": hata_dex, "okunan": len(okunan), "yedek_kaldirac": 20})
        return len(okunan)

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
        if self.kip == "gercek" and self.hl_oz is not None and self.hl_ofset is not None and self.saat_ms() - self.hl_oz_ms <= 3 * float(self.rules["canli_mutabakat_sn"]) * 1000:
            return self.hl_oz - self.hl_ofset
        return yerel

    def hl_oku(self) -> tuple[dict[str, float], float] | None:
        """Gerçek kip (ağ; kilitsiz): HL pozisyonları (tüm dex) + hesap değeri (tüm perp dex + spot USDC)."""
        adres = os.environ.get("HL_HESAP_ADRESI", "")
        try:
            dexler = self._dexler()
            return clearinghouse_pozisyonlari(self.post, adres, dexler), hesap_degeri_oku(self.post, adres, dexler)
        except Exception as hata:                          # noqa: BLE001
            self.kayit({"olay": "hl_okuma_hata", "tur": type(hata).__name__})
            return None

    def hl_uygula(self, deger: float, simdi: int) -> None:
        self.hl_oz, self.hl_oz_ms = float(deger), simdi
        if self.hl_ofset is None:
            self.hl_ofset = float(deger) - self.yerel_ozsermaye()

    def ledger_oku(self, simdi: int) -> list[dict] | None:
        """Gerçek kip (ağ; kilitsiz): kendi hesabımızın `userNonFundingLedgerUpdates` satırları (sayfalı), `ledger_son_ms`ten sonrası. İlk çağrıda yalnız başlangıç anı sabitlenir (ilk ofset zaten ilk HL okumasından)."""
        if self.ledger_son_ms is None:
            self.ledger_son_ms = simdi
            return None
        try:
            return ledger_sayfala(self.post, os.environ.get("HL_HESAP_ADRESI", ""), self.ledger_son_ms + 1)
        except Exception as hata:                          # noqa: BLE001
            self.kayit({"olay": "ledger_okuma_hata", "tur": type(hata).__name__})
            return None

    def ofset_yenile(self, satirlar: list[dict] | None, simdi: int) -> bool:
        """#5: yeni yatırma/çekme (`deposit`/`withdraw`) satırı görülünce `hl_ofset += net` (net = yatırma − çekme, HL hesabı $). HL − yerel FARKI KORUNUR (birikmiş gerçek funding/kayma/ücret farkı silinmez;
        günlük/zirve freni ve mutabakat bayrağı çalışmaya devam eder). Yalnız HL değeri okunmadan ÖNCE gerçekleşmiş satırlar (`zaman ≤ hl_oz_ms`) işlenir; sonrakiler bir sonraki okumaya kalır.
        `internalTransfer`/`send`/`subAccountTransfer` vb. SAYILMAZ (kasa dışına/içine dış para değil; sayılırsa ofset yanlış kayar), yalnız `ofset_atlanan_tur` olarak kaydedilir (bilgi).
        HL hesabında kasa ayarı kadar para tutulursa ofset 0 olur."""
        if self.kip != "gercek" or not satirlar or self.hl_oz is None or self.ledger_son_ms is None or self.hl_ofset is None:
            return False
        yeni, atlanan = [], {}
        for s in satirlar:
            z, tur = s.get("time"), (s.get("delta") or {}).get("type")
            if not isinstance(z, (int, float)) or not self.ledger_son_ms < z <= self.hl_oz_ms:
                continue
            if tur in ("deposit", "withdraw"):
                yeni.append(s)
            else:
                atlanan[str(tur)] = atlanan.get(str(tur), 0) + 1
        if atlanan:
            self.kayit({"olay": "ofset_atlanan_tur", "turler": atlanan})
        if not yeni:
            self.ledger_son_ms = int(max([self.ledger_son_ms] + [s["time"] for s in satirlar if isinstance(s.get("time"), (int, float)) and s["time"] <= self.hl_oz_ms]))
            return False
        net = sum(float(s["delta"].get("usdc") or 0.0) * (1 if s["delta"]["type"] == "deposit" else -1) for s in yeni)
        eski = self.hl_ofset
        self.hl_ofset = eski + net
        self.ledger_son_ms = int(max(s["time"] for s in satirlar if isinstance(s.get("time"), (int, float)) and s["time"] <= self.hl_oz_ms))
        self.kayit({"olay": "ofset_yenilendi", "eski": eski, "yeni": self.hl_ofset, "net_usd": net, "satir": len(yeni)})
        return True

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
        oranlar = self.funding_oku() if self.funding_bekliyor(simdi) else None
        stop_acik = self.acik_emir_oku() if self.kip == "gercek" and self._aralik_mi("borsa_stop", simdi, float(self.rules["canli_borsa_stop_sn"])) else False     # K-64
        hacimler = self.hacim_oku() if self._aralik_mi("hacim", simdi, 3600 if self._coin_hacim else 300) else None     # K-62: saatte bir (veri yoksa 5 dk'da bir dene)
        fgercek = self.funding_gercek_oku(simdi)                                # G7: gerçek kip, saatte bir; sanalda None
        ledger = self.ledger_oku(simdi) if hl else None                          # gerçek kip: yatırma/çekme kaydı (#5)
        ajan = self.ajan_suresi_oku(simdi)                                       # G-19: gerçek kip, günde bir: API cüzdanı `validUntil`
        btc = self.btc_donem_oku(simdi)                                          # BTC al-tut kıyası: dönem başı BTC fiyatı (yalnız eksikse; salt okur info)
        with self._lock:
            self.mids_uygula(mids, simdi)
            if hacimler:
                self._coin_hacim = hacimler
            if self.son_funding_saat is None:
                self.son_funding_saat = simdi // 3_600_000
            adimlar: list[tuple[str, Callable[[], None]]] = [
                ("belirsiz", lambda: self.belirsiz_coz(simdi)),                    # G-1: sonucu belirsiz emirler risk/mutabakattan ÖNCE deftere
                ("tasfiye", lambda: self._tasfiye(simdi)), ("funding", lambda: self.funding_uygula(oranlar, simdi)), ("funding_gercek", lambda: self.funding_gercek_uygula(fgercek, simdi)),
                ("hl_ozsermaye", lambda: self.hl_uygula(hl[1], simdi) if hl else None), ("ofset", lambda: self.ofset_yenile(ledger, simdi)),
                ("hl_sicrama", lambda: self._hl_sicrama_denetle(simdi) if hl else None), ("risk", lambda: self._risk(simdi)), ("felaket_stop", lambda: self._felaket_stop(simdi)),
                ("borsa_stop", lambda: self.borsa_stop_esitle(stop_acik, simdi) if stop_acik is not False else None), ("anlik_saha", lambda: self._anlik(simdi)),
                ("inen", lambda: self.karar_uygula(self.saha.inenleri_kapat(simdi), simdi)), ("mutabakat", lambda: self._mutabakat(simdi, hl)), ("kapanis_kuyrugu", lambda: self._kuyruk_isle(simdi)),
                ("kadro", lambda: self._kadro_uygula(kadro, simdi)), ("senkron", lambda: (self.senkron_uygula(senkron), self.hesap_uygula(hesaplar, simdi)) if senkron is not None else None),
                ("telegram", lambda: self._komutlar(komutlar)), ("ajan_suresi", lambda: self.ajan_suresi_uygula(ajan, simdi)), ("ozet", lambda: self._gunluk_ozet(simdi)),
                ("emir_ozeti", lambda: self.emir_ozeti(simdi)), ("btc_donem", lambda: self.btc_donem_uygula(btc)), ("donem_seri", lambda: self.donem_seri_guncelle(simdi)),
                ("tur_kaydi", lambda: self._tur_kaydi(simdi)),
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
                        self.tg.gonder(tg.alarm("ALARM: durum diske yazılamıyor", f"Dakikalık durum kaydı başarısız ({type(hata).__name__}).\nYeniden başlatmada son durum kaybolabilir; disk/izinleri kontrol edin."))
                    elif ad != "durum_yaz" and (n == ADIM_ALARM_ARDISIK or (n > ADIM_ALARM_ARDISIK and n % 60 == 0)):      # M-2: aynı adım üst üste 3 kez → alarm (sonra saatte bir)
                        self.tg.gonder(tg.alarm(f"ALARM: '{ad}' adımı hata veriyor", f"Dakikalık '{ad}' adımı üst üste {n} kez başarısız ({type(hata).__name__}: {str(hata)[:100]}).\n"
                                                "Bu adımın koruması (risk/mutabakat/kapanış) çalışmıyor olabilir; kayıtları kontrol edin."))

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

    def donem_seri_guncelle(self, simdi: int) -> None:
        """F-06 (14.11 denetim): `durum/donem_seri.json` = {donem, bas_ms, kasa_usd, btc_donem_fiyat, gunler: [{gun (UTC), ozsermaye_usd, btc}]}. Her dakika o UTC gününün kaydı
        güncellenir: gün bitince son değer = gün sonu. Dönem değişince seri sıfırdan başlar. Dönem yoksa yazılmaz."""
        if not self.donem:
            return
        if self.donem_seri.get("donem") != self.donem:
            self.donem_seri = {"donem": self.donem, "bas_ms": None, "kasa_usd": self.kasa, "btc_donem_fiyat": None, "gunler": []}
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
        if zorla:
            self.tg.tampon_bosalt()                      # G-18: gerçek kip emir tamponu vardiya sonunda beklemeden gider
        dk = float(self.rules.get("canli_telegram_sanal_ozet_dk", 0) or 0)
        if self.kip == "sanal" and dk > 0:
            return self._saatlik_ozet(simdi, dk, zorla)
        sn = float(self.rules["canli_telegram_emir_ozet_sn"])
        if not self._emir_tampon or not (zorla or self._aralik_mi("emir_ozeti", simdi, sn)):
            return
        emirler, self._emir_tampon = self._emir_tampon, []
        self.tg.gonder(tg.msg_emir_ozeti(self.kip, emirler, sn / 60.0))

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
        metin = tg.msg_sanal_saatlik(bas, simdi, round((simdi - bas) / DAKIKA) if zorla else dk, emirler, atlanan,
                                     (self.ozsermaye(), self.risk.gun_basi, self.kasa) if emirler else None, islem, adresler)
        if not metin and not zorla and self.rules.get("canli_telegram_sanal_bos_mesaj", False):
            metin = tg.msg_sanal_saatlik_bos(bas, simdi, dk, atlanan, (self.ozsermaye(), self.risk.gun_basi, self.kasa), islem, adresler)
        if metin:
            self.tg.gonder(metin)

    def _tasfiye(self, simdi: int) -> None:
        if self.kip != "sanal":
            return                                         # gerçek kipte tasfiyeyi HL yapar; mutabakat farkı yakalar
        for e in self.hesap.tasfiye_kontrol(self.marks, simdi):
            self.kayit({"olay": "tasfiye", **e})
            self.tg.gonder(tg.alarm("TASFİYE (sanal)", f"{e['coin']} pozisyonu (trader {tg.kisa(e['adres'])}) {e['tasfiye_px']:.6g} fiyatında tasfiye oldu (piyasa {e['mark']:.6g}).", "💥"))

    _zirve_yenile = False
    bekci_nabiz: Callable[[], None] | None = None          # `calis` bekçinin `nabiz`ını bağlar (kapanış döngüsü her denemede besler)
    _hl_sicrama = False                                     # S-6: son HL okumasında açıklanmayan özsermaye sıçraması var mı
    _hl_sicrama_ms = 0
    _hl_onceki: tuple[float, float] | None = None           # S-6: önceki HL okumasında (HL − ofset, yerel özsermaye) $
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
        if self.kip != "gercek" or self.hl_oz is None or self.hl_ofset is None:
            return
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
        self.tg.gonder(tg.alarm("ALARM: HL özsermayesinde açıklanamayan sıçrama", f"İki okuma arasında {tg.tr_sayi(aciklanmayan)} $ (sınır {tg.tr_sayi(esik)} $); dolum/yatırma/çekme açıklamıyor.\n"
                                "Transfer (send/alt hesap) ya da HL tasfiyesi olabilir. Yeni pozisyon açılmıyor; risk freni bir okuma ertelendi. HL ekranını kontrol edin."))

    def _risk(self, simdi: int) -> None:
        oz = self.ozsermaye()
        if self._zirve_yenile:                                                                  # S-2: DUR sonrası ilk risk adımı (gerçek kipte HL − ofset temeli artık okunmuş olabilir)
            self._zirve_yenile = False
            if abs(oz - self.risk.zirve) > 1e-9:
                eski = self.risk.zirve_yenile(oz)
                self.kayit({"olay": "zirve_yenilendi", "eski_zirve": eski, "yeni_zirve": oz, "gerekce": "dur_sonrasi_ilk_risk"})
        if self.risk.kasa_siniri_asildi(self.kasa, kasa_ust(self.rules, self.kip)):
            if self._aralik_mi("kasa_alarm", simdi, 3600):
                self.tg.gonder(tg.alarm("ALARM: kasa sınırı aşıldı", f"Kasa {tg.tr_sayi(self.kasa, 0)} $ > sınır {tg.tr_sayi(kasa_ust(self.rules, self.kip), 0)} $.\nYeni pozisyon açılmıyor."))
        if self._hl_sicrama and simdi - self._hl_sicrama_ms <= 3 * float(self.rules["canli_mutabakat_sn"]) * 1000:      # S-6: açıklanmayan sıçrama → bu okumada DUR yok (bayrak + alarm verildi)
            self.kayit({"olay": "risk_ertelendi", "neden": "hl_sicrama", "ozsermaye": oz})
            return
        for ev in self.risk.ozsermaye_isle(oz, simdi):
            self.kayit({"olay": "risk", "tur": ev, "ozsermaye": oz})
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
                self.tg.gonder(tg.alarm("ALARM: günlük kayıp sınırı", f"Bugünkü kayıp %{float(self.rules['canli_gunluk_kayip_oran']) * 100:.0f} sınırına ulaştı (özsermaye {tg.tr_sayi(oz)} $).\nBugün yeni pozisyon açılmıyor."))

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
                if aleyhe >= oran - 1e-12:
                    ok, _ = self._kapat_coin(adres, coin, "felaket_stop", simdi)
                    self.kayit({"olay": "felaket_stop", "adres": adres, "coin": coin, "giris": p.giris, "mark": mk, "aleyhe": aleyhe, "kapandi": bool(ok)})
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

    def borsa_stop_esitle(self, acik: list[dict] | None, simdi: int) -> None:
        """K-64: gerçek kipte borsada duran felaket stoplarını net pozisyonlarla eşitler. Kaybolan (tetiklenmiş) stopun coinindeki yerel pozisyonlar borsa teyitli
        kapanış yoluyla temizlenir (`_kapat_coin` → borsa 0 ise G-13 harici kapanış + defter düzeltmesi). Hata → kayıt + saatte bir alarm; motor durmaz."""
        if self.kip != "gercek" or not hasattr(self.yurutucu, "stop_koy"):
            return
        hedef = borsa_stop.hedefler(self.hesap.poz, self.marks, float(self.rules["canli_borsa_stop_oran"]), float(self.rules.get("canli_min_nosyonel_usd", 10)))
        olay = self.borsa_stop.esitle(hedef, acik, self.yurutucu)
        for c in olay["kayip"]:
            adresler = [a for a, cs in self.hesap.poz.items() if c in cs]
            self.kayit({"olay": "borsa_stop_kayip", "coin": c, "yerel_acik": bool(adresler)})
            if not adresler:                                      # pozisyon zaten kapalı: HL reduce-only stopu kendisi düşürmüş olabilir; alarm yok
                continue
            self.tg.gonder(tg.alarm("ALARM: borsa stopu tetiklendi / kayboldu", f"{c} için borsadaki felaket stopu açık emirlerde yok (tetiklenmiş olabilir).\n"
                                    "Pozisyon borsadan teyitle temizleniyor; stop yeniden kurulacak.", "🛑"))
            for adres in adresler:
                self._kapat_coin(adres, c, "borsa_stop", simdi)
        for ad in ("konan", "iptal", "yetim"):
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
        stopsuz = {c for c in hedef if c not in bs_.stoplar}
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

    _son_kadro: dict | None = None
    _kasa_uyari: float | None = None              # D-01: son uyarı verilen kadro kasası (aynı fark için tekrar uyarı yok)
    _coin_hacim: dict[str, float] = {}                    # K-62: coin → 24 sa nosyonel hacim ($); `dakika` saatte bir yeniler (örnek başına atanır)

    def _mutabakat(self, simdi: int, hl: tuple[dict[str, float], float] | None = None) -> None:
        """Gerçek kip: HL ↔ yerel defter. `hl` kilit DIŞINDA okunduysa `_hl_okuma_imza` (`dakika`) o andaki yerel pozisyonlardır; kilit altında defter farklıysa (arada dolum / kapanış) HL kilit altında
        YENİDEN okunur (aksi hâlde eski HL anlık görüntüsü yeni defterle karşılaştırılıp sahte mutabakat alarmı + açılış durması olurdu)."""
        if not self._aralik_mi("mutabakat", simdi, float(self.rules["canli_mutabakat_sn"])):
            return
        imza, self._hl_okuma_imza = self._hl_okuma_imza, None
        if self.kip == "gercek":
            if hl is not None and imza is not None and imza != self._poz_imza():
                self.kayit({"olay": "mutabakat_yeniden_okuma"})
                hl = self.hl_oku()
                if hl is None:
                    return
            hl = hl or self.hl_oku()
            if hl is None:
                return
            hl_poz, hl_deger = hl
            self.hl_uygula(hl_deger, simdi)
            bizim: dict[str, float] = {}
            for coinler in self.hesap.poz.values():
                for c, p in coinler.items():
                    bizim[c] = bizim.get(c, 0.0) + p.sz
            sorunlar = poz_farki(bizim, hl_poz, self.marks, self.kasa, float(self.rules["canli_mutabakat_oran"]))
            fark = abs((hl_deger - (self.hl_ofset or 0.0)) - self.yerel_ozsermaye())          # yerel defter ↔ HL özsermaye farkı (K‑37 §2)
            if fark > self.kasa * float(self.rules["canli_mutabakat_oran"]):
                sorunlar = [*sorunlar, {"neden": "ozsermaye_farki", "fark_usd": fark}]
            if self._hl_sicrama:
                sorunlar = [*sorunlar, {"neden": "hl_sicrama"}]
        else:
            sorunlar = sanal_tutarlilik(self.hesap, self.marks, self.mark_ms, simdi, float(self.rules["canli_mark_stale_sn"]))
        onceki = bool(self.risk.acilis_durdu.get("mutabakat"))
        self.risk.bayrak("mutabakat", bool(sorunlar))
        if sorunlar and not onceki:
            self.kayit({"olay": "mutabakat_alarm", "sorunlar": sorunlar[:10]})
            self.tg.gonder(tg.alarm("ALARM: kayıtlar uyuşmuyor (mutabakat)", f"{len(sorunlar)} sorun bulundu ({sorunlar[0].get('neden')}).\nYeni pozisyon açılmıyor."))
        elif not sorunlar and onceki:
            self.kayit({"olay": "mutabakat_duzeldi"})
            self.tg.gonder(tg.alarm("Mutabakat düzeldi", "Yeni pozisyonlar yeniden serbest.", "✅"))

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
            self._kadro_kasa_denetle(kadro)
        kararlar, durum = self.saha.degerlendir(self._son_kadro, simdi)
        if durum != "ok":
            self.kayit({"olay": "kadro_" + durum})
            if self.saha.alarm_gunu != gun(simdi):
                self.saha.alarm_gunu = gun(simdi)
                self.tg.gonder(tg.alarm(f"ALARM: {durum}", "Takip edilen trader listesi olduğu gibi kalır, yeni trader girmez."))
        self.karar_uygula(kararlar, simdi)

    def _kadro_kasa_denetle(self, kadro: dict) -> None:
        """D-01 (14.11 denetim): kadro.json `kasa_usd` (radar oynatma kasası, `radar_kasa_usd`) motorun kasasından farklıysa seçim başka ölçekte yapılmıştır (ör. 1.000 $'da küçük
        açılışlar atlanır, 10.000 $'da açılır). YALNIZ bilgi: farklı her kasa değeri için bir kez kayıt + uyarı; motor durmaz, kadro yine uygulanır."""
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
                                "Kadro uygulanıyor (durdurma yok); radar_kasa_usd ile motor sanal kasasını eşitleyin.", "⚠️"))

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
                self.tg.gonder(tg.alarm("ALARM: API cüzdanı süresi", f"HL API cüzdanının {durum} ({tarih}).\nSüre dolunca her emir (kapanışlar da) reddedilir. Yeni API cüzdanı oluşturup sunucuya kaydedin, sonra motoru yeniden başlatın."))
        elif okuma.get("durum") == "listede_yok" and not okuma.get("agent_rol"):
            self.tg.gonder(tg.alarm("ALARM: API cüzdanı HL'de yok", "API cüzdanı HL agent listesinde bulunamadı (süresi dolmuş ya da iptal edilmiş olabilir).\nEmirler reddedilir; yeni API cüzdanı gerekli. Acil durumda HL web'den pozisyonları kapatın."))

    def _komutlari_yurut(self, komutlar: list[str]) -> None:
        for k in komutlar:
            if k == "/kapat":                                                  # eski /dur: tüm pozisyonları kapat, motor durur (DUR dosyası)
                self.tg.gonder(tg.msg_kapat_alindi(self.kip))                  # G-16: anında alındı yanıtı (kapanış sonucu ayrı mesajla)
                self.dur_tetikle("komut")
            elif k == "/dur":                                                  # yeni /dur: yalnız yeni giriş/artırma durur; çıkış/azaltma serbest, pozisyonlar trader'ı izlemeye devam eder
                self._duraklat(True)
            elif k in ("/devam", "/baslat"):
                self._duraklat(False)
            elif k == "/durum":
                self.tg.gonder(self.durum_metni())

    def _duraklat(self, ac: bool) -> None:
        """Elle duraklatma (`risk.acilis_durdu['elle_dur']`; kalıcı: `risk.json`). Kapanış/azaltma `acilis_izni`nden geçmediği için DURAKLATMADAN etkilenmez."""
        if not ac and self.risk.dur:
            self.tg.gonder(tg.alarm("Motor kapalı", "Motor `/kapat` ile durduruldu; yeniden açmak sunucudan yapılır. `/devam` bunu açmaz."))
            return
        self.risk.bayrak("elle_dur", ac)
        self.kayit({"olay": "elle_dur" if ac else "elle_devam"})
        self.tg.gonder(tg.alarm("Yeni işlemler duraklatıldı", "Yeni pozisyon açılmaz, artırılmaz. Açık pozisyonlar trader'ı izlemeye ve azaltmaya/kapatmaya devam eder.\nAçmak için /devam.", "⏸️") if ac
                       else tg.alarm("Duraklatma kaldırıldı", self._devam_govde(), "▶️"))
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
        return {"acik": acik, "rest_istek": stats.get("istek"), "rest_429": stats.get("429")}

    def _gunluk_ozet(self, simdi: int) -> None:
        d = datetime.fromtimestamp(simdi / 1000, UTC)
        if d.hour < int(self.rules["canli_ozet_saat_utc"]) or self._ozet_gunu == d.date().isoformat():
            return
        self._ozet_gunu = d.date().isoformat()
        oz = self.ozsermaye()
        self.tg.gonder(tg.msg_gunluk(self.kip, self.kasa, oz, self._ozet_oz if self._ozet_oz is not None else self.kasa, self._ozet_emir, len(self.saha.uyeler), self.saha.n,
                                     self.pano_ek()["acik"], self.hesap.funding_toplam() if self.kip == "sanal" else None))
        self._ozet_oz, self._ozet_emir = oz, 0

    # ------------------------------------------------------------------ özet
    def ozet(self) -> dict[str, Any]:
        ort = lambda x: (sum(x) / len(x)) if x else None            # noqa: E731
        simdi = self.saat_ms()
        oz = self.ozsermaye()
        return {"kip": self.kip, "vardiya": self.vardiya_id, "sure_dk": (simdi - self.baslama_ms) / DAKIKA, "kasa_usd": self.kasa, "ozsermaye_usd": oz, "getiri": oz / self.kasa - 1,
                **self.btc_kiyas(oz / self.kasa - 1),
                "saha": len(self.saha.uyeler), "saha_n": self.saha.n, "inen": len(self.saha.inen), "slot_usd": self.saha.slot, "emir": dict(self.sayac),
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
        if self._donem_eski is not None:
            e = self._donem_eski
            self.kayit({"olay": "donem_yenilendi", "eski_kasa_usd": e["kasa_usd"], "yeni_kasa_usd": self.kasa, "eski_ozsermaye": e["ozsermaye"], "ozsermaye": self.hesap.ozsermaye({}),
                        "kapanmis_net": self.hesap.kapanmis_net, "slot_usd": self.saha.slot, "uye": len(e["slot_bas"])})
        if not self.dur_dosyasi.exists() and self.risk.dur:                                      # DUR dosyası tek yetkili: dosya yoksa risk.json'daki bayat dur sıfırlanır
            self.kayit({"olay": "dur_sifirlandi", "neden": self.risk.dur_neden, "gerekce": "DUR dosyası yok"})
            self.risk.dur, self.risk.dur_neden = False, None
            eski = self.risk.zirve_yenile(self.yerel_ozsermaye())                               # S-2: operatör DUR'u silip yeniden başlattı → zirve GÜNCEL özsermayeye (yoksa 60 sn'de yeniden DUR)
            self._zirve_yenile = True                                                            # gerçek kipte ilk risk adımında HL temelli özsermayeyle bir kez daha kurulur
            self.kayit({"olay": "zirve_yenilendi", "eski_zirve": eski, "yeni_zirve": self.risk.zirve, "gerekce": "dur_sonrasi_yeniden_baslatma"})
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
        self.niyetleri_coz(simdi)
        if dur_yarim is not None:
            self._dur_kapanis_kuyrukla(dur_yarim["neden"], dur_yarim["borsa_acik"], simdi)
        self.piyasa_oku(simdi)
        if self.kip == "sanal":
            self.maks_kaldirac_oku()                                                             # S-7: sanal tasfiye coin başına azami kaldıraçla (gerçek kipte tasfiyeyi HL yapar)
        self._son["kadro"] = 0
        for adres in list(self.saha.uyeler):                                                     # B15 geçişi: düzeltmeden önce girmiş, o günden beri dolum görülmemiş üyenin son dolumu bir kez okunur
            if self.saha.uyeler[adres].get("son_islem_ms") is None:
                self.trader_son_islem_oku(adres, simdi)
        self._kadro(simdi)
        for adres in [*self.saha.uyeler, *self.saha.inen]:
            if adres not in self.poz_tr:
                self.trader_pozlari_oku(adres)
        self.durum_yaz()

    def niyetleri_coz(self, simdi: int) -> int:
        """Çökmeden kalan sonucu yazılmamış niyetler (K‑37 §3) ve yeniden oynatma (t4b #2/#3). Gerçek kip: `orderStatus(cloid)`; emir varsa dolan miktar (`origSz − sz`) DURUMDAN BAĞIMSIZ kullanılır
        (`filled`, `canceled` …): > 0 ise sonuç satırına yazılır (limit fiyatla YAKLAŞIK; kesin değer mutabakatta), `sz > 0` kalmışsa ya da iptal edilmişse "kismi" sayılır. Emir yoksa niyet iptal. Sanal kip: `sonucsuz`,
        emir TEKRARLANMAZ. Ardından `hesap.json`daki son uygulanan niyetten sonraki sonuçlu niyetler deftere oynatılır (çift uygulama yok, kayıp yok). Kısmi kalan AZALTMA < `canli_min_nosyonel_usd` ise atlanır
        (HL <10 $ reduce‑only), değilse kapanış kuyruğuna girer; kısmi KAPANIŞ kuyruğa girer. Döner: çözülen niyet sayısı."""
        sayi = 0
        takip: list[tuple[dict, float, float]] = []                  # (niyet, dolan sz, limit px): kısmi kalan için izleme
        for n in self.niyet.sonucsuz():
            if n["cloid"] in self.hesap.belirsiz:              # G-1: belirsiz emir — işaretçi zaten geçti; `belirsiz_coz` deftere doğrudan (bir kez) uygular
                continue
            durum = "sonucsuz"
            ek: dict[str, Any] = {}
            if self.kip == "gercek":
                try:
                    r = self.post({"type": "orderStatus", "user": os.environ.get("HL_HESAP_ADRESI", ""), "oid": n["cloid"]})
                    if (r or {}).get("status") == "order":
                        emir = r["order"]
                        durum = str(emir.get("status", "?"))
                        e = emir.get("order", {})
                        kalan_sz = float(e.get("sz", 0))
                        dolan = float(e.get("origSz", 0)) - kalan_sz
                        px = float(e.get("limitPx", 0))
                        kismi = dolan > 0 and (durum != "filled" or kalan_sz > EPS)
                        if dolan > 0 and n.get("adres") and n.get("coin"):
                            ek = {"sz": dolan, "px": px, "ucret": 0.0, "dolum": "kismi" if kismi else "dolu"}
                        if kismi:
                            self.sayac["kismi"] += 1
                        if n.get("eylem") in ("azalt", "kapat") and (kismi or durum != "filled"):
                            takip.append((n, max(dolan, 0.0), px))
                    else:
                        durum = "emir_yok_iptal"
                        self._takip_ekle(takip, n)
                except Exception as hata:                  # noqa: BLE001
                    durum = f"orderstatus_hata:{type(hata).__name__}"
                    self.risk.bayrak("mutabakat", True)
                    self._takip_ekle(takip, n)
            self.niyet.sonuc_yaz(n["cloid"], f"cozuldu:{durum}", simdi, **ek)
            self.kayit({"olay": "niyet_sonucsuz", "kip": self.kip, "kimlik": n.get("kimlik"), "eylem": n.get("eylem"), "coin": n.get("coin"), "cloid": n["cloid"], "durum": durum,
                        "dolan_sz": ek.get("sz"), "dolum": ek.get("dolum")})
            sayi += 1
        oynatilan = self._oynat(simdi)
        for n, dolan, px in takip:
            self._kismi_takip(n, dolan, px, simdi)
        if sayi or oynatilan:
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
        for cloid, b in list(self.hesap.belirsiz.items()):
            n = niyetler.get(cloid)
            if n is None or not n.get("adres") or not n.get("coin"):          # niyet satırı yok (bozulma): uygulanamaz → borsa ile mutabakat
                self.hesap.belirsiz.pop(cloid, None)
                self.kayit({"olay": "belirsiz_niyet_yok", "cloid": cloid})
                self.risk.bayrak("mutabakat", True)
                continue
            r = sonuclar.get(cloid)
            if r is None:
                if self.kip != "gercek":
                    durum, dolan, px, kalan_sz, ucret = "sonucsuz", 0.0, 0.0, 0.0, 0.0
                else:
                    if simdi - int(b.get("ms", 0)) < bekle_ms:
                        continue
                    try:
                        y = self.post({"type": "orderStatus", "user": os.environ.get("HL_HESAP_ADRESI", ""), "oid": cloid})
                    except Exception as hata:                  # noqa: BLE001 - ağ yok: girdi kalır, sonraki dakika yeniden
                        b["deneme"] = int(b.get("deneme", 0)) + 1
                        self.kayit({"olay": "belirsiz_sorgu_hata", "cloid": cloid, "coin": n["coin"], "deneme": b["deneme"], "tur": type(hata).__name__})
                        if b["deneme"] == 5:
                            self.tg.gonder(tg.alarm("ALARM: belirsiz emir çözülemiyor", f"{n['coin']} {n.get('eylem')} emrinin durumu {b['deneme']} kez sorgulanamadı.\nYeni pozisyon açılmıyor; her dakika yeniden deneniyor."))
                        continue
                    durum, dolan, px, kalan_sz, ucret = "emir_yok", 0.0, 0.0, 0.0, 0.0
                    if (y or {}).get("status") == "order":
                        emir = y["order"]
                        durum = str(emir.get("status", "?"))
                        e = emir.get("order", {})
                        kalan_sz = float(e.get("sz", 0))
                        dolan = max(0.0, float(e.get("origSz", 0)) - kalan_sz)
                        px = float(e.get("limitPx", 0))
                        if dolan > 0:
                            ucret_bul = getattr(self.yurutucu, "_gercek_ucret", None)
                            gercek = ucret_bul(n["coin"], e.get("oid"), cloid, int(n.get("ms", simdi))) if ucret_bul else None
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
        metin = tg.alarm("ALARM: motor dondu, yeniden başlatılıyor", f"Dakikalık bakım {gecen:.0f} sn'dir tamamlanmadı (sınır {self.sinir_sn:.0f} sn).\nSüreç çıkış kodu 1 ile kapanıyor; sunucu yeniden başlatır.")

        def bildir() -> None:
            try:
                self.motor.kayit({"olay": "bekci_tetik", "gecen_sn": round(gecen, 1), "sinir_sn": self.sinir_sn})
            except Exception:                              # noqa: BLE001 - disk dolu olabilir: çıkış yine olur
                pass
            try:
                self.motor.tg.gonder(metin)
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
        motor.tg.gonder(tg.alarm("ALARM: motor görevi durdu", f"'{ad}' görevi beklenmedik biçimde bitti ({type(hata).__name__ if hata else 'beklenmedik'}).\nMotor kapanıyor (çıkış kodu 1); sunucu yeniden başlatır."))
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


async def bekleme_vardiyasi(motor: Motor, sure_sn: float | None, uyku: Callable[[float], Any] = asyncio.sleep) -> dict:
    """K-54: yeni sürüm kadrosu (radar_surum_gerekli) henüz yok ve saha boş → izlenecek adres yoktur. Motor çökmez (09.11 18:01Z olayı: vardiya
    zinciri koptu); vardiya boyunca kadroyu aralıkla yoklar, uygun kadro gelince erken ve temiz biter (sonraki vardiya adreslerle başlar)."""
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
    motor.kacanlari_tamamla()
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


def acilis_hl_denetle(rules: dict, kip: str, post: Callable[[dict], Any], sk: dict, niyet_yolu: Path | None = None) -> tuple[float, float | None]:
    """Açılışın HL'ye bağlı adımları (bir deneme): gerçek kipte API cüzdanı (G6) + etkin kasa + HL değer sınırı (K‑22) + (Y-5, `niyet_yolu` verilirse) yabancı açık emir yok.
    Kalıcı ret `KipHatasi`; HL okunamadı `HlOkunamadi` (G-15)."""
    if kip == "gercek":                                    # G6: emirden önce API cüzdanı doğrulaması (ana anahtar / agent değil → başlamaz)
        dogrulama = api_cuzdan_dogrula(post, os.environ)
        if not dogrulama["tamam"]:
            if dogrulama.get("hl_okunamadi"):
                raise HlOkunamadi(f"API cüzdanı denetlenemedi: {dogrulama['neden']}")
            raise KipHatasi(f"API cüzdanı doğrulanamadı: {dogrulama['neden']}")
    kasa, hl_deger = etkin_kasa(rules, kip, post, **sk)
    if kip == "gercek" and hl_deger is not None and hl_deger > hl_deger_ust(rules) + 1e-9:          # HL tavanı 1.500 $ (kasa yine ≤ 1.000 $: min(ayar, HL))
        raise KipHatasi(f"HL hesap değeri {hl_deger:.0f} $ > sınır {hl_deger_ust(rules):g} $ (K‑22): kârı çekin ya da kullanıcı kararı")
    if kip == "gercek" and niyet_yolu is not None:
        yabanci_emir_denetle(post, os.environ.get("HL_HESAP_ADRESI", ""), niyet_yolu)
    return kasa, hl_deger


def _motor_calistir(args: argparse.Namespace, rules: dict, kip: str, post: Callable[[dict], Any], kadro_oku: Callable[[], dict | None], tgram: tg.Telegram, sk: dict) -> int:
    """Açılış + ana döngü. Çıkış kodları: 0 temiz; 1 beklenmedik (systemd yeniden başlatır); 3 kalıcı (yeniden başlatılmaz); 75 geçici HL/ağ (yeniden başlatılır) — G-15."""
    def bildir(m: str) -> None:
        print(f"açılış: {m}", file=sys.stderr)
    try:
        if kip == "gercek" and (os.environ.get("HL_AG") or "").strip():
            raise KipHatasi("HL_AG ayarlı: motor yalnız ana ağda çalışır (testnet yalnız `copytrade.canli.stop_deneme` içindir); HL_AG satırını ortamdan kaldırın")      # K-64
        kasa, _ = acilis_yeniden_dene(lambda: acilis_hl_denetle(rules, kip, post, sk, Path(args.durum_dizin) / "niyet.jsonl"), bildir=bildir)
        rules = {**rules, "canli_kasa_ayar_usd": kasa_belirle(rules, kip, **sk)[0], "canli_kasa_usd": kasa}
        if sk:
            rules["canli_kasa_kaynagi"] = "arg"                     # G5: Motor sanal kasa uyumunu denetler (bayraksız koşuda anahtar yok, davranış aynı)
        boyut.saha_sayisi(kasa, rules)
    except HlOkunamadi as hata:
        return _baslamadi(tgram, hata, CIKIS_GECICI)
    except (KipHatasi, ValueError) as hata:
        return _baslamadi(tgram, hata, CIKIS_KALICI)
    try:
        yur: Yurutucu = acilis_yeniden_dene(lambda: gercek_yurutucu_olustur(post, rules), bildir=bildir) if kip == "gercek" else SanalYurutucu(post, rules)
    except HlOkunamadi as hata:
        return _baslamadi(tgram, hata, CIKIS_GECICI)
    except AnahtarYok as hata:
        return _baslamadi(tgram, hata, CIKIS_KALICI)
    except (RuntimeError, ValueError) as hata:                     # SDK kurulu değil / anahtar biçimi bozuk: metin anahtar içerebilir, yalnız tür adı
        return _baslamadi(tgram, KipHatasi(f"gerçek yürütücü kurulamadı ({type(hata).__name__})"), CIKIS_KALICI)
    motor = Motor(rules, yur, post, tgram, args.durum_dizin, args.kayit_dizin or (args.durum_dizin / "kayit"), kadro_oku, vardiya_id=args.vardiya)
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
                kilit_fd = motor_kilidi_al(args.durum_dizin)              # G-21: aynı durum dizininde ikinci gerçek süreç → 3
                adres = os.environ.get("HL_HESAP_ADRESI", "").strip()
                if adres:
                    hesap_fd = hesap_kilidi_al(Path(args.durum_dizin).parent, adres)      # Y-5: aynı hesap, başka durum dizini → 3
            except KipHatasi as hata:
                return _baslamadi(tgram, hata, CIKIS_KALICI)
        try:
            return _motor_calistir(args, rules, kip, post, kadro_oku, tgram, sk)
        except Exception as hata:                                       # noqa: BLE001 - beklenmedik: iz günlüğe, kısa alarm (yalnız tür adı), 1 (systemd yeniden başlatır)
            import traceback
            traceback.print_exc()
            try:
                tgram.gonder(tg.alarm("ALARM: motor beklenmedik hatayla durdu", f"Hata türü {type(hata).__name__}. Çıkış kodu 1; systemd yeniden başlatacak.\njournalctl -u sg-canli"))
            except Exception:                                           # noqa: BLE001
                pass
            return 1
    finally:
        for fd in (hesap_fd, kilit_fd):
            if fd is not None:
                os.close(fd)


if __name__ == "__main__":
    sys.exit(main())
