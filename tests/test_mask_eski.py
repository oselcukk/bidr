"""Maskeleme: eski biçim çevirisi (.doc/.xls/.msg/.ppt), `--ayir` ayrı klasörü ve metinle örtüşen
imza kutusunun karartılmaması (yalnız sentetik veri)."""
from __future__ import annotations

import email
import email.policy
import io
import json
import math
import shutil
import subprocess
import sys
import zipfile
from email.message import EmailMessage
from pathlib import Path

import pytest

from bidr.cli import main
from bidr.mask import MaskRules
from bidr.mask import eski as E
from bidr.mask import imza as IM
from bidr.mask import kaynak as K
from bidr.mask import raster as RA
from bidr.mask.ocr import Word

from test_mask import EMAIL, NAME, PHONE, TC1, TC2

RULES = MaskRules(names=(NAME,))
has_textutil = pytest.mark.skipif(shutil.which("textutil") is None, reason="textutil yok (macOS dışı)")


def _zip_bytes(members: dict[str, bytes]) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for n, d in members.items():
            z.writestr(n, d)
    return b.getvalue()


def _xlsx_bytes(rows) -> bytes:
    import openpyxl
    wb = openpyxl.Workbook()
    for r in rows:
        wb.active.append(r)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


# ------------------------------------------------------------------ .xls

class _Cell:
    def __init__(self, v, t):
        self.value, self.ctype = v, t


class _Sheet:
    def __init__(self, name, rows):
        self.name, self._rows = name, rows
        self.nrows = len(rows)
        self.merged_cells = []

    def row(self, r):
        return self._rows[r]


class _Book:
    datemode = 0

    def __init__(self, sheets):
        self._s = sheets

    def sheets(self):
        return self._s

    def release_resources(self):
        pass


def _fake_xls(monkeypatch):
    xlrd = pytest.importorskip("xlrd")
    T, N = xlrd.XL_CELL_TEXT, xlrd.XL_CELL_NUMBER
    book = _Book([_Sheet("Liste/1", [[_Cell("Ad", T), _Cell("TC", T), _Cell("Telefon", T)],
                                     [_Cell(NAME, T), _Cell(float(TC1), N), _Cell(PHONE, T)],
                                     [_Cell("Sayı: E-12345678-302.01-2345678", T), _Cell("", xlrd.XL_CELL_EMPTY),
                                      _Cell(3.0, N)]])])
    monkeypatch.setattr(xlrd, "open_workbook", lambda *a, **k: book)


def test_xls_converted_to_xlsx_and_masked(tmp_path, monkeypatch):
    import openpyxl
    _fake_xls(monkeypatch)
    s = tmp_path / "s"
    s.mkdir()
    (s / "liste.xls").write_bytes(b"\xd0\xcf\x11\xe0 sentetik BIFF")
    rep = K.run_source(s, tmp_path / "o", rules=RULES)
    r = rep["dosyalar"][0]
    assert r["dosya"] == "liste.xls" and r["hedef"] == "liste.xlsx"
    assert r["ozgun_bicim"] == "xls" and r["bicim"] == "xlsx" and "xlrd" in r["donusum"]
    assert r["durum"] == "tamam" and r["maskelenen"] == {"ad": 1, "tc_no": 1, "telefon": 1}
    assert not (tmp_path / "o/liste.xls").exists()
    ws = openpyxl.load_workbook(tmp_path / "o/liste.xlsx").worksheets[0]
    vals = [c.value for row in ws.iter_rows() for c in row]
    assert ws.title == "Liste1" and "Sayı: E-12345678-302.01-2345678" in vals and 3 in vals
    assert not {NAME, PHONE, TC1, int(TC1)} & set(vals)
    assert rep["ozet"]["eski_bicim_cevrilen"] == 1


def test_xls_that_is_really_xlsx(tmp_path):
    s = tmp_path / "s"
    s.mkdir()
    (s / "web.xls").write_bytes(_xlsx_bytes([["Telefon", PHONE]]))
    r = K.run_source(s, tmp_path / "o", rules=RULES)["dosyalar"][0]
    assert r["hedef"] == "web.xlsx" and r["durum"] == "tamam" and "içi xlsx" in r["donusum"]


def test_unreadable_xls_copied_and_flagged(tmp_path):
    s = tmp_path / "s"
    s.mkdir()
    (s / "bozuk.xls").write_bytes(b"\xd0\xcf\x11\xe0 bozuk")
    rep = K.run_source(s, tmp_path / "o", rules=RULES)
    r = rep["dosyalar"][0]
    assert r["durum"] == "desteklenmiyor" and r["elle_bakilmali"] and "çevrilemedi" in r["neden"]
    assert (tmp_path / "o/bozuk.xls").read_bytes() == b"\xd0\xcf\x11\xe0 bozuk"


