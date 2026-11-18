"""`bidr render -w WS --sablon FR-0833.docx [--out report.docx] [--birim "…"] [--yil 2026]`."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _run(args) -> int:
    from .run import Options, render

    ws = Path(args.workspace).expanduser().resolve()
    birim = args.birim
    if birim is None:
        from bidr.init.config import load_section
        birim = (load_section(ws) or {}).get("birim")
    out = Path(args.out).expanduser() if args.out else ws / "report.docx"
    texts = Path(args.texts).expanduser() if args.texts else ws / "texts"
    audit = Path(args.audit).expanduser() if args.audit else ws / "audit-olcutler.json"
    opts = Options(puan_isareti=args.puan_isareti, kanit_bicimi=args.kanit_bicimi,
                   eksik_notu=not args.eksik_notu_yok)
    if args.bos_ifade:
        opts.bos_ifade = args.bos_ifade
    if args.bos_kanit:
        opts.bos_kanit = args.bos_kanit
    try:
        res = render(Path(args.sablon), out, texts_dir=texts, audit_path=audit,
                     birim=birim, yil=args.yil, opts=opts)
    except (FileNotFoundError, ValueError) as e:
        print(f"HATA {e}", file=sys.stderr)
        return 2
    for u in res.uyarilar:
        print(f"uyarı: {u}")
    print(json.dumps(res.ozet(), ensure_ascii=False, indent=1))
    if res.taslak:
        print("Belge TASLAK damgalı: doğrulanmamış metin var → "
              + ", ".join(res.dogrulanmamis + res.reddedildi))
    print(f"report: {res.out}")
    return 0


def register(sub):
    p = sub.add_parser("render", help="FR-0833 şablonunun Açıklamalar/Kanıtlar hücrelerini "
                                      "texts/<ölçüt>.json'dan doldurur (report.docx; model yok)")
    p.add_argument("--workspace", "-w", required=True)
    p.add_argument("--sablon", required=True, help="boş FR-0833 şablonu (.docx; salt okunur)")
    p.add_argument("--out", default=None, help="çıktı (vars.: WS/report.docx)")
    p.add_argument("--birim", default=None, help="kapaktaki birim adı (vars.: config.yaml birim)")
    p.add_argument("--yil", default=None, help="kapaktaki yıl (verilmezse şablondaki kalır)")
    p.add_argument("--texts", default=None, help="metin klasörü (vars.: WS/texts)")
    p.add_argument("--audit", default=None, help="audit-olcutler.json (vars.: WS/audit-olcutler.json)")
    p.add_argument("--puan-isareti", choices=["kalin", "golge", "yok"], default="kalin",
                   help="öz değerlendirme düzeyinin rubrikte işaretlenmesi (vars.: kalin, "
                        "Kimya 2025 raporu usulü; Matematik/Fizik/MBG işaretlememiş: yok)")
    p.add_argument("--kanit-bicimi", choices=["mat", "kilavuz"], default="mat",
                   help="Kanıtlar listesi: mat '1_OD3: ad' (vars.) | kilavuz '[1-OD3]. ad'")
    p.add_argument("--bos-ifade", default=None, help="metni olmayan ölçüt için Açıklamalar ifadesi")
    p.add_argument("--bos-kanit", default=None, help="metni olmayan ölçüt için Kanıtlar ifadesi")
    p.add_argument("--eksik-notu-yok", action="store_true",
                   help="metni olmayan ölçüte audit'in eksik kanıt notunu yazma")
    p.set_defaults(func=_run)
