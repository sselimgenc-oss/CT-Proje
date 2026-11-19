# CT kural maliyeti (son 7 gün, 2026-11-19T22:02:31Z)

**Slot tavanı:** 6420 olay, 5 trader; karşı-olgu toplam 1.31 $ (kapanan 0.00, açık 1.31; hayali nosyonel 599.70 $).

| Neden | Olay | Trader | Karşı-olgu kapanan $ | Açık anlık $ | Toplam $ | Hayali nosyonel $ |
|---|---:|---:|---:|---:|---:|---:|
| bant_ici | 7947 | 8 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| slot_tavani | 6420 | 5 | 0.00 (0) | 1.31 (11) | 1.31 | 599.70 |
| hip3_atlandi | 3943 | 6 | -7.87 (3) | -10.11 (15) | -17.98 | 1057.93 |
| min_emir_atlandi | 2552 | 5 | 0.00 (0) | -0.02 (1) | -0.02 | 0.93 |
| ters_netlesme | 1051 | 7 | 0.00 (0) | 0.42 (3) | 0.42 | 255.70 |
| spot_atlandi | 14 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| gec_acilis | 8 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| trader_hesap_yok | 3 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |

Notlar:

- Yalnız bilgi: kural, eşik, slot tavanı ve işlem mantığını değiştirmez.
- Karşı-olgu adres|coin başına TEK açılır (ilk atlama); slot_tavani gibi sık nedenleri eksik örnekler, $ değerleri alt sınır/yaklaşıktır.
- Olay = emir_yok adedi (ML atlaması bir kez sayılır); karşı-olgu yalnız ac/artir (bant_ici hariç).
- Açık anlık $ = şu an açık hayali pozisyonların son değerlemesi; toplam = kapanan + açık; hayali nosyonel = ikisinin hayali_usd toplamı.
- Pencere son 7 gün; trader adresi yok, yalnız adet.
