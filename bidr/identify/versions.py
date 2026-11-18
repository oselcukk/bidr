"""Aynı belgenin farklı sürümlerini (ör. docx taslak ↔ imzalı tarama PDF) bağla.

Yalnız metin içeriğine bakılır: katlanmış sözcüklerin TF-IDF kosinüs benzerliği.
Çok yaygın sözcükler (form şablonu, kurum adı) IDF ile bastırılır; aynı şablonu
kullanan farklı toplantılar bu yüzden birleşmez. İki belgenin birincil tarihleri
farklıysa çok yüksek benzerlik dışında bağlanmaz.
"""
from __future__ import annotations

import math
import re
from collections import Counter

_TOK = re.compile(r"[a-z]{3,}")

THRESHOLD = 0.90          # bağlama eşiği
DATE_CONFLICT_MIN = 0.95  # tarihler farklıysa gereken benzerlik
MIN_TOKENS = 25


HEAD_CHARS = 2000
HEAD_MIN = 0.5            # baş bölgeler de benzemeli (aynı şablonu dolduran farklı birimler ayrılır)


def _vectors(texts: dict[str, str], df: Counter | None = None, n: int | None = None
             ) -> dict[str, dict[str, float]]:
    tfs = {k: Counter(_TOK.findall(t)) for k, t in texts.items()}
    if df is None:
        n = len(tfs)
        df = Counter()
        for tf in tfs.values():
            df.update(tf.keys())
    vecs = {}
    for k, tf in tfs.items():
        if sum(tf.values()) < MIN_TOKENS:
            continue
        v = {}
        for w, c in tf.items():
            if n > 4 and df[w] > 0.5 * n:
                continue
            v[w] = (1 + math.log(c)) * math.log((n + 1) / max(df[w], 1))
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        vecs[k] = {w: x / norm for w, x in v.items()}
    return vecs


def _cos(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b.get(w, 0.0) for w, x in a.items())


RARE_DF = 4               # en çok bu kadar belgede geçen sözcük "nadir" sayılır
RARE_MIN = 0.5            # nadir sözcüklerde de benzerlik (ortak şablonu dolduran farklı birimler ayrılır)
RARE_MIN_TOKENS = 10
TITLE_CHARS = 200
TITLE_MIN = 0.6
TITLE_CHECK_MAXLEN = 50000  # uzun raporlarda baş kısım kapak/künye farkıyla oynayabilir


def _rare_sets(texts: dict[str, str], df: Counter) -> dict[str, set[str]]:
    return {k: {w for w in set(_TOK.findall(t)) if df[w] <= RARE_DF} for k, t in texts.items()}


def group(texts: dict[str, str], dates: dict[str, str | None],
          types: dict[str, str] | None = None) -> dict[str, dict]:
    """doc_id -> {grup, uyeler, benzerlik}. Tek başına olanlar dahil edilmez."""
    vecs = _vectors(texts)
    df: Counter = Counter()
    for t in texts.values():
        df.update(set(_TOK.findall(t)))
    heads = _vectors({k: t[:HEAD_CHARS] for k, t in texts.items()}, df, len(texts))
    rare = _rare_sets(texts, df)
    types = types or {}
    ids = sorted(vecs)
    parent = {i: i for i in ids}
    best: dict[str, float] = {}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            s = _cos(vecs[a], vecs[b])
            if s < THRESHOLD:
                continue
            if a in heads and b in heads and _cos(heads[a], heads[b]) < HEAD_MIN:
                continue
            ra, rb = rare[a], rare[b]
            if min(len(ra), len(rb)) >= RARE_MIN_TOKENS:
                if len(ra & rb) / min(len(ra), len(rb)) < RARE_MIN:
                    continue
            elif s < DATE_CONFLICT_MIN:
                # ayırt edici sözcük yok (kısa/şablon belge): neredeyse aynı olmalı
                continue
            ha, hb = set(_TOK.findall(texts[a][:TITLE_CHARS])), set(_TOK.findall(texts[b][:TITLE_CHARS]))
            if (min(len(ha), len(hb)) >= 5 and max(len(texts[a]), len(texts[b])) < TITLE_CHECK_MAXLEN
                    and len(ha & hb) / len(ha | hb) < TITLE_MIN and s < 0.99):
                # başlık bölgesi farklı (ör. aynı anket formu, farklı ders)
                continue
            ta, tb = types.get(a), types.get(b)
            if ta and tb and ta != tb and s < DATE_CONFLICT_MIN:
                continue
            da, db = dates.get(a), dates.get(b)
            if da and db and da != db and s < DATE_CONFLICT_MIN:
                continue
            parent[find(a)] = find(b)
            best[a] = max(best.get(a, 0), s)
            best[b] = max(best.get(b, 0), s)
    groups: dict[str, list[str]] = {}
    for i in ids:
        groups.setdefault(find(i), []).append(i)
    out = {}
    for members in groups.values():
        if len(members) < 2:
            continue
        gid = "sg-" + min(members)
        for m in members:
            out[m] = {"grup": gid, "uyeler": sorted(x for x in members if x != m),
                      "benzerlik": round(best.get(m, 0.0), 3)}
    return out
