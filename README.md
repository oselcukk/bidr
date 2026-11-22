# bidr

Birim İç Değerlendirme Raporu (BİDR) hazırlığı için açık kaynak araç: bir birimin
belge klasörünü tarar, belgeleri YÖKAK ölçütlerine kanıt olarak eşler, kılavuza
uygun dosyalar ve ölçüt açıklamalarını yalnız onaylı kanıtlardan yazar. Model
bağımsızdır: yerel model, Claude veya bir API ile çalışır.

Durum: geliştirme; hat kurulumdan rapora kadar uygulanmış. Ayrıntı: `docs/ARCHITECTURE.md`.

## Kullanım

En kolay yol, kendi kodlama ajanınızı (Claude Code, Codex, opencode, Kiro, Hermes…) bu
klasörde açıp "bidr'i kur", sonra çalışma alanında "raporu hazırla" demektir. Ajan
`AGENTS.md` ve `.agents/skills/` altındaki skill'lerle (`bidr-kur`, `bidr-rapor`,
`bidr-hakem`) ilerler ve her adımda `bidr next`'in söylediğini yapar.

**Ajan modu, ücretli API yok.** Model işi (görsel okuma, karar, kanıt adı, metin yazımı,
doğrulama) iş paketleriyle yürür: `bidr <aşama> prepare` paketleri yazar, ajan her paket için
`*.out.json` yazar, `bidr <aşama> apply` cevabı şemaya ve kod denetimine (birebir alıntı, atıf,
OD aşımı) sokar. Rapor işinde `bidr decide run` / `bidr llm` kullanılmaz.

Kurulumdan rapora kısa akış:

```
uv venv && uv pip install -e '.[dev]'            # Python ≥ 3.11; OCR için poppler + tesseract (tur)
bidr init --sablon > ~/bidr-calisma/birim2025/answers.yaml   # doldurun
bidr init --answers ~/bidr-calisma/birim2025/answers.yaml    # config.yaml, AGENTS.md, skill'ler
bidr next   -w ~/bidr-calisma/birim2025          # sıradaki tam komut + tamamlanma şartı
bidr status -w ~/bidr-calisma/birim2025          # bütün aşamalar: bitti / bekliyor / engelli
```

Aşamalar (`bidr/data/pipeline.yaml`, ayrıntı `docs/ARCHITECTURE.md`):

1. **Belgeler:** ingest (metin, OCR) → transcribe / describe (taranmış sayfa ve fotoğraflar,
   ajan görerek) → identify (tür, tarih, dönem) → candidates.
2. **Eşleme:** kaba ve ince karar (ajan; her eşleşme belgeden birebir alıntıyla) → hakem
   (geçmiş yıl etiketiyle farklar, kullanıcı karar verir) → name (kanıt adı önerisi).
3. **İnceleme:** audit → `review.xlsx` (her satıra kullanıcı KARAR yazar: kabul/ret/duzelt;
   kanıt adı ve bağlantı düzeltilebilir), `gaps.md` (eksik kanıtlar), ölçüt OD önerisi.
   Kullanıcı açıkça "karar vermeyeceğim, sen devam et" derse ajan kararları kullanıcı yetkisiyle
   verir: her satırın NOT'una "ajan (kullanıcı yetkisiyle)" yazar, güveni düşük eşleşmeleri ret
   sayar, rapor TASLAK kalır (bkz. `bidr-rapor` skill'i).
4. **Rapor:** file (kanıt klasörü `evidence/`, `evidence-index.csv`) → write (ölçüt metni) →
   verify (kod + metni yazmamış, taze bir ajan; reddedilen metin gerekçesiyle yeniden yazılır,
   2 turdan sonra kullanıcı karar verir) → yonler (alan düzeyi Güçlü / Gelişmeye Açık Yönler;
   yalnız doğrulanmış metin ve audit bulgusundan, aynı bağımsız doğrulamayla) → render
   (`report.docx`, FR-0833 şablonu; kapak hazırlayanları, ölçüt kapsamı) → denetle (kılavuz
   biçim denetimi) → teslim (dekanlığa teslim paketi; aşağıda).

**Sandbox'lı ajan ortamı** (Codex, Claude Code sandbox gibi; yalnız çalışma klasörüne yazılabilir,
`export X=…` ya da `X=… komut` biçimi izin ister): hazır sarmalayıcıyı kullanın. Geçici klasörü
(`TMPDIR`; OCR'da `tesseract` geçici PNG'yi `/tmp` altında açamaz) ve paket önbelleklerini repo
içindeki git dışı `_tmp/`'ye alıp komutu çalıştırır; ortam değişkenini elle vermek gerekmez:

