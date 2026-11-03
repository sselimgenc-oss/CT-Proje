/**
 * Hyperliquid Perps Pano — Terminal Sürümü
 * Güvenlik: Yalnızca VERI_URL okunur. API anahtarı, token veya emir/işlem düğmesi bulunmaz.
 * HTML kaçışı ve kesin veri doğrulaması içerir.
 */

const VERI_URL = 'ornek_veri.json';

// Durum değişkenleri
let panoVerisi = null;
let aktifTakimAdi = 'İlk 11';
let acikIslemlerGenisletildi = false;
let yenilemeSayaci = 60;
let sayacInterval = null;

// Trader sıralama durumu
let traderSiralama = {
  sutun: 'net_oran',
  artan: false
};

// ==========================================
// 1. GÜVENLİK VE HTML KAÇIŞI (HIP-3 Koruması)
// ==========================================
function kacis(metin) {
  if (metin === undefined || metin === null) return '';
  return String(metin)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

const BILINEN_NEDENLER = ['trader_kapatti', 'trader_azaltti', 'yon_degisti', 'stop', 'tasfiye'];
function guvenliNedenSinifi(neden) {
  return BILINEN_NEDENLER.includes(neden) ? neden : 'bilinmeyen';
}

// ==========================================
// 2. TEMA YÖNETİMİ (localStorage Korumalı)
// ==========================================
function temaBaslat() {
  let kayitliTema = 'dark';
  try {
    kayitliTema = localStorage.getItem('hl_pano_tema') || 'dark';
  } catch (e) {
    kayitliTema = 'dark';
  }

  temaUygula(kayitliTema);

  const temaButonu = document.getElementById('tema-degistir-btn');
  if (temaButonu) {
    temaButonu.addEventListener('click', () => {
      const suankiTema = document.body.classList.contains('light-theme') ? 'light' : 'dark';
      const yeniTema = suankiTema === 'dark' ? 'light' : 'dark';
      temaUygula(yeniTema);
      try {
        localStorage.setItem('hl_pano_tema', yeniTema);
      } catch (e) {}
    });
  }
}

function temaUygula(tema) {
  const temaButonu = document.getElementById('tema-degistir-btn');
  if (tema === 'light') {
    document.body.classList.add('light-theme');
    if (temaButonu) temaButonu.innerHTML = '🌙 Koyu Tema';
  } else {
    document.body.classList.remove('light-theme');
    if (temaButonu) temaButonu.innerHTML = '☀️ Açık Tema';
  }
}

// ==========================================
// 3. SAYI, ORAN VE FİYAT BİÇİMLENDİRME
// ==========================================
function formatPara(deger, zorlaIsaret = false) {
  if (deger === undefined || deger === null || isNaN(deger)) return '— $';
  const absVal = Math.abs(deger);
  const formatted = new Intl.NumberFormat('tr-TR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(absVal);

  if (zorlaIsaret) {
    if (deger > 0.0001) return `+${formatted} $`;
    if (deger < -0.0001) return `-${formatted} $`;
    return `${formatted} $`;
  }
  return `${deger < 0 ? '-' : ''}${formatted} $`;
}

function formatOran(oran, zorlaIsaret = false, basamak = 2) {
  if (oran === undefined || oran === null || isNaN(oran)) return '—';
  const yuzde = Math.abs(oran * 100);
  const minDigits = basamak === 0 ? 0 : 1;
  const maxDigits = Math.max(minDigits, basamak);

  const formatted = new Intl.NumberFormat('tr-TR', {
    minimumFractionDigits: minDigits,
    maximumFractionDigits: maxDigits
  }).format(yuzde);

  if (zorlaIsaret) {
    if (oran > 0.00001) return `+%${formatted}`;
    if (oran < -0.00001) return `-%${formatted}`;
    return `%${formatted}`;
  }
  return `${oran < 0 ? '-' : ''}%${formatted}`;
}

function formatOndalik(deger, basamak = 2) {
  if (deger === undefined || deger === null || isNaN(deger)) return '—';
  return new Intl.NumberFormat('tr-TR', {
    minimumFractionDigits: basamak,
    maximumFractionDigits: basamak
  }).format(deger);
}

// Fiyat biçimi: 1'in altındaki fiyatlarda 4–6 anlamlı basamak, büyük fiyatlarda 2 ondalık
function formatFiyat(v) {
  if (v === undefined || v === null || isNaN(v)) return '—';
  const num = Number(v);
  if (num === 0) return '0,00';
  const abs = Math.abs(num);
  if (abs >= 1) {
    return new Intl.NumberFormat('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(num);
  }
  return new Intl.NumberFormat('tr-TR', { maximumSignificantDigits: 6 }).format(num);
}

function formatSaatTr(isoStr) {
  if (!isoStr) return '—';
  try {
    const d = new Date(isoStr);
    return new Intl.DateTimeFormat('tr-TR', {
      timeZone: 'Europe/Istanbul',
      hour: '2-digit',
      minute: '2-digit'
    }).format(d);
  } catch (e) {
    return isoStr;
  }
}

function formatTarihSaatTr(isoStr) {
  if (!isoStr) return '—';
  try {
    const d = new Date(isoStr);
    return new Intl.DateTimeFormat('tr-TR', {
      timeZone: 'Europe/Istanbul',
      day: '2-digit',
      month: '2-digit',
      hour: '2-digit',
      minute: '2-digit'
    }).format(d);
  } catch (e) {
    return isoStr;
  }
}

function formatKisaTarihTr(dateStr) {
  if (!dateStr) return '—';
  try {
    const d = new Date(dateStr);
    return new Intl.DateTimeFormat('tr-TR', {
      timeZone: 'Europe/Istanbul',
      day: 'numeric',
      month: 'short'
    }).format(d);
  } catch (e) {
    return dateStr;
  }
}

function yasHesapla(acilisIso, referansIso) {
  if (!acilisIso) return '—';
  const t1 = new Date(acilisIso).getTime();
  const t2 = referansIso ? new Date(referansIso).getTime() : Date.now();
  if (isNaN(t1)) return '—';
  let diffMs = t2 - t1;
  if (diffMs < 0) diffMs = 0;

  const toplamDk = Math.floor(diffMs / (1000 * 60));
  const gun = Math.floor(toplamDk / (60 * 24));
  const sa = Math.floor((toplamDk % (60 * 24)) / 60);
  const dk = toplamDk % 60;

  if (gun > 0) return `${gun} gün ${sa} sa`;
  if (sa > 0) return `${sa} sa ${dk} dk`;
  return `${Math.max(1, dk)} dk`;
}

function sureHesapla(acilisIso, kapanisIso) {
  if (!acilisIso || !kapanisIso) return '—';
  const t1 = new Date(acilisIso).getTime();
  const t2 = new Date(kapanisIso).getTime();
  if (isNaN(t1) || isNaN(t2)) return '—';
  let diffMs = Math.abs(t2 - t1);

  const toplamDk = Math.floor(diffMs / (1000 * 60));
  const gun = Math.floor(toplamDk / (60 * 24));
  const sa = Math.floor((toplamDk % (60 * 24)) / 60);
  const dk = toplamDk % 60;

  if (gun > 0) return `${gun} gün ${sa} sa`;
  if (sa > 0) return `${sa} sa ${dk} dk`;
  return `${Math.max(1, dk)} dk`;
}

function turkceNeden(nedenKodu) {
  const nedenler = {
    'trader_kapatti': 'Trader kapattı',
    'trader_azaltti': 'Azalttı',
    'yon_degisti': 'Yön değişti',
    'stop': 'Stop',
    'tasfiye': 'Tasfiye'
  };
  return nedenler[nedenKodu] || nedenKodu || '—';
}

function kzSinifi(deger) {
  if (deger === undefined || deger === null || isNaN(deger)) return 'neutral';
  if (deger > 0.00001) return 'profit';
  if (deger < -0.00001) return 'loss';
  return 'neutral';
}

// ==========================================
// 4. TOOLTIP YÖNETİMİ
// ==========================================
let tooltipEl = null;

function setupTooltip() {
  tooltipEl = document.getElementById('chart-tooltip');
  if (!tooltipEl) {
    tooltipEl = document.createElement('div');
    tooltipEl.id = 'chart-tooltip';
    tooltipEl.className = 'chart-tooltip';
    document.body.appendChild(tooltipEl);
  }
}

function showTooltip(e, text) {
  if (!tooltipEl) setupTooltip();
  tooltipEl.innerHTML = kacis(text);
  tooltipEl.classList.add('visible');
  moveTooltip(e);
}

function moveTooltip(e) {
  if (!tooltipEl) return;
  const x = e.clientX + 12;
  const y = e.clientY - 28;
  tooltipEl.style.left = `${x}px`;
  tooltipEl.style.top = `${y}px`;
}

function hideTooltip() {
  if (!tooltipEl) return;
  tooltipEl.classList.remove('visible');
}

// ==========================================
// 5. VERİ YÜKLEME VE KONTROL
// ==========================================
async function veriyiYukle() {
  const hataKutusu = document.getElementById('hata-kutusu');
  const hataMetni = document.getElementById('hata-metni');
  const yenilemeIkon = document.getElementById('yenileme-ikon');

  if (yenilemeIkon) yenilemeIkon.style.opacity = '0.4';

  try {
    const url = `${VERI_URL}?_t=${Date.now()}`;
    const yanit = await fetch(url, {
      method: 'GET',
      headers: { 'Accept': 'application/json' }
    });

    if (!yanit.ok) {
      throw new Error(`HTTP ${yanit.status}`);
    }

    const veri = await yanit.json();
    if (!veri || !veri.takimlar || !Array.isArray(veri.takimlar)) {
      throw new Error('Veri formatı geçersiz: "takimlar" bulunamadı.');
    }

    panoVerisi = veri;
    yenilemeSayaci = 60;

    if (hataKutusu) hataKutusu.classList.add('hidden');

    panoyuGuncelle();
  } catch (err) {
    console.error('Veri yükleme hatası:', err);
    if (hataKutusu && hataMetni) {
      hataMetni.textContent = `Veri yüklenemedi: ${kacis(err.message)}. Otomatik tekrar denenecektir.`;
      hataKutusu.classList.remove('hidden');
    }
  } finally {
    if (yenilemeIkon) yenilemeIkon.style.opacity = '1';
  }
}

// ==========================================
// 6. ANA PANONUN ÇİZİLMESİ
// ==========================================
function panoyuGuncelle() {
  if (!panoVerisi) return;

  // 1. Durum Şeridi (Status Bar)
  durumSeridiniGuncelle();

  // 2. Takım sekmeleri
  sekmeleriCiz();

  // 3. Aktif Takım
  let aktifTakim = panoVerisi.takimlar.find(t => t.ad === aktifTakimAdi);
  if (!aktifTakim && panoVerisi.takimlar.length > 0) {
    aktifTakim = panoVerisi.takimlar[0];
    aktifTakimAdi = aktifTakim.ad;
  }
  if (!aktifTakim) return;

  // 4. Üst Şerit Metrik Kutuları (9 Metrik)
  ustSeritMetrikleriniCiz(aktifTakim);

  // 5. Kasa Kartı ve Özet
  kasaKartiniCiz(aktifTakim);

  // 6. 4 Adet Inline SVG Grafik
  grafikleriCiz(aktifTakim);

  // 7. Trader Tablosu (Sıralanabilir)
  traderTablosunuCiz(aktifTakim);

  // 8. Açık İşlemler Tablosu
  acikIslemleriCiz(aktifTakim);

  // 9. Son Kapananlar Tablosu
  sonKapananlariCiz(aktifTakim);

  // Alt bilgi
  const footerZaman = document.getElementById('son-veri-saat');
  if (footerZaman && panoVerisi.uretildi) {
    footerZaman.textContent = `Son veri üretim zamanı: ${kacis(formatTarihSaatTr(panoVerisi.uretildi))} (TSİ)`;
  }
}

// 4. Durum Şeridi
function durumSeridiniGuncelle() {
  const dinleyici = panoVerisi.dinleyici || {};
  const durumDinleyici = document.getElementById('durum-dinleyici');
  const durumSaat = document.getElementById('durum-saat');

  if (durumDinleyici) {
    // 1. Düzeltme: '0,29' ve 0 yedekleri kaldırıldı; alan yoksa '—' gösterilir
    const medyanStr = (dinleyici.gecikme_medyan_sn !== undefined && dinleyici.gecikme_medyan_sn !== null)
      ? `${formatOndalik(dinleyici.gecikme_medyan_sn, 2)} sn`
      : '—';
    const kacanStr = (dinleyici.kacan !== undefined && dinleyici.kacan !== null)
      ? kacis(dinleyici.kacan)
      : '—';

    durumDinleyici.innerHTML = `Dinleyici: gecikme medyanı <strong>${medyanStr}</strong> · kaçan <strong>${kacanStr}</strong>`;
  }

  if (durumSaat && panoVerisi.uretildi) {
    durumSaat.textContent = `TSİ ${kacis(formatSaatTr(panoVerisi.uretildi))}`;
  }

  // Tazelik uyarısı (2,5 saatten eskiyse sarı uyarı)
  const uyariKutusu = document.getElementById('uyari-kutusu');
  const uyariMetni = document.getElementById('uyari-metni');
  if (uyariKutusu && uyariMetni && panoVerisi.uretildi) {
    const uretildiZaman = new Date(panoVerisi.uretildi).getTime();
    const farkSaat = (Date.now() - uretildiZaman) / (1000 * 60 * 60);

    if (farkSaat > 2.5) {
      const saatBicimli = new Intl.NumberFormat('tr-TR', { maximumFractionDigits: 1 }).format(farkSaat);
      uyariMetni.textContent = `Veri ${saatBicimli} saat önce güncellendi`;
      uyariKutusu.classList.remove('hidden');
    } else {
      uyariKutusu.classList.add('hidden');
    }
  }
}

// Sekmeler
function sekmeleriCiz() {
  const container = document.getElementById('takim-sekmeleri');
  if (!container || !panoVerisi) return;

  container.innerHTML = '';
  panoVerisi.takimlar.forEach(takim => {
    const btn = document.createElement('button');
    btn.className = `tab-btn ${takim.ad === aktifTakimAdi ? 'active' : ''}`;
    btn.textContent = takim.ad;
    btn.addEventListener('click', () => {
      aktifTakimAdi = takim.ad;
      acikIslemlerGenisletildi = false;
      panoyuGuncelle();
    });
    container.appendChild(btn);
  });
}

// 1. Üst Şerit Metrik Kutuları (Uydurma varsayılanlar olmadan)
function ustSeritMetrikleriniCiz(takim) {
  const metrik = takim.metrik || {};

  // 1. Bugün %
  const bugunEl = document.getElementById('strip-bugun');
  if (bugunEl) {
    bugunEl.textContent = formatOran(metrik.bugun_oran, true);
    bugunEl.className = `strip-val ${kzSinifi(metrik.bugun_oran)}`;
  }

  // 2. Bu Hafta %
  const haftaEl = document.getElementById('strip-hafta');
  if (haftaEl) {
    haftaEl.textContent = formatOran(metrik.hafta_oran, true);
    haftaEl.className = `strip-val ${kzSinifi(metrik.hafta_oran)}`;
  }

  // 3. Bu Ay %
  const ayEl = document.getElementById('strip-ay');
  if (ayEl) {
    ayEl.textContent = formatOran(metrik.ay_oran, true);
    ayEl.className = `strip-val ${kzSinifi(metrik.ay_oran)}`;
  }

  // 4. Açık Pozisyon & Maruziyet %
  const pozEl = document.getElementById('strip-pozisyon');
  const maruziyetEl = document.getElementById('strip-maruziyet');
  if (pozEl) {
    const count = (takim.acik && Array.isArray(takim.acik)) ? takim.acik.length : '—';
    pozEl.textContent = count;
  }
  if (maruziyetEl) {
    maruziyetEl.textContent = (metrik.maruziyet_oran !== undefined && metrik.maruziyet_oran !== null)
      ? `${formatOran(metrik.maruziyet_oran, false, 0)} maruziyet`
      : '—';
  }

  // 5. Toplam Getiri %
  const toplamEl = document.getElementById('strip-toplam');
  if (toplamEl) {
    toplamEl.textContent = formatOran(metrik.toplam_oran, true);
    toplamEl.className = `strip-val ${kzSinifi(metrik.toplam_oran)}`;
  }

  // 6. Kazanma Oranı (Yarım Halka Gösterge) - 0.5 uydurması kaldırıldı
  const winTxt = document.getElementById('strip-kazanma-txt');
  const winGauge = document.getElementById('strip-kazanma-gauge');
  const totalTrades = document.getElementById('strip-toplam-islem');

  const hasWinRate = metrik.kazanma_orani !== undefined && metrik.kazanma_orani !== null;

  if (winTxt) {
    winTxt.textContent = hasWinRate ? formatOran(metrik.kazanma_orani, false, 0) : '—';
    winTxt.className = `strip-val ${hasWinRate ? kzSinifi(metrik.kazanma_orani - 0.5) : 'neutral'}`;
  }

  if (totalTrades) {
    totalTrades.textContent = (metrik.islem_sayisi !== undefined && metrik.islem_sayisi !== null)
      ? `${metrik.islem_sayisi} işlem`
      : '—';
  }

  if (winGauge) {
    const radius = 14;
    const stroke = 3.5;
    const circumference = Math.PI * radius;

    if (hasWinRate) {
      const progress = Math.max(0, Math.min(1, metrik.kazanma_orani));
      const offset = circumference * (1 - progress);
      winGauge.innerHTML = `
        <svg viewBox="0 0 36 20">
          <path d="M 4 18 A 14 14 0 0 1 32 18" fill="none" stroke="var(--bg-subtle)" stroke-width="${stroke}" stroke-linecap="round"/>
          <path d="M 4 18 A 14 14 0 0 1 32 18" fill="none" stroke="var(--color-profit)" stroke-width="${stroke}"
                stroke-dasharray="${circumference}" stroke-dashoffset="${offset}" stroke-linecap="round"/>
        </svg>
      `;
    } else {
      // Değer yoksa boş gri halka
      winGauge.innerHTML = `
        <svg viewBox="0 0 36 20">
          <path d="M 4 18 A 14 14 0 0 1 32 18" fill="none" stroke="var(--bg-subtle)" stroke-width="${stroke}" stroke-linecap="round"/>
        </svg>
      `;
    }
  }

  // 7. Kâr Faktörü - Değer yoksa kırmızı değil nötr renk
  const pfEl = document.getElementById('strip-kar-faktoru');
  if (pfEl) {
    if (metrik.kar_faktoru !== undefined && metrik.kar_faktoru !== null) {
      pfEl.textContent = formatOndalik(metrik.kar_faktoru, 2);
      pfEl.className = `strip-val ${metrik.kar_faktoru >= 1.0 ? 'profit' : 'loss'}`;
    } else {
      pfEl.textContent = '—';
      pfEl.className = 'strip-val neutral';
    }
  }

  // 8. Ortalama Kazanç / Kayıp (İki Renkli Çubuk) - 0.02 / 0.01 uydurması kaldırıldı
  const barWin = document.getElementById('bar-win-seg');
  const barLoss = document.getElementById('bar-loss-seg');
  const lblWin = document.getElementById('strip-ort-kazanc');
  const lblLoss = document.getElementById('strip-ort-kayip');

  const hasWin = metrik.ort_kazanc_oran !== undefined && metrik.ort_kazanc_oran !== null;
  const hasLoss = metrik.ort_kayip_oran !== undefined && metrik.ort_kayip_oran !== null;

  if (hasWin && hasLoss) {
    const winAvg = Math.abs(metrik.ort_kazanc_oran);
    const lossAvg = Math.abs(metrik.ort_kayip_oran);
    const totalAvg = winAvg + lossAvg;
    const winPercent = totalAvg > 0 ? (winAvg / totalAvg) * 100 : 50;

    if (barWin) {
      barWin.style.width = `${winPercent.toFixed(1)}%`;
      barWin.style.display = 'block';
    }
    if (barLoss) {
      barLoss.style.width = `${(100 - winPercent).toFixed(1)}%`;
      barLoss.style.display = 'block';
    }
    if (lblWin) lblWin.textContent = formatOran(metrik.ort_kazanc_oran, true, 1);
    if (lblLoss) lblLoss.textContent = formatOran(metrik.ort_kayip_oran, true, 1);
  } else {
    // Alan yoksa çubuk gri kalsın, etiketler '—' olsun
    if (barWin) barWin.style.width = '0%';
    if (barLoss) barLoss.style.width = '0%';
    if (lblWin) lblWin.textContent = '—';
    if (lblLoss) lblLoss.textContent = '—';
  }

  // 9. İşlem Başı Beklenti %
  const expEl = document.getElementById('strip-beklenti');
  if (expEl) {
    expEl.textContent = formatOran(metrik.beklenti_oran, true);
    expEl.className = `strip-val ${kzSinifi(metrik.beklenti_oran)}`;
  }
}

// Kasa Kartı ve Özet (Uydurma 0'lar kaldırıldı)
function kasaKartiniCiz(takim) {
  const kasa = takim.kasa || {};
  const ozet = takim.ozet || {};

  const bakiyeEl = document.getElementById('kasa-bakiye');
  const degisimEl = document.getElementById('kasa-degisim');
  const takimAdEl = document.getElementById('kasa-takim-ad');

  if (takimAdEl) takimAdEl.textContent = kacis(takim.ad);
  if (bakiyeEl) bakiyeEl.textContent = formatPara(kasa.bakiye_usd);

  if (degisimEl) {
    const hasUsd = kasa.degisim_usd !== undefined && kasa.degisim_usd !== null;
    const hasOran = kasa.degisim_oran !== undefined && kasa.degisim_oran !== null;

    if (hasUsd || hasOran) {
      const cls = hasUsd ? kzSinifi(kasa.degisim_usd) : kzSinifi(kasa.degisim_oran);
      degisimEl.className = `kasa-change-line ${cls}`;
      const usdStr = hasUsd ? formatPara(kasa.degisim_usd, true) : '— $';
      const oranStr = hasOran ? formatOran(kasa.degisim_oran, true) : '—';
      degisimEl.innerHTML = `
        <span>${usdStr}</span>
        <span>·</span>
        <span>${oranStr}</span>
        <span style="color:var(--text-secondary);font-weight:400;">başlangıçtan</span>
      `;
    } else {
      degisimEl.className = 'kasa-change-line neutral';
      degisimEl.innerHTML = `
        <span>— $</span>
        <span>·</span>
        <span>—</span>
        <span style="color:var(--text-secondary);font-weight:400;">başlangıçtan</span>
      `;
    }
  }

  // Özet metinleri (|| 0 ve || 11 kaldırıldı, eksik değerler '—')
  const nakitEl = document.getElementById('ozet-nakit');
  const teminatEl = document.getElementById('ozet-teminat');
  const teminatAltEl = document.getElementById('ozet-teminat-alt');
  const kzEl = document.getElementById('ozet-kz');
  const kzAltEl = document.getElementById('ozet-kz-alt');
  const bugunEl = document.getElementById('ozet-bugun');
  const kadroEl = document.getElementById('ozet-kadro');

  if (nakitEl) nakitEl.textContent = formatPara(ozet.nakit_usd);
  if (teminatEl) teminatEl.textContent = formatPara(ozet.acik_teminat_usd);
  if (teminatAltEl) {
    teminatAltEl.textContent = (ozet.acik_islem !== undefined && ozet.acik_islem !== null)
      ? `${ozet.acik_islem} işlem`
      : '—';
  }

  if (kzEl) {
    if (ozet.acik_kz_usd !== undefined && ozet.acik_kz_usd !== null) {
      kzEl.textContent = formatPara(ozet.acik_kz_usd, true);
      kzEl.className = `mono-val ${kzSinifi(ozet.acik_kz_usd)}`;
    } else {
      kzEl.textContent = '— $';
      kzEl.className = 'mono-val neutral';
    }
  }

  if (kzAltEl) {
    if (ozet.son24_islem !== undefined && ozet.son24_islem !== null) {
      const winPart = (ozet.son24_kazanma_orani !== undefined && ozet.son24_kazanma_orani !== null)
        ? ` (${formatOran(ozet.son24_kazanma_orani, false, 0)} kazanç)`
        : '';
      kzAltEl.textContent = `${ozet.son24_islem} işlem${winPart}`;
    } else {
      kzAltEl.textContent = '—';
    }
  }

  if (bugunEl) {
    const acStr = (ozet.bugun_acilan !== undefined && ozet.bugun_acilan !== null) ? `${ozet.bugun_acilan} açıldı` : '—';
    const kapStr = (ozet.bugun_kapanan !== undefined && ozet.bugun_kapanan !== null) ? `${ozet.bugun_kapanan} kapandı` : '—';
    bugunEl.textContent = (acStr === '—' && kapStr === '—') ? '—' : `${acStr} · ${kapStr}`;
  }

  if (kadroEl) {
    const doluStr = (ozet.kadro_dolu !== undefined && ozet.kadro_dolu !== null) ? ozet.kadro_dolu : '—';
    const topStr = (ozet.kadro_toplam !== undefined && ozet.kadro_toplam !== null) ? ozet.kadro_toplam : '—';
    kadroEl.textContent = (doluStr === '—' && topStr === '—') ? '—' : `Kadro: ${doluStr} / ${topStr}`;
  }

  // 2. Düzeltme: Mini Kasa Grafiği etiketinde hesap yapılmaz; doğrudan kasa.degisim_oran kullanılır
  cizMiniKasaGrafik(kasa.egri, kasa.baslangic_usd, kasa.degisim_oran);
}

function cizMiniKasaGrafik(egri, baslangicUsd, degisimOran) {
  const container = document.getElementById('kasa-grafik');
  if (!container || !egri || egri.length < 2) return;

  const w = 320, h = 90;
  const padL = 36, padR = 48, padT = 14, padB = 18;
  const cW = w - padL - padR, cH = h - padT - padB;

  const baseV = baslangicUsd !== undefined && baslangicUsd !== null ? baslangicUsd : egri[0][1];
  const vals = egri.map(x => x[1]);
  const minV = Math.min(...vals, baseV);
  const maxV = Math.max(...vals, baseV);
  const lastV = vals[vals.length - 1];
  const range = (maxV - minV) || 1;
  const yMin = minV - range * 0.1, yMax = maxV + range * 0.1;
  const span = yMax - yMin;

  const getX = (i) => padL + (i / (egri.length - 1)) * cW;
  const getY = (v) => padT + cH - ((v - yMin) / span) * cH;

  const points = egri.map((d, i) => `${getX(i).toFixed(1)},${getY(d[1]).toFixed(1)}`).join(' ');
  const areaPoints = `${getX(0)},${padT + cH} ${points} ${getX(egri.length - 1)},${padT + cH}`;

  const isUp = (degisimOran !== undefined && degisimOran !== null) ? (degisimOran >= 0) : (lastV >= baseV);
  const color = isUp ? 'var(--color-profit)' : 'var(--color-loss)';
  const lastX = getX(egri.length - 1), lastY = getY(lastV);

  // 2. Düzeltme: Hesap yapılmaz, kasa.degisim_oran kullanılır
  const chg = (degisimOran !== undefined && degisimOran !== null)
    ? formatOran(degisimOran, true)
    : '—';

  container.innerHTML = `
    <svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
      <defs>
        <linearGradient id="miniKasaGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="${color}" stop-opacity="0.3"/>
          <stop offset="100%" stop-color="${color}" stop-opacity="0.0"/>
        </linearGradient>
      </defs>
      <!-- 5. Düzeltme: CSS değişkenli sıfır çizgisi -->
      <line x1="${padL}" y1="${getY(baseV).toFixed(1)}" x2="${padL + cW}" y2="${getY(baseV).toFixed(1)}" stroke="var(--chart-zero-line)" stroke-dasharray="2 2"/>
      <polygon points="${areaPoints}" fill="url(#miniKasaGrad)"/>
      <polyline points="${points}" fill="none" stroke="${color}" stroke-width="2"/>
      <circle cx="${lastX.toFixed(1)}" cy="${lastY.toFixed(1)}" r="3" fill="${color}"/>
      <rect x="${lastX + 4}" y="${lastY - 8}" width="42" height="16" rx="3" fill="${color}"/>
      <text x="${lastX + 25}" y="${lastY + 3.5}" text-anchor="middle" font-size="9" font-weight="700" fill="#fff" font-family="var(--font-mono)">${chg}</text>
    </svg>
  `;
}

// ==========================================
// 7. 4 ADET İNLİNE SVG GRAFİK (CSS Değişkenleri ile)
// ==========================================
function grafikleriCiz(takim) {
  const seriler = takim.seriler || {};

  // 1. Kümülatif K/Z (Yeşil Alan)
  cizAlanGrafik({
    containerId: 'grafik-kumulatif',
    badgeId: 'badge-kumulatif-son',
    data: seriler.kumulatif_kz || [],
    strokeColor: 'var(--color-profit)',
    gradId: 'gradKumulatif',
    stopColor: 'rgba(16, 185, 129, 0.4)'
  });

  // 2. Kasa Bakiyesi (Turuncu Çizgi)
  cizCizgiGrafik({
    containerId: 'grafik-bakiye',
    badgeId: 'badge-bakiye-son',
    data: seriler.bakiye || [],
    strokeColor: 'var(--color-accent)',
    gradId: 'gradBakiye',
    stopColor: 'rgba(245, 158, 11, 0.25)'
  });

  // 3. Düşüş (Drawdown, Kırmızı Alan 0'dan aşağı)
  cizDususGrafik({
    containerId: 'grafik-dusus',
    badgeId: 'badge-dusus-son',
    data: seriler.dusus || [],
    strokeColor: 'var(--color-loss)',
    gradId: 'gradDusus',
    stopColor: 'rgba(244, 63, 94, 0.35)'
  });

  // 4. Günlük Net K/Z (Yeşil/Kırmızı Çubuklar)
  cizGunlukCubukGrafik({
    containerId: 'grafik-gunluk',
    badgeId: 'badge-gunluk-ozet',
    data: seriler.gunluk_kz || []
  });
}

function cizAlanGrafik(cfg) {
  const container = document.getElementById(cfg.containerId);
  const badge = document.getElementById(cfg.badgeId);
  if (!container || !cfg.data || cfg.data.length < 2) return;

  const data = cfg.data;
  const lastVal = data[data.length - 1][1];
  if (badge) {
    badge.textContent = formatPara(lastVal, true);
    badge.className = `panel-badge ${kzSinifi(lastVal)}`;
  }

  const w = 380, h = 130;
  const padL = 40, padR = 16, padT = 16, padB = 22;
  const cW = w - padL - padR, cH = h - padT - padB;

  const vals = data.map(d => d[1]);
  const minV = Math.min(...vals, 0);
  const maxV = Math.max(...vals, 0);
  const range = (maxV - minV) || 1;
  const yMin = minV - range * 0.1, yMax = maxV + range * 0.1;
  const span = yMax - yMin;

  const getX = (i) => padL + (i / (data.length - 1)) * cW;
  const getY = (v) => padT + cH - ((v - yMin) / span) * cH;

  const zeroY = getY(0);
  const points = data.map((d, i) => `${getX(i).toFixed(1)},${getY(d[1]).toFixed(1)}`).join(' ');
  const areaPoints = `${getX(0)},${zeroY} ${points} ${getX(data.length - 1)},${zeroY}`;

  let dotsHtml = '';
  data.forEach((d, i) => {
    const cx = getX(i).toFixed(1);
    const cy = getY(d[1]).toFixed(1);
    const dateStr = formatKisaTarihTr(d[0]);
    const valStr = formatPara(d[1], true);
    dotsHtml += `
      <circle cx="${cx}" cy="${cy}" r="4" fill="transparent" class="chart-point"
              data-tooltip="${dateStr}: ${valStr}" style="cursor:pointer;" />
    `;
  });

  // 5. Düzeltme: Sabit renkler yerine CSS değişkenleri
  container.innerHTML = `
    <svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
      <defs>
        <linearGradient id="${cfg.gradId}" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="${cfg.stopColor}"/>
          <stop offset="100%" stop-color="${cfg.stopColor}" stop-opacity="0.0"/>
        </linearGradient>
      </defs>
      <line x1="${padL}" y1="${zeroY.toFixed(1)}" x2="${padL + cW}" y2="${zeroY.toFixed(1)}" stroke="var(--chart-zero-line)" stroke-dasharray="2 2"/>
      <text x="${padL - 6}" y="${zeroY + 3.5}" fill="var(--chart-axis-text)" font-size="9" text-anchor="end" font-family="var(--font-mono)">0 $</text>

      <polygon points="${areaPoints}" fill="url(#${cfg.gradId})"/>
      <polyline points="${points}" fill="none" stroke="${cfg.strokeColor}" stroke-width="2"/>
      ${dotsHtml}

      <text x="${padL}" y="${h - 4}" fill="var(--chart-axis-text)" font-size="9" font-family="var(--font-mono)">${formatKisaTarihTr(data[0][0])}</text>
      <text x="${padL + cW}" y="${h - 4}" fill="var(--chart-axis-text)" font-size="9" text-anchor="end" font-family="var(--font-mono)">${formatKisaTarihTr(data[data.length - 1][0])}</text>
    </svg>
  `;

  attachHoverEvents(container);
}

function cizCizgiGrafik(cfg) {
  const container = document.getElementById(cfg.containerId);
  const badge = document.getElementById(cfg.badgeId);
  if (!container || !cfg.data || cfg.data.length < 2) return;

  const data = cfg.data;
  const lastVal = data[data.length - 1][1];
  if (badge) badge.textContent = formatPara(lastVal);

  const w = 380, h = 130;
  const padL = 46, padR = 16, padT = 16, padB = 22;
  const cW = w - padL - padR, cH = h - padT - padB;

  const vals = data.map(d => d[1]);
  const minV = Math.min(...vals);
  const maxV = Math.max(...vals);
  const range = (maxV - minV) || 1;
  const yMin = minV - range * 0.1, yMax = maxV + range * 0.1;
  const span = yMax - yMin;

  const getX = (i) => padL + (i / (data.length - 1)) * cW;
  const getY = (v) => padT + cH - ((v - yMin) / span) * cH;

  const points = data.map((d, i) => `${getX(i).toFixed(1)},${getY(d[1]).toFixed(1)}`).join(' ');

  let dotsHtml = '';
  data.forEach((d, i) => {
    const cx = getX(i).toFixed(1);
    const cy = getY(d[1]).toFixed(1);
    const dateStr = formatKisaTarihTr(d[0]);
    const valStr = formatPara(d[1]);
    dotsHtml += `
      <circle cx="${cx}" cy="${cy}" r="4" fill="transparent" class="chart-point"
              data-tooltip="${dateStr}: ${valStr}" style="cursor:pointer;" />
    `;
  });

  // 5. Düzeltme: Sabit renkler yerine CSS değişkenleri
  container.innerHTML = `
    <svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
      <defs>
        <linearGradient id="${cfg.gradId}" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="${cfg.stopColor}"/>
          <stop offset="100%" stop-color="${cfg.stopColor}" stop-opacity="0.0"/>
        </linearGradient>
      </defs>
      <line x1="${padL}" y1="${getY(maxV).toFixed(1)}" x2="${padL + cW}" y2="${getY(maxV).toFixed(1)}" stroke="var(--chart-grid-light)" stroke-dasharray="2 2"/>
      <text x="${padL - 6}" y="${getY(maxV) + 3.5}" fill="var(--chart-axis-text)" font-size="9" text-anchor="end" font-family="var(--font-mono)">${Math.round(maxV)} $</text>

      <line x1="${padL}" y1="${getY(minV).toFixed(1)}" x2="${padL + cW}" y2="${getY(minV).toFixed(1)}" stroke="var(--chart-grid-light)" stroke-dasharray="2 2"/>
      <text x="${padL - 6}" y="${getY(minV) + 3.5}" fill="var(--chart-axis-text)" font-size="9" text-anchor="end" font-family="var(--font-mono)">${Math.round(minV)} $</text>

      <polyline points="${points}" fill="none" stroke="${cfg.strokeColor}" stroke-width="2"/>
      ${dotsHtml}

      <text x="${padL}" y="${h - 4}" fill="var(--chart-axis-text)" font-size="9" font-family="var(--font-mono)">${formatKisaTarihTr(data[0][0])}</text>
      <text x="${padL + cW}" y="${h - 4}" fill="var(--chart-axis-text)" font-size="9" text-anchor="end" font-family="var(--font-mono)">${formatKisaTarihTr(data[data.length - 1][0])}</text>
    </svg>
  `;

  attachHoverEvents(container);
}

function cizDususGrafik(cfg) {
  const container = document.getElementById(cfg.containerId);
  const badge = document.getElementById(cfg.badgeId);
  if (!container || !cfg.data || cfg.data.length < 2) return;

  const data = cfg.data;
  const lastVal = data[data.length - 1][1];
  if (badge) {
    badge.textContent = formatOran(lastVal, true);
    badge.className = `panel-badge ${kzSinifi(lastVal)}`;
  }

  const w = 380, h = 130;
  const padL = 44, padR = 16, padT = 16, padB = 22;
  const cW = w - padL - padR, cH = h - padT - padB;

  const vals = data.map(d => d[1]);
  const minV = Math.min(...vals, -0.05);
  const yMin = minV * 1.15;
  const yMax = 0.005;
  const span = yMax - yMin;

  const getX = (i) => padL + (i / (data.length - 1)) * cW;
  const getY = (v) => padT + cH - ((v - yMin) / span) * cH;

  const zeroY = getY(0);
  const points = data.map((d, i) => `${getX(i).toFixed(1)},${getY(d[1]).toFixed(1)}`).join(' ');
  const areaPoints = `${getX(0)},${zeroY} ${points} ${getX(data.length - 1)},${zeroY}`;

  let dotsHtml = '';
  data.forEach((d, i) => {
    const cx = getX(i).toFixed(1);
    const cy = getY(d[1]).toFixed(1);
    const dateStr = formatKisaTarihTr(d[0]);
    const valStr = formatOran(d[1], true);
    dotsHtml += `
      <circle cx="${cx}" cy="${cy}" r="4" fill="transparent" class="chart-point"
              data-tooltip="${dateStr}: ${valStr}" style="cursor:pointer;" />
    `;
  });

  // 5. Düzeltme: Sabit renkler yerine CSS değişkenleri
  container.innerHTML = `
    <svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
      <defs>
        <linearGradient id="${cfg.gradId}" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="${cfg.stopColor}"/>
          <stop offset="100%" stop-color="${cfg.stopColor}" stop-opacity="0.05"/>
        </linearGradient>
      </defs>
      <line x1="${padL}" y1="${zeroY.toFixed(1)}" x2="${padL + cW}" y2="${zeroY.toFixed(1)}" stroke="var(--chart-zero-line)" stroke-dasharray="2 2"/>
      <text x="${padL - 6}" y="${zeroY + 3.5}" fill="var(--chart-axis-text)" font-size="9" text-anchor="end" font-family="var(--font-mono)">%0</text>

      <line x1="${padL}" y1="${getY(minV).toFixed(1)}" x2="${padL + cW}" y2="${getY(minV).toFixed(1)}" stroke="var(--chart-grid-light)" stroke-dasharray="2 2"/>
      <text x="${padL - 6}" y="${getY(minV) + 3.5}" fill="var(--chart-axis-text)" font-size="9" text-anchor="end" font-family="var(--font-mono)">${formatOran(minV, true, 1)}</text>

      <polygon points="${areaPoints}" fill="url(#${cfg.gradId})"/>
      <polyline points="${points}" fill="none" stroke="${cfg.strokeColor}" stroke-width="2"/>
      ${dotsHtml}

      <text x="${padL}" y="${h - 4}" fill="var(--chart-axis-text)" font-size="9" font-family="var(--font-mono)">${formatKisaTarihTr(data[0][0])}</text>
      <text x="${padL + cW}" y="${h - 4}" fill="var(--chart-axis-text)" font-size="9" text-anchor="end" font-family="var(--font-mono)">${formatKisaTarihTr(data[data.length - 1][0])}</text>
    </svg>
  `;

  attachHoverEvents(container);
}

function cizGunlukCubukGrafik(cfg) {
  const container = document.getElementById(cfg.containerId);
  const badge = document.getElementById(cfg.badgeId);
  if (!container || !cfg.data || cfg.data.length === 0) return;

  const data = cfg.data;
  if (badge) badge.textContent = `${data.length} Günlük Veri`;

  const w = 900, h = 120;
  const padL = 46, padR = 20, padT = 16, padB = 22;
  const cW = w - padL - padR, cH = h - padT - padB;

  const vals = data.map(d => d[1]);
  const maxAbs = Math.max(...vals.map(Math.abs), 0.015);
  const yMin = -maxAbs * 1.15;
  const yMax = maxAbs * 1.15;
  const span = yMax - yMin;

  const getY = (v) => padT + cH - ((v - yMin) / span) * cH;
  const zeroY = getY(0);

  const numBars = data.length;
  const barSlot = cW / numBars;
  const barWidth = Math.max(2, barSlot * 0.7);

  let barsHtml = '';
  data.forEach((d, i) => {
    const v = d[1];
    const x = padL + i * barSlot + (barSlot - barWidth) / 2;
    const yVal = getY(v);
    const isPos = v >= 0;
    const color = isPos ? 'var(--color-profit)' : 'var(--color-loss)';

    const barY = isPos ? yVal : zeroY;
    const barH = Math.max(2, Math.abs(yVal - zeroY));

    const dateStr = formatKisaTarihTr(d[0]);
    const valStr = formatOran(v, true);

    barsHtml += `
      <rect x="${x.toFixed(1)}" y="${barY.toFixed(1)}" width="${barWidth.toFixed(1)}" height="${barH.toFixed(1)}"
            fill="${color}" rx="1" class="chart-point"
            data-tooltip="${dateStr}: ${valStr}" style="cursor:pointer;" />
    `;
  });

  // 5. Düzeltme: Sabit renkler yerine CSS değişkenleri
  container.innerHTML = `
    <svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
      <line x1="${padL}" y1="${zeroY.toFixed(1)}" x2="${padL + cW}" y2="${zeroY.toFixed(1)}" stroke="var(--chart-zero-line)" stroke-dasharray="2 2"/>
      <text x="${padL - 6}" y="${zeroY + 3.5}" fill="var(--chart-axis-text)" font-size="9" text-anchor="end" font-family="var(--font-mono)">%0</text>

      <line x1="${padL}" y1="${getY(maxAbs).toFixed(1)}" x2="${padL + cW}" y2="${getY(maxAbs).toFixed(1)}" stroke="var(--chart-grid-light)" stroke-dasharray="2 2"/>
      <text x="${padL - 6}" y="${getY(maxAbs) + 3.5}" fill="var(--chart-axis-text)" font-size="9" text-anchor="end" font-family="var(--font-mono)">${formatOran(maxAbs, true, 1)}</text>

      <line x1="${padL}" y1="${getY(-maxAbs).toFixed(1)}" x2="${padL + cW}" y2="${getY(-maxAbs).toFixed(1)}" stroke="var(--chart-grid-light)" stroke-dasharray="2 2"/>
      <text x="${padL - 6}" y="${getY(-maxAbs) + 3.5}" fill="var(--chart-axis-text)" font-size="9" text-anchor="end" font-family="var(--font-mono)">${formatOran(-maxAbs, true, 1)}</text>

      ${barsHtml}

      <text x="${padL}" y="${h - 4}" fill="var(--chart-axis-text)" font-size="9" font-family="var(--font-mono)">${formatKisaTarihTr(data[0][0])}</text>
      <text x="${padL + cW}" y="${h - 4}" fill="var(--chart-axis-text)" font-size="9" text-anchor="end" font-family="var(--font-mono)">${formatKisaTarihTr(data[data.length - 1][0])}</text>
    </svg>
  `;

  attachHoverEvents(container);
}

function attachHoverEvents(container) {
  const elements = container.querySelectorAll('.chart-point');
  elements.forEach(el => {
    el.addEventListener('mouseenter', (e) => {
      const txt = el.getAttribute('data-tooltip');
      if (txt) showTooltip(e, txt);
    });
    el.addEventListener('mousemove', (e) => {
      moveTooltip(e);
    });
    el.addEventListener('mouseleave', () => {
      hideTooltip();
    });
  });
}

// ==========================================
// 8. TRADER TABLOSU (Sıralanabilir & Kaçışlı)
// ==========================================
function traderTablosunuCiz(takim) {
  const tbody = document.getElementById('trader-tablosu-body');
  const badge = document.getElementById('trader-sayisi-badge');
  const table = document.getElementById('trader-tablosu');
  if (!tbody) return;

  let traderlar = [...(takim.traderlar || [])];
  if (badge) badge.textContent = `${traderlar.length} Trader`;

  if (traderlar.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" class="center" style="padding:16px;color:var(--text-muted);">Trader verisi bulunmuyor</td></tr>';
    return;
  }

  traderlar.sort((a, b) => {
    let vA = a[traderSiralama.sutun];
    let vB = b[traderSiralama.sutun];

    if (traderSiralama.sutun === 'son_islem') {
      vA = new Date(vA).getTime() || 0;
      vB = new Date(vB).getTime() || 0;
    }

    if (vA < vB) return traderSiralama.artan ? -1 : 1;
    if (vA > vB) return traderSiralama.artan ? 1 : -1;
    return 0;
  });

  tbody.innerHTML = '';
  traderlar.forEach(t => {
    const tr = document.createElement('tr');
    tr.className = 'trader-row';

    const netCls = kzSinifi(t.net_oran);
    const winRateStr = formatOran(t.kazanma_orani, false, 0);
    const netStr = formatOran(t.net_oran, true);
    const sonIslemStr = yasHesapla(t.son_islem, panoVerisi.uretildi);
    const adGuvenli = kacis(t.ad);
    const islemGuvenli = (t.islem !== undefined && t.islem !== null) ? t.islem : '—';

    // 3. Düzeltme: HTML kaçışı uygulandı
    tr.innerHTML = `
      <td class="left">
        <span class="desktop-only trader-tag"><strong>${adGuvenli}</strong></span>
        <!-- Mobil Kart -->
        <div class="mobile-only mobile-card-top">
          <span class="trader-tag" style="font-size:12px;"><strong>${adGuvenli}</strong></span>
          <span class="mono-val ${netCls}" style="font-weight:700;">${netStr}</span>
        </div>
        <div class="mobile-only mobile-card-meta">
          <span>${islemGuvenli} işlem (${winRateStr} kazanç)</span>
          <span>Son: ${sonIslemStr}</span>
        </div>
      </td>
      <td class="right num desktop-only">${islemGuvenli}</td>
      <td class="right num desktop-only">${winRateStr}</td>
      <td class="right num desktop-only ${netCls}"><strong>${netStr}</strong></td>
      <td class="right num desktop-only" style="color:var(--text-secondary);">${sonIslemStr}</td>
    `;
    tbody.appendChild(tr);
  });

  if (table && !table.dataset.eventsBound) {
    const headers = table.querySelectorAll('th.sortable');
    headers.forEach(th => {
      th.addEventListener('click', () => {
        const col = th.getAttribute('data-col');
        if (traderSiralama.sutun === col) {
          traderSiralama.artan = !traderSiralama.artan;
        } else {
          traderSiralama.sutun = col;
          traderSiralama.artan = false;
        }

        headers.forEach(h => {
          const icon = h.querySelector('.sort-icon');
          if (h.getAttribute('data-col') === traderSiralama.sutun) {
            if (icon) icon.textContent = traderSiralama.artan ? '▲' : '▼';
          } else {
            if (icon) icon.textContent = '▲▼';
          }
        });

        const curTeam = panoVerisi.takimlar.find(x => x.ad === aktifTakimAdi);
        if (curTeam) traderTablosunuCiz(curTeam);
      });
    });
    table.dataset.eventsBound = 'true';
  }
}

// ==========================================
// 9. AÇIK İŞLEMLER TABLOSU (Kaçışlı & Fiyat Biçimli)
// ==========================================
function acikIslemleriCiz(takim) {
  const acikListesi = takim.acik || [];
  const tbody = document.getElementById('acik-islemler-body');
  const badgeCount = document.getElementById('acik-islem-sayisi');
  const expandRow = document.getElementById('acik-expand-row');
  const expandBtn = document.getElementById('acik-expand-btn');

  if (badgeCount) badgeCount.textContent = acikListesi.length;
  if (!tbody) return;
  tbody.innerHTML = '';

  const limitGerekiyor = acikListesi.length > 10;
  const gosterilecekler = (limitGerekiyor && !acikIslemlerGenisletildi) 
    ? acikListesi.slice(0, 10) 
    : acikListesi;

  if (expandRow && expandBtn) {
    if (limitGerekiyor) {
      expandRow.style.display = '';
      const gizlenenSayi = acikListesi.length - 10;
      if (acikIslemlerGenisletildi) {
        expandBtn.innerHTML = `▲ Daha az göster (${gizlenenSayi} işlem gizle)`;
      } else {
        expandBtn.innerHTML = `▼ +${gizlenenSayi} işlem daha (toplama dahil)`;
      }
      expandBtn.onclick = () => {
        acikIslemlerGenisletildi = !acikIslemlerGenisletildi;
        acikIslemleriCiz(takim);
      };
    } else {
      expandRow.style.display = 'none';
    }
  }

  if (acikListesi.length === 0) {
    tbody.innerHTML = '<tr><td colspan="9" class="center" style="padding:20px;color:var(--text-muted);">Açık işlem bulunmuyor</td></tr>';
  } else {
    gosterilecekler.forEach(pos => {
      const tr = document.createElement('tr');
      tr.className = 'pos-row';

      const yonCls = pos.yon === 'long' ? 'long' : 'short';
      const yonEtiket = pos.yon === 'long' ? `L ${kacis(pos.kaldirac)}x` : `S ${kacis(pos.kaldirac)}x`;
      const kzCls = kzSinifi(pos.kz_usd);
      const yasMetni = yasHesapla(pos.acilis, panoVerisi.uretildi);
      const liqMetni = pos.likidasyona_uzaklik_oran !== undefined ? `liq ${formatOran(pos.likidasyona_uzaklik_oran, false, 0)} uzak` : '—';

      // 3. ve 4. Düzeltmeler: HTML kaçışı ve bilimsel gösterimsiz Türkçe fiyat biçimlendirmesi
      const coinGuvenli = kacis(pos.coin);
      const traderGuvenli = kacis(pos.trader);
      const girisFiyat = formatFiyat(pos.giris);
      const sonFiyat = formatFiyat(pos.son);

      tr.innerHTML = `
        <td class="left">
          <div class="desktop-only" style="display:inline-flex;align-items:center;gap:6px;">
            <strong>${coinGuvenli}</strong>
          </div>
          <!-- Mobil Kart Görünümü -->
          <div class="mobile-only mobile-card-top">
            <div style="display:flex;align-items:center;gap:6px;">
              <strong style="font-size:14px;">${coinGuvenli}</strong>
              <span class="badge-pos ${yonCls}">${yonEtiket}</span>
            </div>
            <div style="text-align:right;">
              <div class="mono-val ${kzCls}" style="font-weight:700;">${formatPara(pos.kz_usd, true)}</div>
              <div class="mono-val ${kzCls}" style="font-size:11px;">${formatOran(pos.kz_oran, true)}</div>
            </div>
          </div>
          <div class="mobile-only mobile-card-meta">
            <span><span class="trader-tag">${traderGuvenli}</span> · ${yasMetni}</span>
            <span style="color:var(--text-secondary);font-family:var(--font-mono);">${liqMetni}</span>
          </div>
          <div class="mobile-only mobile-card-metrics">
            <div class="mobile-metric-item">
              <span class="mobile-metric-label">Teminat</span>
              <span class="mobile-metric-val">${formatPara(pos.teminat_usd)}</span>
            </div>
            <div class="mobile-metric-item">
              <span class="mobile-metric-label">Büyüklük</span>
              <span class="mobile-metric-val">${formatPara(pos.buyukluk_usd)}</span>
            </div>
            <div class="mobile-metric-item">
              <span class="mobile-metric-label">Giriş / Son</span>
              <span class="mobile-metric-val">${girisFiyat} / ${sonFiyat}</span>
            </div>
          </div>
        </td>
        <td class="center desktop-only"><span class="badge-pos ${yonCls}">${yonEtiket}</span></td>
        <td class="center desktop-only"><span class="trader-tag">${traderGuvenli}</span></td>
        <td class="center desktop-only" style="color:var(--text-secondary);">${yasMetni}</td>
        <td class="right desktop-only mono-val" style="color:var(--text-secondary);">${liqMetni}</td>
        <td class="right num desktop-only">${formatPara(pos.teminat_usd)}</td>
        <td class="right num desktop-only">${formatPara(pos.buyukluk_usd)}</td>
        <td class="right num desktop-only ${kzCls}"><strong>${formatPara(pos.kz_usd, true)}</strong></td>
        <td class="right num desktop-only ${kzCls}"><strong>${formatOran(pos.kz_oran, true)}</strong></td>
      `;
      tbody.appendChild(tr);
    });
  }

  // 2. Düzeltme: Tek izin verilen hesap olan dinamik tablosal toplam
  toplamSatiriniCiz(acikListesi);
}

function toplamSatiriniCiz(acikListesi) {
  const tfoot = document.getElementById('acik-islemler-foot');
  if (!tfoot) return;

  let toplamTeminat = 0;
  let toplamBuyukluk = 0;
  let toplamKzUsd = 0;

  acikListesi.forEach(pos => {
    toplamTeminat += Number(pos.teminat_usd) || 0;
    toplamBuyukluk += Number(pos.buyukluk_usd) || 0;
    toplamKzUsd += Number(pos.kz_usd) || 0;
  });

  const toplamKzOran = toplamTeminat > 0 ? (toplamKzUsd / toplamTeminat) : 0;
  const kzCls = kzSinifi(toplamKzUsd);

  tfoot.innerHTML = `
    <tr class="total-row">
      <td colspan="5" class="left desktop-only">
        <span class="total-label">TOPLAM (${acikListesi.length})</span>
      </td>
      <td class="right num desktop-only"><strong>${formatPara(toplamTeminat)}</strong></td>
      <td class="right num desktop-only"><strong>${formatPara(toplamBuyukluk)}</strong></td>
      <td class="right num desktop-only ${kzCls}"><strong>${formatPara(toplamKzUsd, true)}</strong></td>
      <td class="right num desktop-only ${kzCls}"><strong>${formatOran(toplamKzOran, true)}</strong></td>

      <!-- Mobil Toplam Kartı -->
      <td colspan="9" class="mobile-only">
        <div class="mobile-total-wrap">
          <div class="mobile-total-header">
            <span>TOPLAM (${acikListesi.length} İşlem)</span>
            <span class="${kzCls}">${formatPara(toplamKzUsd, true)} (${formatOran(toplamKzOran, true)})</span>
          </div>
          <div class="mobile-total-grid">
            <div class="mobile-metric-item">
              <span class="mobile-metric-label">Toplam Teminat</span>
              <span class="mobile-metric-val">${formatPara(toplamTeminat)}</span>
            </div>
            <div class="mobile-metric-item">
              <span class="mobile-metric-label">Toplam Büyüklük</span>
              <span class="mobile-metric-val">${formatPara(toplamBuyukluk)}</span>
            </div>
          </div>
        </div>
      </td>
    </tr>
  `;
}

// ==========================================
// 10. SON KAPANANLAR TABLOSU (Kaçışlı & Sınıf Korumalı)
// ==========================================
function sonKapananlariCiz(takim) {
  const kapananListesi = takim.kapanan || [];
  const tbody = document.getElementById('kapanan-islemler-body');
  const badgeCount = document.getElementById('kapanan-islem-sayisi');

  if (badgeCount) badgeCount.textContent = kapananListesi.length;
  if (!tbody) return;
  tbody.innerHTML = '';

  if (kapananListesi.length === 0) {
    tbody.innerHTML = '<tr><td colspan="8" class="center" style="padding:20px;color:var(--text-muted);">Kapanan işlem bulunmuyor</td></tr>';
    return;
  }

  kapananListesi.forEach(pos => {
    const tr = document.createElement('tr');
    tr.className = 'closed-row';

    const yonCls = pos.yon === 'long' ? 'long' : 'short';
    const yonEtiket = pos.yon === 'long' ? `L ${kacis(pos.kaldirac)}x` : `S ${kacis(pos.kaldirac)}x`;
    const kzCls = kzSinifi(pos.kz_usd);
    const sureMetni = sureHesapla(pos.acilis, pos.kapanis);
    const nedenMetni = kacis(turkceNeden(pos.neden));
    // 3. Düzeltme: reason-tag sınıf adında yalnız bilinen 5 değeri kabul et
    const nedenSinif = guvenliNedenSinifi(pos.neden);
    const coinGuvenli = kacis(pos.coin);
    const traderGuvenli = kacis(pos.trader);

    tr.innerHTML = `
      <td class="left">
        <div class="desktop-only" style="display:inline-flex;align-items:center;gap:6px;">
          <strong>${coinGuvenli}</strong>
        </div>
        <!-- Mobil Kart -->
        <div class="mobile-only mobile-card-top">
          <div style="display:flex;align-items:center;gap:6px;">
            <strong>${coinGuvenli}</strong>
            <span class="badge-pos ${yonCls}">${yonEtiket}</span>
            <span class="reason-tag ${nedenSinif}">${nedenMetni}</span>
          </div>
          <div class="num ${kzCls}" style="font-weight:700;">
            ${formatPara(pos.kz_usd, true)}
          </div>
        </div>
        <div class="mobile-only mobile-card-meta">
          <span><span class="trader-tag">${traderGuvenli}</span> · ${sureMetni}</span>
          <span class="num ${kzCls}">${formatOran(pos.kz_oran, true)} (Ana para: ${formatPara(pos.ana_para_usd)})</span>
        </div>
      </td>
      <td class="center desktop-only"><span class="badge-pos ${yonCls}">${yonEtiket}</span></td>
      <td class="center desktop-only"><span class="reason-tag ${nedenSinif}">${nedenMetni}</span></td>
      <td class="center desktop-only" style="color:var(--text-secondary);">${sureMetni}</td>
      <td class="center desktop-only"><span class="trader-tag">${traderGuvenli}</span></td>
      <td class="right num desktop-only">${formatPara(pos.ana_para_usd)}</td>
      <td class="right num desktop-only ${kzCls}"><strong>${formatPara(pos.kz_usd, true)}</strong></td>
      <td class="right num desktop-only ${kzCls}"><strong>${formatOran(pos.kz_oran, true)}</strong></td>
    `;
    tbody.appendChild(tr);
  });
}

// ==========================================
// 11. ZAMANLAYICI VE BAŞLATMA
// ==========================================
function sayaciBaslat() {
  if (sayacInterval) clearInterval(sayacInterval);

  sayacInterval = setInterval(() => {
    yenilemeSayaci--;
    const sayacEl = document.getElementById('sayac-metni');
    if (sayacEl) sayacEl.textContent = `${yenilemeSayaci}s`;

    if (yenilemeSayaci <= 0) {
      yenilemeSayaci = 60;
      veriyiYukle();
    }
  }, 1000);
}

document.addEventListener('DOMContentLoaded', () => {
  setupTooltip();
  temaBaslat();
  veriyiYukle();
  sayaciBaslat();

  const retryBtn = document.getElementById('btn-tekrar-dene');
  if (retryBtn) {
    retryBtn.addEventListener('click', () => {
      veriyiYukle();
    });
  }
});