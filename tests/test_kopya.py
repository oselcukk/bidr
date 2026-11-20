"""Kopyalar, kanıt kodunun OD tutarlılığı ve yönler çapraz denetimi (kör test 2026-11-20).

Yalnız sentetik metin; model yok. Kapsam:
- identify: OCR'lı tarama kopyası ve kontrollü belgenin sayfaları aynı sürüm grubuna girer;
  farklı tarihli toplantı (K20), kardeş kalıp (iş akışı), farklı ders formu ve farklı revizyon
  ayrı kalır (yanlış birleştirme sınaması);
- file: ölçüt içinde kapsanan kopya kapsayana katılır (atıflıysa numarayı paylaşır);
- kanıt kodu: ölçüt OD'sinin üstündeki düzey yalnız o düzey zincirde kurulmuşsa;
- savunma: "Başkanlığa iletilmesine karar" iyileştirme değildir;
- yönler: "kanıt yok" hükmü kanıt durumuyla, güçlü yönle ve hedefle çelişmez.
"""
from __future__ import annotations

import random

from bidr.identify import versions as V
from bidr.identify.text import collapse, fold

# -- sentetik metinler -------------------------------------------------------------------------

YAZI = """05.08.2025

Örnek Teknik Üniversitesi
Temel Bilimler Fakültesi
Örnek Bölüm Başkanlığı'na,

2024-2025 Bahar dönemi ders değerlendirme anketleri ve öğrenci memnuniyet anketlerinin
sonuçlarının değerlendirilmesi için 05.08.2025 tarihinde gerçekleştirilen anket komisyonu
toplantısında alınan kararlar doğrultusunda gereğini bilgilerinize arz ederiz.

Kararlar:
1. Derslikte projeksiyon cihazı ve klima arızası gibi teknik altyapı sorunlarına ilişkin
yanıtlar değerlendirilmiş, altyapı sorularının ayrı iki soru şeklinde hazırlanarak farklı
bir değerlendirmeye katılmasına karar verilmiştir.
2. Seçmeli ders havuzunun genişletilmesine yönelik öğrenci taleplerinin Bölüm Başkanlığına
iletilmesine karar verilmiştir.
3. Laboratuvar derslerinin kredi yükü ve ders bilgilendirmelerinin zamanlaması ile ilgili
geri bildirimlerin Bölüm Başkanlığına iletilmesine karar verilmiştir.

Komisyon Başkanı ve üyeleri
"""
# aynı komisyonun aynı kalıpla yazdığı başka toplantı: başka tarih, başka kararlar
BASKA = (YAZI.split("Kararlar:")[0].replace("05.08.2025", "14.01.2025").replace("Bahar", "Güz") + """Kararlar:
1. Anket formlarının çevrim içi sisteme taşınmasına ve yanıt oranlarının dönem sonunda raporlanmasına
karar verilmiştir.
2. Mezun anketi sorularının program çıktılarıyla eşleştirilerek yeniden düzenlenmesine karar verilmiştir.
""")
CEVRE = ("Stratejik plan izleme tablosu göstergeleri kütüphane hizmetleri yemekhane memnuniyeti "
         "araştırma merkezi bütçesi öğrenci kulüpleri sosyal tesis onarımı ") * 3


def _ocr(text: str, rate: float = 0.03, seed: int = 1) -> str:
    """OCR benzeri bozulma: harf değişimi ve sonuna el yazısı çöpü."""
    rnd = random.Random(seed)
    sub = {"a": "u", "n": "rı", "t": "f", "r": "ı", "e": "c", "l": "1", "i": "İ"}
    out = [sub.get(c, c) if c in sub and rnd.random() < rate else c for c in text]
    return "".join(out) + "\nG3 Ralim Tqp1 ~ / ;h Ww oS 2Q25 (4 \\6.%0 BBLS | Ars C2 ff e2 Do ACCU"


def _fold(t: str) -> str:
    return fold(collapse(t))


