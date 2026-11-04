import assert from "node:assert/strict";
import test from "node:test";
import fixture from "../../tests/fixtures/olaylar.json" with { type: "json" };
import { accumulatedOrderEvents, callbackData, decision, formatEvent, formatStatus, handleTelegram, mergeFills, runCron, sendOnce } from "../src/index.js";
import { orderEvents } from "../src/events.js";

test("ortak oid fixture Python ile aynı olayları üretir", () => {
  const actual = orderEvents(fixture.trader, fixture.fills, fixture.account)
    .map(({ id, tur, coin, yon }) => ({ id, tur, coin, yon }));
  assert.deepEqual(actual, fixture.expected);
});

test("callback en çok 64 bayt ve yalnız geçerli kararlar", () => {
  const data = callbackData({ id: "T1-123-acilis" }, "s", "g");
  assert.ok(new TextEncoder().encode(data).byteLength <= 64);
  assert.deepEqual(decision(data), { olay_id: "T1-123-acilis", karar: "atladi", neden: "gec_gordum" });
  assert.deepEqual(decision("k|T1-123-acilis|s"), { olay_id: "T1-123-acilis", menu: true });
  assert.equal(decision("k|T1-123-acilis|s|v"), null);
  assert.equal(decision("bad"), null);
});

test("geçersiz webhook gizli başlığı D1 veya Telegram'a dokunmaz", async () => {
  const response = await handleTelegram(new Request("https://worker/telegram", { method: "POST", headers: { "content-type": "application/json" }, body: "{}" }),
    { TELEGRAM_WEBHOOK_SECRET: "beklenen" }, () => { throw new Error("çağrılmamalı"); });
  assert.equal(response.status, 403);
});

test("ilk cron imleci şimdiye koyar, geçmiş bildirimi göndermez", async () => {
  const writes = [];
  const env = { DB: { prepare(sql) { return { bind(...args) { return {
    first: async () => undefined,
    run: async () => { writes.push([sql, args]); return { meta: { changes: 1 } }; },
  }; } }; } } };
  const fetcher = async () => new Response(JSON.stringify({ uretildi: new Date().toISOString(), traderlar: [{ id: "T1", kol: "oda", adres: "0x1", takma_ad: "Test", hesap_degeri: 1000, pozisyonlar: [], saglik: { isik: "yesil" } }] }));
  await runCron(env, fetcher);
  // imlec yazısına ek olarak durum uyarısının (veri yaşı) ilk kez görülen taban durumu da D1'e yazılır
  // (bildirim DEĞİL — yalnız sonraki karşılaştırma için; bkz. "yalnız durum değişince uyarı" testleri aşağıda).
  assert.equal(writes.filter(([sql]) => /INSERT INTO imlec/.test(sql)).length, 1);
  assert.equal(writes.filter(([sql]) => /INSERT INTO uyari_durum/.test(sql)).length, 1);   // T1: kalabalık uyarısı kalktı (2 → 1)
});

test("ilk görülen kırmızı ışık bildirim üretmez; yeşilden kırmızıya geçiş üretir", async () => {
  const lights = new Map(), notified = new Set(), sent = [];
  const env = { TELEGRAM_BOT_TOKEN: "x", TELEGRAM_CHAT_ID: "1", DB: { prepare(sql) { return { bind(...args) { return {
    first: async () => /FROM imlec/.test(sql) ? { son_dolum: 0 } : /FROM isik/.test(sql) ? (lights.has(args[0]) ? { isik: lights.get(args[0]) } : undefined) : /FROM bildirilen/.test(sql) ? (notified.has(args[0]) ? { olay_id: args[0] } : undefined) : undefined,
    run: async () => { if (/INSERT INTO isik/.test(sql)) lights.set(args[0], args[1]); if (/INSERT OR IGNORE INTO bildirilen/.test(sql)) notified.add(args[0]); return { meta: { changes: 1 } }; },
  }; } }; } } };
  let colour = "kirmizi", n = 0;
  const fetcher = async (url, init) => {
    // uretildi her çağrıda biraz ileri (yalnız olay id'si farklı olsun diye); "şimdi"ye yakın kalır ki veri yaşı
    // uyarısı (checkStateAlerts) bu testte yanlışlıkla tetiklenmesin.
    if (String(url).includes("durum.json")) return new Response(JSON.stringify({ uretildi: new Date(Date.now() + n++).toISOString(), traderlar: [{ id: "T1", kol: "oda", adres: "0x1", takma_ad: "Test", hesap_degeri: 1000, saglik: { isik: colour } }] }));
    if (String(url).includes("api.hyperliquid.xyz")) return new Response(JSON.stringify([]));
    sent.push(JSON.parse(init.body)); return new Response(JSON.stringify({ ok: true }));
  };
  await runCron(env, fetcher);
  assert.equal(lights.get("T1"), "kirmizi");
  assert.equal(sent.length, 0);
  colour = "yesil"; await runCron(env, fetcher);
  colour = "kirmizi"; await runCron(env, fetcher);
  assert.equal(sent.length, 1);
  assert.match(sent[0].text, /sağlık ışığı kırmızı/);
});

