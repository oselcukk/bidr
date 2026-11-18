"""`bidr compare-labels`: model kararı ↔ geçmiş insan etiketi; hakem kuyruğu; uzlaşı.

Girdi: `decisions.jsonl`, `labels.jsonl`, (varsa) `documents.jsonl`.
Çıktı:
  label-compare.md      özet: alt ve ana ölçüt düzeyinde aynı / model ekliyor / model itiraz
  label-review.jsonl    hakem soruları (5'erli gruplar)
  label-review.md       aynı sorular okunur biçimde; her sorunun altında `- Karar:` satırı
  label-answers.jsonl   hakem cevapları (elle ya da `label-review.md`'den toplanır)
  consensus-labels.jsonl  `--apply` ile: labels.jsonl biçiminde uzlaşı etiketleri

Soru türleri ve seçenekleri:
  ekliyor   model geçmişte olmayan bir alt ölçüt öneriyor   → ekle | reddet | belirsiz
  itiraz    geçmiş alt ölçütü model doğrulamadı            → koru | kaldir | belirsiz
  od_farki  aynı alt ölçüt, OD farklı                      → od_model | od_gecmis | od=N | belirsiz

Hakem cevabı biçimi (`label-answers.jsonl`, satır başına bir):
  {"soru_id": "<doc_id>:<olcut>:<tur>", "karar": "ekle", "od": 3, "not": "..."}
`od` yalnız `ekle` için isteğe bağlıdır (verilmezse model OD'si).

`consensus-labels.jsonl` her etiketli belge için bir satır; alanlar labels.jsonl ile
uyumludur (`doc_id`, `birimler`, `etiketli`, `etiketler[].olcut/duzey/od`), böylece
değerlendirme `labels.jsonl` yerine bunu okuyabilir. Ek alanlar: `kaynak: uzlasi`,
`tamam` (açık soru yoksa true), `acik_sorular`, etiket başına `karar_kaynagi`
(gecmis | hakem | model_aynı). `iz` taşınmaz.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from bidr.common import Workspace, read_jsonl, write_jsonl
from bidr.criteria.loader import load_criteria
from bidr.criteria.model import id_key

ALT, ANA = "alt_olcut", "ana_olcut"
GROUP = 5
EKLIYOR, ITIRAZ, OD_FARKI = "ekliyor", "itiraz", "od_farki"
OPTIONS = {
    EKLIYOR: ["ekle", "reddet", "belirsiz"],
    ITIRAZ: ["koru", "kaldir", "belirsiz"],
    OD_FARKI: ["od_model", "od_gecmis", "od=N", "belirsiz"],
}
OPTION_HELP = {
    "ekle": "model haklı, ölçüt eklenir", "reddet": "eklenmez",
    "koru": "geçmiş etiket doğru, kalır", "kaldir": "geçmiş etiket yanlış, çıkar",
    "od_model": "model OD'si", "od_gecmis": "geçmiş OD", "od=N": "başka OD (ör. od=3)",
    "belirsiz": "karar verilemedi, açık kalır",
}
FILES = {"compare": "label-compare.md", "review_jsonl": "label-review.jsonl",
         "review_md": "label-review.md", "answers": "label-answers.jsonl",
         "consensus": "consensus-labels.jsonl"}


def _od_int(x) -> int | None:
    if isinstance(x, int):
        return x
    m = re.search(r"(\d)", str(x or ""))
    return int(m.group(1)) if m else None


def history(label: dict) -> dict:
    alt, ana = {}, set()
    for e in label.get("etiketler") or []:
        o = e.get("olcut")
        if not o:
            continue
        if e.get("duzey") == ALT:
            alt[o] = sorted({v for v in (_od_int(x) for x in e.get("od") or []) if v})
        elif e.get("duzey") == ANA:
            ana.add(o)
    return {"alt": alt, "ana": ana | {o.rsplit(".", 1)[0] for o in alt}}


def _short(doc: dict | None, text_head: str = "") -> str:
    parts = []
    if doc:
        if doc.get("doc_type_etiket") and doc.get("doc_type") != "bilinmeyen":
            parts.append(doc["doc_type_etiket"])
        if doc.get("baslik"):
            parts.append(f"“{doc['baslik']}”")
        if doc.get("tarih"):
            parts.append(doc["tarih"])
        m = doc.get("metin") or {}
        if m.get("sayfa"):
            parts.append(f"{m['sayfa']} s.")
    if not parts and text_head:
        parts.append("“" + " ".join(text_head.split())[:120] + "…”")
    return ", ".join(parts) or "(tanım yok)"


def compare_doc(dec: dict, label: dict) -> dict:
    h = history(label)
    acc = {m["olcut"]: m for m in dec.get("olcutler") or []}
    best = {}  # olcut → en yüksek OD'li kabul edilmiş eşleşme
    rejected: dict[str, list] = {}
    for m in dec.get("eslesmeler") or []:
        if m.get("kabul"):
            b = best.get(m["olcut"])
            if b is None or (m.get("od_kabul") or 0) > (b.get("od_kabul") or 0):
                best[m["olcut"]] = m
        else:
            rejected.setdefault(m.get("olcut"), []).append(m)
    galt, malt = set(h["alt"]), set(acc)
    gana = h["ana"]
    mana = {o.rsplit(".", 1)[0] for o in malt}
    return {
        "doc_id": dec["doc_id"],
        "model_karar": dec.get("karar"),
        "alt": {"ayni": sorted(galt & malt, key=id_key), "ekliyor": sorted(malt - galt, key=id_key),
                "itiraz": sorted(galt - malt, key=id_key)},
        "ana": {"ayni": sorted(gana & mana, key=id_key), "ekliyor": sorted(mana - gana, key=id_key),
                "itiraz": sorted(gana - mana, key=id_key)},
        "gecmis": h, "model": acc, "en_iyi": best, "reddedilen": rejected,
        "adaylar": dec.get("adaylar") or [],
    }


def _model_view(m: dict | None, cs) -> dict | None:
    if not m:
        return None
    try:
        yuva_metin = cs.get_slot(m["yuva"]).text
    except KeyError:
        yuva_metin = None
    return {"olcut": m["olcut"], "yuva": m["yuva"], "yuva_metni": yuva_metin, "asama": m.get("asama"),
            "od": m.get("od_kabul"), "alinti": m.get("alinti"), "gerekce": m.get("gerekce"),
            "guven": m.get("guven"), "isaret": (m.get("denetim") or {}).get("isaret", [])}


def _title(cs, o: str) -> str:
    try:
        return cs.get(o).title
    except KeyError:
        return "(bilinmeyen ölçüt)"


def questions(c: dict, cs, short: str, dosya: str | None) -> list[dict]:
    qs = []
    did = c["doc_id"]
    galt = c["gecmis"]["alt"]
    gecmis = {"alt": {o: [f"OD{x}" for x in v] for o, v in sorted(galt.items(), key=lambda t: id_key(t[0]))},
              "ana": sorted(c["gecmis"]["ana"], key=id_key)}
    base = {"doc_id": did, "belge": short, "dosya": dosya, "gecmis": gecmis,
            "model_karar": c["model_karar"]}
    for o in c["alt"]["ekliyor"]:
        qs.append({**base, "soru_id": f"{did}:{o}:{EKLIYOR}", "tur": EKLIYOR, "olcut": o,
                   "olcut_baslik": cs.get(o).title,
                   "ana_duzeyde_ayni": o.rsplit(".", 1)[0] in c["gecmis"]["ana"],
                   "model": _model_view(c["en_iyi"].get(o), cs), "secenekler": OPTIONS[EKLIYOR]})
    for o in c["alt"]["itiraz"]:
        rej = c["reddedilen"].get(o) or []
        qs.append({**base, "soru_id": f"{did}:{o}:{ITIRAZ}", "tur": ITIRAZ, "olcut": o,
                   "olcut_baslik": _title(cs, o),
                   "aday_miydi": o in c["adaylar"],
                   "model": None,
                   "model_reddedilen": [{"yuva": m.get("yuva"), "alinti": m.get("alinti"),
                                         "red": (m.get("denetim") or {}).get("red")} for m in rej],
                   "secenekler": OPTIONS[ITIRAZ]})
    for o in c["alt"]["ayni"]:
        g = galt.get(o) or []
        mv = _model_view(c["en_iyi"].get(o), cs)
        if g and mv and mv["od"] and mv["od"] not in g:
            qs.append({**base, "soru_id": f"{did}:{o}:{OD_FARKI}", "tur": OD_FARKI, "olcut": o,
                       "olcut_baslik": cs.get(o).title, "model": mv,
                       "od_yonu": "model_dusuk" if mv["od"] < min(g) else "model_yuksek",
                       "secenekler": OPTIONS[OD_FARKI]})
    return qs


# -- md ---------------------------------------------------------------------------

def _q_md(i: int, q: dict) -> str:
    g = q["gecmis"]
    galt = ", ".join(f"{o} ({'/'.join(v) or 'OD yok'})" for o, v in g["alt"].items()) or "yok"
    lines = [f"### S{i} · {q['soru_id']}",
             f"- Belge: {q['belge']} — `{q['doc_id']}`" + (f" — dosya: `{q['dosya']}`" if q.get("dosya") else ""),
             f"- Geçmiş etiket (alt): {galt}; ana: {', '.join(g['ana']) or 'yok'}"]
    o = f"{q['olcut']} {q['olcut_baslik']}"
    if q["tur"] == EKLIYOR:
        lines.append(f"- Soru: Model **{o}** ekliyor"
                     + (" (ana ölçüt geçmişte var)." if q.get("ana_duzeyde_ayni") else "."))
    elif q["tur"] == ITIRAZ:
        why = {"kanit_degil": "model belgeyi kanıt saymadı",
               "olcut_yok": "model hiçbir ölçüte uydurmadı"}.get(q["model_karar"], "model bu ölçütü önermedi")
        if not q.get("aday_miydi"):
            why += "; ölçüt modelin aday listesinde değildi"
        lines.append(f"- Soru: Geçmiş etiket **{o}**; {why}.")
        for r in q.get("model_reddedilen") or []:
            lines.append(f"  - Modelin reddedilen önerisi ({', '.join(r['red'] or [])}): {r['yuva']} “{r['alinti']}”")
    else:
        lines.append(f"- Soru: **{o}** iki tarafta da var; OD farklı "
                     f"({'model daha düşük' if q['od_yonu'] == 'model_dusuk' else 'model daha yüksek'}).")
    m = q.get("model")
    if m:
        lines.append(f"- Model önerisi: yuva {m['yuva']} “{m['yuva_metni']}”; aşama {m['asama']} → OD{m['od']}; "
                     f"güven {m['guven']}" + (f"; işaret: {', '.join(m['isaret'])}" if m["isaret"] else ""))
        lines.append(f"- Alıntı: > {m['alinti']}")
        lines.append(f"- Gerekçe: {m['gerekce']}")
    lines.append("- Seçenekler: " + " · ".join(f"`{s}` {OPTION_HELP[s]}" for s in q["secenekler"]))
    lines.append("- Karar: ")
    return "\n".join(lines)


def review_md(qs: list[dict]) -> str:
    out = ["# Hakem kuyruğu: model ↔ geçmiş etiket", "",
           "Her sorunun `Karar:` satırına seçenek kodunu yazın (ör. `ekle`, `od=3`). İsteğe bağlı not: `- Not: ...`. Sonra "
           "`bidr compare-labels -w WS --apply` uzlaşı etiketlerini yazar. "
           "Bu dosya yeniden üretilirken doldurulmuş kararlar önce `label-answers.jsonl`'e alınır.", ""]
    for gi in range(0, len(qs), GROUP):
        out.append(f"## Grup {gi // GROUP + 1}")
        out.append("")
        for i, q in enumerate(qs[gi:gi + GROUP], gi + 1):
            out.append(_q_md(i, q))
            out.append("")
    return "\n".join(out)


_HDR = re.compile(r"^###\s+S\d+\s+·\s+(\S+)")
_KARAR = re.compile(r"^-\s*Karar:\s*`?([^`\s]*)`?\s*$")
_NOT = re.compile(r"^-\s*Not:\s*(.*)$")


def parse_review_md(text: str) -> list[dict]:
    """Doldurulmuş `label-review.md`'den cevaplar."""
    out, cur = [], None
    for line in text.splitlines():
        m = _HDR.match(line)
        if m:
            cur = {"soru_id": m.group(1)}
            continue
        if cur is None:
            continue
        m = _KARAR.match(line.strip())
        if m and m.group(1):
            cur["karar"] = m.group(1).strip()
            out.append(cur)
            continue
        m = _NOT.match(line.strip())
        if m and out and out[-1] is cur:
            cur["not"] = m.group(1).strip()
    return out


