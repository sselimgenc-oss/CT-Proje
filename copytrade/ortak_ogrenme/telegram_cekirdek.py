# Kaynak: sselimgenc-oss/SG-Github-AB-proje trader/paket/ortak_ogrenme/telegram_cekirdek.py @ f6221cb (kopya; değiştirme, güncelleme kaynaktan)
"""Telegram cekirdegi (ortak paket, parca 3; spec: docs/standart/ortak-ogrenme-paketi-parca3-spec.md).

Standart: docs/standart/telegram-standardi.md. Kaynak: trader_core/telegram.py (yalniz genel parcalar).
Yalniz standart kutuphane. trader_core / trader_engine / trader_ml ICE AKTARILMAZ.

Icerik:
- metin: `mask`, `neutralize`, `fit_text`, `etiketle` (proje etiketi [ML] / [1L3A] / [CT])
- istemci: `TelegramClient` (enjekte `http_post(url, json=..., timeout=...) -> (status, body)`; varsayilan urllib)
- kuyruk: `Outbox` (atomik JSON, hiz siniri, tekrar onleme, INFO yaslanmasi)
- giden: `TelegramNotifier.send_text` (etiketli, kuyruklu, yeniden denemeli)
- iki adimli onay: `OnayKapisi` (4 haneli kod, 120 sn, tek kullanim, yalniz sha256 saklanir, denetim JSONL)

Token hicbir cikti, istisna metni ya da kayitta bulunmaz (`mask`). Telegram ticareti asla bloke etmez; bu modul
yalniz bildirim/onay yardimcisidir.
"""
from __future__ import annotations

import hashlib
import hmac
import json as _json
import logging
import os
import re
import secrets
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("ortak_ogrenme.telegram")
UTC = timezone.utc

API = "https://api.telegram.org"
MAX_TEXT = 3500
RETRY_DELAYS = (2, 5, 15)
SEND_BUDGET_S = 30.0
CODE_TTL_S = 120
DEDUP_WINDOW_S = 600
SPOOL_MAX_FILES = 500
SPOOL_MAX_BYTES = 5 * 1024 * 1024
INFO_MAX_AGE_S = 24 * 3600
RATE_PER_MIN = 15
SEVERITIES = ("INFO", "WARN", "CRIT")
PROJELER = ("ML", "1L3A", "CT")
CODE_RE = re.compile(r"^\d{4}$")

_KEY_RE = re.compile(r"sk-ant-[A-Za-z0-9_\-]*")          # trader_core.lesson.scrub ile ayni desen
_TOKEN_RE = re.compile(r"bot\d+:[A-Za-z0-9_\-]+")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _scrub(text: Any) -> str:
    """API anahtari benzeri dizgileri (sk-ant-...) tamamen atar."""
    return _KEY_RE.sub("[redacted]", str(text))


