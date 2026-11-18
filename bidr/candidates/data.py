"""Çalışma klasöründen belge derlemi.

Özellik olarak YALNIZ şunlar okunur: `text/<doc_id>.txt` (içerik) ve varsa
`documents.jsonl` içindeki `doc_type`. `labels.jsonl` yalnız altın etiket
(`etiketler[].olcut`) ve bölme için birim (`birimler`) verir; `iz`, yol ve ad
alanları hiç okunmaz. `inventory.csv`'den yalnız `doc_id` sütunu okunur (metni
olmayan belgeleri raporlamak için); yol sütunlarına dokunulmaz.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from bidr.common import Workspace, read_jsonl

from .text import bag, text_hash

MIN_CHARS = 200          # bundan kısa (boşluksuz değil, kırpılmış) metin "kisa"
ALT = "alt_olcut"

# Durumlar
OK, KISA, BOS, METIN_YOK = "ok", "kisa", "bos", "metin_yok"


@dataclass
class Doc:
    doc_id: str
    ws: str
    chars: int = 0
    durum: str = OK
    thash: str | None = None
    bag: dict = field(default_factory=dict, repr=False)
    gold: tuple[str, ...] = ()          # alt ölçüt etiketleri (değerlendirme için)
    units: tuple[str, ...] = ()         # yalnız bölme için; özellik değil
    doc_type: str | None = None

    @property
    def labeled(self) -> bool:
        return bool(self.gold)

    @property
    def usable(self) -> bool:
        return self.durum == OK

    @property
    def keys(self) -> set[str]:
        """Sızıntı denetimi için içerik kimlikleri."""
        k = {f"id:{self.doc_id}"}
        if self.thash and self.durum in (OK, KISA):
            k.add(f"tx:{self.thash}")
        return k


def gold_from_label(row: dict) -> tuple[str, ...]:
    subs = {e["olcut"] for e in row.get("etiketler") or [] if e.get("duzey") == ALT}
    return tuple(sorted(subs))


def read_doc_types(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for r in read_jsonl(path):
        did, t = r.get("doc_id"), r.get("doc_type")
        if did and isinstance(t, str) and t.strip():
            out[did] = t.strip()
    return out


def inventory_ids(path: Path) -> list[str]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return [r["doc_id"] for r in csv.DictReader(f) if r.get("doc_id")]


def load(ws_root: Path | str, *, name: str | None = None) -> list[Doc]:
    ws = Workspace(Path(ws_root))
    name = name or ws.root.name
    labels = {r["doc_id"]: r for r in read_jsonl(ws.labels) if r.get("doc_id")} \
        if ws.labels.exists() else {}
    types = read_doc_types(ws.documents)
    ids: list[str] = []
    seen: set[str] = set()
    tx = sorted(p.stem for p in ws.text_dir.glob("*.txt")) if ws.text_dir.exists() else []
    for did in [*tx, *inventory_ids(ws.inventory)]:
        if did not in seen:
            seen.add(did)
            ids.append(did)
    docs = []
    for did in ids:
        d = Doc(doc_id=did, ws=name, doc_type=types.get(did))
        lab = labels.get(did)
        if lab:
            d.gold = gold_from_label(lab)
            d.units = tuple(lab.get("birimler") or ())
        p = ws.text_path(did)
        if not p.exists():
            d.durum = METIN_YOK
        else:
            t = p.read_text(encoding="utf-8", errors="replace")
            s = t.strip()
            d.chars = len(s)
            d.thash = text_hash(t)
            d.durum = BOS if not s else (KISA if len(s) < MIN_CHARS else OK)
            if s:
                d.bag = dict(bag(t))
        docs.append(d)
    return docs
