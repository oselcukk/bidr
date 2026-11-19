# Rapor katmanı (name → file → write → verify → yonler → render) — arayüz sözleşmesi

Sahibi: şef. Aşamalar `bidr/data/pipeline.yaml`'da; tamamlanma denetimleri
`bidr/pipeline/checks.py`'de (`name_tamam`, `file_tamam`, `write_tamam`, `verify_tamam`,
`yonler_tamam`, `render_tamam`). Her komut önkoşulu bitmeden çıkış kodu 3 ile durur.

## Girdi: onaylı eşleşmeler
`decisions.jsonl` içindeki kabul edilmiş eşleşmeler; varsa `review-decisions.jsonl`
(audit apply) kararları üstündür: `ret` olan eşleşme düşer, `duzelt` olan düzeltilmiş
ölçüt/yuva/aşamayla girer. Düşük güvenli eşleşme önerilen OD'ye katılmaz; inceleme kararı
(`kabul`/`duzelt`) bunu kaldırır (insan kararı kuralı aşar; audit ve file aynı kural).
Ölçüt düzeyi OD: `audit-olcutler.json` (audit çıktısı).

### Eksik kanıt notu (`audit-olcutler.json` `olcutler[].eksik_kanit_notu`)
Audit üretir (docs/AUDIT.md "Eksik kanıt notu"); render okur. `null` ya da
`{"durum": "kanitsiz" | "neredeyse_kanitsiz", "nedenler": [...], "metin": "Eksik kanıt notu: …"}`.
Render sözleşmesi (uygulandı: `render.run.audit_note`): alan doluysa ölçütün Açıklamalar hücresine
`metin` (italik, metnin paragraflarından sonra) yazılır,
**ölçütün metni olsa da** (`neredeyse_kanitsiz`: yalnız kurum geneli, yalnız dönem dışı, yalnız
tarihi/birimi doğrulanmamış ya da yalnız düşük güvenli kanıtı olan ölçüt metinle de doldurulmuş
olabilir; not bölümün bu döneme ait doğrudan kanıtı olmadığını söyler). `kanitsiz` metni
bugünkü `eksik_text` çıktısıyla aynıdır; alan yoksa (eski audit çıktısı) render bugünkü
davranışı sürdürür. `--eksik-notu-yok` ikisini de kapatır. Kapsam dışı (`baska_birim`) ölçütte
yazılmaz. Metni olup not alan ölçütler `.bidr-render.json` `eksik_notlu_metin`.

## Kanıt adı (`ad`, `ad_kaynagi`) — öncelik insan > model > kural
- `insan`: review.xlsx "kanıt adı" düzeltmesi (`bidr audit apply` → `kanit-adlari.jsonl`,
  inceleme klasörüne).
