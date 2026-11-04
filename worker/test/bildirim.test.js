import assert from "node:assert/strict";
import test from "node:test";
import { bildirimKipi, checkStateAlerts, dailySummaryText, runCron, sendDailySummaryIfDue } from "../src/index.js";

function d1Mock(durumlar = {}) {
  const writes = [];
  return {
    writes,
    DB: {
      prepare(sql) {
        return {
          bind(...args) {
            return {
              first: async () => {
                if (/FROM imlec/.test(sql)) return { son_dolum: 0 };
                if (/FROM uyari_durum/.test(sql)) return args[0] in durumlar ? { deger: durumlar[args[0]] } : undefined;
                if (/FROM ozet_gonderildi/.test(sql)) return durumlar.gonderilenGunler?.has(args[0]) ? { gun: args[0] } : undefined;
                return undefined;
              },
              run: async () => { writes.push([sql, args]); if (/INSERT INTO uyari_durum/.test(sql)) durumlar[args[0]] = args[1]; if (/INSERT OR IGNORE INTO ozet_gonderildi/.test(sql)) durumlar.gonderilenGunler?.add(args[0]); return { meta: { changes: 1 } }; },
            };
          },
        };
      },
    },
  };
}

test("bildirimKipi: varsayılan 'ozet'; yalnız tam olarak 'islem' ise açık", () => {
  assert.equal(bildirimKipi({}), "ozet");
  assert.equal(bildirimKipi({ BILDIRIM_KIPI: "ozet" }), "ozet");
  assert.equal(bildirimKipi({ BILDIRIM_KIPI: "baska" }), "ozet");
  assert.equal(bildirimKipi({ BILDIRIM_KIPI: "islem" }), "islem");
});

test("varsayılan kipte (ozet) açılış/kapanış Telegram'a gitmez, ama kırmızı ışık uyarısı yine gider", async () => {
  const mock = d1Mock();
  const fill = { coin: "BTC", side: "B", sz: "1", px: "100", time: 5, oid: 7, tid: 1, startPosition: "0" };
  const sent = [];
  const fetcher = async (url, init) => {
    if (String(url).includes("durum.json")) return new Response(JSON.stringify({ uretildi: new Date().toISOString(), traderlar: [{ id: "T1", kol: "oda", adres: "0x1", takma_ad: "Test", hesap_degeri: 1000, pozisyonlar: [], saglik: { isik: "kirmizi" } }] }));
    if (String(url).includes("api.hyperliquid.xyz")) return new Response(JSON.stringify([fill]));
    sent.push(JSON.parse(init.body).text); return new Response(JSON.stringify({ ok: true }));
  };
  const env = { TELEGRAM_BOT_TOKEN: "x", TELEGRAM_CHAT_ID: "1", DB: mock.DB };   // BILDIRIM_KIPI yok → varsayılan "ozet"
  await runCron(env, fetcher);   // ilk koşu: kırmızı ışık ilk kez görülüyor — taban, bildirim yok
  assert.equal(sent.length, 0);
  await runCron(env, fetcher);   // ikinci koşu: hâlâ kırmızı, yeni geçiş yok
  assert.equal(sent.filter(t => /açtı/.test(t)).length, 0, "açılış bildirimi kipi kapalıyken hiç gitmemeli");
});

