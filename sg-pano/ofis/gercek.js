/* Ofis · gerçek veri uyarlayıcı: sg-arge veri dalındaki secim.json + kapı durum.json → ofis/SEMA.md şeması (bkz. SEMA.md §9).
   Kural: veri olmayan alan boş/null kalır; sahte figür, sahte olay yok. Körlük: kâr/zarar, puan ve kol karşılaştırması taşınmaz (yalnız kat ve sıra).
   Tarayıcıda window.OFIS.Gercek, Node'da module.exports (test). */
(function (root, factory) {
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else { root.OFIS = root.OFIS || {}; root.OFIS.Gercek = api; }
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';
  const REPO = 'sselimgenc-oss/sg-arge', DAL = 'copytrade-kapi', IZLEME_DALI = 'copytrade-izleme';
  const AGAC = 'https://api.github.com/repos/' + REPO + '/git/trees/' + DAL + '?recursive=1';   // kimliksiz API: tek çağrı
  const HAM = 'https://raw.githubusercontent.com/' + REPO + '/' + DAL + '/';
  const IZLEME_HAM = 'https://raw.githubusercontent.com/' + REPO + '/' + IZLEME_DALI + '/izleme/durum.json';
  const ESIK_DK = 7 * 1440;                                   // seçim ve kapı haftalık/günlük üretilir: bir haftadan eskiyse VERİ ESKİ
  const GRI = 'sanal izleme başlamadı';
  const TARIH = /^\d{4}-\d{2}-\d{2}/;

  /* ağaç (GitHub git/trees yanıtı ya da yol listesi) → en son seçim klasörü ve kapı tarihleri */
  function enSon(agac) {
    const yollar = (Array.isArray(agac) ? agac : (agac && agac.tree) || []).map(x => (typeof x === 'string' ? x : x.path));
    const secimler = yollar.map(p => /^secim\/([^/]+)\/secim\.json$/.exec(p)).filter(Boolean).map(m => m[1]).filter(d => TARIH.test(d)).sort();
    const durumlar = yollar.map(p => /^copytrade\/kapi\/(\d{4}-\d{2}-\d{2})\/durum\.json$/.exec(p)).filter(Boolean).map(m => m[1]).sort();
    return { secim: secimler.length ? secimler[secimler.length - 1] : null, durumlar: durumlar };
  }
  /* seçimin dayandığı kapı koşusu: secim.json'da kapi_tarihi varsa o (v1.3), yoksa seçim tarihinden önceki/aynı en son durum.json */
  function kapiTarihi(secim, durumlar) {
    if (secim && secim.kapi_tarihi && durumlar.indexOf(secim.kapi_tarihi) >= 0) return secim.kapi_tarihi;
    const t = String((secim && secim.tarih) || '');
    const uygun = durumlar.filter(d => d <= t);
    return uygun.length ? uygun[uygun.length - 1] : durumlar.length ? durumlar[durumlar.length - 1] : null;
  }
  const kisa = a => (a.length > 12 ? a.slice(0, 6) + '…' + a.slice(-4) : a);
  const sayi = v => (typeof v === 'number' && isFinite(v) ? v : null);
  const trSayi = v => (v == null ? 'bilinmiyor' : Number(v).toLocaleString('tr-TR', { maximumFractionDigits: 0 }));

  function cevir(secim, durum, opt) {
    opt = opt || {};
    const simdi = opt.simdi instanceof Date ? opt.simdi : new Date();
    const n = (secim && secim.sayilar) || {}, tarih = String((secim && secim.tarih) || '').slice(0, 10);
    const z = tarih + 'T00:00:00Z', surum = (secim && secim.secim_surumu) || 'v1';
    const kapiZ = opt.kapiTarihi ? opt.kapiTarihi + 'T00:00:00Z' : z;
    const girdi = Object.keys((secim && secim.adresler) || {}).map(a => Object.assign({ adres: a }, secim.adresler[a]));
    const sira = (a, b) => ((a.sira == null ? 1e9 : a.sira) - (b.sira == null ? 1e9 : b.sira)) || String(a.tarz).localeCompare(String(b.tarz)) || (a.adres < b.adres ? -1 : 1);
    const odaListe = girdi.filter(e => e.kollar.indexOf('oda') >= 0).sort(sira);
    const adayListe = girdi.filter(e => e.kollar.indexOf('aday') >= 0 && e.kollar.indexOf('oda') < 0).sort(sira);
    const olustur = (e, kat, onek, i) => ({
      id: onek + String(i + 1).padStart(2, '0'), adres: kisa(e.adres), takma_ad: e.adres.slice(2, 6), kat: kat, kol: kat === 'oda' ? 'kohort' : 'havuz',
      tarz: e.tarz || null, etiket: tarih, gun: sayi(e.gecmis_gun) == null ? null : Math.round(e.gecmis_gun), islem_n: null, sira: sayi(e.sira),
      medyan_kaldirac: sayi(e.medyan_kaldirac), en_yuksek_kaldirac: sayi(e.en_yuksek_kaldirac), genc_aday: !!e.genc_aday,
      kat_olay: { id: 'secim-' + surum + '-' + tarih + '-' + onek + (i + 1), kural: 'Seçim ' + surum + ' — ön izleme: ' + (kat === 'oda' ? 'aday katında ilk sıralardan odaya alındı' : 'aday katına girdi'), zaman: z }
    });
    const traderlar = odaListe.map((e, i) => olustur(e, 'oda', 'O', i)).concat(adayListe.map((e, i) => olustur(e, 'aday', 'A', i)));
    const kolSayi = k => sayi(n[k]);
    const evren = durum ? sayi(durum.evren) : null, islenen = durum ? sayi(durum.islenen) : null;
    const kapsam = durum && sayi(durum.kapsam) != null ? '%' + Math.round(durum.kapsam * 100) : null;
    const vk = (anahtar, ad, durumu, deger, zaman) => ({ anahtar: anahtar, ad: ad, durum: durumu, deger: deger, zaman: zaman, esik_dk: ESIK_DK });
    const kapiTamam = durum && durum.durum === 'tamam';
    const live = opt.izleme || null, etiket = surum + '@' + (opt.kapiTarihi || tarih);
    const eslesmis = live && Array.isArray(live.traderlar) ? live.traderlar.filter(t => t.secim === etiket) : [];
    const onaylandi = eslesmis.length > 0;
    const canli = Object.fromEntries(eslesmis.map(t => [String(t.adres).toLowerCase(), t]));
    const acikIslemler = [];
    const liveRows = onaylandi ? girdi.filter(e => canli[e.adres]).map((e, i) => {
      const t = canli[e.adres], ks = t.kollar || [t.kol];
      const kat = ks.indexOf('referans_oda') >= 0 || ks.indexOf('referans_kontrol') >= 0 ? 'referans' : (ks.indexOf('oda') >= 0 ? 'oda' : (ks.indexOf('kontrol') >= 0 ? 'kontrol' : ks.indexOf('taban') >= 0 ? 'lab' : 'aday'));
      if (kat === 'oda') (t.pozisyonlar || []).forEach((p, j) => {
        const acilisMs = p.acilis ? Date.parse(p.acilis) : NaN, veriMs = live.uretildi ? Date.parse(live.uretildi) : simdi.getTime();
        acikIslemler.push({
          id: t.id + '-' + p.coin + '-' + j, trader: t.id, coin: p.coin || 'bilinmiyor', yon: p.yon === 'short' ? 'short' : 'long',
          kaldirac: sayi(p.kaldirac), yas_dk: isNaN(acilisMs) ? null : Math.max(0, (veriMs - acilisMs) / 60000),
          kz_usd: sayi(t.hesap_degeri) > 0 && sayi(p.anlik_kz_usd) != null ? sayi(p.anlik_kz_usd) * 1000 / sayi(t.hesap_degeri) : null, kz_yuzde: null, lik_uzaklik: null,
          teminat_usd: sayi(t.hesap_degeri) > 0 && sayi(p.buyukluk_usd) != null && sayi(p.kaldirac) > 0 ? Math.abs(sayi(p.buyukluk_usd)) * 1000 / sayi(t.hesap_degeri) / sayi(p.kaldirac) : null   // K/Z ve teminat panoyla aynı 1.000 $ sanal ölçekte (teminat = nosyonel / kaldıraç); yalnız durum.json'da gerçekten olan alanlar; sahte yüzde/teminat/likidasyon uydurulmaz
        });
      });
      // Güncel motor (sanal_kopya_v3 — sabit tutar + çıkış kuralları + tasfiye); v1 (sanal_kopya) silinmedi
      // ama ofis artık onu göstermiyor (kullanıcı kararı 2026-10-30). Çıkış alanı adı (sanal_kopya) değişmedi;
      // bu uyarlayıcının kendi çıktı sözleşmesi, kaynaktaki alan adıyla bağımlı değil.
      return Object.assign(olustur(e, kat, t.id.slice(0, 1), i), { id: t.id, adres: kisa(t.adres), takma_ad: t.takma_ad, kat: kat, kol: t.kol, saglik: t.saglik, sanal_kopya: t.sanal_kopya_v3 || null, veri_zamani: t.veri_zamani || live.uretildi });
    }) : traderlar;
    const copies = eslesmis.map(t => t.sanal_kopya_v3).filter(c => c && typeof c.getiri === 'number');
    const total = key => copies.reduce((x, c) => x + (sayi(c[key]) || 0), 0);
    // "durum":"hesaplanamadi" (v3 henüz hesaplanmamış/hesaplanamamış) sayılmaz: ortalamaya 0 olarak girip
    // getiriyi çekmesin, kasa toplamına da hayalî üye eklemesin (worker/src/index.js sanalKohort ile aynı düzeltme).
    const kol = name => eslesmis.filter(t => (t.kollar || []).indexOf(name) >= 0).map(t => t.sanal_kopya_v3).filter(c => c && typeof c.getiri === 'number');
    const getiri = name => { const a = kol(name); return a.length ? a.reduce((x, c) => x + (sayi(c.getiri) || 0), 0) / a.length : null; };
    const hazirOda = live && live.canli_oda_ozeti && live.canli_oda_ozeti.surum === 1 ? live.canli_oda_ozeti : null;
    const odaV3 = kol('oda').filter(c => sayi(c.baslangic_usd) > 0 && sayi(c.bakiye_usd) != null);
    const odaBaslangic = hazirOda ? hazirOda.v3_baslangic_toplam_usd : (odaV3.length ? odaV3.reduce((x, c) => x + c.baslangic_usd, 0) : null);
    const odaBakiye = hazirOda ? hazirOda.v3_bakiye_toplam_usd : (odaV3.length ? odaV3.reduce((x, c) => x + c.bakiye_usd, 0) : null);
    const odaGetiriler = odaV3.map(c => c.bakiye_usd / c.baslangic_usd - 1);
    const odaOrtalama = hazirOda ? hazirOda.getiri_ortalama.deger : (odaGetiriler.length ? odaGetiriler.reduce((x, v) => x + v, 0) / odaGetiriler.length : null);
    const odaOrtalamaN = hazirOda ? hazirOda.getiri_ortalama.payda_n : odaGetiriler.length;
    const hafta = onaylandi ? Math.max(1, Math.floor((simdi.getTime() - Date.parse(tarih + 'T00:00:00Z')) / 604800000) + 1) : 0;
    const gunSayisi = onaylandi ? Math.max(1, Math.floor((simdi.getTime() - Date.parse(tarih + 'T00:00:00Z')) / 86400000) + 1) : null;   // t0 günü = 1 (hafta×7 değil)
    const gecmis = (live && live.olaylar || []).map(e => ({ id: e.id, zaman: e.zaman, tur: e.tur === 'acilis' ? 'islem_acildi' : e.tur === 'kapanis' ? 'islem_kapandi' : e.tur, oda: (liveRows.find(t => t.id === e.trader) || {}).kat || 'diger', trader: e.trader, metin: e.trader + ' · ' + e.coin + ' · ' + e.tur })).filter(e => e.tur === 'islem_acildi' || e.tur === 'islem_kapandi');
    const maxLev = eslesmis.filter(t => (t.kollar || []).indexOf('oda') >= 0).reduce((x, t) => Math.max(x, ...(t.pozisyonlar || []).map(p => sayi(p.kaldirac) || 0)), 0);
    return {
      surum: 1, uretildi: simdi.toISOString(), kaynak: 'hyperliquid-kapi (veri dalı ' + DAL + ', seçim ' + surum + ' ' + tarih + ')',
      secim: { surum: surum, tarih: tarih, kapi_tarihi: opt.kapiTarihi || null, onaylandi: onaylandi },
      cipler: { golge: onaylandi ? 'açık' : GRI, telegram: null },
      kasa: { deger_usd: onaylandi ? odaBakiye : null, baslangic_usd: onaylandi ? odaBaslangic : null,
        getiri_toplam: onaylandi && hazirOda ? hazirOda.getiri_toplam.deger : (onaylandi && odaBaslangic ? (odaBakiye - odaBaslangic) / odaBaslangic : null),
        getiri_toplam_n: onaylandi ? (hazirOda ? hazirOda.getiri_toplam.payda_n : odaV3.length) : 0,
        getiri_ortalama: onaylandi ? odaOrtalama : null, getiri_ortalama_n: onaylandi ? odaOrtalamaN : 0,
        ozet_kaynagi: hazirOda ? 'canli_oda_ozeti' : 'eski_sozlesme', zaman: live && live.uretildi || null, gun_n: gunSayisi,
        egri: hazirOda ? hazirOda.kasa_egrisi_usd : [], kontrol_deger_usd: onaylandi ? kol('kontrol').reduce((x, c) => x + (sayi(c.bakiye_usd) || 0), 0) : null },
      ozet: { islem_basi_usd: null, bugun_kz_usd: null, bugun_acilan_n: null, bugun_kapanan_n: null, zaman: null },
      katlar: {
        havuz: { n: kolSayi('havuz'), masa: 0, zaman: z, esik_dk: ESIK_DK },
        aday: { n: kolSayi('aday'), masa: adayListe.length, zaman: z, esik_dk: ESIK_DK },
        oda: { n: kolSayi('oda'), kapasite: null, masa: odaListe.length, zaman: z, esik_dk: ESIK_DK },
        kontrol: { n: kolSayi('kontrol'), masa: 0, zaman: z, esik_dk: ESIK_DK }
      },
      traderlar: liveRows, acik_islemler: acikIslemler, kapananlar: [], olaylar: [], gecmis_olaylar: gecmis, akis_suresi_sn: 0,
      kohort_kontrol: {
        hafta: hafta, hafta_toplam: 12, performans_kilitli: false,
        kollar: [{ ad: 'Oda (yönetilen)', n: onaylandi ? odaOrtalamaN : kolSayi('oda'), getiri: onaylandi ? odaOrtalama : null }, { ad: 'Referans oda', n: onaylandi ? kol('referans_oda').length : 0, getiri: getiri('referans_oda') }, { ad: 'Kontrol (sabit)', n: onaylandi ? kol('kontrol').length : kolSayi('kontrol'), getiri: getiri('kontrol') }, { ad: 'Referans kontrol', n: onaylandi ? kol('referans_kontrol').length : 0, getiri: getiri('referans_kontrol') }, { ad: 'Taban', n: onaylandi ? kol('taban').length : kolSayi('taban'), getiri: getiri('taban') }, { ad: 'Elle liste', n: kolSayi('elle') }],
        onkayit: 'Pilot; yönetilen oda sabit referans kontrol koluyla izlenir', zaman: live && live.uretildi || z, esik_dk: ESIK_DK
      },
      veri_kalitesi: [
        vk('tarama', 'Tarama (kapı koşusu)', durum ? (kapiTamam ? 'tamam' : 'uyari') : 'bilinmiyor', durum ? 'evren ' + trSayi(evren) + ' · işlenen ' + trSayi(islenen) + (kapsam ? ' · kapsam ' + kapsam : '') : null, durum ? kapiZ : null),
        vk('lab', 'Gölge defteri', onaylandi ? 'tamam' : 'bilinmiyor', onaylandi ? 'izlenen ' + eslesmis.length + ' trader' : null, live && live.uretildi || null), vk('arsiv', 'Arşiv yazımı', 'bilinmiyor', null, null),
        vk('denetim', 'Sağlama (gölge ↔ trader PnL)', 'bilinmiyor', null, null), vk('gecikme', 'Gecikme zinciri p95', 'bilinmiyor', null, null), vk('mum', '1 dk mum boşluğu', 'bilinmiyor', null, null)
      ],
      risk: { zaman: live && live.uretildi || null, tavanlar: onaylandi ? [{ anahtar: 'kaldirac', ad: 'Oda en yüksek kaldıraç', kullanim: maxLev, tavan: 10, birim: 'x' }] : [] }, telegram: { bugun_n: null, son: [], zaman: null },
      tarama: { puanlar: [], zaman: durum ? kapiZ : null, esik_dk: ESIK_DK },
      kapi: { bugun_gecen_n: null, bugun_elenen_n: null, zaman: z, esik_dk: ESIK_DK },
      arsiv: { turler: [], zaman: null }, onkayit_kasasi: { surum: null, commit: null, dondurma_tarihi: null, zaman: null },
      oda_sayilar: {
        tarama: durum ? [['Evren', evren], ['İşlenen', islenen], ['Kapsam', kapsam], ['Hesap sürümü', durum.hesap || null]] : [],
        kapi: [['Havuz', kolSayi('havuz')], ['Aday', kolSayi('aday')], ['Oda', kolSayi('oda')]]
      },
      oda_durum: onaylandi ? {} : { lab: { gri: true, metin: GRI }, finans: { gri: true, metin: GRI }, risk: { gri: true, metin: GRI }, kontrol: { gizli: true } },
      oda_kaynak: { lab: ['veri_kalitesi:lab'], aday: ['katlar:aday'], oda: ['katlar:oda'], kontrol: ['kohort_kontrol'], finans: ['kasa', 'kohort_kontrol'], risk: ['risk'], tarama: ['veri_kalitesi:tarama', 'tarama'], kapi: ['kapi'], sekreterlik: ['kohort_kontrol'] },
      ekran_kaynak: { 'tarama.tv': 'tarama', 'aday.tv': 'katlar:aday' }
    };
  }

  /* ağ: (0) son.json işaretçisi (varsa yalnız ham dosyalar: API yok), yoksa (1) ağaç — tek API çağrısı; (2) secim.json, (3) durum.json. fetchFn: fetch uyumlu. */
  async function yukle(fetchFn, opt) {
    opt = opt || {};
    const oku = async url => { const r = await fetchFn(url, { cache: 'no-store' }); if (!r.ok) throw new Error(url.replace(/^https:\/\/[^/]+\//, '') + ' → HTTP ' + r.status); return r.json(); };
    let sonJ = null;
    try { sonJ = await oku(HAM + 'son.json'); } catch (e) { sonJ = null; }                       // yayıncı işaretçisi: API çağrısı gerekmez
    let secimKlasor, durumlar = [];
    if (sonJ && sonJ.secim) secimKlasor = sonJ.secim;
    else {
      const agac = await oku(AGAC);
      if (agac.truncated) throw new Error('veri dalı ağacı kesildi (truncated); son.json işaretçisi gerekir');
      const son = enSon(agac);
      if (!son.secim) throw new Error('veri dalında secim/<tarih>/secim.json yok');
      secimKlasor = son.secim; durumlar = son.durumlar;
    }
    const secim = await oku(HAM + 'secim/' + secimKlasor + '/secim.json');
    const kt = sonJ && sonJ.secim ? (secim.kapi_tarihi || sonJ.kapi || null) : kapiTarihi(secim, durumlar);
    const durum = kt ? await oku(HAM + 'copytrade/kapi/' + kt + '/durum.json') : null;
    let izleme = null;
    try { izleme = await oku(IZLEME_HAM); } catch (e) { izleme = null; }
    return cevir(secim, durum, { simdi: opt.simdi, kapiTarihi: kt, izleme: izleme });
  }

  return { AGAC: AGAC, HAM: HAM, IZLEME_HAM: IZLEME_HAM, GRI: GRI, enSon: enSon, kapiTarihi: kapiTarihi, cevir: cevir, yukle: yukle };
});
