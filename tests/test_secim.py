"""Seçim v1.3 altın örnekleri (docs/GOREV_SECIM_V1.md, GOREV_SECIM_V13.md): 12 satırlık, elle hesaplanmış kapı tablosu → havuz / aday / oda / kontrol."""
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from copytrade import secim
from copytrade.izleme_motoru import load_list
from copytrade.kurallar import load_rules

RULES = load_rules()


def addr(name: str) -> str:
    return "0x" + name * 40


def row(name, tarz, net, genc=False, adim2="Geçti", **extra):
    delay = 30 if tarz == "intraday" else 120
    return {"address": addr(name), "tarz": tarz, "adim1": "Geçti", "adim2": adim2, "kapi_gecikme_dk": delay,
            f"gecikme_{delay}dk_net": net, "genc_aday": genc, "median_leverage": 1.5, "max_leverage": 4.0, "gecmis_gun": 400.0,
            "account_value": 1000.0, "hesap": "v1.1-test", **extra}


# intraday (gecikme 30 dk): a..g; swing (120 dk): 1..4 (hex hane '1'..'4'); x = adım 2 Kaldı (havuz dışı)
TABLE = pd.DataFrame([
    row("a", "intraday", 0.50),
    row("b", "intraday", 0.40, genc=True),
    row("c", "intraday", 0.30, iliskili_adresler=addr("a")),       # a ile bağlı, puanı düşük
    row("d", "intraday", 0.20),
    row("e", "intraday", 0.10),
    row("f", "intraday", -0.05),                                    # negatif puan: aday olamaz
    row("0", "intraday", None),                                     # puansız: havuzda, aday değil
    row("1", "swing", 0.60),
    row("2", "swing", 0.80, genc=True),
    row("3", "swing", 0.05),
    row("4", "swing", 0.02),
    row("9", "swing", 0.99, adim2="Kaldı"),                         # havuz dışı
])


def test_havuz_ve_puan():
    pool = secim.havuz(TABLE)
    assert len(pool) == 11 and addr("9") not in {r["address"] for r in pool}        # adım 2 Kaldı
    assert {r["address"]: r["puan"] for r in pool}[addr("0")] is None               # puansız satır havuzda
    assert {r["address"]: r["puan"] for r in pool}[addr("2")] == 0.80               # swing → 120 dk sütunu
    assert {r["address"]: r["puan"] for r in pool}[addr("a")] == 0.50               # intraday → 30 dk sütunu


def test_aday_gercek_kurallarla_yuvarla_yukari():
    # intraday pozitif 5 (a,b,c,d,e): ceil(5·0,15 = 0,75) = 1 → a;  swing pozitif 4: ceil(0,6) = 1 → 2 (en yüksek puan)
    candidates = secim.adaylar(secim.havuz(TABLE), RULES)
    assert [(r["address"], r["sira"]) for r in candidates] == [(addr("a"), 1), (addr("2"), 1)]


def test_aday_az_ise_oda_tum_aday_ve_kisa_uyarisi():
    candidates = secim.adaylar(secim.havuz(TABLE), RULES)
    room = secim.oda_sec(candidates, RULES)
    assert {r["address"] for r in room["oda"]} == {addr("a"), addr("2")} and room["kisa"] is True      # 2 < 10


def test_oda_kota_genc_oncelik_ve_iliskili_hesap():
    rules = {**RULES, "secim_aday_orani": 0.5, "secim_oda_max": 3, "secim_oda_min": 2}
    # intraday ceil(2,5)=3 → a,b,c;  swing ceil(2)=2 → 2,1  (aday 5)
    candidates = secim.adaylar(secim.havuz(TABLE), rules)
    assert [r["address"] for r in candidates] == [addr("a"), addr("b"), addr("c"), addr("2"), addr("1")]
    room = secim.oda_sec(candidates, rules)
    # c, a ile bağlı ve puanı düşük → elenir (not); uygun 4 (a, b, 2, 1), hedef min(3, 4) = 3
    assert room["notlar"] == {addr("c"): f"ilişkili hesap: {addr('a')[:6]} puanı daha yüksek, o kalır"}
    # kota (aday payı 3:2 → 1,8 / 1,2): taban 1 + 1; en büyük kalan intraday → intraday 2, swing 1
    assert room["kota"] == {"intraday": 2, "swing": 1}
    # swing kotası 1: genç olmayan 1 (0,60), genç 2 (0,80) → genç olmayan önce
    assert {r["address"] for r in room["oda"]} == {addr("a"), addr("b"), addr("1")}
    assert [r["address"] for r in room["oda"]] == [addr("1"), addr("a"), addr("b")]     # sıra: genç olmayanlar (puan ↓), sonra genç
    assert room["kisa"] is False                                                        # 3 ≥ secim_oda_min 2


