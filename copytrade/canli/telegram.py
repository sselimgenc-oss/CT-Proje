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
import secrets
import threading
import time
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable

from copytrade.canli.takma_ad import takma_ad

ONEMLI_ONEKLER = ("ALARM", "DUR", "TASFİYE", "🚨", "🛑", "💥", "🔴")          # her zaman sesli
PROJE_ETIKETI = "[CT]"                    # her mesajın İLK satırı "[CT] <başlık>" (INFO/WARN/CRIT kullanıcıya GÖSTERİLMEZ; yalnız iç mantıkta sesli/sessiz için)
KOMUTLAR = ("/durum", "/rapor", "/yardim", "/start", "/durdur", "/devam", "/hepsini_kapat")      # standart komut adları (motora iki adımlı onaydan sonra bu adlarla gider)
ESKI_AD = {"/dur": "/durdur", "/kapat": "/hepsini_kapat", "/baslat": "/devam"}        # eski adlar eş ad olarak çalışır (anlamları değişmedi)
YOK_KOMUTLAR = ("/kurulumlar", "/ders", "/kademe", "/kademe_devam", "/onayla", "/reddet")        # ortak standartta var, CT'de yok: "henüz yok" yanıtı
IKI_ADIMLI = ("/durdur", "/devam", "/hepsini_kapat")      # riskli komutlar: 4 haneli kod + 120 sn
ONAY_SURE_S = 120.0
GECERLI_KOMUT_METNI = "/durum /rapor /durdur /devam /hepsini_kapat /yardim"          # bilinmeyen komut yanıtında gösterilir (eski adlar /dur /kapat /baslat eş ad, listelenmez)
HIZ_LIMITI_DK = 15                        # standart: dakikada en çok 15 mesaj (fazlası kuyrukta bekler, kaybolmaz)
INFO_OMUR_S = 24 * 3600.0                 # standart: 24 saatten eski INFO mesajı atılır
TEKRAR_PENCERE_S = 300.0                  # standart: aynı uyarı (WARN/CRIT, aynı metin / anahtar) bu sürede bir kez
UYARI_ARA_S = 6 * 3600.0                  # kullanıcı standardı: aynı uyarı en çok 6 saatte bir (`Telegram.uyar`); düzelince TEK "Düzeldi" (`Telegram.duzeldi`)
BASTIRILAN_TURLER = frozenset({"saha_giris", "saha_cikis", "saha_uyari", "saatlik_bos", "emir_ozeti", "emir_artir_azalt", "islem_satiri",
                           "haftalik_kadro", "kopya_kacan", "kadro_surum_bekleniyor", "ogrenme_ders"})      # KOD ANAHTARI: bu türler Telegram'a GİTMEZ; kayda `tg_bastirildi` (tür ile) yazılır, tespit/kayıt/pano sürer. Geri açmak için `Telegram.bastirilan` kümesinden çıkarın
MESAJ_AZAMI = 3500                        # standart: mesaj başına en çok karakter
KACIRILAN_PENCERE_S = 15 * 60          # G-16: bundan eski (ya da motor başlamadan önce gelmiş) komut YÜRÜTÜLMEZ; "işlenmedi, yeniden gönder" yanıtı alır
YENIDEN_BEKLEME_S = (2.0, 5.0, 15.0)   # G-18: önemli mesaj (ONEMLI_ONEKLER) gönderilemezse bu beklemelerle 3 kez daha denenir
GUNCELLEME_SESSIZ_S = 15 * 60.0       # K-80: güncellemeden sonraki bu sürede (işaret dosyası `guncelleme_zamani`) yalnız ÖLÜMCÜL uyarılar gider; diğer WARN/CRIT sürenin sonunda, hâlâ geçerliyse gönderilir
DOGRULAMA_SN = 45.0                    # K-80: durum alarmları (bot durdu/veri eski/kapanış eksik/HL okunamıyor...) göndermeden önce bu kadar sonra koşul İKİNCİ kez sınanır (motor kurar; Telegram() varsayılanı 0 = kapalı)
OLUMCUL_ISARETLER = ("bot durdu", "bot hâlâ kapalı", "tasfiye", "kayıp sınırı", "sert fren", "kapanış eksik", "kapanmadı", "kapanış bugün", "felaket stopu", "stopsuz pozisyon", "durdurma", "vardiya başlamadı", "yalnız kapanış")
OLUMCUL_ONEKLER = ("🔴", "🛑", "💥")
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


def onem_duzeyi(metin: str) -> str:
    """Standart önem düzeyi (INFO/WARN/CRIT) metnin ilk satırından: önemli önekler (ALARM, 🚨, 🛑, 💥 ...) CRIT; UYARI/⚠️/⏸️/📭/❓ WARN; geri kalanı INFO."""
    ilk = metin.split("\n", 1)[0]
    if metin.startswith(ONEMLI_ONEKLER) or "ALARM" in ilk:
        return "CRIT"
    if "UYARI" in ilk or ilk.startswith(("⚠️", "⏸️", "📭", "❓", "🧮", "🔐")):
        return "WARN"
    return "INFO"


_BASLIK_KOD = re.compile(r"^((?:🚨|⚠️|ℹ️|🛑)\s+)?(ALARM|UYARI|BİLGİ):\s*(.*)$")
_BASLIK_IKON = {"ALARM": "🚨", "UYARI": "⚠️", "BİLGİ": "ℹ️"}


def baslik_sade(metin: str) -> str:
    """Giden mesajın ilk satırı: 'ALARM:/UYARI:/BİLGİ:' kod sözcüğü atılır, ikon kalır ('🚨 ALARM: kasa sınırı aşıldı' → '🚨 Kasa sınırı aşıldı'). Seviye (INFO/WARN/CRIT) kullanıcıya yazılmaz."""
    ilk, ayr, kalan = metin.partition("\n")
    m = _BASLIK_KOD.match(ilk)
    if not m:
        return metin
    ikon, rest = (m.group(1) or _BASLIK_IKON[m.group(2)] + " "), m.group(3)
    bas = ("İ" if rest[:1] == "i" else rest[:1].upper()) + rest[1:]
    return f"{ikon}{bas}{ayr}{kalan}"


def mesaj_kirp(metin: str, azami: int = MESAJ_AZAMI) -> str:
    """Standart: ≤ 3500 karakter; sığmazsa SONDAN kısaltılır (ilk satırlar = başlık/kritik satır sabit kalır)."""
    if len(metin) <= azami:
        return metin
    ek = "\n…(kısaltıldı)"
    return metin[:azami - len(ek)] + ek


