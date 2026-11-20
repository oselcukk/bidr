"""Görüntü katmanı maskeleme: OCR (taranmış PDF, görsel), imza bölgesi, taranamadı durumu,
docx/html genişletmeleri. Yalnız sentetik veri (algoritmayla üretilen TC, çizilmiş imza)."""
from __future__ import annotations

import json
import math
import zipfile
from pathlib import Path

import pytest

from bidr.mask import MaskRules
from bidr.mask import formats as F
from bidr.mask import imza as IM
from bidr.mask import ocr as O
from bidr.mask import raster as RA
from bidr.mask import run as R

from test_mask import EMAIL, OGR, PHONE, TC1, TC2

PIL = pytest.importorskip("PIL")
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

needs_ocr = pytest.mark.skipif(not O.ocr_available(), reason="tesseract + tur/eng yok")


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:                       # eski Pillow: ölçeklenemeyen yazı tipi
        pytest.skip("Pillow ölçeklenebilir varsayılan yazı tipi yok")


def _signature(d: ImageDraw.ImageDraw, x: int, y: int, w: int = 260, h: int = 70, color=(20, 40, 190)):
    """Sentetik imza: döngülü serbest çizgi."""
    pts = []
    for i in range(160):
        t = i / 159
        pts.append((x + t * w + 18 * math.sin(t * 25), y + h / 2 + h / 2 * math.sin(t * 9) * math.cos(t * 3)))
    d.line(pts, fill=color, width=4, joint="curve")
    d.line([(x + 20, y + h - 5), (x + w - 30, y + 8)], fill=color, width=3)


def make_page(*, pii: bool = True, labeled_sig: bool = False, unlabeled_sig: bool = False):
    """A4 ~150 ppi sayfa görüntüsü."""
    img = Image.new("RGB", (1240, 1754), "white")
    d = ImageDraw.Draw(img)
    f = _font(34)
    y = 120
    for line in ("Bolum Kurulu Karari", "Toplanti gundemi ve alinan kararlar asagidadir.",
                 "Karar metni oy birligi ile kabul edilmistir."):
        d.text((120, y), line, fill="black", font=f)
        y += 70
    if pii:
        for line in (f"T.C. Kimlik No: {TC1}", f"Telefon: {PHONE}", f"E-posta: {EMAIL}", f"Ogrenci no: {OGR}"):
            d.text((120, y), line, fill="black", font=f)
            y += 70
    if labeled_sig:
        d.text((120, 1150), "İmza:", fill="black", font=f)
        _signature(d, 260, 1120)
    if unlabeled_sig:
        _signature(d, 800, 1550, color=(10, 10, 10))
    return img


def _ocr_text(img) -> str:
    return " ".join(w.text for w in O.ocr_words(img))


# ---------------------------------------------------------------- OCR eşleme (OCR'sız birim)

def test_pii_hits_from_word_boxes_and_digit_confusion():
    tc_o = TC1.replace("0", "O") if "0" in TC1 else TC1[:3] + "l" + TC1[4:] if TC1[3] == "1" else TC1
    words = [O.Word("Kimlik", 95, 10, 10, 80, 30, (1, 1, 1, 1)), O.Word(tc_o, 70, 90, 10, 300, 30, (1, 1, 1, 1)),
             O.Word("Tel", 95, 10, 50, 40, 70, (1, 1, 2, 1)), O.Word(PHONE[:4], 90, 50, 50, 100, 70, (1, 1, 2, 1)),
             O.Word(PHONE[5:8], 90, 110, 50, 150, 70, (1, 1, 2, 1)),
             O.Word(PHONE[9:11], 90, 160, 50, 190, 70, (1, 1, 2, 1)),
             O.Word(PHONE[12:], 90, 200, 50, 230, 70, (1, 1, 2, 1)),
             O.Word(TC2[:5], 90, 10, 90, 60, 110, (1, 1, 3, 1)), O.Word(TC2[5:], 90, 66, 90, 130, 110, (1, 1, 3, 1))]
    c, boxes = O.find_pii(words, MaskRules())
    assert c["tc_no"] == 2 and c["telefon"] == 1, c
    assert any(b[0] >= 90 and b[2] <= 300 for b in boxes)       # TC kutusu kelime içinde
    assert all(b[0] >= 50 or b[1] != 50 for b in boxes)         # "Tel" kelimesi karartılmaz


