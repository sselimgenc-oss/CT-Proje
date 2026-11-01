/* Gerçek veri uyarlayıcı testleri:  node ofis/test/gercek.test.js   (ağ yok; elle hesaplanmış altın değerler) */
'use strict';
const G = require('../gercek.js'), F = require('./fixture.js');
let bad = 0;
const ok = (n, c, x) => { if (!c) bad++; console.log((c ? 'OK   ' : 'FAIL ') + n + (x !== undefined && x !== '' ? ' → ' + x : '')); };
const SIMDI = new Date('2026-10-29T12:00:00Z');

/* ağaç: tek API çağrısı; en son seçim klasörü adla sıralanır ("<tarih>-v1.3" aynı günkü "<tarih>"ten sonra gelir) */
const son = G.enSon(F.agac(['2026-10-27', '2026-10-28', '2026-10-28-v1.3'], ['2026-10-27', '2026-10-28']));
ok('en son seçim klasörü: 2026-10-28-v1.3', son.secim === '2026-10-28-v1.3', son.secim);
ok('kapı tarihleri sıralı', son.durumlar.join() === '2026-10-27,2026-10-28');
ok('seçim yoksa null', G.enSon(F.agac([], ['2026-10-28'])).secim === null);
ok('kapı tarihi: secim.json kapi_tarihi varsa o', G.kapiTarihi({ kapi_tarihi: '2026-10-27', tarih: '2026-10-28' }, son.durumlar) === '2026-10-27');
ok('kapı tarihi: yoksa seçim tarihinden önceki/aynı en son', G.kapiTarihi({ tarih: '2026-10-28' }, ['2026-10-27', '2026-10-28', '2026-10-30']) === '2026-10-28');

