"""Biçime göre maskeleme (yayın kopyası) ve bağımsız yeniden tarama.

Her `mask_*(src, dst, rules)` → `{"maskelenen": Counter, "temizlenen": [...], "uyarilar": [...]}`.
`scan_file(path, rules)` maskeleyiciden bağımsız okur → `{"bulgular": Counter, "sorunlar": [...],
"imza": [...]}`; kopyanın yayımlanabilirliğine bu karar verir.

PDF: PyMuPDF (`pymupdf`/`fitz`) varsa gerçek kaldırma (redaction: içerik ve metin katmanı
silinir); yoksa pypdf ile en iyi çaba (içerik akışındaki metin işlemlerinin baytları değiştirilir;
iki baytlı/gömülü kodlamalı yazı tiplerinde ve görüntüdeki metinde işe yaramaz — yeniden tarama
yakalar). İkisinde de üst veri, XMP, ekler, yorum/açıklamalar, form alanları, yer imleri temizlenir.
"""
from __future__ import annotations

import io
import re
import zipfile
from collections import Counter
from pathlib import Path

from .detect import PLACEHOLDERS, MaskRules, detect, mask_text

PDF_EXT = {".pdf"}
DOCX_EXT = {".docx"}
XLSX_EXT = {".xlsx", ".xlsm"}
TEXT_EXT = {".txt", ".csv", ".md", ".tsv"}
SUPPORTED = PDF_EXT | DOCX_EXT | XLSX_EXT | TEXT_EXT

# Ham akış taramasında (PDF) yalnız ayırt edici türler: koordinat sayılarıyla karışmaz.
RAW_KINDS = ("tc_no", "iban", "eposta")


class MaskError(RuntimeError):
    pass


def _fold(s: str) -> str:
    return s.replace("İ", "i").replace("I", "ı").lower()


def _has_imza(s: str) -> bool:
    f = _fold(s)
    return "imza" in f or "ımza" in f


def _sub_rules(rules: MaskRules, kinds) -> MaskRules:
    return MaskRules(kinds=tuple(k for k in rules.kinds if k in kinds),
                     student_patterns=rules.student_patterns, names=rules.names)


def pdf_engine(prefer: str = "auto") -> str:
    """'pymupdf' (gerçek kaldırma) ya da 'pypdf' (en iyi çaba)."""
    if prefer == "pypdf":
        return "pypdf"
    if _fitz() is not None:
        return "pymupdf"
    if prefer == "pymupdf":
        raise MaskError("PyMuPDF kurulu değil: pip install 'bidr[maske]'")
    return "pypdf"


def _fitz():
    try:
        import pymupdf as fitz  # type: ignore
        return fitz
    except ImportError:
        try:
            import fitz  # type: ignore
            return fitz
        except ImportError:
            return None


def _quiet_pypdf() -> None:
    import logging
    logging.getLogger("pypdf").setLevel(logging.ERROR)


# ---------------------------------------------------------------- PDF (pypdf, en iyi çaba)

_POS_OPS = {b"Td", b"TD", b"Tm", b"T*"}


def _str_bytes(o) -> bytes | None:
    from pypdf.generic import ByteStringObject, TextStringObject
    if isinstance(o, TextStringObject):
        return bytes(o.original_bytes)
    if isinstance(o, ByteStringObject):
        return bytes(o)
    return None


