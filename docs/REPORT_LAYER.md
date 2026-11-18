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
  ince kararın `kanit_adi`'sı (classify_fine v7).
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
Bir belge bir ölçütte bir kez numaralanır; farklı ölçütlerde ayrı numara alır.
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

## config.yaml `rapor:` bölümü (hepsi isteğe bağlı; kullanıcı yazar, `bidr init` korur)
| anahtar | anlamı |
|---|---|
| `onceki_rapor` | geçen yılın FR-0833 docx'i ya da `<ölçüt>.txt` klasörü (write: üslup ve karşılaştırma) |
| `sablon` | boş FR-0833 şablonu (render) |
| `kanit_kok_baglanti` | kanıt klasörünün yüklendiği kök adres (klasör bağlantıları) |
| `yayin_alan_adlari` | gövde URL'sinin yayın adresi sayılacağı alan adları (ör. `[gtu.edu.tr]`) |
| `yeniden_yazim_siniri` | reddedilen metin için en çok yeniden yazım turu (vars. 2) |
| `kanit_adi_modeli` | `false`: `name` aşaması atlanır |
