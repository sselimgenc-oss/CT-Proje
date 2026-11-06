"""06.11 vardiyası `ModuleNotFoundError: numpy` ile BAŞLAMADI: canlı vardiya iş akışı yalnız websockets/PyYAML/requests kurar.
Bu test, vardiyada çalışan modüllerin numpy/pandas/scipy OLMADAN içe aktarılabildiğini doğrular (CI'da bunlar kurulu olduğu için ayrı süreçte engellenir)."""
import subprocess
import sys

import pytest

MODULLER = ["copytrade.canli.motor", "copytrade.canli.pano", "copytrade.canli.telegram", "copytrade.canli.risk", "copytrade.saglik", "copytrade.coin_sinif"]


@pytest.mark.parametrize("modul", MODULLER)
def test_canli_vardiya_modulleri_numpy_olmadan_ice_aktarilir(modul):
    kod = f"import sys\nfor k in ('numpy', 'pandas', 'scipy'):\n    sys.modules[k] = None\nimport importlib\nimportlib.import_module({modul!r})\n"
    r = subprocess.run([sys.executable, "-c", kod], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-600:]
