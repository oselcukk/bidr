"""Çalışma alanı yapılandırması: `config.yaml`'ın `bidr:` bölümü.

`config.yaml` model katmanıyla paylaşılır (`models:`, `privacy:`; bkz. docs/MODEL_LAYER.md).
Bu modül yalnız `bidr:` bölümünü okur/yazar; diğer bölümlere (ve yorumlarına) dokunmaz.
`bidr:` bölümü olan çalışma alanı "yönetilen" sayılır: aşama kapıları yalnız orada işler.
"""
from __future__ import annotations

import os
import re
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


# `rapor:` bölümüne yazılan cevaplar (bidr bölümüne girmez): anahtar → açıklama
RAPOR_FIELDS = {
    "hazirlayanlar": "kapaktaki 'Raporu Hazırlayanlar': [{unvan, ad_soyad, eposta, gorev}, …]",
}
HAZIRLAYAN_KEYS = ("unvan", "ad_soyad", "eposta", "gorev")
RAPOR_SECTION = "rapor"


class ConfigError(ValueError):
    pass


def check_preparers(v) -> tuple[list[dict] | None, list[str]]:
    """`rapor.hazirlayanlar` listesi → (temiz liste | None, hatalar). None/boş: liste yok.
    Her kişi: `ad_soyad` gerekli; `unvan`, `eposta`, `gorev` isteğe bağlı (kapakta boş kalır)."""
    import re
    if v is None or v == "" or v == []:
        return None, []
    if not isinstance(v, list):
        return None, ["hazirlayanlar bir liste olmalı: [{unvan, ad_soyad, eposta, gorev}, …]"]
    out, errs = [], []
    for i, x in enumerate(v, 1):
        if not isinstance(x, dict):
            errs.append(f"hazirlayanlar #{i}: sözlük olmalı ({', '.join(HAZIRLAYAN_KEYS)})")
            continue
        bad = sorted(set(map(str, x)) - set(HAZIRLAYAN_KEYS))
        if bad:
            errs.append(f"hazirlayanlar #{i}: bilinmeyen alan(lar) {', '.join(bad)} (geçerli: {', '.join(HAZIRLAYAN_KEYS)})")
        rec = {k: " ".join(str(x.get(k) or "").split()) for k in HAZIRLAYAN_KEYS}
        if not rec["ad_soyad"]:
            errs.append(f"hazirlayanlar #{i}: `ad_soyad` gerekli")
        if rec["eposta"] and not re.fullmatch(r"[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+", rec["eposta"]):
            errs.append(f"hazirlayanlar #{i}: e-posta biçimi geçersiz: {rec['eposta']}")
        out.append(rec)
    return (None, errs) if errs else (out, [])


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
    unknown = sorted(set(answers) - set(FIELDS) - set(RAPOR_FIELDS))
    if unknown:
        errs.append(f"bilinmeyen alan(lar): {', '.join(unknown)} (geçerli: {', '.join([*FIELDS, *RAPOR_FIELDS])})")
    if "hazirlayanlar" in answers:
        errs += check_preparers(answers["hazirlayanlar"])[1]
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


def load_rapor(ws: Path) -> dict:
    try:
        sec = read_raw(ws).get(RAPOR_SECTION)
    except yaml.YAMLError:
        return {}
    return sec if isinstance(sec, dict) else {}


def write_rapor_key(ws: Path, key: str, value) -> Path:
    """config.yaml `rapor:` bölümünde yalnız `key`'i yazar; bölümün öteki anahtarları ve dosyanın
    öteki bölümleri (yorumlarıyla) korunur. Blok biçimli bölümde yalnız o anahtarın satırları
    değişir; akış biçimli (`rapor: {…}`) bölüm anahtarları korunarak blok biçimine çevrilir."""
    p = Path(ws) / CONFIG
    raw = read_raw(ws) if p.exists() else {}
    cur = raw.get(RAPOR_SECTION) if isinstance(raw.get(RAPOR_SECTION), dict) else None
    sub = yaml.safe_dump({key: value}, allow_unicode=True, sort_keys=False, default_flow_style=False)
    sub_lines = ["  " + ln + "\n" for ln in sub.rstrip("\n").split("\n")]
    lines = p.read_text(encoding="utf-8").splitlines(keepends=True) if p.exists() else []
    head = next((i for i, ln in enumerate(lines) if ln.startswith(f"{RAPOR_SECTION}:")), None)
    if head is None:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines += (["\n"] if lines else []) + [f"{RAPOR_SECTION}:\n"] + sub_lines
    elif lines[head].split("#")[0].strip() != f"{RAPOR_SECTION}:":
        # akış biçimi ya da tek satır: bölümü anahtarları koruyarak yeniden yaz
        end = head + 1
        while end < len(lines) and (lines[end].startswith((" ", "\t")) or not lines[end].strip()):
            end += 1
        merged = dict(cur or {})
        merged[key] = value
        body = yaml.safe_dump({RAPOR_SECTION: merged}, allow_unicode=True, sort_keys=False, default_flow_style=False)
        lines[head:end] = [body]
    else:
        end = head + 1
        while end < len(lines) and (lines[end].startswith((" ", "\t")) or not lines[end].strip()):
            end += 1
        while end > head + 1 and not lines[end - 1].strip():
            end -= 1
        k0 = next((i for i in range(head + 1, end) if re.match(rf"^\s+{re.escape(key)}\s*:", lines[i])), None)
        if k0 is None:
            lines[end:end] = sub_lines
        else:
            ind = len(lines[k0]) - len(lines[k0].lstrip())

            def inside(ln: str) -> bool:
                d = len(ln) - len(ln.lstrip())
                return not ln.strip() or d > ind or (d == ind and ln.lstrip().startswith("- "))
            k1 = k0 + 1
            while k1 < end and inside(lines[k1]):
                k1 += 1
            lines[k0:k1] = [" " * ind + ln[2:] for ln in sub_lines]
    text = "".join(lines)
    parsed = yaml.safe_load(text) or {}
    got = (parsed.get(RAPOR_SECTION) or {}) if isinstance(parsed, dict) else {}
    want = dict(cur or {})
    want[key] = value
    if got != want or {k: v for k, v in parsed.items() if k != RAPOR_SECTION} != \
            {k: v for k, v in raw.items() if k != RAPOR_SECTION}:
        raise ConfigError("config.yaml `rapor:` bölümü güvenle güncellenemedi; elle düzeltin")
    p.write_text(text, encoding="utf-8")
    return p
