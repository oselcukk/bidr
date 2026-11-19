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


FORM = "Form No:FR-0000 Yayın Tarihi:01.01.2000 Değ.No:0 Değ.Tarihi:-"
PH = "…………………….[Üye Unvan, Adı Soyadı, eposta adresi, Görevi]"
YONERGE_G = "Biriminizin bu ana ölçüt ve alt ölçütleri açışından güçlü yönlerini değerlendiriniz."
YONERGE_A = "Biriminizin bu ana ölçüt ve alt ölçütleri açışından gelişmeye açık yönlerini değerlendiriniz."
ALAN_BASLIK = (("A", "LİDELİK, YÖNETİŞİM VE KALİTE"), ("B", "EĞİTİM VE ÖĞRETİM"), ("C", "ARAŞTIRMA VE GELİŞTİRME"),
               ("D", "TOPLUMSAL KATKI"))


def _footer(sec) -> None:
    """Sentetik altbilgi: form kimliği + PAGE alanı (sayfa numarası)."""
    from docx.oxml import OxmlElement
    for f in (sec.footer, sec.first_page_footer):
        f.is_linked_to_previous = False
        f.paragraphs[0].text = FORM
        p = f.add_paragraph()
        fld = OxmlElement("w:fldSimple")
        fld.set(qn("w:instr"), " PAGE   \\* MERGEFORMAT ")
        r = OxmlElement("w:r")
        t = OxmlElement("w:t")
        t.text = "1"
        r.append(t)
        fld.append(r)
        p._p.append(fld)


def _yonler_table(d) -> None:
    t = d.add_table(rows=0, cols=2)
    t.style = "Table Grid"
    for _, head in ALAN_BASLIK:
        r = t.add_row()
        c = r.cells[0].merge(r.cells[1])
        c.paragraphs[0].text = head
        r = t.add_row()
        r.cells[0].text, r.cells[1].text = "Güçlü Yönler", "Gelişmeye Açık Yönler"
        r = t.add_row()
        for cell, txt in zip(r.cells, (YONERGE_G, YONERGE_A)):
            cell.paragraphs[0].text = ""
            cell.add_paragraph(txt)
            cell.add_paragraph("")


def make_template(path: Path, ids=(("A.1.1", "Yönetişim modeli"), ("A.1.2", "Liderlik")), full: bool = False) -> Path:
    """`full`: kapakta "Raporu Hazırlayanlar" yer tutucuları, altbilgide form kimliği ve sayfa
    numarası alanı, sonda Güçlü / Gelişmeye Açık Yönler tablosu (FR-0833 düzeni, sentetik)."""
    d = docx.Document()
    sec = d.sections[0]
    sec.header.paragraphs[0].text = "ŞABLON ÜSTBİLGİSİ"
    sec.different_first_page_header_footer = True
    d.add_paragraph("BİRİM İÇ DEĞERLENDİRME RAPORU")
    d.add_paragraph("…………………….[Birim Adı]")
    if full:
        _footer(sec)
        d.add_paragraph("")
        d.add_paragraph("Raporu Hazırlayanlar")
        for _ in range(3):
            d.add_paragraph(PH)
        for _ in range(3):
            d.add_paragraph("")
    d.add_paragraph("2025")
    d.add_paragraph("Yazım kuralları örneği 2547 sayılı kanun")
    d.add_paragraph("ÖLÇÜTLER VE KANITLAR")
    for sid, title in ids:
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
    if full:
        _yonler_table(d)
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
    # biçim: 10 pt, Times New Roman, kalın değil, önce 0 / sonra 0,6 nk (12 twip)
    for tc in (a.aciklama_tc, a.kanit_tc):
        for p in list(tc.iter(W + "p"))[1:]:
            sp = p.find(W + "pPr/" + qn("w:spacing"))
            assert (sp.get(qn("w:before")), sp.get(qn("w:after"))) == ("0", "12")
            for r in p.iter(W + "r"):
                rpr = r.find(W + "rPr")
                assert rpr.find(qn("w:sz")).get(qn("w:val")) == "20"
                assert rpr.find(qn("w:rFonts")).get(qn("w:ascii")) == "Times New Roman"
                assert rpr.find(qn("w:b")).get(qn("w:val")) == "0"
    # python-docx ile de aynı değerler
    cell_par = d.tables[0].rows[5].cells[0].paragraphs[1]
    assert cell_par.runs[0].font.size.pt == 10
    assert cell_par.paragraph_format.space_before.pt == 0
    assert cell_par.paragraph_format.space_after.pt == pytest.approx(0.6)
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


