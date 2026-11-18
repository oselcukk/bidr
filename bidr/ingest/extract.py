"""Belge türüne göre metin çıkarma. Her çıkarıcı `Extraction` döndürür.

Sayfalar ayrı tutulur; çıktı dosyasında '\\f' ile birleştirilir. Sayfa kavramı
olmayan biçimlerde (docx, odt) tek "sayfa" döner; xlsx'te her çalışma sayfası,
pptx'te her slayt bir sayfadır.
"""
from __future__ import annotations

import datetime as _dt
import re
import subprocess
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

from . import ocr

# Bir PDF sayfasının metin katmanı bu kadar harf/rakamdan azsa OCR'a düşülür.
MIN_PAGE_ALNUM = 40
# Bu kadardan az metin + sayfada görsel varsa (taranmış sayfa üstünde EBYS damgası
# gibi) OCR da denenir; OCR belirgin şekilde daha çok metin verirse o kullanılır.
STAMP_PAGE_ALNUM = 400
PDF_PAGE_WORKERS = 4


class Unsupported(Exception):
    pass


@dataclass
class Extraction:
    pages: list[str]
    method: str
    page_count: int | None = None
    ocr_pages: int = 0
    # OCR gerekiyordu ama kapalıydı / yapılamadı (sayfa sayısı)
    ocr_missing: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\f".join(self.pages)


def _alnum(s: str) -> int:
    return sum(ch.isalnum() for ch in s)


