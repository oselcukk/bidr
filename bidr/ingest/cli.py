"""`bidr ingest SOURCE --workspace WS`"""
from __future__ import annotations

from collections import Counter
from pathlib import Path


def _cmd(args) -> int:
    from .pipeline import run

    rows = run(Path(args.source), Path(args.workspace), force=args.force,
               use_ocr=not args.no_ocr, workers=args.workers)
    c = Counter(r["status"] for r in rows)
    print(" ".join(f"{k}={v}" for k, v in sorted(c.items())))
    return 0


def register(sub):
    p = sub.add_parser("ingest", help="kaynak klasörü tara: inventory.csv + text/<doc_id>.txt")
    p.add_argument("source", help="kaynak klasör (salt okunur)")
    p.add_argument("--workspace", "-w", required=True, help="çalışma klasörü (repo dışı)")
    p.add_argument("--force", action="store_true", help="metni olan belgeleri de yeniden işle")
    p.add_argument("--no-ocr", action="store_true", help="OCR yapma (taranmış sayfalar needs_ocr kalır)")
    p.add_argument("--workers", type=int, default=None, help="paralel dosya sayısı (varsayılan: çekirdek)")
    p.set_defaults(func=_cmd)
