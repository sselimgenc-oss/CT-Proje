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

from copytrade import surum_karsilastirma
from copytrade.canli.gunluk_ozet import alinmayan_neden, kopya_kalite
from copytrade.canli.telegram import ATLA_TR, KACIRILAN_NEDENLER, kip_adi, tr_isaretli, tr_sayi, tr_yuzde
from copytrade.saglik import durum as saglik_durum, kontrol as saglik_kontrol

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


def duygu_metni(ozet: dict) -> tuple[str, str]:
    """Piyasa duygusu (Fear & Greed; sanalda uçta yeni açılışı atlatır, gerçekte yalnız kayıt): ('25', 'Extreme Fear') ya da ('—', 'yalnız kayıt')."""
    d = ozet.get("duygu") or {}
    return (str(d["deger"]), str(d["sinif"])) if d.get("deger") is not None and d.get("sinif") else ("—", "yalnız kayıt")


def btc_metni(ozet: dict) -> tuple[str, str]:
    """Başarı ölçütü kıyası (31.12: ayda ≥ %4 VE BTC al-tut'tan iyi): motorun `ozet.json` `btc_al_tut_getiri` / `btc_fark` alanları (aynı dönemde BTC al-tut getirisi; fark = getiri − BTC).
    Döner ("BTC al-tut: +%x,x", "fark: +%x,x"); veri yoksa "—"."""
    bt, fk = ozet.get("btc_al_tut_getiri"), ozet.get("btc_fark")
    return ("BTC al-tut: " + ("—" if bt is None else tr_yuzde(float(bt), 1)), "fark: " + ("—" if fk is None else tr_yuzde(float(fk), 1)))


def komisyon_ozeti(kayitlar: list[dict], ozet: dict, donem_seri: dict | None) -> tuple[float | None, float | None, float | None]:
    """Kullanıcı isteği 15.11 (Fable önerisi; yalnız bilgi): dönem başından (`donem_seri.bas_ms`; yoksa tüm kayıt penceresi) ödenen ücret, brüt K/Z (= net + ücret) ve ücretin brüt K/Z'ye oranı.
    Komisyon emir ADEDİNE değil HACME bağlıdır. Kayıt penceresi ≤ 14 gün; dönem daha uzunsa ücret penceredekiyle sınırlıdır. Döner (ücret, brüt, oran) — brüt ≤ 0 ise oran None."""
    bas = int((donem_seri or {}).get("bas_ms") or 0)
    ucret = sum(float(k.get("ucret") or 0.0) for k in kayitlar if k.get("olay") == "emir" and k.get("durum") in ("dolu", "kismi") and int(k.get("zaman_ms") or 0) >= bas)
    kasa, oz = ozet.get("kasa_usd"), ozet.get("ozsermaye_usd")
    if kasa is None or oz is None:
        return ucret, None, None
    brut = float(oz) - float(kasa) + ucret
    return ucret, brut, (ucret / brut if brut > 0 else None)


def komisyon_metni(kayitlar: list[dict], ozet: dict, donem_seri: dict | None) -> tuple[str, str]:
    """("ödenen ücret: 14,40 $", "brüt kârın %x'i" | "brüt K/Z ≤ 0: kâr yok, ücret zararı büyütüyor")."""
    u, b, o = komisyon_ozeti(kayitlar, ozet, donem_seri)
    alt = "—" if b is None else (f"brüt kârın %{tr_sayi(o * 100, 0)}'i" if o is not None else "brüt K/Z ≤ 0: ücret zararı büyütüyor")
    return (f"ödenen ücret: {usd(u)}", alt)


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
                 kadro: dict | None = None, surum_gun: dict[str, str] | None = None, pbo: dict | None = None) -> tuple[str, list[dict]]:
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
         f"Başarı kıyası (aynı dönemde): toplam {yuzde(ozet.get('getiri'))} · {' · '.join(btc_metni(ozet))} · {' · '.join(hedef_metni(ozet))}", "",
         f"Komisyon (dönem): {' · '.join(komisyon_metni(kayitlar, ozet, donem_seri))} _(ücret işlem hacmine bağlıdır, emir sayısına değil)_", "",
         f"Piyasa duygusu (Fear & Greed 0-100; sanalda ≥75 yeni long, ≤25 yeni short atlatır; gerçekte yalnız kayıt): {' · '.join(duygu_metni(ozet))}", ""]
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
    ko = [k for k in k24 if k.get("olay") == "karsi_olgu_kapandi"]
    if ko:
        neden_ko: dict[str, list[float]] = {}
        for k in ko:
            g = neden_ko.setdefault(str(k.get("neden") or "?"), [0, 0.0])
            g[0] += 1
            g[1] += float(k.get("pnl_usd") or 0.0)
        s += ["## Alınmayan sinyaller (hayali, 24 sa; işlem etkisi yok)", "", f"- {len(ko)} kapandı · toplam {usd(sum(g[1] for g in neden_ko.values()), True)}"
              + " · " + " · ".join(f"{ad} {int(g[0])} ({usd(g[1], True)})" for ad, g in sorted(neden_ko.items(), key=lambda kv: -abs(kv[1][1]))), ""]
    og = ozet.get("ogrenme")
    if og:                                                                       # ortak öğrenme karnesi (takma adlı; sanal kasa = 1.000 $ başlangıç, işlem başına %1 × R; yalnız rapor)
        s += ["## Ortak öğrenme karnesi (sanal)", "", "| kurulum | aday | ort R | sanal kasa | getiri | en derin | drift | ders | filtre |", "|---|---|---|---|---|---|---|---|---|"]
        s += [f"| {r['kurulum']} | {r['alinan']} | {r['ort_r'] if r['ort_r'] is None else format(r['ort_r'], '+.2f')} | {usd(r['kasa'])} | {yuzde(r['getiri_pct'] / 100.0)} | {r['en_derin_pct']:.1f}% | {r['drift']} | "
              f"{'emekli' if r.get('emekli') else (('x' + format(r['carpan'], 'g')) if r.get('carpan') else '—')} | {'var' if r.get('filtre') else 'yok'} |" for r in og]
        s += [""]
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
    if pbo:
        s += ["", pbo_satiri(pbo)]
    s += [""] + surum_karsilastirma.md_bolum(surum_karsilastirma.karsilastir(kayitlar, surum_gun))
    s += donem_md(donem_seri or {}, kadro or {})
    return "\n".join(s) + "\n", gecmis_yeni


TSI = timezone(timedelta(hours=3))

RENKLER = ("#f5a524", "#3ddc84", "#5b9dff", "#ff5d5d", "#b07cff", "#2dd4bf", "#f472b6", "#a3a3a3")


def _tsi(ms: int, bicim: str = "%d.%m %H:%M") -> str:
    return datetime.fromtimestamp(ms / 1000, TSI).strftime(bicim)


# ------------------------------------------------------------------------------------------------------------------------------ dönem boyu (pano 14.11; kaynak durum/donem_seri.json)
def pbo_satiri(pbo: dict) -> str:
    """Son `radar/<tarih>/pbo.json` tek satır (hesap `copytrade.pbo_rapor`da; burada yalnız biçim)."""
    if pbo.get("durum") != "tamam":
        return f"PBO (aşırı uydurma olasılığı, bilgi): yetersiz veri — {pbo.get('neden', '')}"
    return f"PBO (aşırı uydurma olasılığı, bilgi): {pbo['pbo']:.2f} (T={pbo.get('kullanilan_t')} gün, {len(pbo.get('adaylar', []))} aday; ≥ 0,5 = seçim üstünlüğü sınamada korunmuyor)"


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


def maruziyet_ozeti(ds: dict, oz: float, kasa: float) -> dict:
    """M-04 (kullanıcı kararı 14.11; yalnız rapor): zaman ağırlıklı ortalama brüt ve |net| maruziyet ($ ve kasaya oran) ve KULLANILAN sermaye getirisi = (özsermaye − kasa) / ortalama brüt
    maruziyet (kasanın tamamına değil, ortalamada piyasada duran paraya göre). Veri yoksa None. Yeni karar yok."""
    dl = ds.get("doluluk") or {}
    sure = float(dl.get("sure_ms") or 0)
    brut = float(dl.get("brut_ms") or 0) / sure if sure > 0 and dl.get("brut_ms") is not None else None
    net = float(dl.get("net_ms") or 0) / sure if sure > 0 and dl.get("net_ms") is not None else None
    return {"brut": brut, "net": net, "brut_oran": brut / kasa if brut is not None and kasa > 0 else None, "net_oran": net / kasa if net is not None and kasa > 0 else None,
            "sermaye_getirisi": (oz - kasa) / brut if brut and brut > 0 else None}


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
    mo = maruziyet_ozeti(ds, float((ds.get("gunler") or [{}])[-1].get("ozsermaye_usd") or ds.get("kasa_usd") or 0.0), float(ds.get("kasa_usd") or 0.0))
    s.append(f"- kullanılan sermaye getirisi {yuzde(mo['sermaye_getirisi'])} · ort. brüt maruziyet {usd(mo['brut'])} · ort. net {usd(mo['net'])} · risk kilidi olayı {len(ds.get('kilitler') or [])} (gölge eğri yok)")
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
            f'<div class="ek ek2">en düşük {esc(f(lo))} · en yüksek {esc(f(hi))}{" · kesikli çizgi: başlangıç kasası" if baz is not None else ""}</div>')


KATMAN_AD = {"ilk11": "İlk 11", "yedek": "Yedek", "bilinmiyor": "bilinmiyor"}
VERI_YOK = '<div class="bos">— {}</div>'


def serit(hucreler: list[str], sinif: str = "") -> str:
    """Rakam şeridi: sütun sayısı hücre sayısına göre seçilir (masaüstünde boş kutu kalmasın): telefon 2 (tek sayıda 3), masaüstü 6/4/5/3'ten hücre sayısını bölen ilki (yoksa 4)."""
    n = len(hucreler)
    tel = 2 if n % 2 == 0 else 3
    mas = next((k for k in (6, 4, 5, 3) if n % k == 0), 4)
    return f'<div class="sirit{(" " + sinif) if sinif else ""}" style="--sm:{tel};--sk:{mas}">{"".join(hucreler)}</div>'


KILIT_TR = {"gunluk_kayip": "günlük kayıp freni", "gunluk_kapat": "günlük kayıp: hepsi kapandı", "zirve_dusus": "zirveden düşüş freni", "felaket_stop": "stop"}


def _kilit_tr(tur: str) -> str:
    return KILIT_TR.get(tur, "diğer")


def _donem_egri_html(nok: list[tuple[int, float, float | None, float]], kilitler: list[dict] | None = None) -> str:
    """Dönem eğrisi (inline SVG): motor kasası (turuncu) ↔ BTC al-tut (mavi) ↔ %4/ay hedef (gri kesikli). 2'den az nokta → açıklama.
    M-05 (kullanıcı kararı 14.11): risk kilidi olayları (`donem_seri.kilitler`) kırmızı dikey çizgiyle işaretlenir. Kilitsiz "gölge" eğri ÇİZİLMEZ: kilit yüzünden açılmayan / erken
    kapanan pozisyonların sonraki fiyat yolu motor defterinde yok (ayrı bir gölge defter gerekir); bu yüzden yalnız işaret + açıklama."""
    kilitler = kilitler or []
    acik = (f'<div class="ha">Risk freni olayı: {len(kilitler)}' + (" (" + ", ".join(f"{_tsi(int(k['ms']), '%d.%m %H:%M')} {esc(_kilit_tr(str(k.get('tur'))))}" for k in kilitler[-5:]) + ")" if kilitler else "") + ' — grafikte kırmızı çizgi.</div>')
    if len(nok) < 2:
        return VERI_YOK.format("dönem eğrisi ilk günün sonunda çizilir") + acik
    x0, x1 = nok[0][0], nok[-1][0]
    deg = [v for n in nok for v in (n[1], n[2], n[3]) if v is not None]
    lo, hi = min(deg), max(deg)
    ar, xa = (hi - lo) or 1.0, (x1 - x0) or 1
    xy = lambda t, v: f"{(t - x0) / xa * 300:.1f},{78 - (v - lo) / ar * 66:.1f}"                # noqa: E731
    cizgi = lambda i, renk, ek="": (f'<polyline fill="none" stroke="{renk}" stroke-width="1.8" vector-effect="non-scaling-stroke"{ek} points="'      # noqa: E731
                                    + " ".join(xy(n[0], n[i]) for n in nok if n[i] is not None) + '"/>')
    btc = cizgi(2, "#5b9dff") if sum(1 for n in nok if n[2] is not None) >= 2 else ""
    son = nok[-1]
    isaret = "".join(f'<line x1="{(int(k["ms"]) - x0) / xa * 300:.1f}" y1="0" x2="{(int(k["ms"]) - x0) / xa * 300:.1f}" y2="80" stroke="#ff5d5d" stroke-width="1" vector-effect="non-scaling-stroke"/>'
                     for k in kilitler if x0 <= int(k.get("ms") or 0) <= x1)
    return (f'<svg viewBox="0 0 300 80" preserveAspectRatio="none" class="gr">{isaret}{cizgi(3, "#8a8a94", ' stroke-dasharray="4 3"')}{btc}{cizgi(1, "#f5a524")}</svg>'
            f'<div class="ek"><span>{_tsi(x0, "%d.%m")}</span><span>{_tsi(x1, "%d.%m %H:%M")}</span></div>'
            f'<div class="ek ek2"><span class="lg"><i style="background:#f5a524"></i>motor {esc(tl2(son[1]))}</span><span class="lg"><i style="background:#5b9dff"></i>BTC al-tut {esc(tl2(son[2]))}</span>'
            f'<span class="lg"><i style="background:#8a8a94"></i>%4/ay hedef {esc(tl2(son[3]))}</span></div>' + acik)


def _katki_html(so: dict) -> str:
    """Trader başına dönem katkısı (kapanmış slotlar dahil): giriş/çıkış (TSİ), katman, net K/Z $."""
    if not so["trader"]:
        return VERI_YOK.format("dönemde henüz trader takibe alınmadı")
    satir = "".join(f'<tr><td>{esc(kisa(r["adres"]))}</td><td>{esc(KATMAN_AD.get(r.get("katman") or "bilinmiyor", "—"))}</td><td class="so">{_tsi(int(r["giris_ms"]))}</td>'
                    f'<td class="so">{_tsi(int(r["cikis_ms"])) if r.get("cikis_ms") else "sahada"}</td><td class="sg {"art" if float(r.get("net_usd") or 0) >= 0 else "eks"}">{esc(tl2(r.get("net_usd"), True))}</td></tr>'
                    for r in so["trader"][:40])
    return (f'<div class="tw"><table><tr><th>TRADER</th><th>KATMAN</th><th>GİRİŞ</th><th>ÇIKIŞ</th><th class="sg">NET</th></tr>{satir}</table></div>'
            f'<div class="ha" style="padding:6px 11px">Net = girişten beri K/Z (ücret, fonlama ücreti, açık pozisyon dahil). Toplam {esc(tl2(so["toplam"], True))}.</div>')


def _ilk_yedek_html(so: dict) -> str:
    if not so["katman"]:
        return VERI_YOK.format("henüz trader yok")
    return "".join(f'<div class="s"><b>{esc(KATMAN_AD.get(k, k))}</b> · {v["n"]} trader · <span class="{"art" if v["net"] >= 0 else "eks"}">{esc(tl2(v["net"], True))}</span>'
                   f' <span class="so">(trader başı {esc(tl2(v["net"] / v["n"], True))})</span></div>' for k, v in sorted(so["katman"].items()))


def _gecmis_html(ds: dict) -> str:
    """Giriş/çıkış geçmişi dönem boyu (neden ile; en yeni üstte, en çok 40)."""
    olay = []
    for r in ds.get("slotlar") or []:
        olay.append((int(r["giris_ms"]), f'giriş · {esc(kisa(r["adres"]))} · {esc(_saha_neden_tr(str(r.get("giris_neden") or "")))}'))
        if r.get("cikis_ms"):
            olay.append((int(r["cikis_ms"]), f'çıkış · {esc(kisa(r["adres"]))} · {esc(_saha_neden_tr(str(r.get("cikis_neden") or "")))}{" (sonuçla)" if r.get("sonuc") else ""}'))
    if not olay:
        return VERI_YOK.format("dönemde giriş/çıkış yok")
    return "".join(f'<div class="s"><span class="so">{_tsi(ms)}</span> {m}</div>' for ms, m in sorted(olay, reverse=True)[:40])


HUNI_TR = {"islem_az": "az işlem", "devir_yuksek": "çok sık al-sat", "dolum_fazla": "işlem hacmi fazla", "tutma_kisa": "pozisyonu çok kısa tutuyor", "kopya_zarar": "kopyalayınca zarar"}


