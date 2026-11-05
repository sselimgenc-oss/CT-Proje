"""Günlük rapor (T6 §3, K‑37): `pano/OZET.md` — telefondan GitHub'da okunan Markdown özeti. `canli-durum` dalında her vardiya sonunda güncellenir.

Kural 7: YENİ HESAP YOK. Yalnız mevcut durum/kayıt dosyalarındaki sayıları biçimler (`ozet.json`, `risk.json`, `kayit/*.jsonl`) ve basit istatistikler (sayı, toplam, medyan) alır;
getiri/özsermaye motorun yazdığı değerlerdir. Haftalık getiri için günlük özsermaye geçmişi (`pano/gecmis.json`, günde bir nokta, son 15 gün) tutulur.

Birimler: oranlar yüzde olarak gösterilir (0,012 → %1,20); $ kasa ölçeğinde (`canli_kasa_usd`); saatler UTC (belirtilir); kayma = (dolum − trader fiyatı) / trader fiyatı, ALEYHE pozitif.

    python -m copytrade.canli.pano --durum durum --kayit kayit --gecmis pano/gecmis.json --cikti pano/OZET.md [--isabet-dali radar]
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta, timezone
from html import escape as esc
from pathlib import Path

from copytrade.canli.telegram import kip_adi, tr_isaretli, tr_sayi, tr_yuzde

SAAT_MS = 3_600_000
GUN_MS = 24 * SAAT_MS
RISK_OLAYLARI = ("risk", "dur", "dur_tamam", "mutabakat_alarm", "mutabakat_duzeldi", "kapanis_eksik", "tasfiye", "kuyruk_tasti", "vardiya_boslugu", "vardiya_baslamadi", "telegram_yetkisiz")


def kisa(adres: str) -> str:
    return adres[:8] + "…" if len(adres) > 8 else adres


def yuzde(v: float | None, isaretli: bool = True) -> str:
    return "—" if v is None else f"{v * 100:{'+' if isaretli else ''}.2f}%"


def usd(v: float | None, isaretli: bool = False) -> str:
    return "—" if v is None else f"{v:{'+' if isaretli else ''},.2f} $"


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


def pencere24(kayitlar: list[dict], simdi_ms: int) -> list[dict]:
    return [k for k in kayitlar if simdi_ms - GUN_MS <= int(k.get("zaman_ms", 0)) <= simdi_ms]


def pano_olustur(ozet: dict, risk: dict, hesap: dict, kayitlar: list[dict], isabetler: list[dict], gecmis: list[dict], simdi_ms: int) -> tuple[str, list[dict]]:
    """Saf fonksiyon. Döner (Markdown, güncel özsermaye geçmişi)."""
    kasa, oz = float(ozet.get("kasa_usd") or 0.0), float(ozet.get("ozsermaye_usd") or 0.0)
    gecmis_yeni = gecmis_guncelle(gecmis, oz, simdi_ms)
    gun_basi, zirve = risk.get("gun_basi"), risk.get("zirve")
    gun_getiri = (oz - float(gun_basi)) / kasa if gun_basi is not None and kasa > 0 else None
    dusus = (float(zirve) - oz) / float(zirve) if zirve and float(zirve) > 0 else None
    hafta = hafta_getirisi(gecmis, oz, simdi_ms, kasa)
    k24 = pencere24(kayitlar, simdi_ms)
    emirler = [k for k in k24 if k.get("olay") == "emir"]
    dolumlar = [k for k in emirler if k.get("durum") in ("dolu", "kismi")]
    kaymalar = sorted(k["kayma_trader"] for k in dolumlar if k.get("kayma_trader") is not None)
    funding24 = sum(float(k.get("funding_usd") or 0.0) for k in k24 if k.get("olay") == "funding")
    ucret24 = sum(float(k.get("ucret") or 0.0) for k in emirler)
    s = [f"# Canlı rapor — {datetime.fromtimestamp(simdi_ms / 1000, UTC):%Y-%m-%d %H:%M} UTC", "",
         f"**Kip** {ozet.get('kip', '—')} · vardiya `{ozet.get('vardiya', '—')}` · saha {ozet.get('saha', '—')}/{ozet.get('saha_n', '—')} (inen {ozet.get('inen', 0)})", "",
         "## Kasa", "",
         "| kasa | özsermaye | gün | hafta | toplam | zirveden düşüş |", "|---|---|---|---|---|---|",
         f"| {usd(kasa)} | {usd(oz)} | {yuzde(gun_getiri)} | {yuzde(hafta)}{'' if hafta is not None else ' (geçmiş < 7 gün)'} | {yuzde(ozet.get('getiri'))} | {yuzde(-dusus if dusus is not None else None)} |", ""]
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
          f"- funding {usd(funding24, True)} · ücret {usd(ucret24)}", ""]
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
        s += ["ilk ölçüm 2026-11-12"]
    return "\n".join(s) + "\n", gecmis_yeni


TSI = timezone(timedelta(hours=3))
RENKLER = ("#f5a524", "#3ddc84", "#5b9dff", "#ff5d5d", "#b07cff", "#2dd4bf", "#f472b6", "#a3a3a3")


def _tsi(ms: int, bicim: str = "%d.%m %H:%M") -> str:
    return datetime.fromtimestamp(ms / 1000, TSI).strftime(bicim)


def _cizgi(deg: list[float], renk: str, dolgu: bool = True, taban: float | None = None) -> str:
    """Alan/çizgi grafik (inline SVG). 2'den az nokta → bilgi yazısı."""
    if len(deg) < 2:
        return '<div class="bos">Veri birikiyor — birkaç tur sonra çizilir</div>'
    lo = min(deg) if taban is None else min(min(deg), taban)
    hi = max(deg) if taban is None else max(max(deg), taban)
    ar = (hi - lo) or 1.0
    xs = [i * 300 / (len(deg) - 1) for i in range(len(deg))]
    ys = [78 - (v - lo) / ar * 66 for v in deg]
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    alan = f'<polygon points="0,80 {pts} 300,80" fill="{renk}" opacity=".16"/>' if dolgu else ""
    return f'<svg viewBox="0 0 300 80" preserveAspectRatio="none" class="gr">{alan}<polyline fill="none" stroke="{renk}" stroke-width="1.8" vector-effect="non-scaling-stroke" points="{pts}"/></svg>'


