Görev: Birim İç Değerlendirme Raporu (BİDR) şablonunun son tablosunda bir ana alan için "Güçlü Yönler" ve "Gelişmeye Açık Yönler" maddelerini yazacaksın. Maddeler kalite komisyonuna ve dış değerlendiricilere gider; yalnız aşağıdaki ALT ÖLÇÜTLER bölümüne dayanır. Orada olmayanı yazmak, olgunluk düzeyini (OD) şişirmek ve öğüt/vaat vermek en ağır hatadır.

Kurallar:
1. Her madde kısa (1-2 cümle), akademik ve resmî Türkçe; edilgen, kurumsal anlatım ("{{hitap}} … yürütülmektedir"). Birinci/ikinci şahıs, soru, ünlem, slogan, abartı ("mükemmel", "son derece", "başarıyla", "büyük önem") yok.
2. Her cümle dayandığı alt ölçüt kodunu parantez içinde taşır, nokta öncesinde: "… tanımlanmıştır (B.1.1)." Birden çok ölçüt: "(B.1.1, B.1.3)". Kanıt numarası (`[1_OD3]`) kullanma.
3. Güçlü yön yalnız DOĞRULANMIŞ METNİ olan ölçütten çıkar ve yalnız o metinde açıkça söylenen uygulamayı özetler; metinde olmayan sonuç, sayı, kapsam ya da sıklık ekleme. Atıf yapılabilecek ölçütler: {{guclu_olcutler}}.
4. Gelişmeye açık yön yalnız ölçütün BULGULAR satırından çıkar (eksik PUKÖ halkası, düşük OD, yalnız kurum geneli düzenleme, bu dönemde kanıt bulunamaması) ve bulguyu olgu olarak söyler: "… izleme sonuçlarına ilişkin kanıt bulunmamaktadır (B.1.2)." Atıf yapılabilecek ölçütler: {{gelisme_olcutler}}.
5. Öğüt ve vaat yok: "-malıdır/-melidir", "önerilir", "tavsiye", "planlanmaktadır", "yapılacaktır", "hedeflenmektedir" gibi ifadeler kullanma; ne yapılması gerektiğini değil, ne eksik olduğunu yaz.
6. Olgunluk dili ölçütün önerilen OD'siyle sınırlıdır: OD4 altındaki ölçüt için "sistematik olarak izlenmekte", "PUKÖ döngüsü", "izlenmekte ve iyileştirilmektedir"; OD5 altındaki için "içselleştirilmiş", "sürdürülebilir", "örnek gösterilebilir", "özgün" yazma. "OD3" gibi düzey anma.
7. Benzer ölçütleri tek maddede toplayabilirsin. Dayanağı olmayan liste boş kalır ([]); boşluğu doldurmak için madde uydurma. Her listede en çok 6 madde.

ALAN
{{alan}}

ALT ÖLÇÜTLER (yalnız birimin doldurduğu ölçütler; tek dayanak)
{{olcutler}}

Yalnız şu biçimde tek bir JSON nesnesi döndür:
{"guclu": [{"metin": "{{hitap}} … yürütülmektedir (B.1.1)."}], "gelisme": [{"metin": "… kanıt bulunmamaktadır (B.1.2)."}]}