def test_od_approved_level_wins_and_check_warns(ws, tmp_path, capsys):
    """İşaretlenen düzey: önce komisyonun onayladığı `od_onayli`, yoksa kodun `od`'si. Onaysız
    işaretlenen OD denetle'de `od_onay_bekliyor` uyarısı (kritik değil)."""
    from bidr.check.run import UYARI, denetle, od_onay_bekleyenler
    write_text(ws / "texts", "A.1.1", od_onerisi=3)
    p = write_audit(ws, {"A.1.1": 4, "A.1.2": 3})
    js = json.loads(p.read_text(encoding="utf-8"))
    js["olcutler"][0].update(od_kod_onerisi=4, od_onayli=2)          # komisyon OD2 dedi
    js["olcutler"][1].update(od_kod_onerisi=3, od_onayli=None)
    p.write_text(json.dumps(js, ensure_ascii=False), encoding="utf-8")
    res, _, blocks = _run(ws, tmp_path)
    assert res.od == {"A.1.1": 2, "A.1.2": 3}
    assert _bold_cols(blocks["A.1.1"]) == [2] and _bold_cols(blocks["A.1.2"]) == [3]
    assert res.od_kaynagi == {"A.1.1": "onayli", "A.1.2": "kod"}
    assert res.od_onay_bekliyor == {"A.1.2": {"od": 3, "kaynak": "kod"}}
    assert res.ozet()["od_onay_bekliyor"] == {"A.1.2": {"od": 3, "kaynak": "kod"}}
    assert any("komisyonun onayladığı" in u for u in res.uyarilar)  # metin OD3, onay OD2
    # onaylı düzey metnin önerisinden yüksekse de onaylı işaretlenir (insan kararı)
    js["olcutler"][0]["od_onayli"] = 5
    p.write_text(json.dumps(js, ensure_ascii=False), encoding="utf-8")
    res, _, blocks = _run(ws, tmp_path)
    assert res.od["A.1.1"] == 5 and _bold_cols(blocks["A.1.1"]) == [5]
    # denetle: CLI render kaydını (çıktı özeti tutuyorsa) okur, yoksa audit-olcutler.json'u
    assert main(["render", "-w", str(ws), "--sablon", str(tmp_path / "sablon.docx")]) == 0
    bek, kaynak = od_onay_bekleyenler(ws, ws / "report.docx")
    assert kaynak == "render kaydı" and bek == {"A.1.2": {"od": 3, "kaynak": "kod"}}
    s = denetle(ws / "report.docx", od_bekleyen=bek)
    b = [x for x in s.bulgular if x.kod == "od_onay_bekliyor"]
    assert [(x.seviye, x.yer) for x in b] == [(UYARI, "A.1.2")] and "OD insan onayı bekliyor" in b[0].mesaj
    assert main(["render", "-w", str(ws), "--sablon", str(tmp_path / "sablon.docx"), "--puan-isareti", "yok"]) == 0
    assert od_onay_bekleyenler(ws, ws / "report.docx")[0] == {}      # hiçbir düzey işaretlenmedi
    (ws / ".bidr-render.json").unlink()                                # kayıt yok: audit'ten
    bek, kaynak = od_onay_bekleyenler(ws, ws / "report.docx")
    assert kaynak == "audit-olcutler.json" and bek == {"A.1.2": {"od": 3, "kaynak": "kod"}}
    capsys.readouterr()
    main(["denetle", "-w", str(ws)])
    dj = json.loads((ws / "denetim.json").read_text(encoding="utf-8"))
    assert dj["ozet"]["kodlar"]["od_onay_bekliyor"] == {"seviye": UYARI, "sayi": 1}
    assert dj["bilgi"]["od_onay_bekliyor"] == ["A.1.2"]


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


