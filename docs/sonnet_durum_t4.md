# T4 durum notu (Sonnet) — belgede yazmayan, tahminle seçilen kararlar (lider onayına)

1. **Tek PR.** Motor, Telegram, kurulum ve vardiya iş akışı tek PR'da (görevde "gerekirse 2 PR" yazıyor; bağımlılık yoğun olduğu için bölünmedi).
2. **Dinleyici yeniden kullanımı (kural 7):** `copytrade/dinleyici.py` (`Dinleyici`) alt sınıflanır (`CanliDinleyici`): WS, `trades` + ilk 10 adres için `userFills`, tekilleştirme, kopma → REST dolgusu aynen; yalnız `risk_isle` kancası motor kuyruğuna bağlanır. `risk_defter.py` / `live_koruma.py` kullanılmadı (sabit tutar boyutu yerine `boyut.py`; K‑28).
   HL kullanıcıya özgü abonelik sınırı (≈ 10 adres) nedeniyle `userFills` ilk 10 adrese, tüm saha `trades` kanalından izlenir; `trades` olaylarında `startPosition` yok → motor trader pozisyonunu kendisi izler (REST başlangıç + `poz_senkron` her `canli_hesap_okuma_sn`).
3. **Trader hesap değeri (oran paydası):** `clearinghouseState.marginSummary.accountValue` (ana dex), 10 dk önbellek; T3 radarındaki `accountValue` ile aynı kaynak olmayabilir (perp + spot farkı) — gözlem notu.
4. **Saha kuralı yorumları:** (a) "Günde ≤ 2 değişiklik" = saha GİRİŞLERİ (boş slot doldurma + değiştirme); düşmeler sayılmaz; ilk gün kurulumu sayılmaz. (b) Kadro dışı (kadro.json'da yok ya da sıra > 30) = "form sırası" nedeniyle SONUÇLA düşme (14 gün bekleme). (c) Kaldıraç ihlali = R1 elemesi → sonuçla.
   (d) "72 sa işlem yok" ölçümünün tabanı son WS dolumu ya da (hiç yoksa) saha giriş anıdır. (e) Sahadan inen adres 24 saat boyunca `inen` kalır; bu sürede yeniden girişe aday olamaz.
5. **Korelasyon:** `kadro.json korelasyon` yalnız İlk 11 için; ilişki yoksa (çift matriste yok) "ilişkisiz" sayılır. Kural "bağlı bileşen ≤ 2 kişi" olarak uygulanır (a–b ve b–c ≥ 0,7 ise üçlü yasak).
6. **Patlama freni:** 8. yeni coin açılışı dahil ondan sonra 30 dk yeni açılış yok; "yeni coin" = bizde o coinde pozisyon yokken açılış.
7. **Kaçan dolum penceresi:** açılışta/dolguda REST ile tamamlanan dolumlar `canli_kacan_pencere_dk` (60 dk) ile sınırlı; daha eskisi yalnız trader izleyicisini günceller (saatler önceki açılışı şimdiki fiyatla kopyalamak risk; belgeye ek). `gec_goruldu` işaretlenir, emir o anki defterle.
8. **Mutabakat eşiği:** |fark| nosyoneli > kasa × %1 (1.000 $ → 10 $). Sanal kipte "tutarlılık" = açık pozisyonlu coinlerin mark'ı ≤ 300 sn eski + başlangıç marjı toplamı özsermayeyi aşmıyor.
9. **Vardiya devri:** `concurrency` kuyruğu (iptal yok) + `kilit.json` (20 dk nabız). 4 saatte bir cron, vardiya 4 sa 15 dk: kuyrukta hep bir sonraki bekler, eski bitince hemen başlar (boşluk/çift emir yok). Durum 15 dk'da bir veri dalına yazılır.
10. **Telegram:** `/dur` ve `/durum`; gönderim arka plan iş parçacığında (emir hattı beklemez). `K‑13` iş akışı taramasına tek istisna: `canli_vardiya.yml` Telegram secret'larını ortama geçirir. Secret yoksa kanal kapalı (yalnız kayıt).
11. **Gerçek kip kodu yazıldı ve sahte exchange ile sınandı, ÇALIŞTIRILMADI.** SDK sürümü `hyperliquid-python-sdk==0.24.0` (2026-06-04, ≥ 2 hafta). `kip_belirle`: `GITHUB_ACTIONS=true` iken ret.
12. Funding hesaba girmez (T2 ile aynı v1 kararı).

## K-35 (lider denetimi) notları
13. **v4 sınırları v5'ten kaldırıldı (lider onayına):** `kopya_v5` gerçekte `kopya_v4` risk katmanını da uyguluyordu — emir başına 100 $ ve trader başına toplam 200 $ (referans kasa 1.000 $). Bu, 272,7 $'lık slot toplam tavanından ÖNCE devreye girip toplamı 200 $'da tutuyordu; canlı motor ise 272,7 $'a kadar açardı → R1/6 canlıdan farklı sayı görürdü
    (K‑35 "R1/6 aynı sayıyı görsün" ile çelişir). Bu yüzden `kopya_v5(k35=True)` bu iki sınırı kapatır; HL azami kaldıraç/teminat sınırı kalır. Eski davranış yalnız karşılaştırma için `k35=False` (radar `--v4-yan-yana` → `v5_onceki_kopya_getiri_7g`).
    Etki: altın örnek (3 coin, 150k/160k/50k $, slot 90,91): eski kural 100 + 100 + 0 = 200 $ nosyonel, yeni 136,36 + 136,36 + 0 = 272,73 $.
14. **`slot_tavani` etiketi** eski `tavan_kirpildi` (artırma yolu) yerine geçti; tek emir tavanı (3 × slot) hâlâ `tavan_kirpildi`.
15. **Gerçek kipte kasa değişimi:** `hesap.json` kasa ayarı/etkin kasa değişince SIFIRLANMAZ (pozisyon/K‑Z kaydı korunur), yalnız `kasa_usd` güncellenir; slot ve N yeniden hesaplanır.
16. **Marj tavanı** başlangıç marjını `nosyonel / 3` (giriş fiyatı) sayar; serbest kasa = özsermaye (mark dahil). Sayaç `marj_yok` hem kırpmayı hem sıfırlamayı sayar.

## Gerçek vardiya gözlemi — LİDER KARARI GEREKİR (artırma kuralı)
17. **Açılış 11 $'a yuvarlanınca, sonraki "artırma" oransal olarak patlıyor.** İlk gerçek sanal vardiyada (run 41904629030, kayıt `canli-durum-deneme:kayit/2026-11-04.jsonl`) trader `0xc932b572…` `xyz:GEV` (HIP‑3) üzerinde açtı:
    (a) `ac`: kendi payına düşen hedef < 11 $ → `min_emir_yuvarlandi` **11 $**; (b) hemen ardından aynı emrin sonraki dolumu (`artir`, trader pozisyonunun küçük bir önceki değerine göre büyük bağıl artış) → kural §5b "trader'ın değişim oranıyla" = bizim 11 $ × (sonra − önce)/önce
    = **261,73 $** (`tavan_kirpildi`, yani tavana dayandı: 272,73 − 11). Trader'ın gerçek payı (slot × nosyonel/hesap) bunun çok altındaydı; tek bir partial-fill zinciri slotun tamamını bir coine bağladı.
    Neden: büyük trader emirleri birden çok kısmi dolumla gelir; ilk dolum küçüktür (11 $'a yuvarlanır), ikinci dolum "önceki pozisyona göre %2000 artış" gibi görünür. **Öneri (kod değiştirmedim; §5b metni "değişim oranı" diyor):** artırmayı hedef‑tabanlı yap:
    `hedef_toplam = slot × (trader nosyonel sonra / trader hesap)` (tavanlı), `emir = max(0, hedef_toplam − bizim mevcut)`; açılışta olduğu gibi yuvarlama yalnız en küçük hedefte. Karar lider + kullanıcıdadır (RADAR §5b değişikliği, K‑28 etkisi: R1/6 de aynı kuralı görmeli).
    K‑35 slot toplam tavanı bu durumun zararını 3 × slot ile sınırlar ama her seferinde tavana kadar dolması hâlâ beklenen davranış değil.

