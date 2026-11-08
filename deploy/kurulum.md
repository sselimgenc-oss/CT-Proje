# Canlı motor kurulumu (Ubuntu 24.04) — T5'e hazır

> **Gerçek para sınırı (AGENTS.md):** tek Hyperliquid hesabı, kasa ≤ 1.000 $, yalnız **para çekme yetkisiz API cüzdanı**. Anahtar yalnız sunucuda (`/etc/sg-canli.env`); repoda, günlükte, Telegram'da, komut satırında ASLA.
> Varsayılan kip **sanal**. Gerçek kip **yalnız sunucu ortamından** açılır (G4): `/etc/sg-canli.env` içinde `CANLI_KIP=gercek` + `CANLI_KASA_USD` + anahtarlar, sonra servis yeniden başlatılır (kullanıcı kararı, T5). `kurallar.yaml canli_kip` yalnız `sanal` kabul eder (`gercek` yazılırsa motor KipHatasi ile başlamaz; depodan gerçek kip açılamaz).
> Adım adım açılış listesi (kullanıcı için): `deploy/ACILIS_KONTROL.md`.

## 1. Paketler ve kullanıcı
```bash
sudo apt-get update && sudo apt-get install -y python3 python3-venv git
sudo useradd --system --create-home --shell /usr/sbin/nologin sgcanli
sudo git clone https://github.com/sselimgenc-oss/sg-arge.git /opt/sg-arge
sudo chown -R sgcanli:sgcanli /opt/sg-arge
sudo -u sgcanli python3 -m venv /opt/sg-arge/.venv
sudo -u sgcanli /opt/sg-arge/.venv/bin/pip install --require-hashes -r /opt/sg-arge/requirements-canli.lock
```
- `requirements-canli.lock` (G-22): tüm paketler sürüm + sha256 ile sabit, hepsi en az 2 haftalık. `--require-hashes` bir paket değişmişse kurulumu durdurur. `requirements-canli.txt` yalnız kilidin kaynağıdır; sunucuda doğrudan KURULMAZ.

## 2. Ortam dosyaları (izin 600; repoya KONMAZ)
Üç ayrı dosya (G-22: HL anahtarı yalnız motor birimine yüklenir; alarm birimi yalnız Telegram dosyasını, yayım birimi yalnız yayım dosyasını okur):

| Dosya | Okuyan birim | İçerik |
|---|---|---|
| `/etc/sg-canli.env` | `sg-canli`, `sg-canli-kontrol` | HL anahtarı, hesap adresi, kip, kasa, `TELEGRAM_KOMUT` |
| `/etc/sg-canli-telegram.env` | `sg-canli`, `sg-canli-kontrol`, `sg-canli-alarm` | bot token, sohbet kimliği |
| `/etc/sg-canli-yayim.env` (isteğe bağlı) | `sg-canli-yayim` | `GERCEK_YAYIM_HEDEF`, `GERCEK_YAYIM_TOKEN` |

```bash
sudo install -m 600 -o sgcanli -g sgcanli /dev/null /etc/sg-canli.env
sudo install -m 600 -o sgcanli -g sgcanli /dev/null /etc/sg-canli-telegram.env
sudo -e /etc/sg-canli.env
sudo -e /etc/sg-canli-telegram.env
```

**Yazım kuralı (G-9):** her satır yalnız `AD=değer`. Satır sonuna açıklama (`# …`) YAZMAYIN: systemd onu değerin parçası sayar (`CANLI_KASA_USD=300  # not` → motor açılmaz). Eşittir çevresinde boşluk, tırnak, `export` yok. Açıklama gerekiyorsa `#` ile başlayan AYRI bir satıra yazın.

`/etc/sg-canli.env` — sanal deneme için (yalnız iki satır):
```
HL_API_CUZDAN_ANAHTARI=<para çekme yetkisiz API cüzdanı özel anahtarı>
HL_HESAP_ADRESI=<ana hesap adresi 0x…>
```
`/etc/sg-canli.env` — gerçek kip (T5, kullanıcı kararıyla):
```
HL_API_CUZDAN_ANAHTARI=<para çekme yetkisiz API cüzdanı özel anahtarı>
HL_HESAP_ADRESI=<ana hesap adresi 0x…>
CANLI_KIP=gercek
CANLI_KASA_USD=1000
TELEGRAM_KOMUT=
```
- `CANLI_KASA_USD` ($): gerçek kipte ZORUNLU, 0 < kasa ≤ 1.000 (`canli_kasa_ust_usd`). Yalnız motor süreci kullanır; radar/kadro/sanal seri `kurallar.yaml canli_kasa_usd` (1.000) ile hesaplanır.
- `TELEGRAM_KOMUT=` sunucuda boş kalır (komutları motor alır).

