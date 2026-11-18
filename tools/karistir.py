#!/usr/bin/env python3
"""Belge havuzunu tohumla tekrarlanabilir biçimde "dağınık bölüm klasörü"ne dönüştürür.

Amaç: bidr'ın kanıtı dosya adından değil içerikten bulabildiğini sınamak. Girdi havuzu salt
okunur; çıktı `--out` klasörüne, gizli eşleme ise çıktı klasörünün DIŞINDAKİ `--esleme`
dosyasına yazılır. Ayrıntı: tools/README-karistir.md.

Kullanım:
    python tools/karistir.py HAVUZ --manifest HAVUZ/manifest-gizli.csv \
        --out /yol/dagınık --esleme /yol/esleme.json --tohum 42
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

MAPPING_VERSION = 1
FIXED_ZIP_TIME = (2019, 3, 14, 9, 26, 0)
FIXED_PDF_TIME = time.gmtime(0)

DEFAULT_RATES = {
    "tarama": 0.07,      # PDF/görsel → taranmış kopya (istisna: dosyaların ~%5–8'i)
    "donustur": 0.70,    # HTML → PDF/metin, DOCX → PDF
    "birlestir": 0.20,   # küçük PDF'leri tek PDF'te birleştir
    "parcala": 0.35,     # uzun PDF'i parçala
    "kopya": 0.10,       # birebir kopya, farklı adla
    "zip": 0.15,         # çıktıyı zip arşivine koy
    "bozuk": 0.03,       # kaynağın kesik (bozuk) kopyası
    "cop": 0.05,         # alakasız/boş dosya oranı (en az 2)
    "kok": 0.08,         # dosyanın kök klasörde kalma olasılığı
}

PDF_EXT = {".pdf"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp"}
HTML_EXT = {".html", ".htm", ".xhtml"}
DOCX_EXT = {".docx", ".doc", ".odt", ".rtf"}

SMALL_PDF_PAGES = 3
LONG_PDF_PAGES = 6
MAX_SCAN_PAGES = 12

FILE_PATTERNS = [
    "scan_{n4}", "Scan_{n4}", "IMG_{n4}", "belge son son", "belge son", "belge", "Adsız",
    "Adsız {n1}", "Untitled", "Untitled ({n1})", "Yeni Belge", "Yeni Belge ({n1})",
    "document ({n1})", "doc{n5}", "Taranmış_{n3}", "final_v{n1}", "final son", "son hali",
    "Kopya - Adsız", "yeni", "dosya{n2}", "{date}", "Scan {date}", "ek{n1}", "EK-{n1}",
    "çıktı", "imza", "tarama{n2}", "evrak{n3}", "gonder", "duzeltilmis", "taslak {n1}",
    "New Document", "file_{n4}", "print_{n3}",
]
IMAGE_PATTERNS = [
    "IMG_{n4}", "IMG-{date8}-WA{n4}", "WhatsApp Image {date} at {hh}.{mm}.{ss}",
    "Screenshot {date} at {hh}.{mm}.{ss}", "Ekran Resmi {date} {hh}.{mm}.{ss}", "DSC{n5}",
    "photo_{n4}", "scan_{n4}", "image{n2}",
]
FOLDER_PATTERNS = [
    "Yeni Klasör", "Yeni Klasör ({n1})", "New folder", "New Folder ({n1})", "eski", "arşiv",
    "Arsiv_{year}", "misc", "Masaüstü", "Desktop", "Downloads", "İndirilenler", "yedek",
    "backup", "old", "temp", "son", "son hali", "taranan", "scans", "Belgeler", "Documents",
    "toplantı", "gönderilecek", "to sort", "düzenlenecek", "{year}", "{year} dosyalar", "ekler",
    "attachments", "kopya", "evrak", "dosyalar", "bakılacak", "misc stuff", "_eski_",
]
JUNK_KINDS = ["bos", "tmp", "kilit", "rastgele", "ds_store", "thumbs"]


# --------------------------------------------------------------------------- yardımcılar

def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fold(s: str) -> str:
    """Büyük/küçük harf ve aksan duyarsız karşılaştırma biçimi."""
    s = s.replace("İ", "i").replace("I", "ı").lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.replace("ı", "i")


def forbidden_tokens(rows: list[dict]) -> set[str]:
    """Çıktı adlarında geçmemesi gereken parçalar: kaynak adları ve id'ler."""
    out: set[str] = set()
    for r in rows:
        rid = (r.get("id") or "").strip()
        if len(rid) >= 3:
            out.add(fold(rid))
        p = Path(r.get("yol") or "")
        for part in (p.name, p.stem):
            if len(part) >= 4:
                out.add(fold(part))
    return out


