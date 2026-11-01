/* Ofis · dünya: bina yerleşimi, odalar, mobilya, zemin, yürüme ağı. */
(function () {
  'use strict';
  const O = window.OFIS, S = O.S, HW = O.HW, HH = O.HH, C = O.C, shade = O.shade;
  const BX = 4, BY = 5, BW = 26, BH = 20, WW = 42, WH = 34;
  const OX = WH * HW, OY = 96;
  const CW = (WW + WH) * HW, CH = OY + (WW + WH) * HH + 44;
  const sx = (x, y) => OX + (x - y) * HW, sy = (x, y) => OY + (x + y) * HH;

  const ROOMS = [
    { id: 'makam', ad: 'Makam', x: 0, y: 0, w: 4, h: 4, fl: ['parquet', '#8a5a3a'], ac: '#7a4a32', solid: true },
    { id: 'sekreterlik', ad: 'Sekreterlik', x: 4, y: 0, w: 4, h: 4, fl: ['carpet', '#a9bba4'], ac: '#5f7d68' },
    { id: 'finans', ad: 'Finans', x: 8, y: 0, w: 4, h: 4, fl: ['tile', '#cfe6e0', '#b6d6cf'], ac: '#2a7f7a' },
    { id: 'haberlesme', ad: 'Haberleşme', x: 12, y: 0, w: 4, h: 4, fl: ['carpet', '#566d93'], ac: '#3e5a8c' },
    { id: 'risk', ad: 'Risk', x: 16, y: 0, w: 4, h: 4, fl: ['tile', '#efd5c4', '#e0bca3'], ac: '#c4553a' },
    { id: 'denetim', ad: 'Denetim', x: 20, y: 0, w: 3, h: 4, fl: ['grate', '#58626d'], ac: '#4c5a6a', solid: true },
    { id: 'arsiv', ad: 'Arşiv', x: 23, y: 0, w: 3, h: 4, fl: ['wood', '#b48a54'], ac: '#7b5a34', solid: true },
    { id: 'tarama', ad: 'Bilgi İşlem/IT', x: 0, y: 4, w: 5, h: 5, fl: ['carpet', '#a56f88'], ac: '#8a4f6c' },
    { id: 'cay', ad: 'Çay Ocağı', x: 5, y: 4, w: 3, h: 5, fl: ['fayans', '#eef4f1', '#4fa6a6'], ac: '#2f8c8c' },
    { id: 'lab', ad: 'LAB', x: 8, y: 4, w: 10, h: 5, fl: ['tile', '#e4f0ec', '#d1e4de'], ac: '#2f8a76' },
    { id: 'kontrol', ad: 'Yedekler', x: 18, y: 4, w: 8, h: 5, fl: ['carpet', '#5f8f93'], ac: '#3d6f78' },
    { id: 'bahce', ad: 'AVLU · HAVUZ', x: 0, y: 9, w: 26, h: 6, fl: ['grass', '#5e9c46'], ac: '#3f7a4a', out: true },
    { id: 'aday', wall: 18, ad: 'PAF Takım', x: 0, y: 15, w: 6, h: 5, fl: ['carpet', '#d9a06c'], ac: '#b7733c' },
    { id: 'oda', wall: 18, ad: 'İlk 11', x: 6, y: 15, w: 16, h: 5, fl: ['carpet', '#2f5d70'], ac: '#244a5c' },
    { id: 'kapi', wall: 18, ad: 'Kapı', x: 22, y: 15, w: 4, h: 5, fl: ['stone', '#bcc1c6'], ac: '#59636e' }
  ];
  const roomAt = {}; // "lx,ly" → oda
  ROOMS.forEach(r => { r.cx = r.x + r.w / 2; r.cy = r.y + r.h / 2; for (let i = 0; i < r.w; i++) for (let j = 0; j < r.h; j++) roomAt[(r.x + i) + ',' + (r.y + j)] = r; });
  const roomById = {}; ROOMS.forEach(r => (roomById[r.id] = r));

  // Etre-inspired isometric office staging, drawn from our own room geometry.
  // These small accent rugs make each doorway read as a deliberate threshold.
  // `oda` IDs remain the dashboard's stable programmatic room IDs.
  const ENTRY_MATS = [
    ['makam', 1, 3], ['sekreterlik', 5, 3], ['finans', 11, 3], ['haberlesme', 14, 3],
    ['risk', 17, 3], ['denetim', 21, 3], ['arsiv', 24, 3],
    ['tarama', 2, 8], ['cay', 6, 8], ['lab', 11, 8], ['kontrol', 24, 8],
    ['aday', 1, 15], ['oda', 9, 15], ['kapi', 23, 15]
  ];

  const W = (O.World = { BX, BY, BW, BH, WW, WH, OX, OY, CW, CH, sx, sy, ROOMS, roomById, roomAt, entryMats: ENTRY_MATS.map(([id, x, y]) => ({ id, x, y })), statics: [], seats: { lab: [], aday: [], oda: [], kontrol: [] }, staff: [], objects: [], tvs: {}, wins: [], leds: {}, screens: [], trees: [], lamps: [], boxSlots: [], doors: [] });

  /* ---------- yürüme ağı ---------- */
  const blocked = new Set(), wallH = new Set(), wallV = new Set();
  const inW = (x, y) => x >= 0 && y >= 0 && x < WW && y < WH;
  W.block = (x, y) => blocked.add(x + ',' + y);
  W.isBlocked = (x, y) => blocked.has(x + ',' + y);
  function canStep(x, y, nx, ny) {
    if (!inW(nx, ny)) return false;
    if (nx === x + 1 && wallV.has((x + 1) + ',' + y)) return false;
    if (nx === x - 1 && wallV.has(x + ',' + y)) return false;
    if (ny === y + 1 && wallH.has(x + ',' + (y + 1))) return false;
    if (ny === y - 1 && wallH.has(x + ',' + y)) return false;
    return true;
  }
  /* en kısa yol (BFS, 4 komşu). hedef ve başlangıç engelli olabilir (koltuk). */
  W.path = function (ax, ay, bx, by) {
    const key = (x, y) => y * WW + x, prev = new Map(), q = [[ax, ay]];
    prev.set(key(ax, ay), null);
    const D = [[1, 0], [0, 1], [-1, 0], [0, -1]];
    while (q.length) {
      const [x, y] = q.shift();
      if (x === bx && y === by) break;
      for (const d of D) {
        const nx = x + d[0], ny = y + d[1];
        if (prev.has(key(nx, ny)) || !canStep(x, y, nx, ny)) continue;
        if (blocked.has(nx + ',' + ny) && !(nx === bx && ny === by)) continue;
        prev.set(key(nx, ny), [x, y]); q.push([nx, ny]);
      }
    }
    if (!prev.has(key(bx, by))) return null;
    const out = []; let cur = [bx, by];
    while (cur) { out.push(cur); cur = prev.get(key(cur[0], cur[1])); }
    return out.reverse().slice(1);
  };

  /* ---------- statik varlıklar ---------- */
  function ent(k, px, py, s) { const e = { k: k, px: px, py: py, s: s }; W.statics.push(e); return e; }
  W.ent = ent;
  const putT = (s, tx, ty, ko) => ent(tx + ty + 1 + (ko || 0), sx(tx, ty), sy(tx, ty), s);
  const L = (s, lx, ly, o) => { o = o || {}; const e = putT(s, BX + lx, BY + ly, o.k); if (o.block !== false) W.block(BX + lx, BY + ly); if (o.obj) W.objects.push({ id: o.obj, room: o.obj.split('.')[0], e: e }); return e; };
  const OBJ = (id, e) => W.objects.push({ id: id, room: id.split('.')[0], e: e });
  W.putT = putT;

  /* ---------- zemin ---------- */
  const type = {}; // "x,y" → { k: tür, ... }
  function T(x, y, v) { type[x + ',' + y] = v; }
  const ROAD_X = WW - 3;                       // ana yol: sağ kenarda, y yönünde
  const LOT = { x0: BX + BW + 4, x1: ROAD_X - 1, y0: BY + 1, y1: BY + 11 }; // otopark: binanın kuzeydoğusunda, dik/düz sıralı
  // avlu (bahçe) yerleşimi: yerel koordinatlar (lx, ly); ly 9..14
  const POOL = { x0: 9, x1: 16, y0: 11, y1: 12 };
  const garden = { path: new Set(), pool: new Set() };
  (function gardenPlan() {
    const P = (x, y) => garden.path.add(x + ',' + y);
    for (let x = 8; x <= 17; x++) for (let y = 10; y <= 13; y++) if (!(x >= POOL.x0 && x <= POOL.x1 && y >= POOL.y0 && y <= POOL.y1)) P(x, y); // havuz kenar taşı
    for (let x = 0; x <= 7; x++) { P(x, 11); P(x, 12); }
    for (let x = 18; x <= 25; x++) { P(x, 11); P(x, 12); }
    [2, 6, 21, 24].forEach(x => { P(x, 9); P(x, 10); });
    [11, 14].forEach(x => P(x, 9));
    [1, 4, 23].forEach(x => { P(x, 13); P(x, 14); });
    [9, 15].forEach(x => P(x, 14));
    for (let x = POOL.x0; x <= POOL.x1; x++) for (let y = POOL.y0; y <= POOL.y1; y++) garden.pool.add(x + ',' + y);
  })();
  function buildTypes() {
    for (let x = 0; x < WW; x++) for (let y = 0; y < WH; y++) T(x, y, { k: 'grass' });
    // ana yol (sağ kenar, dikey)
    for (let x = ROAD_X; x < WW; x++) for (let y = 0; y < WH; y++) T(x, y, { k: 'asph', c: '#454a54', road: true });
    // otopark (kuzeydoğu): düz, birbirine dik duran park yerleri
    for (let x = LOT.x0; x <= LOT.x1; x++) for (let y = LOT.y0; y <= LOT.y1; y++) T(x, y, { k: 'asph', c: '#4d525c' });
    // giriş meydanı ve yaya yolu (doğu kapısı → yol)
    for (let x = BX + BW; x < BX + BW + 4; x++) for (let y = BY + 15; y <= BY + 18; y++) T(x, y, { k: 'stone', c: '#d7cdb6' });
    for (let x = BX + BW + 4; x < ROAD_X; x++) for (let y = BY + 16; y <= BY + 17; y++) T(x, y, { k: 'stone', c: '#d7cdb6' });
    // bina önü şeridi (güney)
    for (let x = BX - 1; x < BX + BW + 1; x++) T(x, BY + BH, { k: 'stone', c: '#d9d2c0' });
    // oda zeminleri
    ROOMS.forEach(r => {
      if (r.out) return;
      for (let i = 0; i < r.w; i++) for (let j = 0; j < r.h; j++) T(BX + r.x + i, BY + r.y + j, { k: r.fl[0], c: r.fl[1], c2: r.fl[2], room: r.id });
    });
    // Doorway rugs are floor tiles, so they remain in the isometric scene and
    // never affect the existing room hit testing or one-click card routing.
    ENTRY_MATS.forEach(([id, lx, ly]) => {
      const r = roomById[id];
      T(BX + lx, BY + ly, { k: 'carpet', c: r.ac, room: id, rug: true });
    });
    // avlu: çim + taş yollar + havuz
    for (let lx = 0; lx < BW; lx++) for (let ly = 9; ly <= 14; ly++) {
      const key = lx + ',' + ly, x = BX + lx, y = BY + ly;
      if (garden.pool.has(key)) T(x, y, { k: 'water', c: '#256f96', c2: '#4eb4d4', room: 'bahce', edge: { n: ly === POOL.y0, w: lx === POOL.x0 } });
      else if (garden.path.has(key)) T(x, y, { k: 'stone', c: '#e0d6bf', room: 'bahce' });
      else T(x, y, { k: 'grass', room: 'bahce' });
    }
    // halılar: Makam kırmızısı, Kapı paspası
    for (let i = 1; i <= 2; i++) for (let j = 1; j <= 3; j++) T(BX + i, BY + j, { k: 'carpet', c: '#9c3a34', rug: true, room: 'makam' });
    T(BX + 25, BY + 16, { k: 'carpet', c: '#4a525c', room: 'kapi', rug: true }); T(BX + 25, BY + 17, { k: 'carpet', c: '#4a525c', room: 'kapi', rug: true });
  }
  function buildGround() {
    const P = new O.Px(CW, CH);
    P.rect(0, 0, CW, CH, '#5e9c46');
    for (let s = 0; s < WW + WH; s++) for (let x = 0; x < WW; x++) {
      const y = s - x; if (y < 0 || y >= WH) continue;
      const t = type[x + ',' + y];
      const px = sx(x, y), py = sy(x, y);
      if (t.k === 'grass') drawGrass(P, px, py, x, y);
      else S.floorTile(P, px, py, x, y, t.k, t.c, t.c2, t.edge);
    }
    const wl = (a, b, c) => { const p = [sx(a[0], a[1]), sy(a[0], a[1])], q = [sx(b[0], b[1]), sy(b[0], b[1])]; P.line(p[0], p[1], q[0], q[1], c); };
    // otopark çizgileri: park yerleri 2 karo genişliğinde, kenara dik
    for (let y = LOT.y0; y <= LOT.y1 + 1; y += 2) wl([LOT.x0, y], [LOT.x0 + 3, y], '#e8eaee');
    wl([LOT.x0, LOT.y0], [LOT.x0, LOT.y1 + 1], '#e8eaee');
    // yol şeridi
    for (let y = 0; y < WH; y += 2) wl([ROAD_X + 1, y + 0.2], [ROAD_X + 1, y + 1.2], '#e4c64a');
    // yaya geçidi
    for (let k = 0; k < 6; k++) wl([ROAD_X, BY + 15.6 + k * 0.5], [ROAD_X + 3, BY + 15.6 + k * 0.5], '#e8eaee');
    // havuz kenarı: ince beyaz taş dudak
    wl([BX + POOL.x0, BY + POOL.y1 + 1], [BX + POOL.x1 + 1, BY + POOL.y1 + 1], '#fbf6e8'); wl([BX + POOL.x1 + 1, BY + POOL.y0], [BX + POOL.x1 + 1, BY + POOL.y1 + 1], '#fbf6e8');
    // arka duvar dibinde yumuşak gölge (avlu satırları hariç)
    const sh = (pts, a) => P.poly(pts.map(q => [sx(q[0], q[1]), sy(q[0], q[1])]), O.pk(20, 16, 30, a));
    [[0.12, 34], [0.28, 22], [0.48, 12]].forEach(b => {
      sh([[BX, BY], [BX + BW, BY], [BX + BW, BY + b[0]], [BX, BY + b[0]]], b[1] * 0.6);
      sh([[BX, BY], [BX + b[0], BY], [BX + b[0], BY + 9], [BX, BY + 9]], b[1] * 0.6);
      sh([[BX, BY + 15], [BX + b[0], BY + 15], [BX + b[0], BY + BH], [BX, BY + BH]], b[1] * 0.6);
    });
    // bina kaidesi: yalnız görünen (güney/doğu) yüzler
    const slabH = (x0, x1, y, col, edge) => { P.poly([[sx(x0, y), sy(x0, y)], [sx(x1, y), sy(x1, y)], [sx(x1, y), sy(x1, y) + 7], [sx(x0, y), sy(x0, y) + 7]], col); P.line(sx(x0, y), sy(x0, y) + 7, sx(x1, y), sy(x1, y) + 7, edge); };
    const slabV = (x, y0, y1, col, edge) => { P.poly([[sx(x, y1), sy(x, y1)], [sx(x, y0), sy(x, y0)], [sx(x, y0), sy(x, y0) + 7], [sx(x, y1), sy(x, y1) + 7]], col); P.line(sx(x, y1), sy(x, y1) + 7, sx(x, y0), sy(x, y0) + 7, edge); };
    slabH(BX, BX + BW, BY + 9, '#aab3b9', '#6d767c');          // kuzey kanat, avluya bakan yüz
    slabH(BX, BX + BW, BY + BH, '#b2bcc2', '#6d767c');          // güney kanat, ön yüz
    slabV(BX + BW, BY, BY + 9, '#939ea6', '#6d767c');
    slabV(BX + BW, BY + 15, BY + BH, '#939ea6', '#6d767c');
    W.ground = P.flush();
  }
  function drawGrass(P, px, py, x, y) { S.floorGrass(P, px, py, x, y); }

  /* ---------- duvar / bölme ---------- */
  function buildWalls() {
    const accAt = (lx, ly) => (roomAt[lx + ',' + ly] || { ac: '#6a5a40' }).ac;
    const decoH = { 0: 'pic', 1: 'win', 2: 'win', 3: 'pic', 4: 'win', 5: 'win', 11: 'pic', 15: 'win', 16: 'win', 19: 'pic' };
    const decoV = { 3: 'win', 4: 'win', 7: 'win', 8: 'pic', 15: 'win', 16: 'pic', 19: 'win' };
    const garden = ly => ly >= 9 && ly <= 14;
    ent(BX + BY - 0.4, sx(BX, BY), sy(BX, BY), S.wallCorner('#7a4a32')).wall = ['makam'];
    for (let lx = 0; lx < BW; lx++) {
      const d = decoH[lx] || '';
      ent(BX + lx + BY + 0.4, sx(BX + lx, BY), sy(BX + lx, BY), S.wallBH(accAt(lx, 0), d, lx)).wall = [roomAt[lx + ',0'].id];
      if (d === 'win') W.wins.push({ side: 'L', e: ent(BX + lx + BY + 0.41, sx(BX + lx, BY), sy(BX + lx, BY), null) });
    }
    for (let ly = 0; ly < BH; ly++) {
      wallV.add(BX + ',' + (BY + ly));
      if (garden(ly)) continue;               // avluda batı kenarı açık (yalnız yürüme çiti)
      const d = decoV[ly] || '';
      ent(BX + BY + ly + 0.4, sx(BX, BY + ly), sy(BX, BY + ly), S.wallBV(accAt(0, ly), d, ly + 3)).wall = [roomAt['0,' + ly].id];
      if (d === 'win') W.wins.push({ side: 'R', e: ent(BX + BY + ly + 0.41, sx(BX, BY + ly), sy(BX, BY + ly), null) });
    }
    for (let lx = 0; lx < BW; lx++) wallH.add((BX + lx) + ',' + BY);
    // ön ve sağ alçak duvar (kesit); girişte boşluk
    for (let lx = 0; lx < BW; lx++) { ent(BX + lx + BY + BH + 0.57, sx(BX + lx, BY + BH - 1), sy(BX + lx, BY + BH - 1), S.curbH()); wallH.add((BX + lx) + ',' + (BY + BH)); }
    for (let ly = 0; ly < BH; ly++) {
      if (ly === 16 || ly === 17) continue;
      if (garden(ly)) ent(BX + BW + BY + ly + 0.5, sx(BX + BW, BY + ly), sy(BX + BW, BY + ly), S.partV('glass', '#3f7a4a'));   // avlunun doğu ucu cam galeri duvarı
      else ent(BX + BW + BY + ly + 0.57, sx(BX + BW - 1, BY + ly), sy(BX + BW - 1, BY + ly), S.curbV());
      wallV.add((BX + BW) + ',' + (BY + ly));
    }
    // giriş kapı sütunları
    ent(BX + BW + BY + 16 - 0.06 + 0.57, sx(BX + BW - 1, BY + 16), sy(BX + BW - 1, BY + 16), S.doorPost());
    ent(BX + BW + BY + 18 - 0.06 + 0.57, sx(BX + BW - 1, BY + 18), sy(BX + BW - 1, BY + 18), S.doorPost());

    /* iç bölmeler. kapılar (boşluklar) hâlinde. Avluya bakan yüzler cam. */
    const kind = (a, b) => ((a && a.solid) || (b && b.solid)) ? 'solid' : 'glass';
    const ra = (lx, ly) => roomAt[lx + ',' + ly];
    const gapsH = { 4: [1, 5, 11, 14, 17, 21, 24], 9: [2, 6, 11, 14, 21, 24], 15: [1, 4, 9, 15, 23] };
    W.gapsH = gapsH;
    Object.keys(gapsH).forEach(yy => {
      const y = +yy;
      for (let lx = 0; lx < BW; lx++) {
        if (gapsH[y].indexOf(lx) >= 0) continue;
        const a = ra(lx, y - 1), b = ra(lx, y); if (a === b) continue;
        const k = (a && a.out) || (b && b.out) ? 'glass' : kind(a, b), room = a && a.out ? b : b && b.out ? a : b;
        const pe = ent(BX + lx + BY + y + 0.5, sx(BX + lx, BY + y), sy(BX + lx, BY + y), S.partH(k, (room && room.ac) || '#777')); if (k === 'solid') pe.wall = [a.id, b.id];
        wallH.add((BX + lx) + ',' + (BY + y));
      }
    });
    const gapsV = {};
    gapsV[6 + ',' + 17] = 1; gapsV[22 + ',' + 17] = 1; gapsV[8 + ',' + 6] = 1; gapsV[18 + ',' + 6] = 1;
    W.gapsV = gapsV;
    for (let lx = 1; lx < BW; lx++) for (let ly = 0; ly < BH; ly++) {
      const a = ra(lx - 1, ly), b = ra(lx, ly); if (!a || !b || a === b) continue;
      if (a.out || b.out) continue;
      if (gapsV[lx + ',' + ly]) continue;
      const pv = ent(BX + lx + BY + ly + 0.5, sx(BX + lx, BY + ly), sy(BX + lx, BY + ly), S.partV(kind(a, b), b.ac)); if (kind(a, b) === 'solid') pv.wall = [a.id, b.id];
      wallV.add((BX + lx) + ',' + (BY + ly));
    }
  }

  /* ---------- yerleşim ---------- */
  const SEATD = {}; // masa anahtarı → ekran girişi
  function pod(room, lx, deskY, seatY, wood, seedBase, opt) {
    opt = opt || {};
    const dsk = L(S.desk('y', wood || '#b98a55', seedBase + lx), lx, deskY);
    const scr = ent(BX + lx + BY + deskY + 1.02, sx(BX + lx, BY + deskY), sy(BX + lx, BY + deskY), null);
    const seat = { room: room, lx: lx, ly: seatY, tx: BX + lx, ty: BY + seatY, scr: scr, deskE: dsk, occ: null, kind: opt.kind };
    W.block(seat.tx, seat.ty);
    seat.chair = ent(seat.tx + seat.ty + 1.2, sx(seat.tx, seat.ty) , sy(seat.tx, seat.ty) + HH, null);
    seat.chair.s = null;
    seat.chairLook = O.look(seedBase * 7 + lx * 3 + seatY).chair;
    W.screens.push({ scr: scr, dir: 'y' });
    return seat;
  }
  W.seatPos = (seat) => ({ x: sx(seat.tx, seat.ty), y: sy(seat.tx, seat.ty) + HH });

  function buildFurniture() {
    const seats = W.seats;
    /* --- MAKAM --- */
    L(S.bigDesk('a'), 1, 1, { obj: 'makam.masa' }); L(S.bigDesk('b'), 2, 1, { obj: 'makam.masa' });
    L(S.shelf('x', 'tall', 11), 0, 1, { obj: 'makam.kitaplik' }); L(S.shelf('x', 'tall', 12), 0, 2, { obj: 'makam.kitaplik' });
    L(S.globe(), 3, 0, { obj: 'makam.kure' }); L(S.plant('tall'), 3, 3); L(S.plant('small'), 0, 3); L(S.floorLamp(), 3, 2);
    W.staff.push({ id: 'makam', room: 'makam', tx: BX + 1, ty: BY, pose: 'sitF', look: O.look(901, 'makam', { acc: 'tie', shirt: '#2c3342', pants: '#1f2430', hs: 'short', hair: '#d9d4c8', chair: '#7a2f2f', skin: '#e5b88e' }), blockSeat: true });
    W.block(BX + 1, BY); W.block(BX + 2, BY);
    W.emptyChairs = [{ tx: BX + 1, ty: BY + 2, c: '#7a2f2f' }, { tx: BX + 2, ty: BY + 2, c: '#7a2f2f' }];
    /* --- SEKRETERLİK --- */
    L(S.shelf('y', 'tall', 21), 6, 0, { obj: 'sekreterlik.kural_rafi' }); L(S.shelf('y', 'tall', 22), 7, 0, { obj: 'sekreterlik.kural_rafi' }); L(S.shelf('y', 'low', 23), 4, 0);
    const sk = pod('sekreterlik', 5, 1, 2, '#c9a36a', 30, { kind: 'staff' });
    sk.scr.s = S.screen('y', 'staff');
    W.staff.push({ id: 'sekreter', room: 'sekreterlik', seat: sk, pose: 'sit', look: O.look(911, 'sek', { shirt: '#c05a8a', hs: 'bun', hair: '#4a3322', acc: '' }) });
    L(S.safe(), 7, 1, { obj: 'sekreterlik.onkayit_kasasi' }); L(S.printer(), 7, 2, { obj: 'sekreterlik.yazici' }); L(S.plant('tall'), 4, 3); L(S.cabinet('y'), 7, 3, { obj: 'sekreterlik.dosya_dolabi' }); L(S.box(3), 4, 2);
    /* --- FİNANS --- */
    L(S.safe(), 8, 0, { obj: 'finans.kasa' }); L(S.coins(), 11, 1, { obj: 'finans.para' }); OBJ('finans.tv', W.tvs.finans.e); OBJ('haberlesme.tv', W.tvs.haber.e); OBJ('risk.tv', W.tvs.risk.e); OBJ('tarama.tv', W.tvs.tarama.e); OBJ('aday.tv', W.tvs.aday.e);
    const f1 = pod('finans', 10, 1, 2, '#d8d2c2', 40, { kind: 'staff' }); f1.scr.s = S.screen('y', 'staff');
    const f2 = pod('finans', 8, 2, 3, '#d8d2c2', 41, { kind: 'staff' }); f2.scr.s = S.screen('y', 'staff');
    W.staff.push({ id: 'finans1', room: 'finans', seat: f1, pose: 'sit', look: O.look(921, 'fin', { acc: 'visor', shirt: '#e9e4d2' }) });
    W.staff.push({ id: 'finans2', room: 'finans', seat: f2, pose: 'sit', look: O.look(922, 'fin', { shirt: '#3b82c4', hs: 'long' }) });
    L(S.plant('tall'), 11, 2);
    /* --- HABERLEŞME --- */
    const h1 = pod('haberlesme', 13, 1, 2, '#9aa5b4', 50, { kind: 'staff' }); h1.scr.s = S.screen('y', 'staff');
    const h2 = pod('haberlesme', 15, 1, 2, '#9aa5b4', 51, { kind: 'staff' }); h2.scr.s = S.screen('y', 'staff');
    W.staff.push({ id: 'haber1', room: 'haberlesme', seat: h1, pose: 'sit', look: O.look(931, 'hab', { acc: 'headset', shirt: '#3b6fb4' }) });
    W.staff.push({ id: 'haber2', room: 'haberlesme', seat: h2, pose: 'sit', look: O.look(932, 'hab', { acc: 'headset', shirt: '#2f9aa8', hs: 'long' }) });
    L(S.mailbox(), 12, 3, { obj: 'haberlesme.posta' }); W.zarfE = putT(null, BX + 15, BY + 0); W.block(BX + 15, BY + 0); OBJ('haberlesme.zarf_rafi', W.zarfE);   // zarf rafı: bugünkü bildirimler (dinamik) L(S.plant('small'), 15, 3); L(S.cooler(), 14, 1, { obj: 'haberlesme.sebil' }); L(S.box(1), 12, 1, { obj: 'haberlesme.koli' }); L(S.box(2), 12, 2, { obj: 'haberlesme.koli' });
    W.mailboxLocal = [12, 3];
    /* --- RİSK --- */
    const r1 = pod('risk', 17, 1, 2, '#c9b9a0', 60, { kind: 'staff' }); r1.scr.s = S.screen('y', 'staff');
    const r2 = pod('risk', 19, 1, 2, '#c9b9a0', 61, { kind: 'staff' }); r2.scr.s = S.screen('y', 'staff');
    W.staff.push({ id: 'risk1', room: 'risk', seat: r1, pose: 'sit', look: O.look(941, 'risk', { acc: 'vest', shirt: '#f28c28' }) });
    W.staff.push({ id: 'risk2', room: 'risk', seat: r2, pose: 'sit', look: O.look(942, 'risk', { shirt: '#b5472f', acc: 'glasses' }) });
    L(S.beacon(), 16, 0, { obj: 'risk.fener' }); W.beaconE = ent(BX + 16 + BY + 0 + 1.02, sx(BX + 16, BY), sy(BX + 16, BY), null);
    L(S.cabinet('y'), 16, 3, { obj: 'risk.dolap' }); L(S.plant('small'), 19, 3);
    W.alarmE = putT(null, BX + 18, BY + 3); W.block(BX + 18, BY + 3); OBJ('risk.alarm', W.alarmE);   // alarm paneli: tavan doluluğu (dinamik sprite, office.js)
    /* --- DENETİM --- */
    ['20', '21', '22'].forEach((x, i) => { L(S.rack('y'), +x, 0, { obj: ['denetim.sunucu1', 'denetim.sunucu2', 'denetim.sunucu3'][i] }); W.leds['rack' + x] = ent(BX + +x + BY + 1.02, sx(BX + +x, BY), sy(BX + +x, BY), null); });
    const d1 = pod('denetim', 21, 2, 3, '#aeb8c6', 70, { kind: 'staff' }); d1.scr.s = S.screen('y', 'staff');
    W.staff.push({ id: 'denetim', room: 'denetim', seat: d1, pose: 'sit', look: O.look(951, 'den', { acc: 'glasses', shirt: '#6b7a8f' }) });
    L(S.cabinet('y'), 22, 2, { obj: 'denetim.dolap' }); L(S.plant('small'), 20, 3, { block: false });
    /* --- ARŞİV --- */
    ['23', '24', '25'].forEach((x, i) => L(S.shelf('y', 'tall', 31 + i), +x, 0, { obj: ['arsiv.raf1', 'arsiv.raf2', 'arsiv.raf3'][i] }));
    L(S.shelf('y', 'arsiv', 36), 24, 2, { obj: 'arsiv.dolap' });
    L(S.box(1), 25, 2, { obj: 'arsiv.kutu' }); W.boxSlots = [[25, 3], [25, 3], [25, 3], [25, 3], [25, 3]];
    W.block(BX + 25, BY + 3);
    W.staff.push({ id: 'arsivci', room: 'arsiv', tx: BX + 24, ty: BY + 3, pose: 'stand', dir: 'u', look: O.look(961, 'ars', { shirt: '#9a6b3b', acc: 'glasses', hs: 'bald' }) });
    /* --- TARAMA --- */
    const t1 = pod('tarama', 2, 5, 6, '#b9a9d0', 80, { kind: 'staff' }); t1.scr.s = S.screen('y', 'staff');
    const t2 = pod('tarama', 4, 5, 6, '#b9a9d0', 81, { kind: 'staff' }); t2.scr.s = S.screen('y', 'staff');
    W.staff.push({ id: 'tarama1', room: 'tarama', seat: t1, pose: 'sit', look: O.look(971, 'tar', { shirt: '#6a4fa0', hs: 'short' }) });
    W.staff.push({ id: 'tarama2', room: 'tarama', seat: t2, pose: 'sit', look: O.look(972, 'tar', { shirt: '#2f9aa8', hs: 'long' }) });
    L(S.printer(), 0, 7, { obj: 'tarama.yazici1' }); L(S.printer(), 0, 8, { obj: 'tarama.yazici2' }); L(S.plant('tall'), 4, 8); L(S.plant('small'), 0, 4);
    /* --- ÇAY OCAĞI --- (tezgâh arka sırada; önünü kapatacak uzun nesne yok, semaver görünür) */
    L(S.counter('u', 'tea'), 6, 4, { obj: 'cay.semaver' }); L(S.counter('u', ''), 7, 4); L(S.fridge('y'), 7, 8, { obj: 'cay.buzdolabi' });
    L(S.table('round'), 6, 7, { obj: 'cay.masa' }); L(S.stool(), 5, 7); L(S.plant('small'), 5, 6); L(S.vending(), 5, 8, { obj: 'cay.otomat' });
    W.staff.push({ id: 'cayci', room: 'cay', tx: BX + 5, ty: BY + 5, pose: 'stand', dir: 'u', look: O.look(981, 'cay', { acc: 'apron', shirt: '#d9d4c8', hs: 'bun', hair: '#2b2118' }), cayci: true });
    /* --- LAB --- (koltuk sütunları arasında boş koridor sütunları: her koltuğa ulaşılır) */
    [9, 10, 12, 13, 15, 16].forEach((x, i) => { seats.lab.push(pod('lab', x, 4, 5, '#ccd6e0', 100 + i)); seats.lab.push(pod('lab', x, 7, 8, '#ccd6e0', 120 + i)); });
    L(S.cooler(), 8, 4, { obj: 'lab.sebil' }); L(S.plant('tall'), 12, 6); L(S.cabinet('y'), 15, 6, { obj: 'lab.kayit_dolabi' }); L(S.board(), 17, 5, { obj: 'lab.pano' }); L(S.plant('small'), 13, 6);   // kapı boşlukları (y=4, x=11/14/17) açık
    /* --- KONTROL --- */
    [19, 20, 22, 23, 25].forEach((x, i) => { seats.kontrol.push(pod('kontrol', x, 4, 5, '#b9c4d2', 140 + i)); seats.kontrol.push(pod('kontrol', x, 7, 8, '#b9c4d2', 160 + i)); });
    L(S.dice(), 18, 4, { obj: 'kontrol.zar' }); L(S.plant('tall'), 25, 6, { obj: 'kontrol.bitki1' });   // kapı boşlukları (21 ve 24, y=4) açık kalır
    seats.kontrol.forEach(sk => W.objects.push({ id: 'kontrol.masa', room: 'kontrol', e: sk.deskE }));
    /* --- ADAY --- */
    [0, 2, 3, 5].forEach((x, i) => { seats.aday.push(pod('aday', x, 15, 16, '#d9b78e', 200 + i)); seats.aday.push(pod('aday', x, 18, 19, '#d9b78e', 220 + i)); });
    L(S.plant('tall'), 0, 17, { obj: 'aday.bitki1' });
    seats.aday.forEach(sk => W.objects.push({ id: 'aday.masa', room: 'aday', e: sk.deskE }));
    /* --- ODA --- */
    [7, 8, 10, 11, 13, 14, 16, 17, 19, 20].forEach((x, i) => { seats.oda.push(pod('oda', x, 15, 16, '#b4c2cc', 300 + i)); seats.oda.push(pod('oda', x, 18, 19, '#b4c2cc', 330 + i)); });
    seats.oda.forEach(sk => W.objects.push({ id: 'oda.masa', room: 'oda', e: sk.deskE }));
    [6, 12, 18, 21].forEach((x, i) => L(S.plant('tall'), x, 15, i < 3 ? { obj: ['oda.bitki1', 'oda.bitki2', 'oda.bitki3'][i] } : {}));
    /* --- KAPI --- */
    L(S.turnstile(), 24, 16, { obj: 'kapi.turnike1' }); L(S.turnstile(), 24, 18, { obj: 'kapi.turnike2' });
    const g = pod('kapi', 22, 18, 19, '#9aa5b4', 400, { kind: 'staff' }); g.scr.s = S.screen('y', 'staff');
    W.staff.push({ id: 'kapici', room: 'kapi', seat: g, pose: 'sit', look: O.look(991, 'kapi', { acc: 'cap', shirt: '#1f3a6e' }) });
    L(S.plant('tall'), 22, 15); L(S.plant('tall'), 25, 15); L(S.plant('small'), 25, 19); L(S.bench('u'), 23, 19, { obj: 'kapi.bank' });
  }
  W.sitDir = 'u';

  /* ---------- çevre ---------- */
  function buildOutside() {
    const taken = new Set();
    const ok = (x, y) => { const t = type[x + ',' + y]; return t && t.k === 'grass' && !taken.has(x + ',' + y); };
    const r = O.rng(77);
    const take = (x, y) => { taken.add(x + ',' + y); W.block(x, y); };
    // otopark: kuzeydoğuda, kenara dik duran düz sıra (açılı park yok)
    const cols = ['#d4553b', '#3b82c4', '#e0a93a', '#3aa17a', '#8a63c9', '#e8e4da', '#2c3342', '#d86b8f', '#6b7a8f', '#c0683a'];
    for (let y = LOT.y0; y <= LOT.y1; y += 2) {
      if (r() < 0.38) continue;
      const c = cols[Math.floor(r() * cols.length)], x = LOT.x0 + 1;
      ent(x + y + 2.4, sx(x, y), sy(x, y), S.car(c, y * 7 + 3));
    }
    // giriş meydanı: çiçek tavaları ve tabela
    [[BX + BW, BY + 14, '#ff8fa8'], [BX + BW + 2, BY + 14, '#ffd24a'], [BX + BW, BY + 19, '#ffffff'], [BX + BW + 2, BY + 19, '#f5a3c0']].forEach((q, i) => {
      if (!ok(q[0], q[1])) return; ent(q[0] + q[1] + 1, sx(q[0], q[1]), sy(q[0], q[1]) + HH + 2, S.bush(40 + i, q[2])); take(q[0], q[1]);
    });
    OBJ('kapi.tabela', ent(BX + BW + 3 + BY + 19 + 1, sx(BX + BW + 3, BY + 19), sy(BX + BW + 3, BY + 19) + HH, S.signpost())); take(BX + BW + 3, BY + 19);
    // park lambaları: otopark kenarı ve meydan
    [[LOT.x0 - 1, LOT.y0 + 2], [LOT.x0 - 1, LOT.y1 - 1], [BX + BW + 1, BY + 20]].forEach(q => { const e = ent(q[0] + q[1] + 1.1, sx(q[0], q[1]), sy(q[0], q[1]) + HH, S.lamp()); W.lamps.push(e); });
    // çalılar bina önünde (güney)
    for (let lx = 0; lx < 26; lx++) {
      const x = BX + lx, y = BY + BH + 1;
      if (r() < 0.7 && ok(x, y)) { ent(x + y + 1, sx(x, y), sy(x, y) + HH + 2, S.bush(lx, r() < 0.5 ? ['#ff8fa8', '#ffd24a', '#ffffff'][lx % 3] : null)); take(x, y); }
    }
    buildGarden(take);
    // ağaçlar
    const kinds = ['g', 'g', 'o', 'pine', 'g', 'y', 'pine', 'o'];
    for (let x = 0; x < ROAD_X; x++) for (let y = 0; y < WH - 1; y++) {
      const lx = x - BX, ly = y - BY;
      if (!ok(x, y)) continue;
      if (lx >= -2 && lx <= BW + 2 && ly >= -2 && ly <= BH + 3) continue;               // bina çevresi boş
      if (lx > BW - 2 && ly >= 12 && ly <= 22 && x < ROAD_X) continue;                   // giriş meydanı ve yolu
      if (x >= LOT.x0 - 2 && x <= LOT.x1 + 1 && y >= LOT.y0 - 2 && y <= LOT.y1 + 2) continue;
      const d = O.h2(x, y, 55), edge = (lx < -1 || ly < -1 || ly > BH + 1);
      if (d < (edge ? 0.17 : 0.06) && O.h2(x, y, 56) > 0.2) {
        if (taken.has((x - 1) + ',' + y) || taken.has(x + ',' + (y - 1)) || taken.has((x - 1) + ',' + (y - 1))) continue;
        const k = kinds[Math.floor(O.h2(x, y, 57) * kinds.length)];
        ent(x + y + 1, sx(x, y), sy(x, y) + HH, S.tree(k, x * 31 + y)); take(x, y);
      }
    }
  }

  /* avlu: çim, çiçek tarhı, havuz çevresi, şezlong, bank, lamba. Yürünebilir yalnız taş yollar. */
  function buildGarden(take) {
    const lawn = (lx, ly) => { const t = type[(BX + lx) + ',' + (BY + ly)]; return t && t.k === 'grass'; };
    const fl = ['#ff8fa8', '#ffd24a', '#ffffff', '#f5a3c0', '#ffb366'];
    // şezlong güvertesi (havuzun kuzeydoğusu)
    for (let lx = 18; lx <= 20; lx++) for (let ly = 9; ly <= 10; ly++) T(BX + lx, BY + ly, { k: 'deck', c: '#c9a06a', room: 'bahce' });
    const reserved = new Set();
    const put = (lx, ly, spr, dy, ko) => { const x = BX + lx, y = BY + ly; ent(x + y + 1 + (ko || 0), sx(x, y), sy(x, y) + (dy || 0), spr); reserved.add(lx + ',' + ly); };
    put(18, 10, S.lounger('a'), 0); put(19, 10, S.lounger('b'), 0); put(20, 9, S.parasol(), 0, 0.2);
    put(4, 10, S.bench('u'), 0); put(22, 13, S.bench('y'), 0);
    [[7, 10], [18, 13], [7, 13], [25, 10]].forEach(q => { const x = BX + q[0], y = BY + q[1]; const e = ent(x + y + 1.1, sx(x, y), sy(x, y) + HH, S.lamp()); W.lamps.push(e); reserved.add(q[0] + ',' + q[1]); });
    for (let lx = 0; lx < BW; lx++) for (let ly = 9; ly <= 14; ly++) {
      const x = BX + lx, y = BY + ly, key = lx + ',' + ly, t = type[x + ',' + y];
      if (garden.pool.has(key) || garden.path.has(key)) continue;
      W.block(x, y);                                   // yürüme ağı yalnız taş yolları kullanır
      if (reserved.has(key) || (t && t.k === 'deck')) continue;
      const h = O.h2(x, y, 321);
      const cornerTree = (lx <= 0 || lx >= 25) && (ly === 9 || ly === 14);
      if (cornerTree) ent(x + y + 1, sx(x, y), sy(x, y) + HH, S.tree(h < 0.5 ? 'g' : 'o', x * 17 + y));
      else if (h < 0.88) ent(x + y + 1, sx(x, y), sy(x, y) + HH + 2, S.bush(lx * 3 + ly, h < 0.6 ? fl[Math.floor(h * 25) % fl.length] : null));
    }
    // batı kenarında çit hattı (yürüme ağı dışında kalsın)
    for (let ly = 9; ly <= 14; ly++) { const x = BX - 1, y = BY + ly; ent(x + y + 1, sx(x, y), sy(x, y) + HH + 2, S.bush(60 + ly, null)); take(x, y); }
  }

  function buildTVs() {
    const tv = (id, side, lx, ly, span) => {
      const x = BX + lx, y = BY + ly, k = side === 'L' ? (x + span - 1) + y + 0.43 : x + (y + span - 1) + 0.43;
      W.tvs[id] = { side: side, span: span, e: ent(k, sx(x, y), sy(x, y), null) };
    };
    tv('finans', 'L', 9, 0, 2); tv('haber', 'L', 12, 0, 3); tv('risk', 'L', 17, 0, 2); tv('tarama', 'R', 0, 5, 2); tv('aday', 'R', 0, 17, 2);
  }
  W.resort = function () { W.statics.sort((a, b) => a.k - b.k); };
  W.build = function () {
    buildTypes(); buildGround(); buildWalls(); buildTVs(); buildFurniture(); buildOutside();
    W.resort();
  };
  W.poolPoly = function () {
    const a = [BX + POOL.x0, BY + POOL.y0], b = [BX + POOL.x1 + 1, BY + POOL.y1 + 1], pts = [[sx(a[0], a[1]), sy(a[0], a[1])], [sx(b[0], a[1]), sy(b[0], a[1])], [sx(b[0], b[1]), sy(b[0], b[1])], [sx(a[0], b[1]), sy(a[0], b[1])]];
    return { pts: pts, cx: (pts[0][0] + pts[2][0]) / 2, cy: (pts[0][1] + pts[2][1]) / 2, r: (pts[1][0] - pts[3][0]) * 0.6 };
  };
  W.localToWorld = (lx, ly) => [BX + lx, BY + ly];
  W.sign = function (r) { if (r.id === 'bahce') { const q = W.poolPoly(); return { x: q.cx, y: q.cy - 4 }; } const yy = r.y + (r.y === 0 ? 0.9 : 0.5); return { x: sx(BX + r.cx, BY + yy), y: sy(BX + r.cx, BY + yy) - (r.y === 0 ? 40 : r.id === 'cay' ? 46 : 26) }; };
  /* oda çokgeni (zemin) ekran noktaları */
  W.roomPoly = function (r) { const a = [BX + r.x, BY + r.y], b = [BX + r.x + r.w, BY + r.y + r.h]; return [[sx(a[0], a[1]), sy(a[0], a[1])], [sx(b[0], a[1]), sy(b[0], a[1])], [sx(b[0], b[1]), sy(b[0], b[1])], [sx(a[0], b[1]), sy(a[0], b[1])]]; };
})();
