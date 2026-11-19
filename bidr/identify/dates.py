"""İçerik tarihlerini bul (katlanmış metin üzerinde).

Form künyesi tarihleri (Yayın/Değişiklik/Revizyon Tarihi) ve sayfa başındaki
yazdırma damgaları içerik tarihi sayılmaz.

Dönem kuralının (bidr/audit/donem.py) kullandığı ek bilgiler:
- `date_ranges`: "01.03.2025 | 01.03.2027" gibi başlangıç–bitiş çiftleri (proje, sözleşme,
  görevlendirme). Bitiş tarihi belgenin dönemini belirlemez; birincil tarih seçiminde de
  kullanılmaz.
- `plan_span`: baş bölgede "2022-2026 Stratejik Planı" gibi çok yıllı yürürlük aralığı.
- `year_phrases`: "2025 yılı içerisinde", "2025 yılında" gibi açık takvim yılı ifadeleri.
- `update_dates`: web sayfası "Son güncelleme: …" damgası (içerik tarihi değil; sayfanın
  kopyalandığı hâlin tarihi).
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
ACADEMIC = re.compile(r"\b(20\d\d) ?[-/] ?(20\d\d)\b(?:.{0,25}?\b(guz|bahar|yaz|fall|spring|summer)\b)?")
PRINT_STAMP = re.compile(r"^\W{0,3}\d{1,2}[./]\d{1,2}[./]\d{4},? \d{1,2}:\d{2}")
# iki tarih arasında aralık ayracı: boşluk, tablo çizgisi, tire, OCR'ın bıraktığı köşeli/yuvarlak
# ayraç ya da "ile"/"to"/"until"
RANGE_GAP = re.compile(r"^[\s|\-\u2013\u2014/\[\]()]*(?:ile|to|until|tarihleri arasinda)?[\s|\-\u2013\u2014\[\]()]*$")
END_LABEL = re.compile(r"(?:bitis|bitme|sona erme|end)(?: tarihi| date)?\W{0,6}$")
SPAN = re.compile(r"(?<!\d)(20\d\d)\s*[-\u2013\u2014/]\s*(20\d\d)(?!\d)")
SPAN_WORD = re.compile(r"plan|strateji")
YEAR_PHRASE = re.compile(
    r"(?<![\d./-])((?:19|20)\d\d) (?:takvim )?yil(?:i icerisinde|i icinde|i boyunca|inda|ina ait"
    r"|i sonu|i itibariyla|i itibari ile|i faaliyet|i verileri|i raporu|i ocak|i \w+ donemi)")
UPDATE_LABEL = re.compile(r"(?:son guncelleme(?: tarihi)?|guncelleme tarihi|last updated?|last modified)\W{0,8}$")

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


def date_ranges(folded: str, found: list[Found] | None = None) -> list[tuple[Found | None, Found]]:
    """Başlangıç–bitiş çiftleri: yalnız ayraçla (en çok 12 karakter) ayrılmış ardışık iki tarih (ikincisi daha geç,
    en çok 10 yıl sonra) ya da "bitiş tarihi" etiketinden sonraki tarih (başlangıcı None)."""
    found = find_dates(folded) if found is None else found
    out: list[tuple[Found | None, Found]] = []
    used: set[int] = set()
    for a, b in zip(found, found[1:]):
        gap = folded[a.end:b.start]
        if (len(gap) <= 12 and "\n" not in gap and RANGE_GAP.match(gap) and a.d < b.d
                and b.d.year - a.d.year <= 10):
            out.append((a, b))
            used.add(b.start)
    for f in found:
        if f.start not in used and END_LABEL.search(folded[max(0, f.start - 25):f.start]):
            out.append((None, f))
    return out


def plan_span(folded: str, head: int = 1500) -> tuple[int, int] | None:
    """Baş bölgede çok yıllı yürürlük aralığı ("2022-2026 Stratejik Planı", "Stratejik Plan
    (2022–2026)"): yanında 40 karakter içinde plan/strateji geçen ilk 2–10 yıllık aralık.
    Akademik yıl (2024-2025) ve program dönemi ("Erasmus+ 2021-2027") değildir."""
    part = folded[:head]
    for m in SPAN.finditer(part):
        a, b = int(m.group(1)), int(m.group(2))
        if 2 <= b - a <= 10 and SPAN_WORD.search(part[max(0, m.start() - 40):m.end() + 40]):
            return a, b
    return None


def year_phrases(folded: str) -> list[int]:
    """Metindeki açık takvim yılı ifadelerinin yılları ("2025 yılı içerisinde", "2025 yılında"),
    sıklığa göre azalan, eşitlikte ilk geçene göre."""
    counts: dict[int, int] = {}
    for m in YEAR_PHRASE.finditer(folded):
        y = int(m.group(1))
        if MIN_YEAR <= y <= MAX_YEAR:
            counts[y] = counts.get(y, 0) + 1
    return sorted(counts, key=lambda y: -counts[y])


def update_dates(folded: str, found: list[Found] | None = None) -> list[date]:
    """'Son güncelleme: 11 Kasım 2026' gibi sayfa güncelleme damgalarının tarihleri."""
    found = find_dates(folded) if found is None else found
    return sorted({f.d for f in found if UPDATE_LABEL.search(folded[max(0, f.start - 30):f.start])})


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
        # Türün kendi etiketleri künye tarihlerini de okuyabilir (ör. yönergede
        # revizyon tarihi asıl tarihtir); genel etiketler yalnız içerik tarihlerini.
        every = find_dates(folded)
        labels = [(l, re.compile(fold_pattern(l) + r"\W{0,6}"), every) for l in type_labels]
        labels += [(p.pattern, p, found) for p in self.generic]
        for name, rx, pool in labels:
            for m in rx.finditer(folded):
                # etiketten sonraki 60 karakter içinde ilk tarih
                for f in pool:
                    if m.end() - 1 <= f.start <= m.end() + 60:
                        return f.d, "etiket:" + _plain(name), f.start
                    if f.start > m.end() + 60:
                        break
        # Etiketsiz seçimde aralık bitişleri (proje/sözleşme bitişi) ve belgenin kendi yürürlük
        # aralığının çok dışındaki anılan tarihler ("4 Kasım 2014'te kuruldu" gibi; 2022-2026
        # planında) birincil tarih olamaz.
        ends = {b.start for _, b in date_ranges(folded, every)}
        span = plan_span(folded, head)
        found = [f for f in found if f.start not in ends
                 and (span is None or span[0] - 3 <= f.d.year <= span[1])]
        if not found:
            return None, None, None
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
