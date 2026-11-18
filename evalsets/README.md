# Kontrollü değerlendirme setleri (K6, K7)

bidr kendi doğrulamasıyla "35/35 doğrulandı" diyebilir. Bu bir **iç** denetimdir: metni
yazan sistemin bir başka ajanı, sistemin seçtiği alıntılarla karşılaştırır. Dış doğrulama
değildir. Buradaki setler **bilinen hataları** içeren küçük, **sentetik** belge kümeleridir:
yazıcının, doğrulayıcının ve OD hesabının bu hataları yakalayıp yakalamadığı ölçülür.

Bütün belgeler hayalîdir: Örnek Üniversitesi · Örnek Fakültesi · Örnek Bölümü (başka birim:
Kıyas Bölümü), rapor yılı 2025. Gerçek kurum adı, kişi adı, e-posta yoktur; imzalar yalnız
görev adıdır. `tools/degerlendir.py denetle` bunu (ve alıntıların belgede birebir geçtiğini)
denetler.

## Setler

| Set | Belge | İçerik |
|---|---|---|
| `tuzak/` | 28 | Tek bir bölüm klasörü; her belge bir tuzak (ya da karşılaştırma için temiz belge) |
| `od-sinir/` | 37 (10 vaka) | Ölçüt başına 3–6 belgelik kümeler; OD1–OD5 sınır örnekleri |

**tuzak** türleri: yalnız duyurusu olan etkinlik (t01, t02; gerçekleşme kaydı yalnız t02 için
t03'te); boş anket şablonu (t04); kurum geneli yönerge (t05, t06; bölüm uygulaması t21'de);
çelişkili iki sonuç (t07 %78 ↔ t08 %87); başka bölüme ait belge (t09); çok maddeli üst birim
kararı, yalnız bir maddesi bölümü konu alır (t10); dönem sonrası olay (t11, 2026); önceki yıl
olayı (t12); yürürlükten kalkmış düzenleme (t13, t14 kaldırır); aynı çizelgenin üç sürümü
(t15–t17); yanlış alıntıya davetiye çıkaran yakın metinler (t18 karar/niyet, t19 inceleme/öneri,
t20 web beyanı); bilgisiz ekran (t24); geçen yılın BİDR taslağı (t25); fakülte geneli rapor
(t26); gelecek yılın etkinliğinin bu yıl yayımlanan duyurusu (t27); tarihsiz tutanak (t28).

**od-sinir** vakaları: plansız uygulama (B.3.5, OD3 + "plan belgesi önerilir"); kurum
yönergesi + bölüm uygulaması (B.2.3, OD3); yalnız kurum düzenlemesi (B.4.1, OD2); tek seferlik
anket ≠ sistematik izleme (A.4.2, OD3); kopuk PUKÖ turu, önlem izlemeye dayanmıyor (B.1.5, OD3);
özgünlük kanıtı olmadan OD5 iddiası (B.2.1, OD4); geçerli OD5 (B.3.2, olumlu denetim); bilgisiz
belgeler (A.1.3, OD1); önceki/sonraki yıl uygulaması (B.1.2, OD2); niyet önlem değildir
(B.1.3, OD3).

## beklenen.yaml

