"""Binance KÂĞIT süreci (K-81, Aşama A; docs/binance-plan.md §7): HL sanal motoruyla AYNI sinyalleri Binance fiyatlarıyla ayrı bir sanal kasada yürüten ikinci süreç.

Mimari: `python -m copytrade.canli.motor --kip sanal --borsa binance_kagit --durum-dizin durum/binance_kagit --sanal-kasa-usd 1000 ...` = AYNI motor kodu, ayrı durum/kayıt dizini, ayrı sanal kasa;
yalnız (1) `post` = `piyasa_post` (fiyat/fonlama Binance, trader/kadro okumaları HL) ve (2) yürütücü = `BinanceKagitYurutucu`. HL sanal motoru (sg-sanal) AYNEN sürer; bu süreç ayrı systemd biriminde
olduğundan Binance erişimi (451) ya da çökme HL motorunu etkilemez. Kâğıtta her özellik açık ve işleme etkili: bu süreç gerçekten açar/kapar, kendi stopu/tasfiyesi/K-Z'si vardır (gölge/yalnız-kayıt değil).
Telegram: BU süreç ayrı işlem mesajı göndermez (kanal kapalı + komut yok); tek istisna erişim kesilince TEK ⚠️. HL motorunun saatlik özeti `ozet_satiri` ile tek satır ekler.
Erişim yoksa (açılışta 403/451 ya da çalışırken `binance_kagit_erisim_kesinti_sn` boyunca kesintisiz hata): TEK ⚠️ + temiz durma + çıkış kodu 4 (systemd `SuccessExitStatus=4`: yeniden başlatma/alarm döngüsü yok)."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

from copytrade.canli import telegram as tg
from copytrade.canli.binance_eslesme import EslemeTablosu
from copytrade.canli.binance_piyasa import BinancePiyasa, piyasa_post
from copytrade.canli.binance_yurutucu import BinanceKagitYurutucu

CIKIS_ERISIM_YOK = 4
DURUM_ALT_DIZIN = "binance_kagit"


def uyari_gonder(metin: str, ortam: dict | None = None, post: Callable[[str, dict], Any] | None = None) -> bool:
    """TEK ⚠️ Telegram mesajı. Token/chat yalnız ortamdan; yoksa sessiz (False). Hata yutulur; token hiçbir yere yazılmaz."""
    e = os.environ if ortam is None else ortam
    token, chat = (e.get("TELEGRAM_BOT_TOKEN") or "").strip(), (e.get("TELEGRAM_CHAT_ID") or "").strip()
    if not (token and chat):
        return False
    try:
        (post or tg.varsayilan_post)(f"https://api.telegram.org/bot{token}/sendMessage", {"chat_id": chat, "text": f"[CT] {metin}"})
        return True
    except Exception:                                      # noqa: BLE001
        return False


def sessiz_telegram(rules: dict, arka_plan: bool = True) -> tg.Telegram:
    """Binance kâğıt sürecinin Telegram'ı: token/chat BOŞ → kanal kapalı (mesajlar yalnız kayda yazılır), komut okuma yok. Ayrı işlem mesajı yok (kullanıcı kararı)."""
    return tg.Telegram(token="", chat_id="", arka_plan=arka_plan, sessiz_utc=(int(rules["canli_telegram_sessiz_bas_utc"]), int(rules["canli_telegram_sessiz_bit_utc"])))


