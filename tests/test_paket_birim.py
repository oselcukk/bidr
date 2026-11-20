"""Kör test 2026-11-20b kalan sorunları (yalnız sentetik veri, model yok):

- birim: model kurum/fakülte geneli dese de üst birim yazısında birime ait kayıt ("Örnek Bölümü:"
  satırı) üst birimin bu birim hakkındaki belgesidir; dağıtım listesindeki hitap değildir; decide'ın
  OD2 tavanı kalkar. Birleşik PDF'te tür (yönerge) tavanı birimin kendi sayfasından alıntıya
  uygulanmaz (ders değerlendirme sonucu), düzenleme sayfasına uygulanır.
- fotoğraf: görselli belgede fotoğraf altyazısı tek başına uygulama (OD3) değildir; inceleme
  `kabul`ü bunu aşmaz.
- kopya: paket PDF'te alıntılanan sayfa aynı yazının kopyasıysa (tarih paketin ilk parçasının)
  ölçüt içinde tek kanıt; farklı toplantı, kardeş kalıp ayrı kalır; atıflı kalem numarayı paylaşır.
"""
from __future__ import annotations

from bidr.audit.run import build

from test_audit_od import _m, _ws
from test_kopya import BASKA, CEVRE, YAZI, _item, _ocr

import yaml


def _cfg(w, **extra):
    sec = {"birim": "Örnek Bölümü", **extra}
    (w / "config.yaml").write_text(yaml.safe_dump({"bidr": sec}, allow_unicode=True), encoding="utf-8")
    return w


def _capped(m, tur=False):
    """decide'ın kurum geneli tavanı (OD2, `uygulama_kaniti_eksik`) uygulanmış eşleşme."""
    m = dict(m, od_kabul=2)
    m["denetim"] = {"red": [], "isaret": ["uygulama_kaniti_eksik"]}
    return m


def _set_ince(w, did, **ince):
    import json
    p = w / "decisions.jsonl"
    rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    for r in rows:
        if r["doc_id"] == did:
            r["ince"].update(ince)
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


# -- birim ilişkisi ----------------------------------------------------------------------------

UST = ("T.C. ÖRNEK ÜNİVERSİTESİ REKTÖRLÜĞÜ\nÖrnek Fakültesi Dekanlığı\n\nTOPLUMSAL KATKI KOORDİNATÖRLÜĞÜNE\n\n"
       "İlgi yazınız gereği Fakültemize bağlı Bölümlerimizin görevli bilgileri aşağıda sunulmuştur.\n\n"
       "Kıyas Bölümü:\nDr. Kişi Bir / birim temsilcisi\nÖrnek Bölümü:\nDr. Kişi İki / birim temsilcisi\n"
       "Deneme Bölümü:\nDr. Kişi Üç / birim temsilcisi\n")
DAGITIM = ("T.C. ÖRNEK ÜNİVERSİTESİ REKTÖRLÜĞÜ\nÖrnek Fakültesi Dekanlığı\n\nFakülte akademik genel kurulu "
           "toplantısı yapılacaktır.\n\nDağıtım:\nKıyas Bölüm Başkanlığına\nÖrnek Bölüm Başkanlığına\n"
           "Deneme Bölüm Başkanlığına\n")


def test_unit_entry_in_faculty_letter_is_about_unit_but_distribution_list_is_not(tmp_path):
    q1 = "İlgi yazınız gereği Fakültemize bağlı Bölümlerimizin görevli bilgileri aşağıda sunulmuştur."
    q2 = "Fakülte akademik genel kurulu toplantısı yapılacaktır."
    docs = {"ust": ("resmi_yazi", "2025-02-28", UST, [_capped(_m("D.1.1", "D.1.1/1", "uygula", q1))],
                    "fakulte_geneli"),
            "dag": ("resmi_yazi", "2025-12-04", DAGITIM, [_capped(_m("A.1.1", "A.1.1/2", "uygula", q2))],
                    "fakulte_geneli")}
    a = build(_cfg(_ws(tmp_path, docs)))
    u = a.by_key["ust|D.1.1/1"]
    assert u["birim_iliskisi"] == "ust_birim_bu_birim_hakkinda"
    assert "kurum_geneli" not in u["flags"] and "birim_iliskisi_kod" in u["flags"]
    assert u["od"] == 3 and "birim kodca düzeltildi" in u["vurgu"]            # decide'ın OD2 tavanı kalktı
    d = a.by_key["dag|A.1.1/2"]
    assert d["birim_iliskisi"] == "fakulte_geneli" and "kurum_geneli" in d["flags"] and d["od"] == 2


