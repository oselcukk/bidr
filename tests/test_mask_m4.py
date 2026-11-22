"""m4 düzeltme turu: gerçek denemede bulunan gerilemelerin sentetik regresyon testleri ve maskeleme arayüzü
komutları (`ciz`, `sayfa`, `karar … sil`, `bolgeler --json`, ön işleme raporu). Yalnız sentetik veri:
çizilmiş tablolar, el yazısı benzeri eğriler (tests/imza_sentetik.py), uydurma adlar."""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

PIL = pytest.importorskip("PIL")
fitz = pytest.importorskip("pymupdf")
from PIL import Image, ImageDraw  # noqa: E402

import elyazi_synth as ES  # noqa: E402
import imza_sentetik as S  # noqa: E402
from bidr.cli import main  # noqa: E402
from bidr.mask import alan as AL  # noqa: E402
from bidr.mask import bolge as BG  # noqa: E402
from bidr.mask import dogrula as DG  # noqa: E402
from bidr.mask import formats as F  # noqa: E402
from bidr.mask import inceleme as INC  # noqa: E402
from bidr.mask import ocr as O  # noqa: E402
from bidr.mask import onbellek as OB  # noqa: E402
from bidr.mask import raster as RA  # noqa: E402
from bidr.mask import run as R  # noqa: E402
from bidr.mask import yapi as Y  # noqa: E402
from bidr.mask.detect import MaskRules  # noqa: E402

needs_ocr = pytest.mark.skipif(not O.ocr_available(), reason="tesseract + tur/eng yok")
I = Y.I


@pytest.fixture(autouse=True)
def _temiz():
    O._CACHE.clear()
    OB.ac(None)
    yield
    OB.ac(None)


def _png(img) -> bytes:
    b = io.BytesIO()
    img.save(b, format="PNG")
    return b.getvalue()


def _render(path: Path, sayfa: int = 1, dpi: int = 72):
    doc = fitz.open(str(path))
    try:
        return Image.open(io.BytesIO(doc[sayfa - 1].get_pixmap(dpi=dpi).tobytes("png"))).convert("RGB")
    finally:
        doc.close()


# ---------------------------------------------------------------- 1. siyah kapatma en üstte

def _gorsel_pdf(path: Path) -> None:
    im = Image.new("RGB", (600, 300), "white")
    d = ImageDraw.Draw(im)
    for x in range(20, 580, 14):
        d.line([(x, 20), (x + 9, 280)], fill=(25, 45, 200), width=3)       # mavi mürekkep
    doc = fitz.open()
    page = doc.new_page(width=600, height=300)
    page.insert_image(page.rect, stream=_png(im))
    doc.save(str(path))
    doc.close()


def _beyaz_yama(w: int, h: int) -> bytes:
    return _png(Image.new("RGB", (w, h), "white"))


def test_yama_siyah_kutunun_ustune_basilmaz(tmp_path):
    src, dst = tmp_path / "a.pdf", tmp_path / "b.pdf"
    _gorsel_pdf(src)
    doc = fitz.open(str(src))
    page = doc[0]
    siyah = dict(BG.yeni(1, [100, 50, 300, 250], "imza", BG.KAPATILDI, "imza", "imza_blogu", 0.9), _etiket="[İMZA]")
    icinde = dict(BG.yeni(1, [120, 80, 280, 200], "imza", BG.KAPATILDI, "imza", "imza_tasmasi", 0.8),
                  _yama=_beyaz_yama(160, 120), _etiket="[İMZA]")                 # tamamen siyahın içinde
    kismi = dict(BG.yeni(1, [250, 100, 450, 200], "imza", BG.KAPATILDI, "imza", "imza_tasmasi", 0.8),
                 _yama=_beyaz_yama(200, 100), _etiket="[İMZA]")                  # siyahla az örtüşür
    siyahlar, labels = [], []
    F._kapat_turu(fitz, page, [siyah, icinde, kismi], siyahlar, labels, F._redact_flags(fitz))
    # sonraki turda gelen yama da önceki siyahın üstüne basılmaz
    sonra = dict(BG.yeni(1, [150, 120, 260, 160], "imza", BG.KAPATILDI, "imza", "imza_tasmasi", 0.8),
                 _yama=_beyaz_yama(110, 40), _etiket="[İMZA]")
    F._kapat_turu(fitz, page, [sonra], siyahlar, labels, F._redact_flags(fitz))
    doc.save(str(dst))
    doc.close()
    assert "_yama" not in icinde and "_yama" not in sonra and "siyah kapatıldı" in icinde["neden"]
    im = _render(dst)
    siyah_kutu = im.crop((102, 52, 298, 248)).convert("L")
    assert siyah_kutu.getextrema()[1] < 40, "siyah kutunun içinde beyaz dikdörtgen / soluk iz kaldı"
    disari = im.crop((302, 102, 448, 198))                    # kısmi yamanın siyah dışı: beyaz (mürekkep silindi)
    assert min(disari.convert("L").getextrema()) > 200


