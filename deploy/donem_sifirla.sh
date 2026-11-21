#!/usr/bin/env bash
# K-85 ortak dönem sıfırlama (sanal_guncelle.sh VE sanal_baslat.sh kullanır; tek kopya: tutma listesi iki yerde ayrışmasın).
# Yerel durum dönemi (durum/donem.txt) depodaki copytrade/canli/DONEM'den farklıysa (ya da donem.txt yok ama CT durumu var) eski CT durum/kayıt/pano SİLİNİR, yeni donem.txt yazılır.
# Neden sanal_baslat'ta da: güncelleme betiği merge'den ÖNCE kendi geçici kopyasından koşar; yeni sürümün donem_sifirla'sı o güncellemede çalışmaz → eski durum (kasa 10000 $) yeni dönemle çakışıp motor çıkış 3 verirdi.
# Ortam: SANAL_DEPO (varsayılan /var/lib/sg-sanal/depo), SANAL_KULLANICI (boş değilse chown; yalnız root). Hata sıfırlamayı bozmaz (çıkış 0).
DEPO="${SANAL_DEPO:-/var/lib/sg-sanal/depo}"
KULLANICI="${SANAL_KULLANICI-}"
log() { echo "donem_sifirla: $*"; }
donem_sifirla() {
  # Arşiv klasörü açılmaz; eski dönemin verisi veri dalında (canli-durum, git geçmişi) kalır. Servisler bu sırada DURMUŞTUR. Hata güncellemeyi bozmaz.
  local yeni_donem eski_donem
  yeni_donem="$(tr -d '[:space:]' < "$DEPO/copytrade/canli/DONEM" 2>/dev/null)" || return 0
  [ -n "$yeni_donem" ] || return 0
  eski_donem="$(tr -d '[:space:]' < "$DEPO/durum/donem.txt" 2>/dev/null)"
  [ "$eski_donem" = "$yeni_donem" ] && return 0
  log "yeni dönem ${yeni_donem} (yerelde: '${eski_donem:-yok}'): durum/kayıt/pano sıfırlanıyor"
  [ -e "$DEPO/durum/DUR" ] && log "UYARI: durum/DUR (elle durdurma) var; silinmedi, yeni dönemde de motor durur"
  # Yalnız CT motor/koruyucu/pano durumu silinir; KORUNAN: binance kâğıt (durum/binance_kagit*, kayit/binance_kagit), fiyat ölçümü (olcum*), paylaşım/ortak, DUR, dağıtım işaretleri ve bekçi/alarm dosyaları.
  local f ad
  for f in "$DEPO/durum"/* "$DEPO/durum"/.[!.]*; do
    [ -e "$f" ] || continue
    ad="$(basename "$f")"
    case "$ad" in
      guncelleme_zamani|donem.txt|DUR|binance_kagit*|olcum*|paylasim*|ortak|kotu_sha|reddedilen|uygulanan_sha|bekci*|guncelleme_gunlugu*|yedek_birimler|dondur|bakim_sn|yarim|alarm_*|tg_bot_durdu*|radar_basladi|motor.lock) continue ;;
    esac
    rm -rf -- "$f" 2>/dev/null || log "UYARI: durum/$ad silinemedi"
  done
  if [ -d "$DEPO/kayit" ]; then
    for f in "$DEPO/kayit"/* "$DEPO/kayit"/.[!.]*; do
      [ -e "$f" ] || continue
      case "$(basename "$f")" in binance_kagit*|olcum*) continue ;; esac
      rm -rf -- "$f" 2>/dev/null || log "UYARI: kayit/$(basename "$f") silinemedi"
    done
  fi
  [ -d "$DEPO/pano" ] && { find "$DEPO/pano" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + 2>/dev/null || log "UYARI: pano temizlenemedi"; }
  mkdir -p "$DEPO/durum" && printf '%s\n' "$yeni_donem" > "$DEPO/durum/donem.txt" && chmod 644 "$DEPO/durum/donem.txt" \
    && { [ -z "$KULLANICI" ] || chown -R "$KULLANICI" "$DEPO/durum" "$DEPO/kayit" "$DEPO/pano" 2>/dev/null || true; } || log "UYARI: durum/donem.txt yazılamadı"
}
donem_sifirla
exit 0