def test_model_says_general_but_document_addressed_to_unit(tmp_path):
    t = ("05.08.2025\nÖrnek Üniversitesi\nÖrnek Fakültesi\nÖrnek Bölüm Başkanlığı'na,\n\n"
         "Anket komisyonu toplantısında alınan kararlar doğrultusunda gereğini arz ederiz.\n")
    q = "Anket komisyonu toplantısında alınan kararlar doğrultusunda gereğini arz ederiz."
    docs = {"hitap": ("resmi_yazi", "2025-08-05", t, [_m("A.4.2", "A.4.2/2", "planla", q)], "kurum_geneli")}
    r = build(_cfg(_ws(tmp_path, docs))).by_key["hitap|A.4.2/2"]
    assert r["birim_iliskisi"] == "kendi" and "kurum_geneli" not in r["flags"]


SONUC = ("Örnek Üniversitesi\nDeğerlendirme Form Sonucu\nŞube Kodu/Ders Kodu 1/ORN407\n"
         "Programı Örnek (%100 İngilizce)\nDönem Adı 2024-2025 Bahar\n"
         "Dersi Alan Öğrenci/Değerlendiren Sayısı/Puan 14/13/4,31\n")
YONERGE = ("DERECEYE GİREN MEZUNLARIN TESPİTİNE İLİŞKİN YÖNERGE\n\nMADDE 1 - Bu yönergenin amacı Örnek "
           "Üniversitesi lisans programlarında başarı sıralamasının esaslarını düzenlemektir.\n"
           "MADDE 3- Sıralama mezuniyet ağırlıklı genel not ortalamasına göre yapılır.\n")


def test_unit_page_in_combined_pdf_escapes_type_cap(tmp_path):
    q1 = "Dersi Alan Öğrenci/Değerlendiren Sayısı/Puan 14/13/4,31"
    q2 = "MADDE 3- Sıralama mezuniyet ağırlıklı genel not ortalamasına göre yapılır."
    docs = {"birlesik": ("yonerge", "2025-06-26", SONUC + "\f" + YONERGE,
                         [_capped(_m("A.4.2", "A.4.2/2", "uygula", q1)), _m("B.2.4", "B.2.4/1", "planla", q2)])}
    a = build(_cfg(_ws(tmp_path, docs), ders_kodlari=["ORN"]))
    s = a.by_key["birlesik|A.4.2/2"]
    assert "kurum_geneli" not in s["flags"] and "birim_sayfasi" in s["flags"]
    assert s["etkin_asama"] == "uygula" and s["od"] == 3
    y = a.by_key["birlesik|B.2.4/1"]
    assert "kurum_geneli" in y["flags"] and "birim_sayfasi" not in y["flags"]    # düzenleme sayfası
    # tek sayfalık (birleşik olmayan) kurum yönergesi tür tavanında kalır
    docs = {"tek": ("yonerge", "2025-06-26", SONUC + YONERGE, [_capped(_m("A.4.2", "A.4.2/2", "uygula", q1))])}
    t = build(_cfg(_ws(tmp_path / "b", docs), ders_kodlari=["ORN"])).by_key["tek|A.4.2/2"]
    assert "kurum_geneli" in t["flags"] and t["od"] == 2


# -- fotoğraf ----------------------------------------------------------------------------------

FOTO = ("Örnek Bölüm Girişi\n\nÖrnek Bölüm Dersliği\n\nÖrnek Bölümü Engelli Tuvaleti\n\n"
        "[gömülü görsel: word/media/image1.jpg]\n\nÖrnek Bölümü Dinlenme Alanı\n")


