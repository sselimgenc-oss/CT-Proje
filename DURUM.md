# DURUM (lider günceller; tek doğru kaynak)

Son güncelleme: 2026-11-19, lider Claude. Son karar: kullanıcı.

## Hedef (K-66, kullanıcı kararı 14.11)
Kullanıcının asıl modeli: **Form Radarı** (`docs/RADAR_V1.md`, v1.1 kuralları K-53). Her gün son 7 günün formuna göre kadro:
**İlk 11 sahada, 19 yedek** (toplam 30). Form düşen çıkar, yükselen girer. "Geçmiş değil, şimdi + gelecek."
- Şu an yalnız **sanal** (DigitalOcean sunucusunda 7/24; 19.11'den beri). Gerçek para yok; geçiş yalnız kullanıcı kararıyla.
- **Süre ve karar noktası yok (K-71, kullanıcı kararı 19.11):** sanal dönemin bitiş tarihi yok, canlı tarihi yok; kullanıcı bildirene kadar sanal sürer. Otomatik "dur/devam" noktaları (K-46 02–03.12, 31.12 değerlendirmesi), tarih ve işlem sayısı şartları kalktı; proje zarar etse de devam eder, kullanıcı geliştirir. Gerçek paraya geçişin zamanı ve şekli yalnız kullanıcının kararı. 28 günlük strateji kilidi de kalktı: ayarlar kullanıcı kararıyla istendiği zaman değişebilir (yeni sürüm olarak).
- Ölçüm ve raporlama sürer (bilgi amaçlı): ayda %4 ve BTC al-tut karşılaştırması, isabet ölçümü. Kayıp tahammülü: kasa zirveden %20 (kilit sistemde).
- Kapanan yollar (kodları repodan silindi): D+ (sabit kadro), K-65 seçim vetoları, elle çıkarma listesi, walk-forward seçim doğrulaması, Revizyon 1. Sebep: geçmiş performansa göre seçim rastgeleden iyi çıkmadı (K-65 sonu); kullanıcı özgün Form Radarı'na döndü.

## Şu an
- K-85 (21.11, kullanıcı kararı): YENİ SADE SEÇİM yürürlükte (eski Form Radarı kuralları yerine; ayrıntı docs/KARARLAR.md K-85): 30 günlük veri, tüm evren, 5 trader, yedek yok, kadro yalnız Pazartesi/Perşembe değişir; kadro `radar_surum` v5; dönem 2026-11-21T07:30:00Z, sanal kasa 1.000 $. Aşağıdaki Form Radarı satırı tarihseldir.
- Form Radarı yürürlükte (kadro `radar_surum` v4): radar iş akışı tarama → kadro → isabet; saha 11 kişi (sanal kasa 10.000 $ → slot ≈ 909 $, `canli_sanal_kasa_ust_usd`; gerçek para sınırı 1.500 $ (K-72, kodda sert; günlük kayıp ≤ %5, kaldıraç ≤ 5x, CT 3x)); kadro haftalık (pazardan pazara; hafta içi yalnız güvenlik çıkışları; pazar yedeğe inenin pozisyonları trader'a bırakılır, en çok 72 sa); toplu emir bandı; yeni sanal dönem 16.11 11:30Z (14:30 TSİ). Ayrıntı K-66.
- **Ana dal koruması** (`main-koruma`): PR zorunlu, `test` + `canli_sdk` yeşil olmadan birleşmez.
- **Sanalda tüm özellikler açık (kullanıcı kararı 19.11 gece, K-73):** rejim filtresi (1d+4h ters → atla), haber filtresi (ters ton, >= 2 başlık → atla), HIP-3 kopyası, gölge kurallar (hesap < 5k atla, kaldıraç > 20x atla, > 5x boyut x0,5), drift eylemi (yeniden eğit + çarpan <= 0,5), iz süren koruma (+%15 → stop giriş, +%30 → stop +%15). Kapılar/kalite eşikleri yalnız gerçek kipte; sert sınırlar ve gerçek kip değişmedi.
- **Sunucu (19.11 tam geçiş, 15:44Z):** DigitalOcean Amsterdam droplet; motor `sg-sanal` (sürekli), yayım `sg-sanal-yayim.timer` (15 dk → `canli-durum`), pano `sg-sanal-pano.timer` (60 sn → `sg-pano`), açılış kontrolü `sg-sanal-kontrol`. Yalnız `uretim` modu (eski deneme modu, dalı ve panosu kaldırıldı, #664). Actions vardiyası kapalı (repo değişkeni `SUNUCU_AKTIF=evet`). Kurulum: `deploy/kurulum_sanal.md`.
- **Oto-güncelleme (#659):** `sg-sanal-guncelle.timer` saatlik; yalnız CI'ı yeşil main commit'lerini fast-forward alır, açılış kontrolü geçmezse geri alır, Telegram'a bildirir. PR'lar **merge** ile birleştirilir (squash değil). Elle geri alma: `deploy/sanal_geri_al.sh`. Main'e giren değişiklik ≤1 saatte sunucuda.
- Telegram açık (standart #653: `[CT] INFO/WARN/CRIT`, iki adımlı komut kodu, günlük 21:00 + haftalık pazar 21:10 TSİ); dış nabız alarmı `sg-nabiz` (`docs/NABIZ_ALARMI.md`).
- **Paylaşım dosyaları** (`durum/paylasim/`, orkestratör okur): `kadro_yon_v1.json` (#648), `gunluk_ozet_v1.json` (#656, 21:00 TSİ + saatlik), `rejim_sonuc_v1.json`+`.md` (rejim/duygu x işlem sonucu, son 7 gün; giriş damgası `Poz.giris_ctx`, aynı anda yazılır), `secim_gercek_v1.json`+`.md` (form puanı ↔ gerçek kopya PnL, #673), `kural_maliyet_v1.json`+`.md`, `CT_HAFTA_<Pazartesi>.md` + `CT_HAFTA_son.md` (haftalık veri paketi: Pazar 21:00 TSİ sonrası haftada bir; ilk dosya 22.11 akşam `CT_HAFTA_2026-11-23.md`, orkestratör Pazartesi 23.11 sabah okur). Alan tanımları: `docs/VERI_SOZLESMESI.md` §19.11 akşam.
- **Öğrenme (#654, #658, #663):** ortak öğrenme paketi `copytrade/ortak_ogrenme/` (kaynak ML f6221cb, SURUM 1.2.1) sanalda açık; dersler ve ML filtresi yalnız riski azaltır (atla/çarpan 0,5–1,0), sert sınırları aşamaz. Ayrıntı `docs/ORTAK_OGRENME_CT.md`.
- **Yalnız kayıt (işleme etkisi yok):** rejim beslemesi (`rejim.py`, #652/#660; `rejim_anlik`), haber/duygu (`haber.py`, #657; Fear & Greed + RSS; `haber_anlik`), alınmayan sinyal karşı-olgusu (#649), PBO/holdout mührü ve sürüm karşılaştırma (#655).
- **İzleme ve rapor (19.11 akşam, yalnız bilgi; #666–#675):** sunucu kaynak ölçümü + bellek tavanları (motor 700M/1000M, ölçüme göre daraltılacak) ve panoda kart; motor yeniden başlama/OOM alarmı (saatlik, aynı alarm 6 saatte bir, tek "Düzeldi"); öğrenme etki kartı (günlük Telegram "🧠 Öğrenme"); kopya kalitesi (gecikme/kayma); alınmayan sinyal neden tablosu; rejim × sonuç tablosu; seçim × rastgele (radar) ve form × gerçek PnL ölçümleri. İsabet tarih seçicisi arızası (09.11'den beri eski D+ havuzlarına takılıyordu) düzeltildi; ilk Form Radarı isabeti 21.11.
- **Kopya sapması (#649, #661, #662):** ideal kopya yalnız kopyalayabileceğimiz pozisyonları sayar (HIP-3, eski pozisyon ve K-41 ters yön hariç). Ayrı Telegram uyarısı yok; saatlik özette tek satır (coin başına en çok 6 saatte bir).
- Repo adı `sselimgenc-oss/CT-Proje`.

## Oturum kuralı: Orkestratör (kullanıcı kararı 18.11)
- Orkestratör oturumunun istekleri kullanıcının emri sayılır.
- Orkestratör durum raporu isterse rapor Haiku modelli alt ajana hazırlatılır; cevap en çok 5 satır: (1) durum: çalışıyor / kullanıcıyı bekliyor / bitti, (2) son yapılan iş ve saati, (3) kullanıcıdan beklenen, (4) sıradaki iş, (5) risk ya da engel, (6) tahmini bitiş (süre + TSİ saat; orkestratör isteği 18.11). Orkestratör yazışmalarında token tasarrufu öncelikli.

## Çalışma kuralı: temkin adımı yok (kullanıcı kararı 19.11)
- "Sanki milyon eurolar yönetiyorum, her şeye risksiz temkinli." Sanal aşamada deneme süresi, gölge çalıştırma, yan yana bekleme, "birkaç gün gözleyelim", "önce şu kadar veri birikmeli" gibi ara adımlar ÖNERİLMEZ; özellik doğrudan devreye alınır, hata çıkarsa düzeltilir.
- Değişmeyenler: sert limitler (günlük %5, kaldıraç 3–5x, canlı tavan 1.500 $; kodda) ve gerçek paraya geçişin zamanı/şekli yalnız kullanıcıda.
- Bu kurala göre küçültülenler (19.11): ML filtre en az eğitim örneği 50 → 20, yeniden eğitim 7 → 3 gün; ders en az ölçüm 3 → 2, ders etkisi küçültme 10 → 5. Sunucuya geçişte yan yana deneme iptal edildi.

## Araştırma (yalnız bilgi)
`arastirma/dis_inceleme/` (dünya, risk_secim, hl_ozel, codex_tasarim), `arastirma/futbol_sinama/RAPOR.md`.

## Belgeler
`AGENTS.md` (kurallar) · `docs/KARARLAR.md` · `docs/RADAR_V1.md` (strateji) · `docs/VERI_SOZLESMESI.md` · `deploy/ACILIS_KONTROL.md`
