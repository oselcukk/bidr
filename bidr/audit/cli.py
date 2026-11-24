"""`bidr audit -w WS [--profile P] [--out DIR]`, `bidr audit apply -w WS [--out DIR]` ve
`bidr audit elle esitle|ekle|geri|liste -w WS` (bölümün elle eklediği eşleşmeler; bidr/audit/elle.py)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _run(args) -> int:
    from bidr.pipeline.gate import check_gate

    from . import run
    from .report import gap_line, top_gaps
    if not getattr(args, "workspace", None):
        print("HATA --workspace/-w gerekli", file=sys.stderr)
        return 2
    ws = Path(args.workspace).expanduser().resolve()
    if args.eylem == "elle":
        return _elle(args, ws)
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


def _elle(args, ws: Path) -> int:
    """Bölümün elle eklediği belge–ölçüt eşleşmeleri. İnsan kararıdır: ajan kullanıcının sözü olmadan eklemez."""
    from . import elle as E
    a = list(args.arg or [])
    try:
        if args.islem == "liste":
            g = E.oku(ws)
            if args.json:
                print(json.dumps(g, ensure_ascii=False, indent=1))
            else:
                for e in g:
                    print(f"{e['anahtar']}: {e['dosya'] or e['sha256'][:12]} → {e['olcut']}"
                          + (f" ({e['yuva']})" if e["yuva"] else "") + (f" [{e['asama']}]" if e["asama"] else ""))
                print(f"{len(g)} elle eşleşme ({E.DOSYA})")
            return 0
        if args.islem == "ekle":
            if len(a) != 2:
                print("HATA kullanım: bidr audit elle ekle -w WS <belge yolu|doc_id> <ölçüt> [--yuva Y] "
                      "[--asama A] [--not N]", file=sys.stderr)
                return 2
            k = E.ekle(ws, a[0], a[1], yuva=args.yuva, asama=args.asama, notu=args.not_ or "")
            print(f"eklendi: {k}")
        elif args.islem == "geri":
            if len(a) != 1:
                print("HATA kullanım: bidr audit elle geri -w WS <anahtar>", file=sys.stderr)
                return 2
            if not E.geri(ws, a[0]):
                print(f"HATA {a[0]}: böyle bir elle eşleşme yok", file=sys.stderr)
                return 2
            print(f"geri alındı: {a[0]}")
        st = E.esitle(ws, out=args.out)
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        print(f"HATA {e}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({k: st[k] for k in ("eklenen", "guncellenen", "kaldirilan", "zaten_kabul", "bulunamayan")},
                         ensure_ascii=False))
    else:
        print(f"elle eşleşme: {len(st['eklenen'])} eklendi, {len(st['guncellenen'])} güncellendi, "
              f"{len(st['kaldirilan'])} kaldırıldı, {len(st['zaten_kabul'])} zaten kabul edilmişti")
        for b in st["bulunamayan"]:
            print(f"uyarı: {b['anahtar']}: {b['neden']}")
        if st["degisti"]:
            print(f"Sonra: bidr audit -w {ws} (inceleme tablosu ve OD yenilenir)")
    return 0


def _ortak(p, alt: bool) -> None:
    # alt komutta varsayılan verilmez (SUPPRESS): üst komuttaki değer ezilmesin
    kw = {"default": argparse.SUPPRESS} if alt else {"default": None}
    p.add_argument("--workspace", "-w", **kw)
    p.add_argument("--profile", help="varsayılan: config.yaml profili, yoksa akademik_bolum", **kw)
    p.add_argument("--out", help="çıktı klasörü (varsayılan çalışma alanı); paylaşılan WS'yi salt okumak için", **kw)


def register(sub):
    p = sub.add_parser("audit", help="ölçüt düzeyinde OD, eksik kanıt raporu (gaps.md) ve inceleme "
                                     "tablosu (review.xlsx); `apply`: doldurulmuş tabloyu işler; `elle`: bölümün "
                                     "elle eklediği eşleşmeler")
    _ortak(p, False)
    act = p.add_subparsers(dest="eylem")
    a = act.add_parser("apply", help="review.xlsx kararlarını işle")
    _ortak(a, True)
    e = act.add_parser("elle", help="KULLANICININ elle eklediği belge–ölçüt eşleşmeleri (elle-eslesmeler.json): "
                                    "esitle (dosyayı kararlara işle) | ekle <belge> <ölçüt> | geri <anahtar> | liste")
    _ortak(e, True)
    e.add_argument("islem", choices=["esitle", "ekle", "geri", "liste"])
    e.add_argument("arg", nargs="*", help="ekle: <belge yolu|doc_id> <ölçüt>; geri: <anahtar>")
    e.add_argument("--yuva", default=None)
    e.add_argument("--asama", default=None, choices=["planla", "uygula", "kontrol_et", "onlem_al", "ozgun"])
    e.add_argument("--not", dest="not_", default=None)
    e.add_argument("--json", action="store_true")
    p.set_defaults(func=_run)
