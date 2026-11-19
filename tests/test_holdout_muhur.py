"""Holdout mührü: append-only manifest, değişiklik tespiti, kullanım kaydı. Ağsız (yerel dosyalar; git yok)."""
import copy
import json

import pytest

from copytrade import holdout_muhur as H

BAS = "2026-11-20"


def dosyalar(**k):
    return {(t, d): v for (t, d), v in k.items()}


def test_muhur_yalniz_holdout_sonrasi_ve_listedeki_dosyalar():
    m0 = H.bos_manifest(BAS)
    d = {("2026-11-19", "isabet.json"): b"eski", ("2026-11-20", "havuz_ilk.json"): b"h", ("2026-11-20", "kadro_ilk.json"): b"k", ("2026-11-20", "kadro.json"): b"gun-ici"}
    m1, r = H.muhurla(m0, d, "2026-11-21")
    assert [(g["tarih"], g["dosya"]) for g in m1["muhurler"]] == [("2026-11-20", "havuz_ilk.json"), ("2026-11-20", "kadro_ilk.json")]
    assert r["atlanan"] == 2 and m0["muhurler"] == []           # girdi değişmez
    assert m1["muhurler"][0]["sha256"] == H.sha256_hex(b"h")      # altın: bilinen SHA-256 (boş olmayan baytın özeti)
    assert H.sha256_hex(b"") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert H.zincir_sorunlari(m1) == []


def test_ayni_dosya_tekrar_muhurlenmez_degisen_ihlal_olur():
    m1, _ = H.muhurla(H.bos_manifest(BAS), {("2026-11-20", "isabet.json"): b"v1"}, "2026-11-27")
    m2, r2 = H.muhurla(m1, {("2026-11-20", "isabet.json"): b"v1"}, "2026-11-28")
    assert m2 == m1 and r2["yeni"] == [] and r2["ihlal"] == []
    m3, r3 = H.muhurla(m2, {("2026-11-20", "isabet.json"): b"v2-DEGISTI"}, "2026-11-29")
    assert r3["ihlal"] == ["2026-11-20/isabet.json"]
    assert len(m3["muhurler"]) == 1 and m3["muhurler"][0]["sha256"] == H.sha256_hex(b"v1")     # mühür ezilmez
    assert m3["ihlaller"][0]["gelen_sha256"] == H.sha256_hex(b"v2-DEGISTI")
    m4, r4 = H.muhurla(m3, {("2026-11-20", "isabet.json"): b"v2-DEGISTI"}, "2026-11-30")        # aynı ihlal ikinci kez yazılmaz
    assert len(m4["ihlaller"]) == 1 and r4["ihlal"] == []
    assert H.ekleme_mi(m1, m4) and H.zincir_sorunlari(m4) == []


def test_dogrula_degisen_eksik_ve_saklama_disi():
    m, _ = H.muhurla(H.bos_manifest(BAS), {("2026-11-20", "havuz_ilk.json"): b"a", ("2026-11-21", "kadro_ilk.json"): b"b", ("2026-11-22", "isabet.json"): b"c"}, "2026-11-22")
    depo = {("2026-11-20", "havuz_ilk.json"): b"a", ("2026-11-21", "kadro_ilk.json"): b"b-oynandi"}      # 3. dosya yok
    oku = lambda t, d: depo.get((t, d))                                                              # noqa: E731
    s = H.dogrula(m, oku, "2026-11-23")
    assert not s["tamam"] and s["degisen"] == ["2026-11-21/kadro_ilk.json"] and s["eksik"] == ["2026-11-22/isabet.json"]
    # 90 günden eski eksik dosya = saklama süresi (radar_yayimla.sh siler) → ihlal değil
    s2 = H.dogrula(m, lambda t, d: None, "2027-03-10")
    assert s2["eksik"] == [] and len(s2["saklama_disi"]) == 3 and s2["tamam"]
    tam = H.dogrula(m, lambda t, d: {"a": b"a", "b": b"b", "c": b"c"}[chr(97 + ["2026-11-20", "2026-11-21", "2026-11-22"].index(t))], "2026-11-23")
    assert tam["tamam"] and tam["kontrol"] == 3


def test_zincir_manifest_elle_duzenlenirse_yakalanir():
    m, _ = H.muhurla(H.bos_manifest(BAS), {("2026-11-20", "isabet.json"): b"x", ("2026-11-21", "isabet.json"): b"y"}, "2026-11-22")
    kotu = copy.deepcopy(m)
    kotu["muhurler"][0]["sha256"] = H.sha256_hex(b"sahte")        # hash'i değiştirip dosyayı uydurma
    assert any("muhurler[0]" in x for x in H.zincir_sorunlari(kotu))
    silinmis = copy.deepcopy(m)
    del silinmis["muhurler"][0]                                    # kaydı silme
    assert H.zincir_sorunlari(silinmis)
    assert not H.ekleme_mi(m, silinmis) and not H.ekleme_mi(m, kotu)
    ters = copy.deepcopy(m)
    ters["muhurler"].reverse()
    assert H.zincir_sorunlari(ters)


