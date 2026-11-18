"""`bidr write prepare|apply`."""
from __future__ import annotations

import re


def olcut_list(s: str | None) -> list[str] | None:
    return [x.strip().rstrip(".") for x in re.split(r"[,\s]+", s) if x.strip()] if s else None


def _cmd(args) -> int:
    from bidr.pipeline.gate import check_gate
    if (rc := check_gate(args.workspace, "write")) is not None:
        return rc
    from . import run as R

    try:
        if args.action == "prepare" and args.reddedilenler:
            if args.redo:
                print("HATA --reddedilenler ile --redo birlikte kullanılmaz")
                return 2
            st = R.prepare_rejected(args.workspace, only=olcut_list(args.only), index=args.index,
                                    audit=args.audit, onceki=args.onceki, notes=args.notlar, hitap=args.hitap)
            print(f"yeniden yazım: {st['paket']} paket ({st['yeni']} yeni/değişen), bekleyen {st['bekleyen']} "
                  f"→ {st['klasor']}")
            for c, n in st["tur"].items():
                print(f"  {c}: tur {n}")
            if st["insan_gerekli"]:
                print("yeniden yazım sınırına ulaşan (insan gerekli; `bidr verify karar`): "
                      + ", ".join(st["insan_gerekli"]))
            if st["cikarildi"]:
                print("insan kararıyla rapordan çıkarılan: " + ", ".join(st["cikarildi"]))
            print(f"Ajan (metni ilk yazandan ve doğrulayıcıdan ayrı, taze bir ajan): {st['klasor']}/README.md")
            return 0
        if args.action == "prepare":
            st = R.prepare(args.workspace, only=olcut_list(args.only), redo=args.redo, index=args.index,
                           audit=args.audit, onceki=args.onceki, notes=args.notlar, hitap=args.hitap)
            print(f"{st['paket']} paket ({st['yeni']} yeni/değişen), zaten_tamam={st['zaten_tamam']}, "
                  f"bekleyen {st['bekleyen']} → {st['klasor']}")
            print(f"önceki yıl metni: {st['onceki'] or 'yok'}"
                  + (f" ({st['onceki_olcut']} ölçütte bulundu)" if st["onceki"] else ""))
            if st["kanitsiz"]:
                print(f"kanıtsız ölçüt (paket yok; metin yazılmaz): {', '.join(st['kanitsiz'])}")
            print(f"Ajan: {st['klasor']}/README.md")
            return 0
        st = R.apply(args.workspace, model=args.model, index=args.index, audit=args.audit)
    except (FileNotFoundError, KeyError) as e:
        print(f"HATA {e}")
        return 2
    print(f"işlenen={st['islenen']} değişmedi={st['degismedi']} bekleyen={len(st['bekleyen'])} "
          f"geçersiz={len(st['gecersiz'])} eski paket={len(st['eski'])}")
    for c, errs in st["gecersiz"].items():
        print(f"  geçersiz {c}:")
        for e in errs:
            print(f"    - {e}")
    if st["eski"]:
        print(f"  eski paket (kanıt listesi/OD/görev sürümü değişti; yeniden prepare): {', '.join(st['eski'])}")
    return 1 if st["gecersiz"] else 0


def _src_args(p) -> None:
    p.add_argument("--workspace", "-w", required=True)
    p.add_argument("--index", help="evidence-index.csv yolu (vars. <ws>/evidence-index.csv)")
    p.add_argument("--audit", help="audit-olcutler.json yolu (vars. <ws>/audit-olcutler.json)")


def register(sub):
    p = sub.add_parser("write", help="ölçüt açıklama metinleri (ajan modu) → texts/<ölçüt>.json")
    act = p.add_subparsers(dest="action", required=True)
    a = act.add_parser("prepare", help="iş paketleri work/write/<ölçüt>.json")
    _src_args(a)
    a.add_argument("--only", metavar="OLCUT[,…]", help="yalnız bu ölçütler (yazılmış olsalar da)")
    a.add_argument("--redo", action="store_true", help="yazılmış metinleri de yeniden paketle")
    a.add_argument("--reddedilenler", action="store_true",
                   help="yeniden yazım turu: verify'ın reddettiği metinler için doğrulayıcının cümle bazlı "
                        "gerekçesiyle yeni paket (tur sınırı: config.yaml rapor.yeniden_yazim_siniri, vars. 2)")
    a.add_argument("--onceki", help="geçen yılın raporu (FR-0833 docx) ya da <ölçüt>.txt klasörü "
                                    "(vars. config.yaml rapor.onceki_rapor)")
    a.add_argument("--notlar", help="komisyon bilgisi YAML'ı {ölçüt: [bilgi, …]} (vars. <ws>/rapor-notlari.yaml)")
    a.add_argument("--hitap", help="kurumsal özne (vars. profile göre 'Bölümümüzde' / 'Birimimizde')")
    a.set_defaults(func=_cmd)
    a = act.add_parser("apply", help="<ölçüt>.out.json cevaplarını denetle ve texts/'e yaz")
    _src_args(a)
    a.add_argument("--model", default="ajan:belirtilmemis", help="metni yazan ajan/model (kayda geçer)")
    a.set_defaults(func=_cmd)
