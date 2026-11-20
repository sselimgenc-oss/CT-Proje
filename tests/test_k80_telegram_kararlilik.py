"""K-80 (kararlılık): Telegram güncelleme penceresi (15 dk yalnız ölümcül), durum alarmı çift doğrulaması + bağlam satırı, saglik.py aynı kurallar. Ağ yok; sahte saat/zamanlayıcı/post."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from copytrade import saglik
from copytrade.canli import telegram as tg


class _Ortam:
    def __init__(self, tmp_path: Path, dogrulama: float = 0.0):
        self.t = 1_800_000_000.0
        self.zamanlayicilar: list[tuple[float, object]] = []
        self.giden: list[str] = []
        self.kayitlar: list[dict] = []
        self.isaret = tmp_path / "guncelleme_zamani"
        self.tgram = tg.Telegram("TOK", "42", post=lambda url, yuk: self.giden.append(yuk["text"]) or {"ok": True}, kayit=self.kayitlar.append, saat_s=lambda: self.t, uyku=lambda s: None,
                                 zamanlayici=lambda sn, f: self.zamanlayicilar.append((sn, f)))
        self.tgram.guncelleme_isareti = self.isaret
        self.tgram.cift_dogrulama_sn = dogrulama

    def guncelleme(self, dk_once: float = 0):
        self.isaret.write_text(f"{int(self.t - dk_once * 60)}\nabc\n")

    def ilerle(self, sn: float):
        self.t += sn
        bekleyen, self.zamanlayicilar = self.zamanlayicilar, []
        for _sn, f in bekleyen:
            f()

    def olaylar(self, ad: str) -> list[dict]:
        return [k for k in self.kayitlar if k.get("olay") == ad]


@pytest.fixture
def o(tmp_path):
    return _Ortam(tmp_path)


def test_olumcul_ayirimi():
    for m in ("🔴 Bot durdu\nNeden: x", "💥 Tasfiye (sanal)", "🚨 Günlük kayıp sınırı\nBugün...", "🚨 Pozisyonlar hâlâ kapanmadı\nkapanış eksik: 2", "🚨 Kapanış bugün de olmadı", "🛑 DUR", "🚨 Günlük sert fren", "🚨 Felaket stopu"):
        assert tg.olumcul_mu(m), m
    for m in ("🚨 HL okunamıyor\n3 ardışık", "🚨 Kayıtlar uyuşmuyor (mutabakat)", "⚠️ Radar sunucuda çalışmadı", "🚨 Kasa sınırı aşıldı", "🚨 HL hesap değeri geçersiz"):
        assert not tg.olumcul_mu(m), m


def test_guncelleme_penceresinde_yalniz_olumcul_gider_digeri_15_dk_sonra(o):
    o.guncelleme(dk_once=1)
    assert o.tgram.gonder("🚨 Kayıtlar uyuşmuyor (mutabakat)\nYeni pozisyon açılmıyor.") is True      # ertelendi (kabul)
    assert o.tgram.gonder("💥 Tasfiye (sanal)\nBTC tasfiye oldu.") is True
    assert o.tgram.gonder("ℹ️ Saatlik özet: 3 işlem") is True                                         # INFO (işlem özeti) etkilenmez
    assert len(o.giden) == 2 and any("Tasfiye" in m for m in o.giden) and any("Saatlik özet" in m for m in o.giden) and not any("uyuşmuyor" in m for m in o.giden)
    assert o.olaylar("tg_guncelleme_bekletildi")
    o.ilerle(14 * 60 + 5)                                                                             # pencere bitti (işaret 1 dk önceydi: kalan 14 dk)
    assert any("uyuşmuyor" in m for m in o.giden) and len(o.giden) == 3


def test_pencere_sonunda_hala_gecerli_degilse_gitmez_ve_duzeldi_iptal_eder(o):
    gecerli = {"v": True}
    o.guncelleme(dk_once=0)
    o.tgram.uyar("hl_okunamiyor", "🚨 ALARM: HL okunamıyor\nx", dogrula=lambda: gecerli["v"])
    o.tgram.uyar("ofset", "🚨 ALARM: yatırma/çekme kaydı okunamıyor\nx", dogrula=lambda: True)
    assert o.giden == []
    gecerli["v"] = False                                                                              # koşul pencere içinde düzeldi
    o.ilerle(15 * 60 + 1)
    assert not any("HL okunamıyor" in m for m in o.giden) and any("atırma/çekme" in m for m in o.giden)
    assert o.olaylar("tg_dogrulama_dustu")
    assert o.tgram.duzeldi("hl_okunamiyor", "✅ Düzeldi: HL") is False and not any("Düzeldi" in m for m in o.giden)   # hiç gitmemiş alarm için "düzeldi" yok
    o.tgram.uyar("hl_okunamiyor", "🚨 ALARM: HL okunamıyor\nx", dogrula=lambda: True)                # sonra yeniden olursa uyarı gider (6 saat kilidi kurulmadı)
    o.ilerle(0)
    assert any("HL okunamıyor" in m for m in o.giden)


def test_pencere_yoksa_bayat_isaret_ve_isaretsiz_normal(o):
    assert o.tgram.gonder("🚨 Kayıtlar uyuşmuyor") and len(o.giden) == 1                              # işaret dosyası yok
    o.guncelleme(dk_once=16)                                                                          # 15 dk geçti
    assert o.tgram.gonder("🚨 Kayıtlar uyuşmuyor 2") and len(o.giden) == 2
    o.isaret.write_text("bozuk\n")
    assert o.tgram.guncelleme_kalan_s() == 0.0
    o.isaret.write_text(f"{int(o.t + 3600)}\n")                                                       # gelecekte (saat kayması): alarm SUSTURULMAZ
    assert o.tgram.guncelleme_kalan_s() == 0.0


def test_cift_dogrulama_kosul_gecerliyse_gonderir_baglam_satiri_ile(tmp_path):
    o = _Ortam(tmp_path, dogrulama=tg.DOGRULAMA_SN)
    o.guncelleme(dk_once=125)                                                                         # 15 dk penceresi dışı; son güncelleme 2 sa 5 dk önce
    assert o.tgram.uyar("kasa_siniri", "🚨 ALARM: kasa sınırı aşıldı\nYeni pozisyon açılmıyor.", dogrula=lambda: True) is True
    assert o.giden == [] and o.olaylar("tg_dogrulama_bekliyor")
    o.tgram.uyar("kasa_siniri", "🚨 ALARM: kasa sınırı aşıldı\nYeni pozisyon açılmıyor.", dogrula=lambda: True)   # sürerken tekrar çağrı: yeni zamanlayıcı kurulmaz
    assert len(o.zamanlayicilar) == 1
    o.ilerle(tg.DOGRULAMA_SN + 1)
    assert len(o.giden) == 1
    satirlar = o.giden[0].split("\n")
    assert satirlar[0].startswith("[CT] 🚨") and satirlar[-1].startswith("⏱ ") and "son güncelleme 2 sa" in satirlar[-1]


def test_cift_dogrulama_kosul_dustuyse_gonderilmez_duzeldi_de_gitmez(tmp_path):
    o = _Ortam(tmp_path, dogrulama=45.0)
    durum = {"v": True}
    o.tgram.uyar("hl_deger", "🚨 ALARM: HL hesap değeri geçersiz\nx", dogrula=lambda: durum["v"])
    durum["v"] = False
    o.ilerle(46)
    assert o.giden == [] and o.olaylar("tg_dogrulama_dustu")
    assert o.tgram.duzeldi("hl_deger", "✅ Düzeldi: HL hesap değeri") is False and o.giden == []


def test_cift_dogrulama_duzeldi_beklerken_iptal_eder(tmp_path):
    o = _Ortam(tmp_path, dogrulama=45.0)
    o.tgram.uyar("ofset", "🚨 ALARM: ofset\nx", dogrula=lambda: True)
    assert o.tgram.duzeldi("ofset", "✅ Düzeldi") is False
    o.ilerle(46)
    assert o.giden == [] and o.olaylar("tg_ertelenen_iptal")


def test_olay_alarmlari_cift_dogrulamaya_girmez_ve_varsayilan_kapali(tmp_path):
    o = _Ortam(tmp_path, dogrulama=45.0)
    o.tgram.gonder("💥 Tasfiye (sanal)\nBTC")                                                         # dogrula verilmedi (gerçekleşmiş olay): anında
    assert len(o.giden) == 1 and o.zamanlayicilar == []
    o2 = _Ortam(tmp_path, dogrulama=0.0)
    o2.tgram.uyar("kasa", "🚨 ALARM: kasa", dogrula=lambda: True)                                     # çift doğrulama kapalı (varsayılan): eski davranış, bağlam eklenmez
    assert len(o2.giden) == 1 and "⏱" not in o2.giden[0]


def test_zamanlayicisiz_esik_yolu_eski_gibi_gonderir(tmp_path):
    giden: list[str] = []
    t = tg.Telegram("TOK", "42", post=lambda u, y: giden.append(y["text"]) or {"ok": True})
    t.cift_dogrulama_sn = 45.0
    assert t.uyar("x", "🚨 ALARM: x", dogrula=lambda: True) and len(giden) == 1                      # --kontrol (eşzamanlı) yolu bekletmez


def test_bagimsiz_sure_metni():
    assert tg.sure_metni(30) == "30 sn" and tg.sure_metni(600) == "10 dk" and tg.sure_metni(3 * 3600 + 600) == "3 sa 10 dk"


# ----------------------------------------------------------------------------------------------- saglik.py (Actions yolu)
def test_saglik_guncelleme_penceresi_yardimcisi(tmp_path):
    yol = tmp_path / "isaret"
    simdi_ms = int(time.time() * 1000)
    assert saglik.guncelleme_penceresinde_mi("", simdi_ms) is False and saglik.guncelleme_penceresinde_mi(str(yol), simdi_ms) is False
    yol.write_text(f"{int(time.time()) - 60}\n")
    assert saglik.guncelleme_penceresinde_mi(str(yol), simdi_ms) is True
    yol.write_text(f"{int(time.time()) - 16 * 60}\n")
    assert saglik.guncelleme_penceresinde_mi(str(yol), simdi_ms) is False


def _saglik_calistir(monkeypatch, tmp_path, ilk, ikinci, isaret_dk=None, ek=()):
    giden: list[str] = []
    sirali = [ilk, ikinci]
    monkeypatch.setattr(saglik, "_git_fetch", lambda d: True)
    for ad in ("_git_oku",):
        monkeypatch.setattr(saglik, ad, lambda dal, yol: None)
    monkeypatch.setattr(saglik, "_git_zaman_ms", lambda d, y: None)
    monkeypatch.setattr(saglik, "_git_var", lambda d, y: False)
    monkeypatch.setattr(saglik, "_git_son_commit_ms", lambda d: None)
    monkeypatch.setattr(saglik, "kayit_olaylari", lambda d, s: None)
    monkeypatch.setattr(saglik, "vardiya_kosulari_oku", lambda *a, **k: None)
    monkeypatch.setattr(saglik, "kontrol", lambda *a, **k: sirali.pop(0) if len(sirali) > 1 else sirali[0])
    monkeypatch.setattr(time, "sleep", lambda s: None)
    monkeypatch.setattr(tg.Telegram, "gonder", lambda self, metin, *a, **k: giden.append(metin) or True)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    args = ["--telegram", *ek]
    if isaret_dk is not None:
        yol = tmp_path / "isaret"
        yol.write_text(f"{int(time.time()) - isaret_dk * 60}\nabc\n")
        args += ["--guncelleme-isareti", str(yol)]
    saglik.main(args)
    return giden


def test_saglik_ikinci_okumada_duzelen_bulgu_alarma_girmez(monkeypatch, tmp_path):
    kritik = [saglik.Bulgu("KRITIK", "motor_yok", "Motor sessiz")]
    assert _saglik_calistir(monkeypatch, tmp_path, kritik, [], ek=("--dogrula-sn", "1")) == []
    assert len(_saglik_calistir(monkeypatch, tmp_path, kritik, kritik, ek=("--dogrula-sn", "1"))) == 1


def test_saglik_pencerede_yalniz_kritik_gider_ve_baglam_satiri(monkeypatch, tmp_path):
    uyari = [saglik.Bulgu("UYARI", "pano_bayat", "Pano eski")]
    kritik = [saglik.Bulgu("KRITIK", "motor_yok", "Motor sessiz")]
    assert _saglik_calistir(monkeypatch, tmp_path, uyari, uyari, isaret_dk=3) == []                  # 15 dk içinde UYARI gitmez
    g = _saglik_calistir(monkeypatch, tmp_path, kritik, kritik, isaret_dk=3)
    assert len(g) == 1 and "Motor sessiz" in g[0] and "⏱ son güncelleme 3 dk önce" in g[0]
