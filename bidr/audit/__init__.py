"""`bidr audit`: ölçüt düzeyinde OD toplama, eksik kanıt raporu ve inceleme tablosu.

Belirleyici (model yok). Kurallar: `docs/AUDIT.md`, `bidr/audit/rules.py`.
"""
from .rules import LINKS, criterion_od
from .run import audit, build

__all__ = ["LINKS", "audit", "build", "criterion_od"]
