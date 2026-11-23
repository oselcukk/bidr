"""İkinci (genişletilmiş) arama: kanıtsız ya da zayıf ölçütler için arşivin tamamında
ters yönlü arama (K12).

İlk geçiş (`bidr candidates`) belgeyi sorgu, ölçütleri derlem alır: belge başına ilk k
ölçüt. Seyrek ölçütün uygun belgesi, o belgenin ilk k'sına giremezse hiç ince karara
gitmez. İkinci arama yönü çevirir: ölçüt sorgu, işlenmiş arşivin bütün belgeleri derlem.

Sorgu = ölçüt metni (başlık ×3, üst ölçüt başlığı, tanım, rubrik, örnek kanıt maddeleri =
yuvalar; `model.criterion_text`) + eşanlamlı genişletme (`synonyms.expand`). Puan iki
sinyalin (belgeler arasında en yüksek puana bölünmüş) toplamı:
  sorgu  BM25: arşiv belgeleri "belge", genişletilmiş ölçüt sorgusu "sorgu"; IDF arşivden.
  yuva   ilk geçişin yuva sinyali (`SlotBM25`): belgenin bu ölçütün en iyi yuvasına puanı.
Eğitim/etiket sinyali (knn, tür, öncel) kullanılmaz: girdiler yalnız `text/`, ölçüt verisi,
`decisions.jsonl`, `audit-olcutler.json` (bu yılın denetimi). `labels.jsonl` (geçmiş rapor
etiketleri, kanıt adları), yol ve dosya adları okunmaz.

Seçim: belge, ölçüt için ilk geçişte ince karara aday OLMAMIŞ olmalı (kaydın `adaylar` ve
kaba `secilen` listesinde yok, o ölçütle hiç eşleşmesi yok), ince kararı sonuçlanmış olmalı;
öz-referans türü, başka birime ait sayılan (insan kararı öncelikli) ve kararı devralan
mükerrer belge seçilmez. Ölçüt başına en iyi `n` belge.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from bidr.common import Workspace, read_jsonl
from bidr.criteria.model import CriteriaSet, id_key

from .dil import expand_bag, query_terms
from .model import BM25, SlotBM25, criterion_text
from .synonyms import expand
from .text import bag

AUDIT_JSON = "audit-olcutler.json"
OD_ESIK = 2          # bu düzey ve altındaki ölçüt zayıf (OD ≤ 2)
N_BELGE = 5          # ölçüt başına ikinci aramanın ekleyeceği en çok belge
WEIGHTS = {"sorgu": 1.0, "yuva": 1.0}
NEDENLER = ("kanitsiz", "dusuk_od", "yalniz_kurum_geneli", "bolum_kaniti_yok")


def load_audit(path: Path) -> dict[str, dict] | None:
    """audit-olcutler.json → {ölçüt: özet}; yoksa ya da okunamıyorsa None."""
    if not path.exists():
        return None
    try:
        js = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return {c["olcut"]: c for c in js.get("olcutler") or [] if c.get("olcut")}


def unit_own(view: dict, doc: dict | None) -> bool:
    """Belge birimin kendi kanıtı mı: birim ilişkisi kurum/fakülte geneli ya da başka birim
    değil, türü kurum geneli düzenleme değil (audit'in kurum geneli kuralıyla aynı; insan birim
    kararı `unit_view` ile öncelikli)."""
    from bidr.audit.rules import KARAR_TURLERI, KURUM_GENELI_TURLER
    from bidr.decide.run import BIRIM_DISI, GENEL_ILISKI, record_unit_relation

    rel = record_unit_relation(view)
    dtype = (doc or {}).get("doc_type") or ""
    tur_kg = dtype in KURUM_GENELI_TURLER and not (
        rel == "ust_birim_bu_birim_hakkinda" and dtype in KARAR_TURLERI)
    return rel not in GENEL_ILISKI and rel != BIRIM_DISI and not tur_kg


def _unit_stats(recs: dict[str, dict], pins: dict, tags: dict, docs: dict) -> dict[str, dict]:
    """Ölçüt başına kabul edilmiş eşleşme, bölüm (birim) kanıtı sayısı ve en yüksek od_kabul.
    Bölüm kanıtı: `unit_own` belgedeki eşleşme."""
    from bidr.decide.run import unit_view

    out: dict[str, dict] = {}
    for rec in recs.values():
        if rec.get("durum") != "ok" or rec.get("asama") != "ince":
            continue
        view = unit_view(rec, pins, tags)
        bolum = unit_own(view, docs.get(rec["doc_id"]))
        for m in view.get("eslesmeler") or []:
            if not m.get("kabul"):
                continue
            s = out.setdefault(m["olcut"], {"kabul": 0, "bolum": 0, "od": 1})
            s["kabul"] += 1
            s["bolum"] += bolum
            if isinstance(m.get("od_kabul"), int):
                s["od"] = max(s["od"], m["od_kabul"])
    return out


def weak_criteria(allowed: list[str], recs: dict[str, dict], *, audit: dict[str, dict] | None = None,
                  pins: dict | None = None, tags: dict | None = None, docs: dict | None = None,
                  od_esik: int = OD_ESIK) -> dict[str, dict]:
    """Kanıtsız/zayıf alt ölçütler → {ölçüt: {nedenler, od, eslesme, bolum_eslesme, kaynak}}.

    - kanitsiz: sayılan eşleşme yok;
    - dusuk_od: önerilen OD ≤ `od_esik`;
    - yalniz_kurum_geneli: audit'e göre yalnız kurum geneli düzenlemeyle eşleşti;
    - bolum_kaniti_yok: kabul edilmiş eşleşmelerin hiçbiri birimin kendi belgesinden değil.
    OD ve sayılan eşleşme audit-olcutler.json'dan (PUKÖ zinciri, insan kararları dahil);
    yoksa decisions.jsonl'den yaklaşık (en yüksek `od_kabul`, kaynak `decisions`)."""
    st = _unit_stats(recs, pins or {}, tags or {}, docs or {})
    out: dict[str, dict] = {}
    for c in allowed:
        s = st.get(c, {"kabul": 0, "bolum": 0, "od": 1})
        a = (audit or {}).get(c)
        if a is not None:
            n, od, kg, src = int(a.get("eslesme") or 0), int(a.get("od") or 1), \
                bool(a.get("kurum_geneli_yalniz")), "audit"
        else:
            n, od, kg, src = s["kabul"], s["od"] if s["kabul"] else 1, False, "decisions"
        why: list[str] = []
        if n == 0:
            why.append("kanitsiz")
        else:
            if od <= od_esik:
                why.append("dusuk_od")
            if kg:
                why.append("yalniz_kurum_geneli")
            if s["bolum"] == 0:
                why.append("bolum_kaniti_yok")
        if why:
            out[c] = {"olcut": c, "nedenler": why, "od": od, "eslesme": n,
                      "bolum_eslesme": s["bolum"], "kaynak": src}
    return out


