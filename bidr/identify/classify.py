"""Kural tabanlı tür tanıma. Girdi YALNIZ belge metnidir (dosya adı/yol yok)."""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from .catalog import UNKNOWN, Catalog
from .text import collapse, fold, looks_binary, quality

MIN_ALNUM = 40          # bundan az harf/rakam -> metin yok
MIN_QUALITY = 0.15      # okunabilir sözcük oranı bunun altındaysa -> okunamaz

# Kod: iki harf + 4 hane (katlanmış metinde). Künye bağlamı: önünde "form/doküman/
# iş akış no" ya da ardında "yayın tarihi".
_CODE = re.compile(r"(?<![a-z0-9])([a-z]{2}) ?[-;:]? ?(\d{4})(?!\d)")
_LABEL_BEFORE = re.compile(r"(form|dokuman|is ?akis)\s*(no|numarasi)?\s*[:;.]?\s*$")
_LABEL_AFTER = re.compile(r"^\s*[,;:]?\s*(yayin|yay\S{0,3}) ?tarihi")


@dataclass
class Doc:
    raw: str
    text: str = ""       # boşluğu sıkıştırılmış özgün metin
    folded: str = ""     # 1:1 katlanmış
    regions: dict = field(default_factory=dict)

    @classmethod
    def from_text(cls, raw: str, region_sizes: dict[str, int]) -> "Doc":
        t = collapse(raw)
        f = fold(t)
        n = len(f)
        regions = {
            "ust": (0, min(n, region_sizes["ust"])),
            "bas": (0, min(n, region_sizes["bas"])),
            "son": (max(0, n - region_sizes["son"]), n),
            "tum": (0, n),
        }
        return cls(raw=raw, text=t, folded=f, regions=regions)

    def quote(self, start: int, end: int, pad: int = 30, maxlen: int = 160) -> str:
        a, b = max(0, start - pad), min(len(self.text), end + pad)
        q = self.text[a:b]
        if len(q) > maxlen:
            q = q[:maxlen] + "…"
        return q


def find_codes(doc: Doc, prefixes: dict[str, str]) -> tuple[list[str], list[str]]:
    """(künye bağlamındaki kodlar [sıklık sırasıyla], yalnız anılan kodlar)."""
    labeled: Counter = Counter()
    mentioned: list[str] = []
    f = doc.folded
    for m in _CODE.finditer(f):
        pre = prefixes.get(m.group(1))
        if not pre:
            continue
        code = f"{pre}-{m.group(2)}"
        before = f[max(0, m.start() - 22):m.start()]
        after = f[m.end():m.end() + 20]
        if _LABEL_BEFORE.search(before) or _LABEL_AFTER.match(after):
            labeled[code] += 1
        elif code not in mentioned:
            mentioned.append(code)
    lab = [c for c, _ in labeled.most_common()]
    return lab, [c for c in mentioned if c not in lab]


def score(doc: Doc, catalog: Catalog, labeled_codes: list[str]) -> dict[str, dict]:
    res: dict[str, dict] = {}
    for t in catalog.types:
        total = 0.0
        ev = []
        for s in t.signatures:
            a, b = doc.regions[s.region]
            seg = doc.folded[a:b]
            if s.min_count > 1:
                ms = list(s.pattern.finditer(seg))
                if len(ms) < s.min_count:
                    continue
                m = ms[0]
                kind = "yapi"
                extra = {"sayi": len(ms)}
            else:
                m = s.pattern.search(seg)
                if not m:
                    continue
                kind = "baslik" if s.region in ("ust", "bas") else "ifade"
                extra = {}
            total += s.weight
            ev.append({"kural": f"{t.name}.{s.id}", "tur": kind if s.weight > 0 else "ceza",
                       "bolge": s.region, "agirlik": s.weight,
                       "alinti": doc.quote(a + m.start(), a + m.end()), "konum": a + m.start(),
                       "uzunluk": m.end() - m.start(), **extra})
        res[t.name] = {"puan": total, "kanitlar": ev}
    # künye kodları
    cw = catalog.code_weight
    seen_types = set()
    for i, code in enumerate(labeled_codes):
        tname, cname = catalog.code_info(code)
        if not tname:
            tname = "form_belgesi" if catalog.get("form_belgesi") else None
            w = cw / 2
        else:
            w = cw if i == 0 else cw / 2  # en sık kod tam, diğerleri yarım
        if not tname or tname in seen_types:
            continue
        seen_types.add(tname)
        pos = doc.folded.find(fold(code))
        r = res.setdefault(tname, {"puan": 0.0, "kanitlar": []})
        r["puan"] += w
        r["kanitlar"].append({"kural": f"kurum_kodu.{code}", "tur": "form_kodu", "bolge": "kunye",
                              "agirlik": w, "alinti": f"{code}" + (f" ({cname})" if cname else ""),
                              "konum": pos if pos >= 0 else None})
    return res


def classify(raw: str, catalog: Catalog) -> dict:
    doc = Doc.from_text(raw, catalog.regions)
    alnum = sum(ch.isalnum() for ch in doc.text)
    q = quality(doc.folded)
    labeled, mentioned = find_codes(doc, catalog.prefix_map())
    out = {
        "doc_type": UNKNOWN, "guven": 0.0, "guven_duzeyi": "yok", "puan": 0.0,
        "ikinci_tur": None, "ikinci_puan": 0.0, "kanitlar": [], "neden": None,
        "form_kodu": labeled[0] if labeled else None, "form_kodlari": labeled,
        "anilan_form_kodlari": mentioned[:20],
        "metin": {"karakter": len(doc.text), "okunabilirlik": q},
    }
    if looks_binary(raw):
        out["neden"] = "ikili_icerik"
        return out | {"_doc": doc}
    if alnum < MIN_ALNUM:
        out["neden"] = "metin_yok"
        return out | {"_doc": doc}
    scores = score(doc, catalog, labeled)
    order = {n: i for i, n in enumerate(catalog.names)}
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1]["puan"], order.get(kv[0], 999)))
    (best, bs), (second, ss) = ranked[0], ranked[1]
    top, sec = bs["puan"], ss["puan"]
    out["ikinci_tur"] = second if sec > 0 else None
    out["ikinci_puan"] = sec
    if q < MIN_QUALITY and top < catalog.threshold + 2:
        out["neden"] = "okunamaz_metin"
        out["puan"] = top
        return out | {"_doc": doc}
    if top < catalog.threshold:
        out["neden"] = "kural_tutmadi"
        out["puan"] = top
        out["aday"] = best if top > 0 else None
        return out | {"_doc": doc}
    margin = (top - max(sec, 0)) / top
    conf = round(min(1.0, top / 10) * (0.5 + 0.5 * margin), 2)
    level = "yuksek" if conf >= 0.6 else "orta" if conf >= 0.35 else "dusuk"
    out.update(doc_type=best, puan=top, guven=conf, guven_duzeyi=level,
               kanitlar=[e for e in bs["kanitlar"]])
    return out | {"_doc": doc}
