"""Belge başlığı ve içerikten türetilen çalışma adı."""
from __future__ import annotations

import re

from .classify import Doc
from .text import slug, tr_title

_CAPS_RUN = re.compile(r"\s(?:[A-ZÇĞİÖŞÜ]{3,}[.,]?\s+){1,}[A-ZÇĞİÖŞÜ]{3,}")


def _cut(doc: Doc, start: int, end: int) -> str:
    return doc.text[start:end].strip(" :;,-|")


def _konu(doc: Doc) -> str | None:
    m = re.search(r"\bkonu ?: ?", doc.folded[:2000])
    if not m:
        return None
    s = doc.text[m.end():m.end() + 160]
    c = _CAPS_RUN.search(s)
    if c and c.start() > 3:
        s = s[:c.start()]
    s = re.split(r"\s(?:İlgi|Ilgi|ilgi)\s?:|\sSayın\s|\sEkler\s?:|\sDear\s|\sDeğerli\s|\sMerhaba",
                 s)[0]
    return s.strip(" :;,-") or None


def _email_subject(doc: Doc) -> str | None:
    k = _konu(doc)
    if k:
        return k
    m = re.search(r"outlook\s+(.{3,140}?)\s+kimden\b", doc.folded[:800])
    if m:
        return _cut(doc, m.start(1), m.end(1))
    return None


def _session(doc: Doc) -> str | None:
    m = re.search(r"(toplanti|oturum) sayisi ?: ?(?:oturum sayisi ?: ?)?(?:\d\d\.\d\d\.\d{4} )?(\d{2,4} ?/ ?\d{1,3})",
                  doc.folded[:1500])
    return m.group(2).replace(" ", "") if m else None


_EXTRACT = {
    "ders_bilgi_formu": r"(?:ders bilgi formu ?\( ?([^)]{2,20}?) ?\)|ders adi ?: ?(.{3,60}?) ders kodu)",
    "etkinlik_duyurusu": r"etkinlik adi ?:? ?(.{3,100}?)(?= etkinlik tipi| a\. giris| icerik\b|$)",
    "faaliyet_raporu": r"etkinlik adi ?: ?(.{3,100}?)(?= a\. giris|$)",
    "is_akisi": r"is akis adi ?: ?(.{3,100}?)(?= baslama|$)",
    "ders_izlencesi": r"(?:syllabus|ders izlencesi)\W{0,3}(.{3,60}?)(?= semester| instructors?| donem|$)",
}

_PREFIX = {"resmi_yazi": "Yazi", "e_posta": "Eposta"}


def _from_evidence(doc: Doc, ev: list[dict]) -> str | None:
    heads = [e for e in ev if e.get("tur") == "baslik" and e.get("konum") is not None and e["agirlik"] > 0]
    if not heads:
        return None
    e = max(heads, key=lambda e: (e["agirlik"], -e["konum"]))
    a = e["konum"]
    b = a + e.get("uzunluk", 20)
    # büyük harfli başlıksa sağa doğru büyük harfli sözcükler bitene dek uzat
    seg = doc.text[a:b]
    if seg.upper() == seg:
        m = re.match(r"(?:[A-ZÇĞİÖŞÜ0-9()\-–/&.,']+\s?){1,12}", doc.text[b:b + 120])
        if m:
            b += len(m.group(0))
    # baştaki sayfa/yazdırma damgası, zaman vb. temizlik
    return _cut(doc, a, b)


def title(doc_type: str, doc: Doc, evidence: list[dict]) -> str | None:
    t: str | None = None
    if doc_type == "olcut_aciklama_taslagi":
        m = re.search(r"\[([a-e]\.\d\.\d)-", doc.folded)
        if m:
            t = f"{m.group(1).upper()} Ölçüt Açıklaması"
    elif doc_type == "akts_bilgi_paketi":
        start = doc.folded.find("akademik programlar")
        seg = doc.folded[max(start, 0):max(start, 0) + 600]
        hits = []
        for rx in (r"ders bilgi formu ?\( ?[^)]{2,15}\)", r"ders katalogu", r"program ciktilari matrisi",
                   r"diploma eki", r"tyyc .{0,60}?yeterlilikleri", r"program ogrenme ciktilari"):
            m = re.search(rx, seg)
            if m:
                hits.append((m.start(), m.end()))
        if hits:
            a0, b0 = min(hits)
            off = max(start, 0)
            t = "Bilgi Paketi " + _cut(doc, off + a0, off + b0)
    elif doc_type == "resmi_yazi":
        t = _konu(doc)
    elif doc_type == "e_posta":
        t = _email_subject(doc)
    elif doc_type in _EXTRACT:
        m = re.search(_EXTRACT[doc_type], doc.folded[:2500])
        if m:
            g = next(i for i in range(1, (m.lastindex or 0) + 1) if m.group(i)) if m.lastindex else 0
            t = _cut(doc, m.start(g), m.end(g))
    if not t:
        t = _from_evidence(doc, evidence)
    if t and doc_type.endswith("_karari"):
        s = _session(doc)
        if s and s not in t:
            t = f"{t} {s}"
    if not t:
        t = first_line(doc.raw)
    if not t:
        return None
    t = re.sub(r"\s+", " ", t).strip()
    return tr_title(t[:140])


def first_line(raw: str) -> str | None:
    for line in raw.splitlines():
        line = line.strip(" \t\f|[]")
        if line.startswith(("üstbilgi]", "altbilgi]", "sayfa:")):
            continue
        if sum(c.isalpha() for c in line) >= 4:
            return line[:100]
    return None


def working_name(date_iso: str | None, doc_type: str, label: str, t: str | None) -> str:
    base = slug(t or label) or slug(label) or "Belge"
    pre = _PREFIX.get(doc_type)
    if pre and not base.lower().startswith(pre.lower()):
        base = f"{pre}-{base}"
    return f"{date_iso or 'tarihsiz'}_{base}"
