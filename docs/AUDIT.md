# audit: ölçüt OD'si, eksik kanıt raporu, inceleme tablosu

`bidr audit -w WS [--profile P] [--out DIR]` · `bidr audit apply -w WS [--out DIR]`

Belirleyici aşama (model yok). Girdi: `decisions.jsonl` (yalnız ince aşamada **kabul
edilmiş** eşleşmeler: alıntısı kodla doğrulanmış), `documents.jsonl` (tür, dönem içi,
çalışma adı), ölçütler ve yuva etiketleri (`slot-tags-yokak-2025.yaml`). Çalışma alanını
yalnız okur; çıktılar `--out` klasörüne (varsayılan çalışma alanı):

| Dosya | İçerik |
|---|---|
| `review.xlsx` | Sayfa 1 "Eşleşmeler": satır = kabul edilmiş eşleşme; sayfa 2 "Ölçüt özeti"; "Açıklama"; gizli `_meta` |
| `gaps.md` | OD dağılımı, öncelikli eksikler, kurum geneli uyarıları, ölçüt ölçüt zincir ve boş yuvalar |
| `audit-olcutler.json` | Ölçüt özetlerinin makine okunur hali (render aşaması için) |
| `review-decisions.jsonl` | `apply`: kullanıcı kararları (satır başına bir kayıt) |
| `slot-tags-oneri.yaml` | `apply`: yuva etiketi onay/düzeltme ÖNERİLERİ; etiket dosyasını değiştirmez |

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
2. **Kurum geneli düzenleme** (`yonetmelik`, `yonerge`, `senato_karari` türleri,
   `rules.KURUM_GENELI_TURLER`): kanıt ilkesi `kurum_geneli_duzenleme` gereği yalnız planla.
   Daha yüksek aşama denmişse planla'ya iner, `uygulama_kaniti_eksik` işaretlenir; ölçütte
   bu belgeler dışında uygulama kanıtı yoksa gaps.md'de ayrı listelenir.
3. **Dönem kuralı** (belge türüne göre; aşağıda): yapı belgesi yürürlükteyse sayılır, olay
   belgesi rapor yılında gerçekleşmiş olmalı; önceki yıl olayı "geçmiş kanıt", tarihsiz olay
   "tarih doğrulanmalı" (sayılmaz).
4. **Düşük güven** (`guven: dusuk`): önerilen OD'ye katılmaz; ayrıca "OD (düşük güven
   dahil)" hesaplanır ve fark varsa not düşülür. Bu, OD'yi doğrulanmamış eşleşmeyle şişirmemek
   içindir.
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
| **yapı** | müfredat, ders kataloğu (bilgi paketi), ders bilgi formu, yönerge/yönetmelik, görev dağılımı, iş akışı, stratejik plan | sayılır | sayılır + `guncellik_dogrulanmali` | sayılır + `guncellik_dogrulanmali` | sayılır + `guncellik_dogrulanmali` |
| **olay** | kurul/komisyon kararı, tutanak, anket sonucu, faaliyet/değerlendirme raporu, yazışma, dönemlik ders kayıtları (ders programı, izlence, açılan dersler) | sayılır | U/K/Ö sayılmaz: `gecmis_kanit`; planla sayılır + güncellik | sayılmaz: `tarih_dogrulanmali` | sayılmaz: `donem_sonrasi` |
| **karma** | web sayfası, ekran görüntüsü, form, anket formu; katalog dışı tür | aşama belirler: planla → yapı, U/K/Ö/Z → olay | | | |

- **Yapı:** önemli olan rapor yılında yürürlükte olmasıdır. Yürürlükten kalktığı biliniyorsa
  kanıt değildir (kanıt ilkesi `yururlukten_kalkmis`: model `kanit_degil` der, satır gelmez).
  Kod yürürlüğü bilemez: tarih rapor yılında değilse "güncellik doğrulanmalı" (gaps.md
  "Güncelliği doğrulanacak belgeler"); yürürlükte değilse kullanıcı satırı `ret` eder.
