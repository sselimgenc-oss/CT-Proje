#!/usr/bin/env bash
# Yalnız Actions'ın geçici checkout'unda çalışır; kullanıcı checkout'unda çalıştırmayın.
# Veri dalı `radar` (main'den) ya da `radar-deneme` (dal doğrulaması; `VERI_DALI`): radar/<tarih>/{havuz,kadro}.json + radar/son/kadro.json; 90 günden eski tarihli klasörler silinir. Kök commit yalnız dal ilk kez oluşurken (orphan); sonra düz commit.
# Denetim R-1: günün İLK yayımı ayrıca radar/<tarih>/{kadro_ilk,havuz_ilk}.json olarak saklanır ve ASLA üzerine yazılmaz (motor K-39 ile günün ilk kadrosunu uygular; §7b isabeti onu ölçer).
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
# T6: önceki günlerin `isabet.json` dosyaları (7 gün önceki havuz için bugün ölçülür) da yayımlanır
mkdir -p "$archive/isabet"
for d in radar/????-??-??; do
  if [ -s "$d/isabet.json" ]; then mkdir -p "$archive/isabet/$(basename "$d")"; cp "$d/isabet.json" "$archive/isabet/$(basename "$d")/"; fi
done
# GitHub 100 MB sınırı için yayımlanan her dosya 90 MB altında olmalı.
for f in "$archive"/*.json "$archive"/isabet/*/isabet.json; do
  [ -f "$f" ] || continue
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
if [ ! -e "radar/$gun/kadro_ilk.json" ] && ! git cat-file -e "HEAD:radar/$gun/kadro.json" 2>/dev/null; then
  # Günün ilk yayımı (veri dalında o günün kadrosu henüz yok): ilk kadro + aynı koşunun havuzu korunur; aynı günün sonraki yayımları bu iki dosyaya dokunmaz.
  # Bu değişiklikten ÖNCE yayımlanmış bir günde (kadro.json var, kadro_ilk.json yok) ikinci yayım kadro_ilk.json YAZMAZ (yanlış "ilk" olurdu); isabet onu git geçmişinden kurar.
  cp "$archive/kadro.json" "radar/$gun/kadro_ilk.json"
  cp "$archive/havuz.json" "radar/$gun/havuz_ilk.json"
  git add -f "radar/$gun/kadro_ilk.json" "radar/$gun/havuz_ilk.json"
fi
for f in "$archive"/isabet/*/isabet.json; do
  [ -f "$f" ] || continue
  g="$(basename "$(dirname "$f")")"
  mkdir -p "radar/$g"
  cp "$f" "radar/$g/isabet.json"
  git add -f "radar/$g/isabet.json"
done
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
