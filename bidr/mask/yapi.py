"""İmza: "imzayı tam bul" yerine "imzanın bulunabileceği alanı kapat" (yapısal kapatma; model yok).

Girdi: sayfa/görsel (PIL) + aynı görüntünün piksel koordinatında kelimeler (OCR ve/veya PDF metin
katmanı). Çıktı: `Bolge` listesi (kutu, karar, neden, kaynak, güven, geri basılan yazı). Kurallar:

1. **İmza sütunu** (`imza_sutunu`): tablo ızgarası yatay/dikey çizgilerden çıkarılır (taramada
   morfolojik koşu tespiti; metin katmanlı PDF'te ayrıca vektör çizimler). Başlık hücresi "İmza"/
   "İmzası" olan sütunun bütün veri hücreleri kapatılır; ad/unvan sütunları açık kalır. Başlık yalnız
   ilk sayfadaysa sütun düzeni belge bağlamında tutulur: hizası tutan devam sayfası tablosunda aynı
   sütun kapatılır. Hücre sınırını taşan mürekkep (sütundaki mürekkebe bitişik bileşenler) ayrı
   taşma bölgesiyle kapatılır.
2. **İmza bloğu** (`imza_blogu`): tablo dışındaki unvan/rol satırlarının (Üye, Başkan, Prof. Dr. …)
   üstündeki bant (önceki basılı satıra kadar, en çok ~0,9 inç) mürekkep içeriyorsa kapatılır;
   "İmza:" etiketinin sağı/altı (`imza_etiketi`) da öyle.
3. **Gömülü görüntü** (`gomulu_gorsel`, metin katmanlı sayfa): etiket yakınındaki ya da imza
   sütunundaki imza boyutlu gömülü görüntü kutusu doğrudan kapatılır. Belgede "e-imza / elektronik
   imza" ibaresi varsa metin katmanlı sayfada etiketsiz mürekkep/görüntü araması yapılmaz.
4. **Metinle örtüşen imza**: kapatılır. Altındaki ad/unvan PDF metin katmanından okunuyorsa kutunun
   üstüne geri basılır (`geri_basilan`); yalnız OCR'dan okunuyorsa bölge `onay_bekliyor`. Renkli
   (mavi/mor) mürekkep siyah metinden HSV ile ayrılabiliyorsa yalnız mürekkep pikselleri beyazlatılır
   (`yama`; alttaki metin kalır) ve bölge `kapatildi`.
5. **Yanlış alarm süzgeçleri** (yalnız etiketsiz adaylar; etiket yakınındaki aday süzülmez): sayfanın
   üst bandı (antet/logo), dairesel kaşe/mühür, aynı konumda başka sayfalarda (ya da dosyalarda)
   tekrarlayan öğe, tamamen basılı sayfada (not dökümü) eşiği geçemeyen tek aday → `birakildi`.
   Kalan etiketsiz aday kapatılır ve `onay_bekliyor` olur (kaçırmak fazladan kapatmaktan pahalı).

Koordinatlar: çözümleme `imza.A_PPI` (100 ppi) çözünürlüğünde yapılır; dönen kutular girdi
görüntüsünün pikselindedir (PDF puanına çevirme `raster`'ın işi). Değerler hiçbir yere yazılmaz.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass

from . import imza as IM
from .ocr import Word

I = IM.A_PPI

KAPATILDI, ONAY, BIRAKILDI = "kapatildi", "onay_bekliyor", "birakildi"
GERI_BASMA_EKI = "[imza gizlendi]"

ANTET_BANDI = 0.20          # sayfanın üst payı: etiketsiz aday antet/logo sayılır
BASILI_SAYFA_KELIME = 120   # bu kadar okunabilir kelimeli etiketsiz sayfa "tamamen basılı" (not dökümü)
MIN_SUTUN_MUREKKEP = 6      # imza sütunu gövdesinde kapatma için en az mürekkep pikseli (A_PPI)
MIN_BANT_MUREKKEP = 15
DEVAM_TOL = 0.12 * I        # devam sayfasında sütun sınırı hiza toleransı


@dataclass
class Bolge:
    kutu: tuple                  # girdi görüntüsü pikseli
    karar: str
    neden: str
    kaynak: str
    guven: float
    tur: str = "imza"
    geri_basilan: str | None = None
    yama: object = None          # PIL görüntüsü: kutunun mürekkebi ayrılmış hâli (siyah kutu yerine)

    @property
    def kapat(self) -> bool:
        return self.karar != BIRAKILDI and self.yama is None

    def kayit(self, kimlik: str, sayfa: int, kutu_pt) -> dict:
        return {"id": kimlik, "sayfa": sayfa, "kutu": [round(float(v), 1) for v in kutu_pt], "tur": self.tur,
                "karar": self.karar, "neden": self.neden, "kaynak": self.kaynak, "guven": round(self.guven, 2),
                "geri_basilan": self.geri_basilan}


def etiket_yazisi(b: Bolge) -> str:
    """Kapatılan kutuya yazılacak işaret: geri basılan ad/unvan ya da `[İMZA]`."""
    return f"{b.geri_basilan} {GERI_BASMA_EKI}" if b.geri_basilan else IM.IMZA_LABEL


# ---------------------------------------------------------------- belge bağlamı

_E_IMZA = re.compile(r"elektronik (?:olarak )?imza|e-?imza|e imza ile|guvenli elektronik|elektronik olarak imzalan")
_FOLD = str.maketrans({"ı": "i", "İ": "i", "I": "i", "ğ": "g", "Ğ": "g", "ü": "u", "Ü": "u", "ş": "s", "Ş": "s",
                       "ö": "o", "Ö": "o", "ç": "c", "Ç": "c"})


def e_imza_metni(text: str) -> bool:
    """"Bu belge güvenli elektronik imza ile imzalanmıştır", "e-imzalıdır" … ibaresi."""
    t = re.sub(r"\s+", " ", text.translate(_FOLD).lower()).replace("\u2010", "-").replace("\u2011", "-")
    return bool(_E_IMZA.search(t))


class TekrarBellegi:
    """Dosyalar arası tekrar (logo/antet): normalleştirilmiş konum + görüntü parmak izi. Çağıran (hat)
    aynı nesneyi dosyalar boyunca verirse, aynı konumda ikinci kez görülen etiketsiz aday süzülür."""

    def __init__(self):
        self.kayit: list = []

    def gor(self, kn, iz) -> bool:
        hit = any(_ayni_yer(kn, k) and _benzer(iz, z) for k, z in self.kayit)
        self.kayit.append((kn, iz))
        return hit


class Baglam:
    """Bir belgenin sayfaları boyunca tutulan bilgi: dosya özeti (bölge kimliği), e-imza ibaresi,
    imza sütunu düzeni (devam sayfaları) ve tekrar sınaması için değiştirilmemiş belge kopyası."""

    def __init__(self, doc=None, sha8: str = "00000000", e_imza: bool = False, bellek: TekrarBellegi | None = None):
        self.doc = doc
        self.sha8 = sha8
        self.e_imza = e_imza
        self.sutun = None               # (xs / W, sütun sırası)
        self.bellek = bellek
        self._cagri: Counter = Counter()
        self._iz_cache: dict = {}

    def kimlikler(self, sayfa: int, n: int) -> list[str]:
        """Kararlı bölge kimlikleri: aynı girdide aynı. Sayfanın ilk çözümlemesi 1'den, aynı sayfanın
        sonraki turları (maskeleme sonrası yeniden tarama) 100·tur'dan başlar."""
        tur = self._cagri[sayfa]
        self._cagri[sayfa] += 1
        base = 100 * tur
        return [f"{self.sha8}-s{sayfa}-{base + i + 1}" for i in range(n)]

    def sutun_kaydet(self, xs, c: int, W: int, sayfa: int = 0) -> None:
        if sayfa and self._cagri[sayfa]:
            return              # maskeleme sonrası yeniden tarama: karartılmış sayfanın düzeni kaydedilmez
        self.sutun = ([x / float(W) for x in xs], c)

    def sutun_eslesir(self, xs, W: int) -> int | None:
        if not self.sutun:
            return None
        ref, c = self.sutun
        if len(ref) != len(xs):
            return None
        if all(abs(x / float(W) - r) * W <= DEVAM_TOL for x, r in zip(xs, ref)):
            return c
        return None

    def tekrar_mi(self, sayfa: int, kn, iz=None) -> bool:
        """`kn` (normalleştirilmiş kutu) konumunda başka sayfalarda da aynı görünüm var mı."""
        hit = False
        if self.doc is not None and len(self.doc) > 1:
            ref = self._sayfa_izi(sayfa, kn)
            if ref is not None:
                n = len(self.doc)
                for j in sorted((j for j in range(1, n + 1) if j != sayfa), key=lambda j: abs(j - sayfa))[:6]:
                    z = self._sayfa_izi(j, kn)
                    if z is not None and _benzer(ref, z):
                        hit = True
                        break
                iz = iz or ref
        if self.bellek is not None and iz is not None:
            hit = self.bellek.gor(kn, iz) or hit
        return hit

    def _sayfa_izi(self, sayfa: int, kn):
        key = (sayfa, tuple(round(v, 3) for v in kn))
        if key in self._iz_cache:
            return self._iz_cache[key]
        iz = None
        try:
            import io

            import pymupdf
            from PIL import Image
            page = self.doc[sayfa - 1]
            rr = page.rect * page.rotation_matrix          # görüntülenen (döndürülmüş) sayfa
            r = pymupdf.Rect(rr.x0 + kn[0] * rr.width, rr.y0 + kn[1] * rr.height,
                             rr.x0 + kn[2] * rr.width, rr.y0 + kn[3] * rr.height) * page.derotation_matrix
            r = r & page.rect
            if not r.is_empty:
                pix = page.get_pixmap(dpi=100, clip=r, colorspace=pymupdf.csGRAY)
                g = Image.open(io.BytesIO(pix.tobytes("png"))).convert("L")
                g = g.rotate(-page.rotation, expand=True) if page.rotation else g
                iz = parmak_izi(g)
        except Exception:
            iz = None
        self._iz_cache[key] = iz
        return iz


