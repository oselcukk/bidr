"""Redaksiyon doğrulaması: maskeli çıktıda her kapatılan kutunun altında çıkarılabilir metin ya da
görüntü verisi kalmadığını denetleyen son adım.

- PDF (PyMuPDF): kutunun içinde (kenarlardan biraz içeride) merkezi kalan kelimeler çıkarılır;
  maskeleyicinin yazdığı yer tutucular (`[TC_NO]`, `[İMZA]` …) ve bölgenin `geri_basilan` yazısı
  dışında harf/rakam kalırsa başarısız. Kutuyla kesişen her görüntünün (XObject) piksel verisi açılır,
  kutunun görüntüdeki karşılığı kırpılır: redaksiyon pikselleri tek renge boyar; kırpıntı tek renkli
  değilse (altında görüntü verisi kaldı) başarısız. Satır içi görüntü (xref 0) açılamaz: başarısız.
- Görsel: kutunun piksel karşılığı karanlık olmalı (siyah kutu + koyu gri yer tutucu yazısı).

Başarısızlıkta dosya `tamam` sayılmaz (kayıtta `redaksiyon_dogrulama`).
"""
from __future__ import annotations

import re
from pathlib import Path

_PLACEHOLDER = re.compile(r"\[[^\]\[]{1,24}\]|\[[A-ZÇĞİÖŞÜ_]+|[A-ZÇĞİÖŞÜ_]+\]")
TEK_RENK = 0.97              # kırpıntı piksellerinin en az bu kadarı aynı değerde
KARANLIK = 0.9               # görselde kutu piksellerinin en az bu kadarı koyu (< 128)


def _inner(k, pad: float):
    x0, y0, x1, y1 = k
    p = min(pad, (x1 - x0) / 4, (y1 - y0) / 4)
    return x0 + p, y0 + p, x1 - p, y1 - p


def _residual(text: str, allowed: list[str]) -> str:
    t = text
    for a in allowed:
        if a:
            for part in a.split():
                t = t.replace(part, " ")
    t = _PLACEHOLDER.sub(" ", t)
    return "".join(c for c in t if c.isalnum())


def _uniform(pix, x0: int, y0: int, x1: int, y1: int) -> bool:
    from collections import Counter
    n = pix.n
    samples = pix.samples
    stride = pix.stride
    c: Counter = Counter()
    tot = 0
    step = max(1, int(((x1 - x0) * (y1 - y0) / 20000) ** 0.5))
    for y in range(y0, y1, step):
        row = y * stride
        for x in range(x0, x1, step):
            o = row + x * n
            c[bytes(samples[o:o + n])] += 1
            tot += 1
    if not tot:
        return True
    return c.most_common(1)[0][1] / tot >= TEK_RENK


def pdf(path: Path, bolgeler: list[dict]) -> list[str]:
    from .formats import _fitz
    fitz = _fitz()
    if fitz is None:
        return []
    kapali = [b for b in bolgeler or [] if b.get("karar") == "kapatildi"]
    if not kapali:
        return []
    out: list[str] = []
    doc = fitz.open(str(path))
    try:
        words_by: dict[int, list] = {}
        imgs_by: dict[int, list] = {}
        pixes: dict[int, object] = {}
        for b in kapali:
            sn = int(b["sayfa"])
            if sn < 1 or sn > doc.page_count:
                out.append(f"{b.get('id')}: sayfa yok")
                continue
            page = doc[sn - 1]
            if sn not in words_by:
                words_by[sn] = page.get_text("words")
                try:
                    imgs_by[sn] = page.get_image_info(xrefs=True)
                except Exception:
                    imgs_by[sn] = []
            x0, y0, x1, y1 = _inner(b["kutu"], 1.0)
            if x1 <= x0 or y1 <= y0:
                continue
            inside = [w[4] for w in words_by[sn] if x0 <= (w[0] + w[2]) / 2 <= x1 and y0 <= (w[1] + w[3]) / 2 <= y1]
            res = _residual(" ".join(inside), [b.get("geri_basilan") or "", "imza gizlendi"])
            if res:
                out.append(f"{b.get('id')}: kutunun altında çıkarılabilir metin kaldı (s.{sn})")
                continue
            r = fitz.Rect(x0, y0, x1, y1)
            for info in imgs_by[sn]:
                ib = fitz.Rect(info["bbox"])
                inter = ib & r
                if inter.is_empty or inter.width < 1 or inter.height < 1:
                    continue
                xref = info.get("xref") or 0
                if not xref:
                    out.append(f"{b.get('id')}: kutunun altında açılamayan satır içi görüntü (s.{sn})")
                    break
                try:
                    pix = pixes.get(xref)
                    if pix is None:
                        pix = fitz.Pixmap(doc, xref)
                        if pix.alpha or pix.n > 4:
                            pix = fitz.Pixmap(fitz.csRGB, pix)
                        pixes[xref] = pix
                    inv = ~fitz.Matrix(info["transform"])
                except Exception:
                    out.append(f"{b.get('id')}: kutunun altındaki görüntü açılamadı (s.{sn})")
                    break
                pts = [fitz.Point(inter.x0, inter.y0) * inv, fitz.Point(inter.x1, inter.y1) * inv,
                       fitz.Point(inter.x0, inter.y1) * inv, fitz.Point(inter.x1, inter.y0) * inv]
                us = [min(1, max(0, p.x)) for p in pts]
                vs = [min(1, max(0, p.y)) for p in pts]
                px0, px1 = int(min(us) * pix.width) + 2, int(max(us) * pix.width) - 2
                py0, py1 = int(min(vs) * pix.height) + 2, int(max(vs) * pix.height) - 2
                if px1 <= px0 or py1 <= py0:
                    continue
                if not _uniform(pix, px0, py0, px1, py1):
                    out.append(f"{b.get('id')}: kutunun altında görüntü verisi kaldı (s.{sn})")
                    break
    finally:
        doc.close()
    return out


def gorsel(path: Path, bolgeler: list[dict]) -> list[str]:
    from .raster import _open_image, image_scale
    kapali = [b for b in bolgeler or [] if b.get("karar") == "kapatildi"]
    if not kapali:
        return []
    img = _open_image(path).convert("L")
    sc = image_scale(img)
    out = []
    for b in kapali:
        x0, y0, x1, y1 = _inner([v / sc for v in b["kutu"]], 1.0)
        x0, y0 = max(0, int(x0)), max(0, int(y0))
        x1, y1 = min(img.width, int(x1)), min(img.height, int(y1))
        if x1 <= x0 or y1 <= y0:
            continue
        hist = img.crop((x0, y0, x1, y1)).histogram()
        tot = sum(hist) or 1
        if sum(hist[:128]) / tot < KARANLIK:
            out.append(f"{b.get('id')}: kutu kapatılmamış görünüyor (görsel)")
    return out


def dogrula(path: Path, kind: str, bolgeler: list[dict], engine: str) -> list[str]:
    if kind == "pdf" and engine == "pymupdf":
        return pdf(path, bolgeler)
    if kind == "gorsel":
        return gorsel(path, bolgeler)
    return []
