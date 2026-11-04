# GÖREV T2 — Radar taraması: R0 evren + R1 kopyalanabilirlik (Sonnet)

Dayanak: `docs/RADAR_V1.md` §1–3 (K‑19). Dal: `claude/t2-radar-tarama` (main'den). Tek PR. Puanlama (R2) ve kadro (R3) bu işte **yok**.

## 1. Kod
- Yeni modül **`copytrade/radar_tarama.py`**: `evren(...)` (R0), `kopyalanabilirlik(...)` (R1), `kos(...)` (ikisi + yazım), `main()` (CLI).
  İki kip (`RADAR_V1.md` §2, K‑25): `--kip tam` (hafta pnl ilk 300) ve `--kip sicak` (gün pnl ilk 50, kadroda olmayan, son 6 sa değerlendirilmiş
  olan atlanır; `--kadro` dosyası verilirse onun üyeleri de eklenir). Kadro/sıralama mantığı T3–T4'te; T2 yalnız havuzu üretir.
- **Kural 7 (tek yer):** HL istekleri yalnız `tarama.PublicClient` ile; işlem eşleme `olcut.closed_round_trips`, kaldıraç `olcut.effective_leverage_detail`;
  kopya oynatma **yalnız** mevcut motorla (`kopya_v4.hesapla`, sabit tutar + v4 risk sınırları), piyasa/mum verisi `izleme_motoru`'nun mevcut
  hazırlayıcısıyla (gerekirse oradan ortak fonksiyona çıkar, kopyalama). Maliyet `hl_ortak.TAKER/SLIPPAGE`.
- Eşikler yalnız `kurallar.yaml`'da, yeni anahtarlar (kodda sayı sabiti yok; `tests/test_kurallar_anahtarlari.py` kapsar):

| Anahtar | Değer | Birim |
|---|---|---|
| `radar_min_hesap_usd` | 10000 | trader_$ |
| `radar_aday_tavan` | 300 | kişi (tam) |
| `radar_sicak_aday_tavan` | 50 | kişi (sıcak, gün pnl) |
| `radar_sicak_tekrar_saat` | 6 | saat |
| `radar_pencere_saat` | 168 | saat |
| `radar_min_islem` | 10 | kapanmış round trip |
| `radar_min_medyan_tutma_saat` | 1.0 | saat |
| `radar_kisa_islem_dk` | 5 | dakika |
| `radar_kisa_islem_payi_max` | 0.25 | oran |
| `radar_max_kaldirac` | 20.0 | x |
| `radar_likit_coin_hacim_usd` | 1000000 | $ (coin 24 sa nosyonel hacim, `metaAndAssetCtxs.dayNtlVlm`) |
| `radar_likit_pay_min` | 0.80 | oran (nosyonel) |
| `radar_kopya_gecikme_dk` | 1 | dakika |
| `radar_kopya_koruma_min` | 0.50 | oran (kopya getirisi / trader getirisi) |
| `radar_akil_sagligi_getiri_max` | 3.0 | oran (+%300) |

## 2. Tanımlar (karar verildi; değiştirme)
- **R0:** lider tablosu satırı; `accountValue ≥ radar_min_hesap_usd`, hafta penceresi `pnl > 0` ve `vlm > 0`. Hafta `pnl`'e göre azalan sıra, ilk
  `radar_aday_tavan` alınır. Kesilen kişi sayısı `evren_kesilen` olarak yazılır. Vault: adres `vault_details` ile vault çıkıyorsa `vault` nedeniyle elenir
  (yalnız ilk 300'e sorgu).
- **Trader getirisi (R1/6 paydası):** `trader_getiri_7g = hafta_pnl / (accountValue − hafta_pnl)` (oran; yatırma/çekme `pnl`'i etkilemez).
  Payda ≤ 0 → elenir, neden `payda_yok`.
- **Pencere:** `[kosu_ms − 168 sa, kosu_ms)`. Pencere başında açık pozisyon: round trip sayısına yalnız pencere içinde kapananlar girer; kopya
  oynatması pencere başında **boş** başlar (açık pozisyon kopyalanmaz; RADAR_V1 §5 ile aynı ilke).
- **Kurallar sırayla** değerlendirilir, ilk başarısız kuralın kodu `neden` olur ama **tüm** ölçüler yine yazılır (teşhis için):
  `islem_az`, `tutma_kisa`, `kisa_islem_fazla`, `kaldirac_yuksek`, `likidite_dusuk`, `kopya_zarar` (kopya getirisi ≤ 0), `kopya_koruma_dusuk`
  (kopya / trader < 0,50), `akil_sagligi` (kopya getirisi > 3,0 ya da hesap ≤ 0), `veri_hatasi` (istek hatası; mesaj `hata` alanında, uydurma yok).
- Sınırlar **dahil**: tam 10 işlem geçer, tam 1,0 sa geçer, tam %25 geçer, tam 20x geçer, tam %80 geçer, tam %50 geçer.

## 3. Çıktı ve sözleşme
- `radar/<YYYY-MM-DD>/havuz.json` (tam) ve `radar/<YYYY-MM-DD>/sicak_<HH>.json` (sıcak): `{"sema": "radar-havuz-v1", "kip", "kosu_ms", "pencere_bas_ms", "evren_toplam", "evren_kesilen", "satirlar": [...]}`;
  satır: `adres, hesap_usd (trader_$), hafta_pnl_usd (trader_$), trader_getiri_7g (oran), islem_sayisi, medyan_tutma_saat, kisa_islem_payi (oran),
  max_kaldirac (x), likit_pay (oran), kopya_getiri_7g (oran, 1.000 kopya_$ ölçeğinde), kopya_koruma (oran), gecti (bool), neden (kod|null), hata (str|null)`.
- `docs/VERI_SOZLESMESI.md`'ye yeni bölüm **"Radar havuzu (R0/R1)"**: her alanın birimi/ölçeği/zamanı, yukarıdaki gibi. Sözleşmeye yazılmayan alan yazılmaz.
- İş akışı **`radar_deneme.yml`** (yalnız `workflow_dispatch`, girdi `aday_sayisi` varsayılan 20): koşar, `havuz.json`'u artifact olarak yükler,
  özet tabloyu (`gecti` sayısı, neden dağılımı, her sayısal sütunun min/medyan/max) iş özetine yazar. Zamanlama (cron) T4'te.

## 4. Testler (altın örnek zorunlu; elle hesaplanmış sayılar)
- Her R1 kuralı için sınırın hem tam üstü hem tam altı (ör. 10 işlem geçer / 9 elenir) — sentetik dolumlarla, beklenen sayı test içinde elle yazılı.
- `trader_getiri_7g` altın örnek: hesap 11.000, pnl 1.000 → 1.000/10.000 = 0,10. Payda sıfır ve negatif → `payda_yok`.
- Kopya oynatma altın örnek: tek coin, 1 long aç/kapat, fiyat 100→110, gecikme 1 dk'da dolum fiyatı mumdan, maliyetler dahil — beklenen kopya getirisi elle.
- Uç durumlar (kalite kuralı 1): boş dolum listesi, pencere başında açık pozisyon, eksik mum (fiyatsız eylem sayılır, uydurulmaz), hesap 0, 2.000+ dolum
  (sayfa sınırı), lider tablosunda eksik alan, API 429 (mevcut `RateLimiter`/yeniden deneme).
- `python -m pytest -q` ve `npm test --prefix worker` yeşil.

## 5. Kabul
1. Testler yeşil; PR'da önceki/sonraki test sayısı.
2. **Küçük gerçek veri denemesi:** `radar_deneme.yml` `aday_sayisi=20` ile koşmuş, bağlantısı PR'da; PR açıklamasında satır sayısı, `gecti` sayısı,
   neden dağılımı, her sayısal sütunun min/medyan/max'ı. Akıl sağlığı: hiçbir oran milyon % değil, kopya kasası 1.000 $ ölçeğinde.
3. Sonra `aday_sayisi=300` koşusu: süre (dk) ve 429 sayısı PR'da (T4 günlük zamanlaması bu süreye göre kurulacak; 150 dk iş sınırı).
4. `DURUM.md` T2 satırı güncel.
