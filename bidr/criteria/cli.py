"""`bidr criteria list|show|validate`."""
from __future__ import annotations

import sys
from pathlib import Path

from .loader import build, default_path, load_criteria, read_raw, validate


def _cmd_list(a) -> int:
    cs = load_criteria(a.file)
    for area in cs.areas:
        print(f"{area.id}. {area.title}")
        for c in cs.children(area.id):
            print(f"  {c.id}. {c.title}")
            for s in cs.children(c.id):
                print(f"    {s.id}. {s.title}")
    return 0


def _cmd_show(a) -> int:
    cs = load_criteria(a.file)
    try:
        x = cs.get(a.id)
    except KeyError:
        print(f"bulunamadı: {a.id}", file=sys.stderr)
        return 1
    print(f"{x.id}. {x.title}")
    for d in x.description:
        print(f"  - {d}")
    if not hasattr(x, "rubric"):
        for c in cs.children(x.id):
            print(f"  {c.id}. {c.title}")
        return 0
    print(f"\nDOLDURACAK BİRİMLER: {x.units}")
    for n in x.units_note:
        print(f"  {n}")
    print("\nOlgunluk düzeyleri:")
    for k in sorted(x.rubric):
        print(f"  {k}: {x.rubric[k]}")
    print("\nÖrnek Kanıtlar:")
    for e in x.example_evidence:
        print(f"  - {e}")
    return 0


def _cmd_validate(a) -> int:
    p = Path(a.file) if a.file else default_path()
    raw = read_raw(p)
    errs = validate(raw, p.parent / "schema.json")
    if errs:
        for e in errs:
            print(f"HATA: {e}", file=sys.stderr)
        return 1
    cs = build(raw)
    full = sum(1 for s in cs.sub_criteria if all(s.rubric.get(k) for k in range(1, 6)))
    print(f"{p}: geçerli — {len(cs.areas)} ana alan, {len(cs.criteria)} ana ölçüt, "
          f"{len(cs.sub_criteria)} alt ölçüt ({full} tanesinde 5 rubrik düzeyi dolu)")
    return 0


def register(sub) -> None:
    p = sub.add_parser("criteria", help="YÖKAK/BİDR ölçüt şeması")
    p.add_argument("--file", default=None, help="ölçüt YAML'ı (vars.: bidr/data/criteria/yokak-2025.yaml)")
    s = p.add_subparsers(dest="criteria_cmd", required=True)
    s.add_parser("list", help="ölçüt ağacını listele").set_defaults(func=_cmd_list)
    sh = s.add_parser("show", help="bir ölçütü göster (ör. A.1.2)")
    sh.add_argument("id")
    sh.set_defaults(func=_cmd_show)
    s.add_parser("validate", help="şema ve yapı denetimi").set_defaults(func=_cmd_validate)
