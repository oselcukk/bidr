"""`bidr hakem sorular|cevap`: hakem kuyruğunu kullanıcıya sormak ve kararını kodla
denetleyerek `label-answers.jsonl`'e yazmak (bidr-hakem skill'i bunu kullanır).

Kuyruğu `bidr compare-labels` üretir; uzlaşıyı `bidr compare-labels --apply` yazar.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from bidr.common import Workspace, read_jsonl, write_jsonl


def _load(ws: Workspace):
    from bidr.decide.compare import FILES, load_answers, parse_review_md
    rp = ws.root / FILES["review_jsonl"]
    if not rp.exists():
        raise FileNotFoundError(f"{FILES['review_jsonl']} yok: önce `bidr compare-labels -w {ws.root}`")
    qs = list(read_jsonl(rp))
    ans = load_answers(ws)
    md = ws.root / FILES["review_md"]
    if md.exists():
        for a in parse_review_md(md.read_text(encoding="utf-8")):
            ans[a["soru_id"]] = {**ans.get(a["soru_id"], {}), **a}
    return qs, ans


def open_questions(ws_root: Path) -> tuple[list[dict], list[dict]]:
    """(cevapsız sorular, tüm sorular); geçersiz cevaplı soru cevapsız sayılır."""
    from bidr.decide.compare import parse_answer
    qs, ans = _load(Workspace(ws_root))
    op = [q for q in qs if not ((a := ans.get(q["soru_id"])) and parse_answer(q["tur"], a.get("karar", "")))]
    return op, qs


def record_answer(ws_root: Path, soru_id: str, karar: str, *, od: int | None = None,
                  not_: str | None = None) -> dict:
    """Cevabı denetler ve yazar (aynı soruya yeni cevap eskisinin yerine geçer)."""
    from bidr.decide.compare import FILES, OPTIONS, load_answers, parse_answer
    ws = Workspace(ws_root)
    qs = {q["soru_id"]: q for q in read_jsonl(ws.root / FILES["review_jsonl"])}
    q = qs.get(soru_id)
    if q is None:
        raise ValueError(f"böyle bir soru yok: {soru_id}")
    parsed = parse_answer(q["tur"], karar)
    if parsed is None:
        raise ValueError(f"geçersiz karar {karar!r}; {q['tur']} için seçenekler: {', '.join(OPTIONS[q['tur']])}")
    if od is not None and (parsed[0] != "ekle" or not 1 <= od <= 5):
        raise ValueError("--od yalnız `ekle` ile ve 1-5 arası verilir")
    rec = {"soru_id": soru_id, "karar": karar.strip(), "kaynak": "bidr hakem cevap"}
    if od is not None:
        rec["od"] = od
    if not_:
        rec["not"] = not_
    ans = load_answers(ws)
    ans[soru_id] = rec
    write_jsonl(ws.root / FILES["answers"], ans.values())
    return rec


def _sorular(args) -> int:
    from bidr.decide.compare import GROUP, _q_md
    try:
        op, qs = open_questions(Path(args.workspace))
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 2
    grp = op[:args.n]
    if args.json:
        print(json.dumps({"toplam": len(qs), "cevapsiz": len(op), "sorular": grp}, ensure_ascii=False, indent=1))
        return 0
    print(f"Hakem kuyruğu: {len(qs)} soru, {len(op)} cevapsız. Sıradaki {len(grp)} (grup boyu {GROUP}):\n")
    idx = {q["soru_id"]: i for i, q in enumerate(qs, 1)}
    for q in grp:
        print(_q_md(idx[q["soru_id"]], q).replace("\n- Karar: ", ""))
        print()
    if not op:
        print(f"Bütün sorular cevaplı. Sonraki: bidr compare-labels -w {args.workspace} --apply")
    return 0


def _cevap(args) -> int:
    try:
        rec = record_answer(Path(args.workspace), args.soru_id, args.karar, od=args.od, not_=args.not_)
    except (ValueError, FileNotFoundError) as e:
        print(f"HATA {e}", file=sys.stderr)
        return 2
    op, qs = open_questions(Path(args.workspace))
    print(f"yazıldı: {rec['soru_id']} = {rec['karar']}; cevapsız {len(op)}/{len(qs)}")
    return 0


def register(sub):
    p = sub.add_parser("hakem", help="hakem kuyruğu: cevapsız soruları göster, kullanıcının kararını yaz")
    a = p.add_subparsers(dest="hakem_cmd", required=True)
    s = a.add_parser("sorular", help="sıradaki cevapsız soruları göster (vars. 5)")
    s.add_argument("--workspace", "-w", required=True)
    s.add_argument("-n", type=int, default=5)
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=_sorular)
    c = a.add_parser("cevap", help="KULLANICININ kararını denetleyip label-answers.jsonl'e yaz")
    c.add_argument("--workspace", "-w", required=True)
    c.add_argument("soru_id")
    c.add_argument("karar", help="ekle|reddet|koru|kaldir|od_model|od_gecmis|od=N|belirsiz (soru türüne göre)")
    c.add_argument("--od", type=int, help="yalnız `ekle` ile: eklenen ölçütün OD'si (vars. model OD'si)")
    c.add_argument("--not", dest="not_", help="kısa not (ör. kullanıcının gerekçesi)")
    c.set_defaults(func=_cevap)