def kisa(adres: str) -> str:
    """Trader adresinin kullanıcıya gösterilen biçimi: sabit takma ad (örn. "Kartal-78"); geçersizse kısa adres."""
    return takma_ad(adres)


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
        self.izinli_id: set[str] = {x.strip() for x in re.split(r"[,\s]+", str(ortam.get("TELEGRAM_IZINLI_ID", ""))) if x.strip()}      # Denetim-8: GERÇEK kipte grup sohbetinde komut verebilecek kullanıcı kimlikleri (from.id); boş = grupta komut yok
        self.komut_kapali = komut_kapali_mi(ortam.get("TELEGRAM_KOMUT", ""))      # G4: tek getUpdates tüketicisi (sunucu); kapalıysa yalnız gönderim (S-22: "kapalı" da)
        self.kayit = kayit
        self.sessiz_utc, self.saat_s = sessiz_utc, saat_s or time.time          # gece (UTC saat aralığı) önemsiz mesajlar sessiz (bildirim sesi yok); alarmlar HER ZAMAN sesli
        self.bastirilan: set[str] = set(BASTIRILAN_TURLER)      # bastırılan mesaj türleri (kayda yazılır, gitmez)
        self._uyari_son: dict[str, float] = {}                 # `uyar` anahtarı -> son gönderim zamanı (düzelince silinir)
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
        self._bekleyen: dict | None = None             # iki adımlı onay: {komut, kod, bitis (s), kim}; bellekte (yeniden başlatmada düşer: komut yeniden gönderilir)
        self.kod_uret: Callable[[], str] = lambda: f"{secrets.randbelow(9000) + 1000}"      # 4 haneli kod (testte enjekte)
        self._gonderim_zamanlari: list[float] = []     # hız sınırı penceresi (son gönderim saatleri)
        self._son_gonderim: dict[str, float] = {}      # tekrar önleme: anahtar -> son gönderim saati
        # G-18: yeniden deneme beklemesi ve gerçek kip emir tamponu yalnız arka planda (motor) ya da açıkça verilince; eşzamanlı yol (test, --kontrol) tek deneme / anında gönderim
        self._yeniden = arka_plan or uyku is not None
        self.uyku = uyku or time.sleep
        self.tampon_sn = 0.0                           # G-18: gerçek kip emir mesajı birleştirme süresi (sn); motor kurar (`canli_telegram_gercek_tampon_sn`)
        self._zamanlayici_fn = zamanlayici if zamanlayici is not None else (_varsayilan_zamanlayici if arka_plan else None)
        self._tampon: list[dict] = []
        self._tampon_bicim: Callable[[list[dict]], str] | None = None
        self._tampon_zaman: Any = None
        self._tampon_kilit = threading.Lock()
        self.guncelleme_isareti: Path | None = None   # K-80: sunucu güncelleme betiğinin yazdığı işaret (ilk satır epoch sn); yoksa/None: pencere yok. Motor kurar
        self.cift_dogrulama_sn = 0.0                  # K-80: >0 ise `dogrula=` verilen durum alarmları bu kadar sonra yeniden sınanır (motor DOGRULAMA_SN kurar)
        self._ertelenen: dict[str, dict] = {}         # K-80: ikinci doğrulama / güncelleme penceresi bekleyen alarmlar (anahtar -> kayıt)
        self._ertele_kilit = threading.Lock()
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

    def uyar(self, anahtar: str, metin: str, onem: str | None = None, dogrula: Callable[[], bool] | None = None) -> bool:
        """Ortak uyarı yardımcısı: aynı `anahtar` en çok `UYARI_ARA_S` (6 saat) bir kez gider; sürerken tekrarlar kayda `telegram_tekrar_atlandi` yazar. Gönderilen uyarı `duzeldi` ile kapatılır.
        `dogrula` (K-80): durum alarmı için koşulu yeniden sınayan çağrı; verilirse ve `cift_dogrulama_sn` > 0 ise gönderim ertelenir, koşul hâlâ geçerliyse gider."""
        simdi = float(self.saat_s())
        son = self._uyari_son.get(anahtar)
        if son is not None and simdi - son < UYARI_ARA_S:
            if self.kayit:
                self.kayit({"olay": "telegram_tekrar_atlandi", "onem": onem or "WARN", "anahtar": anahtar, "pencere_sn": UYARI_ARA_S})
            return False
        self._uyari_son[anahtar] = simdi
        ok = self.gonder(metin, onem, anahtar=anahtar, dogrula=dogrula, _iptal=lambda: self._uyari_son.pop(anahtar, None))
        if not ok:
            self._uyari_son.pop(anahtar, None)                     # gitmedi: 6 saatlik kilit kurulmaz, sonraki çağrıda yeniden denenir
        return ok

    def duzeldi(self, anahtar: str, metin: str) -> bool:
        """`uyar(anahtar)` ile uyarılmış bir sorun düzelince TEK "Düzeldi" mesajı (INFO, sessiz); uyarı hiç verilmediyse ya da zaten kapatıldıysa hiçbir şey gitmez.
        K-80: uyarı henüz GİTMEMİŞ (ikinci doğrulama / güncelleme penceresi bekliyor) ise iptal edilir; "düzeldi" de gitmez."""
        with self._ertele_kilit:
            bekleyen = self._ertelenen.pop(anahtar, None)
        if bekleyen is not None:
            if self.kayit:
                self.kayit({"olay": "tg_ertelenen_iptal", "anahtar": anahtar, "neden": "duzeldi"})
            if bekleyen.get("iptal"):
                bekleyen["iptal"]()
            return False
        if self._uyari_son.pop(anahtar, None) is None:
            return False
        self._son_gonderim.pop(anahtar, None)                      # düzelmiş sorun yeniden olursa 5 dk tekrar penceresi uyarıyı yutmasın
        return self.gonder(metin, "INFO")

    # ------------------------------------------------------------------------------------------ K-80: ikinci doğrulama + güncelleme penceresi
    def guncelleme_kalan_s(self) -> float:
        """Güncelleme işaretinden sonraki `GUNCELLEME_SESSIZ_S` penceresinde kalan saniye (pencere yoksa 0). İşaret yok/okunamıyor/bozuk/gelecekte: 0 (alarm susturulmaz)."""
        if self.guncelleme_isareti is None:
            return 0.0
        try:
            ts = float(Path(self.guncelleme_isareti).read_text(encoding="utf-8").split()[0])
        except (OSError, ValueError, IndexError):
            return 0.0
        gecen = float(self.saat_s()) - ts
        return GUNCELLEME_SESSIZ_S - gecen if 0 <= gecen < GUNCELLEME_SESSIZ_S else 0.0

    def son_guncelleme_metni(self) -> str | None:
        """Bağlam satırı için: 'son güncelleme N dk/sa önce' (işaret yoksa None)."""
        if self.guncelleme_isareti is None:
            return None
        try:
            ts = float(Path(self.guncelleme_isareti).read_text(encoding="utf-8").split()[0])
        except (OSError, ValueError, IndexError):
            return None
        return f"son güncelleme {sure_metni(float(self.saat_s()) - ts)} önce"

    def _ertele(self, anahtar: str, sn: float, kayit: dict) -> bool:
        """Alarmı `sn` sonraya erteler (aynı anahtar bekliyorsa yenisi eklenmez). Zamanlayıcı yoksa False (çağıran kendi yoluna devam eder / düşürür)."""
        if self._zamanlayici_fn is None:
            return False
        with self._ertele_kilit:
            if anahtar in self._ertelenen:
                return True
            kayit.setdefault("ilk_s", float(self.saat_s()))
            self._ertelenen[anahtar] = kayit
        self._zamanlayici_fn(max(sn, 0.0) + 0.5, lambda: self._ertele_bitti(anahtar))
        return True

    def _ertele_bitti(self, anahtar: str) -> None:
        with self._ertele_kilit:
            e = self._ertelenen.pop(anahtar, None)
        if e is None:                                              # düzeldi ile iptal edildi
            return
        try:
            gecerli = True if e.get("dogrula") is None else bool(e["dogrula"]())
        except Exception:                                          # noqa: BLE001 - sınama çökerse alarm kaybolmasın
            gecerli = True
        if not gecerli:
            if self.kayit:
                self.kayit({"olay": "tg_dogrulama_dustu", "anahtar": anahtar, "metin": str(e["metin"])[:120]})
            if e.get("iptal"):
                e["iptal"]()
            return
        metin = e["metin"]
        if not e.get("baglamli"):
            satir = self._baglam_satiri(e["ilk_s"])
            metin = f"{metin}\n{satir}"
            e["baglamli"] = True
        self.gonder(metin, e["onem"], anahtar=e["anahtar"], tur=e.get("tur"), alan=e.get("alan"), dogrula=None, _ic=True, _iptal=e.get("iptal"), _baglamli=True)

    def _baglam_satiri(self, ilk_s: float) -> str:
        """Alarm metnine tek satır bağlam: ne zamandır sürüyor + son güncelleme ne zaman."""
        parca = [f"⏱ başladı: {sure_metni(float(self.saat_s()) - ilk_s)} önce" if float(self.saat_s()) - ilk_s >= 60 else "⏱ yeni başladı"]
        gun = self.son_guncelleme_metni()
        parca.append(gun if gun else "son güncelleme: kayıt yok")
        return " · ".join(parca)

    def gonder(self, metin: str, onem: str | None = None, anahtar: str | None = None, tur: str | None = None, alan: dict | None = None, dogrula: Callable[[], bool] | None = None,
               _ic: bool = False, _iptal: Callable[[], Any] | None = None, _baglamli: bool = False) -> bool:
        """Mesaj gönderir; hata motoru DURDURMAZ (sayılır). Token günlüğe/hata metnine ASLA yazılmaz. `onem`: INFO/WARN/CRIT (yoksa metinden çıkarılır); `anahtar`: tekrar önleme
        anahtarı (yoksa WARN/CRIT için metnin kendisi). Giden mesajın ilk satırı `[CT] <ÖNEM>` olur (kayda/`gonderilen`e düz metin yazılır).
        K-80: (1) `dogrula` verilmiş durum alarmı `cift_dogrulama_sn` sonra koşul yeniden sınanarak gider (+1 bağlam satırı); (2) güncelleme penceresinde (işaret < 15 dk) ÖLÜMCÜL olmayan WARN/CRIT
        pencere sonuna ertelenir (o zaman `dogrula` hâlâ geçerliyse gider; olay türü alarmlar `dogrula`sız gecikmeli gider, kaybolmaz). Gerçekleşmiş olay alarmları (tasfiye vb.) `dogrula` vermez: çift doğrulamaya girmez."""
        if tur is not None and tur in self.bastirilan:             # bastırılan tür: gönderilmez, kayda yazılır (tespit silinmedi)
            if self.kayit:
                self.kayit({"olay": "tg_bastirildi", "tur": tur, "metin": metin[:200]})
                self.kayit({"olay": "tg_mesaj", "tur": tur, "anahtar": anahtar, "seviye": onem or onem_duzeyi(metin), "sessiz": False, "metin": metin, "gonderildi": False, "bastirildi": True, **(alan or {})})
            return False
        seviye = onem or onem_duzeyi(metin)
        k = anahtar if anahtar is not None else metin
        if dogrula is not None and not _ic and self.cift_dogrulama_sn > 0 and seviye != "INFO":
            if self._ertele(k, self.cift_dogrulama_sn, {"metin": metin, "onem": onem, "anahtar": anahtar, "tur": tur, "alan": alan, "dogrula": dogrula, "iptal": _iptal}):
                if self.kayit:
                    self.kayit({"olay": "tg_dogrulama_bekliyor", "anahtar": k, "sn": self.cift_dogrulama_sn})
                return True
        kalan = self.guncelleme_kalan_s() if seviye != "INFO" else 0.0
        if kalan > 0 and not olumcul_mu(metin):
            if self.kayit:
                self.kayit({"olay": "tg_guncelleme_bekletildi", "anahtar": k, "kalan_sn": round(kalan), "metin": metin[:120]})
            if self._ertele(k, kalan, {"metin": metin, "onem": onem, "anahtar": anahtar, "tur": tur, "alan": alan, "dogrula": dogrula, "iptal": _iptal, "baglamli": _baglamli}):
                return True
            return False
        metin = kip_etiketle(metin, self.kip)
        for m in self.maske:
            metin = re.sub(re.escape(m), "[hesap]", metin, flags=re.I)
        self.gonderilen.append(metin)
        if self.kayit:
            self.kayit({"olay": "telegram", "metin": metin[:300], "acik": self.acik})
            self.kayit({"olay": "tg_mesaj", "tur": tur, "anahtar": anahtar, "seviye": onem or onem_duzeyi(metin), "sessiz": self.sessiz_mi(metin), "metin": metin, "gonderildi": bool(self.acik),
                        "bastirildi": False, **(alan or {})})      # mutabakat: TAM metin + yapısal alanlar (adres/coin/yon/pnl/neden); token/chat id yazılmaz (metinde yok, `maskele` kayıtta ayrıca süzer)
        if not self.acik:
            return False
        oge = (metin, onem or onem_duzeyi(metin), anahtar, float(self.saat_s()))
        if self._havuz is not None:
            self._havuz.submit(self._gonder_sync, *oge)
            return True
        return self._gonder_sync(*oge)

    def sessiz_mi(self, metin: str) -> bool:
        if self.sessiz_utc is None or metin.startswith(ONEMLI_ONEKLER):
            return False
        saat = datetime.fromtimestamp(self.saat_s(), timezone.utc).hour
        bas, bit = self.sessiz_utc
        return (bas <= saat < bit) if bas < bit else (saat >= bas or saat < bit)

    def _hiz_bekle(self) -> None:
        """Standart: dakikada en çok `HIZ_LIMITI_DK` mesaj. Doluysa en eski gönderimin 60 sn dolmasına dek beklenir (mesaj kaybolmaz, kuyrukta kalır)."""
        while True:
            simdi = float(self.saat_s())
            self._gonderim_zamanlari = [t for t in self._gonderim_zamanlari if simdi - t < 60.0]
            if len(self._gonderim_zamanlari) < HIZ_LIMITI_DK:
                return
            bekle = self._gonderim_zamanlari[0] + 60.0 - simdi
            if self.kayit:
                self.kayit({"olay": "telegram_hiz_siniri", "bekle_sn": round(max(bekle, 0.0), 1)})
            self.uyku(max(bekle, 0.0))
            self._gonderim_zamanlari.pop(0)             # beklendi: en eski gönderim pencereden çıktı sayılır (sahte saatte de ilerler)

    def _gonder_sync(self, metin: str, onem: str = "INFO", anahtar: str | None = None, kuyruga_s: float | None = None) -> bool:
        """G-18: önemli mesaj (ONEMLI_ONEKLER) gönderilemezse 2/5/15 sn beklemeyle 3 kez daha denenir; 429'da en az `retry_after` (≤ 60 sn) beklenir, önemsiz mesaj da 429'da bir kez
        yeniden denenir. Önemli mesaj eşzamanlı yolda da bekleyerek yeniden denenir (en çok ≈22 sn + HTTP süreleri; motor kilidi altında çağrılmaz: motor gönderimi arka plan havuzunda); önemsiz mesaj eşzamanlı yolda tek deneme. `hata_sayisi` yalnız son başarısızlıkta artar."""
        simdi0 = float(self.saat_s())
        if onem == "INFO" and kuyruga_s is not None and simdi0 - kuyruga_s > INFO_OMUR_S:      # standart: 24 saatten eski INFO atılır
            if self.kayit:
                self.kayit({"olay": "telegram_eski_info_atildi", "yas_sn": round(simdi0 - kuyruga_s)})
            return False
        anahtar = anahtar if anahtar is not None else (metin if onem != "INFO" else None)
        if anahtar is not None:
            son = self._son_gonderim.get(anahtar)
            if son is not None and simdi0 - son < TEKRAR_PENCERE_S:                            # standart: aynı uyarı kısa sürede bir kez
                if self.kayit:
                    self.kayit({"olay": "telegram_tekrar_atlandi", "onem": onem})
                return False
        self._hiz_bekle()
        gidecek = mesaj_kirp(f"{PROJE_ETIKETI} {baslik_sade(metin)}")
        plan = list(YENIDEN_BEKLEME_S) if metin.startswith(ONEMLI_ONEKLER) else []      # önemli mesaj eşzamanlı yolda da yeniden denenir (sağlık/açılış/başlamadı alarmı: kilit altında DEĞİL; motor gönderimi zaten arka plan havuzunda)
        deneme = 0
        while True:
            deneme += 1
            try:
                yanit = self.post(self._url("sendMessage"), {"chat_id": self.chat_id, "text": gidecek, "disable_notification": onem == "INFO" or self.sessiz_mi(metin)})
                if isinstance(yanit, dict) and yanit.get("ok") is False and int(yanit.get("error_code") or 0) == 429:
                    raise CokIstek(_retry_after(yanit))
                self._gonderim_zamanlari.append(float(self.saat_s()))
                if anahtar is not None:
                    self._son_gonderim[anahtar] = float(self.saat_s())
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
            if kimden.get("is_bot", False):
                return False
            if self.kip == "gercek":                            # Denetim-8: gerçek parada gruptaki HER üye /kapat /devam veremez: `TELEGRAM_IZINLI_ID` boşsa komut yok, doluysa yalnız listedeki from.id
                return str(kimden.get("id", "")) in self.izinli_id
            return True                                         # sanal kip: eski davranış (grup üyesi)
        return str(kimden.get("id", "")) == self.chat_id

    def _kod_isle(self, kod: str, tarih: float, kim: str) -> tuple[str | None, str | None]:
        """Onay kodu yanıtı. Döner (yürütülecek komut | None, yanıt metni | None). Süre MESAJ tarihine göre (vardiya gecikmesi kullanıcıyı haksız yere düşürmesin); yanlış kod / süre
        dolması bekleyen onayı iptal eder (hiçbir şey olmaz, bot söyler). Her sonuç denetim kaydına yazılır."""
        b = self._bekleyen
        if b is None:
            return None, "ℹ️ Bekleyen onay yok (süresi dolmuş ya da motor yeniden başlamış olabilir). İşlem yapılmadı; komutu yeniden gönderin."
        self._bekleyen = None
        if tarih > float(b["bitis"]):
            sonuc, yanit = "sure_doldu", f"⏱️ {b['komut']} onay kodunun süresi ({int(ONAY_SURE_S)} sn) doldu. İŞLEM YAPILMADI; gerekirse komutu yeniden gönderin."
        elif kod != b["kod"]:
            sonuc, yanit = "yanlis_kod", f"❌ {b['komut']}: kod yanlış. İŞLEM YAPILMADI; gerekirse komutu yeniden gönderin."
        else:
            sonuc, yanit = "onaylandi", None
        if self.kayit:
            self.kayit({"olay": "telegram_onay_sonuc", "komut": b["komut"], "sonuc": sonuc, "kim": kim, "istenen_kim": b.get("kim")})
        return (b["komut"] if sonuc == "onaylandi" else None), yanit

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
            ham = str(m.get("text", "") or "").strip()
            metin = ESKI_AD.get(komut_adi(ham), komut_adi(ham))          # eski ad → standart ad (/dur→/durdur, /kapat→/hepsini_kapat, /baslat→/devam)
            kod_mu = bool(re.fullmatch(r"\d{4}", ham))
            if not metin.startswith("/") and not kod_mu:
                continue
            if not self.yetkili_mi(m):
                self.yetkisiz_sayisi += 1
                if self.kayit:
                    self.kayit({"olay": "telegram_yetkisiz", "komut": metin[:20], "chat": str((m.get("chat") or {}).get("id", ""))[:3] + "…"})
                continue
            uid = int(u.get("update_id", 0))
            tarih = float(m.get("date", 0) or 0)
            kim = str((m.get("from") or {}).get("id", ""))
            if kod_mu:                                                  # iki adımlı onay: 2. adım (4 haneli kod yanıtı)
                if tarih < self.baslangic_s or uid in self._yanitlanan:
                    continue
                self._yanitlanan.add(uid)
                onaylanan, yanit_m = self._kod_isle(ham, tarih, kim)
                if onaylanan:
                    komutlar.append(onaylanan)
                if yanit_m:
                    yanitlar.append(yanit_m)
                continue
            if metin in YOK_KOMUTLAR or metin in ("/yardim", "/start"):     # yalnız yanıt (motorda iş yok); her update'e bir kez
                if uid not in self._yanitlanan:
                    self._yanitlanan.add(uid)
                    yanitlar.append(msg_yardim() if metin in ("/yardim", "/start") else msg_yok_komut(metin))
                continue
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
                    yanitlar.append(msg_komut_islenmedi(komut_adi(ham), simdi - tarih, once_basladi))      # yalnız yanıt verilir; eski komut ASLA yürütülmez
                continue
            if metin in IKI_ADIMLI:                                     # 1. adım: ne olacağını söyle, kod iste; komut KOD gelene dek yürütülmez
                kod = self.kod_uret()
                self._bekleyen = {"komut": metin, "kod": kod, "bitis": simdi + ONAY_SURE_S, "kim": kim}
                if self.kayit:
                    self.kayit({"olay": "telegram_onay_istendi", "komut": metin, "kim": kim, "sure_sn": int(ONAY_SURE_S)})
                yanitlar.append(msg_onay_iste(metin, kod, self.kip))
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


