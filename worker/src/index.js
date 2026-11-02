import { eventId, isPerp, orderEvents } from "./events.js";

const INFO = "https://api.hyperliquid.xyz/info";
const STATUS = "https://raw.githubusercontent.com/sselimgenc-oss/sg-arge/copytrade-izleme/izleme/durum.json";
const CALLBACK = /^k\|([^|]+)\|([as])(?:\|([gbd]))?$/;

function json(data, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json; charset=utf-8" } });
}

function nowIso() { return new Date().toISOString(); }

async function retryFetch(url, init, fetcher = fetch) {
  let response = await fetcher(url, init);
  if (response.status === 429) {
    await new Promise(resolve => setTimeout(resolve, 1200));
    response = await fetcher(url, init);
  }
  return response;
}

async function telegram(env, method, body, fetcher = fetch) {
  const response = await fetcher(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`Telegram ${method} başarısız`);
  return response.json();
}

function number(value, digits = 2) {
  return new Intl.NumberFormat("tr-TR", { maximumFractionDigits: digits }).format(value);
}

// durum.json'daki traderlar[].tarz (v1.3): yalnız intraday ve swing etiketlenir
const STYLE_LABEL = { intraday: "[Intraday]", swing: "[Swing]" };

function nameWithStyle(trader) {
  const label = STYLE_LABEL[trader.tarz];
  return label ? `${trader.takma_ad} ${label}` : trader.takma_ad;
}

function formatEvent(event, trader) {
  if (event.tur === "isik") return `🔴 ${nameWithStyle(trader)} · sağlık ışığı kırmızı`;
  const icon = { acilis: "🟢", kapanis: "🔴", buyutme: "🔵" }[event.tur] || "⚪";
  const action = { acilis: "açtı", kapanis: "kapattı", buyutme: "büyüttü" }[event.tur];
  const pct = event.hesap_payi == null ? "" : ` · hesabın %${number(event.hesap_payi * 100, 1)}'i`;
  return `${icon} ${nameWithStyle(trader)} · ${event.coin} ${event.yon.toUpperCase()} ${action} · giriş ${number(event.fiyat)}${pct}`;
}

function callbackData(event, decision, reason) {
  const data = `k|${event.id}|${decision}${reason ? `|${reason}` : ""}`;
  return new TextEncoder().encode(data).byteLength <= 64 ? data : null;
}

function keyboard(event) {
  const open = callbackData(event, "a");
  const skip = callbackData(event, "s");
  return open && skip ? { inline_keyboard: [[{ text: "Açtım", callback_data: open }, { text: "Atladım", callback_data: skip }]] } : undefined;
}

function skipKeyboard(event) {
  const items = [["Geç gördüm", "g"], ["Beğenmedim", "b"], ["Diğer", "d"]]
    .map(([text, code]) => ({ text, callback_data: callbackData(event, "s", code) })).filter(item => item.callback_data);
  return { inline_keyboard: [items] };
}

function decision(data) {
  const found = CALLBACK.exec(data || "");
  if (!found) return null;
  const [, olay_id, raw, code] = found;
  if (raw === "a" && !code) return { olay_id, karar: "acti", neden: "diger" };
  if (raw === "s" && !code) return { olay_id, menu: true };
  const map = { g: "gec_gordum", b: "begenmedim", d: "diger" };
  return raw === "s" && map[code] ? { olay_id, karar: "atladi", neden: map[code] } : null;
}

async function currentStatus(fetcher = fetch) {
  const response = await fetcher(STATUS, { headers: { "cache-control": "no-cache" } });
  if (!response.ok) throw new Error("durum.json okunamadı");
  return response.json();
}

async function fills(address, start, fetcher = fetch) {
  const response = await retryFetch(INFO, { method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ type: "userFillsByTime", user: address, startTime: start, endTime: Date.now() }) }, fetcher);
  if (!response.ok) throw new Error(`Hyperliquid ${response.status}`);
  const body = await response.json();
  if (!Array.isArray(body)) throw new Error("Geçersiz Hyperliquid dolum yanıtı");
  return body.filter(isPerp);
}