def _cubuk(deg: list[float]) -> str:
    if not deg:
        return '<div class="bos">Günlük çubuklar ilk günün sonunda görünür</div>'
    m = max(abs(v) for v in deg) or 1.0
    w = 300 / len(deg)
    r = "".join(f'<rect x="{i * w + w * .15:.1f}" y="{(40 - max(v, 0) / m * 36):.1f}" width="{w * .7:.1f}" height="{max(abs(v) / m * 36, 1.2):.1f}" fill="{"#3ddc84" if v >= 0 else "#ff5d5d"}"/>' for i, v in enumerate(deg))
    return f'<svg viewBox="0 0 300 80" preserveAspectRatio="none" class="gr"><line x1="0" y1="40" x2="300" y2="40" stroke="#3a3a40" stroke-width=".6"/>{r}</svg>'


def html_olustur(ozet: dict, risk: dict, hesap: dict, kayitlar: list[dict], gecmis: list[dict], simdi_ms: int, kadro: dict | None = None, saha_durum: dict | None = None) -> str:
    """Telefonda/bilgisayarda açılan tek dosyalık koyu "terminal" paneli (Cloudflare `pano/index.html`): rakam şeridi, özsermaye/düşüş/günlük K-Z grafikleri, pozisyon dağılımı, pozisyon ve işlem tabloları, içgörüler.
    Saf fonksiyon; yeni hesap yok (özet + kayıtlardan yalnız toplama/dizme). Dış kaynak/JS yok; tüm metin HTML kaçışlı."""
    kasa, oz = float(ozet.get("kasa_usd") or 0.0), float(ozet.get("ozsermaye_usd") or 0.0)
    gun_basi, zirve = risk.get("gun_basi"), risk.get("zirve")
    gun = (oz - float(gun_basi)) / kasa if gun_basi is not None and kasa > 0 else None
    dusus = (float(zirve) - oz) / float(zirve) if zirve and float(zirve) > 0 else None
    hafta = hafta_getirisi(gecmis, oz, simdi_ms, kasa)
    k24 = pencere24(kayitlar, simdi_ms)
    emirler = [k for k in k24 if k.get("olay") == "emir"]
    dolum = [k for k in emirler if k.get("durum") in ("dolu", "kismi")]
    kaymalar = [abs(k["kayma_trader"]) * 1e4 for k in dolum if k.get("kayma_trader") is not None]
    funding24 = sum(float(k.get("funding_usd") or 0.0) for k in k24 if k.get("olay") == "funding")
    din = ozet.get("dinleyici") or {}
    kip = str(ozet.get("kip", "—"))

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
    if len(seri) < 2:
        seri = [(0, float(g["ozsermaye"])) for g in gecmis if g.get("ozsermaye") is not None] + seri
    deg = [v for _, v in seri]
    if not deg or deg[-1] != oz:
        deg.append(oz)
    tepe, dd = 0.0, []
    for v in deg:
        tepe = max(tepe, v)
        dd.append((v / tepe - 1) * 100 if tepe > 0 else 0.0)
    gunluk: dict[str, float] = {}
    for ms, v in seri:
        if ms:
            gunluk[datetime.fromtimestamp(ms / 1000, UTC).date().isoformat()] = v
    gv = list(gunluk.values())
    cubuklar = [b - a for a, b in zip(gv, gv[1:])]

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
    islem_satir = "".join(f'<tr><td class="so">{_tsi(int(k["zaman_ms"]), "%H:%M")}</td><td><b>{esc(str(k.get("coin", "")))}</b></td><td class="{"art" if k.get("yon") == "B" else "eks"}">{"AL" if k.get("yon") == "B" else "SAT"} · {EYLEM.get(k.get("eylem", ""), "")}</td><td class="sg">{esc(tl(k.get("usd_dolan") or k.get("usd_istenen")))}</td><td class="sg so">{tr_sayi(abs(k["kayma_trader"]) * 1e4 if k.get("kayma_trader") is not None else 0, 1)} bp</td></tr>'
                          for k in sorted(emirler, key=lambda k: -int(k["zaman_ms"]))[:12]) or '<tr><td colspan="5" class="bos">Son 24 saatte emir yok</td></tr>'
    # içgörüler (yalnız dizme/sayma)
    ic = []
    kz = [q for q in acik if q.get("kz_usd") is not None]
    if kz:
        en_iyi, en_kotu = max(kz, key=lambda q: q["kz_usd"]), min(kz, key=lambda q: q["kz_usd"])
        ic.append(f'En iyi pozisyon: <b>{esc(en_iyi["coin"])}</b> <span class="{renk(en_iyi["kz_usd"])}">{esc(tl(en_iyi["kz_usd"], True))}</span>; en zayıf: <b>{esc(en_kotu["coin"])}</b> <span class="{renk(en_kotu["kz_usd"])}">{esc(tl(en_kotu["kz_usd"], True))}</span>.')
        ic.append(f'Açık pozisyonların {sum(1 for q in kz if q["kz_usd"] >= 0)}/{len(kz)} tanesi kârda.')
    sayim: dict[str, int] = {}
    for k in emirler:
        sayim[k.get("adres", "")] = sayim.get(k.get("adres", ""), 0) + 1
    if sayim:
        a_, n_ = max(sayim.items(), key=lambda x: x[1])
        ic.append(f'Son 24 saatte en çok işlem yapan trader: <b>{esc(kisa(a_))}</b> ({n_} emir).')
    if kaymalar:
        ic.append(f'Emirler trader fiyatına ortalama {tr_sayi(sum(kaymalar) / len(kaymalar), 1)} bp farkla doldu (küçük = iyi).')
    ic.append(f'Brüt pozisyon {esc(tl(sum(q.get("usd") or 0 for q in acik)))} = kasanın %{(sum(q.get("usd") or 0 for q in acik) / kasa * 100 if kasa > 0 else 0):.0f}\'i.')
    saha = [k for k in k24 if k.get("olay") in ("saha_giris", "saha_dus")]
    saha_html = "".join(f'<div class="s">{"➕ giriş" if k["olay"] == "saha_giris" else "➖ çıkış"} · {_tsi(int(k["zaman_ms"]), "%H:%M")} · {esc(kisa(k["adres"]))} · {esc(str(k.get("neden", "")))}</div>' for k in saha) or '<div class="bos">Trader listesinde değişiklik yok</div>'
    riskler = [k for k in k24 if k.get("olay") in RISK_OLAYLARI]
    risk_html = "".join(f'<div class="s eks">⚠ {_tsi(int(k["zaman_ms"]), "%H:%M")} · {esc(str(k["olay"]))}</div>' for k in riskler) or '<div class="s art">✓ Son 24 saatte risk olayı yok</div>'
    gun_kayip_pay = min(max(-(gun or 0) / 0.05, 0.0), 1.0) * 100
    dusus_pay = min(max((dusus or 0) / 0.20, 0.0), 1.0) * 100
    # KADRO sekmesi: ilk 11 + yedekler; tıklayınca "bize ne verdi" mini özeti (yalnız defter/kayıt toplamı; yeni hesap yok)
    uyeler, inenler = ((saha_durum or {}).get("uyeler") or {}), ((saha_durum or {}).get("inen") or {})
    emir_say: dict[str, int] = {}
    son_emir: dict[str, int] = {}
    for k in kayitlar:
        if k.get("olay") == "emir" and k.get("adres"):
            emir_say[k["adres"]] = emir_say.get(k["adres"], 0) + 1
            son_emir[k["adres"]] = max(son_emir.get(k["adres"], 0), int(k.get("zaman_ms", 0)))
    kz_adres: dict[str, float] = {}
    poz_adres: dict[str, int] = {}
    for q in acik:
        kz_adres[q["adres"]] = kz_adres.get(q["adres"], 0.0) + float(q.get("kz_usd") or 0.0)
        poz_adres[q["adres"]] = poz_adres.get(q["adres"], 0) + 1
    gerc, ucr, slot_bas = hesap.get("realize") or {}, hesap.get("ucret") or {}, hesap.get("slot_bas") or {}
    kartlar, yedek_kartlar = [], []
    for r in (kadro or {}).get("satirlar") or []:
        ad = r["adres"]
        durum = "SAHADA" if ad in uyeler else ("İNİYOR" if ad in inenler else ("SIRADA" if r.get("katman") == "ilk11" else "YEDEK"))
        net = (float(gerc.get(ad, 0.0)) - float(ucr.get(ad, 0.0)) + kz_adres.get(ad, 0.0)) if ad in slot_bas else None
        yuzde_s = (net / float(slot_bas[ad])) if net is not None and float(slot_bas.get(ad) or 0) > 0 else None
        giris = (uyeler.get(ad) or {}).get("giris_ms")
        if ad in slot_bas:
            ayrinti = (f'<div class="ms"><div><span class="so">Takibe alındı</span><br>{_tsi(int(giris), "%d.%m %H:%M") if giris else "—"}</div>'
                       f'<div><span class="so">Slot (ayrılan para)</span><br>{esc(tl(float(slot_bas[ad])))}</div>'
                       f'<div><span class="so">Bize verdiği (net)</span><br><b class="{renk(net)}">{esc(tl(net, True))}</b> <span class="{renk(yuzde_s)}">{esc(tyuz(yuzde_s))}</span></div>'
                       f'<div><span class="so">Gerçekleşen / açık</span><br>{esc(tl(float(gerc.get(ad, 0.0)) - float(ucr.get(ad, 0.0)), True))} / {esc(tl(kz_adres.get(ad, 0.0), True))}</div>'
                       f'<div><span class="so">Emir sayısı</span><br>{emir_say.get(ad, 0)}</div>'
                       f'<div><span class="so">Açık pozisyon</span><br>{poz_adres.get(ad, 0)}</div>'
                       f'<div><span class="so">Son işlem</span><br>{_tsi(son_emir[ad]) if ad in son_emir else "—"}</div>'
                       f'<div><span class="so">Radar 7g kopya getirisi</span><br>{esc(tyuz(r.get("kopya_getiri_7g")))}</div></div>')
        else:
            ayrinti = (f'<div class="ms"><div><span class="so">Durum</span><br>Henüz kopyalanmıyor — {"boş yer açılınca girer" if durum == "SIRADA" else "yedek listede"}</div>'
                       f'<div><span class="so">Radar 7g kopya getirisi</span><br>{esc(tyuz(r.get("kopya_getiri_7g")))}</div>'
                       f'<div><span class="so">Form puanı</span><br>{float(r.get("form") or 0):.1f} / 100</div>'
                       f'<div><span class="so">Azami kaldıraç</span><br>{float(r.get("max_kaldirac") or 0):.1f}x</div></div>')
        rozet = {"SAHADA": "art", "İNİYOR": "eks", "SIRADA": "yok", "YEDEK": "yok"}[durum]
        (kartlar if r.get("katman") != "yedek" else yedek_kartlar).append(f'<details class="kd"><summary><span class="sr">{int(r.get("sira", 0))}</span><b>{esc(kisa(ad))}</b><span class="rz {rozet}">{durum}</span>'
                       f'<span class="fb"><i style="width:{min(max(float(r.get("form") or 0), 0), 100):.0f}%"></i></span><span class="fm">{float(r.get("form") or 0):.0f}</span>'
                       f'<span class="nt {renk(net)}">{esc(tl(net, True)) if net is not None else ""}</span></summary>{ayrinti}</details>')
    kadro_tarih = _tsi(int(kadro["kosu_ms"]), "%d.%m %H:%M") if kadro and kadro.get("kosu_ms") else "—"
    kadro_html = "".join(kartlar) + ('<div class="yb">YEDEKLER</div>' + "".join(yedek_kartlar) if yedek_kartlar else "") if (kartlar or yedek_kartlar) else '<div class="bos">Kadro verisi okunamadı</div>'
    uyari = '<div class="uy">⚠ GERÇEK PARA</div>' if kip == "gercek" else ""
    return f"""<!doctype html>
<html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex"><meta name="color-scheme" content="dark">
<title>Copy Trade Panosu</title>
<style>
:root{{--bg:#0a0a0b;--k:#111113;--cz:#25252a;--y:#e9e9ee;--so:#8a8a94;--tu:#f5a524;--art:#3ddc84;--eks:#ff5d5d}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--y);font:13px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;padding:12px}}
.ust{{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:10px}}.lg0{{background:var(--tu);color:#000;font-weight:800;padding:2px 7px;border-radius:3px}}
.ust b{{font-size:15px;letter-spacing:.05em}}.so,.ha{{color:var(--so)}}.rozet{{border:1px solid var(--cz);border-radius:3px;padding:1px 8px;color:var(--tu);font-size:11px}}
.sirit{{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--cz);border:1px solid var(--cz);margin-bottom:8px}}
.h{{background:var(--k);padding:8px 9px}}.hb{{font-size:10px;letter-spacing:.09em;color:var(--so);text-transform:uppercase}}.hd{{font-size:17px;font-weight:700;margin:2px 0}}.ha{{font-size:11px}}
.art{{color:var(--art)}}.eks{{color:var(--eks)}}.yok{{color:var(--so)}}
.izgara{{display:grid;grid-template-columns:1fr;gap:8px}}.p{{background:var(--k);border:1px solid var(--cz);min-width:0}}
.pb{{font-size:10px;letter-spacing:.09em;color:var(--tu);text-transform:uppercase;padding:8px 11px;border-bottom:1px solid var(--cz);display:flex;justify-content:space-between}}.pb span{{color:var(--so)}}
.pi{{padding:10px 11px}}.gr{{width:100%;height:110px;display:block}}.bos{{color:var(--so);padding:14px 4px;font-size:12px}}
table{{width:100%;border-collapse:collapse;font-size:12px}}td,th{{padding:6px 8px;border-bottom:1px solid #1c1c21;text-align:left;white-space:nowrap}}th{{font-size:10px;color:var(--so);letter-spacing:.08em}}.sg{{text-align:right}}tr:last-child td{{border:0}}
.tw{{overflow-x:auto}}.dg{{display:flex;height:16px;border-radius:3px;overflow:hidden;background:#1c1c21}}.dg span{{display:block;height:100%}}
.lg{{display:inline-block;margin:6px 12px 0 0;font-size:11px;color:var(--so)}}.lg i{{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:5px}}
.s{{padding:4px 0;font-size:12px}}.ic div{{padding:5px 0 5px 12px;border-bottom:1px solid #1c1c21;position:relative}}.ic div:before{{content:"›";color:var(--tu);position:absolute;left:0}}
.ol{{height:7px;background:#1c1c21;border-radius:4px;margin:4px 0 9px;overflow:hidden}}.ol i{{display:block;height:100%;background:var(--tu)}}.uy{{background:var(--eks);color:#fff;font-weight:800;padding:6px 10px;margin-bottom:8px;border-radius:3px}}
.tabs{{display:flex;gap:2px;margin:0 0 8px;border-bottom:1px solid var(--cz);overflow-x:auto}}.tabs label{{padding:9px 13px;font-size:11px;letter-spacing:.09em;color:var(--so);cursor:pointer;white-space:nowrap;border-bottom:2px solid transparent}}.tabs em{{font-style:normal;background:#1c1c21;border-radius:9px;padding:0 6px;margin-left:4px;color:var(--y)}}
input[name=t]{{position:absolute;opacity:0;pointer-events:none}}.sekmeler section{{display:none}}
#t1:checked~.tabs label[for=t1],#t2:checked~.tabs label[for=t2],#t3:checked~.tabs label[for=t3],#t4:checked~.tabs label[for=t4],#t5:checked~.tabs label[for=t5]{{color:var(--tu);border-bottom-color:var(--tu)}}
#t1:checked~.sekmeler .n1,#t2:checked~.sekmeler .n2,#t3:checked~.sekmeler .n3,#t4:checked~.sekmeler .n4,#t5:checked~.sekmeler .n5{{display:grid}}
.kd{{border-bottom:1px solid #1c1c21}}.kd summary{{display:grid;grid-template-columns:22px 1fr auto 46px 24px auto;gap:8px;align-items:center;padding:9px 2px;cursor:pointer;list-style:none}}.kd summary::-webkit-details-marker{{display:none}}
.sr{{color:var(--so)}}.rz{{font-size:10px;border:1px solid var(--cz);border-radius:3px;padding:0 6px;letter-spacing:.05em}}.fb{{height:6px;background:#1c1c21;border-radius:3px;overflow:hidden}}.fb i{{display:block;height:100%;background:var(--tu)}}.fm{{text-align:right;color:var(--so)}}.nt{{text-align:right;min-width:64px}}
.ms{{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;padding:4px 4px 12px 30px;font-size:12px}}.yb{{margin:12px 0 2px;font-size:10px;letter-spacing:.1em;color:var(--tu)}}
@media(min-width:900px){{.ms{{grid-template-columns:repeat(4,1fr)}}}}
@media(min-width:900px){{body{{padding:18px;max-width:1280px;margin:auto}}.sirit{{grid-template-columns:repeat(6,1fr)}}.hd{{font-size:20px}}.izgara{{grid-template-columns:repeat(3,1fr)}}.g2{{grid-column:span 2}}.g3{{grid-column:span 3}}}}
</style></head><body>
<div class="ust"><div><span class="lg0">CT</span> <b>COPY TRADE PANOSU</b></div><div><span class="rozet">{esc(kip_adi(kip))}</span> <span class="so">güncelleme {_tsi(simdi_ms, "%d.%m.%Y %H:%M")} TSİ · her 4 saatte bir</span></div></div>{uyari}
<div class="sirit">{hucre("Özsermaye", tl(oz), "", f"kasa {tr_sayi(kasa, 0)} $")}{hucre("Bugün", tyuz(gun), renk(gun), tl(oz - float(gun_basi), True) if gun_basi is not None else "")}{hucre("Bu hafta", tyuz(hafta) if hafta is not None else "—", renk(hafta), "" if hafta is not None else "7 gün dolmadı")}{hucre("Başlangıçtan beri", tyuz(ozet.get("getiri")), renk(ozet.get("getiri")), tl(oz - kasa, True))}{hucre("Zirveden düşüş", tyuz(-dusus if dusus is not None else None), renk(-dusus if dusus is not None else None), f"zirve {tl(float(zirve))}" if zirve else "")}{hucre("Açık pozisyon", str(len(acik)), "", f"brüt {tl(sum(q.get('usd') or 0 for q in acik))}")}</div>
<input type="radio" name="t" id="t1" checked><input type="radio" name="t" id="t2"><input type="radio" name="t" id="t3"><input type="radio" name="t" id="t4"><input type="radio" name="t" id="t5">
<div class="tabs"><label for="t1">ÖZET</label><label for="t5">KADRO <em>{len(kartlar) + len(yedek_kartlar)}</em></label><label for="t2">POZİSYON <em>{len(acik)}</em></label><label for="t3">İŞLEMLER <em>{len(emirler)}</em></label><label for="t4">RİSK</label></div>
<div class="sekmeler">
<section class="n1 izgara">
<div class="p g2"><div class="pb">Özsermaye (tur sonları) <span>{esc(tl(oz))}</span></div><div class="pi">{_cizgi(deg, "#f5a524")}</div></div>
<div class="p"><div class="pb">Günlük net K/Z <span>$</span></div><div class="pi">{_cubuk(cubuklar)}</div></div>
<div class="p g2"><div class="pb">İçgörüler</div><div class="pi ic">{"".join(f"<div>{x}</div>" for x in ic)}</div></div>
<div class="p"><div class="pb">Risk payı <span>sınıra göre</span></div><div class="pi"><div class="ha">Günlük kayıp (sınır %5)</div><div class="ol"><i style="width:{gun_kayip_pay:.0f}%"></i></div><div class="ha">Zirveden düşüş (sınır %20)</div><div class="ol"><i style="width:{dusus_pay:.0f}%"></i></div>{risk_html}</div></div>
</section>
<section class="n2 izgara">
<div class="p g2"><div class="pb">Açık pozisyonlar <span>{len(acik)} adet</span></div><div class="tw"><table><tr><th>COİN</th><th>YÖN</th><th class="sg">TUTAR</th><th class="sg">K/Z</th><th>TRADER</th></tr>{poz_satir}</table></div></div>
<div class="p"><div class="pb">Para dağılımı <span>coin başına</span></div><div class="pi"><div class="dg">{cubuk_html}</div>{efsane}</div></div>
</section>
<section class="n3 izgara">
<div class="g3 sirit">{hucre("Emir (24 sa)", str(len(emirler)), "", f"dolum {len(dolum)}")}{hucre("Ort. fark", f"{tr_sayi(sum(kaymalar) / len(kaymalar), 1)} bp" if kaymalar else "—", "", "trader fiyatına göre")}{hucre("Funding (24 sa)", tl(funding24, True), renk(funding24), "sanal")}{hucre("Takipte", f"{ozet.get('saha', '—')}/{ozet.get('saha_n', '—')}", "", "trader")}</div>
<div class="p g2"><div class="pb">Son işlemler <span>24 sa, en yeni üstte</span></div><div class="tw"><table><tr><th>SAAT</th><th>COİN</th><th>YÖN</th><th class="sg">TUTAR</th><th class="sg">FARK</th></tr>{islem_satir}</table></div></div>
<div class="p"><div class="pb">Trader değişiklikleri <span>24 sa</span></div><div class="pi">{saha_html}</div></div>
</section>
<section class="n5 izgara">
<div class="p g3"><div class="pb">Takip edilen ilk 11 ve yedekler <span>radar {kadro_tarih} TSİ · dokun → bize ne verdi</span></div><div class="pi kl">{kadro_html}</div></div>
</section>
<section class="n4 izgara">
<div class="g3 sirit">{hucre("WS kopma", str(din.get("kopma", "—")), "", "tur başına")}{hucre("REST 429", str(ozet.get("rest_429", "—")), "", "hız sınırı")}{hucre("Tur süresi", f"{float(ozet.get('sure_dk') or 0) / 60:.1f} sa", "", "son tur")}{hucre("Özsermaye zirvesi", tl(float(zirve)) if zirve else "—", "", "")}</div>
<div class="p g2"><div class="pb">Zirveden düşüş (tur sonları) <span>{dd[-1]:.2f}%</span></div><div class="pi">{_cizgi(dd, "#ff5d5d", taban=0.0)}</div></div>
<div class="p"><div class="pb">Risk olayları <span>24 sa</span></div><div class="pi">{risk_html}</div></div>
</section>
</div>
<div class="so" style="margin:16px 0 4px;font-size:11px">Sanal kip: gerçek para yok. Veriler Hyperliquid halka açık verisidir. Saatler TSİ.</div>
</body></html>
"""


