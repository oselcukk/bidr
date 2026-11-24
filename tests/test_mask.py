"""bidr maskele ve model öncesi maskeleme (yalnız sentetik veri: TC numaraları algoritmayla üretilir,
adlar ve numaralar hayalîdir)."""
from __future__ import annotations

import csv
import hashlib
import json
import random
import zipfile
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (ArrayObject, DecodedStreamObject, DictionaryObject, NameObject, NumberObject,
                           TextStringObject)

from bidr.cli import main
from bidr.mask import MaskRules, detect, iban_valid, mask_text, tc_valid
from bidr.mask import formats as F
from bidr.mask import run as R
from bidr.mask.detect import register_detector, unregister_detector
from bidr.mask.model import ModelMasker, mask_before_model_enabled, mask_model_inputs


# ---------------------------------------------------------------- sentetik üreticiler

def make_tc(rng: random.Random) -> str:
    d = [rng.randint(1, 9)] + [rng.randint(0, 9) for _ in range(8)]
    d10 = ((sum(d[0:9:2]) * 7) - sum(d[1:8:2])) % 10
    d11 = (sum(d) + d10) % 10
    return "".join(map(str, d + [d10, d11]))


def make_iban(rng: random.Random) -> str:
    bban = "".join(str(rng.randint(0, 9)) for _ in range(22))
    num = "".join(str(int(c, 36)) for c in bban + "TR00")
    chk = 98 - int(num) % 97
    return f"TR{chk:02d}{bban}"


def spaced(iban: str) -> str:
    return " ".join(iban[i:i + 4] for i in range(0, len(iban), 4))


RNG = random.Random(20261119)
TC1, TC2, TC3 = make_tc(RNG), make_tc(RNG), make_tc(RNG)
IBAN = make_iban(RNG)
EMAIL = "deneme.kisi@ornek.edu.tr"
PHONE = "0555 000 11 22"
OGR = "2021999001"
NAME = "Deneme Kisioglu"


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ---------------------------------------------------------------- tespit

def test_tc_algorithm():
    for _ in range(50):
        t = make_tc(RNG)
        assert tc_valid(t)
        bad = t[:10] + str((int(t[10]) + 1) % 10)
        assert not tc_valid(bad)
    assert not tc_valid("0" + TC1[1:])
    assert not tc_valid(TC1[:10])


def test_iban_generator_valid():
    assert iban_valid(IBAN) and iban_valid(spaced(IBAN))
    assert not iban_valid(IBAN[:-1] + str((int(IBAN[-1]) + 1) % 10))


def test_detect_all_kinds_and_placeholders():
    bad_tc = TC1[:10] + str((int(TC1[10]) + 1) % 10)
    text = (f"TC: {TC1}, geçersiz {bad_tc}; e-posta {EMAIL}; tel {PHONE} / +90 (312) 000 00 00; "
            f"IBAN {spaced(IBAN)}; öğrenci no: 51234; numara {OGR}; sorumlu {NAME}.")
    rules = MaskRules(names=(NAME,))
    kinds = [f.kind for f in detect(text, rules)]
    assert kinds.count("tc_no") == 1
    assert kinds.count("telefon") == 2
    assert kinds.count("ogrenci_no") == 2
    assert {"eposta", "iban", "ad"} <= set(kinds)
    masked, c = mask_text(text, rules)
    for v in (TC1, EMAIL, IBAN[:8], OGR, NAME, "000 11 22"):
        assert v not in masked
    assert bad_tc in masked                      # algoritmayı geçmeyen 11 hane TC değildir
    for ph in ("[TC_NO]", "[EPOSTA]", "[TELEFON]", "[IBAN]", "[OGRENCI_NO]", "[AD]"):
        assert ph in masked
    assert c["tc_no"] == 1 and c["ad"] == 1


def test_name_turkish_case_and_ascii_fold():
    rules = MaskRules(names=("Şükrü Örnekçi",))
    for v in ("ŞÜKRÜ ÖRNEKÇİ", "Sukru Ornekci", "şükrü  örnekçi"):
        assert [f.kind for f in detect(f"imza: {v}.", rules)] == ["ad"], v
    assert not detect("Şükrüoğlu Örnekçiler", rules)


