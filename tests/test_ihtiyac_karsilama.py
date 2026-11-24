"""bidr ihtiyac: istek "karşılandı" hesabı kabul edilmiş inceleme kararlarından (yol haritası Faz 1 madde 8).
Yalnız sentetik veri."""
from __future__ import annotations

from openpyxl import load_workbook

from bidr.ihtiyac import rapor as R
from bidr.ihtiyac import sade as S
from bidr.ihtiyac.eslestir import VAR
from bidr.ihtiyac.referans import build_reference

from test_ihtiyac import ALINTI, _m, _metin, _ws

T1 = _metin("SENTETIK BELGE", "korvane", "lispat", "durmeko", "faslin", "gortev")
T2 = _metin("SENTETIK BELGE", "pelvoru", "tanisk", "merdove", "kuspal", "virden")
T3 = _metin("SENTETIK BELGE", "zabrel", "nostik", "huvemar", "dilkos", "sarpet")
T4 = _metin("SENTETIK BELGE", "yorbek", "calmid", "fenusta", "rokval", "biltem")
SORU = "Bu dersin iş yükü AKTS kredisiyle uyumlu muydu?"


def _ref(tmp_path, rows: str):
    p = tmp_path / "ek.csv"
    p.write_text("olcut,belge_turu,ad,yuva\n" + rows, encoding="utf-8")
    return build_reference(None, ek=p)


def _hedef(tmp_path, docs):
    return _ws(tmp_path / "guncel", 2026, docs)


def _sade(res, cid):
    return {r["olcut"]: r for r in res["sade"]}.get(cid)


def _metinler(res, cid):
    """Açık (işaretsiz) istekler; dosyada karşılığı bulunan istek işaretli satırdadır, sayılmaz."""
    r = _sade(res, cid)
    return [m["metin"] for m in r["maddeler"] if not m.get("bulundu")] if r else []


def test_a_tur_duzeyinde_istek_ayni_turden_kabul_edilmis_belgeyle_kapanir(tmp_path):
    """Geçen yılki "MATH407 anket sonucu" B.3.1'de; bu yıl başka dersin anketi A.4.2'de kabul edilmiş: istenmez,
    "Var olan kanıt" sütununda karşılayan belge ve ölçütü."""
    ref = _ref(tmp_path, "B.3.1,anket_sonucu,MATH407 Ders Degerlendirme Anketi Sonucu 2024-2025,B.3.1/3\n")
    ws = _hedef(tmp_path, {"m204": ("anket_sonucu", True, "2026-02-01", "Math 204 Ders Degerlendirme Anketi Sonucu", T1,
                                    [_m("A.4.2", "A.4.2/2", "uygula", 3)], "kabul")})
    res = R.run(ws, referans=ref, out=tmp_path / "o")
    g = res["gecen"][0]
    assert g["durum"] == VAR and g["karsilama"]["olcut"] == "A.4.2" and "tür" in g["karsilama"]["neden"]
    assert not any("anket" in m.lower() and "MATH407" in m for m in _metinler(res, "B.3.1"))
    assert not any(t["kaynak"] == "geçen yıl" for t in res["talepler"] if t["olcut"] == "B.3.1")
    r = _sade(res, "B.3.1")
    kap = [m for m in r["maddeler"] if m.get("bulundu")]
    assert len(kap) == 1 and "Herhangi bir dersin" in kap[0]["metin"]
    assert kap[0]["dosyada"] == "Dosyada var: «Math 204 Ders Degerlendirme Anketi Sonucu» (A.4.2 ölçütünde)"
    assert r["karsilanan"] == []
    # incelemede reddedilmiş aynı türden belge kapatmaz
    ws2 = _ws(tmp_path / "guncel2", 2026, {"m204": ("anket_sonucu", True, "2026-02-01", "Math 204 Anket", T1,
                                                    [_m("A.4.2", "A.4.2/2", "uygula", 3)], "ret")})
    res2 = R.run(ws2, referans=ref, out=tmp_path / "o2")
    assert res2["gecen"][0]["durum"] != VAR
    assert any("Herhangi bir dersin" in m for m in _metinler(res2, "B.3.1"))


