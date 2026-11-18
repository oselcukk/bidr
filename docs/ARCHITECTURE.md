# Mimari

`bidr`, bir birimin dağınık belge klasörünü tarar, her belgeyi YÖKAK ölçütlerine
(FR-0833 BİDR şablonu) kanıt olarak eşler, kılavuza uygun dosyalar ve ölçüt
açıklamalarını yalnız onaylı kanıtlardan yazar. Hangi modelin kullanılacağı
kullanıcıya kalır (yerel, Claude, API).

## İlkeler

1. **Dosya adı ve klasör girdi değildir.** Bölümlerde adlar güvenilmez. Belgenin
   ne olduğu yalnız içeriğinden anlaşılır. Var olan insan adlandırmaları
   (ör. `A.1.2 Bölüm Toplantı Tutanakları.pdf`) yalnız *etiket* olarak,
   değerlendirme için kullanılır; sınıflandırıcıya gösterilmez.
2. **Kaynak salt okunurdur.** Sistem kopya üretir; orijinali değiştirmez, taşımaz.
3. **İki katman.** Belirleyici katman (kod, model yok) ve model katmanı (görev
   sözleşmeleri: prompt + JSON şema). Her aşama bir dosya okur, bir dosya yazar;
   herhangi bir aşamada model değiştirilebilir.
4. **Modele güvenilmez.** Her iddia birebir alıntıyla gelir ve kodla denetlenir.
5. **Gerçek veri repoya girmez.** Testler sentetiktir.

## Aşamalar

Sözleşme: `bidr/data/pipeline.yaml` (önkoşul, girdi/çıktı, komut, tamamlanma denetimi, insan
onayı). Katman: D = belirleyici kod, M = model işi (ajan modu: `prepare` iş paketi yazar, ajan
`*.out.json` yazar, `apply` şema + kod denetimi), I = insan kararı. `bidr status` / `bidr next`
hepsini gösterir; önkoşulu bitmemiş aşamanın komutu çıkış kodu 3 ile durur.

| # | Aşama (id) | Katman | Önkoşul | Çıktı (çalışma alanında) |
|---|---|---|---|---|
| 0 | kurulum | I | — | `config.yaml` (`bidr:`), `AGENTS.md`, skill'ler |
| 1 | ingest | D (+OCR) | kurulum | `inventory.csv`, `text/<doc_id>.txt`, `arsiv/` (arşiv/e-posta üyeleri), gaps.md ingest bölümü |
| 2 | transcribe (isteğe bağlı) | M | ingest | düşük kaliteli taramaların görsel okuması → `text/` |
| 3 | describe (isteğe bağlı) | M | ingest | metni seyrek fotoğraf/afişin betimlemesi → `text/` (`[GÖRSEL BETİMLEME` başlığı), `describe.jsonl` |
| 4 | etiketler | D | kurulum | `labels.jsonl` (geçmiş yıl; yalnız karşılaştırma) |
| 5 | identify | D | ingest, transcribe, describe | `documents.jsonl` (tür, içerik tarihi, dönem, sürüm, çalışma adı) |
| 6 | candidates | D | identify | `candidates.jsonl` |
| 7 | karar_kaba / karar_ince | M | candidates | `decisions.jsonl` (ölçüt, yuva, aşama, birebir alıntı, kanıt adı) |
| 8 | hakem | I | karar_ince, etiketler | `consensus-labels.jsonl` |
| 9 | name (isteğe bağlı) | M | karar_ince | `kanit-adlari.jsonl` (kaynak: model) |
| 9b | faaliyet | D | karar_ince | `faaliyetler.json` (aynı toplantı/etkinliğin belgeleri; güncelliği içerikle denetlenir) |
| 10 | audit | D + I | karar_ince, hakem, name, faaliyet | `review.xlsx`, `gaps.md`, `audit-olcutler.json`; apply: `review-decisions.jsonl`, insan adları/bağlantıları |
| 10b | ikinci_arama (isteğe bağlı) | M | audit | `work/ikinci_arama/`, `decisions.jsonl`'e işaretli eşleşmeler (kabul varsa audit yeniden; `rapor.ikinci_arama: false` → atlandi) |
| 11 | file | D | audit, ikinci_arama | `evidence/A/A.1/A.1.2/…`, `evidence-index.csv` (ad, bağlantı) |
| 12 | write | M | file | `texts/<ölçüt>.json` |
| 13 | verify | D + M (+I) | write | `verify.jsonl`; reddedilen → yeniden yazım döngüsü; sınırdan sonra insan kararı |
| 14 | yonler | M (+D) | verify | `yonler/<alan>.json` (alan düzeyi Güçlü / Gelişmeye Açık Yönler; doğrulaması verify akışında, `verify-yonler.jsonl`) |
| 15 | render | D | yonler | `report.docx` (kanıt adları bağlantılı, kapak hazırlayanları, 8 güçlü/gelişme hücresi, ölçüt kapsamı, eksik kanıt notu), `gaps.md` bağlantı ve kapsam kararı bölümleri |
| 16 | denetle | D (+I) | render | `denetim.json` (güncel docx'in sha'sı; kritik bulgu → "yayıma hazır değil", kullanıcı) |

