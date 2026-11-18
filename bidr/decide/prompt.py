"""Görev girdilerinin hazırlanması: ölçüt/yuva listeleri, belge bilgisi, metin kısaltma.

Modele giden her şey burada üretilir. Kaynaklar YALNIZ şunlardır:
  - ölçüt şablonu (başlık, rubrik, kanıt yuvası metni; birebir) ve yuva etiketleri,
  - `text/<doc_id>.txt` (belge metni),
  - `documents.jsonl` içinden `CONTENT_FIELDS` (metinden çıkarılmış içerik alanları).
Dosya yolu, dosya adı, `calisma_adi`, `labels.jsonl` (`iz` dahil) ve `inventory.csv`
asla okunmaz ve modele gitmez.
"""
from __future__ import annotations

import re

from bidr.candidates.text import tokens
from bidr.criteria.model import CriteriaSet, id_key
from bidr.criteria.slots import STAGE_OD, SlotTag

# documents.jsonl'den modele gidebilecek alanlar (hepsi metinden çıkarılır).
CONTENT_FIELDS = ("doc_type", "doc_type_etiket", "tarih", "akademik_donem", "metin.sayfa")
UNKNOWN_TYPE = "bilinmeyen"

COARSE_CHARS = 6000      # kaba seçimde belge metni bütçesi (karakter)
FINE_CHARS = 8000        # ince kararda belge metni bütçesi
HEAD_SHARE = 0.5         # kısaltmada baştan alınan pay
CHUNK = 600              # kısaltmada seçilen parça boyu
GAP = " [...] "

GENERIC_SHARE = 0.25     # yuvaların bu payından fazlasında geçen sözcük ayırt edici sayılmaz


def approx_tokens(s: str) -> int:
    """Kaba token tahmini (Türkçe için muhafazakâr: ~3 karakter/token)."""
    return (len(s) + 2) // 3


# -- belge bilgisi -------------------------------------------------------------

def content_info(doc: dict | None) -> dict:
    """documents.jsonl kaydından yalnız izinli içerik alanları."""
    if not doc:
        return {}
    out = {}
    t = doc.get("doc_type")
    if isinstance(t, str) and t and t != UNKNOWN_TYPE:
        out["tur"] = doc.get("doc_type_etiket") or t
    if isinstance(doc.get("tarih"), str):
        out["tarih"] = doc["tarih"]
    ad = doc.get("akademik_donem")
    if isinstance(ad, list) and ad:
        out["akademik_donem"] = [str(x) for x in ad[:3]]
    m = doc.get("metin")
    if isinstance(m, dict) and isinstance(m.get("sayfa"), int):
        out["sayfa"] = m["sayfa"]
    return out


def render_info(info: dict) -> str:
    if not info:
        return "(yok)"
    parts = []
    if "tur" in info:
        parts.append(f"tür tahmini: {info['tur']}")
    if "tarih" in info:
        parts.append(f"içerik tarihi: {info['tarih']}")
    if "akademik_donem" in info:
        parts.append("akademik dönem: " + ", ".join(info["akademik_donem"]))
    if "sayfa" in info:
        parts.append(f"sayfa: {info['sayfa']}")
    return "; ".join(parts)


# -- metin kısaltma ------------------------------------------------------------

