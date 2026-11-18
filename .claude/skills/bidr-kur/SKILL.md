---
name: bidr-kur
description: bidr'i kurar ve bir BİDR çalışma alanı açar - Python ortamı, bidr komutu, OCR araçları, kurulum soruları kullanıcının dilinde, answers.yaml, `bidr init`. Tetik - "kur", "kurulum", "bidr'i kur", "yeni dönem", "yeni birim", "çalışma alanı aç", "kaynak klasör değişti"; `bidr next` kurulum aşamasını gösteriyorsa. Kullanma - kurulu alanda raporu sürdürmek (bidr-rapor), hakem soruları (bidr-hakem).
---

# bidr-kur

Kullanıcıyla onun dilinde konuş; komutlar, dosya adları ve YAML anahtarları olduğu gibi kalır.
Cevap uydurma: bilmediğin her alanı kullanıcıya sor.

## 1. bidr kurulu mu?

- Çalışma alanında `AGENTS.md` varsa oradaki "bidr komutu" yolunu kullan; kurulum tamamdır, 2. adıma geç.
- Repo içindeysen: `.venv/bin/bidr --help` (Windows: `.venv\Scripts\bidr --help`) çalışıyorsa kurulu.
- Değilse repo kökünde (Python ≥ 3.11):
  - `uv venv && uv pip install -e '.[dev]'`
  - uv yoksa: `python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'`
    (Windows: `py -3 -m venv .venv` ve `.venv\Scripts\pip install -e .[dev]`)
  - Denetim: `.venv/bin/bidr --help` ve `.venv/bin/pytest -q` geçmeli.

### Sandbox'lı ajan ortamı

Yalnız çalışma klasörüne yazabildiğin bir sandbox'taysan (ev dizinindeki paket önbelleği ve
`/tmp` kapalı) önbelleği ve geçici klasörü repo içindeki git dışı `_tmp/`'ye al; aynı
`TMPDIR`'i sonraki bütün `bidr` komutlarında da kullan (OCR'da `tesseract` geçici PNG'yi
`TMPDIR` altında açar; açamazsa hata mesajı bunu söyler):

```
mkdir -p _tmp/uv-cache _tmp/pip-cache _tmp/tmp
export UV_CACHE_DIR="$PWD/_tmp/uv-cache" PIP_CACHE_DIR="$PWD/_tmp/pip-cache" TMPDIR="$PWD/_tmp/tmp"
uv venv && uv pip install -e '.[dev]'
```

uv yoksa `python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'` aynı ortam
değişkenleriyle. Windows PowerShell: `$env:UV_CACHE_DIR="$PWD\_tmp\uv-cache"` vb.
Sandbox ağ erişimini kapatıyorsa kurulumu kullanıcıdan izin isteyerek ya da sandbox dışında yaptır.

## 2. Dış araçlar (metin çıkarma ve OCR)

`pdftotext`, `pdftoppm` (poppler) ve `tesseract` + Türkçe dil verisi (`tesseract --list-langs`
çıktısında `tur`). Eksikse kullanıcıya söyle ve kurulum komutunu öner; sistem paketini
kullanıcının onayı olmadan kurma:
macOS `brew install poppler tesseract tesseract-lang` · Debian/Ubuntu
`sudo apt install poppler-utils tesseract-ocr tesseract-ocr-tur` · Windows: poppler ve
Tesseract (UB Mannheim) kurulup PATH'e eklenir. OCR olmadan taranmış belgeler
`needs_ocr` kalır ve değerlendirilemez (`bidr status` uyarır).

## 3. Kurulum soruları

Şablonu al: `bidr init --sablon`. Soruları sırayla, kullanıcının dilinde, varsayılanıyla sor:

| # | Soru | Anahtar | Not |
|---|---|---|---|
| 1 | Birimin belge klasörü nerede? | `kaynak` | Salt okunur kalacağını söyle; hiçbir dosyası değişmez |
| 2 | Çalışma alanı nerede olsun? | `calisma_alani` | Kaynağın ve bidr reposunun DIŞINDA; gerçek veri burada durur |
| 3 | Birimin adı? | `birim` | ör. "Fizik Bölümü" |
| 4 | Birim türü? | `profil` | şablondaki seçenekler; bölüm için `akademik_bolum` |
| 5 | Rapor dönemi (yıl)? | `donem` | ör. 2025 |
| 6 | Kurum? | `kurum` | şablondaki seçenekler; bilinmiyorsa `null` |
| 7 | Kaynakta geçen yılın BİDR raporu ve ölçüt adlı kanıt klasörleri var mı? | `gecmis_etiket` | evet ise model kararları onlarla karşılaştırılır ve hakem soruları çıkar |
| 8 | (7 evetse) Etiketlerdeki birim adı | `etiket_birim` | boş = `birim` |
| 9 | Model işini kim yapacak? | `ajan` | kendi adın, ör. `claude-code:sonnet`; kayda geçer |

Cevapları `<calisma_alani>/answers.yaml` dosyasına yaz (klasörü aç), kullanıcıya göster,
sonra: `bidr init --answers <calisma_alani>/answers.yaml`.

### Boş rapor şablonu (FR-0833)

Rapor (`bidr render`) boş FR-0833 .docx şablonunu ister (`config.yaml` `rapor.sablon`). Kurulumda edin:
1. Kurum profilinde (`bidr/data/institutions/<kurum>.yaml`) `sablon_adresi` doluysa şablonu o
   adresten çalışma alanına indir (ör. `<calisma_alani>/sablon/FR-0833.docx`), dosyanın gerçekten
   .docx olduğunu denetle ve kullanıcıya hangi adresten indirdiğini söyle.
2. Adres boşsa ya da indirme başarısızsa kullanıcıdan boş şablon dosyasını iste (kurumun kalite
   birimi sayfasından ya da bölüm sekreterliğinden edinilir). Adres ya da dosya uydurma.
3. Dosya yolunu `config.yaml` `rapor.sablon`'a yazdır (kullanıcıya göstererek). Şablon şimdi
   yoksa sorun değil: render'a kadar `bidr next` yeniden ister.

## 4. Çıkış kodları

- `0`: kuruldu. Çıktıda yazan `config.yaml`, `AGENTS.md`, `CLAUDE.md` ve skill kopyaları oluşur.
- `2`: geçersiz cevap. Hataları kullanıcıya göster, yalnız ilgili soruyu yeniden sor.
- `5`: çalışma alanı zaten farklı cevaplarla kurulu. Farkı kullanıcıya göster; yalnız kullanıcı
  açıkça "evet" derse `--yes` ile yeniden çalıştır. `--yes`'i kendi kararınla ekleme.

## 5. İsteğe bağlı: Claude Code hook'u

Kullanıcı isterse `bidr init --answers ... --claude-hook`: çalışma alanında
`.claude/settings.json`'a oturum başında `bidr status --kisa` özetini bağlama koyan bir hook
yazar. Yalnız Claude Code'da çalışır; doğruluk ona dayanmaz (kapılar kodda). Var olan
`settings.json`'a dokunmaz, eklenecek parçayı yazdırır.

## 6. Bitti

`bidr next -w <calisma_alani>` çalıştır ve kullanıcıya sıradaki adımı söyle. Kullanıcı raporla
devam etmek isterse skill `bidr-rapor`.

- Birim adı karar paketlerine girer ve belgenin bu birime ait olup olmadığı buna göre değerlendirilir: `config.yaml` birim alanına birimin resmî adını yazdırın (ör. "Matematik Bölümü").
