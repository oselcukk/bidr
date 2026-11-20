"""Birleşik/derleme belgenin parçaları (model yok, yalnız metin): sayfa aralıkları, parça tarihi
ve alıntının geldiği parça.

Birleştirilmiş PDF'te (e-posta + 2020 tarihli yazı + 2025 tarihli yazı) belgenin tek tarihi bütün
parçalara uygulanırsa 2020 yazısı 2025 sayılır. Parça sınırları sayfa başlarından okunur:

- `ingest`: yeni belgenin başladığı sayfa (`bidr.ingest.parts.multi_doc_starts`: sayfa numarası
  1'e döner ya da üst bilgi ve konu tamamen değişir; ingest'in `coklu_belge_suphesi` işaretiyle
  aynı hesap, güncel metin üzerinde);
- `kod`: sayfa başındaki doküman/form kodu değişir (belgede birden çok farklı kod varsa);
- `baslik`: sayfa başında tarihli resmî üst bilgi (EBYS "Evrak Tarih ve Sayısı", "Sayı: … Konu:"
  yazı başlığı, e-posta "Kimden … Tarih") var ve tarihi parçanın önceki üst bilgisinden farklı
  (aynı EBYS yazısının her sayfasındaki damga yeni parça açmaz). "Toplantı Tarihi:" da üst bilgidir.

Parça tarihi identify'ın belge tarihiyle aynı hesapla (`DateFinder.primary` vb.) yalnız parçanın
sayfalarından çıkarılır (`documents.jsonl` `parcalar`). Dönem kuralı (bidr/audit/donem.py) eşleşme
başına alıntının parçasının tarih alanlarını kullanır (`part_view`). Parçanın tarihi emin değilse
(tarih yok; ya da sınır yalnız ingest'in "konu değişti" sezgisinden ve tarih etiketsiz) ya da
alıntı metinde bulunamazsa belge tarihi kalır, satır `tarih_dogrulanmali` işareti alır.
"""
from __future__ import annotations

import re
from functools import lru_cache

from .dates import find_dates
from .text import collapse, fold

# -- sayfa başı doküman kodu ------------------------------------------------------------------

_KOD = re.compile(r"(?<![a-z0-9])([a-z]{2}) ?([-;:]?) ?(\d{3,4})(?!\d)")
# Kod yalnız künye bağlamında: önünde (40 karakter içinde) "doküman/document/form/dok/iş akış",
# ardında "yayın tarihi / date released" ya da kendisi tireli ve sıfır dolgulu (ÖR-0101, FR-0066).
# "na 2024 2025 bahar", "tarih ve 2026 06 03 sayılı", "proje no 126f399", ders kodu (ME 107),
# program kodu (PR 100) kod değildir.
_KOD_ONCE = re.compile(r"\b(?:dokuman|document|form|dok|is akis)\b")
_KOD_SONRA = re.compile(r"^\W{0,3}(?:ilk )?(?:yayin tarihi|date released|release date|publication date)")
_KOD_DEGIL = {"no", "ve", "md", "ek", "sy", "na", "tr"}
KOD_BOLGE = 400
LISTE_KOD = 2
_LISTE = re.compile(r"(?<![a-z0-9])[a-z]{2} ?- ?0\d{2,3}(?!\d)")


def page_code(page: str) -> str | None:
    """Sayfa başındaki doküman/form kodu (YÖ-0087 → "yo87", FR-0356 → "fr356") ya da None."""
    f = " ".join(re.sub(r"[^a-z0-9;:-]+", " ", fold(page[:KOD_BOLGE])).split())
    found: list[str] = []
    for m in _KOD.finditer(f):
        if m.group(1) in _KOD_DEGIL:
            continue
        if ((m.group(2) == "-" and m.group(3).startswith("0"))
                or _KOD_ONCE.search(f[max(0, m.start() - 40):m.start()])
                or _KOD_SONRA.match(f[m.end():m.end() + 30])):
            c = f"{m.group(1)}{int(m.group(3))}"
            if c not in found:
                found.append(c)
    # sayfa başında birden çok farklı kod ya da sayfanın tamamında LISTE_KOD+1 ve üstü farklı
    # tireli kod: doküman/form listesi ya da atıf (künye değil)
    if len(found) != 1:
        return None
    whole = set(_LISTE.findall(fold(page)))
    return found[0] if len(whole) <= LISTE_KOD else None


