"""İmza: yapısal kapatma (bidr/mask/yapi.py). Hat (m2) yalnız `kapatildi` bölgeleri karartır;
`onay_bekliyor` bölge insan kararına kadar açık kalır ve dosya elle bakılmalı olur (pakete girmez). Yalnız sentetik veri (tests/imza_sentetik.py: çizilmiş
tablo, el yazısı benzeri eğriler, uydurma adlar).

Kapsam: imza sütunu çok sayfada (başlık yalnız ilk sayfada), metinle örtüşen imzada geri basma
(metin katmanı) ve onay bekleme (OCR), renkli mürekkebin ayrılması, yanlış alarm süzgeçleri (tekrar,
kaşe, antet, not dökümü), gömülü görüntü, e-imza atlaması, kaçırma olmaması ve kapatmanın gerçek
silme olması (kutu altında çıkarılabilir metin/görüntü pikseli kalmaması)."""
from __future__ import annotations

import io
import json

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image, ImageDraw  # noqa: E402

import imza_sentetik as S  # noqa: E402
from bidr.mask import imza as IM  # noqa: E402
from bidr.mask import ocr as O  # noqa: E402
from bidr.mask import run as R  # noqa: E402
from bidr.mask import yapi as Y  # noqa: E402
from bidr.mask.detect import MaskRules  # noqa: E402

needs_ocr = pytest.mark.skipif(not O.ocr_available(), reason="tesseract + tur/eng yok")
KAYIT_ALANLARI = {"id", "sayfa", "kutu", "tur", "karar", "neden", "kaynak", "guven", "geri_basilan", "kapali"}


def _fitz():
    return pytest.importorskip("pymupdf")


def _maskele(tmp_path, ad: str, uret):
    """İmzalı ve imzasız sürümü üretir, imzalıyı maskeler → (kayıt, kaynak, imzasız, maskeli)."""
    src, bos, dst = tmp_path / "src" / ad, tmp_path / "bos" / ad, tmp_path / "out" / ad
    uret(src, True)
    uret(bos, False)
    rec = R.mask_and_check(src, dst, MaskRules(), "pymupdf", temiz=tmp_path / "temiz" / ad)
    return rec, src, bos, dst


def _goruntu_temiz(page, rect, pad: float = 1.5) -> bool:
    """Sayfadaki gömülü görüntülerin `rect` içine düşen pikselleri beyaz mı (gerçek silme)."""
    fitz = _fitz()
    r0 = fitz.Rect(rect)
    r0 = fitz.Rect(r0.x0 + pad, r0.y0 + pad, r0.x1 - pad, r0.y1 - pad)
    for info in page.get_image_info(xrefs=True):
        bb = fitz.Rect(info["bbox"])
        inter = bb & r0
        if inter.is_empty or not info.get("xref"):
            continue
        im = Image.open(io.BytesIO(page.parent.extract_image(info["xref"])["image"])).convert("L")
        sx, sy = im.width / bb.width, im.height / bb.height
        crop = im.crop((int((inter.x0 - bb.x0) * sx), int((inter.y0 - bb.y0) * sy),
                        max(1, int((inter.x1 - bb.x0) * sx)), max(1, int((inter.y1 - bb.y0) * sy))))
        if crop.getextrema()[0] < 245:
            return False
    return True


def _kutudaki_metin(page, rect) -> str:
    fitz = _fitz()
    return " ".join(w[4] for w in page.get_text("words", clip=fitz.Rect(rect)))


def _metin(page) -> str:
    return " ".join(page.get_text("text").split())


# ---------------------------------------------------------------- birim (OCR'sız)

