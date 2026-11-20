"""CT yerel koruyucu (K-82): motordan BAĞIMSIZ ikinci hat. Ayrı süreç (`python -m copytrade.koruyucu`, deploy/sg-sanal-koruyucu.service).

Okur (motorun dosyaları, salt okur): durum/risk.json (son özsermaye), durum/motor.json (kasa, kip), durum/kilit.json (motor nabzı).
Yazar: durum/ortak/ct.json (taslak arayüz CT bölümü), durum/ortak/dur.json (bayrak), durum/ortak/koruyucu.json (nabız + kendi gün/zirve durumu), kayit/koruyucu/<gün>.jsonl.
Denetler (kendi gün başı/zirve hesabıyla; motorunkine bağımlı değil, yalnız ilk kurulumda tohumlanır):
  günlük kayıp >= `canli_gunluk_kayip_oran`  -> `yeni_acilis_dur` (UTC gün dönümünde kalkar)
  zirveden düşüş >= `canli_zirve_dusus_oran` -> `kapat_dur` (mandal: yalnız insan kaldırır: DUR dosyası/bayrak silinir)
  motor nabzı `koruyucu_motor_nabiz_bayat_sn`den eski -> alarm + `yeni_acilis_dur` (nabız düzelince kalkar)
Motor tarafı (`motor_kancasi`, motor.py dakikalık adım): bayrağı uygular (yeni açılış durur / dur_tetikle) ve koruyucu nabzını denetler. Limit rakamı burada yok: kurallar.yaml okunur."""
from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from copytrade.canli import telegram as tg
from copytrade.kurallar import load_rules

SEMA_HESAP, SEMA_DUR, SEMA_KORUYUCU = "ortak.hesap.v1", "ortak.dur.v1", "ortak.koruyucu.v1"
SURUM = 1
ORTAK = "ortak"
BAYRAK_ACILIS = "koruyucu"          # risk.acilis_durdu anahtarı (koruyucu bayrağı, `elle_dur` ile karışmaz)
BAYRAK_NABIZ = "koruyucu_nabiz"     # koruyucu bir kez görüldü ve nabzı bayatladı: açılış durur
MOTOR_ACILIS_BEKLEME_MS = 90_000    # motor yeni başladıysa mandal bayrağı bu kadar uygulanmaz (koruyucu DUR'un insan tarafından silindiğini görüp mandalı kaldırsın)