def _clean(s: str) -> str:
    lines = [ln.rstrip() for ln in s.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    out: list[str] = []
    blank = 0
    for ln in lines:
        if ln.strip():
            blank = 0
            out.append(ln)
        else:
            blank += 1
            if blank == 1:
                out.append("")
    return "\n".join(out).strip("\n")


def _run(cmd: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


# --------------------------------------------------------------------------- PDF

def _pdf_pages(path: Path) -> int | None:
    r = _run(["pdfinfo", str(path)], timeout=60)
    m = re.search(rb"^Pages:\s+(\d+)", r.stdout, re.M)
    return int(m.group(1)) if m else None


def _pdf_image_pages(path: Path) -> set[int]:
    """Üzerinde büyükçe (>=200x200) görsel bulunan sayfalar."""
    r = _run(["pdfimages", "-list", str(path)], timeout=120)
    pages: set[int] = set()
    for line in r.stdout.decode("utf-8", "replace").splitlines()[2:]:
        parts = line.split()
        if len(parts) >= 5 and parts[0].isdigit():
            try:
                w, h = int(parts[3]), int(parts[4])
            except ValueError:
                continue
            if w >= 200 and h >= 200:
                pages.add(int(parts[0]))
    return pages


def _garbled(s: str) -> bool:
    """ToUnicode eşlemesi olmayan fontlar: metin katmanı var ama okunamaz."""
    vis = [c for c in s if not c.isspace()]
    if len(vis) < 20:
        return False
    bad = sum(1 for c in vis if c == "�" or 0xE000 <= ord(c) <= 0xF8FF or ord(c) < 32)
    return bad / len(vis) > 0.2 or "(cid:" in s


def extract_pdf(path: Path, use_ocr: bool) -> Extraction:
    n = _pdf_pages(path)
    r = _run(["pdftotext", "-layout", "-enc", "UTF-8", str(path), "-"])
    if r.returncode != 0 and not r.stdout:
        raise RuntimeError(f"pdftotext hata {r.returncode}: {r.stderr.decode('utf-8', 'replace')[:200]}")
    raw = r.stdout.decode("utf-8", "replace").split("\f")
    if raw and not raw[-1].strip():
        raw = raw[:-1]
    if n is None:
        n = len(raw)
    raw += [""] * (n - len(raw))
    pages = [_clean(p) for p in raw[:n]] if n else [_clean(p) for p in raw]

    weak = [i for i, p in enumerate(pages) if _alnum(p) < STAMP_PAGE_ALNUM or _garbled(p)]
    img_pages = _pdf_image_pages(path) if weak else set()
    ocr_pages = ocr_missing = 0
    can_ocr = use_ocr and ocr.ocr_available()
    jobs: list[tuple[int, bool]] = []
    for i in weak:
        p = pages[i]
        must = _alnum(p) < MIN_PAGE_ALNUM or _garbled(p)
        maybe = (i + 1) in img_pages
        if not (must or maybe):
            continue
        if not can_ocr:
            if must and maybe:
                ocr_missing += 1
            continue
        jobs.append((i, must))
    # Sayfalar paralel OCR'lanır; toplam eşzamanlı OCR ocr modülünde sınırlıdır.
    with ThreadPoolExecutor(max_workers=PDF_PAGE_WORKERS) as pool:
        results = list(pool.map(lambda j: _clean(ocr.ocr_pdf_page(path, j[0] + 1)), jobs))
    for (i, must), t in zip(jobs, results):
        p = pages[i]
        a = _alnum(p)
        ta = _alnum(t)
        # Zorunlu durumda OCR daha çok metin verdiyse; damga durumunda belirgin
        # (2 kat) fazlaysa OCR metni kullanılır.
        if (must and (ta > a or _garbled(p))) or (not must and ta > 2 * a):
            pages[i] = t
            ocr_pages += 1
    method = "pdftotext" + (f"+ocr({ocr_pages}/{len(pages)})" if ocr_pages else "")
    return Extraction(pages, method, n, ocr_pages, ocr_missing)


# ------------------------------------------------------------------------ Görsel

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".gif", ".webp", ".heic", ".heif"}


def extract_image(path: Path, use_ocr: bool) -> Extraction:
    from PIL import Image, ImageOps

    with tempfile.TemporaryDirectory(prefix="bidr-img-") as td:
        src = path
        if path.suffix.lower() in {".heic", ".heif"}:
            conv = Path(td) / "conv.png"
            r = _run(["sips", "-s", "format", "png", str(path), "--out", str(conv)], timeout=120)
            if r.returncode != 0 or not conv.exists():
                raise RuntimeError("HEIC dönüştürülemedi (sips)")
            src = conv
        frames: list[Path] = []
        with Image.open(src) as im:
            nframes = getattr(im, "n_frames", 1)
            for k in range(nframes):
                im.seek(k)
                fr = ImageOps.exif_transpose(im.copy()).convert("L")
                out = Path(td) / f"f{k}.png"
                fr.save(out)
                frames.append(out)
        if not use_ocr or not ocr.ocr_available():
            return Extraction([""] * len(frames), "image(no-ocr)", len(frames), 0, len(frames))
        pages = [_clean(ocr.ocr_image(f)) for f in frames]
    return Extraction(pages, "ocr", len(pages), len(pages), 0)


# -------------------------------------------------------------------------- DOCX

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"


def _docx_para(p: ET.Element) -> list[str]:
    buf: list[str] = []
    extra: list[str] = []

    def walk(node: ET.Element) -> None:
        for ch in node:
            tag = ch.tag
            if tag == W + "t":
                buf.append(ch.text or "")
            elif tag == W + "tab":
                buf.append("\t")
            elif tag in (W + "br", W + "cr"):
                buf.append("\n")
            elif tag == W + "noBreakHyphen":
                buf.append("-")
            elif tag in (W + "delText", W + "instrText", MC_FALLBACK, W + "rPr", W + "pPr"):
                continue
            elif tag == W + "txbxContent":
                extra.extend(_docx_blocks(ch))
            else:
                walk(ch)

    walk(p)
    return ["".join(buf)] + extra


def _direct(el: ET.Element, tag: str) -> list[ET.Element]:
    out: list[ET.Element] = []
    for ch in el:
        if ch.tag == tag:
            out.append(ch)
        elif ch.tag in (W + "sdt", W + "sdtContent", W + "customXml"):
            out.extend(_direct(ch, tag))
    return out


def _docx_table(tbl: ET.Element) -> list[str]:
    lines: list[str] = []
    # Yalnız bu tablonun kendi satır/hücreleri (iter() iç içe tablolarınkini de verirdi);
    # içerik denetimi (sdt) sarmalayıcıları açılır.
    rows = _direct(tbl, W + "tr")
    for tr in rows:
        cells = []
        nested = False
        for tc in _direct(tr, W + "tc"):
            if any(ch.tag == W + "tbl" for ch in tc):
                nested = True
            cells.append([ln for ln in _docx_blocks(tc) if ln.strip()])
        if nested:
            # İç içe tablo: hücre içeriklerini blok halinde, sırayla yaz.
            for c in cells:
                lines.extend(c)
        elif any(cells):  # tamamen boş satırlar yazılmaz
            lines.append(" | ".join(" ".join(c) for c in cells))
    return lines


def _docx_blocks(el: ET.Element) -> list[str]:
    out: list[str] = []
    for ch in el:
        tag = ch.tag
        if tag == W + "p":
            out.extend(_docx_para(ch))
        elif tag == W + "tbl":
            out.extend(_docx_table(ch))
        elif tag in (W + "tcPr", W + "tblPr", W + "sectPr", W + "pPr", MC_FALLBACK):
            continue
        else:
            out.extend(_docx_blocks(ch))
    return out


def _docx_part(z: zipfile.ZipFile, name: str) -> str:
    root = ET.fromstring(z.read(name))
    return _clean("\n".join(_docx_blocks(root)))


def _part_sort_key(name: str) -> tuple[int, str]:
    m = re.search(r"(\d+)\.xml$", name)
    return (int(m.group(1)) if m else 0, name)


def extract_docx(path: Path, use_ocr: bool = True) -> Extraction:
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if "word/document.xml" not in names:
            raise RuntimeError("word/document.xml yok")
        heads = sorted((n for n in names if re.fullmatch(r"word/header\d*\.xml", n)), key=_part_sort_key)
        foots = sorted((n for n in names if re.fullmatch(r"word/footer\d*\.xml", n)), key=_part_sort_key)
        notes = [n for n in ("word/footnotes.xml", "word/endnotes.xml") if n in names]

        def uniq(parts: list[str]) -> list[str]:
            seen, res = set(), []
            for n in parts:
                t = _docx_part(z, n)
                if t.strip() and t not in seen:
                    seen.add(t)
                    res.append(t)
            return res

        sections: list[str] = []
        h = uniq(heads)
        if h:
            sections.append("[üstbilgi]\n" + "\n".join(h))
        sections.append(_docx_part(z, "word/document.xml"))
        nt = uniq(notes)
        if nt:
            sections.append("[dipnot]\n" + "\n".join(nt))
        f = uniq(foots)
        if f:
            sections.append("[altbilgi]\n" + "\n".join(f))
        pages = None
        if "docProps/app.xml" in names:
            m = re.search(rb"<(?:\w+:)?Pages>(\d+)<", z.read("docProps/app.xml"))
            if m:
                pages = int(m.group(1))
    return Extraction(["\n\n".join(s for s in sections if s.strip())], "docx-xml", pages)


# ------------------------------------------------------------- doc / rtf / odt

def _textutil(path: Path) -> str:
    r = _run(["textutil", "-convert", "txt", "-encoding", "UTF-8", "-stdout", str(path)], timeout=180)
    if r.returncode != 0:
        raise RuntimeError(f"textutil hata {r.returncode}: {r.stderr.decode('utf-8', 'replace')[:200]}")
    return r.stdout.decode("utf-8", "replace")


def _odt_header_footer(path: Path) -> tuple[str, str]:
    ns_style = "{urn:oasis:names:tc:opendocument:xmlns:style:1.0}"
    try:
        with zipfile.ZipFile(path) as z:
            root = ET.fromstring(z.read("styles.xml"))
    except Exception:
        return "", ""

    def collect(tags: tuple[str, ...]) -> str:
        seen, res = set(), []
        for el in root.iter():
            if el.tag in tags:
                t = _clean(" ".join(x.strip() for x in el.itertext() if x.strip()))
                if t and t not in seen:
                    seen.add(t)
                    res.append(t)
        return "\n".join(res)

    hs = tuple(ns_style + t for t in ("header", "header-left", "header-first"))
    fs = tuple(ns_style + t for t in ("footer", "footer-left", "footer-first"))
    return collect(hs), collect(fs)


def extract_textutil(path: Path, use_ocr: bool = True) -> Extraction:
    body = _clean(_textutil(path))
    if path.suffix.lower() == ".odt":
        h, f = _odt_header_footer(path)
        parts = ([f"[üstbilgi]\n{h}"] if h else []) + [body] + ([f"[altbilgi]\n{f}"] if f else [])
        return Extraction(["\n\n".join(p for p in parts if p)], "textutil+odt-styles", None)
    return Extraction([body], "textutil", None)


# -------------------------------------------------------------------------- XLSX

def _cell_str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, _dt.datetime):
        return v.date().isoformat() if v.time() == _dt.time() else v.isoformat(sep=" ")
    if isinstance(v, (_dt.date, _dt.time)):
        return v.isoformat()
    return str(v).strip()


