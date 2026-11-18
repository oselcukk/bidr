"""ingest testleri: tamamen sentetik (belgeler test içinde üretilir)."""
from __future__ import annotations

import csv
import shutil
import zipfile
from pathlib import Path

import pytest

from bidr.common import Workspace, doc_id
from bidr.ingest import extract as ex
from bidr.ingest import ocr
from bidr.ingest.pipeline import run, scan

HAS_POPPLER = bool(shutil.which("pdftotext") and shutil.which("pdfinfo"))
HAS_OCR = HAS_POPPLER and bool(shutil.which("pdftoppm")) and ocr.ocr_available()
HAS_TEXTUTIL = bool(shutil.which("textutil"))


# ----------------------------------------------------------------- üreticiler

def make_docx(path: Path) -> Path:
    import docx

    d = docx.Document()
    sec = d.sections[0]
    sec.header.paragraphs[0].text = "Ust bilgi BASLIK-ALFA"
    sec.footer.paragraphs[0].text = "FR-9999 Rev.01"
    ft = sec.footer.add_table(rows=1, cols=2, width=docx.shared.Inches(6))
    ft.cell(0, 0).text = "Form No: XY-123"
    ft.cell(0, 1).text = "Sayfa altbilgi tablosu"
    d.add_paragraph("Govde paragrafi birinci")
    outer = d.add_table(rows=2, cols=2)
    outer.cell(0, 0).text = "Dis hucre A1"
    outer.cell(0, 1).text = "Dis hucre B1"
    outer.cell(1, 0).text = "Dis hucre A2"
    inner_cell = outer.cell(1, 1)
    inner_cell.text = "Ic tablo oncesi"
    inner = inner_cell.add_table(rows=2, cols=2)
    inner.cell(0, 0).text = "Katilimci Bir"
    inner.cell(0, 1).text = "Imza Bir"
    inner.cell(1, 0).text = "Katilimci Iki"
    inner.cell(1, 1).text = "Imza Iki"
    d.add_paragraph("Govde paragrafi son")
    d.save(path)
    return path


def make_xlsx(path: Path) -> Path:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Birinci"
    ws.append(["Ders", "Kredi"])
    ws.append(["MAT101", 4])
    ws2 = wb.create_sheet("Ikinci")
    ws2["C3"] = "uzak hucre degeri"
    wb.save(path)
    return path


def make_pptx(path: Path) -> Path:
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    s1 = prs.slides.add_slide(prs.slide_layouts[1])
    s1.shapes.title.text = "Slayt bir baslik"
    s1.placeholders[1].text = "Madde metni"
    s2 = prs.slides.add_slide(prs.slide_layouts[5])
    s2.shapes.title.text = "Tablolu slayt"
    tbl = s2.shapes.add_table(2, 2, Inches(1), Inches(2), Inches(4), Inches(1)).table
    tbl.cell(0, 0).text = "TabloHucre1"
    tbl.cell(1, 1).text = "TabloHucre4"
    prs.save(path)
    return path


def make_text_image(path: Path, lines: list[str]):
    from PIL import Image, ImageDraw, ImageFont

    try:
        font = ImageFont.load_default(size=56)
    except TypeError:  # eski Pillow
        font = ImageFont.load_default()
    img = Image.new("RGB", (1800, 160 + 110 * len(lines)), "white")
    dr = ImageDraw.Draw(img)
    for i, ln in enumerate(lines):
        dr.text((80, 80 + 110 * i), ln, fill="black", font=font)
    img.save(path)
    return img


def make_text_pdf(path: Path, page_texts: list[str]) -> Path:
    """Metin katmanlı en küçük PDF (Helvetica), elle yazılmış."""
    objs: list[bytes] = []
    n = len(page_texts)
    font_id = 3 + 2 * n
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode())
    for i, t in enumerate(page_texts):
        content_id = 4 + 2 * i
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                    f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>".encode())
        lines = t.split("\n")
        ops = "BT /F1 14 Tf 72 720 Td 18 TL " + " ".join(f"({ln}) Tj T*" for ln in lines) + " ET"
        objs.append(f"<< /Length {len(ops)} >>\nstream\n{ops}\nendstream".encode())
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for k, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{k} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(bytes(out))
    return path


