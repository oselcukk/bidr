# ihtiyac: kanıt ihtiyaç raporu

```
bidr ihtiyac referans -w ÖNCEKİ_WS [--ek iyi-kanitlar.csv] --out referans.json
bidr ihtiyac -w WS [--referans referans.json] [--out DIR] [--ic-taslak]
             [--istenecekler istenecekler.md|.csv] [--somut S.yaml] [--oneriler O.yaml]
             [--turler T.yaml] [--sorumlular S.yaml] [--kurum-katalog kurum-katalog-esleme.json]
bidr kurum-katalog cek     [-w WS | --kurum K | --profil P.yaml] [--out DIR]
bidr kurum-katalog prepare [-w WS] [--out DIR] [--yeniden]
bidr kurum-katalog apply   [-w WS] [--out DIR] --model M
```

İki Excel üretilir: **`istenen-kanitlar.xlsx`** bölümdeki kişilere/birimlere iletilecek sade listedir
(bkz. 5); `ihtiyac.xlsx` model/teknik kullanım içindir (puan, kaynak, kılavuz yuvası, PUKÖ halkası).

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
| `istenen-kanitlar.xlsx` | sade liste (bölüme iletilecek; bkz. 5) |
| `kurum-katalog.json`, `kurum-katalog-esleme.json` | `bidr kurum-katalog` çıktıları (bkz. 6); `ihtiyac` yalnız okur |
| `ihtiyac.md` | sayılar (önceliğe ve kaynağa göre), ilk 15 talep (kaynakla), kılavuz önerileri (ölçüt başına yuva kimlikleri), karşılığı bulunmayan iyi kanıtlar |
| `report-ic.docx` | `--ic-taslak`: report.docx'in **kopyası**; her ölçütün "Açıklamalar" hücresinin sonuna kırmızı "[EKSİK: …]" ve başa "İÇ ÇALIŞMA TASLAĞI" satırı. Asıl `report.docx`'e yazılmaz (aynı yola yazma reddedilir); render kodu değişmez, blok bulucu (`bidr.render.template.find_blocks`) yalnız okunur. |

## 5. Sade liste: `istenen-kanitlar.xlsx`

Komisyon dışındaki okur (bölüm sekreterliği, komisyon başkanları, öğretim elemanları) için; her
`bidr ihtiyac` çalışmasında yazılır. Model yok; metinler kodla şablonlanır (`bidr/ihtiyac/sade.py`).

- **Satır = madde (alt ölçüt)**: talepler ölçüt başına tek satırda toplanır. Sıralama: öncelik, sonra
  kanıtsız maddeler, sonra puan, sonra madde kodu.
- **Sütunlar**: Sıra · Madde (`B.3.2 — Akademik destek hizmetleri`, kılavuz başlığı) · Öncelik ·
  İstenen belgeler · Neden gerekli · Kimden istenebilir · Kılavuzdaki örnek kanıtlar · Not / örnek.
  Puan, kaynak, belge türü ve yuva kimliği yazılmaz.
- **Öncelik** (sözle): Yüksek = kanıtsız madde ya da tek belgeyle olgunluk düzeyi artan madde (puan
  ≥ 80); Orta = geçen yılın karşılığı bulunamayan belgesi ya da bir üst düzeyin eksik belgesi (45–60);
  Düşük = yalnız tamamlayıcı kılavuz önerileri. Elle istek satırın önceliğini yükseltebilir (varsayılan
  Orta; satırda `[yüksek]`/`[düşük]`).
