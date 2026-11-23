"""m7: kapanmayan sorunların kökten çözümü (gerçek veri denemesi v5 bulguları; yalnız sentetik veri).

1 sessiz imza kaçağı yok (zarfa girmeyen iz, satır bandından geçen vuruş: öneri) · 2 ad koruması: tablo kuralı (otomatik
kapatma yalnız İmza sütununda), yazı satırı yapısı (OCR güveninden bağımsız basılı satır bandı), ad satırı çıkarımı ·
3 renk ayırma yaması siyahla örtüşünce korumalı yedek · 4 ölçüm: yazı benzeri satır parçası, görsel zemin ·
5 onay yükü: el yazısı satır kelimesi aday değil, paraf sütunu tek öneri, web çıktısında etiketsiz aday yok ·
ek: zarf bağlı vuruşu bölge dışına izler. Genel ölçüt: ad metninin siyah altı payı ≤ %5, sessiz kaçak 0, dilekçede ≤ 5 öneri."""
from __future__ import annotations

import pytest

PIL = pytest.importorskip("PIL")
fitz = pytest.importorskip("pymupdf")
from PIL import Image, ImageDraw  # noqa: E402

import asiri_sentetik as A  # noqa: E402
import imza_sentetik as S  # noqa: E402
import m7_sentetik as M  # noqa: E402
from bidr.mask import formats as F  # noqa: E402
from bidr.mask import imza as IM  # noqa: E402
from bidr.mask import ocr as O  # noqa: E402
from bidr.mask import onbellek as OB  # noqa: E402
from bidr.mask import raster as RA  # noqa: E402
from bidr.mask import run as R  # noqa: E402
from bidr.mask import satir as SA  # noqa: E402
from bidr.mask import yapi as Y  # noqa: E402

needs_ocr = pytest.mark.skipif(not O.ocr_available(), reason="tesseract + tur/eng yok")
I = Y.I


@pytest.fixture(autouse=True)
def _temiz():
    O._CACHE.clear()
    OB.ac(None)
    yield
    OB.ac(None)


def _w(text, x0, y0, x1, y1, line=1, conf=96.0):
    return O.Word(text, conf, x0, y0, x1, y1, (1, 1, line, 1))


def _murekkep(img, ppi=150):
    return SA.temiz_murekkep(IM.hazirla(img, [], ppi).raw_ink)


# ---------------------------------------------------------------- yazı satırı yapısı (satir.py)

def test_basili_satir_ocrsiz_bulunur():
    img = Image.new("RGB", (1240, 400), "white")
    d = ImageDraw.Draw(img)
    d.text((120, 100), "Prof. Dr. Ayşe Demir toplantıya katılmıştır.", fill="black", font=S.font(30))
    S.imza_ciz(d, 200, 220, w=300, h=90, seed=4)
    rows = SA.satirlar(_murekkep(img))
    basili = [r for r in rows if r.basili]
    assert len(basili) == 1 and basili[0].n >= 6, [(r.kutu, r.n, r.basili) for r in rows]
    x0, y0, x1, y1 = basili[0].kutu
    assert x0 <= 90 and x1 >= 440 and 60 <= y0 <= 80 and y1 <= 95        # yalnız metin satırı; imza satır değil
    assert not any(r.kutu[1] > 120 for r in rows)


def test_el_yazisi_satiri_bulunur_imza_satir_degil():
    img = Image.new("RGB", (1240, 500), "white")
    d = ImageDraw.Draw(img)
    M.el_yazisi_satir(d, 100, 120, 8, 17, M.EL_MAVI, seed=3, x_son=1100)
    M.el_yazisi_satir(d, 100, 180, 8, 17, M.EL_MAVI, seed=4, x_son=1100)
    S.imza_ciz(d, 700, 300, w=260, h=80, color=M.EL_MAVI, seed=9)
    rows = SA.satirlar(_murekkep(img))
    assert len([r for r in rows if r.n >= 5 and r.kutu[3] < 140]) == 2, [(r.kutu, r.n) for r in rows]
    assert not any(r.kutu[1] > 180 for r in rows)                        # imza: satır yok
    ms = Y._metin_satirlari_yapi(rows)
    kelime = SA.parcalar(max(rows, key=lambda r: r.n))[2]
    assert Y._satir_ici(kelime, ms)
    assert not Y._satir_ici((466, 200, 640, 254), ms)                    # imza kutusu satır içi değil


