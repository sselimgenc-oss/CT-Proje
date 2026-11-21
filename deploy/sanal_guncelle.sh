#!/usr/bin/env bash
# Sunucu SANAL motoru: otomatik güncelleme (root; sg-sanal-guncelle.service/.timer: günde 2 SABİT pencere 10:30 ve 22:30 TSİ = 07:30/19:30 UTC, K-80; pencere dışında CI-yeşil yeni commit beklemede kalır). ACİL elle güncelleme: `sudo systemctl start --no-block sg-sanal-guncelle` (betik pencereye bakmaz; aynı kapılar). Elle geri alma: deploy/sanal_geri_al.sh <sha> (bu betiği SANAL_HEDEF_SHA ile çağırır).
# Akış: git fetch (sgsanal) -> origin/main == HEAD ise çık -> origin/main commit'inin CI'ı YEŞİL mi (GitHub genel API, kimliksiz; `test` ve `canli_sdk` var + hepsi completed/success)? değilse çık (günlüğe neden)
#   -> yalnız fast-forward -> servisleri durdur (durdururken son durum yayımlanır) -> git merge --ff-only -> pip (yalnız kilit dosyası değiştiyse; --require-hashes) -> birim dosyaları (yalnız değiştiyse) + daemon-reload
#   -> duman testi: sg-sanal-kontrol "tamam": true -> servisleri başlat, ~60 sn sonra sg-sanal aktif mi. Haftada bir (bakim): git gc --auto + worktree prune.
# Sunucu dayanıklılık alarmı (alarm_kontrol): her çalışmada, tüm erken çıkışlardan (dondurma, aynı sha, CI) ÖNCE; hata güncellemeyi bozmaz. Son 1 saatte >2 yeniden başlama veya OOM-kill -> [CT] CRIT (tür başına 6 saatte bir); düzelince tek [CT] INFO.
# HERHANGİ bir hata: git reset --hard <önceki sha>, kilit/birimler geri, servisler yeniden başlar, Telegram [CT] CRIT. Başarıda [CT] INFO.
# Yarım kalan güncelleme (D9): servisler durdurulmadan ÖNCE $DURUM/yarim yazılır (önceki/yeni sha, motor/zamanlayıcı durumu); başarı ya da geri alma sonunda silinir. Betik arada öldürülürse (SIGKILL/OOM/zaman aşımı) sonraki çalışma
#   bu işareti görür: birleştirme olduysa uygulama yolunu (pip/birim/duman/başlat) TAMAMLAR, olmadıysa eski sürümü başlatır; tek ⚠️ satır. Kasıtlı duruş (durum/DUR, $DURUM/dondur) ezilmez: motor başlatılmaz.
# K-80 kararlılık: (a) her başarılı/geri alınan kurulumdan önce $DEPO/durum/guncelleme_zamani (epoch sn) yazılır: motor/Telegram sonraki 15 dk yalnız ölümcül uyarı yollar; (b) kurulum sonrası ÖZ-DENETİM (servisler, zamanlayıcılar, ozet.json yazılıyor mu, son yayım yeni mi) başarısızsa geri alma;
#   (c) başarılı normal kurulum $DURUM/bekci yazar: 60 dk boyunca deploy/sanal_bekci.sh (5 dk'lık zamanlayıcı) sayaçları izler, eşik aşılırsa BU betiği SANAL_HEDEF_SHA + SANAL_GERI_NEDEN + SANAL_KOTU_SHA ile çağırıp önceki sürüme döner ve sha'yı kotu_sha yapar;
#   (d) saatlik dayanıklılık alarmı ayrı zamanlayıcıdan (sg-sanal-denetim.timer; SANAL_YALNIZ_ALARM=1: yalnız alarm_kontrol, güncelleme yok). Durum alarmları ("Bot durdu") göndermeden önce SANAL_DOGRULA_SN (45) sonra yeniden sınanır.
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
YARIM="$DURUM/yarim"                                                 # güncelleme sürerken var (D9)
YEDEK="$DURUM/yedek_birimler"                                        # birim yedeği kalıcı dizinde (yarım kalırsa geri alma yedeği yaşasın)
BEKCI="$DURUM/bekci"                                                 # 60 dk bekçi işareti (K-80): epoch / yeni sha / önceki sha / motor önceden aktif mi
ISARET="$DEPO/durum/guncelleme_zamani"                               # K-80: motor/Telegram okur (sgsanal okuyabilsin: 644)
DOGRULA_SN="${SANAL_DOGRULA_SN:-45}"                                 # K-80: durum alarmı göndermeden önce koşulu bu kadar sonra yeniden sına
OZ_SN="${SANAL_OZ_DENETIM_SN:-180}"                                  # K-80: öz-denetimde ozet.json'un yazılmasını en çok bu kadar bekle
devam=0
GERI_NEDEN="${SANAL_GERI_NEDEN:-}"                                   # K-80: bekçi geri dönüşü (neden metni) + bozuk sha
KOTU_SHA="${SANAL_KOTU_SHA:-}"
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

