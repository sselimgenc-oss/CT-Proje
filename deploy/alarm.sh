#!/usr/bin/env bash
# OnFailure alarmı: Telegram sendMessage (curl). TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID ortamdan (/etc/sg-canli.env). Token ASLA basılmaz (URL curl'e stdin ile verilir).
# Kullanım: alarm.sh [birim-adı]. Token/chat yoksa "atlandı" yazıp 0 ile çıkar (alarm zinciri ikinci bir hata üretmesin). GITHUB_ACTIONS gerektirmez.
set -u
BIRIM="${1:-sg-canli}"
if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] || [ -z "${TELEGRAM_CHAT_ID:-}" ]; then
  echo "alarm: Telegram anahtarı yok; atlandı (birim: ${BIRIM})"
  exit 0
fi
METIN="ALARM: ${BIRIM} servisi düştü ($(hostname 2>/dev/null || echo sunucu), $(date -u +%Y-%m-%dT%H:%MZ)). Sistem işlem kopyalamıyor olabilir: journalctl -u ${BIRIM}"
if printf 'url = "https://api.telegram.org/bot%s/sendMessage"\n' "${TELEGRAM_BOT_TOKEN}" | curl -sS -f --max-time 20 --config - \
     --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" --data-urlencode "text=${METIN}" -o /dev/null 2>/dev/null; then
  echo "alarm: gönderildi (${BIRIM})"
else
  echo "alarm: gönderilemedi (${BIRIM})" >&2
fi
exit 0
