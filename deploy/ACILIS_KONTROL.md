# Gerçek paraya açılış — kontrol listesi (sade)

Kaynak: `docs/DENETIM_PROJE_2026-11-08.md` §4; G-9, G-15, G-20, G-21, G-22 düzeltmeleriyle güncellendi. Teknik ayrıntı: `deploy/kurulum.md`.
Kural: bir adımda beklenen sonucu görmezseniz **DURUN** ve ekrandaki çıktıyı lidere gönderin. Anahtarı hiçbir yere (sohbet, ekran görüntüsü, e-posta, komut satırı) yapıştırmayın.

## Ön koşul (lider onaylar; size yalnız "hazır" denir)
- Denetim düzeltmeleri (G-1…G-6, G-9, G-12…G-23) main'de ve testli.
- G-8 + G-23 tamam; G-10 Actions zamanlayıcısına dayanmadan çalışıyor.
- 1.000 $ sanal seri (K-49 dönemi) en az 7 temiz gün koştu (K-50; 300 $ seri iptal).
- 7 temiz sanal gün tamam.

## A) Bir gün önce
1. **Hyperliquid ekranı:** açık pozisyon 0, açık emir 0, hesapta yalnız 1.000 $ USDC (fazlası yok).
   Para yalnız Arbitrum köprüsüyle girip çıkar. Vault, "send" ya da alt hesap transferi YAPMAYIN.
2. **Yeni API cüzdanı** açın (adı: `sg-canli`). Bitiş tarihini takvime yazın. Anahtar yalnız şifre yöneticisinde.
3. **GitHub → Settings → Variables:** `TELEGRAM_ACIK` "evet" OLMASIN (Actions sessiz kalsın).
   "evet" ise `TELEGRAM_KOMUT` = `kapali` olmalı (noktasız i).
4. Sunucuda `timedatectl` → "System clock synchronized: yes" yazmalı.
5. Sunucuda `df -h /var` → en az 5 GB boş olmalı.
6. **Sanal denemenin dizinini arşivleyin** (sunucuda daha önce sanal deneme yaptıysanız; silmeyin):
   ```
   sudo systemctl stop sg-canli
   sudo mv /var/lib/sg-canli /var/lib/sg-canli.sanal-ARSIV
   ```
   Bu yapılmazsa motor gerçek kipte açılmaz ("sanal durum dizininde gerçek kip açılmaz").

## B) Açılış günü (sakin bir saat seçin; 2 saat ekran başında olun)
7. **Kodu güncelleyin:**
   ```
   sudo -u sgcanli git -C /opt/sg-arge pull --ff-only
   git -C /opt/sg-arge log -1 --oneline
   ```
   Görünen kod, liderin verdiği kodla aynı olmalı.
8. **Kilitli paketleri kurun** (her paket imzasıyla denetlenir):
   ```
   sudo -u sgcanli /opt/sg-arge/.venv/bin/pip install --require-hashes -r /opt/sg-arge/requirements-canli.lock
   ```
   Son satır "Successfully installed" ya da "Requirement already satisfied" olmalı; "HASH" hatası görürseniz DURUN.
9. **Ortam dosyalarını yazın.** İki dosya var:
   ```
   sudo -e /etc/sg-canli.env
   sudo -e /etc/sg-canli-telegram.env
   ```
   - `/etc/sg-canli.env` tam olarak şu 5 satır (değerleri siz yazın):
     ```
     HL_API_CUZDAN_ANAHTARI=...
     HL_HESAP_ADRESI=0x...
     CANLI_KIP=gercek
     CANLI_KASA_USD=1000
     TELEGRAM_KOMUT=
     ```
   - `/etc/sg-canli-telegram.env` tam olarak şu 2 satır:
     ```
     TELEGRAM_BOT_TOKEN=...
     TELEGRAM_CHAT_ID=...
     ```
   - Her satır yalnız `AD=değer`. Satır sonuna `#` ile açıklama YAZMAYIN; boşluk ve tırnak koymayın.
   - Denetleyin (değerleri göstermez):
     ```
     sudo /opt/sg-arge/.venv/bin/python -m copytrade.canli.ortam_dosyasi motor /etc/sg-canli.env
     sudo /opt/sg-arge/.venv/bin/python -m copytrade.canli.ortam_dosyasi telegram /etc/sg-canli-telegram.env
     sudo stat -c '%a %U %n' /etc/sg-canli.env /etc/sg-canli-telegram.env
     ```
     İlk iki komut "tamam" yazmalı. Üçüncüsü her dosya için `600 sgcanli` yazmalı.
