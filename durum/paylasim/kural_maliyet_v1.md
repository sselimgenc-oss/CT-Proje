# CT kural maliyeti (son 7 gün, 2026-11-20T11:01:28Z)

**Slot tavanı:** 6440 olay, 6 trader; karşı-olgu toplam -15.40 $ (kapanan 0.68, açık -16.08; hayali nosyonel 1300.28 $).

| Neden | Olay | Trader | Karşı-olgu kapanan $ | Açık anlık $ | Toplam $ | Hayali nosyonel $ |
|---|---:|---:|---:|---:|---:|---:|
| bant_ici | 8768 | 8 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| slot_tavani | 6440 | 6 | 0.68 (2) | -16.08 (12) | -15.40 | 1300.28 |
| hip3_atlandi | 4130 | 6 | -14.95 (4) | -8.58 (18) | -23.53 | 1085.16 |
| min_emir_atlandi | 2695 | 6 | 0.00 (0) | -0.10 (3) | -0.10 | 3.49 |
| ters_netlesme | 1412 | 8 | 0.77 (5) | -4.94 (8) | -4.17 | 2413.89 |
| duygu_ters | 111 | 4 | 0.00 (0) | 1.26 (5) | 1.26 | 361.96 |
| spot_atlandi | 14 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| gec_acilis | 8 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| haber_ters | 8 | 2 | 0.00 (0) | 3.82 (2) | 3.82 | 309.97 |
| trader_hesap_yok | 3 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| patlama_freni | 2 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |

Notlar:

- Yalnız bilgi: kural, eşik, slot tavanı ve işlem mantığını değiştirmez.
- Karşı-olgu adres|coin başına TEK açılır (ilk atlama); slot_tavani gibi sık nedenleri eksik örnekler, $ değerleri alt sınır/yaklaşıktır.
- Olay = emir_yok adedi (ML atlaması bir kez sayılır); karşı-olgu yalnız ac/artir (bant_ici hariç).
- Açık anlık $ = şu an açık hayali pozisyonların son değerlemesi; toplam = kapanan + açık; hayali nosyonel = ikisinin hayali_usd toplamı.
- Pencere son 7 gün; trader adresi yok, yalnız adet.
