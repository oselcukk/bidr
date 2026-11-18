"""`bidr decide`: iki adımlı model kararı → decisions.jsonl.

İki yol, aynı görev girdileri ve aynı denetim:
  - ajan modu (birincil): `prepare` iş paketlerini `work/<aşama>/<doc_id>.json` olarak
    yazar; kullanıcının ajanı her paketi okuyup cevabı `<doc_id>.out.json`'a yazar;
    `apply` cevapları doğrular (şema + alıntı) ve decisions.jsonl'e işler. Sağlayıcı
    çağrılmaz.
  - sağlayıcı modu (ikincil): `run` aynı girdileri `bidr.llm.run_task` ile işler.

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


class Backend:
    """`bidr.llm` arayüzü (docs/MODEL_LAYER.md). Verilmeyen işlev çağrıldığında
    `bidr.llm`'den alınır; testler sahtesini verir."""
    NAMES = ("run_task", "load_model_config", "verify_quote", "render_task", "validate_output")

    def __init__(self, **fns):
        bad = set(fns) - set(self.NAMES)
        if bad:
            raise TypeError(f"bilinmeyen işlev: {bad}")
        self._fns = fns

    def __getattr__(self, name):
        if name in Backend.NAMES:
            f = self.__dict__["_fns"].get(name)
            if f is None:
                import bidr.llm as llm
                f = getattr(llm, name)
            return f
        raise AttributeError(name)


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
    return str(m) if m else str(getattr(cfg, "model_id", None) or getattr(cfg, "id", cfg))


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


# -- bağlam ---------------------------------------------------------------------

@dataclass
class Context:
    ws: Workspace
    cs: CriteriaSet
    tags: dict
    profile: str | None
    allowed: list[str]
    ex_types: frozenset
    docs: dict
    cand: dict
    k: int
    max_aday: int

    @classmethod
    def load(cls, ws_root: Path, *, profile: str | None = "akademik_bolum", k: int = 5,
             max_aday: int = 6, candidates_name: str = "candidates.jsonl",
             criteria: CriteriaSet | None = None, exclude_types: frozenset | None = None) -> "Context":
        ws = Workspace(ws_root)
        cs = criteria or load_criteria()
        allowed = load_profile(profile).allowed(cs) if profile else [s.id for s in cs.sub_criteria]
        return cls(ws, cs, load_tags(cs), profile or None, allowed,
                   excluded_types() if exclude_types is None else exclude_types,
                   _documents(ws), _candidates(ws.root / candidates_name), k, max_aday)

    def text(self, did: str) -> str:
        return self.ws.text_path(did).read_text(encoding="utf-8", errors="replace")

    def det_top(self, did: str) -> list[str]:
        aset = set(self.allowed)
        return [c["olcut"] for c in (self.cand.get(did) or {}).get("adaylar", [])
                if c.get("olcut") in aset][:self.k]

    def skip_reason(self, did: str) -> str | None:
        doc = self.docs.get(did)
        if doc and doc.get("doc_type") in self.ex_types:
            return "oz_referans_turu"
        if not self.ws.text_path(did).exists():
            return "metin_yok"
        if not self.text(did).strip():
            return "metin_bos"
        return None


def select_ids(ctx: Context, *, only_labeled: bool = False, limit: int | None = None,
               ids: list[str] | None = None) -> list[str]:
    out = ids if ids is not None else (
        sorted(p.stem for p in ctx.ws.text_dir.glob("*.txt")) if ctx.ws.text_dir.exists() else [])
    if only_labeled:
        lab = _labeled_ids(ctx.ws)
        out = [i for i in out if i in lab]
    return out[:limit] if limit else out


# -- decisions.jsonl deposu ----------------------------------------------------------

def load_decisions(ws: Workspace, name: str = DECISIONS) -> dict[str, dict]:
    p = ws.root / name
    return {r["doc_id"]: r for r in read_jsonl(p)} if p.exists() else {}


def save_decisions(ws: Workspace, recs: dict[str, dict], name: str = DECISIONS) -> Path:
    from bidr.common import write_jsonl
    out = ws.root / name
    write_jsonl(out, [recs[k] for k in sorted(recs)])
    return out


