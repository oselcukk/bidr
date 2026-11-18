"""`verify_quote`: modelin "birebir" alıntısının belge metninde gerçekten geçtiğini denetler.

Karşılaştırma bir iskelet üzerinde yapılır: her iki tarafta
- Unicode NFKC (ligatürler: ﬁ → fi), Türkçe büyük/küçük harf katlama
  (İ/I/ı/i hepsi `i`), aksan atma (ş→s, ğ→g, ç→c, ö→o, ü→u, â→a),
- harf/rakam dışı her şey (boşluk, satır sonu, tire, noktalama, yumuşak tire)
  atılır; böylece satır sonunda tireyle bölünen sözcük ("değer-\\nlendirme")
  ve boşluk farkları kendiliğinden tutar,
- sık OCR karışmaları aynı biçime katlanır (rn→m, vv→w, 0→o, 1→l).
Tam eşleşme yoksa yaklaşık alt dizi eşlemesi (Sellers düzenleme uzaklığı)
yapılır; kalan OCR hataları (düşen/yanlış harf) puanı biraz düşürür. Puan = 1 - uzaklık / alıntı iskeleti uzunluğu.
"""
from __future__ import annotations

import unicodedata
from collections import Counter
from typing import NamedTuple

_TR = {"İ": "i", "I": "i", "ı": "i", "i̇": "i"}
_OCR_PAIRS = {"rn": "m", "vv": "w"}
_OCR_SINGLE = {"0": "o", "1": "l"}
_EXTRA = {"ß": "ss", "æ": "ae", "œ": "oe", "ø": "o", "đ": "d", "ł": "l"}


class QuoteMatch(NamedTuple):
    ok: bool
    score: float
    span: tuple[int, int] | None   # belge metninde (başlangıç, bitiş) karakter aralığı


def _fold_char(ch: str) -> str:
    if ch in _TR:
        return "i"
    s = unicodedata.normalize("NFKC", ch)
    out = []
    for c in s:
        if c in _TR:
            out.append("i")
            continue
        c = c.lower()
        c = _EXTRA.get(c, c)
        for d in unicodedata.normalize("NFKD", c):
            if unicodedata.combining(d):
                continue
            if d.isalnum():
                out.append(d)
    return "".join(out)


def skeleton(text: str) -> tuple[str, list[int], list[int]]:
    """Katlanmış iskelet; her iskelet karakterinin özgün metindeki (başlangıç, bitiş) indeksleri.

    Harf katlamasından sonra iki tarafa da aynı OCR katlaması uygulanır:
    rn→m, vv→w, 0→o, 1→l (taranmış metinde en sık karışanlar).
    """
    chars: list[str] = []
    idx: list[int] = []
    cache: dict[str, str] = {}
    for i, ch in enumerate(text):
        f = cache.get(ch)
        if f is None:
            f = cache[ch] = _fold_char(ch)
        for c in f:
            chars.append(c)
            idx.append(i)
    out: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    n = len(chars)
    j = 0
    while j < n:
        pair = chars[j] + chars[j + 1] if j + 1 < n else ""
        if pair in _OCR_PAIRS:
            out.append(_OCR_PAIRS[pair])
            starts.append(idx[j])
            ends.append(idx[j + 1] + 1)
            j += 2
            continue
        out.append(_OCR_SINGLE.get(chars[j], chars[j]))
        starts.append(idx[j])
        ends.append(idx[j] + 1)
        j += 1
    return "".join(out), starts, ends


def _sellers(q: str, t: str) -> tuple[int, int, int]:
    """q'nun t içindeki en iyi yaklaşık eşleşmesi: (uzaklık, başlangıç, bitiş)."""
    m = len(q)
    prev_cost = [0] * (len(t) + 1)
    prev_start = list(range(len(t) + 1))
    for i in range(1, m + 1):
        qc = q[i - 1]
        cost = [i] + [0] * len(t)
        start = [0] + [0] * len(t)
        for j in range(1, len(t) + 1):
            sub = prev_cost[j - 1] + (qc != t[j - 1])
            dele = prev_cost[j] + 1      # q harfi metinde yok
            ins = cost[j - 1] + 1        # metinde fazladan harf
            if sub <= dele and sub <= ins:
                cost[j], start[j] = sub, prev_start[j - 1]
            elif dele <= ins:
                cost[j], start[j] = dele, prev_start[j]
            else:
                cost[j], start[j] = ins, start[j - 1]
        prev_cost, prev_start = cost, start
    best_j = min(range(len(t) + 1), key=lambda j: (prev_cost[j], -j))
    return prev_cost[best_j], prev_start[best_j], best_j


def _candidate_offsets(q: str, t: str, k: int, top: int) -> list[int]:
    """q'nun k-gramlarının t'deki konumlarından hizalama başlangıcı oylaması."""
    pos: dict[str, list[int]] = {}
    for j in range(len(t) - k + 1):
        pos.setdefault(t[j:j + k], []).append(j)
    votes: Counter = Counter()
    seen = set()
    for i in range(len(q) - k + 1):
        g = q[i:i + k]
        if g in seen:
            continue
        seen.add(g)
        hits = pos.get(g)
        if not hits or len(hits) > 200:   # çok sık k-gram oy vermez
            continue
        for j in hits:
            votes[(j - i) // 8] += 1      # kaba kova: küçük kaymalar aynı adaya
    return [b * 8 for b, _ in votes.most_common(top)]


def verify_quote(quote: str, text: str, threshold: float = 0.9) -> QuoteMatch:
    """Alıntının metinde (toleranslı) geçip geçmediği.

    Döner: `(ok, score, span)`; `score` 0..1, `span` özgün metindeki
    `(başlangıç, bitiş)` aralığı (eşleşme yoksa None). `ok = score >= threshold`.
    """
    if not quote or not text:
        return QuoteMatch(False, 0.0, None)
    q, _, _ = skeleton(quote)
    t, tstart, tend = skeleton(text)
    if not q or not t:
        return QuoteMatch(False, 0.0, None)

    def span(s: int, e: int) -> tuple[int, int]:
        return (tstart[s], tend[e - 1])

    pos = t.find(q)
    if pos >= 0:
        return QuoteMatch(True, 1.0, span(pos, pos + len(q)))

    m = len(q)
    pad = max(8, m // 4)
    if m * len(t) <= 400_000:
        windows = [(0, len(t))]
    else:
        k = 5 if m >= 20 else max(2, m // 4)
        windows = []
        for off in _candidate_offsets(q, t, k, top=6):
            windows.append((max(0, off - pad), min(len(t), off + m + pad + 8)))
    best = (m + 1, 0, 0)
    for a, b in windows:
        d, s, e = _sellers(q, t[a:b])
        if d < best[0]:
            best = (d, a + s, a + e)
    d, s, e = best
    if e <= s:
        return QuoteMatch(False, 0.0, None)
    score = max(0.0, 1.0 - d / m)
    return QuoteMatch(score >= threshold, round(score, 4), span(s, e))
