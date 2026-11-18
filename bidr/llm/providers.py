"""Sağlayıcılar: `complete(system, messages) -> Completion`. Bağımlılıksız (urllib/subprocess).

`messages` = [{"role": "user"|"assistant", "content": str}, ...]; ilk ve son
ileti `user`. Yeniden denemelerde konuşma uzar (önceki yanıt + hata mesajı).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from .config import LLMError, ModelConfig


class ProviderError(LLMError):
    """Sağlayıcıya ulaşılamadı ya da sağlayıcı hata döndürdü."""

    def __init__(self, msg: str, *, transient: bool = False):
        super().__init__(msg)
        self.transient = transient  # True: yeniden denemek anlamlı (zaman aşımı, 429, 5xx)


@dataclass
class Completion:
    text: str
    usage: dict[str, Any] = field(default_factory=dict)


class Provider:
    def __init__(self, cfg: ModelConfig):
        self.cfg = cfg

    def complete(self, system: str, messages: list[dict]) -> Completion:  # pragma: no cover
        raise NotImplementedError


def _api_key(cfg: ModelConfig, default_env: str | None) -> str | None:
    env = cfg.api_key_env or default_env
    if not env:
        return None
    val = os.environ.get(env)
    return val or None


def _post_json(url: str, body: dict, headers: dict, timeout: float) -> dict:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"content-type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:500]
        except Exception:
            pass
        transient = e.code in (408, 409, 425, 429, 500, 502, 503, 504, 529)
        raise ProviderError(f"HTTP {e.code} {url}: {detail}", transient=transient) from None
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise ProviderError(f"bağlantı hatası {url}: {getattr(e, 'reason', e)}", transient=True) from None
    except json.JSONDecodeError as e:
        raise ProviderError(f"sağlayıcı JSON olmayan yanıt döndürdü ({url}): {e}") from None


class OpenAICompatible(Provider):
    """`POST {base_url}/chat/completions` (Ollama, LM Studio, vLLM, OpenRouter, ...)."""

    def complete(self, system, messages):
        cfg = self.cfg
        body: dict[str, Any] = {"model": cfg.model,
                                "messages": [{"role": "system", "content": system}, *messages]}
        if cfg.temperature is not None:
            body["temperature"] = cfg.temperature
        if cfg.max_tokens is not None:
            body["max_tokens"] = cfg.max_tokens
        body.update(cfg.params)
        headers = {}
        key = _api_key(cfg, None)
        if cfg.api_key_env and not key:
            raise ProviderError(f"ortam değişkeni boş: {cfg.api_key_env}")
        if key:
            headers["authorization"] = f"Bearer {key}"
        url = cfg.base_url.rstrip("/") + "/chat/completions"
        r = _post_json(url, body, headers, cfg.timeout)
        try:
            text = r["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            raise ProviderError(f"beklenmeyen yanıt biçimi: {json.dumps(r)[:300]}") from None
        return Completion(text=text, usage=r.get("usage") or {})


class Anthropic(Provider):
    """Anthropic Messages API (HTTPS). Anahtar ortam değişkeninden (vars. ANTHROPIC_API_KEY)."""

    API_VERSION = "2023-06-01"
    DEFAULT_BASE = "https://api.anthropic.com"

    def complete(self, system, messages):
        cfg = self.cfg
        key = _api_key(cfg, "ANTHROPIC_API_KEY")
        if not key:
            raise ProviderError(f"anahtar yok: ortam değişkeni {cfg.api_key_env or 'ANTHROPIC_API_KEY'} boş")
        body: dict[str, Any] = {"model": cfg.model, "system": system, "messages": messages,
                                "max_tokens": cfg.max_tokens or 4096}
        if cfg.temperature is not None:
            body["temperature"] = cfg.temperature
        body.update(cfg.params)
        url = (cfg.base_url or self.DEFAULT_BASE).rstrip("/") + "/v1/messages"
        r = _post_json(url, body, {"x-api-key": key, "anthropic-version": self.API_VERSION}, cfg.timeout)
        blocks = r.get("content") or []
        text = "".join(b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text")
        if not text and r.get("type") == "error":
            raise ProviderError(f"anthropic hata: {r.get('error')}")
        return Completion(text=text, usage=r.get("usage") or {})


def flatten_conversation(messages: list[dict]) -> str:
    """Tek atımlık sağlayıcılar (claude-cli) için konuşmayı tek isteme çevirir."""
    if len(messages) == 1:
        return messages[0]["content"]
    parts = []
    for i, m in enumerate(messages):
        if i == 0:
            parts.append(m["content"])
        elif m["role"] == "assistant":
            parts.append("\n\n=== ÖNCEKİ YANITIN ===\n" + m["content"])
        else:
            parts.append("\n\n=== DÜZELTME İSTEĞİ ===\n" + m["content"])
    return "".join(parts)


# claude-cli alt sürecinin ortamından varsayılan olarak çıkarılan değişkenler:
# bunlar varken CLI aboneliği değil faturalı API'yi (ya da Bedrock/Vertex/Foundry) kullanır.
CLAUDE_CLI_BILLING_ENV = (
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
    "AWS_BEARER_TOKEN_BEDROCK",
)


class ClaudeCLI(Provider):
    """`claude -p`: istem stdin'den, `--output-format json`, araçsız, oturum kaydı yok.

    Çalışma klasörü boş bir geçici klasördür (proje CLAUDE.md'si yüklenmesin).
    Ek bayraklar `args` ile verilir. Faturalı API'ye düşmemek için
    `CLAUDE_CLI_BILLING_ENV` değişkenleri alt sürecin ortamından çıkarılır
    (`allow_api_key: true` ile açıkça izin verilmedikçe); CLI aboneliği kullanır.
    """

    def child_env(self) -> dict:
        env = dict(os.environ)
        if not self.cfg.allow_api_key:
            for k in CLAUDE_CLI_BILLING_ENV:
                env.pop(k, None)
        return env

    def build_argv(self, system: str) -> list[str]:
        cfg = self.cfg
        exe = cfg.command or shutil.which("claude")
        if not exe:
            raise ProviderError("`claude` bulunamadı (PATH'te yok; config'te `command:` ile yol verin)")
        argv = [exe, "-p", "--output-format", "json", "--no-session-persistence",
                "--tools", "", "--strict-mcp-config", "--disable-slash-commands",
                "--system-prompt", system]
        if cfg.model:
            argv += ["--model", cfg.model]
        argv += list(cfg.args)
        return argv

    def complete(self, system, messages):
        cfg = self.cfg
        argv = self.build_argv(system)
        prompt = flatten_conversation(messages)
        with tempfile.TemporaryDirectory(prefix="bidr-llm-") as cwd:
            try:
                p = subprocess.run(argv, input=prompt, capture_output=True, text=True,
                                   timeout=cfg.timeout, cwd=cwd, env=self.child_env())
            except subprocess.TimeoutExpired:
                raise ProviderError(f"claude-cli zaman aşımı ({cfg.timeout} sn)", transient=True) from None
            except OSError as e:
                raise ProviderError(f"claude-cli çalıştırılamadı: {e}") from None
        out = (p.stdout or "").strip()
        try:
            r = json.loads(out) if out else None
        except json.JSONDecodeError:
            r = None
        if not isinstance(r, dict):
            raise ProviderError(
                f"claude-cli beklenmeyen çıktı (kod {p.returncode}): {(out or p.stderr or '')[:400]}",
                transient=p.returncode != 0)
        if r.get("is_error") or p.returncode != 0:
            raise ProviderError(f"claude-cli hata (kod {p.returncode}): {str(r.get('result') or r)[:400]}",
                                transient=True)
        usage = dict(r.get("usage") or {})
        if "total_cost_usd" in r:
            usage["total_cost_usd"] = r["total_cost_usd"]
        return Completion(text=str(r.get("result") or ""), usage=usage)


class Fake(Provider):
    """Testler için: `responses` sırayla verilir, sonuncu tekrarlanır.

    Öğe str ise olduğu gibi, dict/list ise JSON olarak döner; çağrılabilirse
    `f(system, messages) -> str|dict` çağrılır. Her çağrı `cfg._fake_calls`a eklenir.
    """

    def complete(self, system, messages):
        cfg = self.cfg
        items = cfg.responses or []
        if not items:
            raise ProviderError("fake sağlayıcı: `responses` boş")
        i = min(len(cfg._fake_calls), len(items) - 1)
        cfg._fake_calls.append({"system": system, "messages": [dict(m) for m in messages]})
        item = items[i]
        if callable(item):
            item = item(system, messages)
        if isinstance(item, Exception):
            raise item
        text = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
        return Completion(text=text)


_REGISTRY = {"openai-compatible": OpenAICompatible, "anthropic": Anthropic,
             "claude-cli": ClaudeCLI, "fake": Fake}


def get_provider(cfg: ModelConfig) -> Provider:
    cfg.check_privacy()
    return _REGISTRY[cfg.provider](cfg)
