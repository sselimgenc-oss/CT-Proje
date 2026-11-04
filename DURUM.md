# DURUM (lider günceller; tek doğru kaynak)

Son güncelleme: 2026-11-04, lider Claude (Opus). Yazıcı: Sonnet.

## Hedef
Form Radarı v1 (`docs/RADAR_V1.md`, K‑22…K‑26): her gün son 7 günde formu yüksek, kopyalanabilir trader'ları bul → İlk 11'in tamamını 1.000 $ kasayla
**doğrudan canlı** kopyala (deneme yok, K‑23) → 28 gün sonra büyütme kapısı (kullanıcı kararı).

## İş sırası
| İş | Durum |
|---|---|
| T1 eski sistemi sil | **bitti** (#492) |
| T1b Cloudflare/VPS kaldır (`docs/GOREV_T1B_SUNUCUSUZ.md`, K‑20) | **bitti** (#494) |
| T2 R0+R1 tarama (`docs/GOREV_T2_RADAR_TARAMA.md`) | **Bitti** (#495): 300 aday 33 dk, 429 = 0; gecti 0/300 → K‑31 (getiri sırası), K‑32 (koruma = kopya/ayna, T3'te) |
| T3 tek boyut + K‑32 + R2 form + günlük kadro (`docs/GOREV_T3_FORM_KADRO.md`, K‑28, K‑32) | Sonnet'te: PR açıldı (`claude/t3-form-kadro`); küçük kararlar `docs/sonnet_durum_t3.md` |
| T4 canlı motor (`docs/GOREV_T4_CANLI_MOTOR.md`) | T3 sonrası Sonnet |
| T5 sunucu + canlıya alma (kullanıcı: sunucu, API cüzdanı, 1.000 $) | bekliyor |
| T6 rapor + pano | bekliyor |

## Kalan altyapı (yeni sistem kullanır)
Kopya motoru (`defter.py`, `kopya_v2…v4`, `golge.py` çıkış kuralları), HL istemcisi (`tarama.py`, `hl_public_adapter.py`), anlık dinleyici
(`dinleyici.py`, `risk_defter.py`; canlıda sunucu gerekir, K‑20), gecikme ölçümü (`gecikme_kar.py`), izleme motoru çekirdeği, pano iskeleti, Faz 3 hazırlık modülleri.
Cloudflare ve DigitalOcean yok (K‑20): her şey GitHub Actions + veri dalı.

## Belgeler
`AGENTS.md` (kurallar) · `docs/KARARLAR.md` · `docs/RADAR_V1.md` (strateji) · `docs/VERI_SOZLESMESI.md` · `docs/GOREV_T*.md`

## T1 notu (2026-11-04, Sonnet)
- Eski sistem (kapı, İlk 11 puanı, oda/kontrol, ön kayıt, araştırma, ilgili iş akışı/test/belge) silindi; kalan kod `hl_ortak.py`/`deneme_arac.py`'ye taşınanlarla çalışıyor. Python testleri 872 → 470 (+32 anahtar testi), Worker 28 → 26.
- Açık sorular lider için: `ilk11` adı kalan altyapıda (dinleyici/risk/faz3) duruyor, Worker `kol=oda` bildirimi duruyor, `son_yaz.py` silinmedi — ayrıntı `docs/sonnet_durum_t1.md`.
- `izleme.yml` zamanlaması kapalı (T4'te radar kadrosu için geri gelir); veri dalı `copytrade-kapi` ve eski dallar PR birleşince lider tarafından silinir.
