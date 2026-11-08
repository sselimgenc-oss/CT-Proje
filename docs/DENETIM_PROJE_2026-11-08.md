> Kaynak: Fable proje denetimi iş akışı (7 alan + toplu hakemler, 08.11). Dünkü G-1…G-11'in devamı: G-12…G-24, S-1…S-24. Lider planı: KARARLAR K-48.

# Bulgu sentezi (denetim 08.11): gerçek paraya geçiş öncesi yeni zorunlu maddeler (G-12…G-24)

**Kapsam:**
- Kod `origin/main` 20f424ff. Veri `origin/canli-durum` b665d69d, kayıtlar 05–08.11.
- `motor.py` satırları dünkü bulgulara göre yaklaşık +30 kaydı; aşağıda güncel satırlar var.
- Test paketini bu adımda yeniden koşmadım. Alanlar 882 geçti dedi; hakem güncel HEAD'de 910 saydı.
- Dünden sonra bulguları etkileyen iki değişiklik:
  - **#577:** Actions'ta Telegram artık varsayılan kapalı. Token yalnız `vars.TELEGRAM_ACIK == 'evet'` iken veriliyor (`canli_vardiya.yml:59-60,73-74`, `saglik.yml:37-38`).
  - **#578:** 300 $ paralel seri iş akışı eklendi (`canli_vardiya_300.yml`). Henüz koşmadı: `canli-durum-300` dalı yok.

---

## 1. Gerçek paradan önce zorunlu yeni maddeler (G-12…G-24, önem sırasıyla)

**G-12 — Motor süreç olarak ayakta kalıp sessizce donabiliyor ya da yarı ölü kalabiliyor**
- **Kritik, güven yüksek.** Üç alan bağımsız buldu: yürütücü, sunucu, test.
- **(a) Emir çağrısında zaman aşımı yok:**
  - `yurutucu.py:288` SDK `Exchange(...)` nesnesini `timeout` vermeden kuruyor. SDK 0.24.0'da varsayılan `timeout=None`, yani `session.post(..., timeout=None)`.
  - Emir ve `update_leverage` motor kilidi tutulurken gidiyor (`motor.py:511` `olay_isle`, `dakika` kilidi `:1129`).
  - Yeniden üretim: yanıt vermeyen sunucuya yapılan çağrı 8 sn sonra hâlâ bekliyor (`/tmp/claude-0/wf2/t5/b/sdk_timeout.py`). 4 sn asılı emir `dakika()`'yı 7,71 sn bekletti (`/tmp/claude-0/wf2/testkal/r/r3_kilit_asili.py`).
- **(b) Dakikalık görev tek istisnayla ölüyor:** `_periyodik` (`motor.py:1652`) `to_thread(motor.dakika)` çağrısını try içine almıyor; `dakika` içindeki `durum_yaz()` (`:1147`) de adım korumasının dışında. Yeniden üretim (`/tmp/claude-0/wf2/t5/b/periyodik.py`): görev ölüyor, `durdur` tetiklenmiyor.
  - Hakem notu: disk dolu (ENOSPC) durumunda emir yolu da niyet yazımında düşer. Yani bu tetikleyicide "emir vermeye devam eder" abartılı; asıl sorun sessiz ölüm.
- **Etki:**
  - Risk freni, `/kapat`, kapanış kuyruğu, senkron, `ozet.json` ve kilit nabzı durur.
  - systemd tepki vermez: süreç canlı, `WatchdogSec` yok.
  - Bilinen G-10 (dış ölü adam alarmı) bu durumu ancak nabız `dakika`'dan geliyorsa yakalar.
- **Düzeltme:**
  - `Exchange(..., timeout=10)`. Zaman aşımı "red" değil "belirsiz" sayılsın ve `orderStatus(cloid)` ile çözülsün (G-1 ile ortak iş).
  - `_periyodik` try/except ile sarılsın; görev bitince süreç çıksın (`add_done_callback` → çıkış 1).
  - Bekçi: `dakika` 120 sn ilerlemezse alarm + `os._exit(1)`; isteğe bağlı `Type=notify` + `WatchdogSec=180`.
  - Test bölüm 5'te (test 2).

**G-13 — Gerçek kipte HL pozisyonu defterden küçükse kapanış ters yönde gidiyor ve süresiz takılıyor**
- **Kritik, güven yüksek.** İki alan ayrı ayrı yeniden üretti.
- **Neden:** `_kalan_sz` (`motor.py:706-717`) gerçek kipte `hl − diğer adreslerin yerel payı` döndürüyor; işarete ya da büyüklüğe kırpma yok.
- **Senaryo:** iki trader aynı coinde aynı yönde (gerçek durumda SOL ve ZEC böyle). HL tasfiye, ADL ya da elle kapatma ile pozisyonu küçültürse kalan negatif çıkar. `_kapat_coin` uzun pozisyonu kapatmak için ALIŞ reduce-only gönderir.
- **Kanıt:**
  - `/tmp/claude-0/wf2/risk/t/test_repro_risk.py::test_hl_tasfiye_sonrasi_kapanis_takilir` ve `/tmp/claude-0/wf2/testkal/r/r1_tasfiye_iki_trader.py`.
  - HL gibi davranan sahte borsada: 5 reddedilen ALIŞ, `kapanis_eksik=1` (tüm açılışlar kapalı), defter 0,27273/0,27273, HL 0. Kalıcı.
  - Bugünkü sahte borsada (`tests/test_canli_t4b.py:61-68`, reduce-only denetimi yok) aynı emir YENİ long açıyor ve mutabakat temiz görünüyor. Test yeşil kalırdı.
  - Gerçek kipte motor seviyesinde 2 trader'lı test sayısı 0. `kur_gercek` (`:71`) tek trader kuruyor.
- **Etki:** coin hiç kapanmaz; `kapanis_eksik` tüm açılışları süresiz durdurur; DUR ve `/kapat` hiç bitmez. Tek trader'lı coin güvenli (diğer pay 0).
- **Düzeltme:**
  - `k = hl − diger`. `yerel·k ≤ 0` ise 0; değilse işaret `yerel`'in, büyüklük `min(|k|, |yerel|)`.
  - k=0 ve yerel ≠ 0 ise `harici_kapanis`: `_yerel_temizle` + Telegram alarmı.
  - Sahte borsa reduce-only kuralını uygulasın ve bunun kendi testi olsun.

