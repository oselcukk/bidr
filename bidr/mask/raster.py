"""Görüntü katmanı: taranmış/tam sayfa görüntülü PDF sayfaları ve görsel dosyalar.

Tek görüntü için ortak adım (`analyze_image`): OCR kelimeleri → desen kutuları (`ocr.find_pii`)
+ imza çözümlemesi (`imza.analyze`) + OCR kalitesi. Maskeleme bu kutuları siyah dikdörtgenle
kapatır (PDF: PyMuPDF redaction, görüntü pikselleri de değişir; görsel: Pillow). Yeniden tarama
aynı adımı maskeli kopya üzerinde baştan çalıştırır.

"Taranamadı": metin katmanı olmayan bir sayfa/görsel OCR'dan geçemezse (tesseract yok, hata,
ya da mürekkepli sayfada güvenilir kelime çok az / güven çok düşük) dosya asla "tamam" sayılmaz.
"""
from __future__ import annotations

import io
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import imza as IM
from .detect import MaskRules
from .ocr import OcrFailed, Word, find_pii_typed, ink_ratio, ocr_available, ocr_words, text_quality

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}
SIG_DPI = 100                     # metin katmanlı sayfada imza çözümlemesi çözünürlüğü
MIN_GOOD_WORDS = 8                # mürekkepli sayfada OCR'ın "okudu" sayılması için
MIN_CONF = 50.0
INK_EMPTY = 0.004                 # bunun altı boş sayfa: OCR kalitesi aranmaz


@dataclass
class ImageScan:
    bulgular: Counter = field(default_factory=Counter)
    kutular: list = field(default_factory=list)          # PII kutuları (görüntü pikseli)
    turler: list = field(default_factory=list)           # kutu başına tür (yer tutucu etiketi için)
    imza: IM.Result | None = None
    taranamadi: str | None = None                        # neden (None: okundu)
    words: list = field(default_factory=list)


def _quality_reason(img, words: list[Word]) -> str | None:
    good, conf = text_quality(words)
    if ink_ratio(img) < INK_EMPTY:
        return None
    if good < MIN_GOOD_WORDS:
        return "OCR metin bulamadı (el yazısı/fotoğraf/düşük kalite olabilir)"
    if conf is not None and conf < MIN_CONF:
        return f"OCR güveni düşük ({conf:.0f})"
    return None


def _analyze_once(img, ppi, rules, ocr, extra_words, flag_unlabeled, need_text, all_zone) -> tuple[ImageScan, bool]:
    r = ImageScan()
    words: list[Word] = list(extra_words or [])
    ran = False
    if ocr:
        try:
            ow = ocr_words(img)
            ran = True
        except (OcrFailed, Exception) as e:   # araç yok / çöktü
            r.taranamadi = f"OCR çalışmadı: {str(e)[:120]}" if ocr_available() else "OCR yok (tesseract + tur dil verisi)"
            ow = []
        if ran:
            r.bulgular, r.kutular, r.turler = find_pii_typed(ow, rules)
            if need_text:
                r.taranamadi = _quality_reason(img, ow)
        words += ow
    r.words = words
    r.imza = IM.analyze(img, words, ppi, flag_unlabeled=flag_unlabeled, all_zone=all_zone)
    return r, ran


def _unrotate(box, how: str, W: int, H: int):
    """Döndürülmüş görüntüdeki kutu → özgün görüntü (W×H özgün boyut)."""
    x0, y0, x1, y1 = box
    if how == "180":
        return (W - x1, H - y1, W - x0, H - y0)
    if how == "90":                      # ROTATE_90 (saat yönü tersine): (x, y) → (y, W - x)
        return (W - y1, x0, W - y0, x1)
    return (y0, H - x1, y1, H - x0)      # ROTATE_270: (x, y) → (H - y, x)