def test_satir_bandi_ustunden_gecen_vurusla_uzar():
    """İmza adın baş harflerinin üstünden geçip onları büyük bileşene katar: bant, kalan harflerden satırın
    bütününe uzar; yalnız vuruşun olduğu yere (yazı yok) uzamaz."""
    img = M.ortusen_blok()[0]
    ink = _murekkep(img)
    rows = [r for r in SA.satirlar(ink) if r.basili and 880 <= r.kutu[1] <= 895 and r.kutu[0] < 300]
    assert rows, "ad satırının serbest harfleri satır olarak bulunamadı"
    bt = SA.genislet(ink, rows[0])
    assert bt[0] <= 130 and bt[2] >= 280, bt                              # "Prof. Dr. Ayşe Demir": 100..285 (100 ppi)
    assert bt[0] >= 80 and bt[2] <= 300, bt


def test_ust_satir_cikarimi():
    """Unvan satırının üstündeki ad satırı, imza bütün harflerinin üstünden geçse de satır düzeninden bulunur;
    üstünde yalnız imza olan unvan satırında satır uydurulmaz."""
    ink = _murekkep(A.gri_tarama(M.ortusen_blok(tam=True)[0]))
    us = SA.ust_satir(ink, (104, 918, 237, 933))
    assert us is not None and 880 <= us[1] <= 895 and us[2] - us[0] >= 60, us
    img = Image.new("RGB", (1240, 500), "white")
    d = ImageDraw.Draw(img)
    d.text((150, 300), "Bölüm Başkanı", fill="black", font=S.font(30))
    S.imza_ciz(d, 160, 200, w=260, h=80, seed=5)
    assert SA.ust_satir(_murekkep(img), (100, 203, 235, 222)) is None


# ---------------------------------------------------------------- 1. sessiz kaçak yok

def test_zarfa_girmeyen_kucuk_izler_artik_olarak_doner():
    img = Image.new("RGB", (900, 300), "white")
    d = ImageDraw.Draw(img)
    S.imza_ciz(d, 60, 100, w=200, h=70, seed=3)
    for i in range(4):                                                    # büyük vuruştan ayrı kısa kancalar
        d.line([(340 + 50 * i, 160), (347 + 50 * i, 145), (355 + 50 * i, 158)], fill=S.SIYAH_MUREKKEP, width=3)
    zarf, sayac = Y._murekkep_zarfi(img, 1.0, (40, 80, 560, 200), [], 14.0)
    assert len(zarf) == 1 and zarf[0][2] < 300
    assert len(sayac.artik) >= 3, sayac.artik
    assert all(a[0] >= 320 for a in sayac.artik)


def test_gurultu_artik_uretmez():
    g = A.gri_tarama(Image.new("RGB", (600, 300), "white"))
    zarf, sayac = Y._murekkep_zarfi(g, 1.0, (20, 20, 580, 280), [], 14.0)
    assert zarf == [] and sayac.artik == []


def test_zarf_bagli_vurusu_bolge_disina_izler():
    """Ek: bölge sınırında kesilen vuruşun kuyruğu açık kalmaz (bağlı bileşen bütünüyle alınır, en çok `ZARF_YAY`)."""
    img = Image.new("RGB", (900, 400), "white")
    d = ImageDraw.Draw(img)
    S.imza_ciz(d, 100, 120, w=320, h=90, seed=6)
    zarf, _ = Y._murekkep_zarfi(img, 1.0, (80, 100, 300, 230), [], 14.0)
    assert zarf and max(z[2] for z in zarf) >= 300 + 0.9 * Y.ZARF_YAY, zarf      # bölge 300'de bitiyor; vuruş ~430'a kadar
    assert max(z[2] for z in zarf) <= 300 + Y.ZARF_YAY + 1


def test_imza_etiketinde_kucuk_izler_oneri_olur():
    img = Image.new("RGB", (int(8.27 * I), int(6 * I)), "white")
    d = ImageDraw.Draw(img)
    S.imza_ciz(d, 160, 300, w=110, h=40, seed=5, width=2)
    for i in range(3):
        d.line([(300 + 22 * i, 332), (306 + 22 * i, 318), (313 + 22 * i, 330)], fill=S.SIYAH_MUREKKEP, width=2)
    bol = Y.goruntu_bolgeleri(img, [_w("İmza:", 90, 315, 140, 332)], I)
    kap = [b for b in bol if b.kapat]
    assert kap, [(b.kaynak, b.karar, b.neden) for b in bol]
    kutular = [p for b in bol if b.karar != Y.BIRAKILDI for p in (b.parcalar or [b.kutu])]
    for i in range(3):                                                    # her küçük iz ya kapalı ya öneride
        iz = (300 + 22 * i, 318, 313 + 22 * i, 332)
        assert any(IM._overlap(iz, k) > 0.5 * Y._area(iz) for k in kutular), (iz, [(b.kaynak, b.kutu) for b in bol])


