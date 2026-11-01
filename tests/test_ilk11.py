"""İlk11 Faz 1 altın örnekleri: yüzdelik, puan, kadro ve PAPER kapıları."""
import pytest

from copytrade import ilk11


def test_yuzdelik_sira_eksik_ve_dusus_yonu():
    assert ilk11.yuzdelik({"b": 20, "a": 10, "c": None}) == {"a": 25, "b": 75, "c": 35}
    assert ilk11.yuzdelik({"a": 10, "b": 20}, dusuk_iyi=True) == {"a": 75, "b": 25}


def test_agirlikli_kaldirac_puani_ve_eksik_alan():
    ham = {"a": {"golge": 1}, "b": {"golge": 2}}
    scores = ilk11.agirlikli_puan(ham)
    # K1 rankleri 25/75, dokuz eksik alanın her biri 35; ağırlıkları varsayılanla normalize edilir.
    expected_a = (25 + sum(ilk11.KALDIRAC_AGIRLIKLARI[p] * 35 for p in ilk11.KALDIRAC_ALANLARI[1:])) / sum(ilk11.KALDIRAC_AGIRLIKLARI.values())
    assert scores["a"] == pytest.approx(expected_a)
    assert scores["b"] == pytest.approx(expected_a + 50 / sum(ilk11.KALDIRAC_AGIRLIKLARI.values()))


def test_golge_kirpma_buzulme_altin_ornek():
    got = ilk11.golge_ozeti([-2, 0.5, 4, None])
    assert got == {"n": 3, "ortalama": pytest.approx(5 / 6), "buzulmus_ortalama": pytest.approx(5 / 22)}
    assert ilk11.golge_ozeti([])["n"] == 0


def test_etre_kaldirac_alan_on_donusumleri_altin_ornekler():
    assert ilk11.hesap_puani(None) is None
    assert ilk11.hesap_puani(0) is None
    assert ilk11.hesap_puani(5_000) == 0
    assert ilk11.hesap_puani(130_000) == pytest.approx(0.5)
    assert ilk11.hesap_puani(1_000_000) == 1

    assert ilk11.siklik_puani(None) is None
    assert ilk11.siklik_puani(1) == 1
    assert ilk11.siklik_puani(3) == 1
    assert ilk11.siklik_puani(8) == pytest.approx(12 / 17)
    assert ilk11.siklik_puani(8, bot=8) == 0
    assert ilk11.siklik_puani(20) == 0

    assert ilk11.tutma_puani(None) is None
    assert ilk11.tutma_puani(1) == 0
    assert ilk11.tutma_puani(3) == pytest.approx(1 / 3)
    assert ilk11.tutma_puani(5) == 1
    assert ilk11.tutma_puani(30) == 1
    assert ilk11.tutma_puani(240) == pytest.approx(0.4)

    assert ilk11.kaldirac_puani(None) is None
    assert ilk11.kaldirac_puani(4) == 1
    assert ilk11.kaldirac_puani(14) == pytest.approx(0.5)
    assert ilk11.kaldirac_puani(24) == 0


def test_ilk_kadro_ham_alanlari_etre_on_donusumleriyle_puanlar():
    candidates = [
        {"id": "low", "uygun": True, "alanlar": {"hesap": 5_000, "siklik": 20, "tutma": 1, "kaldirac": 24}},
        {"id": "high", "uygun": True, "alanlar": {"hesap": 130_000, "siklik": 1, "tutma": 5, "kaldirac": 4}},
    ]
    result = ilk11.ilk_kadro(candidates)
    # Her alanın sıra dönüşümü yüksek traderı yukarıda tutar; diğer 6 alan iki tarafta eksik ve eşittir.
    assert result["kadro"][0]["id"] == "high"


def test_en_iyi_50_kararli_esitlik_ve_kapasite():
    rows = [{"id": f"{i:02}", "uygun": True, "alanlar": {"golge": i}, "form_puani": i,
             "kapi_puani": i, "gecerli_gozlem_suresi": i} for i in range(55)]
    rows += [{"id": "uygun-degil", "uygun": False, "alanlar": {"golge": 999}}]
    out = ilk11.ilk_kadro(rows)
    assert out["secim_adedi"] == 50
    assert len(out["kadro"]) == 50
    assert [sum(r["grup"] == group for r in out["kadro"]) for group in ("ilk11", "yedek11", "paf")] == [11, 11, 28]
    assert "54" in {r["id"] for r in out["kadro"]}
    assert "00" not in {r["id"] for r in out["kadro"]}
    again = ilk11.ilk_kadro(rows)
    assert out == again
    with pytest.raises(ValueError, match="50"):
        ilk11.ilk_kadro(rows, kapasite=49)


def test_esit_puan_tie_break_form_gecmis_sure_id():
    rows = [{"id": "b", "uygun": True, "alanlar": {}, "form_puani": 1, "kapi_puani": 9, "gecerli_gozlem_suresi": 9},
            {"id": "a", "uygun": True, "alanlar": {}, "form_puani": 2, "kapi_puani": 1, "gecerli_gozlem_suresi": 1}]
    out = ilk11.ilk_kadro(rows)
    assert [r["id"] for r in out["kadro"]] == ["a", "b"]


