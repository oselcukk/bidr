"""Sayfa yapısından iki tespit (model yok, yalnız metin):

1. **Parça grubu.** Tek bir belgenin bölünmüş parçaları (ör. `tutanak-1.pdf` s.1-3,
   `tutanak-2.pdf` s.4-6) ayrı dosyalar olarak gelir. B, A'nın devamıdır: B'nin ilk sayfa
   numarası A'nın son sayfa numarasının bir fazlası VE en az bir destek belirtisi: aynı toplam
   sayfa ("Sayfa 4/6" ↔ "Sayfa 3/6"), aynı üst bilgi satırı (A'nın son, B'nin ilk sayfasının
   üst satırları) ya da yüksek sözcük benzerliği. Dosya adına bakılmaz. Zincirlenen parçalar
   `parca_grubu` (`pg-<en küçük doc_id>`) ve `parca_sira` (1..k) alır.
2. **Birden çok belge şüphesi.** Birleştirilmiş PDF'te (ör. tutanak + ders izlencesi) bir
   sayfada yeni belge başlıyor olabilir: sayfa numarası 1'e döner (öncesi numaralıyken) ya da
   üst bilgi tamamen değişir, sayfada başlık gibi bir satır vardır ve iki bölümün sözcükleri
   neredeyse hiç örtüşmez. Bu turda yalnız işaret: `coklu_belge_suphesi` = yeni belgenin
   başladığı sayfalar (`3;7`); bölme yapılmaz.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter

# "Sayfa 3/10", "Sayfa 3 / 10", "Page 3 of 10", "Sayfa: 3", "3/10" (satırda tek), "- 3 -"
_NUM_TOTAL = re.compile(r"\b(?:sayfa|page|sf)\s*(?:no)?\s*[:.]?\s*(\d{1,4})\s*(?:/|of|-|\()\s*(\d{1,4})\b", re.I)
_NUM_ONLY = re.compile(r"\b(?:sayfa|page)\s*(?:no)?\s*[:.]?\s*(\d{1,4})\b", re.I)
_LINE_TOTAL = re.compile(r"^\s*(\d{1,4})\s*/\s*(\d{1,4})\s*$")
_LINE_BARE = re.compile(r"^\s*[-–]?\s*(\d{1,4})\s*[-–]?\s*$")
_TOK = re.compile(r"[a-z]{4,}")

HEAD_LINES = 3          # üst bilgi: sayfanın ilk birkaç dolu satırı
FOOT_LINES = 4
HEAD_MIN_LETTERS = 10   # kısa satırlar (tarih, numara) üst bilgi sayılmaz
SIM_SUPPORT = 0.25      # parça desteği: sözcük kümesi Jaccard benzerliği
MULTI_SIM_MAX = 0.08    # çoklu belge: iki bölümün sözcük benzerliği bunun altında
MULTI_MIN_ALNUM = 150   # her iki bölümde en az bu kadar harf/rakam
PAGED_METHODS = ("pdftotext", "ocr", "agent_vision")


def fold(s: str) -> str:
    s = s.replace("İ", "i").replace("I", "ı").lower()
    s = s.translate(str.maketrans("ıçğöşü", "icgosu"))
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def _lines(page: str) -> list[str]:
    return [ln.strip() for ln in page.split("\n") if ln.strip()]


def page_number(page: str) -> tuple[int | None, int | None]:
    """Sayfadaki sayfa numarası (ve varsa toplam): önce alt, sonra üst satırlar."""
    ls = _lines(page)
    if not ls:
        return None, None
    foot, head = ls[-FOOT_LINES:][::-1], ls[:HEAD_LINES]
    for zone, bare in ((foot, True), (head, False)):
        for k, ln in enumerate(zone):
            m = _NUM_TOTAL.search(ln) or _LINE_TOTAL.match(ln)
            if m:
                a, b = int(m.group(1)), int(m.group(2))
                if 0 < a <= b:
                    return a, b
            m = _NUM_ONLY.search(ln)
            if m and int(m.group(1)) > 0:
                return int(m.group(1)), None
            if bare and k < 2:
                m = _LINE_BARE.match(ln)
                if m and 0 < int(m.group(1)) < 1000:
                    return int(m.group(1)), None
    return None, None


def _head(page: str) -> set[str]:
    out = set()
    for ln in _lines(page)[:HEAD_LINES]:
        f = re.sub(r"[^a-z]+", " ", fold(ln)).strip()
        if sum(c.isalpha() for c in f) >= HEAD_MIN_LETTERS and page_number(ln) == (None, None):
            out.add(f)
    return out


def _toks(text: str) -> set[str]:
    return set(_TOK.findall(fold(text)))


def _jac(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


class Paged:
    """Bir belgenin sayfa numaralaması ve üst bilgisi."""

    def __init__(self, did: str, pages: list[str]):
        self.did = did
        self.pages = pages
        self.nums = [page_number(p) for p in pages]
        offs = Counter(n - i for i, (n, _) in enumerate(self.nums) if n is not None)
        self.first = self.last = self.total = None
        if offs:
            off, c = offs.most_common(1)[0]
            found = sum(offs.values())
            if c * 2 >= found:          # numaralar tutarlı (çoğunluk aynı kayma)
                self.first = 1 + off
                self.last = len(pages) + off
                tots = Counter(t for _, t in self.nums if t)
                self.total = tots.most_common(1)[0][0] if tots else None
        self.head_first = _head(pages[0]) if pages else set()
        self.head_last = _head(pages[-1]) if pages else set()
        self._toks: set[str] | None = None

    @property
    def toks(self) -> set[str]:
        if self._toks is None:
            self._toks = _toks("\n".join(self.pages))
        return self._toks


def continues(a: Paged, b: Paged) -> tuple[bool, str]:
    """B, A'nın devamı mı? (karar, gerekçe)"""
    if a.last is None or b.first is None or b.first != a.last + 1 or b.first < 2:
        return False, ""
    if a.total and b.total:
        if a.total != b.total:
            return False, ""
        return True, "sayfa_no+toplam"
    if a.total and b.last and b.last > a.total:
        return False, ""
    if a.head_last & b.head_first:
        return True, "sayfa_no+ust_bilgi"
    if _jac(a.toks, b.toks) >= SIM_SUPPORT:
        return True, "sayfa_no+benzerlik"
    return False, ""


