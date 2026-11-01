/* Ofis · birimler arası iletişim işaretleri: zarf, not kâğıdı, ok. Her işaret bir olaydan doğar (eşleme tablosu: OLAYLAR.md).
   Olay yoksa işaret yoktur. Rakam ya da renk performans anlamı taşımaz (ok rengi: aqua = bilgi, kayısı = uyarı). */
(function () {
  'use strict';
  const O = window.OFIS, W = O.World, Off = O.Office, HH = O.HH;
  const BX = W.BX, BY = W.BY;
  const marks = [];           // uçuşan işaretler (kısa ömürlü)
  const notes = {};           // kalıcı not/bayrak: trader id → { e, shown }
  let seq = 0;
  const MAX_MARKS = 8;
  const now = () => performance.now();
  const prune = () => { const t = now(); for (let i = marks.length - 1; i >= 0; i--) if (t - marks[i].t0 >= marks[i].dur) marks.splice(i, 1); };
  Off.marks = () => { prune(); return marks.slice(); };
  Off.notes = () => notes;

  /* ---- konumlar (ekran pikseli, dünya tuvali) ---- */
  const roomPt = id => {
    const r = W.roomById[id]; if (!r) return null;
    const p = W.roomPoly(r); return { x: (p[0][0] + p[2][0]) / 2, y: (p[0][1] + p[2][1]) / 2 - 8 };
  };
  const tilePt = (tx, ty) => ({ x: W.sx(tx + 0.5, ty + 0.5), y: W.sy(tx + 0.5, ty + 0.5) - 8 });
  function pos(id, st) {
    if (id === 'out') { const m = tilePt(BX + W.mailboxLocal[0], BY + W.mailboxLocal[1]); return { x: m.x + 130, y: m.y - 62 }; }
    if (id === 'exit') return tilePt(BX + W.BW + 3, BY + 17);
    if (id === 'mailbox') { const m = tilePt(BX + W.mailboxLocal[0], BY + W.mailboxLocal[1]); return { x: m.x, y: m.y - 14 }; }
    if (id && id.indexOf('seat:') === 0) { const a = st.actorById[id.slice(5)]; if (a && a.sx != null) return { x: a.sx, y: a.sy - 18 }; const t = st.traders[id.slice(5)]; return roomPt((t && t.kat) || 'oda'); }
    return roomPt(id);
  }
  const katOf = (st, tid) => { const a = st.actorById[tid], k = a ? a.kat : (st.traders[tid] || {}).kat; return k === 'lab' || k === 'aday' || k === 'oda' || k === 'kontrol' ? k : 'oda'; };
  const COL = { bilgi: '#46d3c2', uyari: '#ffb86b' };

  function addMark(m, st) {
    prune();
    if (marks.length >= MAX_MARKS) return;           // olay yağmurunda fazla işaret çizilmez (durum yine doğrudur)
    const a = pos(m.a, st), b = pos(m.b, st); if (!a || !b) return;
    marks.push({ id: 'm' + (++seq), kind: m.k, a: a, b: b, t0: now(), dur: Off.reduced ? 3200 : 3600, color: m.warn ? COL.uyari : COL.bilgi, warn: !!m.warn, e: m.e, zaman: Off.clock() });
  }
  function markPos(m, t) {
    const p = Math.min(1, (t - m.t0) / m.dur), q = Off.reduced ? 0.5 : Math.min(0.94, 0.06 + p * 1.05);
    const mx = (m.a.x + m.b.x) / 2, my = (m.a.y + m.b.y) / 2 - Math.min(40, Math.hypot(m.b.x - m.a.x, m.b.y - m.a.y) * 0.18);
    const x = (1 - q) * (1 - q) * m.a.x + 2 * (1 - q) * q * mx + q * q * m.b.x, y = (1 - q) * (1 - q) * m.a.y + 2 * (1 - q) * q * my + q * q * m.b.y;
    return { x: x, y: y, p: p };
  }
  Off.markBusy = function () { prune(); const t = now(); for (let i = 0; i < marks.length; i++) if (t - marks[i].t0 < marks[i].dur) return !Off.reduced; return false; };

  /* ---- çizim ---- */
  function drawArrow(ctx, m, al) {
    const dx = m.b.x - m.a.x, dy = m.b.y - m.a.y, d = Math.hypot(dx, dy) || 1, ux = dx / d, uy = dy / d;
    const head = () => { ctx.beginPath(); ctx.moveTo(m.b.x, m.b.y); ctx.lineTo(m.b.x - ux * 12 - uy * 6, m.b.y - uy * 12 + ux * 6); ctx.lineTo(m.b.x - ux * 12 + uy * 6, m.b.y - uy * 12 - ux * 6); ctx.closePath(); };
    ctx.save(); ctx.globalAlpha = al; ctx.lineCap = 'butt';
    ctx.setLineDash([7, 5]); ctx.strokeStyle = 'rgba(8,16,20,.85)'; ctx.lineWidth = 5; ctx.beginPath(); ctx.moveTo(m.a.x, m.a.y); ctx.lineTo(m.b.x - ux * 7, m.b.y - uy * 7); ctx.stroke();
    ctx.strokeStyle = m.color; ctx.lineWidth = 2.5; ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = 'rgba(8,16,20,.85)'; ctx.lineWidth = 3; ctx.strokeStyle = 'rgba(8,16,20,.85)'; head(); ctx.fill(); ctx.stroke();
    ctx.fillStyle = m.color; head(); ctx.fill();
    ctx.restore();
  }
  Off.extraDyn = function (out, t) {
    for (let i = marks.length - 1; i >= 0; i--) if (t - marks[i].t0 >= marks[i].dur) marks.splice(i, 1);
    marks.forEach(m => {
      const mp = markPos(m, t), al = mp.p < 0.1 ? mp.p / 0.1 : mp.p > 0.8 ? Math.max(0, (1 - mp.p) / 0.2) : 1;
      out.push({ k: 1e6 - 1, draw: ctx => {
        drawArrow(ctx, m, al);
        const ic = m.kind === 'zarf' ? O.icons.envelope() : m.kind === 'not' ? O.icons.not() : null;
        if (ic) { ctx.globalAlpha = al; ctx.drawImage(ic.c, Math.round(mp.x - ic.ax), Math.round(mp.y - ic.ay)); ctx.globalAlpha = 1; }
      } });
    });
    const st = Off.state();
    Object.keys(notes).forEach(tid => {
      const n = notes[tid]; if (!n.shown) return;
      const seat = (st.actorById[tid] || {}).seat; if (!seat) return;
      const ic = O.icons.bayrakNot(), x = W.sx(seat.tx, seat.ty - 1) , y = W.sy(seat.tx, seat.ty - 1) + HH + 4;
      out.push({ k: seat.tx + seat.ty - 1 + 1.4, draw: ctx => ctx.drawImage(ic.c, Math.round(x + 4 - ic.ax), Math.round(y - ic.ay)) });
    });
  };
  /* tıklama: işaret ya da not (dünya koordinatı) */
  Off.markAt = function (wx, wy) {
    prune(); const t = now(), st = Off.state(); let best = null, bd = 1e9;
    marks.forEach(m => {
      const mp = markPos(m, t), dx = wx - mp.x, dy = wy - mp.y, d = Math.hypot(dx, dy);
      let dd = (m.kind === 'ok') ? 1e9 : d; // ok için çizgiye mesafe
      const vx = m.b.x - m.a.x, vy = m.b.y - m.a.y, L2 = vx * vx + vy * vy || 1, u = Math.max(0, Math.min(1, ((wx - m.a.x) * vx + (wy - m.a.y) * vy) / L2)), sd = Math.hypot(wx - (m.a.x + u * vx), wy - (m.a.y + u * vy));
      if (m.kind === 'ok') dd = sd; else dd = Math.min(d, sd + 6);
      if (dd < 10 && dd < bd) { bd = dd; best = { type: 'isaret', mark: m }; }
    });
    Object.keys(notes).forEach(tid => {
      const n = notes[tid]; if (!n.shown) return; const seat = (st.actorById[tid] || {}).seat; if (!seat) return;
      const x = W.sx(seat.tx, seat.ty - 1) + 4, y = W.sy(seat.tx, seat.ty - 1) + HH + 4 - 10, d = Math.hypot(wx - x, wy - y);
      if (d < 14 && d < bd) { bd = d; best = { type: 'isaret', note: n, trader: tid }; }
    });
    return best;
  };

  /* ---- taşıyıcı figür: çalışan masasından kalkar, bir yere zarf/not götürür, geri döner ---- */
  function adjFree(tx, ty) {
    const D = [[0, 1], [1, 0], [-1, 0], [0, -1]];
    for (let i = 0; i < D.length; i++) { const x = tx + D[i][0], y = ty + D[i][1]; if (!W.isBlocked(x, y)) return [x, y]; }
    return [tx, ty];
  }
  Off.courier = function (staffId, target, carry, done) {
    const st = Off.state(), a = st.actorById['s:' + staffId];
    if (!a || !a.home || Off.reduced || st.fastUntil > now() || a.path.length || a.queue.length || a.dead) return false;
    const seat = a.seat, home = a.home.slice();
    if (seat) { seat.occ = null; seat.chair.s = O.chairSpr(seat.chairLook, 'b'); a.seat = null; }
    a.carry = carry;
    a.queue = [{ go: target }, { wait: 0.6 }, { fn: x => { x.pose = 'stand'; if (done) done(); } }, { go: seat ? [seat.tx, seat.ty] : home }, seat ? { sit: seat } : { fn: x => { x.pose = 'stand'; x.dir = 'u'; } }, { fn: x => { x.carry = null; } }];
    return true;
  };

  /* ---- olay → işaret eşlemesi ---- */
  const FIN = 'finans';
  const MAP = {
    yeni_adres: (e, st) => [{ k: 'zarf', a: 'tarama', b: 'kapi' }],
    kapi_gecti: () => [{ k: 'ok', a: 'kapi', b: 'lab' }],
    kapi_elendi: () => [{ k: 'not', a: 'kapi', b: 'exit', warn: true }],
    havuzdan_cikar: () => [{ k: 'ok', a: 'lab', b: 'kapi' }],
    terfi: e => [{ k: 'ok', a: e.kimden, b: e.kime }, { k: 'not', a: e.kimden, b: 'seat:' + e.trader }],
    kat_dusur: e => [{ k: 'ok', a: e.kimden, b: e.kime, warn: true }, { k: 'not', a: e.kimden, b: 'seat:' + e.trader, warn: true }],
    islem_acildi: (e, st) => [{ k: 'not', a: katOf(st, e.trader), b: FIN }],
    islem_kapandi: (e, st) => [{ k: 'zarf', a: katOf(st, ((st.kapanan[0] || {}).trader)), b: FIN }],
    risk_tavan: () => [{ k: 'ok', a: 'risk', b: 'oda', warn: true }, { k: 'not', a: 'risk', b: 'oda', warn: true }],
    risk_normal: () => [{ k: 'ok', a: 'risk', b: 'oda' }],
    veri_bayat: e => [{ k: 'not', a: 'denetim', b: e.oda, warn: true }],
    veri_taze: e => [{ k: 'ok', a: 'denetim', b: e.oda }],
    denetim: e => [{ k: 'not', a: 'denetim', b: 'makam', warn: e.sonuc !== 'tamam' }],
    arsiv_yazildi: () => [{ k: 'ok', a: 'denetim', b: 'arsiv' }],
    kasa_guncelle: () => [{ k: 'ok', a: 'finans', b: 'makam' }],
    kural_kitabi: () => [{ k: 'zarf', a: 'sekreterlik', b: 'makam' }],
    kullanici_karari: () => [{ k: 'not', a: 'makam', b: 'sekreterlik' }],
    veri_yenile: () => [{ k: 'ok', a: 'finans', b: 'oda' }]
  };
  const traderSeatTile = (st, tid) => { const a = st.actorById[tid]; return a && a.seat ? [a.seat.tx, a.seat.ty] : null; };

  Off.onEvent((e, st) => {
    const fire = list => list.forEach(m => addMark(Object.assign({ e: e }, m), st));
    if (e.tur === 'bildirim') {
      // Haberleşme'den zarf çıkar: postacı posta kutusuna yürür, zarfı bırakır, zarf dışarı süzülür
      const go = () => fire([{ k: 'zarf', a: 'mailbox', b: 'out' }]);
      const mb = [BX + W.mailboxLocal[0] + 1, BY + W.mailboxLocal[1]];
      if (!Off.courier('haber1', mb, 'envelope', go)) go();
      return;
    }
    if (e.tur === 'kirmizi_bayrak') {
      const tid = e.trader, n = notes[tid] = { e: e, shown: true }, tt = traderSeatTile(st, tid);
      // Kırmızı bayrak durumu kritiktir: ziyaret/yürüme kuyruğu taşıyıcıyı meşgul
      // edebilir. Notu olayla aynı anda göster; kurye yalnızca görsel geri bildirimdir.
      const delivered = () => fire([{ k: 'not', a: 'denetim', b: 'seat:' + tid, warn: true }]);
      if (!tt || !Off.courier('denetim', adjFree(tt[0], tt[1]), 'bayrakNot', delivered)) delivered();
      return;
    }
    if (e.tur === 'bayrak_kalkti') {
      const tid = e.trader, tt = traderSeatTile(st, tid);
      // Kaldırma da olayla aynı anda geçerlidir; animasyon kuyruğu notu tutamaz.
      delete notes[tid];
      const drop = () => fire([{ k: 'ok', a: 'seat:' + tid, b: 'denetim' }]);
      if (!tt || !Off.courier('denetim', adjFree(tt[0], tt[1]), null, drop)) drop();
      return;
    }
    const f = MAP[e.tur]; if (f) fire(f(e, st));
  });
  Off.resetHook = function () { Object.keys(notes).forEach(k => delete notes[k]); marks.length = 0; };
})();