def read_inv(ws: Path) -> dict[str, dict]:
    with open(Workspace(ws).inventory, newline="", encoding="utf-8") as f:
        return {r["rel_path"]: r for r in csv.DictReader(f)}


def text_of(ws: Path, row: dict) -> str:
    return Workspace(ws).text_path(row["doc_id"]).read_text(encoding="utf-8")


# ---------------------------------------------------------------------- docx

def test_docx_nested_table_header_footer(tmp_path):
    p = make_docx(tmp_path / "x.docx")
    res = ex.extract(p)
    t = res.text
    for s in ["Ust bilgi BASLIK-ALFA", "FR-9999 Rev.01", "Form No: XY-123",
              "Govde paragrafi birinci", "Dis hucre A1 | Dis hucre B1",
              "Ic tablo oncesi", "Katilimci Bir | Imza Bir", "Katilimci Iki | Imza Iki",
              "Govde paragrafi son"]:
        assert s in t, s
    # iç tablo bir kez yazılır (iter() kaynaklı tekrar yok)
    assert t.count("Katilimci Iki") == 1
    # sıra: üstbilgi < gövde < altbilgi
    assert t.index("BASLIK-ALFA") < t.index("Govde paragrafi birinci") < t.index("FR-9999")
    assert t.index("Govde paragrafi birinci") < t.index("Katilimci Bir") < t.index("Govde paragrafi son")


