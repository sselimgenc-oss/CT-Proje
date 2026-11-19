# CT Telegram düzeni (ortak standart sürüm 1, 19.11.2026)

Kod: `copytrade/canli/telegram.py` (gönderim, komut okuma, onay), `copytrade/canli/motor.py` (`_komutlari_yurut`, günlük/haftalık özet). Testler: `tests/test_telegram_standart.py`.

## Mesaj biçimi
- İlk satır `[CT] INFO|WARN|CRIT` (önem metinden çıkarılır: ALARM/🚨/🛑/💥/DUR = CRIT; UYARI/⚠️/⏸️/📭/❓ = WARN; kalan INFO).
- Gönderim arka plan kuyruğunda (tek işçi); önemli mesaj ağ hatasında 2/5/15 sn ile yeniden denenir, 429'da `retry_after` beklenir (mevcut G-18 mantığı).
- Hız sınırı dakikada 15: fazlası kuyrukta bekler, kaybolmaz. 24 saatten eski INFO atılır (WARN/CRIT atılmaz).
- Tekrar önleme: aynı WARN/CRIT metni 5 dk içinde bir kez (INFO'da yalnız açık `anahtar` verilirse).
- En çok 3500 karakter (sondan kısaltılır, başlık sabit). Token/hesap adresi maskelenir. Yalnız tanımlı `chat_id` (+ `yetkili_mi` kuralları, K-37).

## Komutlar
| Komut | İş | Onay |
|---|---|---|
| `/durum` | anlık durum | yok |
| `/rapor` | günlük raporu hemen (özet sayaçlarını değiştirmez) | yok |
| `/durdur` (eski `/dur`) | yeni giriş/artırma durur; çıkış serbest | iki adımlı |
| `/devam` (eski `/baslat`) | elle duraklatmayı kaldırır | iki adımlı |
| `/hepsini_kapat` (eski `/kapat`) | tüm pozisyonları kapatır, motoru durdurur (anlamı değişmedi) | iki adımlı |
| `/yardim`, `/start` | komut listesi + gecikme notu | yok |
| `/kurulumlar /ders /kademe /kademe_devam /onayla /reddet` | CT'de henüz yok: "CT'de henüz yok" yanıtı | - |

## İki adımlı onay
1. Riskli komut gelir; bot ne olacağını yazar ve 4 haneli kod verir (120 sn geçerli).
2. Kullanıcı kodu yanıtlar. Süre MESAJIN tarihine göre ölçülür (vardiya gecikmesi haksız düşürmesin). Doğruysa komut uygulanır; yanlış kod ya da süre dolması bekleyeni iptal eder, bot "İŞLEM YAPILMADI" der.
3. Denetim kaydı (`kayit`): `telegram_onay_istendi`, `telegram_onay_sonuc` (onaylandi / yanlis_kod / sure_doldu; kim), `komut_yurutuldu`.
- Bekleyen onay bellektedir: motor yeniden başlarsa düşer, komut yeniden gönderilir. Yeni riskli komut öncekinin yerini alır.

## Raporlar
- Günlük rapor 21:00 TSİ (`canli_ozet_saat_utc: 18`; eskiden 09:00 TSİ "Günaydın" özetiydi).
- Haftalık özet Pazar 18:10 UTC (21:10 TSİ): hafta K/Z, BTC al-tut kıyası, emir sayısı, slot K/Z'ye göre en iyi/en kötü trader. Yalnız rapor; işlem mantığına girmez. Taban `motor.json`da (`hafta_gunu`, `hafta_taban`); ilk özet "başlangıçtan beri" gösterir.

## Standarttan sapmalar
- "Evet, onayla" düğmesi yok (kod yolu seçildi). Sağlık kontrolü/"Düzeldi" bildirimleri CT'de `saglik.yml` iş akışında ayrıdır, bu değişikliğe dahil edilmedi. Haftalık özet yapay zekâ bütçesine bağlı değil (CT'de yok).
- Komutlara yarım dakikada bir bakılır (motor `_periyodik`, 30 sn) ve yalnız motor çalışırken; vardiya geçişinde ve "bekleme vardiyasında" cevap gecikebilir. Sunucuya taşınınca kalkar (`/yardim` metninde yazılı).
