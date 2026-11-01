# Faz 3: anlık hat ve Hyperliquid entegrasyon hazırlığı

Bu belge mevcut kodun kanıtlanabilir durumunu, güvenli public read-only/dry-run uygulamasını ve saniyelik canlı kopyaya geçişteki açık boşlukları kaydeder. Dry-run runtime ve servis sarmalayıcısı kaynak kodda uygulanmıştır; hosting/deployment ve 24 saatlik gerçek-veri koşusu yapılmış değildir. Bu depoda canlı emir hattı yoktur; cüzdan/özel anahtar, imza, hesap yetkilendirmesi, exchange order veya live enable yapılmamıştır.

## Eklenmiş Faz 3 read-only/dry-run kodu

- `copytrade/hl_ws_dry_run.py`: HL `userFills` mesajlarını normalize eder, süreç içi tekilleştirme/sıra takibi ve stale/late kontrolleriyle yalnız dry-run öneri veya ret kaydı üretir. Emir gönderme arayüzü içermez.
- `copytrade/hl_ws_runtime.py`: adapter enjekte edilen runtime; WebSocket olaylarını alır, reconnect sonrası read-only backfill planı uygular, health sayaçları ve JSONL/manifest kanıtı tutar.
- `copytrade/hl_public_adapter.py`: public `userFills` WebSocket ve `userFillsByTime` info sorgusu için adapter sağlar. Bu public okuma akışıdır; imza, wallet veya exchange/order çağrısı değildir.
- `copytrade/faz3_dry_run_service.py`: açıkça başlatılan wrapper; dry-run modu, 11 benzersiz adres, süre sınırı ve loopback health endpoint'lerini doğrular. `--check-config` bağlantı açmadan yapılandırmayı denetler.
- `copytrade/faz3_preflight.py`: dry-run ön koşul kanıtını salt bellek üzerinde doğrular; başarılı çıktı live yetkisi vermez.

Bu modüllerin kodda bulunması, hosting kurulumu, servis işletimi, gözlemlenmiş gerçek veri veya 24 saatlik kabul kanıtı anlamına gelmez. 24 saatlik gerçek-veri dry-run koşusu tamamlanmamıştır. Servis yeniden başlatmaları arasında kalıcı idempotency deposu da sağlanmış değildir.

## Mevcut durum: kod kanıtı

- `worker/wrangler.toml` içindeki cron `* * * * *`'dır. Bu dakikalık tetikleme hedefidir; çalışma anının kesin zaman garantisi değildir (`docs/VERI_SOZLESMESI.md`, “Worker oda tarama sağlığı”).
- `worker/src/index.js` içindeki `scheduled()` `runCron()` çağırır. `runCron()` `durum.json`'dan `kol == "oda"` traderlarını alır, `userFillsByTime` ile son imleçten itibaren dolumları sorgular, sonuçları D1'de biriktirir ve imleci ilerletir. Yeni dolum gecikmesini de kaydeder. Bu, REST yoklamasıdır; websocket dinleyicisi değildir.
- Aynı Worker kodu olayları Telegram'a ancak `BILDIRIM_KIPI=islem` ise yollar; aksi halde günlük özet/durum akışı vardır. Telegram callback'leri kullanıcı kararını kaydeder, emir göndermez.
- `.github/workflows/izleme.yml` saatte bir, `.github/workflows/arsiv.yml` 15 dakikada bir çalışır. Bunlar geçmiş veriyi/izlemeyi tamamlayan işlerdir; saniyelik yürütme döngüsü değildir.
- `copytrade/tarama.py` ve diğer `copytrade` modülleri HL public bilgi/dolum verisini analiz eder. `copytrade/__init__.py` paketin imzalama, cüzdan veya emir yerleştirme kodu içermediğini açıkça belirtir. Kod tabanında HL emir gönderme ya da cüzdan imzalama çağrısı bulunmuyor.
- `docs/GOREV_ETRE_GECIS.md` E1 açıklaması Worker dakikalık yoklamayı yaklaşık 1–2 dk gecikmeli seçenek, kalıcı WS hizmetini saniyelik seçenek olarak tarif etmiş. O belge şu an depoda bulunmuyor; bu nedenle aşağıdaki gereksinimler o eski planın uygulanmış olduğu anlamına gelmez.

## Saniyelik canlı kopya için açık boşluklar

Mevcut dakikalık cron yeni dolumu ancak sonraki başarılı taramada fark eder. Gerçek gecikme ağ, cron gecikmesi, trader sayısı, API sınırlaması ve hata tekrarlarına bağlıdır; her dakika çalışacağı ya da her dolumu anında yakalayacağı garanti edilmez. Dakikalık REST taraması Telegram bildirimi için yararlı bir yedek/uzlaştırma yolu olabilir, fakat saniyelik emir kopyalama gereksinimini tek başına karşılamaz.

Saniyelik akış için sürekli çalışan bir süreç gerekir. Read-only/dry-run runtime ve public HL `userFills` adapter'ı bu sürecin kaynak kod iskeletini/uygulamasını sağlar: reconnect, heartbeat/sessizlik, backfill ve olay tekilleştirme davranışları vardır. Ancak servis hosting'e kurulmamış ve gerçek veriyle 24 saat çalıştırılmamıştır; bu nedenle işletim dayanıklılığı doğrulanmış sayılmaz. Cloudflare Worker'ın dakikalık scheduled handler'ı kalıcı websocket oturumu değildir. Durable Object ya da ayrı bir sürekli servis teknik adaydır; kapasite, ücret, işletim ve ağ erişimi kararı ayrıca verilmelidir. Mevcut tekilleştirme durumu süreç içi bellektedir, kalıcı kuyruk/restart recovery garantisi değildir.