def analyze_image(img, ppi: float, rules: MaskRules, *, ocr: bool = True, extra_words: list[Word] | None = None,
                  flag_unlabeled: bool = True, need_text: bool = True, all_zone: bool = False) -> ImageScan:
    """`ocr=False`: yalnız `extra_words` (PDF metin katmanı) ile imza çözümlemesi.
    `need_text`: OCR kalitesi düşükse `taranamadi` doldurulsun mu (metin katmanı yoksa evet).
    OCR kalitesi düşükse görüntü 180/90/270 derece döndürülüp yeniden denenir (ters taranmış sayfa);
    okunan yöndeki kutular özgün görüntüye geri çevrilir."""
    from PIL import Image
    r, ran = _analyze_once(img, ppi, rules, ocr, extra_words, flag_unlabeled, need_text, all_zone)
    if not (ran and need_text and r.taranamadi and not extra_words):
        return r
    for how, t in (("180", Image.Transpose.ROTATE_180), ("90", Image.Transpose.ROTATE_90),
                   ("270", Image.Transpose.ROTATE_270)):
        r2, _ = _analyze_once(img.transpose(t), ppi, rules, ocr, None, flag_unlabeled, need_text, all_zone)
        if r2.taranamadi is None:
            r2.kutular = [_unrotate(b, how, img.width, img.height) for b in r2.kutular]
            if r2.imza:
                r2.imza.kapat = [_unrotate(b, how, img.width, img.height) for b in r2.imza.kapat]
            r2.words = []
            return r2
    return r


def label_items(r: "ImageScan") -> list:
    """Bir taramanın kapatılacak kutuları için (kutu, yer tutucu) çiftleri."""
    from .detect import PLACEHOLDERS
    out = [(b, PLACEHOLDERS.get(k, f"[{k.upper()}]")) for b, k in zip(r.kutular, r.turler)]
    out += [(b, IM.IMZA_LABEL) for b in (r.imza.kapat if r.imza else [])]
    return out


def black_out(img, boxes, pad: float = 2.0):
    from PIL import ImageDraw
    out = img.convert("RGB") if img.mode not in ("RGB", "L") else img.copy()
    d = ImageDraw.Draw(out)
    for x0, y0, x1, y1 in boxes:
        d.rectangle([x0 - pad, y0 - pad, x1 + pad, y1 + pad], fill=0)
    return out


_FONT_FILES = ("DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
               "/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial.ttf",
               "C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf")
_FONT_PATH: list = []


def _font(size: int):
    """Türkçe harfli (İ) yazı tipi; bulunamazsa Pillow'un varsayılanı (yazı ASCII'ye çevrilir)."""
    from PIL import ImageFont
    if not _FONT_PATH:
        found = None
        for f in _FONT_FILES:
            try:
                ImageFont.truetype(f, 12)
                found = f
                break
            except OSError:
                continue
        _FONT_PATH.append(found)
    size = max(6, int(size))
    if _FONT_PATH[0]:
        return ImageFont.truetype(_FONT_PATH[0], size), True
    try:
        return ImageFont.load_default(size=size), False
    except TypeError:                    # eski Pillow: ölçeklenemeyen bit eşlem yazı tipi
        return ImageFont.load_default(), False


# Yazı rengi: siyah kutunun içinde koyu gri. Okunur, ama parlaklığı imza çözümlemesinin "dolu blok"
# eşiğinin (110) altında kaldığı için kutu yeniden taramada tek parça siyah blok sayılır (beyaz yazı
# kutuyu delik deşik eder, harf araları imza vuruşu gibi görünürdü).
LABEL_GRAY = 100


def draw_labels(img, items, pad: float = 2.0):
    """Kapatılan kutuların içine yer tutucu yazısı (`[İMZA]`, `[TC_NO]` …): okuyan (insan ya da
    model) orada neyin kapatıldığını bilsin. Kutu yazıya dar gelirse yazı küçülür; yine sığmazsa
    yazı kutudan taşmasın diye yazılmaz (kutu yine kapalıdır). `items`: [(kutu, yazı)]."""
    from PIL import ImageDraw
    if not items:
        return img
    out = img.convert("RGB") if img.mode not in ("RGB", "L") else img
    d = ImageDraw.Draw(out)
    ink = LABEL_GRAY if out.mode == "L" else (LABEL_GRAY,) * 3
    for (x0, y0, x1, y1), text in items:
        x0, y0, x1, y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad
        w, h = x1 - x0, y1 - y0
        size = int(min(h * 0.8, 48))
        while size >= 6:
            f, unicode_ok = _font(size)
            if not unicode_ok:
                text = text.replace("İ", "I")
            bb = d.textbbox((0, 0), text, font=f)
            if bb[2] - bb[0] <= w - 2 and bb[3] - bb[1] <= h - 1:
                d.text((x0 + (w - (bb[2] - bb[0])) / 2 - bb[0], y0 + (h - (bb[3] - bb[1])) / 2 - bb[1]),
                       text, font=f, fill=ink)
                break
            size = int(size * 0.85) if size > 7 else size - 1
    return out


