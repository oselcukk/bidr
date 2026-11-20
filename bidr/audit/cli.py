"""`bidr audit -w WS [--profile P] [--out DIR]` ve `bidr audit apply -w WS [--out DIR]`."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _run(args) -> int:
    from bidr.pipeline.gate import check_gate

    from . import run
    from .report import gap_line, top_gaps
    ws = Path(args.workspace).expanduser().resolve()
    rc = check_gate(ws, "audit")
    if rc is not None:
        return rc
    try:
        if args.eylem == "apply":
            st = run.apply(ws, out=args.out, profile=args.profile)
            print(json.dumps({k: v for k, v in st.items()}, ensure_ascii=False, indent=1))
            if st["gecersiz"]:
                print(f"HATA {len(st['gecersiz'])} satırın kararı geçersiz (yukarıda); düzeltip yeniden "
                      "apply çalıştırın", file=sys.stderr)
                return 1
            if st["kanit_adi_gecersiz"]:
                print(f"HATA {len(st['kanit_adi_gecersiz'])} belgenin kanıt adı düzeltmesi geçersiz "
                      "(yukarıda); öteki kararlar işlendi", file=sys.stderr)
                return 1
            if st["baglanti_gecersiz"]:
                print(f"HATA {len(st['baglanti_gecersiz'])} belgenin bağlantı düzeltmesi geçersiz "
                      "(yukarıda); öteki kararlar işlendi", file=sys.stderr)
                return 1
            if st["birim_gecersiz"]:
                for k, v in st["birim_gecersiz"].items():
                    print(f"  {k}: {v}", file=sys.stderr)
                print(f"HATA {len(st['birim_gecersiz'])} belgenin birim ilişkisi kararı geçersiz; öteki "
                      "kararlar işlendi", file=sys.stderr)
                return 1
            b = st.get("birim") or {}
            if b.get("geri_alinan") or b.get("kaldirilan") or b.get("baska_birim_onay"):
                print("Birim kararları değişti: tabloyu yenileyin (geri alınan eşleşmeler 'İnceleme' "
                      "sayfasında karar bekler): bidr audit -w " + str(ws) + (f" --out {args.out}" if args.out else ""))
            if b.get("yeniden_karar"):
                print(f"{len(b['yeniden_karar'])} belge yeniden ince karar bekliyor (eşleşme kaydı yok; birim "
                      f"ilişkisi pakete sabit yazılır): bidr decide prepare -w {ws} --stage fine --only "
                      + ",".join(b["yeniden_karar"]))
            if st["bos"]:
                print(f"{st['bos']} satır karar bekliyor.")
            if st.get("yeniden_bak"):
                print(f"{st['yeniden_bak']} kararlı satır yeniden bakılmalı ('İnceleme' 1. bölüm; eski karar "
                      "geçerli): KARARINIZ'ı yeniden seçin (aynı kalacaksa aynısını), sonra yeniden apply.")
            return 0
        a, paths = run.audit(ws, out=args.out, profile=args.profile)
    except (FileNotFoundError, RuntimeError, ValueError) as e:
        print(f"HATA {e}", file=sys.stderr)
        return 2
    for u in a.uyarilar:
        print(f"uyarı: {u}")
    dist = run.od_distribution(a)
    print(f"{len(a.rows)} eşleşme, {len(a.criteria)} ölçüt; önerilen OD dağılımı: "
          + ", ".join(f"OD{k}={v}" for k, v in dist.items()))
    print("Öncelikli eksikler:")
    for i, c in enumerate(top_gaps(a, 10), 1):
        print(f"  {i}. {gap_line(c)}")
    for k, p in paths.items():
        print(f"{k}: {p}")
    print("Sonra: review.xlsx 'İnceleme' sayfasında KARARINIZ (2. bölüm için 'Hepsini kabul' seçilebilir; "
          "ya da kullanıcıya satır satır sorulur) → bidr audit apply -w " + str(ws)
          + (f" --out {args.out}" if args.out else ""))
    return 0


def register(sub):
    p = sub.add_parser("audit", help="ölçüt düzeyinde OD, eksik kanıt raporu (gaps.md) ve inceleme "
                                     "tablosu (review.xlsx); `apply`: doldurulmuş tabloyu işler")
    p.add_argument("eylem", nargs="?", choices=["apply"], help="apply: review.xlsx kararlarını işle")
    p.add_argument("--workspace", "-w", required=True)
    p.add_argument("--profile", default=None, help="varsayılan: config.yaml profili, yoksa akademik_bolum")
    p.add_argument("--out", default=None,
                   help="çıktı klasörü (varsayılan çalışma alanı); paylaşılan WS'yi salt okumak için")
    p.set_defaults(func=_run)
