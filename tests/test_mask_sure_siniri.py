"""Maskeleme hiçbir zaman koşuyu tutmaz: dosya başına süre sınırı (bidr/havuz.py) ve "olduğu gibi devam" sonrası
yalnız var olan maskeler (`bidr maskele -w WS --yalniz-kaynak`).

Olay (canlı, 26.11): rapor yüklendikten sonra kanıt maskelemesi tek bir dev sayfalı taranmış PDF'de (sayfa başına
~77 MP OCR) 35+ dakika sürdü, iş "işleniyor"da kaldı. Bölüm "olduğu gibi devam" demişti: kanıtlar kaynak kipin maskeli
kopyalarıdır, yeniden hesap gerekmez. Yalnız sentetik veri."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from bidr import havuz as H
from bidr.mask import run as R


# ---------------------------------------------------------------- havuz


def _yavas(j):
    if j.get("alt"):
        # alt süreç (OCR gibi): süreç grubuyla birlikte öldürülmeli
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        Path(j["alt"]).write_text(str(p.pid))
        p.wait()
    time.sleep(j.get("uyku", 0))
    if j.get("patla"):
        raise ValueError("sentetik")
    if j.get("cik"):
        os._exit(7)
    return {"dosya": j["ad"], "durum": "tamam"}


def _yasiyor(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:                                   # zombi (ebeveyni init değilse) yaşıyor sayılmaz
        out = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout
        return bool(out.strip()) and not out.strip().startswith("Z")
    except OSError:
        return True


def test_havuz_sure_asan_isi_alt_surecleriyle_keser_digerleri_surer(tmp_path):
    alt = tmp_path / "alt.pid"
    isler = [{"ad": "a"}, {"ad": "takilan", "alt": str(alt)}, {"ad": "c", "uyku": 0.2}]
    olen: list[int] = []
    bas = time.monotonic()
    out = H.calistir(_yavas, isler, isci=2, sinir=lambda j: 1.5 if j["ad"] == "takilan" else 30,
                     zaman_asimi=lambda j, sn: {"dosya": j["ad"], "durum": "zaman_asimi", "sn": sn},
                     beklenmedik=lambda j, n: {"dosya": j["ad"], "durum": "hata"}, olduruldu=olen.append,
                     aralik=0.2)
    assert time.monotonic() - bas < 20
    assert [r["dosya"] for r in out] == ["a", "takilan", "c"]          # iş sırası
    assert [r["durum"] for r in out] == ["tamam", "zaman_asimi", "tamam"]
    assert len(olen) == 1
    pid = int(alt.read_text())
    for _ in range(50):
        if not _yasiyor(pid):
            break
        time.sleep(0.1)
    assert not _yasiyor(pid), "alt süreç (tesseract yerine) öldürülmedi"


def test_havuz_istisna_ve_cokme_kosuyu_dusurmez():
    isler = [{"ad": "a", "patla": True}, {"ad": "b", "cik": True}, {"ad": "c"}]
    out = H.calistir(_yavas, isler, isci=2, sinir=lambda j: 30, zaman_asimi=None,
                     beklenmedik=lambda j, n: {"dosya": j["ad"], "durum": "hata", "neden": n}, aralik=0.2)
    assert [r["durum"] for r in out] == ["hata", "hata", "tamam"]
    assert "ValueError" in out[0]["neden"] and "çıkış 7" in out[1]["neden"]


def test_dosya_siniri_sayfa_ve_boyutla_buyur(tmp_path, monkeypatch):
    pypdf = pytest.importorskip("pypdf")
    w = pypdf.PdfWriter()
    for _ in range(4):
        w.add_blank_page(595, 842)
    pdf = tmp_path / "x.pdf"
    with open(pdf, "wb") as f:
        w.write(f)
    ayar = {"dosya": 120.0, "sayfa": 30.0, "mb": 10.0}
    assert H.dosya_siniri(pdf, ayar) == 120 + 4 * 30
    img = tmp_path / "x.png"
    img.write_bytes(b"\0" * 2_000_000)
    assert H.dosya_siniri(img, ayar) == pytest.approx(120 + 20)
    assert H.dosya_siniri(pdf, None) is None
    monkeypatch.setenv(H.ORTAM_DOSYA, "0")
    assert H.sure_ayari() is None                                        # 0: sınırsız
    monkeypatch.setenv(H.ORTAM_DOSYA, "60")
    assert H.sure_ayari()["dosya"] == 60 and H.sure_ayari(dosya=5)["dosya"] == 5


def test_kanit_kipi_sure_asimi_kaydi_ozgunu_birakir(tmp_path):
    from bidr.mask.kaynak import sure_asildi
    ev, dst_root, teslim = tmp_path / "evidence", tmp_path / "evidence-maskeli", tmp_path / "maskeleme-bekleyen"
    (ev / "B.1").mkdir(parents=True)
    src = ev / "B.1" / "1 Tarama.pdf"
    src.write_bytes(b"%PDF-1.4 sentetik")
    yarim = dst_root / "B.1" / "1 Tarama.pdf"
    yarim.parent.mkdir(parents=True)
    yarim.write_bytes(b"yarim")
    job = {"src": str(src), "rel": "B.1/1 Tarama.pdf", "dst": str(yarim), "dst_root": str(dst_root),
           "teslim_root": str(teslim)}
    rec = sure_asildi(job, 150.0)
    assert rec["durum"] == "zaman_asimi" and rec["elle_bakilmali"] and "150 sn" in rec["neden"]
    assert not yarim.exists() and src.exists()
    assert R.bekliyor(rec)                     # teslimde listelenir (maskeleme eksik), kanıt düşmez


# ---------------------------------------------------------------- --yalniz-kaynak

fitz = pytest.importorskip("pymupdf")


@pytest.fixture
def _temiz(monkeypatch):
    from bidr.mask import ocr as O
    from bidr.mask import onbellek as OB
    from bidr.mask import raster as RA
    O._CACHE.clear()
    OB.ac(None)
    OB._ACIK.clear()
    monkeypatch.delenv("BIDR_MASKE_WS", raising=False)
    RA._SABLON.clear()
    yield
    OB.ac(None)
    OB._ACIK.clear()
    RA._SABLON.clear()


def _pdf(path: Path, satirlar: list[str]) -> None:
    doc = fitz.open()
    p = doc.new_page()
    for i, t in enumerate(satirlar):
        p.insert_text((72, 120 + 20 * i), t, fontsize=10)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    doc.close()


def test_yalniz_kaynak_hic_hesaplamaz_var_olani_kullanir_olmayani_listeler(tmp_path, monkeypatch, _temiz):
    from bidr.mask.kaynak import YALNIZ_KAYNAK_DURUM, run_source
    from bidr.teslim.run import MASKE_OZGUN, Maske
    ws, kaynak, kopya = tmp_path / "ws", tmp_path / "bolum", tmp_path / "maskeli"
    ws.mkdir()
    _pdf(kaynak / "B.1" / "a.pdf", ["Kurul toplantisi yapildi.", "iletisim: deneme.birinci@ornek.edu.tr"])
    _pdf(kaynak / "B.1" / "b.pdf", ["Laboratuvar yenilendi."])
    run_source(kaynak, kopya, engine="pymupdf", ws=ws)
    ev = ws / "evidence"
    (ev / "B.1").mkdir(parents=True)
    shutil.copyfile(kopya / "B.1" / "a.pdf", ev / "B.1" / "1 Kurul.pdf")       # kaynak kipin maskeli çıktısı
    shutil.copyfile(kopya / "B.1" / "b.pdf", ev / "B.1" / "2 Lab.pdf")
    _pdf(ev / "B.2" / "3 Yeni.pdf", ["Sonradan dosyalanan belge (sentetik)."])   # kaynak maskesi yok

    def yasak(*a, **k):
        raise AssertionError("yalniz_kaynak kipinde maskeleme hesaplandı")
    monkeypatch.setattr(R, "mask_and_check", yasak)
    rap = R.run(ws, evidence=ev, engine="pymupdf", yalniz_kaynak=True)
    d = {r["dosya"]: r for r in rap["dosyalar"]}
    assert d["B.1/1 Kurul.pdf"]["kaynak_kipten"] and d["B.1/2 Lab.pdf"]["kaynak_kipten"]
    assert d["B.1/1 Kurul.pdf"]["durum"] != YALNIZ_KAYNAK_DURUM
    yeni = d["B.2/3 Yeni.pdf"]
    assert yeni["durum"] == YALNIZ_KAYNAK_DURUM and yeni["elle_bakilmali"] and R.bekliyor(yeni)
    assert not (ws / "evidence-maskeli" / "B.2" / "3 Yeni.pdf").exists()
    assert rap["yalniz_kaynak"] is True
    # teslim: dosya düşmez, olduğu gibi girer ve "maskelenmedi" diye listelenir
    kaynak_, deger, neden, bekleyen = Maske(ws, ev).sec(ev / "B.2" / "3 Yeni.pdf")
    assert kaynak_ == ev / "B.2" / "3 Yeni.pdf" and deger == MASKE_OZGUN and bekleyen and "yeniden" in neden


def test_yalniz_kaynak_eski_kaynak_sonucunu_kullanir_ve_listeler(tmp_path, monkeypatch, _temiz):
    """Kaynak maskelemesinden sonra girdi değişti (burada: dosyanın kararı): sonuç hesaplanmaz, kaynak kipin kaydı
    ve maskeli kopyası kullanılır, dosya "maskelenmedi" diye listelenir."""
    from bidr.mask.kaynak import YALNIZ_KAYNAK_DURUM, run_source
    ws, kaynak, kopya = tmp_path / "ws", tmp_path / "bolum", tmp_path / "maskeli"
    ws.mkdir()
    _pdf(kaynak / "a.pdf", ["Kurul toplantisi yapildi."])
    run_source(kaynak, kopya, engine="pymupdf", ws=ws)
    ev = ws / "evidence"
    ev.mkdir()
    shutil.copyfile(kopya / "a.pdf", ev / "1 Kurul.pdf")
    monkeypatch.setattr(R, "kaynak_sonucu", lambda *a, **k: None)     # girdisi değişmiş say
    monkeypatch.setattr(R, "mask_and_check", lambda *a, **k: (_ for _ in ()).throw(AssertionError("hesaplandı")))
    rap = R.run(ws, evidence=ev, engine="pymupdf", yalniz_kaynak=True)
    r = rap["dosyalar"][0]
    assert r["durum"] == YALNIZ_KAYNAK_DURUM and r["kaynak_eski"] and r["kaynak_durum"]
    assert R.bekliyor(r)


def test_yalniz_kaynak_ve_yalniz_oneri_birlikte_olmaz(tmp_path):
    (tmp_path / "evidence").mkdir()
    with pytest.raises(R.MaskRunError):
        R.run(tmp_path, yalniz_kaynak=True, yalniz_oneri=True)
