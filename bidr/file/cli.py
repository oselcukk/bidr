"""`bidr file -w WS [--out DIR] [--source DIR] [--review DIR] [--tum-belge] [--zip]`."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _run(args) -> int:
    from bidr.pipeline.gate import check_gate

    from . import run
    ws = Path(args.workspace).expanduser().resolve()
    try:
        from bidr.pipeline.state import stage
        stage("file")
        rc = check_gate(ws, "file", kaynak=args.source)
        if rc is not None:
            return rc
    except KeyError:
        pass
    try:
        st = run.run(ws, out=args.out, source=args.source, review_dir=args.review,
                     whole=args.tum_belge, make_zip=args.zip, profile=args.profile)
    except (FileNotFoundError, run.FileError, ValueError) as e:
        print(f"HATA {e}", file=sys.stderr)
        return 2
    for u in st.pop("uyarilar"):
        print(f"uyarı: {u}")
    print(json.dumps(st, ensure_ascii=False, indent=1))
    if not st["inceleme"]:
        print("UYARI: inceleme yapılmadı (review-decisions.jsonl yok); kanıtlar insan onaysız.")
    return 0


def register(sub):
    p = sub.add_parser("file", help="onaylı eşleşmeleri ölçüt klasörlerine kılavuz adıyla kopyalar "
                                    "(evidence/…) ve evidence-index.csv üretir; kaynak değişmez")
    p.add_argument("--workspace", "-w", required=True)
    p.add_argument("--out", default=None, help="çıktı klasörü (varsayılan çalışma alanı)")
    p.add_argument("--source", default=None,
                   help="kaynak kök (config.yaml'da `bidr: kaynak` yoksa gerekli; salt okunur)")
    p.add_argument("--review", default=None,
                   help="review-decisions.jsonl'in klasörü (audit --out; varsayılan çalışma alanı)")
    p.add_argument("--tum-belge", action="store_true",
                   help="birleşik PDF'i de (tek dosyada birden çok belge) bölmeden tam kopyala; "
                        "varsayılan: her dosya tam, birleşik dosyada her belge kendi bütün sayfalarıyla "
                        "(alıntı sayfasına kesilmez)")
    p.add_argument("--zip", action="store_true", help="evidence.zip de üret")
    p.add_argument("--profile", default=None, help="varsayılan: config.yaml profili, yoksa akademik_bolum")
    p.set_defaults(func=_run)
