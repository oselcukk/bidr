"""Kişisel veri tespiti (belirleyici; model yok).

Türler (öncelik sırasıyla; çakışmada önce gelen kazanır):
  tc_no       11 hane + T.C. kimlik algoritması (ilk hane 0 değil, 10. ve 11. hane denetimi)
  iban        TR + 24 hane (boşluklu yazım dahil)
  eposta      ad@alan.uzantı
  telefon     +90 / 0090 / 0 önekli ya da alan kodu parantezli Türkiye numarası
  ogrenci_no  yapılandırılabilir desenler (`privacy.maskeleme.ogrenci_no_desenleri`)
  ad          yapılandırmadaki ad listesi (`privacy.maskeleme.ad_listesi`; ör. personel listesi)

Bulunan değerler bellekte kalır; raporlara yalnız tür ve sayı yazılır.
Genişletme noktası: `register_detector` (ör. ileride yerel model ile ad tanıma).
"""
from __future__ import annotations

import csv
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

KINDS = ("tc_no", "iban", "eposta", "telefon", "ogrenci_no", "ad")
PLACEHOLDERS = {"tc_no": "[TC_NO]", "iban": "[IBAN]", "eposta": "[EPOSTA]", "telefon": "[TELEFON]",
                "ogrenci_no": "[OGRENCI_NO]", "ad": "[AD]"}

# Varsayılan öğrenci numarası desenleri: yıl önekli 9-10 hane ve "öğrenci no: …" bağlamı
# (grup 1 varsa yalnız grup maskelenir).
DEFAULT_STUDENT_PATTERNS = (
    r"(?<!\d)(?:19|20)\d{7,8}(?!\d)",
    r"(?i)(?:öğrenci|ogrenci|ÖĞRENCİ|OGRENCI)\s*(?:no|numarası|numarasi|numara)\s*[:.]?\s*(\d{5,12})(?!\d)",
)

_RE_TC = re.compile(r"(?<!\d)[1-9]\d{10}(?!\d)")
_RE_IBAN = re.compile(r"(?<![A-Za-z0-9])[Tt][Rr][ \t]?(?:\d[ \t]?){23}\d(?!\d)")
_RE_EMAIL = re.compile(r"(?<![\w.%+\-])[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}(?![\w])")
_SEP = r"[ \t\-./]{0,2}"
_RE_PHONE = re.compile(
    r"(?<![\d+])(?:"
    rf"(?:\+[ \t]?90|0090|0){_SEP}\(?[2-5]\d{{2}}\)?{_SEP}\d{{3}}{_SEP}\d{{2}}{_SEP}\d{{2}}"
    rf"|\((?:0[ \t]?)?[2-5]\d{{2}}\){_SEP}\d{{3}}{_SEP}\d{{2}}{_SEP}\d{{2}}"
    r")(?!\d)")


def tc_valid(s: str) -> bool:
    """T.C. kimlik numarası algoritması."""
    if len(s) != 11 or not s.isdigit() or s[0] == "0":
        return False
    d = [int(c) for c in s]
    if ((sum(d[0:9:2]) * 7) - sum(d[1:8:2])) % 10 != d[9]:
        return False
    return sum(d[:10]) % 10 == d[10]


def iban_valid(s: str) -> bool:
    """IBAN mod-97 denetimi (TR için 26 karakter)."""
    s = re.sub(r"\s+", "", s).upper()
    if not re.fullmatch(r"TR\d{24}", s):
        return False
    r = s[4:] + s[:4]
    num = "".join(str(int(c, 36)) for c in r)
    return int(num) % 97 == 1


@dataclass(frozen=True)
class Finding:
    kind: str
    start: int
    end: int


# Genişletme noktası: ek tespitçiler (ör. yerel model ile ad tanıma). İşlev metni alır,
# (başlangıç, bitiş) çiftleri döndürür. Yer tutucu `[TUR]` biçimindedir.
_EXTRA: dict[str, Callable[[str], Iterable[tuple[int, int]]]] = {}