def query_bag(cs: CriteriaSet, sid: str, synonyms: bool = True):
    """(sorgu torbası, eşanlamlıdan eklenen belirteçler)."""
    t = criterion_text(cs, sid)
    if not synonyms:
        return bag(t), []
    q, added = expand(t)
    for x in query_terms(t, q):       # Türkçe ölçüt → İngilizce belge (izlence, ders sitesi)
        q[x] = 1
        added.append(x)
    return q, added


@dataclass
class Archive:
    """İşlenmiş arşiv: `text/` altındaki her belgenin sözcük torbası (yalnız içerik)."""
    bags: dict[str, dict] = field(default_factory=dict)

    @classmethod
    def load(cls, ws_root: Path | str) -> "Archive":
        ws = Workspace(Path(ws_root))
        bags = {}
        if ws.text_dir.exists():
            for p in sorted(ws.text_dir.glob("*.txt")):
                t = p.read_text(encoding="utf-8", errors="replace")
                b = bag(t)
                if b:
                    bags[p.stem] = expand_bag(t, dict(b))
        return cls(bags)


class Searcher:
    """Ölçüt → arşiv belgeleri puanı (sorgu BM25 + yuva sinyali, belgeler arasında normalize)."""

    def __init__(self, cs: CriteriaSet, archive: Archive, *, synonyms: bool = True,
                 weights: dict | None = None):
        self.cs = cs
        self.archive = archive
        self.synonyms = synonyms
        self.weights = dict(weights or WEIGHTS)
        self.bm = BM25.from_bags(archive.bags) if archive.bags else None
        self.slots = SlotBM25(cs)
        self._slot_cache: dict[str, dict[str, float]] = {}
        self._search_cache: dict[str, tuple[list[dict], list[str]]] = {}

    def _slot_scores(self, did: str) -> dict[str, float]:
        if did not in self._slot_cache:
            self._slot_cache[did] = self.slots.score(self.archive.bags[did])
        return self._slot_cache[did]

    def search(self, sid: str) -> tuple[list[dict], list[str]]:
        """([{doc_id, puan, sinyaller}], eşanlamlıdan eklenen belirteçler), azalan puan.
        Sorgu BM25'i sıfır olan belge listeye girmez (ölçüt sözcüklerinden hiçbiri yok).
        Sonuç önbellekte: arşiv ve çapraz yol aynı aramayı paylaşır."""
        if sid not in self._search_cache:
            self._search_cache[sid] = self._search(sid)
        return self._search_cache[sid]

    def _search(self, sid: str) -> tuple[list[dict], list[str]]:
        if self.bm is None:
            return [], []
        q, added = query_bag(self.cs, sid, self.synonyms)
        bm = {d: v for d, v in self.bm.score(q).items() if v > 0}
        if not bm:
            return [], added
        ys = {d: self._slot_scores(d).get(sid, 0.0) for d in bm}
        mb, my = max(bm.values()), max(ys.values())
        rows = []
        for d in bm:
            sg = {"sorgu": bm[d] / mb, "yuva": (ys[d] / my) if my > 0 else 0.0}
            rows.append({"doc_id": d, "puan": round(sum(self.weights[k] * v for k, v in sg.items()), 6),
                         "sinyaller": {k: round(v, 6) for k, v in sg.items()}})
        rows.sort(key=lambda r: (-r["puan"], r["doc_id"]))
        return rows, added


