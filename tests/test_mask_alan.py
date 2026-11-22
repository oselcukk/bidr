"""Kişisel veri etiketinin alanı (el yazısıyla doldurulmuş form/dilekçe), modelin okuma metniyle el
yazısı denetimi ve öğrenci numarası desenleri. Yalnız sentetik veri: basılı etiket + el yazısı
benzeri karalama (okunamayan dalgalı çizgi); kurum/kişi adı yok."""
from __future__ import annotations

import csv
import json
import math
from collections import Counter
from pathlib import Path

import pytest

from bidr.mask import MaskRules, detect
from bidr.mask import alan as AL
from bidr.mask import ocr as O
from bidr.mask import run as R
from bidr.mask.detect import institution_patterns

from test_mask import PHONE, TC1

PIL = pytest.importorskip("PIL")
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

needs_ocr = pytest.mark.skipif(not O.ocr_available(), reason="tesseract + tur/eng yok")


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        pytest.skip("Pillow ölçeklenebilir varsayılan yazı tipi yok")


def scribble(d: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int = 40, seed: int = 0, color=(25, 45, 170)):
    """El yazısı benzeri karalama: okunamayan dalgalı çizgi kümesi (OCR rakam/harf çıkaramaz)."""
    pts = []
    for i in range(int(w / 3)):
        t = i / max(1, int(w / 3) - 1)
        pts.append((x + t * w, y + h / 2 + h / 2.4 * math.sin(t * w / 9 + seed) * math.cos(t * 7 + seed)))
    d.line(pts, fill=color, width=3, joint="curve")
    return (x, y, x + w, y + h)


# A4 ~150 ppi form: basılı etiketler (sola dayalı, ':' ile), değerler karalama. → (görüntü, değer kutuları
# {tür: kutu}, korunması gereken basılı satır kutuları)
def make_form(*, labels=True, body_line=True):
    img = Image.new("RGB", (1240, 1754), "white")
    d = ImageDraw.Draw(img)
    f = _font(30)
    keep = []
    d.text((420, 120), "BASVURU FORMU", fill="black", font=f)
    y = 260
    vals = {}
    rows = [("Kimlik No:", "tc_no"), ("Dogum Tarihi:", "dogum_tarihi"), ("Telefon:", "telefon"),
            ("E-posta:", "eposta"), ("Ogrenci No:", "ogrenci_no"), ("Adres:", "adres")]
    for i, (lab, kind) in enumerate(rows):
        if labels:
            d.text((100, y), lab, fill="black", font=f)
            keep.append(d.textbbox((100, y), lab, font=f))
        lw = d.textbbox((100, y), lab, font=f)[2]
        vals[kind] = scribble(d, lw + 40, y - 6, 420, seed=i)
        y += 90
    if body_line:
        d.text((100, y + 60), "Karar metni oy birligi ile kabul edilmistir.", fill="black", font=f)
        keep.append(d.textbbox((100, y + 60), "Karar metni oy birligi ile kabul edilmistir.", font=f))
    return img, vals, keep


def _covered(box, fields, frac=0.9) -> bool:
    x0, y0, x1, y1 = box
    area = (x1 - x0) * (y1 - y0)
    best = 0.0
    for fb in fields:
        ix = max(0.0, min(x1, fb[2]) - max(x0, fb[0]))
        iy = max(0.0, min(y1, fb[3]) - max(y0, fb[1]))
        best = max(best, ix * iy / area)
    return best >= frac


def _hits(box, fields) -> bool:
    return any(min(box[2], f[2]) > max(box[0], f[0]) and min(box[3], f[3]) > max(box[1], f[1]) for f in fields)


def W(text, x0, y0, x1, y1, line=1, conf=95.0):
    return O.Word(text, conf, x0, y0, x1, y1, (1, 1, line, 1))


# ---------------------------------------------------------------- alan geometrisi (OCR'sız: kurgu kelimeler)