def baglam(doc) -> Baglam:
    """PyMuPDF belgesine bağlı tek bağlam (sayfalar sırayla işlenir). Tekrar sınaması değiştirilmemiş
    bir kopyadan yapılır (maskeleme sırasında önceki sayfalar karartılmış olabilir)."""
    b = getattr(doc, "_bidr_yapi", None)
    if b is not None:
        return b
    sha8, kopya = "00000000", None
    name = getattr(doc, "name", None) or ""
    try:
        from pathlib import Path
        p = Path(name)
        if name and p.is_file():
            sha8 = hashlib.sha256(p.read_bytes()).hexdigest()[:8]
            import pymupdf
            kopya = pymupdf.open(str(p))
    except Exception:
        kopya = None
    src = kopya if kopya is not None else doc
    try:
        e = any(e_imza_metni(pg.get_text("text")) for pg in src)
    except Exception:
        e = False
    b = Baglam(doc=src, sha8=sha8, e_imza=e)
    try:
        doc._bidr_yapi = b
    except Exception:
        pass
    return b


# ---------------------------------------------------------------- parmak izi (tekrar sınaması)

def parmak_izi(gray):
    """Gri kırpıntının kaba görünümü (24×12 koyuluk, ortalaması çıkarılmış): küçük kaymalara dayanıklı."""
    from PIL import Image
    if gray.width < 4 or gray.height < 4:
        return None
    s = gray.convert("L").resize((24, 12), Image.BOX)
    v = [255 - p for p in s.tobytes()]
    if sum(v) < 24 * 12 * 6:                 # neredeyse boş
        return None
    m = sum(v) / len(v)
    d = [x - m for x in v]
    n = sum(x * x for x in d) ** 0.5
    return [x / n for x in d] if n else None


def _benzer(a, b) -> bool:
    return a is not None and b is not None and sum(x * y for x, y in zip(a, b)) >= 0.85


def _ayni_yer(a, b) -> bool:
    return all(abs(x - y) <= 0.02 for x, y in zip(a, b))


# ---------------------------------------------------------------- çizgiler ve tablolar

