"""bidr.evaluate: ölçüler, bölmeler, sızıntı denetimi."""
from __future__ import annotations

import json

import pytest

from bidr.candidates.data import load
from bidr.cli import main
from bidr.evaluate.metrics import collapse, doc_metrics
from bidr.evaluate.run import SYSTEMS, LeakageError, Split, _make, louo_splits, transfer_split

from synth import CS, ctext, make_ws

VALID = {s.id for s in CS.sub_criteria}


def test_doc_metrics():
    m = doc_metrics(["A.1.1", "A.1.2", "B.1.1", "C.1.1"], {"B.1.1", "C.1.1"})
    assert m["R@1"] == 0 and m["R@3"] == 0.5 and m["R@5"] == 1.0
    assert m["H@3"] == 1.0 and m["H@1"] == 0.0
    assert m["MRR"] == pytest.approx(1 / 3)
    assert doc_metrics(["A.1.1"], {"D.1.1"})["MRR"] == 0.0


def test_collapse():
    assert collapse(["A.1.2", "B.1.1", "A.1.3", "A.2.1"]) == ["A.1", "B.1", "A.2"]


def _tbf(tmp_path):
    docs = [
        {"text": ctext("A.1.2", "u1 bir"), "gold": ["A.1.2"], "units": ["U1"]},
        {"text": ctext("A.1.2", "u1 u2 ortak"), "gold": ["A.1.2"], "units": ["U1", "U2"]},
        {"text": ctext("B.1.1", "u2 iki"), "gold": ["B.1.1"], "units": ["U2"]},
        {"text": ctext("B.1.1", "u3 üç"), "gold": ["B.1.1"], "units": ["U3"]},
        # aynı metin, farklı doc_id (pdf/docx gibi), farklı birim
        {"text": ctext("C.2.1", "kopya"), "gold": ["C.2.1"], "units": ["U3"], "id": "aaaaaaaaaaaaaaaa"},
        {"text": ctext("C.2.1", "kopya"), "gold": ["C.2.1"], "units": ["U1"], "id": "bbbbbbbbbbbbbbbb"},
        {"text": "", "gold": ["D.1.1"], "units": ["U3"]},
        {"text": ctext("D.2.1"), "gold": [], "units": ["U1"]},      # etiketsiz
    ]
    return make_ws(tmp_path / "tbf", docs), docs


def test_louo_ayrik(tmp_path):
    ws, docs = _tbf(tmp_path)
    sps = louo_splits(load(ws), VALID)
    assert [s.name for s in sps] == ["louo:U1", "louo:U2", "louo:U3"]
    for sp in sps:
        z = sp.leakage()
        assert z["doc_id_kesisim"] == 0 and z["metin_ozeti_kesisim"] == 0
        assert all(d.labeled for d in sp.train)
    u1 = sps[0]
    tr = {d.doc_id for d in u1.train}
    assert docs[1]["id"] not in tr                      # çok birimli belge U1 testinde
    assert "aaaaaaaaaaaaaaaa" not in tr                 # metin kopyası eğitimden atıldı
    assert u1.dropped_train == 1
    u3 = sps[2]
    assert [d.doc_id for d in u3.skipped] == [docs[6]["id"]]   # boş metin ölçüme girmez
    assert docs[7]["id"] not in {d.doc_id for d in u3.test}


def test_transfer_ortak_belge_egitimden_atilir(tmp_path):
    ws, docs = _tbf(tmp_path)
    te = make_ws(tmp_path / "mat", [
        {"text": docs[3]["text"], "gold": ["B.1.1"], "id": docs[3]["id"], "units": ["M"]},
        {"text": ctext("A.1.2", "yeni"), "gold": ["A.1.2"], "units": ["M"]},
    ])
    sp = transfer_split(load(ws), load(te), VALID, "t")
    assert docs[3]["id"] not in {d.doc_id for d in sp.train}
    assert sp.leakage()["doc_id_kesisim"] == 0 and sp.dropped_train == 1


def test_sizinti_yakalanir(tmp_path):
    ws, _ = _tbf(tmp_path)
    d = [x for x in load(ws) if x.labeled and x.usable]
    sp = Split("x", d[:2], d[:1], [], 0)
    assert sp.leakage()["doc_id_kesisim"] == 1
    # _make ortak içeriği atar, hata vermez
    assert _make("y", d, d[:1], VALID).leakage()["doc_id_kesisim"] == 0