def test_fields_from_label_words_without_ocr():
    img = Image.new("RGB", (1240, 900), "white")
    d = ImageDraw.Draw(img)
    v1 = scribble(d, 330, 194, 400)
    v2 = scribble(d, 330, 294, 380, seed=2)
    v3 = scribble(d, 830, 294, 300, seed=3)       # "Uyruk:" alanı (kişisel etiket değil)
    words = [W("T.C.", 100, 200, 150, 230, 1), W("Kimlik", 160, 200, 240, 230, 1), W("No:", 250, 200, 300, 230, 1),
             W("Telefon:", 100, 300, 210, 330, 2), W("Uyruk:", 740, 300, 820, 330, 2)]
    fields = AL.find_fields(img, words)
    boxes = [f.box for f in fields]
    assert {f.kind for f in fields} == {"tc_no", "telefon"}
    assert _covered(v1, boxes) and _covered(v2, boxes)
    assert not _hits(v3, boxes)                       # sonraki etiketin alanına taşmaz
    assert not any(_hits(w.box, boxes) for w in words)  # etiketlerin kendisi açık kalır


def test_name_label_is_never_a_field():
    img = Image.new("RGB", (1240, 600), "white")
    d = ImageDraw.Draw(img)
    scribble(d, 330, 194, 400)
    words = [W("Adı", 100, 200, 150, 230), W("Soyadı:", 160, 200, 260, 230)]
    assert AL.find_fields(img, words) == []


def test_running_text_label_is_not_a_field():
    img = Image.new("RGB", (1240, 600), "white")
    d = ImageDraw.Draw(img)
    scribble(d, 600, 194, 300)
    ws = [W("Basvuran", 100, 200, 220, 230), W("ogrenci", 230, 200, 330, 230), W("numarasi", 340, 200, 460, 230),
          W("ile", 470, 200, 510, 230), W("kayit", 520, 200, 590, 230)]
    assert AL.find_fields(img, ws) == []


def test_empty_or_already_masked_field_is_skipped():
    img = Image.new("RGB", (1240, 600), "white")
    d = ImageDraw.Draw(img)
    words = [W("Kimlik", 100, 200, 190, 230), W("No:", 200, 200, 250, 230)]
    # m5: boş alan kapatılmaz (en küçük yeterli maske)
    assert AL.find_fields(img, words) == []
    d.rectangle([255, 170, 1220, 260], fill=0)        # önceki kapatma (yeniden tarama)
    assert AL.find_fields(img, words) == []


def test_weak_label_footer_and_printed_value_not_fields():
    """Kurumsal altlık: sayfa alt bandında "Tel:" / "E-posta:" ve basılı değer; zayıf etiket alınmaz.
    Gövdede güçlü etiketsiz sayfada basılı (güvenle okunan) değerli zayıf etiket de alınmaz."""
    img = Image.new("RGB", (1240, 1754), "white")
    d = ImageDraw.Draw(img)
    f = _font(28)
    d.text((240, 1660), "0262 000 00 00", fill="black", font=f)
    d.text((240, 400), "0262 000 00 00", fill="black", font=f)
    words = [W("Tel:", 100, 1660, 160, 1690, 1), W("0262", 240, 1660, 310, 1690, 1), W("000", 320, 1660, 370, 1690, 1),
             W("Telefon:", 100, 400, 220, 430, 2), W("0262", 240, 400, 310, 430, 2),
             W("000", 320, 400, 370, 430, 2), W("00", 380, 400, 410, 430, 2), W("00", 420, 400, 450, 430, 2)]
    assert AL.find_fields(img, words) == []


def test_weak_label_with_handwriting_is_field():
    img = Image.new("RGB", (1240, 1754), "white")
    d = ImageDraw.Draw(img)
    v = scribble(d, 260, 394, 400)
    words = [W("Telefon:", 100, 400, 220, 430)]
    fs = AL.find_fields(img, words)
    assert [f.kind for f in fs] == ["telefon"] and _covered(v, [f.box for f in fs])


