"""Ortak öğrenme paketi (kopya, af68a02) temel testleri: kayıt gidiş-dönüş, işlem notu, ders yaşam döngüsü, fren/geri alma raporu. Ağsız, elle hesaplı."""
from datetime import datetime, timezone

import pytest

from copytrade.ortak_ogrenme import SURUM, ders, notlar
from copytrade.ortak_ogrenme.kayit import Aday, aday_from_dict, aday_to_dict, oku_jsonl, yaz_jsonl


def aday(i, ts, r, seans="weekend", kurulum="T_abc123", alindi=True, **kw):
    return Aday(id=f"a{i}", proje="CT", kurulum=kurulum, enstruman="BTC/USD", varlik_sinifi="kripto", yon="long", ts=ts, alindi=alindi, r=r, seans=seans, **kw)


def dt(g, s=12):
    return datetime(2027, 1, g, s, tzinfo=timezone.utc)


def test_surum_ve_kayit_gidis_donus(tmp_path):
    assert SURUM == "1.1.0"
    a = aday(1, dt(16), -2.0, ozellikler={"kaldirac": 3.0}, etiketler=("coin:BTC",), cikis={"exit_reason": "x"})
    assert aday_from_dict(aday_to_dict(a)) == a and aday_to_dict(a)["ts"] == "2027-01-16T12:00:00Z"
    yol = tmp_path / "a.jsonl"
    yaz_jsonl(yol, [a, aday(2, dt(17), 1.0)])
    assert [x.id for x in oku_jsonl(yol)] == ["a1", "a2"]


def test_kayit_dogrulama():
    with pytest.raises(ValueError):
        aday(1, datetime(2027, 1, 16), 1.0)                      # tz'siz
    with pytest.raises(ValueError):
        Aday(id="x", proje="CT", kurulum="k", enstruman="e", varlik_sinifi="kripto", yon="yan", ts=dt(16), alindi=True, r=1.0)
    with pytest.raises(ValueError):
        aday_from_dict({"id": "x"})


def test_not_yaz_kayipta_ders_etiketi_uretir():
    etiketler, metin = notlar.not_yaz(aday(1, dt(16), -2.0))     # hafta sonu + kayıp → seans_kapali dersi
    assert "sonuc:kayip" in etiketler and "ders:seans_kapali:T_abc123" in etiketler and "seans:weekend" in etiketler
    assert "\n" not in metin
    et2, _ = notlar.not_yaz(aday(2, dt(16), 2.0))                 # kazançta ders yok
    assert not any(t.startswith("ders:") for t in et2)
    with pytest.raises(ValueError):
        notlar.not_yaz(aday(3, dt(16), None))


def test_gece_adimi_alive_retired_ve_fren(tmp_path):
    yol = tmp_path / "ders.json"
    kid = "seans_kapali:T_abc123"
    nlar = [{"note_date": "2027-01-16", "tags": ["ders:" + kid]}]
    kayiplar = [aday(i, dt(17, i), -2.0) for i in range(1, 5)]    # doğumdan sonraki hafta sonu işlemleri: 4 × −2 R
    out = ders.gece_adimi(kayiplar, nlar, yol, "2027-01-19")
    assert out["born"] == [kid] and out["alive"] == [kid] and out["retired"] == []
    etki, n = ders.ders_etkisi(kayiplar, kid, "2027-01-16", datetime(2027, 1, 19, tzinfo=timezone.utc))
    assert (etki, n) == (8.0, 4) and ders.etkin_dersler(yol) == [kid]
    # uygulamadan sonra bu koşulda KAZANÇ: tek ders etkisi −4 ≤ −3 → geri al; toplam −4 > −10 → fren yok
    sonra = [*kayiplar, aday(9, dt(23), 4.0)]
    r = ders.fren_durumu(sonra, [kid], dt(20), datetime(2027, 1, 24, tzinfo=timezone.utc))
    assert r == {"toplam_etki": -4.0, "fren": False, "geri_al": [kid]}
    r2 = ders.fren_durumu([*sonra, aday(10, dt(23, 15), 7.0)], [kid], dt(20), datetime(2027, 1, 24, tzinfo=timezone.utc))
    assert r2["fren"] is True and r2["toplam_etki"] == -11.0
    # kazanç getiren koşul: ders emekli olur
    yol2 = tmp_path / "ders2.json"
    out2 = ders.gece_adimi([aday(1, dt(17), 3.0)], nlar, yol2, "2027-01-19")
    assert out2["retired"] == [kid]