def test_kotalar_en_buyuk_kalan():
    assert secim._kotalar({"intraday": 3, "swing": 2}, 4) == {"intraday": 2, "swing": 2}        # 2,4 / 1,6 → 2 + 1
    assert secim._kotalar({"intraday": 1, "swing": 1}, 3) == {"intraday": 2, "swing": 1}        # 1,5 / 1,5 eşit → tarz adı sırası
    assert secim._kotalar({"intraday": 0, "swing": 0}, 3) == {"intraday": 0, "swing": 0}


def pool_of(spec):
    """spec: {ad: (tarz, en_yuksek_kaldirac)} → havuz satırları (puan 0,1: kontrol puana bakmaz)."""
    return [{"address": addr(n), "tarz": t, "max_leverage": lev, "puan": 0.1} for n, (t, lev) in spec.items()]


# intraday a,b,c,d (en yüksek kaldıraç 1, 2, 8, 9) · swing 1,2,3,4 (1, 2, 8, 9); medyan (2 + 8) / 2 = 5 → alt = ≤ 5
KONTROL_HAVUZU = pool_of({"a": ("intraday", 1.0), "b": ("intraday", 2.0), "c": ("intraday", 8.0), "d": ("intraday", 9.0),
                          "1": ("swing", 1.0), "2": ("swing", 2.0), "3": ("swing", 8.0), "4": ("swing", 9.0)})


def test_havuz_statik_kosullari_kapi_ile_ayni():
    rows = [row("a", "intraday", 0.5),                                       # 1,5x / 4x: girer
            row("b", "intraday", 0.9, max_leverage=36.5),                    # en yüksek kaldıraç 36,5x > 10: girmez
            row("c", "intraday", 0.8, median_leverage=3.5),                  # medyan 3,5x > 3: girmez
            row("d", "swing", 0.7, kisa_islem_payi=0.30),                    # kısa işlem payı %30 > %25: girmez
            row("e", "swing", 0.6, kisa_islem_payi=0.25),                    # tam sınır: girer
            row("f", "swing", 0.5, median_leverage=3.0, max_leverage=10.0),  # tam sınır: girer
            row("0", "swing", 0.4, median_leverage=None),                    # kaldıraç bilinmiyor: kapıdaki gibi kalır
            row("1", "swing", 0.3, kisa_islem_payi=None)]                    # kısa işlem payı yok: kapıdaki gibi geçer
    got = {r["address"] for r in secim.havuz(pd.DataFrame(rows), RULES)}
    assert got == {addr("a"), addr("e"), addr("f"), addr("1")}
    assert RULES["kisa_islem_payi_max"] == 0.25 and RULES["kapi_max_medyan_kaldirac"] == 3.0 and RULES["kapi_max_kaldirac"] == 10.0



def test_havuz_eski_evren_satirlarini_almaz():
    # Kapı birleşimi önceki koşuların satırlarını da taşır; güncel evrende olmayanlar evren_disi=True (denetim B14).
    rows = [row("a", "intraday", 0.5, evren_disi=False), row("b", "intraday", 0.9, evren_disi=True),
            row("c", "swing", 0.7)]                                          # sütun yoksa (eski kapı tablosu) girer
    got = {r["address"] for r in secim.havuz(pd.DataFrame(rows), RULES)}
    assert got == {addr("a"), addr("c")}