def test_renk_ayirma_yalniz_yapisal_imza_bolgesinde():
    assert "etiketsiz_aday" not in Y.RENK_AYIRMA_KAYNAK and "imza_sutunu" in Y.RENK_AYIRMA_KAYNAK


@needs_ocr
def test_mavi_el_yazisi_icerik_metni_yamalanmaz(tmp_path):
    """Etiketsiz mavi el yazısı içerik (tutanakta karar metni) basılı metnin üstünde: yama yok, kutu açık."""
    img = S._bos()
    d = ImageDraw.Draw(img)
    y = 230
    for t in S._GOVDE * 2:
        d.text((120, y), t, fill="black", font=S.font(30))
        y += 55
    S.imza_ciz(d, 160, 700, w=330, h=80, color=S.MAVI, seed=5)        # içerik metni üstünde mavi el yazısı
    p = tmp_path / "t.pdf"
    S.pdf_goruntu_sayfalari(p, [img])
    rec = R.mask_and_check(p, tmp_path / "o.pdf", MaskRules(), "pymupdf")
    assert not any("renkli mürekkep ayrıldı" in b["neden"] for b in rec.get("bolgeler") or []), rec["bolgeler"]


# ---------------------------------------------------------------- 2. yeniden tarama aynı kutuyu eklemez

def test_icinde_payi_ve_dogrulama_ayni_kutudaki_geri_basmalar(tmp_path):
    assert F._icinde_payi([10, 10, 20, 20], [[0, 0, 30, 30]]) == 1.0
    assert F._icinde_payi([10, 10, 60, 20], [[0, 0, 30, 30]]) < 0.9
    src = tmp_path / "a.pdf"
    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    S.metin_yaz(page, (20, 60), "Ayşe Demir Prof. Dr.", 11)
    page.add_redact_annot(fitz.Rect(15, 45, 200, 70), fill=(0, 0, 0))
    page.apply_redactions()
    S.metin_yaz(page, (20, 60), "Ayşe Demir", 6)            # birinci bölgenin geri basması
    S.metin_yaz(page, (90, 60), "Prof. Dr.", 6)             # aynı kutudaki ikinci bölgenin geri basması
    doc.save(str(src))
    doc.close()
    a = dict(BG.yeni(1, [15, 45, 200, 70], "imza", BG.KAPATILDI, "imza", "gomulu_gorsel", 0.9, "Ayşe Demir"), id="x-s1-1")
    b = dict(BG.yeni(1, [80, 45, 200, 70], "imza", BG.KAPATILDI, "imza", "imza_tasmasi", 0.8, "Prof. Dr."), id="x-s1-2")
    assert DG.pdf(src, [a, b]) == []
    assert DG.pdf(src, [dict(a, geri_basilan=None), dict(b, geri_basilan=None)])       # izin yoksa kalan metin


def test_vektor_cizelge_tasan_imza_tek_bolge_ve_tamam(tmp_path):
    """Gömülü imza görüntüsü kapatılıp ad/unvan geri basılınca yeniden tarama aynı kutuyu yeni kimlikle eklemez;
    redaksiyon doğrulaması geri basılan yazıyı kalan metin saymaz."""
    p = tmp_path / "v.pdf"
    S.vektor_cizelge(p, sayfa=1, satir=6, tasan=(3,))
    rec = R.mask_and_check(p, tmp_path / "o.pdf", MaskRules(), "pymupdf")
    kap = [b for b in rec["bolgeler"] if b.get("kapali")]
    for i, x in enumerate(kap):
        for y in kap[i + 1:]:
            if x["sayfa"] == y["sayfa"]:
                assert F._icinde_payi(y["kutu"], [x["kutu"]]) < 0.9 or F._icinde_payi(x["kutu"], [y["kutu"]]) < 0.9 \
                    or x["kaynak"] != y["kaynak"], (x, y)
    assert not rec.get("redaksiyon_dogrulama"), rec
    assert rec["durum"] == "tamam", rec


# ---------------------------------------------------------------- 3. imza sütunu geometrisi

def _w(t, x0, y0, x1, y1):
    return O.Word(t, 95, x0, y0, x1, y1, (1, 1, int(y0), 1))


