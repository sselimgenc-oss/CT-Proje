# İlk 11 kadro v1 — Faz 1 karar belgesi

Bu belge Faz 1 kadro kurallarını kaydeder. **Veri kaynağı, birim, pencere ve iş akışı tanımı:** `docs/ILK11_SECIM_SARTNAME.md`
(K‑12, 2026-11-02). Çelişkide K‑12 ve şartname geçerlidir. Mod: PAPER (gerçek emir/cüzdan Faz 3).

## Yol haritası

1. **Faz 1 — Karar belgesi ve veri modeli:** kadro kuralları, puanlama kararları ve verinin nasıl temsil edileceği.
2. **Faz 2 — 13 oda iç kararları:** oda üyeliği ve kadro içi yönetim kararları.
3. **Faz 3 — Canlı hesap/cüzdan ve HL işlem hattı:** ayrı güvenlik ve onay kapıları gerekir. Şu an PAPER modunda kalınır; gerçek emir ve sıcak cüzdan bu fazın hedefidir.

## Kullanıcı kararları

- **Evren:** Yalnız Hyperliquid (HL).
- **Başlangıç:** Pazar 13:00 Türkiye saati. Başarısız olursa aynı dondurulmuş girdi ve snapshot ile iki saatte bir yeniden denenir; yeni veriyle girdi yenilenmez.
- **Kadro:** 50 kişi, uygun evrenden (CT-Kapı `katman` = `izleme_adayi` | `kopyalanabilir`, K‑12 madde 2); İlk 11 = 11, Yedek 11 = 11, PAF = 28. PAF kadronun işlem yapmayan (yalnız izlenen) kademesidir; kadro dışı bu üç grubun hiçbirinde olmayandır.
- **İlk dağıtım (K‑12 madde 3):** Kapı yalnız uygunluğu belirler; sıra **İlk 11 puanıyla** (`copytrade/ilk11.py`, 10 alan) yapılır — yalnız 10 alanın hepsi gerçek veriyle dolduktan sonra (şartname §6: her alan doluluk ≥ %90). En iyi 11 İlk 11'e, sonraki 11 Yedek 11'e, sonraki 28 PAF'a atanır. Başlangıç dağıtımı sonrası terfi/düşme kuralları uygulanır.
- **Form puanı (K‑12 madde 5):** aynı 10 alanlı puan, son 30 günün verisiyle her Pazar yeniden hesaplanır (şartname §4).
- **Geçici kadro (K‑12 madde 4):** 2026-11-01 acil leaderboard-only kadro (`snapshot_id 1d92dd25…`) yalnız "geçici"dir; kapı uygunluğu ve 10 alan yoktur. İlk gerçek Pazar kadrosu yayımlanınca tamamen kaldırılır.
- **Eşikler:** form 60 ve üstü yükselmeye uygun, 40 altı düşmeye adaydır (`ilk11.pazar_gecis`: `>= 60`, `< 40`). Yalnız geçerli Pazar form snapshot'ında uygulanır (bkz. Faz 1 yürütme sınırı); Yedek→İlk 11 ayrıca PAPER kapısını ister.
- **Düşüş:** İki ardışık Pazar geçerli HL işlemi yoksa düşüş uygulanır.
- **Terfi eşitliği:** Önce form puanı; eşitse geçmiş kapı puanı; o da eşitse geçerli gözlem süresi daha uzun olan öne geçer.
- **Yedek → İlk 11 kapısı:** son 6 geçerli PAPER (sanal) işlem; toplam > 0, kazanma oranı ≥ %40, en iyi işlem çıkarılınca toplam > 0. Altıya ulaşmayan geçemez. İşlem kaynağı: `sanal_kopya_v3.kapanan_islemler` (şartname §4.2).
- **Düşüş zinciri:** Form veya iki Pazar hareketsizlik nedeniyle her kademe yalnız bir altına iner: İlk 11→Yedek 11→PAF→kadro dışı. PAF işlem yapan kadro değildir.

## İlk11 İşlem Politikası v1 — kaynak referansı

Yalnız referans; Faz 1'de işlem motoru değişmez (güncel motor `sanal_kopya_v3`).

- Giriş fiyat bandı: üst +%1, alt −%2; azami kaldıraç 5x.
- Marj bazlı stop: −%50. Ana para eşiğinde (%100 marj getirisi) pozisyonun %50'si alınır. Zirve marj getirisi %40'ı gördükten sonra zirveden %45 düşüşte kapat.
- Süreli stoplar: 12 saatte −%25, 24 saatte −%15, 48 saatte −%5. Süreli kâr alma: 24 saatte +%10, 48 saatte +%5. Azami pozisyon süresi 168 saat; trader satışı aynalanır.

## Faz 1 yürütme sınırı

İlk seçimde uygunluk kapısı (K‑12: kapı `katman` `izleme_adayi`/`kopyalanabilir`, taze kapı koşusu) yalnız evreni belirler; İlk 11 puanı uygun tüm HL adayları üzerinde yüzdelik sıralanır, en iyi 50 alınır. Eşit puanlarda form puanı, geçmiş kapı puanı, geçerli gözlem süresi, sonra sabit `id` kullanılır. `ilk11.pazar_gecis` yalnız plan döndürür; izleme listesine yazmaz — planı Pazar işi uygular (şartname §5.3–5.4). Geçerli tek Pazar snapshotında form ≥60 üst gruba yükselmeye uygunluk, <40 bir alt gruba düşüş adayıdır; eksik/geçersiz form hareket üretmez. İki ardışık Pazar aktivitesizliğinde de her grup yalnız bir alt gruba düşer: İlk11→Yedek→PAF→kadro dışı. Terfi yalnız komşu gruplar arasındadır: PAF→Yedek (≥60), Yedek→İlk11 (≥60 ve son 6 geçerli PAPER işlemi toplamı >0, kazanma oranı ≥0,40, en iyi işlem çıkarılınca toplam >0). Kod PAPER planıdır; cüzdan/emir yoktur.

İlgili mevcut alanların sözleşmesi `docs/VERI_SOZLESMESI.md` içindedir. Bu belge yeni veri alanı veya motor davranışı tanımlamaz.

## Pazar snapshot veri biçimi (Faz 1)

10 alan `form_ham` olarak açıkça verilir; kaynak, birim ve pencere `docs/ILK11_SECIM_SARTNAME.md` §3'tedir (leaderboard ROI kullanılmaz).

Snapshot; Türkiye saatiyle Pazar 13:00 anını, kaynak sürümlerini, normalize edilmiş adayları ve ilk 50'nin `ilk11`/`yedek11`/`paf` dağılımını taşır. Kanonik JSON gövdesinin SHA-256 özeti `snapshot_id` olur; `snapshot_json` içerik değişimini hash ile doğrular. Bu aşamada snapshot oluşturma saf bir fonksiyondur; dosyaya yazma, kalıcı kayıt veya yeniden deneme orkestrasyonu yapmaz.

**Pazar planlayıcısı teknik notu:** Pazar planlayıcısı yan etkisizdir; ilk koşuyu `Europe/Istanbul` saat diliminde Pazar 13:00’te açar, başarısızlıktan sonra son başarısızlık zamanına iki saat ekleyerek tekrar zamanlar. Her tekrar aynı `snapshot_id` ile doğrulanır; kimlik uyuşmazlığı reddedilir. Başarı sonrası yeni deneme planlanmaz. Henüz snapshot yoksa `snapshot_hazirla` eylemi üretir.
