# Mutabakat v2 — copy-trade (HL dolumları ↔ motor kaydı)

Veri anı: **20.11 04:05 TSİ** (`durum/ozet.json` yazılış). Son kayıt: 20.11 04:05 TSİ. Dönem: 16.11 11:30 UTC → veri anı. Kaynak: `origin/canli-durum` revizyonu **`2d3b17ab`** (kayıt, hesap, ozet; dal canlı ilerler, bu sabit commit analiz edildi) + Hyperliquid public info (dolumlar; anlık pozisyonlar ve allMids çalıştırma anında). Betik: `araclar/mutabakat_v2.py`. Adresler kısa biçimde (`0x1234ab…`).

**Birim:** pozisyon = bir (trader, coin) döngüsü. Kapanış = `kapat` veya azaltmayla kalan miktar ≤ 1e-4 × açılan büyüklük (v1 bu eşiği 1 $ olarak kullanmıştı), ya da tasfiye. Tutar $ (kopya ölçeği, sanal kasa 10.000 $).

## Özet

| kalem | değer |
|---|---|
| Trader açılış/artış olayı (HL, 11 trader, 60 sn birleştirme) | 456 |
| Kopyalandı | 75 |
| Kaçan (toplam) | 2 (hata: 0, kayıt yok: 2) |
| Takip öncesi (kadro dışı, kaçan sayılmaz) | 11 |
| Bilerek atlandı (toplam) | 368 |
| Bizim kapanmış pozisyon | 20 kapanış + 1 tasfiye = 21 |
| Bizim açık pozisyon (log) / motor `hesap.poz` | 32 / 31 |
| Açık pozisyon, trader'da artık açık değil | 0 |
| Açık pozisyon, trader'da ters yönde | 0 |
| Eşleşmeyen kapanış (trader'da karşılık yok) | 2 |
| Boyut sapması > 2x (ya da < 0,5x) | 31 |
| Kasa (10.000 + realize − ücret + fonlama, hesap.json) | 9.937,75 $ (motor kasa 10.000,00 $ — realize toplamı kendi başına yeterli; bkz. 2) |
| Telegram pozisyon mesajı (yeni düzen, ≥ 04:15 TSİ) | henüz yeni düzende işlem yok |

## 1) Kopya kapsamı (trader açılış/artış olayları)

Trader olayı (HL `userFillsByTime`, 11 trader, 60 sn birleştirme): 456. Eşleşme: bizim kaydın `trader_dolum_ms` değeri, olay aralığının ±2 sn içinde. Kadroya alınmadan önceki olaylar (11) sayıma girmez.

### 1-0) Bizim açılış/artış dolumlarının HL karşılığı (kaynağa göre)

Dolu açılış/artış kaydı: 126. HL'de aynı trader, coin ve ±2 sn içinde dolum var: 104. **Yok: 22**.

| kaynak (`kaynak`) | yok olan dolum | trader | coin | zaman (TSİ) |
|---|---|---|---|---|
| trades | ac | 0x76c2cd… | ALGO | 16.11 14:32 |
| trades | ac | 0x76c2cd… | WLFI | 16.11 14:32 |
| trades | ac | 0x76c2cd… | INJ | 16.11 14:32 |
| trades | ac | 0x76c2cd… | FIL | 16.11 14:32 |
| trades | ac | 0x76c2cd… | AVAX | 16.11 14:35 |
| trades | ac | 0x76c2cd… | TRX | 16.11 16:27 |
| trades | artir | 0x76c2cd… | INJ | 16.11 16:50 |
| trades | ac | 0x76c2cd… | CAKE | 16.11 16:52 |
| trades | artir | 0x76c2cd… | WLFI | 16.11 16:57 |
| trades | artir | 0x76c2cd… | CAKE | 16.11 21:20 |
| trades | artir | 0x76c2cd… | CAKE | 17.11 01:13 |
| trades | artir | 0x76c2cd… | CAKE | 17.11 03:37 |
| trades | ac | 0x76c2cd… | AERO | 18.11 17:10 |
| trades | artir | 0x76c2cd… | DOGE | 18.11 17:11 |
| trades | ac | 0x76c2cd… | NEAR | 18.11 17:25 |
| trades | ac | 0x76c2cd… | ETC | 18.11 17:25 |
| trades | ac | 0x76c2cd… | DOT | 18.11 17:35 |
| trades | ac | 0x76c2cd… | LIT | 18.11 18:42 |
| trades | artir | 0x76c2cd… | AERO | 19.11 17:55 |
| trades | artir | 0x76c2cd… | AERO | 19.11 18:35 |
| trades | ac | 0x76c2cd… | TAO | 19.11 23:10 |
| trades | artir | 0x76c2cd… | TAO | 20.11 00:21 |

Kayıtlardaki trader açılış/artış anahtarı (adres, coin, ms) 12374 adet; bunların HL fill'inde karşılığı olan: 926. HL'de karşılığı olmayan (log'a özgü): 11448 (0x76c2cd 8259, 0x6a8686 3189). Bunlar çoğunlukla `emir_yok` kayıtlarıdır; sayıma etkisi yok (sayım HL olaylarından yapılır), ama kaynağı doğrulanmadı. HL'de olup kayıtta hiç açılış anahtarı olmayan: 20 (kadro öncesi olaylar dahil).

### 1a) Bilerek atlandı (filtre adına göre)

| filtre (`neden`) | olay |
|---|---|
| hip3_atlandi | 207 |
| slot_tavani | 67 |
| ters_netlesme | 63 |
| bant_ici | 21 |
| min_emir_atlandi | 3 |
| spot_atlandi | 2 |
| duygu_ters | 2 |
| gec_acilis | 2 |
| trader_hesap_yok | 1 |
| hesap_kucuk | 0 (kayıtta yok) |
| **toplam** | **368** |

### 1b) Kaçan (hata ya da kayıt yok)

| sebep | olay |
|---|---|
| kayıt yok | 2 |
| **toplam** | **2** |

| trader | coin | yön | zaman (TSİ) | olay | sebep |
|---|---|---|---|---|---|
| 0xc3602c… | INJ | kısa | 18.11 15:29 | 8 dolum | kayıt yok |
| 0x2d29c0… | xyz:SPCX | kısa | 18.11 15:49 | 3 dolum | kayıt yok |

Yön uyumu (kopyalanan olaylar, bizim `yon` vs trader yönü): 75/75.

## 2) Açık pozisyonlarımız, trader'da bugün

Anlık konum: 20.11 04:12 TSİ (`clearinghouseState`, tüm HIP-3 dex'leri). Bizim açık: 32.

- Trader'da açık değil: **0**
- Trader'da açık ama ters yön: **0**
- Aynı yön: **32**

## 1c) Kapanışlar: trader kapanışı ile eşleşme

Eşleşen kapanış: 18 / 20. Eşleşmeyen: **2**.
Gecikme (bizim dolum − trader dolumu): medyan 0,6 sn, en büyük 2,4 sn, en küçük 0,4 sn (n=18).
Zaman farkı (kayıttaki trader zamanı − HL dolum zamanı): medyan -0,4 sn, en büyük mutlak 1,0 sn.

| # | trader | coin | yön | kapanış tipi | bizim kapanış (TSİ) | trader dolumu (TSİ) | gecikme sn | eşleşme |
|---|---|---|---|---|---|---|---|---|
| 1 | 0x6a8686… | HYPE | uzun | kapat | 16.11 17:25 | 16.11 17:25 | 0,4 | tamam |
| 2 | 0xc30c7e… | ETH | kısa | sifir | 16.11 18:52 | 16.11 18:52 | 1,9 | tamam |
| 3 | 0xdebd49… | SOL | kısa | kapat | 17.11 06:10 | 17.11 06:10 | 0,6 | tamam |
| 4 | 0x6a8686… | HYPE | kısa | kapat | 17.11 08:22 | 17.11 08:22 | 0,6 | tamam |
| 5 | 0xdebd49… | BTC | uzun | kapat | 17.11 14:05 | 17.11 14:05 | 0,5 | tamam |
| 6 | 0xc30c7e… | ETH | kısa | kapat | 17.11 19:05 | 17.11 19:05 | 0,5 | tamam |
| 7 | 0xc30c7e… | ZEC | kısa | kapat | 17.11 19:05 | 17.11 19:05 | 0,5 | tamam |
| 8 | 0xdebd49… | BTC | uzun | kapat | 17.11 21:55 | 17.11 21:55 | 0,7 | tamam |
| 9 | 0xdebd49… | SOL | uzun | kapat | 18.11 02:10 | 18.11 02:10 | 0,8 | tamam |
| 10 | 0x76c2cd… | CAKE | uzun | sifir | 18.11 03:38 | — | — | yok |
| 11 | 0xdebd49… | BTC | uzun | kapat | 18.11 18:05 | 18.11 18:05 | 0,8 | tamam |
| 12 | 0x6d2667… | HYPE | kısa | kapat | 18.11 19:10 | 18.11 19:10 | 1,1 | tamam |
| 13 | 0xdebd49… | SOL | uzun | kapat | 18.11 19:25 | 18.11 19:25 | 0,5 | tamam |
| 14 | 0x2d29c0… | VVV | kısa | tasfiye | 19.11 07:32 | — | — | bizde emir yok; trader tarafı yok |
| 15 | 0xdebd49… | SOL | kısa | kapat | 19.11 08:50 | 19.11 08:50 | 0,5 | tamam |
| 16 | 0x2d29c0… | MEGA | kısa | sifir | 19.11 13:31 | 19.11 13:31 | 2,4 | tamam |
| 17 | 0x76c2cd… | LIT | kısa | sifir | 19.11 18:34 | — | — | yok |
| 18 | 0xdebd49… | BTC | uzun | kapat | 19.11 20:10 | 19.11 20:10 | 0,7 | tamam |
| 19 | 0x2d29c0… | PURR | kısa | kapat | 19.11 21:06 | 19.11 21:06 | 0,7 | tamam |
| 20 | 0x2d29c0… | BTC | uzun | kapat | 19.11 21:49 | 19.11 21:49 | 0,6 | tamam |
| 21 | 0xdebd49… | ETH | uzun | kapat | 20.11 01:30 | 20.11 01:30 | 0,6 | tamam |

## 1d) Boyut oranı

Karşılaştırılan dolum: 126 (açma/artırma: trader pozisyon değeri / hesap değeri vs bizim pozisyon / slot; azaltma/kapatma: kapatılan oran). Sapma = bizim oran / trader oranı; 2x üstü ya da 0,5x altı listelenir.

Sapma sayısı: **31** (8 açma/artırma, 23 azaltma/kapatma).

| tür | trader | coin | zaman (TSİ) | trader oranı | bizim oran | sapma (biz/trader) |
|---|---|---|---|---|---|---|
| artırma | 0xdebd49… | SOL | 16.11 18:45 | 1.316 | 0.6092 | 0.463x |
| azaltma | 0xc30c7e… | ETH | 16.11 18:52 | 0.4237 | 1 | 2.36x |
| azaltma | 0x6a8686… | HYPE | 17.11 01:23 | 0.07075 | 0.1863 | 2.63x |
| azaltma | 0xdebd49… | SOL | 17.11 03:30 | 0.3333 | 0.1222 | 0.367x |
| azaltma | 0xc30c7e… | ZEC | 17.11 19:05 | 0.02721 | 0.4153 | 15.3x |
| azaltma | 0xdebd49… | BTC | 17.11 21:55 | 0.5942 | 0.2478 | 0.417x |
| azaltma | 0x76c2cd… | CAKE | 17.11 23:17 | 0.0003286 | 0.175 | 533x |
| açma | 0x76c2cd… | HBAR | 17.11 23:37 | 0.07134 | 0.01607 | 0.225x |
| azaltma | 0x76c2cd… | CAKE | 18.11 00:11 | 0.000401 | 0.2112 | 527x |
| azaltma | 0x76c2cd… | CAKE | 18.11 01:09 | 0.001818 | 0.2674 | 147x |
| azaltma | 0x76c2cd… | CAKE | 18.11 02:06 | 0.0007706 | 0.3612 | 469x |
| azaltma | 0x76c2cd… | CAKE | 18.11 03:15 | 0.00926 | 0.566 | 61.1x |
| azaltma | 0x76c2cd… | CAKE | 18.11 03:38 | 0.01232 | 1 | 81.2x |
| açma | 0xdebd49… | SOL | 18.11 03:45 | 0.1524 | 0.04995 | 0.328x |
| azaltma | 0x76c2cd… | INJ | 18.11 17:25 | 0.008446 | 0.2107 | 24.9x |
| açma | 0x76c2cd… | DOT | 18.11 17:35 | 0.02569 | 0.01273 | 0.496x |
| azaltma | 0xdebd49… | BTC | 18.11 18:05 | 0.03783 | 0.1045 | 2.76x |
| açma | 0x76c2cd… | LIT | 18.11 18:42 | 0.02806 | 0.01233 | 0.439x |
| azaltma | 0x6d2667… | HYPE | 18.11 19:10 | 0.01299 | 0.06683 | 5.14x |
| azaltma | 0x6d2667… | HYPE | 18.11 19:10 | 0.003065 | 0.04987 | 16.3x |
| azaltma | 0xc30c7e… | ZEC | 19.11 02:50 | 0.09421 | 0.9944 | 10.6x |
| azaltma | 0xc3602c… | VVV | 19.11 05:26 | 0.005826 | 0.2077 | 35.7x |
| azaltma | 0xdebd49… | SOL | 19.11 08:25 | 0.016 | 0.06117 | 3.82x |
| azaltma | 0x2d29c0… | MEGA | 19.11 13:31 | 0.06388 | 1 | 15.7x |
| artırma | 0x2d29c0… | BTC | 19.11 14:06 | 0.3243 | 0.1172 | 0.361x |
| azaltma | 0x76c2cd… | TRX | 19.11 17:33 | 0.0004746 | 0.05306 | 112x |
| azaltma | 0x76c2cd… | LIT | 19.11 18:34 | 0.01439 | 1 | 69.5x |
| azaltma | 0x76c2cd… | TRX | 19.11 19:18 | 0.0005401 | 0.04818 | 89.2x |
| azaltma | 0x76c2cd… | WLFI | 19.11 19:28 | 0.0003972 | 0.1054 | 265x |
| açma | 0xc30c7e… | ZEC | 19.11 21:08 | 0.07486 | 0.01947 | 0.26x |
| artırma | 0xc30c7e… | ZEC | 20.11 01:13 | 0.09312 | 0.03857 | 0.414x |

## 2) Kasa bağımsız kontrol

- Gerçekleşen K/Z, bizim pozisyonlardan (kapanış + kısmi azaltmaların `pnl_usd` toplamı + tasfiye): **-51,50 $**
- `hesap.json` realize toplamı: **-51,50 $**; fark: **-0,00 $**
- Trader bazında fark yok (> 0,005 $).
- Ücret: bizim 10,77 $ / hesap.json 10,77 $
- Fonlama (hesap.json): +0,02 $
- Kasa = 10.000 + realize − ücret + fonlama = **9.937,75 $**; motor `ozet.kasa_usd` = 10.000,00 $.
- Açık K/Z (motor, `ozet.acik` toplamı) +67,13 $; özsermaye (kasa + açık K/Z) = **10.004,89 $**; motor `ozsermaye_usd` = 10.004,89 $.

**Açık K/Z fiyat kaynağı:** `copytrade/canli/motor.py` `mids_al()` → HL `allMids` orta fiyatı (mark). `hesap.py` özsermaye ve `gerceklesmemis()` aynı `marks` sözlüğünü kullanır; `pano.py` açık satırları `ozet['acik']` içindeki `kz_usd = sz·(mark − giriş)` değerinden okur. Yani pano ile motor aynı fiyat kaynağını kullanır (allMids, mark). Kontrol: veri anındaki mark ile şimdiki allMids farkı medyan +0.283% (n=31; zaman farkından kaynaklanır).

### 2b) Kapalı pozisyonlar (gerçekleşen K/Z, kısmi azaltmalar dahil)

| # | trader | coin | yön | açılış | kapanış | tip | giriş | çıkış | gerçekleşen K/Z $ | ücret $ |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 0x6a8686… | HYPE | uzun | 16.11 15:36 | 16.11 17:25 | kapat | 65,5353 | 66,496 | +0,16 | 0,01 |
| 2 | 0xc30c7e… | ETH | kısa | 16.11 17:41 | 16.11 18:52 | sifir | 1.847,7 | 1.820,8 | +1,03 | 0,06 |
| 3 | 0xdebd49… | SOL | kısa | 16.11 18:15 | 17.11 06:10 | kapat | 70,3135 | 71,8984 | -12,42 | 0,50 |
| 4 | 0x6a8686… | HYPE | kısa | 17.11 01:04 | 17.11 08:22 | kapat | 70,3185 | 70,3681 | -0,25 | 0,32 |
| 5 | 0xdebd49… | BTC | uzun | 16.11 18:00 | 17.11 14:05 | kapat | 64.973,6 | 64.329 | -11,60 | 1,05 |
| 6 | 0xc30c7e… | ETH | kısa | 17.11 18:41 | 17.11 19:05 | kapat | 1.789,9 | 1.789,4 | +0,00 | 0,02 |
| 7 | 0xc30c7e… | ZEC | kısa | 16.11 21:36 | 17.11 19:05 | kapat | 929,657 | 937,078 | -0,58 | 0,07 |
| 8 | 0xdebd49… | BTC | uzun | 17.11 14:50 | 17.11 21:55 | kapat | 64.910,8 | 63.700 | -14,91 | 0,71 |
| 9 | 0xdebd49… | SOL | uzun | 17.11 06:40 | 18.11 02:10 | kapat | 72,5632 | 73,0896 | +4,04 | 0,50 |
| 10 | 0x76c2cd… | CAKE | uzun | 16.11 16:52 | 18.11 03:38 | sifir | 1,60775 | 1,64115 | +2,94 | 0,13 |
| 11 | 0xdebd49… | BTC | uzun | 18.11 02:25 | 18.11 18:05 | kapat | 64.895 | 63.625 | -8,70 | 0,40 |
| 12 | 0x6d2667… | HYPE | kısa | 17.11 02:18 | 18.11 19:10 | kapat | 70,453 | 65,8852 | +66,58 | 0,89 |
| 13 | 0xdebd49… | SOL | uzun | 18.11 03:45 | 18.11 19:25 | kapat | 75,092 | 72,829 | -1,37 | 0,04 |
| 14 | 0x2d29c0… | VVV | kısa | 16.11 20:40 | 19.11 07:32 | tasfiye | 19,8528 | 22,6889 | -14,97 | 0,05 |
| 15 | 0xdebd49… | SOL | kısa | 18.11 19:40 | 19.11 08:50 | kapat | 72,9569 | 74,5768 | -19,28 | 0,79 |
| 16 | 0x2d29c0… | MEGA | kısa | 19.11 05:50 | 19.11 13:31 | sifir | 0,057069 | 0,057286 | -0,04 | 0,01 |
| 17 | 0x76c2cd… | LIT | kısa | 18.11 18:42 | 19.11 18:34 | sifir | 2,7416 | 2,8996 | -0,65 | 0,01 |
| 18 | 0xdebd49… | BTC | uzun | 19.11 10:30 | 19.11 20:10 | kapat | 63.553 | 62.527 | -2,58 | 0,14 |
| 19 | 0x2d29c0… | PURR | kısa | 17.11 01:58 | 19.11 21:06 | kapat | 0,0944077 | 0,0790043 | +10,76 | 0,05 |
| 20 | 0x2d29c0… | BTC | uzun | 19.11 14:06 | 19.11 21:49 | kapat | 63.721 | 62.946 | -1,30 | 0,10 |
| 21 | 0xdebd49… | ETH | uzun | 18.11 02:35 | 20.11 01:30 | kapat | 1.806,45 | 1.759,59 | -49,04 | 1,68 |
| | | | | | | | | **toplam** | **-52,18** | |

Kapanmış pozisyon: 20 (kapat 16, sıfırlanan 4) + tasfiye 1 = 21.

### 2c) Açık pozisyonlar: log ↔ motor miktar

Eşleşen: 31 / 32. Farklı: 1.
- 0xc30c7e… ZEC: log -0.000117766, motor 0, fark -0.000118 (kapanis_duzeltme alt kümesi (3 kayıt) ile açıklanıyor)

## 2d) v1'e göre düzeltmeler

- Kapanmış pozisyon: v1 25 (16 kapat + 9 'sıfır', eşik 1 $) → v2 20 (16 kapat + 4 'sıfır', eşik 1e-4 × açılan). Fark: v1'in 5 'sıfır' kapanışı ZEC (0x c30c7e) ve HYPE kalıntı düzeltmeleri (miktar ~1e-5 – 5e-4 coin) idi; bunlar gerçek kapanış değil.
- Tasfiye: 1 (VVV, 19.11 07:32 TSİ). Bu motorun sanal tasfiye kontrolüdür (`hesap.tasfiye_kontrol`, mark ≤ likit fiyat); trader tarafında karşılığı olması beklenmez.
- Toplam pozisyon: v1 58 → v2 53 (20 kapanış + 1 tasfiye + 32 açık).
- Açık pozisyon: kurala göre 32 (v1 ile aynı sayı); motor `hesap.poz` 31. Fark: ZEC kalıntısı (miktar ~1e-4 coin; motor `kapanis_duzeltme` ile sıfırladı, bizim toz eşiğimizin üstünde kaldığı için açık sayıldı).
- Kasa: bu revizyonda realize -51,50 $, kasa 9.937,75 $ (v1 anında 9.937,51 $ idi; veri ilerledi). Açık K/Z (`ozet.acik`): +67,13 $ (v1 anında +48,02 $).

## 3) 78 kapanış dolumunun dökümü

Kayıttaki azalt/kapat dolumu (dolu/kısmi): **78**.

| grup | dolum sayısı |
|---|---|
| kapanış dolumu (kapat) | 16 |
| kapanış dolumu (azaltma ile sıfır) | 4 |
| kısmi azaltma → kapanan pozisyon | 48 |
| kısmi azaltma → açık pozisyon | 10 |
| kısmi azaltma → tasfiye pozisyonu | 0 |
| **toplam** | **78** |

Kontrol: 78 = 78 → tamam. Kapanan pozisyon sayısı = kapat 16 + sıfırlanan 4 = 20, tasfiye 1.

## 4) Telegram

- Yeni düzen başlangıcı: 20.11 04:15 TSİ (kullanıcı bildirimi). Veri son kaydı 20.11 04:05 TSİ.
- `tg_mesaj` kaydı: 0. Yeni düzen sonrası pozisyon mesajı kaydı: 0.
- Yeni düzende (≥ 04:15 TSİ) açılan/kapanan pozisyon: 0.
- Sonuç: henüz yeni düzende işlem yok.

