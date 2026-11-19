"""Kadro seçimi x gerçek kopya PnL (`ct.secim_gercek.v1`): Spearman + permütasyon (elle doğrulanan altın örnek), takma ad, dosya çıktısı, yayım betikleri. Yalnız bilgi; ağsız."""
from __future__ import annotations

import json
from pathlib import Path

from copytrade.canli import secim_gercek as sg
from copytrade.canli.ogrenme_adaptor import takma_ad
from tests.test_canli_motor import kur

ROOT = Path(__file__).resolve().parent.parent
GUN_MS = 86_400_000
T0 = 1_800_000_000_000
G0 = sg._gun(T0)


def _e(adres, pnl, ucret, ms=T0, durum="dolu"):
    return {"olay": "emir", "adres": adres, "durum": durum, "pnl_usd": pnl, "ucret": ucret, "zaman_ms": ms}


ADR = ["0x" + c * 40 for c in "abcd"]
KAYIT = [_e(ADR[0], 10.0, 1.0), _e(ADR[1], 5.0, 0.0), _e(ADR[2], -1.0, 0.0), _e(ADR[3], -2.0, 1.0),
         _e(ADR[0], 0.0, 0.0, durum="red"), _e("0x" + "e" * 40, 99.0, 0.0)]          # red sayılmaz; kadro dışı trader elenir
GECMIS = {G0: {"form": dict(zip(ADR, [80.0, 70.0, 60.0, 50.0], strict=True)), "ilk11_n": 4, "yedek_n": 6}}


def test_spearman_el_ile():
    assert sg.spearman([4, 3, 2, 1], [9, 5, -1, -3]) == 1.0
    assert abs(sg.spearman([1, 2, 3, 4], [9, 5, -1, -3]) + 1.0) < 1e-12
    assert sg.spearman([1, 2, 3], [5, 5, 5]) is None
    assert abs(sg.spearman([1, 2, 3, 4], [1, 2, 2, 5]) - 0.9486832980505138) < 1e-9      # eşit sıralar [1,2.5,2.5,4]


def test_altin_gun_net_pnl_ve_tam_permutasyon():
    pg = sg.gunluk_pnl(KAYIT)
    assert pg[G0][ADR[0]]["net"] == 9.0 and pg[G0][ADR[3]]["net"] == -3.0 and pg[G0][ADR[0]]["n"] == 1
    h = sg.hesapla(pg, GECMIS)
    g = h["gunler"][0]
    assert g["durum"] == "tamam" and g["kopyalanan_n"] == 4 and g["rho"] == 1.0 and g["yontem"] == "tam"
    assert g["p"] == round(1 / 24, 4)                                # 4! = 24 permütasyondan yalnız kimlik rho=1
    assert g["toplam_net_pnl"] == 10.0 and g["yedek_n"] == 6
    assert h["toplu"]["gun_n"] == 1 and h["toplu"]["rho_ort"] == 1.0


def test_ters_sira_rho_eksi_bir_p_bir():
    ters = {G0: {"form": dict(zip(ADR, [50.0, 60.0, 70.0, 80.0], strict=True)), "ilk11_n": 4, "yedek_n": 0}}
    g = sg.hesapla(sg.gunluk_pnl(KAYIT), ters)["gunler"][0]
    assert g["rho"] == -1.0 and g["p"] == 1.0


def test_az_trader_ve_kadro_yok_atlanir():
    h = sg.hesapla(sg.gunluk_pnl(KAYIT[:2]), GECMIS)
    assert h["gunler"][0]["durum"] == "az_trader" and h["toplu"] == {"durum": "yok", "gun_n": 0}
    assert sg.hesapla(sg.gunluk_pnl(KAYIT), {})["gunler"] == []
    assert sg.hesapla(sg.gunluk_pnl([_e(a, 1.0, 0.0, ms=T0 - GUN_MS) for a in ADR]), GECMIS)["gunler"] == []   # önceki kadro yok


def test_ornek_yontemi_tohumlu_ve_tekrarlanabilir():
    form = [float(i) for i in range(10)]
    pnl = [float((i * 7) % 10) for i in range(10)]
    a, b = sg.gun_testi(form, pnl, 20270115), sg.gun_testi(form, pnl, 20270115)
    assert a == b and a["yontem"] == "ornek" and 0 < a["p"] <= 1


def test_takma_ad_ve_cikti_adres_icermez():
    v = sg.olustur(KAYIT, GECMIS, T0 + 1000)
    s = json.dumps(v, ensure_ascii=False)
    assert v["sema"] == "ct.secim_gercek.v1" and v["proje"] == "CT"
    assert "0x" not in s and takma_ad(ADR[0]) in s
    assert "# CT" in sg.markdown(v) and "| " in sg.markdown(v)
    assert "veri yok" in sg.markdown(sg.olustur([], {}, T0))


def test_kadro_kaydet_ve_durum_yaz_dosyalari_yazar(tmp_path):
    m, hl, saat, _ = kur(tmp_path)
    m.baslat()
    kadro = {"satirlar": [{"adres": ADR[0], "katman": "ilk11", "form": 70.5}, {"adres": ADR[1], "katman": "yedek", "form": 60.0}]}
    sg.kadro_kaydet(m, kadro, T0)
    assert sg.gecmis_oku(m.durum_dizin)[G0] == {"form": {ADR[0]: 70.5, ADR[1]: 60.0}, "ilk11_n": 1, "yedek_n": 1}
    m.durum_yaz()
    d = tmp_path / "durum" / "paylasim"
    v = json.loads((d / "secim_gercek_v1.json").read_text(encoding="utf-8"))
    assert v["sema"] == "ct.secim_gercek.v1" and (d / "secim_gercek_v1.md").read_text(encoding="utf-8").startswith("# CT")


def test_yayim_betikleri_dosyalari_kopyalar():
    for yol in (".github/scripts/canli_yayimla.sh", "deploy/sanal_yayimla.sh"):
        s = (ROOT / yol).read_text(encoding="utf-8")
        assert "secim_gercek_v1.json" in s and "secim_gercek_v1.md" in s
