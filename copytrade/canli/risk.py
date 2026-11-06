"""Portföy riski (docs/RADAR_V1.md §6; görev T4 §1). SAF durum makinesi: saat ve özsermaye dışarıdan verilir.

- Coin yoğunlaşması: aynı coinde TÜM slotların brüt nosyoneli ≤ kasa × `canli_coin_tavan_oran`; aşan açılış KIRPILIR (kırpılan < `radar_min_emir_usd` ise 0).
- Patlama freni: bir trader `canli_patlama_pencere_dk` dk içinde ≥ `canli_patlama_coin` YENİ coin açarsa (o sekizinci açılış dahil) `canli_patlama_ara_dk` dk ondan yeni açılış kopyalanmaz (kapanışlar izlenir).
- Günlük kayıp: UTC gün başı özsermayeden kayıp ≥ `canli_gunluk_kayip_oran` → o gün yeni açılış yok.
- Zirveden düşüş ≥ `canli_zirve_dusus_oran` → `DUR`: tüm pozisyonlar reduce‑only kapatılır, motor durur, `durum/DUR` yazılır (elle silinmeden yeniden açılmaz). `/kapat` aynı (yeni `/dur` yalnız yeni girişi durdurur).
- Kasa > `canli_kasa_ust_usd` (AGENTS.md sınırı): yeni açılış yok + alarm.
"""
from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
from typing import Any

DAKIKA = 60_000


def gun(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).date().isoformat()


