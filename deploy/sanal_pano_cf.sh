#!/usr/bin/env bash
# Sunucu SANAL motoru: Cloudflare Workers pano yayını (sg-sanal-pano.timer, dakikada bir). .github/scripts/pano_cf_yayimla.sh'in sunucu karşılığı.
# Kaynak: depo klonundaki pano/index.html (sanal_yayimla.sh her 15 dk yeniden üretir; Actions'taki veri dalı okumasıyla aynı içerik). İçerik DEĞİŞTİYSE yayımlanır (sha256; son yayım: /var/lib/sg-sanal/pano_son.sha).
# Ortam: /etc/sg-sanal-mod.env (SUNUCU_MOD, PANO_ISIM) + /etc/sg-sanal-pano.env (CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID; yalnız bu birimde; HL/Telegram/git anahtarı burada YOK).
# Güvence: yalnız uretim ↔ sg-pano (eski deneme modu kaldırıldı). Çift uyuşmazsa çıkış 3. İki Cloudflare secret'ı yoksa yayım yapılmaz (çıkış 0).
set -euo pipefail
cd "${SANAL_DEPO:-/var/lib/sg-sanal/depo}"
mod="${SUNUCU_MOD:?SUNUCU_MOD gerekli}"
isim="${PANO_ISIM:?PANO_ISIM gerekli}"
case "$mod:$isim" in
  uretim:sg-pano) ;;
  *) echo "HATA: geçersiz mod/pano adı ($mod / $isim): yalnız uretim=sg-pano geçerli" >&2; exit 3 ;;
esac
if [ -z "${CLOUDFLARE_API_TOKEN:-}" ] || [ -z "${CLOUDFLARE_ACCOUNT_ID:-}" ]; then
  echo "Cloudflare secret'ları yok: pano yayını yapılmaz"
  exit 0
fi
wrangler="${WRANGLER:-$(pwd)/.github/pano/node_modules/.bin/wrangler}"
[ -x "$wrangler" ] || { echo "wrangler kurulu değil: $wrangler (npm ci adımı: deploy/kurulum_sanal.md)" >&2; exit 1; }
[ -s pano/index.html ] || { echo "pano/index.html henüz yok; sonraki turda"; exit 0; }
son_dosya="${PANO_SON:-/var/lib/sg-sanal/pano_son.sha}"
ozet="$(sha256sum pano/index.html | cut -d' ' -f1)"
if [ -f "$son_dosya" ] && [ "$(cat "$son_dosya")" = "$ozet:$isim" ]; then exit 0; fi
gecici="$(mktemp -d)"
trap 'rm -rf "$gecici"' EXIT
mkdir "$gecici/site"                                                      # --assets=site: wrangler'ın .wrangler/ geçici dosyaları yayımlanmaz
cp pano/index.html "$gecici/site/index.html"
printf '/*\n  Content-Security-Policy: frame-ancestors '"'"'self'"'"' https://orkestra-kapi.sselimgenc-c18.workers.dev\n' > "$gecici/site/_headers"   # tek pano kapısı (orkestratör, 19.11): yalnız kendi alanı + kapı iframe'de açabilir
if ( cd "$gecici" && WRANGLER_SEND_METRICS=false timeout -k 10 120 "$wrangler" deploy --assets=site --name "$isim" --compatibility-date=2026-11-01 >/dev/null ); then
  printf '%s' "$ozet:$isim" > "$son_dosya"
  echo "pano yayımlandı ($(date -u +%FT%TZ), $isim, ${ozet:0:12})"
else
  echo "UYARI: Cloudflare pano yayını başarısız ($isim); sonraki turda yeniden denenir" >&2
  exit 1
fi
