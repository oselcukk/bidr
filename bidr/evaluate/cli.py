"""`bidr evaluate`: aday ölçüt taban çizgisi (recall@k, MRR; sinyal × bölme)."""
from __future__ import annotations

import json
from pathlib import Path


def _run(args) -> int:
    from .run import report_md, evaluate

    louo = [Path(p).expanduser() for p in args.louo or []]
    transfers = [(Path(a).expanduser(), Path(b).expanduser()) for a, b in args.transfer or []]
    if not louo and not transfers:
        print("en az bir --louo veya --transfer gerekli")
        return 2
    units = [u for u in (args.units or "").split(",") if u] or None
    ex = None if not args.no_exclude_types else frozenset()
    results, meta = evaluate(louo, transfers, units, profile=args.profile, exclude_types=ex)
    md = report_md(args.name, results, meta)
    data = {"ad": args.name, "ayarlar": meta, "sonuclar": results}
    outs = [Path(p).expanduser() for p in args.out] if args.out else \
        list(dict.fromkeys([*louo, *(b for _, b in transfers)]))
    for o in outs:
        o.mkdir(parents=True, exist_ok=True)
        (o / f"eval-{args.name}.md").write_text(md, encoding="utf-8")
        (o / f"eval-{args.name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                                  encoding="utf-8")
        print(f"→ {o / f'eval-{args.name}.md'}")
    if not args.quiet:
        print(md)
    return 0


def register(sub):
    p = sub.add_parser("evaluate", help="aday ölçüt sıralamasını insan etiketlerine karşı ölç")
    p.add_argument("--louo", action="append", metavar="WS",
                   help="bu WS içinde birim dışarıda bırakmalı bölme (tekrarlanabilir)")
    p.add_argument("--transfer", nargs=2, action="append", metavar=("EĞİTİM_WS", "TEST_WS"),
                   help="eğitim WS ile eğit, test WS'de sına (ortak içerik eğitimden atılır)")
    p.add_argument("--units", help="LOUO birimleri, virgülle (varsayılan: etiketlerdeki tüm birimler)")
    p.add_argument("--name", default="baseline", help="çıktı adı: eval-<ad>.md/json")
    p.add_argument("--out", action="append", metavar="KLASÖR",
                   help="çıktı klasörü (varsayılan: her test WS)")
    p.add_argument("--profile", help="birim profili (ör. akademik_bolum): yalnız doldurulacak ölçütler sıralanır")
    p.add_argument("--no-exclude-types", action="store_true",
                   help="öz-referans türlerini (profiles/haric_turler.yaml) dışlama")
    p.add_argument("--quiet", "-q", action="store_true")
    p.set_defaults(func=_run)
