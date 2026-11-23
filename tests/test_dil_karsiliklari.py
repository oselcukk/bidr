"""Türkçe–İngilizce karşılık sözlüğü ve izlence türü önceliği (sentetik veri)."""
from __future__ import annotations

from bidr.candidates.data import load
from bidr.candidates.dil import cross_terms, expand_bag, load_groups, query_terms
from bidr.candidates.ikinci import Archive, Searcher, query_bag
from bidr.candidates.model import Model
from bidr.candidates.run import build, candidate_row, type_priorities
from bidr.candidates.text import bag
from bidr.identify.catalog import load_catalog

from synth import CS, ctext, make_ws

SYLLABUS = """MATH 102 Calculus II Syllabus - Spring 2026
Instructor: Dr. Example. Email: example@example.edu
Office Hours: Wednesday 14:00-15:00 or by appointment.
Course Description: sequences, series, integration techniques, applications.
Textbook: Thomas' Calculus. Weekly schedule: week 1 sequences, week 2 series,
week 3 power series, week 4 Taylor series, week 5 integration by parts.
Course policies: attendance is expected; late submissions are not accepted.
Academic integrity: plagiarism and cheating are reported to the dean.
""" * 2

TR_DOCS = [
    ctext("A.1.2", "kurul toplantısı danışmanlık sınav ödev"),
    ctext("B.1.1", "program tasarımı ve onayı"),
    ctext("C.2.1", "araştırma ağı ve yetkinlik"),
    "Bölüm kurulu toplantısında öğrenci danışmanlığı, sınav programı ve staj "
    "başvuruları görüşüldü; anket sonuçları değerlendirildi. " * 6,
]


def test_sozluk_yuklenir_ve_iki_dil_var():
    g = load_groups()
    assert len(g) >= 12
    assert all(grp["tr"][0] and grp["en"][0] for grp in g)


def test_ingilizce_ofis_saati_turkce_danisman_belirteci_ekler():
    add = cross_terms("Office Hours: by appointment", only_from="en")
    assert "danis" in add and "ofis" in add
    assert {"advis", "offic"} <= set(query_terms("Öğrencilerin danışmanlara erişimi"))


def test_turkce_belge_torbasi_degismez():
    for t in TR_DOCS:
        b = dict(bag(t))
        assert expand_bag(t, b) == b


def test_ek_uzantisi_baska_sozcuge_tasmaz():
    # "intern" "international" ile eşleşmemeli; yalnız tam öbekler (sonda ek serbest)
    assert cross_terms("international conference", only_from="en") == []
    assert "staj" in cross_terms("summer internships", only_from="en")


def test_izlence_turu_onceligi_katalogda():
    t = load_catalog().get("ders_izlencesi")
    assert t.criteria_priority.get("B.3.2") == 1.0
    assert "ders_izlencesi" in type_priorities()


def _ws(tmp_path, doc_type=None):
    docs = [{"text": t, "gold": [g], "units": ["U"]}
            for t, g in zip(TR_DOCS, ["A.1.2", "B.1.1", "C.2.1", "A.1.2"])]
    docs.append({"text": SYLLABUS, "gold": [], "units": ["U"], "id": "e" * 16})
    types = {"e" * 16: doc_type} if doc_type else None
    return make_ws(tmp_path / "ws", docs, types), docs


def _row(ws, did, **kw):
    rows, _ = build(ws, [ws], 10, **kw)
    return next(r for r in rows if r["doc_id"] == did)


def test_ingilizce_izlence_b32_adayi_olur(tmp_path):
    ws, _ = _ws(tmp_path, "ders_izlencesi")
    r = _row(ws, "e" * 16)
    assert len(r["adaylar"]) == 10                  # aday sayısı değişmez
    assert "B.3.2" in [a["olcut"] for a in r["adaylar"]]


def test_tur_bilinmese_de_sozluk_b32_yuvasina_getirir(tmp_path):
    ws, _ = _ws(tmp_path)
    r = _row(ws, "e" * 16, type_priority={})
    assert "B.3.2" in [a["olcut"] for a in r["adaylar"]]
    m = Model(CS).fit(load(ws))
    d = next(x for x in load(ws) if x.doc_id == "e" * 16)
    assert "B.3.2" in m.criterion_slots(d)
    # sözlük olmadan (özgün torba) B.3.2 yuvasıyla hiç ortak sözcük yok
    d.xbag = None
    assert "B.3.2" not in m.criterion_slots(d)


def test_turkce_belgelerde_aday_listesi_sozlukten_etkilenmez(tmp_path):
    ws, docs = _ws(tmp_path)
    m = Model(CS).fit(load(ws))
    for d in load(ws):
        if d.doc_id == "e" * 16:
            continue
        a = candidate_row(m, d, 10)
        d.xbag = None
        assert candidate_row(m, d, 10) == a


def test_ikinci_arama_turkce_sorgu_ingilizce_belgeyi_bulur(tmp_path):
    ws, _ = _ws(tmp_path)
    q, added = query_bag(CS, "B.3.2")
    assert "advis" in added and "offic" in q
    s = Searcher(CS, Archive.load(ws))
    rows, _ = s.search("B.3.2")
    assert "e" * 16 in [r["doc_id"] for r in rows]
