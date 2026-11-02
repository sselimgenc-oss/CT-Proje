"""İlk 11 Pazar işi: ilk seçim ya da haftalık form + 60/40 geçiş planı + izleme listesi (docs/ILK11_SECIM_SARTNAME.md §2, §4, §5.3–5.4, §5.7).

Yalnız DOSYA üretir (ağ yok, emir yok); commit / push iş akışındadır. Hesap tek yerdedir (kural 7): ham alanlar `ilk11_alanlar`, puan / dağıtım /
terfi kapısı / 60/40 `ilk11`, zamanlama `pazar_akis`, snapshot `ilk11_veri` — bu modül yalnız girdi seçer, birleştirir ve yazar.

Girdiler (veri dalı çıkışları, iş akışı klasör olarak getirir):
- ``--kapi-dali``: ``copytrade-kapi`` checkout'u (``copytrade/kapi/<tarih>/{sonuc.csv,durum.json}``, önceki ``ilk11/<tarih>/``, ``son.json``).
- ``--izleme-dali``: ``copytrade-izleme`` checkout'u, TAM git geçmişiyle (``izleme/durum.json`` sürümü as_of'a göre seçilir); deneme için ``--durum-dosyasi``.
Çıktı (``--cikti``/``ilk11/<pazar-tarihi>/``): ``snapshot.json``, ``alanlar.csv``, ``plan.json``, ``akis.json``, ``RAPOR.md``; ayrıca ``ilk11/izleme_listesi.yaml``
ve ``son.json``'a ``ilk11`` anahtarı. Hata: yalnız ``RAPOR.md`` (+ ``alanlar.csv``) yazılır, snapshot yazılmaz, çıkış kodu 1 (önceki kadro sürer).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

import pandas as pd
import yaml

from copytrade import ilk11, ilk11_alanlar, secim
from copytrade.ilk11 import KALDIRAC_ALANLARI
from copytrade.ilk11_veri import snapshot_json, snapshot_olustur
from copytrade.izleme_motoru import load_list
from copytrade.kapi import HESAP_SURUMU
from copytrade.kurallar import RULES as KURALLAR_YOLU
from copytrade.kurallar import load_rules
from copytrade.pazar_akis import pazar_akis_plani

ISTANBUL = ZoneInfo("Europe/Istanbul")
KATMANLAR = ("izleme_adayi", "kopyalanabilir")
SEMA_ILK, SEMA_FORM = "ilk11-pazar-v1", "ilk11-form-v1"
GECICI_SEMA, GECICI_KIMLIK_ONEKI = "ilk11-acil-baslangic-leaderboard-only-v1", "1d92dd25"   # §5.7: geçici kadro önceki kadro SAYILMAZ
DURUM_YOLU = "izleme/durum.json"
GUN = timedelta(days=1)


class GirdiHatasi(RuntimeError):
    """Girdi seçilemedi / kalite kapısı tutmadı: snapshot yayımlanmaz, iş kırmızı biter (önceki kadro sürer)."""


# ---------------------------------------------------------------------------------------------------- zaman / dosya yardımcıları

def pazar_as_of(now: datetime) -> datetime:
    """Takvimden as_of: ``now``'dan önceki (dahil) en son Pazar 13:00 Europe/Istanbul. Cron gecikmesi sonucu değiştirmez (§5.1)."""
    if now.tzinfo is None:
        raise ValueError("now zaman dilimi içermeli")
    yerel = now.astimezone(ISTANBUL)
    adaydi = (yerel - timedelta(days=(yerel.weekday() - 6) % 7)).replace(hour=13, minute=0, second=0, microsecond=0)
    return adaydi - timedelta(days=7) if adaydi > yerel else adaydi


def pazar_as_of_tarih(tarih: str) -> datetime:
    return datetime.fromisoformat(tarih).replace(hour=13, tzinfo=ISTANBUL)


