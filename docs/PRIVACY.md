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
| e-posta `[EPOSTA]` (kurumsal adresler dahil) | **el yazısı değerin kendisi** (OCR okuyamaz); yalnız BASILI kişisel veri etiketinin alanı kapatılır (aşağıda, `[KİŞİSEL VERİ]`). Etiketi de el yazısıyla yazılmış alan kalır; modelin okuma metni varsa dosya "elle bakılmalı" olur |
| Türkiye telefon numarası `[TELEFON]` (kurum santrali dahil) | adres, doğum tarihi, not/puan, unvan, imza sirküsü dışındaki kişisel bilgiler |
| öğrenci no `[OGRENCI_NO]` (yıl önekli 9, 10 ya da 12 hane, kurum profilindeki desenler ya da "öğrenci no: …" bağlamı) | düz metinde biçimi beklenmedik numaralar (kural tabanlı tespitin kaçırdıkları) |
| taranmış sayfada kişisel veri etiketinin alanı `[KİŞİSEL VERİ]` (kimlik/pasaport no, öğrenci no, doğum tarihi/yeri, adres, telefon/GSM, e-posta etiketinin sağı ya da alttaki hücre; el yazısıyla doldurulmuş değer okunmasa da) | — |
| imza `[İMZA]` (imza etiketi/unvan bloğu yakınındaki mürekkep) | etiketsiz imza (elle bakılmalı listesine girer), paraf |
| belge üst verisi, yorumlar, izlenen değişiklikler, gömülü ekler | desteklenmeyen biçimlerin içi (`.ppt`/`.pptx`, `.gif`/`.heic` …; araç yoksa eski `.doc`/`.msg`: olduğu gibi kopyalanır, elle bakılmalı) |

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
             [--motor auto|pymupdf|pypdf] [--is N] [--rapor DOSYA] [--ilerleme] [--ayir]
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
- **Eski biçimler** geçici klasörde yeni biçime çevrilip maskelenir; maskeli kopyada yeni
  uzantısıyla durur (rapor: `dosya` özgün ad, `hedef` yeni ad, `ozgun_bicim`, `donusum`):
  `.doc` → `.docx` (macOS `textutil`; textutil'in Word belgesi olarak tanımadığı dosya çevrilmez;
  textutil yoksa — Linux/Windows — LibreOffice ile `.pdf`), `.ppt`/`.pptx` → `.pdf` (LibreOffice:
  `soffice --headless --convert-to pdf`, her çağrıda ayrı geçici kullanıcı profili
  `-env:UserInstallation=…`, tek süreç, zaman aşımı),
  `.xls` → `.xlsx` (xlrd ile okunur, openpyxl ile yazılır: hücre değerleri, tarihler, sayfa adları,
  birleşik hücreler; formül hesaplanmış değer olarak, biçim/grafik/görsel taşınmaz), `.msg` → `.eml`
  (`extract-msg` kuruluysa: başlıklar, gövde, ekler; sonra `.eml` gibi). Uzantısı `.doc`/`.xls` olup
  içi docx/xlsx ya da HTML olan dosyalar doğru biçime yönlendirilir. Çevrilemeyen (textutil de
  LibreOffice da yok — açık kurulum mesajıyla —, `extract-msg` yok, bozuk dosya) olduğu gibi
  kopyalanır, `desteklenmiyor` + anlaşılır neden, elle bakılmalı. Çevrilen biçimde yazı biçimi ve
  gömülü görseller kaybolabilir (uyarı); özgün dosya kaynakta durur.
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
- **`--ayir`**: elle bakılmalı dosyalar (`basarisiz`, `taranamadi`, `hata`, `desteklenmiyor`) maskeli
  kopyaya **girmez**; kopyanın dışında `<out>.elle-bakilmali/` klasörüne aynı göreli yolla konur
  (kap üyesi: `<kap adı>/<üye yolu>`; kaptan çıkarılır, e-posta ekinin yerine kısa bir
  `<ek>.ayrildi.txt` notu konur). Raporda kayıt başına `ayrildi`, ayrıca `ayrilan` listesi ve
  `ozet.ayrilan`. Hiçbir dosya silinmez; yalnız yeri değişir. Varsayılan (bayraksız) davranış
  "kanıt düşmez": hepsi kopyada kalır.
- **Rapor**: `<out>.maskeleme-raporu.json` (ya da `--rapor`), **çıktı klasörünün dışında**. Dosya
  başına `dosya` (özgün yol), `hedef` (maskeli yol), `bicim`, `durum`
  (tamam/basarisiz/taranamadi/hata/desteklenmiyor/kap), `elle_bakilmali`, `neden`,
  `bulunan`/`maskelenen`/`kalan` (tür → sayı), `imza_bolgesi`, `imza_ortusen_kelime`,
  `imza_metin_elle` (metinle örtüştüğü için kapatılmayan imza sayfası/görseli); özet
  (`eski_bicim_cevrilen`, `imza_metinle_ortusen_elle`, `--ayir` ile `ayrilan`) ve `elle_bakilmali` listesi.
  Değerlerin kendisi yazılmaz, ama **özgün dosya adları** (kişi adı içerebilir) yazılır: rapor
  modele verilmez.