- **İstenen belgeler** (madde madde, bu sırayla): (1) elle istekler; (2) geçen yılki raporda olup bu
  yıl karşılığı bulunamayan belgeler — tekrarlayan belgede addaki yıl rapor yılına ilerletilir
  ("… 2025-2026 (geçen yılki raporda: «… 2024-2025»)"), aynı türden 3+ belge tek maddede toplanır
  (kurum yönetmelik/yönerge/iş akışları birlikte); (3) **komisyon önerileri**
  (`bidr/data/ihtiyac_oneriler.yaml`: syllabus, TYYÇ matrisleri, ders bilgi paketi, kabul/mezuniyet
  koşulları, diploma eki, fiziki olanaklar, seminer duyuruları, ders anketleri…; her öneri kılavuz
  maddelerine eşlenir ve yalnız eşlendiği maddelerden biri karşılanmamışsa gösterilir); (4)
  karşılanmamış kılavuz maddelerinin **somut karşılıkları** (`bidr/data/ihtiyac_somut.yaml`: her
  "Örnek Kanıtlar" maddesi → bölüm düzeyinde 1–2 somut belge; `{yil}` rapor yılı; özgün uygulama
  maddeleri ortak metinle ve yalnız son düzey istendiğinde). (3)+(4) satır başına en çok 6 madde;
  öneriyle kapsanan kılavuz maddesi ayrıca yazılmaz. Tam liste `ihtiyac.xlsx`'tedir; (5) **kurumun
  bu maddeyle eşlenmiş belgeleri** (bkz. 6): `• Belge adı (kod)` (yalnız yönetmelik, yönerge, usul-esas, iş akışı ve anket; form girmez; bağlantı yalnız `kurum-katalog.json`'da), en çok 10 (fazlası
  "… ve N belgesi daha"); geçen yılki raporda kullanılan kurum belgesi katalogda bulunursa (2)'de
  ayrıca yazılmaz, bağlantısıyla burada ilk sıradadır. Kimden: `ihtiyac_sorumlular.yaml` belge türü
  satırı (yönetmelik, yönerge, usul_esas, iş akışı, form, anket).
- **Neden gerekli**: hazır cümleler — "Bu madde için şu an rapora konabilecek hiç belge yok. En çok
  işe yarayacak belge … gösteren bir belgedir: tek başına maddenin olgunluk düzeyini 1'den 3'e
  çıkarır.", "Bu maddede N belge var ama … gösteren belge yok …", "Geçen yılki raporda bu maddede
  kullanılan N belgenin bu yılki hâli bulunamadı.", "Madde şu an olgunluk düzeyi 3'te. Bir üst düzeye
  (4) çıkmak için … gerekiyor." Aşamalar düz Türkçe: plan/kural, gerçekten yapıldığı, izleme sonucu,
  iyileştirme, özgün uygulama.
- **Kılavuzdaki örnek kanıtlar**: maddenin henüz karşılanmamış "Örnek Kanıtlar" metinleri (kılavuzdan
  birebir, madde madde; kod yok).
- **Kimden istenebilir**: maddelerin sorumluları (en çok 3); `ihtiyac_sorumlular.yaml`, kayıtta varsa
  `ihtiyac_somut.yaml`'daki `kimden`. Belirsiz "İlgili komisyon" yerine alanın sorumlusu yazılır.
- **Not / örnek**: dosyada zaten olan belgeler (en çok 4) ve geçen yıl bu amaçla kullanılan belge.
- **Sayfalar**: "İstenen kanıtlar", "Kime gönderilecek" (aynı istekler kişi/birim × madde),
  "Nasıl okunur" (5 satır). Hücreler kaydırmalı, başlık satırı dondurulmuş ve her sayfada yinelenir,
  yatay A4'e genişlikte sığar.

**Elle istekler** (`--istenecekler`): inceleme sırasında komisyonun söylediği istekler.
Markdown: yalnız madde işaretli satırlar okunur, `- B.3.2 — 2026 ders izlenceleri (syllabus)`
(ayırıcı `—`, `–`, `:` ya da ` - `; `**B.3.2**` da olur). Satırda `[yüksek]`/`[orta]`/`[düşük]` ve
`(kimden: …)` isteğe bağlı. `B.1.x` ya da `B.1` ana madde satırı olarak ("alt madde belirtilmedi"),
kodsuz satır "Genel" satırı olarak eklenir. CSV: `madde,istek` zorunlu, `oncelik`, `kimden` isteğe bağlı.

## 6. Kurum belge kataloğu (`bidr kurum-katalog`)

Kurumun herkese açık mevzuat ve kalite sayfalarındaki belgelerin (yönetmelik, yönerge, usul-esas,
iş akışı, form, anket) yalnız **adları ve bağlantıları** çekilir, adlarından alt ölçütlere eşlenir ve
sade listeye madde olarak girer. Ek dosyalar indirilmez.