def _segmentler(bin_img, min_run: int, max_kalin: int) -> list:
    """Satır satır ≥ `min_run` mürekkep koşuları → ardışık satırlarda birleşen ince segmentler
    [(merkez, a0, a1)] (yatay için merkez y, uç x)."""
    W, H = bin_img.size
    src = bin_img.tobytes()
    pat = re.compile(rb"\xff{%d,}" % min_run)
    segs: list = []
    active: list = []
    for y in range(H):
        row = []
        for m in pat.finditer(src, y * W, (y + 1) * W):
            row.append((m.start() - y * W, m.end() - y * W))
        if not row and not active:
            continue
        nxt = []
        for x0, x1 in row:
            for s in active:
                if min(s[3], x1) - max(s[2], x0) >= 0.5 * min(s[3] - s[2], x1 - x0):
                    s[1] = y
                    s[2], s[3] = min(s[2], x0), max(s[3], x1)
                    break
            else:
                s = [y, y, x0, x1]
                segs.append(s)
            nxt.append(s)
        active = [s for s in active if s[1] >= y] + [s for s in nxt if s not in active]
    out = [((s[0] + s[1]) / 2.0, s[2], s[3]) for s in segs if s[1] - s[0] + 1 <= max_kalin]
    # hafif eğik taramada aynı çizgi parçalara bölünür: aynı hizadaki bitişik parçaları birleştir
    out.sort()
    merged: list = []
    for c, a0, a1 in out:
        for m in merged:
            if abs(m[0] - c) <= 6 and a0 <= m[2] + 10 and m[1] <= a1 + 10:
                m[0] = (m[0] + c) / 2
                m[1], m[2] = min(m[1], a0), max(m[2], a1)
                break
        else:
            merged.append([c, a0, a1])
    return [tuple(m) for m in merged]


def cizgiler(raw_ink) -> tuple[list, list]:
    """Taramada morfolojik çizgi tespiti (A_PPI ikili mürekkep): → (yatay [(y, x0, x1)], dikey [(x, y0, y1)])."""
    from PIL import Image, ImageFilter
    dil = raw_ink.filter(ImageFilter.MaxFilter(3))
    yat = _segmentler(dil, int(0.8 * I), 8)
    dik = _segmentler(dil.transpose(Image.Transpose.TRANSPOSE), int(0.25 * I), 8)
    return yat, dik


def cizgisiz(img, ppi: float):
    """Tablo ızgarası olan taramada OCR için çizgileri silinmiş kopya (yoksa None). tesseract ızgaralı
    sayfayı tek görüntü bloğu sayıp hücre yazılarını (başlıktaki "İmza" dahil) çoğu zaman atlıyor."""
    from PIL import ImageDraw
    k = I / float(ppi)
    W, H = max(1, int(img.width * k)), max(1, int(img.height * k))
    raw: list = []
    IM._binary(img, [], W, H, raw)
    yat, dik = cizgiler(raw[0])
    tabs = tablolar(yat, dik)
    if not tabs:
        return None
    out = img.convert("RGB").copy()
    d = ImageDraw.Draw(out)
    f = 1.0 / k
    for t in tabs:
        x0, y0, x1, y1 = t.kutu
        for y, a, b in yat:
            if y0 - 8 <= y <= y1 + 8 and a < x1 + 8 and b > x0 - 8:
                d.rectangle([a * f - 2, y * f - 5 * f / 2, b * f + 2, y * f + 5 * f / 2], fill="white")
        for x, a, b in dik:
            if x0 - 8 <= x <= x1 + 8 and a < y1 + 8 and b > y0 - 8:
                d.rectangle([x * f - 5 * f / 2, a * f - 2, x * f + 5 * f / 2, b * f + 2], fill="white")
    return out


def vektor_cizgileri(page, scale: float) -> tuple[list, list]:
    """Metin katmanlı PDF'te çizim nesnelerinden tablo çizgileri (görüntü pikseli, `scale` ölçeği)."""
    import pymupdf
    yat, dik = [], []
    try:
        drawings = page.get_drawings()
    except Exception:
        return yat, dik
    rot = page.rotation_matrix

    def add(p0, p1):
        p0, p1 = pymupdf.Point(p0) * rot, pymupdf.Point(p1) * rot
        x0, y0, x1, y1 = p0.x * scale, p0.y * scale, p1.x * scale, p1.y * scale
        if abs(y1 - y0) <= 1.5 and abs(x1 - x0) >= 0.8 * I:
            yat.append(((y0 + y1) / 2, min(x0, x1), max(x0, x1)))
        elif abs(x1 - x0) <= 1.5 and abs(y1 - y0) >= 0.25 * I:
            dik.append(((x0 + x1) / 2, min(y0, y1), max(y0, y1)))

    for d in drawings:
        for it in d.get("items") or []:
            if it[0] == "l":
                add(it[1], it[2])
            elif it[0] == "re":
                r = pymupdf.Rect(it[1])
                if r.height <= 2.5:
                    add((r.x0, (r.y0 + r.y1) / 2), (r.x1, (r.y0 + r.y1) / 2))
                elif r.width <= 2.5:
                    add(((r.x0 + r.x1) / 2, r.y0), ((r.x0 + r.x1) / 2, r.y1))
                else:
                    add(r.tl, r.tr)
                    add(r.bl, r.br)
                    add(r.tl, r.bl)
                    add(r.tr, r.br)
    return yat, dik


def _birlestir(vals, tol) -> list:
    out: list = []
    for v in sorted(vals):
        if out and v - out[-1][-1] <= tol:
            out[-1].append(v)
        else:
            out.append([v])
    return [sum(g) / len(g) for g in out]


@dataclass
class Tablo:
    xs: list
    ys: list

    @property
    def kutu(self):
        return (self.xs[0], self.ys[0], self.xs[-1], self.ys[-1])

    def hucre(self, x: float, y: float):
        """(sütun, satır) ya da None."""
        if not (self.xs[0] <= x < self.xs[-1] and self.ys[0] <= y < self.ys[-1]):
            return None
        c = max(i for i in range(len(self.xs) - 1) if self.xs[i] <= x)
        r = max(i for i in range(len(self.ys) - 1) if self.ys[i] <= y)
        return c, r


