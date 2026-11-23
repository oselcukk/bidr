"""`bidr guncel` (yerel sürüm ile uzak main'i karşılaştırır) ve `bidr guncelle` (temiz main'de
ileri sarma + gerekirse yeniden kurulum). Ayrıntı: `bidr/guncel/core.py`."""
from __future__ import annotations

import json


def _guncel(args) -> int:
    from .core import check, summary_lines
    d = check()
    if args.json:
        from .core import open_packages
        print(json.dumps({**d.to_dict(), "acik_paketler": open_packages(args.workspace)},
                         ensure_ascii=False, indent=1))
        return 0
    for ln in summary_lines(d, args.workspace):
        print(ln)
    return 0


def _guncelle(args) -> int:
    from .core import update
    return update(ws=args.workspace, force=args.yine_de)


def register(sub):
    p = sub.add_parser("guncel", help="bidr güncel mi: yerel commit/sürüm ile uzak main (çevrimdışıysa 'denetlenemedi')")
    p.add_argument("--workspace", "-w", help="çalışma alanı: açık iş paketi varsa güncellemeyi aşama sınırına bırakır")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_guncel)
    p = sub.add_parser("guncelle", help="bidr'i güncelle: temiz main'de git ileri sarma, gerekirse yeniden kurulum, özet")
    p.add_argument("--workspace", "-w", help="çalışma alanı: açık iş paketi varken durur; sonra AGENTS.md ve skill'leri yeniler")
    p.add_argument("--yine-de", action="store_true",
                   help="açık iş paketi olsa da güncelle (yalnız kullanıcı isterse)")
    p.set_defaults(func=_guncelle)
