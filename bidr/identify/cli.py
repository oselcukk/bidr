"""`bidr identify --workspace WS [--period 2025]`"""
from __future__ import annotations

from collections import Counter
from pathlib import Path


def _cmd(args) -> int:
    from .catalog import load_catalog
    from .pipeline import run

    cat = load_catalog(Path(args.catalog) if args.catalog else None,
                       institutions=args.institution or None)
    recs = run(Path(args.workspace), period=args.period, catalog=cat,
               write_report=not args.no_report)
    c = Counter(r["doc_type"] for r in recs)
    print(" ".join(f"{k}={v}" for k, v in c.most_common()))
    return 0


def register(sub):
    p = sub.add_parser("identify", help="belge türü, tarih, başlık, sürüm grubu: documents.jsonl")
    p.add_argument("--workspace", "-w", required=True, help="çalışma klasörü (ingest çıktısı)")
    p.add_argument("--period", type=int, default=None, help="değerlendirme yılı (ör. 2025)")
    p.add_argument("--catalog", default=None, help="tür kataloğu YAML (varsayılan: paket verisi)")
    p.add_argument("--institution", action="append", default=[],
                   help="kurum profili adı (bidr/data/institutions/<ad>.yaml); varsayılan: hepsi")
    p.add_argument("--no-report", action="store_true", help="identify-report.md yazma")
    p.set_defaults(func=_cmd)