Belge kaydı (iki sette aynı; od-sinir'de vakanın `belgeler` listesinde):

```yaml
- dosya: t04-ders-degerlendirme-anket-formu.md   # belgeler/ altına göre
  tuzak: bos_anket
  belge_turu: anket_formu          # identify katalog türü (dönem kuralı ve tür tavanı için)
  tarih: "2025-01-10"              # null: tarihsiz
  kanit: evet                      # evet | hayir | gecmis | dogrulanmali
  birim_iliskisi: kendi            # MODEL_LAYER birim ilişkisi
  en_yuksek_od: 2                  # bu belgeye dayanarak rapor yılı için savunulabilecek en yüksek OD
  gerekce: "..."
  eslesmeler:                      # doğru ince kararın vermesi beklenen eşleşmeler (ideal)
    - {olcut: A.4.2, yuva: A.4.2/1, asama: planla, alinti: "birebir alıntı"}
  naif:                            # tuzağa düşen modelin kaydı (yalnız farklıysa)
    birim_iliskisi: kendi
    eslesmeler: [...]
  bilinen_acik: "..."              # naif kaydı kodun yakalayamadığının gerekçesi (testte xfail)
  kapanan_acik: "..."              # kapanmış eski açık ve kapatan savunma (bilgi)
  yazilmamali:                     # bu belgeye dayanarak yazılmaması gereken iddialar
    - iddia: "Anket uygulanmış ve sonuçları değerlendirilmiştir."
      olcut: A.4.2                 # yoksa bütün metinlerde aranır
      anahtar: ["sonuçları", "ortalama"]   # biri cümlede geçerse (Türkçe harf/büyüklük duyarsız)
      atif_sart: true              # true (varsayılan): yalnız bu belgeye atıf yapan cümlede
      haric: ["önerilmiştir"]      # biri cümlede varsa ihlal sayılmaz
```

`kanit`: `gecmis` önceki yıl olayıdır (süreklilik kanıtı, bu yılın halkası değil);
`dogrulanmali` tarihsiz olaydır (tarih doğrulanmadan sayılmaz). İkisinde ve `hayir`'da
`en_yuksek_od` 1'dir.

Ölçüt beklentisi: tuzak'ta `olcutler: {B.3.5: {od: 3, eksik: [kontrol_et, onlem_al],
not_icermeli: [...]}}`; od-sinir'de vaka alanları `olcut`, `beklenen_od`, `eksik_halka`,
`eksik_kosul`, `not_icermeli`, `bilinen_acik` / `kapanan_acik`. OD kuralları docs/AUDIT.md'dekilerdir (zincir,
örtük plan, kurum geneli tavanı, dönem kuralı). tuzak'ta ayrıca `surum_gruplari` (tek kanıt
sayılması gereken sürümler ve temsilcisi) ve `celiskiler`.

## Çalıştırma

### 1. Kod-only (model yok): audit OD hesabı

```
python tools/degerlendir.py denetle   --set evalsets/od-sinir
python tools/degerlendir.py sentetik  --set evalsets/od-sinir --mod naif --out /tmp/ws-naif
bidr audit -w /tmp/ws-naif
python tools/degerlendir.py karsilastir --set evalsets/od-sinir -w /tmp/ws-naif --md rapor.md
```

`sentetik` beklenen.yaml'daki karar kayıtlarından `decisions.jsonl`, `documents.jsonl` (tür,
tarih, dönem 2025) ve `text/` yazar. `--mod ideal` doğru kararları, `--mod naif` tuzağa düşen
modelin kararlarını verir; `--vaka` tek vakayı alır. Aynı denetim
`tests/test_evalset_od.py`'de (pytest) çalışır.

### 2. Tam tur (model gerektirir; bu turda çalıştırılmadı)

1. Set klasörünü (`evalsets/tuzak/belgeler`) kaynak klasör olarak kullanan bir çalışma alanı
   kurun: `bidr init --sablon` ile cevap dosyası, `birim: Örnek Bölümü`, `donem: 2025`,
   `profil: akademik_bolum`. Dosya adları bidr'a girdi değildir; yine de adları gizlemek için
   klasörü önce `tools/karistir.py` ile karıştırabilirsiniz. Eşleme içerik özetiyle (doc_id)
   yapılır: yalnız ad/klasör değiştiren bozmalar eşlemeyi korur; içeriği değiştirenleri kapatın
   (`--tarama 0 --donustur 0 --birlestir 0 --parcala 0 --bozuk 0`). Karıştırılmamış klasörde
   `inventory.csv` yolu da eşlenir.
2. Hattı `bidr next` ile render'a kadar yürütün (ince karar, audit kararları, file, write,
   verify, render). `beklenen.yaml`'ı ajana göstermeyin.
3. Karşılaştırın:

```
python tools/degerlendir.py karsilastir --set evalsets/tuzak -w WS [--inceleme AUDIT_OUT] \
    --md tuzak-rapor.md --json tuzak-sonuc.json --ajan-paketi /tmp/iddia-paket