def sure_metni(sn: float) -> str:
    """Bağlam satırı için süre: '45 sn' / '12 dk' / '3 sa 10 dk'."""
    sn = max(float(sn), 0.0)
    if sn < 90:
        return f"{sn:.0f} sn"
    dk = sn / 60
    if dk < 120:
        return f"{dk:.0f} dk"
    return f"{int(dk // 60)} sa {int(dk % 60)} dk"


def olumcul_mu(metin: str) -> bool:
    """K-80: güncelleme sonrası 15 dk içinde de HEMEN gidecek ölümcül mesaj mı (bot durdu, tasfiye, kayıp sınırı, kapanış eksik, DUR...). 🔴/🛑/💥 başlıklar her zaman."""
    if metin.startswith(OLUMCUL_ONEKLER):
        return True
    norm = metin.replace("İ", "i").replace("I", "ı").lower()
    return any(i in norm for i in OLUMCUL_ISARETLER)


ALARM_BASLIKLARI = ("🔴", "🚨", "🛑", "💥", "⏸️", "▶️", "✅", "ℹ️", "⚠️", "ALARM", "UYARI", "BİLGİ", "TASFİYE", "DUR")


def kip_etiketle(metin: str, kip: str | None) -> str:
    """S-22: `alarm()` biçimli çok satırlı mesajın başlığına kısa kip eklenir: '🚨 ALARM: x (GERÇEK PARA)'. Başlıkta kip zaten varsa dokunulmaz."""
    if not kip:
        return metin
    ilk, ayr, kalan = metin.partition("\n")
    if not kalan or not ilk.startswith(ALARM_BASLIKLARI) or "(sanal" in ilk or "(GERÇEK" in ilk or "[GERÇEK]" in ilk or "[sanal]" in ilk:
        return metin
    return f"{ilk} ({kip_adi(kip)}){ayr}{kalan}"


