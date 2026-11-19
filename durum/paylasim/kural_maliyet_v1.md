# CT kural maliyeti (son 7 gün, 2026-11-19T20:05:47Z)

**Slot tavanı:** 5815 olay, 5 trader; karşı-olgu toplam 0.51 $ (kapanan 0.00, açık 0.51; hayali nosyonel 122.31 $).

| Neden | Olay | Trader | Karşı-olgu kapanan $ | Açık anlık $ | Toplam $ | Hayali nosyonel $ |
|---|---:|---:|---:|---:|---:|---:|
| bant_ici | 7817 | 8 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| slot_tavani | 5815 | 5 | 0.00 (0) | 0.51 (3) | 0.51 | 122.31 |
| hip3_atlandi | 3480 | 6 | -7.87 (3) | -9.03 (6) | -16.90 | 993.30 |
| min_emir_atlandi | 2419 | 5 | 0.00 (0) | -0.01 (1) | -0.01 | 0.93 |
| ters_netlesme | 1026 | 7 | 0.00 (0) | 0.11 (2) | 0.11 | 253.72 |
| spot_atlandi | 14 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| gec_acilis | 8 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| trader_hesap_yok | 3 | 1 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |

Notlar:

- Yalnız bilgi: kural, eşik, slot tavanı ve işlem mantığını değiştirmez.
- Karşı-olgu adres|coin başına TEK açılır (ilk atlama); slot_tavani gibi sık nedenleri eksik örnekler, $ değerleri alt sınır/yaklaşıktır.
- Olay = emir_yok adedi (ML atlaması bir kez sayılır); karşı-olgu yalnız ac/artir (bant_ici hariç).
- Açık anlık $ = şu an açık hayali pozisyonların son değerlemesi; toplam = kapanan + açık; hayali nosyonel = ikisinin hayali_usd toplamı.
- Pencere son 7 gün; trader adresi yok, yalnız adet.
