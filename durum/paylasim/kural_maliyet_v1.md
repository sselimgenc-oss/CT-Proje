# CT kural maliyeti (son 7 gün, 2026-11-21T11:36:37Z)

**Slot tavanı:** 7551 olay, 6 trader; karşı-olgu toplam -161.15 $ (kapanan -18.96, açık -142.19; hayali nosyonel 4931.92 $).

| Neden | Olay | Trader | Karşı-olgu kapanan $ | Açık anlık $ | Toplam $ | Hayali nosyonel $ |
|---|---:|---:|---:|---:|---:|---:|
| bant_ici | 10981 | 10 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| slot_tavani | 7551 | 6 | -18.96 (10) | -142.19 (17) | -161.15 | 4931.92 |
| hip3_atlandi | 4130 | 6 | -24.96 (15) | -5.33 (7) | -30.29 | 1085.16 |
| min_emir_atlandi | 3329 | 7 | -0.35 (3) | -0.23 (2) | -0.59 | 5.06 |
| ters_netlesme | 1647 | 9 | 98.85 (9) | -17.18 (11) | 81.67 | 3613.01 |
| duygu_ters | 1000 | 7 | 1.94 (5) | 21.91 (18) | 23.85 | 1898.92 |
| ara_dolum_siniri | 551 | 6 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| rejim_ters | 105 | 5 | 0.83 (3) | 3.19 (4) | 4.02 | 1462.48 |
| spot_atlandi | 25 | 1 | 0.00 (0) | 0.77 (1) | 0.77 | 68.82 |
| elle_dur | 23 | 1 | 0.07 (2) | 0.00 (0) | 0.07 | 6.97 |
| gec_acilis | 8 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| haber_ters | 8 | 2 | -5.39 (1) | -10.09 (1) | -15.48 | 309.97 |
| trader_hesap_yok | 3 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| patlama_freni | 2 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |

Notlar:

- Yalnız bilgi: kural, eşik, slot tavanı ve işlem mantığını değiştirmez.
- Karşı-olgu adres|coin başına TEK açılır (ilk atlama); slot_tavani gibi sık nedenleri eksik örnekler, $ değerleri alt sınır/yaklaşıktır.
- Olay = emir_yok adedi (ML atlaması bir kez sayılır); karşı-olgu yalnız ac/artir (bant_ici hariç).
- Açık anlık $ = şu an açık hayali pozisyonların son değerlemesi; toplam = kapanan + açık; hayali nosyonel = ikisinin hayali_usd toplamı.
- Pencere son 7 gün; trader adresi yok, yalnız adet.
