"""`bidr faaliyet -w WS [--out DOSYA] [--json]`: faaliyet kayıtları → faaliyetler.json + özet tablo."""
from __future__ import annotations

import json
import sys


def _cmd(args) -> int:
    from . import run as R
    try:
        dest, data = R.run(args.workspace, args.out)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=1))
        return 0
    st = data["ozet"]
    print(f"{st['faaliyet']} faaliyet ({st['faaliyetli']} belge) → {dest}; ince karar {st['ince']} belge, "
          f"faaliyetsiz {st['faaliyetsiz']}, alanı olmayan eski kayıt {st['alansiz_eski']}"
          + (f", başka birim {st['baska_birim']}" if st["baska_birim"] else ""))
    if data["faaliyetler"]:
        print(R.table(data))
        print("Aşama: D duyuru, P plan, Z düzenleme, G gerçekleşme, K katılım, DG değerlendirme, "
              "İ iyileştirme, ? diğer")
    if st["yalniz_duyuru"]:
        print(f"UYARI: {st['yalniz_duyuru']} faaliyetin yalnız duyuru/plan belgesi var; "
              f"'düzenlenmiştir' denemez (gerçekleşme kanıtı gerekir).")
    if st["alansiz_eski"]:
        print(f"Not: {st['alansiz_eski']} kayıt classify_fine v8 ve öncesinden (faaliyet alanı yok); "
              f"isteğe bağlı: `bidr decide prepare -w WS --stage fine` özetini görüp `--yes`.")
    return 0


def register(sub):
    p = sub.add_parser("faaliyet", help="aynı toplantı/etkinliğin belgelerini bağla → faaliyetler.json")
    p.add_argument("--workspace", "-w", required=True)
    p.add_argument("--out", help="çıktı dosyası (vars. <ws>/faaliyetler.json)")
    p.add_argument("--json", action="store_true", help="tablo yerine JSON yaz")
    p.set_defaults(func=_cmd)
