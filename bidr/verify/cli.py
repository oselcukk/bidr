"""`bidr verify prepare|apply`."""
from __future__ import annotations


def _cmd(args) -> int:
    from bidr.pipeline.gate import check_gate
    if (rc := check_gate(args.workspace, "verify")) is not None:
        return rc
    from bidr.write.cli import olcut_list

    from . import run as R

    try:
        if args.action == "karar":
            r = R.decide(args.workspace, args.olcut, args.karar, args.note or "")
            print(f"{r['olcut']}: {r['karar']} kaydedildi (tur {r['tur']}, sınır {r['sinir']})")
            if r["karar"] == "tekrar":
                print("Sıradaki: bidr write prepare -w <ws> --reddedilenler")
            elif r["karar"] == "kabul":
                print(f"{r['olcut']}: metin insan onayıyla rapora girer (doğrulayıcı reddi kayıtta kalır)")
            return 0
        if args.action == "prepare":
            st = R.prepare(args.workspace, only=olcut_list(args.only), redo=args.redo, index=args.index,
                           audit=args.audit, onceki=args.onceki, notes=args.notlar)
            print(f"{st['metin']} metin: {st['paket']} paket ({st['yeni']} yeni/değişen), "
                  f"zaten_tamam={st['zaten_tamam']}, kod denetiminde reddedilen={len(st['kod_reddi'])}, "
                  f"bekleyen {st['bekleyen']} → {st['klasor']}")
            if st.get("yeni_kural"):
                print(f"  doğrulanmış ama sonradan eklenen içerik kuralına takılan metin (tur sayacı sıfırlandı, "
                      f"yeniden yazıma gider): {', '.join(st['yeni_kural'])}")
            for c, why in st["kod_reddi"].items():
                print(f"  reddedildi {c} (kod):")
                for w in why:
                    print(f"    - {w}")
            y = st.get("yonler") or {}
            if y.get("metin") or y.get("eski_metin"):
                print(f"güçlü/gelişmeye açık yönler: {y['metin']} alan, {y['paket']} paket ({y['yeni']} yeni/değişen), "
                      f"zaten_tamam={y['zaten_tamam']}, kod denetiminde reddedilen={len(y['kod_reddi'])}"
                      + (f", bekleyen {y['bekleyen']} → {y['klasor']}/README.md" if y.get("klasor") else ""))
                for a, why in y["kod_reddi"].items():
                    print(f"  reddedildi {a} (kod):")
                    for w in why:
                        print(f"    - {w}")
                if y["eski_metin"]:
                    print(f"  girdisi değişen alan (önce bidr yonler prepare): {', '.join(y['eski_metin'])}")
            print(f"Ajan (metni yazandan bağımsız olmalı): {st['klasor']}/README.md")
            return 1 if st["kod_reddi"] or y.get("kod_reddi") else 0
        st = R.apply(args.workspace, model=args.model)
    except (FileNotFoundError, KeyError, ValueError) as e:
        print(f"HATA {e}")
        return 2
    print(f"dogrulandi={len(st['dogrulandi'])} reddedildi={len(st['reddedildi'])} değişmedi={st['degismedi']} "
          f"bekleyen={len(st['bekleyen'])} geçersiz={len(st['gecersiz'])} eski paket={len(st['eski'])}")
    for c, why in st["reddedildi"].items():
        print(f"  reddedildi {c}:")
        for w in why:
            print(f"    - {w}")
    for c, errs in st["gecersiz"].items():
        print(f"  geçersiz cevap {c}: {'; '.join(errs)}")
    if st["eski"]:
        print(f"  eski paket (metin değişti; yeniden prepare): {', '.join(st['eski'])}")
    y = st.get("yonler") or {}
    if any(y.get(k) for k in ("dogrulandi", "reddedildi", "bekleyen", "gecersiz", "eski")):
        print(f"güçlü/gelişmeye açık yönler: dogrulandi={len(y['dogrulandi'])} reddedildi={len(y['reddedildi'])} "
              f"bekleyen={len(y['bekleyen'])} geçersiz={len(y['gecersiz'])} eski paket={len(y['eski'])}")
        for a, why in y["reddedildi"].items():
            print(f"  reddedildi {a}:")
            for w in why:
                print(f"    - {w}")
        for a, errs in y["gecersiz"].items():
            print(f"  geçersiz cevap {a}: {'; '.join(errs)}")
    bad = st["gecersiz"] or st["reddedildi"] or y.get("gecersiz") or y.get("reddedildi")
    return 1 if bad else 0


def register(sub):
    p = sub.add_parser("verify", help="metin doğrulama: kod + bağımsız ajan → verify.jsonl")
    act = p.add_subparsers(dest="action", required=True)
    a = act.add_parser("prepare", help="kod denetimi + iş paketleri work/verify/<ölçüt>.json")
    a.add_argument("--workspace", "-w", required=True)
    a.add_argument("--only", metavar="OLCUT[,…]", help="yalnız bu ölçütler (doğrulanmış olsalar da)")
    a.add_argument("--redo", action="store_true", help="doğrulanmış metinleri de yeniden paketle")
    a.add_argument("--index", help="evidence-index.csv (vars. son write prepare'in kullandığı)")
    a.add_argument("--audit", help="audit-olcutler.json (vars. son write prepare'in kullandığı)")
    a.add_argument("--onceki", help="geçen yılın raporu/klasörü (vars. son write prepare'in kullandığı)")
    a.add_argument("--notlar", help="komisyon bilgisi YAML'ı (vars. son write prepare'in kullandığı)")
    a.set_defaults(func=_cmd)
    a = act.add_parser("karar", help="KULLANICININ kararı, reddedilen metin için: cikar (rapora girmez) | "
                                     "tekrar (bir yeniden yazım turu daha) | kabul (doğrulayıcının "
                                     "itirazı yerinde değil: metin olduğu gibi rapora girer) → verify-insan.jsonl")
    a.add_argument("--workspace", "-w", required=True)
    a.add_argument("olcut")
    a.add_argument("karar", choices=["cikar", "tekrar", "kabul"])
    a.add_argument("--not", dest="note", default="", help="kullanıcının gerekçesi (kayda geçer)")
    a.set_defaults(func=_cmd)
    a = act.add_parser("apply", help="<ölçüt>.out.json kararlarını işle: dogrulandi / reddedildi")
    a.add_argument("--workspace", "-w", required=True)
    a.add_argument("--model", default="ajan:belirtilmemis", help="doğrulayan ajan/model (kayda geçer)")
    a.set_defaults(func=_cmd)
