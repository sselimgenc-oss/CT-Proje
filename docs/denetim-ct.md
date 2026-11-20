# CT genel denetim — 20.11.2026

Kullanıcı onaylı genel denetim (düzen: sg-orkestra-sefi/DENETIM_PLANI.md). Taban: son 48 saat (c19015cb → main) + para yolu.
Yöntem: araç taraması (Haiku) → mutasyon testi (para yolunun küçük modülleri) → 5 modül incelemesi (Sonnet, her bulgu KIRMIZI testle) → temiz bağlamlı çürütme (2 Sonnet) → güven sınaması (yerel dalda 5 bilinçli hata, habersiz inceleyici).
Kırmızı testler ve ham raporlar oturum çalışma alanında (R1–R5, CURUTME_*, H0); düzeltme işlerinde testlere dönüştürülecek.

## Özet

| | Sayı |
|---|---|
| Doğrulanmış bulgu (benzersiz) | **19** — kritik 1 (düzeltildi), orta 5, düşük 13 |
| Çürütülen | 2 |
| Şüphe (testsiz) | 38 + araç bulguları |
| Güven sınaması | **2/5** (eşik 4/5 → hesap.py, borsa_stop.py, sert_sinirlar.py işaretlendi; Opus okudu) |
| Kullanıcı/Fable kararı gereken | 1 |

## Kritik — bulundu, hemen düzeltildi

**K1. Telafi stopla kapanan pozisyonu yeniden açıyordu** (motor.py `kacan_telafi`, K-75). Bizim stopumuzla (felaket / tasfiye koruması / iz süren / tasfiye) kapanan pozisyon, trader hâlâ açıkken aynı ya da sonraki senkronda yeniden açılıyordu; stoplar `son_atla`ya yazmıyor, lehte fiyatta kayma sınırı yoktu. Kâğıtta açık ve işleme etkili: EVET (yalnız sanal). Gerçek kip: etkisiz.
→ **#696** (20.11 14:39 TSİ): stop muafiyeti (trader kapatıp yeniden açana kadar), fiyat sınırı iki yönlü ±%1. Kırmızı testler yeşil.

## Orta

| # | Yer | Bulgu | Kâğıtta açık / işleme etkili |
|---|---|---|---|
| O1 | motor.py ~1219–1244 (`_emir_isle`, azaltma hedefi) | Ders / drift / gölge-B5 çarpanı (×0,5) yalnız açılışta uygulanıyor; azaltma tam slotla hesaplanıyor → yarım açılan pozisyon trader kısmi azaltınca küçülmüyor (`min_emir_atlandi`). İki inceleyici ayrı buldu. | Evet / evet (sanal; ders çarpanı gerçekte de) |
| O2 | hesap.py:206 (`from_json`) | Defter kaldıracı hesap.json'dan yükleniyor; yaml `canli_marj_kaldirac` değişirse defter eski değerde kalır → gerçekte dinamik stop yanlış kaldıraçla. | Bugün etkisiz (ikisi de 3) |
| O3 | haber.py:19-20, 67-70 (`ton`) | Düz alt-dize eşleşmesi: "bank"→"ban", "issue"→"sue", "against"→"gain" → yanlış `haber_ters`, masum başlıkla açılış atlanıyor. | Evet / evet (sanal) |
| O4 | telegram.py:226-229 (`uyar`) | Gönderim başarısız olsa da anahtar 6 sa kilitleniyor → Telegram kısa kesintisinde risk uyarıları 6 sa gitmez. | İşleme etkisi yok (bildirim kaybı) |
| O5 | pano.py:928-956 (AÇIK sekmesi) | Stop sütunu K-74 dinamik stopu yok sayıp sabit %20 gösteriyor (azami 3x coinde 120,00 yerine 111,29 olmalı). Motor doğru stopu uyguluyor. | İşleme etkisi yok (yanlış gösterim) |

## Düşük