# ---------------------------------------------------------------- görsel dosyalar

def open_image_bytes(data: bytes):
    return _open_image(io.BytesIO(data))


def _open_image(path):
    from PIL import Image, ImageOps
    im = Image.open(str(path) if isinstance(path, Path) else path)
    im.load()
    im = ImageOps.exif_transpose(im)
    if im.mode not in ("RGB", "L"):
        bg = Image.new("RGB", im.size, (255, 255, 255))
        im = im.convert("RGBA")
        bg.paste(im, mask=im.split()[3])
        im = bg
    return im


def _ppi(img) -> float:
    """Belge fotoğrafı/taraması için kaba ölçek: kısa kenar A4 genişliği (8,27 inç) sayılır."""
    return max(40.0, min(img.width, img.height) / 8.27)


def _ocr_view(img):
    """Küçük görselleri OCR için büyüt (tesseract ~300 ppi sever)."""
    from PIL import Image
    if min(img.width, img.height) < 1400:
        f = 2 if min(img.width, img.height) >= 700 else 3
        return img.resize((img.width * f, img.height * f), Image.LANCZOS), f
    return img, 1


def scan_image_obj(img, rules: MaskRules, *, flag_unlabeled: bool = True, all_zone: bool = False) -> ImageScan:
    """`all_zone`: görselin tamamı imza etiketinin yakını sayılır (belgede imza etiketi olan docx'in
    gömülü görseli: taranmış imza resmi)."""
    big, f = _ocr_view(img)
    r = analyze_image(big, _ppi(big), rules, flag_unlabeled=flag_unlabeled, all_zone=False,
                      need_text=not all_zone and flag_unlabeled)
    if f != 1:
        r.kutular = [(a / f, b / f, c / f, d / f) for a, b, c, d in r.kutular]
        if r.imza:
            r.imza.kapat = [(a / f, b / f, c / f, d / f) for a, b, c, d in r.imza.kapat]
    if all_zone:
        box = signature_image_box(img, [Word(w.text, w.conf, w.x0 / f, w.y0 / f, w.x1 / f, w.y1 / f, w.line)
                                        for w in r.words])
        if box is not None:
            r.imza = r.imza or IM.Result()
            r.imza.kapat.append(box)
            r.imza.etiketli += 1
    return r


def signature_image_box(img, words: list[Word]):
    """Belgede imza etiketi varken gömülü görselin kendisi imza resmi mi: tek renkli (logo/fotoğraf
    değil), neredeyse yazısız, beyaz zeminde seyrek mürekkep. Evetse mürekkebin kutusu."""
    from PIL import Image
    if multicolor(img):
        return None
    if sum(1 for w in words if IM._confident(w)) > 2:
        return None
    k = min(1.0, 800.0 / max(img.width, img.height))
    W, H = max(1, int(img.width * k)), max(1, int(img.height * k))
    ink, _ = IM._binary(img, [], W, H)
    hist = ink.histogram()
    frac = hist[255] / float(W * H)
    if not (0.002 <= frac <= 0.3):
        return None
    bb = ink.getbbox()
    if not bb:
        return None
    pad = 3 / k
    return (max(0, bb[0] / k - pad), max(0, bb[1] / k - pad), min(img.width, bb[2] / k + pad),
            min(img.height, bb[3] / k + pad))