def part_groups(docs: dict[str, list[str]]) -> dict[str, dict]:
    """doc_id -> {grup, sira, gerekce}; tek başına olanlar dahil edilmez.

    `docs`: doc_id -> sayfa metinleri (yalnız sayfa yapısı olan belgeler)."""
    paged = {d: Paged(d, ps) for d, ps in docs.items() if ps}
    by_first: dict[int, list[Paged]] = {}
    for p in paged.values():
        if p.first is not None and p.first >= 2:
            by_first.setdefault(p.first, []).append(p)
    nxt: dict[str, tuple[str, str]] = {}
    prev: dict[str, str] = {}
    pref = {"sayfa_no+toplam": 0, "sayfa_no+ust_bilgi": 1, "sayfa_no+benzerlik": 2}
    for a in sorted(paged.values(), key=lambda p: p.did):
        if a.last is None:
            continue
        cands = []
        for b in by_first.get(a.last + 1, []):
            if b.did == a.did or b.did in prev:
                continue
            ok, why = continues(a, b)
            if ok:
                cands.append((pref[why], -_jac(a.toks, b.toks), b.did, why))
        if cands:
            _, _, bd, why = min(cands)
            nxt[a.did] = (bd, why)
            prev[bd] = a.did
    out: dict[str, dict] = {}
    for d in sorted(paged):
        if d in prev or d not in nxt:
            continue
        chain, why = [d], []
        seen = {d}
        while chain[-1] in nxt and nxt[chain[-1]][0] not in seen:
            bd, w = nxt[chain[-1]]
            chain.append(bd)
            seen.add(bd)
            why.append(w)
        gid = "pg-" + min(chain)
        for k, x in enumerate(chain, 1):
            out[x] = {"grup": gid, "sira": k, "uyeler": [y for y in chain if y != x],
                      "gerekce": ", ".join(sorted(set(why)))}
    return out


