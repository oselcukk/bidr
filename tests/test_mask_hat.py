"""Maskeleme hattı (m2): bölge listesi ve insan kararları, teslim kapısı, önbellek, redaksiyon
doğrulaması, eski biçim dönüşümü (LibreOffice). Yalnız sentetik veri."""
from __future__ import annotations

import io
import json
import os
import shutil
import stat
import sys
from pathlib import Path

import pytest

from bidr.cli import main
from bidr.mask import bolge as BG
from bidr.mask import dogrula as DG
from bidr.mask import eski as E
from bidr.mask import inceleme as INC
from bidr.mask import ocr as O
from bidr.mask import onbellek as OB
from bidr.mask import raster as RA
from bidr.mask import run as R

from test_mask import TC1
from test_mask_raster import _scanned_pdf, make_page

PIL = pytest.importorskip("PIL")
fitz = pytest.importorskip("pymupdf")
from PIL import Image  # noqa: E402

needs_ocr = pytest.mark.skipif(not O.ocr_available(), reason="tesseract + tur/eng yok")


@pytest.fixture(autouse=True)
def _temiz_onbellek():
    """Testler arası süreç içi OCR belleği ve etkin önbellek sıfırlanır."""
    O._CACHE.clear()
    OB.ac(None)
    yield
    OB.ac(None)


def _ws_imzali(tmp_path: Path, name: str = "A/A.1/A.1.1/[1-OD3]. Tutanak.pdf") -> Path:
    ws = tmp_path / "ws"
    _scanned_pdf(ws / "evidence" / name, make_page(unlabeled_sig=True))
    return ws


def _rec(rep: dict, dosya: str | None = None) -> dict:
    return next(r for r in rep["dosyalar"] if dosya is None or r["dosya"] == dosya)


# ---------------------------------------------------------------- bölgeler ve kararlar

@needs_ocr
def test_bolgeler_kararlar_uygulanir_ve_kalicidir(tmp_path, capsys):
    ws = _ws_imzali(tmp_path)
    rel = "A/A.1/A.1.1/[1-OD3]. Tutanak.pdf"
    rep = R.run(ws, engine="pymupdf")
    rec = _rec(rep)
    assert rec["durum"] == "basarisiz" and rec["elle_bakilmali"], rec
    sha8 = OB.sha256_file(ws / "evidence" / rel)[:8]
    onay = BG.onay_bekleyen(rec["bolgeler"])
    assert onay and all(b["tur"] == "imza" and b["id"].startswith(f"{sha8}-s1-") for b in onay)
    assert any(b["tur"] == "kisisel_veri" and b["karar"] == "kapatildi" for b in rec["bolgeler"])   # TC, telefon …
    assert all(set(b) >= {"id", "sayfa", "kutu", "tur", "karar", "neden", "kaynak", "guven", "geri_basilan"}
               for b in rec["bolgeler"])
    assert TC1 not in json.dumps(rep, ensure_ascii=False)
    ids = [b["id"] for b in rec["bolgeler"]]
    # komut: onay bekleyenler listelenir
    assert main(["maskele", "bolgeler", "-w", str(ws), "--json"]) == 1
    js = json.loads(capsys.readouterr().out)
    assert {b["id"] for b in js["bolgeler"]} == {b["id"] for b in onay}
    # karar: kapat (CLI) → sonraki çalıştırmada kapatılır, yeniden sorulmaz
    for b in onay:
        assert main(["maskele", "karar", "-w", str(ws), b["id"], "kapat", "--kim", "sentetik"]) == 0
    capsys.readouterr()
    assert main(["maskele", "bolgeler", "-w", str(ws)]) == 0
    assert "KARAR VERİLDİ, UYGULANMADI" in capsys.readouterr().out
    rep2 = R.run(ws, engine="pymupdf")
    rec2 = _rec(rep2)
    assert rec2["durum"] == "tamam", rec2
    assert [b["id"] for b in rec2["bolgeler"]][:len(ids)] == ids                      # kararlı kimlik
    by = {b["id"]: b for b in rec2["bolgeler"]}
    for b in onay:
        assert by[b["id"]]["karar"] == "kapatildi" and by[b["id"]]["insan"]["kim"] == "sentetik"
    assert (ws / "evidence-maskeli" / rel).is_file() and not rec2.get("redaksiyon_dogrulama")
    assert INC.bekleyenler(ws)["bolgeler"] == []
    # kalıcı: üçüncü çalıştırma aynı
    rec3 = _rec(R.run(ws, engine="pymupdf"))
    assert rec3["durum"] == "tamam" and BG.ozet(rec3["bolgeler"]) == BG.ozet(rec2["bolgeler"])


