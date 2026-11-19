"""Kanıt yuvaları, PUKÖ etiket önerileri, birim profili, öz-referans türleri, yuva sinyali."""
from __future__ import annotations

import copy
from collections import Counter

import pytest

from bidr.candidates.data import load
from bidr.candidates.model import Model, SlotBM25
from bidr.candidates.run import build
from bidr.candidates.text import tokens
from bidr.cli import main
from bidr.common import read_jsonl
from bidr.criteria.profiles import Profile, excluded_types, load_profile
from bidr.criteria.slots import STAGE_OD, load_tags, read_tags, tag_summary, validate_tags
from bidr.evaluate.run import _make

from synth import CS, ctext, make_ws

VALID = {s.id for s in CS.sub_criteria}


def test_yuva_kimlikleri_ve_metin():
    sl = CS.slots()
    assert len(sl) == 273
    assert len({s.id for s in sl}) == 273
    assert sum(len(s.example_evidence) for s in CS.sub_criteria) == 273
    x = CS.get_slot("A.2.2/4")
    assert x.criterion == "A.2.2" and x.index == 4
    assert x.text == CS.get("A.2.2").example_evidence[3]          # birebir
    assert [s.id for s in CS.get("A.1.1").slots] == [f"A.1.1/{i}" for i in range(1, 5)]
    with pytest.raises(KeyError):
        CS.get_slot("A.2.2/99")
    with pytest.raises(KeyError):
        CS.get_slot("A.2/1")


def test_dipnot_yuvalari():
    fn = [s for s in CS.slots() if s.footnote]
    assert all("AKTS" in s.text for s in fn) and len(fn) == 5
    assert len(CS.slots(include_footnotes=False)) == 268


def test_etiket_dosyasi_gecerli_ve_tam():
    tags = load_tags(CS)
    assert set(tags) == {s.id for s in CS.slots()}
    assert all(t.state in ("oneri", "onayli") for t in tags.values())
    for t in tags.values():
        assert list(t.od) == sorted({STAGE_OD[s] for s in t.stages if s in STAGE_OD})
        assert t.text == CS.get_slot(t.slot).text
    oz = tag_summary(tags)
    assert oz["yuva"] == 273 and oz["dipnot"] == 5
    assert oz["belirsiz"] == sum(t.uncertain for t in tags.values() if t.kind != "dipnot")


def test_etiket_dogrulama_hatalari():
    raw = read_tags()
    assert validate_tags(raw, CS) == []
    bad = copy.deepcopy(raw)
    bad["etiketler"][0]["metin"] += " x"
    bad["etiketler"][1]["asama"] = ["planla", "belirsiz"]
    bad["etiketler"][2]["od"] = [5]
    del bad["etiketler"][3]
    errs = "\n".join(validate_tags(bad, CS))
    assert "birebir değil" in errs and "belirsiz başka" in errs
    assert "od" in errs and "etiketsiz yuva" in errs


def test_profil_akademik_bolum():
    p = load_profile("akademik_bolum")
    dec = {d.criterion: d for d in p.decisions(CS)}
    assert dec["A.3.1"].verdict == "haric" and not dec["A.3.1"].keep
    assert dec["A.3.2"].verdict == "haric"
    # ölçütü kılavuzda adı yazan birim doldurur: bölümü kapsamayanlar doldurulmaz
    assert dec["A.3.3"].verdict == "haric" and not dec["A.3.3"].keep
    assert dec["C.1.3"].verdict == "haric"
    assert dec["A.1.1"].verdict == "dahil"
    assert len(p.allowed(CS)) == 42


def test_profil_kurallari():
    p = Profile("x", ("TÜM AKADEMİK BİRİMLER",), ("TÜM ENSTİTÜLER",), "dus", {"A.1.1": "haric"})
    assert p.decide("Z", "tüm akademik  birimler, KAGEM").keep
    assert not p.decide("Z", "TÜM ENSTİTÜLER, KAGEM").keep          # dus politikası
    assert p.decide("A.1.1", "TÜM AKADEMİK BİRİMLER").verdict == "haric"   # elle karar önce


def test_haric_turler_veri():
    assert {"bidr_sablonu", "olcut_aciklama_taslagi", "bidr_raporu"} <= excluded_types()