**G-14 — Vardiya başında ve her yeniden bağlanmada WS snapshot'ı trader pozisyonunu (`poz_tr`) bayat değerle eziyor**
- **Kritik, güven yüksek.**
- **Kod:**
  - `_olay_isle` (`motor.py:542-553`) canlı olmayan olaylar için de `_poz_tr_isle` çağırıyor; `dusen_isle`'deki zaman denetimi (`:535`) burada yok.
  - `_poz_tr_ms` `motor.json`'a yazılmıyor (`:423-426`).
  - `islenen` 5000 kayıtla sınırlı ve 34 adres paylaşıyor; 0x8730 tek başına 2477 kayıt tutuyor. Listeden düşmüş eski dolumlar yeniden uygulanıyor.
  - `senkron_uygula` (`:926`) okumadan sonra olay görülen coini atladığı için bozuk değer yaklaşık 10 dk kalıyor.
- **Gerçek veride 5 iz** (her birinde arada 0 canlı olay):
  - 11-06 05:35 0x8730 ZEC [−50 → −100]
  - 11-06 22:42 0xda9f BTC [0,379 → 0,662]
  - 11-07 07:15 0x4b9b kPEPE [49,1M → 33,8M]; UNI [0 → 14.265]; 0xda9f BTC [1,325 → 0,662], yani tam 2×
  - 11-08 00:20 0x323f BTC [2,90 → 0]
- **Etki:** bu pencerede gelen canlı dolum yanlış önce/sonra değerleriyle karar üretir: çift açılış, yarım azaltma ya da G-3 yolu (ters yönlü artırma). Dünkü denetimin "yön/işaret, ters dönüş sırası doğru" hükmü yalnız `poz_tr` doğruyken geçerli.
- **Düzeltme:**
  - `_olay_isle`'de `o.zaman_ms < _poz_tr_ms[(adres, coin)]` ise poz_tr'ye dokunma.
  - `_poz_tr_ms`'yi kalıcı yaz.
  - Canlı olmayan olayda yalnız son REST senkronundan yeni dolumu uygula.
  - `islenen`'i adres başına tut ya da 50.000'e çıkar.

**G-15 — Açılışta geçici ağ ya da HL hatası çıkış kodu 3 veriyor; systemd yeniden başlatmıyor**
- **Etki kritik; olasılık düşük-orta.**
- **Kod ve birim:**
  - `etkin_kasa` (`motor.py:123`) ve `api_cuzdan_dogrula` (`:157`) ağ hatasını `KipHatasi`'na çeviriyor; sonuç `return 3` (`:1803/1828/1836`).
  - Birimde `RestartPreventExitStatus=3` (`deploy/sg-canli.service:22`).
  - Yeniden üretim: `/tmp/claude-0/wf2/t5/b/cikis3.py` → "agent doğrulanamadı" / "HL hesap değeri okunamadı" → 3.
- **Hakem düzeltmesi:** `PublicClient` 5/15/45 sn yeniden deniyor. Yani tetik için yaklaşık 65 sn'yi aşan bir kesinti gerekiyor. StartLimit alt iddiası zayıf.
- **Etki:** gece yeniden başlatma ya da sunucu açılışı bir kesintiye denk gelirse açık pozisyonlar yönetimsiz kalır. Alarm metni de yanıltıcıdır ("agent doğrulanamadı").
- **Düzeltme:**
  - 3 yalnız kalıcı nedenler için: DUR, kip uyumsuzluğu, ana anahtar, kasa sınırı, agent gerçekten listede yok.
  - Ağ hatasına ayrı kod (75) ve ayrı neden (`hl_okunamadi`).
  - Açılışta artan beklemeli yeniden deneme; birimde `RestartSec=30`, `RestartMaxDelaySec=600`.

**G-16 — Telegram `/kapat` güvenilir değil: argümanlı, bilinmeyen ya da eski komut sessizce düşüyor; offset komut yürütülmeden önce diske yazılabiliyor**
- **Önemli, güven yüksek** (sahte gönderimle yeniden üretildi).
- **Kod:**
  - `telegram.py:119` metnin tamamını karşılaştırıyor: `"/kapat hemen".split("@")[0]` listede yok.
  - `:131` 15 dk'dan eski komut yürütülmüyor ve yanıt da almıyor.
  - Yeniden üretim: 7 girdiden 3'ü işlendi, 0 yanıt gitti.
  - Offset: `dakika` önce kilitsiz `komutlari_al` çağırıyor (`motor.py:1124`), sonra kilit altında `_komutlar`. Arada olay iş parçacığı `motor.json`'a ilerlemiş `tg_offset`'i yazıyor (`:425`). Bu aralıkta çökme olursa komut iz bırakmadan kaybolur (olasılık düşük).
- **Etki:** panik anında yazılan "/kapat şimdi" hiçbir şey yapmaz ve kullanıcı bunu öğrenmez.
- **Düzeltme:**
  - Komut adı = ilk sözcük.
  - Bilinmeyen komuta yanıt; eski komuta yürütmeden "işlenmedi" yanıtı.
  - Offset yalnız `_komutlar` bittikten sonra kalıcı olsun.

**G-17 — WebSocket kopma yolu: sessiz kopma algılanmıyor; kopma sırasındaki dolumlar emir üretmiyor**
- **Önemli. (a) güven yüksek, (b) güven orta.**
- **(a) Sessiz kopma:**
  - `alma_zaman_asimi_sn` (`copytrade/dinleyici.py:327`) hiçbir yerde okunmuyor.
  - `_oturum` (`:608`) 1 sn'lik `recv` zaman aşımını normal sayıyor; `ws_baglan` `ping_interval=None` (`:695`).
  - Yarı açık TCP yaklaşık 15 dk fark edilmez. Yeniden üretim `/tmp/claude-0/wf2/t5/b/sessiz_ws.py`: kopma 0.
  - Normalde saniyede 11–60 mesaj geliyor; 60 sn sessizlik kesin ölü bağlantı demek.
