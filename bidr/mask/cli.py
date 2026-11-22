"""`bidr maskele` iki kullanım:

- teslim/yayın kopyası: `bidr maskele -w WS [--evidence DIR] [--out DIR] [--motor …] [--ad-listesi DOSYA]`
- model öncesi kaynak maskeleme: `bidr maskele --kaynak BÖLÜM_KLASÖRÜ --out MASKELİ_KOPYA [-w WS]
  [--motor …] [--ad-listesi DOSYA] [--is N] [--rapor DOSYA] [--ayir]`

İnsan kontrolü (teslim kapısı; bkz. `inceleme`):

- `bidr maskele bolgeler -w WS [--json]`: onay bekleyen bölgeler;
- `bidr maskele karar -w WS <bolge_id> kapat|birak [--kim AD]`: bölge kararı (sonraki `bidr maskele` uygular);
- `bidr maskele yukle -w WS <kanit_dosyasi> <maskeli_dosya> [--kim AD] [--zorla]`: elle maskelenmiş sürüm.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _rules(args, base: Path | None):
    from .detect import MaskRules, load_name_list, read_ws_config
    rules = MaskRules.from_config(read_ws_config(base), base) if base else MaskRules()
    if args.ad_listesi:
        from dataclasses import replace
        rules = replace(rules, names=tuple(rules.names) + tuple(load_name_list(args.ad_listesi, base or Path.cwd())))
    return rules


def _run_source(args) -> int:
    from .formats import MaskError
    from .kaynak import run_source
    from .run import MaskRunError
    if not args.out:
        print("HATA --kaynak ile --out (maskeli kopya klasörü) zorunlu", file=sys.stderr)
        return 2
    ws = Path(args.workspace).expanduser().resolve() if args.workspace else None

    def progress(i, n, rel):
        if args.ilerleme:
            print(f"[{i}/{n}] {rel}", file=sys.stderr, flush=True)
    try:
        r = run_source(Path(args.kaynak), Path(args.out), rules=_rules(args, ws), engine=args.motor,
                       workers=max(1, args.is_ or 1), report=Path(args.rapor) if args.rapor else None,
                       progress=progress, ayir=args.ayir, ws=ws)
    except (FileNotFoundError, MaskRunError, MaskError, ValueError) as e:
        print(f"HATA {e}", file=sys.stderr)
        return 2
    for u in r["uyarilar"]:
        print(f"uyarı: {u}")
    print(json.dumps(r["ozet"], ensure_ascii=False, indent=1))
    print(f"rapor: {r['rapor']}")
    if r.get("ayrilan_klasor"):
        print(f"--ayir: {len(r['ayrilan'])} dosya maskeli kopyanın dışına ayrıldı: {r['ayrilan_klasor']}")
    if r["elle_bakilmali"]:
        print(f"ELLE BAKILMALI ({len(r['elle_bakilmali'])}):")
        for y in r["elle_bakilmali"]:
            print(f"  [{y['durum']}] {y['hedef'] or y['dosya']}: {y['neden']}")
        return 1
    return 0


def _ws_req(args) -> Path | None:
    if not args.workspace:
        print("HATA --workspace/-w gerekli", file=sys.stderr)
        return None
    return Path(args.workspace).expanduser().resolve()


def _bolgeler(args) -> int:
    from .inceleme import IncelemeError, bekleyenler
    ws = _ws_req(args)
    if ws is None:
        return 2
    try:
        r = bekleyenler(ws)
    except IncelemeError as e:
        print(f"HATA {e}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 1 if (r["bolgeler"] or r["bolgesiz"]) else 0
    if not (r["bolgeler"] or r["bolgesiz"] or r["karar_verilmis"]):
        print("onay bekleyen bölge yok")
        return 0
    if r["bolgeler"]:
        print(f"ONAY BEKLEYEN BÖLGE ({len(r['bolgeler'])}; {r['dosya']} dosya):")
        last = None
        for b in r["bolgeler"]:
            if b["dosya"] != last:
                print(f"  {b['dosya']}")
                last = b["dosya"]
            k = ", ".join(f"{v:.0f}" for v in b["kutu"])
            print(f"    {b['id']}  s.{b['sayfa']}  {b['tur']}  [{k}]  {b['neden']} ({b['kaynak']}, güven {b['guven']})")
        print(f"  → bidr maskele karar -w {ws} <bolge_id> kapat|birak")
    if r["karar_verilmis"]:
        print(f"KARAR VERİLDİ, UYGULANMADI ({len(r['karar_verilmis'])}): bidr maskele -w {ws} ile uygulanır")
        for b in r["karar_verilmis"]:
            print(f"    {b['id']}  {b['karar']}  {b['dosya']}")
    if r["bolgesiz"]:
        print(f"BÖLGESİZ KONTROL BEKLEYEN ({len(r['bolgesiz'])}): yalnız elle maskelenmiş sürümle "
              f"(bidr maskele yukle -w {ws} <kanit> <maskeli_dosya>)")
        for x in r["bolgesiz"]:
            print(f"    [{x['durum']}] {x['dosya']}: {x['neden']}")
    return 1 if (r["bolgeler"] or r["bolgesiz"]) else 0


def _karar(args) -> int:
    from .inceleme import IncelemeError, karar
    ws = _ws_req(args)
    if ws is None:
        return 2
    try:
        d = karar(ws, args.bolge_id, args.karar, args.kim)
    except IncelemeError as e:
        print(f"HATA {e}", file=sys.stderr)
        return 2
    print(f"karar yazıldı: {d['id']} → {d['karar']} ({d['kim']}, {d['zaman']})")
    print(f"uygulamak için: bidr maskele -w {ws}")
    return 0


def _yukle(args) -> int:
    from .inceleme import IncelemeError, yukle
    ws = _ws_req(args)
    if ws is None:
        return 2
    try:
        r = yukle(ws, args.kanit, args.maskeli, args.kim, zorla=args.zorla)
    except IncelemeError as e:
        print(f"HATA {e}", file=sys.stderr)
        return 2
    for u in r["uyarilar"]:
        print(f"uyarı: {u}")
    print(f"elle maskelendi: {r['dosya']} → {r['maskeli']} (saklanan: {r['elle']})")
    return 0


def _run(args) -> int:
    islem = getattr(args, "islem", None)
    if islem == "bolgeler":
        return _bolgeler(args)
    if islem == "karar":
        return _karar(args)
    if islem == "yukle":
        return _yukle(args)
    if args.kaynak:
        return _run_source(args)
    from .detect import load_name_list
    from .formats import MaskError
    from .run import MaskRunError, run
    if not args.workspace:
        print("HATA --workspace/-w (ya da --kaynak) gerekli", file=sys.stderr)
        return 2
    ws = Path(args.workspace).expanduser().resolve()

    def progress(i, n, rel):
        if args.ilerleme:
            print(f"[{i}/{n}] {rel}", file=sys.stderr, flush=True)
    try:
        names = load_name_list(args.ad_listesi, ws) if args.ad_listesi else None
        r = run(ws, evidence=args.evidence, out=args.out, engine=args.motor, names=names,
                workers=max(1, args.is_ if args.is_ is not None else 2), onbellek_kullan=not args.onbellek_yok,
                progress=progress)
    except (FileNotFoundError, MaskRunError, MaskError, ValueError) as e:
        print(f"HATA {e}", file=sys.stderr)
        return 2
    for u in r["uyarilar"]:
        print(f"uyarı: {u}")
    for f in r["dosyalar"]:
        if f.get("imza_uyarisi"):
            print(f"uyarı: imza bölgesi olabilir (elle bakın): {f['dosya']} {', '.join(f['imza_uyarisi'])}")
        if f.get("imza_elle"):
            print(f"uyarı: imza elle bakılmalı: {f['dosya']} {', '.join(f['imza_elle'])}")
    print(json.dumps(r["ozet"], ensure_ascii=False, indent=1))
    if r["yayimlanamaz"]:
        print(f"YAYIMLANAMAZ ({len(r['yayimlanamaz'])}):")
        for y in r["yayimlanamaz"]:
            print(f"  {y['dosya']}: {y['neden']}")
        n = r["ozet"].get("kontrol_bekleyen_dosya", 0)
        if n:
            print(f"maskelenecek yeri var, kontrol bekliyor: {n} dosya (teslim paketine girmez) → "
                  f"bidr maskele bolgeler -w {ws}")
        return 1
    return 0


def register(sub):
    p = sub.add_parser("maskele", help="kişisel veri maskeleme: kanıtların (evidence/) yayın kopyası ya da "
                                       "--kaynak ile bölüm klasörünün model öncesi maskeli kopyası; "
                                       "asıl dosyalar değişmez")
    p.add_argument("--workspace", "-w", default=None,
                   help="çalışma alanı (evidence modu için zorunlu; --kaynak modunda config.yaml kuralları için)")
    p.add_argument("--evidence", default=None, help="kanıt klasörü (varsayılan <ws>/evidence)")
    p.add_argument("--kaynak", default=None,
                   help="model öncesi maskeleme: bölüm belge klasörü (salt okunur); maskeli kopya --out'a yazılır")
    p.add_argument("--out", default=None, help="evidence modu: çıktı kökü (varsayılan kanıt klasörünün üstü); "
                                               "--kaynak modu: maskeli kopya klasörü (zorunlu)")
    p.add_argument("--rapor", default=None,
                   help="--kaynak modu: rapor yolu (varsayılan <out>.maskeleme-raporu.json, çıktının dışında)")
    p.add_argument("--ayir", action="store_true",
                   help="--kaynak modu: maskelemesi eksik kalan/maskelenemeyen dosyalar maskeli kopyaya girmez; "
                        "<out>.elle-bakilmali/ klasörüne ayrılır ve raporda listelenir (varsayılan: kopyada kalır)")
    p.add_argument("--is", dest="is_", type=int, default=None,
                   help="paralel işçi sayısı (varsayılan: kanıt modunda 2, --kaynak modunda 1)")
    p.add_argument("--ilerleme", action="store_true", help="dosya başına ilerleme yaz")
    p.add_argument("--onbellek-yok", action="store_true",
                   help="kanıt modu: çalışma alanı önbelleğini (.cache/maske.sqlite) kullanma")
    p.add_argument("--motor", choices=("auto", "pymupdf", "pypdf"), default="auto",
                   help="PDF motoru: pymupdf gerçek kaldırma; pypdf en iyi çaba (varsayılan: varsa pymupdf)")
    p.add_argument("--ad-listesi", default=None,
                   help="ek ad listesi (.txt satır başına bir ad ya da .csv ilk sütun); "
                        "config.yaml privacy.maskeleme.ad_listesi'ne eklenir")
    p.set_defaults(func=_run, islem=None)
    alt = p.add_subparsers(dest="islem", metavar="{bolgeler,karar,yukle}")

    def ws_arg(q):
        q.add_argument("--workspace", "-w", default=argparse.SUPPRESS, help="çalışma alanı")
    q = alt.add_parser("bolgeler", help="onay bekleyen bölgeleri listele (teslim kapısı)")
    ws_arg(q)
    q.add_argument("--json", action="store_true", help="JSON çıktı")
    q = alt.add_parser("karar", help="bölge kararı: kapat | birak (sonraki bidr maskele uygular)")
    ws_arg(q)
    q.add_argument("bolge_id")
    q.add_argument("karar", choices=("kapat", "birak"))
    q.add_argument("--kim", default=None, help="kararı veren (varsayılan: kullanıcı adı)")
    q = alt.add_parser("yukle", help="elle maskelenmiş sürümü kabul et (kayıt 'elle maskelendi')")
    ws_arg(q)
    q.add_argument("kanit", help="kanıt dosyası (evidence/ içindeki yol ya da evidence/'e göreli yol)")
    q.add_argument("maskeli", help="elle maskelenmiş dosya")
    q.add_argument("--kim", default=None)
    q.add_argument("--zorla", action="store_true", help="yüklenen dosyada desen bulgusu kalsa da kabul et")