@needs_ocr
def test_birak_karari_imzayi_acik_birakir(tmp_path):
    ws = tmp_path / "ws"
    p = ws / "evidence/A/foto.png"
    p.parent.mkdir(parents=True)
    make_page(pii=False, unlabeled_sig=True).save(p)
    rec = _rec(R.run(ws))
    assert rec["durum"] == "basarisiz" and rec["onay_bekleyen"] >= 1
    for b in BG.onay_bekleyen(rec["bolgeler"]):
        INC.karar(ws, b["id"], "birak", "sentetik")
    rec2 = _rec(R.run(ws))
    assert rec2["durum"] == "tamam", rec2
    assert {b["karar"] for b in rec2["bolgeler"] if b["tur"] == "imza"} == {"birakildi"}
    out = Image.open(ws / "evidence-maskeli/A/foto.png").convert("L")
    assert out.crop((800, 1540, 1060, 1630)).getextrema()[0] < 60        # imza mürekkebi duruyor
    assert out.crop((800, 1540, 1060, 1630)).getextrema()[1] > 200       # karartılmadı


def test_karar_eslesmezse_uygulanmaz():
    bg = BG.Baglam("abcd1234", {"abcd1234-s1-1": {"id": "abcd1234-s1-1", "karar": "birak", "kutu": [500, 500, 600, 600],
                                                  "tur": "imza"}})
    b = BG.yeni(1, [10, 10, 50, 50], "imza", BG.ONAY, "etiketsiz", "imza_etiketsiz", 0.3)
    bg.sayfa(1, [b])
    assert b["id"] == "abcd1234-s1-1" and b["karar"] == BG.ONAY and bg.uyarilar
    b2 = BG.yeni(1, [500, 500, 600, 600], "imza", BG.ONAY, "etiketsiz", "imza_etiketsiz", 0.3)
    bg2 = BG.Baglam("abcd1234", bg.kararlar)
    bg2.sayfa(1, [b2])
    assert b2["karar"] == BG.BIRAKILDI


def test_karar_komutu_bilinmeyen_bolge(tmp_path, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / R.REPORT).write_text(json.dumps({"dosyalar": []}), encoding="utf-8")
    assert main(["maskele", "karar", "-w", str(ws), "yok-s1-1", "kapat"]) == 2
    assert "bulunamadı" in capsys.readouterr().err
    assert not (ws / BG.KARARLAR).exists()


# ---------------------------------------------------------------- teslim kapısı (gerçek maskeleme)

def _pdf_metin(path: Path, metin: str) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), metin, fontsize=12)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    doc.close()


