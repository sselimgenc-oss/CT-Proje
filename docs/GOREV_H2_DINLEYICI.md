# Görev H2 — Anlık dinleyici dry-run (VPS)

Kaynak: K‑17, `docs/FAZ1_ANLIK_KOPYA.md`; Opus salt-okur denetimi 2026-11-02 (origin/main 700d2e7). Yazar: Sonnet. Denetçi: lider.
Emir, anahtar, cüzdan, imza kodu **yok**. Sunucuda secret yok.

## Mevcut durum (denetim)
- Var: `hl_public_adapter.py` (gerçek WS bağlantısı, adres başına `userFills`, `userFillsByTime` dolgu), `hl_ws_runtime.py`
  (yeniden bağlanma 1→30 sn, dolgu, tekilleştirme, JSONL, manifest), `faz3_dry_run_service.py` (`/healthz`, `/readyz`, SIGTERM).
  Testler sahte transport ile (20 test); gerçek ağ koşusu hiç yapılmadı.
- Engeller: adres sayısı 11'e sabit; `websockets` requirements'ta yok; `isSnapshot` ilk geçmiş dolumları gecikmeyi bozar;
  dolgu senkron (olay döngüsünü kilitler) ve sayfalanmaz; `error`/`subscriptionResponse` sessizce atılır; uygulama ping'i yok;
  gerçek alma anı damgası yok; trader kırılımı yok; dönemsel kaçan-dolum karşılaştırması yok; YAML liste okunmaz.
- **Kritik risk (doğrulanacak):** HL, IP başına kullanıcıya özgü aboneliklerde **en çok 10 benzersiz kullanıcı** sınırı koyuyor olabilir.
  Kadro 50 + referans bu sınırı aşar.

## Lider kararları (K‑18)
1. **İki kaynak, biri birincil:** Birincil kaynak **`trades` kanalı** (coin başına; her işlemde `users: [alıcı, satıcı]`) — tüm coinlere
   abone olunur, izlenen adresler `users` alanından süzülür; kullanıcı başına sınır yoktur (doğrulanacak). Çapraz kontrol: ilk 10 adres için
   `userFills` (yön/`dir`, ücret, kapanış PnL buradan). Hakem: her 10 dk REST `userFillsByTime` karşılaştırması.
2. **Adım 0 (1 saatlik koşudan önce, 5 dk):** 11. adres aboneliğinde sunucu yanıtını kaydet (sınır gerçek mi); `trades` kanalında
   `users` alanı var mı ve izlenen bir adresin dolumu görünüyor mu. Sonuç PR'a yazılır; sınır yoksa yalnız `userFills` yeterli olabilir.
3. **Kanıt taşıma:** deneme süresince elle — kullanıcı sunucuda `cat ozet.json` çıktısını yapıştırır (adres yok, takma ad var).
   Deploy key/R2 sunucuda secret gerektirir; ileride kullanıcıya sorulur.
4. **systemd `Restart=on-failure`** açık; yeniden başlama sayısı özete girer.
5. Sıra öne alındı: A4‑1'den hemen sonra H2 (7 günlük ölçüm saati erken başlasın); sonra A4‑3 → H1 → A4‑2 → A4‑4 → H5.

## İş (en küçük değişiklik seti)
- Adres sayısı yapılandırılabilir (1..N, üst sınır `kurallar.yaml` değil servis config'i); `faz3_preflight` 11 kalır.
- `--liste <yaml>`: `izleme_motoru.load_list` yeniden kullanılır (kural 7); K‑12.8 kapsamı (`ilk11`, `yedek11`, `paf`, `referans_*`).
  Kadro dosyası yoksa başlamaz (fail-closed).
- `trades` aboneliği + `users` süzme; `userFills` çapraz kontrol (≤ 10 adres).
- Mesaj alındığı anda `recv_ms` damgası; `isSnapshot` dolumları gecikme ve kabulden ayrı sayılır.
- `error` ve `subscriptionResponse` sayılır ve özetlenir (ham veri yazılmadan).
- Uygulama ping'i (`{"method":"ping"}`), dolgu `asyncio.to_thread` + sayfalama.
- 10 dk'da bir REST karşılaştırma: REST'te olup WS'de olmayan = **kaçan**.
- Saatlik `ozet.json`: trader (takma ad) başına n, gecikme medyan/p95/max (sn), kaçan, kopma, yeniden bağlanma, yeniden başlama.
- `requirements-dinleyici.txt` (websockets, PyYAML; pandas yok), `deploy/sg-dinleyici.service`, `docs/H2_KURULUM.md` (kullanıcı rehberi).
- Saat: rehberde `timedatectl` NTP kontrolü; özet saat kayması uyarısı (negatif gecikme sayısı) içerir.

## Altın örnekler (elle)
- Gecikmeler [0,4; 0,6; 1,0; 2,0; 5,0] sn → medyan 1,0; p95 en yakın sıra yöntemi → 5,0.
- `isSnapshot` dolumu → kabul 0, gecikme örneği 0.
- REST 5 dolum, WS 4 → kaçan 1. Aynı `tid` iki kez (biri `trades`, biri `userFills`) → tekil 1.
- Uç: boş liste (başlamaz), 0 dolumlu trader, tam sayfa sınırında dolgu, negatif gecikme (saat kayması) ayrı sayılır.

## Kabul
- `python -m pytest -q` tam paket yeşil.
- Adım 0 sonucu + 1 saatlik gerçek koşu özeti (kullanıcı sunucusunda) PR'a; göz kontrolü: gecikme medyanı birkaç sn içinde, kaçan = 0.
- Sonra 24 saat, sonra 7 gün. Bitti = 7 günlük özet.

## Kullanıcı rehberi içeriği (`docs/H2_KURULUM.md`, gizli bilgi yazdırmaz)
1. Windows PowerShell: `ssh-keygen -t ed25519`; yalnız `.pub` DigitalOcean → Settings → Security. Özel anahtar kimseyle paylaşılmaz.
2. Droplet: Singapore SGP1, Ubuntu 24.04, Basic 1 GB, SSH key.
3. `ssh root@<IP>`; kullanıcı `sg`; `apt install -y python3-venv git`; `timedatectl` (NTP açık).
4. `git clone` (repo açık, token yok); venv; `pip install -r requirements-dinleyici.txt`.
5. systemd birimi kopyala, `systemctl enable --now sg-dinleyici`.
6. Kontrol: `systemctl status`, `journalctl -u sg-dinleyici -n 50`, `cat /var/lib/sg-dinleyici/ozet.json`.
7. Durdurma: `systemctl stop sg-dinleyici`. DO güvenlik duvarı: yalnız 22 açık.