def yaz(yol: Path, veri: Any) -> None:
    """Atomik JSON yazma: geçici dosya + fsync + os.replace + dizin fsync."""
    yol.parent.mkdir(parents=True, exist_ok=True)
    gecici = yol.with_suffix(yol.suffix + ".tmp")
    with gecici.open("w", encoding="utf-8") as f:
        f.write(json.dumps(veri, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(gecici, yol)
    try:
        dfd = os.open(yol.parent, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass


def oku(yol: Path) -> dict | None:
    try:
        d = json.loads(yol.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def _gun(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).date().isoformat()


def _sayi(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and abs(v) != float("inf") else None


class Kayit:
    """kayit/koruyucu/<gün>.jsonl; yazma hatası koruyucuyu durdurmaz."""

    def __init__(self, dizin: Path, saat_ms: Callable[[], int]) -> None:
        self.dizin, self.saat_ms = dizin, saat_ms

    def __call__(self, olay: dict) -> None:
        ms = self.saat_ms()
        try:
            self.dizin.mkdir(parents=True, exist_ok=True)
            with (self.dizin / f"{_gun(ms)}.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({"zaman_ms": ms, **olay}, ensure_ascii=False, separators=(",", ":"), default=str) + "\n")
        except OSError:
            pass


class Koruyucu:
    def __init__(self, rules: dict, durum_dizin: Path, kayit_dizin: Path, tgram: tg.Telegram | None = None, saat_ms: Callable[[], int] | None = None) -> None:
        self.rules = rules
        self.durum = Path(durum_dizin)
        self.ortak = self.durum / ORTAK
        self.saat_ms = saat_ms or (lambda: int(time.time() * 1000))
        self.kayit = Kayit(Path(kayit_dizin) / "koruyucu", self.saat_ms)
        self.tg = tgram if tgram is not None else tg.Telegram()
        self.d: dict = oku(self.ortak / "koruyucu.json") or {}                   # kendi kalıcı durumu (gün, gün başı, zirve, mandal, nedenler)
        self._motor_bayat = False

    # ------------------------------------------------------------------ girdiler
    def _motor_nabzi(self) -> int | None:
        k = oku(self.durum / "kilit.json") or {}
        m = oku(self.durum / "motor.json") or {}
        degerler = [int(v) for v in (k.get("nabiz_ms"), m.get("yazildi_ms")) if _sayi(v)]
        return max(degerler) if degerler else None

    def _tohumla(self, oz: float, kasa: float | None, simdi: int) -> None:
        """İlk çalışma: gün başı / zirve motorun kaydından tohumlanır (varsa), yoksa güncel değer / kasa. Sonrası kendi hesabı."""
        r = oku(self.durum / "risk.json") or {}
        g = _gun(simdi)
        gb = _sayi(r.get("gun_basi")) if r.get("gun") == g else None
        zr = _sayi(r.get("zirve"))
        self.d.update({"gun": g, "gun_basi": gb if gb else oz, "zirve": max(x for x in (zr, kasa, oz) if x is not None)})

    # ------------------------------------------------------------------ bir döngü
    def adim(self) -> dict:
        simdi = self.saat_ms()
        r = oku(self.durum / "risk.json") or {}
        m = oku(self.durum / "motor.json") or {}
        oz, kasa = _sayi(r.get("son_oz")), _sayi(m.get("kasa_usd"))
        d = self.d
        nedenler: list[str] = []                                                                   # her döngüde yeniden değerlendirilir (mandal `kapat` ayrı ve kalıcı)
        nabiz = self._motor_nabzi()
        dur_var = (self.durum / "DUR").exists()
        # --- insan DUR'u kaldırdı mı (mandal kaldırma): DUR görülmüştü, şimdi yok
        if d.get("dur_goruldu") and not dur_var and d.get("kapat"):
            self._mandal_kaldir("DUR dosyası silindi", oz)
        if d.get("kapat") and dur_var:
            d["dur_goruldu"] = True
        if d.get("kapat") and not (self.ortak / "dur.json").exists():                               # bayrak dosyası silindi: insan kaldırdı
            self._mandal_kaldir("bayrak dosyası silindi", oz)
        # --- özsermaye denetimi
        gunluk = dusus = None
        if oz is not None:
            if "gun" not in d:
                self._tohumla(oz, kasa, simdi)
            g = _gun(simdi)
            if g != d["gun"]:
                d["gun"], d["gun_basi"] = g, d.get("son_oz", oz)                                   # F09: gün sınırı tabanı = önceki günün son gözlemi
            d["son_oz"] = oz
            d["zirve"] = max(float(d["zirve"]), oz)
            gb, zr = float(d["gun_basi"]), float(d["zirve"])
            gunluk = (gb - oz) / gb if gb > 0 else 0.0
            dusus = (zr - oz) / zr if zr > 0 else 0.0
            if gunluk >= float(self.rules["canli_gunluk_kayip_oran"]) - 1e-12:
                nedenler.append("gunluk_kayip")
                if not d.get("gunluk_alarm") == g:
                    d["gunluk_alarm"] = g
                    self.kayit({"olay": "koruyucu", "tur": "gunluk_kayip", "oran": round(gunluk, 5), "oz": oz})
                    self.tg.gonder(f"⚠️ Koruyucu: günlük kayıp %{gunluk * 100:.1f} (sınır %{float(self.rules['canli_gunluk_kayip_oran']) * 100:.0f}); yeni açılış durduruldu")
            if dusus >= float(self.rules["canli_zirve_dusus_oran"]) - 1e-12 and not d.get("kapat"):
                d["kapat"], d["kapat_ms"], d["kapat_neden"] = True, simdi, "zirve_dusus"
                self.kayit({"olay": "koruyucu", "tur": "zirve_dusus_kapat", "oran": round(dusus, 5), "oz": oz})
                self.tg.gonder(f"❌ Koruyucu: zirveden düşüş %{dusus * 100:.1f} (sınır %{float(self.rules['canli_zirve_dusus_oran']) * 100:.0f}); hepsi kapatılıyor, motor duruyor")
        # --- motor nabzı
        bayat_sn = float(self.rules.get("koruyucu_motor_nabiz_bayat_sn", 180))
        bayat = nabiz is not None and not dur_var and (simdi - nabiz) / 1000 > bayat_sn
        if bayat:
            nedenler.append("motor_nabiz_bayat")
            if not self._motor_bayat:
                self.kayit({"olay": "koruyucu", "tur": "motor_nabiz_bayat", "yas_sn": round((simdi - nabiz) / 1000)})
            self.tg.uyar("koruyucu_motor_nabiz", f"⚠️ Koruyucu: motor nabzı {int((simdi - nabiz) / 60000)} dk'dır yok; yeni açılış durduruldu",
                         dogrula=lambda: self._motor_hala_bayat(bayat_sn))
        elif self._motor_bayat:
            self.kayit({"olay": "koruyucu", "tur": "motor_nabiz_duzeldi"})
            self.tg.duzeldi("koruyucu_motor_nabiz", tg.duzeldi_metni("koruyucu", "Motor nabzı geri geldi; yeni açılış serbest."))
        self._motor_bayat = bool(bayat)
        d["nedenler"] = sorted(set(nedenler))
        # --- yazımlar
        acilis = bool(d["nedenler"])
        kapat = bool(d.get("kapat"))
        yaz(self.ortak / "dur.json", {"sema": SEMA_DUR, "surum": SURUM, "yazildi_ms": simdi, "toplam": None,
                                      "ct": {"yeni_acilis_dur": acilis or kapat, "kapat_dur": kapat, "nedenler": d["nedenler"] + ([d.get("kapat_neden")] if kapat else []), "ms": simdi},
                                      "ml": None})
        yaz(self.ortak / "ct.json", self._ct_bolumu(simdi, r, m, oz, gunluk, dusus))
        d.update({"sema": SEMA_KORUYUCU, "surum": SURUM, "yazildi_ms": simdi})
        yaz(self.ortak / "koruyucu.json", d)
        return {"acilis_dur": acilis or kapat, "kapat_dur": kapat, "nedenler": d["nedenler"], "gunluk": gunluk, "dusus": dusus}

    def _motor_hala_bayat(self, bayat_sn: float) -> bool:
        n = self._motor_nabzi()
        return n is not None and not (self.durum / "DUR").exists() and (self.saat_ms() - n) / 1000 > bayat_sn

    def _mandal_kaldir(self, neden: str, oz: float | None) -> None:
        d = self.d
        d["kapat"], d["dur_goruldu"] = False, False
        d.pop("kapat_ms", None), d.pop("kapat_neden", None)
        if oz is not None:
            d["zirve"] = oz                                                                          # yeniden başlatma: zirve güncel değere (motor `zirve_yenile` ile aynı mantık)
        self.kayit({"olay": "koruyucu", "tur": "mandal_kalkti", "neden": neden})

    def _ct_bolumu(self, simdi: int, r: dict, m: dict, oz: float | None, gunluk: float | None, dusus: float | None) -> dict:
        ozet = oku(self.durum / "ozet.json") or {}
        d = self.d
        return {"sema": SEMA_HESAP, "surum": SURUM, "taraf": "ct", "kip": m.get("kip"), "yazildi_ms": simdi, "ozsermaye_usd": oz,
                "gun_basi_usd": d.get("gun_basi"), "zirve_usd": d.get("zirve"), "gunluk_kayip_oran": gunluk, "zirveden_dusus_oran": dusus,
                "acik_nosyonel_usd": _sayi(ozet.get("brut_usd")), "kaldirac": None, "acik_pozisyon": ozet.get("acik_pozisyon"), "dur": bool(r.get("dur"))}


# ---------------------------------------------------------------------- motor tarafı
def bayrak_oku(durum_dizin: Path) -> dict | None:
    """durum/ortak/dur.json: CT bölümü. Okunamazsa None (bayrak yok sayılmaz: çağıran `bayat_mi` ile karar verir)."""
    d = oku(Path(durum_dizin) / ORTAK / "dur.json")
    c = d.get("ct") if d else None
    return c if isinstance(c, dict) else None


def motor_kancasi(motor: Any, simdi: int) -> None:
    """Motor dakikalık adımı (motor.py "koruyucu"): (1) koruyucu bayrağını UYGULAR (sanal ve gerçek kip aynı; gölge/yalnız-kayıt yok),
    (2) koruyucu nabzını denetler. Kapanış/azaltma `acilis_izni`nden geçmediği için bayraktan etkilenmez."""
    durum = Path(motor.durum_dizin)
    rules = motor.rules
    k = oku(durum / ORTAK / "koruyucu.json")
    # --- (2) koruyucu nabzı: ilk kurulumda koruyucu hiç yoksa motoru kilitleme (yalnız uyarı); bir kez görüldükten sonra bayatlarsa açılış durur
    gorulen = durum / "koruyucu_gorulen"
    bayat_sn = float(rules.get("koruyucu_nabiz_bayat_sn", 180))
    nabiz = _sayi(k.get("yazildi_ms")) if k else None
    taze = nabiz is not None and (simdi - nabiz) / 1000 <= bayat_sn
    if taze and not gorulen.exists():
        yaz(gorulen, {"ilk_ms": simdi})
    if taze:
        motor.risk.bayrak(BAYRAK_NABIZ, False)
        motor.tg.duzeldi("koruyucu_yok", tg.duzeldi_metni("koruyucu", "Koruyucu nabzı geri geldi."))
    elif gorulen.exists():
        if not motor.risk.acilis_durdu.get(BAYRAK_NABIZ):
            motor.kayit({"olay": "koruyucu_nabiz_bayat", "yas_sn": None if nabiz is None else round((simdi - nabiz) / 1000)})
        motor.risk.bayrak(BAYRAK_NABIZ, True)
        motor.tg.uyar("koruyucu_yok", "⚠️ Koruyucu nabzı yok; yeni açılış durduruldu", dogrula=lambda: bool(motor.risk.acilis_durdu.get(BAYRAK_NABIZ)))
    else:
        motor.tg.uyar("koruyucu_yok", "⚠️ Koruyucu henüz çalışmıyor (ilk kurulum); yeni açılış engellenmedi", dogrula=lambda: not (durum / "koruyucu_gorulen").exists())
    # --- (1) bayrak
    b = bayrak_oku(durum)
    if not b:
        motor.risk.bayrak(BAYRAK_ACILIS, False)
        return
    ac = bool(b.get("yeni_acilis_dur")) or bool(b.get("kapat_dur"))
    if bool(motor.risk.acilis_durdu.get(BAYRAK_ACILIS)) != ac:
        motor.kayit({"olay": "koruyucu_bayrak", "yeni_acilis_dur": ac, "kapat_dur": bool(b.get("kapat_dur")), "nedenler": b.get("nedenler")})
    motor.risk.bayrak(BAYRAK_ACILIS, ac)
    if b.get("kapat_dur") and not motor.risk.dur and simdi - int(getattr(motor, "baslama_ms", 0) or 0) >= MOTOR_ACILIS_BEKLEME_MS:
        motor.dur_tetikle("koruyucu")


# ---------------------------------------------------------------------- süreç
def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="CT yerel koruyucu (K-82)")
    ap.add_argument("--durum-dizin", default="durum")
    ap.add_argument("--kayit-dizin", default="kayit")
    ap.add_argument("--bir-kez", action="store_true")
    a = ap.parse_args(argv)
    rules = load_rules()
    t = tg.Telegram(arka_plan=True)
    t.cift_dogrulama_sn = tg.DOGRULAMA_SN
    t.guncelleme_isareti = Path(a.durum_dizin) / "guncelleme_zamani"
    t.komut_kapali = True
    k = Koruyucu(rules, Path(a.durum_dizin), Path(a.kayit_dizin), t)
    aralik = float(rules.get("koruyucu_aralik_sn", 30))
    while True:
        try:
            k.adim()
        except Exception as hata:                                                                    # noqa: BLE001 - döngü ölmez; kayıt + alarm saatte bir
            k.kayit({"olay": "koruyucu", "tur": "adim_hata", "hata": type(hata).__name__, "mesaj": str(hata)[:160]})
            t.uyar("koruyucu_adim_hata", f"⚠️ Koruyucu adımı hata veriyor ({type(hata).__name__})")
        if a.bir_kez:
            return 0
        time.sleep(aralik)


if __name__ == "__main__":
    sys.exit(main())
