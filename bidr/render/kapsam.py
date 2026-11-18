"""Sorumlu birim kapsamı: her alt ölçüt için birimin doldurma sorumluluğu (salt okunur).

Durumlar:
  bolum          birim doldurur (kanıt yoksa "kanıt bulunamadı" yazılır)
  ortak          birim başka birimlerle birlikte doldurur (render'da `bolum` gibi)
  baska_birim    birimin doldurma sorumluluğunda değil (hücreye kısa kapsam ifadesi; kanıt
                 yokluğu yazılmaz, OD işaretlenmez)
  karar_gerekli  kim dolduracak belli değil (rapor TASLAK; gaps.md'de soru)

Öncelik (yüksekten düşüğe):
  1. config.yaml `rapor.kapsam: {ölçüt: durum}` — çalışma alanında kullanıcının kararı;
  2. profil YAML'ındaki `kapsam: {ölçüt: durum}` — profil düzeyinde kesin karar;
  3. profilin mevcut kuralı (geri uyumlu): `kararlar`/`dahil` → bolum, `belirsiz` → karar_gerekli,
     doldurucu birimler arasında profil yok (haric) → baska_birim.
Profil bilinmiyorsa her ölçüt `bolum` sayılır (eski davranış).
"""
from __future__ import annotations

from pathlib import Path

import yaml

BOLUM, ORTAK, BASKA, KARAR = "bolum", "ortak", "baska_birim", "karar_gerekli"
DURUMLAR = (BOLUM, ORTAK, BASKA, KARAR)
DOLDURUR = (BOLUM, ORTAK)          # kanıt yokluğu yalnız bunlarda yazılır
_FROM_VERDICT = {"dahil": BOLUM, "haric": BASKA, "belirsiz": KARAR}


def _check_map(m, where: str) -> tuple[dict[str, str], list[str]]:
    if not m:
        return {}, []
    if not isinstance(m, dict):
        return {}, [f"{where}: kapsam bir sözlük olmalı ({{ölçüt: {'|'.join(DURUMLAR)}}})"]
    out, uy = {}, []
    for k, v in m.items():
        k, v = str(k).strip().rstrip("."), str(v).strip()
        if v not in DURUMLAR:
            uy.append(f"{where}: {k} kapsamı '{v}' geçersiz ({' | '.join(DURUMLAR)}); yok sayıldı")
            continue
        out[k] = v
    return out, uy


def profile_scope(profile: str | Path | None, cs=None) -> tuple[dict[str, str], list[str]]:
    """Profil verisinden {ölçüt: durum} (bütün alt ölçütler) ve uyarılar."""
    from bidr.criteria.loader import load_criteria
    from bidr.criteria.profiles import load_profile, profiles_dir
    cs = cs or load_criteria()
    if not profile:
        return {s.id: BOLUM for s in cs.sub_criteria}, []
    p = Path(str(profile))
    if not p.suffix:
        p = profiles_dir() / f"{profile}.yaml"
    prof = load_profile(p)
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    explicit, uy = _check_map(raw.get("kapsam"), f"profil {prof.name}")
    out = {}
    for s in cs.sub_criteria:
        out[s.id] = explicit.get(s.id) or _FROM_VERDICT[prof.decide(s.id, s.units).verdict]
    unknown = sorted(set(explicit) - set(out))
    if unknown:
        uy.append(f"profil {prof.name}: bilinmeyen ölçüt kapsamı: {', '.join(unknown)}")
    return out, uy


def workspace_scope(ws_root: Path, cs=None) -> tuple[dict[str, str], list[str]]:
    """Çalışma alanının kapsam görünümü: profil (config.yaml `bidr.profil`) + `rapor.kapsam`."""
    from bidr.init.config import load_section
    from bidr.write.sources import rapor_section
    sec = load_section(Path(ws_root)) or {}
    out, uy = profile_scope(sec.get("profil"), cs)
    over, u2 = _check_map(rapor_section(Path(ws_root)).get("kapsam"), "config.yaml rapor.kapsam")
    uy += u2
    for k, v in over.items():
        if k not in out:
            uy.append(f"config.yaml rapor.kapsam: bilinmeyen ölçüt {k}")
            continue
        out[k] = v
    return out, uy


def fills(kapsam: dict[str, str] | None, cid: str) -> bool:
    """Birim bu ölçütü dolduruyor mu (bolum | ortak)."""
    return (kapsam or {}).get(cid, BOLUM) in DOLDURUR