def test_docx_textbox_not_duplicated(tmp_path):
    """mc:AlternateContent içindeki metin kutusu (Choice + Fallback) bir kez okunur."""
    p = make_docx(tmp_path / "tb.docx")
    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    box = (
        '<w:p><w:r><mc:AlternateContent xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006">'
        f'<mc:Choice Requires="wps"><w:drawing><w:txbxContent xmlns:w="{W}"><w:p><w:r><w:t>KUTU-KOD-77</w:t></w:r></w:p>'
        '</w:txbxContent></w:drawing></mc:Choice>'
        f'<mc:Fallback><w:pict><w:txbxContent xmlns:w="{W}"><w:p><w:r><w:t>KUTU-KOD-77</w:t></w:r></w:p></w:txbxContent>'
        '</w:pict></mc:Fallback></mc:AlternateContent></w:r></w:p>'
    )
    out = tmp_path / "tb2.docx"
    with zipfile.ZipFile(p) as zin, zipfile.ZipFile(out, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename.startswith("word/footer"):
                s = data.decode("utf-8")
                s = s.replace("</w:ftr>", box + "</w:ftr>")
                data = s.encode("utf-8")
            zout.writestr(item, data)
    t = ex.extract(out).text
    assert t.count("KUTU-KOD-77") == 1


# --------------------------------------------------------------- xlsx / pptx

def test_xlsx_all_sheets(tmp_path):
    res = ex.extract(make_xlsx(tmp_path / "a.xlsx"))
    assert res.page_count == 2
    assert "MAT101\t4" in res.pages[0]
    assert "[sayfa: Ikinci]" in res.pages[1] and "uzak hucre degeri" in res.pages[1]


def test_pptx_slides_and_tables(tmp_path):
    res = ex.extract(make_pptx(tmp_path / "s.pptx"))
    assert res.page_count == 2
    assert "Slayt bir baslik" in res.pages[0] and "Madde metni" in res.pages[0]
    assert "TabloHucre1" in res.pages[1] and "TabloHucre4" in res.pages[1]


def test_text_and_html(tmp_path):
    (tmp_path / "a.txt").write_bytes("Çağrı ölçüt".encode("cp1254"))
    assert "Çağrı ölçüt" in ex.extract(tmp_path / "a.txt").text
    (tmp_path / "b.html").write_text(
        "<html><head><style>x{}</style></head><body><p>Bir</p><table><tr><td>H1</td><td>H2</td></tr></table>"
        "<script>gizli()</script></body></html>", encoding="utf-8")
    t = ex.extract(tmp_path / "b.html").text
    assert "Bir" in t and "H1" in t and "H2" in t and "gizli" not in t and "x{}" not in t


@pytest.mark.skipif(not HAS_TEXTUTIL, reason="textutil yok (macOS dışı)")
def test_rtf_textutil(tmp_path):
    (tmp_path / "r.rtf").write_text(r"{\rtf1\ansi Merhaba RTF metni\par}", encoding="ascii")
    assert "Merhaba RTF metni" in ex.extract(tmp_path / "r.rtf").text


# ----------------------------------------------------------------------- PDF

@pytest.mark.skipif(not HAS_POPPLER, reason="poppler yok")
def test_pdf_text_layer_pages(tmp_path):
    p = make_text_pdf(tmp_path / "t.pdf", [
        "Birinci sayfa metni yeterince uzun bir satir burada\nikinci satir da var metin",
        "Ikinci sayfa metni de yeterince uzun bir satir burada\nve devam ediyor",
    ])
    res = ex.extract(p, use_ocr=False)
    assert res.page_count == 2 and len(res.pages) == 2
    assert "Birinci sayfa" in res.pages[0] and "Ikinci sayfa" in res.pages[1]
    assert "\f" in res.text and res.ocr_pages == 0


@pytest.mark.skipif(not HAS_OCR, reason="tesseract/poppler yok")
def test_scanned_pdf_falls_back_to_ocr(tmp_path):
    img = make_text_image(tmp_path / "s.png", ["TARAMA BELGESI", "KOMISYON KARARI 2024"])
    pdf = tmp_path / "scan.pdf"
    img.save(pdf, "PDF", resolution=150)
    res = ex.extract(pdf, use_ocr=True)
    assert res.ocr_pages == 1
    assert "KOMISYON" in res.text.upper()
    off = ex.extract(pdf, use_ocr=False)
    assert off.ocr_missing == 1 and not off.text.strip()


@pytest.mark.skipif(not HAS_OCR, reason="tesseract yok")
def test_image_ocr(tmp_path):
    make_text_image(tmp_path / "foto.png", ["TOPLANTI TUTANAGI"])
    res = ex.extract(tmp_path / "foto.png", use_ocr=True)
    assert "TUTANAG" in res.text.upper()


# ------------------------------------------------------------------ pipeline

def build_source(root: Path) -> Path:
    src = root / "kaynak"
    (src / "alt" / "derin").mkdir(parents=True)
    make_docx(src / "alt" / "tutanak.docx")
    make_xlsx(src / "tablo.xlsx")
    shutil.copy(src / "tablo.xlsx", src / "alt" / "derin" / "tablo kopya.xlsx")
    (src / "not.txt").write_text("Duz metin notu", encoding="utf-8")
    (src / "bos.txt").write_text("   \n", encoding="utf-8")
    with zipfile.ZipFile(src / "arsiv.zip", "w") as z:
        z.writestr("a.txt", "x")
    (src / "bozuk.docx").write_bytes(b"bu bir docx degil")
    (src / ".DS_Store").write_bytes(b"\0\0")
    (src / "~$tutanak.docx").write_bytes(b"kilit")
    (src / "alt" / ".Belge.pdf.icloud").write_bytes(b"plist")
    (src / ".gizli").mkdir()
    (src / ".gizli" / "x.txt").write_text("gizli", encoding="utf-8")
    return src


def test_scan_skips_hidden_marks_icloud(tmp_path):
    src = build_source(tmp_path)
    rels = {e.rel: e for e in scan(src)}
    assert ".DS_Store" not in rels and "~$tutanak.docx" not in rels
    assert not any(".gizli" in r for r in rels)
    assert rels["alt/Belge.pdf"].placeholder and rels["alt/Belge.pdf"].ext == ".pdf"


def test_run_inventory_and_texts(tmp_path):
    src = build_source(tmp_path)
    ws = tmp_path / "ws"
    before = sorted((p.relative_to(src), p.stat().st_mtime_ns) for p in src.rglob("*"))
    rows = run(src, ws, use_ocr=False, log=lambda m: None)
    after = sorted((p.relative_to(src), p.stat().st_mtime_ns) for p in src.rglob("*"))
    assert before == after  # kaynak değişmedi

    inv = read_inv(ws)
    assert len(rows) == len(inv) == 9  # arşiv + içindeki a.txt ayrı satır
    tut = inv["alt/tutanak.docx"]
    assert tut["status"] == "ok" and tut["doc_id"] == doc_id(src / "alt" / "tutanak.docx")
    assert tut["sha256"].startswith(tut["doc_id"]) and int(tut["chars"]) > 0
    assert "Katilimci Iki" in text_of(ws, tut) and "FR-9999" in text_of(ws, tut)

    x = inv["tablo.xlsx"]
    assert x["pages"] == "2" and x["dup_of"] == ""
    kop = inv["alt/derin/tablo kopya.xlsx"]
    assert kop["dup_of"] == "tablo.xlsx" and kop["doc_id"] == x["doc_id"] and kop["status"] == "ok"

    assert inv["bos.txt"]["status"] == "empty"
    assert inv["arsiv.zip"]["status"] == "archive" and inv["arsiv.zip"]["doc_id"]
    uye = inv["arsiv.zip!/a.txt"]
    assert uye["status"] == "ok" and uye["kapsayici"] == "arsiv.zip" and text_of(ws, uye) == "x"
    assert inv["bozuk.docx"]["status"] == "error" and inv["bozuk.docx"]["error"]
    assert inv["alt/Belge.pdf"]["status"] == "not_downloaded" and inv["alt/Belge.pdf"]["doc_id"] == ""
    assert inv["not.txt"]["status"] == "ok"

    # sayfa ayırıcı: xlsx iki sayfa -> bir '\f'
    assert text_of(ws, x).count("\f") == 1


def test_rerun_skips_and_force(tmp_path, monkeypatch):
    src = build_source(tmp_path)
    ws = tmp_path / "ws"
    run(src, ws, use_ocr=False, log=lambda m: None)
    calls: list[str] = []
    real = ex.extract

    def spy(path, use_ocr=True):
        calls.append(Path(path).name)
        return real(path, use_ocr)

    monkeypatch.setattr(ex, "extract", spy)
    run(src, ws, use_ocr=False, log=lambda m: None)
    # yalnız tamamlanmamışlar (boş, desteklenmeyen, hatalı) yeniden denenir
    assert "tutanak.docx" not in calls and "tablo.xlsx" not in calls and "not.txt" not in calls
    assert read_inv(ws)["alt/tutanak.docx"]["status"] == "ok"
    calls.clear()
    run(src, ws, use_ocr=False, force=True, log=lambda m: None)
    assert "tutanak.docx" in calls and "tablo.xlsx" in calls
    assert "tablo kopya.xlsx" not in calls  # kopya hiç işlenmez


@pytest.mark.skipif(not HAS_OCR, reason="tesseract yok")
def test_no_ocr_then_ocr(tmp_path):
    src = tmp_path / "k"
    src.mkdir()
    make_text_image(src / "foto.png", ["TOPLANTI TUTANAGI"])
    ws = tmp_path / "ws"
    run(src, ws, use_ocr=False, log=lambda m: None)
    assert read_inv(ws)["foto.png"]["status"] == "needs_ocr"
    run(src, ws, use_ocr=True, log=lambda m: None)
    r = read_inv(ws)["foto.png"]
    assert r["status"] == "ocr" and "TUTANAG" in text_of(ws, r).upper()


def test_workspace_inside_source_rejected(tmp_path):
    src = build_source(tmp_path)
    with pytest.raises(ValueError):
        run(src, src / "ws", log=lambda m: None)


def test_cli_registered(tmp_path):
    from bidr.cli import main

    src = build_source(tmp_path)
    assert main(["ingest", str(src), "--workspace", str(tmp_path / "ws"), "--no-ocr"]) == 0
    assert (tmp_path / "ws" / "inventory.csv").exists()


# ------------------------------------------------- gömülü görseller ve kalite

def make_docx_with_images(path: Path, tmp: Path, *, body_text: str = "") -> Path:
    """Gövdede büyük ekran görüntüsü + küçük logo; üstbilgide logo."""
    import docx
    from docx.shared import Cm

    shot = tmp / "shot.png"
    make_text_image(shot, ["EKRAN GORUNTUSU", "DERS KAYIT LISTESI", "OGRENCI NUMARASI VE ADI"])
    logo = tmp / "logo.png"
    make_text_image(logo, ["LOGO METNI"])
    d = docx.Document()
    d.sections[0].header.paragraphs[0].add_run().add_picture(str(logo), width=Cm(12))
    if body_text:
        d.add_paragraph(body_text)
    d.add_picture(str(logo), width=Cm(2))        # küçük gösterim: elenir
    d.add_picture(str(shot), width=Cm(15))
    d.save(path)
    return path


@pytest.mark.skipif(not HAS_OCR, reason="tesseract yok")
def test_docx_embedded_image_ocr(tmp_path):
    p = make_docx_with_images(tmp_path / "ekran.docx", tmp_path)
    res = ex.extract(p, use_ocr=True)
    t = res.text
    assert "[gömülü görsel: word/media/" in t
    assert "KAYIT" in t.upper()
    assert "LOGO" not in t.upper()  # küçük gösterilen ve üstbilgideki logo OCR'lanmaz
    assert res.images_ocr == 1 and "img-ocr(1)" in res.method
    q = ex.assess(res)
    assert q["ocr_conf"] and q["quality"] >= ex.LOW_QUALITY and not q["low_quality"]


def test_docx_embedded_image_no_ocr_needs_ocr(tmp_path):
    src = tmp_path / "k"
    src.mkdir()
    make_docx_with_images(src / "ekran.docx", tmp_path)
    ws = tmp_path / "ws"
    run(src, ws, use_ocr=False, log=lambda m: None)
    assert read_inv(ws)["ekran.docx"]["status"] == "needs_ocr"


@pytest.mark.skipif(not HAS_OCR, reason="tesseract yok")
def test_docx_with_text_and_image_pipeline(tmp_path):
    src = tmp_path / "k"
    src.mkdir()
    make_docx_with_images(src / "ekran.docx", tmp_path, body_text="Govde metni burada")
    ws = tmp_path / "ws"
    run(src, ws, log=lambda m: None)
    r = read_inv(ws)["ekran.docx"]
    assert r["status"] == "ocr" and r["images_ocr"] == "1" and r["low_quality"] == ""
    t = text_of(ws, r)
    assert t.index("Govde metni") < t.index("[gömülü görsel")


@pytest.mark.skipif(not HAS_OCR, reason="tesseract yok")
def test_pptx_embedded_image_ocr(tmp_path):
    from pptx import Presentation
    from pptx.util import Cm

    shot = tmp_path / "shot.png"
    make_text_image(shot, ["SLAYT GORSELI", "KOMISYON UYELERI"])
    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[6])
    s.shapes.add_picture(str(shot), Cm(1), Cm(1), width=Cm(20))
    s.shapes.add_picture(str(shot), Cm(1), Cm(15), width=Cm(2))  # aynı görsel: bir kez
    p = tmp_path / "s.pptx"
    prs.save(p)
    res = ex.extract(p, use_ocr=True)
    assert res.page_count == 1 and "KOMISYON" in res.pages[0].upper()
    assert res.pages[0].count("[gömülü görsel: slayt 1") == 1