def _mask_ops(operations, rules: MaskRules, counts: Counter) -> bool:
    """Metin işlemlerini birleştirip (Tj, TJ, ', ") tespit eder; eşleşen baytları 'X' yapar."""
    from pypdf.generic import ArrayObject, ByteStringObject, FloatObject, NumberObject
    chars: list[str] = []
    where: list[tuple | None] = []      # (işlem no, işlenen no, dizi no | None, bayt no)

    def virt(c):
        chars.append(c)
        where.append(None)

    def add(oi, ai, ei, o):
        b = _str_bytes(o)
        if b is None:
            return
        for j, x in enumerate(b):
            chars.append(chr(x))      # latin-1: bayt ↔ karakter birebir
            where.append((oi, ai, ei, j))

    for oi, (operands, op) in enumerate(operations):
        if op in (b"BT", b"ET"):
            virt("\n")
        elif op in _POS_OPS:
            virt(" ")
        elif op == b"Tj" and operands:
            add(oi, 0, None, operands[0])
        elif op == b"'" and operands:
            virt("\n")
            add(oi, 0, None, operands[0])
        elif op == b'"' and len(operands) >= 3:
            virt("\n")
            add(oi, 2, None, operands[2])
        elif op == b"TJ" and operands and isinstance(operands[0], ArrayObject):
            for ei, el in enumerate(operands[0]):
                if isinstance(el, (NumberObject, FloatObject, int, float)):
                    if float(el) <= -200:
                        virt(" ")
                else:
                    add(oi, 0, ei, el)
    text = "".join(chars)
    fs = detect(text, rules)
    if not fs:
        return False
    hits: dict[tuple, set[int]] = {}
    for f in fs:
        counts[f.kind] += 1
        for i in range(f.start, f.end):
            w = where[i]
            if w is not None and not text[i].isspace():
                hits.setdefault(w[:3], set()).add(w[3])
    for (oi, ai, ei), pos in hits.items():
        operands = operations[oi][0]
        o = operands[ai] if ei is None else operands[ai][ei]
        b = bytearray(_str_bytes(o) or b"")
        for j in pos:
            b[j] = ord("X")
        new = ByteStringObject(bytes(b))
        if ei is None:
            operands[ai] = new
        else:
            operands[ai][ei] = new
    return True


def _clean_pdf_writer(w) -> list[str]:
    """Belge düzeyi temizlik: üst veri, XMP, ekler, form, yer imleri, yapı ağacı, sayfa açıklamaları."""
    from pypdf.generic import NameObject
    done = []
    root = w.root_object
    for key, tag in (("/Metadata", "xmp"), ("/Names", "ekler_ve_adlar"), ("/AcroForm", "form"),
                     ("/OpenAction", "eylem"), ("/AA", "eylem"), ("/Outlines", "yer_imleri"),
                     ("/StructTreeRoot", "yapi_agaci"), ("/PieceInfo", "ozel_veri")):
        if NameObject(key) in root:
            del root[NameObject(key)]
            done.append(tag)
    for page in w.pages:
        for key, tag in (("/Annots", "yorum_aciklama"), ("/Metadata", "xmp"), ("/PieceInfo", "ozel_veri"),
                         ("/Thumb", "kucuk_resim"), ("/AA", "eylem")):
            if NameObject(key) in page:
                del page[NameObject(key)]
                done.append(tag)
    try:
        if w.metadata:
            done.append("ust_veri")
    except Exception:
        pass
    w.metadata = None
    return sorted(set(done))


def _rebuild(w):
    """Yalnız sayfaları (ve onların başvurduğu nesneleri) yeni bir yazıcıya taşır: silinen
    ekler, eski içerik akışları gibi sahipsiz nesneler dosyaya yazılmaz."""
    from pypdf import PdfWriter
    out = PdfWriter()
    for page in w.pages:
        out.add_page(page)
    out.metadata = None
    return out


def mask_pdf_pypdf(src: Path, dst: Path, rules: MaskRules) -> dict:
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import ContentStream
    _quiet_pypdf()
    reader = PdfReader(str(src))
    if reader.is_encrypted:
        raise MaskError("şifreli PDF")
    w = PdfWriter(clone_from=reader)
    counts: Counter = Counter()
    uyarilar = ["PyMuPDF yok: PDF maskeleme pypdf ile en iyi çaba (içerik akışı baytları); "
                "gerçek kaldırma için pip install 'bidr[maske]'"]
    for page in w.pages:
        cs = page.get_contents()
        if cs is not None and _mask_ops(cs.operations, rules, counts):
            page.replace_contents(cs)
        res = page.get("/Resources")
        xobjs = (res.get_object().get("/XObject") if res is not None else None)
        if xobjs is not None:
            for name in list(xobjs.get_object().keys()):
                xo = xobjs.get_object()[name].get_object()
                if xo.get("/Subtype") != "/Form":
                    continue
                try:
                    fcs = ContentStream(xo, w)
                    if _mask_ops(fcs.operations, rules, counts):
                        xo.set_data(fcs.get_data())
                except Exception as e:   # biçim nesnesi değiştirilemedi: yeniden tarama karar verir
                    uyarilar.append(f"biçim nesnesi işlenemedi: {type(e).__name__}")
    temiz = _clean_pdf_writer(w)
    w = _rebuild(w)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(dst, "wb") as f:
        w.write(f)
    return {"maskelenen": counts, "temizlenen": temiz, "uyarilar": uyarilar}