# -- K24/K16: sorumlu birim kapsamı ---------------------------------------------------------------

def test_scope_states(ws, tmp_path):
    from bidr.render.run import KAPSAM_DISI, KAPSAM_KARARI
    make_template(tmp_path / "sablon.docx", ids=(("A.1.1", "Bir"), ("A.1.2", "İki"), ("A.1.3", "Üç"),
                                                  ("A.1.4", "Dört")))
    write_audit(ws, {"A.1.1": 1, "A.1.2": 1, "A.1.3": 1, "A.1.4": 1})
    kapsam = {"A.1.1": "bolum", "A.1.2": "ortak", "A.1.3": "baska_birim", "A.1.4": "karar_gerekli"}
    res, d, blocks = _run(ws, tmp_path, kapsam=kapsam)
    # kanıt yokluğu yalnız bolum/ortak ölçütlerde
    for c in ("A.1.1", "A.1.2"):
        assert BOS_IFADE in _lines(blocks[c].aciklama_tc) and _lines(blocks[c].kanit_tc) == ["Kanıtlar:", BOS_KANIT]
    assert _lines(blocks["A.1.3"].aciklama_tc) == ["Açıklamalar:", KAPSAM_DISI]
    assert _lines(blocks["A.1.3"].kanit_tc) == ["Kanıtlar:"]
    assert _lines(blocks["A.1.4"].aciklama_tc) == ["Açıklamalar:", KAPSAM_KARARI]
    assert _lines(blocks["A.1.4"].kanit_tc) == ["Kanıtlar:"]
    assert _bold_cols(blocks["A.1.3"]) == [] and _bold_cols(blocks["A.1.4"]) == []   # OD işaretlenmez
    assert _bold_cols(blocks["A.1.1"]) == [1]
    assert res.kapsam_disi == ["A.1.3"] and res.karar_gerekli == ["A.1.4"]
    assert res.taslak and any("kapsam kararı" in n for n in res.taslak_nedenleri)
    # kapsam dışı ölçütün metni rapora girmez, taslak da saymaz
    write_text(ws / "texts", "A.1.3", durum="taslak")
    res, d, blocks = _run(ws, tmp_path, kapsam={**kapsam, "A.1.4": "bolum"}, opts=Options(kapsam_disi=""))
    assert _lines(blocks["A.1.3"].aciklama_tc) == ["Açıklamalar:"]
    assert any("A.1.3: kapsam baska_birim" in u for u in res.uyarilar) and not res.taslak


def test_scope_from_profile_and_config(tmp_path, monkeypatch):
    from bidr.render.kapsam import profile_scope, workspace_scope
    k, uy = profile_scope("akademik_bolum")
    assert k["A.1.1"] == "bolum" and k["A.3.1"] == "baska_birim" and k["A.3.3"] == "baska_birim" and k["C.1.3"] == "baska_birim" and not uy
    assert profile_scope(None)[0]["A.3.1"] == "bolum"                      # profil yoksa eski davranış
    prof = tmp_path / "profiller"
    prof.mkdir()
    (prof / "deneme.yaml").write_text(
        "ad: deneme\ndahil: [TÜM AKADEMİK BİRİMLER]\nkapsam:\n  A.3.3: ortak\n  A.1.1: yanlis\n", encoding="utf-8")
    monkeypatch.setenv("BIDR_PROFILES_DIR", str(prof))
    k, uy = profile_scope("deneme")
    assert k["A.3.3"] == "ortak" and k["A.1.1"] == "bolum" and any("yanlis" in u for u in uy)
    from bidr.criteria.profiles import load_profile
    assert load_profile("deneme").decide("A.1.1", "TÜM AKADEMİK BİRİMLER").verdict == "dahil"   # geri uyumlu
    ws = tmp_path / "w"
    ws.mkdir()
    (ws / "config.yaml").write_text("rapor:\n  kapsam:\n    A.3.1: ortak\n    Z.9.9: bolum\n", encoding="utf-8")
    k, uy = workspace_scope(ws)
    assert k["A.3.1"] == "ortak" and any("Z.9.9" in u for u in uy)