def test_b_baska_olcutte_kanit_olan_kurum_belgesi_istenmez(tmp_path):
    ref = _ref(tmp_path, "A.1.4,is_akisi,GTU Is Akislari Listesi,A.1.4/2\n")
    ws = _hedef(tmp_path, {"akis": ("is_akisi", None, "2025-01-01", "Kurum Is Akislari Listesi", T2,
                                    [_m("A.3.4", "A.3.4/1", "planla", 2)], "kabul")})
    kurum = {"ogeler": [{"id": "K1", "ad": "Is Akislari Listesi", "kod": "", "tur": "is_akisi", "ilgili": True,
                         "olcutler": ["A.1.4"]},
                        {"id": "K2", "ad": "Sentetik Danismanlik Yonergesi", "kod": "YO-0042", "tur": "yonerge",
                         "ilgili": True, "olcutler": ["A.1.4"]}]}
    res = R.run(ws, referans=ref, out=tmp_path / "o", kurum=kurum)
    g = res["gecen"][0]
    assert g["durum"] == VAR and g["karsilama"]["olcut"] == "A.3.4"
    assert g["karsilama"]["metin"] == "«Kurum Is Akislari Listesi» (A.3.4 ölçütünde)"
    r = _sade(res, "A.1.4")
    kur = [m["metin"] for m in r["kurum"]]
    assert kur == ["Sentetik Danismanlik Yonergesi (YO-0042)"]          # dosyada olan iş akışı listesi istenmez
    assert any("Is Akislari Listesi" in x and "A.3.4 ölçütünde" in x for x in r["karsilanan"])


def test_c_ayni_olcutte_ayni_turden_baska_belgeyle_karsilanmis(tmp_path):
    """Geçen yılın seminer duyuruları bu yıl aynı ölçütte başka bir seminer duyurusuyla karşılanmış; yuvası başka
    türden belgeyle (yönerge, çalıştay programı) dolu olsa kapanmaz."""
    ref = _ref(tmp_path, "B.3.5,etkinlik_duyurusu,2024-2025 Bahar Donemi Bolum Seminerleri,B.3.5/2\n")
    ws = _hedef(tmp_path, {
        "yon": ("yonerge", None, "2024-01-01", "Akademik Atama Kosullari Yonergesi", T4,
                [_m("B.3.5", "B.3.5/2", "planla", 2)], "kabul"),
        "sem": ("etkinlik_duyurusu", True, "2026-03-27", "Bolum Genel Seminer Duyurusu Mart 2026", T3,
                [_m("B.3.5", "B.3.5/1", "planla", 3)], "kabul")})
    res = R.run(ws, referans=ref, out=tmp_path / "o")
    g = res["gecen"][0]
    assert g["durum"] == VAR and g["karsilama"]["olcut"] == "B.3.5" and "başka belgeyle" in g["karsilama"]["neden"]
    assert g["karsilama"]["ad"] == "Bolum Genel Seminer Duyurusu Mart 2026"
    # yalnız başka türden belgeler: yuva dolu da olsa kapanmaz
    ws2 = _ws(tmp_path / "g2", 2026, {
        "yon": ("yonerge", None, "2024-01-01", "Akademik Atama Kosullari Yonergesi", T4,
                [_m("B.3.5", "B.3.5/2", "planla", 2)], "kabul"),
        "cal": ("faaliyet_raporu", True, "2026-03-01", "Sentetik Calistay Programi", T3,
                [_m("B.3.5", "B.3.5/2", "uygula", 3)], "kabul")})
    res2 = R.run(ws2, referans=ref, out=tmp_path / "o2")
    assert res2["gecen"][0]["durum"] != VAR
    assert any("Bolum Seminerleri" in m for m in _metinler(res2, "B.3.5"))
    # aynı türden ama yalnız zayıf kanıt: kapanmaz
    ws3 = _ws(tmp_path / "g3", 2026, {"sem": ("etkinlik_duyurusu", True, "2026-03-27", "Bolum Seminer Duyurusu", T3,
                                              [{**_m("B.3.5", "B.3.5/2", "uygula", 3), "alinti": "Seminer yapıldı."}],
                                              "kabul")})
    assert R.run(ws3, referans=ref, out=tmp_path / "o3")["gecen"][0]["durum"] != VAR


