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
    r = _sade(res, cid)
    return [m["metin"] for m in r["maddeler"]] if r else []


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
    assert r and r["karsilanan"] == ["«MATH407 Ders Degerlendirme Anketi Sonucu 2024-2025» yerine "
                                     "«Math 204 Ders Degerlendirme Anketi Sonucu» (A.4.2 ölçütünde)"]
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


def test_c_ayni_yuva_baska_belgeyle_karsilanmis(tmp_path):
    """Geçen yılın seminer duyurularının yuvası bu yıl başka bir belgeyle (çalıştay programı) tam dolu."""
    ref = _ref(tmp_path, "B.3.5,etkinlik_duyurusu,Bolum Seminer Duyurulari 2025,B.3.5/2\n")
    ws = _hedef(tmp_path, {"cal": ("faaliyet_raporu", True, "2026-03-01", "Sentetik Calistay Programi", T3,
                                   [_m("B.3.5", "B.3.5/2", "uygula", 3)], "kabul")})
    res = R.run(ws, referans=ref, out=tmp_path / "o")
    g = res["gecen"][0]
    assert g["durum"] == VAR and g["karsilama"]["olcut"] == "B.3.5" and "başka belgeyle" in g["karsilama"]["neden"]
    assert not any("Seminer Duyurulari" in m for m in _metinler(res, "B.3.5"))
    # aynı yuva yalnız zayıf kanıtla doluysa kapanmaz
    ws2 = _ws(tmp_path / "g2", 2026, {"cal": ("faaliyet_raporu", True, "2026-03-01", "Calistay", T3,
                                              [{**_m("B.3.5", "B.3.5/2", "uygula", 3), "alinti": "Çalıştay yapıldı."}],
                                              "kabul")})
    assert R.run(ws2, referans=ref, out=tmp_path / "o2")["gecen"][0]["durum"] != VAR


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
