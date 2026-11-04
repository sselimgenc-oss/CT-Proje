# DURUM (lider günceller; tek doğru kaynak)

Son güncelleme: 2026-11-04, lider Claude (Opus). Yazıcı: Sonnet.

## Hedef
Form Radarı v1 (`docs/RADAR_V1.md`, K‑22): son 7 günde formu yüksek, kopyalanabilir trader'ları bul → İlk 11 → ilk 4'ü 100 $ kasayla
**doğrudan canlı** kopyala (deneme yok, K‑23) → 28 gün sonra büyütme kapısı (kullanıcı kararı).

## İş sırası
| İş | Durum |
|---|---|
| T1 eski sistemi sil (`docs/GOREV_T1_ESKI_SISTEM_SIL.md`) | **Sonnet'te** |
| T1b Cloudflare/VPS kaldır (`docs/GOREV_T1B_SUNUCUSUZ.md`, K‑20) | T1 sonrası Sonnet |
| T2 R0+R1 tarama (`docs/GOREV_T2_RADAR_TARAMA.md`) | T1b ile paralel Sonnet |
| T3 R2 form puanı | bekliyor |
| T4 canlı motor (kadro, saha, yürütücü, boyutlandırma, risk, Telegram) | bekliyor |
| T5 sunucu + canlıya alma (kullanıcı: sunucu, API cüzdanı, 100 $) | bekliyor |
| T6 rapor + pano | bekliyor |

## Kalan altyapı (yeni sistem kullanır)
Kopya motoru (`defter.py`, `kopya_v2…v4`, `golge.py` çıkış kuralları), HL istemcisi (`tarama.py`, `hl_public_adapter.py`), anlık dinleyici
(`dinleyici.py`, `risk_defter.py`; canlıda sunucu gerekir, K‑20), izleme motoru çekirdeği, pano iskeleti, Faz 3 hazırlık modülleri.
Cloudflare ve DigitalOcean yok (K‑20): her şey GitHub Actions + veri dalı.

## Belgeler
`AGENTS.md` (kurallar) · `docs/KARARLAR.md` · `docs/RADAR_V1.md` (strateji) · `docs/VERI_SOZLESMESI.md` · `docs/GOREV_T*.md`
