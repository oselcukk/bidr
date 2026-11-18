"""Bölmeler, sızıntı denetimi ve taban çizgisi tabloları."""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from bidr.candidates.data import Doc, load
from bidr.candidates.model import Model
from bidr.criteria.loader import load_criteria

from .metrics import KS, collapse, doc_metrics, mean

SYSTEMS = {
    "bm25": ("bm25",),
    "knn": ("knn",),
    "tur": ("tur",),
    "oncel": ("oncel",),
    "birlesik": ("bm25", "knn", "tur", "oncel"),
}
LEVELS = ("alt", "ana")


class LeakageError(RuntimeError):
    pass


@dataclass
class Split:
    name: str
    train: list[Doc]
    test: list[Doc]           # etiketli, ölçüme giren
    skipped: list[Doc]        # etiketli ama metni boş/kısa/yok
    dropped_train: int        # test içeriğiyle çakıştığı için eğitimden atılan

    def leakage(self) -> dict:
        tr_id = {d.doc_id for d in self.train}
        te_id = {d.doc_id for d in self.test + self.skipped}
        # boş metinlerin özeti içerik kimliği sayılmaz (Doc.keys)
        tr_tx = {k for d in self.train for k in d.keys if k.startswith("tx:")}
        te_tx = {k for d in self.test + self.skipped for k in d.keys if k.startswith("tx:")}
        return {"egitim": len(self.train), "test": len(self.test),
                "doc_id_kesisim": len(tr_id & te_id), "metin_ozeti_kesisim": len(tr_tx & te_tx),
                "egitimden_atilan_ortak_icerik": self.dropped_train}


def _make(name: str, train_pool: list[Doc], test_pool: list[Doc], valid: set[str]) -> Split:
    lab = [d for d in test_pool if any(g in valid for g in d.gold)]
    test = [d for d in lab if d.usable]
    skipped = [d for d in lab if not d.usable]
    keys = set().union(*(d.keys for d in lab)) if lab else set()
    train = [d for d in train_pool if d.labeled and d.usable and not (d.keys & keys)]
    dropped = sum(1 for d in train_pool if d.labeled and (d.keys & keys))
    sp = Split(name, train, test, skipped, dropped)
    lk = sp.leakage()
    if lk["doc_id_kesisim"] or lk["metin_ozeti_kesisim"]:
        raise LeakageError(f"{name}: eğitim/test kesişimi {lk}")
    return sp


def louo_splits(docs: list[Doc], valid: set[str], units: list[str] | None = None) -> list[Split]:
    lab = [d for d in docs if d.labeled]
    units = units or sorted({u for d in lab for u in d.units})
    out = []
    for u in units:
        test = [d for d in lab if u in d.units]
        rest = [d for d in lab if u not in d.units]
        out.append(_make(f"louo:{u}", rest, test, valid))
    return out


def transfer_split(train_docs: list[Doc], test_docs: list[Doc], valid: set[str], name: str) -> Split:
    return _make(name, train_docs, test_docs, valid)


def evaluate_split(sp: Split, cs, systems=SYSTEMS) -> dict:
    valid = {s.id for s in cs.sub_criteria}
    model = Model(cs).fit(sp.train)
    per = {s: {lv: [] for lv in LEVELS} for s in systems}
    active = defaultdict(int)
    per_crit = defaultdict(lambda: [0, 0])   # birleşik, alt düzey R@10: [bulunan, toplam]
    for d in sp.test:
        gold = {g for g in d.gold if g in valid}
        raw = model.signal_scores(d)
        for s, sc in raw.items():
            if any(v > 0 for v in sc.values()):
                active[s] += 1
        for name, sig in systems.items():
            rows, _ = model.rank(d, sig)
            ranking = [r[0] for r in rows]
            per[name]["alt"].append(doc_metrics(ranking, gold))
            per[name]["ana"].append(doc_metrics(collapse(ranking), {g.rsplit(".", 1)[0] for g in gold}))
            if name == "birlesik":
                top = set(ranking[:10])
                for g in gold:
                    per_crit[g][0] += g in top
                    per_crit[g][1] += 1
    return {
        "bolme": sp.name,
        "sizinti": sp.leakage(),
        "olcume_girmeyen": [{"doc_id": d.doc_id, "durum": d.durum, "chars": d.chars} for d in sp.skipped],
        "etkin_sinyal_belge": dict(active),
        "_per": per,
        "olcut_R@10_birlesik": {g: {"bulunan": a, "toplam": b} for g, (a, b) in sorted(per_crit.items())},
    }


