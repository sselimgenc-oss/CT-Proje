"""Telegram bildirimi + komutlar (Bot API doğrudan; görev T4 §1). Token/chat YALNIZ ortamdan (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`); yoksa kanal KAPALI (mesajlar yalnız kayda yazılır, motor çökmez).

`post(url, json) -> dict` enjekte edilir (testte sahte). K‑37: komut yalnız `chat.id == chat_id` VE `from.id == chat_id` (özel sohbet) ise kabul edilir; yetkisiz komut kayda alınır; motor başlangıcından ÖNCE tarihli mesajlar yok sayılır (eski /dur yeniden tetiklenmez); `offset` motor.json'da kalıcıdır. Komutlar: `/dur` (motoru durdur: pozisyonları kapat) ve `/durum`. Mesajlar kısa, adres kısaltılır (ilk 8 karakter).
"""
from __future__ import annotations

import os
import re
import time
from typing import Any, Callable

KOMUTLAR = ("/dur", "/durum")


def kisa(adres: str) -> str:
    return adres[:8] + "…" if len(adres) > 8 else adres


def varsayilan_post(url: str, yuk: dict) -> dict:
    import requests
    r = requests.post(url, json=yuk, timeout=25)
    r.raise_for_status()
    return r.json()


class Telegram:
    def __init__(self, token: str | None = None, chat_id: str | None = None, post: Callable[[str, dict], dict] | None = None, ortam: dict | None = None,
                 kayit: Callable[[dict], None] | None = None, arka_plan: bool = False, baslangic_s: float | None = None) -> None:
        ortam = os.environ if ortam is None else ortam
        self.token = (token if token is not None else ortam.get("TELEGRAM_BOT_TOKEN", "")).strip()
        self.chat_id = str(chat_id if chat_id is not None else ortam.get("TELEGRAM_CHAT_ID", "")).strip()
        self.post = post or varsayilan_post
        self.kayit = kayit
        self.offset = 0
        self.baslangic_s = float(time.time() if baslangic_s is None else baslangic_s)       # bundan önce tarihli mesajlar yok sayılır
        self.yetkisiz_sayisi = 0
        self.maske: list[str] = []                     # mesajlarda gizlenecek değerler (ör. kendi HL hesap adresimiz)
        self.hata_sayisi = 0
        self.gonderilen: list[str] = []
        self._havuz = None
        if arka_plan:                                  # motor: gönderim emir hattını (25 sn'ye varan HTTP zaman aşımı) bekletmesin
            from concurrent.futures import ThreadPoolExecutor
            self._havuz = ThreadPoolExecutor(max_workers=1, thread_name_prefix="telegram")

    @property
    def acik(self) -> bool:
        return bool(self.token and self.chat_id)

    def _url(self, yontem: str) -> str:
        return f"https://api.telegram.org/bot{self.token}/{yontem}"

    def gonder(self, metin: str) -> bool:
        """Mesaj gönderir; hata motoru DURDURMAZ (sayılır). Token günlüğe/hata metnine ASLA yazılmaz."""
        for m in self.maske:
            metin = re.sub(re.escape(m), "[hesap]", metin, flags=re.I)
        self.gonderilen.append(metin)
        if self.kayit:
            self.kayit({"olay": "telegram", "metin": metin[:300], "acik": self.acik})
        if not self.acik:
            return False
        if self._havuz is not None:
            self._havuz.submit(self._gonder_sync, metin)
            return True
        return self._gonder_sync(metin)

    def _gonder_sync(self, metin: str) -> bool:
        try:
            self.post(self._url("sendMessage"), {"chat_id": self.chat_id, "text": metin[:4000], "disable_notification": False})
            return True
        except Exception as hata:                      # noqa: BLE001 - ağ/HTTP hatası; ayrıntı (URL'de token var) yazılmaz
            self.hata_sayisi += 1
            if self.kayit:
                self.kayit({"olay": "telegram_hata", "tur": type(hata).__name__})
            return False

    def komutlari_al(self) -> list[str]:
        """Yeni komutları (`/dur`, `/durum`) döner; yalnız `chat_id`'den gelenler; offset ilerler."""
        if not self.acik:
            return []
        try:
            yanit = self.post(self._url("getUpdates"), {"offset": self.offset, "timeout": 0, "allowed_updates": ["message"]})
        except Exception as hata:                      # noqa: BLE001
            self.hata_sayisi += 1
            if self.kayit:
                self.kayit({"olay": "telegram_hata", "tur": type(hata).__name__})
            return []
        komutlar: list[str] = []
        for u in (yanit or {}).get("result", []):
            self.offset = max(self.offset, int(u.get("update_id", 0)) + 1)
            m = u.get("message") or {}
            metin = str(m.get("text", "")).strip().split("@")[0].lower()
            if not metin.startswith("/"):
                continue
            if str((m.get("chat") or {}).get("id", "")) != self.chat_id or str((m.get("from") or {}).get("id", "")) != self.chat_id:
                self.yetkisiz_sayisi += 1
                if self.kayit:
                    self.kayit({"olay": "telegram_yetkisiz", "komut": metin[:20], "chat": str((m.get("chat") or {}).get("id", ""))[:3] + "…"})
                continue
            if float(m.get("date", 0) or 0) < self.baslangic_s:
                if self.kayit:
                    self.kayit({"olay": "telegram_eski_komut", "komut": metin[:20]})
                continue
            if metin in KOMUTLAR:
                komutlar.append(metin)
        return komutlar


# ---------------------------------------------------------------------------------------------- mesaj biçimleri (kısa)
def msg_saha(tur: str, adres: str, neden: str, sira: int | None = None) -> str:
    return f"SAHA {tur}: {kisa(adres)}" + (f" (sıra {sira})" if sira else "") + f" — {neden}"


def msg_emir(adres: str, coin: str, yon: str, usd: float, px: float | None, kayma: float | None, durum: str, kip: str) -> str:
    return (f"EMİR[{kip}] {kisa(adres)} {coin} {'AL' if yon == 'B' else 'SAT'} {usd:.1f}$ @{px:.6g}" if px else f"EMİR[{kip}] {kisa(adres)} {coin} {'AL' if yon == 'B' else 'SAT'} {usd:.1f}$ {durum}") \
        + (f" kayma {kayma * 1e4:+.1f}bp" if kayma is not None else "") + f" [{durum}]"


def msg_gunluk(kip: str, kasa: float, ozsermaye: float, gun_getiri: float, toplam_getiri: float, saha: int, n: int, acik: list[str], funding_usd: float | None = None) -> str:
    return (f"GÜNLÜK ÖZET [{kip}] kasa {kasa:.0f}$ · özsermaye {ozsermaye:.2f}$ · gün {gun_getiri * 100:+.2f}% · toplam {toplam_getiri * 100:+.2f}% · saha {saha}/{n}"
            + (f" · funding {funding_usd:+.4f}$" if funding_usd is not None else "") + "\n"
            + ("açık: " + ", ".join(acik) if acik else "açık pozisyon yok"))
