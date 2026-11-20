# CT kural maliyeti (son 7 gün, 2026-11-20T05:05:59Z)

**Slot tavanı:** 6440 olay, 6 trader; karşı-olgu toplam -16.11 $ (kapanan 0.68, açık -16.79; hayali nosyonel 1300.28 $).

| Neden | Olay | Trader | Karşı-olgu kapanan $ | Açık anlık $ | Toplam $ | Hayali nosyonel $ |
|---|---:|---:|---:|---:|---:|---:|
| bant_ici | 8095 | 8 | 0.00 (0) | 0.00 (0) | 0.00 | 0.00 |
| slot_tavani | 6440 | 6 | 0.68 (2) | -16.79 (12) | -16.11 | 1300.28 |
| hip3_atlandi | 4130 | 6 | -14.95 (4) | -9.41 (18) | -24.36 | 1085.16 |
| min_emir_atlandi | 2691 | 6 | 0.00 (0) | -0.11 (2) | -0.11 | 1.99 |
| ters_netlesme | 1238 | 7 | -0.12 (2) | 8.67 (7) | 8.55 | 883.74 |
| duygu_ters | 80 | 2 | 0.00 (0) | 0.19 (2) | 0.19 | 15.15 |
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