def test_imza_sutunu_baslik_cizgilerinden_ve_tablo_sonunda_biter():
    """Üstte katılım tablosu (Sıra | Ad | Unvan | İmza), hemen altında başka sütun düzenli gündem tablosu:
    gündem tablosunun İmza sütununa düşen ara çizgisi sütunu daraltmaz, sütun katılım tablosunda biter."""
    xs = [50, 100, 300, 450, 560]
    yat = [(y, 50, 560) for y in (100, 130, 160, 190, 220)]               # katılım: başlık + 3 satır
    yat += [(y, 50, 560) for y in (250, 300, 350)]                          # gündem (30 px boşluk)
    dik = [(x, 100, 220) for x in xs]
    dik += [(x, 250, 350) for x in (50, 200, 500, 560)]                     # gündemde 500: İmza sütununun içinde
    tabs = Y.tablolar(yat, dik)
    assert tabs
    t = next(t for t in tabs if t.ys[0] <= 100)
    words = [_w("Sıra", 55, 105, 90, 125), _w("Adı", 110, 105, 150, 125), _w("Unvanı", 310, 105, 380, 125),
             _w("İmza", 480, 105, 530, 125)]
    hit = Y.imza_sutunu(t, words)
    assert hit is not None
    c, r, hx = hit
    k = Y.sutun_kutusu(t, c, r, hx)
    assert abs(k[0] - 450) <= 3 and abs(k[2] - 560) <= 3, k          # başlık hücresinin iki çizgisi
    assert abs(k[1] - 130) <= 3 and abs(k[3] - 220) <= 8, k          # gündem tablosuna inmez


def test_vektor_hucre_cizgileri_zincirlenir():
    segs = [(450, 100, 130), (450, 130, 160), (450, 160, 190), (450, 240, 300)]
    assert Y._zincir_sonu(segs, 450, 100) == 190


# ---------------------------------------------------------------- 4. dönmüş sayfa

@needs_ocr
def test_doksan_derece_donmus_tutanakta_imza_sutunu(tmp_path):
    p0 = tmp_path / "duz.pdf"
    S.taranmis_cizelge(p0, sayfa=1, satir=8)
    img = S.sayfa_goruntuleri(p0)[0].transpose(Image.Transpose.ROTATE_90)     # yatay taranmış
    if O.sayfa_yonu(img) is None:
        pytest.skip("tesseract OSD (osd dil verisi) yok")
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    page.insert_image(page.rect, stream=_png(img))
    p = tmp_path / "donuk.pdf"
    doc.save(str(p))
    doc.close()
    rec = R.mask_and_check(p, tmp_path / "o.pdf", MaskRules(), "pymupdf")
    sutun = [b for b in rec["bolgeler"] if b["kaynak"] == "imza_sutunu" and b["karar"] == "kapatildi"]
    assert sutun, rec["bolgeler"]
    # özgün (yatay) sayfa koordinatı: dönmüş sayfada sütun yatay bir şerittir, sayfanın içinde
    k = sutun[0]["kutu"]
    assert 0 <= k[0] < k[2] <= 842 and 0 <= k[1] < k[3] <= 595 and (k[2] - k[0]) > (k[3] - k[1]), k


# ---------------------------------------------------------------- 5. el yazısı dilekçe

def test_birlesik_ocr_cizgisiz_kelimeleri_ekler():
    a = O.Word("Kimlik", 90, 0, 0, 50, 10, (1, 1, 1, 1))
    b = O.Word("Kimlik", 92, 1, 0, 51, 10, (1, 1, 1, 1))
    c = O.Word("Ayşe", 90, 100, 0, 140, 10, (1, 1, 1, 1))
    out = RA._birlesik([a], [b, c])
    assert len(out) == 2 and out[1].text == "Ayşe" and out[1].line[0] == "c"


@needs_ocr
def test_tablolu_el_yazisi_dilekce_kimlik_ve_eposta_kapatilir(tmp_path):
    """Izgaralı dilekçe: etiket hücresi | el yazısı değer. Etiket alanı (kimlik no, e-posta) kapatılır; sayfa
    "taranamadı" olmaz (desen/etiket/kalite özgün görüntünün OCR'ından)."""
    Fm = ES.Form()
    Fm.text(420, 100, "DILEKCE")
    ys = [220, 300, 380, 460, 540]
    for y in ys:
        Fm.hline(80, 1100, y)
    for x in (80, 460, 1100):
        Fm.vline(x, 220, 540)
    Fm.text(100, 240, "Adı Soyadı")
    ES.scribble(Fm.d, 500, 238, 300, seed=1)
    Fm.text(100, 320, "T.C. Kimlik No")
    tc = ES.digits(Fm.d, "10000000146", 500, 320, seed=2)
    Fm.text(100, 400, "E-posta")
    ep = ES.scribble(Fm.d, 500, 398, 420, seed=3)
    Fm.text(100, 480, "Bölümü")
    ES.scribble(Fm.d, 500, 478, 260, seed=4)
    y = 620
    for t in ("Bölümünüzde öğrenim görmekteyim. Gereğinin yapılmasını", "saygılarımla arz ederim."):
        Fm.text(100, y, t)
        y += 60
    p = tmp_path / "dilekce.pdf"
    S.pdf_goruntu_sayfalari(p, [Fm.img])
    rec = R.mask_and_check(p, tmp_path / "o.pdf", MaskRules(), "pymupdf")
    alan = [b for b in rec["bolgeler"] if b["tur"] == "el_yazisi_alan" and b.get("kapali")]
    s = 72 / 150
    for v in (tc, ep):
        vp = [c * s for c in v]
        assert any(BG.ortusme(b["kutu"], vp) >= 0.6 for b in alan), (v, rec["bolgeler"])
    assert not rec.get("taranamadi"), rec


