"""Veri dalı ``son.json`` işaretçisi için altın örnek ve iş akışı bağlantısı."""
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("son_yaz", ROOT / ".github/scripts/son_yaz.py")
son_yaz = importlib.util.module_from_spec(spec)
spec.loader.exec_module(son_yaz)
SIMDI = datetime(2026, 10, 29, 6, 0, 0, tzinfo=UTC)


def test_son_json_anahtarlari_birlestirir(tmp_path):
    path = tmp_path / "son.json"
    son_yaz.yaz(path, {"kapi": "2026-10-28"}, SIMDI)
    assert json.loads(path.read_text()) == {"kapi": "2026-10-28", "uretildi": "2026-10-29T06:00:00Z"}
    son_yaz.yaz(path, {"secim": "2026-10-28-v1.3"}, SIMDI)                                      # kapı anahtarı korunur
    assert json.loads(path.read_text()) == {"kapi": "2026-10-28", "secim": "2026-10-28-v1.3", "uretildi": "2026-10-29T06:00:00Z"}
    son_yaz.yaz(path, {"kapi": "2026-10-29"}, SIMDI)                                            # yenisi eskinin üzerine yazar
    assert json.loads(path.read_text())["kapi"] == "2026-10-29" and json.loads(path.read_text())["secim"] == "2026-10-28-v1.3"


def test_son_json_cli(tmp_path):
    path = tmp_path / "son.json"
    son_yaz.main(["son_yaz.py", str(path), "secim", "2026-10-30-v1.3"])
    assert json.loads(path.read_text())["secim"] == "2026-10-30-v1.3"
