Görev: Belge, aday YÖKAK BİDR alt ölçütlerinden hangilerine hangi kanıt yuvasıyla kanıttır? OD'yi şişirmek en ağır hatadır.

Kurallar:
1. "alinti": belgeden BİREBİR, kesintisiz 1-2 cümle (≤300 karakter; ekleme, düzeltme, "[...]" yok); kod denetler, tutmayan reddedilir. Belgede yazmayanı iddia etme; konunun adı geçmesi yetmez: alıntı yuvanın istediğinin belgede var olduğunu göstermeli.
2. "yuva": ölçütün listelenen yuvası (ör. B.1.1/2). "asama": yuva etiketindekilerden; "içeriğe bağlı"da: plan/tanım/yönerge/niyet → planla; yapıldığının kaydı → uygula; ölçme/izleme sonucu → kontrol_et; onlem_al, ozgun ilkelerdeki gibi. Boş form, duyuru, gelecek zamanlı ifade uygula değildir.
3. "od_onerisi": planla 2, uygula 3, kontrol_et 4, onlem_al 4, ozgun 5; kararsızsan düşüğü. "guven": yuksek|orta|dusuk. "gerekce": ≤1 cümle.
4. Aday uymuyorsa "olcut_yok"; belge kanıt değilse (ilgisiz metin, ilkelerin saymadıkları; boş form/anket şablonu kanıttır: planla, OD2) "kanit_degil"; ikisinde "eslesmeler" boş. Zorlama eşleşme yapma.
5. Komisyonun kanıt ilkeleri (aynen uygula):
{{kanit_ilkeleri}}
6. "birim_iliskisi" (belge aşağıdaki BİRİM'in mi?) YALNIZ belge metninden; kişileri tanıyarak ya da dış bilgiyle değil: "kendi" | "ust_birim_bu_birim_hakkinda" (dekanlık, FYK, senato, rektörlüğün bu birimi doğrudan (programı, dersi, kadrosu, öğrencisi) konu alan kararı) | "fakulte_geneli"/"kurum_geneli" (bütün birimleri kapsar; birimin satırı alıntılanabiliyorsa "kendi") | "baska_birim" ("kanit_degil", eşleşme yok, gerekçede sahibi) | "belirsiz" (eşleşmeleri ver, nedenini yaz). Birimin kendi sayfası/listesi (bölüm web sayfası, proje/yayın listesi, ders bilgi formu) kurum sitesinde olsa da "kendi"dir; metinde birimin adı, programı ya da ders kodu varken "belirsiz" deme.
7. "kanit_adi": belgeyi tek bakışta tanıtan 3-7 sözcük, Türkçe, kurumsal, Baş Harfleri Büyük: tür, konu, varsa ders kodu, dönem/yıl ("MATH113 Örnek Ders İzlencesi"); aynı türü ayırt eder. OCR hatasını düzelt; tamamı büyük harf, kişi adı, unvan, hitap, e-posta YOK (kişinin rolü); yasak: / \ : * ? " < > |. Her kararda doldur.
8. "faaliyet": toplantı/etkinlik belgesinde {"ad": 2-6 sözcük, bütün belgelerinde aynı, "tarih": "YYYY-AA-GG"|"YYYY-AA"|null, "asama": duyuru|plan|gerceklesme|katilim|degerlendirme|iyilestirme|duzenleme|diger}, değilse null. Afiş/davet "duyuru"; duyuru gerçekleşmenin kanıtı değildir.

BİRİM (bu rapor yalnız bu birim için hazırlanıyor)
{{birim}}

ADAY ALT ÖLÇÜTLER
{{adaylar}}

BELGE BİLGİSİ (otomatik, yanılabilir)
{{belge_bilgisi}}

BELGE METNİ
<<<
{{belge_metni}}
>>>

Tek JSON nesnesi döndür:
{"karar": "olcut_var"|"olcut_yok"|"kanit_degil", "birim_iliskisi": "kendi", "kanit_adi": "Bölüm Kurulu Kararları 2024", "faaliyet": null, "eslesmeler": [{"olcut": "B.1.1", "yuva": "B.1.1/2", "asama": "uygula", "od_onerisi": 3, "alinti": "...", "gerekce": "...", "guven": "orta"}], "gerekce": "kısa"}
