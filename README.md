# bidr

Birim İç Değerlendirme Raporu (BİDR) hazırlığı için açık kaynak araç: bir birimin
belge klasörünü tarar, belgeleri YÖKAK ölçütlerine kanıt olarak eşler, kılavuza
uygun dosyalar ve ölçüt açıklamalarını yalnız onaylı kanıtlardan yazar. Model
bağımsızdır: yerel model, Claude veya bir API ile çalışır.

Durum: geliştirme (v0.1). Ayrıntı: `docs/ARCHITECTURE.md`.

## Kullanım

En kolay yol, kendi kodlama ajanınızı (Claude Code, Codex, opencode, Kiro, Hermes…) bu
klasörde açıp "bidr'i kur", sonra çalışma alanında "raporu hazırla" demektir. Ajan
`AGENTS.md` ve `.agents/skills/` altındaki skill'lerle (`bidr-kur`, `bidr-rapor`,
`bidr-hakem`) ilerler. Model işini ajan kendisi yapar; ücretli API çağrılmaz.

Elle:

```
uv venv && uv pip install -e '.[dev]'            # Python ≥ 3.11; OCR için poppler + tesseract (tur)
bidr init --sablon > ~/bidr-calisma/birim2025/answers.yaml   # doldurun
bidr init --answers ~/bidr-calisma/birim2025/answers.yaml    # config.yaml, AGENTS.md, skill'ler
bidr next   -w ~/bidr-calisma/birim2025          # sıradaki tam komut + tamamlanma şartı
bidr status -w ~/bidr-calisma/birim2025          # bütün aşamalar: bitti / bekliyor / engelli
```

Aşamalar (`bidr/data/pipeline.yaml`): kurulum → ingest → (geçmiş etiketler) → identify →
candidates → kaba karar → ince karar → hakem → inceleme, dosyalama, yazım, doğrulama,
render (son beşi henüz yok). Karar aşamalarında `bidr decide prepare` iş paketleri yazar,
ajan her paket için `<doc_id>.out.json` yazar, `bidr decide apply` cevapları şema ve
birebir alıntı denetiminden geçirir. Önkoşulu bitmemiş aşamanın komutu çıkış kodu 3 ile
durur. Çalışma alanı repo ve kaynak klasör dışında olmalıdır; kaynak salt okunurdur.

İsteğe bağlı: `bidr init ... --claude-hook` Claude Code'da oturum başında
`bidr status --kisa` özetini bağlama koyar. Yalnız Claude Code'a özgüdür; kapılar ondan
bağımsızdır.

Gebze Teknik Üniversitesi Matematik Bölümü'nde geliştirilmektedir; kurumun resmî
aracı değildir.

Lisans: MIT.
