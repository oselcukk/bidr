"""Aday ölçüt sinyalleri ve birleştirme.

Sinyaller (her biri 46 alt ölçüt için bir puan sözlüğü verir):
  bm25   belge metni ↔ ölçüt metni (başlık ×3, üst ölçüt başlığı, tanım, rubrik,
         örnek kanıtlar); ölçütler "belge", incelenen belge "sorgu" (BM25, k3 ile
         sorgu terim sıklığı doyumu). IDF yalnız ölçüt derleminden.
  yuva   belge metni ↔ her kanıt yuvası ayrı (yuva metni + alt ölçüt başlığı;
         dipnot yuvaları hariç). Ölçüt puanı = yuvalarının en yüksek puanı.
         IDF yalnız yuva derleminden.
  knn    etiketli eğitim belgelerine TF-IDF kosinüs en yakın m komşu; komşunun
         ölçütleri benzerlikle ağırlıklı toplanır. IDF yalnız eğitim belgelerinden.
  tur    documents.jsonl doc_type → ölçüt dağılımı (eğitimden, önsel ile düzeltilmiş).
         Belgenin türü yoksa ya da eğitimde türlü belge yoksa kapalı.
  oncel  eğitimdeki ölçüt sıklığı (taban çizgisi; birleşikte eşitlik bozucu).

Birleşik: her sinyal en yüksek puanına bölünür (0..1), ağırlıkla toplanır.
Varsayılan birleşik `DEFAULT_COMBO` (eski dört sinyal); `yuva` istenirse
`signals` ile katılır.

Profil (`allowed`): yalnız izin verilen alt ölçütler sıralamaya girer; sinyaller
yine 46 ölçüt üzerinden hesaplanır (eğitim ve IDF değişmez).
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from bidr.criteria.model import CriteriaSet, id_key

from .data import Doc
from .text import bag

SIGNALS = ("bm25", "yuva", "knn", "tur", "oncel")
DEFAULT_COMBO = ("bm25", "yuva", "knn", "tur", "oncel")
DEFAULT_WEIGHTS = {"bm25": 1.0, "yuva": 1.0, "knn": 1.0, "tur": 0.5, "oncel": 0.05}


def criterion_text(cs: CriteriaSet, sid: str) -> str:
    s = cs.get(sid)
    parent = cs.get(s.parent)
    parts = [s.title] * 3 + [parent.title]
    parts += list(s.description)
    parts += [v for _, v in sorted(s.rubric.items())]
    parts += list(s.example_evidence)
    return "\n".join(parts)


def slot_text(cs: CriteriaSet, slot) -> str:
    return slot.text + "\n" + cs.get(slot.criterion).title


class BM25:
    """Ölçüt (ya da yuva) metinleri "belge", incelenen belge "sorgu"."""

    def __init__(self, cs: CriteriaSet, k1: float = 1.2, b: float = 0.75, k3: float = 8.0,
                 texts: dict[str, str] | None = None):
        if texts is None:
            texts = {s.id: criterion_text(cs, s.id) for s in cs.sub_criteria}
        self.ids = list(texts)
        self.tf = {sid: bag(t) for sid, t in texts.items()}
        self.len = {sid: sum(c.values()) for sid, c in self.tf.items()}
        self.avg = sum(self.len.values()) / len(self.ids)
        df = Counter()
        for c in self.tf.values():
            df.update(c.keys())
        n = len(self.ids)
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}
        self.k1, self.b, self.k3 = k1, b, k3

    def score(self, doc_bag: dict) -> dict[str, float]:
        out = dict.fromkeys(self.ids, 0.0)
        q = {t: f for t, f in doc_bag.items() if t in self.idf}
        if not q:
            return out
        for sid in self.ids:
            tf = self.tf[sid]
            norm = self.k1 * (1 - self.b + self.b * self.len[sid] / self.avg)
            s = 0.0
            for t, qf in q.items():
                f = tf.get(t)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (f + norm) * \
                        qf * (self.k3 + 1) / (qf + self.k3)
            out[sid] = s
        return out


class SlotBM25:
    """Yuva düzeyi BM25: her kanıt yuvası ayrı belge; ölçüt puanı = en iyi yuvası."""

    def __init__(self, cs: CriteriaSet, **kw):
        slots = cs.slots(include_footnotes=False)
        self.crit = {x.id: x.criterion for x in slots}
        self.criteria = [s.id for s in cs.sub_criteria]
        self.bm = BM25(cs, texts={x.id: slot_text(cs, x) for x in slots}, **kw)

    def slot_scores(self, doc_bag: dict) -> dict[str, float]:
        return self.bm.score(doc_bag)

    def score(self, doc_bag: dict, slot_sc: dict[str, float] | None = None) -> dict[str, float]:
        sc = slot_sc if slot_sc is not None else self.slot_scores(doc_bag)
        out = dict.fromkeys(self.criteria, 0.0)
        for sid, v in sc.items():
            c = self.crit[sid]
            if v > out[c]:
                out[c] = v
        return out


def _tfidf(b: dict, idf: dict) -> dict[str, float]:
    v = {t: (1 + math.log(f)) * idf[t] for t, f in b.items() if t in idf}
    n = math.sqrt(sum(x * x for x in v.values())) or 1.0
    return {t: x / n for t, x in v.items()}


@dataclass
class Model:
    cs: CriteriaSet
    m: int = 10
    weights: dict = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    alpha: float = 2.0          # tür dağılımı için önsel ağırlığı
    allowed: frozenset | None = None        # birim profili süzgeci (None = 46'nın hepsi)
    excluded_types: frozenset = frozenset()  # öz-referans türler: eğitime girmez, aday almaz

    def __post_init__(self):
        self.ids = [s.id for s in self.cs.sub_criteria]
        self.out_ids = [i for i in self.ids if self.allowed is None or i in self.allowed]
        self.bm25 = BM25(self.cs)
        self.slots = SlotBM25(self.cs)
        self.train: list[Doc] = []

    def excluded(self, doc: Doc) -> bool:
        return bool(doc.doc_type) and doc.doc_type in self.excluded_types

    # -- eğitim ---------------------------------------------------------------
    def fit(self, train: list[Doc]) -> "Model":
        """Yalnız etiketli ve kullanılabilir metinli belgeler alınır."""
        valid = set(self.ids)
        self.train = [d for d in train if d.labeled and d.usable and not self.excluded(d)
                      and any(g in valid for g in d.gold)]
        df = Counter()
        for d in self.train:
            df.update(d.bag.keys())
        n = len(self.train)
        self.idf = {t: math.log((n + 1) / (c + 0.5)) for t, c in df.items()} if n else {}
        self.vecs = [_tfidf(d.bag, self.idf) for d in self.train]
        self.prior = Counter(g for d in self.train for g in d.gold if g in valid)
        self.type_counts: dict[str, Counter] = defaultdict(Counter)
        for d in self.train:
            if d.doc_type:
                self.type_counts[d.doc_type].update(g for g in d.gold if g in valid)
        return self

    def train_keys(self) -> set[str]:
        return set().union(*(d.keys for d in self.train)) if self.train else set()

    # -- sinyaller --------------------------------------------------------------
    def _excluded(self, doc: Doc) -> list[bool]:
        k = doc.keys
        return [bool(t.keys & k) for t in self.train]

    def _prior(self, excl: list[bool]) -> Counter:
        p = Counter(self.prior)
        for t, x in zip(self.train, excl):
            if x:
                p.subtract(g for g in t.gold if g in p)
        return p

    def signal_scores(self, doc: Doc) -> dict[str, dict[str, float]]:
        """Her sinyal için ham puanlar. Eğitimde aynı içerik varsa (doc_id veya
        metin özeti) o belge komşu/sayım olarak kullanılmaz."""
        excl = self._excluded(doc)
        out = {"bm25": self.bm25.score(doc.bag) if doc.bag else dict.fromkeys(self.ids, 0.0)}
        out["yuva"] = self.slots.score(doc.bag) if doc.bag else dict.fromkeys(self.ids, 0.0)

        knn = dict.fromkeys(self.ids, 0.0)
        if self.train and doc.bag:
            q = _tfidf(doc.bag, self.idf)
            sims = []
            for i, (t, v) in enumerate(zip(self.train, self.vecs)):
                if excl[i]:
                    continue
                s = sum(x * v.get(w, 0.0) for w, x in q.items())
                if s > 0:
                    sims.append((s, i))
            sims.sort(reverse=True)
            for s, i in sims[: self.m]:
                for g in self.train[i].gold:
                    if g in knn:
                        knn[g] += s
        out["knn"] = knn

        prior = self._prior(excl)
        total = sum(max(v, 0) for v in prior.values())
        pr = {sid: (max(prior.get(sid, 0), 0) + 0.5) / (total + 0.5 * len(self.ids))
              for sid in self.ids}
        out["oncel"] = pr if self.train else dict.fromkeys(self.ids, 0.0)

        tur = dict.fromkeys(self.ids, 0.0)
        if doc.doc_type and doc.doc_type in self.type_counts:
            tc = Counter(self.type_counts[doc.doc_type])
            for t, x in zip(self.train, excl):
                if x and t.doc_type == doc.doc_type:
                    tc.subtract(g for g in t.gold if g in tc)
            n = sum(max(v, 0) for v in tc.values())
            if n > 0:
                tur = {sid: (max(tc.get(sid, 0), 0) + self.alpha * pr[sid]) / (n + self.alpha)
                       for sid in self.ids}
        out["tur"] = tur
        if len(self.out_ids) != len(self.ids):
            out = {k: {sid: v[sid] for sid in self.out_ids} for k, v in out.items()}
        return out

    def best_slots(self, doc: Doc, n: int = 3) -> list[tuple[str, float]]:
        """Belgenin en iyi eşleşen kanıt yuvaları (profil süzgecine uyan), azalan puan."""
        if not doc.bag:
            return []
        sc = self.slots.slot_scores(doc.bag)
        ok = set(self.out_ids)
        rows = [(k, v) for k, v in sc.items() if v > 0 and self.slots.crit[k] in ok]
        rows.sort(key=lambda r: (-r[1], id_key(r[0].split("/")[0]), int(r[0].split("/")[1])))
        return rows[:n]

    def criterion_slots(self, doc: Doc) -> dict[str, list[tuple[str, float]]]:
        """Ölçüt başına yuvaları puan sırasıyla (yalnız > 0)."""
        out: dict[str, list] = {}
        if not doc.bag:
            return out
        for k, v in self.slots.slot_scores(doc.bag).items():
            if v > 0:
                out.setdefault(self.slots.crit[k], []).append((k, v))
        for v in out.values():
            v.sort(key=lambda r: (-r[1], int(r[0].split("/")[1])))
        return out

    def rank(self, doc: Doc, signals: tuple[str, ...] | None = None):
        """(ölçüt, birleşik puan, sinyal başına normalize puan) listesi, azalan."""
        raw = self.signal_scores(doc)
        norm = {}
        for name, sc in raw.items():
            mx = max(sc.values()) if sc else 0.0
            norm[name] = {k: (v / mx if mx > 0 else 0.0) for k, v in sc.items()}
        use = signals or DEFAULT_COMBO
        rows = []
        for sid in self.out_ids:
            total = sum(self.weights.get(s, 0.0) * norm[s][sid] for s in use) \
                if len(use) > 1 else norm[use[0]][sid]
            rows.append((sid, total, {s: norm[s][sid] for s in raw}))
        # eşitlikte deterministik: kimlik sırası
        rows.sort(key=lambda r: (-r[1], id_key(r[0])))
        return rows, raw


def active_signals(model: Model, doc: Doc, raw: dict) -> list[str]:
    return [s for s in SIGNALS if any(v > 0 for v in raw[s].values())]