def tablolar(yat, dik, tol: float = 6) -> list[Tablo]:
    """Yatay çizgi grupları (x kapsamı örtüşen) + aralarında en az bir satır boyu uzanan dikey
    çizgiler → ızgara. En az 2 sütun ve 2 satır (başlık + veri)."""
    groups: list = []
    for y, x0, x1 in sorted(yat):
        for g in groups:
            ov = min(g[2], x1) - max(g[1], x0)
            if ov >= 0.6 * min(g[2] - g[1], x1 - x0) and y - g[0][-1] <= 3.5 * I:
                g[0].append(y)
                g[1], g[2] = min(g[1], x0), max(g[2], x1)
                break
        else:
            groups.append([[y], x0, x1])
    out = []
    for ys_raw, x0, x1 in groups:
        ys = _birlestir(ys_raw, tol)
        if len(ys) < 3:
            continue
        xs = []
        for xc, a, b in dik:
            if x0 - tol <= xc <= x1 + tol and any(a <= ys[i] + tol and b >= ys[i + 1] - tol
                                                  for i in range(len(ys) - 1)):
                xs.append(xc)
        xs = _birlestir(xs, tol)
        if len(xs) < 3:
            continue
        out.append(Tablo(xs, ys))
    return out


def _imza_basligi(w: Word) -> bool:
    if IM.is_placeholder(w.text):
        return False
    c = IM._core(w.text)
    return any(p in IM._STRICT or IM._STRICT_RE.match(p) for p in c.replace("/", " ").split())


def imza_sutunu(t: Tablo, words: list[Word]):
    """Başlık hücresinde (en çok 4 kelime) "İmza"/"İmzası" olan sütun → (sütun, başlık satırı)."""
    best = None
    for w in words:
        if not _imza_basligi(w):
            continue
        cell = t.hucre((w.x0 + w.x1) / 2, (w.y0 + w.y1) / 2)
        if cell is None:
            continue
        c, r = cell
        if r >= len(t.ys) - 2:
            continue                      # altında veri satırı yok
        x0, x1, y0, y1 = t.xs[c], t.xs[c + 1], t.ys[r], t.ys[r + 1]
        inside = [o for o in words if x0 <= (o.x0 + o.x1) / 2 < x1 and y0 <= (o.y0 + o.y1) / 2 < y1]
        if len(inside) > 4 or not IM._line_ok([o.text for o in inside]):
            continue
        if best is None or r < best[1]:
            best = (c, r)
    return best


# ---------------------------------------------------------------- yardımcılar

def _area(b) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _ic(a, b) -> float:
    """a'nın b içinde kalan payı."""
    return IM._overlap(a, b) / max(1.0, _area(a))


def _union(a, b):
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _clip(b, W, H):
    return (max(0.0, b[0]), max(0.0, b[1]), min(float(W), b[2]), min(float(H), b[3]))


def _ink_px(ink, b) -> int:
    x0, y0, x1, y1 = int(max(0, b[0])), int(max(0, b[1])), int(min(ink.width, b[2])), int(min(ink.height, b[3]))
    if x1 - x0 < 1 or y1 - y0 < 1:
        return 0
    return ink.crop((x0, y0, x1, y1)).histogram()[255]


def _ink_bbox(ink, b):
    x0, y0, x1, y1 = int(max(0, b[0])), int(max(0, b[1])), int(min(ink.width, b[2])), int(min(ink.height, b[3]))
    if x1 - x0 < 1 or y1 - y0 < 1:
        return None
    bb = ink.crop((x0, y0, x1, y1)).getbbox()
    return None if bb is None else (x0 + bb[0], y0 + bb[1], x0 + bb[2], y0 + bb[3])


def kase_mi(raw_ink, box) -> bool:
    """Dairesel kaşe/mühür: kareye yakın kutu, mürekkebin çoğu çember bandında, çember neredeyse
    kapalı, köşelerde mürekkep yok. Mühre değen imza kutuyu kareden çıkarır: süzülmez."""
    import math
    w, h = box[2] - box[0], box[3] - box[1]
    if not (0.45 * I <= w <= 2.5 * I and 0.78 <= w / max(1.0, h) <= 1.28):
        return False
    crop = raw_ink.crop(tuple(int(v) for v in box))
    cx, cy, R = crop.width / 2.0, crop.height / 2.0, (crop.width + crop.height) / 4.0
    tot = ring = outside = 0
    sectors = set()
    data = crop.tobytes()
    cw = crop.width
    for idx in range(len(data)):
        if data[idx] != 255:
            continue
        y, x = divmod(idx, cw)
        d = math.hypot(x + 0.5 - cx, y + 0.5 - cy)
        tot += 1
        if 0.78 * R <= d <= 1.08 * R:
            ring += 1
            sectors.add(int((math.atan2(y - cy, x - cx) + math.pi) / (2 * math.pi) * 16) % 16)
        elif d > 1.12 * R:
            outside += 1
    return tot >= 40 and ring >= 0.45 * tot and len(sectors) >= 13 and outside <= 0.05 * tot


def _renk_ayir(img, box_in, h: IM.Hazirlik, box_a, kelimeler: list[Word]):
    """Kutudaki imza mürekkebi renkli (mavi/mor) ve altındaki metin siyahsa HSV ile ayırır → yama
    (mürekkebi beyazlatılmış kırpıntı) ya da None. Doğrulama: yamada imza benzeri mürekkep ve renkli
    piksel kalmamalı (kalan koyu nötr mürekkep basılı metindir)."""
    if _ink_px(h.colored, box_a) < 20:
        return None
    crop = img.crop(tuple(int(v) for v in box_in)).convert("RGB")
    hh, ss, vv = crop.convert("HSV").split()
    hd, sd, vd = hh.tobytes(), ss.tobytes(), vv.tobytes()
    sat = [i for i in range(len(sd)) if sd[i] >= 60 and vd[i] >= 40]
    if len(sat) < 20 or sum(1 for i in sat if 130 <= hd[i] <= 220) < 0.85 * len(sat):
        return None
    lum = crop.convert("L").tobytes()
    cw = crop.width
    dark = neutral = 0
    for w in kelimeler:              # alttaki kelimelerin koyu pikselleri doygun değil (siyah basılı metin)
        x0, y0 = int(max(0, w.x0 - box_in[0])), int(max(0, w.y0 - box_in[1]))
        x1, y1 = int(min(crop.width, w.x1 - box_in[0])), int(min(crop.height, w.y1 - box_in[1]))
        for y in range(y0, y1):
            for x in range(x0, x1):
                i = y * cw + x
                if lum[i] < 110:
                    dark += 1
                    neutral += sd[i] < 70
    if kelimeler and (dark < 10 or neutral < 0.5 * dark):
        return None
    yama = murekkebi_ayir(img, box_in)
    k = h.k
    W2, H2 = max(1, int(yama.width * k)), max(1, int(yama.height * k))
    ink2, col2 = IM._binary(yama, [], W2, H2)
    if col2.histogram()[255] > 3:
        return None
    for c in IM._cluster([c for c in IM._components(ink2) if c[4] >= 8], int(0.08 * I)):
        if IM._signature_like(c, 0):
            return None
    return yama


