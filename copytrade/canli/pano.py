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
from datetime import UTC, datetime
from pathlib import Path

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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--durum", type=Path, default=Path("durum"))
    ap.add_argument("--kayit", type=Path, default=Path("kayit"))
    ap.add_argument("--gecmis", type=Path, default=Path("pano/gecmis.json"))
    ap.add_argument("--cikti", type=Path, default=Path("pano/OZET.md"))
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
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
