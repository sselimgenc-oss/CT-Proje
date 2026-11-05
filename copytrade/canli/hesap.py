"""Kopya hesabı (defter): trader başına coin pozisyonları, gerçekleşen K/Z, ücretler; izole 3x marj ve tasfiye fiyatı yerelde. SAF (ağ yok); JSON'a serileşir (yeniden başlatma, `durum/hesap.json`).

Birim: `$` = kasa ölçeği (kopya_$; `kasa_usd` = `canli_kasa_usd`), `sz` coin miktarı (işaretli: + long / − short), fiyat $/coin. Funding hesaba GİRMEZ (T2 oynatmasıyla aynı v1 kararı; rapor satırında not).
Özsermaye = kasa + gerçekleşen − ücret + gerçekleşmemiş (mark). Slot özsermayesi = slot başlangıcı + o trader'ın girişten beri net K/Z'si (slot −%10 düşme kuralı).
Tasfiye (izole): long `giris × (1 − 1/k) / (1 − mmr)`, short `giris × (1 + 1/k) / (1 + mmr)`; `mmr = 1 / (2 × coin azami kaldıracı)` (HL bakım marjı = azami kaldıracın başlangıç marjının yarısı); azami kaldıraç bilinmiyorsa 20.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

EPS = 1e-12


@dataclass
class Poz:
    sz: float                 # işaretli coin miktarı
    giris: float              # ortalama giriş fiyatı
    acilis_ms: int
    kaldirac: float = 3.0


def tasfiye_fiyati(yon_long: bool, giris: float, kaldirac: float, azami_kaldirac: float | None) -> float:
    mmr = 1.0 / (2.0 * (azami_kaldirac or 20.0))
    return giris * (1 - 1 / kaldirac) / (1 - mmr) if yon_long else giris * (1 + 1 / kaldirac) / (1 + mmr)


class Hesap:
    def __init__(self, kasa_usd: float, kaldirac: float = 3.0, maks_kaldirac: dict[str, float] | None = None) -> None:
        self.kasa_usd, self.kaldirac = float(kasa_usd), float(kaldirac)
        self.maks_kaldirac = dict(maks_kaldirac or {})
        self.poz: dict[str, dict[str, Poz]] = {}
        self.realize: dict[str, float] = {}          # adres -> girişten beri gerçekleşen K/Z (ücret HARİÇ)
        self.ucret: dict[str, float] = {}            # adres -> girişten beri ücret
        self.slot_bas: dict[str, float] = {}         # adres -> slot başlangıç $ (giriş anı)
        self.tasfiyeler: list[dict] = []
        self.kapanmis_net = 0.0                      # sahadan çıkıp kaydı silinen üyelerin net K/Z'si (özsermaye sürekliliği)

    # ------------------------------------------------------------------ slot
    def slot_ac(self, adres: str, slot_usd: float) -> None:
        self.slot_bas[adres] = float(slot_usd)
        self.realize[adres] = self.ucret[adres] = 0.0
        self.poz.setdefault(adres, {})

    def slot_kapat(self, adres: str) -> None:
        """Pozisyonsuz üyenin kaydını siler (açık pozisyonu varsa çağrılmaz)."""
        if not self.poz.get(adres):
            self.kapanmis_net += self.realize.get(adres, 0.0) - self.ucret.get(adres, 0.0)
            for d in (self.poz, self.realize, self.ucret, self.slot_bas):
                d.pop(adres, None)

    # ------------------------------------------------------------------ dolum
    def sz(self, adres: str, coin: str) -> float:
        p = self.poz.get(adres, {}).get(coin)
        return p.sz if p else 0.0

    def uygula(self, adres: str, coin: str, yon: str, sz: float, px: float, ucret: float, zaman_ms: int) -> float:
        """Dolumu işler (yön B alış / A satış; `sz` işaretsiz). Pozisyon sıfırı AŞMAZ (ters dönüş çağıranda kapanış + açılış olarak iki dolum). Döner: bu dolumun gerçekleşen K/Z'si (ücret hariç)."""
        if sz <= 0 or px <= 0 or not math.isfinite(px):
            raise ValueError("dolum sz/px geçersiz")
        signed = sz if yon == "B" else -sz
        poz = self.poz.setdefault(adres, {}).get(coin)
        pnl = 0.0
        if poz is None or abs(poz.sz) < EPS:
            self.poz[adres][coin] = Poz(signed, px, zaman_ms, self.kaldirac)
        elif poz.sz * signed > 0:                                        # artırma: ağırlıklı ortalama giriş
            toplam = abs(poz.sz) + abs(signed)
            poz.giris = (poz.giris * abs(poz.sz) + px * abs(signed)) / toplam
            poz.sz += signed
        else:                                                            # azaltma / kapanış
            kapanan = min(abs(poz.sz), abs(signed))
            if abs(signed) > abs(poz.sz) + 1e-9:
                raise ValueError("ters dönüş tek dolumda uygulanamaz (kapanış + açılış olarak böl)")
            pnl = kapanan * (px - poz.giris) * (1.0 if poz.sz > 0 else -1.0)
            poz.sz += signed
            if abs(poz.sz) < 1e-12:
                del self.poz[adres][coin]
        self.realize[adres] = self.realize.get(adres, 0.0) + pnl
        self.ucret[adres] = self.ucret.get(adres, 0.0) + ucret
        return pnl

    # ------------------------------------------------------------------ değerleme
    def poz_usd(self, adres: str, coin: str, mark: float | None) -> float:
        p = self.poz.get(adres, {}).get(coin)
        return 0.0 if p is None else abs(p.sz) * (mark or p.giris)

    def brut_coin(self, coin: str, marks: dict[str, float]) -> float:
        return sum(abs(c[coin].sz) * (marks.get(coin) or c[coin].giris) for c in self.poz.values() if coin in c)

    def brut_toplam(self, marks: dict[str, float]) -> float:
        return sum(abs(p.sz) * (marks.get(k) or p.giris) for c in self.poz.values() for k, p in c.items())

    def gerceklesmemis(self, adres: str | None, marks: dict[str, float]) -> float:
        kume = self.poz.values() if adres is None else [self.poz.get(adres, {})]
        return sum(p.sz * ((marks.get(k) or p.giris) - p.giris) for c in kume for k, p in c.items())

    def ozsermaye(self, marks: dict[str, float]) -> float:
        return self.kasa_usd + sum(self.realize.values()) - sum(self.ucret.values()) + self.gerceklesmemis(None, marks) + self.kapanmis_net

    def slot_ozsermaye(self, adres: str, marks: dict[str, float]) -> float | None:
        if adres not in self.slot_bas:
            return None
        return self.slot_bas[adres] + self.realize.get(adres, 0.0) - self.ucret.get(adres, 0.0) + self.gerceklesmemis(adres, marks)

    def marj_toplam(self) -> float:
        return sum(abs(p.sz) * p.giris / p.kaldirac for c in self.poz.values() for p in c.values())

    # ------------------------------------------------------------------ tasfiye
    def tasfiye_kontrol(self, marks: dict[str, float], zaman_ms: int) -> list[dict]:
        """Mark fiyatı tasfiye fiyatını geçen izole pozisyonları tasfiye fiyatında kapatır (kayıp ≈ marjın bakım marjı dışındaki kısmı). Döner: tasfiye olayları."""
        olaylar = []
        for adres, coinler in list(self.poz.items()):
            for coin, p in list(coinler.items()):
                mark = marks.get(coin)
                if not mark:
                    continue
                uzun = p.sz > 0
                liq = tasfiye_fiyati(uzun, p.giris, p.kaldirac, self.maks_kaldirac.get(coin))
                if (uzun and mark <= liq) or (not uzun and mark >= liq):
                    pnl = self.uygula(adres, coin, "A" if uzun else "B", abs(p.sz), liq, 0.0, zaman_ms)
                    ev = {"adres": adres, "coin": coin, "tasfiye_px": liq, "mark": mark, "pnl": pnl, "zaman_ms": zaman_ms}
                    olaylar.append(ev)
                    self.tasfiyeler.append(ev)
        return olaylar

    # ------------------------------------------------------------------ kalıcılık
    def to_json(self) -> dict[str, Any]:
        return {"kasa_usd": self.kasa_usd, "kaldirac": self.kaldirac, "maks_kaldirac": self.maks_kaldirac, "realize": self.realize, "ucret": self.ucret, "slot_bas": self.slot_bas,
                "poz": {a: {c: asdict(p) for c, p in coinler.items()} for a, coinler in self.poz.items()}, "tasfiyeler": self.tasfiyeler[-200:], "kapanmis_net": self.kapanmis_net}

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> "Hesap":
        h = cls(d["kasa_usd"], d.get("kaldirac", 3.0), d.get("maks_kaldirac"))
        h.realize, h.ucret, h.slot_bas = dict(d.get("realize", {})), dict(d.get("ucret", {})), dict(d.get("slot_bas", {}))
        h.poz = {a: {c: Poz(**p) for c, p in coinler.items()} for a, coinler in d.get("poz", {}).items()}
        h.tasfiyeler = list(d.get("tasfiyeler", []))
        h.kapanmis_net = float(d.get("kapanmis_net", 0.0))
        return h
