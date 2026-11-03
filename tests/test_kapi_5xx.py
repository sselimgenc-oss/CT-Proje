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
    def __init__(self, kod, veri=None, headers=None):
        self.status_code, self._veri, self.headers = kod, veri if veri is not None else {"ok": kod}, headers or {}

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
        return s if isinstance(s, Yanit) else Yanit(s)


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


def test_429_toplam_bekleme_eskisinden_az_degil_5xx_ve_ag_icin_5_15_45_4xx_yeniden_denenmez():
    c, oturum, bekleme = istemci(429, 200)
    assert c.info({"type": "x"}) == {"ok": 200} and bekleme == [5]
    c, oturum, bekleme = istemci(*[429] * 6)                          # kapı istemcisi: 429 sabrı KISALMADI (eski ilke: 5/10/20/40/60 = 135 sn)
    with pytest.raises(RateLimitError):
        c.info({"type": "x"})
    eski = istemci(*[429] * 6, ilke=None)
    with pytest.raises(RateLimitError):
        eski[0].info({"type": "x"})
    assert bekleme == [5, 10, 20, 40, 60] and sum(bekleme) >= sum(eski[2]) == 135
    c, oturum, bekleme = istemci(500, 500, 500, 500)                  # 5/15/45 yalnız 5xx ve ağ hataları için
    with pytest.raises(requests.HTTPError):
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


def test_429_retry_after_basligina_uyulur_takvimden_uzunsa_o_kadar_bekler():
    c, oturum, bekleme = istemci(Yanit(429, headers={"Retry-After": "90"}), Yanit(429, headers={"Retry-After": "1"}), Yanit(429, headers={"Retry-After": "abc"}), 200)
    assert c.info({"type": "x"}) == {"ok": 200}
    assert bekleme == [90, 10, 20]                                    # max(takvim, başlık); başlık takvimden kısa ya da geçersizse takvim
    c, oturum, bekleme = istemci(Yanit(429, headers={"Retry-After": "99999"}), 200)
    c.info({"type": "x"})
    assert bekleme == [300]                                           # uç değer RETRY_AFTER_MAX ile sınırlı


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


def test_c_hatali_oran_aday_yuzde_birin_ustundeyse_eksik():
    k = lambda hatali, aday, satir=None: kapi.run_status(48, 48, satir or aday, satir or aday, "tam", RULES, hatali, aday, satir or aday)       # noqa: E731
    assert k(0, 100)["durum"] == "tamam" and k(1, 100)["durum"] == "tamam"                            # tam %1: eşik AŞILMADI
    asim = k(2, 100)
    assert asim["durum"] == "eksik" and asim["hatali_satir"] == 2 and asim["hatali_oran_aday"] == 0.02 and "hatali_satir" in asim["neden"]
    gercek = k(160, 1354, 15240)                                                                     # 2026-11-03: kapsam 1,0; payda analize girenler (1.354), tüm satırlar değil
    assert gercek["kapsam"] == 1.0 and gercek["durum"] == "eksik"
    assert gercek["hatali_oran_aday"] == round(160 / 1354, 6) and gercek["hatali_oran_evren"] == round(160 / 15240, 6) and gercek["aday_satir"] == 1354
    assert "hatali_oran" not in gercek                                                               # belirsiz tek oran alanı yok
    assert "/1354" in gercek["neden"]
    # eşik YALNIZ aday oranına uygulanır: evren oranı %1'in altında kalsa da eksik; evren oranı yüksek, aday oranı düşükse tamam
    assert kapi.run_status(48, 48, 15240, 15240, "tam", RULES, 20, 2000, 15240)["durum"] == "tamam"   # 20/2000 = %1 (aşılmadı), 20/15240 yalnız bilgi
    assert kapi.run_status(48, 48, 15240, 15240, "tam", RULES, 21, 2000, 15240)["durum"] == "eksik"
    assert kapi.run_status(48, 48, 10, 10, "tam", RULES, 0, 0, 10)["hatali_oran_aday"] == 0.0           # aday yoksa sıfıra bölme yok
    assert RULES["veri_butunlugu_hatali_oran_max"] == 0.01


