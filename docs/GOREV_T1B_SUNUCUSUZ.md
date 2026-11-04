# GÖREV T1b — Cloudflare/VPS bağımlılıklarını kaldır (Sonnet)

Dayanak: **K‑20, K‑21** (Cloudflare yok; anlık motor kalır, kâğıt kipi şimdilik Actions'ta vardiyalı, canlı sunucuda). Dal: `claude/t1b-sunucusuz` (main'den, T1 birleştikten sonra). Tek PR. Küçük iş.

## Silinecek
- `worker/` (tamamı), `.github/workflows/worker.yml`. (`deploy/sg-dinleyici.service` ve `docs/H2_KURULUM.md` **kalır**: sağlayıcıdan bağımsız
  systemd kurulumu olarak sadeleştir — DigitalOcean'a özgü adımları çıkar; canlı sunucuda kullanılacak.)
- `copytrade/gecikme.py` ve `copytrade/kararlar.py` (yalnız Worker D1'den okuyordu) + testleri; `izleme.yml`/diğer iş akışlarındaki `GECIKME_URL`,
  `KARAR_URL`, R2/Cloudflare adımları.
- `ci.yml`'deki Worker test adımı (node).

## Değişecek
- `izleme_motoru` motor durumu R2 yerine veri dalında (`copytrade-izleme`, `izleme/motor.json.gz`) okunur/yazılır; R2 kodu varsa kaldır.
  Davranış aynı; `izleme_deneme.yml` ile 1 trader deneme yeşil.
- Belgeler: `VERI_SOZLESMESI.md`, `FAZ1_ANLIK_KOPYA.md`, `FAZ3_TEKNIK_HAZIRLIK.md`'den Worker/D1/R2/VPS anlatımı çıkar; dinleyici bölümü "canlıda sunucu
  gerekir (K‑20)" notuyla kalır. `DURUM.md` "Kalan altyapı" satırından Worker ve VPS'i çıkar.

## Kalır
`dinleyici.py`, `risk_defter.py`, `live_koruma.py`, `hl_ws_*`, `faz3_*`, `dinleyici_deneme.yml` (GitHub runner'da gerçek ağ denemesi).

## Kabul
1. `grep -rniE "cloudflare|wrangler|workers\.dev|\bR2\b|\bD1\b|KARAR_URL|GECIKME_URL|digitalocean"` → yalnız `docs/KARARLAR.md` ve bu belge.
2. `python -m pytest -q` yeşil; silinen testler gerekçesiyle PR'da.
3. `izleme_deneme.yml` (1 trader) yeşil, bağlantı PR'da.
