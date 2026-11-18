# Rapor katmanı (name → file → write → verify → render) — arayüz sözleşmesi

Sahibi: şef. Aşamalar `bidr/data/pipeline.yaml`'da; tamamlanma denetimleri
`bidr/pipeline/checks.py`'de (`name_tamam`, `file_tamam`, `write_tamam`, `verify_tamam`,
`render_tamam`). Her komut önkoşulu bitmeden çıkış kodu 3 ile durur.

## Girdi: onaylı eşleşmeler
`decisions.jsonl` içindeki kabul edilmiş eşleşmeler; varsa `review-decisions.jsonl`
(audit apply) kararları üstündür: `ret` olan eşleşme düşer, `duzelt` olan düzeltilmiş
ölçüt/yuva/aşamayla girer. Düşük güvenli eşleşme önerilen OD'ye katılmaz; inceleme kararı
(`kabul`/`duzelt`) bunu kaldırır (insan kararı kuralı aşar; audit ve file aynı kural).
Ölçüt düzeyi OD: `audit-olcutler.json` (audit çıktısı).

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
Bir belge bir ölçütte bir kez numaralanır; farklı ölçütlerde ayrı numara alır. `kopyalar`:
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
   ↔ dolu metin). Dönem işareti yok, tarih aynı değil ve sayısal içerik farklıysa emin
   olunamaz: tek sayılır, satır `surum_belirsiz` işaretlenir, gaps.md "Sürümü doğrulanacak
   belgeler"de listelenir; komisyon üyenin satırını `duzelt` ederse (yuva aynı kalabilir) ayrı
   kanıt kalır. Temsilci satırı `surum_temsilcisi` işareti alır.
2. **İlgililik.** (a) write sonrası metinde atıf yapılan kanıt her zaman girer, sınıra sayılmaz
   (atıf `texts/<ölçüt>.json`'dan; numara önceki dizinle, dizin değiştiyse `evidence-secim.json`
   atıf eşlemesiyle belgeye bağlanır). (b) Atıfsız kanıt yalnız doğrudan ilgiliyse girer: güven
   ≥ `en_dusuk_guven` ve sayılan eşleşmelerinden en az biri `dolayli_isaretler`'den
   (`asama_yuva_etiketine_uymuyor`, `asama_dusuruldu`, `birim_aitligi_dogrulanmali`) birini
   taşımıyor; ölçüt başına `olcut_basina_en_fazla` (sıra: OD'ye sayılan önce, sonra OD, güven,
   tarih). (c) Kurum geneli düzenleme (audit `kurum_geneli` işareti) bir ölçütte en çok
   `kurum_geneli_en_fazla`; madde alıntısı olan önce; kalanlar gaps.md "Elenen kurum geneli
   belgeler". İnceleme `duzelt`i (insan yerleştirmesi) sınır yüzünden düşmez; `kabul` güven ve
   dolaylılık eşiğini aşar ama sınırlara tabidir (`audit_tamam` her satıra karar istediğinden
   toplu `kabul` seçimi kapatmamalı). Audit'in saydığı her halka (P/U/K/Ö/Z) listede en az bir
   kanıtla kalır: seçilmemişse en iyi aday sınırlara rağmen girer (`zincir_icin_secildi`), yani
   yayımlanan liste audit OD'sini destekler.

Elenen her belge nedeniyle gaps.md'nin `<!-- bidr:kanit-secimi -->` bölümünde (file yazar,
audit korur) ve `evidence-secim.json`'da görünür. Ayarlar `bidr/data/profiles/kanit_secimi.yaml`
(kurum `BIDR_PROFILES_DIR` ile değiştirir), çalışma alanı config.yaml `rapor.kanit_secimi`
(anahtar anahtar üstüne yazar); varsayılan: ölçüt başına 6 atıfsız kanıt, kurum geneli 2, en
düşük güven `orta`, sürüm birleştirme açık. Ayar değişince `file_tamam` yeniden dosyalama ister
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
paket yazar; istemin sonuna doğrulayıcının cümle bazlı gerekçesi ve reddedilen metin eklenir
(doğrulayıcının paketi verilmez). Ajan yeniden yazar → `write apply` (metnin `tur`u bir artar)
→ `verify prepare/apply` yeniden. Yeniden yazımı ve doğrulamayı ayrı, taze ajanlar yapar.
`rapor.yeniden_yazim_siniri` (vars. 2) turdan sonra hâlâ reddedilen ölçüt "insan gerekli"dir:
kullanıcı `bidr verify karar -w WS <ölçüt> cikar|tekrar` ile karar verir (`verify-insan.jsonl`;
`cikar` metni rapordan çıkarır, `tekrar` bir tur ekler).