def mask_pdf_pymupdf(src: Path, dst: Path, rules: MaskRules) -> dict:   # pragma: no cover - isteğe bağlı
    fitz = _fitz()
    doc = fitz.open(str(src))
    if doc.needs_pass:
        raise MaskError("şifreli PDF")
    counts: Counter = Counter()
    temiz = set()
    uyarilar = []
    for page in doc:
        for a in list(page.annots() or []):
            page.delete_annot(a)
            temiz.add("yorum_aciklama")
        for wdg in list(page.widgets() or []):
            page.delete_widget(wdg)
            temiz.add("form")
        text = page.get_text("text")
        for f in detect(text, rules):
            counts[f.kind] += 1
            frag = text[f.start:f.end]
            found = False
            for part in [p.strip() for p in re.split(r"[\r\n]+", frag) if p.strip()]:
                for r in page.search_for(part):
                    page.add_redact_annot(r, fill=(0, 0, 0))
                    found = True
            if not found:
                uyarilar.append(f"s.{page.number + 1}: bulgu konumu bulunamadı ({f.kind})")
        page.apply_redactions()
    if doc.metadata and any(doc.metadata.values()):
        temiz.add("ust_veri")
    doc.set_metadata({})
    try:
        doc.del_xml_metadata()
        temiz.add("xmp")
    except Exception:
        pass
    for n in list(doc.embfile_names()):
        doc.embfile_del(n)
        temiz.add("ekler_ve_adlar")
    if doc.get_toc():
        doc.set_toc([])
        temiz.add("yer_imleri")
    dst.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(dst), garbage=4, deflate=True, clean=True)
    doc.close()
    # PyMuPDF'in dokunmadığı katalog girdileri (yapı ağacı vb.): pypdf ile ikinci geçiş
    from pypdf import PdfReader, PdfWriter
    _quiet_pypdf()
    w = PdfWriter(clone_from=PdfReader(str(dst)))
    temiz |= set(_clean_pdf_writer(w))
    w = _rebuild(w)
    buf = io.BytesIO()
    w.write(buf)
    dst.write_bytes(buf.getvalue())
    return {"maskelenen": counts, "temizlenen": sorted(temiz), "uyarilar": uyarilar}


def _iter_indirect(reader):
    from pypdf.generic import IndirectObject
    seen = set()
    for gen, d in (reader.xref or {}).items():
        for num in d:
            seen.add((num, gen))
    for num in (getattr(reader, "xref_objStm", None) or {}):
        seen.add((num, 0))
    for num, gen in sorted(seen):
        try:
            yield reader.get_object(IndirectObject(num, gen, reader))
        except Exception:
            continue


def scan_pdf(path: Path, rules: MaskRules) -> dict:
    from pypdf import PdfReader
    from pypdf.generic import StreamObject
    _quiet_pypdf()
    reader = PdfReader(str(path))
    found: Counter = Counter()
    sorunlar: list[str] = []
    imza: list[str] = []
    if reader.is_encrypted:
        return {"bulgular": found, "sorunlar": ["sifreli"], "imza": imza}
    for i, page in enumerate(reader.pages, 1):
        try:
            t = page.extract_text() or ""
        except Exception:
            t = ""
            sorunlar.append(f"s.{i}: metin çıkarılamadı")
        for f in detect(t, rules):
            found[f.kind] += 1
        if page.get("/Annots"):
            sorunlar.append("yorum_aciklama")
        if _has_imza(t) and _page_has_image(page):
            imza.append(f"s.{i}")
    meta = reader.metadata or {}
    mtext = "\n".join(str(v) for v in meta.values() if v)
    for f in detect(mtext, rules):
        found[f.kind] += 1
    if any(str(meta.get(k) or "").strip() for k in ("/Author", "/Title", "/Subject", "/Keywords")):
        sorunlar.append("ust_veri")
    root = reader.trailer["/Root"].get_object()
    for key, tag in (("/Metadata", "xmp"), ("/AcroForm", "form"), ("/Outlines", "yer_imleri")):
        if key in root:
            sorunlar.append(tag)
    names = root.get("/Names")
    if names is not None and "/EmbeddedFiles" in names.get_object():
        sorunlar.append("ek_dosya")
    raw_rules = _sub_rules(rules, RAW_KINDS)
    raw: Counter = Counter()
    for obj in _iter_indirect(reader):
        if not isinstance(obj, StreamObject):
            continue
        if obj.get("/Subtype") in ("/Image", "/Type1C", "/CIDFontType0C", "/OpenType") or "/Length1" in obj \
                or "/N" in obj:
            continue
        try:
            data = obj.get_data()
        except Exception:
            continue
        for f in detect(data.decode("latin-1"), raw_rules):
            raw[f.kind] += 1
    for k, n in raw.items():                      # ham akışta kalan: metin çıkarımının kaçırdığı
        found[k] = max(found[k], n)
    return {"bulgular": found, "sorunlar": sorted(set(sorunlar)), "imza": imza}


