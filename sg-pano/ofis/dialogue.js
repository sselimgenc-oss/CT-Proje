/* Ofis · olay kaynaklı kısa konuşma balonları. Özgün, DOM'suz Canvas katmanı. */
(function () {
  'use strict';
  const O = window.OFIS;
  const LINES = {
    yeni_adres: 'Yeni kayıt geldi.', kapi_gecti: 'Kontrol tamamlandı.', kapi_elendi: 'Kayıt kapıda durduruldu.',
    havuzdan_cikar: 'Kayıt gözden geçiriliyor.', terfi: 'Yeni aşamaya geçildi.', dusurme: 'Kayıt yeniden incelenecek.',
    islem_acildi: 'Yeni olay kaydedildi.', islem_kapandi: 'Kapanış kayda geçti.', bildirim: 'Yeni bildirim geldi.',
    risk_tavan: 'Risk sınırına ulaşıldı.', risk_normal: 'Risk denetimi normale döndü.', veri_bayat: 'Kaynak güncelleme bekliyor.',
    veri_taze: 'Kaynak güncellendi.', denetim: 'Denetim tamamlandı.', arsiv_yazildi: 'Kayıt arşive eklendi.',
    kasa_guncelle: 'Kayıt yenilendi.', kural_kitabi: 'Kural kaydı güncellendi.', kullanici_karari: 'Karar kayda geçti.',
    veri_yenile: 'Kaynaklar yenilendi.', kirmizi_bayrak: 'İşaret incelemeye alındı.', bayrak_kalkti: 'İnceleme işareti kaldırıldı.',
    telegram: 'Haberleşme güncellendi.', tarama: 'Tarama tamamlandı.'
  };
  const ROOM = { havuz: 'lab', spot: 'lab', kohort: 'oda', kontrol: 'kontrol' };
  const live = new Map();
  let Off = null;
  const now = () => performance.now();

  function actorFor(e, state) {
    if (e.trader && state.actorById[e.trader]) return state.actorById[e.trader];
    const room = e.oda || ROOM[e.kol] || null;
    return state.actors.find(a => !a.dead && (a.room === room || a.kat === room)) ||
      state.actors.find(a => !a.dead && a.kind === 'staff');
  }
  function onEvent(e, state) {
    const line = LINES[e.tur];
    if (!line || !state) return;
    const a = actorFor(e, state);
    if (!a) return;
    const id = a.id || a.staffId;
    live.set(id, { id, text: line, until: now() + 2800 });
  }
  function rounded(ctx, x, y, w, h, r) {
    ctx.beginPath(); ctx.moveTo(x + r, y); ctx.lineTo(x + w - r, y); ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r); ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h); ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.lineTo(x, y + r); ctx.quadraticCurveTo(x, y, x + r, y); ctx.closePath();
  }
  function draw(ctx, state, toView, width, height) {
    if (!state) return;
    const t = now();
    live.forEach((b, id) => { if (b.until <= t || !state.actorById[id]) live.delete(id); });
    ctx.save();
    live.forEach(b => {
      const a = state.actorById[b.id];
      if (!a || a.sx == null || a.dead || a.alpha < 0.4) return;
      const p = toView(a.sx, a.sy - (a.pose === 'sit' || a.pose === 'sitF' ? 36 : 32));
      const font = '600 11px ui-monospace, monospace'; ctx.font = font;
      const textW = Math.min(174, ctx.measureText(b.text).width), w = textW + 16, h = 25;
      const x = Math.max(5, Math.min(width - w - 5, p.x - w / 2)), y = Math.max(5, Math.min(height - h - 11, p.y - h - 10));
      const alpha = Math.max(0, Math.min(1, (b.until - t) / 350));
      ctx.globalAlpha = alpha; rounded(ctx, x, y, w, h, 5); ctx.fillStyle = '#fff8e9'; ctx.fill();
      ctx.strokeStyle = '#23353a'; ctx.lineWidth = 1; ctx.stroke();
      ctx.beginPath(); ctx.moveTo(p.x, y + h - 1); ctx.lineTo(p.x - 4, y + h + 5); ctx.lineTo(p.x + 4, y + h - 1); ctx.closePath();
      ctx.fillStyle = '#fff8e9'; ctx.fill(); ctx.strokeStyle = '#23353a'; ctx.stroke();
      ctx.fillStyle = '#17272b'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(b.text, x + w / 2, y + h / 2, w - 10);
    });
    ctx.restore();
  }
  function busy() {
    const t = now();
    live.forEach((b, id) => { if (b.until <= t) live.delete(id); });
    return live.size > 0;
  }
  O.Dialogue = {
    init: function (office) { Off = office; live.clear(); Off.onEvent(onEvent); },
    draw: draw,
    busy: busy,
    clear: function () { live.clear(); }
  };
})();
