# CT kural maliyeti (son 7 gün, 2026-11-21T10:36:03Z)

**Slot tavanı:** 7551 olay, 6 trader; karşı-olgu toplam -180.62 $ (kapanan -18.96, açık -161.66; hayali nosyonel 4931.92 $).

| Neden | Olay | Trader | Karşı-olgu kapanan $ | Açık anlık $ | Toplam $ | Hayali nosyonel $ |
|---|---:|---:|---:|---:|---:|---:|
| bant_ici | 10981 | 10 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| slot_tavani | 7551 | 6 | -18.96 (10) | -161.66 (17) | -180.62 | 4931.92 |
| hip3_atlandi | 4130 | 6 | -24.96 (15) | -5.64 (7) | -30.60 | 1085.16 |
| min_emir_atlandi | 3329 | 7 | -0.35 (3) | -0.26 (2) | -0.61 | 5.06 |
| ters_netlesme | 1645 | 9 | 98.85 (9) | -18.60 (11) | 80.24 | 3613.01 |
| duygu_ters | 921 | 6 | 1.94 (5) | 42.74 (16) | 44.68 | 1177.11 |
| ara_dolum_siniri | 510 | 6 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| rejim_ters | 105 | 5 | 0.83 (3) | 0.22 (4) | 1.05 | 1462.48 |
| spot_atlandi | 25 | 1 | 0.00 (0) | -0.02 (1) | -0.02 | 68.82 |
| elle_dur | 23 | 1 | 0.07 (2) | 0.00 (0) | 0.07 | 6.97 |
| gec_acilis | 8 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| haber_ters | 8 | 2 | -5.39 (1) | -12.27 (1) | -17.66 | 309.97 |
| trader_hesap_yok | 3 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| patlama_freni | 2 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |

Notlar:

- Yalnız bilgi: kural, eşik, slot tavanı ve işlem mantığını değiştirmez.
- Karşı-olgu adres|coin başına TEK açılır (ilk atlama); slot_tavani gibi sık nedenleri eksik örnekler, $ değerleri alt sınır/yaklaşıktır.
- Olay = emir_yok adedi (ML atlaması bir kez sayılır); karşı-olgu yalnız ac/artir (bant_ici hariç).
- Açık anlık $ = şu an açık hayali pozisyonların son değerlemesi; toplam = kapanan + açık; hayali nosyonel = ikisinin hayali_usd toplamı.
- Pencere son 7 gün; trader adresi yok, yalnız adet.
