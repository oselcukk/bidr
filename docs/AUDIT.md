# audit: ölçüt OD'si, eksik kanıt raporu, inceleme tablosu

`bidr audit -w WS [--profile P] [--out DIR]` · `bidr audit apply -w WS [--out DIR]`

Belirleyici aşama (model yok). Girdi: `decisions.jsonl` (yalnız ince aşamada **kabul
edilmiş** eşleşmeler: alıntısı kodla doğrulanmış), `documents.jsonl` (tür, dönem içi,
çalışma adı), ölçütler ve yuva etiketleri (`slot-tags-yokak-2025.yaml`). Çalışma alanını
yalnız okur; çıktılar `--out` klasörüne (varsayılan çalışma alanı):

| Dosya | İçerik |
|---|---|
| `review.xlsx` | Sayfa 1 "Eşleşmeler": satır = kabul edilmiş eşleşme; sayfa 2 "Ölçüt özeti"; "Başka birime ait sayılanlar"; "Açıklama"; gizli `_meta` |
| `gaps.md` | OD dağılımı, öncelikli eksikler, kurum geneli uyarıları, ölçüt ölçüt zincir ve boş yuvalar |
| `audit-olcutler.json` | Ölçüt özetlerinin makine okunur hali (render aşaması için) |
| `review-decisions.jsonl` | `apply`: kullanıcı kararları (satır başına bir kayıt) |
| `olcut-od-kararlari.jsonl` | `apply`: komisyonun onayladığı nihai OD ("Ölçüt özeti" ONAYLANAN OD; kod önerisinden ayrı) |
| `slot-tags-oneri.yaml` | `apply`: yuva etiketi onay/düzeltme ÖNERİLERİ; etiket dosyasını değiştirmez |
| `birim-kararlari.jsonl` | `apply`: insan birim ilişkisi kararları (belge başına; `bidr decide` çalışma alanındakini okur) |

## OD bir ölçüt özelliğidir

Belge OD taşımaz; her eşleşme ölçütün PUKÖ zincirinde bir **halkayı** kanıtlar. Halkalar ve
düzeyler (rubrik 2-5 ile, `slots.STAGE_OD` ile aynı):

| Düzey | Gereken halkalar |
|---|---|
| OD2 | planla (P) |
| OD3 | + uygula (U) |
| OD4 | + kontrol_et (K) **ve** onlem_al (Ö) — ikisi birden |
| OD5 | + ozgun (Z) |

Önerilen OD = 2'den başlayarak **kesintisiz** sağlanan en yüksek düzey; hiçbiri yoksa OD1.
OD bütün kabul edilmiş eşleşmelerden hesaplanır; `bidr file`'ın kanıt seçimi (ilgililik, kurum
geneli sınırı, sürüm/kopya birleştirme; docs/REPORT_LAYER.md "Kanıt seçimi") yalnız
yayımlanan kanıt listesini sınırlar, OD'yi değiştirmez; her sayılan halka listede en az bir
kanıtla kalır.
Zincir eksikse düşük düzey: P+U+K (Ö yok) → OD3; P+U+Z (K/Ö yok) → OD3.

Bir düzey şu durumda sağlanır: o düzeyin her halkası kanıtlı ya da ölçütte o halkaya ait
yuva yok (**yuvasız**), ve o düzeyde ya da üstünde en az bir halka kanıtlı. Böylece:

- A.1.2 gibi plan/uygulama yuvası olmayan ölçütte K+Ö → OD4 (alt halkalar aranmaz);
- B.2.3 gibi kontrol/önlem yuvası olmayan ölçütte P+U → OD3; OD4 kendiliğinden gelmez,
  gaps.md "şablonda yuvası yok; ölçüt açıklamasına uygun belge gerekir" der.

Tek yumuşatma (komisyon kararı, 2026-11-18): plan halkası eksik ama U/K/Ö var → düzey 2
örtük sağlanır (uygulama tanımlı bir sürecin kanıtıdır), zincir yukarı devam eder ve ölçüt
"plan belgesi önerilir" diye işaretlenir. OD4 kuralı (K ve Ö birlikte) değişmez.

## Halkayı ne sayar (eşleşme → sayılan aşama)

1. **Kod OD'si esas:** decide `od_kabul`'u düşürdüyse (aşama yuva etiketine uymuyor ya da
   model daha düşük OD dedi) aşama da düşer: OD3 → uygula, OD2 → planla, OD4 → kontrol_et
   (temkinli; önlem açık kanıt ister).
2. **Kurum/fakülte geneli belge** (`yonetmelik`, `yonerge`, `senato_karari` türleri,
   `rules.KURUM_GENELI_TURLER`, ya da ince kararın `birim_iliskisi`'si `kurum_geneli` /
   `fakulte_geneli`): kanıt ilkesi `kurum_geneli_duzenleme` gereği yalnız planla. Daha yüksek
   aşama denmişse planla'ya iner, `uygulama_kaniti_eksik` işaretlenir (fakültede ayrıca
   `fakulte_geneli`); ölçütte bu belgeler dışında uygulama kanıtı yoksa gaps.md'de ayrı
   listelenir. İstisna: `birim_iliskisi: ust_birim_bu_birim_hakkinda` olan karar türü
   (`rules.KARAR_TURLERI`: senato kararı) sınırlanmaz: üst birimin bu birimi konu alan kararı
   birimin kanıtıdır (yönetmelik/yönerge türü yine planla). Bölümün kendi usul ve esası
   (`yonerge` türünde, başlığında birimin adı, `kendi`) kurum geneli değildir (aşağıda "Kod
   tarafı savunmalar").
2b. **Kod tarafı savunmalar ve faaliyet kaydı** (aşağıda ayrı bölümler): hariç tür, bilgisiz
   ekran, yürürlükten kaldırılmış düzenleme ve başka birimin maddesi sayılmaz; boş form,
   duyuru/gelecek zaman ve gerçekleşmesi kanıtlanmamış faaliyet planla'ya; katılım kaydı
   izleme, öneri/bilgilendirme/sürüm notu ve izlemeye dayanmayan değişiklik önlem sayılmaz;
   özgün halka bağımsız ve sürekli kanıt ister.
2a. **Birim aitliği** (`birim_iliskisi`, docs/MODEL_LAYER.md): `baska_birim` belgenin
   eşleşmeleri decide'da reddedilir, "Eşleşmeler" sayfasına gelmez; review.xlsx "Başka birime
   ait sayılanlar" sayfasında ve gaps.md "Başka birime ait sayılan belgeler" bölümünde
   gerekçesiyle listelenir; komisyon kararı geri alabilir (aşağıda "Birim ilişkisini geri
   alma"). `belirsiz` belge **insan onaylayana dek sayılmaz** (kör test 2026-11-19: başka
   bölümün anket/tutanakları bu işaretle kanıt sayılıyordu): satır `birim_aitligi_dogrulanmali`
   + `birim_onay_bekliyor` işareti, `birim_onay_bekliyor: true` alanı ve "BİRİM AİTLİĞİ
   DOĞRULANMALI" vurgusu alır, OD'ye katılmaz, yayımlanan kanıt listesine girmez (`bidr file`
   `birim_dogrulanmali` nedeniyle eler). Onay: satırın KARAR'ı `kabul`/`duzelt`
   (`birim_aitligi_onaylandi`) ya da birim sayfasında belgeye ilişki seçmek (`kendi` vb.;
   işaret kalkar). Kullanıcı inceleme yapmadan "devam et" derse de kural geçerlidir: karar
   yoksa sayılmaz. review.xlsx'te bu satırlar "Eşleşmeler"in başındadır (birim, vurgu, KARAR
   hücreleri koyu turuncu) ve belgeler birim sayfasında da listelenir; gaps.md "Birim aitliği
   doğrulanmalı" belge başına onay durumunu yazar. Döngü (aşağıda) onay bekleyen satırı açmaz.
   Eski kayıtta alan yoksa `kendi` (eski `kurum_geneli` bayrağı varsa `kurum_geneli`).
