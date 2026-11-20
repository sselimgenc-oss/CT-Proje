# CT kural maliyeti (son 7 gün, 2026-11-20T16:02:01Z)

**Slot tavanı:** 7538 olay, 6 trader; karşı-olgu toplam -121.43 $ (kapanan -15.34, açık -106.09; hayali nosyonel 4845.43 $).

| Neden | Olay | Trader | Karşı-olgu kapanan $ | Açık anlık $ | Toplam $ | Hayali nosyonel $ |
|---|---:|---:|---:|---:|---:|---:|
| bant_ici | 10732 | 9 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| slot_tavani | 7538 | 6 | -15.34 (8) | -106.09 (18) | -121.43 | 4845.43 |
| hip3_atlandi | 4130 | 6 | -24.54 (13) | -3.66 (9) | -28.20 | 1085.16 |
| min_emir_atlandi | 3248 | 7 | -0.27 (2) | -0.21 (2) | -0.47 | 4.40 |
| ters_netlesme | 1594 | 8 | 3.01 (6) | 60.74 (9) | 63.75 | 2759.03 |
| duygu_ters | 772 | 5 | 0.19 (1) | 36.16 (13) | 36.35 | 664.13 |
| rejim_ters | 30 | 2 | 0.00 (0) | -0.04 (2) | -0.04 | 0.92 |
| spot_atlandi | 14 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| gec_acilis | 8 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| haber_ters | 8 | 2 | 0.00 (0) | -14.84 (2) | -14.84 | 309.97 |
| trader_hesap_yok | 3 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| patlama_freni | 2 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |

Notlar:

- Yalnız bilgi: kural, eşik, slot tavanı ve işlem mantığını değiştirmez.
- Karşı-olgu adres|coin başına TEK açılır (ilk atlama); slot_tavani gibi sık nedenleri eksik örnekler, $ değerleri alt sınır/yaklaşıktır.
- Olay = emir_yok adedi (ML atlaması bir kez sayılır); karşı-olgu yalnız ac/artir (bant_ici hariç).
- Açık anlık $ = şu an açık hayali pozisyonların son değerlemesi; toplam = kapanan + açık; hayali nosyonel = ikisinin hayali_usd toplamı.
- Pencere son 7 gün; trader adresi yok, yalnız adet.
