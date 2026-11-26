"""Karar aşamalarının (`coarse`/`fine`) paket girdisi parmak izi ve eski izlerle uyum.

`prepare` son tam eskime hesabında bu izi `work/_durum/<aşama>-yeniden.json`'a (`parmak`) yazar;
`bidr status` (bidr/pipeline/checks.py) izi yeniden hesaplar, tutmazsa prepare'i (onaysız, model çağrısı
yok) yeniden ister.

Şema 2 (`v2-<16 hex>`): istemi kuran kod dosyaları bayt olarak değil sözdizimi olarak girer — belge
dizgeleri, yorumlar ve biçim çıkarılmış ağacın metni (`ast.unparse`). Davranışı değiştirmeyen düzenleme
(modül/fonksiyon açıklaması, yorum, satır kırma) aşamaları eskitmez. Görev dosyaları (istem metni, şema),
ölçüt/profil verisi ve çalışma alanının girdileri bayt olarak girer: onların her baytı istemdir.

Şema 1 (önek yok, 16 hex): eski kayıt; kod baytları ham girer. Bu sürüme geçişte canlı çalışma alanları
eskimesin diye şema 1 iz yalnız şu iki koşulla geçerli sayılır (`uyumlu`):
  1. İz, dondurulmuş eski run.py (`parmak_eski/run-<sürüm>.py.gz`, o sürümün dosyasının birebir baytları)
     ve öbür girdilerin BUGÜNKÜ hâliyle şema 1'e göre yeniden hesaplanınca birebir tutar — yani öbür kod
     dosyaları, görev/ölçüt/profil verisi ve çalışma alanı girdileri iz yazıldığından beri değişmemiştir;
  2. bugünkü run.py ile dondurulmuş run.py'nin şema 2 sözdizimi aynıdır (`input_fingerprint` dışında:
     o fonksiyon izi hesaplar, istemi kurmaz) — yani aradaki fark davranışsızdır.
Biri tutmazsa iz eskidir (eski davranış). İlk tam prepare izi şema 2 ile yazar; köprü bir daha gerekmez.
Bu modül izin kendisini hesaplar, istem kurmaz: izin kod listesinde değildir.
"""
from __future__ import annotations

import ast
import functools
import gzip
import hashlib
import json
from pathlib import Path

SEMA = "v2-"
ESKI_DIR = Path(__file__).resolve().parent / "parmak_eski"
# run.py'nin istemi belirlemeyen üst düzey tanımları (sözdizimi izinden çıkarılır)
RUN_DISI = frozenset({"input_fingerprint"})


def sozdizimi(kaynak: str, disi: frozenset[str] = frozenset()) -> str:
    """Kaynağın davranış izi: yorumsuz, biçimsiz, belge dizgesiz sözdizimi ağacı metni; `disi` adlı
    üst düzey fonksiyon/sınıflar çıkarılır."""
    tree = ast.parse(kaynak)
    for node in ast.walk(tree):
        for alan in ("body", "orelse", "finalbody"):
            gov = getattr(node, alan, None)
            if not isinstance(gov, list) or not gov or not isinstance(gov[0], ast.stmt):
                continue
            yeni = [st for st in gov
                    if not (isinstance(st, ast.Expr) and isinstance(st.value, ast.Constant)
                            and isinstance(st.value.value, str))]           # belge dizgesi / çıplak dizge
            if node is tree and disi:
                yeni = [st for st in yeni
                        if not (isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                                and st.name in disi)]
            if not yeni and alan == "body" and not isinstance(node, ast.Module):
                yeni = [ast.Pass()]
            setattr(node, alan, yeni)
    return ast.unparse(tree)


def _kod(p: Path) -> bytes:
    disi = RUN_DISI if p.name == "run.py" and p.parent.name == "decide" else frozenset()
    return sozdizimi(p.read_text(encoding="utf-8"), disi).encode("utf-8")


def _hesap(ws, stage: str, kod) -> str:
    """İki şemanın ortak gövdesi; `kod(p)` kod dosyasının ize giren baytları."""
    from bidr.decide import run as R
    from bidr import notlar as N
    h = hashlib.sha256()

    def add(p: Path, icerik: bytes | None = None) -> None:
        if p.is_file():
            h.update(p.name.encode("utf-8") + b"\0" + (p.read_bytes() if icerik is None else icerik) + b"\0")

    for p in sorted((R.TASKS_DIR / R.STAGES[stage]).rglob("*")):
        add(p)
    for p in R.FINGERPRINT_CODE:
        if p.is_file():
            add(p, kod(p))
    for d in R.FINGERPRINT_DATA:
        for p in sorted(d.rglob("*")):
            add(p)
    for name in ("documents.jsonl", "candidates.jsonl", R.BIRIM_KARARLARI, N.NOTLAR):
        add(ws.root / name)
    h.update(json.dumps(R.P.unit_info(ws.root), ensure_ascii=False, sort_keys=True).encode("utf-8"))
    if stage == "fine":                     # etkinlik dosyası ipucu başka belgelerin kararından kurulur
        from bidr.faaliyet import dosya as ED
        h.update(ED.parmak(ED.yukle(ws.root)).encode("utf-8"))
    if ws.text_dir.exists():
        for p in sorted(ws.text_dir.glob("*.txt")):
            add(p)
    return h.hexdigest()[:16]


def hesapla(ws, stage: str) -> str:
    """Şema 2 iz (`v2-…`)."""
    return SEMA + _hesap(ws, stage, _kod)


@functools.lru_cache(maxsize=None)
def _eski_runlar() -> tuple[bytes, ...]:
    """Dondurulmuş eski run.py baytları (şema 1 izi yazmış sürümler)."""
    return tuple(gzip.decompress(f.read_bytes()) for f in sorted(ESKI_DIR.glob("run-*.py.gz")))


def sema1(ws, stage: str, run_bayt: bytes) -> str:
    """Şema 1 iz; run.py yerine `run_bayt` (öbür kod dosyaları bugünkü baytlarıyla)."""
    return _hesap(ws, stage, lambda p: run_bayt if p.name == "run.py" and p.parent.name == "decide"
                  else p.read_bytes())


def uyumlu(ws, stage: str, kayitli: str | None) -> bool:
    """Kayıtlı iz (`<aşama>-yeniden.json` `parmak`) bugünkü girdi ve kodla geçerli mi."""
    from bidr.decide import run as R
    if not isinstance(kayitli, str) or not kayitli:
        return False
    if kayitli == R.input_fingerprint(ws, stage):
        return True
    if kayitli.startswith(SEMA):
        return False
    simdi = sozdizimi(next(p for p in R.FINGERPRINT_CODE if p.name == "run.py").read_text(encoding="utf-8"),
                      RUN_DISI)
    for eski in _eski_runlar():
        if sozdizimi(eski.decode("utf-8"), RUN_DISI) == simdi and sema1(ws, stage, eski) == kayitli:
            return True
    return False
