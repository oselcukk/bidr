"""`bidr maskele` iki kullanım:

- teslim/yayın kopyası: `bidr maskele -w WS [--evidence DIR] [--out DIR] [--motor …] [--ad-listesi DOSYA]
  [--yalniz-oneri | --yalniz-kaynak]` (`--yalniz-oneri`: hiçbir tespit kendiliğinden kapatılmaz, hepsi öneri olur;
  yalnız insan kararları — `karar kapat`, `ciz`, `yukle` — uygulanır; docx/xlsx/düz metin/html'de desen başına
  sayfasız öneri. `--yalniz-kaynak`: "olduğu gibi devam" sonrası; hiçbir maske hesaplanmaz, yalnız kaynak kipin ve
  önbelleğin var olan maskeleri kopyalanır, olmayan dosya "maskelenmedi" diye listelenir)
- iki kipte de dosya başına süre sınırı (`--dosya-suresi`, `--sayfa-suresi`; ortam `BIDR_MASKE_DOSYA_SURESI`,
  `BIDR_MASKE_SAYFA_SURESI`, `BIDR_MASKE_MB_SURESI`; varsayılan 120 sn + PDF'de sayfa başına 30 sn, başka biçimde MB
  başına 10 sn; 0: sınırsız): aşan dosyanın süreci kesilir, dosya "maskelenemedi, elle bakılmalı" (`zaman_asimi`)
- model öncesi kaynak maskeleme: `bidr maskele --kaynak BÖLÜM_KLASÖRÜ --out MASKELİ_KOPYA [-w WS]
  [--motor …] [--ad-listesi DOSYA] [--is N] [--rapor DOSYA] [--ayir]`
  (`-w` ile: çalışma alanı önbelleği `.cache/maske.sqlite`, ilerleme `<ws>/maskeleme-ilerleme.json`; işaret
  `.bidr-maskeleme.json` koşunun başında `durum: yarim`, sonunda `tamam`: kesilen koşu kaldığı yerden sürer)

İnsan kontrolü (teslim kapısı; bkz. `inceleme`):

- `bidr maskele bolgeler -w WS [--json]`: onay bekleyen bölgeler (`--json`: bütün bölgeler + dosya/sayfa bilgisi);
- `bidr maskele karar -w WS <bolge_id> kapat|birak|sil [--kim AD]`: bölge kararı (sonraki `bidr maskele`
  uygular); `sil` yalnız kullanıcı bölgesi;
- `bidr maskele ciz -w WS <dosya> --sayfa N --kutu x0,y0,x1,y1 [--kim AD] [--json]`: kullanıcı bölgesi
  (kalıcı gerçek redaksiyon; şablon belleğine öneri örneği);
- `bidr maskele sayfa -w WS <dosya> --sayfa N [--dpi 110] [-o cikti.png] [--maskeli] [--json]`: sayfa görüntüsü;
- `bidr maskele yukle -w WS <dosya> <maskeli_dosya> [--kim AD] [--zorla]`: elle maskelenmiş sürüm.

`<dosya>`: rapordaki dosya yolu, klasördeki yol ya da belge kimliği (sha256 / öneki). Rapor: kanıt modunun
`<ws>/maskeleme-raporu.json`'u, yoksa ön işlemenin `<ws>/maskeleme-kaynak-raporu.json`'u (`--kaynak … -w WS`).
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
                       progress=progress, ayir=args.ayir, ws=ws, onbellek_kullan=not args.onbellek_yok,
                       sure=_sure(args))
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


def _sure(args):
    from bidr.havuz import sure_ayari
    return sure_ayari(args.dosya_suresi, args.sayfa_suresi)


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
            if b.get("konum"):                       # bölgesiz biçim: sayfasız öneri
                print(f"    {b['id']}  {b['konum']}  {b['tur']}  {b['neden']} ({b['kaynak']})")
                continue
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
    if getattr(args, "json", False):
        print(json.dumps(d, ensure_ascii=False))
        return 0
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


def _ciz(args) -> int:
    from .inceleme import IncelemeError, ciz
    ws = _ws_req(args)
    if ws is None:
        return 2
    try:
        d = ciz(ws, args.dosya, args.sayfa, args.kutu, args.kim)
    except IncelemeError as e:
        print(f"HATA {e}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(d, ensure_ascii=False, indent=1))
        return 0
    if d.get("uyari"):
        print(f"uyarı: {d['uyari']}")
    k = ", ".join(f"{v:.1f}" for v in d["kutu"])
    print(f"kullanıcı bölgesi: {d['id']} s.{d['sayfa']} [{k}] (sonraki `bidr maskele` uygular; silmek için "
          f"bidr maskele karar -w {ws} {d['id']} sil)")
    return 0


def _sayfa(args) -> int:
    from .inceleme import IncelemeError, sayfa
    ws = _ws_req(args)
    if ws is None:
        return 2
    if not args.o and not args.json:
        print("HATA -o çıktı.png (ya da yalnız bilgi için --json) gerekli", file=sys.stderr)
        return 2
    try:
        d = sayfa(ws, args.dosya, args.sayfa, args.dpi, Path(args.o) if args.o else None, maskeli=args.maskeli)
    except IncelemeError as e:
        print(f"HATA {e}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(d, ensure_ascii=False, indent=1))
    else:
        print(f"{d['png']}: s.{d['sayfa']}/{d['sayfa_sayisi']} {d['genislik']:.1f}×{d['yukseklik']:.1f} pt, {d['dpi']} dpi")
    return 0


def _run(args) -> int:
    islem = getattr(args, "islem", None)
    if islem == "ciz":
        return _ciz(args)
    if islem == "sayfa":
        return _sayfa(args)
    if islem == "bolgeler":
        return _bolgeler(args)
    if islem == "karar":
        return _karar(args)
    if islem == "yukle":
        return _yukle(args)
    if args.kaynak:
        if args.yalniz_oneri or args.yalniz_kaynak:
            print("HATA --yalniz-oneri / --yalniz-kaynak yalnız kanıt kipinde (-w) kullanılır", file=sys.stderr)
            return 2
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
                progress=progress, yalniz_oneri=args.yalniz_oneri, yalniz_kaynak=args.yalniz_kaynak,
                sure=_sure(args))
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
        print(f"maskeleme kararı bekleyen: {n} dosya (teslim paketine o anki maskeli hâliyle girer ve "
              f"listelenir) → bidr maskele bolgeler -w {ws}")
    return 1 if (r["yayimlanamaz"] or n) else 0


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
                   help="paralel işçi sayısı (varsayılan: kanıt modunda 2, --kaynak modunda 1; işleyici çekirdek "
                        "sayısını verir)")
    p.add_argument("--ilerleme", action="store_true", help="dosya başına ilerleme yaz")
    p.add_argument("--yalniz-oneri", action="store_true",
                   help="kanıt kipi: hiçbir tespit kendiliğinden kapatılmaz; hepsi onay bekleyen öneri olur (insan "
                        "kararları uygulanır); docx/xlsx/düz metin/html metni değiştirilmez, desen başına öneri yazılır; "
                        "üst veri temizliği yine yapılır")
    p.add_argument("--yalniz-kaynak", action="store_true",
                   help="kanıt kipi, \"olduğu gibi devam\" sonrası: hiçbir maske hesaplanmaz; kaynak kipin ve "
                        "önbelleğin var olan maskeleri kullanılır, olmayan dosya olduğu gibi kalır ve 'maskelenmedi' "
                        "diye listelenir")
    p.add_argument("--dosya-suresi", type=float, default=None,
                   help="dosya başına süre sınırı tabanı, sn (varsayılan BIDR_MASKE_DOSYA_SURESI ya da 120; 0: "
                        "sınırsız); aşan dosya 'maskelenemedi, elle bakılmalı'")
    p.add_argument("--sayfa-suresi", type=float, default=None,
                   help="PDF'de sayfa başına ek süre, sn (varsayılan BIDR_MASKE_SAYFA_SURESI ya da 30)")
    p.add_argument("--onbellek-yok", action="store_true",
                   help="çalışma alanı önbelleğini (.cache/maske.sqlite) kullanma (kanıt modu; --kaynak modunda "
                        "-w verildiyse)")
    p.add_argument("--motor", choices=("auto", "pymupdf", "pypdf"), default="auto",
                   help="PDF motoru: pymupdf gerçek kaldırma; pypdf en iyi çaba (varsayılan: varsa pymupdf)")
    p.add_argument("--ad-listesi", default=None,
                   help="ek ad listesi (.txt satır başına bir ad ya da .csv ilk sütun); "
                        "config.yaml privacy.maskeleme.ad_listesi'ne eklenir")
    p.set_defaults(func=_run, islem=None)
    alt = p.add_subparsers(dest="islem", metavar="{bolgeler,karar,ciz,sayfa,yukle}")

    def ws_arg(q):
        q.add_argument("--workspace", "-w", default=argparse.SUPPRESS, help="çalışma alanı")
    q = alt.add_parser("bolgeler", help="onay bekleyen bölgeleri listele (teslim kapısı)")
    ws_arg(q)
    q.add_argument("--json", action="store_true", help="JSON çıktı")
    q = alt.add_parser("karar", help="bölge kararı: kapat | birak (sonraki bidr maskele uygular)")
    ws_arg(q)
    q.add_argument("bolge_id")
    q.add_argument("karar", choices=("kapat", "birak", "sil"), help="sil: yalnız `ciz` ile çizilen bölge")
    q.add_argument("--kim", default=None, help="kararı veren (varsayılan: kullanıcı adı)")
    q.add_argument("--json", action="store_true", help="yazılan karar satırı JSON")
    q = alt.add_parser("ciz", help="kullanıcı bölgesi ekle (kalıcı gerçek redaksiyon; şablon belleğine öneri örneği)")
    ws_arg(q)
    q.add_argument("dosya", help="rapordaki dosya yolu, klasördeki yol ya da belge kimliği (sha256)")
    q.add_argument("--sayfa", type=int, required=True, help="sayfa no (1'den)")
    q.add_argument("--kutu", required=True, help="x0,y0,x1,y1: görüntülenen sayfada PDF puanı, sol üst köken")
    q.add_argument("--kim", default=None)
    q.add_argument("--json", action="store_true", help="yeni bölge kaydı JSON (id dahil)")
    q = alt.add_parser("sayfa", help="belgenin sayfa görüntüsü (PNG) ve sayfa boyutları")
    ws_arg(q)
    q.add_argument("dosya", help="rapordaki dosya yolu, klasördeki yol ya da belge kimliği (sha256)")
    q.add_argument("--sayfa", type=int, default=1, help="sayfa no (1'den)")
    q.add_argument("--dpi", type=int, default=110, help="çözünürlük (PNG ölçeği = dpi/72)")
    q.add_argument("-o", default=None, help="çıktı PNG yolu")
    q.add_argument("--maskeli", action="store_true", help="maskeli kopyanın sayfası")
    q.add_argument("--json", action="store_true", help="sayfa sayısı ve boyut (pt) JSON")
    q = alt.add_parser("yukle", help="elle maskelenmiş sürümü kabul et (kayıt 'elle maskelendi')")
    ws_arg(q)
    q.add_argument("kanit", help="kanıt dosyası (evidence/ içindeki yol ya da evidence/'e göreli yol)")
    q.add_argument("maskeli", help="elle maskelenmiş dosya")
    q.add_argument("--kim", default=None)
    q.add_argument("--zorla", action="store_true", help="yüklenen dosyada desen bulgusu kalsa da kabul et")
