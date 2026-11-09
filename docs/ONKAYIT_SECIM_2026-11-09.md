# Ön kayıt: trader seçim + değiştirme yapısı adayları (09.11.2026)

Yazan: Fable 5.1 (yüksek), bağımsız tasarımcı. Kalıcılık testi (`kalicilik.yml`) sonucu GÖRÜLMEDEN yazıldı ve commit edildi (K-54). **Bu belgedeki eşikler, N'ler, sıklıklar ve karar kuralı sonradan değiştirilmez**; değişiklik = yeni aday, yalnız ileri haftalarla sınanır.

## 0. Çerçeve
- Amaç yeni yapıyla **yeni trader bulmak**; hiçbir aday eski radar havuzuna (679 adres) ya da v1 R0'nun "7 g getiri kuyruğu"na dayanmaz. Her aday evrenini lider tablosunun TAMAMINDAN kendi ölçüsüyle kurar.
- Lider tablosunun geçmişi yok; HL `portfolio` (1 çağrı, ağırlık 20) `allTime`/`month`/`week` **pnlHistory + accountValueHistory** verir → t haftasına kadarki noktalarla 30/60/90 g getiri, haftalık pnl dizisi ve düşüş **lookahead'siz** hesaplanır. Lider tablosunun bugünkü sayıları yalnız **adres listesi** için kullanılır.
- Kalıcılık testi (679 adres) yalnız eski yapının teşhisidir; aday seçimine girdi olmaz.

## 1. Adaylar
Ortak: kasa 1.000 $, boş koltuk nakitte, R4 risk/şalterler aynen, kopya oynatma `kopya_v5` tam maliyetli.

