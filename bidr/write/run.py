"""`bidr write prepare|apply`: ölçüt açıklama metinleri (ajan modu) → `texts/<ölçüt>.json`.

prepare: kanıtı olan her ölçüt için `work/write/<ölçüt>.json` paketi. Girdiler:
  - `evidence-index.csv` (kanıt no, ad, alıntılar; alıntının belge metnindeki bağlamı),
  - `audit-olcutler.json` (önerilen OD, PUKÖ zinciri, eksik halkalar, notlar),
  - ölçüt tanımı/rubrik (paket verisi), kılavuzun yazım soruları,
  - isteğe bağlı: geçen yılın aynı ölçüt metni (`--onceki` ya da config.yaml
    `rapor.onceki_rapor`: FR-0833 docx'i ya da `<ölçüt>.txt` klasörü) ve komisyon bilgisi
    (`rapor-notlari.yaml`).
apply: şema + kod denetimi (bidr/write/text.py: her cümlede atıf, atıf listede mi, OD aşımı,
yasak ifade, uydurma gelecek vaadi). Geçemeyen cevap yazılmaz (GECERSIZ.md); geçen metin
`texts/<ölçüt>.json` olur, `durum: taslak` (doğrulama `bidr verify`).
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from bidr.common import Workspace, read_jsonl
from bidr.criteria.loader import load_criteria
from bidr.criteria.model import id_key

from . import packages as K
from . import sources as S
from . import text as T

TASK = "write_criterion"
STAGE = "write"
TEXTS = "texts"
HALKA = {"planla": "planlama", "uygula": "uygulama", "kontrol_et": "kontrol (izleme/ölçme)",
         "onlem_al": "önlem alma (iyileştirme)", "ozgun": "özgün uygulama"}
GUIDE = Path(__file__).resolve().parents[1] / "data" / "criteria" / "guide.yaml"
RULE = ("İstemdeki kurallara uy: her cümle `[n_ODk]` atfı taşır, yalnız kanıtta olanı yaz, "
        "önerilen OD'nin üstünde olgunluk dili kullanma, gelecek vaadi uydurma.")


class Backend:
    """`bidr.llm` arayüzü; testler sahtesini verir."""
    NAMES = ("render_task", "validate_output", "verify_quote")

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


def task_version(name: str = TASK) -> str:
    from bidr.llm import load_task
    return str(load_task(name).version)


def texts_dir(ws: Workspace) -> Path:
    return ws.root / TEXTS


def work_dir(ws: Workspace, stage: str = STAGE) -> Path:
    return ws.root / "work" / stage


# -- bağlam ---------------------------------------------------------------------------------

class Sources:
    """Bir çalışma alanının yazım/doğrulama girdileri (salt okunur)."""

    def __init__(self, ws_root: Path, *, index: Path | None = None, audit: Path | None = None,
                 onceki: str | Path | None = None, notes: Path | None = None, verify=None):
        self.ws = Workspace(Path(ws_root))
        self.index_path = Path(index) if index else self.ws.root / S.INDEX
        self.audit_path = Path(audit) if audit else self.ws.root / S.AUDIT
        if not self.index_path.exists():
            raise FileNotFoundError(f"{S.INDEX} yok: {self.index_path} (önce `file` aşaması)")
        if not self.audit_path.exists():
            raise FileNotFoundError(f"{S.AUDIT} yok: {self.audit_path} (önce `bidr audit`)")
        self.index = S.load_index(self.index_path)
        self.audit = S.load_audit(self.audit_path)
        src = onceki if onceki is not None else S.configured_previous(self.ws.root)
        self.previous, self.previous_name = S.load_previous(src) if src else ({}, None)
        self.notes = S.load_notes(Path(notes) if notes else self.ws.root / S.NOTES)
        self.cs = load_criteria()
        self.verify = verify
        self.docs = ({r["doc_id"]: r for r in read_jsonl(self.ws.documents) if r.get("doc_id")}
                     if self.ws.documents.exists() else {})
        self._texts: dict[str, str | None] = {}

    def doc_text(self, did: str) -> str | None:
        if did not in self._texts:
            p = self.ws.text_path(did) if did else None
            self._texts[did] = p.read_text(encoding="utf-8", errors="replace") if p and p.exists() else None
        return self._texts[did]

    def od(self, olcut: str) -> int:
        a = self.audit.get(olcut) or {}
        return int(a.get("od") or 1)

    def index_nos(self, olcut: str) -> set[str]:
        return {r["kanit_no"] for r in self.index.get(olcut, [])}

    def evidence(self, olcut: str, only: set[str] | None = None) -> list[dict]:
        """Kanıtlar, alıntı bağlamıyla (paket ve doğrulama için)."""
        out = []
        for r in self.index.get(olcut, []):
            if only is not None and r["kanit_no"] not in only:
                continue
            doc = self.docs.get(r.get("doc_id")) or {}
            out.append({"no": r["kanit_no"], "ad": r.get("ad", ""), "dosya": r.get("dosya", ""),
                        "doc_id": r.get("doc_id", ""), "od": r.get("od"), "yuvalar": r["yuvalar"],
                        "belge_turu": doc.get("doc_type_etiket") or doc.get("doc_type") or "",
                        "tarih": doc.get("tarih") or "",
                        "alintilar": S.evidence_context(self.doc_text(r.get("doc_id")), r["alintilar"],
                                                        self.verify)})
        return out

    def gaps(self, olcut: str) -> list[str]:
        """Eksik halkalar ve notlar (insan okur; metne değil `eksikler` alanına)."""
        a = self.audit.get(olcut) or {}
        out = []
        for e in a.get("eksik") or []:
            yv = "; ".join(y["yuva"] for y in e.get("yuvalar") or [])
            out.append(f"OD{a.get('sonraki_od')} için {HALKA.get(e['halka'], e['halka'])} kanıtı eksik: "
                       f"{e.get('gereken', '')}" + (f" (yuva: {yv})" if yv else ""))
        out += [str(n) for n in a.get("notlar") or []]
        return out

    def previous_text(self, olcut: str) -> str:
        p = self.previous.get(olcut) or {}
        if not p.get("aciklama"):
            return "yok"
        s = "Açıklamalar:\n" + p["aciklama"]
        if p.get("kanitlar"):
            s += "\n\nKanıtlar:\n" + p["kanitlar"]
        return s

    def notes_text(self, olcut: str) -> str:
        n = self.notes.get(olcut) or []
        return "\n".join(f"- {x}" for x in n) if n else "yok"


# -- istem girdileri ---------------------------------------------------------------------------

def render_criterion(cs, olcut: str, od: int | None = None) -> str:
    s = cs.get(olcut)
    lines = [f"{s.id} {s.title}"]
    if od is not None:
        lines.append(f"Önerilen OD: {od}")
    lines.append("Tanım:")
    lines += [f"- {d}" for d in s.description]
    lines.append("Rubrik:")
    lines += [f"{k}: {v}" for k, v in sorted(s.rubric.items())]
    return "\n".join(lines)


def render_od(a: dict, gaps: list[str]) -> str:
    z = a.get("zincir") or {}
    zz = ", ".join(f"{HALKA.get(k, k)}: {v.get('durum')} ({v.get('eslesme', 0)} eşleşme)" for k, v in z.items())
    lines = [f"Önerilen OD: {a.get('od', 1)} — metin bu düzeyin üstünde olgunluk iddia etmez.",
             f"PUKÖ zinciri: {a.get('zincir_kisa', '')}" + (f" ({zz})" if zz else "")]
    if gaps:
        lines.append("Eksikler ve notlar (metne yazılmaz; ayrı listelenir):")
        lines += [f"- {g}" for g in gaps]
    return "\n".join(lines)


def render_evidence(ev: list[dict], cs) -> str:
    blocks = []
    for e in ev:
        lines = [f"[{e['no']}] {e['ad']}"]
        info = ", ".join(x for x in (f"tür: {e['belge_turu']}" if e["belge_turu"] else "",
                                     f"tarih: {e['tarih']}" if e["tarih"] else "") if x)
        if info:
            lines.append(f"  {info}")
        for y in e["yuvalar"]:
            try:
                lines.append(f"  yuva {y}: {cs.get_slot(y).text}")
            except KeyError:
                lines.append(f"  yuva {y}")
        for i, q in enumerate(e["alintilar"], 1):
            lines.append(f"  alıntı {i}: «{q['alinti']}»")
            if q.get("baglam"):
                lines.append(f"  bağlam {i}: «{q['baglam']}»")
            elif q.get("alinti_belgede") is False:
                lines.append(f"  (alıntı belge metninde bulunamadı)")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def writing_questions() -> str:
    g = yaml.safe_load(GUIDE.read_text(encoding="utf-8"))
    for sec in g.get("sections") or []:
        if sec.get("section") == "Açıklama Metni Yazımı":
            return "\n".join(f"- {t}" for t in sec["text"][1:])
    return "-"


def hitap_for(profile: str | None, override: str | None = None) -> str:
    if override:
        return override
    return "Bölümümüzde" if (profile or "akademik_bolum") == "akademik_bolum" else "Birimimizde"


def write_inputs(src: Sources, olcut: str, hitap: str) -> tuple[dict, dict]:
    a = src.audit.get(olcut) or {"od": 1}
    gaps = src.gaps(olcut)
    ev = src.evidence(olcut)
    inputs = {"hitap": hitap, "olcut": render_criterion(src.cs, olcut),
              "od_bilgisi": render_od(a, gaps), "kanitlar": render_evidence(ev, src.cs),
              "onceki_metin": src.previous_text(olcut), "komisyon_bilgisi": src.notes_text(olcut),
              "yazim_sorulari": writing_questions()}
    meta = {"olcut": olcut, "od_onerisi": src.od(olcut), "eksikler": gaps,
            "kanitlar": [{"no": e["no"], "ad": e["ad"], "dosya": e["dosya"], "doc_id": e["doc_id"]} for e in ev],
            "komisyon": bool(src.notes.get(olcut)), "onceki": src.previous_name if olcut in src.previous else None}
    return inputs, meta


# -- kaynak yolları ----------------------------------------------------------------------------

SOURCES_FILE = "kaynaklar.json"      # work/write/: prepare'in kullandığı girdi yolları


def save_source_paths(src: "Sources", onceki, notes) -> None:
    d = work_dir(src.ws)
    d.mkdir(parents=True, exist_ok=True)
    rec = {"index": str(src.index_path), "audit": str(src.audit_path),
           "onceki": str(onceki) if onceki else None, "notlar": str(notes) if notes else None}
    (d / SOURCES_FILE).write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")


def source_paths(ws_root: Path, *, index=None, audit=None, onceki=None, notes=None) -> dict:
    """Komut satırında verilmeyen yollar son `write prepare`'in kaydından (yoksa varsayılan)."""
    f = work_dir(Workspace(Path(ws_root))) / SOURCES_FILE
    saved = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    return {"index": index or saved.get("index"), "audit": audit or saved.get("audit"),
            "onceki": onceki if onceki is not None else saved.get("onceki"),
            "notes": notes or saved.get("notlar")}


