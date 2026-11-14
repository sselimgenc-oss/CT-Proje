"""v1.1 seçim kuralları (K-53, kullanıcı kararı 09.11, Fable 5.1 görüşü): S1 ay pnl > 0, S2 kopya işlem ≥ 10, S4 H = 0, D1 nedene bağlı tutma. Ağsız altın örnekler."""
from pathlib import Path

from copytrade import radar_kadro as rk
from copytrade import radar_tarama as r
from tests.test_radar_tarama import A1, A2, A3, BAS, HOUR, MIN, RULES, RULES1, Sahte, dolum, kos, lider, satir_al

ROOT = Path(__file__).resolve().parents[1]


def lider_ay(adres, hesap, pnl, vlm, ay):
    s = lider(adres, hesap, pnl, vlm)
    s["windowPerformances"].append(["month", {"pnl": str(ay), "roi": "0", "vlm": "1"}])
    return s


def test_kurallar_v11_degerleri():
    assert RULES["radar_surum"] == "v4"                                     # M-09 (14.11): v3 → v4 (radar hunisi + mantık denetimi düzeltmeleri)
    assert RULES["radar_ay_pnl_pozitif"] is True and RULES["radar_min_kopya_islem"] == 0 and RULES["radar_tutma_onceki_kadro"] is True
    assert float(RULES["radar_agirlik_h"]) == 0.0
    assert "radar_t_oncelik" not in RULES                                   # t önceliği (taslak) Fable denetimiyle reddedildi: kural yok


def test_ay_pnl_okuma_ve_kapi():
    assert r.ay_pnl(lider_ay(A1, 20_000, 5, 1, -3)) == -3.0
    assert r.ay_pnl(lider(A1, 20_000, 5, 1)) is None                       # pencere yok
    assert r.ay_pnl({"monthPnl": "7"}) == 7.0                               # düz biçim
    assert r.ay_kapisi(lider_ay(A1, 20_000, 5, 1, 0), RULES) is False       # tam 0 elenir (> 0 gerekir)
    assert r.ay_kapisi(lider_ay(A1, 20_000, 5, 1, 0.01), RULES) is True
    assert r.ay_kapisi(lider(A1, 20_000, 5, 1), RULES) is True             # ölçülemez ≠ başarısız
    assert r.ay_kapisi(lider_ay(A1, 20_000, 5, 1, -1), {**RULES, "radar_ay_pnl_pozitif": False}) is True     # kapalı = v1


def test_evren_ay_kapisi_tek_haftada_parlayani_ayiklar():
    satirlar = [lider_ay("0xa", 20_000, 900, 1, -50), lider_ay("0xb", 20_000, 100, 1, 10), lider("0xc", 20_000, 50, 1)]
    adaylar, toplam, _ = r.evren(satirlar, RULES)
    assert [a["adres"] for a in adaylar] == ["0xb", "0xc"] and toplam == 2
    assert adaylar[0]["ay_pnl_usd"] == 10.0 and adaylar[1]["ay_pnl_usd"] is None
    adaylar_v1, _, _ = r.evren(satirlar, {**RULES, "radar_ay_pnl_pozitif": False})
    assert [a["adres"] for a in adaylar_v1] == ["0xa", "0xb", "0xc"]


def test_kopya_islem_kapisi_sansdan_once_ve_kapatilabilir():
    iyi = {"hesap_usd": 20_000.0, "islem_sayisi": 30, "medyan_tutma_saat": 2.0, "kisa_islem_payi": 0.0, "max_kaldirac": 3.0, "likit_pay": 1.0,
           "kopya_getiri_7g": 0.05, "kopya_koruma": 0.9, "devir_hafta": 1.0, "kopya_alt20": 0.0, "kopya_islem_sayisi": 4, "hata": None}
    acik = {**RULES, "radar_min_kopya_islem": 10}                          # kullanıcı 14.11: üretimde 0 (kapalı); mekanizma eşik 10 ile sınanır
    assert r.degerlendir(iyi, acik) == (False, "kopya_islem_az")           # işlem az: şans kapısından önce
    assert r.degerlendir({**iyi, "kopya_islem_sayisi": 10}, acik) == (False, "sans_riski")
    assert r.degerlendir({**iyi, "kopya_islem_sayisi": 10, "kopya_alt20": 0.01}, acik) == (True, None)
    assert r.degerlendir(iyi, RULES) == (False, "sans_riski")             # üretim (0): 4 kopya işlemi elemez; şans süzgeci (kural 8) aynen
    assert r.degerlendir({**iyi, "kopya_alt20": 0.01}, {**RULES, "radar_min_kopya_islem": 0}) == (True, None)     # 0 = kapalı (v1)
    assert r.degerlendir(iyi, acik, yalniz_dolum=True) == (True, None)    # dolum aşamasında bakılmaz (kopya oynatılmadan önce)


