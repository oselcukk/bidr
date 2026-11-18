"""`bidr llm`: model yapılandırmasını sınama ve tek görev çalıştırma.

    bidr llm check -w WS [--role R] [--no-call]
    bidr llm run TASK --input girdi.json -w WS [--role R] [--no-cache] [--refresh]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _cache_dir(ws_root: Path) -> Path:
    return ws_root / ".cache" / "llm"


def _check(args) -> int:
    from bidr.common import Workspace

    from .config import LLMError, configured_roles, load_model_config
    from .runner import run_task

    ws = Workspace(args.workspace)
    try:
        roles = [args.role] if args.role else (configured_roles(ws) or ["default"])
    except LLMError as e:
        print(f"HATA: {e}")
        return 2
    rc = 0
    for role in roles:
        try:
            cfg = load_model_config(ws, role)
        except LLMError as e:
            print(f"[{role}] HATA: {e}")
            rc = 2
            continue
        d = cfg.describe()
        line = f"[{role}] {d['id']} uzak={'evet' if d['remote'] else 'hayır'}"
        if d.get("api_key_env"):
            line += f" anahtar=${d['api_key_env']}"
        print(line)
        if args.no_call:
            continue
        try:
            res = run_task("_echo", {"metin": "Bölüm kurulu toplantısı yapıldı."}, cfg, cache_dir=None)
            print(f"[{role}]   erişim tamam: {res.attempts} deneme, "
                  f"çıktı {json.dumps(res.output, ensure_ascii=False)}")
        except LLMError as e:
            print(f"[{role}]   ERİŞİM HATASI: {e}")
            rc = 1
    return rc


def _run(args) -> int:
    from bidr.common import Workspace

    from .config import LLMError, load_model_config
    from .runner import TaskFailed, run_task

    ws = Workspace(args.workspace)
    try:
        inputs = json.loads(Path(args.input).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"girdi okunamadı: {e}", file=sys.stderr)
        return 2
    if not isinstance(inputs, dict):
        print("girdi bir JSON nesnesi olmalı", file=sys.stderr)
        return 2
    try:
        cfg = load_model_config(ws, args.role)
        res = run_task(args.task, inputs, cfg, cache_dir=None if args.no_cache else _cache_dir(ws.root),
                       refresh=args.refresh)
    except TaskFailed as e:
        print(f"BAŞARISIZ: {e}", file=sys.stderr)
        if e.raw is not None:
            print(f"son ham yanıt:\n{e.raw[:2000]}", file=sys.stderr)
        return 1
    except LLMError as e:
        print(f"HATA: {e}", file=sys.stderr)
        return 2
    print(json.dumps(res.to_dict(), ensure_ascii=False, indent=2))
    return 0


def register(sub):
    p = sub.add_parser("llm", help="model katmanı: yapılandırmayı sına, görev çalıştır")
    s = p.add_subparsers(dest="llm_command", required=True)

    c = s.add_parser("check", help="config.yaml'ı ve sağlayıcıya erişimi sınar (küçük bir _echo çağrısı)")
    c.add_argument("--workspace", "-w", required=True)
    c.add_argument("--role", help="yalnız bu rol (vars. config'teki tüm roller)")
    c.add_argument("--no-call", action="store_true", help="modeli çağırma, yalnız yapılandırmayı denetle")
    c.set_defaults(func=_check)

    r = s.add_parser("run", help="tek görev çalıştır, doğrulanmış çıktıyı yazdır")
    r.add_argument("task", help="görev adı (bidr/tasks/<ad>) ya da görev klasörü yolu")
    r.add_argument("--input", required=True, help="girdi alanları (JSON nesnesi)")
    r.add_argument("--workspace", "-w", required=True)
    r.add_argument("--role", default="default", help="config'teki model rolü (vars. default)")
    r.add_argument("--no-cache", action="store_true", help="önbelleği kullanma")
    r.add_argument("--refresh", action="store_true", help="önbellekten okuma, yeniden sor (sonucu yazar)")
    r.set_defaults(func=_run)
