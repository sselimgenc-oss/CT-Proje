# CT kural maliyeti (son 7 gün, 2026-11-20T19:02:52Z)

**Slot tavanı:** 7551 olay, 6 trader; karşı-olgu toplam -126.18 $ (kapanan -16.02, açık -110.16; hayali nosyonel 4931.92 $).

| Neden | Olay | Trader | Karşı-olgu kapanan $ | Açık anlık $ | Toplam $ | Hayali nosyonel $ |
|---|---:|---:|---:|---:|---:|---:|
| bant_ici | 10922 | 9 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| slot_tavani | 7551 | 6 | -16.02 (9) | -110.16 (18) | -126.18 | 4931.92 |
| hip3_atlandi | 4130 | 6 | -24.54 (13) | -4.28 (9) | -28.81 | 1085.16 |
| min_emir_atlandi | 3315 | 7 | -0.35 (3) | -0.17 (2) | -0.52 | 5.06 |
| ters_netlesme | 1610 | 9 | 80.70 (7) | 14.98 (9) | 95.68 | 3004.88 |
| duygu_ters | 787 | 6 | 0.19 (1) | 38.44 (14) | 38.63 | 665.14 |
| rejim_ters | 85 | 3 | 0.00 (0) | -0.05 (2) | -0.05 | 0.92 |
| ara_dolum_siniri | 47 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| spot_atlandi | 25 | 1 | 0.00 (0) | -0.80 (1) | -0.80 | 68.82 |
| gec_acilis | 8 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| haber_ters | 8 | 2 | 0.00 (0) | -21.18 (2) | -21.18 | 309.97 |
| trader_hesap_yok | 3 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| patlama_freni | 2 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |

Notlar:

- Yalnız bilgi: kural, eşik, slot tavanı ve işlem mantığını değiştirmez.
- Karşı-olgu adres|coin başına TEK açılır (ilk atlama); slot_tavani gibi sık nedenleri eksik örnekler, $ değerleri alt sınır/yaklaşıktır.
- Olay = emir_yok adedi (ML atlaması bir kez sayılır); karşı-olgu yalnız ac/artir (bant_ici hariç).
- Açık anlık $ = şu an açık hayali pozisyonların son değerlemesi; toplam = kapanan + açık; hayali nosyonel = ikisinin hayali_usd toplamı.
- Pencere son 7 gün; trader adresi yok, yalnız adet.
