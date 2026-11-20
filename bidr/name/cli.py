"""`bidr name prepare|apply -w WS [--only DOC_ID,…]`: işlenmiş belgelere kanıt adı."""
from __future__ import annotations

import argparse
import sys


def _ids(s: str | None) -> list[str] | None:
    import re
    return [x for x in re.split(r"[,\s]+", s) if x] if s else None


def _cmd(args) -> int:
    from bidr.common import Workspace
    from bidr.pipeline.gate import check_gate

    from . import run as R
    if (rc := check_gate(args.workspace, "name")) is not None:
        return rc
    ws = Workspace(args.workspace)
    only = _ids(args.only)
    if only is not None:
        from bidr.decide.run import resolve_ids
        only, errs = resolve_ids(ws, only)
        if errs:
            print("belge kimliği hatası: " + "; ".join(errs), file=sys.stderr)
            return 2
    try:
        if args.action == "prepare":
            st = R.prepare(ws.root, only=only, redo=args.redo, parca=args.parca)
            print(f"{st['paket']} paket ({st['yeni']} yeni/değişen), zaten adlı={st['zaten_adli']}, "
                  f"bekleyen {st['bekleyen']} → {st['klasor']}"
                  + (f" (parça adı için derleme belgesi: {st['derleme']})" if st.get("derleme") else ""))
            if st["uygun_degil"]:
                print("kabul edilmiş eşleşmesi yok ya da mükerrer kopya (paketlenmedi): "
                      + ", ".join(st["uygun_degil"]))
            print(f"Ajan: {st['klasor']}/README.md")
            return 0
        st = R.apply(ws.root, model=args.model, only=only)
    except FileNotFoundError as e:
        print(f"HATA {e}", file=sys.stderr)
        return 2
    print(f"işlenen={st['islenen']} değişmedi={st['degismedi']} bekleyen={len(st['bekleyen'])} "
          f"geçersiz={len(st['gecersiz'])} reddedilen={len(st['reddedilen'])} "
          f"eski sürüm={len(st['eski_surum'])} doğrulanmalı={len(st['dogrulanmali'])} "
          f"parça adlı={len(st['parca'])} → {st['dosya']}")
    for did, errs in st["gecersiz"].items():
        print(f"  geçersiz {did}: {'; '.join(errs)}")
    for did, x in st["reddedilen"].items():
        print(f"  reddedildi {did} ({', '.join(x['neden'])}): {x['oneri']}")
    for did, x in st["dogrulanmali"].items():
        why = x["belge"] + ([f"parca_uyumsuz: {', '.join(x['parca_uyumsuz'])}"] if x["parca_uyumsuz"] else [])
        print(f"  doğrulanmalı {did} ({'; '.join(why)}): {x['ad']}")
    for did, notes in st["parca_not"].items():
        print(f"  parça adı notu {did}: {'; '.join(notes)}")
    return 1 if (st["gecersiz"] or st["reddedilen"]) else 0


def register(sub):
    p = sub.add_parser("name", help="ajan modu: işlenmiş belgelere kanıt adı (kanit-adlari.jsonl, kaynak: model)")
    act = p.add_subparsers(dest="action", required=True)
    a = act.add_parser("prepare", help="iş paketleri: work/name/<doc_id>.json")
    a.add_argument("--workspace", "-w", required=True)
    a.add_argument("--only", metavar="DOC_ID[,…]", help="yalnız bu belgeler (adı olsa da yeniden paketlenir)")
    a.add_argument("--redo", action="store_true", help="model adı olan belgeleri de paketle")
    a.add_argument("--parca", action=argparse.BooleanOptionalAction, default=True,
                   help="adı olan ama derleme olduğu saptanan belgeleri parça adı için (yeniden) paketle "
                        "(varsayılan; --no-parca kapatır)")
    a.set_defaults(func=_cmd)
    a = act.add_parser("apply", help="<doc_id>.out.json cevaplarını doğrula ve kanit-adlari.jsonl'e yaz")
    a.add_argument("--workspace", "-w", required=True)
    a.add_argument("--model", default="ajan:belirtilmemis", help="cevabı yazan ajan/model (kayda geçer)")
    a.add_argument("--only", metavar="DOC_ID[,…]")
    a.set_defaults(func=_cmd)