- **(b) Kopma dolumları emir üretmiyor:**
  - `Olcum.olay` snapshot dolumunu bile `gorulen`'e yazıyor (`:168-173`); `Olcum.dolgu` `gorulen`'dekini atlıyor (`:222`).
  - Sonuç: kopukken olan ve HL'nin snapshot'la yeniden gönderdiği dolum motora yalnız `canli=False` olarak ulaşıyor, emir çıkmıyor.
  - Hakem depo düzeneğiyle yeniden üretti. Mevcut test ikinci bağlantıda snapshot vermediği (`[]`) için bunu görmüyor.
- **Düzeltme:**
  - `son_mesaj` yaşı `alma_zaman_asimi_sn`'yi aşarsa `ConnectionError`; ayrıca `ping_interval=20`.
  - Snapshot dolumları ayrı kümede tutulsun; dolgu yalnız canlı görülenleri atlasın.

**G-18 — Alarm teslimi: tek deneme; gece reddedilen emir sessiz; M-3 uyarıyı anlamsızlaştırıyor**
- **Önemli, güven orta-yüksek.**
- **Kod ve veri:**
  - `_gonder_sync` (`telegram.py:93-101`) tek deneme yapıyor. 4 günde 6 `telegram_hata` var; `saglik.py` yalnız ≥5/vardiya'da uyarıyor, yani kullanıcı bunları hiç görmez.
  - `sessiz_mi` (`:86`) yalnız `ONEMLI_ONEKLER` ile başlayan mesajları sesli bırakıyor. Gerçek kipte red ya da dolmadı emri "⚠️" ile başlıyor, bu yüzden 00–08 TSİ arası sessiz.
  - Kayıtta 35 kapanışın 34'ü `kismi`; 22 mesajda "tam dolmadı" yazıyor, neredeyse hepsi tam kapanış.
- **Düzeltme:**
  - Önemli mesajlarda 3 deneme (2/5/15 sn); 429'da `retry_after` kadar bekle.
  - Gerçek kipte durumu "dolu" olmayan emir mesajı "🚨" ile başlasın.
  - Önce M-3 düzelsin.
  - Gerçek kipte emir mesajları 2–3 sn tamponla birleştirilsin (05.11 16:25:55'te 5 sn'de 14 emir oldu).

**G-19 — HL hata metni kayboluyor; agent cüzdan süresi yalnız açılışta denetleniyor**
- **Önemli, güven yüksek.**
- **Kod:**
  - Üst düzey `{"status":"err","response":"<metin>"}` yanıtı TypeError'a düşüp "yanit_bicimi" sayılıyor (`yurutucu.py:250-258`). Örnekler: "Invalid nonce", "User or API Wallet … does not exist".
  - İstisna yolunda yalnız tür adı yazılıyor; `Dolum.ham` hiç kaydedilmiyor.
  - `api_cuzdan_dogrula` yalnız açılışta çağrılıyor. Süresi vardiya ortasında dolan cüzdan her emri opak bir red yapar; kapanışlar da gider.
- **Düzeltme:**
  - `status=="err"` → `hl_err: <metin[:160]>`.
  - Red durumunda `ham` kayda yazılsın (300 karakter).
  - Günde bir `extraAgents.validUntil` denetimi; bitişe 7 gün kala uyarı.

**G-20 — Sanaldan gerçeğe geçiş günü ve `--kontrol` eksikleri**
- **Önemli, güven yüksek.** Arıza güvenli tarafta (çıkış 3 + alarm), ama ilk gün açılış başarısız olur.
- **Eksikler:**
  - `kip_uyumu_denetle` (`motor.py:1346-1363`) sanal durum dizininde gerçek kipi reddediyor; `kurulum.md:25`'te öngörülen sanal denemeden sonra dizini arşivleme adımı yok.
  - `--kontrol` `/tmp/sg-kontrol` dizinine bakıyor (`kurulum.md:40`). Asıl dizindeki kip uyumunu, DUR dosyasını, mutabakat bayrağını, HL'de açık pozisyon ya da emir olup olmadığını görmüyor.
  - Telegram için yalnız "token var mı" bakıyor, deneme mesajı göndermiyor.
  - Zorunlu listede kadronun `taze` olması değil, yalnız `var` olması aranıyor.
  - Saat sapması denetlenmiyor (alt nokta zayıf: timesyncd varsayılan açık).
- **Düzeltme:** `kurulum.md`'ye `systemctl stop` + `mv /var/lib/sg-canli /var/lib/sg-canli.sanal-<tarih>` adımı. `--kontrol` asıl dizini salt okunur okusun ve şunları raporlasın: kip uyumu, DUR, mutabakat, HL açık pozisyon/emir sayısı, gerçek bir `sendMessage`, `kadro.taze` (zorunlu), saat sapması.

**G-21 — Sunucuda çift motor süreci engellenmiyor**
- **Olasılık düşük, etki gerçek para; düzeltme ucuz.** Güven orta.
- **Neden:**
  - `--vardiya` varsayılanı "yerel" (`motor.py:1790`); birim bu bayrağı vermiyor.
  - `kilit_al` (`:396`) kendi kimliğiyle aynı kilidi tazelik denetimi yapmadan geçiyor.
  - `kurulum.md:40` operatöre motoru elle, farklı bir dizinle çalıştırtıyor. `--kontrol` unutulursa aynı agent cüzdanla, ayrı defterle ikinci bir gerçek süreç açılır.
- **Düzeltme:** gerçek kipte `fcntl.flock` ile `/var/lib/sg-canli/motor.lock`; ikinci süreç çıkış 3. Gerçek kipte durum dizini mutlak ve zorunlu olsun.

