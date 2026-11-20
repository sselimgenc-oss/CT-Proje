# CT kural maliyeti (son 7 gün, 2026-11-20T14:05:28Z)

**Slot tavanı:** 7329 olay, 6 trader; karşı-olgu toplam -11.56 $ (kapanan 0.68, açık -12.24; hayali nosyonel 2690.55 $).

| Neden | Olay | Trader | Karşı-olgu kapanan $ | Açık anlık $ | Toplam $ | Hayali nosyonel $ |
|---|---:|---:|---:|---:|---:|---:|
| bant_ici | 9579 | 8 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| slot_tavani | 7329 | 6 | 0.68 (2) | -12.24 (20) | -11.56 | 2690.55 |
| hip3_atlandi | 4130 | 6 | -14.95 (4) | -10.75 (18) | -25.70 | 1085.16 |
| min_emir_atlandi | 3167 | 6 | -0.02 (1) | -0.06 (3) | -0.08 | 4.40 |
| ters_netlesme | 1506 | 8 | 0.77 (5) | -2.37 (9) | -1.60 | 2420.10 |
| duygu_ters | 770 | 5 | 0.00 (0) | 12.43 (14) | 12.43 | 664.13 |
| rejim_ters | 15 | 1 | 0.00 (0) | -0.00 (1) | -0.00 | 0.56 |
| spot_atlandi | 14 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| gec_acilis | 8 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| haber_ters | 8 | 2 | 0.00 (0) | 2.95 (2) | 2.95 | 309.97 |
| trader_hesap_yok | 3 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| patlama_freni | 2 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |

Notlar:

- Yalnız bilgi: kural, eşik, slot tavanı ve işlem mantığını değiştirmez.
- Karşı-olgu adres|coin başına TEK açılır (ilk atlama); slot_tavani gibi sık nedenleri eksik örnekler, $ değerleri alt sınır/yaklaşıktır.
- Olay = emir_yok adedi (ML atlaması bir kez sayılır); karşı-olgu yalnız ac/artir (bant_ici hariç).
- Açık anlık $ = şu an açık hayali pozisyonların son değerlemesi; toplam = kapanan + açık; hayali nosyonel = ikisinin hayali_usd toplamı.
- Pencere son 7 gün; trader adresi yok, yalnız adet.