def test_photo_caption_alone_is_not_implementation_even_if_accepted(tmp_path):
    q = "Örnek Bölümü Engelli Tuvaleti"
    docs = {"foto": ("altyapi_listesi", None, FOTO, [_m("B.3.4", "B.3.4/1", "uygula", q)])}
    w = _cfg(_ws(tmp_path, docs))
    dec = {"satir": "foto|B.3.4/1", "doc_id": "foto", "olcut": "B.3.4", "yuva": "B.3.4/1", "karar": "kabul",
           "duzelt": None, "etiket": None, "not": ""}
    a = build(w, review={dec["satir"]: dec})
    r = a.by_key["foto|B.3.4/1"]
    assert not r["sayilir"] and "fotograf_destekleyici" in r["flags"]
    # yanında belge dayanağı (gerçek uygulama metni) varsa fotoğraf düşürülmez
    t = "Örnek Bölümü engelli öğrenciler için rampa ve asansör düzenlemesini 2025 yılında tamamlamıştır."
    docs["rapor"] = ("faaliyet_raporu", "2025-06-01", t, [_m("B.3.4", "B.3.4/2", "uygula", t)])
    b = build(_cfg(_ws(tmp_path / "b", docs)))
    assert b.by_key["foto|B.3.4/1"]["sayilir"] and "fotograf_destekleyici" not in b.by_key["foto|B.3.4/1"]["flags"]


def test_caption_heuristic():
    from bidr.audit.savunma import altyazi
    assert altyazi("Örnek Bölümü Engelli Tuvaleti", FOTO)
    assert not altyazi("2025 yılı faaliyetleri ekte sunulmuştur.", "2025 yılı faaliyetleri ekte sunulmuştur.")
    assert not altyazi("Bölüm kurulu toplanmıştır", "Bölüm kurulu toplanmıştır")
    assert not altyazi("Bu metinde geçmeyen bir altyazı", FOTO)


# -- paket PDF: alıntılanan parçanın kopyası -----------------------------------------------------

KARAR = ("Toplantı Tarihi: 06.01.2025\nÖrnek Bölüm Kurulu toplandı. Karar 2025/1: ORN 441 dersinin "
         "içeriği müfredat komisyonu önerisiyle güncellenmiş, ders saatleri yeniden düzenlenmiştir. "
         "Karar 2025/2: yüksek lisans danışman atamaları onaylanmıştır. Karar 2025/3: laboratuvar "
         "güvenliği eğitiminin bütün araştırma görevlilerine verilmesine karar verilmiştir.\n") * 2


def _paket_setup():
    texts = {"yazi": YAZI, "paket": KARAR + "\f" + _ocr(YAZI.replace("Bahar", "Büar"), seed=3),
             "paket2": BASKA + "\f" + _ocr(YAZI, seed=5), "baska": BASKA,
             **{f"d{i}": f"dolgu {i} " + CEVRE for i in range(3)}}
    docs = {"yazi": {"tarih": "2025-08-05", "doc_type": "komisyon_tutanagi"},
            "paket": {"tarih": "2025-01-06", "doc_type": "bolum_kurulu_karari"},
            "paket2": {"tarih": "2025-01-14", "doc_type": "komisyon_tutanagi"},
            "baska": {"tarih": "2025-01-14", "doc_type": "komisyon_tutanagi"},
            **{f"d{i}": {"tarih": None, "doc_type": "bilinmiyor"} for i in range(3)}}
    return texts, docs


