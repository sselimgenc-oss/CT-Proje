# Lider denetimi — pano, veri, motor davranışı (2026-11-05, gerçek `canli-durum` verisiyle)

Yöntem: `canli-durum` dalının durum ve kayıt dosyaları + `radar:radar/son/kadro.json` alındı. `pano.py` (main f4249c3) bunlarla yerelde çalıştırıldı.
Sayfa 390 px telefon genişliğinde ekran görüntüsüyle incelendi.
Kontrol: özsermaye = kasa + gerçekleşen − ücret + funding + açık K/Z + kapanmış. Sayılar tutarlı (−4,66 $ = 1,49 − 0,61 − 0,01 − 5,52 açık).
Sayfada yatay kaydırma yok.

## A. Kararlar (lider; Sonnet uygular, altın örnek testle)

### K‑38. Azaltma da hedef tabanlı (K‑36'nın simetriği)
- **Bulgu:** üretim vardiyası 42003105254'te 1.535 `min_emir_atlandi` var. Trader pozisyonu küçük parçalarla küçültünce her parça < 11 $ olur ve atlanır.
  Oransal azaltma bir sonraki dolumda "önce"yi yeniden hesaplar; atlanan azaltmalar **kaybolur**. Artırma K‑36 ile hedefe yetişiyor, azaltma yetişmiyor.
  Sonuçta bizim pozisyon trader'ınkine göre sistematik olarak **büyük** kalır.
- **Kural (`RADAR_V1.md` §5b, `boyut.hedef_emir` `azalt`):** hedef = slot × |trader_poz_sonra| × fiyat / trader_hesap (3 × slot tavanlı); fark = biz − hedef.
  - fark ≥ 11 $ → fark kadar azalt;
  - fark < 11 $ → atla (birikir, sonra yakalanır);
  - hedef < 11 $ ve biz ≥ 11 $ → tamamını kapat (`kucuk_kalan_kapat`);
  - trader tam kapanışı → tamamını kapat (değişmez).