`/etc/sg-canli-telegram.env`:
```
TELEGRAM_BOT_TOKEN=<bot token>
TELEGRAM_CHAT_ID=<sohbet kimliği>
```

Denetim (değerleri GÖSTERMEZ; yalnız satır no + sorun):
```bash
sudo /opt/sg-arge/.venv/bin/python -m copytrade.canli.ortam_dosyasi motor /etc/sg-canli.env
sudo /opt/sg-arge/.venv/bin/python -m copytrade.canli.ortam_dosyasi telegram /etc/sg-canli-telegram.env
sudo stat -c '%a %U %n' /etc/sg-canli.env /etc/sg-canli-telegram.env
```
İlk ikisi `tamam` yazmalı; `stat` her dosya için `600 sgcanli`.

**Telegram tek tüketici (G4):** aynı bot için `getUpdates` çağıran yalnız BİR süreç olmalı (iki tüketici komut kaybettirir). Gerçek sunucu devreye girdiğinde GitHub Actions vardiyası
`vars.TELEGRAM_KOMUT=kapali` ile çalıştırılır (repo değişkeni; GitHub → Settings → Variables): `TELEGRAM_KOMUT=kapali` iken motor yalnız mesaj gönderir, komut (`getUpdates`) almaz. İş akışı bağlıdır (`canli_vardiya.yml` vardiya işi env'i `TELEGRAM_KOMUT: ${{ vars.TELEGRAM_KOMUT }}`);
repo değişkeni tanımsızsa boştur = Actions'ta komut alma AÇIK (mevcut davranış). **T5/sunucu geçişinde değişken `kapali` yapılmazsa iki `getUpdates` tüketicisi olur ve komutlar (ör. `/kapat`) kaybolur: geçiş kontrol listesine yazılıdır.**

## 3. Sanaldan gerçeğe geçiş günü (G-20)
Sunucuda daha önce **sanal** deneme yapıldıysa durum dizini sanal kayıt taşır; gerçek kip orada AÇILMAZ (çıkış 3, "sanal durum dizininde gerçek kip açılmaz"). Gerçek kipten ÖNCE arşivleyin (silmeyin):
```bash
sudo systemctl stop sg-canli
sudo mv /var/lib/sg-canli /var/lib/sg-canli.sanal-$(date -u +%Y%m%d)
```
Motor ilk açılışta `/var/lib/sg-canli` dizinini boş olarak yeniden kurar (`StateDirectory`).

## 4. Açılış kontrolü (emir göndermez; anahtar komut satırına düşmez)
```bash
sudo cp /opt/sg-arge/deploy/sg-canli*.service /opt/sg-arge/deploy/sg-canli-yayim.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start sg-canli-kontrol
journalctl -u sg-canli-kontrol -n 120 -o cat
```
- `sg-canli-kontrol.service` ortamı systemd ile dosyadan yükler (`EnvironmentFile`): anahtar `sudo` kaydına, `ps` çıktısına ya da kabuk geçmişine DÜŞMEZ.
- ASIL durum dizinini (`/var/lib/sg-canli/durum`) **salt okunur** inceler; hiçbir dosya yazmaz. Rapor (sırsız JSON) günlüğe yazılır.
- `systemctl start` "failed" derse `"tamam": false` demektir: servisi AÇMAYIN, raporu lidere gönderin.

Raporda bakılacaklar (gerçek kip; hepsi zorunlu):

| Alan | Beklenen |
|---|---|
| `tamam` | `true` |
| `kip`, `kasa_kaynagi` | `"gercek"`, `"ortam"` |
| `etkin_kasa_usd` | ≈ `CANLI_KASA_USD` (ör. 1000) |
| `ana_anahtar` / `agent_dogrulandi` | `false` / `true` |
| `hl_deger_siniri_ok` | `true` (HL hesap değeri ≤ 1.000 $) |
| `kadro.taze` | `true` |
| `hl_acik_poz` / `hl_acik_emir` | ilk açılışta `0` / `0` (açık emir her zaman 0 olmalı) |
| `saat.ok` | `true` (sunucu saati HL'den en çok 2 sn sapık) |
| `telegram.deneme_gonderildi` | `true` ve telefona "🚨 DENEME — açılış kontrolü" mesajı geldi |
| `durum.kip_uyumu` / `durum.dur` / `durum.mutabakat` | `true` / `false` / `false` |
| `durum.motor_calisiyor` | açılıştan önce `false` |

## 5. Servis
```bash
sudo systemctl enable --now sg-canli
journalctl -u sg-canli -f
```
Durdurma: `sudo systemctl stop sg-canli` (açık pozisyonlar yerinde kalır) ya da Telegram `/kapat` (tüm pozisyonlar reduce-only kapanır, motor durur, `DUR` yazılır).
Telegram komutları: `/kapat` = tüm pozisyonları kapat + motor durur (`DUR`); `/dur` = yalnız yeni giriş/artırma durur, çıkış serbest, motor çalışır; `/devam` = `/dur` duraklatmasını kaldırır (`/kapat` sonrası açmaz: sunucudan `DUR` silinir). `/durum` = risk bayrakları.

**Çıkış kodları ve yeniden başlatma (G-15, G-21):**

| Kod | Anlamı | systemd |
|---|---|---|
| 3 | Kalıcı neden: `DUR` dosyası, kip uyumsuzluğu, ana cüzdan anahtarı, kasa/HL değer sınırı, agent HL listesinde yok, ikinci motor (`motor.lock` dolu), göreli durum dizini | yeniden BAŞLATMAZ; alarm birimi Telegram'a yazar |
| 75 | Geçici: açılışta HL/ağ okunamadı (motor önce 15/45/120 sn bekleyerek yeniden dener) | 30 sn'den 10 dk'ya artan beklemeyle yeniden başlatır; her denemede Telegram'a "geçici" alarmı |
| 1 | Beklenmedik hata / görev düştü | aynı artan beklemeyle yeniden başlatır |

- `DUR` dosyası (`/var/lib/sg-canli/durum/DUR`) elle silinmeden motor yeniden **açılmaz**.
- Gerçek kipte motor `/var/lib/sg-canli/durum/motor.lock` dosyasını kilitler (`flock`); aynı dizinde ikinci motor 3 ile çıkar. Gerçek kipte `--durum-dizin` mutlak yol olmak zorunda. Motoru elle (birim dışında) ÇALIŞTIRMAYIN.

## 6. Güncelleme
```bash
sudo systemctl stop sg-canli
sudo -u sgcanli git -C /opt/sg-arge pull --ff-only
sudo -u sgcanli /opt/sg-arge/.venv/bin/pip install --require-hashes -r /opt/sg-arge/requirements-canli.lock
sudo cp /opt/sg-arge/deploy/sg-canli*.service /opt/sg-arge/deploy/sg-canli-yayim.timer /etc/systemd/system/ && sudo systemctl daemon-reload
sudo systemctl start sg-canli-kontrol && sudo systemctl start sg-canli
```
Yeniden başlatmada motor `durum/` ve HL açık pozisyonlarını okuyup kaldığı yerden devam eder (işlenen dolum kimlikleri saklanır: çift emir yok). Durum dizini dolu olduğundan kontrolde HL açık pozisyon > 0 olabilir; açık emir yine 0 olmalı.

## 7. Sessiz ölüm alarmı ve gerçek motor nabzı (G8)
```bash
sudo systemctl enable --now sg-canli-yayim.timer
sudo systemctl start sg-canli-alarm
```
- `sg-canli.service` `OnFailure=sg-canli-alarm.service`: servis kalıcı düşünce (çıkış 3 ya da 10 dk'da 5'ten fazla başlatma) `deploy/alarm.sh` Telegram'a tek mesaj atar. Token/chat yalnız `/etc/sg-canli-telegram.env`'den; yoksa "atlandı" yazıp 0 ile biter. Son komut deneme alarmıdır: telefona gelmeli.
- `sg-canli-yayim.timer` (15 dk) `deploy/gercek_yayimla.sh` çalıştırır: maskeli `ozet.json` + `kilit.json` + `nabiz.json` (adresler `0xAAAA…ZZZZ`, anahtar alanları `[gizli]`) `/var/lib/sg-canli/yayim/` altına yazılır.
- Dışarı yayım **`GERCEK_YAYIM_HEDEF`** (git uzak adresi; `/etc/sg-canli-yayim.env`) tanımlıysa `canli-gercek` dalına itilir (`GERCEK_YAYIM_TOKEN` isteğe bağlı; git'e ortam değişkeniyle verilir, komut satırına düşmez; git hataları maskeli günlüğe yazılır). Tanımlı değilse yalnız yerel nabız. **Hedef (K2/K3) kullanıcı kararı bekliyor**; karar gelene kadar dosyayı oluşturmayın.
- Deneme: `sudo systemctl start sg-canli-yayim && journalctl -u sg-canli-yayim -n 5`.
