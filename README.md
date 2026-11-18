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
   2 turdan sonra kullanıcı karar verir) → render (`report.docx`, FR-0833 şablonu).

**Sandbox'lı ajan ortamı** (Codex, Claude Code sandbox gibi; yalnız çalışma klasörüne yazılabilir):
paket yöneticisi önbelleği ve geçici klasör çalışma klasörüne alınır, yoksa kurulum ya da OCR
(`tesseract` geçici PNG'yi `/tmp` altında açamaz) başarısız olur:

```
mkdir -p _tmp/uv-cache _tmp/pip-cache _tmp/tmp                 # _tmp/ git dışıdır
export UV_CACHE_DIR="$PWD/_tmp/uv-cache" PIP_CACHE_DIR="$PWD/_tmp/pip-cache" TMPDIR="$PWD/_tmp/tmp"
uv venv && uv pip install -e '.[dev]'                          # bidr komutlarını da aynı TMPDIR ile çalıştırın
```

**Boş FR-0833 şablonu** (`rapor.sablon`, render için gerekli): kurulumda kullanıcıdan istenir.
Kurum profili (`bidr/data/institutions/<kurum>.yaml`) `sablon_adresi` taşıyorsa ajan şablonu
oradan çalışma alanına indirir; adres boşsa (gtu profilinde şimdilik boş) kullanıcıya sorulur.

Önkoşulu bitmemiş aşamanın komutu çıkış kodu 3 ile durur. Çalışma alanı repo ve kaynak
klasör dışında olmalıdır; kaynak salt okunurdur.

Rapor ayarları `config.yaml`'ın `rapor:` bölümündedir (hepsi isteğe bağlı; ayrıntı
`docs/REPORT_LAYER.md`): `sablon` (boş FR-0833 .docx), `onceki_rapor` (geçen yılın raporu),
`kanit_kok_baglanti` (kanıt klasörünü yüklediğiniz kök adres), `yayin_alan_adlari`,
`yeniden_yazim_siniri`. Raporda kanıt adı tıklanabilir bağlantıdır: kamuya açık belge
yayımlandığı adrese (belge metnindeki web adresi ya da review.xlsx "bağlantı" sütunu),
yayımlanmamış belge kanıt klasöründeki yoluna bağlanır; bağlantısızlar gaps.md'de listelenir.
Yükleme sizin işinizdir; bidr hiçbir yere dosya göndermez.

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