const d = G.cevir(F.secim('2026-10-28', null), F.durum, { simdi: SIMDI, kapiTarihi: '2026-10-28' });
const ids = k => d.traderlar.filter(t => t.kat === k).map(t => t.id);
ok('şema sürümü 1, kaynak ornek değil', d.surum === 1 && !/^ornek/.test(d.kaynak), d.kaynak);
ok('uretildi = verilen şimdi (veri yaşları gerçek saate göre)', d.uretildi === '2026-10-29T12:00:00.000Z');
ok('oda: 6 gerçek trader (O01..O06), sıra: aday sırası sonra tarz', ids('oda').join() === 'O01,O02,O03,O04,O05,O06');
ok('aday: yalnız odada olmayan 3 aday (A01..A03)', ids('aday').join() === 'A01,A02,A03');
ok('kontrol, taban, havuz figürü yok', d.traderlar.length === 9 && !d.traderlar.some(t => ['kontrol', 'lab'].includes(t.kat)));
const o1 = d.traderlar[0];
ok('takma ad = adresin ilk 4 hanesi, tarz, kaldırıcı, sıra', o1.takma_ad === 'a01a' && o1.tarz === 'intraday' && o1.en_yuksek_kaldirac === 3 && o1.sira === 1, JSON.stringify(o1));
ok('kısa adres 0x…son4', /^0x[0-9a-f]{4}…[0-9a-f]{4}$/.test(o1.adres), o1.adres);
ok('genç aday işareti taşınır', d.traderlar.find(t => t.id === 'O06').genc_aday === true && o1.genc_aday === false);
/* körlük: puan, kâr/zarar, kol karşılaştırması taşınmaz */
const metin = JSON.stringify(d);
ok('körlük: hiçbir trader puan taşımaz', d.traderlar.every(t => !('puan' in t)));
ok('körlük: kasa/özet/işlem/olay boş, K/Z yok', d.kasa.deger_usd === null && d.ozet.bugun_kz_usd === null && d.acik_islemler.length === 0 && d.kapananlar.length === 0 && d.olaylar.length === 0 && d.gecmis_olaylar.length === 0);
ok('körlük: seçimdeki puan değeri (0.123456) hiçbir yerde yok', !/0\.123456|0\.9[0-9]?\b/.test(metin.replace(/"tohum":\d+/, '')));
ok('pilot görünümü: performans kilitli değil, tarama puanı taşınmaz', d.kohort_kontrol.performans_kilitli === false && d.tarama.puanlar.length === 0);
/* sayılar */
ok('katlar: havuz 30 · aday 9 · oda 6 · kontrol sayısı 5', d.katlar.havuz.n === 30 && d.katlar.aday.n === 9 && d.katlar.oda.n === 6 && d.katlar.kontrol.n === 5);
ok('masa: lab 0, aday 3, oda 6, kontrol 0', d.katlar.havuz.masa === 0 && d.katlar.aday.masa === 3 && d.katlar.oda.masa === 6 && d.katlar.kontrol.masa === 0);
ok('tarama odası: evren, işlenen, kapsam, hesap sürümü', JSON.stringify(d.oda_sayilar.tarama) === JSON.stringify([['Evren', 13710], ['İşlenen', 13767], ['Kapsam', '%100'], ['Hesap sürümü', 'v1.1-2026-10-27d']]), JSON.stringify(d.oda_sayilar.tarama));
ok('kapı odası: havuz, aday, oda', JSON.stringify(d.oda_sayilar.kapi) === JSON.stringify([['Havuz', 30], ['Aday', 9], ['Oda', 6]]));
ok('kontrol kolu: yalnız sayı, kohort kartında (n=5)', d.kohort_kontrol.kollar.some(k => /Kontrol/.test(k.ad) && k.n === 5) && d.oda_durum.kontrol.gizli === true);
ok('finans, risk, lab gri: "sanal izleme başlamadı"', ['lab', 'finans', 'risk'].every(r => d.oda_durum[r].gri && d.oda_durum[r].metin === 'sanal izleme başlamadı'));
ok('tarama veri kalitesi satırı durum.json sayılarını taşır', d.veri_kalitesi[0].deger === 'evren 13.710 · işlenen 13.767 · kapsam %100', d.veri_kalitesi[0].deger);
ok('verisi olmayan kalite satırları "bilinmiyor", sıfır değil', d.veri_kalitesi.slice(1).every(v => v.durum === 'bilinmiyor' && v.deger === null && v.zaman === null));
ok('seçim sürümü v1 (secim.json sürüm vermiyorsa), tarih', d.secim.surum === 'v1' && d.secim.tarih === '2026-10-28' && d.secim.onaylandi === false);
const d13 = G.cevir(F.secim('2026-10-28', 'v1.3'), null, { simdi: SIMDI });
ok('v1.3: sürüm etiketi; kapı durumu yoksa tarama satırı bilinmiyor', d13.secim.surum === 'v1.3' && d13.veri_kalitesi[0].durum === 'bilinmiyor' && d13.oda_sayilar.tarama.length === 0);
const sCanli = F.secim('2026-10-28', 'v1.3'), aCanli = Object.keys(sCanli.adresler)[0];
const izleme = { uretildi: '2026-10-29T12:00:00Z', traderlar: [{ id: 'O01', adres: aCanli, takma_ad: 'a001', secim: 'v1.3@2026-10-28', kol: 'oda', kollar: ['oda'], hesap_degeri: 10000, saglik: { isik: 'yesil', nedenler: [] }, pozisyonlar: [
  { coin: 'BTC', yon: 'long', kaldirac: 3, anlik_kz_usd: -29.5, buyukluk_usd: 3000, acilis: '2026-10-29T10:00:00Z' },
  { coin: 'ETH', yon: 'short', kaldirac: 5, anlik_kz_usd: 12.25, acilis: '2026-10-29T11:30:00Z' }
], sanal_kopya_v3: { baslangic_usd: 1000, bakiye_usd: 1012, getiri: .012 }}, { id: 'K01', adres: Object.keys(sCanli.adresler)[1], takma_ad: 'k001', secim: 'v1.3@2026-10-28', kol: 'kontrol', kollar: ['kontrol'], saglik: { isik: 'yesil', nedenler: [] }, pozisyonlar: [{ coin: 'SOL', yon: 'long', kaldirac: 2, anlik_kz_usd: 5, acilis: '2026-10-29T11:00:00Z' }], sanal_kopya_v3: { baslangic_usd: 1000, bakiye_usd: 990, getiri: -.01 }}, { id: 'R01', adres: Object.keys(sCanli.adresler)[2], takma_ad: 'r001', secim: 'v1.3@2026-10-28', kol: 'referans_oda', kollar: ['referans_oda'], saglik: { isik: 'yesil', nedenler: [] }, pozisyonlar: [], sanal_kopya_v3: { baslangic_usd: 1000, bakiye_usd: 900, getiri: -.1 }}], olaylar: [{ id: 'O01-1-acilis', zaman: '2026-10-29T11:00:00Z', trader: 'O01', tur: 'acilis', coin: 'BTC', yon: 'long' }, { id: 'X-1-acilis', zaman: '2026-10-29T11:00:00Z', trader: 'X', tur: 'acilis', coin: 'ETH', yon: 'long' }] };
const canli = G.cevir(sCanli, F.durum, { simdi: SIMDI, kapiTarihi: '2026-10-28', izleme: izleme });
ok('altın örnek: oda kasası kontrol ve referanstan ayrıdır; bilinmeyen olay Diğer olur', canli.secim.onaylandi && canli.kasa.deger_usd === 1012 && canli.kasa.kontrol_deger_usd === 990 && canli.traderlar.some(t => t.id === 'R01' && t.kat === 'referans') && canli.gecmis_olaylar.some(e => e.trader === 'X' && e.oda === 'diger') && !canli.oda_durum.lab, JSON.stringify(canli.kasa));
const ozetliIzleme = JSON.parse(JSON.stringify(izleme));
ozetliIzleme.canli_oda_ozeti = { surum: 1, v3_hesaplanabilir_n: 2, v3_baslangic_toplam_usd: 2000, v3_bakiye_toplam_usd: 2080,
  getiri_toplam: { deger: 0.04, payda_n: 2 }, getiri_ortalama: { deger: 0.05, payda_n: 2 }, kasa_egrisi_usd: [['2026-10-27', 2000], ['2026-10-28', 2080]] };