def test_tablo_izgarasi_ve_imza_sutunu():
    img = Image.new("RGB", (1240, 900), "white")
    d = ImageDraw.Draw(img)
    for i in range(6):
        d.line([(100, 100 + i * 95), (1140, 100 + i * 95)], fill="black", width=2)
    for x in S.COLS:
        d.line([(x, 100), (x, 575)], fill="black", width=2)
    h = IM.hazirla(img, [], 150)
    yat, dik = Y.cizgiler(h.raw_ink)
    tabs = Y.tablolar(yat, dik)
    assert len(tabs) == 1 and len(tabs[0].xs) == 5 and len(tabs[0].ys) == 6, tabs
    k = IM.A_PPI / 150
    basliklar = [O.Word(t, 95, (x + 14) * k, 130 * k, (x + 90) * k, 150 * k, (1, 1, 1, i))
                 for i, (x, t) in enumerate(zip(S.COLS, ["Sıra", "Adı Soyadı", "Unvanı", "İmza"]))]
    assert Y.imza_sutunu(tabs[0], basliklar)[:2] == (3, 0)
    assert Y.imza_sutunu(tabs[0], basliklar[:3]) is None


def test_bolge_kaydi_bicimi_ve_kararli_kimlik():
    bag = Y.Baglam(sha8="abcdef12")
    b = Y.Bolge((1, 2, 3, 4), Y.KAPATILDI, "İmza sütunu", "imza_sutunu", 0.95)
    ids = bag.kimlikler(2, 2)
    assert ids == ["abcdef12-s2-1", "abcdef12-s2-2"]
    assert bag.kimlikler(2, 1) == ["abcdef12-s2-101"]            # aynı sayfanın yeniden taranması
    rec = b.kayit(ids[0], 2, (1, 2, 3, 4))
    assert set(rec) - {"parcalar"} == KAYIT_ALANLARI and rec["tur"] == "imza" and rec["geri_basilan"] is None
    json.dumps(rec)
    b.geri_basilan = "Ayşe Demir – Prof. Dr."
    assert Y.etiket_yazisi(b) == "Ayşe Demir – Prof. Dr. [imza gizlendi]"


def test_antet_bandi_ve_dosyalar_arasi_tekrar():
    def sayfa(y):
        img = Image.new("RGB", (1240, 1754), "white")
        S.imza_ciz(ImageDraw.Draw(img), 800, y, seed=5)
        return img
    # üst bant: antet/logo sayılır
    out = Y.goruntu_bolgeleri(sayfa(120), [], 150)
    assert out and all(b.karar == Y.BIRAKILDI and "üst bandı" in b.neden for b in out), out
    # aynı konumda ikinci dosyada görülen etiketsiz aday süzülür (dosyalar arası bellek)
    bellek = Y.TekrarBellegi()
    a = Y.goruntu_bolgeleri(sayfa(1500), [], 150, bag=Y.Baglam(bellek=bellek))
    b = Y.goruntu_bolgeleri(sayfa(1500), [], 150, bag=Y.Baglam(bellek=bellek))
    assert [x.karar for x in a] == [Y.ONAY], a
    assert [x.karar for x in b] == [Y.BIRAKILDI] and "tekrarlayan" in b[0].neden, b


def test_kase_dairesi_suzulur_imza_degen_kase_suzulmez():
    img = Image.new("RGB", (1240, 1754), "white")
    S.kase_ciz(ImageDraw.Draw(img), 600, 1000)
    out = Y.goruntu_bolgeleri(img, [], 150)
    assert out and all(b.karar == Y.BIRAKILDI and "kaşe" in b.neden for b in out), out
    # mühre değen imza: kutu kareden çıkar, süzülmez (kapatılır, onay bekler)
    S.imza_ciz(ImageDraw.Draw(img), 660, 980, w=300, h=70, seed=3)
    out2 = Y.goruntu_bolgeleri(img, [], 150)
    assert any(b.karar == Y.ONAY for b in out2), out2


def test_renkli_murekkep_ayirma_metni_korur():
    img = Image.new("RGB", (600, 200), "white")
    d = ImageDraw.Draw(img)
    d.text((40, 80), "Ayşe Demir", fill="black", font=S.font(40))
    S.imza_ciz(d, 30, 40, w=420, h=120, color=S.MAVI, seed=4)
    yama = Y.murekkebi_ayir(img, (0, 0, 600, 200))
    hsv = yama.convert("HSV").tobytes()
    mavi = sum(1 for i in range(0, len(hsv), 3) if hsv[i + 1] >= 60 and 130 <= hsv[i] <= 220)
    assert mavi == 0
    assert yama.convert("L").crop((40, 80, 300, 130)).getextrema()[0] < 80      # siyah yazı duruyor