def skipped_record(did: str, reason: str, ctx: Context) -> dict:
    r = {"doc_id": did, "sema": SCHEMA, "durum": "atlandi", "neden": reason, "profil": ctx.profile}
    if reason == "oz_referans_turu":
        r["doc_type"] = ctx.docs[did]["doc_type"]
    return r


# -- görev girdileri ve sonuç işleme (iki yolun ortak çekirdeği) ----------------------

def coarse_inputs(ctx: Context, did: str) -> tuple[dict, dict]:
    """(görev girdileri, meta). Meta, `apply`'ın ihtiyaç duyduğu ve modele gitmeyen bilgi."""
    info = P.content_info(ctx.docs.get(did))
    det = ctx.det_top(did)
    body, ex = P.excerpt(ctx.text(did), P.COARSE_CHARS, P.criteria_terms(ctx.cs, det) if det else None)
    inputs = {"olcutler": P.coarse_list(ctx.cs, ctx.allowed), "belge_bilgisi": P.render_info(info),
              "belge_metni": body}
    meta = {"belge_bilgisi": info, "metin": ex, "profil": ctx.profile, "izinli": list(ctx.allowed),
            "istem_token_tahmini": P.approx_tokens("".join(inputs.values()))}
    return inputs, meta


def apply_coarse(did: str, out: dict, meta: dict, model_id: str, extra: dict | None = None) -> dict:
    aset = set(meta["izinli"])
    picked: list[str] = []
    if out.get("karar") == "olcut_var":
        for o in out.get("olcutler") or []:
            if o.get("olcut") in aset and o["olcut"] not in picked:
                picked.append(o["olcut"])
    return {"doc_id": did, "sema": SCHEMA, "durum": "ok", "asama": "kaba", "profil": meta["profil"],
            "gorev": {COARSE: task_version(COARSE)}, "belge_bilgisi": meta["belge_bilgisi"],
            "kaba": {"karar": out.get("karar"), "olcutler": out.get("olcutler") or [],
                     "secilen": picked[:MAX_COARSE], "gerekce": out.get("gerekce", ""),
                     "liste_disi": [o.get("olcut") for o in out.get("olcutler") or []
                                    if o.get("olcut") not in aset],
                     "model": model_id, "metin": meta["metin"],
                     "istem_token_tahmini": meta["istem_token_tahmini"], **(extra or {})}}


def fine_inputs(ctx: Context, did: str, rec: dict) -> tuple[dict, dict] | None:
    """Kaba kayıttan aday birleşimi; aday yoksa None."""
    cands, det, cut = merge_candidates(rec["kaba"]["secilen"], ctx.cand.get(did), set(ctx.allowed),
                                       ctx.k, ctx.max_aday)
    meta = {"adaylar": cands, "belirleyici_ilk_k": det, "adaylar_kesilen": cut}
    if not cands:
        return None, meta
    body, ex = P.excerpt(ctx.text(did), P.FINE_CHARS, P.criteria_terms(ctx.cs, cands))
    inputs = {"adaylar": P.fine_list(ctx.cs, cands, ctx.tags),
              "belge_bilgisi": P.render_info(rec.get("belge_bilgisi") or {}), "belge_metni": body}
    meta.update(metin=ex, istem_token_tahmini=P.approx_tokens("".join(inputs.values())))
    return inputs, meta


def no_candidate(rec: dict, meta: dict) -> dict:
    rec = dict(rec)
    rec.update(asama="ince", adaylar=[], belirleyici_ilk_k=meta["belirleyici_ilk_k"],
               adaylar_kesilen=[], ince={"karar": "atlandi", "neden": "aday_yok"},
               eslesmeler=[], olcutler=[], reddedilen_eslesme=0,
               karar="kanit_degil" if rec["kaba"]["karar"] == "kanit_degil" else "olcut_yok")
    return rec


