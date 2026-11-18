"""`bidr name prepare|apply`: işlenmiş belgelere sonradan kanıt adı (ajan modu; ucuz görev).

  prepare  kabul edilmiş eşleşmesi olan her belge için (mükerrer kopyalar hariç: adı
           temsilcinindir) `work/name/<doc_id>.json` iş paketi yazar: belge metninin başı,
           içerik alanları (tür, tarih, akademik dönem), identify başlığı, eşleştiği ölçütler
           ve alıntılar. Yol/dosya adı/çalışma adı pakete girmez (decide ile aynı ilke).
           Model adı zaten olan belge (`kanit-adlari.jsonl` model kaydı ya da ince kararın
           kabul edilmiş `kanit_adi`'sı) paketlenmez (`--redo` ya da `--only` ile yeniden).
           Uygunluk insan birim kararıyla (`birim-kararlari.jsonl`, insan > model) belirlenir:
           başka birim sayılıp komisyonca geri alınan belgenin geri yüklenen eşleşmeleri kanıttır;
           komisyonun başka birim onayladığı belgeninki değildir (audit/file ile aynı görünüm).
  apply    `<doc_id>.out.json` cevaplarını şemaya ve `check_name`'e göre doğrular,
           `kanit-adlari.jsonl`'e `kaynak: model` olarak yazar. Kişi adı/unvan/e-posta içeren
           ya da biçimsiz ad reddedilir (`GECERSIZ.md`), belge kural adında kalır.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from bidr.common import Workspace, read_jsonl
from bidr.decide import prompt as P

from .check import check_name
from .resolve import NAMES, decision_name, load_names, upsert

TASK = "name_evidence"
NAME_CHARS = 2500        # belge metni bütçesi (baş ağırlıklı)
QUOTE_CHARS = 200
MAX_MATCH = 6

README = """# bidr iş paketleri: {task} (sürüm {version})

Her `<doc_id>.json` bir iş paketidir: belgeye kanıt dosyası adı ver. Sağlayıcı çağrılmaz.

1. Paketi oku; `istem` görevin tamamıdır, `sema` cevabın şemasıdır.
2. Cevabı YALNIZ JSON olarak aynı klasörde `<doc_id>.out.json`'a yaz.
3. Bitince: `bidr name apply -w <çalışma klasörü> --model <ajan/model adı>`.
   Reddedilen adlar `GECERSIZ.md`'de; düzeltip yeniden apply.

Bekleyen paket: {n}
"""


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def task_version() -> str:
    import yaml
    from bidr.llm.tasks import TASKS_DIR
    return str((yaml.safe_load((TASKS_DIR / TASK / "task.yaml").read_text(encoding="utf-8")) or {})["version"])


def work_dir(ws: Workspace) -> Path:
    return ws.root / "work" / "name"


def _decisions(ws: Workspace) -> dict[str, dict]:
    p = ws.root / "decisions.jsonl"
    if not p.exists():
        raise FileNotFoundError(f"decisions.jsonl yok: {p}")
    return {r["doc_id"]: r for r in read_jsonl(p) if r.get("doc_id")}


def decisions_view(ws: Workspace, recs: dict[str, dict] | None = None, cs=None) -> dict[str, dict]:
    """Kararların insan birim kararıyla görünümü (`bidr.decide.run.unit_view`; insan > model).
    Birim kararları decide gibi çalışma alanındaki `birim-kararlari.jsonl`'den okunur."""
    from bidr.decide.run import load_unit_pins, unit_view
    recs = _decisions(ws) if recs is None else recs
    pins = load_unit_pins(ws.root)
    if not pins:
        return recs
    from bidr.criteria.slots import load_tags
    if cs is None:
        from bidr.criteria.loader import load_criteria
        cs = load_criteria()
    tags = load_tags(cs)
    return {d: unit_view(r, pins, tags) for d, r in recs.items()}


def eligible(recs: dict[str, dict]) -> list[str]:
    """Kabul edilmiş eşleşmesi olan, kararı devralmamış (temsilci ya da tekil) belgeler."""
    out = []
    for did, r in sorted(recs.items()):
        if r.get("durum") != "ok" or r.get("asama") != "ince":
            continue
        if (r.get("mukerrer") or {}).get("durum") == "devralindi":
            continue
        if any(m.get("kabul") for m in r.get("eslesmeler") or []):
            out.append(did)
    return out


def inputs_of(ws: Workspace, did: str, rec: dict, doc: dict | None, cs=None) -> dict:
    if cs is None:
        from bidr.criteria.loader import load_criteria
        cs = load_criteria()
    lines = []
    for m in [m for m in rec.get("eslesmeler") or [] if m.get("kabul")][:MAX_MATCH]:
        try:
            title = cs.get(m["olcut"]).title
        except KeyError:
            title = ""
        q = (m.get("alinti") or "").replace("\n", " ")
        q = q if len(q) <= QUOTE_CHARS else q[:QUOTE_CHARS].rsplit(" ", 1)[0] + " …"
        lines.append(f"- {m['olcut']} {title} (yuva {m['yuva']}, {m.get('asama')}): \"{q}\"")
    text = ws.text_path(did).read_text(encoding="utf-8", errors="replace") if ws.text_path(did).exists() else ""
    body, _ = P.excerpt(text, NAME_CHARS)
    bas = (doc or {}).get("baslik")
    return {"belge_bilgisi": P.render_info(P.content_info(doc)),
            "baslik": bas.strip() if isinstance(bas, str) and bas.strip() else "(yok)",
            "olcutler": "\n".join(lines) or "(yok)", "belge_metni": body or "(metin yok)"}


