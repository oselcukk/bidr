"""m6: aşırı kapatmayı kökten azaltma (gerçek veri denemesi v4 bulguları, yalnız sentetik veri).

1 mürekkep ayrılamayan metinle örtüşen imza öneri olur (geri basma onayı yok; gri/JPEG/eğik taramada mürekkep zarfı)
2 sayfa toplamı sınırı · 3 basılı metin koruması (kelimeden kırpma) · 4 bölge düzeyinde kapatma ölçümü + eşik
5 dönmüş tutanakta İmza sütunu kesin kapalı · 6 web çıktısında banner/renkli yazı kapatılmaz · 7 [İMZA]/[GÖRSEL]
8 paraflar tek tek küçük öneri · 9 dolu zarf (silüet yok) · 10 `python -m bidr` · genel set: basılı metnin siyah payı."""
from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

import pytest

PIL = pytest.importorskip("PIL")
fitz = pytest.importorskip("pymupdf")
from PIL import Image, ImageDraw  # noqa: E402

import asiri_sentetik as A  # noqa: E402
import imza_sentetik as S  # noqa: E402
from bidr.mask import imza as IM  # noqa: E402
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


def _w(text, x0, y0, x1, y1, line=1, conf=96.0):
    return O.Word(text, conf, x0, y0, x1, y1, (1, 1, line, 1))


def _kapali_dikdortgenler(b: Y.Bolge) -> list:
    return list(b.parcalar) if b.parcalar else [b.kutu]


def _ortme(word_box, rects) -> float:
    a = max(1.0, (word_box[2] - word_box[0]) * (word_box[3] - word_box[1]))
    return min(1.0, sum(IM._overlap(word_box, r) for r in rects) / a)


def _metin_korunur(bol, kelimeler) -> None:
    """Genel kural: hiçbir otomatik kapatma korunan kelimenin %50'sinden fazlasını örtmez."""
    for b in bol:
        if not b.kapat:
            continue
        for w in kelimeler:
            assert _ortme(w.box, _kapali_dikdortgenler(b)) <= 0.5, (w.text, b.kaynak, b.kutu, b.parcalar)


def _maskele(tmp_path, ad, uret):
    src, bos, dst = tmp_path / ad, tmp_path / f"bos_{ad}", tmp_path / f"o_{ad}"
    uret(src, True)
    uret(bos, False)
    rec = R.mask_and_check(src, dst, MaskRules(), "pymupdf")
    return rec, src, bos, dst


# ---------------------------------------------------------------- 1. mürekkep ayrılamazsa öneri; geri basma yok

def _etiketli_imza(img_size=(int(8.27 * I), int(6 * I))):
    img = Image.new("RGB", img_size, "white")
    d = ImageDraw.Draw(img)
    S.imza_ciz(d, 160, 300, w=180, h=50, seed=5, width=2)
    return img, [_w("İmza:", 90, 315, 140, 332)]


def test_murekkep_ayrilamazsa_kutu_kapatilmaz_oneri_olur(monkeypatch):
    img, ws = _etiketli_imza()
    monkeypatch.setattr(Y, "_murekkep_zarfi", lambda *a, **k: ([], lambda b: 0))
    bol = Y.goruntu_bolgeleri(img, ws, I)
    imza = [b for b in bol if b.kaynak in Y.DARALT_KAYNAK]
    assert any(b.karar == Y.ONAY for b in imza) and all(b.karar != Y.KAPATILDI and not b.kapali and not b.kapat
                                                        for b in imza), \
        [(b.kaynak, b.karar, b.neden) for b in bol]
    assert all("geri basma" not in b.neden for b in bol)
    assert all(b.geri_basilan is None for b in bol)


def test_geri_basma_yolu_kalkti():
    src = Path(Y.__file__).read_text(encoding="utf-8")
    assert "geri basma gerekli" not in src and "geri_basilan = _metin" not in src