**G-22 — Anahtarı tutan sanal ortam sabitlenmemiş; anahtar gereksiz birimlere de yükleniyor; CI SDK'yı hiç kurmuyor**
- **Önemli, güven yüksek.**
- **Kanıt:**
  - `requirements-canli.txt` yalnız 4 paketi sabitliyor. Temiz kurulumda 33 paketin 29'u sabitsiz; `regex 2026.11.7` 2 günlük, `pydantic_core 2.50.4` 3 günlük. Proje kuralı en az 2 haftalık sürüm.
  - `kurulum.md:57` güncellemesi `pip install` çalıştırmıyor.
  - `deploy/sg-canli-alarm.service:9` ve `sg-canli-yayim.service:11` de `/etc/sg-canli.env` dosyasını yüklüyor, yani `HL_API_CUZDAN_ANAHTARI` bu birimlerde de var.
  - `ci.yml:21` yalnız `requirements.txt` kuruyor; SDK hiç içe aktarılmıyor; `yurutucu.py:282-288` %0 kapsanıyor.
- **Düzeltme:**
  - Hash'li `requirements-canli.lock`; kurulum ve güncellemede `--require-hashes`.
  - Telegram değişkenleri ayrı env dosyasına; alarm ve yayım birimleri yalnız onu yüklesin.
  - CI'da kilit dosyasından kuran ve ağsız tel biçimi testi koşan bir iş (`Cloid`, `order_wire`, `Exchange(timeout=)` imzası).

**G-23 — G-8'in kapatmadığı vektör: vardiya işindeki `contents:write` token'ı motora, panoya ve `npx wrangler`'a açık**
- **Önemli, güven orta; olasılık düşük, etki yüksek.**
- **Kanıt:**
  - `canli_vardiya.yml:27-28` iş akışı düzeyinde `contents: write`; `:78` checkout'ta `persist-credentials: false` yok.
  - `canli_yayimla.sh:17` `npx --yes wrangler@4.158.0` her vardiyada yaklaşık 17 kez, kilit dosyası olmadan çözülüyor.
  - Hakem: dal koruması bu yolu kapatmaz, çünkü radar dalını da aynı Actions kimliği yazıyor.
  - Etki yolu: radar dalına sahte kadro yazılır, sunucu kadroyu 300 sn'de bir okur.
  - `canli_vardiya_300.yml` de iş akışı düzeyinde `contents: write` taşıyor (orada wrangler ve sır yok).
- **Düzeltme:**
  - `persist-credentials: false`; push kimliği yalnız yayım betiğine.
  - Cloudflare yayını ayrı, `contents: read` iznine sahip bir işe; wrangler `npm ci` + kilit dosyasıyla.
  - Eylemler commit SHA ile sabitlensin.

**G-24 — 300 $ ölçek ayrı bir boyut rejimi; paralel ölçüm henüz koşmadı (karar kapısı)**
- **Önemli, güven yüksek.** Yöntem değişikliği değil, ölçüm eksiği.
- **Sayılar** (05–08.11, sanal emirler ×0,3; ölçekleme yaklaşık ama yön sağlam):
  - Açılış: 58 emirden 50'si (%86) 11 $'ın altında kalır, 11 $'a yuvarlanır (ortanca 3,33×).
  - Artırma: 185'ten 174'ü (%94) eşik altında, atlanır.
  - Azaltma: 109'dan 97'si (%89) eşik altında.
- **Durum:** `docs/KARARLAR.md:176-177` paralel 300 $ seriyi şart koşuyor. `canli-durum-deneme` 1.000 $ ile koşmuş ve 06.11 22:21Z'den beri durmuş. #578 (bugün) iş akışını ekledi ama `CALISTIR_300` tetiklenmemiş; `canli-durum-300` dalı yok.
- **Gereken:** en az 3 gün koşu; 300 ↔ 1.000 $ yan yana (atlanan oranı, yuvarlama payı, getiri); kullanıcı kararı.

---

## 2. Bilinen maddelerin eksik ya da yanlış tarifi

- **G-1:**
  - Kurtarma mekanizması hiç çalışmıyor: `_yurut` emirden hemen sonra `niyet.sonuc_yaz(cloid, 'red')` yazıyor (`motor.py:657`). `niyet.sonucsuz()` bu niyeti dışarıda bıraktığı için `niyetleri_coz` içindeki `orderStatus(cloid)` kurtarması `sdk_hatasi` durumunda hiç koşmuyor.
  - Hatayı doğru sayan ikinci bir test daha var: `tests/test_canli_yurutucu.py:117` (ConnectionError → red).
- **M-3:**
  - Yalnız sayaç değil: Telegram'da 22 yanlış "⚠️ tam dolmadı" uyarısı üretiyor (G-18).
  - `tests/test_canli_yurutucu.py:109` kısmi durumu doğru sayıyor. Yorumu "motor pozisyon boyutunu ister" diyor, oysa `_kapat_coin` ×1,05 istiyor.
  - Düzeltme PR'larından önce bu testler `xfail(strict=True)` yapılsın ki AGENTS.md'deki "testler zayıflatılmaz" kuralıyla çatışma çıkmasın.
- **G-8:** dal koruması tek başına yetmez (G-23).
- **G-10:**
  - Çözüm Actions cron'una dayanamaz. `saglik.yml` 11-06 00:58 → 11-08 13:32 aralığında yaklaşık 61 saatlik slotun 11'inde tetiklendi; en uzun boşluk 420 dk.
  - `saglik.py:146-163` yalnız en yeni tamamlanmış koşuya bakıyor; bu hep iptal edilmiş bir cron oluyor, yani koşu sonucu dalı hiç KRİTİK üretmiyor.
  - Yeni: #577 sonrası `saglik.yml:37-38` de `TELEGRAM_ACIK` değişkenine bağlı. Değişken "evet" değilse Actions motoru ölünce bugün hiç alarm yok. Tek iz panodaki "VERİ BAYAT" uyarısı, o da yalnız sayfa açılırken (S-15).
  - Öneri: Cloudflare Workers Cron ya da dışarıdan ping servisi.
