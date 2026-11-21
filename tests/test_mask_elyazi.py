"""El yazısıyla doldurulmuş form alanları: alan geometrisi (dört yön, kılavuz/alt çizgi/tarak/hücre),
etiketsiz rakam dizisi sezgisi, form şablon belleği ve bölge sözleşmesi. Yalnız sentetik veri
(`elyazi_synth`): basılı etiketler + el yazısı benzeri rakamlar; gerçek kişi/kurum/numara yok."""
from __future__ import annotations

import io
import json

import pytest

pytest.importorskip("numpy")
PIL = pytest.importorskip("PIL")
from PIL import ImageFont  # noqa: E402

try:
    ImageFont.load_default(size=12)
except TypeError:                                   # pragma: no cover
    pytest.skip("Pillow ölçeklenebilir varsayılan yazı tipi yok", allow_module_level=True)

from bidr.mask import alan as AL  # noqa: E402
from bidr.mask import ocr as O  # noqa: E402
from bidr.mask import sablon as SB  # noqa: E402

import elyazi_synth as S  # noqa: E402

needs_ocr = pytest.mark.skipif(not O.ocr_available(), reason="tesseract + tur/eng yok")


def regions(F, **kw):
    return AL.el_yazisi_bolgeleri(F.img, F.words, dosya="d0c1d2e3", **kw)


def boxes(regs, karar="kapatildi", kaynak=None):
    return [tuple(r["kutu"]) for r in regs if r["karar"] == karar and (kaynak is None or r["kaynak"] == kaynak)]


def assert_closed(F, regs, frac=0.9):
    kap = boxes(regs)
    for k, v in F.vals.items():
        assert S.covered(v, kap, frac), (k, v, regs)
    alls = [tuple(r["kutu"]) for r in regs]
    for kb in F.keep:
        assert not S.hits(kb, alls), (kb, regs)


# ---------------------------------------------------------------- alan geometrisi

@pytest.mark.parametrize("name,yapi", [("sag_nokta", "noktalı kılavuz"), ("alt_cizgi", "alt çizgi"),
                                       ("tarak", "kutucuk dizisi"), ("tablo", "tablo hücresi"),
                                       ("ust", "alt çizgi")])
def test_field_geometry_four_directions(name, yapi):
    """Sağdaki noktalı kılavuz, alttaki alt çizgi, kutucuk dizisi, tablo hücresi ve çizginin altındaki
    açıklama etiketi ("(T.C. Kimlik No)": değer üstte). Ad alanı ve basılı metin açık kalır."""
    F = S.FORMLAR[name](0)
    regs = regions(F)
    assert_closed(F, regs)
    ea = [r for r in regs if r["kaynak"] == "etiket_alani" and r["karar"] == "kapatildi"]
    assert ea and any(yapi in r["neden"] for r in ea), regs
    if name == "ust":
        assert any("üstünde" in r["neden"] for r in ea)
    if name == "alt_cizgi":
        assert any("altında" in r["neden"] for r in ea)


@pytest.mark.parametrize("name", ["sag_nokta", "alt_cizgi", "tarak", "tablo", "ust", "bos"])
@pytest.mark.parametrize("deg", [2.0, -2.5])
def test_skewed_scan(name, deg):
    F = S.rotate(S.FORMLAR[name](1), deg)
    assert_closed(F, regions(F), 0.85)


def test_empty_guided_field_is_closed():
    """Boş görünen alan da kapatılır (kaçırma pahalı): kılavuz varsa alan bellidir."""
    F = S.form_bos()
    regs = regions(F)
    assert_closed(F, regs)
    assert any("boş görünüyor" in r["neden"] for r in regs)
    assert AL.find_fields(F.img, F.words)               # raster hattı (find_fields) da kapatır


