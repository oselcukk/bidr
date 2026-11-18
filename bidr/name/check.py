"""Kanıt adı denetimi (model yok). Model ya da insan önerisi kanıt dosyasının adı olur:
kişi adı/unvan/e-posta taşımaz, kısa, dosya sisteminde güvenli.

Kişi adını genel olarak tanımak mümkün değil; burada unvan, hitap ve e-posta yakalanır
(istem kişi adını ayrıca yasaklar). Yanlış pozitif yalnız öneriyi reddeder: ad kurala düşer.
"""
from __future__ import annotations

import re
import unicodedata

from bidr.file.naming import MAX_AD, has_person

MIN_SOZCUK, MAX_SOZCUK = 2, 10        # istem 3-7 ister; kod yalnız açık aşımı reddeder
_HITAP = re.compile(r"(?<![A-Za-zÇĞİÖŞÜçğıöşü])(?:bey|beyefendi|hanım|hanımefendi|hoca|hocası|hocam)"
                    r"(?![A-Za-zçğıöşü])", re.IGNORECASE)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')


def clean(s: str) -> str:
    s = unicodedata.normalize("NFC", str(s or ""))
    s = re.sub(r"\s+", " ", s).strip().strip("\"'“”‘’").strip()
    return s.rstrip(" .;,")


def check_name(s) -> tuple[str | None, list[str]]:
    """(temiz ad, hatalar). Hata varsa ad None."""
    if not isinstance(s, str):
        return None, ["bos"]
    t = clean(s)
    errs: list[str] = []
    if not t:
        return None, ["bos"]
    if _EMAIL.search(t):
        errs.append("eposta")
    if has_person(t) or _HITAP.search(t):
        errs.append("kisi_unvan")
    if _BAD.search(t):
        errs.append("yasakli_karakter")
    n = len(re.findall(r"\w+", t))
    if n < MIN_SOZCUK or n > MAX_SOZCUK or len(t) > MAX_AD:
        errs.append("uzunluk")
    letters = sum(c.isalpha() for c in t)
    if letters < 3 or letters / len(t) < 0.5:
        errs.append("bozuk")
    return (None, errs) if errs else (t, [])