def _parca(taban: Path, rows):
    klasor = taban / "stage1-0" / "2026-10-28"
    klasor.mkdir(parents=True)
    pd.DataFrame(rows).to_csv(klasor / "sonuc.csv", index=False)
    (klasor / "evren.json").write_text(json.dumps({"evren": len(rows)}))
    (klasor / "bitti.json").write_text("{}")


def test_c2_birlestirme_durum_json_hatali_alanlari(tmp_path):
    def satirlar(hatali):
        return [{"address": f"0x{i:04d}", "asama1": "Geçti", "closed_trades": 12 + i, "profitable_month_ratio": 0.5 + i * 1e-3, **_metrikler(i),
                 **({"hata": "HTTPError: 500 Server Error"} if i < hatali else {})} for i in range(100)]
    _parca(tmp_path / "a", satirlar(2))
    _parca(tmp_path / "b", satirlar(1))
    uc = kapi.merge_shards(tmp_path / "a", tmp_path / "ra", 1, "tam")["2026-10-28"]
    bir = kapi.merge_shards(tmp_path / "b", tmp_path / "rb", 1, "tam")["2026-10-28"]
    assert (uc["durum"], uc["hatali_satir"], uc["hatali_oran_aday"], uc["hatali_oran_evren"], uc["kapsam"]) == ("eksik", 2, 0.02, 0.02, 1.0) and "hatali_satir" in uc["neden"]
    assert (bir["durum"], bir["hatali_satir"], bir["hatali_oran_aday"]) == ("tamam", 1, 0.01)
    yazilan = json.loads((tmp_path / "ra/kapi/2026-10-28/durum.json").read_text())
    assert yazilan["hatali_satir"] == 2 and yazilan["durum"] == "eksik"
    assert "DURUM: EKSİK" in (tmp_path / "ra/kapi/2026-10-28/RAPOR.md").read_text(encoding="utf-8")


# ------------------------------------------------------------------ yeniden koşu: bayt bayt birleşim
def _metrikler(i: int) -> dict:
    """Akıl sağlığı kapısının (EXPECTED_FILLED + boş sütun) istediği, satıra göre değişen gerçekçi ham metrikler."""
    return {"history_days": 100.0 + i, "account_age_days": 200.0 + i, "median_holding_hours": 1 + i * 0.1, "median_leverage": 2 + i * 0.01, "max_leverage": 5 + i * 0.01,
            "candle_coverage": 0.9 + i * 1e-4, "max_drawdown": 0.1 + i * 1e-3, "gecikme_30dk_net": 0.01 + i * 1e-4, "gecikme_120dk_net": 0.02 + i * 1e-4,
            "kisa_islem_payi": 0.3 + i * 1e-3, "pay_kripto": 0.5 + i * 1e-3, "tarz": "swing" if i % 2 else "intraday", "plasebo_p": 0.5 + i * 1e-3, "nw_t": 1 + i * 0.01,
            **{f"adim{k}": "Yetersiz" for k in range(1, 7)}}


