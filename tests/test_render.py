"""bidr render: sentetik FR-0833 benzeri şablon → doldur → yeniden oku (model yok, gerçek şablon yok)."""
from __future__ import annotations

import json
from pathlib import Path

import docx
import pytest
from docx.oxml.ns import qn
from lxml import etree

from bidr.cli import main
from bidr.common import sha256_file
from bidr.criteria.extract_docx import W, _ptext
from bidr.render.run import BOS_IFADE, BOS_KANIT, DOGRULANMADI, GOLGE, TASLAK_METNI, Options, render
from bidr.render.template import find_blocks

PLACEHOLDER_A = "Bu bölüme açıklayıcı metin yazılmalı."
PLACEHOLDER_K = "Kanıtlar buraya yazılmalı."


def _merged_row(table, text_lines: list[str]):
    row = table.add_row()
    cell = row.cells[0].merge(row.cells[4])
    cell.paragraphs[0].text = text_lines[0]
    for t in text_lines[1:]:
        cell.add_paragraph(t)
    return cell


def make_template(path: Path) -> Path:
    d = docx.Document()
    sec = d.sections[0]
    sec.header.paragraphs[0].text = "ŞABLON ÜSTBİLGİSİ"
    sec.different_first_page_header_footer = True
    d.add_paragraph("BİRİM İÇ DEĞERLENDİRME RAPORU")
    d.add_paragraph("…………………….[Birim Adı]")
    d.add_paragraph("2025")
    d.add_paragraph("Yazım kuralları örneği 2547 sayılı kanun")
    d.add_paragraph("ÖLÇÜTLER VE KANITLAR")
    for sid, title in (("A.1.1", "Yönetişim modeli"), ("A.1.2", "Liderlik")):
        t = d.add_table(rows=0, cols=5)
        t.style = "Table Grid"
        _merged_row(t, ["DOLDURACAK BİRİMLER: TÜM AKADEMİK BİRİMLER"])
        _merged_row(t, [f"{sid}. {title}", "Sentetik ölçüt açıklaması."])
        r = t.add_row()
        for i, c in enumerate(r.cells):
            c.text = str(i + 1)
        r = t.add_row()
        for i, c in enumerate(r.cells):
            c.text = f"Sentetik rubrik düzey {i + 1} ({sid})"
        _merged_row(t, ["Örnek Kanıtlar:", "Sentetik örnek kanıt"])
        _merged_row(t, ["Açıklamalar:", PLACEHOLDER_A, "", ""])
        _merged_row(t, ["Kanıtlar:", PLACEHOLDER_K, ""])
        d.add_paragraph("")
    d.add_paragraph("SON BÖLÜM")
    d.save(str(path))
    return path


def write_text(texts: Path, cid: str, **kw) -> None:
    texts.mkdir(parents=True, exist_ok=True)
    t = {"olcut": cid, "od_onerisi": 3, "durum": "dogrulandi",
         "paragraflar": [{"metin": f"{cid} sentetik paragraf bir [1_OD3].", "atiflar": ["1_OD3"]},
                         {"metin": f"{cid} sentetik paragraf iki [2_OD2].", "atiflar": ["2_OD2"]}],
         "kanitlar": [{"no": "1_OD3", "ad": "Sentetik kanıt bir", "dosya": "a.pdf"},
                      {"no": "2_OD2", "ad": "Sentetik kanıt iki", "dosya": "b.pdf"}],
         "eksikler": [], "onceki_yila_gore": "", "kaynak": {"model": "test", "gorev_surumu": "0"}}
    t.update(kw)
    (texts / f"{cid}.json").write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")


def write_audit(ws: Path, ods: dict[str, int]) -> Path:
    p = ws / "audit-olcutler.json"
    p.write_text(json.dumps({"surum": 1, "olcutler": [
        {"olcut": c, "od": od, "eksik": [{"halka": "uygula", "gereken": f"{c} için uygulama kanıtı"}]}
        for c, od in ods.items()]}, ensure_ascii=False), encoding="utf-8")
    return p


@pytest.fixture
def ws(tmp_path):
    w = tmp_path / "ws"
    w.mkdir()
    make_template(tmp_path / "sablon.docx")
    return w


def _lines(tc) -> list[str]:
    return [_ptext(p) for p in tc.iter(W + "p")]


def _bold_cols(block) -> list[int]:
    out = []
    for od in range(1, 6):
        for tc in block.rubric_cells(od):
            for r in tc.iter(W + "r"):
                b = r.find(W + "rPr/" + qn("w:b")) if r.find(W + "rPr") is not None else None
                if b is not None and b.get(qn("w:val")) in (None, "1", "true"):
                    out.append(od)
                    break
    return sorted(set(out))


def _run(ws, tmp_path, **kw):
    out = ws / "report.docx"
    res = render(tmp_path / "sablon.docx", out, texts_dir=ws / "texts",
                 audit_path=ws / "audit-olcutler.json", **kw)
    d = docx.Document(str(out))
    blocks, warn = find_blocks(d)
    assert not warn
    return res, d, blocks