@needs_ocr
@pytest.mark.parametrize("gri", [False, True])
def test_parcali_imzada_sessiz_kacak_yok(tmp_path, gri):
    r = M.olc(tmp_path, "parca", M.parcali_imza_blok(), gri=gri)
    assert r["sessiz"] == 0 and r["ad_siyah"] <= 0.05, {k: r[k] for k in ("sessiz", "acik", "ad_siyah", "oneri")}
    assert r["oneri"] <= 2
    assert any(b["kaynak"] == "imza_blogu" and b["kapali"] for b in r["rec"]["bolgeler"])    # büyük vuruş kapalı


# ---------------------------------------------------------------- 2. ad koruması

def _tablo(el_yazisi=True):
    """100 ppi ızgaralı tablo: Adı Soyadı | Unvanı | İmza; ad/unvan el yazısı, imzalardan biri unvan hücresine taşar."""
    W, H = int(8.27 * I), int(7 * I)
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    cols, y0, rh = (40, 300, 520, 790), 100, 66
    for i in range(6):
        d.line([(cols[0], y0 + i * rh), (cols[-1], y0 + i * rh)], fill="black", width=1)
    for x in cols:
        d.line([(x, y0), (x, y0 + 5 * rh)], fill="black", width=1)
    ws = [_w("Adı", 50, 122, 80, 137, 1), _w("Soyadı", 85, 122, 140, 137, 1), _w("Unvanı", 310, 122, 370, 137, 1),
          _w("İmza", 530, 122, 570, 137, 1)]
    adlar = []
    for j in range(4):
        yy = y0 + (j + 1) * rh
        cx = M.el_yazisi_kelime(d, 52, yy + 46, 5, 12, M.EL_SIYAH, 300 + j, 2)
        cx = M.el_yazisi_kelime(d, cx + 14, yy + 46, 6, 12, M.EL_SIYAH, 330 + j, 2)
        ux = M.el_yazisi_kelime(d, 312, yy + 46, 5, 12, M.EL_SIYAH, 360 + j, 2)
        adlar += [(48, yy + 20, cx + 2, yy + 52), (308, yy + 20, ux + 2, yy + 52)]
        if j == 1:
            S.imza_ciz(d, 400, yy + 10, w=300, h=46, seed=20 + j, width=2)          # unvan hücresine taşan
        else:
            S.imza_ciz(d, 560, yy + 10, w=190, h=44, seed=20 + j, width=2)
    return img, ws, cols, adlar


def test_tabloda_otomatik_kapatma_yalniz_imza_sutununda():
    img, ws, cols, adlar = _tablo()
    bol = Y.goruntu_bolgeleri(img, ws, I, kesin=ws)
    kap = [b for b in bol if b.kapat]
    assert any(b.kaynak == "imza_sutunu" for b in kap), [(b.kaynak, b.karar, b.neden) for b in bol]
    for b in kap:                                                         # hiçbir otomatik kapatma ad/unvan sütununda değil
        for p in (b.parcalar or [b.kutu]):
            assert p[0] >= cols[2] - 2, (b.kaynak, p, b.neden)
    # unvan hücresine taşan vuruş sessiz düşmez: tek toplu öneri, yalnız taşan zarf parçalarıyla
    tasma = [b for b in bol if b.karar == Y.ONAY and b.kaynak == "imza_tasmasi"]
    assert len(tasma) == 1 and tasma[0].parcalar, [(b.kaynak, b.karar, b.neden) for b in bol]
    assert all(p[2] <= cols[2] + 2 and p[0] >= 380 for p in tasma[0].parcalar), tasma[0].parcalar
    # el yazısı ad/unvan kelimeleri öneri de olmaz (İmza sütunlu tabloda imzanın yeri İmza sütunudur)
    oneri = [b for b in bol if b.karar == Y.ONAY]
    assert len(oneri) == 1, [(b.kaynak, b.kutu, b.neden) for b in oneri]
    for a in adlar:
        assert all(IM._overlap(a, p) < 0.2 * Y._area(a) for b in oneri for p in (b.parcalar or [b.kutu])
                   if a[0] < 300), a


