# CT kural maliyeti (son 7 gün, 2026-11-20T02:04:49Z)

**Slot tavanı:** 6425 olay, 5 trader; karşı-olgu toplam -8.34 $ (kapanan 0.68, açık -9.01; hayali nosyonel 651.27 $).

| Neden | Olay | Trader | Karşı-olgu kapanan $ | Açık anlık $ | Toplam $ | Hayali nosyonel $ |
|---|---:|---:|---:|---:|---:|---:|
| bant_ici | 7957 | 8 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| slot_tavani | 6425 | 5 | 0.68 (2) | -9.01 (10) | -8.34 | 651.27 |
| hip3_atlandi | 4130 | 6 | -7.87 (3) | -14.71 (19) | -22.58 | 1085.16 |
| min_emir_atlandi | 2627 | 5 | 0.00 (0) | -0.04 (2) | -0.04 | 1.99 |
| ters_netlesme | 1155 | 7 | 0.02 (1) | 5.92 (5) | 5.94 | 762.57 |
| duygu_ters | 80 | 2 | 0.00 (0) | 0.04 (2) | 0.04 | 15.15 |
| spot_atlandi | 14 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| gec_acilis | 8 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| trader_hesap_yok | 3 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |

Notlar:

- Yalnız bilgi: kural, eşik, slot tavanı ve işlem mantığını değiştirmez.
- Karşı-olgu adres|coin başına TEK açılır (ilk atlama); slot_tavani gibi sık nedenleri eksik örnekler, $ değerleri alt sınır/yaklaşıktır.
- Olay = emir_yok adedi (ML atlaması bir kez sayılır); karşı-olgu yalnız ac/artir (bant_ici hariç).
- Açık anlık $ = şu an açık hayali pozisyonların son değerlemesi; toplam = kapanan + açık; hayali nosyonel = ikisinin hayali_usd toplamı.
- Pencere son 7 gün; trader adresi yok, yalnız adet.
