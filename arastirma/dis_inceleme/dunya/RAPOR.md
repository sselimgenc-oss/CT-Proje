# Dünyada copy trade'de trader nasıl seçiliyor? (kaynak taraması, 14.11.2026)

Yalnız bilgi. Her kaynak arama sonuçlarında varlığı doğrulanarak yazıldı; tam metni okunamayanlar "özetten" diye işaretlendi.
Kanıt düzeyi: [hakemli] / [çalışma kâğıdı-tez] / [platform-blog].

## Kısa özet
1. Pratikte üç seçim tarzı var: (a) platform sıralaması/popülerlik, (b) "kural listesi" (en az 6–12 ay geçmiş, düşüş < %20, düşük kaldıraç, çeşitlendirme), (c) risk-normalize puanlama (Darwinex).
2. Popülerlik ile performans arasında ilişki zayıf; insanlar çoğunlukla popüler olanı kopyalıyor.
3. Kopyalama imkânı insanları daha fazla risk almaya itiyor (laboratuvar deneyi).
4. Beceri gerçekten var ama çok nadir: Tayvan gün içi trader'larında geçen yılın en iyileri ertesi yıl da kazandı, ancak ücret sonrası kalıcı kazanan nüfusun %1'inden az.
5. Hyperliquid'de para transferinin ana kanalları: anlık işlem isteği (taker), zorla kapanış (likidasyon) ve ücretler. Kaybeden taraf çoğunlukla elle işlem yapan bireyler.
6. Kripto copy platformlarında lider kendisi kâr etse bile takipçinin kâr etmesi çok daha az (doğrulanmamış rakamlar).
7. Akademik kanıt az ve çoğu eski. En doğrudan olanı (Dorfleitner ve ark. 2018): en yüksek getiriye göre seçmek kaybettiriyor, riske göre getiri (Sharpe) ile seçmek iyileştiriyor. Kripto copy için büyük, güncel ve bağımsız bir ileri test bulunamadı.

## 1. Pratikteki yöntemler
- **Platform sıralaması / popülerlik (eToro, Binance, Bybit, Bitget).** Takipçi sayısı, getiri, kazanma oranı. eToro üzerinde büyük ölçekli çalışma: kullanıcılar kimi kopyalayacağını çoğunlukla popülerliğe göre seçiyor ve bu, gerçek performansla zayıf ilişkili [çalışma kâğıdı, arXiv 2507.01817, Joseph, Riedl, Pentland & Moro (2025); özetten]. Ayrı bir eToro ağı çalışması: liderin takipçi kazanması, getiri kadar iletişim/paylaşımla da ilgili [Deng, Yang, Pelster, Tan; çalışma kâğıdı → Information Systems Research].
- **Kural listesi (broker/borsa rehberleri).** Ortak eşikler: ≥ 6–12 ay doğrulanmış geçmiş (tercihen farklı piyasa dönemleri), en büyük düşüş < %20, aşırı kaldıraçtan kaçınma, getirisi tek dönemde toplanmamış olma, birkaç trader'a dağıtma, zaman ufku uyumu. Kaynaklar çıkar sahibi (borsa/broker); eşikler kanıtlanmış standart değil, alışkanlık [platform-blog: Binance, BitMEX, Pepperstone vb.].
- **Risk-normalize puanlama (Darwinex).** Her trader'ın stratejisi aynı risk hedefine (aylık en çok %6,5 VaR) çekilerek karşılaştırılıyor; 12 "yatırılabilir özellik": deneyim (veri anlamlılığı, 12 dönemde dolar), risk istikrarı, pozisyon başına risk ayarı, getiri/süre tutarlılığı, performans, kapasite… D-Score 5 yıllık getiri eğrisinin kalitesi [platform belgesi: help.darwinex.com]. Bu yöntemin ileriye dönük başarısını gösteren bağımsız çalışma bulunamadı.

