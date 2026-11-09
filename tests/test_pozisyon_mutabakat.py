"""`copytrade/pozisyon_mutabakat.py` testleri (Argon A13 altın örnekleri; bozuk satır sayısı dönüş değerinde) ve izleme motoru bağlantısı."""
from __future__ import annotations

import math

import pandas as pd

from copytrade.pozisyon_mutabakat import borsa_pozisyonlari, mutabakat as _mutabakat, mutabakat_dataframe, ozet


def mutabakat(*args, **kwargs):
    """Satırlar (bozuk sayısı ayrı testte)."""
    return _mutabakat(*args, **kwargs)[0]


# =====================================================================
# 1. Elle Hesaplanmış Altın Örnekler (Golden Samples)
# =====================================================================


def test_altin_ornek_tum_durumlar():
    """
    Her 5 durumun ('uyumlu', 'yetim', 'eksik', 'yon_farki', 'boy_farki')
    yer aldığı elle hesaplanmış altın test senaryosu.
    """
    defter = {
        "BTC": 1.0,  # Uyumlu: borsa 1.0, fark 0.0
        "ETH": 10.0,  # Yetim: defterde 10.0, borsada kapalı (0.0)
        "AVAX": 50.0,  # Yon farki: defter Long 50, borsa Short -50
        "DOGE": 1000.0,  # Boy farki: defter 1000, borsa 1100 (fark 100 > tolerans 10)
        "LINK": 200.0,  # Uyumlu: defter 200, borsa 201 (fark 1 <= tolerans 2)
    }

    borsa_durumu = {
        "assetPositions": [
            {"position": {"coin": "BTC", "szi": "1.0", "entryPx": "65000.0"}},
            {"position": {"coin": "SOL", "szi": "25.0", "entryPx": "180.0"}},  # Eksik: defterde yok, borsada 25
            {"position": {"coin": "AVAX", "szi": "-50.0", "entryPx": "25.0"}},
            {"position": {"coin": "DOGE", "szi": "1100.0", "entryPx": "0.15"}},
            {"position": {"coin": "LINK", "szi": "201.0", "entryPx": "12.0"}},
            {"position": {"coin": "NEAR", "szi": "0.0", "entryPx": "5.0"}},  # Sıfır büyüklük: elenmeli
        ]
    }

    goreli_tol = 0.01  # %1
    mutlak_tol = 0.05

    satirlar = mutabakat(defter, borsa_durumu, goreli_tol, mutlak_tol)
    satir_haritasi = {s["coin"]: s for s in satirlar}

    # Toplam 6 coin olmalı: BTC, ETH, AVAX, DOGE, LINK ve SOL (NEAR sıfır olduğu için elendi)
    assert len(satirlar) == 6
    assert set(satir_haritasi.keys()) == {"BTC", "ETH", "AVAX", "DOGE", "LINK", "SOL"}

    # BTC: Uyumlu
    assert satir_haritasi["BTC"]["durum"] == "uyumlu"
    assert satir_haritasi["BTC"]["defter"] == 1.0
    assert satir_haritasi["BTC"]["borsa"] == 1.0
    assert math.isclose(satir_haritasi["BTC"]["fark"], 0.0, abs_tol=1e-9)

    # ETH: Yetim (Trader çıkmış, bizde açık kalmış)
    assert satir_haritasi["ETH"]["durum"] == "yetim"
    assert satir_haritasi["ETH"]["defter"] == 10.0
    assert satir_haritasi["ETH"]["borsa"] == 0.0
    assert math.isclose(satir_haritasi["ETH"]["fark"], 10.0, abs_tol=1e-9)

    # SOL: Eksik (Borsada var, defterimizde yok)
    assert satir_haritasi["SOL"]["durum"] == "eksik"
    assert satir_haritasi["SOL"]["defter"] == 0.0
    assert satir_haritasi["SOL"]["borsa"] == 25.0
    assert math.isclose(satir_haritasi["SOL"]["fark"], -25.0, abs_tol=1e-9)

    # AVAX: Yön Farkı (İşaretler zıt)
    assert satir_haritasi["AVAX"]["durum"] == "yon_farki"
    assert satir_haritasi["AVAX"]["defter"] == 50.0
    assert satir_haritasi["AVAX"]["borsa"] == -50.0
    assert math.isclose(satir_haritasi["AVAX"]["fark"], 100.0, abs_tol=1e-9)

    # DOGE: Boy Farkı (Fark 100 > Tolerans max(0.05, 0.01 * 1000) = 10)
    assert satir_haritasi["DOGE"]["durum"] == "boy_farki"
    assert satir_haritasi["DOGE"]["defter"] == 1000.0
    assert satir_haritasi["DOGE"]["borsa"] == 1100.0
    assert math.isclose(satir_haritasi["DOGE"]["fark"], -100.0, abs_tol=1e-9)

    # LINK: Uyumlu (Fark 1.0 <= Tolerans max(0.05, 0.01 * 200) = 2.0)
    assert satir_haritasi["LINK"]["durum"] == "uyumlu"
    assert satir_haritasi["LINK"]["defter"] == 200.0
    assert satir_haritasi["LINK"]["borsa"] == 201.0
    assert math.isclose(satir_haritasi["LINK"]["fark"], -1.0, abs_tol=1e-9)

    # Özet Kontrolleri
    ozet_sonuc = ozet(satirlar)
    assert ozet_sonuc["toplam"] == 6
    assert ozet_sonuc["uyumlu"] == 2  # BTC ve LINK
    assert ozet_sonuc["yetim"] == 1  # ETH
    assert ozet_sonuc["eksik"] == 1  # SOL
    assert ozet_sonuc["yon_farki"] == 1  # AVAX
    assert ozet_sonuc["boy_farki"] == 1  # DOGE
    # Uyumsuz oran: (6 - 2) / 6 = 4/6 = 2/3 ≈ 0.666666...
    assert math.isclose(ozet_sonuc["uyumsuz_oran"], 4.0 / 6.0, rel_tol=1e-7)


