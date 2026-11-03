#!/usr/bin/env bash
# Yalnız Actions'ın geçici checkout'unda çalışır. Kapı sonuçları ve kesif.json `copytrade-kapi` veri dalına yazılır
# (main'e yazılmaz; dal yoksa yetim dal olarak açılır).
set -euo pipefail
[ "${GITHUB_ACTIONS:-}" = true ] || { echo 'Yalnız GitHub Actions için.' >&2; exit 1; }
: "${DAY:?}"; : "${MOD:?}"
[ -s "copytrade/kapi/$DAY/sonuc.csv" ] || { echo "copytrade/kapi/$DAY/sonuc.csv yok; yayımlanacak sonuç yok." >&2; exit 1; }
archive=$(mktemp -d)
archive_scripts=$(mktemp -d)
cp .github/scripts/son_yaz.py "$archive_scripts/"      # veri dalına geçince betik dizini kaybolur
trap 'rm -rf "$archive" "$archive_scripts"' EXIT
mkdir -p "$archive/copytrade/kapi"
cp -r "copytrade/kapi/$DAY" "$archive/copytrade/kapi/"
if [ "$MOD" != hizli ] && [ -s kesif/kesif.json ]; then mkdir -p "$archive/kesif"; cp kesif/kesif.json "$archive/kesif/"; fi
git config user.name 'github-actions[bot]'
git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
if git ls-remote --exit-code --heads origin refs/heads/copytrade-kapi >/dev/null; then
  git fetch origin copytrade-kapi
  git checkout -f -B copytrade-kapi FETCH_HEAD
else
  status=$?
  if [ "$status" -ne 2 ]; then exit "$status"; fi
  git checkout --orphan copytrade-kapi
  git rm -rfq --ignore-unmatch .
fi
cp -r "$archive"/. .
git add -f "copytrade/kapi/$DAY"
# Seçim raporunun yoğunlaşma hesabı bu dosyayı okur. Genel ignore kuralları
# değişse bile kapı günlüğü veri dalında açıkça yer almalıdır.
[ -f "copytrade/kapi/$DAY/gunluk.csv.gz" ] && git add -f "copytrade/kapi/$DAY/gunluk.csv.gz"
# İlk 11 işi ve izleme en son kapı tarihini buradan okur; diğer anahtarlar (ilk11) korunur. Eski bir günün yeniden koşusu işaretçiyi GERİ ALMAZ.
son_kapi=$(python3 -c "import json,os;print(json.load(open('son.json')).get('kapi','') if os.path.exists('son.json') else '')")
if [ -z "$son_kapi" ] || [ "$DAY" \> "$son_kapi" ] || [ "$DAY" = "$son_kapi" ]; then
  python3 "$archive_scripts/son_yaz.py" son.json kapi "$DAY"
  git add -f son.json
fi
[ -f kesif/kesif.json ] && git add -f kesif/kesif.json
if git diff --cached --quiet; then exit 0; fi
git commit -m "copytrade: CT-Kapı sonuçları $DAY ($MOD)"
for attempt in 1 2 3; do
  if git ls-remote --exit-code --heads origin refs/heads/copytrade-kapi >/dev/null; then
    git pull --rebase origin copytrade-kapi
  else
    status=$?
    if [ "$status" -ne 2 ]; then exit "$status"; fi
  fi
  if git push origin HEAD:copytrade-kapi; then exit 0; fi
  if [ "$attempt" -lt 3 ]; then sleep 5; fi
done
exit 1
