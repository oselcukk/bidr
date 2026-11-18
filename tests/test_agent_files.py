"""Ajan dosyaları: skill'ler, aynaları, AGENTS.md / CLAUDE.md tutarlılığı."""
from __future__ import annotations

import filecmp
from pathlib import Path

import yaml

from bidr.init.skills import MIRRORS, skill_dirs
from bidr.pipeline import load_spec

REPO = Path(__file__).resolve().parents[1]
SKILLS = {"bidr-kur", "bidr-rapor", "bidr-hakem"}


def _front(p: Path) -> dict:
    t = p.read_text(encoding="utf-8")
    assert t.startswith("---\n")
    return yaml.safe_load(t.split("---\n", 2)[1])


def test_skills_exist_with_frontmatter():
    got = {p.name for p in skill_dirs(REPO)}
    assert got == SKILLS
    for p in skill_dirs(REPO):
        fm = _front(p / "SKILL.md")
        assert fm["name"] == p.name
        assert "Tetik" in fm["description"] and "Kullanma" in fm["description"]


def test_mirrors_are_identical_copies():
    for m in MIRRORS:
        for s in SKILLS:
            a, b = REPO / ".agents/skills" / s / "SKILL.md", REPO / m / s / "SKILL.md"
            assert b.exists() and not b.is_symlink(), f"{m}/{s}: `python -m bidr.init.skills` çalıştırın"
            assert filecmp.cmp(a, b, shallow=False), f"{m}/{s} farklı: `python -m bidr.init.skills`"


def test_agents_md_routes_to_every_skill_and_stage_skill():
    agents = (REPO / "AGENTS.md").read_text(encoding="utf-8")
    ws_agents = (REPO / "bidr/data/workspace/AGENTS.md").read_text(encoding="utf-8")
    for s in SKILLS:
        assert s in agents and s in ws_agents
    assert (REPO / "CLAUDE.md").read_text(encoding="utf-8").strip() == "@AGENTS.md"
    for s in load_spec()["asamalar"]:
        if s.get("skill"):
            assert s["skill"] in SKILLS
    for rule in ("Dosya adı", "salt okunur", "Ücretli API", "alıntı"):
        assert rule.lower() in agents.lower() and rule.lower() in ws_agents.lower(), rule