def test_package_page_copy_counted_once_standalone_representative():
    from bidr.file import select as S
    texts, docs = _paket_setup()
    q = "altyapı sorularının ayrı iki soru şeklinde hazırlanarak farklı"
    items = [_item("B.3.3", "paket", 4, q), _item("B.3.3", "yazi", 4, q), _item("B.3.3", "paket2", 4, q)]
    # belge düzeyinde kapsama tutmaz (tarih paketin ilk parçasının)
    rest, _ = S.merge_contained(list(items), docs, texts.__getitem__, cited=set())
    assert len(rest) == 3
    rest, merges = S.merge_versions(items, docs, texts.__getitem__, cited=set())
    assert [it.doc_id for it in rest] == ["yazi"]                       # yazının kendisi temsilci
    assert sorted(rest[0].kopyalar_surum) == ["paket", "paket2"]
    assert {u["neden"] for m in merges for u in m["uyeler"]} == {"parca_kopyasi"}


def test_package_other_meeting_stays_separate_and_cited_shares_number():
    from bidr.file import select as S
    from bidr.file.naming import number_sources, source_key
    texts, docs = _paket_setup()
    q = "altyapı sorularının ayrı iki soru şeklinde hazırlanarak farklı"
    qb = "Anket formlarının çevrim içi sisteme taşınmasına"
    # paket2'nin bu ölçütte alıntıladığı sayfa başka toplantının (14.01) yazısı: 05.08 yazısıyla birleşmez
    items = [_item("A.4.2", "yazi", 4, q), _item("A.4.2", "paket2", 4, qb), _item("A.4.2", "baska", 4, qb)]
    rest, _ = S.merge_parts(items, docs, texts.__getitem__, cited=set())
    assert sorted(it.doc_id for it in rest) == ["baska", "yazi"]
    # atıf yapılan paket listede kalır ama yazıyla tek numara taşır
    items = [_item("B.3.3", "yazi", 4, q), _item("B.3.3", "paket", 4, q)]
    rest, _ = S.merge_parts(items, docs, texts.__getitem__, cited={"paket"})
    assert len(rest) == 2
    num = number_sources(rest, key=lambda i: source_key(i.doc_id, docs, i), od=lambda i: i.od)
    assert len({s for s, _, _ in num}) == 1


def test_template_siblings_not_merged_as_parts():
    from bidr.file import select as S
    akis = ("İŞ AKIŞ NO: İA-01{n} İŞ AKIŞ ADI: DEĞİŞİM PROGRAMI {yon} ÖĞRENCİ\nYayın Tarihi 21.06.2017 "
            "Revizyon Tarihi 26.09.2022\nÖğrenci başvurusu birim koordinatörüne iletilir. Koordinatör "
            "başvuruyu değerlendirir ve kabul edilen öğrencinin öğrenim anlaşması hazırlanır. Öğrenim "
            "anlaşması bölüm başkanı tarafından onaylanır ve dış ilişkiler ofisine gönderilir. Dönem "
            "sonunda not dönüşümü intibak komisyonunca yapılır ve öğrenci işlerine bildirilir.\n")
    texts = {"gelen": akis.format(n=33, yon="GELEN"), "giden": akis.format(n=34, yon="GİDEN"),
             **{f"d{i}": f"dolgu {i} " + CEVRE for i in range(3)}}
    docs = {"gelen": {"tarih": "2022-09-26", "doc_type": "is_akisi"},
            "giden": {"tarih": "2022-09-26", "doc_type": "is_akisi"},
            **{f"d{i}": {"tarih": None, "doc_type": "bilinmiyor"} for i in range(3)}}
    q = "Öğrenci başvurusu birim koordinatörüne iletilir."
    items = [_item("A.5.1", "gelen", 2, q), _item("A.5.1", "giden", 2, q)]
    rest, _ = S.merge_parts(items, docs, texts.__getitem__, cited=set())
    assert len(rest) == 2


def test_period_marks_tolerate_unread_semester():
    from bidr.file.select import Version, relation
    a = Version("a", {}, "2024-2025 Bahar dönemi anket sonuçları", frozenset())
    b = Version("b", {}, "2024-2025 Büar dönemi anket sonuçları", frozenset())
    c = Version("c", {}, "2024-2025 Güz dönemi anket sonuçları", frozenset())
    assert relation(a, b, kopya=True)[0] == "ayni"
    assert relation(a, c, kopya=True) == ("ayri", "farkli_donem")
