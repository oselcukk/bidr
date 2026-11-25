"""`bidr teslim -w WS [--out DIR] [--tarih YYYY-AA-GG] [--zip-yok] [--pdf-araci …] [--canli] [--taslak]
[--kararsizlari-disla]`.

Dekanlığa teslim paketi: dolu rapor, ölçüt klasörlü kanıtlar, web sayfası kanıtlarının alınma tarihli
PDF kopyaları ve kanıt dizini (bidr/teslim/run.py). Maskeleme kararı bekleyen kanıt pakete o anki
maskeli hâliyle (maskelenemediyse özgünüyle) girer, konsolda ve MASKELEME-UYARI.txt'de listelenir (çıkış
kodunu değiştirmez). Çıkış kodu: 0 paket eksiksiz; 1 paket eksik ya da (`--kararsizlari-disla` ile)
kararı bekleyen kanıt pakete girmedi (EKSIK.txt; listelenir); 2 girdi hatası ya da PDF aracı yok (hiçbir şey yazılmaz);
3 kapı (biçim denetimi geçmedi; `--taslak` ile taslak paket üretilebilir). Kişisel veri maskelemesi teslimi
durdurmaz: eksik / eski ya da kapalıysa paket yine üretilir, uyarı konsolda ve paketteki MASKELEME-UYARI.txt'de."""
from __future__ import annotations

import sys
from pathlib import Path


def _run(args) -> int:
    from bidr.pipeline.gate import check_gate

    from .run import TeslimError, build, ozet_json
    from .web import PdfAraciYok

    ws = Path(args.workspace).expanduser().resolve()
    if not args.taslak and (rc := check_gate(ws, "teslim")) is not None:
        print("  (taslak paket için: bidr teslim --taslak; paket TASLAK işaretli olur)", file=sys.stderr)
        return rc
    try:
        res = build(ws, Path(args.out) if args.out else None, docx_path=Path(args.docx) if args.docx else None,
                    tarih=args.tarih, zip_yap=not args.zip_yok, arac=args.pdf_araci, canli=args.canli,
                    taslak=args.taslak, kararsizlari_disla=args.kararsizlari_disla,
                    oldugu_gibi=True if args.oldugu_gibi else None)
    except PdfAraciYok as e:
        print(f"HATA {e}", file=sys.stderr)
        return 2
    except (TeslimError, ValueError) as e:
        print(f"HATA {e}", file=sys.stderr)
        return 2
    for u in res.uyarilar:
        print(f"uyarı: {u}")
    print(ozet_json(res))
    if res.maskeleme_uyarisi:
        print(f"UYARI kişisel veri: {res.maskeleme_uyarisi}", file=sys.stderr)
        for x in res.maskesiz:
            print(f"  - {x['olcut']} [{x['kanit_no']}] {x['dosya']} (MASKELENMEDİ)", file=sys.stderr)
    pakette = [x for x in res.karar_bekleyen if x["pakette"]]
    if pakette:
        from .run import KARAR_BASLIK, MASKE_OZGUN
        print(f"UYARI {KARAR_BASLIK.format(n=len(pakette))} (pakette; kesin kapatmalar uygulandı, kararsız öneriler "
              "açık; 'maskelenmedi' olanlar ÖZGÜN dosya):", file=sys.stderr)
        for x in pakette:
            v = "MASKELENMEDİ" if x["maskeleme"] == MASKE_OZGUN else x["maskeleme"]
            print(f"  - {x['olcut']} [{x['kanit_no']}] {x['dosya']} ({v}): {x['neden']}", file=sys.stderr)
        print(f"  → bidr maskele bolgeler -w {ws} ; karar/yukle, sonra bidr maskele -w {ws} ve bidr teslim "
              "(eski davranış: --kararsizlari-disla)", file=sys.stderr)
    if res.kontrol_bekliyor:
        from .run import KONTROL_BASLIK
        print(KONTROL_BASLIK.format(n=len(res.kontrol_bekliyor)) + " (--kararsizlari-disla: pakete girmedi; "
              "rapordaki atıf ve numara değişmedi):")
        for x in res.kontrol_bekliyor:
            print(f"  - {x['olcut']} [{x['kanit_no']}] {x['kanit']}: {x['neden']}")
        print(f"  → bidr maskele bolgeler -w {ws} ; bidr maskele karar -w {ws} <bolge_id> kapat|birak ; "
              f"ya da bidr maskele yukle -w {ws} <kanit> <maskeli_dosya> ; sonra bidr maskele -w {ws} ve bidr teslim")
    if res.elle_bakilacak:
        print(f"NOT ({len(res.elle_bakilacak)}):")
        for x in res.elle_bakilacak:
            print(f"  - {x['dosya']}: {x['neden']}")
    elif not res.maskeleme:
        print("bilgi: kişisel veri maskelemesi yapılmadı (bidr maskele); dizinde 'Maskeleme: yapılmadı'")
    if res.taslak:
        print("Paket TASLAK: biçim denetimi geçmeden üretildi (EKSIK.txt); teslimden önce yeniden üretin.")
    if res.eksik:
        print(f"EKSİK PAKET: raporun {len(res.eksik)} kanıt satırı paketteki bir dosyayla eşleşmedi ya da "
              "PDF kopyası üretilemedi:")
        for e in res.eksik:
            print(f"  - {e}")
    print(f"teslim: {res.cikti}" + (f"\nzip: {res.zip}" if res.zip else ""))
    return 1 if (res.eksik or res.kontrol_bekliyor) else 0