def extract_xlsx(path: Path, use_ocr: bool = True) -> Extraction:
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    pages = []
    try:
        for ws in wb.worksheets:
            lines = [f"[sayfa: {ws.title}]"]
            for row in ws.iter_rows(values_only=True):
                cells = [_cell_str(v) for v in row]
                while cells and not cells[-1]:
                    cells.pop()
                if any(cells):
                    lines.append("\t".join(cells))
            pages.append("\n".join(lines))
    finally:
        wb.close()
    return Extraction(pages, "openpyxl", len(pages))


# -------------------------------------------------------------------------- PPTX

def extract_pptx(path: Path, use_ocr: bool = True) -> Extraction:
    from pptx import Presentation

    prs = Presentation(str(path))

    def shape_lines(shape) -> list[str]:
        out: list[str] = []
        if getattr(shape, "shape_type", None) == 6 or hasattr(shape, "shapes"):  # grup
            for s in getattr(shape, "shapes", []):
                out.extend(shape_lines(s))
            return out
        if getattr(shape, "has_table", False) and shape.has_table:
            for row in shape.table.rows:
                out.append(" | ".join(c.text.replace("\n", " ").strip() for c in row.cells))
        if getattr(shape, "has_text_frame", False) and shape.has_text_frame:
            out.append(shape.text_frame.text)
        return out

    pages = []
    for slide in prs.slides:
        lines: list[str] = []
        for sh in slide.shapes:
            lines.extend(shape_lines(sh))
        if slide.has_notes_slide:
            nt = slide.notes_slide.notes_text_frame.text if slide.notes_slide.notes_text_frame else ""
            if nt.strip():
                lines.append("[not]\n" + nt)
        pages.append(_clean("\n".join(lines)))
    return Extraction(pages, "python-pptx", len(pages))


