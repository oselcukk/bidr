"""Sentetik çalışma klasörü (gerçek veri yok). Metinler ölçüt metninden türetilir."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from bidr.candidates.model import criterion_text
from bidr.criteria.loader import load_criteria

CS = load_criteria()


def did(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def ctext(sid: str, extra: str = "") -> str:
    return criterion_text(CS, sid) + "\n" + extra


def make_ws(root: Path, docs: list[dict], doc_types: dict[str, str] | None = None) -> Path:
    """docs: {"id"?, "text", "gold": [...], "units": [...], "path"?}"""
    root.mkdir(parents=True, exist_ok=True)
    (root / "text").mkdir(exist_ok=True)
    labels, inv = [], []
    for i, d in enumerate(docs):
        x = d.get("id") or did(d["text"] + str(i))
        d["id"] = x
        (root / "text" / f"{x}.txt").write_text(d["text"], encoding="utf-8")
        path = d.get("path", f"klasor/{i}.pdf")
        inv.append({"doc_id": x, "sha256": x * 4, "rel_path": path, "ext": ".pdf", "size": 1,
                    "pages": 1, "chars": len(d["text"]), "method": "x", "status": "ok",
                    "dup_of": "", "error": ""})
        gold = d.get("gold") or []
        labels.append({"kayit": f"doc:{x}", "doc_id": x, "durum": "ok", "birimler": d.get("units", ["U"]),
                       "etiketli": bool(gold),
                       "etiketler": [{"olcut": g, "duzey": "alt_olcut"} for g in gold],
                       "iz": {"yalniz_iz": True, "yollar": [{"yol": path}]}})
    with open(root / "inventory.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(inv[0]))
        w.writeheader()
        w.writerows(inv)
    with open(root / "labels.jsonl", "w", encoding="utf-8") as f:
        for r in labels:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    if doc_types:
        with open(root / "documents.jsonl", "w", encoding="utf-8") as f:
            for k, t in doc_types.items():
                f.write(json.dumps({"doc_id": k, "doc_type": t}, ensure_ascii=False) + "\n")
    return root
