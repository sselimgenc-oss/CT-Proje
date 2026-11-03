"""Kapı 5xx dayanıklılığı, veri bütünlüğü durumu (hatali_satir / hatali_oran) ve hatalı satırların bayt-bayt birleşen yeniden koşusu."""
from __future__ import annotations

import io
import json
from pathlib import Path

import pandas as pd
import pytest
import requests

from copytrade import kapi, kapi_yeniden
from copytrade.kurallar import load_rules
from copytrade.tarama import KAPI_YENIDEN_BEKLEME, PublicClient, RateLimiter, RateLimitError

RULES = load_rules()


# ------------------------------------------------------------------ yeniden deneme (PublicClient)
class Yanit:
    def __init__(self, kod, veri=None):
        self.status_code, self._veri = kod, veri if veri is not None else {"ok": kod}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._veri


class Oturum:
    def __init__(self, *sonuclar):
        self.sonuclar, self.cagri = list(sonuclar), 0

    def request(self, method, url, json=None, timeout=None):
        self.cagri += 1
        s = self.sonuclar.pop(0)
        if isinstance(s, Exception):
            raise s
        return Yanit(s)


def istemci(*sonuclar, ilke=KAPI_YENIDEN_BEKLEME):
    bekleme = []
    oturum = Oturum(*sonuclar)
    return PublicClient(session=oturum, limiter=RateLimiter(10 ** 9), sleep=bekleme.append, yeniden_bekleme=ilke), oturum, bekleme


def test_a_500_500_basari_bekleme_5_15():
    c, oturum, bekleme = istemci(500, 500, 200)
    assert c.info({"type": "x"}) == {"ok": 200}
    assert bekleme == [5, 15] and oturum.cagri == 3 and c.stats["5xx"] == 2


def test_b_dort_kez_500_hata_yukselir_uc_yeniden_deneme():
    c, oturum, bekleme = istemci(500, 500, 500, 500)
    with pytest.raises(requests.HTTPError):
        c.info({"type": "x"})
    assert bekleme == [5, 15, 45] and oturum.cagri == 4


def test_429_ve_ag_hatasi_ayni_ilke_4xx_yeniden_denenmez():
    c, oturum, bekleme = istemci(429, 200)
    assert c.info({"type": "x"}) == {"ok": 200} and bekleme == [5]
    c, oturum, bekleme = istemci(429, 429, 429, 429)
    with pytest.raises(RateLimitError):
        c.info({"type": "x"})
    assert bekleme == [5, 15, 45]
    c, oturum, bekleme = istemci(requests.ConnectionError("x"), requests.Timeout("y"), 200)
    assert c.info({"type": "x"}) == {"ok": 200} and bekleme == [5, 15] and c.stats["ag"] == 2
    c, oturum, bekleme = istemci(*[requests.ConnectionError("x")] * 4)
    with pytest.raises(requests.ConnectionError):
        c.info({"type": "x"})
    assert bekleme == [5, 15, 45] and oturum.cagri == 4
    for kod in (400, 404):                                   # 4xx (429 hariç): bekleme yok, tek istek
        c, oturum, bekleme = istemci(kod)
        with pytest.raises(requests.HTTPError):
            c.info({"type": "x"})
        assert bekleme == [] and oturum.cagri == 1


def test_eski_ilke_degismedi_diger_tuketiciler_icin():
    c, oturum, bekleme = istemci(500, 500, 500, ilke=None)
    with pytest.raises(requests.HTTPError):
        c.info({"type": "x"})
    assert bekleme == [2, 6] and oturum.cagri == 3                       # 5xx: 3 deneme (2/6 sn)
    c, oturum, bekleme = istemci(requests.ConnectionError("x"), ilke=None)
    with pytest.raises(requests.ConnectionError):
        c.info({"type": "x"})
    assert bekleme == [] and oturum.cagri == 1                           # ağ hatası yeniden denenmez
    c, oturum, bekleme = istemci(*[429] * 6, ilke=None)
    with pytest.raises(RateLimitError):
        c.info({"type": "x"})
    assert bekleme == [5, 10, 20, 40, 60]


def test_kapi_istemcisi_kapi_ilkesiyle_kurulur(monkeypatch):
    gorulen = {}

    class Kayit:
        def __init__(self, *a, **k):
            gorulen.update(k)
            raise SystemExit(0)
    monkeypatch.setattr(kapi, "PublicClient", Kayit)
    with pytest.raises(SystemExit):
        kapi.main(["--root", "x", "--tarih", "2026-01-01"])
    assert gorulen["yeniden_bekleme"] == (5, 15, 45)


