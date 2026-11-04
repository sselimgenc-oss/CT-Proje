# T2 durum (Sonnet) — Radar taraması: R0 evren + R1 kopyalanabilirlik

Dal: `claude/t2-radar-tarama` (taban: `main`). Görev: `docs/GOREV_T2_RADAR_TARAMA.md`, strateji `docs/RADAR_V1.md` (ikisi de `main`'de yok; `claude/stoic-carson-w3xagz` dalından okudum).

## Açık sorular / kararlar (lider)
1. **Süre ve API bütçesi (gerçek veriyle ölçüldü, kabul 3'ü etkiler).** `PublicClient` sınırı 700 ağırlık/dk. Hafta pnl'e göre ilk adaylar yüksek hacimli hesaplar: ilk aday 16.751 dolum = 63 sn (≈ 270 dolum/sn değil, **≈ 16 bin satır/dk**; 2.000'lik sayfa 120 ağırlık).
   Kopya oynatma için her **coin** bir kez 1 dk (20 + 83 ek ağırlık) ve 1 sa (20 + 3) mum serisi çeker (≈ 126 ağırlık ≈ 11 sn/coin); 250 farklı coin ≈ 45 dk. 300 adaylı tarama 150 dk iş sınırına **sığmayabilir**; sonuç PR açıklamasında. Olası kısaltmalar (belge kararı gerekir,
   yapmadım): (a) cheap-kural önceliği — `devir_yuksek` yalnız lider tablosuyla bilinir, bu adaylara dolum çekmemek (ama `neden` sırası ve "tüm ölçüler yazılır" ilkesi değişir); (b) dolum sayısı tavanı (bot/piyasa yapıcı); (c) API sınırını 1.200'e yaklaştırmak.
2. **Kaldıraç paydası:** `max_kaldirac` = pozisyon değeri / **koşu anındaki** `accountValue` (zaman serili hesap değeri için `portfolio` çağrısı aday başına ek 20 ağırlık; çekmedim). Hafta içinde büyük para giriş/çıkışı olan hesapta kaldıraç yanlı olabilir.
3. **Funding kopya oynatmaya girmez** (R1/6 yalnız taker + kayma diyor; funding çekmek aday başına ek sayfa).
4. **Yürütme fiyatı:** `candleSnapshot` yalnız son 5.000 dakikalık mumu verir → son ≈ 3,5 gün 1 dk mum, daha eskisi 1 sa mumun açılışı (`izleme_motoru.execution_candles` mevcut davranışı; 1 dk gecikme için kaba). Eksik fiyat uydurulmaz, eylem atlanır.
5. **Kopya motoru:** görev belgesi `kopya_v4.hesapla`, RADAR_V1 §3 `defter.copy_ledger` diyor; görev belgesini izledim. Tarz `intraday` (E3 çıkış kuralları); radar henüz tarz sınıflamıyor.
6. **Bootstrap tohumu** tabloda yok: adresin ilk 16 hex hanesinden türetilir (aynı girdi aynı sonuç).
7. **Sözleşmeye eklenen alan:** `fiyatsiz_eylem` (adet; görev listesinde yok, teşhis için; eksik mum "sayılır" maddesinden). Sözleşmede yazılı.
8. `vault`/`payda_yok` `neden` kodları R1 listesinde yok; R0 metni ve payda tanımından geldi, sözleşmede yazılı.
9. `tests/test_is_akislari.py` iş akışı listesi satırı T1b PR'ıyla birleştirmede çakışır (T1b `worker.yml`'i çıkarır, bu PR `radar_deneme.yml`'i ekler).

## Yapılan
- `copytrade/radar_tarama.py`: `evren` (R0), `islem_olculeri`, `kopya_olculeri`, `degerlendir` (R1), `MumOnbellegi` (coin başına bir kez mum), `Baglam.kopya_oynat` (`kopya_v4.hesapla`), `kos`, `ozet_md`, `main`.
- `kurallar.yaml`: 16 `radar_*` anahtarı (görev tablosu birebir). `docs/VERI_SOZLESMESI.md` §12 "Radar havuzu (R0/R1)".
- `.github/workflows/radar_deneme.yml` (`workflow_dispatch` + `copytrade/radar_deneme/CALISTIR` push tetiği; secret yok, veri dalına yazmaz).
- `tests/test_radar_tarama.py`: 28 test (altın örnekler elle hesaplı; her R1 sınırı tam üst/tam alt).

## Lider kararları (2026-11-04, Claude) — uygula, sonra 20 ve 300 adaylı koşu
1. **Bütçe: ucuzdan pahalıya sıra** (aynı eşikler; yalnız ölçüm sırası değişir, ölçülmeyen alan `null`):
   a) `devir_yuksek` lider tablosundan bilinir → dolum **çekilmeden** elenir; sonra `vault` sorgusu.
   b) Dolum tavanı: `client.fills(..., max_rows=radar_dolum_tavan)`, **`radar_dolum_tavan = 5000`**; tavana ulaşan → yeni kod **`dolum_fazla`**
      (7 günde 5.000+ dolum ≈ 2 dk'da bir; kopyalanamaz). Yeni anahtar `kurallar.yaml`'a, test ile.
   c) Dolum tabanlı kurallar (1–5: işlem, tutma, kısa, kaldıraç, likidite) önce; biri başarısızsa **kopya oynatma yapılmaz** (kopya alanları `null`).
   d) Radar istemcisi hız sınırı **1.100 ağırlık/dk** (HL IP sınırı 1.200); yeni anahtar `radar_api_agirlik_dk`.
   e) Zaman bütçesi **`radar_zaman_butcesi_dk = 120`**: aşılınca kalan adaylar `neden: zaman_yok`, özet ve PR'da sayısı.
   Yeni `neden` sırası: `veri_hatasi, payda_yok, devir_yuksek, vault, dolum_fazla, islem_az, tutma_kisa, kisa_islem_fazla, kaldirac_yuksek,
   likidite_dusuk, kopya_zarar, kopya_koruma_dusuk, sans_riski, akil_sagligi, zaman_yok`.
2. Kaldıraç paydası koşu anı `accountValue`: kabul (v1); sözleşmeye "koşu anı" yaz.
3. Funding oynatmaya girmez: kabul (v1); sözleşmeye yaz.
4. **Yürütme fiyatı:** 1 dk mumun olmadığı eski kısım (≈ 3,5 günden eski) için 1 sa yerine **5 dk mum** (5.000 × 5 dk ≈ 17 gün kapsar).
   Fiyat = t + gecikme anını içeren 5 dk mumun **açılış ve kapanışından bizim yönümüze kötü olanı** (alışta büyük, satışta küçük; temkinli).
   `izleme_motoru.execution_candles`'a isteğe bağlı parametre ile ekle, **varsayılan bugünkü davranış** (izleme değişmez, kural 6). Altın örnek ekle.
   Her satıra `yaklasik_fiyat_eylem` (adet) yaz; sözleşmeye ekle.
5. `kopya_v4.hesapla` doğru (RADAR_V1 metni düzeltildi). Tarz `intraday` kabul.
6–8. Kabul.
9. T1b (#494) önce birleşir; sonra `main`'i bu dala birleştir (çakışma: iş akışı listesi, ikisini de uygula).
Kabul: görev §5 aynen (20 ve 300 adaylı koşu bağlantısı, süre, 429, neden dağılımı, sütun min/medyan/max).
