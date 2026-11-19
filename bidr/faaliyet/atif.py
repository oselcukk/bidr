"""Belgeler arası "dayanır" bağı: yalnız belge metnindeki AÇIK göndermeden (belirleyici, model yok).

İki gönderme türü tanınır (katlanmış metinde):

1. **Sayı göndermesi** (`sayi`): "27.01.2025 tarih ve E.184506 sayılı yazısı" → kendi başlığında
   aynı tarih ve aynı evrak sayısını taşıyan belge(ler) ("Sayı : E-…-184506" + belge tarihi ya da
   "Evrak Tarih ve Sayısı: 27.01.2025-E.184506"). Tarih VE sayının son rakam öbeği birlikte
   eşleşmelidir; aynı yazının kopyaları hepsi hedef olur.
2. **Ad göndermesi** (`ad`): "<faaliyet adı> (kararı|görüşleri|sonuçları…) doğrultusunda /
   sonucunda / üzerine / uyarınca / istinaden" → adı bu ifadeyle karşılıklı örtüşen (en az iki
   ayırt edici sözcük) faaliyet kaydı; kaydın tarihi kaynak belgeden önce ve `AD_PENCERE` gün
   içinde olmalı, böyle TEK kayıt olmalı. Birden çok aday varsa bağ kurulmaz (tahmin yok),
   not düşer.

Bağlar zaman yönlüdür (gönderilen önce gelir); zincir (`reach`) bu yüzden döngüsüzdür.
"""
from __future__ import annotations

import re
from collections import deque
from datetime import date, timedelta

from .group import _word_match, fold

AD_PENCERE = 180                 # ad göndermesi: kaynak belgeden en çok bu kadar gün önceki faaliyet
DERINLIK = 4                     # zincirde en çok bu kadar bağ
BASLIK = 2500                    # belgenin kendi sayısı başlıkta aranır (ilk karakterler)

_DATE = r"(\d{1,2})\s*[./]\s*(\d{1,2})\s*[./]\s*(\d{4})"
_NO = r"([a-z]{0,3}\s*[.\-]?\s*\d[\w./\-]*\d|\d)"
CITE = re.compile(_DATE + r"\s+tarih\w*\s+(?:ve|ile)\s+(?:sayi\w*\s*:?\s*)?" + _NO + r"\s+sayil")
OWN_EVRAK = re.compile(r"evrak\s+tarih\w*\s+ve\s+sayisi\s*:?\s*" + _DATE + r"\s*-\s*" + _NO)
OWN_SAYI = re.compile(r"\bsayi\s*:\s*" + _NO)
OWN_DATE = re.compile(_DATE)
CONNECTOR = re.compile(r"\b(?:dogrultusunda|sonucunda|sonuclarina\s+gore|uzerine|uyarinca|istinaden)\b")
# Gönderilen şeyin türünü söyleyen sözcükler (ifadenin sonunda atılır).
TUR_SOZ = ("karar", "gorus", "sonuc", "degerlendirme", "toplanti", "tutanag", "yazi", "rapor", "oneri",
           "talep", "bulgu")
# Faaliyet adında ayırt edici olmayan sözcükler.
GENEL_AD = ("toplanti", "olagan", "olaganustu")
BIRIM_AD = ("bolum", "birim")
WORD = re.compile(r"[a-z]+|\d+")
# katlamadan önce hızlı ön süzgeç (özgün metinde, büyük/küçük harf duyarsız)
ON_CITE = re.compile(r"say[ıi]l[ıi]", re.I)
ON_CONN = re.compile(r"do[ğg]rultusunda|sonucunda|sonu[çc]lar[ıi]na|[üu]zerine|uyar[ıi]nca|istinaden", re.I)


_CH: dict[str, str] = {}


def folded_map(text: str) -> tuple[str, list[int] | None]:
    """(katlanmış metin, katlanmış karakter → özgün konum; uzunluk korunduysa None = birebir)."""
    text = text or ""
    ft = fold(text)
    if len(ft) == len(text):
        return ft, None
    out, idx = [], []
    for i, ch in enumerate(text):
        c = _CH.get(ch)
        if c is None:
            c = _CH[ch] = fold(ch)
        out.append(c)
        idx.extend([i] * len(c))
    return "".join(out), idx


