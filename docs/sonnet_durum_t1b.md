# T1b durum (Sonnet) — Cloudflare/VPS bağımlılıklarını kaldır

Dal: `claude/t1b-sunucusuz` (taban: `main`, T1 birleşmiş). Görev: `docs/GOREV_T1B_SUNUCUSUZ.md` (K‑20).

## Not: görev belgeleri main'de yok
`GOREV_T1B_SUNUCUSUZ.md`, `GOREV_T2_RADAR_TARAMA.md`, güncel `RADAR_V1.md`/`KARARLAR.md` (K‑20…K‑27) `main`'de değil, `claude/stoic-carson-w3xagz` dalında.
Görevi o dalın belgelerinden okudum; kodu `main` tabanlı dalda yazdım.

## Açık sorular (lider)
1. **Veri dalı büyümesi:** `izleme/motor.json.gz` her koşuda (2 saatte bir) yeniden commit'leniyor; git geçmişi dalda birikir (önceden R2'deydi, repo büyümüyordu).
   Gz boyutu bilinmiyor (R2'deki dosya görülemedi); 90 MB üstü dosyada yayım kırmızı biter (mevcut sınır). Gerekirse dalı periyodik "yetim commit"e sıkıştırmak ayrı iş.
2. **Kabul grep'i** `\bR2\b` `docs/RADAR_V1.md` ve `DURUM.md`'deki strateji aşaması "R2 form puanı"nı da yakalıyor (R2 = Cloudflare depo değil); bu eşleşmeleri değiştirmedim.
3. `kol == "oda"` / `izleme_listesi.yaml` eski kol adları hâlâ duruyor (T1 notu); bu işte dokunulmadı.

## Yapılan
- Silindi: `worker/` (tamamı), `.github/workflows/worker.yml`, `copytrade/gecikme.py`, `copytrade/kararlar.py`, `tests/test_gecikme.py`.
- `izleme.yml`: R2 indir/yükle adımları kalktı; motor durumu veri dalından gelen `izleme/motor.json.gz`'den açılır. `izleme_yayimla.sh`: `motor.json` → `gzip -n -9` → `motor.json.gz`; `kararlar.jsonl`/`gecikme.json`/`degisim.json` yayım listesinden çıktı.
- `ci.yml` ve `sonnet_isci.yml`: node/Worker adımları kalktı.
- Belgeler: `H2_KURULUM.md` (sağlayıcıdan bağımsız), `VERI_SOZLESMESI.md` (Worker/D1/R2, kararlar, gecikme.json, Telegram bölümü çıktı; `gecikme_kar.json` kaldı), `FAZ1`, `FAZ3_TEKNIK_HAZIRLIK`, `saglik_hatti.py` docstring, `DURUM.md`.
- `deploy/sg-dinleyici.service`, `dinleyici.py`, `risk_defter.py`, `live_koruma.py`, `hl_ws_*`, `faz3_*`, `dinleyici_deneme.yml` aynen kaldı.