def msg_bilinmeyen_komut(komut: str) -> str:
    return f"❓ Bilinmeyen komut: {komut[:30]}. Geçerli komutlar: {GECERLI_KOMUT_METNI}"


def msg_komut_islenmedi(komut: str, yas_sn: float, motor_kapaliydi: bool) -> str:
    """G-16 (§5): '📭 /kapat 23 dk önce geldi, motor o sırada kapalıydı; İŞLENMEDİ. Hâlâ istiyorsan yeniden gönder.'"""
    dk = max(0, round(yas_sn / 60))
    neden = "motor o sırada kapalıydı" if motor_kapaliydi else f"{KACIRILAN_PENCERE_S // 60} dk sınırını aştı"
    return f"📭 {komut} {dk} dk önce geldi, {neden}; İŞLENMEDİ. Hâlâ istiyorsan yeniden gönder."


ONAY_ACIKLAMA = {"/durdur": "YENİ girişler ve artırmalar durur; açık pozisyonlar trader'ı izlemeye ve azaltmaya/kapatmaya devam eder.",
                 "/devam": "Elle duraklatma kalkar (başka bir risk engeli sürüyorsa yeni işlemler yine kapalı kalır).",
                 "/hepsini_kapat": "TÜM pozisyonlar reduce-only kapatılır ve motor durur (yeniden açmak sunucudan yapılır)."}


def msg_onay_iste(komut: str, kod: str, kip: str | None = None) -> str:
    kip_s = f" ({kip_adi(kip)})" if kip else ""
    return (f"🔐 {komut} onayı{kip_s}\n{AYRAC}\nNe olacak: {ONAY_ACIKLAMA.get(komut, 'komut uygulanır')}\n"
            f"Onaylamak için {int(ONAY_SURE_S)} sn içinde şu 4 haneli kodu yanıt olarak yazın: {kod}\nVazgeçmek için hiçbir şey yazmayın; yanlış kod ya da süre dolarsa işlem yapılmaz.")


def msg_yok_komut(komut: str) -> str:
    return f"ℹ️ {komut}: CT'de henüz yok. Geçerli komutlar: {GECERLI_KOMUT_METNI}"


def msg_yardim() -> str:
    return ("📖 CT komutları\n" + AYRAC + "\n/durum · anlık durum\n/rapor · günlük raporu hemen gönderir\n"
            "/durdur · yeni girişleri durdurur (açık pozisyonlar kalır) [kod ister; eski adı /dur]\n/devam · duraklatmayı kaldırır [kod ister]\n"
            "/hepsini_kapat · tüm pozisyonları kapatır, motoru durdurur (acil) [kod ister; eski adı /kapat]\n/yardim, /start · bu liste\n"
            "Riskli komutlar iki adımlıdır: bot ne olacağını yazar, 4 haneli kod verir; kodu 120 sn içinde yanıtlayın.\n"
            "Henüz CT'de olmayanlar: /kurulumlar /ders /kademe /kademe_devam /onayla /reddet.\n"
            "⏳ Not: CT şimdilik GitHub Actions vardiya zincirinde çalışıyor: komutlara yarım dakikada bir bakılır, ama vardiyalar arası geçişte "
            "(birkaç dk; zincir koparsa daha uzun) cevap GECİKEBİLİR; gecikirse onay kodunun süresi dolabilir, komutu yeniden gönderin. "
            "Sunucuya taşınınca bu gecikme kalkar.")


REJIM_TR = {"trend_up": "yükseliş", "trend_down": "düşüş", "range": "yatay", "volatile": "dalgalı", "unclear": "belirsiz", "bilinmiyor": "bilinmiyor",
            "Extreme Fear": "aşırı korku", "Fear": "korku", "Neutral": "nötr", "Greed": "açgözlülük", "Extreme Greed": "aşırı açgözlülük"}      # D13: rejim/duygu etiketi → Türkçe (Telegram + pano TEK sözlük)


def rejim_satiri(tablo: list[dict] | None) -> str | None:
    """Haftalık 1g rejim tablosundan tek satır (`rejim_sonuc.topla(...)["rejim_1d"]`): en iyi/en kötü rejim toplam PnL'e göre; "bilinmiyor" ve boş kovalar hariç. Bilinen kova yoksa None (satır atlanır)."""
    bilinen = [r for r in (tablo or []) if isinstance(r, dict) and r.get("etiket") != "bilinmiyor" and int(r.get("n") or 0) >= 1]
    if not bilinen:
        return None
    iyi, kotu = max(bilinen, key=lambda r: float(r["toplam_pnl"])), min(bilinen, key=lambda r: float(r["toplam_pnl"]))
    return (f"🧭 Rejim (7g): en iyi {REJIM_TR.get(str(iyi['etiket']), iyi['etiket'])} 1g {tr_isaretli(float(iyi['toplam_pnl']))} $ (n={int(iyi['n'])}), "
            f"en kötü {REJIM_TR.get(str(kotu['etiket']), kotu['etiket'])} 1g {tr_isaretli(float(kotu['toplam_pnl']))} $ (n={int(kotu['n'])})")


def msg_haftalik(kip: str, kasa: float, oz: float, onceki_oz: float | None, btc: float | None, onceki_btc: float | None, emir: int, slotlar: list[tuple[str, float]],
                 rejim: list[dict] | None = None, acik_poz: int | None = None) -> str:
    """Haftalık özet (Pazar 21:10 TSİ; yalnız rapor): hafta K/Z, BTC kıyası, emir sayısı, slot K/Z'ye göre en iyi/en kötü trader. `onceki_oz` None → ilk özet: başlangıçtan (kasa).
    `rejim` (opsiyonel, 1g rejim satırları): bilinen kova varsa tek satır "🧭 Rejim (7g)" eklenir; None ise eski çıktı aynen kalır."""
    ilk = onceki_oz is None
    fark = oz - (kasa if ilk else onceki_oz)
    satirlar = [f"🗓️ Haftalık özet ({kip_adi(kip)})", AYRAC,                                                 # ilk 3 satır: özsermaye, hafta K/Z, açık pozisyon
                f"💰 Özsermaye: {tr_sayi(oz)} $",
                f"{'📈' if fark >= 0 else '📉'} {'Başlangıçtan beri' if ilk else 'Hafta'}: {tr_isaretli(fark)} $ ({tr_yuzde(fark / kasa)})",
                f"📌 Açık pozisyon: {acik_poz}" if acik_poz is not None else "📌 Açık pozisyon: —"]
    if btc and onceki_btc:
        satirlar.append(f"₿ BTC al-tut: {tr_yuzde(btc / onceki_btc - 1)}" + (f" · fark {tr_yuzde(fark / kasa - (btc / onceki_btc - 1))}" if not ilk else ""))
    else:
        satirlar.append("₿ BTC kıyası: bu hafta için veri yok")
    satirlar.append(f"🧾 Hafta içi {emir} emir")
    if slotlar:
        en_iyi, en_kotu = max(slotlar, key=lambda x: x[1]), min(slotlar, key=lambda x: x[1])
        satirlar += [f"🏆 En iyi trader: {kisa(en_iyi[0])} · {tr_isaretli(en_iyi[1])} $ (slot K/Z)", f"🔻 En kötü trader: {kisa(en_kotu[0])} · {tr_isaretli(en_kotu[1])} $ (slot K/Z)"]
    else:
        satirlar.append("👥 Sahada trader yok")
    rejim_s = rejim_satiri(rejim)
    if rejim_s:
        satirlar.append(rejim_s)
    return "\n".join(satirlar)


