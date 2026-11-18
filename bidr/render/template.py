"""FR-0833 şablonunda alt ölçüt bloklarını bulur (salt okur).

Blok düzeni (`bidr.criteria.extract_docx` ile aynı okuma): alt ölçüt başlık satırı
("A.1.2. Liderlik …"), "1 2 3 4 5" satırı, bir ya da birden çok 5 hücreli rubrik satırı,
"Örnek Kanıtlar:" satırı, "Açıklamalar:" satırı, "Kanıtlar:" satırı. Bir sonraki
"DOLDURACAK BİRİMLER:" veya ölçüt başlığı bloğu kapatır.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from bidr.criteria.extract_docx import RE_MAIN, RE_SUB, UNITS_PREFIX, W, _cell_lines, _row_cells

ACIKLAMA = "Açıklamalar:"
KANIT = "Kanıtlar:"
ORNEK = "Örnek Kanıtlar:"
COVER_STOP = "ÖLÇÜTLER VE KANITLAR"


@dataclass
class Block:
    olcut: str
    header_tc: object
    numbers: list = field(default_factory=list)        # 5 w:tc ("1".."5")
    rubric: list = field(default_factory=list)         # satır başına 5 w:tc
    aciklama_tc: object | None = None
    kanit_tc: object | None = None

    def rubric_cells(self, od: int) -> list:
        """OD düzeyinin sütunundaki rubrik metin hücreleri (çok satırlı rubrikte hepsi)."""
        return [row[od - 1] for row in self.rubric if len(row) >= od]


def _head(tc) -> str:
    lines = _cell_lines(tc)
    return lines[0] if lines else ""


def find_blocks(doc) -> tuple[dict[str, Block], list[str]]:
    """{olcut: Block} ve uyarılar. `doc` python-docx Document."""
    blocks: dict[str, Block] = {}
    warnings: list[str] = []
    cur: Block | None = None
    in_rubric = False
    for tbl in doc.element.body.iterchildren(W + "tbl"):
        for tr in tbl.iter(W + "tr"):
            cells = _row_cells(tr)
            if not cells:
                continue
            head = _head(cells[0])
            flat = [" ".join(_cell_lines(c)).strip() for c in cells]
            m = RE_SUB.match(head) if len(cells) == 1 else None
            if m:
                sid = f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
                cur = Block(sid, cells[0])
                if sid in blocks:
                    warnings.append(f"{sid}: şablonda iki kez geçiyor; ilki kullanıldı")
                else:
                    blocks[sid] = cur
                in_rubric = False
                continue
            if head.startswith(UNITS_PREFIX) or RE_MAIN.match(head):
                cur, in_rubric = None, False
                continue
            if cur is None:
                continue
            if flat == ["1", "2", "3", "4", "5"]:
                cur.numbers = cells
                in_rubric = True
                continue
            if head.startswith(ORNEK):
                in_rubric = False
                continue
            if head.startswith(ACIKLAMA):
                cur.aciklama_tc = cells[0]
                in_rubric = False
                continue
            if head.startswith(KANIT):
                cur.kanit_tc = cells[0]
                in_rubric = False
                continue
            if in_rubric and len(cells) == 5:
                cur.rubric.append(cells)
    for sid, b in blocks.items():
        if b.aciklama_tc is None:
            warnings.append(f"{sid}: 'Açıklamalar:' hücresi bulunamadı")
        if b.kanit_tc is None:
            warnings.append(f"{sid}: 'Kanıtlar:' hücresi bulunamadı")
        if not b.rubric:
            warnings.append(f"{sid}: rubrik satırı bulunamadı")
    return blocks, warnings
