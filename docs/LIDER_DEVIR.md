> **2026-10-30 gece (kullanıcı kararı: "tüm yetkilerini Sonnet'e devret, Pazartesi 14:00'e kadar her yetkin onda olsun"):**
> **2.11.2026 Pazartesi 14:00 TR'ye kadar** Claude'un (Opus) tüm liderlik yetkileri Sonnet'te: görev yazma, karar kaydı, PR açma,
> denetleyip birleştirme, temizlik/silme (sg-arge ve sg-pano), iş akışı ve belge yönetimi. Claude bu sürede iş yapmaz.
> Sınırlar aynen: `AGENTS.md` değişmez kuralları; para, hesap, ücretli servis, eşik, repo silme kararları kullanıcının.
> Devirde açık kalan: sg-pano temizliği yapılmadı (öneri: `ofis/kanit/` kanıt görselleri/videoları ve `docs/` altındaki eski ekran
> görüntüleri ile durum belgeleri silinebilir; `test/pano.test.js` `docs/` klasörüne ekran görüntüsü yazdığı için `docs/TASARIM.md` kalsın;
> silmeden sonra `node --test` ile testler doğrulanmalı). sg-arge temizliği #443 ile tamamlandı.

> **2026-10-30 akşam (kullanıcı kararı K‑11):** Yeni Sonnet oturumu **tek lider** ve birleştirme yetkili (CI yeşil + Sol denetimi
> sonrası). Görev `docs/GOREV_ETRE_GECIS.md`. Claude (Opus) bu işten çekildi. Codex (Sol) denetçi.

> **2026-10-30 güncelleme (kullanıcı kararı: "Sonneti kapatıcam yetkileri devral"):** Sonnet ortak liderliği sona erdi.
> Tek lider Claude (bu oturum); Codex (Sol) denetçi. Sonnet'in açık PR'ı #434 (`claude/zen-heisenberg-lx1ond`) lidere devredildi:
> önce `izleme_deneme.yml` ile küçük gerçek veri denemesi (O10, B17, O01, O02; motor süresi, v1↔v2), sonra Sol denetimi, sonra birleştirme.

# Lider devri — Sonnet ortak lider (2026-10-30 → 2026-11-02 Pazartesi), lider Claude (Opus) limitte

Okuma sırası: bu dosya → `DURUM.md` ("Şu an") → `AGENTS.md` (kurallar + **kalite kuralları**) → `docs/KARARLAR_D.md` (K‑5…K‑8) →
`docs/GOREV_VERI_DUZELTME.md`. Kullanıcı Türkçe, telefondan, teknik değil: kısa, sade, adım adım; TR saati (UTC+3).

## Yetki
- Sonnet bu süre için **ortak lider**: görev yazma, PR açma, sg-arge ve sg-pano PR'larını **denetleyip birleştirme** dahil.
- **Kullanıcıya sorulmadan yapılmaz:** para/hesap/anahtar, `kurallar.yaml` eşik değişikliği, ön kayıt (`docs/ONKAYIT_D.md`) değişikliği,
  oda/kontrol üyeliği değişikliği, repo/dal silme, gerçek emir (yasak: `AGENTS.md`, K‑7b; bot görevi askıda).
- Denetim: **Codex (Sol) bağımsız denetçi.** Senin yazdığın kodu Codex denetler (kalite kuralı 3: gerçek çıktıya bakılır).

## Durum (30.10 sabah)
- Pilot: 91 trader izleniyor (oda 18, kontrol 18 [E01 `kollar`'da], taban 18, elle 8, **havuz 30** — K‑8, t0 30.10, sessiz).
- Eski veri akışı: Worker'ın `izleme.yml` ve `arsiv.yml` iş akışlarını tetikleme mekanizması, bu iş akışları kaldırıldığı için emekliye ayrıldı.
  Telegram: işlem mesajları kapalı (`BILDIRIM_KIPI=ozet`), 09:00 TR günlük özet,
  veri > 3 sa / kalabalık uyarısı. `motor.json` R2'de (`izleme/motor.json.gz`), veri dalında değil.
- Eski `arsiv.yml` koşuları günlük boşluk eşiğinde **bilerek kırmızı** bitebiliyordu; bu iş akışı artık çalıştırılmıyor.
- İlk 91'lik izleme koşusu uzun (30 yeni trader 90 günlük geçmiş indirir). Bittiğinde: süre (motor adımı) ve 30 havuz trader'ının
  `gecerli` sayısı → makulse havuzun tamamı (`python -m copytrade.secim --izleme-listesi --secim <secim.json> --havuz-adet 154`,
  sonra izleme süresine bak; 150 dk iş sınırı).
- Faz 3: iptal edildi (süre sınırında bitemiyor) — isteğe bağlı, madde 12. Kalıcılık: sonucu sayısal bozuk — madde 13 (öncelikli).
- İzometrik tema tamamen kaldırıldı. Ofis tek görünüm (klasik). Telefonda menü → alttan bilgi paneli (sg-pano #43).

## Öncelik (Pazartesiye kadar; "önce veri" kuralı)
1. `docs/GOREV_VERI_DUZELTME.md` madde 1–11 (olay arşivi kesilmesi, tek fiyat eksiği, perp hesabı sıfır, geçersizlerin toplamlara
   girmesi, zaman damgası, sanal lot şeffaflığı/O10 negatif bakiye, mutabakat ikiye ayırma; pano: kasa tablosu sanal lotlardan,
   `kollar` üyeliği, son kapananlar, kapsam etiketleri). Her madde test + **küçük gerçek veri denemesi** (kural 1).
2. Madde 13 kalıcılık düzeltmesi → `kalicilik.yml` yeniden koşu → sade özet kullanıcıya.
3. Codex'in pano/ofis denetim bulguları (kullanıcı ayrı istedi) → düzelt.
4. Madde 14 kararsız test. Madde 12 (Faz 3) yalnız zaman kalırsa: önbellek → ön eleme → örneklem; önce 1 pencere × 50 hesap.

## Dikkat (ilk iki günün dersleri)
- Birimler: `sanal_kopya.getiri` **oran** (0,012 = %1,2); kaldıraç "x"; `hesap_degeri` trader hesabı $; sanal kopya 1.000 $ ölçeği;
  kol üyeliği için `kollar` (ana etiket `kol`). `uretildi` koşu başlangıcıdır.
- GitHub secret adı `GITHUB_` ile başlayamaz. Veri dalında dosya ≤ 90 MB. Bu ortamdan Hyperliquid API'ye erişim olmayabilir
  (proxy 403): deneme koşusunu Actions'ta küçük girdiyle yap.
- Her PR sonunda kullanıcıya 3 satır sade özet. Birleştirdiğin her şeyi `DURUM.md` "Şu an"a tek satırla yaz.
- Pazartesi: lider Claude döner; bu dosyanın sonuna "Devir notu" ekle (yapılan, açık kalan, kullanıcının kararını bekleyen).

## Devir notu (Sonnet doldurur)
