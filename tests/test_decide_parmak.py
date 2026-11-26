"""Karar aşaması paket girdisi parmak izi (bidr/decide/parmak.py): kod dosyaları sözdizimi olarak girer
(belge dizgesi/yorum düzenlemesi aşamaları eskitmez), eski şema 1 izi yalnız dondurulmuş eski run.py ile
birebir tutar ve aradaki fark davranışsızsa geçerli sayılır. Sahte model; sentetik veri."""
from __future__ import annotations

import gzip
import json

import pytest

from bidr.common import Workspace
from bidr.decide import parmak as PM
from bidr.decide import run as R
from bidr.decide.run import prepare

from test_decide import FakeLLM, ws  # noqa: F401  (ws: fixture)
from test_guncel_karar import _check, _full

RUN = next(p for p in R.FINGERPRINT_CODE if p.name == "run.py")


def _docstring_edit(src: str) -> str:
    """Modül açıklamasına satır ve yeni bir yorum ekler (davranışsız)."""
    i = src.index('"""') + 3
    return src[:i] + "Davranışsız açıklama satırı.\n" + src[i:] + "\n# yeni yorum\n"


def test_sozdizimi_docstring_ve_yorum_yok_sayilir():
    a = 'def f(x):\n    """Açıklama."""\n    # yorum\n    return x + 1\n'
    b = 'def f(x):\n    """Bambaşka açıklama,\n    iki satır."""\n    return x + 1  # başka yorum\n'
    c = 'def f(x):\n    return x + 2\n'
    d = 'def f(x):\n    """Yalnız açıklama."""\n'
    assert PM.sozdizimi(a) == PM.sozdizimi(b) != PM.sozdizimi(c)
    assert "pass" in PM.sozdizimi(d)                    # gövdesi yalnız açıklama: geçerli kalır
    assert PM.sozdizimi("x = 'veri'\n") != PM.sozdizimi("x = 'başka'\n")   # değer dizgesi davranıştır
    e = 'def input_fingerprint(ws, s):\n    return 1\nY = 2\n'
    assert PM.sozdizimi(e, PM.RUN_DISI) == PM.sozdizimi("Y = 2\n")


def test_kod_belge_dizgesi_degisince_iz_ayni_davranis_degisince_farkli(ws, tmp_path, monkeypatch):
    root, _ = ws
    src = RUN.read_text(encoding="utf-8")
    kopya = tmp_path / "decide" / "run.py"
    kopya.parent.mkdir()
    kopya.write_text(src, encoding="utf-8")
    monkeypatch.setattr(R, "FINGERPRINT_CODE", (kopya,) + R.FINGERPRINT_CODE[1:])
    once = R.input_fingerprint(Workspace(root), "coarse")
    assert once.startswith(PM.SEMA)
    kopya.write_text(_docstring_edit(src), encoding="utf-8")
    assert R.input_fingerprint(Workspace(root), "coarse") == once
    kopya.write_text(src + "\nYENI_SABIT = 1\n", encoding="utf-8")
    assert R.input_fingerprint(Workspace(root), "coarse") != once


def test_docstring_duzenlemesi_tamam_asamayi_eskitmez(ws, tmp_path, monkeypatch):
    root, _ = ws
    fake = FakeLLM()
    kopya = tmp_path / "decide" / "run.py"
    kopya.parent.mkdir()
    kopya.write_text(RUN.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(R, "FINGERPRINT_CODE", (kopya,) + R.FINGERPRINT_CODE[1:])
    _full(root, fake, fake.backend())
    assert _check(root, "coarse").bitti and _check(root, "fine").bitti
    kopya.write_text(_docstring_edit(kopya.read_text(encoding="utf-8")), encoding="utf-8")
    assert _check(root, "coarse").bitti and _check(root, "fine").bitti
    kopya.write_text(kopya.read_text(encoding="utf-8") + "\nYENI_SABIT = 1\n", encoding="utf-8")
    ck = _check(root, "fine")
    assert not ck.bitti and ck.komutlar == ["PREP"] and "eski olabilir" in ck.neden


@pytest.fixture
def eski_dir(tmp_path, monkeypatch):
    d = tmp_path / "parmak_eski"
    d.mkdir()
    monkeypatch.setattr(PM, "ESKI_DIR", d)
    PM._eski_runlar.cache_clear()
    yield d
    PM._eski_runlar.cache_clear()


def _sema1_kaydi(root, stage, eski: bytes):
    """Eski sürümün yazdığı kaydı taklit eder: şema 1 iz (önek yok), eski run.py baytlarıyla."""
    f = R.restale_path(Workspace(root), stage)
    d = json.loads(f.read_text(encoding="utf-8"))
    d["parmak"] = PM.sema1(Workspace(root), stage, eski)
    assert not d["parmak"].startswith(PM.SEMA)
    f.write_text(json.dumps(d), encoding="utf-8")


def test_eski_sema_izi_davranissiz_farkta_gecerli(ws, eski_dir):
    """Geçiş: eski sürüm (run.py'si bugünkünden yalnız açıklamayla ayrılır) izi yazmış; yeni sürüm
    kurulunca aşama eskimez, model çağrısı gerekmez."""
    root, _ = ws
    fake = FakeLLM()
    _full(root, fake, fake.backend())
    eski = _docstring_edit(RUN.read_text(encoding="utf-8")).encode("utf-8")
    (eski_dir / "run-eski.py.gz").write_bytes(gzip.compress(eski))
    for stage in ("coarse", "fine"):
        _sema1_kaydi(root, stage, eski)
        assert _check(root, stage).bitti
    # girdi değişti (belge notu/metin): eski iz artık tutmaz → prepare istenir
    t = sorted((root / "text").glob("*.txt"))[0]
    t.write_text(t.read_text(encoding="utf-8") + " ek", encoding="utf-8")
    ck = _check(root, "coarse")
    assert not ck.bitti and "eski olabilir" in ck.neden
    # prepare izi yeni şemayla yazar
    prepare(root, "coarse", backend=fake.backend())
    assert R.load_restale(Workspace(root), "coarse")["parmak"].startswith(PM.SEMA)


def test_eski_sema_izi_davranis_farkinda_ya_da_bilinmeyen_kodda_eski(ws, eski_dir):
    root, _ = ws
    fake = FakeLLM()
    _full(root, fake, fake.backend())
    davranisli = (RUN.read_text(encoding="utf-8") + "\nYENI_SABIT = 1\n").encode("utf-8")
    (eski_dir / "run-eski.py.gz").write_bytes(gzip.compress(davranisli))
    _sema1_kaydi(root, "fine", davranisli)
    assert not _check(root, "fine").bitti               # iz tutar ama kod davranışı farklı
    bilinmeyen = _docstring_edit(RUN.read_text(encoding="utf-8")).encode("utf-8") + b"\n# x\n"
    _sema1_kaydi(root, "fine", bilinmeyen)              # dondurulmamış sürümün izi
    assert not _check(root, "fine").bitti


def test_dondurulmus_run_okunur_ve_sozdizimi_kurulur():
    PM._eski_runlar.cache_clear()
    eski = PM._eski_runlar()
    assert eski, "parmak_eski/ altında dondurulmuş run.py yok"
    for b in eski:
        assert "def input_fingerprint" in PM.sozdizimi(b.decode("utf-8"))
