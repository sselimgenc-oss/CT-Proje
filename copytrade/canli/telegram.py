"""Telegram bildirimi + komutlar (Bot API doğrudan; görev T4 §1). Token/chat YALNIZ ortamdan (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`); yoksa kanal KAPALI (mesajlar yalnız kayda yazılır, motor çökmez).

`post(url, json) -> dict` enjekte edilir (testte sahte). K‑37: komut yalnız `chat.id == chat_id` VE `from.id == chat_id` (özel sohbet) ise kabul edilir; yetkisiz komut kayda alınır; motor başlangıcından ÖNCE tarihli mesajlar yok sayılır (eski /dur yeniden tetiklenmez); `offset` motor.json'da kalıcıdır. Komutlar: `/dur` (yeni giriş/artırma durur; çıkış serbest), `/devam` (= `/baslat`; duraklatmayı kaldırır), `/kapat` (tüm pozisyonları kapat, motoru durdur) ve `/durum`. Mesajlar kısa, adres kısaltılır (ilk 8 karakter).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
import re
import time
from datetime import timedelta
from typing import Any, Callable

ONEMLI_ONEKLER = ("ALARM", "DUR", "TASFİYE", "🚨", "🛑", "💥")          # her zaman sesli
KOMUTLAR = ("/dur", "/devam", "/baslat", "/kapat", "/durum")
KACIRILAN_PENCERE_S = 15 * 60          # vardiya başlangıcından önceki bu süre içinde gelip düşürülen komuta "işlenmedi" yanıtı (komut ÇALIŞTIRILMAZ)


def kisa(adres: str) -> str:
    return adres[:8] + "…" if len(adres) > 8 else adres


def _urllib_post(url: str, yuk: dict) -> dict:
    """`requests` kurulu değilse yedek yol (yalnız standart kütüphane); HTTP hatasında istisna atar."""
    import json
    import urllib.request
    istek = urllib.request.Request(url, data=json.dumps(yuk).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(istek, timeout=25) as r:
        return json.loads(r.read().decode("utf-8"))


def varsayilan_post(url: str, yuk: dict) -> dict:
    try:
        import requests
    except ImportError:
        return _urllib_post(url, yuk)
    r = requests.post(url, json=yuk, timeout=25)
    r.raise_for_status()
    return r.json()


class Telegram:
    def __init__(self, token: str | None = None, chat_id: str | None = None, post: Callable[[str, dict], dict] | None = None, ortam: dict | None = None,
                 kayit: Callable[[dict], None] | None = None, arka_plan: bool = False, baslangic_s: float | None = None,
                 sessiz_utc: tuple[int, int] | None = None, saat_s: Callable[[], float] | None = None) -> None:
        ortam = os.environ if ortam is None else ortam
        self.token = (token if token is not None else ortam.get("TELEGRAM_BOT_TOKEN", "")).strip()
        self.chat_id = str(chat_id if chat_id is not None else ortam.get("TELEGRAM_CHAT_ID", "")).strip()
        self.post = post or varsayilan_post
        self.komut_kapali = str(ortam.get("TELEGRAM_KOMUT", "")).strip().lower() == "kapali"      # G4: tek getUpdates tüketicisi (sunucu); kapalıysa yalnız gönderim
        self.kayit = kayit
        self.sessiz_utc, self.saat_s = sessiz_utc, saat_s or time.time          # gece (UTC saat aralığı) önemsiz mesajlar sessiz (bildirim sesi yok); alarmlar HER ZAMAN sesli
        self.offset = 0
        self.baslangic_s = float(time.time() if baslangic_s is None else baslangic_s)       # bundan önce tarihli mesajlar yok sayılır
        self.yetkisiz_sayisi = 0
        self._yanitlanan: set[int] = set()             # "vardiya arasında geldi" yanıtı verilen update_id'ler (her mesaja bir kez)
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

    def sessiz_mi(self, metin: str) -> bool:
        if self.sessiz_utc is None or metin.startswith(ONEMLI_ONEKLER):
            return False
        saat = datetime.fromtimestamp(self.saat_s(), timezone.utc).hour
        bas, bit = self.sessiz_utc
        return (bas <= saat < bit) if bas < bit else (saat >= bas or saat < bit)

    def _gonder_sync(self, metin: str) -> bool:
        try:
            self.post(self._url("sendMessage"), {"chat_id": self.chat_id, "text": metin[:4000], "disable_notification": self.sessiz_mi(metin)})
            return True
        except Exception as hata:                      # noqa: BLE001 - ağ/HTTP hatası; ayrıntı (URL'de token var) yazılmaz
            self.hata_sayisi += 1
            if self.kayit:
                self.kayit({"olay": "telegram_hata", "tur": type(hata).__name__})
            return False

    def komutlari_al(self) -> list[str]:
        """Yeni komutları (`KOMUTLAR`) döner; yalnız `chat_id`'den gelenler; offset ilerler."""
        if not self.acik or self.komut_kapali:
            return []
        try:
            yanit = self.post(self._url("getUpdates"), {"offset": self.offset, "timeout": 0, "allowed_updates": ["message"]})
        except Exception as hata:                      # noqa: BLE001
            self.hata_sayisi += 1
            if self.kayit:
                self.kayit({"olay": "telegram_hata", "tur": type(hata).__name__})
            return []
        komutlar: list[str] = []
        kacirilan: list[str] = []
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
                uid = int(u.get("update_id", 0))
                if metin in KOMUTLAR and float(m.get("date", 0) or 0) >= self.baslangic_s - KACIRILAN_PENCERE_S and uid not in self._yanitlanan:
                    self._yanitlanan.add(uid)
                    kacirilan.append(metin)                # yalnız yanıt verilir; eski komut ASLA yürütülmez
                continue
            if metin in KOMUTLAR:
                komutlar.append(metin)
        if kacirilan:
            self.gonder(alarm("Komut işlenmedi", f"{', '.join(dict.fromkeys(kacirilan))} komutu vardiya arasında geldi, işlenmedi.\nTekrar gönder.", "📭"))
        return komutlar


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


