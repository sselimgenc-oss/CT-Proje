/* Üst gezinmenin gerçek etkileşim testi: node ofis/test/navigasyon_ui.test.js */
'use strict';
const { chromium } = require('playwright');
const http = require('http'), fs = require('fs'), path = require('path');
const root = path.join(__dirname, '..', '..');
const types = { '.html': 'text/html', '.js': 'text/javascript', '.json': 'application/json', '.css': 'text/css' };
const server = http.createServer((req, res) => {
  let file = decodeURIComponent(req.url.split('?')[0]);
  if (file.endsWith('/')) file += 'index.html';
  fs.readFile(path.join(root, file), (err, data) => {
    res.writeHead(err ? 404 : 200, { 'content-type': (types[path.extname(file)] || 'application/octet-stream') + '; charset=utf-8' });
    res.end(err ? 'not found' : data);
  });
});
const assert = (label, value) => { console.log((value ? 'OK   ' : 'FAIL ') + label); if (!value) process.exitCode = 1; };
server.listen(0, '127.0.0.1', async () => {
  let browser;
  try {
    browser = await chromium.launch();
    const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
    await page.goto('http://localhost:' + server.address().port + '/ofis/?durum=ornek');
    await page.waitForFunction('window.OFIS && window.OFIS.ready');
    await page.focus('.ray-grup summary');
    await page.keyboard.press('Enter');
    assert('klavyeyle Trade Odası açılır', await page.locator('.ray-grup').first().evaluate(el => el.open));
    await page.click('.ray-grup [data-oda=oda]');
    await page.waitForFunction("location.hash === '#oda/oda' && OFIS.debug.mode.room === 'oda'");
    assert('İlk 11 aynı oda görünümünü ve adresini açar', await page.locator('#odaUst').isVisible());
    assert('oda seçilince açılır menü kapanır', !(await page.locator('.ray-grup[open]').count()));
    await page.click('.ray [data-tab=genel]');
    await page.waitForFunction("location.hash === '' && !OFIS.debug.mode.active");
    assert('Genel binaya döner', true);
    await page.setViewportSize({ width: 390, height: 844 });
    assert('telefon görünümünde üst menü taşmadan yatay kaydırılır', await page.locator('.ray-ic').evaluate(el => getComputedStyle(el).overflowX === 'auto'));
  } catch (err) {
    console.error(err.stack || err);
    process.exitCode = 1;
  } finally {
    if (browser) await browser.close();
    server.close();
  }
});