async function sendOnce(env, event, trader, fetcher = fetch) {
  const previous = await env.DB.prepare("SELECT olay_id FROM bildirilen WHERE olay_id = ?").bind(event.id).first();
  if (previous) return false;
  await telegram(env, "sendMessage", { chat_id: env.TELEGRAM_CHAT_ID, text: formatEvent(event, trader),
    reply_markup: ["acilis", "buyutme"].includes(event.tur) ? keyboard(event) : undefined }, fetcher);
  await env.DB.prepare("INSERT OR IGNORE INTO bildirilen(olay_id, zaman) VALUES (?, ?)")
    .bind(event.id, nowIso()).run();
  return true;
}

function mergeFills(previous, incoming) {
  const all = new Map((previous || []).map(fill => [String(fill.tid), fill]));
  for (const fill of incoming) all.set(String(fill.tid), fill);
  return [...all.values()].sort((a, b) => Number(a.time) - Number(b.time) || String(a.tid).localeCompare(String(b.tid)));
}

async function accumulatedOrderEvents(env, trader, rows, account) {
  const grouped = new Map();
  for (const row of rows) grouped.set(String(row.oid), [...(grouped.get(String(row.oid)) || []), row]);
  const events = [];
  for (const [oid, incoming] of grouped) {
    const saved = await env.DB.prepare("SELECT dolumlar FROM emirler WHERE trader = ? AND oid = ?").bind(trader, oid).first();
    const merged = mergeFills(saved ? JSON.parse(saved.dolumlar) : [], incoming);
    await env.DB.prepare("INSERT INTO emirler(trader, oid, dolumlar) VALUES (?, ?, ?) ON CONFLICT(trader, oid) DO UPDATE SET dolumlar=excluded.dolumlar")
      .bind(trader, oid, JSON.stringify(merged)).run();
    events.push(...orderEvents(trader, merged, account));
  }
  return events;
}

function isNotified(trader) { return trader.kol === "oda"; }

// Gerçek algılama gecikmesi (dk): bir dolumun gerçek zamanı ile Worker'ın şu an onu görmesi arasındaki fark.
// Pozisyon yaşıyla (copytrade.saglik_hatti) karıştırılmamalı — bu, Hyperliquid'den Worker'a kadar geçen gerçek süre.
function gecikmeDk(fillTimeMs, nowMs = Date.now()) { return (nowMs - fillTimeMs) / 60000; }

// BILDIRIM_KIPI: "ozet" (varsayılan) — yalnız günlük özet + durum değişince uyarı; "islem" — açılış/kapanış/büyütme
// bildirimleri de (eski davranış) açık. Kod silinmez, yalnız bu ayarla kapatılır/açılır (lider kararı, kullanıcı).
function bildirimKipi(env) { return env.BILDIRIM_KIPI === "islem" ? "islem" : "ozet"; }

