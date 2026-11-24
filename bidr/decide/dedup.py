"""Mükerrer metin: içerik hash'i (doc_id) farklı ama metni aynı ya da çok yakın belgeler.

Örnek: aynı e-postanın iki çıktısı (yalnız yazdırma saati farklı), aynı belgenin docx ve
PDF'i. Böyle bir grupta yalnız bir temsilci modele gider; ötekiler kararı devralır
(bkz. `run.inherit`). Devralan belgenin alıntıları KENDİ metnine karşı yeniden denetlenir;
temsilcinin kabul edilen bir eşleşmesi bile tutmazsa belge gruptan ayrılır ve kendisi
işlenir. Dosya adı/yolu kullanılmaz; yalnız `text/` ve documents.jsonl `doc_type`.

Eşleşme ölçütü (temkinli):
  - iskelet (NFKC, küçük harf, aksansız, harf/rakam dışı atılmış sözcük dizisi) eşit → "ayni_metin";
  - ya da en az `NEAR_MIN_TOKENS` sözcük, sözcük düzeyinde en çok `NEAR_MAX_DIFF` sözcük ve
    `NEAR_MAX_FRAC` oranında fark, `doc_type` aynı → "yakin_metin".
Aynı şablonu dolduran farklı belgeler (ör. farklı dönemin izleme tablosu: onlarca sayı
farklı) bu eşiği geçmez; OCR'ı farklı iki tarama da çoğunlukla geçmez (temkinli taraf).
identify'ın `surum_grubu`'su (kosinüs ≥ 0.90; farklı sürümler) karar devri için gevşektir,
kullanılmaz.

Tarama kopyası (`scan_copy_pairs`, yöntem "tarama_kopyasi"): aynı kâğıdın iki ayrı taraması (farklı
bayt, farklı OCR gürültüsü) yukarıdaki sözcük eşiğini geçmez. İki koşul BİRLİKTE aranır:
  - OCR metni: bidr/identify/versions.py kopya bağı (`CopyIndex.copy`: birincil tarihler aynı, türler
    uyumlu, baş bölge kimlikleri ayrık değil) ve şablon dışı parçacıklarda iki yönlü kapsama
    ≥ `SCAN_TEXT_MIN`;
  - sayfa görüntüsü: bidr/identify/imghash.py `same_pages` (sayfa sayısı eşit, her sayfa pHash
    uzaklığı eşikte).
Farklı tarihli/revizyonlu sürüm (metinde tarih ya da kimlik farkı) kopya sayılmaz; görüntüsü
karmalanamayan belge (docx, kaynağı bulunamayan) bu yoldan kopya olmaz.

Metin kopyası (`text_copy_pairs`, yöntem "metin_kopyasi"): farklı adla yeniden yüklenmiş, taranmamış
belge (metni aynı ya da neredeyse aynı; dışa aktarma/sayfa altlığı farkı yukarıdaki sözcük eşiğini
aşabilir). Görüntü koşulu yerine daha sıkı metin koşulu: birincil tarih İKİSİNDE DE var ve aynı,
`CopyIndex.copy` bağı (türler uyumlu, baş bölge kimlikleri ayrık değil) ve şablon dışı parçacıklarda iki
yönlü kapsama ≥ `TEXT_COPY_MIN`. Tarihsiz belge bu yoldan kopya olmaz (yalnız birebir/çok yakın metin).
"""
from __future__ import annotations

import difflib
import hashlib
import re
import unicodedata
from typing import Callable

NEAR_MIN_TOKENS = 40
NEAR_MAX_DIFF = 8          # sözcük
NEAR_MAX_FRAC = 0.03
SHINGLE = 5
PREFILTER_JACCARD = 0.5
SCAN_TEXT_MIN = 0.8        # tarama kopyası: OCR parçacıklarında iki yönlü kapsama (ölçülen gerçek çiftler 0,95–0,98)
TEXT_COPY_MIN = 0.9        # metin kopyası (görüntü koşulu yok): iki yönlü kapsama

_TOK = re.compile(r"[a-z0-9]+")


def skeleton(text: str) -> list[str]:
    t = unicodedata.normalize("NFKC", text).replace("İ", "i").replace("I", "ı").lower()
    t = "".join(c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c))
    return _TOK.findall(t.replace("ı", "i"))


def _diff_tokens(a: list[str], b: list[str]) -> int:
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return sum(max(i2 - i1, j2 - j1) for op, i1, i2, j1, j2 in sm.get_opcodes() if op != "equal")


