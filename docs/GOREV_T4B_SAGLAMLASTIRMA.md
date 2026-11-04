# Görev T4b — Motor sağlamlaştırma (bağımsız denetim sonrası, K‑37)

Kaynak: bağımsız denetim raporu (2026-11-05). Lider her bulguyu kodda doğruladı. Bu görev **gerçek kipten (T5) önce zorunlu**; sanal kip T4 ile çalışmayı sürdürür.
Dal: `claude/t4b-saglamlastirma` (T4 main'e girdiyse main'den, girmediyse `claude/t4-canli-motor`'dan). Her madde testle gelir (AGENTS.md).

## 1. Kapanış teyidi (Kritik)
- `_adres_kapat` / `dur_tetikle` / trader kapanışı: IOC sonrası kalan `sz` > 0 ise taze defterle **yeniden dene**. En çok 5 deneme; bant %0,5 → %1 → %2.
  %2'ye yalnız DUR ve kapanışta çıkılır; açılış bandı değişmez.
- Gerçek kipte her deneme sonrası `clearinghouseState` (tüm dex) okunur. "Kapandı" yalnız borsa pozisyonu 0 iken yazılır.
- Düzleşmezse durum `kapanis_eksik` olur. Her dakika alarm verilir ve yeniden denenir. Motor bakım döngüsü (kapanışlar) çalışır kalır, yeni açılış yapılmaz.
  `dur_tetikle` motoru ancak tüm pozisyonlar teyitli 0 olunca durdurur.
- Normal kapanış/azaltmada kısmi dolum kalırsa bir sonraki dakikada yeniden denenir (`kapanis_kuyrugu`).
- Testler: kısmi IOC, hiç dolmayan IOC, 5 denemede de düzleşmeyen pozisyon, sanal kipte sığ defter.

## 2. Gerçek özsermaye risk temeli (Yüksek)
- **Gerçek kip:** her mutabakatta (60 sn) HL `accountValue` okunur (tüm perp dex + spot USDC, K‑35 paydası).
  Günlük −%5, zirveden −%20 ve marj tavanı bu değerle hesaplanır.
  Yerel defter ile fark > kasa × `canli_mutabakat_oran` → alarm + yeni açılış yok (mevcut bayrak).
- **Sanal kip:** funding hesaba girer. Saatlik oran × nosyonel × yön, HL'nin saat başı funding'iyle. Funding bilgisi `metaAndAssetCtxs` / `fundingHistory`'den gelir.
  `kopya_v5` funding'i nasıl alıyorsa aynı işaret ve birim kullanılır (kural 7); altın örnek testle.
- Kayıt satırında `funding_usd` gösterilir; günlük özette toplam funding yer alır.

## 3. Çift emir koruması: önce yaz, sonra emir ver (Yüksek)
- Emirden ÖNCE `durum/niyet.jsonl` dosyasına {kimlik, eylem, coin, usd, cloid, ms} eklenir, fsync ile.
  `cloid` = sha256(dolum kimliği + eylem)'in ilk 16 baytı (deterministik).
- Gerçek kipte emir `cloid` ile verilir (SDK `Cloid`).
- Yeniden başlatmada sonucu yazılmamış niyetler için iki yol var:
  - gerçek kip: `orderStatus(cloid)` sorulur; emir varsa sonucu işlenir, yoksa niyet iptal edilir;
  - sanal kip: niyet "sonuçsuz" kaydedilir, emir tekrarlanmaz.
- `islenen` kimlikleri niyetle birlikte kalıcıdır.
- Test: emir ile durum yazımı arasında çökme benzetimi yapılır. Yeniden başlatmada aynı dolum ikinci emir üretmemeli.

## 4. HL emir doğrulaması (Orta‑yüksek)
- `sz` yuvarlandıktan sonra `sz × en_iyi ≥ 10 $` değilse emir verilmez (`min_nosyonel`). Bu kural reduce‑only tam kapanışta uygulanmaz; HL küçük kapanışa izin verir. Bunu SDK/dokümandan doğrula ve PR'a yaz.
- Limit fiyat tick'e içe doğru yuvarlanır: alışta aşağı, satışta yukarı. Böylece bant hiç aşılmaz. Testle.

## 5. Gecikmiş açılış politikası (lider kararı)
- **Açılış/artırma:** olay yaşı (trader dolum zamanı → bizim işleme anımız) > `canli_olay_stale_sn` (120 sn) ise emir verilmez (`gec_acilis`, sayaç).
  Yakalama, trader'ın sonraki dolumunda K‑36 hedef tabanlı artırmayla kendiliğinden olur.
- **Kapanış/azaltma:** yaşı ne olursa olsun işlenir.
  60 dk penceresinden eski kapanışlar senkronda trader pozisyonu 0 görülünce kapatılır.
- Belge (`sonnet_durum_t4.md` #12, motor docstring) ve testler bu kurala göre düzeltilir. 5 dk eski açılış testi artık emir ÜRETMEMELİ.

## 6. Kuyruk önceliği ve gecikme (Orta)
- Olay kuyruğu öncelikli: kapat/azalt → ac/artir. Kuyruk sınırı 10.000 olay. Taşarsa açılışlar düşer, kapanışlar kalır; durum alarmla bildirilir.
- `kuyruk_gecikme_ms` ölçülür (p50/max) ve vardiya özetine yazılır. Açılışta yaş kuralı (§5) kuyruk bekleme süresini de içerir.

## 7. Telegram (Orta)
- Komut yalnız `chat.id == TELEGRAM_CHAT_ID` **ve** `from.id == TELEGRAM_CHAT_ID` ise kabul edilir (özel sohbet).
  Yetkisiz komut kayda alınır.
- Motor başlangıcından önceki tarihli mesajlar yok sayılır; eski bir /dur yeniden tetiklenmez.
- `offset` `motor.json`'da kalıcı tutulur.

## 8. Vardiya eşzamanlılığı (Orta)
- `concurrency.group`: main → `canli-vardiya-uretim`; diğer dallar → `canli-vardiya-deneme-${{ github.ref_name }}`.
  Böylece deneme vardiyası üretimi bekletmez.
- Vardiya açılışında önceki kilit nabzı 30 dk'dan eskiyse Telegram'a "vardiya boşluğu X dk" gönderilir ve olay `vardiya_boslugu` olarak kaydedilir.

## 9. Sanal defter derinliği (Orta)
- Aynı coinde 5 sn içindeki ardışık sanal emirler, öncekilerin tükettiği defter seviyelerini düşerek yürür. Kısmi dolum ve `dolmadi` gerçekçi olur.

## 10. Herkese açık veri
- Gerçek kipte kendi HL hesap adresimiz hiçbir durum/kayıt dosyasına ve Telegram mesajına yazılmaz. Test: çıktılarda `HL_HESAP_ADRESI` geçmez.
- Trader adresleri HL'de zaten herkese açık; kalır.

## Kabul
- Tam test paketi geçmeli.
- Sanal vardiya en az 4 saat koşar. Sayılar raporlanır: emir, kayma, `gec_acilis`, `kapanis_eksik`, `funding_usd`, `kuyruk_gecikme_ms` p50/max, `min_nosyonel`.
- Belirsiz bir karar çıkarsa dur ve `docs/sonnet_durum_t4b.md`'ye yaz.
