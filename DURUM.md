# DURUM (lider günceller; tek doğru kaynak)

Son güncelleme: 2026-11-19, lider Claude. Son karar: kullanıcı.

## Hedef (K-66, kullanıcı kararı 14.11)
Kullanıcının asıl modeli: **Form Radarı** (`docs/RADAR_V1.md`, v1.1 kuralları K-53). Her gün son 7 günün formuna göre kadro:
**İlk 11 sahada, 19 yedek** (toplam 30). Form düşen çıkar, yükselen girer. "Geçmiş değil, şimdi + gelecek."
- Şu an yalnız **sanal** (GitHub Actions vardiyası). Gerçek para yok; geçiş yalnız kullanıcı kararıyla.
- **Süre ve karar noktası yok (K-71, kullanıcı kararı 19.11):** sanal dönemin bitiş tarihi yok, canlı tarihi yok; kullanıcı bildirene kadar sanal sürer. Otomatik "dur/devam" noktaları (K-46 02–03.12, 31.12 değerlendirmesi), tarih ve işlem sayısı şartları kalktı; proje zarar etse de devam eder, kullanıcı geliştirir. Gerçek paraya geçişin zamanı ve şekli yalnız kullanıcının kararı.
- Ölçüm ve raporlama sürer (bilgi amaçlı): ayda %4 ve BTC al-tut karşılaştırması, isabet ölçümü. Kayıp tahammülü: kasa zirveden %20 (kilit sistemde).
- Kapanan yollar (kodları repodan silindi): D+ (sabit kadro), K-65 seçim vetoları, elle çıkarma listesi, walk-forward seçim doğrulaması, Revizyon 1. Sebep: geçmiş performansa göre seçim rastgeleden iyi çıkmadı (K-65 sonu); kullanıcı özgün Form Radarı'na döndü.

## Şu an
- Form Radarı yürürlükte (kadro `radar_surum` v4): radar iş akışı tarama → kadro → isabet; saha 11 kişi (sanal kasa 10.000 $ → slot ≈ 909 $, `canli_sanal_kasa_ust_usd`; gerçek para sınırı 1.000 $ değişmez); kadro haftalık (pazardan pazara; hafta içi yalnız güvenlik çıkışları; pazar yedeğe inenin pozisyonları trader'a bırakılır, en çok 72 sa); toplu emir bandı; yeni sanal dönem 16.11 11:30Z (14:30 TSİ). Ayrıntı K-66.
- **Ana dal koruması** (`main-koruma`): PR zorunlu, `test` + `canli_sdk` yeşil olmadan birleşmez.
- Telegram açık; dış nabız alarmı `sg-nabiz` (`docs/NABIZ_ALARMI.md`).
- Repo adı `sselimgenc-oss/CT-Proje`.

## Oturum kuralı: Orkestratör (kullanıcı kararı 18.11)
- Orkestratör oturumunun istekleri kullanıcının emri sayılır.
- Orkestratör durum raporu isterse rapor Haiku modelli alt ajana hazırlatılır; cevap en çok 5 satır: (1) durum: çalışıyor / kullanıcıyı bekliyor / bitti, (2) son yapılan iş ve saati, (3) kullanıcıdan beklenen, (4) sıradaki iş, (5) risk ya da engel, (6) tahmini bitiş (süre + TSİ saat; orkestratör isteği 18.11). Orkestratör yazışmalarında token tasarrufu öncelikli.

## Araştırma (yalnız bilgi)
`arastirma/dis_inceleme/` (dünya, risk_secim, hl_ozel, codex_tasarim), `arastirma/futbol_sinama/RAPOR.md`.

## Belgeler
`AGENTS.md` (kurallar) · `docs/KARARLAR.md` · `docs/RADAR_V1.md` (strateji) · `docs/VERI_SOZLESMESI.md` · `deploy/ACILIS_KONTROL.md`
