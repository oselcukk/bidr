Görev: Birim İç Değerlendirme Raporu (BİDR) için aşağıdaki alt ölçütün "Açıklamalar" metnini yazacaksın. Metin kalite komisyonuna ve dış değerlendiricilere gidecek; yalnız verilen kanıtlara dayanır. Kanıtta olmayanı yazmak ve olgunluk düzeyini (OD) şişirmek en ağır hatadır.

Üslup:
1. Akademik, resmî Türkçe; edilgen ve kurumsal anlatım ("{{hitap}} … yürütülmektedir", "… belirlenmiştir"). Birinci tekil şahıs, ikinci şahıs hitap, soru cümlesi yok.
2. Slogan, koçluk dili ("-malıdır", "öneririz", "unutmayın"), abartı ("mükemmel", "son derece", "titizlikle", "başarıyla", "büyük önem"), ünlem yok. Belge adlarını ve sayıları kanıttaki gibi yaz.
3. 2-5 kısa paragraf; her paragraf bir konu (süreç nasıl tanımlı / nasıl uygulanıyor / izleme / varsa iyileştirme). Kanıtı olmayan konu için paragraf yazma.

Kanıt ve atıf:
4. HER cümle en az bir atıf taşır: kılavuz gösterimiyle `[n_ODk]` (ör. `[1_OD3]`), yalnız aşağıdaki KANITLAR listesindeki numaralar, OD'siyle birebir. Atıf cümle sonundaki noktadan önce gelir: "… uygulanmaktadır [2_OD3]." Birden çok atıf: "[1_OD2], [3_OD3]".
5. Bir cümle yalnız atıf yaptığı kanıtın alıntısında ya da bağlamında açıkça görülen şeyi söyler. Kanıtın adından, belge türünden ya da ölçüt tanımından çıkarım yapma; sayı, tarih, kurul adı, ders kodu yalnız kanıtta geçiyorsa yazılır.
6. Kurum geneli yönetmelik/yönerge yalnız kural ve süreç tanımıdır: "… çerçevesinde tanımlanmıştır" de; bölümün uyguladığını ancak uygulama kanıtı gösteriyorsa yaz.

Olgunluk düzeyi:
7. Önerilen OD (aşağıda) metnin üst sınırıdır. Onun üstündeki rubrik düzeylerinin dilini kullanma: OD4 altıysa "sistematik olarak izlenmekte", "PUKÖ döngüsü", "izlenmekte ve iyileştirilmektedir"; OD5 altıysa "içselleştirilmiş", "sürdürülebilir", "örnek gösterilebilir", "özgün" yok. "izlenmektedir / iyileştirilmiştir / önlem alınmıştır" diyen cümle OD4 ya da üstü bir kanıta, "özgün" diyen cümle OD5 kanıta atıf yapmalı. Metinde "OD3" gibi düzey anma.
8. Eksikleri metne yazma: eksik halkalar ayrı listelenir (kod ekler). "… kurulması planlanmaktadır", "… yapılacaktır" gibi gelecek zaman vaadi UYDURMA. Yalnız KOMİSYON BİLGİSİ'nde verilmiş bir plan varsa onu bir cümleyle aktarabilirsin; o cümle `[n_ODk]` yerine `[komisyon]` işareti taşır ve bilginin ötesine geçmez.

Önceki yıl:
9. ÖNCEKİ YIL METNİ yalnız üslup örneği ve karşılaştırma içindir; oradaki iddiaları bu yılın kanıtı yoksa tekrar etme, eski kanıt numaralarını ([B.1.1-2-OD3] gibi) kullanma.
10. "onceki_yila_gore": bu yılın kanıtlarında olup önceki yıl metninde ya da kanıt listesinde yer almayan uygulamaları 1-3 cümleyle belirt; her cümle bu yılın kanıtına atıf yapar ("Önceki yıldan farklı olarak … [4_OD3]."). Önceki yıl metni yoksa ya da açık bir fark yoksa boş dize ("") ver.

Kılavuzun sorduğu sorular (kanıtın yettiği kadarıyla cevapla):
{{yazim_sorulari}}

ALT ÖLÇÜT
{{olcut}}

OLGUNLUK DÜZEYİ (audit; kodla hesaplandı)
{{od_bilgisi}}

KANITLAR (atıf yapılabilecek tek liste)
{{kanitlar}}

ÖNCEKİ YIL METNİ (yalnız üslup ve karşılaştırma için; kanıt değildir)
<<<
{{onceki_metin}}
>>>

KOMİSYON BİLGİSİ
{{komisyon_bilgisi}}

Yalnız şu biçimde tek bir JSON nesnesi döndür:
{"paragraflar": [{"metin": "{{hitap}} … tanımlanmıştır [1_OD2]. … yürütülmektedir [2_OD3]."}], "onceki_yila_gore": ""}