def test_tohum_altin_deger():
    assert secim.tohum_dizgesi("v1.3", "2026-10-28") == "secim-v1.3-2026-10-28"
    assert secim.tohum("v1.3", "2026-10-28") == 0x532caf57ce210502 == 5993357995778573570       # printf ... | sha256sum, ilk 8 bayt


def test_kontrol_ayni_dilimden_odayla_ayrik():
    got = secim.kontrol_sec(KONTROL_HAVUZU, [addr("c"), addr("3")], "2026-10-28", "v1.3")
    assert got["esik"] == 5.0
    assert got["eslesme"] == {addr("c"): addr("d"), addr("3"): addr("4")}       # intraday/ust yalnız d, swing/ust yalnız 4 kaldı
    assert got["kontrol"] == [addr("4"), addr("d")] and got["eslesmeyen"] == []
    assert set(got["ikincil"]) == {addr(n) for n in "ab124d"} and not {addr("c"), addr("3")} & set(got["ikincil"])     # havuz − oda
    assert not {addr("c"), addr("3")} & set(got["kontrol"])


def test_kontrol_dilim_sirasi_hash_ve_bos_dilimde_ayni_tarz():
    # a, b (intraday/alt) odada → alt dilimde kontrol kalmadı → aynı tarzın üst dilimi (c, d); sha256(secim-v1.3-<kapı>-<adres>) sırası:
    # 2026-10-28: c 1694a28f < d d8b847df → a→c, b→d (adres sırasıyla);  2026-10-27: d 8b0d577b < c beab36eb → a→d, b→c
    first = secim.kontrol_sec(KONTROL_HAVUZU, [addr("a"), addr("b")], "2026-10-28", "v1.3")
    assert first["eslesme"] == {addr("a"): addr("c"), addr("b"): addr("d")}
    second = secim.kontrol_sec(KONTROL_HAVUZU, [addr("a"), addr("b")], "2026-10-27", "v1.3")
    assert second["eslesme"] == {addr("a"): addr("d"), addr("b"): addr("c")}                # farklı kapı tarihi → farklı eşleşme
    assert first == secim.kontrol_sec(KONTROL_HAVUZU, [addr("a"), addr("b")], "2026-10-28", "v1.3")      # aynı girdi → aynı çıktı
    mixed = secim.kontrol_sec(KONTROL_HAVUZU, [addr("a"), addr("c")], "2026-10-28", "v1.3")
    assert mixed["eslesme"] == {addr("a"): addr("b"), addr("c"): addr("d")}                 # a alt→b (alt), c üst→d (üst)


def test_kontrol_eslesemeyen_oda_uyesi_yazilir():
    got = secim.kontrol_sec(KONTROL_HAVUZU, [addr(n) for n in "abcd"], "2026-10-28", "v1.3")      # intraday'in tamamı odada
    assert got["kontrol"] == [] and got["eslesmeyen"] == [addr(n) for n in "abcd"]
    assert set(got["ikincil"]) == {addr(n) for n in "1234"}


def test_kontrol_puana_bakmaz_oda_disindaki_herkes_cikabilir():
    pool = [{**r, "puan": 0.1 * i} for i, r in enumerate(KONTROL_HAVUZU)]
    seen = set()
    for day in range(1, 29):
        seen |= set(secim.kontrol_sec(pool, [addr("c")], f"2026-10-{day:02d}", "v1.3")["kontrol"])
    assert addr("c") not in seen and seen <= {addr("a"), addr("b"), addr("d")}               # odadan asla; başka biri hep d (üst dilim)
    assert seen == {addr("d")}


def test_secim_kapi_tarihine_baglidir_secim_tarihine_degil():
    one = secim.sec(TABLE, "2026-10-28", [], [], RULES, kapi_tarihi="2026-10-27")
    again = secim.sec(TABLE, "2026-10-30", [], [], RULES, kapi_tarihi="2026-10-27")             # seçim yeniden koştu
    assert one["kontrol"] == again["kontrol"] and one["eslesme"] == again["eslesme"] and one["tohum_dizgesi"] == "secim-v1.3-2026-10-27"
    other = secim.sec(TABLE, "2026-10-28", [], [], RULES, kapi_tarihi="2026-10-29")
    assert other["tohum_dizgesi"] == "secim-v1.3-2026-10-29"


