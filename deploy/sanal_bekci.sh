#!/usr/bin/env bash
# Sunucu SANAL motoru: 60 dk BEKÇİ + otomatik geri dönüş (K-80; root; sg-sanal-bekci.service/.timer, 5 dk'da bir).
# Güncelleme betiği (sanal_guncelle.sh) başarılı NORMAL kurulumdan sonra $DURUM/bekci yazar (epoch / yeni sha / önceki sha / motor önceden aktif mi). Bu betik işaret varken her 5 dk'da sağlık sayaçlarına bakar:
#   motor yeniden başlama (günlük 'Scheduled restart job'), bekci_tetik, Telegram hata/429, hata olayları (adim/olay/defter) — hepsi KURULUMDAN BERİ sayılır — ve motor aktif değil (üst üste 2 tur).
# Eşik aşılırsa: SANAL_HEDEF_SHA=<önceki> SANAL_GERI_NEDEN=<neden> SANAL_KOTU_SHA=<yeni> ile sanal_guncelle.sh çağrılır (aynı geri alma yolu: durdur, reset, duman testi, başlat); tek ⚠️ "Yeni sürüm sorun çıkardı, önceki
#   sürüme dönüldü (neden)" gider; bozuk sha kotu_sha olur (sonraki pencerede aynı sürüm tekrar kurulmaz). 60 dk sorunsuz geçerse işaret silinir. Eşikler ortamdan (varsayılanlar aşağıda; elle ayar: systemctl edit sg-sanal-bekci).
# Güncelleme sürerken (kilit dolu) o tur atlanır. İşaretteki sha HEAD ile uyuşmuyorsa (araya elle geri alma/güncelleme girdi) işaret bayat sayılıp silinir. Telegram bildirimini sanal_guncelle.sh yapar; burada sır yok.
set -uo pipefail
DEPO="${SANAL_DEPO:-/var/lib/sg-sanal/depo}"
DURUM="${SANAL_DURUM_DIZIN:-/var/lib/sg-sanal-guncelle}"
KULLANICI="${SANAL_KULLANICI-sgsanal}"
SYSTEMCTL="${SANAL_SYSTEMCTL:-systemctl}"
JOURNALCTL="${SANAL_JOURNALCTL:-journalctl}"
KILIT="${SANAL_GUNCELLE_KILIT:-/run/sg-sanal-guncelle.lock}"
BEKCI="$DURUM/bekci"
PENCERE_SN="${BEKCI_PENCERE_SN:-3600}"            # izleme süresi
ESIK_YENIDEN="${BEKCI_ESIK_YENIDEN:-3}"           # kurulumdan beri motor yeniden başlama >= 3 (dayanıklılık alarmı da >2 der)
ESIK_TETIK="${BEKCI_ESIK_TETIK:-1}"               # bekçi motoru öldürdü >= 1 (motor donmuş demektir)
ESIK_TELEGRAM="${BEKCI_ESIK_TELEGRAM:-5}"         # telegram_hata + 429 >= 5 (saglik.py TELEGRAM_HATA_UYARI ile aynı)
ESIK_HATA="${BEKCI_ESIK_HATA:-8}"                 # adim_hata + olay_hata + defter_hata >= 8 (tek tek geçici HL hatalarına dayanıklı)
SAYAC="$(dirname "$0")/sanal_bekci_say.py"
log() { echo "bekci: $*"; }
as_user() { if [ -n "$KULLANICI" ] && [ "$(id -un)" != "$KULLANICI" ]; then runuser -u "$KULLANICI" -- "$@"; else "$@"; fi; }

