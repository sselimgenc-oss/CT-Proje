# CT kadro seçimi x gerçek kopya PnL (form sırası, 2026-11-21T06:06:19Z)

Toplu: 2 gün, ortalama rho = 0.100, p = 0.422 (tek yönlü).

| Gün | Kopyalanan / Kadro | rho | p | Net PnL $ | Durum |
|---|---:|---:|---:|---:|---|
| 2026-11-19 | 4 / 17 | -0.800 | 0.958 | -2.43 | tamam (tam) |
| 2026-11-20 | 3 / 28 | 1.000 | 0.167 | 6.97 | tamam (tam) |
| 2026-11-21 | 0 / 30 | - | - | - | az_trader |

Notlar:

- Yalnız bilgi: seçim/eşik/limit değiştirmez.
- Değişken: gerçek kopya PnL'i yalnız sahadaki traderlar için var; 'rastgele 11' karşılaştırması yapılamaz (yedek için varsayımsal PnL yok). Bunun yerine form puanı sırası ile gerçek net PnL sırasının Spearman ilişkisi.
- rho > 0: yüksek form puanlı trader o gün daha çok kazandırmış. p tek yönlü permütasyon; küçük örneklem, günler bağımsız değil.
- Kayıt penceresi: 6 gün; form geçmişi: 3 kadro günü; net = gerçekleşen K/Z - ücret.
