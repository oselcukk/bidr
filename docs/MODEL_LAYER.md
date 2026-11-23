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
  işaretlenir. Yalnız tablo başlığı/sütun adlarından oluşan alıntı ("Komisyon Adı … Görev
  Tanımı …", içerik satırı yok) reddedilir (`alinti_tablo_basligi`; GECERSIZ.md'de gerekçesiyle).
- **Komisyon/görev tanımı tabloları.** Metinde "Komisyon Adı … Görev Tanımı" başlığı olan belgede
  (bölüm kurul ve komisyon listesi, görev dağılımı) komisyon görev alanları ölçütlere eşlenir
  (`bidr/candidates/komisyon.py`: değişim programları → A.5.1, danışmanlık/kariyer → B.3.2,
  kalite kurulu → A.1.4, muafiyet/intibak → B.2.3 …) ve kaba seçimden sonra adaylara eklenir
  (kayıtta `adaylar_komisyon`); aday tavanı 6 yerine `KOMISYON_MAX_ADAY` (8). Uzayan aday listesi
  belge metni payından düşer (en az 4000 karakter), istem bütçesi korunur. Öteki belgelerin aday
  listesi değişmez; ikinci arama bu eklemeyi yapmaz.
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
- **Faaliyet kaydı (classify_fine v9).** İnce karar çıktısında isteğe bağlı belge düzeyi
  `faaliyet`: `{"ad": 2-6 sözcük, "tarih": "YYYY-AA-GG" | "YYYY-AA" | null, "asama": duyuru |
  plan | gerceklesme | katilim | degerlendirme | iyilestirme | duzenleme | diger}`; belge bir
  toplantı/etkinliğe ait değilse `null`. İstem kuralı 11 kısa ve örneklidir ("duyuru
  gerçekleşmenin kanıtı değildir"). Kayıt: `ince.faaliyet` (ad boşlukça düzeltilir); cevapta
  alan yoksa kayda girmez. Mükerrer üye temsilcinin faaliyetini devralır (`rep_output`).
  **Sürüm 8 → 9:** mevcut mekanizma değişmedi: v8 kayıtları "eski_surum" görünür, `bidr decide
  prepare --stage fine` maliyet özeti verir, yeniden paketleme yalnız `--yes` ile; onaylanmazsa
  eski kararlar geçerli kalır ve faaliyetsiz sayılır. İstem boyut sınırı (`test_prompt_size_budget`,
  < 8000 token) için ince karar metin bütçesi `FINE_CHARS` 8000 → 7300 karakter.

  `bidr faaliyet -w WS [--out DOSYA] [--json]` (`bidr/faaliyet/`, belirleyici, model yok):
  `decisions.jsonl`'deki faaliyet alanlarını faaliyet kayıtlarında toplar → `faaliyetler.json`
  (`ozet` + `faaliyetler[]`: `id` F001…, `ad`, `adlar`, `tarih` (olay günü), `tarih_araligi`,
  `durum` gerceklesme_kanitli | gerceklesme_dolayli | gerceklesme_kanitsiz, `yalniz_duyuru`,
  `asamalar` {aşama: [doc_id]}, `halkalar` (PUKÖ), `eksik` ("gerceklesme yok", "katilim yok",
  "degerlendirme yok"; değerlendirme varsa "iyilestirme yok"), `belgeler` (doc_id, aşama, karar,
  kanıt adı, birim ilişkisi, kabul edilmiş eşleşmeler), `notlar`) ve özet tablo basar.
  Gruplama (`group.py`): ad benzerliği (Türkçe katlama, ek duyarlı sözcük öneki, Dice ≥ 0.6;
  addaki toplantı no./yıl farklıysa ayrı) + tarih yakınlığı (çapa aşamalar gerceklesme/katilim
  ±3 gün; öteki aşamalar olay gününe göre aşamaya özgü pencerede: duyuru 45 gün önce–3 gün
  sonra, değerlendirme 90 gün, iyileştirme 365 gün sonrasına kadar; en yakın faaliyet).
  Tarihsiz belge adı benzer tek faaliyete bağlanır, birden çok aday varsa ayrı kalır ve
  işaretlenir. `baska_birim` belgeler alınmaz. **Hat aşaması `faaliyet`** (D; karar_ince'den
  sonra, audit'ten önce; `checks.faaliyet_tamam`: `faaliyetler.json` bugünkü decisions.jsonl'den
  yeniden hesaplananla aynı değilse bekliyor — ikinci arama ya da yeniden karar eskitir; yalnız
  duyurulu faaliyet uyarıdır). Write paketine ölçütün kanıtlarının faaliyet özeti girer
  (docs/REPORT_LAYER.md "write"); audit kullanımı tasarımı docs/AUDIT.md "Faaliyet kayıtları".
- **Araç güncellemesinde yeniden işleme** (bitmiş raporu yeni sürümle güncelleme). Paket
  `girdi_sha` (görev girdisi başına sha) taşır, apply onu kayda (`kaba`/`ince.girdi_sha`) ve
  `ince.denetim_surumu`'nu (`DENETIM_SURUMU`, kod denetimi kuralları) yazar. `prepare` işlenmiş
  belgenin eskimesini ayırır (`staleness`): `eski_surum` (görev sürümü; toptan, `--yes`),
  `girdi_degisti` (belgeye özgü girdi — `DOC_KEYS`: aday listesi ve ölçüt blokları, belge
  bilgisi, metin payı, birim — değişti: onaysız yeniden paketlenir), `kural_degisti` (yalnız
  ortak kural metni — istem şablonu, kanıt ilkeleri — değişti: kayıt geçerli, status'ta tek satır
  "istem sürümü eski"; toptan yeniden işleme yalnız `--yes` ile), `istem_degisti` (ayrım
  yapılamadı: girdi izi yok ve eski paket yok; `--yes` ile). `girdi_sha`'sız eski kayıtta ayrım
  kayıttaki istemle üretilmiş eski paketten yapılır: yeni belge girdilerinin her biri eski
  istemde birebir geçiyor ve paketin aday/metin özeti aynıysa yalnız kural değişmiştir (ajanın
  güncelleme denemesindeki `ince_etki.py`'nin genel hâli); ilk karşılaştırmada kayda girdi izi
  yazılır. `apply` yalnız istemi, cevabı ya da denetim sürümü değişen belgeyi yeniden işler
  (öteki `degismedi`); yeniden işlenen kayıtta ikinci arama eşleşmeleri korunur (aşağıda).
  Yardımcı dosyalar paket klasörünün dışında: `work/_durum/<aşama>-yeniden.json` (onay bekleyen
  ve `kural_degisti` belgeler + son tam prepare'in `parmak`'ı: görev dosyaları, istemi kuran kod,
  ölçüt/profil verisi, text/, documents.jsonl, candidates.jsonl, insan birim kararları, birim
  bilgisi). `_pkg_paths` `_` ile başlayan dosyaları ve eski sürümün `YENIDEN.json`'ını paket
  saymaz (prepare onu siler); `doc_id`'siz JSON `paket_degil` sayılır, apply çökmez.
  `checks.karar_tamam`: ajan kipi kayıtları varken parmak yoksa ya da değiştiyse aşama bitmemiş
  ("eski olabilir: araç sürümü ya da girdiler değişti") ve `bidr next` onaysız prepare'i ister;
  prepare etkiyi hesaplar (model çağrısı yok). identify kayıtlarına `arac_surumu` yazılır
  (`identify.pipeline.ARAC_SURUMU`); `identify_tamam` eski sürümlü ya da dönemi config'inkiyle
  aynı olmayan (`--period`'suz çalışmış) kaydı bitmiş saymaz.
- **Bölümün belge notu** (`belge-notlari.yaml`, `bidr/notlar.py`). Kullanıcı (panelde Belgeler sayfası;
  işleyici yazar) bir belge hakkında kısa not bırakabilir: `{surum: 1, notlar: [{dosya, sha256, metin, kim,
  tarih}]}`; `dosya` (inventory `rel_path`) ya da `sha256` ile `doc_id`'ye eşlenir, kopya satırları dahil
  (aynı içeriğin notları birleşir). Not bir İPUCU ve bağlamdır: yalnız not metni (kim/tarih/yol değil)
  belgeye özgü girdinin sonuna "Bölümün belge hakkındaki notu (kullanıcı beyanı): <<<…>>>" bloğuyla ve
  ilkesiyle eklenir — kaba/ince karar ve kanıt adında `belge_bilgisi`'ne, betimlemede görüntü listesine.
  Notsuz belgenin istemi birebir aynı kalır (eskime yok). Görsel okuma (transcribe) notu görmez (birebir
  yazıya geçirme yanlılaşmasın). Alıntı yalnız belgeden: `verify_quote` belge metnine karşı denetler, not
  `text/`'e girmez; betimleme nottan 5+ sözcüklük dizi aktaramaz (`note_leaks`, görünen yazıda geçen hariç;
  geçersiz cevap). Not ile belge çelişirse model kararı belgeden verir ve genel gerekçeyi `[not uyuşmuyor]`
  ile başlatır; kayıtta `kaba`/`ince.belge_notu` (notun parmak izi) ve `not_uyusmuyor`. Audit satırına
  `belge_notu` (bilgi; "yükleyenin notu dikkate alındı", sade "Neden"de "Yükleyenin notu dikkate alındı.";
  verilmiş kararı yeniden baktırmaz) ve çelişkide `not_uyusmuyor` (Dikkat: "Belgeyi yükleyenin notu ile
  belge içeriği uyuşmuyor…", yeniden baktırır) işaretleri. **Not değişince:** `belge_bilgisi` belgeye özgü
  girdi olduğundan `staleness` → `girdi_degisti` (kayıttaki `belge_notu` şimdikiyle aynı değilse devralınan ve
  sağlayıcı kayıtlarında da), belge onaysız yeniden paketlenir; not dosyası `input_fingerprint`'e girer
  (`bidr next` prepare'i ister). Betimleme (`describe.jsonl` `belge_notu`, `settled`) ve model kanıt adı
  (`kanit-adlari.jsonl` `belge_notu`, `name.note_stale`, `checks.name_tamam`) de notu değişen belgeyi yeniden
  paketler. Notlu belge mükerrer metin grubuna girmez (kararı kendi notuyla verilir).
- **Kopya grubu (decide'dan önce).** Metni aynı/çok yakın belgeler (`dedup.find_groups`) ve aynı kâğıdın
  ayrı taramaları (`dedup.scan_copy_pairs`, yöntem `tarama_kopyasi`: OCR metninde iki yönlü kapsama
  ≥ `SCAN_TEXT_MIN` 0,8 + tarih/tür/kimlik uyumu, VE sayfa görüntüsü pHash'i eşit sayfa sayısında sayfa başına
  ≤ `imghash.MAX_BITS` 32/143 bit) tek gruptur: kaba ve ince kararda yalnız temsilci paketlenir, üyeler
  `mukerrer.durum: devralindi` + `kopyasi: <temsilci>` ile kararı devralır. Tarama kopyasında OCR farkı
  temsilcinin alıntısını üyede bozsa da grup bölünmez (`mukerrer.alinti_tutmayan`). Tarihi/revizyonu farklı
  sürüm kopya değildir. Görüntü karmaları `work/_durum/goruntu-karma.json`'da (yalnız karma; görüntü
  saklanmaz). İnceleme tablosunda grup tek satırdır (temsilci; gizli "kopyaları" sütunu ve sade "Dikkat" hücresinde
  "Kopyaları: …"); satır kararı dosyalamada bütün gruba uygulanır (tek kanıt numarası).
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

## İkinci arama (K12)

İlk geçişte (`bidr candidates`) belge sorgu, ölçütler derlemdir: belge başına ilk k ölçüt ince
karara gider. Seyrek ölçütün uygun belgesi o belgenin ilk k'sına giremezse hiç sorulmaz. İkinci
arama, audit sonrasında kanıtsız ya da zayıf kalan alt ölçütler için yönü çevirir: ölçüt sorgu,
işlenmiş arşivin bütün belgeleri derlem. Kod: `bidr/candidates/ikinci.py` (zayıf ölçüt + arama),
`bidr/candidates/synonyms.py` (eşanlamlı grupları), `bidr/candidates/arama.py` (paket + ekleme),
`bidr/evaluate/ikinci_arama.py` (ölçüm). Yeni bağımlılık yok.

- **Zayıf ölçüt** (`weak_criteria`, profil içinde): `kanitsiz` (sayılan eşleşme yok), `dusuk_od`
  (önerilen OD ≤ `--od-esik`, vars. 2), `yalniz_kurum_geneli` (audit `kurum_geneli_yalniz`),
  `bolum_kaniti_yok` (kabul edilmiş eşleşmelerin hiçbiri birimin kendi belgesinden değil; kurum
  geneli kuralı audit'inkiyle aynı, insan birim kararı öncelikli). OD ve sayılan eşleşme
  `audit-olcutler.json`'dan; yoksa `decisions.jsonl`'den yaklaşık (`kaynak: decisions`).
  `--olcut` ile zayıflık hesaplanmadan elle verilir.
- **Arama**: sorgu = ölçüt metni (başlık ×3, üst ölçüt, tanım, rubrik, örnek kanıt maddeleri =
  yuvalar) + eşanlamlı genişletme (metinde bir grubun üyesi öbek olarak geçerse ötekilerin
  sözcükleri sayı 1 ile eklenir; 5 harflik kök çakışması tetiklemez). Puan = sorgu BM25'i (arşiv
  belgeleri derlem, IDF arşivden) + ilk geçişin yuva sinyali; ikisi belgeler arasında en
  yükseğe bölünür. knn/tür/öncel kullanılmaz. **Girdi değildir:** `labels.jsonl` (geçmiş rapor
  etiketleri ve kanıt adları), yol, dosya adı, `kanit-adlari.jsonl`.
- **Seçim**: ince kararı sonuçlanmış, ölçüt için ilk geçişte aday olmamış (kayıttaki `adaylar`,
  kaba `secilen` ve eşleşmelerde yok) belgeler; öz-referans türü, başka birime ait sayılan ve
  kararı devralan mükerrer belge seçilmez. Ölçüt başına en iyi `--n` (vars. 5) belge; belge
  başına en çok `--max-aday` (vars. 6) ölçüt. Çoklu ölçüt korunur: bir belgeye seçilen bütün
  zayıf ölçütler aynı pakette sorulur.
- **Çapraz yol** (vars. açık; `--no-capraz` kapatır): bir belge bir ölçüte atanınca başka
  ölçüte de kanıt olabileceği arşiv sıralamasında çoğu zaman görünmez (bütçe cümlesi etkinlik
  raporunun içinde, bölüm izleme tablosu başka ölçüte atanmış; gerçek veride hedef belge arşivde
  76–145. sırada). Havuz: ince kararı sonuçlanmış, hariç/devralan olmayan, birimin kendi belgesi
  sayılan (`ikinci.unit_own`, `_unit_stats` ile aynı kural) ve en az bir ölçütte ilk geçişte
  kabul edilmiş, insanın reddetmediği (`review-decisions.jsonl`) belgeler. İkinci aramanın kendi
  kabulleri havuz nedeni sayılmaz (zincirleme yok). Belgeye sorulan: ilk geçişte o belgeyle
  eşleşmesi olmayan (kabul ya da ret) zayıf ölçütler; ölçüt ilk geçişin adayı olup ince karar
  eşleşme vermediyse de sorulur (dar aday listesi, ölçüte odaklı kesit). Belge başına en çok
  `--max-aday` ölçüt, sıra ölçüt sorgusunun belgeye puanı. Arşiv yolunun aynı belgeye seçtikleriyle
  tek pakette birleşir; satırın `kaynak`'ı `arsiv`/`capraz`, çapraz satırda `kabul_olcutler`
  (kayıtta `ikinci_arama.olcutler.<ölçüt>.kaynak`). Ölçüm (2026-11-20, model çağrısı yok):
  Matematik havuz 29 belge → 29 ek paket, 174 çift (arşiv yolu 32 paket); Kimya havuz 105 → 105
  ek paket (biri arşiv yoluyla ortak), 628 çift (arşiv yolu 27).
- **Paket** (`bidr arama prepare -w WS`; yönetilen çalışma alanında aşama kapısı: audit bitmeden
  çıkış 3 ve `bidr next` önerisi, paket yazılmaz): `work/ikinci_arama/<doc_id>.json`, `classify_fine`
  görevi, `decide prepare`'inkiyle aynı biçim ve istem (`fine_inputs`; aday listesi yalnız
  ikinci aramanın ölçütleri). `meta.ikinci_arama`: ölçüt başına puan, arşivdeki sıra, zayıflık
  nedenleri ve ilk geçişin parmak izi (`ince_parmak`).
- **Ekleme** (`bidr arama apply -w WS --model M`): şema + `check_matches` (aday dışı ölçüt,
  yuva, birebir alıntı, OD, birim). Birim ilişkisi kayıttan (ilk geçiş; insan kararı öncelikli),
  modelin ikinci cevabı `ikinci_arama.son.birim_iliskisi_model`'de. Eşleşmeler kaydın
  `eslesmeler`ine EKLENİR, `ikinci_arama: true`, `ikinci_arama_paket` (istem sha) ve
  `denetim.isaret`te `ikinci_arama` ile (review.xlsx "işaretler" sütununda görünür); `olcutler`,
  `karar`, `reddedilen_eslesme` yeniden hesaplanır; `ince`, `adaylar`, `kaba` değişmez (decide'ın
  eskime denetimi etkilenmez). Kayıt bölümü `ikinci_arama`: `olcutler` (bakılan ölçüt → puan,
  sıra, nedenler, istem/cevap sha, eşleşme/kabul sayısı), `ince_parmak`, `eslesme`, `son`.
  İlk geçiş yeniden karara bağlanırsa (`decide apply`) ikinci arama eşleşmeleri düşmez:
  `carry_second_search` onları yeni birim ilişkisiyle aynı kod denetiminden geçirip kayda geri
  ekler, `ince_parmak` ve `eslesme` güncellenir (ilk geçiş aynı ölçüt/yuvayı kabul ettiyse ikinci
  aramanınki düşer: çift sayım yok). Cevabı kayıtta olan paket parmak izi eski olsa da işlenmiş
  sayılır (`arama.merged`); işlenmemiş cevabın paketi ilk geçiş değiştiyse `eski_paket` olur.
- **Ölçüm** (`bidr arama olcum -w WS [--json]`): ölçüt başına bakılan çift, önerilen eşleşme,
  kod kabul/red (nedenleriyle), insan kabul/ret/incelenmedi (`review-decisions.jsonl`, satır
  `<doc_id>|<yuva>`) ve isabet. İnsanın kabul ettiği = ilk geçişin kaçırdığı kanıt; reddettiği
  = ikinci aramanın eklediği yanlış.
- **Hat aşaması `ikinci_arama`** (isteğe bağlı M; önkoşul `audit`, `file`'ın önkoşulu; komutlar
  `arama prepare` / ajan / `arama apply`). `checks.ikinci_arama_tamam`: config.yaml
  `rapor.ikinci_arama: false` → `atlandi` (kullanıcının kararı; status'ta görünür); `arama prepare`
  hiç çalışmadıysa (README yok) bekliyor; paket eski (görev sürümü ya da ilk geçişin parmak izi
  değişti) → prepare; cevapsız/geçersiz → ajan; cevabı kayda işlenmemiş (ölçüt başına
  `istem_sha`/`cevap_sha`) → apply; hepsi işlendiyse bitti. Apply decisions.jsonl'i değiştirir:
  audit tablosu eskir (`kararlar_sha`), `audit_tamam` nedeni ikinci aramanın eklediği kabul
  sayısını söyler; audit yeniden çalışır, insan yeni satırları inceler, sonra ikinci arama bitti
  olur (faaliyet kaydı da içerikle yeniden denetlenir). Hakem kuyruğu decisions.jsonl yalnız
  yeniden yazıldıysa (karşılaştırma ve sorular aynı) eskimez; ikinci arama etiketli bir belgeye
  kabul eklediyse eskir.

## Paralel model aşamaları (`bidr parcala`)

Model işi gerektiren aşamalarda cevapsız iş paketleri, paket sayısına göre artan sayıda ajana
**ayrık** listelerle bölünebilir. Kod: `bidr/pipeline/paralel.py`; aşama kararı `pipeline.yaml`
`paralel` alanında (`bolunebilir`, `gerekce`, `dizin`, `duzen` dosya|klasor, isteğe bağlı `anahtar`
deseni ve `grup: alt_bolum`). `load_spec` her M aşamasında bu alanı ister.

| Aşama | Bölünür | Bölme birimi | Gerekçe |
|---|---|---|---|
| transcribe, belirsiz_okuma | evet | belge (`<doc_id>/`) | paket tek belgenin sayfa görüntüleri |
| describe | evet | belge | betimleme belgeye özgü |
| karar_kaba | evet | belge | istem: tek belge + profilin ölçüt listesi |
| karar_ince | evet | belge | istem: tek belge + adayların rubriği; alıntı yalnız o belgeden |
| ikinci_arama | evet | belge | arşiv taraması (ölçüt başına belge seçimi) prepare'de kodla; paket tek belge + ona seçilen bütün zayıf ölçütler |
| name | evet | belge | ad belge başına; adlandırma kuralları her parçada aynı istemde |
| write | evet | alt bölüm (A.1, A.2 …) | paket tek ölçüt ve onun bütün kanıtları/faaliyet özeti (ölçütün zinciri bölünmez); aynı alt bölümün ölçütleri aynı faaliyeti farklı anlatmasın diye tek parçada |
| verify | evet | ölçüt | doğrulayıcı yazarın paketini görmez; parça ajanları da yazım ajanlarından ayrı ve taze |
| yonler (+ yönlerin doğrulaması) | hayır | — | en çok 4 alan paketi; maddeler alanın bütün doğrulanmış metinlerinden, alanlar arası denge ve tekrar raporun bütününde okunur |

**PUKÖ zinciri, faaliyet ve OD bölmeden etkilenmez.** Belgeler arası bağlantıyı hiçbir model
paketi kurmaz: `classify_coarse`/`classify_fine`/`name_evidence`/`transcribe`/`describe` istemlerinin
girdileri yalnız tek belgenindir (`belge_metni`, `belge_bilgisi`, aday ölçütler, birim). Faaliyet
kayıtları `bidr faaliyet` (`faaliyet/run.py`: yalnız `decisions.jsonl`), PUKÖ bağlantıları ve OD
`bidr audit` (`audit/puko.py` `build_links(docs, recs, …)`, `audit/run.py` `build`) içinde modelsiz,
bütün kararlar birlikte okunarak kurulur; apply bütün cevap dosyalarını kimin yazdığından bağımsız
işler. Ölçüt düzeyinde başka belgeleri gören tek model paketi `write_criterion`'dır ve ölçütün bütün
kanıtları tek pakettedir. `tests/test_paralel.py` aynı cevaplar üç parçaya (ve ters sırayla)
dağıtıldığında `decisions.jsonl`, `faaliyetler.json` ve `audit-olcutler.json`'un tek ajanlı koşuyla
birebir aynı olduğunu sınar.

**Parça sayısı.** `N = taban` (vars. 2; ≤ `esik` paket, vars. 20), sonra her `adim` (vars. 20) pakette
+1, en çok `azami` (vars. 20) ve paket (write'ta alt bölüm) sayısı. Varsayılanla
`N = min(20, n, 2 + (n-1)//20)`: 1 paket → 1, 2–20 → 2, 21–40 → 3, 41–60 → 4, …, 361+ → 20. Ayar önceliği: komut bayrağı
(`--taban/--esik/--adim/--azami`, `--parca` zorlar) > config.yaml `rapor.paralel_{taban,esik,adim,azami}` >
varsayılan; tavanı `BIDR_PARALEL_AZAMI` (kota) da düşürür; hiçbiri 20'yi aşamaz. Bölme dengeli:
ağırlık paketin bayt boyutu (klasör düzeninde sayfa görüntüleri), en ağır paket/grup en hafif parçaya
(LPT); sonuç belirlenimci.

**Komutlar.** `bidr next` model aşamasında `Paralel:` satırı yazar (bölünmez + gerekçe | gerekmez |
"N ajanla paralel yapılabilir" + komutlar); `next --json` `sonraki.paralel` (`bolunebilir`,
`parca_sayisi`, `bekleyen`, `komut`, `denetim`). Bekleyen paketleri aşamanın tamamlanma denetimi
söyler (`Check.bekleyen`: cevapsız ∪ geçersiz); yönetilmeyen çalışma alanında klasör taranır.
- `bidr parcala -w WS [aşama] [--json]` → `work/<klasör>/_parca/<k>.txt` (başlık yorum satırları +
  satır başına WS'ye göreli paket yolu) ve `_parca/parcalar.json` (parçalar, paket izi, bölmeden önce
  var olan liste dışı cevapların sha'sı; kopyaları `_parca/yedek/`). `_` ile başlayan ad hiçbir
  aşamada paket sayılmaz.
- Parça ajanının talimatı tek ajanınkiyle aynıdır (README + paketin `istem`i); fark yalnız listedir:
  kendi listesindeki `.out.json`'lar, apply yok, alt ajan yok.
- `bidr parca-denetle -w WS [aşama] [--kuru]` ve **her apply'ın başında** (`apply_oncesi`;
  transcribe, describe, decide, arama, name, write, verify): hiçbir listede olmayan pakete yazılmış
  cevap ya da bölmeden önce var olan liste dışı cevabın değişmesi/silinmesi ihlaldir; yazılan dosya
  `_parca/reddedilen/`'e taşınır, eskisi geri konur (çıkış 1). Paketler bölmeden sonra değiştiyse
  (yeniden prepare) bildirim eskidir ve yok sayılır. Hangi parçanın hangi dosyayı yazdığını dosya
  sistemi söylemez; panel işleyicisi bunu çağrı başına ayrıca denetler (bidr-panel docs/ISLEYICI.md).
