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
