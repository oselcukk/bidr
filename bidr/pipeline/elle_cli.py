"""`bidr elle liste|karar`: elle bakılmalı öğeler (bidr/pipeline/cevap.py) ve bölümün kesin kararı.

  liste  makine okunur liste (`--json`; review.xlsx İnceleme satırları da bundan kurulur): aşama, anahtar, belge, sade
         neden, modelin son cevabının özeti, belgenin şimdiki (OCR) metni, seçenekler, verilmiş karar.
  karar  KULLANICININ kararı (ajan vermez): kabul (modelin son cevabını olduğu gibi uygula; yalnız
         transcribe/describe şüpheli) | varsayilan (taramadaki metinle kal / betimleme yok / karar yok) |
         atla (bu belgeyi bu adımda atla). `work/<aşama>/elle-kararlar.jsonl`'e yazılır; kesindir: belgenin
         içeriği değişmedikçe yeniden doğrulanmaz, yeniden sorulmaz.

Çıkış: 0 tamam · 2 geçersiz argüman/karar."""
from __future__ import annotations

import json


def _cmd(args) -> int:
    from . import cevap as CV
    if args.action == "liste":
        xs = CV.liste(args.workspace)
        if args.json:
            print(json.dumps(xs, ensure_ascii=False, indent=1))
            return 0
        if not xs:
            print("elle bakılmalı öğe yok")
        for x in xs:
            k = x["karar"]
            print(f"{x['asama']} {x['anahtar']} ({x['belge']}): {x['neden_metni']}"
                  + (f" → karar: {k['karar']} ({k.get('kim') or '?'}, {k.get('zaman')})" if k else
                     " → karar bekliyor (varsayılan: " + x["varsayilan"] + ")"))
        return 0
    try:
        r = CV.karar_ver(args.workspace, args.asama, args.anahtar, args.karar, kim=args.kim or "", notu=args.notu or "")
    except ValueError as e:
        print(f"HATA {e}")
        return 2
    print(f"karar kaydedildi: {r['asama']} {r['anahtar']} → {r['karar']}")
    return 0


def register(sub):
    p = sub.add_parser("elle", help="elle bakılmalı model cevapları: liste ve bölümün kesin kararı")
    act = p.add_subparsers(dest="action", required=True)
    a = act.add_parser("liste", help="elle bakılmalı öğeler")
    a.add_argument("--workspace", "-w", required=True)
    a.add_argument("--json", action="store_true")
    a.set_defaults(func=_cmd)
    a = act.add_parser("karar", help="KULLANICININ kararı: kabul | varsayilan | atla")
    a.add_argument("--workspace", "-w", required=True)
    a.add_argument("asama")
    a.add_argument("anahtar")
    a.add_argument("karar")
    a.add_argument("--kim", help="kararı veren (panel kullanıcısı)")
    a.add_argument("--not", dest="notu")
    a.set_defaults(func=_cmd)
