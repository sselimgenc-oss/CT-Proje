// G-10 (denetim 08.11): DIŞ ölü adam alarmı. Cloudflare Worker `sg-nabiz`, Cron Trigger 10 dk'da bir (GitHub Actions cron'una BAĞLI DEĞİL).
// SALT OKUR: veri dalı `canli-durum`'daki `durum/kilit.json` (`nabiz_ms`, `birakildi`) ve `durum/ozet.json` (`yazildi_ms`) ile main'deki
// `copytrade/canli/DONEM` (dönem başlangıcı, UTC ISO) okunur. Emir, anahtar, yazma YOK; yalnız Telegram'a mesaj (secret'lar worker'da).
// Karar (saf, test edilir: tests/test_nabiz.py): yaş = şimdi − max(son nabız, dönem başı). yaş < ESIK_DK → sessiz.
// Durum tutulmaz (KV yok): yaş [ESIK, ESIK+TIK) aralığındaki İLK tikte alarm, sonra her TEKRAR_DK'da bir (yaş − ESIK) mod TEKRAR < TIK.
// Veri okunamazsa (3 deneme, ~80 sn) durum "bilinmiyor": alarm yalnız UTC 3 saatlik ızgaranın ilk tikinde (00:00, 03:00, … +10 dk) — tek kesintide en çok bir uyarı.
// Y-3: kaynak ayarlanabilir — wrangler değişkeni `NABIZ_KAYNAK` (yayında `--var`, GitHub `vars.NABIZ_KAYNAK`): boş → `canli-durum` (sanal); dal adı (aynı depo) ya da
// https ham kök adresi (ör. gerçek motorun `canli-gercek` dalı). Kökte `durum/kilit.json` + `durum/ozet.json` aranır. Gerçek paradan ÖNCE gerçek yayım hedefine çevrilmeli.

