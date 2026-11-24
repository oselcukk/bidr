# Değişiklikler

Her birleştirmede (main'e giren her değişiklik) buraya en üste bir satır eklenir: tarih, kısa
açıklama ve kullanıcıyı ilgilendiriyorsa ne yapması gerektiği. `bidr guncelle` güncellemeden sonra
bu dosyanın yeni satırlarını gösterir. Bu dosyadan önceki geçmiş için `git log`.

- 2026-11-24: Form yanıt tablosu / anket sonucunda belge tarihi yanıt zaman damgalarından (d1-yanit-tarihi): "Zaman
  damgası"/"Timestamp"/"Tamamlanma saati" vb. sütunu varsa `tarih` son yanıt, `yanit_araligi` [ilk, son] ve dönem
  yanıt aralığından (form oluşturma/başlık tarihi değil). identify araç sürümü 3: BİR KEZ `bidr next` identify'ı
  yeniden ister (bütün belgelerin tarih alanları yeniden okunur); tarihi değişen belgelerin dönem sınıfı ve
  çalışma adı değişebilir, audit/inceleme yeniden çalışır.
- 2026-11-24: Farklı adla yeniden yüklenmiş, taranmamış kopya yeniden öneri üretmez (d1-metin-kopya): tarama kopyası
  grubu metin tabanlı belgelere genişletildi (yöntem `metin_kopyasi`: birincil tarih ikisinde de var ve aynı, metinde
  iki yönlü kapsama ≥ 0,9). Grupta tek paket, incelemede tek satır + "Kopyaları:"; önceden ayrı işlenmiş kopyalar
  modelsiz bağlanır. Temsilci önce işlenmiş, sonra incelemede kararı verilmiş belgedir. BİR KEZ: sonraki `bidr decide
  prepare` var olan metin kopyalarını gruplar; kopyanın inceleme satırları kaybolur, temsilcinin satırı ve kararı kalır.
- 2026-11-24: Yazım kod denetimi takılırsa insan kararı (d1-write-karar): `bidr write apply`ın kod denetimini geçemeyen
  her ayrı cevap deneme sayılır (`write-kod-denemeleri.json`); ilk yazım + `rapor.yeniden_yazim_siniri` (vars. 2)
  yeniden yazımdan sonra hâlâ geçemeyen ölçütte `bidr next` `kim: insan` ve `karar_bekleyen` listesi verir (JSON'da
  `sonraki.karar_bekleyen`: ölçüt, deneme, sınır, sorunlar, kabul_edilebilir). Yeni komut `bidr write karar -w WS
  <ölçüt> cikar|tekrar|kabul [--not]` (`write-insan.jsonl`); `kabul` yalnız üslup bulgularında (abartı/slogan/
  ODn dili; koçluk/tahmin/meta ve açık OD anışı değil), atıf/alıntı/bilinmeyen atıf bulgusunda reddedilir; kabul edilen metin yine doğrulanır.
  Panel bu listeyi gösteren sürümle birlikte güncellenmeli.
- 2026-11-24: Maskeleme önbelleğinin kod izi daraltıldı (d1-kod-izi): yalnız sonucu belirleyen kod (tespit/kapatma/
  biçim modülleri, run.py'nin sonuç fonksiyonları) sözdizimi ağacından izlenir; ilerleme göstergesi (`suanki`)
  çağrıları, belge dizgeleri/yorumlar, komut satırı, kaynak kip yönetimi (`kaynak.py`) ve run.py'nin klasör/rapor
  fonksiyonları belgeleri yeniden maskeletmez. BİR KEZ: güncellemeden sonraki ilk `bidr maskele` (kaynak ve kanıt
  kipi) bütün belgeleri yeniden maskeler (kod izinin biçimi değişti; önceki satırın bayt değişikliği de bu
  geçişe biner); OCR katmanı önbellekten gelir. Sonrasında sonucu değiştirmeyen değişiklik yeniden maskeletmez.
- 2026-11-24: Maskeleme çıktısı belirlenimci (d1-belirlenimci): aynı girdi + aynı kurallar → bayt bayt aynı maskeli
  dosya. PDF kaydında rastgele `/ID` üretilmez (özgününki korunur), docx/xlsx yeniden yazımında zip girdi zamanları
  sabit (1980-01-01) ve `docProps/core.xml`'de yalnız `created`/`modified` (özgünün değerleri) kalır; yeniden
  paketlenen zip/tar.gz üyeleri, çevrilen .xls/.doc ve .msg→eml sınırları da sabit. Maskeli dosyaların baytı bir
  kez değişir (bkz. sonraki satır: yeniden maskeleme tek sefer).
- 2026-11-24: Belge kimliği maskeli kopyanın baytına bağlı değil (k1-kimlik): maskeli kaynakta `doc_id` özgün
  dosyanın sha256'sından (`inventory.csv` `ozgun_sha256`); maskeli kopya yeniden üretilip baytı değişince kimlik
  ve kayıtlar korunur, metin yalnız gerçekten değiştiyse yenilenir. Eski çalışma alanlarında var olan kimlikler
  korunur (`kimlikler.jsonl`); doğrulanamayan kimlik silinmez, `_oksuz/`a alınır ve `bidr next` durur. Yeni
  komut `bidr kimlik-onar -w WS [--yedek DIR] [--uygula]`: kimliği kaymış belgeleri eski kimliklerine geri
  bağlar. Metni model yazmış (transcribe/describe) belge `--force` olmadan yeniden çıkarılmaz; kaynaktan çıkan
  belgenin okuma paketleri de `kaynaktan-cikarilan/`a taşınır. Güncellemeden sonra maskeli kaynaklı çalışma
  alanında önce `bidr kimlik-onar -w WS` (kuru koşu) çalıştırın.
- 2026-11-23: Paralel model aşamaları: varsayılan ajan sayısı min(20, n, 2 + (n-1)//20) (1 paket → 1, 2–20 → 2,
  sonra her 20 pakette +1, 361+ → 20); mutlak tavan 10 → 20; yeni `taban` ayarı (`rapor.paralel_taban`,
  `bidr parcala --taban`; vars. 2).
- 2026-11-23: İnceleme: yeni KARARINIZ seçeneği "Ret — başka maddenin konusu" (Doğru madde zorunlu, taşıma olarak
  uygulanır). `audit apply`: ret notunda başka ölçüt anılıp hedef verilmemiş ve belge hiçbir satırda sayılmıyorsa
  uyarı "N belge rapor dışına düştü" + satırda bilgi (`ret_hedefsiz_dustu`). Panel bu seçeneği tanıyan sürümle
  birlikte güncellenmeli.
- 2026-11-23: İkinci arama zorlama eşleşme: belge başka ölçütte kabul edilmişse paket istemi o kabulleri ve
  "aynı alıntı/içerik başka ölçüte taşınmaz → olcut_yok" kuralını taşır (yalnız bekleyen/yeni paketler; işlenmiş
  paket yeniden yazılmaz, görev sürümü değişmedi). Aynı alıntı (normalize) başka ölçütte kabulse eşleşme
  `ayni_alinti_kabul` işareti alır; inceleme kartında "Aynı alıntı X ölçütünde zaten kabul" dikkat notu.
- 2026-11-23: Aday üretimi dil farkı: `bidr/data/dil_karsiliklari.yaml` Türkçe–İngilizce karşılık sözlüğü
  (İngilizce belge → Türkçe ölçüt belirteci; ikinci aramada Türkçe ölçüt → İngilizce belge); `doc_types.yaml`
  `olcut_onceligi` (izlence → B.3.2, B.2.2, B.1.3). Aday sayısı ve kanıt sınırı değişmedi; yeniden aday üretimi
  (`bidr candidates`) gerekir.
- 2026-11-23: Aynı kâğıdın ayrı taramaları karardan önce tek grup (OCR metni + sayfa pHash'i): tek model paketi,
  incelemede tek satır (Dikkat'te "Kopyaları: …", gizli `kopyaları` sütunu), karar gruba; başka birim adı yalnız
  bilinen birim listesinden (x6-birim-kopya). Panel bu sütunu okuyan sürümle birlikte güncellenmeli.
- 2026-11-23: Paralel model aşamaları: `bidr parcala` / `bidr parca-denetle`, pipeline.yaml
  `paralel` kararı; `bidr next` bölünebilir aşamada "Paralel:" satırı gösterir (x5-paralel).
- 2026-11-23: `bidr maskele --kaynak` ilerleme dosyasına o an işlenen belgeyi yazar (`suanki`:
  dosya, sayfa/toplam_sayfa, aşama) (x3-suanki).
- 2026-11-23: `bidr maskele --yalniz-oneri`: hiçbir tespit kendiliğinden kapatılmaz, insan kararları
  uygulanır; bölgesiz biçimlerde (docx/xlsx/metin/html) desen başına öneri (x2-oneri).
- 2026-11-23: İnceleme sayfası (review.xlsx) ve istenen-kanitlar.xlsx yeni tasarım
  (gizli 1. satır başlıklar, görünen başlık 5. satırda); review.xlsx okuyucusu değişmedi (x1-excel).
- 2026-11-23: `bidr guncel` / `bidr guncelle` eklendi; `bidr next` günde bir kez yeni sürümü
  hatırlatır (`BIDR_GUNCEL_DENETIM=0` kapatır). Ajanlar oturum başında `bidr guncel` çalıştırır.
