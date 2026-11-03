#!/usr/bin/env bash
# Yalnız Actions'ın geçici checkout'unda çalışır; kullanıcı checkout'unda çalıştırmayın.
set -euo pipefail
[ "${GITHUB_ACTIONS:-}" = true ] || { echo 'Yalnız GitHub Actions için.' >&2; exit 1; }
archive=$(mktemp -d)
trap 'rm -rf "$archive"' EXIT
# Veri dalına geçince main'in dosyaları kaybolur: arşiv yardımcısını önceden kopyala (A4-2).
cp "$(cd "$(dirname "$0")" && pwd)/olay_arsivle.py" "$archive.olay_arsivle.py"
trap 'rm -rf "$archive" "$archive.olay_arsivle.py"' EXIT
for path in durum.json binance_vadeli.txt kararlar.jsonl degisim.json gecikme.json olay_tasan.jsonl; do
  if [ -f "izleme/$path" ]; then cp "izleme/$path" "$archive/"; fi
done
[ -s "$archive/durum.json" ]
# motor.json R2'de tutulur (izleme.yml); GitHub 100 MB sınırı için yayımlanan her dosya 90 MB altında olmalı.
for f in "$archive"/*; do
  if [ "$(stat -c %s "$f")" -gt 94371840 ]; then echo "Çok büyük: $(basename "$f") ($(stat -c %s "$f") bayt)" >&2; exit 1; fi
done
git config user.name 'github-actions[bot]'
git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
if git ls-remote --exit-code --heads origin copytrade-izleme >/dev/null; then
  git fetch origin copytrade-izleme
  git checkout -f -B copytrade-izleme FETCH_HEAD
else
  status=$?
  if [ "$status" -ne 2 ]; then exit "$status"; fi
  git checkout --orphan copytrade-izleme
  git rm -rfq --ignore-unmatch .
fi
mkdir -p izleme
cp -r "$archive"/. izleme/
# A4-2: yayın penceresinden (son 200) taşan olaylar kalıcı arşive eklenir (eklemeli, kimlik başına tekil, mevcut kayıt değişmez); geçici taşan dosyası dala girmez.
if [ -f izleme/olay_tasan.jsonl ]; then
  python3 "$archive.olay_arsivle.py" izleme/olay_tasan.jsonl izleme/olay_arsivi.jsonl
  rm -f izleme/olay_tasan.jsonl
fi
# Eski motor.json veri dalından kaldırılır (artık R2'de).
git rm -q --cached --ignore-unmatch izleme/motor.json
# Worker'ın kararlar.jsonl dosyası ve diğer arşivleri korunur.
for path in durum.json binance_vadeli.txt kararlar.jsonl degisim.json gecikme.json olay_arsivi.jsonl; do
  if [ -f "izleme/$path" ]; then git add -f "izleme/$path"; fi
done
if git diff --cached --quiet; then exit 0; fi
git commit -m "izleme: saatlik durum $(date -u +%FT%TZ)"
for attempt in 1 2 3; do
  if git ls-remote --exit-code --heads origin copytrade-izleme >/dev/null; then
    git pull --rebase origin copytrade-izleme
  else
    status=$?
    if [ "$status" -ne 2 ]; then exit "$status"; fi
  fi
  if git push origin HEAD:copytrade-izleme; then exit 0; fi
  if [ "$attempt" -lt 3 ]; then sleep 5; fi
done
exit 1
