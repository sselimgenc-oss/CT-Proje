#!/usr/bin/env bash
# SUNUCU RADARI (K-78): günlük Form Radarı taraması + kadro + isabet + PBO + rastgele + holdout mührü, veri dalı `radar`'a yayım. .github/workflows/radar.yml'deki adımların AYNISI (formül/seçim kodu değişmedi; yalnız çalıştıran yer değişti:
# Actions cron'u ~7 sa geç tetikleniyordu → kadro 03:37 TSİ yerine ~10:42'de çıkıyordu). Zamanlayıcı: sg-sanal-radar.timer (00:37 UTC = 03:37 TSİ, Persistent). Actions'ta yalnız elle yedek (workflow_dispatch) kalır.
# Sır: tarama halka açık Hyperliquid verisini okur, ANAHTAR YOK. Push kimliği yalnız sunucudaki SSH deploy anahtarıdır (GIT_SSH_COMMAND, birimden). Telegram (isteğe bağlı) yalnız başarısızlıkta tek ⚠️ satır; başarıda mesaj YOK.
# Motorun çalışma dizinine DOKUNMAZ: kod için depodan geçici AYRI worktree (HEAD'de sabit; otomatik güncelleme ortada merge yapsa da koşu kendi kod kopyasıyla biter), yayım da o worktree'de (radar_yayimla.sh).
# Tek koşu: flock (RADAR_KILIT). Bugünün radar/<tarih>/havuz.json'u veri dalında varsa iş yapılmaz (Persistent yeniden koşusu / çift tetik; RADAR_ZORLA=1 ile atlanır).
# Bağımlılık: pandas/numpy canlı motorun venv'inde yok → ayrı venv (RADAR_VENV), requirements-radar.lock (sha256 kilitli) değişince kendiliğinden kurulur/yenilenir.
set -uo pipefail
veri_dali="${RADAR_VERI_DALI:-radar}"
case "$veri_dali" in radar|radar-deneme) ;; *) echo "Geçersiz RADAR_VERI_DALI: $veri_dali" >&2; exit 1 ;; esac
kaynak="${SANAL_DEPO:-$(pwd)}"
kilit_dosyasi="${RADAR_KILIT:-/var/lib/sg-sanal/radar.lock}"
venv="${RADAR_VENV:-/var/lib/sg-sanal/venv-radar}"
tg_env="${RADAR_TG_ENV:-/etc/sg-sanal-telegram.env}"
tg_api="${RADAR_TG_API:-https://api.telegram.org}"
log() { echo "radar: $*"; }

bildir() {   # tek ⚠️ satır (sesli); anahtar yoksa sessizce atlanır; token argv'ye/günlüğe girmez (curl'e stdin ile)
  local tok="${TELEGRAM_BOT_TOKEN:-}" chat="${TELEGRAM_CHAT_ID:-}"
  if { [ -z "$tok" ] || [ -z "$chat" ]; } && [ -r "$tg_env" ]; then
    tok="$(sed -n 's/^TELEGRAM_BOT_TOKEN=//p' "$tg_env" | tail -n1 | tr -d "\"'\r")"
    chat="$(sed -n 's/^TELEGRAM_CHAT_ID=//p' "$tg_env" | tail -n1 | tr -d "\"'\r")"
  fi
  if [ -z "$tok" ] || [ -z "$chat" ]; then log "telegram anahtarı yok; bildirim atlandı"; return 0; fi
  if printf 'url = "%s/bot%s/sendMessage"\n' "$tg_api" "$tok" | curl -sS -f --max-time 20 --config - \
       --data-urlencode "chat_id=$chat" --data-urlencode "text=[CT] $1" -o /dev/null 2>/dev/null; then log "bildirim gönderildi"; else log "bildirim gönderilemedi"; fi
  return 0
}
basarisiz() {   # $1 = adım adı, $2 = çıkış kodu
  log "HATA: $1 başarısız (çıkış $2)"
  bildir "⚠️ Radar sunucuda çalışmadı: $1 (kadro eski kalır; Actions'ta 'Radar' iş akışı elle başlatılabilir)"
  exit 1
}
kos() {   # kos <ad> <saniye> komut... : zaman aşımıyla çalıştırır; hata = başarısızlık (Actions'taki bash -e ile aynı)
  local ad="$1" sn="$2" rc; shift 2
  log "adım: $ad"
  timeout --kill-after=30 "$sn" "$@"; rc=$?
  [ "$rc" = 0 ] || basarisiz "$ad$([ "$rc" = 124 ] && echo ' (zaman aşımı)')" "$rc"
}

exec 9>"$kilit_dosyasi"
if ! flock -n 9; then log "başka bir radar koşusu sürüyor; çıkılıyor"; exit 0; fi
cd "$kaynak" || { log "depo yok: $kaynak"; exit 1; }

