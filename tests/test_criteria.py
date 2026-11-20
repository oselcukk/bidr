"""Ölçüt şeması testleri. Yalnız repodaki YAML'a bağlıdır; docx gerekmez."""
from __future__ import annotations

import copy
import re

import pytest

from bidr.cli import main as bidr_main
from bidr.criteria import load_criteria, load_guide, validate
from bidr.criteria.loader import read_raw
from bidr.criteria.model import id_key

# FR-0833 R0 şablonunda sayılan alt ölçüt sayısı (A:18, B:18, C:7, D:3).
EXPECTED_SUB = 46


@pytest.fixture(scope="module")
def raw():
    return read_raw()


@pytest.fixture(scope="module")
def cs():
    return load_criteria()


def test_schema_valid(raw):
    assert validate(raw) == []


def test_counts(cs, raw):
    assert len(cs.sub_criteria) == EXPECTED_SUB
    assert raw["meta"]["counts"]["sub_criteria"] == EXPECTED_SUB
    assert [a.id for a in cs.areas] == ["A", "B", "C", "D"]
    assert len(cs.criteria) == 14


def test_rubric_five_levels_filled(cs):
    for s in cs.sub_criteria:
        assert sorted(s.rubric) == [1, 2, 3, 4, 5], s.id
        assert all(s.rubric[k].strip() for k in range(1, 6)), s.id


def test_required_fields_filled(cs):
    for s in cs.sub_criteria:
        assert s.title.strip() and s.units.strip(), s.id
        assert s.description and all(d.strip() for d in s.description), s.id
        assert s.example_evidence and all(e.strip() for e in s.example_evidence), s.id


def test_ids_unique_and_sorted(cs):
    for group in (cs.areas, cs.criteria, cs.sub_criteria):
        ids = [x.id for x in group]
        assert len(ids) == len(set(ids))
        assert ids == sorted(ids, key=id_key)


def test_ids_contiguous_and_parents(cs):
    main_ids = {c.id for c in cs.criteria}
    by_parent: dict[str, list[int]] = {}
    for s in cs.sub_criteria:
        assert re.fullmatch(r"[A-D]\.\d+\.\d+", s.id)
        assert s.parent in main_ids and s.id.startswith(s.parent + ".")
        by_parent.setdefault(s.parent, []).append(int(s.id.rsplit(".", 1)[1]))
    for parent, nums in by_parent.items():
        assert nums == list(range(1, len(nums) + 1)), parent
    assert set(by_parent) == main_ids


def test_lookup(cs):
    s = cs.get("A.1.2")
    assert s.title == "Liderlik" and s.parent == "A.1"
    assert cs.get("A.1.2.").id == "A.1.2"
    assert [c.id for c in cs.children("A")][:2] == ["A.1", "A.2"]
    with pytest.raises(KeyError):
        cs.get("Z.9.9")


def test_no_institution_or_personal_data(raw):
    import json
    blob = json.dumps(raw, ensure_ascii=False) + json.dumps(load_guide(), ensure_ascii=False)
    for bad in ("GTU", "GTÜ", "Gebze", "@", "http://", "https://"):
        assert bad not in blob, bad


def test_validate_detects_errors(raw):
    bad = copy.deepcopy(raw)
    del bad["sub_criteria"][0]["rubric"][3]
    assert any("rubric" in e for e in validate(bad))

    dup = copy.deepcopy(raw)
    dup["sub_criteria"][1]["id"] = dup["sub_criteria"][0]["id"]
    assert any("yinelenen" in e for e in validate(dup))

    swapped = copy.deepcopy(raw)
    swapped["sub_criteria"][0], swapped["sub_criteria"][1] = (
        swapped["sub_criteria"][1], swapped["sub_criteria"][0])
    assert any("sıralı değil" in e for e in validate(swapped))


def test_guide_sections():
    g = load_guide()
    names = [s["section"] for s in g["sections"]]
    for need in ("Yazım Kuralları", "Kanıt Gösterimi", "Ölçüt Değerlendirme Şekli"):
        assert need in names
    notation = g["evidence_notation"]
    assert re.search(notation["in_text"]["pattern"], "yapılmaktadır [2_OD4].").groups() == ("2", "4")
    m = re.match(notation["evidence_list"]["pattern"], "[1-OD3]. Uygulama Örnekleri.pdf")
    assert m and m.groups() == ("1", "3", "Uygulama Örnekleri.pdf")


def test_cli(capsys):
    assert bidr_main(["criteria", "validate"]) == 0
    assert f"{EXPECTED_SUB} alt ölçüt" in capsys.readouterr().out
    assert bidr_main(["criteria", "show", "A.1.2"]) == 0
    out = capsys.readouterr().out
    assert "A.1.2. Liderlik" in out and "5:" in out
    assert bidr_main(["criteria", "list"]) == 0
    assert "D.2.1." in capsys.readouterr().out
    assert bidr_main(["criteria", "show", "Z.9.9"]) == 1


def test_extract_annex_tables(tmp_path):
    """Kılavuz eki tabloları: alan başlığından sonra "Uygulama | Kanıt" satırları (sentetik şablon)."""
    import docx

    from bidr.criteria.extract_docx import extract_annex
    d = docx.Document()
    d.add_paragraph("Örnek Uygulama ve Kanıtlar Listesi")
    d.add_paragraph("LİDERLİK, YÖNETİŞİM VE KALİTE ÖRNEK UYGULAMALAR VE OLASI KANITLAR")
    t = d.add_table(rows=3, cols=2)
    for i, (a, b) in enumerate([("Uygulama", "Kanıt"), ("Sentetik şema\nhazırlanması", "Web sayfası linki"),
                                ("GTÜ komisyonu", "Karar")]):
        t.cell(i, 0).text, t.cell(i, 1).text = a, b
    d.add_paragraph("TOPLUMSAL KATKI ÖRNEK UYGULAMALAR VE OLASI KANITLAR")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "Uygulama", "Kanıt"
    t.cell(1, 0).text, t.cell(1, 1).text = "Sentetik etkinlik", "Duyuru"
    p = tmp_path / "s.docx"
    d.save(p)
    data, warn = extract_annex(p)
    assert not warn
    assert data["alanlar"] == {"A": "LİDERLİK, YÖNETİŞİM VE KALİTE", "D": "TOPLUMSAL KATKI"}
    assert data["meta"]["counts"] == {"A": 2, "D": 1}
    s = data["satirlar"]
    assert [x["id"] for x in s] == ["A/1", "A/2", "D/1"]
    assert s[0]["uygulama"] == "Sentetik şema hazırlanması"
    assert s[1]["uygulama"] == "[KURUM] komisyonu" and data["meta"]["redactions"]
