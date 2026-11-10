"""F05: sanal IOC kayıtları ile aynı penceredeki v5 oynatmasının salt okunur mutabakatı.

Kullanım: python -m copytrade.mutabakat_raporu --bas-ms UTC_MS --bit-ms UTC_MS
    --json rapor.json --md rapor.md [--kayit-dizin yerel/kayit]
Varsayılan kayıt kaynağı origin/canli-durum:kayit/*.jsonl'dir. Çıktı dosyaları
yalnız belirtilen yerel yollara yazılır; veri dalı değiştirilmez.
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from copytrade import kopya_v3, radar_tarama
from copytrade.canli.gercek_sanal_karsilastir import kayit_oku
from copytrade.kurallar import load_rules
from copytrade.olcut import perp_fills


def _gunler(bas: int, bit: int):
    gun = datetime.fromtimestamp(bas / 1000, UTC).date()
    son = datetime.fromtimestamp((bit - 1) / 1000, UTC).date()
    while gun <= son:
        yield gun
        gun += timedelta(days=1)


def dal_kaydi(bas: int, bit: int) -> list[dict]:
    """Takip edilen canli-durum dalından UTC gün dosyalarını git show ile okur."""
    satirlar = []
    for gun in _gunler(bas, bit):
        s = subprocess.run(["git", "show", f"origin/canli-durum:kayit/{gun}.jsonl"], capture_output=True, text=True, check=False)
        if s.returncode != 0:
            continue
        satirlar.extend(json.loads(x) for x in s.stdout.splitlines() if x.strip())
    if not satirlar:
        raise ValueError("canli-durum kayıtları bulunamadı; önce dalı fetch edin")
    return satirlar


def _sayi(x: Any) -> float | None:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def raporla(kayitlar: list[dict], oynatmalar: dict[str, dict], bas: int, bit: int, rules: dict | None = None) -> dict:
    """Oynatmalar: adres → {sonuc: kopya_v5 sonucu, yurutme: Baglam.son_girdi, dolumlar}.

    `net_kz_*` yalnız gerçekleşen işlem netidir; açık K/Z ve funding hariçtir.
    Kayıt kayması dolum fiyatına zaten dahildir, netten ikinci kez düşülmez.
    """
    rules = rules or load_rules()
    kasa = float(rules["canli_kasa_usd"])
    taker, kayma = float(rules["maliyet_taker"]), float(rules["maliyet_kayma"])
    adresler = sorted({k["adres"] for k in kayitlar if k.get("adres") and k.get("olay") in ("emir", "emir_yok")
                      and bas <= int(k.get("trader_dolum_ms") or k.get("zaman_ms") or 0) < bit} | set(oynatmalar))
    uyeler = {}
    for adres in adresler:
        satirlar = [k for k in kayitlar if k.get("adres") == adres and k.get("kip", "sanal") == "sanal"
                    and k.get("olay") in ("emir", "emir_yok") and bas <= int(k.get("trader_dolum_ms") or k.get("zaman_ms") or 0) < bit]
        emirler = [k for k in satirlar if k["olay"] == "emir"]
        atlandi = sum(k["olay"] == "emir_yok" for k in satirlar) + sum(k.get("durum") in ("dolmadi", "red") for k in emirler)
        dolan = [k for k in emirler if (_sayi(k.get("usd_dolan")) or 0) > 0]
        fiyatlar = []
        oynatma = oynatmalar.get(adres, {})
        girdi = oynatma.get("yurutme") or {}
        dolum_anahtar = {(str(f["coin"]), int(f["time"])) for f in oynatma.get("dolumlar", [])}
        for k in dolan:
            coin, zaman = str(k.get("coin")), k.get("trader_dolum_ms")
            if zaman is None or (coin, int(zaman)) not in dolum_anahtar:
                continue
            hedef = kopya_v3.hedef_ms(int(zaman), int(rules["radar_kopya_gecikme_dk"]))
            px = _sayi(girdi.get(coin, {}).get(hedef))
            canli_px = _sayi(k.get("dolum_px"))
            if px and canli_px:
                fiyatlar.append((canli_px - px) / px * (1 if k.get("yon") == "B" else -1))
        canli_ucret = sum(_sayi(k.get("ucret")) or 0 for k in dolan)
        canli_kayma = sum((_sayi(k.get("kayma_trader")) or 0) * (_sayi(k.get("usd_dolan")) or 0) for k in dolan)
        # inceleme: `emir.pnl_usd` açılışta tanımı gereği null (VERI_SOZLESMESI §C); yalnız azaltma/kapanış dolumlarında eksikse ölçülemez
        pnl_tam = all(k.get("pnl_usd") is not None for k in dolan if k.get("eylem") in ("azalt", "kapat"))
        canli_net = sum((_sayi(k.get("pnl_usd")) or 0) for k in dolan) - canli_ucret if pnl_tam else None
        sonuc = oynatma.get("sonuc") or {}
        maliyet = _sayi(sonuc.get("maliyet"))
        toplam_oran = taker + kayma
        replay_ucret = maliyet * kasa * taker / toplam_oran if maliyet is not None and toplam_oran else None
        replay_kayma = maliyet * kasa * kayma / toplam_oran if maliyet is not None and toplam_oran else None
        replay_net = ((_sayi(sonuc.get("gerceklesen")) or 0) - (_sayi(sonuc.get("funding")) or 0)) * kasa if sonuc.get("gerceklesen") is not None else None
        uyeler[adres] = {"emir": len(emirler), "atlanan": atlandi, "dolan": len(dolan), "fiyat_fark_oran_ort": statistics.fmean(fiyatlar) if fiyatlar else None,
                         "fiyat_eslesme": len(fiyatlar), "canli_kayma_usd": canli_kayma, "oynatma_kayma_usd": replay_kayma,
                         "canli_ucret_usd": canli_ucret, "oynatma_ucret_usd": replay_ucret, "canli_net_kz_usd": canli_net,
                         "oynatma_net_kz_usd": replay_net, "net_kz_farki_usd": canli_net - replay_net if canli_net is not None and replay_net is not None else None}
    toplam = {k: sum(u[k] for u in uyeler.values()) for k in ("emir", "atlanan", "dolan", "fiyat_eslesme", "canli_kayma_usd", "canli_ucret_usd")}
    for ad in ("oynatma_kayma_usd", "oynatma_ucret_usd", "canli_net_kz_usd", "oynatma_net_kz_usd", "net_kz_farki_usd"):
        toplam[ad] = sum(u[ad] for u in uyeler.values()) if all(u[ad] is not None for u in uyeler.values()) else None
    fiyatlar = [(u["fiyat_fark_oran_ort"], u["fiyat_eslesme"]) for u in uyeler.values() if u["fiyat_eslesme"]]
    toplam["fiyat_fark_oran_ort"] = sum(v * n for v, n in fiyatlar) / sum(n for _, n in fiyatlar) if fiyatlar else None
    return {"bas_ms": bas, "bit_ms": bit, "net_kz_kapsami": "gerçekleşen işlem; açık K/Z ve funding hariç", "uyeler": uyeler, "toplam": toplam}


def markdown(rapor: dict) -> str:
    def fmt(x: float | None) -> str:
        return "—" if x is None else f"{x:+.4f}"

    satirlar = ["# F05 sanal IOC ↔ v5 mutabakatı", "", "Net K/Z: gerçekleşen işlem; açık K/Z ve funding hariç. Kayma fiyat farkına gömülüdür.", "",
                "| Trader | Emir | Atlanan | Fiyat eşleşme | Ort. fiyat farkı (bp) | Canlı/oynatma kayma $ | Canlı/oynatma ücret $ | Net K/Z farkı $ |",
                "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for ad, u in [*rapor["uyeler"].items(), ("TOPLAM", rapor["toplam"])]:
        fark = u["fiyat_fark_oran_ort"]
        satirlar.append(f"| {ad} | {u['emir']} | {u['atlanan']} | {u['fiyat_eslesme']} | {fmt(fark * 1e4 if fark is not None else None)} | "
                        f"{fmt(u['canli_kayma_usd'])} / {fmt(u['oynatma_kayma_usd'])} | {fmt(u['canli_ucret_usd'])} / {fmt(u['oynatma_ucret_usd'])} | {fmt(u['net_kz_farki_usd'])} |")
    return "\n".join(satirlar) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bas-ms", type=int, required=True)
    ap.add_argument("--bit-ms", type=int, required=True)
    ap.add_argument("--kayit-dizin", type=Path)
    ap.add_argument("--json", type=Path, required=True)
    ap.add_argument("--md", type=Path, required=True)
    a = ap.parse_args()
    if a.bas_ms >= a.bit_ms:
        ap.error("başlangıç bitişten önce olmalı")
    rules = load_rules()
    kayitlar = kayit_oku(a.kayit_dizin) if a.kayit_dizin else dal_kaydi(a.bas_ms, a.bit_ms)
    adresler = sorted({k["adres"] for k in kayitlar if k.get("adres") and k.get("olay") in ("emir", "emir_yok")
                      and a.bas_ms <= int(k.get("trader_dolum_ms") or k.get("zaman_ms") or 0) < a.bit_ms})
    if not adresler:
        raise ValueError("pencerede sanal emir veya emir_yok kaydı yok")
    client = radar_tarama.radar_istemcisi(rules=rules)
    baglam = radar_tarama.Baglam(client, a.bit_ms, a.bas_ms, rules)
    baglam.piyasa_oku()
    oynatmalar = {}
    for adres in adresler:
        dolumlar = perp_fills(client.fills(adres, a.bas_ms, end_ms=a.bit_ms))
        if not dolumlar:
            oynatmalar[adres] = {"sonuc": {"maliyet": 0.0, "gerceklesen": 0.0, "funding": 0.0}, "dolumlar": []}
            continue
        hesap = next((_sayi(k.get("trader_hesap_usd")) for k in kayitlar if k.get("adres") == adres and _sayi(k.get("trader_hesap_usd"))), 0.0)
        payda, _ = radar_tarama.payda_oku(client, adres, hesap or 0.0, a.bas_ms, a.bit_ms, rules)
        sonuc = baglam.kopya_oynat(dolumlar, payda)
        oynatmalar[adres] = {"sonuc": sonuc, "dolumlar": dolumlar, "yurutme": (baglam.son_girdi or {}).get("yurutme", {})}
    rapor = raporla(kayitlar, oynatmalar, a.bas_ms, a.bit_ms, rules)
    a.json.write_text(json.dumps(rapor, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    a.md.write_text(markdown(rapor), encoding="utf-8")


if __name__ == "__main__":
    main()
