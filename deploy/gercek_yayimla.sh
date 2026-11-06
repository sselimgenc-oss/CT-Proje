#!/usr/bin/env bash
# Gerçek motor nabzı (G8). Okur: $DURUM_DIZIN/ozet.json + kilit.json (+ motor.json/risk.json'dan YALNIZ hl_ofset, kasa_usd, mutabakat/dur bayrakları -> nabiz.json). Yazar: $NABIZ_DIZIN/{ozet,kilit,nabiz}.json (MASKELİ: adresler 0xAAAA…ZZZZ, 41+ hanelik onaltılık dizi ve anahtar/gizli adlı alanlar atılır).
# Hedef: GERCEK_YAYIM_HEDEF (ortam; boşsa yalnız yerel nabız). Biçim: git uzak adresi (https://…/depo.git); maskeli dosyalar 'canli-gercek' dalına itilir.
#   İsteğe bağlı GERCEK_YAYIM_TOKEN (yalnız ortamdan; http başlığıyla verilir, basılmaz). Hedef/token repoya KONMAZ. Yayım hedefi (K2/K3) kullanıcı kararı bekliyor.
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
EK=()
[ -n "${GERCEK_YAYIM_TOKEN:-}" ] && EK=(-c "http.extraheader=Authorization: Bearer ${GERCEK_YAYIM_TOKEN}")
if [ ! -d "$KLON/.git" ]; then
  git init -q "$KLON" && git -C "$KLON" remote add origin "$HEDEF" || { echo "yayim: git hazırlanamadı" >&2; exit 1; }
fi
git -C "$KLON" remote set-url origin "$HEDEF"
git -C "$KLON" checkout -q -B canli-gercek 2>/dev/null
mkdir -p "$KLON/durum"
cp "$NABIZ_DIZIN/ozet.json" "$NABIZ_DIZIN/kilit.json" "$KLON/durum/" && cp "$NABIZ_DIZIN/nabiz.json" "$KLON/"
git -C "$KLON" add -A
if ! git -C "$KLON" -c user.name=sg-canli -c user.email=sg-canli@localhost commit -q -m "nabiz $(date -u +%Y-%m-%dT%H:%MZ)" 2>/dev/null; then
  echo "yayim: değişiklik yok"
fi
if git -C "$KLON" "${EK[@]}" push -q --force origin canli-gercek 2>/dev/null; then
  echo "yayim: canli-gercek dalına itildi"
else
  echo "yayim: itme başarısız (yerel nabız yazıldı)" >&2
  exit 1
fi