def test_label_without_any_field_is_pending():
    """Güçlü etiket var, ne kılavuz ne mürekkep: alan yeri belirsiz → kapatılmaz, onaya düşer."""
    F = S.Form()
    F.text(100, 300, "T.C. Kimlik No:")
    regs = regions(F)
    assert [r["karar"] for r in regs] == ["onay_bekliyor"] and "alan bulunamadı" in regs[0]["neden"]
    assert AL.find_fields(F.img, F.words) == []          # eski davranış: kapatılacak bir şey yok


def test_old_fixed_right_box_assumption_removed():
    """Etiketin sağı boş, değer alttaki çizgide: eski kural (yalnız sağ / `:`'sız tablo altı) bulamazdı."""
    F = S.form_alt_cizgi(0)
    old_like = AL.find_fields(F.img, F.words)
    assert S.covered(F.vals["ogrenci_no"], [f.box for f in old_like], 0.9)


def test_ocr_typo_labels():
    W = lambda t: O.Word(t, 90, 0, 0, 1, 1, (1, 1, 1, 1))  # noqa: E731
    assert AL._find_labels([W("Kim1ik"), W("N0:")])[0][0] == "tc_no"
    assert AL._find_labels([W("T.C."), W("Kimllk"), W("No")])[0][0] == "tc_no"
    assert AL._find_labels([W("Ogrencl"), W("Numarasi")])[0][0] == "ogrenci_no"
    assert AL._find_labels([W("Te1efon:")])[0][0] == "telefon"
    assert AL._find_labels([W("Dogum"), W("Tarıhı")])[0][0] == "dogum_tarihi"
    assert AL._find_labels([W("Telekom")]) == [] and AL._find_labels([W("Dogan")]) == []


# ---------------------------------------------------------------- rakam dizisi

def test_unlabeled_eleven_digit_sequence_pending():
    F = S.form_etiketsiz(0)
    regs = regions(F)
    rd = [r for r in regs if r["kaynak"] == "rakam_dizisi"]
    assert len(rd) == 1 and rd[0]["karar"] == "onay_bekliyor" and "11" in rd[0]["neden"]
    assert S.covered(F.vals["tc_no"], boxes(regs, "onay_bekliyor"), 0.95)
    F2 = S.rotate(S.form_etiketsiz(2), -2.5)
    assert S.covered(F2.vals["tc_no"], boxes(regions(F2), "onay_bekliyor"), 0.9)


def test_digit_sequence_near_label_closed_and_name_field_skipped():
    """Kimlik etiketinin ALTINDA (alan geometrisi bulamıyor: `:`'lı, kılavuzsuz) 11 haneli dizi → kapatılır;
    "Bölümü:" alanındaki 11 bileşenli dizi kişisel olmayan etiketin değeri → bölge değil."""
    F = S.Form()
    F.text(420, 100, "DILEKCE")
    b = F.text(100, 300, "T.C. Kimlik No:")
    F.text(700, 300, "Uyruk:")
    F.vals["tc_no"] = S.digits(F.d, "10000000146", 110, b[3] + 14, seed=3)
    b2 = F.text(100, 600, "Bölümü:")
    F.keep.append(S.digits(F.d, "12121212121", b2[2] + 30, 596, seed=4))
    regs = regions(F)
    rd = [r for r in regs if r["kaynak"] == "rakam_dizisi"]
    assert S.covered(F.vals["tc_no"], boxes(regs), 0.95), regs
    assert rd and rd[0]["karar"] == "kapatildi" and "etiket yakınında" in rd[0]["neden"]
    assert not any(S.hits(k, [tuple(r["kutu"]) for r in regs]) for k in F.keep)


def test_negative_page_has_no_regions():
    F = S.form_negatif(0)
    assert regions(F) == []


@needs_ocr
def test_ocr_reading_digits_does_not_hide_sequence():
    """OCR el yazısını (yanlış da olsa) rakam olarak okusa da dizi aday kalır; okuyamasa da."""
    F = S.form_etiketsiz(1)
    ws = O.ocr_words(F.img)
    regs = AL.el_yazisi_bolgeleri(F.img, ws, dosya="x")
    assert S.covered(F.vals["tc_no"], [tuple(r["kutu"]) for r in regs], 0.9), regs