def test_table_cell_label_value_in_next_cell_and_below():
    img = Image.new("RGB", (1240, 900), "white")
    d = ImageDraw.Draw(img)
    for x in (80, 400, 900):                              # dikey tablo çizgileri
        d.line([(x, 150), (x, 420)], fill="black", width=3)
    for y in (150, 260, 340, 420):
        d.line([(80, y), (900, y)], fill="black", width=3)
    v1 = scribble(d, 440, 185, 400)                       # "Kimlik No" | değer (sağdaki hücre)
    v2 = scribble(d, 100, 360, 260, h=40, seed=4)         # "Ogrenci No" başlığı; değer alttaki hücrede
    words = [W("Kimlik", 100, 190, 190, 222, 1), W("No", 200, 190, 240, 222, 1),
             W("Ogrenci", 100, 280, 210, 312, 2), W("No", 220, 280, 260, 312, 2)]
    fs = AL.find_fields(img, words)
    boxes = [f.box for f in fs]
    assert _covered(v1, boxes)
    assert all(b[0] >= 400 or b[1] >= 312 for b in boxes)  # etiket hücresi açık
    assert _covered(v2, boxes, 0.8)


def test_address_extends_to_next_line():
    img = Image.new("RGB", (1240, 900), "white")
    d = ImageDraw.Draw(img)
    v1 = scribble(d, 250, 194, 500)
    v2 = scribble(d, 100, 250, 450, seed=5)               # adresin ikinci satırı (etiketin altında)
    v3 = scribble(d, 330, 400, 300, seed=6)               # sonraki etiketin değeri
    words = [W("Adres:", 100, 200, 200, 230, 1), W("Telefon:", 100, 400, 220, 430, 3),
             W("KARAR", 100, 330, 200, 360, 2)]
    fs = AL.find_fields(img, words)
    adres = [f.box for f in fs if f.kind == "adres"]
    assert _covered(v1, adres) and _covered(v2, adres, 0.8)
    assert not _hits((100, 330, 200, 360), adres)          # alttaki başlık/etiket satırına inmez
    assert _covered(v3, [f.box for f in fs if f.kind == "telefon"])


def test_label_and_value_in_one_ocr_token():
    img = Image.new("RGB", (1240, 600), "white")
    d = ImageDraw.Draw(img)
    v = scribble(d, 230, 194, 400)
    fs = AL.find_fields(img, [W("Telefon:....xx..", 100, 200, 640, 230, conf=40)])
    assert [f.kind for f in fs] == ["telefon"] and _covered(v, [f.box for f in fs], 0.75)


def test_label_normalization():
    assert AL._find_labels([W("T.C.", 0, 0, 1, 1), W("KİMLİK", 0, 0, 1, 1), W("NO", 0, 0, 1, 1)])[0][0] == "tc_no"
    assert AL._find_labels([W("E", 0, 0, 1, 1), W("-", 0, 0, 1, 1), W("posta:", 0, 0, 1, 1)])[0][0] == "eposta"
    assert AL._find_labels([W("Öğrenci", 0, 0, 1, 1), W("Numarası", 0, 0, 1, 1)])[0][0] == "ogrenci_no"
    assert AL._find_labels([W("GSM:", 0, 0, 1, 1)])[0][:2] == ("telefon", True)
    assert AL._find_labels([W("Ev", 0, 0, 1, 1), W("Adresi", 0, 0, 1, 1)])[0][:2] == ("adres", True)
    assert AL._find_labels([W("Telefon", 0, 0, 1, 1)])[0][:2] == ("telefon", False)
    assert AL._find_labels([W("Adı", 0, 0, 1, 1), W("Soyadı", 0, 0, 1, 1)]) == []
    assert AL._find_labels([W("Telekom", 0, 0, 1, 1)]) == []


def test_label_fields_can_be_disabled():
    r = MaskRules.from_config({"privacy": {"maskeleme": {"etiket_alani": False}}})
    assert r.label_fields is False and MaskRules().label_fields is True


# ---------------------------------------------------------------- OCR ile (tesseract)