def _corpus(**docs: str) -> dict[str, str]:
    base = {f"dolgu{i}": _fold(f"dolgu belgesi {i} " + CEVRE + f" kayıt {i * 7}") for i in range(4)}
    return {**base, **{k: _fold(v) for k, v in docs.items()}}


# -- identify: OCR kopyası ----------------------------------------------------------------------

def test_ocr_copy_grouped_but_other_meeting_not():
    texts = _corpus(temiz=YAZI, tarama=_ocr(YAZI), tarama2=_ocr(YAZI, 0.05, seed=7),
                    baska=BASKA)
    dates = {"temiz": "2025-08-05", "tarama": "2025-08-05", "tarama2": "2025-08-05", "baska": "2025-01-14"}
    types = {k: "komisyon_tutanagi" for k in dates}
    g = V.group(texts, dates, types)
    assert g["temiz"]["grup"] == g["tarama"]["grup"] == g["tarama2"]["grup"]
    # aynı kalıpla yazılmış başka toplantının yazısı (farklı tarih): ayrı kalır (K20)
    assert "baska" not in g or g["baska"]["grup"] != g["temiz"]["grup"]
    # TF-IDF tek başına OCR kopyasını kaçırıyordu: bağ kopya geçişinden gelir
    assert V.CopyIndex(texts).copy("temiz", "tarama", "2025-08-05", "2025-08-05",
                                   "komisyon_tutanagi", "komisyon_tutanagi") is not None


def test_copy_guards_against_false_merges():
    akis = ("Örnek Teknik Üniversitesi iş akışı süreç sorumlusu personel daire başkanlığı "
            "başvurunun alınması belgelerin kontrol edilmesi onaya sunulması sisteme işlenmesi "
            "ilgiliye bildirilmesi dosyalanması arşivlenmesi süreç sonu ")
    texts = _corpus(gelen="Değişim programı gelen öğrenci işlemleri " + akis * 2,
                    giden="Değişim programı giden öğrenci işlemleri " + akis * 2,
                    f197="CHEM 197 Genel Kimya Laboratuvarı ders değerlendirme anketi " + CEVRE,
                    f436="CHEM 436 Kimyacılar için Matematik ders değerlendirme anketi " + CEVRE)
    dates = {"gelen": "2022-09-26", "giden": "2022-09-26"}
    types = {"gelen": "is_akisi", "giden": "is_akisi", "f197": "anket_formu", "f436": "anket_formu"}
    texts.update({f"sozluk{i}": _fold(f"gelen ve giden öğrenci sayıları {i} " + CEVRE) for i in range(3)})
    ix = V.CopyIndex(texts)
    assert ix.siblings("gelen", "giden")                                  # "gelen"/"giden": kardeş kalıp
    pairs = {frozenset((a, b)) for a, b, _ in V.copy_pairs(texts, dates, types)}
    assert frozenset(("gelen", "giden")) not in pairs
    assert frozenset(("f197", "f436")) not in pairs                       # farklı ders kodu (baş kimliği)
    assert not V.ids_compatible(V.head_ids(texts["f197"]), V.head_ids(texts["f436"]))


