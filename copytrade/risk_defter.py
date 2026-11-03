"""H5 — anlık kopya risk defteri (DRY-RUN). docs/GOREV_H5_RISK.md, K-17/K-18.

Dinleyicinin gördüğü her İlk 11 dolumu için "kopya emri niyeti" üretir, `live_koruma.evaluate_order` kapısından geçirir (kabul / ret + neden) ve kabul
edilenleri SANAL pozisyon defterine yazar. Emir, anahtar, cüzdan, imza YOK; ağ YOK; her karar satırında `emir_gonderildi: false`.

Boyut kuralı = v3 (kural 7): açılış tutarı `defter.sabit_tutar_egrisi` (sanal kopya hesabının o anki $ değerine göre sabit tutar); ekleme = kopyanın
mevcut pozisyonu × (trader'ın eklediği / trader'ın önceki pozisyonu); azaltma/kapatma = kopyanın trader'ın kapattığı oranı. Maliyet (taker/kayma) dry-run'da
HESABA KATILMAZ (yalnız risk sınırı provası). Birimler: notional $ (1.000 $ sanal ölçek), zaman ms (UTC), fiyat $/coin.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from copytrade.kurallar import load_rules, sabit_tutar_egrisi
from copytrade.live_koruma import GateState, Limits, Mode, evaluate_order

GUN_MS = 86_400_000
EPS = 1e-12
ADRES = re.compile(r"0x[0-9a-fA-F]{40}")
SAKLAMA_GUN = 7


@dataclass
class Poz:
    boyut: float      # işaretli coin miktarı (+ long, − short)
    giris: float      # ortalama giriş fiyatı ($/coin)


class KararGunlugu:
    """`risk_kararlari.jsonl`: günlük döner (UTC gün sınırı: eski gün `risk_kararlari.<YYYY-MM-DD>.jsonl` olur), 7 gün tutulur. Adres yazılamaz."""

    def __init__(self, klasor: Path, saklama_gun: int = SAKLAMA_GUN) -> None:
        self.yol, self.saklama_gun = klasor / "risk_kararlari.jsonl", saklama_gun
        self.gun = self._dosya_gunu()

    def _dosya_gunu(self) -> str | None:
        if not self.yol.is_file():
            return None
        with self.yol.open(encoding="utf-8") as f:
            ilk = f.readline().strip()
        try:
            return str(json.loads(ilk)["gun"]) if ilk else None
        except (ValueError, KeyError):
            return None

    def yaz(self, kayit: dict[str, Any]) -> None:
        metin = json.dumps(kayit, ensure_ascii=False, sort_keys=True)
        if ADRES.search(metin):
            raise ValueError("risk_kararlari.jsonl adres içeremez")
        gun = str(kayit["gun"])
        self.yol.parent.mkdir(parents=True, exist_ok=True)
        if self.gun is not None and self.gun != gun and self.yol.is_file():
            self.yol.replace(self.yol.with_name(f"risk_kararlari.{self.gun}.jsonl"))
            self._temizle(gun)
        self.gun = gun
        with self.yol.open("a", encoding="utf-8") as f:
            f.write(metin + "\n")

    def _temizle(self, bugun: str) -> None:
        sinir = (datetime.strptime(bugun, "%Y-%m-%d") - timedelta(days=self.saklama_gun)).strftime("%Y-%m-%d")
        for yol in self.yol.parent.glob("risk_kararlari.????-??-??.jsonl"):
            if yol.name.split(".")[1] < sinir:
                yol.unlink()


def _gun(ms: int) -> int:
    return ms // GUN_MS


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class RiskDefteri:
    """Saf durum makinesi: olay -> niyet(ler) -> kapı -> sanal defter. `isle` karar satırlarını DÖNDÜRÜR (yazmak çağıranın işi)."""

    def __init__(self, ilk11: set[str], rules: dict | None = None, limitler: Limits | None = None, baslangic_ms: int = 0) -> None:
        rules = rules or load_rules()
        r = rules["risk_dry_run"]
        self.limitler = limitler or Limits.from_rules(rules)
        self.tazelik_ms = int(float(r["sinyal_tazelik_sn"]) * 1000)
        self.referans = float(r["referans_kasa_usd"])
        self.tutar: Callable[[float], float] = sabit_tutar_egrisi(rules)
        self.ilk11 = set(ilk11)
        self.dur_aktif = False
        self.pozlar: dict[tuple[str, str], Poz] = {}
        self.lider: dict[tuple[str, str], float] = {}      # trader'ın görülen pozisyonu (userFills/REST `startPosition` varsa oradan, yoksa kümülatif)
        self.bilinen: dict[str, tuple[int, dict[str, int]]] = {}   # REST ile başlangıç pozisyonu okunan trader -> (varsayılan okuma anı ms, {dex: okuma anı ms}); bilinen trader için "ilk gözlemde düz" varsayımı YOK
        self.fiyatlar: dict[str, float] = {}
        self.realized = 0.0
        self.gun = _gun(baslangic_ms) if baslangic_ms else None
        self.gun_baz = 0.0                                 # gün başındaki toplam K/Z (gerçekleşen + gerçekleşmemiş)
        self.salter = False
        self.sayac = {"niyet": 0, "kabul": 0, "ilk11_disi": 0, "gecersiz_dolum": 0, "lider_pozisyon_varsayimi": 0, "snapshot_gozlem": 0}
        self.ret: dict[str, int] = {}

    def baslangic_ayarla(self, ad: str, pozlar: dict[str, float], okuma_ms: int | dict[str, int]) -> None:
        """H5b: REST `clearinghouseState` ile okunan trader pozisyonlarını (coin -> işaretli miktar) başlangıç/tazeleme olarak verir. O trader için önceki izleme SİLİNİR
        (REST gerçektir); listede olmayan coin düzdür. `okuma_ms` (ms) ve öncesi dolumlar bu okumaya zaten dahil sayılır (çift sayım yok). Dex'ler ardışık okunduğundan
        `okuma_ms` {dex: ms} olabilir (ana dex anahtarı ""; coin'in dex'i `dex:COIN` önekidir); tek sayı = tüm dex'ler."""
        for anahtar in [k for k in self.lider if k[0] == ad]:
            del self.lider[anahtar]
        for coin, boyut in pozlar.items():
            if math.isfinite(boyut) and abs(boyut) > EPS:
                self.lider[(ad, coin)] = boyut
        okuma = {"": int(okuma_ms)} if isinstance(okuma_ms, int) else {k: int(v) for k, v in okuma_ms.items()}
        self.bilinen[ad] = (int(okuma_ms) if isinstance(okuma_ms, int) else min(okuma.values()), okuma)

    def _okuma_esigi(self, ad: str, coin: str) -> int:
        varsayilan, okuma = self.bilinen[ad]
        return okuma.get(coin.split(":", 1)[0] if ":" in coin else "", varsayilan)

    # ------------------------------------------------------------------ durum okuma
    def _mark(self, coin: str, yedek: float) -> float:
        return self.fiyatlar.get(coin, yedek)

    def brut(self, ad: str | None = None) -> float:
        return sum(abs(p.boyut) * self._mark(c, p.giris) for (a, c), p in self.pozlar.items() if ad is None or a == ad)

    def gerceklesmemis(self) -> float:
        return sum(p.boyut * (self._mark(c, p.giris) - p.giris) for (_, c), p in self.pozlar.items())

    def toplam_kz(self) -> float:
        return self.realized + self.gerceklesmemis()

    def gunluk_zarar(self) -> float:
        """Pozitif sayı = zarar ($): UTC gün başından beri toplam K/Z düşüşü (kâr 0 sayılır)."""
        return max(0.0, -(self.toplam_kz() - self.gun_baz))

    def _gun_ilerle(self, ms: int) -> None:
        g = _gun(ms)
        if self.gun is None:
            self.gun = g
        elif g > self.gun:
            self.gun, self.gun_baz, self.salter = g, self.toplam_kz(), False

    def _salter_kontrol(self) -> None:
        if self.gunluk_zarar() >= self.limitler.daily_loss_usd:
            self.salter = True

    def fiyat(self, coin: str, px: float, ms: int) -> None:
        """Herhangi bir işlemin fiyatı: yalnız açık kopya pozisyonu olan coin'ler için işaret fiyatı olur (son görülen işlem fiyatı)."""
        if not any(c == coin for (_, c) in self.pozlar) or not math.isfinite(px) or px <= 0:
            return
        self._gun_ilerle(ms)
        self.fiyatlar[coin] = px
        self._salter_kontrol()

    # ------------------------------------------------------------------ niyet üretimi
    def isle(self, *, ad: str, coin: str, yon: str, sz: float | None, px: float | None, bas_poz: float | None, zaman_ms: int, simdi_ms: int,
             kaynak: str, canli: bool = True) -> list[dict[str, Any]]:
        """Bir trader dolumu -> 0..2 karar satırı. `canli=False` (snapshot / geçmiş): yalnız trader pozisyon takibi güncellenir, niyet üretilmez."""
        if ad not in self.ilk11:
            self.sayac["ilk11_disi"] += 1
            return []
        if yon not in ("B", "A") or sz is None or not math.isfinite(sz) or sz <= EPS or not coin:
            self.sayac["gecersiz_dolum"] += 1                  # sıfır / negatif / eksik miktar: niyet yok (defter de aynısını atlar)
            return []
        anahtar = (ad, coin)
        isaret = 1.0 if yon == "B" else -1.0
        signed = isaret * sz
        if bas_poz is not None and math.isfinite(bas_poz):
            onceki = bas_poz
        else:
            if anahtar not in self.lider and ad not in self.bilinen:
                self.sayac["lider_pozisyon_varsayimi"] += 1    # YALNIZ REST başlangıç pozisyonu okunamadıysa: ilk gözlemde trader düz varsayılır
            onceki = self.lider.get(anahtar, 0.0)
            if ad in self.bilinen and zaman_ms <= self._okuma_esigi(ad, coin):
                onceki -= signed                               # dolum REST okumasından önce: okuma onu zaten içeriyor, tekrar eklenmez
                self.lider[anahtar] = onceki
        sonra = onceki + signed
        self.lider[anahtar] = 0.0 if abs(sonra) < EPS else sonra
        if not canli:
            self.sayac["snapshot_gozlem"] += 1
            return []
        self._gun_ilerle(simdi_ms)
        fiyat_gecerli = px is not None and math.isfinite(px) and px > 0
        if fiyat_gecerli:
            self.fiyatlar[coin] = px                           # kendi dolumu da son görülen fiyat
        self._salter_kontrol()
        niyetler = self._niyetler(anahtar, isaret, signed, onceki, px if fiyat_gecerli else None)
        karar_listesi = []
        for aksiyon, notional, acik, ozel_ret, boyut in niyetler:
            karar_listesi.append(self._karar(ad, coin, aksiyon, notional, acik, ozel_ret, boyut, px if fiyat_gecerli else None, zaman_ms, simdi_ms, kaynak, isaret))
        return karar_listesi

    def _niyetler(self, anahtar: tuple[str, str], isaret: float, signed: float, onceki: float, px: float | None) -> list[tuple[str, float, bool, str | None, float]]:
        """[(aksiyon, notional $, kopya pozisyonu açık mı, kapı dışı ret nedeni, coin miktarı)]. Fiyat yoksa notional 0.0 (karar `fiyat_yok`)."""
        poz = self.pozlar.get(anahtar)
        own = poz.boyut if poz else 0.0
        p = px or 0.0
        cikti: list[tuple[str, float, bool, str | None, float]] = []
        if onceki * signed < 0:                                # trader azaltıyor / kapatıyor / ters çeviriyor
            lider_kapanan = min(abs(onceki), abs(signed))
            if own * onceki > 0:
                kapanan = abs(own) * lider_kapanan / abs(onceki)
                cikti.append(("exit", kapanan * p, True, None, kapanan))
            else:                                              # trader miras / kopyalanmamış pozisyonu kapatıyor: kopyada açık pozisyon yok
                cikti.append(("exit", lider_kapanan * p, False, None, lider_kapanan))
            kalan = abs(signed) - lider_kapanan
            if kalan > EPS:                                    # ters dönüş: kalan miktar yeni pozisyon açar
                cikti.append(("open", self._yeni_tutar(), False, None, 0.0))
        elif own == 0.0:
            if abs(onceki) > EPS:                              # trader'ın zaten açık pozisyonuna ekliyor, kopyamız yok: miras (v3 `gecerli=False`) kopyalanmaz
                cikti.append(("add", self._yeni_tutar(), False, "miras_pozisyon", 0.0))
            else:
                cikti.append(("open", self._yeni_tutar(), False, None, 0.0))
        else:
            oran = abs(signed) / abs(onceki) if abs(onceki) > EPS else 0.0
            cikti.append(("add", abs(own) * self._mark(anahtar[1], poz.giris) * oran if poz else 0.0, True, None, 0.0))
        return cikti

    def _yeni_tutar(self) -> float:
        return float(self.tutar(max(0.0, self.referans + self.toplam_kz())))

    # ------------------------------------------------------------------ kapı + sanal defter
    def _karar(self, ad: str, coin: str, aksiyon: str, notional: float, acik: bool, ozel_ret: str | None, boyut: float, px: float | None,
               zaman_ms: int, simdi_ms: int, kaynak: str, isaret: float) -> dict[str, Any]:
        self.sayac["niyet"] += 1
        gecersiz = px is None or not math.isfinite(notional) or notional <= 0
        zarar = self.gunluk_zarar()
        if gecersiz:
            kapi = {"kabul": False, "nedenler": ["fiyat_yok"] if px is None else ["gecersiz_notional"], "notional_usd": 0.0, "mod": Mode.DRY_RUN.value,
                    "aksiyon": aksiyon, "emir_gonderildi": False}
        else:
            durum = GateState(Mode.DRY_RUN, halt_new_adds=self.dur_aktif)
            kapi = evaluate_order(state=durum, action=aksiyon, trader={"takim": "ilk11", "pozisyon_acik": acik}, notional_usd=notional,
                                  gross_notional_usd=self.brut(), trader_gross_notional_usd=self.brut(ad),
                                  daily_loss_usd=max(zarar, self.limitler.daily_loss_usd) if self.salter else zarar,
                                  signal_time_ms=zaman_ms, signal_deadline_ms=zaman_ms + self.tazelik_ms, now_ms=simdi_ms, limits=self.limitler)
            if ozel_ret and ozel_ret not in kapi["nedenler"]:
                kapi = {**kapi, "kabul": False, "nedenler": [*kapi["nedenler"], ozel_ret]}
        if kapi["kabul"]:
            self.sayac["kabul"] += 1
            self._uygula(ad, coin, aksiyon, notional, boyut, px, isaret)
        else:
            for neden in kapi["nedenler"]:
                self.ret[neden] = self.ret.get(neden, 0) + 1
        return {"zaman": _iso(simdi_ms), "gun": datetime.fromtimestamp(simdi_ms / 1000, UTC).strftime("%Y-%m-%d"), "trader": ad, "coin": coin,
                "aksiyon": aksiyon, "kabul": bool(kapi["kabul"]), "nedenler": list(kapi["nedenler"]), "notional_usd": round(float(notional), 6) if notional > 0 else 0.0,
                "fiyat": px, "dolum_zamani": _iso(zaman_ms), "gecikme_sn": round((simdi_ms - zaman_ms) / 1000, 3), "kaynak": kaynak,
                "dur_aktif": self.dur_aktif, "emir_gonderildi": False}

    def _uygula(self, ad: str, coin: str, aksiyon: str, notional: float, boyut: float, px: float, isaret: float) -> None:
        anahtar = (ad, coin)
        poz = self.pozlar.get(anahtar)
        if aksiyon == "exit":
            if poz is None:
                return
            kapanan = min(abs(poz.boyut), boyut)
            yon = 1.0 if poz.boyut > 0 else -1.0
            self.realized += kapanan * (px - poz.giris) * yon
            kalan = poz.boyut - yon * kapanan
            if abs(kalan) < 1e-12 * max(1.0, abs(poz.boyut)):
                del self.pozlar[anahtar]
            else:
                poz.boyut = kalan
            return
        eklenen = isaret * notional / px
        if poz is None:
            self.pozlar[anahtar] = Poz(eklenen, px)
        else:
            yeni = poz.boyut + eklenen
            poz.giris = (poz.giris * abs(poz.boyut) + px * abs(eklenen)) / abs(yeni)
            poz.boyut = yeni

    # ------------------------------------------------------------------ çıktı
    def ozet(self) -> dict[str, Any]:
        """`ozet.json` `risk` bloğu (VERI_SOZLESMESI.md). Sayaçlar çalışma başından beri kümülatiftir."""
        self._salter_kontrol()
        return {"niyet": self.sayac["niyet"], "kabul": self.sayac["kabul"], "ret": dict(sorted(self.ret.items())),
                "acik_brut_usd": round(self.brut(), 6), "gunluk_zarar_usd": round(self.gunluk_zarar(), 6), "salter_tetiklendi": self.salter,
                "dur_aktif": self.dur_aktif, "ilk11_disi": self.sayac["ilk11_disi"], "gecersiz_dolum": self.sayac["gecersiz_dolum"],
                "lider_pozisyon_varsayimi": self.sayac["lider_pozisyon_varsayimi"], "baslangic_bilinen_trader": len(self.bilinen), "snapshot_gozlem": self.sayac["snapshot_gozlem"],
                "acik_pozisyon": len(self.pozlar), "emir_gonderildi": False}