3. **Dönem kuralı** (belge türüne göre; aşağıda): yapı belgesi rapor yılında yürürlükteyse
   sayılır, olay belgesi rapor yılında gerçekleşmiş olmalı; önceki yıl olayı "geçmiş kanıt",
   tarihsiz olay "tarih doğrulanmalı", dönem sonrası belge "dönem sonrası" (hiçbiri sayılmaz).
4. **Düşük güven** (`guven: dusuk`): önerilen OD'ye katılmaz; ayrıca "OD (düşük güven
   dahil)" hesaplanır ve fark varsa not düşülür. Bu, OD'yi doğrulanmamış eşleşmeyle şişirmemek
   içindir. İnceleme kararı `kabul` ya da `duzelt` ise eşleşme doğrulanmış sayılır ve OD'ye
   katılır (insan kararı kuralı aşar; `bidr file` aynı kuralı uygular). Vurgu "düşük güven
   (incelemede onaylandı)" olur.
5. **İnsan kararı** (`review-decisions.jsonl`): `ret` sayılmaz; `duzelt` kullanıcının
   ölçüt/yuva/aşamasını kullanır (kurum geneli ve dönem sınırları uygulanmaz: karar kullanıcının).

## Dönem kuralı (komisyon kararı, 2026-11-18)

BİDR kapsamı rapor yılının bir önceki takvim yılıdır (kılavuz "Kapsam"; `documents.jsonl`
`donem`). Belgenin tarihi o yıla düşmüyor diye kanıt olmaktan çıkmaz; ne sayıldığı belge
türüne bağlıdır. Sınıflar veri olarak `bidr/data/profiles/donem_kurali.yaml`'dadır (her
katalog türü tam bir sınıfta; test denetler). Ayrı dosya, `doc_types.yaml`'a alan değil:
bu bir tanıma kuralı değil komisyon/kurum politikasıdır (`kurum_geneli.yaml` gibi kurum
`BIDR_PROFILES_DIR` ile değiştirir), identify kataloğu ve sürümü değişmez.

| Sınıf | Türler (örnek) | Rapor yılı | Önceki yıl | Tarih yok | Sonraki yıl |
|---|---|---|---|---|---|
| **yapı** | müfredat, ders kataloğu (bilgi paketi), ders bilgi formu, yönerge/yönetmelik, görev dağılımı, iş akışı, stratejik plan | sayılır | sayılır + `guncellik_dogrulanmali` | sayılır + `guncellik_dogrulanmali` | sayılmaz: `donem_sonrasi`; revizyon kanıtı varsa sayılır + `revizyon_donem_sonrasi` |
| **olay** | kurul/komisyon kararı, tutanak, anket sonucu, faaliyet/değerlendirme raporu, yazışma, dönemlik ders kayıtları (ders programı, izlence, açılan dersler) | sayılır | planla sayılır + `guncellik_dogrulanmali`; U/K/Ö/Z sayılmaz: `gecmis_kanit` | sayılmaz: `tarih_dogrulanmali` | sayılmaz: `donem_sonrasi` |
| **karma** | web sayfası, ekran görüntüsü, form, anket formu; katalog dışı tür | aşama belirler: planla → yapı, U/K/Ö/Z → olay | | | |

- **Yapı:** önemli olan rapor yılında yürürlükte olmasıdır. Yürürlükten kalktığı biliniyorsa
  kanıt değildir (kanıt ilkesi `yururlukten_kalkmis`: model `kanit_degil` der, satır gelmez).
  Kod yürürlüğü bilemez: tarih rapor yılında değilse "güncellik doğrulanmalı" (gaps.md
  "Güncelliği doğrulanacak belgeler"); yürürlükte değilse kullanıcı satırı `ret` eder.
