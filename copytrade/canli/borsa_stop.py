"""K-64: borsada duran felaket stopu (yalnız gerçek kip). SAF karar katmanı + küçük durum; emirleri motor yürütücü üzerinden verir.

- Hyperliquid hesabında coin başına TEK net pozisyon vardır (trader'lar ayrı değil). Stop, coin'in NET pozisyonuna konur:
  baskın yöndeki yerel pozisyonların ağırlıklı ortalama girişinden `canli_borsa_stop_oran` (0,22) aleyhe, reduce-only, piyasa tetikli (`tpsl: sl`).
- Motor ayaktayken K-62 yazılım stopu (%20) önce keser; borsadaki stop YEDEKTİR: süreç/bağlantı/sunucu çökerse borsa kendisi kapatır.
- Eşitleme (dakikalık, gerçek kip): hedef yoksa iptal; yoksa ya da miktar (> %2) / fiyat (> %0,5) / yön değiştiyse ÖNCE yeni stop konur, SONRA eskisi iptal edilir
  (arada stopsuz an olmaz). Net nosyonel < `canli_min_nosyonel_usd` ise stop konmaz (HL reddeder).
- Açık emirlerde artık görünmeyen (tetiklenmiş / dışarıda iptal) bilinen stop → `kayip` döner; motor o coinde pozisyonları borsa teyitli kapanış yoluyla temizler (G-13).
- Durumda olmayan ama bizim önekimizi taşıyan açık stop (eski süreçten yetim) → iptal edilir.
"""
from __future__ import annotations

import secrets
from typing import Any

ONEK = "0x5354"                         # "ST": borsa stopu cloid öneki (Y-5 yabancı emir denetimi bunları bizim sayar)


def stop_cloid() -> str:
    return ONEK + secrets.token_hex(14)


def bizim_mi(cloid: Any) -> bool:
    return str(cloid or "").lower().startswith(ONEK)


def hedefler(poz: dict[str, dict[str, Any]], marks: dict[str, float], oran: float, min_usd: float) -> dict[str, dict]:
    """Coin → {long, sz, tetik} (tetik: ham fiyat, yuvarlanmamış). `poz`: adres → coin → Poz(sz işaretli, giris)."""
    net: dict[str, float] = {}
    for coinler in poz.values():
        for c, p in coinler.items():
            net[c] = net.get(c, 0.0) + float(p.sz)
    sonuc: dict[str, dict] = {}
    for c, n in net.items():
        if abs(n) <= 1e-12:
            continue
        long = n > 0
        baskin = [p for coinler in poz.values() for k, p in coinler.items() if k == c and (p.sz > 0) == long and p.sz and p.giris]
        tutar = sum(abs(p.sz) for p in baskin)
        if tutar <= 0:
            continue
        giris = sum(abs(p.sz) * float(p.giris) for p in baskin) / tutar
        mk = float(marks.get(c) or giris)
        if abs(n) * mk < float(min_usd):
            continue
        sonuc[c] = {"long": long, "sz": abs(n), "tetik": giris * (1 - oran) if long else giris * (1 + oran)}
    return sonuc


def degisti_mi(eski: dict, yeni: dict) -> bool:
    if bool(eski.get("long")) != bool(yeni["long"]):
        return True
    esz, epx = float(eski.get("sz") or 0), float(eski.get("tetik") or 0)
    if esz <= 0 or epx <= 0:
        return True
    return abs(yeni["sz"] - esz) / esz > 0.02 or abs(yeni["tetik"] - epx) / epx > 0.005


