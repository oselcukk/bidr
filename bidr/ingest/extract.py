"""Belge türüne göre metin çıkarma. Her çıkarıcı `Extraction` döndürür.

Sayfalar ayrı tutulur; çıktı dosyasında '\\f' ile birleştirilir. Sayfa kavramı
olmayan biçimlerde (docx, odt) tek "sayfa" döner; xlsx'te her çalışma sayfası,
pptx'te her slayt bir sayfadır.
"""
from __future__ import annotations

import datetime as _dt
import io
import posixpath
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
# Metin katmanı yeterli sayfada OCR atlanır: sayfadaki büyükçe görseller sayfa
# alanının LOGO_COVER'ından azını kaplıyor (logo/küçük şekil) ve metin katmanında en
# az TEXT_ENOUGH harf/rakam var. Gerçek veride (2025) daha geniş bir eşik (ör. kapsama
# < %50) metin kaybettirdi: Word'e yapıştırılmış ekran görüntüleri ve "Print To PDF"
# sayfalarında (metin vektör çizim) OCR, metin katmanının 5-30 katı metin veriyor.
LOGO_COVER = 0.05
TEXT_ENOUGH = 300


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
    # Metne giren her OCR parçası: (metin, tesseract güveni 0-100 | None)
    ocr_units: list[tuple[str, float | None]] = field(default_factory=list)
    # Gömülü görseller: OCR'lanıp metne eklenen / düşük kalite yüzünden eklenmeyen
    images_ocr: int = 0
    images_lowq: int = 0
    # Kalitesi düşük bulunup metne eklenmeyen OCR parçaları (yalnız ölçüm için)
    ocr_dropped: list[tuple[str, float | None]] = field(default_factory=list)

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


def _pdf_page_sizes(path: Path, n: int) -> dict[int, float]:
    """Sayfa alanları (pt²), 1 tabanlı."""
    r = _run(["pdfinfo", "-f", "1", "-l", str(max(1, n)), str(path)], timeout=60)
    out: dict[int, float] = {}
    for m in re.finditer(rb"^Page\s+(\d+) size:\s+([\d.]+) x ([\d.]+)", r.stdout, re.M):
        out[int(m.group(1))] = float(m.group(2)) * float(m.group(3))
    return out


def _pdf_image_cover(path: Path, n: int) -> dict[int, float]:
    """Büyükçe (>=200x200 piksel) görsel içeren sayfalar ve görsellerin kapladığı
    alan payı (0-1+). Taranmış sayfada ~1, logoda ~0.01. Kapsama, piksel boyutu ve
    poppler'ın yerleşimden hesapladığı ppi ile bulunur.
    """
    r = _run(["pdfimages", "-list", str(path)], timeout=120)
    areas = _pdf_page_sizes(path, n)
    cover: dict[int, float] = {}
    for line in r.stdout.decode("utf-8", "replace").splitlines()[2:]:
        parts = line.split()
        if len(parts) < 14 or not parts[0].isdigit() or parts[2] != "image":
            continue
        try:
            pg, w, h = int(parts[0]), int(parts[3]), int(parts[4])
            xppi, yppi = float(parts[12]), float(parts[13])
        except ValueError:
            continue
        if w < 200 or h < 200:
            continue
        area = areas.get(pg)
        if not area or xppi <= 0 or yppi <= 0:
            cover[pg] = max(cover.get(pg, 0.0), 1.0)  # ölçülemedi: tarama say (eski davranış)
            continue
        cover[pg] = cover.get(pg, 0.0) + (w / xppi * 72) * (h / yppi * 72) / area
    return cover


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
    cover = _pdf_image_cover(path, n or len(pages)) if weak else {}
    ocr_pages = ocr_missing = 0
    can_ocr = use_ocr and ocr.ocr_available()
    jobs: list[tuple[int, bool]] = []
    for i in weak:
        p = pages[i]
        must = _alnum(p) < MIN_PAGE_ALNUM or _garbled(p)
        c = cover.get(i + 1)
        maybe = c is not None and not (c < LOGO_COVER and _alnum(p) >= TEXT_ENOUGH)
        if not (must or maybe):
            continue
        if not can_ocr:
            if must and (i + 1) in cover:
                ocr_missing += 1
            continue
        jobs.append((i, must))
    # Sayfalar paralel OCR'lanır; toplam eşzamanlı OCR ocr modülünde sınırlıdır.
    with ThreadPoolExecutor(max_workers=PDF_PAGE_WORKERS) as pool:
        results = list(pool.map(lambda j: ocr.ocr_pdf_page(path, j[0] + 1), jobs))
    units: list[tuple[str, float | None]] = []
    for (i, must), res in zip(jobs, results):
        t = _clean(res.text)
        p = pages[i]
        a = _alnum(p)
        ta = _alnum(t)
        # Zorunlu durumda OCR daha çok metin verdiyse; damga durumunda belirgin
        # (2 kat) fazlaysa OCR metni kullanılır.
        if (must and (ta > a or _garbled(p))) or (not must and ta > 2 * a):
            pages[i] = t
            ocr_pages += 1
            units.append((t, res.conf))
    method = "pdftotext" + (f"+ocr({ocr_pages}/{len(pages)})" if ocr_pages else "")
    return Extraction(pages, method, n, ocr_pages, ocr_missing, ocr_units=units)


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
        res = [ocr.ocr_image_q(f) for f in frames]
    pages = [_clean(r.text) for r in res]
    return Extraction(pages, "ocr", len(pages), len(pages), 0,
                      ocr_units=[(p, r.conf) for p, r in zip(pages, res)])