def _kurulum(tmp_path, hatali_adresler=("0x0003", "0x0007"), toplam=60):
    """60 satırlık gerçek biçimli sonuc.csv (finalize edilmiş) + durum.json; zor biçimler: float uzun kuyruk, virgül/tırnak/satır sonu içeren metin."""
    gun = tmp_path / "root" / "kapi" / "2026-11-03"
    gun.mkdir(parents=True)
    ham = []
    for i in range(toplam):
        adres = f"0x{i:04d}"
        satir = {"address": adres, "account_value": 5000.0 + i * 0.1 + 0.2, "kaynak": "leaderboard", "hesap": kapi.HESAP_SURUMU, "kod_hash": kapi.HESAP_KOD_HASH,
                 "now_ms": 1_793_000_000_000 + i, "asama1": "Geçti", "profitable_month_ratio": 0.1 + 0.2 + i * 1e-9, "closed_trades": 12 + i,
                 "not": 'gece, "riskli"\nikinci satır' if i == 5 else None, "sure_toplam_sn": 1.5 + i, "satir_kaynagi": "bu_kosu", "evren_disi": False}
        if adres in hatali_adresler:
            satir.update({"hata": "HTTPError: 500 Server Error: Internal, Server", "sinif": "Yetersiz", "neden": "veri hatası: HTTPError: 500"})
        else:
            satir.update(_metrikler(i))
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
                 "now_ms": int(now.timestamp() * 1000), "asama1": "Geçti", "profitable_month_ratio": 0.5, "closed_trades": 99}
        if sonuclar[lider["address"]] == "hata":
            satir.update({"hata": "HTTPError: 500 Server Error: yine", "sinif": "Yetersiz", "neden": "veri hatası: HTTPError: 500"})
        else:
            satir.update(_metrikler(int(lider["address"][2:])))
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
    assert (durum["hatali_satir"], durum["hatali_oran_aday"], durum["hatali_oran_evren"]) == (1, round(1 / 60, 6), round(1 / 60, 6)) and durum["durum"] == "eksik" and "hatali_satir" in durum["neden"]
    assert durum["yeniden_kosu"]["duzelen"] == 1 and durum["kapsam"] == 1.0 and durum["parca_biten"] == 48
    assert durum["yeniden_kosu"]["yeniden_kosan_adresler"] == ["0x0003", "0x0007"] and durum["yeniden_kosu"]["finalize_farkli_diger_satir"] == 0
    assert durum["satir_kaynagi"] == {"bu_kosu": 60}                           # İlk 11 uygunluğu `bu_kosu` ister: yeniden koşulan satırlar dışlanmaz
    assert "Hatalı adres: 1/60" in (gun / "RAPOR.md").read_text(encoding="utf-8")


def test_d2_hepsi_duzelirse_durum_tamam(tmp_path):
    kok, gun = _kurulum(tmp_path)
    kapi_yeniden.calistir(kok, "2026-11-03", client=SahteIstemci(), degerlendir=_degerlendirici({"0x0003": "basari", "0x0007": "basari"}), semboller=set(), log=lambda *_: None)
    durum = json.loads((gun / "durum.json").read_text())
    assert (durum["durum"], durum["hatali_satir"], durum["hatali_oran_aday"], durum["neden"]) == ("tamam", 0, 0.0, "")


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


# ------------------------------------------------------------------ hash istisnası (lider kararı: tek seferlik, açık girdiyle, kontrol örneği şartıyla)
ESKI_HASH = "a" * 64


def _eski_kodlu(tmp_path, **kwargs):
    kok, gun = _kurulum(tmp_path, **kwargs)
    tablo = pd.read_csv(gun / "sonuc.csv", low_memory=False, float_precision="round_trip")
    tablo["kod_hash"] = ESKI_HASH                                           # dosya BAŞKA bir kod sürümüyle üretilmiş (11-03'te olan bu)
    tablo.to_csv(gun / "sonuc.csv", index=False)
    return kok, gun


def _tekrar_uretici(gun, hedefler, degisiklik=None):
    """Kontrol örneği için: hedef olmayan adreslerde dosyadaki satırın AYNISINI üretir (hesap mantığı değişmedi); hedeflerde başarılı satır."""
    tablo = pd.read_csv(gun / "sonuc.csv", low_memory=False, float_precision="round_trip").set_index("address", drop=False)
    basari = _degerlendirici({a: "basari" for a in hedefler})
    cagrilar = []

    def degerlendir(lider, *args, **kwargs):
        adres = lider["address"]
        cagrilar.append(adres)
        if adres in hedefler:
            return basari(lider, *args, **kwargs)
        satir = {c: (None if pd.isna(v) else v) for c, v in tablo.loc[adres].items()}
        satir.update(degisiklik or {})
        return satir
    degerlendir.cagrilar = cagrilar
    return degerlendir


