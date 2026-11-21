# Rapor katmanı (name → file → write → verify → yonler → render → denetle → teslim) — arayüz sözleşmesi

Sahibi: şef. Aşamalar `bidr/data/pipeline.yaml`'da; tamamlanma denetimleri
`bidr/pipeline/checks.py`'de (`name_tamam`, `file_tamam`, `write_tamam`, `verify_tamam`,
`yonler_tamam`, `render_tamam`, `denetle_tamam`, `teslim_tamam`). Her komut önkoşulu bitmeden çıkış kodu 3 ile durur.

## Girdi: onaylı eşleşmeler
`decisions.jsonl` içindeki kabul edilmiş eşleşmeler; varsa `review-decisions.jsonl`
(audit apply) kararları üstündür: `ret` olan eşleşme düşer, `duzelt` olan düzeltilmiş
ölçüt/yuva/aşamayla girer. Düşük güvenli eşleşme önerilen OD'ye katılmaz; inceleme kararı
(`kabul`/`duzelt`) bunu kaldırır (insan kararı kuralı aşar; audit ve file aynı kural).
Ölçüt düzeyi OD: `audit-olcutler.json` (audit çıktısı).

### Eksik kanıt notu (`audit-olcutler.json` `olcutler[].eksik_kanit_notu`)
Audit üretir (docs/AUDIT.md "Eksik kanıt notu"); render okur. `null` ya da
`{"durum": "kanitsiz" | "neredeyse_kanitsiz", "nedenler": [...], "metin": "Eksik kanıt notu: …"}`.
**Not komisyon içindir, rapor metnine girmez** (kör test 2026-11-20: "Eksik kanıt notu: … Gereken: …"
Açıklamalar'a sızdı). Not gaps.md'de ("Neredeyse kanıtsız ölçütler" ve "Ölçüt ölçüt") ve review.xlsx'te
kalır; metni olmayan ölçütün Açıklamalar hücresinde yalnız "Bu ölçüt için bu dönemde kanıt
bulunamamıştır." yazar. `--eksik-notu-yok` eski seçenektir, etkisizdir. Metni olup notu olan ölçütler
`.bidr-render.json` `eksik_notlu_metin` (bilgi).

### Aracın iç dili (`bidr/write/ic_dil.py`)
"Eksik kanıt notu", "Gereken:", "OD'ye sayılmamıştır", "olgunluk düzeyine sayılmış", "eşleşmiş",
"uygulama halkası", "olgunluk değerlendirmesinde … esas alındığından", alt çizgili işaretler
(`kurum_geneli`), araç dosya adları. Üç denetim aynı listeyi kullanır: ölçüt metni (`write apply`,
`verify` kod denetimi: `ic_dil`), alan maddeleri (`yonler apply`, `verify`: `ic_dil`) ve son çıktı
(`bidr denetle`: KRİTİK `ic_dil`). Yazım istemleri iç terim yerine sade karşılık verir (yonler
bulguları: "birimin bu dönemdeki uygulamasını gösteren belge yok"). Kanıt yönetimi kararı da iç dildir
(kör test 2026-11-20, Kimya A.1.5/B.1.6): "… dönem sonrasına ait olduğundan", "tarihi belgede
görülmediğinden", "bu dönemin kanıtı olarak gösterilememektedir", "kanıt olarak sayılmamıştır" —
gelişmeye açık yön bölümün eksiğini söyler, aracın bir belgeyi neden saymadığını değil.


## Kanıt adı (`ad`, `ad_kaynagi`) — öncelik insan > model parça adı > model > kural
- `insan`: review.xlsx "kanıt adı" düzeltmesi (`bidr audit apply` → `kanit-adlari.jsonl`,
  inceleme klasörüne).
- `model`: `bidr name prepare|apply` (ajan; isteğe bağlı aşama `name`, audit'ten önce) ya da
  ince kararın `kanit_adi`'sı (classify_fine v7). `name` uygunluğu insan birim kararıyla
  belirlenir (`birim-kararlari.jsonl`, audit/file ile aynı görünüm): geri alınan belge kanıttır;
  ince kararın kabul edilmiş `kanit_adi`'sı olan belge paketlenmez.
- `kural`: identify başlığı, yoksa tür etiketi (`bidr/file/naming.py`).
- `model_parca`: derleme belgede (birleştirilmiş PDF) yuva başına parça adı
  (`kanit-adlari.jsonl` model kaydının `parca_adlari`'sı, `name_evidence` v3). Kalem (ölçüt ×
  belge) yuvalarından karar sırasıyla ilkinin parça adını alır; aynı belgenin farklı parçaları
  farklı ölçütlerde farklı dosya adı alır, aynı parça tek ad (apply süzer). Apply parça adını
  yalnız derleme kanıtı olan belgede tutar (sayfa başlarında birden çok doküman kodu ya da belge
  adı bazı alıntıların çevresinde tutmuyor). İnsan adı varsa parça adı kullanılmaz. Model adı
  olan derlemeleri parça adı için yeniden paketlemek: `bidr name prepare --parca`.
Her ad yeniden denetlenir (kişi adı/unvan/e-posta yok); tutmayan kaynak atlanır. Model adının
belgede dayanağı (`bidr/name/ground.py`) dizinin `isaretler` sütununa geçer: `ad_dogrulanmali`
(adın türü/birimi/niteliği/sayısı belgede yok), `ad_parca_uyumsuz` (adın türü/konusu kalemin bir
alıntısının çevresinde yok: derlemenin başka parçası; parça adlı yuvada parça adıyla denetlenir),
`parca_adi_coklu` (tek dosyadaki yuvalar farklı parça adlarına düşüyor). İnsan adı denetlenmez.
config.yaml `rapor.kanit_adi_modeli: false` `name` aşamasını atlar.

## Kanıt bağlantısı (`baglanti`, `baglanti_kaynagi`) — öncelik insan > belge metni > klasör
- `insan`: review.xlsx "bağlantı" sütunu (`bidr audit apply` → `kanit-baglantilari.jsonl`,
  `kaynak: insan`; belgeye ait, http(s)).
- `belge_metni`: kamuya açık belge yayımlandığı adrese bağlanır. Adres belge metninden: web
  çıktısının üst/altbilgisi (sayfanın ilk/son iki satırı) ya da birden çok sayfada tek başına
  satır olarak yinelenen URL; gövdedeki (ya da bir kez tek başına geçen) URL yalnız
  `rapor.yayin_alan_adlari` listesindeki alan adındaysa (alt alan adları dahil). Ana sayfa
  adresi (yolsuz; kurum yazısı altbilgisi) sayılmaz. Metinden okunan adres OCR'dan gelebilir:
  şüpheli adres (`links.url_issue`: alan adı biçimi — "Wwww." —, bilinmeyen üst alan adı — ".con" —,
  OCR yer tutucusu — "[okunamadı" —, kesik yol — satırda boşlukla bölünmüş "…/d isplay.aspx",
  "dno=KİM 197&…", tireyle biten —, oturum gerektiren posta/giriş sayfası) bağlantı olmaz; kanıt
  `baglanti_supheli` işareti alır, gaps.md'nin "Doğrulanmalı" alt bölümünde adres ve nedeniyle
  listelenir (kör test 2026-11-20).
- `klasor`: yayımlanmamış belge; kanıt klasörü kullanıcı tarafından yüklendikten sonra
  `rapor.kanit_kok_baglanti` + `evidence/`'e göre göreli yol (her parça yüzde kodlu). bidr yüklemez.
Bağlantısı olmayan kanıtlar `gaps.md`'nin "Bağlantısı olmayan kanıtlar" bölümünde
(`<!-- bidr:baglanti-yok -->` işaretleyicileri arasında; file ve render yeniler, audit korur).

## file → `evidence-index.csv` + `evidence/`
Sözleşme sütunları: `kanit_no` (ölçüt içinde sıra + OD, kılavuz gösterimi: `1_OD3`),
`olcut`, `od`, `ad` (insan okur kanıt adı), `dosya` (evidence/'e göre göreli yol), `doc_id`,
`sayfalar` (kaynak dosyadan alınan sayfalar; boş = dosyanın tamamı), `yuvalar`, `alintilar` (JSON liste).

**Kanıt dosyası tamdır** (kalite komisyonu kararı 2026-11-21). Kanıt alıntı sayfasına göre
kesilmez: dosya olduğu gibi kopyalanır. Gerekçe: gerçek raporda 133 kanıtın 106'sı alıntı
sayfasına kesilmiş, web sayfası PDF'lerinden "1/3" gibi tek sayfalar kalmıştı; okur belgeyi
bütün olarak görmeli. Alıntı sayfasına kesme seçeneği kaldırıldı (isteğe bağlı olarak da yok:
belgeyi yarım gösteren çıktı üretmemeli; birleşik dosyanın meşru ihtiyacı aşağıdaki parça kuralıyla
karşılanır). Tek istisna **birleşik dosya**: tek PDF'e birden çok ayrı belge taranmışsa (identify
`documents.jsonl` `parcalar`) her belge kendi sayfalarının TAMAMIYLA kanıttır; `sayfalar` o
belgenin sayfa aralığıdır, işaret `birlesik_dosyadan_ayrildi`. Bir belge hiçbir zaman yarım
kesilmez: parça sınırı yalnız güvenilir kaynaktan (`sinir: kod` sayfa başındaki doküman kodu
değişti, `sinir: baslik` tarihi farklı resmî üst bilgi) gelirse kesilir. ingest'in sezgisel sınırı
(`coklu_belge_suphesi`: "konu ve başlık değişti", "sayfa no 1'e döndü") kesmez: o sınırın iki yanı
aynı belge sayılır (gerçek veride bu sınırlar imza sayfasını, kararın ekli başvuru/transkriptlerini,
tutanağın gündemini ayırıyordu). Alıntıların düştüğü parçalar bu yüzden komşularıyla birleşir;
sonuç dosyanın tamamıysa, alıntının parçası bulunamıyorsa ya da PDF ile metnin sayfa sayısı
tutmuyorsa tam dosya kopyalanır ve satır `parca_araligi_belirsiz_tum_dosya` (ya da
`sayfa_sayisi_uyusmuyor_tum_dosya`) işareti alır. Model parça adları (`split_parts`) kalemi ayrı
numaralara bölse de her numaranın dosyası bu kurala uyar (parça aralığı bilinmiyorsa iki numara da
tam dosyadır, işaretli). `bidr file --tum-belge` birleşik dosyayı da bölmez. Manifest `kesim`
(`belge` | `tum`) alanı olmayan eski kanıt klasörü (alıntı sayfasına kesilmiş) güncel sayılmaz:
`file_tamam` yeniden dosyalatır. Maskeleme ve teslim dosya dosya çalışır; `sayfalar` yalnız
bilgidir (maskeli dizine aynen geçer).
Ek sütunlar: `inceleme`, `kopyalar`, `kaynak`, `isaretler`, `ad_kaynagi` (insan|model_parca|model|kural),
`baglanti` (raporda kanıt adının adresi; boş olabilir), `baglanti_kaynagi`
(insan|belge_metni|klasor|boş).
Bir belge bir ölçütte bir kez numaralanır; farklı ölçütlerde ayrı numara alır. **Numara ve kod
OD'si** (`bidr/file/naming.py`): kod OD'si `evidence_od(audit satırları, ölçüt OD'si)` — kodun
düşüşleri yansır (kurum geneli → planla → OD2; `od_kabul` düşüşü), ölçüt OD'sine sayılmayan kanıt
(dönem kuralı, düşük güven) ölçütün önerilen OD'sinin üstünü göstermez, modelin ham OD'si
kullanılmaz. Ölçüt OD'sinin üstündeki düzey yalnız o düzey audit zincirinde kurulmuşsa gösterilir
(OD4: izleme VE iyileştirme halkası kanıtlı; kılavuz örneği metin OD2 / kanıt OD4 böyle korunur);
yalnız izleme olan ölçütte "OD4" etiketi ölçüt OD'sine iner ("iyileştirme kanıtı yok" bulgusuyla
çelişmesin). Aynı kaynak (aynı içerik ya da aynı `surum_grubu`; parça grupları, OCR'lı tarama
kopyaları ve kontrollü belgenin sayfaları dahil — bkz. `bidr/identify/versions.py`) ya da ölçüt
içinde kapsanan kopya (`select.merge_contained`, `kaynak_grubu`) bir ölçütte
seçimde ayrı tutulsa da (farklı dönem verisi) tek numara ve tek OD alır (`number_sources`): satırlar
aynı `kanit_no`, aynı `ad` (grubun ilk üyesinin) ve aynı `baglanti`yı (öncelik insan > belge metni >
klasör) taşır — write'ın kanıt listesi ve render'ın (ölçüt, kanit_no) bağlantı haritası tek değer
görür — ama her üye ayrı dosyadır (`[n-ODk]. Ad (tarih).uzantı`, işaret
`ayni_kaynak_tek_numara`; biçim denetçisi bunu uyarı değil bilgi olarak `ayni_numarali_kopyalar` altında listeler). Dosya adı
klasörde büyük/küçük harf duyarsız tekildir: çakışmada kısa kimlik eklenir, hiçbir belge ötekinin
üstüne yazılmaz. Arşiv/e-posta üyesi kanıtlanırken üyenin kendisi kopyalanır. `kopyalar`:
bu satırın temsil ettiği öteki belgeler (mükerrer metin ve tek kanıt sayılan sürümler).
Ek dosya `evidence-secim.json`: seçilenler (neden), elenenler (neden), sürüm birleştirmeleri,
metin atıflarının belge eşlemesi ve ayarlar.
**Metin adları dizinden:** `texts/<ölçüt>.json` `kanitlar[].ad/dosya` dizinin kopyasıdır; `bidr file`
(çıktı çalışma alanıysa) girdisi güncel (`girdi_sha`: kanıt no + doc_id + OD aynı) metinlerde bu
alanları dizinle eşitler (`sync_text_names`; metin, durum ve doğrulama değişmez). Kör test
2026-11-20: metin adlandırmadan önce yazıldığı için rapor, dizinde ve dosya adında doğru olan parça
adı yerine birleşik PDF'in ilk parçasının adını basıyordu (Mat B.4.1, C.2.1; Kimya C.1.1, C.2.1).
**Metin atıfları yeniden dosyalamada** (`bidr/file/renumber.py`): numaralar değişirse metinler
eskir (`write_tamam`, `girdi_sha`). Çıktı çalışma alanıysa `bidr file`, girdisi önceki dizinle
tutan metinde değişiklik yalnız numaralamadaysa — yeni dizindeki her numaranın belgeleri ve kod
OD'si önceki dizinde tek numarayla aynı (yeni kanıt yok), atıf yapılan her kanıt duruyor — atıfları
kodla günceller: cümleler değişmez; `[n_ODk]`, `atiflar`, `kanitlar`, `girdi_sha` güncellenir;
`numara_haritasi` (şimdiki → yazıldığı atıf) `text_sha`'yı koruduğu için doğrulama ve yönler
eskimez; değişiklik `yeniden_numaralama` günlüğüne yazılır. Yeni kanıt eklendiyse, atıf yapılan
kanıt çıktıysa/bölündüyse ya da kod OD'si değiştiyse metin yeniden yazılır (`bidr file` çıktısı
`metin_yeniden_yazilacak`, `bidr next` write aşamasında "N ölçütün metni eski"). write'ın kaynak
yolları (`work/write/kaynaklar.json`) çalışma alanına göreli kaydedilir: kopyalanan çalışma alanı
asıl alanın dizinini okumaz (gerçek veri 2026-11-21: kopyada `next` bu yüzden eski metni görmedi).