def msg_kapat_alindi(kip: str) -> str:
    return f"🛑 /hepsini_kapat alındı ({kip_adi(kip)}): tüm pozisyonlar reduce-only kapatılıyor; bitince ayrı mesaj gelecek."


# ---------------------------------------------------------------------------------------------- mesaj biçimleri (sade Türkçe, emojili)
KIP_ADI = {"sanal": "sanal · deneme parası", "gercek": "GERÇEK PARA"}
NEDEN_TR = {"ilk_gun": "ilk kadro", "bos_slot": "boş yer açıldı", "kor_gevsetildi": "boş yer açıldı (benzerlik kuralı gevşetildi; saha hep dolu)", "kadro_disi": "günlük kadrodan düştü", "r1_elendi": "radarın kopyalanabilirlik (R1) elemesinden düştü", "dusme": "slot değeri düştü (kural)", "hafta_yedege": "haftalık değişim: yedeğe indi (pozisyonlar trader kapatana kadar izlenir)", "hafta_elendi": "haftalık değişim: radar eledi (pozisyonlar kapatıldı)", "hafta_kadro_disi": "haftalık değişim: yeni kadroda yok (pozisyonlar kapatıldı)", "bugun_kadroda_yok": "bugünkü radar kadrosunda yok"}
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
    if tur == "uyarı":
        return f"⚠️ Hafta içi uyarı (çıkış yok, pazar değerlendirilir): {kisa(adres)}\n↳ {aciklama}"
    return f"➖ Trader takipten çıktı: {kisa(adres)}\n↳ Neden: {aciklama}"


DURUM_BUYUK = {"red": "REDDEDİLDİ", "dolmadi": "DOLMADI", "kismi": "KISMEN DOLDU", "belirsiz": "SONUCU BELİRSİZ"}
SONRAKI_ADIM = {"kapat": "Kapanış daha geniş bantla yeniden denenecek; olmazsa kuyruğa alınır ve dakikada bir denenir. Tekrarlarsa: /hepsini_kapat ya da HL web.",
                "azalt": "Azaltma bir sonraki dakikada yeniden denenecek. Tekrarlarsa: /hepsini_kapat ya da HL web.",
                "ac": "Pozisyon açılmadı (yeniden denenmez).", "artir": "Artırma yapılmadı (yeniden denenmez)."}


def fiyat(v: float | None) -> str:
    """Fiyat kademeli ondalık (pano + Telegram ortak): ≥ 1 $ → 2, < 1 $ → 4, < 0,01 $ → 6 (küçük coinlerde "0,08" hiçbir şey söylemez); Türkçe virgül, binlik nokta. Dolar K/Z her zaman 2 ondalık."""
    if v is None:
        return "—"
    a = abs(float(v))
    return tr_sayi(float(v), 2 if a >= 1 or a == 0 else (4 if a >= 0.01 else 6))


fiyat_tr = fiyat                                                       # eski ad (geriye uyum)


def _kip_eki(kip: str) -> str:
    return " (GERÇEK PARA)" if kip == "gercek" else " (sanal)"


def msg_acildi(adres: str, coin: str, yon: str, giris: float, usd: float, stop: float | None, kip: str, trader_px: float | None = None, gecikme_sn: float | None = None) -> str:
    """Pozisyon AÇILDI (2 satır): başlık + 'Giriş (trader · fark) · Tutar · Stop'. Trader adı panodaki gösterimle aynı (`kisa`); coin sade. `trader_px`: trader'ın dolum fiyatı (fark = bizim fiyat / trader fiyatı − 1, mutlak %);
    `gecikme_sn`: yalnız eşik aşıldıysa verilir → '· 45 sn geç' eki."""
    stop_s = fiyat_tr(stop) if stop else "yok"
    kopya = f" (trader {fiyat_tr(trader_px)} · fark %{tr_sayi(abs(giris / trader_px - 1) * 100, 2)})" if trader_px else ""
    gec = f" · {gecikme_sn:.0f} sn geç" if gecikme_sn else ""
    return (f"{'🟢' if yon == 'B' else '🟠'} {coin} {'LONG' if yon == 'B' else 'SHORT'} açıldı · trader {kisa(adres)}{_kip_eki(kip)}\n"
            f"Giriş {fiyat_tr(giris)}{kopya} · Tutar {tr_sayi(usd, 0 if usd >= 100 else 1)} $ · Stop {stop_s}{gec}")


KAPANIS_NEDEN_TR = {"tasfiye": "tasfiye", "felaket_stop": "stop", "tasfiye_koruma_stop": "tasfiye koruması stopu", "borsa_stop": "stop", "borsa_stop_korumasiz": "stopsuz kaldığı için kapatıldı", "tam_kapanis": "trader kapattı",
                    "trader_kapali_senkron": "trader kapattı", "trader_ters_senkron": "trader yön değiştirdi", "gunluk_kapat": "günlük kayıp freni",
                    "sahipsiz_pozisyon": "sahipsiz pozisyon kuralı", "iz_suren_koruma": "iz süren koruma", "dur": "bot durduruldu", "komut": "sen kapattın (/hepsini_kapat)", "inen_24sa": "trader takipten çıktı", "inen_ters": "trader takipten çıktı"}


def kapanis_nedeni_tr(neden: str) -> str:
    """Kapanış nedeni, kullanıcı dilinde: stop / iz süren koruma / trader kapattı; diğer kural kesmeleri 'koruma kuralı'."""
    if neden in KAPANIS_NEDEN_TR:
        return KAPANIS_NEDEN_TR[neden]
    return "koruma kuralı" if neden else "trader kapattı"


def msg_kapandi(adres: str, coin: str, pnl_usd: float, pnl_oran: float | None, neden: str, kip: str, toplam_tutar: float | None = None, artir: int = 0, azalt: int = 0) -> str:
    """Pozisyon KAPANDI: $ ve % sonuç + neden (zararda 🔻, kârda ✅; 🔴 yalnız kritik). Pozisyon artırıldıysa 3. satır: 'Toplam tutar 54,6 $ (2 artırma)'; yüzde hep TOPLAM tutara göre."""
    oran = f" ({tr_yuzde(pnl_oran)})" if pnl_oran is not None else ""
    m = (f"{'🔻' if pnl_usd < 0 else '✅'} {coin} kapandı · trader {kisa(adres)}{_kip_eki(kip)}\n"
         f"{tr_isaretli(pnl_usd)} ${oran} · Neden: {kapanis_nedeni_tr(neden)}")
    if toplam_tutar and (artir or azalt):
        m += f"\nToplam tutar {tr_sayi(toplam_tutar, 0 if toplam_tutar >= 100 else 1)} $ (" + ", ".join(x for x in (f"{artir} artırma" if artir else "", f"{azalt} azaltma" if azalt else "") if x) + ")"
    return m


def msg_kopya_hata(tur: str, coin: str, adres: str, neden: str) -> str:
    """Sessiz bilgi: 'Trader açtı, biz açamadık: <neden>' / 'Trader kapattı, biz kapatamadık: <neden>' (yalnız hata/eksik kopya; kural gereği atlananlar için gönderilmez)."""
    return f"ℹ️ Trader {'açtı, biz açamadık' if tur == 'ac' else 'kapattı, biz kapatamadık'}: {neden}\n{coin} · trader {kisa(adres)}"


BOT_NEDEN_TR = {"komut": "sen /hepsini_kapat ile durdurdun", "zirve_dusus": "özsermaye zirveden çok düştü (zirve düşüş freni)"}


def msg_bot_durdu(neden: str, acik_poz: int, stop_durumu: str, ek: str = "", senden: str = "Yeniden başlatmak için bana haber ver.", son: str | None = None) -> str:
    """Ayrı 🔴 'Bot durdu' mesajı (kritik, sesli; 6 saat tekrar sınırına TAKILMAZ; en çok 5 satır + `[CT]`): neden, açık pozisyon sayısı ve stop durumu.
    `ek`: pozisyonlar tam kapanmadıysa ayrıntı (ör. borsada kalan)."""
    son = son or (f"Pozisyonlar DÜZLEŞMEDİ{ek}; yeni işlem açılmıyor, kapanış yeniden deneniyor." if (ek or acik_poz > 0) else "Tüm pozisyonlar kapandı; yeni işlem açılmıyor.")
    return f"🔴 Bot durdu\nNeden: {BOT_NEDEN_TR.get(neden, sade_ad(neden))}\nAçık pozisyon: {acik_poz} · Stop: {stop_durumu}\n{son}\n{senden}"