const DAKIKA = 60000;
const DEPO = "sselimgenc-oss/CT-Proje";
const HAM = `https://raw.githubusercontent.com/${DEPO}`;
export const VARSAYILAN_DAL = "canli-durum";
// Y-3: veri kökü. Geçersiz değer (boşluk, http, garip karakter) → varsayılan (sessizce yanlış yere bakmasın diye `kaynak_ozel` yanıtta görünür).
export function kaynak(env = {}) {
  const v = String(env.NABIZ_KAYNAK ?? "").trim();
  let kok = `${HAM}/${VARSAYILAN_DAL}`;
  let ozel = false;
  if (/^https:\/\/[^\s?#]+$/.test(v) && !/\/\.\.?(\/|$)/.test(v)) {
    kok = v.replace(/\/+$/, "");
    ozel = true;
  } else if (/^[A-Za-z0-9._-]+(\/[A-Za-z0-9._-]+)*$/.test(v) && !v.split("/").some((p) => /^\.+$/.test(p)) && v !== VARSAYILAN_DAL) {
    kok = `${HAM}/${v}`;
    ozel = true;
  }
  return { kilit: `${kok}/durum/kilit.json`, ozet: `${kok}/durum/ozet.json`, donem: `${HAM}/main/copytrade/canli/DONEM`, ozel };
}
export const KAYNAK = (({ kilit, ozet, donem }) => ({ kilit, ozet, donem }))(kaynak({}));
export const ACTIONS_URL = `https://github.com/${DEPO}/actions/workflows/canli_vardiya.yml`;
export const VARSAYILAN = { esik_dk: 45, tekrar_dk: 180, tik_dk: 10 };

// Saf karar. Zamanlar UTC ms; eşikler dakika. son_ms null = bilinmiyor (veri okunamadı). donem_ms: dönem başlangıcı (yoksa null).
export function karar(simdi_ms, son_ms, esik_dk = VARSAYILAN.esik_dk, tekrar_dk = VARSAYILAN.tekrar_dk, ek = {}) {
  const tik_dk = ek.tik_dk ?? VARSAYILAN.tik_dk;
  const donem_ms = Number.isFinite(ek.donem_ms) ? ek.donem_ms : null;
  if (donem_ms !== null && simdi_ms < donem_ms) return { alarm: false, durum: "donem_bekleniyor", yas_dk: null };
  if (!Number.isFinite(son_ms)) {
    const dk = Math.floor(simdi_ms / DAKIKA);
    return { alarm: dk % tekrar_dk < tik_dk, durum: "bilinmiyor", yas_dk: null };
  }
  const taban = donem_ms !== null ? Math.max(son_ms, donem_ms) : son_ms;
  const yas_dk = Math.max(0, (simdi_ms - taban) / DAKIKA);
  if (yas_dk < esik_dk) return { alarm: false, durum: "taze", yas_dk };
  return { alarm: (yas_dk - esik_dk) % tekrar_dk < tik_dk, durum: "bayat", yas_dk };
}

// En yeni nabız/yayım zamanı (UTC ms): kilit.nabiz_ms ve ozet.yazildi_ms'in büyüğü; geçerli değer yoksa null.
export function son_zaman(kilit, ozet) {
  const z = [kilit?.nabiz_ms, ozet?.yazildi_ms].map(Number).filter((x) => Number.isFinite(x) && x > 0);
  return z.length ? Math.max(...z) : null;
}

export function ayarlar(env = {}) {
  const sayi = (v, d, alt) => {
    const n = Number(v);
    return Number.isFinite(n) && n >= alt ? n : d;
  };
  const tik_dk = VARSAYILAN.tik_dk;
  return { esik_dk: sayi(env.ESIK_DK, VARSAYILAN.esik_dk, 1), tekrar_dk: sayi(env.TEKRAR_DK, VARSAYILAN.tekrar_dk, tik_dk), tik_dk };
}

const bekle = (ms) => new Promise((r) => setTimeout(r, ms));

async function al(url, tur, bekleme_ms) {
  for (let i = 0; i <= bekleme_ms.length; i++) {
    try {
      const r = await fetch(`${url}?t=${Date.now()}`, { headers: { "user-agent": "sg-nabiz" }, cf: { cacheTtl: 0 } });
      if (r.ok) return tur === "json" ? await r.json() : await r.text();
    } catch (_) {
      // ağ hatası / bozuk JSON: yeniden dene
    }
    if (i < bekleme_ms.length) await bekle(bekleme_ms[i]);
  }
  return null;
}

// Bir kontrol turu (gönderim yok). bekleme_ms: denemeler arası bekleme (zamanlı tik: [20 sn, 60 sn]; elle sorgu: []).
export async function kontrol(env, simdi_ms, bekleme_ms = [20000, 60000]) {
  const a = ayarlar(env);
  const kay = kaynak(env);
  const [kilit, ozet, donem_metin] = await Promise.all([al(kay.kilit, "json", bekleme_ms), al(kay.ozet, "json", bekleme_ms), al(kay.donem, "text", [])]);
  const donem = donem_metin ? Date.parse(donem_metin.trim()) : NaN;
  const donem_ms = Number.isFinite(donem) ? donem : null;
  const son_ms = son_zaman(kilit, ozet);
  const k = karar(simdi_ms, son_ms, a.esik_dk, a.tekrar_dk, { donem_ms, tik_dk: a.tik_dk });
  return { ...k, simdi_ms, son_ms, donem_ms, birakildi: kilit ? Boolean(kilit.birakildi) : null, vardiya: kilit?.vardiya ?? null,
    okundu: { kilit: kilit !== null, ozet: ozet !== null, donem: donem_ms !== null }, kip: ozet?.kip ?? null, kaynak_ozel: kay.ozel, ...a };
}

// Mesaj etiketi: ozet.kip (gercek/sanal); okunamadıysa varsayılan kaynak → "Sanal motor", özel kaynak → "Motor" (kip bilinmiyor).
function etiket(s) {
  if (s.kip === "gercek") return "Gerçek motor";
  if (s.kip === "sanal" || !s.kaynak_ozel) return "Sanal motor";
  return "Motor";
}

export function mesaj(s) {
  const ad = etiket(s);
  const sunucu = ad !== "Sanal motor";
  if (s.durum === "bilinmiyor") {
    return `⚠️ UYARI: ${ad} nabzı okunamadı (GitHub ham veri 3 denemede erişilemedi). Elle bakın: ${sunucu ? "sunucuda systemctl status sg-canli" : ACTIONS_URL}`;
  }
  const ek = s.birakildi ? " (son vardiya kilidi bıraktı, yenisi başlamadı)" : "";
  const neden = sunucu ? "Motor ya da yayım (sg-canli-yayim) durmuş olabilir: sunucuda systemctl status sg-canli sg-canli-yayim.timer" : `Vardiya zinciri kopmuş olabilir: ${ACTIONS_URL}`;
  return `🚨 ALARM: ${ad} nabzı yok — son yayım ${Math.round(s.yas_dk)} dk önce${ek}. ${neden}\n(sg-nabiz; sürerse ${Math.round(s.tekrar_dk / 60)} saatte bir yinelenir)`;
}

export function telegram_acik(env) {
  return env.TELEGRAM_ACIK === "evet" && Boolean(env.TELEGRAM_BOT_TOKEN) && Boolean(env.TELEGRAM_CHAT_ID);
}

async function gonder(env, metin) {
  if (!telegram_acik(env)) {
    console.log("telegram kapalı (TELEGRAM_ACIK != evet ya da secret yok); mesaj gönderilmedi");
    return false;
  }
  try {
    const r = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ chat_id: env.TELEGRAM_CHAT_ID, text: metin, disable_web_page_preview: true }),
    });
    if (!r.ok) console.log(`telegram gönderilemedi: HTTP ${r.status}`);
    return r.ok;
  } catch (_) {
    console.log("telegram gönderilemedi: ağ hatası");
    return false;
  }
}

// Zamanlı tur: kontrol + gerekiyorsa Telegram. simdi_ms = tikin planlanan anı (pencere hesabı tik ızgarasına oturur).
export async function calis(env, simdi_ms, bekleme_ms) {
  const s = await kontrol(env, simdi_ms, bekleme_ms);
  console.log(JSON.stringify({ durum: s.durum, alarm: s.alarm, yas_dk: s.yas_dk, okundu: s.okundu }));
  if (s.alarm) s.gonderildi = await gonder(env, mesaj(s));
  return s;
}

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(calis(env, event.scheduledTime));
  },
  // Elle kontrol: JSON durum (gönderim YOK; secret değeri dönmez). `alarm` = bu an bir tik olsaydı alarm verilir miydi.
  async fetch(_istek, env) {
    const s = await kontrol(env, Date.now(), []);
    const k = kaynak(env);
    const govde = { ...s, telegram: telegram_acik(env) ? "acik" : "kapali", kaynak: { kilit: k.kilit, ozet: k.ozet, donem: k.donem } };
    return new Response(JSON.stringify(govde, null, 2), { headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" } });
  },
};
