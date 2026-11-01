/* Üst oda gezinmesi için görünürlük, gruplama ve erişilebilirlik sözleşmesi. */
'use strict';
const fs = require('fs');
const path = require('path');
const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');
const css = fs.readFileSync(path.join(__dirname, '..', 'ofis.css'), 'utf8');
const fail = [];
const ok = (label, condition) => { console.log((condition ? 'OK   ' : 'FAIL ') + label); if (!condition) fail.push(label); };
const nav = html.match(/<nav class="ray"[\s\S]*?<\/nav>/);
if (!nav) throw new Error('Ofis gezinme nav öğesi bulunamadı');
const n = nav[0];
const roomGroup = id => {
  const re = new RegExp('<details class="ray-grup">\\s*<summary>([^<]+)</summary>([\\s\\S]*?)</details>', 'g');
  for (const m of n.matchAll(re)) if (m[2].includes('data-oda="' + id + '"')) return m[1];
  return null;
};
ok('Genel, bina görünümünün ana gezinme düğmesi', /data-tab="genel"[^>]*aria-pressed="true"[\s\S]*?<span>Genel<\/span>/.test(n));
ok('Trade Odası sırası İlk 11, Yedekler, PAF Takım', /<summary>Trade Odası<\/summary>[\s\S]*?data-oda="oda"[\s\S]*?data-oda="kontrol"[\s\S]*?data-oda="aday"/.test(n));
ok('Yönetim: Makam, Sekreterlik, Finans, Risk', ['makam', 'sekreterlik', 'finans', 'risk'].every(id => roomGroup(id) === 'Yönetim'));
ok('Operasyon: Bilgi İşlem, Denetim, Arşiv, Haberleşme', ['tarama', 'denetim', 'arsiv', 'haberlesme'].every(id => roomGroup(id) === 'Operasyon'));
ok('Kapı ve LAB gezinmede yer almıyor', !/data-oda="(?:kapi|lab)"/.test(n));
ok('Çay Ocağı ayrı, isteğe bağlı grup', roomGroup('cay') === 'Çay Ocağı');
ok('Gruplar native details/summary ile klavyeden açılabilir', (n.match(/<details class="ray-grup">/g) || []).length === 4 && (n.match(/<summary>/g) || []).length === 4);
ok('Mobilde yatay kaydırma ve dokunma hedefleri tanımlı', /@media \(max-width: 899px\)[\s\S]*?\.ray-ic[\s\S]*?overflow-x: auto[\s\S]*?\.ray button[\s\S]*?min-height: 44px/.test(css));
if (fail.length) process.exitCode = 1;
