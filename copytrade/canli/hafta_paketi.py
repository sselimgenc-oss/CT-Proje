"""CT haftalık veri paketi (YALNIZ BİLGİ; karar/limit/eşik/işlem mantığına girmez): orkestratör ve danışmanın Pazartesi sabahı okuduğu TEK Markdown.

Girdi (hesap yeniden yapılmaz, hazır dosyalar okunur): `durum/paylasim/{gunluk_ozet,rejim_sonuc,secim_gercek,kural_maliyet}_v1.json`, radar dalı (`radar/<tarih>/isabet.json`,
raw.githubusercontent.com; kadro okumasıyla aynı repo/dal kuralı, kısa zaman aşımı, hata = "radar verisi okunamadı") ve `durum/hafta_gecmis.json` (günlük özet damgalarından
her yazımda güncellenen 14 günlük küçük geçmiş: haftalık kasa farkı, filtre/ders toplamı, gecikme/kayma, RAM tepe, yeniden başlama).
Yazım: `durum/paylasim/CT_HAFTA_<YYYY-AA-GG>.md` (tarih = yaklaşan Pazartesi, TSİ) + `CT_HAFTA_son.md`; Pazar 21:00 TSİ'den sonra, haftada bir (dosya varsa tekrar yazılmaz).
Trader adresi yok (özet dosyaları zaten takma ad/adetle gelir; burada adres deseni ayrıca maskelenir).
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

TSI = timezone(timedelta(hours=3))                                     # Türkiye: sabit UTC+3 (yaz saati yok)
GECMIS = "hafta_gecmis.json"
GECMIS_GUN = 14
RADAR_GUN = 8
RADAR_TIMEOUT_SN = 8.0
SON = "CT_HAFTA_son.md"
_ADRES = re.compile(r"0x[0-9a-fA-F]+")
YOK = "—"


# ---------------------------------------------------------------------------------------------------- yardımcılar
def _oku(yol: Path) -> dict | None:
    try:
        d = json.loads(Path(yol).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def _say(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") else None


def _f(v: Any, n: int = 2, isaret: bool = False) -> str:
    x = _say(v)
    if x is None:
        return YOK
    return f"{x:+.{n}f}" if isaret else f"{x:.{n}f}"


def _yuzde(v: Any, n: int = 2) -> str:
    x = _say(v)
    return YOK if x is None else f"{100 * x:+.{n}f}"


def _tablo(baslik: list[str], satirlar: list[list[str]]) -> list[str]:
    out = ["| " + " | ".join(baslik) + " |", "|" + "|".join("---" for _ in baslik) + "|"]
    return out + ["| " + " | ".join(s) + " |" for s in satirlar]


def rapor_tarihi(simdi_ms: int) -> date:
    """TSİ'de yaklaşan Pazartesi (bugün Pazartesi ise bugün): orkestratörün haftalık raporu Pazartesi sabahı (ilk: 23.11.2026)."""
    g = datetime.fromtimestamp(simdi_ms / 1000, UTC).astimezone(TSI).date()
    return g + timedelta(days=(0 - g.weekday()) % 7)


pazar_tarihi = rapor_tarihi                                              # geriye uyum (eski ad)


# ---------------------------------------------------------------------------------------------------- radar
def radar_url(rules: dict, tarih: str) -> str:
    return f"https://raw.githubusercontent.com/{rules['canli_kadro_repo']}/{rules['canli_kadro_dali']}/radar/{tarih}/isabet.json"


def radar_oku(rules: dict, bitis: date, gun: int = RADAR_GUN, timeout: float = RADAR_TIMEOUT_SN) -> list[dict] | None:
    """Son `gun` günün radar isabet.json dosyaları (tarih artan). 404 = o gün yok (atlanır); ağ hatası/bozuk yanıt = None (okunamadı; denemeyi keser)."""
    import requests
    sonuc: list[dict] = []
    try:
        for i in range(gun - 1, -1, -1):
            t = (bitis - timedelta(days=i)).isoformat()
            r = requests.get(radar_url(rules, t), timeout=timeout)
            if r.status_code == 404:
                continue
            r.raise_for_status()
            d = r.json()
            if isinstance(d, dict):
                sonuc.append(d)
    except Exception:                                                  # noqa: BLE001
        return None
    return sonuc


# ---------------------------------------------------------------------------------------------------- geçmiş (haftalık toplama için)
def gecmis_oku(durum_dizin: Path) -> dict:
    return _oku(Path(durum_dizin) / GECMIS) or {}