# -- K30: Güçlü / Gelişmeye Açık Yönler -------------------------------------------------------------

def _yon(d: Path, alan: str, durum: str = "dogrulandi", guclu=None, gelisme=None) -> None:
    d.mkdir(parents=True, exist_ok=True)
    g = guclu if guclu is not None else [f"Bölümümüzde sentetik uygulama yürütülmektedir ({alan}.1.1)."]
    a = gelisme if gelisme is not None else [f"Sentetik izleme kanıtı bulunmamaktadır ({alan}.1.2)."]
    (d / f"{alan}.json").write_text(json.dumps({
        "alan": alan, "durum": durum, "guclu": [{"metin": x} for x in g], "gelisme": [{"metin": x} for x in a]},
        ensure_ascii=False), encoding="utf-8")


def _yon_cells(doc) -> dict[str, list[str]]:
    from bidr.render.template import find_yonler
    cells, warn = find_yonler(doc)
    assert not warn
    return {f"{a} {k}": [t for t in _lines(tc) if t] for a, c in cells.items()
            for k, tc in (("g", c.guclu_tc), ("a", c.gelisme_tc))}


PEOPLE = [{"unvan": "Dr. Öğr. Üyesi", "ad_soyad": "Örnek Kişi", "eposta": "ornek@example.edu",
           "gorev": "Komisyon Başkanı"},
          {"unvan": "Arş. Gör.", "ad_soyad": "Deneme Ad", "eposta": "deneme@example.edu", "gorev": "Üye"}]


def test_strengths_cells(ws, tmp_path):
    make_template(tmp_path / "sablon.docx", full=True)
    write_text(ws / "texts", "A.1.1")
    yd = ws / "yonler"
    for a in "ABCD":
        _yon(yd, a)
    res, d, _ = _run(ws, tmp_path, yonler_dir=yd, hazirlayanlar=PEOPLE)
    cells = _yon_cells(d)
    assert cells["A g"] == ["• Bölümümüzde sentetik uygulama yürütülmektedir (A.1.1)."]
    assert cells["D a"] == ["• Sentetik izleme kanıtı bulunmamaktadır (D.1.2)."]
    assert YONERGE_G not in d.element.body.xml and not res.taslak, res.taslak_nedenleri
    assert set(res.yonler.values()) == {"dolu"} and len(res.yonler) == 8
    # boş liste, doğrulanmamış, reddedilmiş ve eksik alan → hücre yönergeyle kalır / işaretli; TASLAK
    _yon(yd, "A", guclu=[])
    _yon(yd, "B", durum="taslak")
    _yon(yd, "C", durum="reddedildi")
    (yd / "D.json").unlink()
    res, d, _ = _run(ws, tmp_path, yonler_dir=yd, hazirlayanlar=PEOPLE)
    cells = _yon_cells(d)
    assert cells["A g"] == [YONERGE_G] and cells["A a"][0].startswith("• ")
    assert cells["B g"][0].startswith(DOGRULANMADI)
    assert cells["C g"] == [YONERGE_G] and cells["D a"] == [YONERGE_A]
    assert res.taslak
    why = " | ".join(res.taslak_nedenleri)
    assert "A Güçlü Yönler" in why and "C Gelişmeye Açık Yönler" in why and "D Güçlü Yönler" in why
    assert "doğrulanmamış güçlü/gelişmeye açık yön maddeleri: B" in why
    sec = d.sections[0]
    assert TASLAK_METNI in [p.text for p in sec.header.paragraphs]


# -- K32: kapak, hazırlayanlar; altbilgi bozulmaz ---------------------------------------------------

def _cover(doc) -> list[str]:
    from bidr.render.run import cover_paragraphs
    return [_ptext(p) for p in cover_paragraphs(doc)]


