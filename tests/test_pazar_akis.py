from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from copytrade.pazar_akis import pazar_akis_plani


IST = ZoneInfo("Europe/Istanbul")


def dt(value):
    return datetime.fromisoformat(value).replace(tzinfo=IST)


def test_ilk_deneme_cumartesiden_yaklasan_pazar_13e_bekler():
    out = pazar_akis_plani(now=dt("2026-11-07T12:00:00"), deneme_sayisi=0)
    assert out["eylem"] == "bekle"
    assert out["zaman"] == "2026-11-08T13:00:00+03:00"
    assert out["deneme_no"] == 1


def test_ilk_deneme_pazar_13_oncesi_ve_sonrasi():
    before = pazar_akis_plani(now=dt("2026-11-08T12:59:59"), deneme_sayisi=0)
    due = pazar_akis_plani(now=dt("2026-11-08T13:00:00"), deneme_sayisi=0,
                           snapshot_id="snapshot-a")
    after = pazar_akis_plani(now=dt("2026-11-08T13:00:01"), deneme_sayisi=0,
                            snapshot_id="snapshot-a")
    assert before["eylem"] == "bekle"
    assert due["eylem"] == after["eylem"] == "calistir"
    assert due["snapshot_id"] == "snapshot-a"


def test_hafta_ici_yeni_akis_gelecek_pazari_bekler():
    out = pazar_akis_plani(now=dt("2026-11-09T09:00:00"), deneme_sayisi=0)
    assert out["eylem"] == "bekle"
    assert out["zaman"] == "2026-11-15T13:00:00+03:00"


def test_baslangicta_zaman_geldiyse_snapshot_hazirlanmasini_ister():
    out = pazar_akis_plani(now=dt("2026-11-08T13:00:00"), deneme_sayisi=0)
    assert out["eylem"] == "snapshot_hazirla"
    assert out["snapshot_id"] is None
    assert out["snapshot_as_of"] == "2026-11-08T13:00:00+03:00"


def test_saniyelik_gecikmede_snapshot_as_of_sabit_pazar_13():
    out = pazar_akis_plani(now=dt("2026-11-08T13:00:01"), deneme_sayisi=0)
    assert out["eylem"] == "snapshot_hazirla"
    assert out["zaman"] == "2026-11-08T13:00:00+03:00"
    assert out["snapshot_as_of"] == "2026-11-08T13:00:00+03:00"


def test_basarisizliktan_sonra_iki_saatlik_araligi_bekler_ve_dolunca_tekrarlar():
    failed_at = dt("2026-11-08T13:00:00")
    base = {"deneme_sayisi": 1, "snapshot_id": "frozen-1",
            "retry_snapshot_id": "frozen-1", "son_basarisiz_at": failed_at}
    early = pazar_akis_plani(now=failed_at + timedelta(hours=1, minutes=59), **base)
    due = pazar_akis_plani(now=failed_at + timedelta(hours=2), **base)
    late = pazar_akis_plani(now=failed_at + timedelta(hours=7), **base)
    assert early["eylem"] == "bekle"
    assert early["zaman"] == "2026-11-08T15:00:00+03:00"
    assert due["eylem"] == late["eylem"] == "yeniden_dene"
    assert due["deneme_no"] == late["deneme_no"] == 2
    assert late["snapshot_id"] == "frozen-1"


def test_retry_farkli_snapshot_kimligini_reddeder():
    out = pazar_akis_plani(
        now=dt("2026-11-08T15:00:00"), deneme_sayisi=1,
        snapshot_id="frozen-1", retry_snapshot_id="new-data",
        son_basarisiz_at=dt("2026-11-08T13:00:00"),
    )
    assert out["eylem"] == "reddet"
    assert "eşleşmiyor" in out["neden"]


def test_retry_snapshot_kimligi_eksikse_reddeder():
    out = pazar_akis_plani(
        now=dt("2026-11-08T15:00:00"), deneme_sayisi=1,
        snapshot_id="frozen-1", son_basarisiz_at=dt("2026-11-08T13:00:00"),
    )
    assert out["eylem"] == "reddet"


def test_basarili_akis_tekrar_denemez():
    out = pazar_akis_plani(
        now=dt("2026-11-08T15:00:00"), deneme_sayisi=1,
        snapshot_id="frozen-1", retry_snapshot_id="frozen-1",
        son_basarisiz_at=dt("2026-11-08T13:00:00"), basarili=True,
    )
    assert out["eylem"] == "tamamla"
    assert out["deneme_no"] == 1


def test_naive_zaman_ve_gecersiz_deneme_sayisi_hata_verir():
    with pytest.raises(ValueError, match="timezone"):
        pazar_akis_plani(now=datetime(2026, 11, 8, 13), deneme_sayisi=0)
    with pytest.raises(ValueError, match="tam sayı"):
        pazar_akis_plani(now=dt("2026-11-08T13:00:00"), deneme_sayisi=-1)


def test_utc_input_istanbul_saatine_dogru_donusturulur():
    out = pazar_akis_plani(
        now=datetime(2026, 11, 8, 10, 0, tzinfo=timezone.utc),
        deneme_sayisi=0, snapshot_id="frozen-utc",
    )
    assert out["eylem"] == "calistir"
    assert out["zaman"] == "2026-11-08T13:00:00+03:00"