def msg_emir(adres: str, coin: str, yon: str, usd: float, px: float | None, kayma: float | None, durum: str, kip: str, eylem: str = "") -> str:
    ne = "AL" if yon == "B" else "SAT"
    ok = "🟢" if yon == "B" else "🔴"
    ilk = f"{ok} {coin} {ne}: {tr_sayi(usd, 0 if usd >= 100 else 1)} $ ({kip_adi(kip)})"
    nedeni = f"\n↳ Trader {kisa(adres)} {EYLEM_TR.get(eylem, 'işlem yaptı')}, biz de kopyaladık"
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
        return msg_emir(e["adres"], e["coin"], e["yon"], e["usd"], e.get("px"), e.get("kayma"), e["durum"], kip, e.get("eylem", ""))
    gruplar: dict[tuple, list[dict]] = {}
    for e in emirler:
        gruplar.setdefault((e["adres"], e["coin"], e["yon"], e.get("eylem", "")), []).append(e)
    satirlar = [f"🧾 Son {dakika:.0f} dakikada {len(emirler)} emir ({kip_adi(kip)})"]
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
ATLA_TR = {"gec_acilis": "geç görülen açılış", "spot_atlandi": "spot coin", "hip3_atlandi": "HIP-3 coin", "ters_netlesme": "ters netleşme", "trader_hesap_yok": "trader hesabı okunamadı",
           "slot_tavani": "slot tavanı", "marj_yok": "marj yok", "coin_tavani": "coin tavanı", "min_nosyonel": "çok küçük emir"}


def _yuzde1(oran: float) -> str:
    """0.0125 → '+%1,3'; −0.012 → '−%1,2'; yuvarlanınca sıfır olan → '%0,0' (işaretsiz)."""
    y = round(oran * 100, 1)
    return "%0,0" if y == 0 else ("+" if y > 0 else "−") + "%" + tr_sayi(abs(y), 1)


