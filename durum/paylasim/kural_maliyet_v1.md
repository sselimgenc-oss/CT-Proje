# CT kural maliyeti (son 7 gün, 2026-11-20T18:00:09Z)

**Slot tavanı:** 7551 olay, 6 trader; karşı-olgu toplam -127.80 $ (kapanan -15.34, açık -112.46; hayali nosyonel 4931.92 $).

| Neden | Olay | Trader | Karşı-olgu kapanan $ | Açık anlık $ | Toplam $ | Hayali nosyonel $ |
|---|---:|---:|---:|---:|---:|---:|
| bant_ici | 10900 | 9 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| slot_tavani | 7551 | 6 | -15.34 (8) | -112.46 (19) | -127.80 | 4931.92 |
| hip3_atlandi | 4130 | 6 | -24.54 (13) | -4.39 (9) | -28.92 | 1085.16 |
| min_emir_atlandi | 3311 | 7 | -0.27 (2) | -0.26 (3) | -0.53 | 5.06 |
| ters_netlesme | 1596 | 8 | 3.01 (6) | 67.34 (9) | 70.35 | 2759.03 |
| duygu_ters | 772 | 5 | 0.19 (1) | 40.33 (13) | 40.51 | 664.13 |
| rejim_ters | 84 | 2 | 0.00 (0) | -0.04 (2) | -0.04 | 0.92 |
| spot_atlandi | 25 | 1 | 0.00 (0) | -0.27 (1) | -0.27 | 68.82 |
| gec_acilis | 8 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| haber_ters | 8 | 2 | 0.00 (0) | -18.83 (2) | -18.83 | 309.97 |
| trader_hesap_yok | 3 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| patlama_freni | 2 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |

Notlar:

- Yalnız bilgi: kural, eşik, slot tavanı ve işlem mantığını değiştirmez.
- Karşı-olgu adres|coin başına TEK açılır (ilk atlama); slot_tavani gibi sık nedenleri eksik örnekler, $ değerleri alt sınır/yaklaşıktır.
- Olay = emir_yok adedi (ML atlaması bir kez sayılır); karşı-olgu yalnız ac/artir (bant_ici hariç).
- Açık anlık $ = şu an açık hayali pozisyonların son değerlemesi; toplam = kapanan + açık; hayali nosyonel = ikisinin hayali_usd toplamı.
- Pencere son 7 gün; trader adresi yok, yalnız adet.