def name_is_clean(name: str, forbidden: set[str]) -> bool:
    f = fold(name)
    return not any(tok in f for tok in forbidden)


@dataclass
class Tools:
    pdftoppm: str | None = None
    fitz: object | None = None
    soffice: str | None = None
    chrome: str | None = None

    def summary(self) -> dict:
        return {"pdftoppm": bool(self.pdftoppm), "pymupdf": self.fitz is not None,
                "soffice": bool(self.soffice), "chrome": bool(self.chrome)}


def find_tools(disabled: set[str]) -> Tools:
    t = Tools()
    if "pdftoppm" not in disabled:
        t.pdftoppm = shutil.which("pdftoppm")
    if "pymupdf" not in disabled:
        try:
            import fitz  # type: ignore
            t.fitz = fitz
        except Exception:
            t.fitz = None
    if "soffice" not in disabled:
        t.soffice = shutil.which("soffice") or shutil.which("libreoffice")
        mac = "/Applications/LibreOffice.app/Contents/MacOS/soffice"
        if not t.soffice and os.path.exists(mac):
            t.soffice = mac
    if "chrome" not in disabled:
        for c in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
            if shutil.which(c):
                t.chrome = shutil.which(c)
                break
        mac = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        if not t.chrome and os.path.exists(mac):
            t.chrome = mac
    return t


# --------------------------------------------------------------------------- PDF/görsel

def pdf_page_count(p: Path) -> int | None:
    try:
        from pypdf import PdfReader
        r = PdfReader(str(p))
        if r.is_encrypted:
            return None
        return len(r.pages)
    except Exception:
        return None


def normalize_pdf(src: Path, dst: Path, pages: range | None = None) -> None:
    """PDF'i pypdf ile sabit üst veriyle yeniden yazar (tekrarlanabilir bayt)."""
    from pypdf import PdfReader, PdfWriter
    w = PdfWriter()
    r = PdfReader(str(src))
    if pages is None:
        w.append(r)
    else:
        w.append(r, pages=(pages.start, pages.stop))
    w.add_metadata({"/Producer": "pdf"})
    with open(dst, "wb") as f:
        w.write(f)


def merge_pdfs(srcs: list[Path], dst: Path) -> None:
    from pypdf import PdfReader, PdfWriter
    w = PdfWriter()
    for s in srcs:
        w.append(PdfReader(str(s)))
    w.add_metadata({"/Producer": "pdf"})
    with open(dst, "wb") as f:
        w.write(f)


def render_pdf_pages(src: Path, tools: Tools, work: Path, max_pages: int):
    """PDF sayfalarını gri ton görsele çevirir. (görseller, kullanılan araç) ya da (None, neden)."""
    from PIL import Image
    if tools.pdftoppm:
        prefix = work / "sayfa"
        try:
            subprocess.run([tools.pdftoppm, "-r", "90", "-gray", "-png", "-f", "1", "-l",
                            str(max_pages), str(src), str(prefix)],
                           check=True, capture_output=True, timeout=300)
            files = sorted(work.glob("sayfa*.png"))
            if files:
                imgs = []
                for f in files:
                    with Image.open(f) as im:
                        imgs.append(im.convert("L"))
                return imgs, "pdftoppm"
        except Exception as e:  # araç hatası: düşüş yoluna geç
            err = f"pdftoppm: {type(e).__name__}"
        else:
            err = "pdftoppm: çıktı yok"
    else:
        err = "pdftoppm yok"
    if tools.fitz is not None:
        try:
            doc = tools.fitz.open(str(src))
            imgs = []
            for i, page in enumerate(doc):
                if i >= max_pages:
                    break
                pix = page.get_pixmap(dpi=90, colorspace=tools.fitz.csGRAY)
                imgs.append(Image.frombytes("L", (pix.width, pix.height), pix.samples))
            if imgs:
                return imgs, "pymupdf"
        except Exception as e:
            err += f"; pymupdf: {type(e).__name__}"
    else:
        err += "; pymupdf yok"
    return None, err


