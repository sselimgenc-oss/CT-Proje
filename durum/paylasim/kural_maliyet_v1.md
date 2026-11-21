# CT kural maliyeti (son 7 gün, 2026-11-21T08:33:01Z)

**Slot tavanı:** 7551 olay, 6 trader; karşı-olgu toplam -169.06 $ (kapanan -18.96, açık -150.10; hayali nosyonel 4931.92 $).

| Neden | Olay | Trader | Karşı-olgu kapanan $ | Açık anlık $ | Toplam $ | Hayali nosyonel $ |
|---|---:|---:|---:|---:|---:|---:|
| bant_ici | 10981 | 10 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| slot_tavani | 7551 | 6 | -18.96 (10) | -150.10 (17) | -169.06 | 4931.92 |
| hip3_atlandi | 4130 | 6 | -24.96 (15) | -5.64 (7) | -30.59 | 1085.16 |
| min_emir_atlandi | 3329 | 7 | -0.35 (3) | -0.23 (2) | -0.59 | 5.06 |
| ters_netlesme | 1635 | 9 | 98.85 (9) | -19.69 (10) | 79.15 | 3567.30 |
| duygu_ters | 893 | 6 | 1.94 (5) | 53.58 (14) | 55.52 | 868.25 |
| ara_dolum_siniri | 427 | 5 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| rejim_ters | 101 | 4 | 1.06 (2) | -1.37 (3) | -0.31 | 909.40 |
| spot_atlandi | 25 | 1 | 0.00 (0) | -0.66 (1) | -0.66 | 68.82 |
| elle_dur | 23 | 1 | 0.00 (0) | -0.00 (2) | -0.00 | 6.96 |
| gec_acilis | 8 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| haber_ters | 8 | 2 | 0.00 (0) | -20.34 (2) | -20.34 | 309.97 |
| trader_hesap_yok | 3 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| patlama_freni | 2 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |

Notlar:

- Yalnız bilgi: kural, eşik, slot tavanı ve işlem mantığını değiştirmez.
- Karşı-olgu adres|coin başına TEK açılır (ilk atlama); slot_tavani gibi sık nedenleri eksik örnekler, $ değerleri alt sınır/yaklaşıktır.
- Olay = emir_yok adedi (ML atlaması bir kez sayılır); karşı-olgu yalnız ac/artir (bant_ici hariç).
- Açık anlık $ = şu an açık hayali pozisyonların son değerlemesi; toplam = kapanan + açık; hayali nosyonel = ikisinin hayali_usd toplamı.
- Pencere son 7 gün; trader adresi yok, yalnız adet.