# ---------------------------------------------------------------- 6. onay bölgeleri inceleme kopyasında çizilir

def test_onay_bolgesi_inceleme_kopyasinda_cerceveli(tmp_path):
    p = tmp_path / "y.pdf"
    S.metin_pdf_gorselli(p, etiket=False, e_imza=False)
    dst = tmp_path / "o.pdf"
    rec = R.mask_and_check(p, dst, MaskRules(), "pymupdf")
    onay = [b for b in rec["bolgeler"] if b["karar"] == "onay_bekliyor" and not b.get("kapali")]
    assert onay and rec["elle_bakilmali"], rec
    doc = fitz.open(str(dst))
    try:
        cizim = [d for d in doc[0].get_drawings() if d.get("color") and abs(d["color"][0] - 1) < 0.01
                 and abs(d["color"][1] - R.ONAY_RENK[1]) < 0.02]
        assert cizim, "onay bölgesi çerçevesi yok"
        assert "ONAY BEKLIYOR" in doc[0].get_text()
    finally:
        doc.close()


# ---------------------------------------------------------------- 7. imza olmayan görsel [GÖRSEL]

def test_gorsel_etiketi_notr():
    b = Y.Bolge((0, 0, 1, 1), "kapatildi", "x", "gomulu_gorsel", 0.9, gorsel=True)
    assert Y.etiket_yazisi(b) == "[GÖRSEL]"
    b.geri_basilan = "Ayşe Demir"
    assert Y.etiket_yazisi(b) == "Ayşe Demir [GÖRSEL]"
    assert Y.etiket_yazisi(Y.Bolge((0, 0, 1, 1), "kapatildi", "x", "imza_blogu", 0.9)) == "[İMZA]"


def _foto(w=320, h=200, seed=3):
    import random
    rnd = random.Random(seed)
    im = Image.new("RGB", (w, h))
    px = im.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = ((x * 3 + rnd.randint(0, 60)) % 256, (y * 5 + rnd.randint(0, 60)) % 256,
                        (x + y + rnd.randint(0, 90)) % 256)
    return im


def test_unvan_yakinindaki_fotograf_imza_sayilmaz(tmp_path):
    p = tmp_path / "cv.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    y = 120
    for t in S._GOVDE * 3:
        S.metin_yaz(page, (60, y), t, 11)
        y += 22
    page.insert_image(fitz.Rect(360, 600, 480, 680), stream=_png(_foto()))
    S.metin_yaz(page, (370, 700), "Prof. Dr. Ayşe Demir", 11)
    S.metin_yaz(page, (370, 716), "Bölüm Başkanı", 11)
    doc.save(str(p))
    doc.close()
    dst = tmp_path / "o.pdf"
    rec = R.mask_and_check(p, dst, MaskRules(), "pymupdf")
    assert not [b for b in rec.get("bolgeler") or [] if b["kaynak"] == "gomulu_gorsel"], rec["bolgeler"]
    doc = fitz.open(str(dst))
    try:
        assert "[İMZA]" not in doc[0].get_text()
    finally:
        doc.close()


# ---------------------------------------------------------------- kural a: OCR'dan ad → kapalı + onay

@needs_ocr
def test_ocr_adli_ortusen_imza_kapali_ve_onayda(tmp_path):
    src, bos, dst = tmp_path / "s.pdf", tmp_path / "b.pdf", tmp_path / "o.pdf"
    S.tutanak(src, ortusen=True)
    S.tutanak(bos, ortusen=True, imzali=False)
    rec = R.mask_and_check(src, dst, MaskRules(), "pymupdf")
    onay = [b for b in rec["bolgeler"] if b["karar"] == "onay_bekliyor"]
    assert onay and all(b["kapali"] and b["geri_basilan"] is None and "geri basma" in b["neden"] for b in onay), onay
    assert rec["elle_bakilmali"] and S.kacirilan(src, bos, dst)[1] == 0        # kutu kapalı: kaçırma yok


# ---------------------------------------------------------------- kural b: rakam dizisi

def test_rakam_dizisi_basili_sayfada_aranmaz():
    tw = [O.Word(f"k{i}", 100.0, 0, i * 10, 50, i * 10 + 8, (1, 1, i, 1)) for i in range(30)]
    assert not RA.rakam_dizisi_gerekli(tw)                                   # metin katmanı
    good = [O.Word(f"kelime{i}", 95, 0, i * 10, 50, i * 10 + 8, (1, 1, i, 1)) for i in range(80)]
    assert not RA.rakam_dizisi_gerekli(good)                                 # güvenle OCR'lanan basılı sayfa
    assert RA.rakam_dizisi_gerekli(good[:10])
    Fm = ES.form_etiketsiz(0)
    assert not [r for r in AL.el_yazisi_bolgeleri(Fm.img, Fm.words, rakam=False) if r["kaynak"] == "rakam_dizisi"]