def make_noise_image(path: Path, seed: int = 7):
    """Metinsiz, gürültülü 'fotoğraf': OCR çöp ya da hiç metin vermez."""
    import random
    from PIL import Image, ImageDraw

    rnd = random.Random(seed)
    img = Image.new("L", (900, 700), 200)
    dr = ImageDraw.Draw(img)
    for _ in range(400):
        x, y = rnd.randrange(900), rnd.randrange(700)
        dr.line((x, y, x + rnd.randrange(-60, 60), y + rnd.randrange(-60, 60)),
                fill=rnd.randrange(0, 120), width=rnd.randrange(1, 6))
    img.save(path)


@pytest.mark.skipif(not HAS_OCR, reason="tesseract yok")
def test_photo_flagged_low_quality(tmp_path):
    src = tmp_path / "k"
    src.mkdir()
    make_noise_image(src / "foto.png")
    make_text_image(src / "temiz.png", ["BOLUM KURULU TOPLANTI TUTANAGI", "GUNDEM MADDELERI VE KARARLAR",
                                         "KATILIMCILAR LISTESI"])
    ws = tmp_path / "ws"
    run(src, ws, log=lambda m: None)
    inv = read_inv(ws)
    assert inv["foto.png"]["low_quality"] == "1"
    assert inv["temiz.png"]["low_quality"] == "" and float(inv["temiz.png"]["quality"]) >= ex.LOW_QUALITY
    assert inv["temiz.png"]["ocr_conf"]


