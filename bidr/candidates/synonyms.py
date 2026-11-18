"""İkinci arama için eşanlamlı/yakın anlamlı terim grupları (bağımsız, veri değil kod).

Her grup aynı kanıt türünü farklı adlandırmalardır (kurum içi yazışmalarda yaygın).
Sorgu metninde bir grubun herhangi bir üyesi öbek olarak geçiyorsa (sözcükler tam, yalnız
ek serbest) grubun öteki üyelerinin sözcükleri sorguya eklenir (`expand`). Eklenen
sözcükler `text.tokens` ile belirtece indirgenir (aksan katlama, ilk 5 harf).
Grup yalnız ölçüt metni tarafını genişletir; belge metni değişmez.
"""
from __future__ import annotations

import re
from collections import Counter
from functools import lru_cache

from .text import bag, fold, tokens

_WORD = re.compile(r"[a-z]+")

GROUPS: tuple[tuple[str, ...], ...] = (
    ("tutanak", "toplantı tutanağı", "kurul kararı", "toplantı notu", "karar defteri"),
    ("anket", "memnuniyet", "geri bildirim", "görüş formu", "değerlendirme formu"),
    ("dış paydaş", "danışma kurulu", "sektör temsilcisi", "işveren temsilcisi"),
    ("öğrenme çıktıları", "program çıktıları", "kazanım", "yeterlilik"),
    ("iyileştirme", "düzeltici faaliyet", "önleyici faaliyet", "düzeltici önlem"),
    ("izleme", "takip", "gözden geçirme"),
    ("stratejik plan", "eylem planı", "performans göstergesi", "hedef kartı"),
    ("ders bilgi paketi", "ders izlencesi", "müfredat", "öğretim planı", "ders planı"),
    ("staj", "işyeri eğitimi", "uygulamalı eğitim", "işletmede mesleki eğitim"),
    ("öğrenci kulübü", "öğrenci topluluğu", "sosyal etkinlik", "kültürel etkinlik"),
    ("araştırma projesi", "bilimsel araştırma", "proje başvurusu", "tübitak", "bap"),
    ("yayın", "makale", "bildiri", "kitap bölümü"),
    ("toplumsal katkı", "topluma hizmet", "sosyal sorumluluk", "gönüllülük"),
    ("iç değerlendirme", "öz değerlendirme", "akreditasyon", "dış değerlendirme"),
    ("akademik danışmanlık", "danışman", "mentorluk", "rehberlik"),
    ("ölçme ve değerlendirme", "sınav", "başarı değerlendirme", "notlandırma"),
    ("engelli", "erişilebilirlik", "dezavantajlı", "özel gereksinim"),
    ("uluslararasılaşma", "erasmus", "değişim programı", "hareketlilik", "farabi", "mevlana"),
    ("eğiticinin eğitimi", "öğretim yetkinliği", "hizmet içi eğitim", "pedagojik eğitim"),
    ("laboratuvar", "altyapı", "donanım", "derslik"),
    ("insan kaynakları", "atama", "yükseltme", "kadro"),
    ("bilgi yönetim sistemi", "otomasyon", "veri tabanı", "bilgi sistemi"),
    ("kalite komisyonu", "kalite güvencesi", "kalite kurulu", "kalite elçisi"),
    ("yönetişim", "organizasyon şeması", "görev tanımı", "yetki devri"),
    ("ödül", "teşvik", "takdir belgesi", "başarı belgesi"),
    ("şikayet", "öneri sistemi", "dilek ve öneri"),
    ("mezun izleme", "mezun takibi", "mezun anketi", "istihdam"),
    ("önceki öğrenmelerin tanınması", "intibak", "muafiyet", "kredi transferi", "yatay geçiş"),
    ("iş birliği", "protokol", "iyi niyet anlaşması", "sözleşme"),
    ("bütçe", "mali kaynak", "harcama", "ödenek"),
    ("program tasarımı", "program açma", "program güncelleme", "müfredat güncelleme"),
)


@lru_cache(maxsize=1)
def _compiled() -> tuple[tuple[tuple[re.Pattern, tuple[str, ...]], ...], ...]:
    """Grup üyeleri: (katlanmış metinde sözcük-başı öbek deseni, belirteçler). Öbeğin her
    sözcüğü tam yazılır, yalnız sonuna ek gelebilir ("uygulamalı eğitim" "uygulamaları
    eğitim"le eşleşmez); 5 harflik kök çakışmaları genişletmeyi tetiklemez."""
    out = []
    for g in GROUPS:
        mem = []
        for p in g:
            words = _WORD.findall(fold(p))
            if words:
                pat = re.compile(r"\b" + r"\w*\s+".join(map(re.escape, words)) + r"\w*")
                mem.append((pat, tuple(tokens(p))))
        out.append(tuple(mem))
    return tuple(out)


def expand(text: str, q: Counter | None = None) -> tuple[Counter, list[str]]:
    """(metnin torbası + eşanlamlılar, eklenen belirteçler). Grup, metinde bir üyesi öbek
    olarak geçiyorsa tetiklenir. Eklenen belirteç sayısı 1'dir (asıl ölçüt sözcüklerinin
    ağırlığını bastırmasın); torbada zaten olan belirteç eklenmez."""
    out = Counter(bag(text) if q is None else q)
    ft = " ".join(_WORD.findall(fold(text)))
    added: list[str] = []
    for grp in _compiled():
        if not any(pat.search(ft) for pat, _ in grp):
            continue
        for _, toks in grp:
            for t in toks:
                if t not in out:
                    out[t] = 1
                    added.append(t)
    return out, added
