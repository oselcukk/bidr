"""İlgili ama kanıt sayılmamış belgeler: bir ölçütte aday olmuş (belirleyici aday, kaba seçim ya da
ince karar eşleşmesi) ama o ölçütün kanıt listesine (`evidence-index.csv`) girmemiş belgeler.

İki yerde kullanılır:
  - yazım paketi (`bidr write`): "kanıt bulunmamaktadır" hükmünden önce yazar bu belgelerin varlığını
    görür (yokluk hükmü yerine "ilgili ama yetersiz belge" ayrımı; atıf yapılmaz);
  - kör denetim paketi (`bidr denetim`): kapsam kaybını görmek için denetçiye kısa liste ve metin.

Belgenin neden kullanılmadığı (ince kararın gerekçesi, inceleme kararı) verilmez: yazar ve denetçi
yalnız belgenin kendisini görür. Başka birimin belgesi (`birim_iliskisi: baska_birim`) ve mükerrer
kopya listeye girmez. Salt okunur.
"""
from __future__ import annotations

import json
from pathlib import Path

from bidr.common import read_jsonl

DECISIONS = "decisions.jsonl"
DOCUMENTS = "documents.jsonl"
BASKA_BIRIM = "baska_birim"
AZAMI = 8


def _load(p: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not p.exists():
        return out
    try:
        for r in read_jsonl(p):
            if r.get("doc_id"):
                out[r["doc_id"]] = r
    except (OSError, ValueError):
        return {}
    return out


def candidate_criteria(rec: dict) -> set[str]:
    """Belgenin aday olduğu ölçütler (ince karar adayları, kaba seçim, eşleşmeler)."""
    out = set(rec.get("adaylar") or [])
    out.update((rec.get("kaba") or {}).get("secilen") or [])
    out.update(m.get("olcut") for m in rec.get("eslesmeler") or [] if m.get("olcut"))
    return {x for x in out if isinstance(x, str) and x}


class Related:
    """Bir çalışma alanının aday kayıtları; `for_criterion` ölçüt başına liste verir."""

    def __init__(self, ws_root: Path):
        root = Path(ws_root)
        self.recs = _load(root / DECISIONS)
        self.docs = _load(root / DOCUMENTS)
        self.by_c: dict[str, list[str]] = {}
        for did, rec in self.recs.items():
            if (rec.get("ince") or {}).get("birim_iliskisi") == BASKA_BIRIM:
                continue
            m = rec.get("mukerrer") or {}
            if m.get("temsilci") and m.get("temsilci") != did:
                continue
            for c in candidate_criteria(rec):
                self.by_c.setdefault(c, []).append(did)

    def name(self, did: str) -> str:
        d = self.docs.get(did) or {}
        return str(d.get("calisma_adi") or d.get("baslik") or d.get("doc_type") or did)

    def for_criterion(self, olcut: str, used: set[str], limit: int = AZAMI) -> list[dict]:
        """[{doc_id, ad, tur, tarih}] — kanıt listesinde (`used`) olmayan aday belgeler, belge kimliğine
        göre sabit sırada (en çok `limit`)."""
        out = []
        for did in sorted(set(self.by_c.get(olcut) or []) - set(used)):
            d = self.docs.get(did) or {}
            out.append({"doc_id": did, "ad": self.name(did),
                        "tur": str(d.get("doc_type_etiket") or d.get("doc_type") or ""),
                        "tarih": str(d.get("tarih") or "")})
            if len(out) >= limit:
                break
        return out


def render(rows: list[dict]) -> str:
    """Yazım istemindeki İLGİLİ AMA KANIT SAYILMAMIŞ BELGELER bölümü."""
    if not rows:
        return "yok"
    lines = []
    for r in rows:
        info = ", ".join(x for x in (r.get("tur"), r.get("tarih")) if x)
        lines.append(f"- {r['ad']}" + (f" ({info})" if info else ""))
    return "\n".join(lines)


def sha(rows: list[dict]) -> str:
    return json.dumps([r["doc_id"] for r in rows])