```
sh tools/sandbox.sh kur                    # .venv + bidr (uv yoksa python3 -m venv + pip)
sh tools/sandbox.sh pytest -q              # test paketi (TMPDIR repo içindeyken de geçer)
sh tools/sandbox.sh next -w <çalışma alanı>   # her bidr komutu: sh tools/sandbox.sh <argümanlar>
```

Sarmalayıcıyla çalışan `bidr next` ve çalışma alanının `AGENTS.md`'si sonraki komutları da
sarmalayıcıyla yazar. Çalışma alanı yine repo dışında olmalıdır; `_tmp/`'ye yalnız geçici dosya
düşer. Windows PowerShell'de aynı oturumda bir kez:
`$env:TMPDIR="$PWD\_tmp\tmp"; $env:UV_CACHE_DIR="$PWD\_tmp\uv-cache"; $env:PIP_CACHE_DIR="$PWD\_tmp\pip-cache"`.

**Boş FR-0833 şablonu** (`rapor.sablon`, render için gerekli): kurulumda kullanıcıdan istenir ve
yolu answers.yaml `sablon` alanına (tam yol) yazılır; `bidr init` dosyanın .docx olduğunu
denetleyip `config.yaml` `rapor.sablon`'a yazar (config elle düzenlenmez). Kurum profili
(`bidr/data/institutions/<kurum>.yaml`) `sablon_adresi` taşıyorsa ajan şablonu oradan çalışma
alanına indirir; adres boşsa (gtu profilinde şimdilik boş) kullanıcıya sorulur. Şablon kurulumda
yoksa `sablon: null` kalır; render'dan önce `bidr next` yeniden ister.

Çıkış kodları: 0 tamam · 2 eksik/yanlış argüman · 3 önkoşul aşaması bitmemiş · 5 `init`
kullanıcı onayı ister; `apply` komutlarında 1 = geçersiz ya da şüpheli cevap uygulanmadı
(`work/<aşama>/GECERSIZ.md`), `denetle`'de 1 = kritik bulgu, `teslim`'de 1 = eksik paket (ayrıntı `docs/ARCHITECTURE.md`).
Çalışma alanı repo ve kaynak klasör dışında olmalıdır; kaynak salt okunurdur.

**Alt ajanlarla çalışmak.** Kaba/ince karar gibi binlerce paketli aşamalarda paketler alt
ajanlara gruplanır. Claude Code aynı anda en çok 20 alt ajan çalıştırır: 20'lik dalgalar halinde
başlatın. Paketlerin istem başı (kurallar, ölçüt kataloğu) ve sonu (şema) birebir aynıdır; her
alt ajana bu ortak kısmı bir kez, belgeye özgü kısımları bir grup dosyasında verin. Cevaplar yine
paket başına `*.out.json`; ayrıntı `docs/ARCHITECTURE.md` "Ajan modunda iş paketlerini dağıtmak".

Rapor ayarları `config.yaml`'ın `rapor:` bölümündedir (hepsi isteğe bağlı; ayrıntı
`docs/REPORT_LAYER.md`): `sablon` (boş FR-0833 .docx; answers.yaml `sablon` ile `bidr init`
yazar), `hazirlayanlar` (kapak; answers.yaml ile), `onceki_rapor` (geçen yılın raporu),
`kanit_kok_baglanti` (kanıt klasörünü yüklediğiniz kök adres), `yayin_alan_adlari`,
`yeniden_yazim_siniri`, `teslim` (aşağıda).

**Teslim modu** (`config.yaml` `rapor.teslim`; varsayılan `dekanlik`):

