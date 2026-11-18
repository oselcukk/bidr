"""Model katmanı. Arayüz sözleşmesi: docs/MODEL_LAYER.md.

    from bidr.llm import ModelConfig, load_model_config, run_task, TaskResult, verify_quote
    from bidr.llm import render_task, validate_output   # ajan modu: sağlayıcı çağrılmaz
"""
from .config import (LLMConfigError, LLMError, ModelConfig, PrivacyError, config_from_dict,
                     load_model_config)
from .jsonx import ExtractError, extract_json
from .providers import ProviderError, get_provider
from .quote import QuoteMatch, verify_quote
from .runner import TaskFailed, TaskResult, render_task, run_task, validate_output
from .tasks import Task, TaskError, load_task, render_prompt

__all__ = [
    "ModelConfig", "load_model_config", "render_task", "validate_output", "config_from_dict", "run_task", "TaskResult", "verify_quote",
    "QuoteMatch", "extract_json", "load_task", "render_prompt", "get_provider", "Task",
    "LLMError", "LLMConfigError", "PrivacyError", "ProviderError", "TaskFailed", "TaskError",
    "ExtractError",
]