## 2. Kanıt: seçim ileride işe yarıyor mu?
- **Apesteguia, Oechssler, Weidenholzer (2020), "Copy Trading", Management Science 66(12) 5608–5622** [hakemli; deney]. Başkalarının başarısını görmek risk almayı artırıyor; doğrudan kopyalama imkânı bunu daha da artırıyor → aşırı risk.
- **Oehler, Horn, Wendt (2016), wikifolio sertifikaları, International Review of Financial Analysis 46, 202–210** [hakemli]. 1.084 sosyal trade portföyü, faktör modelleriyle getiri/alfa. Bulgunun ayrıntısı bu taramada doğrulanamadı (tam metin açılamadı).
- **Barber, Lee, Liu, Odean (2014), "The Cross-Section of Speculator Skill", Journal of Financial Markets 18** [hakemli]. Tayvan gün içi trader'ları 1992–2006: geçen yılın en iyi 500'ü ertesi yıl günde ~38 bps (ücret sonrası) kazanıyor; en kötüler kaybetmeye devam. Ancak güvenilir şekilde kazananlar nüfusun %1'inden az. Ders: geçmiş performans *çok büyük ve uzun* veride biraz bilgi taşıyor; az adayla ve kısa pencerede bu sinyal gürültüde kayboluyor (bizim bulguyla uyumlu).
- **Jia, Moallemi, Wang, Zeng (2026), "Who Loses and Why? Market Microstructure of Perpetual Futures", AFT 2026 (LIPIcs), doi 10.4230/LIPIcs.AFT.2026.36** [hakemli konferans; genişletilmiş özet, tam metin SSRN'de]. Hyperliquid'in en çok işlem gören 10 sözleşmesi, 27.03.2025–30.06.2026 tam emir/işlem kaydı: bireyler defterin pahalı (aceleci, taker) tarafında kaybediyor; para transferinin kanalları anlık işlem, zorla kapanış ve ücretler. (Cüzdan sayısı ve ayrıntılar yalnız ikincil kaynakta görüldü.)
- **Kripto copy platformları (Binance/Bybit/MEXC) 90 günlük çalışma** [platform-blog, doğrulanmamış; KuCoin blogu]: liderlerin büyük çoğunluğu kendisi kârlıyken, takipçisine kâr ettirenlerin oranı ~%44. Kaynak rakip borsa; yöntem görülmedi.
- **Hyperliquid vault'ları.** tradingstrategy.ai gibi siteler, ömür boyu −%86…−%97 kaybetmiş vault'ları da listeliyor → batan vault'ları görmek mümkün görünüyor (hayatta kalma yanlılığını ölçmek için kullanılabilir). Kullanıcı vault'larında lidere %10 kâr payı [platform-blog].

## 3. Bize anlamı
- Bizim walk-forward sonucu ("geçmişe bakarak seçim rastgeleden iyi değil") literatürle çelişmiyor: beceri var ama çok nadir ve ancak çok büyük/uzun veriyle seçilebiliyor. Ancak destek dolaylı: Tayvan hisse verisi farklı piyasa, farklı dönem.
- Sosyal trade'de doğrudan kanıt: en yüksek birikimli getiriye göre seçmek kaybettiriyor, Sharpe (riske göre getiri) ile seçmek sonucu iyileştiriyor; takipçi sayısı getiriyle ilişkili değil (Dorfleitner ve ark. 2018). Lider olmak davranışı bozabiliyor: takipçi kazanan trader zararı kapatmamaya daha eğilimli (Pelster & Hofmann 2018).
- Dünyada yaygın yöntemler (sıralama, kural listesi) ileriye dönük olarak kanıtlanmış değil; çıkar sahibi kaynaklardan geliyor.
- Darwinex'in risk-normalize yaklaşımı bizim için farklı bir fikir: trader'ı *seçmekten çok*, kopyalanan riski sabit bir hedefe çekmek (kaldıracı trader'a göre değil hedef riske göre ayarlamak). Getiriyi artırdığı kanıtlı değil; riski düzenler.
- Hyperliquid çalışması bireylerin taker tarafında sistematik kaybettiğini gösteriyor; maker tarafa geçmenin bizim ölçekte kazandıracağını göstermiyor (maker kârı altyapı ister). Yalnız taker maliyetini seçim/maliyet ölçütüne eklemenin gerekçesi sayılabilir.
- Vault yolu için batanları da gösteren bir veri kaynağı var gibi; Fable'ın "kör nokta D" sayımı yapılabilir.

## 4. Sınırlamalar
- Ağ kısıtı yüzünden arXiv ve RePEc sayfaları açılamadı; bazı bulgular arama özetlerinden.
- Forum/Reddit deneyimleri bu taramada bulunamadı (arama broker rehberlerine düştü).
- "Şu yöntemle seçilen trader ileride kazandırdı" diyen bağımsız, büyük, güncel bir *kripto* çalışması bulunamadı (sosyal trade için Dorfleitner ve ark. 2018 var).
- Denetim (Fable): 5 ana kaynak doğrulandı; Oehler, Deng ve KuCoin rakamları ayrıca aranmadı.

## Kaynaklar
- Apesteguia, Oechssler, Weidenholzer (2020): https://bse.eu/research/publications/copy-trading · doi 10.1287/mnsc.2019.3508
- Oehler, Horn, Wendt (2016): https://fis.uni-bamberg.de/handle/uniba/41492 · doi 10.1016/j.irfa.2016.05.007
- Barber, Lee, Liu, Odean (2014): https://faculty.haas.berkeley.edu/odean/papers/day%20traders/Day%20Trading%20Skill%20110523.pdf
- Jia, Moallemi, Wang, Zeng (2026): https://drops.dagstuhl.de/entities/document/10.4230/LIPIcs.AFT.2026.36
- eToro popülerlik–performans: https://www.arxiv.org/pdf/2507.01817
- Deng, Yang, Pelster, Tan: https://wiwi.uni-paderborn.de/fileadmin-wiwi/cetar/TAF_Working_Paper_Series/TAF_WP_074_DengYangPelsterTan2023_rev.pdf
- Dorfleitner ve ark. (2018), "To follow or not to follow – An empirical analysis of the returns of actors on social trading platforms", Quarterly Review of Economics and Finance 70, 160–171
- Pelster & Hofmann (2018), Journal of Banking & Finance 94, 75–88
- Darwinex yatırılabilir özellikler: https://help.darwinex.com/what-are-investable-attributes · https://help.darwinex.com/d-score
- Binance lider seçim rehberi: https://www.binance.com/blog/futures/copy-trading-essential-criteria-for-selecting-lead-traders-5061215295703009149
- KuCoin (doğrulanmamış 90 gün çalışması): https://www.kucoin.com/blog/is-crypto-copytrading-profitable-in-2026
- Vault örnekleri: https://tradingstrategy.ai/vaults/hyper-3