# ------------------------------------------------------------------ hatali satır sayısı ve durum
def test_b_satir_hata_dolu_ve_hatali_satir_sayilir():
    class Bozuk:
        stats = {"istek": 0, "429": 0, "5xx": 0}
        uclar = {}
        limiter = RateLimiter(10 ** 9)

        def portfolio(self, address):
            raise requests.HTTPError("500 Server Error: Internal Server Error")

    class Onbellek:
        requests = 0
        def saglik(self, coin): return {}
        def get(self, coin): return []
    from datetime import UTC, datetime
    satir = kapi.evaluate_address({"address": "0xabc", "accountValue": 10000.0}, Bozuk(), Onbellek(), datetime.now(UTC), 0, 0, None, RULES, log=lambda *_: None)
    assert satir["hata"].startswith("HTTPError: 500") and satir["sinif"] == "Yetersiz" and satir["neden"].startswith("veri hatası")
    assert kapi.hatali_satir_say(pd.DataFrame([satir, {"address": "0xdef", "asama1": "Yetersiz"}])) == 1


def test_c_hatali_oran_yuzde_birin_ustundeyse_eksik():
    k = lambda hatali, satir: kapi.run_status(48, 48, satir, satir, "tam", RULES, hatali, satir)       # noqa: E731
    assert k(0, 100)["durum"] == "tamam" and k(1, 100)["durum"] == "tamam"                            # tam %1: eşik AŞILMADI
    asim = k(2, 100)
    assert asim["durum"] == "eksik" and asim["hatali_satir"] == 2 and asim["hatali_oran"] == 0.02 and "hatali_satir" in asim["neden"]
    gercek = k(160, 15240)                                                                           # 2026-11-03: kapsam 1,0 ama 160 hatalı satır
    assert gercek["kapsam"] == 1.0 and gercek["durum"] == "eksik" and gercek["hatali_oran"] == round(160 / 15240, 6)
    assert RULES["veri_butunlugu_hatali_oran_max"] == 0.01


def _parca(taban: Path, rows):
    klasor = taban / "stage1-0" / "2026-10-28"
    klasor.mkdir(parents=True)
    pd.DataFrame(rows).to_csv(klasor / "sonuc.csv", index=False)
    (klasor / "evren.json").write_text(json.dumps({"evren": len(rows)}))
    (klasor / "bitti.json").write_text("{}")


def test_c2_birlestirme_durum_json_hatali_alanlari(tmp_path):
    def satirlar(hatali):
        return [{"address": f"0x{i:04d}", "asama1": "Yetersiz", **({"hata": "HTTPError: 500 Server Error"} if i < hatali else {})} for i in range(100)]
    _parca(tmp_path / "a", satirlar(2))
    _parca(tmp_path / "b", satirlar(1))
    uc = kapi.merge_shards(tmp_path / "a", tmp_path / "ra", 1, "tam")["2026-10-28"]
    bir = kapi.merge_shards(tmp_path / "b", tmp_path / "rb", 1, "tam")["2026-10-28"]
    assert (uc["durum"], uc["hatali_satir"], uc["hatali_oran"], uc["kapsam"]) == ("eksik", 2, 0.02, 1.0) and "hatali_satir" in uc["neden"]
    assert (bir["durum"], bir["hatali_satir"], bir["hatali_oran"]) == ("tamam", 1, 0.01)
    yazilan = json.loads((tmp_path / "ra/kapi/2026-10-28/durum.json").read_text())
    assert yazilan["hatali_satir"] == 2 and yazilan["durum"] == "eksik"
    assert "DURUM: EKSİK" in (tmp_path / "ra/kapi/2026-10-28/RAPOR.md").read_text(encoding="utf-8")