def test_append_only_ekleme_mi():
    m1, _ = H.muhurla(H.bos_manifest(BAS), {("2026-11-20", "isabet.json"): b"x"}, "2026-11-21")
    m2, _ = H.muhurla(m1, {("2026-11-21", "isabet.json"): b"y"}, "2026-11-22")
    assert H.ekleme_mi(m1, m2) and not H.ekleme_mi(m2, m1)
    degisik_bas = {**m2, "holdout_bas": "2026-01-01"}
    assert not H.ekleme_mi(m1, degisik_bas)


def test_kullanim_bir_kez_tekrar_isaretli():
    m = H.bos_manifest(BAS)
    m1 = H.kullanim_kaydet(m, "2026-12-01", "ml_filtre_v1", "ilk deneme")
    assert m1["kullanim_sayisi"] == 1 and m1["kullanim"][0]["tekrar"] is False and m["kullanim"] == []
    with pytest.raises(ValueError, match="zaten kullanıldı"):
        H.kullanim_kaydet(m1, "2026-12-05", "ml_filtre_v1")
    m2 = H.kullanim_kaydet(m1, "2026-12-05", "ml_filtre_v1", "ikinci bakış", tekrar=True)
    assert m2["kullanim_sayisi"] == 2 and m2["kullanim"][1]["tekrar"] is True and H.zincir_sorunlari(m2) == [] and H.ekleme_mi(m1, m2)
    with pytest.raises(ValueError):
        H.kullanim_kaydet(m, "2026-12-05", "  ")
    bozuk = {**m2, "kullanim_sayisi": 5}
    assert any("kullanim_sayisi" in x for x in H.zincir_sorunlari(bozuk))
    farkli = H.kullanim_kaydet(m1, "2026-12-06", "baska_amac")
    assert farkli["kullanim_sayisi"] == 2 and farkli["kullanim"][1]["tekrar"] is False


def test_cli_muhurla_dogrula_ve_kullanim(tmp_path, monkeypatch, capsys):
    kok = tmp_path / "radar"
    (kok / "2026-11-20").mkdir(parents=True)
    (kok / "2026-11-20" / "havuz_ilk.json").write_bytes(b"{}")
    (kok / "2026-11-19").mkdir()
    (kok / "2026-11-19" / "isabet.json").write_bytes(b"{}")      # holdout öncesi
    man = kok / "holdout" / "manifest.json"
    ortak = ["--kok", str(kok), "--manifest", str(man), "--bugun", "2026-11-21"]
    assert H.main(["muhurla", *ortak, "--kullanim-amac", "deneme", "--kullanim-not", "n"]) == 0
    m = json.loads(man.read_text(encoding="utf-8"))
    assert m["holdout_bas"] == BAS and len(m["muhurler"]) == 1 and m["kullanim_sayisi"] == 1
    assert H.main(["dogrula", *ortak]) == 0
    # aynı amaç tekrar: kayıt eklenmez, çıkış 0, ::error:: görünür
    assert H.main(["muhurla", *ortak, "--kullanim-amac", "deneme"]) == 0
    assert "REDDEDİLDİ" in capsys.readouterr().err
    assert json.loads(man.read_text(encoding="utf-8"))["kullanim_sayisi"] == 1
    # dosyayı değiştir: dogrula 1; muhurla ihlali kaydeder, mührü ezmez
    (kok / "2026-11-20" / "havuz_ilk.json").write_bytes(b'{"oynandi": 1}')
    assert H.main(["dogrula", *ortak]) == 1
    assert H.main(["muhurla", *ortak]) == 0
    m2 = json.loads(man.read_text(encoding="utf-8"))
    assert len(m2["ihlaller"]) == 1 and m2["muhurler"] == m["muhurler"]
    assert "HOLDOUT İHLALİ" in capsys.readouterr().err


def test_kullanim_dosyasi_idempotent_ve_tekrar_reddi():
    metin = "# başlık\n\n2026-12-01 | ml_v1 | ilk bakış\n2026-12-09 | ml_v1 | ikinci | tekrar\n2026-12-10 | baska\n"
    satirlar = H.kullanim_satirlari(metin)
    assert satirlar == [("2026-12-01", "ml_v1", "ilk bakış", False), ("2026-12-09", "ml_v1", "ikinci", True), ("2026-12-10", "baska", "", False)]
    m, red = H.kullanim_isle(H.bos_manifest(BAS), satirlar)
    assert red == [] and m["kullanim_sayisi"] == 3 and m["kullanim"][1]["tekrar"] is True
    m2, red2 = H.kullanim_isle(m, satirlar)                      # her koşu dosyayı yeniden okur: yeni kayıt yok
    assert m2 == m and red2 == []
    m3, red3 = H.kullanim_isle(m, [("2026-12-20", "ml_v1", "işaretsiz tekrar", False)])
    assert m3 == m and len(red3) == 1
    with pytest.raises(ValueError):
        H.kullanim_satirlari("bozuk satir")