test("dailySummaryText: sanal kopya ölçeğinde oda kasası/getiri, oda−kontrol farkı, 24 saatlik işlem (altın örnek)", () => {
  const now = Date.parse("2026-10-30T06:00:00Z");
  const t = (id, kol, bakiye, baslangic, getiri, isik = "yesil") => ({ id, kol, kollar: [kol], takma_ad: id, saglik: { isik }, sanal_kopya_v3: { bakiye_usd: bakiye, baslangic_usd: baslangic, getiri } });
  const status = {
    uretildi: "2026-10-30T05:50:00Z",   // 10 dk önce
    traderlar: [
      t("O1", "oda", 1100, 1000, 0.10, "yesil"), t("O2", "oda", 900, 1000, -0.10, "kirmizi"), t("O3", "oda", 1000, 1000, 0, "sari"),
      t("K1", "kontrol", 1050, 1000, 0.05), t("K2", "kontrol", 950, 1000, -0.05),
    ],
    olaylar: [
      { trader: "O1", coin: "BTC", tur: "acilis", zaman: new Date(now - 3600000).toISOString() },
      { trader: "O2", coin: "ETH", tur: "kapanis", zaman: new Date(now - 7200000).toISOString() },
      { trader: "O1", coin: "SOL", tur: "acilis", zaman: new Date(now - 48 * 3600000).toISOString() },   // 48 sa önce, sayılmaz
    ],
  };
  const text = dailySummaryText(status, now);
  // oda kasası = 1100+900+1000 = 3000; getiri ortalaması (10%,-10%,0%)/3 = 0 → "+0,0%"
  assert.match(text, /Oda kasası \(sanal\): \$3\.000 \(\+0,0%\)/);
  // oda−kontrol farkı: oda ort 0%, kontrol ort (5%,-5%)/2=0% → fark 0,0%
  assert.match(text, /Oda − Kontrol farkı.*\+0,0%/);
  // son 24 saat: 2 işlem (3. olay 48 saat önce, dışarıda), 2 farklı trader
  assert.match(text, /Son 24 saat: 2 işlem · 2 trader/);
  assert.match(text, /🟢 1 {3}🟡 1 {3}🔴 1/);
  assert.match(text, /Veri 10 dk önce/);
});

test("dailySummaryText: v3 hesaplanamamış trader ortalamaya 0 olarak girmez (dışarıda bırakılır)", () => {
  const now = Date.parse("2026-10-30T06:00:00Z");
  const t = (id, kol, bakiye, baslangic, getiri) => ({ id, kol, kollar: [kol], takma_ad: id, saglik: { isik: "yesil" }, sanal_kopya_v3: { bakiye_usd: bakiye, baslangic_usd: baslangic, getiri } });
  const status = {
    uretildi: "2026-10-30T05:50:00Z",
    traderlar: [
      t("O1", "oda", 1100, 1000, 0.10),
      { id: "O2", kol: "oda", kollar: ["oda"], takma_ad: "O2", saglik: { isik: "sari" }, sanal_kopya_v3: { surum: "v3", durum: "hesaplanamadi", yer_tutucu: true, neden: "hiç okunmadı" } },
    ],
    olaylar: [],
  };
  const text = dailySummaryText(status, now);
  // yalnız O1 sayılır (bakiye 1.100, getiri +10%); O2 hesaplanamadığı için ne kasaya ne ortalamaya 0 olarak girer
  assert.match(text, /Oda kasası \(sanal\): \$1\.100 \(\+10,0%\)/);
});

test("checkStateAlerts: veri 3 saatten eskiyse uyarı gider, aynı durumda tekrarlanmaz", async () => {
  const mock = d1Mock();
  const sent = [];
  const fetcher = async (url, init) => { sent.push(JSON.parse(init.body).text); return new Response(JSON.stringify({ ok: true })); };
  const env = { TELEGRAM_BOT_TOKEN: "x", TELEGRAM_CHAT_ID: "1", DB: mock.DB };
  const eskiStatus = { uretildi: new Date(Date.now() - 200 * 60000).toISOString() };   // 200 dk > 180 dk eşik
  await checkStateAlerts(env, eskiStatus, fetcher);
  assert.equal(sent.length, 1);
  assert.match(sent[0], /3 saatten eski/);
  await checkStateAlerts(env, eskiStatus, fetcher);   // hâlâ eski, aynı uyarı tekrarlanmaz
  assert.equal(sent.length, 1);
  const tazeStatus = { uretildi: new Date().toISOString() };
  await checkStateAlerts(env, tazeStatus, fetcher);   // tazeye döndü, uyarı yok (yalnız kötüye gidişte uyarır)
  assert.equal(sent.length, 1);
  await checkStateAlerts(env, eskiStatus, fetcher);   // tekrar eskidi → tekrar uyarır
  assert.equal(sent.length, 2);
});