- **Yapı, rapor yılından sonra** (kör test 2026-11-19: "Komisyonlar 2026-2027", 2026
  takvimleri bölümün tek yapı kanıtı olmuştu): dönemden sonra yürürlüğe girmiş, o dönemin
  kanıtı değil (`donem_sonrasi`, sayılmaz, yayımlanan listeye girmez). İstisna: tarih bir
  revizyon/değişiklik etiketinden geliyorsa (`tarih_kaynagi`'nda `tarih.revizyon_etiketleri`)
  ya da metinde rapor yılı veya öncesine ait tarih varsa düzenlemenin önceki sürümü dönemde
  yürürlükte olabilir: sayılır, `revizyon_donem_sonrasi` ("revizyon tarihi dönem sonrası;
  dönemdeki sürüm aranmalı"; gaps.md "Revizyon tarihi dönem sonrası olan düzenlemeler").
- **Yapı sürümleri** (identify `surum_grubu`, yalnız yapı sınıfı türler; kör test: ÇAP
  yönergesinin 2014/2017/2018/2026 sürümleri birlikte sayılmıştı): rapor yılında yürürlükte
  olan sürüm seçilir: yılı rapor yılı ya da öncesi olan en yeni sürüm. Daha yeni sürümü rapor
  yılından önce çıkmış sürüm dönemden önce yerini bırakmıştır (`surum_yururlukten_kalkmis`,
  kanıt ilkesi `yururlukten_kalkmis`); rapor yılından sonraki sürüm de kanıt değildir
  (`surum_donem_sonrasi`); ikisi de sayılmaz, yayımlanmaz. Yenisi rapor yılında çıkan önceki
  sürüm dönemin bir kısmında yürürlükteydi: sayılır. Tarihsiz sürüm varsa hangisinin yürürlükte
  olduğu belirlenemez: `surum_dogrulanmali` (tarihli aday sayılır, tarihsiz üye sayılmaz;
  tarihli aday yoksa tarihsizler sayılır); gaps.md "Sürümü doğrulanacak düzenlemeler".
- **Olay, önceki yıl** (eski olay belgesi): uygulama/izleme/önlem/özgün halkalarını kanıtlamaz
  (kör test 2026-11-19: 2024'ten eski 26 satırın 20'si OD'ye girmişti). Plan halkası ise sayılır:
  dönemden önce alınmış ama hâlâ yürürlükte olan usul/karar belgesi (kullanıcı kararı 2026-11-19:
  "belgeler hâlâ uygulamada; her yıl müfredat değişmez"; `donem_kurali.yaml`
  `onceki_olay_plani_sayilir: true`, satır `guncellik_dogrulanmali`; `false` planla dahil hiçbir
  halkayı saymaz). Sayılmayan satırlar gaps.md "Geçmiş kanıtlar (süreklilik)" bölümünde ayrı
  listelenir: OD5'in istediği sistematikliğin ve "bir önceki yıla göre ne değişti" sorusunun
  kanıtı. Yayımlanan kanıt listesinde ölçüt başına en çok `kanit_secimi.yaml`
  `gecmis_kanit_en_fazla` (vars. 1).
- **Olay, tarih yok** (`donem_ici` bilinmiyor): hiçbir aşama sayılmaz, satır tabloda gri ama
  görünür kalır ("tarih doğrulanmalı"; gaps.md "Tarihi doğrulanacak olay belgeleri"; ölçüt
  notu "doğrulanırsa OD x"). Gerekçe: tarihsiz olay rapor yılında da, önce de, sonra da
  olmuş olabilir; saymak OD'yi doğrulanmamış kanıtla şişirir (en ağır hata), satırı gizlemek
  ise kullanıcının tek bakışta düzeltebileceği kanıtı kaybettirir. Kullanıcı tarihi
  doğrularsa satırı `duzelt` + aşama ile sayar (insan kararı dönem kuralını aşar).
- **Karma:** web sayfası hem misyon metni hem haber, form boşken tanım doluyken kayıt
  olabilir; türü değil eşleşmenin aşaması belirler.
- **Belgenin tarihi ve kaynağı** (`donem.doc_time`; satırda `tarih`, `tarih_kaynagi`,
  `tarih_notu`, review.xlsx "tarih · kaynağı"): öncelik (1) metin içi birincil tarih (identify
  `tarih`; kaynak "metin (etiket: …)", "metin (baş bölgede en sık tarih)", "metin (baş bölgedeki
  ilk tarih)", "metin (metindeki ilk tarih)"); (2) akademik dönem (`akademik_donem`; identify
  karar veremediyse dönemsiz "2026-2027" akademik yılı: rapor yılı aralıktaysa içinde, aralık
  sonraysa dönem sonrası); (3) kaynak dosya adı (`inventory.csv` `rel_path`, yalnız dosya adı,
  klasörler değil): zayıf kanıttır, yalnız dışlamada güvenilir: dosya adı rapor yılını
  gösteren olay belgesi yine "tarih doğrulanmalı" (not "tarih yalnız dosya adından"), dönem
  sonrası/önceki yılı gösteren dışlanır. Belgenin dosya sistemi üst verisi (oluşturma/değişiklik
  zamanı) kullanılmaz: kopyalama tarihidir.
- **Olay belgesinde birden çok tarih** (`identify` `tarihler`): olayın tarihi ile belgede geçen
  referans tarihleri ayrılır. Birincil tarih bir etiketten geliyorsa (ör. "Toplantı tarihi:")
  olayın tarihidir; ötekiler referanstır (eylem son tarihi, atıf yapılan karar). Etiketsizse:
  birincil tarih rapor yılında ve belgede yalnız daha eski tarihler varsa olay rapor yılındadır
  (referanslar geçmişe atıf yapar); birincil tarih rapor yılında ama dönem sonrası tarih de
  varsa, ya da birincil tarih önceki yıl ama rapor yılı tarihi de varsa olay tarihi kodla
  ayrılamaz: `tarih_dogrulanmali` (sayılmaz; not hangi tarihlerin çeliştiğini yazar).
  `tarih.olay_tarihi_en_gec` türlerinde (vars. `etkinlik_duyurusu`) olayın tarihi belgedeki en
  geç tarihtir: duyuru yayım tarihini değil etkinlik tarihini taşır (2025 Aralık'ta yayımlanan
  2026 Ocak semineri dönem sonrasıdır).
- **Tarih kaynakları, kör test 2026-11-20** (identify alanları `tarih_araliklari`,
  `yururluk_araligi`, `yil_ifadeleri`, `guncelleme_tarihi`; `bidr/identify/dates.py`):
  - *Başlangıç–bitiş aralıkları* (proje, sözleşme, görevlendirme: "01.03.2025 | 01.03.2027";
    "Bitiş tarihi:" etiketi): bitiş tarihi belgenin dönemini belirlemez. Birincil tarih
    seçiminde kullanılmaz; olay belgesinde ileri bitiş tarihi "dönem sonrası tarih de var"
    belirsizliği doğurmaz. En az 3 çiftli aralık tablosunda (proje listesi) eşi okunamamış ileri
    tarihler de bitiş/OCR kalıntısı sayılır; dönem sonrası BAŞLANGIÇ (2026'da başlayan proje)
    belirsizlik olarak kalır. Etiketsiz birincil tarih önceki yılda/bilinmiyor ama bir aralık
    rapor yılında başlıyorsa olay rapor yılındadır (kaynak "aralık başlangıcı").
  - *Plan yürürlük aralığı* (baş bölgede plan/strateji sözcüğünün yanında 2–10 yıllık
    "2022-2026"; eski kayıtta başlıktan): yapı belgesinde aralık rapor yılını kapsıyorsa
    önceki/bilinmeyen tarih belgeyi dönem içi yapar (hazırlık tarihi değil yürürlük belirler);
    dönem sonrası tarihi aşmaz. Etiketsiz birincil tarih seçimi aralığın 3 yıl öncesinden eski
    anılan tarihleri atlar (kör test: "2022-2026 Stratejik Planı"nın tarihi plandaki "4 Kasım
    2014" kuruluş anmasından okunmuş, kanıt adına "(2014-11-04)" olarak girmişti: dosyalama
    aynı adlı iki numarayı belge tarihiyle ayırır, `bidr/file/run.py`). Program dönemi
    ("Erasmus+ 2021-2027") ve akademik yıl yürürlük aralığı değildir.
  - *Açık yıl ifadesi* ("2025 yılı içerisinde", "2025 yılında"): metinde tam tarih ve akademik
    dönem yoksa tarih kaynağıdır (kaynak "metin (yıl ifadesi: …)"). Rapor yılı geçiyorsa dönem
    içi; yalnız sonraki yıllar geçiyorsa dönem sonrası; yalnız önceki yıllar ("1994 yılında
    kuruldu") belgenin tarihi değildir: bilinmiyor kalır.
  - *Dönem sonrası güncellenmiş sayfa* ("Son güncelleme: 11 Kasım 2026"; damga içerik tarihi
    sayılmaz): içerikte rapor yılını gösteren tarih ya da yıl ifadesi yoksa sayfanın gösterdiği
    hâl (kurul üyeleri, haberler) rapor yılına ait olmayabilir (kör test: A.1.4 kurul yapısı ve
    A.1.5 haberleri 2026 kopyalarından alınmış, 2025 kadrosuyla çelişmişti). Plan halkası
    (tanım) `guncellik_dogrulanmali` + `sayfa_donem_sonrasi` ile sayılır; uygulama ve üstü
    sayılmaz (`tarih_dogrulanmali` + `sayfa_donem_sonrasi`): OD3+ dayanağı olamaz. İçerikte
    rapor yılı tarihi/ifadesi varsa kural devreye girmez.
- **Yıllık olmayan döngüler:** ölçütte sayılan (düşük güvenli olmayan) bir eşleşmenin
  kodla doğrulanmış **alıntısı** bir gözden geçirme döngüsü tanımlıyorsa ("her 4 yılda bir",
  "dört yılda bir", "akreditasyon döngüsünde", "program süresinin sonunda"), son N yılın
  (yıl > dönem − N; N alıntıdaki sayı, yoksa 4, en çok 6; yıllık döngü sayılmaz) önceki yıl
  olayları o ölçütte geçerli halka sayılır (`dongu_halkasi`). Birden çok tanım varsa en kısa
  pencere. Döngü model gerekçesinden değil alıntıdan tanınır (kanıt ilkesi `donem_kurali`
  modelden bu cümleyi alıntılamasını ister). Döngü yoksa `dongu.olcutler`'deki ölçütlerde
  (B.1.5: "yıllık ve program süresi temelli izlemeler", B.1.5/5; A.1.4: "takvim yılı
  temelinde tasarlanmayan diğer kalite döngüleri") gaps.md öneri yazar: "Müfredat gözden
  geçirme döngüsünü tanımlayan bir bölüm kurulu kararı önerilir (ör. her 4 yılda ya da
  akreditasyon döngüsünde); bir kez alınınca her yıl kanıt üretir."
- `documents.jsonl`'de dönem bilgisi yoksa (`bidr identify --period` verilmemiş) kural
  uygulanmaz, uyarı yazılır.

## Eksikler (gaps.md)

Her ölçüt için bir üst düzeye çıkmak için eksik halkalar, o halkaya etiketli yuvaların
metinleri ("OD4 için şu tür belge gerekiyor") ve boş yuvalar (hiç sayılan eşleşmesi olmayan
kanıt yuvaları; dipnotlar hariç). Öncelik sırası:

1. kanıt var ama OD ≤ 2 (uygulama ya da plan halkası eksik, kurum geneli-yalnız dahil):
   en ucuz yükseltme, hakemin ilk soracağı;
2. hiç kanıt yok (OD1);
3. OD3: kontrol/önlem eksik;
4. OD4: özgün eksik.

Grup içinde boş yuva sayısı çok olan önce.

Savunma bölümleri (varsa): gerçekleşmesi kanıtlanmamış faaliyetler (`faaliyetler.json`) ve kodun
düşürdüğü ya da saymadığı eşleşmeler (işarete göre gruplu).

Birim bölümleri (varsa): birim aitliği doğrulanmalı (`belirsiz`), başka birime ait sayılan
belgeler (`baska_birim`, kanıt sayılmadı; tablodaki birim sayfasına yönlendirir; insanın
onayladığı "(insan onayladı)", geri aldığı listeden çıkar), birim ilişkisi komisyonca
değiştirilen belgeler (model → insan değeri ve durum). `audit-olcutler.json` `birim_aitligi`
aynı listeleri ve `insan_karari`'nı taşır.

Dönem bölümleri (varsa): gözden geçirme döngüleri ve döngü önerileri, geçmiş kanıtlar
(süreklilik), dönem sonrası ve yürürlükte olmayan sürümler (kanıt sayılmadı), revizyon tarihi
dönem sonrası olan düzenlemeler, sürümü doğrulanacak düzenlemeler, tarihi doğrulanacak olay
belgeleri (nedeniyle), güncelliği doğrulanacak belgeler.

**Eksik kanıt notu** (`audit-olcutler.json` ölçüt alanı `eksik_kanit_notu`; render şeridi
okur): `null` ya da `{"durum", "nedenler", "metin"}`. Not komisyon içindir: rapora (açıklama
hücrelerine) yazılmaz, gaps.md'de kalır (k3, 2026-11-20).
- `kanitsiz`: ölçütte hiç eşleşme yok (ya da hepsi insanca reddedildi). `metin`: "Eksik kanıt notu: <eksik halkaların gereken metinleri>." (gaps.md)
- `neredeyse_kanitsiz`: eşleşme var ama bölümün bu döneme ait, düşük güvenli olmayan ve
  kurum geneli olmayan **sayılan** kanıtı yok. `nedenler` (birden çok olabilir):
  `yalniz_kurum_geneli`, `yalniz_dusuk_guven`, `yalniz_donem_disi` (geçmiş, dönem sonrası ya da
  yürürlükte olmayan sürüm), `tarihi_dogrulanmamis`, `birim_dogrulanmamis`. `metin`: "Eksik
  kanıt notu: bölümün bu döneme ait doğrudan kanıtı yok (<nedenler>). Gereken: <…>."
- Öteki ölçütlerde `null`. gaps.md "Neredeyse kanıtsız ölçütler (eksik kanıt notu)" bunları
  listeler; ölçüt notlarına "neredeyse kanıtsız: …" eklenir. Ölçüt ayrıca `donem_sonrasi`
  listesini taşır (`satir`, `belge`, `yuva`, `asama`, `yil`, `isaret`).

Öteki aşamaların işaretli bölümleri (`<!-- bidr:<ad> -->` … `<!-- /bidr:<ad> -->`) audit yeniden
yazarken belgedeki sırasıyla korunur (`report.compose_gaps`): ingest (`bidr:ingest`), kanıt seçimi
(`bidr:kanit-secimi`: elenen kurum geneli belgeler, listeye alınmayan diğer belgeler, tek kanıt
sayılan sürümler, sürümü doğrulanacak belgeler), "Bağlantısı olmayan kanıtlar"
(`bidr:baglanti-yok`), kapsam kararı (`bidr:kapsam`) ve sonradan eklenecek her işaretli bölüm.

**Kanıtla cevaplanmayan sorular** (`<!-- bidr:sorular -->`, audit yazar): verify'ın
`soru-kapsami.json`'undan (çalışma alanı kökü; yoksa bölüm yazılmaz) `kanitla_cevaplanmayan`
(ölçüt · soru — cevapsız / uydurma şüphesi (yerler): gerekçe) ve `denetlenmedi` listesi
("Soru kapsamı denetlenmeyen ölçütler"); kullanıcının `cikar` dediği metin listelenmez. verify
audit'ten sonra çalıştığından bölüm `bidr audit`/`audit apply` yeniden çalışınca güncellenir;
yalnız bu bölümü yenilemek için `bidr.audit.report.update_soru_gaps(gaps.md, ws)` (gövdeye dokunmaz;
verify/render şeridi çağırabilir).

## review.xlsx

"Eşleşmeler" sütunları: satır kimliği (`<doc_id>|<yuva>`), belge çalışma adı, tür, birim ilişkisi
(`belirsiz` sarı), dönem içi,
dönem kuralı (sınıf · zaman · işaret, ör. "olay · önceki yıl (2023) · geçmiş kanıt
(süreklilik)"; doğrulama isteyen hücre sarı), ölçüt, yuva ve metni, model aşaması, sayılan aşama, sayılan OD, yuva etiketi (aşama → OD) ve
durumu (öneri/onaylı), vurgu, güven, işaretler, alıntı, gerekçe; kullanıcı sütunları
(mavi): **KARAR** (kabul/ret/duzelt), düzelt: ölçüt/yuva/aşama, yuva etiketi kararı
(onayla/duzelt) ve yeni aşama(lar), NOT; **kanıt adı** (belge sütununun yanında; öneriyle
dolu, düzeltilebilir). Sonda salt okunur "kanıt adı (öneri)" ve "kanıt adı kaynağı"
(insan/model/kural; öncelik insan > model > kural, `bidr/name/resolve.py`). **bağlantı**
(kullanıcı sütunu; öneriyle dolu): raporda kanıt adının bağlanacağı adres; öneri belge
metnindeki yayın adresidir (web çıktısının üst/altbilgisi, `bidr/file/links.py`), yanında salt
okunur "bağlantı (öneri)" ve "bağlantı kaynağı" (insan/belge_metni). "alıntı kaynağı":
`belge` ya da `betimleme` — belge metni `bidr describe` başlığıyla başlıyor ve alıntı betimleme
öncesi metinde (`text_pre_describe/`) yoksa alıntı ajanın görsel betimlemesindendir (sarı,
işaret `betimleme_alintisi`, vurgu "alıntı görsel betimlemeden").

Vurgular: OD4/OD5'e yükselten satırın OD/etiket hücreleri turuncu; yükselten etiket hâlâ
öneri ise koyu turuncu ve "ÖNERİ etiket" yazar. Düşük güven sarı. Sayılmayan satırlar gri (ret,
geçmiş kanıt, tarihsiz ya da dönem sonrası belge, yürürlükteki sürüm olmayan düzenleme, birim
aitliği onay bekleyen). Birim aitliği onay bekleyen satırlar tablonun başındadır. "tarih ·
kaynağı" sütunu (dönem kuralının yanında) belgenin tarihini, kaynağını ve varsa tarih notunu
gösterir.
Sütunlar başlık adıyla okunur; kullanıcı sütun ekleyip sırayı değiştirebilir.

`bidr audit` yeniden çalıştırılınca işlenmiş kararlar (`review-decisions.jsonl`) tabloya geri
yazılır; tabloda olup işlenmemiş kararlar da kaybolmaz (yeni tabloya taşınır, eski tablo
`review.onceki.xlsx`).

**Yeniden bakılmalı (güncelleme, kör test 2026-11-20).** Karar verildiğinde satırın gördüğü durum
— inceleme işaretleri (kararın kendisinden doğanlar hariç: `insan_reddetti`, `insan_duzeltti`,
birim onayı), sayılan aşama ve OD — `audit apply` ile `review-gorulen.jsonl`'e yazılır. Audit yeniden
çalışınca (araç sürümü, yeni belge, identify/decide değişikliği) işlenmiş kararı olan bir satıra yeni
işaret eklendiyse (ör. `tarih_dogrulanmali`, `birim_sayfasi`, `fotograf_mekan`) ya da `kabul`
satırının sayılan aşaması/OD'si değiştiyse karar **korunur ve geçerli kalır** (insan kararı ezilmez),
ama satır "YENİDEN BAK: karardan sonra değişen" sütununda gerekçesiyle (ör. `yeni işaret: birim_sayfasi;
OD 2 → 3`) turuncu vurgulanır ve tablonun başına alınır; `bidr audit` uyarısı ve `bidr status`/`next`
(`audit_tamam`, `ilerleme.yeniden_bak`) sayısını verir. Kullanıcı satıra bakar: karar aynı kalacaksa
"bakıldı (evet)" sütununa `evet` yazar, değilse KARAR/NOT'u değiştirir (değişen karar da bakılmış
sayılır); `bidr audit apply` görülen durumu günceller. `apply` tek başına işareti kaldırmaz. Bu
özellikten önce işlenmiş kararlarda (`review-gorulen.jsonl` yok) görülen durum önceki tablonun
satırından alınır ve yalnız yeni işaret karşılaştırılır (önceki tablo karar işlenmeden üretilmiş
olabilir; aşama/OD karşılaştırması yanıltır); ilk `apply`'dan sonra tam karşılaştırma yapılır.

"Başka birime ait sayılanlar" (birim sayfası): ilk satır kısa açıklama, ikinci satır başlık;
satır = modelin `baska_birim` ya da `belirsiz` dediği, ya da insanın birim kararı verdiği belge
(belirsizde eşleşmeler sütunu onay bekleyen eşleşmeleri gösterir). Sütunlar: belge
kimliği, çalışma adı, kanıt adı, modelin gerekçesi, birim yüzünden reddedilen eşleşmeler
(ölçüt yuva · aşama · OD önerisi: alıntı, 160 karaktere kısaltılmış), durum, kullanıcı
sütunları **insan_birim_iliskisi** (açılır liste: kendi, ust_birim_bu_birim_hakkinda,
fakulte_geneli, kurum_geneli, baska_birim, model; `belirsiz` seçilemez) ve not. Yeniden üretilen
tabloda kayıtlı karar doludur; uygulanmamış birim kararı yeni tabloya taşınır.

## Birim ilişkisini geri alma

Öncelik insan > model (kanıt adı/bağlantıdaki düzenle aynı). `audit apply` birim sayfasını
okur ve `birim-kararlari.jsonl`'e yazar (`kaynak: insan`, `model_iliskisi`, `yeniden_karar`,
not, zaman). Boş hücre önceki insan kararını korur ("Eşleşmeler"deki boş KARAR hücresi gibi);
kararı kaldırıp modelin kararına dönmek için `model` seçilir (`kaldirilan`). Sayfada olmayan
belgenin kararı korunur. Geçersiz değer `birim_gecersiz` (çıkış 1; öteki kararlar işlenir).
`decisions.jsonl` değişmez: audit, file ve name kaydı insan kararıyla görür
(`decide.run.unit_view`; name: geri alınan belge kanıt sayılır, ince kararın `kanit_adi`'sı
varsa o kullanılır, yoksa `bidr name prepare` paketler).

- `baska_birim` dışı değer, modelin reddedilmiş eşleşmesi kayıtlıysa (red nedeni yalnız
  `baska_birim`): eşleşmeler geri yüklenir, `od_kabul` yeniden hesaplanır ve yeni ilişkinin
  kuralı uygulanır (fakülte/kurum geneli → OD2 tavanı, `uygulama_kaniti_eksik`, yalnız P;
  kendi/üst birim → tavan yok); işaret `birim_iliskisi_insan`. Birim kararı değişince tablo
  güncel sayılmaz (`_meta.birim_sha`): `bidr audit` yenilenince satırlar "Eşleşmeler"
  sayfasına gelir ve öteki satırlar gibi kabul/ret/duzelt bekler.
- Eşleşme kaydı yoksa (model kurala uyup eşleşme vermediyse) kayıt `yeniden_karar: true` olur;
  `bidr status/next` ince karar aşamasını bekleyen iş gösterir (`bidr decide prepare --stage
  fine --only <doc_id>`). Paketlenirken insan ilişkisi istemin BİRİM bölümüne "SABİT BİLGİ"
  olarak yazılır; `apply` çıktıdaki alanı insan değerine zorlar (`ince.birim_iliskisi_kaynagi:
  insan`, modelin dediği `birim_iliskisi_model`). Görev sürümü değişmez; insan kararı audit'te
  uygulanan belge "istem değişti" sayılmaz.
- `baska_birim` (onay): belge kanıt dışı kalır, gaps.md'de "(insan onayladı)".
- İlişki ikinci kez değişirse (ör. önce `fakulte_geneli` → yeniden karar, OD2 düşüşü kayda
  yazılır; sonra `kendi`): eski düşüş kayıtta kalır, görünüm kaldıramaz. Kayıt önceki insan
  ilişkisiyle karara bağlandığından `yeniden_karar: true` olur; `bidr status/next` yine
  `bidr decide prepare --stage fine --only <doc_id>` gösterir.
- Ayrı `--out` kullanılırsa sabit birim ilişkisi yeniden karar paketine girmez: `bidr decide`
  (ve `bidr name`) yalnız çalışma alanındaki `birim-kararlari.jsonl`'i okur. Yeniden karar
  gerekiyorsa dosyayı çalışma alanına kopyalayın ya da inceleme klasörü olarak çalışma alanını
  kullanın.

## apply

Tabloyu okur, her satırın kararını doğrular (geçersiz karar: çıkış 1, satır kayda girmez),
`review-decisions.jsonl`'i yazar, `gaps.md` ve `audit-olcutler.json`'u kararlarla yeniden
hesaplar (tabloyu yeniden yazmaz). Yuva etiketi kararları `slot-tags-oneri.yaml`'a toplanır:
yuva, mevcut etiket, önerilen aşama/OD (`durum: onayli`), kaynak satırlar; aynı yuvaya
çelişen öneriler `celiskiler`'e. "kanıt adı" hücresi öneriden farklıysa düzeltme
`kanit-adlari.jsonl`'e (`--out` klasörü) `kaynak: insan` olarak yazılır; ad belgeye aittir
(bir satırda değiştirmek yeter). Aynı belgenin satırlarında farklı adlar ya da kişi adı/unvan/
e-posta içeren ad geçersizdir (`kanit_adi_gecersiz`, çıkış 1; öteki kararlar işlenir).
"bağlantı" hücresi öneriden farklıysa `kanit-baglantilari.jsonl`'e `kaynak: insan` yazılır
(belgeye ait; http(s) olmayan değer ya da bir belgede iki farklı adres geçersiz:
`baglanti_gecersiz`, çıkış 1). Birim sayfası yukarıdaki gibi işlenir; sayfası olmayan eski
tablo sorunsuz okunur (birim kararları değişmez). Paket verisi (`bidr/data/criteria/`) değişmez; öneriyi
işlemek kullanıcı onayıyla ayrı bir adımdır. gaps.md yeniden yazılırken `bidr file`/`render`'ın
"Bağlantısı olmayan kanıtlar" ve `bidr file`'ın "Kanıt seçimi" bölümleri korunur.

## Tamamlanma şartı (`audit_tamam`)

review.xlsx var ve güncel `decisions.jsonl`'den üretilmiş (`_meta.kararlar_sha`); her satırın
geçerli kararı var; tablodaki her karar `review-decisions.jsonl`'de birebir; kanıt adı ve
bağlantı düzeltmeleri ve birim sayfası kararları da işlenmiş (`uygulanmamis_duzeltme` = 0);
birim kararları tablodan sonra değiştiyse tablo yeniden üretilmiş; "yeniden bakılmalı" satır yok
(her biri için `bakıldı` = evet ya da değişen karar, işlenmiş). Aşama `onay: insan`: kararı ajan vermez.

## Faaliyet kayıtları (faaliyet → audit)

Girdi: çalışma alanındaki `faaliyetler.json` (`bidr faaliyet`, docs/MODEL_LAYER.md "Faaliyet
kaydı"). Dosya yoksa davranış faaliyetsiz haliyle aynıdır (eşleşmeler belge belge sayılır;
aşağıdaki "Kod tarafı savunmalar" yine uygulanır). Bağ doc_id üzerindendir
(`faaliyetler[].belgeler[].doc_id`); uygulayan `bidr/audit/savunma.py`.

1. **Zincir faaliyet aşamasına göre.** Belgenin faaliyetteki aşaması PUKÖ halkasına eşlenir
   (`bidr.faaliyet.group.PUKO`: duyuru/plan/duzenleme → planla, gerceklesme/katilim → uygula,
   degerlendirme → kontrol_et, iyilestirme → onlem_al). Eşleşmenin aşaması bundan yüksekse
   düşük olan sayılır, satır `faaliyet_asamasi_uyusmuyor` alır (`diger` sınır koymaz).
2. **Yalnız duyurusu olan faaliyet uygula halkasını sağlamaz.** `yalniz_duyuru: true` ya da
   `durum: gerceklesme_kanitsiz` kaydın belgelerinden gelen "uygula" (ve üstü) eşleşmesi
   planla'ya iner, `gerceklesme_kaniti_yok` işaretlenir; gaps.md "Gerçekleşmesi kanıtlanmamış
   faaliyetler" bölümü (ad, tarih, eksik aşamalar) açar. `gerceklesme_dolayli` (katılım ya da
   değerlendirme var, tutanak/rapor yok) uygula sayılır, vurgu "gerçekleşme belgesi önerilir".
3. **OD4 için aynı faaliyet tercih edilir.** K ve Ö halkaları aynı faaliyetten geliyorsa
   (değerlendirme → iyileştirme) gaps.md "kapalı döngü" der; farklı faaliyetlerden geliyorsa
   OD yine sayılır, not düşülür (iyileştirmenin hangi sonuca dayandığı doğrulanmalı).
4. **Write paketine faaliyet özeti** (uygulandı: `bidr/write/run.py`, görev `write_criterion` v2;
   docs/REPORT_LAYER.md "write"). Ölçüte bağlı her faaliyet için `{ad, tarih, durum,
   asamalar, eksik}` write girdisine girer; yazım kuralı: yalnız `gerceklesme_kanitli` ya da
   `gerceklesme_dolayli` faaliyet için "düzenlenmiştir/gerçekleştirilmiştir" yazılır,
   yalnız duyurulu olan için "planlanmıştır/duyurulmuştur". verify bu kuralı denetler.
5. **Kimlik ve güncellik.** `F001…` kimlikleri bir çalıştırma içinde kararlıdır (tarih, ad
   sırası); audit kayıtla bağı doc_id üzerinden kurar, `_meta`'ya `faaliyetler.json` özeti
   (sha) girer: dosya değişirse tablo güncel sayılmaz.
   `durum: gerceklesme_kanitsiz` kaydın belgelerinden gelen uygula (ve üstü) eşleşmesi planla'ya
   iner, `gerceklesme_kaniti_yok` işaretlenir; gaps.md "Gerçekleşmesi kanıtlanmamış faaliyetler"
   (kimlik, ad, tarih, eksik aşamalar). `gerceklesme_dolayli` uygula sayılır, vurgu
   "gerçekleşme belgesi önerilir".
3. **Kapalı döngü.** Önlem (Ö) satırı, izleme (K) ile aynı belgeden ya da değerlendirme aşaması
   olan aynı faaliyetten geliyorsa ölçüt notu "kapalı döngü"; farklı belgelerden geliyorsa
   (aşağıda K→Ö bağı) "iyileştirme izlemeden ayrı belgede: … doğrulanmalı".
4. **Write girdisi.** `audit-olcutler.json` ölçüt alanı `faaliyetler`: ölçüte bağlı her faaliyet
   için `{id, ad, tarih, durum, yalniz_duyuru, asamalar, eksik}`. Yazım kuralı (write/verify
   şeridinin işi): yalnız `gerceklesme_kanitli` / `gerceklesme_dolayli` faaliyet için
   "düzenlenmiştir/gerçekleştirilmiştir", yalnız duyurulu olan için "planlanmıştır/duyurulmuştur".
5. **Güncellik.** `F001…` kimlikleri bir çalıştırma içinde kararlıdır. review.xlsx `_meta`
   `faaliyet_sha` taşır; `faaliyetler.json` değişirse (ya da sonradan oluşursa) tablo güncel
   sayılmaz (`review_state.guncel`), `bidr audit` yeniden çalıştırılmalı.

### PUKÖ zinciri (belgeler arası açık atıf)

Sorun (Kimya kör testi, 2026-11-20): anket komisyonu kararı (14.01) → bölüm yazısı (27.01, "dış
paydaş görüşleri ve anket komisyonu kararı doğrultusunda hazırlanan …") → Fakülte Kurulu kararı
(03.02, "… 27.01.2025 tarih ve E.… sayılı yazısı görüşüldü", dersler açıldı) gerçek bir
izleme → önlem döngüsüdür; ama eşleşmeler belge belge değerlendirildiği için ara yazı hiçbir
ölçütte sayılmadı (aday ve inceleme aşamasında düştü), karar belgesi de yalnız "uygula" kaldı.
Belgeler arasındaki bağ ancak metindeki göndermeden görülür.

1. **"Dayanır" bağı yalnız açık göndermeden** (`bidr/faaliyet/atif.py`, belirleyici):
   - *sayı*: "GG.AA.YYYY tarih(li) ve <sayı> sayılı …" → başlığında aynı tarih ve aynı evrak
     sayısını (son rakam öbeği) taşıyan belge(ler) ("Sayı : E-…-184506" + belge tarihi ya da
     "Evrak Tarih ve Sayısı: GG.AA.YYYY-E.184506"). Tarih ve sayı birlikte tutmalı.
   - *ad*: "<ad> (kararı | görüşleri | sonuçları | değerlendirmesi …) doğrultusunda / sonucunda /
     sonuçlarına göre / üzerine / uyarınca / istinaden" → adı bu ifadeyle karşılıklı örtüşen (en
     az iki ayırt edici sözcük; "Bölüm", "Toplantısı" sayılmaz) faaliyet kaydı (`faaliyetler.json`).
     Kayıt kaynak belgeden önce ve 180 gün içinde olmalı, böyle **tek** kayıt olmalı; birden çoksa
     bağ kurulmaz, audit uyarısı düşer. Tür sözcüğü olmayan sayım ("Fakülte Kurulu, … ve …
     doğrultusunda") ve çoğul genel anma ("kurulların kararları") bağ kurmaz.
   Bağlar zaman yönlüdür; zincir en çok 4 bağ izlenir. Tahmin (yalnız tarih yakınlığı, konu
   benzerliği) bağ kurmaz.
2. **Önlem halkası** (`bidr/audit/puko.py`, audit sırasında; `faaliyetler.json` dosyası
   değişmez). Ölçüt C'de izleme kanıtı olan belge X (C'deki sayılan, düşük güvenli olmayan satırı
   `kontrol_et`; ya da sayılan satırı olup faaliyet kaydındaki aşaması `degerlendirme`) ve X'e
   zincirle dayanan, türü `…_karari` olan belge Y varsa: Y'nin C'nin önlem yuvasındaki satırı
   `onlem_al`'a çıkar, satır yoksa açılır (`puko_zinciri` işareti; alıntı Y'deki gönderme cümlesi,
   gerekçe zincirin yolu). Önlem yuvası: yalnız `onlem_al` etiketli olan önce, sonra `onlem_al`
   içeren, sonra belirsiz. Ölçütte önlem yuvası yoksa uygulanmaz. Dönem kuralı açılan satıra da
   uygulanır; kod savunmaları uygulanmaz (dayanak metindeki atıftır).
3. **İnsan kararı aşar.** Zincir satırı (`Y|yuva`) review.xlsx'te reddedilirse sayılmaz ve başka
   yuvaya taşınmaz. Modelin Y için aynı yuvadaki eşleşmesi reddedilmişse (başka bir iddia, ör.
   "uygula") sıradaki önlem yuvası denenir.
4. **Çıktı.** `audit-olcutler.json` ölçüt alanı `puko_zinciri`: `[{satir, onlem, izleme,
   ara_belgeler, yol, baglar[{kaynak, hedef, faaliyet, tur, atif}], sayilir}]`; ölçüt notu
   "PUKÖ zinciri: `Y → ara → X` (… ara belgeler kanıt listesine önerilir)". Ara belgeler (ör.
   bölüm yazısı) satır olarak eklenmez: kanıt listesine ve rapor metnine girmeleri write/file
   şeridinin işidir.

## Kod tarafı savunmalar (K27 OD rubriği)

Modelin bilinen yanlışlarını (evalsets/ `naif` kayıtları) belge türü, alıntıdaki ifade, belge
metni (`text/`), birim adı (`config.yaml` `bidr.birim`) ve faaliyet kaydıyla yakalayan
belirleyici denetimler (`bidr/audit/savunma.py`; desenler katlanmış metinde). Her düşürme
satırda işaretlenir, gaps.md "Kodun düşürdüğü ya da saymadığı eşleşmeler" bölümünde listelenir.
Satırın KARAR'ı `kabul` ya da `duzelt` ise metin sezgileri uygulanmaz (insan kararı aşar; düşük
güven kuralı gibi). Hariç tür ve yürürlükten kaldırma `kabul`de de geçerlidir. `haric_tur`,
`bilgisiz_ekran`, `yururlukten_kalkmis` ve `madde_baska_birim` ile sayılmayan belge yayımlanan
kanıt listesine de girmez (`bidr file`, neden işaretin kendisi; gaps.md "Kanıt seçimi").

| İşaret | Koşul | Sonuç |
|---|---|---|
| `haric_tur` | tür `haric_turler.yaml`'da (BİDR raporu/taslağı; geçen yılınki dahil) | sayılmaz |
| `bilgisiz_ekran` | web/ekran/form türünde giriş ekranı (kullanıcı adı/parola + giriş) ya da yalnız kısa bağlantı maddelerinden oluşan sayfa | sayılmaz |
| `yururlukten_kalkmis` | başka bir belgenin "… tarihli … yürürlükten kalkar/kaldırılmıştır" cümlesindeki tarih bu belgenin tarihine eşit (kaldıran belge rapor yılı ya da öncesi) | sayılmaz, dönem dışı listesine girer, yayımlanmaz |
| `madde_baska_birim` | birim adı biliniyor; alıntının bulunduğu madde/gündem başka birimi anıyor, bu birimi anmıyor (madde ilkesi) | sayılmaz |
| `bos_form` | tür `anket_formu`/`form_belgesi`, metinde sonuç (yanıt sayısı, ortalama, %, ondalık puan) yok, aşama U+ | planla |
| `gerceklesme_kaniti_yok` | tür `etkinlik_duyurusu`, ya da alıntıda gelecek zaman ("-acaktır/-ecektir"), ya da faaliyet yalnız duyurulu | planla |
| `uygulama_kaniti_eksik` + `kurum_geneli` | alıntıda bütün birimleri kapsayan ifade ("Fakültemizin bütün bölümlerinde") | planla |
| `katilim_izleme_degil` | kontrol_et alıntısı yalnız katılım/yapılma kaydı (izleme/ölçme sözcüğü yok) | uygula |
| `niyet_onlem_degil` | onlem_al alıntısı öneri/niyet ("önerilmiştir", "önümüzdeki", gelecek zaman) | kontrol_et |
| `bilgilendirme_onlem_degil` | onlem_al alıntısı "bilgisine sunulmuştur / bilgi verilmiştir" | uygula |
| `surum_notu_onlem_degil` | onlem_al alıntısı sürüm notu ("revize edilmiş halidir"), izleme sözcüğü yok | uygula |
| `yonlendirme_onlem_degil` | onlem_al alıntısı yalnız yönlendirme/talep: karardaki "-mesine/-masına" fiillerinin hepsi iletme/bildirme/gönderme ("Başkanlığa iletilmesine karar"), ya da üst yazı/talep ("gereğini arz ederiz") ve değişiklik sözcüğü yok (kanıt ilkesi `iyilestirme_kaniti`) | kontrol_et (izleme sözcüğü varsa), yoksa uygula |
| `birim_iliskisi_kod` | birim adı biliniyor, model `kendi`/`ust_birim…` dedi, metinde birimin adı hiç yok: başka birim adı varsa `belirsiz` (insan onaylayana dek sayılmaz), bütün birimleri kapsayan belge ise (rektörlük, senato, "fakültemizin") `kurum_geneli`/`fakulte_geneli` (OD2 tavanı). Birim sayfasında modelin ilişkisi `birim_iliskisi_model` olarak görünür; insan birim kararı kodu aşar | ilişki değişir |
| `birim_iliskisi_kod` (ters yön) | model `kurum_geneli`/`fakulte_geneli` dedi ama belge birime özgü: (a) baş bölgede (ilk 12 satır) birime hitap ("Örnek Bölüm Başkanlığına") ve belgede başka bölüme hitap yok (dağıtım listesi hitap değildir), (b) üst birim yazısında birime ait kayıt ("Örnek Bölümü:" satırı ve altında içerik; madde ilkesi), ya da (c) baş bölgede (ilk 600 karakter) birimin ders kodu ya da program adı. Belge rektörlük/dekanlık yazısıysa `ust_birim_bu_birim_hakkinda`, değilse `kendi`; decide'ın OD2 tavanı (`uygulama_kaniti_eksik`) kalkar (`kurum_tavani_kaldirildi`), tür tavanı varsa kalır. Satır "birim kodca düzeltildi … doğrulanmalı" vurgusu alır | ilişki değişir |
| `birim_sayfasi` | tür tavanlı belge (yönerge/yönetmelik/senato kararı) birleşik PDF (form feed ile ≥2 sayfa); alıntının sayfasında birimin ders kodu/program adı/adı var, madde yapısı ("MADDE n"), bütün birimleri kapsayan ifade ve başka birim adı yok: o satıra tür tavanı uygulanmaz, decide'ın OD2 tavanı kalkar (ör. kurum yönergesiyle birleşmiş bölüm ders değerlendirme sonucu) | tavan yok |

**Tür tavanı ve bölümün kendi usul belgesi.** `yonerge`/`yonetmelik` türü kurum geneli
sayılır; ama model `kendi` dediyse ve başlıkta (ilk 300 karakter) birimin adı geçiyor, metin
bütün birimleri kapsamıyorsa bölümün kendi usul ve esasıdır: tavan ve `kurum_geneli` işareti
uygulanmaz (`bidr file`'ın kurum geneli sınırına da takılmaz). `senato_karari` her zaman tür
tavanındadır (üst birim istisnası değişmedi). Birim adı yoksa bugünkü tür kuralı.

## Halka bağları ve OD3/OD5 koşulları

Ölçüt düzeyinde, dönem kuralı ve döngüden sonra (`Savunma.criterion`):

- **K→Ö bağı.** Önlem (onlem_al) yalnız bir izleme sonucuna dayanıyorsa sayılır: (a) aynı
  belgede ya da aynı faaliyette izleme var (kapalı döngü), ya da (b) ölçütte tarihi önlemden
  sonra olmayan bir izleme kanıtı var (sayılan, geçmiş kanıt ya da döngü halkası) **ve**
  alıntı, model gerekçesi ya da belge metni bir izleme sonucuna bağ kuruyor ("sonuç", "bulgu",
  "anket", "değerlendirme", "rapor", "yetersiz", "hedefin altında" …). Ölçütte izleme yuvası
  yoksa yalnız (b)'deki bağ aranır. Aksi `onlem_izlemeye_dayanmiyor`: uygula sayılır.
  İstem modelden önlemin gerekçesinde dayandığı sonucu yazmasını ister.
- **Tek seferlik anket** kontrol_et olabilir; OD4 yine K **ve** ona dayanan Ö ister.
  "Kurula bilgi verildi", öneri/niyet ve sürüm notu iyileştirme değildir (yukarıdaki tablo).
- **OD3: bölüm geneline yayılmış uygulama.** Sayılan uygulama tek belgeden geliyorsa ve o
  belge bölüm düzeyi türde değilse (bölüm/anabilim dalı kurulu kararı, müfredat, ders kataloğu,
  ders programı, açılan dersler, görev dağılımı, istatistik tablosu) ölçüt `uygulama_yayilimi:
  "kismi"` ve "OD3 kısmi: tek uygulama örneği" notu alır; OD düşmez. Bölüm kurulu kararı bölüm
  uygulamasıdır (`yaygin`).
- **Fotoğrafın değeri sahnesine bağlıdır** (kullanıcı kararı 2026-11-20). Ölçütün sayılan
  uygulamasının tamamı fotoğrafa dayanıyorsa her satırın sahnesine bakılır: **etkinlik**
  (seminer, konuşma, sunum, toplantı, tören, katılımcılar/öğrenciler, ziyaret…) gerçekleşmeyi
  kanıtlar, satır `uygula` olarak sayılır; **mekân/altyapı/ekipman** (derslik, laboratuvar,
  koridor, tuvalet, cihaz…; "toplantı salonu" gibi mekân adları dahil) süreç uygulaması değildir,
  satır `planla` olarak kalır (`fotograf_mekan`); **belirsiz** sahne destekleyicidir, sayılmaz
  (`fotograf_destekleyici`), OD3 belge ister. Sahne önce alıntıyı içeren `bidr describe` bloğundan
  (yalnız "Görsel türü: fotoğraf"; "Etkinlik" alanı dolu ve duyuru/afiş değil → etkinlik; yoksa
  sahne/betimleme sözcükleri, "Kalabalık: kişi yok" etkinliği dışlar), alıntı bir bloğa ait değilse
  belgenin bütün blokları (hepsi aynıysa), blok yoksa altyazının kendi sözcükleri
  (`bidr/audit/savunma.py` `sahne`). Fotoğraf dayanağı: tür `fotograf`, ya da görselli belgede (gömülü görsel işareti,
  `bidr describe` betimlemesi) ya da betimlemeden alınmış alıntının bir **fotoğraf altyazısı**
  olması (en çok 8 sözcük, yüklemle/noktayla bitmiyor, metinde kendi satırı; ör. tür
  `altyapi_listesi` olan "Bölüm Engelli Tuvaleti" fotoğraf derlemesi). İnceleme `kabul`ü
  eşleşmeyi onaylar, fotoğrafı uygulama kanıtına çevirmez; yalnız `duzelt` (insan aşamayı
  yerleştirdi) aşar. `fotograf` türünde incelemede kabul edilmiş uzun metin alıntısı (afiş/katalog
  yazısı) fotoğraf sayılmaz.
- **OD5: sürdürülebilir ve örnek gösterilebilir.** Özgün (Z) satırı ancak (1) bağımsızsa —
  üst birimin bu birimi konu alan belgesi ya da öz beyan türü olmayan (web sayfası, faaliyet/öz
  değerlendirme raporu, duyuru, BİDR dışında) bir belgede dış tanınma ifadesi ("iyi uygulama",
  ödül, akreditasyon, "seçilmiştir", "yaygınlaştırılmasına") — ve (2) sürekliyse — ölçütte
  geçmiş kanıt/döngü halkası var ya da metin birden çok dönemi anıyor ("2021 yılından bu yana",
  "her yıl", "kesintisiz") — sayılır. Aksi `ozgun_kanitsiz` (sayılmaz). Tek öz-övgü cümlesi ya
  da yalnız web metni OD5 üretmez.
- **Kod önerisi ve nihai düzey ayrı.** `audit-olcutler.json` ölçüt alanları: `od` ve
  `od_kod_onerisi` (kodun önerisi), `od_onayli` (komisyonun onayladığı
  nihai düzey; yoksa `null`), `od_onay` (`{od, not, kod_onerisi, zaman}`). Onay review.xlsx
  "Ölçüt özeti" sayfasındaki **ONAYLANAN OD (insan)** (1-5) ve **OD notu** sütunlarından `bidr
  audit apply` ile `olcut-od-kararlari.jsonl`'e (`kaynak: insan`) yazılır; boş hücre onayı
  kaldırır, geçersiz değer `od_gecersiz` (çıkış 1 değil, öteki kararlar işlenir; önceki onay
  korunur). Uygulanmamış onay `uygulanmamis_duzeltme`'ye sayılır ve yeniden üretilen tabloya
  taşınır. Kod OD5 önerdiyse ve onay yoksa not: "OD5 kod önerisidir: insan onayı bekliyor";
  onay kod önerisinden farklıysa not: "komisyonun onayladığı düzey ODx". Render rubrikte önce
  `od_onayli`'yi, yoksa `od`'yi işaretler; onaysız işaretlenen düzey `bidr denetle`'de
  `od_onay_bekliyor` uyarısıdır (docs/REPORT_LAYER.md "OD onayı").

Bilinen sınırlar: desenler sözcük düzeyindedir (eşanlamlı ifade kaçabilir); birim adı
`config.yaml`'da yoksa birim/madde/usul denetimleri çalışmaz; madde bloğu "Madde N",
"Gündem N", "Karar N" ya da numaralı satırla bölünür.
