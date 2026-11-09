"""Telegram bildirimi + komutlar (Bot API doğrudan; görev T4 §1). Token/chat YALNIZ ortamdan (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`); yoksa kanal KAPALI (mesajlar yalnız kayda yazılır, motor çökmez).

`post(url, json) -> dict` enjekte edilir (testte sahte). K‑37: komut yalnız `chat.id == chat_id` ise ve özel sohbette ayrıca `from.id == chat_id` ise kabul edilir (grup kimliği negatif: grup üyesi, bot değil; `yetkili_mi`); yetkisiz komut kayda alınır; motor başlangıcından ÖNCE tarihli mesajlar yok sayılır (eski /dur yeniden tetiklenmez); `offset` motor.json'da kalıcıdır. Komutlar: `/dur` (yeni giriş/artırma durur; çıkış serbest), `/devam` (= `/baslat`; duraklatmayı kaldırır), `/kapat` (tüm pozisyonları kapat, motoru durdur) ve `/durum`. Mesajlar kısa, adres kısaltılır (ilk 8 karakter).

Denetim 2026-11-08: G-16 komut adı = ilk sözcük; bilinmeyen komuta yanıt; eski (motor kapalıyken ya da > 15 dk) komut yürütülmez, "İŞLENMEDİ" yanıtı alır; offset `_komutlar` bitince kalıcı.
G-18 önemli mesajda 2/5/15 sn yeniden deneme + 429 `retry_after`; gerçek kipte dolu olmayan emir 🚨 (gece sesli), emir mesajları kısa tamponda birleşir. S-13 tek `ATLA_TR`. S-22 alarm başlığında kip.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
import re
import threading
import time
from datetime import timedelta
from typing import Any, Callable

ONEMLI_ONEKLER = ("ALARM", "DUR", "TASFİYE", "🚨", "🛑", "💥")          # her zaman sesli
KOMUTLAR = ("/dur", "/devam", "/baslat", "/kapat", "/durum")
GECERLI_KOMUT_METNI = "/dur /devam /kapat /durum"          # bilinmeyen komut yanıtında gösterilir (`/baslat` = `/devam` eş adı, listelenmez)
KACIRILAN_PENCERE_S = 15 * 60          # G-16: bundan eski (ya da motor başlamadan önce gelmiş) komut YÜRÜTÜLMEZ; "işlenmedi, yeniden gönder" yanıtı alır
YENIDEN_BEKLEME_S = (2.0, 5.0, 15.0)   # G-18: önemli mesaj (ONEMLI_ONEKLER) gönderilemezse bu beklemelerle 3 kez daha denenir
RETRY_AFTER_TAVAN_S = 60.0             # G-18: 429 `retry_after` en çok bu kadar beklenir (gönderim iş parçacığı kilitlenmesin)


class CokIstek(RuntimeError):
    """Telegram 429 (Too Many Requests): `retry_after` sn sonra yeniden denenebilir."""

    def __init__(self, retry_after: float | None) -> None:
        super().__init__(f"429 retry_after={retry_after}")
        self.retry_after = retry_after


def _retry_after(govde: Any) -> float | None:
    try:
        return float(((govde or {}).get("parameters") or {}).get("retry_after"))
    except (TypeError, ValueError, AttributeError):
        return None


def komut_adi(metin: str) -> str:
    """G-16: komut adı = İLK sözcük, `@bot` eki atılır, küçük harf. '/kapat hemen' → '/kapat'; '/durum@sg_bot' → '/durum'."""
    parca = str(metin or "").strip().split()
    return parca[0].split("@")[0].lower() if parca else ""


def komut_kapali_mi(deger: Any) -> bool:
    """S-22: `TELEGRAM_KOMUT` = 'kapali' / 'kapalı' / 'KAPALI' / 'KAPALİ' → komut okuma kapalı (Türkçe ı/İ ASCII i sayılır)."""
    s = str(deger or "").strip().replace("İ", "i").replace("I", "i").replace("ı", "i").lower()
    return s == "kapali"


def kisa(adres: str) -> str:
    return adres[:8] + "…" if len(adres) > 8 else adres


def _urllib_post(url: str, yuk: dict) -> dict:
    """`requests` kurulu değilse yedek yol (yalnız standart kütüphane); HTTP hatasında istisna atar (429 → `CokIstek`)."""
    import urllib.error
    import urllib.request
    istek = urllib.request.Request(url, data=json.dumps(yuk).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(istek, timeout=25) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as hata:
        if hata.code != 429:
            raise
        try:
            govde = json.loads(hata.read().decode("utf-8"))
        except Exception:                              # noqa: BLE001
            govde = None
        raise CokIstek(_retry_after(govde)) from None


def varsayilan_post(url: str, yuk: dict) -> dict:
    try:
        import requests
    except ImportError:
        return _urllib_post(url, yuk)
    r = requests.post(url, json=yuk, timeout=25)
    if r.status_code == 429:                           # G-18: Telegram hız sınırı; `parameters.retry_after` kadar beklenir
        try:
            govde = r.json()
        except ValueError:
            govde = None
        raise CokIstek(_retry_after(govde))
    r.raise_for_status()
    return r.json()


class Telegram:
    def __init__(self, token: str | None = None, chat_id: str | None = None, post: Callable[[str, dict], dict] | None = None, ortam: dict | None = None,
                 kayit: Callable[[dict], None] | None = None, arka_plan: bool = False, baslangic_s: float | None = None,
                 sessiz_utc: tuple[int, int] | None = None, saat_s: Callable[[], float] | None = None, uyku: Callable[[float], None] | None = None,
                 zamanlayici: Callable[[float, Callable[[], None]], Any] | None = None) -> None:
        ortam = os.environ if ortam is None else ortam
        self.token = (token if token is not None else ortam.get("TELEGRAM_BOT_TOKEN", "")).strip()
        self.chat_id = str(chat_id if chat_id is not None else ortam.get("TELEGRAM_CHAT_ID", "")).strip()
        self.post = post or varsayilan_post
        self.komut_kapali = komut_kapali_mi(ortam.get("TELEGRAM_KOMUT", ""))      # G4: tek getUpdates tüketicisi (sunucu); kapalıysa yalnız gönderim (S-22: "kapalı" da)
        self.kayit = kayit
        self.sessiz_utc, self.saat_s = sessiz_utc, saat_s or time.time          # gece (UTC saat aralığı) önemsiz mesajlar sessiz (bildirim sesi yok); alarmlar HER ZAMAN sesli
        self.offset = 0
        self._bekleyen_offset: int | None = None       # G-16: yürütülmemiş komut taşıyan partiden ÖNCEKİ offset; `onayla()`ya dek motor.json'a bu yazılır
        self.kip: str | None = None                    # S-22: motor kurar; alarm başlığına kip etiketi eklenir
        self.baslangic_s = float(time.time() if baslangic_s is None else baslangic_s)       # bundan önce tarihli mesajlar yok sayılır
        self.yetkisiz_sayisi = 0
        self._yanitlanan: set[int] = set()             # "vardiya arasında geldi" yanıtı verilen update_id'ler (her mesaja bir kez)
        self.maske: list[str] = []                     # mesajlarda gizlenecek değerler (ör. kendi HL hesap adresimiz)
        self.hata_sayisi = 0
        self.gonderilen: list[str] = []
        self._havuz = None
        # G-18: yeniden deneme beklemesi ve gerçek kip emir tamponu yalnız arka planda (motor) ya da açıkça verilince; eşzamanlı yol (test, --kontrol) tek deneme / anında gönderim
        self._yeniden = arka_plan or uyku is not None
        self.uyku = uyku or time.sleep
        self.tampon_sn = 0.0                           # G-18: gerçek kip emir mesajı birleştirme süresi (sn); motor kurar (`canli_telegram_gercek_tampon_sn`)
        self._zamanlayici_fn = zamanlayici if zamanlayici is not None else (_varsayilan_zamanlayici if arka_plan else None)
        self._tampon: list[dict] = []
        self._tampon_bicim: Callable[[list[dict]], str] | None = None
        self._tampon_zaman: Any = None
        self._tampon_kilit = threading.Lock()
        if arka_plan:                                  # motor: gönderim emir hattını (25 sn'ye varan HTTP zaman aşımı) bekletmesin
            from concurrent.futures import ThreadPoolExecutor
            self._havuz = ThreadPoolExecutor(max_workers=1, thread_name_prefix="telegram")

    @property
    def acik(self) -> bool:
        return bool(self.token and self.chat_id)

    def _url(self, yontem: str) -> str:
        return f"https://api.telegram.org/bot{self.token}/{yontem}"

    @property
    def kalici_offset(self) -> int:
        """G-16: motor.json'a yazılacak offset. Yürütülmeyi bekleyen komut varken partiden ÖNCEKİ offset (çökmede komut yeniden okunur ve 'işlenmedi' yanıtı alır; iz bırakmadan kaybolmaz)."""
        return self.offset if self._bekleyen_offset is None else self._bekleyen_offset

    def onayla(self) -> None:
        """G-16: motor `_komutlar`ı bitirdi → ilerlemiş offset kalıcı olabilir."""
        self._bekleyen_offset = None

    def tampona(self, oge: dict, bicim: Callable[[list[dict]], str]) -> None:
        """G-18: gerçek kip emir mesajları `tampon_sn` içinde TEK mesajda birleşir (ilk öğe zamanlayıcıyı başlatır). Zamanlayıcı yoksa / kanal kapalıysa / süre 0 → anında."""
        with self._tampon_kilit:
            self._tampon.append(oge)
            self._tampon_bicim = bicim
            bekle = self.tampon_sn > 0 and self.acik and self._zamanlayici_fn is not None
            if bekle and self._tampon_zaman is None:
                self._tampon_zaman = self._zamanlayici_fn(self.tampon_sn, self.tampon_bosalt)
        if not bekle:
            self.tampon_bosalt()

    def tampon_bosalt(self) -> None:
        """Tampondaki emirleri tek mesajda gönderir (zamanlayıcı ya da vardiya sonu)."""
        with self._tampon_kilit:
            liste, self._tampon, self._tampon_zaman = self._tampon, [], None
            bicim = self._tampon_bicim
        if liste and bicim is not None:
            self.gonder(bicim(liste))

    def gonder(self, metin: str) -> bool:
        """Mesaj gönderir; hata motoru DURDURMAZ (sayılır). Token günlüğe/hata metnine ASLA yazılmaz."""
        metin = kip_etiketle(metin, self.kip)
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

    def sessiz_mi(self, metin: str) -> bool:
        if self.sessiz_utc is None or metin.startswith(ONEMLI_ONEKLER):
            return False
        saat = datetime.fromtimestamp(self.saat_s(), timezone.utc).hour
        bas, bit = self.sessiz_utc
        return (bas <= saat < bit) if bas < bit else (saat >= bas or saat < bit)

    def _gonder_sync(self, metin: str) -> bool:
        """G-18: önemli mesaj (ONEMLI_ONEKLER) gönderilemezse 2/5/15 sn beklemeyle 3 kez daha denenir; 429'da en az `retry_after` (≤ 60 sn) beklenir, önemsiz mesaj da 429'da bir kez
        yeniden denenir. Bekleme yalnız `_yeniden` (arka plan iş parçacığı) açıkken; eşzamanlı yolda tek deneme. `hata_sayisi` yalnız son başarısızlıkta artar."""
        plan = list(YENIDEN_BEKLEME_S) if (metin.startswith(ONEMLI_ONEKLER) and self._yeniden) else []
        deneme = 0
        while True:
            deneme += 1
            try:
                yanit = self.post(self._url("sendMessage"), {"chat_id": self.chat_id, "text": metin[:4000], "disable_notification": self.sessiz_mi(metin)})
                if isinstance(yanit, dict) and yanit.get("ok") is False and int(yanit.get("error_code") or 0) == 429:
                    raise CokIstek(_retry_after(yanit))
                return True
            except Exception as hata:                  # noqa: BLE001 - ağ/HTTP hatası; ayrıntı (URL'de token var) yazılmaz
                ra = hata.retry_after if isinstance(hata, CokIstek) else None
                if isinstance(hata, CokIstek) and self._yeniden and deneme == 1 and not plan:
                    plan = [0.0]                       # önemsiz mesaj: 429'da bir kez daha (retry_after kadar bekleyip)
                if not plan:
                    self.hata_sayisi += 1
                    if self.kayit:
                        self.kayit({"olay": "telegram_hata", "tur": type(hata).__name__, "deneme": deneme})
                    return False
                bekle = plan.pop(0)
                if ra is not None:
                    bekle = max(bekle, min(float(ra), RETRY_AFTER_TAVAN_S))
                if self.kayit:
                    self.kayit({"olay": "telegram_yeniden", "tur": type(hata).__name__, "deneme": deneme, "bekle_sn": bekle})
                self.uyku(bekle)

    def yetkili_mi(self, m: dict) -> bool:
        """Komut yetkisi: `chat.id == TELEGRAM_CHAT_ID` ZORUNLU. Özel sohbet (pozitif kimlik) → ek olarak `from.id == chat_id`. Grup / süper grup (kimlik '-' ile başlar; Telegram
        grup kimlikleri negatiftir) → `from.id` kullanıcının kendi kimliğidir, chat kimliğine eşit OLAMAZ: grubun üyesinden gelen komut kabul edilir (grup üyeliğini kullanıcı yönetir),
        bot hesaplarından gelen (`from.is_bot`) reddedilir. Diğer her sohbet reddedilir."""
        if not self.chat_id or str((m.get("chat") or {}).get("id", "")) != self.chat_id:
            return False
        kimden = m.get("from") or {}
        if self.chat_id.startswith("-"):
            return not kimden.get("is_bot", False)
        return str(kimden.get("id", "")) == self.chat_id

    def komutlari_al(self) -> list[str]:
        """Yeni komutları (`KOMUTLAR`; komut adı = İLK sözcük, '/kapat hemen' → '/kapat') döner; yalnız `chat_id`'den gelenler; offset ilerler.
        G-16: bilinmeyen komut → geçerli komutları listeleyen yanıt; motor başlamadan önce ya da `KACIRILAN_PENCERE_S`'den (15 dk) önce gelmiş komut YÜRÜTÜLMEZ, "İŞLENMEDİ" yanıtı
        alır (her update bir kez). Yürütülecek komut dönerse `kalici_offset` partiden önceki değerde kalır; motor `_komutlar` bitince `onayla()` çağırır."""
        if not self.acik or self.komut_kapali:
            return []
        try:
            yanit = self.post(self._url("getUpdates"), {"offset": self.offset, "timeout": 0, "allowed_updates": ["message"]})
        except Exception as hata:                      # noqa: BLE001
            self.hata_sayisi += 1
            if self.kayit:
                self.kayit({"olay": "telegram_hata", "tur": type(hata).__name__})
            return []
        onceki = self.offset
        simdi = float(self.saat_s())
        komutlar: list[str] = []
        yanitlar: list[str] = []
        for u in (yanit or {}).get("result", []):
            self.offset = max(self.offset, int(u.get("update_id", 0)) + 1)
            m = u.get("message") or {}
            metin = komut_adi(m.get("text", ""))
            if not metin.startswith("/"):
                continue
            if not self.yetkili_mi(m):
                self.yetkisiz_sayisi += 1
                if self.kayit:
                    self.kayit({"olay": "telegram_yetkisiz", "komut": metin[:20], "chat": str((m.get("chat") or {}).get("id", ""))[:3] + "…"})
                continue
            uid = int(u.get("update_id", 0))
            tarih = float(m.get("date", 0) or 0)
            if metin not in KOMUTLAR:
                if self.kayit:
                    self.kayit({"olay": "telegram_bilinmeyen_komut", "komut": metin[:20]})
                if uid not in self._yanitlanan:
                    self._yanitlanan.add(uid)
                    yanitlar.append(msg_bilinmeyen_komut(metin))
                continue
            once_basladi = tarih < self.baslangic_s
            if once_basladi or simdi - tarih > KACIRILAN_PENCERE_S:
                if self.kayit:
                    self.kayit({"olay": "telegram_eski_komut", "komut": metin[:20], "yas_sn": round(simdi - tarih)})
                if uid not in self._yanitlanan:
                    self._yanitlanan.add(uid)
                    yanitlar.append(msg_komut_islenmedi(metin, simdi - tarih, once_basladi))      # yalnız yanıt verilir; eski komut ASLA yürütülmez
                continue
            komutlar.append(metin)
        if komutlar and self._bekleyen_offset is None:
            self._bekleyen_offset = onceki
        if yanitlar:
            self.gonder("\n".join(yanitlar))
        return komutlar