# ------------------------------------------------------------- Gömülü görseller

# Logo/ikon gibi küçük görseller elenir: görüntülenen alan ve piksel kısa kenarı.
MIN_IMG_CM2 = 12.0       # belgede gösterildiği boyut (ör. 4 x 3 cm)
MIN_IMG_PX = 150         # kısa kenar, piksel
MAX_IMAGES = 40          # belge başına en çok OCR'lanan görsel
# Görsel OCR'ının kalitesi bunun altındaysa metni belgeye eklenmez (fotoğraf çöpü);
# sayılır ve belge kalite işaretinde kullanılır.
IMG_DROP_Q = 0.35
# Bundan az harf/rakam veren görsel (logo kırıntısı: "G GE İK") metne eklenmez.
MIN_IMG_ALNUM = 15
EMU_PER_CM = 360000

_UNITS_CM = {"cm": 1.0, "mm": 0.1, "in": 2.54, "pt": 2.54 / 72, "pc": 2.54 / 6, "px": 2.54 / 96}


def _len_cm(v: str | None) -> float | None:
    m = re.fullmatch(r"\s*([\d.]+)\s*([a-z]*)\s*", v or "")
    if not m:
        return None
    try:
        return float(m.group(1)) * _UNITS_CM.get(m.group(2) or "pt", 0) or None
    except ValueError:
        return None


@dataclass
class _Img:
    label: str                 # nereden geldiği (paket içi yol)
    data: bytes
    area_cm2: float | None     # belgede görüntülenen alan; bilinmiyorsa None


def unit_quality(text: str, conf: float | None) -> float:
    """OCR parçası kalitesi 0-1: tesseract güveni x metin sağlığı."""
    h = ocr.text_health(text)
    if conf is None or h is None:
        return 0.0
    return round(conf / 100 * h, 3)


def _ocr_images(imgs: list[_Img], use_ocr: bool, res: Extraction) -> list[tuple[str, str]]:
    """Uygun görselleri OCR'la; (etiket, metin) listesi döndür, sayaçları `res`e yaz."""
    from PIL import Image, ImageOps

    seen: set[bytes] = set()
    cand: list[_Img] = []
    for im in imgs:
        if im.area_cm2 is not None and im.area_cm2 < MIN_IMG_CM2:
            continue
        key = im.data[:4096] + len(im.data).to_bytes(8, "big")
        if key in seen:
            continue
        seen.add(key)
        cand.append(im)
    if not cand:
        return []
    can = use_ocr and ocr.ocr_available()
    out: list[tuple[str, str] | None] = []
    with tempfile.TemporaryDirectory(prefix="bidr-emb-") as td:
        files: list[tuple[_Img, Path]] = []
        for k, im in enumerate(cand):
            try:
                with Image.open(io.BytesIO(im.data)) as pil:
                    if min(pil.size) < MIN_IMG_PX:
                        continue
                    fr = ImageOps.exif_transpose(pil.copy()).convert("L")
            except Exception:  # EMF/WMF/SVG gibi raster olmayanlar
                continue
            f = Path(td) / f"i{k}.png"
            fr.save(f)
            files.append((im, f))
        if len(files) > MAX_IMAGES:
            res.notes.append(f"gömülü görsel sınırı: {len(files)} görselden {MAX_IMAGES} OCR'landı")
            files = files[:MAX_IMAGES]
        if not files:
            return []
        if not can:
            res.ocr_missing += len(files)
            return []
        with ThreadPoolExecutor(max_workers=PDF_PAGE_WORKERS) as pool:
            results = list(pool.map(lambda x: ocr.ocr_image_q(x[1]), files))
    for (im, _), r in zip(files, results):
        t = _clean(r.text)
        if _alnum(t) < MIN_IMG_ALNUM:
            continue
        if unit_quality(t, r.conf) < IMG_DROP_Q:
            res.images_lowq += 1
            res.ocr_dropped.append((t, r.conf))
            continue
        res.images_ocr += 1
        res.ocr_units.append((t, r.conf))
        out.append((im.label, t))
    return [o for o in out if o]


