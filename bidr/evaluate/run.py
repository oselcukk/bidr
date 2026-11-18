"""Bölmeler, sızıntı denetimi ve taban çizgisi tabloları."""
from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from bidr.candidates.data import Doc, load
from bidr.candidates.model import Model
from bidr.criteria.loader import load_criteria
from bidr.criteria.profiles import excluded_types, load_profile

from .metrics import KS, collapse, doc_metrics, mean

SYSTEMS = {
    "bm25": ("bm25",),
    "yuva": ("yuva",),
    "knn": ("knn",),
    "tur": ("tur",),
    "oncel": ("oncel",),
    # eski birleşik (tür sinyalsiz = taban çizgisi koşulu) ve türlü hâli
    "birlesik_eski": ("bm25", "knn", "oncel"),
    "birlesik": ("bm25", "knn", "tur", "oncel"),
    # yeni: ölçüt-metni BM25 yerine yuva düzeyi BM25
    "birlesik_yuva": ("yuva", "knn", "oncel"),
    "birlesik_yuva_tur": ("yuva", "knn", "tur", "oncel"),
    "birlesik_hepsi": ("bm25", "yuva", "knn", "tur", "oncel"),
}
SINGLE = ("bm25", "yuva", "knn", "tur")
LEVELS = ("alt", "ana")


# Yakın kopya eşiği: bir test belgesine ham terim sıklığı (TF) kosinüsü bu değer ya
# da üstü olan etiketli belge eğitimden atılır (aynı belgenin başka taraması/sürümü,
# imza sayfası farkı vb.). Birebir doc_id / metin özeti denetimine ektir.
NEAR_DUP = 0.9


class LeakageError(RuntimeError):
    pass


def _unit_tf(b: dict) -> dict[str, float]:
    n = math.sqrt(sum(v * v for v in b.values())) or 1.0
    return {t: v / n for t, v in b.items()}


def tf_cosine(a: dict, b: dict) -> float:
    """İki belge torbası (`Doc.bag`: kökler) arasında ham TF kosinüsü (IDF'siz;
    eğitim derlemine bağlı olmasın diye)."""
    ua, ub = _unit_tf(a), _unit_tf(b)
    if len(ua) > len(ub):
        ua, ub = ub, ua
    return sum(x * ub.get(t, 0.0) for t, x in ua.items())


def near_duplicates(train: list[Doc], test: list[Doc], thr: float) -> dict[str, tuple[str, float]]:
    """Eğitim belgesi -> (en benzer test belgesi, kosinüs), yalnız kosinüs >= thr olanlar."""
    tv = [(d.doc_id, _unit_tf(d.bag)) for d in test if d.bag]
    inv: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for j, (_, v) in enumerate(tv):
        for t, x in v.items():
            inv[t].append((j, x))
    out: dict[str, tuple[str, float]] = {}
    for d in train:
        if not d.bag:
            continue
        acc: dict[int, float] = defaultdict(float)
        for t, x in _unit_tf(d.bag).items():
            for j, y in inv.get(t, ()):
                acc[j] += x * y
        if not acc:
            continue
        j, s = max(acc.items(), key=lambda kv: (kv[1], -kv[0]))
        if s >= thr - 1e-9:
            out[d.doc_id] = (tv[j][0], round(min(s, 1.0), 4))
    return out


@dataclass
class Split:
    name: str
    train: list[Doc]
    test: list[Doc]           # etiketli, ölçüme giren
    skipped: list[Doc]        # etiketli ama metni boş/kısa/yok
    dropped_train: int        # test içeriğiyle çakıştığı için eğitimden atılan
    excluded_test: int = 0    # öz-referans türü yüzünden ölçümden çıkan etiketli test belgesi
    excluded_train: int = 0   # aynı nedenle eğitimden çıkan etiketli belge
    near_dup: float | None = None   # yakın kopya eşiği (None: denetim kapalı)
    # eğitimden atılan yakın kopyalar: (eğitim doc_id, test doc_id, kosinüs)
    near_dropped: tuple[tuple[str, str, float], ...] = ()

    def leakage(self) -> dict:
        tr_id = {d.doc_id for d in self.train}
        te_id = {d.doc_id for d in self.test + self.skipped}
        # boş metinlerin özeti içerik kimliği sayılmaz (Doc.keys)
        tr_tx = {k for d in self.train for k in d.keys if k.startswith("tx:")}
        te_tx = {k for d in self.test + self.skipped for k in d.keys if k.startswith("tx:")}
        return {"egitim": len(self.train), "test": len(self.test),
                "doc_id_kesisim": len(tr_id & te_id), "metin_ozeti_kesisim": len(tr_tx & te_tx),
                "egitimden_atilan_ortak_icerik": self.dropped_train,
                "yakin_kopya_esigi": self.near_dup,
                "egitimden_atilan_yakin_kopya": len(self.near_dropped),
                "haric_tur_test": self.excluded_test, "haric_tur_egitim": self.excluded_train}


def _is_ex(d: Doc, ex: frozenset) -> bool:
    return bool(d.doc_type) and d.doc_type in ex


