"""Kadro seçimi x GERÇEK kopya PnL'i (`ct.secim_gercek.v1`): `durum/paylasim/secim_gercek_v1.json` + `.md`. YALNIZ BİLGİ: seçim, işlem ve limitlere girmez.

DEĞİŞKEN (zayıf, dürüst): "İlk 11, rastgele 11'e karşı" gerçek PnL ile YAPILAMAZ; çünkü gerçek (sanal hesapta kopyalanan) PnL yalnız sahaya girmiş traderlar için var.
Yedek traderların varsayımsal kopya PnL'ini hesaplayan bir yer yok (`karsi_olgu` alınmayan SİNYALİ izler, yedek traderı değil). Bu yüzden her UTC günü için:
O gün gerçekten kopyalanan (>=1 dolu emir) ve o günün kadro listesinde (ilk11 + yedek; saha haftalık olduğundan üye ilk11 dışına düşmüş olabilir) form puanı olan traderlar için gerçek net PnL (gerçekleşen K/Z - ücret) ile o günün kadro FORM puanı (R2) arasında Spearman rho;
permütasyon p (tek yönlü: rho >= gözlenen; küçük p = yüksek form daha iyi PnL getirmiş). n! <= 1000 ise TÜM permütasyonlar sayılır, değilse 1000 karıştırma (sabit tohum).
Toplu: günlük rho ortalaması; p = gün içi karıştırmayla aynı istatistik. Günler arası örtüşme/bağımlılık var; <3 trader olan gün atlanır. Küçük örneklem: yalnız bilgi.
Form geçmişi `durum/form_gecmis.json`da (gün -> {form: {adres: form}, ilk11_n, yedek_n}; kadro her okunduğunda, 14 gün) tutulur; kimlik dışarıya yalnız `takma_ad` ile çıkar.
"""
from __future__ import annotations

import json
import os
import random
import tempfile
from datetime import UTC, datetime
from itertools import permutations
from math import factorial
from pathlib import Path
from typing import Any

from copytrade.canli.ogrenme_adaptor import takma_ad

SEMA = "ct.secim_gercek.v1"
DOSYA_JSON = "secim_gercek_v1.json"
DOSYA_MD = "secim_gercek_v1.md"
GECMIS = "form_gecmis.json"
PENCERE_GUN = 14
MIN_TRADER = 3
R = 1000
_DOLU = ("dolu", "kismi")
_GUN_MS = 86_400_000


def _say(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") else None


def _gun(ms: float) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).date().isoformat()


def _rank(x: list[float]) -> list[float]:
    """Ortalama sıra (eşitlikte ortak sıra)."""
    sirali = sorted(range(len(x)), key=lambda i: x[i])
    r = [0.0] * len(x)
    i = 0
    while i < len(sirali):
        j = i
        while j + 1 < len(sirali) and x[sirali[j + 1]] == x[sirali[i]]:
            j += 1
        for k in range(i, j + 1):
            r[sirali[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def _pearson(a: list[float], b: list[float]) -> float | None:
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    sa = sum((x - ma) ** 2 for x in a)
    sb = sum((y - mb) ** 2 for y in b)
    if sa == 0 or sb == 0:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True)) / (sa * sb) ** 0.5


def spearman(form: list[float], pnl: list[float]) -> float | None:
    """Spearman rho (ortalama sıralı Pearson); sabit dizide None."""
    return _pearson(_rank(form), _rank(pnl))


def gun_testi(form: list[float], pnl: list[float], tohum: int, r: int = R) -> dict:
    """Tek gün: rho ve tek yönlü permütasyon p (rho_perm >= rho). n! <= r ise tam sayım."""
    n = len(form)
    rho = spearman(form, pnl)
    if rho is None:
        return {"rho": None, "p": None, "yontem": "sabit"}
    rf = _rank(form)
    rp = _rank(pnl)
    if factorial(n) <= r:
        kar = [_pearson(rf, list(p)) for p in permutations(rp)]
        yontem = "tam"
    else:
        rng = random.Random(tohum)
        kar = []
        for _ in range(r):
            p = rp[:]
            rng.shuffle(p)
            kar.append(_pearson(rf, p))
        yontem = "ornek"
    p = sum(1 for k in kar if k is not None and k >= rho - 1e-12) / len(kar)
    return {"rho": rho, "p": p, "yontem": yontem}