def test_template_blocks(tmp_path):
    d = docx.Document(str(make_template(tmp_path / "s.docx")))
    blocks, warn = find_blocks(d)
    assert list(blocks) == ["A.1.1", "A.1.2"] and not warn
    b = blocks["A.1.1"]
    assert len(b.numbers) == 5 and len(b.rubric) == 1
    assert _ptext(b.rubric_cells(3)[0]) == "Sentetik rubrik düzey 3 (A.1.1)"


def test_fill_cells_and_format(ws, tmp_path):
    write_text(ws / "texts", "A.1.1", onceki_yila_gore="Önceki yıla göre sentetik fark.")
    write_audit(ws, {"A.1.1": 3, "A.1.2": 2})
    res, d, blocks = _run(ws, tmp_path)
    a = blocks["A.1.1"]
    assert _lines(a.aciklama_tc) == ["Açıklamalar:", "A.1.1 sentetik paragraf bir [1_OD3].",
                                     "A.1.1 sentetik paragraf iki [2_OD2].",
                                     "Önceki yıla göre sentetik fark."]
    assert _lines(a.kanit_tc) == ["Kanıtlar:", "1_OD3: Sentetik kanıt bir", "2_OD2: Sentetik kanıt iki"]
    # biçim: 10 pt, Times New Roman, kalın değil, önce 0 / sonra 6 pt (120 twip)
    for tc in (a.aciklama_tc, a.kanit_tc):
        for p in list(tc.iter(W + "p"))[1:]:
            sp = p.find(W + "pPr/" + qn("w:spacing"))
            assert (sp.get(qn("w:before")), sp.get(qn("w:after"))) == ("0", "120")
            for r in p.iter(W + "r"):
                rpr = r.find(W + "rPr")
                assert rpr.find(qn("w:sz")).get(qn("w:val")) == "20"
                assert rpr.find(qn("w:rFonts")).get(qn("w:ascii")) == "Times New Roman"
                assert rpr.find(qn("w:b")).get(qn("w:val")) == "0"
    # python-docx ile de aynı değerler
    cell_par = d.tables[0].rows[5].cells[0].paragraphs[1]
    assert cell_par.runs[0].font.size.pt == 10
    assert cell_par.paragraph_format.space_before.pt == 0
    assert cell_par.paragraph_format.space_after.pt == pytest.approx(6.0)
    # metni olmayan ölçüt boş kalmaz: nötr ifade + audit eksik notu
    b = blocks["A.1.2"]
    assert _lines(b.aciklama_tc) == ["Açıklamalar:", BOS_IFADE,
                                     "Eksik kanıt notu: A.1.2 için uygulama kanıtı."]
    assert _lines(b.kanit_tc) == ["Kanıtlar:", BOS_KANIT]
    body = d.element.body.xml
    assert PLACEHOLDER_A not in body and PLACEHOLDER_K not in body
    assert res.dolu == ["A.1.1"] and res.bos == ["A.1.2"] and not res.taslak
    assert TASLAK_METNI not in "".join(p.text for s in d.sections for p in s.header.paragraphs)


def test_od_mark_modes(ws, tmp_path):
    write_text(ws / "texts", "A.1.1", od_onerisi=3)
    write_audit(ws, {"A.1.1": 4, "A.1.2": 2})
    res, d, blocks = _run(ws, tmp_path)
    assert _bold_cols(blocks["A.1.1"]) == [3] and _bold_cols(blocks["A.1.2"]) == [2]
    assert res.od == {"A.1.1": 3, "A.1.2": 2}
    # rubrik metni değişmez
    assert _ptext(blocks["A.1.1"].rubric_cells(3)[0]) == "Sentetik rubrik düzey 3 (A.1.1)"

    res, d, blocks = _run(ws, tmp_path, opts=Options(puan_isareti="golge"))
    b = blocks["A.1.1"]
    fills = [tc.find(W + "tcPr/" + qn("w:shd")) for tc in b.rubric[0]]
    assert [f.get(qn("w:fill")) if f is not None else None for f in fills] == [None, None, GOLGE, None, None]
    assert b.numbers[2].find(W + "tcPr/" + qn("w:shd")).get(qn("w:fill")) == GOLGE
    assert _bold_cols(b) == []

    res, d, blocks = _run(ws, tmp_path, opts=Options(puan_isareti="yok"))
    assert _bold_cols(blocks["A.1.1"]) == [] and res.od == {}


def test_od_capped_by_audit(ws, tmp_path):
    write_text(ws / "texts", "A.1.1", od_onerisi=4)
    write_audit(ws, {"A.1.1": 3})
    res, _, blocks = _run(ws, tmp_path)
    assert res.od["A.1.1"] == 3 and _bold_cols(blocks["A.1.1"]) == [3]
    assert any("aşıyor" in u for u in res.uyarilar)


