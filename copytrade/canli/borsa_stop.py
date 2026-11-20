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

YETIM_SONEK = "#yetim"                  # Denetim-5 (K-68): defter dışı (yetim) borsa fazlası için AYRI stop anahtarı ("ETH#yetim"); borsaya giden coin adı sonekten önceki kısımdır
ONEK = "0x5354"                         # "ST": borsa stopu cloid öneki (Y-5 yabancı emir denetimi bunları bizim sayar)


def stop_cloid() -> str:
    return ONEK + secrets.token_hex(14)


def bizim_mi(cloid: Any) -> bool:
    return str(cloid or "").lower().startswith(ONEK)


def hedefler(poz: dict[str, dict[str, Any]], marks: dict[str, float], oran: float, min_usd: float, oran_fn: Any = None) -> dict[str, dict]:
    """Coin → {long, sz, tetik} (tetik: ham fiyat, yuvarlanmamış). `poz`: adres → coin → Poz(sz işaretli, giris).
    `oran_fn(coin, long, giris) -> oran` (K-74 `dinamik_stop`; None = hep sabit `oran`, eski davranış)."""
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
        o = oran if oran_fn is None else float(oran_fn(c, long, giris))
        sonuc[c] = {"long": long, "sz": abs(n), "tetik": giris * (1 - o) if long else giris * (1 + o)}
    return sonuc


def coin_adi(anahtar: str) -> str:
    """Stop anahtarı → borsa coin adı ("ETH#yetim" → "ETH")."""
    return anahtar[: -len(YETIM_SONEK)] if anahtar.endswith(YETIM_SONEK) else anahtar


def yetim_mi(anahtar: str) -> bool:
    return anahtar.endswith(YETIM_SONEK)


def yetim_hedefler(yetim: dict[str, dict], marks: dict[str, float], oran: float, min_usd: float, oran_fn: Any = None) -> dict[str, dict]:
    """Denetim-5 (K-68): defter dışı borsa fazlası için ek stop. `yetim`: coin → {sz (işaretli fazla), mark (yetimin İLK görüldüğü andaki mark; kalıcı)}.
    Tetik referansı SABİT ilk mark'tır (her dakika güncellenmez: stop fiyatı kovalamaz), `oran` kadar aleyhe. Referans mark yoksa stop yok (uydurma fiyat yok).
    Defter temelli `hedefler` DEĞİŞMEZ; bu yalnız fazla miktarı korur (anahtar: coin + YETIM_SONEK).
    `oran_fn(coin, long, ref_mark) -> oran` (K-74 `dinamik_stop`, D7; None = sabit `oran`)."""
    sonuc: dict[str, dict] = {}
    for c, y in yetim.items():
        sz, ref = float(y.get("sz") or 0.0), float(y.get("mark") or 0.0)
        if abs(sz) <= 1e-12 or ref <= 0:
            continue
        mk = float(marks.get(c) or ref)
        if abs(sz) * mk < float(min_usd):
            continue
        long = sz > 0
        o = oran if oran_fn is None else float(oran_fn(c, long, ref))
        sonuc[c + YETIM_SONEK] = {"long": long, "sz": abs(sz), "tetik": ref * (1 - o) if long else ref * (1 + o)}
    return sonuc


def degisti_mi(eski: dict, yeni: dict) -> bool:
    if bool(eski.get("long")) != bool(yeni["long"]):
        return True
    esz, epx = float(eski.get("sz") or 0), float(eski.get("tetik") or 0)
    if esz <= 0 or epx <= 0:
        return True
    return abs(yeni["sz"] - esz) / esz > 0.02 or abs(yeni["tetik"] - epx) / epx > 0.005


def _stop_durum(yurutucu: Any, cloid: Any) -> Any:
    """Yürütücünün `stop_durum(cloid)`ı (orderStatus; resting/open ise oid) — yoksa ya da hata verirse None (bilinmiyor = "yok" sayılmaz, çağıran tekrar sorar)."""
    f = getattr(yurutucu, "stop_durum", None)
    if f is None or not cloid:
        return None
    try:
        return f(str(cloid))
    except Exception:                                  # noqa: BLE001
        return None


