# Görev H5 — Risk sınırları (dry-run)

Kaynak: `docs/FAZ1_ANLIK_KOPYA.md` H5; K‑17 (anlık kopya), K‑18 (lider karar verir; canlı/para kullanıcıda).
Yazar: Sonnet (tek yazar). Lider denetler, birleştirir. **Emir, anahtar, cüzdan, imza YOK; yalnız karar kaydı.**

## Amaç
Anlık dinleyicinin (`copytrade/dinleyici.py`) gördüğü her İlk 11 dolumu için "kopya emri niyeti" üret, risk sınırlarından geçir,
**kabul / ret + neden** kaydet. Canlıda para korumasının dry-run provası: hangi sınır ne sıklıkla tetikleniyor, kaç sinyal kaçıyor.

## Var olan (yeniden kullan, ikinci kopya yazma — kural 7)
- `copytrade/live_koruma.py`: `Mode`, `GateState`, `Limits`, `evaluate_order` (dry-run kapısı, `emir_gonderildi: False`). Testli, ama
  hiçbir yerden çağrılmıyor. **Bunu genişlet**, yeni bir kapı yazma.
- `copytrade/dinleyici.py`: `Olay` akışı (trades + userFills + REST dolgu), saatlik `ozet.json`, `STATE_DIRECTORY`.
- Kopya boyutu: v3 ile aynı kural (`kopya_v3.py` / `kurallar.yaml` `sabit_tutar_*`). Boyut hesabını kopyalama; fonksiyonu çağır.

## Lider kararları (dry-run varsayılanları; canlı sayıları H4'te kullanıcı onaylar)
| Sınır | Alan (`kurallar.yaml`, yeni blok `risk_dry_run:`) | Varsayılan | Birim |
|---|---|---|---|
| Referans kasa | `referans_kasa_usd` | 1000 | $ (sanal kopya ölçeği) |
| Emir başına tavan | `emir_tavan_usd` | 100 | $ notional |
| Trader başına açık notional tavanı | `trader_tavan_usd` | 200 | $ notional (yeni sınır) |
| Toplam açık brüt notional tavanı | `toplam_brut_tavan_usd` | 1500 | $ (1,5x referans) |
| Günlük zarar şalteri | `gunluk_zarar_usd` | 30 | $ (referansın %3'ü; UTC gün) |
| Sinyal tazeliği | `sinyal_tazelik_sn` | 10 | sn (dolum zamanı → karar anı) |
| Elle durdurma (/dur) | `dur_dosyasi` | `$STATE_DIRECTORY/DUR` | dosya varsa yeni giriş/ekleme reddedilir; çıkış serbest |

- Yalnız **İlk 11** için niyet üretilir; Yedek/PAF/referans yalnız ölçülür (`yalniz_ilk11`).
- Çıkış (azaltma/kapama) sınırlardan muaf; yalnız açık kopya pozisyonu varsa kabul (`acik_pozisyon_yok`).
- Trader'ın t0 öncesi (miras) pozisyonu kopyalanmaz: v3 kuralıyla aynı (A4‑4 bulgusu).
- Günlük zarar: kabul edilen sanal kopya pozisyonlarının gerçekleşen + gerçekleşmemiş zararı (son görülen işlem fiyatıyla). Fiyat yoksa
  `fiyat_yok` say, tahmin etme.

## Yapılacak
1. `Limits`'e `trader_tavan_usd` ekle; değerleri `kurallar.yaml` `risk_dry_run`'dan oku (varsayılan tablo). `evaluate_order` yeni neden: `trader_tavani`.
2. `copytrade/risk_defter.py` (yeni): olay → niyet (open/add/exit, notional) → `evaluate_order` → sanal pozisyon defteri (kabul edilenler)
   → günlük zarar. Saf fonksiyonlar; ağ yok.
3. Dinleyiciye bağla: `calis` her olayda deftere verir; `ozet.json`'a `risk` bloğu: `niyet`, `kabul`, `ret` (neden başına sayı),
   `acik_brut_usd`, `gunluk_zarar_usd`, `salter_tetiklendi`, `dur_aktif`. Karar satırları `$STATE_DIRECTORY/risk_kararlari.jsonl`
   (takma ad, adres YOK; dosya günlük döner, 7 gün tutulur).
4. Liste: dinleyici listesinde İlk 11 üyeliği hangi alanla geliyor kontrol et (`izleme_listesi.yaml`/`ilk11` çıktısı); yoksa
   alan ekle ve VERI_SOZLESMESI'ne yaz. Pilot listede İlk 11 yoksa: tüm liste "ilk11 sayılır" bayrağı YALNIZ deneme için (`--risk-tum-liste`).
5. Testler (altın örnek, elle hesap): (a) 3 dolum → 2 kabul 1 `emir_limiti`; (b) trader tavanı aşımı; (c) toplam brüt aşımı;
   (d) zarar şalteri → sonraki girişler ret, çıkış kabul; (e) DUR dosyası; (f) geç sinyal; (g) miras pozisyon kapanışı kopyalanmaz;
   (h) UTC gün dönümünde günlük zarar sıfırlanır. Uç: sıfır/negatif notional, fiyat yok, aynı dolum iki kaynaktan (trades + userFills) → tek niyet.
6. `docs/VERI_SOZLESMESI.md`: `risk` bloğu ve `risk_kararlari.jsonl` alanları birimleriyle; sürüm notu.
7. `docs/H2_KURULUM.md`: güncelleme adımı (`git pull` + `systemctl restart sg-dinleyici`) ve `/dur` kullanımı (`touch /var/lib/sg-dinleyici/DUR`, kaldırma `rm`).
8. Kural 1: yerelde kayıtlı/örnek olay akışıyla deneme (ağ gerekmez) + PR açıklamasında özet. Sunucu denemesini lider kullanıcıyla yapar.
9. `python -m pytest -q` tam paket; PR açıklamasına sonuç. Birleştirme lider.

## Kabul
- Dry-run'da sınır ihlali sayılır ve reddedilir (FAZ1 H5 kabulü); `emir_gonderildi` her satırda `false`.
- Dinleyicinin gecikme/kaçan ölçümü değişmez (mevcut testler aynen geçer).
- Sunucu belleği: 1 GB'ta rahat (defter trader × coin boyutunda).

## Kapsam dışı
- Gerçek emir, anahtar, imza, cüzdan. Canlı sınır sayıları (H4, kullanıcı). Seçim/kapı/eşik değişikliği.