def finalize(results: list[dict], pooled_name: str | None = None) -> list[dict]:
    """Belge düzeyi ölçüleri ortalar; istenirse LOUO katlarını havuzlar."""
    out = []
    pool = defaultdict(lambda: defaultdict(list))
    pool_active: dict[str, int] = defaultdict(int)
    for r in results:
        per = r.pop("_per")
        r["olcu"] = {s: {lv: mean(v) for lv, v in d.items()} for s, d in per.items()}
        r["n"] = len(next(iter(per.values()))["alt"]) if per else 0
        if pooled_name and r["bolme"].startswith("louo:"):
            for s_, c in r.get("etkin_sinyal_belge", {}).items():
                pool_active[s_] += c
            for s, d in per.items():
                for lv, v in d.items():
                    pool[s][lv].extend(v)
        out.append(r)
    if pooled_name and pool:
        n = len(next(iter(pool.values()))["alt"])
        out.append({"bolme": pooled_name, "n": n, "etkin_sinyal_belge": dict(pool_active),
                    "olcu": {s: {lv: mean(v) for lv, v in d.items()} for s, d in pool.items()}})
    return out


def table_md(results: list[dict], level: str) -> str:
    cols = [f"R@{k}" for k in KS] + ["H@5", "H@10", "MRR"]
    lines = [f"| bölme | n | sinyal | " + " | ".join(cols) + " |",
             "|---|---:|---|" + "---:|" * len(cols)]
    for r in results:
        for s, d in r["olcu"].items():
            m = d[level]
            off = "etkin_sinyal_belge" in r and s in ("bm25", "knn", "tur") and \
                not r["etkin_sinyal_belge"].get(s)
            vals = ["kapalı"] * len(cols) if off else [f"{m[c]:.3f}" for c in cols]
            lines.append(f"| {r['bolme']} | {r['n']} | {s} | " + " | ".join(vals) + " |")
    return "\n".join(lines)


def report_md(name: str, results: list[dict], meta: dict) -> str:
    out = [f"# Aday ölçüt değerlendirmesi: {name}", "",
           "Özellikler yalnız `text/` içeriği (+ varsa `documents.jsonl` doc_type). "
           "Dosya adı/yol/`iz` kullanılmaz. Etiketsiz belgeler ölçüme girmez; "
           "boş/kısa metinli etiketli belgeler ayrı listelenir.", "",
           "Ölçüler: R@k = doğru ölçütlerin ilk k'daki oranı (belge ortalaması); "
           "H@k = en az bir doğru ilk k'da; MRR = ilk doğrunun ters sırası. "
           "`kapalı` = sinyal bu bölmede hiçbir test belgesi için veri üretmedi.", "",
           "## Sızıntı denetimi", "",
           "| bölme | eğitim | test | doc_id ∩ | metin özeti ∩ | eğitimden atılan ortak içerik |",
           "|---|---:|---:|---:|---:|---:|"]
    for r in results:
        if "sizinti" in r:
            z = r["sizinti"]
            out.append(f"| {r['bolme']} | {z['egitim']} | {z['test']} | {z['doc_id_kesisim']} | "
                       f"{z['metin_ozeti_kesisim']} | {z['egitimden_atilan_ortak_icerik']} |")
    for lv, title in (("alt", "Alt ölçüt (46)"), ("ana", "Ana ölçüt (14)")):
        out += ["", f"## {title}", "", table_md(results, lv)]
    out += ["", "## Ölçüme girmeyen etiketli belgeler (boş / kısa / metin yok)", ""]
    seen = set()
    for r in results:
        for s in r.get("olcume_girmeyen", []):
            if s["doc_id"] not in seen:
                seen.add(s["doc_id"])
                out.append(f"- `{s['doc_id']}` {s['durum']} ({s['chars']} karakter) — {r['bolme']}")
    if not seen:
        out.append("- yok")
    out += ["", "## Ayarlar", "", "```json", json.dumps(meta, ensure_ascii=False, indent=1), "```", ""]
    return "\n".join(out)


def evaluate(louo: list[Path], transfers: list[tuple[Path, Path]], units: list[str] | None = None,
             cs=None) -> tuple[list[dict], dict]:
    cs = cs or load_criteria()
    valid = {s.id for s in cs.sub_criteria}
    cache: dict[Path, list[Doc]] = {}

    def docs(p: Path) -> list[Doc]:
        p = Path(p).expanduser().resolve()
        if p not in cache:
            cache[p] = load(p)
        return cache[p]

    results = []
    for ws in louo:
        res = [evaluate_split(sp, cs) for sp in louo_splits(docs(ws), valid, units)]
        results += finalize(res, pooled_name=f"louo:{Path(ws).name}:havuz")
    for tr, te in transfers:
        sp = transfer_split(docs(tr), docs(te), valid, f"{Path(tr).name}→{Path(te).name}")
        results += finalize([evaluate_split(sp, cs)])
    m = Model(cs)
    meta = {"agirliklar": m.weights, "knn_m": m.m, "tur_alpha": m.alpha,
            "metin_esigi_karakter": 200, "kok_uzunlugu": 5,
            "olcut_surumu": cs.meta.get("source_sha256")}
    return results, meta
