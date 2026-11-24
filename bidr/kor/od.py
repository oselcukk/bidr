"""Kör denetimin OD kararı: bölümün kabul ettiği OD değişikliği `audit-olcutler.json` okunurken
ölçütün `od`'sine yansır (yazım, doğrulama, yönler ve render aynı değeri görür).

Kayıt: `kor-denetim-kararlar.jsonl` (audit dosyasıyla aynı klasörde; `bidr denetim karar`). Ölçüt
başına SON OD kararı geçerlidir. Uygulanma koşulları:
  - karar `kabul`;
  - kararın verildiği andaki kod önerisi (`od_kod`) bugünkü audit `od`'siyle aynı (kanıt ya da
    inceleme kararları sonradan değiştiyse karar eskir, uygulanmaz; `bidr denetim ozet` gösterir);
  - komisyon inceleme tablosunda bu ölçüte OD onaylamamış (`od_onayli` boş): komisyonun onayı
    önceliklidir, değişiklik inceleme tablosunda yapılır.
Kod önerisi `od_kod_onerisi`'nde kalır; uygulanan karar `od_denetim` alanında görünür.
Bu modül yaprak modüldür (yalnız json/pathlib): bidr/write/sources.py ve bidr/render/run.py içe aktarır.
"""
from __future__ import annotations

import json
from pathlib import Path

KARARLAR = "kor-denetim-kararlar.jsonl"


def load_decisions(root: Path) -> list[dict]:
    p = Path(root) / KARARLAR
    if not p.exists():
        return []
    out = []
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if isinstance(r, dict) and r.get("bulgu_id"):
                out.append(r)
    except OSError:
        return []
    return out


def od_decisions(root: Path) -> dict[str, dict]:
    """{ölçüt: son OD kararı} (kabul ya da ret)."""
    out: dict[str, dict] = {}
    for r in load_decisions(root):
        if r.get("sinif") == "od" and r.get("olcut"):
            out[r["olcut"]] = r
    return out


def applies(row: dict | None, dec: dict | None) -> bool:
    if not row or not dec or dec.get("karar") != "kabul":
        return False
    if row.get("od_onayli") in (1, 2, 3, 4, 5):
        return False
    try:
        return int(dec.get("od_kod")) == int(row.get("od") or 1) and int(dec.get("od")) in (1, 2, 3, 4, 5)
    except (TypeError, ValueError):
        return False


def apply_overrides(rows: dict[str, dict], root: Path) -> dict[str, dict]:
    """`rows` ({ölçüt: audit satırı}) içinde geçerli OD kararlarını uygular (yerinde değil; kopya döner)."""
    decs = od_decisions(root)
    if not decs:
        return rows
    out = dict(rows)
    for c, dec in decs.items():
        row = rows.get(c)
        if applies(row, dec):
            out[c] = {**row, "od": int(dec["od"]),
                      "od_denetim": {"od": int(dec["od"]), "od_kod": int(dec["od_kod"]),
                                     "bulgu_id": dec["bulgu_id"], "zaman": dec.get("zaman")}}
    return out


def file_sha(root: Path) -> str | None:
    """Karar dosyasının özeti (render girdisine yalnız dosya varsa girer)."""
    import hashlib
    p = Path(root) / KARARLAR
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p.exists() else None
