# CT kural maliyeti (son 7 gün, 2026-11-20T06:05:03Z)

**Slot tavanı:** 6440 olay, 6 trader; karşı-olgu toplam -16.85 $ (kapanan 0.68, açık -17.53; hayali nosyonel 1300.28 $).

| Neden | Olay | Trader | Karşı-olgu kapanan $ | Açık anlık $ | Toplam $ | Hayali nosyonel $ |
|---|---:|---:|---:|---:|---:|---:|
| bant_ici | 8311 | 8 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| slot_tavani | 6440 | 6 | 0.68 (2) | -17.53 (12) | -16.85 | 1300.28 |
| hip3_atlandi | 4130 | 6 | -14.95 (4) | -8.94 (18) | -23.89 | 1085.16 |
| min_emir_atlandi | 2694 | 6 | 0.00 (0) | -0.09 (3) | -0.09 | 3.49 |
| ters_netlesme | 1316 | 7 | -3.47 (4) | 7.69 (5) | 4.22 | 883.74 |
| duygu_ters | 81 | 2 | 0.00 (0) | 0.07 (2) | 0.07 | 15.15 |
| spot_atlandi | 14 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| gec_acilis | 8 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| haber_ters | 5 | 1 | 0.00 (0) | 0.93 (1) | 0.93 | 105.73 |
| trader_hesap_yok | 3 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| patlama_freni | 2 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |

Notlar:

- Yalnız bilgi: kural, eşik, slot tavanı ve işlem mantığını değiştirmez.
- Karşı-olgu adres|coin başına TEK açılır (ilk atlama); slot_tavani gibi sık nedenleri eksik örnekler, $ değerleri alt sınır/yaklaşıktır.
- Olay = emir_yok adedi (ML atlaması bir kez sayılır); karşı-olgu yalnız ac/artir (bant_ici hariç).
- Açık anlık $ = şu an açık hayali pozisyonların son değerlemesi; toplam = kapanan + açık; hayali nosyonel = ikisinin hayali_usd toplamı.
- Pencere son 7 gün; trader adresi yok, yalnız adet.