# ------------------------------------------------------------------ .doc

def _make_doc(path: Path, text: str) -> None:
    txt = path.with_suffix(".txt")
    txt.write_text(text, encoding="utf-8")
    subprocess.run(["textutil", "-convert", "doc", "-output", str(path), str(txt)], check=True,
                   capture_output=True)
    txt.unlink()


@has_textutil
def test_doc_converted_with_textutil(tmp_path):
    s = tmp_path / "s"
    s.mkdir()
    _make_doc(s / "dilekce.doc", f"Dilekçe\nAd: {NAME}\nTelefon: {PHONE}\nTC {TC2}\nSayı: E-12345678-302.01-2345678\n")
    (s / "arsiv.zip").write_bytes(_zip_bytes({"ic/eski.doc": (s / "dilekce.doc").read_bytes()}))
    rep = K.run_source(s, tmp_path / "o", rules=RULES)
    recs = {r["dosya"]: r for r in rep["dosyalar"]}
    r = recs["dilekce.doc"]
    assert r["hedef"] == "dilekce.docx" and r["ozgun_bicim"] == "doc" and "textutil" in r["donusum"]
    assert r["durum"] == "tamam" and {"ad", "telefon", "tc_no"} <= set(r["maskelenen"])
    with zipfile.ZipFile(tmp_path / "o/dilekce.docx") as z:
        xml = z.read("word/document.xml").decode()
    assert NAME not in xml and PHONE not in xml and "E-12345678-302.01-2345678" in xml
    m = recs["arsiv.zip!/ic/eski.doc"]
    assert m["hedef"] == "arsiv.zip!/ic/eski.docx" and m["durum"] == "tamam"
    with zipfile.ZipFile(tmp_path / "o/arsiv.zip") as z:
        assert z.namelist() == ["ic/eski.docx"]


def test_doc_without_textutil_flagged(tmp_path, monkeypatch):
    monkeypatch.setattr(E.shutil, "which", lambda name: None)
    s = tmp_path / "s"
    s.mkdir()
    (s / "eski.doc").write_bytes(b"\xd0\xcf\x11\xe0 sentetik")
    r = K.run_source(s, tmp_path / "o", rules=RULES)["dosyalar"][0]
    assert r["durum"] == "desteklenmiyor" and r["elle_bakilmali"] and "textutil yok" in r["neden"]
    assert (tmp_path / "o/eski.doc").exists()


@has_textutil
def test_doc_not_recognised_by_textutil_flagged(tmp_path):
    s = tmp_path / "s"
    s.mkdir()
    (s / "eski.doc").write_bytes(b"\xd0\xcf\x11\xe0 sentetik")      # textutil düz metin sanar
    r = K.run_source(s, tmp_path / "o", rules=RULES)["dosyalar"][0]
    assert r["durum"] == "desteklenmiyor" and "tanımadı" in r["neden"]


# ------------------------------------------------------------------ .ppt/.pptx, .msg

@pytest.mark.parametrize("name", ["sunum.ppt", "sunum.pptx"])
def test_presentation_flagged(tmp_path, name):
    s = tmp_path / "s"
    s.mkdir()
    (s / name).write_bytes(b"PK sentetik")
    r = K.run_source(s, tmp_path / "o", rules=RULES)["dosyalar"][0]
    assert r["durum"] == "desteklenmiyor" and r["elle_bakilmali"] and "sunum" in r["neden"]


def test_msg_without_library_flagged(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "extract_msg", None)
    s = tmp_path / "s"
    s.mkdir()
    (s / "ileti.msg").write_bytes(b"\xd0\xcf\x11\xe0 sentetik")
    r = K.run_source(s, tmp_path / "o", rules=RULES)["dosyalar"][0]
    assert r["durum"] == "desteklenmiyor" and "extract-msg" in r["neden"]


def test_msg_converted_to_eml(tmp_path, monkeypatch):
    class _Att:
        longFilename = "ek.txt"
        data = f"ek {TC2}\n".encode()

    class _Msg:
        subject = f"Başvuru {NAME}"
        sender = f"{NAME} <{EMAIL}>"
        to = "bolum@ornek.edu.tr"
        cc = None
        date = None
        body = f"Telefon {PHONE}\nSayı: E-12345678-302.01-2345678\n"
        htmlBody = None
        attachments = [_Att()]

        def __init__(self, path):
            pass

        def close(self):
            pass

    mod = type(sys)("extract_msg")
    mod.Message = _Msg
    monkeypatch.setitem(sys.modules, "extract_msg", mod)
    s = tmp_path / "s"
    s.mkdir()
    (s / "ileti.msg").write_bytes(b"\xd0\xcf\x11\xe0 sentetik")
    rep = K.run_source(s, tmp_path / "o", rules=RULES)
    recs = {r["dosya"]: r for r in rep["dosyalar"]}
    r = recs["ileti.msg"]
    assert r["hedef"] == "ileti.eml" and r["ozgun_bicim"] == "msg" and r["durum"] == "tamam"
    assert recs["ileti.msg!/ek.txt"]["maskelenen"] == {"tc_no": 1}
    data = (tmp_path / "o/ileti.eml").read_bytes().decode("utf-8", "replace")
    assert NAME not in data and PHONE not in data and EMAIL not in data


