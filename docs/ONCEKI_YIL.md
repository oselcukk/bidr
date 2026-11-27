# Geçen yılın raporu (yalnız karşılaştırma)

FR-0833 Değ.No:1 PUKÖ anlatımında "önceki yıllar ile karşılaştırmalı" iyileştirme istiyor. Bölüm geçen yılın
doldurulmuş BİDR raporunu (docx ya da pdf) bir kez verir; bidr ondan ölçüt başına özet çıkarır ve yazım/doğrulama
paketlerine **karşılaştırma bağlamı** olarak koyar.

Kurallar (2026-11-26/27 kararları):
- Geçen yılın belgesi bu yılın kanıtı değildir: kanıt havuzuna, kanıt numaralarına, maskelemeye, teslim paketine
  girmez; metinde ona atıf verilmez. Geçen yıl belgeleri bölüme sorulmaz.
- Açıklamada anılabilir: "2025 yılında X vardı, bu yıl Y yapıldı" — yalnız bu yılın kanıtı bir değişikliği,
  iyileştirmeyi ya da sürekliliği gösteriyorsa, kısa. Geçen yılın metninde olmayanı geçen yıla mal etmek doğrulamada
  ret nedenidir. Geçen yılın OD'si bu yılın OD'sini belirlemez.
- İsteğe bağlıdır (yeni bölümün geçen yılı yok). Raporu olmayan bölümde hiçbir şey değişmez.

## Ayrıştırma: `bidr onceki-yil cek -w <ws> --rapor <dosya>`

Modelsiz (`bidr/onceki/oku.py`) → `<ws>/onceki-yil.json`: ölçüt başına `od`, `od_kaynak`, `od_isaretli`, `aciklama`,
`kanitlar` [{no, od, ad, kod_olcut}].
- docx: `bidr.render.template.find_blocks` blok düzeni; "Açıklamalar:" etiketi silinmişse Kanıtlar'dan önceki tek
  hücreli satır açıklama sayılır (uyarıyla). "Bu kısım için veri bulunmamaktadır." boş sayılır.
- OD: rubrik satırında ötekilerden ayrı biçimlenmiş sütun (kalın / farklı gölge / vurgu: `isaret`); birden çok
  sütun işaretliyse en yükseği (uyarı, özet "OD4–5" gösterir); işaret yoksa kanıt kodlarındaki en yüksek OD
  (`kanit_kodlari`); ikisi de yoksa boş.
- pdf: metin katmanı (pypdf); başlık ölçüt kimliği + ölçüt başlığıyla tanınır; sayfa altbilgisi atılır; OD yalnız
  kanıt kodlarından.
`bidr onceki-yil goster -w <ws> [--olcut A.1.2]`, `bidr onceki-yil kaldir -w <ws>`. Kapısızdır (`check_gate` yok).

## Yazım ve doğrulama bağlamı (`bidr/onceki/baglam.py`)

Ölçütün geçen yıl kaydı varsa `write prepare` (ilk yazım ve `--reddedilenler` yeniden yazımı) istemin SONUNA
`bidr/tasks/write_criterion/onceki_yil.md` bölümünü ekler: kurallar + özet (geçen yıl OD'si, açıklama en çok 1200
karakter, cümle sınırında kısaltılmış, geçen yılın atıfları çıkarılmış; geçen yıl gösterilen belge adları). `verify
prepare` aynı şekilde `bidr/tasks/verify_text/onceki_yil.md` ekler (açıklama en çok 4000 karakter): her karşılaştırma
cümlesi (paragraf içinde de) geçen yılın metnine ve bu yılın kanıtına karşı denetlenir. Pakete ve metin kaydına
`onceki_yil: {kaynak_sha, od}` izi yazılır.

### Parmak izi: neden var olan metinler yeniden yazılmaz

`write prepare` bir metni `kaynak.temel_istem_sha` (temel istemin özeti) ve görev sürümü tutuyorsa güncel sayar
(`zaten_tamam`). Ek bölüm temel istemin **dışındadır** (kör denetim alıntı bölümü gibi): temel istem, görev
sürümleri (`write_criterion` 5, `verify_text` 4) ve `girdi_sha` (kanıt listesi + OD) değişmez. Sonuç:
- raporu olmayan bölümde paket istemi, `istem_sha`, `meta` ve metin kaydı bayt bayt aynıdır (test:
  `tests/test_onceki_yil.py::test_raporsuz_bolumde_paket_ve_izler_aynı`);
- rapor sonradan gelince var olan metinler `zaten_tamam` kalır; bağlam yalnız bir sonraki yazımda girer (yeni kanıt,
  OD değişimi, doğrulama reddi, `--redo`, `--only`);
- yalnız ilgili ölçütün paketi değişir; geçen yıl kaydı olmayan ölçütün paketi aynı kalır.
- doğrulama metin özetiyle (`metin_sha`) işler; ek bölüm doğrulanmış metni yeniden doğrulatmaz.
Not: eski `--onceki` / `config.yaml rapor.onceki_rapor` yolu (geçen yılın metni TEMEL isteme, `onceki_metin`) ayrıca
duruyor; panel onu kullanmaz. Çalışma alanında `onceki-yil.json` varsa eski yol devre dışıdır (geçen yıl istemde iki kez
görünmesin): `write prepare` "UYARI önceki yıl metni … kullanılmadı" yazar. Eski yolu kullanan bölümde bu, temel istemi
(`onceki_metin` "yok" olur) ve dolayısıyla metinlerin güncelliğini değiştirir.

Dönem denetimi (`donem_ici_atlandi`, `bidr/write/text.py`): `onceki-yil.json` olan bölümde geçen yılı (yalnız
`dönem - 1`) "bu yıl"/"bu dönem" ile açıkça karşılaştıran cümle ("2025'te … vardı, bu yıl …") dönem dışı sayılmaz.
Genel dönem denetimi aynıdır; raporu olmayan bölümde bu cümle de denetlenir.

## Tek seferlik karşılaştırma geçişi: `bidr write karsilastirma-ekle prepare|apply|sonuc`

Kendiliğinden çalışmaz. Var olan doğrulanmış metinlere ucuz bir düzeltme geçişi (`bidr/onceki/karsilastirma.py`,
görev `karsilastirma_ekle`):
1. `prepare`: geçen yıl kaydı olan, `dogrulandi`, bu geçişten geçmemiş ve geçen yıl bağlamıyla yazılmamış her metin
   için paket (mevcut cümleler yer kimliğiyle, geçen yıl özeti, bu yılın kanıtları).
2. Ajan cevabı: `yok` | `ekle` (bir cümlenin ardına 1-2 cümle) | `degistir` (tek cümleyi karşılaştırmalı yap).
3. `apply`: ekleme kodla yapılır; metnin geri kalanı, atıfları ve OD'si değişmez. Kod denetimi: yeni cümlede atıf,
   atıf listede, OD dili, OD anma yok, değiştirilen cümlenin atıfları korunmuş, yeni içerik bulgusu yok. Geçen metin
   `taslak` olur (eski hâli `karsilastirma.geri`de). `yok` ve kod reddi metni değiştirmez, işaret bırakır.
4. `bidr verify prepare --only <değişenler>` → doğrulayıcı → `verify apply` (sonunda `sonuc` kendiliğinden):
   doğrulanan ekleme kalır (`eklendi`); reddedilende eski metin, durumu ve `verify.jsonl` satırı geri gelir
   (`reddedildi`).
5. `bidr render` (modelsiz).
Her ölçütte `karsilastirma` işareti kalır: ikinci çalıştırma paket üretmez.
