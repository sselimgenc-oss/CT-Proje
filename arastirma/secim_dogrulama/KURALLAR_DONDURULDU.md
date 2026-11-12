# KURALLAR DONDURULDU — walk-forward seçim doğrulaması

Yazılma: 2026-11-11, **hiçbir ölçüm yapılmadan önce** (yalnız API biçimi denetimi ve boyut sayımı yapıldı). Bu dosya sonradan değiştirilmez.
Kaynak: `/home/user/secim_dogrulama_prompt.md` (§1–§3) + kullanıcı değişiklikleri (kollar B/C/D, K-65 veri düzeltmesi). Kod: `/home/user/wf/olcum.py` (`K` sözlüğü bu eşiklerin aynısıdır).

## Tarihler
- Çapa = boru hattının ilk başlatıldığı saat (UTC, `ayar.json`). T12 = çapanın UTC günü − 28 gün; T1…T12 haftalık (T1 = T12 − 77 gün).
- Her T için ölçü penceresi [T, T + 28 gün). **T12 kilitli**: birinci turda ileri ölçüm yapılmaz.
- "Bugün" = çapa: yalnız aday havuzu (ileri ölçüm yok).

## Veri tanımları (K-65 ile aynı)
- Pnl: yalnız PERP seri (`perpAllTime` + `perpMonth` + `perpWeek` birleşik; `secim_d.pnl_serisi`). Hesap değeri: toplam seri (`allTime`+`month`+`week` `accountValueHistory`, `secim_d.seri_birlestir`). T'deki değer = T'de ya da öncesindeki son nokta.
- Dolumlar: yalnız perp (`olcut.perp_fills`; spot atılır). HIP-3 dolumları kopya oynatmasında atlanır (`radar_hip3_kopya: false`).
- Kopya oynatma: `kopya_v5.hesapla`, kasa 1.000 $ → slot 200 $ (5 slot), hedef bazlı boyut (trader pozisyonu / trader hesabı × slot; payda = T anındaki/öncesindeki hesap değeri serisi), minimum emir 11 $ (`radar_min_emir_usd`; 5,5 $ altı açılmaz, arası 11 $'a yuvarlanır), pozisyon tavanı 1,5 × slot, taker %0,045 + kayma %0,05, funding (`gecmis_funding.FundingOnbellegi`). Gecikmesiz (trader dolum fiyatı) + tam maliyet; işaret/tasfiye saatlik mumdan (`kalicilik_testi` yaklaşımı). Pencere başında kopya boştur.
- Getiri raporu: net getiri ve en büyük düşüş slot (200 $) oranı olarak.

## §1 Dondurulmuş seçim kuralları (her T'de YALNIZ T'ye kadarki veriyle)
1. Hesap değeri (T'de) ≥ 50.000 $.
2. Son 12 haftanın (T'ye kadar) ≥ 8'i pozitif perp pnl (12 haftanın hepsi ölçülebilir olmalı); 90 g kümülatif perp pnl düşüşü / hesap ≤ %20.
3. Devir: son 28 g perp hacmi / hesap / 4 ≤ 25x (haftalık). Ortanca pozisyon tutma süresi (son 28 g kapanan işlemler) ≥ 30 dk.
4. En yüksek gerçek kaldıraç (son 28 g, `olcut.effective_leverage_detail`, payda T'deki hesap) ≤ 5x. Aktif coin (son 28 g) ≤ 8. Son 28 g nosyonelin %100'ü likit coinlerde (pencerenin saatlik mumlarından günlük ortalama hacim ≥ 1M $; `radar_likit_coin_hacim_usd`).
5. Kopya oynatmasında kapanan işlem: son 56 g ≥ 6 ve son 28 g ≥ 3 (iki ayrı oynatma, her biri pencere başında boş).
6. Son 56 g oynatmasında 11 $ minimum emir yüzünden atlanan (ideal) emir hacmi payı ≤ %20.
7. Son 28 g kopya getirisi (maliyet + funding dahil) > 0 ve koruma = kopya / ayna (aynı oynatma maliyetsiz) ≥ 0,5 (ayna ≤ 0 → geçmez).
8. Sıralama: haftalık pnl/hesap t-istatistiği (`secim_d.portfolio_olculeri`). "İlk 5" bu sıradan.

**Kontrol grubu:** T'de hesap ≥ 50k ve T'den önceki 30 g perp pnl > 0. Uygulamada: herhangi bir T'de bu tanıma uyan hesaplardan sabit tohumla (20261111) **700** rastgele adres; her T'de bunların o T'de tanıma uyanları (havuz). (D kolu için ≥ 10k tanımıyla ayrı 300 adreslik örneklem.)

## Kollar (hepsi her T'de; her biri o T'deki kontrol havuzundan eşit büyüklükte 1.000 rastgele çekilişe karşı)
- **A:** §1 kuralları 1–7 (yazıldığı gibi). Seçim = geçenlerin TÜMÜ; ilk 5 = t sırası.
- **B:** A + iki veto: (a) T'ye kadar ömür boyu perp pnl ≤ 0 → çıkar; (b) son 28 g perp dolumlarında `olcut.martingale_ratio` (`martingale_min_adverse` = 0,02): ekleme sayısı ≥ `martingale_min_additions` (5) VE zarara ekleme payı ≥ 0,40 → çıkar.
- **C:** kontrol tanımına uyan (≥ 50k, 30 g pnl > 0) ve 3–7 kapılarını + iki vetoyu geçenlerin TÜMÜ; kural 2 ve sıralama YOK. Yalnız kontrol örneklemi üzerinde ölçülür (seçim havuzun alt kümesidir: "geçen vs kontrol").
- **D:** A, ama hesap ≥ 10.000 $ (bugünkü canlı eşik). Birincil karşılaştırma ≥ 10k kontrol havuzu (≥ 10k ve 30 g pnl > 0); ikincil olarak 50k havuzu da raporlanır.

## Veri yeterliliği / çıkarma
- Dolumları [T − 56 g, T + 28 g) aralığını kapsamayan (adres başına en çok 10.000 dolum, en yeni kısım tutulur; okunamayan) hesaplar o T'de **iki gruptan da** çıkarılır, sayısı her T için raporlanır. Boşluk doldurma / tahmin yok.

## §3 Geçme şartı (üçü birden; her kol için ayrı)
1. **Birleşik:** S = seçilen grubun T başına ortanca net getirilerinin (seçileni olan T'ler) ortalaması; boş dağılım = her çekiliş i için aynı T'lerde çekiliş ortancalarının ortalaması. S, 1.000 birleşik çekilişin **≥ %90'ından** büyük olmalı.
2. 12 tarihin **en az 9'unda** seçilen ortanca > kontrol havuzu ortancası (seçileni olmayan T "iyi değil" sayılır). Kilitli T12 en son açılır ve sayılır. Birinci turda (T1–T11) en az 8/11 gerekir (9/12 hâlâ mümkün olsun).
3. Tüm (T, seçilen) çiftlerinin maliyet sonrası ortanca net getirisi **> 0**.

**Tur kuralı:** Birinci tur = T1–T11 ile üç şart. Geçen kol için T12 açılır, son hüküm T1–T12 ile verilir. Birinci turda geçmeyen kolda T12 kilitli kalır; **tek** revizyon hakkı vardır (yalnız birinci tur başarısızsa, gerekçesi yazılarak, sınırlı kural değişikliği; bu boru hattı revizyonu kendisi YAPMAZ — kullanıcı/analist kararı). İkinci tur da geçmezse "seçim değer katmıyor"; kurallar daha fazla kurcalanmaz.
