"""`bidr candidates`: belge başına sıralı aday alt ölçütler → candidates.jsonl."""
from __future__ import annotations

from pathlib import Path


def _run(args) -> int:
    from bidr.common import Workspace

    from .model import DEFAULT_COMBO, SIGNALS
    from .run import run

    ws = Workspace(args.workspace)
    if not ws.text_dir.exists():
        print(f"text/ yok: {ws.text_dir}")
        return 2
    signals = tuple(s for s in (args.signals or "").split(",") if s) or DEFAULT_COMBO
    bad = [s for s in signals if s not in SIGNALS]
    if bad:
        print(f"bilinmeyen sinyal: {', '.join(bad)} (geçerli: {', '.join(SIGNALS)})")
        return 2
    out, oz = run(ws.root, [Path(t) for t in args.train or []], k=args.k, out_name=args.out,
                  profile=args.profile, signals=signals)
    print(f"{oz['belge']} belge → {out} (eğitim: {oz['egitim_belgesi']} etiketli belge, "
          f"türlü belge: {oz['tur_bilgisi']}, öz-referans türü dışlanan: {oz['haric_tur']})")
    print(f"birleşik: {'+'.join(oz['birlesik'])}; aday ölçüt: {oz['olcut']}"
          + (f" (profil {oz['profil']})" if oz["profil"] else ""))
    for d in oz.get("profil_kararlari", []):
        print(f"  {d['olcut']}: {d['karar']} ({d['gerekce']}) → {'aday' if d['aday'] else 'düşer'}")
    d = oz["durum"]
    print(f"durum: ok={d['ok']} kisa={d['kisa']} bos={d['bos']} metin_yok={d['metin_yok']}")
    for s in oz["sorunlu"]:
        print(f"  {s['durum']:9} {s['doc_id']} ({s['chars']} karakter)")
    return 0


def register(sub):
    p = sub.add_parser("candidates", help="belge başına aday ölçütler (metin + yuva + komşu + tür) → candidates.jsonl")
    p.add_argument("--workspace", "-w", required=True)
    p.add_argument("--train", action="append", metavar="WS",
                   help="etiketli eğitim çalışma klasörü (tekrarlanabilir); aynı içerik kendine komşu olmaz")
    p.add_argument("--k", type=int, default=10, help="belge başına aday sayısı (varsayılan 10)")
    p.add_argument("--profile", help="birim profili (ör. akademik_bolum): doldurmayacağı ölçütler düşer")
    p.add_argument("--signals", help="birleşik sinyaller, virgülle (vars. bm25,yuva,knn,tur,oncel; ör. yuva,knn,tur,oncel)")
    p.add_argument("--out", default="candidates.jsonl", help="çıktı dosya adı (WS içinde)")
    p.set_defaults(func=_run)