def test_rules_from_config(tmp_path):
    (tmp_path / "personel.txt").write_text("# liste\nDeneme Kisioglu\nÖrnek Hayali\n", encoding="utf-8")
    cfg = {"privacy": {"maskeleme": {"ogrenci_no_desenleri": [r"\bS\d{6}\b"], "ad_listesi": "personel.txt",
                                     "turler": ["ogrenci_no", "ad"]}}}
    rules = MaskRules.from_config(cfg, tmp_path)
    kinds = [f.kind for f in detect(f"S123456 numaralı Örnek Hayali; {TC1}", rules)]
    assert kinds == ["ogrenci_no", "ad"]                      # tc_no türlerde yok
    with pytest.raises(ValueError):
        MaskRules(kinds=("bilinmeyen",))
    with pytest.raises(ValueError):
        MaskRules(student_patterns=("(",))
    assert MaskRules(local_model="yerel").warnings


def test_extension_point_detector():
    register_detector("ozel", lambda t: [(t.find("GİZLİ"), t.find("GİZLİ") + 5)] if "GİZLİ" in t else [])
    try:
        assert mask_text("bu GİZLİ bilgi")[0] == "bu [OZEL] bilgi"
    finally:
        unregister_detector("ozel")


# ---------------------------------------------------------------- sentetik belgeler

def _font(w):
    return w._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"), NameObject("/Encoding"): NameObject("/WinAnsiEncoding")}))


def make_pdf(path: Path, pages: list[bytes], *, meta=True, annot=True, attach=True, image_on: set[int] = frozenset()):
    w = PdfWriter()
    font = _font(w)
    for i, content in enumerate(pages):
        page = w.add_blank_page(612, 792)
        res = {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        if i in image_on:
            img = DecodedStreamObject()
            img.set_data(b"\x00")
            img.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Image"),
                        NameObject("/Width"): NumberObject(1), NameObject("/Height"): NumberObject(1),
                        NameObject("/ColorSpace"): NameObject("/DeviceGray"),
                        NameObject("/BitsPerComponent"): NumberObject(8)})
            res[NameObject("/XObject")] = DictionaryObject({NameObject("/Im1"): w._add_object(img)})
            content += b" q 50 0 0 20 72 600 cm /Im1 Do Q"
        page[NameObject("/Resources")] = DictionaryObject(res)
        s = DecodedStreamObject()
        s.set_data(content)
        page[NameObject("/Contents")] = w._add_object(s)
        if annot:
            a = DictionaryObject({NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Text"),
                                  NameObject("/Rect"): ArrayObject([NumberObject(0)] * 4),
                                  NameObject("/Contents"): TextStringObject(f"not: {EMAIL}")})
            page[NameObject("/Annots")] = ArrayObject([w._add_object(a)])
    if meta:
        w.add_metadata({"/Author": NAME, "/Title": f"Kayit {TC2}"})
    if attach:
        w.add_attachment("ek.txt", f"ek {TC3}".encode())
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        w.write(f)


def pdf_text(p: Path) -> str:
    return "\n".join(pg.extract_text() or "" for pg in PdfReader(str(p)).pages)


PDF_OK = [
    (f"BT /F1 11 Tf 72 700 Td (Karar metni. TC: {TC1} e-posta {EMAIL}) Tj 0 -20 Td "
     f"[(Sorumlu: Deneme) -250 (Kisioglu)] TJ 0 -20 Td (Tel {PHONE} IBAN {spaced(IBAN)}) Tj ET").encode(),
    (f"BT /F1 11 Tf 72 700 Td (Ikinci sayfa ogrenci no: {OGR}) Tj ET").encode(),
]
PDF_SPLIT = [(f"BT /F1 11 Tf 72 700 Td (Kimlik {TC1[:6]}) Tj [({TC1[6:8]}) -20 ({TC1[8:]} sonu)] TJ ET").encode()]


def make_docx(path: Path):
    import docx
    d = docx.Document()
    p = d.add_paragraph("Başvuru sahibi T.C. ")
    p.add_run(TC1[:5])
    p.add_run(TC1[5:])                       # TC iki koşuya bölünmüş
    p.add_run(f" e-posta {EMAIL}")
    d.add_paragraph(f"Danışman: {NAME}")
    t = d.add_table(rows=1, cols=2)
    t.cell(0, 0).text = "Telefon"
    t.cell(0, 1).text = PHONE
    d.sections[0].header.paragraphs[0].text = f"İletişim {EMAIL}"
    try:
        d.add_comment(p.runs[0], text=f"kontrol {TC2}", author=NAME)
    except AttributeError:
        pass
    d.core_properties.author = NAME
    d.core_properties.title = f"Dosya {TC2}"
    path.parent.mkdir(parents=True, exist_ok=True)
    d.save(str(path))