def parse_answer(tur: str, karar: str) -> tuple[str, int | None] | None:
    """(kod, od) ya da geçersizse None."""
    k = (karar or "").strip().lower()
    m = re.fullmatch(r"od\s*=?\s*(?:od)?([1-5])", k)
    if tur == OD_FARKI and m:
        return "od=N", int(m.group(1))
    return (k, None) if k in OPTIONS[tur] else None


def load_answers(ws: Workspace) -> dict[str, dict]:
    p = ws.root / FILES["answers"]
    return {r["soru_id"]: r for r in read_jsonl(p) if r.get("soru_id")} if p.exists() else {}


def harvest_md(ws: Workspace) -> int:
    """label-review.md'deki doldurulmuş kararları label-answers.jsonl'e ekler (md yeni
    kararı jsonl'dekinin üstüne yazar). Eklenen/güncellenen sayısı."""
    p = ws.root / FILES["review_md"]
    if not p.exists():
        return 0
    got = parse_review_md(p.read_text(encoding="utf-8"))
    if not got:
        return 0
    ans = load_answers(ws)
    n = 0
    for a in got:
        old = ans.get(a["soru_id"])
        if old is None or old.get("karar") != a["karar"] or old.get("not") != a.get("not"):
            ans[a["soru_id"]] = {**(old or {}), **a, "kaynak": "label-review.md"}
            n += 1
    write_jsonl(ws.root / FILES["answers"], ans.values())
    return n


