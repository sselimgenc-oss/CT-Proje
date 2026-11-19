# Kaynak: sselimgenc-oss/SG-Github-AB-proje trader/tests/paket/test_ortak_ogrenme_121_timeout.py @ f6221cb (içe aktarma yolu CT'ye uyarlandı)
"""1.2.1 regresyonu: varsayilan urllib istemcisi (baglanti, okuma) demetiyle gercekten istek atabilmeli."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import copytrade.ortak_ogrenme as ortak_ogrenme
from copytrade.ortak_ogrenme import telegram_cekirdek as TC


class _H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(n)
        body = json.dumps({"ok": True, "result": [{"update_id": 7}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def sunucu(monkeypatch):
    srv = HTTPServer(("127.0.0.1", 0), _H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    monkeypatch.setattr(TC, "API", f"http://127.0.0.1:{srv.server_address[1]}")
    yield
    srv.shutdown()


def test_surum():
    assert ortak_ogrenme.SURUM == "1.2.1"


@pytest.mark.parametrize("to", [(5, 10), [5, 40], 7, 7.5, None])
def test_default_http_post_demet_ve_sayi(sunucu, to):
    st, body = TC.default_http_post(f"{TC.API}/botX/getMe", json={}, timeout=to)
    assert st == 200 and body["ok"] is True


def test_varsayilan_istemci_get_updates_calisir(sunucu):
    c = TC.TelegramClient("123:abc")          # http_post verilmez -> varsayilan urllib yolu
    assert c.get_updates(None, timeout=1) == [{"update_id": 7}]


def test_urllib_timeout_cevirimi():
    assert TC._urllib_timeout((5, 40)) == 40.0
    assert TC._urllib_timeout((None, 3)) == 3.0
    assert TC._urllib_timeout(9) == 9 and TC._urllib_timeout(None) is None