def make_xlsx(path: Path):
    import openpyxl
    from openpyxl.comments import Comment
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Liste"
    ws.append(["Ad", "TC", "E-posta", "Öğrenci"])
    ws.append([NAME, int(TC1), EMAIL, int(OGR)])
    ws.append(["Örnek Hayali", TC2, "yok", "x"])
    ws["A3"].comment = Comment(f"tel {PHONE}", "yazar")
    ws.oddFooter.center.text = f"Hazırlayan {NAME}"
    wb.properties.creator = NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(path))


@pytest.fixture
def ws(tmp_path):
    ws = tmp_path / "ws"
    ev = ws / "evidence"
    (ev / "A/A.1/A.1.1").mkdir(parents=True)
    (ws / "config.yaml").write_text(
        "privacy:\n  no_remote: false\n  maskeleme:\n    ad_listesi: [Deneme Kisioglu, Örnek Hayali]\n",
        encoding="utf-8")
    make_pdf(ev / "A/A.1/A.1.1/[A.1.1-1-OD3] Karar.pdf", PDF_OK)
    make_docx(ev / "A/A.1/A.1.2/[A.1.2-1-OD2] Başvuru.docx")
    make_xlsx(ev / "B/B.1/B.1.1/[B.1.1-1-OD3] Liste.xlsx")
    (ev / "B/B.1/B.1.1/sunum.pptx").write_bytes(b"PK sentetik")
    (ev / "B/B.1/B.1.1/not.txt").write_text(f"İletişim: {EMAIL}\n", encoding="utf-8")
    (ev / ".bidr-evidence.json").write_text("{}", encoding="utf-8")
    with open(ws / "evidence-index.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["kanit_no", "olcut", "ad", "dosya", "alintilar", "kaynak"])
        w.writeheader()
        w.writerow({"kanit_no": "1_OD3", "olcut": "A.1.1", "ad": "Karar", "dosya": "A/A.1/A.1.1/[A.1.1-1-OD3] Karar.pdf",
                    "alintilar": json.dumps([f"TC: {TC1}"]), "kaynak": f"{NAME}/karar.pdf"})
    return ws


def _originals(ws: Path) -> dict:
    return {p: _sha(p) for p in (ws / "evidence").rglob("*") if p.is_file()}


# ---------------------------------------------------------------- yayın kopyası

def test_maskele_end_to_end(ws, capsys):
    before = _originals(ws)
    rc = main(["maskele", "-w", str(ws), "--motor", "pypdf"])
    out = capsys.readouterr().out
    assert rc == 1                                   # sunum taranamaz → yayımlanamaz
    assert before == _originals(ws)                  # asıl dosyalar değişmedi
    m = ws / "evidence-maskeli"
    rep = json.loads((ws / R.REPORT).read_text(encoding="utf-8"))
    by = {f["dosya"]: f for f in rep["dosyalar"]}

    pdf = m / "A/A.1/A.1.1/[A.1.1-1-OD3] Karar.pdf"
    rec = by["A/A.1/A.1.1/[A.1.1-1-OD3] Karar.pdf"]
    assert rec["durum"] == "tamam", rec
    assert rec["kalan"] == {}
    assert rec["bulunan"]["tc_no"] >= 2 and rec["maskelenen"]["tc_no"] == 1
    assert {"ust_veri", "yorum_aciklama", "ekler_ve_adlar"} <= set(rec["temizlenen"])
    txt = pdf_text(pdf)
    for v in (TC1, EMAIL, OGR, "Kisioglu", IBAN[4:8] + " " + IBAN[8:12]):
        assert v not in txt
    raw = pdf.read_bytes()
    for v in (TC1, TC2, TC3, EMAIL):
        assert v.encode() not in raw
    r = PdfReader(str(pdf))
    assert not r.metadata or not r.metadata.get("/Author")
    assert not r.pages[0].get("/Annots") and "/Names" not in r.trailer["/Root"]

    for rel in ("A/A.1/A.1.2/[A.1.2-1-OD2] Başvuru.docx", "B/B.1/B.1.1/[B.1.1-1-OD3] Liste.xlsx",
                "B/B.1/B.1.1/not.txt"):
        assert by[rel]["durum"] == "tamam", by[rel]
        assert (m / rel).is_file()
        blob = b"".join(zipfile.ZipFile(m / rel).read(n) for n in zipfile.ZipFile(m / rel).namelist()) \
            if rel.endswith(("x",)) else (m / rel).read_bytes()
        for v in (TC1, TC2, EMAIL, NAME, "000 11 22", OGR):
            assert v.encode() not in blob, (rel, v)

    dx = by["A/A.1/A.1.2/[A.1.2-1-OD2] Başvuru.docx"]
    assert dx["maskelenen"]["tc_no"] >= 1 and "ust_veri" in dx["temizlenen"]
    import docx
    if hasattr(docx.document.Document, "add_comment"):
        assert "yorumlar" in dx["temizlenen"] and dx["bulunan"]["tc_no"] == 3
    xl = by["B/B.1/B.1.1/[B.1.1-1-OD3] Liste.xlsx"]
    assert xl["maskelenen"]["tc_no"] == 2 and "yorumlar" in xl["temizlenen"]
    assert by["B/B.1/B.1.1/sunum.pptx"]["durum"] == "desteklenmiyor"
    assert not (m / "B/B.1/B.1.1/sunum.pptx").exists()
    assert [y["dosya"] for y in rep["yayimlanamaz"]] == ["B/B.1/B.1.1/sunum.pptx"]
    assert not (m / ".bidr-evidence.json").exists()

    # rapor değerin kendisini içermez
    blob = (ws / R.REPORT).read_text(encoding="utf-8")
    for v in (TC1, TC2, EMAIL, NAME, OGR):
        assert v not in blob
    # dizin kopyası
    with open(ws / R.INDEX_OUT, encoding="utf-8") as f:
        row = next(csv.DictReader(f))
    assert TC1 not in row["alintilar"] and "[TC_NO]" in row["alintilar"]
    assert NAME not in row["kaynak"] and row["maskeleme"] == "tamam"
    assert "YAYIMLANAMAZ" in out

    # yeniden çalıştırma kendi çıktısını siler
    assert main(["maskele", "-w", str(ws), "--motor", "pypdf"]) == 1


def make_nested_form_pdf(path: Path, inner: bytes):
    """Metin iç içe biçim nesnesinde (sayfa → Fm1 → Fm2): pypdf yolu yalnız ilk düzeyi işler."""
    w = PdfWriter()
    font = _font(w)
    page = w.add_blank_page(612, 792)

    def form(data: bytes, res: dict):
        s = DecodedStreamObject()
        s.set_data(data)
        s.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Form"),
                  NameObject("/BBox"): ArrayObject([NumberObject(0), NumberObject(0), NumberObject(612),
                                                    NumberObject(792)]),
                  NameObject("/Resources"): DictionaryObject(res)})
        return w._add_object(s)

    fm2 = form(inner, {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
    fm1 = form(b"/Fm2 Do", {NameObject("/XObject"): DictionaryObject({NameObject("/Fm2"): fm2})})
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/XObject"): DictionaryObject({NameObject("/Fm1"): fm1})})
    s = DecodedStreamObject()
    s.set_data(b"/Fm1 Do")
    page[NameObject("/Contents")] = w._add_object(s)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        w.write(f)


def test_tc_split_across_text_ops_is_masked(tmp_path):
    ws = tmp_path / "ws"
    make_pdf(ws / "evidence/A/x.pdf", PDF_SPLIT, meta=False, annot=False, attach=False)
    rep = R.run(ws, engine="pypdf")
    rec = rep["dosyalar"][0]
    assert rec["durum"] == "tamam" and rec["maskelenen"] == {"tc_no": 1}, rec
    assert TC1 not in pdf_text(ws / "evidence-maskeli/A/x.pdf").replace("\n", "")


def test_leftover_fails_and_is_unpublishable(tmp_path):
    ws = tmp_path / "ws"
    make_nested_form_pdf(ws / "evidence/A/x.pdf", f"BT /F1 11 Tf 72 700 Td (Kimlik {TC1}) Tj ET".encode())
    assert TC1 in pdf_text(ws / "evidence/A/x.pdf")
    rep = R.run(ws, engine="pypdf")
    rec = rep["dosyalar"][0]
    assert rec["durum"] == "basarisiz" and rec["kalan"] == {"tc_no": 1}, rec
    assert not (ws / "evidence-maskeli/A/x.pdf").exists()
    assert (ws / R.FAIL_DIR / "A/x.pdf").is_file()
    assert rep["yayimlanamaz"][0]["dosya"] == "A/x.pdf"
    assert TC1 not in json.dumps(rep, ensure_ascii=False)


def test_signature_warning_only(tmp_path, capsys):
    ws = tmp_path / "ws"
    make_pdf(ws / "evidence/A/imzali.pdf", [b"BT /F1 11 Tf 72 700 Td (Bolum Baskani IMZA) Tj ET",
                                           b"BT /F1 11 Tf 72 700 Td (imza yok resim yok) Tj ET"],
             meta=False, annot=False, attach=False, image_on={0})
    assert main(["maskele", "-w", str(ws), "--motor", "pypdf"]) == 0
    rep = json.loads((ws / R.REPORT).read_text(encoding="utf-8"))
    assert rep["dosyalar"][0]["imza_uyarisi"] == ["s.1"]
    assert rep["dosyalar"][0]["durum"] == "tamam"            # yalnız uyarı
    assert "imza bölgesi" in capsys.readouterr().out


def test_cli_name_list_and_foreign_out(tmp_path):
    ws = tmp_path / "ws"
    (ws / "evidence/A").mkdir(parents=True)
    (ws / "evidence/A/n.txt").write_text("Komisyon: Hayali Tanık", encoding="utf-8")
    (tmp_path / "adlar.csv").write_text("Hayali Tanık,unvan\n", encoding="utf-8")
    assert main(["maskele", "-w", str(ws), "--ad-listesi", str(tmp_path / "adlar.csv")]) == 0
    assert (ws / "evidence-maskeli/A/n.txt").read_text(encoding="utf-8") == "Komisyon: [AD]"
    other = tmp_path / "baska"
    (other / R.OUT_DIR).mkdir(parents=True)
    (other / R.OUT_DIR / "kullanici.txt").write_text("x", encoding="utf-8")
    assert main(["maskele", "-w", str(ws), "--out", str(other)]) == 2
    assert main(["maskele", "-w", str(tmp_path / "yok")]) == 2


def test_pymupdf_engine_if_available(ws):
    pytest.importorskip("pymupdf")
    rep = R.run(ws, engine="pymupdf")
    rec = next(f for f in rep["dosyalar"] if f["dosya"].endswith("Karar.pdf"))
    assert rec["motor"] == "pymupdf" and rec["durum"] == "tamam", rec


def test_engine_selection():
    assert F.pdf_engine("pypdf") == "pypdf"
    if F._fitz() is None:
        assert F.pdf_engine("auto") == "pypdf"
        with pytest.raises(F.MaskError):
            F.pdf_engine("pymupdf")


# ---------------------------------------------------------------- model öncesi maskeleme

def test_model_masking_off_by_default(tmp_path):
    (tmp_path / "config.yaml").write_text("privacy:\n  no_remote: false\n", encoding="utf-8")
    inputs = {"belge_metni": f"TC {TC1}"}
    out, c = mask_model_inputs(inputs, tmp_path)
    assert out is inputs and not c
    assert not mask_before_model_enabled({})
    assert ModelMasker.load(tmp_path / "yok").text(TC1) == TC1


def test_model_masking_on(tmp_path):
    (tmp_path / "config.yaml").write_text(
        "privacy:\n  mask_before_model: true\n  maskeleme:\n    ad_listesi: [Deneme Kisioglu]\n", encoding="utf-8")
    inputs = {"belge_metni": f"Başvuran {NAME} ({TC1}), {EMAIL}", "doc_id": TC2,
              "parcalar": [f"öğrenci no: {OGR}", {"tel": PHONE}], "sayi": 3}
    mm = ModelMasker.load(tmp_path, skip_keys=("doc_id",))
    out = mm.inputs(inputs)
    assert out["belge_metni"] == "Başvuran [AD] ([TC_NO]), [EPOSTA]"
    assert out["parcalar"] == ["öğrenci no: [OGRENCI_NO]", {"tel": "[TELEFON]"}]
    assert out["doc_id"] == TC2 and out["sayi"] == 3
    assert inputs["belge_metni"].startswith("Başvuran Deneme")     # girdi değişmedi
    assert mm.counts["tc_no"] == 1
    # alıntı denetimi: modelin gördüğü (maskeli) metne karşı, belirleyici
    assert mm.text(inputs["belge_metni"]) == out["belge_metni"]


def test_model_masking_backend_wrappers(tmp_path):
    from bidr.llm import render_task, verify_quote
    (tmp_path / "config.yaml").write_text("privacy:\n  mask_before_model: true\n", encoding="utf-8")
    mm = ModelMasker.load(tmp_path)
    doc = f"Giriş. Başvuran {TC1} numaralı kişi, {EMAIL} adresinden yazdı. Kurul kararı alındı."
    seen = {}

    def fake_render(task, inputs):
        seen.update(inputs)
        return {"prompt": inputs["metin"]}
    assert mm.render(fake_render)("t", {"metin": doc})["prompt"] == mm.text(doc)
    assert TC1 not in seen["metin"]
    vq = mm.verify_quote(verify_quote)
    q = "Başvuran [TC_NO] numaralı kişi, [EPOSTA] adresinden yazdı."
    r = vq(q, doc)
    assert r.ok and doc[r.span[0]:r.span[1]].startswith("Başvuran " + TC1)
    assert doc[r.span[0]:r.span[1]].rstrip(".").endswith("adresinden yazdı")
    r2 = vq("Kurul kararı alındı.", doc)
    assert r2.ok and r2.span == verify_quote("Kurul kararı alındı.", doc).span   # PII sonrası kayma düzeltilir
    off = ModelMasker(False)
    assert off.render(fake_render) is fake_render and off.verify_quote(verify_quote) is verify_quote
    assert callable(render_task)


# ---------------------------------------------------------------- e-posta biçimleri (OCR bozulmaları)

@pytest.mark.parametrize("adres", [
    "ad@ornek.con",                      # OCR: .com → .con
    "ad@ornek.c0m",                      # OCR: o → 0
    "ad@ornek.corn",                     # OCR: m → rn
    "ad.soyad@ornek.0rg",
    "ad @ ornek.com",                    # @ çevresinde boşluk
    "ad@ ornek.edu.tr",
    "ad @ornek.edu.tr",
    "ad@ornek. com",                     # alan adında boşluklu nokta
    "ad@ornek .edu. tr",
    "ad(at)ornek.com",                   # (at) yazımı
    "ad (at) ornek.edu.tr",
    "ad [AT] ornek [dot] com",
    "ad@gıtu.edu.tr",                    # alan adında noktasız ı (OCR)
    "ad@örnek-üni.edu.tr",               # alan adında Türkçe harfler
    "kişi.şükrü@ornek.edu.tr",           # yerel kısımda Türkçe harfler
    "ÇAĞRI.ÖZ@ORNEK.COM.TR",
    "ad.soyad@birim.ornek.gov.tr",       # kurum adresi (alt alan adı)
    "jane.doe@uni-ornek.de",             # yabancı üniversite adresleri
    "j.doe@ornek.ac.uk",
    "prof_x@ornek-univ.edu",
    "o'neil@ornek.ie",
    "ad.soyad+bidr@ornek.ch",
])
def test_eposta_bicimleri(adres):
    t = f"İletişim: {adres}, 2025."
    fs = [f for f in detect(t) if f.kind == "eposta"]
    assert [t[f.start:f.end] for f in fs] == [adres]
    masked, c = mask_text(t)
    assert c["eposta"] == 1 and masked == "İletişim: [EPOSTA], 2025."


@pytest.mark.parametrize("metin", [
    "lodash@4.17.21 sürümü",             # paket sürümü
    "python@3.12 ve node@18.x",
    "pip install bidr==0.1.0",
    "doi:10.1000/ornek.2025.123 ve https://doi.org/10.1000/xyz",
    "@property\ndef ad(self): ...",       # dekoratör: yerel kısım yok
    "@app.route('/x')",
    "y = x @ np.linalg.inv(a)",           # matris çarpımı (boşluklu @, bilinen uzantı yok)
    "c = a @ b.T + w @ v.shape",
    "kullanici@localhost",
    "v1.2@3.4",
    "Toplantı @ salon saat 14.00",
    "x@y.c",
    "e-posta: eposta@maskeli.invalid",   # maskeleyicinin yer tutucu adresi
])
def test_eposta_yanlis_pozitif_yok(metin):
    assert [metin[f.start:f.end] for f in detect(metin) if f.kind == "eposta"] == []


def test_eposta_cumle_icinde_sinirlar():
    t = "Adresler: ad@ornek.edu.tr'ye, (ikinci@ornek.com) ve ucuncu @ ornek. com.tr; son."
    assert [t[f.start:f.end] for f in detect(t) if f.kind == "eposta"] == [
        "ad@ornek.edu.tr", "ikinci@ornek.com", "ucuncu @ ornek. com.tr"]
