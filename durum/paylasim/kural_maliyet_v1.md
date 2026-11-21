# CT kural maliyeti (son 7 gün, 2026-11-21T01:04:50Z)

**Slot tavanı:** 7551 olay, 6 trader; karşı-olgu toplam -120.74 $ (kapanan -18.96, açık -101.78; hayali nosyonel 4931.92 $).

| Neden | Olay | Trader | Karşı-olgu kapanan $ | Açık anlık $ | Toplam $ | Hayali nosyonel $ |
|---|---:|---:|---:|---:|---:|---:|
| bant_ici | 10950 | 10 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| slot_tavani | 7551 | 6 | -18.96 (10) | -101.78 (17) | -120.74 | 4931.92 |
| hip3_atlandi | 4130 | 6 | -24.54 (13) | -5.45 (9) | -29.99 | 1085.16 |
| min_emir_atlandi | 3322 | 7 | -0.35 (3) | -0.19 (2) | -0.54 | 5.06 |
| ters_netlesme | 1627 | 9 | 80.70 (8) | 7.28 (10) | 87.98 | 3373.15 |
| duygu_ters | 818 | 6 | 1.11 (2) | 41.71 (14) | 42.82 | 665.99 |
| ara_dolum_siniri | 137 | 3 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| rejim_ters | 91 | 3 | 1.06 (2) | -0.03 (1) | 1.03 | 636.49 |
| spot_atlandi | 25 | 1 | 0.00 (0) | -0.82 (1) | -0.82 | 68.82 |
| gec_acilis | 8 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| haber_ters | 8 | 2 | 0.00 (0) | -20.97 (2) | -20.97 | 309.97 |
| trader_hesap_yok | 3 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| patlama_freni | 2 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |

Notlar:

- Yalnız bilgi: kural, eşik, slot tavanı ve işlem mantığını değiştirmez.
- Karşı-olgu adres|coin başına TEK açılır (ilk atlama); slot_tavani gibi sık nedenleri eksik örnekler, $ değerleri alt sınır/yaklaşıktır.
- Olay = emir_yok adedi (ML atlaması bir kez sayılır); karşı-olgu yalnız ac/artir (bant_ici hariç).
- Açık anlık $ = şu an açık hayali pozisyonların son değerlemesi; toplam = kapanan + açık; hayali nosyonel = ikisinin hayali_usd toplamı.
- Pencere son 7 gün; trader adresi yok, yalnız adet.