# ---------------------------------------------------------------- metin katmanlı PDF (OCR gerekmez)

def test_vektor_cizelge_sutun_cok_sayfa_ve_geri_basma(tmp_path):
    fitz = _fitz()
    info = {}

    def uret(p, i):
        info.update(S.vektor_cizelge(p, sayfa=2, tasan=(4,), imzali=i))
    rec, src, bos, dst = _maskele(tmp_path, "cizelge.pdf", uret)
    bol = rec["bolgeler"]
    assert all(set(b) - {"parcalar"} == KAYIT_ALANLARI for b in bol)
    sutun = [b for b in bol if b["kaynak"] == "imza_sutunu"]
    assert {b["sayfa"] for b in sutun} == {1, 2}, bol                         # başlık yalnız s.1'de
    assert any("devam" in b["neden"] for b in sutun if b["sayfa"] == 2)
    geri = [b for b in bol if b["geri_basilan"]]
    assert len(geri) == 1 and geri[0]["geri_basilan"] == "Arş. Gör." and geri[0]["karar"] == Y.KAPATILDI, bol
    assert not rec["elle_bakilmali"] and rec["durum"] == "tamam", rec
    n, kacan = S.kacirilan(src, bos, dst)
    assert n >= 28 and kacan == 0
    doc = fitz.open(str(dst))
    try:
        for b in sutun:
            pg = doc[b["sayfa"] - 1]
            assert _goruntu_temiz(pg, b["kutu"])                              # imza görüntüsü silindi
            # kutuda yalnız maskeleyicinin yazısı (yanındaki taşma kutusunun geri basılan yazısı dahil)
            assert all(t in "[İMZA] Arş. Gör. [imza gizlendi]" for t in _kutudaki_metin(pg, b["kutu"]).split())
        pg = doc[0]
        t = _kutudaki_metin(pg, geri[0]["kutu"])
        assert "Arş. Gör. [imza gizlendi]" in " ".join(t.split()), t           # ad/unvan geri basıldı
        assert _goruntu_temiz(pg, geri[0]["kutu"])
        txt = _metin(pg)
        assert "Mehmet Kaya" in txt and "Doç. Dr." in txt                      # ad/unvan sütunları açık
    finally:
        doc.close()


@pytest.mark.parametrize("etiket,e_imza,karar", [(True, False, Y.KAPATILDI), (False, False, Y.ONAY),
                                                 (False, True, Y.BIRAKILDI)])
def test_gomulu_gorsel_etiket_ve_e_imza(tmp_path, etiket, e_imza, karar):
    fitz = _fitz()
    rect = {}

    def uret(p, i):
        rect["r"] = S.metin_pdf_gorselli(p, etiket=etiket, e_imza=e_imza, imzali=i)
    rec, src, bos, dst = _maskele(tmp_path, "yazi.pdf", uret)
    bol = [b for b in rec.get("bolgeler") or [] if b["kaynak"] == "gomulu_gorsel"]
    if karar == Y.BIRAKILDI:     # e-imzalı belge: mürekkep/görüntü araması yapılmaz
        assert not rec["elle_bakilmali"], rec
        assert bol and all(b["karar"] == Y.BIRAKILDI and "e-imza" in b["neden"] for b in bol), rec
        return
    assert bol and bol[0]["karar"] == karar, rec
    assert rec["elle_bakilmali"] == (karar == Y.ONAY)
    if karar == Y.ONAY:          # onay bekleyen bölge insan kararına kadar açık; dosya pakete girmez (elle)
        return
    doc = fitz.open(str(dst))
    try:
        assert _goruntu_temiz(doc[0], rect["r"])
        if etiket:
            assert "Prof. Dr. Ayşe Demir" in _metin(doc[0])
    finally:
        doc.close()
    assert S.kacirilan(src, bos, dst)[1] == 0


# ---------------------------------------------------------------- taranmış sayfa (OCR)

