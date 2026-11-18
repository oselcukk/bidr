"""OCR: tesseract ve pdftoppm sistem araçları üzerinden (subprocess)."""
from __future__ import annotations

import functools
import re
import os
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
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


@dataclass
class OcrResult:
    """OCR metni + tesseract'ın kelime güvenleri (0-100; harf sayısıyla ağırlıklı ortalama)."""
    text: str
    conf: float | None  # kelime yoksa None
    words: int = 0

    def __str__(self) -> str:  # eski çağıranlar metni beklerse
        return self.text


def _tsv_conf(tsv: str) -> tuple[float | None, int]:
    tot = wsum = 0.0
    n = 0
    for line in tsv.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) < 12 or parts[0] != "5":
            continue
        word = parts[11].strip()
        try:
            c = float(parts[10])
        except ValueError:
            continue
        if not word or c < 0:
            continue
        w = max(1, sum(ch.isalnum() for ch in word))
        tot += c * w
        wsum += w
        n += 1
    return (tot / wsum if wsum else None), n


def ocr_image_q(path: Path) -> OcrResult:
    """Tek görseli OCR'la; metin ve güven birlikte (tek tesseract çağrısı: txt + tsv)."""
    if not ocr_available():
        raise OcrUnavailable(f"tesseract veya '{OCR_LANGS}' dil verisi yok")
    with tempfile.TemporaryDirectory(prefix="bidr-tess-") as td:
        base = Path(td) / "o"
        with _SLOTS:
            r = subprocess.run(
                ["tesseract", str(path), str(base), "-l", OCR_LANGS, "--psm", _psm(), "txt", "tsv"],
                capture_output=True, text=True, timeout=OCR_TIMEOUT, env=_env(),
            )
        if r.returncode != 0:
            raise RuntimeError(f"tesseract hata {r.returncode}: {r.stderr.strip()[:200]}")
        text = base.with_suffix(".txt").read_text(encoding="utf-8", errors="replace")
        tsv_p = base.with_suffix(".tsv")
        tsv = tsv_p.read_text(encoding="utf-8", errors="replace") if tsv_p.exists() else ""
    conf, n = _tsv_conf(tsv)
    return OcrResult(text, conf, n)


def ocr_image(path: Path) -> str:
    """Tek bir görsel dosyasını OCR'la (tesseract'ın okuyabildiği biçimde olmalı)."""
    return ocr_image_q(path).text


def ocr_pdf_page(pdf: Path, page: int) -> OcrResult:
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
        return ocr_image_q(img)


# ------------------------------------------------------------- metin sağlığı

_LETTERS = "A-Za-zÇĞİÖŞÜçğıöşüÂâÎîÛûÉéÀàÄäß"
_WORD = re.compile(rf"^[{_LETTERS}]+(?:[-'’][{_LETTERS}]+)*$")
_NUM = re.compile(r"^[\d.,:/%()+\-–]*\d[\d.,:/%()+\-–]*$")
# e-posta, URL, kod (FR-0069, MBG111, A.1.2) da sağlıklı belirteçtir
_SPECIAL = re.compile(r"^(?:[\w.+-]+@[\w-]+(?:\.[\w-]+)+|(?:https?://|www\.)\S+"
                      r"|[A-ZÇĞİÖŞÜ]{1,6}[-.]?\d+(?:[-.]\d+)*)$")
_VOWELS = set("aeıioöuüâîûéàäAEIİOÖUÜÂÎÛÉÀÄ")
_PUNCT = "\"'“”‘’()[]{}<>.,;:!?«»|*•·-–—_"


def text_health(text: str) -> float | None:
    """Kelime benzeri belirteçlerin karakter payı (0-1). OCR çöpünü ayırmak için.

    İyi belirteç: (noktalamadan arındırılmış) en az 2 harfli, yalnız harf, büyük/küçük
    düzeni makul (tümü büyük, tümü küçük ya da baş harf büyük), 4+ harfliyse sesli
    harf içeren kelime; ya da rakam içeren sayı/tarih. Belirteç yoksa None.
    """
    good = total = 0
    for tok in text.split():
        core = tok.strip(_PUNCT)
        n = len(tok)
        total += n
        if not core:
            continue
        if _NUM.match(core) or _SPECIAL.match(core):
            good += n
            continue
        if len(core) < 2 or not _WORD.match(core):
            continue
        body = core[1:]
        if not (core.isupper() or core.islower() or body.islower()):
            continue
        if len(core) >= 4 and not any(c in _VOWELS for c in core):
            continue
        good += n
    return good / total if total else None
