# REVİZYON 1 DONDURULDU — tek revizyon hakkı (ileriye dönük sınav)

Yazılma: 2026-11-14. Kullanıcı kararı: "1'e tamamım" (seçenek 1: şimdilik canlı yok, tek revizyon bugün dondurulur, ileriye dönük ölçülür).
Bu dosya sonradan değiştirilmez. Tur 1 sonucu (RAPOR.md, 14.11): A/B/D "kötü" (rastgeleden kötü, maliyet sonrası zararda); C kâğıt üzerinde "belirsiz" ama 7 adres / 17 gözlem (gürültü). Fable incelemesi: t sıralaması ve kural 2 değer katmıyor (yön ters), vetolar en kötüleri ayıklıyor.

## Revizyon (yalnız kural ÇIKARMA; yeni eşik YOK)
- Seçim = T'de: hesap ≥ 50.000 $ VE T'den önceki 30 g perp pnl > 0 (kontrol tanımı) VE §1 kapıları **3–7** (KURALLAR_DONDURULDU.md, aynen) VE iki veto (B kolu, aynen).
- **Kaldırılan:** §1 kural 2 (12 haftanın ≥ 8'i pozitif + 90 g düşüş) ve kural 8 (t-istatistiği sıralaması). Geçenlerin TÜMÜ seçilir, eşit ağırlık.
- Bilinçli olarak EKLENMEYEN: devir ≤ 5x, kaldıraç ≤ 1,5x, geçmiş kopya getirisi tavanı (tur 1 verisinden okundu → aşırı uyum riski).
- Ölçüm C kolundan farklı olarak **tam evrende** (donmuş `evren.json`, 11.11), yalnız 700'lük örneklemde değil.

## Tarihler (gerçek örneklem dışı)
- T12 = 2026-10-14 (kilitliydi), T13 = 2026-10-21, T14 = 2026-10-28, T15 = 2026-11-04, T16 = 2026-11-11. Pencere [T, T + 28 g). Son olgunlaşma 2026-12-09.
- Evren 11.11 lider tablosundan kurulduğu için bu ileri pencerelerde hayatta kalma yanlılığı yok (sonradan batan / çeken hesaplar evrende).
- Veri tanımları, kopya oynatma, maliyet, veri yeterliliği / çıkarma: KURALLAR_DONDURULDU.md ile aynen.

## Kontrol
- Birincil: KURALLAR_DONDURULDU.md'deki kontrol (≥ 50k, 30 g pnl > 0; sabit tohumlu 700 adres; her T'de 1.000 eşit büyüklükte çekiliş).
- İkincil (bilgi, hükme girmez): aynı havuzdan yalnız T'den önceki 28 g'de işlemi olanlar (geleceğe bakmadan).

## Geçme şartı (üçü birden)
1. Birleşik yüzdelik (KURALLAR_DONDURULDU §3 şart 1 aynen, T12–T16) ≥ %90.
2. 5 tarihin en az 4'ünde seçilen ortanca > kontrol havuzu ortancası (seçileni olmayan T "iyi değil").
3. Tüm (T, seçilen) çiftlerinin maliyet sonrası ortanca net getirisi > 0.
- Bilgi olarak raporlanır (hükme girmez): ortalama, sol kuyruk (< −%5 payı), adres kümeli bootstrap.

## Hüküm
- Üçü birden geçerse: seçim "geçti" → Faz 4'ün diğer şartlarına (kopya köprüsü, güvenlik listesi, gerçek /kapat testi) geçilir; canlı yine kullanıcı kararı.
- Geçmezse: K-65 terk ölçütü — bu seçim yaklaşımıyla canlı YOK; yapı yeniden tasarlanır ya da durulur (kullanıcı kararı). Başka revizyon hakkı yok.
