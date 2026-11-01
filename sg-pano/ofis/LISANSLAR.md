# Ofis · varlık kaynakları ve lisanslar

**Sonuç: dış görsel varlık yok.** Ofisin tüm görselleri (zemin, duvar, mobilya, ağaç, araba, kişi, simge) bu klasördeki JavaScript
kodunun çalışırken piksel piksel çizdiği, **bu iş için elle yazılmış** çizimlerdir. Hiçbir resim dosyası (PNG/WebP/SVG sprite sayfası)
indirilmedi ya da kopyalanmadı; bu yüzden üçüncü taraf lisans yükümlülüğü yoktur.

| Varlık | Kaynak | Lisans |
|---|---|---|
| Zemin dokuları (çim, balıksırtı parke, halı, fayans/seramik, metal ızgara, güverte, taş, su, asfalt) | `sprites.js` içinde kodla üretilir (gürültü + desen kuralları) | Bu reponun kendi içeriği |
| Duvar, cam bölme (avluya bakan cam galeri dâhil), pencere, giriş | `sprites.js` | Bu reponun kendi içeriği |
| Mobilya ve küçük işlev nesneleri (masa, monitör, raf, sunucu dolabı, kasa, tezgâh, semaver, koli, şezlong, şemsiye, vb.) | `sprites.js` | Bu reponun kendi içeriği |
| Ağaçlar, çalılar, arabalar, park lambası, tabela | `sprites.js` | Bu reponun kendi içeriği |
| Kişi figürleri, sandalye, balon simgeleri, zarf/para/kutu | `kisiler.js` | Bu reponun kendi içeriği |
| Duvar ekranlarının içeriği (eğri, çubuklar) | `office.js` — çalışma anında veriden çizilir | Bu reponun kendi içeriği |
| Arayüz simgeleri (logo, ışık simgesi, kilit) ve menü elmasları | Sayfa içinde elle yazılmış SVG yolları ve CSS `clip-path` (`index.html`, `ofis.css`, `panel.js`) | Bu reponun kendi içeriği |
| Bilgi kutusu, ayarlar penceresi, oda içi geçiş, iletişim işaretleri (zarf, not, ok, bayrak, gülümseme balonu) | `bilgi.js`, `ad.js`, `iletisim.js`, `kisiler.js`, `ofis.css` — hepsi kodla (CSS + Canvas); simge dosyası yok | Bu reponun kendi içeriği |
| Olay kaynaklı kısa konuşma balonları | `dialogue.js` — Canvas 2D ile çalışma anında çizilir; dış görsel veya kaynak kod kopyası yok | Bu reponun kendi içeriği |
| Kullanıcı tıklamasına verilen karakter replikleri | `konusma.js` — Canvas 2D ile çalışma anında çizilir; özgün, kısa ofis replikleri | Bu reponun kendi içeriği |
| Replik ve ad metinleri (`replikler.json`, `kadro.json`) | Bu iş için yazıldı; sahte/uydurma örnek içerik | Bu reponun kendi içeriği |
| Sıcak iç ışık, ortam ışığı, su altı ışığı | `main.js` — çalışma anında Canvas gradyanlarıyla (PNG yok) | Bu reponun kendi içeriği |
| Yazı tipi | Sistem yazı tipleri (`ui-monospace` / `Segoe UI` / `Roboto` yığını); yazı tipi dosyası indirilmez | İşletim sistemine ait; dağıtılmaz |
| Kütüphane | Yok (saf JavaScript + Canvas 2D). CDN kullanılmaz | — |

Lisansı belirsiz varlık kullanılmadı. Telif konusunda şüphe doğarsa bu belgeye değil önce kodun ilgili işlevine bakın: her çizim
`sprites.js` / `kisiler.js` içinde okunabilir hâldedir.

## Etre V2 ile ilişki
`/tmp/etre-review.APFwx6` içindeki GPL-3.0 lisanslı Etre V2 yalnız etkileşim/estetik referansı olarak incelendi (kişi hareketi, konuşma balonu,
oda gezintisi). `dialogue.js` ve bu ofisteki diğer kod, Etre kaynak dosyalarından kopyalanmadı veya uyarlanmadı; Etre görseli, atlası, ekran görüntüsü
ve trading/API/eylem kodu alınmadı. Bu nedenle Etre kodu veya varlığı dağıtıma eklenmemiştir; Etre'nin GPL-3.0 lisansı bu dosyaların lisansı değildir.
Özgün renderer ve lisans kaydı bu repoda kalır.

