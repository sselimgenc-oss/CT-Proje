<!-- İkinci Claude hesabının raporu (PDF'ten metne çevrildi; içerik değiştirilmedi). -->
```text
Hyperliquid'e özgü trader seçimi kanıtı (kaynak
taraması, 14.11.2026)
Yalnız bilgi. Lider Opus; işçiler Sonnet; denetim Fable. Kanıt etiketleri: [hakemli] · [çalışma kâğıdı] ·
[birincil belge] (Hyperliquid dokümanı) · [veri sitesi] · [haber] · [blog]. Okuma düzeyi: (tam)
metin okundu · (özet) yalnız özet/genişletilmiş özet · (arama) yalnız arama sonucu görüldü.


Teknik olmayan özet (8 madde)

   1. Hyperliquid'de 15 aylık tüm işlemler incelendiğinde, sitenin arayüzünden elle işlem yapanlar
      toplamda yaklaşık 1,1 milyar $ kaybetmiş; kazanan taraf piyasa yapıcı botlar (+208 milyon $).
      Kaybın üçte ikisi ücretlerden geliyor.
   2. Bu büyük çalışmanın erişilebilen bölümünde "geçen dönemin kazananı bu dönem de kazanıyor
      mu?" sorusu sorulmuyor. Tam metne ağ engeli yüzünden ulaşılamadı.
   3. Hyperliquid'de "kâr eden cüzdanlar kâr etmeye devam ediyor mu" sorusunu doğrudan ölçen bir
      çalışma bulunamadı.
   4. Yakın tek kanıt: bazı cüzdanların işlemlerinden saniyeler sonra fiyat onların lehine gidiyor ve bu
      özellik 10 günden 10 güne kalıcı. Ama avantaj saniyelerle ve birkaç baz puanla ölçülüyor; geç
      kopyalayan birinin bundan pay alamayacağı makul bir çıkarım (ölçülmedi).
   5. Kâr eden cüzdan listeleri (Nansen, coinmarketman vb.) yalnız "şu an kim kârda" fotoğrafı
      veriyor; ileriye dönük test yok. Bir blogun 15 günlük kâğıt denemesinde "en iyi cüzdanları
      kopyalama" zarar etti (zayıf kanıt).
   6. Vault'larda kapanmış ve batmış olanların tek tek sayfaları görülebiliyor (tradingstrategy.ai kapalı
      vault'ları silmiyor, işaretliyor; tüm evrenin veri setinde olup olmadığı doğrulanmadı), ama
      "vault'ların yüzde kaçı zarar etti" diye yayımlanmış bir sayı bulunamadı; bunu biz API'den
      sayabiliriz.
   7. Vault kuralları birincil kaynaktan doğrulandı: lider kârın %10'unu alır, lider her an vault'un en az
      %5'ine sahip olmalı, kullanıcı vault'larında para 1 gün, HLP'de 4 gün kilitli. Liderin ve yatıranın
      gerçek getirisi arasındaki farkı ölçen bir çalışma bulunamadı.
   8. Sonuç: Hyperliquid'e özgü kanıt, bizim "geçmiş performansa bakarak seçim işe yaramıyor"
      bulgumuzla çelişmiyor ama onu doğrudan da kanıtlamıyor. Risk ölçütlerinin en kötüleri elediğini
      kendi testimiz gösteriyor; dış kanıt bunu yalnız grup düzeyinde destekliyor; kazananı seçtirdiğine
      dair kanıt yok. Vault, kopya gecikmesini ortadan kaldırır ama seçim sorununu çözmez; üstüne
      %10 kâr payı ve HLP'ye özgü manipülasyon riski ekler.


1. Jia, Moallemi, Wang, Zeng (2026): "Who Loses and Why?"

Kaynak: AFT 2026, LIPIcs 36:1–36:3, doi 10.4230/LIPIcs.AFT.2026.36 [hakemli konferans, (özet)].
Genişletilmiş özet PDF'i okundu. SSRN 7270041 tam metni bu oturumun ağ izin listesinde olmadığı için
erişilemedi.

Veri: Hyperliquid'in en çok işlem gören 10 perp sözleşmesi, 27.03.2025–30.06.2026, tam emir/işlem
kaydı, 729.540 aktif cüzdan.

Hangi grup kazanıyor:
 Grup                                         Net sonuç     Taker yürütme        Ücret             Likidite alma
                                                            maliyeti                               payı

 Arayüz (front-end) trader'ları — yazarlara   −1,11         2,43 bps             725 M$ (2,99      %85
 göre "ağırlıklı bireysel"                    milyar $                           bps)

 Algoritmik taker'lar                         ≈ başa baş    1,70 bps             55 M$ (2,17       %69
                                                                                 bps)

 Piyasa yapıcılar                             +208 M$       0,70 bps             50 M$ (0,16       %20
                                                                                 bps)


        Arayüz kaybının kanalları şöyle: gönüllü işlem −154 M$, net zorla çıkış −226 M$, ücret −725 M$.
        Likidasyonlar arayüz grubuna 344 M$'a mal oluyor; ADL 118 M$ geri veriyor.
        Üç grubun likidasyon hacminin %96'sı arayüz grubundan geliyor.

Kazananlar kazanmaya devam ediyor mu? Özette bulunamadı. Geçmiş kâra göre sıralama,
örneklem dışı test ya da beceri/şans ayrımı yok. HLP, copy trade ve vault'lar da özette geçmiyor.
Bunların tam metinde olup olmadığı bilinmiyor; doğrulamak için SSRN sayfasını kullanıcının kendi
tarayıcısında açması gerekiyor.

Bize anlamı: Kazananlar bir rol (piyasa yapıcı, düşük ücret, pasif emir). Bu rolün kazancı
kopyalanamaz; kopya ancak taker olarak ve gecikmeli yapılır. Kopyaladığımız trader'ların büyük
olasılıkla "arayüz/algoritmik taker" profilinde olduğunu varsayıyoruz (ölçülmedi). Bu gruplar ortalamada
ücret sonrası ancak başa baş ya da zararda. Bulgu grup düzeyinde ve betimsel; cüzdan düzeyinde
ileriye dönük bir sonuç vermiyor.


2. Hyperliquid'de performans kalıcılığı: başka kanıt var mı?

Ana sonuç: Geçmiş kâr liderlerinin ileriki dönemde kârlı kalıp kalmadığını Hyperliquid verisiyle test
eden hakemli makale, çalışma kâğıdı ya da yöntemi açık bir veri analizi bulunamadı.

        Zhai (2026), "Public Trader Identity: Adverse Selection and Return Predictability",
        arXiv 2608.04373, Baruch College [çalışma kâğıdı, (kısmi): sayılar gövde ve eklerden, Fable
        tarafından PDF'ten doğrulandı].
              Veri: Temmuz 2026, 147.113 cüzdan, 14,3 milyon agresif emir.
              Ölçü: cüzdanın agresif emirlerinin 10 saniyelik "markout" puanı, yani bilgi içeriği.
              Gerçekleşmiş kâr değil.
              Kalıcılık: bitişik 10 günlük pencerelerde Spearman ρ = 0,52 (akrana göre düzeltilmiş 0,62).
              En üst ondalık (D10) doğrulama penceresinde ham, hacim ağırlıklı 2,20 bps (kontrollü en
              üst yirmilik 3,11 bps); Aralık 2025 tekrarında ρ ≈ 0,47.
              Yorum: Hyperliquid'de bir şey kalıcı. Ama bu, saniyeler içinde sönen ve birkaç baz puanlık
              bir avantaj. Saniyelik, taker tarafı bir sinyal; kopya gecikmesi ve kaymanın bu farkı silmesi
              beklenir (çıkarım). Pozisyon tutan trader'ın getiri kalıcılığına dair bir şey söylemiyor.
        coinmarketman / HyperTracker kohortları [veri sitesi/blog, (tam)].
              Ömür boyu gerçekleşmiş kâra göre 8 kohort var (ör. "Money Printer" ≥ +1 M$).
              Yalnız anlık fotoğraf veriyor: kohortlar arası geçiş oranı ya da ileri getiri yok.
              Diğer coinmarketman yazıları açılmadı.
        Nansen Hyperliquid lider tablosu / "smart money" [veri sitesi, (arama)]: API ve rehber var;
        kalıcılık analizi bulunamadı.
        Hyperdash: taranamadı; kalıcılık analizi bulunamadı.
        HyprSwarm, "when copying smart money loses" [blog, (tam)].
              4.260 cüzdan izlenmiş, 435'i "elit" sayılmış; 19 kâğıt strateji ~15 gün denenmiş (Mart
              2026, risk-kapalı dönem).
              "Copy ELO Top-3" kazanma oranı %44, −50 $; "Top-10" %47, −68 $.
             Kısa dönem; puanın yalnız geçmiş veriyle hesaplanıp hesaplanmadığı belirsiz. Zayıf ama
             yön bizimle aynı.
      Kripto borsa copy trade, 90 gün (Binance/Bybit/MEXC) [blog, ikincil aktarım]. Liderlerin
      ~%97'si kendisi kârlıyken takipçiye kâr ettirenlerin oranı Bybit'te %40, Binance'te %72. Kalıcılık
      testi değil; birincil çalışma bulunamadı.
      ETRE raporundan (depomuz) [ikincil, iç]. İzlenen HL trader'larının izlemeye alınmadan önceki
      pozisyonları +%0,34; sonrakiler −%0,02 (n = 12.053). Listeye giriş anındaki hayatta kalma
      yanlılığının doğrudan örneği.
      Dune, Kaiko, Glassnode, Messari, Galaxy, Delphi: taranmadı; "hiç yok" denemez.


3. Hyperliquid vault'ları

3a. Kapanan/batan vault'lar dahil getiri dağılımı nereden alınır?

      Hyperliquid info API [birincil belge]: vaultSummaries ve vaultDetails uç noktaları (Chainstack
      belgesi).
             Her vault'un portfolio serisi ve isClosed bilgisi okunabiliyor.
             vaultSummaries 'in kapalı vault'ların tamamını listeleyip listelemediği doğrulanmadı. Tam
             evren için vault adreslerini işlem kayıtlarından (vault oluşturma olayları) toplamak
             gerekebilir.
      tradingstrategy.ai [veri sitesi, (tam)].
             HL vault sayfaları kapalı vault'ları siliyor değil, "Vault is permanently closed" diye
             işaretliyor.
             "Muhtemelen terk edilmiş" bayrağı ve "blacklisted" (pay fiyatı sıfırlaması) uyarısı veriyor.
             Getiriyi para giriş-çıkışlarından arındırıp pay fiyatı üzerinden, kâr payı sonrası "net" ve
             öncesi "gross" olarak veriyor.
             Toplu veri (JSON + Parquet) ücretli Pro planda; ücretsiz örnekler yalnız Ethereum.
             Kapalı HL vault'larının veri setinde olup olmadığı yazmıyor (doğrulanmadı).
      Apify "Hyperliquid Vault Analyzer" [veri sitesi, (arama)]: includeClosed filtresiyle kapalı
      vault'ları da tarıyor (ücretli, üçüncü taraf).
      web3-ethereum-defi "Hyperliquid vault benchmark" eğitimi [açık kaynak, (arama)]: kendi
      sayımımız için hazır kod örneği olabilir.
      "Vault'ların yüzde kaçı zarar etti / ortanca getiri" diye yayımlanmış istatistik:
      bulunamadı.

Örnek: tradingstrategy.ai'de "Hyperliquidity Trader (HLT)" vault'u ömür boyu net −%100, en büyük
düşüş −%100 ve "Blacklisted" (pay fiyatı sıfırlaması) bayraklı. Sayfa canlı: arama önbelleğinde 3 aylık
getiri pozitif görünürken 14.11'de Fable −%31,7 okudu. Yani kısa pencere getirisi hızla değişiyor; bu
nedenle örnek, "pencere seçimi tuzağı"nın kanıtı olarak değil, yalnız uyarı olarak verilmiştir. Kapalı
vault örneği: "Retardio's Hedge Vault" ("permanently closed", ömür boyu net −%72,4).

3b. Liderin getirisi ↔︎ yatıranın gerçek getirisi

      Ölçen çalışma bulunamadı.
      Mekanizmadan çıkan farklar şunlar (çıkarım, ölçüm değil):
          1. Yatıran kâr ettiğinde kârın %10'u lidere gider.
          2. Lider kendi payından kâr payı ödemez ve ayrıca bu %10'u alır.
          3. Vault'un pay fiyatı getirisi zaman ağırlıklı. Yatıranlar çoğunlukla iyi bir dönemden sonra
             girdiği için para ağırlıklı (gerçek) getiri bundan düşük olabilir. Bunu vault giriş-çıkış
             kayıtlarıyla ölçmek mümkün.
          4. Çekişte açık pozisyonlar kapanırken kayma oluşabilir (birincil belge bunu söylüyor).
3c. Birincil kaynaktan doğrulanan kurallar

     Kullanıcı vault kilidi 1 gün, HLP kilidi 4 gün [birincil belge: depositors].
     Lider kâr payı %10. Belgedeki örnek: 100 USDC yatırılır, vault ikiye katlanır; 200 − 10 = 190
     USDC çekilir [birincil belge: depositors, leaders].
            Kesintinin çekişte mi, yüksek su işareti ile mi, yatıran başına mı hesaplandığı belgede
            açıkça yazmıyor.
     Lider vault'un ≥ %5'ini her an tutmalı; bu oranın altına düşürecek çekiş yapamaz [birincil belge:
     leaders].
     Vault kapanmadan önce tüm pozisyonlar kapanır; kapanışta yatıranlar paylarını alır [birincil
     belge: leaders].
     Oluşturma ücreti ve en az yatırım: vault oluşturmak 10.000 USDC "gas" ücreti gerektirir (işlem
     ücretleriyle aynı şekilde protokole dağıtılır); lider vault'a en az 100 USDC yatırmalıdır [birincil
     belge: leaders; Fable doğruladı].
     HLP kâr payı almıyor [blog: eco.com; birincil belgede ayrıca doğrulanmadı].

3d. HLP olayları (birincil duyuru bulunamadı; haber ve araştırma siteleri)

     ETH 50x balina, 12.03.2025 [veri sitesi Arkham; haber The Block].
            Pozisyon > 300 M$; teminat çekildikten sonra likidasyon oldu; HLP ~4 M$ kaybetti.
            Ardından azami kaldıraç BTC'de 40x, ETH'de 25x'e indi; ertesi gün HLP'den > 130 M$
            çekildi.
     JELLY, 26.03.2025 [haber Cointelegraph; CoinGecko].
            ~6 M$'lık kısa pozisyon, HLP'ye devredilen pozisyonla manipülasyon.
            Doğrulayıcılar sözleşmeyi listeden çıkardı; vakıf etkilenen kullanıcılara ödeme sözü verdi.
            HLP pozisyonu sonunda ~703 k$ kârla kapandı. Başka haberlerdeki "12–13 M$ risk"
            rakamı doğrulanmadı.
            Dersi: zarar, doğrulayıcı müdahalesiyle önlendi.
     POPCAT, 12–13.11.2025 [haber Cointelegraph]: ~3 M$ ile 19 cüzdandan saldırı; HLP ~4,9 M$
     kaybetti; köprü çekişleri kısa süre durdu.
     2026 olayları: bu taramada bulunamadı.


4. "Riske göre seçim" ve "vault'a yatırım" için ne söylüyor?

Riske göre seçim:

     Hyperliquid'e özgü ileriye dönük bir "seçim işe yarıyor" kanıtı yok. Kalıcı olduğu gösterilen tek
     şey, kopyalanamayacak kadar kısa ömürlü saniyelik bilgi.
     Kazanan grup (piyasa yapıcılar) rol olarak kazanıyor; bu kazanç ücret yapısından ve pasif
     emirden geliyor, kopyalanamıyor.
     Kaybettiren kanallar (taker maliyeti, ücret, zorla kapanış) ise ölçülebilir. Bu yüzden riske dayalı
     ölçütler (kaldıraç, likidasyona yakınlık, taker payı, devir hızı) eleme için gerekçeli görünüyor;
     ancak bu dış kanıt grup düzeyinde ve betimsel, cüzdan düzeyinde ileriye dönük eleme kanıtı
     değil. Dayanağı esasen kendi testimiz: turda bulduğumuz "yüksek devir/kaldıraç profili
     kaybettiriyor" sonucuyla ve vetoların en kötüleri ayıklamasıyla uyumlu.
     Bunlarla kazananı seçmek ise kanıtlı değil.
     REVIZYON_1 ileri testleri (T12–T16) bu açığı kapatacak tek doğrudan ölçüm olmaya devam
     ediyor.

Vault'a yatırım:

     Artıları:
           Kopya gecikmesi ve atlanan emir sorunu yok, çünkü aynı hesap.
           Lider kendi parasının en az %5'ini aynı vault'ta tutuyor.
           Kayıtlar herkese açık.
           Kilit kısa: 1 gün.
    Eksileri:
           Seçim sorunu aynen sürüyor: vault sıralaması da geçmiş getiri sıralaması. Batan
           vault'ların sıralamada nasıl ele alındığı doğrulanmadı; kısa pencere getirisi ile ömür boyu
           sonuç birbirinden çok farklı olabiliyor (HLT örneği).
           Kârın %10'u lidere gidiyor.
           Yatıranın para ağırlıklı getirisi ölçülmemiş.
    HLP farklı bir ürün: trader seçimi değil, piyasa yapıcı ve likidasyon karşı tarafı (benzetme: Jia ve
    ark.'daki "kazanan rol"e benziyor; özet HLP'den söz etmiyor). Ama manipülasyon saldırılarında
    zarar edebiliyor ve 4 gün kilitli.
    Önerilen ölçüm (yalnız öneri, karar kullanıcının): Hyperliquid info API ile tüm vault'ları (kapalılar
    dahil) çekip şunları saymak:
           (i) ömür boyu net getiri dağılımı,
           (ii) "geçen 90 günün en iyi %10'u" sonraki 90 günde ne yaptı,
           (iii) giriş-çıkış kayıtlarıyla para ağırlıklı yatıran getirisi.
           Salt okuma; walk-forward düzeneğinin vault uyarlaması.


5. Sınırlamalar ve denetim

    SSRN, Dagstuhl açılış sayfası, Hyperdash, Dune ve bazı tradingstrategy.ai sayfaları oturumun ağ
    izin listesi dışında kaldı. Bulgular özet ve arama sonuçlarıyla sınırlı.
    HLP olayları birincil Hyperliquid duyurusuyla doğrulanamadı.
    Denetim (Fable, 14.11): Jia özetindeki tüm sayılar, Zhai sayıları ve lider belgesindeki kurallar
    kaynakla aynı bulundu. Düzeltilenler: Zhai başlığı, HLT örneği (canlı sayfa farklı), oluşturma ücreti
    satırı, abartılı çıkarımlar (özet 4/6/8, §1, §4). Kilit süreleri ve 190 USDC örneği Opus tarafından
    depositors sayfasından okundu, Fable ayrıca bakmadı.


Kaynaklar

    Jia ve ark. (2026), genişletilmiş özet: https://drops.dagstuhl.de/storage/00lipics/lipics-vol395-aft2
    026/LIPIcs.AFT.2026.36/LIPIcs.AFT.2026.36.pdf
    Aynı çalışmanın SSRN sayfası (erişilemedi): https://papers.ssrn.com/sol3/papers.cfm?abstract_id
    =7270041
    Zhai (2026): https://arxiv.org/abs/2608.04373
    coinmarketman kohortları: https://coinmarketman.com/blog/pnl-based-trader-classification-why-
    performance-matters-more-than-size-on-hyperliquid--en/
    Nansen HL lider tablosu API: https://docs.nansen.ai/api/hyperliquid-apis/hyperliquid-leaderboard
    HyprSwarm: https://hyprswarm.pages.dev/news/when-copying-smart-money-loses/
    KuCoin (ikincil, 90 gün): https://www.kucoin.com/blog/is-crypto-copytrading-profitable-in-2026
    HL vault yatıran belgesi: https://hyperliquid.gitbook.io/hyperliquid-docs/hypercore/vaults/for-vaul
    t-depositors
    HL vault lider belgesi: https://hyperliquid.gitbook.io/hyperliquid-docs/hypercore/vaults/for-vault-l
    eaders
    vaultSummaries: https://docs.chainstack.com/reference/hyperliquid-info-vaultsummaries.md
    vaultDetails: https://docs.chainstack.com/reference/hyperliquid-info-vault-details.md
    tradingstrategy.ai HLT: https://tradingstrategy.ai/vaults/hyperliquidity-trader-hlt
    tradingstrategy.ai kapalı vault örneği: https://tradingstrategy.ai/vaults/retardio-s-hedge-vault
tradingstrategy.ai veri setleri: https://tradingstrategy.ai/trading-view/vaults/datasets
Apify vault analizcisi: https://apify.com/bb-tradetec/hyperliquid-vault-analyzer
Vault benchmark eğitimi: https://web3-ethereum-defi.readthedocs.io/tutorials/hyperliquid-vault-b
enchmark.html
ETH balina: https://info.arkm.com/research/hyperliquid-whale-passes-4m-loss-to-hlp-vault · http
s://www.theblock.co/amp/post/345866/hype-drop-hlp-vault-loss-hyperliquid-whale-liquidation
JELLY: https://cointelegraph.com/news/hyperliquid-delists-jelly-perps-citing-suspicious-activity · ht
tps://www.coingecko.com/learn/hyperliquid-hlp-vault-analysis
POPCAT: https://cointelegraph.com/news/hyperliquid-hlp-popcat-attack-3m-wipeout
HLP ücretsizliği (blog): https://eco.com/support/en/articles/15197987-hyperliquid-vault-strategies
-2026-hlp-and-user-vaults-explained
Dahili: arastirma/dis_inceleme/dunya/RAPOR.md , arastirma/dis_inceleme/etre/RAPOR.md ,
docs/KARARLAR.md K-65
```
