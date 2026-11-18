"""`bidr describe prepare|apply`."""
from __future__ import annotations


def _ids(s: str | None) -> list[str] | None:
    return [x.strip() for x in s.split(",") if x.strip()] if s else None


def _cmd(args) -> int:
    from bidr.pipeline.gate import check_gate
    if (rc := check_gate(args.workspace, "describe")) is not None:
        return rc
    from . import run as R

    if args.action == "prepare":
        only = _ids(args.only)
        if not only and not args.auto:
            print("seçim yok: --only DOC_ID,… ya da --auto verin")
            return 2
        st = R.prepare(args.workspace, only=only, auto=args.auto, source=args.source, dpi=args.dpi,
                       max_images=args.max_images, limit=args.limit, redo=args.redo)
        sec = f"seçilen={st['secilen']}, " if args.auto else ""
        print(f"{sec}{st['paket']} paket ({st['yeni']} yeni/değişen), zaten_tamam={st['zaten_tamam']}, "
              f"bekleyen {st['bekleyen']} → {st['klasor']}")
        for did, why in st["atlandi"].items():
            print(f"  atlandı {did}: {why}")
        print(f"Ajan: {st['klasor']}/README.md")
        return 0
    st = R.apply(args.workspace, model=args.model, accept_suspicious=args.kabul_supheli,
                 only=_ids(args.only))
    print(f"işlenen={st['islenen']} değişmedi={st['degismedi']} metin_belgesi={len(st['metin_belgesi'])} "
          f"bekleyen={len(st['bekleyen'])} geçersiz={len(st['gecersiz'])} şüpheli={len(st['supheli'])} "
          f"eski sürüm={len(st['eski_surum'])}")
    for did, c in sorted(st["tutarlilik"].items()):
        print(f"  {did}: görünen yazı ↔ OCR {c['durum']} örtüşme={c['oran']}")
    for did in st["metin_belgesi"]:
        print(f"  {did}: ajan 'metin sayfası' dedi; betimlenmedi → bidr transcribe prepare --only {did}")
    for did, errs in st["gecersiz"].items():
        print(f"  geçersiz {did}: {'; '.join(errs)}")
    if st["degisen"]:
        g = st["gecersiz_kilinan"]
        print(f"metni değişen {len(st['degisen'])} belge: documents -{g['documents']}, candidates "
              f"-{g['candidates']}, decisions metin_degisti={g['decisions']}, karar paketi .eski={g['paket']}")
        print("Sonra: bidr identify, bidr candidates, bidr decide prepare/apply (bidr next sırayı verir)")
    return 1 if (st["gecersiz"] or st["supheli"]) else 0


def register(sub):
    p = sub.add_parser("describe", help="ajan modu: metni az görüntüleri (fotoğraf, afiş, tabela) betimlet")
    act = p.add_subparsers(dest="action", required=True)
    a = act.add_parser("prepare", help="görüntüler + iş paketi: work/describe/<doc_id>/")
    a.add_argument("--workspace", "-w", required=True)
    a.add_argument("--only", help="virgülle ayrılmış doc_id listesi (seyreklik aranmaz)")
    a.add_argument("--auto", action="store_true",
                   help="envanterden seç: metni seyrek görüntü dosyaları, görsel ağırlıklı PDF sayfaları, "
                        "gövdesi seyrek docx'lerin gömülü görselleri")
    a.add_argument("--source", help="kaynak klasör (vars. config.yaml bidr.kaynak); salt okunur")
    a.add_argument("--dpi", type=int, default=150, help="PDF sayfa görüntüsü çözünürlüğü (vars. 150)")
    a.add_argument("--max-images", type=int, default=20, help="bundan çok görseli olan belge atlanır (vars. 20)")
    a.add_argument("--limit", type=int)
    a.add_argument("--redo", action="store_true", help="betimlenmiş belgeleri de yeniden paketle")
    a.set_defaults(func=_cmd)
    a = act.add_parser("apply", help="<doc_id>.out.json cevaplarını doğrula ve belge metnine yaz")
    a.add_argument("--workspace", "-w", required=True)
    a.add_argument("--model", default="ajan:belirtilmemis", help="cevabı yazan ajan/model (kayda geçer)")
    a.add_argument("--only", help="yalnız bu doc_id'ler")
    a.add_argument("--kabul-supheli", action="store_true",
                   help="görünen yazıları OCR'la örtüşmeyen (şüpheli) cevapları da uygula (kayıtta işaretli)")
    a.set_defaults(func=_cmd)
