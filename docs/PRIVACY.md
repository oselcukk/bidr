# Kişisel veri: maskeleme ve kurum notu

İsteğe bağlı modül (`bidr/mask/`; kurumsal gereksinim K8/K26). Ana hattı beklemez; hat aşamalarının
tamamlanma şartlarına girmez.

## Önce kurum notu: "ücretli API yok" verinin yerelde kaldığı anlamına gelmez

`bidr` model işini varsayılan olarak **ajan modunda** yaptırır: `prepare` iş paketlerini yazar,
bir kodlama ajanı (ör. Claude Code, Codex) paketleri okuyup cevabı yazar. Ücretli bir API anahtarı
kullanılmaması **belgelerin bilgisayardan çıkmadığı anlamına gelmez**:

- Ajan, iş paketlerini ve içlerindeki **belge metinlerini okur**. Ajan bulutta çalışan bir modele
  bağlıysa (abonelikle kullanılsa bile) okuduğu metin o modelin sağlayıcısına gönderilir.
- Ajan çalışma klasöründe dolaşabilir: iş paketlerinin dışında `text/`, `evidence/` ya da kaynak
  klasördeki dosyaları da açabilir. Model öncesi maskeleme yalnız iş paketlerine giren metni
  kapsar; ajanın doğrudan açtığı dosyaları kapsamaz.
- Belgelerde öğrenci, personel ve başvuru bilgisi (kimlik numarası, iletişim bilgisi, not,
  imza) bulunabilir; bunların yurt içi/yurt dışı bir hizmet sağlayıcıya aktarılması KVKK
  kapsamında bir işlemedir.

Bu nedenle kurum iki yoldan birini **açıkça** seçmelidir:

1. **Kullanımı onaylamak**: hangi ajan/sağlayıcının hangi belgeleri okuyacağı, sağlayıcının veri
   saklama ve eğitim koşulları ve aktarımın hukuki dayanağı kurumca (ör. veri sorumlusu / KVKK
   birimi) değerlendirilip onaylanır. `privacy.mask_before_model: true` bu durumda riski azaltır
   ama ortadan kaldırmaz (yalnız bilinen desenler ve listedeki adlar gizlenir).
2. **Yerel model kullanmak**: `config.yaml`'da `privacy.no_remote: true` ve yerel bir
   OpenAI uyumlu sunucu (ör. `base_url: http://localhost:11434/v1`); uzak sağlayıcılar kodla
   reddedilir (docs/MODEL_LAYER.md). Bu durumda ajan modu da yerel bir ajanla kullanılmalıdır.

Gerçek veriyle çalışmaya bu karar verilmeden başlanmamalıdır. Repo ve testler yalnız sentetik
veri içerir.

## İki kullanım

Maskeleme aynı yerel, kural tabanlı tespitçiyle (desenler + tesseract OCR + imza bölgesi; model
kullanılmaz, ağ bağlantısı yok) iki yerde kullanılır:

| kullanım | komut | ne zaman | girdi → çıktı |
|---|---|---|---|
| **A. Model öncesi kaynak maskeleme** | `bidr maskele --kaynak KLASÖR --out KOPYA` | belgeler modele (ajan/Claude) gösterilmeden **önce**; hat maskeli kopya üzerinde çalışır | bölüm belge klasörü (salt okunur) → aynı ağacın maskeli kopyası + rapor |
| **B. Teslim kopyası maskeleme** | `bidr maskele -w WS` | rapor/kanıt paketi paylaşılmadan önce | `evidence/` → `evidence-maskeli/` + `maskeleme-raporu.json` |

A, modele giden belge içeriğini azaltır: hat (`bidr ingest KOPYA -w WS`) yalnız maskeli kopyayı
görür. B, hattın sonunda paylaşılacak kanıtların kopyasını üretir. İkisi birlikte de kullanılabilir.
Ayrıca iş paketlerine giren metin için `privacy.mask_before_model` vardır (bölüm 2).

### Neyin maskelendiği, neyin maskelenMEdiği

