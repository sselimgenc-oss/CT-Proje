"""Seçim isabeti (T6 §1, RADAR_V1 §7b): gruplama, sıra korelasyonu, özet, kötü senaryo, süre bütçesi, kısmi pencere. Ağsız; sayılar elle hesaplanmıştır."""
import json

import pytest

from copytrade import radar_isabet as ri
from copytrade.kurallar import load_rules

RULES = load_rules()
GUN = 86_400_000
BAS = 1_793_822_902_197


def adr(i):
    return "0x" + f"{i:040x}"


def test_spearman_altin_ornekler():
    """Sıralar 1..4 ve 1,3,2,4: Σd² = 0+1+1+0 = 2 → ρ = 1 − 6·2 / (4·15) = 0,8. Eşitlikte ortalama sıra; n<3 ya da sabit taraf → None."""
    assert ri.spearman([10, 20, 30, 40], [0.01, 0.03, 0.02, 0.04]) == pytest.approx(0.8)
    assert ri.spearman([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)
    assert ri.spearman([1, 2], [1, 2]) is None and ri.spearman([1, 2, 3], [5, 5, 5]) is None
    assert ri._sirala([5, 1, 1, 3]) == [4.0, 1.5, 1.5, 3.0]


def test_grup_ozeti_altin_ornek():
    g = ri.grup_ozeti([0.04, -0.02, 0.0, 0.02])
    assert g == {"n": 4, "ortalama": pytest.approx(0.01), "medyan": pytest.approx(0.01), "kar_orani": 0.5}      # 0 kârda sayılmaz
    assert ri.grup_ozeti([]) == {"n": 0, "ortalama": None, "medyan": None, "kar_orani": None}


def havuz_kadro(n_elenen=40):
    satirlar = [{"adres": adr(i), "gecti": True, "kopya_getiri_7g": 0.01, "hesap_usd": 100_000.0} for i in range(1, 6)]
    satirlar += [{"adres": adr(100 + i), "gecti": False, "neden": "kopya_zarar", "kopya_getiri_7g": -0.01, "hesap_usd": 50_000.0} for i in range(n_elenen)]
    satirlar += [{"adres": adr(500 + i), "gecti": False, "neden": "islem_az", "kopya_getiri_7g": None, "hesap_usd": 50_000.0} for i in range(10)]      # kopya aşamasına varmadı: grup dışı
    kadro = {"satirlar": [{"adres": adr(i), "sira": i, "katman": "ilk11" if i <= 2 else "yedek", "form": 100.0 - 10 * i} for i in range(1, 6)]}
    return {"kosu_ms": BAS, "satirlar": satirlar}, kadro


def test_gruplari_sec_gruplar_ve_sabit_tohum():
    havuz, kadro = havuz_kadro()
    s = ri.gruplari_sec(havuz, kadro, "2026-11-04", 30)
    assert s["gruplar"]["ilk11"] == [adr(1), adr(2)] and s["gruplar"]["havuz_geri"] == [adr(3), adr(4), adr(5)]
    assert len(s["gruplar"]["elenen"]) == 30 and s["elenen_aday_sayisi"] == 40 and s["tohum"] == 20261104
    assert all(100 <= int(a, 16) < 140 for a in s["gruplar"]["elenen"])           # yalnız kopya aşamasına varıp elenenler (500+ ve gecti olanlar yok)
    assert ri.gruplari_sec(havuz, kadro, "2026-11-04", 30)["gruplar"]["elenen"] == s["gruplar"]["elenen"]          # aynı tohum aynı seçim
    assert ri.gruplari_sec(havuz, kadro, "2026-11-05", 30)["gruplar"]["elenen"] != s["gruplar"]["elenen"]          # başka gün başka tohum
    assert len(ri.gruplari_sec(*havuz_kadro(5), "2026-11-04", 30)["gruplar"]["elenen"]) == 5                       # 30'dan az aday: hepsi


def test_isabet_olustur_altin_ornek_ic_farklar_ve_kotu():
    """İlk 11: [0,04; 0,02] (ort 0,03). Geri kalan: [0,01; −0,01; 0,0]. Havuz (5) ort = 0,06 / 5 = 0,012 → fark 0,018. Elenen [−0,02; −0,04] ort −0,03 → fark 0,06.
    Formlar 90,80,70,60,50 ↔ getiriler: sıralar form 5,4,3,2,1 / getiri 5,4,3,1,2 → Σd² = 2 → IC = 1 − 12/120 = 0,9.
    Kötü: ilk11 [0,01; 0,0] ort 0,005; havuz kötü [0,01;0;0;−0,02;−0,01] ort −0,004 → fark 0,009; elenen kötü [−0,03;−0,05] ort −0,04 → fark 0,045;
    IC kötü: getiri sıraları [5;3,5;3,5;1;2] → Σdxdy = 8,5, Σdx² = 10, Σdy² = 9,5 → 8,5/√95 = 0,8721."""
    havuz, kadro = havuz_kadro(2)
    secim = ri.gruplari_sec(havuz, kadro, "2026-11-04", 30)
    iyi = {adr(1): 0.04, adr(2): 0.02, adr(3): 0.01, adr(4): -0.01, adr(5): 0.0}
    kotu = {adr(1): 0.01, adr(2): 0.0, adr(3): 0.0, adr(4): -0.02, adr(5): -0.01}
    elen = secim["gruplar"]["elenen"]
    olcum = {a: {"sonraki_7g": iyi[a], "sonraki_7g_kotu": kotu[a], "hata": None} for a in iyi}
    olcum[elen[0]] = {"sonraki_7g": -0.02, "sonraki_7g_kotu": -0.03, "hata": None}
    olcum[elen[1]] = {"sonraki_7g": -0.04, "sonraki_7g_kotu": -0.05, "hata": None}
    i = ri.isabet_olustur("2026-11-04", havuz, kadro, secim, olcum, BAS, BAS + 7 * GUN, True, False, 1.5)
    assert i["gruplar"]["ilk11"]["ortalama"] == pytest.approx(0.03) and i["gruplar"]["ilk11"]["kar_orani"] == 1.0 and i["gruplar"]["ilk11"]["ortalama_kotu"] == pytest.approx(0.005)
    assert i["havuz"]["n"] == 5 and i["havuz"]["ortalama"] == pytest.approx(0.012) and i["havuz"]["ortalama_kotu"] == pytest.approx(-0.004)
    assert i["gruplar"]["elenen"]["ortalama"] == pytest.approx(-0.03) and i["gruplar"]["elenen"]["ortalama_kotu"] == pytest.approx(-0.04)
    assert i["ic"] == pytest.approx(0.9) and i["ic_n"] == 5 and i["ic_kotu"] == pytest.approx(8.5 / 95 ** 0.5)
    assert i["fark_ilk11_havuz"] == pytest.approx(0.018) and i["fark_ilk11_havuz_kotu"] == pytest.approx(0.009)
    assert i["fark_ilk11_elenen"] == pytest.approx(0.06) and i["fark_ilk11_elenen_kotu"] == pytest.approx(0.045)
    assert i["pencere_tam"] is True and i["pencere_gun"] == 7.0 and i["tohum"] == 20261104 and i["eksik"] is False
    assert len(i["satirlar"]) == 5 + 2 and json.dumps(i, allow_nan=False)
    assert "IC (form ↔ sonraki_7g, n=5): +0.9000" in ri.ozet_md(i)


def test_olculemeyen_adres_n_den_dusulur_ve_isaretlenir():
    havuz, kadro = havuz_kadro(0)
    secim = ri.gruplari_sec(havuz, kadro, "2026-11-04", 30)
    olcum = {adr(1): {"sonraki_7g": 0.04, "sonraki_7g_kotu": 0.03, "hata": None}, adr(2): {"sonraki_7g": None, "sonraki_7g_kotu": None, "hata": "HTTPError"}}
    i = ri.isabet_olustur("2026-11-04", havuz, kadro, secim, olcum, BAS, BAS + 7 * GUN, True, True, 0.1)
    g = i["gruplar"]["ilk11"]
    assert g["secilen"] == 2 and g["n"] == 1 and g["olculemeyen"] == 1 and i["eksik"] is True
    assert i["gruplar"]["elenen"]["ortalama"] is None and i["fark_ilk11_elenen"] is None


# ------------------------------------------------------------------------------------------------------------------------------ ağ (sahte istemci)
class SahteBaglam:
    ornekler: list = []

    def __init__(self, client, kosu_ms, pencere_bas_ms, rules, v4_yan_yana=False):
        self.rules, self.bas, self.bit = rules, pencere_bas_ms, kosu_ms
        self.hacim, self.azami_kaldirac, self.mum = {}, None, object()
        SahteBaglam.ornekler.append(self)

    def piyasa_oku(self):
        self.hacim = {"BTC": 1e9}

    def kopya_oynat(self, dolumlar, hesap):
        kotu = int(self.rules["radar_kopya_gecikme_dk"]) == 3
        return {"getiri": len(dolumlar) * (0.001 if kotu else 0.002)}


class SahteIstemci:
    def __init__(self, bos=()):
        self.bos, self.cagri = set(bos), []

    def fills(self, adres, bas, max_rows=None, end_ms=None):
        self.cagri.append((adres, bas, end_ms))
        return [] if adres in self.bos else [{"coin": "BTC", "time": bas + 1000, "px": "100", "sz": "1", "side": "B"}, {"coin": "@107", "time": bas + 2000, "px": "1", "sz": "1", "side": "B"}]


def test_calistir_kotu_senaryo_gecikme_3_kayma_2x_bos_pencere_sifir_kismi_pencere(monkeypatch):
    monkeypatch.setattr(ri.radar_tarama, "Baglam", SahteBaglam)
    SahteBaglam.ornekler = []
    havuz, kadro = havuz_kadro(3)
    simdi = BAS + 3 * GUN                                           # 7 gün dolmadı
    cli = SahteIstemci(bos={adr(5)})
    assert ri.calistir(cli, havuz, kadro, "2026-11-04", simdi, RULES, kismi=False, log=lambda *_: None) is None            # tam pencere yoksa ölçülmez
    i = ri.calistir(cli, havuz, kadro, "2026-11-04", simdi, RULES, kismi=True, log=lambda *_: None)
    iyi, kotu = SahteBaglam.ornekler
    assert int(iyi.rules["radar_kopya_gecikme_dk"]) == 1 and int(kotu.rules["radar_kopya_gecikme_dk"]) == 3
    assert iyi.rules["maliyet_kayma"] == pytest.approx(0.0005) and kotu.rules["maliyet_kayma"] == pytest.approx(0.001)         # 2×
    assert i["pencere_tam"] is False and i["pencere_gun"] == pytest.approx(3.0) and i["pencere_bit_ms"] == simdi and cli.cagri[0][1:] == (BAS, simdi)
    s = {x["adres"]: x for x in i["satirlar"]}
    assert s[adr(1)]["sonraki_7g"] == pytest.approx(0.002) and s[adr(1)]["sonraki_7g_kotu"] == pytest.approx(0.001)          # spot dolum (@107) sayılmaz: tek perp dolum
    assert s[adr(5)]["sonraki_7g"] == 0.0 and s[adr(5)]["sonraki_7g_kotu"] == 0.0                                          # pencerede işlem yok → 0 (ölçüldü)
    tam = ri.calistir(cli, havuz, kadro, "2026-11-04", BAS + 8 * GUN, RULES, log=lambda *_: None)
    assert tam["pencere_tam"] is True and tam["pencere_bit_ms"] == BAS + 7 * GUN and tam["pencere_gun"] == 7.0              # 8. günde bile pencere tam 7 gün


def test_zaman_butcesi_asilinca_eksik_yazilir_kalanlar_olculmez(monkeypatch):
    monkeypatch.setattr(ri.radar_tarama, "Baglam", SahteBaglam)
    havuz, kadro = havuz_kadro(3)
    sayac = {"t": 0.0}

    def saat():
        sayac["t"] += 700.0                                         # her çağrıda 700 sn: bütçe 1.800 sn
        return sayac["t"]
    i = ri.calistir(SahteIstemci(), havuz, kadro, "2026-11-04", BAS + 8 * GUN, RULES, log=lambda *_: None, saat=saat)
    assert i["eksik"] is True and sum(1 for x in i["satirlar"] if x["sonraki_7g"] is not None) < len(i["satirlar"])


def test_main_havuz_yoksa_atlar_cikis_0(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(ri, "git_oku", lambda dal, yol, rev=None: None)
    monkeypatch.setattr(ri, "git_ilk_commit", lambda dal, yol: None)
    assert ri.main(["--cikti", str(tmp_path), "--veri-dali", "radar"]) == 0
    assert "ilk ölçüm 2026-11-12" in capsys.readouterr().out and not list(tmp_path.iterdir())


def test_main_hata_olursa_tarama_bozulmaz_eksik_dosyaya_yazilir(monkeypatch, tmp_path):
    havuz, kadro = havuz_kadro(2)
    monkeypatch.setattr(ri, "git_oku", lambda dal, yol, rev=None: {"havuz.json": havuz, "kadro.json": kadro}.get(yol.rsplit("/", 1)[1]))      # yalnız eski adlar (kadro_ilk yok)
    monkeypatch.setattr(ri, "git_ilk_commit", lambda dal, yol: None)
    monkeypatch.setattr(ri, "calistir", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(ri.radar_tarama, "radar_istemcisi", lambda rules=None: object())
    assert ri.main(["--cikti", str(tmp_path), "--tarih", "2026-11-04"]) == 0
    d = json.loads((tmp_path / "2026-11-04" / "isabet.json").read_text(encoding="utf-8"))
    assert d["eksik"] is True and d["hata"] == "RuntimeError" and d["kadro_kaynagi"] == "son"


def test_varsayilan_tarih_gec_baslayan_havuzu_ertesi_gun_yakalar(monkeypatch):
    from copytrade import radar_isabet as ri
    gun = ri.GUN_MS
    d = {"2026-11-05": {"kosu_ms": 1793860000000}}                   # havuz 11-05 07:19 UTC'de koşmuş (geç başlayan koşu)
    monkeypatch.setattr(ri, "git_oku", lambda dal, yol: d.get(yol.split("/")[1]) if yol.endswith("havuz.json") else None)
    kural = {"isabet_pencere_gun": 7}
    sabah = int(1793860000000 + 7 * gun - 6 * 3600 * 1000)           # 11-12 01:19 UTC: pencere dolmadı → bugün−7 (11-05) denenir, calistir None döner
    assert ri.varsayilan_tarih(sabah, kural, "radar") == "2026-11-05"
    ertesi = 1793860000000 + 8 * gun - 6 * 3600 * 1000               # 11-13 01:19 UTC: 11-05 hâlâ ölçülmemiş ve dolmuş → 11-05
    assert ri.varsayilan_tarih(ertesi, kural, "radar") == "2026-11-05"
    d_olcu = lambda dal, yol: d.get(yol.split("/")[1]) if yol.endswith("havuz.json") else ({"x": 1} if yol.endswith("isabet.json") else None)
    monkeypatch.setattr(ri, "git_oku", d_olcu)                       # ölçüm yazılmışsa tekrar seçilmez → bugün−7
    assert ri.varsayilan_tarih(ertesi, kural, "radar") == "2026-11-06"


# ------------------------------------------------------------------------------------------------------------------------------ R-1: günün İLK kadrosu ölçülür; R-7: isabet hatası yayımı engellemez
ILK_KOSU, SON_KOSU = 1_793_841_373_358, 1_793_863_142_722           # gerçek 2026-11-05: ilk yayım 01:16Z (c566fbc5), güncel kadro.json 07:19Z (e3c10cde)


def iki_kosu():
    """İlk koşu: İlk 11 = adr(1), adr(2); aynı günün sonraki koşusu: İlk 11 = adr(3), adr(4)."""
    havuz1, kadro1 = havuz_kadro(2)
    havuz1["kosu_ms"] = kadro1["kosu_ms"] = ILK_KOSU
    havuz2, _ = havuz_kadro(2)
    havuz2["kosu_ms"] = SON_KOSU
    kadro2 = {"kosu_ms": SON_KOSU, "satirlar": [{"adres": adr(i), "sira": i, "katman": "ilk11" if i in (3, 4) else "yedek", "form": 100.0 - 10 * i} for i in range(1, 6)]}
    return (havuz1, kadro1), (havuz2, kadro2)


def sahte_dal(guncel: dict, gecmis: dict | None = None):
    """git_oku taklidi: `guncel` = origin/<dal> ucundaki dosyalar {yol: json}; `gecmis` = {sha: {yol: json}}."""
    return lambda dal, yol, rev=None: (gecmis or {}).get(rev, {}).get(yol) if rev else guncel.get(yol)


def test_gun_oku_kadro_ilk_varsa_onu_ve_ayni_kosunun_havuzunu_kullanir(monkeypatch):
    (h1, k1), (h2, k2) = iki_kosu()
    k = "radar/2026-11-05"
    monkeypatch.setattr(ri, "git_oku", sahte_dal({f"{k}/kadro_ilk.json": k1, f"{k}/havuz_ilk.json": h1, f"{k}/kadro.json": k2, f"{k}/havuz.json": h2}))
    monkeypatch.setattr(ri, "git_ilk_commit", lambda dal, yol: pytest.fail("kadro_ilk varken git geçmişine bakılmaz"))
    havuz, kadro, kaynak = ri.gun_oku("radar", "2026-11-05")
    assert kaynak == "ilk" and kadro["kosu_ms"] == havuz["kosu_ms"] == ILK_KOSU


def test_gun_oku_eski_gunde_ilk_kadroyu_git_gecmisinden_kurar_yoksa_son(monkeypatch):
    (h1, k1), (h2, k2) = iki_kosu()
    k = "radar/2026-11-05"
    monkeypatch.setattr(ri, "git_oku", sahte_dal({f"{k}/kadro.json": k2, f"{k}/havuz.json": h2}, {"c566fbc5": {f"{k}/kadro.json": k1, f"{k}/havuz.json": h1}}))
    monkeypatch.setattr(ri, "git_ilk_commit", lambda dal, yol: "c566fbc5" if yol == f"{k}/kadro.json" else None)
    havuz, kadro, kaynak = ri.gun_oku("radar", "2026-11-05")
    assert kaynak == "ilk_git" and kadro["kosu_ms"] == havuz["kosu_ms"] == ILK_KOSU
    monkeypatch.setattr(ri, "git_ilk_commit", lambda dal, yol: None)                      # geçmiş yok (sığ checkout) → güncel kadro, "son" diye işaretli
    havuz, kadro, kaynak = ri.gun_oku("radar", "2026-11-05")
    assert kaynak == "son" and kadro["kosu_ms"] == havuz["kosu_ms"] == SON_KOSU


def test_git_ilk_commit_gercek_git_ile_gunun_ilk_yayimini_bulur(tmp_path, monkeypatch):
    """Gerçek git: veri dalında aynı gün iki yayım (kosu 1 → 2); ilk commit'teki kadro + havuz kosu 1, uç kosu 2; yayımı olmayan gün → None."""
    import subprocess
    co, uzak = tmp_path / "co", tmp_path / "remote.git"
    co.mkdir()
    subprocess.run(["git", "init", "-q", "--bare", str(uzak)], check=True)

    def g(*a):
        subprocess.run(["git", "-C", str(co), *a], check=True, capture_output=True, text=True)
    g("init", "-q")
    g("config", "user.name", "T")
    g("config", "user.email", "t@e")
    g("remote", "add", "origin", str(uzak))
    d = co / "radar/2026-11-05"
    d.mkdir(parents=True)
    for kosu in (1, 2):
        (d / "kadro.json").write_text(json.dumps({"kosu_ms": kosu, "satirlar": []}))
        (d / "havuz.json").write_text(json.dumps({"kosu_ms": kosu, "satirlar": []}))
        g("add", ".")
        g("commit", "-qm", f"radar {kosu}")
    g("push", "-q", "origin", "HEAD:radar")
    g("fetch", "-q", "origin")
    monkeypatch.chdir(co)
    havuz, kadro, kaynak = ri.gun_oku("radar", "2026-11-05")
    assert kaynak == "ilk_git" and kadro["kosu_ms"] == 1 and havuz["kosu_ms"] == 1
    assert ri.git_oku("radar", "radar/2026-11-05/kadro.json")["kosu_ms"] == 2
    assert ri.git_ilk_commit("radar", "radar/2026-11-06/kadro.json") is None


def test_main_kadro_ilk_ile_olcer_ilk11_ilk_kadronun_ve_kaynak_yazilir(monkeypatch, tmp_path):
    """Uçtan uca: İlk 11 = ilk kadronun (adr 1, 2), sonraki kadronun (adr 3, 4) DEĞİL; pencere başı = ilk koşu; `kadro_kaynagi: "ilk"`."""
    import time as _t
    (h1, k1), (h2, k2) = iki_kosu()
    simdi = int(_t.time() * 1000)
    h1["kosu_ms"] = k1["kosu_ms"] = simdi - 8 * GUN
    h2["kosu_ms"] = k2["kosu_ms"] = simdi - 8 * GUN + 6 * 3600 * 1000
    k = "radar/2026-11-05"
    monkeypatch.setattr(ri, "git_oku", sahte_dal({f"{k}/kadro_ilk.json": k1, f"{k}/havuz_ilk.json": h1, f"{k}/kadro.json": k2, f"{k}/havuz.json": h2}))
    monkeypatch.setattr(ri.radar_tarama, "Baglam", SahteBaglam)
    monkeypatch.setattr(ri.radar_tarama, "radar_istemcisi", lambda rules=None: SahteIstemci())
    assert ri.main(["--cikti", str(tmp_path), "--tarih", "2026-11-05"]) == 0
    d = json.loads((tmp_path / "2026-11-05" / "isabet.json").read_text(encoding="utf-8"))
    assert d["kadro_kaynagi"] == "ilk" and d["kadro_kosu_ms"] == d["havuz_kosu_ms"] == d["pencere_bas_ms"] == h1["kosu_ms"]
    assert [s["adres"] for s in d["satirlar"] if s["grup"] == "ilk11"] == [adr(1), adr(2)]


def test_main_beklenmeyen_hata_isabet_hatasi_basar_ve_cikis_0(monkeypatch, tmp_path, capsys):
    """R-7: try dışındaki çağrılar (varsayilan_tarih / okuma / json.dumps allow_nan=False) patlasa da çıkış 0 → radar.yml'de kadro yayımı engellenmez; hata AÇIKÇA basılır."""
    monkeypatch.setattr(ri, "varsayilan_tarih", lambda *a, **k: (_ for _ in ()).throw(json.JSONDecodeError("bozuk", "x", 0)))
    assert ri.main(["--cikti", str(tmp_path)]) == 0
    c = capsys.readouterr()
    assert "ISABET HATASI" in c.err and "JSONDecodeError" in c.err and "::error title=ISABET HATASI::" in c.out
    havuz, kadro = havuz_kadro(2)
    monkeypatch.setattr(ri, "gun_oku", lambda dal, tarih: (havuz, kadro, "ilk"))
    monkeypatch.setattr(ri.radar_tarama, "radar_istemcisi", lambda rules=None: object())
    monkeypatch.setattr(ri, "calistir", lambda *a, **k: {"x": float("nan")})                    # allow_nan=False → ValueError
    assert ri.main(["--cikti", str(tmp_path), "--tarih", "2026-11-04"]) == 0
    assert "ISABET HATASI" in capsys.readouterr().err and not (tmp_path / "2026-11-04" / "isabet.json").exists()


def test_radar_yml_isabet_adimi_yayimdan_once_ve_hata_yayimi_engellemez():
    """isabet.json'lar yayımla taşındığı için isabet adımı yayımdan önce kalır; bu yüzden main() her hatada 0 döner (yukarıdaki test)."""
    from pathlib import Path

    import yaml
    wf = yaml.safe_load((Path(__file__).resolve().parents[1] / ".github/workflows/radar.yml").read_text(encoding="utf-8"))
    ad = [a.get("name", "") for a in wf["jobs"]["radar"]["steps"]]
    assert ad.index("Seçim isabeti (§7b)") < ad.index("Veri dalına yaz (radar)")             # K-66: Form Radarı ile isabet adımı geri