def _yaz_atomik(yol: Path, metin: str) -> None:
    yol.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(yol.parent), prefix=".hp-", suffix=".tmp")
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


def kaydet(durum_dizin: Path, ozet: dict) -> None:
    """Günlük özet sözlüğünden (gunluk_ozet.olustur çıktısı) o UTC günün satırını günceller (günün son değeri kalır; yeniden başlama saat kovalarında toplanır)."""
    gun = str(ozet.get("gun") or "")
    if not gun:
        return
    h = gecmis_oku(durum_dizin)
    s = h.get(gun) if isinstance(h.get(gun), dict) else {}
    og, sg, kk, ks = ozet.get("ogrenme") or {}, ozet.get("saglik") or {}, ozet.get("kopya_kalite") or {}, ozet.get("kasa") or {}
    saat = str(ozet.get("uretim") or "")[11:13]
    rb = dict(s.get("rb") or {})
    if saat and isinstance(sg.get("yeniden_baslama_1s"), int):
        rb[saat] = sg["yeniden_baslama_1s"]
    s.update({"oz": ks.get("simdi"), "baslangic": ks.get("baslangic"), "filtre_atlanan": og.get("filtre_atlanan"), "filtre_kp": og.get("filtre_karsi_olgu_pnl"),
              "ders_kucultulen": og.get("ders_kucultulen"), "ders_engellenen": og.get("ders_engellenen"), "kk_n": kk.get("n"),
              "gecikme_med": kk.get("gecikme_ms_medyan"), "gecikme_p90": kk.get("gecikme_ms_p90"), "kayma_med": kk.get("kayma_bps_medyan"), "kayma_p90": kk.get("kayma_bps_p90"),
              "ram_tepe": max([x for x in (_say(s.get("ram_tepe")), _say(sg.get("ram_tepe_mb")), _say(sg.get("ram_mb"))) if x is not None], default=None),
              "rb": rb, "oom": bool(s.get("oom")) or sg.get("oom_son") is True, "oom_olculdu": bool(s.get("oom_olculdu")) or isinstance(sg.get("oom_son"), bool)})
    h[gun] = s
    for k in sorted(h)[:-GECMIS_GUN]:
        del h[k]
    _yaz_atomik(Path(durum_dizin) / GECMIS, json.dumps(h, ensure_ascii=False, indent=1))


def _hafta_gunleri(gecmis: dict, bitis: date) -> list[tuple[str, dict]]:
    """Bitişe (Pazartesi) kadar son 7 UTC gününün kayıtları (Pazar akşamı yazılırken bitiş günü hariç: Pazar dahil geri 7 gün)."""
    son = bitis - timedelta(days=1)
    alt = (son - timedelta(days=6)).isoformat()
    return [(g, gecmis[g]) for g in sorted(gecmis) if alt <= g <= son.isoformat() and isinstance(gecmis[g], dict)]


# ---------------------------------------------------------------------------------------------------- bölümler
def _b_kasa(oz: dict | None, rs: dict | None, hafta: list[tuple[str, dict]], uyari: list[str]) -> list[str]:
    out = ["## 1) Kasa ve haftalık PnL", ""]
    if not oz:
        uyari.append("gunluk_ozet_v1.json okunamadı: kasa bölümü boş.")
        return out + ["Veri yok (günlük özet okunamadı).", ""]
    k, isl = oz.get("kasa") or {}, oz.get("islem") or {}
    haftalik, kapsam = None, ""
    oz_l = [(g, _say(s.get("oz"))) for g, s in hafta if _say(s.get("oz")) is not None]
    if oz_l and _say(k.get("simdi")) is not None:
        g0, v0 = oz_l[0]
        haftalik = float(k["simdi"]) - v0
        kapsam = f"{g0} sonrası; {len(oz_l)} günlük kayıt"
        if len(oz_l) < 7:
            uyari.append(f"Kasa geçmişi {len(oz_l)}/7 gün: haftalık PnL kısmi ({g0} günü son değerinden itibaren).")
    else:
        uyari.append("Kasa geçmişi yok: haftalık PnL hesaplanamadı (toplam PnL başlangıçtan).")
    gerc = rs_toplam(rs)
    out += _tablo(["Mod", "Başlangıç $", "Şimdi $", "Toplam PnL $", "Haftalık PnL $", "Zirveden düşüş %", "Açık poz."],
                  [[str(oz.get("mod") or YOK), _f(k.get("baslangic")), _f(k.get("simdi")), _f(k.get("toplam_pnl"), isaret=True), _f(haftalik, isaret=True),
                    _f(k.get("zirveden_dusus_yuzde")), str(isl.get("acik_pozisyon", YOK))]])
    satir = f"Haftalık PnL = şimdiki özsermaye − kayıtlı en eski gün sonu ({kapsam or 'geçmiş yok'})."
    if gerc:
        satir += f" Son 7 günde kapanan {gerc[0]} işlemde gerçekleşen K/Z (ücret hariç): {gerc[1]:+.2f} $."
    out += ["", satir, ""]
    return out


