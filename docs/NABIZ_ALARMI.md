# Dış nabız alarmı — `sg-nabiz` (G-10, denetim 08.11)

## Ne yapar
- Cloudflare Worker `sg-nabiz` (`.github/nabiz/worker.js`), **Cloudflare Cron Trigger** ile 10 dk'da bir çalışır. GitHub Actions cron'una bağlı değil.
- Salt okur. Emir, anahtar ve yazma yok. Okuduğu üç dosya:
  - `canli-durum:durum/kilit.json` (`nabiz_ms`, `birakildi`)
  - `canli-durum:durum/ozet.json` (`yazildi_ms`)
  - `main:copytrade/canli/DONEM`
- Okuma `raw.githubusercontent.com` üzerinden, önbelleği aşmak için `?t=` ekiyle yapılır.
- **Kaynak ayarı (Y-3):** wrangler değişkeni `NABIZ_KAYNAK` (yayında GitHub `vars.NABIZ_KAYNAK`'tan `--var` ile; yoksa `canli-durum`).
  - Değer: dal adı (aynı depo, ör. `canli-gercek`) ya da https ham kök (ör. `https://raw.githubusercontent.com/<sahip>/<depo>/canli-gercek`). Kökte `durum/kilit.json` ve `durum/ozet.json` aranır (`deploy/gercek_yayimla.sh` bu düzende iter).
  - Geçersiz değer yok sayılır (varsayılan). Elle sorgu yanıtında `kaynak` ve `kaynak_ozel` görünür.
  - Mesaj etiketi `ozet.kip`'ten: "Gerçek motor" / "Sanal motor" (özel kaynak okunamadıysa "Motor"); gerçek kipte bağlantı yerine sunucu komutu yazılır.
  - **Gerçek paradan önce ön koşul:** worker gerçek yayım hedefine (`GERCEK_YAYIM_HEDEF`, `canli-gercek` dalı) çevrilmiş olmalı; hedef herkese açık okunabilir olmalı (worker'da token yok). Aksi hâlde worker yalnız sanal motoru izler. Bkz. `deploy/ACILIS_KONTROL.md` ön koşul.
  - Tek worker tek kaynağa bakar: gerçek kipe geçince sanal seri bu alarmdan çıkar (yeni altyapı kurulmadı).
- Yaş = şimdi − max(`nabiz_ms`, `yazildi_ms`, dönem başı). Birim dakika, zamanlar UTC ms.
- Yaş ≥ `ESIK_DK` (45) ise alarm verilir. İlk mesaj, eşiği geçtikten sonraki ilk tiktedir: yaş [45, 55) dk.
- Durum sürerse alarm `TEKRAR_DK`'da (180 dk) bir yinelenir: yaş 225, 405, … dk. KV yok, durum saklanmaz; "düzeldi" mesajı yok.
- Dönem başlangıcından (`DONEM`) önce alarm verilmez (bekleme normaldir). Dönem başladıktan sonra yaş en erken dönem başından sayılır.
- Normal boşluklar eşiğin altında kalır:
  - yayım 15 dk'da birdir;
  - vardiya devri ≈ kurulum + 15 dk ilk yayım.
- Ham veri okunamazsa:
  - her dosya için 3 deneme yapılır (0 / 20 / 60 sn bekleme);
  - yine olmazsa durum "bilinmiyor" olur;
  - uyarı yalnız UTC 3 saatlik ızgaranın (00, 03, 06 … UTC) ilk tikinde gider;
  - tek dosya okunduysa karar o dosyayla verilir;
  - `DONEM` okunamazsa yok sayılır.
- Mesaj Türkçe ve kısadır: "🚨 ALARM: Sanal motor nabzı yok — son yayım N dk önce … <Actions bağlantısı>".
- Elle kontrol: worker adresi (`https://sg-nabiz.<hesap>.workers.dev/`) JSON durum döner. Bu sorgu Telegram'a mesaj göndermez ve secret değeri içermez.

## Yayın
- `.github/workflows/nabiz_yayim.yml` iki durumda çalışır: main'e `.github/nabiz/**` push'u ya da elle tetikleme. Yalnız main.
- Yetki `contents: read`. wrangler 4.158.0 `.github/pano` kilit dosyasından kurulur.
- Telegram yalnız `vars.TELEGRAM_ACIK == 'evet'` iken açılır:
  - worker'a `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` secret'ı konur (`wrangler secret put`, stdin);
  - `TELEGRAM_ACIK=evet` değişkeni verilir.
- Değişken `evet` değilse worker çalışır ama yalnız günlüğe yazar.
- **Kullanıcı:** Cloudflare token'ında `Workers Scripts: Edit` olmalı. `sg-pano` zaten bu token ile yayımlanıyor. Cron Trigger da aynı yetkiyle kurulur.
- İlk yayım elle yapılır: Actions → "Nabız alarmı yayını" → Run workflow (main).
- `TELEGRAM_ACIK` değişince iş akışı yeniden koşturulmalı. Secret'lar worker'da kalır; `TELEGRAM_ACIK=hayir` gönderimi kapatır.

## Ayar
- `.github/nabiz/wrangler.toml` `[vars]`: `ESIK_DK`, `TEKRAR_DK`. `NABIZ_KAYNAK` dosyada değil; GitHub Variables → yayında `--var`.
- Cron 10 dk'dır; worker'daki `tik_dk` ile aynı olmalı.
- Test: `tests/test_nabiz.py` (node ile; CI'da atlanmaz).