Canlı kopya karar/hesap hattı henüz emir yürütücüsüne bağlı değildir. Önce mevcut `copytrade` hesaplarının hangi olayda ne boyutta emir önereceği, fiyat/işaret tazeliği, kaldıraç/marjin sınırı, maksimum notional, açık emir/pozisyon mutabakatı, iptal ve acil durdurma davranışları tanımlanmalı; her öneri kaynak HL olayıyla izlenebilir olmalıdır. Bu belge strateji eşiklerini veya emir boyutunu belirlemez.

## Cüzdan ve hesap yetkilendirmesi için güvenli yaklaşım

1. Hesap sahibi önce yalnız MetaMask bağlantısıyla adresini seçer; adres eşleşmesi ve salt okunur bakiye/pozisyon görünümü yapılır. Salt okunur keşif için imza veya özel anahtar gerekmez. Bağlantı tek başına emir izni sayılmaz.
2. Emir yetkisi gerekiyorsa, ana MetaMask cüzdanının özel anahtarı servise aktarılmaz. Hyperliquid'in desteklediği agent/API-wallet yetkilendirme akışı incelenip kullanıcı cüzdanında açıkça onaylanır; hizmet yalnız sınırlı işlem imzası yetkisi olan ayrı anahtarı kullanır. Para çekme yetkisi verilmez. Her ortam ve hesap için ayrı anahtar, en az bakiye ve iptal/yenileme prosedürü kullanılır.
3. Ürün akışında kullanıcıya imzalanan izin kapsamı, bağlı HL hesabı, ağ, anahtarın amacı ve iptal adımı açık gösterilir. İzin/agent adresi sunucu tarafında doğrulanır; beklenmeyen hesap, ağ veya izin kapsamı durumunda emir yolu kapalı kalır. Anahtarlar yalnız secret manager'da tutulur; log, D1, JSON, repo veya Telegram'a asla yazılmaz.
4. Hyperliquid'in güncel imza türü, agent kapsamı, süre/iptal davranışı ve MetaMask mesaj gösterimi entegrasyondan önce resmi güncel dokümantasyonla doğrulanmalıdır. Bu depoda bunları doğrulayan veya uygulayan kod yoktur; belge bu nedenle imzalama payload'ı ya da API detayını varsaymaz.

## Emir kapısından önce dry-run / salt okunur ön kontrol

Aşağıdaki sıra bir kabul planıdır; tamamlandığına dair beyan değildir. Runtime/service wrapper implementasyonu mevcutken hosting/deployment, 24 saatlik gerçek-veri koşusu ve koşu kanıtları beklemektedir.

1. **Salt okunur keşif:** yalnız public HL endpointleriyle market metadata, test adresi/açıkça kullanıcı tarafından sağlanan adres için bakiye, pozisyon ve açık emirleri oku. İstek/yanıtı saklarken kişisel adresi maskele; hiçbir imza veya emir metodu çağırma.
2. **Akış sağlamlığı:** websocket bağlantı/yeniden bağlanma, heartbeat, kesinti sonrası REST backfill, tekrar eden ve sırası değişmiş olaylar, kısmi dolum ve 429 davranışını emir üretmeden sınama. Akış yaşı eşik dışındaysa öneri üretimini durdur.
3. **Dry-run öneri:** canlı olayları mevcut hesap motorundan geçirip yalnız emir önerisi üret (yön, miktar, fiyat dayanağı, risk sınırları, kaynak olay kimliği, ret nedeni). Simüle edilen emirler açıkça `dry_run` işaretli olsun; hiçbir imza anahtarı yüklenmesin ve HL exchange/order endpointine istek gönderilmesin.
4. **Mutabakat ve idempotency:** önerileri salt okunur mevcut pozisyon/açık emirlerle karşılaştır; yinelenen olayın ikinci öneri/emre dönüşmediğini, kısmi doldurma ve yeniden başlatmada durumun kurtarıldığını doğrula. Belirsizlik, stale fiyat, limit aşımı veya hesap uyuşmazlığında fail-closed davran.
5. **Ölçüm raporu:** en az bir temsilî trader ve kısa gerçek veri penceresinde olay zamanı → görülme zamanı → öneri zamanı gecikme dağılımı, kaçırılan/tekrarlanan olay, API hata/429 sayısı, stale süreleri ve dry-run ret nedenlerini raporla. Gerçek veri testi yalnız okuma ve dry-run kapsamındadır.
6. **Ayrı yetkilendirme kapısı:** bu ön kontroller geçse bile wallet/key oluşturma, kullanıcı hesabını yetkilendirme, imza, gerçek emir, para veya live enable kendiliğinden başlamaz. Bunlar ayrı ve açık kullanıcı kararı gerektiren, henüz yapılmamış adımlardır; olası emir öncesi ayrıca küçük-limitli kontrollü pilot, kill switch ve izleme/olay müdahale planı hazırlanır. Deployment da henüz yapılmamıştır.

## Kapsam notu

Bu belge teknik boşlukları ve güvenli ön kontrol sırasını tanımlar; canlı emir davranışını, strateji kurallarını, sermaye sınırlarını, ücretli altyapı tercihini veya kullanıcı yetkilendirmesini karara bağlamaz.
