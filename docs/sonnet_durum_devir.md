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
- **Sanal doğrulama: 7 gün** kesintisiz temiz çalışma. Sayaç, lider kararındaki gerçek kip öncesi + Telegram maddeleri main'e testli birleştikten sonraki ilk vardiyadan başlar (önceki "#533/#534/#535" tarihi geçersiz). "Temiz" önerisi: vardiya boşluğu yok, `kapanis_eksik` 0, sağlık kontrolünde `KRITIK` yok (UYARI açıklanmış), haftalık denetimde engelleyici bulgu yok. Sayaç bozulursa (KRİTİK) 0'dan başlar — lider kararı.
- **İlk gerçek kasa: 300 $** (kullanıcı kararı 05.11 akşam; önceki 100 $ geçersiz, bkz. KARARLAR "Lider kararları — 2026-11-05 akşam") (`canli_kasa_usd`; mevcut sanal kasa 1.000 $ ayarı bu karar gerçek kipe geçerken uygulanır, şimdi DEĞİŞMEZ: sanal seri bozulmaz). Artırım yalnız kullanıcı kararıyla, üst sınır 1.000 $ (K-22/K-26).
- Gerçek kip, cüzdan (MetaMask + para çekme yetkisiz API cüzdanı), anahtar, sunucu (T5): lider onayı + Opus denetimli gerçek kip riskleri (#2–#7 `sonnet_durum_t4b.md`, `/kapat` sonrası `risk.json dur` sıfırlama) çözülmeden BAŞLAMAZ.

## Lider kararları 05.11 akşam — iş listesi (KARARLAR.md'ye işli)
| # | İş | Durum |
|---|---|---|
| 1 | Docs: K‑41 + kararlar + 300 $ | ✔ #537 |
| 2 | Dal temizliği (22 birleşmiş dal silindi; liste #538; `copytrade-izleme` kullanıcı ayrıca onaylamadı → durur; geçici `claude/gecici-dal-sil` kaldı, silinecek) | ✔ (kısmen) |
| 3 | t4b #2, #3 (atomik yazım + çökme testi), #6, #7 | ✔ #541 (Opus bulguları düzeltildi) |
| 4 | K‑41 `ters_netlesme` + #5 `hl_ofset += net` (yatırma−çekme; Opus: HL−yerel birikmiş farkı silmesin) + `non_funding_ledger` sayfalama | ✔ #540 |
| 5 | Telegram: baslat DUR sıfırlama, vardiya arası komut yanıtı, `/durum` bayrakları; DUR dosyası kapanıştan ÖNCE atomik (Opus bloklayıcı) | ✔ #539 |
| 6 | Pano: Sağlık+Risk K/Z altına (#542), KADRO sekmesi SAHADA n/11 / BEKLİYOR sarı / İNİYOR / YEDEK (#543) | ✔ |
| 7 | 300 $ paralel sanal vardiya | **İPTAL (kullanıcı kararı 05.11: iki iş yapıp sistemi yormayalım)**; yerine gerekirse mevcut 1.000 $ kayıtlarından tek seferlik "300 $ olsaydı" yeniden hesabı |
| 8 | `yatirma_payi` 7 gün ölçüm satırı (radar özeti) | sırada |
| 9 | `sonnet_isci.yml`: aktif (@sonnet yorumu tetikler), KALDIRILMADI | karar lidere |
| 10 | K‑38 (#530): kod Opus denetiminde doğru; önceki vardiya sayıları BAŞKA dalın koşusuydu (geçersiz). Temiz deneme vardiyası 21:35Z başladı (≈ 01:50Z biter) | bekliyor |

**7 günlük sayaç:** B ve C maddeleri main'de (#539/#540/#541, 05.11 21:2x Z). Sayaç, bunlardan sonra YENİ KODLA başlayan ilk ana vardiyadan başlar: mevcut vardiya (run 42101416359) 20:40Z'de eski kodla başladı, ≈ 00:55Z'de biter; sonraki vardiya (≈ 00:55Z = 03:55 TSİ) sayacın başı. Yeni pano görünümü de o vardiyada canlıya gelir.

**T5 öncesi kalanlar (Opus notları):** HL < 10 $ reduce-only (toz kalıntı, kullanıcı onaylı küçük gerçek deneme); kısmi azaltma kalıntısı 1–10 $ trader tam kapatınca `kapanis_eksik` (t4b); `kucuk_kalan_kapat` için hesap okuması yaşı/sapması koruması; `canli-durum-deneme` tek veri dalı iki dal çakışması (kilit); `azalt_oransal_yedek` tam/kısmi ayrımı kayda alanı; `orderStatus canceled` kalan `sz` varsayımı T5 denemesinde doğrulanacak.

## Önerilen kararlar (lider)
- **Telegram komutları (kullanıcı kararı 2026-11-05, lider denetimine):** `/kapat` = eski `/dur` (tüm pozisyonları kapat, motor durur, `DUR` dosyası). **Yeni `/dur`** = yalnız yeni giriş/artırma durur (`risk.acilis_durdu["elle_dur"]`, kalıcı); çıkış/azaltma serbest, motor çalışır, `DUR` yazılmaz (`docs/H2_KURULUM.md`'deki özgün `/dur` anlamı). `/devam` (= `/baslat`) duraklatmayı açar; `/kapat` sonrası açmaz (motor kapalı; yeniden açmak sunucudan — T5 sürekli sunucuda `DUR` silme/yeniden başlatma). Eski `/dur` testi `/kapat` ile aynen korundu.
- **Opus bulguları (lidere, T5 öncesi):** (1) `/kapat` sonrası yalnız `durum/DUR` silinip motor yeniden başlatılırsa `risk.json` içindeki `dur: true` kalır ve motor açılış yapmaz — T5 yeniden açma prosedürü `risk.json dur`'u da sıfırlamalı (ya da `baslat` DUR yokken sıfırlamalı). (2) İki vardiya arasında gönderilen komutlar `telegram_eski_komut` olarak sessizce düşer (kullanıcıya yanıt yok): komutu vardiya başladıktan sonra tekrar gönder. (3) `gunluk_kayip`/`mutabakat` etkinken `/durum` hâlâ "Risk: normal" der (eski; küçük iyileştirme).

## Günlük kontrol tablosu
| Tarih | radar çalıştı | gecti | ana vardiya sayısı/boşluk | kasa / özsermaye | olaylar |
|---|---|---|---|---|---|
| 05.11 | 07:18Z'de (birincil 6,7 sa geç; kadro var) | — | 04:58Z + 09:31Z; boşluk yok | 1.000 / ~1.000,7 | #510 #512 #514 birleşti; Telegram çalışıyor |

## Sayaç — temiz tanımı (genişletilmiş, lider kararı 05.11 gece)
Sayaç günü "temiz" sayılır ancak hepsi doğruysa:
- vardiya işi başarısız / iptal / zaman aşımı yok;
- `BAŞLAMADI` ve vardiya boşluğu yok;
- mutabakat alarmı yok; `adim_hata`, `olay_hata`, `defter_hata` 0;
- `kapanis_eksik` 0;
- kadro her gün geldi;
- sağlık işi günde ≥ 20 kez koştu;
- komut kaybı yok;
- KRİTİK yok.

## T5 öncesi zorunlular (Opus uçtan uca denetim, 05.11 gece)
1. Telegram tek tüketici (B1): deneme dalında token yok — ✔ bu PR (`canli_vardiya.yml`, `saglik.yml`: secret yalnız `refs/heads/main`).
2. Kip/kasa yalnız sunucuda okunsun (B2; radar ve sanal seri etkilenmesin).
3. API cüzdanı doğrulaması (Y3: ana anahtar değil agent; HL değeri ≤ 1.000 $ uyarısı).
4. HIP-3 + spot kararı (B3 + Y1).
5. Gerçek funding/ücret deftere (B4).
6. Gerçek motor nabız/özet yayını + sağlık kontrolünün okuması (Y2).
7. Kip/kasa uyuşmazlığında başlama yok (O11); kurulum belgesinde `/dur` ↔ `/kapat` (O10) — ✔ bu PR.
8. HL 10 $ altı reduce-only tam kapanış: kullanıcı onaylı küçük gerçek deneme.
9. Patlama freni (O1); K-38 kararı (O2: birleş ya da belge notu).