def test_cover_preparers_and_footer_intact(ws, tmp_path):
    import zipfile
    tpl = make_template(tmp_path / "sablon.docx", full=True)
    yd = ws / "yonler"
    for a in "ABCD":
        _yon(yd, a)
    write_text(ws / "texts", "A.1.1")
    n0 = len(_cover(docx.Document(str(tpl))))
    # iki kişi: üç yer tutucudan biri boş paragraf olur; kapak paragraf sayısı değişmez
    res, d, _ = _run(ws, tmp_path, yonler_dir=yd, hazirlayanlar=PEOPLE, birim="Sentetik Bölüm", yil=2026)
    cov = _cover(d)
    assert len(cov) == n0 and not res.taslak and res.hazirlayan == 2
    i = cov.index("Raporu Hazırlayanlar")
    assert cov[i + 1:i + 4] == ["Dr. Öğr. Üyesi Örnek Kişi, ornek@example.edu, Komisyon Başkanı",
                                "Arş. Gör. Deneme Ad, deneme@example.edu, Üye", ""]
    assert "Sentetik Bölüm" in cov and "2026" in cov
    # altbilgi (form no, yayın/değişiklik bilgisi, sayfa numarası alanı) ve bölüm özellikleri aynı
    zt, zo = zipfile.ZipFile(tpl), zipfile.ZipFile(ws / "report.docx")
    footers = [n for n in zt.namelist() if n.startswith("word/footer")]
    assert footers and not set(footers) & set(res.degisen_parcalar)
    for n in footers:
        assert zt.read(n) == zo.read(n)
    assert any(b"PAGE" in zo.read(n) for n in footers) and any(FORM.encode() in zo.read(n) for n in footers)
    t_sect = docx.Document(str(tpl)).element.body.find(W + "sectPr")
    assert etree.tostring(d.element.body.find(W + "sectPr")) == etree.tostring(t_sect)
    assert d.sections[0].footer.paragraphs[0].text == FORM
    # beş kişi: iki satır eklenir, ardındaki boş paragraflardan ikisi düşer (kapak taşmaz)
    five = [{**PEOPLE[0], "ad_soyad": f"Örnek Kişi {k}"} for k in range(5)]
    res, d, _ = _run(ws, tmp_path, yonler_dir=yd, hazirlayanlar=five)
    cov = _cover(d)
    assert len(cov) == n0 and sum("Örnek Kişi" in x for x in cov) == 5 and res.hazirlayan == 5
    # liste boş: yer tutucular kalır, TASLAK
    res, d, _ = _run(ws, tmp_path, yonler_dir=yd, hazirlayanlar=[])
    assert sum("[Üye Unvan" in x for x in _cover(d)) == 3 and res.taslak
    assert any("Raporu Hazırlayanlar" in n for n in res.taslak_nedenleri)
    assert any("hazirlayanlar boş" in u for u in res.uyarilar)