test("ilk Telegram ağ hatası sonraki cron denemesinde gönderilir, başarılı olay yinelenmez", async () => {
  const sent = new Set(); let attempts = 0;
  const env = { TELEGRAM_CHAT_ID: "1", TELEGRAM_BOT_TOKEN: "x", DB: { prepare(sql) { return { bind(...args) { return {
    first: async () => sent.has(args[0]) ? { olay_id: args[0] } : undefined,
    run: async () => { if (/INSERT OR IGNORE INTO bildirilen/.test(sql)) sent.add(args[0]); return { meta: { changes: 1 } }; },
  }; } }; } } };
  const event = { id: "T1-1-acilis", tur: "acilis", coin: "BTC", yon: "long", fiyat: 1, hesap_payi: 0 };
  await assert.rejects(sendOnce(env, event, { takma_ad: "Test" }, async () => { attempts += 1; throw new Error("ağ"); }));
  assert.equal(sent.size, 0);
  assert.equal(await sendOnce(env, event, { takma_ad: "Test" }, async () => { attempts += 1; return new Response(JSON.stringify({ ok: true })); }), true);
  assert.equal(await sendOnce(env, event, { takma_ad: "Test" }, async () => { attempts += 1; return new Response(JSON.stringify({ ok: true })); }), false);
  assert.equal(attempts, 2);
});

test("Atladım neden menüsü açılır, neden kaydolur ve yeniden basma aynı kaydı günceller", async () => {
  const writes = [], methods = [];
  const env = { TELEGRAM_CHAT_ID: "1", TELEGRAM_BOT_TOKEN: "x", TELEGRAM_WEBHOOK_SECRET: "secret", DB: { prepare(sql) { return { bind(...args) { return {
    run: async () => { writes.push([sql, args]); return { meta: { changes: 1 } }; },
  }; } }; } } };
  const update = (data) => new Request("https://worker/telegram", { method: "POST", headers: { "X-Telegram-Bot-Api-Secret-Token": "secret" }, body: JSON.stringify({ callback_query: { id: "q", data, from: { id: "1" }, message: { chat: { id: "1" }, message_id: 2, text: "olay" } } }) });
  const fetcher = async (url) => { methods.push(String(url).split("/").at(-1)); return new Response(JSON.stringify({ ok: true })); };
  await handleTelegram(update("k|T1-1-acilis|s"), env, fetcher);
  assert.deepEqual(methods, ["answerCallbackQuery", "editMessageReplyMarkup"]);
  assert.equal(writes.length, 0);
  await handleTelegram(update("k|T1-1-acilis|s|g"), env, fetcher);
  await handleTelegram(update("k|T1-1-acilis|s|g"), env, fetcher);
  assert.equal(writes.filter(([sql]) => /INSERT INTO kararlar/.test(sql)).length, 2);
  assert.ok(methods.includes("editMessageText"));
});

test("sorgulara bölünen oid, D1 birikiminden sonra motorla aynı olayı verir", async () => {
  const orders = new Map();
  const env = { DB: { prepare(sql) { return { bind(...args) { return {
    first: async () => orders.has(`${args[0]}:${args[1]}`) ? { dolumlar: orders.get(`${args[0]}:${args[1]}`) } : undefined,
    run: async () => { orders.set(`${args[0]}:${args[1]}`, args[2]); return { meta: { changes: 1 } }; },
  }; } }; } } };
  const first = { coin: "BTC", side: "B", sz: "1", px: "100", time: 1, oid: 7, tid: 1, startPosition: "0" };
  const second = { coin: "BTC", side: "B", sz: "1", px: "110", time: 2, oid: 7, tid: 2, startPosition: "1" };
  await accumulatedOrderEvents(env, "T1", [first], 1000);
  const actual = await accumulatedOrderEvents(env, "T1", [second], 1000);
  assert.deepEqual(actual, orderEvents("T1", mergeFills([first], [second]), 1000));
  assert.equal(actual[0].hesap_payi, .21);
});

