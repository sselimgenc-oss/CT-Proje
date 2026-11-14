"""Günlük rapor (T6 §3, K‑37): `pano/OZET.md` — telefondan GitHub'da okunan Markdown özeti. `canli-durum` dalında her vardiya sonunda güncellenir.

Kural 7: YENİ HESAP YOK. Yalnız mevcut durum/kayıt dosyalarındaki sayıları biçimler (`ozet.json`, `risk.json`, `kayit/*.jsonl`) ve basit istatistikler (sayı, toplam, medyan) alır;
getiri/özsermaye motorun yazdığı değerlerdir. Haftalık getiri için günlük özsermaye geçmişi (`pano/gecmis.json`, günde bir nokta, son 15 gün) tutulur.

Birimler: oranlar yüzde olarak gösterilir (0,012 → %1,20); $ kasa ölçeğinde (`canli_kasa_usd`); saatler UTC (belirtilir); kayma = (dolum − trader fiyatı) / trader fiyatı, ALEYHE pozitif.

    python -m copytrade.canli.pano --durum durum --kayit kayit --gecmis pano/gecmis.json --cikti pano/OZET.md [--isabet-dali radar]
"""
from __future__ import annotations

import argparse
import re
from collections import Counter
import json
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta, timezone
from html import escape as esc
from pathlib import Path

from copytrade.canli.telegram import ATLA_TR, KACIRILAN_NEDENLER, kip_adi, tr_isaretli, tr_sayi, tr_yuzde
from copytrade.saglik import durum as saglik_durum, kontrol as saglik_kontrol, ozet_metin as saglik_metin

SAAT_MS = 3_600_000
GUN_MS = 24 * SAAT_MS
KAYIT_GUN = 14                                                                          # pano kayıt penceresi (gün): veri dalı `kayit/` 14 günden eskisini siler (canli_yayimla.sh)
FUNDING_OLAYLARI = ("funding", "funding_gercek")                                       # S-16: sanal kipte `funding`, gerçek kipte `funding_gercek` (HL); ikisi de `funding_usd` ($, + alınan / − ödenen)
RISK_OLAYLARI = ("risk", "dur", "dur_tamam", "mutabakat_alarm", "mutabakat_duzeldi", "kapanis_eksik", "tasfiye", "kuyruk_tasti", "vardiya_boslugu", "vardiya_baslamadi", "telegram_yetkisiz")


def kisa(adres: str) -> str:
    return adres[:8] + "…" if len(adres) > 8 else adres


def yuzde(v: float | None, isaretli: bool = True) -> str:
    """Oran → Türkçe yüzde (B5: OZET.md ve HTML aynı biçim): 0,0125 → '+%1,25'."""
    return "—" if v is None else (tr_yuzde(v) if isaretli else "%" + tr_sayi(v * 100))


def btc_metni(ozet: dict) -> tuple[str, str]:
    """Başarı ölçütü kıyası (31.12: ayda ≥ %4 VE BTC al-tut'tan iyi): motorun `ozet.json` `btc_al_tut_getiri` / `btc_fark` alanları (aynı dönemde BTC al-tut getirisi; fark = getiri − BTC).
    Döner ("BTC al-tut: +%x,x", "fark: +%x,x"); veri yoksa "—"."""
    bt, fk = ozet.get("btc_al_tut_getiri"), ozet.get("btc_fark")
    return ("BTC al-tut: " + ("—" if bt is None else tr_yuzde(float(bt), 1)), "fark: " + ("—" if fk is None else tr_yuzde(float(fk), 1)))


def hedef_metni(ozet: dict) -> tuple[str, str]:
    """F-06: ("aylık eşdeğer: +%x,x", "hedef %4/ay: geçiyor|geçmiyor|—") — motorun `aylik_esdeger` ((1 + R)^(30/gün) − 1), `aylik_hedef`, `hedef_gecer` alanlarından."""
    ay, hd, gec = ozet.get("aylik_esdeger"), ozet.get("aylik_hedef"), ozet.get("hedef_gecer")
    etiket = f"hedef %{tr_sayi(float(hd) * 100, 0)}/ay" if hd is not None else "hedef %4/ay"
    return ("aylık eşdeğer: " + ("—" if ay is None else tr_yuzde(float(ay), 1)), f"{etiket}: " + ("—" if gec is None else ("geçiyor" if gec else "geçmiyor")))


def saha_metni(ozet: dict) -> str:
    """Saha doluluğu (kullanıcı 14.11): "saha x/11" (+ ", uygun aday yok" motor boş yeri dolduramadıysa) · bugünkü kadronun R1'i geçen trader sayısı (`kadro.json` `gecti_sayisi`)."""
    s = f"saha {ozet.get('saha', '—')}/{ozet.get('saha_n', '—')}" + (", uygun aday yok" if ozet.get("saha_eksik_neden") == "uygun_aday_yok" else "")
    return f"{s} · bugün R1'i geçen trader: {ozet.get('r1_gecen') if ozet.get('r1_gecen') is not None else '—'}"


def usd(v: float | None, isaretli: bool = False) -> str:
    return "—" if v is None else (tr_isaretli(v) if isaretli else tr_sayi(v)) + " $"


def gun_str(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).date().isoformat()


def gecmis_guncelle(gecmis: list[dict], ozsermaye: float, simdi_ms: int, tut: int = 15) -> list[dict]:
    """Günde bir nokta: bugünün noktası varsa güncellenir (gün sonu değeri), yoksa eklenir; en çok `tut` gün."""
    gun = gun_str(simdi_ms)
    yeni = [g for g in gecmis if g.get("gun") != gun] + [{"gun": gun, "ozsermaye": float(ozsermaye)}]
    return sorted(yeni, key=lambda g: g["gun"])[-tut:]


def hafta_getirisi(gecmis: list[dict], ozsermaye: float, simdi_ms: int, kasa: float) -> float | None:
    """(şimdiki özsermaye − 7 gün önceki özsermaye) / kasa; 7 gün önceki nokta (en yakın önceki gün) yoksa None."""
    hedef = gun_str(simdi_ms - 7 * GUN_MS)
    onceki = [g for g in gecmis if g["gun"] <= hedef]
    return None if not onceki or kasa <= 0 else (ozsermaye - onceki[-1]["ozsermaye"]) / kasa


def gun_getirisi(oz: float, gun_basi: float | None) -> float | None:
    """S-14/S-17: "bugün" = (özsermaye − UTC gün başı özsermayesi) / gün başı özsermayesi — motorun günlük kayıp tanımıyla aynı payda (`risk.py`); gün başı yoksa None."""
    return None if gun_basi is None or float(gun_basi) <= 0 else (oz - float(gun_basi)) / float(gun_basi)


def zirve_dusus(oz: float, zirve: float | None) -> float | None:
    """Motorun zirveden düşüşü (`risk.py`): (zirve − özsermaye) / zirve; zirve yoksa None. Pano bu tek kaynağı gösterir."""
    return (float(zirve) - oz) / float(zirve) if zirve and float(zirve) > 0 else None


def funding_toplam(kayitlar: list[dict]) -> float:
    """S-16: verilen kayıtlardaki funding toplamı ($; sanal `funding` + gerçek `funding_gercek`)."""
    return sum(float(k.get("funding_usd") or 0.0) for k in kayitlar if k.get("olay") in FUNDING_OLAYLARI)


def kayit_donemi(kayitlar: list[dict]) -> tuple[str, str, int] | None:
    """S-4: kayıtların gerçekten kapsadığı UTC gün aralığı (ilk gün, son gün, farklı gün sayısı); kayıt yoksa None."""
    gunler = sorted({gun_str(int(k["zaman_ms"])) for k in kayitlar if k.get("zaman_ms")})
    return (gunler[0], gunler[-1], len(gunler)) if gunler else None


def donem_etiketi(donem: tuple[str, str, int] | None) -> str:
    """'05.11–08.11 · 4 gün' (UTC gün); kayıt yoksa 'kayıt yok'."""
    if donem is None:
        return "kayıt yok"
    gg = lambda g: f"{g[8:10]}.{g[5:7]}"
    return (gg(donem[0]) if donem[0] == donem[1] else f"{gg(donem[0])}–{gg(donem[1])}") + f" · {donem[2]} gün"


def pencere24(kayitlar: list[dict], simdi_ms: int) -> list[dict]:
    return [k for k in kayitlar if simdi_ms - GUN_MS <= int(k.get("zaman_ms", 0)) <= simdi_ms]


