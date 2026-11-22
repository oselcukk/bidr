"""m5 ek iş (gerçek veri denemesi bulguları, sentetik): aşırı kapatma (en küçük yeterli maske), her açık onay
bölgesi dosyayı "karar bekliyor" yapar, arka plan görüntüsü, tik/paraf, renkli taranmış imza, kesik sütun
çizgisi, yinelenen neden. Yalnız sentetik veri."""
from __future__ import annotations

import io
import math
import random
from pathlib import Path

import pytest

PIL = pytest.importorskip("PIL")
fitz = pytest.importorskip("pymupdf")
from PIL import Image, ImageDraw  # noqa: E402

import imza_sentetik as S  # noqa: E402
from bidr.mask import alan as AL  # noqa: E402
from bidr.mask import ocr as O  # noqa: E402
from bidr.mask import onbellek as OB  # noqa: E402
from bidr.mask import raster as RA  # noqa: E402
from bidr.mask import run as R  # noqa: E402
from bidr.mask import yapi as Y  # noqa: E402
from bidr.mask.detect import MaskRules  # noqa: E402

needs_ocr = pytest.mark.skipif(not O.ocr_available(), reason="tesseract + tur/eng yok")


@pytest.fixture(autouse=True)
def _temiz():
    O._CACHE.clear()
    OB.ac(None)
    yield
    OB.ac(None)


def _siyah_alti_payi(ozgun: Path, maskeli: Path) -> float:
    """Özgün metin katmanı kelimelerinin (≥ 3 harf) kaçta kaçı maskeli kopyada siyah kutu altında (kelime
    kutusunun ≥ %50'si tam siyah)."""
    d0, d1 = fitz.open(str(ozgun)), fitz.open(str(maskeli))
    try:
        n = alt = 0
        for p0, p1 in zip(d0, d1):
            for w in p0.get_text("words"):
                if sum(c.isalpha() for c in w[4]) < 3:
                    continue
                n += 1
                pix = p1.get_pixmap(dpi=72, clip=fitz.Rect(w[:4]))
                g = Image.open(io.BytesIO(pix.tobytes("png"))).convert("L")
                h = g.histogram()
                if sum(h[:8]) >= 0.5 * max(1, sum(h)):
                    alt += 1
        return alt / max(1, n)
    finally:
        d0.close()
        d1.close()


# ---------------------------------------------------------------- 2. aşırı kapatma: en küçük yeterli maske

def _metinli_imzali_pdf(path: Path) -> None:
    """Metin katmanlı karar sayfası: karar paragrafı, ad/unvan satırları ve ad satırının üstünden geçen
    gömülü imza görüntüsü (metinle örtüşen imza)."""
    doc = fitz.open()
    p = doc.new_page()
    y = 90
    for _ in range(6):
        S.metin_yaz(p, (72, y), "Kurul gündemdeki maddeyi görüşmüş ve oy birliğiyle kabul etmiştir.", 11)
        y += 18
    S.metin_yaz(p, (90, 600), "Prof. Dr. Deneme Birinci", 11)
    S.metin_yaz(p, (90, 618), "Bölüm Başkanı", 11)
    p.insert_image(fitz.Rect(80, 575, 260, 615), stream=S._imza_png(w=360, h=80, seed=3))
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    doc.close()


def test_metin_katmanli_sayfada_metin_siyah_altinda_kalmaz(tmp_path):
    src, dst = tmp_path / "s.pdf", tmp_path / "o.pdf"
    _metinli_imzali_pdf(src)
    rec = R.mask_and_check(src, dst, MaskRules(), "pymupdf")
    assert rec["kapatma_olcumu"]["siyah_altinda"] == 0, rec["kapatma_olcumu"]
    assert _siyah_alti_payi(src, dst) <= 0.05
    doc = fitz.open(str(dst))
    try:
        t = doc[0].get_text().replace("\xa0", " ")
    finally:
        doc.close()
    assert "oy birliğiyle" in t and "Bölüm Başkanı" in t