def test_text_health_and_assess_without_ocr():
    from bidr.ingest.ocr import text_health

    assert text_health("Bölüm Kurulu 12.03.2025 tarihinde toplandı.") == 1.0
    assert text_health("ii Rrkk ;: |l ~~ aSdF eE 7x") < 0.3
    assert text_health("   ") is None
    assert text_health("Kime: Ad SOYAD <ad@gtu.edu.tr>; FR-0069 www.gtu.edu.tr") == 1.0
    q = ex.assess(ex.Extraction(["metin"], "text"))
    assert q == {"ocr_conf": "", "quality": "", "low_quality": False}
    # OCR'dan 24 karakter çöp: güven yüksek olsa da düşük kalite
    junk = ex.Extraction(["al ~ Ze. ii |] aSdF Rrkk"], "ocr", 1, 1, ocr_units=[("al ~ Ze. ii |] aSdF Rrkk", 60.0)])
    assert ex.assess(junk)["low_quality"]


@pytest.mark.skipif(not HAS_OCR, reason="tesseract/poppler yok")
def test_pdf_figure_page_not_ocred(tmp_path, monkeypatch):
    """Metin katmanı yeterli, yalnız logo boyutunda görsel olan PDF sayfası OCR'a gitmez;
    metin katmanı kısa (vektör çizilmiş metin) ya da tam sayfa tarama olan sayfa OCR'lanır."""
    from PIL import Image

    fig = tmp_path / "fig.png"
    make_text_image(fig, ["SEKIL ICINDEKI YAZI"])
    pdf = tmp_path / "fig.pdf"
    page = Image.new("RGB", (1240, 1754), "white")  # A4 @150dpi
    small = Image.open(fig).resize((400, 80))
    page.paste(small, (100, 100))
    page.save(pdf, "PDF", resolution=150)
    # pdfimages tek tam sayfa görsel görür; kapsamayı monkeypatch ile şekil boyutuna indir
    calls: list[int] = []
    real = ocr.ocr_pdf_page
    monkeypatch.setattr(ocr, "ocr_pdf_page", lambda p, n: (calls.append(n), real(p, n))[1])
    real_run = ex._run
    text = "Word belgesinden gelen yeterince uzun metin katmani burada duruyor ve okunuyor " * 5
    assert ex.TEXT_ENOUGH <= ex._alnum(text) < ex.STAMP_PAGE_ALNUM
    monkeypatch.setattr(ex, "_run", _fake_run_factory(real_run, text, cover_ppi=1200))  # ~%1.6
    res = ex.extract(pdf, use_ocr=True)
    assert calls == [] and res.ocr_pages == 0 and "Word belgesinden" in res.text
    # aynı logo, ama metin katmanı kısa: OCR denenir
    short = "Etkinlik uyeleri ozet bolumu kisa metin katmani parcasi"
    monkeypatch.setattr(ex, "_run", _fake_run_factory(real_run, short, cover_ppi=1200))
    ex.extract(pdf, use_ocr=True)
    assert calls == [1]
    calls.clear()
    monkeypatch.setattr(ex, "_run", _fake_run_factory(real_run, text, cover_ppi=150))
    ex.extract(pdf, use_ocr=True)
    assert calls == [1]  # tam sayfa tarama: damga durumunda OCR denenir