# Telegram sadeleştirme (kullanıcı 20.11): başarılı güncelleme Telegram'a HİÇ mesaj atmaz (günlükte); yalnız başarısız/geri alınan güncelleme TEK ⚠️ satır gönderir.

bildir() {   # $1 = INFO|WARN|CRIT (INFO sessiz gider), $2 = metin (ilk satır başlık; mesaj "[CT] <metin>" olur). INFO sessiz gider (disable_notification=true); WARN/CRIT normal sesli. Token/chat yoksa sessizce atlanır; token hiçbir yere basılmaz.
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

isaret_yaz() {   # K-80: güncelleme zamanı (epoch sn); servisler başlamadan ÖNCE yazılır → motor ilk dakikadan itibaren 15 dk penceresini bilir. Hata kurulumu bozmaz.
  local gecici="$ISARET.tmp"
  [ -d "$DEPO/durum" ] || return 0
  { date +%s; printf '%s\n' "${yeni:-}"; } > "$gecici" 2>/dev/null && chmod 644 "$gecici" && { [ -z "$KULLANICI" ] || chown "$KULLANICI" "$gecici" 2>/dev/null || true; } && mv -f -- "$gecici" "$ISARET" || { rm -f -- "$gecici"; log "UYARI: güncelleme işareti yazılamadı"; }
  return 0
}

yayim_taze() {   # veri dalındaki (origin/canli-durum) son yayım <= 50 dk mı: 0 taze, 1 eski, 2 bilinmiyor (dal yok)
  local t
  t="$(g log -1 --format=%ct refs/remotes/origin/canli-durum 2>/dev/null)" || return 2
  [[ "$t" =~ ^[0-9]+$ ]] || return 2
  [ $(( $(date +%s) - t )) -le 3000 ]
}

oz_denetim() {   # K-80: kurulum sonrası öz-denetim; sorun varsa nedeni yazar (stdout) ve 1 döner
  local ad bas sn=0 taze=0 sorun=""
  for ad in sg-sanal-radar.timer sg-sanal-ikinci-alarm.timer sg-sanal-denetim.timer sg-sanal-bekci.timer sg-sanal-koruyucu.service; do
    [ -f "$BIRIM_DIZIN/$ad" ] || continue
    "$SYSTEMCTL" is-enabled --quiet "$ad" || sorun="$sorun $ad-etkin-degil"
  done
  for ad in $aktif_zaman; do aktif "$ad" || sorun="$sorun $ad-aktif-degil"; done
  if [ "$aktif_motor" = 1 ]; then
    aktif sg-sanal || sorun="$sorun sg-sanal-aktif-degil"
    bas="${baslat_ms:-0}"
    while :; do   # durum dosyaları yazılıyor mu: ozet.json yazildi_ms, servis başlangıcından sonra
      python3 -c 'import json,sys
d=json.load(open(sys.argv[1]))
sys.exit(0 if float(d.get("yazildi_ms") or 0) >= float(sys.argv[2]) else 1)' "$DEPO/durum/ozet.json" "$bas" 2>/dev/null && { taze=1; break; }
      [ "$sn" -ge "$OZ_SN" ] && break
      sleep 5; sn=$((sn + 5))
    done
    [ "$taze" = 1 ] || sorun="$sorun durum-dosyalari-yazilmiyor"
    if [ "${yayim_once:-2}" = 0 ]; then yayim_taze; [ "$?" != 1 ] || sorun="$sorun son-yayim-eski"; fi
  fi
  [ -z "$sorun" ] || { echo "${sorun# }"; return 1; }
  return 0
}

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
  isaret_yaz
  baslat_hepsi || log "UYARI: servisler başlatılamadı"
  sleep "$BEKLE"
  motor_saglam || motor_durum="DEĞİL (elle bakın: journalctl -u sg-sanal)"
  printf '%s\n' "$yeni" > "$DURUM/kotu_sha"
  rm -f -- "$YARIM" "$BEKCI"; rm -rf -- "$YEDEK"
  bildir WARN "⚠️ Bot güncellemesi başarısız, eski sürümle devam ediyor"
  exit 1
}

