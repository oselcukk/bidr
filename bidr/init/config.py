"""Çalışma alanı yapılandırması: `config.yaml`'ın `bidr:` bölümü.

`config.yaml` model katmanıyla paylaşılır (`models:`, `privacy:`; bkz. docs/MODEL_LAYER.md).
Bu modül yalnız `bidr:` bölümünü okur/yazar; diğer bölümlere (ve yorumlarına) dokunmaz.
`bidr:` bölümü olan çalışma alanı "yönetilen" sayılır: aşama kapıları yalnız orada işler.
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

CONFIG = "config.yaml"
SECTION = "bidr"
SCHEMA_VERSION = 1

# cevap anahtarı → (tür, zorunlu, açıklama)
FIELDS: dict[str, tuple[type | tuple, bool, str]] = {
    "calisma_alani": (str, False, "çalışma alanı klasörü (repo ve kaynak dışında); -w verilirse o geçer"),
    "kaynak": (str, True, "birimin belge klasörü (salt okunur; hiçbir dosyası değiştirilmez)"),
    "birim": (str, True, "birimin adı (ör. Fizik Bölümü)"),
    "profil": (str, True, "birim profili (bidr/data/profiles/<ad>.yaml; ör. akademik_bolum)"),
    "donem": (int, True, "rapor dönemi / değerlendirme yılı (ör. 2025)"),
    "kurum": ((str, type(None)), False, "kurum profili (bidr/data/institutions/<ad>.yaml); boş = hepsi"),
    "gecmis_etiket": (bool, False, "kaynakta geçmiş yılın BİDR raporu ve etiketli kanıt klasörleri var mı"),
    "etiket_birim": ((str, type(None)), False, "labels build --unit değeri (vars. birim)"),
    "egitim": (list, False, "candidates --train için etiketli başka çalışma alanları (isteğe bağlı)"),
    "ajan": ((str, type(None)), False, "model işini yapan ajanın adı, kayıtlara geçer (ör. claude-code:opus)"),
}


class ConfigError(ValueError):
    pass


def data_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "data"


def repo_root() -> Path | None:
    """bidr kaynak reposunun kökü (düzenlenebilir kurulumda); yoksa None."""
    root = Path(__file__).resolve().parents[2]
    pp = root / "pyproject.toml"
    if pp.exists() and 'name = "bidr"' in pp.read_text(encoding="utf-8", errors="replace"):
        return root
    return None


def available_profiles() -> list[str]:
    from bidr.criteria.profiles import EXCLUDED_TYPES_FILE, profiles_dir
    # Birim profili = "dahil" anahtarı olan dosya; politika dosyaları (kanıt ilkeleri,
    # kurum geneli, dönem kuralı, hariç türler) aynı klasörde ama profil değildir.
    import yaml as _yaml
    out = []
    for p in profiles_dir().glob("*.yaml"):
        if p.name == EXCLUDED_TYPES_FILE:
            continue
        try:
            data = _yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        if isinstance(data, dict) and "dahil" in data:
            out.append(p.stem)
    return sorted(out)


def available_institutions() -> list[str]:
    d = Path(os.environ.get("BIDR_INSTITUTIONS_DIR", data_dir() / "institutions")).expanduser()
    return sorted(p.stem for p in d.glob("*.yaml"))


def _inside(a: Path, b: Path) -> bool:
    """a, b'nin kendisi ya da altında mı."""
    return a == b or b in a.parents


