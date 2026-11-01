# Faz 3 canlı işlem v1 — güvenlik mimarisi

Bu belge kullanıcı kararlarını güvenlik sınırlarına çevirir. Bu bir mimari ve aktivasyon şartnamesidir; canlı işlem yetkisi vermez. Belge hazırlanırken cüzdan bağlanmaz, emir gönderilmez, secret/private key istenmez veya kurulmaz, deployment yapılmaz. Mevcut PAPER/salt okunur çalışma biçimi, ayrı ve açık Makam onayı olmadan değişmez.

## Karar kapsamı

- **Pazar ve ürün:** yalnız Hyperliquid (HL) perpetuals (perps); spot, başka borsa ve başka ürün yok.
- **İşlem cüzdanı:** kullanıcının MetaMask cüzdanı. Seed phrase/private key hiçbir uygulama, depo, günlük, mesajlaşma kanalı veya ajanla paylaşılmaz. Sistem cüzdanı kullanıcı adına içe aktaramaz.
- **Pilot bütçesi:** 100 USDC, 7 takvim günü, yalnız İlk 11. Tahsis edilen tutar pilot için üst sınırdır; otomatik ikmal veya ek transfer yoktur.
- **Limitler:** günlük gerçekleşmiş + gerçekleşmemiş zarar en çok 10 USDC; toplam açık notional en çok 300 USDC; tek emir notional'i en çok 100 USDC. Limit hesabı belirsizse emir kapısı kapalıdır. Bütçe ve limitler kaldıraçla büyütülemez.
- **Sinyal disiplini:** geç gelen sinyal kopyalanmaz (late copy yok); sinyalin kabul penceresi dolmuşsa atlanır, fiyatın peşinden gidilmez.
- **Durdurma ve kayıt:** kill switch yeni girişleri ve pozisyon eklemeyi durdurur; önceden tanımlı risk çıkışları çalışmaya devam eder. Finans mutabakatı uyumsuz veya güncel değilse işlem durur. Arşiv ve Sekreterlik kayıtları zorunludur.

## Aktivasyon durum makinesi

Durumlar yalnız ileri yönde ve kayıtlı bir geçişle ilerler. Her geçiş sürüm, zaman (UTC), aktör, gerekçe, politika özeti ve ilgili snapshot/olay kimliğiyle Arşiv'e yazılır; Makam onayı ve Sekreterlik kaydı olmadan gerçek işlem durumu açılamaz.

| Durum | İzin verilen davranış | İleri geçiş koşulu |
|---|---|---|
| `PAPER` | Mevcut sanal işlem ve salt okunur piyasa verisi | Sürüm kontrollü canlı işlem tasarımı Makamca talep edilir |
| `READ_ONLY` | Kullanıcı onaylı adresin herkese açık hesap/pozisyon verisini okuma; imzalama ve emir yok | Veri kaynağı, cüzdan adresi ve bakiye görüntüsü doğrulanır; kullanıcı ayrıca dry-run ister |
| `DRY_RUN` | Canlı fiyat/sinyal akışını alıp emir kararını üretme ve kaydetme; ağa imzalı emir gönderilmez | Süresi ayrıca açıkça kararlaştırılmış gölge doğrulama, limit/kill-switch/mutabakat senaryoları ve Denetim kabulü tamamlanır |
| `ARMED` | Sınırlı pilot için yapılandırma hazır; emir gönderimi hâlâ kapalı | Makamın açık pilot onayı, Sekreterlikte ayrı talep ve onay kaydı, kullanıcı tarafından cüzdan onayı, tüm kapı kontrollerinin yeşil olması |
| `LIVE` | Yalnız onaylı İlk 11 HL perps pilot emirleri ve belirtilen limitler | Yedi gün veya önceki durdurma koşullarından biri gerçekleşince otomatik `STOPPED` |
| `STOPPED` | Yeni giriş/ekleme yok; açık pozisyonlar yalnız kayıtlı otomatik risk çıkışlarına tabi; durum yeniden açılmaz | Yalnız inceleme, mutabakat ve yeni sürüm/onay zinciriyle `READ_ONLY` veya `DRY_RUN` aşamasına dönülebilir |

