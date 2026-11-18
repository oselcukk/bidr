"""Görev sözleşmeleri: `bidr/tasks/<ad>/` = prompt.md + output.schema.json + task.yaml."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import LLMError

TASKS_DIR = Path(__file__).resolve().parent.parent / "tasks"
_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\}\}")


class TaskError(LLMError):
    pass


@dataclass
class Task:
    name: str
    path: Path
    version: str
    description: str
    prompt: str
    schema: dict
    system: str | None = None          # task.yaml `system:` (yoksa genel sistem istemi)
    include_schema: bool = True        # istemin sonuna şema ve "yalnız JSON" talimatı eklensin mi
    meta: dict = field(default_factory=dict)

    @property
    def fields(self) -> list[str]:
        return sorted(set(_PLACEHOLDER.findall(self.prompt)))


def load_task(name: str | Path, tasks_dir: Path | None = None) -> Task:
    """Görevi adından (`classify_fine`) ya da klasör yolundan yükler."""
    p = Path(name)
    if not (p.is_dir() and (p / "prompt.md").exists()):
        p = Path(tasks_dir or TASKS_DIR) / str(name)
    if not p.is_dir():
        raise TaskError(f"görev bulunamadı: {name} ({p})")
    missing = [f for f in ("prompt.md", "output.schema.json", "task.yaml") if not (p / f).exists()]
    if missing:
        raise TaskError(f"görev eksik ({p}): {', '.join(missing)}")
    import yaml

    meta = yaml.safe_load((p / "task.yaml").read_text(encoding="utf-8")) or {}
    if not isinstance(meta, dict) or "version" not in meta:
        raise TaskError(f"{p}/task.yaml: `version` gerekli")
    try:
        schema = json.loads((p / "output.schema.json").read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise TaskError(f"{p}/output.schema.json geçersiz JSON: {e}") from None
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError

    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as e:
        raise TaskError(f"{p}/output.schema.json geçersiz şema: {e.message}") from None
    return Task(name=p.name, path=p, version=str(meta["version"]),
                description=str(meta.get("description", "")),
                prompt=(p / "prompt.md").read_text(encoding="utf-8"), schema=schema,
                system=meta.get("system"), include_schema=bool(meta.get("include_schema", True)),
                meta=meta)


def _lookup(inputs: dict, key: str):
    cur = inputs
    for part in key.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            raise KeyError(key)
    return cur


def render_prompt(template: str, inputs: dict) -> str:
    """`{{alan}}` (ve `{{a.b}}`) yer tutucularını tek geçişte doldurur.

    str değerler olduğu gibi, diğerleri girintili JSON olarak girer. Girilen
    değerin içindeki `{{...}}` yeniden işlenmez. Eksik alan hatadır.
    """
    missing = [k for k in _PLACEHOLDER.findall(template) if not _has(inputs, k)]
    if missing:
        raise TaskError(f"girdide eksik alan(lar): {', '.join(sorted(set(missing)))}")

    def sub(m):
        v = _lookup(inputs, m.group(1))
        return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, indent=2)

    return _PLACEHOLDER.sub(sub, template)


def _has(inputs, key):
    try:
        _lookup(inputs, key)
        return True
    except KeyError:
        return False
