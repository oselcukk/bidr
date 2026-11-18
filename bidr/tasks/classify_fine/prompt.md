Görev: Aşağıdaki belgenin, verilen aday YÖKAK BİDR alt ölçütlerinden hangilerine hangi kanıt yuvası üzerinden kanıt olduğuna karar vereceksin. Karar kalite raporunda kullanılacak; olgunluk düzeyini (OD) şişirmek en ağır hatadır.

Kurallar:
1. Her eşleşme için "alinti": belge metninden BİREBİR, kesintisiz bir parça (1-2 cümle, en çok 300 karakter). Sözcük ekleme, çıkarma, düzeltme, birleştirme yapma; "[...]" içerme. Alıntı kodla metne karşı denetlenir; tutmayan eşleşme reddedilir.
2. Belgede yazmayanı iddia etme. Konunun adının geçmesi kanıt değildir: alıntı, yuvanın istediği şeyin bu belgede gerçekten var olduğunu göstermeli.
3. "yuva": alıntının karşıladığı yuvanın kimliği (ör. B.1.1/2); yalnız o ölçüt altında listelenenlerden.
4. "asama": yuvanın etiketindeki aşamalardan biri. Etiket "içeriğe bağlı" ise alıntıya göre seç: plan, karar, tanım, yönerge → planla; yapıldığının kaydı → uygula; ölçme, izleme, değerlendirme sonucu → kontrol_et; izleme sonucuna dayanan iyileştirme → onlem_al; belgede açıkça özgün/örnek gösterilebilir denen uygulama → ozgun. Yalnız plan ya da karar içeren belge "uygula" değildir.
5. "od_onerisi" aşamanın düzeyidir: planla 2, uygula 3, kontrol_et 4, onlem_al 4, ozgun 5. Kararsız kalırsan düşük olanı seç.
6. "guven": yuksek | orta | dusuk. "gerekce": en çok 1 cümle, alıntının yuvayı neden karşıladığı.
7. Hiçbir aday uymuyorsa karar "olcut_yok"; belge kanıt niteliği taşımıyorsa (boş şablon, bu BİDR raporunun kendisi ya da taslağı, ilgisiz metin; dış akreditasyon öz değerlendirme raporları kanıttır) "kanit_degil". İkisinde de "eslesmeler" boş liste. Bu cevaplar geçerlidir; zorlama eşleşme yapma.
8. Komisyonun kanıt ilkeleri (aynen uygula):
{{kanit_ilkeleri}}
9. "birim_iliskisi": belge aşağıdaki BİRİM'e ait mi (klasörde fakülte ve başka bölüm belgeleri de olabilir)?
   - "kendi": birimin kendi belgesi.
   - "ust_birim_bu_birim_hakkinda": dekanlık, fakülte yönetim kurulu, senato ya da rektörlüğün bu birimi (programı, dersi, kadrosu, öğrencisi, komisyonu) doğrudan konu alan kararı/yazısı. OD tavanı yok; alıntı yalnız bu birimi konu alan maddeden.
   - "fakulte_geneli" / "kurum_geneli": bütün birimleri kapsayan düzenleme, politika ya da fakülte/kurum geneli faaliyet. Kod eşleşmeleri OD2 ile sınırlar. Bölüm kırılımlı fakülte belgesinde (ör. anketin bölüm tablosu) birimin satırı alıntılanabiliyorsa "kendi".
   - "baska_birim": başka bölüm/birimin belgesi; kanıt değil: karar "kanit_degil", eşleşme yok, gerekçede ait olduğu birim.
   - "belirsiz": aitlik metinden anlaşılmıyor; eşleşmeleri ver, gerekçede nedenini yaz.
   Örnek (birim Matematik): FYK kararının 3. maddesi Matematik Bölümü'nün ders değişikliğini onaylıyor → "ust_birim_bu_birim_hakkinda", alıntı 3. maddeden. Kimya Bölümü laboratuvar güvenliği tutanağı → "baska_birim". Üniversite eğitim-öğretim yönetmeliği → "kurum_geneli".
10. "kanit_adi": belgenin kanıt dosyası adı; komisyon ve hakem dosya listesinde belgenin ne olduğunu tek bakışta anlamalı. 3-7 sözcük, Türkçe, kurumsal, her sözcüğün baş harfi büyük. Belgenin türünü ve konusunu söyler; ders belgesinde ders kodunu, dönemlik/yıllık belgede dönemi ya da yılı içerir (metinde varsa): "Bölüm Toplantı Tutanakları", "Öğrenci Ders Memnuniyet Anketi", "MATH113 Örnek Ders İzlencesi", "ASELSAN Bilgisayar Laboratuvarı". Aynı türden belgeleri ayırt eder ("Yönerge" değil "GTÜ Çift Anadal Programı Yönergesi"). OCR hatalarını düzeltir, tamamı büyük harf yazmaz. Kişi adı, unvan, hitap, e-posta YOK (kişiye ait belgede rolü yazılır). "kanit_degil" ve "olcut_yok" kararında da doldurulur.

BİRİM (bu rapor yalnız bu birim için hazırlanıyor)
{{birim}}

ADAY ALT ÖLÇÜTLER
{{adaylar}}

BELGE BİLGİSİ (metinden otomatik çıkarıldı, yanılabilir)
{{belge_bilgisi}}

BELGE METNİ
<<<
{{belge_metni}}
>>>

Yalnız şu biçimde tek bir JSON nesnesi döndür:
{"karar": "olcut_var" | "olcut_yok" | "kanit_degil", "birim_iliskisi": "kendi", "kanit_adi": "Bölüm Kurulu Kararları 2024", "eslesmeler": [{"olcut": "B.1.1", "yuva": "B.1.1/2", "asama": "uygula", "od_onerisi": 3, "alinti": "...", "gerekce": "...", "guven": "orta"}], "gerekce": "genel kısa gerekçe"}
