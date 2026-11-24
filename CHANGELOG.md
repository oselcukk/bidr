# Değişiklikler

Her birleştirmede (main'e giren her değişiklik) buraya en üste bir satır eklenir: tarih, kısa
açıklama ve kullanıcıyı ilgilendiriyorsa ne yapması gerektiği. `bidr guncelle` güncellemeden sonra
bu dosyanın yeni satırlarını gösterir. Bu dosyadan önceki geçmiş için `git log`.

- 2026-11-24: Belge kimliği maskeli kopyanın baytına bağlı değil (k1-kimlik): maskeli kaynakta `doc_id` özgün
  dosyanın sha256'sından (`inventory.csv` `ozgun_sha256`); maskeli kopya yeniden üretilip baytı değişince kimlik
  ve kayıtlar korunur, metin yalnız gerçekten değiştiyse yenilenir. Eski çalışma alanlarında var olan kimlikler
  korunur (`kimlikler.jsonl`); doğrulanamayan kimlik silinmez, `_oksuz/`a alınır ve `bidr next` durur. Yeni
  komut `bidr kimlik-onar -w WS [--yedek DIR] [--uygula]`: kimliği kaymış belgeleri eski kimliklerine geri
  bağlar. Metni model yazmış (transcribe/describe) belge `--force` olmadan yeniden çıkarılmaz; kaynaktan çıkan
  belgenin okuma paketleri de `kaynaktan-cikarilan/`a taşınır. Güncellemeden sonra maskeli kaynaklı çalışma
  alanında önce `bidr kimlik-onar -w WS` (kuru koşu) çalıştırın.
- 2026-11-23: Paralel model aşamaları: varsayılan ajan sayısı min(20, n, 2 + (n-1)//20) (1 paket → 1, 2–20 → 2,
  sonra her 20 pakette +1, 361+ → 20); mutlak tavan 10 → 20; yeni `taban` ayarı (`rapor.paralel_taban`,
  `bidr parcala --taban`; vars. 2).
- 2026-11-23: İnceleme: yeni KARARINIZ seçeneği "Ret — başka maddenin konusu" (Doğru madde zorunlu, taşıma olarak
  uygulanır). `audit apply`: ret notunda başka ölçüt anılıp hedef verilmemiş ve belge hiçbir satırda sayılmıyorsa
  uyarı "N belge rapor dışına düştü" + satırda bilgi (`ret_hedefsiz_dustu`). Panel bu seçeneği tanıyan sürümle
  birlikte güncellenmeli.
- 2026-11-23: İkinci arama zorlama eşleşme: belge başka ölçütte kabul edilmişse paket istemi o kabulleri ve
  "aynı alıntı/içerik başka ölçüte taşınmaz → olcut_yok" kuralını taşır (yalnız bekleyen/yeni paketler; işlenmiş
  paket yeniden yazılmaz, görev sürümü değişmedi). Aynı alıntı (normalize) başka ölçütte kabulse eşleşme
  `ayni_alinti_kabul` işareti alır; inceleme kartında "Aynı alıntı X ölçütünde zaten kabul" dikkat notu.
- 2026-11-23: Aday üretimi dil farkı: `bidr/data/dil_karsiliklari.yaml` Türkçe–İngilizce karşılık sözlüğü
  (İngilizce belge → Türkçe ölçüt belirteci; ikinci aramada Türkçe ölçüt → İngilizce belge); `doc_types.yaml`
  `olcut_onceligi` (izlence → B.3.2, B.2.2, B.1.3). Aday sayısı ve kanıt sınırı değişmedi; yeniden aday üretimi
  (`bidr candidates`) gerekir.
- 2026-11-23: Aynı kâğıdın ayrı taramaları karardan önce tek grup (OCR metni + sayfa pHash'i): tek model paketi,
  incelemede tek satır (Dikkat'te "Kopyaları: …", gizli `kopyaları` sütunu), karar gruba; başka birim adı yalnız
  bilinen birim listesinden (x6-birim-kopya). Panel bu sütunu okuyan sürümle birlikte güncellenmeli.
- 2026-11-23: Paralel model aşamaları: `bidr parcala` / `bidr parca-denetle`, pipeline.yaml
  `paralel` kararı; `bidr next` bölünebilir aşamada "Paralel:" satırı gösterir (x5-paralel).
- 2026-11-23: `bidr maskele --kaynak` ilerleme dosyasına o an işlenen belgeyi yazar (`suanki`:
  dosya, sayfa/toplam_sayfa, aşama) (x3-suanki).
- 2026-11-23: `bidr maskele --yalniz-oneri`: hiçbir tespit kendiliğinden kapatılmaz, insan kararları
  uygulanır; bölgesiz biçimlerde (docx/xlsx/metin/html) desen başına öneri (x2-oneri).
- 2026-11-23: İnceleme sayfası (review.xlsx) ve istenen-kanitlar.xlsx yeni tasarım
  (gizli 1. satır başlıklar, görünen başlık 5. satırda); review.xlsx okuyucusu değişmedi (x1-excel).
- 2026-11-23: `bidr guncel` / `bidr guncelle` eklendi; `bidr next` günde bir kez yeni sürümü
  hatırlatır (`BIDR_GUNCEL_DENETIM=0` kapatır). Ajanlar oturum başında `bidr guncel` çalıştırır.