```

### 3. Ajan değerlendirmesi (isteğe bağlı)

Anahtar ifade denetimi kaba bir eleme yapar (eşanlamlı ifadeyi kaçırabilir, ilgisiz cümleyi
yakalayabilir). `--ajan-paketi DIR` her yazılmaması gereken iddia için bir iş paketi yazar
(`<belge>--<n>.json`: talimat, iddia, belge metni, ölçüt metninin cümleleri ve atıf yaptıkları
belgeler). Metni yazmamış **taze** bir ajan her paket için `<belge>--<n>.out.json` yazar:
`{"karar": "geciyor" | "gecmiyor", "yerler": [...], "gerekce": "..."}`. Cevaplar
`--ajan-cevaplari DIR` ile tablonun "ajan" sütununa girer.

### 4. Yayıma hazır durum sınaması

```
python tools/degerlendir.py taslak-sinama
```

Gerçek `bidr.verify.run.judge` ve `bidr.render.run.render` ile (sentetik şablon, geçici klasör):
bütün cümleler desteklenince metin `dogrulandi` ve rapor taslak değil; **tek** cümle
`desteklenmiyor` ya da `kismen` ise metin `reddedildi` ve rapor "TASLAK" damgalı; reddedilen
metni insan `cikar` derse metin rapora girmez ve rapor taslak sayılmaz.
`karsilastir` aynı kuralı gerçek çalışma alanında denetler: `verify.jsonl`'de desteklenmeyen
cümlesi olan her metin için metin durumu ve `.bidr-render.json` `taslak` alanı.

## Tablo ve ölçüler

- **Belge sonucu.** `yakalandı`: kanıt olan belgede sayılan OD ≤ `en_yuksek_od`; kanıt
  olmayan / geçmiş / tarihsiz belgede hiçbir halka sayılmamış (sayılan OD 1); başka birime ait
  belgede birim ilişkisi `baska_birim` ya da hiçbir halka sayılmamış. Aksi `kaçırıldı`.
  "Sayılan" audit'in OD'ye kattığı satırlardır (dönem kuralı, kurum geneli tavanı, düşük güven
  ve insan kararları uygulanmış; `audit.run.build` salt okunur çalıştırılır).
- **OD.** `tam` / `-1` / `eksik (-n)` / `fazla (+n)` (sistem − beklenen). Özette `±1` = `-1`
  ve `fazla (+1)`. Fazla OD en ağır hatadır (kanıtsız olgunluk iddiası).
- **Ölçüt.** `audit-olcutler.json` (yoksa audit çekirdeği) OD'si, bir üst düzey için eksik
  halkalar ve beklenen notlar.
- **Sürüm grupları.** `evidence-index.csv`'de grup bir ölçütte tek satır mı (kopyalar dahil).
- **İddialar.** `GEÇTİ` (ihlal: cümle ve yeri), `geçmedi`, `metin yok`; `şüpheli`: anahtar ifade
  var ama atıf başka belgeye.
- **Yayım engeli.** `engelliyor` / `ENGELLEMİYOR` / `metin yok`.

## Bilinen açıklar

`naif` kayıtla audit'in fazla OD verdiği, kodun tek başına yakalayamadığı durumlar
`bilinen_acik` alanıyla işaretlenir ve testte xfail(strict) olur. **Şu an açık yok** (2026-11-19):
ilk turdaki 19 açığın hepsi kod tarafı savunmalarla (docs/AUDIT.md "Kod tarafı savunmalar",
`bidr/audit/savunma.py`) kapandı; naif kayıtlar xfail'siz geçer. Kapanan açık beklenen.yaml'da
`kapanan_acik` (kapatan işaretle) olarak kalır. Model tarafı (ince karar istemi, kanıt ilkeleri)
yine tam turda bu setle ölçülmelidir: savunmalar sözcük düzeyindedir.

| Eski açık | Örnek | Kapatan (audit işareti) |
|---|---|---|
| Gelecek zaman / gerçekleşme kaydı yokluğu denetlenmez (duyuru = uygulama) | t01, t02, t27 | `gerceklesme_kaniti_yok` (+ t27: `tarih.olay_tarihi_en_gec`) |
| Aşama modelin: tek seferlik sonuç "izleme", bilgilendirme "önlem" sayılabilir | t03, A.4.2 vakası | `katilim_izleme_degil`, `bilgilendirme_onlem_degil` |
| Boş form ile dolu sonuç ayrımı OD'de yok | t04 | `bos_form` |
| Birim aitliği ve "kanıt değil" yalnız modelden; audit metne bakmaz | t09, t24, A.1.3 vakası | `birim_iliskisi_kod` (→ `belirsiz`), `bilgisiz_ekran` |
| Madde ilkesi denetlenmez (çok maddeli kararda başka bölümün maddesi) | t10 | `madde_baska_birim` |
| Yürürlükten kalkma bilinemez (yalnız güncellik işareti) | t13 | `yururlukten_kalkmis` (yayımlanan listeye de girmez) |
| Sürüm notu ("revize") önlem sayılabilir | t17 | `surum_notu_onlem_degil` |
| Hariç türler (BİDR taslağı) audit'te yeniden denetlenmez | t25 | `haric_tur` |
| Kurum/fakülte geneli tavanı yalnız yönetmelik/yönerge/senato türünde ya da model söyleyince | t26, B.4.1 vakası | `birim_iliskisi_kod` (→ `kurum_geneli`/`fakulte_geneli`) |
| K→Ö bağı denetlenmez (önlem izleme sonucuna dayanıyor mu) | B.1.5 vakası | `onlem_izlemeye_dayanmiyor` |
| Öneri/niyet önlem sayılabilir | B.1.3 vakası | `niyet_onlem_degil` |
| Özgün halka tek beyanla kurulur (süreklilik, dış tanınma aranmaz) | B.2.1 vakası | `ozgun_kanitsiz` |
| Tür tavanı birim ilişkisine bakmaz: bölümün kendi usul-esası (`yonerge`) `kurum_geneli` işareti alır | t14 | bölümün kendi usul belgesi (`Savunma.own_regulation`) |

Yeni bir açık bulunursa ilgili kayda `bilinen_acik` (gerekçe) eklenir ve bu tabloya satır
girer; kapanınca test XPASS verip başarısız olur (strict): alan `kapanan_acik`'a çevrilir.

## Sınırlar

- Setler küçüktür; oranlar (yakalama yüzdesi) genelleme değil, hata türü başına var/yok
  göstergesidir.
- Anahtar ifade denetimi sözcük düzeyindedir; nihai yargı için ajan paketi ya da insan okuması
  gerekir.
- Çelişkili sonuçlar yalnız metin düzeyinde ölçülür (bidr'da çelişki algılayan kod yok).
- `en_yuksek_od` belge düzeyinde halkanın OD'sidir; ölçüt OD'si zincirle belirlenir.