def apply_fine(ctx: Context, did: str, rec: dict, out: dict, meta: dict, model_id: str,
               verify: Callable, extra: dict | None = None) -> dict:
    rec = dict(rec)
    matches = check_matches(out, meta["adaylar"], ctx.cs, ctx.tags, ctx.text(did), verify)
    rec["gorev"] = {**rec.get("gorev", {}), FINE: task_version(FINE)}
    rec.update(asama="ince", adaylar=meta["adaylar"], belirleyici_ilk_k=meta["belirleyici_ilk_k"],
               adaylar_kesilen=meta["adaylar_kesilen"])
    rec["ince"] = {"karar": out.get("karar"), "gerekce": out.get("gerekce", ""), "model": model_id,
                   "metin": meta["metin"], "istem_token_tahmini": meta["istem_token_tahmini"],
                   **(extra or {})}
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


def stats_of(recs: dict[str, dict]) -> dict:
    st = {"belge": len(recs), "ok": 0, "atlandi": 0, "hata": 0, "kaba": 0, "ince": 0,
          "olcut_var": 0, "olcut_yok": 0, "kanit_degil": 0, "kabul_eslesme": 0, "reddedilen_eslesme": 0}
    for r in recs.values():
        st[r["durum"]] = st.get(r["durum"], 0) + 1
        if r["durum"] != "ok":
            continue
        st[r.get("asama", "kaba")] += 1
        if r.get("asama") == "ince":
            st[r["karar"]] += 1
            st["kabul_eslesme"] += sum(m["kabul"] for m in r.get("eslesmeler", []))
            st["reddedilen_eslesme"] += r.get("reddedilen_eslesme", 0)
    return st


# -- ajan modu: iş paketleri -------------------------------------------------------------

STAGES = {"coarse": COARSE, "fine": FINE}
README = """# bidr iş paketleri: {task} (sürüm {version})

Bu klasördeki her `<doc_id>.json` bir iş paketidir. Sağlayıcı/API çağrılmaz; işi sen
(ajan) yaparsın.

1. Paketi oku. `istem` alanı görevin tamamıdır (kurallar, ölçütler, belge metni);
   `sema` cevabın uyması gereken JSON şemasıdır.
2. İstemdeki kurallara uy: yalnız belge metnine dayan, alıntılar belgeden birebir olsun;
   "kanit_degil" ve "olcut_yok" geçerli cevaplardır.
3. Cevabı YALNIZ JSON olarak (açıklama, kod çiti yok) aynı klasörde `<doc_id>.out.json`
   dosyasına yaz. Var olan paketleri ve başka dosyaları değiştirme.
4. Paketler birbirinden bağımsızdır; paralel alt ajanlar kullanabilirsin (her alt ajana
   bir grup paket ver).
5. Bitince: `bidr decide apply -w <çalışma klasörü> --stage {stage} --model <ajan/model adı>`.
   Geçersiz cevaplar listelenir ve `GECERSIZ.md`'ye yazılır; onları yeniden yap.

Bekleyen paket: {n}
"""


def work_dir(ws: Workspace, stage: str) -> Path:
    return ws.root / "work" / stage


def _pkg_paths(d: Path) -> list[Path]:
    return sorted(p for p in d.glob("*.json") if not p.name.endswith(".out.json"))


def _write_pkg(d: Path, did: str, task: str, inputs: dict, meta: dict, backend: Backend) -> bool:
    """Paketi yazar; istem değiştiyse eski cevabı `.out.json.eski` yapar. Yeni/değişmiş ise True."""
    import hashlib
    r = backend.render_task(task, inputs)
    sha = hashlib.sha256(r["prompt"].encode("utf-8")).hexdigest()[:16]
    pkg = {"gorev": r["task"], "surum": str(r["version"]), "doc_id": did, "istem_sha": sha,
           "cikti_dosyasi": f"{did}.out.json", "istem": r["prompt"], "sema": r["schema"],
           "ozet": {"istem_karakter": len(r["prompt"]), "istem_token_tahmini": P.approx_tokens(r["prompt"]),
                    **{k: v for k, v in meta.items() if k in ("adaylar", "belge_bilgisi")},
                    "metin": meta.get("metin")},
           "meta": meta}
    p = d / f"{did}.json"
    old = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    if old and old.get("istem_sha") == sha:
        return False
    out = d / f"{did}.out.json"
    if out.exists():
        out.replace(d / f"{did}.out.json.eski")
    p.write_text(json.dumps(pkg, ensure_ascii=False, indent=1), encoding="utf-8")
    return True