def test_secim_kimligi_ve_ikincil_kontrol():
    result = secim.sec(TABLE, "2026-10-28", [], [], RULES, kapi_tarihi="2026-10-27")
    assert result["secim_surumu"] == "v1.3" and result["kapi_tarihi"] == "2026-10-27" and RULES["secim_surumu"] == "v1.3"
    assert result["kurallar_sha256"] == hashlib.sha256((Path(secim.__file__).parent / "kurallar.yaml").read_bytes()).hexdigest()
    assert result["secim_sha256"] == hashlib.sha256(Path(secim.__file__).read_bytes()).hexdigest()
    oda = {a for a, e in result["adresler"].items() if "oda" in e["kollar"]}
    assert oda == {addr("a"), addr("2")} and not oda & set(result["kontrol"])                  # oda ↔ kontrol kesişimi boş
    assert set(result["ikincil_kontrol"]) == {r["address"] for r in secim.havuz(TABLE, RULES)} - oda and result["sayilar"]["ikincil_kontrol"] == 9
    assert result["dilim_tablosu"] == {"intraday/alt": {"oda": 1, "kontrol": 1, "havuz": 7}, "swing/alt": {"oda": 1, "kontrol": 1, "havuz": 4}}


def test_taban_30_gunluk_pnl():
    board = [{"ethAddress": addr("a"), "windowPerformances": [["day", {"pnl": "999"}], ["month", {"pnl": "100"}]]},
             {"ethAddress": addr("b"), "windowPerformances": [["month", {"pnl": "300"}]]},
             {"ethAddress": addr("c"), "windowPerformances": [["month", {"pnl": "-5"}]]}]
    assert secim.taban_sec(board, 2) == [addr("b"), addr("a")]


def test_sec_kol_onceligi_ve_ciktilar():
    board = [{"ethAddress": addr("a"), "windowPerformances": [["month", {"pnl": "9"}]]},
             {"ethAddress": addr("z"), "windowPerformances": [["month", {"pnl": "8"}]]}]
    result = secim.sec(TABLE, "2026-10-28", board, [addr("d"), addr("y")], RULES)
    assert result["sayilar"]["oda"] == 2 and result["sayilar"]["kontrol"] == 2 and result["sayilar"]["taban"] == 2   # N = oda sayısı
    entries = result["adresler"]
    assert entries[addr("a")]["kol"] == "oda" and set(entries[addr("a")]["kollar"]) >= {"oda", "aday", "havuz", "taban"}
    assert entries[addr("d")]["kol"] == "elle" and entries[addr("y")]["kol"] == "elle" and entries[addr("y")]["tarz"] is None
    assert entries[addr("z")]["kol"] == "taban" and entries[addr("z")]["puan"] is None
    assert entries[addr("2")]["genc_aday"] is True and entries[addr("2")]["hesap_surumu"] == "v1.1-test"
    assert addr("9") not in entries                                     # adım 2 Kaldı: hiçbir kolda yok
    text = secim.rapor(result, TABLE, {"hesap": "v1.1-test", "kapsam": 1.0, "durum": "tamam"})
    assert "oda 2 adres; en az 10" in text and "secim-v1.3-2026-10-28" in text and "| gecikme_30dk_net |" in text
    assert "geçmiş getiri sıralaması (adım 1–3 süzgeçli)" in text and "## Oda ↔ kontrol dilim dağılımı" in text and "| intraday/alt | 7 | 1 | 1 |" in text