## render → `report.docx`
FR-0833 şablonunun (config.yaml `rapor.sablon` ya da `--sablon`; salt okunur) ölçüt
bloklarında "Açıklamalar" ve "Kanıtlar" hücreleri doldurulur; biçim kılavuza uygun. Kanıtlar
hücresinde kanıt adı `evidence-index.csv` `baglanti` adresine tıklanabilir bağlantıdır
(Word köprüsü). `[komisyon]` işareti metinden temizlenir. `dogrulandi` olmayan metin varsa
belge "TASLAK" damgalı üretilir; kullanıcının `cikar` dediği reddedilmiş metin rapora girmez ve
taslak saymaz. `.bidr-render.json` girdilerin özetini tutar (`render_tamam`).

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
| kanıt dosya adı `[Ölçüt-sıra-ODk] Ad.uzantı`, klasör `A/A.1/A.1.1/`; listede olmayan dosya; evidence-index.csv ile fark | uyarı |
| kanıtsız "bulunamamıştır" ifadeli ölçüt (insan kararı) | uyarı |

Kapsam birimin doldurduğu bölgelerdir; şablonun kendi kılavuz metni biçim denetimine girmez. Başlık
biçimi bulgusu şablonda da varsa "şablon kusuru" diye işaretlenir (FR-0833 R0'da B.2 kalın değil,
A.3.1 11 pt, A.5.1 10 pt).

**Paragraf sonrası aralık — kurumdan sorulacak.** Kılavuz metni "sonrası 0,6 nk" der; render 6 pt
yazar (`docx_ops.SPACING_AFTER`, geçen yılın raporlarındaki değer). Denetim yapılandırılabilir,
varsayılanı render'la aynı **6 nk**: config.yaml `rapor.denetim.paragraf_sonrasi_nk: 0.6` ya da
`--paragraf-sonrasi 0.6`. Öteki anahtarlar: `yazi_tipi`, `govde_punto`, `baslik_punto`,
`aciklama_punto`, `paragraf_oncesi_nk`.

**Kanıt gösterimi — karar gerekli.** Kılavuzun örneği metin içinde `[1_OD3]`, ölçüt sonundaki
listede `[1-OD3]. Uygulama Örnekleri.pdf` kullanır (`guide.yaml` `evidence_notation`). Render'ın
varsayılanı (`--kanit-bicimi mat`) listeyi `1_OD3: ad` yazar (geçen yılın Matematik raporu usulü);
denetçi bunu `kanit_gosterimi_karar` uyarısıyla raporlar, iki gösterim karışıksa
`kanit_gosterimi_karisik`. Kurum kılavuz gösterimini isterse render `--kanit-bicimi kilavuz`.

Hatta bağlama (öneri; bu değişiklikte yapılmadı): `pipeline.yaml`'a render'dan sonra `denetle`
aşaması (katman D) ve `checks.py`'de `denetle_tamam` (denetim.json `docx` sha'sı güncel ve
`yayima_hazir`); kritik bulgu yayımı durdurur, uyarılar insan onayına bırakılır.

## config.yaml `rapor:` bölümü (hepsi isteğe bağlı; kullanıcı yazar, `bidr init` korur)
| anahtar | anlamı |
|---|---|
| `onceki_rapor` | geçen yılın FR-0833 docx'i ya da `<ölçüt>.txt` klasörü (write: üslup ve karşılaştırma) |
| `sablon` | boş FR-0833 şablonu (render) |
| `kanit_kok_baglanti` | kanıt klasörünün yüklendiği kök adres (klasör bağlantıları) |
| `yayin_alan_adlari` | gövde URL'sinin yayın adresi sayılacağı alan adları (ör. `[gtu.edu.tr]`) |
| `kanit_secimi` | kanıt seçimi ayarları (yukarıda; `olcut_basina_en_fazla`, `kurum_geneli_en_fazla`, `en_dusuk_guven`, `dolayli_isaretler`, `surum_birlestir`) |
| `yeniden_yazim_siniri` | reddedilen metin için en çok yeniden yazım turu (vars. 2) |
| `kanit_adi_modeli` | `false`: `name` aşaması atlanır |
| `denetim` | biçim denetçisi kuralları (`paragraf_sonrasi_nk` vars. 6 — kılavuz 0,6 der, kurumdan doğrulanacak; `yazi_tipi`, `govde_punto`, `baslik_punto`, `aciklama_punto`, `paragraf_oncesi_nk`) |