@needs_ocr
def test_teslim_kapisi_karar_ve_yukleme(tmp_path):
    from test_teslim import Sahte, _render, _rows, _ws
    from bidr.teslim.run import build
    ws = _ws(tmp_path)
    _render(ws, tmp_path, "dekanlik")
    ev = ws / "evidence" / "A" / "A.1"
    _pdf_metin(ev / "A.1.1" / "[1-OD3]. Sentetik kanıt bir.pdf", "Sentetik kurul karari metni.")
    kurul = ev / "A.1.2" / "[1-OD3]. Kurul kararı.pdf"
    kurul.unlink()
    _scanned_pdf(kurul, make_page(unlabeled_sig=True))
    rel = "A/A.1/A.1.2/[1-OD3]. Kurul kararı.pdf"
    rec = _rec(R.run(ws, engine="pymupdf"), rel)
    assert rec["durum"] == "basarisiz" and rec["onay_bekleyen"] >= 1
    res = build(ws, arac=Sahte(), zip_yap=False)
    pk = ws / "teslim" / "kanitlar" / "A" / "A.1"
    assert (pk / "A.1.1" / "[1-OD3]. Sentetik kanıt bir.pdf").is_file()
    # karar bekleyen: dışlanmaz; o anki maskeli hâli (çerçevesiz teslim kopyası) girer ve listelenir
    giren = pk / "A.1.2" / "[1-OD3]. Kurul kararı.pdf"
    assert rec.get("teslim_kopya") and giren.read_bytes() == (ws / rec["teslim_kopya"]).read_bytes()
    assert giren.read_bytes() != (ws / "evidence" / rel).read_bytes()
    doc = fitz.open(str(giren))
    try:
        assert "ONAY BEKLIYOR" not in doc[0].get_text()              # inceleme çerçevesi teslim kopyasında yok
    finally:
        doc.close()
    doc = fitz.open(str(ws / rec["kopya"]))
    try:
        assert "ONAY BEKLIYOR" in doc[0].get_text()                  # inceleme kopyasında var
    finally:
        doc.close()
    assert [x["kanit"] for x in res.karar_bekleyen] == [rel] and res.kontrol_bekliyor == []
    assert res.karar_bekleyen[0]["maskeleme"] == "karar bekliyor"
    rows = {(r["Ölçüt"], r["Kanıt no"]): r for r in _rows(ws / "teslim" / "kanit-dizini.csv")}
    assert ("A.1.2", "1_OD3") in rows and rows[("A.1.2", "1_OD3")]["Maskeleme"] == "karar bekliyor"
    # elle maskelenmiş sürüm: kabul edilir, kayıt "elle maskelendi", pakete girer
    elle = tmp_path / "elle.pdf"
    _pdf_metin(elle, "Elle maskelenmis surum [IMZA]")
    r = INC.yukle(ws, rel, elle, "sentetik")
    assert r["dosya"] == rel
    res = build(ws, arac=Sahte(), zip_yap=False)
    assert (pk / "A.1.2" / "[1-OD3]. Kurul kararı.pdf").read_bytes() == elle.read_bytes()
    assert res.karar_bekleyen == []
    rows = {(r["Ölçüt"], r["Kanıt no"]): r for r in _rows(ws / "teslim" / "kanit-dizini.csv")}
    assert rows[("A.1.2", "1_OD3")]["Maskeleme"] == "elle maskelendi"
    # yeniden maskeleme yüklenen sürümü korur (kanıt değişmedikçe)
    rec = _rec(R.run(ws, engine="pymupdf"), rel)
    assert rec["durum"] == "elle_maskelendi"
    assert (ws / "evidence-maskeli" / rel).read_bytes() == elle.read_bytes()
    # kişisel veri kalmış yükleme reddedilir
    kirli = tmp_path / "kirli.pdf"
    _pdf_metin(kirli, f"T.C. Kimlik No: {TC1}")
    with pytest.raises(INC.IncelemeError, match="kişisel veri"):
        INC.yukle(ws, rel, kirli)
    # kanıt değişti: yükleme yok sayılır; bölge kararı (kapat) sonrası girer
    (ws / R.ELLE_KAYIT).unlink()
    rec = _rec(R.run(ws, engine="pymupdf"), rel)
    for b in BG.onay_bekleyen(rec["bolgeler"]):
        INC.karar(ws, b["id"], "kapat", "sentetik")
    rec = _rec(R.run(ws, engine="pymupdf"), rel)
    assert rec["durum"] == "tamam", rec
    res = build(ws, arac=Sahte(), zip_yap=False)
    assert (pk / "A.1.2" / "[1-OD3]. Kurul kararı.pdf").is_file() and res.karar_bekleyen == []


# ---------------------------------------------------------------- önbellek

@needs_ocr
def test_onbellek_ocr_isabeti_ve_kural_surumu(tmp_path, monkeypatch):
    ws = _ws_imzali(tmp_path)
    O.CAGRI.clear()
    R.run(ws, engine="pymupdf")
    ilk = sum(O.CAGRI.values())
    assert ilk > 0 and (ws / ".cache" / "maske.sqlite").is_file()
    # değişmeyen dosya: yeniden işlenmez, OCR çağrılmaz
    O._CACHE.clear()
    O.CAGRI.clear()
    rep = R.run(ws, engine="pymupdf")
    assert sum(O.CAGRI.values()) == 0 and rep["ozet"]["onbellekten"] == 1 and _rec(rep).get("onbellek")
    # kural sürümü değişti: aday katmanı yeniden, OCR önbellekten (tesseract çağrılmaz)
    O._CACHE.clear()
    O.CAGRI.clear()
    monkeypatch.setattr(R, "KURAL_SURUM", R.KURAL_SURUM + 100)
    rep = R.run(ws, engine="pymupdf")
    assert rep["ozet"]["onbellekten"] == 0 and sum(O.CAGRI.values()) == 0, O.CAGRI
    assert _rec(rep)["durum"] == "basarisiz"
    # önbelleksiz: OCR yeniden çalışır
    O._CACHE.clear()
    O.CAGRI.clear()
    R.run(ws, engine="pymupdf", onbellek_kullan=False)
    assert sum(O.CAGRI.values()) > 0