def test_hash_farkliysa_varsayilan_reddeder_mesaj_istisnayi_gosterir(tmp_path):
    kok, gun = _eski_kodlu(tmp_path)
    once = (gun / "sonuc.csv").read_bytes()
    degerlendir = _tekrar_uretici(gun, {"0x0003", "0x0007"})
    with pytest.raises(kapi_yeniden.YenidenKosuReddedildi, match="--hash-istisnasi"):
        kapi_yeniden.calistir(kok, "2026-11-03", client=SahteIstemci(), degerlendir=degerlendir, semboller=set(), log=lambda *_: None)
    assert (gun / "sonuc.csv").read_bytes() == once and degerlendir.cagrilar == []


def test_hash_istisnasi_kontrol_ornegi_tutarsa_isler_durum_json_kaydi(tmp_path):
    kok, gun = _eski_kodlu(tmp_path)
    once = (gun / "sonuc.csv").read_bytes().decode("utf-8")
    degerlendir = _tekrar_uretici(gun, {"0x0003", "0x0007"})
    ozet = kapi_yeniden.calistir(kok, "2026-11-03", client=SahteIstemci(), degerlendir=degerlendir, semboller=set(), log=lambda *_: None, hash_istisnasi=True)
    kontrol = [a for a in degerlendir.cagrilar if a not in ("0x0003", "0x0007")]
    assert len(kontrol) == 20 and len(set(kontrol)) == 20 and degerlendir.cagrilar[:20] == kontrol            # önce 20 kontrol satırı, sonra hedefler
    assert not {"0x0003", "0x0007"} & set(kontrol)                                                          # kontrol örneği başarılı (hata boş) satırlardan
    durum = json.loads((gun / "durum.json").read_text())
    assert durum["kod_hash_orijinal"] == ESKI_HASH and durum["kod_hash_yeniden"] == kapi.HESAP_KOD_HASH
    assert durum["hash_istisnasi"] == "kapi-5xx yeniden deneme; hesap mantığı değişmedi" and (durum["kontrol_ornek"], durum["kontrol_ayni"]) == (20, 20)
    assert durum["hatali_satir"] == 0 and ozet["duzelen"] == 2
    sonra = (gun / "sonuc.csv").read_bytes().decode("utf-8")
    degisen = [kapi_yeniden.kayit_adresi(a) for a, b in zip(kapi_yeniden.kayitlar(once), kapi_yeniden.kayitlar(sonra)) if a != b]
    assert degisen == ["0x0003", "0x0007"] and ozet["finalize_farkli_diger_satir"] == 0                       # kontrol satırları dahil diğerleri bayt bayt aynı
    assert durum["kod_hashler"] == sorted([ESKI_HASH, kapi.HESAP_KOD_HASH]) and durum["kod_hash_farkli"] is True


def test_hash_istisnasi_kontrol_ornegi_tek_fark_varsa_durur_hicbir_sey_yazilmaz(tmp_path):
    kok, gun = _eski_kodlu(tmp_path)
    once, durum_once = (gun / "sonuc.csv").read_bytes(), (gun / "durum.json").read_bytes()
    degerlendir = _tekrar_uretici(gun, {"0x0003", "0x0007"}, degisiklik={"max_drawdown": 0.9999})
    with pytest.raises(kapi_yeniden.YenidenKosuReddedildi, match="kontrol örneği tutmadı"):
        kapi_yeniden.calistir(kok, "2026-11-03", client=SahteIstemci(), degerlendir=degerlendir, semboller=set(), log=lambda *_: None, hash_istisnasi=True)
    assert (gun / "sonuc.csv").read_bytes() == once and (gun / "durum.json").read_bytes() == durum_once
    assert len(degerlendir.cagrilar) == 1                                                                   # ilk farkta durdu; hedef satırlara hiç geçilmedi