const ozetOncelik = G.cevir(sCanli, F.durum, { simdi: SIMDI, kapiTarihi: '2026-10-28', izleme: ozetliIzleme });
ok('canli_oda_ozeti önceliklidir: kasa ve eğri tarayıcı toplamı yerine hazır özetten gelir', ozetOncelik.kasa.deger_usd === 2080 && ozetOncelik.kasa.baslangic_usd === 2000 && ozetOncelik.kasa.getiri_toplam === 0.04 && JSON.stringify(ozetOncelik.kasa.egri) === JSON.stringify(ozetliIzleme.canli_oda_ozeti.kasa_egrisi_usd), JSON.stringify(ozetOncelik.kasa));
ok('canli_oda_ozeti ortalama getirisi ve paydası korunur', ozetOncelik.kasa.getiri_ortalama === 0.05 && ozetOncelik.kasa.getiri_ortalama_n === 2 && ozetOncelik.kohort_kontrol.kollar[0].n === 2);
const bosOzetIzleme = JSON.parse(JSON.stringify(izleme));
bosOzetIzleme.canli_oda_ozeti = { surum: 1, v3_hesaplanabilir_n: 0, v3_baslangic_toplam_usd: null, v3_bakiye_toplam_usd: null,
  getiri_toplam: { deger: null, payda_n: 0 }, getiri_ortalama: { deger: null, payda_n: 0 }, kasa_egrisi_usd: [] };
const bosOzet = G.cevir(sCanli, F.durum, { simdi: SIMDI, kapiTarihi: '2026-10-28', izleme: bosOzetIzleme });
ok('hazır özet n=0: kasa/getiri null kalır, sıfır veya trader satırlarından türetilmez', bosOzet.kasa.deger_usd === null && bosOzet.kasa.getiri_toplam === null && bosOzet.kasa.getiri_ortalama === null && bosOzet.kohort_kontrol.kollar[0].n === 0 && bosOzet.kasa.egri.length === 0);
/* açık işlemler: durum.json'daki oda üyelerinin pozisyonlar listesinden (yalnız kollar:['oda']; kontrol/referans dışarıda) */
ok('açık işlemler: yalnız oda üyelerinden (2), kontrol üyesinin pozisyonu alınmaz', canli.acik_islemler.length === 2 && canli.acik_islemler.every(x => x.trader === 'O01'), JSON.stringify(canli.acik_islemler));
const btc = canli.acik_islemler.find(x => x.coin === 'BTC'), eth = canli.acik_islemler.find(x => x.coin === 'ETH');
ok('altın örnek (BTC): yön/kaldıraç taşınır, K/Z 1.000 $ ölçeğinde (−29,5 × 1000 / 10.000 = −2,95), süre = uretildi − açılış (120 dk)', btc && btc.yon === 'long' && btc.kaldirac === 3 && Math.abs(btc.kz_usd + 2.95) < 1e-9 && btc.yas_dk === 120, JSON.stringify(btc));
ok('altın örnek (ETH): short, 30 dk önce açıldı', eth && eth.yon === 'short' && eth.kaldirac === 5 && Math.abs(eth.kz_usd - 1.225) < 1e-9 && eth.yas_dk === 30, JSON.stringify(eth));
ok('sahte veri yok: yüzde/likidasyon uydurulmaz; teminat yalnız büyüklük varsa (BTC: 3000 × 1000 / 10.000 / 3 = 100 $), yoksa null (ETH)', canli.acik_islemler.every(x => x.kz_yuzde === null && x.lik_uzaklik === null) && Math.abs(btc.teminat_usd - 100) < 1e-9 && eth.teminat_usd === null, JSON.stringify([btc.teminat_usd, eth.teminat_usd]));
/* gölge kasası günü: t0'dan bu yana gün sayısı (t0 günü = 1), hafta × 7 değil (lider denetimi: "n=7 gün" → bugün 1 hatasıydı) */
ok('kasa.gun_n: t0\'dan bu yana gün (hafta × 7 değil)', canli.kasa.gun_n === Math.floor((SIMDI.getTime() - Date.parse('2026-10-28T00:00:00Z')) / 86400000) + 1 && canli.kasa.gun_n !== canli.kohort_kontrol.hafta * 7, 'gun_n=' + canli.kasa.gun_n + ' hafta=' + canli.kohort_kontrol.hafta);

