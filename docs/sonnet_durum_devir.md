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
| #514 | Telegram sade Türkçe mesajlar | 685 test |

## Açık sorunlar / lider kararı gerekenler
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

## Önerilen kararlar (lider)
- (boş; yeni öneriler buraya)

## Günlük kontrol tablosu
| Tarih | radar çalıştı | gecti | ana vardiya sayısı/boşluk | kasa / özsermaye | olaylar |
|---|---|---|---|---|---|
| 05.11 | 07:18Z'de (birincil 6,7 sa geç; kadro var) | — | 04:58Z + 09:31Z; boşluk yok | 1.000 / ~1.000,7 | #510 #512 #514 birleşti; Telegram çalışıyor |