def pano_olustur(ozet: dict, risk: dict, hesap: dict, kayitlar: list[dict], isabetler: list[dict], gecmis: list[dict], simdi_ms: int, donem_seri: dict | None = None,
                 kadro: dict | None = None) -> tuple[str, list[dict]]:
    """Saf fonksiyon. Döner (Markdown, güncel özsermaye geçmişi)."""
    kasa, oz = float(ozet.get("kasa_usd") or 0.0), float(ozet.get("ozsermaye_usd") or 0.0)
    gecmis_yeni = gecmis_guncelle(gecmis, oz, simdi_ms)
    gun_basi, zirve = risk.get("gun_basi"), risk.get("zirve")
    gun_getiri = gun_getirisi(oz, gun_basi)
    dusus = zirve_dusus(oz, zirve)
    hafta = hafta_getirisi(gecmis, oz, simdi_ms, kasa)
    k24 = pencere24(kayitlar, simdi_ms)
    emirler = [k for k in k24 if k.get("olay") == "emir"]
    dolumlar = [k for k in emirler if k.get("durum") in ("dolu", "kismi")]
    kaymalar = sorted(k["kayma_trader"] for k in dolumlar if k.get("kayma_trader") is not None)
    funding24 = funding_toplam(k24)
    ucret24 = sum(float(k.get("ucret") or 0.0) for k in emirler)
    s = [f"# Canlı rapor — {datetime.fromtimestamp(simdi_ms / 1000, UTC):%Y-%m-%d %H:%M} UTC", "",
         f"**Kip** {ozet.get('kip', '—')} · vardiya `{ozet.get('vardiya', '—')}` · saha {ozet.get('saha', '—')}/{ozet.get('saha_n', '—')} (inen {ozet.get('inen', 0)})" + (" · **bekleme vardiyası** (saha boş / kadro bekleniyor)" if ozet.get("bekleme_vardiyasi") else ""), "",
         f"**Saha doluluğu** {saha_metni(ozet)}", "",
         "## Kasa", "",
         "| kasa | özsermaye | gün | hafta | toplam | zirveden düşüş |", "|---|---|---|---|---|---|",
         f"| {usd(kasa)} | {usd(oz)} | {yuzde(gun_getiri)} | {yuzde(hafta)}{'' if hafta is not None else ' (geçmiş < 7 gün)'} | {yuzde(ozet.get('getiri'))} | {yuzde(-dusus if dusus is not None else None)} |", "",
         f"Başarı kıyası (aynı dönemde): toplam {yuzde(ozet.get('getiri'))} · {' · '.join(btc_metni(ozet))} · {' · '.join(hedef_metni(ozet))}", ""]
    # açık pozisyonlar: ozet['acik'] (mark'lı) varsa K/Z ile, yoksa hesap.json'dan giriş fiyatıyla
    s += ["## Açık pozisyonlar", ""]
    acik = ozet.get("acik")
    if acik is None:
        acik = [{"adres": a, "coin": c, "sz": p["sz"], "giris": p["giris"], "mark": None, "usd": abs(p["sz"]) * p["giris"], "kz_usd": None} for a, cs in (hesap.get("poz") or {}).items() for c, p in cs.items()]
    if acik:
        s += ["| trader | coin | yön | $ | K/Z |", "|---|---|---|---|---|"]
        s += [f"| {kisa(p['adres'])} | {p['coin']} | {'L' if p['sz'] > 0 else 'S'} | {usd(p.get('usd'))} | {usd(p.get('kz_usd'), True)} |" for p in sorted(acik, key=lambda p: -(p.get("usd") or 0))]
    else:
        s += ["açık pozisyon yok"]
    s += ["", "## Son 24 saat", "",
          f"- emir {len(emirler)} · dolum {len(dolumlar)} · kayma p50 {yuzde(kaymalar[len(kaymalar) // 2] if kaymalar else None)} / max {yuzde(kaymalar[-1] if kaymalar else None)} (n={len(kaymalar)})",
          f"- funding {usd(funding24, True)} · ücret {usd(ucret24)}", "",
          "_gün = (özsermaye − UTC gün başı özsermayesi) / gün başı (motorun günlük kayıp tanımı); hafta/toplam kasaya göre; zirveden düşüş motorun zirvesine göre._", ""]
    saha = [k for k in k24 if k.get("olay") in ("saha_giris", "saha_dus")]
    s += ["## Saha değişiklikleri (24 sa)", ""] + ([f"- {gun_str(k['zaman_ms'])} {datetime.fromtimestamp(k['zaman_ms'] / 1000, UTC):%H:%M} {'giriş' if k['olay'] == 'saha_giris' else 'çıkış'} {kisa(k['adres'])} — {k.get('neden', '')}" for k in saha] or ["değişiklik yok"])
    riskler = [k for k in k24 if k.get("olay") in RISK_OLAYLARI]
    s += ["", "## Risk olayları (24 sa)", ""] + ([f"- {datetime.fromtimestamp(k['zaman_ms'] / 1000, UTC):%H:%M} `{k['olay']}`" + (f" {k.get('tur') or k.get('neden') or ''}" if (k.get('tur') or k.get('neden')) else "") for k in riskler] or ["olay yok"])
    din = ozet.get("dinleyici") or {}
    bosluk = ", ".join(f"{b.get('dk')} dk" for b in k24 if b.get("olay") == "vardiya_boslugu") or "yok"
    s += ["", "## Vardiya sağlığı", "",
          f"- süre {ozet.get('sure_dk', 0):.0f} dk · WS kopma {din.get('kopma', '—')} / yeniden bağlanma {din.get('yeniden_baglanma', '—')} · boşluk {bosluk} · "
          f"REST 429 {ozet.get('rest_429', '—')}", "",
          "## Seçim isabeti (son 7)", ""]
    if isabetler:
        s += ["| havuz tarihi | pencere | IC | İlk 11 − havuz | İlk 11 − elenen | n (ilk11/havuz/elenen) |", "|---|---|---|---|---|---|"]
        for i in sorted(isabetler, key=lambda x: x["tarih"])[-7:]:
            g = i["gruplar"]
            s.append(f"| {i['tarih']} | {i['pencere_gun']:.1f} gün{'' if i.get('pencere_tam') else ' (kısmi)'}{' ⚠eksik' if i.get('eksik') else ''} | {i['ic'] if i['ic'] is None else format(i['ic'], '+.2f')} | "
                     f"{yuzde(i.get('fark_ilk11_havuz'))} | {yuzde(i.get('fark_ilk11_elenen'))} | {g['ilk11']['n']}/{g['havuz_geri']['n']}/{g['elenen']['n']} |")
    else:
        s += [isabet_yok_metni(ozet)]
    s += donem_md(donem_seri or {}, kadro or {})
    return "\n".join(s) + "\n", gecmis_yeni


TSI = timezone(timedelta(hours=3))

RENKLER = ("#f5a524", "#3ddc84", "#5b9dff", "#ff5d5d", "#b07cff", "#2dd4bf", "#f472b6", "#a3a3a3")


def _tsi(ms: int, bicim: str = "%d.%m %H:%M") -> str:
    return datetime.fromtimestamp(ms / 1000, TSI).strftime(bicim)


# ------------------------------------------------------------------------------------------------------------------------------ dönem boyu (pano 14.11; kaynak durum/donem_seri.json)
def isabet_yok_metni(ozet: dict) -> str:
    """Seçim isabeti henüz yoksa: ilk ölçüm dönem başından 7 gün sonra (isabet 7 gün önceki havuzu ölçer); dönem bilinmiyorsa yalnız açıklama. Sabit tarih yok."""
    from copytrade.canli.motor import donem_ms
    bas = donem_ms(ozet.get("donem"))
    return f"henüz ölçüm yok — ilk ölçüm ≈ {gun_str(bas + 7 * GUN_MS)} (7 gün önceki kadronun sonraki 7 günü)" if bas else "henüz ölçüm yok (isabet 7 gün önceki kadroyu ölçer)"


def slot_ozeti(ds: dict) -> dict:
    """`donem_seri.slotlar` → {trader: [{adres, katman, giris_ms, cikis_ms, net_usd, ...}] (net azalan), katman: {ilk11|yedek|bilinmiyor: {n, net}}, toplam}. Yeni hesap yok: motorun yazdığı netlerin toplamı."""
    slotlar = list(ds.get("slotlar") or [])
    katman: dict[str, dict] = {}
    for r in slotlar:
        k = r.get("katman") if r.get("katman") in ("ilk11", "yedek") else "bilinmiyor"
        d = katman.setdefault(k, {"n": 0, "net": 0.0})
        d["n"] += 1
        d["net"] += float(r.get("net_usd") or 0.0)
    return {"trader": sorted(slotlar, key=lambda r: -float(r.get("net_usd") or 0.0)), "katman": katman, "toplam": sum(float(r.get("net_usd") or 0.0) for r in slotlar)}


def doluluk_ozeti(ds: dict) -> tuple[float | None, float | None, float]:
    """(slot-gün doluluk oranı = Σ sahadaki üye × süre / Σ saha_n × süre, nakitte kalan pay (zaman ağırlıklı), ölçülen süre gün); veri yoksa None."""
    dl = ds.get("doluluk") or {}
    sure, kap = float(dl.get("sure_ms") or 0), float(dl.get("kapasite_ms") or 0)
    return ((float(dl.get("slot_ms") or 0) / kap) if kap > 0 else None, (float(dl.get("nakit_ms") or 0) / sure) if sure > 0 else None, sure / GUN_MS)


def emir_orani(ds: dict) -> tuple[float | None, float | None, dict]:
    """(atlanan oranı = atlanan / (emir + atlanan), yuvarlanan oranı = yuvarlanan / emir, sayaç); veri yoksa None."""
    sy = ds.get("emir_sayac") or {}
    e, a, y = int(sy.get("emir") or 0), int(sy.get("atlanan") or 0), int(sy.get("yuvarlanan") or 0)
    return ((a / (e + a)) if e + a else None, (y / e) if e else None, sy)


def egri_noktalari(ds: dict, hedef_ay: float, simdi_ms: int) -> list[tuple[int, float, float | None, float]]:
    """Dönem eğrisi: [(ms, motor özsermaye $, BTC al-tut $ | None, hedef $)]. İlk nokta dönem başı (= kasa); sonra her UTC gün sonu (bugün: şimdi). BTC al-tut = kasa × BTC / dönem başı BTC;
    hedef = kasa × (1 + `basari_aylik_hedef`)^(gün / 30). Yeni hesap yok: motorun yazdığı gün sonu değerleri."""
    from copytrade.canli.motor import donem_ms
    kasa = float(ds.get("kasa_usd") or 0.0)
    bas = ds.get("bas_ms") or donem_ms(ds.get("donem"))
    gunler = [g for g in ds.get("gunler") or [] if g.get("ozsermaye_usd") is not None]
    if not kasa or bas is None or not gunler:
        return []
    btc0 = ds.get("btc_donem_fiyat")
    hedef = lambda ms: kasa * (1 + hedef_ay) ** (max(ms - bas, 0) / GUN_MS / 30)              # noqa: E731
    nokta = [(int(bas), kasa, kasa if btc0 else None, kasa)]
    for g in gunler:
        ms = min(int(datetime.fromisoformat(g["gun"]).replace(tzinfo=UTC).timestamp() * 1000) + GUN_MS, simdi_ms)
        b = kasa * float(g["btc"]) / float(btc0) if btc0 and g.get("btc") else None
        nokta.append((max(ms, int(bas)), float(g["ozsermaye_usd"]), b, hedef(ms)))
    return nokta


def donem_md(ds: dict, kadro: dict) -> list[str]:
    """OZET.md dönem bölümü (HTML ile aynı kaynak): eğri son noktası, İlk 11 ↔ Yedek katkısı, trader katkısı, doluluk, atlanan/yuvarlanan oranı, radar hunisi."""
    s = ["", "## Dönem (kalıcı seri)", ""]
    if not ds:
        return s + ["— (durum/donem_seri.json yok: dönem kaydı birikince görünür)"]
    nok = egri_noktalari(ds, 0.04, 2 ** 62)
    if nok:
        _, m, b, h = nok[-1]
        s.append(f"- motor {usd(m)} · BTC al-tut {usd(b)} · %4/ay hedef çizgisi {usd(h)}")
    so = slot_ozeti(ds)
    s.append("- katkı: " + " · ".join(f"{KATMAN_AD.get(k, k)} {v['n']} slot {usd(v['net'], True)}" for k, v in sorted(so["katman"].items())) if so["katman"] else "- katkı: — (henüz slot yok)")
    dol, nakit, gun_ = doluluk_ozeti(ds)
    s.append(f"- saha doluluğu {yuzde(dol, False)} · nakitte kalan {yuzde(nakit, False)} ({tr_sayi(gun_, 1)} gün ölçüldü)")
    at, yv, sy = emir_orani(ds)
    s.append(f"- atlanan sinyal {yuzde(at, False)} · yuvarlanan emir {yuzde(yv, False)} (emir {sy.get('emir', 0)}, atlanan {sy.get('atlanan', 0)})")
    hn = kadro.get("huni") or {}
    s.append(f"- radar hunisi: evren {hn.get('evren', '—')} → aday {hn.get('aday', '—')} → ≥{hn.get('islem_esik', 10)} işlem {hn.get('islem_yeterli', '—')} → geçen {hn.get('gecen', '—')}" if hn else "- radar hunisi: — (kadroda `huni` yok)")
    if so["trader"]:
        s += ["", "| trader | katman | giriş | çıkış | net $ |", "|---|---|---|---|---|"]
        s += [f"| {kisa(r['adres'])} | {r.get('katman') or '—'} | {_tsi(int(r['giris_ms']))} | {_tsi(int(r['cikis_ms'])) + ' ' + str(r.get('cikis_neden') or '') if r.get('cikis_ms') else 'sahada'} | {usd(r.get('net_usd'), True)} |"
              for r in so["trader"][:30]]
    return s