def normalize(text: str) -> str:
    """Sayfa ayracı → satır; yatay boşluk teke; 3+ boş satır ikiye. İçerik değişmez."""
    t = text.replace("\f", "\n").replace("\r", "")
    t = re.sub(r"[ \t ]+", " ", t)
    t = "\n".join(line.strip() for line in t.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def _cut(t: str, end: int) -> int:
    """`end`'den geriye en yakın boşluğa çek (sözcük bölünmesin)."""
    if end >= len(t):
        return len(t)
    j = t.rfind(" ", max(0, end - 80), end)
    k = t.rfind("\n", max(0, end - 80), end)
    j = max(j, k)
    return j if j > 0 else end


def excerpt(text: str, budget: int, terms: set[str] | None = None) -> tuple[str, dict]:
    """Bütçeye sığan metin ve kısaltma kaydı.

    Sığıyorsa normalize edilmiş metnin tamamı. Sığmıyorsa: baştan `HEAD_SHARE`
    (başlık, konu, tarih genelde baştadır) + kalan bütçe, ölçüt sözcüklerini
    (`terms`, gövdelenmiş) en yoğun içeren `CHUNK` boylu parçalarla; parçalar
    metin sırasında, aralarında `[...]`. `terms` yoksa parçalar eşit aralıklı.
    """
    t = normalize(text)
    info = {"orijinal_karakter": len(text), "normal_karakter": len(t)}
    if len(t) <= budget:
        info.update(verilen_karakter=len(t), kisaltildi=False)
        return t, info
    head_end = _cut(t, int(budget * HEAD_SHARE))
    spans = [(0, head_end)]
    rest = budget - head_end
    chunks = []
    pos = head_end
    while pos < len(t):
        end = _cut(t, pos + CHUNK)
        if end <= pos:
            end = min(len(t), pos + CHUNK)
        chunks.append((pos, end))
        pos = end
    n_pick = max(1, rest // (CHUNK + len(GAP)))
    if terms:
        def score(c):
            toks = tokens(t[c[0]:c[1]])
            return sum(1 for x in toks if x in terms) / (len(toks) ** 0.5 or 1.0)
        ranked = sorted(chunks, key=lambda c: (-score(c), c[0]))
        picked = [c for c in ranked[:n_pick] if score(c) > 0]
        yontem = "bas+olcut_sozcuk_parcalari"
    else:
        picked = []
        yontem = "bas+esit_aralikli_parcalar"
    if not picked:
        step = max(1, len(chunks) // n_pick)
        picked = chunks[::step][:n_pick]
        yontem = "bas+esit_aralikli_parcalar"
    spans += sorted(picked)
    out = []
    for i, (a, b) in enumerate(spans):
        if i and a != spans[i - 1][1]:
            out.append(GAP.strip())
        out.append(t[a:b].strip())
    if spans[-1][1] < len(t):
        out.append(GAP.strip())
    s = "\n".join(out)
    info.update(verilen_karakter=len(s), kisaltildi=True, yontem=yontem,
                parcalar=[[a, b] for a, b in spans])
    return s, info


# -- ölçüt listeleri -------------------------------------------------------------

def coarse_list(cs: CriteriaSet, allowed: list[str]) -> str:
    """Ana ölçüt başlığı altında `kimlik — başlık: rubrik 3` (birebir)."""
    lines = []
    last = None
    for sid in sorted(allowed, key=id_key):
        s = cs.get(sid)
        if s.parent != last:
            last = s.parent
            lines.append(f"[{s.parent} {cs.get(s.parent).title}]")
        lines.append(f"{s.id} — {s.title}: {s.rubric.get(3, '')}")
    return "\n".join(lines)


def slot_tag_label(tag: SlotTag | None) -> str:
    if tag is None or tag.uncertain or not tag.stages:
        return "içeriğe bağlı"
    st = [x for x in tag.stages if x in STAGE_OD]
    od = sorted({STAGE_OD[x] for x in st})
    return "/".join(st) + " → OD" + "/".join(str(x) for x in od)


def fine_list(cs: CriteriaSet, cands: list[str], tags: dict[str, SlotTag]) -> str:
    blocks = []
    for sid in cands:
        s = cs.get(sid)
        lines = [f"## {s.id} {s.title} (ana ölçüt: {s.parent} {cs.get(s.parent).title})", "Rubrik:"]
        lines += [f"  {k}: {v}" for k, v in sorted(s.rubric.items())]
        lines.append("Kanıt yuvaları:")
        for sl in s.slots:
            if sl.footnote:
                continue
            lines.append(f"  - {sl.id} [{slot_tag_label(tags.get(sl.id))}] {sl.text}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _slot_bags(cs: CriteriaSet) -> dict[str, set[str]]:
    return {s.id: set(tokens(s.title)).union(*(set(tokens(x.text)) for x in s.slots if not x.footnote))
            for s in cs.sub_criteria}


def criteria_terms(cs: CriteriaSet, cands: list[str]) -> set[str]:
    """Kısaltmada parça seçimi için aday ölçütlerin (başlık + yuvalar) ayırt edici
    sözcükleri; ölçütlerin `GENERIC_SHARE`'inden fazlasında geçenler (kanıt, birim,
    uygulama…) atılır."""
    bags = _slot_bags(cs)
    df: dict[str, int] = {}
    for b in bags.values():
        for x in b:
            df[x] = df.get(x, 0) + 1
    lim = GENERIC_SHARE * len(bags)
    out: set[str] = set()
    for sid in cands:
        out.update(x for x in bags.get(sid, ()) if df[x] <= lim)
    return out
