# CT kural maliyeti (son 7 gün, 2026-11-21T00:04:45Z)

**Slot tavanı:** 7551 olay, 6 trader; karşı-olgu toplam -128.33 $ (kapanan -18.96, açık -109.37; hayali nosyonel 4931.92 $).

| Neden | Olay | Trader | Karşı-olgu kapanan $ | Açık anlık $ | Toplam $ | Hayali nosyonel $ |
|---|---:|---:|---:|---:|---:|---:|
| bant_ici | 10950 | 10 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| slot_tavani | 7551 | 6 | -18.96 (10) | -109.37 (17) | -128.33 | 4931.92 |
| hip3_atlandi | 4130 | 6 | -24.54 (13) | -5.62 (9) | -30.16 | 1085.16 |
| min_emir_atlandi | 3322 | 7 | -0.35 (3) | -0.20 (2) | -0.55 | 5.06 |
| ters_netlesme | 1621 | 9 | 80.70 (7) | 9.20 (10) | 89.90 | 3371.71 |
| duygu_ters | 787 | 6 | 1.11 (2) | 38.29 (13) | 39.40 | 665.14 |
| ara_dolum_siniri | 137 | 3 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| rejim_ters | 91 | 3 | 1.06 (2) | -0.03 (1) | 1.03 | 636.49 |
| spot_atlandi | 25 | 1 | 0.00 (0) | -0.63 (1) | -0.63 | 68.82 |
| gec_acilis | 8 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| haber_ters | 8 | 2 | 0.00 (0) | -20.13 (2) | -20.13 | 309.97 |
| trader_hesap_yok | 3 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| patlama_freni | 2 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |

Notlar:

- Yalnız bilgi: kural, eşik, slot tavanı ve işlem mantığını değiştirmez.
- Karşı-olgu adres|coin başına TEK açılır (ilk atlama); slot_tavani gibi sık nedenleri eksik örnekler, $ değerleri alt sınır/yaklaşıktır.
- Olay = emir_yok adedi (ML atlaması bir kez sayılır); karşı-olgu yalnız ac/artir (bant_ici hariç).
- Açık anlık $ = şu an açık hayali pozisyonların son değerlemesi; toplam = kapanan + açık; hayali nosyonel = ikisinin hayali_usd toplamı.
- Pencere son 7 gün; trader adresi yok, yalnız adet.
