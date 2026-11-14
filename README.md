# CT-Proje — Hyperliquid copy trade

**Form Radarı v1/v1.1** (`docs/RADAR_V1.md`, K-66): her gün son 7 günde formu yüksek, kopyalanabilir Hyperliquid trader'larını bul;
kadro 30 = İlk 11 + Yedek 19, sahada 11 slot. Şu an **sanal** (GitHub Actions vardiyası, sanal kasa 10.000 $ → 11 slot × ≈ 909 $; radar oynatması da aynı kasayla, `radar_kasa_usd`);
gerçek paraya geçiş kullanıcı kararıdır (gerçek kasa ≤ 1.000 $ → 5 slot × 200 $).

## Durum nerede
- `DURUM.md` — güncel durum, takvim (tek doğru kaynak)
- `docs/KARARLAR.md` — kararlar (K‑…)
- `docs/RADAR_V1.md` — strateji, eşikler (kilitli)
- `docs/VERI_SOZLESMESI.md` — alanlar ve birimleri
- `deploy/ACILIS_KONTROL.md` — gerçek para açılış listesi
- `AGENTS.md` — ajan/katkı kuralları

## Testler
```bash
pip install -r requirements.txt
python -m pytest -q
ruff check .        # CI'da sabit sürümle (ci.yml); yalnız F + E9 (ruff.toml)
```

## Veri dalları (yalnız iş akışları yazar)
- `radar` — günlük havuz + kadro (`radar.yml`, 03:37 TSİ); dal denemeleri `radar-deneme`'ye yazar.
- `canli-durum` — sanal motor durumu, kayıt, pano (`canli_vardiya.yml`); dal denemeleri `canli-durum-deneme`.
- `main`'e doğrudan push yok; PR + `test` ve `canli_sdk` yeşil.

## Güvenlik kuralları
- Repo herkese açık: **anahtar, token, şifre, kişisel veri commit edilmez**. Secret'lar yalnız GitHub Secrets'ta.
- **Gerçek para yalnız sunucuda** (`deploy/`), para çekme yetkisiz API cüzdanıyla; kasa ≤ 1.000 $ (K‑22/K‑26 sınırı, K‑50).
- İş akışlarında yazma token'ı yalnız yayım betiğine verilir (G‑23); checkout'lar kimlik bırakmaz.
