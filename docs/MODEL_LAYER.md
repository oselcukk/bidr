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
- **Birim farkındalığı (classify_fine v8).** İnce karar istemine `{{birim}}` girer: çalışma
  alanı `config.yaml` `bidr.birim` ve `bidr.kurum` profilinin `ad`ı (`prompt.unit_info`;
  birim yoksa "belirtilmedi"). Kaba seçim istemi değişmez (aday seçimi; son söz ince kararın).
  Belge düzeyinde `birim_iliskisi` (eski `kurum_geneli` bool alanının yerine; şema dışı değer
  reddedilir):

  | Değer | Anlamı | Kod (`apply_fine` / `check_matches`) |
  |---|---|---|
  | `kendi` | birimin kendi belgesi | kural yok |
  | `ust_birim_bu_birim_hakkinda` | dekanlık/FYK/senato/rektörlüğün bu birimi konu alan kararı/yazısı; alıntı yalnız birimi konu alan maddeden (madde ilkesi) | OD tavanı yok; audit `senato_karari` tür tavanını da uygulamaz (yönetmelik/yönerge türü yine OD2) |
  | `fakulte_geneli` / `kurum_geneli` | bütün birimleri kapsayan düzenleme, politika ya da fakülte/kurum geneli faaliyet | her eşleşme OD2 (`uygulama_kaniti_eksik`); bölüm kırılımlı fakülte belgesinde birimin satırı alıntılanırsa model `kendi` der |
  | `baska_birim` | başka bölüm/birimin belgesi | her eşleşme reddedilir (`denetim.red: baska_birim`), karar `kanit_degil`, model gerekçesi `ince.gerekce`'de; GECERSIZ.md'ye girmez |
  | `belirsiz` | aitlik metinden anlaşılmıyor | kabul, `birim_aitligi_dogrulanmali` işareti; review.xlsx ve gaps.md'de listelenir |

  Kayıt: `ince.birim_iliskisi`, `ince.birim_iliskisi_kaynagi` (`model` | `eski_alan` |
  `varsayilan` | `insan`); `ince.kurum_geneli` (`model`/`tur`/`karar`) korunur, `model` artık
  `birim_iliskisi`'nden türer. **Geri uyumluluk:** alanı olmayan eski kayıt/cevap
  `kurum_geneli: true` ise `kurum_geneli`, değilse `kendi` sayılır (`belirsiz` değil;
  `record_unit_relation`). Sürüm 7 → 8: işlenmiş kayıtlar "eski_surum" olur; `bidr decide
  prepare --stage fine` özet verir, `--yes` ile birimli yeni istemle yeniden paketler.
  **İnsan kararı** (`birim-kararlari.jsonl`, review.xlsx birim sayfası, docs/AUDIT.md "Birim
  ilişkisini geri alma"): paketlenen belgenin `{{birim}}` girdisine "SABİT BİLGİ" satırı eklenir
  (`render_unit(info, sabit)`); `apply_fine` modelin cevabındaki alanı insan değerine zorlar
  (`birim_iliskisi_kaynagi: insan`, modelin değeri `birim_iliskisi_model`), kurallar insan
  değeriyle uygulanır.
- `bidr decide -w WS [--profile P] [--only-labeled] [--limit N]` →
  `decisions.jsonl`.
- `bidr compare-labels -w WS` → geçmiş etiketle karşılaştırma: aynı / ekliyor /
  itiraz; hakem kuyruğu (5'erli gruplar) `label-review.md` + `.jsonl`.

## Uygulama notları (şerit M)

- **Ajan modu (birincil), sağlayıcısız:** `render_task(task, inputs) ->
  {"task", "version", "prompt", "schema", "system"}` görevin doldurulmuş
  istemini verir (run_task'ın modele gönderdiğiyle birebir aynı; `system` hat
  modunun sistem istemidir, ajan yok sayabilir). `validate_output(task, raw)
  -> (çıktı | None, hatalar)` ham metni (çit/ön söz olabilir) ya da hazır
  dict/list'i aynı ayıklama + şema doğrulamasından geçirir. `run_task` (hat
  modu, gözetimsiz) bu ikisinin üstüne yalnız sağlayıcı çağrısı, yeniden
  deneme ve önbellek ekler. İş paketi dosya biçimi şerit R'nin
  (`bidr decide prepare/apply`).
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
  sürüm, sistem istemi, tam istem, model kimliği; yapılandırmada verilmişse
  üretim ayarları `temperature`, `max_tokens`, `params`). Yalnız şemadan geçen çıktı
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
  metindeki karakter aralığı. **Rakamlar birebir:** alıntıdaki sayılar (tarih,
  sayı, ders kodunun sayı kısmı) eşleşen aralıktakilerle aynı sırada aynı
  olmalı; değilse `ok=False`, puan en çok 0.5. Yalnız harf↔rakam karışması
  gevşer (O/o→0, l/I/ı/i→1; "2O24"="2024", "l5"="15"); ayırıcı farkı
  (12.03 / 12/03) serbest. Sözcük ortasındaki tek rakam ("bi1dirim") harf
  hatası sayılır. Bilinen sınır: harften sonra baştaki OCR'lı rakam
  ("MATl21" ↔ "MAT121") reddedilir (temkinli taraf).
- `bidr llm check -w WS [--role R] [--no-call]` her rol için yapılandırmayı
  ve küçük bir `_echo` çağrısıyla erişimi sınar. `bidr llm run TASK --input
  f.json -w WS [--role R] [--no-cache] [--refresh]`.
- `bidr/tasks/_echo/` yalnız sınama görevidir. `bidr/tasks/` paket değil, veri
  klasörü (`__init__.py` yok); görevler `load_task(ad)` ile bulunur.