### Kanıt seçimi (`bidr/file/select.py`)
Eşleşme kümesi audit'le aynıdır ve audit OD'si bütün kabul edilmiş eşleşmelerden hesaplanır;
seçim yalnız yayımlanan listeyi (`evidence-index.csv`, `evidence/`) belirler. Gerekçe: karışık
klasörde ince karar yüzlerce eşleşme kabul eder; kurum geneli iş akışı/form/yönergeler ve aynı
belgenin sürümleri listeyi şişirir. Ölçüt ölçüt iki adım:

1. **Sürüm ve kopya.** Birebir kopya (`dup_of`) ve mükerrer metin (decide `mukerrer`) zaten tek
   kanıttır. identify'ın `surum_grubu`'ndaki belgeler (metin benzerliği) de tek kanıt sayılır;
   temsilci en yüksek OD'li, sonra en güncel (`tarih`), sonra en eksiksiz (en uzun metin).
   Ayrı kalır: farklı döneme ait veri (baş bölgedeki çeyrek, ay-yıl, "YYYY yılı" işaretleri ya da
   `akademik_donem` ayrık; işaret yoksa tarihleri farklı yıllarda) ve boş şablon ↔ dolu form
   (kanıt ilkesi `bos_form_zinciri`: yalnız planla olan ↔ uygula/üstü olan, ya da boşluklu
   ↔ dolu metin). Aynı parça grubundaki (ingest `parca_grubu`) belgelerde bu kıyas atlanır: tek
   kaynaktır (neden `parca_grubu`). Dönem işareti yok, tarih aynı değil ve sayısal içerik farklıysa emin
   olunamaz: tek sayılır, satır `surum_belirsiz` işaretlenir, gaps.md "Sürümü doğrulanacak
   belgeler"de listelenir; komisyon üyenin satırını `duzelt` ederse (yuva aynı kalabilir) ayrı
   kanıt kalır. Temsilci satırı `surum_temsilcisi` işareti alır.
   **Kopyalar** (kör test 2026-11-20: aynı yazının 5 taraması 5 numara almıştı): identify sürüm
   grubuna OCR'a dayanıklı iki bağ ekler — okunur metin pencerelerinin karakter parçacıklarında iki
   yönde yüksek kapsama (şablon parçacıkları derlem sıklığıyla ayıklanır; birincil tarih aynı, tür
   ve baş bölge kimlikleri — tarih, ders kodu, sayı, doküman no — uyumlu, kardeş kalıp değil) ve
   kontrollü belge imzası (doküman no + revizyon; form numarası değil). Kopya çiftinde modelin
   farklı aşama vermesi ayırmaz (neden `kopya`). Ölçüt içinde **kapsanan kopya**: kalemin şablon
   dışı metninin ≥ %90'ı aynı tarihli başka kalemde ve bu ölçütteki bütün alıntıları da oradaysa
   kapsayan temsilci olur (neden `kapsanan_kopya`); atıflı kalem listede kalır ama numarayı paylaşır.
   Farklı tarihli toplantı/dönem belgesi bu yollarla birleşmez (K20).
