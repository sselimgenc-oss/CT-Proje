# CT kural maliyeti (son 7 gün, 2026-11-21T02:05:16Z)

**Slot tavanı:** 7551 olay, 6 trader; karşı-olgu toplam -127.10 $ (kapanan -18.96, açık -108.13; hayali nosyonel 4931.92 $).

| Neden | Olay | Trader | Karşı-olgu kapanan $ | Açık anlık $ | Toplam $ | Hayali nosyonel $ |
|---|---:|---:|---:|---:|---:|---:|
| bant_ici | 10950 | 10 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| slot_tavani | 7551 | 6 | -18.96 (10) | -108.13 (17) | -127.10 | 4931.92 |
| hip3_atlandi | 4130 | 6 | -24.54 (13) | -5.35 (9) | -29.88 | 1085.16 |
| min_emir_atlandi | 3322 | 7 | -0.35 (3) | -0.19 (2) | -0.54 | 5.06 |
| ters_netlesme | 1627 | 9 | 80.70 (8) | 5.38 (10) | 86.08 | 3373.15 |
| duygu_ters | 837 | 6 | 1.11 (2) | 42.24 (14) | 43.35 | 665.99 |
| ara_dolum_siniri | 137 | 3 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| rejim_ters | 91 | 3 | 1.06 (2) | -0.03 (1) | 1.03 | 636.49 |
| spot_atlandi | 25 | 1 | 0.00 (0) | -0.48 (1) | -0.48 | 68.82 |
| gec_acilis | 8 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| haber_ters | 8 | 2 | 0.00 (0) | -19.56 (2) | -19.56 | 309.97 |
| trader_hesap_yok | 3 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| patlama_freni | 2 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |

Notlar:

- Yalnız bilgi: kural, eşik, slot tavanı ve işlem mantığını değiştirmez.
- Karşı-olgu adres|coin başına TEK açılır (ilk atlama); slot_tavani gibi sık nedenleri eksik örnekler, $ değerleri alt sınır/yaklaşıktır.
- Olay = emir_yok adedi (ML atlaması bir kez sayılır); karşı-olgu yalnız ac/artir (bant_ici hariç).
- Açık anlık $ = şu an açık hayali pozisyonların son değerlemesi; toplam = kapanan + açık; hayali nosyonel = ikisinin hayali_usd toplamı.
- Pencere son 7 gün; trader adresi yok, yalnız adet.