def prepare(ws_root: Path, *, only: list[str] | None = None, redo: bool = False,
            render=None) -> dict:
    if render is None:
        from bidr.llm import render_task as render
    from bidr.criteria.loader import load_criteria
    ws = Workspace(ws_root)
    cs = load_criteria()
    recs = decisions_view(ws, cs=cs)
    docs = {r["doc_id"]: r for r in read_jsonl(ws.documents)} if ws.documents.exists() else {}
    have = load_names(ws.root)
    d = work_dir(ws)
    d.mkdir(parents=True, exist_ok=True)
    st = {"paket": 0, "yeni": 0, "zaten_adli": 0, "uygun_degil": [], "klasor": str(d)}
    pool = eligible(recs)
    if only is not None:
        ids = list(dict.fromkeys(only))
        st["uygun_degil"] = [x for x in ids if x not in pool]
        ids = [x for x in ids if x in pool]
    else:
        ids = pool
    for did in ids:
        if only is None and not redo and ("model" in (have.get(did) or {}) or decision_name(recs[did])):
            st["zaten_adli"] += 1
            continue
        r = render(TASK, inputs_of(ws, did, recs[did], docs.get(did), cs))
        sha = _sha(r["prompt"])[:16]
        p = d / f"{did}.json"
        st["paket"] += 1
        old = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
        if old and old.get("istem_sha") == sha and str(old.get("surum")) == str(r["version"]):
            continue
        out = d / f"{did}.out.json"
        if out.exists():
            out.replace(d / f"{did}.out.json.eski")
        p.write_text(json.dumps({"gorev": r["task"], "surum": str(r["version"]), "doc_id": did,
                                 "istem_sha": sha, "cikti_dosyasi": f"{did}.out.json",
                                 "istem": r["prompt"], "sema": r["schema"]}, ensure_ascii=False, indent=1),
                     encoding="utf-8")
        st["yeni"] += 1
    n = _pending(d)
    (d / "README.md").write_text(README.format(task=TASK, version=task_version(), n=n), encoding="utf-8")
    st["bekleyen"] = n
    return st


def _pkgs(d: Path) -> list[Path]:
    return sorted(p for p in d.glob("*.json") if not p.name.endswith(".out.json")) if d.exists() else []


def _pending(d: Path) -> int:
    return sum(1 for p in _pkgs(d) if not (d / f"{p.stem}.out.json").exists())


def apply(ws_root: Path, *, model: str = "ajan:belirtilmemis", only: list[str] | None = None,
          validate=None) -> dict:
    if validate is None:
        from bidr.llm import validate_output as validate
    ws = Workspace(ws_root)
    d = work_dir(ws)
    ver = task_version()
    st = {"islenen": 0, "degismedi": 0, "bekleyen": [], "gecersiz": {}, "reddedilen": {}, "eski_surum": []}
    have = load_names(ws.root)
    new: list[dict] = []
    for p in _pkgs(d):
        pkg = json.loads(p.read_text(encoding="utf-8"))
        did = pkg["doc_id"]
        if only and did not in only:
            continue
        outp = d / pkg["cikti_dosyasi"]
        if not outp.exists():
            st["bekleyen"].append(did)
            continue
        if str(pkg["surum"]) != ver:
            st["eski_surum"].append(did)
            continue
        raw = outp.read_text(encoding="utf-8")
        out, errs = validate(TASK, raw)
        if out is None:
            st["gecersiz"][did] = errs[:5]
            continue
        ad, errs = check_name(out.get("kanit_adi"))
        if errs:
            st["reddedilen"][did] = {"oneri": out.get("kanit_adi"), "neden": errs}
            continue
        rec = {"doc_id": did, "ad": ad, "kaynak": "model", "model": model, "gorev": {TASK: ver},
               "istem_sha": pkg["istem_sha"], "cevap_sha": _sha(raw)[:16],
               "gerekce": out.get("gerekce", "")}
        prev = (have.get(did) or {}).get("model")
        if prev and {k: v for k, v in prev.items() if k != "zaman"} == rec:
            st["degismedi"] += 1
            continue
        new.append({**rec, "zaman": time.strftime("%Y-%m-%dT%H:%M:%S")})
        st["islenen"] += 1
    if new:
        upsert(ws.root / NAMES, new)
    lines = [f"# Yeniden yapılacak ({TASK})", ""]
    for did, errs in st["gecersiz"].items():
        lines.append(f"- `{did}.json` — geçersiz cevap: " + "; ".join(errs))
    for did, x in st["reddedilen"].items():
        lines.append(f"- `{did}.json` — ad reddedildi ({', '.join(x['neden'])}): "
                     + json.dumps(x["oneri"], ensure_ascii=False)
                     + ". Kişi adı/unvan/e-posta yok; 3-7 sözcük.")
    if d.exists():
        g = d / "GECERSIZ.md"
        if len(lines) > 2:
            g.write_text("\n".join(lines) + "\n", encoding="utf-8")
        elif g.exists():
            g.unlink()
    st["dosya"] = str(ws.root / NAMES)
    return st
