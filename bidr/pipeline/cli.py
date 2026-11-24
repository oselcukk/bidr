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


def paralel_satirlari(p: dict) -> list[str]:
    """`bidr next`: model aşamasının paralel bölünmesi (pipeline.yaml `paralel`, `bidr parcala`)."""
    if not p:
        return []
    if not p.get("bolunebilir"):
        return [f"Paralel: bölünmez — tek ajan yapar. Gerekçe: {p.get('gerekce', '')}"]
    n, b = p.get("parca_sayisi") or 0, p.get("bekleyen") or 0
    if n <= 1:
        return [f"Paralel: gerekmez ({b} paket): tek ajan yapar."]
    return [f"Paralel: bu aşama {n} ajanla paralel yapılabilir ({b} cevapsız paket).",
            f"  a. {p['komut']}   # {n} ayrık parça listesi: work/…/_parca/<k>.txt",
            "  b. Her ajana bir parça listesi verin (talimat tek ajanınkiyle aynı: README + paketin `istem`i); her "
            "ajan YALNIZ kendi listesindeki paketlere cevap yazar, başka cevaba dokunmaz, apply çalıştırmaz, "
            "alt ajan açmaz. Alt ajan yoksa parçaları sırayla kendin yap.",
            f"  c. Hepsi bitince: {p['denetim']}   # liste dışı/ezilmiş cevabı reddeder; sonra yukarıdaki apply "
            "(apply da aynı denetimi yapar)"]


def oneri_satirlari(rep) -> list[str]:
    """Hattı tutmayan, bölüm kararı bekleyen öneriler (kör denetimin OD/kanıt önerileri ve kabul edilmiş metne
    öneriler): bilgi olarak."""
    ob = getattr(rep, "oneri_bekleyen", None) or []
    if not ob:
        return []
    out = [f"Bilgi: denetimin {len(ob)} önerisi bölüm kararını bekliyor (hattı tutmaz; rapor tamamlandı sayılır):"]
    out += [f"  - {x['bulgu_id']} ({x.get('oneri_adi') or x['sinif']}): {x.get('ozet', '')}" for x in ob]
    out += [f"  Karar yalnız KULLANICI derse: {bidr_command()} denetim karar -w {rep.calisma_alani} <bulgu_id> "
            "kabul|ret [--not \"…\"]; kabul edilen OD ya da kabul edilmiş metne öneri küçük bir düzeltme turu açar "
            "(bidr next gösterir), kabul edilen belge ikinci aramaya girer; reddedilen metin önerisinde metin aynen "
            "kalır."]
    return out


def _next(args) -> int:
    from .state import evaluate
    rep = evaluate(args.workspace)
    n = rep.sonraki
    if args.json:
        d = rep.to_dict()
        print(json.dumps({"calisma_alani": rep.calisma_alani, "yonetilen": rep.yonetilen,
                          "sonraki": d["sonraki"], "oneri_bekleyen": d["oneri_bekleyen"]}, ensure_ascii=False, indent=1))
        return 0
    print(_head(rep))
    if n is None:
        print("Bütün aşamalar bitti.")
        for satir in oneri_satirlari(rep):
            print(satir)
        return 0
    if n.durum == "yok":
        print(f"Uygulanmış aşamalar bitti. Sıradaki aşama '{n.id}' ({n.ad}) bidr'de henüz yok; "
              "hat burada biter. Kullanıcıya durumu bildir ve dur; bu aşamayı elle uydurma.")
        for satir in oneri_satirlari(rep):
            print(satir)
        return 0
    print(f"Aşama: {n.id} — {n.ad}")
    print(f"Durum: {n.durum}" + (f" ({KIM[n.kim]})" if n.kim else "") + f" — {n.neden}")
    if n.ilerleme:
        print("İlerleme: " + ", ".join(f"{k}={v}" for k, v in n.ilerleme.items()))
    for u in n.uyarilar:
        print(f"Uyarı: {u}")
    if n.karar_bekleyen:
        print("Karar bekleyen:")
        for x in n.karar_bekleyen:
            if x.get("bulgu_id"):               # kör denetimin OD/kanıt önerisi (bidr denetim karar)
                print(f"  - {x['bulgu_id']} ({x['sinif']}): {x.get('ozet', '')}")
                continue
            ek = "" if not x.get("sorunlar") else ": " + "; ".join(
                f"{i.get('yer', '-')} {i['kod']}: {i['ayrinti']}" for i in x["sorunlar"][:5])
            print(f"  - {x['olcut']} (deneme {x.get('deneme')}, "
                  f"{'kabul edilebilir' if x.get('kabul_edilebilir') else 'kabul edilemez'}){ek}")
    if n.komutlar:
        print("Yap:")
        for i, k in enumerate(n.komutlar, 1):
            print(f"  {i}. {k}")
    for satir in paralel_satirlari(n.paralel):
        print(satir)
    for satir in oneri_satirlari(rep):
        print(satir)
    print(f"Tamamlanma şartı (kod denetler): {n.sart}")
    print("İnsan onayı: " + ("GEREKLİ — kullanıcı karar vermeden bu aşama bitmez; dur ve sor."
                             if n.onay == "insan" else "gerekmez"))
    if n.skill:
        print(f"Skill: {n.skill}")
    print(f"Sonra (her adımdan sonra): {bidr_command()} next -w {rep.calisma_alani}")
    return 0


def _next_guncel(args) -> int:
    """`next` + günde en çok bir kez güncellik hatırlatması (bidr/guncel; git klonu değilse hiçbir şey)."""
    rc = _next(args)
    if not args.json:
        from bidr.guncel.core import next_notice
        line = next_notice(args.workspace)
        if line:
            print(line)
    return rc


def register(sub):
    from . import hakem, paralel
    hakem.register(sub)
    paralel.register(sub)
    p = sub.add_parser("status", help="çalışma alanındaki aşamaların durumu (bitti/bekliyor/engelli + neden)")
    p.add_argument("--workspace", "-w", required=True)
    p.add_argument("--json", action="store_true")
    p.add_argument("--kisa", action="store_true", help="üç satırlık özet (oturum başı hook'u için)")
    p.set_defaults(func=_status)
    p = sub.add_parser("next", help="sıradaki tam adım: komut(lar), tamamlanma şartı, insan onayı")
    p.add_argument("--workspace", "-w", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_next_guncel)
