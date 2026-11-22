"""El yazısıyla doldurulmuş sentetik form üretici (test verisi; gerçek kişi/kurum yok).

Basılı etiketler Pillow'un ölçeklenebilir varsayılan yazı tipiyle; değerler el yazısı benzeri rakamlar
(titrek çoklu çizgi, hafif eğik, mavi). Rakamlar keyfi dizilerdir (geçerli kimlik no değildir). Kelime
kutuları (OCR'sız testler için) çizim konumundan üretilir, güven 95."""
from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw, ImageFont

from bidr.mask import ocr as O

INK = (25, 45, 170)

# birim karede (0..1) rakam vuruşları; her rakam tek bağlı çoklu çizgi
_D = {
    "0": [(0.5 + 0.48 * math.cos(t / 12 * 2 * math.pi), 0.5 + 0.5 * math.sin(t / 12 * 2 * math.pi)) for t in range(13)],
    "1": [(0.25, 0.25), (0.6, 0.0), (0.6, 1.0)],
    "2": [(0.05, 0.25), (0.35, 0.0), (0.8, 0.05), (0.9, 0.3), (0.05, 1.0), (1.0, 1.0)],
    "3": [(0.05, 0.05), (0.95, 0.05), (0.4, 0.45), (0.95, 0.68), (0.6, 1.0), (0.05, 0.9)],
    "4": [(0.75, 1.0), (0.75, 0.0), (0.0, 0.65), (1.0, 0.65)],
    "5": [(0.95, 0.0), (0.15, 0.0), (0.05, 0.45), (0.7, 0.4), (1.0, 0.7), (0.6, 1.0), (0.0, 0.9)],
    "6": [(0.9, 0.0), (0.25, 0.35), (0.0, 0.75), (0.4, 1.0), (0.9, 0.8), (0.6, 0.5), (0.05, 0.65)],
    "7": [(0.0, 0.0), (1.0, 0.0), (0.35, 1.0)],
    "8": [(0.5, 0.5), (0.05, 0.25), (0.5, 0.0), (0.95, 0.25), (0.5, 0.5), (0.0, 0.78), (0.5, 1.0), (1.0, 0.78),
          (0.5, 0.5)],
    "9": [(1.0, 0.35), (0.5, 0.6), (0.0, 0.3), (0.5, 0.0), (1.0, 0.3), (0.85, 1.0)],
}


def font(size: int):
    return ImageFont.load_default(size=size)


def digits(d: ImageDraw.ImageDraw, s: str, x: float, y: float, h: float = 34, seed: int = 0, gap: float = 0.28,
           pitch: float | None = None, color=INK, width: int = 3):
    """El yazısı benzeri rakam dizisi; `pitch` verilirse her rakam sabit aralıkla (kutucuk içi). → kutu."""
    rnd = random.Random(seed)
    w = 0.58 * h
    cx = x
    x0, y0, x1, y1 = x, y, x, y + h
    for i, ch in enumerate(s):
        if ch == " ":
            cx += 0.6 * w
            continue
        hh = h * rnd.uniform(0.9, 1.08)
        slant = rnd.uniform(0.05, 0.18)
        oy = y + rnd.uniform(-0.06, 0.06) * h
        pts = []
        for px, py in _D[ch]:
            jx, jy = rnd.uniform(-0.04, 0.04), rnd.uniform(-0.04, 0.04)
            pts.append((cx + (px + jx) * w + (1 - py) * slant * w, oy + (py + jy) * hh))
        d.line(pts, fill=color, width=width, joint="curve")
        x0, x1 = min(x0, min(p[0] for p in pts)), max(x1, max(p[0] for p in pts))
        y0, y1 = min(y0, min(p[1] for p in pts)), max(y1, max(p[1] for p in pts))
        cx = (x + (i + 1) * pitch) if pitch else cx + w * (1 + gap) * rnd.uniform(0.92, 1.1)
    return (x0 - 2, y0 - 2, x1 + 2, y1 + 2)


def scribble(d, x, y, w, h=34, seed=0, color=INK):
    """Okunamayan el yazısı (ad gibi): dalgalı tek çizgi."""
    pts = []
    n = max(2, int(w / 3))
    for i in range(n):
        t = i / (n - 1)
        pts.append((x + t * w, y + h / 2 + h / 2.4 * math.sin(t * w / 9 + seed) * math.cos(t * 7 + seed)))
    d.line(pts, fill=color, width=3, joint="curve")
    return (x, y, x + w, y + h)