# Veri dalı + canlı kayıt dalı taze (isabet/pano `origin/<dal>` okur; tam geçmiş gerekir: depo tam klon).
git fetch -q origin "+refs/heads/$veri_dali:refs/remotes/origin/$veri_dali" || { log "UYARI: $veri_dali dalı çekilemedi"; }
git fetch -q origin "+refs/heads/canli-durum:refs/remotes/origin/canli-durum" 2>/dev/null || log "UYARI: canli-durum dalı çekilemedi (isabet ek grupları eksik kalabilir)"
bugun="$(date -u +%F)"
if [ "${RADAR_ZORLA:-}" != 1 ] && git cat-file -e "origin/$veri_dali:radar/$bugun/havuz.json" 2>/dev/null; then log "radar/$bugun/ veri dalında zaten var; iş yapılmadı"; exit 0; fi

work="$(mktemp -d)" || exit 1
trap 'git -C "$kaynak" worktree remove --force "$work" 2>/dev/null || rm -rf "$work"' EXIT
git worktree add -f --detach "$work" HEAD >/dev/null || basarisiz "kod worktree'si" 1
cd "$work" || exit 1

# Ayrı venv (canlı motorun venv'i pandas içermez). Kilit dosyasının sha256'sı damga; değişince yeniden kurulur.
if [ -n "${RADAR_PYTHON:-}" ]; then py="$RADAR_PYTHON"; else
  py="$venv/bin/python"
  lock_sha="$(sha256sum requirements-radar.lock | cut -d' ' -f1)"
  if [ ! -x "$py" ] || [ "$(cat "$venv/.lock_sha" 2>/dev/null)" != "$lock_sha" ]; then
    log "radar venv kuruluyor/yenileniyor"
    rm -rf "$venv"
    kos "venv oluşturma" 300 "${RADAR_PY3:-python3}" -m venv "$venv"
    kos "paket kurulumu (requirements-radar.lock)" 1200 "$venv/bin/pip" install -q --require-hashes -r requirements-radar.lock
    printf '%s\n' "$lock_sha" > "$venv/.lock_sha"
  fi
fi

mkdir -p radar
tutma=(); onceki=()
if git cat-file -e "origin/$veri_dali:radar/son/kadro.json" 2>/dev/null; then
  git show "origin/$veri_dali:radar/son/kadro.json" > "$work/onceki_kadro_tarama.json" && tutma=(--onceki-kadro "$work/onceki_kadro_tarama.json")
  git show "origin/$veri_dali:radar/son/kadro.json" > "$work/onceki_kadro.json" && onceki=(--onceki-kadro "$work/onceki_kadro.json")
fi
export VERI_DALI="$veri_dali"
# Süreler: tarama bütçesi radar_zaman_butcesi_dk 150 + pay (radar.yml iş zaman aşımı 210 dk karşılığı: toplam < birimin TimeoutStartSec'i).
kos "tarama" 10200 "$py" -u -m copytrade.radar_tarama --cikti radar --payda-yan-yana "${tutma[@]}" --ozet-md radar/OZET.md
havuz="$(ls radar/*/havuz.json 2>/dev/null | tail -n 1)"
[ -n "$havuz" ] || basarisiz "tarama (havuz.json yok)" 1
kos "kadro" 1500 "$py" -u -m copytrade.radar_kadro --havuz "$havuz" "${onceki[@]}"
kos "seçim isabeti" 2400 "$py" -u -m copytrade.radar_isabet --cikti radar --veri-dali "$veri_dali" --ozet-md radar/ISABET_OZET.md
kos "aşırı uydurma raporu" 900 "$py" -u -m copytrade.pbo_rapor --kok radar --veri-dali "$veri_dali" --cikti radar --ozet-md radar/ISABET_OZET.md
kos "rastgele karşılaştırma" 900 "$py" -u -m copytrade.radar_rastgele --kok radar --veri-dali "$veri_dali" --cikti radar --ozet-md radar/ISABET_OZET.md
ek=(); if [ -f copytrade/radar/HOLDOUT_KULLANIM.txt ]; then ek+=(--kullanim-dosya copytrade/radar/HOLDOUT_KULLANIM.txt); fi
kos "holdout mührü" 600 "$py" -u -m copytrade.holdout_muhur muhurla --kok radar --manifest radar/holdout/manifest.json --veri-dali "$veri_dali" "${ek[@]}"
# Yayım: aynı betik (Actions ile ortak); geçici worktree içinde veri dalına geçer; push kimliği = SSH deploy anahtarı (GIT_SSH_COMMAND).
kos "veri dalına yayım" 900 env RADAR_SUNUCU=1 RADAR_GIT_AD=sg-sanal-sunucu RADAR_GIT_EPOSTA=sg-sanal-sunucu@users.noreply.github.com bash .github/scripts/radar_yayimla.sh
log "tamam: radar/$(basename "$(dirname "$havuz")") yayımlandı"
exit 0
