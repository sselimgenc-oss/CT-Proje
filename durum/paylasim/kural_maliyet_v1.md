# CT kural maliyeti (son 7 gün, 2026-11-20T15:02:39Z)

**Slot tavanı:** 7502 olay, 6 trader; karşı-olgu toplam -1.64 $ (kapanan 0.42, açık -2.06; hayali nosyonel 3643.38 $).

| Neden | Olay | Trader | Karşı-olgu kapanan $ | Açık anlık $ | Toplam $ | Hayali nosyonel $ |
|---|---:|---:|---:|---:|---:|---:|
| bant_ici | 10084 | 8 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| slot_tavani | 7502 | 6 | 0.42 (3) | -2.06 (21) | -1.64 | 3643.38 |
| hip3_atlandi | 4130 | 6 | -14.74 (10) | -5.90 (12) | -20.64 | 1085.15 |
| min_emir_atlandi | 3200 | 7 | -0.02 (1) | -0.08 (3) | -0.10 | 4.40 |
| ters_netlesme | 1511 | 8 | 3.01 (6) | -3.84 (9) | -0.83 | 2759.03 |
| duygu_ters | 770 | 5 | 0.00 (0) | 10.96 (14) | 10.96 | 664.13 |
| rejim_ters | 25 | 2 | 0.00 (0) | -0.00 (2) | -0.00 | 0.92 |
| spot_atlandi | 14 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| gec_acilis | 8 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| haber_ters | 8 | 2 | 0.00 (0) | 1.21 (2) | 1.21 | 309.97 |
| trader_hesap_yok | 3 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| patlama_freni | 2 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |

Notlar:

- Yalnız bilgi: kural, eşik, slot tavanı ve işlem mantığını değiştirmez.
- Karşı-olgu adres|coin başına TEK açılır (ilk atlama); slot_tavani gibi sık nedenleri eksik örnekler, $ değerleri alt sınır/yaklaşıktır.
- Olay = emir_yok adedi (ML atlaması bir kez sayılır); karşı-olgu yalnız ac/artir (bant_ici hariç).
- Açık anlık $ = şu an açık hayali pozisyonların son değerlemesi; toplam = kapanan + açık; hayali nosyonel = ikisinin hayali_usd toplamı.
- Pencere son 7 gün; trader adresi yok, yalnız adet.
