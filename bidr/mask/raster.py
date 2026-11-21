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
from . import yapi as Y
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
    alanlar: list = field(default_factory=list)          # kapatılan etiket alanlarının etiket türleri (alan.py)
    bolgeler: list = field(default_factory=list)         # imza bölgeleri (`yapi.Bolge`, görüntü pikseli)


def _quality_reason(img, words: list[Word]) -> str | None:
    good, conf = text_quality(words)
    if ink_ratio(img) < INK_EMPTY:
        return None
    if good < MIN_GOOD_WORDS:
        return "OCR metin bulamadı (el yazısı/fotoğraf/düşük kalite olabilir)"
    if conf is not None and conf < MIN_CONF:
        return f"OCR güveni düşük ({conf:.0f})"
    return None


def _analyze_once(img, ppi, rules, ocr, extra_words, flag_unlabeled, need_text, all_zone,
                  yapi: dict | None = None) -> tuple[ImageScan, bool]:
    r = ImageScan()
    words: list[Word] = list(extra_words or [])
    ran = False
    clean = None
    if ocr:
        try:
            # imza çözümlemesinde: tablo ızgarası varsa OCR çizgileri silinmiş kopyada (yapi.cizgisiz)
            clean = Y.cizgisiz(img, ppi) if yapi is not None else None
            ow = ocr_words(clean or img)
            ran = True
        except (OcrFailed, Exception) as e:   # araç yok / çöktü
            r.taranamadi = f"OCR çalışmadı: {str(e)[:120]}" if ocr_available() else "OCR yok (tesseract + tur dil verisi)"
            ow = []
        if ran:
            r.bulgular, r.kutular, r.turler = find_pii_typed(ow, rules)
            if rules.label_fields:
                add_label_fields(r, img, ow)
            if need_text:
                r.taranamadi = _quality_reason(img, ow)
        words += ow
    r.words = words
    if yapi is not None:                 # yapısal imza bölgeleri (yapi.py)
        dogrula = (lambda b: box_text_words(crop_for_ocr(img, ppi, b))) if ran and ocr_available() else None
        kelime = (lambda b: _crop_words(clean if clean is not None else img, b)) if ran and ocr_available() else None
        r.bolgeler = Y.goruntu_bolgeleri(img, words, ppi, kesin=list(extra_words or []), bag=yapi.get("bag"),
                                         sayfa=yapi.get("sayfa", 1), ocr_dogrula=dogrula, ocr_kelime=kelime)
        r.imza = Y.sonuc(r.bolgeler)
        return r, ran
    r.imza = IM.analyze(img, words, ppi, flag_unlabeled=flag_unlabeled, all_zone=all_zone)
    if ran:
        verify_covers(r.imza, lambda b: crop_for_ocr(img, ppi, b))
    return r, ran


def _crop_words(img, box) -> list[Word]:
    """Kutunun OCR'ı (tek blok, psm 6) → görüntü koordinatında kelimeler."""
    x0, y0 = int(max(0, box[0])), int(max(0, box[1]))
    x1, y1 = int(min(img.width, box[2])), int(min(img.height, box[3]))
    if x1 - x0 < 8 or y1 - y0 < 8:
        return []
    ws = ocr_words(img.crop((x0, y0, x1, y1)), psm="6")
    return [Word(w.text, w.conf, w.x0 + x0, w.y0 + y0, w.x1 + x0, w.y1 + y0, w.line) for w in ws]


def add_label_fields(r: "ImageScan", img, ow: list[Word]) -> None:
    """Kişisel veri etiketlerinin (el yazısıyla doldurulmuş) alanları: kutu, `etiket_alani` türü ve
    sayısı (alan/satır başına). Yalnız OCR kelimeleri (metin katmanı değil): bkz. `alan`."""
    from . import alan as AL
    try:
        fields = AL.find_fields(img, ow, more=lambda: ocr_words(img, psm="11"))
    except Exception:            # alan çözümlemesi tespiti düşürmesin
        return
    for f in fields:
        r.kutular.append(f.box)
        r.turler.append(AL.KIND)
        r.alanlar.append(f.kind)
    if fields:
        r.bulgular[AL.KIND] += len(fields)