def multicolor(img) -> bool:
    """Doygun piksellerde birden çok belirgin renk tonu var mı (logo/fotoğraf ↔ tek renkli mürekkep)."""
    im = img.convert("RGB")
    im.thumbnail((200, 200))
    hsv = im.convert("HSV")
    bins = [0] * 12
    n = 0
    for h, s_, v in hsv.getdata():
        if s_ >= 80 and 40 < v:
            bins[h * 12 // 256] += 1
            n += 1
    if n < 30:
        return False
    return sum(1 for b in bins if b >= 0.12 * n) >= 2


def save_like(img, dst, fmt_hint: str) -> None:
    """Üst verisiz kaydet (EXIF/konum/yorum yok). `dst`: yol ya da yazılabilir dosya nesnesi."""
    if isinstance(dst, Path):
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst = str(dst)
    e = fmt_hint.lower()
    if e in (".jpg", ".jpeg"):
        img.convert("RGB").save(dst, format="JPEG", quality=92)
    elif e in (".tif", ".tiff"):
        img.save(dst, format="TIFF", compression="tiff_deflate")
    elif e == ".bmp":
        img.save(dst, format="BMP")
    elif e == ".webp":
        img.save(dst, format="WEBP", quality=92)
    else:
        img.save(dst, format="PNG")


def mask_image(src: Path, dst: Path, rules: MaskRules) -> dict:
    img = _open_image(src)
    r = scan_image_obj(img, rules)
    found = r.bulgular
    bolge = len(r.imza.kapat) if r.imza else 0
    ortusen = r.imza.ortusen_kelime if r.imza else 0
    out = img
    labels = []
    for turn in range(3):                    # kapatma sonrası belirginleşen bulgu/vuruş için en çok iki tur daha
        boxes = list(r.kutular) + list(r.imza.kapat if r.imza else [])
        if not boxes:
            break
        labels += label_items(r)
        out = black_out(out, boxes)
        if turn == 2:
            break
        r = scan_image_obj(out, rules)
        bolge += len(r.imza.kapat) if r.imza else 0
        ortusen += r.imza.ortusen_kelime if r.imza else 0
    out = draw_labels(out, labels)
    save_like(out, dst, src.suffix)
    first = scan_image_obj(img, rules)       # önbellekli OCR: yalnız ilk tarama uyarısı
    uyarilar = [f"taranamadı: {first.taranamadi}"] if first.taranamadi else []
    return {"maskelenen": found, "temizlenen": ["ust_veri"], "uyarilar": uyarilar,
            "imza_bolgesi": bolge, "ortusen_kelime": ortusen}


def scan_image(path: Path, rules: MaskRules) -> dict:
    img = _open_image(path)
    r = scan_image_obj(img, rules)
    imza, sor = [], []
    if r.imza and (r.imza.etiketli or r.imza.etiketsiz):
        imza.append("görsel")
    if r.imza and not r.imza.kesin:
        sor.append("imza: elle bakılmalı")
    return {"bulgular": r.bulgular, "sorunlar": sor, "imza": imza,
            "taranamadi": [f"görsel: {r.taranamadi}"] if r.taranamadi else [],
            "imza_aday": r.imza.etiketli if r.imza else 0}


# ---------------------------------------------------------------- PDF sayfaları (PyMuPDF)

_PLACEHOLDER_RE = re.compile(r"\[(?:İMZA|IMZA|MASKELI|[A-Z_]{2,12})\]")


def page_needs_ocr(page) -> tuple[bool, bool]:
    """→ (OCR gerekir mi, metin katmanı var mı). Metin yoksa ya da sayfanın ≥%40'ı tek görüntüyse."""
    text = _PLACEHOLDER_RE.sub("", page.get_text("text")).strip()   # maskeleyicinin yazdığı etiketler sayılmaz
    has_text = len(text) >= 20
    big = 0.0
    try:
        area = page.rect.get_area() or 1.0
        for info in page.get_image_info():
            import pymupdf
            r = pymupdf.Rect(info["bbox"]) & page.rect
            big = max(big, r.get_area() / area)
    except Exception:
        pass
    return (not has_text) or big >= 0.4, has_text


def signature_image_regions(page, scale: float) -> list:
    """Metin katmanlı sayfada imza olabilecek gömülü görseller (görüntü pikseli): imza resmi küçüktür
    (≤ 4×2,5 inç) ve sayfa başlığında (logo) değildir. Vektör çizimler (tablo, akış şeması) ve
    büyük görseller (filigran, kapak) aranmaz."""
    import pymupdf
    out = []
    try:
        infos = page.get_image_info()
    except Exception:
        return out
    pr = page.rect
    rot = page.rotation_matrix
    for info in infos:
        r = pymupdf.Rect(info["bbox"]) & pr
        if r.is_empty or r.width > 4 * 72 or r.height > 2.5 * 72 or r.width < 0.3 * 72:
            continue
        if r.y1 <= pr.y0 + IM.TOP_IGNORE * pr.height:
            continue
        r = r * rot
        out.append((r.x0 * scale, r.y0 * scale, r.x1 * scale, r.y1 * scale))
    return out


def render(page, dpi: int):
    from PIL import Image
    pix = page.get_pixmap(dpi=dpi)
    return Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")


def text_words(page, scale: float) -> list[Word]:
    """PDF metin katmanı kelimeleri → görüntü pikseli (render ölçeğiyle); güven 100."""
    out = []
    rot = page.rotation_matrix
    for x0, y0, x1, y1, t, b, l, _ in page.get_text("words"):
        import pymupdf
        r = pymupdf.Rect(x0, y0, x1, y1) * rot
        out.append(Word(t, 100.0, r.x0 * scale, r.y0 * scale, r.x1 * scale, r.y1 * scale, (b, 0, l, 0)))
    return out


def has_label_words(words: list[Word]) -> bool:
    lines: dict = {}
    for w in words:
        lines.setdefault(w.line, []).append(w)
    for ws in lines.values():
        ws.sort(key=lambda w: w.x0)
        texts = [x.text for x in ws]
        for j, w in enumerate(ws):
            if IM.is_strict_label(w, len(ws), texts, IM._isolated(ws, j)) or IM.is_role_label(w, len(ws)):
                return True
    return False


def to_page_rects(page, boxes, scale: float):
    """Görüntü pikseli kutuları → sayfa (döndürülmemiş) koordinatı."""
    import pymupdf
    der = page.derotation_matrix
    return [(pymupdf.Rect(a / scale, b / scale, c / scale, d / scale) * der) for a, b, c, d in boxes]


def scan_pdf_page(page, rules: MaskRules) -> dict:
    """Tek sayfa: OCR gerekiyorsa OCR + PII + imza; metin katmanlı sayfada imza etiketi ve grafik
    varsa imza çözümlemesi. → {"bulgular","kutular_pt","imza","taranamadi","ortusen"}."""
    need_ocr, has_text = page_needs_ocr(page)
    out = {"bulgular": Counter(), "kutular": [], "turler": [], "imza": None, "taranamadi": None,
           "imza_kutular": []}
    if need_ocr:
        dpi = 300
        img = render(page, dpi)
        tw = text_words(page, dpi / 72.0) if has_text else []
        r = analyze_image(img, dpi, rules, extra_words=tw, need_text=not has_text)
        out["bulgular"] = r.bulgular
        out["kutular"] = to_page_rects(page, r.kutular, dpi / 72.0)
        out["turler"] = list(r.turler)
        out["taranamadi"] = r.taranamadi if not has_text else None
        out["imza"] = r.imza
        out["imza_kutular"] = to_page_rects(page, r.imza.kapat, dpi / 72.0) if r.imza else []
        return out
    regions = signature_image_regions(page, SIG_DPI / 72.0)
    if regions:
        tw = text_words(page, SIG_DPI / 72.0)
        if has_label_words(tw):
            img = render(page, SIG_DPI)
            res = IM.analyze(img, tw, SIG_DPI, flag_unlabeled=False, ink_regions=regions)
            out["imza"] = res
            out["imza_kutular"] = to_page_rects(page, res.kapat, SIG_DPI / 72.0)
    return out