1. **`cek`**: kurum profilinin `katalog:` kayıtları (`bidr/data/institutions/<kurum>.yaml`; `ad`,
   `adres`, `tur`, isteğe bağlı `etkin: false`, `not`). Kurum `-w` çalışma alanının `config.yaml`'ından,
   `--kurum` ya da `--profil` ile. Her liste sayfası tek istek (sayfalama: `rel="next"` ya da
   "Sonraki" bağlantısı aynı yolda izlenir, en çok 20 sayfa); istekler arası 2 sn; User-Agent araç
   adıdır. Ayrıştırma geneldir: tablo başlığında "… ADI" (ad), "… NO" (doküman kodu), "DİLİ",
   "… TARİHİ"/"… SAYISI", "REVİZYON NO" sütunları; "BİRİM ADI:" satırı birim; tablo dışında belge
   dosyasına giden bağlantılar (metindeki kod, kalın ara başlık bölüm; parantez içindeki ikinci bağlantı
   İngilizce sürüm). Tür: sayfanın `tur`'u; yönerge sayfasında "Usul ve Esaslar/Uygulama Esasları"
   adı `usul_esas`, form sayfasında "Anket" adı ya da bölümü `anket`. İngilizce satır aynı kodlu
   Türkçe öğeye `en_baglanti` olur. Çıktı `kurum-katalog.json` (öğe: id, ad, kod, tür, bağlantı,
   birim, bölüm, dil, tarihler, revizyon, sayfa; sayfa başına durum ve öğe sayısı). Çekilemeyen ya da
   öğe bulunamayan sayfa uyarıyla raporlanır.
2. **`prepare`**: kural ön elemesi (`bidr/data/kurum_katalog_kurallar.yaml`): `ele_bolum`,
   `ele_birim`, `ele_ad` desenleri ilgisiz alanları eler (`tut` desenleri elemeyi aşar); `esle`
   desenleri adı aday ölçütlere bağlar (en çok `en_cok` = 3). Kurala uyan öğeler ve elenmeyen bütün
   yönetmelik/yönerge/usul-esaslar model iş paketlerine konur (`work/kurum-katalog/kk-NNN.json`, 60
   öğe; görev `bidr/tasks/kurum_katalog_esle`: ad, kod, tür, birim/bölüm ve kural önerisi → en çok 3
   ölçüt ve kısa gerekçe). Kurala uymayan form/iş akışı ilgisiz kalır. Sonuç
   `kurum-katalog-esleme.json` (öğe başına `ilgili`, `olcutler`, `gerekce`, `kaynak`: kural|model).
3. **`apply`**: `kk-NNN.out.json` cevapları şemaya, paket id'lerine, geçerli alt ölçüt koduna ve en
   çok 3 ölçüte göre denetlenir; geçersizler `GECERSIZ.md`'ye. Model cevabı kural önerisini aşar.

**Önbellek**: öğe anahtarı tür + kod + ad + birim + bölüm. Katalog yeniden çekildiğinde değişmeyen
öğenin model eşlemesi korunur ve yeniden paketlenmez (bağlantı/revizyon değişikliği eşlemeyi
değiştirmez). `prepare`, cevaplanmış ama uygulanmamış paketleri önce uygular. `--yeniden` hepsini
yeniden paketler.

`bidr ihtiyac` eşlemeyi `--kurum-katalog` ile, verilmezse `--out` klasöründe sonra çalışma alanında
arar; yoksa sade liste kurum belgeleri olmadan üretilir.

## Sınırlar

- Eşleştirme benzerliğe dayanır: `var` satırları gözle doğrulanmalıdır (özellikle aynı kalıptan
  üretilmiş belgeler: ders bilgi formları, AKTS sayfaları).
- Dönem kararı identify/audit'in tarih bilgisine dayanır; tarihi okunamayan ya da sonradan
  indirilmiş (dönem sonrası tarihli) web sayfaları "doğrulanmalı" diye işaretlenir.
- Referans set yalnız incelemesi yapılmış (karar yazılmış) çalışma alanından iyi kanıt çıkarır.
- Kılavuz önerileri yuva düzeyindedir: bir yuva farklı bir yuvaya eşlenmiş belgeyle fiilen
  karşılanmış olabilir (eşleştirme yuvayı seçer). Yuva metinleri kurum geneli ifadeler içerir
  ("Kurumun…"); birim düzeyinde karşılığı ayrıca düşünülmelidir. PUKÖ etiketleri öneridir.
- Kurum belgeleri yalnız adlarından eşlenir (içerik okunmaz): bir belge adında geçmeyen bir ölçüte
  ilgili olabilir ya da adı ilgili görünüp içeriği başka olabilir. Liste sayfasının yapısı değişirse
  `cek` "öğe bulunamadı" uyarısı verir.
- Sade listedeki somut belge adları ve öneri eşlemesi geneldir (her birim için doğru değildir); birimin
  düzenine göre `--somut` / `--oneriler` ile kopyası verilebilir. Elle istek ile öneri aynı belgeyi
  farklı sözlerle isteyebilir (metin karşılaştırması yapılmaz).
