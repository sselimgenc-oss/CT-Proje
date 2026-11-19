"""Sürüm karşılaştırma (yalnız RAPOR; AGENTS kural 6: eski ↔ yeni yan yana): canlı motor kaydından (`kayit/<gün>.jsonl`) kapanan kopya işlemlerini sürüme (kadro `radar_surum`)
ve filtre durumuna göre günlük K/Z serisine ayırır.

- **v4+ML (fiili)** = gerçekleşen net K/Z: `emir` olayı, `reduce_only`, `pnl_usd` dolu, `durum` dolu/kismi; net = pnl_usd − ucret (pano `_kapanan_html` ile aynı tanım). UTC gün.
- **v4 taban (ML/ders yokmuş gibi)** = fiili + ML/ders yüzünden atlanan sinyallerin hayali K/Z'si: `emir_yok` nedeni `ml_filtre_atla` / `ders_emekli` olup `_karsi_olgu_ac` ile açılan hayali
  pozisyonun `karsi_olgu_kapandi` olayındaki `pnl_usd` (kapanış günü). Hayali K/Z ücret/kayma İÇERMEZ (motorun karşı-olgu kaydı böyle) → taban bu kadar iyimserdir.
- **Sürüm** = olay günündeki kadronun `radar_surum`'u (`surum_gun`: {YYYY-MM-DD: sürüm}; motor K-39 ile günün ilk kadrosunu uygular → `kadro_ilk.json`). Olayda `surum` alanı varsa o geçerli;
  hiçbiri yoksa "?".

Not (yazım anı): motor kodunda `ml_filtre_atla` / `ders_emekli` nedenleri HENÜZ yok; bunlar gelene dek iki seri birebir aynıdır (hayali bileşen 0) ve rapor bunu açıkça söyler.
Birimler: $ = motorun sanal kasası ölçeği (`canli_kasa_usd`).
"""
from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from html import escape as esc

ML_NEDEN = "ml_filtre_atla"
DERS_NEDEN = "ders_emekli"
FILTRE_NEDENLERI = {ML_NEDEN: "ml_hayali", DERS_NEDEN: "ders_hayali"}
ALANLAR = ("gercek", "ml_hayali", "ders_hayali", "kapanis", "atlanan")


def _gun(ms: float) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).date().isoformat()


def _surum(olay: dict, gun: str, surum_gun: dict[str, str]) -> str:
    return str(olay.get("surum") or olay.get("kadro_surumu") or surum_gun.get(gun) or "?")


def gunluk_seri(kayitlar: list[dict], surum_gun: dict[str, str] | None = None) -> dict[str, dict[str, dict[str, float]]]:
    """{sürüm: {gün: {gercek, ml_hayali, ders_hayali, kapanis, atlanan}}}. `atlanan` = ML/ders nedeniyle atlanan sinyal sayısı (emir_yok). Saf; ağ yok."""
    surum_gun = surum_gun or {}
    cikti: dict[str, dict[str, dict[str, float]]] = {}

    def hucre(olay: dict) -> dict[str, float]:
        g = _gun(float(olay["zaman_ms"]))
        return cikti.setdefault(_surum(olay, g, surum_gun), {}).setdefault(g, dict.fromkeys(ALANLAR, 0.0))

    for o in kayitlar:
        if not isinstance(o.get("zaman_ms"), int | float):
            continue
        ad = o.get("olay")
        if ad == "emir" and o.get("reduce_only") and o.get("pnl_usd") is not None and o.get("durum") in ("dolu", "kismi"):
            h = hucre(o)
            h["gercek"] += float(o["pnl_usd"]) - float(o.get("ucret") or 0.0)
            h["kapanis"] += 1
        elif ad == "karsi_olgu_kapandi" and o.get("neden") in FILTRE_NEDENLERI:
            hucre(o)[FILTRE_NEDENLERI[o["neden"]]] += float(o.get("pnl_usd") or 0.0)
        elif ad == "emir_yok" and o.get("neden") in FILTRE_NEDENLERI:
            hucre(o)["atlanan"] += 1
    return cikti