def _varsayilan_zamanlayici(sn: float, f: Callable[[], None]) -> Any:
    t = threading.Timer(sn, f)
    t.daemon = True
    t.start()
    return t


def kip_etiketle(metin: str, kip: str | None) -> str:
    """S-22: `alarm()` biçimli mesajın (ilk satır + AYRAÇ) başlığına kip eklenir: '🚨 ALARM: x (GERÇEK PARA)'. Başlıkta kip zaten varsa (emir/durum/günlük özet) dokunulmaz."""
    if not kip:
        return metin
    ilk, ayr, kalan = metin.partition("\n")
    if not kalan.startswith(AYRAC) or kip_adi(kip) in ilk or "[GERÇEK]" in ilk or "[sanal]" in ilk:
        return metin
    return f"{ilk} ({kip_adi(kip)}){ayr}{kalan}"


def msg_bilinmeyen_komut(komut: str) -> str:
    return f"❓ Bilinmeyen komut: {komut[:30]}. Geçerli komutlar: {GECERLI_KOMUT_METNI}"


def msg_komut_islenmedi(komut: str, yas_sn: float, motor_kapaliydi: bool) -> str:
    """G-16 (§5): '📭 /kapat 23 dk önce geldi, motor o sırada kapalıydı; İŞLENMEDİ. Hâlâ istiyorsan yeniden gönder.'"""
    dk = max(0, round(yas_sn / 60))
    neden = "motor o sırada kapalıydı" if motor_kapaliydi else f"{KACIRILAN_PENCERE_S // 60} dk sınırını aştı"
    return f"📭 {komut} {dk} dk önce geldi, {neden}; İŞLENMEDİ. Hâlâ istiyorsan yeniden gönder."


