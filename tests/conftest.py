"""Ortak pytest ayarı.

Sandbox'lı ajan ortamında geçici klasör repo içindeki git dışı `_tmp/tmp`'ye alınabilir (README,
"Sandbox'lı ajan ortamı"; `tools/sandbox.sh pytest`). O zaman pytest'in `tmp_path`'i de repo
içinde kalır ve `bidr init` "çalışma alanı repo dışında olmalı" kuralıyla sınama çalışma alanlarını
reddeder. Kural gerçek kullanımda değişmez; yalnız testlerde, pytest'in temel klasörü repo
içindeyse o klasörün altı repo içi sayılmaz. Kuralın kendisi
`test_init_workspace_inside_source_or_repo`'da temel klasör dışındaki `_tmp/ws-sinama` ile sınanır.
"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _guncel_denetim_kapali(monkeypatch):
    """`bidr next`'in günlük güncellik denetimi testlerde ağa çıkmasın (tests/test_guncel.py açar)."""
    monkeypatch.setenv("BIDR_GUNCEL_DENETIM", "0")


@pytest.fixture(autouse=True)
def _tmp_repo_icinde(request, monkeypatch):
    from bidr.init import config

    repo = config.repo_root()
    base = Path(request.config._tmp_path_factory.getbasetemp()).resolve()
    orig = config._inside
    if repo is None or not orig(base, repo):
        return

    def inside(a: Path, b: Path) -> bool:
        if b == repo and orig(Path(a), base):
            return False
        return orig(a, b)

    monkeypatch.setattr(config, "_inside", inside)