def _fake_run_factory(real_run, text: str, cover_ppi: int):
    """pdftotext çıktısını `text` yap; pdfimages ppi değerini `cover_ppi` olarak bildir."""
    def fake(cmd, timeout=300):
        r = real_run(cmd, timeout)
        if cmd[0] == "pdftotext":
            r.stdout = text.encode()
        elif cmd[0] == "pdfimages":
            lines = r.stdout.decode().splitlines()
            out = lines[:2]
            for ln in lines[2:]:
                parts = ln.split()
                parts[12] = parts[13] = str(cover_ppi)
                out.append(" ".join(parts))
            r.stdout = "\n".join(out).encode()
        return r
    return fake


@pytest.mark.skipif(not HAS_OCR, reason="tesseract/poppler yok")
def test_photo_pdf_without_text_flagged(tmp_path):
    src = tmp_path / "k"
    src.mkdir()
    make_noise_image(tmp_path / "n.png")
    from PIL import Image
    Image.open(tmp_path / "n.png").convert("RGB").save(src / "foto.pdf", "PDF", resolution=100)
    ws = tmp_path / "ws"
    run(src, ws, log=lambda m: None)
    r = read_inv(ws)["foto.pdf"]
    assert r["low_quality"] == "1"


# ------------------------------------------- taranmış sayfanın çöp metin katmanı