def test_yeterli_metin_katmaninda_ocr_yok(tmp_path, monkeypatch):
    """Tam sayfa görüntü + yeterli (aranabilir PDF) metin katmanı: OCR çalışmaz."""
    img = make_page(pii=False)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(page.rect, stream=buf.getvalue())
    for i in range(30):
        page.insert_text((60, 60 + i * 24), f"Toplanti gundemi karar metni satir {i} kabul edilmistir",
                         fontsize=9, render_mode=3)
    assert RA.page_needs_ocr(page) == (False, True)
    page2 = fitz.open().new_page(width=595, height=842)
    page2.insert_image(page2.rect, stream=buf.getvalue())
    page2.insert_text((60, 60), "Bolum kurulu karari tutanagi ekidir", fontsize=9, render_mode=3)
    assert RA.page_needs_ocr(page2) == (True, True)                     # yetersiz katman: OCR
    calls = []
    monkeypatch.setattr(RA, "ocr_words", lambda *a, **k: calls.append(1) or [])
    ps = RA.scan_pdf_page(page, R.MaskRules())
    assert calls == [] and ps.get("metin_yeterli")


def test_psm11_yalniz_zayif_ocrda():
    good = [O.Word(f"kelime{i}", 95, 0, i * 10, 50, i * 10 + 8, (1, 1, i, 1)) for i in range(80)]
    assert not RA.weak_ocr(good)
    assert RA.weak_ocr(good[:10])
    assert RA.weak_ocr([O.Word("x9", 30, 0, 0, 5, 5, (1, 1, 1, 1))] * 80)


def test_fotografta_bos_ocr_tekrar_denenmez_ve_onay_bekler(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    p = ws / "evidence/A/foto.jpg"
    p.parent.mkdir(parents=True)
    from PIL import ImageDraw
    im = Image.new("RGB", (900, 1200), (200, 180, 160))
    d = ImageDraw.Draw(im)
    for k in range(40):
        d.ellipse([20 * k, 30 * k, 20 * k + 120, 30 * k + 90], outline=(30, 30, 30), width=6)
    im.save(p, quality=92)
    calls = []
    monkeypatch.setattr(RA, "ocr_words", lambda *a, **k: calls.append(1) or [])
    monkeypatch.setattr(RA, "ocr_available", lambda: True)
    monkeypatch.setattr(R, "raster_ocr_available", lambda: True)
    rec = _rec(R.run(ws, onbellek_kullan=False))
    ok = [b for b in rec["bolgeler"] if b["tur"] == "okunamayan_sayfa"]
    assert ok and ok[0]["karar"] == "onay_bekliyor" and rec["durum"] != "tamam", rec
    assert rec["elle_bakilmali"] and rec["taranamadi"]
    # her tarama tek OCR (döndürülüp yeniden denenmedi): maskeleme + yeniden tarama + kaynak tarama
    assert len(calls) <= 4, len(calls)


# ---------------------------------------------------------------- redaksiyon doğrulaması

def _pdf_gorselli(path: Path) -> None:
    im = Image.new("RGB", (400, 200), "white")
    from PIL import ImageDraw
    ImageDraw.Draw(im).rectangle([40, 40, 360, 160], fill=(200, 30, 30))
    for x in range(40, 360, 8):
        ImageDraw.Draw(im).line([(x, 40), (x + 4, 160)], fill=(20, 20, 200), width=2)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.insert_image(fitz.Rect(0, 50, 400, 250), stream=buf.getvalue())
    page.insert_text((10, 30), "Gizli deger 123456", fontsize=12)
    doc.save(str(path))
    doc.close()


def test_redaksiyon_dogrulamasi(tmp_path):
    src = tmp_path / "a.pdf"
    _pdf_gorselli(src)
    metin = BG.yeni(1, [5, 15, 200, 35], "kisisel_veri", BG.KAPATILDI, "desen", "metin_deseni", 0.9)
    gorsel = BG.yeni(1, [100, 100, 200, 150], "imza", BG.KAPATILDI, "imza", "imza_aday", 0.6)
    for b, n in ((metin, 1), (gorsel, 2)):
        b["id"] = f"x-s1-{n}"
    # yalnız üstüne siyah kutu çizilmiş (redaksiyon değil): metin ve görüntü verisi altında duruyor
    doc = fitz.open(str(src))
    for b in (metin, gorsel):
        doc[0].draw_rect(fitz.Rect(*b["kutu"]), color=(0, 0, 0), fill=(0, 0, 0))
    sahte = tmp_path / "sahte.pdf"
    doc.save(str(sahte))
    hata = DG.pdf(sahte, [metin, gorsel])
    assert any("metin" in h for h in hata) and any("görüntü" in h for h in hata), hata
    # gerçek redaksiyon (görüntü pikselleri de): temiz
    doc = fitz.open(str(src))
    for b in (metin, gorsel):
        doc[0].add_redact_annot(fitz.Rect(*b["kutu"]), fill=(0, 0, 0))
    doc[0].apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS)
    iyi = tmp_path / "iyi.pdf"
    doc.save(str(iyi))
    assert DG.pdf(iyi, [metin, gorsel]) == []
    # yer tutucu yazısı (kutunun içinde) kalan metin sayılmaz
    doc = fitz.open(str(iyi))
    doc[0].insert_text((10, 30), "[TC_NO]", fontsize=10)
    yt = tmp_path / "yt.pdf"
    doc.save(str(yt))
    assert DG.pdf(yt, [metin]) == []