def degrade(img, rng: random.Random):
    """Hafif döndürme + gürültü + gri ton: 'taranmış' görünüm."""
    from PIL import Image
    img = img.convert("L")
    max_side = 1400
    if max(img.size) > max_side:
        k = max_side / max(img.size)
        img = img.resize((max(1, int(img.width * k)), max(1, int(img.height * k))))
    angle = rng.uniform(-2.5, 2.5)
    img = img.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=235)
    noise = Image.frombytes("L", img.size, rng.randbytes(img.width * img.height))
    img = Image.blend(img, noise, rng.uniform(0.04, 0.10))
    return img, round(angle, 2)


def save_image(img, dst: Path, fmt: str) -> None:
    if fmt == "jpg":
        img.save(dst, "JPEG", quality=72)
    elif fmt == "png":
        img.save(dst, "PNG")
    else:
        raise ValueError(fmt)


def save_image_pdf(imgs, dst: Path) -> None:
    first, rest = imgs[0], imgs[1:]
    first.save(dst, "PDF", resolution=90.0, save_all=True, append_images=rest,
               creationDate=FIXED_PDF_TIME, modDate=FIXED_PDF_TIME, producer="scan")


# --------------------------------------------------------------------------- HTML/DOCX

class _TextExtractor(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section",
             "article", "table", "ul", "ol", "header", "footer"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self._skip:
            self._skip -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(raw: bytes) -> str:
    m = re.search(rb'charset=["\']?([A-Za-z0-9_\-]+)', raw[:4096])
    enc = m.group(1).decode("ascii", "ignore") if m else "utf-8"
    try:
        s = raw.decode(enc, errors="replace")
    except LookupError:
        s = raw.decode("utf-8", errors="replace")
    p = _TextExtractor()
    p.feed(s)
    text = html.unescape("".join(p.parts))
    lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in text.splitlines()]
    out, blank = [], False
    for ln in lines:
        if ln:
            out.append(ln)
            blank = False
        elif not blank and out:
            out.append("")
            blank = True
    return "\n".join(out).strip() + "\n"


def soffice_to_pdf(src: Path, work: Path, tools: Tools) -> Path | None:
    if not tools.soffice:
        return None
    outdir = work / "so"
    outdir.mkdir(exist_ok=True)
    profile = work / "so-profil"
    try:
        subprocess.run([tools.soffice, f"-env:UserInstallation=file://{profile}", "--headless",
                        "--convert-to", "pdf", "--outdir", str(outdir), str(src)],
                       check=True, capture_output=True, timeout=300)
    except Exception:
        return None
    pdfs = list(outdir.glob("*.pdf"))
    return pdfs[0] if pdfs else None


def chrome_to_pdf(src: Path, work: Path, tools: Tools) -> Path | None:
    if not tools.chrome:
        return None
    # Kopyayı yalnız başına bir klasöre al; ağ erişimini kapat.
    iso = work / "html"
    iso.mkdir(exist_ok=True)
    local = iso / ("sayfa" + src.suffix.lower())
    shutil.copyfile(src, local)
    out = work / "chrome.pdf"
    try:
        subprocess.run([tools.chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                        "--no-first-run", "--disable-extensions", "--disable-background-networking",
                        "--host-resolver-rules=MAP * ~NOTFOUND",
                        f"--user-data-dir={work / 'chrome-profil'}", f"--print-to-pdf={out}",
                        local.as_uri()], check=True, capture_output=True, timeout=120)
    except Exception:
        return None
    return out if out.exists() and out.stat().st_size > 0 else None


# --------------------------------------------------------------------------- planlama

