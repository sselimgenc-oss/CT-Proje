# T1 durum notu (Sonnet) — eski sistemi sil

Dal: `claude/t1-eski-sistem-sil` (taban: `claude/stoic-carson-w3xagz`). Karar bekleyen sorular **lider için**; dokunmadım, tahminle ilerlemedim.

## Lider kararı gereken (belgede yazmayan / belge ile çelişen)
1. **`ilk11` adı kalan altyapıda yaşıyor.** Kabul grep'i (`ilk11`) yalnız 4 dosyaya izin veriyor, ama "kalır" listesindeki dinleyici, risk defteri ve
   Faz 3 hazırlığı İlk 11'i yeni kadronun adı olarak kullanıyor: `dinleyici.py` (`takim == "ilk11"`), `risk_defter.py` (`ilk11` kümesi, sayaç `ilk11_disi`),
   `live_koruma.py` (ret kodu `yalniz_ilk11`), `faz3_preflight.py` (`grup='ilk11'`), `izleme_liste.py` (`takim` değerleri), `pano_veri.py` (`TAKIMLAR`),
   `risk_deneme.py` ve bunların testleri + `VERI_SOZLESMESI.md` §7/§10 + `H2_KURULUM.md`. Yeniden adlandırma sunucudaki dinleyici sözleşmesini ve
   ret kodlarını değiştirir → **yapmadım**. Seçenek A: RADAR_V1'deki "İlk 11" adı olarak kalsın, grep istisnası genişlesin (önerim).
   Seçenek B: tamamını `kadro` gibi bir adla yeniden adlandıran ayrı PR.
2. **Worker `kol == "oda"` bildirim akışı duruyor.** `isNotified`, günlük özet (oda kasası, oda−kontrol farkı), `/durum` yalnız `kol = oda` için çalışıyor
   (`worker/src/index.js`). Kaldırsaydım Telegram bildirimi tamamen susardı ve yerine geçecek tanım yok (T4). Yalnız kapı/oda'nın ürettiği
   **kalabalık uyarısı ve yönsüz bayrak satırı** çıkarıldı (üreten kod silindi). `izleme_listesi.yaml` (891 satır, `kol: oda/kontrol/taban/havuz`) da
   olduğu gibi duruyor: dinleyici ve Worker bunu okuyor.
3. **`izleme_motoru.py` içinde `kol == "oda"` ile yazılan `veri_kalitesi.mutabakat` kaldı** (kalan `test_pozisyon_mutabakat.py` bunu sınıyor; test zayıflatılmadı).
   T4'te radar kadrosuna bağlanmalı.
4. **`son_yaz.py` + `tests/test_son_json.py`** yalnız silinen kapı yayımcısından çağrılıyordu; listede yok, emin olmadığım için **silmedim**.
5. **`izleme_liste.py` içindeki `KOLLAR` ve `takim` şeması** eski kol adlarını (`oda`, `kontrol`, `taban`, `referans_*`, `cikarilan`, `havuz`) doğruluyor;
   liste dosyası bunları kullandığı için değiştirmedim.
6. **Kuralda yeniden adlandırma (davranış aynı):** kalan kodun okuduğu `ilk11_form_pencere_gun`, `ilk11_durum_min_gecerli_islem`, `ilk11_form_tazelik_dk`
   anahtarları, kabul grep'ine uymak için `kapanan_islem_pencere_gun`, `kapanan_islem_min_gecerli`, `veri_tazelik_dk` oldu (değerler aynı: 30, 6, 270).

## Yapılan taşımalar (kural 7: kopya değil, taşıma)
- `kapi.py` → **`copytrade/hl_ortak.py`**: `TAKER`, `SLIPPAGE`, `spot_usdc`, Binance eşleme/evren/`binance_availability` (davranış aynı).
- `ilk11_deneme.py` → **`copytrade/deneme_arac.py`**: yalnız genel parçalar (`liste`, `durum-ozeti`, `sure_tahmini`); iş akışları buna bağlandı.
- `tarama.py`: `PublicClient`, `RateLimiter`, `_address`, `_window` kaldı; eski günlük aday tarayıcı (`prefilter`, `run`, `main`, rapor) silindi (izleme.csv/`kopya.simulate` ile birlikte eski sistemdi).
- `kurallar.py`: `evaluate` (eski aday süzgeci) silindi. `kurallar.yaml`: 174 → 32 anahtar; kalan her anahtarı kalan kod okuyor (`tests/test_kurallar_anahtarlari.py` bunu her koşuda sınar).
- `izleme_motoru.py`: kapı sonucu okuma (`gate_result`, `gate_style`), `oda_risk` bağlantısı (yönsüz, kalabalık), `kasa_egri` (oda/kontrol), `ilk11_form_ham`, `ilk11_gecerli_saat` çıkarıldı.
  Tarz artık yalnız listeden (`tarz` yoksa `bilinmiyor`, 30 dk).
- `pano_veri.py`: İlk 11 snapshot okuması çıkarıldı (`pano_uret(durum, liste, simdi)`, `--ilk11` yok); `kadro_toplam` hep `null`; pano.js boş durumda "Radar kadrosu T4'te" gösterir.
- `izleme.yml`: cron kaldırıldı (yalnız elle), kapı/İlk 11 liste adımı çıktı; `pano.yml` yalnız `copytrade-izleme` dalını okur.

## Elle düzeltilen test sayıları ve kanıt
Ayrıntı PR açıklamasında (önceki/sonraki sayılar, silinen dosya ve fonksiyon listesi).

