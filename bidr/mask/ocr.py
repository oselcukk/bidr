"""Görüntüdeki kişisel veri: yerel OCR (tesseract) ile kelime kutuları ve desen eşleşen kutular.

Taranmış PDF sayfaları, tam sayfa görüntülü PDF sayfaları ve görsel dosyalar (jpg/png …) için
kullanılır. tesseract sistem aracıdır (`bidr.ingest.ocr` ile aynı yol: subprocess + TSV çıktısı);
yeni Python bağımlılığı yoktur. tesseract ya da `tur+eng` dil verisi yoksa `ocr_available()`
False döner ve çağıran sayfayı "taranamadı" sayar (asla "tamam" değil).

Kelimeler satırlara göre birleştirilir, `detect` aynı kurallarla çalışır; OCR'ın sayılarda sık
yaptığı karışıklıklar (O↔0, l/I↔1, S↔5, B↔8) ve sayı içindeki tek boşluklar için ek iki geçiş
yapılır (yalnız rakam ağırlıklı belirteçlerde; T.C. algoritması yanlış pozitifi süzer).
Değerler bellekte kalır; dışarı yalnız tür ve kutu çıkar.

Önbellek: aynı görüntü süreç içinde bellekten, süreçler/çalıştırmalar arasında çalışma alanının
SQLite önbelleğinden (`onbellek`, katman `ocr`; anahtar = PNG sha256 + tesseract sürümü + dil + psm +
görüntü boyutu) gelir: kural değişse de değişmeyen sayfa yeniden OCR'lanmaz. tesseract tek iş
parçacığıyla çalışır (`OMP_THREAD_LIMIT=1`; paralellik dosya düzeyinde).
"""
from __future__ import annotations

import functools
import hashlib
import io
import re
import subprocess
from collections import Counter, OrderedDict
from dataclasses import dataclass
from pathlib import Path

from .detect import MaskRules, detect

OCR_DPI = 300                  # PDF sayfası OCR çözünürlüğü
_CACHE: "OrderedDict[str, list]" = OrderedDict()
_CACHE_MAX = 48
CAGRI: Counter = Counter()     # süreç içi tesseract çağrısı (psm → sayı): önbellek testleri için


class OcrFailed(RuntimeError):
    pass


@dataclass(frozen=True)
class Word:
    text: str
    conf: float
    x0: float
    y0: float
    x1: float
    y1: float
    line: tuple = ()

    @property
    def box(self) -> tuple[float, float, float, float]:
        return (self.x0, self.y0, self.x1, self.y1)

    @property
    def h(self) -> float:
        return self.y1 - self.y0


def ocr_available() -> bool:
    try:
        from bidr.ingest.ocr import ocr_available as _ok
        return _ok()
    except Exception:
        return False