2. **İlgililik.** (a) write sonrası metinde atıf yapılan kanıt her zaman girer; sınır yüzünden
   düşmez ama sınırdan yer tutar
   (atıf `texts/<ölçüt>.json`'dan; numara önceki dizinle, dizin değiştiyse `evidence-secim.json`
   atıf eşlemesiyle belgeye bağlanır). (b) Atıfsız kanıt yalnız doğrudan ilgiliyse girer: güven
   ≥ `en_dusuk_guven` ve sayılan eşleşmelerinden en az biri `dolayli_isaretler`'den
   (`asama_yuva_etiketine_uymuyor`, `asama_dusuruldu`, `birim_aitligi_dogrulanmali`) birini
   taşımıyor; ölçüt başına `olcut_basina_en_fazla` (sıra: OD'ye sayılan önce, sonra OD, güven,
   tarih). (d) Bu dönemin kanıtı olmayan belge (audit `donem_sonrasi`,
   `surum_yururlukten_kalkmis`, `surum_donem_sonrasi`: dönem sonrası olay/düzenleme,
   yürürlükteki sürüm olmayan düzenleme; neden `donem_sonrasi`), audit savunmasının kanıt
   saymadığı belge (`select.KANIT_DEGIL`: `haric_tur`, `yururlukten_kalkmis`, `bilgisiz_ekran`,
   `madde_baska_birim`; neden işaretin kendisi; insan `kabul`ü hariç tür ve yürürlükten kaldırmayı
   aşmaz) ve birim aitliği insanca onaylanmamış belge (audit `birim_onay_bekliyor`; neden
   `birim_dogrulanmali`) hiç girmez:
   atıf da zincir de aşmaz (insan `duzelt`i audit'te kuralı kaldırır, satır sayılır). Geçmiş
   kanıt (önceki yıl olayı, OD'ye sayılmaz) ölçüt başına en çok `gecmis_kanit_en_fazla`
   (neden `gecmis_siniri`). (c) Kurum geneli düzenleme (audit `kurum_geneli` işareti) bir ölçütte en çok
   `kurum_geneli_en_fazla`; madde alıntısı olan önce; kalanlar gaps.md "Elenen kurum geneli
   belgeler". İnceleme `duzelt`i (insan yerleştirmesi) sınır yüzünden düşmez; `kabul` güven ve
   dolaylılık eşiğini aşar ama sınırlara tabidir (`audit_tamam` her satıra karar istediğinden
   toplu `kabul` seçimi kapatmamalı). Audit'in saydığı her halka (P/U/K/Ö/Z) listede en az bir
   kanıtla kalır: seçilmemişse en iyi aday sınırlara rağmen girer (`zincir_icin_secildi`), yani
   yayımlanan liste audit OD'sini destekler.

Elenen her belge nedeniyle gaps.md'nin `<!-- bidr:kanit-secimi -->` bölümünde (file yazar,
audit korur) ve `evidence-secim.json`'da görünür. Ayarlar `bidr/data/profiles/kanit_secimi.yaml`
(kurum `BIDR_PROFILES_DIR` ile değiştirir), çalışma alanı config.yaml `rapor.kanit_secimi`
(anahtar anahtar üstüne yazar); varsayılan (2026-11-19): ölçüt başına 10 atıfsız kanıt, kurum
geneli 3, geçmiş kanıt 1, en düşük güven `orta`, sürüm birleştirme açık. Metinde atıf yapılan
kanıt sınırdan yer tutar ama sınır yüzünden düşmez: write sonrası yeniden dosyalama listeyi
büyütmez. Gerçek veri 2026-11-21: atıf sınıra sayılmadığı için write sonrası `bidr file`
üst sınırla elenmiş 16 kanıtı geri aldı (133 → 149; kesimle ilgisi yok), üç ölçütte 30 numara
başka belgeye kaydı.

write sonrası (`texts/` var) gaps.md "Kanıt seçimi" bölümü ölçüt başına "Listede olup metinde atıf
almayan kanıtlar" alt listesini de yazar: yayımlanan ama metinde atıf almamış kanıt,
değerlendirici açısından açıklanmamış kanıttır (metinde kullanın ya da satırı `ret` edin). Ayar değişince `file_tamam` yeniden dosyalama ister
(manifest `secim_sha`).
`evidence/.bidr-evidence.json` girdilerin özetini tutar (kararlar, inceleme, adlar,
bağlantılar ve `rapor:` bağlantı ayarları); biri değişince `file_tamam` yeniden dosyalama ister.

## write → `texts/<olcut>.json`
```json
{"olcut": "B.1.1", "od_onerisi": 3, "durum": "taslak|dogrulandi|reddedildi", "tur": 0,
 "girdi_sha": "…", "paragraflar": [{"metin": "… uygulanmaktadır [1_OD3].", "atiflar": ["1_OD3"]}],
 "kanitlar": [{"no": "1_OD3", "ad": "…", "dosya": "…"}],
 "eksikler": ["…"], "onceki_yila_gore": "…", "onceki_ret": ["…"],
 "kaynak": {"model": "…", "gorev_surumu": "…", "istem_sha": "…", "temel_istem_sha": "…"},
 "insan_karari": "cikar"}
```
Yazım paketinin girdileri ayrıca `faaliyetler` (görev `write_criterion` v2): ölçütün kanıtlarının
bağlı olduğu faaliyet kayıtları (`faaliyetler.json`: ad, tarih, aşama → bu ölçütün kanıt no'su,
"YALNIZ DUYURU" işareti, eksik aşamalar; `meta.faaliyetler`). İstem kuralı 7: "düzenlenmiştir/
gerçekleştirilmiştir" yalnız gerçekleşmesi kanıtlı faaliyet için ve gerçekleşme kanıtına atıfla;
yalnız duyurulu faaliyet için "duyurulmuştur/planlanmıştır". `verify_text` istemi (kural 6) aynı
kuralı denetler: yalnız duyuruya dayanan "düzenlendi" iddiası `kismen`. **v1 → v2:** görevin eski
sürümüyle yazılmış metin, `girdi_sha`'sı güncelse geçerli kalır (`write prepare` yeniden paketlemez,
`eski_surum` listeler; `write_tamam` uyarı verir); yeni kuralla yazmak `--only`/`--redo` ile.
**v3 (kör test 2026-11-20, kanıt içeriğinin eksik aktarımı):** her kanıtın altında, alıntı bağlamı
dışında kalan "dönem içi bilgi" (belgede rapor yılını anan pencereler; yayın/evrak/değişiklik
künyesi tarihleri sayılmaz; kurum geneli düzenlemede yok) ve "ölçütle ilgili bilgi" (ölçüt tanımı
mali kaynak, görev tanımı ya da performans soruyorsa bütçe/karşılanma, temsilci/görevlendirme,
gerçekleşme/hedef değeri cümleleri) alıntılardan önce verilir (`write/sources.py` `period_snippets`,
`topic_snippets`; dönem `config.yaml bidr.donem`). **Parça penceresi:** birleşik belgede (`documents.jsonl`
`parcalar`, ≥2 parça) alıntı bağlamı, dönem içi ve ölçütle ilgili bilgi yalnız alıntıların geçtiği
parçaların sayfalarından alınır; kanıtın `tarih`'i alıntının parçasının tarihidir
(`write/sources.py` `part_scope`; doğrulayıcı aynı paketi görür). Kör test 2026-11-20: aynı PDF'e
eklenmiş ilgisiz yönergenin Senato kararı ve başka tarihli tutanak kanıta mal ediliyordu. İstem kuralları 8–11: dönem içi kaydı önce anlat,
sayıyı küçültme ("4 proje", "birinin" değil), kanıtta bilgi varken "kanıt yok" deme, fakülte
değerini bölümün değeri gibi verme ve hedefle karşılaştırmayı açık yaz; kural 13: aracın iç dili yok
(kod `ic_dil`). v2 metinleri girdileri değişmedikçe geçerli kalır.
**v4 (kör test 2026-11-20 güncelleme ölçümü):** paketin başında dönem içi tarihli kaydı olan
kanıtların listesi ("DÖNEM İÇİ KAYDI OLAN KANITLAR (2025): [4_OD3]"); gösterge/izleme belgesinde
birimin adıyla geçen sayılı satır "bölümün kendi verisi" olarak ilk sırada (`sources.unit_value_snippets`,
birim `config.yaml bidr.birim`). Kural 8: dönem içi kayıt zorunlu ve ilk sırada; kural 11: önce
bölümün değeri (tabloda yalnız ham veri varsa hesabıyla: "8 yayın / 28 öğretim üyesi = 0,29"),
fakülte değeri ancak ardından ve "fakülte genelinde" diye. Kod denetimi (`text.content_issues`;
`write apply` paketteki `meta.donem`/`meta.donem_ici` ile, `verify` kod denetimi kanıt listesiyle):
`donem_ici_atlandi` — belgesinde dönem içi tarihli kayıt bulunan kanıta atıf yapan cümlelerin hiçbiri
dönem içini (dönem yılı ya da dönemi kapsayan aralık) anlatmıyor, en az biri yalnız dönem dışı yıl
anıyor; `fakulte_degeri` — paragrafta gerçekleşme değeri (ondalık) var, fakülte/kurum geneli ya da
bölümün yalnız ham verisi anılıyor, bölümün kendi değeri (ondalık ya da "a / b") yok. Bu iki denetim
doğrulanmış eski metinlere de uygulanır: `verify prepare` sonuçlanmış `dogrulandi` metni bunlardan
geçirir, takılan metin `reddedildi` (kod) olur ve tur sayacı sıfırlanır (`yeni_kural`), yani
`--eski-kurallar` beklemeden yeni kuralla yeniden yazıma gider; temiz eski metin dokunulmaz.
**Eski yazım kuralıyla yazılmış metinler (isteğe bağlı yenileme).** `write_tamam` bunları sayar
(`ilerleme.eski_kural`; uyarı: "N metin eski yazım kuralıyla yazıldı … `bidr write prepare -w WS
--eski-kurallar`"); aşama bitmiş sayılır, yenileme zorunlu değildir. `--eski-kurallar` yalnız görev
sürümü eski, `girdi_sha`'sı güncel ve reddedilmemiş metinleri yeni kuralla paketler (`write.run.old_rule_texts`);
yeni metin taslak olur ve yeniden doğrulanır.
**Paket artığı:** `write apply`, cevabı zaten metne dönüşmüş paketi (metnin `istem_sha` ve
`cevap_sha`'sı paketinkiyle aynı; önceki çalıştırmadan kalan, görev sürümü eski olsa da) işlenmiş
sayar (`değişmedi`); "eski paket … yeniden prepare" yalnız gerçekten yeniden hazırlanması gereken
(girdisi değişmiş ya da cevaplanmamış eski sürüm) paket içindir, `bidr next` ile aynı.
Her cümle en az bir atıf taşır; atıflar `evidence-index.csv`'de olmalı. Metin OD'yi
`audit-olcutler.json`'daki önerilen düzeyin üstünde iddia etmez. `[komisyon]` işareti
cümlenin kanıta değil komisyon bilgisine (`rapor-notlari.yaml`) dayandığını gösterir; rapora
girmez (render siler). `girdi_sha`: kanıt listesi (no, doc_id) + OD; değişirse metin eskir.
`onceki_ret`, `insan_karari` yalnız gerektiğinde bulunur.

## verify → `verify.jsonl` + `texts/<olcut>.json` `durum` güncellemesi
Kod denetimi (atıf var mı, alıntı belgede mi, OD aşımı) + model denetimi (cümle atfıyla
gerçekten destekleniyor mu; metni yazmamış, taze bir ajan). Geçemeyen metin `reddedildi`,
gerekçeyle (cümle bazlı: yer, karar, gerekçe).

Yeniden yazım döngüsü: `bidr write prepare --reddedilenler` reddedilen her ölçüt için yeni
paket yazar; istemin sonuna doğrulayıcının bütün gerekçeleri — desteklenmeyen cümleler, beş soru
denetiminin `uydurma_suphesi` soruları (soru, yerler, gerekçe), kod denetimi sorunları ve
`gerekce` listesinde bunlarla gösterilmeyen her satır — ve reddedilen metin eklenir (doğrulayıcının
paketi verilmez). Ajan yeniden yazar → `write apply` (metnin `tur`u bir artar)
→ `verify prepare/apply` yeniden. Tur sayacı metnin girdisine bağlıdır: kanıt listesi/OD değişip
(`girdi_sha`) metin `write prepare` ile yeniden yazılınca ya da `--eski-kurallar` ile yenilenince yeni
metin tur 0'dan başlar; girdi aynıyken `--only`/`--redo` sayacı sıfırlamaz. Yeniden yazımı ve doğrulamayı ayrı, taze ajanlar yapar.
`rapor.yeniden_yazim_siniri` (vars. 2) turdan sonra hâlâ reddedilen ölçüt "insan gerekli"dir:
kullanıcı `bidr verify karar -w WS <ölçüt> cikar|tekrar` ile karar verir (`verify-insan.jsonl`;
`cikar` metni rapordan çıkarır, `tekrar` bir tur ekler).

## yonler → `yonler/<alan>.json` (Güçlü / Gelişmeye Açık Yönler)
FR-0833'ün son tablosu: A, B, C, D alanlarının her birinde "Güçlü Yönler" ve "Gelişmeye Açık
Yönler" hücresi (8 hücre). `bidr yonler prepare|apply` (ajan modu, görev `write_yonler`,
`bidr/write/yonler.py`). Dayanak YALNIZ o alanın birimce doldurulan (kapsam `bolum`/`ortak`)
alt ölçütleridir: güçlü yön → doğrulanmış açıklama metni (`durum: dogrulandi`, `cikar`
edilmemiş); gelişmeye açık yön → audit bulgusu (önerilen OD ≤ 2, eksik PUKÖ halkası, yalnız kurum
geneli düzenleme, kanıtsız ölçüt).
```json
{"alan": "B", "baslik": "B Eğitim ve Öğretim", "durum": "taslak|dogrulandi|reddedildi", "tur": 0,
 "girdi_sha": "…", "guclu": [{"metin": "… yürütülmektedir (B.1.1).", "olcutler": ["B.1.1"]}],
 "gelisme": [{"metin": "… kanıt bulunmamaktadır (B.1.2).", "olcutler": ["B.1.2"]}],
 "kaynak": {"model": "…", "gorev_surumu": "…", "istem_sha": "…"}}
```
Kod denetimi (apply ve verify prepare): her cümle ölçüt kodu taşır; kod alana ait ve listenin
dayanağı olan ölçütlerden (güçlü: doğrulanmış metni olan; gelişme: bulgusu olan); kanıt numarası
(`[1_OD3]`) yok; write'taki yasak ifade (abartı, koçluk, `-malıdır`), gelecek vaadi ve OD aşımı
kuralları; ayrıca "önerilir/gerekmektedir" öğüt dili yok. Kanıtla çapraz denetim (`cross_check`):
gelişmeye açık yönün "yok" hükmü ölçütün KANIT DURUMU'yla çelişmez (`kanitla_celiski`: izleme/
iyileştirme/uygulama halkası kanıtlıyken ya da listede birime ait kanıt varken "bölüm düzeyinde
kanıt yok/yalnız kurum geneli"). Audit zinciri halkayı eksik saysa da ölçütün doğrulanmış metni
izleme/değerlendirme/iyileştirmeyi anlatıyorsa (`yonler.text_rings`: düzenleme/plan cümleleri hariç;
kör test 2026-11-20: Mat C.3.1 izleme tablosu, Kimya D.2.1 raporlama, Kimya B.1.1 değerlendirme
toplantısı) "izlendiğini/değerlendirildiğini/iyileştirildiğini gösteren belge yok" çelişkidir; metin
yalnız izleme verisini anlatıyorsa hüküm "izleme sonuçlarının bölümce değerlendirildiğini gösteren
belge yok"a daraltılır (`yonler.IZLEME_DAR` bulgusu), var olanı kabul eden hüküm ("geri bildirimler
dışında …", "izlenmekle birlikte …") geçer. KANIT DURUMU bunu gösterir ("izleme metinde var",
"metinde izleme verisi var"); metnin anlattığı halkanın bulgusu yazılmaz. Aynı ölçütte güçlü yönün
söylediği uygulamayı ya da sonuçların değerlendirilmesini/buna dayanan değişikliği yok saymaz (`ic_celiski`); hedefe
ulaşıldığı doğrulanmış metinde görünmeyen gösterge/performans değeri güçlü yön olmaz; metindeki
gösterge hedefin altındaysa (söz ya da sayı: "hedeflenen değeri 1.08 … gerçekleşme değeri 0.36")
o ölçütün izleme verisi de güçlü yön olmaz (`hedef_alti_guclu`) ve bu olgu BULGULAR satırına
gelişmeye açık yön dayanağı olarak eklenir (`yonler.HEDEF_BULGU`; doğrulayıcı gelişmeye açık yönü
yalnız BULGULAR'dan kabul ettiği için iki kural aynı bilgiyi görür; `girdi_sha` bu satırı ayrıca
saymaz, doğrulanmış metin özeti zaten girdidir). "Bölümün bu dönemdeki uygulamasını gösteren belge
bulunmamaktadır" BULGULAR'daki uygulama eksikliğinin kendisidir: listede birime ait (izleme/plan)
kanıt olsa da `kanitla_celiski` sayılmaz; genel "bölüm düzeyinde kanıt yok" ve "yalnız kurum geneli"
hükmü sayılır. Fakülte/kurum geneli gösterge
değeri bölümün değeri yanında olmadan verilmez (`fakulte_degeri`); aracın iç dili yok (`ic_dil`).
Bulgular sade dildedir (düzey/halka/"OD'ye sayılmadı" yok); birime ait ama dönem kanıtı sayılmayan
belgenin nedeni bulguya ve maddeye girmez (kanıt yönetimi notu, gaps.md), birime ait belge varken
"yalnız kurum geneli" yerine "dayanak çoğunlukla kurum geneli" denir. `girdi_sha`:
alanın ölçütleri, doğrulanmış metin özetleri, OD, bulgular ve kanıt durumu; değişirse maddeler eskir.
Bağımsız doğrulama `bidr verify prepare|apply` akışına katılır: `work/verify/yonler/<alan>.json`
(görev `verify_yonler`; doğrulayıcıya yalnız maddeler ve atıf yapılan ölçütlerin metni/bulgusu
verilir) → `verify-yonler.jsonl`. Her madde "destekleniyor" ise `dogrulandi`. Alanlar birbirini
beklemez: yön doğrulaması `verify` aşamasını bekletmez (`verify_tamam` yalnız ölçüt metinlerine
bakar); `yonler_tamam` her alanın sıradaki işini (yazım paketi, apply, doğrulama paketi/cevabı,
yeniden yazım turu) ayrı listeler, bir alanın düzeltmesi ötekilerin doğrulaması bitmeden uygulanır. Reddedilen alan
`bidr yonler prepare --reddedilenler` (gerekçeli; `rapor.yeniden_yazim_siniri`). Render reddedilmiş
alanda bütün hücreyi boşaltmaz: doğrulayıcının (model aşaması, kaydı güncel) "destekleniyor" dediği
maddeleri basar, ötekileri çıkarır (`.bidr-render.json` `yon_cikarilan`, uyarı); kod aşamasında
reddedilen alanın maddesi doğrulanmamıştır, basılmaz. Çıkarılan maddeyle bir ölçüt alanın hiçbir yön
hücresinde kalmıyorsa (kör test 2026-11-20, Kimya C: C.3.1 maddesi çıktı, ölçüt hiçbir hücrede yok)
rapor TASLAK olur (`yon_kapsam_kaybi`; madde düzeltilip yeniden doğrulanır). İşlenmiş alanda basılacak madde kalmazsa
hücreye açık ifade yazılır ("Bu alanda bu dönem için kanıtla doğrulanmış bir güçlü yön
belirlenmemiştir."; `yon_ifadeli`), şablon yönergesi kalmaz. Alan maddesi hiç yazılmamışsa hücre
yönergeyle kalır, rapor TASLAK olur. `verify-yonler.jsonl` render girdi özetine girer.

## Sorumlu birim kapsamı (`bidr/render/kapsam.py`)
Her alt ölçüt için `bolum` (birim doldurur) | `ortak` (başka birimlerle birlikte) |
`baska_birim` (birimin doldurma sorumluluğunda değil) | `karar_gerekli`. Öncelik: config.yaml
`rapor.kapsam: {ölçüt: durum}` (kullanıcının kararı) > profil YAML'ı `kapsam:` > profilin
`dahil`/`belirsiz`/`kararlar` kuralı (geri uyumlu: dahil → bolum, belirsiz → karar_gerekli,
haric → baska_birim). Profil bilinmiyorsa hepsi `bolum`. Render: kanıt yokluğu ("Bu ölçüt için bu
dönemde kanıt bulunamamıştır.") yalnız `bolum`/`ortak` ölçütte yazılır. `baska_birim` ölçütün
Açıklamalar hücresine kısa kapsam ifadesi ("Bu ölçüt birimin doldurma sorumluluğunda
değildir."; `--kapsam-disi ''` ile boş), Kanıtlar hücresi yalnız etiket, OD işaretlenmez, metni
varsa rapora girmez (uyarı). Gerekçe: şablonun "Sorumlu Birimler" bölümü doldurma sorumluluğunu
ölçüt tablosundaki "DOLDURACAK BİRİMLER"e bağlar; boş hücre unutulmuş, "kanıt bulunamadı" birimin
eksiği gibi okunur. `karar_gerekli`: metin yoksa kırmızı "[kapsam kararı gerekli]" işareti, rapor
TASLAK, soru gaps.md'de (`<!-- bidr:kapsam -->` işaretleyicileri arasında; render yeniler,
soru kalmayınca kaldırır).

### Beş zorunlu soru kapsamı (K29) → `soru_kapsami`, `soru-kapsami.json`
FR-0833 her alt ölçüt açıklamasında beş soruyu ister (`bidr/verify/run.py` `SORULAR`; metinler
kılavuzun "Açıklama Metni Yazımı" bölümüyle aynı, test denetler): `surec` (süreç / planlama ve
uygulama), `izleme` (izleme ve değerlendirme), `iyilestirme`, `kanitlar` (mevcut ya da özgün
uygulama kanıtı), `onceki_yil` (önceki yıla göre değişiklik). Doğrulayıcı (`verify_text` v2)
her soru için bir karar ve cümle yerleri verir:
- `kanitla_cevaplandi`: en az bir kanıt atıflı cümle soruyu somut uygulamayla cevaplıyor
  (yalnız `[komisyon]` cümlesi yetmez; yer zorunlu).
- `cevapsiz`: cevaplayan cümle yok (yer boş). Metni reddettirmez; kanıt yoksa doğrusu budur.
- `uydurma_suphesi`: soru kanıtsız genel ifadeyle doldurulmuş (yer zorunlu). Metni
  **reddettirir**; gerekçe `soru <id> (uydurma_suphesi; <yerler>): …` satırıyla `gerekce`ye
  girer ve metin yeniden yazım döngüsüne gider.
`verify apply` cevabı doğrular (beş sorunun her biri tam bir kez, yerler metinde var); tutmayan
cevap `gecersiz`. Kapsam `verify.jsonl` kaydına ve `texts/<olcut>.json`'a aynı biçimde yazılır:
```json
"soru_kapsami": {"durum": "denetlendi|denetlenmedi",
 "sorular": [{"soru": "izleme", "baslik": "İzleme ve değerlendirme nasıl yapılıyor?",
              "durum": "kanitla_cevaplandi|cevapsiz|uydurma_suphesi", "yerler": ["p2.1"], "gerekce": "…"}]}
```
`denetlenmedi` (sorular boş): kod denetiminde reddedilen metin, yeniden doğrulamaya alınmış
metin, görev v1 ile doğrulanmış eski kayıt (alan yok) ya da metni değişmiş kayıt. Eski v1
doğrulamaları geçerli kalır (yeniden paketlenmez); yalnız kapsamları bilinmez.

`verify prepare` ve `apply` her çalışmada çalışma alanı kökünde `soru-kapsami.json` yazar
(bütün `texts/` için; gaps.md'nin "Kanıtla cevaplanmayan sorular" listesinin verisi — listeyi
audit yazar):
```json
{"gorev": "verify_text", "sorular": [{"soru": "surec", "baslik": "…"}],
 "olcutler": {"B.1.1": {"durum": "denetlendi", "metin_durumu": "dogrulandi", "metin_sha": "…",
   "sorular": {"izleme": {"durum": "cevapsiz", "yerler": [], "gerekce": "…"}},
   "kanitla_cevaplanmayan": ["izleme"], "insan_karari": "cikar"}},
 "kanitla_cevaplanmayan": [{"olcut": "B.1.1", "soru": "izleme", "baslik": "…",
   "durum": "cevapsiz|uydurma_suphesi", "yerler": [], "gerekce": "…"}],
 "denetlenmedi": ["B.1.2"]}
```
`kanitla_cevaplanmayan` yalnız denetlenmiş metinlerin `cevapsiz` ve `uydurma_suphesi`
sorularıdır (ölçüt sırasıyla); kapsamı bilinmeyen ölçütler `denetlenmedi`de ayrı listelenir.
`insan_karari` yalnız varsa bulunur.

## render → `report.docx`
FR-0833 şablonunun (config.yaml `rapor.sablon` ya da `--sablon`; salt okunur) ölçüt
bloklarında "Açıklamalar" ve "Kanıtlar" hücreleri doldurulur; biçim kılavuza uygun. Kanıtlar
hücresinde kanıt adı `evidence-index.csv` `baglanti` adresine tıklanabilir bağlantıdır
(Word köprüsü), teslim moduna göre (`rapor.teslim`; aşağıda "teslim"): `baglanti`'da dizindeki adres
olduğu gibi; `dekanlik`'ta (varsayılan) kök klasör bağlantısı (`baglanti_kaynagi: klasor`) girmez ve
kaydedilmiş web sayfası kanıtının (.html) satırı ad + görünür özgün adres olur:
`[2-OD2]. Ad (https://…)` (ikisi de bağlantılı). Web kanıtının adresi dizinde yoksa sayfanın kendi
kaydından okunur (`bidr/teslim/web.py` `web_url`: "saved from" yorumu, SingleFile başlığı,
canonical, og:url, base; ana sayfa adresi sayılmaz); bulunamazsa ad bağlantısız kalır. Teslim modu
render girdi özetine girer (değişince rapor eskir). `[komisyon]` işareti metinden temizlenir. Son tablodaki 8 hücreye
`yonler/<alan>.json` maddeleri ("• " ile) yazılır. Kapakta "[Birim Adı]", yıl ve "Raporu
Hazırlayanlar" yer tutucuları (`[Üye Unvan, Adı Soyadı, eposta adresi, Görevi]`) doldurulur:
satır "Unvan Ad Soyad, eposta, Görev"; kişi yer tutucudan çoksa satır eklenir ve ardındaki boş
paragraf düşer (kapak sayfası taşmaz), azsa artan yer tutucu boş paragraf olur. Altbilgi (form
no, yayın/değişiklik bilgisi, sayfa numarası alanı) ve bölüm özellikleri değişmez (parça bayt
düzeyinde korunur; test edilir).
Belge "TASLAK" damgalıdır (`taslak_nedenleri`): `dogrulandi` olmayan metin (kullanıcının
`cikar` dediği ve `baska_birim` ölçütün metni sayılmaz); boş ya da şablon yönergesi
("…değerlendiriniz.") kalan güçlü/gelişmeye açık yön hücresi ya da doğrulanmamış madde; kapakta
kalan hazırlayan yer tutucusu (`rapor.hazirlayanlar` boş); `karar_gerekli` ölçüt. Gerekçeler render
çıktısında ve `.bidr-render.json` `taslak_nedenleri`'nde; `bidr denetle` `taslak_damgasi` bulgusunda
aynı gerekçeyi bu kayıttan okur (belge kayıttan sonra değiştiyse "nedeni bilinmiyor" der, tahmin
etmez).
Kanıtlar hücresi: metnin atıf verdiği kanıtlar + `evidence-index.csv`'de o ölçüte dosyalanmış ama
metinde atıf almayan kanıtlar, numara sırasıyla (`atifsiz_listelenen`). Böylece liste numarası
atlamaz ve kanıt klasöründeki her dosya listede bulunur (`denetle` `kanit_numarasi` /
`listede_olmayan_dosya` çıkmaz); atıfsız kanıt `atifsiz_kanit` uyarısıyla görünür. Kanıtı
rapordan çıkarmanın yolu review.xlsx'te ret → `audit apply` → `file`; metne atıf eklemenin yolu
yeniden yazımdır.
`.bidr-render.json` girdilerin özetini tutar (`render_tamam`): şablon, metinler, `yonler/`,
audit, kanıt dizini, hazırlayanlar ve kapsam görünümü.

## denetle → `denetim.json` (biçim denetçisi; render'dan bağımsız)
`bidr denetle -w WS [--docx yol] [--sablon FR-0833.docx] [--kanit klasör] [--index csv] [--out yol]
[--paragraf-sonrasi NK]` üretilmiş docx'i (vars. `WS/report.docx`) salt okur; render kodunu çağırmaz,
belgeyi kim üretmiş olursa olsun (render ya da elle düzenleme) aynı denetimi yapar (`bidr/check/`).
Çıktı `denetim.json` (vars. `WS/denetim.json`: `ozet.kritik/uyari/yayima_hazir`, kod sayıları,
`bulgular[{seviye, kod, yer, mesaj}]`, `kurallar`, `bilgi`) ve okunur tablo. Çıkış kodu: 0 kritik yok;
**1 kritik var ("yayıma hazır değil")**; 2 girdi hatası. Şablon: `--sablon` > `rapor.sablon` >
`.bidr-render.json` `sablon`.

Kurallar (kılavuz "Yazım Kuralları", "Kanıt Gösterimi"; K31) ve düzeyleri:
| denetim | düzey |
|---|---|
| 46 alt ölçüt bloğu, her birinde Açıklamalar/Kanıtlar hücresi; boş Açıklamalar | kritik |
| şablon yönerge metni (Açıklamalar/Kanıtlar, A–D güçlü/gelişmeye açık yönler) | kritik |
| kapak `[Birim Adı]` ve "Raporu Hazırlayanlar" `[Üye Unvan, …]` yer tutucuları | kritik |
| gövde yazı tipi Times New Roman, 10 pt (etkin biçim: çalışma → stil → tablo stili → varsayılan) | kritik |
| metindeki her `[n_ODk]` listede aynı numara ve OD ile; listede yinelenen numara | kritik |
| üst/altbilgi form kimliği, revizyon, sayfa alanları şablonla aynı (alan sonucu yok sayılır; şablonsuz: varlık) | kritik |
| TASLAK damgası, `[doğrulanmadı]` metni | kritik |
| kanıt klasörü: listedeki kanıtın dosyası var ve adındaki OD aynı | kritik |
| paragraf öncesi/sonrası aralık; başlıklar 12 pt kalın; alt başlık A.1.x.x.x numarası | uyarı |
| şekil/tablo açıklaması: nesnenin üstünde, sağa dayalı, eğik, 10 pt; APA 7 metin içi gösterim (sezgisel) | uyarı |
| atıf almayan liste kanıtı; numara 1..n sıralı değil; metin içinde `[n-ODk]` | uyarı |
| kanıt dosya adı `[sıra-ODk]. Ad.uzantı` (kılavuz), klasör `A/A.1/A.1.1/`; listede olmayan dosya; evidence-index.csv ile fark | uyarı |
| kanıtsız "bulunamamıştır" ifadeli ölçüt (insan kararı) | uyarı |
| rubrikte insan onayı olmadan (kod önerisiyle) işaretlenen OD: `od_onay_bekliyor` "OD insan onayı bekliyor" | uyarı |
| aracın iç dili Açıklamalar ya da yön hücresinde (`ic_dil`: "Eksik kanıt notu", "OD'ye sayılmamıştır", "eşleşmiş", "uygulama halkası" …) | kritik |
| rubrikte OD işareti yok (`od_isaretsiz`; kapsam dışı hariç) ya da birden çok düzey işaretli (`od_isareti_belirsiz`) | kritik |
| yön hücresinde `[doğrulanmadı]` maddesi | kritik |

**OD onayı.** Render rubrikte önce komisyonun onayladığı `od_onayli`'yi (audit-olcutler.json;
review.xlsx "Ölçüt özeti" ONAYLANAN OD → `bidr audit apply`) işaretler; yoksa kodun önerisi `od`
(metnin `od_onerisi` onu aşamaz), o da yoksa metnin önerisi; hiçbiri yoksa OD1 (`varsayilan`):
kapsam dışı olmayan hiçbir ölçüt işaretsiz kalmaz (kapsam kararı bekleyen dahil). Onaysız işaret
normal işarettir (ayırt edici biçim yok); onay bekleyişi `denetle` uyarısıdır. Kalın işarette öteki
düzey hücrelerinin kalınlığı açıkça kapatılır (tablo stili ilk sütunu kalın yapabilir); `denetle`
işareti satırdaki tek kalın ya da ayrık dolgulu hücreden okur (tablo stilinin ilk sütun biçimi
dahil); şablon verilirse rubriği şablonla aynı kalan blok işaretsiz sayılır. `.bidr-render.json`
`od_onay_bekliyor` (`{ölçüt: {od, kaynak: kod|metin|varsayilan}}`) onaysız işaretlenenleri tutar. `bidr denetle` bu listeyi kayıt denetlenen docx'i
üretmişse (çıktı özeti aynı) kayıttan, değilse audit-olcutler.json'dan (`od` var, `od_onayli` yok)
alır (`check.run.od_onay_bekleyenler`; render kodu çağrılmaz).

Kapsam birimin doldurduğu bölgelerdir; şablonun kendi kılavuz metni biçim denetimine girmez. Başlık
biçimi bulgusu şablonda da varsa "şablon kusuru" diye işaretlenir (FR-0833 R0'da B.2 kalın değil,
A.3.1 11 pt, A.5.1 10 pt).

**Paragraf sonrası aralık: 0,6 nk** (kılavuz değeri, kurumca doğrulandı 2026-11-19). Render
(`docx_ops.SPACING_AFTER` = 12 twip) ve denetim varsayılanı aynıdır; gerekirse config.yaml
`rapor.denetim.paragraf_sonrasi_nk` ya da `--paragraf-sonrasi`. Öteki anahtarlar: `yazi_tipi`, `govde_punto`, `baslik_punto`,
`aciklama_punto`, `paragraf_oncesi_nk`.

**Kanıt gösterimi — karar gerekli.** Kılavuzun örneği metin içinde `[1_OD3]`, ölçüt sonundaki
listede `[1-OD3]. Uygulama Örnekleri.pdf` kullanır (`guide.yaml` `evidence_notation`). Render'ın
varsayılanı (`--kanit-bicimi mat`) listeyi `1_OD3: ad` yazar (geçen yılın Matematik raporu usulü);
denetçi bunu `kanit_gosterimi_karar` uyarısıyla raporlar, iki gösterim karışıksa
`kanit_gosterimi_karisik`. Kurum kılavuz gösterimini isterse render `--kanit-bicimi kilavuz`.

**Hat aşaması `denetle`** (D; önkoşul `render`; ardından isteğe bağlı `teslim`). `denetim.json` `docx_sha` denetlenen
dosyanın sha256'sıdır. `checks.denetle_tamam`: denetim.json yok, başka bir docx'e ait ya da sha'sı
güncel report.docx'inkiyle aynı değil (rapor yeniden üretildi ya da elle değişti) → `bidr denetle`;
kritik bulgu varsa bekliyor, KULLANICI gerekli, neden "yayıma hazır değil: N kritik bulgu (kodlar)"
(düzeltme kaynakta, sonra render + denetle); kritik yoksa bitti ("yayıma hazır"), uyarılar engel
değil. Bağlantısız kanıt satırı (Kanıtlar hücresinde `w:hyperlink` yok) teslim moduna göre:
`dekanlik`'ta yalnız `denetim.json` `bilgi.baglanti` (sayı + not; bulgu değil), `baglanti`'da
`baglantisiz_kanit` uyarısı; ikisinde de yayımı engellemez. Geçersiz `rapor.teslim` çıkış 2.

## teslim → `teslim/` + `teslim.zip` (dekanlığa teslim paketi; `bidr/teslim/`)
2025 raporunda bölüm kanıtlara bağlantı vermez: rapor ve kanıt dosyaları dekanlığa teslim edilir,
yüklemeyi dekanlık yapar (`rapor.teslim: dekanlik`, varsayılan). Bağlantı modu (`baglanti`:
`kanit_kok_baglanti`, bağlantı denetimi) sonraki yıllar için araçta kalır.

`bidr teslim -w WS [--out DIR] [--docx yol] [--tarih YYYY-AA-GG] [--zip-yok]
[--pdf-araci otomatik|chrome|weasyprint] [--canli] [--taslak]` yazar (model yok, salt okur):

```
WS/teslim/                       (--out; zip: aynı adla .zip, kökünde klasör adı; adlar NFC)
  report.docx                    WS/report.docx'in kopyası
  kanitlar/A/A.1/A.1.1/[1-OD3]. Ad.pdf
  kanitlar/A/A.1/A.1.4/[3-OD2]. Sayfa.html + [3-OD2]. Sayfa.pdf   (web kanıtı + damgalı PDF kopyası)
  kanit-dizini.xlsx / .csv       Ölçüt, Kanıt no, OD, Kanıt adı, Paketteki dosya, PDF kopyası,
                                 Özgün bağlantı, Bağlantı kaynağı, Alınma tarihi, Maskeleme, Durum
  EKSIK.txt                      yalnız eksik ya da --taslak paket
WS/.bidr-teslim.json             özet (teslim_tamam): report_sha, index_sha, evidence_sha, eksik, …
```

- **Eşleşme:** raporun Kanıtlar listesindeki her satır (ölçüt, sıra, OD; `check.run.kanit_listeleri`)
  `evidence/` altında tam bir dosyayla eşleşir. Pakete yalnız listedeki kanıtlar girer (listede
  olmayan dosya uyarı). Aynı kaynağın belgeleri tek numarayı paylaşıyorsa (dizinde numaranın
  birden çok satırı, `ayni_kaynak_tek_numara`) dizinin o numaraya yazdığı dosyaların hepsi girer
  (kanıt dizininde her biri ayrı satır; dizinde olmayan artık dosya uyarı). Dosya yok / OD uyuşmuyor
  / dizinin bilmediği birden çok aday / PDF üretilemedi → satır
  `Durum: eksik: …`, paket `EKSIK.txt` ile yazılır, çıkış 1.
- **Web kanıtı** (`.html`, `.htm`, `.xhtml`): yanına aynı adla PDF kopyası. Sayfanın bir kopyasının
  başına (gövdenin ilk öğesi) ve sonuna (`body::after`: kapanmamış tablo içinde kalmaz)
  "Kaynak: <URL> · Alınma (erişim) tarihi: <GG.AA.YYYY>" damgası eklenir; betikler kapalı (CSP),
  yerel sayfada ağ erişimi engelli. Özgün adres: dizindeki bağlantı (insan / belge metni; `klasor`
  sayılmaz) → sayfanın kendi kaydı; yoksa damgada ve dizinde "bağlantı bilinmiyor" (uydurma yok,
  uyarı). Alınma tarihi raporlama (teslim) tarihidir (`--tarih`, vars. bugün). `--canli`: adres
  biliniyorsa sayfa özgün adresten yeniden indirilip basılır.
- **Kişisel veri maskeleme** (`bidr maskele` çıktısı, yalnız okunur): `maskeleme-raporu.json` ve
  `evidence-maskeli/` varsa kanıtın maskeli kopyası pakete girer (web PDF'i maskeli HTML'den basılır;
  eski biçimden çevrilen kanıt maskeli kopyanın uzantısıyla). Teslim kapısı (politika 2026-11-22):
  maskelenecek yeri çözülmemiş dosya — onay bekleyen bölge, maskeleme başarısız / taranamadı / hata /
  desteklenmiyor, dosya raporda yok ya da maskeli kopya eski — pakete otomatik girmez; rapordaki atıf
  ve numara değişmez, dizinde satır kalır (Maskeleme `kontrol bekliyor`, dosya boş), komut çıktısında,
  `EKSIK.txt`'de ve `.bidr-teslim.json` `kontrol_bekliyor`'da "maskelenecek yeri var, kontrol bekliyor:
  N dosya"; `teslim_tamam` insan bekler. Bölge kararı ya da elle maskelenmiş sürüm (`bidr maskele
  bolgeler` / `karar` / `yukle`, sonra `bidr maskele`) sonrası yeniden teslimde girer. "Maskeleme"
  sütunu: `tamam` | `elle maskelendi` | `kontrol bekliyor` | `yapılmadı` (maskeleme çalıştırılmamış;
  özgün dosya girer, hat uyarır).
- **PDF aracı** (ücretsiz, kurulu olanı): Google Chrome / Chromium / Edge headless `--print-to-pdf`
  (standart yerde değilse `BIDR_CHROME`), yoksa Python `weasyprint` (isteğe bağlı). Web kanıtı varken
  araç yoksa komut hiçbir şey yazmadan kurulum notuyla durur (çıkış 2).
- **Güvenli yazım:** çıktı klasörü çalışma alanının kendisi/üstü ya da kaynakla iç içe olamaz; var
  olan klasör yalnız bidr teslim'in işaret dosyasını (`.bidr-teslim`) taşıyorsa silinip yeniden
  yazılır, değilse ve boş değilse hata.

**Hat aşaması `teslim`** (D; isteğe bağlı; önkoşul `denetle`). `checks.teslim_tamam`
(`teslim.run.durum`): `baglanti` modunda paket yoksa atlandi; `dekanlik`'ta paket yoksa ya da rapor,
kanıt dizini, kanıt klasörü, maskeleme raporu ya da teslim modu değiştiyse `bidr teslim`; `--taslak` paketi bitmiş
sayılmaz; eksik paket KULLANICI gerekli; tamamsa bitti, özgün adresi bulunamayan web kanıtı uyarı.
Kapı: biçim denetimi geçmeden komut çıkış 3 ile durur; `--taslak` kapıyı atlar, paketi TASLAK işaretler.

## config.yaml `rapor:` bölümü (hepsi isteğe bağlı; kullanıcı yazar, `bidr init` korur)
| anahtar | anlamı |
|---|---|
| `onceki_rapor` | geçen yılın FR-0833 docx'i ya da `<ölçüt>.txt` klasörü (write: üslup ve karşılaştırma) |
| `sablon` | boş FR-0833 şablonu (render); answers.yaml `sablon` (tam yol) ile `bidr init` yazar: dosya var, .docx ve Word paketi olmalı; cevapta boşsa var olan korunur, farklıysa kullanıcı onayı (`--yes`) |
| `kanit_kok_baglanti` | kanıt klasörünün yüklendiği kök adres (klasör bağlantıları) |
| `yayin_alan_adlari` | gövde URL'sinin yayın adresi sayılacağı alan adları (ör. `[gtu.edu.tr]`) |
| `kanit_secimi` | kanıt seçimi ayarları (yukarıda; `olcut_basina_en_fazla`, `kurum_geneli_en_fazla`, `gecmis_kanit_en_fazla`, `en_dusuk_guven`, `dolayli_isaretler`, `surum_birlestir`) |
| `yeniden_yazim_siniri` | reddedilen metin için en çok yeniden yazım turu (vars. 2) |
| `kanit_adi_modeli` | `false`: `name` aşaması atlanır |
| `hazirlayanlar` | kapaktaki "Raporu Hazırlayanlar": `[{unvan, ad_soyad, eposta, gorev}, …]` (`ad_soyad` gerekli; `bidr init` sorar ve yazar); boşsa rapor TASLAK |
| `kapsam` | `{ölçüt: bolum\|ortak\|baska_birim\|karar_gerekli}`: kullanıcının kapsam kararı (profilin üstüne) |
| `teslim` | `dekanlik` (vars.: rapor ve kanıtlar dekanlığa dosya olarak teslim edilir; bağlantısız kanıt bilgi; `bidr teslim` paketi) \| `baglanti` (birim yükler, raporda bağlantı verir; bağlantısız kanıt uyarı) |
| `denetim` | biçim denetçisi kuralları (`paragraf_sonrasi_nk` vars. 0,6 — kılavuz değeri; `yazi_tipi`, `govde_punto`, `baslik_punto`, `aciklama_punto`, `paragraf_oncesi_nk`) |