# =====================================================================
# 2. Tolerans Sınırında Davranış (Sınır Değer Dâhil mi?)
# =====================================================================


def test_tolerans_sinir_deger_goreli():
    """
    Göreli tolerans sınır değerinde davranış testi.
    Kural: Fark tolerans eşiğine tam eşitse sınır DEĞER DÂHİLDİR ve 'uyumlu' kabul edilir.
    Tolerans eşiğini aştığı anda 'boy_farki' olmalıdır.
    """
    defter = {"BTC": 100.0}
    goreli_tol = 0.01  # %1 tolerans = 1.0 birim
    mutlak_tol = 0.0

    # 1. Tam sınır değer: borsa = 101.0 (fark = -1.0, |fark| = 1.0 == tolerans_esigi)
    # Sınır değer dâhil olduğu için durum 'uyumlu' olmalıdır.
    borsa_tam_sinir = {"assetPositions": [{"position": {"coin": "BTC", "szi": "101.0"}}]}
    sonuc = mutabakat(defter, borsa_tam_sinir, goreli_tol, mutlak_tol)
    assert len(sonuc) == 1
    assert sonuc[0]["durum"] == "uyumlu", "Tam sınır değer (fark == tolerans) uyumlu olmalıdır."

    # 2. Sınırın hemen altı: borsa = 100.999 (|fark| = 0.999 < 1.0) -> 'uyumlu'
    borsa_sinir_alti = {"assetPositions": [{"position": {"coin": "BTC", "szi": "100.999"}}]}
    sonuc_alti = mutabakat(defter, borsa_sinir_alti, goreli_tol, mutlak_tol)
    assert sonuc_alti[0]["durum"] == "uyumlu"

    # 3. Sınırın hemen üstü: borsa = 101.0001 (|fark| = 1.0001 > 1.0) -> 'boy_farki'
    borsa_sinir_ustu = {"assetPositions": [{"position": {"coin": "BTC", "szi": "101.0001"}}]}
    sonuc_ustu = mutabakat(defter, borsa_sinir_ustu, goreli_tol, mutlak_tol)
    assert sonuc_ustu[0]["durum"] == "boy_farki"

    # 4. Negatif yönde tam sınır değer: borsa = 99.0 (|fark| = 1.0 == tolerans_esigi) -> 'uyumlu'
    borsa_negatif_sinir = {"assetPositions": [{"position": {"coin": "BTC", "szi": "99.0"}}]}
    sonuc_neg = mutabakat(defter, borsa_negatif_sinir, goreli_tol, mutlak_tol)
    assert sonuc_neg[0]["durum"] == "uyumlu"

    # 5. Negatif yönde sınır üstü: borsa = 98.999 (|fark| = 1.001 > 1.0) -> 'boy_farki'
    borsa_negatif_ustu = {"assetPositions": [{"position": {"coin": "BTC", "szi": "98.999"}}]}
    sonuc_neg_ustu = mutabakat(defter, borsa_negatif_ustu, goreli_tol, mutlak_tol)
    assert sonuc_neg_ustu[0]["durum"] == "boy_farki"


