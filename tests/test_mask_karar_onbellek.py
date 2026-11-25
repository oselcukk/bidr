"""Karar sonrası koşu yalnız ilgili belgeyi yeniden maskeler (kaynak kip, `--kaynak -w`).

Olay (canlı, 26.11): ilk maskelemeden sonra transkripsiyon modelin okuma metnini (`text/<doc_id>.txt`) üretti;
bir panel kararından sonraki koşuda metin bütün belgelerin `aday` anahtarına girdiği için bölümün tamamı (764
belge, saatlerce) yeniden maskelendi. Düzeltme (`kaynak.onbellekli_maske`): el yazısı denetiminin arayacağı bir şey
içermeyen metin anahtara girmez; ad listesi ("bu adı her yerde kapat") belgenin anahtarına yalnız o belgede geçen
adlarla girer. Yalnız sentetik veri: uydurma adlar, numaralar."""
from __future__ import annotations

import csv
import hashlib
import time
from pathlib import Path

import pytest

fitz = pytest.importorskip("pymupdf")
pytest.importorskip("PIL")

from bidr.mask import inceleme as INC  # noqa: E402
from bidr.mask import kaynak as K  # noqa: E402
from bidr.mask import ocr as O  # noqa: E402
from bidr.mask import onbellek as OB  # noqa: E402
from bidr.mask import raster as RA  # noqa: E402
from bidr.mask import run as R  # noqa: E402
from bidr.mask.detect import MaskRules, read_ws_config  # noqa: E402
from bidr.mask.kaynak import run_source  # noqa: E402


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


def _pdf(path: Path, satirlar: list[str], sayfa: int = 1) -> None:
    doc = fitz.open()
    for s in range(sayfa):
        p = doc.new_page()
        p.insert_text((72, 80), f"{path.stem.upper()} (sentetik) sayfa {s + 1}", fontsize=14)
        for i, t in enumerate(satirlar):
            p.insert_text((72, 120 + 20 * i), t, fontsize=10)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    doc.close()


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _metin(p: Path) -> str:
    if p.suffix == ".txt":
        return p.read_text(encoding="utf-8")
    doc = fitz.open(str(p))
    try:
        return "".join(pg.get_text() for pg in doc)
    finally:
        doc.close()


A, B, C, D, N = "B.1/a-rapor.pdf", "B.1/b-plan.pdf", "B.2/c-tutanak.pdf", "B.2/d-uzun.pdf", "C.1/not.txt"
DOSYALAR = (A, B, C, D, N)


def _bolum(kaynak: Path) -> None:
    _pdf(kaynak / A, ["Laboratuvar altyapisi yenilendi.", "Yeni cihazlar alindi."])
    _pdf(kaynak / B, ["Stratejik plan hedefleri gozden gecirildi.", "Komisyon uyesi Deneme Birinci sunum yapti."])
    _pdf(kaynak / C, ["Kurul toplantisi yapildi.", "Mezun anketi degerlendirildi."])
    _pdf(kaynak / D, ["Ders programlari guncellendi."], sayfa=3)
    (kaynak / N).parent.mkdir(parents=True, exist_ok=True)
    (kaynak / N).write_text("Kurul toplantisi gundemi (sentetik)\n", encoding="utf-8")


