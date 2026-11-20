"""Rejim ve duygu x işlem sonucu raporu (`ct.rejim_sonuc.v1`): `durum/paylasim/rejim_sonuc_v1.json` + `.md` (orkestratör haftalık karşılaştırma tablosu). YALNIZ BİLGİ: karar/emir yoluna girmez.

Giriş anı damgası: pozisyon AÇILIRKEN coin'in rejimi (1g/4s) ve duygu sınıfı/değeri `Poz.giris_ctx`a yazılır (hesap.json ile kalıcı); kapanış `emir` kaydı bunu `giris_ctx` alanıyla taşır.
Toplama: son 7 günün `kayit/*.jsonl` dosyalarındaki kapanış emirleri (`eylem=kapat`, dolu/kısmi, `pnl_usd` var). Damgasız (eski) işlemler "bilinmiyor" kovasına düşer.
PnL = gerçekleşen K/Z (ücret hariç). Yalnız `kapat` dolumu toplanır (tasarım: rejim damgası kapanış kaydında; kısmi `azalt` dolumları dahil değil), bu yüzden gunluk_ozet'in toplam gerçekleşen K/Z'sinden FARKLI olabilir.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from copytrade.canli import haber, rejim
from copytrade.canli.hafta_paketi import _yaz_atomik

SEMA = "ct.rejim_sonuc.v1"
DOSYA_JSON = "rejim_sonuc_v1.json"
DOSYA_MD = "rejim_sonuc_v1.md"
PENCERE_GUN = 7
BILINMIYOR = "bilinmiyor"
_DOLU = ("dolu", "kismi")


def giris_ctx(rejim_anlik: dict | None, haber_anlik: dict | None, coin: str, simdi_ms: int) -> dict | None:
    """Açılış anı bağlamı `{r1d, r4h, duygu, duygu_deger}`; hiçbiri yoksa None. İstisna fırlatmaz."""
    try:
        r = rejim.coin_rejimi(rejim_anlik or {}, coin, simdi_ms) or {}
        d = haber.duygu_ozet(haber_anlik or {}, simdi_ms) or {}
        ctx = {"r1d": r.get("1d"), "r4h": r.get("4h"), "duygu": d.get("sinif"), "duygu_deger": d.get("deger")}
        return ctx if any(v is not None for v in ctx.values()) else None
    except Exception:                                                # noqa: BLE001
        return None


def _say(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") else None


def _kova(ctx: Any, anahtar: str) -> str:
    v = ctx.get(anahtar) if isinstance(ctx, dict) else None
    return str(v) if v else BILINMIYOR


def topla(kayitlar: list[dict], simdi_ms: int, gun: int = PENCERE_GUN) -> dict[str, list[dict]]:
    """Saf fonksiyon: son `gun` günün kapanan işlemlerini rejim (1g, 4s) ve duygu sınıfına göre toplar. Satır: etiket, n, kazanan, isabet_yuzde, toplam_pnl, ortalama_pnl."""
    alt = simdi_ms - gun * 86_400_000
    kovalar: dict[str, dict[str, list[float]]] = {"rejim_1d": {}, "rejim_4h": {}, "duygu": {}}
    for k in kayitlar:
        if k.get("olay") != "emir" or k.get("eylem") != "kapat" or k.get("durum") not in _DOLU:
            continue
        pnl = _say(k.get("pnl_usd"))
        ms = _say(k.get("zaman_ms"))
        if pnl is None or ms is None or ms < alt or ms > simdi_ms:
            continue
        ctx = k.get("giris_ctx")
        for boyut, anahtar in (("rejim_1d", "r1d"), ("rejim_4h", "r4h"), ("duygu", "duygu")):
            kovalar[boyut].setdefault(_kova(ctx, anahtar), []).append(pnl)
    sonuc: dict[str, list[dict]] = {}
    for boyut, kv in kovalar.items():
        satirlar = []
        for etiket in sorted(kv, key=lambda e: (e == BILINMIYOR, e)):
            p = kv[etiket]
            toplam = sum(p)
            kaz = sum(1 for x in p if x > 0)
            satirlar.append({"etiket": etiket, "n": len(p), "kazanan": kaz, "isabet_yuzde": round(100.0 * kaz / len(p), 1),
                             "toplam_pnl": round(toplam, 2), "ortalama_pnl": round(toplam / len(p), 2)})
        sonuc[boyut] = satirlar
    return sonuc


def kayitlari_oku(dizin: Path, simdi_ms: int, gun: int = PENCERE_GUN) -> list[dict]:
    """Pencereyi kapsayan günlük JSONL dosyaları (bozuk satır/eksik dosya atlanır)."""
    satirlar: list[dict] = []
    for i in range(gun + 1):
        g = datetime.fromtimestamp((simdi_ms - i * 86_400_000) / 1000, UTC).date().isoformat()
        try:
            with (Path(dizin) / f"{g}.jsonl").open(encoding="utf-8") as f:
                for s in f:
                    try:
                        o = json.loads(s)
                    except ValueError:
                        continue
                    if isinstance(o, dict):
                        satirlar.append(o)
        except OSError:
            continue
    return satirlar


def olustur(kayitlar: list[dict], simdi_ms: int) -> dict:
    tablolar = topla(kayitlar, simdi_ms)
    toplam_n = sum(r["n"] for r in tablolar["rejim_1d"])
    bil = sum(r["n"] for r in tablolar["rejim_1d"] if r["etiket"] == BILINMIYOR)
    notlar = ["Yalnız bilgi: karar/limit/eşik değiştirmez.",
              "Giriş damgası bu sürümden sonra açılan pozisyonlarda var; eski işlemler 'bilinmiyor' (beklenen).",
              f"Pencere son {PENCERE_GUN} gün kapanan işlemler: {toplam_n}; rejimi bilinmeyen (1g): {bil}.",
              "PnL gerçekleşen K/Z (ücret hariç); duygu = Fear&Greed sınıfı (giriş anı)."]
    return {"sema": SEMA, "proje": "CT", "uretim": datetime.fromtimestamp(simdi_ms / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "pencere_gun": PENCERE_GUN, "tablolar": tablolar, "notlar": notlar}


def markdown(veri: dict) -> str:
    bas = {"rejim_1d": "Rejim (1g)", "rejim_4h": "Rejim (4s)", "duygu": "Duygu"}
    out = [f"# CT rejim ve duygu x işlem sonucu (son {veri['pencere_gun']} gün, {veri['uretim']})", ""]
    for boyut, ad in bas.items():
        out += [f"## {ad}", "", f"| {ad} | İşlem | Kazanan | İsabet % | Toplam PnL $ | Ort. PnL $ |", "|---|---:|---:|---:|---:|---:|"]
        satirlar = veri["tablolar"].get(boyut) or []
        for r in satirlar:
            out.append(f"| {r['etiket']} | {r['n']} | {r['kazanan']} | {r['isabet_yuzde']:.1f} | {r['toplam_pnl']:.2f} | {r['ortalama_pnl']:.2f} |")
        if not satirlar:
            out.append("| - | 0 | 0 | - | 0.00 | - |")
        out.append("")
    out += ["Notlar:", ""] + [f"- {n}" for n in veri["notlar"]]
    return "\n".join(out) + "\n"


def yaz(motor: Any) -> None:
    """`paylasim/rejim_sonuc_v1.json` ve `.md` yazar (hata çağırana çıkar; çağıran yutar)."""
    simdi = int(motor.saat_ms())
    veri = olustur(kayitlari_oku(Path(motor.kayit.dizin), simdi), simdi)
    d = Path(motor.durum_dizin) / "paylasim"
    _yaz_atomik(d / DOSYA_JSON, json.dumps(veri, ensure_ascii=False, indent=1))
    _yaz_atomik(d / DOSYA_MD, markdown(veri))