def _cizgi(deg: list[float], renk: str, dolgu: bool = True, taban: float | None = None, baz: float | None = None, x_etiket: tuple[str, str] | None = None, birim: str = "$") -> str:
    """Alan/çizgi grafik (inline SVG) + ölçek: en düşük/en yüksek, `baz` kesikli çizgi (ör. 1.000 $ kasa), x ekseni ilk/son zaman etiketi. 2'den az nokta → bilgi yazısı."""
    if len(deg) < 2:
        return '<div class="bos">Veri birikiyor — birkaç tur sonra çizilir</div>'
    ek = [v for v in (taban, baz) if v is not None]
    lo, hi = min([*deg, *ek]), max([*deg, *ek])
    ar = (hi - lo) or 1.0
    y = lambda v: 78 - (v - lo) / ar * 66                       # noqa: E731
    xs = [i * 300 / (len(deg) - 1) for i in range(len(deg))]
    pts = " ".join(f"{x:.1f},{y(v):.1f}" for x, v in zip(xs, deg))
    alan = f'<polygon points="0,80 {pts} 300,80" fill="{renk}" opacity=".16"/>' if dolgu else ""
    baz_cizgi = f'<line x1="0" y1="{y(baz):.1f}" x2="300" y2="{y(baz):.1f}" stroke="#8a8a94" stroke-width="1" stroke-dasharray="4 3" vector-effect="non-scaling-stroke"/>' if baz is not None else ""
    f = (lambda v: tr_sayi(v) + " " + birim) if birim == "$" else (lambda v: tr_sayi(v) + birim)
    x0, x1 = x_etiket or ("", "")
    return (f'<svg viewBox="0 0 300 80" preserveAspectRatio="none" class="gr">{alan}{baz_cizgi}<polyline fill="none" stroke="{renk}" stroke-width="1.8" vector-effect="non-scaling-stroke" points="{pts}"/></svg>'
            f'<div class="ek"><span>{esc(x0)}</span><span>{esc(x1)}</span></div>'
            f'<div class="ek ek2">en düşük {esc(f(lo))} · en yüksek {esc(f(hi))}{" · kesikli çizgi: başlangıç " + esc(f(baz)) if baz is not None else ""}</div>')


KATMAN_AD = {"ilk11": "İlk 11", "yedek": "Yedek", "bilinmiyor": "bilinmiyor"}
VERI_YOK = '<div class="bos">— {}</div>'


def serit(hucreler: list[str], sinif: str = "") -> str:
    """Rakam şeridi: sütun sayısı hücre sayısına göre seçilir (masaüstünde boş kutu kalmasın): telefon 2 (tek sayıda 3), masaüstü 6/4/5/3'ten hücre sayısını bölen ilki (yoksa 4)."""
    n = len(hucreler)
    tel = 2 if n % 2 == 0 else 3
    mas = next((k for k in (6, 4, 5, 3) if n % k == 0), 4)
    return f'<div class="sirit{(" " + sinif) if sinif else ""}" style="--sm:{tel};--sk:{mas}">{"".join(hucreler)}</div>'


def _donem_egri_html(nok: list[tuple[int, float, float | None, float]]) -> str:
    """Dönem eğrisi (inline SVG): motor kasası (turuncu) ↔ BTC al-tut (mavi) ↔ %4/ay hedef (gri kesikli). 2'den az nokta → açıklama."""
    if len(nok) < 2:
        return VERI_YOK.format("dönem eğrisi ilk UTC gün kaydından sonra çizilir")
    x0, x1 = nok[0][0], nok[-1][0]
    deg = [v for n in nok for v in (n[1], n[2], n[3]) if v is not None]
    lo, hi = min(deg), max(deg)
    ar, xa = (hi - lo) or 1.0, (x1 - x0) or 1
    xy = lambda t, v: f"{(t - x0) / xa * 300:.1f},{78 - (v - lo) / ar * 66:.1f}"                # noqa: E731
    cizgi = lambda i, renk, ek="": (f'<polyline fill="none" stroke="{renk}" stroke-width="1.8" vector-effect="non-scaling-stroke"{ek} points="'      # noqa: E731
                                    + " ".join(xy(n[0], n[i]) for n in nok if n[i] is not None) + '"/>')
    btc = cizgi(2, "#5b9dff") if sum(1 for n in nok if n[2] is not None) >= 2 else ""
    son = nok[-1]
    return (f'<svg viewBox="0 0 300 80" preserveAspectRatio="none" class="gr">{cizgi(3, "#8a8a94", ' stroke-dasharray="4 3"')}{btc}{cizgi(1, "#f5a524")}</svg>'
            f'<div class="ek"><span>{_tsi(x0, "%d.%m")}</span><span>{_tsi(x1, "%d.%m %H:%M")}</span></div>'
            f'<div class="ek ek2"><span class="lg"><i style="background:#f5a524"></i>motor {esc(tl2(son[1]))}</span><span class="lg"><i style="background:#5b9dff"></i>BTC al-tut {esc(tl2(son[2]))}</span>'
            f'<span class="lg"><i style="background:#8a8a94"></i>%4/ay hedef {esc(tl2(son[3]))}</span></div>')


def _katki_html(so: dict) -> str:
    """Trader başına dönem katkısı (kapanmış slotlar dahil): giriş/çıkış (TSİ), katman, net K/Z $."""
    if not so["trader"]:
        return VERI_YOK.format("dönemde henüz slot açılmadı")
    satir = "".join(f'<tr><td>{esc(kisa(r["adres"]))}</td><td>{esc(KATMAN_AD.get(r.get("katman") or "bilinmiyor", "—"))}</td><td class="so">{_tsi(int(r["giris_ms"]))}</td>'
                    f'<td class="so">{_tsi(int(r["cikis_ms"])) if r.get("cikis_ms") else "sahada"}</td><td class="sg {"art" if float(r.get("net_usd") or 0) >= 0 else "eks"}">{esc(tl2(r.get("net_usd"), True))}</td></tr>'
                    for r in so["trader"][:40])
    return (f'<div class="tw"><table><tr><th>TRADER</th><th>KATMAN</th><th>GİRİŞ</th><th>ÇIKIŞ</th><th class="sg">NET</th></tr>{satir}</table></div>'
            f'<div class="ha" style="padding:6px 11px">Net = slotun girişten beri K/Z (ücret, funding, açık pozisyon dahil). Toplam {esc(tl2(so["toplam"], True))}.</div>')


def _ilk_yedek_html(so: dict) -> str:
    if not so["katman"]:
        return VERI_YOK.format("henüz slot yok")
    return "".join(f'<div class="s"><b>{esc(KATMAN_AD.get(k, k))}</b> · {v["n"]} slot · <span class="{"art" if v["net"] >= 0 else "eks"}">{esc(tl2(v["net"], True))}</span>'
                   f' <span class="so">(slot başı {esc(tl2(v["net"] / v["n"], True))})</span></div>' for k, v in sorted(so["katman"].items()))


def _gecmis_html(ds: dict) -> str:
    """Giriş/çıkış geçmişi dönem boyu (neden ile; en yeni üstte, en çok 40)."""
    olay = []
    for r in ds.get("slotlar") or []:
        olay.append((int(r["giris_ms"]), f'➕ giriş · {esc(kisa(r["adres"]))} · {esc(str(r.get("giris_neden") or ""))}'))
        if r.get("cikis_ms"):
            olay.append((int(r["cikis_ms"]), f'➖ çıkış · {esc(kisa(r["adres"]))} · {esc(str(r.get("cikis_neden") or ""))}{" (sonuçla)" if r.get("sonuc") else ""}'))
    if not olay:
        return VERI_YOK.format("dönemde giriş/çıkış yok")
    return "".join(f'<div class="s"><span class="so">{_tsi(ms)}</span> {m}</div>' for ms, m in sorted(olay, reverse=True)[:40])


def _huni_html(kadro: dict | None) -> str:
    hn = (kadro or {}).get("huni") or {}
    if not hn:
        return VERI_YOK.format("kadroda huni özeti yok (yeni radar koşusundan sonra görünür)")
    adim = [("Evren", hn.get("evren")), ("Aday", hn.get("aday")), (f"≥{hn.get('islem_esik', 10)} işlem", hn.get("islem_yeterli")), ("R1 geçen", hn.get("gecen")), ("Kadro", hn.get("kadro"))]
    ust = max([int(v or 0) for _, v in adim] + [1])
    cubuk = "".join(f'<div class="s"><span>{esc(ad)} · <b>{"—" if v is None else v}</b></span><div class="ol"><i style="width:{(int(v or 0) / ust * 100):.1f}%"></i></div></div>' for ad, v in adim)
    nd = hn.get("neden") or {}
    top = sum(nd.values()) or 1
    return cubuk + '<div class="ha">Elenme nedenleri</div>' + "".join(f'<div class="s"><b>{n}</b> × {esc(k)} <span class="so">(%{n / top * 100:.0f})</span></div>' for k, n in list(nd.items())[:8])


def _isabet_html(isabetler: list[dict], ozet: dict) -> str:
    if not isabetler:
        return VERI_YOK.format(isabet_yok_metni(ozet))
    satir = "".join(f'<tr><td>{esc(i["tarih"][5:])}</td><td class="sg">{"—" if i.get("ic") is None else format(i["ic"], "+.2f")}</td><td class="sg">{esc(yuzde(i.get("fark_ilk11_havuz")))}</td>'
                    f'<td class="sg">{esc(yuzde(i.get("fark_ilk11_elenen")))}</td></tr>' for i in sorted(isabetler, key=lambda x: x["tarih"])[-7:])
    return (f'<div class="tw"><table><tr><th>HAVUZ</th><th class="sg">IC</th><th class="sg">İLK11−HAVUZ</th><th class="sg">İLK11−ELENEN</th></tr>{satir}</table></div>'
            '<div class="ha" style="padding:6px 11px">Seçilenlerin sonraki 7 gün kopya getirisi ↔ havuz / elenenler (pozitif = seçim işe yarıyor).</div>')


def _cubuk(deg: list[float]) -> str:
    if not deg:
        return '<div class="bos">Günlük çubuklar ilk günün sonunda görünür</div>'
    m = max(abs(v) for v in deg) or 1.0
    w = 300 / max(len(deg), 6)                              # tek çubuk ekranı kaplamasın
    r = "".join(f'<rect x="{i * w + w * .15:.1f}" y="{(40 - max(v, 0) / m * 36):.1f}" width="{w * .7:.1f}" height="{max(abs(v) / m * 36, 1.2):.1f}" fill="{"#3ddc84" if v >= 0 else "#ff5d5d"}"/>' for i, v in enumerate(deg))
    return f'<svg viewBox="0 0 300 80" preserveAspectRatio="none" class="gr"><line x1="0" y1="40" x2="300" y2="40" stroke="#3a3a40" stroke-width=".6"/>{r}</svg>'


BILESEN_AD = (("G", "Güven ayarlı getiri"), ("K", "Kopya getirisi"), ("I1", "Kârlı gün oranı"), ("I2", "Düşüş (az = iyi)"), ("Y", "Yayılma"), ("H", "Hype yakalama"))
ADRES_RE = re.compile(r"0x[0-9a-fA-F]{40}")


def _atlanan_html(k24: list[dict]) -> str:
    """C2: atlanan sinyaller (24 sa) — neden başına sayı. Yalnız `emir_yok` kayıtları (yeni hesap yok). S-13: etiketler Telegram ile TEK sözlükten (`telegram.ATLA_TR`); kaçırılan nedenler işaretlenir."""
    sayim = Counter(str(k.get("neden") or "?") for k in k24 if k.get("olay") == "emir_yok")
    if not sayim:
        return '<div class="bos">Son 24 saatte atlanan sinyal yok</div>'
    toplam = sum(sayim.values())
    return "".join(f'<div class="s"><b>{n}</b> × {esc(ATLA_TR.get(neden, neden))}{" (kaçırılan)" if neden in KACIRILAN_NEDENLER else ""} <span class="so">(%{n / toplam * 100:.0f})</span></div>'
                   for neden, n in sayim.most_common())


