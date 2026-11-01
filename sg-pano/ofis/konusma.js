/* Ofis · kullanıcı tıklamasına verilen kısa karakter replikleri (özgün Canvas çizimi). */
(function () {
  'use strict';
  const O = window.OFIS, active = new Map(), turn = new Map();
  const AMBIENT = {
    makam: ['Gündem dosyası hazır mı?', 'Karar notunu masama bırakın.'], sekreterlik: ['Takvimde kısa bir boşluk var.', 'Evrak doğru klasöre gitti.'],
    finans: ['Defteri bir kez daha kapatalım.', 'Kuruşuna kadar eşleşti.'], haberlesme: ['Hat temiz, mesaj iletildi.', 'Karşı taraf aldı.'], risk: ['Eşikler sakin görünüyor.', 'Bir gözüm göstergelerde.'],
    denetim: ['İz kaydı tamam.', 'Kaynağı doğruladım.'], arsiv: ['Raflarda yer açıldı.', 'Bu kayıt kolay bulunur artık.'], tarama: ['Tarama kuyruğu ilerliyor.', 'Sıradaki kayıt geliyor.'],
    cay: ['Çay taze, bardak alana.', 'Dem biraz daha otursun.'], lab: ['Örnekler sıraya girdi.', 'Tahtaya yeni not ekledim.'], kontrol: ['Eşleşme turu sürüyor.', 'Karşılaştırma temiz.'],
    aday: ['Yeni dosyaya bakıyorum.', 'Liste bugün hareketli.'], oda: ['Raporu birazdan yollarım.', 'Bu masa dolu görünüyor.'], kapi: ['Giriş kaydı tamam.', 'Buyurun, geçiş açık.']
  };
  let nextAmbient = performance.now() + 5200;
  const LINES = {
    makam: ['Günün akışına bakalım.', 'Bir sonraki kayıt hazır.'],
    sekreterlik: ['Notumu hemen iletiyorum.', 'Takvime ekledim.'],
    finans: ['Rakamları yeniden kontrol ediyorum.', 'Kayıtlar önümde.'],
    haberlesme: ['Hattayım, dinliyorum.', 'Mesajı aldım.'],
    risk: ['Sınırları yakından izliyorum.', 'Kontrol listesi açık.'],
    denetim: ['Kaynağı doğruluyorum.', 'İzini kayda ekledim.'],
    arsiv: ['Kaydı arşivliyorum.', 'Belgeyi buldum.'],
    tarama: ['Yeni kayıtları tarıyorum.', 'Sıradaki kayda geçiyorum.'],
    cay: ['Çay hazır, buyurun.', 'Demlik taze.'],
    kapi: ['Hoş geldiniz, kaydınızı alayım.', 'Kontrol tamam.'],
    lab: ['Ön inceleme sürüyor.', 'Kaydı masama aldım.'],
    aday: ['İncelemeye devam ediyorum.', 'Notlarımı güncelliyorum.'],
    oda: ['Dosya önümde.', 'Gelişmeleri takip ediyorum.'],
    kontrol: ['Karşılaştırmayı açtım.', 'Kontrol kaydını aldım.']
  };
  const roomOf = a => {
    const W = O.World, x = a.tx - W.BX, y = a.ty - W.BY, r = W.roomAt[x + ',' + y];
    return (r && r.id) || a.room || a.kat || 'makam';
  };
  function speak(a) {
    if (!a || a.dead) return;
    const id = a.id || a.staffId || 'actor', lines = LINES[roomOf(a)] || LINES.makam;
    const n = turn.get(id) || 0;
    turn.set(id, n + 1);
    active.set(id, { id, text: lines[n % lines.length], until: performance.now() + 2300 });
  }
  function update(state) {
    if (performance.now() < nextAmbient || !state) return;
    const people = state.actors.filter(a => !a.dead && a.kind === 'staff' && !a.path.length && !a.wait);
    if (people.length) {
      const a = people[Math.floor(Math.random() * people.length)], room = roomOf(a), lines = AMBIENT[room] || AMBIENT.makam;
      const n = turn.get(a.id) || 0;
      turn.set(a.id, n + 1);
      active.set(a.id, { id: a.id, text: lines[n % lines.length], until: performance.now() + 2400 });
    }
    nextAmbient = performance.now() + 10500 + Math.random() * 6500;
  }
  function rounded(ctx, x, y, w, h, r) {
    ctx.beginPath(); ctx.moveTo(x + r, y); ctx.lineTo(x + w - r, y); ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r); ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h); ctx.quadraticCurveTo(x, y + h, x, y + h - r); ctx.lineTo(x, y + r); ctx.quadraticCurveTo(x, y, x + r, y); ctx.closePath();
  }
  function draw(ctx, state, toView, width, height) {
    if (!state) return;
    const t = performance.now();
    active.forEach((b, id) => { if (b.until <= t || !state.actorById[id]) active.delete(id); });
    ctx.save();
    active.forEach(b => {
      const a = state.actorById[b.id];
      if (!a || a.sx == null || a.dead || a.alpha < 0.4) return;
      const p = toView(a.sx, a.sy - (a.pose === 'sit' || a.pose === 'sitF' ? 38 : 34));
      ctx.font = '600 11px ui-monospace, monospace';
      const w = Math.min(184, ctx.measureText(b.text).width + 18), h = 26;
      const x = Math.max(5, Math.min(width - w - 5, p.x - w / 2)), y = Math.max(5, Math.min(height - h - 9, p.y - h - 10));
      ctx.globalAlpha = Math.min(1, Math.max(0, (b.until - t) / 260));
      rounded(ctx, x, y, w, h, 4); ctx.fillStyle = '#dff8f1'; ctx.fill(); ctx.strokeStyle = '#14575b'; ctx.lineWidth = 1; ctx.stroke();
      ctx.beginPath(); ctx.moveTo(p.x, y + h - 1); ctx.lineTo(p.x - 4, y + h + 5); ctx.lineTo(p.x + 4, y + h - 1); ctx.closePath();
      ctx.fillStyle = '#dff8f1'; ctx.fill(); ctx.strokeStyle = '#14575b'; ctx.stroke();
      ctx.fillStyle = '#173638'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(b.text, x + w / 2, y + h / 2, w - 10);
    });
    ctx.restore();
  }
  O.Konusma = { speak, draw, update, nextMs: () => Math.max(20, nextAmbient - performance.now()), clear: () => active.clear(), busy: () => { const t = performance.now(); active.forEach((b, id) => { if (b.until <= t) active.delete(id); }); return active.size > 0; } };
})();
