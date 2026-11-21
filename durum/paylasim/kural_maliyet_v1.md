# CT kural maliyeti (son 7 gün, 2026-11-21T07:33:01Z)

**Slot tavanı:** 7551 olay, 6 trader; karşı-olgu toplam -154.34 $ (kapanan -18.96, açık -135.38; hayali nosyonel 4931.92 $).

| Neden | Olay | Trader | Karşı-olgu kapanan $ | Açık anlık $ | Toplam $ | Hayali nosyonel $ |
|---|---:|---:|---:|---:|---:|---:|
| bant_ici | 10981 | 10 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| slot_tavani | 7551 | 6 | -18.96 (10) | -135.38 (17) | -154.34 | 4931.92 |
| hip3_atlandi | 4130 | 6 | -24.96 (15) | -5.40 (7) | -30.35 | 1085.16 |
| min_emir_atlandi | 3325 | 7 | -0.35 (3) | -0.22 (2) | -0.57 | 5.06 |
| ters_netlesme | 1635 | 9 | 98.85 (9) | -18.84 (10) | 80.01 | 3567.30 |
| duygu_ters | 884 | 6 | 1.92 (4) | 43.42 (15) | 45.33 | 868.25 |
| ara_dolum_siniri | 365 | 5 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| rejim_ters | 99 | 4 | 1.06 (2) | -0.01 (2) | 1.05 | 638.52 |
| spot_atlandi | 25 | 1 | 0.00 (0) | -0.09 (1) | -0.09 | 68.82 |
| gec_acilis | 8 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| haber_ters | 8 | 2 | 0.00 (0) | -17.95 (2) | -17.95 | 309.97 |
| trader_hesap_yok | 3 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| patlama_freni | 2 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |

Notlar:

- Yalnız bilgi: kural, eşik, slot tavanı ve işlem mantığını değiştirmez.
- Karşı-olgu adres|coin başına TEK açılır (ilk atlama); slot_tavani gibi sık nedenleri eksik örnekler, $ değerleri alt sınır/yaklaşıktır.
- Olay = emir_yok adedi (ML atlaması bir kez sayılır); karşı-olgu yalnız ac/artir (bant_ici hariç).
- Açık anlık $ = şu an açık hayali pozisyonların son değerlemesi; toplam = kapanan + açık; hayali nosyonel = ikisinin hayali_usd toplamı.
- Pencere son 7 gün; trader adresi yok, yalnız adet.
