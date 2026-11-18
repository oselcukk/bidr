"""Model yapılandırması: çalışma klasöründeki `config.yaml` → `ModelConfig`.

Hangi sağlayıcı ve model kullanılacağı tamamen kullanıcıya kalır; kodda
varsayılan bir model ya da sağlayıcı yoktur. Anahtarlar dosyaya yazılmaz,
yalnız ortam değişkeninin adı (`api_key_env`) yazılır.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PROVIDERS = ("openai-compatible", "anthropic", "claude-cli", "fake")
ROLES = ("default", "coarse", "fine", "verify")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}

# config.yaml'da bir model girdisinde izin verilen anahtarlar
_KEYS = {
    "provider", "model", "base_url", "api_key_env", "temperature", "max_tokens",
    "timeout", "max_retries", "retry_backoff", "params", "command", "args", "responses",
    "allow_api_key",
}


class LLMError(RuntimeError):
    """Model katmanı hatası (yapılandırma, sağlayıcı, ayıklama)."""


class LLMConfigError(LLMError):
    pass


class PrivacyError(LLMConfigError):
    """`privacy.no_remote: true` iken uzak sağlayıcı istendi."""


@dataclass
class ModelConfig:
    provider: str
    model: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None      # ortam değişkeni ADI; anahtarın kendisi değil
    temperature: float | None = None
    max_tokens: int | None = None
    timeout: float = 600.0
    max_retries: int = 2                # geçersiz yanıttan sonra en çok bu kadar yeniden sor
    retry_backoff: float = 2.0          # aktarım hatasında bekleme (sn), deneme sayısıyla çarpılır
    params: dict[str, Any] = field(default_factory=dict)  # istek gövdesine eklenir (HTTP sağlayıcılar)
    command: str | None = None          # claude-cli: çalıştırılabilir (yoksa PATH'te `claude`)
    args: list[str] = field(default_factory=list)         # claude-cli: ek bayraklar
    allow_api_key: bool = False         # claude-cli: API anahtarı ortam değişkenleri alt sürece geçsin mi
    responses: list[Any] | None = None  # fake: sırayla verilecek yanıtlar (str, dict ya da çağrılabilir)
    no_remote: bool = False
    role: str = "default"
    _fake_calls: list = field(default_factory=list, repr=False, compare=False)

    def __post_init__(self):
        if self.provider not in PROVIDERS:
            raise LLMConfigError(
                f"bilinmeyen sağlayıcı: {self.provider!r} (geçerli: {', '.join(PROVIDERS)})")
        if self.provider in ("openai-compatible", "anthropic") and not self.model:
            raise LLMConfigError(f"{self.provider} için `model` gerekli")
        if self.provider == "openai-compatible" and not self.base_url:
            raise LLMConfigError("openai-compatible için `base_url` gerekli (ör. http://localhost:11434/v1)")
        if self.max_retries < 0:
            raise LLMConfigError("max_retries negatif olamaz")

    @property
    def model_id(self) -> str:
        """Önbellek anahtarına ve kayıtlara giren kimlik, ör. `claude-cli:opus`."""
        name = self.model or "(varsayılan)"
        if self.provider == "openai-compatible":
            host = urlparse(self.base_url or "").netloc
            return f"{self.provider}:{name}@{host}"
        return f"{self.provider}:{name}"

    def generation_signature(self) -> str:
        """Üretimi etkileyen ayarlar (temperature, max_tokens, params); önbellek anahtarına girer.
        Hiçbiri yoksa boş dize (anahtar değişmez)."""
        import json

        sig = {k: v for k, v in (("temperature", self.temperature), ("max_tokens", self.max_tokens),
                                 ("params", self.params or None)) if v is not None}
        return json.dumps(sig, sort_keys=True, ensure_ascii=False) if sig else ""

    @property
    def is_remote(self) -> bool:
        if self.provider == "fake":
            return False
        if self.provider == "openai-compatible":
            host = (urlparse(self.base_url or "").hostname or "").lower()
            return not (host in LOCAL_HOSTS or host.endswith(".localhost"))
        return True  # anthropic, claude-cli

    def check_privacy(self) -> None:
        if self.no_remote and self.is_remote:
            where = self.base_url if self.provider == "openai-compatible" else self.provider
            raise PrivacyError(
                f"privacy.no_remote: true iken uzak sağlayıcı kullanılamaz: {self.provider} ({where}); "
                "yalnız localhost'taki openai-compatible sunucular (Ollama, LM Studio, vLLM) izinli")

    def describe(self) -> dict:
        """Gizli bilgi içermeyen özet (anahtar değeri asla yok)."""
        d = {"role": self.role, "provider": self.provider, "model": self.model, "id": self.model_id,
             "remote": self.is_remote, "no_remote": self.no_remote}
        for k in ("base_url", "api_key_env", "temperature", "max_tokens", "command"):
            v = getattr(self, k)
            if v is not None:
                d[k] = v
        return d


def _ws_root(workspace) -> Path:
    # bidr.common.Workspace ya da yol (dikkat: Path'in de `.root` özniteliği var, "/" döner)
    root = workspace if isinstance(workspace, (str, Path)) else getattr(workspace, "root", workspace)
    return Path(root).expanduser().resolve()


def read_config(workspace) -> dict:
    path = _ws_root(workspace) / "config.yaml"
    if not path.exists():
        raise LLMConfigError(
            f"yapılandırma yok: {path}\n"
            "örnek:\n  models:\n    default: {provider: claude-cli, model: sonnet}\n"
            "  privacy:\n    no_remote: false")
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise LLMConfigError(f"{path}: kök bir sözlük olmalı")
    return data


def config_from_dict(entry: dict, *, role: str = "default", no_remote: bool = False) -> ModelConfig:
    if not isinstance(entry, dict):
        raise LLMConfigError(f"models.{role} bir sözlük olmalı")
    unknown = set(entry) - _KEYS
    if unknown:
        hint = ""
        if {"api_key", "key", "token", "password"} & unknown:
            hint = " (anahtar dosyaya yazılmaz; `api_key_env: ORTAM_DEGISKENI_ADI` kullanın)"
        raise LLMConfigError(f"models.{role}: bilinmeyen alan(lar): {', '.join(sorted(unknown))}{hint}")
    if "provider" not in entry:
        raise LLMConfigError(f"models.{role}: `provider` gerekli ({', '.join(PROVIDERS)})")
    kw = dict(entry)
    for k in ("params",):
        if k in kw and not isinstance(kw[k], dict):
            raise LLMConfigError(f"models.{role}.{k} bir sözlük olmalı")
    if "args" in kw:
        if not isinstance(kw["args"], list):
            raise LLMConfigError(f"models.{role}.args bir liste olmalı")
        kw["args"] = [str(a) for a in kw["args"]]
    return ModelConfig(**kw, role=role, no_remote=no_remote)


def load_model_config(workspace, role: str = "default") -> ModelConfig:
    """`<ws>/config.yaml` içinden rolün modelini okur.

    Rol tanımlı değilse `models.default` kullanılır. Rol girdisi `default`ın
    üstüne yazılır (ör. yalnız `model` değiştirilebilir). `privacy.no_remote`
    açıksa uzak sağlayıcı burada reddedilir.
    """
    data = read_config(workspace)
    models = data.get("models") or {}
    if not isinstance(models, dict):
        raise LLMConfigError("`models` bir sözlük olmalı")
    base = models.get("default") or {}
    own = models.get(role)
    if own is None and not base:
        raise LLMConfigError(f"config.yaml'da models.{role} da models.default da yok")
    entry = dict(base)
    if own:
        if not isinstance(own, dict):
            raise LLMConfigError(f"models.{role} bir sözlük olmalı")
        # sağlayıcı değişiyorsa varsayılanın sağlayıcıya özgü alanlarını taşıma
        if own.get("provider") and own.get("provider") != base.get("provider"):
            entry = {}
        entry.update(own)
    privacy = data.get("privacy") or {}
    no_remote = bool(privacy.get("no_remote", False)) if isinstance(privacy, dict) else False
    cfg = config_from_dict(entry, role=role, no_remote=no_remote)
    cfg.check_privacy()
    return cfg


def configured_roles(workspace) -> list[str]:
    models = read_config(workspace).get("models") or {}
    return [r for r in models if isinstance(models.get(r), dict)]


__all__ = [
    "LLMError", "LLMConfigError", "PrivacyError", "ModelConfig", "PROVIDERS", "ROLES",
    "load_model_config", "config_from_dict", "read_config", "configured_roles",
]
