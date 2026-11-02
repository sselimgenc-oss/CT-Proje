# Faz 1 — Anlık kopya (K‑17)

Kullanıcı kararı 2026-11-02: "1 saat zaten çok geç, anlık olmalı işlemlerimiz; bunları da Faz 1'e alalım." Altyapı: küçük sunucu (VPS).
Amaç: canlıda kâr. Trader'ın kendi getirisi değil, **bizim kopyamızın maliyet sonrası neti** önemlidir.

## Mevcut durum (lider incelemesi, 2026-11-02)
- **Seçim 30–120 dk gecikmeyle ölçülüyor.** Kapı adım 3 ve plasebo `kopya_gecikme_dk` (intraday 30, swing 120) ile hesaplanır;
  yürütme fiyatı saatlik mum açılışıdır (`defter.py`). Yani seçim "geç kopyalayan" birine göre yapılıyor: hızlı trader'lar
  cezalanıyor, anlık kopyada kârlı olabilecekler eleniyor olabilir.
- **İzleme saatlik** (`izleme.yml`): canlıda 60 dk'ya kadar geç giriş demek. Canlı için kabul edilemez.
- **Anlık dinleyici kodu zaten var ama kurulmadı:** `hl_public_adapter.py` (WebSocket `userFills` + `userFillsByTime` dolgu),
  `hl_ws_runtime.py`, `hl_ws_dry_run.py`, `faz3_dry_run_service.py` (yalnız dry-run, emir/anahtar yok; `docs/FAZ3_DRY_RUN_SERVIS.md`).
  24 saatlik gerçek koşu hiç yapılmadı.
- **Geçmişte dakikalık fiyat sınırlı:** 1 dk mumlar yalnız yakın geçmiş için tutulur; 30 günlük pencerede anlık kopya mumla
  ölçülemez. Yaklaşık ölçü: trader'ın kendi dolum fiyatı + kayma + taker (gecikme ≈ 0).

## Faz 1'e eklenen işler (H serisi)
| # | İş | Kim | Bağımlılık | Kabul |
|---|----|-----|-----------|-------|
| H1 | **Gecikme–kâr ölçümü.** Kadro adayları için v3 kopya neti yan yana: anlık (dolum fiyatı + kayma + taker), 1, 5, 30, 120 dk. Yalnız ölçüm; seçim değişmez (kural 6). | Sonnet | A4‑3 (v3 doğruluğu) | Trader başına tablo; anlıkta kazanan/kaybeden sayısı; 2 altın örnek; gerçek veri özeti |
| H2 | **Dinleyici dry-run (VPS).** Mevcut WebSocket kodu kadro 50 + referans için çalışır; emir/anahtar yok. Ölçülür: algılama gecikmesi (dolum zamanı → bizim görme zamanımız), kaçan dolum (dolgu ile karşılaştırma), kopma/yeniden bağlanma. Önce 1 saat, sonra 24 saat, sonra 7 gün. | Sonnet (kod + kurulum rehberi), kullanıcı (sunucu hesabı) | Kullanıcı sunucuyu açar | Gecikme medyan/p95 (sn), kaçan dolum = 0, kopma sayısı; JSONL kanıt |
| H3 | **Kopyalanabilirlik seçimde.** H1 sonucuna göre öneri: seçim gecikmesi gerçek gecikmeye (H2 ölçümü) çekilsin mi, çok kısa tutan trader elensin mi. | Lider önerir | H1, H2 | **Kullanıcı kararı** (strateji kilidi, kural 5); eski ↔ yeni kadro yan yana |
| H4 | **Canlıya Geçiş Kapısı taslağı.** Ön kayıtlı şartlar: en az X hafta anlık kâğıt koşusu, en az Y kapanan kopya işlemi, maliyet + funding sonrası net artı, plaseboyu geçmek, en büyük düşüş < Z. | Lider taslak | — | **Sayılar kullanıcı kararı**; sonuç görülmeden yazılır |
| H5 | **Risk sınırları tasarımı.** Trader başına tavan, toplam açık pozisyon tavanı, zarar şalteri (/dur), küçük başlangıç tutarı; dry-run'da uygulanır. | Sonnet | H2 | Dry-run'da sınır ihlali sayılır ve reddedilir |

## Sıra
PR‑3 → tam kapı taraması → A4‑1 → A4‑3 → **H1** → A4‑2 → A4‑4 → **H2** (sunucu hazır olunca) → H5 → H3/H4 (kullanıcı kararı).
Faz 2 (pano) bundan sonra.

## Sunucu (H2) — kullanıcıdan istenecek
- Küçük bir Linux sunucu (1 vCPU, 1–2 GB RAM yeterli). Hesabı ve ödemeyi kullanıcı yapar.
- Dry-run aşamasında sunucuya **hiçbir anahtar/cüzdan konmaz**; veri herkese açıktır. Kurulum adımları H2 rehberinde.
- Canlıda emir de bu sunucudan gider; o aşamanın anahtar ve güvenlik kuralları (K‑7 güvenlik şartları) ayrıca kullanıcı onayıyla.
