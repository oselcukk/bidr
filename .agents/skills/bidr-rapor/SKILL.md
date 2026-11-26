---
name: bidr-rapor
description: Kurulu bir bidr çalışma alanında BİDR rapor hattını yürütür - `bidr next`'in söylediği adımı yapar, model aşamalarında iş paketlerini ajan olarak cevaplar (karar, ikinci arama, kanıt adı, metin yazımı, doğrulama), yeniden yazım döngüsünü ve biçim denetimini yürütür, kapılara ve insan onayına uyar. Tetik - "raporu hazırla", "BİDR raporu", "devam et", "nerede kaldık", "sıradaki adım", "kanıtları eşle", "decide paketleri", "metinleri yaz", "raporu üret". Kullanma - kurulum veya config değişikliği (bidr-kur), hakem sorularını kullanıcıya sormak (bidr-hakem).
---

# bidr-rapor

Çalışma alanını `AGENTS.md` ve `config.yaml` (içinde `bidr:` bölümü) belirler. `bidr`
yerine AGENTS.md'deki tam yolu kullan. WS = çalışma alanının yolu.

## Oturum başında: bidr güncel mi?

`bidr guncel -w WS` çalıştır. "denetlenemedi" (çevrimdışı, git klonu değil) engel değildir; devam et.
"N commit geride" ise kullanıcıya söyle ve güncellemeyi **aşama sınırında** yap: açık iş paketlerini
bitir, `apply` çalıştır, sonra `bidr guncelle -w WS` ve yeniden `bidr next -w WS`. Komut yerel
değişiklik, başka dal ya da açık paket görürse dokunmaz ve ne yapılacağını yazar; bunu kullanıcıya
aktar, `git` ile zorlamaya ya da `--yine-de` eklemeye kendin karar verme. `bidr next`'in sonundaki
"Yeni bidr sürümü var" satırı da aynı anlama gelir.

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

## Paralel ajanlar (parça listeleri)

Model aşamasında `bidr next` bir `Paralel:` satırı yazar (aşama başına karar ve gerekçe
`bidr/data/pipeline.yaml` `paralel`):

- `Paralel: bölünmez` (yonler) ya da `gerekmez` (paket sayısı eşiğin altında) → tek ajan yapar.
- `Paralel: bu aşama N ajanla paralel yapılabilir` →
  1. `bidr parcala -w WS <aşama>` cevapsız paketleri N AYRIK listeye böler:
     `work/<klasör>/_parca/<k>.txt` (satır başına bir paket yolu; write'ta aynı alt bölümün
     ölçütleri, ör. A.1.x, aynı listede).
  2. N alt ajan başlat; her birine YALNIZ bir parça dosyasını ve bu aşamanın bu skill'deki
     kurallarını ver (talimat tek ajanınkiyle aynı: README + her paketin `istem`i; rubrik, alıntı
     kuralı, şema değişmez). Her alt ajana açıkça söyle: yalnız kendi listesindeki paketlere
     `.out.json` yazar; başka cevaba dokunmaz; apply/prepare çalıştırmaz; kendisi alt ajan açmaz.
     Doğrulama (verify) parçalarını metni yazan ajanlardan ayrı, taze alt ajanlara ver.
  3. Hepsi bitince bir kez `bidr parca-denetle -w WS <aşama>` (liste dışı yazılmış ya da ezilmiş
     cevabı `_parca/reddedilen/`'e taşır, eskisini geri koyar) ve aşamanın apply komutu (apply de
     aynı denetimi yapar). Reddedilen ya da geçersiz kalan paketler `bidr next`'te yeniden cevapsız
     görünür; yeniden `parcala` ile böl ya da kendin yap.
- Alt ajan desteklemiyorsan parçaları sırayla kendin yap (1.txt, 2.txt, …); sonuç aynıdır.

