"""`bidr onceki-yil cek|goster|kaldir` ve `bidr write karsilastirma-ekle prepare|apply|sonuc`.

Kapısızdır (check_gate yok): geçen yılın raporu hattın isteğe bağlı girdisidir; yoksa hiçbir aşama onu beklemez.
"""
from __future__ import annotations

import re
from pathlib import Path


def _cek(args) -> int:
    from . import baglam as OY
    from . import oku as O
    try:
        v = O.oku(Path(args.rapor))
    except (FileNotFoundError, ValueError) as e:
        print(f"HATA {e}")
        return 2
    except Exception as e:  # bozuk docx/pdf: açık hata, çalışma alanına bir şey yazılmaz
        print(f"HATA rapor okunamadı: {type(e).__name__}: {e}")
        return 2
    if not v["ozet"]["aciklamali"]:
        print("HATA raporda açıklaması dolu ölçüt bulunamadı (FR-0833 biçiminde doldurulmuş rapor mu?); yazılmadı")
        return 2
    if not args.cikti and not args.workspace:
        print("HATA -w <çalışma alanı> ya da --cikti gerekli")
        return 2
    hedef = Path(args.cikti) if args.cikti else OY.yol(Path(args.workspace))
    eski = OY.yukle(hedef.parent) if not args.cikti else None
    O.yaz(v, hedef)
    oz = v["ozet"]
    print(f"{v['kaynak']['ad']} ({v['kaynak']['bicim']}): {oz['olcut']} ölçüt, {oz['aciklamali']} açıklamalı, "
          f"OD bulunan {oz['od_bulunan']} (rubrik işareti {oz['od_isaret']}, kanıt kodları {oz['od_kanit_kodlari']})")
    for u in v["uyarilar"]:
        print(f"  uyarı: {u}")
    if eski and (eski.get("kaynak") or {}).get("sha256") == v["kaynak"]["sha256"]:
        print(f"→ {hedef} (aynı rapor; içerik yenilendi)")
    else:
        print(f"→ {hedef}")
    print("Kanıt değildir: yalnız yazım/doğrulama paketlerine karşılaştırma bağlamı olarak girer. Var olan metinler "
          "kendiliğinden yeniden yazılmaz; isteğe bağlı tek seferlik geçiş: bidr write karsilastirma-ekle prepare")
    return 0


def _goster(args) -> int:
    from . import baglam as OY
    v = OY.yukle(Path(args.workspace))
    if v is None:
        print("geçen yılın raporu yok")
        return 0
    oz = v["ozet"]
    print(f"{v['kaynak']['ad']}: {oz['aciklamali']} açıklamalı ölçüt, OD bulunan {oz['od_bulunan']}")
    if args.olcut:
        r = OY.kayit(v, args.olcut)
        print(OY.ozet(r, OY.YAZIM_SINIRI) if r else f"{args.olcut}: kayıt yok")
    return 0


def _kaldir(args) -> int:
    from . import baglam as OY
    p = OY.yol(Path(args.workspace))
    if p.exists():
        p.unlink()
        print(f"kaldırıldı: {p} (var olan metinler değişmez)")
    else:
        print("geçen yılın raporu zaten yok")
    return 0


def register(sub):
    p = sub.add_parser("onceki-yil", help="geçen yılın doldurulmuş BİDR raporu (yalnız karşılaştırma; kanıt değildir)")
    act = p.add_subparsers(dest="action", required=True)
    a = act.add_parser("cek", help="rapordan (docx ya da pdf) ölçüt başına OD, açıklama ve kanıt adlarını çıkar "
                                   "→ <ws>/onceki-yil.json (modelsiz)")
    a.add_argument("--workspace", "-w", help="çalışma alanı (--cikti verilmezse gerekli)")
    a.add_argument("--rapor", required=True, help="geçen yılın doldurulmuş FR-0833 raporu (.docx ya da .pdf)")
    a.add_argument("--cikti", help="çıktı yolu (vars. <ws>/onceki-yil.json)")
    a.set_defaults(func=_cek)
    a = act.add_parser("goster", help="özet; --olcut ile o ölçütün yazım paketine giren özeti")
    a.add_argument("--workspace", "-w", required=True)
    a.add_argument("--olcut")
    a.set_defaults(func=_goster)
    a = act.add_parser("kaldir", help="<ws>/onceki-yil.json'u kaldır (sonraki yazımlarda karşılaştırma bağlamı olmaz)")
    a.add_argument("--workspace", "-w", required=True)
    a.set_defaults(func=_kaldir)