radar_bir_kez() {   # K-85: yeni dönemde radar BİR KEZ hemen başlatılır (kadro aynı gün çıksın; 00:37 zamanlayıcısını beklemeden). İşaret: $DURUM/radar_basladi = başlatılan dönem.
  # Güncelleme sonunda VE saatlik denetimde (root) çağrılır: dönem sıfırlamayı sanal_baslat (sgsanal; birim başlatamaz) yaptıysa ya da eski güncelleme betiği güncellediyse en geç 1 saatte başlar.
  [ -f "$BIRIM_DIZIN/sg-sanal-radar.service" ] && [ -z "$HEDEF" ] || return 0
  local radar_donem
  radar_donem="$(tr -d '[:space:]' < "$DEPO/copytrade/canli/DONEM" 2>/dev/null)"
  if [ -n "$radar_donem" ] && [ "$(cat "$DURUM/radar_basladi" 2>/dev/null)" != "$radar_donem" ]; then   # (bu dönemin sade kadrosu veri dalında varsa betik zaten iş yapmaz)
    if "$SYSTEMCTL" start --no-block sg-sanal-radar.service >/dev/null 2>&1; then printf '%s\n' "$radar_donem" > "$DURUM/radar_basladi"; log "radar yeni dönem için başlatıldı (${radar_donem})"; else log "radar yeni dönem için başlatılamadı"; fi
  fi
  return 0
}
donem_sifirla() {   # K-85: ortak betik (deploy/donem_sifirla.sh; sanal_baslat.sh de çağırır). Servisler bu sırada DURMUŞTUR. Hata güncellemeyi bozmaz.
  SANAL_DEPO="$DEPO" SANAL_KULLANICI="$KULLANICI" bash "$DEPO/deploy/donem_sifirla.sh" || log "UYARI: donem_sifirla.sh başarısız"
}
son_guncelleme_metni() {   # K-80: bağlam satırı için "son güncelleme N dk/sa önce" (işaret yoksa "kayıt yok")
  local ts gecen
  ts="$(head -n1 "$ISARET" 2>/dev/null | tr -dc '0-9')"
  [[ "$ts" =~ ^[0-9]{9,}$ ]] || { echo "son güncelleme: kayıt yok"; return 0; }
  gecen=$(( $(date +%s) - ts ))
  if [ "$gecen" -lt 7200 ]; then echo "son güncelleme $((gecen / 60)) dk önce"; else echo "son güncelleme $((gecen / 3600)) sa $(((gecen % 3600) / 60)) dk önce"; fi
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
        if [ "$DOGRULA_SN" -gt 0 ] 2>/dev/null; then   # K-80: çift doğrulama; koşul DOGRULA_SN sonra hâlâ geçerli mi (günlük + OOM yeniden okunur)
          sleep "$DOGRULA_SN"
          j="$("$JOURNALCTL" -u sg-sanal --since=-1h -o cat --no-pager 2>/dev/null)" || j=""
          sayi="$(printf '%s\n' "$j" | grep -c 'Scheduled restart job' || true)"; [[ "$sayi" =~ ^[0-9]+$ ]] || sayi=0
          oom=0; if printf '%s\n' "$j" | grep -Eiq "Failed with result 'oom-kill'|killed by the OOM killer" || [ "$("$SYSTEMCTL" show -p Result --value sg-sanal 2>/dev/null || true)" = "oom-kill" ]; then oom=1; fi
          if [ "$t" = yeniden ]; then [ "$sayi" -gt "$ALARM_SINIR" ] || { log "alarm ($t) ikinci doğrulamada düzeldi; gönderilmedi"; continue; }; else [ "$oom" = 1 ] || { log "alarm ($t) ikinci doğrulamada düzeldi; gönderilmedi"; continue; }; fi
        fi
        poz="$(acik_poz)"
        baglam="⏱ Son 1 saatte ${sayi} yeniden başlama · $(son_guncelleme_metni)"
        if [ "$t" = yeniden ]; then mesaj="🔴 Bot durdu
Neden: son 1 saatte ${sayi} kez yeniden başladı (sınır ${ALARM_SINIR}); bellek taşması $([ "$oom" = 1 ] && echo oldu || echo olmadı).
Açık pozisyon: ${poz} · Stop: $(stop_metni "$poz")
${baglam}
Sistem motoru kendiliğinden yeniden başlatıyor.
Sorun sürerse bana haber ver."
        else mesaj="🔴 Bot durdu
Neden: bellek tavanı aşıldı, motor öldürüldü (son 1 saatte ${sayi} yeniden başlama).
Açık pozisyon: ${poz} · Stop: $(stop_metni "$poz")
${baglam}
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
if [ "${SANAL_YALNIZ_ALARM:-0}" = 1 ]; then radar_bir_kez; exit 0; fi   # K-80: saatlik denetim zamanlayıcısı (sg-sanal-denetim): yalnız dayanıklılık alarmı, güncelleme yok
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
if [ -z "$HEDEF" ] && [ -s "$YARIM" ]; then   # önceki güncelleme yarıda kesildi (D9)
  { read -r y_onceki; read -r y_yeni; read -r y_motor; read -r y_zaman; } < "$YARIM" || true
  if ! [[ "$y_onceki" =~ ^[0-9a-f]{40}$ ]] || ! [[ "$y_yeni" =~ ^[0-9a-f]{40}$ ]]; then
    log "yarım güncelleme işareti bozuk; silindi"; rm -f -- "$YARIM"
  elif [ -f "$DEPO/durum/DUR" ]; then
    log "yarım güncelleme işareti var ama durum/DUR (kasıtlı duruş) var; motor başlatılmaz"; rm -f -- "$YARIM"; rm -rf -- "$YEDEK"
  else
    aktif_motor="$y_motor"; aktif_zaman="$y_zaman"
    if [ "$head" = "$y_onceki" ]; then   # birleştirme olmamış: eski sürümle servisleri geri aç, normal akış sürsün
      log "yarım güncelleme (birleştirme öncesi) bulundu; eski sürümle servisler başlatılıyor"
      baslat_hepsi || log "UYARI: servisler başlatılamadı"
      rm -f -- "$YARIM"; rm -rf -- "$YEDEK"
      bildir WARN "⚠️ Yarım kalan güncelleme tamamlandı, bot yeniden başlatıldı"
    else                                  # birleştirme olmuş: uygulama yolunu tamamla
      devam=1; onceki="$y_onceki"; yeni="$head"
      lock_degisti=0; birim_degisti=0
      g diff --quiet "$onceki" "$yeni" -- requirements-canli.lock || lock_degisti=1
      konu="$(g log -1 --format=%s "$yeni" | tr -d '\000-\037' | cut -c1-120)"
      log "yarım kalan güncelleme tamamlanıyor: ${onceki:0:7} -> ${yeni:0:7} (${konu}); kilit değişti=$lock_degisti"
      mkdir -p "$YEDEK"
    fi
  fi
fi
if [ "$devam" = 1 ]; then :
elif [ -n "$HEDEF" ]; then
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
    if [ "$(cat "$DURUM/reddedilen" 2>/dev/null)" != "$yeni:ff" ]; then printf '%s\n' "$yeni:ff" > "$DURUM/reddedilen"; bildir WARN "⚠️ Bot güncellemesi başarısız, eski sürümle devam ediyor"; fi
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

if [ "$devam" != 1 ]; then   # (yarım kalan güncelleme devamında: denetimler/durdurma/birleştirme zaten yapıldı)
# durum/ kayit/ pano/ yerel durumdur: gelen commit bunları izlemeye başlarsa dokunma
if [ -n "$(g diff --name-only "$head" "$yeni" -- durum kayit pano)" ]; then
  log "hedef commit durum/ kayit/ pano/ yollarını içeriyor; yerel durum korunsun diye REDDEDİLDİ"
  if [ "$(cat "$DURUM/reddedilen" 2>/dev/null)" != "$yeni:durum" ]; then printf '%s\n' "$yeni:durum" > "$DURUM/reddedilen"; bildir WARN "⚠️ Bot güncellemesi başarısız, eski sürümle devam ediyor"; fi
  exit 0
fi

lock_degisti=0; birim_degisti=0
g diff --quiet "$onceki" "$yeni" -- requirements-canli.lock || lock_degisti=1
konu="$(g log -1 --format=%s "$yeni" | tr -d '\000-\037' | cut -c1-120)"
log "güncelleme: ${onceki:0:7} -> ${yeni:0:7} (${konu}); kilit değişti=$lock_degisti"

aktif_motor=0; aktif_zaman=""
yayim_taze; yayim_once=$?                                   # K-80: öz-denetim yalnız güncelleme ÖNCESİ taze olan yayımı sınar (önceden bozuk yayım güncellemeyi geri aldırmasın)
aktif sg-sanal && aktif_motor=1
for t in $ZAMANLAYICILAR; do if aktif "$t"; then aktif_zaman="$aktif_zaman $t"; fi; done
rm -rf -- "$YEDEK"; mkdir -p "$YEDEK" || exit 1
for f in "$BIRIM_DIZIN"/sg-sanal*.service "$BIRIM_DIZIN"/sg-sanal*.timer; do [ -f "$f" ] && cp -- "$f" "$YEDEK/"; done
printf '%s\n%s\n%s\n%s\n' "$onceki" "$yeni" "$aktif_motor" "$aktif_zaman" > "$YARIM.tmp" && mv -f -- "$YARIM.tmp" "$YARIM" || exit 1      # durdurmadan ÖNCE (D9)

"$SYSTEMCTL" stop $ZAMANLAYICILAR || true
"$SYSTEMCTL" stop sg-sanal || geri_al "sg-sanal durdurulamadı"           # durdururken son durum yayımlanır
if [ -n "$HEDEF" ]; then g reset -q --hard "$yeni" || geri_al "git reset başarısız"; else g merge -q --ff-only "$yeni" || geri_al "git merge --ff-only başarısız"; fi
fi
if [ "$lock_degisti" = 1 ]; then pip_kur || geri_al "pip install başarısız"; fi
birimleri_kur || geri_al "birim dosyaları kurulamadı"
duman_testi || geri_al "duman testi (sg-sanal-kontrol) başarısız"
if [ -z "$HEDEF" ]; then donem_sifirla; fi                                                       # K-85: yeni dönem (DONEM değişti) → yerel durum/kayıt/pano sıfırdan (arşiv klasörü YOK)
isaret_yaz                                                                                       # K-80: servisler başlamadan ÖNCE (ilk dakikadan 15 dk yalnız ölümcül uyarı)
baslat_ms=$(( $(date +%s) * 1000 - 2000 ))
baslat_hepsi || geri_al "servisler başlatılamadı"
sleep "$BEKLE"
motor_saglam || geri_al "sg-sanal ${BEKLE} sn sonra aktif değil"

[ -f "$BIRIM_DIZIN/sg-sanal-ikinci-alarm.timer" ] && { "$SYSTEMCTL" enable --now sg-sanal-ikinci-alarm.timer >/dev/null 2>&1 || log "ikinci alarm zamanlayıcısı açılamadı"; }   # bot durdu 20 dk ikinci mesaj (elle kurulum gerekmesin)
[ -f "$BIRIM_DIZIN/sg-sanal-denetim.timer" ] && { "$SYSTEMCTL" enable --now sg-sanal-denetim.timer >/dev/null 2>&1 || log "saatlik denetim zamanlayıcısı açılamadı"; }   # K-80: saatlik dayanıklılık alarmı (güncelleme günde 2 pencere)
[ -f "$BIRIM_DIZIN/sg-sanal-bekci.timer" ] && { "$SYSTEMCTL" enable --now sg-sanal-bekci.timer >/dev/null 2>&1 || log "60 dk bekçi zamanlayıcısı açılamadı"; }   # K-80: yeni sürümden sonra 60 dk sağlık sayaçları; eşik aşılırsa otomatik geri dönüş
[ -f "$BIRIM_DIZIN/sg-sanal-koruyucu.service" ] && { { "$SYSTEMCTL" enable sg-sanal-koruyucu.service >/dev/null 2>&1 && "$SYSTEMCTL" restart sg-sanal-koruyucu.service >/dev/null 2>&1; } || log "koruyucu servisi açılamadı"; }   # K-82: CT yerel koruyucu (ayrı süreç; restart = yeni kod yüklenir; durumu dosyada, güvenli)
[ -f "$BIRIM_DIZIN/sg-sanal-radar.timer" ] && { "$SYSTEMCTL" enable --now sg-sanal-radar.timer >/dev/null 2>&1 || log "radar zamanlayıcısı açılamadı"; }   # günlük radar sunucuda (K-78; 00:37 UTC; elle kurulum gerekmesin; --now: Persistent kaçan koşuyu yakalar)
if [ -f "$BIRIM_DIZIN/sg-sanal-binance-kagit.service" ] && [ ! -e "$DURUM/binance_kagit_kapali" ]; then   # K-81: Binance kâğıt motoru (HL sanal ile paralel kıyas) oto-kurulur, yeni kod için yeniden başlatılır. Kalıcı kapatma: $DURUM/binance_kagit_kapali
  if [ "$("$SYSTEMCTL" show -p ExecMainStatus --value sg-sanal-binance-kagit.service 2>/dev/null)" = 4 ]; then
    log "binance kâğıt: son çıkış 4 (Binance erişimi yok); yeniden başlatılmadı (her pencerede aynı ⚠️ tekrarlanmasın)"
  else
    "$SYSTEMCTL" enable sg-sanal-binance-kagit.service >/dev/null 2>&1 || log "binance kâğıt birimi etkinleştirilemedi"
    "$SYSTEMCTL" restart --no-block sg-sanal-binance-kagit.service >/dev/null 2>&1 || log "binance kâğıt başlatılamadı"
  fi
fi
if [ -f "$BIRIM_DIZIN/sg-sanal-olcum.service" ] && [ ! -e "$DURUM/olcum_basladi" ]; then   # 5a fiyat farkı ölçümü: BİR KEZ başlatılır (96 sa sonra kendi biter; işaret varken yeniden başlatılmaz)
  if "$SYSTEMCTL" start --no-block sg-sanal-olcum.service >/dev/null 2>&1; then date -u +%FT%TZ > "$DURUM/olcum_basladi"; log "fiyat farkı ölçümü başlatıldı"; else log "fiyat farkı ölçümü başlatılamadı"; fi
fi
radar_bir_kez
if [ -z "$HEDEF" ]; then   # K-80: kurulum sonrası öz-denetim; başarısızsa geri alma (geri_al)
  if oz_neden="$(oz_denetim)"; then log "öz-denetim tamam"; else geri_al "öz-denetim başarısız: $oz_neden"; fi
fi
printf '%s\n' "$yeni" > "$DURUM/uygulanan_sha"
rm -f "$DURUM/kotu_sha" "$DURUM/reddedilen" "$YARIM"; rm -rf "$YEDEK"
if [ "$devam" = 1 ]; then bildir WARN "⚠️ Yarım kalan güncelleme tamamlandı, bot yeniden başlatıldı"; fi
if [ -n "$HEDEF" ]; then
  rm -f -- "$BEKCI"                                                              # geri dönüş bitti: 60 dk bekçi işareti kalkar
  if [ -n "$GERI_NEDEN" ]; then   # K-80: bekçi/otomatik geri dönüş: bozuk sha işaretlenir (sonraki pencerede aynı sürüm tekrar kurulmaz) + tek ⚠️ satır
    [[ "$KOTU_SHA" =~ ^[0-9a-f]{40}$ ]] && printf '%s\n' "$KOTU_SHA" > "$DURUM/kotu_sha"
    bildir WARN "⚠️ Yeni sürüm sorun çıkardı, önceki sürüme dönüldü (${GERI_NEDEN})"
    log "bekçi geri dönüşü: ${onceki:0:7}→${yeni:0:7}; neden: ${GERI_NEDEN}; kötü sha: ${KOTU_SHA:0:7}"
  else
    bildir WARN "⚠️ Bot önceki sürüme döndürüldü"                                # tek satır; sürüm numaraları günlükte
    log "elle geri alındı: ${onceki:0:7}→${yeni:0:7} (${konu})"
  fi
else
  { printf '%s\n%s\n%s\n%s\n' "$(date +%s)" "$yeni" "$onceki" "$aktif_motor" > "$BEKCI.tmp" && mv -f -- "$BEKCI.tmp" "$BEKCI"; } || log "UYARI: 60 dk bekçi işareti yazılamadı"   # K-80: 60 dk bekçi başlar
  date -u +%F >> "$DURUM/guncelleme_gunlugu"; tail -n 200 "$DURUM/guncelleme_gunlugu" > "$DURUM/guncelleme_gunlugu.tmp" && mv -f "$DURUM/guncelleme_gunlugu.tmp" "$DURUM/guncelleme_gunlugu"      # günlük rapor: "Bot bugün N kez güncellendi"
  log "güncellendi: ${onceki:0:7}→${yeni:0:7} (${konu})"                        # Telegram'a mesaj YOK (yalnız günlük)
fi
log "tamam: ${yeni:0:7}"
exit 0