| maskelenir (yer tutucuyla) | maskelenMEZ |
|---|---|
| T.C. kimlik no `[TC_NO]` (algoritma denetimli) | **adlar ve soyadlar** — yalnız `ad_listesi`'ndekiler `[AD]` olur; liste yoksa hiçbir ad maskelenmez |
| IBAN `[IBAN]` | **yüzler ve fotoğraflar** (yüz tanıma yok; fotoğraf olduğu gibi kalır) |
| e-posta `[EPOSTA]` (kurumsal adresler dahil) | **el yazısı** (OCR okuyamaz: el yazısıyla yazılmış numara/ad kalır; sayfa çoğu zaman `taranamadi` olur) |
| Türkiye telefon numarası `[TELEFON]` (kurum santrali dahil) | adres, doğum tarihi, not/puan, unvan, imza sirküsü dışındaki kişisel bilgiler |
| öğrenci no `[OGRENCI_NO]` (yıl önekli 9-10 hane ya da "öğrenci no: …" bağlamı) | düz metinde biçimi beklenmedik numaralar (kural tabanlı tespitin kaçırdıkları) |
| imza `[İMZA]` (imza etiketi/unvan bloğu yakınındaki mürekkep) | etiketsiz imza (elle bakılmalı listesine girer), paraf |
| belge üst verisi, yorumlar, izlenen değişiklikler, gömülü ekler | desteklenmeyen biçimlerin içi (eski `.doc`/`.xls`, `.pptx`, `.msg`, `.gif`/`.heic` …: olduğu gibi kopyalanır, elle bakılmalı) |

Belge kimliği bilgisi korunur: evrak sayısı (`Sayı: E-…`), tarih, karar/toplantı no, ders kodu,
sayfa no, doküman/form kodu (`FR-…`), DOI/URL içindeki sayılar maskelenmez. Yıl önekli öğrenci no
deseni "Sayı/Karar/Evrak/Belge/Proje/Protokol/Toplantı/Doküman/Form/Kod …" sözcüğünün hemen
ardındaki, harf/`-`/`/`/`.`/`=`/`%` ile başlayan ya da `-`/`/`/`.` + rakamla devam eden sayıyı
almaz; telefon deseni harf+tire ("FR-", "E-") ile başlayan kodu almaz (bkz. testler
`tests/test_mask_kaynak.py`).

Yer tutucular gerçek metindir: DOCX/XLSX/HTML/metinde değerin yerine, PDF'te (PyMuPDF motoru)
kapatılan siyah kutunun içine (koyu gri, metin katmanında) yazılır; görsellerde kutunun içine
çizilir. pypdf motorunda PDF değeri `X`'lerle değiştirilir (yer tutucu yok). Böylece model orada
bir kimlik no/telefon/imza bulunduğunu bilir ("belge imzalı") ama değeri görmez.

## A. Model öncesi kaynak maskeleme: `bidr maskele --kaynak`

```
bidr maskele --kaynak BÖLÜM_KLASÖRÜ --out MASKELİ_KOPYA [-w WS] [--ad-listesi DOSYA]
             [--motor auto|pymupdf|pypdf] [--is N] [--rapor DOSYA] [--ilerleme]
```

- Kaynak klasör **salt okunurdur**; hiçbir dosyasına yazılmaz. `--out` kaynakla iç içe olamaz; bidr'in
  üretmediği dosyalar içeren bir klasöre yazılmaz.
- Ağaç aynen kurulur (alt klasörler dahil). Desteklenen biçimler (PDF, DOCX, XLSX, düz metin, HTML,
  görseller) maskelenir ve her kopya bağımsız olarak yeniden taranır (B ile aynı adım).
