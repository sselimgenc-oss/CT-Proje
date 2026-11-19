#!/usr/bin/env bash
# Sunucu SANAL motoru: açılış hazırlığı (sg-sanal.service ExecStartPre). Çalışma dizini = depo klonu (SANAL_DEPO, varsayılan /var/lib/sg-sanal/depo); durum/ kayit/ pano/ orada (Actions düzeniyle aynı).
# Ortam (hepsi /etc/sg-sanal-mod.env'den; sırsız): SUNUCU_MOD = uretim ; VERI_DALI = canli-durum (eski deneme modu 19.11'de kaldırıldı).
# Ne yapar:
#   1) Mod/dal çifti tutarlı mı: yalnız uretim ↔ canli-durum. Değilse çıkış 3 (kalıcı; systemd yeniden denemez).
#   2) Yerel durum zaten varsa (yeniden başlatma / sunucu açılışı) HİÇBİR ŞEY geri yüklenmez: yerel durum asıl kaynaktır (daha eski dal ucundan geri dönmek çift işlem yaratırdı).
#   3) Durum yoksa (ilk açılış):
#      uretim: GEÇİŞ KAPISI — canli-durum/durum/kilit.json'da Actions vardiyası hâlâ canlı görünüyorsa (bırakılmamış ve nabız `canli_kilit_dk` içinde) bekler (en çok GECIS_BEKLE_SN, 1800 sn); olmazsa çıkış 75 (geçici, systemd yeniden dener).
#              Böylece iki motor aynı anda çalışmaz (asıl anahtar: GitHub'da SUNUCU_AKTIF=evet; bu kapı ikinci güvence).
#      durum/kayit/pano geçmişi canli-durum dalından dönem kuralıyla (donem_geri.sh ile aynı) geri yüklenir: dönem aynıysa devam, farklıysa sıfırdan.
# Hiçbir sır basmaz/yazmaz. GITHUB_ACTIONS gerektirmez.
set -euo pipefail
cd "${SANAL_DEPO:-/var/lib/sg-sanal/depo}"
mod="${SUNUCU_MOD:?SUNUCU_MOD gerekli (uretim)}"
veri_dali="${VERI_DALI:?VERI_DALI gerekli}"
case "$mod:$veri_dali" in
  uretim:canli-durum) ;;
  *) echo "HATA: geçersiz mod/dal çifti ($mod / $veri_dali): yalnız uretim=canli-durum geçerli" >&2; exit 3 ;;
esac
if [ -s durum/motor.json ] || [ -s durum/hesap.json ]; then
  echo "sanal_baslat: yerel durum var; geri yükleme yok, kaldığı yerden devam ($mod)"
  exit 0
fi
geri_dali=canli-durum
if [ "$mod" = uretim ]; then
  kilit_dk="$(grep -E '^canli_kilit_dk:' copytrade/kurallar.yaml | awk '{print $2}')"
  bitis=$(( $(date -u +%s) + ${GECIS_BEKLE_SN:-1800} ))
  while :; do
    serbest=evet
    if git ls-remote --exit-code --heads origin "$geri_dali" >/dev/null 2>&1; then
      git fetch -q origin "$geri_dali"
      if git cat-file -e FETCH_HEAD:durum/kilit.json 2>/dev/null; then
        serbest="$(git show FETCH_HEAD:durum/kilit.json | python3 -c 'import json,sys,time; k=json.load(sys.stdin); print("hayir" if (not k.get("birakildi")) and time.time()*1000-int(k.get("nabiz_ms",0)) < float(sys.argv[1])*60000 else "evet")' "$kilit_dk")"
      fi
    fi
    if [ "$serbest" = evet ]; then break; fi
    if [ "$(date -u +%s)" -ge "$bitis" ]; then
      echo "sanal_baslat: Actions vardiyası hâlâ canlı görünüyor (canli-durum kilidi taze): sunucu BAŞLAMADI. GitHub'da SUNUCU_AKTIF=evet yapıldı mı? Vardiya bitince ya da iptal edilince yeniden denenir." >&2
      exit 75
    fi
    echo "sanal_baslat: Actions vardiyası canlı; kilidin bırakılması bekleniyor"
    sleep "${GECIS_ARALIK_SN:-30}"
  done
fi
donem="$(tr -d '[:space:]' < copytrade/canli/DONEM)"
bas_s="$(date -u -d "$donem" +%s)"
simdi_s="$(date -u +%s)"
if [ "$simdi_s" -lt "$bas_s" ]; then
  bekle=$((bas_s - simdi_s))
  if [ "$bekle" -gt $((230 * 60)) ]; then echo "HATA: dönem başlangıcına ${bekle} sn var (> 230 dk); sunucu motoru başlamaz" >&2; exit 75; fi
  echo "sanal_baslat: yeni dönem ${donem}: ${bekle} sn bekleniyor"
  sleep "$bekle"
fi
mkdir -p durum kayit
if git ls-remote --exit-code --heads origin "$geri_dali" >/dev/null 2>&1; then
  git fetch -q origin "$geri_dali"
  eski=""
  if git cat-file -e FETCH_HEAD:durum/donem.txt 2>/dev/null; then eski="$(git show FETCH_HEAD:durum/donem.txt | tr -d '[:space:]')"; fi
  if [ "$eski" = "$donem" ]; then
    git archive FETCH_HEAD durum kayit | tar -x
    if git cat-file -e FETCH_HEAD:pano/gecmis.json 2>/dev/null; then mkdir -p pano; git show FETCH_HEAD:pano/gecmis.json > pano/gecmis.json; fi
    echo "sanal_baslat: durum $geri_dali dalından geri yüklendi (dönem $donem)"
  else
    echo "sanal_baslat: YENİ DÖNEM ${donem} (dalda: '${eski:-yok}'): önceki durum yüklenmedi, motor sıfırdan başlar"
  fi
fi
echo "$donem" > durum/donem.txt