def test_hash_istisnasi_sure_telemetri_sutunlari_karsilastirilmaz(tmp_path):
    """`sure_*` (duvar saati süresi, önbellek sayaçları) hesap değildir; her koşuda farklıdır → kontrol örneğinde karşılaştırılmaz."""
    kok, gun = _eski_kodlu(tmp_path)
    degerlendir = _tekrar_uretici(gun, {"0x0003", "0x0007"}, degisiklik={"sure_toplam_sn": 9999.0})
    kapi_yeniden.calistir(kok, "2026-11-03", client=SahteIstemci(), degerlendir=degerlendir, semboller=set(), log=lambda *_: None, hash_istisnasi=True)
    assert json.loads((gun / "durum.json").read_text())["kontrol_ayni"] == 20


def test_hash_istisnasi_hesap_surumu_farkliysa_yine_reddeder(tmp_path):
    kok, gun = _eski_kodlu(tmp_path)
    tablo = pd.read_csv(gun / "sonuc.csv", low_memory=False)
    tablo.loc[10, "hesap"] = "v0-eski"
    tablo.to_csv(gun / "sonuc.csv", index=False)
    once = (gun / "sonuc.csv").read_bytes()
    with pytest.raises(kapi_yeniden.YenidenKosuReddedildi, match="`hesap` uyuşmuyor"):
        kapi_yeniden.calistir(kok, "2026-11-03", client=SahteIstemci(), degerlendir=_tekrar_uretici(gun, set()), semboller=set(), log=lambda *_: None, hash_istisnasi=True)
    assert (gun / "sonuc.csv").read_bytes() == once


def test_hash_ayniysa_istisna_girdisi_kullanilmaz_kayit_yok(tmp_path):
    kok, gun = _kurulum(tmp_path)
    kapi_yeniden.calistir(kok, "2026-11-03", client=SahteIstemci(), degerlendir=_degerlendirici({"0x0003": "basari", "0x0007": "basari"}), semboller=set(),
                          log=lambda *_: None, hash_istisnasi=True)
    durum = json.loads((gun / "durum.json").read_text())
    assert "hash_istisnasi" not in durum and "kontrol_ornek" not in durum                                   # istisna gerekmedi, kontrol koşulmadı


