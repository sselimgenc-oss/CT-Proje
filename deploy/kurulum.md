# Canlı motor kurulumu (Ubuntu 24.04) — T5'e hazır

> **Gerçek para sınırı (AGENTS.md):** tek Hyperliquid hesabı, kasa ≤ 1.000 $, yalnız **para çekme yetkisiz API cüzdanı**. Anahtar yalnız sunucuda (`/etc/sg-canli.env`); repoda, günlükte, Telegram'da ASLA.
> Varsayılan kip **sanal**. Gerçek kipe geçiş = anahtar + `copytrade/kurallar.yaml` `canli_kip: gercek` + servisin yeniden başlatılması (kullanıcı kararı, T5).

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
TELEGRAM_BOT_TOKEN=<bot token>
TELEGRAM_CHAT_ID=<sohbet kimliği>
```
Kontrol: `stat -c '%a %U' /etc/sg-canli.env` → `600 sgcanli`.

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
