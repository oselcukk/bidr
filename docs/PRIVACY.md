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

## 1. Yayın kopyası maskeleme: `bidr maskele`

```
bidr maskele -w WS [--evidence DIR] [--out DIR] [--motor auto|pymupdf|pypdf] [--ad-listesi DOSYA]
```

`bidr file`'ın ürettiği `evidence/` klasörünün **maskeli sunum kopyasını** üretir. Asıl dosyalara
dokunulmaz.

Çıktılar (varsayılan olarak `evidence/`'in yanında):

| dosya | içerik |
|---|---|
| `evidence-maskeli/` | yayımlanabilir kopyalar (yalnız yeniden taramadan temiz geçenler) |
| `maskeleme-basarisiz/` | yeniden taramada sızıntı kalan kopyalar (elle inceleme için; **yayımlanmaz**) |
| `maskeleme-raporu.json` | dosya başına `bulunan` / `maskelenen` / `kalan` (tür → sayı), temizlenen üst veri, uyarılar, `yayimlanamaz` listesi |
| `evidence-index-maskeli.csv` | `evidence-index.csv` varsa: `ad`, `alintilar`, `kaynak` maskeli; `maskeleme` sütunu (tamam/basarisiz/desteklenmiyor/hata) |

Rapora bulunan değerlerin kendisi yazılmaz; yalnız tür ve sayı. Komut, yayımlanamaz dosya varsa
1, hata varsa 2 ile çıkar.

### Tespit edilenler

| tür | yer tutucu | kural |
|---|---|---|
| `tc_no` | `[TC_NO]` | 11 hane, ilk hane 0 değil, 10. ve 11. hane T.C. kimlik algoritmasını tutar |
| `iban` | `[IBAN]` | `TR` + 24 hane (boşluklu yazım dahil) |
| `eposta` | `[EPOSTA]` | ad@alan.uzantı |
| `telefon` | `[TELEFON]` | `+90`/`0090`/`0` önekli ya da alan kodu parantezli Türkiye numarası |
| `ogrenci_no` | `[OGRENCI_NO]` | yapılandırılabilir desenler; varsayılan: yıl önekli 9-10 hane ve "öğrenci no: …" bağlamı |
| `ad` | `[AD]` | yalnız yapılandırmadaki ad listesi (büyük/küçük harf ve ş/s, ı/i … duyarsız) |

İmza bölgesi bu sürümde **yalnız uyarıdır**: görsel içeren ve metninde "imza" geçen PDF sayfası
(DOCX/XLSX'te belge düzeyinde) raporda `imza_uyarisi` olarak listelenir; elle bakılmalıdır.

### Biçimler

- **PDF**: PyMuPDF kuruluysa (`pip install 'bidr[maske]'`) gerçek kaldırma (redaction): bulunan
  bölge içerikten ve metin katmanından silinir, siyah kutu konur. PyMuPDF yoksa pypdf ile **en iyi
  çaba**: içerik akışındaki metin işlemlerinin baytları değiştirilir; iki baytlı/özel kodlamalı
  yazı tiplerinde, iç içe biçim nesnelerinde ve görüntüdeki (taranmış) metinde işe yaramaz — bu
  durum raporda açık uyarıyla belirtilir ve yeniden tarama yakalar. İki yolda da belge üst verisi,
  XMP, gömülü ekler, yorum/açıklamalar, form alanları, yer imleri ve yapı ağacı temizlenir; yalnız
  sayfalar yeni dosyaya taşınır (silinen nesneler dosyada kalmaz). PyMuPDF'in lisansı AGPL'dir;
  bu yüzden zorunlu bağımlılık değil, isteğe bağlıdır.
- **DOCX**: paragraf metni koşulara bölünmüş olsa da birleşik taranır, değer yer tutucuyla
  değiştirilir (gövde, tablolar, üst/alt bilgi, dipnotlar). Yorumlar ve izlenen değişikliklerin
  silinen metni kaldırılır; çekirdek, özel ve uygulama üst verisi ile küçük resim temizlenir;
  görsel alternatif metni ve harici bağlantı adresleri (mailto) maskelenir.
- **XLSX**: hücre metinleri ve sayı olarak yazılmış numaralar (ör. TC hücresi), üst/alt bilgi ve
  sayfa adları maskelenir; hücre yorumları ve belge üst verisi silinir. openpyxl görselleri ve
  grafikleri korumaz (uyarı verilir).
- **Düz metin** (`.txt`, `.csv`, `.md`, `.tsv`): metin değiştirme.
- **Diğerleri** (görseller, sunumlar …): taranamaz; kopyalanmaz, `yayimlanamaz` listesine girer.

### Yeniden tarama

Her maskeli kopya, maskeleyiciden bağımsız bir okuyucuyla yeniden taranır (PDF: sayfa metni, üst
veri ve sıkıştırılmamış bütün akışlarda ham arama; DOCX/XLSX: paketteki bütün XML parçaları ve
öznitelikleri). Kişisel veri ya da temizlenmemiş üst veri/yorum/ek kalırsa kopya
"maskeleme başarısız" işaretlenir, `evidence-maskeli/`'den çıkarılıp `maskeleme-basarisiz/`'e
alınır ve yayımlanamaz listesine yazılır.

Sınırlar: OCR yok (taranmış sayfadaki yazı görülmez; metin katmanı varsa o taranır); ad tespiti
yalnız listedeki adları bulur; kural tabanlı tespit her biçimi yakalamaz. Yayından önce
`maskeleme-raporu.json` ve imza uyarıları insan tarafından gözden geçirilmelidir.

## 2. Model öncesi maskeleme: `privacy.mask_before_model`

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