def _page_has_image(page) -> bool:
    try:
        res = page.get("/Resources")
        xo = res.get_object().get("/XObject") if res is not None else None
        if xo is not None:
            for v in xo.get_object().values():
                if v.get_object().get("/Subtype") == "/Image":
                    return True
        cs = page.get_contents()
        return cs is not None and any(op == b"INLINE IMAGE" or op == b"BI" for _, op in cs.operations)
    except Exception:
        return False


# ---------------------------------------------------------------- DOCX

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_DOCX_TEXT_PARTS = re.compile(r"^/word/(document|header\d*|footer\d*|footnotes|endnotes)\.xml$")
_DROP_PKG_RELS = ("custom-properties", "extended-properties", "thumbnail")
_DROP_DOC_RELS = ("comments", "commentsExtended", "commentsIds", "commentsExtensible", "people")


def _w(tag: str) -> str:
    return f"{{{W}}}{tag}"


def _nearest(el, tag):
    for a in el.iterancestors(tag):
        return a
    return None


def _mask_paragraph(p, rules: MaskRules, counts: Counter) -> None:
    chars: list[str] = []
    where: list[tuple | None] = []
    for el in p.iter(_w("t"), _w("tab"), _w("br"), _w("cr")):
        if _nearest(el, _w("p")) is not p:
            continue
        if el.tag == _w("t"):
            for j, c in enumerate(el.text or ""):
                chars.append(c)
                where.append((el, j))
        else:
            chars.append(" ")
            where.append(None)
    text = "".join(chars)
    fs = detect(text, rules)
    if not fs:
        return
    edits: dict = {}
    for f in fs:
        counts[f.kind] += 1
        first = True
        for i in range(f.start, f.end):
            w = where[i]
            if w is None:
                continue
            el, j = w
            buf = edits.setdefault(el, list(el.text or ""))
            buf[j] = PLACEHOLDERS.get(f.kind, "[?]") if first else ""
            first = False
    for el, buf in edits.items():
        el.text = "".join(buf)
        el.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")


def _drop_rels(rels, suffixes) -> bool:
    gone = False
    for rid, rel in list(rels.items()):
        if any(rel.reltype.endswith("/" + s) for s in suffixes):
            rels.pop(rid)
            gone = True
    return gone


def mask_docx(src: Path, dst: Path, rules: MaskRules) -> dict:
    import docx
    from docx.opc.part import XmlPart
    d = docx.Document(str(src))
    counts: Counter = Counter()
    temiz: set[str] = set()
    pkg = d.part.package
    # yorumlar: içerikteki kişisel veri sayılır, parça ve işaretler silinir
    for part in pkg.iter_parts():
        if isinstance(part, XmlPart) and re.search(r"/word/comments", str(part.partname)):
            for f in detect("\n".join(part._element.itertext()), rules):
                counts[f.kind] += 1
    for part in list(pkg.iter_parts()):
        if isinstance(part, XmlPart) and _drop_rels(part.rels, _DROP_DOC_RELS):
            temiz.add("yorumlar")
    for part in list(pkg.iter_parts()):
        if not (isinstance(part, XmlPart) and _DOCX_TEXT_PARTS.match(str(part.partname))):
            continue
        root = part._element
        for tag in ("commentRangeStart", "commentRangeEnd"):
            for el in list(root.iter(_w(tag))):
                el.getparent().remove(el)
        for el in list(root.iter(_w("commentReference"))):
            r = el.getparent()
            r.getparent().remove(r)
        # izlenen değişiklikler: silinen metin yayına girmez
        for tag in ("del", "moveFrom"):
            for el in list(root.iter(_w(tag))):
                if el.getparent() is not None and el.getparent().tag != _w("rPr"):
                    for f in detect("".join(el.itertext()), rules):
                        counts[f.kind] += 1
                    el.getparent().remove(el)
                    temiz.add("izlenen_degisiklikler")
        for p in root.iter(_w("p")):
            _mask_paragraph(p, rules, counts)
        for el in root.iter(_w("instrText")):
            if el.text:
                new, c = mask_text(el.text, rules)
                if c:
                    el.text = new
                    counts.update(c)
        for el in root.iter():
            for attr in ("descr", "title", "name"):
                v = el.get(attr)
                if v and el.tag.endswith("}docPr"):
                    new, c = mask_text(v, rules)
                    if c:
                        el.set(attr, new)
                        counts.update(c)
        for rel in part.rels.values():
            if rel.is_external:
                new, c = mask_text(rel.target_ref, rules)
                if c:
                    rel._target = new
                    counts.update(c)
    cp = d.core_properties
    for a in ("author", "last_modified_by", "title", "subject", "keywords", "comments", "category",
              "content_status", "identifier", "version"):
        try:
            if getattr(cp, a):
                temiz.add("ust_veri")
            setattr(cp, a, "")
        except Exception:
            pass
    if _drop_rels(pkg.rels, _DROP_PKG_RELS):
        temiz.add("ust_veri")
    dst.parent.mkdir(parents=True, exist_ok=True)
    d.save(str(dst))
    return {"maskelenen": counts, "temizlenen": sorted(temiz), "uyarilar": []}


