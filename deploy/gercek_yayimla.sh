#!/usr/bin/env bash
# Gerçek motor nabzı (G8). Okur: $DURUM_DIZIN/ozet.json + kilit.json (+ motor.json/risk.json'dan YALNIZ hl_ofset, kasa_usd, mutabakat/dur bayrakları -> nabiz.json). Yazar: $NABIZ_DIZIN/{ozet,kilit,nabiz}.json (MASKELİ: adresler 0xAAAA…ZZZZ, 41+ hanelik onaltılık dizi ve anahtar/gizli adlı alanlar atılır).
# Hedef: GERCEK_YAYIM_HEDEF (ortam; boşsa yalnız yerel nabız). Biçim: git uzak adresi (https://…/depo.git); maskeli dosyalar 'canli-gercek' dalına itilir.
#   İsteğe bağlı GERCEK_YAYIM_TOKEN (yalnız ortamdan, /etc/sg-canli-yayim.env; http başlığı git'e ORTAM DEĞİŞKENİYLE verilir — komut satırına/ps'e düşmez (S-21); hata çıktısında [gizli]). Hedef/token repoya KONMAZ. Yayım hedefi (K2/K3) kullanıcı kararı bekliyor.
#   Git hataları gizlenmez (S-21): stderr'e maskeli yazılır, çıkış 1.
# Hiçbir koşulda anahtar ya da tam adres basılmaz/yazılmaz. GITHUB_ACTIONS gerektirmez.
set -u
DURUM_DIZIN="${DURUM_DIZIN:-/var/lib/sg-canli/durum}"
NABIZ_DIZIN="${NABIZ_DIZIN:-/var/lib/sg-canli/yayim}"
mkdir -p "$NABIZ_DIZIN" || { echo "yayim: $NABIZ_DIZIN oluşturulamadı" >&2; exit 1; }
if [ ! -f "$DURUM_DIZIN/ozet.json" ]; then
  echo "yayim: ozet.json yok; nabız yazılmadı" >&2
  exit 1
fi
python3 -I - "$DURUM_DIZIN" "$NABIZ_DIZIN" <<'PY' || exit 1
import json, re, sys, time
from pathlib import Path
durum, cikti = Path(sys.argv[1]), Path(sys.argv[2])
ADRES = re.compile(r"0x[0-9a-fA-F]{40}")
UZUN_HEX = re.compile(r"(?:0x)?[0-9a-fA-F]{41,}")
GIZLI_AD = re.compile(r"anahtar|private|secret|token|password|sifre|seed|mnemonic", re.I)
def kisalt(s):
    s = UZUN_HEX.sub("[gizli]", s)
    return ADRES.sub(lambda m: m.group(0)[:6] + "…" + m.group(0)[-4:], s)
def maske(v):
    if isinstance(v, dict):
        return {kisalt(str(k)): ("[gizli]" if GIZLI_AD.search(str(k)) else maske(x)) for k, x in v.items()}
    if isinstance(v, list):
        return [maske(x) for x in v]
    if isinstance(v, str):
        return kisalt(v)
    return v
def oku(ad):
    try:
        return json.loads((durum / ad).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
ozet, kilit, motor, risk = oku("ozet.json"), oku("kilit.json"), oku("motor.json") or {}, oku("risk.json") or {}
if ozet is None:
    print("yayim: ozet.json okunamadı", file=sys.stderr)
    sys.exit(1)
(cikti / "ozet.json").write_text(json.dumps(maske(ozet), ensure_ascii=False, indent=1), encoding="utf-8")
(cikti / "kilit.json").write_text(json.dumps(maske(kilit or {}), ensure_ascii=False, indent=1), encoding="utf-8")
nabiz = {"yayim_ms": int(time.time() * 1000), "kip": ozet.get("kip"), "ozet_yazildi_ms": ozet.get("yazildi_ms"), "kilit_nabiz_ms": (kilit or {}).get("nabiz_ms"), "vardiya": ozet.get("vardiya"),
         "hl_ofset": motor.get("hl_ofset"), "kasa_usd": motor.get("kasa_usd", ozet.get("kasa_usd")), "mutabakat": bool((risk.get("acilis_durdu") or {}).get("mutabakat")), "dur": bool(risk.get("dur"))}   # yalnız sayı/bayrak
(cikti / "nabiz.json").write_text(json.dumps(maske(nabiz), ensure_ascii=False), encoding="utf-8")
print("yayim: yerel nabız yazıldı (kip=%s)" % ozet.get("kip"))
PY
HEDEF="${GERCEK_YAYIM_HEDEF:-}"
if [ -z "$HEDEF" ]; then
  echo "yayim: GERCEK_YAYIM_HEDEF yok; yalnız yerel nabız"
  exit 0
fi
KLON="${NABIZ_DIZIN}/git"
if [ -n "${GERCEK_YAYIM_TOKEN:-}" ]; then
  # S-21: başlık git'e ORTAM DEĞİŞKENİYLE verilir (git >= 2.31): token komut satırında (argv, ps, /proc/*/cmdline) görünmez
  export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=http.extraheader GIT_CONFIG_VALUE_0="Authorization: Bearer ${GERCEK_YAYIM_TOKEN}"
fi
gizle() {
  # stdin -> stderr: token ve URL içindeki kullanıcı bilgisi (://kullanıcı:şifre@) maskeli
  local m
  m="$(cat)"
  if [ -n "${GERCEK_YAYIM_TOKEN:-}" ]; then
    m="${m//"$GERCEK_YAYIM_TOKEN"/[gizli]}"
  fi
  [ -n "$m" ] && printf '%s\n' "$m" | sed -E 's#://[^/@[:space:]]+@#://[gizli]@#g' >&2
  return 0
}
calistir() {
  # git komutu; başarısızsa çıktısı GİZLENMEDEN (maskeli) stderr'e + "yayim: <adım> başarısız" + çıkış 1 (S-21)
  local adim="$1" cikti
  shift
  if ! cikti="$(git -C "$KLON" "$@" 2>&1)"; then
    printf '%s' "$cikti" | gizle
    echo "yayim: ${adim} başarısız (yerel nabız yazıldı)" >&2
    exit 1
  fi
}
if [ ! -d "$KLON/.git" ]; then
  mkdir -p "$KLON" || { echo "yayim: $KLON oluşturulamadı" >&2; exit 1; }
  calistir "git init" init -q
  calistir "uzak ekleme" remote add origin "$HEDEF"
fi
calistir "uzak adres" remote set-url origin "$HEDEF"
calistir "dal hazırlama" checkout -q -B canli-gercek
mkdir -p "$KLON/durum"
cp "$NABIZ_DIZIN/ozet.json" "$NABIZ_DIZIN/kilit.json" "$KLON/durum/" && cp "$NABIZ_DIZIN/nabiz.json" "$KLON/" || { echo "yayim: dosyalar kopyalanamadı" >&2; exit 1; }
calistir "git add" add -A
if git -C "$KLON" diff --cached --quiet; then
  echo "yayim: değişiklik yok"
else
  calistir "commit" -c user.name=sg-canli -c user.email=sg-canli@localhost commit -q -m "nabiz $(date -u +%Y-%m-%dT%H:%MZ)"
fi
calistir "itme" push -q --force origin canli-gercek
echo "yayim: canli-gercek dalına itildi"