def msg_bot_durdu_ikinci(neden: str, dakika: int, acik_poz: int | str, stop_durumu: str) -> str:
    """Bot 20 dk içinde dönmediyse İKİNCİ sesli mesaj; son satır orkestratöre yazma talimatı."""
    return (f"🔴 Bot hâlâ kapalı ({dakika} dk)\nNeden: {BOT_NEDEN_TR.get(neden, sade_ad(neden))}\nAçık pozisyon: {acik_poz} · Stop: {stop_durumu}\n"
            f"Senden: orkestratöre 'CT botu durdu' yaz.")


def msg_duzeldi_kesinti(sure_dk: int, ac: int, kapat: int, gec_isleme: int) -> str:
    """Bot yeniden çalışınca TEK Düzeldi: kesinti süresi + o sürede olanlar (açılış sonrası yetişme sonucu). Kaçan işlem varsa mesaj sesli gider (çağıran onem verir)."""
    ne = []
    if kapat:
        ne.append(f"trader {kapat} pozisyon kapattı, bizde de kapatıldı")
    if ac:
        ne.append(f"trader {ac} pozisyon açtı, bizde de açıldı")
    ozet = "; bu sürede " + " · ".join(ne) if ne else ("; bu sürede kaçan işlem yok" if not gec_isleme else f"; bu sürede {gec_isleme} işlem geriye dönük işlendi")
    return f"✅ Düzeldi: bot yeniden çalışıyor\n{sure_dk} dk kapalı kaldı{ozet}."


def msg_limit_yaklasti(kayip_oran: float, sinir_oran: float, oz: float) -> str:
    """Günlük kayıp limitinin %80'ine gelince (günde bir kez) WARN."""
    return (f"⚠️ Günlük kayıp limitine yaklaşıldı\nBugünkü kayıp %{tr_sayi(kayip_oran * 100, 1)} (limit %{tr_sayi(sinir_oran * 100, 0)}); özsermaye {tr_sayi(oz)} $.\n"
            f"Limite ulaşılırsa yeni pozisyon açılmaz.\n{SENDEN_YOK}")


def msg_emir_gercek_sorun(coin: str, eylem: str, usd: float, durum: str, neden: str = "") -> str:
    """G-18 (§5): gerçek kipte DOLU olmayan emir 🚨 ile başlar (gece de sesli). Örnek:
    '🚨 [GERÇEK] EMİR REDDEDİLDİ — BTC kapat 27,30 $\\nneden: hl_err: …\\nKapanış … yeniden denenecek …'."""
    satirlar = [f"🚨 [GERÇEK] EMİR {DURUM_BUYUK.get(durum, durum.upper())} — {coin} {eylem or 'emir'} {tr_sayi(usd)} $"]
    if neden:
        satirlar.append(f"neden: {sade_ad(neden[:200])}")
    if eylem in SONRAKI_ADIM:
        satirlar.append(SONRAKI_ADIM[eylem])
    return "\n".join(satirlar)


def msg_emir(adres: str, coin: str, yon: str, usd: float, px: float | None, kayma: float | None, durum: str, kip: str, eylem: str = "", neden: str = "") -> str:
    ne = "AL" if yon == "B" else "SAT"
    ok = "🟢" if yon == "B" else "🟠"
    ilk = f"{ok} {coin} {ne}: {tr_sayi(usd, 0 if usd >= 100 else 1)} $ ({kip_adi(kip)})"
    nedeni = f"\n↳ Trader {kisa(adres)} {EYLEM_TR.get(eylem, 'işlem yaptı')}, biz de kopyaladık"
    if durum != "dolu" and kip == "gercek":
        return msg_emir_gercek_sorun(coin, eylem, usd, durum, neden) + f"\n↳ Trader {kisa(adres)} · {ne}"
    if durum != "dolu":
        return f"⚠️ {coin} {ne}: emir tam dolmadı ({durum}) · istenen {tr_sayi(usd, 0 if usd >= 100 else 1)} $ ({kip_adi(kip)}){nedeni}"
    return ilk + nedeni + (f"\n↳ Fiyat {fiyat(px)}" if px else "") + (f" · trader'a göre fark {kayma * 1e4:+.1f} bp" if kayma is not None else "")


def ogrenme_satiri(o: dict | None) -> str | None:
    """Öğrenme etkisi tek satırı (günlük rapor). Hepsi 0/null ise None (satır atlanır). `o`: gunluk_ozet.ogrenme_etki anahtarları."""
    if not o:
        return None
    a, p = int(o.get("filtre_atlanan") or 0), o.get("filtre_karsi_olgu_pnl")
    k, e = int(o.get("ders_kucultulen") or 0), int(o.get("ders_engellenen") or 0)
    parcalar = []
    if a:
        parcalar.append(f"filtre {a} sinyal atladı" + (f" (karşı-olgu {tr_isaretli(float(p))} $)" if p is not None else ""))
    if k:
        parcalar.append(f"ders {k} işlemi küçülttü")
    if e:
        parcalar.append(f"ders {e} işlemi engelledi")
    return "🧠 Öğrenme: " + ", ".join(parcalar) if parcalar else None


def risk_satiri(dur: bool = False, bayraklar: list[str] | None = None) -> str:
    """Günlük rapordaki tek risk satırı: durdu mu / yeni işlem kapalı mı. Etkin bayraklar BAYRAK_TR metniyle."""
    if dur:
        return "🛑 Motor DURDURULDU"
    if bayraklar:
        return "⚠️ Yeni işlemler kapalı: " + " · ".join(BAYRAK_TR.get(b, b) for b in bayraklar)
    return "🛡️ Risk: normal, motor çalışıyor"


def msg_gunluk(kip: str, kasa: float, ozsermaye: float, onceki_oz: float, emir_sayisi: int, saha: int, n: int, acik: list[dict], funding_usd: float | None = None, karsi_olgu: dict[str, list[float]] | None = None, ogrenme: dict | None = None,
               dur: bool = False, bayraklar: list[str] | None = None, saglik: list[str] | None = None, kopya_fark: float | None = None, gecikme_sn: float | None = None,
               artir: int = 0, azalt: int = 0, guncelleme: int | None = None, kucult_satir: str = "") -> str:
    """Günlük rapor (21:00 TSİ, ortak standart; en çok ~12 satır, ayrıntı pano). Sıra: kasa → son 24 saat → emirler/takip → açık pozisyon → risk → (varsa) alınmayan sinyal, öğrenme, sağlık → 'Ayrıntı: pano'.
    `onceki_oz`: önceki özetteki özsermaye (ilk özette kasa). `acik`: {coin, sz, usd, kz_usd}. `karsi_olgu`: alınmayan sinyal özeti. `ogrenme`: öğrenme etkisi (satır yalnız sayı > 0 ise).
    `dur`/`bayraklar`: risk durumu (`risk_satiri`). `saglik`: YALNIZ sorun varsa dolu liste (boşsa satır yok)."""
    fark = ozsermaye - onceki_oz
    satirlar = [f"📋 Günlük rapor ({kip_adi(kip)})", AYRAC,                                                  # ilk 3 satır: özsermaye, günün K/Z'si, açık pozisyon
                f"💰 Özsermaye: {tr_sayi(ozsermaye)} $ (başlangıç {tr_sayi(kasa, 0)} $) · başlangıçtan beri {tr_yuzde(ozsermaye / kasa - 1)}",
                f"{'📈' if fark >= 0 else '📉'} Günün K/Z (son 24 saat): {tr_isaretli(fark)} $ ({tr_yuzde(fark / kasa)})" + (f" · 💸 funding (sanal) {tr_isaretli(funding_usd)} $" if funding_usd is not None else "")]
    if acik:
        en = sorted(acik, key=lambda x: -x["usd"])
        parcalar = [f"{'🟩' if x['kz_usd'] >= 0 else '🔻'} {x['coin']} {tr_isaretli(x['kz_usd'])} $" for x in en[:3]]
        if len(acik) > 3:
            parcalar.append(f"… +{len(acik) - 3} daha")
        satirlar.append(f"📌 Açık pozisyon: {len(acik)} (K/Z: " + " · ".join(parcalar) + ")")
    else:
        satirlar.append("📌 Açık pozisyon yok")
    satirlar.append(f"🧾 Bugün {emir_sayisi} emir" + (f" ({artir} artırma, {azalt} azaltma)" if artir or azalt else "") + f" · 👥 takipte {saha}/{n} trader")
    if kopya_fark is not None or gecikme_sn is not None:
        satirlar.append("🎯 Kopya doğruluğu: " + " · ".join(x for x in (f"ortalama fark %{tr_sayi(kopya_fark * 100, 2)}" if kopya_fark is not None else "", f"ortalama gecikme {gecikme_sn:.0f} sn" if gecikme_sn is not None else "") if x))
    if guncelleme:
        satirlar.append(f"🔄 Bot bugün {guncelleme} kez güncellendi")
    satirlar.append(risk_satiri(dur, bayraklar))
    if kucult_satir:
        satirlar.append(kucult_satir)                                                                       # K-77: küçültülmüş traderlar (tek satır)
    if karsi_olgu:
        kn, kk = sum(int(v[0]) for v in karsi_olgu.values()), sum(v[1] for v in karsi_olgu.values())
        satirlar.append(f"🔍 Alınmayan sinyal (hayali, işlem yok): {kn} kapandı · {tr_isaretli(kk)} $ — " + " · ".join(f"{ATLA_TR.get(ad, ad).replace(' (K‑41)', '')} {int(v[0])}/{tr_isaretli(v[1])}" for ad, v in sorted(karsi_olgu.items(), key=lambda kv: -abs(kv[1][1]))[:3]))
    if (og := ogrenme_satiri(ogrenme)):
        satirlar.append(og)
    if saglik:
        satirlar.append("🩺 Sağlık (bu oturum): " + " · ".join(saglik))
    satirlar.append("Ayrıntı: pano")
    return "\n".join(satirlar)


