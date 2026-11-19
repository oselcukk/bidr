"""Şablona dokunan XML işlemleri. Yalnız istenen hücreler/çalışmalar değişir; öğe sırası
OOXML şemasına uygun tutulur (Word sırası bozuk rPr/tcPr'yi onarım uyarısıyla açar)."""
from __future__ import annotations

import copy
from pathlib import Path

from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from bidr.criteria.extract_docx import W, _ptext

FONT = "Times New Roman"
BODY_SZ = 20               # yarım punto: 10 pt gövde (kılavuz "Yazım Kuralları")
SPACING_BEFORE = 0         # twip: "öncesi 0 nk"
SPACING_AFTER = 12         # twip = 0,6 nk: kılavuz "sonrası 0,6 nk" (kurumca doğrulandı, 2026-11-19)
TASLAK_RENK = "C00000"
LINK_RENK = "0563C1"            # Word "Köprü" rengi

# CT_RPr / CT_TcPr öğe sırası (ECMA-376, kısaltılmış: kullandıklarımız ve komşuları)
RPR_ORDER = ["rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps", "strike", "dstrike",
             "outline", "shadow", "emboss", "imprint", "noProof", "snapToGrid", "vanish", "webHidden",
             "color", "spacing", "w", "kern", "position", "sz", "szCs", "highlight", "u", "effect",
             "bdr", "shd", "fitText", "vertAlign", "rtl", "cs", "em", "lang", "eastAsianLayout",
             "specVanish", "oMath"]
TCPR_ORDER = ["cnfStyle", "tcW", "gridSpan", "hMerge", "vMerge", "tcBorders", "shd", "noWrap",
              "tcMar", "textDirection", "tcFitText", "vAlign", "hideMark"]


def _set_ordered(parent, tag: str, order: list[str], attrs: dict[str, str] | None = None):
    """`parent` altında `tag` öğesini (varsa değiştirerek) şema sırasındaki yerine koyar."""
    for old in parent.findall(qn("w:" + tag)):
        parent.remove(old)
    el = OxmlElement("w:" + tag)
    for k, v in (attrs or {}).items():
        el.set(qn("w:" + k), v)
    idx = order.index(tag)
    pos = len(parent)
    for i, ch in enumerate(parent):
        name = ch.tag.split("}")[1] if "}" in ch.tag else ch.tag
        if name in order and order.index(name) > idx:
            pos = i
            break
    parent.insert(pos, el)
    return el


def _rpr(*, bold: bool = False, italic: bool = False, color: str | None = None,
         sz: int = BODY_SZ):
    rpr = OxmlElement("w:rPr")
    f = OxmlElement("w:rFonts")
    for a in ("ascii", "hAnsi", "cs"):
        f.set(qn("w:" + a), FONT)
    rpr.append(f)
    # Şablonun ölçüt tabloları ilk sütunu kalın yapan tablo stiliyle biçimlenir; gövde
    # metni şablondaki gibi açıkça kalın-değil işaretlenir.
    for t in ("b", "bCs"):
        e = OxmlElement("w:" + t)
        if not bold:
            e.set(qn("w:val"), "0")
        rpr.append(e)
    if italic:
        rpr.append(OxmlElement("w:i"))
        rpr.append(OxmlElement("w:iCs"))
    if color:
        c = OxmlElement("w:color")
        c.set(qn("w:val"), color)
        rpr.append(c)
    for t in ("sz", "szCs"):
        e = OxmlElement("w:" + t)
        e.set(qn("w:val"), str(sz))
        rpr.append(e)
    return rpr


def make_paragraph(segments, *, jc: str = "both"):
    """segments: [(metin, {bold, italic, color})]. Gövde paragrafı: 10 pt, iki yana yaslı,
    önce 0 / sonra 0,6 nk. Stil verilmez: şablonun hücre paragrafları gibi Normal kalır."""
    if isinstance(segments, str):
        segments = [(segments, {})]
    p = OxmlElement("w:p")
    ppr = OxmlElement("w:pPr")
    sp = OxmlElement("w:spacing")
    sp.set(qn("w:before"), str(SPACING_BEFORE))
    sp.set(qn("w:after"), str(SPACING_AFTER))
    ppr.append(sp)
    j = OxmlElement("w:jc")
    j.set(qn("w:val"), jc)
    ppr.append(j)
    ppr.append(_rpr())
    p.append(ppr)
    for text, fmt in segments:
        fmt = dict(fmt)
        rid = fmt.pop("rid", None)
        if rid:                      # dış bağlantı: <w:hyperlink r:id> içinde mavi, altı çizili
            fmt.setdefault("color", LINK_RENK)
        r = OxmlElement("w:r")
        rpr = _rpr(**fmt)
        if rid:
            u = OxmlElement("w:u")
            u.set(qn("w:val"), "single")
            rpr.append(u)          # sz/szCs'ten sonra: CT_RPr sırasında u, sz'den sonra gelir
        r.append(rpr)
        t = OxmlElement("w:t")
        t.text = text
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        r.append(t)
        if rid:
            h = OxmlElement("w:hyperlink")
            h.set(qn("r:id"), rid)
            h.append(r)
            p.append(h)
        else:
            p.append(r)
    return p


def link_rid(part, url: str) -> str:
    """Belge parçasında dış bağlantı ilişkisi (aynı adres için aynı kimlik)."""
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    return part.relate_to(url, RT.HYPERLINK, is_external=True)