## Silinen test dosyaları (yalnız silinen modülü test ediyordu)
- tests/test_analiz_d.py (14 test)
- tests/test_analiz_kosu.py (6 test)
- tests/test_arsiv.py (4 test)
- tests/test_arsiv_alarm.py (6 test)
- tests/test_bayrak.py (9 test)
- tests/test_bayrak_ek.py (19 test)
- tests/test_cikis_v14.py (10 test)
- tests/test_ek2_kapi_sutunlari.py (2 test)
- tests/test_eksik_koşu_dis_aday.py (9 test)
- tests/test_esik_5000.py (7 test)
- tests/test_gecis.py (6 test)
- tests/test_haftalik_rapor.py (6 test)
- tests/test_hf_dogrulama.py (12 test)
- tests/test_ilk11.py (12 test)
- tests/test_ilk11_alanlar.py (37 test)
- tests/test_ilk11_pazar.py (20 test)
- tests/test_ilk11_veri.py (5 test)
- tests/test_izleme_ilk11.py (8 test)
- tests/test_kapi_ab.py (5 test)
- tests/test_kapi_istatistik.py (5 test)
- tests/test_kasa_egri.py (2 test)
- tests/test_oda_risk.py (11 test)
- tests/test_pazar_akis.py (11 test)
- tests/test_pilot_veri.py (12 test)
- tests/test_risk_isaretleri.py (6 test)
- tests/test_saglik_kapisi.py (19 test)
- tests/test_secim.py (23 test)
- tests/test_sentetik.py (7 test)
- tests/test_yogunlasma.py (13 test)
- tests/test_asama1_payda.py (5 test)
- tests/test_a14_baglantilar.py (kalan 2 test: kapi_yayimla.sh ve yogunlasma anahtarları; hepsi eski sistem)
- tests/test_copytrade_kapi.py (7 test: zaman ağırlıklı getiri, delayed_copy x2, bhy, plasebo x2, aşama1 — kapi.py silindi; 8. test binance eşleme tests/test_hl_ortak.py'ye TAŞINDI)
- tests/test_trader_secimi.py (30 test; kapı/keşif/plasebo/tarz; 2 PublicClient testi tests/test_tarama_istemci.py'ye TAŞINDI)

## Kalan dosyalarda silinen / değişen test fonksiyonları
- test_a14_baglantilar.py::test_gunluk_kaydet_yalniz_adim1_ve_adim2_gecenler_icin
- test_a14_baglantilar.py::test_birlestirme_parcalarin_ve_onceki_dosyanin_gunluk_getirilerini_birlestirir
- test_a14_baglantilar.py::test_secim_oda_yogunlasmasi_ve_puan_yari_tutarliligi_secim_json_ve_raporda
- test_a14_baglantilar.py::test_gunluk_dosyasi_yoksa_rapor_bunu_soyler_ve_secim_ayni_kalir
- test_a15_baglantilar.py::test_candle_cache_mum_saglik_ozeti_coin_basina_bir_kez_hesaplanir
- test_a15_baglantilar.py::test_kapi_satirina_mum_ozeti_ve_birlestirmede_rapor_ve_durum
- test_a19.py::test_nw_alpha_birebir_kopya_seri_yetersiz_doner
- test_a19.py::test_nw_alpha_alfa_ne_olursa_olsun_artik_varyans_sifirsa_yetersiz
- test_a19.py::test_nw_alpha_gurultulu_gercek_alfa_gecerli_kalir
- test_a19.py::test_nw_alpha_esik_kurallar_yamlindan_gelir
- test_a19.py::test_kapi_adim6_yetersiz_durum_alfa_ne_olursa_olsun_yetersiz
- test_copytrade.py::test_watchlist_preserves_t0_and_never_removes
- test_copytrade.py::test_copy_charges_friction_and_funding
- test_copytrade.py::test_copy_reads_documented_funding_shape_and_does_not_double_charge_fees
- test_copytrade.py::test_rules_have_three_outcomes
- test_copytrade.py::test_prefilter_keeps_every_eligible_leader_without_a_cap
- test_copytrade.py::test_prefilter_kurallari_tek_kez_okur_ve_sonuc_ayni
- test_copytrade.py::test_prefilter_accepts_documented_window_performances_shape
- test_copytrade.py::test_daily_run_writes_public_archive_watchlist_and_report
- test_copytrade.py::test_prefilter_accepts_live_pair_shape_of_window_performances
- test_copytrade.py::test_rate_limited_address_is_recorded_as_no_data_and_run_continues
- test_degisim_saglik.py::test_degisimin_gecerli_gerekcesi_tavani_ve_istisnasi
- test_degisim_saglik.py::test_degisim_oda_listesini_gunceller_ve_cikarilan_56_gun_sonra_silinir
- test_degisim_saglik.py::test_degisim_raporu_gerekceyi_ayri_ve_sanal_alfayi_yazar
- test_degisim_saglik.py::test_degisim_raporu_v1_degil_v3u_okur_ve_v1_tabanini_karistirmaz
- test_degisim_saglik.py::test_degisim_raporu_v3_hesaplanamamissa_bekliyor_v1e_dusmez
- test_degisim_saglik.py::test_referans_odasi_uyesi_cikarilsa_da_listeden_dusmez
- test_golge.py::test_altin_pencere_oncesi_acik_pozisyon_kapanisi_saglama_kiyasindan_cikar
- test_golge.py::test_altin_pencere_ici_flip_kapanisi_alir_yeni_yonu_sonraki_kapanisa_tasir
- test_golge.py::test_altin_sabit_olcekli_saglama_hesap_buyumesinden_bagimsizdir
- test_golge.py::test_altin_saglama_toplam_net_ve_eksik_isaretleme_notu
- test_golge.py::test_altin_trader_toplam_net_golge_unrealizedini_kullanmaz
- test_golge.py::test_altin_kapanir_yeniden_acilir_ve_sonda_acik_kalir_ilk_tur_saglamaya_girer
- test_izleme.py::test_copy_execution_delay_cost_funding_and_event_net
- test_motor_uclari.py::test_e6_bayrak_onbellegi_yeniden_kosuda_cagri_tekrarlamaz
- test_motor_uclari.py::test_e6_yarim_kalan_kosu_yalniz_eksikleri_hesaplar_ve_surum_degisince_gecersiz
- test_motor_uclari.py::secim_sonucu
- test_kapi_5xx.py::test_kapi_istemcisi_kapi_ilkesiyle_kurulur
- test_kapi_5xx.py::test_b_satir_hata_dolu_ve_hatali_satir_sayilir
- test_kapi_5xx.py::test_c_hatali_oran_aday_yuzde_birin_ustundeyse_eksik
- test_kapi_5xx.py::test_c2_birlestirme_durum_json_hatali_alanlari
- test_kapi_5xx.py::_kurulum
- test_kapi_5xx.py::_degerlendirici
- test_kapi_5xx.py::test_d_yeniden_kosu_diger_satirlar_bayt_bayt_ayni_hatalilar_yenilenmis
- test_kapi_5xx.py::test_d2_hepsi_duzelirse_durum_tamam
- test_kapi_5xx.py::test_en_fazla_yalniz_ilk_n_hatali_satiri_kosar
- test_kapi_5xx.py::test_hata_dolu_satir_yoksa_hicbir_sey_yapmaz
- test_kapi_5xx.py::test_hesap_surumu_ya_da_kod_hash_farkliysa_reddeder_dosyaya_dokunmaz
- test_kapi_5xx.py::test_kayit_bolucu_tirnak_icindeki_satir_sonunu_bolmez
- test_kapi_5xx.py::test_hash_farkliysa_reddeder_istisna_yolu_yok
- test_kapi_5xx.py::test_hesap_zamani_yalniz_yeniden_cekilen_satirlarda_digerleri_bos_yeniden_denenen_sayisi
- test_kapi_5xx.py::test_bhy_ailesi_tam_yeniden_hesap_ham_sutunlar_bayt_bayt_ayni
- test_kurallar_uygunluk.py::test_account_floor_boundary_0_4999_fail_5000_pass
- test_kurallar_uygunluk.py::test_gate_functions_use_the_yaml_thresholds_at_the_boundary
- test_kurallar_uygunluk.py::test_freeze_summary_hashes_rules_and_code_and_candidate_list
- test_a15_baglantilar.py::test_mum_sutunlari_bos_olabilir_listesinde (saglik_bos_olabilir kapı anahtarı)
- test_a15_baglantilar.py::_shard (yardımcı)
- test_kurallar_uygunluk.py::test_user_decisions_in_the_task_document_equal_kurallar_yaml (GOREV_TRADER_SECIMI.md karar belgesi silindi)
- test_kurallar_uygunluk.py::test_numbered_user_decisions_10_11_14 (GOREV_TRADER_SECIMI.md karar belgesi silindi)
- test_kurallar_uygunluk.py::test_numbered_user_decision_27_account_floor (GOREV_TRADER_SECIMI.md karar belgesi silindi)
- test_kurallar_uygunluk.py::grab (yardımcı) (GOREV_TRADER_SECIMI.md karar belgesi silindi)
- test_izleme.py::test_style_falls_back_to_gate_result_then_unknown_with_30_minutes -> yeniden adlandırıldı, kapı-sonucu yedek kolu çıkarıldı (kapı kaldırıldı); diğer kollar aynen
- test_hesap_spot.py::test_golden_deneme_ozeti_hesap_tablosu_i_f_yan_yana (ilk11_deneme.hesap_tablosu silindi); ilk11_form_ham/kapi.account_value_parts doğrulamaları çıkarıldı, spot/toplam doğrulamaları hl_ortak ile korundu
- test_altin_ornekler.py::test_golden_8_account_value_floor_sums_main_and_hip3_dexes_and_stops_at_kaldi (kapi.py hesap tabanı); test_scenario_..._in_both_engines -> yalnız defter kolu kaldı (plasebo motoru silindi), 7 elle hesaplı senaryo aynen
- test_is_akislari.py::test_artik_dosyalar_temizlendi_ve_kalanlar_gercekten_kullaniliyor
- test_is_akislari.py::test_deneme_hazirla_dosyalari_kapi_ve_izleme_formatinda_yazar
- test_is_akislari.py::test_deneme_ilk_adimi_eksik_secret_adini_yazar_kirmizi_biter_degeri_asla_yazdirmaz
- test_is_akislari.py::test_deneme_kendi_dalindan_tetiklenebilir_ve_uretime_yazmaz
- test_is_akislari.py::test_deneme_secimi_dagilim_ve_buyuk_kucuk_hesap
- test_is_akislari.py::test_deneme_secimi_yetersiz_aday_net_hata_verir
- test_is_akislari.py::test_deneme_secret_kontrolu_kirmiziysa_ozet_ve_artifact_adimlari_calismaz
- test_is_akislari.py::test_eksik_kosu_kirmizi_biter_ama_kismi_sonuc_yazilir_kesif_ve_snapshot_uretilmez
- test_is_akislari.py::test_izleme_araligi_ile_tazelik_esigi_tutarli_k18
- test_is_akislari.py::test_izleme_deneme_listesi_ve_ozeti
- test_is_akislari.py::test_izleme_listesi_veri_dalindan_okunur_main_listesi_yedek
- test_is_akislari.py::test_kapi_yayimci_eksik_kosunun_kismi_sonucunu_yazar_ve_main_e_dokunmaz
- test_is_akislari.py::test_kapi_yayimci_yazim_yarisinda_yeniden_dener_ve_oncekileri_korur
- test_is_akislari.py::test_pazar_isi_dosyalari_yalniz_basari_kodlarinda_yazar_kod_2_kirmizi_biter
- test_is_akislari.py::test_plan_gunu_tum_parcalara_ve_birlestirmeye_aynen_gecer
- test_is_akislari.py::test_sure_tahmini_iki_sure_ayri_ve_butce_asimi_uyarisi
- test_is_akislari.py::test_v3_yan_yana_altin_ornek
- test_is_akislari.py::test_zamanlamalar_sartnameyle_ayni
- test_is_akislari.py: test_zamanlamalar_sartnameyle_ayni, test_izleme_araligi_ile_tazelik_esigi_tutarli_k18 -> test_izleme_zamanlamasi_t1de_kaldirildi_... ile değiştirildi; test_izleme_listesi_veri_dalindan_okunur... -> main listesi testine; test_artik_dosyalar... -> test_eski_sistem_is_akislari_ve_betikleri_yok
- test_pano_veri.py: SNAP/snapshot girdisi çıkarıldı; kadro_toplam beklentileri 2→None, 1→None (snapshot kaynağı kaldırıldı); test_main... --ilk11 bayrağı çıkarıldı. Test silinmedi.
- test_golge.py::test_altin_v2_onkayit_d_ile_ayni_donmus_esikleri_kullanir -> yeniden adlandırıldı (test_altin_v2_donmus_esikleri_kullanir), içerik aynı; test_kapi_5xx.py -> test_tarama_5xx.py (5 PublicClient testi aynen; kapı bölümleri silindi)

## Test kimliği düzeyinde tam liste (872 → 470; 458 kimlik kalktı, 56 eklendi)
- `tests/test_a14_baglantilar.py` — 6 test (1 tanesi başka dosyada/yeni adla yaşıyor)
  - `test_birlestirme_parcalarin_ve_onceki_dosyanin_gunluk_getirilerini_birlestirir`, `test_gunluk_dosyasi_yoksa_rapor_bunu_soyler_ve_secim_ayni_kalir`, `test_gunluk_kaydet_yalniz_adim1_ve_adim2_gecenler_icin`, `test_secim_oda_yogunlasmasi_ve_puan_yari_tutarliligi_secim_json_ve_raporda`, `test_yayimci_gunluk_getiriyi_acikca_veri_dalina_ekler`
- `tests/test_a15_baglantilar.py` — 3 test
  - `test_candle_cache_mum_saglik_ozeti_coin_basina_bir_kez_hesaplanir`, `test_kapi_satirina_mum_ozeti_ve_birlestirmede_rapor_ve_durum`, `test_mum_sutunlari_bos_olabilir_listesinde`
- `tests/test_a19.py` — 7 test
  - `test_kapi_adim6_yetersiz_durum_alfa_ne_olursa_olsun_yetersiz`, `test_nw_alpha_alfa_ne_olursa_olsun_artik_varyans_sifirsa_yetersiz`, `test_nw_alpha_birebir_kopya_seri_yetersiz_doner`, `test_nw_alpha_esik_kurallar_yamlindan_gelir`, `test_nw_alpha_gurultulu_gercek_alfa_gecerli_kalir`
- `tests/test_altin_ornekler.py` — 8 test
  - `test_golden_8_account_value_floor_sums_main_and_hip3_dexes_and_stops_at_kaldi`, `test_scenario_gives_the_hand_computed_number_in_both_engines`
- `tests/test_analiz_d.py` — 14 test
  - `test_hafta_veri_eksik_siniri`, `test_ikincil_beta_duzeltmesi_tam_uyum_altin`, `test_ikincil_btc_sabitse_beta_sifir_fark_ortalama`, `test_ikincil_mbb_tekrarlanabilir_ve_noktayi_kapsar`, `test_karar_sinir_ve_gerekce`, `test_karar_uc_sonuc_altin_ornekler`, `test_karar_yariyor_dort_kosulun_hepsi_gerekir`, `test_maliyet_duyarliligi_yalniz_intraday_iki_kat`, `test_mde_altin`, `test_spearman_altin_n5`, `test_spearman_baglar_ortalama_sira`, `test_spearman_n12_altin`, `test_spearman_ters_ve_sabit_ve_kucuk_n`, `test_yaml_esikleri_onkayitla_ayni`
- `tests/test_analiz_kosu.py` — 6 test
  - `test_altin_ornek_tablo_bicimi`, `test_gercek_veri_tarihte_ve_sonrasinda_calisir`, `test_gercek_veri_tarihten_once_reddedilir_ve_dosya_okunmaz`, `test_ikincil_oda_esiginin_altinda_denenmez`, `test_sentetik_kilitten_muaf_ve_acikca_etiketli`, `test_yaml_anahtari`
- `tests/test_arsiv.py` — 4 test
  - `test_altin_ornek_44_dk_bosluk_degil_46_dk_bosluk`, `test_altin_ornek_acik_pozisyon_coini_1dk_muma_gider`, `test_altin_ornek_guncel_kapi_havuzu_ve_olay_semasi`, `test_altin_ornek_imlec_sonraki_milisaniyeden_baslar_ve_yol`
- `tests/test_arsiv_alarm.py` — 6 test
  - `test_art_arda_basarisiz_koşular_sayilir_ve_en_son_basari_esas_alinir`, `test_cikis_kodu_alarmda_1_bilgi_kipinde_0`, `test_esik_sinirlari_tam_12_saat_alarm_degil_12_saat_1_dk_alarm`, `test_haftalik_rapor_arsiv_kesintisini_yazar`, `test_hic_basarili_kosu_yoksa_alarm_ve_bos_liste`, `test_yaml_esigi_12_saat`
- `tests/test_asama1_payda.py` — 5 test
  - `test_golden_deposit_is_not_a_return`, `test_golden_losses_give_bounded_drawdown_and_calmar`, `test_golden_steady_gains_chain_to_thirty_percent_without_drawdown`, `test_golden_withdrawal_is_not_a_loss`, `test_impossible_values_of_the_old_denominator_cannot_occur`
- `tests/test_bayrak.py` — 9 test
  - `test_alt_hesap_ters_sub_hesap_ve_master`, `test_bayrak_tablosu_ve_bayrak_raporu_yeni_sutunlari_icerir`, `test_bayrak_yalniz_aday_kati_ve_secimi_degistirmez`, `test_funding_payi_isaretli`, `test_hacim_orani`, `test_hesapla_bes_sutun_ve_kontrol_edilemedi`, `test_rol`, `test_ters_pozisyon`, `test_vault_orani`
- `tests/test_bayrak_ek.py` — 19 test
  - `test_altin_ornek_ekleme_derinligi`, `test_altin_ornek_martingale_karisik_eklemeler`, `test_altin_ornek_martingale_klasik_2x`, `test_altin_ornek_tek_coin_yogunlugu_hhi`, `test_bos_liste_ekleme_derinligi`, `test_bos_liste_martingale`, `test_bos_liste_tek_coin_yogunlugu`, `test_bozuk_satirlar_atlanan_satir_olarak_sayilir`, `test_devralinan_pozisyon_bir_coinde_digerini_etkilemez`, `test_devralinan_pozisyon_ters_donunce_yeni_giris_bilinir`, `test_esit_zamanli_dolumlarda_giris_sirasi_korunur_ve_esit_payda_alfabetik`, `test_karisik_zaman_siralamasi`, `test_karli_ekleme_martingale_sayilmaz`, `test_long_ve_short_tam_simetri`, `test_pencere_oncesi_pozisyonda_giris_bilinmez_zararda_ekleme_olculmez`, `test_spot_dolumlar_perp_suzgeciyle_dislanir_ve_atlanan_sayilmaz`, `test_tek_coin_eklemesiz_pozisyon`, `test_tek_coin_tek_karli`, `test_tum_coinler_zararda_yogunluk`
- `tests/test_cikis_v14.py` — 10 test
  - `test_3_hafta_yetmez`, `test_4_hafta_ve_60_islem_ikisi_saglaninca_cikar`, `test_59_islem_yetmez_60_yeter`, `test_alt_dilim_siniri_10_kisilik_havuzda_alt_5`, `test_alt_dilim_tek_sayida_havuz_yukari_yuvarlar`, `test_arada_uygun_hafta_ardisikligi_bozar`, `test_islem_verisi_yoksa_cikis_degerlendirilemez_ve_cikmaz`, `test_kurallar_v14_degerleri`, `test_odadan_secim_odasinda_olmak_cikisi_engellemez_ama_ustte_olmak_engeller`, `test_tek_alt_dilim_haftasi_yetmez`
- `tests/test_copytrade.py` — 10 test
  - `test_copy_charges_friction_and_funding`, `test_copy_reads_documented_funding_shape_and_does_not_double_charge_fees`, `test_daily_run_writes_public_archive_watchlist_and_report`, `test_prefilter_accepts_documented_window_performances_shape`, `test_prefilter_accepts_live_pair_shape_of_window_performances`, `test_prefilter_keeps_every_eligible_leader_without_a_cap`, `test_prefilter_kurallari_tek_kez_okur_ve_sonuc_ayni`, `test_rate_limited_address_is_recorded_as_no_data_and_run_continues`, `test_rules_have_three_outcomes`, `test_watchlist_preserves_t0_and_never_removes`
- `tests/test_copytrade_kapi.py` — 8 test (1 tanesi başka dosyada/yeni adla yaşıyor)
  - `test_bhy_and_three_outcome_step_classes`, `test_delayed_copy_uses_next_candle_open_not_fill_price`, `test_placebo_placement_preserves_trade_fields_is_non_overlapping_and_seeded`, `test_placebo_scores_runs_fixed_repetitions`, `test_stage1_uses_pnl_history_not_account_value_jumps`, `test_time_weighted_return_removes_deposit_and_keeps_no_flow_series`, `test_zero_delay_uses_leader_fill_and_cache_requests_each_coin_once`
- `tests/test_degisim_saglik.py` — 6 test
  - `test_degisim_oda_listesini_gunceller_ve_cikarilan_56_gun_sonra_silinir`, `test_degisim_raporu_gerekceyi_ayri_ve_sanal_alfayi_yazar`, `test_degisim_raporu_v1_degil_v3u_okur_ve_v1_tabanini_karistirmaz`, `test_degisim_raporu_v3_hesaplanamamissa_bekliyor_v1e_dusmez`, `test_degisimin_gecerli_gerekcesi_tavani_ve_istisnasi`, `test_referans_odasi_uyesi_cikarilsa_da_listeden_dusmez`
- `tests/test_ek2_kapi_sutunlari.py` — 2 test
  - `test_sifir_gecikmede_yonlu_dolum_sutunlari_uretilmez_diger_gecikmelerde_dolu`, `test_yeni_bilgi_sutunlari_akil_sagligi_kapisini_kirmaz`
- `tests/test_eksik_koşu_dis_aday.py` — 9 test
  - `test_48_parca_birlesim_evren_kesisim_bos_ve_az_adreste_bos_parca_zararsiz`, `test_altin_ornek_ortak_evren_parcalari_cakismadan_birlesir`, `test_external_candidates_are_unique_lowercase_addresses_from_all_files`, `test_merge_complete_run_is_tamam`, `test_merge_ignores_shared_universe_snapshot_artifact`, `test_merge_publishes_incomplete_run_as_eksik`, `test_merge_reports_distinct_code_hashes`, `test_run_status_incomplete_when_shard_missing_or_coverage_low`, `test_universe_marks_external_and_bypasses_prefilter`
- `tests/test_esik_5000.py` — 7 test
  - `test_eksik_modu_hesap_degeri_tabanindan_kalan_ama_yeni_esigi_gecenleri_de_alir`, `test_evren_adresleri_verilmezse_eski_olcu_korunur`, `test_hesap_degeri_esikleri_5000`, `test_kapi_v3_belgesinde_surum_3_2_notu`, `test_kapsam_bir_gecmez_evren_disi_satirlar_sayilmaz`, `test_kapsam_evren_adres_kumesine_gore_ve_evren_disi_satir_isaretlenir`, `test_latest_day_ve_tarih_bayragi`
- `tests/test_gecis.py` — 6 test
  - `test_cikis_icin_iki_ardisik_haftalik_degerlendirme`, `test_haftalik_gecis_giris_cikis_ve_surum_kimligi`, `test_kayit_alan_ve_deger_denetimi`, `test_kayit_yalniz_ekler_sirayi_korur_ve_silme_yolu_yok`, `test_kollar_py_ikinci_uygulama_kaldirildi_tek_kaynak_secim`, `test_uygunsuz_haftalar_ardisik_degilse_veya_arada_uygun_varsa_cikis_yok`
- `tests/test_golge.py` — 7 test
  - `test_altin_kapanir_yeniden_acilir_ve_sonda_acik_kalir_ilk_tur_saglamaya_girer`, `test_altin_pencere_ici_flip_kapanisi_alir_yeni_yonu_sonraki_kapanisa_tasir`, `test_altin_pencere_oncesi_acik_pozisyon_kapanisi_saglama_kiyasindan_cikar`, `test_altin_sabit_olcekli_saglama_hesap_buyumesinden_bagimsizdir`, `test_altin_saglama_toplam_net_ve_eksik_isaretleme_notu`, `test_altin_trader_toplam_net_golge_unrealizedini_kullanmaz`, `test_altin_v2_onkayit_d_ile_ayni_donmus_esikleri_kullanir`
- `tests/test_haftalik_rapor.py` — 6 test
  - `test_birincil_havuz_genelinde_spearman_ve_kirilim_altin_ornek`, `test_cikti_dosyasi_ve_cli`, `test_gecis_bayragi_haftalik_gecisi_calistirir_getiri_yoksa_da`, `test_ileri_getirisi_olmayan_adres_eksik_sayilir_ve_hafta_veri_eksik_isaretlenir`, `test_rapor_kosu_suresini_yazar`, `test_rapor_metni_korluk_kol_bazinda_getiri_yok`
- `tests/test_hesap_spot.py` — 5 test
  - `test_golden_F_hesap_spot_usdc_dahil_ve_kapi_tanimiyla_ayni`, `test_golden_deneme_ozeti_hesap_tablosu_i_f_yan_yana`, `test_spot_okuma_hatasi_trader_dusurmez_yalniz_hesap_alani_eksik`, `test_spot_usdc_tek_yerde_account_value_parts_davranisi_degismedi`, `test_spot_yoksa_toplam_perpe_esit_ve_kucuk_hesap_hala_aralik_disi`
- `tests/test_hf_dogrulama.py` — 12 test
  - `test_agac_parquet_dosyalari_ve_uzantilar`, `test_butce_dolunca_kismi_sonuc`, `test_calistir_uctan_uca_yerel_ve_hata_kirmizi`, `test_capraz_altin_ornek`, `test_duckdb_kapsam_satir_ve_degerler`, `test_en_yakin_ve_tarihler`, `test_goreli_fark_ve_ozet`, `test_kapi_adresleri`, `test_ledger_adaylari`, `test_tarih_bolumleri_ve_bosluklar`, `test_tarih_yolu`, `test_yeniden_429_te_bekleyip_dener_digerinde_hemen_firlatir`
- `tests/test_ilk11.py` — 12 test
- `tests/test_ilk11_alanlar.py` — 37 test
  - `test_akil_sagligi_tum_aralik_sinirlari`, `test_bilgi_sutunu_hatasi_kapi_sonucunu_degistirmez`, `test_bos_hesap_ve_kapanmis_islemi_olmayan_trader`, `test_calculate_metrics_kazanma_orani_bilgi_sutununu_yayimlar`, `test_doluluk_sorunlari_yuzde_90_siniri`, `test_dolum_siniri_10000_dolum_hizli_ve_tutarli`, `test_form_ham_30g_aralik_disi_alan_ihlal_olarak_isaretlenir`, `test_form_ham_30g_naif_zaman_reddedilir`, `test_form_tam_senaryo_portfolio_month_week_dolu`, `test_form_yalniz_pencere_icinde_kapanan_islemleri_sayar_acilisi_bilinmeyen_tutmaya_girmez`, `test_golden_10_golge_ilk_tarz_gecikmesindeki_net_intraday_012_swing_030`, `test_golden_11_golge_form_getiriler_010_eksi005_020_buzulmus_ortalama_002273`, `test_golden_14_ay_roi_1805_none_ve_ihlal_kaynagi`, `test_golden_14_yirmi_adaydan_ikisinde_ihlal_yuzde_10_gt_5_kirmizi_biri_gecer`, `test_golden_17_kapi_satirindan_median_holding_hours_3_5_tutma_210_dakika`, `test_golden_1_pencere_getiri_hesap_1000_pnl_100_yatirma_getiri_degildir`, `test_golden_2_yedi_gun_kesimi_sekizinci_gunden_onceki_pnl_sayilmaz`, `test_golden_3_pencere_dusus_ozsermaye_1_1_2_0_9_1_0_ise_ceyrek`, `test_golden_4_pozitif_gun_orani_gunluk_delta_5_eksi3_0_2_ise_ikide_uc`, `test_golden_5_kazanma_orani_net_10_eksi5_3_eksi1_ise_yarim`, `test_golden_5_ucret_yuzunden_eksiye_donen_islem_kaybedendir_ve_tersine_donus_iki_islemdir`, `test_golden_6_siklik_30_gunde_12_islem_ise_0_4_gun_ve_puan_0_4`, `test_golden_7_tutma_saatleri_1_2_30_medyan_2_saat_120_dakika_ve_puan_0_6`, `test_golden_8_kaldirac_efektif_2x_puan_0_9`, `test_golden_9_hesap_255000_dolar_puan_karekok_yarim`, `test_golge_form_yalniz_gecerli_ve_penceredeki_islemler`, `test_hareketsiz_hesap_tutarli_none_getiri_sifir`, `test_ilk_alanlar_nan_ve_eksik_alan_none_kaynagi_none`, `test_ilk_alanlar_tum_alanlar_dolu_ve_leaderboard_degerleri_kullanilmaz`, `test_kapi_bilgi_sutunlari_hafta_ve_ay_ayri_pencere`, `test_kapi_satiri_bilgi_sutunlarini_portfolio_ayni_yanitindan_yazar`, `test_kazanma_orani_net_sifir_kazanan_degil_ve_bos_liste_none`, `test_pnl_history_2_noktadan_az_none`, `test_pozitif_gun_gun_icindeki_birden_cok_noktanin_sonuncusunu_alir_ve_bos_gunu_atlar`, `test_sifira_yakin_payda_olanaksiz_getiri_akil_sagligi_ile_elenir`, `test_spot_dolumu_form_alanlarina_girmez`, `test_yeni_oran_sutunlari_akil_sagligi_kapisinda_0_1_disi_kirmizi`
- `tests/test_ilk11_pazar.py` — 20 test
  - `test_adaylari_hazirla_yalniz_katman_adaylari_ve_sayac`, `test_deneme_yalniz_cikti_yazar_iki_kosuda_ayni_snapshot_id`, `test_form_kapi_eski_ise_hareketler_uygulanir_bosluk_doldurulmaz_cikis_kodu_2`, `test_form_uctan_uca_hareketler_bosluk_doldurma_liste_ve_yeniden_uretim`, `test_form_yedek_terfi_kapisi_kapanan_islemlerle_uctan_uca`, `test_gecici_kadro_onceki_kadro_sayilmaz_ilk_gercek_kosu_ilk_secimdir`, `test_golden_13_terfi_kapisi_son_6_gecerli_sonuc_usd`, `test_golden_15_kapi_klasoru_8_gun_eski_reddedilir_7_gun_kabul`, `test_golden_15_satir_uygunlugu_neden_kodlari`, `test_golden_16_49_uygun_kapasite_bos_1_uyari_paf_27_ve_10_uygun_yayin_yok`, `test_golden_18_form_gecerlilik_ve_aktiflik`, `test_golden_19_snapshot_deterministik_tek_alan_degisimi_farkli_kimlik_ve_tahrif_reddi`, `test_ilk_secim_akil_sagligi_ve_doluluk_kapisi_yayini_engeller`, `test_ilk_secim_kalite_hatasi_rapor_ve_csv_yazar_snapshot_yazmaz`, `test_ilk_secim_kapi_eski_ise_kirmizi_hicbir_snapshot_yazilmaz`, `test_ilk_secim_uctan_uca_dosyalar_akis_liste_ve_idempotans`, `test_izleme_durum_sec_git_gecmisinden_as_of_oncesi_en_son_surum`, `test_kapi_sec_eksik_koşu_kapsam_ve_hesap_surumu_reddeder_en_yeni_uygunu_alir`, `test_pazar_as_of_takvimden_cron_gecikmesi_sonucu_degistirmez`, `test_terfi_kapisi_girdisi_izleme_kapanan_islemlerinden_takim_hafta_sonrasi_gecerli_ve_as_of_oncesi`
- `tests/test_ilk11_veri.py` — 5 test
  - `test_explicit_tutma_is_already_in_minutes`, `test_form_esle_only_transfers_explicit_semantic_matches`, `test_snapshot_is_deterministic_frozen_and_has_team_assignments`, `test_snapshot_rejects_non_sunday_or_wrong_time`, `test_snapshot_tamper_detection`
- `tests/test_is_akislari.py` — 22 test (4 tanesi başka dosyada/yeni adla yaşıyor)
  - `test_artik_dosyalar_temizlendi_ve_kalanlar_gercekten_kullaniliyor`, `test_deneme_hazirla_dosyalari_kapi_ve_izleme_formatinda_yazar`, `test_deneme_ilk_adimi_eksik_secret_adini_yazar_kirmizi_biter_degeri_asla_yazdirmaz`, `test_deneme_kendi_dalindan_tetiklenebilir_ve_uretime_yazmaz`, `test_deneme_secimi_dagilim_ve_buyuk_kucuk_hesap`, `test_deneme_secimi_yetersiz_aday_net_hata_verir`, `test_deneme_secret_kontrolu_kirmiziysa_ozet_ve_artifact_adimlari_calismaz`, `test_eksik_kosu_kirmizi_biter_ama_kismi_sonuc_yazilir_kesif_ve_snapshot_uretilmez`, `test_izleme_araligi_ile_tazelik_esigi_tutarli_k18`, `test_izleme_deneme_listesi_ve_ozeti`, `test_izleme_listesi_veri_dalindan_okunur_main_listesi_yedek`, `test_kapi_yayimci_eksik_kosunun_kismi_sonucunu_yazar_ve_main_e_dokunmaz`, `test_kapi_yayimci_yazim_yarisinda_yeniden_dener_ve_oncekileri_korur`, `test_pazar_isi_dosyalari_yalniz_basari_kodlarinda_yazar_kod_2_kirmizi_biter`, `test_plan_gunu_tum_parcalara_ve_birlestirmeye_aynen_gecer`, `test_sure_tahmini_iki_sure_ayri_ve_butce_asimi_uyarisi`, `test_v3_yan_yana_altin_ornek`, `test_zamanlamalar_sartnameyle_ayni`
- `tests/test_izleme.py` — 2 test
  - `test_copy_execution_delay_cost_funding_and_event_net`, `test_style_falls_back_to_gate_result_then_unknown_with_30_minutes`
- `tests/test_izleme_ilk11.py` — 8 test
  - `test_form_ham_hatasi_izleme_okumasini_dusurmez`, `test_gecerli_saat_24_saatte_12_kosu_24_saat_ayni_kovada_bir_kez_k18`, `test_gecerli_saat_takim_hafta_degisince_sifirlanir_ve_hatali_okuma_saymaz`, `test_kirpma_6_gecerli_islem_30_gunden_eskiyse_yine_yayimlanir_ve_yoksa_dokunmaz`, `test_kirpma_pencere_ve_son_6_gecerli_kurali`, `test_liste_parametresi_alternatif_listeyi_okur`, `test_run_durum_json_kirpilir_motor_json_tam_gecmisi_tutar`, `test_run_ilk11_form_ham_ve_gecerli_saat_yayimlanir`
- `tests/test_kapi_5xx.py` — 19 test (5 tanesi başka dosyada/yeni adla yaşıyor)
  - `test_b_satir_hata_dolu_ve_hatali_satir_sayilir`, `test_bhy_ailesi_tam_yeniden_hesap_ham_sutunlar_bayt_bayt_ayni`, `test_c2_birlestirme_durum_json_hatali_alanlari`, `test_c_hatali_oran_aday_yuzde_birin_ustundeyse_eksik`, `test_d2_hepsi_duzelirse_durum_tamam`, `test_d_yeniden_kosu_diger_satirlar_bayt_bayt_ayni_hatalilar_yenilenmis`, `test_en_fazla_yalniz_ilk_n_hatali_satiri_kosar`, `test_hash_farkliysa_reddeder_istisna_yolu_yok`, `test_hata_dolu_satir_yoksa_hicbir_sey_yapmaz`, `test_hesap_surumu_ya_da_kod_hash_farkliysa_reddeder_dosyaya_dokunmaz`, `test_hesap_zamani_yalniz_yeniden_cekilen_satirlarda_digerleri_bos_yeniden_denenen_sayisi`, `test_kapi_istemcisi_kapi_ilkesiyle_kurulur`, `test_kayit_bolucu_tirnak_icindeki_satir_sonunu_bolmez`
- `tests/test_kapi_ab.py` — 5 test
  - `test_ayni_hesap_farkli_sure_ve_hash_fark_yok_yanit_bir_kez_cekilir`, `test_hata_bir_kez_alinir_iki_koda_ayni_hata_verilir`, `test_hesap_farki_yakalanir_ve_ornek_gosterilir`, `test_kontrol_disi_sabiti_kodda_acik`, `test_modul_yukle_ayri_kopya_yukler_calisan_paketi_bozmaz`
- `tests/test_kapi_istatistik.py` — 5 test
  - `test_blocks_and_seed_preserve_trade_count_and_holding_duration`, `test_neff_correlation_clusters`, `test_newey_west_alpha_and_matched_benchmark_extremes`, `test_placebo_is_reproducible`, `test_placebo_scale_matches_strategy_size`
- `tests/test_kasa_egri.py` — 2 test
  - `test_kasa_egrisi_oda_toplamini_son_bilinen_bakiye_ile_toplar`, `test_kasa_egrisi_v1i_degil_v3u_okur_v3_hesaplanamayan_trader_disarida_kalir`
- `tests/test_kurallar_uygunluk.py` — 8 test (2 tanesi başka dosyada/yeni adla yaşıyor)
  - `test_account_floor_boundary_0_4999_fail_5000_pass`, `test_freeze_summary_hashes_rules_and_code_and_candidate_list`, `test_gate_functions_use_the_yaml_thresholds_at_the_boundary`, `test_numbered_user_decision_27_account_floor`, `test_numbered_user_decisions_10_11_14`, `test_user_decisions_in_the_task_document_equal_kurallar_yaml`
- `tests/test_motor_uclari.py` — 2 test
  - `test_e6_bayrak_onbellegi_yeniden_kosuda_cagri_tekrarlamaz`, `test_e6_yarim_kalan_kosu_yalniz_eksikleri_hesaplar_ve_surum_degisince_gecersiz`
- `tests/test_oda_risk.py` — 11 test
  - `test_esik_sinirlari_tam_esit_bayrak_degil_ve_negatif_funding`, `test_funding_arbitraj_profili_bayraklanir_yonsel_profil_bayraklanmaz`, `test_kalabalik_cakisma_ve_ayni_yon_sayisi_esikleri`, `test_kalabalik_elle_hesap`, `test_kalabalik_uyari_yok_kaldirac_cift_sayilmaz_ve_yonsuz_uye_atlanir`, `test_kolsuz_trader_ek_alan_almaz_ve_sozlesmede_yazili`, `test_maker_payi_pencere_ve_crossed_alani`, `test_motor_spot_hatasi_gizlenmez_ve_gune_onbellege_girmez`, `test_motor_yonsuz_bayrak_gunde_bir_onbellek_ve_kalabalik_alani`, `test_toplam_kar_portfoy_pnl_farki`, `test_yaml_esikleri_sezgisel_ve_belgeli`
- `tests/test_pazar_akis.py` — 11 test
  - `test_basarili_akis_tekrar_denemez`, `test_basarisizliktan_sonra_iki_saatlik_araligi_bekler_ve_dolunca_tekrarlar`, `test_baslangicta_zaman_geldiyse_snapshot_hazirlanmasini_ister`, `test_hafta_ici_yeni_akis_gelecek_pazari_bekler`, `test_ilk_deneme_cumartesiden_yaklasan_pazar_13e_bekler`, `test_ilk_deneme_pazar_13_oncesi_ve_sonrasi`, `test_naive_zaman_ve_gecersiz_deneme_sayisi_hata_verir`, `test_retry_farkli_snapshot_kimligini_reddeder`, `test_retry_snapshot_kimligi_eksikse_reddeder`, `test_saniyelik_gecikmede_snapshot_as_of_sabit_pazar_13`, `test_utc_input_istanbul_saatine_dogru_donusturulur`
- `tests/test_pilot_veri.py` — 12 test
  - `test_altin_ornek_api_pencere_siniri_dolarsa_adres_pencere_disi_eksik_sayilir`, `test_altin_ornek_aralikta_300_dolum_donuyor_adresin_toplami_pencerenin_altindaysa_pencere_disi_degil`, `test_altin_ornek_aralikta_az_dolum_ama_adresin_penceresi_etiketten_sonra_basliyorsa_pencere_disi`, `test_altin_ornek_bosluk_bir_kez_arsive_yazilir_haftalik_koşu_apiye_gitmez`, `test_altin_ornek_ileri_getiri_kapanmis_islem_ve_pasif_adres`, `test_altin_ornek_kol_bazinda_getiri_cikmaz`, `test_altin_ornek_mum_anahtari_coinleri_birbirine_ezmez`, `test_altin_ornek_mum_eksikse_adres_getiriden_cikar_ve_eksik_sayilir`, `test_altin_ornek_risk_girdisi_yalniz_oda_uyeleri_ve_kaldirac_sicramasi`, `test_arsiv_mum_anahtari_gercek_api_satirinda_coin_icerir`, `test_oku_gun_ve_adres_suzgeci_ve_ozet_dosyasi`, `test_secim_havuzu_arsiv_havuzuna_girer`
- `tests/test_risk_isaretleri.py` — 6 test
  - `test_kaldirac_sicramasi_sinir`, `test_kurallar_v14_degerleri`, `test_martingale_baslangici_altin_ornek_ve_sinirlar`, `test_rapor_bolumu_yalniz_bilgi_performans_yok_ve_cli`, `test_tutma_anomalisi_sinir`, `test_uye_isaretleri_toplu_ve_eksik_veri`
- `tests/test_saglik_kapisi.py` — 23 test
  - `test_alfa_yillik_yilliklandirilmis_oldugu_icin_net_getiri_araligina_girmez`, `test_any_fully_empty_column_fails_unless_listed_as_optional`, `test_check_net_range_turns_an_implausible_copy_into_a_row_error`, `test_constant_column_fails_only_with_enough_rows`, `test_dead_columns_not_in_evaluated_row`, `test_empty_column_fails`, `test_error_rate_over_limit_turns_gate_red`, `test_every_non_passing_row_must_have_a_reason`, `test_fail_reason_names_the_first_failing_step_golden`, `test_family_member_without_placebo_fails`, `test_fill_limit_flag`, `test_good_table_passes`, `test_leverage_outside_range_fails`, `test_merge_refuses_to_publish_on_sanity_failure`, `test_missing_copy_fills_make_step3_insufficient_but_static_failure_stays_failed`, `test_net_return_outside_minus1_to_100_fails_the_gate`, `test_ratio_float_noise_within_tolerance_passes_but_real_excess_fails`, `test_ratio_outside_0_1_fails`, `test_single_address_error_does_not_kill_the_shard`
- `tests/test_secim.py` — 23 test
  - `test_aday_az_ise_oda_tum_aday_ve_kisa_uyarisi`, `test_aday_gercek_kurallarla_yuvarla_yukari`, `test_bayrak_ayri_is_aday_kati_icin_secimi_degistirmez`, `test_havuz_eski_evren_satirlarini_almaz`, `test_havuz_kolu_ileriye_donuk_sessiz_izleme_k8`, `test_havuz_statik_kosullari_kapi_ile_ayni`, `test_havuz_ve_puan`, `test_izleme_listesi_ayni_secim_yeniden_yazilirsa_id_ve_t0_degismez`, `test_izleme_listesi_eski_secimi_sabit_referans_olarak_korur`, `test_izleme_listesi_mevcut_satirlari_korur_ve_dogrulanir`, `test_kontrol_ayni_dilimden_odayla_ayrik`, `test_kontrol_dilim_sirasi_hash_ve_bos_dilimde_ayni_tarz`, `test_kontrol_eslesemeyen_oda_uyesi_yazilir`, `test_kontrol_puana_bakmaz_oda_disindaki_herkes_cikabilir`, `test_kotalar_en_buyuk_kalan`, `test_oda_kota_genc_oncelik_ve_iliskili_hesap`, `test_sec_kol_onceligi_ve_ciktilar`, `test_secim_ciktisi_golge_butunluk_bilgi_sutunlarini_korur`, `test_secim_kapi_tarihine_baglidir_secim_tarihine_degil`, `test_secim_kimligi_ve_ikincil_kontrol`, `test_taban_30_gunluk_pnl`, `test_tam_kosu_degilse_durur`, `test_tohum_altin_deger`
- `tests/test_sentetik.py` — 7 test
  - `test_ayni_tohum_ayni_cikti`, `test_gecersiz_parametreler_valueerror_verir`, `test_gurultu_sifirken_ortalama_yetenegi_tam_bulur`, `test_rastgele_puan_isabeti_yetenekli_orana_yakindir`, `test_sans_yalniz_yeteneksizlere_ve_son_gunlere_eklenir`, `test_secim_basarisi_sansli_traderlari_sayir_ve_takma_ad_kabul_etmez`, `test_trader_kimlikleri_ve_cikti_bicimi`
- `tests/test_trader_secimi.py` — 30 test (2 tanesi başka dosyada/yeni adla yaşıyor)
  - `test_activity_thresholds_by_style_and_last_trade_age`, `test_alpha_benchmark_choice_and_basket`, `test_coin_that_does_not_fit_even_alone_is_circularly_shifted_with_a_note`, `test_delay_test_days_is_about_200_and_capped_by_first_fill`, `test_dondurulmus_binance_listesi_tum_parcalarda_ayni_kaynaktir`, `test_finalize_adds_layer_and_young_candidate_flag`, `test_gate_copy_ignores_inherited_exposure_so_window_start_does_not_flip_the_sign`, `test_hip3_binance_mapping`, `test_inactivity_makes_step2_insufficient_and_blocks_later_steps`, `test_kesif_schema_filtering_and_order`, `test_layers`, `test_link_candidates_shared_agent_and_transfer`, `test_merge_completes_existing_day_without_duplicate_rows`, `test_missing_addresses_selects_absent_and_data_error_rows`, `test_night_share_is_report_only_tsi_0100_to_0900`, `test_none_metrics_fail_the_step_instead_of_raising`, `test_placebo_places_trader_with_simultaneous_positions_in_two_coins`, `test_placebo_scores_10000_for_overlapping_two_coin_trader_with_delay`, `test_progress_log_reports_stage_times_and_candle_requests`, `test_quick_run_keeps_pre_v11_rows_apart_as_eski_hesap_and_out_of_the_gate`, `test_related_accounts_flags_from_fixed_responses`, `test_related_pool_uses_all_gate_pool_not_only_layers`, `test_sanity_failure_names_the_source_of_bad_rows`, `test_short_trade_share_depends_on_style`, `test_step3_rules_by_style`, `test_style_boundaries`, `test_test_family_is_steps_1_to_4_and_m_in_report`, `test_weekly_curve_is_365_day_weekly_pnl_over_account`
- `tests/test_yogunlasma.py` — 13 test
  - `TestKorelasyonMatrisi::test_min_ortak_gun_kurali`, `TestKorelasyonMatrisi::test_sifir_varyans`, `TestKorelasyonMatrisi::test_temel_korelasyon`, `TestKumele::test_bagimsiz_seriler_ayri_kumelerde_kalmali`, `TestKumele::test_birebir_ayni_iki_seri_tek_kumeye_girmeli`, `TestKumele::test_bos_ve_tekli_matris`, `TestKumele::test_esik_sinirinda_davranis`, `TestKumele::test_nanli_veri`, `TestYariTutarliligi::test_elle_hesaplanmis_ornek_bagli_siralar`, `TestYariTutarliligi::test_elle_hesaplanmis_ornek_bagsiz_siralar`, `TestYariTutarliligi::test_sabit_puan_veya_yetersiz_veri`, `TestYariTutarliligi::test_tam_ayni_ve_tam_ters_tutarlilik`, `TestYogunlasmaOzeti::test_metrikler`
## Lider kararları (2026-11-04, Claude)
1. **A:** "İlk 11 / Yedek 11 / PAF" yeni kadronun adı (`RADAR_V1.md` §5); `ilk11` kalan altyapıda kalır, yeniden adlandırma yok. Kabul grep'inden `ilk11` çıkarıldı.
2. Worker `kol == "oda"` akışı T4'e kadar kalır; T4'te radar kadrosuna (İlk 11) bağlanır.
3. `veri_kalitesi.mutabakat` T4'te İlk 11'e bağlanır.
4. `son_yaz.py` + `test_son_json.py` kapı/seçim işaretçisiydi → lider sildi.
5. `KOLLAR`/`izleme_listesi.yaml` T4'te radar kadrosu şemasıyla değişir.
6. Anahtar yeniden adları kabul.
