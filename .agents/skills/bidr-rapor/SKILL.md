---
name: bidr-rapor
description: Kurulu bir bidr çalışma alanında BİDR rapor hattını yürütür - `bidr next`'in söylediği adımı yapar, model aşamalarında iş paketlerini ajan olarak cevaplar (karar, ikinci arama, kanıt adı, metin yazımı, doğrulama), yeniden yazım döngüsünü ve biçim denetimini yürütür, kapılara ve insan onayına uyar. Tetik - "raporu hazırla", "BİDR raporu", "devam et", "nerede kaldık", "sıradaki adım", "kanıtları eşle", "decide paketleri", "metinleri yaz", "raporu üret". Kullanma - kurulum veya config değişikliği (bidr-kur), hakem sorularını kullanıcıya sormak (bidr-hakem).
---

# bidr-rapor

Çalışma alanını `AGENTS.md` ve `config.yaml` (içinde `bidr:` bölümü) belirler. `bidr`
yerine AGENTS.md'deki tam yolu kullan. WS = çalışma alanının yolu.

## Döngü

1. `bidr next -w WS` çalıştır ve çıktıyı tamamen oku.
2. Duruma göre:
   - `(komutu çalıştır)` → "Yap:" altındaki komutu birebir çalıştır. Bayrak ekleme/çıkarma.
   - `(model işi: ajan yapar)` → aşağıdaki **iş paketi döngüsü**.
   - `(KULLANICI gerekli)` ya da `İnsan onayı: GEREKLİ` → DUR. Kullanıcıya hangi aşamada
     olduğunu, neyi beklediğini (`next`'in "Durum" satırı) ve sonra ne olacağını söyle.
     Hakem aşamasında kullanıcı isterse skill `bidr-hakem`.
   - "Bütün aşamalar bitti" → rapor biçim denetiminden kritik bulgusuz geçti (yayıma hazır);
     bitirirken özetle. Kanıt klasörü, rapor metni,
     docx, tablo gibi çıktıları hiçbir zaman elle üretme ya da düzenleme: her birinin komutu var.
3. Her komuttan sonra 1'e dön. Aynı adım iki kez üst üste ilerlemiyorsa (ilerleme sayıları
   değişmiyor) dur ve kullanıcıya çıktıyı göster.