def prepare(ws_root: Path, stage: str, *, profile: str | None = "akademik_bolum",
            only_labeled: bool = False, limit: int | None = None, k: int = 5, max_aday: int = 6,
            backend: Backend | None = None, ctx: Context | None = None,
            redo: bool = False) -> dict:
    """İş paketleri. coarse: atlanacak belgeler decisions.jsonl'e `atlandi` yazılır.
    fine: kaba kaydı olan belgeler; adayı olmayanlar doğrudan sonuçlanır.
    Zaten işlenmiş belge (aşama tamam) `redo` verilmedikçe paketlenmez."""
    backend = backend or Backend()
    task = STAGES[stage]
    if ctx is None:
        ctx = Context.load(ws_root, profile=profile, k=k, max_aday=max_aday)
    recs = load_decisions(ctx.ws)
    d = work_dir(ctx.ws, stage)
    d.mkdir(parents=True, exist_ok=True)
    st = {"paket": 0, "yeni": 0, "atlandi": 0, "kaba_yok": 0, "aday_yok": 0, "zaten_tamam": 0}
    for did in select_ids(ctx, only_labeled=only_labeled, limit=limit):
        rec = recs.get(did)
        if stage == "coarse":
            why = ctx.skip_reason(did)
            if why:
                recs[did] = skipped_record(did, why, ctx)
                st["atlandi"] += 1
                continue
            if rec and rec.get("durum") == "ok" and not redo:
                st["zaten_tamam"] += 1
                continue
            inputs, meta = coarse_inputs(ctx, did)
        else:
            if not rec or rec.get("durum") != "ok" or "kaba" not in rec:
                st["kaba_yok"] += 1
                continue
            if rec.get("asama") == "ince" and not redo:
                st["zaten_tamam"] += 1
                continue
            inputs, meta = fine_inputs(ctx, did, rec)
            if inputs is None:
                recs[did] = no_candidate(rec, meta)
                st["aday_yok"] += 1
                continue
        st["paket"] += 1
        st["yeni"] += _write_pkg(d, did, task, inputs, meta, backend)
    save_decisions(ctx.ws, recs)
    pending = sum(1 for p in _pkg_paths(d) if not (d / f"{p.stem}.out.json").exists())
    (d / "README.md").write_text(README.format(task=task, version=task_version(task), stage=stage,
                                               n=pending), encoding="utf-8")
    st["bekleyen"] = pending
    st["klasor"] = str(d)
    return st


def apply(ws_root: Path, stage: str, *, model: str = "ajan:belirtilmemis",
          backend: Backend | None = None, ctx: Context | None = None) -> dict:
    """`.out.json` cevaplarını doğrular ve decisions.jsonl'e işler. Şemaya uymayan ya da
    JSON olmayan cevap işlenmez (`gecersiz`); alıntısı tutmayan eşleşme kayda reddedilmiş
    olarak girer ve `alinti_tutmayan` listesinde yeniden yapılmak üzere gösterilir.
    Paket meta'sı (profil, adaylar) paketten okunur; profil yeniden hesaplanmaz."""
    backend = backend or Backend()
    task = STAGES[stage]
    if ctx is None:
        ctx = Context.load(ws_root, profile=None)
    recs = load_decisions(ctx.ws)
    d = work_dir(ctx.ws, stage)
    st = {"islenen": 0, "bekleyen": [], "gecersiz": {}, "alinti_tutmayan": {}, "eski_surum": []}
    for p in _pkg_paths(d):
        pkg = json.loads(p.read_text(encoding="utf-8"))
        did = pkg["doc_id"]
        outp = d / pkg["cikti_dosyasi"]
        if not outp.exists():
            st["bekleyen"].append(did)
            continue
        if str(pkg["surum"]) != task_version(task):
            st["eski_surum"].append(did)
            continue
        out, errs = backend.validate_output(task, outp.read_text(encoding="utf-8"))
        if out is None:
            st["gecersiz"][did] = errs[:5]
            continue
        extra = {"kip": "ajan", "istem_sha": pkg["istem_sha"]}
        if stage == "coarse":
            recs[did] = apply_coarse(did, out, pkg["meta"], model, extra)
        else:
            rec = recs.get(did)
            if not rec or "kaba" not in rec:
                st["gecersiz"][did] = ["decisions.jsonl'de kaba kayıt yok"]
                continue
            rec = apply_fine(ctx, did, rec, out, pkg["meta"], model, backend.verify_quote, extra)
            recs[did] = rec
            bad = [f"{m.get('yuva')}: {', '.join(m['denetim']['red'])}"
                   for m in rec["eslesmeler"] if not m["kabul"]]
            if bad:
                st["alinti_tutmayan"][did] = bad
        st["islenen"] += 1
    save_decisions(ctx.ws, recs)
    lines = [f"# Yeniden yapılacak ({task})", ""]
    for did, errs in st["gecersiz"].items():
        lines.append(f"- `{did}.json` — geçersiz cevap: " + "; ".join(errs))
    for did, bad in st["alinti_tutmayan"].items():
        lines.append(f"- `{did}.json` — reddedilen eşleşme (alıntı belgede birebir olmalı): "
                     + "; ".join(bad))
    if d.exists():
        g = d / "GECERSIZ.md"
        if len(lines) > 2:
            g.write_text("\n".join(lines) + "\n", encoding="utf-8")
        elif g.exists():
            g.unlink()
    st["durum"] = stats_of(recs)
    return st


