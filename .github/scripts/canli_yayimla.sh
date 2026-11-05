#!/usr/bin/env bash
# Yalnız Actions'ın geçici checkout'unda çalışır. Canlı motor durumunu veri dalına (VERI_DALI: canli-durum | canli-durum-deneme) yazar: durum/*.json, durum/DUR (varsa), pano/OZET.md + pano/gecmis.json (T6 günlük rapor, varsa), kayit/<tarih>.jsonl.
# AYRI git worktree'de çalışır: motorun çalıştığı çalışma dizini DEĞİŞMEZ (arka planda 15 dk'da bir çağrılır). Kayıt 14 günden eskisi silinir. Kök commit yalnız dal ilk kez oluşurken (orphan).
set -euo pipefail
[ "${GITHUB_ACTIONS:-}" = true ] || { echo 'Yalnız GitHub Actions için.' >&2; exit 1; }
veri_dali="${VERI_DALI:-canli-durum}"
case "$veri_dali" in canli-durum|canli-durum-deneme) ;; *) echo "Geçersiz VERI_DALI: $veri_dali" >&2; exit 1 ;; esac
kaynak="$(pwd)"
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
mkdir -p "$work/durum" "$work/kayit"
for f in hesap.json saha.json risk.json motor.json kilit.json ozet.json DUR; do
  if [ -f "$kaynak/durum/$f" ]; then cp "$kaynak/durum/$f" "$work/durum/$f"; fi
done
if [ -d "$kaynak/kayit" ]; then cp -r "$kaynak/kayit/." "$work/kayit/"; fi
if [ -s "$kaynak/pano/OZET.md" ]; then mkdir -p "$work/pano"; cp "$kaynak/pano/OZET.md" "$work/pano/OZET.md"; fi
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
if git -C "$work" diff --cached --quiet; then exit 0; fi
git -C "$work" commit -q -m "canli: durum $(date -u +%FT%TZ)"
for attempt in 1 2 3; do
  if git ls-remote --exit-code --heads origin "$veri_dali" >/dev/null; then
    git -C "$work" pull -q --rebase origin "$veri_dali"
  else
    status=$?
    if [ "$status" -ne 2 ]; then exit "$status"; fi
  fi
  if git -C "$work" push -q origin "HEAD:$veri_dali"; then exit 0; fi
  if [ "$attempt" -lt 3 ]; then sleep 5; fi
done
exit 1