# -- ana akış -----------------------------------------------------------------------

def _load(ws: Workspace, decisions: str):
    decs = {r["doc_id"]: r for r in read_jsonl(ws.root / decisions)}
    labels = {r["doc_id"]: r for r in read_jsonl(ws.labels) if r.get("doc_id")} if ws.labels.exists() else {}
    docs = {r["doc_id"]: r for r in read_jsonl(ws.documents) if r.get("doc_id")} if ws.documents.exists() else {}
    return decs, labels, docs


def build(ws_root: Path, *, decisions: str = "decisions.jsonl", criteria=None) -> dict:
    ws = Workspace(ws_root)
    cs = criteria or load_criteria()
    decs, labels, docs = _load(ws, decisions)
    comps, qs, skipped = [], [], []
    for did, lab in sorted(labels.items()):
        if not lab.get("etiketli"):
            continue
        dec = decs.get(did)
        if not dec or dec.get("durum") != "ok":
            skipped.append({"doc_id": did, "neden": (dec or {}).get("neden") or (dec or {}).get("durum")
                            or "karar_yok"})
            continue
        c = compare_doc(dec, lab)
        comps.append(c)
        head = ws.text_path(did).read_text(encoding="utf-8", errors="replace")[:400] \
            if ws.text_path(did).exists() else ""
        yollar = (lab.get("iz") or {}).get("yollar") or []   # yalnız insan hakem için
        qs.extend(questions(c, cs, _short(docs.get(did), head), yollar[0].get("yol") if yollar else None))
    for i, q in enumerate(qs):
        q["grup"] = i // GROUP + 1
        q["sira"] = i + 1
    return {"karsilastirma": comps, "sorular": qs, "atlanan": skipped}


