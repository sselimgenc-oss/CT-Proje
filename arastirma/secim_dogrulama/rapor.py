"""Aşama 6: kollar × T tabloları, 1.000 rastgele çekiliş, üç geçme şartı, bugünkü aday havuzu, RAPOR.md + CSV/JSON."""
from __future__ import annotations

import csv
import json
import statistics
import os
import sys
import zlib
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, os.environ.get("WF_REPO") or str(Path(__file__).resolve().parents[2]))
from copytrade import boyut  # noqa: E402
from copytrade.kurallar import load_rules  # noqa: E402

import hl  # noqa: E402

CEKILIS = 1000
RULES = load_rules()
KASA = float(RULES["canli_kasa_usd"])
SLOT = boyut.slot_usd(KASA, RULES)
OLCEK = KASA / SLOT                     # kasa getirisi → slot getirisi
KOLLAR = {
    "A": {"ad": "A — spec kuralları (hesap ≥ 50k)", "havuz": "k50", "aday": lambda r: r["r1_A"] and r["r2"], "sira": True},
    "B": {"ad": "B — A + iki veto", "havuz": "k50", "aday": lambda r: r["r1_A"] and r["r2"], "sira": True},
    "C": {"ad": "C — yalnız kopyalanabilirlik kapıları (3–7) + vetolar, sıralama yok", "havuz": "k50", "aday": lambda r: r["ornek50"] and r["k50"], "sira": False},
    "D": {"ad": "D — A, hesap ≥ 10k (bugünkü canlı eşik)", "havuz": "k10", "aday": lambda r: r["r1_D"] and r["r2"], "sira": True},
}


def tarih(ms: int) -> str:
    return datetime.fromtimestamp(int(ms) / 1000, UTC).strftime("%Y-%m-%d")


def yuz(x, n=1) -> str:
    return "—" if x is None else f"{x * 100:+.{n}f}%"


def havuzda(r: dict, h: str) -> bool:
    return bool(r.get("ornek50") and r.get("k50")) if h == "k50" else bool(r.get("ornek10") and r.get("k10"))


def yukle(adresler: list[str], uc: str) -> dict[str, dict]:
    out = {}
    for a in adresler:
        d = hl.oku(uc, a)
        if d:
            out[a] = d["T"]
    return out


def tohum(*x) -> int:
    return zlib.crc32("|".join(map(str, x)).encode())


def t_tablosu(kol: str, T: int, veri: dict, t12: dict | None = None) -> dict:
    k = KOLLAR[kol]
    sec, hav, cik_s, cik_h, sec_satir = [], [], 0, 0, []
    for a, Ts in veri.items():
        r = Ts.get(str(T))
        if not r or not r.get("ilgili"):
            continue
        if t12 is not None:                          # T12: ileri ölçüm ayrı dosyada
            r = {**r, "ileri": ((t12.get(a) or {}).get(str(T)) or {}).get("ileri")}
        aday, hv = k["aday"](r), havuzda(r, k["havuz"])
        if r.get("cikarildi"):
            cik_s += bool(aday)
            cik_h += bool(hv)
            continue
        il = r.get("ileri")
        if (r.get("kol") or {}).get(kol) and il:
            g = il["getiri"] * OLCEK
            sec.append(g)
            sec_satir.append({"adres": a, "t": r.get("t"), "getiri": g, "dusus": il["dusus"] * OLCEK, "hesap": r.get("hesap"), "veto": r.get("veto")})
        if hv and il:
            hav.append(il["getiri"] * OLCEK)
    out = {"T": T, "tarih": tarih(T), "secilen_n": len(sec), "kontrol_n": len(hav), "cikarilan_secim_adayi": cik_s, "cikarilan_kontrol": cik_h,
           "secilen_ortanca": statistics.median(sec) if sec else None, "kontrol_ortanca": statistics.median(hav) if hav else None,
           "en_buyuk_dusus": max((s["dusus"] for s in sec_satir), default=None), "dusus_ortanca": statistics.median([s["dusus"] for s in sec_satir]) if sec_satir else None,
           "_sec": sec, "_hav": hav, "_satir": sec_satir}
    out["cekilis"] = None
    if sec and hav:
        rng = np.random.default_rng(tohum(kol, T))
        h = np.asarray(hav)
        yerine = len(sec) > len(h)
        if yerine:
            idx = rng.integers(0, len(h), size=(CEKILIS, len(sec)))
        else:
            idx = np.argsort(rng.random((CEKILIS, len(h))), axis=1)[:, :len(sec)]
        med = np.median(h[idx], axis=1)
        s = out["secilen_ortanca"]
        out["cekilis"] = med.tolist()
        out["yuzdelik"] = float(np.mean(med < s) + 0.5 * np.mean(med == s))
        out["cekilis_yerine_koyarak"] = yerine
    else:
        out["yuzdelik"] = None
    if k["sira"] and sec_satir:
        ilk5 = sorted(sec_satir, key=lambda s: (s["t"] is None, -(s["t"] or 0), s["adres"]))[:5]
        out["ilk5"] = ilk5
        out["ilk5_ortanca"] = statistics.median([s["getiri"] for s in ilk5])
        if hav:
            rng = np.random.default_rng(tohum(kol, T, "ilk5"))
            h = np.asarray(hav)
            n5 = len(ilk5)
            idx = rng.integers(0, len(h), size=(CEKILIS, n5)) if n5 > len(h) else np.argsort(rng.random((CEKILIS, len(h))), axis=1)[:, :n5]
            m5 = np.median(h[idx], axis=1)
            out["ilk5_yuzdelik"] = float(np.mean(m5 < out["ilk5_ortanca"]) + 0.5 * np.mean(m5 == out["ilk5_ortanca"]))
    return out