def test_imza_hucresi_bossa_oteki_hucredeki_imza_sessiz_dusmez():
    """İmza sütunlu tabloda imza yanlış hücreye (unvan) atılmış, İmza hücresi boş: aday süzülmez, öneri olur."""
    W, H = int(8.27 * I), int(7 * I)
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    cols, y0, rh = (40, 300, 520, 790), 100, 66
    for i in range(5):
        d.line([(cols[0], y0 + i * rh), (cols[-1], y0 + i * rh)], fill="black", width=1)
    for x in cols:
        d.line([(x, y0), (x, y0 + 4 * rh)], fill="black", width=1)
    ws = [_w("Adı", 50, 122, 80, 137, 1), _w("Unvanı", 310, 122, 370, 137, 1), _w("İmza", 530, 122, 570, 137, 1)]
    for j in range(3):
        yy = y0 + (j + 1) * rh
        M.el_yazisi_kelime(d, 52, yy + 46, 6, 12, M.EL_SIYAH, 300 + j, 2)
        if j == 1:
            S.imza_ciz(d, 320, yy + 10, w=170, h=44, seed=20 + j, width=2)         # unvan hücresinde; İmza hücresi boş
        else:
            S.imza_ciz(d, 560, yy + 10, w=190, h=44, seed=20 + j, width=2)
    bol = Y.goruntu_bolgeleri(img, ws, I, kesin=ws)
    yanlis = (320, y0 + 2 * rh + 10, 490, y0 + 2 * rh + 54)
    ilgili = [b for b in bol if IM._overlap(b.kutu, yanlis) > 0.3 * Y._area(yanlis)]
    assert ilgili and all(b.karar == Y.ONAY for b in ilgili), [(b.kaynak, b.karar, b.kutu, b.neden) for b in bol]
    assert not any(b.kapat and IM._overlap(p, yanlis) > 0 for b in bol for p in (b.parcalar or [b.kutu]))


def test_karma_baslikli_sutunda_basili_ad_satiri_acik_kalir():
    """Başlık "Adı Soyadı / İmza": ad da imza hücresinde. OCR adı okuyamasa da (kelime verilmedi) basılı ad satırı
    yapıdan bulunur ve hücre kapatılırken açık kalır; imza kapanır."""
    W, H = int(8.27 * I), int(6 * I)
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    cols, y0, rh = (40, 380, 790), 100, 90
    for i in range(4):
        d.line([(cols[0], y0 + i * rh), (cols[-1], y0 + i * rh)], fill="black", width=1)
    for x in cols:
        d.line([(x, y0), (x, y0 + 3 * rh)], fill="black", width=1)
    ws = [_w("Görevi", 50, 132, 110, 147, 1), _w("Adı", 390, 132, 420, 147, 1), _w("Soyadı", 425, 132, 480, 147, 1),
          _w("/", 485, 132, 490, 147, 1), _w("İmza", 495, 132, 535, 147, 1)]
    adlar = []
    for j in range(2):
        yy = y0 + (j + 1) * rh
        d.text((392, yy + 8), "Prof. Dr. Ayşe Demir Kaya", fill="black", font=S.font(15))
        adlar.append((392, yy + 10, 580, yy + 24))
        S.imza_ciz(d, 520, yy + 34, w=200, h=44, seed=50 + j, width=2)
    bol = Y.goruntu_bolgeleri(img, ws, I, kesin=ws)
    sutun = [b for b in bol if b.kaynak == "imza_sutunu" and b.kapat]
    assert sutun, [(b.kaynak, b.karar, b.neden) for b in bol]
    kapali = [p for b in bol if b.kapat for p in (b.parcalar or [b.kutu])]
    for a in adlar:
        assert sum(IM._overlap(a, p) for p in kapali) <= 0.1 * Y._area(a), (a, kapali)
    for j in range(2):                                                    # imza kapalı
        im = (530, y0 + (j + 1) * rh + 40, 700, y0 + (j + 1) * rh + 72)
        assert sum(IM._overlap(im, p) for p in kapali) >= 0.9 * Y._area(im), (im, kapali)


def test_imzasiz_tabloda_ad_basligi_sutunu_aday_olmaz_paraflar_tek_oneri():
    W, H = int(8.27 * I), int(9 * I)
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    cols, y0, rh = (40, 330, 600, 790), 260, 60
    for i in range(9):
        d.line([(cols[0], y0 + i * rh), (cols[-1], y0 + i * rh)], fill="black", width=1)
    for x in cols:
        d.line([(x, y0), (x, y0 + 8 * rh)], fill="black", width=1)
    ws = [_w("Adı", 50, 282, 80, 297, 1), _w("Soyadı", 85, 282, 140, 297, 1), _w("Ders", 340, 282, 380, 297, 1),
          _w("Onay", 610, 282, 650, 297, 1)]
    for j in range(7):
        yy = y0 + (j + 1) * rh
        cx = M.el_yazisi_kelime(d, 52, yy + 42, 5, 12, M.EL_SIYAH, 400 + j, 2)
        M.el_yazisi_kelime(d, cx + 14, yy + 42, 6, 12, M.EL_SIYAH, 430 + j, 2)
        M.paraf_ciz(d, 650, yy + 12, boy=30, seed=500 + j)
    bol = Y.goruntu_bolgeleri(img, ws, I, kesin=ws)
    assert not any(b.kapat for b in bol)
    oneri = [b for b in bol if b.karar == Y.ONAY]
    assert len(oneri) == 1 and len(oneri[0].parcalar) == 7, [(b.kaynak, b.kutu, b.neden) for b in oneri]
    assert all(p[0] >= 600 and Y._area(p) <= 0.004 * W * H for p in oneri[0].parcalar)
    assert "paraf" in oneri[0].neden