def register_detector(kind: str, fn: Callable[[str], Iterable[tuple[int, int]]]) -> None:
    """Ek tespitçi kaydı (en düşük öncelik). Aynı adla yeniden kayıt öncekinin yerine geçer."""
    _EXTRA[kind] = fn
    PLACEHOLDERS.setdefault(kind, f"[{kind.upper()}]")


def unregister_detector(kind: str) -> None:
    _EXTRA.pop(kind, None)


_TR_VARIANTS = {
    "i": "iİıI", "ı": "ıIiİ", "İ": "İiIı", "I": "Iıiİ",
    "ş": "şŞsS", "Ş": "ŞşSs", "ğ": "ğĞgG", "Ğ": "ĞğGg", "ü": "üÜuU", "Ü": "ÜüUu",
    "ö": "öÖoO", "Ö": "ÖöOo", "ç": "çÇcC", "Ç": "ÇçCc",
}


def _char_class(c: str) -> str:
    v = _TR_VARIANTS.get(c)
    if v is None:
        v = "".join(dict.fromkeys(c + c.lower() + c.upper()))
    return "[" + "".join(re.escape(x) for x in dict.fromkeys(v)) + "]"


def name_pattern(name: str) -> re.Pattern | None:
    """Ad için büyük/küçük harf ve Türkçe karakter (ş/s, ı/i …) duyarsız desen."""
    toks = [t for t in re.split(r"\s+", name.strip()) if t]
    if not toks or sum(len(t) for t in toks) < 3:
        return None
    body = r"\s+".join("".join(_char_class(c) for c in t) for t in toks)
    return re.compile(rf"(?<![\w]){body}(?![\w])")


def load_name_list(spec, base: Path | None = None) -> list[str]:
    """`ad_listesi`: liste ya da dosya yolu (.txt satır başına bir ad; .csv ilk sütun;
    `#` ile başlayan satırlar yok sayılır). Göreli yol çalışma alanına göredir."""
    if not spec:
        return []
    if isinstance(spec, (list, tuple)):
        return [str(x).strip() for x in spec if str(x).strip()]
    p = Path(str(spec)).expanduser()
    if not p.is_absolute() and base is not None:
        p = base / p
    if not p.is_file():
        raise FileNotFoundError(f"ad listesi yok: {p}")
    out: list[str] = []
    if p.suffix.lower() == ".csv":
        with open(p, encoding="utf-8-sig", newline="") as f:
            for row in csv.reader(f):
                if row and row[0].strip() and not row[0].lstrip().startswith("#"):
                    out.append(row[0].strip())
    else:
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            if line.strip() and not line.lstrip().startswith("#"):
                out.append(line.strip())
    return out


@dataclass
class MaskRules:
    kinds: tuple[str, ...] = KINDS
    student_patterns: tuple[str, ...] = DEFAULT_STUDENT_PATTERNS
    names: tuple[str, ...] = ()
    local_model: str | None = None          # genişletme noktası; bu sürümde uygulanmaz
    _compiled: list = field(default_factory=list, repr=False, compare=False)

    def __post_init__(self):
        bad = [k for k in self.kinds if k not in KINDS]
        if bad:
            raise ValueError(f"bilinmeyen maskeleme türü: {', '.join(bad)} (geçerli: {', '.join(KINDS)})")
        comp = []
        for p in self.student_patterns:
            try:
                comp.append(re.compile(p))
            except re.error as e:
                raise ValueError(f"geçersiz öğrenci numarası deseni {p!r}: {e}") from None
        names = sorted({n for n in self.names if n}, key=len, reverse=True)
        self._compiled = [comp, [r for r in (name_pattern(n) for n in names) if r is not None]]

    @property
    def warnings(self) -> list[str]:
        w = []
        if self.local_model:
            w.append("privacy.maskeleme.yerel_model bu sürümde uygulanmıyor; yalnız kural tabanlı tespit")
        return w

    @classmethod
    def from_config(cls, data: dict | None, base: Path | None = None) -> "MaskRules":
        """`config.yaml` kökü (ya da yalnız `privacy:` bölümü) → kurallar."""
        data = data or {}
        priv = data.get("privacy", data) if isinstance(data, dict) else {}
        priv = priv if isinstance(priv, dict) else {}
        m = priv.get("maskeleme") or {}
        if not isinstance(m, dict):
            raise ValueError("privacy.maskeleme bir sözlük olmalı")
        kw = {}
        if m.get("turler"):
            kw["kinds"] = tuple(str(k) for k in m["turler"])
        pats = m.get("ogrenci_no_desenleri")
        if pats is not None:
            kw["student_patterns"] = tuple([pats] if isinstance(pats, str) else (str(p) for p in pats))
        kw["names"] = tuple(load_name_list(m.get("ad_listesi"), base))
        kw["local_model"] = m.get("yerel_model") or None
        return cls(**kw)

    @classmethod
    def load(cls, ws_root: Path) -> "MaskRules":
        return cls.from_config(read_ws_config(ws_root), Path(ws_root))


