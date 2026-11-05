#!/usr/bin/env bash
# Yalnız Actions'ın geçici checkout'unda çalışır. Canlı motor durumunu veri dalına (VERI_DALI: canli-durum | canli-durum-deneme) yazar: durum/*.json, durum/niyet.jsonl (çift emir koruması, vardiyalar arası kalıcı), durum/DUR (varsa), pano/OZET.md + pano/gecmis.json (T6 günlük rapor, varsa), kayit/<tarih>.jsonl.
# AYRI git worktree'de çalışır: motorun çalıştığı çalışma dizini DEĞİŞMEZ (arka planda 15 dk'da bir çağrılır). Kayıt 14 günden eskisi silinir. Kök commit yalnız dal ilk kez oluşurken (orphan).
set -euo pipefail
[ "${GITHUB_ACTIONS:-}" = true ] || { echo 'Yalnız GitHub Actions için.' >&2; exit 1; }
veri_dali="${VERI_DALI:-canli-durum}"
case "$veri_dali" in canli-durum|canli-durum-deneme) ;; *) echo "Geçersiz VERI_DALI: $veri_dali" >&2; exit 1 ;; esac
kaynak="$(pwd)"
# Cloudflare Workers `sg-pano` yayını (K-40 ek; yalnız ana dal `canli-durum`, yalnız pano/index.html; yalnız iki secret de varsa). Cloudflare'in kendi build sistemi takıldığı için yayın buradan yapılır.
# Durum push'undan SONRA çağrılır (yayım gecikse bile çift emir koruması `niyet.jsonl` zamanında yazılır). Anahtar yalnız "Workers düzenle" yetkili; log'da GitHub gizler. Hata yayımı durdurmaz ama GÖRÜNÜR.
cf_yayin() {
  if [ "$veri_dali" = canli-durum ] && [ -s "$kaynak/pano/index.html" ] && [ -n "${CLOUDFLARE_API_TOKEN:-}" ] && [ -n "${CLOUDFLARE_ACCOUNT_ID:-}" ]; then
    local cf_dizin
    cf_dizin="$(mktemp -d)"
    mkdir "$cf_dizin/site"                                                      # --assets=site: wrangler'ın .wrangler/ geçici dosyaları yayımlanmaz
    cp "$kaynak/pano/index.html" "$cf_dizin/site/index.html"
    if ! ( cd "$cf_dizin" && WRANGLER_SEND_METRICS=false timeout -k 10 120 npx --yes wrangler@4.158.0 deploy --assets=site --name sg-pano --compatibility-date=2026-11-01 >/dev/null ); then
      echo "UYARI: Cloudflare pano yayını başarısız (durum yayımı sürer)" >&2
    fi
    rm -rf "$cf_dizin"
  fi
}
[ -d "$kaynak/durum" ] || { echo 'durum/ yok: yayımlanacak bir şey yok'; exit 0; }
work="$(mktemp -d)"
trap 'git -C "$kaynak" worktree remove --force "$work" 2>/dev/null || rm -rf "$work"' EXIT
git config user.name 'github-actions[bot]'
git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
if git ls-remote --exit-code --heads origin "$veri_dali" >/dev/null; then
  git fetch origin "$veri_dali"
  git worktree add -f -B "$veri_dali" "$work" FETCH_HEAD
else
  status=$?
  if [ "$status" -ne 2 ]; then exit "$status"; fi
  git worktree add -f --detach "$work" HEAD
  git -C "$work" checkout --orphan "$veri_dali"
  git -C "$work" rm -rfq --ignore-unmatch .
fi
# Pano (B7): her yayımda (15 dk) güncel `pano/OZET.md` + `pano/index.html`. `--vardiya`: ozet.json başka vardiyadansa (bayat) pano YAZILMAZ. Hata yayımı durdurmaz ama GÖRÜNÜR (stderr uyarısı; sessizce yutulmaz).
if [ -s "$kaynak/durum/ozet.json" ]; then
  if ! python -u -m copytrade.canli.pano --durum durum --kayit kayit --gecmis pano/gecmis.json --cikti pano/OZET.md --html pano/index.html --vardiya "${GITHUB_RUN_ID:-}" ${KADRO_DALI:+--isabet-dali "$KADRO_DALI"} >/dev/null; then
    echo "UYARI: pano üretilemedi (durum yayımı sürer)" >&2
  fi
fi
mkdir -p "$work/durum" "$work/kayit"
for f in hesap.json saha.json risk.json motor.json kilit.json ozet.json niyet.jsonl DUR; do
  if [ -f "$kaynak/durum/$f" ]; then cp "$kaynak/durum/$f" "$work/durum/$f"; fi
done
if [ -d "$kaynak/kayit" ]; then cp -r "$kaynak/kayit/." "$work/kayit/"; fi
if [ -s "$kaynak/pano/OZET.md" ]; then mkdir -p "$work/pano"; cp "$kaynak/pano/OZET.md" "$work/pano/OZET.md"; fi
if [ -s "$kaynak/pano/index.html" ]; then mkdir -p "$work/pano"; cp "$kaynak/pano/index.html" "$work/pano/index.html"; fi
if [ -s "$kaynak/pano/gecmis.json" ]; then mkdir -p "$work/pano"; cp "$kaynak/pano/gecmis.json" "$work/pano/gecmis.json"; fi
# GitHub 100 MB sınırı: yayımlanan her dosya 90 MB altında olmalı.
for f in "$work"/durum/* "$work"/kayit/*; do
  [ -f "$f" ] || continue
  if [ "$(stat -c %s "$f")" -gt 94371840 ]; then echo "Çok büyük: $(basename "$f")" >&2; exit 1; fi
done
sinir="$(date -u -d '14 days ago' +%F)"
for f in "$work"/kayit/*.jsonl; do
  [ -f "$f" ] || continue
  if [[ "$(basename "$f" .jsonl)" < "$sinir" ]]; then git -C "$work" rm -q --ignore-unmatch -f "kayit/$(basename "$f")"; rm -f "$f"; fi
done
git -C "$work" add -f durum kayit
if [ -d "$work/pano" ]; then git -C "$work" add -f pano; fi
if git -C "$work" diff --cached --quiet; then cf_yayin; exit 0; fi
git -C "$work" commit -q -m "canli: durum $(date -u +%FT%TZ)"
for attempt in 1 2 3; do
  if git ls-remote --exit-code --heads origin "$veri_dali" >/dev/null; then
    git -C "$work" pull -q --rebase origin "$veri_dali"
  else
    status=$?
    if [ "$status" -ne 2 ]; then exit "$status"; fi
  fi
  if git -C "$work" push -q origin "HEAD:$veri_dali"; then cf_yayin; exit 0; fi
  if [ "$attempt" -lt 3 ]; then sleep 5; fi
done
exit 1