def test_tolerans_sinir_deger_mutlak():
    """
    Mutlak tolerans sınır değerinde davranış testi.
    """
    defter = {"ETH": 10.0}
    goreli_tol = 0.0
    mutlak_tol = 0.05  # Sabit 0.05 birim tolerans

    # Tam sınır: 10.05 -> fark = 0.05 == mutlak_tol -> 'uyumlu'
    b_tam = {"assetPositions": [{"position": {"coin": "ETH", "szi": "10.05"}}]}
    assert mutabakat(defter, b_tam, goreli_tol, mutlak_tol)[0]["durum"] == "uyumlu"

    # Sınır üstü: 10.05001 -> fark = 0.05001 > mutlak_tol -> 'boy_farki'
    b_ust = {"assetPositions": [{"position": {"coin": "ETH", "szi": "10.05001"}}]}
    assert mutabakat(defter, b_ust, goreli_tol, mutlak_tol)[0]["durum"] == "boy_farki"


# =====================================================================
# 3. Boş Girdiler (Empty / None Inputs)
# =====================================================================


def test_bos_girdiler():
    """
    Tamamen boş veya None olan girdilerin zarifçe işlenmesi.
    """
    # 1. Her iki girdi de boş
    sonuc = mutabakat({}, {}, goreli_tolerans=0.01, mutlak_tolerans=0.01)
    assert sonuc == []
    ozet_bos = ozet(sonuc)
    assert ozet_bos["toplam"] == 0
    assert ozet_bos["uyumsuz_oran"] == 0.0
    assert ozet_bos["uyumlu"] == 0
    assert ozet_bos["yetim"] == 0

    # 2. None verilmesi durumu
    sonuc_none = mutabakat(None, None, goreli_tolerans=0.01, mutlak_tolerans=0.01)
    assert sonuc_none == []
    assert ozet(None)["toplam"] == 0
    assert ozet(None)["uyumsuz_oran"] == 0.0

    # 3. Defter boş, borsa dolu -> tüm pozisyonlar 'eksik' olmalı
    borsa_dolu = {
        "assetPositions": [
            {"position": {"coin": "SOL", "szi": "5.0"}},
            {"position": {"coin": "AVAX", "szi": "-10.0"}},
        ]
    }
    sonuc_eksik = mutabakat({}, borsa_dolu, 0.01, 0.01)
    assert len(sonuc_eksik) == 2
    for s in sonuc_eksik:
        assert s["durum"] == "eksik"
        assert s["defter"] == 0.0
    assert ozet(sonuc_eksik)["eksik"] == 2
    assert ozet(sonuc_eksik)["uyumsuz_oran"] == 1.0

    # 4. Defter dolu, borsa boş -> tüm pozisyonlar 'yetim' olmalı
    defter_dolu = {"BTC": 1.5, "ETH": -3.0}
    sonuc_yetim = mutabakat(defter_dolu, {"assetPositions": []}, 0.01, 0.01)
    assert len(sonuc_yetim) == 2
    for s in sonuc_yetim:
        assert s["durum"] == "yetim"
        assert s["borsa"] == 0.0
    assert ozet(sonuc_yetim)["yetim"] == 2
    assert ozet(sonuc_yetim)["uyumsuz_oran"] == 1.0


# =====================================================================
# 4. Bozuk String Değerler ve Hatalı Satırlar
# =====================================================================


