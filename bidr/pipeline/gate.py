"""Aşama kapıları: önkoşulu bitmemiş aşamanın komutu açık bir hatayla durur.

Kapılar yalnız yönetilen çalışma alanında (config.yaml'da `bidr:` bölümü, `bidr init`
yazar) işler; bölümü olmayan eski/geliştirme çalışma alanlarında komutlar eskisi gibi
çalışır. Denetim salt okunurdur.
"""
from __future__ import annotations

import sys
from pathlib import Path

GATE_EXIT = 3


class GateError(RuntimeError):
    pass


def require_stage(ws_root: Path, stage_id: str, *, kaynak: Path | str | None = None) -> None:
    """`stage_id` aşamasının önkoşulları bitmemişse GateError. Yönetilmeyen WS'de hiçbir şey yapmaz."""
    from bidr.init.config import load_section

    from .state import DONE, evaluate, stage

    ws_root = Path(ws_root).expanduser().resolve()
    sec = load_section(ws_root)
    if sec is None:
        return
    spec = stage(stage_id)
    if kaynak is not None and Path(kaynak).expanduser().resolve() != Path(sec["kaynak"]).resolve():
        raise GateError(f"kaynak klasör config.yaml'dakiyle aynı değil: {Path(kaynak).expanduser().resolve()} ≠ "
                        f"{sec['kaynak']}. Kaynağı değiştirmek için `bidr init` ile yeniden kurun.")
    rep = evaluate(ws_root, until=stage_id)
    bad = [rep.get(o) for o in spec.get("onkosul") or [] if rep.get(o).durum not in DONE]
    if bad:
        why = "; ".join(f"{b.id} ({b.ad}): {b.durum} — {b.neden}" for b in bad)
        raise GateError(f"kapı: '{stage_id}' çalıştırılamaz, önce bitmeli → {why}. "
                        f"Sıradaki adım: bidr next -w {ws_root}")


def check_gate(ws_root, stage_id: str, **kw) -> int | None:
    """CLI yardımcısı: kapı kapalıysa mesajı stderr'e yazar ve çıkış kodunu döndürür."""
    try:
        require_stage(Path(ws_root), stage_id, **kw)
    except GateError as e:
        print(f"HATA {e}", file=sys.stderr)
        return GATE_EXIT
    return None
