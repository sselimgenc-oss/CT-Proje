"""Kopya hesabı (defter): trader başına coin pozisyonları, gerçekleşen K/Z, ücretler; izole 3x marj ve tasfiye fiyatı yerelde. SAF (ağ yok); JSON'a serileşir (yeniden başlatma, `durum/hesap.json`).

Birim: `$` = kasa ölçeği (kopya_$; `kasa_usd` = `canli_kasa_usd`), `sz` coin miktarı (işaretli: + long / − short), fiyat $/coin. Funding (K‑37, yalnız SANAL kip): saatlik `−sz × mark × oran` (long pozitif oranda öder; `defter.py` ile aynı işaret/birim) `funding[adres]`e eklenir ve özsermayeye girer; gerçek kipte HL kendi funding'ini hesaplar.
Özsermaye = kasa + gerçekleşen − ücret + gerçekleşmemiş (mark). Slot özsermayesi = slot başlangıcı + o trader'ın girişten beri net K/Z'si (slot −%10 düşme kuralı).
Tasfiye (izole): long `giris × (1 − 1/k) / (1 − mmr)`, short `giris × (1 + 1/k) / (1 + mmr)`; `mmr = 1 / (2 × coin azami kaldıracı)` (HL bakım marjı = azami kaldıracın başlangıç marjının yarısı); azami kaldıraç bilinmiyorsa 20 (S-7: motor sanal kipte açılışta HL `meta` evreninden `maxLeverage` okur → `maks_kaldirac`; okunamazsa 20 + kayıt).
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
    giris_ctx: dict | None = None   # açılış anı rejim/duygu damgası (yalnız bilgi; rejim_sonuc raporu)
    boyut_carpan: float = 1.0       # K-73 ek (O1): açılış/artırmada slotu küçülten çarpan (ders × gölge B5); AZALTMA aynı çarpanla hedeflenir; hesap.json ile kalıcı
    zirve_kar: float = 0.0          # K-73 iz süren koruma (yalnız sanal): girişe göre en yüksek kâr oranı (artırmada ortalama giriş değişince sıfırlanır); hesap.json ile kalıcı


def tasfiye_fiyati(yon_long: bool, giris: float, kaldirac: float, azami_kaldirac: float | None) -> float:
    mmr = 1.0 / (2.0 * (azami_kaldirac or 20.0))
    return giris * (1 - 1 / kaldirac) / (1 - mmr) if yon_long else giris * (1 + 1 / kaldirac) / (1 + mmr)


def tasfiye_mesafe(yon_long: bool, giris: float, kaldirac: float, azami_kaldirac: float | None) -> float:
    """K-74 (taslak): girişten tasfiye fiyatına ALEYHE oran (0,1429 = %14,29). Formül `tasfiye_fiyati` ile aynı."""
    liq = tasfiye_fiyati(yon_long, giris, kaldirac, azami_kaldirac)
    return (giris - liq) / giris if yon_long else (liq - giris) / giris


def dinamik_stop_orani(yon_long: bool, giris: float, kaldirac: float, azami_kaldirac: float | None, ust: float, pay: float, taban: float = 0.005) -> float:
    """K-74 (taslak, `dinamik_stop` bayrağı): pozisyon başına stop oranı = min(`ust`, tasfiye mesafesi − `pay`); en az `taban` (0 ya da eksi oran 'stop kapalı' demek olmasın)."""
    return max(taban, min(float(ust), tasfiye_mesafe(yon_long, giris, kaldirac, azami_kaldirac) - float(pay)))


KAPANAN_AZAMI = 200                                  # K-77: trader başına saklanan en çok kapanmış pozisyon kaydı


def dolum_net(pnl: float, ucret: float, giris_ucret_payi: float = 0.0) -> float:
    """D3: bir dolumun NET K/Z'si = gerçekleşen − o dolumun ücreti − (kapanışta) pozisyonun giriş/artırma ücretinden düşen pay. Pano KAPANAN ve Telegram 'kapandı' AYNI tanımı kullanır (defter/para etkilenmez)."""
    return float(pnl) - float(ucret) - float(giris_ucret_payi)


