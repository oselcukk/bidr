"""OCR sarmalayıcısının sağlamlığı (sentetik; gerçek tesseract çağrılmaz)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from bidr.ingest import ocr


@pytest.fixture
def fake_tess(monkeypatch):
    monkeypatch.setattr(ocr, "ocr_available", lambda: True)
    monkeypatch.setattr(ocr, "_psm", lambda: "3")
    calls = []

    def install(rc=0, stderr=b"", write=True):
        def run(cmd, **kw):
            assert "text" not in kw, "çıktı bayt olarak okunmalı"
            calls.append((cmd, kw))
            base = Path(cmd[2])
            if write:
                base.with_suffix(".txt").write_text("Merhaba dünya", encoding="utf-8")
                base.with_suffix(".tsv").write_text("level\n", encoding="utf-8")
            return subprocess.CompletedProcess(cmd, rc, b"", stderr)
        monkeypatch.setattr(ocr.subprocess, "run", run)
        return calls
    return install


def test_non_utf8_stderr_does_not_crash(fake_tess, tmp_path):
    # Latin-1/cp1254 baytları: text=True ile UnicodeDecodeError verirdi
    fake_tess(rc=0, stderr=b"Warning: Invalid resolution 0 dpi. \xfe\xf0\xfd \xff")
    assert ocr.ocr_image_q(tmp_path / "x.png").text == "Merhaba dünya"


def test_non_utf8_stderr_on_failure_is_readable(fake_tess, tmp_path):
    fake_tess(rc=1, stderr=b"Fehler \xe4\xf6 bozuk", write=False)
    with pytest.raises(RuntimeError) as e:
        ocr.ocr_image_q(tmp_path / "x.png")
    assert "tesseract hata 1" in str(e.value) and "�" in str(e.value)


def test_cannot_open_temp_file_explains_tmpdir(fake_tess, tmp_path):
    fake_tess(rc=1, stderr=b"Error in pixRead: image file not found: /tmp/bidr-ocr-x/p.png\n"
                            b"Cannot open input file: /tmp/bidr-ocr-x/p.png", write=False)
    with pytest.raises(RuntimeError) as e:
        ocr.ocr_image_q(tmp_path / "p.png")
    assert "TMPDIR" in str(e.value) and "geçici dosyayı açamadı" in str(e.value)


def test_tmpdir_respected(fake_tess, tmp_path, monkeypatch):
    calls = fake_tess()
    tmp = tmp_path / "calisma-tmp"
    tmp.mkdir()
    monkeypatch.setenv("TMPDIR", str(tmp))
    assert ocr.temp_root() == str(tmp)
    ocr.ocr_image_q(tmp_path / "x.png")
    out_base = Path(calls[0][0][2])
    assert tmp in out_base.parents
    assert calls[0][1]["env"]["TMPDIR"] == str(tmp)


def test_tmpdir_missing_falls_back(monkeypatch, tmp_path):
    monkeypatch.setenv("TMPDIR", str(tmp_path / "yok"))
    assert ocr.temp_root() is None


def test_list_langs_bytes(monkeypatch):
    monkeypatch.setattr(ocr.shutil, "which", lambda n: "/usr/bin/tesseract")
    monkeypatch.setattr(ocr.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, 0, b"List of available languages \xfe(3):\neng\nosd\ntur\n", b""))
    ocr.available_langs.cache_clear()
    try:
        assert ocr.available_langs() == frozenset({"eng", "osd", "tur"})
    finally:
        ocr.available_langs.cache_clear()
