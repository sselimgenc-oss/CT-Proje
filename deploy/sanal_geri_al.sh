#!/usr/bin/env bash
# Sunucu SANAL motoru: ELLE geri alma (root): sudo bash /var/lib/sg-sanal/depo/deploy/sanal_geri_al.sh <sha>
# İki adım: (1) 'evet' onayı, (2) başarılı olursa otomatik güncelleme DONDURULUR (aksi halde saatlik güncelleme yeniden ileri sarardı). Dondurmayı kaldırma: sudo rm /var/lib/sg-sanal-guncelle/dondur
# Asıl işi deploy/sanal_guncelle.sh yapar (SANAL_HEDEF_SHA kipi: aynı kilit, duman testi, hata olursa önceki sürüme dönüş, Telegram). sha sunucudaki depoda yerel olarak bulunmalı.
set -euo pipefail
[ "$(id -u)" -eq 0 ] || [ -n "${SANAL_KULLANICI+x}" ] || { echo "root olarak çalıştırın (sudo)." >&2; exit 1; }
sha="${1:-}"
[[ "$sha" =~ ^[0-9a-f]{7,40}$ ]] || { echo "Kullanım: sanal_geri_al.sh <sha (7-40 hex)>" >&2; exit 2; }
depo="${SANAL_DEPO:-/var/lib/sg-sanal/depo}"
durum="${SANAL_DURUM_DIZIN:-/var/lib/sg-sanal-guncelle}"
kullanici="${SANAL_KULLANICI-sgsanal}"
git_c() { if [ -n "$kullanici" ] && [ "$(id -un)" != "$kullanici" ]; then runuser -u "$kullanici" -- git -C "$depo" "$@"; else git -C "$depo" "$@"; fi; }
tam="$(git_c rev-parse --verify -q "${sha}^{commit}")" || { echo "HATA: $sha depoda bulunamadı." >&2; exit 2; }
echo "Şu an : $(git_c log -1 --format='%h %s' HEAD)"
echo "Hedef : $(git_c log -1 --format='%h %s (%ci)' "$tam")"
echo "Servisler durdurulur, depo bu sürüme ALINIR, duman testi yapılır, servisler başlar. Otomatik güncelleme sonra DONDURULUR."
read -r -p "Onaylıyor musunuz? 'evet' yazın: " yanit
[ "$yanit" = evet ] || { echo "İptal edildi; hiçbir şey değişmedi."; exit 1; }
SANAL_HEDEF_SHA="$tam" bash "$(dirname "$0")/sanal_guncelle.sh"
mkdir -p "$durum"
printf '%s\n' "$tam" > "$durum/dondur"
echo "Geri alındı: ${tam:0:7}. Otomatik güncelleme DONDURULDU (kaldırmak için: sudo rm $durum/dondur)."