def first_pass_candidates(rec: dict) -> set[str]:
    """Belgenin ilk geçişte ince karara sunulan (ya da kaba seçimde seçilen) ve eşleştiği
    ölçütler: ikinci arama bunlara yeniden bakmaz. İkinci aramanın kendi eşleşmeleri hariç."""
    out = set(rec.get("adaylar") or [])
    out.update((rec.get("kaba") or {}).get("secilen") or [])
    out.update(m.get("olcut") for m in rec.get("eslesmeler") or [] if not m.get("ikinci_arama"))
    return {x for x in out if x}


def select(searcher: Searcher, weak: dict[str, dict], eligible: dict[str, set[str]], *,
           n: int = N_BELGE) -> dict[str, list[dict]]:
    """{ölçüt: [{doc_id, puan, sira, sinyaller}]}: ölçüt başına uygun en iyi `n` belge.
    `eligible`: {doc_id: bu belgede ikinci aramaya açık ölçütler}. `sira` arşivdeki sıradır
    (uygun olmayan belgeler de sayılır: ilk geçişin bu belgeyi ne kadar geride bıraktığı)."""
    out: dict[str, list[dict]] = {}
    for c in sorted(weak, key=id_key):
        rows, _ = searcher.search(c)
        picked = []
        for i, r in enumerate(rows, 1):
            if c in eligible.get(r["doc_id"], ()):
                picked.append({**r, "sira": i})
                if len(picked) >= n:
                    break
        out[c] = picked
    return out


