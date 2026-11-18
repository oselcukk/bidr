"""`bidr labels build|stats`: insan etiketleri (değerlendirme seti)."""
from __future__ import annotations

from pathlib import Path

from bidr.common import Workspace, read_jsonl, write_jsonl


def _build(args) -> int:
    from .build import build
    from .stats import metin, rapor_md

    kaynak = Path(args.source).expanduser()
    if not kaynak.is_dir():
        print(f"kaynak klasör yok: {kaynak}")
        return 2
    ws = Workspace(args.workspace)
    ws.root.mkdir(parents=True, exist_ok=True)   # text/ ingest'in; burada açılmaz
    takma = {}
    for t in args.unit_alias or []:
        a, _, b = t.partition("=")
        takma[a] = b
    sonuc = build(kaynak, birim=args.unit, takma=takma, etiketsiz=args.etiketsiz or [],
                  raporlar=args.rapor)
    n = write_jsonl(ws.labels, sonuc.kayitlar)
    (ws.root / "labels-report.md").write_text(rapor_md(sonuc, str(kaynak), str(ws.root)), encoding="utf-8")
    print(f"{n} kayıt → {ws.labels}")
    print(metin(sonuc.kayitlar, ayrinti=False))
    return 0


def _stats(args) -> int:
    from .stats import istatistik, metin

    ws = Workspace(args.workspace)
    if not ws.labels.exists():
        print(f"labels.jsonl yok: {ws.labels}")
        return 2
    rows = list(read_jsonl(ws.labels))
    if args.json:
        import json

        st = istatistik(rows)
        print(json.dumps({b: {k: (dict(v) if hasattr(v, "items") else v) for k, v in s.items()}
                          for b, s in st.items()}, ensure_ascii=False, indent=1))
    else:
        print(metin(rows))
    return 0


def register(sub):
    p = sub.add_parser("labels", help="insan etiketleri (klasör/ad/rapor) → labels.jsonl")
    lsub = p.add_subparsers(dest="labels_cmd", required=True)

    b = lsub.add_parser("build", help="kaynak klasörden etiketleri çıkar")
    b.add_argument("source", help="kaynak klasör (salt okunur)")
    b.add_argument("--workspace", "-w", required=True)
    b.add_argument("--unit", help="tüm dosyalar bu birime ait (verilmezse birim = üst düzey alt klasör)")
    b.add_argument("--unit-alias", action="append", metavar="KLASÖR=BİRİM",
                   help="alt klasör adını birim adına çevir (tekrarlanabilir)")
    b.add_argument("--etiketsiz", action="append", metavar="GLOB",
                   help="bu kalıba uyan göreli yollar kaydedilir ama etiket kaynağı / eşleme hedefi olmaz")
    b.add_argument("--rapor", action="append", metavar="GÖRELİ_YOL",
                   help="rapor olarak okunacak docx (verilirse adından otomatik bulma kapanır)")
    b.set_defaults(func=_build)

    s = lsub.add_parser("stats", help="labels.jsonl özeti")
    s.add_argument("--workspace", "-w", required=True)
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=_stats)