VERIFY_PPI = 300                  # kapatma adayı yeniden OCR çözünürlüğü


def crop_for_ocr(img, ppi: float, box):
    """Görüntüden kutu kırpıntısı, OCR için ~300 ppi'ye büyütülmüş."""
    from PIL import Image
    x0, y0, x1, y1 = (int(max(0, box[0])), int(max(0, box[1])), int(min(img.width, box[2])),
                      int(min(img.height, box[3])))
    c = img.crop((x0, y0, max(x0 + 1, x1), max(y0 + 1, y1)))
    f = VERIFY_PPI / float(ppi)
    if f > 1.2:
        c = c.resize((max(1, int(c.width * f)), max(1, int(c.height * f))), Image.LANCZOS)
    return c


def box_text_words(crop) -> int:
    """Kırpıntıdaki okunabilir basılı kelime (imza/unvan etiketleri ve yer tutucular hariç)."""
    try:
        ws = ocr_words(crop, psm="6")
    except Exception:
        return 0
    n = 0
    for w in ws:
        if not IM.readable_word(w) or IM.is_placeholder(w.text):
            continue
        if IM.is_role_label(w) or IM.is_strict_label(w, 1):
            continue
        n += 1
    return n


def verify_covers(res, crop_fn, limit: int | None = None) -> None:
    """Kapatılacak her imza kutusunu karartmadan önce yeniden OCR'la: kutuda `MAX_ORTUSEN`'den çok
    okunabilir basılı kelime (gövde metni) varsa kutu kapatılmaz, bölge "elle bakılmalı" olur.
    Sayfa OCR'ı imza vuruşunun üstündeki metni düşük güvenle okuyup saymamış olabilir; kırpıntı
    OCR'ı bunu yakalar. OCR yoksa çağrılmaz. `res.dogrulama`: kutu başına sayılan kelime."""
    if res is None or not res.kapat or not ocr_available():
        return
    limit = IM.MAX_ORTUSEN if limit is None else limit
    keep = []
    for b in res.kapat:
        n = box_text_words(crop_fn(b))
        res.dogrulama.append(n)
        if n > limit:
            res.elle_bolge += 1
            res.etiketli -= 1
        else:
            keep.append(b)
    res.kapat = keep


def _unrotate(box, how: str, W: int, H: int):
    """Döndürülmüş görüntüdeki kutu → özgün görüntü (W×H özgün boyut)."""
    x0, y0, x1, y1 = box
    if how == "180":
        return (W - x1, H - y1, W - x0, H - y0)
    if how == "90":                      # ROTATE_90 (saat yönü tersine): (x, y) → (y, W - x)
        return (W - y1, x0, W - y0, x1)
    return (y0, H - x1, y1, H - x0)      # ROTATE_270: (x, y) → (H - y, x)


def analyze_image(img, ppi: float, rules: MaskRules, *, ocr: bool = True, extra_words: list[Word] | None = None,
                  flag_unlabeled: bool = True, need_text: bool = True, all_zone: bool = False,
                  yapi: dict | None = None) -> ImageScan:
    """`ocr=False`: yalnız `extra_words` (PDF metin katmanı) ile imza çözümlemesi.
    `need_text`: OCR kalitesi düşükse `taranamadi` doldurulsun mu (metin katmanı yoksa evet).
    OCR kalitesi düşükse görüntü 180/90/270 derece döndürülüp yeniden denenir (ters taranmış sayfa);
    okunan yöndeki kutular özgün görüntüye geri çevrilir. `yapi`: verilirse ({"bag", "sayfa"}) imza
    bölgeleri yapısal kurallarla (`yapi.goruntu_bolgeleri`) çıkarılır, `r.bolgeler`'e yazılır."""
    from PIL import Image
    r, ran = _analyze_once(img, ppi, rules, ocr, extra_words, flag_unlabeled, need_text, all_zone, yapi)
    if not (ran and need_text and r.taranamadi and not extra_words):
        return r
    for how, t in (("180", Image.Transpose.ROTATE_180), ("90", Image.Transpose.ROTATE_90),
                   ("270", Image.Transpose.ROTATE_270)):
        r2, _ = _analyze_once(img.transpose(t), ppi, rules, ocr, None, flag_unlabeled, need_text, all_zone, yapi)
        if r2.taranamadi is None:
            r2.kutular = [_unrotate(b, how, img.width, img.height) for b in r2.kutular]
            for b in r2.bolgeler:            # döndürülmüş yama yerine siyah kutu
                b.kutu = _unrotate(b.kutu, how, img.width, img.height)
                b.yama = None
            if r2.bolgeler:
                r2.imza = Y.sonuc(r2.bolgeler)
            if r2.imza:
                r2.imza.kapat = [_unrotate(b, how, img.width, img.height) for b in r2.imza.kapat]
            r2.words = []
            return r2
    return r


