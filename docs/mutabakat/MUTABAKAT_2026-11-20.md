# İşlem mutabakatı — sanal copy-trade motoru

Veri anı: **20.11 03:19 TSİ** (`durum/ozet.json` yazılış anı). Kayıt başlangıcı: 16.11 11:30 UTC (sanal dönem başı). Kaynak: `origin/canli-durum` dalı (`kayit/*.jsonl`, `durum/hesap.json`, `durum/ozet.json`, `pano/`). Betik: `araclar/mutabakat.py` (salt okuma).

**Birim:** bir pozisyon = bir (trader, coin) çiftinde ilk açılıştan tam kapanışa, tasfiyeye ya da veri anına kadar olan döngü. Azaltmalar aynı pozisyonun parçasıdır. Net K/Z = gerçekleşen K/Z − ücret + (açık pozisyonda) mark K/Z. Fonlama pozisyon bazında ayrılmaz; toplamlarda (B bölümü) yer alır.

**Telegram notu:** Telegram geçmişine erişim yok. Bu tabloda Telegram kontrolü yalnız motorun kendi `kayit` içindeki `telegram` gönderim kayıtlarıyla yapıldı. Pozisyon başına açıldı/kapandı mesajı kaydı, yeni kod ile başlar (20.11 03:06 TSİ birleşti, ~1 sa içinde yayına girdi). Bu tarihten önceki işlemler "eski düzen (beklenen)" sayılır, uyuşmazlık değildir.

## A) Pozisyon tablosu

Toplam 58 pozisyon (25 tam kapanış, 1 tasfiye, 32 açık).

