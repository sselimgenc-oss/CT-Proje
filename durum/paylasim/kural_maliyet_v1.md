# CT kural maliyeti (son 7 gün, 2026-11-21T03:05:32Z)

**Slot tavanı:** 7551 olay, 6 trader; karşı-olgu toplam -141.59 $ (kapanan -18.96, açık -122.63; hayali nosyonel 4931.92 $).

| Neden | Olay | Trader | Karşı-olgu kapanan $ | Açık anlık $ | Toplam $ | Hayali nosyonel $ |
|---|---:|---:|---:|---:|---:|---:|
| bant_ici | 10950 | 10 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| slot_tavani | 7551 | 6 | -18.96 (10) | -122.63 (17) | -141.59 | 4931.92 |
| hip3_atlandi | 4130 | 6 | -24.54 (13) | -5.58 (9) | -30.11 | 1085.16 |
| min_emir_atlandi | 3322 | 7 | -0.35 (3) | -0.20 (2) | -0.55 | 5.06 |
| ters_netlesme | 1627 | 9 | 80.70 (8) | 7.37 (10) | 88.07 | 3373.15 |
| duygu_ters | 837 | 6 | 1.11 (2) | 58.90 (14) | 60.01 | 665.99 |
| ara_dolum_siniri | 137 | 3 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| rejim_ters | 91 | 3 | 1.06 (2) | -0.04 (1) | 1.02 | 636.49 |
| spot_atlandi | 25 | 1 | 0.00 (0) | -1.35 (1) | -1.35 | 68.82 |
| gec_acilis | 8 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| haber_ters | 8 | 2 | 0.00 (0) | -23.29 (2) | -23.29 | 309.97 |
| trader_hesap_yok | 3 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| patlama_freni | 2 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |

Notlar:

- Yalnız bilgi: kural, eşik, slot tavanı ve işlem mantığını değiştirmez.
- Karşı-olgu adres|coin başına TEK açılır (ilk atlama); slot_tavani gibi sık nedenleri eksik örnekler, $ değerleri alt sınır/yaklaşıktır.
- Olay = emir_yok adedi (ML atlaması bir kez sayılır); karşı-olgu yalnız ac/artir (bant_ici hariç).
- Açık anlık $ = şu an açık hayali pozisyonların son değerlemesi; toplam = kapanan + açık; hayali nosyonel = ikisinin hayali_usd toplamı.
- Pencere son 7 gün; trader adresi yok, yalnız adet.