`READ_ONLY`, `DRY_RUN` ve `ARMED` durumlarında emir imzalama uç noktası kapalı olmalıdır. `ARMED` durumuna geçiş tek başına emir gönderme yetkisi oluşturmaz. Kullanıcının mevcut pilot kararı 100 USDC bütçe, 7 takvim günlük CANLI pilot, İlk 11 kapsamı ve günlük zarar/açık notional/tek emir limitleri için sırasıyla 10/300/100 USDC'dir. Canlı onay ayrıca belirli cüzdan adresine, başlangıç/bitiş zamanına ve politika sürümüne bağlanır; bu kapsam unsurlarından biri değişirse onay geçersiz olur. Süre bitiminde sistem `STOPPED` durumuna geçer; uzatma otomatik yapılmaz. `DRY_RUN` teknik ve doğrulama kapısı olabilir, ancak sabit bir 14 günlük süre kullanıcı tarafından ayrıca açıkça kararlaştırılmadıkça zorunlu değildir. Süre kararı yoksa DRY_RUN süresi canlı pilot öncesi preflight'ta açık onaylanmalıdır.

## Emir öncesi zorunlu kapılar

Her yeni emir ve ekleme öncesi aşağıdakilerin tamamı sağlanmalıdır; tek bir kontrol başarısız/eksikse emir reddedilip olay kaydedilir:

1. `LIVE` durumu ve geçerli, süresi dolmamış onay.
2. Yalnız onaylı MetaMask adresi, HL perps pazarı ve İlk 11 üyesi.
3. Sinyal yaşının kabul penceresinde olması ve mevcut fiyatın onaylı fiyat bandında kalması; aksi halde sinyal atlanır.
4. Günlük zarar, toplam açık notional ve tek emir notional limitleri içinde kalma.
5. Güncel fiyat, pozisyon, bakiye ve emir durumuyla başarılı Finans mutabakatı.
6. Sağlıklı veri akışı ve saat senkronu; kill switch kapalı değil; pilot penceresi açık.
7. İdempotency anahtarı ve emir öncesi limit kararı Arşiv'e yazılmış olması.

Emir teyidi belirsizse aynı emir körlemesine yeniden yollanmaz. Önce HL'deki emir/dolum durumu salt okunur sorgulanıp mutabakat edilir; sonuç alınamıyorsa `STOPPED`.

## Limit davranışı ve durdurma

- Günlük zarar 10 USDC'ye ulaşınca veya aşınca yeni giriş ve ekleme kapanır, `STOPPED` olayı üretilir. Zarar hesabına gerçekleşmemiş PnL de dahildir; veri yoksa limit aşılmış gibi davranılır.
- Emir sonrası toplam açık notional 300 USDC'yi aşacaksa veya tek emir 100 USDC'yi aşacaksa ilgili yeni emir/ekleme reddedilir. Limitler emir gönderilmeden önce, emir sonrası olası toplam maruziyet üzerinden kontrol edilir.
- Gecikmiş sinyal, limit reddi veya dış sistem hatası nedeniyle atlanan işlem sonradan telafi edilmez.
- Kill switch yeni giriş/ekleme kapısını kapatır ve tekrar açma için kullanıcıya bağlı onay zinciri ister. Mevcut pozisyonları keyfi piyasa emriyle kapatmaz; yalnız önceden onaylanmış çıkış kuralları sürer. Çıkış hattı da güvenli çalışmıyorsa otomatik işlem durur ve kritik bildirim üretilir.
- Bakiye/pozisyon/emir mutabakatı uyuşmaz, bayatlar veya kaynağına erişilemezse derhal yeni emir ve ekleme durur (`STOPPED`). Finans ve Denetim olayı inceler; fark çözülüp mutabakat yeniden sağlanmadan yeniden aktivasyon yoktur.
- Günlük zarar, notional veya tek işlem limiti artırılamaz, sıfırlanamaz ya da başka cüzdana taşınarak etrafından dolaşılamaz. Değişiklik yeni politika sürümü ve Makam onayı gerektirir.

## Secret ve imzalama sınırları