- **A-2:**
  - Kurtarma "≤ 4 sa" değil. Ölçülen cron gecikmeleri 1 sa 13 dk ile 3 sa 32 dk arası; ardışık cron olayları arasında 10 sa 55 dk / 8 sa 25 dk / 8 sa 20 dk.
  - İki yeni kopma yolu: (b) son yayım düşer, dalda bırakılmamış kilit kalır; (c) iptal ya da zaman aşımı olursa zincir koşmaz (`needs.vardiya.result=='cancelled'`) ve `failure()` alarmı da çalışmaz.
  - main'de kilit kapısı (`zamanlama_kontrol.sh`) concurrency yüzünden gerçek bir çift vardiyayı hiç yakalayamaz, yalnız yanlış "atla" üretir.
  - Düzeltme: kilitteki `vardiya` = run_id, koşu durumu `gh api` ile okunsun; iptale alarm.
- **G-7:** #577 ile Actions'ta Telegram varsayılan kapalı; G-7 büyük ölçüde kapandı. Yan etkisi G-10 maddesinde.
- **Denetimin "yön/işaret doğru" hükmü:** yalnız `poz_tr` doğruyken geçerli (G-14).
- **K-37 metni** ("60 dk'dan eski kapanışlar senkronda kapatılır"): yalnız tam kapanış için doğru (S-1).
- **11-05 `senkron_kapanis` 15 adet:** 9'u spot hatası, 6'sı beklenen (S-9).
- **K-42 / `kurallar.yaml:127`:** gerçek kipte HIP-3 kapanışı SDK dex tablosu gerektirir; not eklenmeli (S-11).

---

## 3. Sonra yapılacaklar (önem sırasıyla)

- **S-1 `senkron_uygula` yalnız tam kapanışı kopyalıyor** (`motor.py:926-943`).
  - Kaçırılan kısmi azaltma hiç uzlaştırılmıyor.
  - Hakem: gözlenen zarar yok; örneklerin çoğu G-14'ün izi.
  - G-14/G-17 ile aynı PR'da yapılması önerilir: REST < izlenen ise reduce-only azaltma.
- **S-2 Zirve −%20 DUR'dan sonra yeniden açma döngüsü.**
  - `baslat` (`motor.py:1366-1370`) yalnız `risk.dur`'u sıfırlıyor; zirve hiç yeniden kurulmuyor (`risk.py:26,43-48`).
  - Yeniden üretildi: DUR silinince 60 sn sonra yeniden DUR.
  - Telegram'daki "DUR dosyası elle silinmeli" talimatı işe yaramıyor.
  - Gerçek parada ilk −%20'den önce zorunlu; o zamana kadar acil durum yönergesine "lider `risk.json` zirvesini kurar" notu.
- **S-3 Kasa değişikliği tabanları yeniden kurmuyor** (`motor.py:1346-1363`, `kadro.py:136-138`).
  - 300 → 500 geçişinde 11 üyenin hepsi `slot_dusus` ile iniyor, mutabakat bayrağı (200 $) kalıcı oluyor. 500 → 300'de risk özsermayesi fazla çıkıyor.
  - Kasa artırımından (R5) önce zorunlu. "HL 274 → N=10" alt iddiası yeniden üretilmedi.
- **S-4 Pano "maliyet" ve "kapanan işlemler" yalnız 2 günü okuyor ama "≤ 14 gün" diye etiketli** (`pano.py:521-524`, `:203-208`).
  - Ücret 0,76 ↔ 3,67 $; kapanan işlem 28 ↔ 102; net −4,78 ↔ −20,39 $; brüt iki dönemi karıştırıyor.
  - 12.11 değerlendirmesinden önce düzeltilmeli.
- **S-5 A-2 yolları** (bölüm 2): sanal 28 günlük serideki delikler.
- **S-6 Ofset yalnız deposit/withdraw sayıyor** (`motor.py:983-1004`). Bilinçli tasarım (`VERI_SOZLESMESI.md:444`). Şimdilik kural: para yalnız köprüyle girer ve çıkar (kontrol listesine eklendi).
- **S-7 Sanal tasfiye her coin için 20x azami kaldıraç varsayıyor.**
  - `maks_kaldirac` hiç doldurulmuyor (`hesap.py:138`; `hesap.json` içinde `{}`).
  - 3x long için gerçek tasfiye −%20 ile −%29,8 arasında, kodun varsaydığı −%31,6.
  - Sanal seri iyimser. Okuyucu `izleme_motoru.py:553`'te var.