def rs_toplam(rs: dict | None) -> tuple[int, float] | None:
    satirlar = (((rs or {}).get("tablolar") or {}).get("rejim_1d")) or []
    if not satirlar:
        return None
    return sum(int(r.get("n") or 0) for r in satirlar), sum(_say(r.get("toplam_pnl")) or 0.0 for r in satirlar)


def _b_secim(radar: list[dict] | None, sg: dict | None, uyari: list[str]) -> list[str]:
    out = ["## 2) Seçim: isabet + rastgele (radar) ve form × gerçek PnL", ""]
    if radar is None:
        uyari.append("radar verisi okunamadı (ağ/zaman aşımı).")
        out += ["Radar isabeti: radar verisi okunamadı.", ""]
    elif not radar:
        uyari.append("Radar dalında son 8 günde isabet dosyası yok.")
        out += ["Radar isabeti: son 8 günde isabet dosyası yok.", ""]
    else:
        satirlar = []
        for d in radar:
            g = (d.get("gruplar") or {}).get("ilk11") or {}
            rk = d.get("rastgele_karsilastirma") or {}
            tam = rk.get("durum") == "tamam"
            satirlar.append([str(d.get("tarih") or YOK), str(g.get("n", YOK)), _yuzde(g.get("ortalama")), _f(g.get("kar_orani"), 2) if g.get("n") else YOK,
                             _yuzde(rk.get("rastgele_medyan")) if tam else YOK, f"{rk['yuzdelik']:.0f}" if tam else YOK, f"{rk['p']:.3f}" if tam else YOK])
        out += _tablo(["Isabet günü", "İlk11 ölçülen", "İlk11 ort. 7g %", "Kâr oranı", "Rastgele medyan %", "Yüzdelik", "p"], satirlar)
        if not any((d.get("gruplar") or {}).get("ilk11", {}).get("n") for d in radar):
            uyari.append("Radar isabetlerinde ölçülen İlk11 yok (7 günlük pencere dolmadı).")
        if not any((d.get("rastgele_karsilastirma") or {}).get("durum") == "tamam" for d in radar):
            uyari.append("Radar rastgele karşılaştırması bu isabet dosyalarında yok/havuz yok.")
        out += ["", "Pencereler örtüşür; yüzdelik şansta ≈ 50, küçük p = seçim şansın üstünde.", ""]
    if not sg:
        uyari.append("secim_gercek_v1.json yok: form × gerçek PnL boş.")
        return out + ["Form × gerçek PnL: veri yok.", ""]
    t = sg.get("toplu") or {}
    if t.get("durum") == "tamam":
        out.append(f"Form × gerçek PnL (Spearman): {t.get('gun_n')} gün, ortalama ρ = {_f(t.get('rho_ort'), 3, True)}, p = {_f(t.get('p'), 3)} (tek yönlü; ρ>0 yüksek form daha çok kazandırmış).")
    else:
        out.append("Form × gerçek PnL: toplu sonuç yok (yeterli trader/gün yok).")
    gunler = [g for g in (sg.get("gunler") or []) if g.get("durum") == "tamam"][-7:]
    if gunler:
        out += [""] + _tablo(["Gün", "Kopyalanan / Kadro", "ρ", "p", "Net PnL $"],
                             [[g["gun"], f"{g['kopyalanan_n']} / {g['kadro_n']}", _f(g.get("rho"), 3, True), _f(g.get("p"), 3), _f(g.get("toplam_net_pnl"), isaret=True)] for g in gunler])
    return out + [""]


