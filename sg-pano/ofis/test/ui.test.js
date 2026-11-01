/* Arayüz testleri (Playwright + Chromium):  node ofis/test/ui.test.js
   Kapsam: oda içi görünüm ve adres yönlendirmesi, bilgi kutusu, tıklanabilir kişiler/nesneler, ad değiştirme (saklama, dışa/içe aktarma),
   olay yokken çizim döngüsünün durması, hızlı olay kuyruğunda durum tutarlılığı, iletişim işaretleri, performans körlüğü, yasal ibare, telefon. */
'use strict';
const { chromium } = require('playwright');
const http = require('http'), fs = require('fs'), path = require('path');
const root = path.join(__dirname, '..', '..');
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.json': 'application/json', '.css': 'text/css', '.md': 'text/plain' };
let bad = 0;
const ok = (n, c, x) => { if (!c) bad++; console.log((c ? 'OK   ' : 'FAIL ') + n + (x !== undefined && x !== '' ? ' → ' + x : '')); };
const sleep = ms => new Promise(r => setTimeout(r, ms));

const srv = http.createServer((q, r) => {
  if (q.url.split('?')[0] === '/favicon.ico') { r.writeHead(204); r.end(); return; }
  let p = decodeURIComponent(q.url.split('?')[0]); if (p.endsWith('/')) p += 'index.html';
  fs.readFile(path.join(root, p), (e, d) => { if (e) { r.writeHead(404); r.end('nf'); return; } r.writeHead(200, { 'content-type': (TYPES[path.extname(p)] || 'application/octet-stream') + '; charset=utf-8' }); r.end(d); });
}).listen(0, async () => {
  const base = 'http://localhost:' + srv.address().port + '/ofis/';
  const b = await chromium.launch();
  const errs = [];
  async function open(url, opt) {
    const ctx = await b.newContext(Object.assign({ viewport: { width: 1440, height: 900 }, acceptDownloads: true }, opt || {}));
    const pg = await ctx.newPage();
    pg.on('pageerror', e => errs.push(e.message)); pg.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
    await pg.goto(base + (url || '?saat=15:40&durum=ornek')); await pg.waitForFunction('window.OFIS&&window.OFIS.ready');
    return { ctx, pg };
  }
  const click = async (pg, id) => {            // oyun dünyasındaki bir aktörün ekran konumuna tıkla
    const p = await pg.evaluate(id => { const a = OFIS.Office.state().actorById[id]; const v = OFIS.debug.toView(a.sx, a.sy - 14); const r = document.getElementById('tuval').getBoundingClientRect(); return { x: v.x + r.left, y: v.y + r.top }; }, id);
    await pg.mouse.click(p.x, p.y);
  };

  /* ---------- A. oda içi görünüm ve adres ---------- */
  let { ctx, pg } = await open();
  await pg.click('.ray [data-oda=lab]'); await sleep(900);
  let st = await pg.evaluate(() => ({ h: location.hash, a: OFIS.debug.mode.active, r: OFIS.debug.mode.room, t: OFIS.debug.roomT(), ust: !document.getElementById('odaUst').hidden, pr: document.querySelector('.ray [data-oda=lab]').getAttribute('aria-pressed') }));
  ok('Lab: adres #oda/lab, oda içi açık, geçiş tamam, geri düğmesi görünür', st.h === '#oda/lab' && st.a && st.r === 'lab' && st.t === 1 && st.ust && st.pr === 'true', JSON.stringify(st));
  const z1 = await pg.evaluate(() => OFIS.debug.cam.z), zf = await pg.evaluate(() => { const c = OFIS.debug.cam; return c.z; });
  await pg.keyboard.press('Escape'); await sleep(300);                          // ilk Esc: sol menüden açılan paneli kapatır (odada kalır)
  await pg.keyboard.press('Escape'); await sleep(900);
  st = await pg.evaluate(() => ({ h: location.hash, a: OFIS.debug.mode.active, t: OFIS.debug.roomT(), ust: document.getElementById('odaUst').hidden, z: OFIS.debug.cam.z }));
  ok('Esc binaya döndürür (adres temizlenir, yakınlaşma geri alınır)', st.h === '' && !st.a && st.t === 0 && st.ust && st.z < z1 * 0.7, JSON.stringify(st) + ' zLab=' + z1.toFixed(2));
  await pg.click('.ray [data-oda=lab]'); await sleep(500); await pg.goBack(); await sleep(900);
  ok('tarayıcı geri tuşu binaya döndürür', await pg.evaluate(() => !OFIS.debug.mode.active && location.hash === ''));
  await pg.goForward(); await sleep(900);
  ok('ileri tuşu odaya geri götürür', await pg.evaluate(() => OFIS.debug.mode.active && OFIS.debug.mode.room === 'lab'));
  await pg.click('#geriBtn'); await sleep(900);
  ok('Geri düğmesi binaya döndürür', await pg.evaluate(() => !OFIS.debug.mode.active && location.hash === ''));
  await pg.click('.ray [data-oda=kapi]'); await sleep(300); await pg.click('.ray [data-oda=arsiv]'); await sleep(400);
  ok('Kapı ve Arşiv aynı kalıpla açılır', await pg.evaluate(() => OFIS.debug.mode.room === 'arsiv' && location.hash === '#oda/arsiv'));
  await pg.click('#geriBtn'); await sleep(900);
  ok('iki oda gezdikten sonra Geri tek adımda binaya döner', await pg.evaluate(() => !OFIS.debug.mode.active && location.hash === ''));
  const walls = await pg.evaluate(() => ({ lab: OFIS.World.statics.filter(e => e.wall && e.wall.includes('lab')).length, arsiv: OFIS.World.statics.filter(e => e.wall && e.wall.includes('arsiv')).length, kapi: OFIS.World.statics.filter(e => e.wall && e.wall.includes('kapi')).length }));
  ok('seçili odanın duvar parçaları işaretli (Arşiv duvarı kalkar)', walls.arsiv > 0, JSON.stringify(walls));
  await ctx.close();
  ({ ctx, pg } = await open('?saat=15:40&durum=ornek#oda/lab'));
  ok('doğrudan #oda/lab adresi odayı anında açar', await pg.evaluate(() => OFIS.debug.mode.active && OFIS.debug.mode.room === 'lab' && OFIS.debug.roomT() === 1));
  await ctx.close();

  /* ---------- B. bilgi kutusu, tıklanabilir kişi ve nesneler ---------- */
  ({ ctx, pg } = await open());
  const atlas = await pg.evaluate(() => {
    const W = OFIS.World, ids = W.ROOMS.filter(r => r.id !== 'bahce').map(r => r.id);
    return { ids: ids, mats: W.entryMats.map(m => m.id), aligned: W.entryMats.every(m => W.roomAt[m.x + ',' + m.y].id === m.id) };
  });
  ok('özgün izometrik ofis atlası: 14 kararlı oda kimliği ve her girişte oda rengine bağlı zemin eşiği', atlas.ids.length === 14 && atlas.mats.length === 14 && atlas.ids.every(id => atlas.mats.includes(id)) && atlas.aligned, JSON.stringify(atlas));
  const floor = await pg.evaluate(() => {
    const r = OFIS.World.roomById.finans, p = OFIS.World.roomPoly(r), c = document.getElementById('tuval').getBoundingClientRect();
    for (let v = 0.2; v < 0.9; v += 0.1) for (let u = 0.2; u < 0.9; u += 0.1) {
      const x = p[0][0] + (p[1][0] - p[0][0]) * u + (p[3][0] - p[0][0]) * v;
      const y = p[0][1] + (p[1][1] - p[0][1]) * u + (p[3][1] - p[0][1]) * v;
      if (!OFIS.debug.pick(x, y, false)) { const q = OFIS.debug.toView(x, y); return { x: q.x + c.left, y: q.y + c.top }; }
    }
    return null;
  });
  if (floor) await pg.mouse.click(floor.x, floor.y);
  await sleep(850);
  ok('oda zeminine tıklama aynı Finanz panelini ve oda görünümünü açar', !!floor && await pg.evaluate(() => OFIS.debug.mode.room === 'finans' && !document.getElementById('kartPanel').hidden && /Finans/.test(document.getElementById('kpBaslik').textContent)));
  await pg.keyboard.press('Escape'); await sleep(850);
  const gaps = await pg.evaluate(() => {
    const W = OFIS.World, bad = [];
    Object.keys(W.gapsH).forEach(y => W.gapsH[y].forEach(lx => [[W.BX + lx, W.BY + +y], [W.BX + lx, W.BY + +y - 1]].forEach(t => { if (W.isBlocked(t[0], t[1])) bad.push('h' + y + ':' + lx + '→' + t.join(',')); })));
    Object.keys(W.gapsV).forEach(k => { const [lx, ly] = k.split(',').map(Number); [[W.BX + lx, W.BY + ly], [W.BX + lx - 1, W.BY + ly]].forEach(t => { if (W.isBlocked(t[0], t[1])) bad.push('v' + k + '→' + t.join(',')); }); });
    return bad;
  });
  ok('iç kapı boşlukları mobilyayla kapanmaz (Denetim koltuğu hariç)', gaps.filter(x => x !== 'h4:21→25,8').length === 0, gaps.join(', '));
  ok('denetçi trader masasına, postacı posta kutusuna yürüyebilir (yol var)', await pg.evaluate(() => { const W = OFIS.World, st = OFIS.Office.state(), d = st.actorById['s:denetim'], t = st.actorById.T046, h = st.actorById['s:haber1']; return !!W.path(d.tx, d.ty, t.tx, t.ty - 1) && !!W.path(h.tx, h.ty, W.BX + W.mailboxLocal[0] + 1, W.BY + W.mailboxLocal[1]); }));
  await pg.click('.ray [data-oda=lab]'); await sleep(900);
  await click(pg, 'T006'); await sleep(400);
  let tx = await pg.evaluate(() => document.getElementById('bilgi').textContent);
  ok('kişiye tıklayınca bilgi kutusu: Kimlik · Gerçek veri · Replik · Neden burada? (olay_id, kural, tarih)', ['Kimlik', 'Gerçek veri', 'Replik', 'Neden burada?', 'olay_id', 'kural', 'tarih', '0xAAAA…0006'].every(k => new RegExp(k, 'i').test(tx)), tx.slice(0, 80).replace(/\n/g, ' '));
  ok('ofis esprisi ayrı ve etiketli', await pg.evaluate(() => !!document.querySelector('#bilgi .r-suz .etiket') && /ofis esprisi/i.test(document.querySelector('#bilgi .r-suz .etiket').textContent)));
  ok('"X dk önce"/zaman ve n gösterilir', /n=\d+/.test(tx) && /(dk önce|şimdi|sa )/.test(tx), '');
  ok('tıklanan kişi tepki animasyonu yapar', await pg.evaluate(() => { const a = OFIS.Office.state().actorById.T006; return !!a.react; }));
  await sleep(1100);
  ok('tepki biter (döngü uykuya döner)', await pg.evaluate(() => { const a = OFIS.Office.state().actorById.T006; return !a.react; }));
  await pg.keyboard.press('Escape'); await sleep(300);
  ok('Esc önce bilgi kutusunu kapatır, odada kalır', await pg.evaluate(() => document.getElementById('bilgi').hidden && OFIS.debug.mode.active));
  await pg.keyboard.press('Escape'); await sleep(900);
  ok('ikinci Esc binaya döndürür', await pg.evaluate(() => !OFIS.debug.mode.active));

  // her kişi tıklanabilir
  const result = await pg.evaluate(async () => {
    const W = OFIS.World, Off = OFIS.Office, st = Off.state(), miss = [];
    const wait = ms => new Promise(r => setTimeout(r, ms));
    const rooms = {};
    st.actors.forEach(a => { if (a.dead) return; const room = a.kind === 'staff' ? a.room : a.kat; if (W.roomById[room] && !W.roomById[room].out) (rooms[room] = rooms[room] || []).push(a); });
    for (const room of Object.keys(rooms)) {
      OFIS.debug.goRoom(room); await wait(260);
      rooms[room].forEach(a => {
        let hit = false;
        for (let dy = 6; dy <= 30 && !hit; dy += 3) for (let dx = -3; dx <= 3 && !hit; dx += 3) { const p = OFIS.debug.pick(a.sx + dx, a.sy - dy, false); if (p && p.type === 'person' && p.a === a) hit = true; }
        if (!hit) miss.push(a.id);
      });
    }
    return { total: st.actors.filter(a => !a.dead).length, miss };
  });
  ok('tüm kişiler tıklanabilir (n=' + result.total + ')', result.miss.length === 0, result.miss.join(','));
  // her odada en az 3 tıklanabilir nesne
  const objres = await pg.evaluate(async () => {
    const W = OFIS.World, wait = ms => new Promise(r => setTimeout(r, ms)), found = {}, bad = [];
    for (const room of Object.keys(W.roomById)) {
      if (W.roomById[room].out) continue;
      OFIS.debug.goRoom(room); await wait(260);
      for (const o of W.objects.filter(x => x.room === room)) {
        const s = o.e.s; if (!s) { bad.push(o.id + ':sprite yok'); continue; }
        const x0 = o.e.px - s.ax, y0 = o.e.py - s.ay; let hit = false;
        for (let y = 3; y < s.c.height && !hit; y += 5) for (let x = 3; x < s.c.width && !hit; x += 5) { const p = OFIS.debug.pick(x0 + x, y0 + y, false); if (p && p.type === 'obje' && p.o.id === o.id) hit = true; }
        if (hit) (found[room] = found[room] || new Set()).add(o.id); else bad.push(o.id);
      }
    }
    return { sayi: Object.fromEntries(Object.keys(found).map(k => [k, found[k].size])), bad };
  });
  const az = Object.keys(objres.sayi).filter(k => objres.sayi[k] < 3);
  ok('her odada en az 3 tıklanabilir nesne (' + Object.keys(objres.sayi).length + ' oda)', Object.keys(objres.sayi).length === 14 && az.length === 0, JSON.stringify(objres.sayi) + (objres.bad.length ? ' ulaşılamayan: ' + objres.bad.join(',') : ''));
  // Lab nesnesi → bilgi kutusu
  await pg.evaluate(() => OFIS.debug.goRoom('lab')); await sleep(900);
  const lp = await pg.evaluate(() => {
    const o = OFIS.World.objects.find(x => x.id === 'lab.pano'), s = o.e.s, x0 = o.e.px - s.ax, y0 = o.e.py - s.ay;
    const hits = []; for (let y = 2; y < s.c.height; y += 2) for (let x = 2; x < s.c.width; x += 2) { const p = OFIS.debug.pick(x0 + x, y0 + y, false); if (p && p.type === 'obje' && p.o.id === 'lab.pano') hits.push([x0 + x, y0 + y]); }
    if (!hits.length) return null; const mx = hits.reduce((a, h) => a + h[0], 0) / hits.length, my = hits.reduce((a, h) => a + h[1], 0) / hits.length; hits.sort((a, b) => Math.hypot(a[0] - mx, a[1] - my) - Math.hypot(b[0] - mx, b[1] - my));
    const v = OFIS.debug.toView(hits[0][0], hits[0][1]), r = document.getElementById('tuval').getBoundingClientRect(); return { x: v.x + r.left, y: v.y + r.top };
  });
  await pg.mouse.click(lp.x, lp.y); await sleep(400);
  tx = await pg.evaluate(() => document.getElementById('bilgi').textContent);
  ok('Lab panosuna tıklayınca havuz verisi (n=, zaman) ve Replik bölümü', /Havuz panosu/.test(tx) && /n=\d+ adres/.test(tx) && /Replik/.test(tx), tx.slice(0, 90));
  await pg.click('#bKapat'); await sleep(200);
  ok('× düğmesi bilgi kutusunu kapatır', await pg.evaluate(() => document.getElementById('bilgi').hidden));
  await ctx.close();

  /* ---------- C. adlar: değiştirme, saklama, dışa/içe aktarma ---------- */
  ({ ctx, pg } = await open());
  await pg.click('#ayarBtn'); await sleep(200);
  ok('ayarlar penceresi açılır (yasal ibare dâhil)', await pg.evaluate(() => document.getElementById('ayarlar').open && /yatırım tavsiyesi değil/.test(document.getElementById('ayarlar').textContent)));
  await pg.fill('input[data-kind=oda][data-id=lab]', 'Havuz Odası'); await pg.keyboard.press('Tab'); await sleep(150);
  await pg.fill('input[data-kind=calisan][data-id=denetim]', 'Müfettiş'); await pg.keyboard.press('Tab'); await sleep(150);
  await pg.click('#ayarKapat'); await sleep(200);
  ok('oda adı menüde ve etiketlerde değişir', await pg.evaluate(() => /Havuz Odası/.test(document.querySelector('.ray [data-oda=lab] span').textContent) && OFIS.Names.room('lab') === 'Havuz Odası'));
  await pg.reload(); await pg.waitForFunction('window.OFIS&&window.OFIS.ready'); await sleep(300);
  ok('adlar sayfa yenilenince korunur', await pg.evaluate(() => OFIS.Names.room('lab') === 'Havuz Odası' && OFIS.Names.staff('denetim') === 'Müfettiş' && /Havuz Odası/.test(document.querySelector('.ray [data-oda=lab] span').textContent)));
  await pg.click('.ray [data-oda=denetim]'); await sleep(900);
  await click(pg, 's:denetim'); await sleep(400);
  tx = await pg.evaluate(() => document.getElementById('bilgi').textContent);
  ok('çalışan bilgi kutusunda yeni ad görünür', /Müfettiş/.test(tx), tx.slice(0, 30));
  await pg.keyboard.press('Escape'); await pg.keyboard.press('Escape'); await sleep(900);
  await pg.click('.ray [data-oda=oda]'); await sleep(900);
  await click(pg, 'T033'); await sleep(300);
  await pg.click('#bAdBtn'); await pg.fill('#bAdInput', 'Kısa Ad'); await pg.click('#bAdForm button[type=submit]'); await sleep(300);
  tx = await pg.evaluate(() => document.getElementById('bilgi').textContent);
  ok('trader takma adı: başlık değişir, gerçek adres (kısaltılmış) sabit kalır', /Kısa Ad/.test(tx) && /0xAAAA…0033/.test(tx), tx.slice(0, 60));
  await pg.keyboard.press('Escape'); await pg.keyboard.press('Escape'); await sleep(900);
  await pg.click('#ayarBtn'); await sleep(200);
  const [dl] = await Promise.all([pg.waitForEvent('download'), pg.click('#ayarDisa')]);
  const exported = JSON.parse(fs.readFileSync(await dl.path(), 'utf8'));
  ok('JSON dışa aktarma (surum 1; oda, çalışan, trader adları)', exported.surum === 1 && exported.odalar.lab === 'Havuz Odası' && exported.calisanlar.denetim === 'Müfettiş' && exported.traderlar.T033 === 'Kısa Ad', JSON.stringify(exported));
  await pg.click('#ayarSifirla'); await sleep(150);
  ok('varsayılana dön: adlar kadro.json varsayılanına döner', await pg.evaluate(() => OFIS.Names.room('lab') === 'LAB' && OFIS.Names.staff('denetim') === 'Denetçi' && OFIS.Names.trader('T033') === ''));
  await pg.setInputFiles('#ayarIce', { name: 'adlar.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify({ surum: 1, odalar: { lab: 'İçe Lab', yok: 'x' }, calisanlar: { cayci: 'Çaycı Usta' }, traderlar: { T033: 'Kısa Ad', zzz: 'x' } })) }); await sleep(300);
  const imp = await pg.evaluate(() => ({ lab: OFIS.Names.room('lab'), cay: OFIS.Names.staff('cayci'), t: OFIS.Names.trader('T033'), msg: document.getElementById('ayarMesaj').textContent }));
  ok('JSON içe aktarma: bilinen kimlikler uygulanır, bilinmeyenler atlanır', imp.lab === 'İçe Lab' && imp.cay === 'Çaycı Usta' && imp.t === 'Kısa Ad' && /2 kayıt atlandı/.test(imp.msg), JSON.stringify(imp));
  await pg.setInputFiles('#ayarIce', { name: 'bozuk.json', mimeType: 'application/json', buffer: Buffer.from('{bozuk') }); await sleep(300);
  ok('geçersiz JSON reddedilir, adlar bozulmaz', await pg.evaluate(() => /[iİ]çe aktarılamadı/.test(document.getElementById('ayarMesaj').textContent) && OFIS.Names.room('lab') === 'İçe Lab'));
  await pg.setInputFiles('#ayarIce', { name: 'surum.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify({ surum: 9, odalar: { lab: 'X' } })) }); await sleep(300);
  ok('desteklenmeyen sürüm reddedilir', await pg.evaluate(() => /desteklenmeyen/.test(document.getElementById('ayarMesaj').textContent) && OFIS.Names.room('lab') === 'İçe Lab'));
  await ctx.close();

  /* ---------- D. olaylar ve kısa ortam replikleri bitince döngü durur ---------- */
  ctx = await b.newContext({ viewport: { width: 1440, height: 900 } }); pg = await ctx.newPage();
  pg.on('pageerror', e => errs.push(e.message));
  const orn = JSON.parse(fs.readFileSync(path.join(root, 'ofis', 'ornek_durum.json'), 'utf8')); orn.olaylar = [];
  await pg.route('**/bos.json', r => r.fulfill({ contentType: 'application/json', body: JSON.stringify(orn) }));
  await pg.goto(base + 'index.html?saat=15:40&durum=bos.json'); await pg.waitForFunction('window.OFIS&&window.OFIS.ready');
  await pg.evaluate(() => { OFIS.Office.state().speed = 0; OFIS.Konusma.clear(); OFIS.Konusma.update = () => {}; OFIS.Konusma.nextMs = () => 30000; }); await sleep(7000);
  const k0 = await pg.evaluate(() => OFIS.perf.kare); await sleep(2500); const k1 = await pg.evaluate(() => OFIS.perf.kare);
  ok('olay yokken kare çizilmez (2,5 sn boyunca ' + (k1 - k0) + ' kare)', k1 - k0 === 0 && await pg.evaluate(() => !OFIS.debug.loop().raf));
  await pg.mouse.move(900, 400); await sleep(300); const k2 = await pg.evaluate(() => OFIS.perf.kare);
  ok('etkileşim döngüyü uyandırır', k2 > k1); await sleep(1500);
  const k3 = await pg.evaluate(() => OFIS.perf.kare); await sleep(1500);
  ok('etkileşimden sonra döngü yeniden uyur', (await pg.evaluate(() => OFIS.perf.kare)) === k3);
  await ctx.close();

  /* ---------- E. hızlı olay kuyruğu: durum her zaman doğru ---------- */
  ({ ctx, pg } = await open('?saat=15:40&durum=ornek&hiz=30'));
  await sleep(9000);
  await pg.evaluate(() => { OFIS.Office.state().speed = 0; }); await sleep(9000);
  const cons = await pg.evaluate(() => {
    const W = OFIS.World, st = OFIS.Office.state(), probs = [];
    st.actors.forEach(a => {
      if (a.dead) return;
      if (a.path.length || a.queue.length || a.wait > 0) probs.push(a.id + ':yürüyor/kuyrukta');
      if (a.carry) probs.push(a.id + ':taşıyor');
      if (a.kind === 'trader' && ['lab', 'aday', 'oda', 'kontrol'].includes(a.kat)) { if (!a.seat || a.seat.occ !== a || a.tx !== a.seat.tx || a.ty !== a.seat.ty) probs.push(a.id + ':koltuk tutarsız'); }
      if (a.kind === 'staff' && a.home && (a.tx !== a.home[0] || a.ty !== a.home[1])) probs.push(a.id + ':yerinde değil');
    });
    let occ = 0; ['lab', 'aday', 'oda', 'kontrol'].forEach(k => W.seats[k].forEach(s => { if (s.occ) occ++; }));
    const seated = st.actors.filter(a => a.kind === 'trader' && !a.dead && ['lab', 'aday', 'oda', 'kontrol'].includes(a.kat)).length;
    if (occ !== seated) probs.push('dolu koltuk ' + occ + ' ≠ oturan ' + seated);
    return { probs, turn: st.turn, simT: Math.round(st.simT), marks: OFIS.Office.marks().length, neg: Object.values(st.katlar).some(k => k.n < 0) };
  });
  ok('hız ×30 sonrası (tur ' + cons.turn + '): koltuk, kat ve figürler tutarlı, takılan animasyon yok', cons.probs.length === 0 && !cons.neg && cons.marks === 0, cons.probs.join(', '));
  await ctx.close();

  /* ---------- F. her olay türü bir iletişim işareti üretir ---------- */
  ({ ctx, pg } = await open());
  await pg.evaluate(() => { OFIS.Office.state().speed = 0; window.__m = {}; setInterval(() => OFIS.Office.marks().forEach(m => { if (m.e && m.e.tur) (window.__m[m.e.tur] = window.__m[m.e.tur] || new Set()).add(m.kind); }), 60); });
  const evs = await pg.evaluate(() => OFIS.data.olaylar.map(e => e.tur));
  for (let i = 0; i < evs.length; i++) {
    await pg.evaluate(i => OFIS.Office.applyEvent(OFIS.data.olaylar[i]), i);
    if (evs[i] === 'kirmizi_bayrak') {
      let arrived = true;
      try { await pg.waitForFunction(() => { const n = OFIS.Office.notes().T046; return !!(n && n.shown); }, null, { timeout: 12000 }); }
      catch (_) { arrived = false; }
      ok('kırmızı bayrak notu trader masasında durur', arrived);
    } else if (evs[i] === 'bayrak_kalkti') {
      try { await pg.waitForFunction(() => !OFIS.Office.notes().T046, null, { timeout: 12000 }); }
      catch (_) { /* report through the final state assertion below */ }
    } else await sleep(evs[i] === 'bildirim' ? 2800 : 1200);
  }
  await sleep(1500);
  const mm = await pg.evaluate(() => Object.fromEntries(Object.entries(window.__m).map(([k, v]) => [k, [...v]])));
  const turler = [...new Set(evs)].filter(t => t !== 'sistem'), yok = turler.filter(t => !mm[t]);
  ok('her olay türü (n=' + turler.length + ') en az bir zarf/not/ok üretir', yok.length === 0, yok.join(', '));
  ok('bayrak kalkınca not masadan kalkar', await pg.evaluate(() => !OFIS.Office.notes().T046));
  ok('olay işaretine tıklayınca olay_id ve zaman', await pg.evaluate(async () => {
    OFIS.Office.applyEvent({ id: 'ev-test', tur: 'kapi_gecti', trader: 'T062', oda: 'kapi', kural: 'ön eleme kuralı', metin: 'test' });
    await new Promise(r => setTimeout(r, 900));
    const m = OFIS.Office.marks()[0]; if (!m) return false;
    const mx = (m.a.x + m.b.x) / 2, my = (m.a.y + m.b.y) / 2, p = OFIS.debug.pick(mx, my, false);
    return !!p && p.type === 'isaret';
  }));
  await ctx.close();

  /* ---------- G. performans körlüğü ve yasal ibare ---------- */
  ({ ctx, pg } = await open());
  await sleep(400);
  tx = await pg.evaluate(() => document.body.textContent);
  ok('kasa değeri ve getiri görünür (Off.KILIT=false; ön kayıt körlüğü yalnız lider kararıyla açılır)', /\$1\.012,40/.test(tx) && /\+%1,2/.test(tx), '');
  ok('yasal ibare her ekranda ("araştırma / sanal, yatırım tavsiyesi değil")', await pg.evaluate(() => { const y = document.getElementById('yasal'); const r = y.getBoundingClientRect(); return /yatırım tavsiyesi değil/.test(y.textContent) && r.height > 0; }));
  await pg.click('.ray [data-oda=finans]'); await sleep(900);
  await pg.evaluate(() => { const o = OFIS.World.objects.find(x => x.id === 'finans.kasa'); const s = o.e.s, x0 = o.e.px - s.ax, y0 = o.e.py - s.ay; const hits = []; for (let y = 2; y < s.c.height; y += 2) for (let x = 2; x < s.c.width; x += 2) { const p = OFIS.debug.pick(x0 + x, y0 + y, false); if (p && p.type === 'obje') hits.push([x0 + x, y0 + y]); } const mx = hits.reduce((a, h) => a + h[0], 0) / hits.length, my = hits.reduce((a, h) => a + h[1], 0) / hits.length; hits.sort((a, b) => Math.hypot(a[0] - mx, a[1] - my) - Math.hypot(b[0] - mx, b[1] - my)); const v = OFIS.debug.toView(hits[0][0], hits[0][1]), r = document.getElementById('tuval').getBoundingClientRect(); window.__pt = { x: v.x + r.left, y: v.y + r.top }; });
  const pt = await pg.evaluate(() => window.__pt); await pg.mouse.click(pt.x, pt.y); await sleep(300);
  tx = await pg.evaluate(() => document.getElementById('bilgi').textContent);
  ok('Finans kasası bilgi kutusunda değer yok, "kilitli" yazar; yasal ibare var', /kilitli/.test(tx) && !/\$1\.0\d\d/.test(tx) && /yatırım tavsiyesi/.test(tx), tx.slice(0, 90));
  await ctx.close();

  /* ---------- H. hareket azaltma ---------- */
  ({ ctx, pg } = await open('?saat=15:40&durum=ornek&hiz=4', { reducedMotion: 'reduce' }));
  await sleep(6000);
  const rm = await pg.evaluate(() => ({ red: OFIS.Office.reduced, walk: OFIS.Office.state().actors.filter(a => a.path.length).length, log: OFIS.Office.state().log.length, raf: OFIS.debug.loop().raf }));
  ok('azaltılmış hareket: yürüyen yok, olaylar işleniyor, döngü uyuyor', rm.red && rm.walk === 0 && rm.log > 0 && !rm.raf, JSON.stringify(rm));
  await ctx.close();

  /* ---------- I. telefon: çekmece, dokunma hedefi, taşma ---------- */
  ({ ctx, pg } = await open('?saat=15:40&durum=ornek', { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, hasTouch: true, isMobile: true }));
  const ov = await pg.evaluate(() => ({ sw: document.documentElement.scrollWidth, iw: innerWidth }));
  ok('telefonda yatay kaydırma yok', ov.sw <= ov.iw + 1, JSON.stringify(ov));
  await pg.tap('.ray [data-oda=lab]'); await sleep(900);
  const pp = await pg.evaluate(() => { const a = OFIS.Office.state().actorById.T006; const v = OFIS.debug.toView(a.sx + 3, a.sy - 6), r = document.getElementById('tuval').getBoundingClientRect(); return { x: v.x + r.left, y: v.y + r.top }; });
  await pg.touchscreen.tap(pp.x, pp.y); await sleep(500);
  const dr = await pg.evaluate(() => { const b = document.getElementById('bilgi'), r = b.getBoundingClientRect(), k = document.getElementById('bKapat').getBoundingClientRect(); return { hidden: b.hidden, pos: getComputedStyle(b).position, bottom: Math.round(r.bottom), vh: innerHeight, w: Math.round(r.width), kw: Math.round(k.width), kh: Math.round(k.height), txt: b.innerText.length }; });
  ok('telefonda bilgi alttan çekmece olarak açılır (dokunmayla, hover gerekmez)', !dr.hidden && dr.pos === 'fixed' && Math.abs(dr.bottom - dr.vh) <= 1 && dr.w === 390, JSON.stringify(dr));
  ok('kapat düğmesi ≥ 44 px', dr.kw >= 44 && dr.kh >= 44);
  const small = await pg.evaluate(() => [...document.querySelectorAll('button, .btn-dosya')].filter(e => { const r = e.getBoundingClientRect(); const cs = getComputedStyle(e); return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && (r.height < 43.5 || r.width < 43.5) && !e.closest('table') && !e.closest('.gozcu'); }).map(e => (e.id || e.className || e.textContent.trim().slice(0, 12)) + ':' + Math.round(e.getBoundingClientRect().width) + 'x' + Math.round(e.getBoundingClientRect().height)));
  ok('telefonda tüm düğmeler ≥ 44 px (tablo ve günlük satırları hariç)', small.length === 0, small.join(', '));
  await pg.tap('#bKapat'); await sleep(200);
  ok('çekmece kapanır', await pg.evaluate(() => document.getElementById('bilgi').hidden));
  await ctx.close();


  /* ---------- K. olay çekmecesi: filtre, olaya tıkla → kamera odaya, figür vurgulanır; telefonda alttan çekmece ---------- */
  ({ ctx, pg } = await open());
  await pg.evaluate(() => { OFIS.Office.state().speed = 0; OFIS.Office.applyEvent(OFIS.data.olaylar.find(e => e.tur === 'yeni_adres')); OFIS.Office.applyEvent(OFIS.data.olaylar.find(e => e.tur === 'terfi')); });
  await pg.click('.gozcu .g-tumu'); await sleep(400);
  const c0 = await pg.evaluate(() => ({ vis: !document.getElementById('olayCekmece').hidden, n: document.querySelectorAll('#cListe button').length, oda: document.querySelectorAll('#fOda option').length, tur: document.querySelectorAll('#fTur option').length }));
  ok('olay çekmecesi açılır; geçmiş günlük + oturum olayları listelenir; oda/trader/tür filtreleri var', c0.vis && c0.n >= 14 && c0.oda === 15 && c0.tur >= 21, JSON.stringify(c0));
  await pg.selectOption('#fOda', 'haberlesme'); await sleep(200);
  let fl = await pg.evaluate(() => { const l = OFIS.Cekmece.filtered(); return { n: l.length, hep: l.every(e => e.oda === 'haberlesme') }; });
  ok('oda filtresi: yalnız o odanın olayları (n=' + fl.n + ')', fl.n >= 3 && fl.hep);
  await pg.selectOption('#fTur', 'terfi'); await sleep(200);
  fl = await pg.evaluate(() => ({ n: OFIS.Cekmece.filtered().length, ui: document.querySelectorAll('#cListe button').length }));
  ok('oda ve tür filtresi birlikte (haberleşme + terfi) → boş sonuç iletisi', fl.n === 0 && fl.ui === 0 && /olay yok/.test(await pg.evaluate(() => document.getElementById('cListe').textContent)));
  await pg.click('#fTemizle'); await pg.selectOption('#fTur', 'terfi'); await sleep(200);
  fl = await pg.evaluate(() => { const l = OFIS.Cekmece.filtered(); return { n: l.length, hep: l.every(e => e.tur === 'terfi'), trader: [...new Set(l.map(e => e.trader))] }; });
  ok('tür filtresi: yalnız terfi (n=' + fl.n + ')', fl.n >= 4 && fl.hep, '');
  await pg.selectOption('#fTrader', fl.trader[0]); await sleep(200);
  ok('trader filtresi', await pg.evaluate(t => OFIS.Cekmece.filtered().length >= 1 && OFIS.Cekmece.filtered().every(e => e.trader === t), fl.trader[0]));
  await pg.click('#fTemizle'); await pg.selectOption('#fTur', 'terfi'); await sleep(200);
  await pg.click('#cListe button >> nth=0'); await sleep(1100);
  const sp = await pg.evaluate(() => { const st = OFIS.Office.state(), l = OFIS.Cekmece.filtered()[0]; return { room: OFIS.debug.mode.room, want: l.oda, trader: l.trader, spot: st.spot && st.spot.id, active: OFIS.debug.mode.active, hash: location.hash }; });
  ok('olaya tıklayınca kamera o odaya gider ve ilgili figür vurgulanır', sp.active && sp.room === sp.want && sp.spot === sp.trader && sp.hash === '#oda/' + sp.want, JSON.stringify(sp));
  await pg.keyboard.press('Escape'); await sleep(300);
  ok('Esc önce çekmeceyi kapatır', await pg.evaluate(() => document.getElementById('olayCekmece').hidden && OFIS.debug.mode.active));
  await sleep(5300);
  ok('vurgu birkaç sn sonra kalkar, döngü uyur', await pg.evaluate(() => !OFIS.Office.busy() || OFIS.Office.state().spot.until < performance.now()));
  await ctx.close();
  ({ ctx, pg } = await open('?saat=15:40&durum=ornek', { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, hasTouch: true, isMobile: true }));
  await pg.tap('.gozcu .g-tumu'); await sleep(500);
  const mc = await pg.evaluate(() => { const b = document.getElementById('olayCekmece'), r = b.getBoundingClientRect(), it = document.querySelector('#cListe button').getBoundingClientRect(), sel = document.getElementById('fOda').getBoundingClientRect(); return { pos: getComputedStyle(b).position, bottom: Math.round(r.bottom), vh: innerHeight, w: Math.round(r.width), ih: Math.round(it.height), sh: Math.round(sel.height) }; });
  ok('telefonda olay çekmecesi alttan açılır; satır ve filtreler ≥ 44 px', mc.pos === 'fixed' && Math.abs(mc.bottom - mc.vh) <= 1 && mc.w === 390 && mc.ih >= 44 && mc.sh >= 44, JSON.stringify(mc));
  await pg.tap('#cListe button >> nth=0'); await sleep(900);
  ok('telefonda olaya dokununca çekmece kapanır, oda açılır', await pg.evaluate(() => document.getElementById('olayCekmece').hidden && OFIS.debug.mode.active));
  await ctx.close();

  /* ---------- L. bayatlık: eşik veride, X dk önce, VERİ ESKİ, sis ---------- */
  ({ ctx, pg } = await open());
  const bz = await pg.evaluate(() => { const d = OFIS.data, kay = []; Object.keys(d.oda_kaynak).forEach(r => d.oda_kaynak[r].forEach(p => { const a = p.split(':'), o = a[0] === 'veri_kalitesi' ? d.veri_kalitesi.find(x => x.anahtar === a[1]) : a[0] === 'katlar' ? d.katlar[a[1]] : d[a[0]]; if (!o || typeof o.esik_dk !== 'number') kay.push(p); })); return kay; });
  ok('her veri kaynağında esik_dk alanı var (koda sabit yazılmamış)', bz.length === 0, bz.join(','));
  await pg.evaluate(() => { OFIS.Office.state().speed = 0; });
  const b0 = await pg.evaluate(() => { const i = OFIS.Office.ageInfo('lab'); return { dk: Math.round(i.dk), esik: i.esik, stale: i.stale, st: !!OFIS.Office.state().stale.lab, txt: OFIS.Panel.ageTxt(i) }; });
  ok('Lab verisi taze: "X dk önce" ve eşik veriden', !b0.stale && b0.esik > 0 && /dk önce|şimdi/.test(b0.txt), JSON.stringify(b0));
  await pg.evaluate(() => OFIS.Office.applyEvent(OFIS.data.olaylar.find(e => e.tur === 'veri_bayat'))); await sleep(300);
  const b1 = await pg.evaluate(() => { const i = OFIS.Office.ageInfo('lab'); return { dk: Math.round(i.dk), stale: i.stale, st: !!OFIS.Office.state().stale.lab }; });
  ok('veri eşikten eskiyse oda bayat olur (95 dk > eşik)', b1.stale && b1.st && b1.dk >= 95, JSON.stringify(b1));
  await pg.click('.ray [data-oda=lab]'); await sleep(900); await pg.click('#odaBilgiBtn'); await sleep(300);
  tx = await pg.evaluate(() => document.getElementById('bilgi').textContent);
  ok('Oda bilgisi: açık "VERİ ESKİ" etiketi, yaş ve eşik', /VERİ ESKİ/.test(tx) && /dk önce/.test(tx) && /eşik/.test(tx), '');
  const fogA = await pg.evaluate(() => { const c = document.getElementById('tuval'), r = OFIS.World.roomById.lab, p = OFIS.World.roomPoly(r), v = OFIS.debug.toView((p[0][0] + p[2][0]) / 2, (p[0][1] + p[2][1]) / 2), x = c.getContext('2d').getImageData(Math.round(v.x * (c.width / OFIS.debug.view.w)), Math.round(v.y * (c.height / OFIS.debug.view.h)), 1, 1).data; return [x[0], x[1], x[2]]; });
  await pg.evaluate(() => OFIS.Office.applyEvent(OFIS.data.olaylar.find(e => e.tur === 'veri_taze'))); await sleep(500);
  const fogB = await pg.evaluate(() => { const c = document.getElementById('tuval'), r = OFIS.World.roomById.lab, p = OFIS.World.roomPoly(r), v = OFIS.debug.toView((p[0][0] + p[2][0]) / 2, (p[0][1] + p[2][1]) / 2), x = c.getContext('2d').getImageData(Math.round(v.x * (c.width / OFIS.debug.view.w)), Math.round(v.y * (c.height / OFIS.debug.view.h)), 1, 1).data; return [x[0], x[1], x[2]]; });
  const sat = a => Math.max(...a) - Math.min(...a);
  ok('bayat oda sislenir (renksizleşir); veri tazelenince renk döner', sat(fogA) < sat(fogB) || Math.abs(fogA[0] - fogB[0]) + Math.abs(fogA[2] - fogB[2]) > 20, JSON.stringify([fogA, fogB]));
  ok('veri_taze sonrası oda bayat değil', await pg.evaluate(() => !OFIS.Office.state().stale.lab));
  await ctx.close();
  // eşik veriden gelir: kasa eşiğini çok küçük yap → olay olmadan oda kendiliğinden bayatlar ve döngü o anda uyanır
  ctx = await b.newContext({ viewport: { width: 1440, height: 900 } }); pg = await ctx.newPage(); pg.on('pageerror', e => errs.push(e.message));
  const o2 = JSON.parse(fs.readFileSync(path.join(root, 'ofis', 'ornek_durum.json'), 'utf8')); o2.olaylar = []; o2.kasa.esik_dk = 0.03; o2.risk.esik_dk = 100000;
  await pg.route('**/esik.json', r => r.fulfill({ contentType: 'application/json', body: JSON.stringify(o2) }));
  await pg.goto(base + 'index.html?saat=15:40&durum=esik.json'); await pg.waitForFunction('window.OFIS&&window.OFIS.ready');
  const e0 = await pg.evaluate(() => !!OFIS.Office.state().stale.finans); await sleep(4000);
  const e1 = await pg.evaluate(() => ({ fin: !!OFIS.Office.state().stale.finans, risk: !!OFIS.Office.state().stale.risk, loop: OFIS.debug.loop().raf }));
  ok('eşik veri dosyasından okunur: kasa eşiği 0,03 dk iken Finans kendiliğinden bayatlar (olay yok), Risk eşiği büyükken taze kalır', !e0 && e1.fin && !e1.risk, JSON.stringify(e1));
  await ctx.close();

  /* ---------- M. oda iç ayrıntıları ve "bu birim ne yapar / ne yapmaz" kartı ---------- */
  ({ ctx, pg } = await open());
  await pg.evaluate(() => { OFIS.Office.state().speed = 0; });
  const det = await pg.evaluate(async () => {
    const wait = ms => new Promise(r => setTimeout(r, ms)), out = {};
    for (const [id, room] of [['risk.alarm', 'risk'], ['haberlesme.zarf_rafi', 'haberlesme'], ['sekreterlik.onkayit_kasasi', 'sekreterlik'], ['oda.masa', 'oda']]) {
      OFIS.debug.goRoom(room); await wait(900);
      const o = OFIS.World.objects.filter(x => x.id === id), hits = [];
      o.forEach(ob => { const s = ob.e.s; if (!s) return; const x0 = ob.e.px - s.ax, y0 = ob.e.py - s.ay; for (let y = 2; y < s.c.height; y += 3) for (let x = 2; x < s.c.width; x += 3) { const p = OFIS.debug.pick(x0 + x, y0 + y, false); if (p && p.type === 'obje' && p.o.id === id) hits.push([x0 + x, y0 + y]); } });
      if (!hits.length) { out[id] = null; continue; }
      const mx = hits.reduce((a, h) => a + h[0], 0) / hits.length, my = hits.reduce((a, h) => a + h[1], 0) / hits.length; hits.sort((a, b) => Math.hypot(a[0] - mx, a[1] - my) - Math.hypot(b[0] - mx, b[1] - my));
      const v = OFIS.debug.toView(hits[0][0], hits[0][1]), r = document.getElementById('tuval').getBoundingClientRect(); out[id] = { x: v.x + r.left, y: v.y + r.top };
    }
    return out;
  });
  const missing = Object.keys(det).filter(k => !det[k]);
  ok('Risk alarm paneli, Haberleşme zarf rafı, Sekreterlik ön kayıt kasası, Oda masaları tıklanabilir', missing.length === 0, missing.join(','));
  const want = { 'risk.alarm': [/Alarm paneli/, /Coin başı/, /dolu/], 'haberlesme.zarf_rafi': [/Zarf rafı/, /n=\d+/, /en çok 12/], 'sekreterlik.onkayit_kasasi': [/Ön kayıt kasası/, /ön kayıt v1\.3/, /a1b2c3d/, /2026-10-14/], 'oda.masa': [/Oda masaları/, /n=14\/20/, /Boş masa/] };
  for (const id of Object.keys(want)) {
    const room = id.split('.')[0]; await pg.evaluate(r => OFIS.debug.goRoom(r), room); await sleep(900);
    const q = await pg.evaluate(id => { const ob = OFIS.World.objects.find(x => x.id === id), s = ob.e.s, x0 = ob.e.px - s.ax, y0 = ob.e.py - s.ay, hits = []; OFIS.World.objects.filter(x => x.id === id).some(o2 => { const s2 = o2.e.s, ax = o2.e.px - s2.ax, ay = o2.e.py - s2.ay; for (let y = 2; y < s2.c.height; y += 3) for (let x = 2; x < s2.c.width; x += 3) { const p = OFIS.debug.pick(ax + x, ay + y, false); if (p && p.type === 'obje' && p.o.id === id) hits.push([ax + x, ay + y]); } return hits.length > 0; }); const mx = hits.reduce((a, h) => a + h[0], 0) / hits.length, my = hits.reduce((a, h) => a + h[1], 0) / hits.length; hits.sort((a, b) => Math.hypot(a[0] - mx, a[1] - my) - Math.hypot(b[0] - mx, b[1] - my)); const v = OFIS.debug.toView(hits[0][0], hits[0][1]), r = document.getElementById('tuval').getBoundingClientRect(); return { x: v.x + r.left, y: v.y + r.top }; }, id);
    await pg.mouse.click(q.x, q.y); await sleep(350);
    const t = await pg.evaluate(() => document.getElementById('bilgi').textContent);
    ok(id + ' bilgi kutusu işlevini gösterir', want[id].every(re => re.test(t)), t.slice(0, 160));
    await pg.keyboard.press('Escape');
  }
  const s0 = await pg.evaluate(() => [OFIS.World.alarmE.s, OFIS.World.zarfE.s]);
  await pg.evaluate(() => { OFIS.Office.applyEvent(OFIS.data.olaylar.find(e => e.tur === 'risk_tavan')); OFIS.Office.applyEvent(OFIS.data.olaylar.find(e => e.tur === 'bildirim')); }); await sleep(900);
  ok('alarm paneli ve zarf rafı veriyle yeniden çizilir (tavan dolunca / bildirim gelince)', await pg.evaluate(a => OFIS.World.alarmE.s !== a[0] && OFIS.World.zarfE.s !== a[1], s0));
  const kart = await pg.evaluate(async () => {
    const bad = []; const wait = ms => new Promise(r => setTimeout(r, ms));
    for (const r of OFIS.World.ROOMS.filter(x => !x.out)) { OFIS.debug.goRoom(r.id); await wait(250); document.getElementById('odaBilgiBtn').click(); await wait(120); const b = document.getElementById('bilgi'), kc = b.querySelector('.birim-kart'); if (!kc || !/Bu birim ne yapar/.test(kc.textContent) || !/Ne yapmaz/.test(kc.textContent) || kc.querySelectorAll('div').length !== 2 || kc.textContent.length < 50) bad.push(r.id); }
    return bad;
  });
  ok('14 odanın hepsinde "Bu birim ne yapar / ne yapmaz" kartı (Oda bilgisi düğmesinde)', kart.length === 0, kart.join(','));
  await ctx.close();

  /* ---------- N. günlük özet: yalnız olay günlüğünden ---------- */
  ({ ctx, pg } = await open());
  ok('günlük özet: "dün: 3 terfi, 1 çıkış, 2 bildirim"', await pg.evaluate(() => /dün: 3 terfi, 1 çıkış, 2 bildirim/.test(document.getElementById('gunIcerik').textContent)));
  await pg.evaluate(() => { OFIS.Office.state().speed = 0; OFIS.Office.applyEvent(OFIS.data.olaylar.find(e => e.tur === 'terfi')); }); await sleep(400);
  ok('bugünkü olaylar özete eklenir (olay günlüğünden)', await pg.evaluate(() => /bugün: 1 terfi, 1 bildirim/.test(document.getElementById('gunIcerik').textContent)), await pg.evaluate(() => document.getElementById('gunIcerik').textContent));
  await ctx.close();
  ctx = await b.newContext({ viewport: { width: 1440, height: 900 } }); pg = await ctx.newPage(); pg.on('pageerror', e => errs.push(e.message));
  const o3 = JSON.parse(fs.readFileSync(path.join(root, 'ofis', 'ornek_durum.json'), 'utf8')); o3.olaylar = []; o3.gecmis_olaylar = o3.gecmis_olaylar.filter(g => !g.zaman.startsWith('2026-10-27'));
  await pg.route('**/bos3.json', r => r.fulfill({ contentType: 'application/json', body: JSON.stringify(o3) }));
  await pg.goto(base + 'index.html?saat=15:40&durum=bos3.json'); await pg.waitForFunction('window.OFIS&&window.OFIS.ready');
  ok('boş günde "dün: değişiklik yok"', await pg.evaluate(() => /dün: değişiklik yok/.test(document.getElementById('gunIcerik').textContent)));
  o3.gecmis_olaylar = []; await ctx.close();
  ctx = await b.newContext({ viewport: { width: 1440, height: 900 } }); pg = await ctx.newPage(); pg.on('pageerror', e => errs.push(e.message));
  const o4 = JSON.parse(fs.readFileSync(path.join(root, 'ofis', 'ornek_durum.json'), 'utf8')); o4.olaylar = []; o4.gecmis_olaylar = [{ id: 'x1', tur: 'terfi', zaman: '2026-10-27T10:00:00Z' }, { id: 'x2', tur: 'terfi', zaman: '2026-10-27T11:00:00Z' }, { id: 'x3', tur: 'havuzdan_cikar', zaman: '2026-10-27T12:00:00Z' }, { id: 'x4', tur: 'islem_acildi', zaman: '2026-10-27T12:30:00Z' }];
  await pg.route('**/bos4.json', r => r.fulfill({ contentType: 'application/json', body: JSON.stringify(o4) }));
  await pg.goto(base + 'index.html?saat=15:40&durum=bos4.json'); await pg.waitForFunction('window.OFIS&&window.OFIS.ready');
  ok('özet yalnız günlükten türer ve yalnız tanımlı gruplar yazılır ("dün: 2 terfi, 1 çıkış")', await pg.evaluate(() => /dün: 2 terfi, 1 çıkış(?!,)/.test(document.getElementById('gunIcerik').textContent)), await pg.evaluate(() => document.getElementById('gunIcerik').textContent));
  await ctx.close();

  /* ---------- O. ses: varsayılan kapalı, ayarlardan açılır, olay başına tek kısa ton (kodla) ---------- */
  ctx = await b.newContext({ viewport: { width: 1440, height: 900 } }); pg = await ctx.newPage(); pg.on('pageerror', e => errs.push(e.message));
  await pg.addInitScript(() => {
    window.__tones = [];
    window.AudioContext = class { constructor() { this.currentTime = 0; this.destination = {}; this.state = 'running'; } resume() { return Promise.resolve(); }
      createGain() { return { gain: { value: 1, setValueAtTime() {}, exponentialRampToValueAtTime() {}, linearRampToValueAtTime() {} }, connect() {} }; }
      createOscillator() { const o = { type: '', frequency: { value: 0 }, connect() {}, start() { window.__tones.push(o.frequency.value); }, stop() {} }; return o; } };
  });
  await pg.goto(base + '?saat=15:40&durum=ornek'); await pg.waitForFunction('window.OFIS&&window.OFIS.ready');
  await pg.evaluate(() => { OFIS.Office.state().speed = 0; });
  const so = await pg.evaluate(() => ({ on: OFIS.Ses.isOn(), cb: document.getElementById('sesAc').checked }));
  ok('ses varsayılan kapalı', !so.on && !so.cb);
  await pg.evaluate(() => { ['bildirim', 'terfi', 'risk_tavan'].forEach(t => OFIS.Office.applyEvent(OFIS.data.olaylar.find(e => e.tur === t))); }); await sleep(300);
  ok('kapalıyken hiç ton çalmaz', (await pg.evaluate(() => window.__tones.length)) === 0);
  await pg.click('#ayarBtn'); await sleep(200); await pg.check('#sesAc'); await pg.click('#ayarKapat'); await sleep(200);
  await pg.evaluate(() => OFIS.Office.applyEvent(OFIS.data.olaylar.find(e => e.tur === 'bildirim'))); await sleep(300);
  await pg.evaluate(() => OFIS.Office.applyEvent(OFIS.data.olaylar.find(e => e.tur === 'risk_tavan'))); await sleep(300);
  const tn = await pg.evaluate(() => ({ t: window.__tones.slice(), k: OFIS.Names.kadro().olay_turleri }));
  ok('açıkken olay başına tek ton; frekans kadro.json olay_turleri\'nden (bildirim ≠ risk_tavan)', tn.t.length === 2 && tn.t[0] === tn.k.bildirim.ton && tn.t[1] === tn.k.risk_tavan.ton && tn.t[0] !== tn.t[1], JSON.stringify(tn.t));
  await pg.evaluate(() => { const s = OFIS.Office.state(); s.fastUntil = performance.now() + 4000; OFIS.Office.applyEvent(OFIS.data.olaylar.find(e => e.tur === 'terfi')); }); await sleep(200);
  ok('olay yağmurunda ton çalınmaz', (await pg.evaluate(() => window.__tones.length)) === 2);
  await pg.reload(); await pg.waitForFunction('window.OFIS&&window.OFIS.ready');
  ok('ses tercihi bu tarayıcıda saklanır', await pg.evaluate(() => OFIS.Ses.isOn() && document.getElementById('sesAc').checked));
  await ctx.close();

  /* ---------- P. terfi kuralı veriden gelir, kodda sabit sayı yok ---------- */
  ({ ctx, pg } = await open());
  await pg.evaluate(() => { OFIS.Office.state().speed = 0; OFIS.Office.applyEvent(OFIS.data.olaylar.find(e => e.tur === 'terfi')); });
  const tk = await pg.evaluate(() => OFIS.data.olaylar.filter(e => e.tur === 'terfi').map(e => e.kural).concat(OFIS.data.traderlar.filter(t => t.kat === 'aday').map(t => t.kat_olay.kural)));
  ok('terfi kuralı örnek veride ön kayıttaki gibi: ≥ 3 hafta ve ≥ 10 kapanmış işlem', tk.length >= 5 && tk.every(k => /≥ 3 hafta ve ≥ 10 kapanmış işlem/.test(k)) && !tk.some(k => /14 gün|20 işlem/.test(k)));
  await pg.click('.ray [data-oda=aday]'); await sleep(900); await click(pg, 'T014'); await sleep(400);
  tx = await pg.evaluate(() => document.getElementById('bilgi').textContent);
  ok('terfi eden trader\'ın kat_olay kaydı olaydan gelir (kural, olay_id)', await pg.evaluate(() => { const t = OFIS.Office.state().traders.T004, e = OFIS.data.olaylar.find(x => x.tur === 'terfi'); return t.kat_olay && t.kat_olay.id === e.id && t.kat_olay.kural === e.kural; }));
  ok('trader repliği ve "Neden burada?" kural metnini olaydaki kural alanından alır', /≥ 3 hafta ve ≥ 10 kapanmış işlem/.test(tx), tx.slice(0, 100));
  await ctx.close();


  /* ---------- Q. ofis paneli: kart sütunu varsayılan gizli, sol menüden açılan panel, günlük özet şeridi ---------- */
  ({ ctx, pg } = await open());
  await pg.evaluate(() => { OFIS.Office.state().speed = 0; });
  const q0 = await pg.evaluate(() => ({ sol: getComputedStyle(document.getElementById('sol')).display, tw: document.getElementById('tuval').getBoundingClientRect().width, iw: innerWidth, rayW: document.querySelector('.ray').getBoundingClientRect().width,
    serit: (() => { const e = document.getElementById('gunSerit'), r = e.getBoundingClientRect(); return { h: r.height, top: r.top, w: r.width, txt: e.textContent }; })(), zp: document.getElementById('zPanel').getAttribute('aria-pressed') }));
  ok('masaüstü: kart sütunu varsayılan gizli, ofis tuvali tüm genişliği kullanır (sol menü kalır)', q0.sol === 'none' && q0.tw >= q0.iw - q0.rayW - 2 && q0.rayW > 100 && q0.zp === 'false', JSON.stringify({ sol: q0.sol, tw: q0.tw, iw: q0.iw, rayW: q0.rayW }));
  ok('günlük özet: ofisin üst kenarında tek satırlık şerit ("dün: …")', q0.serit.h <= 32 && /dün:/.test(q0.serit.txt) && q0.serit.w >= q0.tw - 2, JSON.stringify(q0.serit));
  const gozcu0 = await pg.evaluate(() => { const r = document.getElementById('hGozcu').closest('.gozcu').getBoundingClientRect(); return { l: Math.round(r.left), b: Math.round(innerHeight - r.bottom), vis: r.height > 0 }; });
  ok('Gözcü kaydı kutusu yerinde (sol altta)', gozcu0.vis && gozcu0.l < 200 && gozcu0.b < 80, JSON.stringify(gozcu0));
  const panelDurum = () => pg.evaluate(() => { const p = document.getElementById('kartPanel'), r = p.getBoundingClientRect(); return { acik: !p.hidden && r.height > 0, kartlar: [...p.querySelectorAll('.kart')].map(k => k.id), baslik: document.getElementById('kpBaslik').textContent, hash: location.hash, oda: OFIS.debug.mode.room, aktif: OFIS.debug.mode.active, bilgi: !document.getElementById('bilgi').hidden, yer: r.left > 0 }; });
  ok('açılışta panel kapalı, bina görünümü', !(await panelDurum()).acik && !(await panelDurum()).aktif);
  /* eşleme tablosu: oda → kartlar; tabloda olmayanlar oda bilgisi kartı */
  const ESLE = { finans: ['cKasa'], risk: ['cRisk'], oda: ['cAcik', 'cKap'], arsiv: ['cVeri'], haberlesme: ['cTelegram'], kontrol: ['cKohort'], tarama: ['cOzet', 'cHuni'], kapi: ['cOzet', 'cHuni'], lab: ['cOzet', 'cHuni'], aday: ['cOzet', 'cHuni'] };
  const bozuk = [];
  for (const id of Object.keys(ESLE)) {
    await pg.click('.ray [data-oda=' + id + ']'); await sleep(450);
    const d = await panelDurum();
    if (!(d.acik && JSON.stringify(d.kartlar) === JSON.stringify(ESLE[id]) && d.hash === '#oda/' + id && d.oda === id && d.aktif && !d.bilgi)) bozuk.push(id + ':' + JSON.stringify(d));
  }
  ok('sol menü → panel eşlemesi (Finans→kasa, Risk→risk, Oda→açık işlemler, Tarama/Kapı/Lab/Aday→özet+huni, Arşiv→veri kalitesi, Haberleşme→Telegram) + kamera odaya, adres #oda/<ad>', bozuk.length === 0, bozuk.join(' | ').slice(0, 300));
  const digerleri = [];
  for (const id of ['denetim', 'sekreterlik', 'makam', 'cay']) {
    await pg.click('.ray [data-oda=' + id + ']'); await sleep(450);
    const d = await panelDurum();
    if (!(!d.acik && d.bilgi && d.oda === id && /oda/i.test(await pg.evaluate(() => document.getElementById('bilgi').textContent)))) digerleri.push(id + ':' + JSON.stringify(d));
  }
  ok('diğer odalar (Denetim, Sekreterlik, Makam, Çay ocağı) → oda bilgisi kartı, panel kapalı', digerleri.length === 0, digerleri.join(' | ').slice(0, 300));
  /* kartlar panelde: sütundan alınır, kapanınca yerine döner */
  await pg.click('.ray [data-oda=finans]'); await sleep(450);
  ok('panelde kart sütunundan alınan gerçek kart (Gölge kasası görünür değer)', await pg.evaluate(() => { const k = document.querySelector('#kartPanel #cKasa'); return !!k && /\$1\.012,40/.test(k.textContent) && k.closest('#sol') === null; }));
  const sirasi = await pg.evaluate(() => [...document.querySelectorAll('#sol > .kart')].map(k => k.id).join(','));
  ok('açıkken kart sütunundan eksik (cKasa yok)', !/cKasa/.test(sirasi), sirasi);
  /* kapatma yolları */
  const kapaliMi = async () => !(await panelDurum()).acik && await pg.evaluate(() => document.querySelectorAll('#sol > .kart').length === 10 && document.querySelector('#sol > #cKasa') !== null);
  await pg.click('#kpKapat'); await sleep(1000);
  const dK = await panelDurum();
  ok('× düğmesi paneli kapatır, kartlar sütuna döner, kamera binaya döner (adres temizlenir)', await kapaliMi() && !dK.aktif && dK.hash === '');
  await pg.click('.ray [data-oda=finans]'); await sleep(450); await pg.keyboard.press('Escape'); await sleep(1000);
  const dE = await panelDurum();
  ok('Esc paneli kapatır ve kamera binaya döner', await kapaliMi() && !dE.aktif && dE.hash === '');
  await pg.keyboard.press('Escape'); await sleep(900);
  ok('ikinci Esc binaya döndürür', !(await panelDurum()).aktif);
  await pg.click('.ray [data-oda=risk]'); await sleep(450);
  await pg.click('.ray [data-oda=risk]'); await sleep(1000);
  ok('aynı menüye ikinci tıklama paneli kapatır, kamera binaya döner', await kapaliMi() && !(await panelDurum()).aktif);
  await pg.click('.ray [data-oda=risk]'); await sleep(450);
  ok('aynı menüye üçüncü tıklama yeniden açar', (await panelDurum()).acik);
  await pg.click('.ray [data-oda=makam]'); await sleep(450); await pg.click('.ray [data-oda=makam]'); await sleep(250);
  ok('oda bilgisi kartında da ikinci tıklama kapatır', !(await panelDurum()).bilgi);
  await pg.click('.ray [data-oda=finans]'); await sleep(450);
  const bos = await pg.evaluate(() => { const r = document.getElementById('tuval').getBoundingClientRect(); for (let y = 140; y < r.height - 240; y += 20) for (let x = 520; x < r.width - 80; x += 20) { const w = OFIS.debug.toWorld(x, y); if (!OFIS.debug.pick(w.x, w.y, false)) return { x: r.left + x, y: r.top + y }; } return null; });
  await pg.mouse.click(bos.x, bos.y); await sleep(500);
  ok('ofiste boş alana tıklama paneli kapatır', await kapaliMi() || !(await panelDurum()).acik);
  await pg.click('.ray [data-oda=lab]'); await sleep(450);
  await pg.click('.ray [data-tab=genel]'); await sleep(900);
  const dT = await panelDurum();
  ok('"Tüm ofis" paneli kapatır ve binayı gösterir (adres temizlenir)', await kapaliMi() && !dT.aktif && dT.hash === '');
  await pg.goto(pg.url().split('#')[0] + '#oda/lab'); await pg.reload(); await pg.waitForFunction('window.OFIS&&window.OFIS.ready'); await sleep(900);
  const dH = await panelDurum();
  ok('adres #oda/lab davranışı korunur (doğrudan açılış: oda içi, panel kendiliğinden açılmaz)', dH.aktif && dH.oda === 'lab' && !dH.acik);
  await pg.click('.ray [data-oda=finans]'); await sleep(450);
  await pg.goBack(); await sleep(900);
  ok('tarayıcı geri tuşu: panel kapanır, önceki duruma dönülür', !(await panelDurum()).acik);
  /* günlük özet şeridi → ayrıntı paneli */
  await pg.click('.ray [data-tab=genel]'); await sleep(700);
  await pg.click('#gunSerit'); await sleep(300);
  const dG = await panelDurum();
  ok('günlük özet şeridine tıklayınca ayrıntı paneli (Günlük özet kartı)', dG.acik && JSON.stringify(dG.kartlar) === '["cGun"]' && /dün/.test(await pg.evaluate(() => document.querySelector('#kartPanel #gunIcerik').textContent)));
  await pg.click('#gunSerit'); await sleep(250);
  ok('şeride ikinci tıklama kapatır', await kapaliMi());
  /* olay çekmecesi ile birlikte çakışmaz */
  await pg.click('.ray [data-oda=risk]'); await sleep(450); await pg.click('.ray [data-olay-ac]'); await sleep(300);
  ok('olay çekmecesi açılınca panel kapanır (çakışma yok)', !(await panelDurum()).acik && await pg.evaluate(() => !document.getElementById('olayCekmece').hidden));
  await pg.keyboard.press('Escape');
  /* performans körlüğü ve yasal ibare paneldeyken de aynı */
  await pg.click('.ray [data-oda=finans]'); await sleep(450);
  const pnlTxt = await pg.evaluate(() => document.getElementById('kartPanel').textContent);
  ok('panelde de kasa değeri görünür, yasal ibare de görünür', /\$1\.012,40/.test(pnlTxt) && /yatırım tavsiyesi değil/i.test(await pg.evaluate(() => document.getElementById('yasal').textContent)));
  /* ◧ düğmesi klasik sütunu geri getirir: panel modu kapanır, eski davranış */
  await pg.click('#zPanel'); await sleep(400);
  const dC = await pg.evaluate(() => ({ sol: getComputedStyle(document.getElementById('sol')).display, panel: document.getElementById('kartPanel').hidden, bas: document.getElementById('zPanel').getAttribute('aria-pressed'), n: document.querySelectorAll('#sol > .kart').length }));
  ok('◧ klasik kart sütununu geri getirir (kartlar yerine döner)', dC.sol !== 'none' && dC.panel && dC.bas === 'true' && dC.n === 10, JSON.stringify(dC));
  await pg.click('.ray [data-oda=risk]'); await sleep(500);
  ok('klasik sütun açıkken menü eski gibi çalışır (panel açılmaz)', (await panelDurum()).acik === false && (await panelDurum()).oda === 'risk');
  await ctx.close();

  /* telefon: aynı sahne önceliği; menüden açılan kart alttan panelde */
  ({ ctx, pg } = await open('?saat=15:40&durum=ornek', { viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true }));
  const ph = await pg.evaluate(() => ({ sol: getComputedStyle(document.getElementById('sol')).display, serit: getComputedStyle(document.getElementById('gunSerit')).display, panel: getComputedStyle(document.getElementById('kartPanel')).display, sw: document.documentElement.scrollWidth, n: document.querySelectorAll('#sol > .kart').length }));
  ok('telefon: varsayılan tek sahne, panel başlangıçta kapalı ve yatay kaydırma yok', ph.sol === 'none' && ph.serit === 'none' && ph.panel === 'none' && ph.sw <= 390 && ph.n === 10, JSON.stringify(ph));
  await pg.tap('.ray [data-oda=finans]'); await sleep(700);
  // kullanıcı isteği (2026-10-30): telefonda menüye dokununca bilgi kartı alttan açılan panelde görünür; × ile kart sütuna geri döner
  const tp = await pg.evaluate(() => { const k = document.getElementById('kartPanel'), r = k.getBoundingClientRect(); return { acik: !k.hidden && getComputedStyle(k).display !== 'none', alt: Math.round(r.bottom), ust: Math.round(r.top), kart: k.querySelectorAll('.kart').length, sw: document.documentElement.scrollWidth }; });
  ok('telefon: menüye dokununca bilgi kartı alttan açılan panelde görünür (ekranın alt yarısında, yatay kaydırma yok)', tp.acik && tp.kart >= 1 && tp.alt >= 840 && tp.ust > 300 && tp.sw <= 390, JSON.stringify(tp));
  await pg.tap('#kpKapat'); await sleep(500);
  ok('telefon: × ile panel kapanır, kartlar sütuna geri döner', await pg.evaluate(() => document.getElementById('kartPanel').hidden && document.querySelectorAll('#sol > .kart').length === 10));
  await ctx.close();


  /* ---------- R. tek deneyim: ayrı ana pano gezinmesi yok ---------- */
  ({ ctx, pg } = await open());
  ok('ofis oda gezinmesinde ayrı ana pano bağlantısı yok', await pg.evaluate(() => !document.getElementById('anaPanoLink') && !document.querySelector('.marka[href]')));
  await ctx.close();
  ({ ctx, pg } = await open('?saat=15:40&durum=ornek', { viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true }));
  ok('telefon: ayrı ana pano bağlantısı da yok', await pg.evaluate(() => !document.getElementById('anaPanoLink')));
  await ctx.close();

  /* ---------- T. sol menü paneli kapanınca kamera panel öncesi görünüme yumuşakça döner ---------- */
  ({ ctx, pg } = await open());
  await pg.evaluate(() => { OFIS.Office.state().speed = 0; });
  const camDurum = () => pg.evaluate(() => { const c = OFIS.debug.cam; return { z: c.z, cx: c.cx, cy: c.cy, hash: location.hash, aktif: OFIS.debug.mode.active, oda: OFIS.debug.mode.room, panel: !document.getElementById('kartPanel').hidden }; });
  const yakin = (a, c) => Math.abs(a.z - c.z) < 0.01 && Math.abs(a.cx - c.cx) < 1 && Math.abs(a.cy - c.cy) < 1;
  const bina0 = await camDurum();
  const yol = [['× düğmesi', () => pg.click('#kpKapat')], ['Esc', () => pg.keyboard.press('Escape')], ['aynı menüye ikinci tıklama', () => pg.click('.ray [data-oda=aday]')]];
  for (const [ad, kapat] of yol) {
    await pg.click('.ray [data-oda=aday]'); await sleep(900);
    const ac = await camDurum();
    ok(`${ad}: panel açıkken kamera odaya yakın (z büyük), adres #oda/aday`, ac.panel && ac.z > bina0.z * 1.3 && ac.hash === '#oda/aday', JSON.stringify(ac));
    await kapat(); await sleep(150);
    const ara = await camDurum();
    await sleep(1100);
    const son = await camDurum();
    ok(`${ad}: kamera yumuşak geçişle panel öncesi görünüme (bina) döner`, yakin(son, bina0) && !son.aktif && !son.panel, JSON.stringify({ son, bina0 }));
    ok(`${ad}: geçiş animasyonlu (150 ms'de hâlâ yolda)`, ara.z !== son.z || ara.cx !== son.cx, JSON.stringify(ara));
    ok(`${ad}: #oda/… adresi temizlendi`, son.hash === '', son.hash);
  }
  /* panel açıkken başka menüye geçiş: doğrudan yeni odaya, binaya dönmeden */
  await pg.click('.ray [data-oda=aday]'); await sleep(900);
  await pg.evaluate(() => { window.__zler = []; const c = OFIS.debug.cam; window.__izle = setInterval(() => window.__zler.push(c.z), 16); });
  await pg.click('.ray [data-oda=finans]'); await sleep(1000);
  const gec = await pg.evaluate(() => { clearInterval(window.__izle); return { min: Math.min(...window.__zler), oda: OFIS.debug.mode.room }; });
  const binaZ = bina0.z;
  ok('başka menüye geçiş: kamera doğrudan yeni odaya gider, bina görünümüne dönmez (z hiç bina seviyesine inmez)', gec.oda === 'finans' && gec.min > binaZ * 1.2, JSON.stringify(gec));
  await pg.click('#kpKapat'); await sleep(1300);
  ok('geçişten sonra kapatınca kamera ilk görünüme (bina) döner', yakin(await camDurum(), bina0));
  /* elle yakınlaştırma / sürükleme sonrası kapatma */
  await pg.click('.ray [data-oda=aday]'); await sleep(900);
  const tv = await pg.evaluate(() => { const r = document.getElementById('tuval').getBoundingClientRect(); return { x: r.left + r.width / 2 + 200, y: r.top + r.height / 2 }; });
  await pg.mouse.move(tv.x, tv.y); await pg.mouse.wheel(0, 700); await sleep(200);
  await pg.mouse.move(tv.x, tv.y); await pg.mouse.down(); await pg.mouse.move(tv.x + 90, tv.y + 40, { steps: 6 }); await pg.mouse.up(); await sleep(200);
  const elle = await camDurum();
  ok('elle yakınlaştırma/sürükleme kamerayı değiştirdi', !!elle.panel && Math.abs(elle.z - bina0.z) > 0.01);
  await pg.keyboard.press('Escape'); await sleep(1300);
  ok('elle hareketten sonra da kapatınca panel öncesi görünüme dönülür', yakin(await camDurum(), bina0), JSON.stringify(await camDurum()));
  /* geri tuşu: paneli kapatır, binaya döner */
  await pg.click('.ray [data-oda=aday]'); await sleep(900);
  await pg.goBack(); await sleep(1300);
  const gb = await camDurum();
  ok('tarayıcı geri tuşu paneli kapatır, bina görünümüne döner, adres temizlenir', !gb.panel && !gb.aktif && gb.hash === '' && yakin(gb, bina0), JSON.stringify(gb));
  /* bina yakınlaştırılmışken açılan panel kapanınca o görünüme döner */
  await pg.evaluate(() => { OFIS.debug.cam.z *= 1.15; });
  await pg.evaluate(() => { OFIS.debug.cam.cx += 25; });
  const elleBina = await camDurum();
  await pg.click('.ray [data-oda=risk]'); await sleep(900); await pg.click('#kpKapat'); await sleep(1300);
  ok('panel öncesi elle ayarlı bina görünümüne dönülür', yakin(await camDurum(), elleBina), JSON.stringify({ s: await camDurum(), elleBina }));
  await ctx.close();
  /* Olaydan bağımsız personel ziyareti: ayrı sayfada zamanlayıcıyı kontrollü tetikle. */
  ({ ctx, pg } = await open('?saat=15:40&durum=ornek'));
  const roam = await pg.evaluate(() => {
    const st = OFIS.Office.state(); st.speed = 1; st.visitIn = 0;
    OFIS.Office.update(0.016, 0.016);
    return st.actors.some(a => a.kind === 'staff' && a.visitRoom && (a.path.length || a.queue.length));
  });
  ok('olay gelmeden görevli başka bir odaya ziyaret turu planlar', roam);
  await ctx.close();
  /* azaltılmış hareket: geçiş animasyonsuz */
  ({ ctx, pg } = await open('?saat=15:40&durum=ornek', { reducedMotion: 'reduce' }));
  await pg.evaluate(() => { OFIS.Office.state().speed = 0; });
  const rb = await camDurum();
  await pg.click('.ray [data-oda=aday]'); await sleep(300); await pg.click('#kpKapat'); await sleep(60);
  ok('prefers-reduced-motion: kapatınca kamera anında panel öncesi görünümde', yakin(await camDurum(), rb), JSON.stringify({ s: await camDurum(), rb }));
  await ctx.close();

  ok('sayfa/konsol hatası yok', errs.length === 0, errs.slice(0, 3).join(' | '));
  console.log(bad ? '\n' + bad + ' test başarısız' : '\nhepsi geçti');
  await b.close(); srv.close(); process.exit(bad ? 1 : 0);
});
