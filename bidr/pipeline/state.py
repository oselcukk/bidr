"""Aşama durumu: `pipeline.yaml` sözleşmesi + çalışma alanı dosyaları → her aşama için
bitti / bekliyor / engelli / atlandi / yok. Salt okunur."""
from __future__ import annotations

import shlex
import shutil
import sys
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from bidr.common import Workspace
from bidr.init.config import load_section

from .checks import CHECKS, Check, Ctx

SPEC = Path(__file__).resolve().parents[1] / "data" / "pipeline.yaml"
BITTI, BEKLIYOR, ENGELLI, ATLANDI, YOK = "bitti", "bekliyor", "engelli", "atlandi", "yok"
DONE = (BITTI, ATLANDI)


@lru_cache(maxsize=1)
def load_spec(path: str | None = None) -> dict:
    raw = yaml.safe_load(Path(path or SPEC).read_text(encoding="utf-8"))
    ids = [s["id"] for s in raw["asamalar"]]
    if len(ids) != len(set(ids)):
        raise ValueError("pipeline.yaml: yinelenen aşama kimliği")
    seen: set[str] = set()
    for s in raw["asamalar"]:
        for o in s.get("onkosul") or []:
            if o not in seen:
                raise ValueError(f"pipeline.yaml: {s['id']} önkoşulu {o} ondan önce tanımlı değil")
        if s["sart"]["denetim"] not in CHECKS:
            raise ValueError(f"pipeline.yaml: bilinmeyen denetim {s['sart']['denetim']}")
        if not isinstance(s.get("istege_bagli", False), bool):
            raise ValueError(f"pipeline.yaml: {s['id']} istege_bagli true|false olmalı")
        if s.get("onay") not in ("yok", "insan"):
            raise ValueError(f"pipeline.yaml: {s['id']} onay yok|insan olmalı")
        seen.add(s["id"])
    return raw


def stage(sid: str) -> dict:
    for s in load_spec()["asamalar"]:
        if s["id"] == sid:
            return s
    raise KeyError(sid)


def bidr_command() -> str:
    """Komutlarda kullanılacak `bidr` çağrısı: PATH'teyse `bidr`, değilse tam yol."""
    here = Path(sys.executable).parent / ("bidr.exe" if sys.platform == "win32" else "bidr")
    on_path = shutil.which("bidr")
    if on_path and (not here.exists() or Path(on_path).resolve() == here.resolve()):
        return "bidr"
    if here.exists():
        return shlex.quote(str(here))
    return f"{shlex.quote(sys.executable)} -m bidr.cli"


def formatter(ws: Workspace, sec: dict | None):
    q = shlex.quote
    sec = sec or {}
    exe = bidr_command()
    vals = {
        "ws": q(str(ws.root)),
        "kaynak": q(sec.get("kaynak") or "<kaynak>"),
        "profil": q(sec.get("profil") or "<profil>"),
        "donem": str(sec.get("donem") or "<yıl>"),
        "kurum_arg": f" --institution {q(sec['kurum'])}" if sec.get("kurum") else "",
        "etiket_birim": q(sec.get("etiket_birim") or sec.get("birim") or "<birim>"),
        "egitim_arg": "".join(f" --train {q(e)}" for e in sec.get("egitim") or []),
        "ajan": q(sec["ajan"]) if sec.get("ajan") else "<ajan-adı>",
    }

    def fmt(t: str) -> str:
        out = t
        for k, v in vals.items():
            out = out.replace("{" + k + "}", v)
        return exe + out[4:] if out.startswith("bidr ") else out
    return fmt


@dataclass
class StageState:
    id: str
    ad: str
    durum: str
    kim: str | None
    neden: str
    komutlar: list[str]
    sart: str
    onay: str
    katman: str
    skill: str | None
    ilerleme: dict = field(default_factory=dict)
    uyarilar: list[str] = field(default_factory=list)


@dataclass
class Report:
    calisma_alani: str
    yonetilen: bool
    asamalar: list[StageState]

    def get(self, sid: str) -> StageState:
        return next(s for s in self.asamalar if s.id == sid)

    @property
    def sonraki(self) -> StageState | None:
        return next((s for s in self.asamalar if s.durum not in DONE), None)

    def to_dict(self) -> dict:
        n = self.sonraki
        return {"calisma_alani": self.calisma_alani, "yonetilen": self.yonetilen,
                "asamalar": [asdict(s) for s in self.asamalar],
                "sonraki": asdict(n) if n else None}


def evaluate(ws_root: Path, *, until: str | None = None) -> Report:
    """Aşamaları sırayla değerlendirir. `until` verilirse o aşamada durur (kapılar için)."""
    ws = Workspace(ws_root)
    sec = load_section(ws.root)
    fmt = formatter(ws, sec)
    states: dict[str, StageState] = {}
    for s in load_spec()["asamalar"]:
        base = dict(id=s["id"], ad=s["ad"], sart=" ".join(s["sart"]["metin"].split()), onay=s["onay"],
                    katman=s["katman"], skill=s.get("skill"))
        default_cmds = [fmt(k) for k in s.get("komut") or []]
        blocked = [o for o in s.get("onkosul") or [] if states[o].durum not in DONE]
        if not s.get("uygulandi", True) and s.get("istege_bagli"):
            st = StageState(**base, durum=ATLANDI, kim=None, komutlar=[],
                            neden="isteğe bağlı aşama henüz uygulanmadı; hat atlayarak sürer")
        elif not s.get("uygulandi", True):
            st = StageState(**base, durum=YOK, kim=None, komutlar=[],
                            neden="henüz uygulanmadı: hat bu aşamada biter")
        elif blocked:
            st = StageState(**base, durum=ENGELLI, kim=None, komutlar=default_cmds,
                            neden="önce bitmeli: " + ", ".join(blocked))
        elif sec is None and s["id"] != "kurulum":
            st = StageState(**base, durum=ENGELLI, kim=None, komutlar=default_cmds,
                            neden="çalışma alanı kurulmamış (bidr init)")
        else:
            ck: Check = CHECKS[s["sart"]["denetim"]](Ctx(ws, sec, fmt, s))
            durum = ATLANDI if ck.atlandi else BITTI if ck.bitti else BEKLIYOR
            cmds = [] if durum in DONE else (ck.komutlar if ck.komutlar is not None else default_cmds)
            st = StageState(**base, durum=durum, kim=None if durum in DONE else ck.kim,
                            neden=ck.neden, komutlar=cmds, ilerleme=ck.ilerleme, uyarilar=ck.uyarilar)
        states[s["id"]] = st
        if until and s["id"] == until:
            break
    return Report(str(ws.root), sec is not None, list(states.values()))
