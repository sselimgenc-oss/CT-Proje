#!/usr/bin/env bash
# "Bot durdu" İKİNCİ sesli mesajı: bot 20 dk içinde dönmediyse (motor `durum/tg_bot_durdu` işaretini bırakmış, yeniden çalışınca `baslat` siler) bir kez daha uyarır.
# Çalıştıran: sg-sanal-ikinci-alarm.timer (5 dk'da bir) ve ek olarak sanal_guncelle.sh alarm_kontrol (saatlik yedek). Motor ölüyken de çalışır (motor içinde çözülemez).
# Ortam: ALARM_DURUM_DIZIN (örn. /var/lib/sg-sanal/depo/durum), ALARM_BIRIM (varsayılan sg-sanal), ALARM_BEKLE_SN (varsayılan 1200), token/chat ortamdan ya da ALARM_TG_ENV dosyasından. Token ASLA basılmaz.
set -u
DURUM="${ALARM_DURUM_DIZIN:-}"
BIRIM="${ALARM_BIRIM:-sg-sanal}"
BEKLE="${ALARM_BEKLE_SN:-1200}"
TG_ENV="${ALARM_TG_ENV:-/etc/sg-sanal-telegram.env}"
[ -n "$DURUM" ] && [ -f "$DURUM/tg_bot_durdu" ] && [ ! -f "$DURUM/tg_bot_durdu_2" ] || exit 0
bas="$(head -n1 "$DURUM/tg_bot_durdu" 2>/dev/null | tr -dc '0-9')"
[[ "$bas" =~ ^[0-9]{9,}$ ]] || exit 0
simdi="$(date +%s)"
gecen=$((simdi - bas))
[ "$gecen" -ge "$BEKLE" ] || exit 0
if "${SYSTEMCTL:-systemctl}" is-active --quiet "$BIRIM" 2>/dev/null; then exit 0; fi       # bot çalışıyor: (motor işareti yakında siler) mesaj yok
TOK="${TELEGRAM_BOT_TOKEN:-}"; CHAT="${TELEGRAM_CHAT_ID:-}"
if { [ -z "$TOK" ] || [ -z "$CHAT" ]; } && [ -r "$TG_ENV" ]; then
  TOK="$(sed -n 's/^TELEGRAM_BOT_TOKEN=//p' "$TG_ENV" | tail -n1 | tr -d "\"'\r")"
  CHAT="$(sed -n 's/^TELEGRAM_CHAT_ID=//p' "$TG_ENV" | tail -n1 | tr -d "\"'\r")"
fi
if [ -z "$TOK" ] || [ -z "$CHAT" ]; then echo "alarm_ikinci: Telegram anahtarı yok; atlandı"; exit 0; fi
NEDEN="$(sed -n '2p' "$DURUM/tg_bot_durdu" 2>/dev/null | tr -d '\r')"
[ -n "$NEDEN" ] || NEDEN="bilinmiyor"
POZ="bilinmiyor"
if [ -r "$DURUM/hesap.json" ]; then
  POZ="$(python3 -c 'import json,sys
d=json.load(open(sys.argv[1]))
print(sum(len(c) for c in (d.get("poz") or {}).values()))' "$DURUM/hesap.json" 2>/dev/null || echo bilinmiyor)"
fi
case "$POZ" in 0) STOP="gerekmiyor (pozisyon yok)";; bilinmiyor) STOP="bilinmiyor";; *) STOP="bot kapalıyken yazılım stopu çalışmıyor";; esac
METIN="[CT] 🔴 Bot hâlâ kapalı ($((gecen / 60)) dk)
Neden: ${NEDEN}
Açık pozisyon: ${POZ} · Stop: ${STOP}
Senden: orkestratöre 'CT botu durdu' yaz."
if printf 'url = "https://api.telegram.org/bot%s/sendMessage"\n' "$TOK" | curl -sS -f --max-time 20 --config - \
     --data-urlencode "chat_id=$CHAT" --data-urlencode "text=${METIN}" -o /dev/null 2>/dev/null; then
  date +%s > "$DURUM/tg_bot_durdu_2"
  echo "alarm_ikinci: gönderildi"
else
  echo "alarm_ikinci: gönderilemedi" >&2
fi
exit 0
