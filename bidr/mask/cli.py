"""`bidr maskele -w WS [--evidence DIR] [--out DIR] [--motor auto|pymupdf|pypdf] [--ad-listesi DOSYA]`."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _run(args) -> int:
    from .detect import load_name_list
    from .formats import MaskError
    from .run import MaskRunError, run
    ws = Path(args.workspace).expanduser().resolve()
    try:
        names = load_name_list(args.ad_listesi, ws) if args.ad_listesi else None
        r = run(ws, evidence=args.evidence, out=args.out, engine=args.motor, names=names)
    except (FileNotFoundError, MaskRunError, MaskError, ValueError) as e:
        print(f"HATA {e}", file=sys.stderr)
        return 2
    for u in r["uyarilar"]:
        print(f"uyarı: {u}")
    for f in r["dosyalar"]:
        if f.get("imza_uyarisi"):
            print(f"uyarı: imza bölgesi olabilir (elle bakın): {f['dosya']} {', '.join(f['imza_uyarisi'])}")
        if f.get("imza_elle"):
            print(f"uyarı: imza elle bakılmalı: {f['dosya']} {', '.join(f['imza_elle'])}")
    print(json.dumps(r["ozet"], ensure_ascii=False, indent=1))
    if r["yayimlanamaz"]:
        print(f"YAYIMLANAMAZ ({len(r['yayimlanamaz'])}):")
        for y in r["yayimlanamaz"]:
            print(f"  {y['dosya']}: {y['neden']}")
        return 1
    return 0


def register(sub):
    p = sub.add_parser("maskele", help="kanıtların (evidence/) kişisel verisi maskelenmiş yayın kopyası "
                                       "(evidence-maskeli/) ve maskeleme-raporu.json; asıl dosyalar değişmez")
    p.add_argument("--workspace", "-w", required=True)
    p.add_argument("--evidence", default=None, help="kanıt klasörü (varsayılan <ws>/evidence)")
    p.add_argument("--out", default=None, help="çıktı kökü (varsayılan kanıt klasörünün üstü)")
    p.add_argument("--motor", choices=("auto", "pymupdf", "pypdf"), default="auto",
                   help="PDF motoru: pymupdf gerçek kaldırma; pypdf en iyi çaba (varsayılan: varsa pymupdf)")
    p.add_argument("--ad-listesi", default=None,
                   help="ek ad listesi (.txt satır başına bir ad ya da .csv ilk sütun); "
                        "config.yaml privacy.maskeleme.ad_listesi'ne eklenir")
    p.set_defaults(func=_run)