@dataclass
class Item:
    """Çıktıya yerleşecek bir dosya (staging'de ya da kaynakta duran)."""
    path: Path
    ext: str
    kaynak: list[dict]
    bozmalar: list[str]
    image: bool = False
    out_path: str = ""
    sha256: str = ""
    zipped: bool = False


@dataclass
class Namer:
    rng: random.Random
    forbidden: set[str]
    used: set[str] = field(default_factory=set)

    def _fill(self, pat: str) -> str:
        r = self.rng
        y = r.randint(2016, 2024)
        mo, d = r.randint(1, 12), r.randint(1, 28)
        return pat.format(
            n1=r.randint(1, 9), n2=r.randint(1, 99), n3=f"{r.randint(0, 999):03d}",
            n4=f"{r.randint(0, 9999):04d}", n5=f"{r.randint(0, 99999):05d}",
            year=y, date=f"{y}-{mo:02d}-{d:02d}", date8=f"{y}{mo:02d}{d:02d}",
            hh=f"{r.randint(8, 23):02d}", mm=f"{r.randint(0, 59):02d}", ss=f"{r.randint(0, 59):02d}")

    def folder_name(self) -> str:
        for _ in range(50):
            n = self._fill(self.rng.choice(FOLDER_PATTERNS))
            if name_is_clean(n, self.forbidden):
                return n
        return f"klasor{self.rng.randint(0, 99999):05d}"

    def file_name(self, folder: str, ext: str, image: bool) -> str:
        pats = IMAGE_PATTERNS if image and self.rng.random() < 0.7 else FILE_PATTERNS
        for attempt in range(80):
            stem = self._fill(self.rng.choice(pats))
            if attempt > 20:
                stem += f" ({attempt - 19})"
            name = stem + ext
            rel = f"{folder}/{name}" if folder else name
            if name_is_clean(name, self.forbidden) and rel.lower() not in self.used:
                self.used.add(rel.lower())
                return rel
        rel = f"{folder}/x{self.rng.randint(0, 10**9)}{ext}" if folder else f"x{self.rng.randint(0, 10**9)}{ext}"
        self.used.add(rel.lower())
        return rel