def _image_sections(pairs: list[tuple[str, str]]) -> str:
    return "\n\n".join(f"[gömülü görsel: {lab}]\n{t}" for lab, t in pairs)


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


_WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_V = "{urn:schemas-microsoft-com:vml}"
_PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _rels(z: zipfile.ZipFile, part: str) -> dict[str, str]:
    """Bir paket parçasının ilişkileri: Id -> paket içi yol (dış bağlantılar hariç)."""
    d, f = posixpath.split(part)
    rp = posixpath.join(d, "_rels", f + ".rels")
    if rp not in z.namelist():
        return {}
    out = {}
    for rel in ET.fromstring(z.read(rp)).iter(_PR + "Relationship"):
        if rel.get("TargetMode") == "External":
            continue
        tgt = rel.get("Target") or ""
        out[rel.get("Id")] = (tgt.lstrip("/") if tgt.startswith("/")
                              else posixpath.normpath(posixpath.join(d, tgt)))
    return out


def _docx_images(z: zipfile.ZipFile, part: str = "word/document.xml") -> list[_Img]:
    """Gövdede (üst/altbilgi değil: logolar orada) belge sırasıyla geçen görseller."""
    rels = _rels(z, part)
    root = ET.fromstring(z.read(part))
    names = set(z.namelist())
    found: list[tuple[str, float | None]] = []
    for el in root.iter():
        if el.tag == W + "drawing":
            ext = next(el.iter(_WP + "extent"), None)
            area = None
            if ext is not None:
                try:
                    area = int(ext.get("cx")) * int(ext.get("cy")) / EMU_PER_CM ** 2
                except (TypeError, ValueError):
                    area = None
            for b in el.iter(_A + "blip"):
                rid = b.get(_R + "embed")
                if rid in rels:
                    found.append((rels[rid], area))
        elif el.tag == _V + "shape":
            style = dict(kv.split(":", 1) for kv in (el.get("style") or "").split(";") if ":" in kv)
            w, h = _len_cm(style.get("width")), _len_cm(style.get("height"))
            area = w * h if w and h else None
            for idata in el.iter(_V + "imagedata"):
                rid = idata.get(_R + "id")
                if rid in rels:
                    found.append((rels[rid], area))
    out: list[_Img] = []
    done: set[str] = set()
    for tgt, area in found:
        if tgt in done or tgt not in names:
            continue
        done.add(tgt)
        out.append(_Img(tgt, z.read(tgt), area))
    return out


def extract_docx(path: Path, use_ocr: bool = True) -> Extraction:
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if "word/document.xml" not in names:
            raise RuntimeError("word/document.xml yok")
        heads = sorted((n for n in names if re.fullmatch(r"word/header\d*\.xml", n)), key=_part_sort_key)
        foots = sorted((n for n in names if re.fullmatch(r"word/footer\d*\.xml", n)), key=_part_sort_key)
        notes = [n for n in ("word/footnotes.xml", "word/endnotes.xml") if n in names]

        def uniq(parts: list[str]) -> list[str]:
            seen, acc = set(), []
            for n in parts:
                t = _docx_part(z, n)
                if t.strip() and t not in seen:
                    seen.add(t)
                    acc.append(t)
            return acc

        sections: list[str] = []
        h = uniq(heads)
        if h:
            sections.append("[üstbilgi]\n" + "\n".join(h))
        sections.append(_docx_part(z, "word/document.xml"))
        res = Extraction([], "docx-xml")
        pairs = _ocr_images(_docx_images(z), use_ocr, res)
        if pairs:
            sections.append(_image_sections(pairs))
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
    res.pages = ["\n\n".join(s for s in sections if s.strip())]
    res.page_count = pages
    if res.images_ocr:
        res.method += f"+img-ocr({res.images_ocr})"
    return res


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