def test_secim_ciktisi_golge_butunluk_bilgi_sutunlarini_korur():
    """Kapı tablosundaki bütün yeni bilgi alanları secim.json'a aynen taşınır; aday/oda kararını etkilemez."""
    table = TABLE.copy()
    fields = {"acik_pozisyon_sayisi": 2, "unrealized_end": -0.03, "mark_missing": 1,
              "acik_pozisyon_notional": 0.4, "en_iyi_islem_haric_getiri": 0.08,
              "median_holding_hours": 7.0, "gunluk_islem_sikligi": 1.5,
              "yonlu_dolum_sayisi": 10, "yonlu_dolum_iyi_orani": 0.4,
              "yonlu_dolum_kotu_orani": 0.5, "yonlu_dolum_ortalama_bp": 12.0}
    table.loc[table.address == addr("a"), list(fields)] = list(fields.values())
    entry = secim.sec(table, "2026-10-28", [], [], RULES)["adresler"][addr("a")]
    assert {"acik_pozisyon_sayisi": entry["acik_pozisyon_sayisi"], "unrealized_end": entry["unrealized_end"],
            "mark_missing": entry["mark_missing"], "acik_pozisyon_notional": entry["acik_pozisyon_notional"],
            "en_iyi_islem_haric_getiri": entry["en_iyi_islem_haric_getiri"], "medyan_tutma_saat": entry["medyan_tutma_saat"],
            "gunluk_islem_sikligi": entry["gunluk_islem_sikligi"], "yonlu_dolum_sayisi": entry["yonlu_dolum_sayisi"],
            "yonlu_dolum_iyi_orani": entry["yonlu_dolum_iyi_orani"], "yonlu_dolum_kotu_orani": entry["yonlu_dolum_kotu_orani"],
            "yonlu_dolum_ortalama_bp": entry["yonlu_dolum_ortalama_bp"]} == {
                "acik_pozisyon_sayisi": 2, "unrealized_end": -0.03, "mark_missing": 1,
                "acik_pozisyon_notional": 0.4, "en_iyi_islem_haric_getiri": 0.08,
                "medyan_tutma_saat": 7.0, "gunluk_islem_sikligi": 1.5,
                "yonlu_dolum_sayisi": 10, "yonlu_dolum_iyi_orani": 0.4,
                "yonlu_dolum_kotu_orani": 0.5, "yonlu_dolum_ortalama_bp": 12.0}


def test_izleme_listesi_mevcut_satirlari_korur_ve_dogrulanir(tmp_path: Path):
    result = secim.sec(TABLE, "2026-10-28", [], [addr("d")], RULES)
    existing = [{"id": "T1", "adres": addr("a"), "takma_ad": "aaaa", "durum": "izlemede", "t0": "2026-10-20", "tarz": "intraday"},
                {"id": "T2", "adres": addr("d"), "takma_ad": "dddd", "durum": "izlemede", "t0": "2026-10-20"}]
    rows = secim.izleme_listesi(result, existing, "2026-10-29")
    by = {r["adres"]: r for r in rows}
    # E5: listede zaten olan adres v1.3 kohortuna (oda) girince YENİ id ve t0 alır; eski t0'dan yeniden oynatma yok
    assert by[addr("a")]["id"] != "T1" and by[addr("a")]["t0"] == "2026-10-29" and by[addr("a")]["kol"] == "oda"
    assert "T1" not in {r["id"] for r in rows} and by[addr("a")]["secim"] == "v1.3@2026-10-28"                          # ITT etiketi seçim sürümüne bağlı
    assert by[addr("d")]["id"] == "T2" and by[addr("d")]["t0"] == "2026-10-20" and by[addr("d")]["kol"] == "elle"       # elle satır değişmez
    assert by[addr("2")]["t0"] == "2026-10-29" and by[addr("2")]["id"].startswith("O")
    path = tmp_path / "liste.yaml"
    secim.yaz_izleme_listesi(rows, path)
    loaded = load_list(path)                                      # izleme motorunun doğrulaması kabul eder
    assert len(loaded) == len(rows) and len({r["id"] for r in loaded}) == len(rows)
    assert secim.elle_liste(path) == [addr("d")]                  # elle kolu yeniden okunur; oda/kontrol okunmaz


