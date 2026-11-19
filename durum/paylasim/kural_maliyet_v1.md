# CT kural maliyeti (son 7 gün, 2026-11-19T21:02:14Z)

**Slot tavanı:** 6201 olay, 5 trader; karşı-olgu toplam 2.69 $ (kapanan 0.00, açık 2.69; hayali nosyonel 599.70 $).

| Neden | Olay | Trader | Karşı-olgu kapanan $ | Açık anlık $ | Toplam $ | Hayali nosyonel $ |
|---|---:|---:|---:|---:|---:|---:|
| bant_ici | 7856 | 8 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| slot_tavani | 6201 | 5 | 0.00 (0) | 2.69 (11) | 2.69 | 599.70 |
| hip3_atlandi | 3646 | 6 | -7.87 (3) | -10.88 (6) | -18.75 | 993.30 |
| min_emir_atlandi | 2535 | 5 | 0.00 (0) | -0.01 (1) | -0.01 | 0.93 |
| ters_netlesme | 1032 | 7 | 0.00 (0) | 0.97 (2) | 0.97 | 253.72 |
| spot_atlandi | 14 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| gec_acilis | 8 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| trader_hesap_yok | 3 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |

Notlar:

- Yalnız bilgi: kural, eşik, slot tavanı ve işlem mantığını değiştirmez.
- Karşı-olgu adres|coin başına TEK açılır (ilk atlama); slot_tavani gibi sık nedenleri eksik örnekler, $ değerleri alt sınır/yaklaşıktır.
- Olay = emir_yok adedi (ML atlaması bir kez sayılır); karşı-olgu yalnız ac/artir (bant_ici hariç).
- Açık anlık $ = şu an açık hayali pozisyonların son değerlemesi; toplam = kapanan + açık; hayali nosyonel = ikisinin hayali_usd toplamı.
- Pencere son 7 gün; trader adresi yok, yalnız adet.
