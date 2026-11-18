---
name: bidr-hakem
description: BİDR hakem kuyruğunu kullanıcıya sorar - model kararı ile geçen yılın etiketi arasındaki farkları 5'erli gruplar halinde, her soruda gerekçeli önerinle sunar, kullanıcının kararını `bidr hakem cevap` ile yazar, sonunda uzlaşıyı üretir. Tetik - "hakem soruları", "etiket farkları", "karşılaştırmayı onayla", `bidr next` hakem aşamasında KULLANICI gerekli diyorsa. Kullanma - kurulum (bidr-kur), iş paketleri ve diğer aşamalar (bidr-rapor).
---

# bidr-hakem

Kararı kullanıcı verir; sen önerirsin. Kullanıcının cevabı olmadan hiçbir soruyu cevaplama.
WS = çalışma alanı; `bidr` yerine AGENTS.md'deki tam yolu kullan.

## Adımlar

1. `bidr next -w WS`. Hakem kuyruğu yok ya da eskiyse önce onun verdiği
   `bidr compare-labels -w WS` komutunu çalıştır.
2. `bidr hakem sorular -w WS` sıradaki en çok 5 cevapsız soruyu gösterir (`--json` makine
   için). Her soruda: belge, geçmiş etiket, modelin önerisi (yuva, OD, birebir alıntı,
   gerekçe), seçenekler.
3. Grubu kullanıcıya numaralı olarak, kısa ve onun dilinde sun. Her soru için:
   - ne sorulduğu (model geçmişte olmayan bir ölçüt mü ekliyor / geçmiş etiketi mi
     doğrulamadı / OD mi farklı);
   - alıntı (varsa) aynen;
   - **önerin** ve tek cümle gerekçesi: alıntı ölçütün yuvasını gerçekten karşılıyor mu?
     Alıntı yoksa ya da zayıfsa bunu söyle. Dosya adı veya klasör kanıt değildir.
   - seçenekler: `ekliyor` → `ekle | reddet | belirsiz` (`ekle` için isteğe bağlı OD);
     `itiraz` → `koru | kaldir | belirsiz`; `od_farki` → `od_model | od_gecmis | od=N | belirsiz`.
   Kullanıcıdan tek mesajda cevap iste (ör. "1 ekle, 2 reddet, 3 od=3, 4 koru, 5 belirsiz").
4. Kullanıcının her kararını yaz:
   `bidr hakem cevap -w WS <soru_id> <karar> [--od N] [--not "kullanıcının gerekçesi"]`.
   Kod kararı denetler; geçersizse (çıkış 2) kullanıcıya o soruyu yeniden sor.
   Kullanıcı açıkça "önerin olsun" derse önerini yaz ve `--not "kullanıcı ajan önerisini onayladı"` ekle.
   `belirsiz` geçerli bir cevaptır; soru uzlaşıda açık kalır.
5. Grup bitince 2'ye dön. Kullanıcı ara vermek isterse dur; cevaplar dosyada kalır,
   sonra kalınan yerden devam edilir.
6. Hepsi cevaplıysa `bidr compare-labels -w WS --apply` ve `bidr next -w WS`; kullanıcıya
   eklenen / kaldırılan / OD değişen / açık kalan sayılarını komut çıktısından aktar.

`label-answers.jsonl`'i, `label-review.*`'ı ya da `consensus-labels.jsonl`'i elle düzenleme.
