# Devir dönemi durum belgesi (Sonnet lider; 05.11 – 09.11 14:00 TSİ)
Güncel tutulur; lider 09.11'de bunu okuyarak devralır. Saatler UTC, aksi belirtilmedikçe.

## Çalışma düzeni (kullanıcı kararı 05.11)
- Kodu Sonnet yazar. **Kritik iş ve kod denetimi: Opus 5.5 ajanı** (salt okur, rapor verir; bulguları Sonnet doğrular). **Basit/mekanik işler: Haiku ajanı.** Limit idareli kullanılır.

## Birleşen PR'lar
| PR | Konu | Kabul sayıları |
|---|---|---|
| #504 | T4 canlı motor + K-35/K-36 | 624 test; K-36 vardiyası 41926718012: 6 emir dolu, kayma ~%0,007 |
| #510 | T4b sağlamlaştırma (K-37) | 654 test; vardiya 41971493275 (255 dk): 8 emir (4 artırma), en büyük 43,9 $, hesap_yok 0, kayma +0,45 bp, gec_acilis 0, kapanis_eksik 0, funding −0,057 $, kuyruk p50 11 / max 1126 ms, kopma 1, 429 yok |
| #512 | T6 isabet, pano, yedek cron, para hareketi | 684 test; Opus denetimi: 2 orta bulgu düzeltildi |
| #514, #516–#519 | Telegram: sade Türkçe, emir özeti 15 dk, gece sessiz, gerçek kipte anında emir, tur başladı/bitti kaldırıldı | 689 test |
| #520–#524 | Pano: koyu terminal sayfası, sekmeler (Özet/Kadro/Pozisyon/İşlemler/Risk), Opus denetimi düzeltmeleri | 692 test |
| #525 | Lider belgesi: `DENETIM_PANO_2026-11-05.md`, K-38, K-39 | — |
| #526 | **K-39** kadro dışı iki UTC günü, bekleme yok, gün başına ilk kadro, 05.11 beklemesi silindi (gerçek saha.json ile denendi) | 694 test |
| #527 | Pano §B 1–7 (15 dk yenileme, bayat koruması, ölçekli grafik, işaretli fark, TR biçim) | 698 test |
| #528 | Eski pano sistemi kaldırıldı (pano.yml, pano_veri.py, pano/) | 688 test |
| #529 | Pano §C 1–6 (kopya koruması, atlanan sinyaller, kapanan işlemler, maliyet, maruziyet, kadro kartı) | 690 test |
| #530 (taslak) | **K-38** azaltma hedef tabanlı — radar önce/sonra (42062486135 ↔ 42063124874) ve deneme vardiyası 42063124202 (≈20:35Z) bekleniyor | 697 test |

## Açık sorunlar / lider kararı gerekenler
0. **Yeni (05.11 akşam):** (a) K-38'de trader hesabı bilinmiyorsa azaltma oransal yedeğe düşer (`hesap_yok` ile atlanmaz) — onay. (b) K-39 "üst üste" yorumu: kadro dışı sayacı kadroya dönünce sıfırlanır (sira_ust ile aynı) — onay. (c) Pano yayın yeri: kullanıcı Cloudflare Workers `sg-pano` kurdu (K-20 istisnası, yalnız salt okunur görüntü) — onay. (d) Pano §C2 "atlanan $" toplamı eksik: `boyut.hedef_emir` ayrıntılı çıktısı gerekir; K-38 birleşince küçük PR. (e) Telegram gerçek kipte her emir anında gider (kullanıcı kararı).
1. **T5 öncesi (gerçek kip) çözülmeli — Opus denetim bulguları** (`sonnet_durum_t4b.md` sonu): kısmi dolum+`canceled` kaybı; çökmede sonuçlu niyetlerin deftere oynatılmaması; net pozisyonda reduce-only reddi; `hl_ofset` sabitlenmesi.
2. HL <10 $ reduce-only muafiyeti doğrulanmadı (T5, kullanıcı onayıyla küçük gerçek deneme).
3. `yatirma_payi` min −8,27 (net çekme 538k $) incelenmedi; `kopya_koruma` min −21,7 incelenmedi (bilgi amaçlı).
4. Pano bayat `ozet.json` ile yazılabilir (vardiya başlamadan düşerse) — düşük.
5. `non_funding_ledger` sayfalanmıyor (çok satırlı hesapta net yatırma eksik; yalnız bilgi).
6. Opsiyonel temizlik: `sonnet_isci.yml` kullanılmıyorsa kaldır; `copytrade-izleme` dalı SİLİNMEDİ (lider kararı).