def _fmt_ts(dt: datetime) -> str:
    d = dt.astimezone(UTC)
    return d.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (d.microsecond // 1000)


def _key_hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def atomic_write_json(path, data: dict) -> Path:
    """Gecici dosya + fsync + os.replace; dizin girdisi de diske yazilir (en iyi caba)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(_json.dumps(data, ensure_ascii=False, indent=1, allow_nan=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    try:
        dfd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass
    return path


# ---------------------------------------------------------------------------
# Metin
# ---------------------------------------------------------------------------
def mask(text: Any, token: str | None = None) -> str:
    t = str(text)
    if token:
        t = t.replace(token, "<gizli>")
    t = _TOKEN_RE.sub("bot<gizli>", t)
    return _scrub(t)


def neutralize(text: str) -> str:
    """Komut gibi gorunen '/' satirlarinin basina bosluk ekler; kontrol karakterlerini atar."""
    t = _CTRL_RE.sub(" ", _scrub(text))
    return "\n".join((" " + ln) if ln.startswith("/") else ln for ln in t.split("\n"))


def fit_text(body: str, pinned: str = "", limit: int = MAX_TEXT) -> str:
    """Govde kisalir, `pinned` (komut/kod satirlari) sona sabitlenir ve asla kesilmez."""
    body = neutralize(body)
    tail = ("\n" + pinned) if pinned else ""
    if len(body) + len(tail) <= limit:
        return body + tail
    lines = body.split("\n")
    note_room = 40
    out: list[str] = []
    used = 0
    for ln in lines:
        if used + len(ln) + 1 + len(tail) + note_room > limit:
            break
        out.append(ln)
        used += len(ln) + 1
    dropped = len(lines) - len(out)
    if not out:
        out = [lines[0][: max(0, limit - len(tail) - note_room)]]
        dropped = len(lines) - 1
    return "\n".join(out) + f"\n(kısaltıldı, {dropped} satır)" + tail


def etiketle(proje: str, text: str) -> str:
    """Ilk satira `[PROJE] ` oneki. Zaten etiketliyse tekrar eklenmez. Bilinmeyen proje ValueError."""
    if proje not in PROJELER:
        raise ValueError(f"bilinmeyen proje etiketi: {proje!r}")
    on = f"[{proje}]"
    if str(text).startswith(on):
        return str(text)
    return f"{on} {text}"


# ---------------------------------------------------------------------------
# Istemci
# ---------------------------------------------------------------------------
class TelegramError(Exception):
    def __init__(self, kind: str, status: int = 0, retry_after: float | None = None, desc: str = ""):
        super().__init__(f"{kind} {status} {desc}"[:200])
        self.kind = kind                      # transient | permanent | conflict
        self.status = status
        self.retry_after = retry_after


def _urllib_timeout(timeout: Any) -> float | None:
    """requests tarzi (baglanti, okuma) demeti -> urllib'in tek sayisi (en buyugu; okuma suresi kisalmasin). 1.2.1 duzeltmesi."""
    if isinstance(timeout, (tuple, list)):
        vals = [float(t) for t in timeout if t is not None]
        return max(vals) if vals else None
    return timeout


def default_http_post(url: str, json: Any = None, timeout: Any = None, token: str | None = None):
    """urllib ile JSON POST. -> (status, body_dict). Ag hatasi (0, {}). Istisna metni token icerirse maskelenir.
    `timeout` tek sayi ya da requests tarzi (baglanti, okuma) demeti olabilir (urllib tek sayi ister)."""
    timeout = _urllib_timeout(timeout)
    data = None if json is None else _json.dumps(json).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, (e.read() or b"")
    except Exception as e:  # noqa: BLE001  istisna metni token tasir: maskelenir, zincir basilmaz
        log.warning("http hatasi: %s", mask(type(e).__name__, token))
        return 0, {}
    try:
        body = _json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        body = {}
    return status, body if isinstance(body, dict) else {}


class TelegramClient:
    def __init__(self, token: str, http_post: Callable | None = None, sleep: Callable[[float], None] = time.sleep):
        if not token:
            raise ValueError("token yok")
        self._token = token
        self._post = http_post or (lambda url, json=None, timeout=None: default_http_post(url, json, timeout, token))
        self.sleep = sleep

    def call(self, method: str, payload: dict, timeout=(5, 10)) -> Any:
        try:
            status, body = self._post(f"{API}/bot{self._token}/{method}", json=payload, timeout=timeout)
        except Exception as e:  # noqa: BLE001
            raise TelegramError("transient", 0, desc=mask(type(e).__name__, self._token)) from None
        if status == 200 and body.get("ok") is True:
            return body.get("result")
        params = body.get("parameters") or {}
        desc = mask(body.get("description", ""), self._token)
        if status == 429:
            raise TelegramError("transient", 429, min(60.0, float(params.get("retry_after", 5) or 5)), desc)
        if status == 409:
            raise TelegramError("conflict", 409, desc=desc)
        if status in (400, 401, 403, 404):
            raise TelegramError("permanent", status, desc=desc)
        raise TelegramError("transient", status, desc=desc)

    def send_message(self, chat_id, text: str, *, disable_notification: bool = False, reply_markup=None) -> dict:
        p = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True,
             "disable_notification": bool(disable_notification)}
        if reply_markup is not None:
            p["reply_markup"] = reply_markup
        res = self.call("sendMessage", p)
        if not isinstance(res, dict) or "message_id" not in res:
            raise TelegramError("transient", 200, desc="message_id yok")
        return res

    def get_updates(self, offset: int | None, timeout: int = 30) -> list:
        p: dict = {"timeout": timeout, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            p["offset"] = offset
        res = self.call("getUpdates", p, timeout=(5, timeout + 10))
        return res if isinstance(res, list) else []

    def answer_callback_query(self, callback_query_id: str, text: str = "") -> Any:
        return self.call("answerCallbackQuery", {"callback_query_id": callback_query_id, "text": text[:190]})

    def edit_message_text(self, chat_id, message_id: int, text: str, reply_markup=None) -> Any:
        p = {"chat_id": chat_id, "message_id": message_id, "text": text, "disable_web_page_preview": True}
        p["reply_markup"] = reply_markup if reply_markup is not None else {"inline_keyboard": []}
        return self.call("editMessageText", p)


# ---------------------------------------------------------------------------
# Kuyruk (outbox)
# ---------------------------------------------------------------------------
class Outbox:
    def __init__(self, base: str | Path, now_fn: Callable[[], datetime]):
        self.dir = Path(base) / "outbox"
        self.sent_dir = self.dir / "sent"
        self.now = now_fn
        self.dropped = 0

    def _mk(self) -> None:
        self.sent_dir.mkdir(parents=True, exist_ok=True)

    def sent_recently(self, key: str) -> bool:
        try:
            until = float((self.sent_dir / _key_hash(key)).read_text().strip())
        except (OSError, ValueError):
            return False
        return until > self.now().timestamp()

    def mark_sent(self, key: str, until_epoch: float | None = None) -> None:
        try:
            self._mk()
            until = until_epoch if until_epoch else self.now().timestamp() + DEDUP_WINDOW_S
            (self.sent_dir / _key_hash(key)).write_text(f"{until:.0f}\n")
        except OSError as e:
            log.warning("sent isareti yazilamadi: %s", type(e).__name__)

    def pending_for(self, key: str) -> list[Path]:
        try:
            return sorted(self.dir.glob(f"*-{_key_hash(key)}.json"))
        except OSError:
            return []

    def list(self) -> list[Path]:
        try:
            return sorted(p for p in self.dir.glob("*.json") if p.is_file())
        except OSError:
            return []

    def enqueue(self, item: dict) -> bool:
        """Ayni dedup_key icin ikinci dosya olmaz. Yazilamazsa False (yalniz gunluk)."""
        key = item["dedup_key"]
        if self.pending_for(key):
            return True
        try:
            self._mk()
            ns = int(self.now().timestamp() * 1e9)
            p = self.dir / f"{ns:020d}-{_key_hash(key)}.json"
            atomic_write_json(p, item)
            try:
                os.chmod(p, 0o660)
            except OSError:
                pass
        except Exception as e:  # noqa: BLE001
            log.error("spool yazilamadi: %s", type(e).__name__)
            return False
        self._enforce_limits()
        return True

    def _read(self, p: Path) -> dict | None:
        try:
            d = _json.loads(p.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) and "text" in d and "dedup_key" in d else None
        except (OSError, ValueError):
            return None

    def _enforce_limits(self) -> None:
        files = self.list()
        total = sum(p.stat().st_size for p in files if p.exists())
        if len(files) <= SPOOL_MAX_FILES and total <= SPOOL_MAX_BYTES:
            return
        for sev in ("INFO", "WARN"):
            for p in list(files):
                if len(files) <= SPOOL_MAX_FILES and total <= SPOOL_MAX_BYTES:
                    return
                d = self._read(p)
                if d and d.get("severity") == sev:
                    total -= p.stat().st_size
                    p.unlink(missing_ok=True)
                    files.remove(p)
                    self.dropped += 1

    def drain(self, client: TelegramClient, chat_id: int, sleep: Callable[[float], None] = time.sleep) -> int:
        """Eski->yeni. Basarili dosya silinir. Hata: dur (siradaki tur dener). Gonderilen sayisini dondurur."""
        now = self.now().timestamp()
        items: list[tuple[Path, dict]] = []
        for p in self.list():
            d = self._read(p)
            if d is None:
                continue
            exp = d.get("expires_at")
            if exp is not None and exp <= now:
                p.unlink(missing_ok=True)       # suresi dolmus onay talebi gonderilmez
                continue
            if d.get("severity") == "INFO" and now - float(d.get("created_at", now)) > INFO_MAX_AGE_S:
                p.unlink(missing_ok=True)
                continue
            if self.sent_recently(d["dedup_key"]):
                p.unlink(missing_ok=True)
                continue
            items.append((p, d))
        # hiz siniri: tur basina <= RATE_PER_MIN; asan INFO tek ozet
        budget = RATE_PER_MIN
        if len(items) > budget:
            info = [x for x in items if x[1].get("severity") == "INFO"]
            others = [x for x in items if x[1].get("severity") != "INFO"]
            keep_n = max(0, budget - len(others) - 1)
            merge = info[keep_n:]
            if len(merge) > 1:
                items = sorted(others + info[:keep_n], key=lambda x: x[0].name)
                try:
                    client.send_message(chat_id, f"{len(merge)} mesaj birlestirildi", disable_notification=True)
                    for p, d in merge:
                        p.unlink(missing_ok=True)
                        self.mark_sent(d["dedup_key"])
                except TelegramError:
                    pass
        sent = 0
        for p, d in items[:budget]:
            try:
                client.send_message(chat_id, d["text"], disable_notification=d.get("severity") == "INFO",
                                    reply_markup=d.get("reply_markup"))
            except TelegramError as e:
                if e.kind == "permanent":
                    log.error("CRIT spool gonderimi kalici hata %s", e.status)
                if e.retry_after:
                    sleep(e.retry_after)
                break
            self.mark_sent(d["dedup_key"], d.get("expires_at"))
            p.unlink(missing_ok=True)
            sent += 1
            sleep(1.0)
        return sent


# ---------------------------------------------------------------------------
# Giden: notifier
# ---------------------------------------------------------------------------
class TelegramNotifier:
    def __init__(self, client: TelegramClient, chat_id: int, outbox: Outbox, now_fn: Callable[[], datetime],
                 proje: str, *, sleep: Callable[[float], None] = time.sleep):
        if proje not in PROJELER:
            raise ValueError(f"bilinmeyen proje etiketi: {proje!r}")
        self.client, self.chat_id, self.outbox = client, chat_id, outbox
        self.now = now_fn
        self.proje = proje
        self.sleep = sleep

    def _send_retry(self, text: str, severity: str, reply_markup=None) -> bool:
        waited = 0.0
        delays = list(RETRY_DELAYS)
        while True:
            try:
                self.client.send_message(self.chat_id, text, disable_notification=severity == "INFO",
                                         reply_markup=reply_markup)
                return True
            except TelegramError as e:
                if e.kind in ("permanent", "conflict"):
                    log.error("CRIT telegram kalici gonderim hatasi %s", e.status)
                    return False
                wait = e.retry_after if e.retry_after else (delays.pop(0) if delays else None)
                if wait is None or waited + wait > SEND_BUDGET_S:
                    return False
                self.sleep(wait)
                waited += wait
            except Exception:  # noqa: BLE001
                return False

    def send_text(self, text: str, severity: str, dedup_key: str, *, expires_at: float | None = None,
                  reply_markup=None, pinned: str = "") -> bool:
        """Metni proje etiketiyle gonderir. Gonderilemezse kuyruga yazar (False doner)."""
        if not dedup_key or not isinstance(dedup_key, str):
            raise ValueError("dedup_key zorunlu")
        if severity not in SEVERITIES:
            raise ValueError("gecersiz severity")
        etiketli = etiketle(self.proje, text)
        try:
            return self._deliver(etiketli, severity, dedup_key, expires_at, reply_markup, pinned)
        except Exception as e:  # noqa: BLE001  istisna disariya sizmaz
            log.error("telegram gonderim istisnasi: %s", mask(type(e).__name__))
            return False

    def _deliver(self, text, severity, key, expires_at, reply_markup, pinned) -> bool:
        if self.outbox.sent_recently(key):
            return True                                   # zaten teslim edildi
        body = fit_text(text, pinned)
        if expires_at is not None and expires_at <= self.now().timestamp():
            return False
        if self._send_retry(body, severity, reply_markup):
            self.outbox.mark_sent(key, expires_at)
            for p in self.outbox.pending_for(key):
                p.unlink(missing_ok=True)
            return True
        self.outbox.enqueue({"text": body, "severity": severity, "dedup_key": key, "expires_at": expires_at,
                             "reply_markup": reply_markup, "created_at": self.now().timestamp()})
        return False                                      # spool'a yazmak teslim degildir


# ---------------------------------------------------------------------------
# Iki adimli onay
# ---------------------------------------------------------------------------
class OnayKapisi:
    """Riskli komut icin 4 haneli kod. Kod yalniz mesajla gider; dosyada yalniz sha256(kod) tutulur.

    baslat(komut, ozet) -> kod. dogrula(komut, kod) -> bool: kod, komut eslesirse ve CODE_TTL_S icinde
    dogruysa True; tek kullanimlik. Yanlis kodda bekleyen istek silinir. Baska komut icin dogrulama reddedilir
    (bekleyen istek kalir). Her olay denetim JSONL'ine (zaman, olay, komut, sonuc) yazilir.
    """

    def __init__(self, dosya: str | Path, now_fn: Callable[[], datetime], rng: Any = secrets,
                 denetim: str | Path | None = None):
        self.dosya = Path(dosya)
        self.now = now_fn
        self._rng = rng
        self.denetim = Path(denetim) if denetim else self.dosya.with_name(self.dosya.stem + ".denetim.jsonl")

    def _audit(self, olay: str, komut: str, sonuc: str) -> None:
        row = {"zaman": _fmt_ts(self.now()), "olay": olay, "komut": komut, "sonuc": sonuc}
        try:
            self.denetim.parent.mkdir(parents=True, exist_ok=True)
            with open(self.denetim, "a", encoding="utf-8") as f:
                f.write(_json.dumps(row, ensure_ascii=False) + "\n")
        except OSError as e:
            log.warning("denetim yazilamadi: %s", type(e).__name__)

    def _read(self) -> dict | None:
        try:
            d = _json.loads(self.dosya.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return d if isinstance(d, dict) and {"komut", "kod_sha256", "expires_at"} <= d.keys() else None

    def _clear(self) -> None:
        self.dosya.unlink(missing_ok=True)

    def baslat(self, komut: str, ozet: str) -> str:
        """Bekleyen istegi kurar (varsa yenisiyle degisir) ve 4 haneli kodu dondurur. Kod yalniz burada gorunur."""
        kod = "%04d" % self._rng.randbelow(10000)
        now = self.now().timestamp()
        atomic_write_json(self.dosya, {
            "komut": komut, "ozet": ozet,
            "kod_sha256": hashlib.sha256(kod.encode("utf-8")).hexdigest(),
            "created_at": now, "expires_at": now + CODE_TTL_S,
        })
        self._audit("baslat", komut, "kod_uretildi")
        return kod

    def dogrula(self, komut: str, kod: str) -> bool:
        p = self._read()
        if p is None:
            self._audit("dogrula", komut, "bekleyen_yok")
            return False
        if p["komut"] != komut:
            self._audit("dogrula", komut, "komut_uyusmadi")
            return False
        if self.now().timestamp() > float(p["expires_at"]):
            self._clear()
            self._audit("dogrula", komut, "suresi_doldu")
            return False
        girilen = kod if isinstance(kod, str) and CODE_RE.match(kod) else ""
        beklenen = str(p["kod_sha256"])
        dogru = hmac.compare_digest(hashlib.sha256(girilen.encode("utf-8")).hexdigest(), beklenen) and bool(girilen)
        self._clear()                                     # tek deneme: dogru ya da yanlis, istek tuketilir
        if not dogru:
            self._audit("dogrula", komut, "yanlis_kod")
            return False
        self._audit("dogrula", komut, "onaylandi")
        return True