def compare_md(res: dict, cs) -> str:
    comps = res["karsilastirma"]
    def tot(level, key):
        return sum(len(c[level][key]) for c in comps)
    out = ["# Model ↔ geçmiş etiket karşılaştırması", "",
           f"Karşılaştırılan etiketli belge: {len(comps)}; karar olmadığı için atlanan: {len(res['atlanan'])}.", ""]
    for level, name in (("alt", "Alt ölçüt"), ("ana", "Ana ölçüt")):
        out.append(f"## {name} düzeyi")
        out.append(f"- aynı: {tot(level, 'ayni')}, model ekliyor: {tot(level, 'ekliyor')}, "
                   f"model itiraz ediyor: {tot(level, 'itiraz')}")
        tam = sum(1 for c in comps if not c[level]["ekliyor"] and not c[level]["itiraz"])
        out.append(f"- tam uyuşan belge: {tam}/{len(comps)}")
        out.append("")
    # ana ölçüt başına
    per: dict[str, dict] = {}
    for c in comps:
        for key in ("ayni", "ekliyor", "itiraz"):
            for o in c["alt"][key]:
                d = per.setdefault(o.rsplit(".", 1)[0], {"ayni": 0, "ekliyor": 0, "itiraz": 0})
                d[key] += 1
    out.append("## Ana ölçüt başına (alt ölçüt eşleşmeleri)")
    out.append("")
    out.append("| ana ölçüt | aynı | ekliyor | itiraz |")
    out.append("|---|---|---|---|")
    for a in sorted(per, key=id_key):
        d = per[a]
        out.append(f"| {a} {cs.get(a).title} | {d['ayni']} | {d['ekliyor']} | {d['itiraz']} |")
    out.append("")
    nk = sum(1 for c in comps if c["model_karar"] == "kanit_degil")
    od = [q for q in res["sorular"] if q["tur"] == OD_FARKI]
    out.append(f"Model 'kanıt değil' dediği etiketli belge: {nk}. OD farkı: {len(od)} "
               f"(model düşük: {sum(q['od_yonu'] == 'model_dusuk' for q in od)}, "
               f"model yüksek: {sum(q['od_yonu'] == 'model_yuksek' for q in od)}).")
    out.append("")
    out.append("## Belge başına")
    for c in comps:
        a = c["alt"]
        out.append(f"- `{c['doc_id']}` ({c['model_karar']}): aynı {', '.join(a['ayni']) or '-'}; "
                   f"ekliyor {', '.join(a['ekliyor']) or '-'}; itiraz {', '.join(a['itiraz']) or '-'}")
    if res["atlanan"]:
        out.append("")
        out.append("## Atlanan")
        out.extend(f"- `{s['doc_id']}`: {s['neden']}" for s in res["atlanan"])
    out.append("")
    out.append(f"Hakem kuyruğu: {len(res['sorular'])} soru → `{FILES['review_md']}`.")
    return "\n".join(out) + "\n"


