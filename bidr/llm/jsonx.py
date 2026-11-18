"""Model yanıtından JSON ayıklama ve şema doğrulama."""
from __future__ import annotations

import json
import re

_FENCE = re.compile(r"```[ \t]*([A-Za-z0-9_-]*)[ \t]*\r?\n(.*?)(?:```|\Z)", re.S)
_DECODER = json.JSONDecoder()


class ExtractError(ValueError):
    pass


def _candidates(text: str):
    t = text.strip().lstrip("﻿")
    yield t
    for m in _FENCE.finditer(text):
        lang = m.group(1).lower()
        if lang in ("", "json", "jsonc", "json5"):
            yield m.group(2).strip()


def _scan(text: str, want: tuple[type, ...]):
    """İlk geçerli JSON nesnesini/dizisini metnin içinden bulur (öncesinde/sonrasında metin olabilir)."""
    for i, ch in enumerate(text):
        if ch not in "{[":
            continue
        try:
            val, _end = _DECODER.raw_decode(text, i)
        except json.JSONDecodeError:
            continue
        if isinstance(val, want):
            return val
    raise ExtractError


def extract_json(text: str, want: str = "object"):
    """Yanıttan JSON değerini çıkarır.

    Sıra: metnin tamamı → kod çitleri (```json ... ```) → metin içinde ilk
    çözülebilen `{...}` (want="array" ise `[...]`, "any" ise ikisi). Kapanmamış
    çit de kabul edilir (yanıt kesilmişse en azından içi denenir).
    """
    types = {"object": (dict,), "array": (list,), "any": (dict, list)}[want]
    if not text or not text.strip():
        raise ExtractError("yanıt boş")
    for c in _candidates(text):
        try:
            v = json.loads(c)
            if isinstance(v, types):
                return v
        except json.JSONDecodeError:
            pass
    for c in [*list(_candidates(text))[1:], text]:
        try:
            return _scan(c, types)
        except ExtractError:
            pass
    kind = {"object": "JSON nesnesi ({...})", "array": "JSON dizisi ([...])", "any": "JSON"}[want]
    raise ExtractError(f"yanıtta çözülebilir {kind} bulunamadı")


def schema_errors(value, schema: dict, limit: int = 8) -> list[str]:
    from jsonschema import Draft202012Validator

    v = Draft202012Validator(schema)
    out = []
    for e in sorted(v.iter_errors(value), key=lambda e: [str(p) for p in e.absolute_path]):
        path = "/".join(str(p) for p in e.absolute_path) or "(kök)"
        msg = e.message if len(e.message) <= 300 else e.message[:300] + "…"
        out.append(f"{path}: {msg}")
        if len(out) >= limit:
            break
    return out