- **Olay, önceki yıl:** o yılın U/K/Ö halkası değildir; gaps.md "Geçmiş kanıtlar
  (süreklilik)" bölümünde ayrı listelenir: OD5'in istediği sistematikliğin ve "bir önceki
  yıla göre ne değişti" sorusunun kanıtı. Önceki yıl olayının **planla** eşleşmesi (usul
  tanımlayan karar) yapı gibi sayılır, güncellik işaretlenir.
- **Olay, tarih yok** (`donem_ici` bilinmiyor): hiçbir aşama sayılmaz, satır tabloda gri ama
  görünür kalır ("tarih doğrulanmalı"; gaps.md "Tarihi doğrulanacak olay belgeleri"; ölçüt
  notu "doğrulanırsa OD x"). Gerekçe: tarihsiz olay rapor yılında da, önce de, sonra da
  olmuş olabilir; saymak OD'yi doğrulanmamış kanıtla şişirir (en ağır hata), satırı gizlemek
  ise kullanıcının tek bakışta düzeltebileceği kanıtı kaybettirir. Kullanıcı tarihi
  doğrularsa satırı `duzelt` + aşama ile sayar (insan kararı dönem kuralını aşar).
- **Karma:** web sayfası hem misyon metni hem haber, form boşken tanım doluyken kayıt
  olabilir; türü değil eşleşmenin aşaması belirler.
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

Dönem bölümleri (varsa): gözden geçirme döngüleri ve döngü önerileri, geçmiş kanıtlar
(süreklilik), tarihi doğrulanacak olay belgeleri, güncelliği doğrulanacak belgeler.

## review.xlsx

"Eşleşmeler" sütunları: satır kimliği (`<doc_id>|<yuva>`), belge çalışma adı, tür, dönem içi,
dönem kuralı (sınıf · zaman · işaret, ör. "olay · önceki yıl (2023) · geçmiş kanıt
(süreklilik)"; doğrulama isteyen hücre sarı), ölçüt, yuva ve metni, model aşaması, sayılan aşama, sayılan OD, yuva etiketi (aşama → OD) ve
durumu (öneri/onaylı), vurgu, güven, işaretler, alıntı, gerekçe; kullanıcı sütunları
(mavi): **KARAR** (kabul/ret/duzelt), düzelt: ölçüt/yuva/aşama, yuva etiketi kararı
(onayla/duzelt) ve yeni aşama(lar), NOT.

Vurgular: OD4/OD5'e yükselten satırın OD/etiket hücreleri turuncu; yükselten etiket hâlâ
öneri ise koyu turuncu ve "ÖNERİ etiket" yazar. Düşük güven sarı. Sayılmayan satırlar gri (ret, geçmiş kanıt, tarihsiz ya da dönem sonrası olay).
Sütunlar başlık adıyla okunur; kullanıcı sütun ekleyip sırayı değiştirebilir.

`bidr audit` yeniden çalıştırılınca işlenmiş kararlar (`review-decisions.jsonl`) tabloya geri
yazılır; tabloda olup işlenmemiş kararlar da kaybolmaz (yeni tabloya taşınır, eski tablo
`review.onceki.xlsx`).

## apply

Tabloyu okur, her satırın kararını doğrular (geçersiz karar: çıkış 1, satır kayda girmez),
`review-decisions.jsonl`'i yazar, `gaps.md` ve `audit-olcutler.json`'u kararlarla yeniden
hesaplar (tabloyu yeniden yazmaz). Yuva etiketi kararları `slot-tags-oneri.yaml`'a toplanır:
yuva, mevcut etiket, önerilen aşama/OD (`durum: onayli`), kaynak satırlar; aynı yuvaya
çelişen öneriler `celiskiler`'e. Paket verisi (`bidr/data/criteria/`) değişmez; öneriyi
işlemek kullanıcı onayıyla ayrı bir adımdır.

## Tamamlanma şartı (`audit_tamam`)

review.xlsx var ve güncel `decisions.jsonl`'den üretilmiş (`_meta.kararlar_sha`); her satırın
geçerli kararı var; tablodaki her karar `review-decisions.jsonl`'de birebir. Aşama
`onay: insan`: kararı ajan vermez.