def _model_metinleri(ws: Path, kaynak: Path, ozel: dict[str, str] | None = None) -> None:
    """Transkripsiyonun bıraktığı model metinleri (`inventory.csv` + `text/<doc_id>.txt`), her belge için."""
    (ws / "text").mkdir(parents=True, exist_ok=True)
    with open(ws / "inventory.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["doc_id", "rel_path"])
        for i, d in enumerate(DOSYALAR, 1):
            did = f"doc{i:03d}"
            w.writerow([did, d])
            t = (ozel or {}).get(d)
            if t is None:      # modelin okuduğu metin: sayfa sayfa (form feed), kişisel veri türü yok
                t = "\f".join(_metin(kaynak / d).split("\f")) if d != D else "\f".join(["sayfa"] * 3)
            (ws / "text" / f"{did}.txt").write_text(t, encoding="utf-8")


def _kos(kaynak, kopya, ws, monkeypatch, rules=None):
    cagri: list[str] = []
    asil = R.mask_and_check
    monkeypatch.setattr(R, "mask_and_check",
                        lambda src, *a, **k: cagri.append(Path(src).name) or asil(src, *a, **k))
    t0 = time.monotonic()
    rap = run_source(kaynak, kopya, rules=rules, engine="pymupdf", ws=ws)
    sure = time.monotonic() - t0
    monkeypatch.setattr(R, "mask_and_check", asil)
    return {r["dosya"]: r for r in rap["dosyalar"]}, cagri, sure


def test_karar_ve_model_metni_yalniz_ilgili_belgeleri_yeniden_isler(tmp_path, monkeypatch):
    ws, kaynak, kopya = tmp_path / "ws", tmp_path / "bolum", tmp_path / "maskeli"
    ws.mkdir()
    _bolum(kaynak)
    by, cagri, sure1 = _kos(kaynak, kopya, ws, monkeypatch)           # ilk maskeleme (model metni yok)
    assert sorted(cagri) == sorted(Path(d).name for d in DOSYALAR)
    once = {d: _sha(kopya / d) for d in DOSYALAR}
    kayit = {d: {k: v for k, v in by[d].items() if k not in ("onbellek", "model_metni")} for d in DOSYALAR}

    # transkripsiyon: her belgenin model metni gelir; C'ninkinde maskelemenin kaçırdığı telefon var (el yazısı
    # denetimi bunu yakalamalı); D'ninki sayfa sayısıyla uyuşuyor
    _model_metinleri(ws, kaynak, {C: "Kurul toplantisi yapildi.\nIletisim 0532 111 22 33\n"})
    # tek belgeye panel kararı (kullanıcı çizimi)
    c = INC.ciz(ws, A, 1, [70, 110, 300, 140], "sentetik")
    assert "uyari" not in c, c

    by, cagri, sure2 = _kos(kaynak, kopya, ws, monkeypatch)
    assert sorted(cagri) == sorted(["a-rapor.pdf", "c-tutanak.pdf"]), cagri      # karar + denetim bulgusu
    for d in (B, D, N):                                                          # metni etkisiz: önbellekten
        assert by[d].get("onbellek") and by[d].get("model_metni"), (d, by[d])
        assert _sha(kopya / d) == once[d]
        assert {k: v for k, v in by[d].items() if k not in ("onbellek", "model_metni")} == kayit[d]
    assert not by[A].get("onbellek") and "altyapisi" not in _metin(kopya / A)  # çizim uygulandı
    assert by[C].get("el_yazisi_elle") and by[C]["durum"] != "tamam", by[C]   # denetim çalıştı

    # değişiklik yok: hepsi önbellekten
    by, cagri, _ = _kos(kaynak, kopya, ws, monkeypatch)
    assert cagri == [] and all(by[d].get("onbellek") for d in DOSYALAR)


def test_model_metni_etkisizligi_el_yazisi_denetimiyle_esdeger(tmp_path):
    p = tmp_path / "x.pdf"
    _pdf(p, ["Faaliyet ozeti."], sayfa=2)
    rules = MaskRules()
    res = R.mask_file(p, tmp_path / "y.pdf", rules, engine="pymupdf")
    for t in ("a\fb", "a\fb\f", "a", "a\fb\fc", "0532 111 22 33\fb", "a\fornek@ornek.edu.tr", ""):
        etkisiz = K.model_metni_etkisiz(t, rules, "pdf", p, "pymupdf")
        gaps, note = R.model_text_gaps(t, res, rules)
        if etkisiz:
            assert gaps == [] and note is None, t
    assert K.model_metni_etkisiz("a\fb", rules, "pdf", p, "pymupdf")
    assert not K.model_metni_etkisiz("a", rules, "pdf", p, "pymupdf")               # sayfa sayısı uyuşmuyor
    assert not K.model_metni_etkisiz("a\f0532 111 22 33", rules, "pdf", p, "pymupdf")
    assert K.model_metni_etkisiz("metin", rules, "docx", p, "pymupdf")
    assert not K.model_metni_etkisiz("12345678950", rules, "docx", p, "pymupdf")     # geçerli kimlik no
    assert not K.model_metni_etkisiz("a\fb", rules, "gorsel", p, "pymupdf")


def test_ad_her_yerde_yalniz_adin_gectigi_belgeleri_yeniden_isler(tmp_path, monkeypatch):
    ws, kaynak, kopya = tmp_path / "ws", tmp_path / "bolum", tmp_path / "maskeli"
    ws.mkdir()
    _bolum(kaynak)
    by, cagri, _ = _kos(kaynak, kopya, ws, monkeypatch, MaskRules())
    once = {d: _sha(kopya / d) for d in DOSYALAR}
    assert "Deneme Birinci" in _metin(kopya / B)

    # "bu adı her yerde kapat": ad listesine eklenir (config.yaml privacy.maskeleme.ad_listesi)
    (ws / "config.yaml").write_text("privacy:\n  maskeleme:\n    ad_listesi:\n      - Deneme Birinci\n"
                                    "      - Hic Gecmeyen\n", encoding="utf-8")
    rules = MaskRules.from_config(read_ws_config(ws), ws)
    assert len(rules.names) == 2
    by, cagri, _ = _kos(kaynak, kopya, ws, monkeypatch, rules)
    assert cagri == ["b-plan.pdf"], cagri                                         # yalnız adın geçtiği belge
    assert "Deneme Birinci" not in _metin(kopya / B)
    assert by[B]["maskelenen"].get("ad"), by[B]
    for d in (A, C, D, N):
        assert by[d].get("onbellek") and _sha(kopya / d) == once[d], d

    # aynı listeyle yeniden: hepsi önbellekten
    by, cagri, _ = _kos(kaynak, kopya, ws, monkeypatch, rules)
    assert cagri == [] and all(by[d].get("onbellek") for d in DOSYALAR)

    # ad metni bilinmeyen belge (önceki sürümle işlenmiş): bütün listeyle anahtarlanır, bir kez işlenir;
    # sonra (ad metni yazıldı) önbellekten gelir
    ob = OB.ac(ws)
    ob._c().execute("DELETE FROM k WHERE katman=?", (K.AD_METNI,))
    OB.ac(None)
    rules3 = MaskRules.from_config({"privacy": {"maskeleme": {"ad_listesi": ["Deneme Birinci", "Hic Gecmeyen",
                                                                            "Baska Uydurma"]}}}, ws)
    by, cagri, _ = _kos(kaynak, kopya, ws, monkeypatch, rules3)
    assert sorted(cagri) == sorted(Path(d).name for d in DOSYALAR)
    by, cagri, _ = _kos(kaynak, kopya, ws, monkeypatch, rules3)
    assert cagri == [], cagri
    assert {d: _sha(kopya / d) for d in (A, C, D, N)} == {d: once[d] for d in (A, C, D, N)}


def test_kanit_kipi_suzulmus_ad_listesiyle_kaynak_sonucunu_kullanir(tmp_path, monkeypatch):
    import shutil
    ws, kaynak, kopya = tmp_path / "ws", tmp_path / "bolum", tmp_path / "maskeli"
    ws.mkdir()
    _bolum(kaynak)
    (ws / "config.yaml").write_text("privacy:\n  maskeleme:\n    ad_listesi:\n      - Deneme Birinci\n"
                                    "      - Hic Gecmeyen\n", encoding="utf-8")
    rules = MaskRules.from_config(read_ws_config(ws), ws)
    _kos(kaynak, kopya, ws, monkeypatch, rules)
    ev = ws / "evidence"
    (ev / "B.1").mkdir(parents=True)
    shutil.copyfile(kopya / A, ev / "B.1" / "1 Rapor.pdf")
    shutil.copyfile(kopya / B, ev / "B.1" / "2 Plan.pdf")
    cagri = []
    asil = R.mask_and_check
    monkeypatch.setattr(R, "mask_and_check", lambda src, *a, **k: cagri.append(Path(src).name) or asil(src, *a, **k))
    rap = R.run(ws, evidence=ev, engine="pymupdf")
    assert cagri == [], cagri
    assert rap["ozet"]["kaynak_kipten"] == 2