# ---------------------------------------------------------------- bölge sözleşmesi

def test_region_contract_ids_points_and_decisions():
    F = S.form_sag_nokta(0)
    sc = 1240 / 595.0
    r1 = AL.el_yazisi_bolgeleri(F.img, F.words, sayfa=2, dosya="ab12cd34", olcek=sc)
    r2 = AL.el_yazisi_bolgeleri(F.img, F.words, sayfa=2, dosya="ab12cd34", olcek=sc)
    assert [r["id"] for r in r1] == [r["id"] for r in r2]                 # kararlı kimlik
    assert r1[0]["id"] == "ab12cd34-s2-1"
    for r in r1:
        assert set(r) == {"id", "sayfa", "kutu", "tur", "karar", "neden", "kaynak", "guven", "geri_basilan"}
        assert r["tur"] == "el_yazisi_alan" and r["sayfa"] == 2 and r["geri_basilan"] is None
        assert r["kaynak"] in ("etiket_alani", "rakam_dizisi", "sablon") and 0 <= r["guven"] <= 1
        assert all(0 <= v <= 842 for v in r["kutu"])                       # PDF puanı
    px = AL.el_yazisi_bolgeleri(F.img, F.words, sayfa=2, dosya="ab12cd34")
    assert abs(px[0]["kutu"][2] / sc - r1[0]["kutu"][2]) < 0.05
    r3 = AL.el_yazisi_bolgeleri(F.img, F.words, sayfa=2, dosya="ab12cd34", kararlar={r1[0]["id"]: "birak"})
    assert r3[0]["karar"] == "birakildi" and r3[1]["karar"] == "kapatildi"
    assert "1234567" not in json.dumps(r1)                                # değer yazılmaz


# ---------------------------------------------------------------- şablon belleği

def test_template_learned_from_decision_and_applied_to_second_copy(tmp_path):
    mem = SB.SablonBellegi.calisma_alani(tmp_path)
    A = S.form_sablon(0)
    ra = regions(A, sablonlar=mem)
    pend = [r for r in ra if r["karar"] == "onay_bekliyor"]
    assert len(pend) == 1 and pend[0]["kaynak"] == "rakam_dizisi"
    # insan kararı: kapat → şablona öğretilir (kararlar dosyasındaki "kapat")
    ra2 = regions(A, sablonlar=mem, kararlar={pend[0]["id"]: "kapat"})
    assert ra2[0]["karar"] == "kapatildi"
    data = json.loads((tmp_path / SB.DOSYA).read_text(encoding="utf-8"))
    assert len(data["sablonlar"]) == 1 and len(data["sablonlar"][0]["bolgeler"]) == 1
    raw = json.dumps(data)
    assert "OGRENCI" not in raw and "ogrenci" not in raw                  # belirteçler özetli
    # ikinci kopya: başka el yazısı (rakam dizisi sezgisi bulamaz), yeniden taranmış (ölçek/dönme/öteleme)
    B = S.affine(S.form_sablon(1, deger="karalama"), scale=0.95, deg=1.2, dx=30, dy=-18)
    mem2 = SB.SablonBellegi.calisma_alani(tmp_path)                     # dosyadan yeniden yüklenir
    rb = regions(B, sablonlar=mem2)
    sb = [r for r in rb if r["kaynak"] == "sablon"]
    assert len(sb) == 1 and sb[0]["karar"] == "kapatildi", rb
    assert S.covered(B.vals["tc_no"], boxes(rb), 0.9)
    assert not any(S.hits(k, boxes(rb)) for k in B.keep)