## Kullanıcıya verilen sözler
- Günde bir kısa, sade TSİ özeti. Telegram kuruldu (05.11 12:32 TSİ ilk mesaj geldi); mesajlar sadeleştirildi (#514).
- Pano (`canli-durum:pano/OZET.md`) ilk kez T6 kodlu vardiya sonunda oluşacak; oluşunca bildirilecek.
- Gerçek kip, cüzdan, anahtar, sunucu, kasa artırımı: lider dönünce birlikte.

## Canlıya geçiş — kullanıcı kararları (2026-11-05, lidere)
- **Sanal doğrulama: 7 gün** kesintisiz temiz çalışma. Sayaç yeni kodlarla (#533/#534/#535) başlayan ilk vardiyadan (≈ 05–06.11 gece) başlar. "Temiz" önerisi: vardiya boşluğu yok, `kapanis_eksik` 0, sağlık kontrolünde `KRITIK` yok (UYARI açıklanmış), haftalık denetimde engelleyici bulgu yok. Sayaç bozulursa (KRİTİK) 0'dan başlar — lider kararı.
- **İlk gerçek kasa: 100 $** (`canli_kasa_usd`; mevcut sanal kasa 1.000 $ ayarı bu karar gerçek kipe geçerken uygulanır, şimdi DEĞİŞMEZ: sanal seri bozulmaz). Artırım yalnız kullanıcı kararıyla, üst sınır 1.000 $ (K-22/K-26).
- Gerçek kip, cüzdan (MetaMask + para çekme yetkisiz API cüzdanı), anahtar, sunucu (T5): lider onayı + Opus denetimli gerçek kip riskleri (#2–#7 `sonnet_durum_t4b.md`, `/kapat` sonrası `risk.json dur` sıfırlama) çözülmeden BAŞLAMAZ.

## Önerilen kararlar (lider)
- **Telegram komutları (kullanıcı kararı 2026-11-05, lider denetimine):** `/kapat` = eski `/dur` (tüm pozisyonları kapat, motor durur, `DUR` dosyası). **Yeni `/dur`** = yalnız yeni giriş/artırma durur (`risk.acilis_durdu["elle_dur"]`, kalıcı); çıkış/azaltma serbest, motor çalışır, `DUR` yazılmaz (`docs/H2_KURULUM.md`'deki özgün `/dur` anlamı). `/devam` (= `/baslat`) duraklatmayı açar; `/kapat` sonrası açmaz (motor kapalı; yeniden açmak sunucudan — T5 sürekli sunucuda `DUR` silme/yeniden başlatma). Eski `/dur` testi `/kapat` ile aynen korundu.
- **Opus bulguları (lidere, T5 öncesi):** (1) `/kapat` sonrası yalnız `durum/DUR` silinip motor yeniden başlatılırsa `risk.json` içindeki `dur: true` kalır ve motor açılış yapmaz — T5 yeniden açma prosedürü `risk.json dur`'u da sıfırlamalı (ya da `baslat` DUR yokken sıfırlamalı). (2) İki vardiya arasında gönderilen komutlar `telegram_eski_komut` olarak sessizce düşer (kullanıcıya yanıt yok): komutu vardiya başladıktan sonra tekrar gönder. (3) `gunluk_kayip`/`mutabakat` etkinken `/durum` hâlâ "Risk: normal" der (eski; küçük iyileştirme).

## Günlük kontrol tablosu
| Tarih | radar çalıştı | gecti | ana vardiya sayısı/boşluk | kasa / özsermaye | olaylar |
|---|---|---|---|---|---|
| 05.11 | 07:18Z'de (birincil 6,7 sa geç; kadro var) | — | 04:58Z + 09:31Z; boşluk yok | 1.000 / ~1.000,7 | #510 #512 #514 birleşti; Telegram çalışıyor |