- MetaMask seed phrase ve private key kullanıcıda kalır; kopyalanmaz, depolanmaz, loglanmaz, telemetriye eklenmez ve destek/ajan mesajlarında istenmez.
- Herhangi bir ilerideki otomatik emir tasarımı ayrı, çekim yetkisi olmayan HL işlem yetkisi/agent kimliği gerektiriyorsa, bu kimlik kullanıcı tarafından HL/uyumlu cüzdan akışında oluşturulup açıkça sınırlandırılmalıdır. Bu belge böyle bir anahtarın oluşturulmasını, içe aktarılmasını veya saklanmasını uygulamaz.
- İşlem sırrı gerekirse yalnız secret yöneticisinde tutulur; kaynak kod, `.env`, CI çıktısı, pano, Worker yanıtı, Arşiv/Sekreterlik kaydı ve Telegram'a yazılmaz. Uygulama sırrı yalnız işlem imzalama bileşenine en az yetkiyle verilir; okuma bileşeni sırrı alamaz. Secret değeri hiçbir logda görünmez.
- Pazar verisi ve durum yayınları salt okunur kimlik bilgisiyle çalışır; bunlar emir imzalama yetkisi kazanamaz. Geliştirme, test ve dry-run ortamlarında canlı işlem sırrı bulunmaz.

## Geri alma ve olay müdahalesi

Kullanıcı, durdurma halinde HL hesabındaki agent/API yetkisini HL arayüzünden iptal eder ve MetaMask üzerinden verilmiş ilgili on-chain izinleri varsa ayrıca geri alır. Sistem, varsa kendi imzalama servisi üzerinden yeni giriş/eklemeyi kapatır ve iptal isteğinin sonucunu salt okunur doğrular. İptal doğrulanamıyorsa `STOPPED` kalır, kritik alarm verir; tekrar deneme/yeniden aktivasyon yapmaz. Bu belge iptal işlemi gerçekleştirmez ve cüzdan bağlantısı kurmaz.

Anahtar sızıntısı şüphesinde: kill switch, `STOPPED`, yetki iptali, olay kaydı, kullanıcı bildirimi ve Denetim incelemesi. Kayıp/pozisyon belirsizliğinde önce salt okunur mutabakat; pozisyon azaltma veya kapatma yalnız önceden onaylı risk çıkış politikasıyla.

## Arşiv ve Sekreterlik kayıtları

Arşiv, eklemeli ve değiştirilemez olay geçmişini tutar. En az şu olaylar yazılır: durum geçişleri ve onaylar; kullanılan politika/yazılım sürümü; sinyalin zaman damgası, kaynağı ve kabul/ret nedeni; emir niyeti, limit kararı, HL emir kimliği/sonucu ve dolumlar; ücret/funding; bakiye ve pozisyon mutabakatı; kill switch, durdurma, hata, secret iptali doğrulaması ve yeniden başlatma talebi. Kayıtlar UTC ve ilişkilendirilebilir olay kimliği taşır; seed/private key, secret değeri veya gereksiz kişisel veri içermez.

Sekreterlik ayrı ayrı pilot talebini, Makamın açık onayını, kullanıcı kapsam onayını, başlangıç/bitiş zamanını, cüzdanın herkese açık adresini (yalnız karar kaydında gerekliyse), limitleri, politika sürümünü ve durdurma/yeniden aktivasyon kararlarını kaydeder. Taslak onay sayılmaz. Düzeltme veya karar değişikliği geçmiş satırı değiştirmez; yeni olay ekler. Denetim, Arşiv ile Sekreterlik kayıtlarını karşılaştırır.

## Faz 3'ten canlıya geçiş için çıkış ölçütleri

- Canlı fiyatla `DRY_RUN` doğrulaması ve hiçbir imzalı emir gönderilmemiş olması; DRY_RUN süresi önceden ayrıca açıkça kararlaştırılmamışsa canlı pilot preflight'ında açıkça onaylanmış olması. Sabit 14 gün ancak ayrıca verilmiş açık kullanıcı kararı varsa uygulanır.
- Mutabakat, veri kesintisi, gecikmiş sinyal, limit sınırı, tekrar eden olay ve kill switch senaryoları kayıtlarla doğrulanmış olması.
- Limit kararlarının, onay kapsamının, secret ayrımının, iptal/geri alma prosedürünün ve Arşiv/Sekreterlik zincirinin Denetim tarafından incelenmesi.
- Makamın kapsamı ve son tarihi belirten açık pilot onayı, Sekreterliğin kayıt altına alması ve kullanıcının ilgili cüzdan akışında açık onayı.
- Yukarıdaki koşulların hiçbirisi bu belgenin yazılmasıyla sağlanmış veya canlı yetki verilmiş sayılmaz.
