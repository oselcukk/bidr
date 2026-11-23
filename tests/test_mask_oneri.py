"""`bidr maskele --yalniz-oneri`: hiçbir tespit kendiliğinden kapatılmaz; hepsi öneri olur, insan kararları
uygulanır. Bölgesiz biçimlerde (docx/xlsx/düz metin) desen başına sayfasız öneri; "kapat" yalnız o desenin metnini
değiştirir. Yalnız sentetik veri (uydurma e-posta/telefon, `.invalid`/örnek alan adları)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bidr.cli import main
from bidr.mask import bolge as BG
from bidr.mask import inceleme as INC
from bidr.mask import onbellek as OB
from bidr.mask import run as R

EPOSTA1, EPOSTA2 = "ayse.ornek@example.com", "mehmet.deneme@example.org"
TELEFON = "0532 111 22 33"


@pytest.fixture(autouse=True)
def _temiz():
    OB.ac(None)
    yield
    OB.ac(None)


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ev = ws / "evidence" / "A"
    ev.mkdir(parents=True)
    (ev / "not.txt").write_text(f"İletişim: {EPOSTA1}, {EPOSTA2}\nTelefon: {TELEFON}\nBaşka metin.\n",
                                encoding="utf-8")
    return ws


def _rapor(ws: Path) -> dict:
    return json.loads((ws / R.REPORT).read_text(encoding="utf-8"))


def _rec(ws: Path, dosya: str) -> dict:
    return next(r for r in _rapor(ws)["dosyalar"] if r["dosya"] == dosya)


def _teslim(ws: Path, rec: dict) -> Path:
    return ws / rec["teslim_kopya"]


def test_metin_dosyasi_oneri_kapat_yalniz_o_desen(tmp_path, capsys):
    ws = _ws(tmp_path)
    r = R.run(ws, onbellek_kullan=False, yalniz_oneri=True)
    assert r["yalniz_oneri"] is True
    rec = _rec(ws, "A/not.txt")
    assert rec["durum"] == "tamam" and rec["onay_bekleyen"] == 2 and R.bekliyor(rec), rec
    bs = {b["desen"]: b for b in rec["bolgeler"]}
    assert set(bs) == {"eposta", "telefon"}
    assert bs["eposta"]["adet"] == 2 and bs["telefon"]["adet"] == 1
    assert all(b["tur"] == BG.METIN and b["sayfa"] == 0 and b["konum"] == "metin" and b["karar"] == BG.ONAY
               and not b["kapali"] for b in bs.values())
    assert EPOSTA1 not in json.dumps(rec, ensure_ascii=False)          # değer rapora yazılmaz
    t = _teslim(ws, rec).read_text(encoding="utf-8")
    assert EPOSTA1 in t and TELEFON in t                                # özgün içerik
    # bolgeler --json: sayfasız öneri alanlarıyla
    assert main(["maskele", "bolgeler", "-w", str(ws), "--json"]) == 1
    j = json.loads(capsys.readouterr().out)
    ids = {b["desen"]: b["id"] for b in j["bolgeler"]}
    assert set(ids) == {"eposta", "telefon"}
    assert all(b["konum"] == "metin" and b["adet"] for b in j["bolgeler"])
    assert not j["bolgesiz"]
    # insan: e-posta kapat, telefon açık kalsın
    assert main(["maskele", "karar", "-w", str(ws), ids["eposta"], "kapat", "--kim", "sinama"]) == 0
    assert main(["maskele", "karar", "-w", str(ws), ids["telefon"], "birak", "--kim", "sinama"]) == 0
    capsys.readouterr()
    R.run(ws, onbellek_kullan=False, yalniz_oneri=True)
    rec = _rec(ws, "A/not.txt")
    bs = {b["desen"]: b for b in rec["bolgeler"]}
    assert bs["eposta"]["karar"] == BG.KAPATILDI and bs["eposta"]["kapali"]
    assert bs["telefon"]["karar"] == BG.BIRAKILDI
    assert rec["durum"] == "tamam" and not R.bekliyor(rec), rec
    t = (ws / R.OUT_DIR / "A/not.txt").read_text(encoding="utf-8")
    assert EPOSTA1 not in t and EPOSTA2 not in t and "[EPOSTA]" in t
    assert TELEFON in t                                                 # yalnız kapatılan desen değişti
    # insanın kapattığı yeniden açılabilir
    assert main(["maskele", "karar", "-w", str(ws), ids["eposta"], "birak"]) == 0
    R.run(ws, onbellek_kullan=False, yalniz_oneri=True)
    t = (ws / R.OUT_DIR / "A/not.txt").read_text(encoding="utf-8")
    assert EPOSTA1 in t


def test_normal_kip_degismez(tmp_path):
    ws = _ws(tmp_path)
    R.run(ws, onbellek_kullan=False)
    rec = _rec(ws, "A/not.txt")
    assert rec["durum"] == "tamam" and not rec.get("bolgeler") and not R.bekliyor(rec)
    t = (ws / R.OUT_DIR / "A/not.txt").read_text(encoding="utf-8")
    assert EPOSTA1 not in t and TELEFON not in t


def test_docx_oneri_ust_veri_temizlenir(tmp_path):
    docx = pytest.importorskip("docx")
    ws = tmp_path / "ws"
    p = ws / "evidence" / "B" / "belge.docx"
    p.parent.mkdir(parents=True)
    d = docx.Document()
    d.add_paragraph(f"Sorumlu: {EPOSTA1}")
    d.add_paragraph(f"Tel: {TELEFON}")
    d.core_properties.author = "Sentetik Yazar"
    d.save(str(p))
    R.run(ws, onbellek_kullan=False, yalniz_oneri=True)
    rec = _rec(ws, "B/belge.docx")
    assert rec["durum"] == "tamam" and rec["onay_bekleyen"] == 2, rec
    assert "ust_veri" in rec["temizlenen"]
    t = docx.Document(str(_teslim(ws, rec)))
    metin = "\n".join(x.text for x in t.paragraphs)
    assert EPOSTA1 in metin and TELEFON in metin
    assert not t.core_properties.author
    tel = next(b["id"] for b in rec["bolgeler"] if b.get("desen") == "telefon")
    INC.karar(ws, tel, "kapat", "sinama")
    R.run(ws, onbellek_kullan=False, yalniz_oneri=True)
    rec = _rec(ws, "B/belge.docx")
    t = docx.Document(str(_teslim(ws, rec)))           # e-posta hâlâ öneri: teslim kopyası
    metin = "\n".join(x.text for x in t.paragraphs)
    assert EPOSTA1 in metin and TELEFON not in metin and "[TELEFON]" in metin


def test_xlsx_oneri(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    ws = tmp_path / "ws"
    p = ws / "evidence" / "C" / "liste.xlsx"
    p.parent.mkdir(parents=True)
    wb = openpyxl.Workbook()
    wb.active["A1"] = "E-posta"
    wb.active["B1"] = EPOSTA2
    wb.save(str(p))
    R.run(ws, onbellek_kullan=False, yalniz_oneri=True)
    rec = _rec(ws, "C/liste.xlsx")
    assert [b["desen"] for b in rec["bolgeler"]] == ["eposta"] and rec["onay_bekleyen"] == 1
    assert openpyxl.load_workbook(str(_teslim(ws, rec))).active["B1"].value == EPOSTA2


def test_onbellek_kipleri_ayri(tmp_path):
    ws = _ws(tmp_path)
    R.run(ws, yalniz_oneri=True)
    R.run(ws)
    rec = _rec(ws, "A/not.txt")
    assert not rec.get("bolgeler") and EPOSTA1 not in (ws / R.OUT_DIR / "A/not.txt").read_text(encoding="utf-8")
    R.run(ws, yalniz_oneri=True)
    rec = _rec(ws, "A/not.txt")
    assert rec["onbellek"] and rec["onay_bekleyen"] == 2


def test_kaynak_kipinde_reddedilir(tmp_path, capsys):
    src = tmp_path / "kaynak"
    src.mkdir()
    assert main(["maskele", "--kaynak", str(src), "--out", str(tmp_path / "o"), "--yalniz-oneri"]) == 2
    assert "yalnız kanıt kipinde" in capsys.readouterr().err


def test_baglam_yalniz_oneri_kapatmaz_insan_karari_uygulanir():
    kk = {"abcd1234-s1-2": {"id": "abcd1234-s1-2", "karar": "kapat", "kim": "s"}}
    bg = BG.Baglam("abcd1234", kk, yalniz_oneri=True)
    a = BG.yeni(1, [10, 10, 50, 20], "kisisel_veri", BG.KAPATILDI, "desen", "metin_deseni", 0.9)
    b = BG.yeni(1, [10, 40, 50, 50], "kisisel_veri", BG.KAPATILDI, "desen", "metin_deseni", 0.9)
    c = dict(BG.yeni(1, [10, 60, 50, 70], "imza", BG.ONAY, "geri basma", "imza_blogu", 0.6), kapali=True)
    bg.sayfa(1, [a, b, c])
    assert a["karar"] == BG.ONAY and not a["kapali"] and a["oneri"]
    assert b["karar"] == BG.KAPATILDI and b["kapali"]
    assert c["karar"] == BG.ONAY and not c["kapali"]


fitz = None
try:
    import pymupdf as fitz  # noqa: F811
except ImportError:  # pragma: no cover
    pass


@pytest.mark.skipif(fitz is None, reason="PyMuPDF yok")
def test_pdf_yalniz_oneri_acik_kapat_karariyla_kapanir(tmp_path):
    ws = tmp_path / "ws"
    p = ws / "evidence" / "D" / "form.pdf"
    p.parent.mkdir(parents=True)
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), f"E-posta: {EPOSTA1}", fontsize=11)
    page.insert_text((72, 140), f"Telefon: {TELEFON}", fontsize=11)
    doc.save(str(p))
    doc.close()
    R.run(ws, engine="pymupdf", onbellek_kullan=False, yalniz_oneri=True)
    rec = _rec(ws, "D/form.pdf")
    acik = [b for b in rec["bolgeler"] if b["kaynak"] == "metin_deseni"]
    assert len(acik) == 2 and all(b["karar"] == BG.ONAY and not b["kapali"] for b in acik), rec["bolgeler"]
    assert rec["durum"] == "tamam" and R.bekliyor(rec), rec
    d = fitz.open(str(_teslim(ws, rec)))
    try:
        assert EPOSTA1 in d[0].get_text() and TELEFON in d[0].get_text()
    finally:
        d.close()
    eid = next(b["id"] for b in acik if "eposta" in b["neden"])
    INC.karar(ws, eid, "kapat", "sinama")
    R.run(ws, engine="pymupdf", onbellek_kullan=False, yalniz_oneri=True)
    rec = _rec(ws, "D/form.pdf")
    e = next(b for b in rec["bolgeler"] if b["id"] == eid)
    assert e["karar"] == BG.KAPATILDI and e["kapali"]
    assert not rec.get("redaksiyon_dogrulama")
    d = fitz.open(str(_teslim(ws, rec)))
    try:
        assert EPOSTA1 not in d[0].get_text() and TELEFON in d[0].get_text()
    finally:
        d.close()