def _tsi_saat(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, TSI).strftime("%H:%M")


def msg_sanal_saatlik(bas_ms: int, bit_ms: int, sure_dk: float, emirler: list[dict], atlanan: dict[str, int], kasa_bilgi: tuple[float, float, float] | None = None) -> str:
    """SANAL kip saatlik özet (tek mesaj). `emirler`: {adres, coin, yon, usd ($, sanal 1.000 $ kopya ölçeği), durum, eylem, kayma (oran)}; `atlanan`: neden -> adet. Emir yoksa '' (mesaj gönderilmez). `kasa_bilgi` = (özsermaye $, gün başı özsermaye $, başlangıç kasası $) — pano ile aynı tanım: yüzdeler kasaya göre."""
    if not emirler:
        return ""
    sure = f"{int(sure_dk // 60)} saat" if sure_dk >= 60 and sure_dk % 60 == 0 else f"{sure_dk:.0f} dk"
    say = {k: sum(1 for e in emirler if e.get("eylem") == k) for k in ("ac", "artir", "azalt", "kapat")}
    en = max(emirler, key=lambda e: e["usd"])
    satirlar = [f"🧾 Son {sure} ({_tsi_saat(bas_ms)}–{_tsi_saat(bit_ms)} TSİ): {len(emirler)} emir · sanal",
                f"➕ açılış {say['ac']} · ⬆️ artırma {say['artir']} · ⬇️ azaltma {say['azalt']} · ✖️ kapanış {say['kapat']}",
                f"🏆 En büyük: {tr_sayi(en['usd'], 0 if en['usd'] >= 100 else 1)} $ ({en['coin']}, {'AL' if en['yon'] == 'B' else 'SAT'}) · {kisa(en['adres'])}"]
    if atlanan:
        top = sum(atlanan.values())
        neden, adet = max(atlanan.items(), key=lambda kv: (kv[1], kv[0]))
        satirlar.append(f"⏭️ Atlanan sinyal: {top} (en çok: {ATLA_TR.get(neden, neden)} {adet})")
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


def msg_sanal_saatlik_bos(bas_ms: int, bit_ms: int, sure_dk: float, atlanan: dict[str, int], kasa_bilgi: tuple[float, float, float] | None = None) -> str:
    """SANAL kip: pencerede emir YOK ama sistem canlı (`canli_telegram_sanal_bos_mesaj`). Tek kısa satır grubu; emir sayısı 0."""
    sure = f"{int(sure_dk // 60)} saat" if sure_dk >= 60 and sure_dk % 60 == 0 else f"{sure_dk:.0f} dk"
    satirlar = [f"🧾 Son {sure} ({_tsi_saat(bas_ms)}–{_tsi_saat(bit_ms)} TSİ): emir yok · sistem çalışıyor"]
    if atlanan:
        satirlar.append(f"⏭️ Atlanan sinyal: {sum(atlanan.values())}")
    if kasa_bilgi is not None and kasa_bilgi[2] > 0:
        oz, gun_basi, kasa = kasa_bilgi
        gun, top = oz - gun_basi, oz - kasa
        isaret = lambda x: "🟢" if x >= 0 else "🔴"        # noqa: E731
        satirlar.append(f"💰 Kasa: {tr_sayi(oz)} $ · bugün {isaret(gun)} {tr_isaretli(gun)} $ ({_yuzde1(gun / kasa)}) · başlangıçtan {isaret(top)} {tr_isaretli(top)} $ ({_yuzde1(top / kasa)})")
    return "\n".join(satirlar)


def alarm(baslik: str, govde: str, ikon: str = "🚨") -> str:
    """Sorun mesajı: ikon + başlık, ayraç, sade açıklama. Her zaman sesli (`ONEMLI_ONEKLER`)."""
    return f"{ikon} {baslik}\n{AYRAC}\n{govde}"
