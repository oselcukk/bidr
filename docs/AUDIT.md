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
   birimin kanıtıdır (yönetmelik/yönerge türü yine planla).
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
| **olay** | kurul/komisyon kararı, tutanak, anket sonucu, faaliyet/değerlendirme raporu, yazışma, dönemlik ders kayıtları (ders programı, izlence, açılan dersler) | sayılır | hiçbir halka sayılmaz: `gecmis_kanit` | sayılmaz: `tarih_dogrulanmali` | sayılmaz: `donem_sonrasi` |
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
- **Olay, önceki yıl** (eski olay belgesi): hiçbir halkayı kanıtlamaz, planla dahil (kör test
  2026-11-19: 2024'ten eski 26 satırın 20'si OD'ye girmişti; `donem_kurali.yaml`
  `onceki_olay_plani_sayilir: false`; `true` 2026-11-18 kararındaki "usul tanımlayan eski karar
  yapı gibi" davranışına döner). gaps.md "Geçmiş kanıtlar (süreklilik)" bölümünde ayrı
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
okur): `null` ya da `{"durum", "nedenler", "metin"}`.
- `kanitsiz`: ölçütte hiç eşleşme yok (ya da hepsi insanca reddedildi). `metin` render'ın
  bugünkü notuyla aynıdır: "Eksik kanıt notu: <eksik halkaların gereken metinleri>."
- `neredeyse_kanitsiz`: eşleşme var ama bölümün bu döneme ait, düşük güvenli olmayan ve
  kurum geneli olmayan **sayılan** kanıtı yok. `nedenler` (birden çok olabilir):
  `yalniz_kurum_geneli`, `yalniz_dusuk_guven`, `yalniz_donem_disi` (geçmiş, dönem sonrası ya da
  yürürlükte olmayan sürüm), `tarihi_dogrulanmamis`, `birim_dogrulanmamis`. `metin`: "Eksik
  kanıt notu: bölümün bu döneme ait doğrudan kanıtı yok (<nedenler>). Gereken: <…>."
- Öteki ölçütlerde `null`. gaps.md "Neredeyse kanıtsız ölçütler (eksik kanıt notu)" bunları
  listeler; ölçüt notlarına "neredeyse kanıtsız: …" eklenir. Ölçüt ayrıca `donem_sonrasi`
  listesini taşır (`satir`, `belge`, `yuva`, `asama`, `yil`, `isaret`).

`bidr file`'ın işaretli bölümleri audit yeniden yazarken korunur: "Kanıt seçimi"
(`<!-- bidr:kanit-secimi -->`: elenen kurum geneli belgeler, listeye alınmayan diğer belgeler,
tek kanıt sayılan sürümler, sürümü doğrulanacak belgeler) ve "Bağlantısı olmayan kanıtlar".

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
birim kararları tablodan sonra değiştiyse tablo yeniden üretilmiş. Aşama
`onay: insan`: kararı ajan vermez.
