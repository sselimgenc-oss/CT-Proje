# A0-2 test onarımı: açık sorular

- `26e3f97` `docs/VERI_SOZLESMESI.md`'den satırları kör sildi; testlerin gerektirdiği satır ve üç başlık geri getirildi.
  Hâlâ eksik/yetim kalanlar (karar bekliyor): sağlık hattı maddesinin ilk satırı (`saglik_hatti`, sağlık konisi/CUSUM
  kullanıcı kararı beklediği için GERİ GETİRİLMEDİ); `kapanis_nedenleri` ve v3 "Ekleme" maddelerinin Etre'li satırları;
  "Tüketiciler" maddesinin devam satırı; "## 3. Sağlık ışığı" tablosu hâlâ koni/CUSUM koşulunu anlatıyor.
- `copytrade/kapi/CALISTIR` ve `.github/scripts/{kapi,izleme}_yayimla.sh` silinen iş akışlarının artığı; testler
  geçtiği için dokunulmadı. A2'de iş akışları kurulurken yeniden değerlendirilsin.
- `worker` testleri (`dispatchWorkflow` export hatası) bu işin kapsamı dışı, dokunulmadı.
