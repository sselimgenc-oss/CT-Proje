# DURUM (lider günceller; tek doğru kaynak)

Son güncelleme: 2026-11-09 16:00Z, lider Claude (Opus). Sonnet emekli (06.11); kodu lider ve lidere bağlı ajanlar yazar, lider denetler ve birleştirir. Son karar: kullanıcı.

## Hedef
Form Radarı v1 (`docs/RADAR_V1.md`): her gün son 7 günde formu yüksek, kopyalanabilir trader'ları bul → İlk 11'i 1.000 $ kasayla kopyala.
Şu an **sanal** (GitHub Actions vardiyası); gerçek para da **1.000 $** ile başlar (K‑50), geçiş kararı kullanıcının.

## Şu an
- **Yeni dönem (K‑49):** 09.11 00:01 TSİ (2026-11-08T21:01Z) sıfırdan başladı; eski veri dal geçmişinde arşivli. Yalnız `canli-durum` (1.000 $); 300 $ seri iptal.
- **Telegram açık** (repo değişkeni `TELEGRAM_ACIK=evet`, kullanıcı 08.11). **Dış nabız alarmı** `sg-nabiz` (Cloudflare cron, 10 dk; son yayım > 45 dk → Telegram; `docs/NABIZ_ALARMI.md`).
- **Ana dal koruması** (`main-koruma` ruleset): PR zorunlu, `test` + `canli_sdk` yeşil olmadan birleşmez, silme/force push yok.
- **Radar v1.1 (K-53, 09.11):** 30 g kârda olmayan alınmaz, kopya işlem ≥ 10, H = 0, önceki kadro üyesi yalnız gerçekten kötüleşirse düşer. İlk v1.1 kadrosu 10.11 radar koşusunda. Doğrulama: 8 haftalık geriye dönük kalıcılık testi (sıradaki iş).

## Denetimler (Fable 06–08.11 + dış denetim 3 tur 09.11) — kapanış: K‑51, K‑52
- `docs/DENETIM_DEVIR_2026-11-06.md` (G-1…G-11), `docs/DENETIM_SECIM_2026-11-08.md` (B1…B17), `docs/DENETIM_PROJE_2026-11-08.md` (G-12…G-24, S-1…S-24).
- Kod maddelerinin tamamı main'de ve testli (#573–#593). Açık kalanlar: S-23 (gerçek HL yanıt kaydı; ilk gerçek deneme), v1.1 adayları (28. gün kararı). A-1 kapandı (token daraltıldı, 09.11).

- **Repo adı 08.11'den beri `sselimgenc-oss/CT-Proje`** (eski `sg-arge` adresleri GitHub yönlendirmesiyle çalışır; kod yeni adı kullanır).

## Takvim
| Tarih | İş |
|---|---|
| 12.11 | İlk isabet ölçümü: yalnız boru hattı kontrolü (K‑46), karar değil |
| 15–16.11 | 1.000 $ sanal 7 temiz gün (K‑50) → gerçek para geçişi kullanıcıyla konuşulur (`deploy/ACILIS_KONTROL.md`) |
| 19.11 | 7 ölçülmüş gün: yalnız "üst sınır < 0" ise dur |
| 02–03.12 | 28 gün / 21 ölçülmüş gün: K‑46 kararı + v1.1 adayları (Fable yeniden denetim) |

## Belgeler
`AGENTS.md` (kurallar) · `docs/KARARLAR.md` · `docs/RADAR_V1.md` (strateji) · `docs/VERI_SOZLESMESI.md` · `deploy/ACILIS_KONTROL.md` · denetim belgeleri (yukarıda)