# ------------------------------------------------------------------ --ayir

@pytest.fixture
def src(tmp_path):
    s = tmp_path / "bolum"
    (s / "Kurul").mkdir(parents=True)
    (s / "Kurul/not.txt").write_text(f"Telefon {PHONE}\n", encoding="utf-8")
    (s / "Kurul/sunum.ppt").write_bytes(b"\xd0\xcf\x11\xe0 sentetik")
    (s / "arsiv.zip").write_bytes(_zip_bytes({"a/liste.txt": f"TC {TC1}\n".encode(),
                                              "a/sunum.pptx": b"PK sentetik"}))
    m = EmailMessage()
    m["From"] = "bolum@ornek.edu.tr"
    m["Subject"] = "Toplantı"
    m.set_content("Ekte.\n")
    m.add_attachment(b"PK sentetik", maintype="application", subtype="octet-stream", filename="sunum.pptx")
    (s / "ileti.eml").write_bytes(m.as_bytes())
    return s


def test_default_keeps_unmaskable_in_copy(src, tmp_path):
    rep = K.run_source(src, tmp_path / "o", rules=RULES)
    assert (tmp_path / "o/Kurul/sunum.ppt").exists()
    with zipfile.ZipFile(tmp_path / "o/arsiv.zip") as z:
        assert "a/sunum.pptx" in z.namelist()
    assert "ayrilan" not in rep and not (tmp_path / ("o" + K.SIKI_SUFFIX)).exists()


def test_ayir_sets_unmaskable_aside(src, tmp_path):
    out = tmp_path / "o"
    rep = K.run_source(src, out, rules=RULES, ayir=True)
    aside = Path(rep["ayrilan_klasor"])
    assert aside == tmp_path / ("o" + K.SIKI_SUFFIX)
    # maskeli kopyada yok, ayrı klasörde aynı göreli yolda
    assert not (out / "Kurul/sunum.ppt").exists() and (out / "Kurul/not.txt").exists()
    assert (aside / "Kurul/sunum.ppt").read_bytes() == (src / "Kurul/sunum.ppt").read_bytes()
    with zipfile.ZipFile(out / "arsiv.zip") as z:
        assert z.namelist() == ["a/liste.txt"]
    assert (aside / "arsiv.zip/a/sunum.pptx").read_bytes() == b"PK sentetik"
    # e-posta eki yerine not
    msg = email.message_from_bytes((out / "ileti.eml").read_bytes(), policy=email.policy.default)
    names = [p.get_filename() for p in msg.iter_attachments()]
    assert names == ["sunum.pptx.ayrildi.txt"]
    assert (aside / "ileti.eml/sunum.pptx").exists()
    listed = {a["dosya"]: a["ayrildi"] for a in rep["ayrilan"]}
    assert listed == {"Kurul/sunum.ppt": "Kurul/sunum.ppt", "arsiv.zip!/a/sunum.pptx": "arsiv.zip/a/sunum.pptx",
                      "ileti.eml!/sunum.pptx": "ileti.eml/sunum.pptx"}
    assert rep["ozet"]["ayrilan"] == 3
    assert all(e.get("ayrildi") for e in rep["elle_bakilmali"])
    # yeniden çalıştırma: kendi klasörlerinin üstüne yazar
    K.run_source(src, out, rules=RULES, ayir=True)


def test_cli_ayir(src, tmp_path, capsys):
    out = tmp_path / "cikti"
    rc = main(["maskele", "--kaynak", str(src), "--out", str(out), "--ayir", "--is", "2"])
    assert rc == 1
    o = capsys.readouterr().out
    assert "--ayir: 3 dosya" in o
    rep = json.loads((tmp_path / "cikti.maskeleme-raporu.json").read_text(encoding="utf-8"))
    assert len(rep["ayrilan"]) == 3 and not (out / "Kurul/sunum.ppt").exists()


# ------------------------------------------------------------------ metinle örtüşen imza

PIL = pytest.importorskip("PIL")
from PIL import Image, ImageDraw  # noqa: E402


