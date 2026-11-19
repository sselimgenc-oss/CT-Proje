# Sanal motoru sunucuya taşıma — sade rehber

Kısaca: şimdi sanal (kâğıt üstü) işlem motoru GitHub'ın bedava makinelerinde 4 saatlik parçalar halinde, art arda çalışıyor. Bunu kiralık bir sunucuya (DigitalOcean) taşıyoruz: motor orada 7/24 kesintisiz çalışacak. Para, cüzdan, anahtar yok; hâlâ sanal. Strateji ve hesap kodu değişmez.

**Üç güvenlik kuralı (hepsi kodda):** iki motor asla aynı anda çalışmaz · önce 2–3 gün ayrı bir deneme dalında yan yana izlenir (canlı pano ve veri dokunulmaz) · geri dönüş tek tıktır.

**Aylık maliyet:** sunucu ≈ **12 $/ay** (DigitalOcean Basic, 2 GB RAM / 1 CPU / 50 GB; yedekleme istenirse +≈2,4 $). GitHub, Cloudflare, Telegram: 0 $. Toplam ≈ 12–15 $/ay. (Fiyatı sunucuyu seçerken ekranda doğrulayın.)

**Sır kuralı:** şifre/token/anahtarı **sohbete asla yapıştırmayın**. Aşağıda "sunucuda dosyaya yazın" denen her şey sunucunun içinde kalır; bana yalnız "yazdım" deyin. Sunucunun IP adresi ve SSH "public" (ortak) anahtarı sır değildir, paylaşabilirsiniz.

---

## A. SİZİN yapacaklarınız (sırayla)

1. **DigitalOcean hesabı açın** (digitalocean.com) ve ödeme yöntemi ekleyin.
2. **Kendi bilgisayarınızda SSH anahtarı üretin** (sunucuya girmek için kimlik). Windows'ta PowerShell, Mac'te Terminal açın:
   `ssh-keygen -t ed25519 -C "benim-bilgisayarim"` → hepsine Enter. Sonra `.pub ile biten` dosyanın içeriğini yazdırın (Windows: `type $env:USERPROFILE\.ssh\id_ed25519.pub`, Mac: `cat ~/.ssh/id_ed25519.pub`). **Yalnız `.pub` dosyası paylaşılır**; `id_ed25519` (uzantısız) dosyası özeldir, kimseye verilmez.
3. **Sunucu (Droplet) oluşturun:** Create → Droplets.
   - Bölge: **Frankfurt (FRA1)** (Amsterdam da olur; ABD seçmeyin).
   - İşletim sistemi: **Ubuntu 24.04 (LTS) x64**.
   - Boyut: **Basic → Regular (SSD) → 12 $/ay (2 GB / 1 CPU / 50 GB)**.
   - Giriş yöntemi: **SSH Key** → "New SSH Key" → 2. adımdaki `.pub` içeriğini yapıştırın. (Parola seçmeyin.)
   - İsim: `sg-sanal`. "Monitoring" açık olsun. Oluştur.
4. **Sunucunun IP adresini bana yazın.** Sonra sunucuya bağlanabildiğinizi deneyin: `ssh root@IP_ADRESI` → "Welcome to Ubuntu" görürseniz tamam (`exit` ile çıkın).
   - Kurulum komutlarını **iki yoldan biriyle** yapacağım: (a) ben komutları yazarım, siz sunucuya bağlanıp yapıştırırsınız ve çıktıyı bana gösterirsiniz (varsayılan, en güvenlisi); (b) bu oturumda sunucuya doğrudan bağlanabiliyorsam ben yaparım. **Özel anahtarınızı bana vermeyin**; (b) için gerekirse sunucuda ayrı bir kullanıcı ve ayrı bir anahtar açılır, onu da birlikte karar veririz.