def register(sub):
    p = sub.add_parser("teslim", help="dekanlığa teslim paketi: rapor + ölçüt klasörlü kanıtlar + web "
                                      "kanıtlarının alınma tarihli PDF kopyası + kanıt dizini (klasör + zip)")
    p.add_argument("--workspace", "-w", required=True)
    p.add_argument("--out", default=None, help="paket klasörü (vars.: WS/BIDR-<dönem>-<Birim>; zip: aynı adla .zip)")
    p.add_argument("--docx", default=None, help="rapor (vars.: WS/report.docx)")
    p.add_argument("--tarih", default=None,
                   help="alınma (raporlama) tarihi, YYYY-AA-GG (vars.: bugün); web PDF damgasına ve dizine yazılır")
    p.add_argument("--zip-yok", action="store_true", help="zip yazma (yalnız klasör)")
    p.add_argument("--pdf-araci", choices=["otomatik", "chrome", "weasyprint"], default="otomatik",
                   help="web sayfasını PDF'e basan araç (vars.: otomatik: Chrome/Chromium/Edge, yoksa weasyprint)")
    p.add_argument("--canli", action="store_true",
                   help="web kanıtını özgün adresinden yeniden indirip bas (adres biliniyorsa; vars.: kaydedilmiş sayfa)")
    p.add_argument("--taslak", action="store_true",
                   help="biçim denetimi geçmeden taslak paket üret (EKSIK.txt'de TASLAK; hat bitmiş saymaz)")
    p.add_argument("--kararsizlari-disla", action="store_true",
                   help="maskeleme kararı bekleyen (ya da maskelenemeyen) kanıtı pakete alma (eski davranış; "
                        "varsayılan: o anki maskeli hâliyle girer ve listelenir)")
    p.add_argument("--oldugu-gibi", action="store_true",
                   help="olduğu gibi devam: maskeleme kararı bekleyen kanıtlar incelenmeden o anki (kendiliğinden "
                        "maskelenmiş) hâlleriyle girer, 'incelenmemiş öneri vardı, olduğu gibi eklendi' diye listelenir "
                        "(panel bölümün seçimini <ws>/maskeleme-oldugu-gibi.json'a yazar)")
    p.set_defaults(func=_run)
