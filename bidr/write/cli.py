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
        if args.action == "karar":
            from . import karar as KR
            r = KR.karar(args.workspace, args.olcut, args.karar, args.note or "")
            print(f"{r['olcut']}: {r['karar']} kaydedildi (deneme {r['deneme']}, sınır {r['sinir']}) → {KR.HUMAN}")
            if r["karar"] == "tekrar":
                print("Sıradaki: work/write/GECERSIZ.md'deki gerekçeyle bir yeniden yazım turu daha (taze ajan), "
                      f"sonra bidr write apply -w {args.workspace}")
            elif r["karar"] == "kabul":
                print(f"{r['olcut']}: metin üslup bulgularıyla insan onayıyla yazıldı (durum taslak); "
                      "bağımsız doğrulama (bidr verify) yine yapılır")
            else:
                print(f"{r['olcut']}: metin rapora girmez (kullanıcı kararı)")
            return 0
        if args.action == "prepare" and args.reddedilenler:
            if args.redo or args.eski_kurallar:
                print("HATA --reddedilenler ile --redo/--eski-kurallar birlikte kullanılmaz")
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
                           audit=args.audit, onceki=args.onceki, notes=args.notlar, hitap=args.hitap,
                           old_rules=args.eski_kurallar)
            if args.eski_kurallar:
                print(f"eski yazım kuralıyla yazılmış geçerli metin: {len(st['yenilenen'])}"
                      + (f" ({', '.join(st['yenilenen'])})" if st["yenilenen"] else " — yenilenecek metin yok"))
            print(f"{st['paket']} paket ({st['yeni']} yeni/değişen), zaten_tamam={st['zaten_tamam']}, "
                  f"bekleyen {st['bekleyen']} → {st['klasor']}")
            print(f"önceki yıl metni: {st['onceki'] or 'yok'}"
                  + (f" ({st['onceki_olcut']} ölçütte bulundu)" if st["onceki"] else ""))
            if st["kanitsiz"]:
                print(f"kanıtsız ölçüt (paket yok; metin yazılmaz): {', '.join(st['kanitsiz'])}")
            if st["eski_surum"]:
                print(f"eski yazım kuralıyla yazılmış, girdileri güncel (geçerli; yeniden paketlenmedi): "
                      f"{', '.join(st['eski_surum'])} — isteğe bağlı yenileme (yalnız bunlar): "
                      f"bidr write prepare -w {args.workspace} --eski-kurallar")
            print(f"Ajan: {st['klasor']}/README.md")
            return 0
        from bidr.pipeline.paralel import apply_oncesi
        apply_oncesi(args.workspace, "work/write")   # parça dışı yazılmış/ezilmiş cevap reddedilir
        st = R.apply(args.workspace, model=args.model, index=args.index, audit=args.audit)
    except (FileNotFoundError, KeyError, ValueError) as e:
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
    if st.get("insan_gerekli"):
        print("yeniden yazım sınırından sonra kod denetimini hâlâ geçemeyen (KULLANICI kararı gerekli; "
              "`bidr write karar -w WS <ölçüt> cikar|tekrar|kabul`, kabul yalnız üslup bulgularında): "
              + ", ".join(st["insan_gerekli"]))
    print(f"Sıradaki: bidr next -w {args.workspace}")
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
    a.add_argument("--eski-kurallar", action="store_true",
                   help="isteğe bağlı yenileme: yalnız yazım görevinin eski sürümüyle yazılmış, girdisi değişmemiş "
                        "geçerli metinleri yeni yazım kuralıyla yeniden paketle (sonra yeniden doğrulanır)")
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
    a = act.add_parser("karar", help="KULLANICININ kararı, yeniden yazımlardan sonra kod denetimini geçemeyen "
                                     "metin için: cikar (rapora girmez) | tekrar (bir yeniden yazım turu daha) | "
                                     "kabul (yalnız üslup bulguları: abartı/slogan/ODn dili; metin "
                                     "doğrulamaya gider) → write-insan.jsonl")
    a.add_argument("--workspace", "-w", required=True)
    a.add_argument("olcut")
    a.add_argument("karar", choices=["cikar", "tekrar", "kabul"])
    a.add_argument("--not", dest="note", default="", help="kullanıcının gerekçesi (kayda geçer)")
    a.set_defaults(func=_cmd)
    register_yonler(sub)        # aynı katman (iş paketi + kod denetimi); ayrı modül listesi gerekmez


# -- bidr yonler: alan düzeyinde Güçlü / Gelişmeye Açık Yönler (bkz. bidr/write/yonler.py) ------------

