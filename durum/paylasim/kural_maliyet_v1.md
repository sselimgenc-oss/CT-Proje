# CT kural maliyeti (son 7 gün, 2026-11-20T17:02:32Z)

**Slot tavanı:** 7538 olay, 6 trader; karşı-olgu toplam -145.46 $ (kapanan -15.34, açık -130.12; hayali nosyonel 4845.43 $).

| Neden | Olay | Trader | Karşı-olgu kapanan $ | Açık anlık $ | Toplam $ | Hayali nosyonel $ |
|---|---:|---:|---:|---:|---:|---:|
| bant_ici | 10878 | 9 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| slot_tavani | 7538 | 6 | -15.34 (8) | -130.12 (18) | -145.46 | 4845.43 |
| hip3_atlandi | 4130 | 6 | -24.54 (13) | -4.51 (9) | -29.05 | 1085.16 |
| min_emir_atlandi | 3271 | 7 | -0.27 (2) | -0.29 (3) | -0.56 | 5.06 |
| ters_netlesme | 1595 | 8 | 3.01 (6) | 64.34 (9) | 67.35 | 2759.03 |
| duygu_ters | 772 | 5 | 0.19 (1) | 41.30 (13) | 41.48 | 664.13 |
| rejim_ters | 84 | 2 | 0.00 (0) | -0.04 (2) | -0.04 | 0.92 |
| spot_atlandi | 14 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| gec_acilis | 8 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| haber_ters | 8 | 2 | 0.00 (0) | -18.22 (2) | -18.22 | 309.97 |
| trader_hesap_yok | 3 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| patlama_freni | 2 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |

Notlar:

- Yalnız bilgi: kural, eşik, slot tavanı ve işlem mantığını değiştirmez.
- Karşı-olgu adres|coin başına TEK açılır (ilk atlama); slot_tavani gibi sık nedenleri eksik örnekler, $ değerleri alt sınır/yaklaşıktır.
- Olay = emir_yok adedi (ML atlaması bir kez sayılır); karşı-olgu yalnız ac/artir (bant_ici hariç).
- Açık anlık $ = şu an açık hayali pozisyonların son değerlemesi; toplam = kapanan + açık; hayali nosyonel = ikisinin hayali_usd toplamı.
- Pencere son 7 gün; trader adresi yok, yalnız adet.
