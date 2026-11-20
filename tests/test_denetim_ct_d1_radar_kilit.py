"""R5-1: hafta paketi radar HTTP isteği motor kilidi (_lock) altında yapılıyor (dakika() adımları `with self._lock` içinde)."""
from datetime import UTC, datetime

from copytrade.canli import hafta_paketi as hp
from tests.test_gunluk_ozet import _motor


def test_radar_ag_istegi_motor_kilidi_disinda(tmp_path, monkeypatch):
    m, saat = _motor(tmp_path)
    saat.ms = int(datetime(2026, 11, 22, 18, 30, tzinfo=UTC).timestamp() * 1000)   # Pazar 21:30 TSİ
    m._gunluk_ozet_yazim = None
    sahipli = []
    monkeypatch.setattr(hp, "radar_oku", lambda rules, bitis, **k: sahipli.append(m._lock._is_owned()) or [])
    m.dakika()
    assert sahipli, "radar_oku çağrılmadı (test düzeneği)"
    assert sahipli == [False], f"radar_oku motor kilidi ALTINDA çağrıldı: {sahipli}"