# ---------------------------------------------------------------- imza çözümlemesi (OCR'sız)

def _words_for(img_text_lines):
    return [O.Word(t, 96, *box, (1, 1, i, 1)) for i, (t, box) in enumerate(img_text_lines)]


def test_signature_labeled_is_covered_unlabeled_is_flagged():
    img = Image.new("RGB", (1240, 1754), "white")
    d = ImageDraw.Draw(img)
    for i in range(6):                                      # metin yerine düz bloklar + kelime kutuları
        d.rectangle([120, 120 + i * 60, 900, 140 + i * 60], fill=(0, 0, 0))
    _signature(d, 300, 1100)
    words = _words_for([("Metin", (120, 120 + i * 60, 900, 140 + i * 60)) for i in range(6)] +
                       [("İmza:", (120, 1125, 230, 1160))])
    r = IM.analyze(img, words, 150)
    assert r.etiket == 1 and r.etiketli >= 1 and r.kesin, r
    cov = r.kapat
    assert any(b[0] <= 300 and b[2] >= 540 and b[1] <= 1110 and b[3] >= 1160 for b in cov), cov
    assert r.ortusen_kelime == 0
    # aynı imza etiketsiz: kapatılmaz, elle bakılmalı
    r2 = IM.analyze(img, words[:-1], 150)
    assert not r2.kapat and r2.etiketsiz >= 1 and not r2.kesin
    # tablo çizgileri ve dolu blok imza sayılmaz
    t = Image.new("RGB", (1240, 1754), "white")
    d = ImageDraw.Draw(t)
    for k in range(5):
        d.line([(100, 300 + k * 80), (1100, 300 + k * 80)], fill="black", width=3)
        d.line([(100 + k * 250, 300), (100 + k * 250, 620)], fill="black", width=3)
    d.rectangle([500, 900, 800, 1000], fill="black")
    r3 = IM.analyze(t, [], 150)
    assert r3.etiketsiz == 0 and not r3.kapat, r3


# ---------------------------------------------------------------- OCR ile uçtan uca

@needs_ocr
def test_image_file_masked_and_rescanned(tmp_path):
    ws = tmp_path / "ws"
    p = ws / "evidence/A/form.png"
    p.parent.mkdir(parents=True)
    make_page(labeled_sig=True).save(p)
    assert TC1 in _ocr_text(Image.open(p)).replace(" ", "")
    rep = R.run(ws)
    rec = rep["dosyalar"][0]
    assert rec["durum"] == "tamam", rec
    assert rec["maskelenen"].get("tc_no") == 1 and rec["maskelenen"].get("telefon") == 1, rec
    assert rec["imza_bolgesi"] >= 1
    out = Image.open(ws / "evidence-maskeli/A/form.png")
    txt = _ocr_text(out).replace(" ", "")
    for v in (TC1, EMAIL, OGR):
        assert v not in txt
    assert "Karar" in txt                                    # içerik duruyor
    # imza alanı karartıldı (içinde yalnız koyu gri "[İMZA]" etiketi; beyaz kâğıt kalmadı)
    assert out.convert("L").crop((300, 1130, 500, 1170)).getextrema()[1] <= RA.LABEL_GRAY
    assert TC1 not in json.dumps(rep, ensure_ascii=False)


@needs_ocr
def test_upside_down_scan_is_read(tmp_path):
    ws = tmp_path / "ws"
    p = ws / "evidence/A/ters.png"
    p.parent.mkdir(parents=True)
    make_page().rotate(180).save(p)
    rep = R.run(ws)
    rec = rep["dosyalar"][0]
    assert rec["durum"] == "tamam" and rec["maskelenen"].get("tc_no") == 1, rec
    out = Image.open(ws / "evidence-maskeli/A/ters.png").rotate(180)
    assert TC1 not in _ocr_text(out).replace(" ", "")


@needs_ocr
def test_unlabeled_signature_needs_manual_review(tmp_path):
    ws = tmp_path / "ws"
    p = ws / "evidence/A/foto.jpg"
    p.parent.mkdir(parents=True)
    make_page(pii=False, unlabeled_sig=True).save(p, quality=95)
    rep = R.run(ws)
    rec = rep["dosyalar"][0]
    assert rec["durum"] == "basarisiz" and rec["elle_bakilmali"], rec
    assert any("imza: elle bakılmalı" in s for s in rec["kalan_sorunlar"])
    assert (ws / R.FAIL_DIR / "A/foto.jpg").is_file()


