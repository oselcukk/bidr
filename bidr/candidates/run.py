"""candidates.jsonl üretimi."""
from __future__ import annotations

from pathlib import Path

from bidr.common import Workspace, write_jsonl
from bidr.criteria.loader import load_criteria
from bidr.criteria.model import id_key
from bidr.criteria.profiles import excluded_types, load_profile

from .data import Doc, load
from .model import DEFAULT_COMBO, SIGNALS, Model

SLOTS_PER_CANDIDATE = 2
TOP_SLOTS = 3


def signal_ranks(raw: dict) -> dict[str, dict[str, int]]:
    out = {}
    for s, sc in raw.items():
        if not any(v > 0 for v in sc.values()):
            continue
        order = sorted(sc, key=lambda k: (-sc[k], id_key(k)))
        out[s] = {k: i + 1 for i, k in enumerate(order) if sc[k] > 0}
    return out


def _slots(rows) -> list[dict]:
    return [{"yuva": k, "puan": round(v, 6)} for k, v in rows]


def type_priorities() -> dict[str, dict[str, float]]:
    """Belge türü kataloğundan `olcut_onceligi` (tür -> {alt ölçüt: öncelik})."""
    from bidr.identify.catalog import load_catalog
    return {t.name: dict(t.criteria_priority) for t in load_catalog().types if t.criteria_priority}


def candidate_row(model: Model, doc: Doc, k: int, signals: tuple[str, ...] = DEFAULT_COMBO) -> dict:
    base = {"doc_id": doc.doc_id, "durum": doc.durum, "chars": doc.chars, "doc_type": doc.doc_type}
    if model.excluded(doc):
        return {**base, "haric": "oz_referans_turu", "etkin_sinyaller": [], "birlesik": list(signals),
                "k": k, "en_iyi_yuvalar": [], "adaylar": []}
    rows, raw = model.rank(doc, signals)
    ranks = signal_ranks(raw)
    w = model.weights
    per_crit = model.criterion_slots(doc)
    cands = []
    for i, (sid, total, norm) in enumerate(rows[:k], 1):
        contrib = {s: w.get(s, 0.0) * norm[s] for s in signals if s in ranks}
        top = max(contrib, key=contrib.get) if contrib and max(contrib.values()) > 0 else None
        cands.append({
            "olcut": sid,
            "ana": sid.rsplit(".", 1)[0],
            "sira": i,
            "puan": round(total, 6),
            "sinyaller": {s: round(norm[s], 6) for s in SIGNALS if s in ranks},
            "kaynak": top,
            "kaynaklar": [s for s in SIGNALS if s in ranks and ranks[s].get(sid, 10**9) <= k],
            "yuvalar": _slots(per_crit.get(sid, [])[:SLOTS_PER_CANDIDATE]),
        })
    return {
        **base,
        "etkin_sinyaller": [s for s in SIGNALS if s in ranks],
        "birlesik": list(signals),
        "k": k,
        "en_iyi_yuvalar": _slots(model.best_slots(doc, TOP_SLOTS)),
        "adaylar": cands,
    }


def build(ws_root: Path, train_roots: list[Path], k: int = 10, criteria=None, *,
          profile: str | None = None, signals: tuple[str, ...] = DEFAULT_COMBO,
          exclude_types: frozenset | None = None,
          type_priority: dict | None = None) -> tuple[list[dict], dict]:
    cs = criteria or load_criteria()
    prof = load_profile(profile) if profile else None
    allowed = frozenset(prof.allowed(cs)) if prof else None
    ex = excluded_types() if exclude_types is None else exclude_types
    target = load(ws_root)
    train: list[Doc] = []
    for r in train_roots:
        train.extend(load(r))
    model = Model(cs, allowed=allowed, excluded_types=ex,
                  type_priority=type_priorities() if type_priority is None else type_priority
                  ).fit(train)
    rows = [candidate_row(model, d, k, signals) for d in target]
    ozet = {
        "belge": len(target),
        "egitim_belgesi": len(model.train),
        "durum": {s: sum(d.durum == s for d in target) for s in ("ok", "kisa", "bos", "metin_yok")},
        "tur_bilgisi": sum(1 for d in target if d.doc_type),
        "haric_tur": sum(1 for d in target if model.excluded(d)),
        "olcut": len(model.out_ids),
        "profil": prof.name if prof else None,
        "birlesik": list(signals),
        "sorunlu": [{"doc_id": d.doc_id, "durum": d.durum, "chars": d.chars}
                    for d in target if d.durum != "ok"],
    }
    if prof:
        ozet["profil_kararlari"] = [{"olcut": d.criterion, "karar": d.verdict, "gerekce": d.reason,
                                     "aday": d.keep} for d in prof.decisions(cs) if d.verdict != "dahil"]
    return rows, ozet


def run(ws_root: Path, train_roots: list[Path], k: int = 10, *, out_name: str = "candidates.jsonl",
        profile: str | None = None, signals: tuple[str, ...] = DEFAULT_COMBO) -> tuple[Path, dict]:
    ws = Workspace(ws_root)
    rows, ozet = build(ws.root, train_roots, k, profile=profile, signals=signals)
    out = ws.root / out_name
    write_jsonl(out, rows)
    return out, ozet