Rapor katmanının arayüzü: `docs/REPORT_LAYER.md`; denetim kuralları: `docs/AUDIT.md`;
model katmanı: `docs/MODEL_LAYER.md`.

## Kimlikler

`doc_id` = içerik sha256'sının ilk 16 hanesi (`bidr.common.doc_id`). Aynı içerik
aynı kimliği alır; ad değişse de değişmez.

## Ingest ayrıntıları (`bidr/ingest/`)

- **Biçimler** (`extract.py`): PDF (metin katmanı + OCR), docx/doc/rtf/odt, xlsx/xlsm, **xls**
  (xlrd; içi xlsx ya da HTML olan `.xls` uygun çıkarıcıya gider), pptx, txt/csv/md, HTML,
  görseller, **e-posta** (`.eml`: başlıklar + gövde, text/plain tercihli, yoksa HTML'den metin;
  `.msg` yalnız isteğe bağlı `extract-msg` kuruluysa, yoksa `unsupported`).
- **Kapsayıcılar** (`containers.py`): arşiv (zip, iç içe zip ve klasörler; tar/tgz; `bsdtar` varsa
  7z/rar) ve e-posta ekleri. Her üye envanterde ayrı satırdır; `rel_path` izlenebilir biçimdedir:
  `arsiv.zip!/alt/tutanak.pdf`, `ileti.eml!/ek.pdf`, iç içe `a.zip!/b.zip!/c.pdf`; `kapsayici`
  sütunu bir üst kapsayıcıyı verir. Arşivin kendi satırı `status=archive` (metni yok). Üye
  baytları çalışma klasörüne içerik kimliğiyle açılır (`arsiv/<doc_id><ext>`) ve sonraki bütün
  aşamalar onu normal belge gibi işler (birebir kopya tespiti dahil). Kaynak salt okunur kalır.
  Güvenlik: üye adı hiçbir zaman yazma yolu değildir; `../`/mutlak yollu üye `error` (yol
  geçişi); derinlik (4), üye sayısı (5000), üye (200 MiB) ve toplam (2 GiB) boyut, sıkıştırma
  oranı (200×) sınırları; okuma da sınırla yapılır. Şifreli üye/arşiv `error` ("şifreli"),
  bozuk arşiv `error`, açılamayan tür (bsdtar yokken 7z/rar) `unsupported` ("desteklenmeyen
  arşiv"). Arşiv/e-posta istisnaları gaps.md ingest bölümünde listelenir.
  **Aşağı akış:** describe, transcribe ve file üye dosyayı `bidr.transcribe.run.source_file`
  ile alır (açılmış kopya `arsiv/<doc_id><ext>`, yoksa `containers.source_path` kaynaktan yeniden
  açar; düz dosyada `kaynak/rel_path`); kanıt dosyalama arşivi değil üyenin kendisini kopyalar,
  `evidence-index.csv` `kaynak` sütunu izlenebilir yolu (`a.zip!/b.pdf`) taşır.
- **Parça grubu** (`parts.py`): tek belgenin bölünmüş parçaları. B, A'nın devamıdır: B'nin ilk
  sayfa numarası A'nın sonuncusunun bir fazlası ve destek (aynı toplam sayfa "Sayfa 3/6", aynı
  üst bilgi satırı ya da sözcük benzerliği). Dosya adına bakılmaz. Envanter: `parca_grubu`
  (`pg-<en küçük doc_id>`), `parca_sira`, `parca_gerekce`. identify'ın sürüm gruplarına katmak
  için `bidr.ingest.parts.merge_into_versions(groups, parca)` (identify çağırır; `documents.jsonl`
  `parca_grubu`, `parca_sira`): aynı parça grubu tek `surum_grubu` (`sg-…`) olur; dosyalama
  (`bidr/file/select.py`) dönem/tarih/sayı kıyası yapmadan aynı ölçütte tek kanıt sayar (neden
  `parca_grubu`; temsilci tek parça), audit'in yapı sürümü seçimi parça grubunu tek sürüm sayar.
