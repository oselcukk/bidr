"""Birim profilleri: hangi alt ölçütleri hangi birim türü doldurur.

Veri: `bidr/data/profiles/<ad>.yaml`. BIDR_PROFILES_DIR ile değiştirilebilir.
Karar yalnız ölçütün `units` (DOLDURACAK BİRİMLER) metninden verilir.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .model import CriteriaSet

DEFAULT_DIR = Path(__file__).resolve().parents[1] / "data" / "profiles"
EXCLUDED_TYPES_FILE = "haric_turler.yaml"
DAHIL, HARIC, BELIRSIZ = "dahil", "haric", "belirsiz"


def profiles_dir() -> Path:
    env = os.environ.get("BIDR_PROFILES_DIR")
    return Path(env).expanduser() if env else DEFAULT_DIR


def _norm(s: str) -> str:
    s = s.replace("i", "İ").replace("ı", "I").upper()
    return re.sub(r"\s+", " ", s).strip()


def unit_items(units: str) -> list[str]:
    return [_norm(x) for x in units.split(",") if x.strip()]


@dataclass(frozen=True)
class Decision:
    criterion: str
    verdict: str            # dahil | haric | belirsiz
    reason: str
    keep: bool              # aday listesinde kalır mı


@dataclass
class Profile:
    name: str
    include: tuple[str, ...]
    uncertain: tuple[str, ...]
    uncertain_policy: str = "tut"
    overrides: dict[str, str] = field(default_factory=dict)
    description: str = ""

    def decide(self, criterion: str, units: str) -> Decision:
        if criterion in self.overrides:
            v = self.overrides[criterion]
            return Decision(criterion, v, "elle karar (kararlar)", v == DAHIL)
        items = unit_items(units)
        inc = [p for p in self.include if any(_norm(p) in it for it in items)]
        if inc:
            return Decision(criterion, DAHIL, f"'{inc[0]}'", True)
        unc = [p for p in self.uncertain if any(_norm(p) in it for it in items)]
        if unc:
            return Decision(criterion, BELIRSIZ, f"'{unc[0]}'", self.uncertain_policy == "tut")
        return Decision(criterion, HARIC, "doldurucu birimler arasında akademik birim yok", False)

    def decisions(self, cs: CriteriaSet) -> list[Decision]:
        return [self.decide(s.id, s.units) for s in cs.sub_criteria]

    def allowed(self, cs: CriteriaSet) -> list[str]:
        return [d.criterion for d in self.decisions(cs) if d.keep]


def load_profile(name_or_path: str | Path) -> Profile:
    p = Path(name_or_path)
    if not p.suffix:
        p = profiles_dir() / f"{name_or_path}.yaml"
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    pol = raw.get("belirsiz_politika", "tut")
    if pol not in ("tut", "dus"):
        raise ValueError(f"{p}: belirsiz_politika tut|dus olmalı: {pol}")
    ov = raw.get("kararlar") or {}
    bad = {k: v for k, v in ov.items() if v not in (DAHIL, HARIC)}
    if bad:
        raise ValueError(f"{p}: kararlar dahil|haric olmalı: {bad}")
    return Profile(raw["ad"], tuple(raw.get("dahil") or ()), tuple(raw.get("belirsiz") or ()),
                   pol, dict(ov), raw.get("aciklama", ""))


def excluded_types(path: Path | str | None = None) -> frozenset[str]:
    p = Path(path) if path else profiles_dir() / EXCLUDED_TYPES_FILE
    if not p.exists():
        return frozenset()
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return frozenset(raw.get("haric_turler") or ())
