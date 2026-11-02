"""Arşiv kesinti alarmı: eşik sınırları (12 saat), hiç başarılı koşu yok, rapora yazılan satır, iş akışı sözleşmesi."""
import json
from datetime import UTC, datetime
from pathlib import Path

from copytrade import arsiv_alarm, haftalik_rapor
from copytrade.kurallar import load_rules

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[1]


def kosu(saat_once, sonuc):
    from datetime import timedelta
    return {"conclusion": sonuc, "updated_at": (NOW - timedelta(hours=saat_once)).isoformat().replace("+00:00", "Z")}


def test_yaml_esigi_12_saat():
    assert load_rules()["arsiv_kesinti_saat"] == 12


def test_esik_sinirlari_tam_12_saat_alarm_degil_12_saat_1_dk_alarm():
    assert arsiv_alarm.kesinti([kosu(12, "success")], NOW, 12)["alarm"] is False
    assert arsiv_alarm.kesinti([kosu(12.02, "success")], NOW, 12)["alarm"] is True
    assert arsiv_alarm.kesinti([kosu(11.9, "success"), kosu(0.2, "failure")], NOW, 12)["alarm"] is False      # son başarı yeni; tek başarısız koşu alarm değil


def test_art_arda_basarisiz_koşular_sayilir_ve_en_son_basari_esas_alinir():
    o = arsiv_alarm.kesinti([kosu(30, "success"), kosu(14, "success"), kosu(13, "failure"), kosu(1, "failure"), kosu(0.5, "timed_out")], NOW, 12)
    assert o["alarm"] is True and o["ardisik_basarisiz"] == 3 and o["kesinti_saat"] == 14.0


def test_hic_basarili_kosu_yoksa_alarm_ve_bos_liste():
    assert arsiv_alarm.kesinti([kosu(1, "failure")], NOW, 12) | {} == arsiv_alarm.kesinti([kosu(1, "failure")], NOW, 12) and arsiv_alarm.kesinti([kosu(1, "failure")], NOW, 12)["alarm"] is True
    assert arsiv_alarm.kesinti([], NOW, 12)["alarm"] is True and "hiç başarılı koşu yok" in arsiv_alarm.mesaj(arsiv_alarm.kesinti([], NOW, 12))


def test_cikis_kodu_alarmda_1_bilgi_kipinde_0(tmp_path):
    from datetime import timedelta
    eski = {"workflow_runs": [{"conclusion": "success", "updated_at": (datetime.now(UTC) - timedelta(hours=20)).isoformat()}]}
    (tmp_path / "r.json").write_text(json.dumps(eski))
    assert arsiv_alarm.main(["--runs", str(tmp_path / "r.json")]) == 1
    assert arsiv_alarm.main(["--runs", str(tmp_path / "r.json"), "--bilgi", "--yaz", str(tmp_path / "o.json")]) == 0
    assert json.loads((tmp_path / "o.json").read_text())["alarm"] is True


def test_haftalik_rapor_arsiv_kesintisini_yazar(tmp_path):
    (tmp_path / "s.json").write_text(json.dumps({"secim_surumu": "v1.3", "kapi_tarihi": "2026-10-28", "adresler": {}}))
    (tmp_path / "k.json").write_text(json.dumps(arsiv_alarm.kesinti([kosu(20, "success"), kosu(1, "failure")], NOW, 12)))
    haftalik_rapor.main(["--secim", str(tmp_path / "s.json"), "--tarih", "2026-11-05", "--cikti", str(tmp_path / "r"), "--arsiv-kesinti", str(tmp_path / "k.json")])
    metin = (tmp_path / "r/haftalik_2026-11-05.md").read_text()
    assert "## Arşiv kesintisi" in metin and "🔴 **ALARM**" in metin and "20.0 saat önce" in metin and "1 başarısız koşu" in metin