def test_gri_jpeg_egik_taramada_murekkep_zarfi_bulunur():
    """Gri tonlu, gürültülü, hafif eğik JPEG taramada adın üstünden geçen imzanın mürekkebi (ad kutusu dışında)
    bulunur: zarf boş dönmez, ad kutusuna taşmaz."""
    img = Image.new("RGB", (900, 400), "white")
    d = ImageDraw.Draw(img)
    d.text((120, 220), "Prof. Dr. Ayşe Demir", fill="black", font=S.font(30))
    S.imza_ciz(d, 130, 160, w=300, h=80, seed=11)
    g = A.gri_tarama(img)
    k = 1.0
    ad = (118, 222, 420, 256)                                 # ad satırının kelime kutusu (korunur)
    zarf, sayac = Y._murekkep_zarfi(g, k, (100, 140, 460, 280), [ad])
    assert zarf, "gri taramada mürekkep bulunamadı"
    parca = Y._kirp(zarf, [ad])
    assert parca and all(not IM._inter(p, (ad[0] + 2, ad[1] + 2, ad[2] - 2, ad[3] - 2)) for p in parca)
    # imzanın ad satırı dışındaki pikselleri büyük ölçüde zarfın içinde
    imzasiz = Image.new("RGB", (900, 400), "white")
    ImageDraw.Draw(imzasiz).text((120, 220), "Prof. Dr. Ayşe Demir", fill="black", font=S.font(30))
    mk = S._maske(img, imzasiz)
    md = mk.tobytes()
    n = ic = 0
    for i, v in enumerate(md):
        if not v:
            continue
        x, y = i % mk.width, i // mk.width
        if ad[1] - 4 <= y <= ad[3] + 4:
            continue
        n += 1
        ic += any(p[0] <= x <= p[2] and p[1] <= y <= p[3] for p in parca)
    assert n and ic / n >= 0.9, ic / max(1, n)


def test_gri_taramada_gurultu_zarf_uretmez():
    g = A.gri_tarama(Image.new("RGB", (600, 300), "white"))
    zarf, _ = Y._murekkep_zarfi(g, 1.0, (20, 20, 580, 280), [])
    assert zarf == []


@needs_ocr
def test_gri_taramali_tutanakta_ad_acik_imza_kapali(tmp_path):
    rec, src, bos, dst = _maskele(tmp_path, "gri.pdf", lambda p, i: A.gri_tutanak(p, imzali=i))
    assert A.basili_siyah_payi(bos, dst) <= 0.03
    assert not any("geri basma" in b["neden"] for b in rec["bolgeler"])
    acik_kapali = [b for b in rec["bolgeler"] if b["karar"] == "onay_bekliyor" and b["kapali"]]
    assert not acik_kapali, acik_kapali                       # "kapalı ama onay bekliyor" yolu yok
    oneri = [b for b in rec["bolgeler"] if b["tur"] == "imza" and b["karar"] == "onay_bekliyor"]
    n, kacan = S.kacirilan(src, bos, dst, esik=0.5)
    assert n == 2 and kacan <= len(oneri), (kacan, oneri)


# ---------------------------------------------------------------- 2. sayfa toplamı sınırı

def _kapali_bolge(kaynak, guven, alan, kelime=0):
    b = Y.Bolge((0, 0, 10, 10), Y.KAPATILDI, "test", kaynak, guven)
    b.olcum = {"siyah_altinda_kelime": kelime, "dusuk_guven_kelime": 0, "alan_payi": alan, "gorsel_zemin_payi": 0.0}
    return b


def test_sayfa_toplami_alan_siniri():
    bs = [_kapali_bolge("imza_blogu", 0.85, 0.12), _kapali_bolge("imza_tasmasi", 0.8, 0.14),
          _kapali_bolge("imza_sutunu", 0.95, 0.2), _kapali_bolge("imza_etiketi", 0.9, 0.02)]
    Y._sayfa_siniri(bs)
    kalan = [b for b in bs if b.karar == Y.KAPATILDI]
    assert sum(b.olcum["alan_payi"] for b in kalan) <= Y.SAYFA_ASIRI_ALAN
    assert bs[2].karar == Y.KAPATILDI                         # imza sütunu kesin: öneriye çevrilmez
    assert bs[1].karar == Y.ONAY and "sayfa toplamı" in bs[1].neden and bs[1].parcalar is None


