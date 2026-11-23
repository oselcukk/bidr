"""m9: kaynak kipte (`--kaynak -w`) önbellek geçersizleşmesi belge başınadır.

Tek bir belgeye çizim (`ciz`) ya da karar yalnız o belgenin (ve şablon belleği gerçekten eşleşen aynı formun
kopyalarının) önbellek anahtarını değiştirir; öbür belgeler önbellekten gelir, çıktıları bayt bayt aynı kalır.
Yalnız sentetik veri: uydurma adlar."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

fitz = pytest.importorskip("pymupdf")
pytest.importorskip("PIL")

from bidr.mask import alan as AL  # noqa: E402
from bidr.mask import inceleme as INC  # noqa: E402
from bidr.mask import ocr as O  # noqa: E402
from bidr.mask import onbellek as OB  # noqa: E402
from bidr.mask import raster as RA  # noqa: E402
from bidr.mask.kaynak import run_source  # noqa: E402

from test_mask_m5 import AD1, AD2, KUTU, _sablon_bolgeleri, tutanak  # noqa: E402

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


def _yazi(path: Path) -> None:
    """Tutanakla eşleşmeyen başka bir form (metin katmanlı)."""
    doc = fitz.open()
    p = doc.new_page()
    p.insert_text((72, 80), "FAALIYET RAPORU (sentetik)", fontsize=14)
    for i, t in enumerate(("Bolum laboratuvar altyapisini yeniledi ve yeni cihazlar aldi.",
                           "Ders programlari akreditasyon olcutlerine gore gozden gecirildi.",
                           "Mezun izleme anketi sonuclari kurulda degerlendirildi.")):
        p.insert_text((72, 120 + 20 * i), t, fontsize=10)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    doc.close()


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _metin(p: Path) -> str:
    doc = fitz.open(str(p))
    try:
        return "".join(pg.get_text() for pg in doc)
    finally:
        doc.close()


@needs_np
def test_kaynak_tek_belgeye_cizim_ve_karar_yalniz_o_belgeyi_yeniden_isler(tmp_path):
    ws, kaynak, kopya = tmp_path / "ws", tmp_path / "bolum", tmp_path / "maskeli"
    ws.mkdir()
    T1, T2, Y, N = "B.1.1/tutanak-1.pdf", "B.1.2/tutanak-2.pdf", "C.1/rapor.pdf", "C.1/not.txt"
    tutanak(kaynak / T1, AD1)
    tutanak(kaynak / T2, AD2)
    _yazi(kaynak / Y)
    (kaynak / N).write_text("Kurul toplantisi gundemi (sentetik)\n", encoding="utf-8")

    def kos():
        rap = run_source(kaynak, kopya, engine="pymupdf", ws=ws)
        return {r["dosya"]: r for r in rap["dosyalar"]}

    by = kos()
    assert not any(r.get("onbellek") for r in by.values())
    by = kos()                                                   # değişiklik yok: hepsi önbellekten
    assert all(by[d].get("onbellek") for d in (T1, T2, Y, N)), {d: r.get("onbellek") for d, r in by.items()}
    once = {d: _sha(kopya / d) for d in (T2, Y, N)}
    assert "Deneme Birinci" in _metin(kopya / T1)

    # tek belgeye çizim: yalnız o belge (ve şablonu gerçekten eşleşen aynı formun kopyası) yeniden işlenir
    c = INC.ciz(ws, T1, 1, KUTU, "sentetik")
    assert "uyari" not in c, c
    by = kos()
    assert not by[T1].get("onbellek")
    assert "Deneme Birinci" not in _metin(kopya / T1)          # çizim bu belgede uygulandı
    assert not by[T2].get("onbellek") and len(_sablon_bolgeleri(by[T2])) == 1, by[T2]   # aynı form: öneri
    assert by[Y].get("onbellek") and by[N].get("onbellek"), (by[Y], by[N])
    assert {d: _sha(kopya / d) for d in (Y, N)} == {d: once[d] for d in (Y, N)}
    once2 = {d: _sha(kopya / d) for d in (T2, Y, N)}

    # aynı belgedeki çizime karar (birak): yalnız o belge yeniden işlenir, karar uygulanır
    INC.karar(ws, c["id"], "birak", "sentetik")
    by = kos()
    assert not by[T1].get("onbellek")
    assert "Deneme Birinci" in _metin(kopya / T1)              # bırakıldı: ad yeniden görünür
    assert all(by[d].get("onbellek") for d in (T2, Y, N)), {d: by[d].get("onbellek") for d in (T2, Y, N)}
    assert {d: _sha(kopya / d) for d in (T2, Y, N)} == once2
