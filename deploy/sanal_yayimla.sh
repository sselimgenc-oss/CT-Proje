#!/usr/bin/env bash
# SUNUCU SÜRÜMÜ (deploy/sanal_yayimla.sh): .github/scripts/canli_yayimla.sh'ten türetildi; Actions'a özgü kısımlar (GITHUB_ACTIONS zorunluluğu, YAYIM_TOKEN) çıkarıldı; sunucuda push kimliği SSH deploy anahtarıdır (GIT_SSH_COMMAND; sır repoda/ortam dosyasında DEĞİL, yalnız sunucuda).
# Dal izni: yalnız uretim ↔ canli-durum (SUNUCU_MOD; eski deneme modu kaldırıldı). Çalışma dizini = depo klonu (motorun --durum-dizin durum / --kayit-dizin kayit dizinleri orada). Canlı motor durumunu veri dalına (VERI_DALI: canli-durum) yazar: durum/*.json, durum/niyet.jsonl (çift emir koruması, vardiyalar arası kalıcı), durum/DUR (varsa), pano/OZET.md + pano/gecmis.json (T6 günlük rapor, varsa), kayit/<tarih>.jsonl.
# AYRI git worktree'de çalışır: motorun çalıştığı çalışma dizini DEĞİŞMEZ (arka planda 15 dk'da bir çağrılır). Kayıt 14 günden eskisi silinir. Kök commit yalnız dal ilk kez oluşurken (orphan).
set -euo pipefail
mod="${SUNUCU_MOD:?SUNUCU_MOD gerekli (uretim)}"
veri_dali="${VERI_DALI:-canli-durum}"
case "$mod:$veri_dali" in uretim:canli-durum) ;; *) echo "Geçersiz mod/dal: $mod / $veri_dali (yalnız uretim=canli-durum)" >&2; exit 1 ;; esac
kaynak="$(pwd)"
# Cloudflare pano yayını BU betikte DEĞİL: deploy/sanal_pano_cf.sh (ayrı birim; Cloudflare anahtarını yalnız o görür).
# S-18: arka plan yayımı (15 dk döngü) ile vardiya sonu yayımı AYNI ANDA koşmasın: tek yazar kilidi (flock; iş makinesinde, çalışma dizini dışında). Bekleme tavanı YAYIM_KILIT_SN (600 sn).
kilit_dosyasi="${YAYIM_KILIT:-/var/lib/sg-sanal/yayim.lock}"
exec 9>"$kilit_dosyasi"
if ! flock -w "${YAYIM_KILIT_SN:-600}" 9; then echo "HATA: yayım kilidi ${YAYIM_KILIT_SN:-600} sn'de alınamadı ($kilit_dosyasi)" >&2; exit 1; fi
[ -d "$kaynak/durum" ] || { echo 'durum/ yok: yayımlanacak bir şey yok'; exit 0; }
work="$(mktemp -d)"
trap 'git -C "$kaynak" worktree remove --force "$work" 2>/dev/null || rm -rf "$work"' EXIT
git config user.name 'sg-sanal-sunucu'
git config user.email 'sg-sanal-sunucu@users.noreply.github.com'
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
  if ! "${PYTHON:-python}" -u -m copytrade.canli.pano --durum durum --kayit kayit --gecmis pano/gecmis.json --cikti pano/OZET.md --html pano/index.html --vardiya "${VARDIYA_ID:-}" ${KADRO_DALI:+--isabet-dali "$KADRO_DALI"} >/dev/null; then
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
for f in kadro_yon_v1.json gunluk_ozet_v1.json rejim_sonuc_v1.json rejim_sonuc_v1.md secim_gercek_v1.json secim_gercek_v1.md kural_maliyet_v1.json kural_maliyet_v1.md; do if [ -f "$kaynak/durum/paylasim/$f" ]; then mkdir -p "$work/durum/paylasim"; cp "$kaynak/durum/paylasim/$f" "$work/durum/paylasim/$f"; fi; done
for f in "$kaynak"/durum/paylasim/CT_HAFTA_*.md; do if [ -f "$f" ]; then mkdir -p "$work/durum/paylasim"; cp "$f" "$work/durum/paylasim/$(basename "$f")"; fi; done   # haftalık veri paketi (CT_HAFTA_<Pazartesi>.md + CT_HAFTA_son.md)
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