Kapı hatası (`HATA kapı: ...`, çıkış kodu 3): önkoşul bitmemiş. Atlatmaya çalışma
(config'i düzenlemek, dosya silmek, bayrak denemek yok); `bidr next`'e dön.
Uyarılar (`Uyarı:`) engel değildir ama sonunda kullanıcıya özetlenir.

## İş paketi döngüsü (karar_kaba, karar_ince)

Model işini sen yaparsın; hiçbir API ya da `bidr decide run` / `bidr llm` kullanılmaz.

1. `work/<coarse|fine>/README.md`'yi oku.
2. Cevapsız her `<doc_id>.json` paketi için: `istem` alanı görevin tamamıdır (kurallar, ölçüt
   listesi, belge metni); `sema` cevabın JSON şemasıdır. İstemdeki kurallara uy:
   - yalnız istemdeki belge metnine dayan; dosya adı, klasör, dış bilgi yok;
   - ölçüt yalnız istemdeki listeden/adaylardan; yuva kodları istemdeki gibi;
   - **alıntı belge metninden birebir, kesintisiz kopya**: 1-2 cümle, en az 20 en çok 300
     karakter; kısaltma, "[...]", düzeltme, birleştirme yok. Metin satır kırımlıysa tek satırlık
     anlamlı bir parça yeterli (satır sonu ve boşluk farkını kod tolere eder). Bulamıyorsan o
     eşleşmeyi yazma;
   - aynı (ölçüt, yuva) için tek eşleşme yaz; ikincisi "yinelenen" diye reddedilir;
   - emin değilsen `olcut_yok` ya da `kanit_degil` geçerli ve dürüst cevaptır.
   - ince pakette adayları kod seçer (kaba seçim ∪ belirleyici adaylar): kaba aşamada
     `kanit_degil` dediğin belge de ince pakete gelebilir. Bu bilinçlidir; belgeyi yeniden,
     bağımsız değerlendir (yine `kanit_degil` olabilir).
3. Cevabı YALNIZ JSON olarak (açıklama, kod çiti yok) `work/<aşama>/<doc_id>.out.json`'a yaz.
   Paket dosyalarını (`<doc_id>.json`), `decisions.jsonl`'i ve başka dosyaları değiştirme.
4. Çok paket varsa alt ajanlar kullanabilirsin: her birine bir grup paket ve bu bölümün
   2-3. maddelerini ver; birbirlerinin dosyalarına yazmasınlar.
5. `bidr decide apply -w WS --stage <coarse|fine> --model <ajan adı>` (`next` tam komutu verir;
   `<ajan-adı>` yazıyorsa kendi adını koy, ör. `claude-code:sonnet`).
6. Sonuç:
   - Çıkış 1 / "geçersiz": `work/<aşama>/GECERSIZ.md`'deki paketlerin cevabı şemaya uymuyor ya da
     JSON değil. Yalnız onları hata mesajına göre yeniden yaz, 5'e dön. Aynı paket üç denemede
     hâlâ geçersizse dur ve kullanıcıya bildir.
   - "alıntısı tutmayan": kod o eşleşmeyi reddetti ve kullanmaz. Bir kez yeniden dene: belgede
     birebir geçen cümleyi kopyala ya da eşleşmeyi çıkar. Uydurma alıntıyla geçirmeye çalışma.
   - Kaba `apply` çıktısındaki `olcut_var/olcut_yok/kanit_degil/eşleşme` sayaçları ince aşamadan
     önce 0 görünür; bu normaldir (yalnız ince kararlar sayılır). Durumu `bidr next` belirler.
7. `bidr next` ile devam.

## Görsel okuma (transcribe)

Düşük kaliteli (taranmış/görsel) belge yoksa aşama kendiliğinden "atlandi" olur. Varsa:
`bidr transcribe prepare -w WS --all-low-quality` → `work/transcribe/README.md`'yi oku; her
`<doc_id>/` klasöründeki görüntüleri kendin oku ve yalnız gördüğünü `<doc_id>.out.json`'a
yaz (okunamayan yeri uydurma, README'nin işaretleme kuralına uy) → `bidr transcribe apply -w WS
--model <ajan adı>`. `work/transcribe/GECERSIZ.md`'deki paketleri yeniden yap; `bidr next`.

## Birimi belirsiz OCR'lı belgeler (belirsiz_okuma)

İnce karardan sonra `birim_iliskisi: belirsiz` kalan ve metni OCR'dan gelen belgeler bir kez
görsel okumayla yeniden okunur; aday yoksa aşama kendiliğinden biter. Varsa: `bidr transcribe
prepare -w WS --belirsiz` → yukarıdaki "Görsel okuma" kurallarıyla cevapsız her paketi oku (önce
hepsini bitir, sonra tek `apply`) → `bidr transcribe apply -w WS --model <ajan adı>` → `bidr next`
(metni değişen belgeler için identify → candidates → kaba → ince karar yeniden; metni aynı
kalanın kararı korunur). Birimi kadro adından, grup/klasör bağlamından ya da "klasör bölüm
arşividir" varsayımından çıkarma: metin söylemiyorsa yine `belirsiz` de. Yeniden okumadan sonra
da belirsiz kalanlar ikinci tura girmez; komisyona gider (gaps.md "Birim aitliği doğrulanmalı").

## Görsel betimleme (describe)

Metni az ya da hiç olmayan görüntüler (laboratuvar, derslik, etkinlik, toplantı, tabela, ödül
fotoğrafı, afiş) OCR'la kanıt olamaz; betimlemeleri olabilir. Böyle belge yoksa aşama "atlandi".
Varsa: `bidr describe prepare -w WS --auto` → `work/describe/README.md`'yi oku; her `<doc_id>/`
klasöründeki görüntülere kendin bak ve `<doc_id>.out.json` yaz:
- YALNIZ görüneni: sahne/mekân türü, sayılabilir nesneler yaklaşık sayılarla, görünen yazılar
  (tabela, afiş, ekran) BİREBİR, etkinlik türü, kalabalık büyüklüğü;
- görüntüde yazmayan tarih/yer/kişi adı yok (kod, görünen yazılarda geçmeyen yılı reddeder);
- kimseyi tanımaya çalışma; yüz/saç/kıyafet/cinsiyet/yaş betimlemesi yok (KVKK; kod reddeder).
  Kişiler yalnız sayı ve rolle: "~40 dinleyici", "1 konuşmacı";
- görüntü aslında metin sayfasıysa `icerik: belge_sayfasi` (betimlenmez; aşağıya bak).
→ `bidr describe apply -w WS --model <ajan adı>`. `work/describe/GECERSIZ.md`'deki paketleri
yeniden yap.

**'Metin sayfası' sonucu (`icerik: belge_sayfasi`) engel değil, uyarıdır:** `bidr next` describe
aşamasını bitti sayar ve `Uyarı: N belgeyi ajan 'metin sayfası' saydı … bidr transcribe prepare
… --only <doc_id>` satırını gösterir; hat bu yüzden durmaz. Yine de bu, atlanmaması gereken
önerilen iştir: o belgenin metni OCR çöpü olarak kalır ve yazıya geçirilmedikçe kanıt olarak
değerlendirilemez. Uyarıdaki komutu çalıştırıp transcribe paketini cevapla (yukarıdaki
"Görsel okuma"); yapmadıysan bitirirken kullanıcıya hangi belgelerin metinsiz kaldığını söyle.

Betimleme belgenin metni olur ve başında "GÖRSEL BETİMLEME" işareti taşır: karar
paketlerinde alıntı bu betimlemeden gelir; kanıtı abartma (bir fotoğraf tesisin varlığını
gösterir, kullanım sıklığını ya da iyileştirmeyi göstermez).

## Faaliyet kayıtları (faaliyet)

`bidr faaliyet -w WS` (belirleyici, model yok) ince kararların faaliyet alanlarından aynı
toplantı/etkinliğin belgelerini bağlar → `faaliyetler.json`. Audit'ten önce çalışır; kararlar
değişince (yeniden karar, ikinci arama) `bidr next` yeniden ister. "Yalnız duyuru" uyarısı engel
değildir ama metinde o faaliyet için "düzenlenmiştir" yazılamaz (yazım paketine özeti girer);
kullanıcıya gerçekleşme belgesinin (tutanak, katılım listesi, rapor) eksik olduğunu söyle.

## Denetim (audit): OD, eksikler, inceleme tablosu

1. `bidr audit -w WS --profile <profil>` (`next` tam komutu verir). Çıktı: `review.xlsx`,
   `gaps.md`, `audit-olcutler.json`. Komutun yazdığı OD dağılımını ve öncelikli eksikleri
   kullanıcıya özetle (sayıları çıktıdan al).
2. DUR: `review.xlsx`'teki KARAR sütununu (kabul/ret/duzelt) **kullanıcı** doldurur. Kararı sen
   verme, tabloyu sen doldurma (tek istisna aşağıdaki yetki devri). Kullanıcı isterse satırları birlikte gözden geçir: önce turuncu
   (OD4/OD5'e yükselten, özellikle "ÖNERİ etiket") ve sarı (düşük güven) satırlar. Önerin
   olabilir ama karar ve yazım kullanıcının.
   **Yetki devri.** Kullanıcı açıkça "inceleme tablosunda karar vermeyeceğim, sen devam et" (ya
   da aynı anlamda bir söz) derse — sessizlik, "devam et" ya da "hızlı bitir" yetki devri değildir —
   kararları kullanıcı yetkisiyle sen verirsin:
   - Önce kullanıcıya ne yapacağını bir kez söyle (kural aşağıda; rapor TASLAK kalacak).
   - Tabloyu bidr ortamının Python'u ve openpyxl ile doldur (yalnız KARAR ve NOT hücreleri;
     sütun/sayfa yapısını bozma). Her satırın KARAR'ını yaz ve aynı satırın NOT'una `ajan (kullanıcı yetkisiyle)` yaz
     (gerekçe varsa ardına: `ajan (kullanıcı yetkisiyle): <kısa gerekçe>`).
   - Güveni düşük (`güven: dusuk`, sarı) eşleşmeler `ret`. Güveni orta/yüksek ve işaretsiz satır
     `kabul` (alıntıyı model seçti, kod belgede doğruladı; içerik beğenisiyle ret yok).
   - İşaretli satırlara (belge başına gruplanmış) yeni bir alt ajan belge metnine
     (`text/<doc_id>.txt`) bakarak karar verir; işaretsiz satırlara bakmaz. İşaretli: birim
     aitliği doğrulanmalı ya da `birim_iliskisi_kod`; dönem dışı, `tarih_dogrulanmali`,
     `guncellik_dogrulanmali`; `kurum_geneli`; OD4/OD5'e yükselten.
     Birim: metinde birimin adı, programı, ders kodu, bölüm sayfası ya da kurulu geçiyorsa `kabul`;
     başka birimin belgesi olduğu açıksa ya da birimi gösteren hiçbir ifade yoksa `ret` (sinyal
     uydurma). Dönem: metinde rapor yılına ait tarih ya da ifade ("2025 yılı içerisinde") varsa ya
     da yapı belgesi rapor yılında yürürlükteyse `kabul`; yalnız dönem dışı olaysa `ret`. Kurum
     geneli: alıntı birimin fakültesinin ya da bütün birimlerin maddesindense `kabul` (tavanı kod
     uygular); başka fakültenin/bölümün maddesiyse `ret`. OD4+: alıntı izleme sonucunu ya da ona
     dayanan yapılmış değişikliği gösteriyorsa `kabul`; öneri, niyet ya da bilgilendirmeyse `ret`.
   - Her `ret`in NOT'unda belgeden somut neden olur ve gerekçe belgeyle çelişemez: metinde
     birimin adı ya da ders kodu varken "birim doğrulanamıyor", içerik varken "yalnız başlık"
     yazılmaz. Somut neden kurulamıyorsa satır `kabul`. `duzelt`, kanıt adı ve bağlantı
     düzeltmesi yapma; OD'yi yükseltmek için karar verme.
   - Yetki yalnız review.xlsx kararlarını kapsar; hakem cevapları ve `bidr verify karar` için
     ayrıca açık söz gerekir.
   - Rapor TASLAK kalır: render'ın TASLAK damgası yalnız doğrulanmamış metne bakar, bu yüzden
     raporu sen TASLAK diye bildirirsin. Bitirirken ve her özetinde "kararlar ajan tarafından,
     kullanıcı yetkisiyle verildi; rapor kullanıcı tabloyu gözden geçirene kadar TASLAK" de;
     ajanın verdiği kabul/ret sayılarını (işaret türüne göre) ve birim sinyali olmadığı için
     reddedilen belgeleri söyle. Kullanıcı sonra tabloyu düzeltirse `bidr audit
     apply`'dan yeniden yürür.
3. Kullanıcı "bitti" deyince (yetki devrinde sen bitirince) `bidr audit apply -w WS`. Çıkış 1: geçersiz kararlar listelenir;
   kullanıcıya göster, düzeltmesini iste.
4. `slot-tags-oneri.yaml` oluştuysa kullanıcıya söyle: yuva etiketi önerileridir; paket
   verisine (`bidr/data/criteria/`) sen işleme.
5. OD önerisi ölçüt düzeyindedir (PUKÖ zinciri, `docs/AUDIT.md`); belgeye OD yazma, OD'yi
   yükseltmek için eşleşme uydurma. Eksik kanıt `gaps.md`'de: kullanıcıya hangi belgenin
   gerektiğini oradan söyle.

## İkinci arama (ikinci_arama, isteğe bağlı)

Audit'ten sonra kanıtsız/zayıf ölçütler için arşivde ters arama (`docs/MODEL_LAYER.md` "İkinci
arama"). `bidr arama prepare -w WS --profile <profil>` → `work/ikinci_arama/README.md`; her
`<doc_id>.json` bir ince karar paketidir, kuralları "İş paketi döngüsü"yle aynı (birebir alıntı;
uymuyorsa `olcut_yok`/`kanit_degil` dürüst ve beklenen cevaptır, zorlama) → `bidr arama apply -w
WS --model <ajan adı>`. Kabul edilen eşleşme decisions.jsonl'i değiştirir: `bidr next` önce
faaliyet ve audit'i yeniden ister; yeni satırlar (işaret `ikinci_arama`) review.xlsx'te
**kullanıcının** kararını bekler (yetki devri kuralları aynı). Atlamak kullanıcının kararıdır:
kullanıcı açıkça isterse `config.yaml`'a `rapor: {ikinci_arama: false}` yazılır; status'ta
"atlandi" görünür. Kendiliğinden atlama.

## Kanıt adları ve parça adları (name)

`bidr name prepare -w WS` → `work/name/README.md`; her `<doc_id>.json` için kısa, resmî bir
kanıt dosyası adı yaz (3-7 sözcük; belgenin ne olduğu; kişi adı, unvan, e-posta YOK) →
`bidr name apply -w WS --model <ajan adı>`. Reddedilenler `work/name/GECERSIZ.md`'de. Ad
önceliği insan > model parça adı > model > kural: kullanıcı review.xlsx'te değiştirebilir.
Birleşik/derleme dosyalar (DERLEME satırı "evet") adı olsa da kendiliğinden yeniden paketlenir:
alıntılar farklı parçalardansa `parca_adlari`'na her yuvanın parçasının adını yaz. Bu adım
atlanmaz; `bidr next` aday kalmayınca bitirir.

## Dosyalama (file) ve bağlantılar

`bidr file -w WS` onaylı kanıtları `evidence/<A>/<A.1>/<A.1.2>/[1-OD3]. Ad.pdf` olarak
kopyalar, `evidence-index.csv` yazar. Raporda kanıt adı tıklanabilir bağlantı olur:
kamuya açık belge yayımlandığı adrese (belge metnindeki web adresi; kullanıcı review.xlsx
"bağlantı" sütunuyla düzeltir), yayımlanmamış belge kanıt klasöründeki yoluna
(`config.yaml` `rapor.kanit_kok_baglanti`; klasörü yüklemek kullanıcının işi). `bidr next`
bağlantısız kanıt uyarısı verirse kullanıcıya gaps.md "Bağlantısı olmayan kanıtlar" listesini
göster; adres uydurma, yükleme yapma, config'i kendin doldurma (kök adresi kullanıcı verir).

## Metin yazımı (write)

`bidr write prepare -w WS` → `work/write/README.md`. Her `<ölçüt>.json` paketinin `istem`i
görevin tamamıdır: yalnız KANITLAR listesindekine dayan, her cümle `[n_ODk]` atfı, önerilen
OD'nin üstünde olgunluk dili yok, gelecek vaadi yok (`[komisyon]` işareti yalnız komisyon
bilgisi verilmişse; rapora girmez). FAALİYETLER bölümü kanıtların bağlı olduğu toplantı/etkinlikleri
verir: "düzenlenmiştir/gerçekleştirilmiştir" yalnız gerçekleşmesi kanıtlı faaliyet için ve
gerçekleşme kanıtına atıfla; "YALNIZ DUYURU" faaliyet için "duyurulmuştur/planlanmıştır". Cevap
`work/write/<ölçüt>.out.json` → `bidr write apply -w WS --model <ajan adı>`; geçersizler
`work/write/GECERSIZ.md`'de. Görevin eski sürümüyle yazılmış metinler geçerli kalır (uyarı);
yeniden yazmak isteğe bağlıdır.

## Doğrulama (verify) ve yeniden yazım döngüsü

**Kural: yazmak, doğrulamak ve yeniden yazmak ayrı, taze ajanların işidir.** Metni yazan ajan
(ya da sen, yazdıysan) doğrulama paketini cevaplamaz; her doğrulama turu ve her yeniden yazım
turu yeni bir alt ajana verilir (önceki turun bağlamı olmadan; yalnız paketin `istem`i).
Alt ajan açamıyorsan dur ve kullanıcıya söyle; aynı bağlamda doğrulama yapma.

1. `bidr verify prepare -w WS`: kod denetimi (atıf, alıntı belgede mi, OD aşımı); geçemeyen
   metin model işine gitmeden reddedilir.
2. Taze doğrulayıcı ajan `work/verify/README.md`'ye göre her cümle için
   destekleniyor/kismen/desteklenmiyor + gerekçe yazar; yalnız atıf yapılan kanıtın alıntısına
   ve bağlamına bakar, iyi niyetle tamamlamaz. → `bidr verify apply -w WS --model <ajan adı>`.
3. Reddedilen ölçüt varsa `bidr next` şunu söyler: `bidr write prepare -w WS --reddedilenler`.
   Bu, istemin sonuna doğrulayıcının bütün gerekçelerini (cümle bazlı, beş soru denetiminin
   "uydurma şüphesi", kod denetimi) ve reddedilen metni ekleyen yeni paket yazar. Taze bir yazar ajan yeniden yazar (desteklenmeyen cümleyi kanıtın gösterdiği
   kadarına indirir ya da çıkarır; yeni iddia eklemez) → `bidr write apply` → 1'e dön.
4. Tur sayısı metinde tutulur. `rapor.yeniden_yazim_siniri` (vars. 2) turdan sonra hâlâ
   reddedilen ölçüt için `bidr next` "KULLANICI gerekli" der. DUR: reddedilen cümleleri ve
   gerekçeleri kullanıcıya göster. Seçenekler kullanıcının: kanıt eklemek, komisyon bilgisi
   vermek (`rapor-notlari.yaml`), ya da `bidr verify karar -w WS <ölçüt> cikar` (metin rapora
   girmez) / `tekrar` (bir tur daha). Bu komutu yalnız kullanıcı söyleyince çalıştır.

## Güçlü / Gelişmeye Açık Yönler (yonler)

Şablonun son tablosunda A, B, C, D alanlarının her biri için iki hücre. `bidr yonler prepare
-w WS` → `work/yonler/README.md`; her `<alan>.json` paketinin `istem`i görevin tamamıdır: güçlü
yön YALNIZ o alanın doğrulanmış ölçüt metninden, gelişmeye açık yön YALNIZ audit bulgusundan
(eksik PUKÖ halkası, düşük OD, kanıtsız ölçüt); her cümle ölçüt kodunu parantez içinde taşır
"(B.1.1)"; öğüt ("-malıdır", "önerilir") ve vaat ("yapılacaktır") yok. Dayanağı olmayan liste
boş kalır, madde uydurulmaz. → `bidr yonler apply -w WS --model <ajan adı>`.
Doğrulama aynı `bidr verify prepare|apply` akışındadır (`work/verify/yonler/README.md`; taze,
maddeleri yazmamış ajan). Reddedilen alan için `bidr next` `bidr yonler prepare -w WS
--reddedilenler` der (taze yazar). Sınırdan sonra hâlâ reddedilen alanın hücreleri şablon
yönergesiyle kalır ve rapor TASLAK olur: gerekçeyi (`verify-yonler.jsonl`) kullanıcıya göster.

## Rapor (render)

`bidr render -w WS` FR-0833 şablonunu (`config.yaml` `rapor.sablon`) doldurur → `report.docx`.
Şablon yolu yoksa `bidr next` kullanıcıdan istenmesini söyler; yolu kullanıcıdan al, uydurma.
Belge şu durumlarda TASLAK damgalıdır ve render nedenleri yazar; kullanıcıya söyle:
doğrulanmamış metin; boş ya da şablon yönergesi kalan güçlü/gelişmeye açık yön hücresi;
kapakta "Raporu Hazırlayanlar" yer tutucusu (`rapor.hazirlayanlar` boş: kişileri kullanıcıdan
al, answers.yaml `hazirlayanlar` ile `bidr init`; ad, e-posta uydurma); kapsam kararı gereken
ölçüt.

Ölçüt kapsamı (bidr/render/kapsam.py): `bolum`/`ortak` ölçütte kanıt yoksa "kanıt
bulunamamıştır" yazılır; `baska_birim` (birimin doldurma sorumluluğunda değil) ölçüte kısa
kapsam ifadesi yazılır, kanıt yokluğu yazılmaz; `karar_gerekli` ölçüt gaps.md "Kapsam kararı
gereken ölçütler"de sorulur. Bu KULLANICININ kararıdır: soruyu göster, cevabını
`config.yaml` `rapor: {kapsam: {<ölçüt>: bolum|ortak|baska_birim}}` olarak yalnız kullanıcı
söyleyince yaz, sonra `bidr render`.

## Biçim denetimi (denetle)

Render'dan sonra `bidr denetle -w WS`: report.docx'i kılavuz biçim kurallarına göre salt okur →
`denetim.json`. Kritik bulgu varsa (çıkış 1) `bidr next` "yayıma hazır değil" ve "KULLANICI
gerekli" der: DUR, kritik bulguları (kod, yer, mesaj) kullanıcıya göster. Düzeltme kaynakta
yapılır (doğrulanmamış metin, kapsam kararı, hazırlayanlar, şablon, kanıt klasörü) ve `bidr
render` → `bidr denetle` yeniden; report.docx'i elle düzeltme. Rapor yeniden üretilince ya da
elle değişince denetim eskir. Uyarılar engel değildir; kullanıcıya özetle (ör. paragraf sonrası
aralık kurumdan sorulacak).

## Teslim paketi (teslim, isteğe bağlı)

Denetim geçince `bidr teslim -w WS`: `WS/teslim/` + `teslim.zip` (report.docx, ölçüt klasörlü
kanıtlar, web kanıtlarının tarihli PDF kopyaları, kanıt dizini). Varsayılan mod `rapor.teslim:
dekanlik` (bağlantı verilmez, dosyalar teslim edilir). Çıkış 1: `EKSIK.txt`'teki eşleşmeyen satırları
kullanıcıya göster. Maskeleme başarısız ya da yapılmamışsa kanıt paketten çıkmaz; özgün dosya girer,
dizinde "elle bakılmalı" yazar: bu listeyi kullanıcıya ayrıca söyle. Web kanıtının adresi bilinmiyorsa
uydurma; kullanıcıdan review.xlsx "bağlantı" sütununa yazmasını iste.

## Bitirirken

Çalışma günlüğü tutuyorsan (ör. kullanıcıya ya da bir dosyaya zaman damgalı adımlar) saati her
seferinde sistem saatinden al (`date '+%Y-%m-%d %H:%M'`; Windows `Get-Date -Format "yyyy-MM-dd HH:mm"`);
saat tahmin etme, önceki satırdan türetme.

Kullanıcıya kısa özet: biten aşamalar, bekleyen aşama ve neden, uyarılar (OCR'sız belgeler,
reddedilen eşleşmeler), insan kararı gereken şey. Sayıları `bidr status -w WS`'den al; uydurma.