def murekkebi_ayir(img, box):
    """Kutudaki mavi/mor mürekkep piksellerini (ve 2 piksel halesini) beyazlatır; koyu nötr (siyah
    basılı metin) pikseller kalır. → kutu boyutunda PIL görüntüsü."""
    from PIL import ImageChops, ImageFilter
    crop = img.crop(tuple(int(v) for v in box)).convert("RGB")
    hh, ss, vv = crop.convert("HSV").split()
    m = ImageChops.multiply(hh.point(lambda x: 255 if 125 <= x <= 225 else 0), ss.point(lambda x: 255 if x >= 30 else 0))
    m = m.filter(ImageFilter.MaxFilter(5))
    lum = crop.convert("L")
    neutral_dark = ImageChops.multiply(lum.point(lambda x: 255 if x < 120 else 0), ss.point(lambda x: 255 if x < 70 else 0))
    wipe = ImageChops.subtract(m, neutral_dark)
    out = crop.copy()
    out.paste((255, 255, 255), mask=wipe)
    return out


# ---------------------------------------------------------------- ana çözümleme

_ONCELIK = {"imza_sutunu": 0, "gomulu_gorsel": 1, "imza_blogu": 2, "imza_etiketi": 3, "imza_tasmasi": 4,
            "etiketsiz_aday": 5}


@dataclass
class _R:
    box: tuple                  # A_PPI
    kaynak: str
    neden: str
    guven: float
    karar: str = KAPATILDI


def _okunur(w: Word, kesin: bool, med) -> bool:
    n = sum(ch.isalnum() for ch in w.text)
    if IM.is_placeholder(w.text):
        return False
    if kesin:
        return n >= 1
    return IM.readable_word(w) or IM._texty(w, med) or (w.conf >= 80 and n >= 2)


