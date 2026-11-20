# ihtiyac: kanıt ihtiyaç raporu

```
bidr ihtiyac referans -w ÖNCEKİ_WS [--ek iyi-kanitlar.csv] --out referans.json
bidr ihtiyac -w WS [--referans referans.json] [--out DIR] [--ic-taslak]
             [--turler T.yaml] [--sorumlular S.yaml]
```

Rapor yazılırken belgeler parça parça gelir. `bidr ihtiyac` mevcut çalışma alanından şunu
çıkarır: hangi ölçütte ne eksik, hangi belgenin eklenmesi raporu en çok güçlendirir, kılavuzun
(boş FR-0833 şablonu) "Örnek Kanıtlar" yuvalarından hangileri henüz karşılanmadı, geçen yıl iyi
kanıt olan belgelerin bu yılki karşılığı var mı ve belge kimden istenir. Referans set (geçen yıl)
verilmeden de çalışır: öneriler kılavuzdan ve çalışma alanının kendi durumundan gelir. **Hatırlatma ve öncelik
aracıdır, kesin kontrol listesi değildir.**

- Model çağrısı yok; yalnız mevcut çıktılar (decisions.jsonl, review-decisions.jsonl,
  documents.jsonl, `text/`, audit-olcutler.json) kodla okunur. Satırlar ve OD
  `bidr.audit.run.build` ile kurulur (audit'in dönem, birim aitliği ve kurum geneli kuralları aynen).
- Hat aşaması değildir (pipeline.yaml'da yok, önkoşul kapısı yok). Çalışma alanını salt okur;
  çıktılar `--out` klasörüne (varsayılan çalışma alanı). Paylaşılan bir çalışma alanını
  değiştirmemek için `--out` verin.
- `audit-olcutler.json` decisions.jsonl ile güncelse ölçüt OD'si oradan, değilse yeniden
  hesaplanır (uyarı yazılır).

## 1. Referans set (geçen yılın iyi kanıtları)

`bidr ihtiyac referans -w ÖNCEKİ_WS --out referans.json` önceki (bitmiş) çalışma alanından iyi
kanıtları çıkarır: incelemede **kabul** (ya da düzeltilerek kabul) edilmiş, güveni **orta/yüksek**
(düşük hariç), önerilen OD'ye **katkısı olan** (sayılan) eşleşmeler. Belge × ölçüt başına bir öğe
(aynı ölçütte birden çok yuva birleşir). Öğe: ölçüt, yuva(lar), aşama, belge türü, kanıt adı,
anahtar sözcükler (TF-IDF), tarih/dönem, tekrarlayan tür.

Referans dosyası kendi başına yeterlidir: önceki çalışma alanı sonradan kaldırılsa da eşleştirme
yapılabilsin diye her belge için örneklenmiş içerik parmak izi (karma sayılar; metin değil) saklanır.
Dosya yine de kurum belgelerinden türetilmiştir: repoya konmaz.

**Elle ek** (`--ek iyi-kanitlar.csv`): denetçilerin "iyi kanıt" dediği belgeler. Başlıklar
`olcut,belge_turu,ad` zorunlu; `yuva`, `asama`, `anahtar` (boşlukla ayrılmış sözcükler) isteğe
bağlı. `belge_turu` `bidr/data/doc_types.yaml` tür adıdır. `-w` olmadan yalnız CSV'den referans da
üretilebilir (ilk yıl).

**Tekrarlayan türler** (`bidr/data/ihtiyac_turler.yaml`, `--turler` ile değiştirilir): her yıl/dönem
yeniden üretilen belgeler (ders değerlendirme ve memnuniyet anketleri, danışma kurulu toplantısı,
stratejik plan izleme, bölüm kurulu kararı, komisyon/bölüm toplantısı, seminer programı, faaliyet
raporu, ders programı, görev dağılımı, proje/yayın listesi, staj, birim raporu). Kayıt: belge
türleri + isteğe bağlı desen (ad/başlık/metin başında aranır). İlk uyan kayıt kullanılır.

## 2. Karşılık eşleştirme

Her referans öğe için güncel çalışma alanının bütün belgeleri (başka birime ait sayılanlar hariç)
taranır. Benzerlik:

- **İçerik kopyası**: `bidr.identify.versions`'ın parmak izi ve iki yönlü kapsama eşikleri
  (`fingerprint`, `containment`, `COPY_LO/COPY_HI`; kalıp türlerinde — iş akışı, yönerge, form… —
  iki yönde `COPY_STRICT`). Güncel derlemde çok belgede geçen parçacıklar (kurum kalıbı) sayılmaz.
- **Anahtar sözcük** ve **ad** örtüşmesi (güncel derlemin IDF'iyle ağırlıklı; ad önce kanıt
  adı/başlıkta, bulunmazsa daha düşük ağırlıkla metnin başında aranır) ve **tür** uyumu (aynı tür ya
  da aynı tekrarlayan tür; biri bilinmiyorsa yarım puan).
- Kopya değilse: birleşik benzerlik ≥ 0,55 ve anahtar sözcük ≥ 0,40; tekrarlamayan belgede ad
  örtüşmesi ≥ 0,70 (kardeş kalıplar ayrılsın); tür farklıysa anahtar sözcük ≥ 0,80 ve ad ≥ 0,40
  (tür yanlış atanmış olabilir).

Durum (dönem: audit'in `doc_time` / `yapi_time` kuralı):

| Durum | Tekrarlayan tür | Tekrarlamayan (yapı) belge |
|---|---|---|
| `var` | dönem içi karşılık; tarihi bilinmeyen karşılık (+ "doğrulanmalı") | dönem içi karşılık; dönem dışı ama referanstan eski olmayan karşılık (+ "yürürlüğü doğrulanmalı") |
| `eski_surum` | yalnız önceki yıla ait karşılık | karşılık referans belgeden eski |
| `yok_istenmeli` | karşılık yok ya da yalnız dönem sonrası | karşılık yok |

Her satırda eşleştirme gerekçesi ve karşılığın bu ölçüte eşleşip eşleşmediği yazılır. "Belge var
ama bu ölçüte eşleşmemiş" satırı karar/inceleme için ipucudur (karar değiştirilmez).

## 3. Ölçüt satırı ve öncelik

Her ölçüt için: mevcut (sayılan) kanıtlar, önerilen OD, PUKÖ zinciri, bir üst düzey için eksik
halkalar ve **gereken** (audit'in `GEREKEN` metni + kılavuzda o aşamaya etiketli yuva metinleri,
`bidr/data/criteria/`), geçen yılın karşılığı olmayan iyi kanıtları, kimden istenir, öncelik.
Kapsam dışı ölçütler (profil/`config.yaml rapor.kapsam` → `baska_birim`) listelenmez.

| Öncelik | Puan | Ne zaman |
|---|---|---|
| kanıtsız ölçüt | 100 | ölçütte sayılan kanıt yok |
| tek belgeyle OD artışı | 80–84 | tek halka (tek belge) OD'yi yükseltir (`audit.rules.criterion_od` ile denenir); OD düşükse biraz daha yüksek |
| karşılığı olmayan iyi kanıt | 60 (eski sürüm 58) | geçen yılın iyi kanıtı `yok_istenmeli` / `eski_surum` |
| kılavuz önerisi | 45 / 38 / 32 | karşılanmamış "Örnek Kanıtlar" yuvası: bir üst düzeyin eksik halkası 45, daha üst düzeyin halkası 38, kanıtı olan halkanın boş yuvası 32 (bkz. 3.1) |
| diğer | 20 | yukarıdakiler yoksa: bir üst düzey birden çok halka ister |

Kanıtsız ve tek belge taleplerinde OD'yi en çok yükselten halka istenir (eşitlikte zincirde önce
gelen; aynı etkiyi yapan öteki halkalar gerekçede yazılır).

Gerekçeye hedeflenen düzeyin **kılavuzdaki olgunluk düzeyi tanımı** (`SubCriterion.rubric`)
kısaltılarak eklenir: `OD3 tanımı (kılavuz): «…»` (yalnız kılavuz metni; 160 karakterde kesilir).

### 3.1 Kılavuz önerileri

Her ölçütte, dipnot olmayan her örnek kanıt yuvası (`SubCriterion.example_evidence`; yuva PUKÖ
etiketleri `slot-tags-yokak-2025.yaml`) için **kabul edilmiş** bir kanıt aranır: satırın yuvası bu
yuva, satır sayılıyor, reddedilmemiş ve güveni orta/yüksek ya da incelemede kabul/düzelt edilmiş
(insan kararı düşük güveni aşar; audit ve referans setin kabul mantığı). Bulunmayan yuva
"kılavuz önerisi" olur: yuva metni (şablondan birebir), PUKÖ halkası, kimden istenir (eksik
halkanın sorumlusu), puan ve gerekçe (halka + hedef düzeyin rubrik tanımı; kanıtı olan halkanın
boş yuvasında rubrik yazılmaz).

- **Birleştirme**: yuva zaten bir talebin yuvalarında geçiyorsa (kanıtsız / tek belge / çok halka
  talebinin halka yuvaları ya da geçen yılın iyi kanıtının yuvası) ayrı satır açılmaz; o satırın
  `kaynak`ına "kılavuz" eklenir, puanı ikisinin büyüğü olur. Bu yüzden bir üst düzeyin eksik
  halkasını isteyen "diğer" satırı karşılanmamış yuva içeriyorsa 45 puanla "kılavuz önerisi"
  grubuna geçer.
- **Açıklama metni** (`SubCriterion.description`): her yuvalı talebe, istenen metinle en çok ortak
  sözcük kökü (ilk 5 harf, en az 2) olan açıklama cümlesi "Ölçüt açıklamasından (kılavuz)"
  sütununda gösterilir. Sözcük örtüşmesine dayanır; ipucudur, eşleşme değildir.
- **Kaynak** sütunu: `kanıtsız`, `OD artışı` (tek belge ya da çok halka), `geçen yıl`, `kılavuz`;
  birleşen satırda `+` ile.

**Kimden istenir** (`bidr/data/ihtiyac_sorumlular.yaml`, `--sorumlular` ile değiştirilir): belge
türü → eksik aşama → ölçüt alanı → varsayılan. Varsayılanlar geneldir (bölüm sekreterliği, ilgili
komisyon, bölüm başkanlığı, kalite komisyonu…); birimin kendi düzenine göre uyarlanmalıdır.

## 4. Çıktılar

| Dosya | İçerik |
|---|---|
| `ihtiyac.xlsx` | "Öncelikli talepler" (puan sırasıyla; Kaynak, PUKÖ halkası, ölçüt açıklamasından sütunları), "Ölçüt özeti" (karşılanmamış kılavuz yuvaları, bir üst düzeyin tanımı), "Geçen yıl karşılıkları", "Açıklama" |
| `ihtiyac.md` | sayılar (önceliğe ve kaynağa göre), ilk 15 talep (kaynakla), kılavuz önerileri (ölçüt başına yuva kimlikleri), karşılığı bulunmayan iyi kanıtlar |
| `report-ic.docx` | `--ic-taslak`: report.docx'in **kopyası**; her ölçütün "Açıklamalar" hücresinin sonuna kırmızı "[EKSİK: …]" ve başa "İÇ ÇALIŞMA TASLAĞI" satırı. Asıl `report.docx`'e yazılmaz (aynı yola yazma reddedilir); render kodu değişmez, blok bulucu (`bidr.render.template.find_blocks`) yalnız okunur. |

## Sınırlar

- Eşleştirme benzerliğe dayanır: `var` satırları gözle doğrulanmalıdır (özellikle aynı kalıptan
  üretilmiş belgeler: ders bilgi formları, AKTS sayfaları).
- Dönem kararı identify/audit'in tarih bilgisine dayanır; tarihi okunamayan ya da sonradan
  indirilmiş (dönem sonrası tarihli) web sayfaları "doğrulanmalı" diye işaretlenir.
- Referans set yalnız incelemesi yapılmış (karar yazılmış) çalışma alanından iyi kanıt çıkarır.
- Kılavuz önerileri yuva düzeyindedir: bir yuva farklı bir yuvaya eşlenmiş belgeyle fiilen
  karşılanmış olabilir (eşleştirme yuvayı seçer). Yuva metinleri kurum geneli ifadeler içerir
  ("Kurumun…"); birim düzeyinde karşılığı ayrıca düşünülmelidir. PUKÖ etiketleri öneridir.
