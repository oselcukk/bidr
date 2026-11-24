"""`bidr denetim prepare|apply|karar|ozet` ve `bidr duzelt prepare` (kör denetim; bidr/kor/run.py)."""
from __future__ import annotations

import json


def _denetim(args) -> int:
    from bidr.pipeline.gate import check_gate
    if args.action in ("prepare", "apply") and (rc := check_gate(args.workspace, "kor_denetim")) is not None:
        return rc
    from bidr.common import Workspace

    from . import run as R
    try:
        if args.action == "prepare":
            st = R.prepare(args.workspace, ikinci=args.ikinci)
            print(f"kör denetim tur {st['tur']}: {st['paket']} paket ({st['olcut']} ölçüt, {st['yon']} alan yönü; "
                  f"{st['yeni']} yeni/değişen), bekleyen {st['bekleyen']} → {st['klasor']}")
            print(f"Ajan: metni YAZMAMIŞ, taze ve bağımsız bir denetçi (model Opus): {st['klasor']}/README.md")
            return 0
        if args.action == "apply":
            from bidr.pipeline.paralel import apply_oncesi
            apply_oncesi(args.workspace, "work/kor_denetim")
            st = R.apply(args.workspace, model=args.model)
            print(f"tur {st['tur']}: işlenen={st['islenen']} bekleyen={len(st['bekleyen'])} "
                  f"geçersiz={len(st['gecersiz'])} eski={len(st['eski'])}")
            for k, errs in st["gecersiz"].items():
                print(f"  geçersiz cevap {k}: {'; '.join(errs)}")
            if st["eski"]:
                print(f"  eski paket (rapor değişti; yeniden prepare): {', '.join(st['eski'])}")
            if st["yazildi"]:
                oz = st["ozet"]
                print(f"{R.OUT_JSON} ve {R.OUT_MD} yazıldı (iç ölçüm): ölçüt ortalaması {oz['ortalama']}, yön "
                      f"{oz['yon_ortalama']}, D/K/U {oz['D']}/{oz['K']}/{oz['U']}, bulgular {oz['bulgu']}")
                return 0
            return 1
        ws = Workspace(args.workspace)
        if args.action == "karar":
            r = R.decide(args.workspace, args.bulgu_id, args.karar, args.note or "")
            print(f"{r['bulgu_id']}: {r['karar']} kaydedildi ({r['sinif']}, {r['olcut']})")
            if r["karar"] == "kabul" and r["sinif"] == "od":
                print(f"{r['olcut']}: OD{r['od']} rapora ve metne yansır (sıradaki: bidr next)")
            elif r["sinif"] == "metin":
                print(f"{r['olcut']}: " + ("kabul edilmiş metin bu öneriyle küçük bir düzeltme turunda yeniden "
                                           "yazılır ve doğrulanır (sıradaki: bidr next)" if r["karar"] == "kabul"
                                           else "metin olduğu gibi kalır"))
            elif r["karar"] == "kabul":
                print(f"{r['olcut']}: belge ikinci aramaya girer, eşleşirse inceleme tablosuna aday olarak düşer "
                      "(sıradaki: bidr next)")
            return 0
        js = R.load(ws)
        if not js:
            import sys
            print(f"HATA {R.OUT_JSON} yok: kör denetim yapılmadı", file=sys.stderr)
            return 1
        v = R.view_dict(ws, js)
        if args.json:
            print(json.dumps(v, ensure_ascii=False, indent=1))
            return 0
        R.write_md(ws, v)
        print((ws.root / R.OUT_MD).read_text(encoding="utf-8"))
        return 0
    except (FileNotFoundError, KeyError, ValueError) as e:
        print(f"HATA {e}")
        return 2


def _duzelt(args) -> int:
    from bidr.pipeline.gate import check_gate
    if (rc := check_gate(args.workspace, "duzelt")) is not None:
        return rc
    from . import duzelt as D
    try:
        st = D.prepare(args.workspace)
    except (FileNotFoundError, KeyError, ValueError) as e:
        print(f"HATA {e}")
        return 2
    if st.get("olcum"):
        print(f"tur {st['tur']} ölçümdür: düzeltme yapılmaz")
        return 0
    print(f"düzeltme notuyla açılan yazım paketleri: {', '.join(st['olcut']) or 'yok'}; "
          f"yön paketleri: {', '.join(st['alan']) or 'yok'}")
    print("Sıradaki: bidr next (yazım → doğrulama → yönler → render; yazımı ve doğrulamayı ayrı, taze ajanlara ver)")
    return 0


def register(sub):
    p = sub.add_parser("denetim", help="raporun kör denetimi (isteğe bağlı; iç ölçüm): prepare | apply | karar | ozet")
    act = p.add_subparsers(dest="action", required=True)
    a = act.add_parser("prepare", help="denetim paketleri work/kor_denetim/<anahtar>.json (denetimi istemek budur)")
    a.add_argument("--workspace", "-w", required=True)
    a.add_argument("--ikinci", action="store_true",
                   help="isteğe bağlı ikinci denetim (ölçüm; önce/sonra karşılaştırması); ilk turun düzeltmesinden sonra")
    a.set_defaults(func=_denetim)
    a = act.add_parser("apply", help="denetçi cevaplarını denetle (alıntılar), sınıfla → kor-denetim.json/.md")
    a.add_argument("--workspace", "-w", required=True)
    a.add_argument("--model", default="ajan:belirtilmemis", help="denetçi ajan/model (kayda geçer)")
    a.set_defaults(func=_denetim)
    a = act.add_parser("karar", help="BÖLÜMÜN kararı, OD/kanıt önerisi ve kabul edilmiş metne öneri için: kabul | ret (ajan vermez)")
    a.add_argument("--workspace", "-w", required=True)
    a.add_argument("bulgu_id")
    a.add_argument("karar", choices=["kabul", "ret"])
    a.add_argument("--not", dest="note", default="", help="bölümün notu (kayda geçer)")
    a.set_defaults(func=_denetim)
    a = act.add_parser("ozet", help="denetim sonucu, bulgu başına güncel durum ve kararlarla")
    a.add_argument("--workspace", "-w", required=True)
    a.add_argument("--json", action="store_true")
    a.set_defaults(func=_denetim)
    p = sub.add_parser("duzelt", help="kör denetimin metin bulgularını düzeltme notuyla yazım/yön paketlerine koy")
    act = p.add_subparsers(dest="action", required=True)
    a = act.add_parser("prepare", help="düzeltme notlu yazım (work/write) ve yön (work/yonler) paketleri")
    a.add_argument("--workspace", "-w", required=True)
    a.set_defaults(func=_duzelt)
