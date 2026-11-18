"""gaps.md: ölçüt ve yuva düzeyinde eksik kanıt raporu."""
from __future__ import annotations

from .rules import KISA, LINKS

GRUP = {1: "kanıt var ama uygulama/plan halkası eksik (OD ≤ 2)", 2: "hiç kanıt yok (OD1)",
        3: "OD3: izleme ve/veya iyileştirme kanıtı eksik", 4: "OD4: özgün uygulama kanıtı eksik",
        9: "OD5"}


def _eksik_lines(c: dict) -> list[str]:
    out = []
    for e in c["eksik"]:
        line = f"- **OD{c['sonraki_od']} için {e['halka']} ({KISA[e['halka']]})**: {e['gereken']}."
        if e["yuvasiz"]:
            line += " Şablonda bu halkaya ait yuva yok; ölçüt açıklamasına uygun belge gerekir."
        out.append(line)
        for y in e["yuvalar"][:4]:
            out.append(f"  - `{y['yuva']}` {y['metin']}")
    return out


def top_gaps(a, n: int = 10) -> list[dict]:
    from .run import priority_key
    return sorted((c for c in a.criteria if c["oncelik_grubu"] != 9), key=priority_key)[:n]


def gap_line(c: dict) -> str:
    halkalar = ", ".join(e["halka"] for e in c["eksik"]) or "—"
    extra = " (yalnız kurum geneli düzenleme)" if c["kurum_geneli_yalniz"] else ""
    return (f"{c['olcut']} {c['baslik']}: OD{c['od']}{extra}; OD{c['sonraki_od']} için eksik: {halkalar}; "
            f"boş yuva {c['yuva_toplam'] - c['yuva_dolu']}/{c['yuva_toplam']}")


def gaps_md(a) -> str:
    from .run import od_distribution
    L = [f"# Eksik kanıt raporu", "",
         f"Çalışma alanı: `{a.ws.root.name}` · profil: {a.profile} · kabul edilmiş eşleşme: "
         f"{len(a.rows)} (sayılan {sum(r['sayilir'] for r in a.rows)})", "",
         "Önerilen OD ölçütün PUKÖ zincirinden hesaplanır (belge OD'si değil): P→2, +U→3, "
         "+K **ve** Ö→4, +Z→5; zincir eksikse düşük düzey. Düşük güvenli eşleşme önerilen OD'ye katılmaz. "
         "Kurallar: `docs/AUDIT.md`.", ""]
    for u in a.uyarilar:
        L.append(f"> Uyarı: {u}")
    dist = od_distribution(a)
    L += ["## OD dağılımı", "", "| OD | ölçüt |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in dist.items()]
    L += ["", "## Öncelikli eksikler", ""]
    for i, c in enumerate(top_gaps(a), 1):
        L.append(f"{i}. {gap_line(c)}")
    kg = [c for c in a.criteria if c["kurum_geneli_yalniz"]]
    if kg:
        L += ["", "## Kurum geneli belgeyle eşleşen, uygulama kanıtı eksik ölçütler", ""]
        for c in kg:
            docs = sorted({r["belge"] for r in a.rows if r["olcut"] == c["olcut"] and "kurum_geneli" in r["flags"]})
            L.append(f"- {c['olcut']} {c['baslik']}: " + "; ".join(f"`{d}`" for d in docs[:4]))
    L += ["", "## Ölçüt ölçüt", ""]
    for c in a.criteria:
        z = " ".join(f"{KISA[x]}:{c['zincir'][x]['durum']}" for x in LINKS)
        L.append(f"### {c['olcut']} {c['baslik']} — önerilen OD{c['od']}"
                 + (f" (düşük güven dahil OD{c['od_dusuk_dahil']})" if c["od_dusuk_dahil"] != c["od"] else ""))
        L.append("")
        L.append(f"Zincir: {z} · eşleşme {c['eslesme']} · belge {c['belge']} · "
                 f"dolu yuva {c['yuva_dolu']}/{c['yuva_toplam']}")
        for n in c["notlar"]:
            L.append(f"- Not: {n}")
        if c["sonraki_od"]:
            L += _eksik_lines(c)
        if c["bos_yuvalar"]:
            L.append("- Boş yuvalar:")
            for y in c["bos_yuvalar"]:
                L.append(f"  - `{y['yuva']}` [{y['etiket']}] {y['metin']}")
        L.append("")
    return "\n".join(L).rstrip() + "\n"
