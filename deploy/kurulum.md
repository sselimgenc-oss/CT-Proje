# Canlı motor kurulumu (Ubuntu 24.04) — T5'e hazır

> **Gerçek para sınırı (AGENTS.md):** tek Hyperliquid hesabı, kasa ≤ 1.000 $, yalnız **para çekme yetkisiz API cüzdanı**. Anahtar yalnız sunucuda (`/etc/sg-canli.env`); repoda, günlükte, Telegram'da ASLA.
> Varsayılan kip **sanal**. Gerçek kip **yalnız sunucu ortamından** açılır (G4): `/etc/sg-canli.env` içinde `CANLI_KIP=gercek` + `CANLI_KASA_USD` + anahtarlar, sonra servis yeniden başlatılır (kullanıcı kararı, T5). `kurallar.yaml canli_kip` yalnız `sanal` kabul eder (`gercek` yazılırsa motor KipHatasi ile başlamaz; depodan gerçek kip açılamaz).

## 1. Paketler ve kullanıcı
```bash
sudo apt-get update && sudo apt-get install -y python3 python3-venv git
sudo useradd --system --create-home --shell /usr/sbin/nologin sgcanli
sudo git clone https://github.com/sselimgenc-oss/sg-arge.git /opt/sg-arge
sudo chown -R sgcanli:sgcanli /opt/sg-arge
sudo -u sgcanli python3 -m venv /opt/sg-arge/.venv
sudo -u sgcanli /opt/sg-arge/.venv/bin/pip install -r /opt/sg-arge/requirements-canli.txt
```

## 2. Ortam dosyası (izin 600)
```bash
sudo install -m 600 -o sgcanli -g sgcanli /dev/null /etc/sg-canli.env
sudo -e /etc/sg-canli.env
```
İçerik (değerleri kendiniz yazın; bu dosya repoya KONMAZ):
```
HL_API_CUZDAN_ANAHTARI=<para çekme yetkisiz API cüzdanı özel anahtarı>
HL_HESAP_ADRESI=<ana hesap adresi 0x…>
# Gerçek kip (T5'te, kullanıcı kararıyla; sanal denemede bu iki satır YAZILMAZ):
# CANLI_KIP=gercek
# CANLI_KASA_USD=300        # $; gerçek kipte ZORUNLU, 0 < kasa <= 1000 (canli_kasa_ust_usd). Yalnız motor süreci kullanır; radar/kadro/sanal seri kurallar.yaml canli_kasa_usd (1000) ile hesaplanır
TELEGRAM_KOMUT=             # sunucuda boş bırak (motor komutları alır)
TELEGRAM_BOT_TOKEN=<bot token>
TELEGRAM_CHAT_ID=<sohbet kimliği>
```
Kontrol: `stat -c '%a %U' /etc/sg-canli.env` → `600 sgcanli`.

**Telegram tek tüketici (G4):** aynı bot için `getUpdates` çağıran yalnız BİR süreç olmalı (iki tüketici komut kaybettirir). Gerçek sunucu devreye girdiğinde GitHub Actions vardiyası
`vars.TELEGRAM_KOMUT=kapali` ile çalıştırılır (repo değişkeni; GitHub → Settings → Variables): `TELEGRAM_KOMUT=kapali` iken motor yalnız mesaj gönderir, komut (`getUpdates`) almaz. İş akışı bağlıdır (`canli_vardiya.yml` vardiya işi env'i `TELEGRAM_KOMUT: ${{ vars.TELEGRAM_KOMUT }}`);
repo değişkeni tanımsızsa boştur = Actions'ta komut alma AÇIK (mevcut davranış). **T5/sunucu geçişinde değişken `kapali` yapılmazsa iki `getUpdates` tüketicisi olur ve komutlar (ör. `/kapat`) kaybolur: geçiş kontrol listesine yazılıdır.** `--kontrol` raporunda `kasa_kaynagi` gerçek kipte `"ortam"` olmalıdır.

## 3. Açılış kontrolü (emir göndermez)
```bash
sudo -u sgcanli env $(sudo cat /etc/sg-canli.env | xargs) /opt/sg-arge/.venv/bin/python -m copytrade.canli.motor --kontrol --durum-dizin /tmp/sg-kontrol
```
Rapor `kontrol.json`: anahtar var mı, bakiye, HL bağlantısı, kadro okuma (taze mi), Telegram yapılandırması. `tamam: true` değilse servisi AÇMAYIN.

## 4. Servis
```bash
sudo cp /opt/sg-arge/deploy/sg-canli.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now sg-canli
journalctl -u sg-canli -f
```
Durdurma: `sudo systemctl stop sg-canli` (açık pozisyonlar yerinde kalır) ya da Telegram `/kapat` (tüm pozisyonlar reduce-only kapanır, motor durur, `DUR` yazılır).
Telegram komutları: `/kapat` = tüm pozisyonları kapat + motor durur (`DUR`); `/dur` = yalnız yeni giriş/artırma durur, çıkış serbest, motor çalışır; `/devam` = `/dur` duraklatmasını kaldırır (`/kapat` sonrası açmaz: sunucudan `DUR` silinir). `/durum` = risk bayrakları.
`DUR` dosyası (`/var/lib/sg-canli/durum/DUR`) elle silinmeden motor yeniden **açılmaz** (çıkış kodu 3, systemd yeniden başlatmaz).

## 5. Güncelleme
```bash
sudo systemctl stop sg-canli && sudo -u sgcanli git -C /opt/sg-arge pull --ff-only && sudo systemctl start sg-canli
```
Yeniden başlatmada motor `durum/` ve HL açık pozisyonlarını okuyup kaldığı yerden devam eder (işlenen dolum kimlikleri saklanır: çift emir yok).

## 6. Sessiz ölüm alarmı ve gerçek motor nabzı (G8)
```bash
sudo cp /opt/sg-arge/deploy/sg-canli*.service /opt/sg-arge/deploy/sg-canli-yayim.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now sg-canli-yayim.timer
```
- `sg-canli.service` `OnFailure=sg-canli-alarm.service`: servis kalıcı düşünce (5 yeniden başlatma/10 dk sonrası ya da çıkış 3) `deploy/alarm.sh` Telegram'a tek mesaj atar. Token/chat `/etc/sg-canli.env`'den; yoksa "atlandı" yazıp 0 ile biter. Çıkış 3 (BAŞLAMADI/DUR) yeniden başlatılmaz.
- `sg-canli-yayim.timer` (15 dk) `deploy/gercek_yayimla.sh` çalıştırır: maskeli `ozet.json` + `kilit.json` + `nabiz.json` (adresler `0xAAAA…ZZZZ`, anahtar alanları `[gizli]`) `/var/lib/sg-canli/yayim/` altına yazılır.
- Dışarı yayım **`GERCEK_YAYIM_HEDEF`** (git uzak adresi; `/etc/sg-canli.env`) tanımlıysa `canli-gercek` dalına itilir (`GERCEK_YAYIM_TOKEN` isteğe bağlı). Tanımlı değilse yalnız yerel nabız. **Hedef (K2/K3) kullanıcı kararı bekliyor**; karar gelene kadar boş bırakın.
- Deneme: `sudo systemctl start sg-canli-yayim && journalctl -u sg-canli-yayim -n 5`; alarm: `sudo systemctl start sg-canli-alarm`.
