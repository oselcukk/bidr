"""Ölçüt YAML'ını yükler ve doğrular."""
from __future__ import annotations

import json
import os
from pathlib import Path

import yaml

from .model import Area, CriteriaSet, Criterion, SubCriterion, id_key

# Paket verisi: bidr/data/criteria. BIDR_CRITERIA_DIR ile değiştirilebilir.
DEFAULT_DIR = Path(__file__).resolve().parents[1] / "data" / "criteria"
DEFAULT_FILE = "yokak-2025.yaml"
ORNEK_FILE = "ornek-uygulamalar.yaml"     # kılavuz eki "Örnek Uygulama ve Kanıtlar Listesi" (extract_docx)
SCHEMA_FILE = "schema.json"


def criteria_dir() -> Path:
    env = os.environ.get("BIDR_CRITERIA_DIR")
    return Path(env).expanduser() if env else DEFAULT_DIR


def default_path() -> Path:
    return criteria_dir() / DEFAULT_FILE


def read_raw(path: Path | None = None) -> dict:
    p = Path(path) if path else default_path()
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _jsonable(raw: dict) -> dict:
    """JSON Schema için: rubrik anahtarlarını str'ye çevirir (YAML'da int)."""
    data = json.loads(json.dumps(raw, ensure_ascii=False, default=str))
    return data


def validate(raw: dict, schema_path: Path | None = None) -> list[str]:
    """Şema + yapısal denetim. Hata listesi döner (boşsa geçerli)."""
    import jsonschema

    sp = Path(schema_path) if schema_path else criteria_dir() / SCHEMA_FILE
    schema = json.loads(sp.read_text(encoding="utf-8"))
    errors: list[str] = []
    v = jsonschema.Draft202012Validator(schema)
    for e in sorted(v.iter_errors(_jsonable(raw)), key=lambda e: list(e.path)):
        loc = "/".join(str(x) for x in e.path) or "<kök>"
        errors.append(f"şema: {loc}: {e.message}")
    if errors:
        return errors

    areas = [a["id"] for a in raw["areas"]]
    mains = [c["id"] for c in raw["criteria"]]
    subs = [s["id"] for s in raw["sub_criteria"]]
    for name, ids in (("alan", areas), ("ölçüt", mains), ("alt ölçüt", subs)):
        if len(ids) != len(set(ids)):
            dup = sorted({i for i in ids if ids.count(i) > 1})
            errors.append(f"yinelenen {name} kimliği: {', '.join(dup)}")
        if ids != sorted(ids, key=id_key):
            errors.append(f"{name} kimlikleri sıralı değil")
    for c in raw["criteria"]:
        if c["parent"] not in areas:
            errors.append(f"{c['id']}: üst alan yok ({c['parent']})")
        if not c["id"].startswith(c["parent"] + "."):
            errors.append(f"{c['id']}: kimlik üstle uyumsuz ({c['parent']})")
    for s in raw["sub_criteria"]:
        if s["parent"] not in mains:
            errors.append(f"{s['id']}: üst ölçüt yok ({s['parent']})")
        if not s["id"].startswith(s["parent"] + "."):
            errors.append(f"{s['id']}: kimlik üstle uyumsuz ({s['parent']})")
    counts = raw["meta"]["counts"]
    for key, ids in (("areas", areas), ("criteria", mains), ("sub_criteria", subs)):
        if counts.get(key) != len(ids):
            errors.append(f"meta.counts.{key}={counts.get(key)} ama {len(ids)} öğe var")
    return errors


def build(raw: dict) -> CriteriaSet:
    return CriteriaSet(
        meta=raw["meta"],
        areas=[Area(a["id"], a["title"], tuple(a.get("description") or ()))
               for a in raw["areas"]],
        criteria=[Criterion(c["id"], c["title"], c["parent"],
                            tuple(c.get("description") or ()))
                  for c in raw["criteria"]],
        sub_criteria=[SubCriterion(
            id=s["id"], title=s["title"], parent=s["parent"],
            description=tuple(s["description"]), units=s["units"],
            rubric={int(k): v for k, v in s["rubric"].items()},
            example_evidence=tuple(s["example_evidence"]),
            units_note=tuple(s.get("units_note") or ()),
        ) for s in raw["sub_criteria"]],
    )


def load_criteria(path: Path | str | None = None, *, check: bool = True) -> CriteriaSet:
    """Ölçüt setini yükler. `check=True` ise şema ve yapı doğrulanır; hata varsa ValueError."""
    p = Path(path) if path else default_path()
    raw = read_raw(p)
    if check:
        errs = validate(raw, p.parent / SCHEMA_FILE if (p.parent / SCHEMA_FILE).exists() else None)
        if errs:
            raise ValueError(f"{p}: geçersiz ölçüt dosyası:\n  " + "\n  ".join(errs))
    return build(raw)


def load_guide(path: Path | str | None = None) -> dict:
    p = Path(path) if path else criteria_dir() / "guide.yaml"
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_ornek_uygulamalar(path: Path | str | None = None) -> dict:
    """Kılavuz eki örnek uygulama satırları: {"meta", "alanlar", "satirlar": [{id, alan, uygulama, kanit}]}.
    Satırlar alan düzeyindedir; alt ölçüt eşlemesi `bidr/data/ihtiyac_ornek_uygulama.yaml`'dadır."""
    p = Path(path) if path else criteria_dir() / ORNEK_FILE
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