def load_docs(ws: Workspace) -> dict[str, dict]:
    return {r["doc_id"]: r for r in read_jsonl(ws.documents) if r.get("doc_id")} \
        if ws.documents.exists() else {}


# -- çapraz yol: başka ölçütte kabul edilmiş birim belgeleri ---------------------------------
# Arşiv yolu (yukarıda) ölçüt başına arşivin en iyi `n` belgesini seçer; bir ölçüte atanmış
# belgenin başka bir ölçüte de kanıt olduğu çoğu zaman bu sıralamada geride kalır (bütçe cümlesi
# bir etkinlik raporunun içinde, izleme tablosu performans ölçütünde). Çapraz yol, başka ölçütte
# KABUL edilmiş (insan reddetmemiş) ve birimin kendi belgesi sayılan belgeleri zayıf ölçütlere
# aday yapar: bu belgeler okunmuş ve bölüme ait sayılmıştır, ucuz ve güvenilir adaylardır.
# Ölçüt ilk geçişte bu belgenin adayıydı ama ince karar eşleşme vermediyse de sorulur (dar
# aday listesi ve ölçüte odaklı metin kesiti); o ölçütle eşleşmesi olan (kabul ya da ret, insan
# ret dahil) belgeye o ölçüt yeniden sorulmaz.

def human_rejected(review: dict[str, dict], did: str, yuva: str | None) -> bool:
    return (review.get(f"{did}|{yuva}") or {}).get("karar") == "ret"


def accepted_elsewhere(rec: dict, view: dict, review: dict[str, dict]) -> list[str]:
    """Belgenin ilk geçişte kabul edilmiş, insanın reddetmediği eşleşmelerinin ölçütleri."""
    did = rec["doc_id"]
    return sorted({m["olcut"] for m in view.get("eslesmeler") or []
                   if m.get("kabul") and not m.get("ikinci_arama")
                   and not human_rejected(review, did, m.get("yuva"))}, key=id_key)


def first_pass_matched(rec: dict) -> set[str]:
    """İlk geçişin eşleşme verdiği ölçütler (kabul ya da ret): çapraz yol bunları sormaz."""
    return {m.get("olcut") for m in rec.get("eslesmeler") or [] if not m.get("ikinci_arama")} - {None}


def select_cross(searcher: Searcher, weak: dict[str, dict], pool: dict[str, dict], *,
                 max_aday: int) -> dict[str, list[dict]]:
    """{doc_id: [{olcut, puan, sira, sinyaller}]}: çapraz havuzdaki her belgeye en çok `max_aday`
    zayıf ölçüt. `pool`: {doc_id: {"acik": ölçütler, "kabul": başka ölçütler}}. Sıra: ölçüt
    sorgusunun bu belgeye puanı (arşivde en yükseğe bölünmüş, ölçütler arasında karşılaştırılabilir;
    kanıtsız ölçüte öncelik vermek her pakete ilgisiz kanıtsız ölçüt sokuyordu). Sorgu
    sözcüklerinden hiçbiri belgede yoksa (puan yok) ölçüt sorulmaz."""
    out: dict[str, list[dict]] = {}
    for c in sorted(weak, key=id_key):
        rows, _ = searcher.search(c)
        for i, r in enumerate(rows, 1):
            p = pool.get(r["doc_id"])
            if p and c in p["acik"]:
                out.setdefault(r["doc_id"], []).append({"olcut": c, "puan": r["puan"], "sira": i,
                                                        "sinyaller": r["sinyaller"]})
    for did, rows in out.items():
        rows.sort(key=lambda r: (-r["puan"], id_key(r["olcut"])))
        del rows[max_aday:]
    return out