def test_harf_okunan_dizi_duser():
    Fm = ES.form_etiketsiz(0)
    v = Fm.vals["tc_no"]
    harf = [O.Word("Antalyalı", 70, v[0], v[1], (v[0] + v[2]) / 2, v[3], (9, 1, 1, 1)),
            O.Word("öğrenci", 70, (v[0] + v[2]) / 2, v[1], v[2], v[3], (9, 1, 1, 1))]
    assert AL._harf_okunan(v, harf)
    regs = AL.el_yazisi_bolgeleri(Fm.img, Fm.words + harf)
    assert not [r for r in regs if r["kaynak"] == "rakam_dizisi"], regs


# ---------------------------------------------------------------- kural c: paragraf ve tik

def test_el_yazisi_paragraf_satirlari():
    bant = [(100, 300 + 45 * i, 100 + int(4.5 * I), 300 + 45 * i + 30) for i in range(4)]
    assert set(bant) <= Y._el_yazisi_paragraf(bant)
    imzalar = [(100, 300, 280, 360), (600, 300, 780, 360)]                  # yan yana iki imza: paragraf değil
    assert not Y._el_yazisi_paragraf(imzalar)


@needs_ocr
def test_el_yazisi_paragraf_ve_tik_aday_olmaz(tmp_path):
    img = S._bos()
    d = ImageDraw.Draw(img)
    d.text((120, 120), "TOPLANTI TUTANAGI", fill="black", font=S.font(38))
    y = 230
    for t in S._GOVDE:
        d.text((120, y), t, fill="black", font=S.font(30))
        y += 55
    for i in range(5):                                                       # el yazısı karar metni paragrafı
        ES.scribble(d, 130, 700 + 70 * i, 900, h=40, seed=i, color=(30, 30, 30))
    d.line([(900, 1300), (915, 1318), (945, 1280)], fill=(30, 30, 30), width=3)   # tik
    p = tmp_path / "t.pdf"
    S.pdf_goruntu_sayfalari(p, [img])
    rec = R.mask_and_check(p, tmp_path / "o.pdf", MaskRules(), "pymupdf")
    onay = [b for b in rec.get("bolgeler") or [] if b["karar"] == "onay_bekliyor" and b["tur"] == "imza"]
    assert not onay, onay


# ---------------------------------------------------------------- kural d: fotoğraf / çok aday