10. **Birim dosyalarını kopyalayın ve ön kontrolü çalıştırın** (emir göndermez; anahtar ekrana/komut satırına düşmez):
    ```
    sudo cp /opt/sg-arge/deploy/sg-canli*.service /opt/sg-arge/deploy/sg-canli-yayim.timer /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl start sg-canli-kontrol
    journalctl -u sg-canli-kontrol -n 120 -o cat
    ```
    Görmeniz gerekenler:
    - `"tamam": true` (ilk komut "failed" demediyse)
    - `"kip": "gercek"`, `"kasa_kaynagi": "ortam"`, `"etkin_kasa_usd"` ≈ 1000
    - `"ana_anahtar": false`, `"agent_dogrulandi": true`
    - `"kadro"` içinde `"taze": true`
    - `"hl_acik_poz": 0`, `"hl_acik_emir": 0`
    - `"saat"` içinde `"ok": true`
    - `"durum"` içinde `"kip_uyumu": true`, `"dur": false`, `"mutabakat": false`, `"motor_calisiyor": false`
    - telefona "🚨 DENEME — açılış kontrolü (GERÇEK PARA kipi)" mesajı geldi (`"deneme_gonderildi": true`)
    - Biri farklıysa DURUN ve çıktıyı lidere gönderin.
11. **Alarm denemesi:** `sudo systemctl start sg-canli-alarm` → telefona alarm mesajı gelmeli. Gelmezse DURUN.
12. **Motoru açın:**
    ```
    sudo systemctl enable --now sg-canli sg-canli-yayim.timer
    journalctl -u sg-canli -n 50
    ```
    "BAŞLAMADI" ya da "Traceback" görürseniz DURUN.
    - "BAŞLAMADI (geçici)" + çıkış 75 = HL'ye ulaşılamadı; motor kendisi yeniden dener (en çok 10 dk arayla). 15 dakikada düzelmezse lidere yazın.
    - Çıkış 3 = kalıcı neden (ör. DUR dosyası, yanlış anahtar, kasa sınırı, ikinci motor): motor yeniden denemez; lidere yazın.
13. **Telegram denemeleri:**
    - `/durum` → TEK yanıt gelmeli ve "GERÇEK PARA" yazmalı.
    - `/yardim` → "Bilinmeyen komut" yanıtı gelmeli (G-16 doğrulaması).
    - `/dur`, ardından `/devam` (para hareketi yok).
14. **15 dakika sonra** `sudo cat /var/lib/sg-canli/durum/ozet.json`:
    - `"kip": "gercek"`
    - özsermaye ile HL ekranı arasındaki fark < 1 $
    - `yazildi_ms` 2 dakikadan eski değil
15. İlk gerçek emir mesajı gelince HL ekranında aynı coin, aynı yön ve yaklaşık aynı tutar görülmeli. Uyuşmazsa hemen `/kapat`.
16. Lider eşliğinde < 10 $'lık reduce-only küçük deneme.

## C) İlk 7 gün, her sabah
17. 09:00 TSİ özeti geldi mi? Özetteki özsermaye ile HL ekranı arasındaki fark < 2 $.
18. Sunucuda:
    ```
    systemctl is-active sg-canli
    journalctl -u sg-canli --since '24 hours ago' | grep -c Traceback
    ```
    Birincisi `active`, ikincisi `0` olmalı. `ozet.json` 2 dakikadan taze olmalı (donma kontrolü).
19. API cüzdanının bitişine 14 gün kala yenileyin: yeni anahtar → adım 9 (yalnız anahtar satırı) → adım 10 → `sudo systemctl restart sg-canli`.

## Acil durum
- **Her şeyi kapat:** Telegram'da `/kapat` (yanına başka söz yazmadan). "Tüm pozisyonlar kapandı" mesajı 2 dakikada gelmezse HL web'den pozisyonları elle kapatın, ardından `sudo systemctl stop sg-canli`.
- **Sunucuya ulaşılamıyorsa:** HL web'den pozisyonları kapatın, sonra More → API sayfasından API cüzdanını iptal edin (Revoke).
- **Yeniden açma:** yalnız lider onayıyla:
  ```
  sudo rm /var/lib/sg-canli/durum/DUR
  sudo systemctl start sg-canli-kontrol
  sudo systemctl start sg-canli
  ```
  −%20 sonrasında (S-2 düzelene kadar) lider önce `risk.json` zirvesini yeniden kurar.
- **ASLA:**
  - Anahtarı sohbete, ekrana ya da komut satırına yapıştırmayın.
  - `CANLI_KASA_USD` 1.000'i aşmasın; kasayı değiştirmeyin (S-3 düzelene kadar).
  - Motoru elle ya da ikinci kez başlatmayın (yalnız `systemctl`; ikinci motor çıkış 3 ile reddedilir).
  - `/etc/sg-canli.env` içindeki satırları başka birim dosyasına ya da Telegram dosyasına kopyalamayın.