# -- sağlayıcı modu ---------------------------------------------------------------------------

def run(ws_root: Path, *, profile: str | None = "akademik_bolum", only_labeled: bool = False,
        limit: int | None = None, k: int = 5, max_aday: int = 6,
        candidates_name: str = "candidates.jsonl", backend: Backend | None = None,
        criteria: CriteriaSet | None = None, exclude_types: frozenset | None = None,
        log: Callable[[str], None] = print) -> tuple[Path, dict]:
    """Sağlayıcılı yol: her belge için kaba + ince `run_task` ile; hata belgeyi işaretler."""
    backend = backend or Backend()
    ctx = Context.load(ws_root, profile=profile, k=k, max_aday=max_aday,
                       candidates_name=candidates_name, criteria=criteria, exclude_types=exclude_types)
    if not ctx.cand:
        log(f"uyarı: {candidates_name} yok ya da boş; adaylar yalnız kaba seçimden")
    cfg_c = backend.load_model_config(ctx.ws.root, role="coarse")
    cfg_f = backend.load_model_config(ctx.ws.root, role="fine")
    cache = ctx.ws.root / ".cache" / "llm"
    recs = load_decisions(ctx.ws)
    for did in select_ids(ctx, only_labeled=only_labeled, limit=limit):
        why = ctx.skip_reason(did)
        if why:
            recs[did] = skipped_record(did, why, ctx)
            continue
        try:
            inputs, meta = coarse_inputs(ctx, did)
            res = backend.run_task(COARSE, inputs=inputs, model=cfg_c, cache_dir=cache)
            rec = apply_coarse(did, res.output, meta, _model_id(res, cfg_c),
                               {"kip": "saglayici", "onbellek": bool(getattr(res, "cached", False)),
                                "deneme": getattr(res, "attempts", None)})
            inputs, meta = fine_inputs(ctx, did, rec)
            if inputs is None:
                rec = no_candidate(rec, meta)
            else:
                res = backend.run_task(FINE, inputs=inputs, model=cfg_f, cache_dir=cache)
                rec = apply_fine(ctx, did, rec, res.output, meta, _model_id(res, cfg_f),
                                 backend.verify_quote,
                                 {"kip": "saglayici", "onbellek": bool(getattr(res, "cached", False)),
                                  "deneme": getattr(res, "attempts", None)})
        except Exception as e:  # model/şema hatası: belge işaretlenir, sürer
            rec = {"doc_id": did, "sema": SCHEMA, "durum": "hata", "profil": ctx.profile,
                   "hata": f"{type(e).__name__}: {e}"[:500]}
        recs[did] = rec
        log(f"{did} {rec['durum']} {rec.get('karar', '')}")
        save_decisions(ctx.ws, recs)     # her belgeden sonra: kesilirse kaldığı yer korunur
    out = save_decisions(ctx.ws, recs)
    return out, stats_of(recs)
