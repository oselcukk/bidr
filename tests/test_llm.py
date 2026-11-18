"""bidr.llm: yapılandırma, sağlayıcılar (ağsız taklitlerle), run_task, önbellek, CLI. Sentetik veri."""
from __future__ import annotations

import io
import json
import os
import stat
import sys
from pathlib import Path

import pytest

from bidr.llm import (LLMConfigError, ModelConfig, PrivacyError, ProviderError, TaskFailed, extract_json,
                      load_model_config, load_task, render_prompt, run_task)
from bidr.llm import providers as P
from bidr.llm.jsonx import ExtractError

GOOD = {"alinti": "kurul toplandı", "sozcuk_sayisi": 2, "dil": "tr"}


def fake(*responses, **kw) -> ModelConfig:
    return ModelConfig(provider="fake", model="t", responses=list(responses), retry_backoff=0, **kw)


def write_cfg(ws: Path, text: str) -> Path:
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "config.yaml").write_text(text, encoding="utf-8")
    return ws


# --- yapılandırma -----------------------------------------------------------

def test_load_config_role_fallback_and_override(tmp_path):
    ws = write_cfg(tmp_path / "ws", """
models:
  default: {provider: claude-cli, model: sonnet, timeout: 30}
  fine: {model: opus}
  coarse: {provider: openai-compatible, model: m1, base_url: "http://127.0.0.1:1234/v1"}
""")
    d = load_model_config(ws)
    assert (d.provider, d.model, d.timeout, d.model_id) == ("claude-cli", "sonnet", 30, "claude-cli:sonnet")
    f = load_model_config(ws, "fine")
    assert (f.provider, f.model, f.timeout, f.role) == ("claude-cli", "opus", 30, "fine")
    c = load_model_config(ws, "coarse")
    assert c.provider == "openai-compatible" and c.timeout == 600.0  # varsayılanın alanları taşınmaz
    v = load_model_config(ws, "verify")  # tanımsız rol → default
    assert v.model == "sonnet" and v.role == "verify"


def test_config_errors(tmp_path):
    with pytest.raises(LLMConfigError, match="yapılandırma yok"):
        load_model_config(tmp_path)
    ws = write_cfg(tmp_path / "a", "models:\n  default: {provider: anthropic, model: x, api_key: sk-123}\n")
    with pytest.raises(LLMConfigError, match="api_key_env"):
        load_model_config(ws)
    ws = write_cfg(tmp_path / "b", "models:\n  default: {provider: nope}\n")
    with pytest.raises(LLMConfigError, match="bilinmeyen sağlayıcı"):
        load_model_config(ws)
    ws = write_cfg(tmp_path / "c", "models:\n  default: {provider: openai-compatible, model: x}\n")
    with pytest.raises(LLMConfigError, match="base_url"):
        load_model_config(ws)
    ws = write_cfg(tmp_path / "d", "models: {}\n")
    with pytest.raises(LLMConfigError):
        load_model_config(ws)


@pytest.mark.parametrize("entry,remote", [
    ("{provider: claude-cli, model: sonnet}", True),
    ("{provider: anthropic, model: m}", True),
    ("{provider: openai-compatible, model: m, base_url: 'https://openrouter.ai/api/v1'}", True),
    ("{provider: openai-compatible, model: m, base_url: 'http://localhost:11434/v1'}", False),
    ("{provider: openai-compatible, model: m, base_url: 'http://127.0.0.1:8000/v1'}", False),
    ("{provider: fake, responses: ['{}']}", False),
])
def test_privacy_no_remote(tmp_path, entry, remote):
    ws = write_cfg(tmp_path / "ws", f"models:\n  default: {entry}\nprivacy: {{no_remote: true}}\n")
    if remote:
        with pytest.raises(PrivacyError):
            load_model_config(ws)
    else:
        assert load_model_config(ws).no_remote is True
    ws2 = write_cfg(tmp_path / "ws2", f"models:\n  default: {entry}\n")
    assert load_model_config(ws2).is_remote is remote


def test_privacy_enforced_at_run_too():
    cfg = ModelConfig(provider="anthropic", model="m", no_remote=True)
    with pytest.raises(PrivacyError):
        run_task("_echo", {"metin": "x"}, cfg)


