# Faz 2 — İşlem panosu (kullanıcı kararı 2026-11-02)

Kullanıcı: "Pano olarak kullanıcı dostu, işlemlerin şu tarz gözüktüğü bir pano istiyorum; hem telefonda hem PC'de HTML olarak çalışacak."
Örnek ekran: `docs/img/pano_ornek_2026-11-02.webp` (görsel referans; birebir kopya değil, düzen ve içerik örneği).

## Sıra (değişmez)
- Pano **Faz 1 tamamlandıktan sonra** yapılır: veri, trader seçimi ve motor önce (K‑12, DURUM "tamamlandı kanıtları").
- Pano yalnız **okur**: `copytrade-izleme:izleme/durum.json` ve `copytrade-kapi:ilk11/…` (veri dalları). Hesap yapmaz (AGENTS kural 7);
  gösterilen her sayı motorun yayımladığı alandır. Eksik alan uydurulmaz, "—" / "bilinmiyor" gösterilir.
- Gerçek para yok: başlıkta `SİM` rozeti (PAPER).

## İçerik (örnek ekrana göre)
1. **Başlık:** kol/takım adı (İlk 11, Yedek 11, PAF), "Hyperliquid perps", `SİM` rozeti.
2. **Kasa kartı:** sanal kasa $ (v3, 1.000 $ ölçeğinde; birim sözleşmeye göre), başlangıçtan $ ve % değişim, küçük kasa eğrisi (son 1–3 gün).
3. **Özet kutuları:** Nakit (serbest teminat) · Açık teminat (işlem sayısı) · Açık K/Z (gerçekleşmemiş) · Bugün (açılan/kapanan sayısı) ·
   Yatırılan · İşlem başı tutar · Son 24 sa işlem sayısı + kazanma oranı · Oda/kadro doluluğu.
4. **Açık işlemler tablosu:** coin · yön/kaldıraç rozeti (L/S + x) · trader kısa adresi · yaş (dk/sa) · likidasyona uzaklık % · teminat $ ·
   büyüklük $ · K/Z $ · K/Z %. Alt satır: TOPLAM. Uzun liste "+N işlem daha" ile kısaltılır.
5. **Son kapananlar:** coin · rozet · kapanış nedeni (trader kapattı / azalttı / yön değiştirdi / stop / tasfiye) · süre · trader · ana para · K/Z $ · K/Z %.
6. Renkler: kâr yeşil, zarar kırmızı; rakamlar sağa hizalı, TR biçimi (1.234,56).

## Teknik
- Tek statik HTML (+ küçük JS/CSS), çerçeve gerektirmez; GitHub Pages ile yayın. Telefon (≥ 360 px) ve PC'de düzgün (duyarlı düzen;
  telefonda tablo kartlara dönüşür ya da yatay kaydırma yerine sütunlar kısalır).
- Veri `raw.githubusercontent.com` üzerinden okunur (repo herkese açık); anahtar/secret yok.
- Tazelik: `uretildi` 2 saatten eskiyse üstte sarı uyarı.
- Kabul: gerçek `durum.json` ile telefon ve PC ekran görüntüsü PR'da; sayılar motor alanlarıyla birebir (rastgele 5 işlem elle karşılaştırılır).

## Panonun ihtiyaç duyduğu motor alanları (eksikse A4/Faz 2 işinde eklenir, sözleşmeye yazılır)
- Açık kopya pozisyonu başına: coin, yön, kaldıraç, teminat $, büyüklük $, giriş/son fiyat, K/Z $ ve %, likidasyona uzaklık, açılış zamanı, kaynak trader.
- Kapanan kopya işlemi başına: `kapanan_islemler` (A2 PR‑1) + kapanış nedeni.
- Kol/takım toplamları: nakit, açık teminat, açık K/Z, bugün açılan/kapanan, son 24 sa işlem ve kazanma oranı.
