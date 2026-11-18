"""Kanıt yuvaları için PUKÖ / olgunluk düzeyi (OD) etiket önerileri.

Veri: `data/criteria/slot-tags-yokak-2025.yaml` (şablondan üretilen ölçüt
YAML'ından ayrı durur). Her kayıt bir yuvaya (`A.2.2/4`) bağlıdır; `metin`
yuvanın şablon metniyle birebir aynı olmalıdır. Etiketler öneridir
(`durum: oneri`), insan onayı bekler.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import yaml

from .loader import criteria_dir
from .model import CriteriaSet

TAGS_FILE = "slot-tags-yokak-2025.yaml"
STAGES = ("planla", "uygula", "kontrol_et", "onlem_al", "ozgun", "belirsiz")
STAGE_OD = {"planla": 2, "uygula": 3, "kontrol_et": 4, "onlem_al": 4, "ozgun": 5}
STATES = ("oneri", "onayli", "reddedildi")
KINDS = ("kanit", "dipnot")


@dataclass(frozen=True)
class SlotTag:
    slot: str
    text: str
    kind: str
    stages: tuple[str, ...]
    od: tuple[int, ...]
    reason: str
    state: str

    @property
    def uncertain(self) -> bool:
        return "belirsiz" in self.stages


def read_tags(path: Path | str | None = None) -> dict:
    p = Path(path) if path else criteria_dir() / TAGS_FILE
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)


def validate_tags(raw: dict, cs: CriteriaSet) -> list[str]:
    errs: list[str] = []
    slots = {s.id: s for s in cs.slots()}
    seen: set[str] = set()
    for r in raw.get("etiketler") or []:
        sid = r.get("yuva")
        if sid not in slots:
            errs.append(f"bilinmeyen yuva: {sid}")
            continue
        if sid in seen:
            errs.append(f"yinelenen yuva: {sid}")
        seen.add(sid)
        sl = slots[sid]
        if r.get("metin") != sl.text:
            errs.append(f"{sid}: metin şablonla birebir değil")
        kind = r.get("tur")
        if kind not in KINDS or (kind == "dipnot") != sl.footnote:
            errs.append(f"{sid}: tur={kind} yuvayla uyumsuz")
        st = r.get("asama") or []
        if not st or any(x not in STAGES for x in st):
            errs.append(f"{sid}: geçersiz asama {st}")
        if "belirsiz" in st and len(st) > 1:
            errs.append(f"{sid}: belirsiz başka aşamayla birlikte olamaz")
        od = sorted({STAGE_OD[x] for x in st if x in STAGE_OD})
        if list(r.get("od") or []) != od:
            errs.append(f"{sid}: od {r.get('od')} aşamalarla uyumsuz (beklenen {od})")
        if r.get("durum") not in STATES:
            errs.append(f"{sid}: geçersiz durum {r.get('durum')}")
        if not (r.get("gerekce") or "").strip():
            errs.append(f"{sid}: gerekçe boş")
    missing = sorted(set(slots) - seen)
    if missing:
        errs.append(f"etiketsiz yuva ({len(missing)}): {', '.join(missing[:10])}")
    if raw.get("olcut_surumu") != cs.meta.get("source_sha256"):
        errs.append("olcut_surumu ölçüt dosyasıyla uyuşmuyor")
    return errs


def load_tags(cs: CriteriaSet, path: Path | str | None = None, *, check: bool = True) -> dict[str, SlotTag]:
    raw = read_tags(path)
    if check:
        errs = validate_tags(raw, cs)
        if errs:
            raise ValueError("geçersiz yuva etiket dosyası:\n  " + "\n  ".join(errs))
    return {r["yuva"]: SlotTag(r["yuva"], r["metin"], r["tur"], tuple(r["asama"]),
                               tuple(r["od"]), r["gerekce"], r["durum"])
            for r in raw["etiketler"]}


def tag_summary(tags: dict[str, SlotTag]) -> dict:
    ev = [t for t in tags.values() if t.kind == "kanit"]
    return {
        "yuva": len(tags),
        "dipnot": sum(t.kind == "dipnot" for t in tags.values()),
        "kanit_yuvasi": len(ev),
        "belirsiz": sum(t.uncertain for t in ev),
        "tek_asamali": sum(len(t.stages) == 1 and not t.uncertain for t in ev),
        "cok_asamali": sum(len(t.stages) > 1 for t in ev),
        "asama": dict(Counter(s for t in ev for s in t.stages)),
        "od": dict(sorted(Counter(o for t in ev for o in t.od).items())),
        "durum": dict(Counter(t.state for t in tags.values())),
    }