test("mesaja tarz etiketi: [Intraday] / [Swing]; tarz yoksa etiket yok", () => {
  const event = { id: "T1-1-acilis", tur: "acilis", coin: "BTC", yon: "long", fiyat: 68400, hesap_payi: 0.08 };
  assert.match(formatEvent(event, { takma_ad: "Trader-1", tarz: "intraday" }), /^🟢 Trader-1 \[Intraday\] · BTC LONG açtı/);
  assert.match(formatEvent(event, { takma_ad: "Trader-2", tarz: "swing" }), /^🟢 Trader-2 \[Swing\] · BTC LONG açtı/);
  assert.doesNotMatch(formatEvent(event, { takma_ad: "Trader-3" }), /\[/);
  assert.doesNotMatch(formatEvent(event, { takma_ad: "Trader-4", tarz: "bilinmiyor" }), /\[/);
  assert.equal(formatEvent({ tur: "isik" }, { takma_ad: "Trader-1", tarz: "swing" }), "🔴 Trader-1 [Swing] · sağlık ışığı kırmızı");
});

test("tarz durum.json'dan okunur: cron mesajı etiketli gider", async () => {
  const sent = [];
  const env = { TELEGRAM_BOT_TOKEN: "x", TELEGRAM_CHAT_ID: "1", BILDIRIM_KIPI: "islem", DB: { prepare(sql) { return { bind(...args) { return {
    first: async () => (/FROM imlec/.test(sql) ? { son_dolum: 0 } : undefined),
    run: async () => ({ meta: { changes: 1 } }),
  }; } }; } } };
  const fill = { coin: "BTC", side: "B", sz: "1", px: "100", time: 5, oid: 7, tid: 1, startPosition: "0" };
  const fetcher = async (url, init) => {
    if (String(url).includes("durum.json")) return new Response(JSON.stringify({ uretildi: new Date().toISOString(), traderlar: [{ id: "T1", kol: "oda", adres: "0x1", takma_ad: "Test", tarz: "swing", hesap_degeri: 1000, pozisyonlar: [], saglik: { isik: "yesil" } }] }));
    if (String(url).includes("api.hyperliquid.xyz")) return new Response(JSON.stringify([fill]));
    sent.push(JSON.parse(init.body).text);
    return new Response(JSON.stringify({ ok: true }));
  };
  await runCron(env, fetcher);
  assert.equal(sent.length, 1);
  assert.match(sent[0], /Test \[Swing\] · BTC LONG açtı/);
});

test("bildirim yalnız kol = oda için: kontrol, taban, elle ve kolsuz trader sessiz", async () => {
  const fill = { coin: "BTC", side: "B", sz: "1", px: "100", time: 5, oid: 7, tid: 1, startPosition: "0" };
  const run = async kol => {
    const sent = [], hyperliquid = [];
    const env = { TELEGRAM_BOT_TOKEN: "x", TELEGRAM_CHAT_ID: "1", BILDIRIM_KIPI: "islem", DB: { prepare(sql) { return { bind() { return {
      first: async () => (/FROM imlec/.test(sql) ? { son_dolum: 0 } : undefined),
      run: async () => ({ meta: { changes: 1 } }),
    }; } }; } } };
    const fetcher = async (url, init) => {
      if (String(url).includes("durum.json")) return new Response(JSON.stringify({ uretildi: new Date().toISOString(), traderlar: [{ id: "T1", ...(kol ? { kol } : {}), adres: "0x1", takma_ad: "Test", hesap_degeri: 1000, pozisyonlar: [], saglik: { isik: "yesil" } }] }));
      if (String(url).includes("api.hyperliquid.xyz")) { hyperliquid.push(1); return new Response(JSON.stringify([fill])); }
      sent.push(JSON.parse(init.body).text);
      return new Response(JSON.stringify({ ok: true }));
    };
    await runCron(env, fetcher);
    return { sent: sent.length, hyperliquid: hyperliquid.length };
  };
  assert.deepEqual(await run("oda"), { sent: 1, hyperliquid: 1 });
  for (const kol of ["kontrol", "taban", "elle", undefined]) assert.deepEqual(await run(kol), { sent: 0, hyperliquid: 0 }, String(kol));
});

test("/durum: oda özeti, eski veri uyarısı, dikkat listesi; kâr/zarar yok", () => {
  const now = Date.parse("2026-10-30T12:00:00Z");
  const t = (id, kol, isik, nedenler, poz = 0) => ({ id, kol, takma_ad: id, t0: "2026-10-29", pozisyonlar: Array(poz).fill({}), saglik: { isik, nedenler } });
  const status = { uretildi: "2026-10-30T06:00:00Z", traderlar: [
    t("a1", "oda", "yesil", ["kaldıraç normal"], 2), t("b2", "oda", "kirmizi", ["gerçek kaldıraç > 10x"], 1),
    t("c3", "oda", "sari", ["gerçek kaldıraç 3–10x"]), t("k1", "kontrol", "kirmizi", ["x"]), t("e1", "elle", "yesil", []),
  ] };
  const text = formatStatus(status, now);
  assert.match(text, /hafta 1\/12/);
  assert.match(text, /⚠️ Veri 360 dk önce — güncellenmedi/);
  assert.match(text, /Oda · 3 trader/);
  assert.match(text, /🟢 1 {3}🟡 1 {3}🔴 1/);
  assert.match(text, /Açık pozisyon: 3/);
  assert.match(text, /🔴 Dikkat\n• b2 · gerçek kaldıraç > 10x/);
  assert.match(text, /Sessiz izleme: 2 trader/);
  assert.doesNotMatch(text, /k1/);
  
});

test("/durum: kol alanı yoksa tüm liste 'İzlenen' sayılır, taze veri uyarısız", () => {
  const status = { uretildi: "2026-10-30T11:50:00Z", traderlar: [{ takma_ad: "x", pozisyonlar: [], saglik: { isik: "yesil" } }] };
  const text = formatStatus(status, Date.parse("2026-10-30T12:00:00Z"));
  assert.match(text, /🕐 Veri 10 dk önce/);
  assert.match(text, /İzlenen · 1 trader/);
  assert.doesNotMatch(text, /Sessiz izleme/);
});
