# CT kural maliyeti (son 7 gün, 2026-11-20T01:03:37Z)

**Slot tavanı:** 6425 olay, 5 trader; karşı-olgu toplam -2.19 $ (kapanan 0.68, açık -2.86; hayali nosyonel 651.27 $).

| Neden | Olay | Trader | Karşı-olgu kapanan $ | Açık anlık $ | Toplam $ | Hayali nosyonel $ |
|---|---:|---:|---:|---:|---:|---:|
| bant_ici | 7947 | 8 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| slot_tavani | 6425 | 5 | 0.68 (2) | -2.86 (10) | -2.19 | 651.27 |
| hip3_atlandi | 4130 | 6 | -7.87 (3) | -13.46 (19) | -21.33 | 1085.16 |
| min_emir_atlandi | 2625 | 5 | 0.00 (0) | -0.02 (1) | -0.02 | 0.93 |
| ters_netlesme | 1127 | 7 | 0.02 (1) | 0.19 (5) | 0.21 | 762.57 |
| duygu_ters | 78 | 1 | 0.00 (0) | 0.00 (1) | 0.00 | 1.43 |
| spot_atlandi | 14 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| gec_acilis | 8 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| trader_hesap_yok | 3 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |

Notlar:

- Yalnız bilgi: kural, eşik, slot tavanı ve işlem mantığını değiştirmez.
- Karşı-olgu adres|coin başına TEK açılır (ilk atlama); slot_tavani gibi sık nedenleri eksik örnekler, $ değerleri alt sınır/yaklaşıktır.
- Olay = emir_yok adedi (ML atlaması bir kez sayılır); karşı-olgu yalnız ac/artir (bant_ici hariç).
- Açık anlık $ = şu an açık hayali pozisyonların son değerlemesi; toplam = kapanan + açık; hayali nosyonel = ikisinin hayali_usd toplamı.
- Pencere son 7 gün; trader adresi yok, yalnız adet.
