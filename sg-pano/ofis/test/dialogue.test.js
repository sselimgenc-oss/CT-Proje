/* Kısa konuşma katmanı: olay bağlama, temizleme ve güvenli Canvas metni. */
'use strict';
const fs = require('fs'), path = require('path'), vm = require('vm');
const src = fs.readFileSync(path.join(__dirname, '..', 'dialogue.js'), 'utf8');
let time = 1000, hook;
const OFIS = { onEvent: fn => { hook = fn; } };
const context = { window: { OFIS }, performance: { now: () => time }, Map };
vm.runInNewContext(src, context);
const D = OFIS.Dialogue;
D.init({ onEvent: fn => { hook = fn; } });
const actor = { id: 's:denetim', room: 'denetim', sx: 100, sy: 100, pose: 'stand', alpha: 1 };
const state = { actors: [actor], actorById: { [actor.id]: actor } };
hook({ tur: 'denetim', oda: 'denetim' }, state);
const drawn = [];
const cx = {
  save() {}, restore() {}, beginPath() {}, moveTo() {}, lineTo() {}, quadraticCurveTo() {}, closePath() {}, fill() {}, stroke() {},
  measureText: text => ({ width: text.length * 6 }), fillText: text => drawn.push(text)
};
D.draw(cx, state, (x, y) => ({ x, y }), 300, 200);
if (!drawn.includes('Denetim tamamlandı.')) throw new Error('event dialogue should render for the assigned room actor');
drawn.length = 0;
hook({ tur: 'unknown_event', oda: 'denetim' }, state);
D.draw(cx, state, (x, y) => ({ x, y }), 300, 200);
if (drawn.length !== 1) throw new Error('unknown event must not create extra dialogue');
time += 3000;
drawn.length = 0;
D.draw(cx, state, (x, y) => ({ x, y }), 300, 200);
if (drawn.length) throw new Error('expired dialogue should be removed');
console.log('dialogue renderer checks passed');
