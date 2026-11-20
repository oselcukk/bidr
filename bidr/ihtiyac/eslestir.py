"""Karşılık eşleştirme: her referans öğe için güncel çalışma alanında aynı türden, benzer adlı/anahtar
sözcüklü belge aranır.

Benzerlik araçları `bidr.identify.versions`'tan (salt kullanım): OCR'a dayanıklı içerik parmak izi
(`fingerprint`, `containment`; aynı belgenin kopyası) ve `types_compatible`. Ek olarak anahtar sözcük
ve ad örtüşmesi (güncel derlemin IDF'iyle ağırlıklı).

Durum:
  var            dönem içi (ya da dönemi zamana bağlı olmayan yapı belgesi) karşılık bulundu
  eski_surum     yalnız önceki döneme ait karşılık (aynı belge ya da aynı türün eski yılı)
  yok_istenmeli  aynı türden, benzer adlı belge yok → istenmeli
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from bidr.common import Workspace, read_jsonl
from bidr.identify.versions import (COPY_HI, COPY_LO, COPY_STRICT, COPY_TEMPLATE_DF, COPY_TEMPLATE_FRAC,
                                    TEMPLATE_TYPES, containment, types_compatible)

from .referans import BAS, ORNEK, _SOZ, ad_sozcukleri, parmak_izi
from .tablolar import Turler, norm

VAR, ESKI, YOK = "var", "eski_surum", "yok_istenmeli"
DURUMLAR = (VAR, ESKI, YOK)
ESIK = 0.55             # birleşik benzerlik eşiği (tür + ad + anahtar sözcük)
KW_MIN = 0.40           # anahtar sözcük örtüşmesi alt sınırı (konu aynı olmalı)
BAS_AGIRLIK = 0.6       # ad başlıkta değil yalnız metnin başında geçiyorsa
KW_TURSUZ, AD_TURSUZ = 0.80, 0.40   # tür uyuşmadığında gereken içerik ve ad örtüşmesi
AD_YAPI = 0.70          # tekrarlamayan belgede kopya değilse gereken ad örtüşmesi
KOPYA_MIN = 8           # parmak izinde (örneklenmiş, şablon dışı) en az bu kadar karma
W_KW, W_AD, W_TUR = 0.45, 0.35, 0.20
BILINMEZ = ("", None, "bilinmiyor")


@dataclass
class Hedef:
    """Güncel çalışma alanının eşleştirme için özeti."""
    ws: Workspace
    donem: int | None
    docs: dict[str, dict]
    tokens: dict[str, set[str]]
    titles: dict[str, set[str]]
    heads: dict[str, set[str]]
    tekrar: dict[str, str]
    adlar: dict[str, str]
    olcutler: dict[str, dict[str, bool]]          # doc_id → {ölçüt: sayılıyor mu}
    idf: dict[str, float]
    _fp: dict[str, frozenset] = field(default_factory=dict)
    _template: set[int] | None = None

    def ad(self, did: str) -> str:
        return self.adlar.get(did) or (self.docs.get(did) or {}).get("calisma_adi") or did

    def text(self, did: str) -> str:
        p = self.ws.text_path(did)
        return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""

    def template(self) -> set[int]:
        """Derlemde çok belgede geçen (form/kurum kalıbı) parçacıklar: kopya kararında sayılmaz."""
        if self._template is None:
            df: Counter = Counter()
            for did in self.docs:
                df.update(self.fp(did, raw=True))
            lim = max(COPY_TEMPLATE_DF, int(COPY_TEMPLATE_FRAC * len(self.docs)))
            self._template = {h for h, n in df.items() if n >= lim}
        return self._template

    def fp(self, did: str, raw: bool = False) -> frozenset:
        if did not in self._fp:
            self._fp[did] = frozenset(parmak_izi(self.text(did)))
        return self._fp[did] if raw else self._fp[did] - self.template()


def load_target(ws_root: Path, audit, turler: Turler) -> Hedef:
    """`audit`: bidr.audit.run.build sonucu (satırlar, birim aitliği)."""
    ws = Workspace(ws_root)
    docs = {r["doc_id"]: r for r in read_jsonl(ws.documents)} if ws.documents.exists() else {}
    baska = {x["doc_id"] for x in (audit.birim or {}).get("baska_birim") or []}
    docs = {k: v for k, v in docs.items() if k not in baska}
    adlar: dict[str, str] = {}
    olc: dict[str, dict[str, bool]] = {}
    for r in audit.rows:
        if r.get("kanit_adi") and r["doc_id"] not in adlar:
            adlar[r["doc_id"]] = r["kanit_adi"]
        if r.get("karar") != "ret":
            d = olc.setdefault(r["doc_id"], {})
            d[r["olcut"]] = d.get(r["olcut"], False) or bool(r.get("sayilir"))
    tokens, titles, heads, tekrar = {}, {}, {}, {}
    for did, d in docs.items():
        p = ws.text_path(did)
        t = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
        tokens[did] = set(_SOZ.findall(norm(t)))
        head = " ".join([adlar.get(did, ""), d.get("baslik") or "", d.get("calisma_adi") or ""])
        titles[did] = set(ad_sozcukleri(head))
        heads[did] = set(ad_sozcukleri(t[:300]))
        tr = turler.bul(d.get("doc_type"), " ".join([head, t[:BAS]]))
        tekrar[did] = tr.id if tr else ""
    df: Counter = Counter()
    for s in tokens.values():
        df.update(s)
    n = len(tokens)
    idf = {w: math.log((n + 1) / (c + 1)) + 1.0 for w, c in df.items()}
    return Hedef(ws, audit.donem, docs, tokens, titles, heads, tekrar, adlar, olc, idf)


def _weighted(words: list[str], have: set[str], idf: dict[str, float], default: float) -> float:
    if not words:
        return 0.0
    tot = sum(idf.get(w, default) for w in words)
    return sum(idf.get(w, default) for w in words if w in have) / tot if tot else 0.0


def _tur_puani(it: dict, h: Hedef, did: str) -> float:
    dt = (h.docs.get(did) or {}).get("doc_type")
    if it.get("tekrarlayan") and h.tekrar.get(did) == it["tekrarlayan"]:
        return 1.0
    bt = it.get("belge_turu")
    if bt not in BILINMEZ and bt == dt:
        return 1.0
    if bt in BILINMEZ or dt in BILINMEZ:
        return 0.5
    return 1.0 if types_compatible(bt, dt) else 0.0


def _kopya(ref_fp: list[int] | None, h: Hedef, did: str, ref_type: str | None = None) -> float | None:
    """İçerik kopyası mı (bidr.identify.versions eşikleri: iki yönlü kapsama; kalıp türünde —
    iş akışı, yönerge, form… — kardeş kalıplar ayrılsın diye iki yönde COPY_STRICT)."""
    if not ref_fp:
        return None
    a = frozenset(ref_fp) - h.template()
    b = h.fp(did)
    if len(a) < KOPYA_MIN or len(b) < KOPYA_MIN:
        return None
    lo, hi = containment(a, b)
    strict = ref_type in TEMPLATE_TYPES or (h.docs.get(did) or {}).get("doc_type") in TEMPLATE_TYPES
    need_lo, need_hi = (COPY_STRICT, COPY_STRICT) if strict else (COPY_LO, COPY_HI)
    return round(lo, 3) if lo >= need_lo and hi >= need_hi else None


def adaylar(it: dict, ref_doc: dict | None, h: Hedef) -> list[dict]:
    """Eşik üstü karşılık adayları (benzerliğe göre azalan)."""
    default = max(h.idf.values()) if h.idf else 1.0
    kws, ads = it.get("anahtar") or [], it.get("ad_sozcukleri") or []
    fp = (ref_doc or {}).get("parmak_izi")
    out = []
    tekrar = bool(it.get("tekrarlayan"))
    for did in h.docs:
        tur = _tur_puani(it, h, did)
        kw = _weighted(kws, h.tokens.get(did, set()), h.idf, default)
        if tur == 0.0 and kw < KW_MIN:
            continue
        ad = max(_weighted(ads, h.titles.get(did, set()), h.idf, default),
                 BAS_AGIRLIK * _weighted(ads, h.heads.get(did, set()), h.idf, default))
        sim = W_KW * kw + W_AD * ad + W_TUR * tur
        kop = 1.0 if it.get("doc_id") and it["doc_id"] == did else None
        if kop is None and kw >= 0.5 * KW_MIN and fp:
            kop = _kopya(fp, h, did, it.get("belge_turu"))            # içerik kopyası türden bağımsız aynı belgedir
        if kop is None:
            if tur == 0.0 and not (kw >= KW_TURSUZ and ad >= AD_TURSUZ):
                continue                        # tür farklı: yalnız içerik ve ad çok yakınsa (tür yanlış atanmış olabilir)
            if kw < KW_MIN or (tur > 0.0 and sim < ESIK):
                continue
            if not tekrar and ad < AD_YAPI:
                # tekrarlamayan belge (yönerge, iş akışı…) kardeş kalıplardan ayrılmalı: ad da tutmalı
                continue
        out.append({"doc_id": did, "benzerlik": round(max(sim, 0.9) if kop else sim, 3), "kopya": kop,
                    "kw": round(kw, 2), "ad": round(ad, 2), "tur": tur,
                    **zaman(h.docs.get(did) or {}, bool(it.get("tekrarlayan")))})
    out.sort(key=lambda x: (x["kopya"] is not None, x["benzerlik"]), reverse=True)
    return out


def _neden(c: dict) -> str:
    if c["kopya"] is not None:
        return f"aynı belge (içerik kopyası %{round(100 * c['kopya'])})"
    return (f"benzer belge (anahtar sözcük %{round(100 * c['kw'])}, ad %{round(100 * c['ad'])}, "
            f"tür {'aynı' if c['tur'] == 1.0 else 'belirsiz' if c['tur'] else 'farklı'})")


def zaman(doc: dict, tekrar: bool) -> dict:
    """Belgenin rapor yılına göre zamanı (audit dönem kuralının `doc_time`/`yapi_time`'ı; salt okunur):
    {"zaman": ici|once|sonra|bilinmiyor, "yil": int|None}. Tekrarlayan türde olay zamanı, öteki
    belgelerde yürürlük aralığı da sayılır."""
    from bidr.audit import donem as D
    t = D.doc_time(doc) if tekrar else D.yapi_time(doc)
    return {"zaman": t["zaman"], "yil": t.get("yil")}


def _yil(s: str | None) -> int | None:
    try:
        return int(str(s)[:4]) if s else None
    except ValueError:
        return None


def eslestir(it: dict, ref_doc: dict | None, h: Hedef) -> dict:
    """Durum kuralı. Tekrarlayan tür: dönem içi → var; yalnız önceki yıl → eski_surum; yalnız dönem
    sonrası → yok_istenmeli (dönem içi sürümü istenmeli); tarihi bilinmeyen → var + doğrulanmalı.
    Tekrarlamayan (yapı) belge: karşılığın yılı referans belgenin yılından eskiyse eski_surum,
    değilse var (dönem içi değilse yürürlüğü doğrulanmalı)."""
    cs = adaylar(it, ref_doc, h)
    tekrar = bool(it.get("tekrarlayan"))
    by = {z: [c for c in cs if c["zaman"] == z] for z in ("ici", "once", "sonra", "bilinmiyor")}
    dogrula = False
    c, durum, neden = None, YOK, "aynı türden, benzer adlı/anahtar sözcüklü belge bulunamadı"
    ry = _yil(it.get("tarih"))
    if by["ici"]:
        c, durum = by["ici"][0], VAR
        neden = _neden(c) + f"; dönem içi ({h.donem})"
    elif tekrar:
        if by["bilinmiyor"]:
            c, durum, dogrula = by["bilinmiyor"][0], VAR, True
            neden = _neden(c) + "; tarihi dönemle bağlanamadı: bu yıla ait olduğu doğrulanmalı (tekrarlayan tür)"
        elif by["once"]:
            c, durum = by["once"][0], ESKI
            neden = (_neden(c) + f"; yalnız önceki döneme ait karşılık ({c['yil'] or '?'}): {h.donem} "
                     "sürümü istenmeli (tekrarlayan tür)")
        elif by["sonra"]:
            c = by["sonra"][0]
            neden = (_neden(c) + f"; yalnız dönem sonrası karşılık ({c['yil'] or '?'}): {h.donem} sürümü "
                     "istenmeli (tekrarlayan tür)")
    else:
        rest = by["bilinmiyor"] + by["sonra"] + by["once"]
        rest.sort(key=lambda x: (x["kopya"] is not None, x["benzerlik"]), reverse=True)
        yeni = [x for x in rest if not (ry and x["yil"] and x["yil"] < ry)]
        if yeni:
            c, durum, dogrula = yeni[0], VAR, True
            neden = _neden(c) + (f"; dönem dışı tarihli ({c['yil'] or 'tarihsiz'}): rapor yılında yürürlükte "
                                 "olduğu doğrulanmalı")
        elif rest:
            c, durum = rest[0], ESKI
            neden = (_neden(c) + f"; karşılık referans belgeden eski ({c['yil']} < {ry}): güncel sürümü "
                     "istenmeli")
    out = {"id": it["id"], "durum": durum, "gerekce": neden, "donem_dogrulanmali": dogrula,
           "aday_sayisi": len(cs)}
    if c:
        d = h.docs.get(c["doc_id"]) or {}
        es = h.olcutler.get(c["doc_id"], {})
        out.update({"karsilik_doc_id": c["doc_id"], "karsilik_ad": h.ad(c["doc_id"]),
                    "karsilik_tur": d.get("doc_type") or "", "karsilik_tarih": d.get("tarih") or "",
                    "benzerlik": c["benzerlik"], "kopya": c["kopya"],
                    "olcute_eslesmis": ("evet (sayılıyor)" if es.get(it["olcut"]) else
                                        "evet (sayılmıyor)" if it["olcut"] in es else "hayır")})
        if durum == VAR and it["olcut"] not in es:
            out["gerekce"] += "; belge çalışma alanında var ama bu ölçüte eşleşmemiş: karar/inceleme gözden geçirilmeli"
    return out


def eslestir_hepsi(ref: dict, h: Hedef) -> list[dict]:
    belgeler = ref.get("belgeler") or {}
    cache: dict[tuple, dict] = {}
    out = []
    for it in ref.get("ogeler") or []:
        key = (it.get("doc_id") or "", it.get("kanit_adi"), it.get("belge_turu"), it.get("tekrarlayan"),
               it["olcut"])
        if key not in cache:
            cache[key] = eslestir(it, belgeler.get(it.get("doc_id") or ""), h)
        out.append({**cache[key], "id": it["id"]})
    return out


__all__ = ["VAR", "ESKI", "YOK", "DURUMLAR", "Hedef", "load_target", "eslestir", "eslestir_hepsi", "adaylar",
           "ORNEK"]