def sartlar(tablolar: list[dict], son: bool) -> dict:
    dolu = [t for t in tablolar if t["secilen_n"] > 0 and t["cekilis"] is not None]
    s1 = None
    if dolu:
        S = statistics.fmean(t["secilen_ortanca"] for t in dolu)
        null = np.mean(np.asarray([t["cekilis"] for t in dolu]), axis=0)
        s1 = float(np.mean(null < S) + 0.5 * np.mean(null == S))
    iyi = sum(1 for t in tablolar if t["secilen_ortanca"] is not None and t["kontrol_ortanca"] is not None and t["secilen_ortanca"] > t["kontrol_ortanca"])
    havuz = [g for t in tablolar for g in t["_sec"]]
    s3 = statistics.median(havuz) if havuz else None
    gerek2 = 9 if son else 8
    return {"s1_yuzdelik": s1, "s1": s1 is not None and s1 >= 0.90, "s2_iyi": iyi, "s2_tarih": len(tablolar), "s2_gerek": gerek2, "s2": iyi >= gerek2,
            "s3_ortanca": s3, "s3": s3 is not None and s3 > 0, "gecti": bool(s1 is not None and s1 >= 0.90 and iyi >= gerek2 and s3 is not None and s3 > 0),
            "dolu_tarih": len(dolu), "secilen_toplam": len(havuz)}


def bugun_havuzu(kol: str, veri: dict, simdi: int) -> list[dict]:
    out = []
    for a, Ts in veri.items():
        r = Ts.get(str(simdi))
        if r and (r.get("kol") or {}).get(kol):
            out.append({"adres": a, "hesap": r.get("hesap"), "t": r.get("t"), "kopya28_slot": None if r.get("kopya28") is None else r["kopya28"] * OLCEK,
                        "islem28": r.get("islem28"), "islem56": r.get("islem56"), "devir": r.get("devir"), "tutma_dk": None if r.get("tutma_saat") is None else r["tutma_saat"] * 60,
                        "kaldirac": r.get("kaldirac"), "veto": r.get("veto")})
    return sorted(out, key=lambda s: (s["t"] is None, -(s["t"] or 0)))