def test_control_signature_links_pages_not_revisions_or_forms():
    def page(rev_t: str, rev_n: str, sayfa: str, govde: str) -> str:
        return (f"Doküman No YÖ-0058 Yayın Tarihi 07.02.2019 ÖRNEK TEKNİK ÜNİVERSİTESİ Revizyon Tarihi "
                f"{rev_t} PERSONEL ÖDÜL ESASLARI YÖNERGESİ Revizyon No {rev_n} Sayfa {sayfa} {govde}")
    texts = _corpus(s1=page("04.09.2024", "5", "6-1", "MADDE 1 Amaç ve kapsam " + CEVRE),
                    s5=page("04.09.2024", "5", "6-5", "MADDE 14 Salgın ve afet durumları yürürlük"),
                    eski=page("27.08.2020", "4", "6-1", "MADDE 1 Amaç ve kapsam " + CEVRE),
                    t1="Form No: FR-0044 Yayın Tarihi: 10.10.2016 Değ.No:2 toplantı tutanağı birinci " + CEVRE,
                    t2="Form No: FR-0044 Yayın Tarihi: 10.10.2016 Değ.No:2 toplantı tutanağı ikinci gündem")
    types = {"s1": "yonerge", "s5": "yonerge", "eski": "yonerge", "t1": "toplanti_tutanagi", "t2": "toplanti_tutanagi"}
    dates = {"s1": "2024-09-04", "s5": "2024-09-04", "eski": "2020-08-27"}
    assert V.control_signature(texts["s1"]) == ("yo0058", "04.09.2024|5")
    assert V.control_signature(texts["t1"]) is None                     # form numarası imza değil
    g = V.group(texts, dates, types)
    assert g["s1"]["grup"] == g["s5"]["grup"]                            # aynı yönergenin iki sayfası
    # başka revizyon kopya değil sürümdür (imza farklı; yürürlükteki sürümü audit/donem seçer)
    assert V.control_signature(texts["eski"]) != V.control_signature(texts["s1"])
    assert "t1" not in g or g["t1"]["grup"] != g.get("t2", {}).get("grup")


# -- file: kapsanan kopya ve tek numara ---------------------------------------------------------

def _item(olcut, did, od, alinti, **kw):
    from bidr.file.run import Item
    return Item(olcut=olcut, doc_id=did, od=od, yuvalar=[f"{olcut}/1"], alintilar=[alinti], spans=[None],
                sayilir=True, inceleme="yapilmadi", asamalar={"kontrol_et"}, asamalar_tum={"kontrol_et"},
                guven="yuksek", **kw)


def _contained_setup():
    ek = ("Ek 1 Ders bilgi paketi Genel Kimya Laboratuvarı dersin amacı laboratuvar güvenliği "
          "deney teknikleri yoğunluk ölçümü titrasyon ") * 3
    texts = {"yazi": YAZI, "paket": YAZI + "\n" + ek, "baska": BASKA + ek,
             **{f"d{i}": f"dolgu {i} " + CEVRE for i in range(3)}}
    docs = {"yazi": {"tarih": "2025-08-05", "doc_type": "komisyon_tutanagi"},
            "paket": {"tarih": "2025-08-05", "doc_type": "komisyon_tutanagi"},
            "baska": {"tarih": "2025-01-14", "doc_type": "komisyon_tutanagi"},
            **{f"d{i}": {"tarih": None, "doc_type": "bilinmiyor"} for i in range(3)}}
    return texts, docs


def test_contained_copy_merged_into_container():
    from bidr.file import select as S
    texts, docs = _contained_setup()
    q = "teknik altyapı sorunlarına ilişkin yanıtlar değerlendirilmiş"
    items = [_item("B.3.3", "yazi", 4, q), _item("B.3.3", "paket", 2, q), _item("B.3.3", "baska", 4, q)]
    rest, merges = S.merge_contained(items, docs, texts.__getitem__, cited=set())
    ids = [it.doc_id for it in rest]
    assert ids == ["paket", "baska"]                       # tarihi farklı toplantı ayrı kalır
    paket = rest[0]
    assert "yazi" in paket.kopyalar_surum and paket.od == 4   # aynı içerik: tek kod OD'si
    assert merges[0]["uyeler"][0]["neden"] == "kapsanan_kopya"


def test_contained_copy_needs_quote_and_shares_number_when_cited():
    from bidr.file import select as S
    from bidr.file.naming import number_sources, source_key
    texts, docs = _contained_setup()
    q = "teknik altyapı sorunlarına ilişkin yanıtlar değerlendirilmiş"
    # alıntısı kapsayanda olmayan kalem katılmaz (başka içeriği kanıtlıyor olabilir)
    items = [_item("B.3.3", "yazi", 4, "bu cümle kapsayan belgede hiç geçmeyen ayrı bir içeriktir"),
             _item("B.3.3", "paket", 2, q)]
    rest, _ = S.merge_contained(items, docs, texts.__getitem__, cited=set())
    assert len(rest) == 2 and not getattr(rest[0], "kaynak_grubu", "")
    # metinde atıf yapılan kalem listede kalır ama kapsayanla tek numara ve tek OD taşır
    items = [_item("B.3.3", "yazi", 4, q), _item("B.3.3", "paket", 2, q)]
    rest, _ = S.merge_contained(items, docs, texts.__getitem__, cited={"yazi"})
    assert len(rest) == 2
    num = number_sources(rest, key=lambda i: source_key(i.doc_id, docs, i), od=lambda i: i.od)
    assert {(s, od) for s, od, _ in num} == {(1, 4)}


