"""Türkçe–İngilizce karşılık sözlüğü (`bidr/data/dil_karsiliklari.yaml`).

Ölçüt/yuva metinleri Türkçe, izlence ve ders sitesi gibi belgeler çoğu kez İngilizce:
ortak sözcük olmadığı için BM25/yuva sinyalleri bu belgeleri ilgili ölçüte getirmez.
Sözlük grupları iki yönlü genişletir (`cross_terms`): metinde bir dilin öbeği geçerse
öteki dilin belirteçleri eklenir. Yönler:
  belge → ölçüt (ilk geçiş, ikinci arama arşivi): İngilizce öbek → Türkçe belirteç
      (`expand_bag`); ölçüt derlemi (IDF, uzunluk) değişmez.
  ölçüt → belge (ikinci arama sorgusu): Türkçe öbek → İngilizce belirteç (`query_terms`).
Aynı dil içinde genişletme yapılmaz (o iş `synonyms.py`'nin); İngilizce öbek içermeyen
Türkçe belgenin torbası ve puanı değişmez. Eklenen belirteç sayısı 1'dir; torbada zaten
olan belirteç eklenmez.
"""
from __future__ import annotations

import os
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

import yaml

from .text import fold, tokens

DATA = Path(__file__).resolve().parents[1] / "data" / "dil_karsiliklari.yaml"
DILLER = ("tr", "en")
_WORD = re.compile(r"[a-z]+")


def _pattern(phrase: str) -> re.Pattern | None:
    words = _WORD.findall(fold(phrase))
    if not words:
        return None
    return re.compile(r"\b" + r"\w*\s+".join(map(re.escape, words)) + r"\w*")


@lru_cache(maxsize=4)
def load_groups(path: str | None = None) -> tuple[dict, ...]:
    """Gruplar: her biri {dil: (desenler, belirteçler)}. Dosya yoksa boş."""
    p = Path(path or os.environ.get("BIDR_DIL_KARSILIKLARI", DATA)).expanduser()
    if not p.exists():
        return ()
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    out = []
    for g in raw.get("gruplar") or []:
        grp = {}
        for lang in DILLER:
            pats, toks = [], []
            for ph in g.get(lang) or []:
                pat = _pattern(str(ph))
                if pat is not None:
                    pats.append(pat)
                    toks.extend(t for t in tokens(str(ph)) if t not in toks)
            grp[lang] = (tuple(pats), tuple(toks))
        if all(grp[lang][0] for lang in DILLER):
            out.append(grp)
    return tuple(out)


def _folded(text: str) -> str:
    return " ".join(_WORD.findall(fold(text)))


def cross_terms(text: str, have=None, *, only_from: str | None = None) -> list[str]:
    """Metinde geçen öbeklerin öteki dildeki belirteçleri (`have` içindekiler hariç).
    `only_from="tr"`: yalnız Türkçe öbekler tetikler (ölçüt sorgusu için)."""
    ft = _folded(text)
    have = set(have or ())
    added: list[str] = []
    for grp in load_groups():
        for src, dst in (("tr", "en"), ("en", "tr")):
            if only_from and src != only_from:
                continue
            if any(p.search(ft) for p in grp[src][0]):
                for t in grp[dst][1]:
                    if t not in have:
                        have.add(t)
                        added.append(t)
    return added


def query_terms(text: str, have=None) -> list[str]:
    """Ölçüt sorgusu için: Türkçe öbeklerin İngilizce karşılık belirteçleri."""
    return cross_terms(text, have, only_from="tr")


def expand_bag(text: str, b: dict) -> dict:
    """Belge torbası + İngilizce öbeklerin Türkçe karşılıkları (eşleşme torbası; özgün
    torba değişmez)."""
    add = cross_terms(text, b, only_from="en")
    if not add:
        return dict(b)
    out = Counter(b)
    for t in add:
        out[t] = 1
    return dict(out)