# -- tarihli üst bilgi ------------------------------------------------------------------------

BASLIK_BOLGE = 600
_UST = (re.compile(r"evrak tarih(?:i)? ve sayisi"),
        re.compile(r"\bsayi\s*:.{0,250}?\bkonu\s*:"),
        re.compile(r"\bkimden\b.{0,250}?\btarih\b"),
        re.compile(r"\btoplanti tarihi\b"))


def header_date(page: str) -> str | None:
    """Sayfa başındaki tarihli resmî üst bilginin tarihi (ISO) ya da None."""
    f = fold(collapse(page[:BASLIK_BOLGE * 2]))[:BASLIK_BOLGE]
    for rx in _UST:
        m = rx.search(f)
        if not m:
            continue
        ds = [x for x in find_dates(f) if x.start >= m.start()]
        if ds:
            return ds[0].d.isoformat()
    return None


# -- parça sınırları --------------------------------------------------------------------------

def pages_of(text: str) -> list[str]:
    return (text or "").split("\f")


def part_starts(pages: list[str]) -> list[tuple[int, str]]:
    """Parçaların başladığı sayfalar (0 tabanlı, ilk parça 0) ve sınırın kaynağı
    (ilk | ingest | kod | baslik). Tek sayfada [(0, "ilk")]."""
    from bidr.ingest.parts import multi_doc_starts
    n = len(pages)
    starts: dict[int, str] = {0: "ilk"}
    if n < 2:
        return [(0, "ilk")]
    for k, _ in multi_doc_starts(pages):
        if 1 <= k - 1 < n:
            starts.setdefault(k - 1, "ingest")
    codes = [page_code(p) for p in pages]
    if len({c for c in codes if c}) > 1:
        last = None
        for i, c in enumerate(codes):
            if c:
                if last is not None and c != last:
                    starts.setdefault(i, "kod")
                last = c
    cur = None
    for i, p in enumerate(pages):
        k = header_date(p)
        if i in starts:
            cur = k
        elif k:
            if cur is not None and k != cur:
                starts[i] = "baslik"
            cur = k
    return sorted(starts.items())


@lru_cache(maxsize=512)
def match_quote(quote: str, text: str):
    """`bidr.llm.quote.verify_quote` (aynı süreçte aynı alıntı/metin için bir kez)."""
    from bidr.llm.quote import verify_quote
    return verify_quote(quote, text)


@lru_cache(maxsize=64)
def text_parts(text: str) -> tuple[tuple[int, int, str], ...]:
    """`part_ranges` metin üzerinden (aynı süreçte metin başına bir kez)."""
    return tuple(part_ranges(pages_of(text)))


def part_ranges(pages: list[str]) -> list[tuple[int, int, str]]:
    """[(ilk sayfa, son sayfa, sınır kaynağı)], 0 tabanlı kapalı aralıklar."""
    st = part_starts(pages)
    out = []
    for j, (a, src) in enumerate(st):
        b = st[j + 1][0] - 1 if j + 1 < len(st) else len(pages) - 1
        out.append((a, b, src))
    return out


def quote_page(text: str, quote: str) -> int | None:
    """Alıntının geçtiği sayfa (0 tabanlı) ya da None (alıntı metinde tutmuyor)."""
    if not (quote and text):
        return None
    m = match_quote(quote, text)
    if not (m.ok and m.span):
        return None
    sp = m.span
    pos = 0
    for i, p in enumerate(pages_of(text)):
        end = pos + len(p)
        if sp[0] <= end:
            return i
        pos = end + 1
    return None


def part_of_page(ranges, page: int) -> int | None:
    """Sayfanın parça sırası (`ranges`: part_ranges ya da documents.jsonl `parcalar[].sayfa`,
    1 tabanlı [ilk, son]) ya da None."""
    for j, r in enumerate(ranges):
        if isinstance(r, dict):
            a, b = r["sayfa"][0] - 1, r["sayfa"][1] - 1
        else:
            a, b = r[0], r[1]
        if a <= page <= b:
            return j
    return None