def test_sayfa_toplami_kelime_siniri():
    bs = [_kapali_bolge("imza_blogu", 0.85, 0.01, kelime=5), _kapali_bolge("imza_etiketi", 0.9, 0.01, kelime=4),
          _kapali_bolge("imza_tasmasi", 0.8, 0.01)]
    Y._sayfa_siniri(bs)
    assert bs[0].karar == Y.ONAY and bs[1].karar == Y.KAPATILDI and bs[2].karar == Y.KAPATILDI


# ---------------------------------------------------------------- 3. basılı metin koruması

def _sutunlu_sayfa():
    """Izgaralı tablo (Adı Soyadı | Unvanı | İmza); bir imza hücresinde basılı "Raporlu" yazısı ve yanında imza."""
    W, H = int(8.27 * I), int(6 * I)
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    cols, y0, rh = (40, 300, 480, 780), 100, 60
    for i in range(5):
        d.line([(cols[0], y0 + i * rh), (cols[-1], y0 + i * rh)], fill="black", width=1)
    for x in cols:
        d.line([(x, y0), (x, y0 + 4 * rh)], fill="black", width=1)
    ws = [_w("Adı", 50, 120, 90, 135, 1), _w("Unvanı", 310, 120, 370, 135, 1), _w("İmza", 490, 120, 530, 135, 1)]
    f = S.font(13)
    for j in range(3):
        yy = y0 + (j + 1) * rh
        d.text((50, yy + 20), f"Kişi {j}", fill="black", font=f)
        ws.append(_w(f"Kişi{j}", 50, yy + 20, 100, yy + 35, j + 2))
        if j == 1:
            d.text((490, yy + 20), "Raporlu", fill="black", font=f)
            ws.append(_w("Raporlu", 490, yy + 20, 545, yy + 35, j + 2))
            S.imza_ciz(d, 600, yy + 8, w=150, h=40, seed=20 + j, width=2)
        else:
            S.imza_ciz(d, 520, yy + 8, w=200, h=40, seed=20 + j, width=2)
    return img, ws


def test_imza_sutunu_kapanir_basili_kelime_acik_kalir():
    img, ws = _sutunlu_sayfa()
    bol = Y.goruntu_bolgeleri(img, ws, I, kesin=ws)
    sutun = [b for b in bol if b.kaynak == "imza_sutunu"]
    assert sutun and all(b.karar == Y.KAPATILDI for b in sutun), [(b.kaynak, b.karar, b.neden) for b in bol]
    _metin_korunur(bol, ws)
    rap = next(w for w in ws if w.text == "Raporlu")
    assert any(b.parcalar for b in sutun) and all(_ortme(rap.box, _kapali_dikdortgenler(b)) == 0 for b in sutun)


def test_kirp_kelimeyi_cikarir():
    p = Y._kirp([(0, 0, 100, 50)], [(40, 10, 60, 30)])
    assert all(_ortme((40, 10, 60, 30), [q]) == 0 for q in p)
    assert abs(sum(Y._area(q) for q in p) - (100 * 50 - 22 * 22)) < 1e-6


@needs_ocr
def test_metin_katmanli_gomulu_imza_kelimeleri_ortmez(tmp_path):
    """Metin katmanlı çizelgede unvana taşan gömülü imza görüntüsü: görüntü kapanır, üstündeki ad/unvan kelimeleri
    açık kalır (geri basma yok)."""
    info = {}

    def uret(p, i):
        info.update(S.vektor_cizelge(p, sayfa=1, satir=6, tasan=(3,), imzali=i))
    rec, src, bos, dst = _maskele(tmp_path, "vektor.pdf", uret)
    assert all(b["geri_basilan"] is None for b in rec["bolgeler"])
    assert rec["kapatma_olcumu"]["siyah_altinda"] == 0, rec["kapatma_olcumu"]
    assert A.basili_siyah_payi(bos, dst) <= 0.03


# ---------------------------------------------------------------- 4. ölçüm