# ------------------------------------------------------------------ yeniden koşu: bayt bayt birleşim
def _kurulum(tmp_path, hatali_adresler=("0x0003", "0x0007"), toplam=60):
    """60 satırlık gerçek biçimli sonuc.csv (finalize edilmiş) + durum.json; zor biçimler: float uzun kuyruk, virgül/tırnak/satır sonu içeren metin."""
    gun = tmp_path / "root" / "kapi" / "2026-11-03"
    gun.mkdir(parents=True)
    ham = []
    for i in range(toplam):
        adres = f"0x{i:04d}"
        satir = {"address": adres, "account_value": 5000.0 + i * 0.1 + 0.2, "kaynak": "leaderboard", "hesap": kapi.HESAP_SURUMU, "kod_hash": kapi.HESAP_KOD_HASH,
                 "now_ms": 1_793_000_000_000 + i, "asama1": "Yetersiz", "profitable_month_ratio": 0.1 + 0.2 + i * 1e-9, "closed_trades": 12 + i,
                 "not": 'gece, "riskli"\nikinci satır' if i == 5 else None, "satir_kaynagi": "bu_kosu", "evren_disi": False}
        if adres in hatali_adresler:
            satir.update({"hata": "HTTPError: 500 Server Error: Internal, Server", "sinif": "Yetersiz", "neden": "veri hatası: HTTPError: 500"})
        ham.append(satir)
    tablo = kapi.finalize(pd.DataFrame(ham))
    tablo.to_csv(gun / "sonuc.csv", index=False)
    (gun / "durum.json").write_text(json.dumps({"durum": "eksik", "parca_beklenen": 48, "parca_biten": 48, "islenen": toplam, "evren": toplam, "kapsam": 1.0,
                                                "neden": "", "kapsanan": toplam, "evren_disi_satir": 0, "eski_hesap_satir": 0}), encoding="utf-8")
    return tmp_path / "root", gun


class SahteIstemci:
    def info(self, payload, weight=20):
        return []


def _degerlendirici(sonuclar):
    """adres -> 'basari' | 'hata'; evaluate_address'in dönüş biçimini taklit eder (ağ yok)."""
    cagrilar = []

    def degerlendir(lider, client, cache, now, start, start_200, symbols, rules, yalniz_adim5=False, log=None, dexes=None, gunluk=None):
        cagrilar.append(lider["address"])
        satir = {"address": lider["address"], "account_value": lider["accountValue"], "kaynak": lider["kaynak"], "hesap": kapi.HESAP_SURUMU, "kod_hash": kapi.HESAP_KOD_HASH,
                 "now_ms": int(now.timestamp() * 1000), "asama1": "Yetersiz", "profitable_month_ratio": 0.5, "closed_trades": 99}
        if sonuclar[lider["address"]] == "hata":
            satir.update({"hata": "HTTPError: 500 Server Error: yine", "sinif": "Yetersiz", "neden": "veri hatası: HTTPError: 500"})
        return satir
    degerlendir.cagrilar = cagrilar
    return degerlendir


def test_d_yeniden_kosu_diger_satirlar_bayt_bayt_ayni_hatalilar_yenilenmis(tmp_path):
    kok, gun = _kurulum(tmp_path)
    once = (gun / "sonuc.csv").read_bytes().decode("utf-8")
    degerlendir = _degerlendirici({"0x0003": "basari", "0x0007": "hata"})
    ozet = kapi_yeniden.calistir(kok, "2026-11-03", client=SahteIstemci(), degerlendir=degerlendir, semboller=set(), log=lambda *_: None)
    sonra = (gun / "sonuc.csv").read_bytes().decode("utf-8")
    assert sorted(degerlendir.cagrilar) == ["0x0003", "0x0007"]                  # yalnız hata dolu satırlar koşuldu
    eski_k, yeni_k = kapi_yeniden.kayitlar(once), kapi_yeniden.kayitlar(sonra)
    assert len(eski_k) == len(yeni_k) == 61 and eski_k[0] == yeni_k[0]                               # başlık aynı
    degisen = [kapi_yeniden.kayit_adresi(a) for a, b in zip(eski_k, yeni_k) if a != b]
    assert degisen == ["0x0003", "0x0007"]                                                           # DİĞER 58 KAYIT BAYT BAYT AYNI (satır sonlu 0x0005 dahil)
    assert any("ikinci satır" in k for k in yeni_k if kapi_yeniden.kayit_adresi(k) == "0x0005")
    yeni = pd.read_csv(io.StringIO(sonra), low_memory=False).set_index("address")
    assert pd.isna(yeni.loc["0x0003", "hata"]) and yeni.loc["0x0003", "closed_trades"] == 99 and yeni.loc["0x0003", "satir_kaynagi"] == "bu_kosu"
    assert yeni.loc["0x0007", "hata"].endswith("yine")                                              # hâlâ hatalı satır güncel hatayla yenilendi
    assert yeni.loc["0x0003", "evren_disi"] == False                                                 # noqa: E712 - evren üyeliği korunur
    assert (ozet["hatali_once"], ozet["denenen"], ozet["duzelen"], ozet["hala_hatali"]) == (2, 2, 1, 1)
    durum = json.loads((gun / "durum.json").read_text())
    assert (durum["hatali_satir"], durum["hatali_oran"]) == (1, round(1 / 60, 6)) and durum["durum"] == "eksik" and "hatali_satir" in durum["neden"]
    assert durum["yeniden_kosu"]["duzelen"] == 1 and durum["kapsam"] == 1.0 and durum["parca_biten"] == 48
    assert durum["yeniden_kosu"]["yeniden_kosan_adresler"] == ["0x0003", "0x0007"] and durum["yeniden_kosu"]["finalize_farkli_diger_satir"] == 0
    assert durum["satir_kaynagi"] == {"bu_kosu": 60}                           # İlk 11 uygunluğu `bu_kosu` ister: yeniden koşulan satırlar dışlanmaz
    assert "Hatalı adres: 1/60" in (gun / "RAPOR.md").read_text(encoding="utf-8")