def msg_kapat_alindi(kip: str) -> str:
    return f"🛑 /kapat alındı ({kip_adi(kip)}): tüm pozisyonlar reduce-only kapatılıyor; bitince ayrı mesaj gelecek."


# ---------------------------------------------------------------------------------------------- mesaj biçimleri (sade Türkçe, emojili)
KIP_ADI = {"sanal": "sanal · deneme parası", "gercek": "GERÇEK PARA"}
NEDEN_TR = {"ilk_gun": "ilk kadro", "bos_slot": "boş yer açıldı", "kadro_disi": "günlük kadrodan düştü", "dusme": "slot değeri düştü (kural)"}
EYLEM_TR = {"ac": "pozisyon açtı", "artir": "pozisyonunu artırdı", "azalt": "pozisyonunu azalttı", "kapat": "pozisyonu kapattı"}


def tr_sayi(x: float, ondalik: int = 2) -> str:
    """1234.5 → '1.234,50' (Türkçe gösterim)."""
    return f"{x:,.{ondalik}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def tr_isaretli(x: float, ondalik: int = 2) -> str:
    """12.5 → '+12,50'; -3 → '−3,00'."""
    return ("+" if x >= 0 else "−") + tr_sayi(abs(x), ondalik)


def tr_yuzde(oran: float, ondalik: int = 2) -> str:
    """0.0125 → '+%1,25'."""
    return ("+" if oran >= 0 else "−") + "%" + tr_sayi(abs(oran) * 100, ondalik)