def test_bolge_kaydinda_kapatma_olcumu():
    img, ws = _etiketli_imza()
    bol = Y.goruntu_bolgeleri(img, ws, I)
    kap = [b for b in bol if b.kapat]
    assert kap
    for b in kap:
        d = b.kayit("x", 1, b.kutu)
        assert set(d["kapatma_olcumu"]) >= {"siyah_altinda_kelime", "dusuk_guven_kelime", "alan_payi",
                                             "gorsel_zemin_payi"}


def test_olcum_dusuk_guven_ve_gorsel_zemin():
    foto = Image.new("RGB", (400, 200))
    d = ImageDraw.Draw(foto)
    for i in range(0, 400, 8):
        for j in range(0, 200, 8):
            d.rectangle([i, j, i + 8, j + 8], fill=((i * 7) % 256, (j * 13) % 256, (i * j) % 256))
    ws = [_w("Ayşe", 10, 10, 60, 25, conf=40), _w("Demir", 300, 10, 360, 25, conf=95),
          _w("x", 0, 0, 1, 1), _w("Kayaa", 100, 100, 160, 115, conf=95)]
    kor = [ws[1], ws[3]]
    o = Y._kapatma_olcumu(foto, 1.0, [(0, 0, 200, 200)], ws, kor, 15.0, 400 * 200)
    assert o["dusuk_guven_kelime"] == 1 and o["siyah_altinda_kelime"] == 1
    assert o["alan_payi"] == 0.5 and o["gorsel_zemin_payi"] > 0.4


def test_esik_asilinca_dosya_karar_bekler():
    sayfa = RA.asiri_kapatma([(0, 0, 10, 10)], [], [], 100.0)
    bol = [{"kapali": True, "kapatma_olcumu": {"siyah_altinda_kelime": 0, "dusuk_guven_kelime": 5,
                                               "alan_payi": 0.01, "gorsel_zemin_payi": 0.0}}]
    oz = R.kapatma_ozeti({1: sayfa}, bol)
    assert oz["dusuk_guven_altinda"] == 5 and oz["esik_asildi"]
    assert not R.kapatma_ozeti({1: sayfa}, [])["esik_asildi"]
    kasitli = [{"kapali": True, "kapatma_olcumu": {"siyah_altinda_kelime": 3, "dusuk_guven_kelime": 9,
                                                   "alan_payi": 0.0, "gorsel_zemin_payi": 0.5, "kasitli": True}}]
    assert not R.kapatma_ozeti({1: sayfa}, kasitli)["esik_asildi"]
    assert R.bekliyor({"durum": "tamam", "asiri_kapatma_bekliyor": True})


def test_her_kapatilan_bolgede_olcum(tmp_path):
    """Kişisel veri (kasıtlı) dahil her kapatılan bölgeye `kapatma_olcumu` yazılır."""
    src, dst = tmp_path / "e.pdf", tmp_path / "o.pdf"
    doc = fitz.open()
    p = doc.new_page()
    S.metin_yaz(p, (72, 100), "İletişim: deneme.kisi@ornek.edu.tr adresine yazınız.", 11)
    doc.save(str(src))
    doc.close()
    rec = R.mask_and_check(src, dst, MaskRules(), "pymupdf")
    kap = [b for b in rec["bolgeler"] if b["kapali"]]
    assert kap and all("kapatma_olcumu" in b for b in kap), kap
    assert all(b["kapatma_olcumu"]["kasitli"] for b in kap if b["tur"] == "kisisel_veri")
    assert not rec.get("asiri_kapatma_bekliyor")


# ---------------------------------------------------------------- 5. dönmüş tutanak: İmza sütunu kesin kapalı

def test_dondurulmus_sayfada_parcalar_geri_cevrilir():
    b = Y.Bolge((10, 20, 30, 40), Y.KAPATILDI, "t", "imza_blogu", 0.8)
    b.parcalar = [(12, 22, 20, 30)]
    r = RA.ImageScan()
    r.bolgeler = [b]
    img = Image.new("RGB", (100, 200), "white")
    RA._geri_cevir(r, "90", img)
    assert b.kutu == RA._unrotate((10, 20, 30, 40), "90", 100, 200)
    assert b.parcalar == [RA._unrotate((12, 22, 20, 30), "90", 100, 200)]