@needs_ocr
@pytest.mark.parametrize("ad,uret,gri", [
    ("tut_mavi", lambda: M.el_yazisi_tutanak(), False),
    ("tut_siyah_gri", lambda: M.el_yazisi_tutanak(renk=M.EL_SIYAH), True),
    ("blok_siyah", lambda: M.ortusen_blok(), False),
    ("blok_tam_gri", lambda: M.ortusen_blok(tam=True), True),
    ("blok_mavi", lambda: M.ortusen_blok(renk=S.MAVI, tam=True), False),
])
def test_genel_olcut_ad_korunur_sessiz_kacak_yok(tmp_path, ad, uret, gri):
    """Genel ölçüt: basılı + el yazısı ad/unvan metninin siyah altında kalan oranı ≤ %5; sessiz kaçak 0; az öneri."""
    r = M.olc(tmp_path, ad, uret(), gri=gri)
    oz = {k: r[k] for k in ("ad_siyah", "metin_siyah", "imza", "acik", "sessiz", "oneri")}
    assert r["ad_siyah"] <= 0.05 and r["metin_siyah"] <= 0.05, oz
    assert r["sessiz"] == 0, oz
    assert r["oneri"] <= 3, (oz, [(b["kaynak"], b["neden"]) for b in r["rec"]["bolgeler"] if b["karar"] == "onay_bekliyor"])
    if ad.startswith("tut"):
        assert r["acik"] == 0, oz                                         # İmza sütunu kapalı: imzaların çoğu kapalı
        assert any(b["kaynak"] == "imza_sutunu" and b["kapali"] for b in r["rec"]["bolgeler"])
    else:
        assert any(b["kaynak"] in Y.DARALT_KAYNAK and b["kapali"] for b in r["rec"]["bolgeler"]), r["rec"]["bolgeler"]


def test_makam_adi_unvan_etiketi_degil():
    assert not IM.is_role_label(_w("BAŞKANLIĞINA", 0, 0, 10, 10))
    assert not IM.is_role_label(_w("Dekanlığı", 0, 0, 10, 10))
    assert IM.is_role_label(_w("Başkanı", 0, 0, 10, 10)) and IM.is_role_label(_w("Dekan", 0, 0, 10, 10))


def test_imza_vurusuna_okunan_c_isareti_eposta_olmaz():
    from bidr.mask.detect import MaskRules
    ws = [_w("Ani", 167, 853, 282, 907, 1, 29), _w("©", 300, 853, 318, 907, 1, 53), _w("Dox.", 468, 884, 507, 899, 1, 80),
          _w("Öztürk", 589, 881, 646, 899, 1, 97), _w("Bölüm", 101, 914, 156, 929, 2), _w("Başkanı", 164, 914, 234, 933, 2)]
    assert not O.pii_hits(ws, MaskRules())
    ws2 = [_w("ayse", 100, 100, 140, 115, 1), _w("©", 142, 100, 156, 115, 1), _w("ornek.edu.tr", 158, 100, 260, 115, 1),
           _w("adresine", 270, 100, 330, 115, 1), _w("yazınız", 340, 100, 400, 115, 1)]
    assert [k for k, _ in O.pii_hits(ws2, MaskRules())] == ["eposta"]


# ---------------------------------------------------------------- 3. renk ayırma yaması

def _mavi_imzali_ad():
    img = Image.new("RGB", (int(8.27 * I), int(5 * I)), "white")
    d = ImageDraw.Draw(img)
    f = S.font(15)
    d.text((100, 300), "Prof. Dr. Ayşe Demir", fill="black", font=f)
    d.text((100, 322), "Bölüm Başkanı", fill="black", font=f)
    S.imza_ciz(d, 100, 262, w=200, h=52, color=S.MAVI, seed=11, width=2)
    ws = [_w("Prof.", 100, 302, 136, 316, 1), _w("Dr.", 141, 302, 162, 316, 1), _w("Ayşe", 167, 302, 204, 318, 1),
          _w("Demir", 209, 302, 252, 316, 1), _w("Bölüm", 100, 324, 148, 338, 2), _w("Başkanı", 153, 324, 212, 340, 2)]
    return img, ws