def test_izleme_listesi_eski_secimi_sabit_referans_olarak_korur(tmp_path: Path):
    """Altın örnek: oda değişince eski üye aynı t0/id ile referans kolunda kalır."""
    result = secim.sec(TABLE, "2026-10-29", [], [], RULES, kapi_tarihi="2026-10-29")
    existing = [
        {"id": "O01", "adres": addr("f"), "takma_ad": "ffff", "durum": "izlemede", "t0": "2026-10-29",
         "secim": "v1.3@2026-10-28", "kol": "oda", "kollar": ["oda"]},
        {"id": "K01", "adres": addr("e"), "takma_ad": "eeee", "durum": "izlemede", "t0": "2026-10-29",
         "secim": "v1.3@2026-10-28", "kol": "kontrol", "kollar": ["kontrol"]},
    ]
    rows = secim.izleme_listesi(result, existing, "2026-10-29")
    by = {r["adres"]: r for r in rows}
    assert by[addr("f")]["id"] == "O01" and by[addr("f")]["t0"] == "2026-10-29"
    assert by[addr("f")]["kollar"] == ["referans_oda"]
    assert by[addr("e")]["kollar"] == ["referans_kontrol"]
    path = tmp_path / "liste.yaml"
    secim.yaz_izleme_listesi(rows, path)
    assert {r["kol"] for r in load_list(path)} >= {"referans_oda", "referans_kontrol"}


def test_tam_kosu_degilse_durur(tmp_path: Path):
    day = tmp_path / "kapi" / "2026-10-28"
    day.mkdir(parents=True)
    TABLE.to_csv(day / "sonuc.csv", index=False)
    (day / "durum.json").write_text(json.dumps({"durum": "tamam", "kapsam": 0.0067}), encoding="utf-8")
    with pytest.raises(SystemExit, match="tam koşu değil"):
        secim.main(["--root", str(tmp_path), "--output", str(tmp_path / "secim"), "--tarih", "2026-10-28", "--taban-dosyasi", str(tmp_path / "x")])
    (day / "durum.json").write_text(json.dumps({"durum": "tamam", "kapsam": 0.94}), encoding="utf-8")
    with pytest.raises(SystemExit, match="tam koşu değil"):                                   # 0,94 < 0,95 → dur
        secim.main(["--root", str(tmp_path), "--output", str(tmp_path / "secim"), "--tarih", "2026-10-28", "--taban-dosyasi", str(tmp_path / "x")])
    (day / "durum.json").write_text(json.dumps({"durum": "eksik", "kapsam": 1.0}), encoding="utf-8")
    with pytest.raises(SystemExit, match="tamam değil"):
        secim.main(["--root", str(tmp_path), "--output", str(tmp_path / "secim"), "--tarih", "2026-10-28"])
    (day / "durum.json").write_text(json.dumps({"durum": "tamam", "kapsam": 0.95, "hesap": "v1.1-test"}), encoding="utf-8")     # 0,95 → çalışır
    (tmp_path / "board.json").write_text("[]", encoding="utf-8")
    secim.main(["--root", str(tmp_path), "--output", str(tmp_path / "secim"), "--tarih", "2026-10-28", "--taban-dosyasi", str(tmp_path / "board.json"), "--bayraksiz"])
    published = json.loads((tmp_path / "secim/2026-10-28-v1.3/secim.json").read_text())
    assert published["sayilar"]["oda"] == 2 and published["kapi_tarihi"] == "2026-10-28"        # kapı tarihi = kapı klasörünün adı
    assert (tmp_path / "secim/2026-10-28-v1.3/RAPOR.md").exists()
    with pytest.raises(SystemExit, match="üzerine yazılmaz"):                                     # aynı sürüm + kapı tarihi: yeniden yayımlanmaz
        secim.main(["--root", str(tmp_path), "--output", str(tmp_path / "secim"), "--tarih", "2026-10-30", "--taban-dosyasi", str(tmp_path / "board.json")])
    before = (tmp_path / "secim/2026-10-28-v1.3/secim.json").read_text()
    with pytest.raises(SystemExit, match="üzerine yazılmaz"):
        secim.main(["--root", str(tmp_path), "--output", str(tmp_path / "secim"), "--tarih", "2026-10-28", "--taban-dosyasi", str(tmp_path / "board.json")])
    assert (tmp_path / "secim/2026-10-28-v1.3/secim.json").read_text() == before


