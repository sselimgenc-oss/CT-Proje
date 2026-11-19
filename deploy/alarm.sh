#!/usr/bin/env bash
# OnFailure alarmı: Telegram sendMessage (curl). TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID ortamdan (/etc/sg-canli-telegram.env; G-22: HL anahtarı bu birimde YOK). Token ASLA basılmaz (URL curl'e stdin ile verilir).
# Kullanım: alarm.sh [birim-adı]. Token/chat yoksa "atlandı" yazıp 0 ile çıkar (alarm zinciri ikinci bir hata üretmesin). GITHUB_ACTIONS gerektirmez.
set -u
BIRIM="${1:-sg-canli}"
if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] || [ -z "${TELEGRAM_CHAT_ID:-}" ]; then
  echo "alarm: Telegram anahtarı yok; atlandı (birim: ${BIRIM})"
  exit 0
fi
METIN="[CT] CRIT
Servis durdu: ${BIRIM} ($(date -u +%H:%M) UTC). Sistem işlem kopyalamıyor olabilir.
Sunucu servisi yeniden başlatmayı deniyor.
Sorun sürerse sunucuya bakman gerekebilir."
if printf 'url = "https://api.telegram.org/bot%s/sendMessage"\n' "${TELEGRAM_BOT_TOKEN}" | curl -sS -f --max-time 20 --config - \
     --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" --data-urlencode "text=${METIN}" -o /dev/null 2>/dev/null; then
  echo "alarm: gönderildi (${BIRIM})"
else
  echo "alarm: gönderilemedi (${BIRIM})" >&2
fi
exit 0
