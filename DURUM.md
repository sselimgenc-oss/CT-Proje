# DURUM (lider günceller; tek doğru kaynak)

Son güncelleme: 2026-11-04, lider Claude (Opus). Yazıcı: Sonnet.

## Hedef
Form Radarı v1 (`docs/RADAR_V1.md`): son 7 günde formu yüksek, kopyalanabilir trader'ları bul → PAF'ta ileri sanal kopya ile sına →
teyit edenler İlk 11 → 28 gün ileri deneme ve kontrol grubu sınavı → canlı kararı kullanıcıda.

## İş sırası
| İş | Durum |
|---|---|
| T1 eski sistemi sil | birleşti |
| T1b Worker/sunucu bağımlılıklarını kaldır (`docs/GOREV_T1B_SUNUCUSUZ.md`) | **PR'da, lider denetimi bekliyor** |
| T2 R0+R1 tarama | lider yazacak (T1 birleşince) |
| T3 R2 form puanı | bekliyor |
| T4 R3 kadro + ileri deneme + günlük iş akışı | bekliyor |
| T5 R4 risk + R5 kontrol grubu / canlı kapısı raporu | bekliyor |
| T6 pano | bekliyor |

## Kalan altyapı (yeni sistem kullanır)
Kopya motoru (`defter.py`, `kopya_v2…v4`, `golge.py` çıkış kuralları), HL istemcisi (`tarama.py`, `hl_public_adapter.py`), anlık dinleyici
(`dinleyici.py`, `risk_defter.py`; canlıda sunucu gerekir, K‑20), gecikme ölçümü (`gecikme_kar.py`), izleme motoru çekirdeği, pano iskeleti, Faz 3 hazırlık modülleri.

## Belgeler
`AGENTS.md` (kurallar) · `docs/KARARLAR.md` · `docs/RADAR_V1.md` (strateji) · `docs/VERI_SOZLESMESI.md` · `docs/GOREV_T*.md`

## T1 notu (2026-11-04, Sonnet)
- Eski sistem (kapı, İlk 11 puanı, oda/kontrol, ön kayıt, araştırma, ilgili iş akışı/test/belge) silindi; kalan kod `hl_ortak.py`/`deneme_arac.py`'ye taşınanlarla çalışıyor. Python testleri 872 → 470 (+32 anahtar testi), Worker 28 → 26.
- Açık sorular lider için: `ilk11` adı kalan altyapıda (dinleyici/risk/faz3) duruyor, Worker `kol=oda` bildirimi duruyor, `son_yaz.py` silinmedi — ayrıntı `docs/sonnet_durum_t1.md`.
- `izleme.yml` zamanlaması kapalı (T4'te radar kadrosu için geri gelir); veri dalı `copytrade-kapi` ve eski dallar PR birleşince lider tarafından silinir.