def test_copy_relation_ignores_stage_noise_but_keeps_periods():
    from bidr.file.select import Version, relation
    a = Version("a", {"tarih": "2025-08-05"}, YAZI, frozenset({"planla"}))
    b = Version("b", {"tarih": "2025-08-05"}, _ocr(YAZI), frozenset({"kontrol_et"}))
    assert relation(a, b)[0] == "ayri"                       # sürüm: planla ↔ üstü ayırır (boş form kuralı)
    assert relation(a, b, kopya=True) == ("ayni", "kopya")   # kopya: model gürültüsü ayırmaz
    c = Version("c", {"tarih": "2024-08-05"}, YAZI, frozenset({"kontrol_et"}))
    assert relation(b, c, kopya=True) == ("ayri", "farkli_yil")


# -- kanıt kodunun OD'si --------------------------------------------------------------------------

def _crit(od, **links):
    return {"od": od, "zincir": {x: {"durum": links.get(x, "yok")} for x in
                                 ("planla", "uygula", "kontrol_et", "onlem_al", "ozgun")}}


def test_evidence_od_consistent_with_criterion_chain():
    from bidr.file.naming import evidence_od
    k = [{"od": 4, "sayilir": True}]
    # yalnız izleme (K) var, iyileştirme yok: "OD4" etiketi ölçüt OD'sine iner
    assert evidence_od(k, _crit(3, planla="var", uygula="var", kontrol_et="var")) == 3
    assert evidence_od(k, _crit(2, planla="var", kontrol_et="var")) == 2
    # K ve Ö kurulmuş, alt halka eksik: kılavuz örneği (metin OD2, kanıt OD4) korunur
    assert evidence_od(k, _crit(2, planla="var", kontrol_et="var", onlem_al="var")) == 4
    assert evidence_od(k, _crit(3, planla="var", uygula="var", kontrol_et="yuvasiz", onlem_al="var")) == 4
    # yalnız OD verilirse (eski çağrı) davranış değişmez
    assert evidence_od(k, 2) == 4


# -- savunma: yönlendirme iyileştirme değildir ---------------------------------------------------------

def test_forwarding_decision_is_not_improvement(tmp_path):
    from bidr.audit.savunma import Savunma, f, yonlendirme
    assert yonlendirme(f("Öğrenci taleplerinin Bölüm Başkanlığına iletilmesine karar verilmiştir."))
    assert yonlendirme(f("Gereğini bilgilerinize arz ederiz."))
    assert not yonlendirme(f("Altyapı sorularının ayrı hazırlanarak değerlendirmeye katılmasına karar verilmiştir."))
    assert not yonlendirme(f("Yeni seçmeli dersin açılmasına ve Başkanlığa bildirilmesine karar verildi."))
    sv = Savunma(tmp_path)
    m = {"alinti": "anket sonuçlarına göre geri bildirimlerin Bölüm Başkanlığına iletilmesine karar verilmiştir"}
    out = sv.row({"doc_id": "x"}, m, "komisyon_tutanagi", "onlem_al", False)
    assert out["etkin"] == "kontrol_et" and "yonlendirme_onlem_degil" in out["flags"]
    m = {"alinti": "anket sonuçlarına göre altyapı sorularının ayrı hazırlanmasına karar verilmiştir"}
    assert sv.row({"doc_id": "x"}, m, "komisyon_tutanagi", "onlem_al", False)["etkin"] == "onlem_al"


