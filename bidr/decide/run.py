"""`bidr decide`: iki adımlı model kararı → decisions.jsonl.

Akış (belge başına):
  1. Öz-referans tür (`haric_turler.yaml`) ya da metinsiz belge → atlanır (kayda geçer).
  2. classify_coarse: profile göre süzülmüş alt ölçütler → en çok 5 ölçüt.
  3. Aday birleşimi: kaba seçim ∪ candidates.jsonl ilk k (profil içinde), en çok `max_aday`.
  4. classify_fine: aday rubrik + yuvalar → eşleşmeler.
  5. Kod denetimi: aday dışı ölçüt, geçersiz yuva, tutmayan/çok kısa alıntı → eşleşme
     REDDEDİLİR (kayıtta kalır, `kabul: false`). Aşama yuva etiketine uymuyorsa ya da
     OD aşamayla tutarsızsa OD düşük olana çekilir (`od_kabul`), işaretlenir.

Modele yalnız belge metni ve `documents.jsonl` içerik alanları gider (bkz. prompt.py).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml

from bidr.common import Workspace, read_jsonl
from bidr.criteria.loader import load_criteria
from bidr.criteria.model import CriteriaSet
from bidr.criteria.profiles import excluded_types, load_profile
from bidr.criteria.slots import STAGE_OD, load_tags

from . import prompt as P

TASKS_DIR = Path(__file__).resolve().parents[1] / "tasks"
COARSE, FINE = "classify_coarse", "classify_fine"
MAX_COARSE = 5
MIN_QUOTE = 20           # bundan kısa alıntı kanıt sayılmaz (ör. yalnız başlık sözcüğü)
DECISIONS = "decisions.jsonl"
SCHEMA = 1


@dataclass
class Backend:
    """`bidr.llm` arayüzü (docs/MODEL_LAYER.md). Testler sahtesini verir."""
    run_task: Callable
    load_model_config: Callable
    verify_quote: Callable

    @classmethod
    def default(cls) -> "Backend":
        import bidr.llm as llm
        return cls(llm.run_task, llm.load_model_config, llm.verify_quote)


def task_version(name: str) -> str:
    raw = yaml.safe_load((TASKS_DIR / name / "task.yaml").read_text(encoding="utf-8"))
    return str(raw["version"])


def _documents(ws: Workspace) -> dict[str, dict]:
    if not ws.documents.exists():
        return {}
    return {r["doc_id"]: r for r in read_jsonl(ws.documents) if r.get("doc_id")}


def _candidates(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    return {r["doc_id"]: r for r in read_jsonl(path) if r.get("doc_id")}


def _labeled_ids(ws: Workspace) -> set[str]:
    """Yalnız `--only-labeled` süzgeci için: hangi doc_id etiketli. Başka alan okunmaz."""
    if not ws.labels.exists():
        return set()
    return {r["doc_id"] for r in read_jsonl(ws.labels) if r.get("doc_id") and r.get("etiketli")}


def _model_id(res, cfg) -> str:
    m = getattr(res, "model", None)
    return str(m) if m else str(getattr(cfg, "id", cfg))


def merge_candidates(coarse: list[str], cand_row: dict | None, allowed: set[str], k: int,
                     max_aday: int) -> tuple[list[str], list[str], list[str]]:
    """(adaylar, belirleyici ilk k, kesilenler). Kaba seçim önde, sonra belirleyici sıra."""
    det = [c["olcut"] for c in (cand_row or {}).get("adaylar", [])
           if c.get("olcut") in allowed][:k]
    order: list[str] = []
    for x in [*coarse, *det]:
        if x not in order:
            order.append(x)
    return order[:max_aday], det, order[max_aday:]


def check_matches(out: dict, cands: list[str], cs: CriteriaSet, tags: dict, text: str,
                  verify: Callable) -> list[dict]:
    """İnce kararın eşleşmelerini kodla denetler; her eşleşmeye `denetim`, `kabul`,
    `od_kabul` ekler. Alıntı tam (kısaltılmamış) metne karşı denetlenir."""
    rows = []
    seen = set()
    cset = set(cands)
    for m in out.get("eslesmeler") or []:
        r = dict(m)
        red: list[str] = []
        isaret: list[str] = []
        olcut, yuva = r.get("olcut"), r.get("yuva")
        if olcut not in cset:
            red.append("aday_disi_olcut")
        slot = None
        try:
            slot = cs.get_slot(yuva)
        except KeyError:
            red.append("gecersiz_yuva")
        if slot is not None and (slot.criterion != olcut or slot.footnote):
            red.append("yuva_olcute_ait_degil")
            slot = None
        q = (r.get("alinti") or "").strip()
        ok, score, span = verify(q, text) if q else (False, 0.0, None)
        r["denetim"] = {"alinti_tutuyor": bool(ok), "alinti_skor": round(float(score or 0), 4),
                        "alinti_konum": list(span) if span else None}
        if not ok:
            red.append("alinti_tutmuyor")
        if len(q) < MIN_QUOTE:
            red.append("alinti_cok_kisa")
        if (olcut, yuva) in seen:
            red.append("yinelenen")
        seen.add((olcut, yuva))
        # OD: aşama yuva etiketine uymalı; uymuyorsa yuvanın en düşük OD'si.
        tag = tags.get(yuva) if slot is not None else None
        asama = r.get("asama")
        od_model = r.get("od_onerisi")
        od_kod = None
        if tag is not None:
            r["yuva_etiketi"] = {"asama": list(tag.stages), "od": list(tag.od), "durum": tag.state}
            if tag.uncertain:
                od_kod = STAGE_OD.get(asama)
            elif asama in tag.stages:
                od_kod = STAGE_OD.get(asama)
            else:
                isaret.append("asama_yuva_etiketine_uymuyor")
                od_kod = min(tag.od) if tag.od else None
        elif slot is not None:
            od_kod = STAGE_OD.get(asama)
        if isinstance(od_model, int) and od_kod is not None and od_model != od_kod:
            isaret.append("od_asamayla_tutarsiz")
        cands_od = [x for x in (od_model if isinstance(od_model, int) else None, od_kod) if x]
        r["od_kabul"] = min(cands_od) if cands_od and not red else None
        r["denetim"]["red"] = red
        r["denetim"]["isaret"] = isaret
        r["kabul"] = not red
        rows.append(r)
    return rows


def summarize(matches: list[dict]) -> list[dict]:
    by: dict[str, dict] = {}
    for m in matches:
        if not m["kabul"]:
            continue
        e = by.setdefault(m["olcut"], {"olcut": m["olcut"], "ana": m["olcut"].rsplit(".", 1)[0],
                                       "od": None, "yuvalar": []})
        e["yuvalar"].append(m["yuva"])
        if m["od_kabul"] and (e["od"] is None or m["od_kabul"] > e["od"]):
            e["od"] = m["od_kabul"]
    return list(by.values())


def decide_doc(did: str, text: str, doc: dict | None, *, cs: CriteriaSet, tags: dict,
               allowed: list[str], cand_row: dict | None, k: int, max_aday: int,
               backend: Backend, cfg_coarse, cfg_fine, cache_dir: Path) -> dict:
    info = P.content_info(doc)
    info_s = P.render_info(info)
    det_top = [c["olcut"] for c in (cand_row or {}).get("adaylar", []) if c.get("olcut") in allowed][:k]
    terms = P.criteria_terms(cs, det_top) if det_top else None
    rec: dict = {"doc_id": did, "sema": SCHEMA, "durum": "ok",
                 "gorev": {COARSE: task_version(COARSE), FINE: task_version(FINE)},
                 "belge_bilgisi": info}

    # 1) kaba seçim
    body, ex = P.excerpt(text, P.COARSE_CHARS, terms)
    inputs = {"olcutler": P.coarse_list(cs, allowed), "belge_bilgisi": info_s, "belge_metni": body}
    res = backend.run_task(COARSE, inputs=inputs, model=cfg_coarse, cache_dir=cache_dir)
    out = res.output
    aset = set(allowed)
    picked = []
    for o in (out.get("olcutler") or []) if out.get("karar") == "olcut_var" else []:
        if o.get("olcut") in aset and o["olcut"] not in picked:
            picked.append(o["olcut"])
    rec["kaba"] = {"karar": out.get("karar"), "olcutler": out.get("olcutler") or [],
                   "secilen": picked[:MAX_COARSE], "gerekce": out.get("gerekce", ""),
                   "liste_disi": [o.get("olcut") for o in out.get("olcutler") or []
                                  if o.get("olcut") not in aset],
                   "model": _model_id(res, cfg_coarse), "onbellek": bool(getattr(res, "cached", False)),
                   "deneme": getattr(res, "attempts", None), "metin": ex,
                   "istem_token_tahmini": P.approx_tokens("".join(inputs.values()))}

    # 2) aday birleşimi
    cands, det, cut = merge_candidates(picked[:MAX_COARSE], cand_row, aset, k, max_aday)
    rec["adaylar"] = cands
    rec["belirleyici_ilk_k"] = det
    rec["adaylar_kesilen"] = cut
    if not cands:
        rec["ince"] = {"karar": "atlandi", "neden": "aday_yok"}
        rec["eslesmeler"], rec["olcutler"], rec["karar"] = [], [], out.get("karar") or "olcut_yok"
        return rec

    # 3) ince karar
    body, ex = P.excerpt(text, P.FINE_CHARS, P.criteria_terms(cs, cands))
    inputs = {"adaylar": P.fine_list(cs, cands, tags), "belge_bilgisi": info_s, "belge_metni": body}
    res = backend.run_task(FINE, inputs=inputs, model=cfg_fine, cache_dir=cache_dir)
    out = res.output
    matches = check_matches(out, cands, cs, tags, text, backend.verify_quote)
    rec["ince"] = {"karar": out.get("karar"), "gerekce": out.get("gerekce", ""),
                   "model": _model_id(res, cfg_fine), "onbellek": bool(getattr(res, "cached", False)),
                   "deneme": getattr(res, "attempts", None), "metin": ex,
                   "istem_token_tahmini": P.approx_tokens("".join(inputs.values()))}
    rec["eslesmeler"] = matches
    rec["olcutler"] = summarize(matches)
    if rec["olcutler"]:
        rec["karar"] = "olcut_var"
    elif out.get("karar") == "kanit_degil":
        rec["karar"] = "kanit_degil"
    else:
        rec["karar"] = "olcut_yok"
    rec["reddedilen_eslesme"] = sum(not m["kabul"] for m in matches)
    return rec


def run(ws_root: Path, *, profile: str | None = "akademik_bolum", only_labeled: bool = False,
        limit: int | None = None, k: int = 5, max_aday: int = 6,
        candidates_name: str = "candidates.jsonl", out_name: str = DECISIONS,
        backend: Backend | None = None, criteria: CriteriaSet | None = None,
        exclude_types: frozenset | None = None,
        log: Callable[[str], None] = print) -> tuple[Path, dict]:
    ws = Workspace(ws_root)
    backend = backend or Backend.default()
    cs = criteria or load_criteria()
    tags = load_tags(cs)
    allowed = load_profile(profile).allowed(cs) if profile else [s.id for s in cs.sub_criteria]
    ex_types = excluded_types() if exclude_types is None else exclude_types
    docs = _documents(ws)
    cand = _candidates(ws.root / candidates_name)
    if not cand:
        log(f"uyarı: {candidates_name} yok ya da boş; adaylar yalnız kaba seçimden")
    ids = sorted(p.stem for p in ws.text_dir.glob("*.txt")) if ws.text_dir.exists() else []
    if only_labeled:
        lab = _labeled_ids(ws)
        ids = [i for i in ids if i in lab]
    if limit:
        ids = ids[:limit]
    cfg_c = backend.load_model_config(ws.root, role="coarse")
    cfg_f = backend.load_model_config(ws.root, role="fine")
    cache = ws.root / ".cache" / "llm"
    out = ws.root / out_name
    part = out.with_suffix(out.suffix + ".partial")
    stats = {"belge": 0, "ok": 0, "atlandi": 0, "hata": 0, "olcut_var": 0, "olcut_yok": 0,
             "kanit_degil": 0, "reddedilen_eslesme": 0, "kabul_eslesme": 0}
    with open(part, "w", encoding="utf-8") as f:
        for did in ids:
            stats["belge"] += 1
            doc = docs.get(did)
            text = ws.text_path(did).read_text(encoding="utf-8", errors="replace")
            if doc and doc.get("doc_type") in ex_types:
                rec = {"doc_id": did, "sema": SCHEMA, "durum": "atlandi", "neden": "oz_referans_turu",
                       "doc_type": doc["doc_type"]}
            elif not text.strip():
                rec = {"doc_id": did, "sema": SCHEMA, "durum": "atlandi", "neden": "metin_bos"}
            else:
                try:
                    rec = decide_doc(did, text, doc, cs=cs, tags=tags, allowed=allowed,
                                     cand_row=cand.get(did), k=k, max_aday=max_aday, backend=backend,
                                     cfg_coarse=cfg_c, cfg_fine=cfg_f, cache_dir=cache)
                except Exception as e:  # model/şema hatası: belge işaretlenir, sürer
                    rec = {"doc_id": did, "sema": SCHEMA, "durum": "hata",
                           "hata": f"{type(e).__name__}: {e}"[:500]}
            rec["profil"] = profile
            stats[rec["durum"]] += 1
            if rec["durum"] == "ok":
                stats[rec["karar"]] = stats.get(rec["karar"], 0) + 1
                stats["reddedilen_eslesme"] += rec.get("reddedilen_eslesme", 0)
                stats["kabul_eslesme"] += sum(m["kabul"] for m in rec.get("eslesmeler", []))
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            log(f"{did} {rec['durum']} {rec.get('karar', rec.get('neden', ''))}")
    part.replace(out)
    return out, stats
