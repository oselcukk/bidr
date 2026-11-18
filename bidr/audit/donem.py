"""Dönem kuralı: belge türüne göre (komisyon kararı, 2026-11-18). Veri:
`bidr/data/profiles/donem_kurali.yaml`; gerekçe: `docs/AUDIT.md` "Dönem kuralı".

yapı  → rapor yılında yürürlükte mi: dönem içi tam sayılır; aksi/bilinmiyor sayılır +
        `guncellik_dogrulanmali`.
olay  → rapor yılında mı gerçekleşti: önceki yıl U/K/Ö sayılmaz (`gecmis_kanit`), planla
        yapı gibi sayılır (+ güncellik); sonraki yıl `donem_sonrasi`, tarihsiz
        `tarih_dogrulanmali`: hiçbir aşama sayılmaz, satır görünür.
karma → aşama belirler: planla yapı, üstü olay.
Döngü: ölçütte sayılan bir eşleşmenin alıntısı döngü tanımlıyorsa (her N yılda vb.) son N
yılın `gecmis_kanit` satırları o ölçütte sayılır (`dongu_halkasi`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

FILE = "donem_kurali.yaml"
DEFAULT_PATH = Path(__file__).resolve().parents[1] / "data" / "profiles" / FILE
YAPI, OLAY, KARMA = "yapi", "olay", "karma"
ICI, ONCE, SONRA, BILINMIYOR = "ici", "once", "sonra", "bilinmiyor"
SAYI = {"iki": 2, "uc": 3, "dort": 4, "bes": 5, "alti": 6}

# işaret → tabloda okunur metin
ETIKET = {
    "guncellik_dogrulanmali": "güncellik doğrulanmalı",
    "gecmis_kanit": "geçmiş kanıt (süreklilik)",
    "dongu_halkasi": "döngü halkası",
    "donem_sonrasi": "dönem sonrası",
    "tarih_dogrulanmali": "tarih doğrulanmalı",
}


@dataclass(frozen=True)
class Rule:
    classes: dict[str, str]                # tür → yapi | olay | karma
    cycle_default: int
    cycle_max: int
    cycle_patterns: tuple[re.Pattern, ...]
    cycle_criteria: dict[str, str]         # ölçüt → öneri metni

    def cls(self, doc_type: str | None, stage: str | None) -> str:
        c = self.classes.get(doc_type or "", KARMA)
        if c == KARMA:
            return YAPI if stage == "planla" else OLAY
        return c

    def cycle_years(self, quote: str) -> int | None:
        """Alıntı bir gözden geçirme döngüsü tanımlıyorsa döngü yılı, değilse None."""
        from bidr.identify.text import fold
        f = fold(quote or "")
        for p in self.cycle_patterns:
            m = p.search(f)
            if m:
                n = (m.groupdict() or {}).get("n")
                y = int(n) if n and n.isdigit() else SAYI.get(n or "", self.cycle_default)
                if y < 2:              # yıllık: takvim yılı kuralı zaten geçerli
                    continue
                return min(y, self.cycle_max)
        return None


def rule_path() -> Path:
    from bidr.criteria.profiles import profiles_dir
    p = profiles_dir() / FILE
    return p if p.exists() else DEFAULT_PATH


@lru_cache(maxsize=4)
def _load(path: str, mtime: float) -> Rule:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    classes: dict[str, str] = {}
    for c in (YAPI, OLAY, KARMA):
        for t in raw.get(c) or []:
            if t in classes:
                raise ValueError(f"{path}: '{t}' iki sınıfta ({classes[t]}, {c})")
            classes[t] = c
    d = raw.get("dongu") or {}
    return Rule(classes, int(d.get("varsayilan_yil", 4)), int(d.get("en_cok_yil", 6)),
                tuple(re.compile(p) for p in d.get("desenler") or []),
                {k: " ".join(str(v).split()) for k, v in (d.get("olcutler") or {}).items()})


def load_rule(path: Path | None = None) -> Rule:
    p = Path(path) if path else rule_path()
    return _load(str(p), p.stat().st_mtime)


def doc_time(doc: dict) -> tuple[str, int | None]:
    """(zaman, yıl): belge rapor yılına göre içinde/önce/sonra/bilinmiyor."""
    from bidr.identify.dates import term_year
    ici, period = doc.get("donem_ici"), doc.get("donem")
    year = None
    if doc.get("tarih"):
        try:
            year = int(str(doc["tarih"])[:4])
        except ValueError:
            year = None
    if year is None:
        ys = [y for y in (term_year(t) for t in doc.get("akademik_donem") or []) if y]
        if ys and period is not None:
            before = [y for y in ys if y < period]
            year = max(before) if before else min(ys)
        elif ys:
            year = max(ys)
    if ici is True:
        return ICI, period if period is not None else year
    if ici is False:
        if year is not None and period is not None and year > period:
            return SONRA, year
        return ONCE, year
    return BILINMIYOR, year


def apply_row(rule: Rule, doc: dict, dtype: str, stage: str | None) -> dict:
    """Bir eşleşmeye dönem kuralı: {sinif, zaman, yil, sayilir, flags}. `sayilir` False ise
    satır görünür kalır ama hiçbir halkayı kanıtlamaz (döngü sonradan açabilir)."""
    cls = rule.cls(dtype, stage)
    zaman, yil = doc_time(doc)
    flags: list[str] = []
    say = True
    if cls == YAPI:
        if zaman != ICI:
            flags.append("guncellik_dogrulanmali")
    elif zaman == ONCE:
        if stage == "planla":
            flags.append("guncellik_dogrulanmali")     # usul tanımlayan eski karar: yapı gibi
        else:
            say = False
            flags.append("gecmis_kanit")
    elif zaman == SONRA:
        say = False
        flags.append("donem_sonrasi")
    elif zaman == BILINMIYOR:
        say = False
        flags.append("tarih_dogrulanmali")
    return {"sinif": cls, "zaman": zaman, "yil": yil, "sayilir": say, "flags": flags}


def describe(r: dict) -> str:
    """Tablonun 'dönem kuralı' hücresi."""
    if not r.get("donem_sinif"):
        return ""
    s = {YAPI: "yapı", OLAY: "olay"}[r["donem_sinif"]]
    z = {ICI: "dönem içi", ONCE: "önceki yıl", SONRA: "sonraki yıl", BILINMIYOR: "tarih yok"}[r["donem_zaman"]]
    if r.get("donem_yil") and r["donem_zaman"] != BILINMIYOR:
        z += f" ({r['donem_yil']})"
    marks = [ETIKET[f] for f in r["flags"] if f in ETIKET]
    return " · ".join([s, z, *marks])
