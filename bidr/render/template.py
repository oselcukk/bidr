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


# -- Güçlü Yönler / Gelişmeye Açık Yönler tablosu -----------------------------------------------
# Şablonun sonunda dört alan için iki sütunlu tablo: alan başlık satırı (ör. "EĞİTİM VE
# ÖĞRETİM"), "Güçlü Yönler | Gelişmeye Açık Yönler" satırı, ardından iki içerik hücresi
# (şablonda yönerge metniyle: "… güçlü yönlerini değerlendiriniz.").
GUCLU = "Güçlü Yönler"
GELISME = "Gelişmeye Açık Yönler"
YONLER_YONERGE = "değerlendiriniz"
# Başlık satırındaki anahtar sözcük → alan (şablondaki yazım hatalarına dayanıklı: "LİDELİK").
ALAN_ANAHTAR = (("LİDER", "A"), ("LİDEL", "A"), ("YÖNETİŞİM", "A"), ("EĞİTİM", "B"), ("ARAŞTIRMA", "C"),
                ("TOPLUMSAL", "D"))


@dataclass
class YonCells:
    alan: str
    baslik: str
    guclu_tc: object
    gelisme_tc: object


def _alan_of(head: str) -> str | None:
    up = head.replace("i", "İ").replace("ı", "I").upper()
    for key, alan in ALAN_ANAHTAR:
        if key in up:
            return alan
    return None


def find_yonler(doc) -> tuple[dict[str, YonCells], list[str]]:
    """{alan: YonCells} ve uyarılar. Tablo yoksa boş sözlük."""
    out: dict[str, YonCells] = {}
    warnings: list[str] = []
    for tbl in doc.element.body.iterchildren(W + "tbl"):
        rows = [r for r in tbl.iter(W + "tr")]
        head, order = None, 0
        for i, tr in enumerate(rows):
            cells = _row_cells(tr)
            flat = [" ".join(_cell_lines(c)).strip() for c in cells]
            if len(cells) == 1 and flat[0]:
                head = flat[0]
                continue
            if len(cells) == 2 and flat[0] == GUCLU and flat[1] == GELISME and i + 1 < len(rows):
                nxt = _row_cells(rows[i + 1])
                if len(nxt) != 2:
                    warnings.append(f"'{head}': güçlü/gelişmeye açık yönler içerik satırı bulunamadı")
                    continue
                alan = _alan_of(head or "") or ("ABCD"[order] if order < 4 else None)
                order += 1
                if alan is None:
                    warnings.append(f"'{head}': alan belirlenemedi")
                    continue
                if alan in out:
                    warnings.append(f"{alan}: güçlü/gelişmeye açık yönler iki kez; ilki kullanıldı")
                    continue
                out[alan] = YonCells(alan, head or "", nxt[0], nxt[1])
    return out, warnings


# -- kapak: "Raporu Hazırlayanlar" ----------------------------------------------------------------
HAZIRLAYAN_BASLIK = "Raporu Hazırlayanlar"
HAZIRLAYAN_YER_TUTUCU = "[Üye Unvan"
# FR-0833 Değ.No:1 (10.11.2026) kapağı hazırlayanların ardından ayrı bir başlık altında birim amirinin yer
# tutucusunu taşır; satır biçimi aynı ("[Üye Unvan, Adı Soyadı, eposta adresi, Görevi]"). Eski şablonda yok.
AMIR_BASLIK = "Raporu Onaylayan Birim Amiri"
AMIR_ONEK = "Raporu Onaylayan"


def _norm(t: str) -> str:
    return " ".join(t.split())


def cover_sections(paras: list) -> dict[str, list]:
    """Kapak yer tutucularını başlığa göre bölümler: {"hazirlayan": [w:p…], "amir": [w:p…]}.

    Bir bölüm başlığından ("Raporu Hazırlayanlar", "Raporu Onaylayan Birim Amiri") sonraki ilk dolu ve yer
    tutucu olmayan paragrafa kadar sürer; boş paragraflar bölümü kapatmaz. Hiçbir bölümün içinde olmayan yer
    tutucu (başlıksız eski düzen) hazırlayan sayılır; amir yalnız kendi başlığının altında aranır."""
    from bidr.criteria.extract_docx import _ptext
    out: dict[str, list] = {"hazirlayan": [], "amir": []}
    cur = None
    for p in paras:
        t = _norm(_ptext(p))
        if t == HAZIRLAYAN_BASLIK:
            cur = "hazirlayan"
            continue
        if t.startswith(AMIR_ONEK):
            cur = "amir"
            continue
        if HAZIRLAYAN_YER_TUTUCU in t:
            out[cur or "hazirlayan"].append(p)
            continue
        if t:
            cur = None
    return out
