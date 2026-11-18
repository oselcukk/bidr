"""İkinci aramanın ölçümü: işaretli eşleşmelerin kod ve insan kararı sayıları.

Girdi: decisions.jsonl (`ikinci_arama: true` eşleşmeler, kayıtların `ikinci_arama` bölümü) ve
varsa review-decisions.jsonl (`bidr audit apply`; satır anahtarı `<doc_id>|<yuva>`).
Çıktı ölçüt başına ve toplam:
  bakilan      ikinci aramanın pakete koyduğu (belge, ölçüt) çifti
  eslesme      modelin önerdiği eşleşme
  kod_kabul / kod_red (red nedenleriyle)
  insan_kabul (kabul ya da düzelt), insan_ret, incelenmedi — yalnız kod kabullerinde
  isabet       insan_kabul / (insan_kabul + insan_ret); incelenen yoksa None
"Kaçırdıkları" = insanın kabul ettiği ikinci arama eşleşmeleri (ilk geçişin kaçırdığı
kanıt); "eklediği yanlışlar" = insanın reddettiği ikinci arama eşleşmeleri.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from bidr.common import Workspace, read_jsonl
from bidr.criteria.model import id_key

REVIEW = "review-decisions.jsonl"


def _empty() -> dict:
    return {"bakilan": 0, "eslesme": 0, "kod_kabul": 0, "kod_red": 0, "insan_kabul": 0,
            "insan_ret": 0, "incelenmedi": 0, "red_nedenleri": Counter()}


def measure(ws_root: Path | str, review: Path | str | None = None) -> dict:
    ws = Workspace(Path(ws_root))
    dp = ws.root / "decisions.jsonl"
    recs = list(read_jsonl(dp)) if dp.exists() else []
    rp = Path(review) if review else ws.root / REVIEW
    rev = {r["satir"]: r for r in read_jsonl(rp) if r.get("satir")} if rp.exists() else {}
    by: dict[str, dict] = {}
    for rec in recs:
        ia = rec.get("ikinci_arama") or {}
        for c in ia.get("olcutler") or {}:
            by.setdefault(c, _empty())["bakilan"] += 1
        for m in rec.get("eslesmeler") or []:
            if not m.get("ikinci_arama"):
                continue
            s = by.setdefault(m["olcut"], _empty())
            s["eslesme"] += 1
            if not m.get("kabul"):
                s["kod_red"] += 1
                s["red_nedenleri"].update((m.get("denetim") or {}).get("red") or ["?"])
                continue
            s["kod_kabul"] += 1
            k = (rev.get(f"{rec['doc_id']}|{m.get('yuva')}") or {}).get("karar")
            if k in ("kabul", "duzelt"):
                s["insan_kabul"] += 1
            elif k == "ret":
                s["insan_ret"] += 1
            else:
                s["incelenmedi"] += 1
    total = _empty()
    for s in by.values():
        for k, v in s.items():
            total[k] += v
    out = {}
    for c, s in [*sorted(by.items(), key=lambda x: id_key(x[0])), ("toplam", total)]:
        n = s["insan_kabul"] + s["insan_ret"]
        out[c] = {**s, "red_nedenleri": dict(sorted(s["red_nedenleri"].items())),
                  "isabet": round(s["insan_kabul"] / n, 4) if n else None}
    return {"olcutler": {c: v for c, v in out.items() if c != "toplam"}, "toplam": out["toplam"],
            "inceleme_dosyasi": str(rp) if rev else None}


def format_table(res: dict) -> str:
    cols = ("bakilan", "eslesme", "kod_kabul", "kod_red", "insan_kabul", "insan_ret", "incelenmedi")
    lines = ["ölçüt\t" + "\t".join(cols) + "\tisabet"]
    for c, s in [*res["olcutler"].items(), ("toplam", res["toplam"])]:
        isb = "-" if s["isabet"] is None else f"{s['isabet']:.2f}"
        lines.append(f"{c}\t" + "\t".join(str(s[k]) for k in cols) + f"\t{isb}")
    if res["toplam"]["red_nedenleri"]:
        lines.append("kod red nedenleri: " + ", ".join(f"{k}={v}" for k, v in res["toplam"]["red_nedenleri"].items()))
    if not res["inceleme_dosyasi"]:
        lines.append("review-decisions.jsonl yok: insan kararları henüz sayılmadı (bidr audit apply)")
    return "\n".join(lines)