def test_izleme_listesi_ayni_secim_yeniden_yazilirsa_id_ve_t0_degismez():
    result = secim.sec(TABLE, "2026-10-28", [], [], RULES, kapi_tarihi="2026-10-28")
    existing = [{"id": "T1", "adres": addr("a"), "takma_ad": "aaaa", "durum": "izlemede", "t0": "2026-10-20", "tarz": "intraday"}]
    first = secim.izleme_listesi(result, existing, "2026-10-29")
    again = secim.izleme_listesi(result, first, "2026-10-31")                      # aynı sürüm + kapı: idempotent
    assert {r["adres"]: (r["id"], r["t0"]) for r in again} == {r["adres"]: (r["id"], r["t0"]) for r in first}
    newer = secim.sec(TABLE, "2026-10-30", [], [], RULES, kapi_tarihi="2026-10-30")   # yeni seçim sürümü/kapı: yeniden etiketlenir
    third = secim.izleme_listesi(newer, again, "2026-11-02")
    by_old = {r["adres"]: r for r in again}
    by_new = {r["adres"]: r for r in third}
    assert by_new[addr("a")]["id"] != by_old[addr("a")]["id"] and by_new[addr("a")]["t0"] == "2026-11-02" and by_new[addr("a")]["secim"] == "v1.3@2026-10-30"
    assert by_old[addr("a")]["id"] not in {r["id"] for r in third}                  # eski id yeniden kullanılmaz (motor arşivi adres/t0 değişimini reddeder)

def test_bayrak_ayri_is_aday_kati_icin_secimi_degistirmez():
    result = secim.sec(TABLE, "2026-10-28", [], [], RULES, kapi_tarihi="2026-10-27")
    snapshot = json.dumps(result, sort_keys=True)
    calls = []

    def fn(address, value):
        calls.append((address, value))
        return {"bayrak_rol": "vault"}

    body = secim.bayrak_hesapla(result, fn)
    assert calls == [(addr("2"), 1000.0), (addr("a"), 1000.0)]                                  # aday katı, adres sırası, hesap değeri secim.json'dan
    assert (body["secim_surumu"], body["kapi_tarihi"], body["tamam"]) == ("v1.3", "2026-10-27", True)
    assert body["bayraklar"] == {addr("2"): {"bayrak_rol": "vault"}, addr("a"): {"bayrak_rol": "vault"}}
    assert json.dumps(result, sort_keys=True) == snapshot                                       # secim.json değişmez


def test_havuz_kolu_ileriye_donuk_sessiz_izleme_k8():
    """K-8: havuzun liste dışı üyeleri sha256 sırasıyla 'havuz' koluna eklenir; havuz_adet hedef toplamdır, yeniden üretim idempotent."""
    from copytrade.secim import izleme_listesi
    adres = lambda i: "0x" + f"{i:040x}"
    result = {"secim_surumu": "v1.3", "kapi_tarihi": "2026-10-28", "tarih": "2026-10-29",
              "adresler": {adres(1): {"kollar": ["oda", "havuz"], "tarz": "swing"},
                           **{adres(i): {"kollar": ["havuz"], "tarz": "intraday"} for i in range(2, 12)}}}
    ilk = izleme_listesi(result, [], "2026-10-30", havuz_adet=3)
    havuz = [r for r in ilk if r["kol"] == "havuz"]
    assert len(havuz) == 3 and all(r["t0"] == "2026-10-30" and r["id"].startswith("H") and r["kollar"] == ["havuz"] for r in havuz)
    assert [r for r in ilk if r["kol"] == "oda"][0]["adres"] == adres(1)          # oda değişmez, havuza ikinci kez girmez
    tekrar = izleme_listesi(result, ilk, "2026-11-05", havuz_adet=3)
    assert [(r["id"], r["t0"]) for r in tekrar if r["kol"] == "havuz"] == [(r["id"], r["t0"]) for r in havuz]   # korunur, t0 değişmez
    genis = izleme_listesi(result, ilk, "2026-11-05", havuz_adet=5)
    assert sum(r["kol"] == "havuz" for r in genis) == 5 and len({r["id"] for r in genis}) == len(genis)