- `kopya_v5` aynı fonksiyonu kullanır (K‑28). Kural 6 gereği eski ve yeni R1 sayıları yan yana gösterilir (300 aday `radar_deneme`).
  Motor `azalt`ta da trader hesap paydasını geçirir (K‑36'daki `hesap_yok` hatasından ders: motor testi eklenir).

### K‑39. "Kadro dışı" düşmesi iki ayrı UTC gününde ister; bekleme yok
- **Bulgu:** 05.11'de radar iki kez koştu (01:15 elle, 07:18 geç cron). İkinci kadroda olmayan 3 üye (`0xf90c9e…`, `0xc32f19…`, `0x62edf4…`)
  girişlerinden **3 saat sonra** `kadro_disi` ile düştü ve **14 gün bekleme** aldı. Günde yalnız 10–14 kişi geçtiği için kapıdan bir günlük düşüş
  (ör. 9 işlem) olağandır. 14 gün yasak, iyi trader'ı rastgele cezalandırır.
- **Kural:**
  - `kadro_disi` = üye **iki farklı UTC gününün** kadrosunda yoksa düşer; düşme **sonuç dışıdır**, bekleme yok.
  - Aynı UTC gününde ikinci bir kadro saha kararlarını tetiklemez; motor gün başına yalnız ilk kadroyu uygular. Pano yine en sonuncuyu gösterebilir.
  - Sonuçla düşmeler (slot −%10 vb.) ve 14 günlük bekleme aynen kalır.
- 3 üyenin 05.11 bekleme kaydı K‑39 ile silinir (motor geçişinde tek seferlik, kayda yazılır).

## B. Pano hataları (düzelt)
1. **Zirveden düşüş grafiği yanlış:** `dd` serisi `tepe = risk.zirve` (bugünkü zirve) ile başlıyor. Geçmiş noktalar gelecekteki zirveye göre ölçülüyor.
   Doğrusu: tepe = kasa (ya da serinin ilk değeri), sonra koşan azami.
2. **Günlük K/Z çubukları ilk günü atlıyor:** fark serisine taban olarak kasa (ya da ilk gün başı) eklenmeli.
3. **Özsermaye grafiğinde ölçek yok:** en az/en çok etiketleri ve 1.000 $ (kasa) taban çizgisi eklenmeli. Noktalar zamana göre değil sıraya göre diziliyor;
   x ekseni için ilk ve son saat etiketi yeter.
4. **"FARK" sütunu mutlak değer:** lehimize ve aleyhimize olan kayma ayırt edilmiyor. İşaretli gösterilmeli: aleyhe kırmızı, lehe yeşil.
5. **Markdown ve HTML sayı biçimi farklı:** OZET.md'de `1,000.00 $`, HTML'de `1.000,00 $`. İkisi de Türkçe biçime (`tr_sayi`) geçmeli.
6. **Belge ve kod çelişkisi:** `pano.py` ve `VERI_SOZLESMESI` "Cloudflare Pages" diyor. K‑20 Cloudflare'i kaldırdı.
   Sayfanın gerçekte nerede yayımlandığını yaz (kullanıcıya sor). Eski sistem kalıntısı `.github/workflows/pano.yml` + `copytrade/pano_veri.py` +
   kökteki `pano/` (index.html, pano.js, pano.css, ornek_veri.json) `copytrade-izleme`'ye bağlı ve çalışmıyor; ayrı PR'da kaldır (testleri güncelle).
7. **Pano 4 saatte bir yenileniyor:** durum zaten 15 dakikada bir yayımlanıyor. `pano.py`'yi 15 dakikalık yayım döngüsüne de ekle; sayfa en çok 15 dk bayat olur.
   Bayat uyarısı 6 sa → 1 sa.

## C. Eklenmesi değerli istatistikler (öncelik sırasıyla; hepsi mevcut kayıttan, yeni hesap yok)
1. **Canlı kopya koruması (en önemlisi):** trader başına "bizim slot getirimiz" ve "aynı sürede trader'ın kendi hesap getirisi" yan yana, ve oranı.
   Trader getirisi = (hesap değeri şimdi − girişte) / girişte; `hesap_tr` zaten okunuyor, girişte bir kez saklanır. R1'deki koruma oranının canlı karşılığıdır.
2. **Atlanan sinyaller:** `min_emir_atlandi`, `patlama_freni`, `inen_trader`, `slot_tavani`, `marj_yok`, `gec_acilis` 24 saatlik sayıları ve "atlanan $" toplamı.
   11 $ alt sınırının etkisini kullanıcı görmeli; kasa kararı buna bağlı.
3. **Kapanan işlemler:** sayı, kazanma oranı, ortalama kâr ve zarar, kâr faktörü (trader başına ve toplam).
4. **Maliyet dökümü:** toplam ücret, funding ve kayma ($), brüt K/Z'ye oranı.
5. **Maruziyet:** net uzun/kısa $, brüt/kasa, kullanılan teminat/özsermaye; coin başına %30 tavanına göre doluluk.
6. **Kadro kartına:** `yatirma_payi` (> 0,2 ise ⚠), form bileşenleri (G/K/İ1/İ2/Y/H çubukları), girişten beri trader getirisi (C1),
   trader sayfasına bağlantı (`https://app.hyperliquid.xyz/explorer/address/<adres>`).
7. **Gerek yok:** mum grafikleri, coin logoları, canlı JS akışı, dış kütüphane. Sayfa tek dosya ve hafif kalmalı.

## D. Gözlemler (bilgi; işlem gerekmez)
- **K‑36 canlıda çalışıyor:** BTC 11 $ açılış → aynı dakikada 4 artırma → toplam 135,65 $. Patlama yok, `hesap_yok` 0.
- **Sanal kayma ≈ 0 bp:** 74 dolum, p50 0, en çok 5 bp. Gecikmemiz saniyenin altında olduğu için böyle. R1 1 dk + 5 bp varsayıyor; sanal sonuç iyimser.
  Gerçek kipte gecikme ve kayma farklı olacak, karşılaştırma T5'ten sonra yapılır.
- **Brüt 994 $ = kasanın %99'u:** izole 3x ile teminat ~330 $. Tavanlar içinde.
- **Kadro sırası:** sıra 1 (`0xf3a42f…`, form 75) BEKLİYOR; Yedek sıra 14 (`0xf43a34…`, form 18) sahada ve en çok işlem yapan o. Sebep: günde 2 değişiklik sınırı
  sabah kullanıldı. K‑39 bu çalkantıyı azaltır; sınır şimdilik değişmez.
- **Bu vardiyanın `ozet.json`'unda `acik` ve `rest_429` yok** (T6 öncesi kod). Kadro kartlarındaki K/Z bu yüzden "—". Bir sonraki main vardiyasında dolduğunu doğrula.
