"""Kanıt adının kaynağı ve öncelik sırası: insan > model > kural.

- `kanit-adlari.jsonl` (satır = `{doc_id, ad, kaynak: insan|model, …}`; `(doc_id, kaynak)`
  başına tek kayıt). Model kayıtlarını `bidr name apply` çalışma alanına, insan kayıtlarını
  `bidr audit apply` inceleme klasörüne (`--out`; vars. çalışma alanı) yazar.
- `decisions.jsonl` ince kararındaki `ince.kanit_adi` (classify_fine v7; denetimden geçmişse).
- Kural: `bidr.file.naming.evidence_name` (identify `baslik`'ı, yoksa tür etiketi).

Model kaynakları arasında `kanit-adlari.jsonl` önce gelir (adlandırma görevi ayrı ve sonra
çalışır). Her ad yeniden denetlenir (kişi/unvan/e-posta): tutmayan kaynak atlanır, uyarı verilir.
"""
from __future__ import annotations

import json
from pathlib import Path

from bidr.common import read_jsonl, write_jsonl

from .check import check_name

NAMES = "kanit-adlari.jsonl"
KAYNAKLAR = ("insan", "model")


def load_names(*dirs: Path | str | None) -> dict[str, dict[str, dict]]:
    """doc_id → {kaynak → kayıt}. Sonraki klasör aynı (doc_id, kaynak) için öncekini ezer."""
    out: dict[str, dict[str, dict]] = {}
    seen: set[Path] = set()
    for d in dirs:
        if not d:
            continue
        p = (Path(d).expanduser().resolve() / NAMES)
        if p in seen or not p.exists():
            continue
        seen.add(p)
        for r in read_jsonl(p):
            if r.get("doc_id") and r.get("kaynak") in KAYNAKLAR and r.get("ad"):
                out.setdefault(r["doc_id"], {})[r["kaynak"]] = r
    return out


def upsert(path: Path, recs: list[dict]) -> int:
    """`(doc_id, kaynak)` anahtarıyla ekle/güncelle; dosya doc_id sırasıyla yeniden yazılır."""
    path = Path(path)
    cur = {(r["doc_id"], r["kaynak"]): r for r in read_jsonl(path)} if path.exists() else {}
    n = 0
    for r in recs:
        k = (r["doc_id"], r["kaynak"])
        if cur.get(k) != r:
            n += 1
        cur[k] = r
    path.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(path, [cur[k] for k in sorted(cur)])
    return n


def decision_name(rec: dict | None) -> str | None:
    ka = ((rec or {}).get("ince") or {}).get("kanit_adi")
    if isinstance(ka, dict) and ka.get("durum") == "kabul" and ka.get("ad"):
        return ka["ad"]
    return None


class Resolver:
    """Belge → (ad, kaynak, uyarılar). `aliases`: aynı metnin kopyaları (insan adı kopyanın
    satırında düzeltilmiş olabilir)."""

    def __init__(self, names: dict[str, dict[str, dict]], decisions: dict[str, dict],
                 docs: dict[str, dict], labels: dict[str, str] | None = None):
        self.names, self.decisions, self.docs, self.labels = names, decisions, docs, labels or {}

    @classmethod
    def load(cls, ws_root: Path, *extra_dirs, docs: dict | None = None,
             decisions: dict | None = None, labels: dict | None = None) -> "Resolver":
        ws_root = Path(ws_root)
        if docs is None:
            p = ws_root / "documents.jsonl"
            docs = {r["doc_id"]: r for r in read_jsonl(p) if r.get("doc_id")} if p.exists() else {}
        if decisions is None:
            p = ws_root / "decisions.jsonl"
            decisions = {r["doc_id"]: r for r in read_jsonl(p) if r.get("doc_id")} if p.exists() else {}
        return cls(load_names(ws_root, *extra_dirs), decisions, docs, labels)

    def candidates(self, did: str, aliases: list[str] | tuple = ()) -> list[tuple[str, str]]:
        ids = [did, *[a for a in aliases if a != did]]
        out = []
        for x in ids:
            r = (self.names.get(x) or {}).get("insan")
            if r:
                out.append((r["ad"], "insan"))
        r = (self.names.get(did) or {}).get("model")
        if r:
            out.append((r["ad"], "model"))
        d = decision_name(self.decisions.get(did))
        if d:
            out.append((d, "model"))
        return out

    def resolve(self, did: str, aliases: list[str] | tuple = ()) -> tuple[str, str, list[str]]:
        from bidr.file.naming import evidence_name, safe_name
        uy: list[str] = []
        for ad, src in self.candidates(did, aliases):
            ok, errs = check_name(ad)
            if ok:
                return safe_name(ok), src, uy
            uy.append(f"{did}: {src} kanıt adı reddedildi ({', '.join(errs)}): {json.dumps(ad, ensure_ascii=False)}")
        d = self.docs.get(did) or {}
        ad, u = evidence_name({**d, "doc_id": did}, self.labels.get(d.get("doc_type")))
        return ad, "kural", uy + u
