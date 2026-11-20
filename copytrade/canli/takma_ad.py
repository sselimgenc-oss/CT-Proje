"""Trader takma adı: telefonda 0x… adresleri ayırt etmek için kısa, sabit ad (örn. "Kartal-78").

Durumsuz ve deterministik: aynı adres her ortamda (pano, Telegram, sunucu, Actions) aynı adı alır;
kalıcı dosya gerekmez, trader sahadan çıkıp dönse de ad değişmez.

!!! UYARI: `KELIMELER` listesinin SIRASI ve İÇERİĞİ ASLA değiştirilmemeli (ekleme, silme, yeniden sıralama
dahil). Değişirse mevcut tüm takma adlar kayar. `tests/test_takma_ad.py` listeyi sabitler. !!!
"""
from __future__ import annotations

import hashlib
import re

KELIMELER: tuple[str, ...] = (
    "Kartal", "Şahin", "Vaşak", "Doğan", "Atmaca", "Çaylak", "Baykuş", "Leylek", "Turna", "Kırlangıç",
    "Karga", "Kuzgun", "Serçe", "Bülbül", "Sığırcık", "Martı", "Pelikan", "Flamingo", "Kaz", "Ördek",
    "Güvercin", "Papağan", "Tavus", "Keklik", "Çil", "Delice", "Yalıçapkını", "Ağaçkakan", "Guguk", "Hüthüt",
    "Aslan", "Kaplan", "Leopar", "Panter", "Çita", "Puma", "Kurt", "Çakal", "Tilki", "Ayı",
    "Geyik", "Ceylan", "Karaca", "Maral", "Yaban", "Dağkeçisi", "Muflon", "Bizon", "Zebra", "Fil",
    "Zürafa", "Gergedan", "Su aygırı", "Maymun", "Panda", "Koala", "Kanguru", "Lemur", "Rakun", "Porsuk",
    "Sansar", "Samur", "Kunduz", "Su samuru", "Sincap", "Tavşan", "Kirpi", "Yarasa", "Yunus", "Balina",
    "Köpekbalığı", "Orkinos", "Hamsi", "Levrek", "Çipura", "Mercan", "Denizatı", "Ahtapot", "Müren", "Kılıç",
    "Yılan", "Kaplumbağa", "Bukalemun", "Gekko", "Timsah", "Kobra", "Akrep", "Arı", "Kelebek", "Karınca",
    "Polaris", "Sirius", "Vega", "Antares", "Altair", "Rigel", "Kapella", "Deneb", "Aldebaran", "Betelgeuse",
    "Kuyruklu", "Samanyolu", "Pleyad", "Orion", "Lyra", "Aquila", "Cygnus", "Draco", "Pegasus", "Fenrir",
)

_HEX2 = re.compile(r"^0x([0-9a-f]{2})[0-9a-f]*$")


def kisa_adres(adres: str) -> str:
    """Ham adresin kısa biçimi (`0x1234ab…`); yalnız detay/tooltip için."""
    return adres[:8] + "…" if len(adres) > 8 else adres


def takma_ad(adres: str) -> str:
    """Adresten sabit takma ad üretir; boş/geçersiz adreste mevcut kısa biçime (`0x1234ab…`) düşer."""
    if not isinstance(adres, str):
        return ""
    a = adres.strip().lower()
    m = _HEX2.match(a)
    if not m:
        return kisa_adres(adres)
    h = int.from_bytes(hashlib.sha256(a.encode("utf-8")).digest()[:8], "big")
    return f"{KELIMELER[h % len(KELIMELER)]}-{m.group(1).upper()}"