def _scanned_pdf(path: Path, img):
    fitz = pytest.importorskip("pymupdf")
    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(page.rect, stream=buf.getvalue())
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    doc.close()


@needs_ocr
def test_scanned_pdf_ocr_redaction(tmp_path):
    fitz = pytest.importorskip("pymupdf")
    ws = tmp_path / "ws"
    _scanned_pdf(ws / "evidence/A/tarama.pdf", make_page(labeled_sig=True))
    rep = R.run(ws, engine="pymupdf")
    rec = rep["dosyalar"][0]
    assert rec["durum"] == "tamam", rec
    assert rec["bulunan"].get("tc_no") == 1 and rec["maskelenen"].get("tc_no") == 1
    assert rec["imza_bolgesi"] >= 1
    doc = fitz.open(str(ws / "evidence-maskeli/A/tarama.pdf"))
    img = RA.render(doc[0], 200)
    txt = _ocr_text(img).replace(" ", "")
    assert TC1 not in txt and EMAIL not in txt and "Karar" in txt
    # görüntü pikselleri de değişti (yalnız üstüne kutu çizilmedi): gömülü görüntüyü ayrıca oku
    xref = doc[0].get_images()[0][0]
    raw = Image.open(__import__("io").BytesIO(doc.extract_image(xref)["image"]))
    assert TC1 not in _ocr_text(raw).replace(" ", "")


def test_scanned_pdf_without_ocr_is_never_ok(tmp_path, monkeypatch):
    pytest.importorskip("pymupdf")
    ws = tmp_path / "ws"
    _scanned_pdf(ws / "evidence/A/tarama.pdf", make_page())
    (ws / "evidence-index.csv").write_text("kanit_no,dosya\n1,A/tarama.pdf\n", encoding="utf-8")
    monkeypatch.setattr(O, "ocr_available", lambda: False)
    monkeypatch.setattr(RA, "ocr_available", lambda: False)
    monkeypatch.setattr(R, "raster_ocr_available", lambda: False)
    rep = R.run(ws, engine="pymupdf")
    rec = rep["dosyalar"][0]
    assert rec["durum"] == "taranamadi" and rec["elle_bakilmali"], rec
    assert rec["taranamadi"] and "elle bakılmalı" in rec["neden"]
    assert not (ws / "evidence-maskeli/A/tarama.pdf").exists()
    assert (ws / R.FAIL_DIR / "A/tarama.pdf").is_file()
    assert rep["yayimlanamaz"][0]["dosya"] == "A/tarama.pdf"
    assert rep["ozet"]["taranamadi"] == 1
    assert "taranamadi" in (ws / R.INDEX_OUT).read_text(encoding="utf-8")


def test_blank_page_is_not_taranamadi():
    img = Image.new("RGB", (1240, 1754), "white")
    assert RA._quality_reason(img, []) is None
    d = ImageDraw.Draw(img)
    for i in range(40):
        d.line([(100, 100 + i * 30), (1100, 130 + i * 30)], fill="black", width=6)
    assert RA._quality_reason(img, []) is not None           # mürekkep var, kelime yok


# ---------------------------------------------------------------- docx

