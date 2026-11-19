# Paylaşım verisi: kadro yön özeti (`ct.kadro_yon.v1`)

Salt okur, sürümlü veri akışı; kardeş projeler okur. Karar/emir yoluna girmez; yalnız veri.

- Konum: veri dalı `canli-durum`, yol `durum/paylasim/kadro_yon_v1.json` (ham: `https://raw.githubusercontent.com/<sahip>/<repo>/canli-durum/durum/paylasim/kadro_yon_v1.json`).
- Güncelleme: motor `durum_yaz()` ile yazar; yayım her 15 dk ve vardiya sonunda (`.github/scripts/canli_yayimla.sh`). Okuyan `uretildi_utc`'ye bakıp bayatlığı kendisi denetler.
- Kapsam: yalnız SAHA üyeleri (inen traderlar hariç). Trader adresi, bizim bakiye/özsermaye/kasa, anahtar ve emir bilgisi YOKTUR.
- Şema değişirse yeni dosya (`kadro_yon_v2.json`) yanında yayımlanır; v1 bozulmaz.

## Alanlar
| Alan | Anlam |
|---|---|
| `sema` | `"ct.kadro_yon.v1"` |
| `uretildi_utc` | ISO8601 UTC (`...Z`), motor saati |
| `kadro_surumu` | kadro.json `radar_surum` (yoksa null) |
| `kadro_kosu_utc` | kadro.json `kosu_ms` (radar koşusu) ISO UTC (yoksa null) |
| `saha_trader_sayisi` | saha üyesi sayısı (int) |
| `kip` | `"sanal"` / `"gercek"` |
| `coinler[]` | coin başına satır; sıra: `abs(net_nominal_usd)` azalan, null sonda |
| `coinler[].coin` | HL coin adı (HIP-3 `dex:COIN` olduğu gibi) |
| `long_trader`, `short_trader` | o coinde long / short pozisyonu olan saha trader sayısı |
| `net_yon` | `"long"`/`"short"`: trader sayısı çoğunluğu; eşitse nominal işareti; o da 0 / bilinmiyorsa `"notr"` |
| `nominal_long_usd`, `nominal_short_usd`, `net_nominal_usd` | trader pozisyon büyüklüğü (coin) × mark, $ (TRADER ölçeği, kopya ölçeği değil); mark yoksa null |
| `veri_yasi_sn` | o coindeki trader pozisyon okumalarının EN ESKİSinin yaşı (sn); bilinmiyorsa null |
| `notlar` | "Trader pozisyonlarının toplamı (kopya kadrosu). Bizim hesabımızın pozisyonu DEĞİL. Yatırım tavsiyesi değil." |
