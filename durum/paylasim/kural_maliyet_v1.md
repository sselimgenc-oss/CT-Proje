# CT kural maliyeti (son 7 gün, 2026-11-20T08:05:34Z)

**Slot tavanı:** 6440 olay, 6 trader; karşı-olgu toplam -16.91 $ (kapanan 0.68, açık -17.58; hayali nosyonel 1300.28 $).

| Neden | Olay | Trader | Karşı-olgu kapanan $ | Açık anlık $ | Toplam $ | Hayali nosyonel $ |
|---|---:|---:|---:|---:|---:|---:|
| bant_ici | 8373 | 8 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| slot_tavani | 6440 | 6 | 0.68 (2) | -17.58 (12) | -16.91 | 1300.28 |
| hip3_atlandi | 4130 | 6 | -14.95 (4) | -7.98 (18) | -22.93 | 1085.16 |
| min_emir_atlandi | 2694 | 6 | 0.00 (0) | -0.06 (3) | -0.06 | 3.49 |
| ters_netlesme | 1320 | 8 | 0.77 (5) | 2.81 (5) | 3.58 | 2247.38 |
| duygu_ters | 98 | 3 | 0.00 (0) | 0.17 (3) | 0.17 | 87.39 |
| spot_atlandi | 14 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| gec_acilis | 8 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| haber_ters | 8 | 2 | 0.00 (0) | 2.50 (2) | 2.50 | 309.97 |
| trader_hesap_yok | 3 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| patlama_freni | 2 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |

Notlar:

- Yalnız bilgi: kural, eşik, slot tavanı ve işlem mantığını değiştirmez.
- Karşı-olgu adres|coin başına TEK açılır (ilk atlama); slot_tavani gibi sık nedenleri eksik örnekler, $ değerleri alt sınır/yaklaşıktır.
- Olay = emir_yok adedi (ML atlaması bir kez sayılır); karşı-olgu yalnız ac/artir (bant_ici hariç).
- Açık anlık $ = şu an açık hayali pozisyonların son değerlemesi; toplam = kapanan + açık; hayali nosyonel = ikisinin hayali_usd toplamı.
- Pencere son 7 gün; trader adresi yok, yalnız adet.
