"""Ölçüt veri modeli (salt okunur dataclass'lar)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Area:
    id: str
    title: str
    description: tuple[str, ...] = ()


@dataclass(frozen=True)
class Criterion:
    """Ana ölçüt (ör. A.1)."""
    id: str
    title: str
    parent: str
    description: tuple[str, ...] = ()


@dataclass(frozen=True)
class SubCriterion:
    """Alt ölçüt (ör. A.1.2): kanıtların eşlendiği birim."""
    id: str
    title: str
    parent: str
    description: tuple[str, ...]
    units: str
    rubric: dict[int, str]
    example_evidence: tuple[str, ...]
    units_note: tuple[str, ...] = ()

    @property
    def area(self) -> str:
        return self.id.split(".")[0]


def id_key(cid: str) -> tuple:
    """'B.1.10' gibi kimlikleri doğal sırayla sıralamak için anahtar."""
    head, *nums = cid.split(".")
    return (head, *(int(n) for n in nums))


@dataclass
class CriteriaSet:
    meta: dict
    areas: list[Area]
    criteria: list[Criterion]
    sub_criteria: list[SubCriterion]
    _index: dict[str, object] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        for x in (*self.areas, *self.criteria, *self.sub_criteria):
            self._index[x.id] = x

    def get(self, cid: str):
        """A, A.1 veya A.1.2 kimliğiyle öğe; yoksa KeyError."""
        return self._index[cid.strip().rstrip(".")]

    def children(self, cid: str) -> list:
        pool = self.criteria if cid in {a.id for a in self.areas} else self.sub_criteria
        return [x for x in pool if x.parent == cid]

    def __len__(self) -> int:
        return len(self.sub_criteria)

    def __iter__(self):
        return iter(self.sub_criteria)
