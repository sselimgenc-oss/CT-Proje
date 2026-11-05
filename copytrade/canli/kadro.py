"""Saha yöneticisi (docs/RADAR_V1.md §5; K‑27, K‑33; görev T4 §0–§1). SAF durum makinesi: kadro.json'u okuyup saha kararlarını üretir; saat, slot özsermayesi ve son işlem zamanı dışarıdan verilir.

Saha = en çok N üye (`boyut.saha_sayisi`); kadro N'den küçükse (K‑33) boş slot NAKİT kalır (slot tutarı yine kasa / N; başka trader'a dağıtılmaz) ve kadro büyüdükçe giriş kuralıyla dolar.
Kararlar `Karar` olarak döner (giriş / düş / değiştir / inen_kapat) — uygulamayı motor yapar (slot aç, pozisyon kapat, Telegram, kayıt).
- İlk gün (saha hiç kurulmadıysa): sıra 1…N sahaya (korelasyon kuralı uygulanır); günlük değişiklik sınırına SAYILMAZ.
- Giriş: slot boşsa İlk 11'in (katman `ilk11`) sahada olmayan, beklemede olmayan en iyi sıralısı; günde ≤ `canli_gunde_degisiklik` saha girişi/değişikliği.
- Değiştirme (histerezis): aday sıra ≤ N **ve** üye sıra > İlk 11 sınırı **ve** aday formu ≥ üye formu + `canli_histerezis_puan` → üye "daha_iyisi_geldi" (sonuç dışı) ile iner.
- Düşme — anında: slot düşüşü ≥ `canli_slot_dusus_oran`, kaldıraç > `radar_max_kaldirac` (R1/4); günlük (yeni `kosu_ms`): sıra 2 gün üst üste > `canli_sira_dus`, kadroda yok / sıra > `canli_kadro_disi_sira`
  (1 gün), `canli_islem_yok_saat` saat işlem yok (sonuç dışı). SONUÇLA düşen (slot, sıra, kadro dışı, kaldıraç/R1) `canli_bekleme_gun` gün sahaya dönemez; sonuç dışı düşenin bekleme cezası yok.
- Korelasyon: sahada birbirine ≥ `canli_kor_esik` benzeyen (bağlı bileşen) en çok `canli_kor_max` kişi; ihlal eden aday atlanır (`kor_kirpildi`).
- Kadro bayat / yok (`kosu_ms` > `canli_kadro_eski_saat` saat): yeni giriş yok, düşme kuralları çalışır (günlük sıra kuralları kadro verisi gerektirdiğinden yeni kosu_ms olmadan işlemez).
- Sahadan inen: yeni açılış durur, trader'ın kapanışları izlenir, `canli_inen_saat` sonra kalan pozisyon kapatılır (`inen_kapat`).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from copytrade import boyut
from copytrade.kurallar import load_rules

SAAT = 3_600_000
GUN = 24 * SAAT


@dataclass
class Karar:
    tur: str                  # giris | dus | inen_kapat
    adres: str
    neden: str
    sonuc: bool = False       # dus: sonuçla mı (14 gün bekleme)
    yerine: str | None = None  # değiştirme: yerine giren
    kor_kirpildi: list[str] | None = None


def kadro_taze_mi(kadro: dict | None, simdi_ms: int, rules: dict) -> tuple[bool, str]:
    if not kadro or "kosu_ms" not in kadro or not isinstance(kadro.get("satirlar"), list):
        return False, "kadro_yok"
    yas = simdi_ms - int(kadro.get("kosu_ms", 0))
    if yas > float(rules["canli_kadro_eski_saat"]) * SAAT:
        return False, "kadro_bayat"
    return True, ""


def kor_bilesen_boyutu(adresler: list[str], kor: dict | None, esik: float) -> int:
    """`adresler` arasında korelasyon ≥ eşik kenarlarıyla bağlı en büyük bileşenin kişi sayısı (kadro.json `korelasyon` İlk 11 içindir; olmayan çift ilişkisiz sayılır)."""
    if not kor or len(adresler) < 2:
        return min(1, len(adresler))
    idx = {a: i for i, a in enumerate(kor.get("adresler", []))}
    m = kor.get("matris", [])
    ana = {a: a for a in adresler}

    def bul(x: str) -> str:
        while ana[x] != x:
            ana[x] = ana[ana[x]]
            x = ana[x]
        return x

    for i, a in enumerate(adresler):
        for b in adresler[i + 1:]:
            if a in idx and b in idx:
                r = m[idx[a]][idx[b]]
                if r is not None and r >= esik:
                    ana[bul(a)] = bul(b)
    sayi: dict[str, int] = {}
    for a in adresler:
        sayi[bul(a)] = sayi.get(bul(a), 0) + 1
    return max(sayi.values())


class Saha:
    def __init__(self, rules: dict | None = None, kasa_usd: float | None = None, durum: dict | None = None) -> None:
        self.rules = rules or load_rules()
        self.kasa = float(self.rules["canli_kasa_usd"] if kasa_usd is None else kasa_usd)
        self.n = boyut.saha_sayisi(self.kasa, self.rules)
        self.slot = boyut.slot_usd(self.kasa, self.rules)
        d = durum or {}
        self.uyeler: dict[str, dict] = dict(d.get("uyeler", {}))
        self.inen: dict[str, dict] = dict(d.get("inen", {}))
        self.bekleme: dict[str, int] = {k: int(v) for k, v in (d.get("bekleme") or {}).items()}
        self.degisiklik: dict = dict(d.get("degisiklik") or {"gun": None, "adet": 0})
        self.son_kosu_ms: int = int(d.get("son_kosu_ms", 0))
        self.kurulu: bool = bool(d.get("kurulu", False))
        self.alarm_gunu: str | None = d.get("alarm_gunu")

    # ------------------------------------------------------------------ yardımcılar
    def _gun(self, ms: int) -> str:
        from copytrade.canli.risk import gun
        return gun(ms)

    def _degisiklik_hakki(self, simdi_ms: int, ilk_gun: bool) -> bool:
        if ilk_gun:
            return True
        if self.degisiklik.get("gun") != self._gun(simdi_ms):
            self.degisiklik = {"gun": self._gun(simdi_ms), "adet": 0}
        return self.degisiklik["adet"] < int(self.rules["canli_gunde_degisiklik"])

    def _say(self, simdi_ms: int, ilk_gun: bool) -> None:
        if not ilk_gun:
            self.degisiklik["adet"] += 1

    def _bekliyor(self, adres: str, simdi_ms: int) -> bool:
        return self.bekleme.get(adres, 0) > simdi_ms

    def _ekle(self, adres: str, satir: dict, simdi_ms: int) -> None:
        self.uyeler[adres] = {"giris_ms": simdi_ms, "giris_sira": satir.get("sira"), "sira_ust": 0, "son_islem_ms": None}

    def _dus(self, adres: str, neden: str, sonuc: bool, simdi_ms: int, kararlar: list[Karar]) -> None:
        self.uyeler.pop(adres, None)
        self.inen[adres] = {"inis_ms": simdi_ms, "neden": neden}
        if sonuc:
            self.bekleme[adres] = simdi_ms + int(self.rules["canli_bekleme_gun"]) * GUN
        kararlar.append(Karar("dus", adres, neden, sonuc))

    def islem_gordu(self, adres: str, zaman_ms: int) -> None:
        u = self.uyeler.get(adres)
        if u is not None:
            u["son_islem_ms"] = max(int(u.get("son_islem_ms") or 0), int(zaman_ms))

    # ------------------------------------------------------------------ anlık kontroller (dakikalık)
    def anlik(self, simdi_ms: int, slot_ozsermaye: Callable[[str], float | None], kadro: dict | None = None) -> list[Karar]:
        """Slot düşüşü ≥ eşik ya da kaldıraç ihlali → anında düş (sonuçla). `kadro` verilirse kaldıraç (R1/4) kadro satırından okunur."""
        kararlar: list[Karar] = []
        satir = {s["adres"]: s for s in (kadro or {}).get("satirlar", [])}
        for adres in list(self.uyeler):
            ozs = slot_ozsermaye(adres)
            if ozs is not None and ozs <= self.slot * (1 - float(self.rules["canli_slot_dusus_oran"])) + 1e-9:
                self._dus(adres, "slot_dusus", True, simdi_ms, kararlar)
            elif (satir.get(adres) or {}).get("max_kaldirac") is not None and float(satir[adres]["max_kaldirac"]) > float(self.rules["radar_max_kaldirac"]):
                self._dus(adres, "kaldirac_ihlali", True, simdi_ms, kararlar)
        return kararlar

    def inenleri_kapat(self, simdi_ms: int) -> list[Karar]:
        """Sahadan ineli `canli_inen_saat` saati geçenlerin kalan pozisyonu kapatılır; kayıt silinir (motor pozisyonları kapatır)."""
        kararlar = []
        for adres, i in list(self.inen.items()):
            if simdi_ms - int(i["inis_ms"]) >= float(self.rules["canli_inen_saat"]) * SAAT:
                kararlar.append(Karar("inen_kapat", adres, i.get("neden", "")))
                del self.inen[adres]
        return kararlar

    # ------------------------------------------------------------------ günlük / giriş
    def degerlendir(self, kadro: dict | None, simdi_ms: int) -> tuple[list[Karar], str]:
        """Kadro okumasında çağrılır. Döner (kararlar, durum): durum `ok` | `kadro_yok` | `kadro_bayat`. Yeni `kosu_ms` ise günlük kurallar çalışır; giriş/değiştirme her çağrıda (boş slot varsa) denenir."""
        taze, neden = kadro_taze_mi(kadro, simdi_ms, self.rules)
        kararlar: list[Karar] = []
        if not taze:
            return kararlar, neden
        satirlar = {s["adres"]: s for s in kadro["satirlar"]}
        yeni_gun = int(kadro["kosu_ms"]) != self.son_kosu_ms
        if yeni_gun:
            self._gunluk_dusme(satirlar, simdi_ms, kararlar)
            self.son_kosu_ms = int(kadro["kosu_ms"])
        ilk_gun = not self.kurulu
        self._doldur(kadro, satirlar, simdi_ms, ilk_gun, kararlar)
        self._degistir(kadro, satirlar, simdi_ms, kararlar)
        if self.uyeler:
            self.kurulu = True
        return kararlar, "ok"

    def _gunluk_dusme(self, satirlar: dict[str, dict], simdi_ms: int, kararlar: list[Karar]) -> None:
        for adres in list(self.uyeler):
            u, s = self.uyeler[adres], satirlar.get(adres)
            if s is None or int(s["sira"]) > int(self.rules["canli_kadro_disi_sira"]):
                self._dus(adres, "kadro_disi", True, simdi_ms, kararlar)
                continue
            if int(s["sira"]) > int(self.rules["canli_sira_dus"]):
                u["sira_ust"] = int(u.get("sira_ust", 0)) + 1
                if u["sira_ust"] >= int(self.rules["canli_sira_dus_gun"]):
                    self._dus(adres, "sira", True, simdi_ms, kararlar)
                    continue
            else:
                u["sira_ust"] = 0
            temel = max(int(u.get("son_islem_ms") or 0), int(u.get("giris_ms") or 0))
            if simdi_ms - temel >= float(self.rules["canli_islem_yok_saat"]) * SAAT:
                self._dus(adres, "islem_yok", False, simdi_ms, kararlar)

    def _uygun_adaylar(self, kadro: dict, simdi_ms: int, hedef_sira: int) -> list[dict]:
        return [s for s in sorted(kadro["satirlar"], key=lambda x: int(x["sira"]))
                if int(s["sira"]) <= hedef_sira and s["adres"] not in self.uyeler and s["adres"] not in self.inen and not self._bekliyor(s["adres"], simdi_ms)]

    def _kor_uygun(self, adres: str, kadro: dict, ek: list[str] | None = None) -> bool:
        kume = [*self.uyeler, adres] if ek is None else [*ek, adres]
        return kor_bilesen_boyutu(kume, kadro.get("korelasyon"), float(self.rules["canli_kor_esik"])) <= int(self.rules["canli_kor_max"])

    def _doldur(self, kadro: dict, satirlar: dict[str, dict], simdi_ms: int, ilk_gun: bool, kararlar: list[Karar]) -> None:
        ilk = int(self.rules["radar_kadro_ilk"])
        hedef_sira = self.n if ilk_gun else ilk
        for s in self._uygun_adaylar(kadro, simdi_ms, hedef_sira):
            if len(self.uyeler) >= self.n:
                break
            if not self._degisiklik_hakki(simdi_ms, ilk_gun):
                break
            if not self._kor_uygun(s["adres"], kadro):
                kararlar.append(Karar("giris_atlandi", s["adres"], "kor_kirpildi", kor_kirpildi=list(self.uyeler)))
                continue
            self._ekle(s["adres"], s, simdi_ms)
            self._say(simdi_ms, ilk_gun)
            kararlar.append(Karar("giris", s["adres"], "ilk_gun" if ilk_gun else "bos_slot"))

    def _degistir(self, kadro: dict, satirlar: dict[str, dict], simdi_ms: int, kararlar: list[Karar]) -> None:
        if len(self.uyeler) < self.n:
            return
        ilk, puan = int(self.rules["radar_kadro_ilk"]), float(self.rules["canli_histerezis_puan"])
        for adres in sorted(self.uyeler, key=lambda a: -int((satirlar.get(a) or {"sira": 10**6})["sira"])):
            uye = satirlar.get(adres)
            if uye is None or int(uye["sira"]) <= ilk:
                continue
            for aday in self._uygun_adaylar(kadro, simdi_ms, self.n):
                if float(aday["form"]) < float(uye["form"]) + puan - 1e-9:
                    continue
                if not self._degisiklik_hakki(simdi_ms, False):
                    return
                kalan = [a for a in self.uyeler if a != adres]
                if not self._kor_uygun(aday["adres"], kadro, kalan):
                    kararlar.append(Karar("giris_atlandi", aday["adres"], "kor_kirpildi", kor_kirpildi=kalan))
                    continue
                self._dus(adres, "daha_iyisi_geldi", False, simdi_ms, kararlar)
                self._ekle(aday["adres"], aday, simdi_ms)
                self._say(simdi_ms, False)
                kararlar.append(Karar("giris", aday["adres"], "degistirme", yerine=adres))
                break

    # ------------------------------------------------------------------ kalıcılık
    def to_json(self) -> dict[str, Any]:
        return {"uyeler": self.uyeler, "inen": self.inen, "bekleme": self.bekleme, "degisiklik": self.degisiklik, "son_kosu_ms": self.son_kosu_ms, "kurulu": self.kurulu, "alarm_gunu": self.alarm_gunu}