def test_no_provider_or_model_hardcoded():
    with pytest.raises(TypeError):
        ModelConfig()  # sağlayıcı zorunlu, varsayılanı yok
    assert ModelConfig(provider="claude-cli").model is None


# --- JSON ayıklama ----------------------------------------------------------

@pytest.mark.parametrize("text", [
    '{"a": 1}',
    '```json\n{"a": 1}\n```',
    'İşte sonuç:\n```\n{"a": 1}\n```\nUmarım yardımcı olur.',
    'Sonuç şu: {"a": 1} — bu kadar.',
    'Not: {kısa} değil, asıl yanıt {"a": 1}',
    '﻿  {"a": 1}  ',
    '```json\n{"a": 1}',  # kapanmamış çit
])
def test_extract_json_variants(text):
    assert extract_json(text) == {"a": 1}


def test_extract_json_nested_and_braces_in_strings():
    t = 'önce metin {"x": {"y": [1, 2]}, "s": "a } b {"} sonra'
    assert extract_json(t) == {"x": {"y": [1, 2]}, "s": "a } b {"}
    assert extract_json("liste: [1, 2] bitti", want="array") == [1, 2]


@pytest.mark.parametrize("text", ["", "   ", "JSON yok burada", '{"a": 1,,}', "[1, 2]"])
def test_extract_json_failures(text):
    with pytest.raises(ExtractError):
        extract_json(text)


# --- görev ve istem ---------------------------------------------------------

def test_load_echo_task_and_render():
    t = load_task("_echo")
    assert t.version == "1" and t.fields == ["metin"]
    out = render_prompt("A {{ metin }} B {{veri.n}} C {{liste}}",
                        {"metin": "x {{liste}} y", "veri": {"n": 3}, "liste": [1]})
    assert out == "A x {{liste}} y B 3 C [\n  1\n]"  # eklenen değer yeniden işlenmez
    with pytest.raises(Exception, match="eksik"):
        render_prompt("{{yok}}", {})


def _make_task(root: Path, schema: dict, prompt="Metin: {{metin}}", version="1") -> Path:
    d = root / "gorev"
    d.mkdir(parents=True, exist_ok=True)
    (d / "prompt.md").write_text(prompt, encoding="utf-8")
    (d / "output.schema.json").write_text(json.dumps(schema), encoding="utf-8")
    (d / "task.yaml").write_text(f"version: '{version}'\ndescription: test\n", encoding="utf-8")
    return d


# --- run_task (fake) uçtan uca -----------------------------------------------

def test_run_task_first_try():
    cfg = fake(GOOD)
    r = run_task("_echo", {"metin": "Bölüm kurulu toplandı."}, cfg)
    assert r.output == GOOD and r.attempts == 1 and not r.cached and r.model == "fake:t"
    sent = cfg._fake_calls[0]["messages"][0]["content"]
    assert "Bölüm kurulu toplandı." in sent and '"sozcuk_sayisi"' in sent  # şema isteme eklenir


def test_run_task_retry_feeds_error_back():
    bad_schema = json.dumps({"alinti": "x", "sozcuk_sayisi": "iki", "dil": "tr"})
    cfg = fake("Üzgünüm, JSON veremem.", "```json\n" + bad_schema + "\n```", "Tamam:\n" + json.dumps(GOOD))
    r = run_task("_echo", {"metin": "m"}, cfg)
    assert r.output == GOOD and r.attempts == 3 and len(r.errors) == 2
    assert "bulunamadı" in r.errors[0] and "sozcuk_sayisi" in r.errors[1]
    third = cfg._fake_calls[2]["messages"]
    assert [m["role"] for m in third] == ["user", "assistant", "user", "assistant", "user"]
    assert "sozcuk_sayisi" in third[-1]["content"] and "geçersiz" in third[-1]["content"]


def test_run_task_gives_up():
    cfg = fake("hayır", max_retries=1)
    with pytest.raises(TaskFailed) as ei:
        run_task("_echo", {"metin": "m"}, cfg)
    assert ei.value.attempts == 2 and ei.value.raw == "hayır" and len(cfg._fake_calls) == 2


def test_run_task_transient_provider_error_retried():
    cfg = fake(ProviderError("503", transient=True), GOOD)
    r = run_task("_echo", {"metin": "m"}, cfg)
    assert r.attempts == 2 and "sağlayıcı" in r.errors[0]
    cfg2 = fake(ProviderError("401 yetkisiz"), GOOD)
    with pytest.raises(ProviderError):
        run_task("_echo", {"metin": "m"}, cfg2)