def test_docx_tables_headers_split_runs_and_structural_ids(tmp_path):
    import docx
    d = docx.Document()
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text = "Öğrenci"
    c = t.cell(0, 1).paragraphs[0]
    c.add_run(OGR[:4])
    c.add_run(OGR[4:7]).bold = True
    c.add_run(OGR[7:])
    inner = t.cell(1, 1).add_table(rows=1, cols=1)           # iç içe tablo
    inner.cell(0, 0).text = f"Kimlik {TC1}"
    sec = d.sections[0]
    sec.header.paragraphs[0].add_run(f"Tel {PHONE[:6]}")
    sec.header.paragraphs[0].add_run(PHONE[6:])
    sec.footer.paragraphs[0].text = f"İletişim {EMAIL}"
    sec.different_first_page_header_footer = True
    sec.first_page_footer.paragraphs[0].text = f"Kimlik {TC2}"
    src = tmp_path / "ws/evidence/A/form.docx"
    src.parent.mkdir(parents=True)
    d.save(str(src))
    # Word'ün kendiliğinden verdiği nesne kimliği ve "Resim N" adı (öğrenci no desenine benzer)
    with zipfile.ZipFile(src) as z:
        items = {n: z.read(n) for n in z.namelist()}
    items["word/webSettings.xml"] = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        b'<w:webSettings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        b'<w:divs><w:div w:id="2021999123"><w:bodyDiv w:val="1"/></w:div></w:divs></w:webSettings>')
    with zipfile.ZipFile(src, "w") as z:
        for n, b in items.items():
            z.writestr(n, b)
    rules = MaskRules()
    assert F.scan_file(src, rules)["bulgular"] == {"ogrenci_no": 1, "tc_no": 2, "telefon": 1, "eposta": 1}
    rep = R.run(tmp_path / "ws")
    rec = rep["dosyalar"][0]
    assert rec["durum"] == "tamam", rec
    blob = b"".join(zipfile.ZipFile(tmp_path / "ws/evidence-maskeli/A/form.docx").read(n)
                    for n in zipfile.ZipFile(tmp_path / "ws/evidence-maskeli/A/form.docx").namelist())
    for v in (OGR, TC1, TC2, EMAIL, "000 11 22"):
        assert v.encode() not in blob, v
    assert b'w:id="2021999123"' in blob                      # yapısal kimlik bozulmadı


def test_docx_attribute_text_is_masked(tmp_path):
    import docx
    d = docx.Document()
    p = d.add_paragraph("Alan: ")
    fld = p._p.makeelement("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}fldSimple")
    fld.set("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}instr",
            f'HYPERLINK "mailto:{EMAIL}"')
    p._p.append(fld)
    src = tmp_path / "a.docx"
    d.save(str(src))
    assert F.scan_file(src, MaskRules())["bulgular"]["eposta"] == 1
    F.mask_file(src, tmp_path / "b.docx", MaskRules())
    assert not F.scan_file(tmp_path / "b.docx", MaskRules())["bulgular"]


# ---------------------------------------------------------------- html

def test_html_masked(tmp_path):
    ws = tmp_path / "ws"
    p = ws / "evidence/A/sayfa.html"
    p.parent.mkdir(parents=True)
    user, dom = EMAIL.split("@")
    p.write_text(
        "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Duyuru</title>"
        f"<script>var k='{TC2}';</script></head><body><h1>Yönetmelik</h1>"
        f"<p>İletişim: <a href='mailto:{EMAIL}'>{user}&#64;{dom}</a></p>"
        f"<p>Tel: <span>{PHONE}</span></p><!-- {TC1} --><td>Öğrenci no: {OGR}</td></body></html>",
        encoding="utf-8")
    rep = R.run(ws)
    rec = rep["dosyalar"][0]
    assert rec["bicim"] == "html" and rec["durum"] == "tamam", rec
    out = (ws / "evidence-maskeli/A/sayfa.html").read_text(encoding="utf-8")
    for v in (EMAIL, user, TC1, TC2, OGR, "000 11 22"):
        assert v not in out, v
    assert "Yönetmelik" in out and "[EPOSTA]" in out


@needs_ocr
def test_scanned_pdf_pypdf_engine_cannot_mask_image_so_fails(tmp_path):
    """PyMuPDF yokken (pypdf motoru) taranmış sayfadaki bulgu kapatılamaz: yeniden tarama
    (pdftoppm + OCR) bulur, dosya yayımlanmaz."""
    import shutil as _sh
    if not _sh.which("pdftoppm") and F._fitz() is None:
        pytest.skip("pdftoppm yok")
    ws = tmp_path / "ws"
    p = ws / "evidence/A/tarama.pdf"
    p.parent.mkdir(parents=True)
    make_page().save(p, format="PDF", resolution=150)
    rep = R.run(ws, engine="pypdf")
    rec = rep["dosyalar"][0]
    assert rec["durum"] == "basarisiz" and rec["kalan"].get("tc_no") == 1, rec
    assert not (ws / "evidence-maskeli/A/tarama.pdf").exists()


def test_hex_glyph_codes_are_not_raw_tc(tmp_path):
    """İçerik akışındaki onaltılık glif kodlarında tesadüfen T.C. algoritmasını tutan rakam dizisi
    (gerçek belgede görüldü) ham taramada bulgu sayılmaz."""
    from test_mask import make_pdf
    hexs = ("AB" + TC2 + "C").encode()
    p = tmp_path / "g.pdf"
    make_pdf(p, [b"BT /F1 11 Tf 72 700 Td <" + hexs + b"> Tj ET"], meta=False, annot=False, attach=False)
    assert not F.scan_file(p, MaskRules())["bulgular"]