def test_yamali_bolgede_korumali_yedek_hazir():
    img, ws = _mavi_imzali_ad()
    bol = Y.goruntu_bolgeleri(img, ws, I)
    yamali = [b for b in bol if b.yama is not None]
    assert yamali, [(b.kaynak, b.karar, b.neden) for b in bol]
    assert any(b.yedek for b in yamali)
    for b in yamali:
        if "satırın içinden" in b.neden:
            continue                                                      # satır bandı yaması: yedeği yok (yama basılır)
        assert b.yedek, b.neden
        for w in ws:                                                      # yedek kapatma basılı kelimeyi örtmez
            assert sum(IM._overlap(w.box, p) for p in b.yedek) <= 0.2 * Y._area(w.box), (w.text, b.yedek)


def test_yama_siyahla_ortusunce_butun_kutu_kapanmaz(tmp_path):
    """`formats._kapat_turu`: yama siyah kapatmayla çoğunlukla örtüşünce bütün kutu değil korumalı yedek kapanır;
    yedek yoksa yama basılır (kutu siyah olmaz)."""
    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    S.metin_yaz(page, (60, 100), "Ayşe Demir", 11)
    yama = Image.new("RGB", (80, 40), "white")
    import io
    buf = io.BytesIO()
    yama.save(buf, format="PNG")
    flags = F._redact_flags(fitz)
    siyahlar = [fitz.Rect(40, 60, 160, 84)]                               # önceki siyah: yamanın üst %60'ı
    b = {"kutu": [50, 60, 150, 100], "tur": "imza", "neden": "t", "_yama": buf.getvalue(),
         "_yedek": [[50, 60, 150, 86]], "_etiket": "[İMZA]"}
    b2 = {"kutu": [170, 60, 270, 100], "tur": "imza", "neden": "t", "_yama": buf.getvalue(), "_etiket": "[İMZA]"}
    siyahlar.append(fitz.Rect(165, 60, 275, 84))
    labels: list = []
    F._kapat_turu(fitz, page, [b, b2], siyahlar, labels, flags)
    assert b["parcalar"] == [[50, 60, 150, 86]] and "_yama" not in b and "korumalı zarf" in b["neden"]
    assert not labels                                                     # bütün kutu etiketi yazılmadı
    assert "_yama" in b2 and "parcalar" not in b2                        # yedek yok: yama basıldı, kutu siyah değil
    assert "Ayşe" in page.get_text()                                      # ad satırı (y≈92-102) siyah altında değil
    pix = page.get_pixmap(dpi=72, clip=fitz.Rect(52, 90, 148, 99))
    g = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("L")
    assert sum(g.histogram()[:30]) < 0.5 * g.width * g.height
    doc.close()


def test_dondurulmus_sayfada_yama_yerine_yedek():
    b = Y.Bolge((10, 20, 60, 50), Y.KAPATILDI, "t", "imza_blogu", 0.8)
    b.yama, b.yedek = Image.new("RGB", (50, 30), "white"), [(12, 22, 40, 30)]
    c = Y.Bolge((10, 20, 60, 50), Y.KAPATILDI, "t", "imza_blogu", 0.8)
    c.yama = Image.new("RGB", (50, 30), "white")
    r = RA.ImageScan()
    r.bolgeler = [b, c]
    RA._geri_cevir(r, "90", Image.new("RGB", (100, 200), "white"))
    assert b.yama is None and b.parcalar == [RA._unrotate((12, 22, 40, 30), "90", 100, 200)] and b.karar == Y.KAPATILDI
    assert c.yama is None and c.karar == Y.ONAY and not c.kapat           # yedek yok: bütün kutu kapanmaz, öneri


# ---------------------------------------------------------------- 4. ölçüm

def test_gorsel_zemin_taranmis_kagitta_yanlis_alarm_vermez():
    img = M.el_yazisi_tutanak()[0]
    gri = A.gri_tarama(img)
    assert not Y._gorsel_zemin(gri, (1200, 520, 1700, 720))               # gri, gürültülü JPEG tarama + imza
    sari = Image.new("RGB", (500, 200), (238, 228, 196))                  # sararmış kâğıt + mavi imza + mor kaşe
    d = ImageDraw.Draw(sari)
    S.imza_ciz(d, 40, 40, w=260, h=90, color=S.MAVI, seed=3)
    S.kase_ciz(d, 400, 100, r=70)
    d.text((40, 150), "Prof. Dr. Ayşe Demir", fill="black", font=S.font(26))
    assert not Y._gorsel_zemin(sari, (0, 0, 500, 200))
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as t:
        A.afis(Path(t) / "a.png")
        afis = Image.open(Path(t) / "a.png").convert("RGB")
        assert Y._gorsel_zemin(afis, (100, 500, 700, 900))                # fotoğraf benzeri zemin
    assert Y._gorsel_zemin(Image.new("RGB", (200, 100), (30, 60, 160)), (0, 0, 200, 100))     # düz renkli afiş bandı