- `model`: `bidr name prepare|apply` (ajan; isteğe bağlı aşama `name`, audit'ten önce) ya da
  ince kararın `kanit_adi`'sı (classify_fine v7). `name` uygunluğu insan birim kararıyla
  belirlenir (`birim-kararlari.jsonl`, audit/file ile aynı görünüm): geri alınan belge kanıttır;
  ince kararın kabul edilmiş `kanit_adi`'sı olan belge paketlenmez.
- `kural`: identify başlığı, yoksa tür etiketi (`bidr/file/naming.py`).
Her ad yeniden denetlenir (kişi adı/unvan/e-posta yok); tutmayan kaynak atlanır.
config.yaml `rapor.kanit_adi_modeli: false` `name` aşamasını atlar.

## Kanıt bağlantısı (`baglanti`, `baglanti_kaynagi`) — öncelik insan > belge metni > klasör
- `insan`: review.xlsx "bağlantı" sütunu (`bidr audit apply` → `kanit-baglantilari.jsonl`,
  `kaynak: insan`; belgeye ait, http(s)).
- `belge_metni`: kamuya açık belge yayımlandığı adrese bağlanır. Adres belge metninden: web
  çıktısının üst/altbilgisi (sayfanın ilk/son iki satırı) ya da birden çok sayfada tek başına
  satır olarak yinelenen URL; gövdedeki (ya da bir kez tek başına geçen) URL yalnız
  `rapor.yayin_alan_adlari` listesindeki alan adındaysa (alt alan adları dahil). Ana sayfa
  adresi (yolsuz; kurum yazısı altbilgisi) sayılmaz.
- `klasor`: yayımlanmamış belge; kanıt klasörü kullanıcı tarafından yüklendikten sonra
  `rapor.kanit_kok_baglanti` + `evidence/`'e göre göreli yol (her parça yüzde kodlu). bidr yüklemez.
Bağlantısı olmayan kanıtlar `gaps.md`'nin "Bağlantısı olmayan kanıtlar" bölümünde
(`<!-- bidr:baglanti-yok -->` işaretleyicileri arasında; file ve render yeniler, audit korur).

## file → `evidence-index.csv` + `evidence/`
Sözleşme sütunları: `kanit_no` (ölçüt içinde sıra + OD, kılavuz gösterimi: `1_OD3`),
`olcut`, `od`, `ad` (insan okur kanıt adı), `dosya` (evidence/'e göre göreli yol), `doc_id`,
`sayfalar` (boş = tüm belge), `yuvalar`, `alintilar` (JSON liste).
Ek sütunlar: `inceleme`, `kopyalar`, `kaynak`, `isaretler`, `ad_kaynagi` (insan|model|kural),
`baglanti` (raporda kanıt adının adresi; boş olabilir), `baglanti_kaynagi`
(insan|belge_metni|klasor|boş).
Bir belge bir ölçütte bir kez numaralanır; farklı ölçütlerde ayrı numara alır. **Numara ve kod
OD'si** (`bidr/file/naming.py`): kod OD'si `evidence_od(audit satırları, ölçüt OD'si)` — kodun
düşüşleri yansır (kurum geneli → planla → OD2; `od_kabul` düşüşü), ölçüt OD'sine sayılmayan kanıt
(dönem kuralı, düşük güven) ölçütün önerilen OD'sinin üstünü göstermez, modelin ham OD'si
kullanılmaz. Aynı kaynak (aynı içerik ya da aynı `surum_grubu`; parça grupları dahil) bir ölçütte
seçimde ayrı tutulsa da (farklı dönem verisi) tek numara ve tek OD alır (`number_sources`): satırlar
aynı `kanit_no`, aynı `ad` (grubun ilk üyesinin) ve aynı `baglanti`yı (öncelik insan > belge metni >
klasör) taşır — write'ın kanıt listesi ve render'ın (ölçüt, kanit_no) bağlantı haritası tek değer
görür — ama her üye ayrı dosyadır (`[Ölçüt-n-ODk] Ad (tarih).uzantı`, işaret
`ayni_kaynak_tek_numara`; biçim denetçisi `kanit_dosyasi_yineleniyor` uyarısı verir). Dosya adı
klasörde büyük/küçük harf duyarsız tekildir: çakışmada kısa kimlik eklenir, hiçbir belge ötekinin
üstüne yazılmaz. Arşiv/e-posta üyesi kanıtlanırken üyenin kendisi kopyalanır. `kopyalar`:
bu satırın temsil ettiği öteki belgeler (mükerrer metin ve tek kanıt sayılan sürümler).
Ek dosya `evidence-secim.json`: seçilenler (neden), elenenler (neden), sürüm birleştirmeleri,
metin atıflarının belge eşlemesi ve ayarlar.

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
2. **İlgililik.** (a) write sonrası metinde atıf yapılan kanıt her zaman girer, sınıra sayılmaz
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
kanıt sınıra sayılmaz.

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
→ `verify prepare/apply` yeniden. Yeniden yazımı ve doğrulamayı ayrı, taze ajanlar yapar.
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
kuralları; ayrıca "önerilir/gerekmektedir" öğüt dili yok. `girdi_sha`: alanın ölçütleri, doğrulanmış
metin özetleri, OD ve bulgular; değişirse maddeler eskir.
Bağımsız doğrulama `bidr verify prepare|apply` akışına katılır: `work/verify/yonler/<alan>.json`
(görev `verify_yonler`; doğrulayıcıya yalnız maddeler ve atıf yapılan ölçütlerin metni/bulgusu
verilir) → `verify-yonler.jsonl`. Her madde "destekleniyor" ise `dogrulandi`. Reddedilen alan
`bidr yonler prepare --reddedilenler` (gerekçeli; `rapor.yeniden_yazim_siniri`); sınırdan sonra
hücreler şablon yönergesiyle kalır ve rapor TASLAK olur (insan görür).

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
(Word köprüsü). `[komisyon]` işareti metinden temizlenir. Son tablodaki 8 hücreye
`yonler/<alan>.json` maddeleri ("• " ile) yazılır. Kapakta "[Birim Adı]", yıl ve "Raporu
Hazırlayanlar" yer tutucuları (`[Üye Unvan, Adı Soyadı, eposta adresi, Görevi]`) doldurulur:
satır "Unvan Ad Soyad, eposta, Görev"; kişi yer tutucudan çoksa satır eklenir ve ardındaki boş
paragraf düşer (kapak sayfası taşmaz), azsa artan yer tutucu boş paragraf olur. Altbilgi (form
no, yayın/değişiklik bilgisi, sayfa numarası alanı) ve bölüm özellikleri değişmez (parça bayt
düzeyinde korunur; test edilir).
Belge "TASLAK" damgalıdır (`taslak_nedenleri`): `dogrulandi` olmayan metin (kullanıcının
`cikar` dediği ve `baska_birim` ölçütün metni sayılmaz); boş ya da şablon yönergesi
("…değerlendiriniz.") kalan güçlü/gelişmeye açık yön hücresi ya da doğrulanmamış madde; kapakta
kalan hazırlayan yer tutucusu (`rapor.hazirlayanlar` boş); `karar_gerekli` ölçüt.
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

**OD onayı.** Render rubrikte önce komisyonun onayladığı `od_onayli`'yi (audit-olcutler.json;
review.xlsx "Ölçüt özeti" ONAYLANAN OD → `bidr audit apply`) işaretler; yoksa kodun önerisi `od`
(metnin `od_onerisi` onu aşamaz). `.bidr-render.json` `od_onay_bekliyor` (`{ölçüt: {od, kaynak:
kod|metin}}`) onaysız işaretlenenleri tutar. `bidr denetle` bu listeyi kayıt denetlenen docx'i
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

**Hat aşaması `denetle`** (D; önkoşul `render`; son aşama). `denetim.json` `docx_sha` denetlenen
dosyanın sha256'sıdır. `checks.denetle_tamam`: denetim.json yok, başka bir docx'e ait ya da sha'sı
güncel report.docx'inkiyle aynı değil (rapor yeniden üretildi ya da elle değişti) → `bidr denetle`;
kritik bulgu varsa bekliyor, KULLANICI gerekli, neden "yayıma hazır değil: N kritik bulgu (kodlar)"
(düzeltme kaynakta, sonra render + denetle); kritik yoksa bitti ("yayıma hazır"), uyarılar engel
değil.

## config.yaml `rapor:` bölümü (hepsi isteğe bağlı; kullanıcı yazar, `bidr init` korur)
| anahtar | anlamı |
|---|---|
| `onceki_rapor` | geçen yılın FR-0833 docx'i ya da `<ölçüt>.txt` klasörü (write: üslup ve karşılaştırma) |
| `sablon` | boş FR-0833 şablonu (render) |
| `kanit_kok_baglanti` | kanıt klasörünün yüklendiği kök adres (klasör bağlantıları) |
| `yayin_alan_adlari` | gövde URL'sinin yayın adresi sayılacağı alan adları (ör. `[gtu.edu.tr]`) |
| `kanit_secimi` | kanıt seçimi ayarları (yukarıda; `olcut_basina_en_fazla`, `kurum_geneli_en_fazla`, `gecmis_kanit_en_fazla`, `en_dusuk_guven`, `dolayli_isaretler`, `surum_birlestir`) |
| `yeniden_yazim_siniri` | reddedilen metin için en çok yeniden yazım turu (vars. 2) |
| `kanit_adi_modeli` | `false`: `name` aşaması atlanır |
| `hazirlayanlar` | kapaktaki "Raporu Hazırlayanlar": `[{unvan, ad_soyad, eposta, gorev}, …]` (`ad_soyad` gerekli; `bidr init` sorar ve yazar); boşsa rapor TASLAK |
| `kapsam` | `{ölçüt: bolum\|ortak\|baska_birim\|karar_gerekli}`: kullanıcının kapsam kararı (profilin üstüne) |
| `denetim` | biçim denetçisi kuralları (`paragraf_sonrasi_nk` vars. 0,6 — kılavuz değeri; `yazi_tipi`, `govde_punto`, `baslik_punto`, `aciklama_punto`, `paragraf_oncesi_nk`) |