def test_paper_terfi_kapisi_son_alti_gecerli_ve_en_iyi_haric():
    paper = [{"gecerli": True, "sonuc": x} for x in (0.1, 0.1, 0.1, 0.1, -0.1, 0.2)]
    gate = ilk11.yedekten_terfi_kapisi(paper)
    assert gate["gecti"] is True
    assert gate["toplam"] == pytest.approx(0.5)  # oran: 0,1 = %10; kazanma oranı kesir olarak 5/6
    assert gate["kazanma_orani"] == pytest.approx(5 / 6)
    assert ilk11.yedekten_terfi_kapisi(paper[:-1])["n_gecerli"] == 5
    # En iyi işlem çıkarılınca toplam 0 olmalı, bu nedenle geçemez.
    assert ilk11.yedekten_terfi_kapisi([{"gecerli": True, "sonuc": x} for x in (-0.1, -0.1, -0.1, -0.1, -0.1, 0.6)])["gecti"] is False
    # Geçersiz satır son altı hesabına girmez.
    assert ilk11.yedekten_terfi_kapisi(paper + [{"gecerli": False, "sonuc": 100}])["toplam"] == pytest.approx(0.5)


def test_pazar_60_40_eylemsizlik_ve_yalniz_plan():
    rows = [
        {"id": "inactive", "grup": "ilk11", "form_puani": 70, "bu_pazar_aktif": False, "onceki_pazar_aktif": False},
        {"id": "low", "grup": "yedek11", "form_puani": 30,
         "bu_pazar_gecerli": True, "bu_pazar_aktif": True, "onceki_pazar_aktif": True},
        {"id": "high", "grup": "yedek11", "form_puani": 60, "bu_pazar_aktif": True, "onceki_pazar_aktif": True,
         "bu_pazar_gecerli": True,
         "paper_sonuclari": [{"gecerli": True, "sonuc": x} for x in (0.1, 0.1, 0.1, 0.1, -0.1, 0.2)]},
        {"id": "paf", "grup": "paf", "form_puani": 60, "bu_pazar_aktif": True, "bu_pazar_gecerli": True},
    ]
    plan = ilk11.pazar_gecis(rows, "2026-11-01")
    assert plan["mod"] == "PAPER" and plan["emir_uretildi"] is False and plan["kadro_yazildi"] is False
    assert {m["id"]: m["sonra"] for m in plan["degisiklik_plani"]} == {"inactive": "yedek11", "low": "paf", "high": "ilk11", "paf": "yedek11"}
    # Tek hareketsiz Pazar düşürmez; eksik form/aktivite belirsiz olarak raporlanır.
    plan2 = ilk11.pazar_gecis([{**rows[0], "onceki_pazar_aktif": True}, {"id": "unknown", "grup": "ilk11"}], "2026-11-01")
    assert not plan2["degisiklik_plani"]
    assert any("eksik" in n["neden"] for n in plan2["aciklamalar"])
    assert not ilk11.pazar_gecis([{"id": "edge", "grup": "yedek11", "form_puani": 40,
                                   "bu_pazar_aktif": True, "onceki_pazar_aktif": True}], "2026-11-01")["degisiklik_plani"]


def test_kadro_tavan_asimi_reddedilir():
    rows = [{"id": str(i), "grup": "paf"} for i in range(51)]
    with pytest.raises(ValueError, match="50"):
        ilk11.pazar_gecis(rows, "2026-11-01")


def test_pazar_tek_snapshot_low_downgrade_and_adjacent_tier_only():
    low_rows = [
        {"id": "f", "grup": "ilk11", "form_puani": 39, "bu_pazar_gecerli": True},
        {"id": "r", "grup": "yedek11", "form_puani": 39, "bu_pazar_gecerli": True},
        {"id": "p", "grup": "paf", "form_puani": 39, "bu_pazar_gecerli": True},
    ]
    out = ilk11.pazar_gecis(low_rows, "2026-11-08")
    assert {m["id"]: (m["once"], m["sonra"]) for m in out["degisiklik_plani"]} == {
        "f": ("ilk11", "yedek11"), "r": ("yedek11", "paf"), "p": ("paf", "kadrodisi")}

    # PAF only fills a reserve vacancy; candidates tie-break by form, gate score, duration, then id.
    promoted = ilk11.pazar_gecis([
        {"id": "reserve", "grup": "yedek11", "form_puani": 39, "bu_pazar_gecerli": True},
        *[{"id": f"occupied-{i}", "grup": "yedek11", "form_puani": 50, "bu_pazar_gecerli": True}
          for i in range(10)],
        {"id": "paf-z", "grup": "paf", "form_puani": 70, "kapi_puani": 5, "gecerli_gozlem_suresi": 4,
         "bu_pazar_gecerli": True},
        {"id": "paf-a", "grup": "paf", "form_puani": 70, "kapi_puani": 5, "gecerli_gozlem_suresi": 4,
         "bu_pazar_gecerli": True},
    ], "2026-11-08")
    moves = {m["id"]: m for m in promoted["degisiklik_plani"]}
    assert moves["paf-a"]["sonra"] == "yedek11"
    assert promoted["grup_sayilari_plan"] == {"ilk11": 0, "yedek11": 11, "paf": 2}


def test_iki_pazar_hareketsizlik_her_kademede_yalniz_bir_alt():
    rows = [{"id": f"i-{i}", "grup": "ilk11", "bu_pazar_aktif": i != 0,
             "onceki_pazar_aktif": i != 0} for i in range(11)]
    rows += [{"id": f"y-{i}", "grup": "yedek11", "bu_pazar_aktif": i != 0,
              "onceki_pazar_aktif": i != 0} for i in range(11)]
    rows += [{"id": f"p-{i}", "grup": "paf", "bu_pazar_aktif": i != 0,
              "onceki_pazar_aktif": i != 0} for i in range(28)]
    out = ilk11.pazar_gecis(rows, "2026-11-15")
    moves = {m["id"]: (m["once"], m["sonra"]) for m in out["degisiklik_plani"]}
    assert moves["i-0"] == ("ilk11", "yedek11")
    assert moves["y-0"] == ("yedek11", "paf")
    assert moves["p-0"] == ("paf", "kadrodisi")
    assert out["grup_sayilari_plan"] == {"ilk11": 10, "yedek11": 11, "paf": 28}