@needs_ocr
def test_redaksiyon_dogrulamasi_basarisizsa_tamam_degil(tmp_path, monkeypatch):
    from bidr.mask import formats as F
    ws = tmp_path / "ws"
    _scanned_pdf(ws / "evidence/A/tarama.pdf", make_page())
    monkeypatch.setattr(F, "_redact_flags", lambda fitz_: {"images": fitz_.PDF_REDACT_IMAGE_NONE})
    rec = _rec(R.run(ws, engine="pymupdf", onbellek_kullan=False))
    assert rec["durum"] == "basarisiz" and rec.get("redaksiyon_dogrulama"), rec
    assert any("redaksiyon doğrulaması" in s for s in rec["kalan_sorunlar"])
    assert not (ws / "evidence-maskeli/A/tarama.pdf").exists()


# ---------------------------------------------------------------- eski biçimler (LibreOffice)

def test_libreoffice_yoksa_acik_mesaj_ve_pakete_girmez(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "soffice_path", lambda: None)
    ws = tmp_path / "ws"
    p = ws / "evidence/A/sunum.pptx"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"PK sentetik")
    rep = R.run(ws)
    rec = _rec(rep)
    assert rec["durum"] == "desteklenmiyor" and rec["onay_bekliyor"] and rec["elle_bakilmali"]
    assert "LibreOffice (soffice) bulunamadı" in rec["neden"]
    assert R.bekliyor(rec) and rep["ozet"]["kontrol_bekleyen_dosya"] == 1
    with pytest.raises(E.ConvertError, match="LibreOffice"):
        E.convert(p, tmp_path / "w")


def _sahte_soffice(tmp_path: Path) -> Path:
    """`soffice --headless --convert-to pdf --outdir D F` taklidi: D/<F adı>.pdf yazar, çağrıyı kaydeder."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    pdf = tmp_path / "ornek.pdf"
    _pdf_metin(pdf, "Sunum metni sentetik")
    log = tmp_path / "soffice.log"
    script = bindir / "soffice"
    script.write_text(
        f"#!{sys.executable}\n"
        "import sys, shutil, pathlib\n"
        f"open({str(log)!r}, 'a').write(' '.join(sys.argv[1:]) + '\\n')\n"
        "a = sys.argv[1:]\n"
        "if '--version' in a: print('LibreOffice 0.0 sahte'); sys.exit(0)\n"
        "out = pathlib.Path(a[a.index('--outdir') + 1]); src = pathlib.Path(a[-1])\n"
        f"shutil.copyfile({str(pdf)!r}, out / (src.stem + '.pdf'))\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return bindir


def test_libreoffice_donusumu_ve_onbellek(tmp_path, monkeypatch):
    bindir = _sahte_soffice(tmp_path)
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ.get("PATH", ""))
    E.soffice_version.cache_clear()
    ws = tmp_path / "ws"
    p = ws / "evidence/A/A.1/A.1.1/[2-OD2]. Sunum.pptx"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"PK sentetik sunum")
    rec = _rec(R.run(ws))
    assert rec["durum"] == "tamam" and rec["maskeli"] == "A/A.1/A.1.1/[2-OD2]. Sunum.pdf", rec
    assert "soffice" in rec["donusum"]
    assert (ws / "evidence-maskeli/A/A.1/A.1.1/[2-OD2]. Sunum.pdf").is_file()
    log = (tmp_path / "soffice.log").read_text(encoding="utf-8")
    assert "-env:UserInstallation=file://" in log and "--headless" in log and "--convert-to pdf" in log
    n = log.count("--convert-to")
    R.run(ws)                                                     # dönüşüm önbellekten
    assert (tmp_path / "soffice.log").read_text(encoding="utf-8").count("--convert-to") == n
    # teslim: maskeli kopya yeni uzantısıyla girer
    from bidr.teslim.run import Maske
    m = Maske(ws, ws / "evidence")
    yol, deger, _, _ = m.sec(p)
    assert yol is not None and yol.suffix == ".pdf" and deger == "tamam"
    E.soffice_version.cache_clear()