@needs_ocr
def test_dondurulmus_kurul_karari_imza_sutunu_kapali(tmp_path):
    rec, src, bos, dst = _maskele(tmp_path, "don.pdf", lambda p, i: A.kurul_karari(p, imzali=i, don=90))
    sutun = [b for b in rec["bolgeler"] if b["kaynak"] == "imza_sutunu"]
    assert sutun and all(b["karar"] == "kapatildi" for b in sutun), rec["bolgeler"]
    n, kacan = S.kacirilan(src, bos, dst, esik=0.5)
    assert n >= 4 and kacan <= 1, (n, kacan)                 # taşan imzanın unvan üstündeki kısmı açık kalabilir
    assert A.basili_siyah_payi(bos, dst) <= 0.05


# ---------------------------------------------------------------- 6. web çıktısı

def test_web_ciktisinda_banner_ve_renkli_yazi_kapatilmaz(tmp_path):
    src, dst = tmp_path / "akts.pdf", tmp_path / "o.pdf"
    info = A.web_sayfasi(src)
    doc = fitz.open(str(src))
    try:
        assert RA.web_ciktisi(doc[0])
    finally:
        doc.close()
    rec = R.mask_and_check(src, dst, MaskRules(), "pymupdf")
    kap = [b for b in rec["bolgeler"] if b["tur"] == "imza" and b["kapali"]]
    banner = fitz.Rect(info["banner"])
    assert kap and all(not fitz.Rect(b["kutu"]).intersects(banner) for b in kap), kap
    assert any(fitz.Rect(b["kutu"]).intersects(fitz.Rect(info["imza"])) for b in kap)
    d = fitz.open(str(dst))
    try:
        t = d[0].get_text().replace("\xa0", " ")
        pix = d[0].get_pixmap(dpi=72, clip=banner)
        g = Image.open(io.BytesIO(pix.tobytes("png"))).convert("L")
    finally:
        d.close()
    assert all(ad in t for ad in A.AKTS_DERSLER)
    h = g.histogram()
    assert sum(h[:8]) <= 0.02 * sum(h)                       # banner'da siyah blok yok


# ---------------------------------------------------------------- 7. [İMZA] / [GÖRSEL]

def test_imza_bolgesi_her_zaman_imza_etiketi(monkeypatch):
    img, ws = _etiketli_imza()
    monkeypatch.setattr(Y, "_fotograf", lambda *a, **k: True)
    bol = Y.goruntu_bolgeleri(img, ws, I)
    assert bol and all(not b.gorsel and Y.etiket_yazisi(b) == IM.IMZA_LABEL for b in bol if b.kaynak != "gomulu_gorsel")
    g = Y.Bolge((0, 0, 10, 10), Y.KAPATILDI, "t", "gomulu_gorsel", 0.9)
    g.gorsel = True
    assert Y.etiket_yazisi(g) == Y.GORSEL_LABEL


# ---------------------------------------------------------------- 8. paraflar tek tek

def test_paraflar_tek_tek_kucuk_oneri():
    W, H = int(8.27 * I), int(11.69 * I)
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    n = 0
    for r in range(5):
        for c in range(4):
            S.imza_ciz(d, 120 + 170 * c, 380 + 140 * r, w=80, h=40, seed=80 + n, width=2)
            n += 1
    bol = Y.goruntu_bolgeleri(img, [], I)
    imza = [b for b in bol if b.karar == Y.ONAY]
    assert not any(b.kaynak == "etiketsiz_sayfa" for b in bol)
    # m7: aynı düşey hizadaki paraflar sütun başına tek öneri; her paraf `parcalar`da kendi küçük kutusuyla
    assert len(imza) == 4 and all(b.parcalar and len(b.parcalar) >= 3 for b in imza), \
        [(b.kaynak, b.karar, b.neden) for b in bol]
    assert sum(len(b.parcalar) for b in imza) >= 17
    assert all("paraf" in b.neden for b in imza)
    assert all(Y._area(p) <= 0.01 * W * H for b in imza for p in b.parcalar)
    assert not any(b.kapat for b in bol)


# ---------------------------------------------------------------- 9. dolu zarf

