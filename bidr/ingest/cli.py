"""`bidr ingest SOURCE --workspace WS`"""
from __future__ import annotations

from collections import Counter
from pathlib import Path


def _cmd(args) -> int:
    from bidr.pipeline.gate import check_gate
    from .pipeline import run

    if (rc := check_gate(args.workspace, "ingest", kaynak=args.source)) is not None:
        return rc

    rows = run(Path(args.source), Path(args.workspace), force=args.force,
               use_ocr=not args.no_ocr, workers=args.workers)
    c = Counter(r["status"] for r in rows)
    print(" ".join(f"{k}={v}" for k, v in sorted(c.items())))
    return 0


def _onar(args) -> int:
    import json

    from bidr.common import Workspace
    from . import onar as O

    ws = Workspace(args.workspace)
    kaynak = args.kaynak
    if not kaynak:
        from bidr.init.config import load_section
        kaynak = (load_section(ws.root) or {}).get("kaynak")
    if not kaynak:
        print("HATA: kaynak klasör bilinmiyor (config.yaml `bidr.kaynak` yok); --kaynak verin")
        return 2
    esleme = json.loads(Path(args.esleme).read_text(encoding="utf-8")) if args.esleme else None
    try:
        pl = O.plan(ws.root, Path(kaynak), yedek=Path(args.yedek) if args.yedek else None, esleme=esleme,
                    onbellek=not args.onbelleksiz)
    except (FileNotFoundError, ValueError) as e:
        print(f"HATA: {e}")
        return 2
    c = pl["ciftler"]
    print(f"envanter: {pl['envanter']} belge · arşivde/yedekte kimliği kayıp: {pl['kayip']} · "
          f"önbellek kaydı: {pl['onbellek_kaydi']}")
    print(f"eski kimliğine geri bağlanacak: {len(c)} belge "
          f"(kanıt önbellek+metin: {sum(1 for x in c if set(x['kanit']) >= {'onbellek', 'metin'})}, "
          f"yalnız önbellek: {sum(1 for x in c if x['kanit'] == ['onbellek'])}, "
          f"yalnız metin: {sum(1 for x in c if x['kanit'] == ['metin'])}, "
          f"elle: {sum(1 for x in c if 'elle' in x['kanit'])})")
    for x in c:
        print(f"  {x['eski']} ← {x['yeni']}  {x['rel_path']}" + ("" if x["metin_ayni"] else "  [METİN DEĞİŞMİŞ]"))
    for ad, baslik in (("yeniden_uretilmis", "yeni kimlikle yeniden işlenmiş (dokunulmaz)"),
                       ("cikmis", "kaynaktan gerçekten çıkmış"), ("eski_surum", "daha eski kayma (yenisi geçerli)"),
                       ("celiski", "ÇELİŞKİ (önbellek ≠ metin; dokunulmaz)"),
                       ("cozulemedi", "çözülemedi (kanıt yok; dokunulmaz)")):
        if pl[ad]:
            print(f"{baslik}: {len(pl[ad])}")
            if args.ayrinti or ad in ("celiski", "cozulemedi"):
                for x in pl[ad]:
                    print("  " + json.dumps(x, ensure_ascii=False))
    print(f"kimlik sabitlenecek (göç): {pl['sabitlenecek']} · ozgun_sha256 yazılacak satır: {pl['ozgun_yazilacak']} · "
          f"envanter dışı okuma paketi: {len(pl['oksuz_paket'])} · belirsiz bekleyen: {pl['bekleyen']}")
    for ad, v in pl["insan_kayitlari"].items():
        print(f"{ad}: {v['belge']} belge; envanter dışı {v['envanter_disi_once']} → {v['envanter_disi_sonra']}")
    if pl["metin_degisti"]:
        print(f"kararı `metin_degisti` olan belge: {len(pl['metin_degisti'])} (önceki karar kayıtta duruyor; "
              f"--metin-degisti-geri-al ile geri alınır): {', '.join(pl['metin_degisti'][:8])}")
    if not args.uygula:
        print("KURU KOŞU: hiçbir şey yazılmadı. Yazmak için --uygula")
        return 0
    st = O.uygula(ws.root, pl, degisen_metin=args.degisen_metin, kabul=args.kabul,
                  metin_degisti_geri_al=args.metin_degisti_geri_al)
    if args.metin_degisti_geri_al:
        print(f"`metin_degisti` kararı önceki hâline döndürülen belge: {st['metin_degisti_geri']}")
    print(f"uygulandı: {st['geri_baglanan']} belge eski kimliğine bağlandı; satırlar {st['satir']}; "
          f"metin {st['metin']}; iş paketi {st['paket']}; sabitlenen kimlik {st['sabitlenen']}; "
          f"kenara alınan okuma paketi {st['oksuz_paket']}; belirsiz kalan {st['bekleyen_kalan']}")
    for x in st["degisen_metin"]:
        print(f"  maskeli kopyasının metni değişmiş: {x['doc_id']} {x['rel_path']} → {x['metin']} metin geçerli")
    print(f"önceki hâl ve kenara alınanlar: {st['arsiv']}")
    if args.yedek:
        for ad, v in O.yedekle_karsilastir(ws.root, Path(args.yedek)).items():
            print(f"yedek karşılaştırma {ad}: {v['ayni']}/{v['yedek_belge']} belge birebir aynı; "
                  f"farklı {len(v['farkli'])}, eksik {len(v['eksik'])}, yedekte olmayan {v['fazla']}")
    return 0