def kip_adi(kip: str) -> str:
    return KIP_ADI.get(kip, kip)


AYRAC = "━━━━━━━━━━━━━━"


def msg_saha(tur: str, adres: str, neden: str, sira: int | None = None) -> str:
    kok, _, ek = neden.partition(" ")
    aciklama = NEDEN_TR.get(kok, kok) + (f" {ek}" if ek else "")
    if tur == "giriş":
        return f"➕ Yeni trader takibe alındı: {kisa(adres)}\n↳ Neden: {aciklama}"
    return f"➖ Trader takipten çıktı: {kisa(adres)}\n↳ Neden: {aciklama}"


DURUM_BUYUK = {"red": "REDDEDİLDİ", "dolmadi": "DOLMADI", "kismi": "KISMEN DOLDU", "belirsiz": "SONUCU BELİRSİZ"}
SONRAKI_ADIM = {"kapat": "Kapanış daha geniş bantla yeniden denenecek; olmazsa kuyruğa alınır ve dakikada bir denenir. Tekrarlarsa: /kapat ya da HL web.",
                "azalt": "Azaltma bir sonraki dakikada yeniden denenecek. Tekrarlarsa: /kapat ya da HL web.",
                "ac": "Pozisyon açılmadı (yeniden denenmez).", "artir": "Artırma yapılmadı (yeniden denenmez)."}


