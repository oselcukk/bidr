"""Belge türü kataloğu ve kurum profillerini yükle, desenleri derle."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .text import fold_pattern

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DEFAULT_CATALOG = DATA_DIR / "doc_types.yaml"
INSTITUTIONS_DIR = DATA_DIR / "institutions"

REGIONS = ("ust", "bas", "son", "tum")
UNKNOWN = "bilinmiyor"


class CatalogError(ValueError):
    pass


@dataclass
class Signature:
    id: str
    region: str
    pattern: re.Pattern
    weight: float
    min_count: int = 1
    source: str = ""


@dataclass
class DocType:
    name: str
    label: str
    description: str
    signatures: list[Signature]
    date_labels: list[str] = field(default_factory=list)
    # Aday üretiminde bu türe ölçüt önceliği: {alt ölçüt: 0..1} (`olcut_onceligi`).
    criteria_priority: dict[str, float] = field(default_factory=dict)


@dataclass
class Institution:
    key: str
    name: str
    prefixes: dict[str, str]           # katlanmış önek -> görünen önek
    prefix_types: dict[str, str]       # görünen önek -> tür
    codes: dict[str, dict]             # "FR-0044" -> {tur, ad}
    code_weight: float


@dataclass
class Catalog:
    version: int
    threshold: float
    regions: dict[str, int]
    types: list[DocType]
    institutions: list[Institution]
    date_labels: list[str]
    excluded_date_labels: list[str]

    def get(self, name: str) -> DocType | None:
        for t in self.types:
            if t.name == name:
                return t
        return None

    @property
    def names(self) -> list[str]:
        return [t.name for t in self.types]

    def code_info(self, code: str) -> tuple[str | None, str | None]:
        """Kod -> (tür, ad). Profillerde yoksa önek kuralına bakılır."""
        for inst in self.institutions:
            if code in inst.codes:
                c = inst.codes[code] or {}
                return c.get("tur"), c.get("ad")
        for inst in self.institutions:
            pre = code.split("-")[0]
            if pre in inst.prefix_types:
                return inst.prefix_types[pre], None
        return None, None

    @property
    def code_weight(self) -> float:
        return max((i.code_weight for i in self.institutions), default=6.0)

    def prefix_map(self) -> dict[str, str]:
        m: dict[str, str] = {}
        for inst in self.institutions:
            m.update(inst.prefixes)
        return m


def _compile(p: str, where: str) -> re.Pattern:
    try:
        return re.compile(fold_pattern(p))
    except re.error as e:
        raise CatalogError(f"{where}: geçersiz desen {p!r}: {e}") from e


def _load_type(raw: dict, i: int) -> DocType:
    name = raw.get("ad")
    if not name or not re.fullmatch(r"[a-z0-9_]+", name):
        raise CatalogError(f"tür #{i}: 'ad' küçük harf/rakam/_ olmalı: {name!r}")
    sigs = []
    for j, s in enumerate(raw.get("imzalar") or []):
        where = f"{name}.imzalar[{j}]"
        region = s.get("bolge", "tum")
        if region not in REGIONS:
            raise CatalogError(f"{where}: bölge {region!r} geçersiz ({REGIONS})")
        if "desen" not in s or "id" not in s:
            raise CatalogError(f"{where}: 'id' ve 'desen' zorunlu")
        sigs.append(Signature(
            id=s["id"], region=region, pattern=_compile(s["desen"], where),
            weight=float(s.get("agirlik", 1)), min_count=int(s.get("en_az", 1)),
            source=s["desen"],
        ))
    if not sigs:
        raise CatalogError(f"{name}: en az bir imza gerekli")
    prio = raw.get("olcut_onceligi") or {}
    if isinstance(prio, list):
        prio = dict.fromkeys(prio, 1.0)
    if not isinstance(prio, dict):
        raise CatalogError(f"{name}: 'olcut_onceligi' sözlük ya da liste olmalı")
    crit_prio = {}
    for k, v in prio.items():
        if not re.fullmatch(r"[A-E]\.\d+\.\d+", str(k)):
            raise CatalogError(f"{name}.olcut_onceligi: geçersiz alt ölçüt {k!r}")
        try:
            fv = float(v)
        except (TypeError, ValueError):
            raise CatalogError(f"{name}.olcut_onceligi.{k}: sayı olmalı") from None
        if not 0 < fv <= 1:
            raise CatalogError(f"{name}.olcut_onceligi.{k}: 0 < değer <= 1 olmalı")
        crit_prio[str(k)] = fv
    return DocType(
        name=name, label=raw.get("etiket", name), description=raw.get("aciklama", ""),
        signatures=sigs, date_labels=list(raw.get("tarih_etiketleri") or []),
        criteria_priority=crit_prio,
    )


def load_institution(path: Path) -> Institution:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return Institution(
        key=raw.get("kurum", path.stem), name=raw.get("ad", path.stem),
        prefixes={k.lower(): v for k, v in (raw.get("onekler") or {}).items()},
        prefix_types=dict(raw.get("onek_turleri") or {}),
        codes=dict(raw.get("kodlar") or {}),
        code_weight=float(raw.get("kod_agirligi", 6)),
    )


def institution_paths(keys: list[str] | None = None) -> list[Path]:
    d = Path(os.environ.get("BIDR_INSTITUTIONS_DIR", INSTITUTIONS_DIR)).expanduser()
    if not d.is_dir():
        return []
    paths = sorted(d.glob("*.yaml"))
    if keys:
        wanted = set(keys)
        paths = [p for p in paths if p.stem in wanted]
        missing = wanted - {p.stem for p in paths}
        if missing:
            raise CatalogError(f"kurum profili bulunamadı: {', '.join(sorted(missing))}")
    return paths


def load_catalog(path: Path | None = None, institutions: list[str] | None = None,
                 institution_files: list[Path] | None = None) -> Catalog:
    p = Path(path or os.environ.get("BIDR_DOC_TYPES", DEFAULT_CATALOG)).expanduser()
    with open(p, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    types = [_load_type(t, i) for i, t in enumerate(raw.get("turler") or [])]
    names = [t.name for t in types]
    dup = {n for n in names if names.count(n) > 1}
    if dup:
        raise CatalogError(f"yinelenen tür adı: {sorted(dup)}")
    if UNKNOWN in names:
        raise CatalogError(f"'{UNKNOWN}' ayrılmış addır")
    files = institution_files if institution_files is not None else institution_paths(institutions)
    insts = [load_institution(Path(x)) for x in files]
    for inst in insts:
        for code, c in inst.codes.items():
            t = (c or {}).get("tur")
            if t and t not in names:
                raise CatalogError(f"{inst.key}: {code} bilinmeyen türe bağlı: {t}")
        for pre, t in inst.prefix_types.items():
            if t not in names:
                raise CatalogError(f"{inst.key}: önek {pre} bilinmeyen türe bağlı: {t}")
    regions = {"ust": 300, "bas": 1500, "son": 800}
    regions.update(raw.get("bolgeler") or {})
    return Catalog(
        version=int(raw.get("surum", 1)), threshold=float(raw.get("esik", 4)),
        regions=regions, types=types, institutions=insts,
        date_labels=list(raw.get("genel_tarih_etiketleri") or []),
        excluded_date_labels=list(raw.get("haric_tarih_etiketleri") or []),
    )
