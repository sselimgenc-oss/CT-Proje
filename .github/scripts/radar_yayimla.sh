#!/usr/bin/env bash
# Yalnız Actions'ın geçici checkout'unda çalışır; kullanıcı checkout'unda çalıştırmayın.
# Veri dalı `radar` (main'den) ya da `radar-deneme` (dal doğrulaması; `VERI_DALI`): radar/<tarih>/{havuz,kadro}.json + radar/son/kadro.json; 90 günden eski tarihli klasörler silinir. Kök commit yalnız dal ilk kez oluşurken (orphan); sonra düz commit.
set -euo pipefail
[ "${GITHUB_ACTIONS:-}" = true ] || { echo 'Yalnız GitHub Actions için.' >&2; exit 1; }
veri_dali="${VERI_DALI:-radar}"
case "$veri_dali" in radar|radar-deneme) ;; *) echo "Geçersiz VERI_DALI: $veri_dali" >&2; exit 1 ;; esac
tarih_klasoru="$(ls -d radar/????-??-?? | tail -n 1)"
gun="$(basename "$tarih_klasoru")"
[ -s "$tarih_klasoru/havuz.json" ] && [ -s "$tarih_klasoru/kadro.json" ]
archive=$(mktemp -d)
trap 'rm -rf "$archive"' EXIT
cp "$tarih_klasoru/havuz.json" "$tarih_klasoru/kadro.json" "$archive/"
# GitHub 100 MB sınırı için yayımlanan her dosya 90 MB altında olmalı.
for f in "$archive"/*; do
  if [ "$(stat -c %s "$f")" -gt 94371840 ]; then echo "Çok büyük: $(basename "$f") ($(stat -c %s "$f") bayt)" >&2; exit 1; fi
done
git config user.name 'github-actions[bot]'
git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
if git ls-remote --exit-code --heads origin "$veri_dali" >/dev/null; then
  git fetch origin "$veri_dali"
  git checkout -f -B "$veri_dali" FETCH_HEAD
else
  status=$?
  if [ "$status" -ne 2 ]; then exit "$status"; fi
  git checkout --orphan "$veri_dali"
  git rm -rfq --ignore-unmatch .
fi
mkdir -p "radar/$gun" radar/son
cp "$archive/havuz.json" "$archive/kadro.json" "radar/$gun/"
cp "$archive/kadro.json" radar/son/kadro.json
# 90 gün tutma: tarihli klasörlerden eski olanları sil (YYYY-MM-DD sözlük sırası = tarih sırası).
sinir="$(date -u -d '90 days ago' +%F)"
for d in radar/????-??-??; do
  if [[ "$(basename "$d")" < "$sinir" ]]; then git rm -rq --ignore-unmatch "$d"; rm -rf "$d"; fi
done
git add -f "radar/$gun/havuz.json" "radar/$gun/kadro.json" radar/son/kadro.json
if git diff --cached --quiet; then exit 0; fi
git commit -m "radar: günlük havuz + kadro $gun"
for attempt in 1 2 3; do
  if git ls-remote --exit-code --heads origin "$veri_dali" >/dev/null; then
    git pull --rebase origin "$veri_dali"
  else
    status=$?
    if [ "$status" -ne 2 ]; then exit "$status"; fi
  fi
  if git push origin "HEAD:$veri_dali"; then exit 0; fi
  if [ "$attempt" -lt 3 ]; then sleep 5; fi
done
exit 1
