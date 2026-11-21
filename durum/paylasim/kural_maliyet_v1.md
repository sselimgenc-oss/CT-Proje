# CT kural maliyeti (son 7 gün, 2026-11-21T07:06:22Z)

**Slot tavanı:** 7551 olay, 6 trader; karşı-olgu toplam -150.72 $ (kapanan -18.96, açık -131.75; hayali nosyonel 4931.92 $).

| Neden | Olay | Trader | Karşı-olgu kapanan $ | Açık anlık $ | Toplam $ | Hayali nosyonel $ |
|---|---:|---:|---:|---:|---:|---:|
| bant_ici | 10981 | 10 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| slot_tavani | 7551 | 6 | -18.96 (10) | -131.75 (17) | -150.72 | 4931.92 |
| hip3_atlandi | 4130 | 6 | -24.96 (15) | -5.36 (7) | -30.32 | 1085.16 |
| min_emir_atlandi | 3325 | 7 | -0.35 (3) | -0.21 (2) | -0.57 | 5.06 |
| ters_netlesme | 1635 | 9 | 80.70 (8) | 0.96 (11) | 81.66 | 3567.30 |
| duygu_ters | 884 | 6 | 1.92 (4) | 42.48 (15) | 44.40 | 868.25 |
| ara_dolum_siniri | 363 | 5 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| rejim_ters | 97 | 4 | 1.06 (2) | -0.01 (2) | 1.05 | 638.52 |
| spot_atlandi | 25 | 1 | 0.00 (0) | -0.06 (1) | -0.06 | 68.82 |
| gec_acilis | 8 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| haber_ters | 8 | 2 | 0.00 (0) | -17.77 (2) | -17.77 | 309.97 |
| trader_hesap_yok | 3 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| patlama_freni | 2 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |

Notlar:

- Yalnız bilgi: kural, eşik, slot tavanı ve işlem mantığını değiştirmez.
- Karşı-olgu adres|coin başına TEK açılır (ilk atlama); slot_tavani gibi sık nedenleri eksik örnekler, $ değerleri alt sınır/yaklaşıktır.
- Olay = emir_yok adedi (ML atlaması bir kez sayılır); karşı-olgu yalnız ac/artir (bant_ici hariç).
- Açık anlık $ = şu an açık hayali pozisyonların son değerlemesi; toplam = kapanan + açık; hayali nosyonel = ikisinin hayali_usd toplamı.
- Pencere son 7 gün; trader adresi yok, yalnız adet.