@needs_ocr
def test_taranmis_cizelge_sutun_cok_sayfa_tasan_imza_onay(tmp_path):
    fitz = _fitz()
    rec, src, bos, dst = _maskele(tmp_path, "cizelge.pdf",
                                  lambda p, i: S.taranmis_cizelge(p, sayfa=2, tasan=(3,), imzali=i))
    bol = rec["bolgeler"]
    sutun = [b for b in bol if b["kaynak"] == "imza_sutunu" and b["karar"] == Y.KAPATILDI]
    assert {b["sayfa"] for b in sutun} == {1, 2}, bol
    # sütun yalnız İmza sütununu kaplar (ad/unvan açık): sınır 860-1140 px / 150 ppi
    for b in sutun:
        assert b["kutu"][0] >= 860 * 72 / 150 - 4 and b["kutu"][2] <= 1140 * 72 / 150 + 4, b
    # unvan yazısının üstüne taşan imza (en küçük yeterli maske): kapatma imza mürekkebine daraltılır, unvan
    # siyahın altında kalmaz; "geri basma gerekli mi" onayı gerekmez
    dar = [b for b in bol if b.get("parcalar") and "metinle örtüşen" in b["neden"]]
    assert dar and all(b["karar"] == Y.KAPATILDI and b["geri_basilan"] is None for b in dar), bol
    oneri = [b for b in bol if b["karar"] == Y.ONAY]
    assert all(b["kaynak"] == "imza_metin" and not b["kapali"] for b in oneri), bol   # satır bandı: öneri
    assert rec["kapatma_olcumu"]["siyah_altinda"] == 0, rec["kapatma_olcumu"]
    n, kacan = S.kacirilan(src, bos, dst)
    assert n >= 25 and kacan <= len(dar)          # metin satırında kalan vuruş görünebilir (çoğu kapalı)
    assert S.kacirilan(src, bos, dst, esik=0.5)[1] <= len(oneri)
    doc = fitz.open(str(dst))
    try:
        for b in sutun:
            assert _goruntu_temiz(doc[b["sayfa"] - 1], b["kutu"])               # tarama pikselleri silindi
        img = S.sayfa_goruntuleri(dst)[1]
        txt = " ".join(w.text for w in O.ocr_words(Y.cizgisiz(img, 150) or img))
        assert "Kerem" in txt or "Polat" in txt                                  # ad sütunu okunur
    finally:
        doc.close()


@needs_ocr
def test_renkli_cizelge_tasan_imza_murekkebi_ayrilir(tmp_path):
    rec, src, bos, dst = _maskele(tmp_path, "cizelge.pdf",
                                  lambda p, i: S.taranmis_cizelge(p, sayfa=1, satir=8, tasan=(2,), renk=S.MAVI, imzali=i))
    bol = rec["bolgeler"]
    assert any("renkli mürekkep ayrıldı" in b["neden"] for b in bol), bol
    assert not any(b["karar"] == Y.ONAY for b in bol) and not rec["elle_bakilmali"], rec
    assert S.kacirilan(src, bos, dst)[1] == 0
    out = S.sayfa_goruntuleri(dst)[0]
    hsv = out.convert("HSV").tobytes()
    assert sum(1 for i in range(0, len(hsv), 3) if hsv[i + 1] >= 80 and 130 <= hsv[i] <= 220) < 30   # mavi kalmadı
    txt = " ".join(w.text for w in O.ocr_words(Y.cizgisiz(out, 150) or out))
    assert "Kaya" in txt or "Mehmet" in txt                                     # unvan/ad korunur