def read_ws_config(ws_root: Path) -> dict:
    """`<ws>/config.yaml` (yoksa boş sözlük)."""
    p = Path(ws_root) / "config.yaml"
    if not p.exists():
        return {}
    import yaml

    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _raw(text: str, rules: MaskRules) -> list[tuple[int, int, int, str]]:
    """(öncelik, başlangıç, bitiş, tür) adayları."""
    out = []
    pr = {k: i for i, k in enumerate(KINDS)}
    ks = set(rules.kinds)
    if "tc_no" in ks:
        out += [(pr["tc_no"], m.start(), m.end(), "tc_no") for m in _RE_TC.finditer(text) if tc_valid(m.group())]
    if "iban" in ks:
        out += [(pr["iban"], m.start(), m.end(), "iban") for m in _RE_IBAN.finditer(text)]
    if "eposta" in ks:
        out += [(pr["eposta"], m.start(), m.end(), "eposta") for m in _RE_EMAIL.finditer(text)]
    if "telefon" in ks:
        out += [(pr["telefon"], m.start(), m.end(), "telefon") for m in _RE_PHONE.finditer(text)]
    student, names = rules._compiled
    if "ogrenci_no" in ks:
        for rx in student:
            for m in rx.finditer(text):
                s, e = (m.start(1), m.end(1)) if rx.groups and m.group(1) else (m.start(), m.end())
                if e > s:
                    out.append((pr["ogrenci_no"], s, e, "ogrenci_no"))
    if "ad" in ks:
        for rx in names:
            out += [(pr["ad"], m.start(), m.end(), "ad") for m in rx.finditer(text)]
    for i, (kind, fn) in enumerate(_EXTRA.items()):
        out += [(len(KINDS) + i, int(s), int(e), kind) for s, e in fn(text) if int(e) > int(s)]
    return out


def detect(text: str, rules: MaskRules | None = None) -> list[Finding]:
    """Çakışmasız bulgular, metin sırasında. Çakışmada öncelik, sonra uzunluk kazanır."""
    if not text:
        return []
    rules = rules or MaskRules()
    cands = sorted(_raw(text, rules), key=lambda c: (c[0], -(c[2] - c[1]), c[1]))
    taken: list[tuple[int, int, str]] = []
    for _, s, e, k in cands:
        if all(e <= ts or s >= te for ts, te, _ in taken):
            taken.append((s, e, k))
    return [Finding(k, s, e) for s, e, k in sorted(taken)]


def mask_text(text: str, rules: MaskRules | None = None,
              repl: Callable[[Finding, str], str] | None = None) -> tuple[str, Counter]:
    """Bulguları yer tutucuyla (`[TC_NO]` …) değiştirir. → (maskeli metin, tür sayıları)."""
    fs = detect(text, rules)
    if not fs:
        return text, Counter()
    repl = repl or (lambda f, _s: PLACEHOLDERS.get(f.kind, f"[{f.kind.upper()}]"))
    parts, pos = [], 0
    for f in fs:
        parts.append(text[pos:f.start])
        parts.append(repl(f, text[f.start:f.end]))
        pos = f.end
    parts.append(text[pos:])
    return "".join(parts), Counter(f.kind for f in fs)


def count(text: str, rules: MaskRules | None = None) -> Counter:
    return Counter(f.kind for f in detect(text, rules))
