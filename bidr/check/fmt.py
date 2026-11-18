"""docx'te etkin biçim çözümü (salt okur): çalışma → karakter stili → paragraf stili →
tablo koşullu biçimi (ilk satır/sütun) → tablo stili → belge varsayılanı.

Word'ün bütün kurallarını değil, denetim için gerekenleri izler: yazı tipi (ascii; tema
yazı tipi tema parçasından çözülür), punto, kalın, italik, paragraf öncesi/sonrası aralık
ve hizalama. Çözülemeyen değer `None` döner; denetçi bunu ihlal saymaz, "belirsiz" yazar.
"""
from __future__ import annotations

from bidr.criteria.extract_docx import W, _ptext

A_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_FALSE = {"0", "false", "off"}


def _bool(el) -> bool | None:
    if el is None:
        return None
    return el.get(W + "val") not in _FALSE


class Styles:
    def __init__(self, doc):
        root = doc.styles.element
        self.by_id = {s.get(W + "styleId"): s for s in root.findall(W + "style")}
        self.default_para = next((s.get(W + "styleId") for s in root.findall(W + "style")
                                  if s.get(W + "type") == "paragraph" and s.get(W + "default") in ("1", "true")),
                                 None)
        dd = root.find(W + "docDefaults")
        self.rpr_default = dd.find(f"{W}rPrDefault/{W}rPr") if dd is not None else None
        self.ppr_default = dd.find(f"{W}pPrDefault/{W}pPr") if dd is not None else None
        self.theme = _theme_fonts(doc)

    def chain(self, sid: str | None) -> list:
        out, seen = [], set()
        while sid and sid in self.by_id and sid not in seen:
            seen.add(sid)
            s = self.by_id[sid]
            out.append(s)
            b = s.find(W + "basedOn")
            sid = b.get(W + "val") if b is not None else None
        return out


def _theme_fonts(doc) -> dict[str, str]:
    """{'minor': 'Aptos', 'major': '…'}: tema parçasının latin yazı tipleri (yoksa boş)."""
    try:
        from docx.opc.constants import RELATIONSHIP_TYPE as RT
        from lxml import etree
        part = doc.part.part_related_by(RT.THEME)
        root = etree.fromstring(part.blob)
    except Exception:  # tema parçası yok ya da okunamadı
        return {}
    out = {}
    for kind in ("minor", "major"):
        el = root.find(f".//{A_NS}{kind}Font/{A_NS}latin")
        if el is not None and el.get("typeface"):
            out[kind] = el.get("typeface")
    return out


class TableCtx:
    """Paragrafın içinde bulunduğu en içteki tablo hücresi bağlamı."""

    def __init__(self, tbl, row_idx: int, col_idx: int):
        self.tbl, self.row_idx, self.col_idx = tbl, row_idx, col_idx

    def style_id(self) -> str | None:
        el = self.tbl.find(f"{W}tblPr/{W}tblStyle")
        return el.get(W + "val") if el is not None else None

    def look(self) -> dict[str, bool]:
        el = self.tbl.find(f"{W}tblPr/{W}tblLook")
        if el is None:
            return {"firstRow": True, "firstColumn": True}   # Word varsayılanı 04A0
        out = {}
        val = el.get(W + "val")
        bits = int(val, 16) if val else 0
        for name, bit in (("firstRow", 0x20), ("firstColumn", 0x80)):
            a = el.get(W + name)
            out[name] = (a not in _FALSE) if a is not None else bool(bits & bit)
        return out


def table_ctx(p) -> TableCtx | None:
    tc = next((a for a in p.iterancestors(W + "tc")), None)
    if tc is None:
        return None
    tr = tc.getparent()
    tbl = tr.getparent()
    rows = [r for r in tbl.iterchildren(W + "tr")]
    cells = [c for c in tr.iterchildren(W + "tc")]
    return TableCtx(tbl, rows.index(tr) if tr in rows else -1, cells.index(tc) if tc in cells else -1)