- `-w WS` verilirse `config.yaml`'daki `privacy.maskeleme` kuralları (ad listesi, desenler) kullanılır;
  `--ad-listesi` ekler. `--is N` dosyaları N süreçte paralel işler (OCR yavaştır).

Sonra hat maskeli kopyayla çalıştırılır (`bidr ingest MASKELİ_KOPYA -w WS`). Alıntılar ve
rapor metni maskeli metinden gelir (yer tutucular görünür); teslimde özgün belgeler gerekiyorsa
kanıt dosyaları özgün klasörden eşlenir (`hedef` ↔ `dosya`).

Sınırlar: kural tabanlıdır; adlar yalnız listeden bulunur; el yazısı (basılı etiketinin alanı
dışında), yüz, fotoğraf maskelenmez;
desteklenmeyen biçimler maskelenmez; e-posta gövdesindeki satır içi görseller maskelenir ama
ingest onları okumaz. Bu yüzden A **riski azaltır, kaldırmaz**; yukarıdaki kurum notu geçerlidir.

## B. Teslim kopyası maskeleme: `bidr maskele -w WS`


```
bidr maskele -w WS [--evidence DIR] [--out DIR] [--motor auto|pymupdf|pypdf] [--ad-listesi DOSYA]
                   [--is N] [--ilerleme] [--onbellek-yok]
bidr maskele bolgeler -w WS [--json]                         # onay bekleyen (--json: bütün) bölgeler
bidr maskele karar -w WS <bolge_id> kapat|birak|sil [--kim AD]   # bölge kararı (sil: yalnız kullanıcı bölgesi)
bidr maskele ciz -w WS <dosya> --sayfa N --kutu x0,y0,x1,y1 [--kim AD] [--json]   # kullanıcı bölgesi
bidr maskele sayfa -w WS <dosya> --sayfa N [--dpi 110] [-o out.png] [--maskeli] [--json]
bidr maskele yukle -w WS <dosya> <maskeli_dosya> [--kim AD] [--zorla]
```

İnceleme komutları (`bolgeler`, `karar`, `ciz`, `sayfa`, `yukle`) kanıt modunun `<ws>/maskeleme-raporu.json`'unu,
o yoksa ön işlemenin `<ws>/maskeleme-kaynak-raporu.json`'unu okur (`bidr maskele --kaynak KLASÖR --out KOPYA
-w WS`; modelsiz, `bidr file` öncesi). `<dosya>`: rapordaki yol, klasördeki yol ya da belge kimliği
(sha256/öneki). Kararlar (`maskeleme-kararlari.jsonl`) ve elle maskelenmiş sürümler (`maskeleme-elle.json`,
kaynağın sha256'sıyla) iki modda da geçerlidir: ön işlemede verilen karar sonraki kanıt maskelemesine taşınır,
aynı içerikli kopyalar aynı kararı alır. Kutular dışarıya görüntülenen sayfanın PDF puanında (sol üst köken)
verilir; `sayfa` PNG ölçeği dpi/72.

`bidr file`'ın ürettiği `evidence/` klasörünün **maskeli sunum kopyasını** üretir. Asıl dosyalara
dokunulmaz.

Çıktılar (varsayılan olarak `evidence/`'in yanında):

| dosya | içerik |
|---|---|
| `evidence-maskeli/` | yayımlanabilir kopyalar (yalnız yeniden taramadan temiz geçenler) |
| `maskeleme-basarisiz/` | yeniden taramada sızıntı/şüphe kalan ya da taranamayan dosyaların kopyaları (elle inceleme için; **yayımlanmaz**) |
| `maskeleme-raporu.json` | dosya başına `durum`, `elle_bakilmali`, `bulunan` / `maskelenen` / `kalan` (tür → sayı), `imza_bolgesi`, `imza_elle`, `taranamadi`, temizlenen üst veri, uyarılar, `yayimlanamaz` listesi |
| `evidence-index-maskeli.csv` | `evidence-index.csv` varsa: `ad`, `alintilar`, `kaynak` maskeli; `maskeleme` sütunu (tamam/basarisiz/taranamadi/desteklenmiyor/hata/elle_maskelendi) |
| `maskeleme-kararlari.jsonl` | insan bölge kararları (`bidr maskele karar`; çalıştırmalar arasında kalır) |
| `maskeleme-elle/` + `maskeleme-elle.json` | elle maskelenmiş sürümler (`bidr maskele yukle`; kanıtın sha256'sıyla) |
| `.cache/maske.sqlite` | içerik adresli önbellek (aşağıda; silinebilir, sonuç değişmez) |

Dosya durumları: `tamam` (yayın kopyası `evidence-maskeli/`'de), `elle_maskelendi` (insanın
yüklediği maskeli sürüm `evidence-maskeli/`'de), `basarisiz` (kişisel veri ya da imza şüphesi kaldı,
onay bekleyen bölge var ya da redaksiyon doğrulaması geçmedi), `taranamadi` (metin katmanı yok ve
OCR'dan geçemedi: okunamayan sayfa bölgesi onay bekler), `desteklenmiyor` (eski biçim çevrilemediyse
`onay_bekliyor: true`), `hata`. `tamam`/`elle_maskelendi` dışındaki her durumda `elle_bakilmali:
true`. Maskeleme kanıt seçimini etkilemez: kanıt rapordan çıkarılmaz, atıfı ve numarası değişmez;
yalnız **teslim kapısı** (aşağıda) dosyayı insan kontrolüne kadar pakete almaz.

Eski biçimler (`.doc`, `.xls`, `.ppt`, `.pptx`, `.msg`) kanıt modunda da çevrilip maskelenir (yukarıdaki
A bölümüyle aynı çeviriciler; Linux'ta LibreOffice); maskeli kopya yeni uzantısıyla durur (kayıtta
`maskeli`, `donusum`), teslim paketi o kopyayı alır. Çeviri sonucu önbelleğe yazılır. Çevrilemeyen
dosya kontrol bekler ve pakete girmez; LibreOffice yoksa neden açıkça söylenir.

### Bölgeler, insan kontrolü ve teslim kapısı

Her dosya kaydında (`maskeleme-raporu.json`, PDF/PyMuPDF ve görseller) `bolgeler` listesi vardır;
eski alanlar korunur:

```
{"id": "<dosya-sha8>-s<sayfa>-<sıra>", "sayfa": 1, "kutu": [x0, y0, x1, y1],   # PDF puanı (görselde
 "tur": "imza" | "el_yazisi_alan" | "kisisel_veri" | "okunamayan_sayfa",       #  piksel → puan)
 "karar": "kapatildi" | "onay_bekliyor" | "birakildi", "neden": "…", "kaynak": "kural adı",
 "guven": 0.0-1.0, "geri_basilan": null, "kapali": true | false, "insan": {"karar", "kim", "zaman"}?}
