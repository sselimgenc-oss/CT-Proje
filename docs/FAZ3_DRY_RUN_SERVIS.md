# Faz 3 — dry-run runtime ve servis paketi

Bu belge, repoda eklenmiş güvenli public read-only/dry-run parçalarını ve henüz tamamlanmamış işletim adımlarını açıklar. `copytrade/hl_ws_dry_run.py` olay normalizasyonu, tekilleştirme ve dry-run öneri/ret üretimini; `copytrade/hl_ws_runtime.py` sağlayıcıdan bağımsız runtime, backfill, health durumu ve JSONL kanıt kaydını; `copytrade/hl_public_adapter.py` public HL WebSocket `userFills` aboneliği ile read-only `userFillsByTime` backfill'ini; `copytrade/faz3_dry_run_service.py` ise açıkça çağrılan süreç sarmalayıcısını sağlar. `copytrade/faz3_preflight.py` yalnız verilen kanıtları doğrular. Bunlar dry-run/read-only kapsamındadır; canlı işlem hazırlığı veya doğrulanmış 24 saatlik koşu anlamına gelmez.

**Henüz yapılmadı:** servis herhangi bir hosting ortamına kurulmadı/deploy edilmedi ve 24 saatlik gerçek-veri dry-run koşusu tamamlanmadı. Dockerfile/Compose paketi yoktur. `worker/` dakikalık zamanlanmış REST yoklamasıdır; bu servis ayrı bir süreçtir ve Worker/cron'a bağlanmamıştır. Cüzdan/özel anahtar, imza ve emir gönderme/live enable kapsam dışıdır ve mevcut pakette yoktur.

## Güvenlik ve çalışma sınırı

- Yalnız açıkça `dry_run` modunda başlar; bu mod dışında başlangıç hatası verir.
- Emir, imza, cüzdan erişimi ve private key/secret alma kodu içermez. HL exchange/order uç noktalarına istek göndermez. Yalnız operatörün açıkça verdiği salt okunur akış adresine bağlanabilir.
- Başlangıçta ağa otomatik bağlanma yoktur. Süreci başlatmak, ayrıca `NETWORK_ENABLED=true` ve operatörün sağladığı `WS_URL` verilmedikçe bağlantı kurmaz. Varsayılan `NETWORK_ENABLED=false`; `WS_URL`, hesap/cüzdan adresi ve secret için varsayılan değer yoktur.
- Yapılandırma eksik, mod farklı, zaman sınırı geçersiz veya ağ kapalıyken bağlantı istenmişse fail-closed kapanır; sessizce başka moda geçmez.
- Süreç tek örnek çalışır; olayları `dry_run` etiketi, kaynak olay kimliği ve UTC zamanlarıyla eklemeli JSONL kaydına yazar. Tekilleştirme, yeniden bağlanma/backoff, heartbeat ve kesinti sayacı ölçülür. Tekrar bağlantı, dry-run önerisinin tekrarlanmasına yol açmamalıdır.
- Log/evidence içine secret, imzalı payload, kişisel hesap verisi veya gereksiz adres yazılmaz. Abone olunan kaynak/konu adları yapılandırmadan gelir; adres maskelemesi zorunludur.

## Yapılandırma sözleşmesi

Uygulama, ortam değişkenleri veya salt okunur bir config dosyası kabul edebilir. Ortam değişkenleri önceliklidir. Örnek aşağıda **şablondur**; değerleri doldurulmadan servis çalışmaz ve ağa bağlanmaz:

```dotenv
RUN_MODE=dry_run
NETWORK_ENABLED=false
WS_URL=
SUBSCRIPTIONS=
RUN_DURATION_SECONDS=86400
HEALTH_HOST=127.0.0.1
HEALTH_PORT=8080
EVIDENCE_DIR=./evidence
LOG_LEVEL=INFO
```

`WS_URL` ve `SUBSCRIPTIONS`, yalnız veri sağlayıcısı/konu seçimi kesinleştikten sonra operatörce verilir. Sağlayıcıya özgü endpoint, cüzdan adresi, kimlik bilgisi ve secret bu depoda varsayılanlaştırılmaz. Üretim paketi config dosyasını loglamaz; izinleri en az yetkili ve mümkünse read-only tutar.

## Uygulanmış servis arayüzü

Mevcut uygulama şu parçaları sağlar:

- `entrypoint`: `RUN_MODE=dry_run`, 11 benzersiz abonelik adresi, loopback health host ve en çok 24 saatlik süreyi doğrular; `--check-config` ağ/adapter başlatmadan config kontrolü yapar.
- `listener`: public HL adaptörüyle salt okunur olay alma, heartbeat/sessizlik takibi, sınırlı exponential backoff, tekilleştirme ve reconnect sonrası read-only backfill.
- `dry-run processor`: normalize edilmiş fill için öneri/ret kanıtı üretir; exchange order/emir istemcisi yoktur.
- `health`: `GET /healthz` ve `GET /readyz` loopback'te sunulur. Health süreç durumunu, ready bağlantı/heartbeat durumunu döndürür; hazır değilse `/readyz` `503` verir. Yanıtta secret veya ham payload bulunmaz.
- `evidence`: JSONL olay kayıtları ve koşu sonu manifesti üretir; `SIGTERM`/`SIGINT`'te kapatma/flush akışı vardır.