def run(ws_root: Path, *, decisions: str = "decisions.jsonl") -> tuple[dict, dict]:
    ws = Workspace(ws_root)
    harvested = harvest_md(ws)
    cs = load_criteria()
    res = build(ws.root, decisions=decisions, criteria=cs)
    (ws.root / FILES["compare"]).write_text(compare_md(res, cs), encoding="utf-8")
    write_jsonl(ws.root / FILES["review_jsonl"], res["sorular"])
    (ws.root / FILES["review_md"]).write_text(review_md(res["sorular"]), encoding="utf-8")
    stats = {"belge": len(res["karsilastirma"]), "soru": len(res["sorular"]),
             "atlanan": len(res["atlanan"]), "toplanan_cevap": harvested,
             "tur": {t: sum(q["tur"] == t for q in res["sorular"]) for t in OPTIONS}}
    return res, stats


def consensus(ws_root: Path) -> tuple[Path, dict]:
    """Geçmiş etiket + hakem cevapları → consensus-labels.jsonl (labels.jsonl biçimi)."""
    ws = Workspace(ws_root)
    harvest_md(ws)
    qs = list(read_jsonl(ws.root / FILES["review_jsonl"]))
    ans = load_answers(ws)
    labels = {r["doc_id"]: r for r in read_jsonl(ws.labels) if r.get("doc_id")}
    by_doc: dict[str, list] = {}
    for q in qs:
        by_doc.setdefault(q["doc_id"], []).append(q)
    rows, stats = [], {"belge": 0, "tamam": 0, "acik_soru": 0, "gecersiz_cevap": [],
                       "eklenen": 0, "kaldirilan": 0, "od_degisen": 0}
    for did, lab in sorted(labels.items()):
        if not lab.get("etiketli") and did not in by_doc:
            continue
        alt: dict[str, dict] = {}
        others = []
        for e in lab.get("etiketler") or []:
            if e.get("duzey") == ALT:
                alt[e["olcut"]] = {"olcut": e["olcut"], "duzey": ALT, "od": list(e.get("od") or []),
                                   "karar_kaynagi": "gecmis"}
            else:
                others.append({"olcut": e["olcut"], "duzey": e.get("duzey"), "od": list(e.get("od") or []),
                               "karar_kaynagi": "gecmis"})
        acik = []
        for q in by_doc.get(did, []):
            a = ans.get(q["soru_id"])
            parsed = parse_answer(q["tur"], a.get("karar")) if a else None
            if a and parsed is None:
                stats["gecersiz_cevap"].append(q["soru_id"])
            if parsed is None or parsed[0] == "belirsiz":
                acik.append(q["soru_id"])
                continue
            kod, n = parsed
            o = q["olcut"]
            mod = (q.get("model") or {}).get("od")
            if q["tur"] == EKLIYOR and kod == "ekle":
                od = _od_int(a.get("od")) or mod
                alt[o] = {"olcut": o, "duzey": ALT, "od": [f"OD{od}"] if od else [], "karar_kaynagi": "hakem"}
                stats["eklenen"] += 1
            elif q["tur"] == ITIRAZ and kod == "kaldir":
                alt.pop(o, None)
                stats["kaldirilan"] += 1
            elif q["tur"] == ITIRAZ and kod == "koru" and o in alt:
                alt[o]["karar_kaynagi"] = "hakem"
            elif q["tur"] == OD_FARKI and o in alt:
                if kod == "od_model" and mod:
                    alt[o].update(od=[f"OD{mod}"], karar_kaynagi="hakem")
                    stats["od_degisen"] += 1
                elif kod == "od=N":
                    alt[o].update(od=[f"OD{n}"], karar_kaynagi="hakem")
                    stats["od_degisen"] += 1
                else:
                    alt[o]["karar_kaynagi"] = "hakem"
        ets = sorted(alt.values(), key=lambda e: id_key(e["olcut"])) + others
        rows.append({"doc_id": did, "kayit": lab.get("kayit"), "birimler": lab.get("birimler") or [],
                     "etiketli": any(e["duzey"] == ALT for e in ets) or bool(others),
                     "etiketler": ets, "kaynak": "uzlasi", "tamam": not acik, "acik_sorular": acik,
                     "kullanim": "degerlendirme_etiketi"})
        stats["belge"] += 1
        stats["tamam"] += not acik
        stats["acik_soru"] += len(acik)
    out = ws.root / FILES["consensus"]
    write_jsonl(out, rows)
    return out, stats
