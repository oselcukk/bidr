"""Dev görüntü küçültülerek maskelenir (raster.BUYUK_PIKSEL): 300 dpi'da ~77 MP'lik sayfa (canlı 26.11) ya da
90–105 MP fotoğraf A4'ün 300 dpi alanına (~8,7 MP) iner; olağan sayfa ve görsel değişmez. Yalnız sentetik veri."""
from __future__ import annotations

import pytest

fitz = pytest.importorskip("pymupdf")
PIL = pytest.importorskip("PIL")

from bidr.mask import raster as RA  # noqa: E402


def _sayfa(w, h):
    doc = fitz.open()
    return doc, doc.new_page(width=w, height=h)


def test_olagan_sayfa_300_dpi_kalir():
    for w, h in ((595, 842), (842, 1191), (1191, 1684)):          # A4, A3, A2
        doc, p = _sayfa(w, h)
        assert RA.sayfa_dpi(p, 300) == 300
        doc.close()


def test_dev_sayfa_a4_300_dpi_alanina_iner():
    doc, p = _sayfa(1804, 2657)
    d = RA.sayfa_dpi(p, 300)
    px = (1804 * d / 72) * (2657 * d / 72)
    assert d < 300 and px <= RA.HEDEF_PIKSEL * 1.01 and px > RA.HEDEF_PIKSEL * 0.9
    img = RA.render(p, d)
    assert img.width * img.height <= RA.BUYUK_PIKSEL
    doc.close()


def test_dev_gorsel_kucultulur_olagan_gorsel_degismez(tmp_path):
    from PIL import Image
    buyuk = tmp_path / "buyuk.png"
    Image.new("L", (8000, 6000), 255).save(buyuk)                 # 48 MP
    im = RA._open_image(buyuk)
    assert im.width * im.height <= RA.HEDEF_PIKSEL * 1.01
    assert abs(im.width / im.height - 8000 / 6000) < 0.01
    kucuk = tmp_path / "kucuk.png"
    Image.new("L", (2480, 3508), 255).save(kucuk)
    assert RA._open_image(kucuk).size == (2480, 3508)