@needs_ocr
def test_fotografta_tek_sayfa_onayi(tmp_path):
    foto = _foto(1200, 900, seed=7)
    d = ImageDraw.Draw(foto)
    for i in range(4):
        S.imza_ciz(d, 100 + 250 * (i % 2), 500 + 150 * (i // 2), w=200, h=60, seed=40 + i)
    p = tmp_path / "afis.jpg"
    foto.save(p, quality=92)
    rec = R.mask_and_check(p, tmp_path / "o.jpg", MaskRules(), "pymupdf")
    imza = [b for b in rec.get("bolgeler") or [] if b["tur"] == "imza" and b["karar"] == "onay_bekliyor"]
    assert len(imza) <= 1 and all(b["kaynak"] == "etiketsiz_sayfa" for b in imza), imza


@needs_ocr
def test_ondan_cok_etiketsiz_aday_tek_bolge(tmp_path):
    img = S._bos()
    d = ImageDraw.Draw(img)
    y = 160
    for t in S._GOVDE:
        d.text((120, y), t, fill="black", font=S.font(30))
        y += 55
    n = 0
    for r in range(4):
        for c in range(3):
            S.imza_ciz(d, 120 + 360 * c, 600 + 260 * r, w=230, h=70, seed=60 + n)
            n += 1
    p = tmp_path / "cok.pdf"
    S.pdf_goruntu_sayfalari(p, [img])
    rec = R.mask_and_check(p, tmp_path / "o.pdf", MaskRules(), "pymupdf")
    imza = [b for b in rec.get("bolgeler") or [] if b["tur"] == "imza" and b["karar"] == "onay_bekliyor"]
    assert len(imza) == 1 and imza[0]["kaynak"] == "etiketsiz_sayfa", imza


# ---------------------------------------------------------------- kural e: web çıktısı

def _web_pdf(path: Path, imza_etiketi: bool) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    S.metin_yaz(page, (30, 20), "22.11.2026 14:05   Duyurular - Örnek Üniversitesi", 8)
    S.metin_yaz(page, (30, 830), "https://www.ornek.edu.tr/duyurular/sayfa 1/1", 8)
    y = 120
    for t in S._GOVDE * 2:
        S.metin_yaz(page, (60, y), t, 11)
        y += 22
    page.insert_text((60, 400), "Ayrıntılar için bağlantıya tıklayın: www.ornek.edu.tr/belge", fontsize=11,
                     color=(0, 0, 0.9))
    page.draw_line((60, 402), (330, 402), color=(0, 0, 0.9), width=0.6)
    page.insert_image(fitz.Rect(360, 600, 520, 650), stream=S._imza_png(320, 100, seed=7))
    if imza_etiketi:
        S.metin_yaz(page, (300, 630), "İmza:", 11)
    doc.save(str(path))
    doc.close()


def test_web_ciktisi_tespiti_ve_etiketsiz_gorsel(tmp_path):
    p = tmp_path / "web.pdf"
    _web_pdf(p, imza_etiketi=False)
    doc = fitz.open(str(p))
    try:
        assert RA.web_ciktisi(doc[0])
    finally:
        doc.close()
    rec = R.mask_and_check(p, tmp_path / "o.pdf", MaskRules(), "pymupdf")
    assert not rec.get("bolgeler") and rec["durum"] == "tamam", rec
    p2 = tmp_path / "web2.pdf"
    _web_pdf(p2, imza_etiketi=True)
    rec2 = R.mask_and_check(p2, tmp_path / "o2.pdf", MaskRules(), "pymupdf")
    assert [b for b in rec2["bolgeler"] if b["kaynak"] == "gomulu_gorsel" and b["karar"] == "kapatildi"], rec2


# ---------------------------------------------------------------- kural f: karar tablosu / akan metin

def test_yalniz_yatay_cizgili_tablo_tablo_sayilir():
    yat = [(100 + 60 * i, 50, 50 + 5 * I) for i in range(4)]
    assert Y._yatay_tablolar(yat) and not Y._yatay_tablolar(yat[:2])


@needs_ocr
def test_karar_tablosundaki_unvan_satiri_imza_bandi_degil(tmp_path):
    img = S._bos()
    d = ImageDraw.Draw(img)
    f = S.font(28)
    d.text((120, 120), "KARAR TABLOSU", fill="black", font=S.font(36))
    ys = [260 + 110 * i for i in range(6)]
    for y in ys:
        d.line([(100, y), (1140, y)], fill="black", width=2)
    satir = ["Ders programının güncellenmesine oy birliği ile karar verildi ve kabul edildi.",
             "Üye",
             "Laboratuvar esaslarının yeniden düzenlenmesine oy birliği ile karar verildi."]
    y = 270
    for t in satir * 2:
        d.text((120, y), t, fill="black", font=f)
        y += 36
    ES.scribble(d, 200, 296, 300, h=30, seed=9, color=(30, 30, 30))            # satır içinde el yazısı not
    p = tmp_path / "k.pdf"
    S.pdf_goruntu_sayfalari(p, [img])
    rec = R.mask_and_check(p, tmp_path / "o.pdf", MaskRules(), "pymupdf")
    assert not [b for b in rec.get("bolgeler") or [] if b["kaynak"] == "imza_blogu"], rec["bolgeler"]


# ---------------------------------------------------------------- önbellek sürüm anahtarı

def test_kural_surumu_onbellek_anahtarinda(monkeypatch):
    a = R.aday_anahtari("0" * 64, MaskRules(), "pymupdf", {}, None, "pdf")
    monkeypatch.setattr(R, "KURAL_SURUM", R.KURAL_SURUM + 1)
    assert R.aday_anahtari("0" * 64, MaskRules(), "pymupdf", {}, None, "pdf") != a
    assert R.KURAL_SURUM >= 3 and "kaynak" in R._KOD_MODULLERI


# ---------------------------------------------------------------- arayüz komutları

def _ws_vektor(tmp_path: Path) -> tuple[Path, str]:
    ws = tmp_path / "ws"
    rel = "A/A.1/[1-OD3]. Cizelge.pdf"
    S.vektor_cizelge(ws / "evidence" / rel, sayfa=1, satir=5)
    return ws, rel


def _js(capsys):
    return json.loads(capsys.readouterr().out)


def test_ciz_sayfa_sil_ve_bolgeler_json(tmp_path, capsys):
    ws, rel = _ws_vektor(tmp_path)
    R.run(ws, engine="pymupdf", onbellek_kullan=False)
    # sayfa: PNG + sayfa sayısı/boyutu
    out = tmp_path / "s1.png"
    assert main(["maskele", "sayfa", "-w", str(ws), rel, "--sayfa", "1", "--dpi", "72", "-o", str(out), "--json"]) == 0
    s = _js(capsys)
    assert s["sayfa_sayisi"] == 1 and s["genislik"] == 595 and s["yukseklik"] == 842
    assert Image.open(out).size == (595, 842)
    # ciz: kullanıcı bölgesi (başlık yazısının üstü)
    assert main(["maskele", "ciz", "-w", str(ws), rel, "--sayfa", "1", "--kutu", "45,45,330,70",
                 "--kim", "sentetik", "--json"]) == 0
    c = _js(capsys)
    assert c["id"].endswith("-s1-k1") and c["kaynak"] == "kullanici" and c["kapali"]
    j = INC.bekleyenler(ws)
    assert any(b["id"] == c["id"] and b.get("uygulandi") is False for b in j["tum_bolgeler"])
    R.run(ws, engine="pymupdf", onbellek_kullan=False)
    rep = json.loads((ws / R.REPORT).read_text(encoding="utf-8"))
    rec = rep["dosyalar"][0]
    kb = next(b for b in rec["bolgeler"] if b["id"] == c["id"])
    assert kb["karar"] == "kapatildi" and rec["durum"] == "tamam", rec
    masked = ws / "evidence-maskeli" / rel
    doc = fitz.open(str(masked))
    try:
        assert "Katılım" not in doc[0].get_text()                      # gerçek redaksiyon: metin silindi
    finally:
        doc.close()
    # bolgeler --json: bütün bölgeler, belge kimliği, dosya bilgisi
    main(["maskele", "bolgeler", "-w", str(ws), "--json"])
    j = _js(capsys)
    assert j["mod"] == "kanit"
    d = j["dosyalar"][0]
    assert d["durum"] == "tamam" and d["sayfa_sayisi"] == 1 and d["belge_kimligi"] == rec["sha256"]
    alanlar = {"id", "dosya", "belge_kimligi", "sayfa", "kutu", "tur", "karar", "neden", "kaynak", "guven", "kapali"}
    assert j["tum_bolgeler"] and all(alanlar <= set(b) for b in j["tum_bolgeler"])
    assert any(b["kaynak"] == "imza_sutunu" and b["karar"] == "kapatildi" for b in j["tum_bolgeler"])
    # sil: yalnız kullanıcı bölgesi
    otomatik = next(b["id"] for b in j["tum_bolgeler"] if b["kaynak"] != "kullanici")
    assert main(["maskele", "karar", "-w", str(ws), otomatik, "sil"]) == 2
    capsys.readouterr()
    assert main(["maskele", "karar", "-w", str(ws), c["id"], "sil"]) == 0
    R.run(ws, engine="pymupdf", onbellek_kullan=False)
    rep = json.loads((ws / R.REPORT).read_text(encoding="utf-8"))
    assert not any(b["id"] == c["id"] for b in rep["dosyalar"][0]["bolgeler"])
    doc = fitz.open(str(ws / "evidence-maskeli" / rel))
    try:
        assert "Katılım" in doc[0].get_text()
    finally:
        doc.close()


def test_ciz_desteklenmeyen_bicim_ve_sayfa_disi(tmp_path, capsys):
    ws, rel = _ws_vektor(tmp_path)
    (ws / "evidence/A/not.txt").write_text("deneme", encoding="utf-8")
    R.run(ws, engine="pymupdf", onbellek_kullan=False)
    assert main(["maskele", "ciz", "-w", str(ws), "A/not.txt", "--sayfa", "1", "--kutu", "1,1,5,5"]) == 2
    assert main(["maskele", "ciz", "-w", str(ws), rel, "--sayfa", "3", "--kutu", "1,1,50,50"]) == 2
    assert "sayfa yok" in capsys.readouterr().err


def test_donmus_sayfada_kutu_gorunen_koordinatta(tmp_path):
    ws = tmp_path / "ws"
    rel = "A/d.pdf"
    p = ws / "evidence" / rel
    p.parent.mkdir(parents=True)
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    S.metin_yaz(page, (60, 100), "Döndürülmüş sayfa deneme metni", 12)
    page.set_rotation(90)
    doc.save(str(p))
    doc.close()
    R.run(ws, engine="pymupdf", onbellek_kullan=False)
    c = INC.ciz(ws, rel, 1, [10, 20, 110, 60], "sentetik")
    assert c["kutu"] == [10, 20, 110, 60]
    d = BG.kararlar_yukle(ws)[c["id"]]
    assert d["kutu"] != [10, 20, 110, 60]                                     # iç (döndürülmemiş) koordinat
    R.run(ws, engine="pymupdf", onbellek_kullan=False)
    j = INC.bekleyenler(ws)
    b = next(x for x in j["tum_bolgeler"] if x["id"] == c["id"])
    assert all(abs(u - v) < 0.6 for u, v in zip(b["kutu"], [10, 20, 110, 60])), b
    assert j["dosyalar"][0]["sayfalar"][0]["genislik"] == 842


def test_on_isleme_kaynak_raporu_karar_ve_yukle_tasinir(tmp_path, capsys):
    """`bidr file` öncesi: `--kaynak -w WS` çalışma alanına rapor yazar; bolgeler/ciz/sayfa/yukle onu okur;
    kararlar ve elle maskelenmiş sürüm aynı sha256 ile sonraki kanıt maskelemesine taşınır."""
    ws, kaynak, kopya = tmp_path / "ws", tmp_path / "bolum", tmp_path / "maskeli"
    ws.mkdir()
    S.vektor_cizelge(kaynak / "cizelge.pdf", sayfa=1, satir=5)
    S.metin_pdf_gorselli(kaynak / "yazi.pdf", etiket=False, e_imza=False)
    rc = main(["maskele", "--kaynak", str(kaynak), "--out", str(kopya), "-w", str(ws)])
    capsys.readouterr()
    assert rc in (0, 1) and (ws / INC.KAYNAK_RAPOR).is_file()
    main(["maskele", "bolgeler", "-w", str(ws), "--json"])
    j = _js(capsys)
    assert j["mod"] == "kaynak" and {d["dosya"] for d in j["dosyalar"]} == {"cizelge.pdf", "yazi.pdf"}
    yazi = next(d for d in j["dosyalar"] if d["dosya"] == "yazi.pdf")
    assert yazi["durum"] == "karar_bekliyor"
    onay = next(b for b in j["bolgeler"] if b["dosya"] == "yazi.pdf")
    assert main(["maskele", "karar", "-w", str(ws), onay["id"], "kapat"]) == 0
    capsys.readouterr()
    sha = next(d for d in j["dosyalar"] if d["dosya"] == "cizelge.pdf")["belge_kimligi"]
    assert main(["maskele", "ciz", "-w", str(ws), sha[:12], "--sayfa", "1", "--kutu", "45,45,330,70", "--json"]) == 0
    cid = _js(capsys)["id"]
    out = tmp_path / "p.png"
    assert main(["maskele", "sayfa", "-w", str(ws), "cizelge.pdf", "-o", str(out), "--json"]) == 0
    assert _js(capsys)["sayfa_sayisi"] == 1 and out.is_file()
    # kaynak modu yeniden: kararlar uygulanır
    main(["maskele", "--kaynak", str(kaynak), "--out", str(kopya), "-w", str(ws)])
    capsys.readouterr()
    j = INC.bekleyenler(ws)
    assert next(d for d in j["dosyalar"] if d["dosya"] == "yazi.pdf")["durum"] == "tamam", j["dosyalar"]
    assert any(b["id"] == cid and b["karar"] == "kapatildi" for b in j["tum_bolgeler"])
    # ön işlemede elle maskelenmiş sürüm (belge kimliğiyle)
    elle = tmp_path / "elle.pdf"
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    doc.save(str(elle))
    doc.close()
    ysha = next(d for d in j["dosyalar"] if d["dosya"] == "yazi.pdf")["belge_kimligi"]
    assert main(["maskele", "yukle", "-w", str(ws), ysha, str(elle)]) == 0
    assert (kopya / "yazi.pdf").read_bytes() == elle.read_bytes()
    # bidr file sonrası kanıt modu: aynı içerik → aynı karar, aynı elle sürüm
    ev = ws / "evidence" / "B"
    ev.mkdir(parents=True)
    (ev / "Cizelge.pdf").write_bytes((kaynak / "cizelge.pdf").read_bytes())
    (ev / "Yazi.pdf").write_bytes((kaynak / "yazi.pdf").read_bytes())
    rep = R.run(ws, engine="pymupdf", onbellek_kullan=False)
    by = {r["dosya"]: r for r in rep["dosyalar"]}
    assert any(b["id"] == cid and b["karar"] == "kapatildi" for b in by["B/Cizelge.pdf"]["bolgeler"])
    assert by["B/Yazi.pdf"]["durum"] == R.ELLE, by["B/Yazi.pdf"]


def test_kullanici_ciziminden_sablon_onerisi_kendiliginden_kapatilmaz(tmp_path):
    """`ciz` ile öğrenilen şablon bölgesi aynı formun başka kopyasında yalnız `onay_bekliyor` öneri olur;
    `karar … sil` öğrenilen örneği de unutur."""
    from bidr.mask import sablon as SB
    mem = SB.SablonBellegi.calisma_alani(tmp_path)
    A = ES.form_sablon(0)
    iz = SB.parmak_izi(A.words, A.img.size[0], A.img.size[1], AL.Yapi(A.img, AL._page_h(A.words, A.img.size[1]), A.words))
    assert mem.ogren(iz, [A.vals["tc_no"]], kaynak="abcd1234-s1-k1", oneri=True)
    mem.kaydet()
    B = ES.affine(ES.form_sablon(1, deger="karalama"), scale=0.95, deg=1.2, dx=30, dy=-18)
    rb = AL.el_yazisi_bolgeleri(B.img, B.words, dosya="d", sablonlar=SB.SablonBellegi.calisma_alani(tmp_path))
    sb = [r for r in rb if r["kaynak"] == "sablon"]
    assert len(sb) == 1 and sb[0]["karar"] == "onay_bekliyor" and "kullanıcının" in sb[0]["neden"], rb
    mem2 = SB.SablonBellegi.calisma_alani(tmp_path)
    assert mem2.unut("abcd1234-s1-k1") == 1