test("checkStateAlerts: veri hattı sağlığı kırmızıya geçince uyarır, aynı kırmızıda tekrarlamaz", async () => {
  const mock = d1Mock();
  const sent = [];
  const fetcher = async (url, init) => { sent.push(JSON.parse(init.body).text); return new Response(JSON.stringify({ ok: true })); };
  const env = { TELEGRAM_BOT_TOKEN: "x", TELEGRAM_CHAT_ID: "1", DB: mock.DB };
  const yesil = { uretildi: new Date().toISOString(), saglik_hatti: { isik: "yesil", nedenler: [] } };
  const kirmizi = { uretildi: new Date().toISOString(), saglik_hatti: { isik: "kirmizi", nedenler: ["yetim gölge payı %17", "veri hatası payı %50"] } };
  await checkStateAlerts(env, yesil, fetcher);
  assert.equal(sent.length, 0);
  await checkStateAlerts(env, kirmizi, fetcher);
  assert.equal(sent.length, 1);
  assert.match(sent[0], /Veri hattı sağlığı kırmızı: yetim gölge payı %17, veri hatası payı %50/);
  await checkStateAlerts(env, kirmizi, fetcher);   // hâlâ kırmızı, tekrar uyarmaz
  assert.equal(sent.length, 1);
  await checkStateAlerts(env, yesil, fetcher);
  await checkStateAlerts(env, kirmizi, fetcher);   // yeniden kırmızıya döndü → yeniden uyarır
  assert.equal(sent.length, 2);
});

test("checkStateAlerts: saglik_hatti yoksa (eski veri) çökmez, uyarı göndermez", async () => {
  const mock = d1Mock();
  const sent = [];
  const fetcher = async (url, init) => { sent.push(JSON.parse(init.body).text); return new Response(JSON.stringify({ ok: true })); };
  const env = { TELEGRAM_BOT_TOKEN: "x", TELEGRAM_CHAT_ID: "1", DB: mock.DB };
  await checkStateAlerts(env, { uretildi: new Date().toISOString() }, fetcher);
  assert.equal(sent.length, 0);
});

test("sendDailySummaryIfDue: yalnız 06:00 UTC'de (09:00 TR) ve günde bir kez gönderir", async () => {
  const mock = d1Mock({ gonderilenGunler: new Set() });
  const sent = [];
  const fetcher = async (url, init) => {
    if (String(url).includes("durum.json")) return new Response(JSON.stringify({ uretildi: new Date().toISOString(), traderlar: [] }));
    sent.push(1); return new Response(JSON.stringify({ ok: true }));
  };
  const env = { TELEGRAM_BOT_TOKEN: "x", TELEGRAM_CHAT_ID: "1", DB: mock.DB };
  await sendDailySummaryIfDue(env, fetcher, Date.parse("2026-10-30T05:59:00Z"));
  assert.equal(sent.length, 0, "06:00 değilken gönderilmemeli");
  await sendDailySummaryIfDue(env, fetcher, Date.parse("2026-10-30T06:00:00Z"));
  assert.equal(sent.length, 1);
  await sendDailySummaryIfDue(env, fetcher, Date.parse("2026-10-30T06:00:30Z"));   // aynı dakika yine çağrılsa bile
  assert.equal(sent.length, 1, "aynı gün ikinci kez gönderilmemeli");
  await sendDailySummaryIfDue(env, fetcher, Date.parse("2026-10-31T06:00:00Z"));
  assert.equal(sent.length, 2, "ertesi gün yeniden gönderilmeli");
});

test("sendDailySummaryIfDue: durum.json okunamazsa sessizce atlar", async () => {
  const mock = d1Mock({ gonderilenGunler: new Set() });
  let sent = false;
  const fetcher = async url => { if (String(url).includes("durum.json")) return new Response("", { status: 500 }); sent = true; return new Response(JSON.stringify({ ok: true })); };
  await sendDailySummaryIfDue({ TELEGRAM_BOT_TOKEN: "x", TELEGRAM_CHAT_ID: "1", DB: mock.DB }, fetcher, Date.parse("2026-10-30T06:00:00Z"));
  assert.equal(sent, false);
});