def test_d2_hepsi_duzelirse_durum_tamam(tmp_path):
    kok, gun = _kurulum(tmp_path)
    kapi_yeniden.calistir(kok, "2026-11-03", client=SahteIstemci(), degerlendir=_degerlendirici({"0x0003": "basari", "0x0007": "basari"}), semboller=set(), log=lambda *_: None)
    durum = json.loads((gun / "durum.json").read_text())
    assert (durum["durum"], durum["hatali_satir"], durum["hatali_oran"], durum["neden"]) == ("tamam", 0, 0.0, "")


def test_en_fazla_yalniz_ilk_n_hatali_satiri_kosar(tmp_path):
    kok, gun = _kurulum(tmp_path)
    degerlendir = _degerlendirici({"0x0003": "basari", "0x0007": "basari"})
    ozet = kapi_yeniden.calistir(kok, "2026-11-03", en_fazla=1, client=SahteIstemci(), degerlendir=degerlendir, semboller=set(), log=lambda *_: None)
    assert degerlendir.cagrilar == ["0x0003"] and ozet["denenen"] == 1 and ozet["hala_hatali"] == 0


def test_hata_dolu_satir_yoksa_hicbir_sey_yapmaz(tmp_path):
    kok, gun = _kurulum(tmp_path, hatali_adresler=())
    once = (gun / "sonuc.csv").read_bytes()
    ozet = kapi_yeniden.calistir(kok, "2026-11-03", client=SahteIstemci(), degerlendir=_degerlendirici({}), semboller=set(), log=lambda *_: None)
    assert ozet["denenen"] == 0 and (gun / "sonuc.csv").read_bytes() == once


@pytest.mark.parametrize("sutun,deger", [("kod_hash", "0" * 64), ("hesap", "v0-eski")])
def test_hesap_surumu_ya_da_kod_hash_farkliysa_reddeder_dosyaya_dokunmaz(tmp_path, sutun, deger):
    kok, gun = _kurulum(tmp_path)
    tablo = pd.read_csv(gun / "sonuc.csv", low_memory=False)
    tablo.loc[10, sutun] = deger                                                 # tek satır bile farklıysa red
    tablo.to_csv(gun / "sonuc.csv", index=False)
    once = (gun / "sonuc.csv").read_bytes()
    degerlendir = _degerlendirici({"0x0003": "basari", "0x0007": "basari"})
    with pytest.raises(kapi_yeniden.YenidenKosuReddedildi, match="reddedildi"):
        kapi_yeniden.calistir(kok, "2026-11-03", client=SahteIstemci(), degerlendir=degerlendir, semboller=set(), log=lambda *_: None)
    assert (gun / "sonuc.csv").read_bytes() == once and degerlendir.cagrilar == []   # ne dosya değişti ne de ağa çıkıldı


def test_kayit_bolucu_tirnak_icindeki_satir_sonunu_bolmez():
    metin = 'a,b\n1,"x\ny"\n2,"he said ""hi"""\n3,z'
    assert kapi_yeniden.kayitlar(metin) == ['a,b\n', '1,"x\ny"\n', '2,"he said ""hi"""\n', '3,z'] and "".join(kapi_yeniden.kayitlar(metin)) == metin
