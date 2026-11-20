"""Yapılandırılabilir tablolar: tekrarlayan belge türleri ve "kimden istenir" (YAML)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from bidr.identify.text import fold

DATA = Path(__file__).resolve().parents[1] / "data"
TURLER_FILE = DATA / "ihtiyac_turler.yaml"
SORUMLULAR_FILE = DATA / "ihtiyac_sorumlular.yaml"


def norm(s: str | None) -> str:
    """Türkçe harfsiz, küçük harf, tek boşluk."""
    return " ".join(fold(s or "").split())


@dataclass(frozen=True)
class TekrarTur:
    id: str
    ad: str
    belge_turleri: frozenset[str]
    desen: tuple[re.Pattern, ...]
    siklik: str

    def uyar(self, doc_type: str | None, metin: str) -> bool:
        if doc_type not in self.belge_turleri:
            return False
        return not self.desen or any(p.search(metin) for p in self.desen)


class Turler:
    def __init__(self, path: Path | str | None = None):
        raw = yaml.safe_load(Path(path or TURLER_FILE).read_text(encoding="utf-8")) or {}
        self.turler: list[TekrarTur] = []
        for r in raw.get("turler") or []:
            self.turler.append(TekrarTur(
                id=str(r["id"]), ad=str(r.get("ad") or r["id"]),
                belge_turleri=frozenset(r.get("belge_turleri") or []),
                desen=tuple(re.compile(norm(d).replace(" ", r"\s*")) for d in r.get("desen") or []),
                siklik=str(r.get("siklik") or "")))
        self.by_id = {t.id: t for t in self.turler}

    def bul(self, doc_type: str | None, metin: str) -> TekrarTur | None:
        """Belgenin tekrarlayan türü (ilk uyan kayıt) ya da None. `metin`: ad + başlık + baş bölge."""
        m = norm(metin)
        for t in self.turler:
            if t.uyar(doc_type, m):
                return t
        return None


class Sorumlular:
    def __init__(self, path: Path | str | None = None):
        raw = yaml.safe_load(Path(path or SORUMLULAR_FILE).read_text(encoding="utf-8")) or {}
        self.varsayilan = str(raw.get("varsayilan") or "Bölüm sekreterliği")
        self.belge_turu = {str(k): str(v) for k, v in (raw.get("belge_turu") or {}).items()}
        self.asama = {str(k): str(v) for k, v in (raw.get("asama") or {}).items()}
        self.alan = {str(k): str(v) for k, v in (raw.get("alan") or {}).items()}

    def kim(self, belge_turu: str | None = None, asama: str | None = None, olcut: str | None = None) -> str:
        if belge_turu and belge_turu in self.belge_turu:
            return self.belge_turu[belge_turu]
        if asama and asama in self.asama:
            return self.asama[asama]
        if olcut and olcut[:1] in self.alan:
            return self.alan[olcut[:1]]
        return self.varsayilan
