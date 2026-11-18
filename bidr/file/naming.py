"""Kanıt adı ve dosya adı (model yok).

Kanıt adı belgenin çalışma adının kaynağından üretilir: identify `calisma_adi`'yı
`baslik`'tan (yoksa tür etiketinden) ASCII slug olarak kurar; burada aynı kaynak Türkçe
karakterleriyle kullanılır. Başlık işe yaramıyorsa (boş, tek sözcük, bozuk karakter) tür
etiketi geçer. Ad kişi adı taşımaz: unvan/e-posta görülürse ad tür etiketine düşer ve uyarı
verilir. Dosya adı tüm yaygın dosya sistemlerinde güvenli (Windows yasaklı karakterleri yok,
NFC, uzunluk sınırlı).
"""
from __future__ import annotations

import re
import unicodedata

MAX_AD = 80

_PREFIX = {"resmi_yazi": "Yazı", "e_posta": "E-posta"}
_FORBIDDEN = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')
# Kişi adı işaretleri: akademik/idari unvanlar, hitap, e-posta. Ad üretmek için yeterince
# temkinli; yanlış pozitif yalnız adı tür etiketine düşürür.
_PERSON = re.compile(
    r"(?<![A-Za-zÇĞİÖŞÜçğıöşü])(?:prof|doç|doc|dr|öğr|ogr|arş|ars|gör|gor|sayın|sayin|"
    r"sn|uzm|okt)\.(?=\s|[A-ZÇĞİÖŞÜ]|$)|"
    r"(?<![A-Za-zÇĞİÖŞÜçğıöşü])(?:sayın|sayin)(?![A-Za-zçğıöşü])|"   # "öğretim üyesi" tek başına rol adıdır, kişi değil
    r"[\w.+-]+@[\w-]+\.[\w.]+",
    re.IGNORECASE)
_TR_LOWER = str.maketrans("Iİ", "ıi")
_TR_UPPER = str.maketrans("ıi", "Iİ")


def has_person(s: str | None) -> bool:
    return bool(s and _PERSON.search(s))


def _tr_title(s: str) -> str:
    """Tamamı büyük harfli başlığı Türkçe kurala uygun baş harf büyük yaz."""
    letters = [c for c in s if c.isalpha()]
    if not letters or sum(c.isupper() for c in letters) / len(letters) < 0.8:
        return s
    out = []
    for w in s.split(" "):
        low = w.translate(_TR_LOWER).lower()
        out.append(low[:1].translate(_TR_UPPER).upper() + low[1:] if low else low)
    return " ".join(out)


def _usable(t: str | None) -> bool:
    if not t:
        return False
    t = t.strip()
    letters = sum(c.isalpha() for c in t)
    if letters < 3 or letters / max(len(t), 1) < 0.6:
        return False
    if any(unicodedata.category(c) in ("Cc", "Co", "Cn") for c in t):
        return False
    if re.search(r"[^\w\s.,;:()'’&/+\-–\[\]%]", t):      # ¢, ! vb.: bozuk metin katmanı
        return False
    return len(re.findall(r"\w+", t)) >= 2


def safe_name(s: str, max_len: int = MAX_AD) -> str:
    s = unicodedata.normalize("NFC", s)
    s = _FORBIDDEN.sub(" ", s).replace("[", "(").replace("]", ")")
    s = re.sub(r"\s+", " ", s).strip(" .-_")
    if len(s) > max_len:
        cut = s[:max_len]
        s = (cut.rsplit(" ", 1)[0] if " " in cut[max_len // 2:] else cut).rstrip(" .,-_")
    return s or "Belge"


def evidence_name(doc: dict | None, type_label: str | None) -> tuple[str, list[str]]:
    """(kanıt adı, uyarılar). `doc`: documents.jsonl kaydı."""
    doc = doc or {}
    uy: list[str] = []
    label = type_label or "Belge"
    base = doc.get("baslik")
    for field_ in ("calisma_adi", "baslik"):
        if has_person(doc.get(field_)):
            uy.append(f"{doc.get('doc_id')}: {field_} kişi adı içeriyor olabilir; kanıt adı tür etiketinden")
            base = None
            break
    base = _tr_title(base.strip()) if _usable(base) else label
    base = re.sub(r"\s*\(\s*$", "", base)                   # yarım kalmış parantez
    if base.count("(") > base.count(")"):
        base += ")"
    pre = _PREFIX.get(doc.get("doc_type") or "")
    if pre and not base.lower().startswith(pre.lower()):
        base = f"{pre} - {base}"
    return safe_name(base), uy


def date_of(doc: dict | None) -> str | None:
    t = (doc or {}).get("tarih")
    if isinstance(t, str) and re.match(r"\d{4}-\d{2}-\d{2}$", t):
        return t
    m = re.match(r"(\d{4}-\d{2}-\d{2})_", (doc or {}).get("calisma_adi") or "")
    return m.group(1) if m else None


def file_name(olcut: str, sira: int, od: int, ad: str, ext: str) -> str:
    """`[B.1.1-1-OD3] Ad.pdf`: geçen yılki Matematik kanıt adlarıyla ve kılavuzun kanıt
    listesi gösterimiyle (`[1-OD3]. Ad.pdf`) aynı; ölçüt öneki dosyayı klasörü dışında da
    tanınır kılar."""
    return f"[{olcut}-{sira}-OD{od}] {ad}{ext.lower()}"
