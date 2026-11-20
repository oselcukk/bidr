"""`bidr maskele` iki kullanım:

- teslim/yayın kopyası: `bidr maskele -w WS [--evidence DIR] [--out DIR] [--motor …] [--ad-listesi DOSYA]`
- model öncesi kaynak maskeleme: `bidr maskele --kaynak BÖLÜM_KLASÖRÜ --out MASKELİ_KOPYA [-w WS]
  [--motor …] [--ad-listesi DOSYA] [--is N] [--rapor DOSYA] [--ayir]`
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _rules(args, base: Path | None):
    from .detect import MaskRules, load_name_list, read_ws_config
    rules = MaskRules.from_config(read_ws_config(base), base) if base else MaskRules()
    if args.ad_listesi:
        rules = MaskRules(kinds=rules.kinds, student_patterns=rules.student_patterns,
                          names=tuple(rules.names) + tuple(load_name_list(args.ad_listesi, base or Path.cwd())),
                          local_model=rules.local_model)
    return rules


def _run_source(args) -> int:
    from .formats import MaskError
    from .kaynak import run_source
    from .run import MaskRunError
    if not args.out:
        print("HATA --kaynak ile --out (maskeli kopya klasörü) zorunlu", file=sys.stderr)
        return 2
    ws = Path(args.workspace).expanduser().resolve() if args.workspace else None

    def progress(i, n, rel):
        if args.ilerleme:
            print(f"[{i}/{n}] {rel}", file=sys.stderr, flush=True)
    try:
        r = run_source(Path(args.kaynak), Path(args.out), rules=_rules(args, ws), engine=args.motor,
                       workers=max(1, args.is_), report=Path(args.rapor) if args.rapor else None,
                       progress=progress, ayir=args.ayir)
    except (FileNotFoundError, MaskRunError, MaskError, ValueError) as e:
        print(f"HATA {e}", file=sys.stderr)
        return 2
    for u in r["uyarilar"]:
        print(f"uyarı: {u}")
    print(json.dumps(r["ozet"], ensure_ascii=False, indent=1))
    print(f"rapor: {r['rapor']}")
    if r.get("ayrilan_klasor"):
        print(f"--ayir: {len(r['ayrilan'])} dosya maskeli kopyanın dışına ayrıldı: {r['ayrilan_klasor']}")
    if r["elle_bakilmali"]:
        print(f"ELLE BAKILMALI ({len(r['elle_bakilmali'])}):")
        for y in r["elle_bakilmali"]:
            print(f"  [{y['durum']}] {y['hedef'] or y['dosya']}: {y['neden']}")
        return 1
    return 0


def _run(args) -> int:
    if args.kaynak:
        return _run_source(args)
    from .detect import load_name_list
    from .formats import MaskError
    from .run import MaskRunError, run
    if not args.workspace:
        print("HATA --workspace/-w (ya da --kaynak) gerekli", file=sys.stderr)
        return 2
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
    p = sub.add_parser("maskele", help="kişisel veri maskeleme: kanıtların (evidence/) yayın kopyası ya da "
                                       "--kaynak ile bölüm klasörünün model öncesi maskeli kopyası; "
                                       "asıl dosyalar değişmez")
    p.add_argument("--workspace", "-w", default=None,
                   help="çalışma alanı (evidence modu için zorunlu; --kaynak modunda config.yaml kuralları için)")
    p.add_argument("--evidence", default=None, help="kanıt klasörü (varsayılan <ws>/evidence)")
    p.add_argument("--kaynak", default=None,
                   help="model öncesi maskeleme: bölüm belge klasörü (salt okunur); maskeli kopya --out'a yazılır")
    p.add_argument("--out", default=None, help="evidence modu: çıktı kökü (varsayılan kanıt klasörünün üstü); "
                                               "--kaynak modu: maskeli kopya klasörü (zorunlu)")
    p.add_argument("--rapor", default=None,
                   help="--kaynak modu: rapor yolu (varsayılan <out>.maskeleme-raporu.json, çıktının dışında)")
    p.add_argument("--ayir", action="store_true",
                   help="--kaynak modu: maskelemesi eksik kalan/maskelenemeyen dosyalar maskeli kopyaya girmez; "
                        "<out>.elle-bakilmali/ klasörüne ayrılır ve raporda listelenir (varsayılan: kopyada kalır)")
    p.add_argument("--is", dest="is_", type=int, default=1, help="--kaynak modu: paralel işçi sayısı")
    p.add_argument("--ilerleme", action="store_true", help="--kaynak modu: dosya başına ilerleme yaz")
    p.add_argument("--motor", choices=("auto", "pymupdf", "pypdf"), default="auto",
                   help="PDF motoru: pymupdf gerçek kaldırma; pypdf en iyi çaba (varsayılan: varsa pymupdf)")
    p.add_argument("--ad-listesi", default=None,
                   help="ek ad listesi (.txt satır başına bir ad ya da .csv ilk sütun); "
                        "config.yaml privacy.maskeleme.ad_listesi'ne eklenir")
    p.set_defaults(func=_run)