# -- parça tarihi (identify) ------------------------------------------------------------------

# documents.jsonl'deki tarih alanları (parça kaydında da aynı adlarla; dönem kuralı bunları okur)
TARIH_ALANLARI = ("tarih", "tarih_kaynagi", "tarihler", "tarih_araligi", "akademik_donem",
                  "tarih_araliklari", "yururluk_araligi", "yil_ifadeleri", "guncelleme_tarihi",
                  "donem_ici", "donem_kaniti")


_DAMGA = re.compile(r"^\W{0,3}\d{1,2}[./]\d{1,2}[./]\d{4},? \d{1,2}:\d{2}")


def parts_record(pages: list[str], date_fields) -> list[dict]:
    """Birden çok parçalı belgede `parcalar` kaydı: [{sayfa: [ilk, son] (1 tabanlı), sinir, emin,
    <tarih alanları>}]; tek parçada []. `date_fields(raw) -> dict` identify'ın tarih hesabıdır.
    Sayfa başındaki yazdırma damgası ("21.01.2026 11:09") parça tarihi sayılmaz.
    `emin`: parçanın tarihi kendi künyesinden (etiketli tarih, ör. "Toplantı Tarihi:") ya da sınırı
    kesin (doküman kodu, tarihli üst bilgi) ve parçada tarih var. Ingest'in "konu değişti"
    sezgisiyle ayrılan ve tarihi etiketsiz (baş bölgede ilk/en sık, metindeki ilk) parça emin
    değildir: aynı belgenin devam sayfası olabilir."""
    rs = part_ranges(pages)
    if len(rs) < 2:
        return []
    out = []
    for a, b, src in rs:
        raw = "\n".join(_DAMGA.sub("", p.lstrip(), count=1) for p in pages[a:b + 1])
        f = date_fields(raw)
        rec = {"sayfa": [a + 1, b + 1], "sinir": src, **{k: f.get(k) for k in TARIH_ALANLARI}}
        etiket = str(rec.get("tarih_kaynagi") or "").startswith("etiket:")
        rec["emin"] = _has_date(rec) and (etiket or src in ("kod", "baslik") or bool(header_date(pages[a])))
        out.append(rec)
    return out


def _has_date(p: dict) -> bool:
    return bool(p.get("tarih") or p.get("akademik_donem") or p.get("yil_ifadeleri")
                or p.get("yururluk_araligi"))


def part_view(doc: dict, quote: str | None, text: str | None) -> dict | None:
    """Eşleşmenin dönem kararında kullanılacak parça bilgisi (dönem kuralına girdi):
    `{"alanlar": {tarih alanları}, "sayfa": [ilk, son], "dogrulanmali": bool, "not": str, "etiket": str}`.
    Parçasız belgede ya da metin verilmemişse None (belge tarihi; değişiklik yok). Parçanın
    tarihi emin değilse: belgeninkiyle aynıysa None; değilse (ya da alıntının parçası
    bulunamazsa) `alanlar` boş, `dogrulanmali` True: belge tarihi kalır, satır doğrulanmalı."""
    parts = doc.get("parcalar") or []
    if len(parts) < 2 or text is None:
        return None
    pg = quote_page(text, quote or "")
    j = part_of_page(parts, pg) if pg is not None else None
    if j is None:
        return {"alanlar": {}, "sayfa": None, "dogrulanmali": True,
                "not": "birleşik belge: alıntının parçası bulunamadı, belge tarihi kullanıldı"}
    p = parts[j]
    s = p["sayfa"]
    label = f"s. {s[0]}" if s[0] == s[1] else f"s. {s[0]}-{s[1]}"
    if p.get("emin"):
        return {"alanlar": {k: p.get(k) for k in TARIH_ALANLARI}, "sayfa": s, "dogrulanmali": False,
                "not": "", "etiket": f"parça {label}"}
    if p.get("tarih") and p.get("tarih") == doc.get("tarih"):
        return None
    why = "tarih yok" if not _has_date(p) else f"tarihi belirsiz ({p.get('tarih') or '?'})"
    return {"alanlar": {}, "sayfa": s, "dogrulanmali": True,
            "not": f"birleşik belge: alıntının parçasında ({label}) {why}, belge tarihi kullanıldı"}
