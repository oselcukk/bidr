"""Komisyon/görev tanımı tabloları: komisyon görevleriyle ilişkili ölçütler (aday ekleme).

Bölümün "Komisyon Adı … Görev Tanımı" tablosu (kurul ve komisyon listesi, görev dağılımı) her
satırında başka bir sürecin organizasyonel yapısını kanıtlar (değişim programları komisyonu →
uluslararasılaşma, danışmanlık → akademik destek …). Belirleyici sıralama belgeyi bütün olarak
puanladığından bu satırların çoğu ilk adaylara girmez; komisyon adı ile ölçüt sözcükleri de
çoğu zaman örtüşmez ("değişim programları" ↔ "uluslararasılaşma"). Bu modül (1) belgenin böyle bir
tablo olduğunu başlık sinyalinden tanır, (2) metinde geçen komisyon görev alanlarını ölçütlere
eşler. Karar aşaması (`bidr decide`) eşlenen ölçütleri ince karar adaylarına ekler ve aday
tavanını yükseltir. Eşleme veri değil koddur (synonyms.py gibi); yalnız bu belgelerde kullanılır.
"""
from __future__ import annotations

import re

from .text import fold

# Tablo başlığı: "Komisyon Adı" ve ardından (aynı başlık satırı/bölgesi) "Görev Tanımı".
BASLIK = re.compile(r"komisyon\s+adi\W[\s\S]{0,250}?gorev\s+tanim")

# (katlanmış metinde desen, ölçüt). Sıra önemsiz: ölçütler metindeki ilk geçiş sırasıyla döner.
GOREV_OLCUT: tuple[tuple[str, str], ...] = (
    (r"danisma kurul|dis paydas", "A.4.1"),
    (r"degisim program|erasmus|farabi|mevlana|uluslararasi (?:iliski|ofis|koordinat)", "A.5.1"),
    (r"danisman|rehberlik|kariyer", "B.3.2"),
    (r"kalite (?:kurul|komisyon)", "A.1.4"),
    (r"muafiyet|intibak|yatay gecis|yandal", "B.2.3"),
    (r"mufredat|ders plan|ogretim plan", "B.1.5"),
    (r"olcme ve degerlendirme|ders dosya", "B.2.2"),
    (r"anket", "A.4.2"),
    (r"mezun (?:iliski|izleme|takip)", "A.4.3"),
    (r"is sagligi|alt ?yapi|laboratuvar", "B.3.3"),
    (r"engelli|dezavantaj", "B.3.4"),
    (r"tesvik|odul", "B.4.3"),
    (r"web (?:sayfa|site|komisyon)|iletisim \(?web", "A.1.5"),
    (r"doktora yeterlik", "C.1.3"),
    (r"toplumsal katki", "D.1.1"),
)
_GOREV = tuple((re.compile(r"\b(?:" + p + r")"), c) for p, c in GOREV_OLCUT)


def _flat(text: str) -> str:
    return " ".join(fold(text or "").split())


def is_committee_table(text: str) -> bool:
    """Metin bir komisyon/görev tanımı tablosu mu ("Komisyon Adı … Görev Tanımı" başlığı)."""
    return bool(BASLIK.search(_flat(text)))


def committee_criteria(text: str, allowed: set[str] | None = None) -> list[str]:
    """Komisyon tablosunda geçen görev alanlarının ölçütleri, metindeki ilk geçiş sırasıyla.
    Tablo değilse boş liste."""
    t = _flat(text)
    m = BASLIK.search(t)
    if not m:
        return []
    t = t[m.start():]
    hits = []
    for pat, c in _GOREV:
        if allowed is not None and c not in allowed:
            continue
        x = pat.search(t)
        if x:
            hits.append((x.start(), c))
    out: list[str] = []
    for _, c in sorted(hits):
        if c not in out:
            out.append(c)
    return out