# -- prepare / apply ------------------------------------------------------------------------------

def _criteria(src: Sources, only: list[str] | None) -> tuple[list[str], list[str]]:
    """(kanıtı olan ölçütler, kanıtsız ölçütler) — `only` verilirse onunla sınırlı."""
    have = set(src.index)
    pool = set(only) if only else have | set(src.audit)
    yes = sorted((c for c in pool if c in have), key=id_key)
    no = sorted((c for c in pool if c not in have), key=id_key)
    return yes, no


def load_text(ws: Workspace, olcut: str) -> dict | None:
    p = texts_dir(ws) / f"{olcut}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def prepare(ws_root: Path, *, only: list[str] | None = None, redo: bool = False,
            index: Path | None = None, audit: Path | None = None, onceki=None, notes: Path | None = None,
            hitap: str | None = None, backend: Backend | None = None) -> dict:
    backend = backend or Backend()
    src = Sources(ws_root, index=index, audit=audit, onceki=onceki, notes=notes, verify=backend.verify_quote)
    unknown = [c for c in only or [] if c not in src.cs._index]
    if unknown:
        raise KeyError(f"bilinmeyen ölçüt: {', '.join(unknown)}")
    save_source_paths(src, onceki if onceki is not None else S.configured_previous(src.ws.root), notes)
    _, profile = S.unit_name(src.ws.root)
    h = hitap_for(profile, hitap)
    d = work_dir(src.ws)
    d.mkdir(parents=True, exist_ok=True)
    yes, no = _criteria(src, only)
    st = {"paket": 0, "yeni": 0, "zaten_tamam": 0, "kanitsiz": no, "onceki": src.previous_name,
          "onceki_olcut": sum(c in src.previous for c in yes)}
    for c in yes:
        inputs, meta = write_inputs(src, c, h)
        r = backend.render_task(TASK, inputs)
        t = load_text(src.ws, c)
        if (t and not redo and not only and (t.get("kaynak") or {}).get("istem_sha") == K.sha(r["prompt"])
                and str((t.get("kaynak") or {}).get("gorev_surumu")) == str(r["version"])):
            st["zaten_tamam"] += 1
            continue
        st["paket"] += 1
        st["yeni"] += K.write_pkg(d, c, r, meta, force=bool(redo and t))
    st["bekleyen"] = K.write_readme(d, task=TASK, version=task_version(), cmd="write", rule=RULE)
    st["klasor"] = str(d)
    return st