def gunluk_pnl(kayitlar: list[dict]) -> dict[str, dict[str, dict]]:
    """gün -> adres -> {pnl, ucret, net, n}: dolu/kısmi emirlerden gerçekleşen K/Z ve ücret (tüm dolumlar)."""
    out: dict[str, dict[str, dict]] = {}
    for k in kayitlar:
        if k.get("olay") != "emir" or k.get("durum") not in _DOLU or not k.get("adres"):
            continue
        ms = _say(k.get("zaman_ms"))
        if ms is None:
            continue
        s = out.setdefault(_gun(ms), {}).setdefault(str(k["adres"]).lower(), {"pnl": 0.0, "ucret": 0.0, "n": 0})
        s["pnl"] += _say(k.get("pnl_usd")) or 0.0
        s["ucret"] += _say(k.get("ucret")) or 0.0
        s["n"] += 1
    for g in out.values():
        for s in g.values():
            s["net"] = s["pnl"] - s["ucret"]
    return out


def kadro_formlari(kadro: dict) -> tuple[dict[str, float], int, int]:
    """kadro.json -> ({adres: form} tüm satırlar (ilk11 + yedek), ilk11 sayısı, yedek sayısı). Sahadaki üye bugünkü ilk11'de olmayabilir (saha haftalık); formu yine kadro satırından okunur."""
    form, ilk, yedek = {}, 0, 0
    for s in kadro.get("satirlar") or []:
        f = _say(s.get("form"))
        if f is None or not s.get("adres"):
            continue
        form[str(s["adres"]).lower()] = f
        if s.get("katman") == "ilk11":
            ilk += 1
        elif s.get("katman") == "yedek":
            yedek += 1
    return form, ilk, yedek


def hesapla(pnl_gun: dict, form_gecmis: dict, r: int = R) -> dict:
    """Saf: günlük Spearman + toplu. `form_gecmis`: gün -> {"form": {adres: form}, "ilk11_n": int, "yedek_n": int} (gün yoksa en yakın önceki kadro)."""
    gunler, kullan = [], []
    kadro_gunleri = sorted(form_gecmis)
    for g in sorted(pnl_gun):
        onceki = [k for k in kadro_gunleri if k <= g]
        if not onceki:
            continue
        kg = onceki[-1]
        ilk = (form_gecmis[kg] or {}).get("form") or {}
        adresler = sorted(a for a in pnl_gun[g] if a in ilk)
        satir = {"gun": g, "kadro_gunu": kg, "ilk11_n": (form_gecmis[kg] or {}).get("ilk11_n"), "kadro_n": len(ilk), "kopyalanan_n": len(adresler), "yedek_n": (form_gecmis[kg] or {}).get("yedek_n")}
        if len(adresler) < MIN_TRADER:
            gunler.append({**satir, "durum": "az_trader"})
            continue
        form = [float(ilk[a]) for a in adresler]
        net = [pnl_gun[g][a]["net"] for a in adresler]
        t = gun_testi(form, net, int(g.replace("-", "")), r)
        if t["rho"] is None:
            gunler.append({**satir, "durum": "sabit"})
            continue
        satir.update({"durum": "tamam", "rho": round(t["rho"], 4), "p": round(t["p"], 4), "yontem": t["yontem"],
                      "toplam_net_pnl": round(sum(net), 2),
                      "traderlar": [{"takma_ad": takma_ad(a), "form": round(float(ilk[a]), 2), "islem": pnl_gun[g][a]["n"], "pnl": round(pnl_gun[g][a]["pnl"], 2),
                                     "ucret": round(pnl_gun[g][a]["ucret"], 2), "net_pnl": round(pnl_gun[g][a]["net"], 2)} for a in sorted(adresler, key=lambda a: -ilk[a])]})
        gunler.append(satir)
        kullan.append((form, net, g))
    return {"gunler": gunler, "toplu": _toplu(kullan, r)}


def _toplu(kullan: list[tuple[list[float], list[float], str]], r: int) -> dict:
    if not kullan:
        return {"durum": "yok", "gun_n": 0}
    rhos = [spearman(f, n) or 0.0 for f, n, _ in kullan]
    ort = sum(rhos) / len(rhos)
    rng = random.Random(sum(int(g.replace("-", "")) for _, _, g in kullan))
    kar = []
    for _ in range(r):
        top = 0.0
        for f, n, _g in kullan:
            p = n[:]
            rng.shuffle(p)
            top += spearman(f, p) or 0.0
        kar.append(top / len(kullan))
    p = sum(1 for k in kar if k >= ort - 1e-12) / len(kar)
    return {"durum": "tamam", "gun_n": len(kullan), "rho_ort": round(ort, 4), "p": round(p, 4), "r": r}


