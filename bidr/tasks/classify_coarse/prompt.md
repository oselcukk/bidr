Görev: Bir üniversite bölümünün kalite komisyonu için, aşağıdaki belgenin YÖKAK BİDR alt ölçütlerinden hangilerine kanıt olabileceğini ön seçeceksin.

Kurallar:
1. Yalnız BELGE METNİ'ne dayan. Metinde yazmayan bir şeyi varsayma; dosya adı veya başka bilgi verilmemiştir.
2. Bir ölçütü, belge o ölçütün konusunda somut bir plan, karar, uygulama kaydı, ölçme/izleme sonucu ya da iyileştirme içeriyorsa seç. Konunun yalnız adının geçmesi yetmez.
3. En çok 5 ölçüt seç, en güçlüsü önde. Yalnız listedeki kimlikleri yaz.
4. Belge kanıt niteliği taşımıyorsa (boş şablon, öz değerlendirme raporu ya da taslağı, ilgisiz ya da okunamayan metin) karar "kanit_degil". Kanıt niteliğinde ama listedeki hiçbir ölçüte uymuyorsa karar "olcut_yok". Bu iki cevap geçerlidir; zorlama eşleşme yapma. Bu iki durumda "olcutler" boş liste olur.
5. Gerekçeler Türkçe, kısa (en çok 1 cümle) ve belgede gördüğün şeye dayalı olsun.

ALT ÖLÇÜTLER (kimlik — başlık: rubrik düzey 3 metni)
{{olcutler}}

BELGE BİLGİSİ (metinden otomatik çıkarıldı, yanılabilir)
{{belge_bilgisi}}

BELGE METNİ
<<<
{{belge_metni}}
>>>

Yalnız şu biçimde tek bir JSON nesnesi döndür:
{"karar": "olcut_var" | "olcut_yok" | "kanit_degil", "olcutler": [{"olcut": "B.1.1", "gerekce": "..."}], "gerekce": "genel kısa gerekçe"}