BAYRAK_TR = {"gunluk_kayip": "🔻 Günlük kayıp freni: bugün yeni işlem yok", "mutabakat": "🧮 Mutabakat farkı: yeni işlem kapalı", "elle_dur": "⏸️ Yeni işlem duraklatıldı (/devam ile açılır)",
             "fren": "🧯 Patlama freni: bir trader'dan yeni açılış beklemede", "kasa_siniri": "🔒 Kasa sınırı aşıldı: yeni işlem kapalı",
             "belirsiz": "❓ Sonucu belirsiz emir borsadan sorgulanıyor: yeni işlem kapalı", "stop_korumasiz": "🛑 Borsa stopu kurulamadığı için pozisyon kapatıldı: yeni işlem geçici kapalı"}


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
        satirlar += [msg_emir_gercek_sorun(e["coin"], e.get("eylem", ""), e["usd"], e["durum"], e.get("neden", "")).splitlines()[0] + (f" · {sade_ad(e['neden'][:120])}" if e.get("neden") else "")
                     for e in sorunlu[:1]]
        if len(sorunlu) > 1:
            satirlar[-1] += f" (+{len(sorunlu) - 1} sorunlu emir daha)"
    satirlar.append(f"🧾 {'Son birkaç saniyede' if dakika < 1 else f'Son {dakika:.0f} dakikada'} {len(emirler)} emir ({kip_adi(kip)})")
    sirali_g = sorted(gruplar.items(), key=lambda kv: -sum(x["usd"] for x in kv[1]))
    yer = 5 - len(satirlar)                                              # `[CT]` satırıyla en çok 6 satır: sığmayan gruplar tek "… ve N daha" satırında sayılır
    fazla = len(sirali_g) - (yer - 1) if len(sirali_g) > yer else 0
    for (adres, coin, yon, eylem), liste in sirali_g[:yer - 1 if fazla else len(sirali_g)]:
        toplam = sum(x["usd"] for x in liste)
        eksik = sum(1 for x in liste if x["durum"] != "dolu")
        satirlar.append(f"{'🟢 AL' if yon == 'B' else '🟠 SAT'} {coin}: {tr_sayi(toplam, 0)} $" + (f" ({len(liste)} emir)" if len(liste) > 1 else "")
                        + f" · {kisa(adres)} {EYLEM_TR.get(eylem, 'işlem yaptı')}" + (f" · ⚠️ {eksik} tanesi tam dolmadı" if eksik else ""))
    if fazla:
        satirlar.append(f"… ve {fazla} işlem grubu daha")
    return "\n".join(satirlar)


TSI = timezone(timedelta(hours=3))
# S-13: atlanan sinyal etiketlerinin TEK kaynağı (Telegram + pano). `min_emir_atlandi` eşiği `radar_min_emir_usd` (11 $) ile aynı; test bunu denetler.
ATLA_TR = {"gec_acilis": "geç görülen açılış", "spot_atlandi": "spot coin", "hip3_atlandi": "HIP-3 coin", "ters_netlesme": "ters netleşme (K‑41)", "ara_dolum_siniri": "ara dolum sınırı (ilk 2 sonrası)", "trader_hesap_yok": "trader hesabı okunamadı",
           "hesap_yok": "trader hesap değeri kullanılamadı", "slot_tavani": "slot tavanı", "marj_yok": "marj yok", "coin_tavani": "coin tavanı", "min_nosyonel": "çok küçük emir",
           "min_emir_atlandi": "çok küçük (< 11 $)", "bant_ici": "toplu emir bekliyor (fark küçük)", "inen_trader": "ayrılan trader (yeni alım yok)", "ders_emekli": "ders: trader emekli (yeni alım yok)", "ml_filtre_atla": "ML filtresi (düşük puan)", "rejim_ters": "piyasa yönüne ters", "haber_ters": "haber akışı ters", "duygu_ters": "piyasa duygusu ters", "hesap_kucuk": "trader hesabı küçük", "kaldirac_cok_yuksek": "trader kaldıracı çok yüksek", "iz_suren_koruma": "iz süren koruma", "patlama_freni": "patlama freni", "dur": "motor durdu",
           "gunluk_kayip": "günlük kayıp freni", "mutabakat": "mutabakat farkı", "elle_dur": "elle duraklatma", "kasa_siniri": "kasa sınırı", "belirsiz": "belirsiz emir bekleniyor", "stop_korumasiz": "stopsuz pozisyon kapatıldı (geçici)",
           "kapanis_eksik": "kapanış eksik", "kaldirac_dusuk": "azami kaldıraç düşük (< 5x)", "kaldirac_bilinmiyor": "azami kaldıraç okunamadı", "mark_eski": "fiyat verisi eski",
           "hl_deger": "HL hesap değeri geçersiz",
           "binance_eslesme_yok": "Binance'te karşılığı yok", "binance_eslesme_dogrulanmadi": "Binance eşlemesi doğrulanmadı", "binance_islem_yok": "Binance'te işlem yok",
           "binance_min_nosyonel": "Binance min. emir değeri altı", "binance_erisim_yok": "Binance erişimi yok"}      # K-81: yalnız Binance kâğıt süreci üretir
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


def drift_satiri(drift: dict[str, float]) -> str:
    """Saatlik özet için TEK kopya sapması satırı (bilgi; ayrı mesaj yok): '📐 Kopya sapması: 4 coin, en büyük ETH %411'. Boşsa ''."""
    if not drift:
        return ""
    coin, oran = max(drift.items(), key=lambda kv: (kv[1], kv[0]))
    return f"📐 Kopya sapması: {len(drift)} coin, en büyük {coin} %{round(oran * 100)} (yalnız bilgi)"


def kucult_satiri(olaylar: list[dict]) -> str:
    """K-77: özet penceresinde boyutu küçülen/geri dönen traderlar için TEK satır (ayrı mesaj yok): '🔽 Zarar küçültme: Kartal-78 ½ (5 kapanış, −3,20 $) · Vaşak-12 geri ×1'. Olay yoksa ''.
    Aynı trader birden çok kez değiştiyse son hâli. Seviye: 1 = ½, 2 = en küçük, 0 = geri ×1."""
    son: dict[str, dict] = {}
    for e in olaylar or []:
        son[e["adres"]] = e
    parca = []
    for adres, e in son.items():
        ad = {0: "geri ×1", 1: "½", 2: "en küçük"}.get(int(e["yeni"]), "?")
        parca.append(f"{kisa(adres)} {ad}" + (f" ({e['n']} kapanış, {tr_isaretli(float(e['net']))} $)" if int(e["yeni"]) else ""))
    return ("🔽 Zarar küçültme: " + " · ".join(parca[:3]) + (f" … +{len(parca) - 3}" if len(parca) > 3 else "")) if parca else ""


STOP_KAPANISLARI = frozenset({"felaket_stop", "borsa_stop", "borsa_stop_korumasiz", "tasfiye_koruma_stop", "iz_suren_koruma", "tasfiye"})      # K-79: "stopla kapanan" satırı (kendi korumamız / borsa stopu / tasfiye); anlık ALARM'ları ayrıca gider
ISLEM_SATIR_AZAMI = 4                                                                                                                            # özet satırında en çok bu kadar kalem; fazlası "… +N"


def _kalemler(parcalar: list[str], azami: int = ISLEM_SATIR_AZAMI) -> str:
    return " · ".join(parcalar[:azami]) + (f" · … +{len(parcalar) - azami}" if len(parcalar) > azami else "")


def _yon_tr(yon: str) -> str:
    return "long" if yon == "B" else "short"


def net_kz(emirler: list[dict]) -> float:
    """K-79: özetin net K/Z'si = penceredeki TAM kapanan pozisyonların net toplamı. Pozisyon neti = pozisyonun tüm dolumlarının gerçekleşen K/Z'si − ücretleri (giriş/artırma ücreti dahil; `hesap.dolum_net`);
    pano KAPANAN `net` ve 'kapandı' mesajıyla AYNI tanım (kısmi azaltmalar pozisyon sonunda zaten içindedir; çift sayılmaz)."""
    return sum(float(e["kz"]) for e in emirler if e.get("kapandi") and e.get("kz") is not None)