class Risk:
    def __init__(self, rules: dict, kasa_usd: float, durum: dict | None = None) -> None:
        self.rules, self.kasa = rules, float(kasa_usd)
        d = durum or {}
        self.zirve: float = float(d.get("zirve", kasa_usd))
        self.gun: str | None = d.get("gun")
        self.gun_basi: float = float(d.get("gun_basi", kasa_usd))
        self.dur: bool = bool(d.get("dur", False))
        self.dur_neden: str | None = d.get("dur_neden")
        self.fren_bitis: dict[str, int] = {k: int(v) for k, v in (d.get("fren_bitis") or {}).items()}
        self.yeni_coin: dict[str, deque[tuple[int, str]]] = {a: deque((int(x[0]), str(x[1])) if isinstance(x, (list, tuple)) else (int(x), "") for x in v) for a, v in (d.get("yeni_coin") or {}).items()}      # (ms, coin); eski biçim (yalnız ms) okunur
        self.acilis_durdu: dict[str, bool] = dict(d.get("acilis_durdu") or {})        # neden -> aktif mi (gunluk_kayip, mutabakat, kasa_siniri, kadro)

    # ------------------------------------------------------------------ özsermaye izleme
    def ozsermaye_isle(self, ozsermaye: float, simdi_ms: int) -> list[str]:
        """Dakikalık çağrı: UTC gün sınırını, günlük kayıp bayrağını ve zirve düşüşünü günceller. Döner: yeni tetiklenen olaylar (`gunluk_kayip`, `zirve_dusus`)."""
        olaylar: list[str] = []
        g = gun(simdi_ms)
        if g != self.gun:
            self.gun, self.gun_basi = g, float(ozsermaye)
            self.acilis_durdu["gunluk_kayip"] = False
        self.zirve = max(self.zirve, float(ozsermaye))
        kayip = (self.gun_basi - ozsermaye) / self.gun_basi if self.gun_basi > 0 else 0.0
        if kayip >= float(self.rules["canli_gunluk_kayip_oran"]) - 1e-12 and not self.acilis_durdu.get("gunluk_kayip"):
            self.acilis_durdu["gunluk_kayip"] = True
            olaylar.append("gunluk_kayip")
        dusus = (self.zirve - ozsermaye) / self.zirve if self.zirve > 0 else 0.0
        if dusus >= float(self.rules["canli_zirve_dusus_oran"]) - 1e-12 and not self.dur:
            self.dur, self.dur_neden = True, "zirve_dusus"
            olaylar.append("zirve_dusus")
        return olaylar

    def dur_ver(self, neden: str) -> None:
        self.dur, self.dur_neden = True, neden

    def kasa_siniri_asildi(self, kasa_usd: float) -> bool:
        asildi = float(kasa_usd) > float(self.rules["canli_kasa_ust_usd"]) + 1e-9
        self.acilis_durdu["kasa_siniri"] = asildi
        return asildi

    def bayrak(self, ad: str, aktif: bool) -> None:
        self.acilis_durdu[ad] = aktif

    # ------------------------------------------------------------------ açılış izni
    def acilis_izni(self, adres: str, coin: str, yeni_coin_mu: bool, simdi_ms: int) -> tuple[bool, str]:
        """Yeni açılış / artırma izni (kapanış/azaltma buradan GEÇMEZ). Döner (izin, neden)."""
        if self.dur:
            return False, "dur"
        for ad, aktif in self.acilis_durdu.items():
            if aktif:
                return False, ad
        if self.patlama_freni(adres, coin, yeni_coin_mu, simdi_ms):
            return False, "patlama_freni"
        return True, ""

    def patlama_freni(self, adres: str, coin: str, yeni_coin_mu: bool, simdi_ms: int) -> bool:
        """O1 (RADAR §6: '≥ 8 yeni coin'): pencere içindeki FARKLI coin sayısı (açılmak istenen coin dahil) eşiğe varırsa fren. Burada sayılmaz; açılış gerçekleşince `yeni_coin_kaydet`."""
        if simdi_ms < self.fren_bitis.get(adres, 0):
            return True
        if not yeni_coin_mu:
            return False
        farkli = self._pencere_coinleri(adres, simdi_ms) | {coin}
        if len(farkli) >= int(self.rules["canli_patlama_coin"]):
            self.fren_bitis[adres] = simdi_ms + int(self.rules["canli_patlama_ara_dk"]) * DAKIKA
            self.yeni_coin.pop(adres, None)
            return True
        return False

    def _pencere_coinleri(self, adres: str, simdi_ms: int) -> set[str]:
        pencere = int(self.rules["canli_patlama_pencere_dk"]) * DAKIKA
        kuyruk = self.yeni_coin.get(adres)
        if kuyruk is None:
            return set()
        while kuyruk and kuyruk[0][0] < simdi_ms - pencere:
            kuyruk.popleft()
        return {c for _, c in kuyruk}

    def yeni_coin_kaydet(self, adres: str, coin: str, simdi_ms: int) -> None:
        """Gerçekten AÇILAN yeni coini patlama frenine yazar (aynı coin pencerede bir kez sayılır)."""
        self._pencere_coinleri(adres, simdi_ms)
        kuyruk = self.yeni_coin.setdefault(adres, deque())
        if coin not in {c for _, c in kuyruk}:
            kuyruk.append((simdi_ms, coin))

    def coin_tavani(self, emir_usd: float, coin_brut_usd: float) -> tuple[float, str]:
        """Aynı coindeki toplam brüt ≤ kasa × oran. Döner (uygulanan $, neden): kırpılmadıysa neden ''; kırpılan < min emir ise 0 ('coin_tavani')."""
        izin = float(self.rules["canli_coin_tavan_oran"]) * self.kasa - coin_brut_usd
        if emir_usd <= izin + 1e-9:
            return emir_usd, ""
        kirpilan = max(0.0, izin)
        return (kirpilan, "coin_tavani_kirpildi") if kirpilan >= float(self.rules["radar_min_emir_usd"]) else (0.0, "coin_tavani")

    def marj_kirp(self, emir_usd: float, marj_kullanilan_usd: float, ozsermaye_usd: float, kaldirac: float | None = None) -> tuple[float, str]:
        """K‑35 toplam marj tavanı: açık pozisyonların başlangıç marjı toplamı (nosyonel / kaldıraç) + yeni emrin marjı ≤ özsermaye (serbest kasa). Aşan kısım KIRPILIR (`marj_yok`);
        kırpılan < `radar_min_emir_usd` ise 0. Gerçek kipte HL zaten reddeder; sanal kipte bu olmadan getiri şişerdi. Döner (uygulanan $, neden: '' | 'marj_yok')."""
        k = float(kaldirac if kaldirac is not None else self.rules["canli_marj_kaldirac"])
        izin = max(0.0, float(ozsermaye_usd) - float(marj_kullanilan_usd)) * k
        if emir_usd <= izin + 1e-9:
            return emir_usd, ""
        return (izin, "marj_yok") if izin >= float(self.rules["radar_min_emir_usd"]) else (0.0, "marj_yok")

    # ------------------------------------------------------------------ kalıcılık
    def to_json(self) -> dict[str, Any]:
        return {"zirve": self.zirve, "gun": self.gun, "gun_basi": self.gun_basi, "dur": self.dur, "dur_neden": self.dur_neden, "fren_bitis": self.fren_bitis,
                "yeni_coin": {a: list(v) for a, v in self.yeni_coin.items()}, "acilis_durdu": self.acilis_durdu}