async function runCron(env, fetcher = fetch) {
  let status;
  try { status = await currentStatus(fetcher); } catch { return; }
  // Bildirim yalnız kol = oda için; kontrol/taban/elle kolları sessiz izlenir (Worker onlar için Hyperliquid'e de gitmez).
  for (const trader of (status.traderlar || []).filter(isNotified)) {
    const stored = await env.DB.prepare("SELECT son_dolum FROM imlec WHERE trader = ?").bind(trader.id).first();
    if (!stored) {
      await env.DB.prepare("INSERT INTO imlec(trader, son_dolum) VALUES (?, ?)").bind(trader.id, Date.now()).run();
      continue;
    }
    try {
      const rows = await fills(trader.adres, Number(stored.son_dolum), fetcher);
      for (const event of await accumulatedOrderEvents(env, trader.id, rows, Number(trader.hesap_degeri))) {
        if (["acilis", "kapanis", "buyutme"].includes(event.tur) && bildirimKipi(env) === "islem") await sendOnce(env, event, trader, fetcher);
      }
      const newest = Math.max(Number(stored.son_dolum), ...rows.map(row => Number(row.time)));
      // Her dakika çalıştığı için yalnız değişince yazılır (D1 ücretsiz yazma kotası).
      if (newest !== Number(stored.son_dolum)) {
        await env.DB.prepare("UPDATE imlec SET son_dolum = ? WHERE trader = ?").bind(newest, trader.id).run();
        // E1 devamı (Sol denetimi 2026-10-30): gerçek algılama gecikmesi — trader'ın en yeni dolum zamanı ile
        // Worker'ın onu şu an görmesi arasındaki fark. Yalnız en son örnek tutulur.
        await env.DB.prepare("INSERT INTO son_gecikme(trader, gecikme_dk, zaman) VALUES (?, ?, ?) ON CONFLICT(trader) DO UPDATE SET gecikme_dk=excluded.gecikme_dk, zaman=excluded.zaman")
          .bind(trader.id, gecikmeDk(newest), nowIso()).run();
      }
    } catch { /* the cursor intentionally remains unchanged */ }
    const previous = await env.DB.prepare("SELECT isik FROM isik WHERE trader = ?").bind(trader.id).first();
    // The first observed colour is a baseline, not an alert. Alert only on a known non-red → red transition.
    if (previous && trader.saglik?.isik === "kirmizi" && previous.isik !== "kirmizi") {
      await sendOnce(env, { id: `${trader.id}-${status.uretildi}-isik`, tur: "isik", coin: "", yon: "", fiyat: null, hesap_payi: null }, trader, fetcher);
    }
    const current = trader.saglik?.isik || "yesil";
    if (previous?.isik !== current) {
      await env.DB.prepare("INSERT INTO isik(trader, isik) VALUES (?, ?) ON CONFLICT(trader) DO UPDATE SET isik=excluded.isik")
        .bind(trader.id, current).run();
    }
  }
  await checkStateAlerts(env, status, fetcher);
}

async function handleTelegram(request, env, fetcher = fetch) {
  if (request.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.TELEGRAM_WEBHOOK_SECRET) return new Response("forbidden", { status: 403 });
  const update = await request.json();
  const callback = update.callback_query;
  if (callback) {
    if (String(callback.from?.id) !== String(env.TELEGRAM_CHAT_ID) || String(callback.message?.chat?.id) !== String(env.TELEGRAM_CHAT_ID)) return new Response("ok");
    await telegram(env, "answerCallbackQuery", { callback_query_id: callback.id }, fetcher);
    const value = decision(callback.data);
    if (!value) return new Response("ok");
    if (value.menu) {
      await telegram(env, "editMessageReplyMarkup", { chat_id: callback.message.chat.id, message_id: callback.message.message_id,
        reply_markup: skipKeyboard({ id: value.olay_id }) }, fetcher);
      return new Response("ok");
    }
    await env.DB.prepare("INSERT INTO kararlar(olay_id, zaman, karar, neden, etiket) VALUES (?, ?, ?, ?, '') ON CONFLICT(olay_id) DO UPDATE SET zaman=excluded.zaman, karar=excluded.karar, neden=excluded.neden, etiket=''")
      .bind(value.olay_id, nowIso(), value.karar, value.neden).run();
    const label = value.karar === "acti" ? "✅ Açtım" : `⏭ Atladım — ${value.neden.replaceAll("_", " ")}`;
    await telegram(env, "editMessageReplyMarkup", { chat_id: callback.message.chat.id, message_id: callback.message.message_id,
      reply_markup: { inline_keyboard: [] } }, fetcher);
    await telegram(env, "editMessageText", { chat_id: callback.message.chat.id, message_id: callback.message.message_id,
      text: `${callback.message.text}\n${label}` }, fetcher);
    return new Response("ok");
  }
  const message = update.message;
  if (String(message?.chat?.id) !== String(env.TELEGRAM_CHAT_ID) || message?.text !== "/durum") return new Response("ok");
  let status;
  try { status = await currentStatus(fetcher); } catch { return new Response("ok"); }
  await telegram(env, "sendMessage", { chat_id: env.TELEGRAM_CHAT_ID, text: formatStatus(status), disable_web_page_preview: true }, fetcher);
  return new Response("ok");
}

