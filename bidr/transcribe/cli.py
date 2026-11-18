"""`bidr transcribe prepare|apply`."""
from __future__ import annotations


def _ids(s: str | None) -> list[str] | None:
    return [x.strip() for x in s.split(",") if x.strip()] if s else None


def _gate(ws) -> int | None:
    """Aşama pipeline.yaml'a kayıtlıysa kapısını uygula; değilse (henüz kayıtsız) geç."""
    from bidr.pipeline.state import load_spec
    if not any(s.get("id") == "transcribe" for s in load_spec().get("asamalar", [])):
        return None
    from bidr.pipeline.gate import check_gate
    return check_gate(ws, "transcribe")


def _cmd(args) -> int:
    if (rc := _gate(args.workspace)) is not None:
        return rc
    from . import run as R

    if args.action == "prepare":
        only = _ids(args.only)
        if not only and not args.all_low_quality:
            print("seçim yok: --only DOC_ID,… ya da --all-low-quality verin")
            return 2
        st = R.prepare(args.workspace, only=only, all_low_quality=args.all_low_quality,
                       source=args.source, dpi=args.dpi, max_pages=args.max_pages,
                       limit=args.limit, redo=args.redo)
        print(f"{st['paket']} paket ({st['yeni']} yeni/değişen), zaten_tamam={st['zaten_tamam']}, "
              f"bekleyen {st['bekleyen']} → {st['klasor']}")
        for did, why in st["atlandi"].items():
            print(f"  atlandı {did}: {why}")
        print(f"Ajan: {st['klasor']}/README.md")
        return 0
    st = R.apply(args.workspace, model=args.model, accept_suspicious=args.kabul_supheli,
                 only=_ids(args.only))
    print(f"işlenen={st['islenen']} değişmedi={st['degismedi']} bekleyen={len(st['bekleyen'])} "
          f"geçersiz={len(st['gecersiz'])} şüpheli={len(st['supheli'])} eski sürüm={len(st['eski_surum'])}")
    for did, c in sorted(st["tutarlilik"].items()):
        print(f"  {did}: {c['durum']} örtüşme={c['oran']} [okunamadı]={c['okunamadi']}")
    for did, errs in st["gecersiz"].items():
        print(f"  geçersiz {did}: {'; '.join(errs)}")
    if st["degisen"]:
        g = st["gecersiz_kilinan"]
        print(f"metni değişen {len(st['degisen'])} belge: documents -{g['documents']}, candidates "
              f"-{g['candidates']}, decisions metin_degisti={g['decisions']}, karar paketi .eski={g['paket']}")
        print("Sonra: bidr identify, bidr candidates, bidr decide prepare/apply (bidr next sırayı verir)")
    return 1 if (st["gecersiz"] or st["supheli"]) else 0


def register(sub):
    p = sub.add_parser("transcribe", help="ajan modu: düşük kaliteli belgeleri sayfa görüntüsünden yazıya geçir")
    act = p.add_subparsers(dest="action", required=True)
    a = act.add_parser("prepare", help="sayfa görüntüleri + iş paketi: work/transcribe/<doc_id>/")
    a.add_argument("--workspace", "-w", required=True)
    a.add_argument("--only", help="virgülle ayrılmış doc_id listesi")
    a.add_argument("--all-low-quality", action="store_true", help="inventory.csv'de low_quality=1 olanların hepsi")
    a.add_argument("--source", help="kaynak klasör (vars. config.yaml bidr.kaynak); salt okunur")
    a.add_argument("--dpi", type=int, default=200, help="PDF sayfa görüntüsü çözünürlüğü (vars. 200)")
    a.add_argument("--max-pages", type=int, default=40, help="bundan uzun belge atlanır (vars. 40)")
    a.add_argument("--limit", type=int)
    a.add_argument("--redo", action="store_true", help="yazıya geçirilmiş belgeleri de yeniden paketle")
    a.set_defaults(func=_cmd)
    a = act.add_parser("apply", help="<doc_id>.out.json cevaplarını doğrula ve belge metni yap")
    a.add_argument("--workspace", "-w", required=True)
    a.add_argument("--model", default="ajan:belirtilmemis", help="cevabı yazan ajan/model (kayda geçer)")
    a.add_argument("--only", help="yalnız bu doc_id'ler")
    a.add_argument("--kabul-supheli", action="store_true",
                   help="OCR'la örtüşmeyen (şüpheli) cevapları da uygula (kayıtta işaretli kalır)")
    a.set_defaults(func=_cmd)