def _iso(d: str, m: str, y: str) -> str | None:
    try:
        return date(int(y), int(m), int(d)).isoformat()
    except ValueError:
        return None


def _num(tok: str) -> str | None:
    g = re.findall(r"\d+", tok or "")
    return g[-1].lstrip("0") or "0" if g else None


_SENT_END = re.compile(r"[.!?](?=\s|$)|\n\s*\n")


def _excerpt(text: str, idx: list[int] | None, a: int, b: int, n: int = 300) -> str:
    """Eşleşmeyi içeren cümle (önceki/sonraki cümle sonundan), boşlukları sıkıştırılmış."""
    s = idx[a] if idx and a < len(idx) else min(a, len(text))
    e = (idx[b - 1] + 1 if b - 1 < len(idx) else len(text)) if idx else min(b, len(text))
    lo = max(0, s - 400)
    starts = [m.end() for m in _SENT_END.finditer(text, lo, s)]
    s = starts[-1] if starts else lo
    m = _SENT_END.search(text, e)
    e = m.end() if m and m.start() - e < 400 else min(len(text), e + 200)
    out = " ".join(text[s:e].split())
    return out if len(out) <= n else out[:n - 1] + "…"


def own_numbers(text: str, tarih: str | None) -> set[tuple[str, str]]:
    """Belgenin kendi (tarih, evrak sayısı) çiftleri (başlıktan)."""
    ft = fold(text or "")[:BASLIK]
    out = set()
    for m in OWN_EVRAK.finditer(ft):
        d, n = _iso(m[1], m[2], m[3]), _num(m[4])
        if d and n:
            out.add((d, n))
    dates = {tarih} if tarih else set()
    if not dates:
        dates = {d for m in OWN_DATE.finditer(ft) if (d := _iso(m[1], m[2], m[3]))}
    for m in OWN_SAYI.finditer(ft):
        n = _num(m[1])
        if n and len(n) >= 3:            # kısa sayı (sayfa/madde) belge kimliği değildir
            out.update((d, n) for d in dates)
    return out


def citations(text: str) -> list[tuple[str, str, str]]:
    """Metindeki "<tarih> tarih ve <sayı> sayılı" göndermeleri: [(tarih, sayı, alıntı)]."""
    if not ON_CITE.search(text or ""):
        return []
    ft, idx = folded_map(text)
    out = []
    for m in CITE.finditer(ft):
        d, n = _iso(m[1], m[2], m[3]), _num(m[4])
        if d and n:
            out.append((d, n, _excerpt(text, idx, m.start(), m.end())))
    return out


def _strip_tail(words: list[str]) -> list[str]:
    while words and any(words[-1].startswith(t) for t in TUR_SOZ):
        words = words[:-1]
    return words


def named_refs(text: str) -> list[tuple[list[list[str]], str]]:
    """Bağlaçtan ("doğrultusunda" …) önceki ifadeler: [(sözcük listeleri (ve/virgülle ayrık), alıntı)]."""
    if not ON_CONN.search(text or ""):
        return []
    ft, idx = folded_map(text)
    out = []
    for m in CONNECTOR.finditer(ft):
        lo = max(0, m.start() - 160)
        pre = re.split(r"[.;:]|\n\s*\n", ft[lo:m.start()])[-1]
        segs = []
        for seg in re.split(r",|\bve\b|\bile\b", pre):
            raw = WORD.findall(seg)
            w = _strip_tail(raw)
            if w and len(w) < len(raw):       # ifade gönderilen şeyin türüyle biter ("… kararı")
                segs.append(w[-6:])
        if segs:
            out.append((segs, _excerpt(text, idx, m.start() - len(pre), m.end())))
    return out


def name_cores(ad: str) -> list[frozenset]:
    """Faaliyet adının ayırt edici sözcük kümeleri (en az iki sözcük): tam hali ve birim sözcüğü
    ("Bölüm …") atılmış hali."""
    w = [x for x in WORD.findall(fold(ad)) if not x.isdigit() and x not in ("ve", "ile", "icin")
         and not any(x.startswith(g) for g in GENEL_AD)]
    cores = []
    for c in (w, [x for x in w if not any(x.startswith(b) for b in BIRIM_AD)]):
        s = frozenset(c)
        if len(s) >= 2 and s not in cores:
            cores.append(s)
    return cores


