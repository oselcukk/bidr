Görev: Aşağıdaki belgenin, verilen aday YÖKAK BİDR alt ölçütlerinden hangilerine hangi kanıt yuvası üzerinden kanıt olduğuna karar vereceksin. Karar kalite raporunda kullanılacak; olgunluk düzeyini (OD) şişirmek en ağır hatadır.

Kurallar:
1. Her eşleşme için "alinti": belge metninden BİREBİR, kesintisiz bir parça (1-2 cümle, en çok 300 karakter). Sözcük ekleme, çıkarma, düzeltme, birleştirme yapma; "[...]" içerme. Alıntı kodla metne karşı denetlenir; tutmayan eşleşme reddedilir.
2. Belgede yazmayanı iddia etme. Konunun adının geçmesi kanıt değildir: alıntı, yuvanın istediği şeyin bu belgede gerçekten var olduğunu göstermeli.
3. "yuva": alıntının karşıladığı yuvanın kimliği (ör. B.1.1/2); yalnız o ölçüt altında listelenenlerden.
4. "asama": yuvanın etiketindeki aşamalardan biri. Etiket "içeriğe bağlı" ise alıntıya göre seç: plan, karar, tanım, yönerge → planla; yapıldığının kaydı → uygula; ölçme, izleme, değerlendirme sonucu → kontrol_et; izleme sonucuna dayanan iyileştirme → onlem_al; belgede açıkça özgün/örnek gösterilebilir denen uygulama → ozgun. Yalnız plan ya da karar içeren belge "uygula" değildir.
5. "od_onerisi" aşamanın düzeyidir: planla 2, uygula 3, kontrol_et 4, onlem_al 4, ozgun 5. Kararsız kalırsan düşük olanı seç.
6. "guven": yuksek | orta | dusuk. "gerekce": en çok 1 cümle, alıntının yuvayı neden karşıladığı.
7. Hiçbir aday uymuyorsa karar "olcut_yok"; belge kanıt niteliği taşımıyorsa (boş şablon, öz değerlendirme raporu ya da taslağı, ilgisiz metin) "kanit_degil". İkisinde de "eslesmeler" boş liste. Bu cevaplar geçerlidir; zorlama eşleşme yapma.

ADAY ALT ÖLÇÜTLER
{{adaylar}}

BELGE BİLGİSİ (metinden otomatik çıkarıldı, yanılabilir)
{{belge_bilgisi}}

BELGE METNİ
<<<
{{belge_metni}}
>>>

Yalnız şu biçimde tek bir JSON nesnesi döndür:
{"karar": "olcut_var" | "olcut_yok" | "kanit_degil", "eslesmeler": [{"olcut": "B.1.1", "yuva": "B.1.1/2", "asama": "uygula", "od_onerisi": 3, "alinti": "...", "gerekce": "...", "guven": "orta"}], "gerekce": "genel kısa gerekçe"}
