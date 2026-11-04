# DURUM (lider günceller; tek doğru kaynak)

Son güncelleme: 2026-11-04, lider Claude (Opus). Yazıcı: Sonnet.

## Hedef
Form Radarı v1 (`docs/RADAR_V1.md`): son 7 günde formu yüksek, kopyalanabilir trader'ları bul → PAF'ta ileri sanal kopya ile sına →
teyit edenler İlk 11 → 28 gün ileri deneme ve kontrol grubu sınavı → canlı kararı kullanıcıda.

## İş sırası
| İş | Durum |
|---|---|
| T1 eski sistemi sil (`docs/GOREV_T1_ESKI_SISTEM_SIL.md`) | **Sonnet'te** |
| T1b Cloudflare/VPS kaldır (`docs/GOREV_T1B_SUNUCUSUZ.md`, K‑20) | T1 sonrası Sonnet |
| T2 R0+R1 tarama (`docs/GOREV_T2_RADAR_TARAMA.md`) | T1b ile paralel Sonnet |
| T3 R2 form puanı | bekliyor |
| T4 R3 kadro + ileri deneme + günlük iş akışı | bekliyor |
| T5 R4 risk + R5 kontrol grubu / canlı kapısı raporu | bekliyor |
| T6 pano | bekliyor |

## Kalan altyapı (yeni sistem kullanır)
Kopya motoru (`defter.py`, `kopya_v2…v4`, `golge.py` çıkış kuralları), HL istemcisi (`tarama.py`, `hl_public_adapter.py`), anlık dinleyici
(`dinleyici.py`, `risk_defter.py`; canlıda sunucu gerekir, K‑20), izleme motoru çekirdeği, pano iskeleti, Faz 3 hazırlık modülleri.
Cloudflare ve DigitalOcean yok (K‑20): her şey GitHub Actions + veri dalı.

## Belgeler
`AGENTS.md` (kurallar) · `docs/KARARLAR.md` · `docs/RADAR_V1.md` (strateji) · `docs/VERI_SOZLESMESI.md` · `docs/GOREV_T*.md`