def test_olcum_yazi_benzeri_satir_parcasi_sayar():
    """OCR hiç kelime vermese de siyah altında kalan basılı satır parçaları sayılır; imza vuruşu sayılmaz."""
    img = Image.new("RGB", (int(8.27 * I), int(4 * I)), "white")
    d = ImageDraw.Draw(img)
    d.text((80, 100), "Prof. Dr. Ayşe Demir Bölüm Başkanı", fill="black", font=S.font(16))
    S.imza_ciz(d, 100, 200, w=220, h=60, seed=7, width=2)
    rows = [r for r in SA.satirlar(_murekkep(img, I)) if r.basili]
    yp = [q for r in rows for q in SA.parcalar(r)]
    assert len(yp) >= 4
    o = Y._kapatma_olcumu(img, 1.0, [(60, 90, 300, 130)], [], [], None, img.width * img.height, yp)
    assert o["yazi_parca"] >= 2 and o["yazi_alan_payi"] > 0.1 and o["siyah_altinda_kelime"] == 0
    o2 = Y._kapatma_olcumu(img, 1.0, [(90, 190, 340, 270)], [], [], None, img.width * img.height, yp)
    assert o2["yazi_parca"] == 0 and o2["gorsel_zemin_payi"] == 0.0


def test_ozet_yazi_altinda_esigi_ve_sayfa_siniri():
    sayfa = RA.asiri_kapatma([(0, 0, 10, 10)], [], [], 100.0)
    bol = [{"kapali": True, "kapatma_olcumu": {"siyah_altinda_kelime": 0, "dusuk_guven_kelime": 0, "yazi_parca": 3,
                                               "alan_payi": 0.01, "gorsel_zemin_payi": 0.0}}]
    oz = R.kapatma_ozeti({1: sayfa}, bol)
    assert oz["yazi_altinda"] == 3 and oz["esik_asildi"]
    bol[0]["kapatma_olcumu"]["yazi_parca"] = 1
    assert not R.kapatma_ozeti({1: sayfa}, bol)["esik_asildi"]
    bs = []
    for kaynak, yp in (("imza_blogu", 5), ("imza_etiketi", 4), ("imza_tasmasi", 0)):
        b = Y.Bolge((0, 0, 10, 10), Y.KAPATILDI, "t", kaynak, 0.8)
        b.olcum = {"siyah_altinda_kelime": 0, "dusuk_guven_kelime": 0, "alan_payi": 0.01, "gorsel_zemin_payi": 0.0,
                   "yazi_parca": yp}
        bs.append(b)
    Y._sayfa_siniri(bs)                                                   # OCR kelimesi yok; yapı ölçümü sınırı tetikler
    assert bs[0].karar == Y.ONAY and bs[1].karar == Y.KAPATILDI and bs[2].karar == Y.KAPATILDI


# ---------------------------------------------------------------- 5. onay yükü

@needs_ocr
@pytest.mark.parametrize("ad,renk,gri", [("dil_mavi", M.EL_MAVI, False), ("dil_siyah_gri", M.EL_SIYAH, True)])
def test_dilekcede_oneri_az_imza_sessiz_degil(tmp_path, ad, renk, gri):
    r = M.olc(tmp_path, ad, M.dilekce(renk=renk), gri=gri)
    oz = {k: r[k] for k in ("ad_siyah", "imza", "acik", "sessiz", "oneri")}
    assert r["oneri"] <= 5, (oz, [(b["kaynak"], b["neden"]) for b in r["rec"]["bolgeler"] if b["karar"] == "onay_bekliyor"])
    assert r["sessiz"] == 0 and r["imza"] == 1, oz                        # imza ya kapalı ya öneride
    assert r["ad_siyah"] <= 0.05, oz                                      # el yazısı gövde kapatılmadı


@needs_ocr
def test_parafli_tabloda_tek_oneri(tmp_path):
    r = M.olc(tmp_path, "paraf", M.parafli_tablo())
    oneri = [b for b in r["rec"]["bolgeler"] if b["karar"] == "onay_bekliyor" and b["tur"] == "imza"]
    assert len(oneri) <= 2 and r["sessiz"] == 0, [(b["kaynak"], b["neden"]) for b in oneri]
    assert sum(len(b.get("parcalar") or []) for b in oneri) >= 11         # her paraf kendi küçük kutusuyla
    assert r["metin_siyah"] <= 0.01