const ESKI_DK = 90;
const LIGHT = { yesil: "🟢", sari: "🟡", kirmizi: "🔴" };
const VERI_UYARI_DK = 180;   // günlük uyarı eşiği: 3 saat (ayrı: /durum'un kendi 90 dk eşiğinden farklı, bilgi amaçlı)

// Güncel motor (sanal_kopya_v3 — sabit tutar + çıkış kuralları + tasfiye); v1 (sanal_kopya) silinmez/değişmez
// ama bu özetin kaynağı artık o değil (kullanıcı kararı 2026-10-30). v3 hesaplanamamış ("durum":"hesaplanamadi")
// bir trader ortalamaya 0 olarak girmesin diye dışarıda bırakılır (yalnız gerçek getiri değeri varsa sayılır).
function sanalKohort(all, kol) {
  return all.filter(t => (t.kollar || [t.kol]).includes(kol)).map(t => t.sanal_kopya_v3).filter(c => c && typeof c.getiri === "number");
}
function ortalamaGetiri(copies) {
  return copies.length ? copies.reduce((sum, c) => sum + (Number(c.getiri) || 0), 0) / copies.length : null;
}
function yuzdeYaz(v) { return v == null ? "bilinmiyor" : `${v >= 0 ? "+" : ""}${(v * 100).toLocaleString("tr-TR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`; }

// Günde bir, 09:00 TR'de (06:00 UTC): sanal kopya ölçeğinde oda kasası/getiri, oda−kontrol farkı (aynı dönem,
// her ikisi de sanal_kopya_v3.getiri ortalaması), son 24 saatteki işlem sayısı ve trader sayısı, ışıklar, veri yaşı.
function dailySummaryText(status, nowMs = Date.now()) {
  const all = status.traderlar || [];
  const room = all.filter(isNotified);
  const odaKopya = sanalKohort(all, "oda"), kontrolKopya = sanalKohort(all, "kontrol");
  const kasa = odaKopya.reduce((sum, c) => sum + (Number(c.bakiye_usd) || 0), 0);
  const odaGetiri = ortalamaGetiri(odaKopya), kontrolGetiri = ortalamaGetiri(kontrolKopya);
  const fark = odaGetiri != null && kontrolGetiri != null ? odaGetiri - kontrolGetiri : null;
  const sonGunOlaylari = (status.olaylar || []).filter(e => { const t = Date.parse(e.zaman); return Number.isFinite(t) && nowMs - t <= 86400000 && nowMs - t >= 0; });
  const odaIdleri = new Set(room.map(t => t.id));   // özet oda içindir; olaylar listesi tüm kolları taşır
  const islemOlaylari = sonGunOlaylari.filter(e => ["acilis", "kapanis", "buyutme"].includes(e.tur) && odaIdleri.has(e.trader));
  const age = Math.max(0, Math.floor((nowMs - Date.parse(status.uretildi)) / 60000));
  const count = c => room.filter(t => (t.saglik?.isik || "yesil") === c).length;
  return [
    "📊 SG Arge · Günlük özet",
    "",
    `💰 Oda kasası (sanal): $${kasa.toLocaleString("tr-TR", { maximumFractionDigits: 0 })} (${yuzdeYaz(odaGetiri)})`,
    `📐 Oda − Kontrol farkı (aynı dönem, sanal kopya): ${fark == null ? "bilinmiyor" : yuzdeYaz(fark)}`,
    `🔁 Son 24 saat: ${islemOlaylari.length} işlem · ${new Set(islemOlaylari.map(e => e.trader)).size} trader`,
    `🟢 ${count("yesil")}   🟡 ${count("sari")}   🔴 ${count("kirmizi")}`,
    age > ESKI_DK ? `⚠️ Veri ${age} dk önce — güncellenmedi` : `🕐 Veri ${age} dk önce`,
    "",
  ].join("\n");
}

