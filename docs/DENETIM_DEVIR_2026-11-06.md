# Devir denetimi — 2026-11-06 (lider, Sonnet emekliye ayrılmadan önce)

Kapsam: `main` 239d16f1 + veri dalları (`canli-durum` 21:00Z, `radar` 06.11). Üç bağımsız inceleme (para yolu, radar→kadro, altyapı/güvenlik/pano) + lider doğrulaması.
Önemli bulgular kodda ve yeniden üretim betikleriyle doğrulandı. Hiçbiri **bugünkü sanal** sonucu bozmuyor; G maddeleri **gerçek kipte** para kaybettirebilir.

## Sağlam bulunanlar
- Testler 878 → 880 (K-45 ile) geçiyor. Muhasebe denklemi kuruşuna tutuyor (özsermaye 961,90 $).
- Boyutlama (§5b, K-35/36/38), yön/işaret, ters dönüş sırası, kayma/funding işaretleri doğru. Niyet + cloid yazımı fsync ile emirden önce.
- R2 form puanı bağımsız yeniden hesapla birebir; R1 eşikleri doğru; 300 satır, NaN/çift adres yok; spot/HIP-3 ayrımı doğru.
- Gerçek kip GitHub Actions'ta çalışamaz (`GITHUB_ACTIONS` + `CANLI_*` reddi); kasa ≤ 1.000 $; ana anahtar reddi, agent cüzdan doğrulaması (G6); para çekme/transfer çağrısı yok.
- Repo + tüm dallar + geçmiş: özel anahtar, token, chat id **yok**.
- Pano sayıları kaynak JSON ile aynı; HTML kaçışı doğru (XSS yolu yok).
- `xyz:GOLD` 262 $ (HIP-3): K-42'den önce (05.11) açılmış; kapanış/azaltma K-42'de serbest → trader kapatınca kapanır.

## Hemen yapılan
- **K-45** (bu PR): boş slot Yedek'le de dolar; eski kadro yok sayılır. Eski kodla yarın saha 7/11 kalacaktı; yeni kodla 11/11 (gerçek veriyle denendi).

## Gerçek paraya geçmeden ZORUNLU (G)
| # | Sorun | Senaryo | Yer |
|---|---|---|---|
| G-1 | Emir gönderildikten sonra SDK/ağ hatası "red" sayılıyor | HL'de pozisyon açılır, defter 0; trader kapatınca biz kapatmayız (yetim pozisyon). Mutabakat yalnız alarm verir | `yurutucu.py:250`, `motor.py:614` |
| G-2 | `/kapat`, DUR, zirve −%20 yalnız defterdeki coinleri kapatıyor | Defterde olmayan borsa pozisyonu açık kalır, "tümü kapandı" mesajı yine gider | `motor.py:833` |
| G-3 | Bizim pozisyon trader'a ters yöndeyse artırma ters emir gönderiyor (reduce-only değil) | Kaçan ters dönüşten sonra borsada net ters pozisyon, defterle 54 $ fark (betikle üretildi) | `motor.py:211`, `senkron_uygula` |
| G-4 | Kapanıştan önce de `update_leverage` çağrılıyor | Kaldıraç ayarı reddedilirse o coinin kapanışı hiç gitmez | `yurutucu.py:203–229` |
| G-5 | Gerçek kipte zararla yeniden başlatma zararı iki kez sayıyor | kasa = min(ayar, HL) + eski realize → yerel özsermaye düşük; mutabakat bayrağı kalıcı, açılış durur; yanlış DUR riski | `motor.py:302`, `:107` |
| G-6 | `perpDexs` tek hatası süreç boyunca önbellekte | Trader hesabı eksik toplanır → emirler 3× slot tavanına kadar büyür | `motor.py:470` |
| G-7 | Telegram iki tüketici | Sunucu açılınca Actions vardiyası `/kapat`'ı yutabilir. Actions'ta komut varsayılan KAPALI olmalı ya da sanal için ayrı bot | `canli_vardiya.yml:74` |
| G-8 | `main`, `radar`, `canli-durum` dalları korumasız | Sunucu `main`'den çekiyor, kadroyu `radar` dalından okuyor; yazma izinli herhangi bir iş akışı/bağımlılık gerçek parayı yönlendirebilir. Kullanıcı: GitHub → Settings → Branches/Rulesets | GitHub ayarı |
| G-9 | `deploy/kurulum.md` hataları | Kontrol komutu özel anahtarı `sudo` kaydına/`ps`'e düşürüyor ve yorum satırlarında çalışmıyor; satır içi yorum systemd'de değere karışıyor (`CANLI_KASA_USD=300  # …` → motor açılmaz) | `kurulum.md:27–40` |
| G-10 | Dış "ölü adam" alarmı yok | Sunucu çökerse/ağ giderse açık pozisyonla sessizlik | K2/K3 |
| G-11 | ~~`sonnet_isci.yml` hâlâ açık~~ **kaldırıldı 06.11** (kullanıcı: `CLAUDE_CODE_OAUTH_TOKEN` sırrı repoda yok) | `@sonnet` yorumu yazma yetkili ajan başlatır. Kapatılmalı; `CLAUDE_CODE_OAUTH_TOKEN` sırrı kullanıcı tarafından iptal | iş akışı + GitHub Secrets |