def test_draft_mark_and_unverified(ws, tmp_path):
    write_text(ws / "texts", "A.1.1", durum="taslak")
    write_text(ws / "texts", "A.1.2", durum="reddedildi")
    write_audit(ws, {"A.1.1": 3, "A.1.2": 2})
    res, d, blocks = _run(ws, tmp_path)
    assert res.taslak and res.dogrulanmamis == ["A.1.1"] and res.reddedildi == ["A.1.2"]
    a = _lines(blocks["A.1.1"].aciklama_tc)
    assert a[1].startswith(DOGRULANMADI) and a[2] == "A.1.1 sentetik paragraf bir [1_OD3]."
    r = _lines(blocks["A.1.2"].aciklama_tc)
    assert r[1].startswith(DOGRULANMADI) and BOS_IFADE in r and "sentetik paragraf" not in " ".join(r)
    sec = d.sections[0]
    hdr = [p.text for p in sec.header.paragraphs]
    assert hdr[0] == "ŞABLON ÜSTBİLGİSİ" and TASLAK_METNI in hdr      # mevcut üstbilgi korunur
    assert TASLAK_METNI in [p.text for p in sec.first_page_header.paragraphs]  # ilk sayfa
    p = [p for p in sec.header.paragraphs if p.text == TASLAK_METNI][0]
    assert p.style.name == "Header"


def test_cover_and_kilavuz_format(ws, tmp_path):
    write_text(ws / "texts", "A.1.1")
    res, d, blocks = _run(ws, tmp_path, birim="Sentetik Bölüm", yil=2026,
                          opts=Options(kanit_bicimi="kilavuz"))
    texts = [p.text for p in d.paragraphs]
    assert "Sentetik Bölüm" in texts and "2026" in texts and "2025" not in texts
    assert not any("[Birim Adı]" in t for t in texts)
    assert "Yazım kuralları örneği 2547 sayılı kanun" in texts
    assert _lines(blocks["A.1.1"].kanit_tc)[1:] == ["[1-OD3]. Sentetik kanıt bir", "[2-OD2]. Sentetik kanıt iki"]
    assert res.kapak == {"birim": "Sentetik Bölüm", "yil": "2026"}


def test_rest_of_template_untouched(ws, tmp_path):
    tpl = tmp_path / "sablon.docx"
    sha = sha256_file(tpl)
    write_text(ws / "texts", "A.1.1")
    write_audit(ws, {"A.1.1": 3, "A.1.2": 2})
    res, d, blocks = _run(ws, tmp_path)
    assert sha256_file(tpl) == sha                                   # şablon salt okunur
    t = docx.Document(str(tpl))
    tb, _ = find_blocks(t)
    skip = {id(c) for b in blocks.values() for c in [b.aciklama_tc, b.kanit_tc]
            + [x for row in b.rubric for x in row]}
    et, eo = list(t.element.body.iterchildren()), list(d.element.body.iterchildren())
    assert len(et) == len(eo)
    for a, b in zip(et, eo):
        if a.tag == W + "tbl":
            for ca, cb in zip(a.iter(W + "tc"), b.iter(W + "tc")):
                if id(cb) not in skip:
                    assert etree.tostring(ca) == etree.tostring(cb)
        else:
            assert etree.tostring(a) == etree.tostring(b)
    # dokunulmayan parçalar bayt düzeyinde aynı
    import zipfile
    zt, zo = zipfile.ZipFile(tpl), zipfile.ZipFile(ws / "report.docx")
    for n in zt.namelist():
        if n not in res.degisen_parcalar:
            assert zt.read(n) == zo.read(n), n
    assert "word/styles.xml" not in res.degisen_parcalar


def test_refuses_overwrite_and_warns_citation(ws, tmp_path):
    with pytest.raises(ValueError):
        render(tmp_path / "sablon.docx", tmp_path / "sablon.docx", texts_dir=ws / "texts", audit_path=None)
    write_text(ws / "texts", "A.1.1",
               paragraflar=[{"metin": "Atıf listede yok [9_OD3].", "atiflar": ["9_OD3"]}])
    write_text(ws / "texts", "B.9.9")
    res, _, _ = _run(ws, tmp_path)
    assert any("[9_OD3]" in u for u in res.uyarilar)
    assert any(u.startswith("B.9.9") for u in res.uyarilar)


def test_cli(ws, tmp_path, capsys):
    write_text(ws / "texts", "A.1.1", durum="taslak")
    rc = main(["render", "-w", str(ws), "--sablon", str(tmp_path / "sablon.docx"),
               "--birim", "Sentetik Bölüm", "--yil", "2026", "--puan-isareti", "golge"])
    assert rc == 0 and (ws / "report.docx").exists()
    out = capsys.readouterr().out
    assert "TASLAK" in out and "report:" in out
    rc = main(["render", "-w", str(ws), "--sablon", str(tmp_path / "yok.docx")])
    assert rc == 2
