"""candidates.jsonl üretimi."""
from __future__ import annotations

from pathlib import Path

from bidr.common import Workspace, write_jsonl
from bidr.criteria.loader import load_criteria
from bidr.criteria.model import id_key

from .data import Doc, load
from .model import SIGNALS, Model


def signal_ranks(raw: dict) -> dict[str, dict[str, int]]:
    out = {}
    for s, sc in raw.items():
        if not any(v > 0 for v in sc.values()):
            continue
        order = sorted(sc, key=lambda k: (-sc[k], id_key(k)))
        out[s] = {k: i + 1 for i, k in enumerate(order) if sc[k] > 0}
    return out


def candidate_row(model: Model, doc: Doc, k: int) -> dict:
    rows, raw = model.rank(doc)
    ranks = signal_ranks(raw)
    w = model.weights
    cands = []
    for i, (sid, total, norm) in enumerate(rows[:k], 1):
        contrib = {s: w.get(s, 0.0) * norm[s] for s in SIGNALS if s in ranks}
        top = max(contrib, key=contrib.get) if contrib and max(contrib.values()) > 0 else None
        cands.append({
            "olcut": sid,
            "ana": sid.rsplit(".", 1)[0],
            "sira": i,
            "puan": round(total, 6),
            "sinyaller": {s: round(norm[s], 6) for s in SIGNALS if s in ranks},
            "kaynak": top,
            "kaynaklar": [s for s in SIGNALS if s in ranks and ranks[s].get(sid, 10**9) <= k],
        })
    return {
        "doc_id": doc.doc_id,
        "durum": doc.durum,
        "chars": doc.chars,
        "doc_type": doc.doc_type,
        "etkin_sinyaller": [s for s in SIGNALS if s in ranks],
        "k": k,
        "adaylar": cands,
    }


def build(ws_root: Path, train_roots: list[Path], k: int = 10, criteria=None) -> tuple[list[dict], dict]:
    cs = criteria or load_criteria()
    target = load(ws_root)
    train: list[Doc] = []
    for r in train_roots:
        train.extend(load(r))
    model = Model(cs).fit(train)
    rows = [candidate_row(model, d, k) for d in target]
    ozet = {
        "belge": len(target),
        "egitim_belgesi": len(model.train),
        "durum": {s: sum(d.durum == s for d in target) for s in ("ok", "kisa", "bos", "metin_yok")},
        "tur_bilgisi": sum(1 for d in target if d.doc_type),
        "sorunlu": [{"doc_id": d.doc_id, "durum": d.durum, "chars": d.chars}
                    for d in target if d.durum != "ok"],
    }
    return rows, ozet


def run(ws_root: Path, train_roots: list[Path], k: int = 10) -> tuple[Path, dict]:
    ws = Workspace(ws_root)
    rows, ozet = build(ws.root, train_roots, k)
    out = ws.root / "candidates.jsonl"
    write_jsonl(out, rows)
    return out, ozet