def test_bozuk_string_degerler():
    """
    Bozuk string değerler, float'a çevrilemeyen metinler, NaN, Inf ve eksik alanların
    sayılması ve güvenle atlanması.
    """
    bozuk_veri = {
        "assetPositions": [
            {"position": {"coin": "BTC", "szi": "gecersiz_sayi"}},  # Bozuk float
            {"position": {"coin": "ETH", "szi": "10.5"}},  # Geçerli
            {"position": {"coin": "SOL", "szi": "NaN"}},  # NaN -> Bozuk
            {"position": {"coin": "AVAX", "szi": "Infinity"}},  # Inf -> Bozuk
            {"position": {"coin": "", "szi": "5.0"}},  # Boş coin adı -> Bozuk
            {"position": {"coin": "DOGE", "szi": None}},  # None szi -> Bozuk
            {"position": None},  # Bozuk pozisyon nesnesi
            "tamamen_hatali_satir",  # Dict olmayan satır
            {"position": {"coin": "LINK", "szi": "-20.0"}},  # Geçerli Short
            {"position": {"coin": "NEAR", "szi": "0.0"}},  # Geçerli sıfır (bozuk değil, elenmeli)
        ]
    }

    pozisyonlar, bozuk = borsa_pozisyonlari(bozuk_veri)

    # Geçerli coinler sadece ETH (10.5) ve LINK (-20.0) kalmalı
    assert set(pozisyonlar.keys()) == {"ETH", "LINK"}
    assert pozisyonlar["ETH"] == 10.5
    assert pozisyonlar["LINK"] == -20.0
    assert "NEAR" not in pozisyonlar, "Sıfır büyüklük elenmeliydi."

    # Bozuk satır sayısı:
    # 1: gecersiz_sayi
    # 2: NaN
    # 3: Infinity
    # 4: Boş coin
    # 5: None szi
    # 6: position None
    # 7: dict olmayan satır
    # Toplam 7 bozuk satır olmalı
    assert bozuk == 7
    assert _mutabakat({}, bozuk_veri, 0.01, 0.01)[1] == 7                      # mutabakat da aynı sayıyı döner


def test_defterde_bozuk_degerler():
    """
    Defter girdisinde sayısal olmayan veya bozuk değerlerin temizlenmesi.
    """
    defter = {
        "BTC": "1.0",  # String float -> 1.0 olarak kabul edilmeli
        "ETH": 5.0,  # Normal float
        "SOL": "hatali",  # Geçersiz -> atlanmalı
        "DOGE": float("nan"),  # NaN -> atlanmalı
    }
    borsa = {
        "assetPositions": [
            {"position": {"coin": "BTC", "szi": "1.0"}},
            {"position": {"coin": "ETH", "szi": "5.0"}},
        ]
    }
    satirlar = mutabakat(defter, borsa, 0.01, 0.01)
    satir_haritasi = {s["coin"]: s for s in satirlar}

    assert "BTC" in satir_haritasi and satir_haritasi["BTC"]["durum"] == "uyumlu"
    assert "ETH" in satir_haritasi and satir_haritasi["ETH"]["durum"] == "uyumlu"
    assert "SOL" not in satir_haritasi
    assert "DOGE" not in satir_haritasi


# =====================================================================
# 5. Long ve Short Simetrisi (Symmetry Tests)
# =====================================================================


def test_long_short_simetrisi():
    """
    Tüm durumlar için Long pozitif ve Short negatif büyüklüklerin
    birebir simetrik davrandığının doğrulanması.
    """
    durum_senaryolari = [
        # (Durum, Long Defter, Long Borsa, Short Defter, Short Borsa, Goreli, Mutlak)
        ("uyumlu_tam", 10.0, 10.0, -10.0, -10.0, 0.01, 0.01),
        ("uyumlu_tolerans", 100.0, 100.5, -100.0, -100.5, 0.01, 0.01),
        ("yetim", 5.0, 0.0, -5.0, 0.0, 0.01, 0.01),
        ("eksik", 0.0, 8.0, 0.0, -8.0, 0.01, 0.01),
        ("yon_farki", 10.0, -10.0, -10.0, 10.0, 0.01, 0.01),
        ("boy_farki", 100.0, 120.0, -100.0, -120.0, 0.01, 0.01),
    ]

    for isim, l_def, l_bor, s_def, s_bor, g_tol, m_tol in durum_senaryolari:
        # Long çalıştırma
        b_long = {"assetPositions": [{"position": {"coin": "TEST", "szi": str(l_bor)}}]} if l_bor != 0.0 else {}
        d_long = {"TEST": l_def} if l_def != 0.0 else {}
        res_long = mutabakat(d_long, b_long, g_tol, m_tol)[0]

        # Short çalıştırma
        b_short = {"assetPositions": [{"position": {"coin": "TEST", "szi": str(s_bor)}}]} if s_bor != 0.0 else {}
        d_short = {"TEST": s_def} if s_def != 0.0 else {}
        res_short = mutabakat(d_short, b_short, g_tol, m_tol)[0]

        # 1. Durumlar birebir aynı olmalı
        assert res_long["durum"] == res_short["durum"], (
            f"Simetri ihlali ({isim}): Long durum {res_long['durum']} != Short durum {res_short['durum']}"
        )

        # 2. Mutlak farklar birebir eşit olmalı
        assert math.isclose(abs(res_long["fark"]), abs(res_short["fark"]), abs_tol=1e-9), (
            f"Fark mutlak değeri simetrik değil ({isim}): {res_long['fark']} vs {res_short['fark']}"
        )


