"""Maskeleme çıktısı belirlenimci: aynı girdi + aynı kurallar → bayt bayt aynı maskeli dosya (yalnız sentetik
veri). Kaynaklar: PDF trailer `/ID` (PyMuPDF her kayıtta rastgele), zip girdi zamanları, core.xml `modified`,
arşiv üye zamanları, gzip başlık zamanı, e-posta sınırları."""
from __future__ import annotations

import email
import email.policy
import shutil
import time
import zipfile
from email.message import EmailMessage
from pathlib import Path

import pytest

from bidr.mask import belirlenimci as BL
from bidr.mask import kaynak as K
from bidr.mask import run as R
from bidr.mask.formats import pdf_engine

from test_mask import PDF_OK, _sha, make_docx, make_pdf, make_xlsx
from test_mask_kaynak import RULES, src  # noqa: F401 — fixture


def _iki_kez(src_: Path, d: Path, eng: str) -> list[str]:
    shas = []
    for i in range(2):
        out = d / f"o{i}{src_.suffix}"
        R.mask_and_check(src_, out, RULES, eng)
        shas.append(_sha(out))
        if i == 0:
            time.sleep(2.1)            # zip zaman çözünürlüğü 2 sn: saat farkı çıktıya sızmasın
    return shas


@pytest.mark.parametrize("ad", ["a.docx", "a.xlsx"])
def test_ooxml_iki_maskeleme_ayni_sha(tmp_path, ad):
    s = tmp_path / ad
    (make_docx if ad.endswith("docx") else make_xlsx)(s)
    a, b = _iki_kez(s, tmp_path, "auto")
    assert a == b
    with zipfile.ZipFile(tmp_path / f"o0{s.suffix}") as z:
        assert {i.date_time for i in z.infolist()} == {BL.ZIP_ZAMANI}
        core = z.read(BL.CORE).decode("utf-8")
    with zipfile.ZipFile(s) as z:
        ozgun = z.read(BL.CORE).decode("utf-8")
    # core.xml'de yalnız created/modified, değerleri özgününki
    import re
    for alan in ("created", "modified"):
        m = re.search(rf"<dcterms:{alan}[^>]*>([^<]+)<", ozgun)
        if m:
            assert m.group(1) in core
    assert "creator" not in core and "title" not in core and "lastModifiedBy" not in core


def test_pdf_iki_maskeleme_ve_onay_cercevesi_ayni_sha(tmp_path):
    s = tmp_path / "a.pdf"
    make_pdf(s, PDF_OK)
    eng = pdf_engine("auto")
    a, b = _iki_kez(s, tmp_path, eng)
    assert a == b
    if eng != "pymupdf":
        return
    shas = []
    for i in range(2):                 # açık öneri çerçevesi ikinci bir PyMuPDF kaydı
        c = tmp_path / f"c{i}.pdf"
        shutil.copyfile(tmp_path / "o0.pdf", c)
        R.onay_cercevesi(c, "pdf", [{"sayfa": 1, "kutu": [50, 50, 150, 80]}], eng)
        shas.append(_sha(c))
    assert shas[0] == shas[1]
    assert b"/ID" not in (tmp_path / "c0.pdf").read_bytes()      # özgünde /ID yok: eklenmedi


def test_pdf_kaydet_ozgun_id_korunur(tmp_path):
    fitz = pytest.importorskip("pymupdf")
    d = fitz.open()
    d.new_page()
    p = tmp_path / "idli.pdf"
    d.save(str(p))                     # PyMuPDF yeni /ID verir
    d.close()
    import re
    id0 = re.findall(rb"/ID\s*\[[^\]]*\]", p.read_bytes())
    assert id0
    for i in range(2):
        d = fitz.open(str(p))
        BL.pdf_kaydet(d, tmp_path / f"k{i}.pdf", garbage=3, deflate=True)
        d.close()
        assert re.findall(rb"/ID\s*\[[^\]]*\]", (tmp_path / f"k{i}.pdf").read_bytes()) == id0


def test_kaynak_agaci_iki_kosuda_ayni(src, tmp_path):   # noqa: F811
    agaclar = []
    for i in range(2):
        out = tmp_path / f"out{i}"
        K.run_source(src, out, rules=RULES, engine="pypdf")
        agaclar.append({p.relative_to(out).as_posix(): _sha(p) for p in out.rglob("*")
                        if p.is_file() and p.name != ".bidr-maskeleme.json"})
        if i == 0:
            time.sleep(2.1)
    assert agaclar[0] == agaclar[1]
    assert any(k.endswith(".tar.gz") for k in agaclar[0]) and any(k.endswith(".zip") for k in agaclar[0])


def test_eml_sinirlari_icerikten():
    def yap():
        m = EmailMessage(policy=email.policy.default)
        m["Subject"] = "Deneme"
        m.set_content("gövde")
        m.add_alternative("<p>gövde</p>", subtype="html")
        m.add_attachment(b"ek", maintype="application", subtype="octet-stream", filename="ek.bin")
        BL.eml_sinirlarini_sabitle(m)
        return m.as_bytes()
    a, b = yap(), yap()
    assert a == b
    m = email.message_from_bytes(a, policy=email.policy.default)
    assert m.get_boundary().startswith("=_bidr_")