SCAN_LINES = ["BOLUM KURULU TOPLANTI TUTANAGI", "TOPLANTI TARIHI 19.11.2025 SAYISI 4",
              "GUNDEM MADDELERI VE KARARLAR", "KATILIMCILAR LISTESI VE IMZALAR",
              "MUFREDAT GUNCELLEME KOMISYONU", "DERS ICERIKLERI GOZDEN GECIRILDI",
              "OGRENCI GERI BILDIRIMLERI INCELENDI", "KARAR OYBIRLIGI ILE ALINMISTIR",
              "BOLUM BASKANI ONAYINA SUNULMUSTUR", "TOPLANTI SONA ERMISTIR"] * 2
# Tarayıcı OCR'ının çöp katmanını taklit eden bozulmuş kopya ("Toplantl Saylsl")
GARBLED_LAYER = "\n".join(
    " ".join(w[0] + w[1:].lower().replace("i", "l").replace("a", "|").replace("e", "E")
             if len(w) > 3 else w for w in ln.split()) for ln in SCAN_LINES)


def _scan_pdf(tmp_path: Path) -> Path:
    from PIL import Image

    img = tmp_path / "sayfa.png"
    make_text_image(img, SCAN_LINES)
    pdf = tmp_path / "tarama.pdf"
    Image.open(img).convert("RGB").save(pdf, "PDF", resolution=150)
    return pdf