def sha256_dosya(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_metin(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _json(path: Path, varsayilan: Any = None) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else varsayilan


def _bos(value: Any) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def _bayrak(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "1.0"}


def _sayi(value: Any) -> float | None:
    return None if _bos(value) else ilk11_alanlar._sayi(value)


# ---------------------------------------------------------------------------------------------------- kapı girdisi ve uygunluk (§2)

def kapi_sec(kapi_dali: Path, as_of: datetime, rules: dict) -> dict[str, Any]:
    """as_of tarihinden önceki (dahil) EN YENİ uygun kapı klasörü: ``durum == "tamam"``, ``kapsam ≥ kapsam_hedefi``, ``hesap == HESAP_SURUMU``.
    Uygun klasör yoksa ``GirdiHatasi``. ``eski``: as_of tarihi − klasör tarihi > ``ilk11_kapi_tazelik_gun`` (karar çağıranda)."""
    kok, sebepler, gun = kapi_dali / "copytrade/kapi", [], as_of.date()
    klasorler = sorted((p for p in kok.glob("*") if p.is_dir() and _tarih_mi(p.name) and date.fromisoformat(p.name) <= gun), reverse=True) if kok.exists() else []
    for klasor in klasorler:
        durum = _json(klasor / "durum.json", {})
        if durum.get("durum") != "tamam":
            sebepler.append(f"{klasor.name}: durum={durum.get('durum')!r}")
        elif durum.get("kapsam") is None or float(durum["kapsam"]) < float(rules["kapsam_hedefi"]):
            sebepler.append(f"{klasor.name}: kapsam {durum.get('kapsam')} < {rules['kapsam_hedefi']}")
        elif durum.get("hesap") != HESAP_SURUMU:
            sebepler.append(f"{klasor.name}: hesap {durum.get('hesap')!r} != {HESAP_SURUMU!r}")
        elif not (klasor / "sonuc.csv").exists():
            sebepler.append(f"{klasor.name}: sonuc.csv yok")
        else:
            fark = (gun - date.fromisoformat(klasor.name)).days
            return {"tarih": klasor.name, "klasor": klasor, "durum": durum, "gun_farki": fark, "eski": fark > int(rules["ilk11_kapi_tazelik_gun"])}
    raise GirdiHatasi("uygun (tamam, kapsam hedefi, güncel hesap sürümü) kapı klasörü yok" + (": " + "; ".join(sebepler[:5]) if sebepler else ""))


def _tarih_mi(ad: str) -> bool:
    try:
        date.fromisoformat(ad)
        return True
    except ValueError:
        return False


def satir_uygunlugu(satir: Mapping[str, Any], as_of: datetime, rules: dict) -> tuple[bool, str | None]:
    """§2 madde 3–6 (klasör kapısı ve tazeliği ``kapi_sec``'te). Neden: katman_yok | hata | evren_disi | eski_satir."""
    if satir.get("katman") not in KATMANLAR:
        return False, "katman_yok"
    if not _bos(satir.get("hata")) and str(satir.get("hata")).strip():
        return False, "hata"
    if _bayrak(satir.get("evren_disi")):
        return False, "evren_disi"
    kaynak = satir.get("satir_kaynagi")
    sinir_ms = int((as_of.astimezone(UTC) - timedelta(days=int(rules["ilk11_kapi_tazelik_gun"]))).timestamp() * 1000)
    if not _bos(kaynak):
        if kaynak != "bu_kosu":
            return False, "eski_satir"
    elif _bos(satir.get("now_ms")) or float(satir["now_ms"]) < sinir_ms:
        return False, "eski_satir"
    return True, None


def adaylari_hazirla(tablo: pd.DataFrame, as_of: datetime, rules: dict) -> tuple[list[dict], dict[str, int]]:
    """Kapı tablosundan katman adayları (izleme_adayi | kopyalanabilir) + 10 ham alan. Diğer satırlar yalnız sayılır (``katman_yok``)."""
    adaylar: list[dict] = []
    sayac = {"toplam_satir": int(len(tablo)), "katman_yok": 0}
    gorulen: set[str] = set()
    for satir in tablo.to_dict("records"):
        adres = str(satir["address"]).lower()
        uygun, neden = satir_uygunlugu(satir, as_of, rules)
        if neden == "katman_yok":
            sayac["katman_yok"] += 1
            continue
        if adres in gorulen:
            raise GirdiHatasi(f"kapı tablosunda yinelenen adres: {adres}")
        gorulen.add(adres)
        alanlar, kaynaklar = ilk11_alanlar.ilk_alanlar(satir, rules)
        puan = secim.puan(satir)
        adaylar.append({"id": adres, "uygun": uygun, "uygunluk_nedeni": neden, "alanlar": alanlar, "alan_kaynagi": kaynaklar,
                        "kapi_puani": puan, "tarz": satir.get("tarz") if satir.get("tarz") in ("intraday", "swing") else None})
    return sorted(adaylar, key=lambda a: a["id"]), sayac


# ---------------------------------------------------------------------------------------------------- puan / dağılım yardımcıları

def yuzdelik_ve_puan(alanlar_by_id: Mapping[str, Mapping[str, float | None]]) -> tuple[dict[str, dict[str, float]], dict[str, float]]:
    """``ilk11`` fonksiyonlarıyla (değişmez) alan yüzdelikleri ve ağırlıklı puan; evren = verilen kümenin tamamı."""
    ham = {k: ilk11.hazirla_kaldirac_alanlari(v) for k, v in alanlar_by_id.items()}
    yuzdelik = {f: ilk11.yuzdelik({k: v.get(f) for k, v in ham.items()}, f in ilk11.DUSUK_IYI) for f in KALDIRAC_ALANLARI}
    return ({k: {f: yuzdelik[f][k] for f in KALDIRAC_ALANLARI} for k in ham}, ilk11.agirlikli_puan(ham))


def dagilim(degerler: Sequence[float]) -> dict[str, float | None]:
    xs = [float(x) for x in degerler if x is not None]
    return {"n": len(xs), "min": min(xs), "medyan": statistics.median(xs), "max": max(xs)} if xs else {"n": 0, "min": None, "medyan": None, "max": None}


def _f(x: Any) -> str:
    return "—" if x is None else (f"{x:.6g}" if isinstance(x, float) else str(x))


def alanlar_csv(adaylar: Sequence[Mapping[str, Any]], yuzdelik: Mapping[str, Mapping[str, float]], puan: Mapping[str, float]) -> str:
    """Aday başına: adres, uygun, neden, 10 ham alan, 10 yüzdelik, puan, kapı puanı, alan_kaynagi (JSON). Yüzdelik / puan yalnız uygun adaylarda."""
    satirlar = []
    for a in adaylar:
        satir: dict[str, Any] = {"adres": a["id"], "uygun": a["uygun"], "uygunluk_nedeni": a.get("uygunluk_nedeni") or ""}
        satir.update({f: a["alanlar"].get(f) for f in KALDIRAC_ALANLARI})
        satir.update({f + "_yuzdelik": yuzdelik.get(a["id"], {}).get(f) for f in KALDIRAC_ALANLARI})
        satir.update({"puan": puan.get(a["id"]), "kapi_puani": a.get("kapi_puani"),
                      "alan_kaynagi": json.dumps(a["alan_kaynagi"], ensure_ascii=False, sort_keys=True)})
        satirlar.append(satir)
    return pd.DataFrame(satirlar).to_csv(index=False, lineterminator="\n")


def doluluk_tablosu(ozet: Mapping[str, Mapping[str, int]], adaylar: Sequence[Mapping[str, Any]]) -> list[str]:
    """RAPOR: alan | dolu | eksik | ihlal | kaynak (uygun adaylarda en sık kaynak)."""
    uygun = [a for a in adaylar if a["uygun"]]
    satir = ["| alan | dolu | eksik | ihlal | kaynak |", "|---|---|---|---|---|"]
    for alan in KALDIRAC_ALANLARI:
        kaynaklar = [a["alan_kaynagi"].get(alan) for a in uygun if not ilk11_alanlar.ihlal_mi(a["alan_kaynagi"].get(alan)) and a["alan_kaynagi"].get(alan)]
        ana = max(set(kaynaklar), key=kaynaklar.count) if kaynaklar else "—"
        v = ozet[alan]
        satir.append(f"| {alan} | {v['dolu']}/{v['toplam']} | {v['eksik']} | {v['ihlal']} | `{ana}` |")
    return satir


def dagilim_tablosu(adaylar: Sequence[Mapping[str, Any]], yuzdelik: Mapping[str, Mapping[str, float]], puan: Mapping[str, float]) -> list[str]:
    uygun = [a for a in adaylar if a["uygun"]]
    satir = ["| sütun | n | min | medyan | max |", "|---|---|---|---|---|"]
    kaynaklar = [(f, [a["alanlar"].get(f) for a in uygun]) for f in KALDIRAC_ALANLARI]
    kaynaklar += [(f + "_yuzdelik", [yuzdelik[a["id"]][f] for a in uygun if a["id"] in yuzdelik]) for f in KALDIRAC_ALANLARI]
    kaynaklar.append(("puan", [puan[a["id"]] for a in uygun if a["id"] in puan]))
    for ad, xs in kaynaklar:
        d = dagilim(xs)
        satir.append(f"| {ad} | {d['n']} | {_f(d['min'])} | {_f(d['medyan'])} | {_f(d['max'])} |")
    return satir


def kadro_sabit_sutun_sorunlari(adaylar: Sequence[Mapping[str, Any]]) -> list[str]:
    """§6.3: sabit sütun (tüm değerler aynı) hatadır — yalnız ≥ 2 uygun adayta anlamlı."""
    uygun = [a for a in adaylar if a["uygun"]]
    if len(uygun) < 2:
        return []
    out = []
    for f in KALDIRAC_ALANLARI:
        degerler = {a["alanlar"].get(f) for a in uygun}
        if len(degerler) == 1:
            out.append(f"{f}: {len(uygun)} adayta sabit değer ({next(iter(degerler))!r})")
    return out


# ---------------------------------------------------------------------------------------------------- ilk seçim

def kaynak_surumu_kapi(kapi: Mapping[str, Any], rules_yolu: Path) -> dict[str, str]:
    """Snapshot ``kaynak_surumu``: girdi dosyalarının SHA-256'sı (§6.5d) ve kodun SHA'sı."""
    return {"kapi": kapi["tarih"], "kapi_sonuc_sha256": sha256_dosya(kapi["klasor"] / "sonuc.csv"),
            "kapi_durum_sha256": sha256_dosya(kapi["klasor"] / "durum.json"),
            "ilk11_alanlar": sha256_dosya(Path(ilk11_alanlar.__file__)), "kurallar": sha256_dosya(rules_yolu)}


def ilk_secim(adaylar: Sequence[dict], as_of: datetime, kaynak: Mapping[str, str], rules: dict, deneme: bool) -> dict[str, Any]:
    """Uygun evrende akıl sağlığı + doluluk + yayın eşiği kontrolü, sonra ``ilk11_veri.snapshot_olustur``. Döner: snapshot, yuzdelik, puan, ozet, uyarilar."""
    uygun = [a for a in adaylar if a["uygun"]]
    ozet = ilk11_alanlar.doluluk_ozeti([a["alanlar"] for a in uygun], [a["alan_kaynagi"] for a in uygun])
    problemler = ilk11_alanlar.saglik_sorunlari(ozet, rules) + ilk11_alanlar.doluluk_sorunlari(ozet, rules)
    if len(uygun) < int(rules["ilk11_min_uygun"]) and not deneme:
        problemler.append(f"uygun aday {len(uygun)} < {rules['ilk11_min_uygun']}: snapshot yayımlanmaz")
    yuzdelik, puan = yuzdelik_ve_puan({a["id"]: a["alanlar"] for a in uygun})
    sonuc: dict[str, Any] = {"ozet": ozet, "yuzdelik": yuzdelik, "puan": puan, "problemler": problemler, "snapshot": None,
                             "sabit_sutunlar": kadro_sabit_sutun_sorunlari(adaylar)}   # §6.3: RAPOR'da gösterilir (denetçi hata sayar), yayını engellemez
    if problemler:
        return sonuc
    girdi = [{"id": a["id"], "uygun": a["uygun"], "form_ham": a["alanlar"], "kapi_puani": a["kapi_puani"], "gecerli_gozlem_suresi": None} for a in adaylar]
    sonuc["snapshot"] = snapshot_olustur(girdi, as_of, kaynak)
    return sonuc


# ---------------------------------------------------------------------------------------------------- önceki kadro (§5.7)

def onceki_snapshot_bul(ilk11_kok: Path, as_of: datetime) -> tuple[str, dict] | None:
    """as_of tarihinden ÖNCEKİ en yeni YAYIMLANMIŞ (``akis.json`` basarili) gerçek Pazar snapshot'ı. Geçici (acil) kadro sayılmaz; hash doğrulanır."""
    gun = as_of.date()
    for klasor in sorted((p for p in ilk11_kok.glob("*") if p.is_dir() and _tarih_mi(p.name) and date.fromisoformat(p.name) < gun), reverse=True):
        yol = klasor / "snapshot.json"
        if not yol.exists() or not (_json(klasor / "akis.json", {}).get("basarili") is True):
            continue
        snap = json.loads(yol.read_text(encoding="utf-8"))
        if snap.get("sema") == GECICI_SEMA or str(snap.get("snapshot_id", "")).startswith(GECICI_KIMLIK_ONEKI) or snap.get("sema") not in (SEMA_ILK, SEMA_FORM):
            continue
        try:
            snapshot_json(snap)
        except ValueError as hata:
            raise GirdiHatasi(f"{klasor.name}/snapshot.json doğrulanamadı: {hata}") from hata
        return klasor.name, snap
    return None


def onceki_kadro(tarih: str, snap: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Önceki snapshot'tan kadro: [{id, grup, takim_hafta}]. İlk seçimde hepsi snapshot tarihinde girmiştir; formda ``kadro_sonrasi``."""
    if snap["sema"] == SEMA_FORM:
        return [{"id": r["id"], "grup": r["grup"], "takim_hafta": r["takim_hafta"]} for r in snap["kadro_sonrasi"]]
    return [{"id": r["id"], "grup": r["takim"], "takim_hafta": tarih} for r in snap["kadro"]]


# ---------------------------------------------------------------------------------------------------- haftalık form (§4)

def izleme_durum_sec(izleme_dali: Path, as_of_utc: datetime) -> tuple[dict, str]:
    """``copytrade-izleme`` git geçmişinden ``uretildi ≤ as_of`` olan EN SON ``izleme/durum.json`` sürümü (yalnız as_of'a bağlı → tekrar denemede aynı girdi).
    Döner: (durum, commit SHA)."""
    kayit = subprocess.run(["git", "-C", str(izleme_dali), "log", "--format=%H", "--", DURUM_YOLU], capture_output=True, text=True, check=False)
    if kayit.returncode != 0:
        raise GirdiHatasi(f"izleme dalı git geçmişi okunamadı: {kayit.stderr.strip()[:200]}")
    for sha in kayit.stdout.split():
        icerik = subprocess.run(["git", "-C", str(izleme_dali), "show", f"{sha}:{DURUM_YOLU}"], capture_output=True, text=True, check=False)
        if icerik.returncode != 0:
            continue
        durum = json.loads(icerik.stdout)
        if pd.Timestamp(durum["uretildi"]).to_pydatetime() <= as_of_utc:
            return durum, sha
    raise GirdiHatasi("as_of'tan önce üretilmiş izleme/durum.json sürümü yok")


def form_satiri(uye: Mapping[str, Any], trader: Mapping[str, Any] | None, as_of_utc: datetime, onceki_aktif: bool | None,
                kapi_puani: float | None, rules: dict) -> dict[str, Any]:
    """Bir kadro üyesinin form girdisi (``bu_pazar_gecerli`` / ``bu_pazar_aktif`` tanımları §4.1) ve ``paper_sonuclari`` (§4.2)."""
    bos = dict.fromkeys(KALDIRAC_ALANLARI)
    form = (trader or {}).get("ilk11_form_ham") or {}
    alanlar = {**bos, **(form.get("alanlar") or {})}
    veri_zamani = pd.Timestamp(trader["veri_zamani"]).to_pydatetime() if trader and trader.get("veri_zamani") else None
    taze = veri_zamani is not None and as_of_utc - veri_zamani <= timedelta(minutes=int(rules["ilk11_form_tazelik_dk"]))
    dolu = sum(v is not None for v in alanlar.values())
    gecerli = bool(trader and trader.get("gecerli") is True and taze and "alanlar" in form and dolu >= int(rules["ilk11_form_min_dolu_alan"]))
    aktif: bool | None = None
    if trader and trader.get("gecerli") is True and "son_perp_dolum" in trader:
        son = trader["son_perp_dolum"]
        aktif = bool(son and pd.Timestamp(son).to_pydatetime() > as_of_utc - 7 * GUN and pd.Timestamp(son).to_pydatetime() <= as_of_utc)
    saat = (trader or {}).get("ilk11_gecerli_saat") or {}
    gozlem = saat.get("saat", 0) / 24 if saat.get("baslangic") == uye["takim_hafta"] else None
    giris = pazar_as_of_tarih(uye["takim_hafta"]).astimezone(UTC)
    paper = sorted((x for x in ((trader or {}).get("sanal_kopya_v3") or {}).get("kapanan_islemler") or []
                    if x.get("gecerli") is True and pd.Timestamp(x["acilis"]).to_pydatetime() > giris and pd.Timestamp(x["kapanis"]).to_pydatetime() <= as_of_utc),
                   key=lambda x: x["kapanis"])
    return {"id": uye["id"], "grup": uye["grup"], "takim_hafta": uye["takim_hafta"], "alanlar": alanlar, "alan_kaynagi": (form.get("alan_kaynagi") or {}),
            "bu_pazar_gecerli": gecerli, "bu_pazar_aktif": aktif, "onceki_pazar_aktif": onceki_aktif, "kapi_puani": kapi_puani,
            "gecerli_gozlem_suresi": gozlem, "dolu_alan": dolu,
            "paper_sonuclari": [{"sonuc": x["sonuc_usd"], "gecerli": True, "kapanis": x["kapanis"]} for x in paper]}


def form_hesapla(kadro: Sequence[Mapping[str, Any]], durum: Mapping[str, Any], as_of: datetime, onceki_aktif: Mapping[str, bool | None],
                 kapi_puani: Mapping[str, float | None], rules: dict) -> dict[str, Any]:
    """Form puanı (kadronun 50'si arasında ``ilk11`` yüzdeliği) + ``ilk11.pazar_gecis`` planı. Döner: satirlar, plan."""
    as_of_utc = as_of.astimezone(UTC)
    trader = {str(t["adres"]).lower(): t for t in durum["traderlar"]}
    satirlar = [form_satiri(u, trader.get(u["id"]), as_of_utc, onceki_aktif.get(u["id"]), kapi_puani.get(u["id"]), rules) for u in kadro]
    _, puan = yuzdelik_ve_puan({s["id"]: s["alanlar"] for s in satirlar})
    for s in satirlar:
        s["form_puani"] = puan[s["id"]]
    plan = ilk11.pazar_gecis(satirlar, as_of.date().isoformat())
    return {"satirlar": satirlar, "plan": plan}


def kadro_sonrasi_uygula(satirlar: Sequence[Mapping[str, Any]], plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Plan hareketlerini uygular; ``kadrodisi`` olan çıkar. Sıra: id."""
    hareket = {m["id"]: m["sonra"] for m in plan["degisiklik_plani"]}
    return sorted(({"id": s["id"], "grup": hareket.get(s["id"], s["grup"]), "takim_hafta": s["takim_hafta"]} for s in satirlar
                   if hareket.get(s["id"]) != "kadrodisi"), key=lambda r: r["id"])


def bos_paf_doldur(kadro: list[dict[str, Any]], adaylar: Sequence[Mapping[str, Any]], tarih: str,
                   haric: Sequence[str] = ()) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """K-12.6: kadroda olmayan UYGUN adaylar İlk 11 puanıyla sıralanır; boş PAF yerlerine en iyisi girer (yalnız PAF'a giriş). Puan, uygun evrenin tamamında.
    ``haric``: bu hafta formdan kadro dışına çıkanlar aynı hafta geri alınmaz."""
    uygun = {a["id"]: a["alanlar"] for a in adaylar if a["uygun"]}
    _, puan = yuzdelik_ve_puan(uygun)
    uyeler = {r["id"] for r in kadro} | set(haric)
    bos = min(ilk11.PAF - sum(r["grup"] == "paf" for r in kadro), ilk11.KAPASITE - len(kadro))
    sirali = sorted((i for i in uygun if i not in uyeler), key=lambda i: (-puan[i], i))[:max(0, bos)]
    girenler = [{"id": i, "grup": "paf", "takim_hafta": tarih, "puan": puan[i]} for i in sirali]
    return sorted(kadro + [{k: v for k, v in g.items() if k != "puan"} for g in girenler], key=lambda r: r["id"]), girenler


def form_snapshot(as_of: datetime, kaynak: Mapping[str, str], satirlar: Sequence[Mapping[str, Any]], plan: Mapping[str, Any],
                  kadro_sonrasi: Sequence[Mapping[str, Any]], girenler: Sequence[Mapping[str, Any]], uyari: str | None) -> dict[str, Any]:
    """``ilk11-form-v1``: aynı kanonik JSON + SHA-256 kuralı (``snapshot_json`` ile doğrulanır)."""
    govde = {
        "sema": SEMA_FORM, "as_of": as_of.astimezone(ISTANBUL).isoformat(), "kaynak_surumu": dict(sorted(kaynak.items())),
        "adaylar": [{"id": s["id"], "uygun": True, "uygunluk_nedeni": None, "alanlar": s["alanlar"], "alan_kaynagi": s["alan_kaynagi"],
                     "kapi_puani": s["kapi_puani"], "gecerli_gozlem_suresi": s["gecerli_gozlem_suresi"], "form_puani": s["form_puani"],
                     "bu_pazar_gecerli": s["bu_pazar_gecerli"], "bu_pazar_aktif": s["bu_pazar_aktif"], "onceki_pazar_aktif": s["onceki_pazar_aktif"]}
                    for s in satirlar],
        "kadro": [{"id": s["id"], "takim": s["grup"], "puan": s["form_puani"]} for s in satirlar],
        "plan": {"degisiklik_plani": plan["degisiklik_plani"], "grup_sayilari_plan": plan["grup_sayilari_plan"], "aciklamalar": plan["aciklamalar"]},
        "boslugu_dolduranlar": [dict(g) for g in girenler], "kadro_sonrasi": [dict(r) for r in kadro_sonrasi], "uyari": uyari,
    }
    kanonik = json.dumps(govde, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {"snapshot_id": hashlib.sha256(kanonik.encode("utf-8")).hexdigest(), **govde}


# ---------------------------------------------------------------------------------------------------- izleme listesi (§5.3)

REFERANS_ETIKET = {"oda": "referans_oda", "referans_oda": "referans_oda", "kontrol": "referans_kontrol", "referans_kontrol": "referans_kontrol"}


def referans_etiketle(satir: Mapping[str, Any]) -> dict[str, Any] | None:
    """K-12.8 (lider kararı): pilotun `oda` / `kontrol` kolları sabit referans kolu olur (`referans_oda` / `referans_kontrol`; `id`, `t0` korunur);
    taban / elle / havuz / cikarilan saatlik izlemeden çıkar. Referans değilse ``None``."""
    etiketler = sorted({REFERANS_ETIKET[k] for k in {satir.get("kol"), *(satir.get("kollar") or [])} if k in REFERANS_ETIKET})
    return {**satir, "kol": etiketler[-1], "kollar": etiketler} if etiketler else None     # oda + kontrol birlikteyse referans_oda ana etiket


def liste_olustur(kadro: Sequence[Mapping[str, Any]], kaynak_satirlar: Sequence[Mapping[str, Any]], adaylar: Mapping[str, Mapping[str, Any]],
                  tarih: str, snapshot_id: str, form_puani: Mapping[str, float]) -> list[dict[str, Any]]:
    """K-12.8: yeni liste = kadro 50 + sabit referans kolları; eski pilot kolları (taban, elle, havuz, oda, kontrol …) çıkar. Aynı adres tek satır
    (``id`` / ``t0`` / ``kol`` korunur, ``takim`` eklenir). Yeni üye: yeni ``id`` + ``t0`` = snapshot günü (motor t0 değişmezliği)."""
    mevcut = {str(r["adres"]).lower(): dict(r) for r in kaynak_satirlar}
    uyeler = {r["id"]: r for r in kadro}
    kullanilan = {r["id"] for r in mevcut.values()}
    cikti: list[dict[str, Any]] = []
    for adres, satir in mevcut.items():
        takim_alanlari = ("takim", "snapshot_id", "form_puani", "takim_hafta")
        if adres in uyeler:
            continue
        if referans_etiketle(satir):
            cikti.append({k: v for k, v in referans_etiketle(satir).items() if k not in takim_alanlari})
    for adres, uye in sorted(uyeler.items()):
        satir = mevcut.get(adres)
        if satir is None:
            kimlik = "K" + adres[2:12]
            n = 12
            while kimlik in kullanilan:
                n += 2
                kimlik = "K" + adres[2:n]
            kullanilan.add(kimlik)
            satir = {"id": kimlik, "adres": adres, "takma_ad": adres[2:6], "durum": "izlemede", "t0": tarih}
            tarz = adaylar.get(adres, {}).get("tarz")
            if tarz:
                satir["tarz"] = tarz
        satir = {**(referans_etiketle(satir) or satir), "takim": uye["grup"], "snapshot_id": snapshot_id, "takim_hafta": uye["takim_hafta"]}
        if adres in form_puani:
            satir["form_puani"] = round(float(form_puani[adres]), 6)
        else:
            satir.pop("form_puani", None)
        cikti.append(satir)
    return cikti


def liste_yaz(yol: Path, satirlar: Sequence[Mapping[str, Any]]) -> None:
    """Yazar ve ``izleme_motoru.load_list`` ile doğrular (şema / benzersizlik hatası = iş hatası)."""
    yol.parent.mkdir(parents=True, exist_ok=True)
    yol.write_text("# İLK 11 İZLEME LİSTESİ — `python -m copytrade.ilk11_pazar` üretir; ELLE YAZILMAZ.\n"
                   + yaml.safe_dump({"traderlar": [dict(s) for s in satirlar]}, allow_unicode=True, sort_keys=False), encoding="utf-8")
    load_list(yol)


# ---------------------------------------------------------------------------------------------------- RAPOR

def rapor_ilk(tarih: str, kapi: Mapping[str, Any], sayac: Mapping[str, int], sonuc: Mapping[str, Any], adaylar: Sequence[Mapping[str, Any]],
              deneme: bool) -> str:
    snap, uygun = sonuc["snapshot"], [a for a in adaylar if a["uygun"]]
    nedenler: dict[str, int] = {}
    for a in adaylar:
        if not a["uygun"]:
            nedenler[a["uygunluk_nedeni"]] = nedenler.get(a["uygunluk_nedeni"], 0) + 1
    satir = [f"# İlk 11 — ilk seçim ({tarih})" + (" [DENEME]" if deneme else ""), "",
             f"- Durum: **{'YAYIMLANDI' if snap else 'YAYIMLANMADI'}**" + (f" (`snapshot_id` `{snap['snapshot_id']}`)" if snap else ""),
             f"- Kapı klasörü: `{kapi['tarih']}` (as_of'tan {kapi['gun_farki']} gün önce; hesap `{kapi['durum'].get('hesap')}`, kapsam {kapi['durum'].get('kapsam')})",
             f"- Kapı satırı {sayac['toplam_satir']}; katman adayı {len(adaylar)}, katman_yok {sayac['katman_yok']}; uygun evren **{len(uygun)}**; "
             f"uygun olmayan katman adayı: {nedenler or 'yok'}"]
    if snap:
        grup = {g: sum(r["takim"] == g for r in snap["kadro"]) for g in ("ilk11", "yedek11", "paf")}
        satir += [f"- Kadro: secim_adedi {snap['secim_adedi']}; İlk 11 {grup['ilk11']}, Yedek 11 {grup['yedek11']}, PAF {grup['paf']}; kapasite boş {50 - snap['secim_adedi']}"]
        if snap.get("uyari"):
            satir.append(f"- **UYARI:** {snap['uyari']}")
    if deneme:
        satir.append("- DENEME: yayın eşiği (`ilk11_min_uygun`) ve akış durumu uygulanmadı; hiçbir kadro / liste / son.json yazılmadı.")
    if sonuc.get("sabit_sutunlar"):
        satir += ["", "## UYARI: sabit sütun (tüm değerler aynı)"] + [f"- {p}" for p in sonuc["sabit_sutunlar"]]
    if sonuc["problemler"]:
        satir += ["", "## Sorunlar (snapshot yayımlanmadı)"] + [f"- {p}" for p in sonuc["problemler"]]
    satir += ["", "## Doluluk (uygun evren)", ""] + doluluk_tablosu(sonuc["ozet"], adaylar)
    satir += ["", "## Dağılım (uygun evren)", ""] + dagilim_tablosu(adaylar, sonuc["yuzdelik"], sonuc["puan"])
    if snap:
        satir += ["", "## Kadro (İlk 11 puanı sırasıyla)", "", "| sıra | adres | takım | puan |", "|---|---|---|---|"]
        satir += [f"| {i + 1} | `{r['id']}` | {r['takim']} | {r['puan']:.2f} |" for i, r in enumerate(snap["kadro"])]
    return "\n".join(satir) + "\n"


def rapor_form(tarih: str, kapi: Mapping[str, Any] | None, izleme: Mapping[str, str], satirlar: Sequence[Mapping[str, Any]], plan: Mapping[str, Any],
               kadro_sonrasi: Sequence[Mapping[str, Any]], girenler: Sequence[Mapping[str, Any]], uyarilar: Sequence[str], snapshot_id: str) -> str:
    sayim = {g: sum(r["grup"] == g for r in kadro_sonrasi) for g in ("ilk11", "yedek11", "paf")}
    gecerli = sum(s["bu_pazar_gecerli"] for s in satirlar)
    satir = [f"# İlk 11 — haftalık form ({tarih})", "", f"- `snapshot_id` `{snapshot_id}`",
             f"- İzleme girdisi: commit `{izleme['commit'][:12]}`, uretildi {izleme['uretildi']}",
             f"- Kapı: " + (f"`{kapi['tarih']}` ({kapi['gun_farki']} gün önce{'; ESKİ' if kapi['eski'] else ''})" if kapi else "yok"),
             f"- Kadro (önce): {len(satirlar)}; geçerli form {gecerli}/{len(satirlar)}; hareket {len(plan['degisiklik_plani'])}; boşluğu dolduran {len(girenler)}",
             f"- Kadro (sonra): İlk 11 {sayim['ilk11']}, Yedek 11 {sayim['yedek11']}, PAF {sayim['paf']} (toplam {len(kadro_sonrasi)})"]
    satir += [f"- **UYARI:** {u}" for u in uyarilar]
    satir += ["", "## Hareketler", ""] + ([f"- `{m['id']}`: {m['once']} -> {m['sonra']} ({m['neden']})" for m in plan["degisiklik_plani"]] or ["- yok"])
    satir += ["", "## Boşluğu dolduranlar (K-12.6)", ""] + ([f"- `{g['id']}` -> paf (puan {g['puan']:.2f})" for g in girenler] or ["- yok"])
    satir += ["", "## Açıklamalar", ""] + ([f"- `{a['id']}`: {a['neden']}" for a in plan["aciklamalar"]] or ["- yok"])
    satir += ["", "## Form dağılımı (kadro)", "", "| sütun | n | min | medyan | max |", "|---|---|---|---|---|"]
    for ad, xs in [(f, [s["alanlar"][f] for s in satirlar]) for f in KALDIRAC_ALANLARI] + [("form_puani", [s["form_puani"] for s in satirlar])]:
        d = dagilim(xs)
        satir.append(f"| {ad} | {d['n']} | {_f(d['min'])} | {_f(d['medyan'])} | {_f(d['max'])} |")
    return "\n".join(satir) + "\n"


# ---------------------------------------------------------------------------------------------------- akış

def _akis_oku(klasor: Path) -> dict[str, Any]:
    return _json(klasor / "akis.json", {"deneme_sayisi": 0, "snapshot_id": None, "son_basarisiz_at": None, "basarili": False})


def _plan_cagir(now: datetime, as_of: datetime, akis: Mapping[str, Any], snapshot_id: str | None) -> dict[str, Any]:
    ilk = int(akis["deneme_sayisi"]) == 0
    # İlk denemede planlayıcı "bu haftanın Pazar 13:00"ını arar; Pazar dışı telafi koşusunda as_of'u (geçen Pazar) "şimdi" gibi veririz.
    efektif = as_of if ilk and now.astimezone(ISTANBUL).date() != as_of.date() else now
    son = datetime.fromisoformat(akis["son_basarisiz_at"]) if akis.get("son_basarisiz_at") else None
    if son is None and not ilk:
        son = as_of          # ilk denemede başarıyla biten akışın başarısızlık zamanı yok; planlayıcı sözleşmesi bir zaman ister (başarılıysa 'tamamla' döner)
    return pazar_akis_plani(now=efektif, deneme_sayisi=int(akis["deneme_sayisi"]), snapshot_id=snapshot_id or akis.get("snapshot_id"),
                            retry_snapshot_id=(akis.get("snapshot_id") if not ilk else None), son_basarisiz_at=son, basarili=bool(akis.get("basarili")))


def _yaz(yol: Path, metin: str) -> None:
    yol.parent.mkdir(parents=True, exist_ok=True)
    yol.write_text(metin, encoding="utf-8")


def calistir(kapi_dali: Path, cikti: Path, now: datetime, izleme_dali: Path | None = None, durum_dosyasi: Path | None = None,
             taban_liste: Path | None = None, deneme: bool = False, rules: dict | None = None,
             rules_yolu: Path | None = None) -> int:
    """Pazar işi. Çıkış kodu 0: yayımlandı / bekle / tamamla; 1: girdi / kalite hatası (hiçbir şey yayımlanmadı, önceki kadro sürer; hazırlık hatası deneme SAYILMAZ);
    2: form yayımlandı AMA kapı eski / yok (boşluk doldurma yapılmadı) — iş akışı dosyaları commit eder, sonra işi KIRMIZI bitirir (§2)."""
    rules, rules_yolu = rules or load_rules(), rules_yolu or KURALLAR_YOLU
    as_of = pazar_as_of(now)
    tarih = as_of.date().isoformat()
    hedef = cikti / "ilk11" / tarih
    akis = _akis_oku(kapi_dali / "ilk11" / tarih)
    if not deneme:
        plan = _plan_cagir(now, as_of, akis, None)
        print(f"Pazar akışı ({tarih}): {plan['eylem']} — {plan['neden']}")
        if plan["eylem"] in ("bekle", "tamamla"):
            return 0
        if plan["eylem"] == "reddet":
            print("HATA: akış reddedildi", file=sys.stderr)
            return 1
    try:
        onceki = onceki_snapshot_bul(kapi_dali / "ilk11", as_of)
        kapi = None
        try:
            kapi = kapi_sec(kapi_dali, as_of, rules)
        except GirdiHatasi:
            if onceki is None:
                raise
        if onceki is None:
            sonuc_kodu = _ilk_secim_akisi(kapi, as_of, tarih, hedef, kapi_dali, cikti, akis, now, taban_liste, deneme, rules, rules_yolu)
        else:
            sonuc_kodu = _form_akisi(onceki, kapi, as_of, tarih, hedef, kapi_dali, cikti, akis, now, izleme_dali, durum_dosyasi, taban_liste, deneme, rules, rules_yolu)
    except GirdiHatasi as hata:
        _yaz(hedef / "RAPOR.md", f"# İlk 11 Pazar işi ({tarih}) — HATA\n\nSnapshot yayımlanmadı; önceki kadro sürer.\n\n- {hata}\n")
        print(f"HATA: {hata}", file=sys.stderr)
        return 1
    return sonuc_kodu


def _yayinla(hedef: Path, snapshot: Mapping[str, Any], csv_metni: str, plan: Mapping[str, Any], rapor: str, akis: Mapping[str, Any],
             now: datetime, deneme: bool) -> None:
    _yaz(hedef / "snapshot.json", snapshot_json(snapshot) + "\n")
    _yaz(hedef / "alanlar.csv", csv_metni)
    _yaz(hedef / "plan.json", json.dumps(plan, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    _yaz(hedef / "RAPOR.md", rapor)
    if not deneme:
        _yaz(hedef / "akis.json", json.dumps({"deneme_sayisi": int(akis["deneme_sayisi"]) + 1, "snapshot_id": snapshot["snapshot_id"],
                                              "son_basarisiz_at": akis.get("son_basarisiz_at"), "basarili": True}, indent=1) + "\n")


def _kimlik_kontrol(akis: Mapping[str, Any], snapshot_id: str) -> None:
    if int(akis["deneme_sayisi"]) > 0 and akis.get("snapshot_id") and akis["snapshot_id"] != snapshot_id:
        raise GirdiHatasi(f"tekrar denemede snapshot_id değişti ({akis['snapshot_id'][:12]} -> {snapshot_id[:12]}): girdi değişmiş olamaz, yayımlanmadı")


def _son_json_guncelle(kapi_dali: Path, cikti: Path, tarih: str, snapshot: Mapping[str, Any]) -> None:
    son = _json(kapi_dali / "son.json", {})
    son["ilk11"] = {"tarih": tarih, "snapshot_id": snapshot["snapshot_id"], "sema": snapshot["sema"]}
    _yaz(cikti / "son.json", json.dumps(son, ensure_ascii=False, indent=1, sort_keys=True) + "\n")


def _kaynak_liste(kapi_dali: Path, taban_liste: Path | None) -> list[dict]:
    onceki = kapi_dali / "ilk11/izleme_listesi.yaml"
    yol = onceki if onceki.exists() else taban_liste
    return load_list(yol) if yol and yol.exists() else []


def _ilk_secim_akisi(kapi, as_of, tarih, hedef, kapi_dali, cikti, akis, now, taban_liste, deneme, rules, rules_yolu) -> int:
    if kapi["eski"]:
        raise GirdiHatasi(f"kapı verisi eski: {kapi['gun_farki']} gün > {rules['ilk11_kapi_tazelik_gun']} (klasör {kapi['tarih']}); ilk seçim yapılmaz")
    tablo = pd.read_csv(kapi["klasor"] / "sonuc.csv")
    adaylar, sayac = adaylari_hazirla(tablo, as_of, rules)
    sonuc = ilk_secim(adaylar, as_of, kaynak_surumu_kapi(kapi, rules_yolu), rules, deneme)
    csv_metni = alanlar_csv(adaylar, sonuc["yuzdelik"], sonuc["puan"])
    rapor = rapor_ilk(tarih, kapi, sayac, sonuc, adaylar, deneme)
    if sonuc["snapshot"] is None:
        _yaz(hedef / "RAPOR.md", rapor)
        _yaz(hedef / "alanlar.csv", csv_metni)
        print("HATA: " + "; ".join(sonuc["problemler"]), file=sys.stderr)
        return 1
    snap = sonuc["snapshot"]
    _kimlik_kontrol(akis, snap["snapshot_id"])
    plan = {"tur": "ilk_secim", "snapshot_id": snap["snapshot_id"], "alanlar_csv_sha256": sha256_metin(csv_metni),
            "dagitim": [{"id": r["id"], "takim": r["takim"], "puan": r["puan"]} for r in snap["kadro"]],
            "kapasite_bos": ilk11.KAPASITE - snap["secim_adedi"], "uyari": snap["uyari"]}
    _yayinla(hedef, snap, csv_metni, plan, rapor, akis, now, deneme)
    if not deneme:
        kadro = [{"id": r["id"], "grup": r["takim"], "takim_hafta": tarih} for r in snap["kadro"]]
        liste_yaz(cikti / "ilk11/izleme_listesi.yaml", liste_olustur(kadro, _kaynak_liste(kapi_dali, taban_liste), {a["id"]: a for a in adaylar},
                                                                         tarih, snap["snapshot_id"], {}))
        _son_json_guncelle(kapi_dali, cikti, tarih, snap)
    print(f"İlk seçim yayımlandı: snapshot_id {snap['snapshot_id']}, secim_adedi {snap['secim_adedi']}")
    return 0


def _form_akisi(onceki, kapi, as_of, tarih, hedef, kapi_dali, cikti, akis, now, izleme_dali, durum_dosyasi, taban_liste, deneme, rules, rules_yolu) -> int:
    onceki_tarih, onceki_snap = onceki
    kadro = onceki_kadro(onceki_tarih, onceki_snap)
    as_of_utc = as_of.astimezone(UTC)
    if durum_dosyasi is not None:
        durum, izleme_commit = json.loads(durum_dosyasi.read_text(encoding="utf-8")), "dosya:" + sha256_dosya(durum_dosyasi)
    elif izleme_dali is not None:
        durum, izleme_commit = izleme_durum_sec(izleme_dali, as_of_utc)
    else:
        raise GirdiHatasi("form için --izleme-dali (ya da --durum-dosyasi) gerekli")
    uyarilar: list[str] = []
    uretildi = pd.Timestamp(durum["uretildi"]).to_pydatetime()
    if as_of_utc - uretildi > timedelta(minutes=int(rules["ilk11_form_tazelik_dk"])):
        uyarilar.append(f"izleme girdisi eski ({uretildi.isoformat()}; as_of'tan {(as_of_utc - uretildi) / timedelta(minutes=1):.0f} dk önce > "
                        f"{rules['ilk11_form_tazelik_dk']}): bu hafta form geçersiz, form hareketi yok")
    adaylar, kapi_puani = [], {}
    if kapi is not None and not kapi["eski"]:
        adaylar, _ = adaylari_hazirla(pd.read_csv(kapi["klasor"] / "sonuc.csv"), as_of, rules)
        kapi_puani = {a["id"]: a["kapi_puani"] for a in adaylar}
    elif kapi is None:
        uyarilar.append("uygun kapı klasörü yok: kapı puanı (eşitlik) boş, kadro boşluğu doldurulmadı")
    else:
        uyarilar.append(f"kapı verisi eski ({kapi['gun_farki']} gün > {rules['ilk11_kapi_tazelik_gun']}): kadro boşluğu doldurulmadı, kapı puanı boş")
    onceki_aktif = {a["id"]: a.get("bu_pazar_aktif") for a in onceki_snap.get("adaylar", []) if onceki_snap["sema"] == SEMA_FORM}
    hesap = form_hesapla(kadro, durum, as_of, onceki_aktif, kapi_puani, rules)
    satirlar, plan = hesap["satirlar"], hesap["plan"]
    kadro_sonra = kadro_sonrasi_uygula(satirlar, plan)
    girenler: list[dict[str, Any]] = []
    if adaylar:
        kadro_sonra, girenler = bos_paf_doldur(kadro_sonra, adaylar, tarih, [m["id"] for m in plan["degisiklik_plani"] if m["sonra"] == "kadrodisi"])
    kaynak = {"izleme": f"{izleme_commit}@{durum['uretildi']}", "ilk11_alanlar": sha256_dosya(Path(ilk11_alanlar.__file__)), "kurallar": sha256_dosya(rules_yolu),
              "onceki_snapshot": onceki_snap["snapshot_id"]}
    if kapi is not None:
        kaynak.update({"kapi": kapi["tarih"], "kapi_sonuc_sha256": sha256_dosya(kapi["klasor"] / "sonuc.csv")})
    snap = form_snapshot(as_of, kaynak, satirlar, plan, kadro_sonra, girenler, "; ".join(uyarilar) or None)
    _kimlik_kontrol(akis, snap["snapshot_id"])
    yuzdelik, puan = yuzdelik_ve_puan({s["id"]: s["alanlar"] for s in satirlar})
    csv_metni = alanlar_csv([{**s, "uygun": True, "uygunluk_nedeni": None} for s in satirlar], yuzdelik, puan)
    rapor = rapor_form(tarih, kapi, {"commit": izleme_commit, "uretildi": durum["uretildi"]}, satirlar, plan, kadro_sonra, girenler, uyarilar, snap["snapshot_id"])
    plan_json = {"tur": "form", "snapshot_id": snap["snapshot_id"], **plan, "boslugu_dolduranlar": girenler, "kadro_sonrasi": kadro_sonra}
    _yayinla(hedef, snap, csv_metni, plan_json, rapor, akis, now, deneme)
    if not deneme:
        puanlar = {s["id"]: s["form_puani"] for s in satirlar}
        kapi_adaylar = {a["id"]: a for a in adaylar}
        liste_yaz(cikti / "ilk11/izleme_listesi.yaml", liste_olustur(kadro_sonra, _kaynak_liste(kapi_dali, taban_liste), kapi_adaylar, tarih, snap["snapshot_id"], puanlar))
        _son_json_guncelle(kapi_dali, cikti, tarih, snap)
    print(f"Form yayımlandı: snapshot_id {snap['snapshot_id']}, hareket {len(plan['degisiklik_plani'])}, boşluğu dolduran {len(girenler)}")
    # §2: kapı eski / yok ise boşluk doldurma yapılmaz ve iş kırmızı biter (veri yine de yazıldı, kadro hareketleri uygulandı)
    return 2 if kapi is None or kapi["eski"] else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kapi-dali", type=Path, required=True)
    ap.add_argument("--cikti", type=Path, default=None, help="varsayılan: --kapi-dali")
    ap.add_argument("--izleme-dali", type=Path, default=None)
    ap.add_argument("--durum-dosyasi", type=Path, default=None, help="git yerine doğrudan izleme/durum.json (deneme)")
    ap.add_argument("--taban-liste", type=Path, default=None, help="ilk çalıştırmada referans kolların alınacağı liste (örn. main'deki copytrade/izleme_listesi.yaml)")
    ap.add_argument("--now", default=None, help="ISO zaman (varsayılan: şimdi, UTC)")
    ap.add_argument("--deneme", action="store_true", help="kural 1 denemesi: akış / liste / son.json yazılmaz, yayın eşiği uygulanmaz")
    ap.add_argument("--basarisiz-isaretle", action="store_true", help="bu Pazar için akis.json'a başarısız deneme yaz (push başarısız olduysa)")
    args = ap.parse_args(argv)
    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else datetime.now(UTC)
    cikti = args.cikti or args.kapi_dali
    if args.basarisiz_isaretle:
        tarih = pazar_as_of(now).date().isoformat()
        akis = _akis_oku(args.kapi_dali / "ilk11" / tarih)
        _yaz(cikti / "ilk11" / tarih / "akis.json", json.dumps({**akis, "deneme_sayisi": int(akis["deneme_sayisi"]) + 1, "basarili": False,
                                                              "son_basarisiz_at": now.isoformat()}, indent=1) + "\n")
        return 0
    return calistir(args.kapi_dali, cikti, now, args.izleme_dali, args.durum_dosyasi, args.taban_liste, args.deneme)


if __name__ == "__main__":
    sys.exit(main())