- **S-8 Kilit altında ağ beklemesi** (G-12'nin kalanı).
  - Kapanış kuyruğunda sınırsız yeniden deneme var (`motor.py:769`).
  - `PublicClient` 429 geri çekilmesi kilit altında; 300 sn'ye kadar `Retry-After`.
  - Düzeltme: üstel geri çekilme + günlük tavan; emir yolu için kısa zaman aşımlı ayrı istemci.
- **S-9 Senkron spot bakiyeyi okumuyor** (`dinleyici.py:719`). K-42 semptomu kapattı; spot gürültüsü sürüyor. Spot coinleri senkronda atla.
- **S-10 HL hata metinleri ve SDK varlık tablosu** dışında kalan küçük yürütücü işleri: `ClientError` metni kayda, `AGIRLIK`'a `userRole` eklenmesi.
- **S-11 `meta`/szDecimals önbelleği** (`yurutucu.py:197-201`).
  - Açılıştan sonra listelenen coin yeniden başlatmaya kadar açılamıyor (kopya kaçırma; açılmayan pozisyonun kapanması da gerekmez).
  - KeyError metni opak.
  - HIP-3 kısmı `canli_hip3_kopya=false` ile zaten kapalı.
- **S-12 Sanal dolum modeli iyimser** (bilgi).
  - 387 emir: 0 red; kayma 377'sinde ≈0.
  - Gerçek sz yuvarlaması BTC 8/11, ETH 12/20, SOL 4/9 kapanış dışı emri "kismi" yapardı.
  - Kural 6 gereği gerçek kipin ilk 50 emri sanal ile yan yana raporlansın.
- **S-13 "Atlanan sinyal" metni** (bölüm 5). `ATLA_TR` içinde motorun kullandığı `min_emir_atlandi` ve `inen_trader` anahtarları yok; aynı bilgi `pano.py:156`'da ikinci sözlükte tutuluyor (kural 7).
- **S-14 Pano aynı kavrama iki sayı gösteriyor.**
  - Zirveden düşüş −%3,97 ↔ −%3,87; bugün +2,50 ↔ +2,66 $.
  - Risk payı çubuğu `/0.05` ve `/0.20` ile koda sabit ve kasaya bölüyor (`pano.py:343-344`); motor `gun_basi`'ye bölüyor (`risk.py:44`).
- **S-15 Pano bayatlık uyarısı yalnız sayfa yüklenirken çalışıyor.** `setInterval` + `visibilitychange` eklenmeli.
- **S-16 Funding raporu.**
  - Telegram günlük "Funding (sanal)" +0,07 $ diyor, kümülatif değer −0,30 $ (`slot_kapat`, `hesap.py:48`).
  - Pano `funding_gercek` olayını saymıyor (`pano.py:79,208,251`).
- **S-17 "Günlük kayıp" üç ayrı tanımla ölçülüyor:** risk `/gun_basi`, pano `/kasa`, sabah özeti 06→06 UTC. Etiketlenmeli.
- **S-18 Arka plan yayımı ile son yayım çakışması** (`canli_vardiya.yml:123` `pkill -P`, `canli_yayimla.sh:68`). Hakem: vardiya başına yaklaşık %0,1. Çözüm: `flock` + `wait`.
- **S-19 `radar.yml:25-27` concurrency grubu dallar arası ortak.** 11-04'te deneme push'u main koşusunu iptal etti.
- **S-20 Zincir yaş koruması kuyruk süresini sayıyor; `sure_dk` üst sınırsız.**
- **S-21 Kalıntılar.**
  - `dal_sil.yml` (408668534) hâlâ etkin; `izleme.yml` silinmiş dala yazıyor; 40 dalda `sonnet_isci.yml` duruyor; Pages açık.
  - `deploy/gercek_yayimla.sh:55` token'ı argv'ye koyuyor ve `:67` hatayı `2>/dev/null` ile gizliyor. Bu betik devreye alınmadan önce düzeltilmeli.
- **S-22 Telegram sanal/gerçek ayrımı.** 19 `tg.alarm` şablonunda kip yok; "kapalı" (ı) yazımı tanınmıyor (`telegram.py:50`). #577 ile büyük ölçüde azaldı.
- **S-23 Kayıtlı HL yanıtı yok** (`tests/fixtures` içinde yalnız 2 dosya). T5 duman koşusunda order/orderStatus/updateLeverage/HIP-3 yanıtları kaydedilip sahte borsaya bağlansın.
- **S-24 Test hijyeni.**
  - T0 = 2027-01-15 08:00 UTC, gece yarısı değil; yorumlar yanlış.
  - Motor düzeyinde 00:00 UTC sınır testi yok.
  - 1 testte assert yok (`test_canli_motor.py:1217`); `sleep(0.3)`'e bağlı asyncio testi var.

---

## 4. Gerçek paraya açılış kontrol listesi (sade)

**Ön koşul** (lider onaylar; kullanıcı yalnız "hazır" bilgisini görür):
- G-1…G-6, G-9, G-12…G-23 main'de ve testli.
- G-8 + G-23 tamam; G-10 Actions cron'una dayanmadan çalışıyor.
- G-24'ün 300 $ sonucu kullanıcıya sunuldu.
- 7 temiz sanal gün tamam.

**A) Bir gün önce**
1. Hyperliquid ekranı: açık pozisyon 0, açık emir 0, hesapta yalnız 300 $ USDC; toplam değer 1.000 $'ın altında. Para yalnız Arbitrum köprüsüyle girip çıkar; vault, "send" ya da alt hesap transferi YAPMAYIN (S-6).
2. Yeni API cüzdanı açın ("sg-canli"). Bitiş tarihini takvime yazın. Anahtar yalnız şifre yöneticisinde; ekran görüntüsü, Telegram, e-posta YOK.
3. GitHub → Variables: `TELEGRAM_ACIK` "evet" OLMASIN (Actions sessiz kalsın). "Evet" ise `TELEGRAM_KOMUT=kapali` olmalı (noktasız i).
4. Sunucuda `timedatectl` → "System clock synchronized: yes".
5. `df -h /var` → en az 5 GB boş.
6. Sunucuda daha önce sanal deneme yaptıysanız: `sudo systemctl stop sg-canli` ve `sudo mv /var/lib/sg-canli /var/lib/sg-canli.sanal-ARSIV` (silmeyin).

**B) Açılış günü** (sakin bir saat seçin; 2 saat ekran başında olun)