def _odt_images(path: Path) -> list[_Img]:
    """content.xml'deki çerçeveli görseller (svg:width/height ile), belge sırasıyla."""
    draw = "{urn:oasis:names:tc:opendocument:xmlns:drawing:1.0}"
    svg = "{urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0}"
    xl = "{http://www.w3.org/1999/xlink}"
    out: list[_Img] = []
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            root = ET.fromstring(z.read("content.xml"))
            done: set[str] = set()
            for fr in root.iter(draw + "frame"):
                w, h = _len_cm(fr.get(svg + "width")), _len_cm(fr.get(svg + "height"))
                for im in fr.iter(draw + "image"):
                    href = (im.get(xl + "href") or "").lstrip("./")
                    if href in names and href not in done:
                        done.add(href)
                        out.append(_Img(href, z.read(href), w * h if w and h else None))
    except (zipfile.BadZipFile, KeyError, ET.ParseError):
        return []
    return out


def extract_textutil(path: Path, use_ocr: bool = True) -> Extraction:
    body = _clean(_textutil(path))
    if path.suffix.lower() == ".odt":
        h, f = _odt_header_footer(path)
        res = Extraction([], "textutil+odt-styles")
        pairs = _ocr_images(_odt_images(path), use_ocr, res)
        imgs = [_image_sections(pairs)] if pairs else []
        parts = ([f"[üstbilgi]\n{h}"] if h else []) + [body] + imgs + ([f"[altbilgi]\n{f}"] if f else [])
        res.pages = ["\n\n".join(p for p in parts if p)]
        if res.images_ocr:
            res.method += f"+img-ocr({res.images_ocr})"
        return res
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

    def pictures(shapes, k: int) -> list[_Img]:
        out: list[_Img] = []
        for sh in shapes:
            if hasattr(sh, "shapes"):
                out.extend(pictures(sh.shapes, k))
                continue
            try:
                img = sh.image  # yalnız resim şekillerinde var
            except Exception:
                continue
            try:
                area = int(sh.width) * int(sh.height) / EMU_PER_CM ** 2
            except (TypeError, ValueError):
                area = None
            out.append(_Img(f"slayt {k}: {img.filename or 'görsel'}", img.blob, area))
        return out

    res = Extraction([], "python-pptx")
    pages = []
    for k, slide in enumerate(prs.slides, 1):
        lines: list[str] = []
        for sh in slide.shapes:
            lines.extend(shape_lines(sh))
        if slide.has_notes_slide:
            nt = slide.notes_slide.notes_text_frame.text if slide.notes_slide.notes_text_frame else ""
            if nt.strip():
                lines.append("[not]\n" + nt)
        pairs = _ocr_images(pictures(slide.shapes, k), use_ocr, res)
        if pairs:
            lines.append(_image_sections(pairs))
        pages.append(_clean("\n".join(lines)))
    res.pages, res.page_count = pages, len(pages)
    if res.images_ocr:
        res.method += f"+img-ocr({res.images_ocr})"
    return res


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


# ------------------------------------------------------------------- Kalite

# Belge düzeyi: OCR'a dayanan belgenin kalitesi bunun altındaysa "düşük kalite"
# işaretlenir (sonraki aşama görsel modele yollar).
LOW_QUALITY = 0.5
# OCR'dan bu kadardan az harf/rakam geldiyse (ör. fotoğraftan birkaç çöp karakter)
# kalite ne olursa olsun düşük sayılır.
LOW_OCR_ALNUM = 40


def assess(res: Extraction) -> dict:
    """OCR kalite ölçüsü: `ocr_conf` (0-100), `quality` (0-1), `low_quality` (bool).

    Yalnız OCR'lanan parçalar ölçülür (metne giren + düşük kaliteden atılan gömülü
    görseller). OCR'sız belgede alanlar boştur. Düşük kalite işareti, belge metni
    OCR'a dayandığında (OCR payı >= yarı ya da belge metni kısa) konur.
    """
    units = [(t, c, True) for t, c in res.ocr_units] + [(t, c, False) for t, c in res.ocr_dropped]
    if not units:
        return {"ocr_conf": "", "quality": "", "low_quality": False}
    wsum = qsum = csum = cw = 0.0
    used_alnum = 0
    for t, c, used in units:
        a = _alnum(t)
        if used:
            used_alnum += a
        w = max(a, 20)  # boş/çok kısa parça da ağırlık taşısın
        wsum += w
        qsum += w * unit_quality(t, c)
        if c is not None:
            csum += w * c
            cw += w
    quality = qsum / wsum if wsum else 0.0
    conf = csum / cw if cw else None
    total = _alnum(res.text)
    depends = used_alnum * 2 >= total or total < 200
    low = depends and (quality < LOW_QUALITY or used_alnum < LOW_OCR_ALNUM)
    return {
        "ocr_conf": "" if conf is None else round(conf, 1),
        "quality": round(quality, 2),
        "low_quality": low,
    }


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