# ---------------------------------------------------------------- OOXML tarama (docx, xlsx)

_GROUP = {_w("p"), "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si",
          "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}is"}


def _xml_texts(data: bytes) -> list[str]:
    """XML parçasının metinleri: paragraf/paylaşılan dize birleşik, kalan metin düğümleri ve
    öznitelik değerleri ayrı ayrı."""
    from lxml import etree
    try:
        root = etree.fromstring(data, parser=etree.XMLParser(resolve_entities=False, huge_tree=True))
    except etree.XMLSyntaxError:
        return [data.decode("utf-8", "replace")]
    groups: dict = {}
    order: list = []
    out: list[str] = []
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        for v in el.attrib.values():
            out.append(v)
        if el.text and el.tag not in _GROUP:
            g = None
            for a in el.iterancestors():
                if a.tag in _GROUP:
                    g = a
                    break
            if g is None:
                out.append(el.text)
            else:
                if g not in groups:
                    groups[g] = []
                    order.append(g)
                groups[g].append(el.text)
    return ["".join(groups[g]) for g in order] + out


def _scan_ooxml(path: Path, rules: MaskRules) -> tuple[Counter, list[str], bool, str]:
    found: Counter = Counter()
    sorunlar: list[str] = []
    body = []
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        has_media = any(n.startswith(("word/media/", "xl/media/")) for n in names)
        for n in names:
            if not (n.endswith(".xml") or n.endswith(".rels")):
                continue
            texts = _xml_texts(z.read(n))
            for t in texts:
                for f in detect(t, rules):
                    found[f.kind] += 1
            if n.startswith(("word/document", "xl/sharedStrings", "xl/worksheets/")):
                body.extend(texts)
            if re.match(r"(word/comments|xl/comments|xl/threadedComments)", n):
                sorunlar.append("yorum")
            if n == "docProps/custom.xml":
                sorunlar.append("ust_veri")
            if n == "docProps/core.xml":
                from lxml import etree
                root = etree.fromstring(z.read(n))
                for el in root:
                    local = etree.QName(el).localname
                    if local in ("creator", "lastModifiedBy", "title", "subject", "keywords", "description") \
                            and (el.text or "").strip():
                        sorunlar.append("ust_veri")
            if re.match(r"word/(document|header|footer|footnotes|endnotes).*\.xml$", n) and b"<w:del " in z.read(n):
                sorunlar.append("izlenen_degisiklikler")
    return found, sorted(set(sorunlar)), has_media, "\n".join(body)


def scan_docx(path: Path, rules: MaskRules) -> dict:
    found, sorunlar, media, body = _scan_ooxml(path, rules)
    imza = ["belge"] if media and _has_imza(body) else []
    return {"bulgular": found, "sorunlar": sorunlar, "imza": imza}


# ---------------------------------------------------------------- XLSX

def _mask_cell_value(v, rules: MaskRules, counts: Counter):
    if isinstance(v, str):
        new, c = mask_text(v, rules)
        counts.update(c)
        return new
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, int) or (isinstance(v, float) and v.is_integer() and abs(v) < 1e15):
        s = str(int(v))
        new, c = mask_text(s, rules)
        if c:
            counts.update(c)
            return new
    return v