def _stroke(d, x, y, w=260, h=70):
    pts = [(x + t / 159 * w + 18 * math.sin(t / 159 * 25),
            y + h / 2 + h / 2 * math.sin(t / 159 * 9) * math.cos(t / 159 * 3)) for t in range(160)]
    d.line(pts, fill=(20, 40, 190), width=4, joint="curve")


def _page(words_under: int):
    """150 ppi sayfa: "İmza:" etiketi; sağında mavi imza; imzanın altında `words_under` basılı kelime
    (yalnız kelime kutusu: OCR'sız birim testi)."""
    img = Image.new("RGB", (1240, 900), "white")
    d = ImageDraw.Draw(img)
    words = [Word("İmza:", 95, 100, 400, 190, 430, (1, 1, 1, 0))]
    _stroke(d, 230, 370)
    x, y, line = 240, 385, 2
    for i in range(words_under):
        words.append(Word(f"Gövde{i}", 95, x, y, x + 46, y + 18, (1, 1, line, 0)))
        x += 52
        if x > 440:
            x, y, line = 240, y + 26, line + 1
    return img, words


def test_signature_with_few_words_is_covered():
    img, words = _page(2)
    r = IM.analyze(img, words, 150)
    assert r.kapat and r.elle_bolge == 0 and r.kesin
    assert r.ortusen_kelime <= IM.MAX_ORTUSEN


def test_signature_over_body_text_not_covered():
    img, words = _page(14)
    r = IM.analyze(img, words, 150)
    assert not r.kapat and r.elle_bolge >= 1 and not r.kesin
    assert r.ortusen_kelime == 0 and max(o[0] for o in r.olcum) > IM.MAX_ORTUSEN
    # sınır açıkça yükseltilirse kapatılır (ölçüm için)
    assert IM.analyze(img, words, 150, max_ortusen=100, max_pay=1.1).kapat


def test_reocr_keeps_body_text_open(monkeypatch):
    """Sayfa OCR'ı imzanın altındaki metni okuyamamış olsa da kırpıntı OCR'ı okursa kutu kapatılmaz."""
    img, words = _page(0)
    r = IM.analyze(img, words, 150)
    assert r.kapat
    monkeypatch.setattr(RA, "ocr_available", lambda: True)
    many = [Word(f"metin{i}", 90, i * 60, 0, i * 60 + 50, 20, (1, 1, 1, 0)) for i in range(IM.MAX_ORTUSEN + 1)]
    monkeypatch.setattr(RA, "ocr_words", lambda crop, psm=None: many)
    n = len(r.kapat)
    RA.verify_covers(r, lambda b: RA.crop_for_ocr(img, 150, b))
    assert not r.kapat and r.elle_bolge == n and not r.kesin and r.dogrulama == [IM.MAX_ORTUSEN + 1] * n


def test_reocr_ignores_labels_and_placeholders(monkeypatch):
    img, words = _page(0)
    r = IM.analyze(img, words, 150)
    n = len(r.kapat)
    monkeypatch.setattr(RA, "ocr_available", lambda: True)
    few = [Word(t, 90, 0, 0, 40, 20, (1, 1, 1, 0)) for t in ("[İMZA]", "İmza", "Prof.", "Başkanı", "Kisioglu")]
    monkeypatch.setattr(RA, "ocr_words", lambda crop, psm=None: few)
    RA.verify_covers(r, lambda b: RA.crop_for_ocr(img, 150, b))
    assert len(r.kapat) == n and r.dogrulama == [1] * n


def test_image_scan_reports_text_overlap(tmp_path, monkeypatch):
    img, words = _page(14)
    monkeypatch.setattr(RA, "ocr_available", lambda: False)

    res = IM.analyze(img, words, 150)

    def fake(im, ppi, rules, **kw):
        sc = RA.ImageScan()
        sc.imza = res
        return sc
    monkeypatch.setattr(RA, "analyze_image", fake)
    p = tmp_path / "imzali.png"
    img.save(p)
    out = RA.scan_image(p, RULES)
    assert any("basılı metinle örtüşen" in s for s in out["sorunlar"]) and out["imza_metin"] == ["görsel"]


def test_signature_ink_mostly_on_text_not_covered():
    """Az kelime ama adaydaki mürekkebin çoğu kelime kutularında (renkli basılı başlık gibi): kapatılmaz."""
    img, words = _page(0)
    words = [words[0], Word("Başlık", 95, 215, 360, 355, 445, (1, 1, 2, 0)),
             Word("Yazısı", 95, 355, 360, 500, 445, (1, 1, 2, 0))]
    r = IM.analyze(img, words, 150)
    assert any(o[0] == 2 and o[1] >= IM.MAX_METIN_PAYI and not o[2] for o in r.olcum)
    assert r.elle_bolge >= 1 and not r.kesin
    assert IM.analyze(img, words, 150, max_pay=1.1).elle_bolge == 0
