# Riske göre seçim (Sharpe / istikrar) ileriye dönük işe yarıyor mu? (14.11.2026)

Yalnız bilgi. Kaynakların varlığı aramayla doğrulandı; tam metni okunamayanlar "özetten" diye işaretli.
Kanıt düzeyi: [hakemli] / [çalışma kâğıdı-tez] / [platform-blog].

## Kısa özet
1. Sosyal trade'de en doğrudan kanıt (Dorfleitner ve ark. 2018): en çok kazanana göre seçim ağır kaybettiriyor; Sharpe'a göre seçim sonucu iyileştiriyor; yalnız sağlayıcının portföy riskini de hesaba katan stratejiler pozitif getiri veriyor. Ancak işlem maliyeti sonrası, faktör modeline göre hiçbir strateji anormal getiri üretmiyor.
2. Çok aktif işlem yapan sağlayıcıların getirisi daha düşük; takipçi sayısı ve yatırılan para gelecek performansı göstermiyor.
3. Fonlarda: Sharpe sıralaması kısa vadede biraz kalıcılık gösterebiliyor; uzun vadede kanıt karışık. CTA'larda geçmiş performansa göre yönetici seçmek ileride üstün sonuç vermemiş.
4. Bireysel yatırımcıların riske göre performansının dönemler arası korelasyonu düşük (~%10) ama sıfır değil: aynı çalışmada üst dilim sonradan da kazanıyor.
5. Sosyal trade, kalibre edilmiş bir teorik modelde bireyin beklenen kaybını ~%5,1 artırıyor (Bundesbank tartışma kâğıdı; ampirik kopya ölçümü değil).
6. Özet hüküm: risk bilgisini kullanmak tek çalışmada (Dorfleitner) "kaybı azaltıyor"; maliyet sonrası "kazandırdığı" kanıtlanmış değil.

## 1. Bulgular
- **Dorfleitner ve ark. (2018), Quarterly Review of Economics and Finance 70, 160–171** [hakemli; özetten]. Sosyal trade platformu verisi. En yüksek birikimli getiriye göre seçim büyük kayıp; Sharpe dikkate alınınca getiri artıyor; yalnız sağlayıcının portföy riskini kullanan "sofistike" stratejiler pozitif getiri. İşlem maliyeti sonrası Carhart 4 faktör modelinde hiçbir stratejide pozitif anormal getiri yok. Yüksek işlem aktivitesi getiriyle negatif ilişkili; takipçi sayısı ve yatırılan sermaye daha iyi performansı öngörmüyor.
- **Handy & Meksi (2025), "Blinded by Bias", Journal of Wealth Management 28(1)** [hakemli; özetten; yazarlar bir CTA fon-fonu şirketinde çalışıyor, çıkar ilişkisi olabilir]. CTA'larda geçmiş üstün performansa göre yönetici seçmek ve portföy kurmak gelecekte üstün performans getirmiyor.
- **Journal of Derivatives & Hedge Funds (2009)** [hakemli; özetten]. Sharpe ve aşağı yönlü risk türevleri, kalıcılığı yakalamada faktör ölçülerinden daha hassas; hedge fon kalıcılığı kanıtı karışık.
- **Coval, Hirshleifer & Shumway, "Can Individual Investors Beat the Market?" (çalışma kâğıdı 2002; Review of Asset Pricing Studies 2021)** [hakemli; özetten]. Riske göre performansın dönemler arası korelasyonu ~%10; üst dilim sonraki dönemde de piyasayı yeniyor.
- **Russ (2025), Bundesbank tartışma kâğıdı 29/2025** [çalışma kâğıdı; teorik model]. Kalibre edilmiş modelde sosyal trade, bireyin beklenen kaybını ~%5,1 artırıyor.
- **Kakhbod, Kazempour, Livdan, Schürhoff, "Finfluencers" (SFI 23-30 / CEPR DP 20204)** [çalışma kâğıdı; özetten]. Becerisiz ve "ters becerili" sosyal medya yatırım fenomenlerinin daha çok takipçisi ve etkisi var.

## 2. Bizim testimizle ilişki
- Walk-forward'daki t sıralaması (`copytrade/secim_d.py`), 12 haftalık ham haftalık Sharpe sıralamasına eşdeğer (×√12): trader'ın kendi perp pnl'i / hafta başı hesap değeri; kopya maliyeti ve funding yok; para giriş-çıkışı düzeltilmemiş; yalnız kapıları geçenler arasında ilk 5. Test edilen şey kapılar + sıralama birlikteydi; **Sharpe'ı tek başına sınamadık.**
- Dorfleitner'in olumlu etkisi "en çok kazanana göre seçim"e kıyasla; rastgele kontrole göre değil. Bizim kıyasımız daha sert.
- Dorfleitner'in "portföy riskini kullanan strateji" bulgusu ile Darwinex'in risk normalizasyonu (aylık en çok %6,5 VaR hedefi; bkz. dunya/RAPOR.md) aynı yöne bakıyor: trader'ı seçmekten çok, kopyalanan riski sabit tutmak. Bunu bizim veride ayrıca denemedik.
- "Çok aktif işlem kötü" bulgusu bizim devir kapısıyla uyumlu.
- Genel hüküm değişmiyor: hiçbir seçim yöntemi maliyet sonrası güvenilir kazanç kanıtı vermiyor; riske dayalı yöntemler (tek çalışmada) en fazla zararı azaltıyor.
- Denetim (Fable): künyeler doğrulandı; Dorfleitner bulgularının ayrıntısı ve JDHF 2009 tam doğrulanamadı.

## 3. Sınırlamalar
- Tam metinler (ScienceDirect, Springer) okunamadı; sayısal ayrıntılar özetlerden.
- Kripto/Hyperliquid'e özgü riske göre seçim çalışması bulunamadı.

## Kaynaklar
- Dorfleitner, Fischer, Lung, Willmertinger, Stang, Dietrich (2018): https://epub.uni-regensburg.de/37172/ · doi 10.1016/j.qref.2018.04.009
- Handy & Meksi (2025): https://a-us.storyblok.com/f/1022432/x/7604212f92/blindedbybias_journal-of-wealth-management-2025.pdf
- JDHF (2009): https://link.springer.com/article/10.1057/jdhf.2009.11
- Russ (2025), Bundesbank: https://www.bundesbank.de/en/publications/research/discussion-papers/social-trading-correlated-retail-investing-and-non-fundamental-speculation-967886
- Finfluencer: https://afajof.org/management/viewp.php?n=119896
- Coval, Hirshleifer, Shumway: https://sites.uci.edu/dhirshle/files/2019/06/Can-individual-investor-beat-the-market_0718_CHS.pdf
