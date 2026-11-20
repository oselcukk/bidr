"""`bidr arama`: ikinci aramanın ince karar paketleri ve sonuçlarının işlenmesi.

Ajan modu, `bidr decide` ile aynı sözleşme: `prepare` paketleri `work/ikinci_arama/<doc_id>.json`
olarak yazar (görev `classify_fine`, aynı istem ve şema; aday listesi yalnız ikinci aramanın
bu belgeye seçtiği ölçütler), ajan `<doc_id>.out.json` yazar, `apply` cevabı aynı kod
denetiminden (`decide.run.check_matches`: aday dışı ölçüt, yuva, birebir alıntı, OD, birim)
geçirip decisions.jsonl'deki kayda EKLER. İlk geçişin eşleşmeleri ve `ince` bölümü değişmez.

İşaret: ikinci aramanın eklediği her eşleşme `ikinci_arama: true` ve `denetim.isaret`te
`ikinci_arama` taşır (review.xlsx "işaretler" sütununda görünür); kayıtta `ikinci_arama`
bölümü hangi ölçütlerin hangi puanla bakıldığını tutar. Ölçüm: `bidr arama olcum`.

İlk geçiş yeniden karara bağlanırsa (`decide apply`) ikinci aramanın eşleşmeleri düşmez:
`decide.run.carry_second_search` onları yeni birim ilişkisiyle yeniden denetleyip kayda ekler ve
`ince_parmak`'ı günceller (aynı ölçüt/yuvayı ilk geçiş kabul ettiyse ikinci aramanınki düşer).
Cevabı zaten kayıtta olan paket, parmak izi eski olsa da işlenmiş sayılır (`merged`).
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

from bidr.common import Workspace
from bidr.criteria.model import id_key

from . import ikinci as I

WORK = "ikinci_arama"
ISARET = "ikinci_arama"
REVIEW = "review-decisions.jsonl"

README = """# bidr ikinci arama paketleri: classify_fine (sürüm {version})

Bu klasördeki her `<doc_id>.json` bir ince karar paketidir; `bidr decide`'ın ince karar
paketleriyle aynı görev ve aynı kurallar. Fark: aday ölçütler kanıtsız ya da zayıf kalmış
ölçütlerdir (ikinci arama): ya ilk geçişte bu belge için aday olmamışlardır ya da belge başka
bir ölçütte kanıt olarak kabul edilmiştir ve aynı belgenin bu ölçüte de kanıt olup olmadığı
sorulur. Belgenin öteki ölçütteki kabulü bu ölçüt için kanıt değildir; yalnız metne bak. Uymuyorsa
"olcut_yok" ya da "kanit_degil" geçerli ve beklenen cevaptır; zorlama.

1. Paketi oku; `istem` görevin tamamı, `sema` cevabın JSON şeması.
2. Cevabı YALNIZ JSON olarak aynı klasörde `<doc_id>.out.json` dosyasına yaz.
3. Bitince: `bidr arama apply -w <çalışma klasörü> --model <ajan/model adı>`.