```

`kapali`: kutu maskeli kopyada kapatıldı mı. `onay_bekliyor` bölge çoğunlukla AÇIKTIR (insan kararına kadar);
`maskeleme-basarisiz/` inceleme kopyasında (ve `--kaynak` ağacındaki eksik maskeli kopyada) bu bölgeler
turuncu kesik çerçeve ve "[ONAY BEKLIYOR]" işaretiyle çizilir: inceleyici kopyayı maskeli sanmasın. Tek
istisna metinle örtüşen imza (ad yalnız OCR'dan okundu): kutu kapalıdır, onay "geri basma gerekli mi" içindir.
Kullanıcı bölgesi (`ciz`): `tur`/`kaynak` `kullanici`, kimlik `<sha8>-s<sayfa>-k<n>`; her koşuda gerçek
redaksiyonla uygulanır, ayrıca form şablon belleğine öneri örneği olur (aynı formdan başka belgede yalnız
`onay_bekliyor` öneri; kendiliğinden kapatılmaz). Kapatılan kutuya yazılan işaret: imza `[İMZA]`, imza
olmayan görsel (fotoğraf, rozet, ikon) `[GÖRSEL]`.

Kimlik kararlıdır (aynı girdi + aynı kurallar → aynı kimlik). Kaynaklar: `metin_deseni`,
`ocr_deseni`, `etiket_alani`, `kapatan_isaretleme`, `imza_aday` (kapatıldı), `imza_etiketsiz`,
`imza_metin` (metinle örtüşen imza), `imza_kalan` (maskeli kopyada kapatılmamış aday), `ocr`
(okunamayan sayfa), `model_metni` (modelin okuma metninde olup kapatılmayan tür; yalnız sayfa
bilinir). Yeniden taramanın adayı bilinen bölgeyle (aynı sayfa, aynı tür, örtüşen kutu) eşleşirse
açıklanmış sayılır; eşleşmeyen yeni bölge olarak onay bekler. `onay_bekliyor` bölgesi olan dosya
`elle_bakilmali: true`'dur.

- `bidr maskele bolgeler -w WS [--json]` onay bekleyen bölgeleri (dosya, kimlik, sayfa, tür, kutu,
  neden), kararı verilip henüz uygulanmamışları ve bölgesi olmayan kontrol bekleyen dosyaları
  (yalnız elle maskeleme) listeler; bekleyen varsa çıkış kodu 1.
- `bidr maskele karar -w WS <bolge_id> kapat|birak [--kim AD]` `maskeleme-kararlari.jsonl`'a satır
  ekler (`{"id", "karar", "kim", "zaman", "kutu", "tur", "kaynak"}`; aynı kimliğin son satırı
  geçerli). Sonraki `bidr maskele` bölgeyi kimliğiyle bulur: `kapat` → kapatılır (okunamayan sayfada
  bütün sayfa), `birak` → açık bırakılır; karar verilmiş bölge yeniden sorulmaz. Kararın kutusu/türü
  bölgeyle eşleşmezse (kurallar değişip sıra kaydıysa) karar uygulanmaz, uyarı verilir. Otomatik
  kapatılan desen ve etiket alanı bulguları `birak` ile açılamaz (yalnız imza); `model_metni`
  bölgesi yalnız `birak` alır (yeri bilinmediği için kapatmak elle maskelemeyle olur).
- `bidr maskele yukle -w WS <kanit_dosyasi> <maskeli_dosya>` elle maskelenmiş sürümü kabul eder:
  `maskeleme-elle/`'ye kopyalanır, kayıt hemen `elle_maskelendi` olur ve kopya `evidence-maskeli/`'ye
  konur; sonraki çalıştırmalar kanıt dosyası değişmedikçe (sha256) aynı sürümü kullanır. Yüklenen
  dosyada metin desenine uyan kişisel veri kalmışsa reddedilir (`--zorla` ile kabul, uyarıyla).

**Teslim kapısı** (`bidr teslim`, politika 2026-11-22): maskelenecek yeri çözülmemiş dosya — onay
bekleyen bölgesi olan, `basarisiz`, `taranamadi`, `hata`, `desteklenmiyor`, maskeli kopyası eski ya
da raporda olmayan — kanıt paketine (ve `evidence-maskeli/`'ye) otomatik **girmez**. Rapordaki kanıt
atıfı ve numarası değişmez; kanıt dizininde satır kalır (dosya boş, Maskeleme `kontrol bekliyor`),
teslim çıktısında ve özetinde (`kontrol_bekliyor`, `kontrol_uyarisi`) açık uyarı: "maskelenecek yeri
var, kontrol bekliyor: N dosya"; `EKSIK.txt` listeler; hat aşaması insan bekler. Karar ya da maskeli
yükleme ve yeniden `bidr maskele` sonrası yeniden `bidr teslim`'de dosya girer. Eski "kısmen maskeli
kopya pakete girer" davranışı kalktı. Maskeleme hiç çalıştırılmadıysa özgün dosyalar girer
(Maskeleme `yapılmadı`; hat uyarır).

### Redaksiyon doğrulaması

Son adım (PDF/PyMuPDF ve görseller): maskeli çıktıda her kapatılan bölgenin kutusunun altında
çıkarılabilir metin ya da görüntü verisi kalmadığı denetlenir. PDF'te kutunun içinde merkezi kalan
kelimeler çıkarılır (yer tutucular ve `geri_basilan` yazısı dışında harf/rakam kalmamalı); kutuyla
kesişen her gömülü görüntünün pikselleri açılır, kutunun görüntüdeki karşılığı tek renkli olmalı
(redaksiyon pikselleri boyar; yalnız üstüne çizilmiş kutu bunu geçemez). Görselde kutu karanlık
olmalı. Başarısızsa dosya `tamam` sayılmaz (`basarisiz`, kayıtta `redaksiyon_dogrulama`).

### Önbellek ve hız

Çalışma alanında içerik adresli SQLite önbellek (`.cache/maske.sqlite`; `--onbellek-yok` ile
kapatılır). Anahtar içeriğin sha256'sı + işi etkileyen her şeydir; dosya adı/zaman girmez:

- `ocr`: sayfa görüntüsü (PNG) sha256 + tesseract sürümü + dil + psm + görüntü boyutu → kelimeler;
- `donusum`: eski biçimli dosya sha256 + çevirici ve sürümü → çevrilmiş dosya;
- `aday`: kaynak sha256 + kural sürümü (`KURAL_SURUM`) + maskeleme kodu parmak izi + kurallar (ad
  listesi yalnız özetiyle) + PDF motoru + o dosyanın insan kararları + model metni → kayıt + maskeli kopya.

Değişmeyen dosya yeniden işlenmez (`aday` isabeti; raporda `onbellek: true`, özette `onbellekten`).
Kural ya da karar değişince yalnız `aday` katmanı yeniden hesaplanır; sayfa görüntüleri aynı
kaldığından OCR yeniden çalışmaz. Kanıt modunda dosyalar varsayılan iki işçi süreçte işlenir
(`--is N`); tesseract tek iş parçacığıyla (`OMP_THREAD_LIMIT=1`) çalışır. Metin katmanının *varlığı*
değil *yeterliliği* ölçülür: tam sayfa görüntülü sayfada görüntünün üstünde yeterli metin katmanı
varsa (≥ 25 kelime, çoğu harf/rakam ağırlıklı, görüntü yüksekliğinin yarısına yayılmış: aranabilir
PDF) OCR yapılmaz; imza ve etiket alanı metin katmanı kelimeleriyle çözümlenir. Görsel dosyada
(fotoğraf) OCR hiç metin bulamazsa görüntü döndürülüp yeniden denenmez: görsel `okunamayan_sayfa`
bölgesi olur (onay bekler; "kişisel veri yok" sayılmaz).

Rapora bulunan değerlerin kendisi yazılmaz; yalnız tür ve sayı. Komut, yayımlanamaz dosya varsa
1, hata varsa 2 ile çıkar.

### Tespit edilenler

| tür | yer tutucu | kural |
|---|---|---|
| `tc_no` | `[TC_NO]` | 11 hane, ilk hane 0 değil, 10. ve 11. hane T.C. kimlik algoritmasını tutar |
| `iban` | `[IBAN]` | `TR` + 24 hane (boşluklu yazım dahil) |
| `eposta` | `[EPOSTA]` | ad@alan.uzantı |
| `telefon` | `[TELEFON]` | `+90`/`0090`/`0` önekli ya da alan kodu parantezli Türkiye numarası |
| `ogrenci_no` | `[OGRENCI_NO]` | yapılandırılabilir desenler; varsayılan: dört haneli yıl (19xx/20xx) önekli 9, 10 ya da 12 hane ve "öğrenci no: …" bağlamı (belge kimliği bağlamı hariç, yukarıda). 11 hane alınmaz (T.C. kimlik / 0'lı telefon uzunluğu); `90` önekli (telefon), IBAN parçası, `E-…`/`…-1` gibi kod parçaları alınmaz. Kurum profili (`bidr/data/institutions/<kurum>.yaml` `privacy.maskeleme.ogrenci_no_desenleri`; çalışma alanında `bidr.kurum`) kuruma özgü biçimi EKLER: ör. GTÜ'de iki haneli yıl önekli 12 hane |
| `etiket_alani` | `[KİŞİSEL VERİ]` | yalnız görüntü katmanı (taranmış sayfa, görsel): kişisel veri etiketinin alanı (aşağıda) |
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

### El yazısıyla doldurulmuş form alanları: `etiket_alani`

Taranmış başvuru formu/dilekçede kimlik no, telefon, e-posta, adres, doğum tarihi, öğrenci no çoğu
zaman EL YAZISIYLA doldurulur; OCR rakamları okuyamadığı için desen eşleşmez. Etiketler ise basılıdır
ve okunur. Kural (`bidr/mask/alan.py`): OCR'lanan sayfada kişisel veri etiketi bulunursa etiketin
alanı karartılır, içine `[KİŞİSEL VERİ]` yazılır; raporda `etiket_alani` (alan satırı başına) sayılır.

- **Etiketler**: *güçlü* (yalnız kişiye ait olabilir): T.C. kimlik no / pasaport no, öğrenci no /
  numarası, doğum tarihi / yeri, ev / ikamet / yazışma / tebligat adresi, GSM / cep telefonu;
  *zayıf* (kurum iletişim bilgisinde de geçer): telefon / tel, e-posta, adres. **Ad/soyad etiketi
  yoktur**: kişi adları maskelenmez.
- **Yalnız görüntü katmanında** (taranmış / tam sayfa görüntülü PDF sayfası, görsel): metin katmanlı
  sayfadaki basılı etiket ve değeri zaten desenlerle yakalanır; web sayfası altlığı, bölüm telefonu
  gibi kurumsal satırlar bu kurala girmez.
- **Yanlış pozitif sınırları**: etiket `:` ile (aynı ya da sonraki belirteçte) ya da satır/tablo
  hücresi başında olmalı (akan metindeki "öğrenci numarası …" alınmaz); zayıf etiket sayfanın üst
  (%7, antet) ve alt (%8, altlık) bandında alınmaz ve ancak sayfada güçlü bir etiket varsa (form
  bağlamı) ya da alandaki mürekkebin çoğu güvenle okunan basılı metin değilse (el yazısı) alınır;
  zaten kapatılmış alan alınmaz. OCR yazım hataları ("Kim1ik N0", "Kimllk", "Te1efon") etikete
  düzeltilir (harf içi rakam karışıklığı, ≥ 5 harfli anahtar sözcükte tek harf hatası).
- **Alan geometrisi** (sabit "etiketin sağı" varsayımı yok): sayfanın basılı iskeleti çıkarılır
  (noktalı kılavuz, alt çizgi, kutucuk/tarak dizisi, tablo çizgileri; eğik taramada da) ve etiketin
  dört yönünde aday aranır: sağ (kılavuz/çizgi/tarak, komşu hücre, el yazısı mürekkebi), alt (altındaki
  sahipsiz kılavuz/tarak, alttaki hücre), üst (çizginin altındaki "(T.C. Kimlik No)" açıklaması), sol.
  En yakın alan seçilir; puanı yakın ikinci yön de bölge olur (boşsa `onay_bekliyor`). Alan bir
  sonraki etikete (`:` ile biten basılı belirteç, iki basılı form sözcüğü, açıklama), tablo
  çizgisine ya da çizgi sonuna kadar kapatılır; **kılavuzlu alan boş görünse de kapatılır** (kaçırmak
  pahalı). Başka etiketin kılavuzu (aynı bantta hemen solunda biten etiket) alt/üst aday olmaz. Adres
  alanı bir-iki satır (ya da sahipsiz kılavuz satırı) aşağı uzar. Güçlü etiket var ama alan
  bulunamıyorsa bölge `onay_bekliyor` olur.
- **Rakam dizisi** (`rakam_dizisi`): etiket okunmasa da benzer yükseklikte, aynı tabanda yan yana
  10-13 el yazısı bileşen (form çizgileri ve güvenle okunan harfli basılı kelimeler hariç) adaydır;
  11 (kimlik) ya da 12 (öğrenci no) bileşen yalnız güveni artırır. Kişisel veri etiketi yakınındaysa
  kapatılır, değilse `onay_bekliyor`; kişisel olmayan etiketin (ör. "Bölümü:") değeri sayılmaz. OCR'ın
  bileşenleri rakam okuması da okuyamaması da adayı düşürmez.
- **Form şablon belleği** (`sablon`, `bidr/mask/sablon.py`, çalışma alanında
  `maske-sablonlari.json`): aynı formun kopyaları basılı iskelet parmak iziyle (güvenle okunan harf
  belirteçleri, dosyada kısa özet olarak; çizgi düzeni; el yazısı hariç) tanınır. İnsanın bir
  kopyada kapattığı bölgeler (kararlar dosyasında `kapat`) şablona kaydedilir ve parmak izi eşleşen
  sayfalara hizalanarak (ortak tek belirteçlerden ölçek/öteleme/küçük dönme; aykırı ayıklama) uygulanır.
  Hizalama güvenilmezse (az çapa, artık hata > 0,5 yazı yüksekliği, dönme > 6°, çizgiler örtüşmüyor)
  otomatik kapatılmaz, `onay_bekliyor` olur.
- Bölgeler (`el_yazisi_bolgeleri`): `tur: el_yazisi_alan`, `kaynak: etiket_alani | rakam_dizisi |
  sablon`, `karar`, `neden`, `guven`, kutu PDF puanı (bölge sözleşmesi). Raster hattı
  (`find_fields`) yalnız `kapatildi` alanları karartır.
- **İkinci OCR geçişi**: tesseract'ın varsayılan sayfa bölmesi el yazısıyla karışık form satırlarını
  ya da transkript sütununu bütünüyle atlayabilir; sayfada etiket ya da kişisel belge ipucu
  (öğrenci, kimlik, başvuru, form, transkript …) varsa ve ilk geçiş (psm 3) zayıfsa — 60'tan az
  güvenilir kelime ya da harf ağırlıklı ortalama güven 80'in altında — seyrek metin kipiyle (psm 11)
  ikinci geçiş yapılır, yeni etiketler eklenir (sayfa başına ~2-3 sn). İlk geçiş güçlüyse ikinci geçiş
  yapılmaz.
- Kapatma `privacy.maskeleme.etiket_alani: false` ile kapatılabilir (varsayılan açık).

**Modelin okuma metniyle el yazısı denetimi**: çalışma alanı biliniyorsa (`-w`; kaynak modunda
`--kaynak … -w WS` ile, kaynak daha önce okunmuşsa) dosyanın modelce okunmuş metni
(`text/<doc_id>.txt`; kanıt modunda `evidence-index.csv`, kaynak modunda `inventory.csv` ile
eşlenir; sayfalar form feed ile ayrılır) aynı desenlerle taranır. Bir sayfada kimlik no, telefon,
e-posta, öğrenci no ya da IBAN varken maskeleme o sayfada o türden daha azını kapattıysa (değer de
etiket de el yazısı; OCR ikisini de okuyamadı) dosya `basarisiz` olur ve kayıtta
`el_yazisi_elle: ["s.2: kimlik no, e-posta"]`, nedeninde "elle bakılmalı: el yazısı kişisel veri
kapatılamadı (…)" yazar. Değer rapora yazılmaz; yalnız tür ve sayfa. Etiket alanı kapsamı türüne
göre sayılır (telefon etiketinin alanı telefonu kapatmış sayılır). Sayfa sayısı uyuşmuyorsa denetim
yapılmaz (uyarı); sayfasız biçimlerde (metin, docx …) ve pypdf motorunda belge bütünü karşılaştırılır.

**Taranamadı**: metin katmanı olmayan bir sayfa/görsel OCR'dan geçemezse — tesseract ya da dil
verisi yok, araç hatası, ya da mürekkepli sayfada güvenilir kelime çok az / ortalama güven < 50
(el yazısı, fotoğraf, kötü tarama) — dosya `taranamadi` olur; asla `tamam` sayılmaz. Boş sayfa
taranamadı sayılmaz.

### İmza

**Yapısal kapatma (`bidr/mask/yapi.py`; PDF sayfaları ve görsel dosyalar).** İlke: imzayı tam
bulmak yerine imzanın bulunabileceği alanı kapatmak. Bölgeler `bolgeler` listesine (kaynak kuralıyla)
yazılır; aşağıdaki eski kurallar (1-8) DOCX'e gömülü görsellerde sürer.

- `imza_sutunu`: tablo ızgarası taramada morfolojik yatay/dikey çizgi tespitiyle, metin katmanlı
  PDF'te ayrıca vektör çizimlerden çıkarılır. Başlık hücresi "İmza"/"İmzası" olan sütunun bütün veri
  hücreleri kapatılır; ad/unvan sütunları açık kalır. Başlık yalnız ilk sayfadaysa sütun düzeni
  belge boyunca hatırlanır; sütun sınırları tutan (±0,12 inç) devam sayfası tablosunda aynı sütun
  kapatılır. Izgaralı sayfada OCR çizgileri silinmiş kopyada yapılır (tesseract ızgaralı sayfada
  hücre yazılarını çoğu zaman atlıyordu), başlık satırı gerekirse ayrıca hedefli OCR'lanır.
- `imza_tasmasi`: sütundan/banttan dışarı taşan, ona bitişik mürekkep (altında kalan kelime
  kutuları dahil) ayrı kutuyla kapatılır.
- `imza_blogu`: tablo dışındaki unvan/rol satırının (ve hemen üstündeki ad satırının) üstündeki bant
  (önceki basılı satıra kadar, en çok 0,9 inç) mürekkep içeriyorsa kapatılır; `imza_etiketi`:
  "İmza:" etiketinin sağı/altı ve etiket/unvan yakınındaki imza benzeri küme.
- `gomulu_gorsel`: metin katmanlı sayfada etiket/unvan yakınındaki ya da imza sütunundaki imza
  boyutlu gömülü görüntü kutusu doğrudan kapatılır; sayfanın alt yarısındaki etiketsiz, tek renkli,
  seyrek görüntü onay bekler. Belgede "e-imza / güvenli elektronik imza" ibaresi varsa metin katmanlı
  sayfada etiketsiz görüntü/mürekkep araması yapılmaz (`birakildi`).
- **Metinle örtüşen imza**: kapatılır; altındaki ad/unvan PDF metin katmanından okunuyorsa kutunun
  üstüne "Ad Soyad – Unvan [imza gizlendi]" geri basılır (`geri_basilan`, `kapatildi`); yalnız
  OCR'dan okunuyorsa geri basılmaz, kutu kapalı kalır ve bölge "geri basma gerekli mi" diye
  `onay_bekliyor` olur (`kapali: true`). Renk ayırma yalnız yapısal imza bölgesinde ve imza boyunda
  yapılır (kutu dışındaki mavi el yazısı içerik metni yamalanmaz); siyah kapatma her zaman en son ve
  en üsttedir: siyahla çoğunlukla örtüşen yama basılmaz, kalanı kırpılır. Mavi/mor mürekkep siyah metinden HSV ile
  ayrılabiliyorsa (yamada imza benzeri mürekkep ve renkli piksel kalmadığı doğrulanır) yalnız
  mürekkep pikselleri beyazlatılır, alttaki metin kalır (`kapatildi`; PDF'te alttaki görüntü
  pikselleri beyaz karartmayla silinip yama basılır).
- **Yanlış alarm süzgeçleri** (yalnız etiketsiz adaylar; etiket/sütun yakınındaki aday süzülmez —
  her sayfaya yapıştırılmış imza da tekrarlar): sayfanın üst %20'si (antet/logo); dairesel
  kaşe/mühür (kareye yakın kutu, mürekkebin çoğu çember bandında, köşeler boş; mühre değen imza
  kutuyu kareden çıkarır, süzülmez); aynı konumda başka sayfalarda (değiştirilmemiş kopyadan) ya da
  çağıran `TekrarBellegi` verirse başka dosyalarda görülen öğe; tamamen basılı sayfada (≥120
  okunur kelime, etiket yok) eşiği (renkli ya da ≥1,2×0,4 inç) geçemeyen tek aday; 0,5 inçten küçük
  tik/çentik; satır düzeni tutarlı el yazısı paragrafı. Süzülenler `birakildi` + neden; kalan etiketsiz
  aday `onay_bekliyor` (kapatılmaz; inceleme kopyasında çerçeveli). Fotoğraf/afişte (renk çeşitliliği
  yüksek, az metin) ya da sayfada 10'dan çok aday varsa adaylar tek sayfa onayına (`etiketsiz_sayfa`)
  toplanır. Unvan satırı bandı tablo içinde (yalnız yatay çizgili karar tablosu dahil), akan metinde ve
  fotoğrafta çalışmaz. Web çıktısında (üst/alt bilgide URL + tarih) mürekkep yalnız gömülü görüntülerde
  aranır; gömülü görüntü yalnız imza oranında, tek renkli ve gerçek "İmza" etiketine yakınsa alınır.
- **Yön**: taranmış sayfanın yönü (tesseract OSD) imza/alan çözümlemesinden önce düzeltilir; kutular
  özgün sayfa koordinatına çevrilir.
- **Rakam dizisi** (`rakam_dizisi`): metin katmanlı ya da güvenle OCR'lanan basılı sayfada aranmaz;
  bileşenlerinin çoğu harf okunan dizi düşer. Güçlü kişisel veri etiketi bulunup alanı bulunamazsa
  etiketin sağındaki satır bandı yine kapatılır.

Eski kurallar (gömülü DOCX görselleri; model kullanılmaz; basit görüntü işleme, Pillow):

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

7. **Basılı metinle örtüşen aday karartılmaz.** Her kapatma adayı için içine alanının ≥%40'ı düşen
   okunabilir basılı kelime (güven ≥ 70 ya da metin satırı boyunda düşük güvenli, en az üç harf/rakam;
   imza/unvan etiketleri hariç) sayılır ve adaydaki mürekkebin bu kelime kutularına düşen payı
   ölçülür. **3'ten çok kelime** ya da **en az 2 kelime ve mürekkebin ≥%50'si kelimelerde** ise aday
   kapatılmaz (belge bilgisi kaybolmasın; imza açık kalır): sayfa/görsel **"imza: elle bakılmalı —
   basılı metinle örtüşen imza kapatılmadı"** olur (durum `basarisiz`, raporda `imza_metin_elle`).
8. **Yeniden OCR doğrulaması**: OCR varsa kapatılacak her kutu karartılmadan önce ~300 ppi
   kırpıntı olarak yeniden OCR'lanır (sayfa OCR'ı imza vuruşunun altındaki yazıyı düşük güvenle
   okuyup saymamış olabilir); kutuda 3'ten çok okunabilir kelime çıkarsa kutu yine kapatılmaz,
   elle bakılmalı olur.

Eşikler gerçek bölüm verisinde ölçüldü (imzalı 150 belge, aday kırpıntılarına tek tek bakılarak):
gerçek imza kutuları altındaki ad/unvanla 0-2 (seyrek 3) kelime örtüşür ve mürekkeplerinin çoğu
kelime dışındadır; yanlış adaylar (renkli basılı yazı — ders bilgi formları, duyurular —, toplantı
başlık bloğu, ekran görüntüsü) 3'ten çok kelimeyle ya da mürekkebinin çoğu kelimelerde olarak
örtüşür. Birden çok imzanın birleştiği ve unvan sütununu da kaplayan kutu da bu yüzden kapatılmaz,
elle bakılmalı olur. Logo gibi metinsiz yanlış adaylar kapatılmaya devam eder.

Yanlış karartma ölçüsü: kapatılan imza kutularıyla örtüşen okunabilir kelime sayısı raporda
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

Sınırlar: OCR el yazısını okuyamaz (değer yalnız basılı etiketinin alanı olarak kapatılır;
etiketi de el yazısı olan alan kalır, modelin okuma metni varsa dosya elle bakılmalı olur; el
yazısı sayfa `taranamadi` ya da imza şüphesiyle elle bakılmalı olabilir); imza tespiti sezgiseldir (etiketsiz imza ve imzaya benzeyen çizimler elle
bakılmalı); PyMuPDF yoksa taranmış sayfadaki bulgu ve imza kapatılamaz (yeniden tarama
yakalar, dosya `basarisiz`) ve bölge listesi üretilmez (yalnız elle maskeleme); DOCX/XLSX/HTML/metin
dosyalarında bölge yoktur (sorun kalırsa elle maskeleme); ad tespiti yalnız listedeki adları bulur;
kural tabanlı tespit her biçimi yakalamaz. Yayından önce onay bekleyen bölgeler (`bidr maskele
bolgeler`) insan tarafından karara bağlanmalıdır.

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
                              # (varsayılanların yerine geçer; kurum profilinin desenleri her durumda eklenir)
    etiket_alani: true        # taranmış sayfada kişisel veri etiketinin alanı [KİŞİSEL VERİ] (varsayılan açık)
    ad_listesi: personel.txt  # ya da liste; .txt satır başına bir ad, .csv ilk sütun; göreli yol ws'e göre
    yerel_model: null         # genişletme noktası (bu sürümde uygulanmaz)
```

Ad listesi gerçek kişi verisidir: çalışma klasöründe tutulur, repoya girmez.
