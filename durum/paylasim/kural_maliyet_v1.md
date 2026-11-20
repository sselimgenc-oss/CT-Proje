# CT kural maliyeti (son 7 gün, 2026-11-20T12:01:41Z)

**Slot tavanı:** 6762 olay, 6 trader; karşı-olgu toplam -18.73 $ (kapanan 0.68, açık -19.41; hayali nosyonel 1744.70 $).

| Neden | Olay | Trader | Karşı-olgu kapanan $ | Açık anlık $ | Toplam $ | Hayali nosyonel $ |
|---|---:|---:|---:|---:|---:|---:|
| bant_ici | 8982 | 8 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| slot_tavani | 6762 | 6 | 0.68 (2) | -19.41 (17) | -18.73 | 1744.70 |
| hip3_atlandi | 4130 | 6 | -14.95 (4) | -10.42 (18) | -25.37 | 1085.16 |
| min_emir_atlandi | 3064 | 6 | -0.02 (1) | -0.11 (2) | -0.14 | 3.49 |
| ters_netlesme | 1417 | 8 | 0.77 (5) | 1.22 (9) | 1.99 | 2420.10 |
| duygu_ters | 503 | 5 | 0.00 (0) | 8.82 (12) | 8.82 | 634.27 |
| rejim_ters | 15 | 1 | 0.00 (0) | 0.00 (1) | 0.00 | 0.56 |
| spot_atlandi | 14 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| gec_acilis | 8 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| haber_ters | 8 | 2 | 0.00 (0) | 2.27 (2) | 2.27 | 309.97 |
| trader_hesap_yok | 3 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| patlama_freni | 2 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |

Notlar:

- Yalnız bilgi: kural, eşik, slot tavanı ve işlem mantığını değiştirmez.
- Karşı-olgu adres|coin başına TEK açılır (ilk atlama); slot_tavani gibi sık nedenleri eksik örnekler, $ değerleri alt sınır/yaklaşıktır.
- Olay = emir_yok adedi (ML atlaması bir kez sayılır); karşı-olgu yalnız ac/artir (bant_ici hariç).
- Açık anlık $ = şu an açık hayali pozisyonların son değerlemesi; toplam = kapanan + açık; hayali nosyonel = ikisinin hayali_usd toplamı.
- Pencere son 7 gün; trader adresi yok, yalnız adet.
