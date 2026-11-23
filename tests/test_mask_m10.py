"""m10: kanıt kipi (`bidr maskele -w`) kaynak kipin (`--kaynak -w`) sonucunu yeniden kullanır.

Panel akışında bidr'in kaynağı kaynak kipin maskeli ağacıdır; kanıt dosyası oradaki maskeli kopyanın aynısıdır.
Kanıt kipi bu dosyayı yeniden maskelemez: kayıt, bölgeler ve çerçevesiz teslim hâli önbellekten gelir. Kural ya
da o belgenin kararı değişince (ya da kanıt dosyası farklıysa) normal işlenir. Yalnız sentetik veri: uydurma adlar."""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

fitz = pytest.importorskip("pymupdf")
pytest.importorskip("PIL")

from bidr.mask import alan as AL  # noqa: E402
from bidr.mask import inceleme as INC  # noqa: E402
from bidr.mask import ocr as O  # noqa: E402
from bidr.mask import onbellek as OB  # noqa: E402
from bidr.mask import raster as RA  # noqa: E402
from bidr.mask import run as R  # noqa: E402
from bidr.mask.detect import MaskRules, read_ws_config  # noqa: E402
from bidr.mask.kaynak import run_source  # noqa: E402

from test_mask_m5 import AD1, AD2, KUTU, tutanak  # noqa: E402
from test_mask_m9 import _yazi  # noqa: E402

needs_np = pytest.mark.skipif(AL.np is None, reason="numpy yok")


@pytest.fixture(autouse=True)
def _temiz(monkeypatch):
    O._CACHE.clear()
    OB.ac(None)
    OB._ACIK.clear()
    monkeypatch.delenv("BIDR_MASKE_WS", raising=False)
    RA._SABLON.clear()
    yield
    OB.ac(None)
    OB._ACIK.clear()
    RA._SABLON.clear()


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


@needs_np
def test_kanit_kipi_kaynak_kip_sonucunu_yeniden_kullanir(tmp_path, monkeypatch):
    ws, kaynak, kopya = tmp_path / "ws", tmp_path / "bolum", tmp_path / "maskeli"
    ws.mkdir()
    T1, T2, Y, N = "B.1.1/tutanak-1.pdf", "B.1.2/tutanak-2.pdf", "C.1/rapor.pdf", "C.1/not.txt"
    tutanak(kaynak / T1, AD1)
    tutanak(kaynak / T2, AD2)
    _yazi(kaynak / Y)
    (kaynak / N).write_text("Kurul toplantisi gundemi (sentetik)\n", encoding="utf-8")
    rules = MaskRules.from_config(read_ws_config(ws), ws)

    def kaynak_kos():
        rap = run_source(kaynak, kopya, rules=rules, engine="pymupdf", ws=ws)
        return {r["dosya"]: r for r in rap["dosyalar"]}

    kaynak_kos()
    INC.ciz(ws, T1, 1, KUTU, "sentetik")        # T2 (aynı form) şablon önerisi alır: açık öneri, çerçeveli kopya
    kb = kaynak_kos()
    assert R._acik_oneri(kb[T2]), kb[T2]

    # kanıt klasörü: kaynak kipin maskeli kopyaları (dosyalama yeniden adlandırır) + kaynakta olmayan yeni dosya
    ev = ws / "evidence"
    ad = {T1: "1 Tutanak.pdf", T2: "2 Tutanak.pdf", Y: "3 Rapor.pdf", N: "4 Not.txt"}
    for d, a in ad.items():
        (ev / "B.1").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(kopya / d, ev / "B.1" / a)
    _yazi(ev / "B.1" / "5 Yeni.pdf")

    cagri = []
    asil = R.mask_and_check
    monkeypatch.setattr(R, "mask_and_check", lambda src, *a, **k: cagri.append(Path(src).name) or asil(src, *a, **k))
    rap = R.run(ws, evidence=ev, engine="pymupdf")
    by = {r["dosya"]: r for r in rap["dosyalar"]}
    assert cagri == ["5 Yeni.pdf"], cagri                      # yalnız yeni dosya işlendi
    assert rap["ozet"]["kaynak_kipten"] == 4
    for d, a in ad.items():
        r = by[f"B.1/{a}"]
        assert r.get("kaynak_kipten") and r["durum"] == kb[d]["durum"]
        assert r.get("bolgeler") == kb[d].get("bolgeler")
    # açık önerili belge: inceleme kopyası (çerçeveli) = kaynak kopyası; teslim kopyası çerçevesiz hâl
    r2 = by["B.1/2 Tutanak.pdf"]
    assert R.bekliyor(r2) and r2.get("teslim_kopya"), r2
    assert _sha(ws / R.FAIL_DIR / "B.1/2 Tutanak.pdf") == _sha(kopya / T2)
    assert _sha(ws / r2["teslim_kopya"]) != _sha(kopya / T2)
    assert _sha(ws / R.OUT_DIR / "B.1/3 Rapor.pdf") == _sha(kopya / Y)

    # o belgenin kararı değişince (kaynak kip yeniden koşmadıysa) kanıt kipi o dosyayı normal işler
    sab = [b for b in kb[T2]["bolgeler"] if b["kaynak"] == "sablon"]
    INC.karar(ws, sab[0]["id"], "birak", "sentetik")
    cagri.clear()
    R.run(ws, evidence=ev, engine="pymupdf")
    assert "2 Tutanak.pdf" in cagri and "3 Rapor.pdf" not in cagri, cagri