def test_cli_evaluate(tmp_path):
    ws, _ = _tbf(tmp_path)
    te = make_ws(tmp_path / "mat", [{"text": ctext("B.1.1", "x"), "gold": ["B.1.1"], "units": ["M"]}])
    assert main(["evaluate", "--louo", str(ws), "--transfer", str(ws), str(te), "--name", "t", "-q"]) == 0
    data = json.loads((ws / "eval-t.json").read_text())
    names = [r["bolme"] for r in data["sonuclar"]]
    assert names == ["louo:U1", "louo:U2", "louo:U3", "louo:tbf:havuz", "tbf→mat"]
    for r in data["sonuclar"]:
        if "sizinti" in r:
            assert r["sizinti"]["doc_id_kesisim"] == 0
        assert set(r["olcu"]) == set(SYSTEMS)
        assert "R@10" in r["olcu"]["birlesik"]["ana"]
    assert (te / "eval-t.md").exists()
    md = (ws / "eval-t.md").read_text()
    assert "kapalı" in md and "Ölçüme girmeyen" in md


def test_yakin_kopya_egitimden_atilir(tmp_path):
    """Neredeyse aynı metin (başka tarama/sürüm: birkaç sözcük farkı) eğitimden atılır,
    sayılır; farklı belge kalır; eşik kapalıyken eski davranış."""
    from bidr.evaluate.run import NEAR_DUP, tf_cosine

    base = ctext("B.1.1", "toplanti tutanagi")
    tr = make_ws(tmp_path / "tr", [
        {"text": base + " imza sayfasi ek", "gold": ["B.1.1"], "units": ["T"]},   # yakın kopya
        {"text": ctext("A.1.2", "baska belge"), "gold": ["A.1.2"], "units": ["T"]},
        {"text": ctext("C.2.1"), "gold": ["C.2.1"], "units": ["T"]},
    ])
    te = make_ws(tmp_path / "te", [{"text": base, "gold": ["B.1.1"], "units": ["M"]}])
    trd, ted = load(tr), load(te)
    near_id = did_of(tr, 0)
    assert tf_cosine(next(d for d in trd if d.doc_id == near_id).bag, ted[0].bag) >= NEAR_DUP
    sp = transfer_split(trd, ted, VALID, "t")
    ids = {d.doc_id for d in sp.train}
    assert near_id not in ids and len(ids) == 2
    z = sp.leakage()
    assert z["egitimden_atilan_yakin_kopya"] == 1 and z["yakin_kopya_esigi"] == NEAR_DUP
    assert sp.near_dropped[0][:2] == (near_id, ted[0].doc_id)
    off = transfer_split(trd, ted, VALID, "t", near_dup=None)
    assert near_id in {d.doc_id for d in off.train}
    assert off.leakage()["egitimden_atilan_yakin_kopya"] == 0
    # eşik 1'e çekilirse bu çift atılmaz (birebir aynı değil)
    assert near_id in {d.doc_id for d in transfer_split(trd, ted, VALID, "t", near_dup=1.0).train}


def did_of(ws, i: int) -> str:
    import csv as _csv
    with open(ws / "inventory.csv", encoding="utf-8") as f:
        return list(_csv.DictReader(f))[i]["doc_id"]


def test_cli_yakin_kopya_raporu(tmp_path):
    base = ctext("B.1.1", "toplanti tutanagi")
    tr = make_ws(tmp_path / "tr", [
        {"text": base + " imza sayfasi ek", "gold": ["B.1.1"], "units": ["T"]},
        {"text": ctext("A.1.2", "baska belge"), "gold": ["A.1.2"], "units": ["T"]},
    ])
    te = make_ws(tmp_path / "te", [{"text": base, "gold": ["B.1.1"], "units": ["M"]}])
    assert main(["evaluate", "--transfer", str(tr), str(te), "--name", "y", "-q"]) == 0
    r = json.loads((te / "eval-y.json").read_text())["sonuclar"][0]
    assert r["sizinti"]["egitimden_atilan_yakin_kopya"] == 1 and len(r["yakin_kopyalar"]) == 1
    assert "eğitimden atılan yakın kopya" in (te / "eval-y.md").read_text()
    assert main(["evaluate", "--transfer", str(tr), str(te), "--name", "z", "--near-dup", "0", "-q"]) == 0
    r = json.loads((te / "eval-z.json").read_text())
    assert r["sonuclar"][0]["sizinti"]["egitimden_atilan_yakin_kopya"] == 0
    assert r["ayarlar"]["yakin_kopya_esigi"] is None
    assert "Yakın kopya denetimi kapalı" in (te / "eval-z.md").read_text()
