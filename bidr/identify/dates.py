"""İçerik tarihlerini bul (katlanmış metin üzerinde).

Form künyesi tarihleri (Yayın/Değişiklik/Revizyon Tarihi) ve sayfa başındaki
yazdırma damgaları içerik tarihi sayılmaz.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from .text import fold_pattern

MONTHS = {
    "ocak": 1, "subat": 2, "mart": 3, "nisan": 4, "mayis": 5, "haziran": 6,
    "temmuz": 7, "agustos": 8, "eylul": 9, "ekim": 10, "kasim": 11, "aralik": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}
_MON = "|".join(sorted(MONTHS, key=len, reverse=True))

NUMERIC = re.compile(r"(?<![\d/.])(\d{1,2}) ?[./-] ?(\d{1,2}) ?[./-] ?((?:19|20)\d\d)(?!\d)")
ISO = re.compile(r"(?<!\d)((?:19|20)\d\d)-(\d{2})-(\d{2})(?!\d)")
TEXTUAL = re.compile(rf"(?<!\d)(\d{{1,2}}) ({_MON}),? ((?:19|20)\d\d)(?!\d)")
TEXTUAL_EN = re.compile(rf"\b({_MON}) (\d{{1,2}}),? ((?:19|20)\d\d)(?!\d)")
ACADEMIC = re.compile(r"\b(20\d\d) ?[-/–] ?(20\d\d)\b(?:.{0,25}?\b(guz|bahar|yaz|fall|spring|summer)\b)?")
PRINT_STAMP = re.compile(r"^\W{0,3}\d{1,2}[./]\d{1,2}[./]\d{4},? \d{1,2}:\d{2}")

MIN_YEAR, MAX_YEAR = 1990, 2035


@dataclass
class Found:
    d: date
    start: int
    end: int


def _mk(y: int, m: int, d: int) -> date | None:
    if not (MIN_YEAR <= y <= MAX_YEAR):
        return None
    try:
        return date(y, m, d)
    except ValueError:
        if d <= 12 < m:  # ABD biçimi (ay/gün/yıl)
            try:
                return date(y, d, m)
            except ValueError:
                return None
        return None


def find_dates(folded: str) -> list[Found]:
    out: list[Found] = []
    for m in NUMERIC.finditer(folded):
        d = _mk(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        if d:
            out.append(Found(d, m.start(), m.end()))
    for m in ISO.finditer(folded):
        d = _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            out.append(Found(d, m.start(), m.end()))
    for m in TEXTUAL.finditer(folded):
        d = _mk(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)))
        if d:
            out.append(Found(d, m.start(), m.end()))
    for m in TEXTUAL_EN.finditer(folded):
        d = _mk(int(m.group(3)), MONTHS[m.group(1)], int(m.group(2)))
        if d:
            out.append(Found(d, m.start(), m.end()))
    out.sort(key=lambda f: f.start)
    return out


class DateFinder:
    def __init__(self, labels: list[str], excluded: list[str]):
        self.generic = [re.compile(fold_pattern(l) + r"\W{0,6}") for l in labels]
        self.excluded = re.compile("(" + "|".join(fold_pattern(e) for e in excluded) + r")\W{0,4}$") \
            if excluded else None

    def _is_excluded(self, folded: str, f: Found) -> bool:
        if f.start < 25 and PRINT_STAMP.match(folded[:f.end + 8]):
            return True
        if self.excluded is None:
            return False
        before = folded[max(0, f.start - 30):f.start]
        return bool(self.excluded.search(before))

    def content_dates(self, folded: str) -> list[Found]:
        return [f for f in find_dates(folded) if not self._is_excluded(folded, f)]

    def primary(self, folded: str, type_labels: list[str], found: list[Found],
                head: int = 1500) -> tuple[date | None, str | None, int | None]:
        """Birincil içerik tarihi: önce türün etiketleri, sonra genel etiketler,
        sonra baş bölgede en sık geçen, sonra ilk tarih. (tarih, kaynak, konum)"""
        if not found:
            return None, None, None
        labels = [(l, re.compile(fold_pattern(l) + r"\W{0,6}")) for l in type_labels]
        labels += [(p.pattern, p) for p in self.generic]
        for name, rx in labels:
            for m in rx.finditer(folded):
                # etiketten sonraki 60 karakter içinde ilk tarih
                for f in found:
                    if m.end() - 1 <= f.start <= m.end() + 60:
                        return f.d, "etiket:" + _plain(name), f.start
                    if f.start > m.end() + 60:
                        break
        in_head = [f for f in found if f.start < head]
        if in_head:
            counts: dict[date, int] = {}
            for f in in_head:
                counts[f.d] = counts.get(f.d, 0) + 1
            best = max(in_head, key=lambda f: (counts[f.d], -f.start))
            src = "bas_en_sik" if counts[best.d] > 1 else "bas_ilk"
            if src == "bas_ilk":
                best = in_head[0]
            return best.d, src, best.start
        return found[0].d, "metin_ilk", found[0].start


def _plain(p: str) -> str:
    return p.replace(r"\s*", " ").replace(r"\W{0,6}", "").replace("\\", "")


def academic_terms(folded: str, head: int = 1500) -> list[str]:
    """'2024-2025 Bahar' gibi akademik dönem ifadeleri (baş bölgeden)."""
    out = []
    for m in ACADEMIC.finditer(folded[:head]):
        a, b = int(m.group(1)), int(m.group(2))
        if b != a + 1:
            continue
        term = {"fall": "guz", "spring": "bahar", "summer": "yaz"}.get(m.group(3) or "", m.group(3) or "")
        s = f"{a}-{b}" + (f" {term}" if term else "")
        if s not in out:
            out.append(s)
    return out


def term_year(term: str) -> int | None:
    """Akademik dönemin düştüğü takvim yılı: güz -> ilk yıl, bahar/yaz -> ikinci yıl."""
    m = re.match(r"(\d{4})-(\d{4})(?: (\w+))?", term)
    if not m or not m.group(3):
        return None
    return int(m.group(1)) if m.group(3) == "guz" else int(m.group(2))