def _b_rejim(rs: dict | None, uyari: list[str]) -> list[str]:
    out = ["## 3) Rejim × sonuç (son 7 gün kapanan işlemler)", ""]
    if not rs:
        uyari.append("rejim_sonuc_v1.json yok: rejim bölümü boş.")
        return out + ["Veri yok.", ""]
    ad = {"rejim_1d": "Rejim 1g", "rejim_4h": "Rejim 4s", "duygu": "Duygu"}
    satirlar = []
    for b, a in ad.items():
        for r in (rs.get("tablolar") or {}).get(b) or []:
            satirlar.append([a, str(r.get("etiket")), str(r.get("n")), _f(r.get("isabet_yuzde"), 1), _f(r.get("toplam_pnl"), isaret=True), _f(r.get("ortalama_pnl"), isaret=True)])
    out += _tablo(["Boyut", "Etiket", "İşlem", "İsabet %", "Toplam PnL $", "Ort. PnL $"], satirlar) if satirlar else ["Kapanan işlem yok."]
    tum = rs_toplam(rs)
    bil = sum(int(r.get("n") or 0) for r in (rs.get("tablolar") or {}).get("rejim_1d", []) if r.get("etiket") == "bilinmiyor")
    if tum and tum[0] and bil == tum[0]:
        uyari.append("Tüm kapanan işlemlerin rejimi 'bilinmiyor' (giriş damgası yeni; rejim kırılımı henüz anlamsız).")
    return out + [""]


def _b_kural(km: dict | None, uyari: list[str]) -> list[str]:
    out = ["## 4) Kural maliyeti (alınmayan sinyal × karşı-olgu)", ""]
    if not km:
        uyari.append("kural_maliyet_v1.json yok: kural maliyeti boş.")
        return out + ["Slot tavanı: veri yok.", ""]
    v = (km.get("vurgu") or {}).get("slot_tavani")
    if v:
        out += [f"**Slot tavanı:** {v['olay_adedi']} olay, {v['trader_sayisi']} trader; karşı-olgu toplam {_f(v.get('toplam_karsi_olgu_pnl'), isaret=True)} $ "
                f"(kapanan {_f(v.get('karsi_olgu_kapanan_pnl'), isaret=True)}, açık {_f(v.get('karsi_olgu_acik_pnl'), isaret=True)}; hayali nosyonel {_f(v.get('hayali_nosyonel'))} $).", ""]
    else:
        out += ["**Slot tavanı:** son 7 günde kayıt yok.", ""]
    sat = (km.get("satirlar") or [])[:6]
    if sat:
        out += _tablo(["Neden", "Olay", "Trader", "Karşı-olgu toplam $", "Hayali nosyonel $"],
                      [[str(r["neden"]), str(r.get("olay_adedi")), str(r.get("trader_sayisi")), _f(r.get("toplam_karsi_olgu_pnl"), isaret=True), _f(r.get("hayali_nosyonel"))] for r in sat])
    out += ["", "Karşı-olgu adres|coin başına tek açılır; sık nedenler eksik örneklenir, $ alt sınır/yaklaşıktır.", ""]
    return out


def _topla(hafta: list[tuple[str, dict]], anahtar: str) -> float | None:
    v = [x for x in (_say(s.get(anahtar)) for _, s in hafta) if x is not None]
    return sum(v) if v else None


def _b_ogrenme(oz: dict | None, hafta: list[tuple[str, dict]], uyari: list[str]) -> list[str]:
    out = ["## 5) Öğrenme etkisi (filtre / ders)", ""]
    og = (oz or {}).get("ogrenme") or {}
    if not og and not hafta:
        uyari.append("Öğrenme verisi yok (günlük özet ve geçmiş boş).")
        return out + ["Veri yok.", ""]
    n = len(hafta)
    atlanan, kp, kucuk, engel = (_topla(hafta, k) for k in ("filtre_atlanan", "filtre_kp", "ders_kucultulen", "ders_engellenen"))
    out += _tablo(["Kapsam", "Filtre atlanan", "Filtre karşı-olgu $", "Ders küçültülen", "Ders engellenen"],
                  [[f"hafta ({n} gün kayıtlı)", _f(atlanan, 0), _f(kp, isaret=True), _f(kucuk, 0), _f(engel, 0)],
                   ["bugün", _f(og.get("filtre_atlanan"), 0), _f(og.get("filtre_karsi_olgu_pnl"), isaret=True), _f(og.get("ders_kucultulen"), 0), _f(og.get("ders_engellenen"), 0)]])
    out += ["", f"Filtre aktif: {'evet' if og.get('filtre_aktif') else 'hayır'}; dersler: aktif {og.get('aktif_ders', YOK)}, yeni {og.get('yeni_ders', YOK)}, emekli {og.get('emekli_ders', YOK)}. "
                "Karşı-olgu $ = filtrenin/dersin atladığı işlemlerin hayali sonucu (+ = atlanan işlem kazanacaktı, yani atlamak maliyetli; − = atlamak kâr).", ""]
    if n < 7:
        uyari.append(f"Öğrenme haftalık toplamı {n}/7 gün kayıttan.")
    return out


