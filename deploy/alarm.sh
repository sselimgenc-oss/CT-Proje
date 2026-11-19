#!/usr/bin/env bash
# OnFailure alarmı: Telegram sendMessage (curl). TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID ortamdan (/etc/sg-canli-telegram.env; G-22: HL anahtarı bu birimde YOK). Token ASLA basılmaz (URL curl'e stdin ile verilir).
# Kullanım: alarm.sh [birim-adı]. Token/chat yoksa "atlandı" yazıp 0 ile çıkar (alarm zinciri ikinci bir hata üretmesin). GITHUB_ACTIONS gerektirmez.
set -u
BIRIM="${1:-sg-canli}"
if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] || [ -z "${TELEGRAM_CHAT_ID:-}" ]; then
  echo "alarm: Telegram anahtarı yok; atlandı (birim: ${BIRIM})"
  exit 0
fi
# açık pozisyon sayısı: ALARM_DURUM_DIZIN (ör. /var/lib/sg-sanal/depo/durum) verilmişse diskteki defterden; yoksa "bilinmiyor". Aynı dizine `tg_bot_durdu` işareti yazılır → motor yeniden çalışınca tek "Düzeldi" yollar.
POZ="bilinmiyor"
if [ -n "${ALARM_DURUM_DIZIN:-}" ] && [ -r "${ALARM_DURUM_DIZIN}/hesap.json" ]; then
  POZ="$(python3 -c 'import json,sys
d=json.load(open(sys.argv[1]))
print(sum(len(c) for c in (d.get("poz") or {}).values()))' "${ALARM_DURUM_DIZIN}/hesap.json" 2>/dev/null || echo bilinmiyor)"
  printf '%s\nservis düştü (%s)\n' "$(date +%s)" "${BIRIM}" > "${ALARM_DURUM_DIZIN}/tg_bot_durdu" 2>/dev/null || true; rm -f "${ALARM_DURUM_DIZIN}/tg_bot_durdu_2" 2>/dev/null
fi
case "$POZ" in 0) STOP="gerekmiyor (pozisyon yok)";; bilinmiyor) STOP="bilinmiyor";; *) STOP="bot kapalıyken yazılım stopu çalışmıyor";; esac
METIN="[CT] 🔴 Bot durdu
Neden: servis düştü (${BIRIM}, $(date -u +%H:%M) UTC).
Açık pozisyon: ${POZ} · Stop: ${STOP}
Sistem servisi yeniden başlatmayı deniyor.
Sorun sürerse bana haber ver."
if printf 'url = "https://api.telegram.org/bot%s/sendMessage"\n' "${TELEGRAM_BOT_TOKEN}" | curl -sS -f --max-time 20 --config - \
     --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" --data-urlencode "text=${METIN}" -o /dev/null 2>/dev/null; then
  echo "alarm: gönderildi (${BIRIM})"
else
  echo "alarm: gönderilemedi (${BIRIM})" >&2
fi
exit 0