def goruntu_bolgeleri(img, words: list[Word], ppi: float, *, kesin: list[Word] | None = None,
                      bag: Baglam | None = None, sayfa: int = 1, metin_sayfasi: bool = False,
                      gomulu: list | None = None, vektor: tuple | None = None, ocr_dogrula=None,
                      ocr_kelime=None) -> list[Bolge]:
    """Tek sayfa/görsel için imza bölgeleri (kutular girdi pikselinde).

    `words`: bütün kelimeler (OCR + metin katmanı); `kesin`: bunlardan metin katmanından gelenler
    (geri basılabilir). `metin_sayfasi`: metin katmanlı PDF sayfası (etiketsiz mürekkep yalnız
    gömülü görüntülerde aranır; e-imzalı belgede hiç aranmaz). `gomulu`: [(kutu, imza_gibi)] gömülü
    görüntü kutuları (girdi pikseli). `vektor`: (yatay, dikey) vektör çizgileri (girdi pikseli).
    `ocr_dogrula(kutu) → okunan kelime sayısı`: kapatılacak kutunun yeniden OCR'ı (gizli metin).
    `ocr_kelime(kutu) → kelimeler` (girdi pikseli): tablo başlık satırının hedefli OCR'ı (sayfa OCR'ı
    ızgaralı tabloda başlığı çoğu zaman yanlış okur)."""
    h = IM.hazirla(img, words, ppi)
    k, W, H, wa = h.k, h.W, h.H, h.wa
    kesin_set = set(kesin or [])
    kesin_idx = {i for i, w in enumerate(words) if w in kesin_set}
    labels = set(h.strict) | set(h.role)
    hs = sorted(w.h for w in wa if IM._confident(w))
    med = hs[len(hs) // 2] if hs else None
    conf_boxes = [w.box for w in wa if IM._confident(w)]

    # --- tablo ızgarası
    yat, dik = cizgiler(h.raw_ink)
    if vektor:
        yat += [(y * k, a * k, b * k) for y, a, b in vektor[0]]
        dik += [(x * k, a * k, b * k) for x, a, b in vektor[1]]
    tabs = tablolar(yat, dik)
    comps = [c for c in IM._components(h.ink) if c[4] >= 4]
    regs: list[_R] = []
    kayitlar: list[_R] = []

    def tasma(b, kaynak_neden):
        """`b` bölgesindeki mürekkebe bitişik, dışarı taşan bileşenler → taşma bölgeleri."""
        near = (b[0] - 5, b[1] - 5, b[2] + 5, b[3] + 5)
        lim = (b[0] - 2.5 * I, b[1] - 1.0 * I, b[2] + 2.5 * I, b[3] + 1.0 * I)
        out_c = [c for c in comps if _ic(c, (b[0] - 1, b[1] - 1, b[2] + 1, b[3] + 1)) < 0.999 and _ic(c, lim) > 0.99]
        if not _ink_px(h.ink, (b[0] + 2, b[1] + 2, b[2] - 2, b[3] - 2)):
            return
        seeds = [c for c in out_c if IM._inter(c, near)]
        kel = [list(w.box) + [0] for w in wa if IM._confident(w) or IM._texty(w, med)]
        groups = []
        used = set()
        for s in seeds:
            if id(s) in used:
                continue
            g = list(s[:4])
            n = s[4]
            used.add(id(s))
            changed = True
            while changed:
                changed = False
                for c in out_c:
                    if id(c) in used:
                        continue
                    if c[0] <= g[2] + 8 and g[0] <= c[2] + 8 and c[1] <= g[3] + 8 and g[1] <= c[3] + 8:
                        g = [min(g[0], c[0]), min(g[1], c[1]), max(g[2], c[2]), max(g[3], c[3])]
                        n += c[4]
                        used.add(id(c))
                        changed = True
                # imzanın altında kalan kelime kutusu (mürekkep çözümlemesinde silinmiş): taşma ona da uzanır
                for c in kel:
                    if id(c) not in used and c[0] <= g[2] + 4 and g[0] <= c[2] + 4 and c[1] < g[3] and g[1] < c[3] \
                            and _ic(c, lim) > 0.99 and _ic(c, b) < 0.5:
                        g = [min(g[0], c[0]), min(g[1], c[1]), max(g[2], c[2]), max(g[3], c[3])]
                        used.add(id(c))
                        changed = True
            if n >= 10 and _ic(tuple(g), b) < 0.9:
                groups.append(tuple(g))
        for g in groups:
            regs.append(_R((g[0] - 3, g[1] - 3, g[2] + 3, g[3] + 3), "imza_tasmasi", kaynak_neden, 0.8))

    sutun_kutulari = []
    for t in tabs:
        hit = imza_sutunu(t, wa)
        cont = bag.sutun_eslesir(t.xs, W) if bag is not None and not hit else None
        if not hit and cont is None and ocr_kelime is not None:
            for r in range(min(2, len(t.ys) - 2)):        # başlık satırı adayları: hedefli OCR
                try:
                    ek = ocr_kelime((t.xs[0] / k, t.ys[r] / k, t.xs[-1] / k, t.ys[r + 1] / k))
                except Exception:
                    ek = []
                ek = [Word(w.text, w.conf, w.x0 * k, w.y0 * k, w.x1 * k, w.y1 * k, w.line) for w in ek
                      if IM._confident(w)]
                hit = imza_sutunu(t, ek)
                if hit:
                    break
        body = None
        if hit:
            c, r = hit
            body = (t.xs[c], t.ys[r + 1], t.xs[c + 1], t.ys[-1])
            neden, guven = "İmza sütunu", 0.95
            if bag is not None:
                bag.sutun_kaydet(t.xs, c, W, sayfa)
        elif cont is not None:
            c = cont
            if c is not None:
                body = (t.xs[c], t.ys[0], t.xs[c + 1], t.ys[-1])
                neden, guven = "İmza sütunu (devam sayfası, hizası tutan tablo)", 0.85
        if body is None:
            continue
        sutun_kutulari.append(body)
        if _ink_px(h.ink, (body[0] + 2, body[1] + 2, body[2] - 2, body[3] - 2)) >= MIN_SUTUN_MUREKKEP:
            regs.append(_R((body[0] + 1, body[1] + 1, body[2] - 1, body[3] - 1), "imza_sutunu", neden, guven))
            tasma(body, "İmza sütunundan taşan mürekkep")
    tab_kutulari = [t.kutu for t in tabs]

    def tabloda(w) -> bool:
        cx, cy = (w.x0 + w.x1) / 2, (w.y0 + w.y1) / 2
        return any(a <= cx <= c and b <= cy <= d for a, b, c, d in tab_kutulari)

    # --- imza bloğu (tablo dışı unvan/rol satırları)
    lines: dict = {}
    for i, w in enumerate(wa):
        lines.setdefault(w.line, []).append(i)
    blok_satirlari = []
    for li in lines.values():
        lab = [i for i in li if i in labels and not tabloda(wa[i])]
        if not lab or len(li) > 7:
            continue
        bx = (min(wa[i].x0 for i in li), min(wa[i].y0 for i in li), max(wa[i].x1 for i in li), max(wa[i].y1 for i in li))
        blok_satirlari.append([bx, set(li)])
    blok_satirlari.sort(key=lambda b: b[0][1])
    bloklar: list = []
    for bx, ids in blok_satirlari:
        for b in bloklar:
            g = b[0]
            if bx[1] - g[3] <= 0.45 * I and bx[0] < g[2] + 0.3 * I and g[0] < bx[2] + 0.3 * I:
                b[0] = _union(g, bx)
                b[1] |= ids
                break
        else:
            bloklar.append([bx, set(ids)])
    # bloğun hemen üstündeki kısa satırlar (unvanın üstündeki ad satırı; iki sütunlu imza bloğunda
    # OCR iki adı tek satır okuyabilir) bloğa katılır: imza bandı adın üstünden başlar
    satir_kutulari = []
    for li in lines.values():
        okunan = sum(1 for i in li if i in kesin_idx or IM.readable_word(wa[i]) or i in labels)
        if len(li) <= 10 and okunan * 2 >= len(li):
            satir_kutulari.append(((min(wa[i].x0 for i in li), min(wa[i].y0 for i in li), max(wa[i].x1 for i in li),
                                    max(wa[i].y1 for i in li)), set(li)))
    for b in bloklar:
        changed = True
        while changed:
            changed = False
            for bx, ids in satir_kutulari:
                if ids <= b[1] or any(tabloda(wa[i]) for i in ids):
                    continue
                g = b[0]
                if bx[3] <= g[1] + 2 and g[1] - bx[3] <= 0.4 * I and bx[0] < g[2] and g[0] < bx[2]:
                    b[0] = _union(g, bx)
                    b[1] |= ids
                    changed = True
    zones = []
    for blk, blk_ids in bloklar:
        if (blk[1] + blk[3]) / 2 < 0.15 * H:
            continue                        # antet bandındaki unvan satırı (yazı başlığı) imza bloğu değil
        x0 = blk[0] - 0.4 * I
        x1 = max(blk[2], blk[0] + 2.2 * I) + 0.4 * I
        y1 = blk[1] - 1
        # bandın üst sınırı: önceki basılı satır (imza vuruşuna OCR'ın verdiği anlamsız kelimeler değil)
        above = [w.y1 for j, w in enumerate(wa) if j not in blk_ids and IM.readable_word(w) and med and w.h <= 1.5 * med
                 and w.y1 <= blk[1] + 1 and w.x0 < x1 and w.x1 > x0]
        y0 = max([blk[1] - 0.9 * I] + [a + 2 for a in above])
        zones.append((blk[0] - 1.0 * I, blk[1] - 0.9 * I, blk[2] + 3.0 * I, blk[3] + 0.9 * I))
        if y1 - y0 < 0.15 * I:
            continue
        band = _clip((x0, y0, x1, y1), W, H)
        if _ink_px(h.ink, band) >= MIN_BANT_MUREKKEP:
            regs.append(_R(band, "imza_blogu", "İmza bloğu: unvan/rol satırının üstündeki imza bandı", 0.85))
            tasma(band, "İmza bloğu bandından taşan mürekkep")

    # --- "İmza:" etiketinin sağı ve altı; sütun başlığı "İmza"nın altı (ızgarasız tablo)
    for i in h.strict:
        w = wa[i]
        if tabloda(w):
            continue
        lh = max(8.0, w.h)
        same = [o for o in conf_boxes if o[0] > w.x1 and o[1] < w.y1 and o[3] > w.y0]
        rx1 = min([o[0] - 2 for o in same] + [w.x1 + 2.5 * I, W])
        bx0, bx1 = w.x0 - 0.3 * I, w.x0 + 2.5 * I
        below_words = [o for o in conf_boxes if o[1] >= w.y1 and o[0] < bx1 and o[2] > bx0]
        by1 = min([o[1] - 2 for o in below_words] + [w.y1 + 0.8 * I, H])
        for r in ((w.x1 + 2, w.y0 - 0.6 * lh, rx1, w.y1 + 0.6 * lh), (bx0, w.y1 + 2, bx1, by1)):
            r = _clip(r, W, H)
            if r[2] - r[0] < 4 or r[3] - r[1] < 4:
                continue
            if _ink_px(h.ink, r) >= 15:
                bb = _ink_bbox(h.ink, r)
                regs.append(_R((bb[0] - 3, bb[1] - 3, bb[2] + 3, bb[3] + 3), "imza_etiketi", "İmza etiketinin alanı", 0.9))
                tasma(r, "İmza etiketi alanından taşan mürekkep")
        zones.append((w.x0 - 0.3 * I, w.y0 - 0.4 * I, w.x1 + 3.0 * I, w.y1 + 1.2 * I))
        stop = [o[1] for o in conf_boxes if o[1] > w.y1 + 2 and o[0] < w.x1 + 0.2 * I and o[2] > w.x0 - 0.2 * I]
        zones.append((w.x0 - 0.6 * I, w.y1, w.x1 + 0.6 * I, min([w.y1 + 5 * I, H] + stop)))
    for i in h.role:
        w = wa[i]
        if not tabloda(w):
            zones.append((w.x0 - 1.0 * I, w.y0 - 0.9 * I, w.x1 + 3.0 * I, w.y1 + 0.9 * I))

    label_boxes = [wa[i].box for i in labels]

    def etiket_yakin(b) -> bool:
        return any(IM._inter(b, z) for z in zones) or any(IM._inter(b, s) for s in sutun_kutulari)

    # --- gömülü görüntüler (metin katmanlı sayfa)
    etiketsiz: list = []                 # (kutu, kaynak, ölçüt)
    for gb_in, imza_gibi in gomulu or []:
        gb = (gb_in[0] * k, gb_in[1] * k, gb_in[2] * k, gb_in[3] * k)
        near = (gb[0] - 1.5 * I, gb[1] - 1.0 * I, gb[2] + 1.5 * I, gb[3] + 1.0 * I)
        if any(IM._inter(gb, s) for s in sutun_kutulari) or any(IM._inter(near, lb) for lb in label_boxes) \
                or any(_ic(gb, z) > 0.3 for z in zones):
            regs.append(_R(gb, "gomulu_gorsel", "İmza etiketi yakınında gömülü görüntü", 0.9))
        elif imza_gibi and (gb[1] + gb[3]) / 2 > 0.5 * H:
            etiketsiz.append((gb, "gomulu_gorsel", None))

    # --- mürekkep adayları (etiketli: kapat; etiketsiz: süzgeçler)
    if not metin_sayfasi:
        from PIL import ImageChops
        clusters = IM._cluster([c for c in comps if c[4] >= 8], int(0.08 * I))
        col_data = ImageChops.multiply(h.colored, h.colored)
        for c in clusters:
            cpx = col_data.crop((c[0], c[1], c[2], c[3])).histogram()[255]
            if not IM._signature_like(c, cpx):
                continue
            if h.thick.crop((c[0], c[1], c[2], c[3])).histogram()[255] > 0.3 * c[4]:
                continue
            box = (c[0], c[1], c[2], c[3])
            if any(_ic(box, r.box) >= 0.7 for r in regs):
                continue
            ana = next((r for r in regs if IM._inter(box, r.box)), None)
            if ana is not None or etiket_yakin(box):
                nearz = (box[0] - 0.25 * I, box[1] - 0.25 * I, box[2] + 0.25 * I, box[3] + 0.25 * I)
                x0, y0, x1, y1 = box
                for o in comps:
                    if IM._inter(o, nearz):
                        x0, y0, x1, y1 = min(x0, o[0]), min(y0, o[1]), max(x1, o[2]), max(y1, o[3])
                for w in wa:                 # imzanın üstüne taştığı (silinmiş) kelime kutuları
                    if (IM._confident(w) or IM._texty(w, med)) and IM._overlap(w.box, (x0, y0, x1, y1)) > 0.15 * _area(w.box):
                        x0, y0, x1, y1 = min(x0, w.x0), min(y0, w.y0), max(x1, w.x1), max(y1, w.y1)
                if ana is not None:
                    regs.append(_R((x0 - 5, y0 - 5, x1 + 5, y1 + 5), "imza_tasmasi",
                                   f"{ana.neden.split(':')[0]} alanından taşan mürekkep", 0.8))
                else:
                    regs.append(_R((x0 - 5, y0 - 5, x1 + 5, y1 + 5), "imza_etiketi", "İmza etiketi/unvan yakınında imza", 0.85))
            else:
                etiketsiz.append((box, "etiketsiz_aday", (c, cpx)))

    # --- süzgeçler
    okunur_n = sum(1 for j, w in enumerate(wa) if j not in labels and IM.readable_word(w))
    basili = okunur_n >= BASILI_SAYFA_KELIME and not labels and len(etiketsiz) == 1
    for box, kaynak, olcu in etiketsiz:
        cy = (box[1] + box[3]) / 2
        kn = (box[0] / W, box[1] / H, box[2] / W, box[3] / H)
        if metin_sayfasi and bag is not None and bag.e_imza:
            kayitlar.append(_R(box, kaynak, "e-imzalı belge: metin katmanlı sayfada mürekkep araması yapılmaz", 0.7, BIRAKILDI))
            continue
        if cy < ANTET_BANDI * H:
            kayitlar.append(_R(box, kaynak, "sayfanın üst bandı (antet/logo)", 0.7, BIRAKILDI))
            continue
        if olcu is not None and kase_mi(h.raw_ink, box):
            kayitlar.append(_R(box, kaynak, "dairesel kaşe/mühür", 0.7, BIRAKILDI))
            continue
        iz = None
        if bag is not None:
            if bag.doc is None:
                g = img.crop((int(box[0] / k), int(box[1] / k), int(box[2] / k) + 1, int(box[3] / k) + 1)).convert("L")
                iz = parmak_izi(g)
            if bag.tekrar_mi(sayfa, kn, iz):
                kayitlar.append(_R(box, kaynak, "aynı konumda tekrarlayan öğe (logo/antet)", 0.75, BIRAKILDI))
                continue
        if basili and olcu is not None:
            c, cpx = olcu
            w_, h_ = c[2] - c[0], c[3] - c[1]
            guclu = cpx >= 0.6 * c[4] or (w_ >= 1.2 * I and h_ >= 0.4 * I)
            if not guclu:
                kayitlar.append(_R(box, kaynak, "tamamen basılı sayfada etiketsiz tek aday (eşik altı)", 0.6, BIRAKILDI))
                continue
        pad = 5 if kaynak == "etiketsiz_aday" else 0
        regs.append(_R((box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad), kaynak,
                       "etiketsiz imza benzeri iz" if kaynak == "etiketsiz_aday" else "etiketsiz gömülü görüntü (imza olabilir)",
                       0.5, ONAY))

    # --- birleştir: başka bölgenin içinde kalan bölge düşer
    regs = [_R(_clip(r.box, W, H), r.kaynak, r.neden, r.guven, r.karar) for r in regs]
    regs.sort(key=lambda r: (_ONCELIK.get(r.kaynak, 9), -_area(r.box)))
    kept: list[_R] = []
    for r in regs:
        if _area(r.box) < 4:
            continue
        if any(_ic(r.box, o.box) >= 0.9 for o in kept):
            continue
        kept.append(r)

    # --- metinle örtüşme: geri basma / renk ayırma / onay
    out: list[Bolge] = []
    for r in kept:
        b_in = (r.box[0] / k, r.box[1] / k, r.box[2] / k, r.box[3] / k)
        cov = [j for j, w in enumerate(wa) if _okunur(w, j in kesin_idx, med) and not IM.is_strict_label(w, 1)
               and IM._overlap(w.box, r.box) / max(1.0, (w.x1 - w.x0) * (w.y1 - w.y0)) >= 0.4]
        bol = Bolge(b_in, r.karar, r.neden, r.kaynak, r.guven)
        if cov:
            cov_in = [words[j] for j in cov]
            yama = _renk_ayir(img, b_in, h, r.box, cov_in)
            if yama is not None:
                bol.yama = yama
                bol.neden += "; renkli mürekkep ayrıldı, alttaki metin korundu"
            elif all(j in kesin_idx for j in cov):
                bol.geri_basilan = _metin(cov_in)
                bol.neden += "; metinle örtüşen imza, ad/unvan metin katmanından geri basıldı"
            else:
                bol.karar = ONAY
                bol.neden += "; metinle örtüşen imza, ad/unvan OCR'dan (geri basılmadı)"
        elif ocr_dogrula is not None and r.kaynak != "imza_sutunu" and bol.karar == KAPATILDI:
            try:
                n = ocr_dogrula(b_in)
            except Exception:
                n = 0
            if n >= 2:
                bol.karar = ONAY
                bol.neden += f"; kutuda yeniden OCR'da {n} okunabilir kelime"
        out.append(bol)
    for r in kayitlar:
        out.append(Bolge((r.box[0] / k, r.box[1] / k, r.box[2] / k, r.box[3] / k), r.karar, r.neden, r.kaynak, r.guven))
    return out


def _metin(ws: list[Word]) -> str:
    """Kelimeler satır sırasıyla; satırlar " – " ile: "Ad Soyad – Unvan"."""
    rows: list = []
    for w in sorted(ws, key=lambda w: ((w.y0 + w.y1) / 2, w.x0)):
        cy = (w.y0 + w.y1) / 2
        if rows and abs(rows[-1][0] - cy) <= 0.5 * max(4.0, w.h):
            rows[-1][1].append(w)
        else:
            rows.append([cy, [w]])
    return " – ".join(" ".join(x.text for x in sorted(r[1], key=lambda w: w.x0)) for r in rows)


def sonuc(bolgeler: list[Bolge]) -> IM.Result:
    """Eski arabirim (`imza.Result`): kapatılacak kutular (onay bekleyenler dahil; renk ayrılanlar
    hariç — onlar yama olarak basılır). Kapatılan bölgeler `etiketli` sayılır; etiketsiz/metin
    örtüşmesi kararı artık bölge kararındadır (`onay_bekliyor`)."""
    r = IM.Result()
    for b in bolgeler:
        if b.karar == BIRAKILDI:
            continue
        if b.yama is None:
            r.kapat.append(b.kutu)
        r.etiketli += 1
    return r


def imza_bolgeleri(path, rules=None, *, bellek: TekrarBellegi | None = None) -> list[dict]:
    """Bir dosyanın imza bölgeleri (sözleşmedeki `bolgeler` biçimi; kutu PDF puanı / görselde piksel).
    PDF (PyMuPDF gerekir) ve görsel dosyalar; diğer biçimlerde boş liste. Maskeleme aynı kuralları
    `raster.scan_pdf_page` / `raster.mask_image` içinde uygular ve aynı kimlikleri üretir."""
    from pathlib import Path

    from . import raster
    from .detect import MaskRules
    rules = rules or MaskRules()
    p = Path(path)
    ext = p.suffix.lower()
    if ext == ".pdf":
        import pymupdf
        doc = pymupdf.open(str(p))
        try:
            bag = baglam(doc)
            bag.bellek = bellek
            out: list = []
            for page in doc:
                out += raster.scan_pdf_page(page, rules).get("bolgeler") or []
            return out
        finally:
            doc.close()
    if ext in raster.IMAGE_EXT:
        img = raster._open_image(p)
        bag = Baglam(sha8=hashlib.sha256(p.read_bytes()).hexdigest()[:8], bellek=bellek)
        r = raster.scan_image_obj(img, rules, bag=bag)
        return raster.bolge_kayitlari(r.bolgeler, bag, 1, lambda b: b)
    return []
