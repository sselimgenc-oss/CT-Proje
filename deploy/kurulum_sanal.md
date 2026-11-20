# Sanal motor sunucu kurulumu (Ubuntu 24.04, DigitalOcean) — teknik

> Kullanıcı için sade anlatım ve sıra: `docs/SUNUCU_SANAL_GECIS.md`. Bu dosya sunucuda çalıştırılan komutların kaynağıdır (gerçek kip için ayrı: `deploy/kurulum.md`; ikisi AYNI sunucuda çalıştırılmaz).
> Sanal motor cüzdan/anahtar kullanmaz. Sunucudaki tek git sırrı SSH deploy anahtarıdır (özel kısım sunucudan çıkmaz; GitHub'a yalnız ortak/public kısım yazılır).

## Mimari (Actions ↔ sunucu)
| Parça | Actions (şimdi) | Sunucu |
|---|---|---|
| Motor | `canli_vardiya.yml` 4 sa 15 dk vardiya zinciri | `sg-sanal.service` sürekli (`--kip sanal --sanal-kasa-usd 10000`) |
| Durum yayımı | `canli_yayimla.sh` (15 dk, `GITHUB_TOKEN`) | `sg-sanal-yayim.timer` → `deploy/sanal_yayimla.sh` (15 dk + servis durunca; SSH deploy anahtarı) |
| Veri dalı | `canli-durum` | `canli-durum` |
| Pano | `pano` işi → `sg-pano` | `sg-sanal-pano.timer` → `deploy/sanal_pano_cf.sh` → `sg-pano` |
| Kadro | motor `radar` dalından raw.githubusercontent.com | aynı (motor kodu; git gerekmez) |
| Dış nabız (`sg-nabiz`) | `canli-durum` kilit/özet | DEĞİŞMEZ: üretimde sunucu aynı dosyaları aynı dala yazar |
| Geri yükleme | `donem_geri.sh` | `deploy/sanal_baslat.sh` (yalnız İLK açılışta; sonra yerel durum asıl kaynaktır) |

**Çift motor güvencesi (3 katman):**
1. Anahtar: repo değişkeni `SUNUCU_AKTIF=evet` (ya da main'de `copytrade/canli/SUNUCU_AKTIF` dosyası) → `zamanlama_kontrol.sh` her olayda (cron, dispatch, push) `atla=true`; `vardiya`, `pano` ve `zincir` işleri koşmaz, zincir kopar.
2. Sunucu geçiş kapısı: üretim modunda ilk açılışta `canli-durum:durum/kilit.json` taze ve bırakılmamışsa (Actions vardiyası canlı) sunucu 75 ile bekler/başlamaz.
3. Motorun kendi kilidi (`durum/kilit.json`, `canli_kilit_dk`=20): iki motor AYNI veri dalına yazıyorsa karşılıklı engeller. Kilit yalnız veri dalı üzerinden görülür (15 dk yayım gecikmeli). (Eski "deneme" modu — ayrı dal/pano — 19.11 tam geçişle kaldırıldı.)

## 1. Paketler
```bash
sudo apt-get update && sudo apt-get install -y python3 python3-venv git ufw
# Node 22 (wrangler 4 için; Ubuntu 24.04 deposundaki Node 18 yetmez)
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && sudo apt-get install -y nodejs
sudo ufw allow OpenSSH && sudo ufw --force enable        # gelen bağlantı yalnız SSH; sunucu hiçbir port açmaz
```

## 2. Kullanıcı ve SSH deploy anahtarı
```bash
sudo useradd --system --create-home --home-dir /var/lib/sg-sanal --shell /usr/sbin/nologin sgsanal
sudo -u sgsanal mkdir -m 700 /var/lib/sg-sanal/.ssh
sudo -u sgsanal ssh-keygen -t ed25519 -N "" -C "sg-sanal-sunucu" -f /var/lib/sg-sanal/.ssh/id_ed25519
sudo -u sgsanal sh -c 'ssh-keyscan -t ed25519 github.com > /var/lib/sg-sanal/.ssh/known_hosts'
sudo -u sgsanal ssh-keygen -lf /var/lib/sg-sanal/.ssh/known_hosts     # SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU olmalı (GitHub'ın yayımladığı ed25519 parmak izi; farklıysa DURUN)
printf 'Host github.com\n  IdentityFile /var/lib/sg-sanal/.ssh/id_ed25519\n  IdentitiesOnly yes\n  UserKnownHostsFile /var/lib/sg-sanal/.ssh/known_hosts\n  StrictHostKeyChecking yes\n' | sudo -u sgsanal tee /var/lib/sg-sanal/.ssh/config >/dev/null
sudo cat /var/lib/sg-sanal/.ssh/id_ed25519.pub        # YALNIZ bu ortak (public) satır GitHub'a yapıştırılır
```
GitHub → repo → Settings → Deploy keys → Add deploy key → **Allow write access** işaretli. Özel anahtar (`id_ed25519`, `.pub` OLMAYAN) ASLA kopyalanmaz.
**Sınır:** deploy anahtarı GitHub'da depo genelinde yazar (yalnız bir dala kısıtlanamaz). `main` korunmalı: Settings → Rules → Rulesets → main için "Restrict updates"/"Require a pull request" (bypass listesi boş). Aksi halde sunucu ele geçirilirse `main` yazılabilir.

## 3. Kod, paketler, wrangler
```bash
sudo -u sgsanal git clone git@github.com:sselimgenc-oss/CT-Proje.git /var/lib/sg-sanal/depo
sudo -u sgsanal python3 -m venv /var/lib/sg-sanal/venv
sudo -u sgsanal /var/lib/sg-sanal/venv/bin/pip install --require-hashes -r /var/lib/sg-sanal/depo/requirements-canli.lock
sudo -u sgsanal npm ci --prefix /var/lib/sg-sanal/depo/.github/pano --ignore-scripts --no-audit --no-fund
sudo cp /var/lib/sg-sanal/depo/deploy/sg-sanal*.service /var/lib/sg-sanal/depo/deploy/sg-sanal*.timer /etc/systemd/system/ && sudo systemctl daemon-reload
```

## 4. Mod ve ortam dosyaları
```bash
sudo bash /var/lib/sg-sanal/depo/deploy/sanal_mod.sh uretim          # /etc/sg-sanal-mod.env yazar (sırsız); servisi başlatmaz
sudo install -m 600 -o sgsanal -g sgsanal /dev/null /etc/sg-sanal-pano.env
sudo -e /etc/sg-sanal-pano.env                                        # iki satır (aşağıda)
```
`/etc/sg-sanal-pano.env` (yalnız `AD=değer`; satır sonuna açıklama YAZMAYIN; boş bırakılırsa pano yayımı yapılmaz, motor çalışır):
```
CLOUDFLARE_API_TOKEN=<Workers düzenleme izinli API token>
CLOUDFLARE_ACCOUNT_ID=<hesap kimliği>
```
Telegram: sunucuda açık (dosya yoksa tüm kanallar sessiz). `/etc/sg-sanal-telegram.env` (izin 600, sahibi `sgsanal`): `TELEGRAM_BOT_TOKEN=…`, `TELEGRAM_CHAT_ID=…`. Actions kapalı olduğundan komutları tek tüketici olarak sunucu okur.

## 5. Açılış kontrolü ve başlatma
```bash
sudo systemctl start sg-sanal-kontrol; journalctl -u sg-sanal-kontrol -n 60 -o cat     # "tamam": true, kip sanal, kadro var
sudo systemctl enable --now sg-sanal sg-sanal-yayim.timer sg-sanal-pano.timer sg-sanal-ikinci-alarm.timer     # ikinci: bot 20 dk dönmezse ikinci sesli mesaj
journalctl -u sg-sanal -f                                                               # canlı günlük
```
İlk açılışta `sanal_baslat.sh` durumu `canli-durum` dalından (dönem aynıysa) kopyalar. 15 dk sonra ilk sunucu yayımı `canli-durum` dalında görünür.

## 6. Güncelleme
```bash
sudo systemctl stop sg-sanal-pano.timer sg-sanal-yayim.timer sg-sanal      # durdururken son yayım yapılır
sudo -u sgsanal git -C /var/lib/sg-sanal/depo pull --ff-only
sudo -u sgsanal /var/lib/sg-sanal/venv/bin/pip install --require-hashes -r /var/lib/sg-sanal/depo/requirements-canli.lock
sudo cp /var/lib/sg-sanal/depo/deploy/sg-sanal*.service /var/lib/sg-sanal/depo/deploy/sg-sanal*.timer /etc/systemd/system/ && sudo systemctl daemon-reload
sudo systemctl start sg-sanal sg-sanal-yayim.timer sg-sanal-pano.timer
```
Yerel durum korunur (geri yükleme olmaz). **Yeni dönem** (`copytrade/canli/DONEM` değişti): `sudo bash …/sanal_mod.sh <mevcut mod>` (eski durumu arşivler), sonra başlat; motor sıfırdan başlar ve dönem başına kadar bekler.

## 6b. Otomatik güncelleme (saatlik)
`sg-sanal-guncelle.timer` her saat (±5 dk) `deploy/sanal_guncelle.sh`'ı root olarak çalıştırır; elle §6 yapmak gerekmez.
- **Kapı:** `origin/main` yeni commit'i varsa ve GitHub CI'ı yeşilse (`test` ve `canli_sdk` kontrolleri var ve hepsi `success`; genel API, anahtarsız) uygulanır. Yeşil değil/yok/bekliyorsa hiçbir şey yapılmaz (günlüğe neden yazılır, bir sonraki saatte yeniden bakılır). CI PR'da koştuğundan, birleştirme commit'inde kontrol yoksa PR ucunun (2. ebeveyn) kontrolleri okunur.
- **Yalnız fast-forward** (`git merge --ff-only`); depo tarihi değişmişse reddeder ve CRIT yollar.
- **Sıra:** zamanlayıcılar + `sg-sanal` durur (son durum yayımlanır) → merge → `pip install --require-hashes` (yalnız `requirements-canli.lock` değiştiyse) → birim dosyaları (yalnız değiştiyse) + `daemon-reload` → duman testi (`sg-sanal-kontrol`, günlükte `"tamam": true`) → servisler başlar → ~60 sn sonra `sg-sanal` aktif ve yeniden başlamamış mı.
- **Hata:** herhangi bir adımda `git reset --hard <önceki>`, kilit paketleri/birimler eski haline, servisler yeniden başlar, Telegram `[CT] CRIT`. Bozuk commit bir daha denenmez (yeni commit gelene kadar).
- **Telegram:** `/etc/sg-sanal-telegram.env` (yoksa sessiz). Başarılı güncellemede mesaj yok; başarısızsa tek satır `[CT] ⚠️ Bot güncellemesi başarısız, eski sürümle devam ediyor`.
- **Yerel durum:** `durum/ kayit/ pano/` depoda izlenmez, git dokunmaz; gelen commit bunları izlemeye başlarsa güncelleme reddedilir. Servis önceden durdurulmuşsa güncelleme onu başlatmaz.
- **Birim sınırları ve bakım:** `sg-sanal*.service` içindeki bellek/CPU sınırları (`MemoryHigh/Max`, `Nice`, `CPUQuota`) da birim dosyası değiştiğinde bu adımda kopyalanır, `daemon-reload` olur ve `sg-sanal` yeniden başlar; ayrıca elle işlem gerekmez (elle §6 izleniyorsa `cp` + `daemon-reload` + `restart sg-sanal` gerekir). Haftada bir (`$DURUM/bakim_sn` damgası) `git gc --auto` + `git worktree prune` de burada çalışır. Ölçüm: `durum/motor.json` içindeki `kaynak` (ram_mb, ram_tepe_mb, cgroup_mb, yuk_1dk, disk_bos_gb) ve günlük özetin `saglik` alanı.
- **Sunucu dayanıklılık alarmı:** her saatlik çalışmada (yeni commit olmasa da, dondurulmuş olsa da; güncellemeden önce, hatası güncellemeyi bozmaz) `journalctl -u sg-sanal --since=-1h` ve `systemctl show -p Result sg-sanal` okunur. Son 1 saatte 2'den FAZLA yeniden başlama (`Scheduled restart job`) veya OOM-kill (bellek tavanı) varsa `[CT] CRIT  Sunucu motoru son 1 saatte N kez yeniden başladı (sınır 2). Bellek tavanı: OOM evet/hayır.` (OOM için ayrı CRIT). Aynı tür en çok 6 saatte bir (`$DURUM/alarm_yeniden`, `alarm_oom`: son gönderim zamanı). Durum düzelince tek `[CT] INFO  Sunucu motoru düzeldi…` ve durum dosyaları silinir. Ölçüm `/var/lib/sg-sanal/saglik_sunucu.json`'a yazılır; günlük özetin `saglik.yeniden_baslama_1s` / `saglik.oom_son` alanları buradan okunur (dosya yok/3 saatten eski: null). Sınırlar: `SANAL_ALARM_YENIDEN_SINIR` (2), `SANAL_ALARM_ARA_SN` (21600).
- **Kilit:** aynı anda iki güncelleme koşmaz (`flock /run/sg-sanal-guncelle.lock`). Durum dosyaları: `/var/lib/sg-sanal-guncelle/` (root'a ait).
- **Güvenlik notu:** betik root çalışır ve depodan (CI'dan geçen `main`) gelir; `main` koruması (§2) bu yüzden önemli: sunucudaki `sgsanal` hesabı ele geçerse depo dosyaları root'a yükselmek için kullanılabilir.

**Tek seferlik açma** (root kabuğunda tek satır; bekleyen güncellemeleri hemen uygular, `--no-block` ile hemen döner; izlemek için `journalctl -u sg-sanal-guncelle -f -o cat`):
```bash
mkdir -p /var/lib/sg-sanal-guncelle && sudo -u sgsanal git -C /var/lib/sg-sanal/depo rev-parse HEAD > /var/lib/sg-sanal-guncelle/uygulanan_sha && sudo -u sgsanal git -C /var/lib/sg-sanal/depo pull --ff-only && cp /var/lib/sg-sanal/depo/deploy/sg-sanal*.service /var/lib/sg-sanal/depo/deploy/sg-sanal*.timer /etc/systemd/system/ && systemctl daemon-reload && systemctl enable --now sg-sanal-guncelle.timer && systemctl start --no-block sg-sanal-guncelle && echo OTO-GUNCELLEME-ACIK
```
(İlk satır, çekmeden ÖNCEKİ sürümü "çalışan sürüm" diye kaydeder; böylece çekilen kod hemen duman testi + yeniden başlatmayla uygulanır, hata olursa o sürüme dönülür.)

**Elle geri alma** (iki adım: `evet` onayı; sonra otomatik güncelleme DONDURULUR): `sudo bash /var/lib/sg-sanal/depo/deploy/sanal_geri_al.sh <sha>` (sha sunucudaki depoda olmalı; `git -C /var/lib/sg-sanal/depo log --oneline -10`). Dondurmayı kaldırma: `sudo rm /var/lib/sg-sanal-guncelle/dondur`. Kapatma: `sudo systemctl disable --now sg-sanal-guncelle.timer`.

## 6c. Günlük radar sunucuda (K-78)
Radar (tarama + kadro + isabet + PBO + rastgele + holdout mührü + `radar` dalına yayım) artık Actions yerine sunucuda koşar: Actions cron'u ~7 sa geç tetikleniyordu (kadro 03:37 TSİ yerine ~10:42'de çıkıyordu). Formül/seçim kodu aynı; adımlar `radar.yml` ile birebir aynı modüller.
- **Birimler:** `sg-sanal-radar.timer` (00:37 UTC = 03:37 TSİ, `Persistent=true`, ±2 dk rastgele) → `sg-sanal-radar.service` → `deploy/sanal_radar.sh`. Otomatik güncelleme (§6b) birim dosyalarını kopyalar, `daemon-reload` yapar ve `systemctl enable --now sg-sanal-radar.timer` çalıştırır; elle kurulum gerekmez (elle §3/§6 izleniyorsa `cp` + `daemon-reload` + `sudo systemctl enable --now sg-sanal-radar.timer`).
- **Sır ihtiyacı: YOK.** Tarama halka açık Hyperliquid verisini okur. Veri dalına yazmak için mevcut SSH deploy anahtarı (§2; `GIT_SSH_COMMAND` birimde, repoda sır yok) yeter. Telegram anahtarı isteğe bağlı (`/etc/sg-sanal-telegram.env`; yoksa alarm atlanır). Cloudflare/HL anahtarı bu birimde yok.
- **Düzen:** depodan geçici ayrı worktree (HEAD'de sabit; motorun çalışma dizini ve `durum/ kayit/ pano/` değişmez, otomatik güncelleme araya girse de koşu kendi kod kopyasıyla biter). Tek koşu: `flock /var/lib/sg-sanal/radar.lock`. Bugünün `radar/<tarih>/havuz.json`'u veri dalında varsa iş yapılmaz (Persistent/çift tetik; zorla: `RADAR_ZORLA=1`). Adım zaman aşımları: tarama 170 dk (kural bütçesi 150), kadro 25, isabet 40, diğerleri ≤ 15; birim `TimeoutStartSec=4h`.
- **Kaynak:** `MemoryHigh=550M`, `MemoryMax=700M`, `CPUQuota=60%`, `Nice=15`, `IOSchedulingClass=idle` (motor 300M ile çakışmasın; 2 GB sunucu). `OOMPolicy=continue`: bellek tavanı aşılırsa betik ölmez, adım başarısız görünür ve alarm gider. İlk koşudan sonra gerçek tepe: `systemctl show -p MemoryPeak sg-sanal-radar` (tavan yetmezse not düşün).
- **Bağımlılık:** pandas/numpy canlı motorun venv'inde yok; ayrı venv `/var/lib/sg-sanal/venv-radar`, `requirements-radar.lock` (sha256 kilitli) ilk koşuda ve kilit değişince `sanal_radar.sh` tarafından kendiliğinden kurulur (internet gerekir; ilk koşu birkaç dk uzar).
- **Alarm:** başarısızlıkta tek `[CT] ⚠️ Radar sunucuda çalışmadı: <adım>` (sesli); başarıda mesaj YOK. Kadro eski kalır (`son/` güncellenmez); sağlık/pano "radar geldi mi" eşikleri (`saglik.py`: 30 sa uyarı / 54 sa kritik) yeni saatle de doğru.
- **Actions:** `radar.yml`'de cron kaldırıldı; yalnız elle yedek (`workflow_dispatch`, sunucu radarı çalışmazsa). Sunucu ve Actions AYNI anda koşmamalı (ikisi de `radar` dalına yazar).
- **Elle / izleme:** hemen koş: `sudo systemctl start --no-block sg-sanal-radar` (bugünün radarı veri dalında varsa iş yapmaz; zorlamak için `sudo systemctl edit sg-sanal-radar` ile geçici `Environment=RADAR_ZORLA=1`); günlük: `journalctl -u sg-sanal-radar -n 50 -o cat`; sonraki koşu: `systemctl list-timers sg-sanal-radar.timer`.

## 7. Sorun giderme
- `journalctl -u sg-sanal -n 100 -o cat`, `systemctl status sg-sanal sg-sanal-yayim.timer sg-sanal-pano.timer`.
- Yayım: `sudo systemctl start sg-sanal-yayim; journalctl -u sg-sanal-yayim -n 20 -o cat` ("Permission denied (publickey)" = deploy anahtarı eklenmemiş/yazma izni yok).
- Pano: `sudo systemctl start sg-sanal-pano; journalctl -u sg-sanal-pano -n 20 -o cat`.
- Çıkış 3 = kalıcı (ör. mod/dal uyuşmazlığı); servis yeniden başlamaz: nedeni günlükten okuyun, düzeltip `sudo systemctl reset-failed sg-sanal && sudo systemctl start sg-sanal`.
- Motoru elle (birim dışında) ÇALIŞTIRMAYIN.

## 8. Fiyat farkı ölçümü (HL ↔ Binance, 96 saat)

Oto-güncelleme birimi kurar ve ölçümü BİR KEZ başlatır (`/var/lib/sg-sanal-guncelle/olcum_basladi` işareti; 96 sa sonra kendi biter, yeniden başlatılmaz). Yeniden ölçmek için işareti silin. Aşağıdaki elle adımlar yalnız gerekirse:
Salt-okur, bağımsız servis (`deploy/sg-sanal-olcum.service`); motora dokunmaz. Enable edilmez (yeniden açılışta kendiliğinden başlamaz).
```bash
sudo cp /var/lib/sg-sanal/depo/deploy/sg-sanal-olcum.service /etc/systemd/system/ && sudo systemctl daemon-reload
sudo systemctl start sg-sanal-olcum            # 96 saat koşar, kendiliğinden biter (enable ETMEYİN)
journalctl -u sg-sanal-olcum -n 30 -o cat      # çıkış 3 = Binance erişimi yok (451/403): tek ⚠️ Telegram + durum/olcum/fiyat_farki/<gün>.jsonl'de "erisim" kaydı
sudo -u sgsanal bash -c 'cd /var/lib/sg-sanal/depo && /var/lib/sg-sanal/venv/bin/python -m copytrade.olcum.fiyat_farki --ozet'    # özet markdown → stdout + durum/olcum/fiyat_farki/OZET.md
```
Çıktı yeri: `/var/lib/sg-sanal/depo/durum/olcum/fiyat_farki/` (`<gün>.jsonl`: `erisim`, `fark`, `mid`, `bitis` olayları). Veri dalına yayımlanmaz (yayım betiği yalnız bilinen dosyaları kopyalar); özeti elle alın.
