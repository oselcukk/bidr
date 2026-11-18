"""`run_task`: istemi doldur → modele sor → JSON ayıkla → şemayla doğrula → (gerekirse) yeniden sor.

Önbellek anahtarı = sha256(görev adı + görev sürümü + tam istem + sistem istemi + model kimliği
+ yapılandırmada varsa üretim ayarları: temperature, max_tokens, params).
Yalnız şemadan geçen çıktı önbelleğe yazılır.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import LLMError, ModelConfig
from .jsonx import ExtractError, extract_json, schema_errors
from .providers import ProviderError, get_provider
from .tasks import Task, load_task, render_prompt

SYSTEM_PROMPT = (
    "Sen bir belge çözümleme görevini yerine getiren yardımcısın. Yanıtın yalnız "
    "istenen JSON şemasına uyan tek bir JSON değeri olmalı; açıklama, ön söz ya da "
    "kod çiti ekleme. Belgede olmayan bir şeyi uydurma; alıntı istenen alanlara "
    "belge metninden birebir alıntı yaz."
)


class TaskFailed(LLMError):
    """Model, deneme hakkı içinde şemaya uyan çıktı veremedi."""

    def __init__(self, msg: str, *, attempts: int, raw: str | None, errors: list[str]):
        super().__init__(msg)
        self.attempts = attempts
        self.raw = raw
        self.errors = errors


@dataclass
class TaskResult:
    task: str
    output: Any                 # şemaya göre doğrulanmış çıktı
    model: str                  # ör. "claude-cli:opus"
    attempts: int               # modele kaç kez soruldu (önbellekten geldiyse ilk çalışmadaki sayı)
    cached: bool
    raw: str                    # son (geçerli) ham yanıt
    key: str = ""               # önbellek anahtarı
    version: str = ""           # görev sürümü
    errors: list[str] = field(default_factory=list)   # geçersiz denemelerin hata özetleri
    usage: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"task": self.task, "version": self.version, "model": self.model, "output": self.output,
                "attempts": self.attempts, "cached": self.cached, "key": self.key, "errors": self.errors}


def _schema_want(schema: dict) -> str:
    t = schema.get("type")
    if t == "array":
        return "array"
    if t == "object" or "properties" in schema:
        return "object"
    return "any"


def build_prompt(task: Task, inputs: dict) -> str:
    body = render_prompt(task.prompt, inputs)
    if not task.include_schema:
        return body
    schema = json.dumps(task.schema, ensure_ascii=False, indent=2)
    return (f"{body.rstrip()}\n\n---\nYanıtını yalnız aşağıdaki JSON şemasına uyan tek bir JSON "
            f"değeri olarak ver (başka metin yok):\n```json\n{schema}\n```\n")


def cache_key(task: Task, prompt: str, system: str, model: ModelConfig) -> str:
    h = hashlib.sha256()
    parts = [task.name, task.version, system, prompt, model.model_id]
    gen = model.generation_signature()
    if gen:
        parts.append(gen)
    for part in parts:
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def _cache_path(cache_dir: Path, key: str) -> Path:
    return Path(cache_dir) / key[:2] / f"{key}.json"


def _cache_get(cache_dir, key, task: Task) -> dict | None:
    p = _cache_path(cache_dir, key)
    if not p.exists():
        return None
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if rec.get("key") != key or schema_errors(rec.get("output"), task.schema):
        return None  # bozuk ya da şema değişmiş: yok say
    return rec


def _cache_put(cache_dir, key, rec: dict) -> None:
    p = _cache_path(cache_dir, key)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def _feedback(errors: list[str]) -> str:
    lines = "\n".join(f"- {e}" for e in errors)
    return ("Önceki yanıtın geçersizdi:\n" + lines +
            "\n\nAynı görevi yeniden yap ve yalnız şemaya uyan tek bir JSON değeri döndür "
            "(açıklama ya da kod çiti olmadan).")


def _as_task(task, tasks_dir=None) -> Task:
    return task if isinstance(task, Task) else load_task(task, tasks_dir)


def render_task(task: str | Path | Task, inputs: dict, *, tasks_dir: Path | None = None) -> dict:
    """Sağlayıcısız (ajan modu): görevin doldurulmuş istemi ve şeması.

    `run_task`'ın modele gönderdiğiyle aynı istem. Döner:
    `{"task", "version", "prompt", "schema", "system"}` (`system` = hat modunda
    kullanılan sistem istemi; ajan isterse yok sayar).
    """
    t = _as_task(task, tasks_dir)
    return {"task": t.name, "version": t.version, "prompt": build_prompt(t, inputs),
            "schema": t.schema, "system": t.system or SYSTEM_PROMPT}


def validate_output(task: str | Path | Task, raw, *, tasks_dir: Path | None = None) -> tuple[Any, list[str]]:
    """Sağlayıcısız (ajan modu): ham yanıt metni ya da hazır dict/list → `(çıktı | None, hatalar)`.

    `run_task` ile aynı JSON ayıklama ve şema doğrulaması. Geçerliyse
    `(çıktı, [])`, değilse `(None, [hata, ...])`.
    """
    t = _as_task(task, tasks_dir)
    if isinstance(raw, (dict, list)):
        value = raw
    elif isinstance(raw, str):
        try:
            value = extract_json(raw, _schema_want(t.schema))
        except ExtractError as e:
            return None, [str(e)]
    else:
        return None, [f"desteklenmeyen yanıt türü: {type(raw).__name__} (str, dict ya da list olmalı)"]
    errs = schema_errors(value, t.schema)
    return (None, errs) if errs else (value, [])


def run_task(task: str | Path | Task, inputs: dict, model: ModelConfig, cache_dir: str | Path | None = None,
             *, tasks_dir: Path | None = None, refresh: bool = False) -> TaskResult:
    """Görevi çalıştırır. Bkz. docs/MODEL_LAYER.md.

    - `cache_dir` verilirse önbellekten okur/yazar; `refresh=True` okumayı atlar (yazar).
    - Geçersiz yanıtta hata mesajı modele geri verilerek en çok `model.max_retries`
      kez yeniden sorulur; geçici aktarım hataları da aynı bütçeden düşer.
    - Başaramazsa `TaskFailed` (son ham yanıt ve hatalarla) yükseltir.
    """
    t = _as_task(task, tasks_dir)
    rendered = render_task(t, inputs)
    prompt, system = rendered["prompt"], rendered["system"]
    key = cache_key(t, prompt, system, model)
    model.check_privacy()

    if cache_dir is not None and not refresh:
        rec = _cache_get(cache_dir, key, t)
        if rec is not None:
            return TaskResult(task=t.name, output=rec["output"], model=rec.get("model", model.model_id),
                              attempts=int(rec.get("attempts", 1)), cached=True, raw=rec.get("raw", ""),
                              key=key, version=t.version, errors=list(rec.get("errors", [])))

    provider = get_provider(model)
    messages = [{"role": "user", "content": prompt}]
    errors: list[str] = []
    usage: dict = {}
    raw: str | None = None
    budget = 1 + model.max_retries
    attempt = 0
    while attempt < budget:
        attempt += 1
        try:
            comp = provider.complete(system, messages)
        except ProviderError as e:
            if not e.transient or attempt >= budget:
                raise
            errors.append(f"deneme {attempt}: sağlayıcı: {e}")
            if model.retry_backoff:
                time.sleep(model.retry_backoff * attempt)
            continue
        raw = comp.text
        for k, v in (comp.usage or {}).items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                usage[k] = usage.get(k, 0) + v
        value, errs = validate_output(t, raw)
        if not errs:
            res = TaskResult(task=t.name, output=value, model=model.model_id, attempts=attempt,
                             cached=False, raw=raw, key=key, version=t.version, errors=errors, usage=usage)
            if cache_dir is not None:
                _cache_put(cache_dir, key, {
                    "key": key, "task": t.name, "version": t.version, "model": model.model_id,
                    "output": value, "raw": raw, "attempts": attempt, "errors": errors,
                    "created": datetime.now(timezone.utc).isoformat(timespec="seconds")})
            return res
        errors.append(f"deneme {attempt}: " + "; ".join(errs))
        messages = [*messages, {"role": "assistant", "content": raw},
                    {"role": "user", "content": _feedback(errs)}]
    raise TaskFailed(f"{t.name}: {attempt} denemede şemaya uyan çıktı alınamadı ({model.model_id}): "
                     f"{errors[-1] if errors else ''}", attempts=attempt, raw=raw, errors=errors)
