# GÖREV T1 — Eski sistemi tamamen sil (Sonnet)

Dayanak: kullanıcı kararı **K‑19** (2026-11-04): "eski sistemi, kapıyı tamamen kaldır sil, eski sisteme ilişkin repoda hiçbir şey kalmasın."
Yeni strateji: `docs/RADAR_V1.md`. Dal: `claude/t1-eski-sistem-sil` (main'den). Tek PR.

## İlke
- **Eski sistem** = Kapı v3 ve tüm adımları, İlk 11 puanı/Pazar kadrosu, seçim/bayrak/oda/kontrol/taban/havuz kolları, ön kayıt, geçiş/rotasyon,
  haftalık analiz/rapor, arşiv, araştırma klasörü, bunların iş akışları, testleri, belgeleri, `kurallar.yaml` anahtarları.
- **Kalır (yeni sistem kullanacak):** kopya motoru, HL veri istemcisi, anlık dinleyici, risk defteri, izleme motorunun kopya/ölçüm çekirdeği,
  Worker, pano iskeleti, Faz 3 (canlı hazırlık) modülleri.
- Kalan bir modül silinen bir modülden fonksiyon alıyorsa: **o fonksiyonu kalan tarafa taşı** (kopyalama değil, tek yer — kural 7),
  silinen modülü sonra sil. Davranış değişmez; kalan testler aynen geçmeli.
- Listede olmayan ve emin olmadığın dosya: **silme, dur**, `docs/sonnet_durum_t1.md`'ye yaz.

## Silinecekler
**Kod (`copytrade/`):** `kapi.py`, `kapi_yeniden.py`, `kapi_ab.py`, `kesif.py`, `secim.py`, `bayrak.py`, `bayrak_ek.py`, `yogunlasma.py`,
`ilk11.py`, `ilk11_alanlar.py`, `ilk11_veri.py`, `ilk11_pazar.py`, `ilk11_deneme.py`, `ilk11_deneme/`, `pazar_akis.py`, `gecis.py`, `degisim_rapor.py`,
`analiz_d.py`, `analiz_kosu.py`, `haftalik_rapor.py`, `arsiv.py`, `arsiv_alarm.py`, `pilot_veri.py`, `risk_isaretleri.py`, `hf_dogrulama.py`,
`golge_saglama.py`, `sentetik.py`, `izleme.py` ve `kopya.py` (v1; `tarama.py`'nin bunlardan aldığı kalacak parça varsa önce taşı), `oda_risk.py`
(oda kavramı gidiyor; `izleme_motoru` bağlantısı çıkarılır — kalabalık/coin yoğunlaşması T5'te radar kadrosu için yeniden yazılacak).
**Diğer:** `kapi/` (klasör; `kurallar.py`'nin `kapi/istatistik.py`'den aldığı kalan bir şey varsa taşı), `arastirma/` (tamamı).
**İş akışları:** `copytrade_kapi.yml`, `ilk11_pazar.yml`, `ilk11_deneme.yml`, `izleme_v3_yan_yana.yml`. `izleme.yml`'in zamanlamasını (cron) kaldır
(eski kadroyu izliyor; T4'te radar kadrosu için geri gelir), `izleme_deneme.yml` ve `gecikme_kar_deneme.yml`'den `ilk11`/`kapi` adımlarını çıkar.
**Belgeler (`docs/`):** `KAPI_V3.md`, `ILK11_KADRO_V1.md`, `ILK11_SECIM_SARTNAME.md`, `ONKAYIT_D.md`, `KARARLAR_D.md` (yerini `KARARLAR.md` aldı),
`FAZ2_ODA_KARARLARI.md`, `DENETIM_TRADER_2026-10-30.md`, `GOREV_SECIM_V1.md`, `GOREV_SECIM_V13.md`, `GOREV_TRADER_SECIMI.md`, `GOREV_H1_GECIKME_KAR.md`,
`GOREV_H2_DINLEYICI.md`, `GOREV_H5_RISK.md`, `GELISIM_GUNLUGU.md`, `LIDER_DEVIR.md`, `PROTOKOL.md`, `WORKER_TETIKLEME.md`, `codex_durum_a0_test.md`,
`sonnet_durum_hf.md`. `VERI_SOZLESMESI.md` ve `FAZ2_PANO.md`'den eski sisteme ait bölümleri (kapı, İlk 11 puan alanları, oda/kol, ön kayıt) çıkar;
kopya motoru, dinleyici, gecikme bölümleri kalır.
**Testler:** yalnız silinen modülleri test eden dosyalar silinir. Kalan modülü test eden dosyada eski sisteme ait test fonksiyonu varsa yalnız o
fonksiyon gider; kalan modüllerin testleri **zayıflatılmaz**. Silinen her test dosyası PR'da gerekçesiyle listelenir.
**`kurallar.yaml`:** yalnız silinen kodun okuduğu anahtarlar silinir (kapı eşikleri, plasebo, alfa, BHY, ilk11_*, oda/kol, golge_terfi_*, aktif_* vb.).
Kalan kodun okuduğu (maliyet, kopya gecikmesi, sabit tutar, golge_v2, tasfiye, pozisyon tavanı, dinleyici/risk) **kalır**. Kontrol: kalan kodda
`load_rules()[...]` ile okunan her anahtar dosyada var (test ekle: `tests/test_kurallar_anahtarlari.py`).
**Pano / Worker:** `pano_veri.py` İlk 11 snapshot'ına bağlı → İlk 11/snapshot okuması çıkarılır, takım bölümü "radar kadrosu T4'te" boş durumu
gösterir; Worker'da kapı/ilk11/oda kodu varsa çıkar (`node --test` yeşil kalmalı).

## Dallar (kod PR'ı birleştikten SONRA, lider yapar)
- Uzak veri dalı `copytrade-kapi` ve birleşmiş/eski tüm `claude/*`, `codex/*`, `faz1-son` dalları silinir. `main` ve `copytrade-izleme` kalır
  (izleme verisi T4'te yeni veri dalı açılınca silinir). Not: git geçmişi (commit'ler) GitHub'da kalır; geçmişi yeniden yazmak ayrı kullanıcı kararıdır.

## Kabul
1. `grep -rniE "kapi_v3|ilk11|ilk 11 puan|onkayit|oda_risk|kontrol kolu|plasebo|bhy" --include=*.py --include=*.yml --include=*.md --include=*.yaml --include=*.js .`
   → yalnız `docs/RADAR_V1.md`, `docs/KARARLAR.md`, `DURUM.md`, bu görev belgesi (İlk 11 yeni kadronun adı olarak RADAR_V1'de kalır).
2. `python -m pytest -q` yeşil; `cd worker && node --test` yeşil. PR'a önceki ve sonraki test sayısı + silinen test listesi.
3. `python -m copytrade.izleme_motoru --help` ve `python -m copytrade.dinleyici --help` çalışır (import kırığı yok).
4. Küçük gerçek veri denemesi (kural 1): `dinleyici_deneme.yml` ve `izleme_deneme.yml` (1 trader) GitHub Actions'ta yeşil; koşu bağlantısı PR'da.
5. `DURUM.md`'ye 3 satırlık T1 notu.