## Taslak 1 ile ilişki (kopya değil, kendi tarzımız)
`sg-arge/arastirma/etre/` yalnız **tarz** referansı olarak okundu. Etre'nin hiçbir görseli, çizimi ya da ekran görüntüsü parçası ofis sayfasına
alınmadı, üzerinden çizilmedi, iz sürülmedi. (Etre karşılaştırma görseli yalnız #18 dalında, lider karşılaştırması içindir; sayfanın parçası değildir.) Oda sırası ve içerikleri `sg-arge/docs/GOREV_D_YOLU.md` Roller tablosundan (14 oda) çıkarıldı.

Adım 0 (özgünleştirme) ile bilinçli farklar:
- **Bina biçimi:** tek dikdörtgen blok yerine, ortasında **avlu ve havuzlu bahçe** olan iki kanatlı yapı (kuzey kanat: Makam…Arşiv + Tarama/Çay/Lab/Kontrol; güney kanat: Aday, Oda, Kapı;
  doğu ucu cam galeri duvarı, batı ucu çit). Kanatlar avludaki taş yollarla bağlanır; figürler yalnız bu yollardan yürür.
- **Çevre:** sol altta açılı otopark yok. Otopark kuzeydoğuda, yola bitişik, düz ve kenara dik park yerleriyle; giriş doğuda yaya meydanı.
- **Gezinme ve etiketler:** üst çubuk (sekmeler, "SİM/TELEGRAM AÇIK" çipleri, vardiya, "Ofis tam ekran") kaldırıldı; sol **dikey menü** (Bina / Hat / Destek grupları, oda renginde elmas simgeler),
  durum plakaları ("kayıt kipi", "haber hattı", "ışık saati"), kesik köşeli koyu **plaka** etiketleri (krem kutular yok).
- **Palet:** koyu deniz-yeşili arayüz, aqua vurgu, kayısı ikinci renk; zeminler ve duvarlar buna göre yeniden seçildi.
- **Taslak 1'den (sg-pano #17) alınan fikirler** yalnız fikir olarak, kodla yeniden çizildi (Taslak 1'in PNG'si kullanılmadı): odalara **sıcak iç ışık**, **cam bölmeler**, **havuzlu bahçe**.
- **Zemin ve nesne çeşitliliği:** Makam balıksırtı parke, Denetim metal ızgara + sunucu ışıkları, Çay ocağı fayans + semaver, Sekreterlik/Haberleşme'de koliler.
- **Kaldırılan sahte hareket:** çaycı yürüyüşü ve ağaç sallanması. **Eklenmeyen oyunlaştırma:** kâr/zarar rengi, rozet, "en iyi" vurgusu yok.

## Varlık boyutu raporu (2026-10-28, sürüm 2 ilk 5 iş sonrası)
Hedef: toplam varlık ≤ 15 MB. Gerçekleşen: **sayfanın görsel varlık dosyası 0 bayt**; tüm sayfa (kod + stil + veri):

| Dosya | Boyut (bayt) |
|---|---:|
| `sprites.js` | 37 607 |
| `main.js` | 34 838 |
| `office.js` | 30 886 |
| `world.js` | 30 164 |
| `ornek_durum.json` | 28 865 |
| `ofis.css` | 22 894 |
| `bilgi.js` | 19 981 |
| `panel.js` | 12 873 |
| `kisiler.js` | 11 391 |
| `iletisim.js` | 10 189 |
| `index.html` | 9 519 |
| `kadro.json` | 9 450 |
| `px.js` | 9 171 |
| `replikler.json` | 6 685 |
| `ad.js` | 6 361 |
| **Toplam (gzip öncesi)** | **≈ 274 KB** |

Ağ üzerinden ≈ 80 KB (gzip). (Eski `kanit/` PR kanıt klasörü 2026-10-30 temizliğinde silindi; git geçmişinde.)
15 MB bütçesinin altındadır. (Etre karşılaştırma görseli #18 dalındadır; sürüm 2 dalına alınmadı.) Testler (`test/`) sayfayla yüklenmez.

**Sürüm 2b eki:** yeni dosyalar `cekmece.js` (≈ 4,6 KB) ve `ses.js` (≈ 2 KB); ses WebAudio ile kodla üretilir, ses dosyası yoktur. Dış varlık eklenmedi; görsel varlık dosyası hâlâ 0 bayt.
Tüm sayfa ≈ 313 KB (gzip öncesi).