def test_tutma_adaylari_onceki_kadro_r0_disindan():
    tablo = [lider_ay(A1, 20_000, 100, 5, 10), lider_ay(A2, 20_000, -40, 5, 10), lider_ay(A3, 20_000, 10, 5, -1), lider_ay("0x" + "4" * 40, 5_000, 1, 5, 1)]
    t = r.tutma_adaylari(tablo, [A3, A2, A1, "0x" + "4" * 40, "0x" + "9" * 40], {A1}, RULES)
    # A1 zaten R0'da (tekrar yok); A2 hafta zararda ama alınır (R1 karar verir); A3 ay zararda → alınmaz; 0x44.. sermaye < 10.000; 0x99.. tabloda yok
    assert [x["adres"] for x in t] == [A2] and t[0]["tutma"] is True and t[0]["hafta_pnl_usd"] == -40.0
    assert r.tutma_adaylari(tablo, [A2], set(), {**RULES, "radar_tutma_onceki_kadro": False}) == []
    assert r.tutma_adaylari([lider_ay(A2.upper().replace("0X", "0x"), 20_000, 1, 5, 1)], [A2], set(), RULES)[0]["adres"].lower() == A2


def test_kos_tutma_once_olculur_isaretlenir_ve_kadroya_girer(tmp_path):
    """A1 R0'da (hafta +100); A2 R0 tavanı (1) dışında ama önceki kadroda → tutma adayı olarak R1'den geçer, satırı `tutma: true`. İkisi de aynı işlemleri yapar."""

    fills, t = [], BAS + HOUR
    for _ in range(12):                                                     # 12 kârlı tur: 100'den aç, 90 dk sonra 110'dan kapat
        fills += [dolum(t, "BTC", "B", 1, 0, 100.0, tid=t), dolum(t + 90 * MIN, "BTC", "A", 1, 1, 110.0, kapanan=10.0, tid=t + 1)]
        t += 3 * HOUR
    fiyat = lambda coin, ts: 110.0 if (ts - BAS - HOUR) % (3 * HOUR) >= 90 * MIN else 100.0     # noqa: E731
    c = Sahte([lider_ay(A1, 20_000, 100, 5_000, 50), lider_ay(A2, 20_000, 10, 5_000, 50)], {A1: fills, A2: fills}, fiyat)
    sonuc = kos(c, tmp_path, adet=1, rules=RULES1, onceki_adresler=[A2])
    assert [s["adres"] for s in sonuc["satirlar"]] == [A2, A1]              # tutma önce ölçülür (bütçe kesmesin)
    assert satir_al(sonuc, A2)["tutma"] is True and satir_al(sonuc, A1)["tutma"] is False
    assert satir_al(sonuc, A2)["gecti"] is True and satir_al(sonuc, A1)["gecti"] is True and satir_al(sonuc, A2)["kopya_islem_sayisi"] == 12   # aynı işlemler → ikisi de geçer
    assert rk.kosu_tam_mi(sonuc, {**RULES1, "radar_aday_tavan": 1})[0]      # fazladan satır koşuyu eksik yapmaz
    kd = rk.kadro_olustur(sonuc, RULES1)
    assert kd["radar_surum"] == "v4" and {s["adres"]: s["tutma"] for s in kd["satirlar"]} == {A1: False, A2: True}


def test_radar_yml_tarama_onceki_kadroyu_gecirir():
    """K-66 (14.11): radar.yml yeniden v1.1 taramasını çalıştırır; önceki kadro üyeleri R1'den geçirilir (tutma)."""
    wf = (ROOT / ".github/workflows/radar.yml").read_text(encoding="utf-8")
    assert '--payda-yan-yana "${tutma[@]}"' in wf and 'tutma=(--onceki-kadro "$RUNNER_TEMP/onceki_kadro_tarama.json")' in wf and "copytrade.secim_d" not in wf