7. `sudo -u sgcanli git -C /opt/sg-arge pull --ff-only` ve `git -C /opt/sg-arge log -1 --oneline`: kod liderin verdiğiyle aynı olmalı.
8. `sudo -u sgcanli /opt/sg-arge/.venv/bin/pip install --require-hashes -r /opt/sg-arge/requirements-canli.lock` (G-22'den sonra).
9. `sudo -e /etc/sg-canli.env`:
   - Her satır yalnız `AD=değer`, satır sonunda açıklama (#) yok.
   - `CANLI_KIP=gercek`, `CANLI_KASA_USD=300`, `TELEGRAM_KOMUT=` (boş).
   - Ardından `sudo stat -c '%a %U' /etc/sg-canli.env` → `600 sgcanli`.
10. Ön kontrol (emir göndermez). Komutu lider verir (G-9/G-20 düzeltilmiş). Görmeniz gerekenler:
    - `"tamam": true`, `"kip": "gercek"`, `etkin_kasa_usd` ≈ 300
    - `"ana_anahtar": false`, `"agent_dogrulandi": true`
    - kadro `"taze": true`, HL açık pozisyon 0
    - telefona deneme mesajı geldi
    - Biri farklıysa DURUN ve çıktıyı lidere gönderin.
11. `sudo systemctl start sg-canli-alarm` → telefona deneme alarmı gelmeli. Gelmezse DURUN.
12. `sudo systemctl enable --now sg-canli sg-canli-yayim.timer`, ardından `journalctl -u sg-canli -n 50`. "BAŞLAMADI" ya da "Traceback" görürseniz DURUN.
13. Telegram denemeleri:
    - `/durum` → TEK yanıt gelmeli ve "GERÇEK PARA" yazmalı.
    - `/yardim` → "Bilinmeyen komut" yanıtı gelmeli (G-16 doğrulaması).
    - `/dur` sonra `/devam` (para hareketi yok).
14. 15 dakika sonra `sudo cat /var/lib/sg-canli/durum/ozet.json`:
    - `"kip": "gercek"`
    - özsermaye ile HL ekranı arasındaki fark < 1 $
    - `yazildi_ms` 2 dakikadan eski değil
15. İlk gerçek emir mesajı gelince HL ekranında aynı coin, aynı yön ve yaklaşık aynı tutar görülmeli. Uyuşmazsa hemen `/kapat`.
16. Lider eşliğinde < 10 $'lık reduce-only küçük deneme (K6).

**C) İlk 7 gün, her sabah**

17. 09:00 TSİ özeti geldi mi? Özetteki özsermaye ile HL ekranı arasındaki fark < 2 $.
18. `systemctl is-active sg-canli` → `active`. `journalctl -u sg-canli --since '24 hours ago' | grep -c Traceback` → 0. `ozet.json` 2 dakikadan taze (donma kontrolü, G-12).
19. API cüzdanının bitişine 14 gün kala yenileyin: yeni anahtar → adım 9 → yeniden başlatma.

**Acil durum**
- **Her şeyi kapat:** Telegram'da `/kapat` (argümansız). "Tüm pozisyonlar kapandı" mesajı 2 dakikada gelmezse HL web'den pozisyonları elle kapatın, ardından `sudo systemctl stop sg-canli`.
- **Sunucuya ulaşılamıyorsa:** HL web'den pozisyonları kapatın, sonra More → API sayfasından API cüzdanını iptal edin (Revoke).
- **Yeniden açma:** yalnız lider onayıyla, `sudo rm /var/lib/sg-canli/durum/DUR && sudo systemctl start sg-canli`. −%20 sonrasında S-2 düzelene kadar lider önce `risk.json` zirvesini yeniden kurar.
- **ASLA:**
  - Anahtarı sohbete ya da ekrana yapıştırmayın.
  - `CANLI_KASA_USD` 1.000'i aşmasın.
  - Kasayı değiştirmeyin (S-3 düzelene kadar).
  - İkinci bir motor açmayın (G-21).

---

## 5. Telegram mesaj önerileri (somut örnekler)

Simgeler süs değil: `ONEMLI_ONEKLER` ile başlayan mesajlar gece de sesli gider.

**Saatlik özet, kaçırılan yokken.** Gerçek veri: 08.11 05:09–06:10 TSİ, 107 `emir_yok`, ayrı işlem yaklaşık 86.
```
⏭️ Kopyalanmayan trader dolumu: 107 (≈86 ayrı işlem)
   • kural gereği 107: 86 ayrılan trader 0x8730…15 (yeni alım yok) · 21 çok küçük (< 11 $)
   • kaçırılan 0 (geç görülen / veri yok)
```

**Kaçırılan varken.** Gerçek veri: 06.11 04:07–05:07, 341 sayım, 32 ayrı işlem, 180 geç açılış.
```
⚠️ Kopyalanmayan trader dolumu: 341 (≈32 ayrı işlem)
   • kural gereği 161
   • KAÇIRILAN 180: geç görülen açılış (vardiya başı yeniden oynatma)
```

**Komut yanıtları (G-16):**
```
❓ Bilinmeyen komut: /stop. Geçerli komutlar: /dur /devam /kapat /durum
📭 /kapat 23 dk önce geldi, motor o sırada kapalıydı; İŞLENMEDİ. Hâlâ istiyorsan yeniden gönder.
🛑 /kapat alındı (GERÇEK PARA): tüm pozisyonlar reduce-only kapatılıyor; bitince ayrı mesaj gelecek.
```

**Gece reddedilen emir, gerçek kip** (G-18/G-19; sesli olmalı):
```
🚨 [GERÇEK] EMİR REDDEDİLDİ — BTC kapat 27,30 $
neden: hl_err: User or API Wallet 0x… does not exist.
Kapanış kuyruğa alındı; 1 dk sonra yeniden denenecek. Tekrarlarsa: /kapat ya da HL web.
```

**Kural:**
- "Kaçırılan" > 0 ise satır ⚠️ ile başlar.
- Etiketler tek sözlükten gelir: `telegram.ATLA_TR`, pano da bunu kullanır.
- Ayrı işlem sayısı `(adres, coin, trader_dolum_ms // 1000)` ile tekilleştirilir.

---

## 6. İlk yazılacak 5 test

1. **G-13, gerçek kip, 2 trader aynı coinde, HL tasfiyesi.**
   - Önce sahte borsaya reduce-only kuralı eklenir (pozisyon yoksa ya da emir aynı yöndeyse red, boyut |poz| ile kırpılır) ve sahte borsanın kendi testi yazılır.
   - Senaryo: A ve B 0,27273 BTC long; HL=0; A kapatır.
   - Beklenen: 0 emir, A defterden mark ile düşülür, kuyruk boş, `kapanis_eksik` yok, alarm var.
2. **G-12, asılı emir.**
   - Sahte `exchange.order` takılır.
   - Beklenen: 10 sn'de zaman aşımı, durum "belirsiz", `orderStatus(cloid)` çağrısı; `dakika` gecikmesi sınırın altında; `Exchange` kurulumuna `timeout=10` geçildi.
   - Ek: `_periyodik` istisnasında süreç kodu ≠ 0 ve alarm.
3. **G-14/G-17, yeniden bağlanma.**
   - (a) `islenen` listesinden düşmüş eski snapshot dolumu `poz_tr`'yi değiştirmez; aynı tid hem trades hem userFills kanalından gelirse delta iki kez eklenmez.
   - (b) 1. bağlantıda tid 1, kopma, 2. bağlantının snapshot'ında tid 2, REST'te tid 2 → motor tid 2'yi dolgu/canlı olarak alır ve emir üretir.
4. **`mutabakat.poz_farki` altın örnekleri** (kasa 300, mark 100; `mutabakat.py:17-23` hiç koşmamış, kapsama %70):
   - HL 0,5 ↔ defter 0,27273 → 22,73 $ > 3 $ → "fark"
   - yalnız HL'de → "yetim"; yalnız defterde → "eksik"
   - 2,9 $ fark → alarm yok
   - mark yok → "mark_yok"
   - "xyz:GOLD" anahtarı kendisiyle eşleşir
5. **G-16, Telegram komutları.**
   - "/kapat hemen" yürütülür; "/stop" yanıt alır; 1 sa önceki "/kapat" yürütülmez ama yanıt alır.
   - `komutlari_al` ile `_komutlar` arasında `motor.json` yazılıp yeniden yüklenirse komut kaybolmaz.

**Süreç notu:** G-1 ve M-3'ü yanlış davranış olarak kilitleyen testler (`test_canli_yurutucu.py:109,117`; `test_canli_motor.py:709`) düzeltme PR'larından önce `xfail(strict=True, reason=…)` yapılsın.

---

## 7. Çürütülenler (kısa)

- **"userFills yalnız ilk 10 adres; `izle_ekle` abone olmuyor":** HL'nin kullanıcıya özgü abonelikte 10 kullanıcı sınırı var ve kod bunu bilerek uyguluyor (`dinleyici.py:7`). Önerilen düzeltme sınırı aşardı.
  - Kalan küçük not: saha değişince öncelik sırası tazelenmiyor; `rest_karsilastir` yalnız "gercek" kaçakları sayıyor.
- **"Kaçan dolum tamamlama penceresi 60 dk ile sınırlı ve ortak `son_olay_ms`":** ilk `dakika` senkronu hemen koşuyor (11-05'te açılıştan yaklaşık 1,5 dk sonra), yani `poz_tr` zaten düzeliyor. Ortak `son_olay_ms` dinleyicinin son canlı anını gösteriyor; pencereyi kısaltmıyor.
  - Kalan küçük not: `kurallar.yaml:162` yorumu kodla çelişiyor.
- **"157 dk boşluk temiz biten vardiyadan sonra oluştu" (A-2 düzeltmesi olarak):** boşluk zincir commit'inden (967d0616, 06.11 02:42Z) önce, eski yalnız-cron düzeninde oluştu. Toz düzeltmeleri beklenen davranış.
- **"Gerçek ücret araması tek seferlik":** tahmin oranı (0,00045) HL'nin taban taker ücretine eşit; 300 $ ölçekte sapma 3 $ mutabakat eşiğine ulaşamaz; "henüz indekslenmedi" yarışı kanıtsız.

---

## 8. Genel hüküm: 300 $ gerçek paraya hazırlık, eksik listesi

**Sağlam olanlar:**
- Muhasebe denklemi kuruşuna tutuyor (961,3085 $).
- Defter yeniden oynatması 387 dolumda yalnız 0,017 $ farkla tutuyor.
- Tick/sz fuzz testinde 0 ihlal.
- cloid ve SDK tel biçimi uyumlu.
- Sanal seride 0 `adim_hata`.

**Sanal ölçüm motoru olarak** iş görüyor. **Gerçek para yürütücüsü olarak henüz hazır değil.** Eksikler:

- **Kod, para yolu:**
  - G-1…G-6 açık.
  - Yeni G-12 (sessiz donma), G-13 (ters reduce-only), G-14 (bayat `poz_tr`) kritik ve üçü de sessiz arıza üretiyor.
  - G-15…G-19 (açılış kodu, `/kapat`, kopma yolu, alarm teslimi, HL hata metni) açık.
- **Kurulum ve işletim:** G-9, G-20 (geçiş günü ve `--kontrol`), G-21 (çift süreç), G-22 (kilitli bağımlılık; anahtar yalnız motor biriminde).
- **Güvenlik:** G-8 + G-23 (Actions yazma kimliği). G-10 dış nabız Actions cron'u dışında kurulmalı; bugün Actions'ta Telegram kapalıyken sanal motor ölümünün de alarmı yok.
- **Kanıt:**
  - Gerçek-kipe özgü kod hiç gerçek HL'ye konuşmadı.
  - Kayıtlı HL yanıtı yok; CI SDK'yı kurmuyor.
  - Gerçek kipte 2+ trader'lı test 0; mutabakat fark dalı hiç koşmamış.
  - T5 duman koşusu (K6) ve yanıt kaydı gerekli.
- **Ölçüm ve karar:** 300 $ paralel seri (G-24) bugün eklendi ama koşmadı; en az 3 gün + kullanıcı kararı gerekiyor. 7 temiz sanal gün; S-4 düzelmeden 12.11 değerlendirmesinin maliyet verisi yanıltıcı.
- **Sonraya bırakılabilir ama tarihli:**
  - S-2: ilk −%20'den önce.
  - S-3: kasa artırımından önce.
  - S-4: 12.11'den önce.
  - S-21'in token kısmı: `gercek_yayimla.sh` devreye girmeden önce.

**Yeniden üretim betikleri:**
- `/tmp/claude-0/wf2/risk/t/test_repro_risk.py`
- `/tmp/claude-0/wf2/risk/t/test_repro_kasa.py`
- `/tmp/claude-0/wf2/risk/t/test_repro_kasa2.py`
- `/tmp/claude-0/wf2/testkal/r/r1_tasfiye_iki_trader.py`
- `/tmp/claude-0/wf2/testkal/r/r3_kilit_asili.py`
- `/tmp/claude-0/wf2/t5/b/sdk_timeout.py`
- `/tmp/claude-0/wf2/t5/b/cikis3.py`
- `/tmp/claude-0/wf2/t5/b/periyodik.py`
- `/tmp/claude-0/wf2/t5/b/sessiz_ws.py`
- `/tmp/claude-0/wf2/tgpano/p1.py`
- `/tmp/claude-0/wf2/altyapi/repro`
- `/tmp/claude-0/wf2/altyapi/repro2`