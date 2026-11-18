"""`bidr status -w WS` ve `bidr next -w WS`: aşama durumu ve sıradaki tam adım."""
from __future__ import annotations

import json

from .state import bidr_command

MARK = {"bitti": "[x]", "bekliyor": "[>]", "engelli": "[ ]", "atlandi": "[-]", "yok": "[.]"}
KIM = {"komut": "komutu çalıştır", "ajan": "model işi: ajan yapar", "insan": "KULLANICI gerekli"}


def _head(rep) -> str:
    from bidr.init.config import load_section
    sec = load_section(rep.calisma_alani) or {}
    tag = f" ({sec['birim']} · {sec['donem']} · {sec['profil']})" if sec else " (kurulmamış)"
    return f"bidr durum: {rep.calisma_alani}{tag}"


def _status(args) -> int:
    from .state import evaluate
    rep = evaluate(args.workspace)
    if args.json:
        print(json.dumps(rep.to_dict(), ensure_ascii=False, indent=1))
        return 0
    n = rep.sonraki
    if args.kisa:
        done = sum(s.durum in ("bitti", "atlandi") for s in rep.asamalar)
        print(_head(rep))
        print(f"aşama: {done}/{len(rep.asamalar)} tamam; sıradaki: "
              + (f"{n.id} ({n.durum}{', ' + KIM[n.kim] if n.kim else ''}) — {n.neden}" if n else "yok"))
        print(f"Ayrıntı ve tam komut: {bidr_command()} next -w {rep.calisma_alani}")
        return 0
    print(_head(rep))
    w = max(len(s.id) for s in rep.asamalar)
    for s in rep.asamalar:
        extra = f" [{s.kim}]" if s.kim else ""
        print(f"  {MARK[s.durum]} {s.id:<{w}}  {s.durum:<8}{extra}  {s.neden}")
        for u in s.uyarilar:
            print(f"      uyarı: {u}")
    print(f"Sıradaki adım: {bidr_command()} next -w {rep.calisma_alani}")
    return 0


def _next(args) -> int:
    from .state import evaluate
    rep = evaluate(args.workspace)
    n = rep.sonraki
    if args.json:
        print(json.dumps({"calisma_alani": rep.calisma_alani, "yonetilen": rep.yonetilen,
                          "sonraki": rep.to_dict()["sonraki"]}, ensure_ascii=False, indent=1))
        return 0
    print(_head(rep))
    if n is None:
        print("Bütün aşamalar bitti.")
        return 0
    if n.durum == "yok":
        print(f"Uygulanmış aşamalar bitti. Sıradaki aşama '{n.id}' ({n.ad}) bidr'de henüz yok; "
              "hat burada biter. Kullanıcıya durumu bildir ve dur; bu aşamayı elle uydurma.")
        return 0
    print(f"Aşama: {n.id} — {n.ad}")
    print(f"Durum: {n.durum}" + (f" ({KIM[n.kim]})" if n.kim else "") + f" — {n.neden}")
    if n.ilerleme:
        print("İlerleme: " + ", ".join(f"{k}={v}" for k, v in n.ilerleme.items()))
    for u in n.uyarilar:
        print(f"Uyarı: {u}")
    if n.komutlar:
        print("Yap:")
        for i, k in enumerate(n.komutlar, 1):
            print(f"  {i}. {k}")
    print(f"Tamamlanma şartı (kod denetler): {n.sart}")
    print("İnsan onayı: " + ("GEREKLİ — kullanıcı karar vermeden bu aşama bitmez; dur ve sor."
                             if n.onay == "insan" else "gerekmez"))
    if n.skill:
        print(f"Skill: {n.skill}")
    print(f"Sonra (her adımdan sonra): {bidr_command()} next -w {rep.calisma_alani}")
    return 0


def register(sub):
    from . import hakem
    hakem.register(sub)
    p = sub.add_parser("status", help="çalışma alanındaki aşamaların durumu (bitti/bekliyor/engelli + neden)")
    p.add_argument("--workspace", "-w", required=True)
    p.add_argument("--json", action="store_true")
    p.add_argument("--kisa", action="store_true", help="üç satırlık özet (oturum başı hook'u için)")
    p.set_defaults(func=_status)
    p = sub.add_parser("next", help="sıradaki tam adım: komut(lar), tamamlanma şartı, insan onayı")
    p.add_argument("--workspace", "-w", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_next)