class Form:
    """Sayfa + kurgu OCR kelimeleri + beklenen değer kutuları + açık kalması gereken kutular."""

    def __init__(self, W=1240, H=1754, size=30):
        self.img = Image.new("RGB", (W, H), "white")
        self.d = ImageDraw.Draw(self.img)
        self.f = font(size)
        self.words: list[O.Word] = []
        self.vals: dict[str, tuple] = {}      # kapatılmalı
        self.keep: list[tuple] = []           # açık kalmalı (basılı metin, ad değeri)
        self.line = 0

    def text(self, x, y, s, keep=True, conf=95.0):
        """Basılı satır: kelime kelime çizilir, her kelime kurgu OCR kelimesi olur."""
        self.line += 1
        cx = x
        for t in s.split(" "):
            bb = self.d.textbbox((cx, y), t, font=self.f)
            self.d.text((cx, y), t, fill="black", font=self.f)
            self.words.append(O.Word(t, conf, bb[0], bb[1], bb[2], bb[3], (1, 1, self.line, 1)))
            if keep:
                self.keep.append(bb)
            cx = bb[2] + self.d.textlength(" ", font=self.f)
        return self.d.textbbox((x, y), s, font=self.f)

    def dots(self, x0, x1, y):
        """Noktalı kılavuz (basılı nokta dizisi)."""
        x = x0
        while x < x1:
            self.d.ellipse([x, y - 1.5, x + 3, y + 1.5], fill="black")
            x += 8

    def hline(self, x0, x1, y, w=2):
        self.d.line([(x0, y), (x1, y)], fill="black", width=w)

    def vline(self, x, y0, y1, w=2):
        self.d.line([(x, y0), (x, y1)], fill="black", width=w)

    def comb(self, x0, y_base, n, pitch=40, tick=34):
        """n kutuluk tarak (taban + n+1 dikey)."""
        self.hline(x0, x0 + n * pitch, y_base)
        for i in range(n + 1):
            self.vline(x0 + i * pitch, y_base - tick, y_base)
        return (x0, y_base - tick, x0 + n * pitch, y_base)


def rotate(form: Form, deg: float) -> Form:
    """Eğik tarama: sayfa ve kelime/değer kutuları `deg` derece döndürülür (merkez etrafında)."""
    W, H = form.img.size
    img = form.img.rotate(deg, resample=Image.BICUBIC, fillcolor="white")
    a = math.radians(-deg)            # PIL: pozitif açı saat yönünün tersi (ekranda)
    cx, cy = W / 2, H / 2

    def tr(b):
        pts = [(b[0], b[1]), (b[2], b[1]), (b[0], b[3]), (b[2], b[3])]
        q = [((x - cx) * math.cos(a) - (y - cy) * math.sin(a) + cx, (x - cx) * math.sin(a) + (y - cy) * math.cos(a) + cy)
             for x, y in pts]
        return (min(p[0] for p in q), min(p[1] for p in q), max(p[0] for p in q), max(p[1] for p in q))

    out = Form(W, H)
    out.img = img
    out.d = ImageDraw.Draw(img)
    out.words = [O.Word(w.text, w.conf, *tr(w.box), w.line) for w in form.words]
    out.vals = {k: tr(v) for k, v in form.vals.items()}
    out.keep = [tr(k) for k in form.keep]
    return out


def covered(box, regions, frac=0.9) -> bool:
    x0, y0, x1, y1 = box
    area = max(1e-6, (x1 - x0) * (y1 - y0))
    best = 0.0
    for fb in regions:
        ix = max(0.0, min(x1, fb[2]) - max(x0, fb[0]))
        iy = max(0.0, min(y1, fb[3]) - max(y0, fb[1]))
        best = max(best, ix * iy / area)
    return best >= frac


def hits(box, regions, frac=0.15) -> bool:
    """Kutunun `frac`'ından fazlası bir bölgeyle örtüşüyor mu (yanlış kapatma)."""
    x0, y0, x1, y1 = box
    area = max(1e-6, (x1 - x0) * (y1 - y0))
    for fb in regions:
        ix = max(0.0, min(x1, fb[2]) - max(x0, fb[0]))
        iy = max(0.0, min(y1, fb[3]) - max(y0, fb[1]))
        if ix * iy / area > frac:
            return True
    return False


