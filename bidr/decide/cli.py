"""`bidr decide` ve `bidr compare-labels`."""
from __future__ import annotations


def _common(args):
    return dict(profile=args.profile or None, only_labeled=args.only_labeled, limit=args.limit,
                k=args.k, max_aday=args.max_aday)


def _stats(st: dict) -> str:
    return (f"ok={st['ok']} (kaba={st['kaba']} ince={st['ince']}) atlandi={st['atlandi']} hata={st['hata']}; "
            f"olcut_var={st['olcut_var']} olcut_yok={st['olcut_yok']} kanit_degil={st['kanit_degil']}; "
            f"eşleşme kabul={st['kabul_eslesme']} red={st['reddedilen_eslesme']}")


def _decide(args) -> int:
    from bidr.pipeline.gate import check_gate

    stage = "karar_ince" if getattr(args, "stage", None) == "fine" else "karar_kaba"
    if (rc := check_gate(args.workspace, stage)) is not None:
        return rc
    from bidr.common import Workspace

    from . import run as R

    ws = Workspace(args.workspace)
    if not ws.text_dir.exists():
        print(f"text/ yok: {ws.text_dir}")
        return 2
    if args.action == "prepare":
        st = R.prepare(ws.root, args.stage, redo=args.redo, **_common(args))
        print(f"{st['paket']} paket ({st['yeni']} yeni/değişen), bekleyen {st['bekleyen']} → {st['klasor']}")
        print(f"atlandi={st['atlandi']} zaten_tamam={st['zaten_tamam']} kaba_yok={st['kaba_yok']} "
              f"aday_yok={st['aday_yok']}")
        print(f"Ajan: {st['klasor']}/README.md")
        return 0
    if args.action == "apply":
        st = R.apply(ws.root, args.stage, model=args.model)
        print(f"işlenen={st['islenen']} bekleyen={len(st['bekleyen'])} geçersiz={len(st['gecersiz'])} "
              f"alıntısı tutmayan belge={len(st['alinti_tutmayan'])} eski sürüm={len(st['eski_surum'])}")
        for did, errs in st["gecersiz"].items():
            print(f"  geçersiz {did}: {'; '.join(errs)}")
        print(_stats(st["durum"]))
        return 1 if st["gecersiz"] else 0
    out, st = R.run(ws.root, log=(lambda m: None) if args.quiet else print, **_common(args))
    print(f"{st['belge']} belge → {out}")
    print(_stats(st))
    return 0


def _compare(args) -> int:
    from bidr.pipeline.gate import check_gate

    if (rc := check_gate(args.workspace, "hakem")) is not None:
        return rc
    from bidr.common import Workspace

    from .compare import FILES, consensus, run

    ws = Workspace(args.workspace)
    if args.apply:
        out, st = consensus(ws.root)
        print(f"{st['belge']} belge → {out}; tamam={st['tamam']} açık soru={st['acik_soru']}; "
              f"eklenen={st['eklenen']} kaldırılan={st['kaldirilan']} od değişen={st['od_degisen']}")
        if st["gecersiz_cevap"]:
            print("geçersiz cevap: " + ", ".join(st["gecersiz_cevap"]))
        return 0
    if not (ws.root / args.decisions).exists():
        print(f"{args.decisions} yok; önce `bidr decide`")
        return 2
    _, st = run(ws.root, decisions=args.decisions)
    print(f"{st['belge']} etiketli belge karşılaştırıldı ({st['atlanan']} atlandı); "
          f"{st['soru']} hakem sorusu {st['tur']} → {FILES['compare']}, {FILES['review_md']}, "
          f"{FILES['review_jsonl']}" + (f"; md'den toplanan cevap: {st['toplanan_cevap']}"
                                        if st["toplanan_cevap"] else ""))
    return 0


def _sel(p, stage: bool):
    p.add_argument("--workspace", "-w", required=True)
    if stage:
        p.add_argument("--stage", choices=("coarse", "fine"), required=True)
    p.add_argument("--profile", default="akademik_bolum",
                   help="birim profili (vars. akademik_bolum; boş dize = 46 ölçütün hepsi)")
    p.add_argument("--only-labeled", action="store_true", help="yalnız geçmiş etiketi olan belgeler")
    p.add_argument("--limit", type=int, help="en çok N belge")
    p.add_argument("--k", type=int, default=5, help="candidates.jsonl'den alınan ilk k aday (vars. 5)")
    p.add_argument("--max-aday", type=int, default=6, help="ince karara giden en çok aday (vars. 6)")


def register(sub):
    p = sub.add_parser("decide", help="model kararı (kaba seçim + rubrikli ince karar, alıntı denetimli) → decisions.jsonl")
    act = p.add_subparsers(dest="action", required=True)
    a = act.add_parser("prepare", help="ajan modu: iş paketleri work/<aşama>/<doc_id>.json")
    _sel(a, True)
    a.add_argument("--redo", action="store_true", help="işlenmiş belgeleri de yeniden paketle")
    a.set_defaults(func=_decide)
    a = act.add_parser("apply", help="ajan modu: <doc_id>.out.json cevaplarını doğrula ve işle")
    a.add_argument("--workspace", "-w", required=True)
    a.add_argument("--stage", choices=("coarse", "fine"), required=True)
    a.add_argument("--model", default="ajan:belirtilmemis",
                   help="cevapları üreten ajan/model (kayda geçer; ör. claude-code:opus)")
    a.set_defaults(func=_decide)
    a = act.add_parser("run", help="sağlayıcı modu: bidr.llm.run_task ile kaba + ince")
    _sel(a, False)
    a.add_argument("--quiet", "-q", action="store_true")
    a.set_defaults(func=_decide)

    q = sub.add_parser("compare-labels", help="model kararı ↔ geçmiş etiket; hakem kuyruğu; --apply ile uzlaşı")
    q.add_argument("--workspace", "-w", required=True)
    q.add_argument("--decisions", default="decisions.jsonl")
    q.add_argument("--apply", action="store_true",
                   help="hakem cevaplarından (label-review.md / label-answers.jsonl) consensus-labels.jsonl yaz")
    q.set_defaults(func=_compare)
