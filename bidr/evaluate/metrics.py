"""Sıralama ölçüleri. Bir belgede birden çok doğru ölçüt olabilir.

recall@k  doğru ölçütlerin ilk k'da bulunan oranı (belge başına, sonra ortalama)
hit@k     en az bir doğru ölçüt ilk k'da mı (karar modelinin en az bir doğru
          seçeneği görmesi)
MRR       ilk doğru ölçütün sırasının tersi
"""
from __future__ import annotations

KS = (1, 3, 5, 10)


def doc_metrics(ranking: list[str], gold: set[str], ks=KS) -> dict[str, float]:
    pos = {c: i for i, c in enumerate(ranking, 1)}
    ranks = sorted(pos.get(g, 10**9) for g in gold)
    m = {}
    for k in ks:
        m[f"R@{k}"] = sum(r <= k for r in ranks) / len(gold)
        m[f"H@{k}"] = float(ranks[0] <= k)
    m["MRR"] = 1.0 / ranks[0] if ranks[0] < 10**9 else 0.0
    return m


def mean(rows: list[dict[str, float]]) -> dict[str, float]:
    if not rows:
        return {}
    return {k: sum(r[k] for r in rows) / len(rows) for k in rows[0]}


def collapse(ranking: list[str]) -> list[str]:
    """Alt ölçüt sıralamasından ana ölçüt sıralaması (ilk görünme = en yüksek puan)."""
    out, seen = [], set()
    for c in ranking:
        p = c.rsplit(".", 1)[0]
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out
