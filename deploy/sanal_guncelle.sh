#!/usr/bin/env bash
# Sunucu SANAL motoru: otomatik güncelleme (root; sg-sanal-guncelle.service/.timer, saatlik). Elle geri alma: deploy/sanal_geri_al.sh <sha> (bu betiği SANAL_HEDEF_SHA ile çağırır).
# Akış: git fetch (sgsanal) -> origin/main == HEAD ise çık -> origin/main commit'inin CI'ı YEŞİL mi (GitHub genel API, kimliksiz; `test` ve `canli_sdk` var + hepsi completed/success)? değilse çık (günlüğe neden)
#   -> yalnız fast-forward -> servisleri durdur (durdururken son durum yayımlanır) -> git merge --ff-only -> pip (yalnız kilit dosyası değiştiyse; --require-hashes) -> birim dosyaları (yalnız değiştiyse) + daemon-reload
#   -> duman testi: sg-sanal-kontrol "tamam": true -> servisleri başlat, ~60 sn sonra sg-sanal aktif mi. Haftada bir (bakim): git gc --auto + worktree prune.
# Sunucu dayanıklılık alarmı (alarm_kontrol): her çalışmada, tüm erken çıkışlardan (dondurma, aynı sha, CI) ÖNCE; hata güncellemeyi bozmaz. Son 1 saatte >2 yeniden başlama veya OOM-kill -> [CT] CRIT (tür başına 6 saatte bir); düzelince tek [CT] INFO.
# HERHANGİ bir hata: git reset --hard <önceki sha>, kilit/birimler geri, servisler yeniden başlar, Telegram [CT] CRIT. Başarıda [CT] INFO.
# Yerel durum (durum/ kayit/ pano/ depoda İZLENMEZ) git tarafından silinmez; yine de gelen commit bu yolları izlemeye başlarsa güncelleme REDDEDİLİR.
# Sır: yalnız /etc/sg-sanal-telegram.env'den (token curl'e stdin ile verilir; argv/günlüğe girmez). Betik kendini geçici kopyadan çalıştırır (git merge çalışan dosyayı değiştirmesin).
set -uo pipefail
if [ -z "${SANAL_GUNCELLE_KOPYA:-}" ]; then
  kopya="$(mktemp /tmp/sanal_guncelle.XXXXXX)" || exit 1
  cp -- "$0" "$kopya" && SANAL_GUNCELLE_KOPYA=1 exec bash "$kopya" "$@"
  exit 1
fi
trap 'rm -f -- "$0"' EXIT

DEPO="${SANAL_DEPO:-/var/lib/sg-sanal/depo}"
SERIT="${SANAL_SERIT:-/var/lib/sg-sanal}"
VENV="${SANAL_VENV:-$SERIT/venv}"
DURUM="${SANAL_DURUM_DIZIN:-/var/lib/sg-sanal-guncelle}"          # root'a ait küçük durum dizini (sgsanal yazamaz)
BIRIM_DIZIN="${SANAL_BIRIM_DIZIN:-/etc/systemd/system}"
KULLANICI="${SANAL_KULLANICI-sgsanal}"
TG_ENV="${SANAL_TG_ENV:-/etc/sg-sanal-telegram.env}"
TG_API="${SANAL_TG_API:-https://api.telegram.org}"
API="${GUNCELLE_API:-https://api.github.com}"
SYSTEMCTL="${SANAL_SYSTEMCTL:-systemctl}"
JOURNALCTL="${SANAL_JOURNALCTL:-journalctl}"
SAGLIK_JSON="${SANAL_SAGLIK_JSON:-$SERIT/saglik_sunucu.json}"      # günlük özet (gunluk_ozet.py) okur; sgsanal okuyabilsin diye 644
ALARM_SINIR="${SANAL_ALARM_YENIDEN_SINIR:-2}"                       # son 1 saatte bundan FAZLA yeniden başlama = alarm
ALARM_ARA_SN="${SANAL_ALARM_ARA_SN:-21600}"                         # aynı alarm türü en çok 6 saatte bir
KILIT="${SANAL_GUNCELLE_KILIT:-/run/sg-sanal-guncelle.lock}"
BEKLE="${GUNCELLE_BEKLE_SN:-60}"
HEDEF="${SANAL_HEDEF_SHA:-}"                                       # elle geri alma kipi (sanal_geri_al.sh)
GIT_SSH="ssh -i $SERIT/.ssh/id_ed25519 -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$SERIT/.ssh/known_hosts -o ConnectTimeout=20 -o ServerAliveInterval=15 -o ServerAliveCountMax=3"
ZORUNLU_CI="test canli_sdk"
ZAMANLAYICILAR="sg-sanal-pano.timer sg-sanal-yayim.timer"