def validate(answers: dict, ws: Path | None = None) -> tuple[dict, list[str]]:
    """Cevapları denetler; (bidr bölümü, hatalar). Hata yoksa bölüm yazılmaya hazırdır."""
    errs: list[str] = []
    if not isinstance(answers, dict):
        return {}, ["cevap dosyası bir YAML sözlüğü olmalı"]
    unknown = sorted(set(answers) - set(FIELDS))
    if unknown:
        errs.append(f"bilinmeyen alan(lar): {', '.join(unknown)} (geçerli: {', '.join(FIELDS)})")
    for k, (typ, req, _) in FIELDS.items():
        v = answers.get(k)
        if v is None or v == "":
            if req:
                errs.append(f"`{k}` gerekli")
            continue
        if typ is int and isinstance(v, str) and v.strip().isdigit():
            v = int(v)
            answers = {**answers, k: v}
        if not isinstance(v, typ) or (typ is int and isinstance(v, bool)):
            errs.append(f"`{k}` türü yanlış: {type(v).__name__}")
    if errs:
        return {}, errs

    if ws is None:
        if not answers.get("calisma_alani"):
            return {}, ["çalışma alanı yolu yok: -w verin ya da `calisma_alani` yazın"]
        ws = Path(answers["calisma_alani"])
    ws = Path(ws).expanduser().resolve()
    src = Path(answers["kaynak"]).expanduser().resolve()
    if not src.is_dir():
        errs.append(f"kaynak klasör yok: {src}")
    elif not os.access(src, os.R_OK):
        errs.append(f"kaynak klasör okunamıyor: {src}")
    if _inside(ws, src):
        errs.append("çalışma alanı kaynak klasörün içinde olamaz (kaynak salt okunur)")
    if _inside(src, ws):
        errs.append("kaynak klasör çalışma alanının içinde olamaz")
    repo = repo_root()
    if repo is not None and (_inside(ws, repo) or _inside(src, repo)):
        errs.append(f"çalışma alanı ve kaynak bidr reposunun ({repo}) dışında olmalı: gerçek veri repoya girmez")
    if answers["profil"] not in available_profiles():
        errs.append(f"bilinmeyen profil: {answers['profil']} (geçerli: {', '.join(available_profiles())})")
    kurum = answers.get("kurum") or None
    if kurum and kurum not in available_institutions():
        errs.append(f"bilinmeyen kurum: {kurum} (geçerli: {', '.join(available_institutions())}; boş = hepsi)")
    donem = int(answers["donem"])
    if not 2000 <= donem <= 2100:
        errs.append(f"dönem bir yıl olmalı: {donem}")
    egitim = []
    for e in answers.get("egitim") or []:
        p = Path(str(e)).expanduser().resolve()
        if not (p / "labels.jsonl").exists():
            errs.append(f"eğitim çalışma alanında labels.jsonl yok: {p}")
        egitim.append(str(p))
    if not str(answers["birim"]).strip():
        errs.append("`birim` boş olamaz")
    if errs:
        return {}, errs
    sec = {
        "surum": SCHEMA_VERSION,
        "kaynak": str(src),
        "birim": str(answers["birim"]).strip(),
        "profil": answers["profil"],
        "donem": donem,
        "kurum": kurum,
        "gecmis_etiket": bool(answers.get("gecmis_etiket", False)),
        "etiket_birim": answers.get("etiket_birim") or str(answers["birim"]).strip(),
        "egitim": egitim,
        "ajan": answers.get("ajan") or None,
    }
    return sec, []


def read_raw(ws: Path) -> dict:
    p = Path(ws) / CONFIG
    if not p.exists():
        return {}
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def load_section(ws: Path) -> dict | None:
    """`bidr:` bölümü; yoksa None (yönetilmeyen çalışma alanı)."""
    try:
        sec = read_raw(ws).get(SECTION)
    except yaml.YAMLError:
        return None
    return sec if isinstance(sec, dict) else None


def check_section(sec: dict, ws: Path) -> list[str]:
    """Yazılmış bölümün hâlâ geçerli olup olmadığı (kaynak taşınmış olabilir)."""
    ans = {k: sec.get(k) for k in FIELDS if k in sec}
    _, errs = validate(ans, ws)
    return errs


def render_section(sec: dict) -> str:
    body = yaml.safe_dump({SECTION: sec}, allow_unicode=True, sort_keys=False, default_flow_style=False)
    head = ("# bidr çalışma alanı (bidr init yazar; elle değiştirmeyin, `bidr init` ile yeniden yazın).\n"
            "# Kaynak klasör salt okunurdur.\n")
    return head + body


def write_section(ws: Path, sec: dict) -> Path:
    """`bidr:` bölümünü yazar; config.yaml'daki diğer bölümler ve yorumlar korunur."""
    p = Path(ws) / CONFIG
    block = render_section(sec)
    if not p.exists():
        p.write_text(block, encoding="utf-8")
        return p
    lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
    out, i, replaced = [], 0, False
    while i < len(lines):
        ln = lines[i]
        if ln.startswith(f"{SECTION}:"):
            # bölümün başındaki bidr yorumlarını da at
            while out and out[-1].startswith(("# bidr çalışma alanı", "# Kaynak klasör salt")):
                out.pop()
            out.append(block)
            replaced = True
            i += 1
            while i < len(lines) and (lines[i].startswith((" ", "\t")) or not lines[i].strip()):
                i += 1
            continue
        out.append(ln)
        i += 1
    if not replaced:
        if out and not out[-1].endswith("\n"):
            out.append("\n")
        out.append(("\n" if out else "") + block)
    text = "".join(out)
    yaml.safe_load(text)  # bozuk yazmayalım
    p.write_text(text, encoding="utf-8")
    return p
