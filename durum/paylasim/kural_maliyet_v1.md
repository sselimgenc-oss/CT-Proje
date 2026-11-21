# CT kural maliyeti (son 7 gün, 2026-11-21T04:05:42Z)

**Slot tavanı:** 7551 olay, 6 trader; karşı-olgu toplam -168.24 $ (kapanan -18.96, açık -149.27; hayali nosyonel 4931.92 $).

| Neden | Olay | Trader | Karşı-olgu kapanan $ | Açık anlık $ | Toplam $ | Hayali nosyonel $ |
|---|---:|---:|---:|---:|---:|---:|
| bant_ici | 10950 | 10 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| slot_tavani | 7551 | 6 | -18.96 (10) | -149.27 (17) | -168.24 | 4931.92 |
| hip3_atlandi | 4130 | 6 | -24.96 (15) | -5.86 (7) | -30.81 | 1085.16 |
| min_emir_atlandi | 3324 | 7 | -0.35 (3) | -0.24 (2) | -0.59 | 5.06 |
| ters_netlesme | 1627 | 9 | 80.70 (8) | 23.40 (10) | 104.11 | 3373.15 |
| duygu_ters | 837 | 6 | 1.16 (3) | 75.32 (13) | 76.48 | 665.99 |
| ara_dolum_siniri | 143 | 3 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| rejim_ters | 97 | 4 | 1.06 (2) | -0.07 (2) | 0.99 | 638.52 |
| spot_atlandi | 25 | 1 | 0.00 (0) | -3.27 (1) | -3.27 | 68.82 |
| gec_acilis | 8 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| haber_ters | 8 | 2 | 0.00 (0) | -31.43 (2) | -31.43 | 309.97 |
| trader_hesap_yok | 3 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| patlama_freni | 2 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |

Notlar:

- Yalnız bilgi: kural, eşik, slot tavanı ve işlem mantığını değiştirmez.
- Karşı-olgu adres|coin başına TEK açılır (ilk atlama); slot_tavani gibi sık nedenleri eksik örnekler, $ değerleri alt sınır/yaklaşıktır.
- Olay = emir_yok adedi (ML atlaması bir kez sayılır); karşı-olgu yalnız ac/artir (bant_ici hariç).
- Açık anlık $ = şu an açık hayali pozisyonların son değerlemesi; toplam = kapanan + açık; hayali nosyonel = ikisinin hayali_usd toplamı.
- Pencere son 7 gün; trader adresi yok, yalnız adet.