async function uyariDurumGetir(env, anahtar) {
  const row = await env.DB.prepare("SELECT deger FROM uyari_durum WHERE anahtar = ?").bind(anahtar).first();
  return row ? row.deger : null;
}
async function uyariDurumYaz(env, anahtar, deger) {
  await env.DB.prepare("INSERT INTO uyari_durum(anahtar, deger) VALUES (?, ?) ON CONFLICT(anahtar) DO UPDATE SET deger=excluded.deger").bind(anahtar, deger).run();
}

// Yalnız durum DEĞİŞİNCE gönderir (uyari_durum'da son bilinen durum tutulur) — aynı uyarı tekrarlanmaz.
async function checkStateAlerts(env, status, fetcher = fetch) {
  const nowMs = Date.now(), age = (nowMs - Date.parse(status.uretildi)) / 60000;
  const eski = Number.isFinite(age) && age > VERI_UYARI_DK, yasDurum = eski ? "eski" : "taze";
  const oncekiYas = await uyariDurumGetir(env, "veri_yas");
  if (eski && oncekiYas !== "eski") {
    await telegram(env, "sendMessage", { chat_id: env.TELEGRAM_CHAT_ID, text: `⚠️ Veri ${Math.round(age)} dk önce üretildi — 3 saatten eski.` }, fetcher);
  }
  if (oncekiYas !== yasDurum) await uyariDurumYaz(env, "veri_yas", yasDurum);

  const kalabalikAcik = !!status.kalabalik?.uyari, kalabalikDurum = kalabalikAcik ? "acik" : "kapali";
  const oncekiKalabalik = await uyariDurumGetir(env, "kalabalik");
  if (kalabalikAcik && oncekiKalabalik !== "acik") {
    await telegram(env, "sendMessage", { chat_id: env.TELEGRAM_CHAT_ID, text: `⚠️ Kalabalık uyarısı başladı: ${status.kalabalik.uyari_metni || "ayrıntı yok"}` }, fetcher);
  }
  if (oncekiKalabalik !== kalabalikDurum) await uyariDurumYaz(env, "kalabalik", kalabalikDurum);

  // yeşil/sarıdan kırmızıya geçişte uyarır; aynı kırmızı durumda tekrarlanmaz (diğer durum uyarılarıyla aynı desen).
  const hatIsik = status.saglik_hatti?.isik;
  if (hatIsik) {
    const oncekiHat = await uyariDurumGetir(env, "saglik_hatti");
    if (hatIsik === "kirmizi" && oncekiHat !== "kirmizi") {
      const nedenler = (status.saglik_hatti.nedenler || []).join(", ") || "ayrıntı yok";
      await telegram(env, "sendMessage", { chat_id: env.TELEGRAM_CHAT_ID, text: `⚠️ Veri hattı sağlığı kırmızı: ${nedenler}` }, fetcher);
    }
    if (oncekiHat !== hatIsik) await uyariDurumYaz(env, "saglik_hatti", hatIsik);
  }
}

// Günde yalnız bir kez (09:00 TR = 06:00 UTC); D1'de o günün TR tarihi işaretlenir ki dakikada bir çalışan
// cron'da yanlışlıkla ikinci kez gönderilmesin.
async function sendDailySummaryIfDue(env, fetcher = fetch, nowMs = Date.now()) {
  const d = new Date(nowMs);
  if (d.getUTCHours() !== 6 || d.getUTCMinutes() !== 0) return;
  const gun = d.toISOString().slice(0, 10);
  const var_ = await env.DB.prepare("SELECT gun FROM ozet_gonderildi WHERE gun = ?").bind(gun).first();
  if (var_) return;
  let status;
  try { status = await currentStatus(fetcher); } catch { return; }
  await telegram(env, "sendMessage", { chat_id: env.TELEGRAM_CHAT_ID, text: dailySummaryText(status, nowMs), disable_web_page_preview: true }, fetcher);
  await env.DB.prepare("INSERT OR IGNORE INTO ozet_gonderildi(gun) VALUES (?)").bind(gun).run();
}

