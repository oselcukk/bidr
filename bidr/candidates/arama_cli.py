"""`bidr arama`: kanıtsız/zayıf ölçütler için ikinci, genişletilmiş arama (ajan modu)."""
from __future__ import annotations

import json
import sys


def _run(args) -> int:
    from bidr.common import Workspace

    ws = Workspace(args.workspace)
    if args.action == "olcum":
        from bidr.evaluate.ikinci_arama import format_table, measure
        res = measure(ws.root, args.review)
        print(json.dumps(res, ensure_ascii=False, indent=1) if args.json else format_table(res))
        return 0
    if args.action == "prepare":
        # Aşama kapısı: zayıf ölçütler audit'in (insan incelemesinden geçmiş) OD'sinden seçilir;
        # audit bitmeden paket hazırlanmaz (yönetilen çalışma alanında; bidr/pipeline/gate.py).
        from bidr.pipeline.gate import check_gate
        if (rc := check_gate(ws.root, "ikinci_arama")) is not None:
            print("HATA `bidr arama prepare` audit bittikten sonra çalışır: zayıf ölçütler incelenmiş "
                  "audit OD'sinden seçilir (review.xlsx kararları → `bidr audit apply`). "
                  f"Sıradaki adım için: bidr next -w {ws.root}", file=sys.stderr)
            return rc
    if not ws.text_dir.exists():
        print(f"text/ yok: {ws.text_dir}")
        return 2
    if not (ws.root / "decisions.jsonl").exists():
        print("decisions.jsonl yok: ikinci arama ilk geçişin ince kararlarından sonra çalışır")
        return 2
    from . import arama as A
    if args.action == "prepare":
        olc = [x for x in (args.olcut or "").replace(" ", ",").split(",") if x] or None
        st = A.prepare(ws.root, profile=args.profile or None, n=args.n, max_aday=args.max_aday,
                       od_esik=args.od_esik, olcutler=olc, synonyms=not args.no_esanlam, redo=args.redo,
                       capraz=not args.no_capraz)
        z = st["zayif"]
        print(f"zayıf ölçüt: {len(z)} (kaynak: {'audit-olcutler.json' if st['audit'] else 'decisions.jsonl, yaklaşık'})")
        for c, info in z.items():
            sec = st["secim"].get(c) or []
            cap = [d for d in st["secim_capraz"].get(c) or [] if d not in sec]
            print(f"  {c}: {', '.join(info['nedenler'])} → {len(sec)} belge"
                  + (f" + {len(cap)} çapraz" if cap else ""))
        print(f"{st['paket']} paket ({st['yeni']} yeni/değişen), bekleyen {st['bekleyen']} → {st['klasor']}"
              + (f"; belge başına sınırdan kesilen ölçüt {st['kesilen']}" if st["kesilen"] else ""))
        print(f"çapraz yol: başka ölçütte kabul edilmiş birim belgesi {st['capraz_havuz']}, "
              f"paketlenen {st['capraz_paket']} belge / {st['capraz_cift']} (belge, ölçüt) çifti")
        print(f"seçilmeyen belge: ince kararı yok={st['ince_yok']} hariç tür/metin={st['haric']} "
              f"başka birim={st['baska_birim']} devralan={st['devralan']}")
        print(f"Ajan: {st['klasor']}/README.md")
        return 0
    from bidr.pipeline.paralel import apply_oncesi
    apply_oncesi(ws.root, "work/ikinci_arama")   # parça dışı yazılmış/ezilmiş cevap reddedilir
    st = A.apply(ws.root, model=args.model)
    print(f"işlenen={st['islenen']} değişmeyen={st['degismedi']} bekleyen={len(st['bekleyen'])} "
          f"geçersiz={len(st['gecersiz'])} eski paket={len(st['eski_paket'])} eski sürüm={len(st['eski_surum'])}; "
          f"eklenen eşleşme kabul={st['eklenen_kabul']} red={st['eklenen_red']}")
    for did, errs in st["gecersiz"].items():
        print(f"  geçersiz {did}: {'; '.join(errs)}")
    if st["eklenen_kabul"]:
        print("decisions.jsonl değişti: `bidr audit` yeniden çalıştırılmalı (eşleşmeler `ikinci_arama` işaretli)")
    return 1 if st["gecersiz"] else 0


def register(sub):
    p = sub.add_parser("arama", help="kanıtsız/zayıf ölçütler için arşivde ikinci arama (ajan modu, işaretli eşleşmeler)")
    act = p.add_subparsers(dest="action", required=True)
    a = act.add_parser("prepare", help="zayıf ölçütleri bul, arşivde ara → work/ikinci_arama/<doc_id>.json")
    a.add_argument("--workspace", "-w", required=True)
    a.add_argument("--profile", default="akademik_bolum", help="birim profili (vars. akademik_bolum)")
    a.add_argument("--n", type=int, default=5, help="ölçüt başına en çok belge (vars. 5)")
    a.add_argument("--max-aday", type=int, default=6, help="pakette en çok ölçüt (vars. 6)")
    a.add_argument("--od-esik", type=int, default=2, help="bu OD ve altı zayıf sayılır (vars. 2)")
    a.add_argument("--olcut", help="zayıflık hesaplama, yalnız bu ölçütleri ara (virgülle)")
    a.add_argument("--no-esanlam", action="store_true", help="eşanlamlı genişletmeyi kapat")
    a.add_argument("--redo", action="store_true", help="ikinci aramayla bakılmış (belge, ölçüt) çiftlerini de paketle")
    a.add_argument("--no-capraz", action="store_true",
                   help="çapraz yolu kapat (başka ölçütte kabul edilmiş birim belgelerini zayıf ölçütlere sorma)")
    a.set_defaults(func=_run)
    a = act.add_parser("apply", help="<doc_id>.out.json cevaplarını denetle, işaretli eşleşme olarak ekle")
    a.add_argument("--workspace", "-w", required=True)
    a.add_argument("--model", default="ajan:belirtilmemis", help="cevapları üreten ajan/model")
    a.set_defaults(func=_run)
    a = act.add_parser("olcum", help="ikinci arama eşleşmelerinin kod/insan kabul-ret sayıları")
    a.add_argument("--workspace", "-w", required=True)
    a.add_argument("--review", help="review-decisions.jsonl (vars. WS içinde)")
    a.add_argument("--json", action="store_true")
    a.set_defaults(func=_run)