def _b_kalite(oz: dict | None, hafta: list[tuple[str, dict]], uyari: list[str]) -> list[str]:
    out = ["## 6) Kopya kalitesi (gecikme / kayma)", ""]
    kk = (oz or {}).get("kopya_kalite") or {}
    satirlar = [[g, str(s.get("kk_n", YOK)), _f(s.get("gecikme_med"), 0), _f(s.get("gecikme_p90"), 0), _f(s.get("kayma_med"), 1, True), _f(s.get("kayma_p90"), 1, True)]
                for g, s in hafta if s.get("kk_n")]
    if satirlar:
        out += _tablo(["Gün", "Dolan emir", "Gecikme medyan ms", "Gecikme p90 ms", "Kayma medyan bps", "Kayma p90 bps"], satirlar)
    elif kk.get("n"):
        out += _tablo(["Kapsam", "Dolan emir", "Gecikme medyan ms", "Gecikme p90 ms", "Kayma medyan bps", "Kayma p90 bps"],
                      [["bugün", str(kk.get("n")), _f(kk.get("gecikme_ms_medyan"), 0), _f(kk.get("gecikme_ms_p90"), 0), _f(kk.get("kayma_bps_medyan"), 1, True), _f(kk.get("kayma_bps_p90"), 1, True)]])
    else:
        uyari.append("Kopya kalitesi verisi yok (dolan emir yok ya da özet/geçmiş boş).")
        return out + ["Veri yok.", ""]
    return out + ["", "Gecikme = bizim dolum − trader dolumu; kayma + = trader fiyatından aleyhe (bps). Günlük değerler gün sonu özetinden.", ""]


def _b_saglik(oz: dict | None, hafta: list[tuple[str, dict]], uyari: list[str]) -> list[str]:
    out = ["## 7) Sunucu sağlığı", ""]
    sg = (oz or {}).get("saglik") or {}
    ram = [x for x in [_say(s.get("ram_tepe")) for _, s in hafta] + [_say(sg.get("ram_tepe_mb"))] if x is not None]
    rb_ol = [s for _, s in hafta if isinstance(s.get("rb"), dict) and s["rb"]]
    rb = sum(sum(int(x) for x in s["rb"].values()) for s in rb_ol) if rb_ol else (sg.get("yeniden_baslama_1s") if isinstance(sg.get("yeniden_baslama_1s"), int) else None)
    oom_ol = any(s.get("oom_olculdu") for _, s in hafta)
    oom = (any(s.get("oom") for _, s in hafta) if oom_ol else None)
    if oom is None and isinstance(sg.get("oom_son"), bool):
        oom = sg["oom_son"]
    out += _tablo(["RAM tepe MB", "Yeniden başlama (hafta)", "OOM-kill", "Disk boş GB", "Hata (bugün)"],
                  [[_f(max(ram) if ram else None, 1), YOK if rb is None else str(rb), YOK if oom is None else ("EVET" if oom else "yok"), _f(sg.get("disk_bos_gb"), 1), str(sg.get("hata_sayisi_gun", YOK))]])
    out += ["", f"Yeniden başlama = saatlik ölçümlerin toplamı ({len(rb_ol)} günde ölçüm var); OOM/yeniden başlama '{YOK}' = ölçülemedi (sunucu dışı ya da bayat).", ""]
    if not ram:
        uyari.append("RAM tepe ölçümü yok.")
    if rb is None:
        uyari.append("Yeniden başlama ölçümü yok (saglik_sunucu.json yok/bayat).")
    return out


