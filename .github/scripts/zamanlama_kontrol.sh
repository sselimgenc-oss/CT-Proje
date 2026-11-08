#!/usr/bin/env bash
# Yedek cron güvencesi (T6 §4, K-37). Kullanım: zamanlama_kontrol.sh radar|canli
# Birincil cron tetiklenmediyse (2026-11-05'te radar.yml hiç tetiklenmedi) YEDEK cron aynı işi başlatır; iş zaten yapılmışsa HİÇBİR ŞEY yapmadan biter:
#   radar : veri dalında bugünün `radar/<tarih>/havuz.json` dosyası varsa atla.
#   canli : veri dalındaki `durum/kilit.json` taze ise (birakildi=false ve nabız < canli_kilit_dk) atla. Bu "BAŞLAMADI" alarmı DEĞİLDİR (beklenen durum): yalnız iş özetine bilgi satırı.
# Atlayabildiği olaylar: `schedule` (radar: her schedule; canli: zamanlama dizgisi YEDEK_CRON'a eşitse) ve canli için `workflow_dispatch` (G3: vardiya zinciri sonrakini dispatch ile tetikler; kilit taze/bırakılmamışsa atlar, çift vardiya olmasın). Push ve radar'ın elle tetiklemesi her zaman çalışır. Çıktı: `atla=true|false` (GITHUB_OUTPUT).
set -euo pipefail
mod="${1:?radar|canli}"
veri_dali="${VERI_DALI:?}"
atla=false
neden="yedek cron değil: normal çalışır"
# radar: HER schedule koşusu (birincil de) bugün yapılmışsa atlar — geç gelen birincil koşu kadroyu gün içinde ikinci kez yazmasın (Opus denetimi, 05.11). canli: yalnız yedek cron.
olay="${GITHUB_EVENT_NAME:-}"
# G3: canli için workflow_dispatch de aynı "taze kilit varsa atla" mantığına girer (vardiya zinciri bir sonrakini dispatch ile tetikler; çift vardiya olmasın).
if { [ "$olay" = schedule ] && { [ "$mod" = radar ] || { [ -n "${YEDEK_CRON:-}" ] && [ "${ZAMANLAMA:-}" = "$YEDEK_CRON" ]; }; }; } || { [ "$olay" = workflow_dispatch ] && [ "$mod" = canli ]; }; then
  neden="yedek cron/dispatch; veri dalı ($veri_dali) yok: çalışır"
  if git ls-remote --exit-code --heads origin "$veri_dali" >/dev/null; then
    git fetch -q --depth=1 origin "$veri_dali"
    case "$mod" in
      radar)
        bugun="$(date -u +%F)"
        if git cat-file -e "FETCH_HEAD:radar/$bugun/havuz.json" 2>/dev/null; then atla=true; neden="yedek cron: radar/$bugun/ zaten var — iş yapılmadı"; else neden="yedek cron: radar/$bugun/ yok — çalışır"; fi
        ;;
      canli)
        kilit_dk="$(grep -E '^canli_kilit_dk:' copytrade/kurallar.yaml | awk '{print $2}')"
        if git cat-file -e "FETCH_HEAD:durum/kilit.json" 2>/dev/null; then
          taze="$(git show FETCH_HEAD:durum/kilit.json | python3 -c 'import json,sys,time; k=json.load(sys.stdin); print("evet" if (not k.get("birakildi")) and time.time()*1000-int(k.get("nabiz_ms",0)) < float(sys.argv[1])*60000 else "hayir")' "$kilit_dk")"
        else
          taze=hayir
        fi
        # A-2 (b) (denetim 08.11): kilitteki `vardiya` = sahibi koşunun run_id'si (motor `--vardiya $GITHUB_RUN_ID`). Son yayım düşüp kilit bırakılmadan kaldıysa ve o koşu
        # BİTMİŞSE (gh api status=completed) kilit bayattır: vardiya başlar (zincir kopmaz). Okunamazsa kilit taze sayılır (güvenli yön: çift vardiya yok).
        if [ "$taze" = evet ]; then
          sahip="$(git show FETCH_HEAD:durum/kilit.json | python3 -c 'import json,sys; print(json.load(sys.stdin).get("vardiya") or "")')"
          case "$sahip" in
            ''|*[!0-9]*) ;;
            *)
              sahip_durum=""
              if ! sahip_durum="$(gh api "repos/${GITHUB_REPOSITORY:-}/actions/runs/${sahip}" --jq .status 2>/dev/null)"; then sahip_durum=""; fi
              if [ "$sahip_durum" = completed ]; then
                taze=hayir
                echo "::warning::kilit bırakılmamış ama sahibi koşu ($sahip) bitmiş: bayat kilit, vardiya başlar"
              fi
              ;;
          esac
        fi
        if [ "$taze" = evet ]; then atla=true; neden="$olay: kilit taze (başka vardiya aktif) — başlamadı (beklenen, alarm yok)"; else neden="$olay: kilit taze değil — vardiya başlar"; fi
        ;;
      *) echo "bilinmeyen mod: $mod" >&2; exit 1 ;;
    esac
  else
    status=$?
    if [ "$status" -ne 2 ]; then exit "$status"; fi
  fi
fi
echo "atla=$atla" >> "${GITHUB_OUTPUT:-/dev/null}"
echo "zamanlama kontrolü [$mod]: $neden"
if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then echo "- zamanlama kontrolü [$mod]: $neden (atla=$atla)" >> "$GITHUB_STEP_SUMMARY"; fi
