"""Türkçe metin normalizasyonu ve belirteçleme (bağımlılıksız).

Adımlar: Türkçe büyük/küçük harf (I→ı, İ→i), aksan katlama (ç→c, ğ→g, ı→i, ö→o,
ş→s, ü→u; OCR hatalarına dayanıklılık için), harf dışını ayırma, durak sözcük
atma, ek budama (ilk 5 harf; Türkçe için bilinen basit ve güçlü yöntem).
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter

STEM_LEN = 5
MIN_LEN = 2

_FOLD = str.maketrans({"ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u",
                       "â": "a", "î": "i", "û": "u"})
_TOKEN = re.compile(r"[a-z]+")

_STOP_RAW = """
ve veya ile ama fakat ancak bir bu su o da de ki mi mu icin gibi kadar gore sonra once
olan olarak olmak oldugu olup olmasi ise en cok daha her tum butun hem ya ne nasil
yani bunu bunun buna bunlar bunlarin sey icinde uzere dair yer yerine diger
the of and in to for on with by is are be as at an or from this that it its not
""".split()
STOP = frozenset(_STOP_RAW)


def lower_tr(s: str) -> str:
    s = unicodedata.normalize("NFC", s)
    return s.replace("I", "ı").replace("İ", "i").lower()


def fold(s: str) -> str:
    s = lower_tr(s).translate(_FOLD)
    # kalan birleşik işaretleri (ör. i̇) at
    s = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def tokens(s: str, stem_len: int | None = None) -> list[str]:
    stem_len = STEM_LEN if stem_len is None else stem_len
    out = []
    for t in _TOKEN.findall(fold(s)):
        if len(t) < MIN_LEN or t in STOP:
            continue
        out.append(t[:stem_len] if stem_len else t)
    return out


def bag(s: str) -> Counter:
    return Counter(tokens(s))


def text_hash(s: str) -> str:
    """İçerik kimliği (metin düzeyi): boşluk farkları yok sayılır.

    Farklı dosyalardan (ör. aynı belgenin pdf ve docx'i) aynı metin çıkarsa aynı
    özeti verir; eğitim/test ayrımında doc_id'ye ek olarak kullanılır."""
    return hashlib.sha1(" ".join(s.split()).encode("utf-8")).hexdigest()[:16]
