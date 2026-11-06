#!/usr/bin/env bash
# Vardiya/kontrol işi başarısız olunca Telegram alarmı (G1). Kullanım: vardiya_alarm.sh <kontrol|vardiya>
# `curl` ile (pip gerekmez). Token/chat YALNIZ main koşusunda ortamda dolu gelir (B1); yoksa sessiz geçer. Secret asla yazdırılmaz.
set -euo pipefail
is_adi="${1:-vardiya}"
if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] || [ -z "${TELEGRAM_CHAT_ID:-}" ]; then
  echo "Telegram anahtarı yok (deneme dalı ya da tanımsız): alarm atlandı"
  exit 0
fi
if [ "$is_adi" = "kontrol" ]; then
  adim="zamanlama kontrolü"
elif [ "${ADIM_GERI:-}" = "failure" ]; then
  adim="durumu geri yükleme"
elif [ "${ADIM_ACILIS:-}" = "failure" ]; then
  adim="açılış kontrolü"
elif [ "${ADIM_MOTOR:-}" = "failure" ]; then
  adim="canlı motor (çıkış kodu 3 = BAŞLAMADI)"
else
  adim="kurulum / sonraki adım"
fi
metin="🚨 Vardiya BAŞLAMADI/ÇÖKTÜ (${is_adi}): ${RUN_URL:-?}
adım: ${adim}"
if ! curl -fsS --max-time 30 --retry 2 -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" --data-urlencode "text=${metin}" >/dev/null 2>&1; then
  echo "Telegram alarmı gönderilemedi" >&2
  exit 1
fi
echo "Telegram alarmı gönderildi"
