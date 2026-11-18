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

| # | Aşama | Katman | Çıktı (çalışma klasöründe) |
|---|---|---|---|
| 1 | ingest | D (+OCR) | `inventory.csv`, `text/<doc_id>.txt` |
| 2 | identify | D (+M) | `documents.jsonl` (tür, içerik tarihi, sürüm grubu, çalışma adı) |
| 3 | segment | D (+M) | `segments.jsonl` |
| 4 | candidates | D | `candidates.jsonl` (tür tablosu + metin benzerliği) |
| 5 | decide | M | `decisions.jsonl` (ölçüt, OD, alıntı) |
| 6 | audit | D | `review.xlsx` |
| 7 | — | İnsan | onay |
| 8 | file | D | `evidence/A/A.1/A.1.2/…`, `evidence-index.csv` |
| 9 | write | M | `texts/<ölçüt>.md` |
| 10 | verify | D+M | `verify.jsonl` |
| 11 | — | İnsan | onay |
| 12 | render | D | `report.docx`, `gaps.md` |

v0.1 kapsamı: iskelet, ölçüt şeması, ingest, etiketli veri, kural tabanlı tanı ve
taban çizgisi ölçümü.

## Kimlikler

`doc_id` = içerik sha256'sının ilk 16 hanesi (`bidr.common.doc_id`). Aynı içerik
aynı kimliği alır; ad değişse de değişmez.

## Çalışma klasörü

Repo dışında tutulur (`bidr.common.Workspace`). Gerçek belge, metin, etiket
yalnız orada durur.

## Durum (v0.1, 2026-11-18)

Biten: `criteria` (46 alt ölçüt, 273 kanıt yuvası, PUKÖ/OD etiketleri:
23 onaylı, 250 öneri), `ingest` (OCR, gömülü görsel, bozuk metin katmanı
tespiti, kalite işareti), `labels`, `identify` (49 tür, yalnız içerik),
`candidates` (bm25, yuva, knn, tür, önsel), `evaluate` (birim dışarıda
bırakmalı ve aktarım bölmeleri; doc_id, metin özeti ve yakın kopya ayıklama).
Bağımsız doğrulama: sızıntı yok, ölçüm yeniden üretilebilir.

Taban çizgisi (LLM yok, akademik bölüm profili, alt ölçüt R@1/R@5/R@10):
fakülte verisiyle eğitilip Matematik'te sınanınca 0.22 / 0.67 / 0.77;
ana ölçütte R@3 0.93.

## v0.2 planı

1. Model katmanı: görev sözleşmeleri (`gorevler/`), sağlayıcılar
   (openai-compatible, anthropic, claude-cli), iki adımlı karar
   (46 başlıktan kaba seçim → rubrikli ince karar, birebir alıntı zorunlu).
2. Ölçüt düzeyinde OD toplama (PUKÖ yuvaları üzerinden), yenilik işareti,
   geçen yılla sürüm farkı.
3. `audit` + `review.xlsx`: kullanılan yuva etiketi her satırda; OD4/OD5'e
   yükselten etiketler işaretli; onaylar etiket dosyasına geri yazılır.
4. Etiket tutarlılığı incelemesi (aynı içerik, farklı birimde farklı ölçüt).