def label_items(r: "ImageScan") -> list:
    """Bir taramanın kapatılacak kutuları için (kutu, yer tutucu) çiftleri."""
    from .detect import PLACEHOLDERS
    out = [(b, PLACEHOLDERS.get(k, f"[{k.upper()}]")) for b, k in zip(r.kutular, r.turler)]
    if r.bolgeler:
        out += [(b.kutu, Y.etiket_yazisi(b)) for b in r.bolgeler if b.kapat]
    else:
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


def scan_image_obj(img, rules: MaskRules, *, flag_unlabeled: bool = True, all_zone: bool = False,
                   bag: "Y.Baglam | None" = None) -> ImageScan:
    """`all_zone`: görselin tamamı imza etiketinin yakını sayılır (belgede imza etiketi olan docx'in
    gömülü görseli: taranmış imza resmi). Görsel dosyada (`flag_unlabeled`, `all_zone` değil) imza
    bölgeleri yapısal kurallarla çıkarılır (`r.bolgeler`); `bag`: dosyalar arası tekrar belleği vb."""
    big, f = _ocr_view(img)
    yeni = flag_unlabeled and not all_zone
    r = analyze_image(big, _ppi(big), rules, flag_unlabeled=flag_unlabeled, all_zone=False,
                      need_text=not all_zone and flag_unlabeled,
                      yapi={"bag": bag or Y.Baglam(), "sayfa": 1} if yeni else None)
    if f != 1:
        r.kutular = [(a / f, b / f, c / f, d / f) for a, b, c, d in r.kutular]
        if r.imza:
            r.imza.kapat = [(a / f, b / f, c / f, d / f) for a, b, c, d in r.imza.kapat]
        for b in r.bolgeler:
            b.kutu = tuple(v / f for v in b.kutu)
            if b.yama is not None:
                from PIL import Image
                b.yama = b.yama.resize((max(1, int(b.kutu[2]) - int(b.kutu[0])), max(1, int(b.kutu[3]) - int(b.kutu[1]))),
                                       Image.LANCZOS)
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


def paste_patches(img, bolgeler):
    """Renk ayrılan imza bölgeleri: kutuya mürekkebi beyazlatılmış kırpıntı yapıştırılır."""
    yamali = [b for b in bolgeler if b.yama is not None and b.karar != Y.BIRAKILDI]
    if not yamali:
        return img
    out = img.convert("RGB") if img.mode not in ("RGB", "L") else img.copy()
    for b in yamali:
        out.paste(b.yama.convert(out.mode), (int(b.kutu[0]), int(b.kutu[1])))
    return out


def bolge_kayitlari(bolgeler, bag: "Y.Baglam", sayfa: int, to_pt) -> list[dict]:
    """`Bolge` listesi → sözleşmedeki `bolgeler` kayıtları (kararlı kimlikle). `to_pt`: kutu → PDF puanı."""
    ids = bag.kimlikler(sayfa, len(bolgeler))
    return [b.kayit(i, sayfa, to_pt(b.kutu)) for i, b in zip(ids, bolgeler)]