| # | Yer | Bulgu |
|---|---|---|
| D1 | hafta_paketi.py:79-95 | Radar okuması (ağ) motor kilidi altında; haftada bir (Paz ≥21:00–Pzt 12:00 TSİ) kopya olayları ~1–2 sn (en kötü ~60 sn) bekler. İşleme etkisi var, nadir. |
| D2 | motor.py ~2648/2669 | Haber/rejim ağ okuması kilit altında (saatte / 30 dk'da bir, ≤~15 sn); kapanış ve stoplar o sürede bekler. |
| D3 | motor.py ~1522 + pano `kapanan_islemler` | Kapandı K/Z'si ve pano KAPANAN neti giriş ücretini düşmüyor (iyimser gösterim, kazanma oranı hafif şişer). Defter/para doğru. |
| D4 | motor.py `_kuyruk_isle` | Dolmayan AZALT kuyruk girdisi mutlak hedef tutuyor; sonraki artırma iptal etmiyor → artırılmış pozisyon geri satılabilir. Nadir. |
| D5 | motor.py `poz_tr` / `eylem_belirle` | EPS tutarsızlığı (1e-9 / 1e-12); tam kapanış nadiren azaltma görünür, senkron düzeltir. |
| D6 | motor.py ~2294-2312 | Telafi yaş önbelleği 24 sa sınırını yeniden denetlemiyor (dar koşulda eski pozisyon açılabilir). |
| D7 | motor.py:3175 (yetim borsa stopu) | Defter dışı (yetim) stop dinamik oranı kullanmıyor (sabit %22). Yalnız gerçek kip. |
| D8 | sert_sinirlar / borsa | Kesirli kaldıraç (4,5x) kabul ediliyor; borsa `int()` ile 4x, defter 4,5x. Yalnız gerçek kip. |
| D9 | deploy/sanal_guncelle.sh | Betik motor durdurulup merge edildikten sonra öldürülürse (zaman aşımı/OOM) sonraki koşular motoru başlatmaz, alarm yok. Nadir. |
| D10 | motor.py `_gunluk_ozet` / `_haftalik_ozet` | Gün/hafta işareti mesaj kurulmadan atılıyor; istisnada o rapor bir daha denenmez. |
| D11 | hafta_paketi.py:141-162 | Haftalık K/Z 7 günlük kayıtla 6 günü kapsıyor. |
| D12 | rejim_sonuc.py:195 | Yalnız `kapat` dolumu toplanıyor (tasarım), ama "gunluk_ozet ile aynı tanım" cümlesi yanlış. |
| D13 | telegram `rejim_satiri`, pano `REJIM_TR` | "trend_up"/"volatile" çevrilmeden görünüyor. |

## Çürütülen (2)
- İz süren korumada artırmanın zirveyi sıfırlaması — KARARLAR'da yazılı tasarım.
- sert_sinirlar'ın yalnız 3 anahtarı denetlemesi — K-72 tam bu üç sınırı tanımlıyor.

## Karar gereken (kullanıcı / Fable)
- **Günlük %5 kayıp sınırı yalnız YENİ açılışı durduruyor**; açık pozisyonlar `canli_gunluk_kapat_oran` (%10) eşiğine kadar kapanmıyor. Bilinçli mi?

## Güven sınaması
Yerel, hiç push edilmeyen dalda para yoluna 5 ince hata eklendi (tam suite 1850 yeşil kaldı). Habersiz inceleyici **2/5** yakaladı: kuyruk azaltmasında reduce_only düşmesi (motor.py), coin tavanında `>=`→`>` (risk.py). Kaçanlar: sanal tasfiyede long `<=`→`<` (hesap.py), stop yeniden kurma eşiği `>`→`>=` (borsa_stop.py), sert sınır günlük kayıp toleransı 1e-12→5e-5 (sert_sinirlar.py). Üçü de eşitlik/tolerans sınırı ve mevcut testlerin hiçbiri bu sınırları sınamıyor.
Eşik altı → üç modülü Opus okudu: yeni hata bulunmadı; asıl eksik **sınır (eşitlik) testleri**. Dal ve çalışma kopyası silindi; oto-güncelleme yalnız `origin/main`i izler.

## Araç taraması (H0)
- ruff temiz; pytest rastgele sırada 2 koşu 1850/1850 yeşil.
- diff-cover: değişen 8.951 satırın %93'ü kapsamda; para yolu küçük modülleri %100 satır kapsamı (ama mutasyon skoru düşük → satır kapsamı yeterli değil).
- mutmut: sert_sinirlar 39 mutant / 7 hayatta (sınır ve tolerans); borsa_stop 225/346 işlendi, 88 hayatta — özellikle `stop_iptal` başarısızlık yolları (satır 117, 147) ve bozuk/yetim eşik yolları (82-84, 128-131) testsiz; risk ve hesap zaman bütçesi nedeniyle tamamlanmadı.
- mypy 165 hata (çoğu tip ipucu; hesap.py:78 dönüş tipi uyuşmazlığı), vulture 2 kullanılmayan import, bandit 2 orta (haber.py:75 dış XML `ET.fromstring` — XML bomba riski; telegram.py:109 urlopen).

## Mükerrer kod (hangisi kalsın)
- Hedef boyut formülü 3 yerde → `boyut.hedef_emir` kalsın; motor.py:1243 ve `_hedef_usd` ona dayansın.
- `realize − ucret + funding` toplamı hesap.py'de 3 kez → tek yardımcı.
- `Ogrenme.agirlik` / `agirlik_alias` → `agirlik_alias` kalsın.
- `yurutucu.tick_yuvarla` ölü kod → `_izgara` + `limit_yuvarla` kalsın.
- Özet modüllerinde: `_say`, `_yaz_atomik` → hafta_paketi sürümü; JSONL okuyucu → `rejim_sonuc.kayitlari_oku`; gün dizgesi, `gun_getirisi`, `zirve_dusus` → risk.py; `kisa`, `TSI` → telegram; para biçimi → `pano._tl`; kazanma oranı → `pano.kapanan_ozeti`; ML çift sayım kuralı → `gunluk_ozet.alinmayan_neden`; `ogrenme_etki` → gunluk_ozet.

## Önerilen düzeltme sırası
1. O1 (azaltma çarpanı), O3 (haber tam kelime eşleşmesi) — sanalda işlemi etkiliyor.
2. Para yolu sınır testleri (güven sınamasının kaçırdığı 3 tür + borsa_stop `stop_iptal` başarısızlık yolları) ve risk/hesap mutmut'unun tamamlanması.
3. O2 (kaldıraç yaml ile eşitlensin, gerçek kip öncesi şart), O4 (başarısız gönderimde kilit yok), O5 (pano dinamik stop).
4. D1/D2 (ağ okumaları kilit dışına), D9 (güncelleme yarıda kalırsa motoru başlat + alarm), haber.py güvenli XML.
5. Diğer düşükler ve mükerrer kod sadeleştirme.