class Hesap:
    def __init__(self, kasa_usd: float, kaldirac: float = 3.0, maks_kaldirac: dict[str, float] | None = None) -> None:
        self.kasa_usd, self.kaldirac = float(kasa_usd), float(kaldirac)
        self.maks_kaldirac = dict(maks_kaldirac or {})
        self.poz: dict[str, dict[str, Poz]] = {}
        self.realize: dict[str, float] = {}          # adres -> girişten beri gerçekleşen K/Z (ücret HARİÇ)
        self.ucret: dict[str, float] = {}            # adres -> girişten beri ücret
        self.slot_bas: dict[str, float] = {}         # adres -> slot başlangıç $ (giriş anı)
        self.tasfiyeler: list[dict] = []
        self.funding: dict[str, float] = {}          # adres -> girişten beri funding ($, işaretli: + alınan / − ödenen; sanal kip)
        self.son_niyet_cloid: str | None = None      # son UYGULANAN niyetin cloid'i (t4b #3: yeniden başlatmada bundan sonraki sonuçlu niyetler oynatılır)
        self.dinleyici = None                        # ortak öğrenme: uygula() sonrası çağrılan fonksiyon (serileşmez; motor bağlar)
        self.kapanmis_net = 0.0                      # sahadan çıkıp kaydı silinen üyelerin net K/Z'si (özsermaye sürekliliği)
        self.poz_net: dict[str, float] = {}          # K-77: "adres|coin" -> AÇIK pozisyonun şimdiye dek net'i (gerçekleşen − her dolumun ücreti; giriş/artırma ücreti dahil = pano `dolum_net` toplamı)
        self.kapanan: dict[str, list[list[float]]] = {}   # K-77: adres -> TAM kapanan pozisyonların [kapanış_ms, net] listesi (en çok `KAPANAN_AZAMI` son); hesap.json ile kalıcı (yeniden başlatmada kaybolmaz)
        self.kucult: dict[str, int] = {}             # K-77: adres -> son bilinen küçültme seviyesi (0 = ×1, 1 = ×0,5, 2 = en küçük); olay tekrarını önler, pano rozeti buradan okur
        self.belirsiz: dict[str, dict] = {}         # G-1: cloid -> {ms, deneme, adres, coin} (Y-2: adres/coin yeni girdilerde); emri gönderilip yanıtı alınamayan (sonucu BELİRSİZ) niyetler. `son_niyet_cloid` ile AYNI atomik
                                                     # yazımda tutulur: çözülünce dolum deftere TEK kez uygulanır ve buradan silinir (oynatma bu niyetleri atlar: işaretçi zaten geçti)

    def _net(self, adres: str) -> float:
        """Üyenin girişten beri net K/Z'si = realize − ücret + funding (sıra korunur: kayan nokta sonucu değişmez)."""
        return self.realize.get(adres, 0.0) - self.ucret.get(adres, 0.0) + self.funding.get(adres, 0.0)

    # ------------------------------------------------------------------ slot
    def slot_ac(self, adres: str, slot_usd: float) -> None:
        """Yeni slot. M-1: üyenin eski defteri varsa (kapanışı teyit edilmeden sahadan inip geri giren üye: realize/ücret/funding ≠ 0, açık pozisyon kalmış olabilir)
        eski net (realize − ücret + funding) önce `kapanmis_net`e taşınır, sonra sıfırlanır: özsermaye değişmez (özdeşlik korunur). Açık pozisyon defterde kalır (K/Z'si yeni slota yazılır)."""
        self.kapanmis_net += self._net(adres)
        self.slot_bas[adres] = float(slot_usd)
        self.realize[adres] = self.ucret[adres] = self.funding[adres] = 0.0
        self.poz.setdefault(adres, {})

    def donem_yenile(self, kasa_usd: float, slot_usd: float) -> dict[str, float]:
        """S-3 (kasa değişikliği; yalnız pozisyonsuzken çağrılır): yeni dönem. Üyelerin girişten beri neti `kapanmis_net`e taşınır, slot tabanları yeni slota kurulur
        (slot özsermayesi = yeni slot; eski taban yüzünden `slot_dusus` yok), `kasa_usd` yeni dönem kasası. Özdeşlik: yeni özsermaye = yeni kasa + kapanmis_net (eski net korunur). Döner: eski değerler (kayıt)."""
        if any(self.poz.values()):
            raise ValueError("dönem yalnız pozisyonsuzken yenilenir")
        eski = {"kasa_usd": self.kasa_usd, "ozsermaye": self.ozsermaye({}), "kapanmis_net": self.kapanmis_net, "slot_bas": dict(self.slot_bas)}
        for adres in list(self.slot_bas):
            self.kapanmis_net += self._net(adres)
            self.realize[adres] = self.ucret[adres] = self.funding[adres] = 0.0
            self.slot_bas[adres] = float(slot_usd)
        self.kasa_usd = float(kasa_usd)
        return eski

    def slot_kapat(self, adres: str) -> None:
        """Pozisyonsuz üyenin kaydını siler (açık pozisyonu varsa çağrılmaz)."""
        if not self.poz.get(adres):
            self.kapanmis_net += self._net(adres)
            for d in (self.poz, self.realize, self.ucret, self.slot_bas, self.funding):
                d.pop(adres, None)

    # ------------------------------------------------------------------ dolum
    def sz(self, adres: str, coin: str) -> float:
        p = self.poz.get(adres, {}).get(coin)
        return p.sz if p else 0.0

    def ters_yonlu_var(self, adres: str, coin: str, yon: str, marks: dict[str, float] | None = None, toz_usd: float = 0.0) -> bool:
        """K‑41: `adres` DIŞINDAKİ bir trader'ın kopya pozisyonu bu coinde `yon` (B/A) açılışının TERSİNE mi? (Tek HL hesabında coin netleşir; ters açılış net pozisyonu küçültür.)
        Nosyoneli (mark, yoksa giriş) `toz_usd` ve altındaki kalıntı (toz; `canli_kapanis_toz_usd`) sayılmaz. Coin dizgesi birebir eşleşir (HIP‑3 `dex:COIN` ayrı coindir)."""
        isaret = 1.0 if yon == "B" else -1.0
        marks = marks or {}
        for a, c in self.poz.items():
            p = c.get(coin)
            if a != adres and p is not None and p.sz * isaret < -EPS and abs(p.sz) * (marks.get(coin) or p.giris) > toz_usd:
                return True
        return False

    def uygula(self, adres: str, coin: str, yon: str, sz: float, px: float, ucret: float, zaman_ms: int) -> float:
        """Dolumu işler (yön B alış / A satış; `sz` işaretsiz). Pozisyon sıfırı AŞMAZ (ters dönüş çağıranda kapanış + açılış olarak iki dolum). Döner: bu dolumun gerçekleşen K/Z'si (ücret hariç)."""
        if sz <= 0 or px <= 0 or not math.isfinite(px):
            raise ValueError("dolum sz/px geçersiz")
        signed = sz if yon == "B" else -sz
        poz = self.poz.setdefault(adres, {}).get(coin)
        pnl = 0.0
        yeni_poz = poz is None or abs(poz.sz) < EPS                      # ortak öğrenme dinleyicisi için (yalnız bildirim; hesabı etkilemez)
        if poz is None or abs(poz.sz) < EPS:
            self.poz[adres][coin] = Poz(signed, px, zaman_ms, self.kaldirac)
        elif poz.sz * signed > 0:                                        # artırma: ağırlıklı ortalama giriş
            toplam = abs(poz.sz) + abs(signed)
            poz.giris = (poz.giris * abs(poz.sz) + px * abs(signed)) / toplam
            poz.sz += signed
            poz.zirve_kar = 0.0                                          # ortalama giriş değişti: eski zirve geçersiz
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
        anahtar = f"{adres}|{coin}"                                      # K-77: pozisyon başına net (pano KAPANAN neti ile aynı tanım); tam kapanışta trader kapanan listesine yazılır
        self.poz_net[anahtar] = self.poz_net.get(anahtar, 0.0) + dolum_net(pnl, ucret)
        if coin not in self.poz.get(adres, {}):
            liste = self.kapanan.setdefault(adres, [])
            liste.append([int(zaman_ms), self.poz_net.pop(anahtar)])
            del liste[:-KAPANAN_AZAMI]
        if self.dinleyici is not None:                                   # ortak öğrenme: dolum bildirimi (hata hesabı bozmaz)
            try:
                p2 = self.poz.get(adres, {}).get(coin)
                ref = p2 if p2 is not None else poz                      # kapanmışsa silinen pozisyon nesnesi (açılış zamanı/kaldıraç için)
                self.dinleyici({"adres": adres, "coin": coin, "yon": yon, "sz": sz, "px": px, "pnl": pnl, "ucret": ucret, "ms": zaman_ms, "yeni": yeni_poz,
                                "kapandi": p2 is None, "poz_sz": 0.0 if p2 is None else p2.sz, "acilis_ms": zaman_ms if ref is None else ref.acilis_ms,
                                "kaldirac": self.kaldirac if ref is None else ref.kaldirac})
            except Exception:                                            # noqa: BLE001
                pass
        return pnl

    def ucret_duzelt(self, adres: str, delta: float) -> None:
        """Denetim-6 (O9): tahmini ücretin gerçek ücretle düzeltmesi (`delta` = gerçek − tahmin). Özsermaye değişimi tam −delta (özdeşlik): slot hâlâ kayıtlıysa `ucret[adres]`e,
        kapanıp silindiyse (`kapanmis_net`e taşındı) doğrudan `kapanmis_net`ten düşülür."""
        if adres in self.ucret:
            self.ucret[adres] += float(delta)
        else:
            self.kapanmis_net -= float(delta)

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

    def funding_isle(self, adres: str, tutar: float) -> None:
        self.funding[adres] = self.funding.get(adres, 0.0) + float(tutar)

    def funding_toplam(self) -> float:
        return sum(self.funding.values())

    def ozsermaye(self, marks: dict[str, float]) -> float:
        return self.kasa_usd + sum(self.realize.values()) - sum(self.ucret.values()) + self.funding_toplam() + self.gerceklesmemis(None, marks) + self.kapanmis_net

    def slot_ozsermaye(self, adres: str, marks: dict[str, float]) -> float | None:
        if adres not in self.slot_bas:
            return None
        return self.slot_bas[adres] + self.realize.get(adres, 0.0) - self.ucret.get(adres, 0.0) + self.funding.get(adres, 0.0) + self.gerceklesmemis(adres, marks)

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
                    sz0, giris0 = abs(p.sz), p.giris                      # uygula() aynı nesneyi sıfırlar: önce yakala
                    pnl = self.uygula(adres, coin, "A" if uzun else "B", sz0, liq, 0.0, zaman_ms)
                    ev = {"adres": adres, "coin": coin, "tasfiye_px": liq, "mark": mark, "pnl": pnl, "zaman_ms": zaman_ms, "sz": sz0, "giris": giris0, "yon": "uzun" if uzun else "kısa"}
                    olaylar.append(ev)
                    self.tasfiyeler.append(ev)
        return olaylar

    # ------------------------------------------------------------------ K-77 zarar küçültme
    def kapanan_ozet(self, adres: str, simdi_ms: int, pencere_ms: int) -> tuple[int, float]:
        """K-77: trader'dan kopyaladığımız, son `pencere_ms` içinde TAM kapanan pozisyonların (adet, net toplam; pozisyon bazında net = giriş+çıkış ücreti dahil)."""
        liste = [k for k in self.kapanan.get(adres, []) if simdi_ms - int(k[0]) <= pencere_ms]
        return len(liste), sum(float(k[1]) for k in liste)

    def kucult_seviye(self, adres: str, simdi_ms: int, pencere_ms: int, n1: int, n2: int) -> tuple[int, int, float]:
        """K-77 (kullanıcı kararı 20.11): (seviye, adet, net). >= `n1` kapanışta net < 0 → 1 (×çarpan1); >= `n2` kapanışta net hâlâ < 0 → 2 (en küçük); net >= 0 → 0 (×1)."""
        n, net = self.kapanan_ozet(adres, simdi_ms, pencere_ms)
        if net >= 0 or n < n1:
            return 0, n, net
        return (2 if n >= n2 else 1), n, net

    # ------------------------------------------------------------------ kalıcılık
    def to_json(self) -> dict[str, Any]:
        return {"kasa_usd": self.kasa_usd, "kaldirac": self.kaldirac, "maks_kaldirac": self.maks_kaldirac, "realize": self.realize, "ucret": self.ucret, "slot_bas": self.slot_bas,
                "poz": {a: {c: asdict(p) for c, p in coinler.items()} for a, coinler in self.poz.items()}, "tasfiyeler": self.tasfiyeler[-200:], "kapanmis_net": self.kapanmis_net, "funding": self.funding, "son_niyet_cloid": self.son_niyet_cloid,
                "belirsiz": self.belirsiz, "poz_net": self.poz_net, "kapanan": self.kapanan, "kucult": self.kucult}

    @classmethod
    def from_json(cls, d: dict[str, Any], kaldirac: float | None = None) -> "Hesap":
        """`kaldirac` (güncel kural `canli_marj_kaldirac`) verilirse defterin YENİ pozisyon kaldıracı odur; açık pozisyonlar kendi `Poz.kaldirac` değerini korur."""
        h = cls(d["kasa_usd"], d.get("kaldirac", 3.0) if kaldirac is None else kaldirac, d.get("maks_kaldirac"))
        h.realize, h.ucret, h.slot_bas = dict(d.get("realize", {})), dict(d.get("ucret", {})), dict(d.get("slot_bas", {}))
        h.poz = {a: {c: Poz(**p) for c, p in coinler.items()} for a, coinler in d.get("poz", {}).items()}
        h.tasfiyeler = list(d.get("tasfiyeler", []))
        h.kapanmis_net = float(d.get("kapanmis_net", 0.0))
        h.funding = dict(d.get("funding", {}))
        h.poz_net = {k: float(v) for k, v in (d.get("poz_net") or {}).items()}
        h.kapanan = {a: [[int(k[0]), float(k[1])] for k in v] for a, v in (d.get("kapanan") or {}).items()}
        h.kucult = {a: int(v) for a, v in (d.get("kucult") or {}).items()}
        h.son_niyet_cloid = d.get("son_niyet_cloid")
        h.belirsiz = {k: dict(v) for k, v in (d.get("belirsiz") or {}).items()}
        return h