def msg_sanal_saatlik(bas_ms: int, bit_ms: int, sure_dk: float, emirler: list[dict], atlanan: dict[str, int], kasa_bilgi: tuple[float, float, float] | None = None,
                      atla_islem: int | None = None, atla_adres: dict[str, dict[str, int]] | None = None, drift_satir: str = "", kucult_satir: str = "", kip: str = "sanal") -> str:
    """K-79: işlem partisi TEK saatlik özet (sanal VE gerçek kip; açıldı/kapandı/artırma/azaltma/stop kapanışı ayrı mesaj OLARAK GİTMEZ, satır olur). Emir yoksa '' (mesaj gönderilmez).
    Satırlar (en çok 5): başlık (emir sayısı + tür + kip + net K/Z) · [⚠️ tam dolmayan] · 🟢 Açılan · ✅/🔻 Kapanan · 🛑 Stopla kapanan · ↕️ Artırılan/azaltılan · 💰 Kasa · 🔽 küçültme.
    `emirler` satırı: {adres, coin, yon, usd, durum, eylem [, kapandi, kz (pozisyon neti), neden_kod]}. `atlanan`/`atla_*`/`drift_satir` imzada kalır, mesaja GİRMEZ (kayıt/pano)."""
    if not emirler:
        return ""
    sure = f"{int(sure_dk // 60)} saat" if sure_dk >= 60 and sure_dk % 60 == 0 else f"{sure_dk:.0f} dk"
    say = {k: sum(1 for e in emirler if e.get("eylem") == k) for k in ("ac", "artir", "azalt", "kapat")}
    ad = {"ac": "açılış", "artir": "artırma", "azalt": "azaltma", "kapat": "kapanış"}
    tur = ", ".join(f"{say[k]} {ad[k]}" for k in ("ac", "artir", "azalt", "kapat") if say[k])
    kapananlar = [e for e in emirler if e.get("kapandi")]
    net_s = f" · net {tr_isaretli(net_kz(emirler))} $" if kapananlar else ""
    baslik = f"🧾 Son {sure}: {len(emirler)} emir" + (f" ({tur})" if tur else "") + ("" if kip == "gercek" else " · sanal") + (" · GERÇEK PARA" if kip == "gercek" else "") + net_s
    eksik = sum(1 for e in emirler if e.get("durum") != "dolu")
    uyari = f"⚠️ {eksik} emir tam dolmadı" if eksik else ""
    acilanlar: dict[tuple, float] = {}
    for e in emirler:
        if e.get("eylem") == "ac":
            k = (e.get("coin", "?"), e.get("yon", "B"))
            acilanlar[k] = acilanlar.get(k, 0.0) + float(e.get("usd") or 0.0)
    a_satir = ("🟢 Açılan: " + _kalemler([f"{c} {_yon_tr(y)} {tr_sayi(u, 0 if u >= 100 else 1)} $" for (c, y), u in acilanlar.items()])) if acilanlar else ""

    def kalem(e: dict, neden: bool = False) -> str:
        kz = e.get("kz")
        return f"{e.get('coin', '?')} {tr_isaretli(float(kz)) + ' $' if kz is not None else 'kapandı'}" + (f" ({kapanis_nedeni_tr(str(e.get('neden_kod') or ''))})" if neden else "")
    normal = [e for e in kapananlar if str(e.get("neden_kod") or "") not in STOP_KAPANISLARI]
    stoplu = [e for e in kapananlar if str(e.get("neden_kod") or "") in STOP_KAPANISLARI]
    k_satir = (f"{'🔻' if sum(float(e.get('kz') or 0) for e in normal) < 0 else '✅'} Kapanan: " + _kalemler([kalem(e) for e in normal])) if normal else ""
    s_satir = ("🛑 Stopla kapanan: " + _kalemler([kalem(e, True) for e in stoplu])) if stoplu else ""
    ara = [f"{e.get('coin', '?')} {'artırıldı' if e['eylem'] == 'artir' else 'azaltıldı'}" for e in emirler if e.get("eylem") in ("artir", "azalt")]
    r_satir = ("↕️ " + _kalemler(ara)) if ara else ""
    kasa = ""
    if kasa_bilgi is not None and kasa_bilgi[2] > 0:
        oz, gun_basi, kasa_tut = kasa_bilgi
        gun = oz - gun_basi
        kasa = f"💰 Kasa: {tr_sayi(oz)} $ · bugün {'🟢' if gun >= 0 else '🔻'} {tr_isaretli(gun)} $ ({_yuzde1(gun / kasa_tut)})"
    satirlar = [x for x in (baslik, uyari, a_satir, k_satir, s_satir, r_satir, kasa, kucult_satir) if x]
    # `[CT]` satırıyla en çok 6 satır → gövde en çok 5. Sıkışırsa sırayla: artırma/azaltma kalemleri düşer (sayılar başlıkta) · tam dolmayan uyarısı başlığa katılır · küçültme satırı düşer (kayıt/pano/günlük raporda var)
    if len(satirlar) > 5 and r_satir:
        satirlar.remove(r_satir)
    if len(satirlar) > 5 and uyari:
        satirlar.remove(uyari)
        satirlar[0] += f" · ⚠️ {eksik} tam dolmadı"
    if len(satirlar) > 5 and kucult_satir:
        satirlar.remove(kucult_satir)
    return "\n".join(satirlar)


def msg_sanal_saatlik_bos(bas_ms: int, bit_ms: int, sure_dk: float, atlanan: dict[str, int], kasa_bilgi: tuple[float, float, float] | None = None,
                          atla_islem: int | None = None, atla_adres: dict[str, dict[str, int]] | None = None, drift_satir: str = "", kucult_satir: str = "") -> str:
    """SANAL kip: pencerede emir YOK ama sistem canlı (`canli_telegram_sanal_bos_mesaj`). Tek kısa satır grubu; emir sayısı 0."""
    sure = f"{int(sure_dk // 60)} saat" if sure_dk >= 60 and sure_dk % 60 == 0 else f"{sure_dk:.0f} dk"
    satirlar = [f"🧾 Son {sure} ({_tsi_saat(bas_ms)}–{_tsi_saat(bit_ms)} TSİ): emir yok · sistem çalışıyor"]
    satirlar += atlanan_satirlari(atlanan, atla_islem, atla_adres)
    if drift_satir:
        satirlar.append(drift_satir)
    if kucult_satir:
        satirlar.append(kucult_satir)
    if kasa_bilgi is not None and kasa_bilgi[2] > 0:
        oz, gun_basi, kasa = kasa_bilgi
        gun, top = oz - gun_basi, oz - kasa
        isaret = lambda x: "🟢" if x >= 0 else "🔻"        # noqa: E731
        satirlar.append(f"💰 Kasa: {tr_sayi(oz)} $ · bugün {isaret(gun)} {tr_isaretli(gun)} $ ({_yuzde1(gun / kasa)}) · başlangıçtan {isaret(top)} {tr_isaretli(top)} $ ({_yuzde1(top / kasa)})")
    return "\n".join(satirlar)


def msg_filtre_hata(sayi: int) -> str:
    """Sanal açılış filtresi tekrarlayan hata uyarısı (başına gonder() "[CT] " ekler)."""
    return (f"⚠️ Sanal filtre 1 saatte {sayi} kez hata verdi\n"
            "Bazı yeni alımlar filtre kontrolü yapılamadan geçti.\n"
            "Alımlar filtresiz sürüyor, hata kaydediliyor.\n"
            "Senden bir şey gerekmiyor.")


def sade_ad(ad: str) -> str:
    """Kod adını okunur yapar: 'ajan_suresi' → 'ajan suresi' (mesajda alt çizgili kod adı kalmaz)."""
    return re.sub(r"[A-Za-z]+(?:_[A-Za-z]+)+", lambda m: m.group(0).replace("_", " "), str(ad))


SENDEN_YOK = "Senden bir şey gerekmiyor."


def alarm(baslik: str, govde: str, ikon: str = "🚨", senden: str | None = SENDEN_YOK) -> str:
    """Sorun mesajı: ikon + başlık (ne oldu), sade açıklama (ne yapılıyor), son satır 'senden bir şey gerekiyor mu' (`senden`: None → eklenmez; çağıran kendi eylem satırını gövdeye yazmıştır).
    Geri tırnak ve kod adları ayıklanır. Her zaman sesli (`ONEMLI_ONEKLER`) ya da WARN; en çok 4 satır (+ `[CT]` etiketi)."""
    metin = f"{ikon} {baslik}\n{govde}".replace("`", "")
    return metin + (f"\n{senden}" if senden else "")


def duzeldi_metni(baslik: str, govde: str) -> str:
    """Tek 'Düzeldi' mesajı (INFO, sessiz): '✅ Düzeldi: <başlık>' + gövde."""
    return f"✅ Düzeldi: {baslik}\n{govde}"
