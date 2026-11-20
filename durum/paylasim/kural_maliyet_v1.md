# CT kural maliyeti (son 7 gün, 2026-11-20T04:05:50Z)

**Slot tavanı:** 6440 olay, 6 trader; karşı-olgu toplam -11.86 $ (kapanan 0.68, açık -12.53; hayali nosyonel 1300.28 $).

| Neden | Olay | Trader | Karşı-olgu kapanan $ | Açık anlık $ | Toplam $ | Hayali nosyonel $ |
|---|---:|---:|---:|---:|---:|---:|
| bant_ici | 8090 | 8 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| slot_tavani | 6440 | 6 | 0.68 (2) | -12.53 (12) | -11.86 | 1300.28 |
| hip3_atlandi | 4130 | 6 | -14.95 (4) | -6.64 (18) | -21.59 | 1085.16 |
| min_emir_atlandi | 2691 | 6 | 0.00 (0) | -0.06 (2) | -0.06 | 1.99 |
| ters_netlesme | 1234 | 7 | -0.12 (2) | 6.12 (6) | 6.00 | 867.32 |
| duygu_ters | 80 | 2 | 0.00 (0) | 0.04 (2) | 0.04 | 15.15 |
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
