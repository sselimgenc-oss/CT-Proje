/* Karakter tıklama repliği ve Canvas çizim katmanı. */
'use strict';
const fs = require('fs'), path = require('path'), vm = require('vm');
const src = fs.readFileSync(path.join(__dirname, '..', 'konusma.js'), 'utf8');
let time = 1000;
const OFIS = { World: { BX: 0, BY: 0, roomAt: { '2,2': { id: 'risk' } } } };
vm.runInNewContext(src, { window: { OFIS }, performance: { now: () => time }, Map, Math });
const K = OFIS.Konusma;
const actor = { id: 's:risk1', room: 'risk', sx: 100, sy: 100, pose: 'sit', alpha: 1 };
Object.assign(actor, { kind: 'staff', path: [], wait: 0 });
const state = { actorById: { [actor.id]: actor } };
const drawn = [];
const ctx = {
  save() {}, restore() {}, beginPath() {}, moveTo() {}, lineTo() {}, quadraticCurveTo() {}, closePath() {}, fill() {}, stroke() {},
  measureText: text => ({ width: text.length * 6 }), fillText: text => drawn.push(text)
};
K.speak(actor);
if (!K.busy()) throw new Error('actor response should keep the animation loop awake');
K.draw(ctx, state, (x, y) => ({ x, y }), 300, 200);
if (!drawn.includes('Sınırları yakından izliyorum.')) throw new Error('click response should draw a room-specific speech bubble');
drawn.length = 0; K.speak(actor); K.draw(ctx, state, (x, y) => ({ x, y }), 300, 200);
if (!drawn.includes('Kontrol listesi açık.')) throw new Error('same actor should rotate its short responses');
drawn.length = 0; time += 2400; K.draw(ctx, state, (x, y) => ({ x, y }), 300, 200);
if (K.busy() || drawn.length) throw new Error('expired speech bubble should be cleared');
actor.tx = 2; actor.ty = 2;
time += K.nextMs() + 1;
K.update({ actors: [actor], actorById: { [actor.id]: actor } });
if (!K.busy()) throw new Error('ambient office chatter should wake the canvas loop');
drawn.length = 0; K.draw(ctx, { actorById: { [actor.id]: actor } }, (x, y) => ({ x, y }), 300, 200);
if (!drawn.length) throw new Error('ambient room-specific line should draw as a speech bubble');
console.log('actor speech checks passed');
