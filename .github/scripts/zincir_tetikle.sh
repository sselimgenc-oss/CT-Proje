#!/usr/bin/env bash
# G3: GitHub cron geç kalıyor/kaçırıyor; vardiya zinciri ve saatlik sağlık tetiği. Kullanım: zincir_tetikle.sh vardiya|saglik
#   vardiya: motor NORMAL bitince bir sonraki vardiyayı `workflow_dispatch` ile tetikler (concurrency kuyruğu eskisi bitene kadar bekletir; kilit taze ise zamanlama_kontrol.sh atlar).
#   saglik : saglik.yml'yi tetikler (kendi cron'u ayrıca durur).
# YALNIZ main'de çalışır (dal denemeleri zincirlemez). Token ortamdan gelir (GH_TOKEN), asla yazdırılmaz. Hata sessiz yutulmaz: ::warning + (vardiya için) Telegram; çıkış 0 (yedek cron ve mevcut alarm sürer).
set -euo pipefail
hedef="${1:?vardiya|saglik}"
case "$hedef" in
  vardiya) dosya=canli_vardiya.yml ;;
  saglik) dosya=saglik.yml ;;
  *) echo "bilinmeyen hedef: $hedef" >&2; exit 1 ;;
esac
if [ "${GITHUB_REF:-}" != refs/heads/main ]; then
  echo "main değil (${GITHUB_REF:-?}): $hedef tetiği atlandı"
  exit 0
fi
if gh workflow run "$dosya" --ref main; then
  echo "$dosya tetiklendi ($hedef)"
  exit 0
fi
echo "::warning::$dosya tetiklenemedi ($hedef); yedek cron devrede"
if [ "$hedef" = vardiya ]; then
  if ! bash "$(dirname "$0")/vardiya_alarm.sh" zincir; then echo "::warning::zincir alarmı gönderilemedi"; fi
fi
exit 0
