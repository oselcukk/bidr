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
