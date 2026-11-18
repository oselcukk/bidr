"""OCR: tesseract ve pdftoppm sistem araçları üzerinden (subprocess)."""
from __future__ import annotations

import functools
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

OCR_LANGS = "tur+eng"
OCR_DPI = 300
OCR_TIMEOUT = 300  # saniye, sayfa başına
# Süreç genelinde eşzamanlı OCR sınırı (dosya ve sayfa paralelliği birlikte).
_SLOTS = threading.BoundedSemaphore(max(1, os.cpu_count() or 2))


class OcrUnavailable(RuntimeError):
    pass


def _env() -> dict:
    env = dict(os.environ)
    # Paralel dosya işlerken tesseract'ın kendi iş parçacıkları çekirdekleri boğmasın.
    env.setdefault("OMP_THREAD_LIMIT", "1")
    return env


@functools.lru_cache(maxsize=1)
def available_langs() -> frozenset[str]:
    exe = shutil.which("tesseract")
    if not exe:
        return frozenset()
    r = subprocess.run([exe, "--list-langs"], capture_output=True, text=True)
    out = (r.stdout or "") + (r.stderr or "")
    return frozenset(line.strip() for line in out.splitlines()[1:] if line.strip())


def ocr_available() -> bool:
    langs = available_langs()
    return bool(langs) and all(l in langs for l in OCR_LANGS.split("+"))


def _psm() -> str:
    # 1 = otomatik sayfa bölme + yön/yazı tespiti (döndürülmüş taramalar için).
    return "1" if "osd" in available_langs() else "3"


def ocr_image(path: Path) -> str:
    """Tek bir görsel dosyasını OCR'la (tesseract'ın okuyabildiği biçimde olmalı)."""
    if not ocr_available():
        raise OcrUnavailable(f"tesseract veya '{OCR_LANGS}' dil verisi yok")
    with _SLOTS:
        r = subprocess.run(
            ["tesseract", str(path), "stdout", "-l", OCR_LANGS, "--psm", _psm()],
            capture_output=True, text=True, timeout=OCR_TIMEOUT, env=_env(),
        )
    if r.returncode != 0:
        raise RuntimeError(f"tesseract hata {r.returncode}: {r.stderr.strip()[:200]}")
    return r.stdout


def ocr_pdf_page(pdf: Path, page: int) -> str:
    """PDF'nin 1 tabanlı `page` sayfasını görüntüye çevirip OCR'la."""
    if not shutil.which("pdftoppm"):
        raise OcrUnavailable("pdftoppm yok")
    with tempfile.TemporaryDirectory(prefix="bidr-ocr-") as td:
        prefix = Path(td) / "p"
        r = subprocess.run(
            ["pdftoppm", "-r", str(OCR_DPI), "-gray", "-png", "-f", str(page),
             "-l", str(page), "-singlefile", str(pdf), str(prefix)],
            capture_output=True, text=True, timeout=OCR_TIMEOUT,
        )
        img = prefix.with_suffix(".png")
        if r.returncode != 0 or not img.exists():
            raise RuntimeError(f"pdftoppm hata {r.returncode}: {r.stderr.strip()[:200]}")
        return ocr_image(img)
