"""Sistem sağlık kontrolü (copytrade/saglik.py): elle verilmiş durumlar → beklenen bulgular (altın örnekler); canlı sayfa zamanı; Telegram alarm kuralı; iş akışı güvenliği."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from copytrade import saglik as s

_GERCEK_OKU = s.vardiya_kosulari_oku

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


def test_g1_telegram_gonderimi_basarisizsa_cikis_2_ve_stderr(monkeypatch, capsys):
    class T:
        acik = True

        def gonder(self, m):
            return False

    from copytrade.canli import telegram as tg
    monkeypatch.setattr(tg, "Telegram", T)
    monkeypatch.setattr(s, "_git_oku", lambda dal, yol: ('{"dur": false}' if yol.endswith("ozet.json") else None))
    monkeypatch.setattr(s, "_git_zaman_ms", lambda dal, yol: None)
    assert s.main(["--telegram"]) == 2
    assert "gönderilemedi" in capsys.readouterr().err


def test_kayipsiz_kopma_yalniz_bilgi_kayipli_kopma_uyari():
    """07.11: vardiyada 8 kopma, 60 sn üstü gecikme 0, atlanan kapanış 0 → yeniden bağlandı, veri kaybı yok: BİLGİ (Telegram alarmı yok)."""
    b = s.kontrol(SIMDI, ozet(dinleyici={"kopma": 8, "kapanis_atlanan": 0, "gecikme_60sn_ustu": 0}), kadro())
    assert [(x.kod, x.seviye) for x in b] == [("kopma", "BILGI")] and "veri kaybı yok" in b[0].mesaj and s.durum(b) == "SAGLIKLI"
    b2 = s.kontrol(SIMDI, ozet(dinleyici={"kopma": 8, "kapanis_atlanan": 0, "gecikme_60sn_ustu": 2}), kadro())
    assert {x.kod: x.seviye for x in b2}["kopma"] == "UYARI" and s.durum(b2) == "UYARI"


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
    for saat, dakika, beklenen in ((10, 0, 0), (9, 0, 1), (9, 14, 1), (9, 20, 0), (9, 50, 0)):      # 07.11 hatası: 09:05/20/35/50 UTC dört kez gönderiliyordu → yalnız saatin ilk 15 dk'sı
        gonderilen.clear()
        monkeypatch.setattr(s, "_git_oku", lambda dal, yol: ('{"dur": false}' if yol.endswith("ozet.json") else '{"kosu_ms": %d, "gecti_sayisi": 14, "saha_n": 11, "satirlar": []}' % int(_t.time() * 1000)))
        monkeypatch.setattr(_t, "time", lambda saat=saat, dakika=dakika: float(saat * 3600 + dakika * 60 + 86400 * 20000))
        s.main(["--telegram"])
        assert len(gonderilen) == beklenen


# ---------------------------------------------------------------------------------------------- G2: kalıcı durum, kayıt olayları, vardiya koşusu, veri dalı yaşı
def kos(sonuc, durum="completed", no=1):
    return {"status": durum, "conclusion": sonuc, "run_number": no, "html_url": f"https://x/{no}"}


def test_kalici_kuyrukta_eksik_girdi_kritik_vardiya_sayaci_0_iken_bile():
    motor = {"kapanis_kuyrugu": {"0xab|BTC": {"eksik": True, "ms": SIMDI - 3 * SA}, "0xcd|ETH": {"eksik": False}}}
    b = s.kontrol(SIMDI, ozet(kapanis_eksik=0), kadro(), motor=motor)
    assert kodlar(b) == {"kapanis_kuyrugu_eksik"} and s.durum(b) == "KRITIK"
    assert "1 EKSİK" in b[0].mesaj and "3.0 saat" in b[0].mesaj and "BTC" in b[0].mesaj
    assert s.kontrol(SIMDI, ozet(), kadro(), motor={"kapanis_kuyrugu": {"0xcd|ETH": {"eksik": False}}}) == []
    assert kodlar(s.kontrol(SIMDI, ozet(kapanis_eksik=1), kadro(), motor=motor)) == {"kapanis_eksik", "kapanis_kuyrugu_eksik"}      # eski bulgu korunur


def test_risk_bayraklari_mutabakat_dur_gunluk_kayip_elle_dur():
    risk = {"dur": False, "acilis_durdu": {"mutabakat": True, "gunluk_kayip": True, "elle_dur": True, "kasa_siniri": False, "kapanis_eksik": False}}
    b = s.kontrol(SIMDI, ozet(), kadro(), risk=risk)
    assert {x.kod: x.seviye for x in b} == {"mutabakat_bayragi": "KRITIK", "gunluk_kayip": "UYARI", "elle_dur": "UYARI"}
    assert kodlar(s.kontrol(SIMDI, ozet(), kadro(), risk={"dur": True, "dur_neden": "zirve", "acilis_durdu": {}})) == {"risk_dur"}
    d = s.kontrol(SIMDI, ozet(), kadro(), risk={"dur": False, "acilis_durdu": {}}, dur_dosyasi=True)
    assert kodlar(d) == {"risk_dur"} and d[0].seviye == "KRITIK"
    assert s.kontrol(SIMDI, ozet(), kadro(), risk={"dur": False, "acilis_durdu": {"mutabakat": False}}, motor={"kapanis_kuyrugu": {}}) == []


def test_kayit_olaylari_son_2_saat_pencere():
    ol = [{"zaman_ms": SIMDI - 30 * DK, "olay": "vardiya_boslugu", "dk": 157.4}, {"zaman_ms": SIMDI - 10 * DK, "olay": "vardiya_baslamadi"},
          {"zaman_ms": SIMDI - 5 * DK, "olay": "kuyruk_tasti"}, {"zaman_ms": SIMDI - 3 * SA, "olay": "vardiya_boslugu", "dk": 99}, {"zaman_ms": SIMDI - 1 * DK, "olay": "emir"}]
    b = s.kontrol(SIMDI, ozet(), kadro(), olaylar=ol)
    assert {x.kod: x.seviye for x in b} == {"vardiya_boslugu": "KRITIK", "vardiya_baslamadi": "KRITIK", "kuyruk_tasti": "UYARI"}
    m = next(x.mesaj for x in b if x.kod == "vardiya_boslugu")
    assert "157.4 dk" in m and "1 kez" in m
    assert s.kontrol(SIMDI, ozet(), kadro(), olaylar=[ol[3]]) == [] and s.kontrol(SIMDI, ozet(), kadro(), olaylar=None) == []


def test_hata_sayaclari_kritik_vardiya_basina():
    b = s.kontrol(SIMDI, ozet(kayit_sayac={"adim_hata": 2, "olay_hata": 0, "defter_hata": 1, "emir": 50}), kadro())
    assert kodlar(b) == {"adim_hata", "defter_hata"} and s.durum(b) == "KRITIK"
    assert s.kontrol(SIMDI, ozet(kayit_sayac={"adim_hata": 0}), kadro()) == []


def test_vardiya_kosusu_failure_timed_out_kritik_cancelled_bilgi():
    assert kodlar(s.kontrol(SIMDI, ozet(), kadro(), vardiya_kosulari=[kos("failure")])) == {"vardiya_kosusu_basarisiz"}
    assert kodlar(s.kontrol(SIMDI, ozet(), kadro(), vardiya_kosulari=[kos("timed_out")])) == {"vardiya_kosusu_basarisiz"}
    c = s.kontrol(SIMDI, ozet(), kadro(), vardiya_kosulari=[kos("cancelled")])
    assert [(x.kod, x.seviye) for x in c] == [("vardiya_kosusu_iptal", "BILGI")] and s.durum(c) == "SAGLIKLI"          # adımsız/concurrency iptali sahte KRİTİK değil
    assert s.kontrol(SIMDI, ozet(), kadro(), vardiya_kosulari=[kos("success")]) == []
    assert s.kontrol(SIMDI, ozet(), kadro(), vardiya_kosulari=[kos(None, "in_progress"), kos("success", no=2)]) == []        # son TAMAMLANAN bakılır
    assert s.kontrol(SIMDI, ozet(), kadro(), vardiya_kosulari=[]) == [] and s.kontrol(SIMDI, ozet(), kadro(), vardiya_kosulari=None) == []   # ağ hatası: bulgu yok


def test_vardiya_kosulari_oku_ag_hatasinda_none():
    assert _GERCEK_OKU("http://127.0.0.1:1/yok", timeout=1) is None


def test_veri_dali_commit_yasi_esikleri_45_uyari_90_kritik():
    assert s.kontrol(SIMDI, ozet(), kadro(), veri_dali_commit_ms=SIMDI - 40 * DK) == []
    u = s.kontrol(SIMDI, ozet(), kadro(), veri_dali_commit_ms=SIMDI - 50 * DK)
    assert [(x.kod, x.seviye) for x in u] == [("veri_dali_bayat", "UYARI")]
    k = s.kontrol(SIMDI, ozet(), kadro(), veri_dali_commit_ms=SIMDI - 100 * DK)
    assert [(x.kod, x.seviye) for x in k] == [("veri_dali_durdu", "KRITIK")]
    assert s.kontrol(SIMDI, ozet(), kadro(), veri_dali_commit_ms=None) == []


def test_ozet_yokken_kalici_bulgular_yine_gorunur():
    assert {"ozet_yok", "mutabakat_bayragi"} <= kodlar(s.kontrol(SIMDI, None, kadro(), risk={"acilis_durdu": {"mutabakat": True}}))


@pytest.fixture(autouse=True)
def _hermetik_cli(monkeypatch):
    """G2: `main` artık git fetch / GitHub REST çağırır; testler ağa ve gerçek git'e dokunmaz (kendi monkeypatch'leri bunun üstüne yazar)."""
    for ad, deger in (("_git_fetch", True), ("_git_var", False), ("_git_son_commit_ms", None), ("kayit_olaylari", None), ("vardiya_kosulari_oku", None)):
        monkeypatch.setattr(s, ad, lambda *a, _d=deger, **k: _d)


def test_vardiya_kosusu_failure_sonrasi_calisan_kosu_bilgi_yoksa_kritik():
    # (a) failure + ardından in_progress / queued -> yalnız BİLGİ (veri bayat olsa bile)
    for durum in ("in_progress", "queued"):
        b = s.kontrol(SIMDI, ozet(), kadro(), vardiya_kosulari=[kos(None, durum, 18), kos("failure", no=17)], veri_dali_commit_ms=SIMDI - 100 * DK)
        assert [(x.kod, x.seviye) for x in b if x.kod.startswith("vardiya_kosusu")] == [("vardiya_kosusu_duzeldi", "BILGI")]
    # (b) failure + sonrası yok + veri bayat -> KRİTİK
    b = s.kontrol(SIMDI, ozet(), kadro(), vardiya_kosulari=[kos("failure", no=17)], veri_dali_commit_ms=SIMDI - 60 * DK)
    assert "vardiya_kosusu_basarisiz" in kodlar(b) and s.durum(b) == "KRITIK"
    # (c) failure sonra success -> bulgu yok
    assert s.kontrol(SIMDI, ozet(), kadro(), vardiya_kosulari=[kos("success", no=18), kos("failure", no=17)]) == []
    # failure + sonrası yok ama veri dalı taze -> BİLGİ
    b = s.kontrol(SIMDI, ozet(), kadro(), vardiya_kosulari=[kos("failure", no=17)], veri_dali_commit_ms=SIMDI - 5 * DK)
    assert s.durum(b) == "SAGLIKLI" and kodlar(b) == {"vardiya_kosusu_duzeldi"}


def test_vardiya_boslugu_sonrasi_vardiya_surerken_uyari_yoksa_kritik():
    ol = [{"zaman_ms": SIMDI - 40 * DK, "olay": "vardiya_boslugu", "dk": 157.4}]
    b = s.kontrol(SIMDI, ozet(yazildi_ms=SIMDI - 5 * DK), kadro(), olaylar=ol, veri_dali_commit_ms=SIMDI - 5 * DK)
    assert [(x.kod, x.seviye) for x in b] == [("vardiya_boslugu", "UYARI")]
    assert s.durum(s.kontrol(SIMDI, ozet(yazildi_ms=SIMDI - 50 * DK), kadro(), olaylar=ol, veri_dali_commit_ms=SIMDI - 5 * DK)) == "KRITIK"      # olaydan sonra yazım yok
    assert s.durum(s.kontrol(SIMDI, ozet(yazildi_ms=SIMDI - 5 * DK), kadro(), olaylar=ol, veri_dali_commit_ms=SIMDI - 60 * DK)) == "KRITIK"      # veri bayat


def test_v2_kadro_gecti_araligi_uygulanmaz():                                                 # K-60: D+ 5 kişi seçer; 8–20 uyarısı yanlış alarm olurdu
    d = kadro(gecti_sayisi=5, saha_n=5, satirlar=[{"katman": "ilk11"}] * 5, radar_surum="v2")
    assert s.kontrol(SIMDI, ozet(), d) == []
    eksik = kadro(gecti_sayisi=4, saha_n=5, satirlar=[{"katman": "ilk11"}] * 4, radar_surum="v2")
    assert kodlar(s.kontrol(SIMDI, ozet(), eksik)) == {"kadro_eksik"}
