"""m5 (teslim): panel uçtan uca denemesinde bulunanların sentetik regresyon testleri.

- kullanıcı çizimi metin katmanlı (born-digital) tutanakta öğrenilir ve aynı formun ikinci tutanağında öneri olur
  (kanıt modu önbellekli ve `--kaynak -w` ön işlemesi);
- "kapat" kararı verilen bölgenin kutusu içindeki mürekkep bileşenini tümüyle örter;
- `birak` kararı otomatik kapatılmış imza bölgesinde de geçerlidir.
Yalnız sentetik veri: uydurma adlar, çizilmiş eğriler."""
from __future__ import annotations

import io
import math
import random
from pathlib import Path

import pytest

PIL = pytest.importorskip("PIL")
fitz = pytest.importorskip("pymupdf")
from PIL import Image  # noqa: E402

import imza_sentetik as S  # noqa: E402
from bidr.mask import alan as AL  # noqa: E402
from bidr.mask import bolge as BG  # noqa: E402
from bidr.mask import inceleme as INC  # noqa: E402
from bidr.mask import ocr as O  # noqa: E402
from bidr.mask import onbellek as OB  # noqa: E402
from bidr.mask import raster as RA  # noqa: E402
from bidr.mask import run as R  # noqa: E402

needs_ocr = pytest.mark.skipif(not O.ocr_available(), reason="tesseract + tur/eng yok")
needs_np = pytest.mark.skipif(AL.np is None, reason="numpy yok")


@pytest.fixture(autouse=True)
def _temiz(monkeypatch):
    O._CACHE.clear()
    OB.ac(None)
    monkeypatch.delenv("BIDR_MASKE_WS", raising=False)
    RA._SABLON.clear()
    yield
    OB.ac(None)
    RA._SABLON.clear()


def _imza(page, x, y, w=100, h=26, seed=7):
    rnd = random.Random(seed)
    sh = page.new_shape()
    pts = [fitz.Point(x + t / 59 * w, y + h / 2 + math.sin(t / 59 * 13) * h / 2.4 + rnd.uniform(-2, 2))
           for t in range(60)]
    for a, b in zip(pts, pts[1:]):
        sh.draw_line(a, b)
    sh.finish(color=(0.05, 0.1, 0.5), width=1.4)
    sh.commit()


def tutanak(path: Path, adlar: tuple) -> None:
    """Metin katmanlı tablolu toplantı tutanağı (aynı form, farklı uydurma adlar)."""
    doc = fitz.open()
    p = doc.new_page()
    p.insert_text((72, 80), "TOPLANTI TUTANAGI (sentetik)", fontsize=14)
    satirlar = [("Ad Soyad", "Gorev", "Imza")] + [(a, g, "") for a, g in zip(adlar, ("Baskan", "Uye", "Raportor"))]
    x0, y0, cw, rh = 72, 120, [180, 140, 130], 40
    for i, row in enumerate(satirlar):
        x = x0
        for j, c in enumerate(row):
            r = fitz.Rect(x, y0 + i * rh, x + cw[j], y0 + (i + 1) * rh)
            p.draw_rect(r, color=(0, 0, 0), width=0.8)
            p.insert_text((x + 5, y0 + i * rh + 25), c, fontsize=10)
            if j == 2 and i > 0:
                _imza(p, x + 10, y0 + i * rh + 6, seed=i)
            x += cw[j]
    p.insert_text((72, 320), "Toplanti gundemdeki maddeleri gorusmus ve karara baglamistir.", fontsize=10)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    doc.close()


AD1 = ("Deneme Birinci", "Ornek Ikinci", "Sahte Ucuncu")
AD2 = ("Uydurma Dorduncu", "Kurgu Besinci", "Hayali Altinci")
KUTU = [74, 165, 250, 275]          # ad sütunu (üç kişi)


def _sablon_bolgeleri(rec):
    return [b for b in rec["bolgeler"] if b["kaynak"] == "sablon"]