def olustur(kayitlar: list[dict], form_gecmis: dict, simdi_ms: int, r: int = R) -> dict:
    pg = gunluk_pnl(kayitlar)
    h = hesapla(pg, form_gecmis, r)
    notlar = ["Yalnız bilgi: seçim/eşik/limit değiştirmez.",
              "Değişken: gerçek kopya PnL'i yalnız sahadaki traderlar için var; 'rastgele 11' karşılaştırması yapılamaz (yedek için varsayımsal PnL yok). Bunun yerine form puanı sırası ile gerçek net PnL sırasının Spearman ilişkisi.",
              "rho > 0: yüksek form puanlı trader o gün daha çok kazandırmış. p tek yönlü permütasyon; küçük örneklem, günler bağımsız değil.",
              f"Kayıt penceresi: {len(pg)} gün; form geçmişi: {len(form_gecmis)} kadro günü; net = gerçekleşen K/Z - ücret."]
    return {"sema": SEMA, "proje": "CT", "uretim": datetime.fromtimestamp(simdi_ms / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "degisken": "form_sirasi_gercek_pnl_spearman",
            "pencere_gun": PENCERE_GUN, "gunler": h["gunler"], "toplu": h["toplu"], "notlar": notlar}


def markdown(v: dict) -> str:
    t = v["toplu"]
    out = [f"# CT kadro seçimi x gerçek kopya PnL (form sırası, {v['uretim']})", ""]
    if t.get("durum") == "tamam":
        out += [f"Toplu: {t['gun_n']} gün, ortalama rho = {t['rho_ort']:.3f}, p = {t['p']:.3f} (tek yönlü).", ""]
    else:
        out += ["Toplu: veri yok.", ""]
    out += ["| Gün | Kopyalanan / Kadro | rho | p | Net PnL $ | Durum |", "|---|---:|---:|---:|---:|---|"]
    for g in v["gunler"]:
        if g["durum"] == "tamam":
            out.append(f"| {g['gun']} | {g['kopyalanan_n']} / {g['kadro_n']} | {g['rho']:.3f} | {g['p']:.3f} | {g['toplam_net_pnl']:.2f} | tamam ({g['yontem']}) |")
        else:
            out.append(f"| {g['gun']} | {g['kopyalanan_n']} / {g['kadro_n']} | - | - | - | {g['durum']} |")
    out += ["", "Notlar:", ""] + [f"- {n}" for n in v["notlar"]]
    return "\n".join(out) + "\n"


def _yaz_atomik(yol: Path, metin: str) -> None:
    yol.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(yol.parent), prefix=".sg-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(metin)
        os.replace(tmp, yol)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def gecmis_oku(durum_dizin: Path) -> dict:
    try:
        v = json.loads((Path(durum_dizin) / GECMIS).read_text(encoding="utf-8"))
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


def kadro_kaydet(motor: Any, kadro: dict, simdi_ms: int) -> None:
    """Kadro okunduğunda günün kadro (ilk11 + yedek) form puanlarını `form_gecmis.json`a yazar (gün başına son okuma; 14 gün). Hata çağırana çıkar; çağıran yutar."""
    form, ilk, yedek = kadro_formlari(kadro)
    if not form:
        return
    g = gecmis_oku(motor.durum_dizin)
    g[_gun(simdi_ms)] = {"form": form, "ilk11_n": ilk, "yedek_n": yedek}
    for eski in sorted(g)[:-PENCERE_GUN]:
        del g[eski]
    _yaz_atomik(Path(motor.durum_dizin) / GECMIS, json.dumps(g, sort_keys=True))


def kayitlari_oku(dizin: Path, simdi_ms: int, gun: int = PENCERE_GUN) -> list[dict]:
    satirlar: list[dict] = []
    for i in range(gun + 1):
        try:
            with (Path(dizin) / f"{_gun(simdi_ms - i * _GUN_MS)}.jsonl").open(encoding="utf-8") as f:
                for s in f:
                    try:
                        o = json.loads(s)
                    except ValueError:
                        continue
                    if isinstance(o, dict) and o.get("olay") == "emir":
                        satirlar.append(o)
        except OSError:
            continue
    return satirlar


def yaz(motor: Any) -> None:
    """`paylasim/secim_gercek_v1.json` ve `.md` yazar (hata çağırana çıkar; çağıran yutar)."""
    simdi = int(motor.saat_ms())
    veri = olustur(kayitlari_oku(Path(motor.kayit.dizin), simdi), gecmis_oku(motor.durum_dizin), simdi)
    d = Path(motor.durum_dizin) / "paylasim"
    _yaz_atomik(d / DOSYA_JSON, json.dumps(veri, ensure_ascii=False, indent=1))
    _yaz_atomik(d / DOSYA_MD, markdown(veri))