# =====================================================================
# 6. Ek Kontroller ve Uç Durumlar
# =====================================================================


def test_negatif_tolerans_hatasi():
    """
    Negatif tolerans verildiğinde ValueError fırlatılmalıdır.
    """
    try:
        mutabakat({"BTC": 1.0}, {}, goreli_tolerans=-0.01, mutlak_tolerans=0.0)
        assert False, "Negatif göreli toleransta ValueError fırlatılmalıydı."
    except ValueError:
        pass

    try:
        mutabakat({"BTC": 1.0}, {}, goreli_tolerans=0.0, mutlak_tolerans=-0.05)
        assert False, "Negatif mutlak toleransta ValueError fırlatılmalıydı."
    except ValueError:
        pass


def test_dataframe_ve_ozet_entegrasyonu():
    """
    `mutabakat_dataframe` ve `ozet` fonksiyonuna doğrudan DataFrame verilmesi durumunun testi.
    """
    defter = {"BTC": 1.0, "ETH": 2.0}
    borsa = {
        "assetPositions": [
            {"position": {"coin": "BTC", "szi": "1.0"}},
            {"position": {"coin": "ETH", "szi": "0.0"}},  # Sıfır pozisyon -> yetim kalır
        ]
    }
    df = mutabakat_dataframe(defter, borsa, 0.01, 0.01)

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2
    assert "coin" in df.columns
    assert "durum" in df.columns

    # ozet fonksiyonu DataFrame kabul etmeli
    ozet_df = ozet(df)
    assert ozet_df["toplam"] == 2
    assert ozet_df["uyumlu"] == 1
    assert ozet_df["yetim"] == 1
    assert ozet_df["uyumsuz_oran"] == 0.5


def test_ayni_coin_birden_fazla_satir():
    """
    Aynı coin birden fazla assetPositions satırında gelirse büyüklükler netleştirilmelidir.
    """
    borsa = {
        "assetPositions": [
            {"position": {"coin": "BTC", "szi": "1.5"}},
            {"position": {"coin": "BTC", "szi": "-0.5"}},  # Net 1.0
        ]
    }
    poz, _ = borsa_pozisyonlari(borsa)
    assert math.isclose(poz["BTC"], 1.0, abs_tol=1e-9)

    # Net sıfır kalırsa elenmeli
    borsa_net_sifir = {
        "assetPositions": [
            {"position": {"coin": "ETH", "szi": "2.0"}},
            {"position": {"coin": "ETH", "szi": "-2.0"}},
        ]
    }
    poz_sifir, _ = borsa_pozisyonlari(borsa_net_sifir)
    assert "ETH" not in poz_sifir




def test_fark_defter_eksi_borsa():
    """
    Fark alanının kesinlikle `defter - borsa` olarak hesaplandığının doğrulanması.
    """
    defter = {"BTC": 10.0, "ETH": -5.0, "SOL": 0.0}
    borsa = {
        "assetPositions": [
            {"position": {"coin": "BTC", "szi": "7.0"}},
            {"position": {"coin": "ETH", "szi": "-8.0"}},
            {"position": {"coin": "SOL", "szi": "4.0"}},
        ]
    }
    satirlar = mutabakat(defter, borsa, goreli_tolerans=0.5, mutlak_tolerans=5.0)
    harita = {s["coin"]: s for s in satirlar}

    # BTC: 10.0 - 7.0 = 3.0
    assert math.isclose(harita["BTC"]["fark"], 3.0, abs_tol=1e-9)
    # ETH: -5.0 - (-8.0) = 3.0
    assert math.isclose(harita["ETH"]["fark"], 3.0, abs_tol=1e-9)
    # SOL: 0.0 - 4.0 = -4.0
    assert math.isclose(harita["SOL"]["fark"], -4.0, abs_tol=1e-9)