# -- yönler: iç tutarlılık ve kanıtla çapraz denetim ---------------------------------------------------

def _meta(olgular, hedef=None):
    return {"alan": "C", "guclu_olcutler": ["C.1.2", "C.3.1"], "gelisme_olcutler": ["C.1.2", "C.3.1"],
            "od": {"C.1.2": 2, "C.3.1": 2}, "olgular": olgular, "hedef": hedef or {}}


def _kodlar(guclu, gelisme, meta):
    from bidr.write import yonler as Y
    t = {"guclu": [{"metin": x} for x in guclu], "gelisme": [{"metin": x} for x in gelisme]}
    return {(i["yer"], i["kod"]) for i in Y.cross_check(t, meta)}


def test_yonler_absence_claim_checked_against_evidence():
    bos = {"kanit": True, "uygulama": False, "izleme": False, "iyilestirme": False, "birim_kaniti": []}
    izl = {**bos, "izleme": True}
    birim = {**bos, "birim_kaniti": ["Bölüm Devam Eden Projeler Listesi"]}
    m = _meta({"C.1.2": izl, "C.3.1": bos})
    assert ("a1", "kanitla_celiski") in _kodlar([], ["İzleme sonuçlarına ilişkin kanıt bulunmamaktadır (C.1.2)."], m)
    # izleme yalnız niteleyici: iyileştirme hükmü, izleme halkası kanıtlı olsa da çelişki değil
    assert not _kodlar([], ["İzleme sonuçlarına dayanan iyileştirme kanıtı bulunmamaktadır (C.1.2)."], m)
    m = _meta({"C.1.2": birim, "C.3.1": bos})
    claim = "Dayanaklar yalnız kurum geneli düzenlemelerle eşleşmekte, bölümün uygulama kanıtı bulunmamaktadır (C.1.2)."
    assert ("a1", "kanitla_celiski") in _kodlar([], [claim], m)
    # nedeniyle yazılan hüküm çelişki değil
    assert not _kodlar([], ["Bölüme ait proje listesinin tarihi doğrulanamadığından OD'ye sayılmamıştır (C.1.2)."], m)
    assert not _kodlar([], ["Bölüme ait proje listesinde projelerin tarihi belgede görülmemektedir (C.1.2)."], m)
    assert not _kodlar([], [claim.replace("C.1.2", "C.3.1")], m)          # kanıt durumu gerçekten boş


def test_yonler_strong_and_weak_must_not_contradict():
    bos = {"kanit": True, "uygulama": False, "izleme": False, "iyilestirme": False, "birim_kaniti": []}
    m = _meta({"C.1.2": bos, "C.3.1": bos})
    zayif = "Bölümün dönem içindeki uygulamasına ilişkin kanıt bulunmamaktadır (C.1.2)."
    assert ("a1", "ic_celiski") in _kodlar(["Bölümde dış destekli projeler yürütülmektedir (C.1.2)."], [zayif], m)
    # yalnız tanım söyleyen güçlü yön, uygulama eksikliğiyle çelişmez
    assert not _kodlar(["Dış kaynakların kullanımı kurum yönergesiyle tanımlanmıştır (C.1.2)."], [zayif], m)