Runtime bileşenlerinin yerel kodda bulunması, hosting kurulumu, işletim gözetimi veya 24 saatlik koşu kanıtının mevcut olduğu anlamına gelmez. Tekilleştirme deposu süreç içi bellektir; servis yeniden başlatmalarında kalıcı idempotency depolaması sağlanmış değildir.

Dockerfile/Compose paketi repoda yoktur. Konteyner paketi eklenirse sabitlenmiş Python taban imajı ve kilitli bağımlılık, root olmayan kullanıcı, read-only root filesystem ve yalnız evidence volume yazma izni kullanılmalıdır. Aşağıdaki Docker komutları, bu paket sağlanana kadar uygulanabilir çalıştırma talimatı değil, hedef işletim prosedürü taslağıdır.

## 24 saatlik koşu prosedürü (deployment paketi sağlandığında; henüz icra edilmedi)

1. Şablon config'i operatörün ayrı çalışma dizinine kopyala. `RUN_MODE=dry_run` ve `RUN_DURATION_SECONDS=86400` değerlerini doğrula. Kasıtlı ağ denemesi yapılacaksa, sağlayıcı read-only olduğu doğrulandıktan sonra `NETWORK_ENABLED=true` ve açıkça seçilmiş `WS_URL`/`SUBSCRIPTIONS` ver; boş bırakılmış config ile ağ bağlantısı olmaz. Secret veya cüzdan adresi ekleme.
2. Mevcut kaynak kodu açık operatör çağrısıyla başlatılabilir; aşağıdaki Docker komutu ancak Compose paketi oluşturulup deployment hazırlandıktan sonra geçerlidir:

   ```sh
   docker compose run -d --name faz3-dry-run dry-run
   ```

   Komut otomatik başlatıcıya, cron'a veya deployment'a eklenmez. Başlangıç UTC zamanı ve koşu kimliği kaydedilir.

3. Health/readiness al:

   ```sh
   curl --fail http://127.0.0.1:8080/healthz
   curl --fail http://127.0.0.1:8080/readyz
   docker inspect --format '{{.State.Status}}' faz3-dry-run
   ```

   `readyz` `503` ise koşuyu sağlıklı sayma. Her kontrolün UTC zamanı ve cevabın yalnız güvenli alanları (durum, uptime, son heartbeat yaşı, sayaçlar) evidence'a yazılsın.

4. Süre 24 saate ulaşınca servis kendiliğinden düzgün kapanır; ara vermek/durdurmak için:

   ```sh
   docker stop --time 30 faz3-dry-run
   ```

   `SIGTERM` sonrası kayıtların flush edildiğini, manifestte `ended_utc` ve `stop_reason` bulunduğunu doğrula. Erken durdurma da koşuyu geçersiz kılmaz; manifestte `completed=false` olmalıdır. Durdurulan koşu yeniden başlatılmaz; yeni koşuya yeni run ID verilir.

5. Son durumu ve log/evidence'ı al:

   ```sh
   docker logs --timestamps faz3-dry-run
   docker cp faz3-dry-run:/app/evidence ./faz3-evidence-<run-id>
   docker inspect --format '{{.State.ExitCode}}' faz3-dry-run
   ```

   Koşu sonu raporu: başlangıç/bitiş UTC, tamamlandı mı, toplam/tekil/tekrar olay sayısı, öneri/ret sayıları (ret nedeni gruplu), reconnect/heartbeat kaybı/429 ve diğer hata sayaçları, gecikme p50/p95/max, config özeti (secret'sız), image/kod sürümü, manifest ve JSONL bütünlük özeti. Ham event payload'ı paylaşılacaksa önce kişisel alanlar temizlenir.

## Health ve evidence alanları

`/healthz` örnek güvenli yanıt: `{"status":"ok","mode":"dry_run","uptime_seconds":120,"run_id":"<id>"}`. `/readyz` buna `listener_connected`, `last_heartbeat_age_seconds` ve `ready` alanlarını ekler. Endpoint yalnız loopback'e bağlanır; dışarı açılması bu sözleşmenin dışında kalır.

JSONL her satırda `run_id`, `event_id`, `event_time_utc`, `received_at_utc`, `processed_at_utc`, `event_type`, `mode="dry_run"` ve `decision`/`reject_reason` içerir. Manifestte config'in hassas olmayan özeti ve dosya checksum'ları bulunur; event payload'ları, secret ve cüzdan adresleri bulunmaz. Kayıtlar UTC ISO-8601 biçimindedir.

## Kabul kapısı ve mevcut durum

Kodda read-only/dry-run runtime, public adapter ve servis sarmalayıcısı vardır; bu doküman servisin deploy edildiğini ya da 24 saat çalıştığını iddia etmez. Hosting/Compose paketi, operasyonel saklama/izleme düzeni ve gerçek veri üzerinde tamamlanmış 24 saatlik koşu hâlâ bekleyen işlerdir. Koşu öncesi emir/imza bağımlılığı olmadığını ve açık config ile kontrollü bağlantıyı incele; koşu yalnız operatörün açık başlatmasıyla yapılır. Wallet/key/signing, exchange order veya live enable ayrı ve henüz yapılmamış işlerdir; dry-run başarısı bunlara izin vermez.