@needs_ocr
def test_form_image_handwritten_fields_masked(tmp_path):
    from bidr.mask import raster as RA
    img, vals, keep = make_form()
    src = tmp_path / "form.png"
    img.save(src)
    r = RA.scan_image_obj(img, MaskRules())
    boxes = [b for b, k in zip(r.kutular, r.turler) if k == "etiket_alani"]
    for kind, v in vals.items():
        assert _covered(v, boxes, 0.85), kind
    assert not any(_hits(k, boxes) for k in keep)
    assert r.bulgular["etiket_alani"] >= len(vals)
    out = tmp_path / "out.png"
    res = RA.mask_image(src, out, MaskRules())
    assert res["maskelenen"]["etiket_alani"] >= len(vals)
    cov = res["sayfa_kapsam"][1]
    assert cov["tc_no"] >= 1 and cov["telefon"] >= 1 and cov["ogrenci_no"] >= 1
    after = RA.scan_image(out, MaskRules())
    assert not after["bulgular"].get("etiket_alani"), after   # yeniden taramada kalan alan yok
    # karar metni ve basılı etiketler açık: o bölgelerin pikselleri değişmedi
    masked = Image.open(out).convert("RGB")
    for x0, y0, x1, y1 in keep:
        assert list(masked.crop((x0, y0, x1, y1)).getdata()) == list(img.crop((x0, y0, x1, y1)).getdata())