@needs_np
def test_cizim_metin_katmanli_tutanakta_ogrenilir_ikincide_oneri(tmp_path):
    ws = tmp_path / "ws"
    r1, r2 = "B/B.1/B.1.1/[1-OD3]. Tutanak bir.pdf", "B/B.1/B.1.2/[1-OD3]. Tutanak iki.pdf"
    tutanak(ws / "evidence" / r1, AD1)
    tutanak(ws / "evidence" / r2, AD2)
    rep = R.run(ws, engine="pymupdf")                    # önbellekli: ikinci tutanak önbellekten gelmemeli
    assert all(not _sablon_bolgeleri(r) for r in rep["dosyalar"])
    c = INC.ciz(ws, r1, 1, KUTU, "sentetik")
    assert "uyari" not in c, c                          # metin katmanından öğrenildi (OCR'a muhtaç değil)
    rep = R.run(ws, engine="pymupdf")
    by = {r["dosya"]: r for r in rep["dosyalar"]}
    ikinci = _sablon_bolgeleri(by[r2])
    assert len(ikinci) == 1 and ikinci[0]["karar"] == BG.ONAY and "kullanıcının" in ikinci[0]["neden"], by[r2]
    k = ikinci[0]["kutu"]
    assert k[0] <= KUTU[0] + 15 and k[2] >= KUTU[2] - 15 and k[1] <= KUTU[1] + 10 and k[3] >= KUTU[3] - 10
    # öneri kendiliğinden kapatılmaz; dosya karar bekler, teslim kopyası çerçevesiz
    assert R.bekliyor(by[r2]) and by[r2]["teslim_kopya"]
    doc = fitz.open(str(ws / by[r2]["teslim_kopya"]))
    try:
        assert "Uydurma Dorduncu" in doc[0].get_text() and "ONAY BEKLIYOR" not in doc[0].get_text()
    finally:
        doc.close()
    # çizimin kendi belgesinde öneri yinelenmez (yeniden taramada da), dosya tamam
    assert not _sablon_bolgeleri(by[r1]) and by[r1]["durum"] == "tamam" and not R.bekliyor(by[r1]), by[r1]
    assert INC.bekleyenler(ws)["dosyalar"][1]["durum"] == "karar_bekliyor"
    # öneriye "kapat": sonraki koşuda kapatılır
    INC.karar(ws, ikinci[0]["id"], "kapat", "sentetik")
    rep = R.run(ws, engine="pymupdf")
    by = {r["dosya"]: r for r in rep["dosyalar"]}
    assert by[r2]["durum"] == "tamam" and not R.bekliyor(by[r2]), by[r2]
    doc = fitz.open(str(ws / "evidence-maskeli" / r2))
    try:
        assert "Uydurma Dorduncu" not in doc[0].get_text()
    finally:
        doc.close()


@needs_np
def test_kaynak_on_islemesi_sablon_bellegini_kullanir(tmp_path):
    from bidr.mask.kaynak import run_source
    ws, kaynak, kopya = tmp_path / "ws", tmp_path / "bolum", tmp_path / "maskeli"
    ws.mkdir()
    tutanak(kaynak / "B.1.1" / "tutanak-1.pdf", AD1)
    tutanak(kaynak / "B.1.2" / "tutanak-2.pdf", AD2)
    run_source(kaynak, kopya, engine="pymupdf", ws=ws)
    c = INC.ciz(ws, "B.1.1/tutanak-1.pdf", 1, KUTU, "sentetik")
    assert "uyari" not in c, c
    rap = run_source(kaynak, kopya, engine="pymupdf", ws=ws)
    by = {r["dosya"]: r for r in rap["dosyalar"]}
    assert len(_sablon_bolgeleri(by["B.1.2/tutanak-2.pdf"])) == 1, by["B.1.2/tutanak-2.pdf"]
    assert not _sablon_bolgeleri(by["B.1.1/tutanak-1.pdf"])
    import os
    assert "BIDR_MASKE_WS" not in os.environ                # ortam geri alındı


# ---------------------------------------------------------------- kapat kutusu mürekkebe genişler