def _huni_html(kadro: dict | None) -> str:
    hn = (kadro or {}).get("huni") or {}
    if not hn:
        return VERI_YOK.format("kadroda huni özeti yok (yeni radar koşusundan sonra görünür)")
    adim = [("Evren", hn.get("evren")), ("Aday", hn.get("aday")), (f"≥{hn.get('islem_esik', 10)} işlem", hn.get("islem_yeterli")), ("Elemeyi geçen", hn.get("gecen")), ("Kadro", hn.get("kadro"))]
    ust = max([int(v or 0) for _, v in adim] + [1])
    cubuk = "".join(f'<div class="s"><span>{esc(ad)} · <b>{"—" if v is None else v}</b></span><div class="ol"><i style="width:{(int(v or 0) / ust * 100):.1f}%"></i></div></div>' for ad, v in adim)
    nd = hn.get("neden") or {}
    top = sum(nd.values()) or 1
    return cubuk + '<div class="ha">Elenme nedenleri</div>' + "".join(f'<div class="s"><b>{n}</b> × {esc(HUNI_TR.get(k, 'diğer'))} <span class="so">(%{n / top * 100:.0f})</span></div>' for k, n in list(nd.items())[:8])


def _karar_kutusu_html(ozet: dict) -> str:
    """31.12 karar kutusu (K-66 başarı ölçütü): aylık eşdeğer ≥ hedef VE aynı dönemde BTC al-tut'tan iyi. Motorun `ozet.json` alanları; yeni hesap yok."""
    ay, hd, bt, gt = ozet.get("aylik_esdeger"), ozet.get("aylik_hedef"), ozet.get("btc_al_tut_getiri"), ozet.get("getiri")
    hedef = "—" if ay is None or hd is None else ("evet" if ay >= hd else "hayır")
    btc = "—" if bt is None or gt is None else ("evet" if gt > bt else "hayır")
    gec = ozet.get("hedef_gecer")
    return (f'<div class="s">aylık eşdeğer ≥ %{tr_sayi(float(hd if hd is not None else 0.04) * 100, 0)}: <b>{hedef}</b> <span class="so">({esc(yuzde(ay))})</span></div>'
            f'<div class="s">BTC al-tut\'tan iyi: <b>{btc}</b> <span class="so">(biz {esc(yuzde(gt))} · BTC {esc(yuzde(bt))})</span></div>'
            f'<div class="s">Bugün itibarıyla: <b class="{"art" if gec else ("eks" if gec is False else "yok")}">{"GEÇİYOR" if gec else ("GEÇMİYOR" if gec is False else "—")}</b></div>'
            '<div class="ha">Değerlendirme 31.12.2026; geçmezse bu yapıyla gerçek para yok.</div>')


def _isabet_ozet_html(isabetler: list[dict], ozet: dict) -> str:
    """M-05: seçim isabeti ÖZETİ (karar kutusunun yanında): ölçüm sayısı, ortalama IC, İlk 11 − havuz / − elenen farkının ortalaması ve pozitif olan ölçüm payı."""
    if not isabetler:
        return VERI_YOK.format(isabet_yok_metni(ozet))
    ic = [float(i["ic"]) for i in isabetler if i.get("ic") is not None]
    fh = [float(i["fark_ilk11_havuz"]) for i in isabetler if i.get("fark_ilk11_havuz") is not None]
    fe = [float(i["fark_ilk11_elenen"]) for i in isabetler if i.get("fark_ilk11_elenen") is not None]
    ort = lambda x: sum(x) / len(x) if x else None                      # noqa: E731
    return (f'<div class="s">{len(isabetler)} ölçüm · ortalama sıralama uyumu <b>{"—" if not ic else tr_isaretli(ort(ic), 2)}</b></div>'
            f'<div class="s">İlk 11 − havuz ort. <b>{esc(yuzde(ort(fh)))}</b> <span class="so">({sum(1 for x in fh if x > 0)}/{len(fh)} pozitif)</span></div>'
            f'<div class="s">İlk 11 − elenen ort. <b>{esc(yuzde(ort(fe)))}</b> <span class="so">({sum(1 for x in fe if x > 0)}/{len(fe)} pozitif)</span></div>'
            '<div class="ha">Pozitif = seçilenler sonraki 7 günde havuzdan / elenenlerden iyi.</div>')


def _maruziyet_ozet_html(mo: dict) -> str:
    if mo["brut"] is None:
        return VERI_YOK.format("maruziyet kaydı birikiyor")
    return (f'<div class="s">kullanılan sermaye getirisi <b>{esc(yuzde(mo["sermaye_getirisi"]))}</b></div>'
            f'<div class="s">ort. brüt maruziyet <b>{esc(tl2(mo["brut"]))}</b> <span class="so">(kasanın {esc(yuzde(mo["brut_oran"], False))})</span></div>'
            f'<div class="s">ort. net maruziyet <b>{esc(tl2(mo["net"]))}</b> <span class="so">(kasanın {esc(yuzde(mo["net_oran"], False))})</span></div>'
            '<div class="ha">Kullanılan sermaye getirisi = (özsermaye − kasa) / zaman ağırlıklı ortalama brüt pozisyon</div>')