@functools.lru_cache(maxsize=1)
def tesseract_version() -> str:
    try:
        r = subprocess.run(["tesseract", "--version"], capture_output=True, timeout=30)
        out = (r.stdout or r.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        return out[0].strip() if out else "?"
    except (OSError, subprocess.SubprocessError):
        return "?"


def _env1() -> dict:
    from bidr.ingest.ocr import _env
    env = _env()
    env["OMP_THREAD_LIMIT"] = "1"          # paralellik dosya düzeyinde (işçiler); tesseract tek iş parçacığı
    return env


def _run_tesseract(png: bytes, psm: str | None = None) -> str:
    from bidr.ingest.ocr import OCR_LANGS, OCR_TIMEOUT, _SLOTS, _decode, _psm, _tempdir, _tool_error
    CAGRI[psm or "vars"] += 1
    with _tempdir("bidr-maske-") as td:
        src = Path(td) / "s.png"
        src.write_bytes(png)
        base = Path(td) / "o"
        with _SLOTS:
            r = subprocess.run(["tesseract", str(src), str(base), "-l", OCR_LANGS, "--psm", psm or _psm(), "tsv"],
                               capture_output=True, timeout=OCR_TIMEOUT, env=_env1())
        out = base.with_suffix(".tsv")
        if r.returncode != 0 or not out.exists():
            raise OcrFailed(str(_tool_error("tesseract", r.returncode, _decode(r.stderr), str(src))))
        return out.read_text(encoding="utf-8", errors="replace")


def parse_tsv(tsv: str) -> list[Word]:
    words = []
    for line in tsv.splitlines()[1:]:
        p = line.split("\t")
        if len(p) < 12 or p[0] != "5":
            continue
        t = p[11].strip()
        if not t:
            continue
        try:
            x, y, w, h = (int(p[6]), int(p[7]), int(p[8]), int(p[9]))
            conf = float(p[10])
        except ValueError:
            continue
        words.append(Word(t, conf, x, y, x + w, y + h, (int(p[1]), int(p[2]), int(p[3]), int(p[4]))))
    return words


def ocr_words(img, psm: str | None = None) -> list[Word]:
    """PIL görüntüsü → kelimeler (piksel koordinatı). Aynı görüntü için önbellekli. `psm`: tesseract
    sayfa bölme kipi (varsayılan: ingest'inki; küçük kırpıntı için "6" tek blok)."""
    if not ocr_available():
        raise OcrFailed("tesseract ya da tur+eng dil verisi yok")
    buf = io.BytesIO()
    im = img if img.mode in ("L", "RGB") else img.convert("RGB")
    im.save(buf, format="PNG")
    png = buf.getvalue()
    key = hashlib.sha1(png).hexdigest() + (psm or "")
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    from bidr.ingest.ocr import OCR_LANGS, _psm
    from . import onbellek
    ob = onbellek.aktif()
    pkey = None
    tsv = None
    if ob is not None:
        pkey = onbellek.anahtar("ocr", onbellek.sha256(png), tesseract_version(), OCR_LANGS, psm or _psm(),
                                im.size, im.mode)
        b = ob.get("ocr", pkey)
        tsv = b.decode("utf-8") if b is not None else None
    if tsv is None:
        tsv = _run_tesseract(png, psm)
        if ob is not None:
            ob.put("ocr", pkey, tsv.encode("utf-8"))
    words = parse_tsv(tsv)
    _CACHE[key] = words
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return words


# ---------------------------------------------------------------- metin ↔ kutu eşleme

_OCR_DIGIT = str.maketrans({"O": "0", "o": "0", "D": "0", "Q": "0", "l": "1", "I": "1", "|": "1", "i": "1",
                            "!": "1", "S": "5", "s": "5", "B": "8", "Z": "2", "z": "2"})


_OCR_AT = str.maketrans({"©": "@", "®": "@"})


def _digitish(tok: str) -> bool:
    core = tok.strip(".,:;()[]")
    if len(core) < 5:
        return False
    d = sum(c.isdigit() for c in core)
    return d >= 0.6 * len(core)


def _lines(words: list[Word]) -> list[list[int]]:
    order: dict = {}
    for i, w in enumerate(words):
        order.setdefault(w.line, []).append(i)
    return list(order.values())


def _build(words: list[Word], variant: int) -> tuple[str, list[tuple[int, int] | None]]:
    """Sayfa metni + karakter başına (kelime no, kelime içi konum). variant: 0 düz, 1 rakam/@
    düzeltmeli, 2 ayrıca sayılar arası ve e-posta noktalaması (. @ _ -) yanındaki boşluk kaldırılmış."""
    chars: list[str] = []
    where: list = []
    for li in _lines(words):
        for k, i in enumerate(li):
            t = words[i].text
            if variant:
                t = t.translate(_OCR_AT)
                if _digitish(t):
                    t = t.translate(_OCR_DIGIT)
            if k:
                prev = chars[-1] if chars else ""
                join = variant == 2 and ((prev.isdigit() and t[:1].isdigit())
                                         or prev in ".@_-" or t[:1] in ".@_-")
                if not join:
                    chars.append(" ")
                    where.append(None)
            for j, c in enumerate(t):
                chars.append(c)
                where.append((i, j))
        chars.append("\n")
        where.append(None)
    return "".join(chars), where


_EMAIL_LABEL = re.compile(r"(?i)^(e-?posta|e-?mail|mail|eposta)\b")
_DOMAINISH = re.compile(r"(?i)^[\w.+\-@©®]*[\w\-]\.(com|net|org|edu|gov|info|k12|bel|tsk|pol|av|biz)(\.tr)?[.,;:)]?$")


def _ocr_email_hits(words: list[Word]):
    """OCR'ın '@' işaretini kaçırdığı e-postalar: "E-posta:" etiketinden sonra satırdaki alan adı
    benzeri belirtece kadar olan kelimeler (etiket hariç). www./http ile başlayan adres değil."""
    for li in _lines(words):
        for a, i in enumerate(li):
            if not _EMAIL_LABEL.match(words[i].text.strip("(:")):
                continue
            for b in range(a + 1, min(len(li), a + 5)):
                t = words[li[b]].text
                if t.lower().startswith(("www.", "http")):
                    break
                if _DOMAINISH.match(t):
                    idx = li[a + 1:b + 1]
                    yield tuple(sorted(idx)), {j: list(range(len(words[j].text))) for j in idx}
                    break


def pii_hits(words: list[Word], rules: MaskRules) -> list[tuple[str, list[tuple[float, float, float, float]]]]:
    """Bulgu başına (tür, [satır kutuları (x0,y0,x1,y1)]); kelime içi eşleşmede kutu harf oranıyla
    daraltılır (biraz pay bırakılarak)."""
    hits: dict[tuple[int, ...], tuple[str, dict]] = {}
    for variant in (0, 1, 2):
        text, where = _build(words, variant)
        for f in detect(text, rules):
            span: dict[int, list[int]] = {}
            for p in range(f.start, f.end):
                w = where[p]
                if w is not None:
                    span.setdefault(w[0], []).append(w[1])
            key = tuple(sorted(span))
            if key and not any(set(key) <= set(k) for k in hits):
                hits = {k: v for k, v in hits.items() if not set(k) <= set(key)}
                hits[key] = (f.kind, span)
    if "eposta" in rules.kinds:
        for key, span in _ocr_email_hits(words):
            if not any(set(key) & set(k) for k in hits):
                hits[key] = ("eposta", span)
    out = []
    for kind, span in hits.values():
        by_line: dict = {}
        for i, js in span.items():
            w = words[i]
            n = max(1, len(w.text))
            a, b = min(js), max(js) + 1
            wd = w.x1 - w.x0
            pad = wd / n * 0.6
            x0 = w.x0 + wd * a / n - (pad if a else 0)
            x1 = w.x0 + wd * b / n + (pad if b < n else 0)
            bx = by_line.get(w.line)
            box = (max(w.x0, x0), w.y0, min(w.x1, x1), w.y1)
            by_line[w.line] = box if bx is None else (min(bx[0], box[0]), min(bx[1], box[1]),
                                                      max(bx[2], box[2]), max(bx[3], box[3]))
        out.append((kind, list(by_line.values())))
    return out


def find_pii(words: list[Word], rules: MaskRules):
    """→ (Counter tür, kutular)."""
    from collections import Counter
    hits = pii_hits(words, rules)
    return Counter(k for k, _ in hits), [b for _, bs in hits for b in bs]


def find_pii_typed(words: list[Word], rules: MaskRules):
    """→ (Counter tür, kutular, kutu başına tür) — kutular `find_pii` ile aynı sırada."""
    from collections import Counter
    hits = pii_hits(words, rules)
    return (Counter(k for k, _ in hits), [b for _, bs in hits for b in bs],
            [k for k, bs in hits for _ in bs])


def text_quality(words: list[Word]) -> tuple[int, float | None]:
    """(güvenilir kelime sayısı, harf ağırlıklı ortalama güven)."""
    good = 0
    tot = wsum = 0.0
    for w in words:
        if w.conf < 0:
            continue
        n = sum(c.isalnum() for c in w.text)
        if not n:
            continue
        tot += w.conf * n
        wsum += n
        if w.conf >= 60 and n >= 2:
            good += 1
    return good, (tot / wsum if wsum else None)


def ink_ratio(img) -> float:
    """Koyu piksel oranı (boş sayfa ayrımı için; küçültülmüş gri görüntüde)."""
    g = img.convert("L")
    g.thumbnail((400, 400))
    hist = g.histogram()
    dark = sum(hist[:140])
    return dark / max(1, g.width * g.height)
