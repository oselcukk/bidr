# Değişiklikler

Her birleştirmede (main'e giren her değişiklik) buraya en üste bir satır eklenir: tarih, kısa
açıklama ve kullanıcıyı ilgilendiriyorsa ne yapması gerektiği. `bidr guncelle` güncellemeden sonra
bu dosyanın yeni satırlarını gösterir. Bu dosyadan önceki geçmiş için `git log`.

- 2026-11-27: FR-0833 Değ.No:1 (10.11.2026) şablonu: kapaktaki "Raporu Onaylayan Birim Amiri" yeni alanı
  `rapor.onaylayan` (answers.yaml `onaylayan`: `{unvan, ad_soyad, eposta, gorev}`); şablonda bölüm varken boşsa rapor
  TASLAK. Hazırlayan yer tutucuları başlığa göre bölümlenir (amir satırı artık hazırlayan sayılmaz; fazla kişi amir
  başlığından önce eklenir). Yıl yer tutucusu "20.." tanınır (`--yil`). `bidr denetle` amir satırını ayrı denetler
  (`kapak_onaylayan`). Ölçüt blokları iki şablonda aynı: şablonu değiştirmek yalnız `bidr render` (+ denetle/teslim)
  ister, model yok. Yapılacak: answers.yaml'a `onaylayan` + `sablon: <yeni .docx>` ile `bidr init`, sonra `bidr render`.
- 2026-11-26: Kanıt atıf gösterimi rapor boyunca kılavuz biçiminde: render (`--kanit-bicimi kilavuz`, vars.) metin
  içi atıfları, önceki yıla göre metnini ve yön maddelerini de `[1-OD3]` yazar (liste satırı zaten `[1-OD3]. Ad`).
  İç biçim `[n_ODk]` değişmedi (istem, write/verify doğrulaması, parmak izleri, görev sürümleri, `texts/*.json`):
  model yeniden çalışmaz. Biçim denetimi metin içi atfın listenin gösterimiyle aynı olmasını ister (ölçüt başına bir
  `atif_gosterimi` uyarısı, kritik değil); teslim paketi numaraları `1-OD3` yazar. Var olan rapor için: `bidr render`
  (+ `bidr denetle`, teslim paketi varsa `bidr teslim`) — model yok.
- 2026-11-26: Karar aşamalarının (kaba/ince) "eski olabilir" parmak izi kod dosyalarını sözdizimi olarak okur
  (`bidr/decide/parmak.py`, iz `v2-…`): belge dizgesi, yorum ya da biçim düzenlemesi aşamaları artık eskitmez
  (canlı olay: run.py'de yalnız açıklama değişti, karar_kaba "eski olabilir" deyip audit'i durdurdu). Görev/istem
  metni, ölçüt/profil verisi ve çalışma alanı girdileri bayt olarak girmeye devam eder. Geçiş: eski biçimli iz
  (önceki sürümün son tam prepare'i) dondurulmuş eski run.py (`parmak_eski/run-44c8add.py.gz`) ile birebir tutuyor ve
  aradaki kod farkı davranışsızsa geçerli sayılır; bu sürüme geçmek tek başına bir aşamayı eskitmez, model işi
  doğurmaz. Yapılacak bir şey yok; ilk tam prepare izi yeni biçimde yazar.
- 2026-11-26: Model cevabı hiçbir aşamada işi kilitlemez (canlı olay: describe "13 cevap geçersiz/şüpheli"):
  transcribe'daki kural ortak oldu (`bidr/pipeline/cevap.py`) ve bütün ajan aşamalarına uygulandı (describe, kaba/ince
  karar, belirsiz okuma, ad, ikinci arama, yazım, doğrulama, yönler, kör denetim). Geçersiz/şüpheli cevap kenara alınır
  (`.red<n>.eski`), paket yeniden cevapsız (ajan üstüne yazmaz; panelin cevap koruması yeniden yazımı geri almaz);
  aynı nedenle ikinci ret (ya da üçüncü ret) → elle bakılmalı (`work/<aşama>/ELLE-BAKILMALI.md`, `bidr next` uyarısı),
  aşama ilerler. Anlamı aşamaya göre: betimleme yok sayılır (metin OCR'da); karar yok; ad kural adında; ikinci arama eşleşme eklemez; yazım/doğrulama/yön doğrulaması
  bölümün kararına (panel karar ekranı), yön yazımı şablon yönergesiyle; kör denetim paketi denetlenemedi. Şema
  enum'unda bilinmeyen değer `diger` seçeneği varsa `diger` olur (ör. `yer: pano`; özgün değer kayıtta). Describe
  talimatında enum listeleri açık; yalnız talimatı değişen paketin verilmiş cevabı korunur. Deneme kaydı ws kökünde
  `cevap-denemeleri.json` (transcribe'ın eski kaydı oraya taşınır). Yapılacak bir şey yok: sıradaki apply var olan
  cevapları yeni kuralla işler. Görev sürümü artmadı, şemalar yalnız genişledi: verilmiş cevaplar geçerli kalır.
  Bölümün kararı: elle bakılmalı belgeler (görsel okuma, betimleme, kaba/ince karar, ad, ikinci arama) review.xlsx
  "İnceleme" sayfasının 1. bölümünde öbür öneriler gibi satır olur (satır kimliği `<doc_id>|elle:<aşama>`; panelde
  İncelemeniz); KARARINIZ Kabul = modelin okuduğunu kullan (yalnız şüpheli okuma/betimleme), Ret = taramadaki metinle /
  model kararı olmadan kalsın. `bidr audit apply` kararı `work/<aşama>/elle-kararlar.jsonl`'e yazar; karar KESİNDİR:
  belgenin içeriği değişmedikçe yeniden doğrulanmaz, sorulmaz (paket yenilense de). Karar verilmeyen belge raporu
  durdurmaz (varsayılan: taramadaki metin). Komut satırı: `bidr elle liste|karar` (kararı yalnız kullanıcı verir).
- 2026-11-26: Görsel okuma (transcribe) takılmaz (canlı olay): her yeri `[okunamadı]` olan cevap reddedilmez,
  "görselde metin yok" olarak normalleşir (`bos`, boş metin); sayfa başına isteğe bağlı `notlar` şemada (görev sürümü
  artmadı). Geçersiz/şüpheli cevap kenara alınır (`.red<n>.eski`), paket yeniden okunur; aynı nedenle ikinci ret
  (ya da üçüncü ret) belgeyi `elle_bakilmali` yapar: metni OCR'da kalır, `work/transcribe/ELLE-BAKILMALI.md` ve
  `bidr next` uyarısında görünür, aşama ilerler. Şüpheli belge sonradan `apply --kabul-supheli --only <id>` ile
  kabul edilebilir. Talimat metni netleşti; yalnız talimatı değişen paketin verilmiş cevabı korunur (yeniden model
  çağrısı yok). Yapılacak bir şey yok: sıradaki `bidr transcribe apply` var olan cevapları yeniden işler.
- 2026-11-24: Faaliyet kaydında dosya serisi bölünmez, adı seriyle uyumlu (prova düzeltmesi): tarihsiz belge aynı
  dosya serisinden üyesi olan kayda önce bağlanır ("ulusal staj 2026-1…5" tek kayıt); kayıt adı belgelerin
  çoğunluğunun adı, eşitlikte seriyle uyumlu ad (önceden uzunluk: "Gibbs Eşitsizliği Semineri"). `faaliyetler.json`
  modelsiz yeniden hesaplanır (`bidr faaliyet`).
- 2026-11-24: `fotograf` sanılan PDF fotoğraf sayılmaz (prova düzeltmesi): etkinlik dosyası ipucu, yakın-tarih sinyali
  ve "bu fotoğraf hangi etkinliğe ait?" isteği yalnız gerçek görsel dosyalara (jpg, jpeg, png, heic, heif, webp).
  Provada açılan tek yanlış ince karar paketi (giriş ekranı PDF'i) artık açılmaz. Model yok.
- 2026-11-24: Eksik listesinde etkinlik istekleri daraldı (prova düzeltmesi): yalnız gerçek etkinlik türleri (seminer,
  konferans, çalıştay, staj programı, tanıtım/tercih günü, kulüp, şenlik, söyleşi…; toplantı, kurul, protokol,
  anlaşma, seçim, başvuru, sınav ve dış etkinliğe katılım değil) ve yalnız bölümün etkinlikleri; madde başına en çok
  bir gerçekleşme ve bir değerlendirme satırı (birden çok etkinlik tek satırda). Model yok.
- 2026-11-24: Eksik listesinde tek anket maddesi kısmen sayılır (prova düzeltmesi): anket belgesinden tek cümlelik
  alıntı, ana metni anket/geri bildirim istemeyen yuvayı (B.1.4/7 "AKTS hesaplama tabloları…") yalnız kısmen
  doldurur; "En az bir ders için ders bazında AKTS iş yükü hesap tablosu" istenir. Model yok.
- 2026-11-24: Eksik listesinde karşılayan belge türüyle seçilir (prova düzeltmesi): geçen yılın belgesi yalnız aynı
  TÜRden (adın tür ifadesi: anket sonucu, ders bilgi formu, seminer, iş akışları listesi…; ve sınıflandırma) kabul
  edilmiş belgeyle kapanır; yuvanın başka türden belgeyle dolu olması kapatmaz. Kapanan istek kendi satırında ☑ ve
  "Dosyada var: «…»" notuyla durur (önceden maddenin ilk satırında "İstenmedi"). Model yok; `bidr ihtiyac` yeniden çalıştırmak yeter.
- 2026-11-24: Eksik listesi inceleme kararlarına göre (d3a): `bidr ihtiyac` geçen yılın belgesini kabul edilmiş
  inceleme kararlarıyla da arar: aynı belge başka ölçütte, derse özgü istekte aynı türden herhangi bir belge, aynı
  ölçütte dolu yuva/aynı tür ("başka belgeyle"), başka ölçütte kanıt olan kurum belgesi → istenmez, "Var olan
  kanıt" sütununda "İstenmedi (dosyada var): …". Yalnız tek soru/çok kısa alıntıyla dolu yuva "kısmen" sayılır,
  somut istek kalır. Model yok; yeniden çalıştırmak yeter.
- 2026-11-24: Etkinlik dosyası ve planlama kanıtı (d3a): afiş/duyuru planlama kanıtıdır (ince karar istemi, kanıt
  ilkesi `etkinlik_dosyasi`, doğrulama istemi; görev sürümleri artmadı). Aynı klasör/dosya serisindeki fotoğrafa
  grubun etkinlik adı ipucu olarak verilir (model karar verir); gerçekleşmesi aynı ölçütte
  kanıtlı etkinliğin duyurusu uygulama sayılır. `bidr ihtiyac` etkinliği adıyla ister (gerçekleşme, OD3 ölçütte değerlendirme) ve bağlamsız
  fotoğraf için belge notu ister. BİR KEZ: `bidr faaliyet` yeniden ister (yeni alanlar); ipucu alan fotoğraflar
  onaysız yeniden karara gider; öteki ince kararlar "kural değişti" bilgisiyle geçerli kalır.
- 2026-11-24: Yön hücresi için bölüm kararı (d3b): güçlü/gelişmeye açık yön alanı yeniden yazımlardan sonra
  doğrulamada hâlâ reddedilirse `bidr next` yonler aşamasında `kim: insan` + `karar_bekleyen` verir (önceden yalnız
  desteklenen maddeler basılıp rapor TASLAK oluyordu). `bidr yonler karar -w WS <alan> tekrar|kabul|cikar`
  (`yonler-insan.jsonl`); `kabul` yalnız bütün reddedilen maddeler "kısmen" ise; `kabul`/`cikar` o alanın TASLAK
  nedenini kaldırır.
- 2026-11-24: Elle eşleşme (d3b): bölüm modelin önermediği belge–ölçüt eşleşmesini ekleyebilir (`elle-eslesmeler.json`;
  `bidr audit elle esitle|ekle|geri|liste -w WS`). Eşleşme review-decisions.jsonl'e insan kaynaklı kabul olarak girer
  (`kaynak: insan`, `elle`), OD/PUKÖ, kanıt dosyalama ve yazımda olağan kabul gibi sayılır; alıntısızsa ikinci aramayla
  belgeden aranır. Yinelenen ekleme kayıt açmaz, geri alma önceki kararı geri getirir (docs/AUDIT.md "Elle eşleşme").
- 2026-11-24: Raporun kör denetimi ve düzeltmesi (d2, isteğe bağlı aşamalar `kor_denetim`, `duzelt`): `bidr denetim
  prepare|apply|karar|ozet`, `bidr duzelt prepare`. İstenmezse hat eskisi gibi biter. Metin bulguları kendiliğinden
  düzeltilir ve yeniden doğrulanır; OD/kanıt önerilerinin bölüm kararı hattı tutmaz (rapor tamamlandı sayılır, `bidr
  next` bekleyen önerileri "Bilgi:" satırında, `--json` üst düzey `oneri_bekleyen`'de gösterir); kabul edilen OD
  sonradan küçük bir düzeltme turu açar. Bölümün daha önce olduğu gibi kabul ettiği metin (`verify karar`/`write
  karar` `kabul`) kendiliğinden yeniden yazılmaz: ona düşen metin bulgusu "Kabul edilmiş metne öneri" olarak bölüm
  kararına gelir (kabul → küçük düzeltme turu, ret → metin aynen kalır; metin denetim dışı bir nedenle değiştiyse
  olağan düzeltme; denetim düzeltmesiyle yeniden yazıldıysa karar verilmemiş öneriler `eskidi` olur).
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