[ -s "$BEKCI" ] || exit 0
{ read -r b_epoch; read -r b_yeni; read -r b_onceki; read -r b_motor; } < "$BEKCI" || true
if ! [[ "$b_epoch" =~ ^[0-9]+$ ]] || ! [[ "$b_yeni" =~ ^[0-9a-f]{40}$ ]] || ! [[ "$b_onceki" =~ ^[0-9a-f]{40}$ ]]; then log "işaret bozuk; silindi"; rm -f -- "$BEKCI"; exit 0; fi
mkdir -p "$DURUM"
if ! flock -n "$KILIT" true 2>/dev/null; then log "güncelleme sürüyor; bu tur atlandı"; exit 0; fi
head="$(as_user git -C "$DEPO" rev-parse HEAD 2>/dev/null)" || head=""
if [ "$head" != "$b_yeni" ]; then log "HEAD işaretteki sürüm değil; işaret bayat, silindi"; rm -f -- "$BEKCI" "$DURUM/bekci_pasif"; exit 0; fi
simdi="$(date +%s)"; gecen=$((simdi - b_epoch))
neden=""
ekle() { neden="${neden:+$neden, }$1"; }

yeniden="$("$JOURNALCTL" -u sg-sanal --since "@$b_epoch" -o cat --no-pager 2>/dev/null | grep -c 'Scheduled restart job' || true)"; [[ "$yeniden" =~ ^[0-9]+$ ]] || yeniden=0
[ "$yeniden" -ge "$ESIK_YENIDEN" ] && ekle "motor ${yeniden} kez yeniden başladı"
sayac="$(python3 -I "$SAYAC" "$DEPO/kayit" "$b_epoch" 2>/dev/null || echo '{}')"
sayi() { printf '%s' "$sayac" | python3 -c 'import json,sys
try: print(int(json.load(sys.stdin).get(sys.argv[1], 0)))
except Exception: print(0)' "$1"; }
tetik="$(sayi bekci_tetik)"; tg="$(sayi telegram)"; hata="$(sayi hata)"
[ "$tetik" -ge "$ESIK_TETIK" ] && ekle "bekçi motoru ${tetik} kez yeniden başlattı"
[ "$tg" -ge "$ESIK_TELEGRAM" ] && ekle "Telegram hata/429 ${tg}"
[ "$hata" -ge "$ESIK_HATA" ] && ekle "hata olayı ${hata}"
if [ "$b_motor" = 1 ] && [ ! -f "$DEPO/durum/DUR" ]; then   # motor aktif değil: üst üste 2 tur (systemd yeniden başlatma boşluğu tek turda yanlış alarm vermesin)
  if "$SYSTEMCTL" is-active --quiet sg-sanal; then rm -f -- "$DURUM/bekci_pasif"
  elif [ -f "$DURUM/bekci_pasif" ]; then ekle "motor aktif değil"
  else date +%s > "$DURUM/bekci_pasif"; log "motor aktif değil (ilk tur; bir sonrakinde hâlâ ise geri dönülür)"; fi
fi

if [ -n "$neden" ]; then
  log "EŞİK AŞILDI ($neden); önceki sürüme dönülüyor: ${b_yeni:0:7} -> ${b_onceki:0:7}"
  rm -f -- "$DURUM/bekci_pasif"
  SANAL_HEDEF_SHA="$b_onceki" SANAL_GERI_NEDEN="$neden" SANAL_KOTU_SHA="$b_yeni" bash "$(dirname "$0")/sanal_guncelle.sh" || log "UYARI: geri dönüş betiği hata verdi (elle bakın: journalctl -u sg-sanal-guncelle)"
  rm -f -- "$BEKCI"
  exit 0
fi
if [ "$gecen" -ge "$PENCERE_SN" ]; then log "60 dk sorunsuz geçti (yeniden=${yeniden} tetik=${tetik} tg=${tg} hata=${hata}); bekçi bitti"; rm -f -- "$BEKCI" "$DURUM/bekci_pasif"; exit 0; fi
log "izleniyor: $((gecen / 60)) dk; yeniden=${yeniden} tetik=${tetik} tg=${tg} hata=${hata}"
exit 0