def _el_yazisi_sayfasi(path: Path) -> None:
    """Taranmış (görüntü) sayfa: "Adi Soyadi:" etiketi, alt çizgi ve üstünde iri el yazısı benzeri dalga."""
    W, H = 1240, 1754                     # 150 dpi A4
    im = Image.new("RGB", (W, H), "white")
    from PIL import ImageDraw
    d = ImageDraw.Draw(im)
    d.text((150, 270), "Adi Soyadi:", fill=(0, 0, 0), font=S.font(28))
    d.line([(330, 310), (940, 310)], fill=(0, 0, 0), width=3)               # alt çizgi (form çizgisi)
    pts = [(350 + t * 5, 280 + math.sin(t / 3.0) * 18) for t in range(100)]   # y 262..298 px (≈ 126..143 pt)
    d.line(pts, fill=(25, 25, 60), width=4)
    b = io.BytesIO()
    im.save(b, format="PNG")
    doc = fitz.open()
    p = doc.new_page(width=595, height=842)
    p.insert_image(p.rect, stream=b.getvalue())
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    doc.close()


@needs_np
def test_kapat_kararli_kutu_murekkebi_tumuyle_orter(tmp_path):
    pdf = tmp_path / "d.pdf"
    _el_yazisi_sayfasi(pdf)
    f = 72 / 150
    ince = [350 * f, 276 * f, 845 * f, 285 * f]                       # yazının ortasından ince bant
    b = BG.yeni(1, ince, "imza", BG.KAPATILDI, "sayfanın üst bandı", "etiketsiz_aday", 0.7)
    b["insan"] = {"karar": "kapat"}
    otomatik = BG.yeni(1, list(ince), "imza", BG.KAPATILDI, "x", "etiketsiz_aday", 0.7)   # insan kararı yok
    kul = dict(BG.yeni(1, list(ince), "kullanici", BG.KAPATILDI, "x", "kullanici", 1.0), insan={"karar": "kapat"})
    doc = fitz.open(str(pdf))
    try:
        RA.pdf_kapat_genislet(doc[0], [b, otomatik, kul])
    finally:
        doc.close()
    k = b["kutu"]
    assert k[1] <= 262 * f and k[3] >= 298 * f and k[0] <= 348 * f and k[2] >= 846 * f, k
    assert k[3] < 310 * f - 0.5 or k[3] - 298 * f < 3           # alt çizgiye (form çizgisi) yayılmaz
    assert k[0] > 330 * f + 5 and k[2] < 940 * f - 5               # alt çizgi boyunca genişlemez
    assert k[1] >= ince[1] - 36 and "genişletildi" in b["neden"]
    assert otomatik["kutu"] == [round(v, 2) for v in ince] and kul["kutu"] == [round(v, 2) for v in ince]


@needs_np
def test_murekkep_kutusu_sinirli():
    im = Image.new("L", (400, 200), 255)
    from PIL import ImageDraw
    d = ImageDraw.Draw(im)
    d.rectangle([100, 20, 120, 180], fill=0)                      # çok uzun bileşen
    k = RA.murekkep_kutusu(im, (90, 90, 130, 100), 25)
    assert k[1] == 65 and k[3] == 125                             # kenar başına en çok 25 px
    assert RA.murekkep_kutusu(im, (300, 90, 340, 100), 25) == (300, 90, 340, 100)   # mürekkep yok


