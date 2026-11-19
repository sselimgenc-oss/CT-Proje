#!/usr/bin/env bash
# Sunucu SANAL motoru: mod değiştirme (root olarak): sudo bash /var/lib/sg-sanal/depo/deploy/sanal_mod.sh uretim
#   (Eski "deneme" modu — ayrı veri dalı ve ayrı pano — 19.11 tam geçişle kaldırıldı; dal ve Worker silindi.)
#   uretim = veri dalı canli-durum, pano sg-pano (Actions vardiyası KAPALI olmalı: GitHub → Settings → Variables → SUNUCU_AKTIF=evet)
# Yapar: servisleri durdurur (durdururken son yayım yapılır) → yerel durumu SİLMEDEN arşive taşır (/var/lib/sg-sanal/arsiv/<tarih>-<eski mod>) → /etc/sg-sanal-mod.env (sırsız) yazar. Servisi BAŞLATMAZ.
# Başlatma: sudo systemctl enable --now sg-sanal sg-sanal-yayim.timer sg-sanal-pano.timer (uretim ilk açılışta Actions vardiyası bitene kadar bekler: sanal_baslat.sh geçiş kapısı).
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "root olarak çalıştırın (sudo)." >&2; exit 1; }
mod="${1:-}"
case "$mod" in
  uretim) dal=canli-durum; pano=sg-pano ;;
  *) echo "Kullanım: sanal_mod.sh uretim (deneme modu kaldırıldı)" >&2; exit 2 ;;
esac
if [ "$mod" = uretim ] && [ "${SANAL_ONAY:-}" != evet ]; then
  echo "UYARI: üretim modunda sunucu canlı panoyu ve canli-durum dalını yönetir. Actions vardiyası KAPALI olmalı (GitHub → Settings → Secrets and variables → Actions → Variables: SUNUCU_AKTIF = evet)."
  read -r -p "Bunu yaptınız mı? Yaptıysanız 'evet' yazın: " yanit
  [ "$yanit" = evet ] || { echo "İptal edildi; hiçbir şey değişmedi."; exit 1; }
fi
depo="${SANAL_DEPO:-/var/lib/sg-sanal/depo}"
systemctl stop sg-sanal-pano.timer sg-sanal-yayim.timer 2>/dev/null || true
systemctl stop sg-sanal 2>/dev/null || true
eski=yok
if [ -f /etc/sg-sanal-mod.env ]; then eski="$(sed -n 's/^SUNUCU_MOD=//p' /etc/sg-sanal-mod.env | head -n1)"; fi
if [ -d "$depo/durum" ] || [ -d "$depo/kayit" ]; then
  arsiv="/var/lib/sg-sanal/arsiv/$(date -u +%Y%m%dT%H%M%SZ)-${eski:-yok}"
  mkdir -p "$arsiv"
  for d in durum kayit pano; do
    if [ -e "$depo/$d" ]; then mv "$depo/$d" "$arsiv/$d"; fi
  done
  chown -R sgsanal:sgsanal /var/lib/sg-sanal/arsiv
  echo "Eski durum arşive taşındı: $arsiv"
fi
rm -f /var/lib/sg-sanal/pano_son.sha
umask 022
printf 'SUNUCU_MOD=%s\nVERI_DALI=%s\nPANO_ISIM=%s\nKADRO_DALI=radar\n' "$mod" "$dal" "$pano" > /etc/sg-sanal-mod.env
echo "Mod: $mod (dal $dal, pano $pano). Başlatmak için: sudo systemctl enable --now sg-sanal sg-sanal-yayim.timer sg-sanal-pano.timer"