@needs_ocr
def test_taranmis_tutanakta_ad_okunur_imza_cogu_kapali(tmp_path):
    src, bos, dst = tmp_path / "s.pdf", tmp_path / "b.pdf", tmp_path / "o.pdf"
    S.tutanak(src, ortusen=True)
    S.tutanak(bos, ortusen=True, imzali=False)
    rec = R.mask_and_check(src, dst, MaskRules(), "pymupdf")
    assert rec["kapatma_olcumu"]["siyah_altinda"] == 0, rec
    oneri = [b for b in rec["bolgeler"] if b["kaynak"] == "imza_metin" and b["karar"] == "onay_bekliyor"]
    assert all(not b["kapali"] for b in oneri) and R.bekliyor(rec) == bool(oneri), rec
    # basılı metnin siyah altında kalan payı: imzasız kopyanın koyu pikselleri maskeli kopyada siyah blok mu
    a, m = S.sayfa_goruntuleri(bos)[0].convert("L"), S.sayfa_goruntuleri(dst)[0].convert("L").resize(
        S.sayfa_goruntuleri(bos)[0].size)
    ad, md = a.tobytes(), m.tobytes()
    W = a.width
    metin = [i for i, v in enumerate(ad) if v < 100]
    # siyah blok: pikselin 2 px çevresi de siyah (basılı harf kenarı beyaza değer)
    def blok(i):
        return all(0 <= j < len(md) and md[j] < 20 for j in (i - 2, i + 2, i - 2 * W, i + 2 * W))
    kapali = sum(1 for i in metin if blok(i))
    assert kapali / max(1, len(metin)) <= 0.05, kapali / max(1, len(metin))
    # ad satırının içinden geçen vuruş ayrılamıyorsa satır bandı öneri olur (kaçan yalnız onlar)
    assert S.kacirilan(src, bos, dst, esik=0.5)[1] <= len(oneri)
    assert S.kacirilan(src, bos, dst, esik=0.5)[0] == 2


def test_cok_buyuk_otomatik_kapatma_oneri_olur():
    """Sayfanın %30'undan büyük otomatik imza bölgesi kapatılmaz, öneri olur (ölçülür)."""
    I = Y.I
    W, H = int(8.27 * I), int(11.69 * I)
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    rnd = random.Random(5)
    pts = [(60 + t * 6, 300 + rnd.uniform(-1, 1) * 300 + math.sin(t / 3) * 200) for t in range(110)]
    d.line(pts, fill=(10, 10, 10), width=2)
    w = O.Word("İmza:", 96, 20, 280, 60, 295, (1, 1, 1, 1))
    bol = Y.goruntu_bolgeleri(img, [w], I)
    buyuk = [b for b in bol if (b.kutu[2] - b.kutu[0]) * (b.kutu[3] - b.kutu[1]) > Y.ASIRI_ALAN * W * H]
    assert all(b.karar != Y.KAPATILDI for b in buyuk), [(b.kutu, b.karar, b.neden) for b in bol]


def test_asiri_kapatma_olcumu():
    o = RA.asiri_kapatma([(0, 0, 10, 10), (50, 50, 60, 60), (100, 100, 110, 110)],
                         [(0, 0, 70, 70)], [(45, 45, 65, 65)], 200 * 200)
    assert o == {"basili_kelime": 3, "siyah_altinda": 1, "en_buyuk_kutu_payi": 0.1225, "siyah_alan_payi": 0.1225}
    oz = R.kapatma_ozeti({1: o, 2: dict(o, siyah_altinda=0)})
    assert oz["siyah_altinda"] == 1 and oz["sayfalar"] == [1]


# ---------------------------------------------------------------- 1. her açık onay bölgesi: karar bekliyor

def test_acik_onay_bolgesi_dosyayi_bekletir():
    rec = {"durum": "tamam", "onay_bekleyen": 1}
    assert R.bekliyor(rec)
    assert not R.bekliyor({"durum": "tamam"}) and not R.bekliyor({"durum": R.ELLE, "onay_bekleyen": 2})


# ---------------------------------------------------------------- 3. arka plan görüntüsü

def test_arka_plan_goruntusu_murekkep_aramasindan_cikar():
    kesin = [O.Word("AKTS", 100, 100 + 40 * i, 120, 160 + 40 * i, 135, (1, 1, i, 1)) for i in range(6)]
    assert Y._arka_plan((50, 50, 1000, 1200), True, kesin, (1240, 1754))       # üstünde metin var
    assert Y._arka_plan((0, 0, 1240, 1200), False, [], (1240, 1754))            # sayfanın büyük kısmı, imza değil
    assert not Y._arka_plan((800, 1500, 1100, 1600), True, kesin, (1240, 1754))  # küçük imza görüntüsü


# ---------------------------------------------------------------- 4. tik / paraf