class BorsaStop:
    def __init__(self, durum: dict | None = None) -> None:
        self.stoplar: dict[str, dict] = {k: dict(v) for k, v in ((durum or {}).get("stoplar") or {}).items()}     # coin → {oid, cloid, long, sz, tetik}
        self.silinecek: list[dict] = [dict(x) for x in ((durum or {}).get("silinecek") or [])]                     # iptali başarısız eski stoplar (yeniden denenir)
        self.ilk = True                                                                                         # süreç başına ilk eşitlemede yetim taraması
        self.korumasiz: dict[str, int] = {k: int(v) for k, v in ((durum or {}).get("korumasiz") or {}).items()}  # K-65: coin → stopsuz kalmaya başladığı an (ms)
        ceza = (durum or {}).get("ceza_ms")
        self.ceza_ms: int | None = int(ceza) if ceza is not None else None                                      # K-65: son zorunlu kapatma anı (yeni açılış cezası)

    def to_json(self) -> dict:
        return {"stoplar": self.stoplar, "silinecek": self.silinecek, "korumasiz": self.korumasiz, "ceza_ms": self.ceza_ms}

    def esitle(self, hedef: dict[str, dict], acik: list[dict] | None, yurutucu: Any) -> dict[str, list]:
        """`acik`: hesabın açık emirleri (openOrders; None = okunamadı → yalnız koy/iptal, kayıp/yetim tespiti yok).
        Döner {"konan": [...], "iptal": [...], "hata": [...], "kayip": [coin...], "yetim": [...]}."""
        olay: dict[str, list] = {"konan": [], "iptal": [], "hata": [], "kayip": [], "yetim": []}
        if acik is not None:
            acik_oid = {str(e.get("oid")) for e in acik if isinstance(e, dict)}
            for c, s in list(self.stoplar.items()):
                if str(s.get("oid")) not in acik_oid:                    # tetiklendi ya da dışarıda iptal edildi
                    olay["kayip"].append(c)
                    del self.stoplar[c]
            kalan = []
            for x in self.silinecek:                                         # açık emirlerde yoksa zaten gitmiş; varsa yeniden iptal dene
                if str(x.get("oid")) in acik_oid and not yurutucu.stop_iptal(str(x.get("coin")), x.get("oid")):
                    kalan.append(x)
            self.silinecek = kalan
            if self.ilk:
                bilinen = {str(s.get("oid")) for s in self.stoplar.values()} | {str(x.get("oid")) for x in self.silinecek}
                for e in acik:
                    if isinstance(e, dict) and bizim_mi(e.get("cloid")) and str(e.get("oid")) not in bilinen:
                        ok = yurutucu.stop_iptal(str(e.get("coin")), e.get("oid"))
                        olay["yetim"].append({"coin": e.get("coin"), "oid": e.get("oid"), "iptal": ok})
                self.ilk = False
        for c in list(self.stoplar):
            if c not in hedef and c not in olay["kayip"]:
                s = self.stoplar[c]
                del self.stoplar[c]
                if yurutucu.stop_iptal(c, s.get("oid")):
                    olay["iptal"].append({"coin": c, "oid": s.get("oid"), "neden": "pozisyon_yok"})
                else:
                    self.silinecek.append({"coin": c, "oid": s.get("oid")})
                    olay["hata"].append({"coin": c, "islem": "iptal", "oid": s.get("oid")})
        for c, h in hedef.items():
            if c in olay["kayip"]:                                           # önce motor borsa teyitli temizlesin; pozisyon kaldıysa sonraki eşitlemede yeniden kurulur
                continue
            eski = self.stoplar.get(c)
            if eski is not None and not degisti_mi(eski, h):
                continue
            cloid = stop_cloid()
            oid, neden, tetik = yurutucu.stop_koy(c, h["long"], h["sz"], h["tetik"], cloid)
            if oid is None:
                olay["hata"].append({"coin": c, "islem": "koy", "neden": neden})
                continue
            self.stoplar[c] = {"oid": oid, "cloid": cloid, "long": h["long"], "sz": h["sz"], "tetik": tetik}
            olay["konan"].append({"coin": c, "oid": oid, "long": h["long"], "sz": h["sz"], "tetik": tetik})
            if eski is not None and not yurutucu.stop_iptal(c, eski.get("oid")):
                self.silinecek.append({"coin": c, "oid": eski.get("oid")})
                olay["hata"].append({"coin": c, "islem": "eski_iptal", "oid": eski.get("oid")})
        return olay