def test_yonler_below_target_indicator_not_strength():
    from bidr.write.yonler import target_state
    bos = {"kanit": True, "uygulama": False, "izleme": False, "iyilestirme": False, "birim_kaniti": []}
    g = "İzleme tablosunda öğretim üyesi başına yayın sayısı 0,36 olarak kaydedilmiştir (C.3.1)."
    assert ("g1", "hedef_alti_guclu") in _kodlar([g], [], _meta({"C.3.1": bos}))
    assert ("g1", "hedef_alti_guclu") in _kodlar([g], [], _meta({"C.3.1": bos}, {"C.3.1": "alti"}))
    assert not _kodlar([g], [], _meta({"C.3.1": bos}, {"C.3.1": "ok"}))
    # yalnız göstergenin tanımlandığını söyleyen madde değer iddiası değildir
    assert not _kodlar(["Performans göstergeleri 2022-2026 Stratejik Planında tanımlanmıştır (C.3.1)."], [],
                       _meta({"C.3.1": bos}))
    assert target_state("Gösterge değeri 0,36 olup hedefin altında kalmıştır.") == "alti"
    assert target_state("Yayın sayısı hedefine ulaşılmıştır.") == "ok"
    assert target_state("Yayın sayısı 7 olarak kaydedilmiştir.") is None
    # söz yoksa sayılar karşılaştırılır (kör test: "hedeflenen değeri 1.08 … gerçekleşme değeri 0.36")
    t = ("Göstergenin yılsonu hedeflenen değeri 1.08 ve gerçekleşme değeri 0.36 olarak yer almaktadır. "
         "2025 hedefi 1,08 olarak belirlenmiştir.")
    assert target_state(t) == "alti"
    assert target_state("2025 hedefi 1,08; gerçekleşme değeri 1,20 olmuştur.") == "ok"
    assert target_state("Hedef 2025 yılı için belirlenmiştir; gerçekleşme 2025 sonunda raporlanır.") is None
    # hedefin altındaki göstergenin izleme verisi (değer anmasa da) güçlü yön olmaz
    veri = "İzleme tablosunda bölüme ait yayın ve öğretim üyesi verisi yer almaktadır (C.3.1)."
    assert ("g1", "hedef_alti_guclu") in _kodlar([veri], [], _meta({"C.3.1": bos}, {"C.3.1": "alti"}))
    assert not _kodlar([veri], [], _meta({"C.3.1": bos}))


def test_yonler_faculty_value_not_unit_value():
    bos = {"kanit": True, "uygulama": False, "izleme": False, "iyilestirme": False, "birim_kaniti": []}
    m = _meta({"C.3.1": bos}, {"C.3.1": "alti"})
    fak = "Fakülte genelinde gösterge gerçekleşme değeri 0,36 olup hedefin altındadır (C.3.1)."
    assert ("a1", "fakulte_degeri") in _kodlar([], [fak], m)
    ikisi = "Bölümün gerçekleşme değeri 0,30, fakülte değeri 0,36 olup hedefin altındadır (C.3.1)."
    assert not _kodlar([], [ikisi], m)
    # "Fakülte Kurulu" kararı ve tarih gösterge değeri değildir
    kurul = "Öğretim planı 25.08.2025 tarihli Fakülte Kurulu kararıyla güncellenmiştir (C.1.2)."
    assert not _kodlar([kurul], [], _meta({"C.1.2": bos}))


def test_yonler_finding_names_uncounted_unit_evidence():
    from bidr.write.yonler import facts, findings
    a = {"od": 2, "sonraki_od": 3, "kurum_geneli_yalniz": True,
         "eksik": [{"halka": "uygula", "gereken": "bölümün uygulama kanıtı"}],
         "zincir": {"planla": {"durum": "var"}, "uygula": {"durum": "yok"}}}
    rows = [{"ad": "Kurum Yönergesi", "isaretler": "kurum_geneli"},
            {"ad": "Bölüm Proje Listesi", "isaretler": "tarih_dogrulanmali, od_sayilmadi"}]
    f = " ".join(findings(a, True, rows))
    assert "Bölüm Proje Listesi (tarihi belgede görülmüyor)" in f and "birime ait belge" in f
    assert "birimin kendi uygulamasını gösteren belge yok" not in f
    # bulgu rapor okurunun dilinde: düzey, halka, "OD'ye sayılmadı", "eşleşti" yok (kör test 2026-11-20)
    from bidr.write.ic_dil import bul
    assert not bul(f) and "OD" not in f
    o = facts(a, rows)
    assert o["birim_kaniti"] == ["Bölüm Proje Listesi"] and not o["uygulama"]
    # eski dizin (işaret sütunu yok): birim kanıtı bilinemez, eski bulgu
    assert facts(a, [{"ad": "x"}])["birim_kaniti"] == []
    assert "dayanak yalnız kurum geneli" in " ".join(findings(a, True, [{"ad": "x"}]))