5. **Ben sunucuda kurulumu yapınca size bir satır "ortak anahtar" (`ssh-ed25519 AAAA… sg-sanal-sunucu`) vereceğim.** GitHub'da depoya ekleyin: depo → **Settings → Deploy keys → Add deploy key** → Başlık `sg-sanal-sunucu` → anahtarı yapıştırın → **"Allow write access" kutusunu işaretleyin** → Add key. (Sunucu bu anahtarla yalnız bu depoya yazar; para/cüzdan yetkisi yoktur.)
6. **`main` dalını koruyun** (deploy anahtarı depoda her dala yazabildiği için): depo → **Settings → Rules → Rulesets → New branch ruleset** → hedef: `main` → "Restrict updates" ve "Require a pull request before merging" açık → bypass listesi boş → Create. (Zaten benzer koruma varsa "yapıldı" deyin.)
7. **Cloudflare pano anahtarı** (sunucunun panoyu yayımlaması için; GitHub'daki mevcut secret'ın değeri geri okunamaz, yenisi gerekir): Cloudflare → My Profile → API Tokens → Create Token → şablon **"Edit Cloudflare Workers"** → oluştur → token'ı bir şifre yöneticisine kopyalayın. Ayrıca "Account ID"yi kopyalayın (Workers & Pages sayfasının sağ tarafında). Sonra sunucuya bağlanıp ben "dosyayı açın" dediğimde `sudo -e /etc/sg-sanal-pano.env` ile dosyaya şu iki satırı **kendiniz** yazın:
   ```
   CLOUDFLARE_API_TOKEN=...
   CLOUDFLARE_ACCOUNT_ID=...
   ```
   (Kaydet: nano'da Ctrl+O, Enter, Ctrl+X.) Bunu boş bırakırsanız motor çalışır ama pano güncellenmez.
8. **Telegram (isteğe bağlı; şimdilik KAPALI kalır, 08.11 kararınız).** Sunucudan bildirim istiyorsanız aynı biçimde `/etc/sg-sanal-telegram.env` dosyasına `TELEGRAM_BOT_TOKEN=...` ve `TELEGRAM_CHAT_ID=...` yazın. İstemiyorsanız hiçbir şey yapmayın.
9. **2–3 gün sonra karar:** doğrulama raporumu (B bölümü) okuyup "geçelim" ya da "bekleyelim" deyin. "Geçelim" derseniz:
10. **GitHub'da tek ayar:** depo → **Settings → Secrets and variables → Actions → Variables** → New repository variable: Ad `SUNUCU_AKTIF`, Değer `evet`. (Bu, Actions vardiyasını kapatır.) Hemen ardından bana "yaptım" yazın; sunucuyu "üretim" moda ben geçiririm (ya da komutu siz yapıştırırsınız).

**Geri dönmek isterseniz (herhangi bir zamanda):** aynı değişkenin değerini `hayir` yapın (tek tık) ve bana yazın. Ayrıntı: D bölümü.

---

## B. Benim (Claude) yapacaklarım

Her adımın çıktısını size gösteririm; beklenen sonucu görmezsem durup size söylerim.
1. Sunucuda `deploy/kurulum_sanal.md` adımları: paketler, `sgsanal` kullanıcısı, SSH anahtarı (özel kısım sunucudan çıkmaz), depo, paketler (imzalı/kilitli sürümler), Cloudflare aracı, servis dosyaları, güvenlik duvarı (yalnız SSH).
2. Ortak anahtarı size veririm (A-5); siz GitHub'a ekledikten sonra yazma denemesi yaparım.
3. **Deneme modu**: `sanal_mod.sh deneme` → sunucu motoru **`canli-durum-sunucu`** adlı AYRI dala yazar, pano **`sg-pano-sunucu`** adresinde (canlı `sg-pano` değişmez), Telegram komutları kapalı. Actions motoru aynen sürer; birbirlerinin dosyasına dokunmaz. Sunucu, başlangıçta Actions'ın o anki durumunun kopyasıyla açılır (aynı dönem, aynı pozisyonlar), sonra ikisi kendi yolunda ilerler.
4. Açılış kontrolü (`sg-sanal-kontrol`): kip sanal, kadro okunuyor, hata yok.

## C. 2–3 günlük yan yana doğrulama (deneme modu)

Her gün bir kez (ilk gün 3 kez) iki dalı karşılaştırırım: `canli-durum` (Actions) ve `canli-durum-sunucu` (sunucu).

| Kontrol | Geçme ölçütü (öneri; sizinle teyit edilir) |
|---|---|
| Sunucu hiç durmadan çalıştı mı (nabız `durum/kilit.json`) | her an < 20 dk eski; kesinti ve yeniden başlatma sayısı günlükte açıklanmış |
| Açık pozisyonların coin/yön listesi | aynı trader sinyallerine aynı pozisyonlar; fark varsa tek tek nedeni açıklanmış (giriş anı fiyatı farkı normal) |
| Özsermaye ve getiri (`durum/ozet.json`) | fark küçük ve açıklanabilir (başlangıçta öneri: 0,5 puan altı); sürekli büyüyen fark = DURUR, araştırılır |
| İşlem sayısı (`kayit/<tarih>.jsonl`) | yakın; sunucuda kaçırılan işlem yok |
| Hata/alarm günlüğü (`journalctl -u sg-sanal`) | açıklanamayan hata yok |
| Pano (`sg-pano-sunucu`) ve veri tazeliği | 15 dk içinde güncel; Actions panosuyla uyumlu |
| Yeniden başlatma testi | sunucuyu bir kez yeniden başlatırım (reboot): motor kendi kalktı, kaldığı yerden devam etti |

Sonuç: size kısa bir tablo + "geçelim / bekleyelim" önerisi.

## D. Geçiş (üretim) ve geri alma

**Geçiş (A-10'dan sonra):**
1. Siz `SUNUCU_AKTIF=evet` yaptınız. Etkisi: yeni Actions vardiyası **hiç başlamaz** (cron, elle çalıştırma, zincir hepsi). Çalışmakta olan vardiya kesilmez, süresi (en çok 4 sa 15 dk) bitince zincir sönmüş olur. Hızlandırmak için o koşuyu Actions'tan "Cancel" edebiliriz; ben `canli-durum` kilidinin "bırakıldı" olduğunu doğrularım.
2. Ben sunucuda `sudo bash deploy/sanal_mod.sh uretim` (onay sorusuna `evet`) → servisleri başlatırım. **Sunucu, Actions vardiyası gerçekten bitmeden başlamaz** (kilit kapısı: en çok 30 dk bekler, sonra bekleyerek yeniden dener). Durum `canli-durum` dalından devralınır (dönem kuralı aynı).
3. İlk 1 saat izlerim: `canli-durum` dalına sunucu işleniyor mu, canlı pano (`sg-pano`) güncel mi, dış nabız (sg-nabiz) ve sağlık kontrolü sessiz mi. Telegram'ı açacaksanız bu aşamada (komutlar için `TELEGRAM_KOMUT=kapali` satırı kaldırılır).
4. Eski deneme dalı (`canli-durum-sunucu`) ve `sg-pano-sunucu` istenirse silinir.

**Geri alma (Actions'a dönüş) — 3 adım, veri kaybı yok:**
1. Sunucuda `sudo systemctl stop sg-sanal` (ben yaparım/siz yapıştırırsınız): motor temiz kapanır, son durum `canli-durum`'a yazılır, kilit "bırakıldı".
2. GitHub'da `SUNUCU_AKTIF` değişkenini `hayir` yapın (tek tık). (Eğer `copytrade/canli/SUNUCU_AKTIF` dosyası da eklenmişse: tek satır `git rm copytrade/canli/SUNUCU_AKTIF` + PR.)
3. Actions → "Canlı vardiya (sanal kip)" → Run workflow (main). Yeni vardiya durumu `canli-durum`'dan alıp kaldığı yerden devam eder. (Sunucu çok aniden ölmüşse kilit 20 dk içinde kendiliğinden bayatlar; vardiya o zaman başlar.)

## E. Sık sorulanlar
- *Sunucu çökerse?* Sistem kendini yeniden başlatır (artan beklemeyle); kalıcı sorunda alarm (Telegram açıksa) ve dış nabız (sg-nabiz) devreye girer; en kötü ihtimalde yukarıdaki geri alma.
- *Strateji/hesap değişiyor mu?* Hayır; aynı kod, aynı kurallar. Yalnız çalıştığı yer değişiyor.
- *Sunucuyu ben mi güncelleyeceğim?* Hayır; kod güncellemesini ben yaparım (`deploy/kurulum_sanal.md` §6).
- *Sunucuyu silersem?* Hiçbir şey kaybolmaz: durum zaten GitHub'da (`canli-durum`) 15 dk'da bir yedekleniyor; en fazla son 15 dakika.