# ------------------------------------------------------------------------------------------------------------------------------ CLI
def _json(yol: Path) -> dict:
    return json.loads(yol.read_text(encoding="utf-8")) if yol.is_file() else {}


def kayitlari_oku(dizin: Path) -> list[dict]:
    """Son iki günlük `kayit/<tarih>.jsonl` (24 sa penceresi gün sınırını aşabilir)."""
    cikti: list[dict] = []
    for f in sorted(dizin.glob("*.jsonl"))[-2:]:
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--durum", type=Path, default=Path("durum"))
    ap.add_argument("--kayit", type=Path, default=Path("kayit"))
    ap.add_argument("--gecmis", type=Path, default=Path("pano/gecmis.json"))
    ap.add_argument("--cikti", type=Path, default=Path("pano/OZET.md"))
    ap.add_argument("--html", type=Path, default=None, help="telefon sayfası (pano/index.html; Cloudflare Pages) da yazılır")
    ap.add_argument("--isabet-dali", default=None, help="isabet.json okunan veri dalı (radar | radar-deneme); yoksa isabet bölümü 'ilk ölçüm' yazar")
    args = ap.parse_args(argv)
    ozet = _json(args.durum / "ozet.json")
    if not ozet:
        print("pano: durum/ozet.json yok; yazılmadı", file=sys.stderr)
        return 0
    gecmis = json.loads(args.gecmis.read_text(encoding="utf-8")) if args.gecmis.is_file() else []
    md, yeni = pano_olustur(ozet, _json(args.durum / "risk.json"), _json(args.durum / "hesap.json"), kayitlari_oku(args.kayit), isabetleri_oku(args.isabet_dali), gecmis, int(time.time() * 1000))
    args.cikti.parent.mkdir(parents=True, exist_ok=True)
    args.cikti.write_text(md, encoding="utf-8")
    args.gecmis.write_text(json.dumps(yeni, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if args.html:
        args.html.write_text(html_olustur(ozet, _json(args.durum / "risk.json"), _json(args.durum / "hesap.json"), kayitlari_oku(args.kayit), yeni, int(time.time() * 1000), kadro_oku(args.isabet_dali), _json(args.durum / "saha.json")), encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
