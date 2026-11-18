Görev: Aşağıdaki belge, verilen aday YÖKAK BİDR alt ölçütlerinden hangilerine hangi kanıt yuvası üzerinden kanıttır? Karar kalite raporunda kullanılacak; olgunluk düzeyini (OD) şişirmek en ağır hatadır.

Kurallar:
1. Her eşleşme için "alinti": belge metninden BİREBİR, kesintisiz bir parça (1-2 cümle, en çok 300 karakter); ekleme, çıkarma, düzeltme, "[...]" yok. Kod metne karşı denetler; tutmayan eşleşme reddedilir.
2. Belgede yazmayanı iddia etme; konunun adının geçmesi kanıt değildir: alıntı, yuvanın istediğinin belgede var olduğunu göstermeli.
3. "yuva": alıntının karşıladığı yuva (ör. B.1.1/2); yalnız o ölçütün listelenen yuvalarından.
4. "asama": yuvanın etiketindeki aşamalardan biri. Etiket "içeriğe bağlı" ise alıntıya göre seç: plan, tanım, yönerge, niyet → planla; yapıldığının kaydı (bölüm kurulunun uygulama kararı dahil) → uygula; ölçme, izleme, değerlendirme sonucu → kontrol_et; izleme sonucuna dayanan, yapılmış iyileştirme → onlem_al (gerekçede dayandığı sonucu yaz); birden çok dönemde sürdürülen ve bağımsızca (üst birim, dış kurum) örnek gösterilen uygulama → ozgun. Değildir: boş form/şablon, duyuru ya da gelecek zamanlı ifade → uygula değil; katılım sayısı → kontrol_et değil; öneri, kurula bilgi verilmesi, sürüm notu ("revize edildi") → onlem_al değil; öz-övgü, tanıtım metni → ozgun değil. Fotoğraf destekleyicidir.
5. "od_onerisi": planla 2, uygula 3, kontrol_et 4, onlem_al 4, ozgun 5. Kararsızsan düşük olanı seç.
6. "guven": yuksek | orta | dusuk. "gerekce": en çok 1 cümle, alıntı yuvayı neden karşılıyor.
7. Aday uymuyorsa "olcut_yok"; belge kanıt değilse (boş şablon, herhangi bir yılın BİDR raporu ya da taslağı, giriş ekranı, bağlantı sayfası, yürürlükten kalkmış düzenleme, ilgisiz metin; dış akreditasyon öz değerlendirme raporları kanıttır) "kanit_degil". İkisinde "eslesmeler" boş; bu cevaplar geçerlidir, zorlama eşleşme yapma.
8. Komisyonun kanıt ilkeleri (aynen uygula):
{{kanit_ilkeleri}}
9. "birim_iliskisi": belge aşağıdaki BİRİM'e ait mi (klasörde fakülte ve başka bölüm belgeleri olabilir)?
   - "kendi": birimin kendi belgesi.
   - "ust_birim_bu_birim_hakkinda": dekanlık, fakülte yönetim kurulu, senato ya da rektörlüğün bu birimi (programı, dersi, kadrosu, öğrencisi, komisyonu) doğrudan konu alan kararı/yazısı. OD tavanı yok; alıntı yalnız bu birimi konu alan maddeden.
   - "fakulte_geneli" / "kurum_geneli": bütün birimleri kapsayan düzenleme, politika ya da fakülte/kurum geneli faaliyet. Kod eşleşmeleri OD2 ile sınırlar. Bölüm kırılımlı fakülte belgesinde birimin satırı alıntılanabiliyorsa "kendi"; bölümün kendi usul ve esası/yönergesi "kendi"dir.
   - "baska_birim": başka bölüm/birimin belgesi: karar "kanit_degil", eşleşme yok, gerekçede ait olduğu birim.
   - "belirsiz": aitlik metinden anlaşılmıyor; eşleşmeleri ver, gerekçede nedenini yaz.
   Birim YALNIZ belge metninden çıkarılır; kişileri tanıyarak ya da dış bilgiyle atanmaz.
   Örnek (birim Matematik): FYK kararının 3. maddesi Matematik Bölümü'nün ders değişikliğini onaylıyor → "ust_birim_bu_birim_hakkinda", alıntı 3. maddeden. Kimya Bölümü tutanağı → "baska_birim".
10. "kanit_adi": belgenin kanıt dosyası adı; dosya listesinde belgenin ne olduğu tek bakışta anlaşılmalı. 3-7 sözcük, Türkçe, kurumsal, her sözcüğün baş harfi büyük. Türü ve konusu; ders belgesinde ders kodu, dönemlik/yıllık belgede dönem ya da yıl (metinde varsa): "Bölüm Toplantı Tutanakları", "MATH113 Örnek Ders İzlencesi". Aynı türden belgeleri ayırt eder ("Yönerge" değil "GTÜ Çift Anadal Programı Yönergesi"). OCR hatalarını düzeltir, tamamı büyük harf yazmaz. Kişi adı, unvan, hitap, e-posta YOK (kişiye ait belgede rolü). Yasak karakter: / \ : * ? " < > |. "kanit_degil" ve "olcut_yok" kararında da doldurulur.
11. "faaliyet": belge bir toplantı/etkinliğe aitse {"ad": 2-6 sözcük, faaliyetin bütün belgelerinde aynı, "tarih": "YYYY-AA-GG" | "YYYY-AA" | null, "asama": duyuru | plan | gerceklesme | katilim | degerlendirme | iyilestirme | duzenleme | diger}, değilse null. Afiş/davet "duyuru"dur; duyuru gerçekleşmenin kanıtı değildir (o tutanak, rapor, fotoğraf).

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
{"karar": "olcut_var" | "olcut_yok" | "kanit_degil", "birim_iliskisi": "kendi", "kanit_adi": "Bölüm Kurulu Kararları 2024", "faaliyet": null, "eslesmeler": [{"olcut": "B.1.1", "yuva": "B.1.1/2", "asama": "uygula", "od_onerisi": 3, "alinti": "...", "gerekce": "...", "guven": "orta"}], "gerekce": "genel kısa gerekçe"}