def test_tam_sifir_defter_ve_borsa():
    """
    Defterde açıkça 0.0 girilmiş ve borsada pozisyonu olmayan coin 'uyumlu' olmalıdır.
    """
    defter = {"BTC": 0.0}
    borsa = {"assetPositions": []}
    satirlar = mutabakat(defter, borsa, goreli_tolerans=0.01, mutlak_tolerans=0.01)
    assert len(satirlar) == 1
    assert satirlar[0]["durum"] == "uyumlu"
    assert satirlar[0]["fark"] == 0.0


def test_sirali_ve_tutarli_cikis():
    """
    Dönen listenin coin isimlerine göre alfabetik sıralı olduğunun kontrolü.
    """
    defter = {"SOL": 1.0, "AVAX": 2.0, "BTC": 3.0}
    borsa = {"assetPositions": [{"position": {"coin": "ETH", "szi": "4.0"}}]}
    satirlar = mutabakat(defter, borsa, 0.01, 0.01)
    coin_sirasi = [s["coin"] for s in satirlar]
    assert coin_sirasi == ["AVAX", "BTC", "ETH", "SOL"]






def test_defterdeki_bozuk_girdiler_de_sayilir():
    rows, broken = _mutabakat({"BTC": "1.0", "SOL": "hatali", "DOGE": float("nan"), "": 1.0}, {"assetPositions": [{"position": {"coin": "BTC", "szi": "1.0"}}, "x"]}, 0.01, 0.01)
    assert [r["coin"] for r in rows] == ["BTC"] and broken == 4                                                    # 3 defter + 1 borsa


# ---------------------------------------------------------------- izleme motoru bağlantısı (uçtan uca)
def _oda_projesi(tmp_path, kol="oda"):
    from tests.test_izleme import ADDRESS, T0, project
    tmp_path.mkdir(parents=True, exist_ok=True)
    row = {"id": "O01", "adres": ADDRESS, "takma_ad": "Test", "durum": "izlemede", "t0": str(T0.date()), "kol": kol}
    return project(tmp_path, [row])


def test_izleme_motoru_oda_uyeleri_icin_mutabakati_veri_kalitesine_yazar(tmp_path):
    """Dolumlar 1 BTC long açık gösteriyor. Borsa da 1 BTC → uyumlu; borsa boş → yetim (trader çıkmış, çıkış dolumu gelmemiş)."""
    from copytrade import izleme_motoru as m
    from tests.test_izleme import NOW, Client
    ok = m.run(_oda_projesi(tmp_path / "a"), tmp_path / "a/out", Client(), NOW)["traderlar"][0]
    q = ok["veri_kalitesi"]["mutabakat"]
    assert (q["uyumlu"], q["yetim"], q["toplam"], q["uyumsuz_oran"], q["bozuk_satir"]) == (1, 0, 1, 0.0, 0) and q["yetim_coinler"] == []
    broken = Client()
    broken.positions = []
    res = m.run(_oda_projesi(tmp_path / "b"), tmp_path / "b/out", broken, NOW)["traderlar"][0]
    q = res["veri_kalitesi"]["mutabakat"]
    assert (q["yetim"], q["uyumlu"], q["uyumsuz_oran"]) == (1, 0, 1.0) and q["yetim_coinler"] == ["BTC"] and q["zaman"] == "2026-10-27T12:00:00Z"
    assert res["sanal_kopya"]["bakiye_usd"] == ok["sanal_kopya"]["bakiye_usd"]             # yalnız rapor: defter/sonuç değişmez, pozisyon kapatılmaz
    saved = __import__("json").loads((tmp_path / "b/out/durum.json").read_text())["traderlar"][0]
    assert saved["veri_kalitesi"]["mutabakat"]["yetim"] == 1                                # durum.json'a yazıldı


def test_izleme_motoru_mutabakat_yalniz_oda_uyeleri_icin(tmp_path):
    from copytrade import izleme_motoru as m
    from tests.test_izleme import NOW, Client
    for kol in ("kontrol", "taban", "elle"):
        trader = m.run(_oda_projesi(tmp_path / kol, kol), tmp_path / kol / "out", Client(), NOW)["traderlar"][0]
        assert "veri_kalitesi" not in trader


def test_mutabakat_tolerans_ve_pozisyon_rapor_ayarlari_kurallardan():
    from copytrade.kurallar import load_rules
    rules = load_rules()
    assert rules["mutabakat_goreli_tolerans"] == 0.01 and rules["mutabakat_mutlak_tolerans"] == 1e-06