@needs_ocr
def test_docx_embedded_signature_image_covered_logo_kept(tmp_path):
    import io

    import docx
    sig = Image.new("RGB", (400, 150), "white")
    _signature(ImageDraw.Draw(sig), 40, 30)
    logo = Image.new("RGB", (300, 150), "white")
    dl = ImageDraw.Draw(logo)
    dl.ellipse([20, 20, 140, 130], fill=(230, 120, 20))
    dl.rectangle([160, 30, 280, 120], fill=(200, 20, 40))
    dl.line([(10, 140), (290, 10)], fill=(20, 40, 160), width=8)
    d = docx.Document()
    for im in (logo, sig):
        b = io.BytesIO()
        im.save(b, format="PNG")
        b.seek(0)
        d.add_picture(b)
    d.add_paragraph("Bölüm Başkanı")
    d.add_paragraph("İmza:")
    src = tmp_path / "ws/evidence/A/f.docx"
    src.parent.mkdir(parents=True)
    d.save(str(src))
    rep = R.run(tmp_path / "ws")
    rec = rep["dosyalar"][0]
    assert rec["durum"] == "tamam" and rec["imza_bolgesi"] == 1, rec
    z = zipfile.ZipFile(tmp_path / "ws/evidence-maskeli/A/f.docx")
    imgs = [Image.open(io.BytesIO(z.read(n))).convert("RGB") for n in sorted(z.namelist()) if "/media/" in n]
    by_size = {im.size: im for im in imgs}
    s_out = by_size[(400, 150)]
    assert s_out.convert("L").crop((60, 50, 280, 90)).getextrema()[1] <= RA.LABEL_GRAY   # imza karartıldı (etiketli)
    assert list(by_size[(300, 150)].getdata()) == list(logo.getdata())         # logo aynen


def test_covering_annotations_become_redactions(tmp_path):
    """Elle karartma için çizilmiş kalın çizgi/mürekkep/koyu vurgulama açıklamaları silinince altındaki
    içerik açığa çıkıyordu (gerçek kanıtta görüldü): kapladıkları alan karartılır, metin de silinir."""
    fitz = pytest.importorskip("pymupdf")
    doc = fitz.open()
    pg = doc.new_page(width=595, height=842)
    pg.insert_text((72, 100), "Gizli satir bir", fontsize=14)
    pg.insert_text((72, 200), "Gizli satir iki", fontsize=14)
    pg.insert_text((72, 300), "Acik satir uc", fontsize=14)
    a = pg.add_line_annot((70, 96), (180, 96))
    a.set_border(width=14)
    a.set_colors(stroke=(0, 0, 0))
    a.update()
    q = pg.search_for("Gizli satir iki")[0]
    h = pg.add_highlight_annot(q)
    h.set_colors(stroke=(0, 0, 0))
    h.update()
    src = tmp_path / "a.pdf"
    doc.save(str(src))
    dst = tmp_path / "b.pdf"
    res = F.mask_pdf_pymupdf(src, dst, MaskRules())
    assert "kapatan_isaretleme" in res["temizlenen"]
    out = fitz.open(str(dst))[0]
    t = out.get_text()
    assert "Gizli" not in t and "Acik satir uc" in t
    assert not list(out.annots() or [])
    img = RA.render(out, 72).convert("L")
    assert img.crop((80, 92, 160, 100)).getextrema()[1] < 60          # kapalı kaldı


def test_covering_annotations_block_pypdf_engine(tmp_path):
    fitz = pytest.importorskip("pymupdf")
    doc = fitz.open()
    pg = doc.new_page()
    pg.insert_text((72, 100), "Gizli", fontsize=14)
    a = pg.add_ink_annot([[(70, 96), (120, 98), (160, 95)]])
    a.set_border(width=14)
    a.update()
    p = tmp_path / "ws/evidence/a.pdf"
    p.parent.mkdir(parents=True)
    doc.save(str(p))
    rec = R.run(tmp_path / "ws", engine="pypdf")["dosyalar"][0]
    assert rec["durum"] == "hata" and rec["elle_bakilmali"] and "örten" in rec["neden"], rec