@needs_ocr
def test_akts_taramasinda_mavi_ders_adlari_oneri_olmaz(tmp_path):
    g = M.akts_goruntu()
    r = M.olc(tmp_path, "akts", (g, g, g))
    imza = [b for b in r["rec"].get("bolgeler") or [] if b["tur"] == "imza" and b["karar"] != "birakildi"]
    assert not imza, [(b["kaynak"], b["karar"], b["neden"]) for b in imza]
    assert r["metin_siyah"] <= 0.01


def test_renkli_basili_yazi_aday_degil():
    img = Image.new("RGB", (int(8.27 * I), int(6 * I)), "white")
    d = ImageDraw.Draw(img)
    f = S.font(18)
    ws = []
    for j in range(6):
        y = 320 + 40 * j
        d.text((120, y), "Diferansiyel Denklemler", fill=(20, 60, 220), font=f)
        ws += [_w("Diferansiyel", 118, y + 2, 228, y + 22, j + 1), _w("Denklemler", 234, y + 2, 334, y + 22, j + 1)]
    bol = Y.goruntu_bolgeleri(img, ws, I)
    assert not [b for b in bol if b.karar != Y.BIRAKILDI], [(b.kaynak, b.karar, b.neden) for b in bol]
    # aynı yerde okunmuş kelime yokken mavi imza adaydır
    img2 = Image.new("RGB", img.size, "white")
    S.imza_ciz(ImageDraw.Draw(img2), 120, 320, w=220, h=60, color=S.MAVI, seed=3, width=2)
    assert any(b.karar == Y.ONAY for b in Y.goruntu_bolgeleri(img2, [], I))


def test_etiketsiz_ara_kapaliyken_aday_aranmaz():
    img = Image.new("RGB", (int(8.27 * I), int(6 * I)), "white")
    S.imza_ciz(ImageDraw.Draw(img), 120, 320, w=220, h=60, seed=3, width=2)
    assert any(b.karar == Y.ONAY for b in Y.goruntu_bolgeleri(img, [], I))
    assert not [b for b in Y.goruntu_bolgeleri(img, [], I, etiketsiz_ara=False) if b.karar != Y.BIRAKILDI]


def test_metin_katmanli_web_goruntu_sayfasinda_etiketsiz_aday_yok(tmp_path):
    """Metin katmanı + üst/alt bilgide URL ve tarih + sayfayı kaplayan görüntü (ekran çıktısı): görüntü olarak
    çözümlenir ama etiketsiz imza adayı aranmaz."""
    src, dst = tmp_path / "w.pdf", tmp_path / "o.pdf"
    img = Image.new("RGB", (1240, 1754), "white")
    d = ImageDraw.Draw(img)
    for j in range(8):
        S.imza_ciz(d, 200, 500 + 110 * j, w=160, h=50, color=S.MAVI, seed=30 + j)   # süslü mavi bağlantı/ikon benzeri izler
    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    doc = fitz.open()
    p = doc.new_page(width=595, height=842)
    p.insert_image(p.rect, stream=buf.getvalue())
    S.metin_yaz(p, (30, 20), "23.11.2026 10:42   AKTS Bilgi Paketi", 8)
    S.metin_yaz(p, (30, 830), "https://akts.ornek.edu.tr/ders/plan?id=42   1/1", 8)
    for j in range(30):
        S.metin_yaz(p, (60, 80 + 22 * j), f"MAT{101 + j} Ders adı ve içerik bilgisi satırı {j} burada yer alır", 10)
    doc.save(str(src))
    doc.close()
    from bidr.mask.detect import MaskRules
    rec = R.mask_and_check(src, dst, MaskRules(), "pymupdf")
    imza = [b for b in rec.get("bolgeler") or [] if b["tur"] == "imza" and b["karar"] != "birakildi"]
    assert not imza, [(b["kaynak"], b["karar"], b["neden"]) for b in imza]


def test_paraf_gruplari_hizali_adaylari_toplar():
    rs = [Y._R((600, 100 + 60 * i, 640, 130 + 60 * i), "etiketsiz_aday", "n", 0.5, Y.ONAY) for i in range(5)]
    rs += [Y._R((100, 400, 180, 440), "etiketsiz_aday", "n", 0.5, Y.ONAY),
           Y._R((300, 100, 380, 140), "gomulu_gorsel", "n", 0.5, Y.ONAY)]
    out = Y._paraf_gruplari(rs)
    assert len(out) == 3
    g = [r for r in out if r.parcalar]
    assert len(g) == 1 and len(g[0].parcalar) == 5 and g[0].box == (600, 100, 640, 370)


def test_kural_surumu_artti():
    assert R.KURAL_SURUM >= 6 and "satir" in R._KOD_MODULLERI