def find_groups(texts: dict[str, str], types: dict[str, str | None] | None = None
                ) -> list[dict]:
    """Gruplar: [{"uyeler": [doc_id…] (sıralı), "toks": {doc_id: iskelet}}].
    Tek başına olan belge grup oluşturmaz. Boş metinli belge gruplanmaz."""
    types = types or {}
    toks = {k: skeleton(v) for k, v in texts.items()}
    toks = {k: v for k, v in toks.items() if v}
    parent = {k: k for k in toks}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    by_hash: dict[str, list[str]] = {}
    for k, v in toks.items():
        by_hash.setdefault(hashlib.sha1(" ".join(v).encode()).hexdigest(), []).append(k)
    for ks in by_hash.values():
        for x in ks[1:]:
            union(ks[0], x)
    # yakın metin: yalnız her kesin grubun bir temsilcisi karşılaştırılır
    reps = sorted(min(ks) for ks in by_hash.values() if len(toks[min(ks)]) >= NEAR_MIN_TOKENS)
    sh = {k: {tuple(toks[k][i:i + SHINGLE]) for i in range(len(toks[k]) - SHINGLE + 1)} for k in reps}
    for i, a in enumerate(reps):
        for b in reps[i + 1:]:
            la, lb = len(toks[a]), len(toks[b])
            if abs(la - lb) > NEAR_MAX_DIFF:
                continue
            ta, tb = types.get(a), types.get(b)
            if ta != tb:
                continue
            inter = len(sh[a] & sh[b])
            if inter / (len(sh[a] | sh[b]) or 1) < PREFILTER_JACCARD:
                continue
            n = _diff_tokens(toks[a], toks[b])
            if n <= NEAR_MAX_DIFF and n / max(la, lb) <= NEAR_MAX_FRAC:
                union(a, b)
    groups: dict[str, list[str]] = {}
    for k in toks:
        groups.setdefault(find(k), []).append(k)
    out = []
    for members in groups.values():
        if len(members) > 1:
            out.append({"uyeler": sorted(members), "toks": {m: toks[m] for m in members}})
    return sorted(out, key=lambda g: g["uyeler"][0])


def relation(group: dict, rep: str, member: str) -> tuple[str, int] | None:
    """Üyenin temsilciye göre bağı: ("ayni_metin", 0) | ("yakin_metin", fark) | None (zincirleme
    benzerlikle gruba girmiş ama temsilciden eşikten çok farklı: devralmaz)."""
    a, b = group["toks"][rep], group["toks"][member]
    if a == b:
        return "ayni_metin", 0
    n = _diff_tokens(a, b)
    if n <= NEAR_MAX_DIFF and n / max(len(a), len(b)) <= NEAR_MAX_FRAC:
        return "yakin_metin", n
    return None


def _copy_text_pairs(texts: dict[str, str], dates: dict[str, str | None], types: dict[str, str | None],
                     esik: float, tarih_sart: bool):
    """Metni kopya olan çiftler (iki yönlü kapsama ≥ `esik`, tarih/tür/kimlik uyumlu) → (a, b, benzerlik)
    üreteci. `tarih_sart`: birincil tarih ikisinde de olmalı (ve aynı)."""
    from bidr.identify import versions as V
    from bidr.identify.text import collapse, fold
    ft = {k: fold(collapse(v)) for k, v in texts.items() if v and v.strip()}
    if len(ft) < 2:
        return
    ty = {k: v for k, v in types.items() if v}
    ix = V.CopyIndex(ft)
    for a, b, _ in V.copy_pairs(ft, dates, ty):
        if tarih_sart and not (dates.get(a) and dates.get(a) == dates.get(b)):
            continue
        if ix.copy(a, b, dates.get(a), dates.get(b), ty.get(a), ty.get(b)) is None:
            continue
        lo, hi = V.containment(ix.inf[a], ix.inf[b])
        if min(lo, hi) < esik:
            continue
        yield min(a, b), max(a, b), round(min(lo, hi), 3)


def scan_copy_pairs(texts: dict[str, str], dates: dict[str, str | None], types: dict[str, str | None],
                    hashes: Callable[[str], list[str] | None]) -> list[tuple[str, str, float]]:
    """Aynı kâğıdın ayrı taramaları → [(a, b, metin benzerliği)]: OCR metni kopya (iki yönlü kapsama
    ≥ SCAN_TEXT_MIN, tarih/tür/kimlik uyumlu) VE sayfa karmaları aynı. `hashes(doc_id)` yalnız
    metin adayı çiftler için çağrılır (görüntü çizimi pahalı)."""
    from bidr.identify.imghash import same_pages
    out = [(a, b, v) for a, b, v in _copy_text_pairs(texts, dates, types, SCAN_TEXT_MIN, False)
           if same_pages(hashes(a), hashes(b))]
    return sorted(set(out))


def text_copy_pairs(texts: dict[str, str], dates: dict[str, str | None],
                    types: dict[str, str | None]) -> list[tuple[str, str, float]]:
    """Farklı adla yeniden yüklenmiş (taranmamış) belge → [(a, b, metin benzerliği)]: birincil tarih
    ikisinde de var ve aynı, metin kopya bağı ve iki yönlü kapsama ≥ TEXT_COPY_MIN (görüntü gerekmez)."""
    return sorted(set(_copy_text_pairs(texts, dates, types, TEXT_COPY_MIN, True)))