def msg_emir_gercek_sorun(coin: str, eylem: str, usd: float, durum: str, neden: str = "") -> str:
    """G-18 (§5): gerçek kipte DOLU olmayan emir 🚨 ile başlar (gece de sesli). Örnek:
    '🚨 [GERÇEK] EMİR REDDEDİLDİ — BTC kapat 27,30 $\\nneden: hl_err: …\\nKapanış … yeniden denenecek …'."""
    satirlar = [f"🚨 [GERÇEK] EMİR {DURUM_BUYUK.get(durum, durum.upper())} — {coin} {eylem or 'emir'} {tr_sayi(usd)} $"]
    if neden:
        satirlar.append(f"neden: {neden[:200]}")
    if eylem in SONRAKI_ADIM:
        satirlar.append(SONRAKI_ADIM[eylem])
    return "\n".join(satirlar)


def msg_emir(adres: str, coin: str, yon: str, usd: float, px: float | None, kayma: float | None, durum: str, kip: str, eylem: str = "", neden: str = "") -> str:
    ne = "AL" if yon == "B" else "SAT"
    ok = "🟢" if yon == "B" else "🔴"
    ilk = f"{ok} {coin} {ne}: {tr_sayi(usd, 0 if usd >= 100 else 1)} $ ({kip_adi(kip)})"
    nedeni = f"\n↳ Trader {kisa(adres)} {EYLEM_TR.get(eylem, 'işlem yaptı')}, biz de kopyaladık"
    if durum != "dolu" and kip == "gercek":
        return msg_emir_gercek_sorun(coin, eylem, usd, durum, neden) + f"\n↳ Trader {kisa(adres)} · {ne}"
    if durum != "dolu":
        return f"⚠️ {coin} {ne}: emir tam dolmadı ({durum}) · istenen {tr_sayi(usd, 0 if usd >= 100 else 1)} $ ({kip_adi(kip)}){nedeni}"
    return ilk + nedeni + (f"\n↳ Fiyat {px:.6g}" if px else "") + (f" · trader'a göre fark {kayma * 1e4:+.1f} bp" if kayma is not None else "")


def msg_gunluk(kip: str, kasa: float, ozsermaye: float, onceki_oz: float, emir_sayisi: int, saha: int, n: int, acik: list[dict], funding_usd: float | None = None) -> str:
    """Sabah 09:00 TSİ: DÜNÜN sonucu = son özetten (≈24 saat) bu yana. `onceki_oz`: önceki özetteki özsermaye (ilk özette kasa). `acik`: {coin, sz, usd, kz_usd}."""
    fark = ozsermaye - onceki_oz
    satirlar = [f"☀️ Günaydın! Dünün sonucu ({kip_adi(kip)})", AYRAC,
                f"{'📈' if fark >= 0 else '📉'} Son 24 saat: {tr_isaretli(fark)} $ ({tr_yuzde(fark / kasa)})",
                f"💰 Kasa şimdi: {tr_sayi(ozsermaye)} $ (başlangıç {tr_sayi(kasa, 0)} $)",
                f"🏁 Başlangıçtan beri: {tr_yuzde(ozsermaye / kasa - 1)}", AYRAC,
                f"🧾 Dün {emir_sayisi} emir verildi · 👥 takipte {saha}/{n} trader"]
    if funding_usd is not None:
        satirlar.append(f"💸 Funding (sanal): {tr_isaretli(funding_usd)} $")
    if acik:
        satirlar.append(f"📌 Açık pozisyonlar ({len(acik)}):")
        for x in sorted(acik, key=lambda x: -x["usd"])[:6]:
            satirlar.append(f"{'🟩' if x['kz_usd'] >= 0 else '🟥'} {x['coin']} · {tr_sayi(x['usd'], 0)} $ · {'uzun' if x['sz'] > 0 else 'kısa'} · {tr_isaretli(x['kz_usd'])} $")
        if len(acik) > 6:
            satirlar.append(f"… ve {len(acik) - 6} küçük pozisyon daha")
    else:
        satirlar.append("📌 Açık pozisyon yok")
    return "\n".join(satirlar)


