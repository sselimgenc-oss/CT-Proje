# Ajan kuralları (Codex ve diğer ajanlar her oturumda okur)

Bu repo bir copy trade araştırma projesidir (Hyperliquid; 2026-10-27 itibarıyla strateji araştırması kapandı ve silindi). Lider: Claude (denetler, birleştirir). Karar: kullanıcı.

## Başlarken
1. `main`'i çek; işe `main`'den yeni bir dal aç: `codex/<iş-adı>`.
2. Önce `DURUM.md`'yi oku (güncel durum ve kararlar), sonra sana verilen görev belgesini (`docs/GOREV_*.md`).
3. Belgede yazmayan bir karar gerekiyorsa **dur**, soruyu `docs/codex_durum_<iş>.md`'ye yaz; tahminle ilerleme.

## Değişmez kurallar
- **Repo herkese açık:** API anahtarı, şifre, token, kişisel veri asla commit edilmez. Anahtarlar yalnız GitHub
  Secrets'ta; para çekme yetkisi kapalı.
- **Gerçek para, aracı kurum bağlantısı, emir yok.** Paper yalnız sanaldır.
- **Yöntem, kapı, eşik ve karar kodu değişmez** (`docs/KAPI_V3.md`, `copytrade/kurallar.yaml`) — görev belgesi
  açıkça istemedikçe. Yeni ölçümler bilgi amaçlıdır.
- **Testler zayıflatılmaz, atlanmaz, silinmez.** Yeni kod test ile gelir.
- **`main`'e doğrudan push yok.** PR açılır; birleştirmeyi lider yapar.

## Kabul kanıtı (2026-10-27, Sol 6.1 denetimi sonrası)
- Hesap değiştiren her PR, elle hesaplanmış **altın örnek** testleriyle gelir (girdi + beklenen sayı).
- Veri üreten işlerde PR açıklamasına çıktı özeti eklenir: satır sayısı, kapsam, her sütunun min/medyan/max'ı.
- "Bitti" yalnız kabul kanıtı ve (varsa) canlı koşu sonucuyla söylenir; hata `|| true` ile örtülmez.
- Lider bu üçü olmadan birleştirmez.

## PR'dan önce
- Tam test paketi: `python -m pytest -q` — sonucu PR açıklamasına yaz.
- PR açılamazsa (yetki/ağ) dalı push etmek yeterli; durum dosyasına not düş.
- Ağ engeli (proxy 403 vb.) varsa uydurma sonuç yazma; işi GitHub Actions iş akışına taşı ya da durumu bildir.

## Dil
Belgeler ve durum notları Türkçe, kısa ve maddeli.

## Kalite kuralları (kullanıcı kararı 2026-10-30; ilk iki günün hatalarından)
1. **Önce küçük gerçek veri denemesi.** Yeni iş akışı, analiz ya da büyük koşu önce küçük gerçek veriyle (ör. 1 pencere × 50 hesap,
   1 trader, 1 saat) çalıştırılır; çıktı gözle kontrol edilir; sonra tam koşu. Yalnız sentetik test yeterli sayılmaz. PR açıklamasına
   deneme komutu ve çıktının özeti yazılır. Sentetik testlere gerçek verinin uç durumları eklenir (sıfıra yakın payda, boş hesap,
   sayfa/olay sınırı, eksik mum, büyük dosya).
2. **Veri sözleşmesi birimiyle.** `docs/VERI_SOZLESMESI.md`'de her alanın birimi ve anlamı açık yazılır: oran mı yüzde mi (getiri
   oranlardır: 0,012 = %1,2), kaldıraç "x", tutar "$" ve **hangi ölçekte** (trader hesabı mı, 1.000 $ sanal kopya mı), zaman UTC mi,
   koşu başlangıcı mı okuma zamanı mı, kol üyeliği `kol` (ana etiket) mi `kollar` (tüm üyelikler) mi. Yeni alan sözleşmeye yazılmadan
   tüketilmez; tüketen kod sözleşmeye göre test edilir.
3. **Denetimde gerçek çıktıya bakmak zorunlu.** "Testler yeşil" birleştirme için yetmez: denetçi değişikliğin gerçek veriyle ürettiği
   çıktıya (sayı, ekran görüntüsü, rapor) bakar ve akıl sağlığını kontrol eder (ör. getiri milyonlarca % olamaz, sanal kasa 1.000 $

## Sadeleştirme kuralları (kullanıcı kararı 2026-10-30; K‑10; kural 4 K‑11 ile kaldırıldı)
5. **Strateji kilitli.** Seçim sürümü, oda/kontrol listeleri, eşikler ve ön kayıt yalnız kullanıcının açık kararıyla değişir.
6. **Hesap değişikliği yan yana.** Kopya hesabını değiştiren iş eski seriyi silmez/yeniden yazmaz; yeni sürüm (v2) yanında yayımlanır.
   PR'da eski ↔ yeni sayılar yan yana (oda, kontrol, O10); açıklanamayan fark varsa birleştirilmez. O10 altın örnek testi zorunlu.
7. **Her iş tek yerde.** Aynı hesap ikinci bir yerde yazılmaz: veri bir kez çekilir, hesap yalnız motorda yapılır, ekranlar
8. **Tek yazar, tek denetçi.** Bir dönemde kodu bir ajan yazar (K‑11 ile Sonnet, tek lider ve birleştirme yetkili), bir ajan denetler (Codex/Sol).