# ---------------------------------------------------------------- form düzenleri

def form_sag_nokta(seed=0) -> Form:
    """Etiket: ............ (değer sağdaki noktalı kılavuzun üstünde) + ad alanı (açık kalmalı)."""
    F = Form()
    F.text(420, 100, "DILEKCE")
    b = F.text(100, 260, "Adı Soyadı:")
    F.dots(b[2] + 10, 1100, b[3] + 4)
    F.keep.append(scribble(F.d, b[2] + 40, b[1] - 8, 300, seed=seed))
    b = F.text(100, 360, "T.C. Kimlik No:")
    F.dots(b[2] + 10, 1100, b[3] + 4)
    F.vals["tc_no"] = digits(F.d, "12345678950", b[2] + 30, b[1] - 10, seed=seed)
    b = F.text(100, 460, "Telefon:")
    F.dots(b[2] + 10, 1100, b[3] + 4)
    F.vals["telefon"] = digits(F.d, "05001112233", b[2] + 30, b[1] - 10, seed=seed + 1)
    F.text(100, 600, "Geregini arz ederim.")
    return F


def form_alt_cizgi(seed=0) -> Form:
    """Etiket satırı, değer alttaki alt çizginin üstünde (etiketin altında)."""
    F = Form()
    F.text(420, 100, "BASVURU FORMU")
    b = F.text(100, 260, "Ogrenci Numarasi:")
    F.hline(100, 700, b[3] + 70)
    F.vals["ogrenci_no"] = digits(F.d, "202100012345", 120, b[3] + 28, seed=seed)
    b = F.text(100, 460, "Bolumu:")
    F.hline(100, 700, b[3] + 70)
    F.keep.append(scribble(F.d, 120, b[3] + 28, 300, seed=seed + 3))
    F.text(100, 640, "Bilgilerin dogrulugunu beyan ederim.")
    return F


def form_tarak(seed=0) -> Form:
    """Kimlik no kutucuk dizisinde (11 kutu, her kutuda bir rakam)."""
    F = Form()
    F.text(420, 100, "BASVURU FORMU")
    b = F.text(100, 300, "T.C. Kimlik No")
    x0 = b[2] + 40
    cb = F.comb(x0, b[3] + 8, 11)
    F.vals["tc_no"] = digits(F.d, "10000000146", x0 + 10, cb[1] + 4, h=26, pitch=40, seed=seed)
    F.text(100, 500, "Imza:")
    return F


def form_tablo(seed=0) -> Form:
    """Tablo: etiket hücresi | değer hücresi; ad satırı açık kalmalı."""
    F = Form()
    F.text(420, 100, "OGRENCI BILGILERI")
    ys = [220, 300, 380, 460]
    for y in ys:
        F.hline(80, 1100, y)
    for x in (80, 460, 1100):
        F.vline(x, 220, 460)
    F.text(100, 240, "Adı Soyadı")
    F.keep.append(scribble(F.d, 500, 238, 300, seed=seed))
    F.text(100, 320, "Kimlik Numarası")
    F.vals["tc_no"] = digits(F.d, "11111111110", 500, 320, seed=seed)
    F.text(100, 400, "Doğum Tarihi")
    F.vals["dogum_tarihi"] = digits(F.d, "01012000", 500, 400, seed=seed + 2)
    return F


def form_ust(seed=0) -> Form:
    """Değer çizginin üstünde, etiket çizginin altında açıklama ("(T.C. Kimlik No)")."""
    F = Form()
    F.text(420, 100, "TAAHHUTNAME")
    F.hline(100, 600, 400)
    F.vals["tc_no"] = digits(F.d, "12121212120", 130, 360, seed=seed)
    F.text(200, 412, "(T.C. Kimlik No)")
    F.hline(700, 1100, 400)
    F.keep.append(scribble(F.d, 720, 360, 300, seed=seed + 1))
    F.text(820, 412, "(Ad Soyad)")
    return F


