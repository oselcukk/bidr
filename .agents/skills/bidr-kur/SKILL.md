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
`/tmp` kapalı; `export X=…` ya da `X=… komut` biçimi izin istiyor) kendi sarmalayıcını yazma,
repodaki hazır sarmalayıcıyı kullan. Geçici klasörü (`TMPDIR`; OCR'da `tesseract` geçici PNG'yi
orada açar) ve paket önbelleklerini repo içindeki git dışı `_tmp/`'ye alır:

```
sh tools/sandbox.sh kur          # .venv + bidr (uv yoksa python3 -m venv + pip)
sh tools/sandbox.sh pytest -q    # geçmeli; TMPDIR repo içindeyken de geçer
sh tools/sandbox.sh --help
```

Sonraki bütün bidr komutlarını `sh <repo>/tools/sandbox.sh <bidr argümanları>` ile çalıştır
(ör. `sh <repo>/tools/sandbox.sh init --answers …`). Böyle çalışan `bidr init` çalışma alanının
`AGENTS.md`'sine, `bidr next` de önerdiği komutlara aynı sarmalayıcıyı yazar. `_tmp/`'ye yalnız
geçici dosya düşer; çalışma alanı yine repo dışında olmalı (init reddeder).
Windows PowerShell: aynı oturumda bir kez `$env:TMPDIR="$PWD\_tmp\tmp"; $env:UV_CACHE_DIR="$PWD\_tmp\uv-cache"; $env:PIP_CACHE_DIR="$PWD\_tmp\pip-cache"`.
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
| 10 | Raporu kimler hazırlıyor? Her kişi için unvan, ad soyad, e-posta, görev | `hazirlayanlar` | Liste: `- {unvan: …, ad_soyad: …, eposta: …, gorev: …}`; raporun kapağına yazılır (`config.yaml` `rapor.hazirlayanlar`). Kişileri uydurma; kullanıcı henüz bilmiyorsa `[]` bırak (rapor TASLAK kalır), sonra aynı soruyla `bidr init` yeniden |
| 11 | Boş FR-0833 rapor şablonu nerede? | `sablon` | .docx'in tam yolu (`config.yaml` `rapor.sablon`'a init yazar); aşağıdaki "Boş rapor şablonu". Henüz yoksa `null` |

Cevapları `<calisma_alani>/answers.yaml` dosyasına yaz (klasörü aç), kullanıcıya göster,
sonra: `bidr init --answers <calisma_alani>/answers.yaml`.

### Boş rapor şablonu (FR-0833)

Rapor (`bidr render`) boş FR-0833 .docx şablonunu ister (`config.yaml` `rapor.sablon`). Kurulumda edin:
1. Kurum profilinde (`bidr/data/institutions/<kurum>.yaml`) `sablon_adresi` doluysa şablonu o
   adresten çalışma alanına indir (ör. `<calisma_alani>/sablon/FR-0833.docx`), dosyanın gerçekten
   .docx olduğunu denetle ve kullanıcıya hangi adresten indirdiğini söyle.
2. Adres boşsa ya da indirme başarısızsa kullanıcıdan boş şablon dosyasını iste (kurumun kalite
   birimi sayfasından ya da bölüm sekreterliğinden edinilir). Adres ya da dosya uydurma.
3. Dosyanın tam yolunu answers.yaml `sablon` alanına yaz (kullanıcıya göstererek) ve
   `bidr init --answers …` çalıştır: init dosyanın .docx olduğunu denetler ve `config.yaml`
   `rapor.sablon`'a o yazar. `config.yaml`'ı elle düzenleme. Şablon şimdi yoksa `sablon: null`
   bırak: render'a kadar `bidr next` yeniden ister; o zaman aynı yolla (answers.yaml + `bidr init`)
   eklenir. Var olan farklı bir şablonun yerine yenisi yazılacaksa init çıkış 5 verir (onay).

## 4. Çıkış kodları

- `0`: kuruldu. Çıktıda yazan `config.yaml`, `AGENTS.md`, `CLAUDE.md` ve skill kopyaları oluşur.
- `2`: geçersiz cevap. Hataları kullanıcıya göster, yalnız ilgili soruyu yeniden sor.
- `5`: çalışma alanı zaten farklı cevaplarla kurulu. Farkı kullanıcıya göster; yalnız kullanıcı
  açıkça "evet" derse `--yes` ile yeniden çalıştır. `--yes`'i kendi kararınla ekleme.

Kurulumdan sonraki bütün komutlarda aynı anlamlar: `3` önkoşul aşaması bitmemiş (kapı; atlatmaya
çalışma, `bidr next`'e dön); `apply` komutlarında `1` = en az bir cevap geçersiz ya da şüpheli
olduğu için uygulanmadı (çıktının son satırı sayıları, `work/<aşama>/GECERSIZ.md` nedenleri
söyler; cevapsız paket 1 yapmaz).

## 5. İsteğe bağlı: Claude Code hook'u

Kullanıcı isterse `bidr init --answers ... --claude-hook`: çalışma alanında
`.claude/settings.json`'a oturum başında `bidr status --kisa` özetini bağlama koyan bir hook
yazar. Yalnız Claude Code'da çalışır; doğruluk ona dayanmaz (kapılar kodda). Var olan
`settings.json`'a dokunmaz, eklenecek parçayı yazdırır.

## 6. Alt ajan kullanacaksan (rapor aşamalarına hazırlık)

Kurulumda kullanıcıya şunu söyle ve kendin de uygula: kaba/ince karar gibi aşamalarda binlerce
iş paketi olur ve alt ajanlara gruplanarak verilir.
- Claude Code aynı anda en çok 20 alt ajan çalıştırır (21.'si hata verir): 20'lik dalgalar halinde
  başlat, biten grubun yerine yenisini koy.
- Paketlerin istem başı (kurallar, ölçüt kataloğu, birim) ve sonu (şema) birebir aynıdır. Her alt
  ajana bu ortak kısmı bir kez (`ORTAK.md`), belgeye özgü kısımları bir grup dosyasında ver; önce
  ortak kısmın bütün paketlerde bayt bayt aynı olduğunu bir betikle doğrula. Paket dosyalarına
  dokunma; cevap yine paket başına `work/<aşama>/<id>.out.json`.
- Alt ajanın Bash'i olmayabilir; cevabı dosya okuma/yazma araçlarıyla yazması yeterli.
Ayrıntı: repo `docs/ARCHITECTURE.md` "Ajan modunda iş paketlerini dağıtmak".

## 7. Bitti

`bidr next -w <calisma_alani>` çalıştır ve kullanıcıya sıradaki adımı söyle. Kullanıcı raporla
devam etmek isterse skill `bidr-rapor`.

- Birim adı karar paketlerine girer ve belgenin bu birime ait olup olmadığı buna göre değerlendirilir: `config.yaml` birim alanına birimin resmî adını yazdırın (ör. "Matematik Bölümü").