def make_folder_pool(rng: random.Random, namer: Namer, n_items: int) -> list[str]:
    target = max(3, min(60, n_items // 3 + 2))
    pool: list[str] = []
    for _ in range(target):
        parents = [p for p in pool if p.count("/") < 3]
        if parents and rng.random() < 0.55:
            base = rng.choice(parents)
            path = f"{base}/{namer.folder_name()}"
        else:
            path = namer.folder_name()
        if path.lower() not in {p.lower() for p in pool}:
            pool.append(path)
    return pool


def pick_folder(rng: random.Random, pool: list[str], rates: dict) -> str:
    if rng.random() < rates["kok"]:
        return ""
    return rng.choice(pool)


def ext_of(row: dict, src: Path) -> str:
    e = src.suffix.lower()
    if e:
        return e
    b = (row.get("bicim") or "").strip().lower().lstrip(".")
    return f".{b}" if b else ""


def scramble(havuz: Path, manifest: Path, out: Path, esleme: Path, tohum: int,
             rates: dict | None = None, disabled_tools: set[str] | None = None,
             quiet: bool = False) -> dict:
    havuz, out, esleme, manifest = (Path(havuz).resolve(), Path(out).resolve(),
                                    Path(esleme).resolve(), Path(manifest).resolve())
    rates = {**DEFAULT_RATES, **(rates or {})}
    if esleme == out or out in esleme.parents:
        raise SystemExit("hata: --esleme çıktı klasörünün dışında olmalı")
    if out == havuz or havuz in out.parents or out in havuz.parents:
        raise SystemExit("hata: --out havuzla iç içe olamaz (havuz salt okunur)")
    if havuz in esleme.parents:
        raise SystemExit("hata: --esleme havuzun içine yazılamaz (havuz salt okunur)")
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"hata: çıktı klasörü boş değil: {out}")

    with open(manifest, encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f) if (r.get("id") or "").strip()]
    rows.sort(key=lambda r: r["id"])

    rng = random.Random(tohum)
    tools = find_tools(disabled_tools or set())
    forbidden = forbidden_tokens(rows)
    forbidden |= {fold(manifest.stem), fold(esleme.stem)}
    namer = Namer(rng, forbidden)
    atlananlar: list[dict] = []
    uyarilar: list[dict] = []
    items: list[Item] = []
    merge_pool: list[tuple[dict, Path, int]] = []

    stage_dir = Path(tempfile.mkdtemp(prefix="karistir-"))
    counter = [0]

    def stage(ext: str) -> Path:
        counter[0] += 1
        return stage_dir / f"{counter[0]:06d}{ext}"

    def work() -> Path:
        counter[0] += 1
        d = stage_dir / f"is{counter[0]:06d}"
        d.mkdir()
        return d

    def skip(rid: str, bozma: str, neden: str) -> None:
        atlananlar.append({"id": rid, "bozma": bozma, "neden": neden})

    def scan(rid: str, src: Path, is_pdf: bool, kaynak: list[dict]) -> bool:
        from PIL import Image
        if is_pdf:
            imgs, info = render_pdf_pages(src, tools, work(), MAX_SCAN_PAGES)
            if imgs is None:
                skip(rid, "tarama", f"araç yok/başarısız: {info}")
                return False
            total = pdf_page_count(src) or len(imgs)
        else:
            try:
                with Image.open(src) as im:
                    imgs = [im.convert("L")]
                info, total = "pillow", 1
            except Exception as e:
                skip(rid, "tarama", f"görsel açılamadı: {type(e).__name__}")
                return False
        out_imgs, angles = [], []
        for im in imgs:
            d, a = degrade(im, rng)
            out_imgs.append(d)
            angles.append(a)
        tags = ["tarama", "gri_ton", "gurultu", f"dondurme:{','.join(map(str, angles))}",
                f"tarayici:{info}", "metin_katmani_yok"]
        if total > len(imgs):
            tags.append(f"ilk_{len(imgs)}_sayfa/{total}")
        if len(out_imgs) == 1 and rng.random() < 0.6:
            fmt = rng.choice(["png", "jpg"])
            p = stage("." + fmt)
            save_image(out_imgs[0], p, fmt)
            items.append(Item(p, "." + fmt, kaynak, tags + [f"bicim:{fmt}"], image=True))
        else:
            p = stage(".pdf")
            save_image_pdf(out_imgs, p)
            items.append(Item(p, ".pdf", kaynak, tags + ["bicim:gorsel_pdf"]))
        return True

    for row in rows:
        rid = row["id"].strip()
        src = havuz / (row.get("yol") or "")
        if not src.is_file():
            uyarilar.append({"id": rid, "uyari": "kaynak dosya yok"})
            continue
        want = (row.get("sha256") or "").strip().lower()
        if want and sha256_file(src) != want:
            uyarilar.append({"id": rid, "uyari": "sha256 manifestle uyuşmuyor"})
        ext = ext_of(row, src)
        kaynak = [{"id": rid}]

        # birebir kopya (ana çıktıya ek olarak)
        if rng.random() < rates["kopya"]:
            items.append(Item(src, ext, [{"id": rid}], ["birebir_kopya", "ad_degisti"],
                              image=ext in IMAGE_EXT))
        # kesik/bozuk kopya (ana çıktıya ek olarak)
        if rng.random() < rates["bozuk"]:
            data = src.read_bytes()
            p = stage(ext)
            p.write_bytes(data[: max(1, len(data) // rng.randint(3, 8))])
            items.append(Item(p, ext, [{"id": rid}], ["bozuk:kesik", "ad_degisti"]))

        if ext in PDF_EXT:
            pages = pdf_page_count(src)
            if pages is None:
                items.append(Item(src, ext, kaynak, ["orijinal", "ad_degisti"]))
                continue
            if pages >= LONG_PDF_PAGES and rng.random() < rates["parcala"]:
                n = rng.randint(2, min(3, pages))
                cuts = sorted(rng.sample(range(1, pages), n - 1))
                bounds = [0] + cuts + [pages]
                try:
                    for i in range(n):
                        a, b = bounds[i], bounds[i + 1]
                        p = stage(".pdf")
                        normalize_pdf(src, p, range(a, b))
                        items.append(Item(p, ".pdf", [{"id": rid, "sayfalar": f"{a + 1}-{b}"}],
                                          [f"parca:{i + 1}/{n}", "ad_degisti"]))
                    continue
                except Exception as e:
                    skip(rid, "parcala", f"pypdf hatası: {type(e).__name__}")
            if rng.random() < rates["tarama"]:
                if scan(rid, src, True, kaynak):
                    continue
            if pages <= SMALL_PDF_PAGES and rng.random() < rates["birlestir"]:
                merge_pool.append((row, src, pages))
                continue
            items.append(Item(src, ext, kaynak, ["orijinal", "ad_degisti"]))

        elif ext in IMAGE_EXT:
            if rng.random() < rates["tarama"] and scan(rid, src, False, kaynak):
                continue
            items.append(Item(src, ext, kaynak, ["orijinal", "ad_degisti"], image=True))

        elif ext in HTML_EXT:
            if rng.random() < rates["donustur"]:
                if rng.random() < 0.6:
                    w = work()
                    pdf, used = soffice_to_pdf(src, w, tools), "soffice"
                    if pdf is None:
                        pdf, used = chrome_to_pdf(src, w, tools), "chrome"
                    if pdf is not None:
                        p = stage(".pdf")
                        try:
                            normalize_pdf(pdf, p)
                            items.append(Item(p, ".pdf", kaynak, ["html_pdf", f"arac:{used}",
                                                                   "ad_degisti"]))
                            continue
                        except Exception as e:
                            skip(rid, "html_pdf", f"pdf okunamadı: {type(e).__name__}")
                    else:
                        skip(rid, "html_pdf", "araç yok (soffice/chrome) ya da başarısız; "
                                              "düz metne düşüldü")
                p = stage(".txt")
                p.write_text(html_to_text(src.read_bytes()), encoding="utf-8")
                items.append(Item(p, ".txt", kaynak, ["html_metin", "ad_degisti"]))
                continue
            items.append(Item(src, ext, kaynak, ["orijinal", "ad_degisti"]))

        elif ext in DOCX_EXT:
            if rng.random() < rates["donustur"]:
                w = work()
                pdf = soffice_to_pdf(src, w, tools)
                if pdf is not None:
                    p = stage(".pdf")
                    try:
                        normalize_pdf(pdf, p)
                        items.append(Item(p, ".pdf", kaynak, ["docx_pdf", "arac:soffice",
                                                               "ad_degisti"]))
                        continue
                    except Exception as e:
                        skip(rid, "docx_pdf", f"pdf okunamadı: {type(e).__name__}")
                else:
                    skip(rid, "docx_pdf", "soffice yok ya da başarısız; orijinal bırakıldı")
            items.append(Item(src, ext, kaynak, ["orijinal", "ad_degisti"]))

        else:
            items.append(Item(src, ext, kaynak, ["orijinal", "ad_degisti"]))

    # küçük PDF'leri 2–4'lük gruplarla birleştir
    sizes, left = [], len(merge_pool)
    while left > 0:
        k = min(rng.randint(2, 4), left)
        sizes.append(k)
        left -= k
    if len(sizes) > 1 and sizes[-1] == 1:  # tek kalan önceki gruba katılır
        last = sizes.pop()
        sizes[-1] += last
    i = 0
    for k in sizes:
        group = merge_pool[i:i + k]
        i += k
        if len(group) < 2:
            row, src, _ = group[0]
            items.append(Item(src, ".pdf", [{"id": row["id"].strip()}], ["orijinal", "ad_degisti"]))
            continue
        p = stage(".pdf")
        kaynak, start = [], 1
        for row, _, pg in group:
            kaynak.append({"id": row["id"].strip(), "sayfalar": f"{start}-{start + pg - 1}"})
            start += pg
        try:
            merge_pdfs([g[1] for g in group], p)
            items.append(Item(p, ".pdf", kaynak, [f"birlestirme:{len(group)}", "ad_degisti"]))
        except Exception as e:
            for row, src, _ in group:
                skip(row["id"].strip(), "birlestir", f"pypdf hatası: {type(e).__name__}")
                items.append(Item(src, ".pdf", [{"id": row["id"].strip()}],
                                  ["orijinal", "ad_degisti"]))

    # alakasız/boş dosyalar
    n_junk = max(4, round(rates["cop"] * len(rows)))
    for j in range(n_junk):
        kind = JUNK_KINDS[j] if j < len(JUNK_KINDS) else rng.choice(JUNK_KINDS)
        if kind == "bos":
            e = rng.choice([".pdf", ".docx", ".jpg", ".txt"])
            p = stage(e)
            p.write_bytes(b"")
            items.append(Item(p, e, [], ["cop:bos_dosya"]))
        elif kind == "tmp":
            p = stage(".tmp")
            p.write_bytes(rng.randbytes(rng.randint(64, 2048)))
            items.append(Item(p, ".tmp", [], ["cop:tmp"]))
        elif kind == "kilit":
            p = stage(".docx")
            p.write_bytes(b"\x0bkullanici" + b"\x00" * 40 + rng.randbytes(110))
            items.append(Item(p, ".docx", [], ["cop:office_kilit"]))
        elif kind == "ds_store":
            p = stage("")
            p.write_bytes(b"\x00\x00\x00\x01Bud1" + rng.randbytes(256))
            items.append(Item(p, "", [], ["cop:ds_store"]))
        elif kind == "thumbs":
            p = stage(".db")
            p.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + rng.randbytes(512))
            items.append(Item(p, ".db", [], ["cop:thumbs_db"]))
        else:
            e = rng.choice([".pdf", ".bin", ".dat"])
            p = stage(e)
            head = b"%PDF-1.4\n" if e == ".pdf" else b""
            p.write_bytes(head + rng.randbytes(rng.randint(100, 4000)))
            items.append(Item(p, e, [], ["cop:bozuk_rastgele"]))

    # yerleştir: klasör havuzu, adlar, zip'ler
    rng.shuffle(items)
    pool = make_folder_pool(rng, namer, len(items))
    out.mkdir(parents=True, exist_ok=True)
    files: list[dict] = []
    zip_candidates = [it for it in items if it.kaynak]
    zip_groups: list[list[Item]] = []
    chosen = [it for it in zip_candidates if rng.random() < rates["zip"]]
    j = 0
    while j < len(chosen):
        k = rng.randint(1, 5)
        zip_groups.append(chosen[j:j + k])
        for it in chosen[j:j + k]:
            it.zipped = True
        j += k

    def place_name(it: Item, folder: str) -> str:
        if it.bozmalar and it.bozmalar[0] == "cop:office_kilit":
            for _ in range(50):
                n = "~$" + namer._fill(rng.choice(FILE_PATTERNS))[:6] + ".docx"
                rel = f"{folder}/{n}" if folder else n
                if name_is_clean(n, forbidden) and rel.lower() not in namer.used:
                    namer.used.add(rel.lower())
                    return rel
        if it.bozmalar and it.bozmalar[0] == "cop:ds_store":
            rel = f"{folder}/.DS_Store" if folder else ".DS_Store"
            if rel.lower() not in namer.used:
                namer.used.add(rel.lower())
                return rel
        if it.bozmalar and it.bozmalar[0] == "cop:thumbs_db":
            rel = f"{folder}/Thumbs.db" if folder else "Thumbs.db"
            if rel.lower() not in namer.used:
                namer.used.add(rel.lower())
                return rel
        return namer.file_name(folder, it.ext, it.image)

    for it in items:
        if it.zipped:
            continue
        rel = place_name(it, pick_folder(rng, pool, rates))
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(it.path, dst)
        files.append({"yol": rel, "sha256": sha256_file(dst), "boyut": dst.stat().st_size,
                      "kaynak": it.kaynak, "bozmalar": it.bozmalar})

    for group in zip_groups:
        rel = namer.file_name(pick_folder(rng, pool, rates), ".zip", False)
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        inner_namer = Namer(rng, forbidden)
        nested = rng.random() < 0.5
        inner_pool = make_folder_pool(rng, inner_namer, len(group)) if nested else []
        members = []
        with zipfile.ZipFile(dst, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for it in group:
                folder = rng.choice(inner_pool) if nested and rng.random() < 0.8 else ""
                mrel = inner_namer.file_name(folder, it.ext, it.image)
                zi = zipfile.ZipInfo(mrel, date_time=FIXED_ZIP_TIME)
                zi.compress_type = zipfile.ZIP_DEFLATED
                zi.external_attr = 0o644 << 16
                zf.writestr(zi, it.path.read_bytes())
                members.append({"yol": mrel, "sha256": sha256_file(it.path),
                                "kaynak": it.kaynak, "bozmalar": it.bozmalar})
        files.append({"yol": rel, "sha256": sha256_file(dst), "boyut": dst.stat().st_size,
                      "kaynak": [k for m in members for k in m["kaynak"]],
                      "bozmalar": ["zip", "ic_ice_klasor" if nested else "duz_zip"],
                      "icerik": members})

    shutil.rmtree(stage_dir, ignore_errors=True)
    files.sort(key=lambda f: f["yol"])

    counts: dict[str, int] = {}
    for f in files:
        for b in f["bozmalar"] + [b for m in f.get("icerik", []) for b in m["bozmalar"]]:
            key = b.split(":")[0]
            counts[key] = counts.get(key, 0) + 1
    covered = {k["id"] for f in files for k in f["kaynak"]}
    mapping = {
        "surum": MAPPING_VERSION,
        "tohum": tohum,
        "oranlar": rates,
        "araclar": tools.summary(),
        "girdi_sayisi": len(rows),
        "kapsanan_kaynak": len(covered),
        "cikti_sayisi": len(files),
        "bozma_sayilari": dict(sorted(counts.items())),
        "atlananlar": atlananlar,
        "uyarilar": uyarilar,
        "dosyalar": files,
    }
    esleme.parent.mkdir(parents=True, exist_ok=True)
    esleme.write_text(json.dumps(mapping, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not quiet:
        print(f"karistir: {len(rows)} kaynak → {len(files)} çıktı dosyası ({out})")
        print("araçlar: " + ", ".join(f"{k}={'var' if v else 'yok'}"
                                      for k, v in tools.summary().items()))
        print("bozmalar: " + ", ".join(f"{k}={v}" for k, v in mapping["bozma_sayilari"].items()))
        if atlananlar:
            print(f"atlanan bozma: {len(atlananlar)} (ayrıntı eşlemede 'atlananlar')")
        if uyarilar:
            print(f"uyarı: {len(uyarilar)} (ayrıntı eşlemede 'uyarilar')")
        print(f"eşleme: {esleme}")
    return mapping


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Belge havuzunu tohumla tekrarlanabilir biçimde "
                                             "dağınık bir bölüm klasörüne dönüştürür.")
    ap.add_argument("havuz", type=Path, help="havuz kökü (salt okunur)")
    ap.add_argument("--manifest", type=Path, help="varsayılan: HAVUZ/manifest-gizli.csv")
    ap.add_argument("--out", type=Path, required=True, help="dağınık klasör (yok ya da boş)")
    ap.add_argument("--esleme", type=Path, required=True,
                    help="gizli eşleme JSON (çıktı klasörünün dışında)")
    ap.add_argument("--tohum", type=int, default=0)
    for k, v in DEFAULT_RATES.items():
        ap.add_argument(f"--{k}", type=float, default=v, help=f"oran (varsayılan {v})")
    ap.add_argument("--arac-kapat", default="",
                    help="virgüllü: pdftoppm,pymupdf,soffice,chrome (yokmuş gibi davran)")
    a = ap.parse_args(argv)
    rates = {k: getattr(a, k) for k in DEFAULT_RATES}
    for k, v in rates.items():
        if not 0.0 <= v <= 1.0:
            ap.error(f"--{k} 0 ile 1 arasında olmalı")
    disabled = {x.strip() for x in a.arac_kapat.split(",") if x.strip()}
    scramble(a.havuz, a.manifest or a.havuz / "manifest-gizli.csv", a.out, a.esleme, a.tohum,
             rates, disabled)
    return 0


if __name__ == "__main__":
    sys.exit(main())
