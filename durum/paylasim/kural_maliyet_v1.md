# CT kural maliyeti (son 7 gün, 2026-11-20T20:02:56Z)

**Slot tavanı:** 7551 olay, 6 trader; karşı-olgu toplam -147.23 $ (kapanan -18.96, açık -128.27; hayali nosyonel 4931.92 $).

| Neden | Olay | Trader | Karşı-olgu kapanan $ | Açık anlık $ | Toplam $ | Hayali nosyonel $ |
|---|---:|---:|---:|---:|---:|---:|
| bant_ici | 10948 | 10 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| slot_tavani | 7551 | 6 | -18.96 (10) | -128.27 (17) | -147.23 | 4931.92 |
| hip3_atlandi | 4130 | 6 | -24.54 (13) | -5.99 (9) | -30.53 | 1085.16 |
| min_emir_atlandi | 3322 | 7 | -0.35 (3) | -0.23 (2) | -0.58 | 5.06 |
| ters_netlesme | 1612 | 9 | 80.70 (7) | 10.27 (9) | 90.98 | 3004.88 |
| duygu_ters | 787 | 6 | 1.11 (2) | 43.57 (13) | 44.67 | 665.14 |
| rejim_ters | 91 | 3 | -0.02 (1) | 3.40 (2) | 3.38 | 636.50 |
| ara_dolum_siniri | 57 | 2 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| spot_atlandi | 25 | 1 | 0.00 (0) | -1.33 (1) | -1.33 | 68.82 |
| gec_acilis | 8 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| haber_ters | 8 | 2 | 0.00 (0) | -23.29 (2) | -23.29 | 309.97 |
| trader_hesap_yok | 3 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| patlama_freni | 2 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |

Notlar:

- Yalnız bilgi: kural, eşik, slot tavanı ve işlem mantığını değiştirmez.
- Karşı-olgu adres|coin başına TEK açılır (ilk atlama); slot_tavani gibi sık nedenleri eksik örnekler, $ değerleri alt sınır/yaklaşıktır.
- Olay = emir_yok adedi (ML atlaması bir kez sayılır); karşı-olgu yalnız ac/artir (bant_ici hariç).
- Açık anlık $ = şu an açık hayali pozisyonların son değerlemesi; toplam = kapanan + açık; hayali nosyonel = ikisinin hayali_usd toplamı.
- Pencere son 7 gün; trader adresi yok, yalnız adet.
