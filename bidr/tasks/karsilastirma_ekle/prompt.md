Görev: Aşağıdaki BİDR ölçüt metni bağımsız doğrulamadan geçmiş, bölüm tarafından kabul edilmiş bir metindir. Bölüm geçen yılın ({{yil}}) raporunu sonradan verdi. Yapacağın tek şey: gerekiyorsa metne geçen yılla kısa bir karşılaştırma katmak. Metni yeniden yazmıyorsun.

Seçeneklerin (yalnız biri):
- "yok": karşılaştırma yapılmaz. Bu yılın kanıtı geçen yıla göre bir değişikliği, iyileştirmeyi ya da sürekliliği açıkça göstermiyorsa, ya da geçen yılın metni o konuda belirsizse doğru cevap budur. "yer": "", "cumleler": [].
- "ekle": "yer" kimlikli cümlenin hemen ardına 1 ya da 2 yeni cümle eklenir.
- "degistir": "yer" kimlikli tek cümle, karşılaştırmalı hâliyle (1 ya da 2 cümle) değiştirilir. Yeni hâl eski cümlenin bütün iddialarını ve atıflarını korur; yalnız karşılaştırma ifadesi eklenir.

Kurallar:
1. Metnin geri kalanına dokunma; başka cümleyi düzeltme, kısaltma, birleştirme. Ekleme kodla yapılır, yalnız senin verdiğin cümleler değişir.
2. Her yeni cümle en az bir `[n_ODk]` atfı taşır; yalnız aşağıdaki KANITLAR listesindeki numaralar. Cümlenin bu yıla dair kısmı atıf yaptığı kanıtın alıntısında ya da bağlamında açıkça görülmelidir.
3. Geçen yıl bilgisi kanıt değildir: geçen yıla atıf yapılmaz, geçen yılın kanıt numaraları ve belge adları kanıt gibi yazılmaz.
4. Uydurma karşılaştırma yok: "{{yil}} yılında X vardı/yoktu" demek için X geçen yılın metninde açıkça yazmalı (ya da yazmadığı açık olmalı). Kısaltılan yer ("[…]") hakkında geçen yıla dair hüküm kurma.
5. Geçen yılın OD'si bu yılın OD'sini belirlemez: OD anma, "olgunluk düzeyi yükselmiştir" deme. Bu yılın önerilen OD'si ({{od}}) üst sınırdır: onun üstündeki rubrik düzeylerinin dilini kullanma.
6. Kısa ve resmî: "{{yil}} yılında … iken bu yıl … [3_OD4]." ya da "{{yil}} yılında olduğu gibi bu yıl da … [1_OD3]." Edilgen, kurumsal anlatım; abartı yok.
7. "gerekce": bir iki cümleyle neden bu seçeneği seçtiğin (hangi kanıt hangi değişikliği gösteriyor ya da neden karşılaştırma yok).

ALT ÖLÇÜT
{{olcut}}

MEVCUT METİN (cümleler, yer kimliğiyle)
{{cumleler}}

GEÇEN YILIN ÖZETİ ({{yil}}; kanıt değildir, atıf yapılmaz)
<<<
{{onceki_ozet}}
>>>

KANITLAR (bu yılın; atıf yapılabilecek tek liste)
{{kanitlar}}

Yalnız şu biçimde tek bir JSON nesnesi döndür:
{"islem": "yok", "yer": "", "cumleler": [], "gerekce": "..."}
