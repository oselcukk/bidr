"""`bidr ihtiyac referans -w ÖNCEKİ_WS [--ek iyi-kanitlar.csv] --out referans.json` ve
`bidr ihtiyac -w WS [--referans referans.json] [--out DIR] [--ic-taslak]`. Model yok; hat aşaması
değildir (önkoşul kapısı yok, çalışma alanı salt okunur)."""
from __future__ import annotations

import sys
from pathlib import Path


def _referans(args) -> int:
    from .referans import build_reference, write_reference
    from .tablolar import Turler
    if not args.workspace and not args.ek:
        print("HATA: -w (önceki çalışma alanı) ya da --ek (CSV) gerekli", file=sys.stderr)
        return 2
    if not args.out:
        print("HATA: --out referans.json gerekli", file=sys.stderr)
        return 2
    ws = Path(args.workspace).expanduser().resolve() if args.workspace else None
    try:
        ref = build_reference(ws, ek=Path(args.ek).expanduser() if args.ek else None,
                              turler=Turler(args.turler) if args.turler else None)
    except (FileNotFoundError, ValueError) as e:
        print(f"HATA: {e}", file=sys.stderr)
        return 1
    p = write_reference(ref, Path(args.out))
    from collections import Counter
    its = ref["ogeler"]
    print(f"referans: {len(its)} iyi kanıt ({len(ref['belgeler'])} belge; "
          f"{sum(1 for x in its if x['kaynak'] == 'elle')} elle) · tekrarlayan: "
          f"{sum(1 for x in its if x['tekrarlayan'])}")
    for k, v in Counter(x["olcut"] for x in its).most_common(5):
        print(f"  {k}: {v}")
    for u in ref["uyarilar"]:
        print(f"uyarı: {u}")
    print(f"yazıldı: {p}")
    return 0


def _rapor(args) -> int:
    from . import rapor
    from .referans import load_reference
    from .tablolar import Sorumlular, Turler
    ws = Path(args.workspace).expanduser().resolve()
    out = Path(args.out).expanduser().resolve() if args.out else ws
    from . import sade
    try:
        ref = load_reference(Path(args.referans)) if args.referans else None
        ist = sade.istekler_oku(args.istenecekler) if args.istenecekler else None
        from .katalog_esle import FILE as KFILE
        from .katalog_esle import esleme_oku
        if args.kurum_katalog:
            kp = Path(args.kurum_katalog).expanduser()
            if not (kp / KFILE if kp.is_dir() else kp).exists():
                raise FileNotFoundError(f"kurum katalog eşlemesi yok: {kp}")
        else:
            kp = next((d / KFILE for d in (out, ws) if (d / KFILE).exists()), None)
        kurum = esleme_oku(kp) if kp else None
        if kurum:
            print(f"kurum belgeleri: {sum(1 for o in kurum['ogeler'] if o.get('ilgili'))} ilgili / "
                  f"{len(kurum['ogeler'])} ({kp})")
        res = rapor.run(ws, referans=ref, out=out,
                        sorumlular=Sorumlular(args.sorumlular) if args.sorumlular else None,
                        turler=Turler(args.turler) if args.turler else None, istekler=ist,
                        somut=sade.Somut(args.somut) if args.somut else None,
                        oneriler=sade.oneriler_yukle(args.oneriler) if args.oneriler else None,
                        kurum=kurum)
    except (FileNotFoundError, ValueError) as e:
        print(f"HATA: {e}", file=sys.stderr)
        return 1
    for t in res["talepler"][:10]:
        print(f"  {t['sira']}. {t['olcut']} [{t['puan']}] {t['istenecek'][:90]} — {t['kimden']}")
    from collections import Counter
    n = Counter(r["oncelik"] for r in res["sade"])
    print(f"istenen kanıtlar: {len(res['sade'])} madde (" + ", ".join(f"{k} {n.get(k, 0)}" for k in
                                                                    (sade.YUKSEK, sade.ORTA, sade.DUSUK))
          + (f"; elle istek {len(ist)}" if ist else "") + ")")
    for k, p in res["paths"].items():
        print(f"{k}: {p}")
    if args.ic_taslak:
        from .taslak import write_draft
        try:
            dst, n, uy = write_draft(ws / "report.docx", out, res["satirlar"], res["talepler"])
        except (FileNotFoundError, ValueError) as e:
            print(f"HATA: {e}", file=sys.stderr)
            return 1
        for u in uy[:10]:
            print(f"uyarı: {u}")
        print(f"iç taslak: {dst} ({n} ölçüte [EKSİK] işareti; asıl report.docx değişmedi)")
    return 0


def _run(args) -> int:
    if args.eylem == "referans":
        return _referans(args)
    if not args.workspace:
        print("HATA: -w gerekli", file=sys.stderr)
        return 2
    return _rapor(args)


def register(sub):
    p = sub.add_parser("ihtiyac", help="kanıt ihtiyaç raporu: eksikler, öncelikli talepler, geçen yılın iyi "
                                       "kanıtlarının bu yılki karşılığı (ihtiyac.xlsx, ihtiyac.md, sade istenen-kanitlar.xlsx; model yok)")
    p.add_argument("eylem", nargs="?", choices=["referans"],
                   help="referans: önceki çalışma alanından iyi kanıt seti (JSON) üret")
    p.add_argument("--workspace", "-w", default=None,
                   help="çalışma alanı (referans eyleminde: önceki yılın bitmiş çalışma alanı)")
    p.add_argument("--referans", default=None, help="referans.json (bidr ihtiyac referans çıktısı)")
    p.add_argument("--ek", default=None, help="referans: elle iyi kanıtlar CSV (olcut,belge_turu,ad[,yuva,asama,anahtar])")
    p.add_argument("--out", default=None,
                   help="referans: çıktı JSON yolu; rapor: çıktı klasörü (varsayılan çalışma alanı)")
    p.add_argument("--ic-taslak", action="store_true",
                   help="report.docx'in kopyasına (report-ic.docx) [EKSİK: …] işaretleri koy")
    p.add_argument("--istenecekler", default=None,
                   help="elle istekler (.md: '- B.3.2 — metin' satırları; .csv: madde,istek[,oncelik,kimden]); "
                        "istenen-kanitlar.xlsx'e birleşir")
    p.add_argument("--somut", default=None,
                   help="kılavuz maddesi → somut belge tablosu (vars.: bidr/data/ihtiyac_somut.yaml)")
    p.add_argument("--oneriler", default=None,
                   help="istenebilecek kanıt önerileri (vars.: bidr/data/ihtiyac_oneriler.yaml)")
    p.add_argument("--kurum-katalog", default=None,
                   help="kurum belge kataloğu eşlemesi (kurum-katalog-esleme.json ya da klasörü; vars. --out, "
                        "sonra çalışma alanında aranır; `bidr kurum-katalog`)")
    p.add_argument("--turler", default=None, help="tekrarlayan tür tablosu (vars.: bidr/data/ihtiyac_turler.yaml)")
    p.add_argument("--sorumlular", default=None,
                   help="kimden istenir tablosu (vars.: bidr/data/ihtiyac_sorumlular.yaml)")
    p.set_defaults(func=_run)