class Resolver:
    def __init__(self, doc):
        self.st = Styles(doc)

    # -- karakter özellikleri -----------------------------------------------------------------
    def _rpr_sources(self, r, p) -> list:
        srcs = [r.find(W + "rPr")]
        rs = r.find(f"{W}rPr/{W}rStyle")
        if rs is not None:
            srcs += [s.find(W + "rPr") for s in self.st.chain(rs.get(W + "val"))]
        srcs += [s.find(W + "rPr") for s in self.st.chain(self._pstyle(p))]
        ctx = table_ctx(p)
        if ctx is not None:
            chain = self.st.chain(ctx.style_id())
            look = ctx.look()
            for s in chain:
                for tsp in s.findall(W + "tblStylePr"):
                    t = tsp.get(W + "type")
                    if (t == "firstRow" and look["firstRow"] and ctx.row_idx == 0) or \
                       (t == "firstCol" and look["firstColumn"] and ctx.col_idx == 0):
                        srcs.append(tsp.find(W + "rPr"))
            srcs += [s.find(W + "rPr") for s in chain]
        srcs.append(self.st.rpr_default)
        return [s for s in srcs if s is not None]

    def _pstyle(self, p) -> str | None:
        el = p.find(f"{W}pPr/{W}pStyle")
        return el.get(W + "val") if el is not None else self.st.default_para

    def font(self, r, p) -> str | None:
        for src in self._rpr_sources(r, p):
            f = src.find(W + "rFonts")
            if f is None:
                continue
            if f.get(W + "ascii"):
                return f.get(W + "ascii")
            th = f.get(W + "asciiTheme")
            if th:
                kind = "major" if th.startswith("major") else "minor"
                return self.st.theme.get(kind, f"tema:{th}")
        return None

    def size_half_pt(self, r, p) -> int | None:
        for src in self._rpr_sources(r, p):
            el = src.find(W + "sz")
            if el is not None and el.get(W + "val"):
                try:
                    return int(el.get(W + "val"))
                except ValueError:
                    return None
        return 20  # OOXML varsayılanı: 10 pt (docDefaults yoksa)

    def toggle(self, r, p, tag: str) -> bool:
        for src in self._rpr_sources(r, p):
            v = _bool(src.find(W + tag))
            if v is not None:
                return v
        return False

    # -- paragraf özellikleri -----------------------------------------------------------------
    def _ppr_sources(self, p) -> list:
        srcs = [p.find(W + "pPr")]
        srcs += [s.find(W + "pPr") for s in self.st.chain(self._pstyle(p))]
        ctx = table_ctx(p)
        if ctx is not None:
            srcs += [s.find(W + "pPr") for s in self.st.chain(ctx.style_id())]
        srcs.append(self.st.ppr_default)
        return [s for s in srcs if s is not None]

    def spacing(self, p, side: str) -> int | None:
        """'before' | 'after' (twip). Otomatik aralık (…Autospacing) `None`: belirsiz değil,
        kuralla uyuşmaz sayılır; denetçi -1 ile ayırır."""
        for src in self._ppr_sources(p):
            sp = src.find(W + "spacing")
            if sp is None:
                continue
            if sp.get(W + side + "Autospacing") in ("1", "true", "on"):
                return -1
            v = sp.get(W + side)
            if v is not None:
                try:
                    return int(v)
                except ValueError:
                    return None
        return 0

    def jc(self, p) -> str:
        for src in self._ppr_sources(p):
            el = src.find(W + "jc")
            if el is not None:
                return el.get(W + "val") or "left"
        return "left"


def text_runs(p) -> list:
    """Metin taşıyan çalışmalar (bağlantı içindekiler dahil; yalnız boşluk olanlar hariç)."""
    out = []
    for r in p.iter(W + "r"):
        t = "".join(x.text or "" for x in r.findall(W + "t"))
        if t.strip():
            out.append(r)
    return out


def has_object(el) -> bool:
    """Öğe görsel/tablo nesnesi mi (ya da içeriyor mu)."""
    if el is None:
        return False
    if el.tag == W + "tbl":
        return True
    return any(True for _ in el.iter(W + "drawing")) or any(True for _ in el.iter(W + "pict"))


def field_signature(container) -> list[str]:
    """Üstbilgi/altbilgi paragraflarının imzası: düz metin + alan kodları `{PAGE}` olarak;
    alan sonuç metni (sayfa numarası) atılır. Boş paragraflar atlanır."""
    out = []
    for p in container.iter(W + "p"):
        parts: list[str] = []
        depth, mode, instr = 0, None, []

        def walk(el):
            nonlocal depth, mode, instr
            for ch in el:
                tag = ch.tag
                if tag == W + "fldSimple":
                    parts.append("{" + " ".join((ch.get(W + "instr") or "").split()[:1]) + "}")
                    continue
                if tag == W + "fldChar":
                    t = ch.get(W + "fldCharType")
                    if t == "begin":
                        depth += 1
                        mode, instr = "instr", []
                    elif t == "separate":
                        mode = "result"
                    elif t == "end" and depth:
                        depth -= 1
                        code = " ".join("".join(instr).split()[:1])
                        if code:
                            parts.append("{" + code + "}")
                        mode = None if depth == 0 else mode
                    continue
                if tag == W + "instrText":
                    if mode == "instr":
                        instr.append(ch.text or "")
                    continue
                if tag == W + "t":
                    if depth == 0:
                        parts.append(ch.text or "")
                    continue
                if tag == W + "tab" and depth == 0 and ch.getparent().tag == W + "r":
                    parts.append("\t")
                    continue
                walk(ch)
        walk(p)
        s = " ".join("".join(parts).split())
        if s:
            out.append(s)
    return out


__all__ = ["Resolver", "text_runs", "has_object", "field_signature", "table_ctx", "_ptext"]