@needs_ocr
def test_scanned_pdf_fields_and_model_text_check(tmp_path):
    """Kanıt modu: s.1 basılı etiketli form (alanlar kapanır), s.2 etiketi de el yazısı (kapatılamaz):
    modelin okuma metni s.2'de kimlik no/telefon gösteriyor → dosya elle bakılmalı, değer rapora yazılmaz."""
    fitz = pytest.importorskip("pymupdf")
    import io
    ws = tmp_path / "ws"
    p1, _, _ = make_form()
    p2, _, _ = make_form(labels=False)
    doc = fitz.open()
    for im in (p1, p2):
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        pg = doc.new_page(width=595, height=842)
        pg.insert_image(pg.rect, stream=buf.getvalue())
    (ws / "evidence/A").mkdir(parents=True)
    doc.save(str(ws / "evidence/A/form.pdf"))
    (ws / "text").mkdir()
    (ws / "text/abc123.txt").write_text(
        f"BASVURU FORMU\nKimlik No: {TC1}\nTelefon: {PHONE}\n\f[el yazısı]\nKimlik No: {TC1}\nTelefon: {PHONE}\n",
        encoding="utf-8")
    with open(ws / "evidence-index.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["kanit_no", "dosya", "doc_id"])
        w.writerow(["1", "A/form.pdf", "abc123"])
    rep = R.run(ws, engine="pymupdf")
    rec = rep["dosyalar"][0]
    assert rec["model_metni"] and rec["maskelenen"].get("etiket_alani", 0) >= 5, rec
    assert rec["el_yazisi_elle"] == ["s.2: kimlik no, telefon"], rec
    assert rec["durum"] == "basarisiz" and R.EL_YAZISI_SORUN in rec["neden"]
    raw = json.dumps(rep, ensure_ascii=False)
    assert TC1 not in raw and PHONE not in raw
    assert rep["ozet"]["el_yazisi_elle_dosya"] == 1


# ---------------------------------------------------------------- model metni denetimi (OCR'sız)

def test_model_text_gaps_counts_per_page():
    rules = MaskRules()
    text = f"a\nTelefon: {PHONE}\n\fKimlik: {TC1}\nTel: {PHONE}\n\f\n"
    res = {"sayfa_sayisi": 3, "sayfa_kapsam": {1: {"telefon": 1}, 2: {"telefon": 1}, 3: {}}}
    gaps, note = R.model_text_gaps(text, res, rules)
    assert gaps == ["s.2: kimlik no"] and note is None
    gaps, note = R.model_text_gaps("x\fy", res, rules)
    assert gaps == [] and "sayfa sayısı" in note
    gaps, note = R.model_text_gaps(text, {"maskelenen": Counter({"telefon": 2})}, rules)
    assert gaps == ["belge: kimlik no"] and note is None


def test_source_mode_uses_inventory_model_text(tmp_path):
    from bidr.mask.kaynak import run_source
    src = tmp_path / "kaynak"
    src.mkdir()
    (src / "not.txt").write_text("toplanti notu\n", encoding="utf-8")
    ws = tmp_path / "ws"
    (ws / "text").mkdir(parents=True)
    (ws / "text/d1.txt").write_text(f"[el yazısı] Telefon: {PHONE}\n", encoding="utf-8")
    (ws / "inventory.csv").write_text("doc_id,rel_path\nd1,not.txt\n", encoding="utf-8")
    rep = run_source(src, tmp_path / "out", ws=ws)
    rec = rep["dosyalar"][0]
    assert rec["model_metni"] and rec["el_yazisi_elle"] == ["belge: telefon"] and rec["elle_bakilmali"]
    assert PHONE not in json.dumps(rep, ensure_ascii=False)
    rep = run_source(src, tmp_path / "out2")             # çalışma alanı yok: denetim yok
    assert not rep["dosyalar"][0].get("el_yazisi_elle") and rep["dosyalar"][0]["durum"] == "tamam"


# ---------------------------------------------------------------- öğrenci numarası desenleri

def _kinds(t, rules=None):
    return [f.kind for f in detect(t, rules or MaskRules())]


def test_default_student_pattern_twelve_digits_and_false_positives():
    assert _kinds("No | 202105001234 | Ad") == ["ogrenci_no"]          # 12 hane, dört haneli yıl önekli
    assert _kinds("2021999001") == ["ogrenci_no"]                       # 10 hane (önceki davranış)
    assert _kinds("20219990012") == []                                  # 11 hane: alınmaz
    assert _kinds("Tel 05321234567") == ["telefon"]
    assert _kinds("+90 532 123 45 67") == ["telefon"]
    assert _kinds("905321234567") == []                                 # 90 önekli: öğrenci no değil
    assert _kinds("Proje No: 202012345678") == []                       # belge kimliği bağlamı
    assert _kinds("E-202012345678") == [] and _kinds("202012345678-1") == []
    assert _kinds("TR33 0006 1005 1978 6457 8413 26") in ([], ["iban"])  # IBAN parçası öğrenci no olmaz
    assert "ogrenci_no" not in _kinds("TR330006100519786457841326")


def test_institution_profile_adds_twelve_digit_pattern():
    cfg = {"bidr": {"kurum": "gtu"}}
    pats = institution_patterns(cfg)
    assert pats, "gtu profilinde öğrenci no deseni yok"
    r = MaskRules.from_config(cfg)
    assert len(r.student_patterns) == len(MaskRules().student_patterns) + len(pats)
    assert _kinds("Ogr | 240502050045 | Kimya", r) == ["ogrenci_no"]    # iki haneli yıl önekli 12 hane
    assert _kinds("240502050045", MaskRules()) == []                   # varsayılan bunu almaz
    assert _kinds("Sayı: 240502050045", r) == []                       # belge kimliği bağlamı
    assert _kinds("05321234567 ve 905321234567", r) == ["telefon"]
    assert "ogrenci_no" not in _kinds("TR330006100519786457841326", r)
    # çalışma alanı desenleri yerine geçmez, eklenir
    r2 = MaskRules.from_config({"bidr": {"kurum": "gtu"},
                                "privacy": {"maskeleme": {"ogrenci_no_desenleri": [r"X\d{5}"]}}})
    assert r2.student_patterns[0] == r"X\d{5}" and len(r2.student_patterns) == 1 + len(pats)
    assert institution_patterns({"bidr": {"kurum": "../etc"}}) == ()
    assert institution_patterns({"bidr": {"kurum": "yok-boyle"}}) == ()