// Oda risk bayrakları (GOREV_ODA_RISK): yalnız uyarı varsa tek satır; bilgi amaçlı, otomasyon yok.
function riskLine(status, room) {
  const parts = [];
  if (status.kalabalik?.uyari && status.kalabalik.uyari_metni) parts.push(status.kalabalik.uyari_metni);
  const flagged = room.filter(t => t.yonsuz_bayrak?.bayrak).map(t => t.takma_ad);
  if (flagged.length) parts.push(`yönsüz bayrak: ${flagged.slice(0, 3).join(", ")}${flagged.length > 3 ? ` +${flagged.length - 3}` : ""}`);
  return parts.length ? `⚠️ ${parts.join(" · ")}` : "";
}

// /durum: yalnız oda (bildirimli kol) ayrıntılı; diğer kollar sayı.
function formatStatus(status, nowMs = Date.now()) {
  const all = status.traderlar || [];
  const hasArms = all.some(t => t.kol);
  const room = hasArms ? all.filter(isNotified) : all;
  const age = Math.max(0, Math.floor((nowMs - Date.parse(status.uretildi)) / 60000));
  const lines = [];
  const starts = room.map(t => Date.parse(t.t0)).filter(Number.isFinite);
  const week = starts.length ? Math.min(12, Math.floor((nowMs - Math.min(...starts)) / (7 * 86400000)) + 1) : null;
  lines.push(`📊 SG Arge · Pilot${week ? ` · hafta ${week}/12` : ""}`);
  lines.push(age > ESKI_DK ? `⚠️ Veri ${age} dk önce — güncellenmedi` : `🕐 Veri ${age} dk önce`);
  lines.push("");
  const count = c => room.filter(t => (t.saglik?.isik || "yesil") === c).length;
  const open = room.reduce((sum, t) => sum + (t.pozisyonlar || []).length, 0);
  lines.push(`${hasArms ? "Oda" : "İzlenen"} · ${room.length} trader`);
  lines.push(`🟢 ${count("yesil")}   🟡 ${count("sari")}   🔴 ${count("kirmizi")}`);
  lines.push(`📂 Açık pozisyon: ${open}`);
  for (const [colour, title] of [["kirmizi", "🔴 Dikkat"], ["sari", "🟡 İzle"]]) {
    const rows = room.filter(t => t.saglik?.isik === colour);
    if (!rows.length) continue;
    lines.push("", title);
    for (const t of rows.slice(0, 5)) lines.push(`• ${t.takma_ad} · ${(t.saglik.nedenler || []).join(", ") || LIGHT[colour]}`);
    if (rows.length > 5) lines.push(`• +${rows.length - 5} trader daha`);
  }
  const risk = riskLine(status, room);
  if (risk) lines.push("", risk);
  lines.push("");
  if (hasArms) lines.push(`👀 Sessiz izleme: ${all.length - room.length} trader (kontrol, taban, elle)`);
  return lines.join("\n");
}

export default {
  scheduled(event, env, ctx) { ctx.waitUntil(runCron(env)); ctx.waitUntil(sendDailySummaryIfDue(env)); },
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/kararlar") {
      const rows = await env.DB.prepare("SELECT olay_id, substr(zaman, 1, 10) AS zaman, karar, CASE WHEN neden = 'bakiye_yok' THEN 'diger' ELSE neden END AS neden, etiket AS \"not\" FROM kararlar ORDER BY zaman").all();
      return json(rows.results || []);
    }
    if (request.method === "GET" && url.pathname === "/gecikme") {
      const rows = await env.DB.prepare("SELECT trader, gecikme_dk, zaman FROM son_gecikme ORDER BY trader").all();
      return json(rows.results || []);
    }
    if (request.method === "POST" && url.pathname === "/telegram") return handleTelegram(request, env);
    return new Response("not found", { status: 404 });
  },
};

export { accumulatedOrderEvents, bildirimKipi, callbackData, checkStateAlerts, dailySummaryText, decision, formatEvent, formatStatus, gecikmeDk, handleTelegram, isNotified, mergeFills, runCron, sendDailySummaryIfDue, sendOnce };