Paralellik sonucu değiştirmez: her paket tek belgeye (ya da tek ölçüte) aittir ve belgeler arası
bağlantılar (PUKÖ zinciri, faaliyet kayıtları, OD) modelsiz `bidr faaliyet` ve `bidr audit`'te
bütün kararlar birlikte okunarak kurulur. Kota için tavan: `BIDR_PARALEL_AZAMI` ortam değişkeni ya
da config.yaml `rapor.paralel_azami` (en çok 20; varsayılan: 1 paket → 1 ajan, 2–20 → 2, 21–40 → 3,
sonra her 20 pakette +1, 361+ → 20).

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
4. Çok paket varsa `bidr next`'in `Paralel:` satırına uy ("Paralel ajanlar"): `bidr parcala`
   ile ayrık listeler, alt ajan başına bir liste ve bu bölümün 2-3. maddeleri.
5. `bidr decide apply -w WS --stage <coarse|fine> --model <ajan adı>` (`next` tam komutu verir;
   `<ajan-adı>` yazıyorsa kendi adını koy, ör. `claude-code:sonnet`).
6. Sonuç:
   - Çıkış 1 / "geçersiz": `work/<aşama>/GECERSIZ.md`'deki paketlerin cevabı şemaya uymuyor ya da
     JSON değil. apply o cevabı kenara aldı (`<doc_id>.out.json.red<n>.eski`; paket yeniden cevapsız):
     yalnız onları hata mesajına göre YENİ `<doc_id>.out.json` olarak yaz (var olanın üstüne yazma), 5'e
     dön. Aynı nedenle ikinci kez reddedilen belge yeniden istenmez: `work/<aşama>/ELLE-BAKILMALI.md`'ye
     girer, review.xlsx İnceleme sayfasının 1. bölümünde satır olur (insan incelemesi), aşama beklemez; kullanıcıya bildir.
     Bu kural bütün model aşamalarında aynıdır (describe, transcribe, karar, ad, ikinci arama, yazım,
     doğrulama, yönler, kör denetim): şema enum'unda olmayan değer `diger` seçeneği varsa `diger` olur.
     Elle bakılmalı öğeler `bidr elle liste -w WS` ile görünür; kararı (`bidr elle karar … kabul|varsayilan|atla`)
     yalnız KULLANICI verir (review.xlsx İnceleme satırı; panelde İncelemeniz), ajan vermez. Karar kesindir;
     vermeden de hat sürer.
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
--model <ajan adı>`. Görüntüde yazı yoksa her sayfa `okunabilirlik: bos`, `metin: ""` (`[okunamadı]`
değil); cevapta yalnız şemadaki alanlar. apply reddettiği cevabı kenara alır (paket yeniden cevapsız):
`work/transcribe/GECERSIZ.md`'deki gerekçeyle yeniden oku ve yaz; `bidr next`. Aynı nedenle ikinci kez
reddedilen belge `ELLE-BAKILMALI.md`'ye girer (metni OCR'da kalır, aşama beklemez); kullanıcıya bildir.

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
- `yer`/`icerik`/`kalabalik` yalnız şemadaki değerlerden; listede olmayan yer (pano, duvar …) `diger`;
  gerçekten okuyamadığın yazıyı `gorunen_yazilar`'a yazma (kod OCR'la karşılaştırır).
→ `bidr describe apply -w WS --model <ajan adı>`. apply reddettiği cevabı kenara alır (paket yeniden
cevapsız): `work/describe/GECERSIZ.md`'deki gerekçeyle görüntüye yeniden bak ve yaz. Aynı nedenle ikinci
kez reddedilen belge `ELLE-BAKILMALI.md`'ye girer (betimleme yok sayılır, metni OCR'da kalır, aşama
beklemez); kullanıcıya bildir.

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
2. DUR: kararı **kullanıcı** verir. Kararı sen verme; tabloya yalnız kullanıcının söylediği kararı
   yazabilirsin (aşağıdaki (b) yolu; tek istisna yetki devri). `review.xlsx` son kullanıcı içindir; açılınca yalnız sade sayfalar görünür:
   - **İnceleme**: satır = bir öneri (Madde · Belge (klasördeki dosya) · Önerilen kanıt adı ·
     Belgede ne yazıyor · Neden bu maddeye · Dikkat · Önerimiz · **KARARINIZ** · Doğru madde · Not).
     KARARINIZ: `Kabul` · `Kabul — etkinlik yapıldı` · `Ret` · `Ret — başka maddenin konusu` (+ Doğru
     madde; taşıma olarak uygulanır) · `Başka maddeye taşı` (+ Doğru madde)
     · `Başka maddeye taşı — etkinlik yapıldı`. Ret nedeni başka bir maddeyse düz `Ret` verme: belge
     rapordan düşer (`audit apply` "rapor dışına düştü" uyarısı verir). Bölümler: 1) bakılması gerekenler (düşük güven,
     işaretli, birim onayı, yeniden bakılacak), 2) sorunsuz görünenler (başlık satırındaki
     KARARINIZ hücresinde `Hepsini kabul` seçilirse boş satırlar kabul sayılır; seçilmezse boş satır
     karar bekler), 3) daha önce karar verilenler.
   - **Bölümünüze ait mi**: birimi belirsiz/başka birim sayılan belgeler (Evet/Hayır…).
   - **Maddeler**: önerilen olgunluk düzeyi; "Onayladığınız düzey" boş = öneri.
   - **Nasıl doldurulur**. Teknik sayfalar ("Eşleşmeler", "Ölçüt özeti", birim sayfası) gizlidir;
     `apply` ikisini birleştirir (sade sayfada değişen hücre önce gelir).
   Kullanıcıya iki yol sun: (a) dosyayı kendisi doldurur; (b) **sohbette tek tek sor**: 1. bölümden
   başlayarak her satır için kısa sor — "Belge `<özgün dosya adı>` → `<madde>`; belgede: «alıntı»;
   dikkat: <Dikkat>; önerimiz: <Önerimiz>. Kabul / Kabul — etkinlik yapıldı / Ret / başka madde?" —
   cevabı aynen İnceleme sayfasının KARARINIZ (taşımada Doğru madde) hücresine yaz, kullanıcının
   gerekçesini Not'a ("kullanıcı: …"). 2. bölümü tek soruyla sor ("bunların hepsini kabul ediyor
   musunuz; itiraz ettiğiniz var mı?"); evet derse başlık satırına `Hepsini kabul`, itirazları tek
   tek yaz. Kullanıcının söylemediği hiçbir karar yazılmaz. Tabloyu bidr ortamının Python'u ve
   openpyxl ile yaz (yalnız KARARINIZ/Doğru madde/Not/kanıt adı hücreleri; sütun/sayfa yapısını bozma).
   Önerin olabilir ama karar kullanıcının.
   **Yetki devri.** Kullanıcı açıkça "inceleme tablosunda karar vermeyeceğim, sen devam et" (ya
   da aynı anlamda bir söz) derse — sessizlik, "devam et" ya da "hızlı bitir" yetki devri değildir —
   kararları kullanıcı yetkisiyle sen verirsin:
   - Önce kullanıcıya ne yapacağını bir kez söyle (kural aşağıda; rapor TASLAK kalacak).
   - Tabloyu bidr ortamının Python'u ve openpyxl ile doldur (İnceleme sayfasında yalnız KARARINIZ ve
     Not hücreleri; sütun/sayfa yapısını bozma; `Hepsini kabul` kullanma, her satırı tek tek yaz). Her
     satırın KARARINIZ'ını (`Kabul`/`Ret`) yaz ve aynı satırın Not'una `ajan (kullanıcı yetkisiyle)` yaz
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
   - Yetki yalnız review.xlsx kararlarını kapsar; hakem cevapları, `bidr verify karar` ve
     `bidr write karar` için ayrıca açık söz gerekir.
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
yeniden yazmak isteğe bağlıdır. Geçersiz cevabı taze bir ajan yeniden yazar; ilk yazım +
`rapor.yeniden_yazim_siniri` (vars. 2) yeniden yazımdan sonra kod denetimini hâlâ geçemeyen ölçüt
için `bidr next` "KULLANICI gerekli" ve "Karar bekleyen:" listesi verir. DUR: son cevabı ve kod
denetiminin bulgularını kullanıcıya göster. Karar kullanıcının: `bidr write karar -w WS <ölçüt>
cikar` (rapora girmez) / `tekrar` (bir tur daha) / `kabul` (yalnız bütün bulgular üslup türündeyse:
abartı, slogan, ODn dili; atıf/alıntı bulgusunda komut reddeder; metin yine
doğrulanır). Bu komutu yalnız kullanıcı söyleyince çalıştır.

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
kullanıcıya göster. Maskeleme teslimi durdurmaz;
uyarır (konsol, paketteki `MASKELEME-UYARI.txt`). Maskeleme açıkken kararı bekleyen kanıt (onay bekleyen
bölge, aşırı kapatma, başarısız maskeleme) o anki maskeli hâliyle girer ve "maskeleme kararı bekleyen belge: N"
diye listelenir (`--kararsizlari-disla` ile girmez; `--oldugu-gibi` / bölümün "olduğu gibi devam" seçimi:
"incelenmemiş öneri vardı, olduğu gibi eklendi"); maskeli kopyası olmayan kanıt özgünüyle girer, adıyla
listelenir. `bidr maskele bolgeler -w WS` listesini kullanıcıya göster. Bölge kararını (`bidr maskele karar …
kapat|birak`) ve elle maskelenmiş sürümü (`bidr maskele yukle`) yalnız kullanıcı verir; sonra `bidr
maskele -w WS` ve `bidr teslim` yeniden. Maskeleme seçili değilse paket "kanıtlar maskelenmeden paketlendi,
kişisel veri içerebilir" uyarısıyla üretilir. Web kanıtının adresi bilinmiyorsa
uydurma; kullanıcıdan review.xlsx "bağlantı" sütununa yazmasını iste.

## Kör denetim ve düzeltme (kor_denetim, duzelt; isteğe bağlı)

Yalnız kullanıcı isterse: `bidr denetim prepare -w WS` (rapor render'dan sonra; istenmezse iki aşama
`atlandi`, hat eskisi gibi biter). Kullanıcıya önce söyle: model kotasını belirgin tüketir (yaklaşık bir
rapor aşaması), 30–40 dk sürebilir, puan iç ölçümdür (aynı model ailesi), kalite belgesi değildir.
- `work/kor_denetim/README.md`: paketleri metni YAZMAMIŞ ve doğrulamamış, taze denetçi ajanlara (Opus)
  ver; yazım/doğrulama bağlamını onlara verme. Paralel parça düzeni geçerli. Sonra `bidr denetim apply`.
- `bidr next` → `bidr duzelt prepare`: metin bulguları düzeltme notuyla yazım/yön paketine girer; hat
  write → verify → yonler → render → denetle'ye döner (yazımı ve doğrulamayı ayrı, taze ajanlara ver).
- OD ve kullanılmamış belge önerileri: `kor-denetim.md` bölümlerini kullanıcıya göster; karar yalnız
  kullanıcının sözüyle: `bidr denetim karar -w WS <bulgu_id> kabul|ret --not "…"`. Karar hattı tutmaz:
  metin düzeltmeleri bitince `bidr next` "Bütün aşamalar bitti" der, bekleyen öneriler "Bilgi:" satırında
  durur; kabul sonradan gelirse `bidr next` küçük düzeltme turunu gösterir. "Doğrulanamadı"
  bulgularını işleme.
- Kullanıcının daha önce olduğu gibi kabul ettiği metne (`verify karar`/`write karar` `kabul`) düşen metin
  bulgusu kendiliğinden düzeltilmez: "Kabul edilmiş metne öneri" olarak aynı karar komutuyla kullanıcıya
  gelir (kabul → küçük düzeltme turu, ret → metin aynen kalır). Metin denetim düzeltmesiyle yeniden yazılınca
  karar verilmemiş öneriler `eskidi` olur; onlara karar sorma.
- İkinci denetim (`--ikinci`) yalnız kullanıcı isterse; ölçümdür, düzeltme yapılmaz.
- `denetle` (biçim denetimi, `denetim.json`) ile karıştırma.

## Bitirirken

Çalışma günlüğü tutuyorsan (ör. kullanıcıya ya da bir dosyaya zaman damgalı adımlar) saati her
seferinde sistem saatinden al (`date '+%Y-%m-%d %H:%M'`; Windows `Get-Date -Format "yyyy-MM-dd HH:mm"`);
saat tahmin etme, önceki satırdan türetme.

Kullanıcıya kısa özet: biten aşamalar, bekleyen aşama ve neden, uyarılar (OCR'sız belgeler,
reddedilen eşleşmeler), insan kararı gereken şey. Sayıları `bidr status -w WS`'den al; uydurma.
