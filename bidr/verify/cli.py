"""`bidr verify prepare|apply`."""
from __future__ import annotations


def _cmd(args) -> int:
    from bidr.pipeline.gate import check_gate
    if (rc := check_gate(args.workspace, "verify")) is not None:
        return rc
    from bidr.write.cli import olcut_list

    from . import run as R

    try:
        if args.action == "prepare":
            st = R.prepare(args.workspace, only=olcut_list(args.only), redo=args.redo, index=args.index,
                           audit=args.audit, onceki=args.onceki, notes=args.notlar)
            print(f"{st['metin']} metin: {st['paket']} paket ({st['yeni']} yeni/değişen), "
                  f"zaten_tamam={st['zaten_tamam']}, kod denetiminde reddedilen={len(st['kod_reddi'])}, "
                  f"bekleyen {st['bekleyen']} → {st['klasor']}")
            for c, why in st["kod_reddi"].items():
                print(f"  reddedildi {c} (kod):")
                for w in why:
                    print(f"    - {w}")
            print(f"Ajan (metni yazandan bağımsız olmalı): {st['klasor']}/README.md")
            return 1 if st["kod_reddi"] else 0
        st = R.apply(args.workspace, model=args.model)
    except (FileNotFoundError, KeyError) as e:
        print(f"HATA {e}")
        return 2
    print(f"dogrulandi={len(st['dogrulandi'])} reddedildi={len(st['reddedildi'])} değişmedi={st['degismedi']} "
          f"bekleyen={len(st['bekleyen'])} geçersiz={len(st['gecersiz'])} eski paket={len(st['eski'])}")
    for c, why in st["reddedildi"].items():
        print(f"  reddedildi {c}:")
        for w in why:
            print(f"    - {w}")
    for c, errs in st["gecersiz"].items():
        print(f"  geçersiz cevap {c}: {'; '.join(errs)}")
    if st["eski"]:
        print(f"  eski paket (metin değişti; yeniden prepare): {', '.join(st['eski'])}")
    return 1 if st["gecersiz"] or st["reddedildi"] else 0


def register(sub):
    p = sub.add_parser("verify", help="metin doğrulama: kod + bağımsız ajan → verify.jsonl")
    act = p.add_subparsers(dest="action", required=True)
    a = act.add_parser("prepare", help="kod denetimi + iş paketleri work/verify/<ölçüt>.json")
    a.add_argument("--workspace", "-w", required=True)
    a.add_argument("--only", metavar="OLCUT[,…]", help="yalnız bu ölçütler (doğrulanmış olsalar da)")
    a.add_argument("--redo", action="store_true", help="doğrulanmış metinleri de yeniden paketle")
    a.add_argument("--index", help="evidence-index.csv (vars. son write prepare'in kullandığı)")
    a.add_argument("--audit", help="audit-olcutler.json (vars. son write prepare'in kullandığı)")
    a.add_argument("--onceki", help="geçen yılın raporu/klasörü (vars. son write prepare'in kullandığı)")
    a.add_argument("--notlar", help="komisyon bilgisi YAML'ı (vars. son write prepare'in kullandığı)")
    a.set_defaults(func=_cmd)
    a = act.add_parser("apply", help="<ölçüt>.out.json kararlarını işle: dogrulandi / reddedildi")
    a.add_argument("--workspace", "-w", required=True)
    a.add_argument("--model", default="ajan:belirtilmemis", help="doğrulayan ajan/model (kayda geçer)")
    a.set_defaults(func=_cmd)