def _kapanan_html(kayitlar: list[dict]) -> str:
    """C3: kapanış dolumları (azaltma/kapanış; net = gerçekleşen − ücret): sayı, kazanma oranı, ort. kâr/zarar, kâr faktörü — toplam ve trader başına. `pnl_usd` kaydı olmayan eski emirler sayılmaz."""
    kap = [k for k in kayitlar if k.get("olay") == "emir" and k.get("reduce_only") and k.get("pnl_usd") is not None and k.get("durum") in ("dolu", "kismi")]
    if not kap:
        return '<div class="bos">Kapanış kaydı henüz yok (bu bilgi yeni kayıtlardan birikir)</div>'

    def ozet(satirlar: list[dict]) -> tuple[int, float | None, float | None, float | None, float | None, float]:
        net = [float(k["pnl_usd"]) - float(k.get("ucret") or 0.0) for k in satirlar]
        kaz, kay = [x for x in net if x > 0], [x for x in net if x < 0]
        pf = (sum(kaz) / -sum(kay)) if kay else None
        return len(net), (len(kaz) / len(net)), (sum(kaz) / len(kaz) if kaz else None), (sum(kay) / len(kay) if kay else None), pf, sum(net)
    def satir(ad: str, o: tuple) -> str:
        n, oran, ok, oz_, pf, toplam = o
        return (f'<tr><td>{esc(ad)}</td><td class="sg">{n}</td><td class="sg">{"—" if oran is None else "%" + tr_sayi(oran * 100, 0)}</td><td class="sg art">{esc(tl2(ok))}</td><td class="sg eks">{esc(tl2(oz_))}</td>'
                f'<td class="sg {"art" if toplam >= 0 else "eks"}">{esc(tl2(toplam, True))}</td></tr>'
                f'<tr class="alt"><td colspan="6">kâr faktörü {"—" if pf is None else tr_sayi(pf)}</td></tr>')
    gruplar: dict[str, list[dict]] = {}
    for k in kap:
        gruplar.setdefault(k.get("adres", ""), []).append(k)
    govde = satir("TOPLAM", ozet(kap)) + "".join(satir(kisa(a), ozet(v)) for a, v in sorted(gruplar.items(), key=lambda kv: -sum(float(x["pnl_usd"]) for x in kv[1])))
    return (f'<div class="tw"><table><tr><th>TRADER</th><th class="sg">ADET</th><th class="sg">KAZANMA</th><th class="sg">ORT. KÂR</th><th class="sg">ORT. ZARAR</th><th class="sg">NET</th></tr>{govde}</table></div>'
            '<div class="ha" style="padding:6px 11px">Her kapanış dolumu bir işlem sayılır (kısmi azaltmalar dahil); net = gerçekleşen − ücret. Kâr faktörü = toplam kâr / toplam zarar.</div>')


def tl2(v: float | None, isaretli: bool = False) -> str:
    return "—" if v is None else (tr_isaretli(v) if (isaretli or v < 0) else tr_sayi(v)) + " $"


def pencere_basi(gecmis: list[dict], donem: tuple[str, str, int] | None) -> tuple[float, str] | None:
    """S-4: kayıt penceresinin ilk gününden ÖNCEKİ son günlük özsermaye (`gecmis.json`, gün sonu) = pencere başı özsermaye. Yoksa None: seri pencere içinde başlamış (kayıt budanmamış), net = özsermaye − kasa."""
    if donem is None:
        return None
    once = [g for g in gecmis if g.get("gun") and g["gun"] < donem[0] and g.get("ozsermaye") is not None]
    return (float(once[-1]["ozsermaye"]), once[-1]["gun"]) if once else None


def _maliyet_html(kayitlar: list[dict], oz: float, kasa: float, gecmis: list[dict] | None = None, kip: str = "sanal") -> str:
    """C4: maliyet dökümü (kayıt penceresi, ≤ 14 gün): ücret, kayma (trader fiyatına göre; + maliyet), funding; brüt K/Z = net + maliyet. Kayma zaten dolum fiyatlarında gömülü olduğundan net'e AYRICA eklenmez, brüt tahmininde geri eklenir.
    S-4: net AYNI pencereden: pencere başından önceki günlük özsermaye (`gecmis`) varsa net = özsermaye − o değer; yoksa (seri pencere içinde başladı) net = özsermaye − kasa. Etiket gerçek gün aralığını yazar."""
    donem = kayit_donemi(kayitlar)
    emirler = [k for k in kayitlar if k.get("olay") == "emir" and k.get("durum") in ("dolu", "kismi")]
    ucret = sum(float(k.get("ucret") or 0.0) for k in emirler)
    kayma = sum(float(k["kayma_trader"]) * float(k.get("usd_dolan") or 0.0) for k in emirler if k.get("kayma_trader") is not None)
    funding = funding_toplam(kayitlar)
    bas = pencere_basi(gecmis or [], donem)
    net = oz - (bas[0] if bas else kasa)
    net_ad, net_ipucu = (("Net K/Z (pencere başından)", f"özsermaye − {bas[1][8:10]}.{bas[1][5:7]} gün sonu özsermayesi") if bas else ("Net K/Z (başlangıçtan beri)", "özsermaye − kasa; seri kayıt penceresi içinde başladı"))
    maliyet = ucret + kayma - funding
    brut = net + maliyet
    oran_txt = f"brüt K/Z'nin %{tr_sayi(maliyet / brut * 100, 0)}'i" if brut > 0 else "brüt K/Z ≤ 0 olduğundan oran hesaplanamadı"
    satir = lambda ad, v, ipucu="": f'<tr><td>{esc(ad)}{f"<br><span class=so>{esc(ipucu)}</span>" if ipucu else ""}</td><td class="sg">{esc(tl2(v, True))}</td></tr>'   # noqa: E731
    return ('<div class="tw"><table><tr><th>KALEM</th><th class="sg">TUTAR</th></tr>'
            + satir("Brüt K/Z (maliyet öncesi, tahmini)", brut, "net + toplam maliyet") + satir("− Ücret", -ucret) + satir("− Kayma (trader fiyatına göre)", -kayma, "+ = aleyhe; dolum fiyatında gömülü")
            + satir(f"± Funding ({'HL' if kip == 'gercek' else 'sanal'})", funding, "+ alınan / − ödenen · pencere toplamı") + satir(net_ad, net, net_ipucu)
            + f'</table></div><div class="ha" style="padding:6px 11px">Toplam maliyet {esc(tl2(maliyet))} · {oran_txt}. Kayıt penceresi: {esc(donem_etiketi(donem))} (UTC; en çok {KAYIT_GUN} gün).</div>')


def _maruziyet_html(acik: list[dict], kasa: float, oz: float, kaldirac: float, coin_tavan_oran: float, tavan_usd: float | None = None) -> str:
    """C5: maruziyet — net uzun/kısa, brüt/kasa, teminat/özsermaye (izole kaldıraç), coin başına doluluk (tavan `risk.coin_tavan_usd`; verilmezse kasa × oran)."""
    uzun = sum(q.get("usd") or 0 for q in acik if q["sz"] > 0)
    kisa_ = sum(q.get("usd") or 0 for q in acik if q["sz"] < 0)
    brut = uzun + kisa_
    teminat = brut / kaldirac if kaldirac > 0 else 0.0
    coin: dict[str, float] = {}
    for q in acik:
        coin[q["coin"]] = coin.get(q["coin"], 0.0) + (q.get("usd") or 0)
    tavan = coin_tavan_oran * kasa if tavan_usd is None else float(tavan_usd)
    cubuk = "".join(f'<div class="s"><span>{esc(c)} · {esc(tl2(u))} / {esc(tl2(tavan))}</span><div class="ol"><i style="width:{min(u / tavan * 100, 100):.0f}%;background:{"#ff5d5d" if u > tavan else "var(--tu)"}"></i></div></div>' for c, u in sorted(coin.items(), key=lambda x: -x[1]) if tavan > 0)
    return (f'<div class="iz2"><div class="h"><div class="hb">Net uzun / kısa</div><div class="hd">{esc(tl2(uzun - kisa_, True))}</div><div class="ha">uzun {esc(tl2(uzun))} · kısa {esc(tl2(kisa_))}</div></div>'
            f'<div class="h"><div class="hb">Brüt / kasa</div><div class="hd">%{tr_sayi(brut / kasa * 100, 0) if kasa > 0 else "—"}</div><div class="ha">brüt {esc(tl2(brut))}</div></div>'
            f'<div class="h"><div class="hb">Teminat / özsermaye</div><div class="hd">%{tr_sayi(teminat / oz * 100, 0) if oz > 0 else "—"}</div><div class="ha">teminat ~{esc(tl2(teminat))} ({tr_sayi(kaldirac, 0)}x)</div></div></div>'
            f'<div class="pi"><div class="ha">Coin başına doluluk (tavan: kasanın %{tr_sayi(tavan / kasa * 100 if kasa > 0 else coin_tavan_oran * 100, 0)}\'u)</div>{cubuk}</div>')


