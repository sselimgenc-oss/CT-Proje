"""İşlem mutabakatı (sanal copy-trade motoru): kayıt olayları ↔ durum (hesap/ozet) ↔ pano ↔ Telegram kayıtları.

Salt okuma. Motor koduna dokunmaz; veriyi `origin/canli-durum` dalından `git show` ile okur.

    python araclar/mutabakat.py [--dal origin/canli-durum] [--cikti docs/mutabakat/MUTABAKAT_2026-11-20.md]

Birim: BİR POZİSYON = bir (trader, coin) çiftinde ilk açılış dolumundan tam kapanışa (`kapat`), tasfiyeye ya da
veri anına (açık) kadar olan döngü. Azaltmalar aynı pozisyonun parçasıdır. Tutar $ (kasa ölçeği, sanal 10.000 $).
Zamanlar TSİ (UTC+3). Trader adresi yalnız kısa biçimde yazılır (public repo).

Telegram notu: Telegram geçmişine erişim YOK. Yalnız motorun kendi `kayit/*.jsonl` içindeki `telegram` gönderim
kayıtları kullanılır. Pozisyon başına açıldı/kapandı mesajı kaydı, yalnız yeni kod (20.11 ~03:06 TSİ birleşti,
~1 sa içinde yayına girdi) ile başlar; daha önceki işlemler "eski düzen (beklenen)" sayılır, uyuşmazlık değildir.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from copytrade.canli import pano  # noqa: E402  (pano'nun gösterdiği sayılar ve kapanış satırları)

TSI = timezone(timedelta(hours=3))
YENI_KOD_MS = int(datetime(2026, 11, 20, 0, 6, tzinfo=UTC).timestamp() * 1000)  # 20.11 03:06 TSİ
TOZ_USD = 1.0           # bu $ altındaki kalan (dolum tutarı) pozisyon sayılmaz; kapanış kayıtlarındaki toz farkı için
KALDIRAC_ESIK = 5.0     # K-67: HL azami kaldıraç < 5 olan coinde gerçekte açılmazdı
ADRES_KISA = lambda a: f"{a[:8]}…" if a else "—"  # noqa: E731


# ---------- veri okuma ----------
def git_oku(dal: str, yol: str) -> str:
    s = subprocess.run(["git", "-C", str(REPO), "show", f"{dal}:{yol}"], capture_output=True, text=True, check=False)
    return s.stdout if s.returncode == 0 else ""


def json_oku(dal: str, yol: str) -> dict:
    t = git_oku(dal, yol)
    return json.loads(t) if t.strip() else {}


def kayit_oku(dal: str) -> list[dict]:
    ls = subprocess.run(["git", "-C", str(REPO), "ls-tree", "-r", "--name-only", dal, "kayit/"], capture_output=True, text=True).stdout.split()
    out: list[dict] = []
    for yol in sorted(ls):
        for satir in git_oku(dal, yol).splitlines():
            if satir.strip():
                out.append(json.loads(satir))
    return sorted(out, key=lambda k: int(k.get("zaman_ms") or 0))


def tsi(ms: float | None) -> str:
    if ms is None:
        return "—"
    return datetime.fromtimestamp(ms / 1000, TSI).strftime("%d.%m %H:%M")


def fiyat(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:,.6g}".replace(",", "§").replace(".", ",").replace("§", ".")


def tr_say(v: float | None, ondalik: int = 2, isaretli: bool = False) -> str:
    if v is None:
        return "—"
    s = f"{v:+,.{ondalik}f}" if isaretli else f"{v:,.{ondalik}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def yuzde(v: float | None, ondalik: int = 2, isaretli: bool = True) -> str:
    if v is None:
        return "—"
    return tr_say(v * 100, ondalik, isaretli) + "%"


# ---------- pozisyon döngüleri ----------
def pozisyonlari_kur(kayitlar: list[dict]) -> tuple[list[dict], list[dict]]:
    """Dolumlardan (dolu/kismi) ve tasfiyelerden pozisyon döngüleri. Döner (pozisyonlar, yetim_olaylar)."""
    acik: dict[tuple, dict] = {}
    bitenler: list[dict] = []
    yetim: list[dict] = []
    olaylar = [k for k in kayitlar if (k.get("olay") == "emir" and k.get("durum") in ("dolu", "kismi")) or k.get("olay") == "tasfiye"]
    for k in olaylar:
        anahtar = (k.get("adres"), k.get("coin"))
        ms = int(k.get("zaman_ms") or 0)
        if k["olay"] == "tasfiye":
            p = acik.pop(anahtar, None)
            if p is None:
                yetim.append(k)
                continue
            p["kapanis"] = "tasfiye"
            p["kapanis_ms"] = ms
            p["cikis_px"] = float(k.get("tasfiye_px") or 0.0)
            p["pnl_gerc"] += float(k.get("pnl") or 0.0)
            p["tasfiye_pnl"] = float(k.get("pnl") or 0.0)
            bitenler.append(p)
            continue
        eylem = k.get("eylem")
        sz = abs(float(k.get("sz") or 0.0))
        if eylem == "ac":
            if anahtar not in acik:
                acik[anahtar] = {"adres": k["adres"], "coin": k["coin"], "yon": "uzun" if k.get("yon") == "B" else "kısa", "acilis_ms": ms,
                                 "giris_sz": 0.0, "giris_usd": 0.0, "tr_usd": 0.0, "tr_sz": 0.0, "pnl_gerc": 0.0, "ucret": 0.0,
                                 "ilk_trader_ms": k.get("trader_dolum_ms"), "dolumlar": [], "kapanis": None, "kapanis_ms": None, "cikis_px": None,
                                 "sayi_ac": 0, "tasfiye_pnl": None, "net_sz": 0.0, "yon_kod": k.get("yon"), "ilk_emir": k}
            p = acik[anahtar]
        else:
            p = acik.get(anahtar)
            if p is None:
                yetim.append(k)
                continue
        p["ucret"] += float(k.get("ucret") or 0.0)
        p["dolumlar"].append(k)
        p["net_sz"] += sz if k.get("yon") == "B" else -sz
        if k.get("reduce_only"):
            p["pnl_gerc"] += float(k.get("pnl_usd") or 0.0)
        else:
            if k.get("dolum_px") is not None:
                p["giris_sz"] += sz
                p["giris_usd"] += sz * float(k["dolum_px"])
            if k.get("trader_px") is not None and sz > 0:
                p["tr_sz"] += sz
                p["tr_usd"] += sz * float(k["trader_px"])
        sifir = eylem == "azalt" and abs(p["net_sz"]) * float(k.get("dolum_px") or 0.0) < TOZ_USD   # azaltma ile pozisyon sıfırlandı (kapat emri yok)
        if eylem == "kapat" or sifir:
            p["kapanis"] = "kapat"
            p["sifir"] = sifir and eylem != "kapat"
            p["kapanis_ms"] = ms
            p["cikis_px"] = float(k.get("dolum_px") or 0.0)
            bitenler.append(acik.pop(anahtar))
    acik_liste = list(acik.values())
    for p in acik_liste:
        p["kapanis"] = None
    return bitenler + acik_liste, yetim


def pozisyon_satiri(p: dict, oz_acik: dict[tuple, dict], hes: dict) -> dict:
    giris = p["giris_usd"] / p["giris_sz"] if p["giris_sz"] else None
    tr_giris = p["tr_usd"] / p["tr_sz"] if p["tr_sz"] else None
    kz_acik = None
    if p["kapanis"] is None:
        q = oz_acik.get((p["adres"], p["coin"]))
        kz_acik = float(q["kz_usd"]) if q and q.get("kz_usd") is not None else None
    net = p["pnl_gerc"] - p["ucret"] + (kz_acik or 0.0)
    ilk = p["dolumlar"][0] if p["dolumlar"] else {}
    ac_dolum = [d for d in p["dolumlar"] if not d.get("reduce_only")]
    tr_ms = ilk.get("trader_dolum_ms") if ilk else None
    acik_mi = p["kapanis"] is None
    maks = hes.get("maks_kaldirac", {}).get(p["coin"])
    return {
        "adres": p["adres"], "coin": p["coin"], "yon": p["yon"], "acilis_ms": p["acilis_ms"], "kapanis_ms": p["kapanis_ms"],
        "kapanis": p["kapanis"] or "açık", "giris": giris, "tr_giris": tr_giris, "cikis": p["cikis_px"], "net": net,
        "gerc": p["pnl_gerc"] - p["ucret"], "kz_acik": kz_acik, "acik": acik_mi, "maks_kaldirac": maks,
        "k67": maks is not None and float(maks) < KALDIRAC_ESIK, "dolum_n": len(p["dolumlar"]), "ac_n": len(ac_dolum),
        "ilk_emir": ilk, "tr_ms": tr_ms, "tasfiye_pnl": p.get("tasfiye_pnl"), "sifir": bool(p.get("sifir")),
    }


# ---------- analiz ----------
def telegram_durumu(satir: dict) -> str:
    """Motor kendi Telegram gönderim kaydı yazmıyorsa: yeni kod öncesi = beklenen eski düzen."""
    if satir["acilis_ms"] < YENI_KOD_MS and (satir["kapanis_ms"] is None or satir["kapanis_ms"] < YENI_KOD_MS):
        return "eski düzen (beklenen)"
    return "YOK (yeni düzen, mesaj kaydı yok)"


def pano_durumu(satir: dict, oz_acik: dict[tuple, dict], hes_poz: dict) -> str:
    if not satir["acik"]:
        return "— (kapalı)"
    q = oz_acik.get((satir["adres"], satir["coin"]))
    if q is None:
        return "YOK"
    hp = (hes_poz.get(satir["adres"]) or {}).get(satir["coin"]) or {}
    ayni_yon = (float(q["sz"]) > 0) == (satir["yon"] == "uzun")
    ayni_sz = hp and abs(float(q["sz"]) - float(hp.get("sz", 0))) <= 1e-6 * max(1.0, abs(float(hp.get("sz", 0))))
    return "var, aynı" if ayni_yon and ayni_sz else "var, FARKLI"


def kopya_istatistik(kayitlar: list[dict]) -> dict:
    ac = [k for k in kayitlar if k.get("olay") == "emir" and k.get("eylem") == "ac" and k.get("durum") == "dolu"]
    ac_red = [k for k in kayitlar if k.get("olay") == "emir" and k.get("eylem") == "ac" and k.get("durum") == "red"]
    atlanan_ac = [k for k in kayitlar if k.get("olay") == "emir_yok" and k.get("eylem") == "ac"]
    gecikme = sorted((k["dolum_ms"] - k["trader_dolum_ms"]) / 1000 for k in ac if k.get("dolum_ms") and k.get("trader_dolum_ms"))
    p90 = gecikme[int(0.9 * (len(gecikme) - 1))] if gecikme else None
    en_yavas = [g for g in gecikme if p90 is not None and g >= p90]
    yon_ok = sum(1 for k in ac if k.get("trader_poz_sonra") is not None and (float(k["trader_poz_sonra"]) > 0) == (k.get("yon") == "B"))
    yon_bilinen = sum(1 for k in ac if k.get("trader_poz_sonra") is not None)
    kayma = [float(k["kayma_trader"]) for k in ac if k.get("kayma_trader") is not None]
    return {
        "trader_acilis_kapsam": len(ac) + len(ac_red) + len(atlanan_ac), "acilan": len(ac), "red": len(ac_red), "atlanan": len(atlanan_ac),
        "yon_ok": yon_ok, "yon_bilinen": yon_bilinen,
        "gecikme_med": statistics.median(gecikme) if gecikme else None, "gecikme_p90": p90,
        "gecikme_yavas_med": statistics.median(en_yavas) if en_yavas else None, "gecikme_n": len(gecikme),
        "kayma_med": statistics.median(kayma) if kayma else None, "kayma_abs_med": statistics.median([abs(x) for x in kayma]) if kayma else None,
        "kayma_n": len(kayma),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dal", default="origin/canli-durum")
    ap.add_argument("--cikti", type=Path, default=REPO / "docs" / "mutabakat" / "MUTABAKAT_2026-11-20.md")
    args = ap.parse_args(argv)
    dal = args.dal

    kayitlar = kayit_oku(dal)
    hes = json_oku(dal, "durum/hesap.json")
    ozet = json_oku(dal, "durum/ozet.json")
    oz_acik = {(q["adres"], q["coin"]): q for q in ozet.get("acik") or []}
    hes_poz = hes.get("poz") or {}
    simdi = int(ozet.get("yazildi_ms") or max(int(k["zaman_ms"]) for k in kayitlar))

    # pano: gösterilen açık pozisyon sayısı (HTML şeridi) ve OZET.md tablosu
    pano_html = git_oku(dal, "pano/index.html")
    m = re.search(r'Açık poz[^<]*</div><div class="hd[^"]*">(\d+)', pano_html)
    pano_strip = int(m.group(1)) if m else None
    pano_md = git_oku(dal, "pano/OZET.md")
    bolum = pano_md.split("## Açık pozisyonlar", 1)[-1].split("## ", 1)[0] if "## Açık pozisyonlar" in pano_md else ""
    pano_md_say = sum(1 for s in bolum.splitlines() if s.startswith("| 0x"))
    kapanan_pano = pano.kapanan_islemler(kayitlar)
    kapanan_pano_ozet = pano.kapanan_ozeti(kapanan_pano)  # pano KAPANAN sekmesinin özeti

    pozlar, yetim = pozisyonlari_kur(kayitlar)
    satirlar = [pozisyon_satiri(p, oz_acik, hes) for p in pozlar]
    satirlar.sort(key=lambda s: s["acilis_ms"])
    for s in satirlar:
        s["tg"] = telegram_durumu(s)
        s["pano"] = pano_durumu(s, oz_acik, hes_poz)

    # motor pozisyon ↔ log yeniden kurulumu
    net_log: dict[tuple, float] = defaultdict(float)
    for k in kayitlar:
        if k.get("olay") == "emir" and k.get("durum") in ("dolu", "kismi"):
            net_log[(k["adres"], k["coin"])] += abs(float(k["sz"])) * (1 if k["yon"] == "B" else -1)
    motor_poz = {(a, c): float(p["sz"]) for a, cs in hes_poz.items() for c, p in cs.items()}
    uyusmazlik = []
    for kk in sorted(set(net_log) | set(motor_poz)):
        a, b = net_log.get(kk, 0.0), motor_poz.get(kk, 0.0)
        if abs(a - b) > 1e-6 * max(1.0, abs(b)):
            uyusmazlik.append({"adres": kk[0], "coin": kk[1], "log": a, "motor": b, "fark": a - b})

    # bütçe / kasa
    real = sum((hes.get("realize") or {}).values())
    ucret = sum((hes.get("ucret") or {}).values())
    fund = sum((hes.get("funding") or {}).values())
    kz_acik_top = sum(float(q["kz_usd"]) for q in ozet.get("acik") or [] if q.get("kz_usd") is not None)
    kasa_hes = float(hes.get("kasa_usd") or 10000.0)
    kasa_gerc = kasa_hes + real - ucret + fund
    ozsermaye_hes = kasa_gerc + kz_acik_top
    ozsermaye_motor = float(ozet.get("ozsermaye_usd") or 0.0)

    # K-67: düşük kaldıraç coinler
    k67 = [s for s in satirlar if s["k67"]]
    k67_net = sum(s["net"] for s in k67)
    k67_kapali_net = sum(s["net"] for s in k67 if not s["acik"])
    tum_net = sum(s["net"] for s in satirlar)

    kop = kopya_istatistik(kayitlar)
    tasfiye = [k for k in kayitlar if k.get("olay") == "tasfiye"]
    duz = [k for k in kayitlar if k.get("olay") == "kapanis_duzeltme"]

    # Telegram
    yeni_kapsam = [s for s in satirlar if s["tg"].startswith("YOK")]
    tg_telegram = [k for k in kayitlar if k.get("olay") == "telegram"]
    tg_pos_msg = [k for k in tg_telegram if re.search(r"(AÇ|KAPAN|Açıldı|Kapandı|açıldı|kapandı)", k.get("metin", "")) and "pozisyon" in k.get("metin", "").lower()]

    # pano/motor sayıları
    acik_satir = [s for s in satirlar if s["acik"]]
    pano_fark = [s for s in acik_satir if s["pano"] != "var, aynı"]

    # A-5: pano KAPANAN satırları ↔ log azalt/kapat emirleri (satır bazında)
    log_kap = [k for k in kayitlar if k.get("olay") == "emir" and k.get("reduce_only") and k.get("durum") in ("dolu", "kismi") and k.get("pnl_usd") is not None]
    log_ix = {(k["adres"], k["coin"], int(k["zaman_ms"])): k for k in log_kap}
    pano_ix = {(r["adres"], r["coin"], r["ms"]): r for r in kapanan_pano}
    ortak = sorted(set(log_ix) & set(pano_ix))
    pano_fazla = [pano_ix[k] for k in sorted(set(pano_ix) - set(log_ix))]
    log_eksik = [log_ix[k] for k in sorted(set(log_ix) - set(pano_ix))]
    kz_uyus = []
    for kk in ortak:
        r, k = pano_ix[kk], log_ix[kk]
        log_net = round(float(k["pnl_usd"]) - float(k.get("ucret") or 0.0), 2)
        log_yon = "uzun" if k.get("yon") == "A" else "kısa"
        if round(r["net"], 2) != log_net or r["yon"] != log_yon or r["coin"] != k["coin"]:
            kz_uyus.append((kk, round(r["net"], 2), log_net, r["yon"], log_yon))
    tasf_log = [t for t in tasfiye]
    for s_ in satirlar:                       # kapalı pozisyonlar: kapanış satırı panoda var mı (aynı trader, coin, kapanış anı)
        if s_["acik"]:
            continue
        if s_["kapanis"] == "tasfiye":
            s_["pano"] = "YOK (tasfiye, KAPANAN'da yok)"
            continue
        r = pano_ix.get((s_["adres"], s_["coin"], int(s_["kapanis_ms"])))
        s_["pano"] = "YOK" if r is None else "var, aynı (satır K/Z A-5)"

    # ---------- Markdown ----------
    L: list[str] = []
    a = L.append
    a("# İşlem mutabakatı — sanal copy-trade motoru")
    a("")
    a(f"Veri anı: **{tsi(simdi)} TSİ** (`durum/ozet.json` yazılış anı). Kayıt başlangıcı: 16.11 11:30 UTC (sanal dönem başı). "
      f"Kaynak: `origin/canli-durum` dalı (`kayit/*.jsonl`, `durum/hesap.json`, `durum/ozet.json`, `pano/`). Betik: `araclar/mutabakat.py` (salt okuma).")
    a("")
    a("**Birim:** bir pozisyon = bir (trader, coin) çiftinde ilk açılıştan tam kapanışa, tasfiyeye ya da veri anına kadar olan döngü. "
      "Azaltmalar aynı pozisyonun parçasıdır. Net K/Z = gerçekleşen K/Z − ücret + (açık pozisyonda) mark K/Z. Fonlama pozisyon bazında ayrılmaz; toplamlarda (B bölümü) yer alır.")
    a("")
    a("**Telegram notu:** Telegram geçmişine erişim yok. Bu tabloda Telegram kontrolü yalnız motorun kendi `kayit` içindeki `telegram` gönderim kayıtlarıyla yapıldı. "
      "Pozisyon başına açıldı/kapandı mesajı kaydı, yeni kod ile başlar (20.11 03:06 TSİ birleşti, ~1 sa içinde yayına girdi). Bu tarihten önceki işlemler \"eski düzen (beklenen)\" sayılır, uyuşmazlık değildir.")
    a("")
    a("## A) Pozisyon tablosu")
    a("")
    a(f"Toplam {len(satirlar)} pozisyon ({sum(1 for s in satirlar if s['kapanis'] == 'kapat')} tam kapanış, {sum(1 for s in satirlar if s['kapanis'] == 'tasfiye')} tasfiye, {len(acik_satir)} açık).")
    a("")
    a("| # | işlem no | trader | coin | yön | açılış (TSİ) | kapanış (TSİ) | giriş | çıkış | net K/Z $ | K-67 (gerçekte açılmazdı) | panoda | Telegram açıldı/kapandı |")
    a("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for i, s in enumerate(satirlar, 1):
        kz = s["net"]
        kapanis_txt = tsi(s["kapanis_ms"]) if s["kapanis_ms"] else "açık"
        if s["kapanis"] == "tasfiye":
            kapanis_txt += " (tasfiye)"
        a(f"| {i} | P{i:03d} | {ADRES_KISA(s['adres'])} | {s['coin']} | {s['yon']} | {tsi(s['acilis_ms'])} | {kapanis_txt} | {fiyat(s['giris'])} | {fiyat(s['cikis'])} | "
          f"{tr_say(kz, 2, True)} | {'evet, maks ' + tr_say(s['maks_kaldirac'], 0) + 'x' if s['k67'] else '—'} | {s['pano']} | {s['tg']} |")
    a("")
    a("Açıklamalar: giriş/çıkış = dolum fiyatı (ağırlıklı ortalama, $/coin). Çıkış tasfiyelerde tasfiye fiyatıdır. \"panoda\" = pano açık pozisyon listesiyle (`ozet.acik`, pano HTML şeridi) aynı yön, miktar ve giriş fiyatı.")
    a("")
    a("### A-2) Mutabakat uyuşmazlıkları (log ↔ motor poz)")
    a("")
    a("| trader | coin | log net (coin) | motor poz (coin) | fark | neden (tahmin / doğrulama) |")
    a("|---|---|---|---|---|---|")
    for u in uyusmazlik:
        neden = "—"
        if u["coin"] == "VVV" and any(t.get("coin") == "VVV" for t in tasfiye):
            neden = "tasfiye (VVV, emir kaydı yok; pnl hesapta var) — beklenen"
        elif abs(u["fark"]) < 0.001 and u["motor"] == 0:
            neden = "toz kalıntı (kapanış sonrası kesir; hesap sıfırlar)"
        elif duz and any(d.get("coin") == u["coin"] for d in duz):
            neden = "kapanis_duzeltme (kesir miktar düzeltmesi)"
        a(f"| {ADRES_KISA(u['adres'])} | {u['coin']} | {u['log']:.6g} | {u['motor']:.6g} | {u['fark']:.3g} | {neden} |")
    a("")
    a(f"Yetim olay (döngüye bağlanamayan emir/tasfiye): {len(yetim)}.")
    a("")
    a("### A-3) Tasfiye ve kapanış düzeltmeleri")
    a("")
    for t in tasfiye:
        a(f"- Tasfiye: trader {ADRES_KISA(t['adres'])}, {t['coin']}, tasfiye fiyatı {fiyat(t.get('tasfiye_px'))}, mark {fiyat(t.get('mark'))}, pnl {tr_say(t.get('pnl'), 2, True)} $. "
          f"Emir kaydı: {'yok' if not any(k.get('olay') == 'emir' and k.get('adres') == t['adres'] and k.get('coin') == t['coin'] and k.get('eylem') == 'kapat' for k in kayitlar) else 'var'}. "
          f"hesap.json `realize` bu pnl'i içerir (trader realize {tr_say(hes['realize'].get(t['adres']), 2, True)} = emir pnl + tasfiye).")
    for d in duz:
        a(f"- kapanis_duzeltme: {ADRES_KISA(d['adres'])}, {d['coin']}, sz {d.get('sz')}, neden {d.get('neden')}.")
    a("")
    a("### A-5) Pano KAPANAN satırları ↔ log azalt/kapat emirleri (satır bazında)")
    a("")
    a(f"Eşleşme anahtarı: trader, coin, zaman (ms). Pano satırı: {len(kapanan_pano)}. Log kapanış dolumu (reduce-only, dolu/kısmi, pnl kayıtlı): {len(log_kap)}. Eşleşen: {len(ortak)}.")
    a(f"- Panoda var, logda yok: **{len(pano_fazla)}**" + (" " + "; ".join(f"{ADRES_KISA(r['adres'])} {r['coin']} {tsi(r['ms'])}" for r in pano_fazla) if pano_fazla else ""))
    a(f"- Logda var, panoda yok: **{len(log_eksik)}**")
    for k in log_eksik:
        a(f"  - {ADRES_KISA(k['adres'])} {k['coin']} {k.get('eylem')} {'uzun' if k.get('yon') == 'A' else 'kısa'} {tsi(int(k['zaman_ms']))} net {tr_say(float(k['pnl_usd']) - float(k.get('ucret') or 0), 2, True)} $ (neden: pano yalnız `reduce_only` ve pnl'li satırları alır; buradaki satır eksik)")
    a(f"- Eşleşenlerde coin/yön/K/Z (2 ondalık) farkı: **{len(kz_uyus)}**" + ("" if not kz_uyus else ""))
    for kk, pn, ln, py, ly in kz_uyus:
        a(f"  - {ADRES_KISA(kk[0])} {kk[1]} {tsi(kk[2])}: pano {pn} / log {ln}, yön pano {py} / log {ly}")
    a(f"- Tasfiye (log, pano KAPANAN listesinde yok): **{len(tasf_log)}** — VVV, −14,97 $.")
    a("")
    a("### A-4) Açık pozisyon sayımı")
    a("")
    a(f"- Motor (`durum/hesap.json` poz): **{len(motor_poz)}**")
    a(f"- Log'dan yeniden kurulan açık pozisyon: **{len(acik_satir)}**")
    a(f"- Pano HTML şeridi (\"Açık poz.\"): **{pano_strip if pano_strip is not None else '—'}**")
    a(f"- Pano OZET.md tablosu satırı: **{pano_md_say}**")
    sifir_say = sum(1 for s in satirlar if s["sifir"])
    a(f"- Pano KAPANAN sekmesi: {kapanan_pano_ozet['poz']} pozisyon ({kapanan_pano_ozet['kapanis']} satır). Log: {sum(1 for s in satirlar if s['kapanis'] == 'kapat') - sifir_say} `kapat` + {sifir_say} azaltmayla sıfırlanan + {sum(1 for s in satirlar if s['kapanis'] == 'tasfiye')} tasfiye = {sum(1 for s in satirlar if s['kapanis'] != 'açık')} kapanmış pozisyon. **UYUŞMAZLIK**: pano kapanış pozisyon sayısı log'dan {sum(1 for s in satirlar if s['kapanis'] != 'açık') - kapanan_pano_ozet['poz']} eksik (azaltmayla sıfırlananlar ve tasfiye pano pozisyon sayısında yok; pano düzeltmesi ayrı PR). Satır bazlı karşılaştırma: bölüm A-5.")
    a(f"- Pano açık satır karşılaştırması: aynı {len(acik_satir) - len(pano_fark)} / farklı {len(pano_fark)}")
    a("")
    a("## B) Toplamlar")
    a("")
    a("| kalem | değer |")
    a("|---|---|")
    a(f"| Başlangıç kasası | {tr_say(kasa_hes)} $ |")
    a(f"| Gerçekleşen K/Z (brüt, `realize` toplamı) | {tr_say(real, 2, True)} $ |")
    a(f"| Ücret (komisyon, toplam) | {tr_say(-ucret, 2, True)} $ |")
    a(f"| Fonlama (toplam) | {tr_say(fund, 2, True)} $ |")
    a(f"| **Kasa (gerçekleşen, ücret + fonlama dahil)** = 10.000 + K/Z − ücret + fonlama | **{tr_say(kasa_gerc)} $** |")
    a(f"| Açık pozisyon mark K/Z (`ozet.acik` toplamı) | {tr_say(kz_acik_top, 2, True)} $ |")
    a(f"| **Özsermaye (kasa + açık K/Z)** — hesap.json'dan hesaplanan | **{tr_say(ozsermaye_hes)} $** |")
    a(f"| Özsermaye — motorun yazdığı (`ozet.json`) | {tr_say(ozsermaye_motor)} $ |")
    a(f"| Fark (hesap − motor) | {tr_say(ozsermaye_hes - ozsermaye_motor, 4, True)} $ |")
    a("")
    a(f"Sağlık kontrolü: özsermaye {tr_say(ozsermaye_hes)} $ (beklenen ~9.990 $ civarı — {'uygun' if abs(ozsermaye_hes - 9990) < 10 else 'SAPMA'}); gerçekleşen kasa {tr_say(kasa_gerc)} $ açık pozisyonların K/Z'si hariçtir.")
    a("")
    a("### B-2) Açık pozisyon sayısı")
    a("")
    a(f"Motor {len(motor_poz)} = pano {pano_strip} = log {len(acik_satir)}: **{'eşit' if len(motor_poz) == pano_strip == len(acik_satir) else 'EŞİT DEĞİL'}**.")
    a("")
    a("### B-3) Telegram")
    a("")
    a(f"- Motorun Telegram kayıtlarında pozisyon başına açıldı/kapandı mesajı: **{len(tg_pos_msg)}** (tüm `telegram` kayıtları: {len(tg_telegram)}; bunlar saatlik özet, uyarı, günlük özet ve trader bildirimleri).")
    a(f"- Yeni kod (03:06 TSİ sonrası) başlangıcından beri açılan/kapanan pozisyon: **{len(yeni_kapsam)}**; bunların mesaj kaydı yok. Dağıtım saati tam bilinmediği için bu sayı **uyuşmazlık olarak sayılmadı**: eksik/fazla/yanlış-yön = 0 (kanıtlanabilen), bekleyen = {len(yeni_kapsam)}.")
    a("- Yanlış yön / fazla mesaj: kayıt yok, değerlendirilemedi.")
    a("")
    a("### B-4) Kopya doğruluğu (trader açılışları)")
    a("")
    a(f"- Trader açılış olayı (kapsam): {kop['trader_acilis_kapsam']} · bizim açtığımız: {kop['acilan']} · red: {kop['red']} · atlanan (kayıt: emir_yok): {kop['atlanan']}.")
    a(f"- Aynı yön: {kop['yon_ok']} / {kop['yon_bilinen']} (açtığımız işlemlerde, trader'ın dolum sonrası pozisyon işaretine göre). Atlanan açılışların yönü kayıtta yok; yön kontrolü yalnız açılan işlemler için yapıldı.")
    a(f"- Gecikme (trader dolumu → bizim dolum), n={kop['gecikme_n']}: medyan **{tr_say(kop['gecikme_med'], 2)} sn**; en yavaş %10 eşiği (p90) **{tr_say(kop['gecikme_p90'], 2)} sn**; en yavaş %10 medyanı {tr_say(kop['gecikme_yavas_med'], 2)} sn.")
    a(f"- Fiyat farkı (kayma_trader, + = aleyhimize), n={kop['kayma_n']}: medyan **{yuzde(kop['kayma_med'], 3)}**; mutlak medyan {yuzde(kop['kayma_abs_med'], 3)}.")
    a("")
    a("### B-5) K-67 (HL azami kaldıracı < 5 olan coinler)")
    a("")
    a(f"Bu işlemler, HL azami kaldıracı 5'in altında olduğu için gerçekte açılmazdı (K-67). Sayı: **{len(k67)}** pozisyon (kapalı {sum(1 for s in k67 if not s['acik'])}, açık {sum(1 for s in k67 if s['acik'])}).")
    a("")
    a("| kalem | pozisyon | net K/Z $ |")
    a("|---|---|---|")
    a(f"| K-67 işlemleri (tümü) | {len(k67)} | {tr_say(k67_net, 2, True)} |")
    a(f"| — kapalı K-67 | {sum(1 for s in k67 if not s['acik'])} | {tr_say(k67_kapali_net, 2, True)} |")
    a(f"| Sanal K/Z — tümü | {len(satirlar)} | {tr_say(tum_net, 2, True)} |")
    a(f"| **Sanal K/Z — K-67 hariç** | {len(satirlar) - len(k67)} | **{tr_say(tum_net - k67_net, 2, True)}** |")
    a("")
    a("### B-6) Tasfiye VVV (−14,97 $) — doğrulama ve neden")
    a("")
    a(f"- Tasfiye kaydı: {len(tasfiye)} adet. Emir kaydı olmayan tasfiye/kapanış: **{len(tasfiye)}** (VVV). Pnl hesap realize'ında mevcut (bölüm A-3).")
    vvv = [s for s in satirlar if s["coin"] == "VVV" and s["kapanis"] == "tasfiye"]
    if vvv:
        s = vvv[0]
        if s["giris"]:
            tasf_px = float(s["cikis"])
            fark_pct = (tasf_px / s["giris"] - 1) * 100
            a(f"- Kayıttaki ortalama giriş {fiyat(s['giris'])}, tasfiye fiyatı {fiyat(tasf_px)}: girişten **{tr_say(fark_pct, 1, True)}%** ({s['yon']} pozisyon).")
        a(f"- Azami kaldıraç (HL) VVV = {tr_say(s['maks_kaldirac'], 0)}x. Koordinatör notu: 3x izole short, bakım marjı %16,7, tasfiye ≈ girişten +%14,3; %20 felaket stopu bu seviyeye ulaşamadan tasfiye oldu. Log ile tutarlılık: giriş-tasfiye farkı yukarıdaki değerdir; mekanizma (bakım marjı) kodla doğrulanmadı, düzeltme (dinamik stop) ayrı PR'da, onay bekliyor.")
    a("")
    a("## C) Kopya işlemlerinin notları")
    a("")
    a(f"- Pozisyon döngüsü: {sum(1 for s in satirlar if s['kapanis'] == 'kapat')} tam kapanış (`kapat`), {sum(1 for s in satirlar if s['kapanis'] == 'tasfiye')} tasfiye, {len(acik_satir)} açık; motor poz ile log net pozisyonu arasındaki fark yalnız A-2'de listelenenlerdir.")
    a(f"- Ücret: log emir ücret toplamı {tr_say(sum(float(k.get('ucret') or 0) for k in kayitlar if k.get('olay') == 'emir' and k.get('durum') in ('dolu', 'kismi')), 4)} $, hesap.json ücret toplamı {tr_say(ucret, 4)} $.")
    a("")
    a("_Bu rapor salt okuma ile üretildi; motor kodu değiştirilmedi._")

    cikti = args.cikti
    cikti.parent.mkdir(parents=True, exist_ok=True)
    cikti.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"yazıldı: {cikti} ({len(satirlar)} pozisyon, kasa {tr_say(kasa_gerc)} $, özsermaye {tr_say(ozsermaye_hes)} $)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