_TITLE_HINT = re.compile(r"(tutanag|izlence|syllabus|rapor|plan|form|karar|yonerge|yonetmelik|protokol|"
                         r"duyuru|program|listesi|cizelge|degerlendirme|anket|bilgi paketi|course)")


def _titleish(page: str) -> bool:
    for ln in _lines(page)[:6]:
        letters = [c for c in ln if c.isalpha()]
        if len(letters) >= 8 and (sum(c.isupper() for c in letters) / len(letters) >= 0.6
                                  or _TITLE_HINT.search(fold(ln))):
            return True
    return False


def _alnum(s: str) -> int:
    return sum(c.isalnum() for c in s)


def multi_doc_starts(pages: list[str]) -> list[tuple[int, str]]:
    """Yeni belgenin başladığından kuşkulanılan sayfalar (1 tabanlı) ve gerekçe."""
    if len(pages) < 2:
        return []
    nums = [page_number(p) for p in pages]
    heads = [_head(p) for p in pages]
    out: list[tuple[int, str]] = []
    seg = 0
    for j in range(1, len(pages)):
        why = ""
        n, _ = nums[j]
        before = [x for x, _ in nums[seg:j] if x is not None]
        if n == 1 and before and max(before) >= 1:
            why = "sayfa_no_yeniden_1"
        else:
            run_head = set().union(*heads[seg:j])
            a_txt, b_txt = "\n".join(pages[seg:j]), "\n".join(pages[j:j + max(1, j - seg)])
            if (heads[j] and run_head and not (heads[j] & run_head) and _titleish(pages[j])
                    and _alnum(a_txt) >= MULTI_MIN_ALNUM and _alnum(b_txt) >= MULTI_MIN_ALNUM
                    and _jac(_toks(a_txt), _toks(b_txt)) < MULTI_SIM_MAX):
                why = "konu_ve_baslik_degisti"
        if why:
            out.append((j + 1, why))
            seg = j
    return out


def merge_into_versions(groups: dict[str, dict], parts: dict[str, str | None]) -> dict[str, dict]:
    """identify'ın sürüm gruplarına (`bidr.identify.versions.group` çıktısı) envanterin parça
    gruplarını (`parca_grubu`) katar: aynı parça grubundaki belgeler ve onların sürüm grubu
    üyeleri tek grupta toplanır; kimlik `sg-<en küçük doc_id>` (sürüm grubuyla aynı biçim), böylece
    dosyalama (`bidr/file/select.py`, `surum_grubu`) onları aynı ölçütte tek kanıt sayar.
    Benzerlik parça bağında bilinmez (sürüm bağı yoksa None)."""
    by_part: dict[str, list[str]] = {}
    for d, g in parts.items():
        if g:
            by_part.setdefault(g, []).append(d)
    if not any(len(v) > 1 for v in by_part.values()):
        return groups
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for d, g in groups.items():
        for m in g["uyeler"]:
            parent[find(d)] = find(m)
    for mem in by_part.values():
        for m in mem[1:]:
            parent[find(mem[0])] = find(m)
    comps: dict[str, list[str]] = {}
    for x in list(parent):
        comps.setdefault(find(x), []).append(x)
    out: dict[str, dict] = {}
    for mem in comps.values():
        if len(mem) < 2:
            continue
        gid = "sg-" + min(mem)
        for m in mem:
            old = groups.get(m)
            out[m] = {"grup": gid, "uyeler": sorted(x for x in mem if x != m),
                      "benzerlik": old["benzerlik"] if old else None}
    return out
