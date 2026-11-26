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


def normalize_enums(value, schema: dict, limit: int = 50) -> list[dict]:
    """Şema enum'unda olmayan metin değeri, enum'da `diger` seçeneği varsa `diger`e çevrilir (yerinde).
    Döner: [{"yol": "a/0/b", "deger": özgün}] (özgün değer kayıtta kalsın). `diger`siz enum'a dokunulmaz:
    orada geçersiz kalır ve cevap yeniden sorulur."""
    from jsonschema import Draft202012Validator
    out: list[dict] = []
    try:
        v = Draft202012Validator(schema)
    except Exception:
        return out
    for _ in range(limit):
        hit = None
        for e in v.iter_errors(value):
            if (e.validator == "enum" and isinstance(e.instance, str) and isinstance(e.validator_value, list)
                    and "diger" in e.validator_value and list(e.absolute_path)):
                hit = e
                break
        if hit is None:
            break
        path = list(hit.absolute_path)
        cur = value
        for p in path[:-1]:
            cur = cur[p]
        out.append({"yol": "/".join(str(p) for p in path), "deger": hit.instance})
        cur[path[-1]] = "diger"
    return out
