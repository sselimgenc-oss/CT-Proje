# T1 durum notu (Sonnet) — eski sistemi sil

Dal: `claude/t1-eski-sistem-sil` (taban: `claude/stoic-carson-w3xagz`). Karar bekleyen sorular **lider için**; dokunmadım, tahminle ilerlemedim.

## Lider kararı gereken (belgede yazmayan / belge ile çelişen)
1. **`ilk11` adı kalan altyapıda yaşıyor.** Kabul grep'i (`ilk11`) yalnız 4 dosyaya izin veriyor, ama "kalır" listesindeki dinleyici, risk defteri ve
   Faz 3 hazırlığı İlk 11'i yeni kadronun adı olarak kullanıyor: `dinleyici.py` (`takim == "ilk11"`), `risk_defter.py` (`ilk11` kümesi, sayaç `ilk11_disi`),
   `live_koruma.py` (ret kodu `yalniz_ilk11`), `faz3_preflight.py` (`grup='ilk11'`), `izleme_liste.py` (`takim` değerleri), `pano_veri.py` (`TAKIMLAR`),
   `risk_deneme.py` ve bunların testleri + `VERI_SOZLESMESI.md` §7/§10 + `H2_KURULUM.md`. Yeniden adlandırma sunucudaki dinleyici sözleşmesini ve
   ret kodlarını değiştirir → **yapmadım**. Seçenek A: RADAR_V1'deki "İlk 11" adı olarak kalsın, grep istisnası genişlesin (önerim).
   Seçenek B: tamamını `kadro` gibi bir adla yeniden adlandıran ayrı PR.
2. **Worker `kol == "oda"` bildirim akışı duruyor.** `isNotified`, günlük özet (oda kasası, oda−kontrol farkı), `/durum` yalnız `kol = oda` için çalışıyor
   (`worker/src/index.js`). Kaldırsaydım Telegram bildirimi tamamen susardı ve yerine geçecek tanım yok (T4). Yalnız kapı/oda'nın ürettiği
   **kalabalık uyarısı ve yönsüz bayrak satırı** çıkarıldı (üreten kod silindi). `izleme_listesi.yaml` (891 satır, `kol: oda/kontrol/taban/havuz`) da
   olduğu gibi duruyor: dinleyici ve Worker bunu okuyor.
3. **`izleme_motoru.py` içinde `kol == "oda"` ile yazılan `veri_kalitesi.mutabakat` kaldı** (kalan `test_pozisyon_mutabakat.py` bunu sınıyor; test zayıflatılmadı).
   T4'te radar kadrosuna bağlanmalı.
4. **`son_yaz.py` + `tests/test_son_json.py`** yalnız silinen kapı yayımcısından çağrılıyordu; listede yok, emin olmadığım için **silmedim**.
5. **`izleme_liste.py` içindeki `KOLLAR` ve `takim` şeması** eski kol adlarını (`oda`, `kontrol`, `taban`, `referans_*`, `cikarilan`, `havuz`) doğruluyor;
   liste dosyası bunları kullandığı için değiştirmedim.
6. **Kuralda yeniden adlandırma (davranış aynı):** kalan kodun okuduğu `ilk11_form_pencere_gun`, `ilk11_durum_min_gecerli_islem`, `ilk11_form_tazelik_dk`
   anahtarları, kabul grep'ine uymak için `kapanan_islem_pencere_gun`, `kapanan_islem_min_gecerli`, `veri_tazelik_dk` oldu (değerler aynı: 30, 6, 270).

## Yapılan taşımalar (kural 7: kopya değil, taşıma)
- `kapi.py` → **`copytrade/hl_ortak.py`**: `TAKER`, `SLIPPAGE`, `spot_usdc`, Binance eşleme/evren/`binance_availability` (davranış aynı).
- `ilk11_deneme.py` → **`copytrade/deneme_arac.py`**: yalnız genel parçalar (`liste`, `durum-ozeti`, `sure_tahmini`); iş akışları buna bağlandı.
- `tarama.py`: `PublicClient`, `RateLimiter`, `_address`, `_window` kaldı; eski günlük aday tarayıcı (`prefilter`, `run`, `main`, rapor) silindi (izleme.csv/`kopya.simulate` ile birlikte eski sistemdi).
- `kurallar.py`: `evaluate` (eski aday süzgeci) silindi. `kurallar.yaml`: 174 → 32 anahtar; kalan her anahtarı kalan kod okuyor (`tests/test_kurallar_anahtarlari.py` bunu her koşuda sınar).
- `izleme_motoru.py`: kapı sonucu okuma (`gate_result`, `gate_style`), `oda_risk` bağlantısı (yönsüz, kalabalık), `kasa_egri` (oda/kontrol), `ilk11_form_ham`, `ilk11_gecerli_saat` çıkarıldı.
  Tarz artık yalnız listeden (`tarz` yoksa `bilinmiyor`, 30 dk).
- `pano_veri.py`: İlk 11 snapshot okuması çıkarıldı (`pano_uret(durum, liste, simdi)`, `--ilk11` yok); `kadro_toplam` hep `null`; pano.js boş durumda "Radar kadrosu T4'te" gösterir.
- `izleme.yml`: cron kaldırıldı (yalnız elle), kapı/İlk 11 liste adımı çıktı; `pano.yml` yalnız `copytrade-izleme` dalını okur.

## Elle düzeltilen test sayıları ve kanıt
Ayrıntı PR açıklamasında (önceki/sonraki sayılar, silinen dosya ve fonksiyon listesi).
