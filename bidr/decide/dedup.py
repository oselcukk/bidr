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
"""
from __future__ import annotations

import difflib
import hashlib
import re
import unicodedata

NEAR_MIN_TOKENS = 40
NEAR_MAX_DIFF = 8          # sözcük
NEAR_MAX_FRAC = 0.03
SHINGLE = 5
PREFILTER_JACCARD = 0.5

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