log() { echo "guncelle: $*"; }
as_user() {
  if [ -n "$KULLANICI" ] && [ "$(id -un)" != "$KULLANICI" ]; then
    runuser -u "$KULLANICI" -- env "HOME=$SERIT" "GIT_SSH_COMMAND=$GIT_SSH" "$@"
  else
    "$@"
  fi
}
g() { as_user git -C "$DEPO" "$@"; }

BASTIR_INFO="${SANAL_TG_BASTIR_INFO:-1}"   # 1 = rutin INFO (sunucu güncellendi / elle geri alındı) Telegram'a GİTMEZ, yalnız günlüğe "tg_bastirildi" yazılır; 0 = gönderilir (sessiz)

bildir() {   # $1 = INFO|WARN|CRIT (YALNIZ iç mantık: INFO sessiz; kullanıcıya yazılmaz), $2 = metin (ilk satır başlık; mesaj "[CT] <metin>" olur). INFO sessiz gider (disable_notification=true); WARN/CRIT normal sesli. Token/chat yoksa sessizce atlanır; token hiçbir yere basılmaz.
  local tok chat sessiz=false
  [ "$1" = INFO ] && sessiz=true
  [ -r "$TG_ENV" ] || { log "telegram ortam dosyası yok; bildirim atlandı"; return 0; }
  tok="$(sed -n 's/^TELEGRAM_BOT_TOKEN=//p' "$TG_ENV" | tail -n1 | tr -d "\"'\r")"
  chat="$(sed -n 's/^TELEGRAM_CHAT_ID=//p' "$TG_ENV" | tail -n1 | tr -d "\"'\r")"
  if [ -z "$tok" ] || [ -z "$chat" ]; then log "telegram anahtarı yok; bildirim atlandı"; return 0; fi
  if printf 'url = "%s/bot%s/sendMessage"\n' "$TG_API" "$tok" | curl -sS -f --max-time 20 --config - \
       --data-urlencode "chat_id=$chat" --data-urlencode "disable_notification=$sessiz" --data-urlencode "text=[CT] $2" -o /dev/null 2>/dev/null; then
    log "bildirim gönderildi ($1)"
  else
    log "bildirim gönderilemedi ($1)"
  fi
  return 0
}

bildir_rutin() {   # $1 = metin. Rutin INFO (güncelleme tamam): varsayılan Telegram'a GİTMEZ (pano/günlük); SANAL_TG_BASTIR_INFO=0 ile sessiz gönderilir.
  if [ "$BASTIR_INFO" = 1 ]; then log "tg_bastirildi: sunucu_guncellendi ($1)"; return 0; fi
  bildir INFO "$1"
}

ci_durum() {   # $1 = sha -> yesil | yok | kirmizi:<neden>
  local json
  json="$(curl -sSL --max-time 20 --retry 1 -H 'Accept: application/vnd.github+json' -H 'User-Agent: sg-sanal-guncelle' \
    "$API/repos/$SLUG/commits/$1/check-runs?per_page=100" 2>/dev/null)" || { echo "kirmizi:GitHub API okunamadı"; return 0; }
  printf '%s' "$json" | ZORUNLU="$ZORUNLU_CI" python3 -c '
import json, os, sys
try:
    d = json.load(sys.stdin)
except Exception:
    print("kirmizi:API yanıtı okunamadı"); sys.exit()
r = d.get("check_runs") if isinstance(d, dict) else None
if not isinstance(r, list):
    print("kirmizi:API yanıtı beklenmedik"); sys.exit()
if not r:
    print("yok"); sys.exit()
ad = {x.get("name") for x in r}
eksik = [n for n in os.environ["ZORUNLU"].split() if n not in ad]
if eksik:
    print("kirmizi:eksik kontrol " + ",".join(eksik)); sys.exit()
kotu = ["%s=%s/%s" % (x.get("name"), x.get("status"), x.get("conclusion")) for x in r if not (x.get("status") == "completed" and x.get("conclusion") == "success")]
print("kirmizi:" + ", ".join(kotu) if kotu else "yesil")
'
}

aktif() { "$SYSTEMCTL" is-active --quiet "$1"; }