def test_template_alignment_failure_is_pending(tmp_path):
    mem = SB.SablonBellegi.calisma_alani(tmp_path)
    A = S.form_sablon(0)
    ra = regions(A, sablonlar=mem)
    regions(A, sablonlar=mem, kararlar={ra[0]["id"]: "kapat"})
    # aynı basılı metin, başka düzen: parmak izi eşleşir, hizalama tutmaz → otomatik kapatılmaz
    C = S.form_sablon(2, deger="karalama", karisik=True)
    rc = regions(C, sablonlar=SB.SablonBellegi.calisma_alani(tmp_path))
    sb = [r for r in rc if r["kaynak"] == "sablon"]
    assert len(sb) == 1 and sb[0]["karar"] == "onay_bekliyor" and "hizalama güvenilmez" in sb[0]["neden"], rc
    assert not boxes(rc)


def test_template_fingerprint_ignores_handwriting_and_other_forms(tmp_path):
    mem = SB.SablonBellegi(tmp_path / SB.DOSYA)
    A = S.form_sablon(0)
    iz = SB.parmak_izi(A.words + [O.Word("Yilmazoglu", 40, 300, 900, 500, 940, (9, 9, 9, 9))], 1240, 1754)
    assert len(iz["capalar"]) == len(SB.parmak_izi(A.words, 1240, 1754)["capalar"])  # düşük güvenli el yazısı yok
    mem.ogren(iz, [(300, 900, 700, 950)], kaynak="x-s1")
    assert mem.eslestir(SB.parmak_izi(S.form_sag_nokta(0).words, 1240, 1754)) is None   # başka form
    al = SB.hizala(mem.sablonlar[0], SB.parmak_izi(S.affine(A, 1.05, -1.0, -20, 25).words, 1240, 1754))
    assert al["guvenilir"] and al["hata"] < 2.0 and abs(al["T"][0] - 1.05) < 0.01


# ---------------------------------------------------------------- kapatma gerçek silme

def test_redaction_removes_handwritten_pixels(tmp_path):
    """Taranmış PDF: kapatılan bölgelerin altındaki görüntü pikselleri gerçekten değişir (üst katman değil)."""
    fitz = pytest.importorskip("pymupdf")
    from bidr.mask.formats import _redact_flags
    F = S.form_tarak(0)
    buf = io.BytesIO()
    F.img.save(buf, format="PNG")
    doc = fitz.open()
    pg = doc.new_page(width=595, height=842)
    pg.insert_image(pg.rect, stream=buf.getvalue())
    sc = F.img.width / 595.0
    regs = AL.el_yazisi_bolgeleri(F.img, F.words, dosya="t", olcek=sc)
    kap = [r for r in regs if r["karar"] == "kapatildi"]
    assert kap
    for r in kap:
        pg.add_redact_annot(fitz.Rect(*r["kutu"]), fill=(0, 0, 0))
    pg.apply_redactions(**_redact_flags(fitz))
    out = tmp_path / "m.pdf"
    doc.save(str(out))
    d2 = fitz.open(str(out))
    xref = d2[0].get_images()[0][0]
    from PIL import Image
    im = Image.open(io.BytesIO(d2.extract_image(xref)["image"])).convert("RGB")
    fx = im.width / F.img.width
    x0, y0, x1, y1 = F.vals["tc_no"]
    crop = im.crop((int(x0 * fx) + 2, int(y0 * fx) + 2, int(x1 * fx) - 2, int(y1 * fx) - 2))
    blue = sum(1 for p in crop.getdata() if p[2] > 120 and p[0] < 90)
    assert blue == 0                                  # el yazısı mürekkebi görüntünün kendisinden silindi
    assert len(set(crop.getdata())) == 1              # alan tek renk (PyMuPDF görüntü pikselini boşaltır)
    page_px = d2[0].get_pixmap(dpi=72, clip=fitz.Rect(*[v / sc for v in F.vals["tc_no"]]))
    assert max(page_px.samples) < 60                  # sayfada siyah kutu
    for kb in F.keep:                                 # basılı etiket açık
        c = im.crop(tuple(int(v * fx) for v in kb))
        assert min(min(p) for p in c.getdata()) < 100 and max(max(p) for p in c.getdata()) > 200
