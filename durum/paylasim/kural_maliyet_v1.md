# CT kural maliyeti (son 7 gün, 2026-11-20T02:18:39Z)

**Slot tavanı:** 6426 olay, 6 trader; karşı-olgu toplam -8.12 $ (kapanan 0.68, açık -8.80; hayali nosyonel 1233.02 $).

| Neden | Olay | Trader | Karşı-olgu kapanan $ | Açık anlık $ | Toplam $ | Hayali nosyonel $ |
|---|---:|---:|---:|---:|---:|---:|
| bant_ici | 7971 | 8 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| slot_tavani | 6426 | 6 | 0.68 (2) | -8.80 (11) | -8.12 | 1233.02 |
| hip3_atlandi | 4130 | 6 | -7.87 (3) | -13.34 (19) | -21.21 | 1085.16 |
| min_emir_atlandi | 2627 | 5 | 0.00 (0) | -0.05 (2) | -0.05 | 1.99 |
| ters_netlesme | 1176 | 7 | 0.02 (1) | 5.52 (5) | 5.54 | 762.57 |
| duygu_ters | 80 | 2 | 0.00 (0) | 0.05 (2) | 0.05 | 15.15 |
| spot_atlandi | 14 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| gec_acilis | 8 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| trader_hesap_yok | 3 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| patlama_freni | 2 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |

Notlar:

- Yalnız bilgi: kural, eşik, slot tavanı ve işlem mantığını değiştirmez.
- Karşı-olgu adres|coin başına TEK açılır (ilk atlama); slot_tavani gibi sık nedenleri eksik örnekler, $ değerleri alt sınır/yaklaşıktır.
- Olay = emir_yok adedi (ML atlaması bir kez sayılır); karşı-olgu yalnız ac/artir (bant_ici hariç).
- Açık anlık $ = şu an açık hayali pozisyonların son değerlemesi; toplam = kapanan + açık; hayali nosyonel = ikisinin hayali_usd toplamı.
- Pencere son 7 gün; trader adresi yok, yalnız adet.