def html_olustur(ozet: dict, risk: dict, hesap: dict, kayitlar: list[dict], gecmis: list[dict], simdi_ms: int, kadro: dict | None = None, saha_durum: dict | None = None, hesap_tr: dict | None = None, havuz: dict | None = None, kurallar: dict | None = None,
                 donem_seri: dict | None = None, isabetler: list[dict] | None = None) -> str:
    """Telefonda/bilgisayarda açılan tek dosyalık koyu "terminal" paneli (`pano/index.html`; kullanıcının Cloudflare Workers statik sayfası `sg-pano` `canli-durum` dalının `pano/` klasörünü gösterir, salt okunur): rakam şeridi, özsermaye/düşüş/günlük K-Z grafikleri, pozisyon dağılımı, pozisyon ve işlem tabloları; DÖNEM sekmesi (14.11): dönem eğrisi, trader katkısı, İlk 11 ↔ Yedek, giriş/çıkış geçmişi, doluluk, emir oranları, radar hunisi, seçim isabeti (`donem_seri`, `kadro.huni`, `isabetler`).
    Saf fonksiyon; yeni hesap yok (özet + kayıtlardan yalnız toplama/dizme). Dış kaynak/JS yok; tüm metin HTML kaçışlı."""
    kasa, oz = float(ozet.get("kasa_usd") or 0.0), float(ozet.get("ozsermaye_usd") or 0.0)
    gun_basi, zirve = risk.get("gun_basi"), risk.get("zirve")
    gun = gun_getirisi(oz, gun_basi)                                                                       # S-14/S-17: motorun tanımı (payda gün başı)
    dusus = zirve_dusus(oz, zirve)                                                                         # S-14: motorun zirvesi (risk.json); grafik başlığı da bunu gösterir
    hafta = hafta_getirisi(gecmis, oz, simdi_ms, kasa)
    k24 = pencere24(kayitlar, simdi_ms)
    donem = kayit_donemi(kayitlar)
    emirler = [k for k in k24 if k.get("olay") == "emir"]
    dolum = [k for k in emirler if k.get("durum") in ("dolu", "kismi")]
    kaymalar = [abs(k["kayma_trader"]) * 1e4 for k in dolum if k.get("kayma_trader") is not None]            # mutlak fark (bp)
    kayma_isaretli = sorted(k["kayma_trader"] * 1e4 for k in dolum if k.get("kayma_trader") is not None)      # işaretli fark (bp; + = trader fiyatından kötü)
    kayma_ortanca = (kayma_isaretli[len(kayma_isaretli) // 2] if len(kayma_isaretli) % 2 else (kayma_isaretli[len(kayma_isaretli) // 2 - 1] + kayma_isaretli[len(kayma_isaretli) // 2]) / 2) if kayma_isaretli else None
    funding24, funding_donem = funding_toplam(k24), funding_toplam(kayitlar)
    din = ozet.get("dinleyici") or {}
    veri_ms = int(ozet.get("yazildi_ms") or max([int(k["zaman_ms"]) for k in kayitlar if k.get("olay") == "kapanis" and (k.get("ozet") or {}).get("vardiya") == ozet.get("vardiya")] or [simdi_ms]))   # verinin YAZILDIĞI an (motor ozet.json'u yazarken); yoksa kapanış kaydı / üretim anı
    kip = str(ozet.get("kip", "—"))
    _sg = saglik_kontrol(simdi_ms, ozet, kadro)                                                            # pano dışı ölçümler (Cloudflare) saatlik iş akışında; burada yalnız motor + radar
    saglik_ozeti = ({"SAGLIKLI": "✅ sorun yok", "UYARI": "⚠ uyarı var", "KRITIK": "🚨 acil"}[saglik_durum(_sg)], "".join(f"<div>{esc(ozet_satiri)}</div>" for ozet_satiri in saglik_metin(_sg).split("\n")))

    def tl(v: float | None, isaretli: bool = False) -> str:
        return "—" if v is None else (tr_isaretli(v) if isaretli else tr_sayi(v)) + " $"

    def tyuz(v: float | None) -> str:
        return "—" if v is None else tr_yuzde(v)

    def renk(v: float | None) -> str:
        return "yok" if v is None else ("art" if v >= 0 else "eks")

    def hucre(baslik: str, deger: str, sinif: str = "", alt: str = "") -> str:
        return f'<div class="h"><div class="hb">{esc(baslik)}</div><div class="hd {sinif}">{esc(deger)}</div><div class="ha">{esc(alt)}</div></div>'

    # özsermaye serisi: tur sonu kayıtları (kapanis) + günlük geçmiş + şimdi
    seri = sorted({int(k["zaman_ms"]): float(k["ozet"]["ozsermaye_usd"]) for k in kayitlar if k.get("olay") == "kapanis" and (k.get("ozet") or {}).get("ozsermaye_usd") is not None}.items())
    tur_nokta = sorted({int(k["zaman_ms"]): float(k["ozsermaye_usd"]) for k in kayitlar if k.get("olay") == "tur" and k.get("ozsermaye_usd") is not None}.items())       # ~15 dk'lık tur noktaları (motor `tur` kaydı)
    if len(seri) < 2:
        seri = [(0, float(g["ozsermaye"])) for g in gecmis if g.get("ozsermaye") is not None] + seri
    deg = [v for _, v in seri]
    if not deg or deg[-1] != oz:
        deg.append(oz)
    gseri = [float(g["ozsermaye"]) for g in gecmis if g.get("ozsermaye") is not None]
    bugun_gun = datetime.fromtimestamp(simdi_ms / 1000, UTC).date().isoformat()
    if len(gseri) >= 2:                                    # günlük geçmiş (15 güne kadar) varsa grafikler onunla; yoksa tur sonu kayıtlarıyla
        deg = (gseri[:-1] if gecmis[-1].get("gun") == bugun_gun else gseri) + [oz]
    deg_gun = deg                                          # günlük çubuklar için
    if len(gseri) >= 2 and gun_basi is not None and risk.get("gun") == bugun_gun:
        # S-14: bugünün çubuğu = özsermaye − motorun UTC gün başı özsermayesi ("Bugün" hücresiyle aynı $). Dünün kapanışı (pano gün sonu noktası) yerine gün başı konur; toplam yine özsermaye − kasa.
        onceki = [float(g["ozsermaye"]) for g in gecmis if g.get("ozsermaye") is not None and g.get("gun") != bugun_gun]
        dun = (datetime.fromtimestamp(simdi_ms / 1000, UTC).date() - timedelta(days=1)).isoformat()
        dun_var = any(g.get("gun") == dun and g.get("ozsermaye") is not None for g in gecmis)
        deg_gun = (onceki[:-1] if dun_var else onceki) + [float(gun_basi), oz]
    x_tur = None
    if len(tur_nokta) >= 3:                               # grafikler 15 dk'lık tur noktalarıyla (başlık "tur sonları"); yoksa günlük/tur-sonu yedeği
        deg = [v for _, v in tur_nokta]
        if deg[-1] != oz:
            deg.append(oz)
        x_tur = (_tsi(tur_nokta[0][0], "%d.%m %H:%M"), _tsi(veri_ms, "%d.%m %H:%M"))
    tepe, dd = (kasa if kasa > 0 else (deg[0] if deg else 0.0)), []                  # B1: koşan azami (başlangıç = kasa); gelecekteki zirve geçmişe uygulanmaz
    for v in deg:
        tepe = max(tepe, v)
        dd.append((v / tepe - 1) * 100 if tepe > 0 else 0.0)
    if dd and dusus is not None:
        dd[-1] = -dusus * 100                              # S-14: son nokta (= şimdiki özsermaye) motorun zirvesine göre; önceki noktalar tur kayıtlarından koşan azami
    gunluk: dict[str, float] = {}
    for ms, v in seri:
        if ms:
            gunluk[datetime.fromtimestamp(ms / 1000, UTC).date().isoformat()] = v
    gv = [kasa] + (list(gunluk.values()) if len(gseri) < 2 else deg_gun)                 # B2: ilk gün de çubuk (taban = kasa)
    cubuklar = [b - a for a, b in zip(gv, gv[1:])]
    if len(gseri) >= 2:
        x_et = (".".join(reversed(str(gecmis[0].get("gun", ""))[5:].split("-"))) if gecmis else "", _tsi(veri_ms, "%d.%m"))
    else:
        ilk_ms = next((ms for ms, _ in seri if ms), None)
        x_et = (_tsi(ilk_ms, "%d.%m %H:%M") if ilk_ms else "", _tsi(veri_ms, "%d.%m %H:%M"))

    if x_tur:
        x_et = x_tur
    kz_ozeti = (f'<div class="ek ek2">son gün {esc(tl(cubuklar[-1], True))} · en iyi {esc(tl(max(cubuklar), True))} · en kötü {esc(tl(min(cubuklar), True))} · toplam {esc(tl(sum(cubuklar), True))}</div>' if cubuklar else "")
    acik = ozet.get("acik")
    if acik is None:
        acik = [{"adres": a, "coin": c, "sz": q["sz"], "usd": abs(q["sz"]) * q["giris"], "kz_usd": None} for a, cs in (hesap.get("poz") or {}).items() for c, q in cs.items()]
    acik = sorted(acik, key=lambda q: -(q.get("usd") or 0))
    toplam = sum(q.get("usd") or 0 for q in acik) or 1.0
    coin_usd: dict[str, float] = {}
    for q in acik:
        coin_usd[q["coin"]] = coin_usd.get(q["coin"], 0.0) + (q.get("usd") or 0)
    dilim = sorted(coin_usd.items(), key=lambda x: -x[1])
    cubuk_html = "".join(f'<span style="width:{u / toplam * 100:.2f}%;background:{RENKLER[i % len(RENKLER)]}" title="{esc(c)}"></span>' for i, (c, u) in enumerate(dilim))
    efsane = "".join(f'<span class="lg"><i style="background:{RENKLER[i % len(RENKLER)]}"></i>{esc(c)} {u / toplam * 100:.0f}%</span>' for i, (c, u) in enumerate(dilim[:8]))
    poz_satir = "".join(f'<tr><td><b>{esc(q["coin"])}</b></td><td>{"UZUN" if q["sz"] > 0 else "KISA"}</td><td class="sg">{esc(tl(q.get("usd")))}</td><td class="sg {renk(q.get("kz_usd"))}">{esc(tl(q.get("kz_usd"), True))}</td><td class="so">{esc(kisa(q["adres"]))}</td></tr>' for q in acik) or '<tr><td colspan="5" class="bos">Açık pozisyon yok</td></tr>'
    EYLEM = {"ac": "AÇ", "artir": "ARTIR", "azalt": "AZALT", "kapat": "KAPAT"}
    islem_satir = "".join(f'<tr><td class="so">{_tsi(int(k["zaman_ms"]), "%H:%M")}</td><td><b>{esc(str(k.get("coin", "")))}</b></td><td class="{"art" if k.get("yon") == "B" else "eks"}">{"AL" if k.get("yon") == "B" else "SAT"} · {EYLEM.get(k.get("eylem", ""), "")}</td><td class="sg">{esc(tl(k.get("usd_dolan") or k.get("usd_istenen")))}</td><td class="sg {"eks" if (k.get("kayma_trader") or 0) > 1e-9 else ("art" if (k.get("kayma_trader") or 0) < -1e-9 else "so")}">{(tr_isaretli(k["kayma_trader"] * 1e4, 1) + " bp") if k.get("kayma_trader") is not None else "—"}</td></tr>'
                          for k in sorted(emirler, key=lambda k: -int(k["zaman_ms"]))[:12]) or '<tr><td colspan="5" class="bos">Son 24 saatte emir yok</td></tr>'
    saha = [k for k in k24 if k.get("olay") in ("saha_giris", "saha_dus")]
    saha_html = "".join(f'<div class="s">{"➕ giriş" if k["olay"] == "saha_giris" else "➖ çıkış"} · {_tsi(int(k["zaman_ms"]), "%H:%M")} · {esc(kisa(k["adres"]))} · {esc(str(k.get("neden", "")))}</div>' for k in saha) or '<div class="bos">Trader listesinde değişiklik yok</div>'
    riskler = [k for k in k24 if k.get("olay") in RISK_OLAYLARI]
    risk_html = "".join(f'<div class="s eks">⚠ {_tsi(int(k["zaman_ms"]), "%H:%M")} · {esc(str(k["olay"]))}</div>' for k in riskler) or '<div class="s art">✓ Son 24 saatte risk olayı yok</div>'
    from copytrade.kurallar import load_rules
    kurallar = kurallar or load_rules()
    gk_sinir, dd_sinir = float(kurallar["canli_gunluk_kayip_oran"]), float(kurallar["canli_zirve_dusus_oran"])     # S-14: sınırlar kurallar.yaml'dan (koda sabit değil)
    gun_kayip_pay = min(max(-(gun or 0) / gk_sinir, 0.0), 1.0) * 100 if gk_sinir > 0 else 0.0                    # gun = motor tanımı (payda gün başı)
    dusus_pay = min(max((dusus or 0) / dd_sinir, 0.0), 1.0) * 100 if dd_sinir > 0 else 0.0
    # KADRO sekmesi: ilk 11 + yedekler; tıklayınca "bize ne verdi" mini özeti (yalnız defter/kayıt toplamı; yeni hesap yok)
    uyeler, inenler = ((saha_durum or {}).get("uyeler") or {}), ((saha_durum or {}).get("inen") or {})
    emir_say: dict[str, int] = {}
    son_emir: dict[str, int] = {}
    for k in kayitlar:
        if k.get("olay") == "emir" and k.get("adres"):
            emir_say[k["adres"]] = emir_say.get(k["adres"], 0) + 1
            son_emir[k["adres"]] = max(son_emir.get(k["adres"], 0), int(k.get("zaman_ms", 0)))
    kz_adres: dict[str, float] = {}
    kz_bilinmiyor: set[str] = set()                        # açık K/Z'si (mark) bilinmeyen trader'lar: 0 SAYILMAZ, "—" yazılır
    poz_adres: dict[str, int] = {}
    for q in acik:
        if q.get("kz_usd") is None:
            kz_bilinmiyor.add(q["adres"])
        else:
            kz_adres[q["adres"]] = kz_adres.get(q["adres"], 0.0) + float(q["kz_usd"])
        poz_adres[q["adres"]] = poz_adres.get(q["adres"], 0) + 1
    gerc, ucr, slot_bas, fnd = hesap.get("realize") or {}, hesap.get("ucret") or {}, hesap.get("slot_bas") or {}, hesap.get("funding") or {}
    satirlar = list((kadro or {}).get("satirlar") or [])
    gorulen = {r["adres"] for r in satirlar}
    for ad in [*uyeler, *inenler, *slot_bas]:               # radar listesinde olmayan ama sahada/iniyor/defterde olanlar da görünsün ("KADRO DIŞI")
        if ad not in gorulen:
            gorulen.add(ad)
            satirlar.append({"adres": ad, "sira": 0, "katman": "disi", "form": None, "kopya_getiri_7g": None, "max_kaldirac": None})
    toplam_net, net_eksik = 0.0, False
    gruplar: dict[str, list[str]] = {"SAHADA": [], "BEKLİYOR": [], "İNİYOR": [], "YEDEK": [], "KADRO DIŞI": []}
    for r in satirlar:
        ad = r["adres"]
        durum = "SAHADA" if ad in uyeler else ("İNİYOR" if ad in inenler else ("BEKLİYOR" if r.get("katman") == "ilk11" else ("KADRO DIŞI" if r.get("katman") == "disi" else "YEDEK")))
        net = (float(gerc.get(ad, 0.0)) - float(ucr.get(ad, 0.0)) + float(fnd.get(ad, 0.0)) + kz_adres.get(ad, 0.0)) if (ad in slot_bas and ad not in kz_bilinmiyor) else None
        if ad in slot_bas:
            if net is None:
                net_eksik = True
            else:
                toplam_net += net
        yuzde_s = (net / float(slot_bas[ad])) if net is not None and float(slot_bas.get(ad) or 0) > 0 else None
        giris = (uyeler.get(ad) or {}).get("giris_ms")
        if ad in slot_bas:
            ayrinti = (f'<div class="ms">{"<div><span class=so>Radar listesinde yok</span><br>kadro dışı, pozisyonlar kapanana kadar izleniyor</div>" if r.get("katman") == "disi" else ""}<div><span class="so">Takibe alındı</span><br>{_tsi(int(giris), "%d.%m %H:%M") if giris else "—"}</div>'
                       f'<div><span class="so">Slot (ayrılan para)</span><br>{esc(tl(float(slot_bas[ad])))}</div>'
                       f'<div><span class="so">Bize verdiği (net)</span><br><b class="{renk(net)}">{esc(tl(net, True))}</b> <span class="{renk(yuzde_s)}">{esc(tyuz(yuzde_s))}</span></div>'
                       f'<div><span class="so">Gerçekleşen (ücret, funding dahil) / açık</span><br>{esc(tl(float(gerc.get(ad, 0.0)) - float(ucr.get(ad, 0.0)) + float(fnd.get(ad, 0.0)), True))} / {"—" if ad in kz_bilinmiyor else esc(tl(kz_adres.get(ad, 0.0), True))}</div>'
                       f'<div><span class="so">Emir sayısı</span><br>{emir_say.get(ad, 0)}</div>'
                       f'<div><span class="so">Açık pozisyon</span><br>{poz_adres.get(ad, 0)}</div>'
                       f'<div><span class="so">Son işlem</span><br>{_tsi(son_emir[ad]) if ad in son_emir else "—"}</div>'
                       f'<div><span class="so">Radar 7g kopya getirisi</span><br>{esc(tyuz(r.get("kopya_getiri_7g")))}</div></div>')
        else:
            ayrinti = (f'<div class="ms"><div><span class="so">Durum</span><br>Henüz sahada değil — {"bekleme süresi, korelasyon ya da günlük değişiklik sınırı nedeniyle olabilir" if durum == "BEKLİYOR" else ("radar listesinde yok" if durum == "KADRO DIŞI" else "yedek listede")}</div>'
                       f'<div><span class="so">Radar 7g kopya getirisi</span><br>{esc(tyuz(r.get("kopya_getiri_7g")))}</div>'
                       f'<div><span class="so">Form puanı</span><br>{tr_sayi(float(r.get("form") or 0), 1)} / 100</div>'
                       f'<div><span class="so">Azami kaldıraç</span><br>{tr_sayi(float(r.get("max_kaldirac") or 0), 1)}x</div></div>')
        ek = ""
        hv = (havuz or {}).get(ad) or {}
        if ad in slot_bas:                                                                      # C1: canlı kopya koruması — bizim slot getirimiz ↔ aynı sürede trader'ın hesap getirisi
            hg, hs = (uyeler.get(ad) or {}).get("hesap_giris_usd"), ((hesap_tr or {}).get(ad) or {}).get("deger")
            tr_get = ((float(hs) - float(hg)) / float(hg)) if hg and hs is not None else None
            bizim = (net / float(slot_bas[ad])) if net is not None and float(slot_bas.get(ad) or 0) > 0 else None
            koruma = (bizim / tr_get) if bizim is not None and tr_get is not None and abs(tr_get) >= 0.001 else None
            ek += (f'<div class="ms"><div><span class="so">Bizim slot getirimiz</span><br><b class="{renk(bizim)}">{esc(tyuz(bizim))}</b></div>'
                   f'<div><span class="so">Trader hesap getirisi (aynı sürede)</span><br><b class="{renk(tr_get)}">{esc(tyuz(tr_get)) if tr_get is not None else "— (girişte kaydedilmemiş)"}</b></div>'
                   f'<div><span class="so">Koruma oranı (bizim ÷ trader)</span><br><b>{tr_sayi(koruma) if koruma is not None else "—"}</b></div>'
                   f'<div><span class="so">Radar koruma (R1, 7g)</span><br>{tr_sayi(float(hv["kopya_koruma"])) if hv.get("kopya_koruma") is not None else "—"}</div></div>'
                   '<div class="ha" style="padding:0 4px 8px 30px">Trader getirisi hesap değerinden hesaplanır; para yatırma/çekmeyi de içerir (yaklaşık).</div>')
        yp = hv.get("yatirma_payi")
        if yp is not None:
            ek += f'<div class="ms"><div><span class="so">Net para yatırma payı (7g)</span><br><b class="{"eks" if float(yp) > 0.2 else ""}">{"⚠ " if float(yp) > 0.2 else ""}{esc(tyuz(float(yp)))}</b></div></div>'
        if r.get("bilesenler"):
            ek += '<div class="bil">' + "".join(f'<div class="bl"><span>{esc(ad_)}</span><div class="ol"><i style="width:{min(max(float(r["bilesenler"].get(k_) or 0), 0), 100):.0f}%"></i></div><span>{float(r["bilesenler"].get(k_) or 0):.0f}</span></div>' for k_, ad_ in BILESEN_AD if k_ != "H" or float(kurallar.get("radar_agirlik_h", 0) or 0) > 0) + '</div>'
        if ADRES_RE.fullmatch(ad):
            ek += f'<div class="ms"><div><a class="ln" href="https://app.hyperliquid.xyz/explorer/address/{ad}" target="_blank" rel="noopener noreferrer">Trader sayfasını aç (Hyperliquid) ↗</a></div></div>'
        ayrinti += ek
        rozet = {"SAHADA": "art", "İNİYOR": "eks", "BEKLİYOR": "bk", "YEDEK": "yok", "KADRO DIŞI": "yok"}[durum]
        gruplar[durum].append(f'<details class="kd{" kb" if durum == "BEKLİYOR" else ""}"><summary><span class="sr">{int(r.get("sira", 0)) or "·"}</span><b>{esc(kisa(ad))}</b><span class="rz {rozet}">{durum}</span>'
                       f'<span class="fb"><i style="width:{min(max(float(r.get("form") or 0), 0), 100):.0f}%"></i></span><span class="fm">{f"{float(r['form']):.0f}" if r.get("form") is not None else ""}</span>'
                       f'<span class="nt {renk(net)}">{esc(tl(net, True)) if net is not None else ""}</span></summary>{ayrinti}</details>')
    mut = (f'<div class="mt">Kartların toplamı <b class="{renk(toplam_net)}">{esc(tl(toplam_net, True))}</b> + kapanmış slotlar <b>{esc(tl(float(hesap.get("kapanmis_net") or 0.0), True))}</b> = '
           f'<b>{esc(tl(toplam_net + float(hesap.get("kapanmis_net") or 0.0), True))}</b> (başlangıçtan beri özsermaye farkı {esc(tl(oz - kasa, True))}){" · bazı K/Z bilinmiyor, toplam eksik" if net_eksik else ""}</div>') if slot_bas else ""
    atlanan_html, kapanan_html, maliyet_html = _atlanan_html(k24), _kapanan_html(kayitlar), _maliyet_html(kayitlar, oz, kasa, gecmis, kip)
    from copytrade.canli.risk import coin_tavan_usd
    maruziyet_html = _maruziyet_html(acik, kasa, oz, float(hesap.get("kaldirac") or 3.0), float(kurallar["canli_coin_tavan_oran"]),
                                     coin_tavan_usd(kurallar, kasa) if kasa > 0 else None)
    gk = (saha_durum or {}).get("gun_kadro") or {}
    gk_ms = int(((gk.get("kadro") or {}).get("kosu_ms")) or 0)
    if gk_ms and kadro and kadro.get("kosu_ms"):               # K‑39: motor gün başına İLK kadroyu uygular; pano EN SON kadroyu gösterir — karışmasın
        motor_satiri = (f'Motor bugün <b>{_tsi(gk_ms, "%H:%M")} TSİ</b> kadrosunu uyguluyor' + ("." if int(kadro["kosu_ms"]) == gk_ms else
                        f' (günün ilk kadrosu); aşağıdaki liste en son kadro ({_tsi(int(kadro["kosu_ms"]), "%H:%M")} TSİ) — ikinci kadro saha kararlarını değiştirmez.'))
    else:
        motor_satiri = ""
    kadro_tarih = _tsi(int(kadro["kosu_ms"]), "%d.%m %H:%M") if kadro and kadro.get("kosu_ms") else "—"
    sahada_n = len(gruplar["SAHADA"])
    saha_n = ozet.get("saha_n") or (kadro or {}).get("saha_n") or kurallar.get("radar_saha_max") or "—"           # 14.11: "/11" sabiti yerine sahanın gerçek boyu
    _bas = {"SAHADA": f"SAHADA ({sahada_n}/{saha_n})", "BEKLİYOR": f"BEKLİYOR ({len(gruplar['BEKLİYOR'])})", "İNİYOR": f"İNİYOR ({len(gruplar['İNİYOR'])})",
            "YEDEK": f"YEDEK ({len(gruplar['YEDEK'])})", "KADRO DIŞI": f"KADRO DIŞI ({len(gruplar['KADRO DIŞI'])})"}
    _alt = {"SAHADA": "şu an kopyalanan traderlar", "BEKLİYOR": "kadroda (İlk 11), henüz sahaya çıkmadı — sahaya çıkmayı bekliyor",
            "İNİYOR": "iniyor — yedeğe düşecek", "YEDEK": "", "KADRO DIŞI": "radar listesinde yok"}
    _bos = {"SAHADA": "henüz sahaya çıkan yok"}
    kadro_html = "".join(f'<div class="yb{" yb-bk" if d == "BEKLİYOR" else ""}" data-bolum="{d}">{_bas[d]}' + (f' <span class="so">· {_alt[d]}</span>' if _alt[d] else "") + "</div>"
                         + ("".join(gruplar[d]) or f'<div class="bos">{_bos[d]}</div>') for d in ("SAHADA", "BEKLİYOR", "İNİYOR", "YEDEK", "KADRO DIŞI") if d == "SAHADA" or gruplar[d])
    if not any(gruplar.values()):
        kadro_html += '<div class="bos">Kadro verisi okunamadı</div>'
    kadro_etiket = f"{sahada_n}/{saha_n}"
    ds = donem_seri or {}
    so = slot_ozeti(ds)
    dol, nakit, dol_gun = doluluk_ozeti(ds)
    at_or, yv_or, sy = emir_orani(ds)
    egri = _donem_egri_html(egri_noktalari(ds, float(kurallar.get("basari_aylik_hedef", 0.04)), simdi_ms))
    hafta_goster = hafta is not None and (ozet.get("getiri") is None or abs(hafta - float(ozet["getiri"])) > 0.0005)        # 14.11: <7 gün ya da "Başlangıçtan beri" ile aynıysa gösterilmez
    ust_hucre = [hucre("Özsermaye", tl(oz), "", f"kasa {tr_sayi(kasa, 0)} $"), hucre("Bugün", tyuz(gun), renk(gun), (tl(oz - float(gun_basi), True) + " · UTC gün başına göre") if gun_basi is not None else ""),
                 *([hucre("Bu hafta", tyuz(hafta), renk(hafta), "son 7 gün")] if hafta_goster else []),
                 hucre("Başlangıçtan beri", tyuz(ozet.get("getiri")), renk(ozet.get("getiri")), tl(oz - kasa, True)),
                 hucre("BTC al-tut (aynı dönem)", btc_metni(ozet)[0].removeprefix("BTC al-tut: "), renk(ozet.get("btc_al_tut_getiri")), btc_metni(ozet)[1]),
                 hucre("Aylık eşdeğer", hedef_metni(ozet)[0].removeprefix("aylık eşdeğer: "), renk(ozet.get("aylik_esdeger")), hedef_metni(ozet)[1]),
                 hucre("Zirveden düşüş", tyuz(-dusus if dusus is not None else None), renk(-dusus if dusus is not None else None), f"motor zirvesi {tl(float(zirve))}" if zirve else ""),
                 hucre("Açık pozisyon", str(len(acik)), "", f"brüt {tl(sum(q.get('usd') or 0 for q in acik))}"),
                 hucre("Saha doluluğu", f"{ozet.get('saha', '—')}/{ozet.get('saha_n', saha_n)}", "eks" if ozet.get("saha_eksik_neden") else "",
                       ("uygun aday yok · " if ozet.get("saha_eksik_neden") == "uygun_aday_yok" else "") + "bugün R1'i geçen trader: " + (str(ozet.get("r1_gecen")) if ozet.get("r1_gecen") is not None else "—"))]
    uyari = '<div class="uy">⚠ GERÇEK PARA</div>' if kip == "gercek" else ""
    return f"""<!doctype html>
<html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex"><meta name="color-scheme" content="dark">
<title>Copy Trade Panosu</title>
<style>
:root{{--bg:#0a0a0b;--k:#111113;--cz:#25252a;--y:#e9e9ee;--so:#8a8a94;--tu:#f5a524;--art:#3ddc84;--eks:#ff5d5d;--bk:#f5d90a}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--y);font:13px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;padding:12px}}
.ust{{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:10px}}.lg0{{background:var(--tu);color:#000;font-weight:800;padding:2px 7px;border-radius:3px}}
.ust b{{font-size:15px;letter-spacing:.05em}}.so,.ha{{color:var(--so)}}.rozet{{border:1px solid var(--cz);border-radius:3px;padding:1px 8px;color:var(--tu);font-size:11px}}
.sirit{{display:grid;grid-template-columns:repeat(var(--sm,2),minmax(0,1fr));gap:1px;background:var(--cz);border:1px solid var(--cz);margin-bottom:8px}}
.h{{background:var(--k);padding:8px 9px}}.hb{{font-size:10px;letter-spacing:.09em;color:var(--so);text-transform:uppercase}}.hd{{font-size:17px;font-weight:700;margin:2px 0}}.ha{{font-size:11px}}
.rz.bk{{color:var(--bk);border-color:var(--bk)}}.kd.kb{{box-shadow:inset 3px 0 0 var(--bk)}}.kd.kb summary{{padding-left:9px}}.yb.yb-bk{{color:var(--bk)}}.art{{color:var(--art)}}.eks{{color:var(--eks)}}.yok{{color:var(--so)}}
.izgara{{display:grid;grid-template-columns:1fr;gap:8px}}.sag{{display:contents}}.p{{background:var(--k);border:1px solid var(--cz);min-width:0}}
.pb{{font-size:10px;letter-spacing:.09em;color:var(--tu);text-transform:uppercase;padding:8px 11px;border-bottom:1px solid var(--cz);display:flex;justify-content:space-between}}.pb span{{color:var(--so)}}
.pi{{padding:10px 11px}}.gr{{width:100%;height:110px;display:block}}.ek{{display:flex;justify-content:space-between;gap:8px;font-size:10px;color:var(--so);margin-top:4px}}.ek2{{justify-content:center;text-align:center}}.bos{{color:var(--so);padding:14px 4px;font-size:12px}}
table{{width:100%;border-collapse:collapse;font-size:12px}}td,th{{padding:6px 8px;border-bottom:1px solid #1c1c21;text-align:left;white-space:nowrap}}th{{font-size:10px;color:var(--so);letter-spacing:.08em}}.sg{{text-align:right}}tr:last-child td{{border:0}}tr.alt td{{font-size:10px;color:var(--so);padding:0 8px 5px;white-space:normal}}
.tw{{overflow-x:auto}}.dg{{display:flex;height:16px;border-radius:3px;overflow:hidden;background:#1c1c21}}.dg span{{display:block;height:100%}}
.lg{{display:inline-block;margin:6px 12px 0 0;font-size:11px;color:var(--so)}}.lg i{{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:5px}}
.s{{padding:4px 0;font-size:12px}}.ic div{{padding:5px 0 5px 12px;border-bottom:1px solid #1c1c21;position:relative}}.ic div:before{{content:"›";color:var(--tu);position:absolute;left:0}}
.ol{{height:7px;background:#1c1c21;border-radius:4px;margin:4px 0 9px;overflow:hidden}}.ol i{{display:block;height:100%;background:var(--tu)}}.uy{{background:var(--eks);color:#fff;font-weight:800;padding:6px 10px;margin-bottom:8px;border-radius:3px}}
.tabs{{display:flex;gap:2px;margin:0 0 8px;border-bottom:1px solid var(--cz);overflow-x:auto}}.tabs label{{padding:9px 13px;font-size:11px;letter-spacing:.09em;color:var(--so);cursor:pointer;white-space:nowrap;border-bottom:2px solid transparent}}.tabs em{{font-style:normal;background:#1c1c21;border-radius:9px;padding:0 6px;margin-left:4px;color:var(--y)}}
input[name=t]{{position:absolute;opacity:0;pointer-events:none}}.sekmeler section{{display:none}}
#t1:checked~.tabs label[for=t1],#t2:checked~.tabs label[for=t2],#t3:checked~.tabs label[for=t3],#t4:checked~.tabs label[for=t4],#t5:checked~.tabs label[for=t5],#t6:checked~.tabs label[for=t6]{{color:var(--tu);border-bottom-color:var(--tu)}}
#t1:checked~.sekmeler .n1,#t2:checked~.sekmeler .n2,#t3:checked~.sekmeler .n3,#t4:checked~.sekmeler .n4,#t5:checked~.sekmeler .n5,#t6:checked~.sekmeler .n6{{display:grid}}
.kd{{border-bottom:1px solid #1c1c21}}.kd summary{{display:grid;grid-template-columns:22px 1fr auto 46px 24px auto;gap:8px;align-items:center;padding:9px 2px;cursor:pointer;list-style:none}}.kd summary::-webkit-details-marker{{display:none}}
.sr{{color:var(--so)}}.rz{{font-size:10px;border:1px solid var(--cz);border-radius:3px;padding:0 6px;letter-spacing:.05em}}.fb{{height:6px;background:#1c1c21;border-radius:3px;overflow:hidden}}.fb i{{display:block;height:100%;background:var(--tu)}}.fm{{text-align:right;color:var(--so)}}.nt{{text-align:right;min-width:64px}}
.ms{{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;padding:4px 4px 12px 30px;font-size:12px}}.iz2{{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--cz)}}.bil{{padding:2px 4px 8px 30px}}.bl{{display:grid;grid-template-columns:130px 1fr 28px;gap:8px;align-items:center;font-size:11px;color:var(--so)}}.bl .ol{{margin:5px 0}}.ln{{color:var(--tu)}}.mt{{margin-top:12px;padding:8px;background:#0e0e10;border:1px solid var(--cz);font-size:12px;color:var(--so)}}.yb{{margin:12px 0 2px;font-size:10px;letter-spacing:.1em;color:var(--tu)}}
@media(min-width:900px){{.ms{{grid-template-columns:repeat(4,1fr)}}}}
@media(min-width:900px){{body{{padding:18px;max-width:1280px;margin:auto}}.sirit{{grid-template-columns:repeat(var(--sk,4),minmax(0,1fr))}}.hd{{font-size:20px}}.izgara{{grid-template-columns:repeat(3,1fr)}}.sag{{display:grid;gap:8px;grid-column:3;grid-row:1 / span 2;align-content:start}}.g2{{grid-column:span 2}}.g3{{grid-column:span 3}}}}
</style></head><body>
<div class="ust"><div><span class="lg0">CT</span> <b>COPY TRADE PANOSU</b></div><div><span class="rozet">{esc(kip_adi(kip))}</span> <span class="so">veri {_tsi(veri_ms, "%d.%m.%Y %H:%M")} TSİ · ~15 dakikada bir yenilenir</span></div></div><div id="bayat" data-ms="{veri_ms}" class="uy" style="display:none">⚠ VERİ BAYAT: son güncelleme 1 saatten eski, sistem durmuş olabilir</div>{uyari}
{serit(ust_hucre)}
<input type="radio" name="t" id="t1" checked><input type="radio" name="t" id="t2"><input type="radio" name="t" id="t3"><input type="radio" name="t" id="t4"><input type="radio" name="t" id="t5"><input type="radio" name="t" id="t6">
<div class="tabs"><label for="t1">ÖZET</label><label for="t6">DÖNEM</label><label for="t5">KADRO <em>{kadro_etiket}</em></label><label for="t2">POZİSYON <em>{len(acik)}</em></label><label for="t3">İŞLEMLER <em>{len(emirler)}</em></label><label for="t4">RİSK</label></div>
<div class="sekmeler">
<section class="n1 izgara">
<div class="p g2"><div class="pb">Özsermaye (tur sonları) <span>{esc(tl(oz))}</span></div><div class="pi">{_cizgi(deg, "#f5a524", baz=kasa if kasa > 0 else None, x_etiket=x_et)}</div></div>
<div class="sag">
<div class="p"><div class="pb">Günlük net K/Z (UTC gün) <span>{esc(tl(cubuklar[-1], True)) if cubuklar else "—"}</span></div><div class="pi">{_cubuk(cubuklar)}{kz_ozeti}</div></div>
<div class="p"><div class="pb">Sağlık <span>{esc(saglik_ozeti[0])}</span></div><div class="pi ic">{saglik_ozeti[1]}</div></div>
<div class="p"><div class="pb">Risk payı <span>sınıra göre</span></div><div class="pi"><div class="ha">Günlük kayıp {esc(yuzde(max(-(gun or 0.0), 0.0), False))} (sınır %{tr_sayi(gk_sinir * 100, 0)}; UTC gün başı özsermayesine göre, motorun freni)</div><div class="ol"><i style="width:{gun_kayip_pay:.0f}%"></i></div><div class="ha">Zirveden düşüş {esc(yuzde(dusus, False))} (sınır %{tr_sayi(dd_sinir * 100, 0)}; motorun zirvesine göre)</div><div class="ol"><i style="width:{dusus_pay:.0f}%"></i></div>{risk_html}</div></div>
</div>
<div class="p g2"><div class="pb">Dönem eğrisi <span>motor ↔ BTC al-tut ↔ %4/ay hedef · UTC gün sonları</span></div><div class="pi">{egri}</div></div>
</section>
<section class="n6 izgara">
<div class="p g3"><div class="pb">Trader katkısı <span>dönem boyu · kapanmış slotlar dahil</span></div>{_katki_html(so)}</div>
<div class="p"><div class="pb">Seçim isabeti <span>son 7 ölçüm</span></div>{_isabet_html(isabetler or [], ozet)}</div>
<div class="p"><div class="pb">İlk 11 ↔ Yedek <span>dönem katkısı</span></div><div class="pi">{_ilk_yedek_html(so)}</div></div>
<div class="p"><div class="pb">Saha doluluğu <span>dönem boyu</span></div><div class="pi">{'<div class="s">slot-gün doluluk <b>' + esc(yuzde(dol, False)) + '</b> · nakitte kalan <b>' + esc(yuzde(nakit, False)) + '</b></div><div class="ha">' + tr_sayi(dol_gun, 1) + ' gün ölçüldü (motorun çalıştığı süre); nakit = 1 − brüt pozisyon / özsermaye, zaman ağırlıklı</div>' if dol is not None else VERI_YOK.format("doluluk kaydı birikiyor")}</div></div>
<div class="p"><div class="pb">Emir oranları <span>dönem boyu</span></div><div class="pi">{'<div class="s">atlanan sinyal <b>' + esc(yuzde(at_or, False)) + '</b> · yuvarlanan emir <b>' + esc(yuzde(yv_or, False)) + '</b></div><div class="ha">emir ' + str(sy.get("emir", 0)) + ' · atlanan ' + str(sy.get("atlanan", 0)) + ' · yuvarlanan ' + str(sy.get("yuvarlanan", 0)) + '</div>' if at_or is not None else VERI_YOK.format("dönemde henüz sinyal yok")}</div></div>
<div class="p g2"><div class="pb">Giriş / çıkış geçmişi <span>dönem boyu · neden</span></div><div class="pi">{_gecmis_html(ds)}</div></div>
<div class="p"><div class="pb">Radar hunisi <span>son kadro</span></div><div class="pi">{_huni_html(kadro)}</div></div>
</section>
<section class="n2 izgara">
<div class="p g2"><div class="pb">Açık pozisyonlar <span>{len(acik)} adet</span></div><div class="tw"><table><tr><th>COİN</th><th>YÖN</th><th class="sg">TUTAR</th><th class="sg">K/Z</th><th>TRADER</th></tr>{poz_satir}</table></div></div>
<div class="p"><div class="pb">Para dağılımı <span>coin başına</span></div><div class="pi"><div class="dg">{cubuk_html}</div>{efsane}</div></div>
<div class="p g3"><div class="pb">Maruziyet <span>net / brüt / teminat / coin tavanı</span></div>{maruziyet_html}</div>
</section>
<section class="n3 izgara">
{serit([hucre("Emir (24 sa)", str(len(emirler)), "", f"dolum {len(dolum)}"), hucre("Ortanca fark (bp)", f"{tr_sayi(kayma_ortanca, 1)} bp" if kayma_ortanca is not None else "—", "", f"ort. mutlak {tr_sayi(sum(kaymalar) / len(kaymalar), 1)} bp · trader fiyatına göre" if kaymalar else "trader fiyatına göre"), hucre("Funding (24 sa)", tl(funding24, True), renk(funding24), f"{'HL' if kip == 'gercek' else 'sanal'} · pencere toplamı {tl(funding_donem, True)}"), hucre("Takipte", f"{ozet.get('saha', '—')}/{ozet.get('saha_n', saha_n)}", "", "trader")], "g3")}
<div class="p g2"><div class="pb">Son işlemler <span>fark: + aleyhe, − lehe</span></div><div class="tw"><table><tr><th>SAAT</th><th>COİN</th><th>YÖN</th><th class="sg">TUTAR</th><th class="sg">FARK</th></tr>{islem_satir}</table></div></div>
<div class="p"><div class="pb">Trader değişiklikleri <span>24 sa</span></div><div class="pi">{saha_html}</div></div>
<div class="p"><div class="pb">Atlanan sinyaller <span>24 sa · neden başına</span></div><div class="pi">{atlanan_html}</div></div>
<div class="p g2"><div class="pb">Kapanan işlemler <span>{esc(donem_etiketi(donem))} (UTC)</span></div>{kapanan_html}</div>
<div class="p g3"><div class="pb">Maliyet dökümü <span>ücret · kayma · funding</span></div>{maliyet_html}</div>
</section>
<section class="n5 izgara">
<div class="p g3"><div class="pb">Takip edilen ilk 11 ve yedekler <span>radar {kadro_tarih} TSİ · dokun → bize ne verdi</span></div><div class="pi kl">{f'<div class="mt" style="margin:0 0 10px">{motor_satiri}</div>' if motor_satiri else ""}{kadro_html}{mut}</div></div>
</section>
<section class="n4 izgara">
{serit([hucre("WS kopma", str(din.get("kopma", "—")), "", "bu vardiyada"), hucre("REST 429", str(ozet.get("rest_429", "—")), "", "hız sınırı"), hucre("Vardiya süresi", f"{tr_sayi(float(ozet.get('sure_dk') or 0) / 60, 1)} sa", "", "son tur"), hucre("Özsermaye zirvesi", tl(float(zirve)) if zirve else "—", "", "")], "g3")}
<div class="p g2"><div class="pb">Zirveden düşüş (tur sonları) <span>{tr_yuzde(dd[-1] / 100)} · motor</span></div><div class="pi">{_cizgi(dd, "#ff5d5d", taban=0.0, x_etiket=x_et, birim="%")}</div></div>
<div class="p"><div class="pb">Risk olayları <span>24 sa</span></div><div class="pi">{risk_html}</div></div>
</section>
</div>
<div class="so" style="margin:16px 0 4px;font-size:11px">Sanal kip: gerçek para yok. Veriler Hyperliquid halka açık verisidir. Saatler TSİ; "bugün" UTC gün başından (03:00 TSİ) itibaren sayılır.</div>
<script>(function(){{var e=document.getElementById("bayat");if(!e)return;function k(){{e.style.display=Date.now()-Number(e.dataset.ms)>3600*1000?"block":"none"}}k();setInterval(k,60000);document.addEventListener("visibilitychange",function(){{if(!document.hidden)k()}})}})()</script>
</body></html>
"""


# ------------------------------------------------------------------------------------------------------------------------------ CLI
def _json(yol: Path) -> dict:
    return json.loads(yol.read_text(encoding="utf-8")) if yol.is_file() else {}


def kayitlari_oku(dizin: Path, gun: int = KAYIT_GUN) -> list[dict]:
    """Son `gun` günlük `kayit/<tarih>.jsonl` (S-4: varsayılan 14 = veri dalının tuttuğu pencere; maliyet ve kapanan işlemler bunun tamamını okur, 24 sa bölümleri ayrıca süzer)."""
    cikti: list[dict] = []
    for f in sorted(dizin.glob("*.jsonl"))[-gun:]:
        for ham in f.read_text(encoding="utf-8").splitlines():
            try:
                cikti.append(json.loads(ham))
            except ValueError:
                continue
    return cikti


def isabetleri_oku(dal: str | None, son: int = 7) -> list[dict]:
    """Veri dalından (`origin/<dal>`) en son `son` `isabet.json`."""
    if not dal:
        return []
    ls = subprocess.run(["git", "ls-tree", "-r", "--name-only", f"origin/{dal}"], capture_output=True, text=True)
    yollar = sorted(y for y in ls.stdout.splitlines() if y.startswith("radar/") and y.endswith("/isabet.json"))[-son:]
    cikti = []
    for y in yollar:
        s = subprocess.run(["git", "show", f"origin/{dal}:{y}"], capture_output=True, text=True)
        if s.returncode == 0:
            cikti.append(json.loads(s.stdout))
    return cikti


def kadro_oku(dal: str | None) -> dict | None:
    """Veri dalından (`origin/<dal>`) güncel `radar/son/kadro.json`; yoksa None."""
    if not dal:
        return None
    s = subprocess.run(["git", "show", f"origin/{dal}:radar/son/kadro.json"], capture_output=True, text=True)
    return json.loads(s.stdout) if s.returncode == 0 and s.stdout.strip() else None


def havuz_oku(dal: str | None, kadro: dict | None) -> dict[str, dict]:
    """Kadronun koşu gününün `radar/<tarih>/havuz.json`'u (adres → satır; yalnız pano alanları: yatirma_payi, kopya_koruma). Yoksa {}."""
    if not dal or not kadro or not kadro.get("kosu_ms"):
        return {}
    gun_ = datetime.fromtimestamp(int(kadro["kosu_ms"]) / 1000, UTC).date().isoformat()
    s = subprocess.run(["git", "show", f"origin/{dal}:radar/{gun_}/havuz.json"], capture_output=True, text=True)
    if s.returncode != 0 or not s.stdout.strip():
        return {}
    return {r["adres"]: {k: r.get(k) for k in ("yatirma_payi", "kopya_koruma")} for r in json.loads(s.stdout).get("satirlar", []) if r.get("adres")}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--durum", type=Path, default=Path("durum"))
    ap.add_argument("--kayit", type=Path, default=Path("kayit"))
    ap.add_argument("--gecmis", type=Path, default=Path("pano/gecmis.json"))
    ap.add_argument("--cikti", type=Path, default=Path("pano/OZET.md"))
    ap.add_argument("--vardiya", default=None, help="bu vardiyanın kimliği; `durum/ozet.json` başka vardiyadansa (bayat) pano YAZILMAZ")
    ap.add_argument("--html", type=Path, default=None, help="telefon sayfası (pano/index.html) da yazılır; kullanıcı Cloudflare Workers statik sayfasıyla (`sg-pano`) gösterir")
    ap.add_argument("--isabet-dali", default=None, help="isabet.json okunan veri dalı (radar | radar-deneme); yoksa isabet bölümü 'ilk ölçüm' yazar")
    args = ap.parse_args(argv)
    ozet = _json(args.durum / "ozet.json")
    if not ozet:
        print("pano: durum/ozet.json yok; yazılmadı", file=sys.stderr)
        return 0
    if args.vardiya and str(ozet.get("vardiya")) != str(args.vardiya):
        print(f"pano: durum/ozet.json başka vardiyadan ({ozet.get('vardiya')} ≠ {args.vardiya}); bayat veri ile pano yazılmadı", file=sys.stderr)
        return 0
    gecmis = json.loads(args.gecmis.read_text(encoding="utf-8")) if args.gecmis.is_file() else []
    kayitlar = kayitlari_oku(args.kayit)
    isabetler, ds, kadro = isabetleri_oku(args.isabet_dali), _json(args.durum / "donem_seri.json"), kadro_oku(args.isabet_dali)
    md, yeni = pano_olustur(ozet, _json(args.durum / "risk.json"), _json(args.durum / "hesap.json"), kayitlar, isabetler, gecmis, int(time.time() * 1000), ds, kadro)
    args.cikti.parent.mkdir(parents=True, exist_ok=True)
    args.cikti.write_text(md, encoding="utf-8")
    args.gecmis.write_text(json.dumps(yeni, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if args.html:
        args.html.write_text(html_olustur(ozet, _json(args.durum / "risk.json"), _json(args.durum / "hesap.json"), kayitlar, yeni, int(time.time() * 1000), kadro, _json(args.durum / "saha.json"), _json(args.durum / "motor.json").get("hesap_tr"), havuz_oku(args.isabet_dali, kadro),
                                               donem_seri=ds, isabetler=isabetler), encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