/* canlı yol sözleşmesi: tek ağaç çağrısı + iki ham dosya, doğru adreslerle */
(async () => {
  const istek = [];
  const sahteFetch = async (url) => {
    istek.push(url);
    if (url === G.HAM + 'son.json') return { ok: false, status: 404, json: async () => ({}) };      // işaretçi yok → ağaç yoluna düşer
    const yanit = b => ({ ok: true, status: 200, json: async () => b });
    if (url === G.AGAC) return yanit(F.agac(['2026-10-28'], ['2026-10-27', '2026-10-28']));
    if (url === G.HAM + 'secim/2026-10-28/secim.json') return yanit(F.secim('2026-10-28', null));
    if (url === G.HAM + 'copytrade/kapi/2026-10-28/durum.json') return yanit(F.durum);
    return { ok: false, status: 404, json: async () => ({}) };
  };
  const g = await G.yukle(sahteFetch, { simdi: SIMDI });
  ok('sözleşme: ağaç adresi git/trees/copytrade-kapi?recursive=1 (kimliksiz tek çağrı)', istek[1] === 'https://api.github.com/repos/sselimgenc-oss/sg-arge/git/trees/copytrade-kapi?recursive=1', istek[1]);
  ok('sözleşme: ham adresler raw.githubusercontent.com/…/copytrade-kapi/secim/<tarih>/secim.json ve copytrade/kapi/<tarih>/durum.json',
    istek[2] === 'https://raw.githubusercontent.com/sselimgenc-oss/sg-arge/copytrade-kapi/secim/2026-10-28/secim.json' && istek[3] === 'https://raw.githubusercontent.com/sselimgenc-oss/sg-arge/copytrade-kapi/copytrade/kapi/2026-10-28/durum.json', istek.join(' | '));
ok('sözleşme: canlı izleme de okunur; yoksa sahte veriye düşmez', istek.length === 5 && istek[4] === G.IZLEME_HAM && g.traderlar.length === 9);
  /* son.json işaretçisi varsa API hiç çağrılmaz */
  const istek2 = [];
  const g2 = await G.yukle(async (url) => {
    istek2.push(url);
    const yanit = b => ({ ok: true, status: 200, json: async () => b });
    if (url === G.HAM + 'son.json') return yanit({ kapi: '2026-10-28', secim: '2026-10-28', uretildi: '2026-10-28T06:00:00Z' });
    if (url === G.HAM + 'secim/2026-10-28/secim.json') return yanit(F.secim('2026-10-28', null));
    if (url === G.HAM + 'copytrade/kapi/2026-10-28/durum.json') return yanit(F.durum);
    return { ok: false, status: 404, json: async () => ({}) };
  }, { simdi: SIMDI });
ok('son.json varsa: 4 ham dosya, API çağrısı yok', istek2.length === 4 && !istek2.some(u => /api\.github\.com/.test(u)) && g2.traderlar.length === 9, istek2.join(' | '));
  let hata = null;
  try { await G.yukle(async () => ({ ok: false, status: 403, json: async () => ({}) }), { simdi: SIMDI }); } catch (e) { hata = e.message; }
  ok('API sınırı (403) → açık hata, sessiz örnek yok', /HTTP 403/.test(hata || ''), hata);
  try { hata = null; await G.yukle(async () => ({ ok: true, status: 200, json: async () => ({ truncated: true, tree: [] }) }), { simdi: SIMDI }); } catch (e) { hata = e.message; }
  ok('kesilmiş ağaç → açık hata', /truncated/.test(hata || ''), hata);
  console.log(bad ? '\n' + bad + ' test başarısız' : '\nhepsi geçti');
  process.exit(bad ? 1 : 0);
})();