class Bekci(threading.Thread):
    """Çalışırken erişim kesilirse TEK ⚠️ + motoru temiz durdurur (çıkış kodu 4). `kontrol()` tek adım (testte doğrudan çağrılır)."""

    def __init__(self, piyasa: BinancePiyasa, motor: Any, uyar: Callable[[str], Any], sinir_sn: float, aralik_sn: float = 15.0) -> None:
        super().__init__(daemon=True, name="binance-bekci")
        self.piyasa, self.motor, self.uyar, self.sinir_sn, self.aralik_sn = piyasa, motor, uyar, float(sinir_sn), aralik_sn
        self.durdur = threading.Event()
        self.uyardi = False

    def kontrol(self) -> bool:
        if self.uyardi or self.piyasa.kesinti_sn() < self.sinir_sn:
            return False
        self.uyardi = True
        self.uyar(f"⚠️ Binance kâğıt katmanı durdu: Binance verisi {self.piyasa.kesinti_sn():.0f} sn okunamadı ({self.piyasa.son_hata or 'bilinmiyor'}). HL sanal motoru etkilenmedi.")
        try:
            self.motor.kayit({"olay": "binance_erisim_yok", "kesinti_sn": round(self.piyasa.kesinti_sn(), 1), "son_hata": self.piyasa.son_hata})
        except Exception:                                  # noqa: BLE001
            pass
        self.motor.cikis_kodu = CIKIS_ERISIM_YOK
        self.motor.dur_istendi = True
        return True

    def run(self) -> None:
        while not self.durdur.wait(self.aralik_sn):
            if self.kontrol():
                return


def hazirla(rules: dict, post: Callable[[dict], Any], post_hizli: Callable[[dict], Any], ortam: dict | None = None, get: Callable | None = None,
            uyar: Callable[[str], Any] | None = None) -> tuple[Callable, Callable, Callable[[], BinanceKagitYurutucu], BinancePiyasa, int]:
    """Binance kâğıt sürecinin parçalarını kurar. Döner (post, post_hizli, yürütücü_fabrikası, piyasa, ilk_kod). `ilk_kod` 0 = erişim var; `CIKIS_ERISIM_YOK` = açılışta 403/451 (TEK ⚠️ gönderildi,
    süreç hiç başlamaz); geçici ağ hatası (ilk deneme) başlamayı engellemez (bekçi kesinti süresini izler)."""
    uyar = uyar or (lambda m: uyari_gonder(m, ortam))
    tablo = EslemeTablosu.yukle()
    piyasa = BinancePiyasa(rules, get)
    kod = 0
    if piyasa.erisim_testi() == "yok":
        uyar("⚠️ Binance kâğıt katmanı başlamadı: sunucudan Binance Futures'a erişim yok (HTTP 403/451). HL sanal motoru etkilenmedi.")
        kod = CIKIS_ERISIM_YOK
    return piyasa_post(post, piyasa, tablo), piyasa_post(post_hizli, piyasa, tablo), (lambda: BinanceKagitYurutucu(piyasa, tablo, rules)), piyasa, kod


# -------------------------------------------------------------------------------------------------------- HL motoru tarafı: saatlik özet satırı
def _oku(yol: Path) -> dict | None:
    try:
        v = json.loads(Path(yol).read_text(encoding="utf-8"))
        return v if isinstance(v, dict) else None
    except (OSError, ValueError):
        return None


def ozet_satiri(durum_dizin: Path, simdi_ms: int, bayat_sn: float = 1800.0) -> str | None:
    """HL motorunun saatlik Telegram özetine eklenecek TEK satır (`durum/binance_kagit/ozet.json`'dan). Dosya yoksa None (Binance kâğıt kurulu değil). Veri bayatsa 'durdu' uyarısı (⚠️).
    Biçim: 🅱️ Binance kâğıt: 3 açık · 12 kapanan · net +4,20 $ · kayma 0,8 bp. Hata motoru etkilemez (çağıran try/except)."""
    o = _oku(Path(durum_dizin) / DURUM_ALT_DIZIN / "ozet.json")
    if not o:
        return None
    yas = (simdi_ms - int(o.get("yazildi_ms") or 0)) / 1000.0
    if yas > bayat_sn:
        return f"⚠️ Binance kâğıt: durdu ya da veri {tg.tr_sayi(yas / 60, 0)} dk eski"
    b = o.get("binance") or {}
    net = float(o.get("ozsermaye_usd") or 0.0) - float(o.get("kasa_usd") or 0.0)
    kayma = b.get("kayma_bp_medyan")
    return (f"🅱️ Binance kâğıt: {int(o.get('acik_pozisyon') or 0)} açık · {int(b.get('kapanan') or 0)} kapanan · net {tg.tr_isaretli(net)} $"
            + (f" · kayma {tg.tr_sayi(float(kayma), 1)} bp" if kayma is not None else ""))


def simdi_ms() -> int:
    return int(time.time() * 1000)
