# Paylaşım verisi: ortak günlük özet (`ortak.gunluk_ozet.v1`)

Orkestratörün ortak şeması; CT yazıcısı `copytrade/canli/gunluk_ozet.py`. Yalnız bilgi; karar/emir yoluna girmez.

- Konum: veri dalı, yol `durum/paylasim/gunluk_ozet_v1.json` (`canli_yayimla.sh` ve `deploy/sanal_yayimla.sh` kopyalar).
- Yazım: motor `durum_yaz()` kancası; günlük Telegram raporu gönderildiği dakikada (21:00 TSİ = `canli_ozet_saat_utc` 18) ve en geç saatte bir. Bayatlık eşiği 26 saat.
- `mod`: gerçek kip `canli`; `SUNUCU_MOD=deneme` ya da `VERI_DALI` = `canli-durum-deneme` → `deneme`; diğer sanal (Actions `canli-durum`, sunucu `uretim`) → `sanal`. Ortam `/etc/sg-sanal-mod.env` (sunucu) ve `canli_vardiya.yml` (Actions).
- Bilinmeyen alan `null`; adres/anahtar/e-posta yok (hesaplar `T_xxxxxx` takma adıyla; çıktıda `0x…` maskelenir).
- Alan notları: `kasa.gun_pnl` = UTC gün başı özsermayeden beri; `islem.*` bugünkü `kayit/<tarih>.jsonl` `emir` olaylarından (`ac` = açılış, `kapat` = kapanış, kazanan/kaybeden = emrin gerçekleşen K/Z işareti, ücret hariç; tasfiye ve borsa stopu `emir` olayı değilse sayılmaz); `alinmayan_sinyal` = `emir_yok` sayısı;
  `hesaplar[].gun_pnl` = bugün gerçekleşen K/Z − ücret, `toplam_pnl` = slot girişinden beri net, `islem` = bugün dolan emir (K-86: `ogrenme` ve `rejim` alanları kaldırıldı);
  `limitler.kaldirac_tavan` = sert sınır 5, `kaldirac_ayar` (ek alan) = kurallardaki marj kaldıracı; `saglik.son_nabiz` = yazım anı.