# -- güvenlik ağı: hiç bölge yokken taranmış sayfada imza benzeri iz -------------------------------------------

import imza_sentetik as SN  # noqa: E402
from bidr.mask import yapi as Y  # noqa: E402

needs_ocr = pytest.mark.skipif(not O.ocr_available(), reason="tesseract + tur/eng yok")


@needs_ocr
def test_imza_izi_tarananda_var_temiz_belgede_yok(tmp_path):
    SN.tutanak(tmp_path / "imzali.pdf", imzali=True)
    SN.tutanak(tmp_path / "imzasiz.pdf", imzali=False)
    assert [s for s, _ in RA.imza_izi(tmp_path / "imzali.pdf", "pdf")] == [1]
    assert RA.imza_izi(tmp_path / "imzasiz.pdf", "pdf") == []
    doc = fitz.open()                                   # düz metin ve web çıktısı: bakılmaz
    p = doc.new_page()
    p.insert_text((30, 20), "https://www.ornek.edu.tr/duyuru  12.03.2025", fontsize=7)
    for k in range(30):
        p.insert_text((60, 70 + 20 * k), f"Duyuru: seminer programi yayimlandi {k}.", fontsize=11)
    doc.save(str(tmp_path / "web.pdf"))
    doc.close()
    assert RA.imza_izi(tmp_path / "web.pdf", "pdf") == []


@needs_ocr
def test_bolgesiz_taramada_imza_izi_dosyayi_tamam_birakmaz(tmp_path, monkeypatch):
    """Yapısal imza tespiti hiçbir şey bulmasa (kaçırma benzetimi) sayfa düzeyinde tek öneri çıkar: dosya `tamam`
    değil, karar bekler; inceleme kopyası çerçeveli, teslim kopyası çerçevesiz."""
    SN.tutanak(tmp_path / "t.pdf", imzali=True)
    monkeypatch.setattr(Y, "goruntu_bolgeleri", lambda *a, **k: [])
    rec = R.mask_and_check(tmp_path / "t.pdf", tmp_path / "m.pdf", MaskRules(), "pymupdf", temiz=tmp_path / "tz.pdf")
    iz = [b for b in rec["bolgeler"] if b["kaynak"] == R.IMZA_IZI]
    assert len(iz) == 1 and iz[0]["karar"] == "onay_bekliyor" and iz[0]["sayfa"] == 1, rec["bolgeler"]
    assert rec["durum"] == "basarisiz" and R.IMZA_IZI_NEDEN in rec["neden"] and R.bekliyor(rec)
    assert (tmp_path / "tz.pdf").is_file() and _sha(tmp_path / "tz.pdf") != _sha(tmp_path / "m.pdf")
