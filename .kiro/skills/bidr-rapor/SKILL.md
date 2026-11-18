---
name: bidr-rapor
description: Kurulu bir bidr çalışma alanında BİDR rapor hattını yürütür - `bidr next`'in söylediği adımı yapar, model aşamalarında iş paketlerini ajan olarak cevaplar (karar, kanıt adı, metin yazımı, doğrulama), yeniden yazım döngüsünü yürütür, kapılara ve insan onayına uyar. Tetik - "raporu hazırla", "BİDR raporu", "devam et", "nerede kaldık", "sıradaki adım", "kanıtları eşle", "decide paketleri", "metinleri yaz", "raporu üret". Kullanma - kurulum veya config değişikliği (bidr-kur), hakem sorularını kullanıcıya sormak (bidr-hakem).
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
   - "Bütün aşamalar bitti" → rapor hazır; bitirirken özetle. Kanıt klasörü, rapor metni,
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
   - Güveni düşük (`güven: dusuk`, sarı) eşleşmeler `ret`. Diğerlerinde alıntı yuvayı açıkça
     karşılıyorsa `kabul`, karşılamıyorsa `ret`; emin olmadığın satır `ret`. `duzelt`, kanıt adı ve
     bağlantı düzeltmesi yapma; OD'yi yükseltmek için karar verme.
   - Yetki yalnız review.xlsx kararlarını kapsar; hakem cevapları ve `bidr verify karar` için
     ayrıca açık söz gerekir.
   - Rapor TASLAK kalır: render'ın TASLAK damgası yalnız doğrulanmamış metne bakar, bu yüzden
     raporu sen TASLAK diye bildirirsin. Bitirirken ve her özetinde "kararlar ajan tarafından,
     kullanıcı yetkisiyle verildi; rapor kullanıcı tabloyu gözden geçirene kadar TASLAK" de;
     ajanın verdiği kabul/ret sayılarını söyle. Kullanıcı sonra tabloyu düzeltirse `bidr audit
     apply`'dan yeniden yürür.
3. Kullanıcı "bitti" deyince (yetki devrinde sen bitirince) `bidr audit apply -w WS`. Çıkış 1: geçersiz kararlar listelenir;
   kullanıcıya göster, düzeltmesini iste.
4. `slot-tags-oneri.yaml` oluştuysa kullanıcıya söyle: yuva etiketi önerileridir; paket
   verisine (`bidr/data/criteria/`) sen işleme.
5. OD önerisi ölçüt düzeyindedir (PUKÖ zinciri, `docs/AUDIT.md`); belgeye OD yazma, OD'yi
   yükseltmek için eşleşme uydurma. Eksik kanıt `gaps.md`'de: kullanıcıya hangi belgenin
   gerektiğini oradan söyle.

## Kanıt adları (name, isteğe bağlı)

`bidr name prepare -w WS` → `work/name/README.md`; her `<doc_id>.json` için kısa, resmî bir
kanıt dosyası adı yaz (3-7 sözcük; belgenin ne olduğu; kişi adı, unvan, e-posta YOK) →
`bidr name apply -w WS --model <ajan adı>`. Reddedilenler `work/name/GECERSIZ.md`'de. Ad
önceliği insan > model > kural: kullanıcı review.xlsx'te değiştirebilir.

## Dosyalama (file) ve bağlantılar

`bidr file -w WS` onaylı kanıtları `evidence/<A>/<A.1>/<A.1.2>/[A.1.2-1-OD3] Ad.pdf` olarak
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
bilgisi verilmişse; rapora girmez). Cevap `work/write/<ölçüt>.out.json` → `bidr write apply
-w WS --model <ajan adı>`; geçersizler `work/write/GECERSIZ.md`'de.

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
   Bu, istemin sonuna doğrulayıcının cümle bazlı gerekçesini ve reddedilen metni ekleyen yeni
   paket yazar. Taze bir yazar ajan yeniden yazar (desteklenmeyen cümleyi kanıtın gösterdiği
   kadarına indirir ya da çıkarır; yeni iddia eklemez) → `bidr write apply` → 1'e dön.
4. Tur sayısı metinde tutulur. `rapor.yeniden_yazim_siniri` (vars. 2) turdan sonra hâlâ
   reddedilen ölçüt için `bidr next` "KULLANICI gerekli" der. DUR: reddedilen cümleleri ve
   gerekçeleri kullanıcıya göster. Seçenekler kullanıcının: kanıt eklemek, komisyon bilgisi
   vermek (`rapor-notlari.yaml`), ya da `bidr verify karar -w WS <ölçüt> cikar` (metin rapora
   girmez) / `tekrar` (bir tur daha). Bu komutu yalnız kullanıcı söyleyince çalıştır.

## Rapor (render)

`bidr render -w WS` FR-0833 şablonunu (`config.yaml` `rapor.sablon`) doldurur → `report.docx`.
Şablon yolu yoksa `bidr next` kullanıcıdan istenmesini söyler; yolu kullanıcıdan al, uydurma.
Doğrulanmamış metin varsa belge TASLAK damgalıdır; bunu kullanıcıya söyle.

## Bitirirken

Çalışma günlüğü tutuyorsan (ör. kullanıcıya ya da bir dosyaya zaman damgalı adımlar) saati her
seferinde sistem saatinden al (`date '+%Y-%m-%d %H:%M'`; Windows `Get-Date -Format "yyyy-MM-dd HH:mm"`);
saat tahmin etme, önceki satırdan türetme.

Kullanıcıya kısa özet: biten aşamalar, bekleyen aşama ve neden, uyarılar (OCR'sız belgeler,
reddedilen eşleşmeler), insan kararı gereken şey. Sayıları `bidr status -w WS`'den al; uydurma.