def _yonler_cmd(args) -> int:
    from bidr.pipeline.gate import check_gate
    if (rc := check_gate(args.workspace, "yonler")) is not None:
        return rc
    from . import yonler as Y
    only = [x.strip().upper() for x in re.split(r"[,\s]+", args.only) if x.strip()] if getattr(args, "only", None) else None
    try:
        if args.action == "karar":
            from . import yon_karar as YK
            r = YK.karar(args.workspace, args.alan, args.karar, args.note or "")
            print(f"{r['alan']}: {r['karar']} kaydedildi (tur {r['tur']}, sınır {r['sinir']}) → {YK.HUMAN}")
            if r["karar"] == "tekrar":
                print(f"Sıradaki: bidr yonler prepare -w {args.workspace} --reddedilenler (taze ajan)")
            elif r["karar"] == "kabul":
                print(f"{r['alan']}: maddeler yazıldığı gibi rapora girer (bölüm onayı; doğrulayıcı reddi kayıtta kalır)")
            else:
                print(f"{r['alan']}: desteklenmeyen maddeler çıkarılmış kalır (bölüm onayı; rapor bu yüzden TASLAK olmaz)")
            return 0
        if args.action == "prepare":
            st = Y.prepare(args.workspace, only=only, redo=args.redo, rejected_only=args.reddedilenler,
                           hitap=args.hitap, index=args.index, audit=args.audit)
            for u in st["uyarilar"]:
                print(f"uyarı: {u}")
            print(f"{st['paket']} paket ({st['yeni']} yeni/değişen), zaten_tamam={st['zaten_tamam']}, "
                  f"bekleyen {st['bekleyen']} → {st['klasor']}")
            for a, n in st["tur"].items():
                print(f"  {a}: yeniden yazım turu {n}")
            if st["insan_gerekli"]:
                print("yeniden yazım sınırına ulaşan alan (hücreler şablon yönergesiyle kalır, rapor TASLAK; "
                      "kullanıcıya göster): " + ", ".join(st["insan_gerekli"]))
            if st["bos_alan"]:
                print(f"birimin doldurduğu ölçütü olmayan alan (paket yok): {', '.join(st['bos_alan'])}")
            who = ("metni ilk yazandan ve doğrulayıcıdan AYRI, taze bir ajan" if st["tur"]
                   else "ajan (doğrulamayı sonra başka, taze bir ajan yapar)")
            print(f"Ajan ({who}): {st['klasor']}/README.md")
            return 0
        st = Y.apply(args.workspace, model=args.model, index=args.index, audit=args.audit)
    except (FileNotFoundError, KeyError, ValueError) as e:
        print(f"HATA {e}")
        return 2
    print(f"işlenen={st['islenen']} değişmedi={st['degismedi']} bekleyen={len(st['bekleyen'])} "
          f"geçersiz={len(st['gecersiz'])} eski paket={len(st['eski'])}")
    for a, errs in st["gecersiz"].items():
        print(f"  geçersiz {a}:")
        for e in errs:
            print(f"    - {e}")
    if st["eski"]:
        print(f"  eski paket (ölçüt metinleri/audit değişti; yeniden prepare): {', '.join(st['eski'])}")
    if st["islenen"]:
        print("Sıradaki: bidr verify prepare (bağımsız doğrulama; alan maddeleri de)")
    return 1 if st["gecersiz"] else 0


def register_yonler(sub):
    p = sub.add_parser("yonler", help="alan düzeyinde Güçlü / Gelişmeye Açık Yönler (ajan modu) → yonler/<alan>.json")
    act = p.add_subparsers(dest="action", required=True)
    a = act.add_parser("prepare", help="iş paketleri work/yonler/<alan>.json (A, B, C, D)")
    _src_args(a)
    a.add_argument("--only", metavar="ALAN[,…]", help="yalnız bu alanlar (ör. A,C)")
    a.add_argument("--redo", action="store_true", help="yazılmış alanları da yeniden paketle")
    a.add_argument("--reddedilenler", action="store_true",
                   help="yeniden yazım turu: doğrulamada reddedilen alanlar için gerekçeli yeni paket "
                        "(sınır: config.yaml rapor.yeniden_yazim_siniri, vars. 2)")
    a.add_argument("--hitap", help="kurumsal özne (vars. profile göre 'Bölümümüzde' / 'Birimimizde')")
    a.set_defaults(func=_yonler_cmd)
    a = act.add_parser("karar", help="KULLANICININ kararı, yeniden yazımlardan sonra doğrulamada hâlâ reddedilen "
                                     "yön hücresi için: tekrar (bir tur daha) | kabul (yalnız bütün reddedilen maddeler "
                                     "'kısmen' ise; yazıldığı gibi) | cikar (desteklenmeyen maddeler çıkarılmış kalır) "
                                     "→ yonler-insan.jsonl")
    a.add_argument("--workspace", "-w", required=True)
    a.add_argument("alan", choices=["A", "B", "C", "D", "a", "b", "c", "d"])
    a.add_argument("karar", choices=["cikar", "tekrar", "kabul"])
    a.add_argument("--not", dest="note", default="", help="kullanıcının gerekçesi (kayda geçer)")
    a.set_defaults(func=_yonler_cmd)
    a = act.add_parser("apply", help="<alan>.out.json cevaplarını denetle ve yonler/'e yaz")
    _src_args(a)
    a.add_argument("--model", default="ajan:belirtilmemis", help="maddeleri yazan ajan/model (kayda geçer)")
    a.set_defaults(func=_yonler_cmd)