# ---------------------------------------------------------------- düz metin/HTML

def _decode(b: bytes) -> str:
    for enc in ("utf-8-sig", "cp1254"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("latin-1")


def extract_text(path: Path, use_ocr: bool = True) -> Extraction:
    return Extraction([_clean(_decode(path.read_bytes()))], "text", None)


class _HTMLText(HTMLParser):
    BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section", "article"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self.skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")
        elif tag in ("td", "th"):
            self.parts.append(" | ")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head") and self.skip:
            self.skip -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def extract_html(path: Path, use_ocr: bool = True) -> Extraction:
    p = _HTMLText()
    p.feed(_decode(path.read_bytes()))
    text = "".join(p.parts)
    text = re.sub(r"[ \t ]+", " ", text)
    return Extraction([_clean(text)], "html", None)


# ----------------------------------------------------------------------- Yönlendirme

EXTRACTORS = {
    ".pdf": extract_pdf,
    ".docx": extract_docx, ".docm": extract_docx, ".dotx": extract_docx,
    ".doc": extract_textutil, ".rtf": extract_textutil, ".odt": extract_textutil,
    ".xlsx": extract_xlsx, ".xlsm": extract_xlsx,
    ".pptx": extract_pptx,
    ".txt": extract_text, ".csv": extract_text, ".tsv": extract_text, ".md": extract_text,
    ".html": extract_html, ".htm": extract_html,
    **{e: extract_image for e in IMAGE_EXTS},
}


def extract(path: Path, use_ocr: bool = True) -> Extraction:
    fn = EXTRACTORS.get(path.suffix.lower())
    if fn is None:
        raise Unsupported(path.suffix.lower() or "(uzantısız)")
    return fn(path, use_ocr)