def mask_xlsx(src: Path, dst: Path, rules: MaskRules) -> dict:
    import openpyxl
    keep_vba = src.suffix.lower() == ".xlsm"
    wb = openpyxl.load_workbook(str(src), keep_vba=keep_vba)
    counts: Counter = Counter()
    temiz: set[str] = set()
    uyarilar: list[str] = []
    with zipfile.ZipFile(src) as z:
        if any(n.startswith(("xl/media/", "xl/charts/", "xl/drawings/")) for n in z.namelist()):
            uyarilar.append("görsel/grafik/çizimler maskeli kopyada korunmaz (openpyxl)")
    titles = set()
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if cell.comment is not None:
                    for f in detect(cell.comment.text or "", rules):
                        counts[f.kind] += 1
                    cell.comment = None
                    temiz.add("yorumlar")
                v = cell.value
                if v is None:
                    continue
                new = _mask_cell_value(v, rules, counts)
                if new is not v and new != v:
                    cell.value = new
        for hf in (ws.oddHeader, ws.oddFooter, ws.evenHeader, ws.evenFooter, ws.firstHeader, ws.firstFooter):
            for part in (hf.left, hf.center, hf.right):
                if part.text:
                    new, c = mask_text(part.text, rules)
                    if c:
                        part.text = new
                        counts.update(c)
        new, c = mask_text(ws.title, rules)
        if c:
            counts.update(c)
            base = re.sub(r"[\[\]:*?/\\]", "", new)[:28] or "Sayfa"
            t, i = base, 1
            while t in titles or t in wb.sheetnames:
                i += 1
                t = f"{base[:26]}{i}"
            ws.title = t
        titles.add(ws.title)
    p = wb.properties
    for a in ("creator", "lastModifiedBy", "title", "subject", "keywords", "description", "category",
              "identifier", "contentStatus", "version"):
        if getattr(p, a, None):
            temiz.add("ust_veri")
            setattr(p, a, None)
    try:
        if len(wb.custom_doc_props.props):
            temiz.add("ust_veri")
        wb.custom_doc_props.props = []
    except Exception:
        pass
    dst.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(dst))
    return {"maskelenen": counts, "temizlenen": sorted(temiz), "uyarilar": uyarilar}


def scan_xlsx(path: Path, rules: MaskRules) -> dict:
    found, sorunlar, media, body = _scan_ooxml(path, rules)
    imza = ["belge"] if media and _has_imza(body) else []
    return {"bulgular": found, "sorunlar": sorunlar, "imza": imza}


# ---------------------------------------------------------------- düz metin

def _read_text(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1254"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1"), "latin-1"


def mask_textfile(src: Path, dst: Path, rules: MaskRules) -> dict:
    text, enc = _read_text(src)
    new, c = mask_text(text, rules)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(new, encoding="utf-8" if enc == "utf-8-sig" else enc)
    return {"maskelenen": c, "temizlenen": [], "uyarilar": []}


def scan_textfile(path: Path, rules: MaskRules) -> dict:
    text, _ = _read_text(path)
    return {"bulgular": Counter(f.kind for f in detect(text, rules)), "sorunlar": [], "imza": []}


# ---------------------------------------------------------------- dağıtım

def kind_of(path: Path) -> str | None:
    e = path.suffix.lower()
    if e in PDF_EXT:
        return "pdf"
    if e in DOCX_EXT:
        return "docx"
    if e in XLSX_EXT:
        return "xlsx"
    if e in TEXT_EXT:
        return "metin"
    return None


def mask_file(src: Path, dst: Path, rules: MaskRules, *, engine: str = "pypdf") -> dict:
    k = kind_of(src)
    if k == "pdf":
        return (mask_pdf_pymupdf if engine == "pymupdf" else mask_pdf_pypdf)(src, dst, rules)
    if k == "docx":
        return mask_docx(src, dst, rules)
    if k == "xlsx":
        return mask_xlsx(src, dst, rules)
    if k == "metin":
        return mask_textfile(src, dst, rules)
    raise MaskError(f"desteklenmeyen biçim: {src.suffix}")


def scan_file(path: Path, rules: MaskRules) -> dict:
    k = kind_of(path)
    if k == "pdf":
        return scan_pdf(path, rules)
    if k == "docx":
        return scan_docx(path, rules)
    if k == "xlsx":
        return scan_xlsx(path, rules)
    if k == "metin":
        return scan_textfile(path, rules)
    raise MaskError(f"desteklenmeyen biçim: {path.suffix}")