def mask_image(src: Path, dst: Path, rules: MaskRules) -> dict:
    import hashlib
    img = _open_image(src)
    bag = Y.Baglam(sha8=hashlib.sha256(Path(src).read_bytes()).hexdigest()[:8])
    r = scan_image_obj(img, rules, bag=bag)
    found = r.bulgular
    kapsam = page_coverage(r.bulgular, r.alanlar)
    bolge = len(r.imza.kapat) if r.imza else 0
    ortusen = r.imza.ortusen_kelime if r.imza else 0
    kayit = bolge_kayitlari(r.bolgeler, bag, 1, lambda b: b)
    out = img
    labels = []
    for turn in range(3):                    # kapatma sonrası belirginleşen bulgu/vuruş için en çok iki tur daha
        boxes = list(r.kutular) + list(r.imza.kapat if r.imza else [])
        yamali = any(b.yama is not None and b.karar != Y.BIRAKILDI for b in r.bolgeler)
        if not boxes and not yamali:
            break
        labels += label_items(r)
        out = paste_patches(out, r.bolgeler)
        out = black_out(out, boxes)
        if turn == 2:
            break
        r = scan_image_obj(out, rules, bag=bag)
        bolge += len(r.imza.kapat) if r.imza else 0
        ortusen += r.imza.ortusen_kelime if r.imza else 0
        kapsam.update(page_coverage(r.bulgular, r.alanlar))
        kayit += [k for k in bolge_kayitlari(r.bolgeler, bag, 1, lambda b: b) if k["karar"] != Y.BIRAKILDI]
    out = draw_labels(out, labels)
    save_like(out, dst, src.suffix)
    first = scan_image_obj(img, rules)       # önbellekli OCR: yalnız ilk tarama uyarısı
    uyarilar = [f"taranamadı: {first.taranamadi}"] if first.taranamadi else []
    return {"maskelenen": found, "temizlenen": ["ust_veri"], "uyarilar": uyarilar,
            "imza_bolgesi": bolge, "ortusen_kelime": ortusen, "sayfa_sayisi": 1, "sayfa_kapsam": {1: dict(kapsam)},
            "bolgeler": kayit}


def page_coverage(bulgular, alanlar) -> Counter:
    """Sayfada kapatılan kişisel veri: desen türleri + etiket alanlarının etiket türü (sayı)."""
    c = Counter({k: n for k, n in (bulgular or {}).items() if k != "etiket_alani" and n})
    c.update(alanlar or [])
    return c


def scan_image(path: Path, rules: MaskRules) -> dict:
    img = _open_image(path)
    r = scan_image_obj(img, rules)
    imza, sor = [], []
    if r.imza and (r.imza.etiketli or r.imza.etiketsiz):
        imza.append("görsel")
    if r.imza and r.imza.etiketsiz:
        sor.append("imza: elle bakılmalı")
    metin = []
    if r.imza and r.imza.elle_bolge:
        from .formats import IMZA_METIN_SORUN
        sor.append(IMZA_METIN_SORUN)
        metin.append("görsel")
    return {"bulgular": r.bulgular, "sorunlar": sor, "imza": imza, "imza_metin": metin,
            "taranamadi": [f"görsel: {r.taranamadi}"] if r.taranamadi else [],
            "imza_aday": r.imza.etiketli if r.imza else 0}


# ---------------------------------------------------------------- PDF sayfaları (PyMuPDF)

_PLACEHOLDER_RE = re.compile(r"\[(?:İMZA|IMZA|MASKELI|KİŞİSEL VERİ|KISISEL VERI|[A-Z_]{2,12})\]")


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


def _render_clip(page, box, scale: float):
    """Metin katmanlı sayfada kutunun (görüntü pikseli, `scale` ölçeği) 300 dpi görüntüsü."""
    from PIL import Image
    r = to_page_rects(page, [box], scale)[0] & page.rect
    pix = page.get_pixmap(dpi=VERIFY_PPI, clip=r)
    return Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")


def to_page_rects(page, boxes, scale: float):
    """Görüntü pikseli kutuları → sayfa (döndürülmemiş) koordinatı."""
    import pymupdf
    der = page.derotation_matrix
    return [(pymupdf.Rect(a / scale, b / scale, c / scale, d / scale) * der) for a, b, c, d in boxes]


def _imza_gibi(img, box) -> bool:
    """Gömülü görüntü imza resmi olabilir mi: tek renkli (logo/fotoğraf değil), seyrek mürekkep."""
    x0, y0, x1, y1 = (int(max(0, box[0])), int(max(0, box[1])), int(min(img.width, box[2])), int(min(img.height, box[3])))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return False
    c = img.crop((x0, y0, x1, y1))
    if multicolor(c):
        return False
    hist = c.convert("L").histogram()
    frac = sum(hist[:160]) / float(c.width * c.height)
    return 0.002 <= frac <= 0.35