@pytest.mark.skipif(not HAS_OCR, reason="tesseract/poppler yok")
def test_scanned_page_garbled_layer_replaced_by_ocr(tmp_path, monkeypatch):
    """Taranmış sayfa + yeterli uzunlukta ama sağlıksız metin katmanı: OCR'lanır, daha
    sağlıklı olan seçilir; kalite metin katmanı için de dolar."""
    pdf = _scan_pdf(tmp_path)
    assert ocr.text_health(GARBLED_LAYER) < ex.LAYER_HEALTH_OK
    assert ex._alnum(GARBLED_LAYER) >= ex.STAMP_PAGE_ALNUM  # eski kurallar OCR'lamazdı
    monkeypatch.setattr(ex, "_run", _fake_run_factory(ex._run, GARBLED_LAYER, cover_ppi=150))
    res = ex.extract(pdf, use_ocr=True)
    assert res.ocr_pages == 1 and "KURULU" in res.text.upper() and "S|ylsl" not in res.text
    q = ex.assess(res)
    assert q["ocr_conf"] and q["quality"] >= ex.LOW_QUALITY and not q["low_quality"]
    # OCR kapalı: katman kalır, kalite katman sağlığından dolar, düşük kalite işaretlenir
    off = ex.extract(pdf, use_ocr=False)
    assert "S|ylsl" in off.text and off.layer_units and off.layer_units[0][1]
    q = ex.assess(off)
    assert q["ocr_conf"] == "" and q["quality"] == round(ocr.text_health(GARBLED_LAYER), 2)
    assert q["low_quality"]


@pytest.mark.skipif(not HAS_OCR, reason="tesseract/poppler yok")
def test_healthy_layer_on_scan_not_ocred(tmp_path, monkeypatch):
    """Taranmış sayfanın sağlıklı metin katmanı (ve görselsiz sayfanın sağlıksız
    katmanı: tablo/kod) OCR'a gitmez; kalite yine dolar ve düşük işaretlenmez."""
    pdf = _scan_pdf(tmp_path)
    calls: list[int] = []
    real = ocr.ocr_pdf_page
    monkeypatch.setattr(ocr, "ocr_pdf_page", lambda p, n: (calls.append(n), real(p, n))[1])
    good = "Bölüm Kurulu toplantı tutanağı gündem maddeleri ve kararlar burada yer alıyor. " * 6
    monkeypatch.setattr(ex, "_run", _fake_run_factory(ex._run, good, cover_ppi=150))
    res = ex.extract(pdf, use_ocr=True)
    assert calls == [] and res.ocr_pages == 0 and "Bölüm Kurulu" in res.text
    q = ex.assess(res)
    assert q["quality"] == 1.0 and not q["low_quality"]
    # görsel kapsaması logo boyutunda: sağlıksız katman da OCR'lanmaz (doğuştan dijital)
    monkeypatch.setattr(ex, "_run", _fake_run_factory(ex._run, GARBLED_LAYER, cover_ppi=1200))
    res = ex.extract(pdf, use_ocr=True)
    assert calls == [] and "S|ylsl" in res.text
    assert not ex.assess(res)["low_quality"]  # taranmış sayfa değil: işaret yok


def test_prefer_ocr_rules():
    garbled = GARBLED_LAYER
    clean = "\n".join(SCAN_LINES)
    assert ex._prefer_ocr(garbled, clean, "health")
    assert not ex._prefer_ocr(clean, garbled, "health")
    # daha sağlıklı ama metnin çoğunu kaybettiriyor: katman kalır
    assert not ex._prefer_ocr(garbled, clean[:120], "health")
    # zorunlu durum eski kuralı korur: boş katmana OCR
    assert ex._prefer_ocr("", "kisa metin", "must")
    # damga durumu: OCR iki kattan fazla metin verirse
    assert ex._prefer_ocr("EBYS damga 12345", clean, "stamp")
