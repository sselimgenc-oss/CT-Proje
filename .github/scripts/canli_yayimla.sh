#!/usr/bin/env bash
# Yalnız Actions'ın geçici checkout'unda çalışır. Canlı motor durumunu veri dalına (VERI_DALI: canli-durum | canli-durum-deneme) yazar: durum/*.json, durum/niyet.jsonl (çift emir koruması, vardiyalar arası kalıcı), durum/DUR (varsa), pano/OZET.md + pano/gecmis.json (T6 günlük rapor, varsa), kayit/<tarih>.jsonl.
# AYRI git worktree'de çalışır: motorun çalıştığı çalışma dizini DEĞİŞMEZ (arka planda 15 dk'da bir çağrılır). Kayıt 14 günden eskisi silinir. Kök commit yalnız dal ilk kez oluşurken (orphan).
set -euo pipefail
[ "${GITHUB_ACTIONS:-}" = true ] || { echo 'Yalnız GitHub Actions için.' >&2; exit 1; }
veri_dali="${VERI_DALI:-canli-durum}"
case "$veri_dali" in canli-durum|canli-durum-deneme) ;; *) echo "Geçersiz VERI_DALI: $veri_dali" >&2; exit 1 ;; esac
kaynak="$(pwd)"
# G-23: Cloudflare pano yayını BU betikte DEĞİL: ayrı `pano` işinde (contents: read; `pano_cf_yayimla.sh`). Bu betik Cloudflare aracı çalıştırmaz.
# G-23: checkout `persist-credentials: false`; yazma kimliği yalnız BU betiğe `YAYIM_TOKEN` ile gelir. Diske (.git/config) yazılmaz, argv'ye konmaz, yazdırılmaz:
# yalnız bu sürecin git komutları için GIT_CONFIG_* ortam değişkeniyle `http.extraheader` (actions/checkout ile aynı biçim). Pano üretimi (python) bu değişkenleri görmez.
if [ -n "${YAYIM_TOKEN:-}" ]; then
  export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0="http.https://github.com/.extraheader"
  GIT_CONFIG_VALUE_0="AUTHORIZATION: basic $(printf 'x-access-token:%s' "$YAYIM_TOKEN" | base64 -w0)"
  export GIT_CONFIG_VALUE_0
  unset YAYIM_TOKEN
fi
# S-18: arka plan yayımı (15 dk döngü) ile vardiya sonu yayımı AYNI ANDA koşmasın: tek yazar kilidi (flock; iş makinesinde, çalışma dizini dışında). Bekleme tavanı YAYIM_KILIT_SN (600 sn).
kilit_dosyasi="${YAYIM_KILIT:-${RUNNER_TEMP:-${TMPDIR:-/tmp}}/canli_yayimla.lock}"
exec 9>"$kilit_dosyasi"
if ! flock -w "${YAYIM_KILIT_SN:-600}" 9; then echo "HATA: yayım kilidi ${YAYIM_KILIT_SN:-600} sn'de alınamadı ($kilit_dosyasi)" >&2; exit 1; fi
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
  if ! env -u GIT_CONFIG_COUNT -u GIT_CONFIG_KEY_0 -u GIT_CONFIG_VALUE_0 python -u -m copytrade.canli.pano --durum durum --kayit kayit --gecmis pano/gecmis.json --cikti pano/OZET.md --html pano/index.html --vardiya "${GITHUB_RUN_ID:-}" ${KADRO_DALI:+--isabet-dali "$KADRO_DALI"} >/dev/null; then
    echo "UYARI: pano üretilemedi (durum yayımı sürer)" >&2
  fi
fi
# Dönem (donem_geri.sh): veri dalındaki dönem bu koşununkinden farklıysa (yeni dönemin ilk yayımı) eski durum/kayıt/pano dal UCUNDAN silinir (git geçmişinde arşivli kalır).
if [ -f "$kaynak/durum/donem.txt" ] && ! cmp -s "$kaynak/durum/donem.txt" "$work/durum/donem.txt" 2>/dev/null; then
  echo "Yeni dönem: veri dalının ucundaki eski durum/kayıt/pano siliniyor (geçmişte arşivli)"
  git -C "$work" rm -rq --ignore-unmatch durum kayit pano
  rm -rf "$work/durum" "$work/kayit" "$work/pano"
fi
mkdir -p "$work/durum" "$work/kayit"
for f in hesap.json saha.json risk.json motor.json kilit.json ozet.json niyet.jsonl DUR donem.txt donem_seri.json; do
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
