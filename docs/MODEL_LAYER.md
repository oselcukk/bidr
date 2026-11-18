# Model katmanı (v0.2) — arayüz sözleşmesi

Sahibi: şef. İki şerit bu sözleşmeye göre paralel yazar; değişiklik gerekirse
raporda istenir.

## `bidr.llm` (şerit M)

```python
from bidr.llm import ModelConfig, load_model_config, run_task, TaskResult, verify_quote

cfg: ModelConfig = load_model_config(workspace, role="fine")   # role: default|coarse|fine|verify
res: TaskResult = run_task("classify_fine", inputs={...}, model=cfg, cache_dir=ws/".cache/llm")
res.output      # dict, görevin output.schema.json'una göre doğrulanmış
res.model       # "claude-cli:opus" gibi
res.attempts, res.cached, res.raw
ok, score, span = verify_quote(quote, text)   # Türkçe katlama, boşluk, OCR toleransı
```

- Görev = `bidr/tasks/<ad>/` klasörü: `prompt.md` (`{{alan}}` yer tutucuları),
  `output.schema.json`, `task.yaml` (`version`, `description`).
- `run_task`: istemi doldurur, JSON ister, yanıttan JSON'u ayıklar, şemaya karşı
  doğrular; geçersizse hata mesajıyla en çok N kez yeniden sorar; önbellek
  anahtarı = sha256(görev sürümü + doldurulmuş istem + model kimliği).
- Sağlayıcılar: `openai-compatible` (Ollama, LM Studio, vLLM, OpenRouter),
  `anthropic` (HTTPS, `ANTHROPIC_API_KEY`), `claude-cli` (`claude -p`),
  `fake` (testler; sabit yanıtlar). Bağımlılıksız (urllib/subprocess).
- Çalışma klasöründe `config.yaml`:
  ```yaml
  models:
    default: {provider: claude-cli, model: sonnet}
    fine:    {provider: claude-cli, model: opus}
  privacy:
    no_remote: false   # true ise yalnız yerel (localhost) sağlayıcılar
  ```
- Anahtar/parola dosyaya yazılmaz; yalnız ortam değişkeni adı.

## Karar görevleri (şerit R)

- `classify_coarse`: belge metni (kısaltılmış) + profile göre süzülmüş alt
  ölçüt başlık ve kısa tanımları → ilgili alt ölçütler (gerekçeli) ya da
  `kanit_degil`.
- `classify_fine`: belge metni + aday ölçütlerin (kaba seçim ∪ belirleyici ilk k)
  rubrik ve kanıt yuvaları (PUKÖ etiketleriyle) → her uyan ölçüt için
  `{olcut, yuva, asama, od_onerisi, alinti, gerekce, guven}`. Alıntı belge
  metninden birebir olmalı; `verify_quote` ile denetlenir, tutmayan karar
  işaretlenir.
- `bidr decide -w WS [--profile P] [--only-labeled] [--limit N]` →
  `decisions.jsonl`.
- `bidr compare-labels -w WS` → geçmiş etiketle karşılaştırma: aynı / ekliyor /
  itiraz; hakem kuyruğu (5'erli gruplar) `label-review.md` + `.jsonl`.

## Uygulama notları (şerit M)

- Modüller: `config` (ModelConfig, config.yaml), `providers`, `tasks` (görev
  yükleme, `{{alan}}`/`{{a.b}}` tek geçişte doldurma; değerin içindeki `{{..}}`
  yeniden işlenmez), `jsonx` (ayıklama + şema), `runner` (run_task, önbellek),
  `quote` (verify_quote), `cli`.
- Kodda varsayılan sağlayıcı/model yok. `models.<rol>` yoksa `models.default`
  kullanılır; rol girdisi default'un üstüne yazılır (sağlayıcı değişirse
  default'un alanları taşınmaz). Model alanları: `provider, model, base_url,
  api_key_env, temperature, max_tokens, timeout, max_retries (vars. 2),
  retry_backoff, params` (HTTP gövdesine eklenir), `command, args,
  allow_api_key` (claude-cli), `responses` (fake). Bilinmeyen alan hatadır;
  `api_key:` gibi bir alan açıkça reddedilir.
- `privacy.no_remote: true`: yalnız `fake` ve host'u localhost/127.0.0.1/::1
  olan openai-compatible izinli; hem yüklemede hem `run_task`'ta denetlenir.
- İstem: görev istemine şema ve "yalnız JSON" talimatı eklenir
  (`task.yaml: include_schema: false` ile kapatılır); sistem istemi genel,
  `task.yaml: system:` ile değişir. JSON ayıklama: tüm metin → kod çitleri →
  metin içindeki ilk çözülebilen `{...}` (şema kökü dizi ise `[...]`).
  Geçersiz yanıtta hata listesi modele geri verilir (konuşma uzar; claude-cli'de
  tek isteme düzleştirilir). Geçici aktarım hataları (zaman aşımı, 429, 5xx)
  aynı deneme bütçesinden yeniden denenir. Başarısızlık: `TaskFailed`
  (`.raw`, `.errors`).
- Önbellek: `cache_dir/<ilk2>/<sha256>.json`; anahtar = sha256(görev adı,
  sürüm, sistem istemi, tam istem, model kimliği). Yalnız şemadan geçen çıktı
  yazılır; bozuk ya da şemaya artık uymayan kayıt yok sayılır. CLI önbelleği
  `<ws>/.cache/llm`. Model kimliği: `claude-cli:opus`,
  `openai-compatible:<model>@<host>`.
- **claude-cli faturası:** alt süreç ortamından `ANTHROPIC_API_KEY`,
  `ANTHROPIC_AUTH_TOKEN`, `CLAUDE_CODE_USE_BEDROCK/VERTEX/FOUNDRY`,
  `AWS_BEARER_TOKEN_BEDROCK` varsayılan olarak çıkarılır; CLI abonelik
  oturumunu kullanır, faturalı API'ye düşmez. Yalnız `allow_api_key: true`
  ile geçer. Çağrı: `claude -p --output-format json --no-session-persistence
  --tools "" --strict-mcp-config --disable-slash-commands --system-prompt S
  [--model M] [args...]`, istem stdin'den, boş geçici klasörde (proje
  CLAUDE.md'si yüklenmez). Kullanıcı düzeyi ayarlar/hook'lar yine yüklenebilir;
  gerekirse `args` ile `--setting-sources`/`--settings` verilir.
- `verify_quote(quote, text, threshold=0.9) -> QuoteMatch(ok, score, span)`:
  iki taraf iskelete indirgenir (NFKC, İ/I/ı/i → i, aksan atma, harf/rakam
  dışı her şey atılır → boşluk, satır sonu, tireyle bölünme, yumuşak tire
  etkisiz; OCR katlaması rn→m, vv→w, 0→o, 1→l). Tam eşleşme yoksa k-gram
  oylamasıyla aday pencereler + Sellers yaklaşık alt dizi eşlemesi;
  puan = 1 − düzenleme uzaklığı / alıntı iskeleti uzunluğu; `span` özgün
  metindeki karakter aralığı.
- `bidr llm check -w WS [--role R] [--no-call]` her rol için yapılandırmayı
  ve küçük bir `_echo` çağrısıyla erişimi sınar. `bidr llm run TASK --input
  f.json -w WS [--role R] [--no-cache] [--refresh]`.
- `bidr/tasks/_echo/` yalnız sınama görevidir. `bidr/tasks/` paket değil, veri
  klasörü (`__init__.py` yok); görevler `load_task(ad)` ile bulunur.