| # | işlem no | trader | coin | yön | açılış (TSİ) | kapanış (TSİ) | giriş | çıkış | net K/Z $ | K-67 (gerçekte açılmazdı) | panoda | Telegram açıldı/kapandı |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | P001 | 0x76c2cd… | ALGO | uzun | 16.11 14:32 | açık | 0,079057 | — | -0,72 | — | var, aynı | eski düzen (beklenen) |
| 2 | P002 | 0x76c2cd… | WLFI | kısa | 16.11 14:32 | açık | 0,0457399 | — | -4,06 | — | var, aynı | eski düzen (beklenen) |
| 3 | P003 | 0x76c2cd… | INJ | uzun | 16.11 14:32 | açık | 6,7141 | — | +8,15 | — | var, aynı | eski düzen (beklenen) |
| 4 | P004 | 0x76c2cd… | FIL | kısa | 16.11 14:32 | açık | 0,59887 | — | +0,47 | — | var, aynı | eski düzen (beklenen) |
| 5 | P005 | 0x76c2cd… | AVAX | uzun | 16.11 14:35 | açık | 7,1329 | — | -0,21 | — | var, aynı | eski düzen (beklenen) |
| 6 | P006 | 0x76c2cd… | kSHIB | uzun | 16.11 14:38 | açık | 0,00387631 | — | -1,40 | — | var, aynı | eski düzen (beklenen) |
| 7 | P007 | 0x6a8686… | HYPE | uzun | 16.11 15:36 | 16.11 17:25 | 65,5353 | 66,496 | +0,15 | — | var, aynı (satır K/Z A-5) | eski düzen (beklenen) |
| 8 | P008 | 0x76c2cd… | ADA | uzun | 16.11 16:23 | açık | 0,15063 | — | +0,36 | — | var, aynı | eski düzen (beklenen) |
| 9 | P009 | 0x76c2cd… | BCH | uzun | 16.11 16:23 | açık | 204,37 | — | +1,01 | — | var, aynı | eski düzen (beklenen) |
| 10 | P010 | 0x76c2cd… | BTC | uzun | 16.11 16:24 | açık | 64.104 | — | -0,39 | — | var, aynı | eski düzen (beklenen) |
| 11 | P011 | 0x76c2cd… | DOGE | uzun | 16.11 16:25 | açık | 0,0590943 | — | -0,62 | — | var, aynı | eski düzen (beklenen) |
| 12 | P012 | 0x76c2cd… | TRX | uzun | 16.11 16:27 | açık | 0,303809 | — | +11,85 | — | var, aynı | eski düzen (beklenen) |
| 13 | P013 | 0x76c2cd… | WLD | kısa | 16.11 16:27 | açık | 0,26011 | — | +1,36 | — | var, aynı | eski düzen (beklenen) |
| 14 | P014 | 0x76c2cd… | CAKE | uzun | 16.11 16:52 | 18.11 03:38 | 1,60775 | 1,6518 | +2,81 | evet, maks 3x | var, aynı (satır K/Z A-5) | eski düzen (beklenen) |
| 15 | P015 | 0xc30c7e… | ETH | kısa | 16.11 17:41 | 16.11 18:52 | 1.847,7 | 1.820,8 | +0,97 | — | var, aynı (satır K/Z A-5) | eski düzen (beklenen) |
| 16 | P016 | 0xdebd49… | BTC | uzun | 16.11 18:00 | 17.11 14:05 | 64.973,6 | 64.156 | -12,65 | — | var, aynı (satır K/Z A-5) | eski düzen (beklenen) |
| 17 | P017 | 0xdebd49… | SOL | kısa | 16.11 18:15 | 17.11 06:10 | 70,3135 | 72,18 | -12,93 | — | var, aynı (satır K/Z A-5) | eski düzen (beklenen) |
| 18 | P018 | 0x2d29c0… | VVV | kısa | 16.11 20:40 | 19.11 07:32 (tasfiye) | 19,8528 | 22,6889 | -15,01 | evet, maks 3x | YOK (tasfiye, KAPANAN'da yok) | eski düzen (beklenen) |
| 19 | P019 | 0xc30c7e… | ZEC | kısa | 16.11 21:36 | 16.11 21:50 | 885,68 | 897,66 | -0,16 | — | var, aynı (satır K/Z A-5) | eski düzen (beklenen) |
| 20 | P020 | 0x6a8686… | HYPE | kısa | 17.11 01:04 | 17.11 01:23 | 70,5852 | 70,089 | +0,94 | — | var, aynı (satır K/Z A-5) | eski düzen (beklenen) |
| 21 | P021 | 0x2d29c0… | PURR | kısa | 17.11 01:58 | 19.11 21:06 | 0,0944077 | 0,0790043 | +10,70 | evet, maks 3x | var, aynı (satır K/Z A-5) | eski düzen (beklenen) |
| 22 | P022 | 0x6d2667… | HYPE | kısa | 17.11 02:18 | 18.11 19:10 | 70,453 | 65,8816 | +65,68 | — | var, aynı (satır K/Z A-5) | eski düzen (beklenen) |
| 23 | P023 | 0xdebd49… | SOL | uzun | 17.11 06:40 | 18.11 02:10 | 72,5632 | 75,406 | +3,54 | — | var, aynı (satır K/Z A-5) | eski düzen (beklenen) |
| 24 | P024 | 0x6a8686… | HYPE | kısa | 17.11 07:16 | 17.11 08:22 | 70,1133 | 70,583 | -1,50 | — | var, aynı (satır K/Z A-5) | eski düzen (beklenen) |
| 25 | P025 | 0xdebd49… | BTC | uzun | 17.11 14:50 | 17.11 21:55 | 64.910,8 | 63.700 | -15,62 | — | var, aynı (satır K/Z A-5) | eski düzen (beklenen) |
| 26 | P026 | 0xc30c7e… | ZEC | kısa | 17.11 18:31 | 17.11 19:05 | 937,919 | 944,47 | -0,49 | — | var, aynı (satır K/Z A-5) | eski düzen (beklenen) |
| 27 | P027 | 0xc30c7e… | ETH | kısa | 17.11 18:41 | 17.11 19:05 | 1.789,9 | 1.789,4 | -0,01 | — | var, aynı (satır K/Z A-5) | eski düzen (beklenen) |
| 28 | P028 | 0x2d29c0… | ETH | uzun | 17.11 19:20 | açık | 1.784,91 | — | -16,73 | — | var, aynı | eski düzen (beklenen) |
| 29 | P029 | 0x76c2cd… | HBAR | kısa | 17.11 23:37 | açık | 0,056943 | — | +0,79 | — | var, aynı | eski düzen (beklenen) |
| 30 | P030 | 0xc30c7e… | ZEC | kısa | 18.11 00:14 | 18.11 00:20 | 920,68 | 926,27 | -0,08 | — | var, aynı (satır K/Z A-5) | eski düzen (beklenen) |
| 31 | P031 | 0xdebd49… | BTC | uzun | 18.11 02:25 | 18.11 18:05 | 64.895 | 63.625 | -9,10 | — | var, aynı (satır K/Z A-5) | eski düzen (beklenen) |
| 32 | P032 | 0xdebd49… | ETH | uzun | 18.11 02:35 | 20.11 01:30 | 1.806,45 | 1.758,5 | -50,72 | — | var, aynı (satır K/Z A-5) | eski düzen (beklenen) |
| 33 | P033 | 0xdebd49… | SOL | uzun | 18.11 03:45 | 18.11 19:25 | 75,092 | 72,829 | -1,41 | — | var, aynı (satır K/Z A-5) | eski düzen (beklenen) |
| 34 | P034 | 0xc30c7e… | ZEC | kısa | 18.11 05:17 | 18.11 05:25 | 945,73 | 953,15 | -0,11 | — | var, aynı (satır K/Z A-5) | eski düzen (beklenen) |
| 35 | P035 | 0xc30c7e… | XRP | kısa | 18.11 05:17 | açık | 0,970928 | — | +9,32 | — | var, aynı | eski düzen (beklenen) |
| 36 | P036 | 0xc3602c… | VVV | kısa | 18.11 08:33 | açık | 21,254 | — | -4,20 | evet, maks 3x | var, aynı | eski düzen (beklenen) |
| 37 | P037 | 0xc3602c… | XRP | kısa | 18.11 08:34 | açık | 0,987541 | — | +9,93 | — | var, aynı | eski düzen (beklenen) |
| 38 | P038 | 0xc3602c… | HYPE | kısa | 18.11 08:35 | açık | 68,955 | — | +7,07 | — | var, aynı | eski düzen (beklenen) |
| 39 | P039 | 0xc3602c… | AAVE | kısa | 18.11 08:36 | açık | 111,82 | — | +11,56 | — | var, aynı | eski düzen (beklenen) |
| 40 | P040 | 0xc3602c… | LINK | kısa | 18.11 08:37 | açık | 9,25388 | — | +3,36 | — | var, aynı | eski düzen (beklenen) |
| 41 | P041 | 0x76c2cd… | AERO | uzun | 18.11 17:10 | açık | 0,432232 | — | -4,32 | evet, maks 3x | var, aynı | eski düzen (beklenen) |
| 42 | P042 | 0x76c2cd… | NEAR | kısa | 18.11 17:25 | açık | 3,3326 | — | +0,38 | — | var, aynı | eski düzen (beklenen) |
| 43 | P043 | 0x76c2cd… | ETC | kısa | 18.11 17:25 | açık | 5,9977 | — | +0,33 | — | var, aynı | eski düzen (beklenen) |
| 44 | P044 | 0x76c2cd… | DOT | kısa | 18.11 17:35 | açık | 0,72254 | — | +0,10 | — | var, aynı | eski düzen (beklenen) |
| 45 | P045 | 0x76c2cd… | LIT | kısa | 18.11 18:42 | 19.11 18:34 | 2,7416 | 2,8996 | -0,66 | — | var, aynı (satır K/Z A-5) | eski düzen (beklenen) |
| 46 | P046 | 0xdebd49… | SOL | kısa | 18.11 19:40 | 19.11 08:50 | 72,9569 | 74,515 | -20,07 | — | var, aynı (satır K/Z A-5) | eski düzen (beklenen) |
| 47 | P047 | 0xc30c7e… | ZEC | kısa | 18.11 22:58 | 19.11 02:50 | 913,28 | 921,01 | -0,10 | — | var, aynı (satır K/Z A-5) | eski düzen (beklenen) |
| 48 | P048 | 0x2d29c0… | MEGA | kısa | 19.11 05:50 | 19.11 13:31 | 0,057069 | 0,057286 | -0,05 | evet, maks 3x | var, aynı (satır K/Z A-5) | eski düzen (beklenen) |
| 49 | P049 | 0xc3602c… | SOL | kısa | 19.11 06:46 | açık | 73,919 | — | +2,96 | — | var, aynı | eski düzen (beklenen) |
| 50 | P050 | 0xdebd49… | BTC | uzun | 19.11 10:30 | 19.11 20:10 | 63.553 | 62.527 | -2,72 | — | var, aynı (satır K/Z A-5) | eski düzen (beklenen) |
| 51 | P051 | 0xf83e8b… | XRP | kısa | 19.11 13:09 | açık | 0,98471 | — | +0,23 | — | var, aynı | eski düzen (beklenen) |
| 52 | P052 | 0x2d29c0… | BTC | uzun | 19.11 14:06 | 19.11 21:49 | 63.721 | 62.946 | -1,39 | — | var, aynı (satır K/Z A-5) | eski düzen (beklenen) |
| 53 | P053 | 0x6d2667… | HYPE | kısa | 19.11 16:15 | açık | 68,7188 | — | +15,55 | — | var, aynı | eski düzen (beklenen) |
| 54 | P054 | 0x2d29c0… | PAXG | uzun | 19.11 19:41 | açık | 3.680,6 | — | -0,20 | — | var, aynı | eski düzen (beklenen) |
| 55 | P055 | 0xc30c7e… | ZEC | kısa | 19.11 21:08 | açık | 896,176 | — | -0,02 | — | var, aynı | eski düzen (beklenen) |
| 56 | P056 | 0x76c2cd… | TAO | kısa | 19.11 23:10 | açık | 193,315 | — | +0,08 | — | var, aynı | eski düzen (beklenen) |
| 57 | P057 | 0xdebd49… | SOL | kısa | 20.11 00:35 | açık | 72,6264 | — | -6,32 | — | var, aynı | eski düzen (beklenen) |
| 58 | P058 | 0xdebd49… | BNB | kısa | 20.11 01:20 | açık | 577,94 | — | -0,13 | — | var, aynı | eski düzen (beklenen) |

Açıklamalar: giriş/çıkış = dolum fiyatı (ağırlıklı ortalama, $/coin). Çıkış tasfiyelerde tasfiye fiyatıdır. "panoda" = pano açık pozisyon listesiyle (`ozet.acik`, pano HTML şeridi) aynı yön, miktar ve giriş fiyatı.

### A-2) Mutabakat uyuşmazlıkları (log ↔ motor poz)

| trader | coin | log net (coin) | motor poz (coin) | fark | neden (tahmin / doğrulama) |
|---|---|---|---|---|---|
| 0x2d29c0… | VVV | -5.27731 | 0 | -5.28 | tasfiye (VVV, emir kaydı yok; pnl hesapta var) — beklenen |
| 0x6a8686… | HYPE | -0.000492596 | 0 | -0.000493 | toz kalıntı (kapanış sonrası kesir; hesap sıfırlar) |
| 0xc30c7e… | ZEC | -0.0398472 | -0.039756 | -9.12e-05 | kapanis_duzeltme (kesir miktar düzeltmesi) |

Yetim olay (döngüye bağlanamayan emir/tasfiye): 0.

### A-3) Tasfiye ve kapanış düzeltmeleri

- Tasfiye: trader 0x2d29c0…, VVV, tasfiye fiyatı 22,6889, mark 22,6975, pnl -14,97 $. Emir kaydı: yok. hesap.json `realize` bu pnl'i içerir (trader realize -5,55 = emir pnl + tasfiye).
- kapanis_duzeltme: 0xc30c7e…, ZEC, sz -2.3036591008721713e-05, neden tam_kapanis.
- kapanis_duzeltme: 0x6a8686…, HYPE, sz -0.0004925962283219842, neden tam_kapanis.
- kapanis_duzeltme: 0xc30c7e…, ZEC, sz -5.501301069956756e-05, neden tam_kapanis.
- kapanis_duzeltme: 0xc30c7e…, ZEC, sz -1.3169967077409847e-05, neden tam_kapanis.

### A-5) Pano KAPANAN satırları ↔ log azalt/kapat emirleri (satır bazında)

Eşleşme anahtarı: trader, coin, zaman (ms). Pano satırı: 77. Log kapanış dolumu (reduce-only, dolu/kısmi, pnl kayıtlı): 77. Eşleşen: 77.
- Panoda var, logda yok: **0**
- Logda var, panoda yok: **0**
- Eşleşenlerde coin/yön/K/Z (2 ondalık) farkı: **0**
- Tasfiye (log, pano KAPANAN listesinde yok): **1** — VVV, −14,97 $.

### A-4) Açık pozisyon sayımı

- Motor (`durum/hesap.json` poz): **32**
- Log'dan yeniden kurulan açık pozisyon: **32**
- Pano HTML şeridi ("Açık poz."): **32**
- Pano OZET.md tablosu satırı: **32**
- Pano KAPANAN sekmesi: 16 pozisyon (77 satır). Log: 16 `kapat` + 9 azaltmayla sıfırlanan + 1 tasfiye = 26 kapanmış pozisyon. **UYUŞMAZLIK**: pano kapanış pozisyon sayısı log'dan 10 eksik (azaltmayla sıfırlananlar ve tasfiye pano pozisyon sayısında yok; pano düzeltmesi ayrı PR). Satır bazlı karşılaştırma: bölüm A-5.
- Pano açık satır karşılaştırması: aynı 32 / farklı 0

## B) Toplamlar

| kalem | değer |
|---|---|
| Başlangıç kasası | 10.000,00 $ |
| Gerçekleşen K/Z (brüt, `realize` toplamı) | -51,75 $ |
| Ücret (komisyon, toplam) | -10,75 $ |
| Fonlama (toplam) | +0,01 $ |
| **Kasa (gerçekleşen, ücret + fonlama dahil)** = 10.000 + K/Z − ücret + fonlama | **9.937,51 $** |
| Açık pozisyon mark K/Z (`ozet.acik` toplamı) | +48,02 $ |
| **Özsermaye (kasa + açık K/Z)** — hesap.json'dan hesaplanan | **9.985,53 $** |
| Özsermaye — motorun yazdığı (`ozet.json`) | 9.985,53 $ |
| Fark (hesap − motor) | +0,0000 $ |

Sağlık kontrolü: özsermaye 9.985,53 $ (beklenen ~9.990 $ civarı — uygun); gerçekleşen kasa 9.937,51 $ açık pozisyonların K/Z'si hariçtir.

### B-2) Açık pozisyon sayısı

Motor 32 = pano 32 = log 32: **eşit**.

### B-3) Telegram

- Motorun Telegram kayıtlarında pozisyon başına açıldı/kapandı mesajı: **0** (tüm `telegram` kayıtları: 144; bunlar saatlik özet, uyarı, günlük özet ve trader bildirimleri).
- Yeni kod (03:06 TSİ sonrası) başlangıcından beri açılan/kapanan pozisyon: **0**; bunların mesaj kaydı yok. Dağıtım saati tam bilinmediği için bu sayı **uyuşmazlık olarak sayılmadı**: eksik/fazla/yanlış-yön = 0 (kanıtlanabilen), bekleyen = 0.
- Yanlış yön / fazla mesaj: kayıt yok, değerlendirilemedi.

### B-4) Kopya doğruluğu (trader açılışları)

- Trader açılış olayı (kapsam): 7695 · bizim açtığımız: 58 · red: 1 · atlanan (kayıt: emir_yok): 7636.
- Aynı yön: 58 / 58 (açtığımız işlemlerde, trader'ın dolum sonrası pozisyon işaretine göre). Atlanan açılışların yönü kayıtta yok; yön kontrolü yalnız açılan işlemler için yapıldı.
- Gecikme (trader dolumu → bizim dolum), n=58: medyan **0,48 sn**; en yavaş %10 eşiği (p90) **0,60 sn**; en yavaş %10 medyanı 0,67 sn.
- Fiyat farkı (kayma_trader, + = aleyhimize), n=58: medyan **+0,001%**; mutlak medyan +0,002%.

### B-5) K-67 (HL azami kaldıracı < 5 olan coinler)

Bu işlemler, HL azami kaldıracı 5'in altında olduğu için gerçekte açılmazdı (K-67). Sayı: **6** pozisyon (kapalı 4, açık 2).

| kalem | pozisyon | net K/Z $ |
|---|---|---|
| K-67 işlemleri (tümü) | 6 | -10,08 |
| — kapalı K-67 | 4 | -1,55 |
| Sanal K/Z — tümü | 58 | -14,48 |
| **Sanal K/Z — K-67 hariç** | 52 | **-4,40** |

### B-6) Tasfiye VVV (−14,97 $) — doğrulama ve neden

- Tasfiye kaydı: 1 adet. Emir kaydı olmayan tasfiye/kapanış: **1** (VVV). Pnl hesap realize'ında mevcut (bölüm A-3).
- Kayıttaki ortalama giriş 19,8528, tasfiye fiyatı 22,6889: girişten **+14,3%** (kısa pozisyon).
- Azami kaldıraç (HL) VVV = 3x. Koordinatör notu: 3x izole short, bakım marjı %16,7, tasfiye ≈ girişten +%14,3; %20 felaket stopu bu seviyeye ulaşamadan tasfiye oldu. Log ile tutarlılık: giriş-tasfiye farkı yukarıdaki değerdir; mekanizma (bakım marjı) kodla doğrulanmadı, düzeltme (dinamik stop) ayrı PR'da, onay bekliyor.

## C) Kopya işlemlerinin notları

- Pozisyon döngüsü: 25 tam kapanış (`kapat`), 1 tasfiye, 32 açık; motor poz ile log net pozisyonu arasındaki fark yalnız A-2'de listelenenlerdir.
- Ücret: log emir ücret toplamı 10,7496 $, hesap.json ücret toplamı 10,7496 $.

_Bu rapor salt okuma ile üretildi; motor kodu değiştirilmedi._