def test_run_task_cache(tmp_path):
    cache = tmp_path / "cache"
    cfg = fake("ön söz " + json.dumps(GOOD))
    r1 = run_task("_echo", {"metin": "m"}, cfg, cache_dir=cache)
    r2 = run_task("_echo", {"metin": "m"}, cfg, cache_dir=cache)
    assert not r1.cached and r2.cached and r2.output == GOOD and r1.key == r2.key
    assert len(cfg._fake_calls) == 1
    # farklı girdi, farklı model → yeni çağrı
    run_task("_echo", {"metin": "başka"}, cfg, cache_dir=cache)
    other = ModelConfig(provider="fake", model="u", responses=[GOOD])
    r3 = run_task("_echo", {"metin": "m"}, other, cache_dir=cache)
    assert not r3.cached and len(cfg._fake_calls) == 2
    # refresh önbelleği okumaz
    r4 = run_task("_echo", {"metin": "m"}, cfg, cache_dir=cache, refresh=True)
    assert not r4.cached and len(cfg._fake_calls) == 3
    # geçersiz yanıt önbelleğe yazılmaz
    n_files = len(list(cache.rglob("*.json")))
    with pytest.raises(TaskFailed):
        run_task("_echo", {"metin": "yeni"}, fake("yok", max_retries=0), cache_dir=cache)
    assert len(list(cache.rglob("*.json"))) == n_files


def test_cache_key_depends_on_task_version(tmp_path):
    schema = {"type": "object", "properties": {"k": {"type": "string"}}, "required": ["k"]}
    cache = tmp_path / "c"
    cfg = fake({"k": "v"})
    t1 = _make_task(tmp_path / "v1", schema, version="1")
    t2 = _make_task(tmp_path / "v2", schema, version="2")
    a = run_task(t1, {"metin": "x"}, cfg, cache_dir=cache)
    b = run_task(t2, {"metin": "x"}, cfg, cache_dir=cache)
    assert a.key != b.key and not b.cached


def test_corrupt_cache_ignored(tmp_path):
    cache = tmp_path / "c"
    cfg = fake(GOOD)
    r = run_task("_echo", {"metin": "m"}, cfg, cache_dir=cache)
    p = cache / r.key[:2] / f"{r.key}.json"
    p.write_text("{bozuk", encoding="utf-8")
    r2 = run_task("_echo", {"metin": "m"}, cfg, cache_dir=cache)
    assert not r2.cached and r2.output == GOOD


def test_array_schema_task(tmp_path):
    t = _make_task(tmp_path, {"type": "array", "items": {"type": "integer"}, "minItems": 1})
    r = run_task(t, {"metin": "x"}, fake("Sonuç: [3, 4]"))
    assert r.output == [3, 4]


# --- HTTP sağlayıcılar (urlopen taklidi, ağ yok) ------------------------------

class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _capture_urlopen(monkeypatch, reply: dict):
    seen = {}

    def urlopen(req, timeout=None):
        seen["url"] = req.full_url
        seen["headers"] = {k.lower(): v for k, v in req.header_items()}
        seen["body"] = json.loads(req.data.decode("utf-8"))
        return _Resp(json.dumps(reply).encode("utf-8"))

    monkeypatch.setattr(P.urllib.request, "urlopen", urlopen)
    return seen


def test_openai_compatible_request(monkeypatch):
    seen = _capture_urlopen(monkeypatch, {"choices": [{"message": {"content": json.dumps(GOOD)}}],
                                          "usage": {"total_tokens": 7}})
    monkeypatch.setenv("BIDR_TEST_KEY", "gizli")
    cfg = ModelConfig(provider="openai-compatible", model="yerel-model", base_url="http://localhost:11434/v1/",
                      api_key_env="BIDR_TEST_KEY", temperature=0, params={"seed": 1})
    r = run_task("_echo", {"metin": "m"}, cfg)
    assert r.output == GOOD and r.usage["total_tokens"] == 7
    assert seen["url"] == "http://localhost:11434/v1/chat/completions"
    assert seen["headers"]["authorization"] == "Bearer gizli"
    b = seen["body"]
    assert b["model"] == "yerel-model" and b["temperature"] == 0 and b["seed"] == 1
    assert b["messages"][0]["role"] == "system" and b["messages"][1]["role"] == "user"


