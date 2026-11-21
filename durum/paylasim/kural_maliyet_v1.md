# CT kural maliyeti (son 7 gün, 2026-11-21T12:30:50Z)

**Slot tavanı:** 7551 olay, 6 trader; karşı-olgu toplam -164.04 $ (kapanan -18.96, açık -145.08; hayali nosyonel 4931.92 $).

| Neden | Olay | Trader | Karşı-olgu kapanan $ | Açık anlık $ | Toplam $ | Hayali nosyonel $ |
|---|---:|---:|---:|---:|---:|---:|
| bant_ici | 10981 | 10 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| slot_tavani | 7551 | 6 | -18.96 (10) | -145.08 (17) | -164.04 | 4931.92 |
| hip3_atlandi | 4130 | 6 | -24.96 (15) | -5.59 (7) | -30.55 | 1085.16 |
| min_emir_atlandi | 3329 | 7 | -0.35 (3) | -0.24 (2) | -0.60 | 5.06 |
| ters_netlesme | 1658 | 9 | 98.85 (9) | -17.59 (12) | 81.26 | 3649.57 |
| duygu_ters | 1078 | 8 | 1.94 (5) | 15.73 (22) | 17.67 | 2096.13 |
| ara_dolum_siniri | 653 | 7 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| rejim_ters | 105 | 5 | 0.83 (3) | 3.11 (4) | 3.94 | 1462.48 |
| elle_dur | 53 | 2 | 0.07 (2) | -0.00 (1) | 0.07 | 7.74 |
| spot_atlandi | 25 | 1 | 0.00 (0) | 0.86 (1) | 0.86 | 68.82 |
| gec_acilis | 8 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| haber_ters | 8 | 2 | -5.39 (1) | -9.79 (1) | -15.19 | 309.97 |
| trader_hesap_yok | 3 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| patlama_freni | 2 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |

Notlar:

- Yalnız bilgi: kural, eşik, slot tavanı ve işlem mantığını değiştirmez.
- Karşı-olgu adres|coin başına TEK açılır (ilk atlama); slot_tavani gibi sık nedenleri eksik örnekler, $ değerleri alt sınır/yaklaşıktır.
- Olay = emir_yok adedi (ML atlaması bir kez sayılır); karşı-olgu yalnız ac/artir (bant_ici hariç).
- Açık anlık $ = şu an açık hayali pozisyonların son değerlemesi; toplam = kapanan + açık; hayali nosyonel = ikisinin hayali_usd toplamı.
- Pencere son 7 gün; trader adresi yok, yalnız adet.