def uret(klasor: Path, ayar: dict, ornek: dict, adresler: list[str], boy: dict, tur: str = "tur1", t12_kollar: list[str] | None = None,
         uc: str = "olcum", tarihler: list[int] | None = None, cikti_ad: str = "RAPOR.md") -> list[str]:
    """Raporu yazar. Döner: birinci turu geçen (T12'si açılacak) kollar (yalnız tur1'de)."""
    tarihler = tarihler or ayar["tarihler"]
    veri = yukle(adresler, uc)
    t12 = yukle(adresler, "olcum_t12") if tur == "son" else None
    ac_t = tarihler[:-1] if len(tarihler) == 12 else tarihler
    sonuc, acilacak = {}, []
    for kol in KOLLAR:
        tab = [t_tablosu(kol, T, veri) for T in ac_t]
        acik = tur == "son" and kol in (t12_kollar or []) and len(tarihler) == 12
        if acik:
            tab.append(t_tablosu(kol, tarihler[11], veri, t12=t12))
        s1 = sartlar(tab[:len(ac_t)], son=False)
        s_son = sartlar(tab, son=True) if acik else None
        if tur == "tur1" and s1["gecti"]:
            acilacak.append(kol)
        sonuc[kol] = {"tablo": tab, "tur1": s1, "son": s_son, "t12_acik": acik, "bugun": bugun_havuzu(kol, veri, ayar["simdi"])}
        if kol == "D":                                  # ikincil: D'nin seçilenleri ≥ 50k kontrol havuzuna karşı
            KOLLAR["D2"] = {**KOLLAR["D"], "havuz": "k50", "ad": "D (ikincil) — 50k kontrol havuzuna karşı"}
            tab2 = [t_tablosu("D2", T, {a: {k: ({**v, "kol": {**(v.get("kol") or {}), "D2": (v.get("kol") or {}).get("D")}} if isinstance(v, dict) else v)
                                            for k, v in Ts.items()} for a, Ts in veri.items()}) for T in ac_t]
            sonuc["D2"] = {"tablo": tab2, "tur1": sartlar(tab2, son=False), "son": None, "t12_acik": False, "bugun": []}
            del KOLLAR["D2"]
    yaz(klasor, ayar, ornek, boy, sonuc, tur, veri, tarihler, cikti_ad)
    return acilacak


