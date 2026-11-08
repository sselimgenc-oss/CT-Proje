#!/usr/bin/env bash
# G-23 (denetim 08.11): Cloudflare Workers `sg-pano` yayını (K-40 ek) AYRI işte koşar: canli_vardiya.yml `pano` işi (contents: read, actions: read; yazma token'ı YOK).
# Vardiya işi (contents: write) wrangler'ı hiç çalıştırmaz, Cloudflare secret'larını görmez. Bu iş vardiya ile PARALEL koşar:
#   her PANO_ARALIK_SN (60 sn) vardiya işinin durumunu okur (gh api), veri dalındaki `canli-durum:pano/index.html`'i indirir; içerik değiştiyse yayımlar.
#   Vardiya işi `completed` olunca SON bir kez indirip (son yayım vardiyanın son adımında dala yazıldı) yayımlar ve biter. Tavan: PANO_TAVAN_SN (290 dk).
# Yalnız `canli-durum` (üretim) dalı; yalnız pano/index.html; yalnız iki secret de varsa. Yayın hatası işi KIRMIZI yapmaz ama GÖRÜNÜR (::warning).
# wrangler: `.github/pano/package-lock.json`'dan `npm ci` ile kurulmuş yerel ikili (WRANGLER); her çağrıda ağdan paket çözülmez.
set -euo pipefail
[ "${GITHUB_ACTIONS:-}" = true ] || { echo 'Yalnız GitHub Actions için.' >&2; exit 1; }
: "${GITHUB_REPOSITORY:?}" "${GITHUB_RUN_ID:?}"
veri_dali=canli-durum
aralik="${PANO_ARALIK_SN:-60}"
tavan="${PANO_TAVAN_SN:-17400}"
wrangler="${WRANGLER:-$(pwd)/.github/pano/node_modules/.bin/wrangler}"
if [ -z "${CLOUDFLARE_API_TOKEN:-}" ] || [ -z "${CLOUDFLARE_ACCOUNT_ID:-}" ]; then
  echo "Cloudflare secret'ları yok: pano yayını yapılmaz"
  exit 0
fi
[ -x "$wrangler" ] || { echo "wrangler kurulu değil: $wrangler (npm ci adımı)" >&2; exit 1; }
cf_dizin="$(mktemp -d)"
trap 'rm -rf "$cf_dizin"' EXIT
mkdir "$cf_dizin/site"                                                          # --assets=site: wrangler'ın .wrangler/ geçici dosyaları yayımlanmaz
son=""
bas="$(date -u +%s)"
yayimla() {
  if ! gh api -H "Accept: application/vnd.github.raw" "repos/${GITHUB_REPOSITORY}/contents/pano/index.html?ref=${veri_dali}" > "$cf_dizin/yeni.html" 2>/dev/null || [ ! -s "$cf_dizin/yeni.html" ]; then
    echo "pano/index.html okunamadı ($veri_dali); sonraki turda yeniden denenir"
    return 0
  fi
  local ozet
  ozet="$(sha256sum "$cf_dizin/yeni.html" | cut -d' ' -f1)"
  if [ "$ozet" = "$son" ]; then return 0; fi
  cp "$cf_dizin/yeni.html" "$cf_dizin/site/index.html"
  if ( cd "$cf_dizin" && WRANGLER_SEND_METRICS=false timeout -k 10 120 "$wrangler" deploy --assets=site --name sg-pano --compatibility-date=2026-11-01 >/dev/null ); then
    son="$ozet"
    echo "pano yayımlandı ($(date -u +%FT%TZ), ${ozet:0:12})"
  else
    echo "::warning::UYARI: Cloudflare pano yayını başarısız (sonraki turda yeniden denenir)"
  fi
}
while :; do
  durum=""
  if ! durum="$(gh api "repos/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}/jobs" --jq '[.jobs[] | select(.name == "vardiya")][0].status' 2>/dev/null)"; then durum=""; fi
  yayimla                                                                       # durum okunduktan SONRA indir: `completed` ise bu, vardiyanın son yayımıdır
  if [ "$durum" = completed ]; then echo "vardiya işi bitti: son pano yayımlandı"; exit 0; fi
  if [ $(( $(date -u +%s) - bas )) -ge "$tavan" ]; then echo "::warning::pano işi tavana (${tavan} sn) ulaştı; vardiya işi hâlâ '${durum:-okunamadı}'"; exit 0; fi
  sleep "$aralik"
done
