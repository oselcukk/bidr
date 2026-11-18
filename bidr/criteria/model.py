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


# Şablonda "Örnek Kanıtlar" listesine karışmış dipnot satırı (kanıt değil).
_FOOTNOTE_PREFIX = "*"


@dataclass(frozen=True)
class EvidenceSlot:
    """Kanıt yuvası: bir alt ölçütün "Örnek Kanıtlar" maddelerinden biri.

    Kimlik `<alt ölçüt>/<sıra>` (1'den başlar, şablon sırası; ör. `A.2.2/4`).
    `text` şablondan birebirdir. `footnote` = madde bir kanıt değil, dipnottur
    (ör. "* 2015 AKTS Kullanıcı Kılavuzu..."); kimliği korunur ama eşlemeye girmez.
    """
    id: str
    criterion: str
    index: int
    text: str

    @property
    def footnote(self) -> bool:
        return self.text.lstrip().startswith(_FOOTNOTE_PREFIX)


def slot_id(criterion: str, index: int) -> str:
    return f"{criterion}/{index}"


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

    @property
    def slots(self) -> tuple[EvidenceSlot, ...]:
        return tuple(EvidenceSlot(slot_id(self.id, i), self.id, i, t)
                     for i, t in enumerate(self.example_evidence, 1))


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

    def slots(self, *, include_footnotes: bool = True) -> list[EvidenceSlot]:
        """Tüm kanıt yuvaları (alt ölçüt sırası, sonra madde sırası)."""
        return [x for s in self.sub_criteria for x in s.slots
                if include_footnotes or not x.footnote]

    def get_slot(self, sid: str) -> EvidenceSlot:
        """`A.2.2/4` kimliğiyle yuva; yoksa KeyError."""
        crit, _, idx = sid.strip().partition("/")
        if not idx.isdigit():
            raise KeyError(sid)
        sub = self._index[crit]
        i = int(idx)
        if not hasattr(sub, "example_evidence") or not 1 <= i <= len(sub.example_evidence):
            raise KeyError(sid)
        return sub.slots[i - 1]

    def children(self, cid: str) -> list:
        pool = self.criteria if cid in {a.id for a in self.areas} else self.sub_criteria
        return [x for x in pool if x.parent == cid]

    def __len__(self) -> int:
        return len(self.sub_criteria)

    def __iter__(self):
        return iter(self.sub_criteria)