def test_yuva_sinyali_dogru_yuvayi_bulur():
    sb = SlotBM25(CS)
    hit = 0
    slots = CS.slots(include_footnotes=False)
    for x in slots:
        sc = sb.slot_scores(Counter(tokens(x.text)))
        hit += sb.crit[max(sc, key=sc.get)] == x.criterion
    assert hit >= 0.6 * len(slots)
    sc = sb.slot_scores(Counter(tokens(CS.get_slot("A.2.2/4").text)))
    assert max(sc, key=sc.get) == "A.2.2/4"


def _ws(tmp_path):
    pad = " dolgu" * 60
    docs = [
        {"text": ctext("A.2.2", "a"), "gold": ["A.2.2"], "units": ["U1"]},
        {"text": ctext("A.3.1", "b"), "gold": ["A.3.1"], "units": ["U1"]},
        {"text": CS.get_slot("A.2.2/4").text + pad, "gold": ["A.2.2"], "units": ["U2"]},
        {"text": ctext("B.1.1", "öz rapor") + pad, "gold": ["B.1.1"], "units": ["U2"]},
    ]
    ws = make_ws(tmp_path / "ws", docs)
    types = {docs[3]["id"]: "bidr_raporu", docs[0]["id"]: "stratejik_plan"}
    return make_ws(tmp_path / "ws", docs, types), docs


def test_candidates_yuva_profil_haric(tmp_path):
    ws, docs = _ws(tmp_path)
    assert main(["candidates", "-w", str(ws), "--train", str(ws), "--profile", "akademik_bolum",
                 "--signals", "yuva,knn,tur,oncel", "--out", "candidates-slots.jsonl"]) == 0
    assert not (ws / "candidates.jsonl").exists()
    rows = {r["doc_id"]: r for r in read_jsonl(ws / "candidates-slots.jsonl")}
    r = rows[docs[2]["id"]]
    assert r["en_iyi_yuvalar"][0]["yuva"] == "A.2.2/4"
    assert r["adaylar"][0]["olcut"] == "A.2.2"
    assert r["adaylar"][0]["yuvalar"][0]["yuva"] == "A.2.2/4"
    for x in rows.values():
        assert all(a["olcut"] not in ("A.3.1", "A.3.2") for a in x["adaylar"])
    ex = rows[docs[3]["id"]]
    assert ex["haric"] == "oz_referans_turu" and ex["adaylar"] == []


def test_varsayilan_birlesik_bes_sinyal(tmp_path):
    """Varsayılan birleşik beş sinyalin tamamıdır (yuva dahil; şef kararı 2026-11-18)."""
    ws, docs = _ws(tmp_path)
    m = Model(CS).fit(load(ws))
    for d in load(ws):
        a, _ = m.rank(d)
        b, _ = m.rank(d, ("bm25", "yuva", "knn", "tur", "oncel"))
        assert [x[0] for x in a] == [x[0] for x in b]


def test_haric_tur_egitime_ve_teste_girmez(tmp_path):
    ws, docs = _ws(tmp_path)
    d = load(ws)
    ex = frozenset({"bidr_raporu"})
    sp = _make("t", d, [x for x in d if "U2" in x.units], VALID, ex)
    assert docs[3]["id"] not in {x.doc_id for x in sp.test}
    assert sp.excluded_test == 1
    sp2 = _make("t2", d, [x for x in d if "U1" in x.units], VALID, ex)
    assert docs[3]["id"] not in {x.doc_id for x in sp2.train} and sp2.excluded_train == 1
    m = Model(CS, excluded_types=ex).fit(d)
    assert docs[3]["id"] not in {x.doc_id for x in m.train}


def test_yuva_sinyali_ad_yol_iz_kullanmaz(tmp_path):
    ws, docs = _ws(tmp_path)
    rows1, _ = build(ws, [ws], signals=("yuva", "knn", "tur", "oncel"))
    inv = (ws / "inventory.csv").read_text().replace("klasor/", "A.3.1 Bilgi/")
    (ws / "inventory.csv").write_text(inv)
    rows2, _ = build(ws, [ws], signals=("yuva", "knn", "tur", "oncel"))
    assert rows1 == rows2


def test_cli_slots_profile(capsys):
    assert main(["criteria", "slots", "A.2.2"]) == 0
    assert "A.2.2/4" in capsys.readouterr().out
    assert main(["criteria", "profile", "akademik_bolum"]) == 0
    assert "42/46" in capsys.readouterr().out