def test_tik_suzgeci_parafi_birakmaz():
    I = Y.I
    tik = [0, 0, int(0.35 * I), int(0.3 * I), int(0.9 * 0.35 * I * 2)]          # tek vuruş, seyrek
    assert Y._tik_mi(tik, [tik])
    kucuk = [0, 0, int(0.2 * I), int(0.2 * I), 30]
    assert Y._tik_mi(kucuk, [kucuk])
    paraf = [0, 0, int(0.4 * I), int(0.3 * I), 120]
    parcalar = [[0, 0, int(0.2 * I), int(0.3 * I), 60], [int(0.2 * I), 0, int(0.4 * I), int(0.3 * I), 60]]
    assert not Y._tik_mi(paraf, parcalar)                                        # çok vuruşlu: paraf
    yogun = [0, 0, int(0.4 * I), int(0.3 * I), 400]
    assert not Y._tik_mi(yogun, [yogun])                                         # yoğun karalama: paraf
    assert not Y._tik_mi([0, 0, int(0.6 * I), 10, 50], [])                       # tik boyunu aşıyor


# ---------------------------------------------------------------- 5. renkli taranmış imza fotoğraf değil

def test_renkli_taranmis_imza_fotograf_sayilmaz():
    im = Image.new("RGB", (400, 140), (246, 244, 238))
    d = ImageDraw.Draw(im)
    rnd = random.Random(1)
    for k in range(3):
        pts = [(20 + t * 4, 70 + math.sin(t / 4 + k) * 40 + rnd.uniform(-3, 3)) for t in range(90)]
        d.line(pts, fill=(30, 50, 170), width=3)
    im = im.resize((200, 70), Image.BILINEAR).resize((400, 140), Image.BICUBIC)   # kenar yumuşatma
    b = io.BytesIO()
    im.save(b, format="JPEG", quality=55)                                        # sıkıştırma gürültüsü
    im = Image.open(io.BytesIO(b.getvalue())).convert("RGB")
    assert not Y._fotograf(im, (0, 0, 400, 140))
    foto = Image.new("RGB", (200, 200))
    foto.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)) for _ in range(200 * 200)])
    assert Y._fotograf(foto, (0, 0, 200, 200))


# ---------------------------------------------------------------- 7. kesik dikey çizgiler

def test_kesik_dikey_cizgiler_zincirlenir():
    I = Y.I
    yat = [(y, 50, 650) for y in (100, 140, 200, 260, 320)]
    dik = []
    for x in (50, 250, 450, 650):
        dik += [(x, 100, 118), (x + 1, 123, 200), (x, 204, 320)]             # başlık hücresinde kesik çizgi
    assert len(Y.dik_zincirle(dik)) == 4
    tabs = Y.tablolar(yat, dik)
    assert len(tabs) == 1 and len(tabs[0].xs) == 4 and len(tabs[0].ys) == 5
    assert Y._zincir_sonu(tabs[0].dik, 250, 100) >= 318
    assert Y._zincir_sonu([(250, 100, 118), (250, 140, 200)], 250, 100, 6) == 118  # uzun boşluk: kopar
    assert 0.1 * I >= 7


# ---------------------------------------------------------------- 8. yinelenen neden

def test_tasma_nedeni_yinelenmez():
    assert Y._tasma_nedeni("İmza sütunu") == "İmza sütunu alanından taşan mürekkep"
    assert Y._tasma_nedeni("İmza sütunundan taşan mürekkep") == "İmza sütunundan taşan mürekkep"
    assert Y._tasma_nedeni("İmza etiketi alanından taşan mürekkep; renkli") == "İmza etiketi alanından taşan mürekkep"
    assert Y._tasma_nedeni("İmza bloğu: unvan satırı") == "İmza bloğu alanından taşan mürekkep"


# ---------------------------------------------------------------- 6. etiket alanı mürekkebe daraltılır

def test_etiket_alani_yalniz_murekkebi_kapatir():
    img = Image.new("RGB", (1240, 600), "white")
    d = ImageDraw.Draw(img)
    d.line([(260, 232), (1100, 232)], fill="black", width=2)                    # alt çizgi (alan)
    pts = [(300 + i * 7, 215 + (7 if i % 2 else -7)) for i in range(30)]           # el yazısı ~300..503
    d.line(pts, fill=(20, 20, 70), width=4)
    W = O.Word
    words = [W("Kimlik", 96, 100, 200, 190, 230, (1, 1, 1, 1)), W("No:", 96, 200, 200, 250, 230, (1, 1, 1, 1))]
    fs = AL.find_fields(img, words)
    assert fs and all(f.karar == "kapatildi" for f in fs), fs
    for f in fs:
        assert f.box[0] >= 255 and f.box[2] <= 560, f.box                     # çizginin tamamı değil, mürekkep