# ------------------------------------------------------------------ BHY ailesi: aile büyüyünce tüm satırların aileye bağlı sütunları yeniden hesaplanır
def test_bhy_ailesi_tam_yeniden_hesap_ham_sutunlar_bayt_bayt_ayni(tmp_path):
    gun = tmp_path / "root" / "kapi" / "2026-11-03"
    gun.mkdir(parents=True)

    def ham(i):
        return {"address": f"0x{i:04d}", "account_value": 5000.0 + i, "kaynak": "leaderboard", "hesap": kapi.HESAP_SURUMU, "kod_hash": kapi.HESAP_KOD_HASH,
                "now_ms": 1_793_000_000_000 + i, "asama1": "Geçti", "profitable_month_ratio": 0.5 + i * 1e-3, "closed_trades": 20 + i,
                "satir_kaynagi": "bu_kosu", "evren_disi": False, **_metrikler(i)}
    satirlar = []
    for i in range(30):
        satir = ham(i)
        if i < 4:                                          # 4 üyeli aile: adım 1–6 Geçti, p = 0,046 → m=4: q = 0,0958 ≤ 0,10 (adım 7 Geçti)
            satir.update({f"adim{k}": "Geçti" for k in range(1, 7)})
            satir["plasebo_p"] = 0.046
        elif i == 4:                                       # hatalı satır (ailede değil)
            satir = {k: v for k, v in satir.items() if k not in _metrikler(0)} | {"hata": "HTTPError: 500", "sinif": "Yetersiz", "neden": "veri hatası: HTTPError: 500"}
        satirlar.append(satir)
    tablo = kapi.finalize(pd.DataFrame(satirlar))
    assert list(tablo.loc[:3, "adim7"]) == ["Geçti"] * 4 and list(tablo.loc[:3, "katman"]) == ["kopyalanabilir"] * 4
    tablo.to_csv(gun / "sonuc.csv", index=False)
    (gun / "durum.json").write_text(json.dumps({"durum": "tamam", "parca_beklenen": 48, "parca_biten": 48, "islenen": 30, "evren": 30, "kapsam": 1.0}), encoding="utf-8")
    once = (gun / "sonuc.csv").read_bytes().decode("utf-8")

    def degerlendir(lider, *args, **kwargs):               # hatalı satır düzelir ve aileye GİRER (adım 1–6 Geçti, p = 0,001) → m = 5
        satir = {k: v for k, v in ham(4).items() if k != "address"} | {"address": lider["address"], "plasebo_p": 0.001}
        satir.update({f"adim{k}": "Geçti" for k in range(1, 7)})
        return satir
    ozet = kapi_yeniden.calistir(tmp_path / "root", "2026-11-03", client=SahteIstemci(), degerlendir=degerlendir, semboller=set(), log=lambda *_: None)
    sonra = (gun / "sonuc.csv").read_bytes().decode("utf-8")
    baslik = kapi_yeniden.kayitlar(once)[0].rstrip("\n").split(",")
    final_j = {baslik.index(c) for c in kapi_yeniden.FINAL_SUTUNLAR}
    degisen = []
    for a, b in zip(kapi_yeniden.kayitlar(once)[1:], kapi_yeniden.kayitlar(sonra)[1:]):
        if a == b:
            continue
        adres = kapi_yeniden.kayit_adresi(a)
        degisen.append(adres)
        if adres != "0x0004":                               # DİĞER satırlarda yalnız aileye bağlı sütunlar değişti; ham sütunlar bayt bayt aynı
            fa, fb = kapi_yeniden._alanlar(a), kapi_yeniden._alanlar(b)
            assert [j for j in range(len(fa)) if fa[j] != fb[j]] and {j for j in range(len(fa)) if fa[j] != fb[j]} <= final_j
    assert degisen == ["0x0000", "0x0001", "0x0002", "0x0003", "0x0004"]                                    # 25 aile dışı satır tamamen aynı
    assert ozet["ham_sutun_farki_diger_satir"] == 0 and ozet["bhy_q_degisen_satir"] == 4 and ozet["finalize_farkli_diger_satir"] == 4
    assert sorted(k["adres"] for k in ozet["karar_degisen"]) == ["0x0000", "0x0001", "0x0002", "0x0003"]
    assert all(k["adim7"] == ["Geçti", "Kaldı"] and k["katman"] == ["kopyalanabilir", "izleme_adayi"] and k["sinif"] == ["Geçti", "Kaldı"] for k in ozet["karar_degisen"])
    yeni = pd.read_csv(io.StringIO(sonra), low_memory=False, float_precision="round_trip").set_index("address")
    assert yeni.loc["0x0000", "bhy_q"] == pytest.approx(0.046 * 5 * sum(1 / i for i in range(1, 6)) / 5) and yeni.loc["0x0000", "bhy_q"] > 0.10
    assert yeni.loc["0x0004", "adim7"] == "Geçti" and yeni.loc["0x0004", "bhy_q"] == pytest.approx(0.001 * 5 * sum(1 / i for i in range(1, 6)))
    bagimsiz = kapi.finalize(pd.read_csv(io.StringIO(sonra), low_memory=False, float_precision="round_trip")).set_index("address")      # dosya, sıfırdan finalize ile tutarlı
    for sutun in ("bhy_q", "adim7", "sinif", "katman"):
        assert kapi_yeniden._esit(yeni[sutun], bagimsiz[sutun]).all(), sutun
    durum = json.loads((gun / "durum.json").read_text())
    assert durum["yeniden_kosu"]["bhy_q_degisen_satir"] == 4 and len(durum["yeniden_kosu"]["karar_degisen"]) == 4 and durum["hatali_satir"] == 0
