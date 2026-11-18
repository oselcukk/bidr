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
| 1 | ingest | D (+OCR) | kurulum | `inventory.csv`, `text/<doc_id>.txt` |
| 2 | transcribe (isteğe bağlı) | M | ingest | düşük kaliteli taramaların görsel okuması → `text/` |
| 3 | describe (isteğe bağlı) | M | ingest | metni seyrek fotoğraf/afişin betimlemesi → `text/` (`[GÖRSEL BETİMLEME` başlığı), `describe.jsonl` |
| 4 | etiketler | D | kurulum | `labels.jsonl` (geçmiş yıl; yalnız karşılaştırma) |
| 5 | identify | D | ingest, transcribe, describe | `documents.jsonl` (tür, içerik tarihi, dönem, sürüm, çalışma adı) |
| 6 | candidates | D | identify | `candidates.jsonl` |
| 7 | karar_kaba / karar_ince | M | candidates | `decisions.jsonl` (ölçüt, yuva, aşama, birebir alıntı, kanıt adı) |
| 8 | hakem | I | karar_ince, etiketler | `consensus-labels.jsonl` |
| 9 | name (isteğe bağlı) | M | karar_ince | `kanit-adlari.jsonl` (kaynak: model) |
| 10 | audit | D + I | karar_ince, hakem, name | `review.xlsx`, `gaps.md`, `audit-olcutler.json`; apply: `review-decisions.jsonl`, insan adları/bağlantıları |
| 11 | file | D | audit | `evidence/A/A.1/A.1.2/…`, `evidence-index.csv` (ad, bağlantı) |
| 12 | write | M | file | `texts/<ölçüt>.json` |
| 13 | verify | D + M (+I) | write | `verify.jsonl`; reddedilen → yeniden yazım döngüsü; sınırdan sonra insan kararı |
| 14 | render | D | verify | `report.docx` (kanıt adları bağlantılı), `gaps.md` bağlantı bölümü |

Rapor katmanının arayüzü: `docs/REPORT_LAYER.md`; denetim kuralları: `docs/AUDIT.md`;
model katmanı: `docs/MODEL_LAYER.md`.

## Kimlikler

`doc_id` = içerik sha256'sının ilk 16 hanesi (`bidr.common.doc_id`). Aynı içerik
aynı kimliği alır; ad değişse de değişmez.

## Çalışma klasörü

Repo dışında tutulur (`bidr.common.Workspace`). Gerçek belge, metin, etiket
yalnız orada durur.

## Durum (2026-11-18)

Hat init'ten render'a kadar uygulanmış ve bağlı: her aşamanın kodla denetlenen tamamlanma
şartı var; sentetik uçtan uca test (`tests/test_pipeline.py`) bütün geçişleri, kapıları,
yeniden yazım döngüsünü ve bağlantılı raporu sınar. Model işi ajan modunda (ücretli API yok).

Ölçüm (v0.1 taban çizgisi, LLM yok, akademik bölüm profili): fakülte verisiyle eğitilip
Matematik'te sınanınca alt ölçüt R@1/R@5/R@10 0.22 / 0.67 / 0.77; ana ölçütte R@3 0.93.

Kalan işler:
1. `fotograf` türünün dönem sınıfı `bidr/data/profiles/donem_kurali.yaml`'a işlenmeli (şimdilik
   kodda karma: planla yapı, üstü olay).
2. Gerçek veriyle tam tur (mat2025): name → audit kararları → file → write → verify → render;
   bağlantı önerilerinin isabeti (web çıktılarının üst/altbilgisi) gerçek belgelerle ölçülmeli.
3. Etiket tutarlılığı incelemesi (aynı içerik, farklı birimde farklı ölçüt); yuva etiketi
   önerilerinin (`slot-tags-oneri.yaml`) paket verisine işlenmesi kullanıcı onayıyla.
4. Geçen yılla sürüm farkı ve yenilik işareti (önceki yıl metni yalnız yazımda kullanılıyor).
