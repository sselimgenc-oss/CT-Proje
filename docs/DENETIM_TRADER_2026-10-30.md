# Derin denetim — copy-trader gözüyle (2026-10-30, Claude; kanıtlı)

Kaynak: `copytrade/izleme_motoru.py`, `copytrade/defter.py`, `copytrade/secim.py`, `worker/src/index.js`, canlı `durum.json`
(üretim 2026-10-30T00:06Z, 91 trader), kapı sonucu `copytrade/kapi/2026-10-28/sonuc.csv` (15.131 hesap; adım 1–2'yi geçen 345).

## 1. Kritik (strateji/para kaybettiren)
**K1. Gecikme stratejinin avantajını yok ediyor — kendi kapı verimiz kanıtlıyor.** Adım 1–2'yi geçen 345 hesabın maliyet sonrası
kopya getirisi (medyan, % olumlu): 0 dk **+%6,38 / %65** · 5 dk **+%0,61 / %51** · 30 dk **−%0,39 / %48** · 120 dk **−%1,40 / %45** ·
480 dk −%2,02 / %43. Avantaj ilk 5 dakikada büyük ölçüde gidiyor; bizim 30/120 dk gecikmemizde medyan kopya **zarar**. Öneri: hedef
gecikme ≤ 5 dk (Worker zaten dakikalık); seçim puanı 5 dk'da dayanıklı avantaj (`gecikme_5dk_net` ve 0→5→30 düşüş eğimi).
**K2. Kopya ölçeği ilk okumadaki hesap değerine sabit (`saved['kopya_paydasi']`, izleme_motoru.py:636).** `defter.capital_scale` zaman
serisi destekliyor ama sabit sayı veriliyor. Trader para yatırınca kopya maruziyeti katlanıyor. Kanıt: O10 hesap değeri 13.629 $ →
28.550 $; O10 sanal kopyası 1 günde **−%115,7** (gerçekleşen −%99,6). Odanın −%9,9 ortalamasının ~6,4 puanı yalnız O10.
**K3. Sanal kasa sıfırın altına düşebiliyor; likidasyon/taban yok.** O10 bakiyesi < 0. Gerçek hesapta likidasyon olurdu; sanal defter
kaybı sınırsız taşıyor → oda ortalaması tek trader'la bozuluyor. Öneri: sanal likidasyon kuralı + kopya kaldıraç tavanı.
**K4. Fonlama, kopyalanmayan (t0 öncesi) pozisyonlar için de sanal kasaya yazılıyor.** `copy_actions` miras pozisyonu kopyalamıyor ama
`copy_results` trader'ın t0 sonrası **tüm** funding'ini hesaba oranlıyor (satır 346–352). Büyük miras pozisyonlu trader'larda (O15 ETH)
sanal getiri fonlamayla yanlış şişer/erir. Öneri: funding yalnız açık kopya lotlarına, lot büyüklüğüyle.
**K5. Kopyanın kendi risk kuralı yok.** Çıkış yalnız trader'ın çıkışı; stop, en uzun tutma, zararda ekleme kuralı yok. 18 odadan 7'si
kırmızı (4'ünde "martingale işareti"/"koni altı") ama kopya sürüyor.
**K6. Toplam kaldıraç kontrolsüz.** Oda pozisyonları sanal ölçekte brüt ~103 bin $ / 18 bin $ sermaye ≈ **5,7x**; net long (HYPE, BTC,
GOLD). Oda düzeyinde tavan yok.

## 2. Önemli (ölçüm/veri doğruluğu)
**Ö1.** Kasa tablosu trader'ın güncel pozisyonlarını gösteriyor, sanal lotları değil (Sol; görevde madde 8).
**Ö2.** Düşüş (drawdown) günlük eğriden hesaplanıyor (`copy_results` satır 407): gün içi düşüş görünmüyor, risk eksik ölçülüyor.
**Ö3.** Kayma sabit %0,05 (kurallar.yaml `maliyet_kayma`); küçük coin/HIP‑3 için düşük (duyarlılıkta %0,125–0,34). Ana karar maliyeti iyimser.
**Ö4.** Seçim puanı tek gecikmede örneklem içi getiri (`secim.puan`): en iyi %15 seçimi "kazananın laneti"ne açık; ileri ölçüm (K‑8) iyi adım.
**Ö5.** API son 10.000 dolum sınırı: çok aktif trader'larda geçmiş eksik → sahte yetim/mutabakat kırmızısı; geçmiş R2 arşivinden okunmalı.
**Ö6.** 2 oda trader'ı `gecerli=false` (O11, O17: veri hatası) ama sonuçları oda ortalamasında.

## 3. Mükerrerlik / fazlalık
**M1.** Dolumlar üç yerde ayrı çekiliyor: R2 arşivi (saatlik), izleme motoru, Telegram Worker (dakikalık). API yükü ×3, mantık iki dilde
(Python `fill_events` ↔ JS `orderEvents`) → sapma riski. Öneri: arşiv tek kaynak.
**M2.** İki gölge hesabı: araştırma `golge.py` ve izleme `copy_results/defter`. Tek motor olmalı.
**M4.** ~10 iş akışı + GitHub zamanlayıcısı + veri dalı (git) depolama: kırılgan (267 MB vakası). Saatlik veri R2'de, zamanlama tek yerde.

## 4. Güvenlik / açık
**G1.** Worker `GET /kararlar` kimliksiz herkese açık (index.js:357): kullanıcının Açtım/Atladım kararları dışarı açık. Gizli anahtar ekle.
**G2.** Repo herkese açık; adresler kamuya açık veridir, sorun değil. Anahtarlar secret'ta (doğru).

Saniyelik kopya (bizde 30/120 dk — K1), tek portföy + netleştirme (bizde brüt/net farkı şu an %18; büyüdükçe artar), stop kapanışları
(K5), işlem başı sabit küçük tutar (bizde hesap oranı — K2 riski), kapanış nedeni, 5 dk güncelleme, otomatik terfi/düşme. Bizim
üstünlüğümüz: kontrol grubu, ön kayıt, bağımsız denetim, ileri ölçüm.

## 6. Öneriler (öncelik)
1. **Gecikme ≤ 5 dk'ya inme planı** (K1): sanal defteri 5 dk ile paralel çalıştır (yeni kol/alan, ön kayıt değişikliği → kullanıcı kararı).
2. **K2 + K3 + K4 düzeltmesi** (kopya ölçeği zaman serisi, sanal likidasyon, funding yalnız kopya lotlarına): mevcut sonuçlar yanıltıcı.
3. **Kopya risk kuralları** (K5) + oda kaldıraç tavanı (K6) — sanal defterde ölçülerek.
4. Seçim puanını 5 dk dayanıklılığı + ileri veriyle yeniden tanımla (Ö4; yeni seçim sürümü, kullanıcı kararı).
5. Tek veri kaynağı (M1, Ö5), tek gölge motoru (M2).
6. Kasa tablosu sanal lotlardan, gün içi düşüş, gerçekçi kayma (Ö1–Ö3).
7. `/kararlar` erişim anahtarı (G1).