class BorsaStop:
    def __init__(self, durum: dict | None = None) -> None:
        self.stoplar: dict[str, dict] = {k: dict(v) for k, v in ((durum or {}).get("stoplar") or {}).items()}     # coin → {oid, cloid, long, sz, tetik}
        self.silinecek: list[dict] = [dict(x) for x in ((durum or {}).get("silinecek") or [])]                     # iptali başarısız eski stoplar (yeniden denenir)
        self.ilk = True                                                                                         # (eski: yalnız ilk eşitlemede yetim taraması; Denetim-6 O3: artık her eşitlemede) süreç başına ilk eşitleme işareti
        self.bekleyen: dict[str, dict] = {k: dict(v) for k, v in ((durum or {}).get("bekleyen") or {}).items()}   # Denetim-6 (O3): anahtar → {cloid, long, sz, tetik, yok}; GÖNDERİMDEN ÖNCE kalıcı yazılan stop cloid'i (yanıt kaybolursa emir yetim/çift kalmasın)
        self.kalici_yaz: Any = None                                                                             # Denetim-6 (O3): motorun bağladığı "durumu diske yaz" çağrısı (stop gönderilmeden önce `bekleyen` fsync'li kaydedilir)
        self.korumasiz: dict[str, int] = {k: int(v) for k, v in ((durum or {}).get("korumasiz") or {}).items()}  # K-65: coin → stopsuz kalmaya başladığı an (ms)
        ceza = (durum or {}).get("ceza_ms")
        self.ceza_ms: int | None = int(ceza) if ceza is not None else None                                      # K-65: son zorunlu kapatma anı (yeni açılış cezası)

    def to_json(self) -> dict:
        return {"stoplar": self.stoplar, "silinecek": self.silinecek, "korumasiz": self.korumasiz, "ceza_ms": self.ceza_ms, "bekleyen": self.bekleyen}

    def _benimse(self, c: str, oid: Any, b: dict, olay: dict[str, list], yurutucu: Any) -> None:
        """Bekleyen cloid borsada açık bulundu: o anahtarın (en son denenen, yani en yeni) stopu olarak kayda geçer; öncekinin stopu varsa iptal edilir (başarısızsa `silinecek`)."""
        eski = self.stoplar.get(c)
        self.stoplar[c] = {"oid": oid, "cloid": b.get("cloid"), "long": bool(b.get("long")), "sz": float(b.get("sz") or 0.0), "tetik": float(b.get("tetik") or 0.0)}
        olay["benimsenen"].append({"coin": c, "oid": oid, "cloid": b.get("cloid")})
        if eski is not None and str(eski.get("oid")) != str(oid) and not yurutucu.stop_iptal(coin_adi(c), eski.get("oid")):
            self.silinecek.append({"coin": c, "oid": eski.get("oid")})
            olay["hata"].append({"coin": c, "islem": "eski_iptal", "oid": eski.get("oid")})

    def _bekleyenleri_coz(self, acik: list[dict], yurutucu: Any, olay: dict[str, list]) -> None:
        """Denetim-6 (O3): önceki turlarda yanıtı alınamayan (`bekleyen`) stoplar açık emirlerde aranır; bulunan benimsenir. Üst üste 3 okumada görünmeyen kayıt düşer (emir hiç gitmemiş);
        sonradan ortaya çıkarsa yetim taraması iptal eder."""
        for c, b in list(self.bekleyen.items()):
            cl = str(b.get("cloid") or "").lower()
            e = next((x for x in acik if isinstance(x, dict) and str(x.get("cloid") or "").lower() == cl), None)
            if e is None:
                b["yok"] = int(b.get("yok", 0)) + 1
                if b["yok"] >= 3:
                    del self.bekleyen[c]
                continue
            del self.bekleyen[c]
            self._benimse(c, e.get("oid"), b, olay, yurutucu)

    def esitle(self, hedef: dict[str, dict], acik: list[dict] | None, yurutucu: Any) -> dict[str, list]:
        """`acik`: hesabın açık emirleri (openOrders; None = okunamadı → yalnız koy/iptal, kayıp/yetim tespiti yok).
        Döner {"konan": [...], "iptal": [...], "hata": [...], "kayip": [coin...], "yetim": [...]}."""
        olay: dict[str, list] = {"konan": [], "iptal": [], "hata": [], "kayip": [], "yetim": [], "konan_belirsiz": [], "benimsenen": []}
        if acik is not None:
            acik_oid = {str(e.get("oid")) for e in acik if isinstance(e, dict)}
            for c, s in list(self.stoplar.items()):
                if str(s.get("oid")) not in acik_oid:                    # tetiklendi ya da dışarıda iptal edildi
                    olay["kayip"].append(c)
                    del self.stoplar[c]
            kalan = []
            for x in self.silinecek:                                         # açık emirlerde yoksa zaten gitmiş; varsa yeniden iptal dene
                if str(x.get("oid")) in acik_oid and not yurutucu.stop_iptal(coin_adi(str(x.get("coin"))), x.get("oid")):
                    kalan.append(x)
            self.silinecek = kalan
            self._bekleyenleri_coz(acik, yurutucu, olay)
            bilinen = {str(s.get("oid")) for s in self.stoplar.values()} | {str(x.get("oid")) for x in self.silinecek}
            bekleyen_cloid = {str(b.get("cloid")).lower() for b in self.bekleyen.values()}
            for e in acik:                                                   # Denetim-6 (O3): yetim taraması HER eşitlemede (bekleyen cloid'ler bilinen sayılır)
                if isinstance(e, dict) and bizim_mi(e.get("cloid")) and str(e.get("oid")) not in bilinen and str(e.get("cloid")).lower() not in bekleyen_cloid:
                    ok = yurutucu.stop_iptal(str(e.get("coin")), e.get("oid"))
                    olay["yetim"].append({"coin": e.get("coin"), "oid": e.get("oid"), "iptal": ok})
            self.ilk = False
        for c in list(self.stoplar):
            if c not in hedef and c not in olay["kayip"]:
                s = self.stoplar[c]
                del self.stoplar[c]
                if yurutucu.stop_iptal(coin_adi(c), s.get("oid")):
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
            if c in self.bekleyen:                                           # önceki turdan yanıtı bilinmeyen stop: önce borsaya sor (çift stop yığılmasın)
                b = self.bekleyen[c]
                oid_b = _stop_durum(yurutucu, b.get("cloid"))
                if oid_b is not None:
                    del self.bekleyen[c]
                    self._benimse(c, oid_b, b, olay, yurutucu)
                    eski = self.stoplar.get(c)
                    if not degisti_mi(self.stoplar[c], h):
                        continue
            cloid = stop_cloid()
            self.bekleyen[c] = {"cloid": cloid, "long": h["long"], "sz": h["sz"], "tetik": h["tetik"], "yok": 0}
            if self.kalici_yaz is not None:                                  # GÖNDERİMDEN ÖNCE diske (süreç gönderim sırasında ölürse cloid bilinir)
                try:
                    self.kalici_yaz()
                except Exception:                                            # noqa: BLE001 - yazma hatası stop kurmayı engellemez (motor dakikalık durum_yaz'da yeniden dener)
                    pass
            oid, neden, tetik = yurutucu.stop_koy(coin_adi(c), h["long"], h["sz"], h["tetik"], cloid)
            if oid is None and str(neden).startswith("sdk_hatasi"):          # istek gitmiş olabilir (zaman aşımı): orderStatus(cloid) ile sor
                oid = _stop_durum(yurutucu, cloid)
                if oid is not None:
                    olay["konan_belirsiz"].append({"coin": c, "oid": oid, "cloid": cloid})
            if oid is None:
                olay["hata"].append({"coin": c, "islem": "koy", "neden": neden})
                continue
            self.bekleyen.pop(c, None)
            self.stoplar[c] = {"oid": oid, "cloid": cloid, "long": h["long"], "sz": h["sz"], "tetik": tetik}
            olay["konan"].append({"coin": c, "oid": oid, "long": h["long"], "sz": h["sz"], "tetik": tetik})
            if eski is not None and not yurutucu.stop_iptal(coin_adi(c), eski.get("oid")):
                self.silinecek.append({"coin": c, "oid": eski.get("oid")})
                olay["hata"].append({"coin": c, "islem": "eski_iptal", "oid": eski.get("oid")})
        return olay
