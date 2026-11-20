# CT kural maliyeti (son 7 gün, 2026-11-20T00:05:17Z)

**Slot tavanı:** 6425 olay, 5 trader; karşı-olgu toplam -2.97 $ (kapanan 0.00, açık -2.97; hayali nosyonel 651.28 $).

| Neden | Olay | Trader | Karşı-olgu kapanan $ | Açık anlık $ | Toplam $ | Hayali nosyonel $ |
|---|---:|---:|---:|---:|---:|---:|
| bant_ici | 7947 | 8 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| slot_tavani | 6425 | 5 | 0.00 (0) | -2.97 (12) | -2.97 | 651.28 |
| hip3_atlandi | 4130 | 6 | -7.87 (3) | -10.11 (19) | -17.98 | 1085.16 |
| min_emir_atlandi | 2552 | 5 | 0.00 (0) | -0.02 (1) | -0.02 | 0.93 |
| ters_netlesme | 1123 | 7 | 0.00 (0) | 0.82 (4) | 0.82 | 675.40 |
| spot_atlandi | 14 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| gec_acilis | 8 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| trader_hesap_yok | 3 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |

Notlar:

- Yalnız bilgi: kural, eşik, slot tavanı ve işlem mantığını değiştirmez.
- Karşı-olgu adres|coin başına TEK açılır (ilk atlama); slot_tavani gibi sık nedenleri eksik örnekler, $ değerleri alt sınır/yaklaşıktır.
- Olay = emir_yok adedi (ML atlaması bir kez sayılır); karşı-olgu yalnız ac/artir (bant_ici hariç).
- Açık anlık $ = şu an açık hayali pozisyonların son değerlemesi; toplam = kapanan + açık; hayali nosyonel = ikisinin hayali_usd toplamı.
- Pencere son 7 gün; trader adresi yok, yalnız adet.
