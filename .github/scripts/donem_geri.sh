#!/usr/bin/env bash
# Vardiya başı: durumu veri dalından geri yükler, DÖNEM kuralıyla (kullanıcı kararı 08.11: pazartesi 09.11 00:01 TSİ = 2026-11-08T21:01Z sıfırdan başlangıç).
# - `copytrade/canli/DONEM` (UTC ISO zaman) = dönem başlangıcı. Koşu bundan ÖNCE başladıysa başlangıca kadar bekler (en çok 230 dk) ve motor süresini kalan bütçeye indirir (GITHUB_ENV GIRDI_SURE_DK).
# - Veri dalındaki `durum/donem.txt` aynı dönemse durum/kayit/gecmis geri yüklenir (normal devam). Farklıysa (yeni dönem) HİÇBİR ŞEY yüklenmez: motor sıfırdan başlar
#   (saha, pozisyonlar, bekleme cezaları, kayıtlar, pano geçmişi). Eski veri dal GEÇMİŞİNDE (git) arşivli kalır; canli_yayimla.sh yeni dönemin ilk yayımında dal ucundan siler.
set -euo pipefail
[ "${GITHUB_ACTIONS:-}" = true ] || { echo 'Yalnız GitHub Actions için.' >&2; exit 1; }
veri_dali="${VERI_DALI:?VERI_DALI gerekli}"
donem="$(tr -d '[:space:]' < copytrade/canli/DONEM)"
bas_s="$(date -u -d "$donem" +%s)"
simdi_s="$(date -u +%s)"
if [ "$simdi_s" -lt "$bas_s" ]; then
  bekle=$((bas_s - simdi_s))
  if [ "$bekle" -gt $((230 * 60)) ]; then echo "HATA: dönem başlangıcına ${bekle} sn var (> 230 dk); bu koşu motoru çalıştırmaz" >&2; exit 1; fi
  echo "Yeni dönem ${donem}: ${bekle} sn bekleniyor"
  sleep "$bekle"
  sure="${GIRDI_SURE_DK:-255}"
  case "$sure" in ''|*[!0-9]*) sure=255 ;; esac
  kalan=$((sure - bekle / 60 - 5))
  if [ "$kalan" -lt 20 ]; then kalan=20; fi
  echo "GIRDI_SURE_DK=${kalan}" >> "${GITHUB_ENV:-/dev/null}"
  echo "Motor süresi kalan bütçeye indirildi: ${kalan} dk"
fi
mkdir -p durum kayit
if git ls-remote --exit-code --heads origin "$veri_dali" >/dev/null; then
  git fetch -q origin "$veri_dali"
  eski=""
  if git cat-file -e FETCH_HEAD:durum/donem.txt 2>/dev/null; then eski="$(git show FETCH_HEAD:durum/donem.txt | tr -d '[:space:]')"; fi
  if [ "$eski" = "$donem" ]; then
    git archive FETCH_HEAD durum kayit | tar -x
    if git cat-file -e FETCH_HEAD:pano/gecmis.json 2>/dev/null; then mkdir -p pano; git show FETCH_HEAD:pano/gecmis.json > pano/gecmis.json; fi
  else
    echo "YENİ DÖNEM ${donem} (veri dalındaki: '${eski:-yok}'): önceki durum YÜKLENMEDİ, motor sıfırdan başlar (eski veri dal geçmişinde arşivli)"
  fi
else
  status=$?
  if [ "$status" -ne 2 ]; then exit "$status"; fi
fi
echo "$donem" > durum/donem.txt