def karsilastir(kayitlar: list[dict], surum_gun: dict[str, str] | None = None) -> dict:
    """Sürüm başına günlük seri + toplam. `gunler` satırı: {gun, v4_ml (fiili), v4_taban (fiili + hayali ML + hayali ders), ml_hayali, ders_hayali, kapanis, atlanan}.
    `filtre_var`: dönemde ML/ders nedeniyle atlanan sinyal ya da hayali K/Z kaydı var mı (yoksa seriler aynıdır)."""
    seri = gunluk_seri(kayitlar, surum_gun)
    surumler: dict[str, dict] = {}
    filtre_var = False
    for sv, gunler in sorted(seri.items()):
        satirlar = []
        for g, h in sorted(gunler.items()):
            satirlar.append({"gun": g, "v4_ml": h["gercek"], "v4_taban": h["gercek"] + h["ml_hayali"] + h["ders_hayali"], "ml_hayali": h["ml_hayali"], "ders_hayali": h["ders_hayali"],
                             "kapanis": int(h["kapanis"]), "atlanan": int(h["atlanan"])})
            filtre_var = filtre_var or bool(h["atlanan"] or h["ml_hayali"] or h["ders_hayali"])
        toplam = {k: (sum(s[k] for s in satirlar) if k not in ("kapanis", "atlanan") else int(sum(s[k] for s in satirlar))) for k in ("v4_ml", "v4_taban", "ml_hayali", "ders_hayali", "kapanis", "atlanan")}
        surumler[sv] = {"gunler": satirlar, "toplam": toplam}
    return {"surumler": surumler, "filtre_var": filtre_var}


def _usd(v: float) -> str:
    return f"{v:+.2f} $"


def md_bolum(k: dict, son_gun: int = 7) -> list[str]:
    """pano `OZET.md` bölümü: sürüm başına son `son_gun` gün + dönem toplamı (v4+ML fiili ↔ v4 taban)."""
    s = ["## Sürüm karşılaştırma (v4 taban ↔ v4+ML fiili; yalnız rapor)", ""]
    if not k["surumler"]:
        return s + ["kapanan işlem kaydı yok", ""]
    if not k["filtre_var"]:
        s += ["_ML filtresi / ders emekliliği henüz sinyal atlamadı (ya da motorda yok): iki seri aynı; ayrışma bu nedenler kaydedilince başlar._", ""]
    for sv, d in k["surumler"].items():
        t = d["toplam"]
        s += [f"**{sv}** · dönem: fiili {_usd(t['v4_ml'])} · taban {_usd(t['v4_taban'])} (ML hayali {_usd(t['ml_hayali'])}, ders hayali {_usd(t['ders_hayali'])}) · kapanış {t['kapanis']} · atlanan {t['atlanan']}", "",
              "| gün (UTC) | v4+ML fiili | v4 taban | kapanış | atlanan |", "|---|---|---|---|---|"]
        s += [f"| {g['gun']} | {_usd(g['v4_ml'])} | {_usd(g['v4_taban'])} | {g['kapanis']} | {g['atlanan']} |" for g in d["gunler"][-son_gun:]]
        s.append("")
    s += ["_Taban = fiili + ML/ders yüzünden atlanan sinyallerin hayali K/Z'si (ücret/kayma içermez, iyimser). Net = gerçekleşen − ücret._", ""]
    return s


def html_tablo(k: dict, son_gun: int = 5) -> str:
    """Pano küçük tablo (sürüm başına son günler + toplam)."""
    if not k["surumler"]:
        return '<div class="bos">Kapanan işlem kaydı henüz yok</div>'
    satir = ""
    for sv, d in k["surumler"].items():
        for g in d["gunler"][-son_gun:]:
            satir += f'<tr><td>{esc(sv)} {esc(g["gun"][5:])}</td><td class="sg">{esc(_usd(g["v4_ml"]))}</td><td class="sg">{esc(_usd(g["v4_taban"]))}</td></tr>'
        t = d["toplam"]
        satir += f'<tr class="alt"><td>{esc(sv)} toplam</td><td class="sg">{esc(_usd(t["v4_ml"]))}</td><td class="sg">{esc(_usd(t["v4_taban"]))}</td></tr>'
    not_ = "" if k["filtre_var"] else " ML/ders henüz sinyal atlamadı: seriler aynı."
    return (f'<div class="tw"><table><tr><th>SÜRÜM / GÜN</th><th class="sg">V4+ML (FİİLİ)</th><th class="sg">V4 TABAN</th></tr>{satir}</table></div>'
            f'<div class="ha" style="padding:6px 11px">Taban = fiili + ML/ders yüzünden atlananların hayali K/Z\'si (iyimser; ücret yok).{not_}</div>')


def surum_gun_oku(dal: str | None, gunler: list[str]) -> dict[str, str]:
    """Veri dalından günün ilk kadrosunun (yoksa güncel kadro) `radar_surum`'u: {gün: sürüm}; okunamayan gün dışarıda kalır (→ "?")."""
    cikti: dict[str, str] = {}
    if not dal:
        return cikti
    for g in gunler:
        for ad in ("kadro_ilk.json", "kadro.json"):
            s = subprocess.run(["git", "show", f"origin/{dal}:radar/{g}/{ad}"], capture_output=True, text=True, check=False)
            if s.returncode == 0 and s.stdout.strip():
                try:
                    v = json.loads(s.stdout).get("radar_surum")
                except json.JSONDecodeError:
                    v = None
                if v is not None:
                    cikti[g] = str(v)
                    break
    return cikti