baslat_hepsi() {
  if [ "$aktif_motor" = 1 ]; then "$SYSTEMCTL" start sg-sanal || return 1; fi
  for t in $aktif_zaman; do "$SYSTEMCTL" start "$t" || return 1; done
  return 0
}

motor_saglam() {   # sg-sanal aktif ve yeniden başlamamış mı (yalnız önceden aktifse sınanır)
  [ "$aktif_motor" = 1 ] || return 0
  aktif sg-sanal || return 1
  [ "$("$SYSTEMCTL" show -p NRestarts --value sg-sanal 2>/dev/null || echo 0)" = 0 ]
}

birimleri_kur() {   # depodaki birimleri kopyalar (yalnız farklıysa); değiştiyse birim_degisti=1
  local f ad
  for f in "$DEPO"/deploy/sg-sanal*.service "$DEPO"/deploy/sg-sanal*.timer; do
    [ -f "$f" ] || continue
    ad="$(basename "$f")"
    if ! cmp -s "$f" "$BIRIM_DIZIN/$ad"; then cp -- "$f" "$BIRIM_DIZIN/$ad" || return 1; birim_degisti=1; fi
  done
  if [ "$birim_degisti" = 1 ]; then "$SYSTEMCTL" daemon-reload || return 1; fi
  return 0
}

