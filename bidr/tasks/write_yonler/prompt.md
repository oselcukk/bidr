Görev: Birim İç Değerlendirme Raporu (BİDR) şablonunun son tablosunda bir ana alan için "Güçlü Yönler" ve "Gelişmeye Açık Yönler" maddelerini yazacaksın. Maddeler kalite komisyonuna ve dış değerlendiricilere gider; yalnız aşağıdaki ALT ÖLÇÜTLER bölümüne dayanır. Orada olmayanı yazmak, olgunluk düzeyini (OD) şişirmek ve öğüt/vaat vermek en ağır hatadır.

Kurallar:
1. Her madde kısa (1-2 cümle), akademik ve resmî Türkçe; edilgen, kurumsal anlatım ("{{hitap}} … yürütülmektedir"). Birinci/ikinci şahıs, soru, ünlem, slogan, abartı ("mükemmel", "son derece", "başarıyla", "büyük önem") yok.
2. Her cümle dayandığı alt ölçüt kodunu parantez içinde taşır, nokta öncesinde: "… tanımlanmıştır (B.1.1)." Birden çok ölçüt: "(B.1.1, B.1.3)". Kanıt numarası (`[1_OD3]`) kullanma.
3. Güçlü yön yalnız DOĞRULANMIŞ METNİ olan ölçütten çıkar ve yalnız o metinde açıkça söylenen uygulamayı özetler; metinde olmayan sonuç, sayı, kapsam ya da sıklık ekleme. Atıf yapılabilecek ölçütler: {{guclu_olcutler}}.
4. Gelişmeye açık yön yalnız ölçütün BULGULAR satırından çıkar (eksik PUKÖ halkası, düşük OD, yalnız kurum geneli düzenleme, bu dönemde kanıt bulunamaması) ve bulguyu olgu olarak söyler: "… izleme sonuçlarına ilişkin kanıt bulunmamaktadır (B.1.2)." Atıf yapılabilecek ölçütler: {{gelisme_olcutler}}.
5. Öğüt ve vaat yok: "-malıdır/-melidir", "önerilir", "tavsiye", "planlanmaktadır", "yapılacaktır", "hedeflenmektedir" gibi ifadeler kullanma; ne yapılması gerektiğini değil, ne eksik olduğunu yaz.
6. Olgunluk dili ölçütün önerilen OD'siyle sınırlıdır: OD4 altındaki ölçüt için "sistematik olarak izlenmekte", "PUKÖ döngüsü", "izlenmekte ve iyileştirilmektedir"; OD5 altındaki için "içselleştirilmiş", "sürdürülebilir", "örnek gösterilebilir", "özgün" yazma. "OD3" gibi düzey anma.
7. Benzer ölçütleri tek maddede toplayabilirsin. Dayanağı olmayan liste boş kalır ([]); boşluğu doldurmak için madde uydurma. Her listede en çok 6 madde.
8. "Kanıt yok" hükmü ölçütün KANIT DURUMU satırıyla çelişmez: izleme "var" olan ölçütte izleme kanıtının, iyileştirme "var" olanda iyileştirme kanıtının yokluğunu; uygulama "var" olan ya da listede birime ait kanıtı bulunan ölçütte "bölüm düzeyinde/bölümün uygulama kanıtı bulunmamaktadır" ya da "yalnız kurum geneli düzenleme" yazma. Birime ait kanıt OD'ye sayılmadıysa bulgudaki nedeniyle yaz: "… birime ait proje listesinin tarihi doğrulanamadığından OD'ye sayılmamıştır (C.1.2)."
9. Aynı ölçüt iki listede de olabilir ama iki madde birbirini çelişmez: güçlü yön bir uygulamayı (karar, proje, kayıt, etkinlik) söylüyorsa gelişmeye açık yön o uygulamanın yokluğunu değil, eksik halkayı (ör. izleme sonuçları, iyileştirme) söyler.
10. Gösterge ya da performans değeri (yayın sayısı, oran, ortalama, gerçekleşme) yalnız metin hedefe ulaşıldığını açıkça söylüyorsa güçlü yöndür. Hedefin altında kalan ya da hedefle karşılaştırılmamış değer güçlü yön değildir; "HEDEF: … hedefin altında" satırı olan ölçütün gösterge değerini güçlü yöne yazma.
11. Metinde ya da bulguda olmayan olgu (kural, puan koşulu, sayı, kurul adı) ekleme; bir düzenlemenin birime özgü hükmü metinde yoksa "birim için ayrıca belirlenmiştir" deme.

ALAN
{{alan}}

ALT ÖLÇÜTLER (yalnız birimin doldurduğu ölçütler; tek dayanak)
{{olcutler}}

Yalnız şu biçimde tek bir JSON nesnesi döndür:
{"guclu": [{"metin": "{{hitap}} … yürütülmektedir (B.1.1)."}], "gelisme": [{"metin": "… kanıt bulunmamaktadır (B.1.2)."}]}