def olustur(paylasim: Path, hafta_bitis: date, radar: list[dict] | None, gecmis: dict | None = None) -> str:
    """Haftalık paket Markdown'u. `radar`: radar_oku çıktısı (None = okunamadı). Saf okuma."""
    p = Path(paylasim)
    oz, rs, sg, km = (_oku(p / f) for f in ("gunluk_ozet_v1.json", "rejim_sonuc_v1.json", "secim_gercek_v1.json", "kural_maliyet_v1.json"))
    hafta = _hafta_gunleri(gecmis or {}, hafta_bitis)
    uyari: list[str] = []
    govde = [f"# CT haftalık veri paketi — {hafta_bitis.isoformat()}", "",
             f"Yalnız bilgi (karar/limit değiştirmez). Hafta: {(hafta_bitis - timedelta(days=7)).isoformat()} → {hafta_bitis.isoformat()}; özet üretimi: {(oz or {}).get('uretim', YOK)}.", ""]
    govde += _b_kasa(oz, rs, hafta, uyari)
    govde += _b_secim(radar, sg, uyari)
    govde += _b_rejim(rs, uyari)
    govde += _b_kural(km, uyari)
    govde += _b_ogrenme(oz, hafta, uyari)
    govde += _b_kalite(oz, hafta, uyari)
    govde += _b_saglik(oz, hafta, uyari)
    govde += ["## 8) Uyarılar / veri boşlukları", ""]
    govde += [f"- {u}" for u in uyari] or ["- Eksik girdi yok."]
    return _ADRES.sub("[gizli]", "\n".join(govde) + "\n")


# ---------------------------------------------------------------------------------------------------- zamanlama
def yazilacak_mi(simdi_ms: int, paylasim: Path) -> date | None:
    """Pazar ≥ 21:00 TSİ (ya da yakalama: Pazartesi 12:00 TSİ'ye kadar) ve o Pazartesi'nin dosyası henüz yoksa Pazartesi tarihi; değilse None."""
    t = datetime.fromtimestamp(simdi_ms / 1000, UTC).astimezone(TSI)
    pazar_gec = t.weekday() == 6 and t.hour >= 21
    pzt_erken = t.weekday() == 0 and t.hour < 12
    if not (pazar_gec or pzt_erken):
        return None
    pazar = rapor_tarihi(simdi_ms)
    return None if (Path(paylasim) / f"CT_HAFTA_{pazar.isoformat()}.md").exists() else pazar


RADAR_YENILE_MS = 3_600_000


def onyukle(motor: Any) -> None:
    """Radar okumasını (ağ) motor kilidi DIŞINDA yapar: `dakika()` kilidi almadan önce çağırır; sonuç `motor._radar_onbellek = (pazar, radar, ms)` (en çok saatte bir yenilenir).
    `yaz_gerekirse` (kilit altında) yalnız bu önbelleği okur. Yazım penceresi dışında hiçbir şey yapmaz. Hata çağırana çıkar (çağıran yutar)."""
    simdi = int(motor.saat_ms())
    pazar = yazilacak_mi(simdi, Path(motor.durum_dizin) / "paylasim")
    if pazar is None:
        return
    on = getattr(motor, "_radar_onbellek", None)
    if on and on[0] == pazar and simdi - on[2] < RADAR_YENILE_MS:
        return
    motor._radar_onbellek = (pazar, radar_oku(motor.rules, pazar), simdi)


def yaz_gerekirse(motor: Any, radar_okuyucu: Callable[[dict, date], list[dict] | None] | None = None) -> bool:
    """`gunluk_ozet.yaz_gerekirse` kancası (hata çağırana çıkar; çağıran yutar). Yazıldıysa True."""
    simdi = int(motor.saat_ms())
    paylasim = Path(motor.durum_dizin) / "paylasim"
    pazar = yazilacak_mi(simdi, paylasim)
    if pazar is None:
        return False
    on = getattr(motor, "_radar_onbellek", None)
    if radar_okuyucu is None and on and on[0] == pazar:                # dakika() kilit DIŞINDA önceden okudu: kilit altında ağ yok (denetim D1)
        radar = on[1]
    else:
        okuyucu = radar_okuyucu or radar_oku                           # önbellek yoksa (dakika() dışı çağrı) eski yol
        try:
            radar = okuyucu(motor.rules, pazar)
        except Exception:                                              # noqa: BLE001
            radar = None
    metin = olustur(paylasim, pazar, radar, gecmis_oku(Path(motor.durum_dizin)))
    _yaz_atomik(paylasim / f"CT_HAFTA_{pazar.isoformat()}.md", metin)
    _yaz_atomik(paylasim / SON, metin)
    return True