# -- bidr write karsilastirma-ekle ------------------------------------------------------------------

def _ks(args) -> int:
    from . import karsilastirma as KS
    only = [x.strip().upper() for x in re.split(r"[,\s]+", args.only) if x.strip()] if getattr(args, "only", None) else None
    try:
        if args.ks_action == "prepare":
            st = KS.prepare(args.workspace, only=only)
            print(f"{len(st['paket'])} paket ({st['yeni']} yeni/değişen), bekleyen {st['bekleyen']} → {st['klasor']}")
            for k, v in st["atlanan"].items():
                if v:
                    print(f"  atlanan ({k}): {len(v)}")
            if st["paket"]:
                print(f"Ajan (metni yazmamış, taze): {st['klasor']}/README.md; sonra: bidr write karsilastirma-ekle "
                      f"apply -w {args.workspace} --model <ad>")
            return 0
        if args.ks_action == "apply":
            st = KS.apply(args.workspace, model=args.model)
            print(f"eklendi (doğrulamaya gider)={len(st['eklendi'])} değişiklik yok={len(st['degisiklik_yok'])} "
                  f"kod reddi={len(st['kod_reddi'])} geçersiz={len(st['gecersiz'])} bekleyen={len(st['bekleyen'])} "
                  f"eski={len(st['eski'])}")
            for c, s in {**st["kod_reddi"], **st["gecersiz"]}.items():
                print(f"  {c}: " + "; ".join(s[:3]))
            if st["eklendi"]:
                print(f"Sıradaki (yalnız değişenler): bidr verify prepare -w {args.workspace} --only "
                      + ",".join(st["eklendi"]))
            return 1 if st["gecersiz"] else 0
        st = KS.sonuc(args.workspace)
        print(f"eklendi={len(st['eklendi'])} reddedildi (eski metin geri)={len(st['reddedildi'])} "
              f"doğrulama bekliyor={len(st['dogrulama_bekliyor'])}")
        return 0
    except (FileNotFoundError, KeyError, ValueError) as e:
        print(f"HATA {e}")
        return 2


def register_write(act):
    """`bidr write` altına `karsilastirma-ekle` (bidr/write/cli.py çağırır)."""
    p = act.add_parser("karsilastirma-ekle", help="TEK SEFERLİK: geçen yılın raporu sonradan gelince doğrulanmış "
                                                  "metinlere gerekirse 1-2 karşılaştırma cümlesi (kendiliğinden çalışmaz)")
    ka = p.add_subparsers(dest="ks_action", required=True)
    a = ka.add_parser("prepare", help="paketler work/karsilastirma/<ölçüt>.json")
    a.add_argument("--workspace", "-w", required=True)
    a.add_argument("--only", metavar="OLCUT[,…]")
    a.set_defaults(func=_ks)
    a = ka.add_parser("apply", help="cevapları kodla uygula (yalnız eklenen/değişen cümle); değişen metin taslak olur")
    a.add_argument("--workspace", "-w", required=True)
    a.add_argument("--model", default="ajan:belirtilmemis")
    a.set_defaults(func=_ks)
    a = ka.add_parser("sonuc", help="doğrulama sonrası: geçen ekleme kalır, reddedilende eski metin geri gelir "
                                    "(verify apply da çağırır)")
    a.add_argument("--workspace", "-w", required=True)
    a.set_defaults(func=_ks)
