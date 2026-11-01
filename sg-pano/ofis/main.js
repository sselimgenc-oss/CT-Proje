/* Ofis · çizim döngüsü, kamera, gün ışığı, etiketler, etkileşim. */
(function () {
  'use strict';
  const O = window.OFIS, W = O.World, Off = O.Office, S = O.S, HW = O.HW, HH = O.HH;
  const $ = s => document.querySelector(s);
  const Names = O.Names, Info = O.Info;
  const qs = new URLSearchParams(location.search);
  const mq = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : { matches: false };
  let reduced = mq.matches || qs.get('hareket') === '0';

  /* ---------- gün ışığı (gerçek saate göre) ---------- */
  const TINT = [[0, [88, 102, 170]], [5, [100, 112, 176]], [6.5, [255, 196, 150]], [8, [255, 250, 242]], [17, [255, 247, 232]], [18.5, [255, 184, 132]], [20, [150, 130, 190]], [21.5, [98, 110, 176]], [24, [88, 102, 170]]];
  const SKY = [[0, '#0b1030', '#26305e'], [5, '#10183c', '#2d3a6c'], [6.5, '#f2a36b', '#ffe0b0'], [8, '#7cc4f5', '#d4efff'], [17, '#7cc4f5', '#d4efff'], [18.5, '#f28a5a', '#ffd0a0'], [20, '#46407a', '#c07a9a'], [21.5, '#10183c', '#2d3a6c'], [24, '#0b1030', '#26305e']];
  function lerp(a, b, t) { return a + (b - a) * t; }
  function kf(tab, h, isSky) {
    for (let i = 0; i < tab.length - 1; i++) {
      const a = tab[i], b = tab[i + 1];
      if (h >= a[0] && h <= b[0]) {
        const t = (h - a[0]) / (b[0] - a[0]);
        if (!isSky) return a[1].map((v, j) => Math.round(lerp(v, b[1][j], t)));
        return { top: O.mix(a[1], b[1], t), bot: O.mix(a[2], b[2], t) };
      }
    }
    return isSky ? { top: O.C(tab[0][1]), bot: O.C(tab[0][2]) } : tab[0][1];
  }
  let light = { h: 12, tint: [255, 250, 242], night: 0, sky: null };
  function updateLight() {
    const c = Off.trParts(Off.clock()), h = c.h + c.m / 60;
    const bucket = Math.round(h * 6);
    if (light.bucket === bucket) return false;
    const hh = bucket / 6, tint = kf(TINT, hh, false), sk = kf(SKY, hh, true);
    const lum = (tint[0] + tint[1] + tint[2]) / 765, night = Math.max(0, Math.min(1, (0.9 - lum) / 0.35));
    const day = hh >= 7.5 && hh <= 18;
    Off.gece = night;                                   // gece konturu (figürler) için
    light = { bucket: bucket, h: hh, tint: tint, night: night, sky: { key: 'k' + bucket, top: sk.top, bot: sk.bot, orb: day ? '#fff2a8' : (night > 0.6 ? '#e8ecff' : '#ffd08a') } };
    W.wins.forEach(w => { w.e.s = S.windowGlass(w.side, light.sky); });
    return true;
  }

  /* ---------- ortam ışığı ve odalara sıcak iç ışık (önceden çizilen katmanlar) ---------- */
  const mk = (w, h) => { const c = document.createElement('canvas'); c.width = w; c.height = h; return c; };
  let ambient = null, roomLight = null, roomLightKey = '';
  function buildAmbient() {
    // çarpım katmanı: ışık yönü (sol üstten) + kenarlara doğru hafif kararma
    const c = mk(W.CW, W.CH), x = c.getContext('2d');
    x.fillStyle = '#fff'; x.fillRect(0, 0, W.CW, W.CH);
    x.globalCompositeOperation = 'multiply';
    const g = x.createLinearGradient(0, 0, W.CW, W.CH); g.addColorStop(0, '#fffaf0'); g.addColorStop(0.55, '#f6f6f4'); g.addColorStop(1, '#dfe6ee');
    x.fillStyle = g; x.fillRect(0, 0, W.CW, W.CH);
    const b = W.roomPoly({ x: 0, y: 0, w: W.BW, h: W.BH }), mx = (b[0][0] + b[2][0]) / 2, my = (b[0][1] + b[2][1]) / 2 + 20, rad = Math.hypot(W.CW, W.CH) * 0.5;
    const v = x.createRadialGradient(mx, my, rad * 0.32, mx, my, rad); v.addColorStop(0, '#fff'); v.addColorStop(1, '#bfc9d6');
    x.fillStyle = v; x.fillRect(0, 0, W.CW, W.CH);
    return c;
  }
  function roomPath(x, r, up) {
    const p = W.roomPoly(r); x.beginPath(); x.moveTo(p[0][0], p[0][1] - (up || 0)); x.lineTo(p[1][0], p[1][1] - (up || 0)); x.lineTo(p[2][0], p[2][1]); x.lineTo(p[3][0], p[3][1]); x.closePath();
  }
  function buildRoomLight() {
    // toplama (lighter) katmanı: her odada merkezden dışa sıcak ışık; havuzda gece su ışığı.
    const c = mk(W.CW, W.CH), x = c.getContext('2d'), n = light.night;
    const a = 0.13 + 0.42 * n;            // gündüz hafif, akşam/gece belirgin
    W.ROOMS.forEach(r => {
      if (r.out) return;
      const p = W.roomPoly(r), cx0 = (p[0][0] + p[2][0]) / 2, cy0 = (p[0][1] + p[2][1]) / 2, rad = Math.max(p[1][0] - p[3][0], (p[2][1] - p[0][1]) * 1.6) * 0.62;
      const cool = r.id === 'denetim', col = cool ? '110,190,255' : r.id === 'makam' ? '255,160,90' : '255,188,118';
      const g = x.createRadialGradient(cx0, cy0, 0, cx0, cy0, rad);
      g.addColorStop(0, 'rgba(' + col + ',' + (a * (cool ? 0.8 : 1)).toFixed(3) + ')'); g.addColorStop(1, 'rgba(' + col + ',0)');
      x.save(); roomPath(x, r, 30); x.clip(); x.fillStyle = g; x.fillRect(cx0 - rad, cy0 - rad, rad * 2, rad * 2); x.restore();
    });
    if (n > 0.05) {
      const pl = W.poolPoly(), g = x.createRadialGradient(pl.cx, pl.cy, 0, pl.cx, pl.cy, pl.r);
      g.addColorStop(0, 'rgba(90,220,235,' + (0.5 * n).toFixed(3) + ')'); g.addColorStop(1, 'rgba(90,220,235,0)');
      x.save(); x.beginPath(); pl.pts.forEach((q, i) => (i ? x.lineTo(q[0], q[1]) : x.moveTo(q[0], q[1]))); x.closePath(); x.clip(); x.fillStyle = g; x.fillRect(pl.cx - pl.r, pl.cy - pl.r, pl.r * 2, pl.r * 2); x.restore();
    }
    return c;
  }
  function lightKey() { const s = Off.state(); return light.bucket + '|' + Object.keys(s.stale).filter(k => s.stale[k]).join(','); }

  /* ---------- oda içi görünüm durumu ---------- */
  const mode = { room: null, active: false };   // active: oda içindeyiz; room: soluklaşma sürerken önceki oda
  let roomT = 0, roomTWant = 0;                  // 0 = bina, 1 = oda içi (yumuşak geçiş)

  /* ---------- tuval ve kamera ---------- */
  const cv = $('#tuval'), cx = cv.getContext('2d');
  const lo = document.createElement('canvas'), lc = lo.getContext('2d');
  const mid = document.createElement('canvas'), mc = mid.getContext('2d');
  const view = { w: 800, h: 500, dpr: 1 };
  const cam = { cx: 0, cy: 0, z: 1 };
  let target = null, fitZ = 1, dirty = true;

  function interest() {
    const x0 = W.OX + (W.BX - W.BY - W.BH) * HW, x1 = W.OX + (W.BX + W.BW - W.BY) * HW;
    const y0 = W.OY + (W.BX + W.BY) * HH - 56, y1 = W.OY + (W.BX + W.BW + W.BY + W.BH) * HH + 18;
    return { x0: x0, x1: x1, y0: y0, y1: y1 };
  }
  function fit() {
    const r = interest(), narrow = view.w < 700, mx = narrow ? 14 : 30, my = narrow ? 20 : 30;
    const z = Math.min(view.w / (r.x1 - r.x0 + mx * 2), view.h / (r.y1 - r.y0 + my * 2));
    return { cx: (r.x0 + r.x1) / 2, cy: (r.y0 + r.y1) / 2 + (narrow ? -6 : 24), z: narrow ? z * 1.12 : z };   // telefonda açılış biraz yakın
  }
  function setCam(c, animate) {
    if (!animate || reduced) { Object.assign(cam, c); target = null; } else target = { cx: c.cx, cy: c.cy, z: c.z, t0: performance.now(), from: { cx: cam.cx, cy: cam.cy, z: cam.z }, dur: 650 };
    dirty = true;
  }
  function resize() {
    const host = $('#ofisTuval'), r = host.getBoundingClientRect();
    view.w = Math.max(200, Math.round(r.width)); view.h = Math.max(160, Math.round(r.height)); view.dpr = Math.min(2, window.devicePixelRatio || 1);
    cv.width = Math.round(view.w * view.dpr); cv.height = Math.round(view.h * view.dpr);
    const f = fit(), first = !cam.z || cam.first;
    const wasFit = Math.abs(cam.z - fitZ) < 1e-3 || !fitZ;
    fitZ = f.z;
    if (!cam.init) { Object.assign(cam, f); cam.init = true; } else if (mode.active && mode.room) Object.assign(cam, interiorCam(mode.room)); else if (wasFit) Object.assign(cam, f);
    dirty = true;
  }
  const toWorld = (px, py) => ({ x: (px - view.w / 2) / cam.z + cam.cx, y: (py - view.h / 2) / cam.z + cam.cy });
  const toView = (wx, wy) => ({ x: (wx - cam.cx) * cam.z + view.w / 2, y: (wy - cam.cy) * cam.z + view.h / 2 });
  function clampCam() {
    cam.z = Math.max(fitZ * 0.7, Math.min(4.2, cam.z));
    const mx = view.w / cam.z / 2, my = view.h / cam.z / 2;
    cam.cx = Math.max(Math.min(cam.cx, W.CW - mx * 0.3), mx * 0.3);
    cam.cy = Math.max(Math.min(cam.cy, W.CH - my * 0.3), my * 0.3);
  }

  /* ---------- sahne ---------- */
  lo.width = W.CW; lo.height = W.CH;
  let grassCache = null;
  function grassColor() {                 // avlu zemininin ortalama çim rengi (su ve yol pikselleri atlanır): gizli odanın örtüsü çevreye uysun
    if (grassCache) return grassCache;
    const r = W.roomById.bahce, p = W.roomPoly(r), g = W.ground.getContext('2d');
    let R = 0, G = 0, B = 0, n = 0;
    for (let i = 1; i < 12; i++) for (let j = 1; j < 6; j++) {
      const u = i / 12, v = j / 6, x = Math.round(p[0][0] + (p[1][0] - p[0][0]) * u + (p[3][0] - p[0][0]) * v), y = Math.round(p[0][1] + (p[1][1] - p[0][1]) * u + (p[3][1] - p[0][1]) * v);
      const d = g.getImageData(x, y, 1, 1).data;
      if (d[3] > 200 && d[1] > d[0] + 25 && d[1] > d[2] + 30) { R += d[0]; G += d[1]; B += d[2]; n++; }
    }
    grassCache = n ? 'rgb(' + Math.round(R / n) + ',' + Math.round(G / n) + ',' + Math.round(B / n) + ')' : 'rgb(94,156,70)';
    return grassCache;
  }
  function drawScene(now) {
    const ctx = lc;
    ctx.globalCompositeOperation = 'source-over'; ctx.globalAlpha = 1; ctx.imageSmoothingEnabled = false;
    ctx.drawImage(W.ground, 0, 0);
    const st = W.statics, dyn = Off.dyn();
    let j = 0;
    for (let i = 0; i < st.length; i++) {
      const e = st[i];
      while (j < dyn.length && dyn[j].k <= e.k) { dyn[j].draw(ctx); j++; }
      if (!e.s) continue;
      if (e.wall && mode.room && roomT > 0.01 && e.wall.indexOf(mode.room) >= 0) {   // seçili odanın duvarı kalkar
        const al = 1 - roomT; if (al < 0.04) continue;
        ctx.globalAlpha = al; ctx.drawImage(e.s.c, Math.round(e.px - e.s.ax), Math.round(e.py - e.s.ay)); ctx.globalAlpha = 1; continue;
      }
      ctx.drawImage(e.s.c, Math.round(e.px - e.s.ax), Math.round(e.py - e.s.ay));
    }
    while (j < dyn.length) { dyn[j].draw(ctx); j++; }
    const s = Off.state();
    // gizli oda (kontrol kolu): ofiste ayrı yer olarak görünmez; zemin ve mobilya avlu çimiyle örtülür (yalnız sayısı panelde yazar)
    W.ROOMS.forEach(r => {
      if (!r.gizli) return;
      const p = W.roomPoly(r), up = 46;
      ctx.save(); ctx.beginPath();
      ctx.moveTo(p[0][0], p[0][1] - up); ctx.lineTo(p[1][0], p[1][1] - up); ctx.lineTo(p[1][0], p[1][1]); ctx.lineTo(p[2][0], p[2][1]); ctx.lineTo(p[3][0], p[3][1]); ctx.lineTo(p[3][0], p[3][1] - up); ctx.closePath();
      ctx.fillStyle = grassColor(); ctx.fill(); ctx.restore();
    });
    // oda vurgusu
    Off.highlights().forEach(h => {
      const r = W.roomById[h.room]; if (!r) return;
      const p = W.roomPoly(r);
      ctx.save(); ctx.beginPath(); ctx.moveTo(p[0][0], p[0][1]); for (let i = 1; i < 4; i++) ctx.lineTo(p[i][0], p[i][1]); ctx.closePath();
      ctx.globalAlpha = h.a * (h.sel ? 0.9 : 1);
      ctx.fillStyle = 'rgba(255,224,120,' + (0.13 * h.pulse) + ')'; ctx.fill();
      ctx.lineWidth = 2; ctx.strokeStyle = h.sel ? 'rgba(255,255,255,0.95)' : 'rgba(255,214,90,' + (0.6 + 0.4 * h.pulse) + ')'; ctx.stroke();
      ctx.restore();
    });
    // oda içi görünüm: diğer odalar soluklaşır
    if (mode.room && roomT > 0.01) {
      const r = W.roomById[mode.room], p = W.roomPoly(r), up = 46;
      ctx.save(); ctx.beginPath(); ctx.rect(0, 0, W.CW, W.CH);
      ctx.moveTo(p[0][0], p[0][1] - up); ctx.lineTo(p[1][0], p[1][1] - up); ctx.lineTo(p[1][0], p[1][1]); ctx.lineTo(p[2][0], p[2][1]); ctx.lineTo(p[3][0], p[3][1]); ctx.lineTo(p[3][0], p[3][1] - up); ctx.closePath();
      ctx.clip('evenodd'); ctx.fillStyle = 'rgba(9,16,20,' + (0.62 * roomT).toFixed(3) + ')'; ctx.fillRect(0, 0, W.CW, W.CH); ctx.restore();
    }
    // gün ışığı (çarpım) + ortam ışığı (çarpım) + odalara sıcak iç ışık (toplama)
    const t = light.tint;
    ctx.globalCompositeOperation = 'multiply'; ctx.fillStyle = 'rgb(' + t[0] + ',' + t[1] + ',' + t[2] + ')'; ctx.fillRect(0, 0, W.CW, W.CH);
    if (!ambient) ambient = buildAmbient();
    ctx.drawImage(ambient, 0, 0);
    const lk = lightKey(); if (!roomLight || lk !== roomLightKey) { roomLight = buildRoomLight(); roomLightKey = lk; }
    ctx.globalCompositeOperation = 'lighter'; ctx.globalAlpha = 1;
    ctx.drawImage(roomLight, 0, 0);
    if (light.night > 0.05) {
      const n = light.night;
      ctx.globalAlpha = Math.min(1, n * 0.9);
      W.lamps.forEach(l => ctx.drawImage(Off.glow.warm, l.px - 26, l.py - 52 - 26));
      ctx.globalAlpha = Math.min(1, n * 0.5);
      W.wins.forEach(w => { const e = w.e; ctx.drawImage(Off.glow.blue, e.px - 22 + (w.side === 'L' ? 20 : -20), e.py - 22 - 20 + (w.side === 'L' ? 10 : 10)); });
    }
    // sunucu ışıkları: denetim durumu veridir (yeşil = tamam, sarı = dikkat); gündüz de hafif görünür
    ctx.globalAlpha = 0.35 + 0.4 * light.night;
    const gl = s.denetim === 'tamam' ? Off.glow.green : Off.glow.amber;
    Object.keys(W.leds).forEach(k => { const e = W.leds[k]; ctx.drawImage(gl, e.px - 18 + 6, e.py - 18 - 16); });
    if (s.alarm) {
      const k = reduced ? 1 : 0.5 + 0.5 * Math.sin(now / 180);
      ctx.globalAlpha = 0.85 * k; const b = W.beaconE; ctx.drawImage(Off.glow.red, b.px - 30, b.py - 30 - 24);
    }
    ctx.globalAlpha = 1; ctx.globalCompositeOperation = 'source-over';
  }

  /* ---------- ekrana aktarım (tam sayı büyütme + yumuşak küçültme) ---------- */
  function blit() {
    const dz = cam.z * view.dpr, k = dz > 1.6 ? Math.ceil(dz) : 1;
    const wl = view.w / cam.z, hl = view.h / cam.z;
    const left = cam.cx - wl / 2, top = cam.cy - hl / 2;
    const sx0 = Math.max(0, Math.floor(left)), sy0 = Math.max(0, Math.floor(top));
    const sx1 = Math.min(W.CW, Math.ceil(left + wl)), sy1 = Math.min(W.CH, Math.ceil(top + hl));
    cx.setTransform(1, 0, 0, 1, 0, 0);
    { const t = light.tint; cx.fillStyle = 'rgb(' + Math.round(94 * t[0] / 255) + ',' + Math.round(156 * t[1] / 255) + ',' + Math.round(70 * t[2] / 255) + ')'; cx.fillRect(0, 0, cv.width, cv.height); }
    const sw = sx1 - sx0, sh = sy1 - sy0;
    if (sw <= 0 || sh <= 0) return;
    if (k > 1) {
      if (mid.width !== sw * k || mid.height !== sh * k) { mid.width = sw * k; mid.height = sh * k; } mc.imageSmoothingEnabled = false; mc.drawImage(lo, sx0, sy0, sw, sh, 0, 0, sw * k, sh * k);
      cx.imageSmoothingEnabled = true; cx.imageSmoothingQuality = 'high';
      cx.drawImage(mid, 0, 0, sw * k, sh * k, (sx0 - left) * dz, (sy0 - top) * dz, sw * dz, sh * dz);
    } else {
      cx.imageSmoothingEnabled = true; cx.imageSmoothingQuality = 'high';
      cx.drawImage(lo, sx0, sy0, sw, sh, (sx0 - left) * dz, (sy0 - top) * dz, sw * dz, sh * dz);
    }
    cx.setTransform(view.dpr, 0, 0, view.dpr, 0, 0);
  }

  /* ---------- etiketler (tuval üstünde keskin metin) ---------- */
  const FONT = '"SF Mono", ui-monospace, Menlo, Consolas, "Liberation Mono", monospace';
  const lighten = (hex, f) => { const c = O.unpack(O.mix(hex, '#ffffff', f)); return 'rgb(' + c[0] + ',' + c[1] + ',' + c[2] + ')'; };
  /* plaka: kesik köşeli koyu levha + sol şerit (oda rengi). Kendi etiket dilimiz. */
  function plate(x, y, text, o) {
    cx.font = '700 ' + o.size + 'px ' + FONT;
    const tw = cx.measureText(text).width, pad = o.pad, st = o.stripe, h = o.size + pad * 2 - 1, w = tw + pad * 2 + st + 2, x0 = Math.round(x - w / 2), y0 = Math.round(y - h / 2), c = Math.max(2, Math.round(h * 0.28));
    cx.save();
    if (o.glow) { cx.shadowColor = o.glow; cx.shadowBlur = 9; }
    cx.beginPath(); cx.moveTo(x0 + c, y0); cx.lineTo(x0 + w, y0); cx.lineTo(x0 + w, y0 + h - c); cx.lineTo(x0 + w - c, y0 + h); cx.lineTo(x0, y0 + h); cx.lineTo(x0, y0 + c); cx.closePath();
    cx.fillStyle = o.bg; cx.fill(); cx.shadowBlur = 0;
    cx.save(); cx.clip();
    if (o.hatch) { cx.fillStyle = o.accent; cx.fillRect(x0, y0, st, h); cx.strokeStyle = 'rgba(15,26,32,.9)'; cx.lineWidth = 1.5; for (let k = -h; k < h; k += 4) { cx.beginPath(); cx.moveTo(x0 + k, y0 + h); cx.lineTo(x0 + k + h, y0); cx.stroke(); } }
    else { cx.fillStyle = o.accent; cx.fillRect(x0, y0, st, h); }
    cx.restore();
    cx.lineWidth = 1; cx.strokeStyle = o.edge; cx.stroke();
    cx.fillStyle = o.fg; cx.textBaseline = 'middle'; cx.textAlign = 'left'; cx.fillText(text, x0 + st + pad + 1, y0 + h / 2 + 0.5);
    cx.restore();
    return w;
  }
  const KOLC = { kohort: '#ffb86b', kontrol: '#7cc4ff', havuz: '#b7c4c9' };
  let hover = null, pinned = null, hoverRoom = null;
  function drawLabels() {
    const s = Off.state(), z = cam.z, showSigns = z >= 0.3;
    const fs = Math.max(6.5, Math.min(12.5, 5.6 + z * 3.2));
    drawTraderLabels();
    drawAgeChips();
    drawRozetler();
    if (showSigns) {
      W.ROOMS.forEach(r => {
        if (r.gizli) return;
        const p = W.sign(r), v = toView(p.x, p.y);
        if (v.x < -90 || v.y < -40 || v.x > view.w + 90 || v.y > view.h + 40) return;
        const gri = Off.gri(r.id), stale = s.stale[r.id] && !gri, sel = s.sel === r.id || hoverRoom === r.id, acc = lighten(r.ac, 0.32);
        cx.globalAlpha = mode.room && r.id !== mode.room ? 1 - 0.68 * roomT : 1;
        plate(v.x, v.y, Names.room(r.id, r.ad), { size: fs, pad: fs < 9 ? 3 : 4, stripe: fs < 9 ? 3 : 4, bg: 'rgba(12,22,28,' + (sel ? '0.97' : '0.88') + ')', fg: gri ? '#aab5b8' : '#eaf4f5', accent: stale ? '#d69a32' : gri ? '#6d777b' : acc, edge: sel ? 'rgba(255,255,255,.9)' : 'rgba(210,235,238,.28)', glow: sel ? acc : null });
        cx.globalAlpha = 1;
      });
    }
    if (O.Dialogue) O.Dialogue.draw(cx, s, toView, view.w, view.h);
    if (O.Konusma) O.Konusma.draw(cx, s, toView, view.w, view.h);
  }
  /* telefon: dolu masası olan odalarda küçük rozet ("Oda 20"); ad plakası yakınlaşmadan okunmasa da kaç kişinin oturduğu görünür */
  function drawRozetler() {
    if (view.w >= 700) return;
    const s = Off.state(), fs = Math.max(7, Math.min(11, 5.6 + cam.z * 2.4));
    ['lab', 'aday', 'oda'].forEach(id => {
      const r = W.roomById[id], n = s.katlar[id === 'lab' ? 'havuz' : id].n, dolu = s.actors.some(a => a.kind === 'trader' && a.kat === id);
      if (!r || r.out || !dolu || n == null) return;
      const p = W.sign(r), v = toView(p.x, p.y + 15);
      if (v.x < -60 || v.y < -20 || v.x > view.w + 60 || v.y > view.h + 20) return;
      cx.globalAlpha = mode.room && id !== mode.room ? 1 - 0.68 * roomT : 1;
      plate(v.x, v.y, { lab: 'Lab', aday: 'Aday', oda: 'Oda' }[id] + ' ' + n, { size: fs, pad: 3, stripe: 3, bg: 'rgba(240,196,92,.95)', fg: '#1a1206', accent: '#a8761c', edge: 'rgba(0,0,0,0)' });
      cx.globalAlpha = 1;
    });
  }
  /* her oda köşesinde ve duvar ekranında "X dk önce"; eşik aşıldıysa (veride, kaynak başına) açık VERİ ESKİ etiketi */
  function drawAgeChips() {
    const z = cam.z, s = Off.state(), fs = Math.max(6.5, Math.min(11, 5.6 + z * 2.4));
    W.ROOMS.forEach(r => {
      if (r.out) return;
      const g = Off.gri(r.id);
      if (g) {                                         // henüz verisi olmayan oda: gri, sahte sayı yok
        const p0 = W.roomPoly(r), v0 = toView(p0[3][0] + 6, p0[3][1] - 4);
        if (v0.x < -80 || v0.y < -30 || v0.x > view.w + 80 || v0.y > view.h + 30) return;
        cx.globalAlpha = mode.room && r.id !== mode.room ? 1 - 0.6 * roomT : 1;
        plate(v0.x + 56, v0.y - 8, g, { size: fs - 0.5, pad: 2, stripe: 2, bg: 'rgba(38,44,48,.88)', fg: '#c3ccd0', accent: '#6d777b', edge: 'rgba(0,0,0,0)' });
        cx.globalAlpha = 1; return;
      }
      const inf = Off.ageInfo(r.id); if (!inf) return;
      if (!inf.stale && z < 1.15) return;
      const p = W.roomPoly(r), v = toView(p[3][0] + 6, p[3][1] - 4);
      if (v.x < -80 || v.y < -30 || v.x > view.w + 80 || v.y > view.h + 30) return;
      cx.globalAlpha = mode.room && r.id !== mode.room ? 1 - 0.6 * roomT : 1;
      const t = O.Panel.ageTxt(inf);
      if (inf.stale) plate(v.x + 40, v.y - 8, 'VERİ ESKİ · ' + t, { size: fs + 1, pad: 3, stripe: 4, bg: 'rgba(40,28,6,.95)', fg: '#ffe2a0', accent: '#f2b035', edge: 'rgba(242,176,53,.9)', hatch: true });
      else plate(v.x + 22, v.y - 8, t, { size: fs - 0.5, pad: 2, stripe: 2, bg: 'rgba(12,22,28,.78)', fg: '#a9c0c6', accent: '#46d3c2', edge: 'rgba(0,0,0,0)' });
      cx.globalAlpha = 1;
    });
    if (z >= 1.5) Object.keys(s.data.ekran_kaynak || {}).forEach(id => {
      const o = W.objects.find(x => x.id === id), inf = Off.screenAge(id); if (!o || !inf) return;
      const v = toView(o.e.px, o.e.py - 60);
      if (v.x < -60 || v.y < -20 || v.x > view.w + 60 || v.y > view.h + 20) return;
      const t = O.Panel.ageTxt(inf);
      plate(v.x, v.y, inf.stale ? 'ESKİ · ' + t : t, { size: fs - 1, pad: 2, stripe: 2, bg: inf.stale ? 'rgba(40,28,6,.95)' : 'rgba(12,22,28,.8)', fg: inf.stale ? '#ffe2a0' : '#a9c0c6', accent: inf.stale ? '#f2b035' : '#46d3c2', edge: 'rgba(0,0,0,0)', hatch: inf.stale });
    });
  }
  function drawTraderLabels() {
    const z = cam.z;
    if (qs.get('etiket') === '0') return;
    const labs = Off.labels(), showAll = z >= 0.9, fs2 = Math.max(7, Math.min(10.5, 5.5 + z * 2.1));
    labs.forEach(l => {
      const hov = hover === l.a || pinned === l.a;
      if (!showAll && !hov) return;
      const v = toView(l.x, l.y);
      if (v.x < -40 || v.y < -20 || v.x > view.w + 40 || v.y > view.h + 20) return;
      const t = l.t || {}, al = Names.trader(l.a.id), short = al || (hov || z >= 2.0 ? (t.adres || l.a.id) : t.takma_ad || '…' + String(t.adres || l.a.id).slice(-4));
      cx.globalAlpha = mode.room && l.a.kat !== mode.room ? 1 - 0.6 * roomT : 1;
      plate(v.x + 4, v.y, short, { size: fs2, pad: 2, stripe: 2, bg: 'rgba(12,22,28,' + (hov ? '0.96' : '0.72') + ')', fg: hov ? '#ffd9a3' : '#eaf4f5', accent: KOLC[t.kol] || '#b7c4c9', edge: hov ? 'rgba(255,217,163,.8)' : 'rgba(0,0,0,0)' });
      cx.globalAlpha = 1;
    });
  }

  /* ---------- ipucu (yalnız ek kolaylık; asıl bilgi tıklamayla bilgi kutusunda) ---------- */
  const tip = $('#ipucu');
  function esc(s) { return String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }
  function showTip(html, px, py) {
    tip.innerHTML = html; tip.hidden = false;
    const tw = tip.offsetWidth, th = tip.offsetHeight;
    let x = px + 14, y = py + 14;
    if (x + tw > view.w - 6) x = Math.max(6, px - tw - 14);
    if (y + th > view.h - 6) y = Math.max(6, py - th - 14);
    tip.style.left = x + 'px'; tip.style.top = y + 'px';
  }
  function hideTip() { tip.hidden = true; }
  function inPoly(poly, wx, wy) {
    let c = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) { if (((poly[i][1] > wy) !== (poly[j][1] > wy)) && (wx < (poly[j][0] - poly[i][0]) * (wy - poly[i][1]) / (poly[j][1] - poly[i][1]) + poly[i][0])) c = !c; }
    return c;
  }
  function roomAtWorld(wx, wy) {
    // önce zemin (tam isabet); yoksa tavana kadar uzanan silüet (duvar bölgesi)
    let hit = null;
    W.ROOMS.forEach(r => { if (!r.out && inPoly(W.roomPoly(r), wx, wy)) hit = r; });
    if (hit) return hit;
    W.ROOMS.forEach(r => {
      if (r.out) return;
      const p = W.roomPoly(r), up = r.wall || 40;
      if (inPoly([[p[0][0], p[0][1] - up], [p[1][0], p[1][1] - up], [p[1][0], p[1][1]], [p[2][0], p[2][1]], [p[3][0], p[3][1]], [p[3][0], p[3][1] - up]], wx, wy)) hit = r;
    });
    return hit;
  }

  /* ---------- seçim: kişi, işaret, nesne (piksel isabetli; dokunmada ≥ 44 px hedef) ---------- */
  function spriteAlpha(e, wx, wy) {
    const s = e.s; if (!s) return 0;
    const x = Math.floor(wx - (e.px - s.ax)), y = Math.floor(wy - (e.py - s.ay));
    if (x < 0 || y < 0 || x >= s.c.width || y >= s.c.height) return 0;
    try { return s.c.getContext('2d').getImageData(x, y, 1, 1).data[3]; } catch (err) { return 255; }
  }
  function objectAt(wx, wy, tol) {
    let hit = null, hk = -1, near = null, nd = 1e9;
    W.objects.forEach(o => {
      if (o.room !== mode.room || !o.e.s) return;
      const sp = o.e.s, x0 = o.e.px - sp.ax, y0 = o.e.py - sp.ay, x1 = x0 + sp.c.width, y1 = y0 + sp.c.height;
      if (wx >= x0 && wx <= x1 && wy >= y0 && wy <= y1 && spriteAlpha(o.e, wx, wy) > 24) { if (o.e.k > hk) { hk = o.e.k; hit = o; } }
      else if (tol > 0) { const d = Math.hypot(Math.max(x0 - wx, 0, wx - x1), Math.max(y0 - wy, 0, wy - y1)); if (d <= tol && d < nd) { nd = d; near = o; } }
    });
    return hit || near;
  }
  function nearPerson(wx, wy, tol) {
    let best = null, bd = tol;
    Off.state().actors.forEach(a => { if (a.sx == null || a.dead) return; const d = Math.hypot(wx - a.sx, wy - (a.sy - 14)); if (d <= bd) { bd = d; best = a; } });
    return best;
  }
  function pick(wx, wy, touch) {
    const a = Off.hit(wx, wy);
    if (a) return { type: 'person', a: a };
    const m = Off.markAt(wx, wy); if (m) return m;
    if (mode.active) {
      const o = objectAt(wx, wy, 0); if (o) return { type: 'obje', o: o };
      if (touch) {
        const tol = 22 / cam.z, p = nearPerson(wx, wy, tol); if (p) return { type: 'person', a: p };
        const o2 = objectAt(wx, wy, tol); if (o2) return { type: 'obje', o: o2 };
      }
    }
    return null;
  }

  /* ---------- oda içi görünüm: aynı tuvalde kamera yakınlaşması, diğer odalar soluklaşır, adres #oda/<id> ---------- */
  let solPx = 0;                                                   // sol üst panelin kapladığı genişlik (px)
  function interiorCam(id) {
    const r = W.roomById[id], p = W.roomPoly(r), cxp = (p[0][0] + p[2][0]) / 2, cyp = (p[0][1] + p[2][1]) / 2, ww = p[1][0] - p[3][0], hh = p[2][1] - p[0][1] + 52;
    const vw = view.w - solPx, pad = vw < 700 ? 18 : 60, z = Math.max(fitZ * 1.15, Math.min(4.2, Math.min(vw / (ww + pad * 2), view.h / (hh + pad + 56))));
    return { cx: cxp - solPx / 2 / z, cy: cyp - 18, z: z };     // açık panel solu kapatır: oda kalan alanın ortasına yerleşir
  }
  function enterRoom(id, opt) {
    const r = W.roomById[id]; if (!r || r.out) return;
    kartKapat(true);
    donCam = null; mode.room = id; mode.active = true; roomTWant = 1; Off.select(id); markRay(id); infoShift = 0;
    if (opt && opt.instant) roomT = 1;
    setCam(interiorCam(id), !(opt && opt.instant));
    $('#odaUst').hidden = false; $('#odaBaslik').textContent = Names.room(id, r.ad);
    document.body.classList.add('oda-ici');
    if (Info.isOpen()) Info.close();
    kick();
  }
  let donCam = null;
  function exitRoom(opt) {
    kartKapat(true);
    mode.active = false; infoShift = 0; roomTWant = 0; Off.select(null); markRay(null); Info.close();
    if (opt && opt.instant) { roomT = 0; mode.room = null; }
    const don = donCam; donCam = null;                           // panel kapanışında kayıtlı görünüm (elle yakınlaşılmış binaya dönüş)
    setCam(don || fit(), !(opt && opt.instant));
    $('#odaUst').hidden = true; document.body.classList.remove('oda-ici');
    kick();
  }
  const roomFromHash = () => { const m = /^#oda\/([a-z]+)$/.exec(location.hash); return m && W.roomById[m[1]] && !W.roomById[m[1]].out ? m[1] : null; };
  function applyRoute(opt) { const id = roomFromHash(); if (id) enterRoom(id, opt); else if (mode.active) exitRoom(opt); }
  const depth = () => (history.state && history.state.d) || 0;
  function goRoom(id) {
    if (!W.roomById[id] || W.roomById[id].out) return;
    if (location.hash !== '#oda/' + id) { try { history.pushState({ d: depth() + 1 }, '', '#oda/' + id); } catch (e) { location.hash = '#oda/' + id; } }
    applyRoute();
  }
  function goBuilding() {
    kartKapat(true);
    if (!mode.active) { markRay(null); setCam(fit(), true); kick(); return; }
    const d = depth();
    if (d > 0) history.go(-d);                                    // tarayıcı geçmişi: popstate binaya döndürür
    else { try { history.replaceState(null, '', location.pathname + location.search); } catch (e) { location.hash = ''; } applyRoute(); }
  }
  window.addEventListener('popstate', () => applyRoute());
  $('#geriBtn').addEventListener('click', goBuilding);
  $('#odaBilgiBtn').addEventListener('click', () => { if (mode.room) Info.show({ type: 'oda', id: mode.room }); });
  /* masaüstünde bilgi kutusu sağdan açılınca oda içi görünüm sola kayar, böylece oda kutunun altında kalmaz */
  let infoShift = 0;
  function shiftFor(open) {
    if (!mode.active || !window.matchMedia('(min-width: 900px)').matches) { if (!open) infoShift = 0; return; }
    if (open && !infoShift) { infoShift = 175 / cam.z; setCam({ cx: cam.cx + infoShift, cy: cam.cy, z: cam.z }, true); }
    else if (!open && infoShift) { setCam({ cx: cam.cx - infoShift, cy: cam.cy, z: cam.z }, true); infoShift = 0; }
  }
  function animRoom(dt) {
    if (roomT === roomTWant) return;
    const sp = reduced ? 1 : dt / 0.45;
    roomT = roomTWant > roomT ? Math.min(roomTWant, roomT + sp) : Math.max(roomTWant, roomT - sp);
    if (roomT <= 0 && !mode.active) mode.room = null;
  }

  /* ---------- etkileşim ---------- */
  let drag = null;
  cv.addEventListener('pointerdown', e => {
    cv.setPointerCapture(e.pointerId);
    drag = { x: e.clientX, y: e.clientY, cx: cam.cx, cy: cam.cy, moved: false, id: e.pointerId, touch: e.pointerType === 'touch' };
  });
  cv.addEventListener('pointermove', e => {
    const r = cv.getBoundingClientRect(), px = e.clientX - r.left, py = e.clientY - r.top;
    if (drag) {
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 6) drag.moved = true;
      if (drag.moved && (cam.z > fitZ * 1.04 || !drag.touch)) { cam.cx = drag.cx - dx / cam.z; cam.cy = drag.cy - dy / cam.z; target = null; clampCam(); hideTip(); kick(); return; }
    }
    if (e.pointerType === 'touch') return;
    const w = toWorld(px, py), p = pick(w.x, w.y, false);
    hover = p && p.type === 'person' ? p.a : null; hoverRoom = p ? null : (roomAtWorld(w.x, w.y) || {}).id || null;
    if (p) showTip('<b>' + esc(Info.title(p)) + '</b><div class="m">tıkla: bilgi kutusu</div>', px, py);
    else if (hoverRoom) showTip('<b>' + esc(Names.room(hoverRoom, (W.roomById[hoverRoom] || {}).ad)) + '</b><div class="m">' + (mode.active ? 'tıkla: bu odaya geç' : 'tıkla: odaya gir') + '</div>', px, py);
    else hideTip();
    cv.style.cursor = p || hoverRoom ? 'pointer' : (cam.z > fitZ * 1.04 ? 'grab' : 'default');
    kick();
  });
  cv.addEventListener('pointerup', e => {
    const was = drag; drag = null;
    if (!was || was.moved) return;
    const r = cv.getBoundingClientRect(), px = e.clientX - r.left, py = e.clientY - r.top, w = toWorld(px, py), p = pick(w.x, w.y, was.touch);
    hideTip();
    if (p) { if (p.type === 'person' && O.Konusma) O.Konusma.speak(p.a); Info.show(p); return; }
    const room = roomAtWorld(w.x, w.y);
    if (room) railTik(room.id);
    else panelKapat();
  });
  cv.addEventListener('pointerleave', () => { hover = null; hoverRoom = null; hideTip(); kick(); });
  cv.addEventListener('wheel', e => {
    e.preventDefault();
    const r = cv.getBoundingClientRect(), px = e.clientX - r.left, py = e.clientY - r.top, before = toWorld(px, py);
    cam.z *= Math.exp(-e.deltaY * 0.0012); clampCam();
    const after = toWorld(px, py); cam.cx += before.x - after.x; cam.cy += before.y - after.y; clampCam(); target = null; kick();
  }, { passive: false });
  cv.addEventListener('keydown', e => {
    const step = 40 / cam.z;
    if (e.key === 'ArrowLeft') cam.cx -= step; else if (e.key === 'ArrowRight') cam.cx += step; else if (e.key === 'ArrowUp') cam.cy -= step; else if (e.key === 'ArrowDown') cam.cy += step;
    else if (e.key === '+' || e.key === '=') zoomBy(1.25); else if (e.key === '-') zoomBy(0.8); else if (e.key === '0') goBuilding();
    else return;
    e.preventDefault(); clampCam(); kick();
  });
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    const navOpen = document.querySelector('.ray-grup[open]');
    if (navOpen) { navOpen.open = false; navOpen.querySelector('summary').focus(); return; }
    const dlg = $('#ayarlar'); if (dlg && dlg.open) return;      // ayarlar penceresi kendi Esc'ini yönetir
    if (O.Cekmece.isOpen()) { O.Cekmece.close(); kick(); } else if (kartAcik || (once && Info.isOpen())) panelKapat(); else if (Info.isOpen()) { Info.close(); kick(); } else if (mode.active) goBuilding();
  });
  function zoomBy(f) { setCam({ cx: cam.cx, cy: cam.cy, z: Math.max(fitZ * 0.7, Math.min(4.2, cam.z * f)) }, true); kick(); }
  $('#zIn').addEventListener('click', () => zoomBy(1.35));
  $('#zOut').addEventListener('click', () => zoomBy(1 / 1.35));
  $('#zFit').addEventListener('click', goBuilding);

  /* ---------- sol dikey menü ---------- */
  /* sol menü → ofisin üstünde açılan panel. TEK EŞLEME TABLOSU: oda → açılacak kart(lar) (index.html'deki kart kimlikleri).
     Tabloda olmayan odalar (denetim, sekreterlik, makam, çay ocağı) oda bilgisi kartını (bilgi kutusu) açar. */
  const HUNI = ['cOzet', 'cHuni'];
  const PANEL_ESLE = {
    finans: ['cKasa'], risk: ['cRisk'], oda: ['cAcik', 'cKap'], arsiv: ['cVeri'], haberlesme: ['cTelegram'], kontrol: ['cKohort'],
    tarama: HUNI, kapi: HUNI, lab: HUNI, aday: HUNI,
  };
  function markRay(id) {
    document.querySelectorAll('.ray [data-tab], .ray [data-oda]').forEach(b => b.setAttribute('aria-pressed', (id ? b.dataset.oda === id : b.dataset.tab === 'genel') ? 'true' : 'false'));
    document.querySelectorAll('.ray-grup').forEach(g => {
      const active = !!(id && g.querySelector('[data-oda="' + id + '"]'));
      g.classList.toggle('secili', active);
    });
  }
  function goCard(id) {
    const el = id && $('#' + id); if (!el) return;
    const sol = $('#sol');
    if (!window.matchMedia('(min-width: 900px)').matches || !sol) return;   // telefonda sayfa kaymaz: ofis görünür kalır
    sol.scrollTo({ top: el.offsetTop - 8, behavior: reduced ? 'auto' : 'smooth' });
    el.classList.add('vurgu'); setTimeout(() => el.classList.remove('vurgu'), 1800);
  }
  function setTab(name) { if (name === 'genel') { goBuilding(); const sol = $('#sol'); if (sol) sol.scrollTo({ top: 0, behavior: reduced ? 'auto' : 'smooth' }); } }
  function refreshNames() {
    document.querySelectorAll('.ray [data-oda] span').forEach(sp => {
      const b = sp.parentElement, id = b.dataset.oda; if (!sp.dataset.def) sp.dataset.def = sp.textContent;
      sp.textContent = Names.isCustom('oda', id) ? Names.room(id) : sp.dataset.def;
    });
    if (mode.room) $('#odaBaslik').textContent = Names.room(mode.room, (W.roomById[mode.room] || {}).ad);
    kick();
  }
  document.querySelectorAll('.ray [data-tab]').forEach(b => b.addEventListener('click', () => setTab(b.dataset.tab)));
  document.querySelectorAll('.ray [data-oda]').forEach(b => {
    const r = W.roomById[b.dataset.oda]; if (r) b.style.setProperty('--c', lighten(r.ac, 0.28));
    b.addEventListener('click', () => railTik(b.dataset.oda));
  });
  document.querySelectorAll('.ray-grup [data-oda]').forEach(b => b.addEventListener('click', () => {
    document.querySelectorAll('.ray-grup[open]').forEach(g => { g.open = false; });
  }));
  document.addEventListener('click', e => {
    if (e.target.closest('.ray-grup')) return;
    document.querySelectorAll('.ray-grup[open]').forEach(g => { g.open = false; });
  });
  /* panel modu: geniş ekran + kart sütunu gizli (varsayılan). Aksi halde (telefon, klasik sütun) eski davranış: kart sütununda kaydır */
  const telefon = () => !window.matchMedia('(min-width: 900px)').matches;
  // telefonda menü tıklaması bilgi kartını alttan açılan panelde gösterir (önce yalnız kamera yakınlaşıyordu, kartlar sayfanın altında kalıyordu)
  const panelModu = () => telefon() || document.body.classList.contains('tam');
  /* sol menü panelinin açılmadan önceki görünümü: kapatınca (×, Esc, aynı menüye ikinci tıklama, boş alan) kamera oraya yumuşakça döner */
  let once = null, railIc = false;
  function anlik() {
    const c = target ? { cx: target.cx, cy: target.cy, z: target.z } : { cx: cam.cx, cy: cam.cy, z: cam.z }, f = fit();
    return { oda: mode.active ? mode.room : null, cam: c, fit: Math.abs(c.z - f.z) < 1e-3 && Math.abs(c.cx - f.cx) < 1 && Math.abs(c.cy - f.cy) < 1 };
  }
  function geriDon() {
    const o = once; once = null; if (!o) return false;
    if (o.oda == null) { donCam = o.fit ? null : o.cam; if (mode.active) goBuilding(); else setCam(o.fit ? fit() : o.cam, true); }
    else { if (!mode.active || mode.room !== o.oda) goRoom(o.oda); setCam(o.cam, true); }
    kick(); return true;
  }
  function panelKapat() {
    const had = kartAcik; railIc = true;
    try { if (had) kartKapat(true); if (Info.isOpen()) Info.close(); } finally { railIc = false; }
    if (!geriDon() && had && mode.active) setCam(interiorCam(mode.room), true);
    kick();
  }
  let kartAcik = null;                                           // { id, yer: [[yerTutucu, kart], …] }
  function kartKapat(sessiz) {
    if (!kartAcik) return;
    if (!railIc) once = null;
    kartAcik.yer.forEach(([ph, el]) => ph.replaceWith(el));
    kartAcik = null; solPx = 0; $('#kartPanel').hidden = true;
    if (!sessiz && mode.active) setCam(interiorCam(mode.room), true);
    kick();
  }
  function kartAc(id, kartlar, baslik) {
    kartKapat(true);
    if (Info.isOpen()) Info.close();
    if (O.Cekmece.isOpen()) O.Cekmece.close();
    const ic = $('#kpIc'), yer = [];
    kartlar.forEach(k => { const el = $('#' + k); if (!el) return; const ph = document.createComment(k); el.before(ph); ic.appendChild(el); yer.push([ph, el]); });
    kartAcik = { id, yer }; $('#kpBaslik').textContent = baslik; $('#kartPanel').hidden = false; ic.scrollTop = 0;
    solPx = telefon() ? 0 : $('#kartPanel').offsetWidth + 10;   // telefonda panel altta: kamera sola kaydırılmaz
    if (mode.active) setCam(interiorCam(mode.room), true);
    kick();
  }
  function railTik(id) {
    if (!panelModu()) { goRoom(id); goCard((PANEL_ESLE[id] || [])[0]); return; }
    const c = Info.current();
    if ((kartAcik && kartAcik.id === id) || (!PANEL_ESLE[id] && mode.room === id && c && c.type === 'oda' && c.id === id)) { panelKapat(); return; }   // aynı menüye ikinci tıklama
    const onceki = once || anlik();                              // panel açıkken başka menüye geçilirse ilk görünüm korunur
    railIc = true;
    try {
      goRoom(id);                                                // kamera doğrudan yeni odaya gider; önceki panel kapanır
      if (PANEL_ESLE[id]) kartAc(id, PANEL_ESLE[id], Names.room(id, (W.roomById[id] || {}).ad)); else Info.show({ type: 'oda', id });
    } finally { railIc = false; }
    once = onceki;
  }
  document.addEventListener('click', e => { if (once && e.target.closest && e.target.closest('#bKapat')) geriDon(); }, true);   // oda bilgi kutusunun × düğmesi
  function seritTik() {
    if (!panelModu()) { goCard('cGun'); return; }
    if (kartAcik && kartAcik.id === 'gun') panelKapat(); else kartAc('gun', ['cGun'], 'Günlük özet');
  }
  $('#gunSerit').addEventListener('click', seritTik);
  $('#kpKapat').addEventListener('click', () => panelKapat());
  window.matchMedia('(min-width: 900px)').addEventListener('change', () => kartKapat(true));
  function togglePanel() {
    const on = !document.body.classList.contains('tam');
    if (!on) kartKapat(true);                                    // klasik sütun açılınca kartlar yerine döner
    document.body.classList.toggle('tam', on);
    const b = $('#zPanel'); if (b) b.setAttribute('aria-pressed', on ? 'false' : 'true');   // basılı = klasik kart sütunu görünür
    setTimeout(() => { resize(); setCam(mode.active ? interiorCam(mode.room) : fit(), false); kick(); }, 60);
  }
  $('#zPanel').addEventListener('click', togglePanel);
  window.OFIS.setTab = setTab;

  /* ---------- ana döngü: olay yokken durur ---------- */
  let raf = 0, wakeT = 0, lastSync = performance.now(), fpsN = 0, fpsT = 0;
  function step(t) {
    const real = Math.max(0, (t - lastSync) / 1000); lastSync = t;
    const dt = Math.min(0.1, real);
    updateLight();
    Off.update(dt, real);                       // örnek olay zamanı gerçek süreyle ilerler (uyku dâhil)
    if (target) {
      const p = Math.min(1, (t - target.t0) / target.dur), e = p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2;
      cam.cx = target.from.cx + (target.cx - target.from.cx) * e; cam.cy = target.from.cy + (target.cy - target.from.cy) * e; cam.z = target.from.z * Math.pow(target.z / target.from.z, e);
      if (p >= 1) target = null;
    }
    animRoom(dt);
    clampCam();
    const p0 = performance.now(); drawScene(t); const p1 = performance.now(); blit(); const p2 = performance.now(); drawLabels(); const p3 = performance.now();
    const pf = window.OFIS.perf || (window.OFIS.perf = { scene: 0, blit: 0, lab: 0, kare: 0 }); pf.scene = pf.scene * 0.9 + (p1 - p0) * 0.1; pf.blit = pf.blit * 0.9 + (p2 - p1) * 0.1; pf.lab = pf.lab * 0.9 + (p3 - p2) * 0.1; pf.kare++;
    dirty = false;
    if (qs.get('perf') === '1') { const el = $('#perf'); if (el) { el.hidden = false; el.textContent = (window.OFIS.fps || 0) + ' fps · sahne ' + pf.scene.toFixed(1) + ' ms · aktarım ' + pf.blit.toFixed(1) + ' ms · kare ' + pf.kare; } }
    fpsN++; fpsT += dt; if (fpsT >= 1) { window.OFIS.fps = Math.round(fpsN / fpsT); fpsN = 0; fpsT = 0; }
  }
  const busyNow = () => (target || roomT !== roomTWant) ? 'raf' : ((O.Dialogue && O.Dialogue.busy()) || (O.Konusma && O.Konusma.busy()) || Off.busy() || false);
  function schedule() {
    if (raf) return;                                  // olay işleyicisi (emit) zaten bir kare istedi
    clearTimeout(wakeT); wakeT = 0;
    const b = reduced ? false : busyNow();
    if (reduced && ((O.Dialogue && O.Dialogue.busy()) || (O.Konusma && O.Konusma.busy()))) wakeT = setTimeout(kick, 2500);
    else if (b === 'raf') raf = requestAnimationFrame(tick);
    else if (b === 'slow') wakeT = setTimeout(kick, 190);
    else wakeT = setTimeout(kick, Math.min(Off.nextEventMs(), 30000));    // uyku: sıradaki örnek olayda (en geç 30 sn'de, ışık saati için) uyan
  }
  function tick(t) { raf = 0; step(t); schedule(); }
  function kick() { if (raf) return; clearTimeout(wakeT); raf = requestAnimationFrame(tick); }
  document.addEventListener('visibilitychange', () => { if (!document.hidden) kick(); });
  function applyMotion() {
    Off.reduced = reduced; document.body.classList.toggle('az-hareket', reduced);
    kick();
  }
  if (mq.addEventListener) mq.addEventListener('change', e => { reduced = e.matches; applyMotion(); });

  /* ---------- açılış ---------- */
  async function getJSON(url, req) {
    try { const r = await fetch(url, { cache: 'no-store' }); if (!r.ok) throw new Error('HTTP ' + r.status); return await r.json(); }
    catch (err) { if (req) throw err; return null; }
  }
  async function boot() {
    if (qs.get('saat')) {
      const m = /^(\d{1,2}):(\d{2})$/.exec(qs.get('saat'));
      if (m) {   // Türkiye saati (UTC+3) olarak yorumlanır — tarayıcının yerel saat dilimine bağlı değil
        const p = Off.trParts(new Date()), hedefUtc = Date.UTC(p.y, p.mo, p.day, +m[1] - 3, +m[2], 0, 0);
        Off.timeOffsetMs = hedefUtc - Date.now();
      }
    }
    const durumPar = qs.get('durum');
    let data;
    try {
      if (!durumPar) data = await O.Gercek.yukle((u, o) => fetch(u, o));            // varsayılan: veri dalındaki gerçek seçim + kapı durumu
      else data = await getJSON(durumPar === 'ornek' ? 'ornek_durum.json' : durumPar, true);   // ?durum=ornek → örnek veri; ?durum=URL → başka dosya
      if (data.surum !== 1) throw new Error('desteklenmeyen şema sürümü: ' + data.surum);
    }
    catch (err) { $('#hata').hidden = false; $('#hata').textContent = 'Veri okunamadı (' + err.message + '). Sahte veri gösterilmiyor.'; return; }
    const kadro = await getJSON('kadro.json'), replik = await getJSON('replikler.json');
    if (!kadro || !replik) { $('#hata').hidden = false; $('#hata').textContent = 'kadro.json ya da replikler.json okunamadı; varsayılan adlar ve replikler kullanılamıyor (veri etkilenmez).'; }
    Names.init(kadro || { odalar: {}, calisanlar: {}, nesneler: {} });
    W.build();
    Object.keys(data.oda_durum || {}).forEach(id => { if (data.oda_durum[id].gizli && W.roomById[id]) { W.roomById[id].out = true; W.roomById[id].gizli = true; } });   // gizli oda: etkileşim, etiket ve ışık dışı; yalnız sayısı panelde
    Off.init(data, { reduced: reduced, speed: parseFloat(qs.get('hiz')) || 1 });
    if (O.Dialogue) O.Dialogue.init(Off);
    window.OFIS.data = data;
    if (data.veri_kaynagi) {
      const badge = $('#veriKaynak');
      badge.hidden = false;
      badge.textContent = data.veri_kaynagi.etiket + (data.veri_kaynagi.snapshot_id ? ' · ' + data.veri_kaynagi.snapshot_id.slice(0, 12) : '');
      badge.classList.toggle('legacy', data.veri_kaynagi.tur === 'legacy');
    }
    updateLight(); resize();
    new ResizeObserver(() => { resize(); kick(); }).observe($('#ofisTuval'));
    Off.on(() => kick());                      // durum her değiştiğinde (dışarıdan gelen olay dâhil) döngü uyanır
    Info.init(Off, { invalidate: kick, onShow: sel => { if (O.Cekmece.isOpen()) O.Cekmece.close(); if (kartAcik && !(sel.type === 'oda')) kartKapat(true); if (sel.type !== 'oda' && !railIc) once = null; pinned = sel.type === 'person' ? sel.a : null; shiftFor(true); }, onClose: () => { pinned = null; shiftFor(false); } }, replik || undefined);
    O.Cekmece.init(Off, { invalidate: kick, beforeOpen: () => { once = null; if (Info.isOpen()) Info.close(); kartKapat(); },
      focusEvent: en => {                          // olaya tıkla: kamera o odaya gider, ilgili figür vurgulanır
        const room = W.roomById[en.oda];
        if (room && !room.out) goRoom(en.oda);
        Off.spot(en); if (window.matchMedia('(max-width: 899px)').matches) O.Cekmece.close();
        kick();
      } });
    if (O.Ses) O.Ses.init(Off, (kadro || {}).olay_turleri || {});
    Names.bindUI(); Names.onChange(refreshNames); refreshNames();
    if (O.Panel) O.Panel.init(Off, { focusRoom: id => goRoom(id) });
    const f = qs.get('oda'); if (f && W.roomById[f] && !W.roomById[f].out) { try { history.replaceState(null, '', location.pathname + '#oda/' + f); } catch (e) { /* adres çubuğu değiştirilemedi */ } }
    window.OFIS.ready = true;
    lastSync = performance.now();
    applyMotion();
    applyRoute({ instant: true });
  }
  window.OFIS.debug = { interest: interest, cam: cam, view: view, toView: toView, toWorld: toWorld, mode: mode, pick: pick, goRoom: goRoom, goBuilding: goBuilding, roomT: () => roomT, loop: () => ({ raf: !!raf, wake: !!wakeT }) };
  window.OFIS.invalidate = kick;
  window.OFIS.focusRoom = id => goRoom(id);
  boot();
})();