def test_anthropic_request(monkeypatch):
    seen = _capture_urlopen(monkeypatch, {"type": "message",
                                          "content": [{"type": "text", "text": json.dumps(GOOD)}]})
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sahte-anahtar")
    cfg = ModelConfig(provider="anthropic", model="secilen-model")
    r = run_task("_echo", {"metin": "m"}, cfg)
    assert r.output == GOOD and r.model == "anthropic:secilen-model"
    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["headers"]["x-api-key"] == "sahte-anahtar" and "anthropic-version" in seen["headers"]
    assert seen["body"]["max_tokens"] > 0 and seen["body"]["system"]


def test_anthropic_without_key_fails(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="anahtar yok"):
        P.get_provider(ModelConfig(provider="anthropic", model="m")).complete("s", [{"role": "user", "content": "x"}])


def test_http_error_transient(monkeypatch):
    import urllib.error

    def urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 503, "busy", {}, io.BytesIO(b"busy"))

    monkeypatch.setattr(P.urllib.request, "urlopen", urlopen)
    cfg = ModelConfig(provider="openai-compatible", model="m", base_url="http://localhost:1/v1")
    with pytest.raises(ProviderError) as ei:
        P.get_provider(cfg).complete("s", [{"role": "user", "content": "x"}])
    assert ei.value.transient


# --- claude-cli (sahte çalıştırılabilirle) ------------------------------------

FAKE_CLAUDE = r'''#!{py}
import json, os, sys
prompt = sys.stdin.read()
log = os.environ["BIDR_FAKE_CLAUDE_LOG"]
with open(log, "a", encoding="utf-8") as f:
    f.write(json.dumps({{"argv": sys.argv[1:], "prompt": prompt, "cwd": os.getcwd(),
        "env_key": os.environ.get("ANTHROPIC_API_KEY"), "env_bedrock": os.environ.get("CLAUDE_CODE_USE_BEDROCK")}}) + "\n")
n = sum(1 for _ in open(log, encoding="utf-8"))
if n == 1:
    result = "Elbette! İşte yanıt: {{\"alinti\": \"x\"}}"
else:
    result = "```json\n" + json.dumps({{"alinti": "kurul", "sozcuk_sayisi": 1, "dil": "tr"}}) + "\n```"
print(json.dumps({{"type": "result", "is_error": False, "result": result, "total_cost_usd": 0.0}}))
'''