def scan_pdf_page(page, rules: MaskRules) -> dict:
    """Tek sayfa: OCR gerekiyorsa OCR + PII + imza; metin katmanlı sayfada imza etiketi, imza sütunu
    (ya da önceki sayfadan sürüp giden sütun) ya da gömülü görüntü varsa imza çözümlemesi.
    İmza bölgeleri yapısal kurallarla (`yapi`) çıkarılır → `bolgeler` (sözleşme kayıtları),
    `imza_kutular` (siyah kutu), `imza_yazilar` (kutuya yazılacak işaret / geri basılan ad),
    `imza_yamalar` ((dikdörtgen, PNG): renkli mürekkebi beyazlatılmış kırpıntı)."""
    need_ocr, has_text = page_needs_ocr(page)
    bag = Y.baglam(page.parent)
    sayfa = page.number + 1
    out = {"bulgular": Counter(), "kutular": [], "turler": [], "imza": None, "taranamadi": None,
           "imza_kutular": [], "alanlar": [], "bolgeler": [], "imza_yazilar": [], "imza_yamalar": []}
    if need_ocr:
        dpi = 300
        img = render(page, dpi)
        tw = text_words(page, dpi / 72.0) if has_text else []
        r = analyze_image(img, dpi, rules, extra_words=tw, need_text=not has_text,
                          yapi={"bag": bag, "sayfa": sayfa})
        out["bulgular"] = r.bulgular
        out["kutular"] = to_page_rects(page, r.kutular, dpi / 72.0)
        out["turler"] = list(r.turler)
        out["alanlar"] = list(r.alanlar)
        out["taranamadi"] = r.taranamadi if not has_text else None
        _imza_out(out, page, r.bolgeler, bag, sayfa, dpi / 72.0)
        return out
    scale = SIG_DPI / 72.0
    regions = signature_image_regions(page, scale)
    tw = text_words(page, scale)
    if regions or has_label_words(tw) or bag.sutun or any(Y._imza_basligi(w) for w in tw):
        img = render(page, SIG_DPI)
        gomulu = [(b, _imza_gibi(img, b)) for b in regions]
        bol = Y.goruntu_bolgeleri(img, tw, SIG_DPI, kesin=tw, bag=bag, sayfa=sayfa, metin_sayfasi=True,
                                  gomulu=gomulu, vektor=Y.vektor_cizgileri(page, scale))
        _imza_out(out, page, bol, bag, sayfa, scale, img)
    return out


def _imza_out(out: dict, page, bol, bag, sayfa: int, scale: float, img=None) -> None:
    out["imza"] = Y.sonuc(bol)
    out["bolgeler"] = bolge_kayitlari(bol, bag, sayfa, lambda b: tuple(to_page_rects(page, [b], scale)[0]))
    for b in bol:
        if b.karar == Y.BIRAKILDI:
            continue
        rect = to_page_rects(page, [b.kutu], scale)[0]
        if b.yama is not None:
            buf = io.BytesIO()
            b.yama.save(buf, format="PNG")
            out["imza_yamalar"].append((rect, buf.getvalue()))
        else:
            out["imza_kutular"].append(rect)
            out["imza_yazilar"].append(Y.etiket_yazisi(b))


def imza_redact(page, ps: dict):
    """Maskeleme: sayfa taramasının imza kutularına karartma açıklaması ekler (renk ayrılan yamalar
    için beyaz) → ((dikdörtgen, yazı) etiketleri, karartma uygulandıktan sonra çağrılacak işlev:
    yamaları basar)."""
    labels = []
    yazilar = ps.get("imza_yazilar") or [IM.IMZA_LABEL] * len(ps.get("imza_kutular") or [])
    for r, t in zip(ps.get("imza_kutular") or [], yazilar):
        page.add_redact_annot(r, fill=(0, 0, 0))
        labels.append((r, t))
    yamalar = list(ps.get("imza_yamalar") or [])
    for r, _ in yamalar:
        page.add_redact_annot(r, fill=(1, 1, 1))

    def sonra():
        for r, png in yamalar:
            try:
                page.insert_image(r, stream=png)
            except Exception:
                pass
    return labels, sonra
