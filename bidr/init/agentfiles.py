"""`bidr init`'in çalışma alanına yazdığı ajan dosyaları: AGENTS.md, CLAUDE.md, skill
kopyaları ve isteğe bağlı Claude Code hook'u. Kullanıcının kendi dosyasının üzerine yazmaz."""
from __future__ import annotations

import json
import shlex
from pathlib import Path

from .config import data_dir, repo_root

MARK = "<!-- bidr:yonetilen"


def _render_agents(ws: Path, sec: dict, bidr: str) -> str:
    t = (data_dir() / "workspace" / "AGENTS.md").read_text(encoding="utf-8")
    vals = {"birim": sec["birim"], "donem": str(sec["donem"]), "profil": sec["profil"],
            "kaynak": sec["kaynak"], "bidr": bidr, "ws_q": shlex.quote(str(ws))}
    for k, v in vals.items():
        t = t.replace("{" + k + "}", v)
    return t


def _write_managed(p: Path, text: str, notes: list[str]) -> None:
    if p.exists():
        old = p.read_text(encoding="utf-8")
        if old == text:
            return
        if not old.startswith(MARK):
            notes.append(f"{p.name} kullanıcıya ait (bidr işareti yok); dokunulmadı")
            return
    p.write_text(text, encoding="utf-8")
    notes.append(f"yazıldı: {p.name}")


def hook_settings(ws: Path, bidr: str) -> dict:
    cmd = f"{bidr} status -w {shlex.quote(str(ws))} --kisa || true"
    return {"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": cmd}]}]}}


def write_workspace_files(ws: Path, sec: dict, *, claude_hook: bool = False) -> list[str]:
    from bidr.pipeline.state import bidr_command

    from .skills import copy_skills
    notes: list[str] = []
    bidr = bidr_command()
    _write_managed(ws / "AGENTS.md", _render_agents(ws, sec, bidr), notes)
    cl = ws / "CLAUDE.md"
    if not cl.exists():
        cl.write_text("@AGENTS.md\n", encoding="utf-8")
        notes.append("yazıldı: CLAUDE.md")
    elif "@AGENTS.md" not in cl.read_text(encoding="utf-8"):
        notes.append("CLAUDE.md kullanıcıya ait ve @AGENTS.md içermiyor; dokunulmadı (elle `@AGENTS.md` ekleyin)")
    repo = repo_root()
    if repo is None:
        notes.append("skill kaynağı (.agents/skills) bulunamadı: skill'ler kopyalanmadı")
    else:
        n = len(copy_skills(repo, ws))
        notes.append(f"skill kopyaları: .agents/skills, .claude/skills, .kiro/skills ({n} klasör)")
    if claude_hook:
        sp = ws / ".claude" / "settings.json"
        want = hook_settings(ws, bidr)
        if sp.exists():
            notes.append(".claude/settings.json zaten var; değiştirilmedi. Eklenecek hook: "
                         + json.dumps(want, ensure_ascii=False))
        else:
            sp.parent.mkdir(parents=True, exist_ok=True)
            sp.write_text(json.dumps(want, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            notes.append("isteğe bağlı hook yazıldı: .claude/settings.json (SessionStart → bidr status --kisa)")
    return notes