- **Birden çok belge şüphesi** (`parts.multi_doc_starts`): birleştirilmiş PDF'te sayfa numarası
  1'e dönüyorsa ya da üst bilgi + başlık + konu (sözcük örtüşmesi) birlikte değişiyorsa
  `coklu_belge_suphesi` = yeni belgenin başladığı sayfalar (`3;7`); bölme yapılmaz, gaps.md'ye
  not düşülür.
- **gaps.md ingest bölümü** (`<!-- bidr:ingest -->` … `<!-- /bidr:ingest -->`): çoklu belge
  şüphesi, parça grupları, arşiv/e-posta istisnaları. Yalnız bu bölüm değiştirilir.

## Çalışma klasörü

Repo dışında tutulur (`bidr.common.Workspace`). Gerçek belge, metin, etiket
yalnız orada durur.

## Durum (2026-11-18)

Hat init'ten biçim denetimine (denetle) kadar uygulanmış ve bağlı (faaliyet kaydı, isteğe bağlı
ikinci arama ve denetle 2026-11-19'da bağlandı): her aşamanın kodla denetlenen tamamlanma
şartı var; sentetik uçtan uca test (`tests/test_pipeline.py`) bütün geçişleri, kapıları,
yeniden yazım döngüsünü ve bağlantılı raporu sınar. Model işi ajan modunda (ücretli API yok).

Ölçüm (v0.1 taban çizgisi, LLM yok, akademik bölüm profili): fakülte verisiyle eğitilip
Matematik'te sınanınca alt ölçüt R@1/R@5/R@10 0.22 / 0.67 / 0.77; ana ölçütte R@3 0.93.

Kalan işler:
1. `fotograf` türünün dönem sınıfı `bidr/data/profiles/donem_kurali.yaml`'a işlenmeli (şimdilik
   kodda karma: planla yapı, üstü olay).
2. Gerçek veriyle tam tur (mat2025): name → audit kararları → file → write → verify → yonler → render;
   bağlantı önerilerinin isabeti (web çıktılarının üst/altbilgisi) gerçek belgelerle ölçülmeli.
3. Etiket tutarlılığı incelemesi (aynı içerik, farklı birimde farklı ölçüt); yuva etiketi
   önerilerinin (`slot-tags-oneri.yaml`) paket verisine işlenmesi kullanıcı onayıyla.
4. Geçen yılla sürüm farkı ve yenilik işareti (önceki yıl metni yalnız yazımda kullanılıyor).
5. Parça grubunun tarihi: parçalar tek kaynak sayılır (identify `surum_grubu`, dosyalamada tek
   kanıt, audit sürüm durumunda tek üye) ama her parçanın dönem kuralı kendi tarihine bakar; tarihsiz
   devam parçası grubun tarihini devralmıyor. Parçaların birleştirilmesi ve birden çok belgeli PDF'in
   bölünmesi sonraki tur.
