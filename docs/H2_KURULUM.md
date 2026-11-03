# H2 — Anlık dinleyici kurulum rehberi (kullanıcı için)

Amaç: Hyperliquid'in **halka açık** verisini bir küçük sunucudan dinleyip algılama gecikmesini, kaçan dolumu ve kopmaları ölçmek.
**Emir, anahtar, cüzdan, imza yoktur; sunucuda hiçbir gizli bilgi bulunmaz.** Kod: `copytrade/dinleyici.py` (görev: `docs/GOREV_H2_DINLEYICI.md`).
Bu rehberde hiçbir adım parola, token ya da özel anahtar yazdırmaz; özel anahtarınızı (`id_ed25519`, uzantısız dosya) kimseyle paylaşmayın.

## 1. SSH anahtarı (Windows PowerShell)
```powershell
ssh-keygen -t ed25519 -C "sg-dinleyici"
type $env:USERPROFILE\.ssh\id_ed25519.pub
```
Yalnız **`.pub`** (genel anahtar) satırını DigitalOcean → Settings → Security → *Add SSH Key*'e yapıştırın.

## 2. Sunucu (Droplet)
- Bölge: **Singapore SGP1** (Hyperliquid'e yakın), imaj: **Ubuntu 24.04**, plan: **Basic 1 GB**, kimlik doğrulama: SSH key (yukarıdaki).
- Güvenlik duvarı (Networking → Firewalls): **yalnız 22 (SSH) açık**; dinleyici dışarıdan bağlantı kabul etmez.

## 3. Bağlan, kullanıcı ve paketler
```bash
ssh root@<SUNUCU_IP>
adduser --disabled-password --gecos "" sg
apt update && apt install -y python3-venv git
timedatectl            # "System clock synchronized: yes" ve "NTP service: active" olmalı
```
Saat önemlidir: gecikme = sunucuya varış anı − dolum zamanı. Saat kayarsa özet **negatif gecikme** sayar ve `saat_kaymasi_uyarisi: true` yazar.
NTP kapalıysa: `timedatectl set-ntp true`.

## 4. Kodu al (repo açık; token gerekmez)
```bash
su - sg
git clone https://github.com/sselimgenc-oss/sg-arge.git
cd sg-arge
python3 -m venv .venv
.venv/bin/pip install -r requirements-dinleyici.txt
```

## 5. İzlenecek liste
Pazar işi (`ilk11_pazar`) kadro 50 + referans listesini `copytrade-kapi` dalına yazar. İlk Pazar'dan önce pilot listesi kullanılır:
```bash
git fetch origin copytrade-kapi
git show origin/copytrade-kapi:ilk11/izleme_listesi.yaml > ~/liste.yaml 2>/dev/null || cp copytrade/izleme_listesi.yaml ~/liste.yaml
wc -l ~/liste.yaml          # boş olmamalı; boş ya da yoksa dinleyici BAŞLAMAZ
```

## 6. Adım 0 — 5 dakikalık keşif (1 saatlik koşudan ÖNCE)
HL'nin kullanıcı başına abonelik sınırı gerçek mi, `trades` kanalında `users` alanı var mı, izlenen adres dolumu görünüyor mu:
```bash
cd ~/sg-arge
.venv/bin/python -m copytrade.dinleyici adim0 --liste ~/liste.yaml --cikti /tmp/adim0 --sure-sn 300
cat /tmp/adim0/adim0.json
```
Çıktıda adres yoktur (takma ad). Çıktıyı lidere/yazara yapıştırın: `userfills_11_adres_hata_sayisi`, `trades_users_alani_var`, `izlenen_dolum_gorundu`.

## 7. Servisi kur ve başlat
```bash
exit                                    # root'a dön
cp /home/sg/sg-arge/deploy/sg-dinleyici.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now sg-dinleyici
```

## 8. Kontrol (1 saat sonra)
```bash
systemctl status sg-dinleyici
journalctl -u sg-dinleyici -n 50
cat /var/lib/sg-dinleyici/ozet.json
```
`ozet.json` (saatlik): trader (takma ad) başına `n`, `gecikme_medyan_sn`, `gecikme_p95_sn`, `gecikme_max_sn`, `kacan`, `negatif_gecikme`; genel `kopma`,
`yeniden_baglanma`, `yeniden_baslama`. Göz kontrolü: **gecikme medyanı birkaç saniye içinde, kaçan = 0**. Çıktıyı yapıştırın (adres içermez).
Sonra 24 saat, sonra 7 gün aynı servis çalışır; "bitti" = 7 günlük özet.

## 8b. Güncelleme ve elle durdurma (H5 risk kapısı, dry-run)
Güncelleme:
```bash
cd /home/sg/sg-arge && sudo -u sg git pull && systemctl restart sg-dinleyici
```
`ozet.json`'da `risk` bloğu ve `/var/lib/sg-dinleyici/risk_kararlari.jsonl` (günlük döner, 7 gün) görünür; emir gönderilmez (`emir_gonderildi: false`). İlk 11 üyeliği listedeki `takim: ilk11` alanından gelir; yalnız deneme için `ExecStart`'a `--risk-tum-liste` eklenir.
**`/dur` (yeni giriş/eklemeyi durdur; çıkış serbest):**
```bash
touch /var/lib/sg-dinleyici/DUR
```
Kaldırmak için:
```bash
rm /var/lib/sg-dinleyici/DUR
```
Dosya her dolumda kontrol edilir; yeniden başlatma gerekmez.

## 9. Durdur
```bash
systemctl stop sg-dinleyici
```
Kaldırmak için ek olarak `systemctl disable sg-dinleyici` ve Droplet'i silin. Servis çökerse `Restart=on-failure` yeniden başlatır; sayısı `yeniden_baslama` alanındadır.

## Bilinen sınırlar
- `trades` coin evreni = izleme motorunun kopyaladığı evren (kural 7): ana perp piyasası + HER HIP-3 dex'inin coinleri (`dex:coin`; `perpDexs` + `meta` `dex`). Spot kopyalanmaz (`olcut.perp_fills`): abone olunmaz, REST hakemde görülürse yalnız `kacan_sinif.spot` olarak sayılır. Abonelik reddi `genel.error` ve `error` çerçeveleriyle görünür.
- Kopma sonrası REST dolgusu (H2b): yeniden bağlanınca [son WS mesajı, yeniden abonelik bitişi] aralığı `userFillsByTime` ile doldurulur; kurtarılan dolum `dolgu` (trader başına adet + `dolgu_gecikme_max_sn`, canlı gecikmeden AYRI) ve `genel.dolgu` olarak yazılır, REST hatası `genel.dolgu_hata`. Dolgu ile alınan dolum görülmüş sayılır: REST hakem `kopma_araligi` / `gercek` kaçan saymaz. Spot dolgu dışıdır.
- `userFills` çapraz kontrolü ilk 10 adresle sınırlıdır (varsayılan; Adım 0 sonucuna göre değişir).
