"""Sistem sağlık kontrolü (copytrade/saglik.py): elle verilmiş durumlar → beklenen bulgular (altın örnekler); canlı sayfa zamanı; Telegram alarm kuralı; iş akışı güvenliği."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from copytrade import saglik as s

ROOT = Path(__file__).resolve().parents[1]
SIMDI = 1_800_000_000_000
DK, SA = 60_000, 3_600_000


def ozet(**kw):
    d = {"yazildi_ms": SIMDI - 5 * DK, "dur": False, "kapanis_eksik": 0, "telegram_hata": 0, "dinleyici": {"kopma": 1, "kapanis_atlanan": 0, "gecikme_60sn_ustu": 0}}
    d.update(kw)
    return d


def kadro(**kw):
    d = {"kosu_ms": SIMDI - 6 * SA, "gecti_sayisi": 14, "saha_n": 11, "satirlar": [{"katman": "ilk11"}] * 11}
    d.update(kw)
    return d


def kodlar(b):
    return {x.kod for x in b}


def test_saglikli_sistem_bulgu_yok():
    b = s.kontrol(SIMDI, ozet(), kadro(), pano_ms=SIMDI - 10 * DK, canli_pano_ms=SIMDI - 20 * DK, canli_pano_ulasildi=True)
    assert b == [] and s.durum(b) == "SAGLIKLI" and "sağlıklı" in s.ozet_metin(b)


def test_vardiya_yasi_esikleri_20dk_normal_40dk_uyari_90dk_kritik():
    assert s.kontrol(SIMDI, ozet(yazildi_ms=SIMDI - 20 * DK), kadro()) == []
    u = s.kontrol(SIMDI, ozet(yazildi_ms=SIMDI - 40 * DK), kadro())
    assert kodlar(u) == {"vardiya_gecikti"} and s.durum(u) == "UYARI"
    k = s.kontrol(SIMDI, ozet(yazildi_ms=SIMDI - 90 * DK), kadro())
    assert kodlar(k) == {"vardiya_durdu"} and s.durum(k) == "KRITIK"


def test_ozet_yok_zaman_yok_kadro_yok():
    assert kodlar(s.kontrol(SIMDI, None, kadro())) == {"ozet_yok"} and s.durum(s.kontrol(SIMDI, None, kadro())) == "KRITIK"
    assert kodlar(s.kontrol(SIMDI, {"dur": False}, kadro())) == {"ozet_zaman_yok"}
    assert kodlar(s.kontrol(SIMDI, ozet(), None)) == {"kadro_yok"}


def test_kapanis_eksik_dur_telegram_kopma_kritik_uyari_bilgi():
    b = s.kontrol(SIMDI, ozet(kapanis_eksik=2, dur=True, telegram_hata=7, dinleyici={"kopma": 6, "kapanis_atlanan": 1, "gecikme_60sn_ustu": 3}), kadro())
    assert kodlar(b) == {"kapanis_eksik", "motor_dur", "telegram_hata", "kopma", "kapanis_atlanan", "gecikme_60"} and s.durum(b) == "KRITIK"
    assert s.kontrol(SIMDI, ozet(dinleyici={"gecikme_60sn_ustu": 3}), kadro())[0].seviye == "BILGI" and s.durum(s.kontrol(SIMDI, ozet(dinleyici={"gecikme_60sn_ustu": 3}), kadro())) == "SAGLIKLI"   # bilgi sağlıklı sayılır
    assert s.ozet_metin(b).splitlines()[0].startswith("🚨")                                         # kritik önce


def test_radar_yasi_gecti_araligi_kadro_eksik():
    assert kodlar(s.kontrol(SIMDI, ozet(), kadro(kosu_ms=SIMDI - 31 * SA))) == {"radar_gecikti"}
    assert kodlar(s.kontrol(SIMDI, ozet(), kadro(kosu_ms=SIMDI - 55 * SA))) == {"radar_durdu"}
    assert kodlar(s.kontrol(SIMDI, ozet(), kadro(gecti_sayisi=7))) == {"gecti_aralik_disi"} and kodlar(s.kontrol(SIMDI, ozet(), kadro(gecti_sayisi=21))) == {"gecti_aralik_disi"}
    assert s.kontrol(SIMDI, ozet(), kadro(gecti_sayisi=11)) == [] and s.kontrol(SIMDI, ozet(), kadro(gecti_sayisi=20)) == []                         # sınırlar dahil
    assert kodlar(s.kontrol(SIMDI, ozet(), kadro(satirlar=[{"katman": "ilk11"}] * 9))) == {"kadro_eksik"}
    b = s.kontrol(SIMDI, ozet(), kadro(gecti_sayisi=8))                                                                                      # K‑43: 11'den az = UYARI (KRİTİK değil)
    assert kodlar(b) == {"kadro_11den_az"} and s.durum(b) == "UYARI"


def test_pano_ve_cloudflare():
    assert kodlar(s.kontrol(SIMDI, ozet(), kadro(), pano_ms=SIMDI - 46 * DK)) == {"pano_bayat"} and s.kontrol(SIMDI, ozet(), kadro(), pano_ms=SIMDI - 44 * DK) == []
    assert kodlar(s.kontrol(SIMDI, ozet(), kadro(), canli_pano_ulasildi=False)) == {"pano_ulasilmiyor"}
    assert kodlar(s.kontrol(SIMDI, ozet(), kadro(), canli_pano_ms=SIMDI - 100 * DK, canli_pano_ulasildi=True)) == {"pano_cf_bayat"}
    assert kodlar(s.kontrol(SIMDI, ozet(), kadro(), canli_pano_ms=None, canli_pano_ulasildi=True)) == {"pano_cf_isaret_yok"}      # eski/yanlış sayfa (zaman işareti yok)


def test_canli_sayfa_zamani_okunur():
    assert s.canli_sayfa_ms('<div id="bayat" data-ms="1793900000000" class="uy" style="display:none">') == 1793900000000
    assert s.canli_sayfa_ms("<html>Hyperliquid Perps Pano — Terminal</html>") is None


def test_pano_ozet_sekmesinde_saglik_kutusu_var():
    from copytrade.canli import pano
    html = pano.html_olustur({"kasa_usd": 1000.0, "ozsermaye_usd": 1000.0, "yazildi_ms": SIMDI - 2 * DK, "vardiya": "v", "kip": "sanal", "dur": False}, {}, {}, [], [], SIMDI, kadro=kadro(satirlar=[], saha_n=0))
    assert "Sağlık" in html and "sorun yok" in html
    html2 = pano.html_olustur({"kasa_usd": 1000.0, "ozsermaye_usd": 1000.0, "yazildi_ms": SIMDI - 120 * DK, "vardiya": "v", "kip": "sanal", "dur": False}, {}, {}, [], [], SIMDI, kadro=kadro(satirlar=[], saha_n=0))
    assert "acil" in html2 and "veri yazmıyor" in html2


def test_is_akisi_salt_okur_push_yok_hata_orulmez():
    metin = (ROOT / ".github/workflows/saglik.yml").read_text(encoding="utf-8")
    wf = yaml.safe_load(metin)
    assert wf["permissions"] == {"contents": "read"} and wf["defaults"]["run"]["shell"] == "bash -euo pipefail {0}"
    assert "git push" not in metin and not re.search(r"\|\|\s*true\b|continue-on-error", metin)
    assert "copytrade.saglik" in metin and "--telegram" in metin and "sg-pano" in metin
    assert not re.search(r"R2_|aws s3|wrangler|AWS_|API_TOKEN", metin)                              # yalnız Telegram secret'ları; Cloudflare/depo anahtarı yok


def test_telegram_alarm_kurali_kritik_her_kosuda_uyari_3_saatte_bir(monkeypatch, capsys):
    gonderilen: list[str] = []

    class T:
        acik = True

        def gonder(self, m):
            gonderilen.append(m)
            return True

    from copytrade.canli import telegram as tg
    monkeypatch.setattr(tg, "Telegram", T)
    monkeypatch.setattr(s, "_git_oku", lambda dal, yol: None)           # ozet/kadro yok → KRITIK
    monkeypatch.setattr(s, "_git_zaman_ms", lambda dal, yol: None)
    assert s.main(["--telegram"]) == 2 and len(gonderilen) == 1 and "ALARM" in gonderilen[0]
    # UYARI: yalnız saat % 3 == 0'da
    import time as _t
    for saat, beklenen in ((10, 0), (9, 1)):
        gonderilen.clear()
        monkeypatch.setattr(s, "_git_oku", lambda dal, yol: ('{"dur": false}' if yol.endswith("ozet.json") else '{"kosu_ms": %d, "gecti_sayisi": 14, "saha_n": 11, "satirlar": []}' % int(_t.time() * 1000)))
        monkeypatch.setattr(_t, "time", lambda saat=saat: float(saat * 3600 + 86400 * 20000))
        s.main(["--telegram"])
        assert len(gonderilen) == beklenen