def _isabet_html(isabetler: list[dict], ozet: dict) -> str:
    if not isabetler:
        return VERI_YOK.format(isabet_yok_metni(ozet))
    satir = "".join(f'<tr><td>{esc(i["tarih"][5:])}</td><td class="sg">{"—" if i.get("ic") is None else tr_isaretli(i["ic"], 2)}</td><td class="sg">{esc(yuzde(i.get("fark_ilk11_havuz")))}</td>'
                    f'<td class="sg">{esc(yuzde(i.get("fark_ilk11_elenen")))}</td></tr>' for i in sorted(isabetler, key=lambda x: x["tarih"])[-7:])
    return (f'<div class="tw"><table><tr><th>HAVUZ</th><th class="sg">UYUM</th><th class="sg">İLK11−HAVUZ</th><th class="sg">İLK11−ELENEN</th></tr>{satir}</table></div>'
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
    return "".join(f'<div class="s"><b>{n}</b> × {esc(_neden_tr(neden))}{" (kaçırılan)" if neden in KACIRILAN_NEDENLER else ""} <span class="so">(%{n / toplam * 100:.0f})</span></div>'
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


def _rejim_sonuc_html(rs: dict | None) -> str:
    """Rejim ve duygu × işlem sonucu (son 7 gün; `durum/paylasim/rejim_sonuc_v1.json`, `copytrade.canli.rejim_sonuc` yazar). Yalnız biçim; yeni hesap yok. Veri yoksa "veri birikiyor"."""
    tablolar = rs.get("tablolar") if isinstance(rs, dict) else None
    if not isinstance(tablolar, dict) or not any(tablolar.get(a) for a in ("rejim_1d", "rejim_4h", "duygu")):
        return BIRIKIYOR

    def pnl_hucre(v: object, isaretli: bool = False) -> str:
        try:
            f = float(v)                                                                   # type: ignore[arg-type]
        except (TypeError, ValueError):
            return "—"
        return esc(tl2(f, isaretli))

    parca = []
    for anahtar, ad in (("rejim_1d", "Rejim (1g)"), ("rejim_4h", "Rejim (4s)"), ("duygu", "Duygu")):
        satirlar = tablolar.get(anahtar) or []
        govde = ""
        for r in satirlar:
            isabet = r.get("isabet_yuzde")
            isabet_metni = "—" if isabet is None else "%" + tr_sayi(float(isabet), 0)
            top = pnl_hucre(r.get("toplam_pnl"), True)
            govde += (f'<tr><td>{esc(REJIM_TR.get(str(r.get("etiket", "?")), str(r.get("etiket", "?"))))}</td><td class="sg">{int(r.get("n") or 0)}</td><td class="sg">{int(r.get("kazanan") or 0)}</td>'
                      f'<td class="sg">{isabet_metni}</td><td class="sg">{top}</td><td class="sg">{pnl_hucre(r.get("ortalama_pnl"))}</td></tr>')
        if not govde:
            govde = '<tr><td colspan="6">veri birikiyor</td></tr>'
        parca.append(f'<div class="ha" style="padding:6px 11px">{esc(ad)}</div>'
                     f'<div class="tw"><table><tr><th>{esc(ad)}</th><th class="sg">İŞLEM</th><th class="sg">KAZANAN</th><th class="sg">İSABET</th><th class="sg">TOPLAM</th><th class="sg">ORT.</th></tr>{govde}</table></div>')
    not_ = (f'<div class="ha" style="padding:6px 11px">Kapanan işlemler, pencere {int(rs.get("pencere_gun") or 7)} gün · gerçekleşen K/Z (ücret hariç) · '
            'giriş anı damgası; damgasız eski işlemler "bilinmiyor" kovasında.</div>')
    return "".join(parca) + not_


def tl2(v: float | None, isaretli: bool = False) -> str:
    return "—" if v is None else (tr_isaretli(v) if (isaretli or v < 0) else tr_sayi(v)) + " $"


def pencere_basi(gecmis: list[dict], donem: tuple[str, str, int] | None) -> tuple[float, str] | None:
    """S-4: kayıt penceresinin ilk gününden ÖNCEKİ son günlük özsermaye (`gecmis.json`, gün sonu) = pencere başı özsermaye. Yoksa None: seri pencere içinde başlamış (kayıt budanmamış), net = özsermaye − kasa."""
    if donem is None:
        return None
    once = [g for g in gecmis if g.get("gun") and g["gun"] < donem[0] and g.get("ozsermaye") is not None]
    return (float(once[-1]["ozsermaye"]), once[-1]["gun"]) if once else None


def tutma_sinifi(saat: float | None) -> str:
    """Fable 15.11 (yalnız bilgi): medyan pozisyon tutma süresi → scalp (< 0,5 sa) · kısa day (0,5–4 sa) · day (4–24 sa) · swing (> 24 sa)."""
    if saat is None:
        return "—"
    return "scalp" if saat < 0.5 else ("kısa day" if saat < 4 else ("day" if saat <= 24 else "swing"))


def _kaldirac_html(r: dict, kaldirac: dict | None) -> str:
    """Trader kartı kaldıraç bilgisi (yalnız gösterim): motorun `kaldirac_tr` kaydı (anlık nosyonel / hesap değeri) + radar 7g azami. Eksik veri "—"."""
    k = kaldirac or {}
    kal, hes = k.get("anlik_kaldirac"), k.get("hesap_usd")
    anlik = "—" if kal is None else f"{tr_sayi(float(kal), 1)}x" + ("" if hes is None else f" (hesap {tr_sayi(float(hes), 0)} $)")
    rad = "—" if r.get("max_kaldirac") is None else f"{tr_sayi(float(r['max_kaldirac']), 1)}x"
    return f'<div><span class="so">Anlık kaldıraç</span><br>{esc(anlik)}</div><div><span class="so">Radar azami (7g)</span><br>{rad}</div>'


def _tarz_html(r: dict) -> str:
    """Kadro satırının bilgi alanları (radar 15.11): medyan tutma süresi + sınıfı, haftalık devir (trader hafta hacmi / hesap ≈ kopya hacmi / slot). Kural DEĞİL; 1–2 hafta ölçüm için."""
    t, d = r.get("medyan_tutma_saat"), r.get("devir_hafta")
    if t is None and d is None:
        return ""
    t_txt = "—" if t is None else f"{tr_sayi(float(t), 1)} sa · {tutma_sinifi(float(t))}"
    d_txt = "—" if d is None else f"{tr_sayi(float(d), 1)}× / hafta"
    return (f'<div><span class="so">Pozisyon tutma (medyan)</span><br>{esc(t_txt)}</div>'
            f'<div><span class="so">Al-sat sıklığı (haftalık devir)</span><br>{esc(d_txt)}</div>')


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
            + satir(f"± Fonlama ücreti ({'HL' if kip == 'gercek' else 'sanal'})", funding, "+ alınan / − ödenen · pencere toplamı") + satir(net_ad, net, net_ipucu)
            + f'</table></div><div class="ha" style="padding:6px 11px">Toplam maliyet {esc(tl2(maliyet))} · {oran_txt}. Kayıt penceresi: {esc(donem_etiketi(donem))} (en çok {KAYIT_GUN} gün).</div>')


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


def _alinmayan_neden_html(satirlar: list[dict]) -> str:
    """Pano kartı "Alınmayan sinyaller (24 sa)" (yalnız bilgi): neden | adet | karşı-olgu PnL $ (hayali). Satır yoksa "veri birikiyor"."""
    if not satirlar:
        return BIRIKIYOR
    govde = "".join(f'<tr><td>{esc(_neden_tr(r["neden"]))}</td><td class="sg">{r["adet"]}</td>'
                    f'<td class="sg {"art" if (r["karsi_olgu_pnl"] or 0) >= 0 else "eks"}">{esc(tl2(r["karsi_olgu_pnl"], True))}</td></tr>'
                    for r in satirlar)
    return (f'<div class="tw"><table><tr><th>NEDEN</th><th class="sg">ADET</th><th class="sg">ALINSAYDI K/Z $</th></tr>{govde}</table></div>'
            '<div class="ha" style="padding:6px 11px">Alınsaydı K/Z: atlanan sinyal alınsaydı ne olurdu (hayali; ücret ve kayma yok). Henüz kapanmayanlar sayılmaz.</div>')


def _kopya_kalite_html(satirlar: list[dict]) -> str:
    """Pano kartı "Kopya kalitesi" (yalnız bilgi): gecikme/görme/kayma özeti; girdi 24 sa kayıtları. Dolan emir yoksa açıklama."""
    q = kopya_kalite(satirlar)
    sn = lambda v: "—" if v is None else f"{tr_sayi(v / 1000, 1)} sn"            # noqa: E731
    bp = lambda v: "—" if v is None else f"{tr_isaretli(v / 100, 2)}%"              # noqa: E731
    if not q["n"]:
        return BIRIKIYOR
    ad, az = q["ac_artir"], q["azalt_kapat"]
    return (f'<div class="mt">gecikme (trader dolumundan sonra): medyan {sn(q["gecikme_ms_medyan"])} · en yavaş %10 {sn(q["gecikme_ms_p90"])}</div>'
            f'<div class="mt">görme (trader dolumundan sonra): medyan {sn(q["gorme_ms_medyan"])}</div>'
            f'<div class="mt">kayma: medyan {bp(q["kayma_bps_medyan"])} · en kötü %10 {bp(q["kayma_bps_p90"])} (+ aleyhe)</div>'
            f'<div class="mt">açılış/artırma: {ad["n"]} dolum · kayma medyan {bp(ad["kayma_bps_medyan"])}</div>'
            f'<div class="mt">azaltma/kapanış: {az["n"]} dolum · kayma medyan {bp(az["kayma_bps_medyan"])}</div>')


BIRIKIYOR = '<div class="bos">veri birikiyor</div>'


REJIM_TR = {"trend_up": "yükseliş", "trend_down": "düşüş", "range": "yatay", "unclear": "belirsiz", "bilinmiyor": "bilinmiyor",
            "Extreme Fear": "aşırı korku", "Fear": "korku", "Neutral": "nötr", "Greed": "açgözlülük", "Extreme Greed": "aşırı açgözlülük"}


def _neden_tr(neden: str) -> str:
    """Atlama nedeni → sade Türkçe etiket (`ATLA_TR`); sözlükte olmayan teknik kod ham görünmez: "diğer" (Fable 19.11)."""
    return _sade(ATLA_TR.get(neden, "diğer"))


def _sade(etiket: str) -> str:
    """Etiketten teknik not eklerini atar: 'ters netleşme (K‑41)' → 'ters netleşme'."""
    return re.sub(r"\s*\(K[‑-]\d+\)", "", str(etiket)).replace("slot tavanı", "yer sınırı").replace("slot", "yer").strip()


def _kart(satirlar: list[tuple[str, str]], aciklama: str) -> str:
    """Ölçüm kartı gövdesi: 3-6 'ad: değer' satırı + TEK açıklama satırı (mevcut `.s` / `.ha` stilleri)."""
    return ("".join(f'<div class="s">{esc(ad)}: <b>{esc(deger)}</b></div>' for ad, deger in satirlar)
            + f'<div class="ha" style="padding-top:6px">{esc(aciklama)}</div>')


def _sunucu_satirlari(saglik: dict | None) -> list[str]:
    """Sunucu sağlığı ek satırları (gunluk_ozet saglik): son 1 saatte yeniden başlama, bellek yetmediği için kapanma. İkisi de yoksa boş."""
    if not isinstance(saglik, dict):
        return []
    n, oom = saglik.get("yeniden_baslama_1s"), saglik.get("oom_son")
    if n is None and oom is None:
        return []
    return [f'<div class="mt">yeniden başlama (son 1 sa): {"—" if n is None else int(n)}</div>',
            f'<div class="mt">bellek yetmediği için kapanma (son 1 sa): {"—" if oom is None else ("var" if oom else "yok")}</div>']


def _ogrenme_html(og: dict | None) -> str:
    """Pano kartı "Öğrenme etkisi" (yalnız bilgi): gunluk_ozet `ogrenme` alanı. Veri yoksa "veri birikiyor"; bilinmeyen alan "—"."""
    if not isinstance(og, dict) or not og:
        return BIRIKIYOR
    sayi = lambda v: "—" if v is None else tr_sayi(float(v), 0)                      # noqa: E731
    return _kart([("Öğrenmenin atladığı sinyal (bugün)", sayi(og.get("filtre_atlanan"))),
                  ("Atlananların hayali K/Z", tl2(og.get("filtre_karsi_olgu_pnl"), True)),
                  ("Küçültülen emir", sayi(og.get("ders_kucultulen"))),
                  ("Engellenen alım", sayi(og.get("ders_engellenen"))),
                  ("Geçerli ders", sayi(og.get("aktif_ders"))),
                  ("Emekli ders", sayi(og.get("emekli_ders")))],
                 "Öğrenme katmanı bugün kaç sinyali atladı ya da emri küçülttü; hayali K/Z, atlananlar alınsaydı ne olurdu.")


def _kural_maliyet_html(km: dict | None) -> str:
    """Pano kartı "Kural maliyeti" (yalnız bilgi): `durum/paylasim/kural_maliyet_v1.json`. Slot tavanı satırı ilk; ardından en büyük 3 neden. Veri yoksa "veri birikiyor"."""
    satirlar = km.get("satirlar") if isinstance(km, dict) else None
    if not isinstance(satirlar, list) or not satirlar:
        return BIRIKIYOR
    gun = int(km.get("pencere_gun") or 7)
    v = ((km.get("vurgu") or {}).get("slot_tavani")) or next((r for r in satirlar if r.get("neden") == "slot_tavani"), None)
    ilk = ("Yer sınırı", "yok" if not v else f'{int(v.get("olay_adedi") or 0)} sinyal · {int(v.get("trader_sayisi") or 0)} trader · {tl2(v.get("toplam_karsi_olgu_pnl"), True)}')
    digerleri = sorted((r for r in satirlar if r.get("neden") != "slot_tavani"), key=lambda r: -abs(float(r.get("toplam_karsi_olgu_pnl") or 0.0)))[:2]
    return _kart([ilk, *[(_neden_tr(r["neden"]), f'{int(r.get("olay_adedi") or 0)} sinyal · {tl2(r.get("toplam_karsi_olgu_pnl"), True)}') for r in digerleri]],
                 f"Son {gun} günde kurallar yüzünden alınmayan sinyallerin hayali K/Z toplamı (alt sınır).")


def _secim_rastgele_html(isabetler: list[dict] | None, sg: dict | None) -> str:
    """Pano kartı "Seçim × rastgele" (yalnız bilgi): radar isabet `rastgele_karsilastirma` (seçilen 11 ↔ aynı havuzdan rastgele 11); yoksa `secim_gercek_v1.json` (form sırası ↔ gerçek K/Z). İkisi de yoksa "veri birikiyor"."""
    ok = [r for r in ((i.get("rastgele_karsilastirma") or {}) for i in (isabetler or [])) if r.get("durum") == "tamam"]
    if ok:
        r = ok[-1]
        yz = r.get("yuzdelik")
        return _kart([("Seçilen 11 · son ölçüm (7 gün sonrası ort.)", tr_yuzde(float(r["secilen_ortalama"]))),
                      ("Rastgele 11 · son ölçüm (ortanca)", tr_yuzde(float(r["rastgele_medyan"]))),
                      ("Seçimin sırası (50 = şans)", "—" if yz is None else tr_sayi(float(yz), 0)),
                      ("Şansla olma ihtimali", "—" if r.get("p") is None else "%" + tr_sayi(float(r["p"]) * 100, 0)),
                      ("Ölçülen gün", str(len(ok)))],
                     "Seçtiğimiz 11 trader, aynı havuzdan rastgele seçilecek 11'den daha iyi mi? Sıra 50'nin üstüyse evet.")
    t = (sg or {}).get("toplu") if isinstance(sg, dict) else None
    if isinstance(t, dict) and t.get("durum") == "tamam":
        return _kart([("Ölçülen gün", str(int(t.get("gun_n") or 0))),
                      ("Form sırası ↔ gerçek K/Z ilişkisi", tr_isaretli(float(t["rho_ort"]), 2)),
                      ("Şansla olma ihtimali", "%" + tr_sayi(float(t["p"]) * 100, 0))],
                     "Form puanı yüksek trader gerçekten daha çok kazandırıyor mu? 0'ın üstü evet, 0 civarı şans demek.")
    return BIRIKIYOR


def _kaynak_html(kaynak: dict | None, saglik: dict | None = None) -> str:
    """Pano kartı "Sunucu kaynakları" (yalnız bilgi): motor.json "kaynak" (copytrade/canli/kaynak.py). Ölçüm yoksa "veri birikiyor"; ölçülemeyen alan "—". `saglik` (gunluk_ozet "saglik"): yeniden başlama + bellek kapanması satırları eklenir."""
    sunucu = _sunucu_satirlari(saglik)
    if not isinstance(kaynak, dict) or not kaynak:
        return "".join(sunucu) if sunucu else BIRIKIYOR
    mb = lambda v: "—" if v is None else f"{tr_sayi(float(v), 0)} MB"            # noqa: E731
    gb = lambda v: "—" if v is None else f"{tr_sayi(float(v), 1)} GB"            # noqa: E731
    yuk = lambda v: "—" if v is None else tr_sayi(float(v), 2)                   # noqa: E731
    olc = kaynak.get("olc_ms")
    zaman = "—" if olc is None else f"{_tsi(int(olc))} TSİ"
    return (f'<div class="mt">RAM: {mb(kaynak.get("ram_mb"))} · tepe {mb(kaynak.get("ram_tepe_mb"))}</div>'
            f'<div class="mt">bellek (servis): {mb(kaynak.get("cgroup_mb"))}</div>'
            f'<div class="mt">yük (1 dk): {yuk(kaynak.get("yuk_1dk"))} · disk boş: {gb(kaynak.get("disk_bos_gb"))}</div>'
            f'<div class="mt">ölçüm zamanı: {zaman}</div>' + "".join(sunucu))



# ------------------------------------------------------------------------------------------------------------------------------ pano v2 (6 sekme): saf yardımcılar
SEKMELER = ("ÖZET", "AÇIK", "KAPANAN", "K/Z", "ÖĞRENME", "TEKNİK")
UCRET_YOK = "Henüz ölçülemedi"
NEDEN_KAPANIS = {"tasfiye": "Tasfiye", "felaket_stop": "Stop", "borsa_stop": "Stop", "borsa_stop_korumasiz": "Stop", "iz_suren_koruma": "İz süren",
                 "tam_kapanis": "Trader kapattı", "kucuk_kalan_kapat": "Trader kapattı", "trader_kapali_senkron": "Trader kapattı",
                 "trader_ters_senkron": "Trader yön değiştirdi", "inen_ters": "Konsensüs döndü",
                 "tamam": "Trader azalttı", "min_emir_yuvarlandi": "Trader azalttı", "slot_tavani": "Trader azalttı"}
RISK_TR = {"risk": "risk freni", "dur": "motor durduruldu", "dur_tamam": "motor durdu", "mutabakat_alarm": "hesap uyuşmazlığı", "mutabakat_duzeldi": "hesap uyuşmazlığı giderildi",
           "kapanis_eksik": "kapanış eksik kaldı", "tasfiye": "zorla kapanma", "kuyruk_tasti": "olay kuyruğu taştı", "vardiya_boslugu": "çalışma kesintisi",
           "vardiya_baslamadi": "çalışma başlamadı", "telegram_yetkisiz": "yetkisiz Telegram denemesi"}
NEDEN_AYRINTI = {"tasfiye": "Sanal tasfiye (zorla kapanma)", "felaket_stop": "Zarar stopu", "borsa_stop": "Borsa stopu", "borsa_stop_korumasiz": "Borsa stopu (koruma kurulamadı)", "iz_suren_koruma": "İz süren koruma",
                 "tam_kapanis": "Trader pozisyonu kapattı", "kucuk_kalan_kapat": "Trader pozisyonu kapattı (küçük kalan)", "trader_kapali_senkron": "Trader pozisyonu kapattı",
                 "trader_ters_senkron": "Trader ters yöne geçti", "inen_ters": "Takipten ayrılan trader'ın pozisyonu, başka bir trader ters yönde açınca kapandı",
                 "tamam": "Trader pozisyonunu küçülttü", "min_emir_yuvarlandi": "Trader pozisyonunu küçülttü", "slot_tavani": "Trader pozisyonunu küçülttü"}
YAS_KODLARI = ("vardiya_gecikti", "vardiya_durdu", "veri_dali_bayat", "veri_dali_durdu")                 # veri yaşı sayısı tek yerde (üstteki uyarı satırı); sağlık listesinde tekrar edilmez
TSI_GUN_MS = 3 * SAAT_MS


def tsi_gun_basi(ms: int) -> int:
    """İçinde bulunulan TSİ gününün başlangıcı (00:00 TSİ, ms). YALNIZ gösterim: motorun günlük kayıp sınırı hâlâ kendi gün başı özsermayesini kullanır."""
    return ((int(ms) + TSI_GUN_MS) // GUN_MS) * GUN_MS - TSI_GUN_MS


def _tl(v: float | None, isaretli: bool = False) -> str:
    return "—" if v is None else (tr_isaretli(v) if isaretli else tr_sayi(v)) + " $"


def _tyuz(v: float | None) -> str:
    return "—" if v is None else tr_yuzde(v)


def _renk(v: float | None) -> str:
    return "yok" if v is None else ("art" if v >= 0 else "eks")


def fiyat(v: float | None) -> str:
    """Fiyat kademeli ondalık: ≥ 1 $ → 2, < 1 $ → 4, < 0,01 $ → 6 (küçük coinlerde "0,08" hiçbir şey söylemez). Dolar K/Z her zaman 2 ondalık."""
    if v is None:
        return "—"
    a = abs(float(v))
    return tr_sayi(float(v), 2 if a >= 1 or a == 0 else (4 if a >= 0.01 else 6))


def sure_metni(ms: float | None) -> str:
    """Süre → '45 dk' · '3 sa 20 dk' · '2 g 4 sa'."""
    if ms is None or ms < 0:
        return "—"
    dk = int(ms // 60_000)
    if dk < 60:
        return f"{dk} dk"
    if dk < 1440:
        return f"{dk // 60} sa {dk % 60} dk"
    return f"{dk // 1440} g {dk % 1440 // 60} sa"


def risk_durumu(oz: float, gun_basi: float | None, gk_sinir: float, durdu: bool) -> tuple[str, str, str]:
    """Üst şerit "Risk durumu": (sınıf, metin, alt yazı). Durdu = motor durdu / açılış freni / günlük sınır doldu (kırmızı); günlük kayıp sınırının ≥ %70'i kullanıldıysa "Limite yakın" (sarı); aksi hâlde "Güvenli".
    Yalnız gösterim: sınır ve gün başı özsermayesi motorun kendisinden (risk.json + kurallar.yaml); burada yeni hesap/karar yok."""
    if gun_basi is None or float(gun_basi) <= 0 or gk_sinir <= 0:
        return ("eks", "Durdu", "") if durdu else ("yok", "—", "günlük limit verisi birikiyor")
    limit = float(gun_basi) * gk_sinir
    kayip = max(float(gun_basi) - oz, 0.0)
    pay = round(kayip / limit, 9)
    alt = f"günlük limite kalan {_tl(max(limit - kayip, 0.0))}"
    if durdu or pay >= 1.0:
        return "eks", "Durdu", alt
    return ("bk", "Limite yakın", alt) if pay >= 0.7 else ("art", "Güvenli", alt)


def ozsermaye_serisi(kayitlar: list[dict], ds: dict, oz: float, kasa: float, simdi_ms: int, gecmis: list[dict] | None = None) -> list[tuple[int, float]]:
    """Özsermaye zaman serisi [(ms, $)] (eskiden yeniye): dönem başı (= kasa) + her UTC gün sonu (`donem_seri.gunler`) + tur noktaları (kayıt) + şimdi. Yeni hesap yok: motorun yazdığı değerler."""
    nok: dict[int, float] = {}
    bas = ds.get("bas_ms")
    if bas and kasa:
        nok[int(bas)] = float(kasa)
    for g in ds.get("gunler") or []:
        if g.get("ozsermaye_usd") is not None and g.get("gun"):
            ms = min(int(datetime.fromisoformat(g["gun"]).replace(tzinfo=UTC).timestamp() * 1000) + GUN_MS, simdi_ms)
            nok[ms] = float(g["ozsermaye_usd"])
    for g in gecmis or []:                                                                                  # pano/gecmis.json: günde bir gün sonu noktası (dönem serisi yoksa yedek)
        if g.get("ozsermaye") is not None and g.get("gun"):
            nok.setdefault(min(int(datetime.fromisoformat(g["gun"]).replace(tzinfo=UTC).timestamp() * 1000) + GUN_MS, simdi_ms), float(g["ozsermaye"]))
    for k in kayitlar:
        if k.get("olay") == "tur" and k.get("ozsermaye_usd") is not None and k.get("zaman_ms"):
            nok[int(k["zaman_ms"])] = float(k["ozsermaye_usd"])
    nok[int(simdi_ms)] = float(oz)
    return sorted(nok.items())


def deger_an(seri: list[tuple[int, float]], ms: int) -> float | None:
    """`ms` anındaki (ya da hemen öncesindeki) özsermaye; seri o ana kadar başlamadıysa None."""
    onceki = [v for t, v in seri if t <= ms]
    return onceki[-1] if onceki else None


def donem_kz(seri: list[tuple[int, float]], oz: float, kasa: float, simdi_ms: int, bas_ms: int | None, gun_basi: float | None) -> list[tuple[str, float | None, float | None]]:
    """K/Z sekmesi: Bugün (TSİ günü) / 7 gün / 30 gün / Toplam → (etiket, $, oran = $ / pencere başı özsermaye). Dönem pencereden kısaysa taban kasa; veri yoksa (None, None)."""
    def pencere(ms: int, yedek: float | None = None) -> tuple[float | None, float | None]:
        if bas_ms and ms <= int(bas_ms):
            taban: float | None = kasa
        else:
            taban = deger_an(seri, ms)
            if taban is None:
                taban = yedek
        return (None, None) if not taban or taban <= 0 else (oz - taban, (oz - taban) / taban)
    bugun = pencere(tsi_gun_basi(simdi_ms), gun_basi)
    return [("Bugün", *bugun), ("Son 7 gün", *pencere(simdi_ms - 7 * GUN_MS)), ("Son 30 gün", *pencere(simdi_ms - 30 * GUN_MS)),
            ("Toplam", oz - kasa, (oz - kasa) / kasa if kasa > 0 else None)]


def kapanan_islemler(kayitlar: list[dict], felaket_oran: float = 0.0) -> list[dict]:
    """KAPANAN sekmesi: kapanış dolumları TEK TEK (toplu değil), yeniden eskiye. Satır = bir `reduce_only` dolum (tam kapanış ya da trader'ın azaltması); net = gerçekleşen K/Z − o dolumun ücreti.
    Pozisyon kimliği (`poz`): aynı (trader, coin) için tam kapanışa (`kapat`) kadar olan tüm azaltmalar + son kapanış tek pozisyondur (kazanma oranı pozisyon bazında sayılır).
    Giriş fiyatı: açılış dolumlarının (trader fiyatı ↔ bizim dolum fiyatı) miktar ağırlıklı ortalaması; kayıtta açılış yoksa bizim giriş K/Z'den geri çıkarılır. Süre = ilk açılış dolumundan beri.
    Neden = kapanış kodu (bilinmeyen → "diğer"); `ayrinti` = ayrıntı satırı (zarar stopu ↔ borsa stopu ayrı)."""
    acik: dict[tuple, dict] = {}
    seq: dict[tuple, int] = {}
    cikti: list[dict] = []
    emirler = sorted((k for k in kayitlar if k.get("olay") == "emir" and k.get("durum") in ("dolu", "kismi")), key=lambda k: int(k.get("zaman_ms") or 0))
    for k in emirler:
        anahtar = (k.get("adres"), k.get("coin"))
        ms = int(k.get("zaman_ms") or 0)
        if not k.get("reduce_only"):
            o = acik.setdefault(anahtar, {"ms": ms, "ders": k.get("ders_carpan"), "sz": 0.0, "tr": 0.0, "biz": 0.0, "n": 0, "kalan": 0.0})
            s_ = abs(float(k.get("sz") or 0.0))
            o["tepe"] = o.get("tepe", 0.0) + s_                                                            # toplam açılan büyüklük (toz toleransı tabanı)
            o["kalan"] = o.get("kalan", 0.0) + s_                                                          # açık büyüklük (kapanış tespiti: sıfıra inince pozisyon bitmiştir)
            if k.get("trader_px") is not None and k.get("dolum_px") is not None and s_ > 0:
                o["sz"] += s_
                o["tr"] += s_ * float(k["trader_px"])
                o["biz"] += s_ * float(k["dolum_px"])
            continue
        if k.get("pnl_usd") is None:
            continue
        o = acik.get(anahtar) or {}
        sz_k = abs(float(k.get("sz") or 0.0))
        kalan = o["kalan"] - sz_k if "kalan" in o else None
        tam = k.get("eylem") == "kapat" or (kalan is not None and kalan <= 1e-4 * o.get("tepe", o["kalan"]))      # toz: açılan büyüklüğün %0,01'i altı kalıntı = sıfır      # kapat / azaltmalarla sıfıra iniş / tasfiye: hepsi pozisyon sonu
        if "kalan" in o:
            o["kalan"] = max(kalan, 0.0)
        poz = (anahtar[0], anahtar[1], seq.get(anahtar, 0))
        if tam:
            acik.pop(anahtar, None)
            seq[anahtar] = seq.get(anahtar, 0) + 1
        pnl, ucret, sz, cikis = float(k["pnl_usd"]), float(k.get("ucret") or 0.0), abs(float(k.get("sz") or 0.0)), k.get("dolum_px")
        uzun = k.get("yon") == "A"                                                                         # kapatan emir SAT ise pozisyon uzundu
        giris = o["biz"] / o["sz"] if o.get("sz") else (None if not sz or cikis is None else (float(cikis) - pnl / sz if uzun else float(cikis) + pnl / sz))
        tr_giris = o["tr"] / o["sz"] if o.get("sz") else None
        net = pnl - ucret
        kod = str(k.get("boyut_neden") or "")
        ayr = NEDEN_AYRINTI.get(kod, "Bilinmeyen kapanış nedeni")
        if kod == "felaket_stop" and felaket_oran > 0:
            ayr += f" (%{tr_sayi(felaket_oran * 100, 0)})"
        tr_cikis = k.get("trader_px")
        cikti.append({"ms": ms, "adres": str(k.get("adres") or ""), "coin": str(k.get("coin") or ""), "yon": "uzun" if uzun else "kısa", "net": net, "poz": poz, "kapat": tam,
                      "oran": (net / (sz * giris)) if giris and sz else None, "neden": NEDEN_KAPANIS.get(kod, "diğer"), "ayrinti": ayr,
                      "giris": giris, "tr_giris": tr_giris, "cikis": None if cikis is None else float(cikis), "tr_cikis": None if tr_cikis is None else float(tr_cikis),
                      "giris_fark": None if not giris or not tr_giris else ((giris - tr_giris) if uzun else (tr_giris - giris)) / tr_giris,                    # + = bizim aleyhe
                      "cikis_fark": None if cikis is None or not tr_cikis else ((float(tr_cikis) - float(cikis)) if uzun else (float(cikis) - float(tr_cikis))) / float(tr_cikis),
                      "sure_ms": (ms - o["ms"]) if o.get("ms") else None, "ucret": ucret, "ders": o.get("ders")})
    return sorted(cikti, key=lambda r: -r["ms"])


def kapanan_ozeti(satirlar: list[dict], tum: list[dict] | None = None) -> dict:
    """Dönem özeti: `kapanis` (dolum adedi), `poz` (tamamen kapanan pozisyon sayısı; kısmi kapanışlar ayrı sayılmaz), `kazanma` (pozisyon bazında, sonuç = pozisyonun TÜM kapanışlarının net toplamı > 0),
    `net` (dönemdeki tüm kapanış satırlarının net toplamı), `ort_kazanc` / `ort_kayip` (pozisyon başına). `tum`: pozisyonun dönem dışındaki kısmi kapanışlarını da toplamak için tüm satırlar."""
    toplam: dict[tuple, float] = {}
    for r in (tum if tum is not None else satirlar):
        toplam[r["poz"]] = toplam.get(r["poz"], 0.0) + r["net"]
    sonuc = [toplam[k] for k in {r["poz"] for r in satirlar if r["kapat"]}]
    kaz, kay = [x for x in sonuc if x > 0], [x for x in sonuc if x < 0]
    return {"kapanis": len(satirlar), "poz": len(sonuc), "kazanma": (len(kaz) / len(sonuc) if sonuc else None), "net": sum(r["net"] for r in satirlar),
            "ort_kazanc": (sum(kaz) / len(kaz) if kaz else None), "ort_kayip": (sum(kay) / len(kay) if kay else None)}


def acik_satirlari(acik: list[dict], hesap: dict, kurallar: dict, simdi_ms: int, kip: str) -> list[dict]:
    """AÇIK sekmesi satırları (yeniden eskiye). Ayrıntı alanları `hesap.json` `poz` kaydından (açılış zamanı, kaldıraç, iz süren zirve kâr); yoksa "—"."""
    poz = hesap.get("poz") or {}
    fel = float(kurallar.get("canli_felaket_stop_oran", 0) or 0)
    iz_acik = kip == "sanal" and bool(kurallar.get("sanal_iz_suren", False))
    bb, kl, ks = float(kurallar.get("iz_basabas_oran", 0.15)), float(kurallar.get("iz_kilit_oran", 0.30)), float(kurallar.get("iz_kilit_seviye", 0.15))
    cikti = []
    for q in acik:
        p = (poz.get(q["adres"]) or {}).get(q["coin"]) or {}
        sz = float(q["sz"])
        giris = q.get("giris") if q.get("giris") is not None else p.get("giris")
        kz = q.get("kz_usd")
        taban = abs(sz) * float(giris) if giris else None
        zk = float(p.get("zirve_kar") or 0.0)
        if not iz_acik:
            iz = "yalnız sanal kipte çalışır"
        elif zk >= kl:
            iz = f"kâr kilitli: fiyat dönerse +%{tr_sayi(ks * 100, 0)} kârda kapanır"
        elif zk >= bb:
            iz = "başa baş: kâr girişe inerse kapanır"
        else:
            iz = f"henüz devrede değil (en yüksek kâr %{tr_sayi(zk * 100, 1)}; %{tr_sayi(bb * 100, 0)}'te başlar)"
        stop = "—" if not giris or fel <= 0 else f"{fiyat(float(giris) * (1 - fel if sz > 0 else 1 + fel))} (girişten %{tr_sayi(fel * 100, 0)} aleyhe)"
        cikti.append({"adres": q["adres"], "coin": q["coin"], "yon": "uzun" if sz > 0 else "kısa", "giris": giris, "mark": q.get("mark"), "kz": kz,
                      "oran": None if kz is None or not taban else float(kz) / taban, "acilis_ms": p.get("acilis_ms"), "sure_ms": (simdi_ms - int(p["acilis_ms"])) if p.get("acilis_ms") else None,
                      "usd": q.get("usd"), "kaldirac": p.get("kaldirac"), "iz": iz, "stop": stop})
    return sorted(cikti, key=lambda r: -(int(r["acilis_ms"]) if r["acilis_ms"] else 0))


def kaynak_kz(hesap: dict, acik: list[dict], uyeler: dict, inenler: dict, kapananlar: list[dict]) -> list[dict]:
    """K/Z sekmesi "Kaynak başına": trader başına net K/Z = gerçekleşen − ücret + fonlama + açık K/Z (kadro kartlarıyla aynı tanım); açık K/Z'si bilinmeyen trader "—". İşlem = kayıt penceresindeki kapanış dolumu."""
    gerc, ucr, fnd, slot = hesap.get("realize") or {}, hesap.get("ucret") or {}, hesap.get("funding") or {}, hesap.get("slot_bas") or {}
    bilinmiyor = {q["adres"] for q in acik if q.get("kz_usd") is None}
    acik_kz: dict[str, float] = {}
    for q in acik:
        if q.get("kz_usd") is not None:
            acik_kz[q["adres"]] = acik_kz.get(q["adres"], 0.0) + float(q["kz_usd"])
    adet = Counter(r["adres"] for r in kapananlar)
    cikti = []
    for ad in dict.fromkeys([*slot, *uyeler, *inenler]):
        net = None if ad in bilinmiyor or ad not in slot else float(gerc.get(ad, 0.0)) - float(ucr.get(ad, 0.0)) + float(fnd.get(ad, 0.0)) + acik_kz.get(ad, 0.0)
        cikti.append({"adres": ad, "net": net, "adet": adet.get(ad, 0), "durum": "açık" if ad in uyeler else "durduruldu"})
    return sorted(cikti, key=lambda r: (r["net"] is None, -(r["net"] or 0.0)))


def _alias_haritasi(adresler: set[str]) -> dict[str, str]:
    """Takma ad (`T_xxxxxx`) → adres (yalnız bellekte; hiçbir dosyaya yazılmaz): ders/ML olayları takma adla tutulur, panoda trader adı gösterilebilsin diye."""
    from copytrade.canli.ogrenme_adaptor import takma_ad
    return {takma_ad(a): a for a in adresler if a}


def ogrenme_ozeti(kayitlar: list[dict], ozet: dict, gunluk: dict | None, kurallar: dict, simdi_ms: int, adlar: dict[str, str]) -> dict:
    """ÖĞRENME sekmesi verisi (ders + makine öğrenmesi). Ölçülemeyen her şey None: panoda "Henüz ölçülemedi (n işlem, en az N gerek)"; uydurma sayı YOK.
    Ders katkısı = (ders yüzünden alınmayan işlemlerin hayali K/Z toplamı) × −1; ML katkısı = (ML'in almadığı işlemlerin hayali K/Z toplamı) × −1 (pozitif = ders/ML bize kazandırdı)."""
    og = [r for r in (ozet.get("ogrenme") or []) if isinstance(r, dict)]
    g_og = (gunluk or {}).get("ogrenme") or {}
    sanal = str(ozet.get("kip", "sanal")) == "sanal"
    var = bool(og or g_og)
    ders_kural = sanal and bool(kurallar.get("ogrenme_aktif", True))
    ml_kural = ders_kural and bool(kurallar.get("ogrenme_filtre_aktif", True))
    gun7 = simdi_ms - 7 * GUN_MS
    emir7 = [k for k in kayitlar if k.get("olay") == "emir" and k.get("durum") in ("dolu", "kismi") and not k.get("reduce_only") and int(k.get("zaman_ms") or 0) >= gun7]
    ad_ = lambda alias: kisa(adlar[alias]) if alias in adlar else "bir trader"               # noqa: E731
    # --- ders
    kucuk = sum(1 for k in emir7 if k.get("ders_carpan") is not None and float(k["ders_carpan"]) < 1.0)
    engel = sum(1 for k in kayitlar if k.get("olay") == "emir_yok" and k.get("neden") == "ders_emekli" and int(k.get("zaman_ms") or 0) >= gun7)
    aktif_ders = int(g_og.get("aktif_ders") or sum(1 for r in og if r.get("carpan") or r.get("emekli")))
    olaylar = sorted((k for k in kayitlar if k.get("olay") in ("ders_uygulandi", "ders_geri_alindi")), key=lambda k: -int(k.get("zaman_ms") or 0))[:5]
    def cumle(k: dict) -> str:
        ad = ad_(str(k.get("kurulum")))
        if k["olay"] == "ders_geri_alindi":
            return f"{ad}: ders geri alındı, güven eski haline döndü"
        if k.get("tur") == "emekli":
            return f"{ad}: son işlemleri kaybettirdi, yeni alımları durduruldu (güven sıfırlandı)"
        c = k.get("carpan")
        return f"{ad}: son işlemleri kaybettirdi, alım boyutu %{tr_sayi(float(c) * 100, 0)}'e düşürüldü (güven azaldı)" if c else f"{ad}: son işlemleri kaybettirdi, alım boyutu küçüldü (güven azaldı)"
    dersler = [(int(k.get("zaman_ms") or 0), cumle(k)) for k in olaylar]
    guven = [f"{ad_(str(r.get('kurulum')))}: " + ("yeni alımlar durduruldu" if r.get("emekli") else f"alım boyutu %{tr_sayi(float(r['carpan']) * 100, 0)}'e düşürüldü") for r in og if r.get("emekli") or r.get("carpan")]
    ders_ko = [float(k.get("pnl_usd") or 0.0) for k in kayitlar if k.get("olay") == "karsi_olgu_kapandi" and k.get("neden") == "ders_emekli"]
    ders_min = 30
    ders_var = aktif_ders > 0 or bool(dersler)
    gun_n = (kayit_donemi(kayitlar) or ("", "", 0))[2]
    # --- ML
    min_n = int(kurallar.get("ogrenme_filtre_min_n", 20))
    islem = max([int(r.get("alinan") or 0) for r in og] or [0])
    modelli = {str(r["kurulum"]) for r in og if r.get("filtre")}
    ret = [k for k in kayitlar if k.get("olay") == "ml_filtre_atla"]
    ret7 = [k for k in ret if int(k.get("zaman_ms") or 0) >= gun7]
    ml_ko = sorted((k for k in kayitlar if k.get("olay") == "karsi_olgu_kapandi" and k.get("neden") == "ml_filtre_atla"), key=lambda k: int(k.get("zaman_ms") or 0))
    adaylar = sorted((k for k in kayitlar if k.get("olay") == "ogrenme_aday" and k.get("net_usd") is not None), key=lambda k: int(k.get("zaman_ms") or 0))
    egitim = [k for k in kayitlar if k.get("olay") == "ml_filtre_egitildi"]
    al = [k for k in kayitlar if k.get("olay") == "ml_filtre_al"]
    al7 = [k for k in al if int(k.get("zaman_ms") or 0) >= gun7]
    kullanilan_ko: set[int] = set()
    kullanilan_ad: set[int] = set()
    kararlar_hepsi = []                                                                                                # (ms, coin, karar, sonuç $ | None, doğru mu | None)
    for k in sorted([*ret, *al], key=lambda k: int(k.get("zaman_ms") or 0)):
        ms = int(k.get("zaman_ms") or 0)
        if k.get("olay") == "ml_filtre_atla":                                                                           # ret: karşı-olgu K/Z < 0 ise ret doğruydu
            s_ = next(((i_, c) for i_, c in enumerate(ml_ko) if i_ not in kullanilan_ko and c.get("coin") == k.get("coin") and int(c.get("zaman_ms") or 0) >= ms), None)
            if s_:
                kullanilan_ko.add(s_[0])
            pnl = None if s_ is None else float(s_[1].get("pnl_usd") or 0.0)
            kararlar_hepsi.append((ms, str(k.get("coin") or "?"), "almadı", pnl, None if pnl is None else pnl < 0))
        else:                                                                                                          # onay: aynı (kurulum, coin) için sonraki kapanan işlem net K/Z > 0 ise onay doğruydu
            s_ = next(((i_, c) for i_, c in enumerate(adaylar) if i_ not in kullanilan_ad and c.get("kurulum") == k.get("kurulum") and c.get("coin") == k.get("coin") and int(c.get("zaman_ms") or 0) >= ms), None)
            if s_:
                kullanilan_ad.add(s_[0])
            net = None if s_ is None else float(s_[1]["net_usd"])
            kararlar_hepsi.append((ms, str(k.get("coin") or "?"), "aldı", net, None if net is None else net > 0))
    kararlar_hepsi.sort(key=lambda x: -x[0])
    sonuclu = [x for x in kararlar_hepsi if x[4] is not None][:20]
    kararlar = [x[:4] for x in kararlar_hepsi[:5]]
    return {"var": var, "ders_acik": ders_kural and var, "ders_kural": ders_kural, "kucuk": kucuk, "engel": engel, "aktif_ders": aktif_ders, "dersler": dersler, "guven": guven,
            "ders_katki": (-sum(ders_ko) if len(ders_ko) >= ders_min else None), "ders_n": len(ders_ko), "ders_min": ders_min, "gun_n": gun_n,
            "ml_kural": ml_kural, "model": bool(modelli), "islem": islem, "min_n": min_n, "ret7": len(ret7), "onay7": len(al7),
            "isabet": (sum(1 for x in sonuclu if x[4]), len(sonuclu)) if modelli and len(sonuclu) >= 10 else None, "isabet_n": len(sonuclu), "ders_var": ders_var,
            "ml_katki": (-sum(float(k.get("pnl_usd") or 0.0) for k in ml_ko) if modelli and len(ml_ko) >= min_n else None), "ml_ko_n": len(ml_ko),
            "egitim": (int(egitim[-1].get("zaman_ms") or 0), egitim[-1].get("n_egitim")) if egitim else None, "kararlar": kararlar}


_EK3 = {0: "ı", 1: "i", 2: "si", 3: "ü", 4: "ü", 5: "i", 6: "sı", 7: "si", 8: "i", 9: "u", 10: "u", 11: "i", 12: "si", 13: "ü", 14: "ü", 15: "i", 16: "sı", 17: "si", 18: "i", 19: "u", 20: "si"}     # Türkçe iyelik eki: 8'i, 12'si, 3'ü


def _kv(satirlar: list[tuple[str, str]]) -> str:
    """Ad / değer satırları (değer HTML; çağıran kaçışlar)."""
    return "".join(f'<div class="kv"><span>{esc(ad)}</span><b>{deger}</b></div>' for ad, deger in satirlar)


def _rozet(sinif: str, metin: str) -> str:
    return f'<span class="rz {sinif}">{esc(metin)}</span>'


def _olculemedi(n: int, en_az: int) -> str:
    return f'<span class="so">Veri birikiyor: {n}/{en_az} işlem</span>'


def ders_karti(d: dict, tam: bool) -> str:
    """Ders kartı. Ders yokken SARI "Açık, henüz ders çıkmadı"; ders çıktıysa ve işlemleri etkiliyorsa yeşil; ders çıktığı hâlde son 7 günde hiçbir işleme uygulanmadıysa KIRMIZI. `tam` = ÖĞRENME sekmesi; ÖZET'te tek satır."""
    if not d["var"] and d["ders_kural"]:
        durum = _rozet("yok", "veri birikiyor")
    elif not d["ders_acik"]:
        durum = _rozet("yok", "Kapalı")
    elif not d["ders_var"]:
        durum = _rozet("bk", "Açık, henüz ders çıkmadı")
    elif d["kucuk"] + d["engel"] > 0:
        durum = _rozet("art", "Açık, işlemleri etkiliyor")
    else:
        durum = _rozet("eks", "Açık ama işlemlere uygulanmıyor")
    if not tam:
        return f'<div class="s">{durum}' + (f' <span class="so">son: {_tsi(d["dersler"][0][0], "%d.%m")}</span>' if d["dersler"] else "") + "</div>"
    son = f'{_tsi(d["dersler"][0][0], "%d.%m")} · {esc(d["dersler"][0][1])}' if d["dersler"] else '<span class="so">henüz ders çıkmadı</span>'
    katki = (f'<span class="{_renk(d["ders_katki"])}">{esc(_tl(d["ders_katki"], True))}</span>' if d["ders_katki"] is not None else _olculemedi(d["ders_n"], d["ders_min"]))
    return (_kv([("Durum", durum), ("Son öğrendiği", son),
                 ("Son 7 günde değişen işlem", f'{d["kucuk"] + d["engel"]} ({d["kucuk"]} küçüldü · {d["engel"]} engellendi)'),
                 (f"Katkı (son {d['gun_n']} gün, derssiz fark)", katki)])
            + ('<div class="ha" style="padding-top:8px">Güven değişimi</div>' + "".join(f'<div class="s">{esc(x)}</div>' for x in d["guven"]) if d["guven"] else ""))


def ml_karti(d: dict, tam: bool) -> str:
    """Makine öğrenmesi kartı. Model henüz eğitilmediyse tek satır "Veri birikiyor: X/N işlem" (uydurma sayı yok). ÖZET'te (`tam` = False) tek satır."""
    if not d["var"] and d["ml_kural"]:
        durum = _rozet("yok", "veri birikiyor")
    elif not d["ml_kural"]:
        durum = _rozet("yok", "Kapalı")
    elif d["model"]:
        durum = _rozet("art", "Açık, işlemleri etkiliyor")
    else:
        durum = _rozet("bk", "Açık, henüz eğitilmedi")
    if not d["model"]:
        yok = _olculemedi(d["islem"], d["min_n"])
        return f'<div class="s">{durum} {yok}</div>' if not tam else _kv([("Durum", durum), ("Ölçüm", yok), ("Son eğitim", '<span class="so">henüz eğitilmedi</span>')])
    isabet = f'son {d["isabet"][1]} kararın {d["isabet"][0]}\'{_EK3.get(d["isabet"][0], "i")} tuttu' if d["isabet"] else f'<span class="so">Veri birikiyor: {d["isabet_n"]}/10 karar</span>'
    ozet_satir = f'{d["onay7"]} işlem onaylandı · ML\'in atlattığı işlem: {d["ret7"]}'
    if not tam:
        return f'<div class="s">{durum}</div>' + _kv([("İsabet", isabet), ("Son 7 gün", ozet_satir)])
    fark = (f'<span class="{_renk(d["ml_katki"])}">{esc(_tl(d["ml_katki"], True))}</span>' if d["ml_katki"] is not None else _olculemedi(d["ml_ko_n"], d["min_n"]))
    egit = "henüz kayıtta yok" if d["egitim"] is None else f'{_tsi(d["egitim"][0], "%d.%m.%Y")} · {"—" if d["egitim"][1] is None else d["egitim"][1]} örnek'
    return _kv([("Durum", durum), ("İsabet", isabet), ("Son 7 gün", ozet_satir), ("Katkı (ML'li − ML'siz K/Z)", fark), ("Son eğitim", esc(egit))])


def _liste_satir(hucreler: list[str], ayrinti: str, sinif: str) -> str:
    """Dokununca açılan tablo satırı: özet (en çok 4 sütun) + ayrıntı."""
    return f'<details class="r"><summary class="g {sinif}">{"".join(f"<div>{h}</div>" for h in hucreler)}</summary><div class="ay">{ayrinti}</div></details>'


def _liste_baslik(basliklar: list[str], sinif: str) -> str:
    return f'<div class="g th {sinif}">{"".join(f"<div>{esc(b)}</div>" for b in basliklar)}</div>'


def _daha_fazla(satirlar: list[str], ilk: int = 20) -> str:
    """İlk `ilk` satır görünür; kalanı "daha fazla" bölümünde."""
    if not satirlar:
        return ""
    govde = "".join(satirlar[:ilk])
    if len(satirlar) > ilk:
        govde += f'<details class="df"><summary>daha fazla ({len(satirlar) - ilk})</summary>{"".join(satirlar[ilk:])}</details>'
    return govde


def kz_html(v: float | None, oran: float | None) -> str:
    """K/Z hücresi: $ üstte, yüzde altta."""
    return f'<b class="{_renk(v)}">{esc(_tl(v, True))}</b><br><span class="{_renk(oran)} kc">{esc(_tyuz(oran))}</span>'


def acik_liste_html(satirlar: list[dict]) -> str:
    if not satirlar:
        return '<div class="bos">Açık işlem yok</div>'
    govde = []
    for r in satirlar:
        ay = _kv([("Trader", esc(kisa(r["adres"]))), ("Stop", esc(r["stop"])), ("İz süren koruma", esc(r["iz"])), ("Büyüklük", esc(_tl(r["usd"]))),
                  ("Kaldıraç", "—" if r["kaldirac"] is None else f'{tr_sayi(float(r["kaldirac"]), 0)}x'), ("Açılış", "—" if not r["acilis_ms"] else _tsi(int(r["acilis_ms"])) + " TSİ")])
        govde.append(_liste_satir([f'<b>{esc(r["coin"])}</b><br><span class="so">{r["yon"]}</span>', f'{fiyat(r["giris"])}<br><span class="so">→ {fiyat(r["mark"])}</span>', kz_html(r["kz"], r["oran"]), esc(sure_metni(r["sure_ms"]))], ay, "ga"))
    return _liste_baslik(["Coin", "Giriş → şimdi", "K/Z", "Süre"], "ga") + _daha_fazla(govde)


def _fark_metni(a: float | None) -> str:
    """Bizim fiyat − trader fiyatı farkı (% ve yön): + = bizim aleyhe."""
    return "—" if a is None else (f"%{tr_sayi(a * 100, 2)} aleyhe" if a >= 0 else f"%{tr_sayi(abs(a) * 100, 2)} lehe")


def kapanan_liste_html(satirlar: list[dict]) -> str:
    if not satirlar:
        return '<div class="bos">Bu dönemde kapanan işlem yok</div>'
    govde = []
    for r in satirlar:
        ders = "uygulanmadı" if r["ders"] is None or float(r["ders"]) >= 1.0 else f'alım boyutu %{tr_sayi(float(r["ders"]) * 100, 0)}\'e düşürülmüştü'
        ay = _kv([("Trader", esc(kisa(r["adres"]))), ("Neden", esc(r["ayrinti"])),
                  ("Giriş (trader → biz)", f'{fiyat(r["tr_giris"])} → {fiyat(r["giris"])} · {_fark_metni(r["giris_fark"])}'),
                  ("Çıkış (trader → biz)", f'{fiyat(r["tr_cikis"])} → {fiyat(r["cikis"])} · {_fark_metni(r["cikis_fark"])}'),
                  ("Süre", esc(sure_metni(r["sure_ms"]))), ("Komisyon", esc(_tl(r["ucret"]))), ("Ders", esc(ders))])
        govde.append(_liste_satir([f'<b>{esc(r["coin"])}</b><br><span class="so kc">{r["yon"]} · {esc(kisa(r["adres"]))}</span>', esc(_tsi(r["ms"])), kz_html(r["net"], r["oran"]), esc(r["neden"])], ay, "gk"))
    return _liste_baslik(["Coin", "Kapanış (TSİ)", "K/Z", "Neden"], "gk") + _daha_fazla(govde)


def _kadro_bolumu(ozet: dict, hesap: dict, kayitlar: list[dict], acik: list[dict], kadro: dict | None, saha_durum: dict | None, hesap_tr: dict | None, havuz: dict | None, kaldirac_tr: dict | None,
                  kurallar: dict, oz: float, kasa: float) -> tuple[str, str, str, str, int, object]:
    """TEKNİK > "Takip edilen traderlar": trader kartları (sahada / bekliyor / iniyor / yedek); dokununca "bize ne verdi" mini özeti (yalnız defter/kayıt toplamı; yeni hesap yok).
    Döner (kartlar HTML, mutabakat satırı, motor kadro satırı, radar tarihi, sahadaki sayı, saha boyu)."""
    tl, tyuz, renk = _tl, _tyuz, _renk
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
                       f'<div><span class="so">Ayrılan para</span><br>{esc(tl(float(slot_bas[ad])))}</div>'
                       f'<div><span class="so">Bize verdiği (net)</span><br><b class="{renk(net)}">{esc(tl(net, True))}</b> <span class="{renk(yuzde_s)}">{esc(tyuz(yuzde_s))}</span></div>'
                       f'<div><span class="so">Gerçekleşen (ücret, fonlama ücreti dahil) / açık</span><br>{esc(tl(float(gerc.get(ad, 0.0)) - float(ucr.get(ad, 0.0)) + float(fnd.get(ad, 0.0)), True))} / {"—" if ad in kz_bilinmiyor else esc(tl(kz_adres.get(ad, 0.0), True))}</div>'
                       f'<div><span class="so">Emir sayısı</span><br>{emir_say.get(ad, 0)}</div>'
                       f'<div><span class="so">Açık pozisyon</span><br>{poz_adres.get(ad, 0)}</div>'
                       f'<div><span class="so">Son işlem</span><br>{_tsi(son_emir[ad]) if ad in son_emir else "—"}</div>'
                       f'<div><span class="so">Radar 7g kopya getirisi</span><br>{esc(tyuz(r.get("kopya_getiri_7g")))}</div>'
                       f'<div><span class="so">Ödenen ücret</span><br>{esc(tl(float(ucr.get(ad, 0.0))))}</div>{_kaldirac_html(r, (kaldirac_tr or {}).get(ad))}{_tarz_html(r)}</div>')
        else:
            ayrinti = (f'<div class="ms"><div><span class="so">Durum</span><br>Henüz sahada değil — {"bekleme süresi, korelasyon ya da günlük değişiklik sınırı nedeniyle olabilir" if durum == "BEKLİYOR" else ("radar listesinde yok" if durum == "KADRO DIŞI" else "yedek listede")}</div>'
                       f'<div><span class="so">Radar 7g kopya getirisi</span><br>{esc(tyuz(r.get("kopya_getiri_7g")))}</div>'
                       f'<div><span class="so">Form puanı</span><br>{tr_sayi(float(r.get("form") or 0), 1)} / 100</div>'
                       f'{_kaldirac_html(r, (kaldirac_tr or {}).get(ad))}{_tarz_html(r)}</div>')
        ek = ""
        hv = (havuz or {}).get(ad) or {}
        if ad in slot_bas:                                                                      # C1: canlı kopya koruması — bizim slot getirimiz ↔ aynı sürede trader'ın hesap getirisi
            hg, hs = (uyeler.get(ad) or {}).get("hesap_giris_usd"), ((hesap_tr or {}).get(ad) or {}).get("deger")
            tr_get = ((float(hs) - float(hg)) / float(hg)) if hg and hs is not None else None
            bizim = (net / float(slot_bas[ad])) if net is not None and float(slot_bas.get(ad) or 0) > 0 else None
            koruma = (bizim / tr_get) if bizim is not None and tr_get is not None and abs(tr_get) >= 0.001 else None
            ek += (f'<div class="ms"><div><span class="so">Bizim getirimiz</span><br><b class="{renk(bizim)}">{esc(tyuz(bizim))}</b></div>'
                   f'<div><span class="so">Trader hesap getirisi (aynı sürede)</span><br><b class="{renk(tr_get)}">{esc(tyuz(tr_get)) if tr_get is not None else "— (girişte kaydedilmemiş)"}</b></div>'
                   f'<div><span class="so">Koruma oranı (bizim ÷ trader)</span><br><b>{tr_sayi(koruma) if koruma is not None else "—"}</b></div>'
                   f'<div><span class="so">Radar koruma oranı (7g)</span><br>{tr_sayi(float(hv["kopya_koruma"])) if hv.get("kopya_koruma") is not None else "—"}</div></div>'
                   '<div class="ha" style="padding:0 4px 8px 30px">Trader getirisi hesap değerinden hesaplanır; para yatırma/çekmeyi de içerir (yaklaşık).</div>')
        yp = hv.get("yatirma_payi")
        if yp is not None:
            ek += f'<div class="ms"><div><span class="so">Net para yatırma payı (7g)</span><br><b class="{"eks" if float(yp) > 0.2 else ""}">{esc(tyuz(float(yp)))}</b></div></div>'
        if r.get("bilesenler"):
            ek += '<div class="bil">' + "".join(f'<div class="bl"><span>{esc(ad_)}</span><div class="ol"><i style="width:{min(max(float(r["bilesenler"].get(k_) or 0), 0), 100):.0f}%"></i></div><span>{float(r["bilesenler"].get(k_) or 0):.0f}</span></div>' for k_, ad_ in BILESEN_AD if k_ != "H" or float(kurallar.get("radar_agirlik_h", 0) or 0) > 0) + '</div>'
        if ADRES_RE.fullmatch(ad):
            ek += f'<div class="ms"><div><a class="ln" href="https://app.hyperliquid.xyz/explorer/address/{ad}" target="_blank" rel="noopener noreferrer">Trader sayfasını aç (Hyperliquid) ↗</a></div></div>'
        ayrinti += ek
        rozet = {"SAHADA": "art", "İNİYOR": "eks", "BEKLİYOR": "bk", "YEDEK": "yok", "KADRO DIŞI": "yok"}[durum]
        gruplar[durum].append(f'<details class="kd{" kb" if durum == "BEKLİYOR" else ""}"><summary><span class="sr">{int(r.get("sira", 0)) or "·"}</span><b>{esc(kisa(ad))}</b><span class="rz {rozet}">{durum}</span>'
                       f'<span class="fb"><i style="width:{min(max(float(r.get("form") or 0), 0), 100):.0f}%"></i></span><span class="fm">{f"{float(r['form']):.0f}" if r.get("form") is not None else ""}</span>'
                       f'<span class="nt {renk(net)}">{esc(tl(net, True)) if net is not None else ""}</span></summary>{ayrinti}</details>')
    mut = (f'<div class="mt">Kartların toplamı <b class="{renk(toplam_net)}">{esc(tl(toplam_net, True))}</b> + takipten ayrılan traderlar <b>{esc(tl(float(hesap.get("kapanmis_net") or 0.0), True))}</b> = '
           f'<b>{esc(tl(toplam_net + float(hesap.get("kapanmis_net") or 0.0), True))}</b> (başlangıçtan beri özsermaye farkı {esc(tl(oz - kasa, True))}){" · bazı K/Z bilinmiyor, toplam eksik" if net_eksik else ""}</div>') if slot_bas else ""
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
    return kadro_html, mut, motor_satiri, kadro_tarih, sahada_n, saha_n



KOYU = "--bg:#0b0b0d;--k:#141417;--cz:#2b2b31;--y:#ececf1;--so:#b3b3bd;--tu:#f5a524;--art:#3ddc84;--eks:#ff6b6b;--bk:#f5d90a;--c2:#202026;--c3:#18181c;--uyb:#7f1d1d;--uyy:#ffe4e4"
ACIK = "--bg:#f4f4f6;--k:#ffffff;--cz:#d6d6dd;--y:#16161a;--so:#5f5f69;--tu:#b36b00;--art:#15803d;--eks:#c81e1e;--bk:#8a5a00;--c2:#e6e6ec;--c3:#f0f0f3;--uyb:#c81e1e;--uyy:#ffffff"
CSS = (":root{" + KOYU + ";color-scheme:dark}"
       ":root[data-theme=light]{" + ACIK + ";color-scheme:light}"
       ":root[data-theme=dark]{" + KOYU + ";color-scheme:dark}"
       "@media(prefers-color-scheme:light){:root:not([data-theme=dark]):not([data-theme=light]){" + ACIK + ";color-scheme:light}}" + """
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--y);font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;font-variant-numeric:tabular-nums;padding:12px;overflow-wrap:anywhere}
.ust{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:10px}.ic .ust{display:none}
.lg0{background:var(--tu);color:#000;font-weight:800;padding:2px 7px;border-radius:4px}.ust b{font-size:15px}
.so,.ha{color:var(--so)}.ha{font-size:11px}.kc{font-size:11px}
.rozet{border:1px solid var(--cz);border-radius:4px;padding:1px 8px;color:var(--tu);font-size:11px;margin-right:6px}
.dug{display:inline-flex;gap:4px}.dug button{background:var(--k);color:var(--y);border:1px solid var(--cz);border-radius:4px;padding:4px 9px;font:inherit;font-size:12px;cursor:pointer}
.uy{background:var(--uyb);color:var(--uyy);font-weight:700;padding:6px 10px;margin-bottom:8px;border-radius:4px}
.rk-b{display:none}.bayat .rk-n{display:none}.bayat .rk-b{display:block}
.sirit{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1px;background:var(--cz);border:1px solid var(--cz);margin-bottom:6px}
.h{background:var(--k);padding:7px 8px;min-width:0}.hb{font-size:10px;letter-spacing:.04em;color:var(--so);text-transform:uppercase}.hd{font-size:15px;font-weight:700;margin:2px 0}.h .ha{font-size:10.5px;line-height:1.3}
.art{color:var(--art)}.eks{color:var(--eks)}.bk{color:var(--bk)}.yok{color:var(--so)}
.gn{text-align:right;font-size:11px;color:var(--so);margin:0 0 6px}
.tabs{display:flex;justify-content:space-between;margin:0 0 8px;border-bottom:1px solid var(--cz)}.tabs label{flex:0 1 auto;padding:9px 5px;font-size:11px;letter-spacing:.02em;color:var(--so);cursor:pointer;white-space:nowrap;border-bottom:2px solid transparent;font-weight:600}
input[type=radio]{position:absolute;opacity:0;pointer-events:none}
.sekmeler>section{display:none}
#t1:checked~.tabs label[for=t1],#t2:checked~.tabs label[for=t2],#t3:checked~.tabs label[for=t3],#t4:checked~.tabs label[for=t4],#t5:checked~.tabs label[for=t5],#t6:checked~.tabs label[for=t6]{color:var(--tu);border-bottom-color:var(--tu)}
#t1:checked~.sekmeler .n1,#t2:checked~.sekmeler .n2,#t3:checked~.sekmeler .n3,#t4:checked~.sekmeler .n4,#t5:checked~.sekmeler .n5,#t6:checked~.sekmeler .n6{display:grid;gap:8px}
.p{background:var(--k);border:1px solid var(--cz);min-width:0;border-radius:6px}
.pb{font-size:11px;letter-spacing:.06em;color:var(--tu);text-transform:uppercase;padding:8px 11px;border-bottom:1px solid var(--cz);display:flex;justify-content:space-between;gap:8px;font-weight:600}.pb span{color:var(--so);text-transform:none;letter-spacing:0;font-weight:400}
.pi{padding:9px 11px}.p.kirmizi{border-color:var(--eks)}.p.sari{border-color:var(--bk)}
.kv{display:flex;justify-content:space-between;gap:10px;padding:4px 0;border-bottom:1px solid var(--c2);font-size:13px}.kv:last-child{border:0}.kv span{color:var(--so);flex:0 0 auto}.kv b{font-weight:600;text-align:right}
.s{padding:4px 0;font-size:13px}.bos{color:var(--so);padding:12px 4px;font-size:12px}.gorev{font-size:16px;font-weight:600}
.rz{font-size:12px;border:1px solid var(--cz);border-radius:4px;padding:0 7px;font-weight:600;display:inline-block}.rz.art{border-color:var(--art)}.rz.eks{border-color:var(--eks)}.rz.bk{border-color:var(--bk)}
.ln{color:var(--tu);cursor:pointer;font-size:12px;display:inline-block;margin-top:6px;font-weight:600}
.g{display:grid;gap:6px;align-items:start;padding:8px 6px}.th{font-size:10px;letter-spacing:.05em;color:var(--so);text-transform:uppercase;border-bottom:1px solid var(--cz);padding:7px 6px}
.ga{grid-template-columns:minmax(0,.95fr) minmax(0,1.5fr) minmax(0,1.05fr) minmax(0,.8fr)}.gk{grid-template-columns:minmax(0,.9fr) minmax(0,1fr) minmax(0,1.05fr) minmax(0,1.1fr)}
.r{border-bottom:1px solid var(--c2)}.r:last-child{border:0}.r>summary{list-style:none;cursor:pointer}.r>summary::-webkit-details-marker{display:none}.g>div{min-width:0;font-size:13px}
.ay{padding:2px 10px 10px;background:var(--c3)}.df>summary{padding:10px;color:var(--tu);cursor:pointer;font-weight:600;font-size:13px}
.pil{display:flex;gap:6px;margin:0 0 8px}.pil label{flex:1;text-align:center;padding:7px 4px;border:1px solid var(--cz);border-radius:6px;font-size:12px;cursor:pointer;color:var(--so);background:var(--k)}
.per{display:none}#p1:checked~.per1,#p2:checked~.per2,#p3:checked~.per3,#p4:checked~.per4{display:block}
#p1:checked~.pil label[for=p1],#p2:checked~.pil label[for=p2],#p3:checked~.pil label[for=p3],#p4:checked~.pil label[for=p4]{color:var(--tu);border-color:var(--tu);font-weight:700}
.ozs{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1px;background:var(--cz);border:1px solid var(--cz);margin-bottom:8px;border-radius:6px;overflow:hidden}
table.tb{width:100%;border-collapse:collapse;font-size:13px}.tb td,.tb th{padding:6px 6px;border-bottom:1px solid var(--c2);text-align:left}.tb th{font-size:10px;color:var(--so);letter-spacing:.05em;text-transform:uppercase;font-weight:600}.tb .sg{text-align:right}.tb tr:last-child td{border:0}.tb tr.alt td{font-size:11px;color:var(--so);padding:0 6px 5px}
.gr{width:100%;height:110px;display:block}.ek{display:flex;justify-content:space-between;gap:8px;font-size:10px;color:var(--so);margin-top:4px}.ek2{justify-content:center;text-align:center;flex-wrap:wrap}
.lg{display:inline-block;margin:6px 12px 0 0;font-size:11px;color:var(--so)}.lg i{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:5px}
.ol{height:7px;background:var(--c2);border-radius:4px;margin:4px 0 9px;overflow:hidden}.ol i{display:block;height:100%;background:var(--tu)}
.td{border-top:1px solid var(--c2)}.td:first-of-type{border-top:0}.td>summary{padding:10px 11px;cursor:pointer;font-weight:600;font-size:13px;list-style:none;display:flex;justify-content:space-between;gap:8px}.td>summary::-webkit-details-marker{display:none}.td>summary::after{content:"+";color:var(--so)}.td[open]>summary::after{content:"−"}
.grp{font-size:11px;letter-spacing:.08em;color:var(--tu);text-transform:uppercase;padding:10px 11px 4px;font-weight:700}
.tw{overflow-x:auto}.iz2{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1px;background:var(--cz)}.mt{margin-top:10px;padding:8px;background:var(--c3);border:1px solid var(--cz);font-size:12px;color:var(--so)}
.kd{border-bottom:1px solid var(--c2)}.kd summary{display:flex;gap:8px;flex-wrap:wrap;align-items:center;padding:8px 2px;cursor:pointer;list-style:none}.kd summary::-webkit-details-marker{display:none}.kd.kb{box-shadow:inset 3px 0 0 var(--bk)}
.sr{color:var(--so)}.fb{height:6px;width:46px;background:var(--c2);border-radius:3px;overflow:hidden;display:inline-block}.fb i{display:block;height:100%;background:var(--tu)}.fm{color:var(--so)}.nt{margin-left:auto}
.ms{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;padding:4px 4px 12px;font-size:12px}.bil{padding:2px 4px 8px}.bl{display:grid;grid-template-columns:110px 1fr 28px;gap:8px;align-items:center;font-size:11px;color:var(--so)}.bl .ol{margin:5px 0}
.yb{margin:12px 0 2px;font-size:10px;letter-spacing:.1em;color:var(--tu)}.yb.yb-bk{color:var(--bk)}
.foot{margin:14px 0 4px;font-size:11px;color:var(--so)}
@media(min-width:900px){body{padding:18px;max-width:1180px;margin:auto;font-size:14px}.sirit{grid-template-columns:repeat(6,minmax(0,1fr))}.hd{font-size:20px}.h .ha{font-size:11px}.tabs label{padding:10px 18px;font-size:12px;flex:0 0 auto}.tabs{justify-content:flex-start}
.n1,.n5{grid-template-columns:repeat(2,minmax(0,1fr))}.n1>.p.tam,.n5>.p.tam{grid-column:1/-1}.ms{grid-template-columns:repeat(4,minmax(0,1fr))}}
@media print{.dug,#bayat{display:none!important}.sekmeler>section{display:grid!important}.tabs{display:none}}
""")

JS = """(function(){var d=document,r=d.documentElement;try{if(window.self!==window.top)r.classList.add("ic")}catch(e){r.classList.add("ic")}
try{var t=localStorage.getItem("ct_tema");if(t==="light"||t==="dark")r.setAttribute("data-theme",t)}catch(e){}
var b=d.getElementById("tema");if(b)b.onclick=function(){var c=r.getAttribute("data-theme")||(window.matchMedia&&matchMedia("(prefers-color-scheme: light)").matches?"light":"dark"),n=c==="light"?"dark":"light";r.setAttribute("data-theme",n);try{localStorage.setItem("ct_tema",n)}catch(e){}};
var y=d.getElementById("yenile");if(y)y.onclick=function(){location.reload()};
var e=d.getElementById("bayat");
function k(){if(!e)return;var ms=Number(e.dataset.ms);if(!ms)return;var dk=Math.max(0,Math.round((Date.now()-ms)/60000)),eski=Date.now()-Number(e.dataset.ms)>3600*1000,s=dk<1?"az önce":(dk<120?dk+" dk önce":Math.round(dk/60)+" sa önce");e.className=eski?"uy":"gn";e.textContent=eski?"Veri bayat: son güncelleme "+s+" — sistem durmuş olabilir":"son güncelleme "+s;r.classList.toggle("bayat",eski)}
k();setInterval(k,60000);document.addEventListener("visibilitychange",function(){if(!document.hidden)k()});
try{["t","p"].forEach(function(a){var s=sessionStorage.getItem("ct_"+a);if(s){var x=d.getElementById(s);if(x)x.checked=true}d.querySelectorAll("input[name="+a+"]").forEach(function(i){i.addEventListener("change",function(){try{sessionStorage.setItem("ct_"+a,i.id)}catch(z){}})})});
var yy=sessionStorage.getItem("ct_y");if(yy)window.scrollTo(0,Number(yy));setTimeout(function(){try{sessionStorage.setItem("ct_y",String(window.scrollY))}catch(z){}location.reload()},180000)}catch(e2){setTimeout(function(){location.reload()},180000)}
})()"""


def _td(baslik: str, govde: str, rozet: str = "") -> str:
    """TEKNİK sekmesi: açılıp kapanan kart."""
    return f'<details class="td"><summary><span>{esc(baslik)}</span>{rozet}</summary><div class="pi">{govde}</div></details>'


def _sayfa_kart(baslik: str, govde: str, sinif: str = "", sag: str = "") -> str:
    return f'<div class="p {sinif}"><div class="pb">{esc(baslik)}{f"<span>{sag}</span>" if sag else ""}</div><div class="pi">{govde}</div></div>'


def _bugun_satiri(r: dict) -> str:
    return (f'<div class="s"><b>{esc(r["coin"])}</b> {r["yon"]} <span class="so">{esc(kisa(r["adres"]))}</span> · {esc(_tsi(r["ms"]))} · <b class="{_renk(r["net"])}">{esc(_tl(r["net"], True))}</b> · {esc(r["neden"])}</div>')


SAHA_NEDEN_TR = {"ilk_gun": "ilk kadro", "bos_slot": "boş yer açıldı", "kor_gevsetildi": "boş yer açıldı", "kadro_disi": "günlük kadrodan düştü", "r1_elendi": "radar elemesinden düştü",
                 "dusme": "performansı düştü (kural)", "hafta_yedege": "haftalık değişim: yedeğe indi", "hafta_elendi": "haftalık değişim: radar eledi", "hafta_kadro_disi": "haftalık değişim: yeni kadroda yok",
                 "bugun_kadroda_yok": "bugünkü radar kadrosunda yok", "islem_yok": "uzun süredir işlem yapmıyor", "donem_basi": "dönem başında zaten sahadaydı"}


def _saha_neden_tr(neden: str) -> str:
    """Saha giriş/çıkış nedeni → sade Türkçe; bilinmeyen kod ham görünmez: "diğer"."""
    return SAHA_NEDEN_TR.get(re.split(r"[ :]", str(neden), maxsplit=1)[0], "diğer")


def _risk_olay_tr(olay: str) -> str:
    return RISK_TR.get(olay, "diğer")


def html_olustur(ozet: dict, risk: dict, hesap: dict, kayitlar: list[dict], gecmis: list[dict], simdi_ms: int, kadro: dict | None = None, saha_durum: dict | None = None, hesap_tr: dict | None = None, havuz: dict | None = None, kurallar: dict | None = None,
                 donem_seri: dict | None = None, isabetler: list[dict] | None = None, kaldirac_tr: dict | None = None, surum_gun: dict[str, str] | None = None,
                 rejim_sonuc: dict | None = None, kaynak: dict | None = None, gunluk_ozet: dict | None = None, kural_maliyet: dict | None = None, secim_gercek: dict | None = None,
                 rejim_anlik: dict | None = None, haber_anlik: dict | None = None) -> str:
    """Telefonda/bilgisayarda açılan tek dosyalık panel (`pano/index.html`; kullanıcının Cloudflare statik sayfası `canli-durum` dalının `pano/` klasörünü gösterir, salt okunur; kapı sayfasında iframe içinde de açılır).
    6 sekme: ÖZET · AÇIK · KAPANAN · K/Z · ÖĞRENME · TEKNİK; üstte her sekmede sabit 6 kutulu şerit. Saf fonksiyon; yeni risk hesabı yok (özet + kayıtlardan yalnız toplama/dizme). Dış kaynak yok; tüm metin HTML kaçışlı."""
    from copytrade.kurallar import load_rules
    from copytrade.canli import haber as haber_mod
    kurallar = kurallar or load_rules()
    kasa, oz = float(ozet.get("kasa_usd") or 0.0), float(ozet.get("ozsermaye_usd") or 0.0)
    gun_basi, zirve = risk.get("gun_basi"), risk.get("zirve")
    dusus = zirve_dusus(oz, zirve)
    gk_sinir, dd_sinir = float(kurallar["canli_gunluk_kayip_oran"]), float(kurallar["canli_zirve_dusus_oran"])          # sınırlar kurallar.yaml'dan (koda sabit değil)
    gun_getiri = gun_getirisi(oz, gun_basi)                                                                          # motorun günlük kayıp tanımı (payda gün başı özsermayesi)
    gun_kayip_pay = min(max(-(gun_getiri or 0) / gk_sinir, 0.0), 1.0) * 100 if gk_sinir > 0 else 0.0
    dusus_pay = min(max((dusus or 0) / dd_sinir, 0.0), 1.0) * 100 if dd_sinir > 0 else 0.0
    k24 = pencere24(kayitlar, simdi_ms)
    donem = kayit_donemi(kayitlar)
    emirler = [k for k in k24 if k.get("olay") == "emir"]
    dolum = [k for k in emirler if k.get("durum") in ("dolu", "kismi")]
    kaymalar = sorted(k["kayma_trader"] for k in dolum if k.get("kayma_trader") is not None)                          # işaretli oran (+ = trader fiyatından kötü)
    kayma_ortanca = (kaymalar[len(kaymalar) // 2] if len(kaymalar) % 2 else (kaymalar[len(kaymalar) // 2 - 1] + kaymalar[len(kaymalar) // 2]) / 2) if kaymalar else None
    funding24 = funding_toplam(k24)
    din = ozet.get("dinleyici") or {}
    veri_ms = int(ozet.get("yazildi_ms") or max([int(k["zaman_ms"]) for k in kayitlar if k.get("olay") == "kapanis" and (k.get("ozet") or {}).get("vardiya") == ozet.get("vardiya")] or [simdi_ms]))
    kip = str(ozet.get("kip", "—"))
    ds = donem_seri or {}
    sg = saglik_kontrol(simdi_ms, ozet, kadro)                                                                         # pano dışı ölçümler (Cloudflare) saatlik iş akışında; burada yalnız motor + radar
    sg_durum = saglik_durum(sg)
    acik = ozet.get("acik")
    if acik is None:
        acik = [{"adres": a, "coin": c, "sz": q["sz"], "giris": q["giris"], "usd": abs(q["sz"]) * q["giris"], "kz_usd": None} for a, cs in (hesap.get("poz") or {}).items() for c, q in cs.items()]
    acik = sorted(acik, key=lambda q: -(q.get("usd") or 0))
    seri = ozsermaye_serisi(kayitlar, ds, oz, kasa, simdi_ms, gecmis)
    kz_donem = donem_kz(seri, oz, kasa, simdi_ms, ds.get("bas_ms"), float(gun_basi) if gun_basi else None)
    durdu = bool(ozet.get("dur") or risk.get("dur") or any((risk.get("acilis_durdu") or {}).values()))
    r_sinif, r_metin, r_alt = risk_durumu(oz, gun_basi, gk_sinir, durdu)
    toplam_oran = ozet.get("getiri") if ozet.get("getiri") is not None else ((oz - kasa) / kasa if kasa > 0 else None)

    def hucre(baslik: str, deger: str, sinif: str = "", alt: str = "") -> str:
        return f'<div class="h"><div class="hb">{esc(baslik)}</div><div class="hd {sinif}">{esc(deger)}</div><div class="ha">{esc(alt)}</div></div>'

    serit_html = serit([hucre("Kasa", _tl(oz), "", f"başl. {_tl(kasa)}"), hucre("Bugün K/Z", _tl(kz_donem[0][1], True), _renk(kz_donem[0][1]), _tyuz(kz_donem[0][2])),
                        hucre("Toplam K/Z", _tl(oz - kasa, True), _renk(oz - kasa), _tyuz(toplam_oran)), hucre("Açık poz.", str(len(acik)), "", f"brüt {_tl(sum(q.get('usd') or 0 for q in acik))}"),
                        hucre("Zirveden düşüş", _tl(-(float(zirve) - oz), True) if zirve else "—", _renk(-dusus if dusus is not None else None), _tyuz(-dusus if dusus is not None else None)),
                        f'<div class="h"><div class="hb">Risk durumu</div><div class="rk-n"><div class="hd {r_sinif}">{esc(r_metin)}</div><div class="ha">{esc(r_alt)}</div></div>'
                        '<div class="rk-b"><div class="hd yok">Bilinmiyor</div><div class="ha">veri güncel değil</div></div></div>'], "s6")
    # ---- veri hazırlığı
    kap = kapanan_islemler(kayitlar, float(kurallar.get("canli_felaket_stop_oran", 0) or 0))
    acik_s = acik_satirlari(acik, hesap, kurallar, simdi_ms, kip)
    uyeler, inenler = ((saha_durum or {}).get("uyeler") or {}), ((saha_durum or {}).get("inen") or {})
    adresler = {*uyeler, *inenler, *(hesap.get("slot_bas") or {}), *(q["adres"] for q in acik), *(str(k["adres"]) for k in emirler if k.get("adres"))}
    og = ogrenme_ozeti(kayitlar, ozet, gunluk_ozet, kurallar, simdi_ms, _alias_haritasi(adresler))
    rejim_eski = bool(rejim_anlik) and rejim_anlik.get("gecerli_son_ms") is not None and simdi_ms > int(rejim_anlik["gecerli_son_ms"])
    haber_eski = bool(haber_anlik) and bool(haber_anlik.get("duygu")) and haber_mod.duygu_ozet(haber_anlik, simdi_ms) is None
    sorunlar = [b for b in sg if b.seviye in ("KRITIK", "UYARI")]
    mesaj = lambda b: "Veri güncel değil (süre üstteki satırda)" if b.kod in YAS_KODLARI else re.sub(r"\s*\([^)]*\.(?:json|jsonl|yml|py|sh)[^)]*\)", "", b.mesaj)      # noqa: E731  dosya adı ve veri yaşı sayısı tekrar edilmez

    # ---- ÖZET
    if durdu or r_sinif == "eks":
        gorev = "Risk freni devrede, yeni işlem açılmıyor; nedeni için TEKNİK sekmesine bakın."
    elif sg_durum == "KRITIK":
        gorev = "Sistemde acil bir sorun var; TEKNİK sekmesindeki sağlık bölümüne bakın."
    else:
        gorev = "Bir şey yapmanız gerekmiyor."
    kzler = [q for q in acik_s if q["kz"] is not None]
    if acik_s:
        en_iyi, en_kotu = max(kzler, key=lambda q: q["kz"], default=None), min(kzler, key=lambda q: q["kz"], default=None)
        toplam_kz = sum(q["kz"] for q in kzler) if kzler else None
        k_acik = _kv([("Açık işlem", str(len(acik_s))), ("Toplam K/Z", f'<span class="{_renk(toplam_kz)}">{esc(_tl(toplam_kz, True))}</span>'),
                      ("En iyi", "—" if not en_iyi else f'{esc(en_iyi["coin"])} {en_iyi["yon"]} <span class="{_renk(en_iyi["kz"])}">{esc(_tl(en_iyi["kz"], True))}</span>'),
                      ("En kötü", "—" if not en_kotu else f'{esc(en_kotu["coin"])} {en_kotu["yon"]} <span class="{_renk(en_kotu["kz"])}">{esc(_tl(en_kotu["kz"], True))}</span>')])
    else:
        k_acik = '<div class="bos">Açık işlem yok</div>'
    k_son = ("".join(_bugun_satiri(r) for r in kap[:3]) + '<label for="t3" class="ln">tümü →</label>') if kap else '<div class="bos">veri birikiyor: henüz kapanan işlem yok</div>'
    if sorunlar:
        isik = ("eks", "Teknik sorun var — ayrıntı TEKNİK sekmesinde")
    elif rejim_eski or haber_eski:
        isik = ("bk", " · ".join([*(["Rejim verisi güncel değil"] if rejim_eski else []), *(["Haber verisi güncel değil"] if haber_eski else [])]))
    else:
        isik = ("art", "Her şey yolunda")
    k_isik = _sayfa_kart("Durum ışığı", f'<div class="gorev {isik[0]}" style="font-size:14px">{esc(isik[1])}</div>', {"eks": "kirmizi", "bk": "sari"}.get(isik[0], ""))
    ozet_kartlari = [_sayfa_kart("Ne yapmalıyım?", f'<div class="gorev rk-n">{esc(gorev)}</div><div class="gorev rk-b eks">Veri 1 saattir gelmiyor: orkestratöre \'CT panosu güncellenmiyor\' yaz.</div>'), _sayfa_kart("Açık işlemler", k_acik), _sayfa_kart("Son kapanan işlemler", k_son),
                     _sayfa_kart("Ders öğrenmesi", ders_karti(og, False)), _sayfa_kart("Makine öğrenmesi", ml_karti(og, False))]
    ozet_kartlari = [k_isik, *ozet_kartlari] if isik[0] == "eks" else [*ozet_kartlari, k_isik]
    # ---- KAPANAN
    bugun0 = tsi_gun_basi(simdi_ms)
    donemler = [("p1", "Bugün", [r for r in kap if r["ms"] >= bugun0]), ("p2", "7g", [r for r in kap if r["ms"] >= simdi_ms - 7 * GUN_MS]),
                ("p3", "30g", [r for r in kap if r["ms"] >= simdi_ms - 30 * GUN_MS]), ("p4", "Tümü", kap)]
    kap_html = "".join(f'<input type="radio" name="p" id="{i}"{" checked" if i == "p2" else ""}>' for i, _, _ in donemler)
    kap_html += '<div class="pil">' + "".join(f'<label for="{i}">{esc(ad)}</label>' for i, ad, _ in donemler) + "</div>"
    for i, _, satirlar in donemler:
        oz_p = kapanan_ozeti(satirlar, kap)
        kap_html += (f'<div class="per per{i[1]}"><div class="ozs">{hucre("Kapanış", str(oz_p["kapanis"]), "", f"{oz_p['poz']} pozisyon")}{hucre("Kazanma", "—" if oz_p["kazanma"] is None else "%" + tr_sayi(oz_p["kazanma"] * 100, 0), "", "pozisyon bazında")}'
                     f'{hucre("Net K/Z", _tl(oz_p["net"], True) if oz_p["kapanis"] else "—", _renk(oz_p["net"]) if oz_p["kapanis"] else "")}</div>'
                     f'<div class="ha" style="padding:0 6px 6px">Net = kapanış K/Z − kapanış komisyonu. Açılış komisyonu ve zorla kapanmalar K/Z sekmesindeki dökümde.</div>{kapanan_liste_html(satirlar)}</div>')
    # ---- K/Z
    nokta = [v for t, v in seri if t >= simdi_ms - 30 * GUN_MS]
    if len(nokta) > 300:
        adim = len(nokta) // 300 + 1
        nokta = nokta[::adim] + [nokta[-1]]
    ilk_ms = next((t for t, _ in seri if t >= simdi_ms - 30 * GUN_MS), simdi_ms)
    egri30 = _cizgi(nokta, "#f5a524", baz=kasa if kasa > 0 else None, x_etiket=(_tsi(ilk_ms, "%d.%m"), _tsi(simdi_ms, "%d.%m")))
    oz_k = kapanan_ozeti(kap)
    donem_satir = "".join(f'<tr><td>{esc(ad)}</td><td class="sg {_renk(v)}">{esc(_tl(v, True))}</td><td class="sg {_renk(o)}">{esc(_tyuz(o))}</td></tr>' for ad, v, o in kz_donem)
    bas_ms_ = int(ds.get("bas_ms") or 0)
    ucret_d, brut_d, oran_d = komisyon_ozeti(kayitlar, ozet, ds)
    fonlama_d = funding_toplam([k for k in kayitlar if int(k.get("zaman_ms") or 0) >= bas_ms_])
    kaynaklar = kaynak_kz(hesap, acik, uyeler, inenler, kap)
    kaynak_satir = "".join(f'<tr><td>{esc(kisa(r["adres"]))}</td><td class="sg {_renk(r["net"])}">{esc(_tl(r["net"], True))}</td><td class="sg">{r["adet"]}</td><td class="sg">{r["durum"]}</td></tr>' for r in kaynaklar)
    kapanmis = float(hesap.get("kapanmis_net") or 0.0)
    bt, fk = ozet.get("btc_al_tut_getiri"), ozet.get("btc_fark")
    btc_satir = ("BTC al-tut " + _tyuz(None if bt is None else float(bt)) + " · biz " + _tyuz(ozet.get("getiri")) + " · fark " + _tyuz(None if fk is None else float(fk))) if bt is not None else "BTC al-tut kıyası: veri birikiyor"
    gerc_t = sum(float(v) for v in (hesap.get("realize") or {}).values())
    tasfiye_t = sum(float(x.get("pnl") or 0.0) for x in (hesap.get("tasfiyeler") or []))
    ucret_t, fon_t = sum(float(v) for v in (hesap.get("ucret") or {}).values()), sum(float(v) for v in (hesap.get("funding") or {}).values())
    acik_t = sum(float(q["kz_usd"]) for q in acik if q.get("kz_usd") is not None)
    fark_t = (oz - kasa) - (gerc_t + acik_t - ucret_t + fon_t + kapanmis)
    ks = lambda v: f'<span class="{_renk(v)}">{esc(_tl(v, True))}</span>'                                           # noqa: E731
    toplam_kart = ""
    if hesap.get("realize") or hesap.get("ucret"):
        toplam_kart = _sayfa_kart("Toplam nasıl oluşuyor", _kv([("Kapanışlar (gerçekleşen)", ks(gerc_t - tasfiye_t)), *([("Zorla kapanma", ks(tasfiye_t))] if abs(tasfiye_t) > 0.005 else []),
                                                              ("Açık pozisyonlar", ks(acik_t)), ("Komisyon (açılış + kapanış)", ks(-ucret_t)), ("Fonlama ücreti", ks(fon_t)),
                                                              *([("Takipten ayrılan traderlar", ks(kapanmis))] if abs(kapanmis) > 0.005 else []), ("Toplam K/Z", f"<b>{ks(oz - kasa)}</b>"),
                                                              *([("Açıklanamayan fark", ks(fark_t))] if abs(fark_t) > 0.05 else [])])
                                  + '<div class="ha" style="padding-top:6px">Toplam = kapanışlar + zorla kapanma + açık − komisyon ± fonlama ücreti (motorun kayıtlı toplamları).</div>')
    bg = kz_donem[0]
    bugun_kart = ""
    if bg[1] is not None:
        bugun_kap = sum(r["net"] for r in kap if r["ms"] >= bugun0)
        limit_gun = (oz - float(gun_basi)) if gun_basi else None
        bugun_kart = _sayfa_kart("Bugün", _kv([("Bugün K/Z (gece yarısından, TSİ)", ks(bg[1])), ("Bugün kapanışlar (net)", ks(bugun_kap)), ("Açık pozisyon değişimi ve masraf", ks(bg[1] - bugun_kap)),
                                                *([("Limit gününde K/Z (03:00 TSİ'den)", ks(limit_gun))] if limit_gun is not None else []), ("Risk durumu", f'<span class="{r_sinif}">{esc(r_metin)}</span> · {esc(r_alt)}')])
                                 + '<div class="ha" style="padding-top:6px">Günlük limit motorun gün başından (03:00 TSİ) sayılır; "Bugün" gece yarısından. Bu yüzden iki K/Z farklı olabilir.</div>')
    kz_html_ = (_sayfa_kart("Özsermaye (son 30 gün)", egri30, "tam") + toplam_kart + bugun_kart + _sayfa_kart("Getiri", f'<table class="tb"><tr><th>Dönem</th><th class="sg">K/Z</th><th class="sg">Oran</th></tr>{donem_satir}</table><div class="ha" style="padding-top:6px">{esc(btc_satir)}</div>')
                + _sayfa_kart("Kazanma", (_kv([("Kazanma oranı (pozisyon bazında)", "—" if oz_k["kazanma"] is None else "%" + tr_sayi(oz_k["kazanma"] * 100, 0)), ("Ortalama kazanç", f'<span class="art">{esc(_tl(oz_k["ort_kazanc"]))}</span>'), ("Ortalama kayıp", f'<span class="eks">{esc(_tl(oz_k["ort_kayip"]))}</span>'),
                                                      ("Kapanan", f'{oz_k["kapanis"]} kapanış · {oz_k["poz"]} pozisyon (son {(donem or ("", "", 0))[2]} gün)')]) if oz_k["kapanis"] else '<div class="bos">veri birikiyor: henüz kapanan işlem yok</div>'))
                + _sayfa_kart("Kaynak başına K/Z", (f'<table class="tb"><tr><th>Trader</th><th class="sg">K/Z</th><th class="sg">İşlem</th><th class="sg">Durum</th></tr>{kaynak_satir}</table>'
                                                    + (f'<div class="ha" style="padding-top:6px">Takipten ayrılan traderlar: {esc(_tl(kapanmis, True))}</div>' if kapanmis else "") if kaynaklar else '<div class="bos">veri birikiyor</div>'), "tam")
                + _sayfa_kart("Maliyetler", _kv([("Komisyon", f"{esc(_tl(ucret_d))}" + (f' <span class="so">(brüt K/Z\'nin %{tr_sayi(oran_d * 100, 0)}\'i)</span>' if oran_d is not None else "")), ("Fonlama ücreti", f'<span class="{_renk(fonlama_d)}">{esc(_tl(fonlama_d, True))}</span>')])))
    # ---- ÖĞRENME
    son_dersler = "".join(f'<div class="s"><span class="so">{_tsi(ms, "%d.%m")}</span> {esc(m)}</div>' for ms, m in og["dersler"]) or '<div class="bos">veri birikiyor: henüz ders çıkmadı</div>'
    ml_kararlar = ""
    for ms, coin, karar, pnl in og["kararlar"]:
        if karar == "aldı":
            sonuc = "sürüyor" if pnl is None else f'sonuç {_tl(pnl, True)} · ' + ("doğru karar" if pnl > 0 else "yanlış karar")
        else:
            sonuc = "sürüyor" if pnl is None else (f'alsaydık {_tl(pnl, True)} · doğru karar' if pnl < 0 else f'alsaydık {_tl(pnl, True)} · yanlış karar')
        ml_kararlar += f'<div class="s"><span class="so">{_tsi(ms, "%d.%m %H:%M")}</span> <b>{esc(coin)}</b> · {karar} · <span class="so">{esc(sonuc)}</span></div>'
    ml_kararlar = ml_kararlar or ('<div class="bos">veri birikiyor: model eğitilince kararlar burada görünür</div>' if not og["model"] else '<div class="bos">veri birikiyor: henüz karar yok</div>')
    ogrenme_html = (_sayfa_kart("Ders öğrenmesi", ders_karti(og, True), "tam") + _sayfa_kart("Son 5 ders", son_dersler) + _sayfa_kart("Makine öğrenmesi", ml_karti(og, True), "tam") + _sayfa_kart("Makine öğrenmesinin son 5 kararı", ml_kararlar))
    # ---- TEKNİK
    tur = lambda b: b.seviye                                                                                          # noqa: E731
    sg_satir = "".join(f'<div class="s {"eks" if tur(b) == "KRITIK" else ("bk" if tur(b) == "UYARI" else "so")}">{esc(mesaj(b))}</div>' for b in sorted(sg, key=lambda b: ("KRITIK", "UYARI", "BILGI").index(b.seviye))) or '<div class="s art">Sorun yok</div>'
    sg_rozet = _rozet({"SAGLIKLI": "art", "UYARI": "bk", "KRITIK": "eks"}[sg_durum], {"SAGLIKLI": "sorun yok", "UYARI": "uyarı var", "KRITIK": "acil"}[sg_durum])
    saglik_kv = _kv([("WS kopma", str(din.get("kopma", "—"))), ("REST 429", str(ozet.get("rest_429", "—"))), ("Vardiya süresi", f"{tr_sayi(float(ozet.get('sure_dk') or 0) / 60, 1)} sa")])
    deg = [v for _, v in seri][-300:]
    tepe, dd = (kasa if kasa > 0 else (deg[0] if deg else 0.0)), []
    for v in deg:
        tepe = max(tepe, v)
        dd.append((v / tepe - 1) * 100 if tepe > 0 else 0.0)
    if dd and dusus is not None:
        dd[-1] = -dusus * 100                                                                                          # son nokta motorun zirvesine göre; önceki noktalar koşan azami
    seri_son = seri[-300:]
    x_et = (_tsi(seri_son[0][0], "%d.%m %H:%M"), _tsi(seri_son[-1][0], "%d.%m %H:%M")) if seri_son else ("", "")
    riskler = [k for k in k24 if k.get("olay") in RISK_OLAYLARI]
    risk_html = "".join(f'<div class="s eks">{_tsi(int(k["zaman_ms"]), "%H:%M")} · {esc(_risk_olay_tr(str(k["olay"])))}</div>' for k in riskler) or '<div class="s art">Son 24 saatte risk olayı yok</div>'
    limit_html = (f'<div class="ha">Günlük kayıp {esc(yuzde(max(-(gun_getiri or 0.0), 0.0), False))} (sınır %{tr_sayi(gk_sinir * 100, 0)}; motorun gün başı özsermayesine göre)</div><div class="ol"><i style="width:{gun_kayip_pay:.0f}%"></i></div>'
                  f'<div class="ha">Zirveden düşüş {esc(yuzde(dusus, False))} (sınır %{tr_sayi(dd_sinir * 100, 0)}; motorun zirvesine göre)</div><div class="ol"><i style="width:{dusus_pay:.0f}%"></i></div>')
    from copytrade.canli.risk import coin_tavan_usd
    maruziyet_html = _maruziyet_html(acik, kasa, oz, float(hesap.get("kaldirac") or 3.0), float(kurallar["canli_coin_tavan_oran"]), coin_tavan_usd(kurallar, kasa) if kasa > 0 else None)
    so = slot_ozeti(ds)
    dol, nakit, dol_gun = doluluk_ozeti(ds)
    at_or, yv_or, sy = emir_orani(ds)
    mo = maruziyet_ozeti(ds, oz, kasa)
    saha_satiri = (f'<div class="ha">saha {esc(str(ozet.get("saha", "—")))}/{esc(str(ozet.get("saha_n", "—")))}' + (", uygun aday yok" if ozet.get("saha_eksik_neden") == "uygun_aday_yok" else "")
                   + f' · bugün radar elemesini geçen trader: {esc(str(ozet.get("r1_gecen") if ozet.get("r1_gecen") is not None else "—"))}</div>')
    doluluk_html = ((f'<div class="s">trader yeri doluluğu <b>{esc(yuzde(dol, False))}</b> · nakitte kalan <b>{esc(yuzde(nakit, False))}</b></div><div class="ha">{tr_sayi(dol_gun, 1)} gün ölçüldü</div>') if dol is not None
                    else VERI_YOK.format("doluluk kaydı birikiyor")) + saha_satiri
    emir_html = ((f'<div class="s">atlanan sinyal <b>{esc(yuzde(at_or, False))}</b> · yuvarlanan emir <b>{esc(yuzde(yv_or, False))}</b></div><div class="ha">emir {sy.get("emir", 0)} · atlanan {sy.get("atlanan", 0)} · yuvarlanan {sy.get("yuvarlanan", 0)}</div>')
                 if at_or is not None else VERI_YOK.format("dönemde henüz sinyal yok"))
    emir_son = "".join(f'<div class="s"><span class="so">{_tsi(int(k["zaman_ms"]), "%H:%M")}</span> <b>{esc(str(k.get("coin", "")))}</b> <span class="{"art" if k.get("yon") == "B" else "eks"}">{"al" if k.get("yon") == "B" else "sat"}</span> {esc(_tl(k.get("usd_dolan") or k.get("usd_istenen")))}'
                       f' <span class="so">fark {esc(tr_yuzde(k["kayma_trader"]) if k.get("kayma_trader") is not None else "—")}</span></div>' for k in sorted(emirler, key=lambda k: -int(k["zaman_ms"]))[:12]) or '<div class="bos">Son 24 saatte emir yok</div>'
    emir_ozet = _kv([("Emir (24 sa)", f"{len(emirler)} (dolum {len(dolum)})"), ("Ortanca fark", "—" if kayma_ortanca is None else esc(tr_yuzde(kayma_ortanca))), ("Fonlama ücreti (24 sa)", f'<span class="{_renk(funding24)}">{esc(_tl(funding24, True))}</span>')])
    saha = [k for k in k24 if k.get("olay") in ("saha_giris", "saha_dus")]
    saha_html = "".join(f'<div class="s">{"giriş" if k["olay"] == "saha_giris" else "çıkış"} · {_tsi(int(k["zaman_ms"]), "%H:%M")} · {esc(kisa(k["adres"]))} · {esc(_saha_neden_tr(str(k.get("neden", ""))))}</div>' for k in saha) or '<div class="bos">Trader listesinde değişiklik yok</div>'
    kadro_html, mut, motor_satiri, kadro_tarih, sahada_n, saha_n = _kadro_bolumu(ozet, hesap, kayitlar, acik, kadro, saha_durum, hesap_tr, havuz, kaldirac_tr, kurallar, oz, kasa)
    dg, ds_ = duygu_metni(ozet)
    duygu_satiri = f'<div class="s">Piyasa duygusu: <b>{esc(dg)}</b> ({esc(REJIM_TR.get(ds_, ds_))})</div>' if dg != "—" else ""
    cu = lambda t, g, r="": _td(t, g, r)                                                                              # noqa: E731
    teknik = (f'<div class="p"><div class="grp">Sağlık</div>{cu("Sistem sağlığı", sg_satir, sg_rozet)}{cu("Bağlantı ve çalışma", saglik_kv)}{cu("Sunucu kaynakları", _kaynak_html(kaynak, (gunluk_ozet or {}).get("saglik")))}'
              f'<div class="grp">Risk limitleri</div>{cu("Günlük ve zirve limiti", limit_html)}{cu("Zirveden düşüş eğrisi", _cizgi(dd, "#ff6b6b", taban=0.0, x_etiket=x_et, birim="%"))}{cu("Maruziyet", maruziyet_html)}{cu("Risk olayları (24 sa)", risk_html)}'
              f'<div class="grp">Kalite kapıları</div>{cu("Başarı ölçütü", _karar_kutusu_html(ozet))}{cu("Seçim isabeti", _isabet_ozet_html(isabetler or [], ozet) + _isabet_html(isabetler or [], ozet))}{cu("Radar süzgeci", _huni_html(kadro))}'
              f'<div class="grp">Ölçümler</div>{cu("Kural maliyeti", _kural_maliyet_html(kural_maliyet))}{cu("Alınmayan sinyaller", _atlanan_html(k24) + _alinmayan_neden_html(alinmayan_neden(k24)))}{cu("Rejim × duygu", duygu_satiri + _rejim_sonuc_html(rejim_sonuc))}'
              f'{cu("Kopya kalitesi", _kopya_kalite_html(k24))}{cu("Seçim × rastgele", _secim_rastgele_html(isabetler, secim_gercek))}{cu("Saha doluluğu", doluluk_html + emir_html + _maruziyet_ozet_html(mo))}{cu("Öğrenme etkisi (bugün)", _ogrenme_html((gunluk_ozet or {}).get("ogrenme")))}'
              f'<div class="grp">Kayıtlar</div>{cu("Dönem eğrisi", _donem_egri_html(egri_noktalari(ds, float(kurallar.get("basari_aylik_hedef", 0.04)), simdi_ms), ds.get("kilitler")))}{cu("Trader katkısı", _katki_html(so))}{cu("İlk 11 ↔ Yedek", _ilk_yedek_html(so))}'
              f'{cu("Giriş / çıkış geçmişi", _gecmis_html(ds))}{cu("Maliyet dökümü", _maliyet_html(kayitlar, oz, kasa, gecmis, kip))}{cu("Trader bazında kapanışlar", _kapanan_html(kayitlar))}{cu("Emirler (24 sa)", emir_ozet + emir_son)}'
              f'{cu("Trader değişiklikleri (24 sa)", saha_html)}{cu("Sürüm karşılaştırma", surum_karsilastirma.html_tablo(surum_karsilastirma.karsilastir(kayitlar, surum_gun)))}'
              f'{cu(f"Takip edilen traderlar ({sahada_n}/{saha_n})", (f"<div class=mt>{motor_satiri}</div>" if motor_satiri else "") + f"<div class=so style=padding:4px>radar {esc(kadro_tarih)} TSİ · dokun → bize ne verdi</div>" + kadro_html + mut)}</div>')
    uyari = '<div class="uy">GERÇEK PARA</div>' if kip == "gercek" else ""
    bayat_s = simdi_ms - veri_ms > 3600 * 1000
    bayat_txt = ("Veri bayat: son güncelleme " + sure_metni(simdi_ms - veri_ms) + " önce — sistem durmuş olabilir") if bayat_s else ("son güncelleme " + (sure_metni(simdi_ms - veri_ms) + " önce" if simdi_ms - veri_ms >= 60_000 else "az önce"))
    return f"""<!doctype html>
<html lang="tr"{' class="bayat"' if bayat_s else ""}><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex"><meta name="color-scheme" content="dark light">
<title>Kopya İşlem Panosu</title>
<style>{CSS}</style></head><body>
<div class="ust"><div><span class="lg0">CT</span> <b>Kopya İşlem Panosu</b></div><div><span class="rozet">{esc(kip_adi(kip))}</span><span class="dug"><button type="button" id="yenile">Yenile</button><button type="button" id="tema">Tema</button></span></div></div>
<div id="bayat" data-ms="{veri_ms}" class="{"uy" if bayat_s else "gn"}">{esc(bayat_txt)}</div>{uyari}
{serit_html}
<input type="radio" name="t" id="t1" checked><input type="radio" name="t" id="t2"><input type="radio" name="t" id="t3"><input type="radio" name="t" id="t4"><input type="radio" name="t" id="t5"><input type="radio" name="t" id="t6">
<div class="tabs">{"".join(f'<label for="t{i + 1}">{ad}</label>' for i, ad in enumerate(SEKMELER))}</div>
<div class="sekmeler">
<section class="n1">{"".join(ozet_kartlari)}</section>
<section class="n2"><div class="p"><div class="pb">Açık işlemler <span>{len(acik_s)} adet</span></div>{acik_liste_html(acik_s)}</div></section>
<section class="n3"><div class="p"><div class="pb">Kapanan işlemler <span>her kapanış ayrı satır</span></div><div class="pi" style="padding:9px 6px">{kap_html}</div></div></section>
<section class="n4">{kz_html_}</section>
<section class="n5">{ogrenme_html}</section>
<section class="n6">{teknik}</section>
</div>
<div class="foot">{"Gerçek para işlemi" if kip == "gercek" else "Sanal kip: gerçek para yok"} · saatler TSİ</div>
<script>{JS}</script>
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


def pbo_oku(dal: str | None) -> dict | None:
    """Veri dalındaki en son `radar/<tarih>/pbo.json` (copytrade.pbo_rapor); yoksa None."""
    if not dal:
        return None
    ls = subprocess.run(["git", "ls-tree", "-r", "--name-only", f"origin/{dal}"], capture_output=True, text=True)
    yollar = sorted(y for y in ls.stdout.splitlines() if y.startswith("radar/") and y.endswith("/pbo.json"))
    if not yollar:
        return None
    s = subprocess.run(["git", "show", f"origin/{dal}:{yollar[-1]}"], capture_output=True, text=True)
    try:
        return json.loads(s.stdout) if s.returncode == 0 and s.stdout.strip() else None
    except ValueError:
        return None


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
    sg = surum_karsilastirma.surum_gun_oku(args.isabet_dali, sorted({datetime.fromtimestamp(k["zaman_ms"] / 1000, UTC).date().isoformat() for k in kayitlar if isinstance(k.get("zaman_ms"), int | float)}))
    md, yeni = pano_olustur(ozet, _json(args.durum / "risk.json"), _json(args.durum / "hesap.json"), kayitlar, isabetler, gecmis, int(time.time() * 1000), ds, kadro, sg, pbo_oku(args.isabet_dali))
    args.cikti.parent.mkdir(parents=True, exist_ok=True)
    args.cikti.write_text(md, encoding="utf-8")
    args.gecmis.write_text(json.dumps(yeni, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if args.html:
        args.html.write_text(html_olustur(ozet, _json(args.durum / "risk.json"), _json(args.durum / "hesap.json"), kayitlar, yeni, int(time.time() * 1000), kadro, _json(args.durum / "saha.json"), _json(args.durum / "motor.json").get("hesap_tr"), havuz_oku(args.isabet_dali, kadro),
                                               donem_seri=ds, isabetler=isabetler, kaldirac_tr=_json(args.durum / "motor.json").get("kaldirac_tr"), surum_gun=sg,
                                               rejim_sonuc=_json(args.durum / "paylasim" / "rejim_sonuc_v1.json"), kaynak=_json(args.durum / "motor.json").get("kaynak"),
                                               gunluk_ozet=_json(args.durum / "paylasim" / "gunluk_ozet_v1.json"), kural_maliyet=_json(args.durum / "paylasim" / "kural_maliyet_v1.json"),
                                               secim_gercek=_json(args.durum / "paylasim" / "secim_gercek_v1.json"),
                                               rejim_anlik=_json(args.durum / "motor.json").get("rejim_anlik"), haber_anlik=_json(args.durum / "motor.json").get("haber_anlik")), encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
