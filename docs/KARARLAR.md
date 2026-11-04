# Kullanıcı kararları (yeni dönem; eskisi `KARARLAR_D.md` T1 ile silinir)

### K‑19. Form Radarı: şimdi + gelecek; eski sistem silinir (kullanıcı, 2026-11-04)
- Strateji geçmiş performans kapısından çıkıp **son 7 günlük form + seçim sonrası ileri deneme** üzerine kurulur: `docs/RADAR_V1.md`.
- Onaylanan lider önerileri: hype = trader'ın sıcak dönemi + trend coini erken yakalama (ikisi); evren ön filtresi hesap ≥ 10.000 $,
  7 günde ≥ 10 işlem, kaldıraç ≤ 20x; günlük kayan 7 günlük pencere, tek kötü günde atma yok (art arda gün kuralı); tutma medyanı ≥ 1 saat;
  kasa zirveden −%20'de her şey durur.
- **Eski sistem** (Kapı v3, İlk 11 puanı, oda/kontrol, ön kayıt, seçim, araştırma) **tamamen silinir**; yan yana tutulmaz. Görev: `GOREV_T1`.
- Roller: **Claude (Opus) = lider/beyin**: tasarım, görev belgesi, denetim (gerçek çıktıya bakarak), birleştirme. **Sonnet = yazıcı**:
  kod, test, PR. Codex devre dışı.
- Kullanıcıda kalan: canlıya geçiş (son karar), sermaye miktarı, para/hesap/anahtar/cüzdan, sunucu. Gerçek para yasağı canlı kapısı
  (`RADAR_V1.md` §7) geçilip kullanıcı açıkça karar verene kadar sürer.

### K‑20. Cloudflare ve DigitalOcean yok; her şey GitHub Actions'ta (lider kararı, 2026-11-04)
- Kullanıcı iki hesabı da kapattı. Worker (Telegram, D1, R2) ve VPS (anlık dinleyici) **artık yok**.
- Gerekçe: ileri sanal kopya hesabı dolum zamanlarından **sonradan** yapılır (1 dk gecikme modeli), yoklama sıklığı sonucu değiştirmez →
  paper için anlık sunucu gerekmez. Günlük tarama ve 2 saatlik ileri deneme GitHub Actions'ta; durum veri dalında; Telegram (varsa) doğrudan
  Actions'tan Bot API ile.
- Anlık dinleyici kodu (`dinleyici.py`, `risk_defter.py`, `live_koruma.py`) **kalır**: canlıya geçişte gerekir. Sunucu seçimi canlı kararıyla birlikte
  kullanıcıya gelir.
- Görev: `docs/GOREV_T1B_SUNUCUSUZ.md`.
