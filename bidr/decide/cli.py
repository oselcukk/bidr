"""`bidr decide` ve `bidr compare-labels`."""
from __future__ import annotations


def _decide(args) -> int:
    from bidr.common import Workspace

    from .run import run

    ws = Workspace(args.workspace)
    if not ws.text_dir.exists():
        print(f"text/ yok: {ws.text_dir}")
        return 2
    out, st = run(ws.root, profile=args.profile or None, only_labeled=args.only_labeled,
                  limit=args.limit, k=args.k, max_aday=args.max_aday,
                  log=(lambda m: None) if args.quiet else print)
    print(f"{st['belge']} belge → {out}")
    print(f"ok={st['ok']} atlandi={st['atlandi']} hata={st['hata']}; "
          f"olcut_var={st['olcut_var']} olcut_yok={st['olcut_yok']} kanit_degil={st['kanit_degil']}; "
          f"eşleşme kabul={st['kabul_eslesme']} red={st['reddedilen_eslesme']}")
    return 0


def _compare(args) -> int:
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


def register(sub):
    p = sub.add_parser("decide", help="model kararı (kaba seçim + rubrikli ince karar, alıntı denetimli) → decisions.jsonl")
    p.add_argument("--workspace", "-w", required=True)
    p.add_argument("--profile", default="akademik_bolum",
                   help="birim profili (vars. akademik_bolum; boş dize = 46 ölçütün hepsi)")
    p.add_argument("--only-labeled", action="store_true", help="yalnız geçmiş etiketi olan belgeler")
    p.add_argument("--limit", type=int, help="en çok N belge")
    p.add_argument("--k", type=int, default=5, help="candidates.jsonl'den alınan ilk k aday (vars. 5)")
    p.add_argument("--max-aday", type=int, default=6, help="ince karara giden en çok aday (vars. 6)")
    p.add_argument("--quiet", "-q", action="store_true")
    p.set_defaults(func=_decide)

    q = sub.add_parser("compare-labels", help="model kararı ↔ geçmiş etiket; hakem kuyruğu; --apply ile uzlaşı")
    q.add_argument("--workspace", "-w", required=True)
    q.add_argument("--decisions", default="decisions.jsonl")
    q.add_argument("--apply", action="store_true",
                   help="hakem cevaplarından (label-review.md / label-answers.jsonl) consensus-labels.jsonl yaz")
    q.set_defaults(func=_compare)
