# Rapor katmanı (file → write → verify → render) — arayüz sözleşmesi

Sahibi: şef. Üç şerit bu sözleşmeye göre paralel yazar.

## Girdi: onaylı eşleşmeler
`decisions.jsonl` içindeki kabul edilmiş eşleşmeler; varsa `review-decisions.jsonl`
(audit apply) kararları üstündür: `ret` olan eşleşme düşer, `duzelt` olan düzeltilmiş
ölçüt/yuva/aşamayla girer. Ölçüt düzeyi OD: `audit-olcutler.json` (audit çıktısı).

## file → `evidence-index.csv` + `evidence/`
Sütunlar: `kanit_no` (ölçüt içinde sıra + OD, kılavuz gösterimi: `1_OD3`),
`olcut`, `od`, `ad` (insan okur kanıt adı, çalışma adından), `dosya` (evidence/'e göre
göreli yol), `doc_id`, `sayfalar` (boş = tüm belge), `yuvalar`, `alintilar` (JSON liste).
Bir belge bir ölçütte bir kez numaralanır; farklı ölçütlerde ayrı numara alır.

## write → `texts/<olcut>.json`
```json
{"olcut": "B.1.1", "od_onerisi": 3, "durum": "taslak|dogrulandi|reddedildi",
 "paragraflar": [{"metin": "… uygulanmaktadır [1_OD3].", "atiflar": ["1_OD3"]}],
 "kanitlar": [{"no": "1_OD3", "ad": "…", "dosya": "…"}],
 "eksikler": ["…"], "onceki_yila_gore": "…", "kaynak": {"model": "…", "gorev_surumu": "…"}}
```
Her cümle en az bir atıf taşır; atıflar `evidence-index.csv`'de olmalı. Metin OD'yi
`audit-olcutler.json`'daki önerilen düzeyin üstünde iddia etmez.

## verify → `verify.jsonl` + `texts/<olcut>.json` `durum` güncellemesi
Kod denetimi (atıf var mı, alıntı belgede mi, OD aşımı) + model denetimi (cümle atfıyla
gerçekten destekleniyor mu). Geçemeyen metin `reddedildi`, gerekçeyle.

## render → `report.docx`
FR-0833 şablonunun ölçüt bloklarında "Açıklamalar" ve "Kanıtlar" hücreleri doldurulur;
biçim kılavuza uygun. `dogrulandi` olmayan metin varsa belge "TASLAK" damgalı üretilir.
