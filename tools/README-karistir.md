# karistir — dağınık bölüm klasörü üreteci

`tools/karistir.py`, etiketli bir belge havuzunu gerçek bir bölüm paylaşım klasörüne benzeyen
dağınık bir klasöre dönüştürür. Amaç, bidr'ın kanıtı **dosya adından değil içerikten**
bulabildiğini sınamaktır. Aynı tohum aynı çıktıyı verir (bayt bayt).

Havuz salt okunurdur: hiçbir kaynak dosya değiştirilmez. Gizli eşleme dosyası çıktı
klasörünün dışına yazılır; çıktı klasörüne verilmez.

## Kullanım

```
python tools/karistir.py HAVUZ \
    --manifest HAVUZ/manifest-gizli.csv \
    --out ~/deneme/dagınık --esleme ~/deneme/esleme-gizli.json --tohum 42
```

- `HAVUZ`: havuz kökü. `--manifest` verilmezse `HAVUZ/manifest-gizli.csv` okunur.
- Manifest sütunları: `id,yol,sha256,boyut,bicim,kaynak_turu,birim,atif_rapor,adres,yil,not`
  (`yol` kökten göreli). Betik yalnız `id`, `yol`, `sha256` ve `bicim`'i kullanır; sha256
  uyuşmazlığı ya da eksik dosya eşlemede `uyarilar` altına yazılır.
- `--out`: yok ya da boş olmalı; havuzla iç içe olamaz.
- `--esleme`: JSON; çıktı klasörünün ve havuzun dışında olmalı.
- Oranlar (0–1): `--tarama 0.07 --donustur 0.7 --birlestir 0.2 --parcala 0.35 --kopya 0.1
  --zip 0.15 --bozuk 0.03 --cop 0.05 --kok 0.08` (parantez içi değerler varsayılandır).
- `--arac-kapat pdftoppm,pymupdf,soffice,chrome`: aracı yokmuş gibi say (deneme için).

## Bozmalar

| Bozma | Ne yapar | Gereken araç |
|---|---|---|
| ad + klasör | `scan_0193.pdf`, `IMG_4471.jpg`, `belge son son.pdf`, `Adsız.docx` gibi anlamsız adlar; derinliği 1–4 olan Türkçe/İngilizce karışık klasörler | — |
| `tarama` | (istisna, varsayılan oran 0,07) PDF sayfası ya da görsel → gri ton, ±2,5° döndürme, gürültü; tek sayfa PNG/JPG ya da görsel-PDF, metin katmanı yok (en çok 12 sayfa) | `pdftoppm`, yoksa PyMuPDF |
| `html_pdf` / `html_metin` | HTML → PDF; araç yoksa ya da şans öyle derse düz metin | `soffice`, yoksa Chrome (ağ kapalı) |
| `docx_pdf` | DOCX → PDF | `soffice` |
| `birebir_kopya` | aynı dosyanın farklı adla ikinci kopyası | — |
| `birlestirme` | 2–4 küçük (≤3 sayfa) PDF tek PDF'te | — (pypdf) |
| `parca` | uzun (≥6 sayfa) PDF 2–3 parçaya | — (pypdf) |
| `zip` | bir ya da birkaç çıktı zip içinde; bazılarında iç içe klasör | — |
| `bozuk:kesik` | kaynağın kesik kopyası | — |
| `cop:*` | boş dosya, `.tmp`, `~$…docx` Office kilit dosyası, rastgele bayt, `.DS_Store`, `Thumbs.db` | — |
| `orijinal` | içerik aynen, yalnız adı ve yeri değişir | — |

Araç bulunamazsa ilgili bozma atlanır, eşlemenin `atlananlar` listesine yazılır ve betik
devam eder. Hangi araçların bulunduğu `araclar` alanındadır. Dönüştürülen PDF'ler pypdf ile
sabit üst veriyle yeniden yazılır; bu yüzden çıktı tohuma göre tekrarlanabilir (aynı makinede,
aynı araç sürümleriyle).

Hiçbir çıktı adı (klasörler ve zip içindekiler dahil) kaynak dosya adını, kaynak adının
gövdesini ya da bir `id`'yi içermez (büyük/küçük harf ve aksan duyarsız denetlenir).

## Eşleme biçimi

```json
{
  "surum": 1, "tohum": 42, "oranlar": {...}, "araclar": {"pdftoppm": true, ...},
  "girdi_sayisi": 120, "kapsanan_kaynak": 120, "cikti_sayisi": 151,
  "bozma_sayilari": {"tarama": 20, "zip": 9, ...},
  "atlananlar": [{"id": "K017", "bozma": "docx_pdf", "neden": "soffice yok ..."}],
  "uyarilar":   [{"id": "K020", "uyari": "sha256 manifestle uyuşmuyor"}],
  "dosyalar": [
    {"yol": "Yeni Klasör (3)/scan_0193.pdf", "sha256": "...", "boyut": 48211,
     "kaynak": [{"id": "K004", "sayfalar": "1-3"}, {"id": "K009", "sayfalar": "4-4"}],
     "bozmalar": ["birlestirme:2", "ad_degisti"]},
    {"yol": "eski/Adsız.zip", "sha256": "...", "boyut": 9120,
     "kaynak": [{"id": "K011"}], "bozmalar": ["zip", "ic_ice_klasor"],
     "icerik": [{"yol": "backup/IMG_4471.jpg", "sha256": "...",
                 "kaynak": [{"id": "K011"}], "bozmalar": ["tarama", "gri_ton", "..."]}]}
  ]
}
```

- `dosyalar`: çıktı klasöründeki **her** dosya, `--out`'a göre göreli yolla, ada göre sıralı.
- `kaynak`: dosyanın içeriğini taşıyan kaynak id'leri; `sayfalar` birleştirmede kaynağın
  çıktıdaki sayfa aralığını, parçalamada kaynaktaki sayfa aralığını verir. Çöp dosyalarda boş.
- `icerik`: yalnız zip'lerde; arşivdeki her üye, kendi kaynağı ve bozmalarıyla.
- `bozmalar`: ilk öğe ana bozmadır; `arac:`, `bicim:`, `dondurme:`, `tarayici:` ayrıntıdır.

## Test

`tests/test_karistir.py` geçici klasörde sentetik PDF/DOCX/HTML/PNG üretir (gerçek kurum
verisi, kişi adı, e-posta yok) ve şunları denetler: aynı tohum → aynı çıktı; eşleme her
çıktı dosyasını ve zip üyesini kapsıyor; çıktıda manifest/eşleme sızıntısı yok; hiçbir ad
kaynak adı ya da id içermiyor; araçlar yokken betik çökmüyor; eşleme çıktı içine yazılamıyor.
