"""R5-3: Telegram.uyar() gönderim BAŞARISIZ olsa da anahtarı 6 saat kilitliyor: uyarı hiç ulaşmadan 6 saat boyunca tekrar denenmez."""
from copytrade.canli import telegram as tg


def test_basarisiz_uyari_6_saat_sessiz_kalmaz():
    cagri = []
    durum = {"ag": False}
    t = {"s": 1000.0}

    def post(url, yuk):
        cagri.append(yuk["text"])
        if not durum["ag"]:
            raise OSError("ag yok")
        return {"ok": True}
    k = tg.Telegram("T", "1", post, saat_s=lambda: t["s"], uyku=lambda s: None)
    assert k.uyar("hl_okunamiyor", "🚨 ALARM: HL okunamıyor\nx") is False        # ağ yok: gitmedi
    durum["ag"] = True
    t["s"] += 3600                                                                # 1 saat sonra ağ düzeldi, sorun sürüyor
    n0 = len(cagri)
    k.uyar("hl_okunamiyor", "🚨 ALARM: HL okunamıyor\nx")
    assert len(cagri) > n0, "hiç iletilmemiş alarm 6 saat boyunca yeniden denenmedi"