def form_bos(seed=0) -> Form:
    """Doldurulmamış form: noktalı kılavuz boş."""
    F = Form()
    F.text(420, 100, "BASVURU FORMU")
    b = F.text(100, 300, "T.C. Kimlik No:")
    F.dots(b[2] + 10, 1000, b[3] + 4)
    F.vals["tc_no"] = (b[2] + 20, b[1] - 6, 1000, b[3] + 4)       # boş alanın kendisi
    return F


def form_etiketsiz(seed=0) -> Form:
    """Etiketi okunamayan (ör. el yazısı) satırda 11 haneli dizi."""
    F = Form()
    F.text(420, 100, "DILEKCE")
    F.text(100, 220, "Bolum Baskanligina,")
    F.vals["tc_no"] = digits(F.d, "12345678950", 300, 500, seed=seed)
    F.text(100, 700, "Geregini arz ederim.")
    return F


FORMLAR = {"sag_nokta": form_sag_nokta, "alt_cizgi": form_alt_cizgi, "tarak": form_tarak, "tablo": form_tablo,
           "ust": form_ust, "bos": form_bos, "etiketsiz": form_etiketsiz}


def affine(form: Form, scale=1.0, deg=0.0, dx=0.0, dy=0.0) -> Form:
    """Yeniden tarama: ölçek + dönme + öteleme (p' = s·R·p + t; görüntü düzlemi)."""
    W, H = form.img.size
    th = math.radians(deg)
    c, s = math.cos(th), math.sin(th)
    coeffs = (c / scale, s / scale, -(c * dx + s * dy) / scale, -s / scale, c / scale, -(-s * dx + c * dy) / scale)
    img = form.img.transform((W, H), Image.AFFINE, coeffs, resample=Image.BICUBIC, fillcolor="white")

    def tr(b):
        pts = [(b[0], b[1]), (b[2], b[1]), (b[0], b[3]), (b[2], b[3])]
        q = [(scale * (c * x - s * y) + dx, scale * (s * x + c * y) + dy) for x, y in pts]
        return (min(p[0] for p in q), min(p[1] for p in q), max(p[0] for p in q), max(p[1] for p in q))

    out = Form(W, H)
    out.img = img
    out.d = ImageDraw.Draw(img)
    out.words = [O.Word(w.text, w.conf, *tr(w.box), w.line) for w in form.words]
    out.vals = {k: tr(v) for k, v in form.vals.items()}
    out.keep = [tr(k) for k in form.keep]
    return out


_DILEKCE = ["OGRENCI ISLERI DAIRE BASKANLIGINA", "Asagida bilgileri bulunan ogrenciyim.",
            "Ders kaydimin yenilenmesi hususunda", "gereginin yapilmasini saygilarimla arz ederim.",
            "Ekler: transkript belgesi"]


def form_sablon(seed=0, deger="digits", karisik=False) -> Form:
    """Şablon testi: basılı dilekçe iskeleti + etiketsiz değer alanı (900. satır). `karisik`: aynı metin
    satırları başka düzende (hizalama tutmamalı)."""
    F = Form()
    order = [4, 2, 0, 3, 1] if karisik else [0, 1, 2, 3, 4]
    xs = [460, 100, 140, 100, 700] if karisik else [300, 100, 100, 100, 100]
    for k, i in enumerate(order):
        F.text(xs[k], 120 + 140 * k, _DILEKCE[i])
    if deger == "digits":
        F.vals["tc_no"] = digits(F.d, "12345678950", 300, 900, seed=seed)
    else:
        F.vals["tc_no"] = scribble(F.d, 300, 900, 280, seed=seed)
    return F


def form_negatif(seed=0) -> Form:
    """Kişisel veri alanı olmayan sayfa: basılı paragraf, el yazısı not (bitişik), basılı belge sayısı.
    Hiçbir şey kapatılmamalı ya da onaya düşmemeli."""
    F = Form()
    F.text(420, 100, "TUTANAK")
    F.text(100, 220, "Sayı: 202312345678")
    F.text(100, 320, "Toplanti 14.00 saatinde baslamistir.")
    F.keep.append(scribble(F.d, 100, 420, 700, seed=seed))
    F.keep.append(scribble(F.d, 100, 500, 520, seed=seed + 4))
    F.text(100, 640, "Karar oy birligi ile alinmistir.")
    return F


FORMLAR["negatif"] = form_negatif