@needs_ocr
def test_kapat_karari_uctan_uca_genisletir(tmp_path):
    """Kanıt modu: imza önerisine "kapat" → maskeli kopyada dalganın mürekkebi kalmaz."""
    ws = tmp_path / "ws"
    rel = "C/C.1/[1-OD3]. Dilekce.pdf"
    _el_yazisi_sayfasi(ws / "evidence" / rel)
    rep = R.run(ws, engine="pymupdf", onbellek_kullan=False)
    rec = rep["dosyalar"][0]
    f = 72 / 150
    hedef = [350 * f, 262 * f, 845 * f, 298 * f]
    adaylar = [b for b in rec["bolgeler"] if b["karar"] != BG.KAPATILDI and BG.ortusme(b["kutu"], hedef) > 0.3]
    if not adaylar:
        pytest.skip("sentetik dalga bu ortamda bölge üretmedi")
    for b in adaylar:
        INC.karar(ws, b["id"], "kapat", "sentetik")
    rep = R.run(ws, engine="pymupdf", onbellek_kullan=False)
    doc = fitz.open(str(ws / "evidence-maskeli" / rel if (ws / "evidence-maskeli" / rel).is_file()
                        else ws / rep["dosyalar"][0]["teslim_kopya"]))
    try:
        pix = doc[0].get_pixmap(dpi=150, clip=fitz.Rect(*[hedef[0] - 2, hedef[1] - 2, hedef[2] + 2, hedef[3] + 2]))
    finally:
        doc.close()
    a = AL.np.asarray(Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")).astype(int)
    lacivert = ((a[:, :, 2] - a[:, :, 0]) > 15) & (a.sum(2) < 450) & (a.sum(2) > 60)
    assert int(lacivert.sum()) == 0


# ---------------------------------------------------------------- birak: kapatılmış imza

def test_birak_kapatilmis_imza_bolgesinde_gecerli(tmp_path):
    ws = tmp_path / "ws"
    rel = "A/A.1/[1-OD3]. Cizelge.pdf"
    S.vektor_cizelge(ws / "evidence" / rel, sayfa=1, satir=5)
    rec = R.run(ws, engine="pymupdf", onbellek_kullan=False)["dosyalar"][0]
    imza = [b for b in rec["bolgeler"] if b["tur"] == "imza" and b["karar"] == BG.KAPATILDI]
    assert imza and rec["durum"] == "tamam", rec
    for b in imza:
        d = INC.karar(ws, b["id"], "birak", "sentetik")                     # kabul edilir
        assert d["karar"] == "birak"
    rec2 = R.run(ws, engine="pymupdf", onbellek_kullan=False)["dosyalar"][0]
    by = {b["id"]: b for b in rec2["bolgeler"]}
    for b in imza:
        assert by[b["id"]]["karar"] == BG.BIRAKILDI and not by[b["id"]]["kapali"], by[b["id"]]
        assert by[b["id"]]["insan"]["karar"] == "birak"
    assert rec2["durum"] == "tamam" and not R.bekliyor(rec2) and not BG.onay_bekleyen(rec2["bolgeler"]), rec2
    # imza mürekkebi maskeli kopyada duruyor (karartılmadı)
    doc = fitz.open(str(ws / "evidence-maskeli" / rel))
    try:
        k = imza[0]["kutu"]
        pix = doc[0].get_pixmap(dpi=72, clip=fitz.Rect(*k))
    finally:
        doc.close()
    g = Image.open(io.BytesIO(pix.tobytes("png"))).convert("L")
    assert g.getextrema()[1] > 200                                          # siyah kutu değil
    # yeniden sorulmaz; tekrar "kapat" denebilir
    assert all(x["id"] not in {b["id"] for b in imza} for x in INC.bekleyenler(ws)["bolgeler"])
    INC.karar(ws, imza[0]["id"], "kapat", "sentetik")
    rec3 = R.run(ws, engine="pymupdf", onbellek_kullan=False)["dosyalar"][0]
    assert {b["id"]: b for b in rec3["bolgeler"]}[imza[0]["id"]]["karar"] == BG.KAPATILDI


def test_birak_desen_bulgusunda_reddedilir(tmp_path):
    ws = tmp_path / "ws"
    rel = "A/x.pdf"
    p = ws / "evidence" / rel
    p.parent.mkdir(parents=True)
    doc = fitz.open()
    pg = doc.new_page()
    pg.insert_text((72, 100), "E-posta: deneme.kisi@ornek.test", fontsize=11)
    doc.save(str(p))
    doc.close()
    rec = R.run(ws, engine="pymupdf", onbellek_kullan=False)["dosyalar"][0]
    b = next(b for b in rec["bolgeler"] if b["tur"] == "kisisel_veri")
    with pytest.raises(INC.IncelemeError, match="birak"):
        INC.karar(ws, b["id"], "birak")
