"""Skill aynaları. Tek kaynak: repo kökündeki `.agents/skills/bidr-*`.

Aynalar (`.claude/skills/`, `.kiro/skills/`) bağlantı değil KOPYADIR: Windows'ta git
sembolik bağlantıları geliştirici modu ve `core.symlinks` ister, zip indirmede kaybolur.
Kopyaların kaynağa eşitliğini `tests/test_agent_files.py` denetler; eşitlemek için:

    python -m bidr.init.skills
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

PREFIX = "bidr-"
MIRRORS = (".claude/skills", ".kiro/skills")


def source_dir(repo: Path) -> Path:
    return repo / ".agents" / "skills"


def skill_dirs(repo: Path) -> list[Path]:
    d = source_dir(repo)
    return sorted(p for p in d.glob(f"{PREFIX}*") if (p / "SKILL.md").exists()) if d.exists() else []


def copy_skills(repo: Path, dest_root: Path, targets=(".agents/skills",) + MIRRORS) -> list[Path]:
    """`bidr-*` skill klasörlerini `dest_root/<hedef>/` altına kopyalar (yalnız bidr-* yenilenir)."""
    out = []
    for t in targets:
        dst = dest_root / t
        if dst.resolve() == source_dir(repo).resolve():
            continue
        dst.mkdir(parents=True, exist_ok=True)
        for s in skill_dirs(repo):
            target = dst / s.name
            if target.is_symlink() or target.is_file():
                target.unlink()
            elif target.exists():
                shutil.rmtree(target)
            shutil.copytree(s, target)
            out.append(target)
    return out


def sync_repo(repo: Path) -> list[Path]:
    return copy_skills(repo, repo, MIRRORS)


def main() -> int:
    from .config import repo_root
    repo = repo_root()
    if repo is None:
        print("bidr reposu bulunamadı (düzenlenebilir kurulum değil)", file=sys.stderr)
        return 2
    for p in sync_repo(repo):
        print(p.relative_to(repo))
    return 0


if __name__ == "__main__":
    sys.exit(main())
