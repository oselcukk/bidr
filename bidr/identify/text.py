"""Metin normalleştirme: boşluk sıkıştırma ve 1:1 Türkçe katlama.

`fold` her karakteri tam olarak bir karaktere eşler; böylece katlanmış metinde
bulunan eşleşmenin konumu özgün (sıkıştırılmış) metinde aynı aralığa düşer ve
alıntı özgün yazımla verilebilir.
"""
from __future__ import annotations

import re
import unicodedata

_TR = {
    "İ": "i", "I": "i", "ı": "i", "i": "i",
    "Ş": "s", "ş": "s", "Ğ": "g", "ğ": "g", "Ü": "u", "ü": "u",
    "Ö": "o", "ö": "o", "Ç": "c", "ç": "c",
    "Â": "a", "â": "a", "Î": "i", "î": "i", "Û": "u", "û": "u",
    "̇": " ",  # birleşik üst nokta (i̇) -> boşluk; uzunluk korunur
    "‐": "-", "‑": "-", "–": "-", "—": "-",
    "’": "'", "‘": "'", "“": '"', "”": '"',
}

# Desenler için: yalnız Türkçe küçük harfleri ASCII'ye indir (kaçış dizilerine dokunma).
_TR_PATTERN = {k: v for k, v in _TR.items() if k.islower() or k in "‐‑–—"}


def _fold_char(c: str) -> str:
    m = _TR.get(c)
    if m is not None:
        return m
    low = c.lower()
    if len(low) != 1:
        return c
    if ord(low) > 127:
        # diğer aksanlı harfler: temel harf (é -> e); uzunluk 1 kalmalı
        base = unicodedata.normalize("NFD", low)[0]
        return base if len(base) == 1 else low
    return low


_CACHE: dict[str, str] = {}


def fold(s: str) -> str:
    out = []
    for c in s:
        f = _CACHE.get(c)
        if f is None:
            f = _CACHE[c] = _fold_char(c)
        out.append(f)
    return "".join(out)


_WS = re.compile(r"\s+")


def collapse(s: str) -> str:
    return _WS.sub(" ", s).strip()


def fold_pattern(p: str) -> str:
    """Katalog desenini derlemeye hazırla: Türkçe harfleri indir, boşluk -> \\s*."""
    p = "".join(_TR_PATTERN.get(c, c) for c in p)
    return p.replace(" ", r"\s*")


_WORD = re.compile(r"[a-z]{2,}")


def quality(folded: str) -> float:
    """Okunabilirlik: 3+ harfli sözcüklerin toplam belirteçlere oranı (0..1)."""
    toks = folded.split()
    if not toks:
        return 0.0
    good = sum(1 for t in toks if len(t) >= 3 and _WORD.fullmatch(t.strip(".,;:()[]\"'!?")))
    return round(good / len(toks), 3)


def looks_binary(raw: str) -> bool:
    """Metin çıkarıcının ham ikili içerik bıraktığı durumlar (ör. zip başlığı)."""
    head = raw[:400]
    if head.startswith("PK") and "[Content_Types].xml" in head:
        return True
    ctrl = sum(1 for c in head if ord(c) < 32 and c not in "\n\r\t\f")
    return len(head) > 0 and ctrl / len(head) > 0.1


_TR_UPPER = str.maketrans({"i": "İ", "ı": "I"})
_TR_LOWER = str.maketrans({"İ": "i", "I": "ı"})


def tr_title(s: str) -> str:
    """Tamamı büyük harfli başlığı Türkçe kurala uygun baş harf büyük yaz."""
    letters = [c for c in s if c.isalpha()]
    if not letters or sum(c.isupper() for c in letters) / len(letters) < 0.8:
        return s
    words = []
    for w in s.split(" "):
        low = w.translate(_TR_LOWER).lower()
        if low[:1]:
            low = low[0].translate(_TR_UPPER).upper() + low[1:]
        words.append(low)
    return " ".join(words)


_ASCII = str.maketrans({
    "ı": "i", "İ": "I", "ş": "s", "Ş": "S", "ğ": "g", "Ğ": "G", "ü": "u", "Ü": "U",
    "ö": "o", "Ö": "O", "ç": "c", "Ç": "C", "â": "a", "Â": "A", "î": "i", "û": "u",
})


def slug(s: str, max_words: int = 8, max_len: int = 70) -> str:
    s = s.translate(_ASCII)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    words = re.findall(r"[A-Za-z0-9]+", s)
    out: list[str] = []
    for w in words[:max_words]:
        w = w[:1].upper() + w[1:] if not w.isupper() or len(w) <= 3 else w[:1] + w[1:].lower()
        if len("-".join(out + [w])) > max_len:
            break
        out.append(w)
    return "-".join(out)