def test_murekkep_zarfi_dolu_siluet_birakmaz():
    img, ws = _etiketli_imza()
    bol = Y.goruntu_bolgeleri(img, ws, I)
    kap = [b for b in bol if b.kapat]
    assert kap and all(b.parcalar and len(b.parcalar) <= 3 for b in kap), [(b.kaynak, b.parcalar) for b in kap]
    rects = [p for b in kap for p in b.parcalar]
    # imza mürekkebinin her pikseli zarfın en az 2 px içinde (kenar payı: biçim okunmaz) ve zarf dolu dikdörtgen
    g = img.convert("L")
    gd, W = g.tobytes(), g.width
    ink = [(i % W, i // W) for i, v in enumerate(gd) if v < 128]
    ic = sum(1 for x, y in ink if any(p[0] + 2 <= x <= p[2] - 2 and p[1] + 2 <= y <= p[3] - 2 for p in rects))
    assert ic >= 0.97 * len(ink), ic / len(ink)
    bos = sum(1 for p in rects for x in range(int(p[0]) + 1, int(p[2]) - 1) for y in range(int(p[1]) + 1, int(p[3]) - 1)
              if gd[y * W + x] >= 128)
    assert bos > 3 * len(ink)                                 # vuruş değil, vuruşları örten dolu alan
    _metin_korunur(bol, ws)


# ---------------------------------------------------------------- 10. python -m bidr

def test_python_m_bidr_calisir():
    kok = Path(__file__).resolve().parents[1]
    r = subprocess.run([sys.executable, "-m", "bidr", "--help"], cwd=str(kok), capture_output=True, text=True,
                       env={"PYTHONPATH": str(kok), "PATH": "/usr/bin:/bin"}, timeout=120)
    assert r.returncode == 0 and "usage" in r.stdout.lower(), r.stderr[-500:]


# ---------------------------------------------------------------- genel set: basılı metnin siyah altında kalan oranı

@needs_ocr
@pytest.mark.parametrize("ad,uret,kacan_ust", [
    ("kurul.pdf", lambda p, i: A.kurul_karari(p, imzali=i), 1),
    ("kurul_gri.pdf", lambda p, i: A.kurul_karari(p, imzali=i, gri=True), 1),
    ("tutanak.pdf", lambda p, i: S.tutanak(p, ortusen=True, imzali=i), None),
    ("tutanak_don.pdf", lambda p, i: A.kurul_karari(p, imzali=i, don=90), 1),
])
def test_genel_set_basili_metin_siyah_payi(tmp_path, ad, uret, kacan_ust):
    rec, src, bos, dst = _maskele(tmp_path, ad, uret)
    pay = A.basili_siyah_payi(bos, dst)
    assert pay <= 0.05, (ad, pay)
    assert rec["kapatma_olcumu"]["siyah_alan_payi"] < 0.3, rec["kapatma_olcumu"]
    n, kacan = S.kacirilan(src, bos, dst, esik=0.5)
    oneri = [b for b in rec["bolgeler"] if b["tur"] == "imza" and b["karar"] == "onay_bekliyor"]
    assert n >= 2 and kacan <= (kacan_ust if kacan_ust is not None else len(oneri)), (ad, n, kacan, oneri)


@needs_ocr
def test_genel_set_afis_kapatilmaz(tmp_path):
    src, dst = tmp_path / "afis.png", tmp_path / "o.png"
    A.afis(src)
    rec = R.mask_and_check(src, dst, MaskRules(), "pymupdf")
    assert not [b for b in rec.get("bolgeler") or [] if b["tur"] == "imza" and b["kapali"]], rec.get("bolgeler")
    assert A.basili_siyah_payi(src, dst) <= 0.01


def test_genel_set_web_sayfasi(tmp_path):
    src, bos, dst = tmp_path / "w.pdf", tmp_path / "wb.pdf", tmp_path / "wo.pdf"
    A.web_sayfasi(src)
    A.web_sayfasi(bos, imzali=False)
    R.mask_and_check(src, dst, MaskRules(), "pymupdf")
    assert A.basili_siyah_payi(bos, dst) <= 0.01
    assert S.kacirilan(src, bos, dst, esik=0.5) == (1, 0)
