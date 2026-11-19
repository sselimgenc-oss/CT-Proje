# Ortak öğrenme (CT) — sade anlatım

Karar: kullanıcı, 19.11. Kardeş ML projesindeki "ortak öğrenme paketi" CT'ye kuruldu ve **sanal kipte AKTİF** (gölge değil). Ama **hiçbir sert sınırı aşamaz**
ve **yalnız riski azaltabilir**: asla büyüklük artırmaz, trader eklemez, radar eşiğine dokunmaz.

## Ne kaydeder?
- Kopyaladığımız her pozisyon **tamamen kapanınca** bir kayıt (Aday) yazılır: hangi trader, coin, yön, kaldıraç kademesi (düşük ≤3x, orta ≤5x, yüksek), süre kademesi, hafta sonu mu, sonuç (R).
- **R nedir?** 1R = pozisyonun en büyük büyüklüğünün %2'si (`ogrenme_r_birim_oran`). R = net kâr/zarar (ücret dahil) ÷ 1R. Yani R, "ne kadar kazandık/kaybettik"i büyüklükten bağımsız ölçer.
- Her kayıt için kodla yazılmış kısa bir **not** (etiketler: giriş, stop, seans, rejim, sonuç, "kaçınılabilir miydi" vb.) üretilir.
- Dosyalar: `durum/ogrenme/adaylar.jsonl`, `notlar.jsonl`, `ders.json`, `uygulama.json`, `izler.json`. Hepsi `canli_yayimla.sh` ile veri dalına (`canli-durum`) yayımlanır, böylece vardiyalar arası kalıcıdır.

## Trader kimliği (gizlilik)
Repo ve veri dalı herkese açık. Bu yüzden **tam cüzdan adresi yeni hiçbir dosyaya yazılmaz.** Trader, `T_` + adresin sha256'sının ilk 6 hex karakteri ile anılır
(örn. `T_3fa91c`). Takma addan adrese geri dönülmez ve eşleme saklanmaz; motor adresi bellekte takma ada çevirir.

## Ders nedir, nasıl doğar?
1. Kayıpla biten bir işlem belli bir koşula uyuyorsa (şu an CT'de ölçülebilen tek koşul: **hafta sonu açılan işlem**) not "ders adayı" önerir: "bu trader'ın hafta sonu işlemlerinden kaçın".
2. Aday ders, doğumundan **sonraki** işlemlerde ölçülür. O koşula uyan işlemler toplamda **kaybettirdiyse** ders "canlı" olur; kazandırdıysa "emekli" olur ve hiç uygulanmaz.
   Etki, az örnekle abartılmasın diye küçültülür (`ogrenme_shrink_n`: n/(n+10)).
3. En az `ogrenme_min_n` (3) işlemle ölçülmeyen ders uygulanmaz. Ölçüm gün sınırında (UTC 00:00'a kadar olan işlemler) yapılır; saatte bir değerlendirilir.

## Ders ne yapabilir? (yalnız risk azaltır)
Bir trader için canlı derslerin toplam etkisi (R):
- ≥ 1,0 R (`ogrenme_agirlik_etki_r`): o trader'ın **yeni açılış/artırma boyutu** 0,5–1,0 arası bir çarpanla küçülür. Çarpan = 1 − 0,5 × etki/3 (en az 0,5; kod çarpanı her koşulda [0,5; 1,0] aralığına sıkıştırır).
- ≥ 3,0 R (`ogrenme_emekli_etki_r`): trader **"emekli"**: yeni açılış ve artırmaları **sonraki haftalık kadro değişimine dek** kopyalanmaz (`emir_yok`, neden `ders_emekli`).
  **Kapanış ve azaltma hiçbir zaman engellenmez.** Hafta değişince emeklilik biter; aynı ders bir daha emekli yaptıramaz (çarpan olarak sürer).

Yapamayacağı şeyler: büyüklüğü artırmak (çarpan > 1 imkânsız), trader eklemek, radar eşiği/ağırlığı değiştirmek, kadro seçmek, gerçek kip kuralları (gerçek kasa tavanı 1.500 $, günlük kayıp %5, kaldıraç ≤ 5x) ve risk modülünü aşmak.
Boyut hesabı ve tüm sert sınırlar dersten SONRA da aynen çalışır; ders yalnız slot çarpanını küçültür ya da açılışı atlatır.

## Geri alma ve fren
Bir ders uygulandıktan sonra, aynı koşuldaki yeni işlemler **kâr getirirse** ders yanlış çıkmıştır:
- Tek bir dersin uygulama sonrası etkisi ≤ −3 R (`ogrenme_geri_alma_r`) → o ders geri alınır (`ders_geri_alindi`, neden `geri_alma`) ve bir daha uygulanmaz.
- Uygulanan derslerin toplamı ≤ −10 R (`ogrenme_fren_esik_r`) → **hepsi** geri alınır (neden `fren`).
- Ders artık geçerli değilse (emekli oldu / örnek düştü) uygulama kendiliğinden kalkar (neden `ders_gecersiz`).
Not: emekli yapılan trader'ın yeni açılışları kopyalanmadığı için o koşulda yeni kanıt birikmez; geri alma esas olarak çarpan aşamasında ve açık pozisyonlarda çalışır.

## Kayıtlar ve bildirim
- Olaylar (`kayit/<tarih>.jsonl`): `ogrenme_aday`, `ders_uygulandi`, `ders_geri_alindi`, `ogrenme_hata`.
- Bir ders uygulandığında **tek** Telegram BİLGİ mesajı gider (sessiz bildirim). Aynı durum tekrar mesaj üretmez.
- Değerlendirme saatte bir, hata sarılıdır: istisna olursa `ogrenme_hata` yazılır, dakikalık döngü etkilenmez.

## Anahtarlar (`copytrade/kurallar.yaml`, `ogrenme_*`)
`ogrenme_aktif` (kapatma anahtarı), `ogrenme_r_birim_oran`, `ogrenme_shrink_n`, `ogrenme_min_n`, `ogrenme_agirlik_etki_r`, `ogrenme_emekli_etki_r`, `ogrenme_fren_esik_r`, `ogrenme_geri_alma_r`, `ogrenme_degerlendirme_dk`.
Her anahtarın yanında açıklama var. Gerçek kipte (`kip: gercek`) öğrenme çalışmaz.

## Kod haritası
- `copytrade/ortak_ogrenme/` — kaynaktan kopya (SG-Github-AB-proje `trader/paket/ortak_ogrenme` @ af68a02). **Değiştirilmez**, güncelleme kaynaktan.
- `copytrade/canli/ogrenme_adaptor.py` — CT'ye özgü çeviri ve uygulama (tek yer).
- Motor temas noktaları (birkaç satır): `Hesap.dinleyici` (dolum bildirimi), `_emir_isle` (emekli engeli + çarpan), dakikalık adım `ogrenme`, `hafta_degisimi` karşılığı.
- Testler: `tests/test_ogrenme_adaptor.py`, `tests/test_ortak_ogrenme_paket.py`.

## Dönem sıfırlanınca
Yeni dönemde `donem_geri.sh` durumu yüklemez; öğrenme kayıtları da sıfırdan başlar (eski veri veri dalı geçmişinde arşivlidir).
