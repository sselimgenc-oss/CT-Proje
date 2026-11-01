/* Ofis · sol panel ve gözcü kaydı. Her sayının yanında zaman damgası ya da n; veri yoksa "bilinmiyor" (sıfır değil). */
(function () {
  'use strict';
  const O = window.OFIS;
  const $ = s => document.querySelector(s);
  const P = (O.Panel = {});
  let Off, api, st, raf = 0;
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const UNK = '<span class="bil">bilinmiyor</span>';
  const num = (v, d) => v == null || isNaN(v) ? null : Number(v).toLocaleString('tr-TR', { minimumFractionDigits: d == null ? 0 : d, maximumFractionDigits: d == null ? 0 : d });
  const usd = (v, sign) => { if (v == null) return UNK; const s = v < 0 ? '−' : (sign && v > 0 ? '+' : ''); return s + '$' + Math.abs(v).toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); };
  const pct = (v, sign, d) => { if (v == null) return UNK; const s = v < 0 ? '−' : (sign && v > 0 ? '+' : ''); return s + '%' + Math.abs(v).toLocaleString('tr-TR', { minimumFractionDigits: d == null ? 1 : d, maximumFractionDigits: d == null ? 1 : d }); };
  const cls = v => (v > 0 ? 'up' : v < 0 ? 'dn' : 'fl');
  const pad = n => (n < 10 ? '0' : '') + n;
  function hm(iso) { if (!iso) return 'bilinmiyor'; if (/^\d{4}-\d{2}-\d{2}T00:00:00Z$/.test(iso)) return iso.slice(0, 10); const d = new Date(iso);   // yalnız gün bilinen kaynaklar tarih olarak yazılır
 if (isNaN(d)) return 'bilinmiyor'; return Off.trHM(d); }
  function dur(sec) { sec = Math.max(0, Math.round(sec)); const m = Math.floor(sec / 60); if (m < 1) return sec + ' sn'; if (m < 60) return m + ' dk'; const h = Math.floor(m / 60); if (h < 24) return h + ' sa ' + pad(m % 60) + ' dk'; return Math.floor(h / 24) + ' g ' + (h % 24) + ' sa'; }
  const NEDEN = { trader_kapatti: 'trader kapattı', zarar_kesme: 'zarar kesme', sure: 'süre doldu' };
  const KATAD = { lab: 'Lab', aday: 'Aday', oda: 'Oda', kontrol: 'Kontrol' };
  const ODA_AD = id => id === 'diger' ? 'Diğer' : (id === 'referans' ? 'Referans' : (() => { const r = O.World.roomById[id]; return r ? O.Names.room(id, r.ad) : id; })());
  const ORN_CHIP = '<span class="ornek">örnek</span>';
  let ORN = ORN_CHIP;                                   // gerçek veride rozet yok (render başında güncellenir)
  const GRIN = '<span class="gri-not">sanal izleme başlamadı</span>';
  P.ornekMi = () => String((O.data || {}).kaynak || '').indexOf('ornek') === 0;

  const dkTxt = m => { m = Math.round(m); return m < 1 ? 'şimdi' : m < 60 ? m + ' dk' : m < 1440 ? Math.floor(m / 60) + ' sa' + (m % 60 ? ' ' + (m % 60) + ' dk' : '') : Math.floor(m / 1440) + ' g'; };
  const ageTxt = inf => (inf ? (Math.round(inf.dk) < 1 ? 'şimdi' : dkTxt(inf.dk) + ' önce') : 'bilinmiyor');
  P.dkTxt = dkTxt; P.ageTxt = ageTxt;
  /* günlük özet: yalnız olay günlüğünden */
  function gun() {
    const g = (O.Names.kadro().ozet_gruplari || []), r = Off.gunlukOzet(g);
    $('#gunIcerik').innerHTML = '<p class="gun-satir"><b>' + esc(r.dun) + '</b></p><p class="gun-satir gun-alt">' + esc(r.bugun) + '</p>';
    $('#gunMeta').innerHTML = 'kaynak: olay günlüğü (n=' + r.n + ') · ' + ORN;
    const sr = $('#gunSeritMetin'); if (sr) sr.textContent = r.dun + ' · ' + r.bugun;
  }
  function kasa() {
    if (Off.gri('finans')) { $('#kasaIcerik').innerHTML = '<p class="bos">' + GRIN + '</p>'; return; }
    const k = st.kasa, el = $('#kasaIcerik'), tem = st.acik.reduce((sum, x) => sum + (x.teminat_usd || 0), 0), kk = st.kk;
    el.innerHTML = '<div class="kasa-satir ks2"><div><span class="kl">oda kasası</span><div class="kv">' + usd(k.deger_usd) + '</div></div><div><span class="kl">getiri</span><div class="kv ' + cls(k.deger_usd == null || !k.baslangic_usd ? 0 : k.deger_usd / k.baslangic_usd - 1) + '">' + pct(k.deger_usd == null || !k.baslangic_usd ? null : (k.deger_usd / k.baslangic_usd - 1) * 100, true) + '</div></div></div>' +
      '<div class="kasa-satir"><span class="kl">kontrol kasası</span><b class="kv">' + usd(k.kontrol_deger_usd) + '</b></div>' +
      '<div class="kasa-satir ks2"><div><span class="kl">başlangıç</span><div class="kv">' + usd(k.baslangic_usd) + '</div></div><div><span class="kl">açık işlem teminatı</span><div class="kv">' + usd(tem) + '</div></div></div>' +
      '<p class="meta">n=' + (k.gun_n == null ? 'bilinmiyor' : k.gun_n + ' gün') + ' · veri ' + hm(k.zaman) + ' · ' + ORN + '</p>';
  }
  function ozet() {
    const a = st.acik, tem = a.reduce((s, x) => s + (x.teminat_usd || 0), 0), o = st.ozet, k = st.katlar, ornek = P.ornekMi();
    const box = (l, v, sub) => '<div class="kutu"><div class="kl">' + l + '</div><div class="kv">' + v + '</div><div class="ks">' + sub + '</div></div>';
    const cap = k.oda.kapasite;
    $('#ozetIcerik').innerHTML = (ornek
      ? box('Açık işlem', a.length, 'teminat ' + usd(tem)) + box('Bugün', 'n=' + (o.bugun_acilan_n + o.bugun_kapanan_n), o.bugun_acilan_n + ' açıldı · ' + o.bugun_kapanan_n + ' kapandı')
      : box('Açık işlem', '<span class="gri-not">—</span>', 'sanal izleme başlamadı') + box('Bugün', '<span class="gri-not">—</span>', 'sanal izleme başlamadı')) +
      box('Oda', num(k.oda.n) == null ? UNK : cap == null ? num(k.oda.n) : k.oda.n + '<small>/' + cap + '</small>', cap == null ? 'n=' + num(k.oda.n) + ' · ' + hm(k.oda.zaman) : 'doluluk ' + pct(k.oda.n / cap * 100, false, 0)) +
      box('Aday', num(k.aday.n) == null ? UNK : num(k.aday.n), 'n=' + num(k.aday.n) + ' · ' + hm(k.aday.zaman)) +
      box('Havuz', num(k.havuz.n) == null ? UNK : num(k.havuz.n), 'n=' + num(k.havuz.n) + ' · ' + hm(k.havuz.zaman)) +
      box('İşlem başı', ornek ? usd(o.islem_basi_usd) : '<span class="gri-not">—</span>', ornek ? 'kural: kurallar.yaml' : 'sanal izleme başlamadı');
    $('#ozetMeta').innerHTML = (ornek ? 'veri ' + hm(o.zaman) : 'seçim verisi ' + hm(k.havuz.zaman)) + ' · ' + ORN;
  }
  function liveSec(x) { return (x.yas_dk || 0) * 60 + (x.t0 ? (Date.now() - x.t0) / 1000 : (Date.now() - st.loadMs) / 1000); }
  function acik() {
    const rows = st.acik.slice().sort((a, b) => liveSec(a) - liveSec(b));
    $('#acikN').textContent = P.ornekMi() || rows.length ? rows.length : '–';
    if (!rows.length) { $('#acikIcerik').innerHTML = P.ornekMi() ? '<p class="bos">Açık gölge işlemi yok.</p>' : '<p class="bos">' + GRIN + '</p>'; return; }
    const lc = v => (v == null ? '' : v <= 10 ? 'dn' : v <= 20 ? 'wr' : 'fl');
    $('#acikIcerik').innerHTML = '<table class="tab"><caption class="sr">Açık gölge işlemleri</caption><thead><tr><th scope="col">İşlem</th><th scope="col">Trader</th><th scope="col" class="r">Süre</th><th scope="col" class="r" title="Trader K/Z, 1.000 $ sanal ölçeğe çevrilmiş">K/Z (1.000 $)</th><th scope="col" class="r" title="Likidasyona uzaklık">Lik.</th></tr></thead><tbody>' +
      rows.map(x => {
        const t = st.traders[x.trader] || {};
        return '<tr data-id="' + esc(x.id) + '"><td><button class="sb" data-trader="' + esc(x.trader) + '"><i class="kt ' + (x.yon === 'long' ? 'lg' : 'sh') + '"></i><b>' + esc(x.coin) + '</b> <span class="yon ' + (x.yon === 'long' ? 'lg' : 'sh') + '">' + (x.yon === 'long' ? 'LONG' : 'SHORT') + ' ' + x.kaldirac + 'x</span></button></td>' +
          '<td class="mono">' + esc((t.adres || x.trader).replace('0xAAAA', '0xAAAA')) + '</td><td class="r s" data-sure="' + esc(x.id) + '">' + dur(liveSec(x)) + '</td>' +
          '<td class="r ' + cls(x.kz_usd) + '">' + usd(x.kz_usd, true) + '<small>' + pct(x.kz_yuzde, true) + '</small></td><td class="r ' + lc(x.lik_uzaklik) + '">' + (x.lik_uzaklik == null ? UNK : pct(x.lik_uzaklik, false)) + '</td></tr>';
      }).join('') + '</tbody></table>';
    $('#acikMeta').innerHTML = 'n=' + rows.length + ' · veri ' + hm(st.ozet.zaman) + ' · trader adresleri ' + ORN;
  }
  function kapanan() {
    const el = $('#kapIcerik');
    if (!st.kapanan.length) { el.innerHTML = P.ornekMi() ? '<p class="bos">Henüz kapanan işlem yok.</p>' : '<p class="bos">' + GRIN + '</p>'; return; }
    el.innerHTML = st.kapanan.slice(0, 5).map(x => {
      const t = st.traders[x.trader] || {};
      return '<div class="kap"><i class="kt ' + (x.kz_usd >= 0 ? 'lg' : 'sh') + '"></i><div class="kk"><b>' + esc(x.coin) + '</b> <span class="yon ' + (x.yon === 'long' ? 'lg' : 'sh') + '">' + (x.yon === 'long' ? 'LONG' : 'SHORT') + '</span><div class="ks">' + esc(NEDEN[x.neden] || x.neden) + ' · ' + dur((x.sure_dk || 0) * 60) + ' · ' + esc(t.adres || x.trader) + '</div></div><div class="kr ' + cls(x.kz_usd) + '">' + pct(x.kz_yuzde, true) + '<small>' + usd(x.kz_usd, true) + '</small></div></div>';
    }).join('');
    $('#kapMeta').innerHTML = 'n=' + Math.min(5, st.kapanan.length) + ' (son kapananlar) · ' + ORN;
  }
  function huni() {
    const k = st.katlar, tot = Math.max(1, k.havuz.n);
    const row = (ad, n, sub, w, c, extra) => '<div class="hr"><div class="hh"><b>' + ad + '</b><span>' + n + extra + '</span></div><div class="hb"><i style="width:' + Math.max(4, w) + '%;background:' + c + '"></i></div><div class="ks">' + sub + '</div></div>';
    $('#huniIcerik').innerHTML =
      row('Havuz · Lab', num(k.havuz.n), 'gölgede izlenir · ' + hm(k.havuz.zaman), 100, '#8aa4c8', '') +
      row('Aday', num(k.aday.n), 'havuzun ' + pct(k.aday.n / tot * 100, false) + ' · ' + hm(k.aday.zaman), k.aday.n / tot * 100, '#e0a14a', '') +
      row('Oda · kopya', k.oda.kapasite == null ? num(k.oda.n) : k.oda.n + '/' + k.oda.kapasite, 'havuzun ' + pct(k.oda.n / tot * 100, false) + ' · ' + hm(k.oda.zaman), k.oda.n / tot * 100, '#6a86d8', '');
    $('#huniMeta').innerHTML = 'ofiste ' + k.havuz.masa + '/' + k.aday.masa + '/' + k.oda.masa + ' masa görünür · ' + ORN;
  }
  function kohort() {
    const k = st.kk, pr = Math.max(0, Math.min(1, k.hafta / k.hafta_toplam));
    $('#kohIcerik').innerHTML = '<div class="hafta"><span>hafta <b>' + k.hafta + '/' + k.hafta_toplam + '</b></span><div class="hb"><i style="width:' + (pr * 100).toFixed(0) + '%;background:#46d3c2"></i></div></div>' +
      '<ul class="kollar">' + k.kollar.map(c => '<li><span>' + esc(c.ad) + '</span><b>N=' + c.n + (c.getiri == null ? '' : ' · ' + pct(c.getiri * 100, true)) + '</b></li>').join('') + '</ul>' +
      '<p class="meta">' + esc(k.onkayit || 'Kohort verisi yok') + '</p>';
    $('#kohMeta').innerHTML = 'veri ' + hm(k.zaman) + ' · ' + ORN;
  }
  function veri() {
    $('#veriIcerik').innerHTML = st.vk.map(r => {
      const inf = Off.srcInfo(r), eski = !!(inf && inf.stale), dur = eski ? 'bayat' : r.durum;
      const d = dur === 'tamam' ? 'ok' : dur === 'bilinmiyor' ? 'bl' : 'wr';
      return '<div class="vr"><i class="nk ' + d + '" aria-hidden="true"></i><div class="vk"><b>' + esc(r.ad) + '</b><div class="ks">' + (r.deger == null ? UNK : esc(r.deger)) + ' · ' + (r.zaman ? hm(r.zaman) + ' · ' + ageTxt(inf) : 'zaman bilinmiyor') + (inf && inf.esik != null ? ' · eşik ' + dkTxt(inf.esik) : '') + '</div></div><span class="rz ' + d + '">' + (dur === 'tamam' ? 'tamam' : dur === 'bayat' ? 'VERİ ESKİ' : dur === 'bilinmiyor' ? 'bilinmiyor' : 'uyarı') + '</span></div>';
    }).join('');
    $('#veriMeta').innerHTML = 'n=' + st.vk.length + ' kontrol · ' + ORN;
  }
  function risk() {
    if (Off.gri('risk')) { $('#riskIcerik').innerHTML = '<p class="bos">' + GRIN + '</p>'; $('#riskMeta').innerHTML = 'eşikler yalnız kurallar.yaml\'da'; return; }
    $('#riskIcerik').innerHTML = st.risk.tavanlar.map(t => {
      const r = t.kullanim / t.tavan, c = r >= 0.999 ? 'dn' : r >= 0.75 ? 'wr' : 'ok', f = x => t.birim === 'kasa payı' ? pct(x * 100, false, 0) : t.birim === 'x' ? (Math.round(x * 10) / 10) + 'x' : '%' + Math.round(x * 100);
      return '<div class="rr"><div class="rh"><b>' + esc(t.ad) + '</b><span class="' + c + '">' + (r >= 0.999 ? 'TAVAN DOLU' : '%' + Math.round(r * 100)) + '</span></div><div class="hb"><i class="' + c + '" style="width:' + Math.min(100, r * 100).toFixed(0) + '%"></i></div><div class="ks">' + esc(t.birim) + ': ' + f(t.kullanim) + ' / ' + f(t.tavan) + '</div></div>';
    }).join('');
    $('#riskMeta').innerHTML = 'veri ' + hm(st.risk.zaman) + ' · eşikler yalnız kurallar.yaml\'da · ' + ORN;
  }
  function tg() {
    $('#tgIcerik').innerHTML = '<div class="tgs"><b>' + (st.tg.bugun_n == null ? UNK : st.tg.bugun_n) + '</b><span>bildirim bugün</span></div><ul class="tgl">' + st.tg.son.slice(0, 3).map(s => '<li>' + esc(s) + '</li>').join('') + '</ul>';
    $('#tgMeta').innerHTML = 'son ' + hm(st.tg.zaman) + ' · ' + ORN;
  }
  /* Taban kolundaki traderlar Lab/havuz katında oturur (ayrı oda çizilmiyor) ama "taban" kontrol kümesi kavramsal
     olarak Lab'dan ayrıdır — olay etiketi karıştırmasın diye "Taban" yazılır (SEMA.md: traderlar[].kol). */
  const odaAdOlay = l => { const t = l.trader && st.traders[l.trader]; return t && t.kol === 'taban' ? 'Taban' : ODA_AD(l.oda); };
  /* gözcü kaydı oturumun canlı günlüğü (st.log) + veri dosyasındaki geçmiş günlüğü (st.gecmis, gerçek veride buradan
     gelir — olay çekmecesiyle aynı kaynak) birleştirir; yoksa sürekli boş kalırdı (örnek veri dışında st.log hiç dolmaz). */
  function gozcuListesi() {
    const log = st.log.map(l => ({ ts: l.ts, oda: l.oda, trader: l.trader, metin: l.metin, iso: l.iso }));
    const gecmis = st.gecmis.map(g => ({ ts: Off.trTarihHM(g.zaman), oda: g.oda || '', trader: g.trader || null, metin: g.metin || g.tur, iso: g.zaman }));
    return log.concat(gecmis).sort((a, b) => (a.iso < b.iso ? 1 : a.iso > b.iso ? -1 : 0));
  }
  function gozcu() {
    $('#gozcuListe').innerHTML = gozcuListesi().slice(0, 7).map(l => '<li><button data-oda="' + esc(l.oda) + '"><time>' + esc(l.ts) + '</time><i class="oc" data-o="' + esc(l.oda) + '">' + esc(odaAdOlay(l)) + '</i><span>' + esc(l.metin) + '</span></button></li>').join('') || '<li class="bos">' + (P.ornekMi() ? 'Henüz olay yok (örnek akış başlıyor).' : 'Henüz olay yok — sanal izleme başlamadı.') + '</li>';
  }
  function aciklama() {
    const k = st.katlar, ac = Object.keys(st.stale).filter(x => st.stale[x]).map(ODA_AD);
    const ornek = P.ornekMi(), gri = Object.keys(O.data.oda_durum || {}).filter(x => (O.data.oda_durum[x] || {}).gri).map(ODA_AD);
    $('#ofisAciklama').textContent = ornek
      ? 'Örnek veriyle çalışan izometrik ofis: 14 oda; Lab, Aday, Oda ve Kontrol masalarında trader figürleri oturur. Havuz ' + k.havuz.n + ', aday ' + k.aday.n + ', oda ' + k.oda.n + '/' + k.oda.kapasite + '. Açık gölge işlemi ' + st.acik.length + '. Risk alarmı ' + (st.alarm ? 'açık' : 'yok') + '. Bayat oda: ' + (ac.length ? ac.join(', ') : 'yok') + '.'
      : O.data.veri_kaynagi && O.data.veri_kaynagi.tur === 'ilk11-acil'
        ? 'Acil leaderboard rosterıyla çalışan ofis; bu normal Pazar sonucu veya Kapı yeterlilik kararı değildir. İlk11, yedekler ve PAF takımları yalnız anlık leaderboard sıralamasını gösterir. Paper izleme başlamadı.'
        : 'Veri dalındaki seçim ve kapı durumuyla çalışan izometrik ofis (onaylanmamış ön izleme): Aday ve Oda masalarında gerçek trader figürleri oturur. Havuz ' + k.havuz.n + ', aday ' + k.aday.n + ', oda ' + k.oda.n + '. Paper izleme başlamadı; henüz verisi olmayan odalar gri: ' + (gri.length ? gri.join(', ') : 'yok') + '.';
  }
  function top() {
    const ornek = P.ornekMi(), d = O.data, sc = d.secim;
    $('#ornekFlt').hidden = !ornek;
    $('#onizlemeFlt').hidden = ornek || !sc;
    if (sc) $('#onizlemeMetin').textContent = d.veri_kaynagi && d.veri_kaynagi.tur === 'ilk11-acil'
      ? 'ACİL leaderboard-only roster · Kapı-qualified değil · ' + sc.tarih
      : 'Seçim ' + sc.surum + (sc.onaylandi ? ' — pilot, hafta ' + st.kk.hafta + '/' + st.kk.hafta_toplam : ' — veri yok') + ' (' + sc.tarih + ')';
    Object.keys(d.oda_durum || {}).forEach(id => { if (d.oda_durum[id].gizli) document.querySelectorAll('.ray [data-oda=' + id + ']').forEach(b => { b.hidden = true; }); });   // gizli oda sol menüde de yok
    const lk = $('#lejKontrol'); if (lk) lk.hidden = false;
    const an = $('#altNot'); if (an && ornek) an.innerHTML = 'Bu sayfa <b>örnek veriyle</b> çalışır (<code>?durum=ornek</code>); adresler uydurmadır.';
    const c = d.cipler || {}, low = v => String(v).toLocaleLowerCase('tr');
    $('#kayitDeger').textContent = c.golge ? low(c.golge) : 'bilinmiyor';
    $('#hatDeger').textContent = c.telegram ? low(c.telegram) : 'bilinmiyor';
    $('#plHat .lamba').className = 'lamba ' + (low(c.telegram || '') === 'açık' ? 'ok' : 'wr');
  }
  function render() {
    raf = 0; st = Off.state(); if (!st) return;
    ORN = P.ornekMi() ? ORN_CHIP : '';
    gun(); kasa(); ozet(); acik(); kapanan(); huni(); kohort(); veri(); risk(); tg(); gozcu(); aciklama(); top();
  }
  function schedule() { if (!raf) raf = requestAnimationFrame(render); }
  P.init = function (off, a) {
    Off = off; api = a;
    Off.on(schedule); O.Names.onChange(schedule);
    document.addEventListener('click', e => {
      const b = e.target.closest('[data-oda]'); if (b && b.closest('#gozcuListe') && b.dataset.oda) api.focusRoom(b.dataset.oda);
      const s = e.target.closest('.sb'); if (s) { const act = Off.state().actorById[s.dataset.trader]; const k = act && act.kat; if (k) api.focusRoom(k); }
    });
    // süre hücreleri canlı akar (hareket azaltılmışsa dakikada bir)
    setInterval(() => {
      if (!st) return;
      const sl = Off.state(); sl.acik.forEach(x => { const c = document.querySelector('[data-sure="' + x.id + '"]'); if (c) c.textContent = dur(liveSec(x)); });
      const sc = $('#saat'); if (sc) sc.textContent = Off.trHM(Off.clock());
    }, Off.reduced ? 15000 : 1000);
    render();
    const sc = $('#saat'); if (sc) sc.textContent = Off.trHM(Off.clock());
  };
})();