# ------------------------------------------------------------------------------------------------ yazım
def yaz(klasor: Path, ayar: dict, ornek: dict, boy: dict, sonuc: dict, tur: str, veri: dict, tarihler: list[int], cikti_ad: str) -> None:
    on = "" if cikti_ad == "RAPOR.md" else Path(cikti_ad).stem + "_"
    # ham CSV (adres × T)
    with (klasor / f"{on}ham_sonuclar.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        alan = ["adres", "T", "hesap", "t", "r1_A", "r1_D", "r2", "k50", "k10", "ornek50", "ornek10", "cikarildi", "neden", "veto", "devir", "tutma_saat", "kaldirac",
                "aktif_coin", "likit_pay", "islem56", "islem28", "atlanan_pay", "kopya28_slot", "koruma", "kol_A", "kol_B", "kol_C", "kol_D", "ileri_getiri_slot", "ileri_dusus_slot"]
        w.writerow(alan)
        for a, Ts in sorted(veri.items()):
            for T, r in sorted(Ts.items()):
                if not r.get("ilgili"):
                    continue
                il = r.get("ileri") or {}
                kol = r.get("kol") or {}
                w.writerow([a, tarih(int(T)) if int(T) != ayar["simdi"] else "bugun", r.get("hesap"), r.get("t"), r.get("r1_A"), r.get("r1_D"), r.get("r2"), r.get("k50"), r.get("k10"),
                            r.get("ornek50"), r.get("ornek10"), r.get("cikarildi"), r.get("neden"), r.get("veto"), r.get("devir"), r.get("tutma_saat"), r.get("kaldirac"),
                            r.get("aktif_coin"), r.get("likit_pay"), r.get("islem56"), r.get("islem28"), r.get("atlanan_pay"),
                            None if r.get("kopya28") is None else r["kopya28"] * OLCEK, r.get("koruma"), kol.get("A"), kol.get("B"), kol.get("C"), kol.get("D"),
                            None if not il else il["getiri"] * OLCEK, None if not il else il["dusus"] * OLCEK])
    # özet JSON (çekiliş dizileri hariç)
    temiz = {k: {**v, "tablo": [{kk: vv for kk, vv in t.items() if not kk.startswith("_") and kk != "cekilis"} for t in v["tablo"]]} for k, v in sonuc.items()}
    (klasor / f"{on}ozet_{tur}.json").write_text(json.dumps({"tur": tur, "boyutlar": boy, "slot_usd": SLOT, "kollar": temiz}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    for k in KOLLAR:
        with (klasor / f"{on}bugun_havuzu_{k}.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["adres", "hesap_usd", "t", "kopya28_slot_getiri", "kopya_islem_28g", "kopya_islem_56g", "devir_hafta", "tutma_dk", "kaldirac", "veto"])
            for s in sonuc[k]["bugun"]:
                w.writerow([s["adres"], s["hesap"], s["t"], s["kopya28_slot"], s["islem28"], s["islem56"], s["devir"], s["tutma_dk"], s["kaldirac"], s["veto"]])
    (klasor / cikti_ad).write_text(md(ayar, ornek, boy, sonuc, tur, tarihler), encoding="utf-8")


def hukum_satiri(k: str, v: dict) -> str:
    s = v["son"] or v["tur1"]
    durum = ("GEÇTİ (seçim değer katıyor)" if s["gecti"] else "GEÇMEDİ") if v["son"] else (
        "1. tur geçti → T12 açılacak" if v["tur1"]["gecti"] else "1. tur GEÇMEDİ (T12 kilitli; tek revizyon hakkı kullanıcıda)")
    return (f"{k}: {durum} — şart1 yüzdelik {yuz(s['s1_yuzdelik'], 0) if s['s1_yuzdelik'] is not None else '—'} (≥%90), "
            f"şart2 {s['s2_iyi']}/{s['s2_tarih']} (≥{s['s2_gerek']}), şart3 ortanca {yuz(s['s3_ortanca'])} (> 0)")


def md(ayar, ornek, boy, sonuc, tur, tarihler) -> str:
    L = []
    a = sonuc["A"]
    asil = a["son"] or a["tur1"]
    L.append("# Trader seçimi örneklem dışı doğrulama (walk-forward) — RAPOR")
    L.append("")
    L.append("**Özet (teknik olmayan okuyucu için):**")
    hk = ("GEÇTİ — seçim kuralları rastgele seçime göre değer katıyor" if (a["son"] and asil["gecti"]) else
          ("GEÇMEDİ — seçim kuralları rastgele seçimden anlamlı biçimde iyi değil" if a["son"] else
           ("Birinci tur geçti; kilitli son tarih (T12) açılınca kesinleşir" if a["tur1"]["gecti"] else "Birinci turda GEÇMEDİ (kurallar şu haliyle değer katmıyor; tek revizyon hakkı kullanıcıda)")))
    L.append(f"1. Ana hüküm (A kolu, spec kuralları): **{hk}**.")
    L.append(f"2. Şart 1 (seçilenlerin ortanca getirisi rastgele çekilişlerin %90'ından iyi mi): {yuz(asil['s1_yuzdelik'], 0) if asil['s1_yuzdelik'] is not None else '—'} → {'evet' if asil['s1'] else 'hayır'}.")
    L.append(f"3. Şart 2 (tarihlerin en az {asil['s2_gerek']}/{asil['s2_tarih']}'inde kontrolden iyi): {asil['s2_iyi']} → {'evet' if asil['s2'] else 'hayır'}.")
    L.append(f"4. Şart 3 (maliyet sonrası ortanca getiri > 0): {yuz(asil['s3_ortanca'])} → {'evet' if asil['s3'] else 'hayır'} (getiri = 4 haftada 200 $ slota göre).")
    for i, k in enumerate(("B", "C", "D"), 5):
        L.append(f"{i}. {hukum_satiri(k, sonuc[k])}.")
    L.append(f"8. Bugünkü aday havuzu: A {len(sonuc['A']['bugun'])}, B {len(sonuc['B']['bugun'])}, C {len(sonuc['C']['bugun'])} (yalnız örneklemden), D {len(sonuc['D']['bugun'])} kişi.")
    L.append("9. Mutlak getiriler hayatta kalma yanlılığı yüzünden şişkin olabilir; yalnız seçilen − kontrol farkı yorumlanmalı.")
    bag = (tarihler[-1] - tarihler[0]) / (28 * 24 * 3_600_000) + 1
    L.append(f"10. 4 haftalık pencereler örtüştüğü için {len(tarihler)} tarih ≈ {bag:.1f} bağımsız dönemdir; sonuç istatistiksel olarak zayıf kanıttır.")
    L.append("")
    L.append(f"_Tur: {tur}. Çapa (şimdi): {datetime.fromtimestamp(ayar['simdi'] / 1000, UTC):%Y-%m-%d %H:%M} UTC. Slot {SLOT:.0f} $; getiri ve düşüşler slot oranıdır._")
    L.append("")
    L.append("## Boyutlar")
    for k, v in boy.items():
        L.append(f"- {k}: {v}")
    L.append("")
    for k, v in sonuc.items():
        ad = KOLLAR[k]["ad"] if k in KOLLAR else "D (ikincil) — D seçilenleri 50k kontrol havuzuna karşı"
        L.append(f"## Kol {ad}")
        L.append("")
        L.append(f"- Tur 1 (T1–T11): {json.dumps({x: v['tur1'][x] for x in ('s1_yuzdelik', 's2_iyi', 's2_gerek', 's3_ortanca', 'gecti')}, default=str)}")
        if v["son"]:
            L.append(f"- Son (T12 açık, T1–T12): {json.dumps({x: v['son'][x] for x in ('s1_yuzdelik', 's2_iyi', 's2_gerek', 's3_ortanca', 'gecti')}, default=str)}")
        elif k in ("A", "B", "C", "D"):
            L.append("- T12: kilitli" + (" (1. tur geçmedi: revizyon kullanıcı kararı; `python calistir.py --t12-ac " + k + "` ile mevcut kurallarla açılır)" if not v["tur1"]["gecti"] else ""))
        L.append("")
        L.append("| T | tarih | seçilen | kontrol | çıkarılan (aday/kontrol) | seçilen ortanca | kontrol ortanca | yüzdelik sıra | en büyük düşüş | ilk 5 ortanca (yüzdelik) |")
        L.append("|---|---|---|---|---|---|---|---|---|---|")
        for i, t in enumerate(v["tablo"], 1):
            i5 = "—" if "ilk5_ortanca" not in t else f"{yuz(t['ilk5_ortanca'])} ({'—' if t.get('ilk5_yuzdelik') is None else f'{t['ilk5_yuzdelik'] * 100:.0f}'})"
            L.append(f"| T{i} | {t['tarih']} | {t['secilen_n']} | {t['kontrol_n']} | {t['cikarilan_secim_adayi']}/{t['cikarilan_kontrol']} | {yuz(t['secilen_ortanca'])} | "
                     f"{yuz(t['kontrol_ortanca'])} | {'—' if t['yuzdelik'] is None else f'{t['yuzdelik'] * 100:.0f}'} | {yuz(t['en_buyuk_dusus'])} | {i5} |")
        L.append("")
        if KOLLAR.get(k, {}).get("sira"):
            L.append("<details><summary>İlk 5 (t-istatistiği sırası) — her T</summary>")
            L.append("")
            for i, t in enumerate(v["tablo"], 1):
                if t.get("ilk5"):
                    L.append(f"- T{i} {t['tarih']}: " + "; ".join(f"{s['adres'][:10]}… t={s['t']:.2f} getiri {yuz(s['getiri'])} düşüş {yuz(s['dusus'])}" if s["t"] is not None
                                                            else f"{s['adres'][:10]}… getiri {yuz(s['getiri'])}" for s in t["ilk5"]))
            L.append("")
            L.append("</details>")
            L.append("")
        if v["bugun"]:
            L.append(f"**Bugünkü aday havuzu ({k}, {len(v['bugun'])} kişi)**" + (" — yalnız rastgele örneklemden (C tam evrende ölçülmedi)" if k == "C" else ""))
            L.append("")
            L.append("| adres | hesap $ | t | kopya getirisi 28g (slot) | kopya işlem 28g / 56g | devir (x/hafta) | tutma (dk) | kaldıraç | veto |")
            L.append("|---|---|---|---|---|---|---|---|---|")
            for s in v["bugun"][:60]:
                L.append(f"| {s['adres']} | {s['hesap']:,.0f} | {'—' if s['t'] is None else f'{s['t']:.2f}'} | {yuz(s['kopya28_slot'])} | {s['islem28']} / {s['islem56']} | "
                         f"{'—' if s['devir'] is None else f'{s['devir']:.1f}'} | {'—' if s['tutma_dk'] is None else f'{s['tutma_dk']:.0f}'} | "
                         f"{'—' if s['kaldirac'] is None else f'{s['kaldirac']:.2f}'} | {s['veto'] or '-'} |")
            L.append("")
    L += ["## Yanlılıklar ve sınırlamalar", "",
          "- **Hayatta kalma:** aday evreni bugünkü lider tablosundan kuruldu. Azaltmak için bugün < 10k olup ömür boyu ≥ 10k $ zarar etmiş ya da ≥ 50M $ hacimli hesaplar da evrene alındı; "
          "para çekip küçülmüş ya da lider tablosundan tamamen düşmüş hesaplar yine eksik. İki grup aynı evrenden geldiği için yalnız göreli fark yorumlanır; mutlak getiriler şişkin olabilir.",
          "- **Dolum geçmişi:** adres başına en çok 10.000 dolum çekildi (en yeni kısım); geçmişi T − 56 g'ye yetmeyen hesaplar o T'de İKİ gruptan da çıkarıldı (tablolarda 'çıkarılan').",
          "- **Bağımsız dönem:** haftalık kaydırmalı 12 tarih × 4 haftalık ileri pencere örtüşür; etkin bağımsız dönem ≈ 3–4.",
          "- **Kopya yaklaşımı:** eski haftalar için 1 dk mum yok; kopya trader'ın dolum fiyatıyla (gecikmesiz) + tam maliyet (taker %0,045 + kayma %0,05) + saatlik funding; "
          "işaret ve tasfiye denetimi saatlik mumdan (kalicilik_testi yaklaşımı). Mutlak seviye gerçek gecikmeli kopyadan biraz iyimser; iki gruba aynı uygulanır.",
          "- **Portfolio çözünürlüğü:** eski tarihlerde perp pnl/hesap serisi allTime'dan gelir (seyrek noktalar; T'den önceki son nokta kullanılır). K-65 'motor tanımı' payda düzeltmesi geçmişe uygulanamaz.",
          "- **Azami kaldıraç (HL coin sınırı)** bugünkü meta değeridir; likidite her pencerenin saatlik mum hacminden (≥ 1M $/gün) ölçülür. HIP-3 coinleri kopyada atlanır (K-43), likidite kuralında sayılır.",
          f"- **Kontrol örneklemi:** kontrol havuzu, herhangi bir T'de kontrol tanımına uyan hesaplardan sabit tohumla rastgele {len(ornek['s50'])} (50k) + {len(ornek['s10'])} (10k, yalnız D) "
          "adresten oluşur; her T'de bunların o T'de tanıma uyanları. C kolu yalnız bu örneklem üzerinde ölçülür.",
          "",
          "## Sonraki adım (yalnız öneri)", "",
          "- Geçerse canlı başlangıç boyutu kullanıcı kararıdır: (a) 2 × 200 $ ile başla, 4 hafta uyumluysa 5 slota çık (düşük risk, yavaş kanıt); "
          "(b) doğrudan 5 × 200 $ (daha hızlı istatistik, 2,5 kat risk); (c) 3 × 200 $ ara yol. Geçmezse canlıya seçim kuralına güvenerek çıkılmamalı.",
          "- Lider tablosunun **haftalık kaydı** bugünden başlatılmalı: haftada bir `stats-data.hyperliquid.xyz/Mainnet/leaderboard` tam yanıtı tarihli gzip olarak (ör. veri dalında `lider/YYYY-MM-DD.json.gz`) "
          "saklanır; ileride evren o tarihteki tablodan kurulur ve batmış hesaplar da görünür.", ""]
    return "\n".join(L) + "\n"