def _make(name: str, train_pool: list[Doc], test_pool: list[Doc], valid: set[str],
          ex: frozenset = frozenset(), near_dup: float | None = NEAR_DUP) -> Split:
    lab_all = [d for d in test_pool if any(g in valid for g in d.gold)]
    lab = [d for d in lab_all if not _is_ex(d, ex)]
    test = [d for d in lab if d.usable]
    skipped = [d for d in lab if not d.usable]
    # sızıntı anahtarları dışlanan belgeleri de kapsar (eğitime kopyası girmesin)
    keys = set().union(*(d.keys for d in lab_all)) if lab_all else set()
    pool = [d for d in train_pool if d.labeled and d.usable and not (d.keys & keys)]
    dropped = sum(1 for d in train_pool if d.labeled and (d.keys & keys))
    near: dict[str, tuple[str, float]] = {}
    if near_dup:
        near = near_duplicates(pool, lab_all, near_dup)
        pool = [d for d in pool if d.doc_id not in near]
    train = [d for d in pool if not _is_ex(d, ex)]
    ex_train = len(pool) - len(train)
    sp = Split(name, train, test, skipped, dropped, len(lab_all) - len(lab), ex_train,
               near_dup or None,
               tuple(sorted(((k, t, c) for k, (t, c) in near.items()), key=lambda r: (-r[2], r[0]))))
    lk = sp.leakage()
    if lk["doc_id_kesisim"] or lk["metin_ozeti_kesisim"]:
        raise LeakageError(f"{name}: eğitim/test kesişimi {lk}")
    return sp


def louo_splits(docs: list[Doc], valid: set[str], units: list[str] | None = None,
                ex: frozenset = frozenset(), near_dup: float | None = NEAR_DUP) -> list[Split]:
    lab = [d for d in docs if d.labeled]
    units = units or sorted({u for d in lab for u in d.units})
    out = []
    for u in units:
        test = [d for d in lab if u in d.units]
        rest = [d for d in lab if u not in d.units]
        out.append(_make(f"louo:{u}", rest, test, valid, ex, near_dup))
    return out


def transfer_split(train_docs: list[Doc], test_docs: list[Doc], valid: set[str], name: str,
                   ex: frozenset = frozenset(), near_dup: float | None = NEAR_DUP) -> Split:
    return _make(name, train_docs, test_docs, valid, ex, near_dup)


def evaluate_split(sp: Split, cs, systems=SYSTEMS, allowed: frozenset | None = None) -> dict:
    valid = {s.id for s in cs.sub_criteria}
    model = Model(cs, allowed=allowed).fit(sp.train)
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
        "yakin_kopyalar": [{"egitim": a, "test": b, "kosinus": c} for a, b, c in sp.near_dropped],
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
            off = "etkin_sinyal_belge" in r and s in SINGLE and \
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
           "| bölme | eğitim | test | doc_id ∩ | metin özeti ∩ | eğitimden atılan ortak içerik "
           "| eğitimden atılan yakın kopya | öz-referans türü: test / eğitim dışı |",
           "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in results:
        if "sizinti" in r:
            z = r["sizinti"]
            nd = z.get("egitimden_atilan_yakin_kopya", 0) if z.get("yakin_kopya_esigi") else "kapalı"
            out.append(f"| {r['bolme']} | {z['egitim']} | {z['test']} | {z['doc_id_kesisim']} | "
                       f"{z['metin_ozeti_kesisim']} | {z['egitimden_atilan_ortak_icerik']} | {nd} | "
                       f"{z.get('haric_tur_test', 0)} / {z.get('haric_tur_egitim', 0)} |")
    thr = meta.get("yakin_kopya_esigi")
    out += ["", (f"Yakın kopya: test belgesine ham TF kosinüsü >= {thr} olan etiketli belge "
                 "eğitimden atılır (birebir doc_id / metin özeti denetimine ek)."
                 if thr else "Yakın kopya denetimi kapalı.")]
    pairs = [(r["bolme"], p) for r in results for p in r.get("yakin_kopyalar", [])]
    if pairs:
        out += ["", "| bölme | eğitimden atılan | en benzer test belgesi | kosinüs |", "|---|---|---|---:|"]
        out += [f"| {b} | `{p['egitim']}` | `{p['test']}` | {p['kosinus']:.3f} |" for b, p in pairs]
    out += ["", "Sistemler: " + "; ".join(f"`{k}` = {'+'.join(v)}" for k, v in SYSTEMS.items()
                                          if len(v) > 1) + "."]
    n_alt = meta.get("aday_olcut", 46)
    for lv, title in (("alt", f"Alt ölçüt ({n_alt} aday)"), ("ana", "Ana ölçüt")):
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
             cs=None, *, profile: str | None = None,
             exclude_types: frozenset | None = None,
             near_dup: float | None = NEAR_DUP) -> tuple[list[dict], dict]:
    cs = cs or load_criteria()
    valid = {s.id for s in cs.sub_criteria}
    ex = excluded_types() if exclude_types is None else frozenset(exclude_types)
    prof = load_profile(profile) if profile else None
    allowed = frozenset(prof.allowed(cs)) if prof else None
    cache: dict[Path, list[Doc]] = {}

    def docs(p: Path) -> list[Doc]:
        p = Path(p).expanduser().resolve()
        if p not in cache:
            cache[p] = load(p)
        return cache[p]

    results = []
    for ws in louo:
        res = [evaluate_split(sp, cs, allowed=allowed) for sp in louo_splits(docs(ws), valid, units, ex, near_dup)]
        results += finalize(res, pooled_name=f"louo:{Path(ws).name}:havuz")
    for tr, te in transfers:
        sp = transfer_split(docs(tr), docs(te), valid, f"{Path(tr).name}→{Path(te).name}", ex, near_dup)
        results += finalize([evaluate_split(sp, cs, allowed=allowed)])
    m = Model(cs, allowed=allowed)
    meta = {"agirliklar": m.weights, "knn_m": m.m, "tur_alpha": m.alpha,
            "sistemler": {k: list(v) for k, v in SYSTEMS.items()},
            "haric_turler": sorted(ex), "profil": prof.name if prof else None,
            "aday_olcut": len(m.out_ids), "yakin_kopya_esigi": near_dup or None,
            "metin_esigi_karakter": 200, "kok_uzunlugu": 5,
            "olcut_surumu": cs.meta.get("source_sha256")}
    return results, meta