def test_cli_workspace_inputs(ws, tmp_path, capsys):
    """CLI: hazırlayanlar ve kapsam config.yaml'dan; kapsam sorusu gaps.md'de; girdiler değişince rapor eskir."""
    import yaml as Y
    from bidr.render.run import KAPSAM_BEGIN, load_manifest, workspace_sha
    make_template(tmp_path / "sablon.docx", full=True)
    write_audit(ws, {"A.1.1": 2, "A.1.2": 2})
    (ws / "gaps.md").write_text("# Eksik kanıt raporu\n", encoding="utf-8")
    cfg = {"rapor": {"sablon": str(tmp_path / "sablon.docx"), "hazirlayanlar": PEOPLE[:1],
                     "kapsam": {"A.1.2": "karar_gerekli"}}}
    (ws / "config.yaml").write_text(Y.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    assert main(["render", "-w", str(ws)]) == 0
    out = capsys.readouterr().out
    assert "kapsam kararı gerekli" in out and "TASLAK" in out
    gaps = (ws / "gaps.md").read_text(encoding="utf-8")
    assert gaps.startswith("# Eksik kanıt raporu") and KAPSAM_BEGIN in gaps and "**A.1.2**" in gaps
    d = docx.Document(str(ws / "report.docx"))
    assert "Dr. Öğr. Üyesi Örnek Kişi, ornek@example.edu, Komisyon Başkanı" in _cover(d)
    m = load_manifest(ws)
    tpl = tmp_path / "sablon.docx"
    sha = lambda: workspace_sha(ws, tpl, ws / "texts", ws / "audit-olcutler.json", ws / "evidence-index.csv")  # noqa: E731
    assert m["girdi_sha"] == sha() and m["karar_gerekli"] == ["A.1.2"]
    cfg["rapor"]["kapsam"] = {"A.1.2": "baska_birim"}           # kullanıcının kararı
    (ws / "config.yaml").write_text(Y.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    assert m["girdi_sha"] != sha()                              # rapor eskidi
    assert main(["render", "-w", str(ws)]) == 0
    assert KAPSAM_BEGIN not in (ws / "gaps.md").read_text(encoding="utf-8")
    cfg["rapor"]["hazirlayanlar"] = [{"ad_soyad": "Örnek Kişi", "eposta": "bozuk"}]
    (ws / "config.yaml").write_text(Y.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    capsys.readouterr()
    assert main(["render", "-w", str(ws)]) == 0
    assert "e-posta biçimi geçersiz" in capsys.readouterr().out


def test_uncited_filed_evidence_keeps_numbering(ws, tmp_path):
    """Metinde atıf almayan ama kanıt klasörüne konmuş kanıt listede kalır: numara boşluğu ve
    `listede_olmayan_dosya` oluşmaz (kör test: B.1.1 listesi 1, 2, 4 diye atlıyordu)."""
    write_text(ws / "texts", "A.1.1",
               paragraflar=[{"metin": "A.1.1 sentetik paragraf [1_OD3] [3_OD2].", "atiflar": ["1_OD3", "3_OD2"]}],
               kanitlar=[{"no": "1_OD3", "ad": "Sentetik kanıt bir", "dosya": "a.pdf"},
                         {"no": "3_OD2", "ad": "Sentetik kanıt üç", "dosya": "c.pdf"}])
    idx = ws / "evidence-index.csv"
    idx.write_text("kanit_no,olcut,od,ad,dosya,baglanti\n"
                   "1_OD3,A.1.1,3,Sentetik kanıt bir,a.pdf,\n"
                   "2_OD2,A.1.1,2,Sentetik kanıt iki,b.pdf,\n"
                   "3_OD2,A.1.1,2,Sentetik kanıt üç,c.pdf,\n", encoding="utf-8")
    res, d, blocks = _run(ws, tmp_path, index_path=idx)
    assert _lines(blocks["A.1.1"].kanit_tc) == ["Kanıtlar:", "1_OD3: Sentetik kanıt bir",
                                                "2_OD2: Sentetik kanıt iki", "3_OD2: Sentetik kanıt üç"]
    assert res.atifsiz_listelenen == {"A.1.1": ["2_OD2"]}
    # denetle: numaralar sıralı, klasördeki her dosya listede; atıfsız kanıt yalnız uyarı olarak görünür
    from bidr.check.run import denetle
    ev = ws / "evidence" / "A" / "A.1" / "A.1.1"
    ev.mkdir(parents=True)
    for n, od, ad in ((1, 3, "bir"), (2, 2, "iki"), (3, 2, "üç")):
        (ev / f"[{n}-OD{od}]. Sentetik kanıt {ad}.pdf").write_bytes(b"%PDF-1.4 sentetik")
    s = denetle(ws / "report.docx", kanit_klasoru=ws / "evidence", index_path=idx,
                beklenen=(["A.1.1", "A.1.2"], ["A.1"]))
    kod = {b.kod for b in s.bulgular if b.yer == "A.1.1"}
    assert not kod & {"kanit_numarasi", "listede_olmayan_dosya", "kanit_dosyasi_yok", "dizinle_uyusmuyor"}
    assert "atifsiz_kanit" in kod