| | **A — v1.1 (kontrol)** | **B — Uzun pencere tutarlılığı** | **C — Kopya dostu stil (düşük devir)** | **D — Sabit kadro, yalnız risk çıkışı** | **E — Kopya sicili (4 haftalık kendi kopyamız)** |
|---|---|---|---|---|---|
| Hipotez | Son haftanın en iyileri + kopyalanabilirlik kapıları ileri getiri verir (bugünkü kural; kontrol). | Getiri kalıcılığı varsa 7 günde değil 12 haftada görünür: uzun pencerede istikrarlı kazanan sürer. | Kopyalayanın kazancı trader'ın getirisinden değil yürütme dostu stilden gelir (uzun tutma, düşük devir, az coin, ılımlı kaldıraç); getiri sırası gürültüdür. | Seçim becerisi ≈ 0 ise asıl maliyet devirdir: bir kez makul kapılarla seç, yalnız risk nedeniyle çıkar. | Tek anlamlı sinyal bizim kopyamızın o trader'da kazanıp kazanmadığıdır; 7 gün yerine 4 haftalık kopya sicili. |
| Evren | Lider tablosu `week` pnl/vlm/accountValue; hafta başı sermaye ≥ 10 k, 30 g pnl > 0; 7 g getiri ilk 300. | Adres listesi, hesap(t) ≥ 10 k (portfolio); portfolio allTime pnl eğrisi: son 12 haftanın ≥ 8'i pnl > 0, 90 g getiri = Δpnl/hesap(t−90g) > 0, 90 g pnl düşüşü ≤ %20 hesap. (~150–400) | Adres listesi, hesap(t) ≥ 10 k; ucuz kapı: aylık hacim/hesap ≤ 15 (test: t'den önceki 4 hafta dolum nosyoneli/hesap); 90 g pnl > 0 (akıl sağlığı, sıralama değil). (~300–600) | B'nin evren kapıları (yalnız kuruluş ve boş koltuk doldurmada). | Adres listesi, hesap(t) ≥ 10 k, 90 g pnl > 0; son 4 haftada ≥ 20 kapanmış işlem. (~400–800) |
| Kapılar (t'den önceki dolumlar) | R1/1–9 + kopya işlem ≥ 10 (v1.1). | Son 4 hafta: medyan tutma ≥ 1 sa, kaldıraç ≤ 20x, likit pay ≥ %80, devir ≤ 100/hf, 4 haftalık kopya getirisi > 0 ve koruma ≥ 0,5. | Son 4 hafta: medyan tutma ≥ 12 sa, aktif coin ≤ 8, kaldıraç ≤ 10x, kısa işlem payı ≤ %10, likit pay ≥ %90, kopya koruma ≥ 0,8, kapanmış işlem ≥ 8. | B kapıları. | 4 haftalık kopya (bizim boyutumuzla): getiri > 0, bootstrap alt %20 > 0, kopya işlem ≥ 20, koruma ≥ 0,5, kaldıraç ≤ 20x. |
| Sıralama | Form puanı (G/K/İ1/İ2/Y, H=0). | Haftalık pnl/hesap dizisinin t-istatistiği (12 hafta), azalan. | Devir artan (en düşük önce); eşitlikte uzun tutma. Getiriye göre sıra YOK. | Kuruluşta B sırası; sonra sıra yok. | 4 haftalık kopya t-istatistiği, azalan. |
| N / boş koltuk | 11; nakit (K-45). | 10; nakit. | 8 (slot 125 $); nakit. | 10; nakit. | 10; nakit. |
| Giriş/çıkış/değiştirme | Günlük; K-39 2 gün kadro dışı; histerezis; slot −%10; 72 sa işlem yok. | Haftalık (pazartesi 00:37 UTC) yeniden dengeleme: üye kapıdan düşerse ya da sırası > 2N olursa çıkar; yerine en iyi sıralı. Hafta içinde yalnız risk çıkışları. | Haftalık; yalnız kapı ihlalinde çıkış (sıra değişimi çıkış nedeni değil). | Çıkış yalnız: slot düşüşü ≥ %15, kaldıraç > 20x, 14 g işlem yok, trader hesabı zirveden ≥ %25 düşüş, 30 g pnl < 0 (iki aylık kontrolde üst üste). Boş koltuk aylık kontrolde dolar. Değiştirme yok. | Haftalık: 4 haftalık kopya getirisi < 0 → çıkar; boş koltuk sıradaki t'ye. 14 g bekleme aynen. |
| Risk değişikliği | — | — | Slot tavanı 2× (tek kişi ≤ kasanın %25'i). | Slot stop %15; coin tavanı %30 aynen. | — |
| Çekirdek parametre | 12+ | 7 | 8 | 6 | 6 |

Benzerlik kuralı ve net yön tavanı adaylara ek değildir; kazanan yapıda yalnız bilgi alanı olarak ölçülür.

## 2. Sınanabilirlik
- **Adres listesi:** lider tablosu (bugün) → `accountValue ≥ 10 k` ya da `allTime vlm ≥ 1 M $`; **pnl işareti filtresi yok**. Beklenen 5–10 k adres.
- **Aşama 1 (ucuz):** her adres için 1 `portfolio` → hesap(t), Δpnl 30/90 g, 12 haftalık pnl dizisi, zirveden düşüş; her t için yalnız t'ye kadarki noktalar. Lider tablosunun bugünkü `windowPerformances` değerleri ölçüye girmez (A'nın R0'u portfolio `week` pnl/hesap ile yaklaşık kurulur; raporlanır).
- **Aşama 2 (pahalı):** aşama 1'de herhangi bir adayın evrenine giren adreslerin 12 haftalık dolumları + saatlik mum; kapı/sıralama ölçüleri yalnız [t−4 hf, t) dolumlarından; sonuç [t, t+1 hf) kopya getirisi (gecikmesiz + tam maliyet, saatlik işaret; tüm adaylara eşit).
- **Yanlılıklar:** lookahead (tüm ölçüler t'den önce); survivorship (silinen hesaplar yok → tümü iyimser; mutlak seviye kararı ileri sanal haftalarla); yaklaşık kopya (ileri haftalarda gerçek 1 dk oynatma); çoklu test (eşikler burada donar).
- **İleriye dönük:** 10.11'den itibaren her hafta beş adayın seçimi gerçek zamanlı üretilip kaydedilir (`aday/<tarih>/secim.json`), sonraki hafta 1 dk gecikmeli gerçek oynatmayla ölçülür. En az 4 ileri hafta.

## 3. Karar kuralı (mekanik)
- **Birim:** 1.000 $ kasa; aday portföyü = o haftanın N üyesi, boş koltuk 0; haftalık kasa getirisi = Σ üye kopya getirisi (maliyet sonrası).
- **Birincil ölçü M1:** haftalık kasa getirisinin ortalaması ($/hafta), hafta bloklu bootstrap %80 aralığı (tohum 20261109); en az **12 hafta** (8 geriye + ≥ 4 ileri). İkincil: kazanan hafta oranı, en büyük düşüş, haftalık devir, boş koltuk oranı, A'ya göre fark.
1. **Eleme:** M1 %80 üst sınırı < 0 ya da M1 ortalaması < A'nın ortalaması → elenir.
2. Kalanlar arasında (aday − A) haftalık farkının Bonferroni düzeltmeli aralığı (4 karşılaştırma → her biri %95) alt sınırı > 0 olanlardan M1 en yüksek olan **kazanır**.
3. Hiçbiri 2'yi geçmiyor ama 1'den kalan varsa: sadelik sırası **D > B > C > E > A** ile en sade kalan seçilir.
4. A dahil hiçbiri 1'i geçmiyorsa (hepsinin ortalaması ≤ 0): **gerçek para yok**; 12 hafta daha yalnız sanal; ikinci turda da geçmezse kullanıcıya "lider tablosu kuyruğundan kopyada edge bulunmadı" raporu, proje yönü kullanıcı kararı.
- **Gerçek para kapısı:** kazanan ≥ 8 ileri sanal hafta; M1 %80 alt sınırı > 0 ve en büyük düşüş ≤ %15 → 1.000 $ gerçek para **önerilir** (karar kullanıcının). Alt sınır ≤ 0 → 8 hafta daha; üst sınır < 0 → yapı düşer, sıradaki aday (madde 3 sırası) sanalda denenir.

## 4. Sürdürülebilirlik
- Çekirdek parametre ≤ 8; hepsi `kurallar.yaml` `secim_*` anahtarlarında; kodda sayı yok.
- Değişiklik takvimi: **üç ayda bir**, yalnız M1 ile ve son 12 haftanın aynı ölçümüyle; aralarda dokunulmaz (hata düzeltmesi serbest, eski ↔ yeni yan yana).
- Her hafta tek otomatik iş, tek çıktı (`secim.json` + `olcum.json`), kullanıcı müdahalesi gerekmez.

## 5. Uygulama notu
- Harness: `copytrade/aday_evren.py` (`evren_lider_tablosu`, `portfolio_olculeri(portfolio, t_ms)` saf), `copytrade/aday_sinama.py` (`dolum_olculeri_4h`, `aday_sec`, `portfoy_getirisi`, `analiz_aday`, `ozet_md`); iş akışı `aday_sinama.yml`: aşama 1 portfolio (6 parça) → aşama 2 dolum (6 parça, ≤ ~650 adres/koşu; aşarsa aday başına koşu) → analiz; haftalık cron ile ileri seçim kaydı (`aday` dalı).
- API: aşama 1 ~8 k adres × 20 ağırlık ≈ 160 k → 6 parçada ~25 dk; aşama 2 ≈ 2,8 dk/adres.
- Kazanan yapıda değişecekler: `radar_tarama.py` (evren), yeni `aday_evren.py`, `radar_form.py`/`radar_kadro.py` (sıralama), `canli/kadro.py` (haftalık yeniden dengeleme; D için yalnız risk + aylık kontrol), `kurallar.yaml` (`secim_*`), `radar.yml` (haftalık), `VERI_SOZLESMESI.md`, testler. Motor yürütme/boyut kodu değişmez. Kurulan yapının kadrosu `radar_surum: v2` taşır (K-54).

## Ön kayıt özeti (sonradan değişmez)
1. Beş aday: A v1.1 (kontrol), B uzun pencere tutarlılığı, C kopya dostu düşük devir, D sabit kadro + yalnız risk çıkışı, E 4 haftalık kopya sicili; eşikler/N/sıklıklar §1'deki gibi donar.
2. Evren: lider tablosunun tamamı yalnız adres listesi (hesap ≥ 10 k ya da allTime vlm ≥ 1 M, pnl filtresi yok); tüm ölçüler t'den önceki portfolio/dolum verisinden; eski 679 adres kullanılmaz.
3. Birincil ölçü: haftalık kasa getirisi (1.000 $, N koltuk, boş koltuk 0, tam maliyet), hafta bloklu bootstrap %80, tohum 20261109; ≥ 12 hafta (8 geriye + ≥ 4 ileri).
4. Seçim: §3 madde 1–4 mekanik; A'ya üstünlük için Bonferroni (4 karşılaştırma, %95); ayrışmazsa sadelik sırası D > B > C > E > A; hepsi ≤ 0 ise gerçek para yok, 12 hafta sanal.
5. Gerçek para: kazanan ≥ 8 ileri sanal hafta, %80 alt sınır > 0 ve düşüş ≤ %15 → öneri; karar kullanıcının.
6. Sonuç görüldükten sonra eşik/evren değişikliği = yeni aday, yalnız ileri haftalarla sınanır. Değişiklik takvimi üç ayda bir, aynı ölçüyle.