BAYRAK_TR = {"gunluk_kayip": "🔻 Günlük kayıp freni: bugün yeni işlem yok", "mutabakat": "🧮 Mutabakat farkı: yeni işlem kapalı", "elle_dur": "⏸️ Yeni işlem duraklatıldı (/devam ile açılır)",
             "fren": "🧯 Patlama freni: bir trader'dan yeni açılış beklemede", "kasa_siniri": "🔒 Kasa sınırı aşıldı: yeni işlem kapalı",
             "belirsiz": "❓ Sonucu belirsiz emir borsadan sorgulanıyor: yeni işlem kapalı"}


def msg_durum(kip: str, ozsermaye: float, kasa: float, saha: int, n: int, inen: int, acik_poz: int, emir: int, dur: bool, duraklat: bool = False, bayraklar: list[str] | None = None) -> str:
    """Anlık durum. `bayraklar`: etkin risk bayrakları (`gunluk_kayip`, `mutabakat`, `elle_dur`, `fren`...); yoksa 'normal'."""
    bayrak = list(dict.fromkeys([*(bayraklar or []), *(["elle_dur"] if duraklat else [])]))
    risk = ("🛑 Motor DURDURULDU" if dur else "\n".join(BAYRAK_TR.get(b, f"⚠️ {b}") for b in bayrak) if bayrak else "🛡️ Risk: normal, motor çalışıyor")
    return (f"📊 Anlık durum ({kip_adi(kip)})\n{AYRAC}\n💰 Özsermaye {tr_sayi(ozsermaye)} $ (kasaya göre {tr_yuzde(ozsermaye / kasa - 1)})\n"
            f"👥 Takipte {saha}/{n} trader" + (f" · {inen} tanesi ayrılıyor (pozisyonları kapanıyor)" if inen else "") + f"\n"
            f"📌 Açık pozisyon: {acik_poz}\n🧾 Bu turda emir: {emir}\n" + risk)


def msg_emir_ozeti(kip: str, emirler: list[dict], dakika: float) -> str:
    """Biriken emirleri TEK mesajda özetler. `emirler`: {adres, coin, yon, usd, durum, eylem, px, kayma}. Tek emir varsa ayrıntılı `msg_emir` biçimi. Aynı (trader, coin, yön, eylem) satırları birleşir."""
    if len(emirler) == 1:
        e = emirler[0]
        return msg_emir(e["adres"], e["coin"], e["yon"], e["usd"], e.get("px"), e.get("kayma"), e["durum"], kip, e.get("eylem", ""), e.get("neden", ""))
    gruplar: dict[tuple, list[dict]] = {}
    for e in emirler:
        gruplar.setdefault((e["adres"], e["coin"], e["yon"], e.get("eylem", "")), []).append(e)
    sorunlu = [e for e in emirler if e["durum"] != "dolu"]
    satirlar: list[str] = []
    if kip == "gercek" and sorunlu:                    # G-18: birleşik mesajda da sorunlu emir varsa 🚨 başta (gece sesli); her sorunlu emir ayrı satır + neden
        satirlar += [msg_emir_gercek_sorun(e["coin"], e.get("eylem", ""), e["usd"], e["durum"], e.get("neden", "")).splitlines()[0] + (f" · {e['neden'][:120]}" if e.get("neden") else "")
                     for e in sorunlu]
    satirlar.append(f"🧾 {'Son birkaç saniyede' if dakika < 1 else f'Son {dakika:.0f} dakikada'} {len(emirler)} emir ({kip_adi(kip)})")
    for (adres, coin, yon, eylem), liste in sorted(gruplar.items(), key=lambda kv: -sum(x["usd"] for x in kv[1])):
        toplam = sum(x["usd"] for x in liste)
        eksik = sum(1 for x in liste if x["durum"] != "dolu")
        satirlar.append(f"{'🟢 AL' if yon == 'B' else '🔴 SAT'} {coin}: {tr_sayi(toplam, 0)} $" + (f" ({len(liste)} emir)" if len(liste) > 1 else "")
                        + f" · {kisa(adres)} {EYLEM_TR.get(eylem, 'işlem yaptı')}" + (f" · ⚠️ {eksik} tanesi tam dolmadı" if eksik else ""))
    kaymalar = [abs(x["kayma"]) * 1e4 for x in emirler if x.get("kayma") is not None]
    if kaymalar:
        satirlar.append(f"↳ Trader'a göre ortalama fark {sum(kaymalar) / len(kaymalar):.1f} bp (küçük = iyi)")
    return "\n".join(satirlar)