def _cited(paragraphs: list[str], onceki: str) -> list[str]:
    seen: list[str] = []
    for r in T.sentence_rows(paragraphs, onceki):
        for c in T.citations(r["metin"]):
            if c not in seen:
                seen.append(c)
    return sorted(seen, key=lambda x: int(x.split("_")[0]))


def text_sha(t: dict) -> str:
    """Metnin içerik özeti (durum ve doğrulama alanları hariç)."""
    body = json.dumps({"p": [p["metin"] for p in t.get("paragraflar") or []],
                       "o": t.get("onceki_yila_gore") or "", "od": t.get("od_onerisi")},
                      ensure_ascii=False, sort_keys=True)
    return K.sha(body)


def apply(ws_root: Path, *, model: str = "ajan:belirtilmemis", index: Path | None = None,
          audit: Path | None = None, backend: Backend | None = None) -> dict:
    backend = backend or Backend()
    sp = source_paths(ws_root, index=index, audit=audit)
    src = Sources(ws_root, index=sp["index"], audit=sp["audit"], onceki="", verify=backend.verify_quote)
    d = work_dir(src.ws)
    td = texts_dir(src.ws)
    st = {"islenen": 0, "degismedi": 0, "bekleyen": [], "gecersiz": {}, "eski": []}
    version = task_version()
    for p in K.pkg_paths(d):
        pkg = json.loads(p.read_text(encoding="utf-8"))
        c = pkg["olcut"]
        outp = d / pkg["cikti_dosyasi"]
        if not outp.exists():
            st["bekleyen"].append(c)
            continue
        meta = pkg["meta"]
        if str(pkg["surum"]) != version:
            st["eski"].append(c)
            continue
        cur = {(r["kanit_no"], r.get("doc_id", "")) for r in src.index.get(c, [])}
        if cur != {(k["no"], k["doc_id"]) for k in meta["kanitlar"]} or src.od(c) != meta["od_onerisi"]:
            st["eski"].append(c)              # kanıt listesi ya da OD paketten sonra değişti
            continue
        raw = outp.read_text(encoding="utf-8")
        out, errs = backend.validate_output(TASK, raw)
        if out is None:
            st["gecersiz"][c] = errs[:5]
            continue
        paras = [x["metin"].strip() for x in out["paragraflar"]]
        onceki = (out.get("onceki_yila_gore") or "").strip()
        issues = T.check_text(paras, onceki, index_nos=src.index_nos(c), od=meta["od_onerisi"],
                              komisyon=meta.get("komisyon", False))
        if issues:
            st["gecersiz"][c] = [f"{i['yer']} {i['kod']}: {i['ayrinti']}" for i in issues]
            continue
        cited = _cited(paras, onceki)
        byno = {k["no"]: k for k in meta["kanitlar"]}
        rec = {"olcut": c, "od_onerisi": meta["od_onerisi"], "durum": "taslak",
               "paragraflar": [{"metin": m, "atiflar": _cited([m], "")} for m in paras],
               "kanitlar": [{"no": n, "ad": byno[n]["ad"], "dosya": byno[n]["dosya"]} for n in cited],
               "eksikler": meta["eksikler"], "onceki_yila_gore": onceki,
               "kaynak": {"model": model, "gorev_surumu": str(pkg["surum"]), "istem_sha": pkg["istem_sha"],
                          "cevap_sha": K.sha(raw), "onceki": meta.get("onceki"), "zaman": K.now()}}
        old = load_text(src.ws, c)
        if old and text_sha(old) == text_sha(rec) and (old.get("kaynak") or {}).get("istem_sha") == pkg["istem_sha"]:
            st["degismedi"] += 1
            continue
        td.mkdir(parents=True, exist_ok=True)
        (td / f"{c}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        st["islenen"] += 1
    K.write_invalid(d, TASK, st["gecersiz"])
    return st