@needs_ocr
def test_tutanak_imza_blogu_ve_ortusen(tmp_path):
    rec, src, bos, dst = _maskele(tmp_path, "tutanak.pdf", lambda p, i: S.tutanak(p, imzali=i))
    assert any(b["kaynak"] == "imza_blogu" for b in rec["bolgeler"]), rec
    assert not rec["elle_bakilmali"] and S.kacirilan(src, bos, dst)[1] == 0
    # ada taşan siyah imza (en küçük yeterli maske): kapatma mürekkebe daraltılır, ad/unvan okunur kalır,
    # imzanın çoğu kapalı; onay gerekmez
    rec, src, bos, dst = _maskele(tmp_path, "ortusen.pdf", lambda p, i: S.tutanak(p, ortusen=True, imzali=i))
    assert any(b.get("parcalar") and "metinle örtüşen" in b["neden"] for b in rec["bolgeler"]), rec
    oneri = [b for b in rec["bolgeler"] if b["karar"] == Y.ONAY]
    assert all(b["kaynak"] == "imza_metin" and not b["kapali"] for b in oneri), rec
    assert S.kacirilan(src, bos, dst, esik=0.5)[1] <= len(oneri)
    tz = tmp_path / "temiz" / "ortusen.pdf"                  # öneri çerçevesiz (teslim) kopya
    out = S.sayfa_goruntuleri(tz if tz.is_file() else dst)[0]
    t = " ".join(w.text for w in O.ocr_words(out.crop((100, 1290, 700, 1420))))
    assert "Bölüm" in t and ("Demir" in t or "emir" in t), t
    # aynı imza mavi: mürekkep ayrılır, ad görünür kalır, onay gerekmez
    rec, src, bos, dst = _maskele(tmp_path, "mavi.pdf",
                                  lambda p, i: S.tutanak(p, ortusen=True, renk=S.MAVI, imzali=i))
    assert not rec["elle_bakilmali"] and S.kacirilan(src, bos, dst)[1] == 0, rec
    out = S.sayfa_goruntuleri(dst)[0]
    t = " ".join(w.text for w in O.ocr_words(out.crop((100, 1290, 700, 1420))))
    assert "Ayşe" in t and "Prof." in t, t        # alttaki ad okunur kalır (kesişen vuruşta harf zedelenebilir)


@needs_ocr
def test_gorsel_dosya_tutanak(tmp_path):
    rec, src, bos, dst = _maskele(tmp_path, "tutanak.png", lambda p, i: S.tutanak(p, imzali=i))
    assert rec["bolgeler"] and all(set(b) - {"parcalar"} == KAYIT_ALANLARI for b in rec["bolgeler"])
    assert not rec["elle_bakilmali"] and S.kacirilan(src, bos, dst)[1] == 0, rec


@needs_ocr
def test_yanlis_alarm_suzgecleri(tmp_path):
    for ad, uret, neden in (("logo.pdf", lambda p, i: S.tekrar_eden_logo(p), "tekrarlayan"),
                            ("kase.pdf", lambda p, i: S.kaseli_sayfa(p), "kaşe"),
                            ("not.pdf", lambda p, i: S.not_dokumu(p), "basılı sayfa")):
        rec, *_ = _maskele(tmp_path, ad, uret)
        bol = rec.get("bolgeler") or []
        assert bol and all(b["karar"] == Y.BIRAKILDI for b in bol), (ad, bol)
        assert any(neden in b["neden"] for b in bol), (ad, bol)
        assert not rec["elle_bakilmali"], (ad, rec)


@needs_ocr
def test_etiket_yakinindaki_tekrar_suzulmez(tmp_path):
    """Her sayfaya yapıştırılmış aynı imza "İmza:" etiketinin yanında: tekrar sayılmaz, kapatılır."""
    rec, src, bos, dst = _maskele(tmp_path, "yapistirma.pdf",
                                  lambda p, i: S.tekrar_eden_logo(p, sayfa=2, etiketli=True, imzali=i))
    kap = [b for b in rec["bolgeler"] if b["karar"] == Y.KAPATILDI]
    assert {b["sayfa"] for b in kap} == {1, 2}, rec["bolgeler"]
    assert S.kacirilan(src, bos, dst)[1] == 0


@needs_ocr
def test_imza_bolgeleri_tek_islev_kararli(tmp_path):
    p = tmp_path / "cizelge.pdf"
    S.taranmis_cizelge(p, sayfa=2, imzali=True)
    a = Y.imza_bolgeleri(p)
    b = Y.imza_bolgeleri(p)
    assert a == b and a and all(x["id"].split("-s")[0] == a[0]["id"].split("-s")[0] for x in a)
    assert all(set(x) - {"parcalar"} == KAYIT_ALANLARI for x in a)