TSI = timezone(timedelta(hours=3))
# S-13: atlanan sinyal etiketlerinin TEK kaynağı (Telegram + pano). `min_emir_atlandi` eşiği `radar_min_emir_usd` (11 $) ile aynı; test bunu denetler.
ATLA_TR = {"gec_acilis": "geç görülen açılış", "spot_atlandi": "spot coin", "hip3_atlandi": "HIP-3 coin", "ters_netlesme": "ters netleşme (K‑41)", "trader_hesap_yok": "trader hesabı okunamadı",
           "hesap_yok": "trader hesap değeri kullanılamadı", "slot_tavani": "slot tavanı", "marj_yok": "marj yok", "coin_tavani": "coin tavanı", "min_nosyonel": "çok küçük emir",
           "min_emir_atlandi": "çok küçük (< 11 $)", "inen_trader": "ayrılan trader (yeni alım yok)", "patlama_freni": "patlama freni", "dur": "motor durdu",
           "gunluk_kayip": "günlük kayıp freni", "mutabakat": "mutabakat farkı", "elle_dur": "elle duraklatma", "kasa_siniri": "kasa sınırı", "belirsiz": "belirsiz emir bekleniyor",
           "kapanis_eksik": "kapanış eksik"}
KACIRILAN_NEDENLER = ("gec_acilis", "trader_hesap_yok", "hesap_yok")      # S-13: "kaçırılan" (geç görülen / veri yok); geri kalanı "kural gereği"


def atla_etiket(neden: str, adresler: dict[str, int] | None = None) -> str:
    """ATLA_TR etiketi; `inen_trader` tek trader'dansa adres eklenir: 'ayrılan trader 0x8730ab… (yeni alım yok)'."""
    if neden == "inen_trader" and adresler and len(adresler) == 1:
        return f"ayrılan trader {kisa(next(iter(adresler)))} (yeni alım yok)"
    return ATLA_TR.get(neden, neden)


def atlanan_satirlari(atlanan: dict[str, int], islem: int | None = None, adresler: dict[str, dict[str, int]] | None = None) -> list[str]:
    """S-13 (§5): kopyalanmayan trader dolumu = "kural gereği" + "kaçırılan" (KACIRILAN_NEDENLER). `islem`: ayrı işlem sayısı ((adres, coin, trader_dolum_ms // 1000) tekil).
    Kaçırılan > 0 → ilk satır ⚠️ ve kaçırılan nedenleri; değilse ⏭️ ve kural gereği nedenleri (en çok 3)."""
    if not atlanan:
        return []
    adresler = adresler or {}
    top = sum(atlanan.values())
    kacan = {k: v for k, v in atlanan.items() if k in KACIRILAN_NEDENLER and v}
    kural = {k: v for k, v in atlanan.items() if k not in KACIRILAN_NEDENLER and v}
    n_kacan, n_kural = sum(kacan.values()), sum(kural.values())
    sirali = lambda d: sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))          # noqa: E731
    ilk = f"{'⚠️' if n_kacan else '⏭️'} Kopyalanmayan trader dolumu: {top}" + (f" (≈{islem} ayrı işlem)" if islem is not None else "")
    kural_satir = f"   • kural gereği {n_kural}"
    if not n_kacan and kural:
        kural_satir += ": " + " · ".join(f"{v} {atla_etiket(k, adresler.get(k))}" for k, v in sirali(kural)[:3])
    if not n_kacan:
        kacan_satir = "   • kaçırılan 0 (geç görülen / veri yok)"
    elif len(kacan) == 1:
        kacan_satir = f"   • KAÇIRILAN {n_kacan}: {atla_etiket(next(iter(kacan)))}"
    else:
        kacan_satir = f"   • KAÇIRILAN {n_kacan}: " + " · ".join(f"{v} {atla_etiket(k)}" for k, v in sirali(kacan))
    return [ilk, kural_satir, kacan_satir]


def _yuzde1(oran: float) -> str:
    """0.0125 → '+%1,3'; −0.012 → '−%1,2'; yuvarlanınca sıfır olan → '%0,0' (işaretsiz)."""
    y = round(oran * 100, 1)
    return "%0,0" if y == 0 else ("+" if y > 0 else "−") + "%" + tr_sayi(abs(y), 1)


def _tsi_saat(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, TSI).strftime("%H:%M")