- `dekanlik` (2025 raporu): birim kanıtlara bağlantı vermez; rapor ve kanıt dosyaları dekanlığa
  teslim edilir, yüklemeyi dekanlık yapar. Bağlantısız kanıt yalnız bilgidir (`bidr denetle`
  "yayıma hazır"ı engellemez). Kaydedilmiş web sayfası kanıtının (.html) satırında raporda ad
  (bağlantılı) ve özgün adres birlikte görünür: `[2-OD2]. Ad (https://…)`. Adres kanıt dizininden
  ya da sayfanın kendi kaydından (canonical, og:url, "saved from" yorumu) okunur; bulunamazsa
  uydurulmaz. Son adım `bidr teslim -w <çalışma alanı>`: `teslim/` klasörü ve `teslim.zip` —
  `report.docx`, `kanitlar/A/A.1/A.1.1/[1-OD3]. Ad.pdf` düzeninde kanıtlar, her web kanıtının
  yanında aynı adla "Kaynak: <URL> · Alınma (erişim) tarihi: <tarih>" damgalı PDF kopyası ve
  `kanit-dizini.xlsx`/`.csv` (ölçüt, kanıt no, OD, ad, paketteki dosya, özgün bağlantı, alınma
  tarihi, maskeleme). `bidr maskele` çalıştırıldıysa kanıtların maskeli kopyası girer; maskeleme kararı bekleyen kanıt (kararı verilmemiş öneri bölgesi, eksik kalan maskeleme) pakete o anki maskeli
  hâliyle girer (kesin kapatmalar uygulanmış, öneriler açık; maskelenemediyse özgünü, "maskelenmedi") ve
  konsolda, `MASKELEME-UYARI.txt`'de ve özetin `karar_bekleyen` alanında "maskeleme kararı bekleyen belgeler"
  diye listelenir; `--kararsizlari-disla` eski davranıştır (girmez) (maskeleme hiç
  yapılmadıysa özgün dosya, "yapılmadı"; ayrıntı `docs/PRIVACY.md`). Raporun kanıt listesindeki her satır paketteki bir dosyayla birebir eşleşir; eşleşmeyen
  ya da PDF'i üretilemeyen satır varsa paket `EKSIK.txt` ile yazılır ve çıkış kodu 1 olur.
  Web PDF'i için kurulu bir araç gerekir (ücretsiz): Google Chrome / Chromium / Edge (yolu
  standart değilse `BIDR_CHROME`) ya da `pip install weasyprint`; ikisi de yoksa komut kurulum
  notuyla durur. Tarih `--tarih YYYY-AA-GG` (vars. bugün); `--taslak` biçim denetimi geçmeden
  taslak paket üretir.
- `baglanti` (sonraki yıllar için): raporda kanıt adı tıklanabilir bağlantıdır: kamuya açık belge
  yayımlandığı adrese (belge metnindeki web adresi ya da review.xlsx "bağlantı" sütunu),
  yayımlanmamış belge `kanit_kok_baglanti` altındaki yoluna bağlanır; bağlantısızlar gaps.md'de
  listelenir ve `bidr denetle`'de uyarıdır. Yükleme sizin işinizdir; bidr hiçbir yere dosya göndermez.

**Kanıt ihtiyaç raporu** (`bidr ihtiyac`; hat aşaması değil, model yok, çalışma alanını salt
okur): belgeler parça parça gelirken neyin eksik olduğunu, hangi belgenin raporu en çok
güçlendireceğini (kanıtsız ölçüt > tek belgeyle OD artışı > geçen yılın karşılığı olmayan iyi
kanıtı) ve belgenin kimden isteneceğini `ihtiyac.xlsx` / `ihtiyac.md` olarak yazar; bölüme iletmek
için madde başına bir satırlık, düz Türkçe, madde madde somut belge listesi `istenen-kanitlar.xlsx`
(elle istekler `--istenecekler istenecekler.md` ile eklenir). Geçen yılın
iyi kanıtları önceki çalışma alanından referans sete çıkarılır ve bu yılki karşılıkları aranır;
`--ic-taslak` report.docx'in kopyasına "[EKSİK: …]" işaretleri koyar. Hatırlatma aracıdır, kesin
kontrol listesi değildir. Ayrıntı: `docs/IHTIYAC.md`.

```
bidr ihtiyac referans -w ~/bidr-calisma/birim2024 --out ~/bidr-calisma/referans-2024.json
bidr ihtiyac -w ~/bidr-calisma/birim2025 --referans ~/bidr-calisma/referans-2024.json \
    [--istenecekler istenecekler.md] [--ic-taslak]
```

**Kurala dönüşmüş kararlar veri dosyasıdır, kod değil.** Kanıt ilkeleri
(`bidr/data/profiles/kanit_ilkeleri.yaml`: ör. kurum geneli yönerge yalnız plan kanıtıdır),
dönem kuralı (`bidr/data/profiles/donem_kurali.yaml`: yapı belgesi yürürlükteyse, olay belgesi
rapor yılında gerçekleştiyse sayılır), birim profili, belge türü kataloğu
(`bidr/data/doc_types.yaml`) ve kurum form kodları (`bidr/data/institutions/`) başka kurum ya
da komisyon kararları için bu dosyalarla değiştirilebilir.

İsteğe bağlı: `bidr init ... --claude-hook` Claude Code'da oturum başında
`bidr status --kisa` özetini bağlama koyar. Yalnız Claude Code'a özgüdür; kapılar ondan
bağımsızdır.

Gebze Teknik Üniversitesi Matematik Bölümü'nde geliştirilmektedir; kurumun resmî
aracı değildir.

Lisans: MIT.