def set_paragraph_text(p, text: str) -> None:
    """Paragrafın metnini değiştirir; pPr ve ilk çalışmanın biçimi korunur."""
    first_r = p.find(".//" + qn("w:r"))
    rpr = first_r.find(qn("w:rPr")) if first_r is not None else None
    for ch in list(p):
        if ch.tag != qn("w:pPr"):
            p.remove(ch)
    r = OxmlElement("w:r")
    if rpr is not None:
        r.append(copy.deepcopy(rpr))
    t = OxmlElement("w:t")
    t.text = text
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    r.append(t)
    p.append(r)


def fill_cell(tc, label: str, paragraphs: list) -> None:
    """Hücrede yalnız etiket paragrafını ("Açıklamalar:") bırakır, ardından `paragraphs`."""
    ps = tc.findall(W + "p")
    if not ps:
        raise ValueError(f"hücrede paragraf yok ({label})")
    first = ps[0]
    if _ptext(first).strip() != label:
        set_paragraph_text(first, label)
    for p in ps[1:]:
        tc.remove(p)
    # tcPr'den sonra, varsa hücre sonundaki başka öğelerden önce ekle
    anchor = first
    for p in paragraphs:
        anchor.addnext(p)
        anchor = p


def mark_bold(tc) -> int:
    """Hücredeki bütün metin çalışmalarını kalın yapar (Kimya 2025 raporundaki işaret)."""
    n = 0
    for r in tc.iter(W + "r"):
        if r.find(W + "t") is None:
            continue
        rpr = r.find(W + "rPr")
        if rpr is None:
            rpr = OxmlElement("w:rPr")
            r.insert(0, rpr)
        _set_ordered(rpr, "b", RPR_ORDER)
        _set_ordered(rpr, "bCs", RPR_ORDER)
        n += 1
    return n


def mark_shade(tc, fill: str) -> None:
    tcpr = tc.find(W + "tcPr")
    if tcpr is None:
        tcpr = OxmlElement("w:tcPr")
        tc.insert(0, tcpr)
    _set_ordered(tcpr, "shd", TCPR_ORDER, {"val": "clear", "color": "auto", "fill": fill})


def header_style(doc):
    """Şablonun üstbilgi stili (yerelleştirilmiş kimliği ne olursa olsun, adı 'header')."""
    from docx.enum.style import WD_STYLE_TYPE
    for s in doc.styles:
        if s.type == WD_STYLE_TYPE.PARAGRAPH and s.style_id and s.name and s.name.lower() == "header":
            return s
    return None


def add_draft_mark(doc, text: str) -> int:
    """Her bölümün üstbilgisine (ilk sayfa farklıysa ona da) TASLAK satırı ekler."""
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor

    style = header_style(doc)
    n = 0
    for i, sec in enumerate(doc.sections):
        hdrs = [sec.header]
        if sec.different_first_page_header_footer:
            hdrs.append(sec.first_page_header)
        for h in hdrs:
            if h.is_linked_to_previous and i > 0:
                continue  # önceki bölümün üstbilgisini kullanıyor; orada zaten işaretli
            p = h.add_paragraph()
            if style is not None:
                p.style = style
            p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            run = p.add_run(text)
            run.bold = True
            run.font.name = FONT
            run.font.size = Pt(14)
            run.font.color.rgb = RGBColor.from_string(TASLAK_RENK)
            n += 1
    return n


def save_preserving(doc, template: Path, out: Path) -> list[str]:
    """Belgeyi kaydeder; içeriği (c14n) değişmeyen her parça şablondaki özgün baytlarıyla
    ve şablondaki sırayla yazılır. python-docx bütün XML parçalarını yeniden serileştirir;
    bu adım dokunulmayan parçaları bayt düzeyinde aynı bırakır. Değişen parça adlarını döner."""
    import io
    import zipfile

    from lxml import etree

    buf = io.BytesIO()
    doc.save(buf)
    new = zipfile.ZipFile(io.BytesIO(buf.getvalue()))
    old = zipfile.ZipFile(template)
    old_names = old.namelist()
    new_names = set(new.namelist())

    def canon(b: bytes) -> bytes | None:
        try:
            return etree.tostring(etree.fromstring(b), method="c14n")
        except etree.XMLSyntaxError:
            return None

    changed: list[str] = []
    order = [n for n in old_names if n in new_names] + sorted(new_names - set(old_names))
    tmp = out.with_suffix(out.suffix + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for n in order:
            nb = new.read(n)
            if n in old_names:
                ob = old.read(n)
                if ob == nb or (n.endswith((".xml", ".rels")) and canon(ob) is not None
                                and canon(ob) == canon(nb)):
                    z.writestr(old.getinfo(n), ob)
                    continue
            changed.append(n)
            z.writestr(n, nb)
    tmp.replace(out)
    return changed


def replace_cell(tc, paragraphs: list) -> None:
    """Hücredeki bütün paragrafları `paragraphs` ile değiştirir (tcPr ve hücre özellikleri korunur).
    Boş liste verilirse hücrede bir boş paragraf kalır (OOXML: hücrede en az bir paragraf)."""
    for p in tc.findall(W + "p"):
        tc.remove(p)
    if not paragraphs:
        paragraphs = [OxmlElement("w:p")]
    for p in paragraphs:
        tc.append(p)


def is_blank_paragraph(p) -> bool:
    """Metni, çizimi, alanı ve bölüm sonu olmayan paragraf (kapak boşluğu)."""
    if _ptext(p).strip():
        return False
    for tag in ("drawing", "pict", "object", "fldSimple", "fldChar", "sectPr", "br"):
        if p.find(".//" + qn("w:" + tag)) is not None:
            return False
    return True