def msg_sanal_saatlik(bas_ms: int, bit_ms: int, sure_dk: float, emirler: list[dict], atlanan: dict[str, int], kasa_bilgi: tuple[float, float, float] | None = None,
                      atla_islem: int | None = None, atla_adres: dict[str, dict[str, int]] | None = None) -> str:
    """SANAL kip saatlik özet (tek mesaj). `emirler`: {adres, coin, yon, usd ($, sanal 1.000 $ kopya ölçeği), durum, eylem, kayma (oran)}; `atlanan`: neden -> adet. Emir yoksa '' (mesaj gönderilmez). `kasa_bilgi` = (özsermaye $, gün başı özsermaye $, başlangıç kasası $) — pano ile aynı tanım: yüzdeler kasaya göre.
    `atla_islem`: atlanan dolumların ayrı işlem sayısı; `atla_adres`: neden -> {adres: adet} (S-13, `atlanan_satirlari`)."""
    if not emirler:
        return ""
    sure = f"{int(sure_dk // 60)} saat" if sure_dk >= 60 and sure_dk % 60 == 0 else f"{sure_dk:.0f} dk"
    say = {k: sum(1 for e in emirler if e.get("eylem") == k) for k in ("ac", "artir", "azalt", "kapat")}
    en = max(emirler, key=lambda e: e["usd"])
    satirlar = [f"🧾 Son {sure} ({_tsi_saat(bas_ms)}–{_tsi_saat(bit_ms)} TSİ): {len(emirler)} emir · sanal",
                f"➕ açılış {say['ac']} · ⬆️ artırma {say['artir']} · ⬇️ azaltma {say['azalt']} · ✖️ kapanış {say['kapat']}",
                f"🏆 En büyük: {tr_sayi(en['usd'], 0 if en['usd'] >= 100 else 1)} $ ({en['coin']}, {'AL' if en['yon'] == 'B' else 'SAT'}) · {kisa(en['adres'])}"]
    satirlar += atlanan_satirlari(atlanan, atla_islem, atla_adres)
    eksik = sum(1 for e in emirler if e["durum"] != "dolu")
    if eksik:
        satirlar.append(f"⚠️ {eksik} emir tam dolmadı")
    toplam = f"💵 Tutar toplamı: {tr_sayi(sum(e['usd'] for e in emirler), 0)} $"
    kaymalar = [abs(e["kayma"]) for e in emirler if e.get("kayma") is not None]
    satirlar.append(toplam + (f" · kayma ort. %{tr_sayi(sum(kaymalar) / len(kaymalar) * 100, 3)}" if kaymalar else ""))
    if kasa_bilgi is not None and kasa_bilgi[2] > 0:
        oz, gun_basi, kasa = kasa_bilgi
        gun, top = oz - gun_basi, oz - kasa
        isaret = lambda x: "🟢" if x >= 0 else "🔴"        # noqa: E731
        satirlar.append(f"💰 Kasa: {tr_sayi(oz)} $ · bugün {isaret(gun)} {tr_isaretli(gun)} $ ({_yuzde1(gun / kasa)}) · başlangıçtan {isaret(top)} {tr_isaretli(top)} $ ({_yuzde1(top / kasa)})")
    return "\n".join(satirlar)


def msg_sanal_saatlik_bos(bas_ms: int, bit_ms: int, sure_dk: float, atlanan: dict[str, int], kasa_bilgi: tuple[float, float, float] | None = None,
                          atla_islem: int | None = None, atla_adres: dict[str, dict[str, int]] | None = None) -> str:
    """SANAL kip: pencerede emir YOK ama sistem canlı (`canli_telegram_sanal_bos_mesaj`). Tek kısa satır grubu; emir sayısı 0."""
    sure = f"{int(sure_dk // 60)} saat" if sure_dk >= 60 and sure_dk % 60 == 0 else f"{sure_dk:.0f} dk"
    satirlar = [f"🧾 Son {sure} ({_tsi_saat(bas_ms)}–{_tsi_saat(bit_ms)} TSİ): emir yok · sistem çalışıyor"]
    satirlar += atlanan_satirlari(atlanan, atla_islem, atla_adres)
    if kasa_bilgi is not None and kasa_bilgi[2] > 0:
        oz, gun_basi, kasa = kasa_bilgi
        gun, top = oz - gun_basi, oz - kasa
        isaret = lambda x: "🟢" if x >= 0 else "🔴"        # noqa: E731
        satirlar.append(f"💰 Kasa: {tr_sayi(oz)} $ · bugün {isaret(gun)} {tr_isaretli(gun)} $ ({_yuzde1(gun / kasa)}) · başlangıçtan {isaret(top)} {tr_isaretli(top)} $ ({_yuzde1(top / kasa)})")
    return "\n".join(satirlar)


def alarm(baslik: str, govde: str, ikon: str = "🚨") -> str:
    """Sorun mesajı: ikon + başlık, ayraç, sade açıklama. Her zaman sesli (`ONEMLI_ONEKLER`)."""
    return f"{ikon} {baslik}\n{AYRAC}\n{govde}"