- **Kaplar** (ingest'in açtığı türler) açılır, üyeleri aynı kurallarla — iç içe kaplar dahil —
  maskelenir ve kap maskeli üyelerle yeniden paketlenir: `.zip` → `.zip`, `.tar(.gz/.bz2/.xz)` →
  aynı biçim, `.eml` → `.eml` (başlıklar, gövde ve ekler; adres başlıklarında e-posta
  `eposta@maskeli.invalid` olur, çünkü `[EPOSTA]` geçerli adres değildir), `.7z`/`.rar` → yazılamadığı
  için `<ad>.7z.zip`. Üye yolları (`arsiv.zip!/alt/belge.pdf`) ingest'in okuduğu biçimde kalır.
  Bozuk/şifreli kap olduğu gibi kopyalanır (`hata`); şifreli üye yeni kaba alınamaz (`hata`).
- **Desteklenmeyen biçimler** olduğu gibi kopyalanır (`desteklenmiyor`, elle bakılmalı) — içleri
  maskelenmemiştir. Gizli/sistem dosyaları (`.DS_Store`, `~$` kilit dosyaları, `__MACOSX`) ingest gibi
  atlanır, kopyalanmaz.
- **Dosya ve klasör adları** da maskelenir (adında öğrenci no ya da listedeki ad geçen dosya
  `[OGRENCI_NO] transkript.pdf` olur; uzantı korunur; çakışırsa ` (2)`).
- **Hiçbir kanıt düşmez**: maskelemesi eksik kalan dosyanın (`basarisiz`: yeniden taramada bulgu ya
  da kapatılamayan imza adayı kaldı; `taranamadi`: OCR okuyamadı) maskeli kopyası, maskelenemeyen
  (`hata`) dosyanın **özgünü** ağaçta kalır. Bunlar raporda `elle_bakilmali: true` ile listelenir;
  komut 1 ile çıkar ve listeyi yazar. Modele vermeden önce bu liste gözden geçirilmelidir (gerekirse
  dosya kopyadan elle çıkarılır ya da elle karartılır).
- **Rapor**: `<out>.maskeleme-raporu.json` (ya da `--rapor`), **çıktı klasörünün dışında**. Dosya
  başına `dosya` (özgün yol), `hedef` (maskeli yol), `bicim`, `durum`
  (tamam/basarisiz/taranamadi/hata/desteklenmiyor/kap), `elle_bakilmali`, `neden`,
  `bulunan`/`maskelenen`/`kalan` (tür → sayı), `imza_bolgesi`; özet ve `elle_bakilmali` listesi.
  Değerlerin kendisi yazılmaz, ama **özgün dosya adları** (kişi adı içerebilir) yazılır: rapor
  modele verilmez.
- `-w WS` verilirse `config.yaml`'daki `privacy.maskeleme` kuralları (ad listesi, desenler) kullanılır;
  `--ad-listesi` ekler. `--is N` dosyaları N süreçte paralel işler (OCR yavaştır).

Sonra hat maskeli kopyayla çalıştırılır (`bidr ingest MASKELİ_KOPYA -w WS`). Alıntılar ve
rapor metni maskeli metinden gelir (yer tutucular görünür); teslimde özgün belgeler gerekiyorsa
kanıt dosyaları özgün klasörden eşlenir (`hedef` ↔ `dosya`).

Sınırlar: kural tabanlıdır; adlar yalnız listeden bulunur; el yazısı, yüz, fotoğraf maskelenmez;
desteklenmeyen biçimler maskelenmez; e-posta gövdesindeki satır içi görseller maskelenir ama
ingest onları okumaz. Bu yüzden A **riski azaltır, kaldırmaz**; yukarıdaki kurum notu geçerlidir.

## B. Teslim kopyası maskeleme: `bidr maskele -w WS`


```
bidr maskele -w WS [--evidence DIR] [--out DIR] [--motor auto|pymupdf|pypdf] [--ad-listesi DOSYA]
```

`bidr file`'ın ürettiği `evidence/` klasörünün **maskeli sunum kopyasını** üretir. Asıl dosyalara
dokunulmaz.

Çıktılar (varsayılan olarak `evidence/`'in yanında):

| dosya | içerik |
|---|---|
| `evidence-maskeli/` | yayımlanabilir kopyalar (yalnız yeniden taramadan temiz geçenler) |
| `maskeleme-basarisiz/` | yeniden taramada sızıntı/şüphe kalan ya da taranamayan dosyaların kopyaları (elle inceleme için; **yayımlanmaz**) |
| `maskeleme-raporu.json` | dosya başına `durum`, `elle_bakilmali`, `bulunan` / `maskelenen` / `kalan` (tür → sayı), `imza_bolgesi`, `imza_elle`, `taranamadi`, temizlenen üst veri, uyarılar, `yayimlanamaz` listesi |
| `evidence-index-maskeli.csv` | `evidence-index.csv` varsa: `ad`, `alintilar`, `kaynak` maskeli; `maskeleme` sütunu (tamam/basarisiz/taranamadi/desteklenmiyor/hata) |

Dosya durumları: `tamam` (yayın kopyası `evidence-maskeli/`'de), `basarisiz` (kişisel veri ya da
imza şüphesi kaldı), `taranamadi` (metin katmanı yok ve OCR'dan geçemedi), `desteklenmiyor`,
`hata`. `tamam` dışındaki her durumda `elle_bakilmali: true`: özgün kanıt rapor ve paketten
**çıkarılmaz**, yalnız yayın kopyası yoktur ("maskeleme eksik, elle bakılmalı"). Maskeleme kanıt
seçimini etkilemez.

Rapora bulunan değerlerin kendisi yazılmaz; yalnız tür ve sayı. Komut, yayımlanamaz dosya varsa
1, hata varsa 2 ile çıkar.

### Tespit edilenler

| tür | yer tutucu | kural |
|---|---|---|
| `tc_no` | `[TC_NO]` | 11 hane, ilk hane 0 değil, 10. ve 11. hane T.C. kimlik algoritmasını tutar |
| `iban` | `[IBAN]` | `TR` + 24 hane (boşluklu yazım dahil) |
| `eposta` | `[EPOSTA]` | ad@alan.uzantı |
| `telefon` | `[TELEFON]` | `+90`/`0090`/`0` önekli ya da alan kodu parantezli Türkiye numarası |
| `ogrenci_no` | `[OGRENCI_NO]` | yapılandırılabilir desenler; varsayılan: yıl önekli 9-10 hane ve "öğrenci no: …" bağlamı (belge kimliği bağlamı hariç, yukarıda) |
| `ad` | `[AD]` | yalnız yapılandırmadaki ad listesi (büyük/küçük harf ve ş/s, ı/i … duyarsız) |

### Görüntüdeki yazı: yerel OCR

Metin katmanı olmayan (taranmış) PDF sayfaları, sayfanın ≥%40'ını kaplayan görüntülü sayfalar,
görsel dosyalar (`.jpg .jpeg .png .tif .tiff .bmp .webp`) ve DOCX'e gömülü görseller yerel
**tesseract** (`tur+eng`; sistem aracı, Python bağımlılığı yok) ile kelime kutularına ayrılır. Aynı
desenler satır metnine uygulanır; OCR'ın sayılardaki karışıklıkları (O→0, l/I→1, S→5, B→8),
sayı içindeki boşluklar ve "E-posta:" etiketinden sonra `@`'si okunamayan adresler için ek
geçişler yapılır (T.C. algoritması yanlış pozitifi süzer). Eşleşen kutular siyah dikdörtgenle
kapatılır: PDF'te PyMuPDF redaction görüntü piksellerini de değiştirir (yalnız üstüne kutu
çizilmez); görselde Pillow ile, üst verisiz (EXIF/konum yok) yeni dosya yazılır. Maskeli kopya
yeniden OCR'lanır; bulgu kalırsa `basarisiz`.

**Taranamadı**: metin katmanı olmayan bir sayfa/görsel OCR'dan geçemezse — tesseract ya da dil
verisi yok, araç hatası, ya da mürekkepli sayfada güvenilir kelime çok az / ortalama güven < 50
(el yazısı, fotoğraf, kötü tarama) — dosya `taranamadi` olur; asla `tamam` sayılmaz. Boş sayfa
taranamadı sayılmaz.

### İmza

Model kullanılmaz; basit görüntü işleme (Pillow):

1. **Etiket bölgesi**: "İmza", "İmzası", "İmza:" (kısa satırda, `:` ile ya da tablo başlığında
   komşularından uzak; "… güvenli elektronik imza ile imzalanmıştır" notu etiket değildir). Etiketin
   sağı ve altı ile "İmza" sütununun altı (sütunda basılı metin başlayana kadar) imza bölgesidir.
2. **Mürekkep adayı**: koyu ya da renkli (mavi tükenmez) pikseller → güvenilir OCR/metin
   kelimeleri, uzun düz çizgiler (hafif eğik tablo kenarları dahil) ve dolu bloklar çıkarılır →
   bağlantılı bileşenler kümelenir → boyutu, seyrekliği, inceliği (aşındırınca kaybolan vuruş) ve
   yüksekliği/rengi imzaya benzeyen kümeler adaydır.
3. İmza etiketinin ya da imza bloğu sözcüklerinin (Üye, Başkan, Dekan, Rektör, Prof., Dr., Onay,
   Hazırlayan …; kısa satırda) yakınındaki aday kümesi (yakınındaki küçük vuruşlarla) siyah
   dikdörtgenle kapatılır. Etiketsiz aday kalan taranmış sayfa/görsel **"imza: elle bakılmalı"**
   olur (durum `basarisiz`); sayfanın üst %15'i (logo) bu kurala girmez.
4. Metin katmanlı PDF sayfasında yalnız küçük gömülü görseller (≤ 4×2,5 inç, başlıkta değil)
   aranır; vektör çizimler (tablo, akış şeması), filigran ve kapak görselleri aranmaz.
5. Yeniden tarama: maskeli kopyada kapatılmamış etiketli aday kalırsa `basarisiz`.
6. **`[İMZA]` işareti**: kapatılan her imza kutusunun içine koyu gri `[İMZA]` yazılır — PDF'te gerçek
   metin olarak (metin katmanında; model/okuyan belgenin imzalı olduğunu bilir), görselde ve DOCX'e
   gömülü görselde piksel olarak. Yazı rengi bilerek koyu gridir: beyaz yazı kutuyu "dolu blok"
   olmaktan çıkarır, harf araları yeniden taramada imza vuruşu sanılırdı. Maskeleyicinin yazdığı
   köşeli ayraçlı işaretler imza etiketi sayılmaz.

Yanlış karartma ölçüsü: kapatılan imza kutularıyla ≥%40 örtüşen güvenilir kelime sayısı raporda
`imza_ortusen_kelime` (dosya ve özet). El yazısıyla doldurulmuş form alanları imza adayıyla
karışabilir: etiketsizse sayfa elle bakılmalı olur, etiket yakınındaysa kapatılır.

Eski davranış da sürer: görsel içeren ve metninde "imza" geçen PDF sayfası (DOCX/XLSX'te belge
düzeyinde) `imza_uyarisi` olarak listelenir.

### Biçimler

- **PDF**: PyMuPDF kuruluysa (`pip install 'bidr[maske]'`; varsayılan motor; yoksa uyarı ve
  pypdf) gerçek kaldırma (redaction): bulunan
  bölge içerikten ve metin katmanından silinir, siyah kutu konur. PyMuPDF yoksa pypdf ile **en iyi
  çaba**: içerik akışındaki metin işlemlerinin baytları değiştirilir; iki baytlı/özel kodlamalı
  yazı tiplerinde, iç içe biçim nesnelerinde ve görüntüdeki (taranmış) metinde işe yaramaz — bu
  durum raporda açık uyarıyla belirtilir ve yeniden tarama yakalar. İki yolda da belge üst verisi,
  XMP, gömülü ekler, yorum/açıklamalar, form alanları, yer imleri ve yapı ağacı temizlenir; yalnız
  sayfalar yeni dosyaya taşınır (silinen nesneler dosyada kalmaz). PyMuPDF'in lisansı AGPL'dir;
  bu yüzden zorunlu bağımlılık değil, isteğe bağlıdır.
  **Örten açıklamalar**: elle karartma için çizilmiş kalın çizgi/mürekkep (Line/Ink ≥ 2 pt), dolu
  kutu, damga ve koyu (siyah) vurgulama açıklamaları silinmeden önce kapladıkları alan karartma
  olarak uygulanır (altındaki görüntü pikselleri ve metin silinir). Önceki sürüm bunları "yorum"
  diye siliyordu ve altındaki imza/ad açığa çıkıyordu. pypdf motoru bunu yapamaz: böyle bir dosya
  `hata` (elle bakılmalı) olur.
- **DOCX**: paragraf metni koşulara bölünmüş olsa da birleşik taranır, değer yer tutucuyla
  değiştirilir (gövde, tablolar, üst/alt bilgi, dipnotlar). Yorumlar ve izlenen değişikliklerin
  silinen metni kaldırılır; çekirdek, özel ve uygulama üst verisi ile küçük resim temizlenir;
  görsel alternatif metni, alan kodları (`fldSimple`), içerik denetimi etiketleri ve harici
  bağlantı adresleri (mailto) maskelenir. Gömülü görseller OCR'lanır; belgede imza etiketi varsa
  görseldeki imza benzeri mürekkep de kapatılır. Yapısal sayı öznitelikleri (nesne kimliği, rsid,
  Word'ün verdiği "Resim 123" adı) kişisel veri sayılmaz (önceki sürümde bunlar yanlışlıkla
  "öğrenci no" sayılıp DOCX'leri başarısız yapıyordu).
- **XLSX**: hücre metinleri ve sayı olarak yazılmış numaralar (ör. TC hücresi), üst/alt bilgi ve
  sayfa adları maskelenir; hücre yorumları ve belge üst verisi silinir. openpyxl görselleri ve
  grafikleri korumaz (uyarı verilir).
- **Düz metin** (`.txt`, `.csv`, `.md`, `.tsv`): metin değiştirme.
- **Görseller** (`.jpg .jpeg .png .tif .tiff .bmp .webp`): OCR + imza (yukarıda); aynı biçimde,
  üst verisiz kopya.
- **HTML** (`.html`, `.htm`; kaydedilmiş web sayfası): metin ve öznitelikler (`mailto:`, `title`,
  `alt`, `value` …) maskelenir, betikler ve HTML yorumları silinir; maskeli HTML yazılır (teslimde
  PDF'e çevirme teslim aşamasının işidir). Yeniden taramada öğeler arası bölünmüş değerler için
  birleşik metin ve `&#64;` gibi kodlanmış karakterler de aranır.
- **Diğerleri** (sunumlar …): taranamaz; kopyalanmaz, `yayimlanamaz` listesine girer.

### Yeniden tarama

Her maskeli kopya, maskeleyiciden bağımsız bir okuyucuyla yeniden taranır (PDF: sayfa metni, üst
veri ve sıkıştırılmamış bütün akışlarda ham arama; DOCX/XLSX: paketteki bütün XML parçaları ve
öznitelikleri). Kişisel veri ya da temizlenmemiş üst veri/yorum/ek kalırsa kopya
"maskeleme başarısız" işaretlenir, `evidence-maskeli/`'den çıkarılıp `maskeleme-basarisiz/`'e
alınır ve yayımlanamaz listesine yazılır.

Sınırlar: OCR el yazısını okuyamaz (el yazısı sayfa `taranamadi` ya da imza şüphesiyle elle
bakılmalı olur); imza tespiti sezgiseldir (etiketsiz imza ve imzaya benzeyen çizimler elle
bakılmalı); PyMuPDF yoksa taranmış sayfadaki bulgu ve imza kapatılamaz (yeniden tarama
yakalar, dosya `basarisiz`); ad tespiti yalnız listedeki adları bulur; kural tabanlı tespit her
biçimi yakalamaz. Yayından önce `maskeleme-raporu.json`, `imza_elle` sayfaları ve imza uyarıları
insan tarafından gözden geçirilmelidir.

## 2. İş paketi metni maskeleme: `privacy.mask_before_model`

Açıksa iş paketlerine ve hat modu istemlerine giren metinlerde aynı kurallarla yer tutucu
kullanılır (`[TC_NO]`, `[OGRENCI_NO]`, `[EPOSTA]` …). Varsayılan kapalıdır.

Yardımcı: `bidr.mask.model.ModelMasker` (`load(ws)`, `inputs(dict)`, `text(str)`,
`render(render_task)`, `verify_quote(verify_quote)`). Model maskeli metni gördüğünden alıntılar
yer tutucu içerebilir; alıntı denetimi aynı kurallarla maskelenmiş metne karşı yapılır ve eşleşme
aralığı özgün metne geri çevrilir (`ModelMasker.verify_quote`).

Bu sürümde yardımcı yazıldı; aşamaların paket hazırlayan koduna bağlanması ayrı bir değişikliktir
(bağlanma noktaları: `bidr/decide/run.py` ve `bidr/write/run.py`'deki `Backend` —
`render_task`/`verify_quote` sarmalanır —, `bidr/verify/run.py` ve `bidr/name/run.py`'nin
`render_task` çağrıları). Görsel okuyan aşamalar (transcribe, describe) görüntü gönderir; bunlar
metin maskelemesinin kapsamı dışındadır.

Yerel model genişletme noktası: `privacy.maskeleme.yerel_model` ileride ad/kişi tanımayı yerel bir
modele yaptırmak için ayrıldı (`bidr.mask.detect.register_detector` ile ek tespitçi bağlanır); bu
sürümde uygulanmaz, yalnız uyarı verir.

## config.yaml

```yaml
privacy:
  no_remote: false            # true: yalnız yerel sağlayıcılar (docs/MODEL_LAYER.md)
  mask_before_model: false    # true: iş paketlerine giren metinde yer tutucu
  maskeleme:                  # hepsi isteğe bağlı
    turler: [tc_no, iban, eposta, telefon, ogrenci_no, ad]
    ogrenci_no_desenleri: ['(?<!\d)(?:19|20)\d{7,8}(?!\d)']   # Python düzenli ifadesi; grup 1 varsa yalnız o
    ad_listesi: personel.txt  # ya da liste; .txt satır başına bir ad, .csv ilk sütun; göreli yol ws'e göre
    yerel_model: null         # genişletme noktası (bu sürümde uygulanmaz)
```

Ad listesi gerçek kişi verisidir: çalışma klasöründe tutulur, repoya girmez.
