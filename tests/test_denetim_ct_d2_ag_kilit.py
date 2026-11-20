"""R3-4: dakika() içinde haber_adimi / rejim_adimi (ağ: requests, 5-15 sn) `self._lock` ALTINDA çalışır; olay_isle (kapanış dahil) aynı kilidi bekler (motor.py:2648, 2669)."""
import threading
import pytest
from copytrade.canli import haber, rejim, motor as mt
from tests.test_canli_motor import kur


@pytest.fixture(autouse=True)
def _m():
    yield
    mt.MASKE.clear()


def _baska_thread_kilit_alabilir(m) -> bool:
    sonuc = []
    def f():
        ok = m._lock.acquire(blocking=False)
        if ok:
            m._lock.release()
        sonuc.append(ok)
    t = threading.Thread(target=f); t.start(); t.join()
    return sonuc[0]


@pytest.mark.parametrize("modul,ad,kural", [(haber, "_getir_json", {"haber_aktif": True, "duygu_kaynak_url": "http://x/"}),
                                            (rejim, "_getir_varsayilan", {"rejim_kaynak_url": "http://x/"})])
def test_ag_cagrisi_kilit_disinda_olmali(tmp_path, monkeypatch, modul, ad, kural):
    m, hl, saat, _ = kur(tmp_path, kurallar=kural)
    m.baslat()
    gozlem = []
    monkeypatch.setattr(modul, ad, lambda url: gozlem.append(_baska_thread_kilit_alabilir(m)) or {})
    m.dakika()
    assert gozlem, "ağ fonksiyonu çağrılmadı"
    assert all(gozlem), "ağ okuması motor kilidi tutulurken yapıldı"