@pytest.fixture
def fake_claude(tmp_path, monkeypatch):
    exe = tmp_path / "claude"
    exe.write_text(FAKE_CLAUDE.format(py=sys.executable), encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("BIDR_FAKE_CLAUDE_LOG", str(log))
    return exe, log


def test_claude_cli_flags_stdin_retry_and_env_scrub(fake_claude, monkeypatch):
    exe, log = fake_claude
    monkeypatch.setenv("ANTHROPIC_API_KEY", "faturali-anahtar")
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    cfg = ModelConfig(provider="claude-cli", model="secilen", command=str(exe), args=["--effort", "low"],
                      retry_backoff=0)
    r = run_task("_echo", {"metin": "Bölüm kurulu"}, cfg)
    assert r.output["alinti"] == "kurul" and r.attempts == 2 and r.model == "claude-cli:secilen"
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    argv = calls[0]["argv"]
    assert argv[0] == "-p" and argv[argv.index("--output-format") + 1] == "json"
    assert argv[argv.index("--model") + 1] == "secilen" and argv[-2:] == ["--effort", "low"]
    assert argv[argv.index("--tools") + 1] == "" and "--system-prompt" in argv
    assert "Bölüm kurulu" in calls[0]["prompt"]                 # istem stdin'den
    assert "ÖNCEKİ YANITIN" in calls[1]["prompt"] and "sozcuk_sayisi" in calls[1]["prompt"]
    assert all(c["env_key"] is None and c["env_bedrock"] is None for c in calls)  # faturalı API'ye düşmez
    assert Path(calls[0]["cwd"]).resolve() != Path.cwd().resolve()


def test_claude_cli_api_key_passthrough_only_when_allowed(fake_claude, monkeypatch):
    exe, log = fake_claude
    monkeypatch.setenv("ANTHROPIC_API_KEY", "izinli")
    cfg = ModelConfig(provider="claude-cli", command=str(exe), allow_api_key=True)
    P.get_provider(cfg).complete("s", [{"role": "user", "content": "x"}])
    call = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert call["env_key"] == "izinli" and "--model" not in call["argv"]  # model verilmezse CLI'nin seçimi


def test_claude_cli_error_output(tmp_path):
    exe = tmp_path / "claude"
    exe.write_text(f"#!{sys.executable}\nimport sys; sys.stdin.read(); print('kimlik doğrulama gerekli'); sys.exit(1)\n")
    exe.chmod(0o755)
    with pytest.raises(ProviderError, match="kimlik"):
        P.get_provider(ModelConfig(provider="claude-cli", command=str(exe))).complete(
            "s", [{"role": "user", "content": "x"}])


# --- CLI ----------------------------------------------------------------------

def test_cli_run_and_check(tmp_path, capsys):
    from bidr.cli import main

    ws = write_cfg(tmp_path / "ws", "models:\n  default:\n    provider: fake\n    responses:\n"
                   "      - '{\"alinti\": \"a\", \"sozcuk_sayisi\": 1, \"dil\": \"tr\"}'\n")
    inp = tmp_path / "in.json"
    inp.write_text(json.dumps({"metin": "a"}), encoding="utf-8")
    assert main(["llm", "run", "_echo", "--input", str(inp), "-w", str(ws)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["output"]["dil"] == "tr" and out["cached"] is False
    assert main(["llm", "run", "_echo", "--input", str(inp), "-w", str(ws)]) == 0
    assert json.loads(capsys.readouterr().out)["cached"] is True
    assert (ws / ".cache" / "llm").is_dir()
    assert main(["llm", "check", "-w", str(ws)]) == 0
    assert "erişim tamam" in capsys.readouterr().out


def test_cli_check_reports_privacy_violation(tmp_path, capsys):
    from bidr.cli import main

    ws = write_cfg(tmp_path / "ws", "models:\n  default: {provider: claude-cli}\nprivacy: {no_remote: true}\n")
    assert main(["llm", "check", "-w", str(ws), "--no-call"]) == 2
    assert "no_remote" in capsys.readouterr().out


# --- ajan modu: sağlayıcısız render/validate ---------------------------------

def test_render_task_matches_run_task_prompt():
    from bidr.llm import render_task

    r = render_task("_echo", {"metin": "Bölüm kurulu toplandı."})
    assert (r["task"], r["version"]) == ("_echo", "1") and r["schema"]["required"]
    assert "Bölüm kurulu toplandı." in r["prompt"] and '"sozcuk_sayisi"' in r["prompt"]
    cfg = fake(GOOD)
    run_task("_echo", {"metin": "Bölüm kurulu toplandı."}, cfg)
    assert cfg._fake_calls[0]["messages"][0]["content"] == r["prompt"]
    assert cfg._fake_calls[0]["system"] == r["system"]


@pytest.mark.parametrize("raw,ok", [
    ("Ajanın cevabı:\n```json\n" + json.dumps(GOOD) + "\n```", True),
    (GOOD, True),
    ({"alinti": "x", "sozcuk_sayisi": "iki", "dil": "tr"}, False),
    ("JSON yok", False),
    (42, False),
])
def test_validate_output(raw, ok):
    from bidr.llm import validate_output

    out, errs = validate_output("_echo", raw)
    if ok:
        assert out == GOOD and errs == []
    else:
        assert out is None and errs


def test_cache_key_includes_generation_params(tmp_path):
    t = load_task("_echo")
    from bidr.llm.runner import cache_key

    base = ModelConfig(provider="claude-cli", model="m")
    k0 = cache_key(t, "p", "s", base)
    assert k0 == cache_key(t, "p", "s", ModelConfig(provider="claude-cli", model="m", timeout=5))
    keys = {k0,
            cache_key(t, "p", "s", ModelConfig(provider="claude-cli", model="m", temperature=0)),
            cache_key(t, "p", "s", ModelConfig(provider="claude-cli", model="m", temperature=0.7)),
            cache_key(t, "p", "s", ModelConfig(provider="claude-cli", model="m", max_tokens=100)),
            cache_key(t, "p", "s", ModelConfig(provider="claude-cli", model="m", params={"seed": 1}))}
    assert len(keys) == 5