## 12.11 isabet ölçümünden ÖNCE
- **R-1:** Aynı gün yeniden radar koşusu `radar/<gün>/kadro.json`'u üzerine yazıyor; motor günün İLK kadrosunu uyguluyor (K-39) → isabet farklı İlk 11'i ölçer (05.11 kanıtlı). Günün ilk kadrosu ayrı saklanmalı ya da isabet `canli-durum` `gun_kadro`'dan okumalı.

## Sonra (önemli, acil değil)
- R-2: `veri_hatasi` satırları koşuyu "tam" sayıyor; HL kesintisinde küçük/boş kadro taze yayımlanır (`radar_kadro.py:27`).
- R-3: Trader kaldıracı koşu anı hesap değerine bölünüyor; hafta başı çok daha yüksek olabilir. Canlı "anında R1/4" denetimi fiilen çalışmıyor (`canli/kadro.py:140`).
- R-4: R1 işlem sayısı/likidite HIP-3 dahil, kopya testi HIP-3 hariç (K-43 tutarsızlığı; ör. 0x62ed… %91 HIP-3).
- R-5: "R1'den elendi → sonuçla 14 gün" kuralı kodda yok; kadro dışı muamelesi görüyor. `kadro.py:10` belge satırı eski.
- R-6: Kadro bayatken `islem_yok` (72 sa) düşmesi çalışmıyor.
- R-7: isabet adımı hata verirse o günün kadrosu yayımlanmayabilir (`radar_isabet.py:253` dışı).
- M-1: Yetim kapanışlı üye geri girerse defteri sıfırlanıyor (`hesap.py:331`; denklem bozulur).
- M-2: Dakikalık adım istisnaları (risk/mutabakat) yalnız kayda gidiyor; Telegram alarmı yok.
- M-3: Her kapanış `kismi` sayılıyor (yalnız sayaç).
- A-1: `CLOUDFLARE_API_TOKEN` deneme dallarında da motor adımı ortamında (yalnız main + yayım adımına daraltılmalı).
- A-2: Kilit bırakılmadan çöken vardiyada zincir kopar; ≤ 4 sa boşluk (yalnız sanal).
- A-3: Pano gerçek kipte de "Sanal kip: gerçek para yok" yazıyor (`pano.py:510`).

## Sıra (lider planı)
1. K-45 (bitti) → 2. R-1 (12.11'den önce) → 3. G-1…G-6 tek görev, her biri altın örnek testiyle → 4. G-7, G-9 → 5. kullanıcıyla G-8, G-10, G-11 ve T5.