Bekleyen paket: {n}
"""


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def first_pass_print(rec: dict) -> str:
    """İlk geçişin ince kararının parmak izi (ikinci aramanın eşleşmeleri hariç)."""
    ince = rec.get("ince") or {}
    ms = [[m.get("olcut"), m.get("yuva"), m.get("alinti")] for m in rec.get("eslesmeler") or []
          if not m.get("ikinci_arama")]
    return _sha(json.dumps([rec.get("adaylar") or [], ince.get("istem_sha"), ince.get("cevap_sha"),
                            ince.get("model"), ms], ensure_ascii=False, sort_keys=True))


def done_criteria(rec: dict) -> set[str]:
    """Bu kayıtta ikinci aramayla bakılmış ölçütler (ilk geçiş değişmediyse)."""
    ia = rec.get("ikinci_arama") or {}
    if not ia or ia.get("ince_parmak") != first_pass_print(rec):
        return set()
    n = sum(bool(m.get("ikinci_arama")) for m in rec.get("eslesmeler") or [])
    if n != ia.get("eslesme", 0):
        return set()
    return set((ia.get("olcutler") or {}))


def merged(rec: dict | None, pkg: dict, cevap: str) -> bool:
    """Paketin bu cevabı kayda zaten işlenmiş mi (ilk geçiş sonradan yeniden uygulanmış olsa da)."""
    if not rec:
        return False
    oc = (rec.get("ikinci_arama") or {}).get("olcutler") or {}
    adaylar = (pkg.get("meta") or {}).get("adaylar") or []
    return done_criteria(rec) >= set(adaylar) and all(
        (oc.get(c) or {}).get("cevap_sha") == cevap and (oc.get(c) or {}).get("istem_sha") == pkg.get("istem_sha")
        for c in adaylar)


def eligible_map(ctx, recs: dict[str, dict], weak: set[str], *, redo: bool = False) -> tuple[dict, dict]:
    """({doc_id: ikinci aramaya açık zayıf ölçütler}, sayaçlar)."""
    from bidr.decide.run import BIRIM_DISI, record_unit_relation, unit_view

    st = {"ince_yok": 0, "haric": 0, "baska_birim": 0, "devralan": 0}
    allowed = set(ctx.allowed)
    out: dict[str, set[str]] = {}
    for did in sorted(p.stem for p in ctx.ws.text_dir.glob("*.txt")):
        rec = recs.get(did)
        if not rec or rec.get("durum") != "ok" or rec.get("asama") != "ince":
            st["ince_yok"] += 1
            continue
        if ctx.skip_reason(did):
            st["haric"] += 1
            continue
        if record_unit_relation(unit_view(rec, ctx.pins, ctx.tags)) == BIRIM_DISI:
            st["baska_birim"] += 1
            continue
        if (rec.get("mukerrer") or {}).get("durum") == "devralindi":
            st["devralan"] += 1                 # temsilcisi aranır; aynı metin iki kez paketlenmez
            continue
        skip = I.first_pass_candidates(rec) | (set() if redo else done_criteria(rec))
        ok = {c for c in weak if c in allowed and c not in skip}
        if ok:
            out[did] = ok
    return out, st


def cross_pool(ctx, recs: dict[str, dict], weak: set[str], review: dict[str, dict], *,
               redo: bool = False) -> dict[str, dict]:
    """Çapraz yolun havuzu: {doc_id: {"acik": zayıf ölçütler, "kabul": başka ölçütler}}.
    Belge ince kararı sonuçlanmış, hariç tutulmamış, devralan mükerrer değil, birimin kendi
    belgesi (`ikinci.unit_own`, insan birim kararı öncelikli) ve en az bir ölçütte kabul edilmiş
    (insan reddetmemiş) olmalı. Açık ölçüt: ilk geçişte o belgeyle eşleşmesi olmayan, ikinci
    aramayla bakılmamış (`redo` değilse) zayıf ölçüt; ilk geçişin adayı olmuş olabilir."""
    from bidr.decide.run import unit_view

    allowed = set(ctx.allowed)
    out: dict[str, dict] = {}
    for did in sorted(p.stem for p in ctx.ws.text_dir.glob("*.txt")):
        rec = recs.get(did)
        if not rec or rec.get("durum") != "ok" or rec.get("asama") != "ince" or ctx.skip_reason(did):
            continue
        if (rec.get("mukerrer") or {}).get("durum") == "devralindi":
            continue
        view = unit_view(rec, ctx.pins, ctx.tags)
        if not I.unit_own(view, ctx.docs.get(did)):
            continue
        kabul = I.accepted_elsewhere(rec, view, review)
        if not kabul:
            continue
        skip = I.first_pass_matched(rec) | (set() if redo else done_criteria(rec))
        acik = {c for c in weak if c in allowed and c not in skip}
        if acik:
            out[did] = {"acik": acik, "kabul": kabul}
    return out


def load_review(ws_root: Path) -> dict[str, dict]:
    """review-decisions.jsonl (`bidr audit apply`): {"<doc_id>|<yuva>": karar}; yoksa boş."""
    from bidr.common import read_jsonl
    p = Path(ws_root) / REVIEW
    return {r["satir"]: r for r in read_jsonl(p) if r.get("satir")} if p.exists() else {}


def _write_readme(d: Path) -> int:
    from bidr.decide.run import FINE, _pkg_paths, task_version
    pending = sum(1 for p in _pkg_paths(d) if not (d / f"{p.stem}.out.json").exists())
    (d / "README.md").write_text(README.format(version=task_version(FINE), n=pending), encoding="utf-8")
    return pending


def prepare(ws_root: Path, *, profile: str | None = "akademik_bolum", n: int = I.N_BELGE,
            max_aday: int = 6, od_esik: int = I.OD_ESIK, olcutler: list[str] | None = None,
            synonyms: bool = True, redo: bool = False, capraz: bool = True, backend=None,
            ctx=None) -> dict:
    """Zayıf ölçütleri bulur, arşivde arar, belge başına bir ince karar paketi yazar.
    `olcutler` verilirse zayıflık hesaplanmaz, yalnız bu ölçütler aranır. `capraz`: başka
    ölçütte kabul edilmiş birim belgeleri de zayıf ölçütlere aday olur (çapraz yol)."""
    from bidr.decide.run import FINE, Backend, Context, _write_pkg, fine_inputs, load_decisions, work_dir

    backend = backend or Backend()
    if ctx is None:
        ctx = Context.load(ws_root, profile=profile, max_aday=max_aday)
    recs = load_decisions(ctx.ws)
    audit = I.load_audit(ctx.ws.root / I.AUDIT_JSON)
    if olcutler:
        weak = {c: {"olcut": c, "nedenler": ["elle"], "kaynak": "elle"} for c in olcutler}
    else:
        weak = I.weak_criteria(ctx.allowed, recs, audit=audit, pins=ctx.pins, tags=ctx.tags,
                               docs=ctx.docs, od_esik=od_esik)
    elig, est = eligible_map(ctx, recs, set(weak), redo=redo)
    searcher = I.Searcher(ctx.cs, I.Archive.load(ctx.ws.root), synonyms=synonyms)
    picks = I.select(searcher, weak, elig, n=n)
    by_doc: dict[str, dict[str, dict]] = {}
    for c, rows in picks.items():
        for r in rows:
            by_doc.setdefault(r["doc_id"], {})[c] = {
                "olcut": c, "puan": r["puan"], "sira": r["sira"], "sinyaller": r["sinyaller"],
                "nedenler": weak[c]["nedenler"], "kaynak": ["arsiv"]}
    pool = cross_pool(ctx, recs, set(weak), load_review(ctx.ws.root), redo=redo) if capraz else {}
    cross = I.select_cross(searcher, weak, pool, max_aday=max_aday)
    for did, rows in cross.items():
        slot = by_doc.setdefault(did, {})
        for r in rows:
            row = slot.setdefault(r["olcut"], {
                "olcut": r["olcut"], "puan": r["puan"], "sira": r["sira"], "sinyaller": r["sinyaller"],
                "nedenler": weak[r["olcut"]]["nedenler"], "kaynak": []})
            row["kaynak"].append("capraz")
            row["kabul_olcutler"] = pool[did]["kabul"]
    d = work_dir(ctx.ws, WORK)
    d.mkdir(parents=True, exist_ok=True)
    secim_capraz: dict[str, list[str]] = {}
    for did, rows in cross.items():
        for r in rows:
            secim_capraz.setdefault(r["olcut"], []).append(did)
    st = {"zayif": weak, "audit": audit is not None, "paket": 0, "yeni": 0, "kesilen": 0,
          "secim": {c: [r["doc_id"] for r in rows] for c, rows in picks.items()},
          "secim_capraz": secim_capraz, "capraz_havuz": len(pool), "capraz_paket": len(cross),
          "capraz_cift": sum(len(v) for v in cross.values()), **est}
    for did in sorted(by_doc):
        rows = sorted(by_doc[did].values(), key=lambda r: (-r["puan"], id_key(r["olcut"])))
        st["kesilen"] += max(0, len(rows) - max_aday)
        rows = rows[:max_aday]
        crits = [r["olcut"] for r in rows]
        rec = recs[did]
        sub = dataclasses.replace(ctx, cand={}, max_aday=len(crits))
        inputs, meta = fine_inputs(sub, did, {"kaba": {"secilen": crits},
                                              "belge_bilgisi": rec.get("belge_bilgisi") or {}},
                                   komisyon=False)
        meta["ikinci_arama"] = {"olcutler": rows, "ince_parmak": first_pass_print(rec)}
        st["paket"] += 1
        st["yeni"] += _write_pkg(d, did, FINE, inputs, meta, backend, force=redo)
    st["bekleyen"] = _write_readme(d)
    st["klasor"] = str(d)
    return st


def merge(ctx, did: str, rec: dict, out: dict, pkg: dict, model: str, verify, cevap_sha: str | None = None) -> dict:
    """İkinci aramanın cevabını kayda ekler. Paketteki ölçütlerin önceki ikinci arama
    eşleşmeleri yenisiyle değişir; ilk geçişin eşleşmeleri ve `ince` bölümü değişmez.
    Birim ilişkisi kayıttan (insan kararı öncelikli): ilk geçişte verilmiş karar esastır."""
    from bidr.decide.run import (BIRIM_DISI, check_matches, kurum_geneli, record_unit_relation,
                                 summarize, unit_relation)
    meta = pkg["meta"]
    crits = meta["adaylar"]
    pin = ctx.pin(did)
    rel = pin or (record_unit_relation(rec) if (rec.get("ince") or {}).get("birim_iliskisi")
                  else unit_relation(out)[0])
    kg = kurum_geneli({**out, "birim_iliskisi": rel}, ctx.docs.get(did))
    new = check_matches(out, crits, ctx.cs, ctx.tags, ctx.text(did), verify, kg["karar"], rel)
    for m in new:
        m["ikinci_arama"] = True
        m["denetim"]["isaret"] = [*m["denetim"]["isaret"], ISARET]
    for m in new:
        m["ikinci_arama_paket"] = pkg["istem_sha"]
    # önceki ikinci arama eşleşmelerinden bu paketin ölçütlerine ait olanlar ve aynı paketin
    # önceki cevabından kalanlar (aday dışı dahil) yenisiyle değişir
    cset = set(crits)
    keep = [m for m in rec.get("eslesmeler") or []
            if not (m.get("ikinci_arama") and (m.get("olcut") in cset
                                                or m.get("ikinci_arama_paket") == pkg["istem_sha"]))]
    rec = dict(rec)
    rec["eslesmeler"] = keep + new
    rec["olcutler"] = summarize(rec["eslesmeler"])
    if rec["olcutler"]:
        rec["karar"] = "olcut_var"
    rec["reddedilen_eslesme"] = sum(not m["kabul"] for m in rec["eslesmeler"])
    ia = dict(rec.get("ikinci_arama") or {})
    if ia.get("ince_parmak") != meta["ikinci_arama"]["ince_parmak"]:
        ia = {}                                  # ilk geçiş değişmiş: eski ikinci arama geçersiz
    info = {r["olcut"]: r for r in meta["ikinci_arama"]["olcutler"]}
    oc = dict(ia.get("olcutler") or {})
    for c in crits:
        oc[c] = {"puan": info.get(c, {}).get("puan"), "sira": info.get(c, {}).get("sira"),
                 "nedenler": info.get(c, {}).get("nedenler", []),
                 "kaynak": info.get(c, {}).get("kaynak", ["arsiv"]), "istem_sha": pkg["istem_sha"],
                 "cevap_sha": cevap_sha, "model": model,
                 "eslesme": sum(m["olcut"] == c for m in new),
                 "kabul": sum(m["olcut"] == c and m["kabul"] for m in new)}
    ia.update(olcutler=oc, ince_parmak=meta["ikinci_arama"]["ince_parmak"],
              eslesme=sum(bool(m.get("ikinci_arama")) for m in rec["eslesmeler"]),
              son={"karar": out.get("karar"), "gerekce": out.get("gerekce", ""), "model": model,
                   "birim_iliskisi_model": unit_relation(out)[0], "birim_iliskisi": rel})
    rec["ikinci_arama"] = ia
    if rel == BIRIM_DISI:
        ia["son"]["not"] = "başka birime ait: eşleşmeler reddedildi"
    return rec, new


def apply(ws_root: Path, *, model: str = "ajan:belirtilmemis", backend=None, ctx=None) -> dict:
    """`.out.json` cevaplarını doğrular, ikinci arama eşleşmesi olarak decisions.jsonl'e ekler."""
    from bidr.decide.run import FINE, Backend, Context, _load_pkg, _pkg_paths, load_decisions, \
        save_decisions, task_version, work_dir

    backend = backend or Backend()
    if ctx is None:
        ctx = Context.load(ws_root, profile=None)
    recs = load_decisions(ctx.ws)
    d = work_dir(ctx.ws, WORK)
    st = {"islenen": 0, "degismedi": 0, "bekleyen": [], "gecersiz": {}, "eski_surum": [],
          "eski_paket": [], "eklenen_kabul": 0, "eklenen_red": 0}
    for p in _pkg_paths(d) if d.exists() else []:
        pkg = _load_pkg(p)
        if pkg is None:
            continue
        did = pkg["doc_id"]
        outp = d / pkg["cikti_dosyasi"]
        if not outp.exists():
            st["bekleyen"].append(did)
            continue
        if str(pkg["surum"]) != task_version(FINE):
            st["eski_surum"].append(did)
            continue
        rec = recs.get(did)
        raw = outp.read_text(encoding="utf-8")
        cevap = _sha(raw)
        if rec and rec.get("asama") == "ince" and merged(rec, pkg, cevap):
            st["degismedi"] += 1                # ilk geçiş yeniden uygulandıysa da eşleşmeler kayıtta
            continue
        if not rec or rec.get("asama") != "ince" or \
                first_pass_print(rec) != pkg["meta"]["ikinci_arama"]["ince_parmak"]:
            st["eski_paket"].append(did)        # ilk geçiş değişmiş: `arama prepare` yeniden paketler
            continue
        out, errs = backend.validate_output(FINE, raw)
        if out is None:
            st["gecersiz"][did] = errs[:5]
            continue
        rec, new = merge(ctx, did, rec, out, pkg, model, backend.verify_quote, cevap)
        recs[did] = rec
        for m in new:
            st["eklenen_kabul" if m["kabul"] else "eklenen_red"] += 1
        st["islenen"] += 1
    save_decisions(ctx.ws, recs)
    if d.exists():
        lines = [f"- `{did}.json` — geçersiz cevap: " + "; ".join(e) for did, e in st["gecersiz"].items()]
        g = d / "GECERSIZ.md"
        if lines:
            g.write_text("# Yeniden yapılacak (ikinci arama)\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
        elif g.exists():
            g.unlink()
    return st