def test_c2_tur_ifadesi_zorunlu_karsilayan_belge_dogru_secilir(tmp_path):
    """Sınıflandırma aynı (anket_sonucu) olsa da adı başka tür söyleyen belge (toplantı haberi) anket sonucu
    değildir; tür ifadesi ortak belgeler arasından adı en yakın olan gösterilir. İş akışları listesi tek bir iş
    akışıyla, fotoğraf isteği iş akışıyla kapanmaz. Kapanan istek kendi satırında işaretli; not o satırda."""
    ref = _ref(tmp_path, "A.4.2,anket_sonucu,MATH407 Ders Degerlendirme Anketi Sonucu 2024-2025,A.4.2/2\n"
                         "A.3.4,is_akisi,GTU Kalite Ofisi Is Akislari Listesi,A.3.4/1\n"
                         "B.3.4,altyapi_listesi,Bolum Fiziki Olanaklar Fotograflari,B.3.4/1\n"
                         "B.1.4,ders_bilgi_formu,MAT308 Olasilik Teorisi Ders Bilgi Formu,B.1.4/1\n")
    ws = _hedef(tmp_path, {
        "hab": ("anket_sonucu", True, "2026-02-01", "2025 Yonetimin Gozden Gecirmesi Toplantisi Haberi", T1,
                [_m("A.4.2", "A.4.2/2", "kontrol_et", 3)], "kabul"),
        "ank": ("anket_sonucu", True, "2026-02-01", "Ders Degerlendirme Anketi Sonuclari", T2,
                [_m("A.4.2", "A.4.2/2", "uygula", 3)], "kabul"),
        "bas": ("is_akisi", None, "2025-01-01", "Bolum Baskani Secimi Is Akisi", T3,
                [_m("A.3.4", "A.3.4/1", "planla", 2)], "kabul"),
        "eng": ("is_akisi", None, "2025-01-01", "Engelli Ogrenci Basvuru Is Akisi", T4,
                [_m("B.3.4", "B.3.4/1", "planla", 2)], "kabul"),
        "muf": ("mufredat", True, "2026-01-01", "Bolum Yuzde Yuz Ingilizce Mufredati", T1,
                [_m("B.1.4", "B.1.4/1", "uygula", 3)], "kabul"),
        "dbf": ("bilinmiyor", True, "2026-01-01", "MATH113 Lineer Cebir I Ders Bilgi Formu", T2,
                [_m("B.1.4", "B.1.4/1", "uygula", 3)], "kabul")})
    res = R.run(ws, referans=ref, out=tmp_path / "o")
    by = {g["olcut"]: g for g in res["gecen"]}
    assert by["A.4.2"]["durum"] == VAR and by["A.4.2"]["karsilama"]["ad"] == "Ders Degerlendirme Anketi Sonuclari"
    assert "Toplantisi" not in by["A.4.2"]["karsilama"]["metin"]
    assert by["A.3.4"]["durum"] != VAR                      # tek iş akışı, iş akışları listesi değil
    assert by["B.3.4"]["durum"] != VAR                      # fotoğraf isteği iş akışıyla kapanmaz
    assert by["B.1.4"]["durum"] == VAR and by["B.1.4"]["karsilama"]["ad"] == "MATH113 Lineer Cebir I Ders Bilgi Formu"
    # Excel: kapanan istek kendi satırında ☑, notu aynı satırda; başka satırda "İstenmedi" yok
    wb = load_workbook(res["paths"]["sade"])[S.SHEETS[0]]
    rows = [[c.value for c in row] for row in wb.iter_rows(min_row=S.BASLIK_SATIRI + 1)]
    a42 = [x for x in rows if x[0] and str(x[0]).startswith("A.4.2") and x[1] in (S.BOS, S.DOLU)]
    hit = [x for x in a42 if x[1] == S.DOLU]
    assert len(hit) == 1 and "Herhangi bir dersin" in hit[0][3]
    assert "Dosyada var: «Ders Degerlendirme Anketi Sonuclari»" in hit[0][5]
    assert not any("İstenmedi" in str(x[5] or "") for x in rows)
    assert S.bilgi_denetimi(res["sade"], res["paths"]["sade"]) == []



def test_d_zayif_kanit_yuvayi_kismen_doldurur_istek_somut_kalir(tmp_path):
    ws = _hedef(tmp_path, {
        "ank": ("anket_formu", True, "2026-01-10", "Ders Degerlendirme Anket Formu", T4,
                [{**_m("B.1.4", "B.1.4/7", "uygula", 3), "alinti": SORU}], "kabul"),
        "dbf": ("ders_bilgi_formu", True, "2026-01-10", "Ders Bilgi Formu", T1,
                [{**_m("B.1.4", "B.1.4/1", "uygula", 3), "alinti": ALINTI}], "kabul")})
    res = R.run(ws, out=tmp_path / "o")
    s = {x["olcut"]: x for x in res["satirlar"]}["B.1.4"]
    assert "B.1.4/7" in s["karsilanmamis_yuvalar"] and "B.1.4/1" not in s["karsilanmamis_yuvalar"]
    assert s["kismen_yuvalar"] == {"B.1.4/7": ["Ders Degerlendirme Anket Formu"]}
    t = next(t for t in res["talepler"] if t["olcut"] == "B.1.4" and "B.1.4/7" in t["yuvalar"])
    assert "kısmen karşılanmış (yalnız zayıf kanıt: «Ders Degerlendirme Anket Formu»" in t["gerekce"]
    r = _sade(res, "B.1.4")
    m = next(m for m in r["maddeler"] if "iş yükü hesap tabloları" in m["metin"])
    assert m["dosyada"] == "kısmen: «Ders Degerlendirme Anket Formu» (tek soru ya da kısa alıntı)"
    # Excel: "Var olan kanıt" sütununda o isteğin satırında zayıf kanıt
    wb = load_workbook(res["paths"]["sade"])[S.SHEETS[0]]
    rows = [[c.value for c in row] for row in wb.iter_rows(min_row=S.BASLIK_SATIRI + 1)]
    hit = [x for x in rows if x[3] == m["metin"]]
    assert hit and "Bu istek için: kısmen: «Ders Degerlendirme Anket Formu»" in hit[0][5]
    assert S.bilgi_denetimi(res["sade"], res["paths"]["sade"]) == []
