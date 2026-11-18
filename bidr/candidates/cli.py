"""`bidr candidates`: belge başına sıralı aday alt ölçütler → candidates.jsonl."""
from __future__ import annotations

from pathlib import Path


def _run(args) -> int:
    from bidr.common import Workspace

    from .run import run

    ws = Workspace(args.workspace)
    if not ws.text_dir.exists():
        print(f"text/ yok: {ws.text_dir}")
        return 2
    out, oz = run(ws.root, [Path(t) for t in args.train or []], k=args.k)
    print(f"{oz['belge']} belge → {out} (eğitim: {oz['egitim_belgesi']} etiketli belge, "
          f"türlü belge: {oz['tur_bilgisi']})")
    d = oz["durum"]
    print(f"durum: ok={d['ok']} kisa={d['kisa']} bos={d['bos']} metin_yok={d['metin_yok']}")
    for s in oz["sorunlu"]:
        print(f"  {s['durum']:9} {s['doc_id']} ({s['chars']} karakter)")
    return 0


def register(sub):
    p = sub.add_parser("candidates", help="belge başına aday ölçütler (metin + komşu + tür) → candidates.jsonl")
    p.add_argument("--workspace", "-w", required=True)
    p.add_argument("--train", action="append", metavar="WS",
                   help="etiketli eğitim çalışma klasörü (tekrarlanabilir); aynı içerik kendine komşu olmaz")
    p.add_argument("--k", type=int, default=10, help="belge başına aday sayısı (varsayılan 10)")
    p.set_defaults(func=_run)
