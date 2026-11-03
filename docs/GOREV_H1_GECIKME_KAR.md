# GÖREV H1 — Gecikme–kâr ölçümü (K‑17, `docs/FAZ1_ANLIK_KOPYA.md`)

Yalnız ölçüm. Seçim, kapı, eşik ve karar kodu DEĞİŞMEZ (kural 5–6); v1/v2/v3 serileri silinmez/yeniden yazılmaz; sonuç yanında yayımlanır.

## Girdi
- İzleme listesi (`copytrade/izleme_listesi.yaml`) satırları; `--idler` ile alt küme (varsayılan: hepsi). Her satır: `id`, `adres`, `t0` (UTC gün), isteğe bağlı `tarz`.
- Hyperliquid herkese açık veri: perp dolumları (`userFillsByTime`), funding, 1 dk ve 1 sa mumlar. Anahtar/emir yok.
- Maliyet: `kurallar.yaml` `maliyet_taker` (0,00045) + `maliyet_kayma` (0,0005) — ORAN, tek yön. `--taker`/`--kayma` ile geçersiz kılınabilir (varsayılan değişmez).
- `--pencere dakika` (varsayılan): etkin başlangıç `max(t0, şimdi − 4800 dk)`; tüm gecikmeler gerçek 1 dk açılışıyla. `--pencere tam`: t0'dan; eski dolumlar saatlik açılışla yaklaşık.

## Yöntem (tek motor, kural 7)
`kopya_v3.hesapla` aynı dolumlar için gecikme 0/1/5/30/120 dk ile çağrılır. Hesap `defter.copy_ledger`'dadır; bu iş yalnız veri çekimini ve döngüyü ekler.
- **Anlık (0):** yürütme fiyatı = trader dolum fiyatı `px`, zamanı = dolum zamanı; maliyet = taker + kayma (diğer gecikmelerle aynı oran). Mum gerekmez.
- **1/5/30/120:** yürütme = hedef dakikanın (dolum + gecikme, dakikaya yukarı) 1 dk mum açılışı (`execution_candles`), eski dolumda saatlik açılış (yaklaşık, işaretli).
- Yürütme zamanı gelmemiş dolum `bekleyen`dir, fiyatsız SAYILMAZ (A4‑3b / B17).

## Çıktı (`gecikme_kar/gecikme_kar.json` + `.md`) — alanlar ve birimler `docs/VERI_SOZLESMESI.md` §4b
- Trader başına, her gecikme için: `net` (ORAN; 1.000 $ sanal kopya ölçeği), `islem` (adet), `fiyatsiz` (adet), `bekleyen`, `yaklasik`.
- `ozet`: anlıkta kazanan/kaybeden/sıfır/hesaplanamayan trader sayısı; anlık − 30 dk net farkı (oran puanı) min/medyan/maks/ortalama.
- Zaman UTC. Getiri ORAN (0,012 = %1,2).

## Kabul
2 altın örnek + uç durum testleri (`tests/test_gecikme_kar.py`); küçük gerçek veri denemesi (`.github/workflows/gecikme_kar_deneme.yml`, 2–3 trader); PR'da test sonucu, komut, çıktı özeti, mevcut gecikmeli v3 ↔ yeni sayılar yan yana.

## Varsayımlar / açık
- Anlık = trader dolumuyla aynı fiyattan dolum (+kayma+taker); algılama/emir gecikmesi sıfır sayılır (gerçeği H2).
- Kayma tüm gecikmelerde aynı sabit oran (gecikmeye göre değişmez).
