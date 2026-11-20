"""CT ortak öğrenme adaptörü (kullanıcı kararı 19.11): kopyalanan trader = "kurulum"; her kapanan kopya pozisyonu bir `Aday` kaydı olur; dersler yalnız RİSK AZALTIR.

Paket: `copytrade/ortak_ogrenme/` (kopya, değiştirilmez). Bu dosya projeye özgü çeviridir (paket README: "çeviri yalnız adaptörde").

KURALLAR (değişmez; testle korunur):
- Kimlik: tam cüzdan adresi hiçbir yeni dosyaya yazılmaz (repo ve `canli-durum` dalı herkese açık). Kurulum adı = `T_` + sha256(adres) ilk 6 hex (`takma_ad`); alias → adres eşlemesi SAKLANMAZ.
- Ders yalnız ŞUNLARI yapabilir: (a) "emekli": o trader'ın YENİ açılış/artırması kopyalanmaz (kapanış/azaltma HİÇ engellenmez), sonraki haftalık kadro değişimine dek;
  (b) slot çarpanı [0.5, 1.0] (yalnız açılış/artırma boyutu). Boyut ARTIRILAMAZ, trader eklenemez, radar eşiğine dokunulamaz, sert sınırlara (gerçek tavan, günlük kayıp, kaldıraç) dokunulmaz.
- Değerlendirme en çok saatte bir; hata motoru durdurmaz (kayıt + yutulur). Yalnız sanal kip (`kip == "sanal"`) ve `ogrenme_aktif: true` iken çalışır.
- R birimi: 1R = pozisyonun en büyük nosyonelinin `ogrenme_r_birim_oran` kadarı ($, kopya ölçeği). R = net K/Z (ücret dahil) / 1R.
- Ders anlamı (paket): `alive` = dersin koşuluna uyan işlemler doğumdan sonra toplamda KAYBETTİRDİ (etki > 0, shrink'li). Yalnız bu dersler uygulanır; `retired` olanlar uygulanmaz.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from copytrade.ortak_ogrenme import drift, ders, karne, notlar
from copytrade.ortak_ogrenme.kayit import Aday, aday_to_dict, oku_jsonl

from . import telegram as tg

AGIRLIK_ALT, AGIRLIK_UST = 0.5, 1.0          # sert sınır: yapılandırma ne derse desin çarpan bu aralıkta kalır
VARSAYILAN = {
    "ogrenme_aktif": True, "ogrenme_r_birim_oran": 0.02, "ogrenme_shrink_n": 10, "ogrenme_min_n": 3,
    "ogrenme_agirlik_etki_r": 1.0, "ogrenme_emekli_etki_r": 3.0, "ogrenme_fren_esik_r": 10.0, "ogrenme_geri_alma_r": 3.0, "ogrenme_degerlendirme_dk": 60,
    "ogrenme_filtre_aktif": True, "ogrenme_filtre_min_n": 50, "ogrenme_filtre_egitim_gun": 7, "ogrenme_filtre_log_saat": 6, "ogrenme_drift_telegram": False,
    "sanal_ogrenme_drift_eylem": True,
}
BEKLEYEN_OMUR_MS = 15 * 60_000               # karar anı özellikleri: açılış dolumu bu süre içinde gelmezse atılır


def takma_ad(adres: str) -> str:
    """Kararlı takma ad: `T_` + sha256(küçük harf adres) ilk 6 hex. Yalnız harf/rakam/`_` (paket ders etiketi sözlüğüne uyar); `0x` içermez; geri çevrilemez."""
    return "T_" + hashlib.sha256(str(adres).strip().lower().encode("utf-8")).hexdigest()[:6]


def _atomik_yaz(yol: Path, veri: Any) -> None:
    yol.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(yol.parent), prefix=".ogr-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(veri, fh, sort_keys=True, indent=1)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, yol)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _oku(yol: Path) -> dict:
    try:
        d = json.loads(yol.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _ekle_satir(yol: Path, kayit: dict) -> None:
    yol.parent.mkdir(parents=True, exist_ok=True)
    with yol.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(kayit, ensure_ascii=False, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def _utc(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


def kaldirac_kademesi(k: float) -> str:
    return "k_dusuk" if k <= 3 else "k_orta" if k <= 5 else "k_yuksek"


def sure_kademesi(saat: float) -> str:
    return "sure_kisa" if saat < 1 else "sure_orta" if saat < 24 else "sure_uzun"


class Ogrenme:
    """Motorun tek temas noktası. `agirlik` / `acilis_engeli` karar yolunda ÇAĞRILIR; tümü hata durumunda "etki yok" (1.0 / None) döner."""

    def __init__(self, rules: dict, dizin: Path, kip: str, saat_ms: Callable[[], int], kayit: Callable[[dict], Any] | None = None,
                 gonder: Callable[[str], Any] | None = None) -> None:
        self.k = {**VARSAYILAN, **{a: rules[a] for a in VARSAYILAN if a in rules}}
        self.dizin, self.saat_ms, self.kayit, self.gonder = Path(dizin), saat_ms, kayit, gonder
        self.aktif = bool(self.k["ogrenme_aktif"]) and kip == "sanal"
        self.adaylar_yolu, self.notlar_yolu = self.dizin / "adaylar.jsonl", self.dizin / "notlar.jsonl"
        self.ders_yolu, self.iz_yolu, self.uyg_yolu = self.dizin / "ders.json", self.dizin / "izler.json", self.dizin / "uygulama.json"
        self.iz: dict[str, dict] = {}
        self.filtre_dizin = self.dizin / "filtre"
        self.karne_yolu = self.dizin / "karne.json"
        self.bekleyen: dict[str, dict] = {}                       # "alias|coin" -> {"ms", "ozellik"}: karar anı özellikleri (eğitim satırı açılış dolumunda bunları alır)
        self._modeller: dict[str, tuple[dict, datetime] | None] = {}     # alias -> (paket, son_kullanma) | None
        self._filtre_log: dict[str, int] = {}
        self._pano: list[dict] = []
        self.uyg: dict[str, Any] = {"emekli": {}, "carpan": {}, "emekli_kullanilan": [], "geri_alinan": {}, "son_ms": 0, "egit_zorla": False, "drift_uyari": {}, "drift_carpan": {}}
        if self.aktif:
            self.iz = _oku(self.iz_yolu)
            self.uyg.update({a: v for a, v in _oku(self.uyg_yolu).items() if a in self.uyg})
            self._pano = list(_oku(self.karne_yolu).get("pano") or [])

    # ------------------------------------------------------------------ olay kaydı (hata yutulur)
    def _kayit(self, **alanlar: Any) -> None:
        try:
            if self.kayit:
                self.kayit(alanlar)
        except Exception:                                         # noqa: BLE001
            pass

    # ------------------------------------------------------------------ 1) kapanan kopya işlemini Aday kaydet
    def dolum(self, o: dict) -> None:
        """`Hesap.dinleyici`: her dolum. Pozisyon tamamen kapanınca Aday + not yazılır. Hata kaydı bozmaz, motoru durdurmaz."""
        if not self.aktif:
            return
        try:
            self._dolum(o)
        except Exception as hata:                                 # noqa: BLE001
            self._kayit(olay="ogrenme_hata", asama="dolum", tur=type(hata).__name__, mesaj=str(hata)[:120])

    def _dolum(self, o: dict) -> None:
        alias, coin = takma_ad(o["adres"]), str(o["coin"])
        anahtar = f"{alias}|{coin}"
        yon_dolum = o["yon"]
        iz = self.iz.get(anahtar)
        izsiz = iz is None or bool(o.get("yeni"))
        if izsiz:
            long = yon_dolum == "B" if o.get("yeni") else yon_dolum == "A"          # açılış B = long; iz yoksa kapanan dolumun tersi
            iz = {"acilis_ms": int(o["acilis_ms"] if not o.get("yeni") else o["ms"]), "yon": "long" if long else "short", "kaldirac": float(o["kaldirac"]),
                  "maks_usd": 0.0, "pnl": 0.0, "ucret": 0.0}
            if o.get("yeni"):                                                         # karar anı özellikleri (motor `filtre_kontrol` ile bıraktı); yoksa yalnız zaman özellikleri
                bk = self.bekleyen.pop(anahtar, None)
                iz["ozellik"] = dict(bk["ozellik"]) if bk and int(o["ms"]) - int(bk["ms"]) <= BEKLEYEN_OMUR_MS else self._zaman_ozellikleri(int(o["ms"]))
        iz["maks_usd"] = max(float(iz["maks_usd"]), abs(float(o["poz_sz"])) * float(o["px"]), float(o["sz"]) * float(o["px"]) if (izsiz and not o.get("yeni")) else 0.0)      # iz yoksa (yeniden başlatma) kapanan dolumun nosyoneli alt sınır
        iz["pnl"] += float(o["pnl"])
        iz["ucret"] += float(o["ucret"])
        if not o.get("kapandi"):
            self.iz[anahtar] = iz
        else:
            self.iz.pop(anahtar, None)
            self._kapanisi_yaz(alias, coin, iz, int(o["ms"]))
        _atomik_yaz(self.iz_yolu, self.iz)

    def _kapanisi_yaz(self, alias: str, coin: str, iz: dict, kapanis_ms: int) -> None:
        net = float(iz["pnl"]) - float(iz["ucret"])
        birim = max(float(iz["maks_usd"]) * float(self.k["ogrenme_r_birim_oran"]), 1e-9)
        sure_saat = max(0.0, (kapanis_ms - int(iz["acilis_ms"])) / 3_600_000.0)
        acilis = _utc(int(iz["acilis_ms"]))
        aday = Aday(
            id=f"{alias}:{coin}:{int(iz['acilis_ms'])}", proje="CT", kurulum=alias, enstruman=f"{coin}/USD", varlik_sinifi="kripto", yon=iz["yon"], ts=acilis,
            alindi=True, r=round(net / birim, 6), seans="weekend" if acilis.weekday() >= 5 else "open", rejim=None,
            ozellikler={"kaldirac": float(iz["kaldirac"]), **{a: float(v) for a, v in (iz.get("ozellik") or {}).items()}},          # YALNIZ karar anında bilinenler (filtre eğitimi)
            etiketler=(f"coin:{coin}", f"yon:{iz['yon']}", f"kaldirac:{kaldirac_kademesi(float(iz['kaldirac']))}", f"sure:{sure_kademesi(sure_saat)}"),
            cikis={"exit_reason": "kopya_kapanis", "bars_held": round(sure_saat, 2), "maks_nosyonel_usd": round(float(iz["maks_usd"]), 4), "net_usd": round(net, 6), "ucret_usd": round(float(iz["ucret"]), 6)},
        )
        _ekle_satir(self.adaylar_yolu, aday_to_dict(aday))
        etiketler, metin = notlar.not_yaz(aday)
        _ekle_satir(self.notlar_yolu, {"id": aday.id, "note_date": _utc(kapanis_ms).strftime("%Y-%m-%d"), "tags": etiketler, "metin": metin})
        self._kayit(olay="ogrenme_aday", kurulum=alias, coin=coin, r=aday.r, net_usd=round(net, 4))

    # ------------------------------------------------------------------ 2) karar yolu: yalnız risk AZALTAN sorgular
    def acilis_engeli(self, adres: str) -> str | None:
        """Yeni açılış/artırma için engel nedeni ("ders_emekli") ya da None. Kapanış/azaltma için ÇAĞRILMAZ."""
        try:
            return "ders_emekli" if self.aktif and takma_ad(adres) in self.uyg["emekli"] else None
        except Exception:                                         # noqa: BLE001
            return None

    def agirlik(self, adres: str) -> float:
        """Slot çarpanı ∈ [0.5, 1.0] (yalnız açılış/artırma boyutuna uygulanır). Hata/bilinmeyen → 1.0. Asla 1.0'ı aşmaz."""
        try:
            if not self.aktif:
                return 1.0
            alias = takma_ad(adres)
            c = self.uyg["carpan"].get(alias)
            w = 1.0 if c is None else float(c["deger"])
            d = self.uyg["drift_carpan"].get(alias)                   # K-73: drift eylemi çarpanı (ders çarpanıyla min alınır)
            if d is not None:
                w = min(w, float(d["deger"]))
            return max(AGIRLIK_ALT, min(AGIRLIK_UST, w))
        except Exception:                                         # noqa: BLE001
            return 1.0

    def agirlik_alias(self, alias: str) -> float:
        c = self.uyg["carpan"].get(alias)
        d = self.uyg["drift_carpan"].get(alias)
        w = min(1.0 if c is None else float(c["deger"]), 1.0 if d is None else float(d["deger"]))
        return max(AGIRLIK_ALT, min(AGIRLIK_UST, w))

    def hafta_degisti(self) -> None:
        """Haftalık kadro değişimi: "emekli" kayıtları biter (bu dersler bir daha emekli yaptırmaz; yalnız çarpan olarak sürer)."""
        if not self.aktif:
            return
        try:
            bitenler = dict(self.uyg["emekli"])
            for a, e in bitenler.items():
                self.uyg["emekli_kullanilan"] = sorted(set(self.uyg["emekli_kullanilan"]) | set(e.get("kimlikler", [])))
                self._kayit(olay="ders_geri_alindi", kurulum=a, neden="hafta_degisimi", tur="emekli")
            self.uyg["emekli"] = {}
            self.uyg["drift_carpan"] = {}                         # K-73: drift çarpanı da haftalık kadro değişiminde biter
            self.uyg["egit_zorla"] = True                         # haftalık kadro değişimi: filtre bir sonraki saatlik adımda yeniden eğitilir
            _atomik_yaz(self.uyg_yolu, self.uyg)
        except Exception as hata:                                 # noqa: BLE001
            self._kayit(olay="ogrenme_hata", asama="hafta", tur=type(hata).__name__, mesaj=str(hata)[:120])

    # ------------------------------------------------------------------ 3) saatlik değerlendirme (sarılı)
    def _sar(self, asama: str, f: Callable[[], Any]) -> None:
        try:
            f()
        except Exception as hata:                                 # noqa: BLE001
            self._kayit(olay="ogrenme_hata", asama=asama, tur=type(hata).__name__, mesaj=str(hata)[:120])

    def adim(self, simdi: int | None = None) -> None:
        """Dakikalık döngüden çağrılır; en çok `ogrenme_degerlendirme_dk` dakikada bir çalışır. Hiçbir hata dışarı çıkmaz; her alt adım ayrı sarılıdır."""
        if not self.aktif:
            return
        try:
            simdi = int(simdi if simdi is not None else self.saat_ms())
            if simdi - int(self.uyg.get("son_ms", 0)) < float(self.k["ogrenme_degerlendirme_dk"]) * 60_000:
                return
            self.uyg["son_ms"] = simdi
        except Exception as hata:                                 # noqa: BLE001
            self._kayit(olay="ogrenme_hata", asama="degerlendirme", tur=type(hata).__name__, mesaj=str(hata)[:120])
            return
        self._sar("degerlendirme", lambda: self.degerlendir(simdi))
        self._sar("filtre_egit", lambda: self.filtre_egit(simdi))        # her alt adım ayrı sarılı: biri patlarsa diğerleri yine çalışır
        self._sar("karne", lambda: self.karne_guncelle(simdi))
        self._sar("durum", lambda: _atomik_yaz(self.uyg_yolu, self.uyg))

    def degerlendir(self, simdi: int) -> dict[str, list]:
        k = self.k
        adaylar = oku_jsonl(self.adaylar_yolu)
        nlar = []
        if self.notlar_yolu.exists():
            for s in self.notlar_yolu.read_text(encoding="utf-8").splitlines():
                if s.strip():
                    n = json.loads(s)
                    nlar.append({"note_date": n["note_date"], "tags": n["tags"]})
        gun = _utc(simdi).strftime("%Y-%m-%d")
        ders.gece_adimi(adaylar, nlar, self.ders_yolu, gun, shrink_n=int(k["ogrenme_shrink_n"]))
        durum = _oku(self.ders_yolu)
        as_of = _utc(simdi)
        olaylar: dict[str, list] = {"uygulandi": [], "geri_alindi": []}

        # (1) GERİ ALMA önce: uygulanmış dersler uygulamadan sonraki işlemlerde zarar ettirdiyse (paket `fren_durumu`) geri al
        gruplar = {**{a: ("emekli", e) for a, e in self.uyg["emekli"].items()}, **{a: ("carpan", c) for a, c in self.uyg["carpan"].items() if a not in self.uyg["emekli"]}}
        raporlar: dict[str, dict] = {}
        for alias, (_tur, e) in gruplar.items():
            kim = [x for x in e.get("kimlikler", [])]
            ms = int(e.get("ms", simdi))
            raporlar[alias] = ders.fren_durumu(adaylar, kim, _utc(ms), as_of, esik_r=float(k["ogrenme_fren_esik_r"]), geri_alma_r=float(k["ogrenme_geri_alma_r"]))
        fren = sum(r["toplam_etki"] for r in raporlar.values()) <= -float(k["ogrenme_fren_esik_r"]) and bool(raporlar)
        for alias, r in raporlar.items():
            if fren or r["geri_al"]:
                for tur in ("emekli", "carpan"):
                    e = self.uyg[tur].pop(alias, None)
                    if e is not None:
                        olaylar["geri_alindi"].append(alias)
                        for kid in (e.get("kimlikler", []) if fren else r["geri_al"]):
                            self.uyg["geri_alinan"][kid] = simdi
                        self._kayit(olay="ders_geri_alindi", kurulum=alias, neden="fren" if fren else "geri_alma", tur=tur, toplam_etki=round(r["toplam_etki"], 4), kimlikler=e.get("kimlikler", []))

        # (2) hedefler: yalnız canlı (alive) + yeterli n + geri alınmamış dersler
        hedef: dict[str, dict] = {}
        for kid, st in durum.items():
            if not isinstance(st, dict) or st.get("status") != "alive" or int(st.get("n", 0)) < int(k["ogrenme_min_n"]) or kid in self.uyg["geri_alinan"]:
                continue
            kod, _, alias = kid.partition(":")
            if kod not in notlar.LESSON_CODES or not alias.startswith("T_"):
                continue
            h = hedef.setdefault(alias, {"etki": 0.0, "etki_emekli": 0.0, "kimlikler": []})
            h["etki"] += float(st.get("effect") or 0.0)
            if kid not in self.uyg["emekli_kullanilan"]:
                h["etki_emekli"] += float(st.get("effect") or 0.0)
            h["kimlikler"].append(kid)
        emekli_esik = float(k["ogrenme_emekli_etki_r"])
        yeni_emekli: dict[str, dict] = {}
        yeni_carpan: dict[str, dict] = {}
        for alias, h in hedef.items():
            if h["etki_emekli"] >= emekli_esik:
                yeni_emekli[alias] = {"etki": round(h["etki_emekli"], 4), "kimlikler": sorted(h["kimlikler"])}
            if h["etki"] >= float(k["ogrenme_agirlik_etki_r"]):
                oran = min(1.0, h["etki"] / emekli_esik) if emekli_esik > 0 else 1.0
                yeni_carpan[alias] = {"deger": round(max(AGIRLIK_ALT, min(AGIRLIK_UST, 1.0 - (AGIRLIK_UST - AGIRLIK_ALT) * oran)), 4), "etki": round(h["etki"], 4), "kimlikler": sorted(h["kimlikler"])}

        # (3) uygula / kaldır (değişim varsa olay; aynı durum tekrar olay üretmez)
        for tur, yeni in (("emekli", yeni_emekli), ("carpan", yeni_carpan)):
            for alias in list(self.uyg[tur]):
                if alias not in yeni:                                     # ders artık geçerli değil (retired / n düştü): bırak
                    e = self.uyg[tur].pop(alias)
                    olaylar["geri_alindi"].append(alias)
                    self._kayit(olay="ders_geri_alindi", kurulum=alias, neden="ders_gecersiz", tur=tur, kimlikler=e.get("kimlikler", []))
            for alias, v in yeni.items():
                eski = self.uyg[tur].get(alias)
                if eski is None or eski.get("deger") != v.get("deger") or eski.get("kimlikler") != v["kimlikler"]:
                    self.uyg[tur][alias] = {**v, "ms": int(eski["ms"]) if eski else simdi}          # geri alma ölçümü ilk uygulama anından
                    olaylar["uygulandi"].append(alias)
                    self._kayit(olay="ders_uygulandi", kurulum=alias, tur=tur, carpan=v.get("deger"), etki=v["etki"], kimlikler=v["kimlikler"])
        _atomik_yaz(self.uyg_yolu, self.uyg)
        if olaylar["uygulandi"] and self.gonder:
            satirlar = []
            for alias in sorted(set(olaylar["uygulandi"])):
                if alias in self.uyg["emekli"]:
                    satirlar.append(f"{alias}: yeni açılışlar bu haftanın kadro değişimine dek kopyalanmıyor (kapanışlar sürer)")
                elif alias in self.uyg["carpan"]:
                    satirlar.append(f"{alias}: yeni açılış boyutu x{self.uyg['carpan'][alias]['deger']:g}")
            try:
                self.gonder(tg.alarm("BİLGİ: ortak öğrenme dersi uygulandı", "\n".join(satirlar) + "\nDers yalnız riski azaltır; kötü giderse otomatik geri alınır.", "ℹ️"))
            except Exception:                                          # noqa: BLE001
                pass
        return olaylar

    # ------------------------------------------------------------------ 4) karne + sanal kasa + drift (yalnız rapor/uyarı)
    def karne_guncelle(self, simdi: int) -> None:
        """Saatlik: paket `karne` (kurulum başına aday/alınan/ort R/sanal kasa) + `kurulum_drift` (CUSUM). `durum/ogrenme/karne.json` + pano özeti; drift `uyari` olunca olay + TEK Telegram UYARI."""
        adaylar = oku_jsonl(self.adaylar_yolu)
        kr = karne.karne(adaylar)
        dr = drift.kurulum_drift(adaylar)
        satirlar = []
        for alias, v in sorted(kr.items()):
            d = dr.get(alias, {})
            e = self.uyg["emekli"].get(alias)
            c = self.uyg["carpan"].get(alias)
            m = self._model(alias, simdi)
            satirlar.append({"kurulum": alias, "aday": v["aday"], "alinan": v["alinan"], "ort_r": None if v["ort_r_alinan"] is None else round(v["ort_r_alinan"], 3),
                             "kasa": v["kasa"]["alinan"]["kasa"], "getiri_pct": v["kasa"]["alinan"]["getiri_pct"], "en_derin_pct": v["kasa"]["alinan"]["en_derin_pct"],
                             "drift": d.get("durum", "yok"), "drift_n": d.get("n", 0), "emekli": e is not None, "carpan": None if c is None else c["deger"], "filtre": m is not None})
        self._pano = satirlar
        _atomik_yaz(self.karne_yolu, {"ms": simdi, "pano": satirlar, "karne": kr, "drift": dr})
        for alias, d in dr.items():
            if d["durum"] != "uyari" or not d["alarms"]:
                continue
            son = int(d["alarms"][-1])
            if son <= int(self.uyg["drift_uyari"].get(alias, 0)):
                continue
            self.uyg["drift_uyari"][alias] = son
            self._kayit(olay="kurulum_drift", kurulum=alias, n=d["n"], alarm_indeksi=son, S=round(float(d["S"]), 4))
            if self.k["sanal_ogrenme_drift_eylem"]:                       # K-73 (kullanıcı kararı 19.11 gece): sanalda drift işlem etkiler: filtre yeniden eğitilir + slot çarpanı <= 0.5
                eski = self.agirlik_alias(alias)
                yeni_c = max(AGIRLIK_ALT, min(AGIRLIK_UST, min(eski, 0.5)))
                self.uyg["egit_zorla"] = True
                self.uyg["drift_carpan"][alias] = {"deger": yeni_c, "ms": int(simdi)}
                self._kayit(olay="drift_eylem", kurulum=alias, egit_zorla=True, carpan_once=round(eski, 4), carpan=yeni_c)
            if self.gonder and self.k["ogrenme_drift_telegram"]:          # varsayılan KAPALI: eşikler CT için kalibre değil (yalnız olay + OZET)
                try:
                    self.gonder(tg.alarm("UYARI: trader performansı bozuluyor (drift)", f"{alias}: son {d['n']} kapanan işlemde CUSUM alarmı (işlem #{son}).\nYalnız uyarı; kopyalama değişmedi.", "⚠️"))
                except Exception:                                  # noqa: BLE001
                    pass

    def pano(self) -> list[dict] | None:
        """`ozet.json` için kurulum satırları (takma adlı); veri yoksa None."""
        return self._pano if self.aktif and self._pano else None

    # ------------------------------------------------------------------ 5) ortak filtre (yalnız ATLAR; asla artırmaz)
    @staticmethod
    def _zaman_ozellikleri(ms: int) -> dict[str, float]:
        d = _utc(ms)
        return {"saat_utc": float(d.hour), "hafta_gunu": float(d.weekday()), "hafta_sonu": 1.0 if d.weekday() >= 5 else 0.0}

    def _ozellikler(self, ms: int, ham: dict) -> dict[str, float]:
        """Karar anında bilinen sayısal özellikler: zaman + trader kaldıracı / hesap büyüklüğü / pozisyon oranı. Eksik/sonsuz değer YAZILMAZ (paket NaN→ortalama doldurur)."""
        o = self._zaman_ozellikleri(ms)
        hesap = ham.get("trader_hesap_usd")
        if isinstance(hesap, (int, float)) and hesap > 0 and math.isfinite(hesap):
            o["trader_hesap_log10"] = math.log10(hesap)
            poz = ham.get("trader_poz_usd")
            if isinstance(poz, (int, float)) and math.isfinite(poz):
                o["trader_poz_oran"] = abs(poz) / hesap
        kl = ham.get("trader_kaldirac")
        if isinstance(kl, (int, float)) and not isinstance(kl, bool) and math.isfinite(kl):
            o["trader_kaldirac"] = float(kl)
        return o

    @staticmethod
    def _filtre_modul() -> Any:
        """numpy yoksa (ör. numpy kurulmamış vardiya) None: filtre kapalı, her şey geçer."""
        try:
            from copytrade.ortak_ogrenme import filtre
            return filtre
        except ImportError:
            return None

    def _model(self, alias: str, simdi: int) -> dict | None:
        """Geçerli (hash + süre) paket ya da None. Önbellekli; süre dolunca otomatik None."""
        fm = self._filtre_modul()
        if fm is None:
            return None
        now = _utc(simdi)
        c = self._modeller.get(alias, False)
        if c is False:
            try:
                p = fm.yukle(self.filtre_dizin / f"{fm._guvenli_ad(alias)}.json", simdi=now)
                c = (p, datetime.fromisoformat(p["meta"]["son_kullanma"]).astimezone(timezone.utc))
            except (fm.PaketHatasi, OSError, ValueError, KeyError):
                c = None
            self._modeller[alias] = c
        if c is None or now >= c[1]:
            return None
        return c[0]

    def _yok_logla(self, alias: str, simdi: int, neden: str) -> None:
        if simdi - self._filtre_log.get(alias, -10**18) >= float(self.k["ogrenme_filtre_log_saat"]) * 3_600_000:
            self._filtre_log[alias] = simdi
            self._kayit(olay="ml_filtre_yok", kurulum=alias, neden=neden)

    def filtre_kontrol(self, adres: str, coin: str, simdi: int, ham: dict) -> dict | None:
        """Yeni açılış/artırma için ÇAĞRILIR. Döner: ATLA kararı {"puan", "esik"} ya da None (geç). Model yok/süresi dolmuş/numpy yok/hata → None (her şeyi geçirir) + `ml_filtre_yok`.
        Yalnız atlar; boyutu asla artırmaz. Geçen açılışın karar anı özellikleri eğitim satırı için saklanır."""
        try:
            if not self.aktif or not self.k["ogrenme_filtre_aktif"]:
                return None
            alias = takma_ad(adres)
            oz = self._ozellikler(simdi, ham)
            if len(self.bekleyen) > 200:
                self.bekleyen = {a: v for a, v in self.bekleyen.items() if simdi - int(v["ms"]) <= BEKLEYEN_OMUR_MS}
            fm = self._filtre_modul()
            paket = self._model(alias, simdi)
            if paket is not None:
                p = float(fm.puan(paket, oz))
                if p < float(paket["esik"]):
                    self._kayit(olay="ml_filtre_atla", kurulum=alias, coin=coin, puan=round(p, 4), esik=round(float(paket["esik"]), 4), n_egitim=paket["meta"].get("n_egitim"))
                    return {"puan": p, "esik": float(paket["esik"])}
                self._kayit(olay="ml_filtre_al", kurulum=alias, coin=coin, puan=round(p, 4), esik=round(float(paket["esik"]), 4), n_egitim=paket["meta"].get("n_egitim"))      # "aldı" kararı (yalnız kayıt; karar mantığı aynı)
            else:
                self._yok_logla(alias, simdi, "numpy_yok" if fm is None else "model_yok_ya_da_suresi_dolmus")
            self.bekleyen[f"{alias}|{coin}"] = {"ms": int(simdi), "ozellik": oz}
            return None
        except Exception as hata:                                 # noqa: BLE001
            self._kayit(olay="ogrenme_hata", asama="filtre_kontrol", tur=type(hata).__name__, mesaj=str(hata)[:120])
            return None

    def filtre_egit(self, simdi: int) -> None:
        """Saatlik adımda: alias başına en az `ogrenme_filtre_min_n` etiketli kapanan işlem varsa ve model yok / `ogrenme_filtre_egitim_gun` günden eski (21 gün son kullanmadan çok önce) / hafta değişimi
        bayrağı varsa yeniden eğitir (paket `egit` + `kaydet`: hash, .prev yedeği, gidiş-dönüş doğrulama). Veri azsa ya da tek sınıfsa EĞİTİLMEZ. numpy yoksa hiçbir şey yapmaz."""
        fm = self._filtre_modul()
        if fm is None or not self.k["ogrenme_filtre_aktif"]:
            return
        zorla = bool(self.uyg.get("egit_zorla"))
        adaylar = oku_jsonl(self.adaylar_yolu)
        grup: dict[str, list[Aday]] = {}
        for a in adaylar:
            if a.alindi and a.r is not None:
                grup.setdefault(a.kurulum, []).append(a)
        now = _utc(simdi)
        for alias, cs in sorted(grup.items()):
            if len(cs) < int(self.k["ogrenme_filtre_min_n"]):
                continue
            mevcut = self._model(alias, simdi)
            if mevcut is not None and not zorla:
                yas_gun = (now - datetime.fromisoformat(mevcut["meta"]["olusturma"]).astimezone(timezone.utc)).total_seconds() / 86400.0
                if yas_gun < float(self.k["ogrenme_filtre_egitim_gun"]):
                    continue
            paket = fm.egit(alias, adaylar, olusturma=now)
            if paket is None:                                       # tek sınıf: eskisi (varsa) kalır, süresi dolunca filtre kendiliğinden kapanır
                self._kayit(olay="ml_filtre_egitilmedi", kurulum=alias, neden="tek_sinif", n=len(cs))
                continue
            fm.kaydet(paket, self.filtre_dizin)
            self._modeller.pop(alias, None)
            self._kayit(olay="ml_filtre_egitildi", kurulum=alias, n_egitim=paket["meta"]["n_egitim"], taban_oran=round(paket["meta"]["taban_oran"], 4), esik=round(paket["esik"], 4),
                        son_kullanma=paket["meta"]["son_kullanma"])
        if zorla:
            self.uyg["egit_zorla"] = False