def _plural(w: str, stem_len: int) -> bool:
    return bool(re.match(r"l[ae]r", w[stem_len:]))


def _wm(x: str, y: str) -> bool:
    """Sözcük eşleşmesi; ifadedeki çoğul ("kurulların") tekil addaki sözcüğe uymaz (genel anma)."""
    if not _word_match(x, y):
        return False
    n = 0
    while n < min(len(x), len(y)) and x[n] == y[n]:
        n += 1
    return not (_plural(x, n) and not _plural(y, n))


def _same(words: list[str], core: frozenset) -> bool:
    """İfadenin son |core| sözcüğü ile çekirdek karşılıklı örtüşür."""
    tail = words[-len(core):]
    return (len(tail) == len(core) and all(any(_wm(x, y) for y in core) for x in tail)
            and all(any(_wm(x, y) for x in tail) for y in core))


def _d(s: str | None) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10]) if s and len(str(s)) >= 10 else None
    except ValueError:
        return None


def links(docs: dict[str, dict], kayitlar: list[dict]) -> tuple[list[dict], list[str]]:
    """docs: {doc_id: {"text", "tarih"}}; kayitlar: faaliyetler.json `faaliyetler`.
    → (bağlar [{kaynak, hedef: [doc_id], faaliyet, tur, atif}], notlar)."""
    own: dict[tuple[str, str], list[str]] = {}
    for did, d in sorted(docs.items()):
        for k in own_numbers(d.get("text") or "", d.get("tarih")):
            own.setdefault(k, []).append(did)
    rec_dates = []
    for k in kayitlar:
        t = _d(k.get("tarih")) or _d((k.get("tarih_araligi") or [None])[0])
        cores = [c for a in dict.fromkeys([k.get("ad") or "", *(k.get("adlar") or [])]) for c in name_cores(a)]
        if t and cores:
            rec_dates.append((k, t, cores))
    out, notlar = [], []
    for did, d in sorted(docs.items()):
        text = d.get("text") or ""
        if not text:
            continue
        seen = set()
        for t, n, ex in citations(text):
            hedef = [x for x in own.get((t, n), []) if x != did]
            if hedef and (t, n) not in seen:
                seen.add((t, n))
                out.append({"kaynak": did, "hedef": hedef, "faaliyet": None, "tur": "sayi", "atif": ex})
        src = _d(d.get("tarih"))
        if src is None:
            continue
        for segs, ex in named_refs(text):
            for words in segs:
                cands = [k for k, t, cores in rec_dates
                         if src - timedelta(days=AD_PENCERE) <= t <= src
                         and did not in {b.get("doc_id") for b in k.get("belgeler") or []}
                         and any(_same(words, c) for c in cores)]
                if len(cands) == 1:
                    k = cands[0]
                    if k.get("id") in seen:
                        continue
                    seen.add(k.get("id"))
                    out.append({"kaynak": did, "hedef": sorted(b["doc_id"] for b in k.get("belgeler") or []),
                                "faaliyet": k.get("id"), "tur": "ad", "atif": ex})
                elif len(cands) > 1:
                    notlar.append(f"{did}: \"{' '.join(words)}\" göndermesine uyan {len(cands)} faaliyet "
                                  f"({', '.join(sorted(str(k.get('id')) for k in cands))}); bağ kurulmadı")
    return out, notlar


def reach(baglar: list[dict], start: str, derinlik: int = DERINLIK) -> dict[str, list[dict]]:
    """start'ın (doğrudan ya da dolaylı) dayandığı belgeler: {doc_id: bağ yolu}."""
    fw: dict[str, list[dict]] = {}
    for b in baglar:
        fw.setdefault(b["kaynak"], []).append(b)
    got: dict[str, list[dict]] = {}
    q = deque([(start, [])])
    while q:
        cur, path = q.popleft()
        if len(path) >= derinlik:
            continue
        for b in fw.get(cur, []):
            for h in b["hedef"]:
                if h != start and h not in got:
                    got[h] = path + [b]
                    q.append((h, path + [b]))
    return got