birimleri_geri() {   # yedekten geri: sonradan eklenenleri sil, eskileri geri koy
  local f ad
  for f in "$BIRIM_DIZIN"/sg-sanal*.service "$BIRIM_DIZIN"/sg-sanal*.timer; do
    [ -f "$f" ] || continue
    ad="$(basename "$f")"
    [ -f "$YEDEK/$ad" ] || rm -f -- "$f"
  done
  for f in "$YEDEK"/*; do [ -f "$f" ] && cp -- "$f" "$BIRIM_DIZIN/$(basename "$f")"; done
  "$SYSTEMCTL" daemon-reload
}

pip_kur() { as_user "$VENV/bin/pip" install -q --require-hashes -r "$DEPO/requirements-canli.lock"; }

duman_testi() {
  local isaret
  isaret="$(date '+%Y-%m-%d %H:%M:%S')"
  timeout 180 "$SYSTEMCTL" start sg-sanal-kontrol || return 1
  "$JOURNALCTL" -u sg-sanal-kontrol --since "$isaret" -o cat --no-pager 2>/dev/null | grep -q '"tamam": true'
}

geri_al() {   # $1 = neden
  local neden="$1" motor_durum=aktif
  log "HATA: $neden; geri alınıyor -> $onceki"
  g reset -q --hard "$onceki" || log "UYARI: git reset başarısız"
  if [ "$lock_degisti" = 1 ]; then pip_kur || log "UYARI: eski kilit paketleri kurulamadı"; fi
  birimleri_geri || log "UYARI: birimler geri yüklenemedi"
  baslat_hepsi || log "UYARI: servisler başlatılamadı"
  sleep "$BEKLE"
  motor_saglam || motor_durum="DEĞİL (elle bakın: journalctl -u sg-sanal)"
  printf '%s\n' "$yeni" > "$DURUM/kotu_sha"
  bildir CRIT "🚨 Sunucu güncellemesi başarısız oldu (${neden}).
Eski sürüm geri yüklendi; motor: ${motor_durum}. Bu sürüm tekrar denenmeyecek.
Senden bir şey gerekmiyor; yeni sürüm gelince otomatik denenir."
  exit 1
}

acik_poz() {   # sanal motorun defterindeki açık pozisyon sayısı (okunamazsa "bilinmiyor")
  python3 -c 'import json,sys
d=json.load(open(sys.argv[1]))
print(sum(len(c) for c in (d.get("poz") or {}).values()))' "$DEPO/durum/hesap.json" 2>/dev/null || echo bilinmiyor
}
stop_metni() {   # $1 = açık pozisyon sayısı
  case "$1" in 0) echo "gerekmiyor (pozisyon yok)";; bilinmiyor) echo "bilinmiyor";; *) echo "bot kapalıyken yazılım stopu çalışmıyor";; esac
}

alarm_kontrol() {   # sg-sanal son 1 saatte >ALARM_SINIR kez yeniden başladı mı / OOM-kill oldu mu. Durum: $DURUM/alarm_yeniden, $DURUM/alarm_oom (içinde son gönderim epoch'u; dosya var = alarm aktif). Hata hiçbir şeyi bozmaz.
  [ -z "$HEDEF" ] || return 0
  local j sayi oom=0 sonuc simdi t son aktif var=0 mesaj toplam kt temiz
  j="$("$JOURNALCTL" -u sg-sanal --since=-1h -o cat --no-pager 2>/dev/null)" || { log "alarm: günlük okunamadı; atlandı"; return 0; }
  sayi="$(printf '%s\n' "$j" | grep -c 'Scheduled restart job' || true)"
  [[ "$sayi" =~ ^[0-9]+$ ]] || sayi=0
  if printf '%s\n' "$j" | grep -Eiq "Failed with result 'oom-kill'|killed by the OOM killer"; then oom=1; fi
  sonuc="$("$SYSTEMCTL" show -p Result --value sg-sanal 2>/dev/null || true)"
  if [ "$sonuc" = "oom-kill" ]; then oom=1; fi
  toplam="$("$SYSTEMCTL" show -p NRestarts --value sg-sanal 2>/dev/null || true)"; [[ "$toplam" =~ ^[0-9]+$ ]] || toplam=null
  simdi="$(date +%s)"
  ALARM_DURUM_DIZIN="$DEPO/durum" bash "$DEPO/deploy/alarm_ikinci.sh" >/dev/null 2>&1 || true      # bot 20 dk dönmediyse ikinci sesli mesaj (5 dk'lık timer asıl yol; bu saatlik yedek)
  # günlük özet için küçük JSON (atomik yaz)
  if kt="$(mktemp "$SAGLIK_JSON.XXXXXX" 2>/dev/null)"; then
    gun_say="$(grep -c "^$(date -u +%F)$" "$DURUM/guncelleme_gunlugu" 2>/dev/null || true)"; [[ "$gun_say" =~ ^[0-9]+$ ]] || gun_say=0
    printf '{"zaman": %s, "yeniden_baslama_1s": %s, "oom_son": %s, "nrestarts_toplam": %s, "guncelleme_bugun": %s}\n' "$simdi" "$sayi" "$([ "$oom" = 1 ] && echo true || echo false)" "$toplam" "$gun_say" > "$kt" \
      && chmod 644 "$kt" && mv -f -- "$kt" "$SAGLIK_JSON" || rm -f -- "$kt"
  fi
  for t in yeniden oom; do
    aktif=0
    if [ "$t" = yeniden ]; then if [ "$sayi" -gt "$ALARM_SINIR" ]; then aktif=1; fi; else aktif=$oom; fi
    if [ "$aktif" = 1 ]; then
      var=1
      son="$(cat "$DURUM/alarm_$t" 2>/dev/null || echo 0)"; [[ "$son" =~ ^[0-9]+$ ]] || son=0
      if [ ! -f "$DURUM/alarm_$t" ] || [ $((simdi - son)) -ge "$ALARM_ARA_SN" ]; then
        poz="$(acik_poz)"
        if [ "$t" = yeniden ]; then mesaj="🔴 Bot durdu
Neden: son 1 saatte ${sayi} kez yeniden başladı (sınır ${ALARM_SINIR}); bellek taşması $([ "$oom" = 1 ] && echo oldu || echo olmadı).
Açık pozisyon: ${poz} · Stop: $(stop_metni "$poz")
Sistem motoru kendiliğinden yeniden başlatıyor.
Sorun sürerse bana haber ver."
        else mesaj="🔴 Bot durdu
Neden: bellek tavanı aşıldı, motor öldürüldü (son 1 saatte ${sayi} yeniden başlama).
Açık pozisyon: ${poz} · Stop: $(stop_metni "$poz")
Sistem motoru kendiliğinden yeniden başlatıyor.
Sorun sürerse bana haber ver."; fi
        printf '%s\n' "$simdi" > "$DURUM/alarm_$t"
        bildir CRIT "$mesaj"
      fi
    fi
  done
  if [ "$var" = 0 ]; then
    temiz=0
    for t in yeniden oom; do if [ -f "$DURUM/alarm_$t" ]; then temiz=1; rm -f -- "$DURUM/alarm_$t"; fi; done
    if [ "$temiz" = 1 ]; then bildir INFO "✅ Düzeldi: bot yeniden çalışıyor (son 1 saatte ${sayi} yeniden başlama).
Senden bir şey gerekmiyor."; fi
  fi
  return 0
}

mkdir -p "$DURUM" || exit 1
exec 9>"$KILIT"
if [ -n "$HEDEF" ]; then
  flock -w 600 9 || { log "kilit alınamadı (başka güncelleme sürüyor)"; exit 1; }
else
  flock -n 9 || { log "başka bir güncelleme sürüyor; çıkılıyor"; exit 0; }
fi

alarm_kontrol || log "UYARI: alarm kontrolü başarısız (güncelleme etkilenmez)"
if [ -z "$HEDEF" ] && [ -s "$DURUM/dondur" ]; then log "otomatik güncelleme DONDURULMUŞ ($(head -c 12 "$DURUM/dondur")); kaldırmak için: rm $DURUM/dondur"; exit 0; fi
[ -d "$DEPO/.git" ] || { log "depo yok: $DEPO"; exit 1; }

bakim() {   # haftada bir hafif git bakımı (gc --auto + worktree prune); damga $DURUM/bakim_sn; hata güncellemeyi etkilemez. Kayıt budaması sanal_yayimla.sh'ta (14 gün).
  [ -z "$HEDEF" ] || return 0
  local simdi son
  simdi="$(date +%s)"; son="$(cat "$DURUM/bakim_sn" 2>/dev/null || echo 0)"
  [[ "$son" =~ ^[0-9]+$ ]] || son=0
  [ $((simdi - son)) -ge 604800 ] || return 0
  g gc --auto -q || log "UYARI: git gc --auto başarısız"
  g worktree prune || log "UYARI: git worktree prune başarısız"
  printf '%s\n' "$simdi" > "$DURUM/bakim_sn"
  log "haftalık git bakımı yapıldı"
}
bakim

SLUG="${GUNCELLE_REPO:-$(g remote get-url origin | sed -E 's#^.*github\.com[:/]+##; s#\.git$##')}"
[[ "$SLUG" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || { log "depo adı çıkarılamadı ($SLUG)"; exit 1; }

head="$(g rev-parse HEAD)" || exit 1
if [ -n "$HEDEF" ]; then
  yeni="$(g rev-parse --verify -q "${HEDEF}^{commit}")" || { log "hedef commit bulunamadı: $HEDEF"; exit 1; }
  onceki="$head"
else
  g fetch -q origin main || { log "git fetch başarısız (ağ?); sonra yeniden denenir"; exit 0; }
  yeni="$(g rev-parse origin/main)" || exit 1
  onceki="$(cat "$DURUM/uygulanan_sha" 2>/dev/null || true)"
  if ! [[ "$onceki" =~ ^[0-9a-f]{40}$ ]] || ! g cat-file -e "${onceki}^{commit}" 2>/dev/null; then onceki="$head"; fi   # uygulanan_sha: servislerin gerçekten çalıştığı sürüm (elle çekme sonrası da uygulanır)
  if [ "$yeni" = "$head" ] && [ "$onceki" = "$head" ]; then exit 0; fi
  if [ -s "$DURUM/kotu_sha" ] && [ "$(cat "$DURUM/kotu_sha")" = "$yeni" ]; then log "${yeni:0:7} daha önce başarısız oldu ve geri alındı; yeni commit beklenir"; exit 0; fi
  if ! g merge-base --is-ancestor "$head" "$yeni"; then
    log "origin/main HEAD'in ileri sarması DEĞİL (fast-forward yok); reddedildi"
    if [ "$(cat "$DURUM/reddedilen" 2>/dev/null)" != "$yeni:ff" ]; then printf '%s\n' "$yeni:ff" > "$DURUM/reddedilen"; bildir CRIT "🚨 Sunucu güncellemesi reddedildi: yeni sürümün geçmişi eskisiyle uyuşmuyor.
Hiçbir şey değiştirilmedi; motor eski sürümle çalışıyor.
Bana haber ver, ben bakarım."; fi
    exit 0
  fi
  ci="$(ci_durum "$yeni")"
  if [ "$ci" = yok ] || [[ "$ci" == kirmizi:eksik\ kontrol* ]]; then   # PR birleştirme commit'inde zorunlu kontrol yoksa (CI pull_request'te koşar; zamanlanmış iş akışları main ucuna başka kontroller ekleyebilir) 2. ebeveyn = PR ucu
    ebeveynler="$(g rev-list --parents -n1 "$yeni")"
    pr_ucu="$(echo "$ebeveynler" | awk 'NF==3 {print $3}')"
    if [ -n "$pr_ucu" ]; then ci="$(ci_durum "$pr_ucu")"; log "kontrol ${yeni:0:7} üzerinde yok; PR ucu ${pr_ucu:0:7} değerlendirildi"; fi
  fi
  if [ "$ci" != yesil ]; then log "CI yeşil değil/yok (${ci#kirmizi:}); ${yeni:0:7} uygulanmadı"; exit 0; fi
fi

# durum/ kayit/ pano/ yerel durumdur: gelen commit bunları izlemeye başlarsa dokunma
if [ -n "$(g diff --name-only "$head" "$yeni" -- durum kayit pano)" ]; then
  log "hedef commit durum/ kayit/ pano/ yollarını içeriyor; yerel durum korunsun diye REDDEDİLDİ"
  if [ "$(cat "$DURUM/reddedilen" 2>/dev/null)" != "$yeni:durum" ]; then printf '%s\n' "$yeni:durum" > "$DURUM/reddedilen"; bildir CRIT "🚨 Sunucu güncellemesi reddedildi: yeni sürüm sunucunun yerel durum dosyalarına dokunuyor.
Hiçbir şey değiştirilmedi; motor eski sürümle çalışıyor.
Bana haber ver, ben bakarım."; fi
  exit 0
fi

lock_degisti=0; birim_degisti=0
g diff --quiet "$onceki" "$yeni" -- requirements-canli.lock || lock_degisti=1
konu="$(g log -1 --format=%s "$yeni" | tr -d '\000-\037' | cut -c1-120)"
log "güncelleme: ${onceki:0:7} -> ${yeni:0:7} (${konu}); kilit değişti=$lock_degisti"

aktif_motor=0; aktif_zaman=""
aktif sg-sanal && aktif_motor=1
for t in $ZAMANLAYICILAR; do if aktif "$t"; then aktif_zaman="$aktif_zaman $t"; fi; done
YEDEK="$(mktemp -d)" || exit 1
for f in "$BIRIM_DIZIN"/sg-sanal*.service "$BIRIM_DIZIN"/sg-sanal*.timer; do [ -f "$f" ] && cp -- "$f" "$YEDEK/"; done

"$SYSTEMCTL" stop $ZAMANLAYICILAR || true
"$SYSTEMCTL" stop sg-sanal || geri_al "sg-sanal durdurulamadı"           # durdururken son durum yayımlanır
if [ -n "$HEDEF" ]; then g reset -q --hard "$yeni" || geri_al "git reset başarısız"; else g merge -q --ff-only "$yeni" || geri_al "git merge --ff-only başarısız"; fi
if [ "$lock_degisti" = 1 ]; then pip_kur || geri_al "pip install başarısız"; fi
birimleri_kur || geri_al "birim dosyaları kurulamadı"
duman_testi || geri_al "duman testi (sg-sanal-kontrol) başarısız"
baslat_hepsi || geri_al "servisler başlatılamadı"
sleep "$BEKLE"
motor_saglam || geri_al "sg-sanal ${BEKLE} sn sonra aktif değil"

[ -f "$BIRIM_DIZIN/sg-sanal-ikinci-alarm.timer" ] && { "$SYSTEMCTL" enable --now sg-sanal-ikinci-alarm.timer >/dev/null 2>&1 || log "ikinci alarm zamanlayıcısı açılamadı"; }   # bot durdu 20 dk ikinci mesaj (elle kurulum gerekmesin)
printf '%s\n' "$yeni" > "$DURUM/uygulanan_sha"
rm -f "$DURUM/kotu_sha" "$DURUM/reddedilen"; rm -rf "$YEDEK"
if [ -n "$HEDEF" ]; then
  bildir INFO "Bot önceki sürüme döndürüldü"                                  # sessiz (INFO); sürüm numaraları günlükte
  log "elle geri alındı: ${onceki:0:7}→${yeni:0:7} (${konu})"
else
  date -u +%F >> "$DURUM/guncelleme_gunlugu"; tail -n 200 "$DURUM/guncelleme_gunlugu" > "$DURUM/guncelleme_gunlugu.tmp" && mv -f "$DURUM/guncelleme_gunlugu.tmp" "$DURUM/guncelleme_gunlugu"      # günlük rapor: "Bot bugün N kez güncellendi"
  bildir_rutin "Sunucu güncellendi: ${onceki:0:7}→${yeni:0:7} (${konu})"       # Telegram'a GİTMEZ (günlüğe tg_bastirildi)
fi
log "tamam: ${yeni:0:7}"
exit 0
