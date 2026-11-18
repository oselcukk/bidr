---
name: bidr-rapor
description: Kurulu bir bidr çalışma alanında BİDR rapor hattını yürütür - `bidr next`'in söylediği adımı yapar, model aşamalarında iş paketlerini ajan olarak cevaplar, kapılara ve insan onayına uyar. Tetik - "raporu hazırla", "BİDR raporu", "devam et", "nerede kaldık", "sıradaki adım", "kanıtları eşle", "decide paketleri". Kullanma - kurulum veya config değişikliği (bidr-kur), hakem sorularını kullanıcıya sormak (bidr-hakem).
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
   - `henüz yok` → hat burada biter. DUR ve kullanıcıya bildir. Kanıt klasörü, rapor metni,
     docx gibi henüz olmayan çıktıları elle üretme.
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
- görüntü aslında metin sayfasıysa `icerik: belge_sayfasi` (betimlenmez; `bidr next` transcribe önerir).
→ `bidr describe apply -w WS --model <ajan adı>`. `work/describe/GECERSIZ.md`'deki paketleri
yeniden yap. Betimleme belgenin metni olur ve başında "GÖRSEL BETİMLEME" işareti taşır: karar
paketlerinde alıntı bu betimlemeden gelir; kanıtı abartma (bir fotoğraf tesisin varlığını
gösterir, kullanım sıklığını ya da iyileştirmeyi göstermez).

## Denetim (audit): OD, eksikler, inceleme tablosu

1. `bidr audit -w WS --profile <profil>` (`next` tam komutu verir). Çıktı: `review.xlsx`,
   `gaps.md`, `audit-olcutler.json`. Komutun yazdığı OD dağılımını ve öncelikli eksikleri
   kullanıcıya özetle (sayıları çıktıdan al).
2. DUR: `review.xlsx`'teki KARAR sütununu (kabul/ret/duzelt) **kullanıcı** doldurur. Kararı sen
   verme, tabloyu sen doldurma. Kullanıcı isterse satırları birlikte gözden geçir: önce turuncu
   (OD4/OD5'e yükselten, özellikle "ÖNERİ etiket") ve sarı (düşük güven) satırlar. Önerin
   olabilir ama karar ve yazım kullanıcının.
3. Kullanıcı "bitti" deyince `bidr audit apply -w WS`. Çıkış 1: geçersiz kararlar listelenir;
   kullanıcıya göster, düzeltmesini iste.
4. `slot-tags-oneri.yaml` oluştuysa kullanıcıya söyle: yuva etiketi önerileridir; paket
   verisine (`bidr/data/criteria/`) sen işleme.
5. OD önerisi ölçüt düzeyindedir (PUKÖ zinciri, `docs/AUDIT.md`); belgeye OD yazma, OD'yi
   yükseltmek için eşleşme uydurma. Eksik kanıt `gaps.md`'de: kullanıcıya hangi belgenin
   gerektiğini oradan söyle.

## Bitirirken

Kullanıcıya kısa özet: biten aşamalar, bekleyen aşama ve neden, uyarılar (OCR'sız belgeler,
reddedilen eşleşmeler), insan kararı gereken şey. Sayıları `bidr status -w WS`'den al; uydurma.
