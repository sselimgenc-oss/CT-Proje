# Dal temizliği listesi — 2026-11-05

**Silme lider+kullanıcı onaylı (KARARLAR 05.11 akşam), liste hazır, silme ayrı adım.** Bu belge yalnız listedir; hiçbir dal silinmedi.

Kaynak: `git ls-remote --heads origin` (2026-11-05), birleşme durumu PR geçmişinden (`state=all`, `head` = dal tepe SHA'sı). Dallar `main`'e squash ile birleştiği için `git merge-base --is-ancestor` tek başına yanıltıcıdır; kararda PR durumu esas alındı.

## Özet
- Toplam uzak dal: 35 (`main` dahil)
- BİRLEŞMİŞ-SİLİNEBİLİR: 22 (PR birleşmiş, dal tepesi PR başındaki SHA ile aynı, korunan listede değil)
- KORUNAN: 12 (`main`, `radar`, `radar-deneme`, `canli-durum`, `canli-durum-deneme`, ve kullanıcı listesindeki korunan dallar)
- AÇIK PR: 2 (`claude/lider-kararlari-0511` #537; `claude/k38-azaltma` #530 draft; ikisi de korunan)
- BELİRSİZ: 1 (`copytrade-izleme`, 31 commit, PR yok, birleşme yok)
- Uzakta bulunmayan (listede sayılmadı): `codex/*` (hiç uzak dal yok), `copytrade-kapi`, `faz1-son`, `pr505` (fetch sırasında "deleted"), `claude/t4b-guvenlik-1`, `claude/k41-ofset`, `claude/telegram-lider-kararlari`

## Tablo

| dal | son commit tarihi | durum | not |
|---|---|---|---|
| main | 2026-11-05 | KORUNAN | varsayılan dal |
| radar | 2026-11-05 | KORUNAN | korunan liste |
| radar-deneme | 2026-11-04 | KORUNAN | korunan liste |
| canli-durum | 2026-11-05 | KORUNAN | korunan liste |
| canli-durum-deneme | 2026-11-05 | KORUNAN | korunan liste |
| claude/canliya-gecis-kararlari | 2026-11-05 | KORUNAN | PR #536 birleşmiş; korunan liste |
| claude/gracious-fermi-anjejo | 2026-11-05 | KORUNAN | PR yok; korunan liste |
| claude/k38-azaltma | 2026-11-05 | AÇIK PR | PR #530 draft; korunan liste |
| claude/k38-baz | 2026-11-05 | KORUNAN | PR yok; korunan liste |
| claude/k39-kadro-disi | 2026-11-05 | KORUNAN | PR #526 birleşmiş; korunan liste |
| claude/lider-kararlari-0511 | 2026-11-05 | AÇIK PR | PR #537 open; korunan liste |
| claude/stoic-carson-w3xagz | 2026-11-05 | KORUNAN | lider dalı; korunan liste |
| copytrade-izleme | 2026-11-03 | BELİRSİZ | 31 commit main'de yok, PR yok; silinmesin, lidere sor (`docs/sonnet_durum_devir.md` "silinmedi, lider kararı") |
| claude/devir-durum | 2026-11-05 | BİRLEŞMİŞ-SİLİNEBİLİR | PR #515 birleşmiş, SHA eşleşiyor |
| claude/devir-durum2 | 2026-11-05 | BİRLEŞMİŞ-SİLİNEBİLİR | PR #531 birleşmiş, SHA eşleşiyor |
| claude/pano-b | 2026-11-05 | BİRLEŞMİŞ-SİLİNEBİLİR | PR #527 birleşmiş |
| claude/pano-c | 2026-11-05 | BİRLEŞMİŞ-SİLİNEBİLİR | PR #529 birleşmiş |
| claude/pano-duzelt | 2026-11-05 | BİRLEŞMİŞ-SİLİNEBİLİR | PR #524 birleşmiş |
| claude/pano-eski-kaldir | 2026-11-05 | BİRLEŞMİŞ-SİLİNEBİLİR | PR #528 birleşmiş |
| claude/pano-html | 2026-11-05 | BİRLEŞMİŞ-SİLİNEBİLİR | PR #520 birleşmiş |
| claude/pano-k40 | 2026-11-05 | BİRLEŞMİŞ-SİLİNEBİLİR | PR #532 birleşmiş |
| claude/pano-kadro | 2026-11-05 | BİRLEŞMİŞ-SİLİNEBİLİR | PR #523 birleşmiş |
| claude/pano-sekme | 2026-11-05 | BİRLEŞMİŞ-SİLİNEBİLİR | PR #522 birleşmiş |
| claude/pano-terminal | 2026-11-05 | BİRLEŞMİŞ-SİLİNEBİLİR | PR #521 birleşmiş |
| claude/pano-yayin | 2026-11-05 | BİRLEŞMİŞ-SİLİNEBİLİR | PR #533 birleşmiş |
| claude/saglik | 2026-11-05 | BİRLEŞMİŞ-SİLİNEBİLİR | PR #535 birleşmiş |
| claude/t4-canli-motor | 2026-11-05 | BİRLEŞMİŞ-SİLİNEBİLİR | PR #504 birleşmiş |
| claude/t4b-saglamlastirma | 2026-11-05 | BİRLEŞMİŞ-SİLİNEBİLİR | PR #510 birleşmiş (korunan `claude/t4b-guvenlik-1` ile karıştırılmasın) |
| claude/t6-rapor-isabet | 2026-11-05 | BİRLEŞMİŞ-SİLİNEBİLİR | PR #512 birleşmiş |
| claude/telegram-gorsel | 2026-11-05 | BİRLEŞMİŞ-SİLİNEBİLİR | PR #518 birleşmiş |
| claude/telegram-gorsel2 | 2026-11-05 | BİRLEŞMİŞ-SİLİNEBİLİR | PR #519 birleşmiş |
| claude/telegram-komutlar | 2026-11-05 | BİRLEŞMİŞ-SİLİNEBİLİR | PR #534 birleşmiş |
| claude/telegram-mesaj | 2026-11-05 | BİRLEŞMİŞ-SİLİNEBİLİR | PR #514 birleşmiş |
| claude/telegram-politika | 2026-11-05 | BİRLEŞMİŞ-SİLİNEBİLİR | PR #517 birleşmiş |
| claude/telegram-toplu | 2026-11-05 | BİRLEŞMİŞ-SİLİNEBİLİR | PR #516 birleşmiş |

## Silinecek dallar (ÇALIŞTIRILMADI — silme ayrı adım, onaydan sonra)

```bash
for b in claude/devir-durum claude/devir-durum2 claude/pano-b claude/pano-c claude/pano-duzelt claude/pano-eski-kaldir claude/pano-html claude/pano-k40 claude/pano-kadro claude/pano-sekme claude/pano-terminal claude/pano-yayin claude/saglik claude/t4-canli-motor claude/t4b-saglamlastirma claude/t6-rapor-isabet claude/telegram-gorsel claude/telegram-gorsel2 claude/telegram-komutlar claude/telegram-mesaj claude/telegram-politika claude/telegram-toplu; do git push origin --delete "$b"; done
```

## Notlar
- `.github/workflows/sonnet_isci.yml`: silinmedi. Dosya `@sonnet` yorumuyla çalışan aktif bir iş akışı (PR yorumu tetikler, K-19); yalnız dosya adına referans yok, ama davranış kullanımda. Testteki bilinen-iş-akışı listesi değişmedi. Kaldırma kararı lidere ait.
- `copytrade-izleme`: BELİRSİZ, silinmez.
- Korunan dal `claude/canliya-gecis-kararlari` PR #536 ile birleşmiş olsa da korunan listede; silinmez.
- Yerel `refs/remotes/origin/canli-durum` ve `canli-durum-deneme` güncellemesi yerel kilit hatası verdi (uzak SHA'lar `ls-remote` ile doğrulandı); yerel ref işi etkilemiyor.