def register(sub):
    q = sub.add_parser("kimlik-onar", help="kimliği kaymış belgelerin kayıtlarını eski kimliklerine geri bağla "
                                           "(maskeli kopya yeniden üretilince); varsayılan kuru koşu")
    q.add_argument("--workspace", "-w", required=True, help="çalışma klasörü")
    q.add_argument("--kaynak", help="maskeli kaynak klasör (varsayılan: config.yaml)")
    q.add_argument("--yedek", help="önceki tutarlı kopya (decisions.jsonl …): karşılaştırma ve arşivde olmayan kararlar")
    q.add_argument("--esleme", help="elle eşleme JSON'u: {eski doc_id: maskeli göreli yol}")
    q.add_argument("--onbelleksiz", action="store_true", help="maskeleme önbelleğini okuma (yalnız metin eşitliği)")
    q.add_argument("--degisen-metin", choices=("eski", "yeni"), default="eski",
                   help="maskeli kopyasının metni gerçekten değişen belgede hangi metin kalsın (eski: kararlar "
                        "geçerli kalır; yeni: belge yeniden karara gider)")
    q.add_argument("--kabul", action="store_true", help="çözülemeyen belirsiz kimlikleri kapat (kayıtları _oksuz/ altında kalır)")
    q.add_argument("--metin-degisti-geri-al", action="store_true",
                   help="kararı `metin_degisti` olan belgelerin önceki kararını geri yükle (ingest'in model metnini "
                        "ezdiği belgeler; metin gerçekten değiştiyse decide prepare yine yakalar)")
    q.add_argument("--ayrinti", action="store_true")
    q.add_argument("--uygula", action="store_true", help="yaz (yoksa kuru koşu)")
    q.set_defaults(func=_onar)

    p = sub.add_parser("ingest", help="kaynak klasörü tara: inventory.csv + text/<doc_id>.txt")
    p.add_argument("source", help="kaynak klasör (salt okunur)")
    p.add_argument("--workspace", "-w", required=True, help="çalışma klasörü (repo dışı)")
    p.add_argument("--force", action="store_true", help="metni olan belgeleri de yeniden işle")
    p.add_argument("--no-ocr", action="store_true", help="OCR yapma (taranmış sayfalar needs_ocr kalır)")
    p.add_argument("--workers", type=int, default=None, help="paralel dosya sayısı (varsayılan: çekirdek)")
    p.set_defaults(func=_cmd)
