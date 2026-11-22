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
    el_yazisi: list = field(default_factory=list)        # m3 onay bekleyen/bırakılan bölgeleri (kutu piksel)
    meta: dict = field(default_factory=dict)             # kutular sırası → m3 bölge bilgisi (kaynak, neden, güven)
    bolgeler: list = field(default_factory=list)         # m1 imza bölgeleri (`yapi.Bolge`, görüntü pikseli)


def _siyah_ustunde(g, w) -> bool:
    """Kelime kutusunun çoğu siyah (önceki kapatma kutusu): OCR'ın siyah çubukta okuduğu çöp kelime."""
    x0, y0, x1, y1 = max(0, int(w.x0)), max(0, int(w.y0)), min(g.width, int(w.x1)), min(g.height, int(w.y1))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return False
    h = g.crop((x0, y0, x1, y1)).histogram()
    return sum(h[:40]) >= 0.5 * max(1, sum(h))


def _quality_reason(img, words: list[Word]) -> str | None:
    g = img.convert("L")
    words = [w for w in words if not _siyah_ustunde(g, w)]      # kapatma kutusundaki çöp okuma kaliteyi düşürmesin
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
    ywords: list[Word] = list(extra_words or [])     # imza çözümlemesinin kelimeleri
    ran = False
    clean = None
    if ocr:
        try:
            # desen, etiket alanı ve OCR kalitesi ÖZGÜN görüntünün OCR'ından (çizgileri silinmiş kopya etiketlerin
            # altını kırpabilir: el yazısı dilekçede etiket kaçar, güven düşer). Tablo ızgarası varsa imza
            # çözümlemesi ayrıca çizgileri silinmiş kopyanın OCR'ını kullanır (yapi.cizgisiz; tesseract
            # ızgaralı sayfada hücre yazılarını, başlıktaki "İmza" dahil, çoğu zaman atlıyor).
            ow = ocr_words(img)
            ran = True
            clean = Y.cizgisiz(img, ppi) if yapi is not None else None
            cw = ocr_words(clean) if clean is not None else None
        except (OcrFailed, Exception) as e:   # araç yok / çöktü
            if not ran:
                r.taranamadi = f"OCR çalışmadı: {str(e)[:120]}" if ocr_available() else "OCR yok (tesseract + tur dil verisi)"
                ow = []
            cw = None
        if ran:
            r.bulgular, r.kutular, r.turler = find_pii_typed(ow, rules)
            if cw:                           # çizgisiz kopyada ek bulunan desenler (örtüşmeyenler)
                b2, k2, t2 = find_pii_typed(cw, rules)
                for bx, tr in zip(k2, t2):
                    if not any(IM._inter(bx, o) for o in r.kutular):
                        r.kutular.append(bx)
                        r.turler.append(tr)
                        r.bulgular[tr] += 1
            if rules.label_fields:
                add_label_fields(r, img, _birlesik(ow, cw))
            if need_text:
                r.taranamadi = _quality_reason(img, ow)
                if r.taranamadi and cw and _quality_reason(img, cw) is None:
                    r.taranamadi = None
        words += ow
        ywords += cw if cw else ow
    r.words = words
    if yapi is not None:                 # m1: yapısal imza bölgeleri (yapi.py)
        dogrula = (lambda b: box_text_words(crop_for_ocr(img, ppi, b))) if ran and ocr_available() else None
        kelime = (lambda b: _crop_words(clean if clean is not None else img, b)) if ran and ocr_available() else None
        r.bolgeler = Y.goruntu_bolgeleri(img, ywords, ppi, kesin=list(extra_words or []), bag=yapi.get("bag"),
                                         sayfa=yapi.get("sayfa", 1), ocr_dogrula=dogrula, ocr_kelime=kelime,
                                         foto=bool(yapi.get("foto")), web=bool(yapi.get("web")))
        r.imza = Y.sonuc(r.bolgeler)
        return r, ran
    r.imza = IM.analyze(img, words, ppi, flag_unlabeled=flag_unlabeled, all_zone=all_zone)
    if ran:
        verify_covers(r.imza, lambda b: crop_for_ocr(img, ppi, b))
    return r, ran


def _birlesik(ow: list[Word], cw: list[Word] | None) -> list[Word]:
    """Özgün OCR kelimeleri + çizgisiz kopyanın yalnız onda bulunan kelimeleri (ayrı satır anahtarıyla):
    ızgaralı tabloda özgün OCR'ın atladığı basılı hücre yazıları el yazısı dizisi sanılmasın."""
    if not cw:
        return ow
    out = list(ow)
    for w in cw:
        if not any(IM._overlap(w.box, o.box) > 0.3 * max(1.0, (w.x1 - w.x0) * (w.y1 - w.y0)) for o in ow):
            out.append(Word(w.text, w.conf, w.x0, w.y0, w.x1, w.y1, ("c",) + tuple(w.line)))
    return out


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
    sayısı (alan/satır başına). Yalnız OCR kelimeleri (metin katmanı değil): bkz. `alan`.

    m3 bağlantı noktası: `alan.el_yazisi_bolgeleri` varsa `find_fields` yerine o çağrılır (ikisi birlikte
    değil: aynı alan çift sayılır); bölgeleri `r.el_yazisi`'ye (piksel kutu, `olcek=1`) girer, kimlik ve
    insan kararlarını toplayıcı (`bolge.Baglam`) verir. Form şablonları çalışma alanından
    (`sablon.SablonBellegi`, `BIDR_MASKE_WS`)."""
    from . import alan as AL
    from .bolge import saglayici
    fn = saglayici("el_yazisi")
    if fn is not None:
        try:
            # psm 11 ikinci geçişi etiket ya da form ipucu bulunduğunda her zaman (eski davranış): psm 3 el
            # yazısıyla karışık form satırını bütünüyle atlayabilir, sayfanın geneli iyi okunsa da
            regs = fn(img, ow, sayfa=1, dosya="m3", olcek=1.0, more=lambda: ocr_words(img, psm="11"),
                      sablonlar=_sablonlar(), rakam=rakam_dizisi_gerekli(ow))
        except Exception:        # sağlayıcı hatası tespiti düşürmesin
            regs = []
        adlar = sorted((getattr(AL, "_TUR_AD", None) or {}).items(), key=lambda kv: -len(kv[1]))
        for b in regs or []:
            if b.get("karar") != "kapatildi":
                r.el_yazisi.append(dict(b, id=None))
                continue
            r.kutular.append(tuple(b["kutu"]))
            r.turler.append(AL.KIND)
            r.meta[len(r.kutular) - 1] = {k: b.get(k) for k in ("kaynak", "neden", "guven")}
            kind = next((k for k, ad in adlar if (b.get("neden") or "").startswith(ad)), None)
            if kind:
                r.alanlar.append(kind)
            r.bulgular[AL.KIND] += 1
        return
    try:
        fields = AL.find_fields(img, ow, more=(lambda: ocr_words(img, psm="11")) if weak_ocr(ow) else None)
    except Exception:            # alan çözümlemesi tespiti düşürmesin
        return
    for f in fields:
        r.kutular.append(f.box)
        r.turler.append(AL.KIND)
        r.alanlar.append(f.kind)
    if fields:
        r.bulgular[AL.KIND] += len(fields)


VERIFY_PPI = 300                  # kapatma adayı yeniden OCR çözünürlüğü
_SABLON: dict = {}


def _sablonlar():
    """Çalışma alanının form şablon belleği (m3; `BIDR_MASKE_WS`), yoksa None."""
    import os
    ws = os.environ.get("BIDR_MASKE_WS")
    if not ws:
        return None
    from .sablon import DOSYA
    try:
        st = (Path(ws) / DOSYA).stat()
        imza = (st.st_mtime_ns, st.st_size)
    except OSError:
        imza = None
    eski = _SABLON.get(ws)
    if eski is None or (eski[0] != imza and not (eski[1] is not None and eski[1].degisti)):
        # dosya bu süreç dışında değiştiyse (ör. `bidr maskele ciz`) yeniden yüklenir
        try:
            from .sablon import SablonBellegi
            _SABLON[ws] = (imza, SablonBellegi.calisma_alani(ws))
        except Exception:
            _SABLON[ws] = (imza, None)
    return _SABLON[ws][1]


KASITLI_TUR = ("kisisel_veri", "el_yazisi_alan", "kullanici")       # içindeki kelime kapatılmak için bulundu
KASITLI_KAYNAK = ("metin_deseni", "ocr_deseni", "kapatan_isaretleme")


def basili_kelime(w) -> bool:
    """Aşırı kapatma ölçümünde sayılan basılı kelime: güvenle okunan, en az 3 harfli."""
    return w.conf >= 80 and sum(c.isalpha() for c in w.text) >= 3


def asiri_kapatma(kelimeler, siyahlar, kasitli, alan: float) -> dict:
    """Kapatma ölçümü: siyah kutuların altında kalan basılı kelime sayısı (kasıtlı kapatılan kişisel veri
    bölgelerinin içindekiler hariç) ve sayfa alanına oranla en büyük / toplam siyah alan. `kelimeler`,
    `siyahlar`, `kasitli`: (x0, y0, x1, y1) aynı düzlemde."""
    def icinde(k, r):
        cx, cy = (k[0] + k[2]) / 2, (k[1] + k[3]) / 2
        return r[0] <= cx <= r[2] and r[1] <= cy <= r[3]
    alti = [k for k in kelimeler if any(icinde(k, s) for s in siyahlar) and not any(icinde(k, q) for q in kasitli)]
    alanlar = [max(0.0, s[2] - s[0]) * max(0.0, s[3] - s[1]) for s in siyahlar]
    a = alan or 1.0
    return {"basili_kelime": len(kelimeler), "siyah_altinda": len(alti),
            "en_buyuk_kutu_payi": round(max(alanlar, default=0.0) / a, 4),
            "siyah_alan_payi": round(min(1.0, sum(alanlar) / a), 4)}


def sablon_onerileri(page, sablonlar) -> list:
    """Metin katmanlı (born-digital) sayfa: form şablon belleğinin bölgeleri (kullanıcı çizimi önerisi, öğrenilmiş
    alan). Şablon düzlemi 300 dpi; kelimeler metin katmanından (çizimden öğrenme de öyle: `inceleme._sablona_ogret`).
    → [(sayfa dikdörtgeni, bölge)]."""
    from . import alan as AL
    if sablonlar is None or AL.np is None or not any(s.get("bolgeler") for s in sablonlar.sablonlar):
        return []
    dpi = 300
    img = render(page, dpi)
    tw = text_words(page, dpi / 72.0)
    regs = AL.el_yazisi_bolgeleri(img, tw, sayfa=1, dosya="m3", olcek=1.0, sablonlar=sablonlar, yalniz_sablon=True)
    rects = to_page_rects(page, [tuple(e["kutu"]) for e in regs], dpi / 72.0)
    return list(zip(rects, regs))


GENISLET_MIN_PT = 12.0          # "kapat" kararlı bölge mürekkebe genişlerken kenar başına en az izin (pt)
GENISLET_MAX_PT = 36.0          # ve en çok izin (kutu yüksekliği kadar, bu sınırlar arasında)
MUREKKEP_ESIK = 170             # gri düzey: bunun altı mürekkep


def murekkep_kutusu(img, box, sinir: float):
    """`img` (PIL) üzerinde `box`la (piksel) kesişen mürekkep bileşenlerini tümüyle örten kutu; kutu her
    kenarda en çok `sinir` piksel büyür. Form çizgileri (uzun ince yatay/dikey bileşen) genişletmeye katılmaz.
    → yeni kutu (piksel) ya da numpy yoksa/mürekkep yoksa `box`."""
    from . import alan as AL
    np = AL.np
    if np is None:
        return tuple(box)
    W, H = img.size
    x0, y0 = max(0, int(box[0] - sinir) - 1), max(0, int(box[1] - sinir) - 1)
    x1, y1 = min(W, int(box[2] + sinir) + 2), min(H, int(box[3] + sinir) + 2)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return tuple(box)
    M = np.asarray(img.crop((x0, y0, x1, y1)).convert("L")) < MUREKKEP_ESIK
    bx = (box[0] - x0, box[1] - y0, box[2] - x0, box[3] - y0)
    out = list(box)
    ince = max(2.0, sinir / 6.0)
    for g in AL._components_np(M):
        if not (g.x0 < bx[2] and g.x1 > bx[0] and g.y0 < bx[3] and g.y1 > bx[1]):
            continue
        if min(g.w, g.h) <= ince and max(g.w, g.h) >= 12 * max(1, min(g.w, g.h)):
            continue                      # form çizgisi (alt çizgi, tablo kenarı)
        out = [min(out[0], g.x0 + x0), min(out[1], g.y0 + y0), max(out[2], g.x1 + x0), max(out[3], g.y1 + y0)]
    pay = max(1.0, sinir / 12.0)
    if out != list(box):
        out = [out[0] - pay, out[1] - pay, out[2] + pay, out[3] + pay]
    return (max(box[0] - sinir, out[0], 0), max(box[1] - sinir, out[1], 0),
            min(box[2] + sinir, out[2], W), min(box[3] + sinir, out[3], H))


def genisletilir(b: dict) -> bool:
    """İnsanın "kapat" dediği (otomatik önerinin) bölgesi mürekkebi tümüyle örtecek kadar genişletilir; kullanıcı
    çizimi (kutuyu insan çizdi), okunamayan sayfa ve yalnız sayfası bilinen model metni bölgesi hariç."""
    return ((b.get("insan") or {}).get("karar") == "kapat" and b.get("_yama") is None and not b.get("parcalar")
            and b.get("tur") not in ("kullanici", "okunamayan_sayfa")
            and b.get("kaynak") not in ("kullanici", "model_metni", "imza_metin"))


def _genislet_siniri(kutu_pt) -> float:
    return min(GENISLET_MAX_PT, max(GENISLET_MIN_PT, kutu_pt[3] - kutu_pt[1]))


def pdf_kapat_genislet(page, regs: list[dict]) -> None:
    """PDF sayfası: `genisletilir` bölgelerin kutusu (döndürülmemiş sayfa koordinatı) mürekkebe genişler."""
    import pymupdf
    dpi = 150
    f = dpi / 72.0
    for b in regs:
        if not genisletilir(b):
            continue
        sinir = _genislet_siniri(b["kutu"])
        r = pymupdf.Rect(*b["kutu"]) * page.rotation_matrix          # görüntülenen sayfa
        clip = (r + (-sinir - 2, -sinir - 2, sinir + 2, sinir + 2)) & page.rect
        if clip.is_empty:
            continue
        from PIL import Image
        pix = page.get_pixmap(dpi=dpi, clip=clip)
        img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("L")
        px = ((r.x0 - clip.x0) * f, (r.y0 - clip.y0) * f, (r.x1 - clip.x0) * f, (r.y1 - clip.y0) * f)
        k = murekkep_kutusu(img, px, sinir * f)
        if tuple(k) == px:
            continue
        yeni = pymupdf.Rect(k[0] / f + clip.x0, k[1] / f + clip.y0, k[2] / f + clip.x0, k[3] / f + clip.y0)
        yeni = (yeni * page.derotation_matrix) | pymupdf.Rect(*b["kutu"])
        b["kutu"] = [round(v, 2) for v in (yeni.x0, yeni.y0, yeni.x1, yeni.y1)]
        b["neden"] += "; kutu mürekkebi örtecek kadar genişletildi"


def sablon_gorunumu_pdf(page):
    """Şablon belleği düzlemi (300 dpi görüntü) ve maskeleme hattının bu sayfada kullandığı kelimeler: metin
    katmanı yeterliyse metin katmanı, değilse özgün + çizgisiz kopya OCR'ı (`analyze_image` ile aynı)."""
    dpi = 300
    img = render(page, dpi)
    need_ocr, has_text = page_needs_ocr(page)
    if not need_ocr and has_text:
        return img, text_words(page, dpi / 72.0)
    return img, _ocr_birlesik(img, dpi)


def _ocr_birlesik(img, ppi) -> list:
    ow = ocr_words(img)
    try:
        clean = Y.cizgisiz(img, ppi)
        cw = ocr_words(clean) if clean is not None else None
    except Exception:
        cw = None
    return _birlesik(ow, cw)
WEAK_WORDS = 60                   # psm 3 bundan az güvenilir kelime verdiyse psm 11 ikinci geçişi
WEAK_CONF = 80.0                  # ya da harf ağırlıklı ortalama güven bunun altındaysa


def rakam_dizisi_gerekli(words: list[Word]) -> bool:
    """Etiketsiz el yazısı rakam dizisi araması: metin katmanlı ya da güvenle OCR'lanan basılı sayfada
    yapılmaz (basılı sayı/kod dizileri yanlış alarm üretir)."""
    if words and all(w.conf >= 100 for w in words):
        return False                     # metin katmanı kelimeleri
    good, conf = text_quality(words)
    return not (good >= WEAK_WORDS and conf is not None and conf >= 85.0)


def weak_ocr(words: list[Word]) -> bool:
    """Varsayılan sayfa bölmesi (psm 3) az kelime ya da düşük güven verdi mi: yalnız o zaman seyrek
    metin kipiyle (psm 11) ikinci geçiş yapılır (sayfa başına ~2-3 sn tasarruf)."""
    good, conf = text_quality(words)
    return good < WEAK_WORDS or conf is None or conf < WEAK_CONF


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
            res.elle_kutu.append(b)
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
                  foto: bool = False, yapi: dict | None = None) -> ImageScan:
    """`ocr=False`: yalnız `extra_words` (PDF metin katmanı) ile imza çözümlemesi.
    `need_text`: OCR kalitesi düşükse `taranamadi` doldurulsun mu (metin katmanı yoksa evet).
    OCR kalitesi düşükse görüntü 180/90/270 derece döndürülüp yeniden denenir (ters taranmış sayfa);
    okunan yöndeki kutular özgün görüntüye geri çevrilir. `foto`: görsel dosya; OCR hiç kelime
    bulamadıysa (fotoğraf) döndürüp yeniden denenmez: görsel okunamayan sayfa olur. `yapi`: verilirse
    ({"bag", "sayfa"}) imza bölgeleri yapısal kurallarla (`yapi.goruntu_bolgeleri`) `r.bolgeler`'e."""
    from PIL import Image
    tr = {"180": Image.Transpose.ROTATE_180, "90": Image.Transpose.ROTATE_90, "270": Image.Transpose.ROTATE_270}
    if ocr and not extra_words and need_text:
        # sayfa yönü imza/alan çözümlemesinden ÖNCE düzeltilir (90° dönmüş tutanakta tablo ve "İmza" başlığı
        # ancak doğru yönde bulunur); kutular özgün görüntü koordinatına geri çevrilir
        from .ocr import sayfa_yonu
        rot = sayfa_yonu(img)
        how = {90: "270", 180: "180", 270: "90"}.get(rot)       # OSD: saat yönünde döndür → PIL transpose
        if how:
            r2, _ = _analyze_once(img.transpose(tr[how]), ppi, rules, ocr, None, flag_unlabeled, need_text,
                                  all_zone, yapi)
            return _geri_cevir(r2, how, img)
    r, ran = _analyze_once(img, ppi, rules, ocr, extra_words, flag_unlabeled, need_text, all_zone, yapi)
    if not (ran and need_text and r.taranamadi and not extra_words):
        return r
    if foto and not any(w.conf >= 0 and any(c.isalnum() for c in w.text) for w in r.words):
        return r
    for how in ("180", "90", "270"):
        r2, _ = _analyze_once(img.transpose(tr[how]), ppi, rules, ocr, None, flag_unlabeled, need_text, all_zone, yapi)
        if r2.taranamadi is None:
            return _geri_cevir(r2, how, img)
    return r


def _geri_cevir(r2: "ImageScan", how: str, img) -> "ImageScan":
    """Döndürülmüş görüntüde yapılan taramanın kutuları → özgün görüntü (yama yerine siyah kutu)."""
    for b in r2.bolgeler:
        b.kutu = _unrotate(b.kutu, how, img.width, img.height)
        b.yama = None
    if r2.bolgeler:
        r2.imza = Y.sonuc(r2.bolgeler)
    r2.kutular = [_unrotate(b, how, img.width, img.height) for b in r2.kutular]
    if r2.imza:
        r2.imza.kapat = [_unrotate(b, how, img.width, img.height) for b in r2.imza.kapat]
        r2.imza.etiketsiz_kutu = [_unrotate(b, how, img.width, img.height) for b in r2.imza.etiketsiz_kutu]
        r2.imza.elle_kutu = [_unrotate(b, how, img.width, img.height) for b in r2.imza.elle_kutu]
    r2.el_yazisi = [dict(e, kutu=list(_unrotate(e["kutu"], how, img.width, img.height))) for e in r2.el_yazisi]
    r2.words = []
    return r2


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


def scan_image_obj(img, rules: MaskRules, *, flag_unlabeled: bool = True, all_zone: bool = False,
                   bag: "Y.Baglam | None" = None) -> ImageScan:
    """`all_zone`: görselin tamamı imza etiketinin yakını sayılır (belgede imza etiketi olan docx'in
    gömülü görseli: taranmış imza resmi). Görsel dosyada (`flag_unlabeled`, `all_zone` değil) imza
    bölgeleri yapısal kurallarla çıkarılır (`r.bolgeler`); `bag`: dosyalar arası tekrar belleği vb."""
    big, f = _ocr_view(img)
    yeni = flag_unlabeled and not all_zone
    r = analyze_image(big, _ppi(big), rules, flag_unlabeled=flag_unlabeled, all_zone=False,
                      need_text=not all_zone and flag_unlabeled, foto=True,
                      yapi={"bag": bag or Y.Baglam(), "sayfa": 1, "foto": renk_cesitliligi(img) >= FOTO_RENK}
                      if yeni else None)
    if f != 1:
        for b in r.bolgeler:
            b.kutu = tuple(v / f for v in b.kutu)
            if b.parcalar:
                b.parcalar = [tuple(v / f for v in q) for q in b.parcalar]
            if b.yama is not None:
                from PIL import Image
                b.yama = b.yama.resize((max(1, int(b.kutu[2]) - int(b.kutu[0])), max(1, int(b.kutu[3]) - int(b.kutu[1]))),
                                       Image.LANCZOS)
        r.kutular = [(a / f, b / f, c / f, d / f) for a, b, c, d in r.kutular]
        if r.imza:
            r.imza.kapat = [(a / f, b / f, c / f, d / f) for a, b, c, d in r.imza.kapat]
            r.imza.etiketsiz_kutu = [(a / f, b / f, c / f, d / f) for a, b, c, d in r.imza.etiketsiz_kutu]
            r.imza.elle_kutu = [(a / f, b / f, c / f, d / f) for a, b, c, d in r.imza.elle_kutu]
        r.el_yazisi = [dict(e, kutu=[v / f for v in e["kutu"]]) for e in r.el_yazisi]
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


FOTO_RENK = 48                  # bu kadar ayrı (nicemlenmiş) renk: fotoğraf/afiş (belge taraması değil)
FOTO_KELIME = 40                # fotoğrafta güvenilir kelime üst sınırı


def renk_cesitliligi(img) -> int:
    """Küçültülmüş görüntüde payı ≥ %0,2 olan nicemlenmiş (kanal başına 8 düzey) renk sayısı: belge
    taraması (beyaz + siyah/mavi mürekkep) birkaç renk, fotoğraf/afiş onlarca renk verir."""
    im = img.convert("RGB")
    im.thumbnail((160, 160))
    c = Counter((r >> 5, g >> 5, b >> 5) for r, g, b in im.getdata())
    n = sum(c.values()) or 1
    return sum(1 for v in c.values() if v >= 0.002 * n)


def fotograf_mi(img, words: list[Word] | None = None) -> bool:
    """Fotoğraf/afiş: renk çeşitliliği yüksek ve az metin."""
    if renk_cesitliligi(img) < FOTO_RENK:
        return False
    good = text_quality(words or [])[0]
    return good < FOTO_KELIME


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


def mask_image(src: Path, dst: Path, rules: MaskRules, bolge=None) -> dict:
    """Görsel dosya: tara → bölgeler (kimlik + insan kararları) → kapatılacaklar siyah kutu → en çok
    iki tur daha (kapatmadan sonra belirenler) → yer tutucular → üst verisiz kayıt."""
    from . import bolge as BG
    img = _open_image(src)
    bg = bolge if bolge is not None else BG.Baglam("00000000")
    r = scan_image_obj(img, rules)
    found = r.bulgular
    kapsam = page_coverage(r.bulgular, r.alanlar)
    ortusen = r.imza.ortusen_kelime if r.imza else 0
    from .formats import _hook_bolgeleri, _kararla
    regs = image_regions(r, img)
    sc = image_scale(img)
    from .formats import YAMA_SIYAH_ORTUSME, YENIDEN_TARAMA_ICINDE, _icinde_payi, kapanir
    for h in _hook_bolgeleri("imza", 1, img, rules, r, sc):
        h.setdefault("_px", [v / sc for v in h["kutu"]])
        regs.append(h)
    for u in bg.kullanici_bolgeleri(1):
        u["_px"] = [v / sc for v in u["kutu"]]
        regs.append(u)
    from .formats import kullaniciyla_ortusen_oneriyi_at
    regs = kullaniciyla_ortusen_oneriyi_at(regs)
    _kararla(bg, 1, regs)
    for b in regs:                           # "kapat" kararlı bölge: mürekkep bileşenlerini tümüyle örtsün
        if genisletilir(b) and b.get("_px"):
            sinir = _genislet_siniri(b["kutu"]) / sc
            k = murekkep_kutusu(img, b["_px"], sinir)
            if tuple(k) != tuple(b["_px"]):
                b["_px"] = list(k)
                b["kutu"] = [round(v * sc, 2) for v in k]
                b["neden"] += "; kutu mürekkebi örtecek kadar genişletildi"
    out = img
    labels = []
    bolge_n = 0
    siyahlar: list = []                      # bütün turların siyah kutuları (piksel)
    for turn in range(3):                    # kapatma sonrası belirginleşen bulgu/vuruş için en çok iki tur daha
        close = [b for b in regs if kapanir(b)]
        if not close:
            break
        siyah_yeni = [p for b in close if b.get("_yama") is None for p in (b.get("_parcalar_px") or [b["_px"]])]
        yamali = []
        for b in close:                      # m1: renkli mürekkebi ayrılmış kırpıntı; siyahla örtüşen yama basılmaz
            if b.get("_yama") is None:
                continue
            if _icinde_toplam(b["_px"], siyahlar + siyah_yeni) >= YAMA_SIYAH_ORTUSME:
                b.pop("_yama")
                b["neden"] += "; renk ayırma yaması siyah kapatmayla örtüştü: siyah kapatıldı"
                siyah_yeni.append(b["_px"])
            else:
                yamali.append(b)
        close = [b for b in close if b.get("_yama") is None]
        labels += [(b["_px"], b.get("_etiket") or "[MASKELI]") for b in close if not b.get("_parcalar_px")]
        bolge_n += sum(1 for b in close + yamali if b["tur"] == "imza")
        for b in yamali:
            out = out.convert("RGB") if out.mode not in ("RGB", "L") else out.copy()
            out.paste(b.pop("_yama").convert(out.mode), (int(b["_px"][0]), int(b["_px"][1])))
            b["_yamali"] = True
        siyahlar += siyah_yeni
        out = black_out(out, siyahlar)       # siyah kapatma her turda en son ve en üstte (önceki turlarınki dahil)
        if turn == 2:
            break
        r = scan_image_obj(out, rules)
        ortusen += r.imza.ortusen_kelime if r.imza else 0
        kapsam.update(page_coverage(r.bulgular, r.alanlar))
        kapali = [b["kutu"] for b in bg.bolgeler if kapanir(b)]
        regs = [b for b in image_regions(r, out) if b["karar"] == BG.KAPATILDI and b["tur"] != "okunamayan_sayfa"
                and not any(o["karar"] == BG.BIRAKILDI and BG.ortusme(o["kutu"], b["kutu"]) >= 0.5 for o in bg.bolgeler)
                and _icinde_payi(b["kutu"], kapali) < YENIDEN_TARAMA_ICINDE]
        if regs:
            _kararla(bg, 1, regs, ilk=False)
    out = draw_labels(out, labels)
    save_like(out, dst, src.suffix)
    first = scan_image_obj(img, rules)       # önbellekli OCR: yalnız ilk tarama uyarısı
    kasitli = [b["_px"] for b in bg.bolgeler if b.get("_px") and (b["tur"] in KASITLI_TUR
                                                                      or b["kaynak"] in KASITLI_KAYNAK)]
    olcum = asiri_kapatma([w.box for w in first.words if basili_kelime(w)], siyahlar, kasitli, img.width * img.height)
    uyarilar = [f"taranamadı: {first.taranamadi}"] if first.taranamadi else []
    return {"maskelenen": found, "temizlenen": ["ust_veri"], "uyarilar": uyarilar,
            "imza_bolgesi": bolge_n, "ortusen_kelime": ortusen, "sayfa_sayisi": 1, "sayfa_kapsam": {1: dict(kapsam)},
            "bolgeler": bg.bolgeler, "sayfa_kutulari": {1: [0.0, 0.0, img.width * sc, img.height * sc]},
            "kapatma_olcumu": {1: olcum},
            "sayfalar": [{"no": 1, "genislik": round(img.width * sc, 2), "yukseklik": round(img.height * sc, 2),
                          "donus": 0, "matris": [1, 0, 0, 1, 0, 0]}]}


def _icinde_toplam(k, kutular) -> float:
    a = max(1e-6, (k[2] - k[0]) * (k[3] - k[1]))
    t = 0.0
    for o in kutular:
        ix = min(k[2], o[2]) - max(k[0], o[0])
        iy = min(k[3], o[3]) - max(k[1], o[1])
        if ix > 0 and iy > 0:
            t += ix * iy
    return min(1.0, t / a)


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
            "imza_aday": r.imza.etiketli if r.imza else 0,
            "bolge_adaylari": [b for b in image_regions(r, img, kalan=True) if b["karar"] == "onay_bekliyor"]}


def image_scale(img) -> float:
    """Görsel pikseli → bölge kutusu (puan): kısa kenar A4 genişliği sayılır (`_ppi`)."""
    return 72.0 / _ppi(img)


def image_regions(r: "ImageScan", img, *, kalan: bool = False) -> list[dict]:
    """Görsel taraması → bölgeler (puan; iç alanlar `_px` piksel kutusu, `_etiket` yer tutucu).
    `kalan`: maskeli kopyanın yeniden taraması (kapatılmamış etiketli imza adayı onay bekler)."""
    from . import bolge as BG
    from .detect import PLACEHOLDERS
    sc = image_scale(img)
    out = []

    def add(px, tur, karar, neden, kaynak, guven, etiket):
        b = BG.yeni(1, [v * sc for v in px], tur, karar, neden, kaynak, guven)
        b["_px"] = list(px)
        b["_etiket"] = etiket
        out.append(b)
    for i, (px, k) in enumerate(zip(r.kutular, r.turler)):
        if k == "etiket_alani":
            m = r.meta.get(i) or {}
            add(px, "el_yazisi_alan", BG.KAPATILDI, m.get("neden") or "kişisel veri etiketinin alanı",
                m.get("kaynak") or "etiket_alani", m.get("guven") or 0.7, PLACEHOLDERS.get(k, "[MASKELI]"))
        else:
            add(px, "kisisel_veri", BG.KAPATILDI, f"desen: {k}", "ocr_deseni", 0.9, PLACEHOLDERS.get(k, "[MASKELI]"))
    for e in r.el_yazisi:
        add(e["kutu"], "el_yazisi_alan", e.get("karar") or BG.ONAY, e.get("neden") or "el yazısı alan",
            e.get("kaynak") or "etiket_alani", e.get("guven") or 0.5, "[KİŞİSEL VERİ]")
    if BG.saglayici("imza") is None and r.imza is not None:
        for px in r.imza.kapat:
            if kalan:
                add(px, "imza", BG.ONAY, "maskeli kopyada kapatılmamış imza adayı", "imza_kalan", 0.5, IM.IMZA_LABEL)
            else:
                add(px, "imza", BG.KAPATILDI, "imza etiketi/unvan yakınında mürekkep", "imza_aday", 0.6, IM.IMZA_LABEL)
        for px in r.imza.elle_kutu:
            add(px, "imza", BG.ONAY, "metinle örtüşen imza: kapatılmadı", "imza_metin", 0.5, IM.IMZA_LABEL)
        for px in r.imza.etiketsiz_kutu:
            add(px, "imza", BG.ONAY, "etiketsiz imza benzeri mürekkep", "imza_etiketsiz", 0.3, IM.IMZA_LABEL)
    if r.taranamadi:
        add((0, 0, img.width, img.height), "okunamayan_sayfa", BG.ONAY, f"okunamadı: {r.taranamadi}"[:160],
            "ocr", 0.0, "[MASKELI]")
    return out


# ---------------------------------------------------------------- PDF sayfaları (PyMuPDF)

_PLACEHOLDER_RE = re.compile(r"\[(?:İMZA|IMZA|MASKELI|KİŞİSEL VERİ|KISISEL VERI|[A-Z_]{2,12})\]")


SUFFICIENT_WORDS = 25            # büyük görüntülü sayfada metin katmanının "yeterli" sayılması için
SUFFICIENT_RATIO = 0.75          # kelimelerin bu kadarı harf/rakam ağırlıklı (çöp OCR katmanı değil)
SUFFICIENT_SPREAD = 0.5          # kelimeler görüntünün yüksekliğinin en az bu kadarına yayılmış


def _big_image(page):
    """Sayfanın en büyük görüntüsü (sayfa dikdörtgeniyle kesişimi) ve sayfa alanına oranı."""
    import pymupdf
    best, frac = None, 0.0
    try:
        area = page.rect.get_area() or 1.0
        for info in page.get_image_info():
            r = pymupdf.Rect(info["bbox"]) & page.rect
            if r.get_area() / area > frac:
                best, frac = r, r.get_area() / area
    except Exception:
        pass
    return best, frac


def text_layer_sufficient(page, rect=None) -> bool:
    """Metin katmanı "var" değil "yeterli" mi: (görüntünün üstünde) yeterince kelime, çoğu harf/rakam
    ağırlıklı ve görüntünün yüksekliğine yayılmış (aranabilir PDF'in OCR katmanı). Yeterliyse OCR
    yapılmaz; imza ve etiket alanı metin katmanı kelimeleriyle çözümlenir."""
    try:
        words = [w for w in page.get_text("words") if not _PLACEHOLDER_RE.fullmatch(w[4])]
    except Exception:
        return False
    if rect is not None:
        words = [w for w in words if rect.x0 - 2 <= (w[0] + w[2]) / 2 <= rect.x1 + 2
                 and rect.y0 - 2 <= (w[1] + w[3]) / 2 <= rect.y1 + 2]
    if len(words) < SUFFICIENT_WORDS:
        return False
    good = [w for w in words if len(w[4]) >= 2 and sum(c.isalnum() for c in w[4]) >= 0.7 * len(w[4])]
    if len(good) < SUFFICIENT_RATIO * len(words):
        return False
    h = (rect.height if rect is not None else page.rect.height) or 1.0
    return (max(w[3] for w in good) - min(w[1] for w in good)) >= SUFFICIENT_SPREAD * h


def page_needs_ocr(page) -> tuple[bool, bool]:
    """→ (OCR gerekir mi, metin katmanı var mı). Metin yoksa ya da sayfanın ≥%40'ı tek görüntüyse ve
    görüntünün üstündeki metin katmanı yeterli değilse (`text_layer_sufficient`)."""
    text = _PLACEHOLDER_RE.sub("", page.get_text("text")).strip()   # maskeleyicinin yazdığı etiketler sayılmaz
    has_text = len(text) >= 20
    rect, big = _big_image(page)
    if not has_text:
        return True, False
    return big >= 0.4 and not text_layer_sufficient(page, rect), has_text


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


def scan_pdf_page(page, rules: MaskRules) -> dict:
    """Tek sayfa: OCR gerekiyorsa OCR + PII + imza; metin katmanlı sayfada imza etiketi ve grafik
    varsa imza çözümlemesi. → {"bulgular","kutular_pt","imza","taranamadi","ortusen"}."""
    need_ocr, has_text = page_needs_ocr(page)
    bag = Y.baglam(page.parent)
    sayfa = page.number + 1
    yapi = {"bag": bag, "sayfa": sayfa}
    out = {"bulgular": Counter(), "kutular": [], "turler": [], "imza": None, "taranamadi": None,
           "imza_kutular": [], "alanlar": [], "imza_aday_kutular": [], "ocr": bool(need_ocr), "bolgeler": []}
    if not need_ocr and has_text and _big_image(page)[1] >= 0.4:
        # yeterli metin katmanlı tarama: OCR yok; imza ve etiket alanı metin katmanı kelimeleriyle
        dpi = 300
        img = render(page, dpi)
        tw = text_words(page, dpi / 72.0)
        r = analyze_image(img, dpi, rules, ocr=False, extra_words=tw, need_text=False, yapi=yapi)
        if rules.label_fields:
            add_label_fields(r, img, tw)
        out["bulgular"] = r.bulgular
        out["kutular"] = to_page_rects(page, r.kutular, dpi / 72.0)
        out["turler"] = list(r.turler)
        out["alanlar"] = list(r.alanlar)
        _imza_out(out, page, r.bolgeler, dpi / 72.0)
        out["el_yazisi"] = _el_rects(page, r, dpi / 72.0)
        out["meta"] = dict(r.meta)
        out["metin_yeterli"] = True
        return out
    if need_ocr:
        dpi = 300
        img = render(page, dpi)
        yapi["foto"] = renk_cesitliligi(img) >= FOTO_RENK
        tw = text_words(page, dpi / 72.0) if has_text else []
        r = analyze_image(img, dpi, rules, extra_words=tw, need_text=not has_text, yapi=yapi)
        out["bulgular"] = r.bulgular
        out["kutular"] = to_page_rects(page, r.kutular, dpi / 72.0)
        out["turler"] = list(r.turler)
        out["alanlar"] = list(r.alanlar)
        out["taranamadi"] = r.taranamadi if not has_text else None
        _imza_out(out, page, r.bolgeler, dpi / 72.0)
        out["el_yazisi"] = _el_rects(page, r, dpi / 72.0)
        out["meta"] = dict(r.meta)
        out["basili_kelimeler"] = to_page_rects(page, [w.box for w in r.words if basili_kelime(w)], dpi / 72.0)
        return out
    scale = SIG_DPI / 72.0
    regions = signature_image_regions(page, scale)
    tw = text_words(page, scale)
    if regions or has_label_words(tw) or bag.sutun or any(Y._imza_basligi(w) for w in tw):
        img = render(page, SIG_DPI)
        gomulu = [(b, _imza_gibi(img, b)) for b in regions]
        bol = Y.goruntu_bolgeleri(img, tw, SIG_DPI, kesin=tw, bag=bag, sayfa=sayfa, metin_sayfasi=True,
                                  gomulu=gomulu, vektor=Y.vektor_cizgileri(page, scale), web=web_ciktisi(page))
        _imza_out(out, page, bol, scale)
    if rules.label_fields:
        try:                                 # aynı formun başka kopyasında çizilen/kapatılan bölgeler
            out["el_yazisi"] = sablon_onerileri(page, _sablonlar())
        except Exception:                    # şablon belleği tespiti düşürmesin
            pass
    return out


_URL = re.compile(r"(?i)(https?://|www\.)\S+|\b[\w-]+\.(com|org|net|edu|gov)(\.tr)?/\S*")
_TARIH = re.compile(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b")


def web_ciktisi(page) -> bool:
    """Tarayıcı çıktısı sayfa (born-digital/web): metin katmanı var, üst ya da alt bilgi bandında URL ve tarih."""
    try:
        r = page.rect
        bant = []
        for x0, y0, x1, y1, t, *_ in page.get_text("words"):
            if y1 <= r.y0 + 0.08 * r.height or y0 >= r.y1 - 0.08 * r.height:
                bant.append(t)
    except Exception:
        return False
    s = " ".join(bant)
    return bool(_URL.search(s)) and bool(_TARIH.search(s))


def _imza_gibi(img, box) -> bool:
    """Gömülü görüntü imza resmi olabilir mi: tek renkli (logo/fotoğraf değil), seyrek mürekkep."""
    x0, y0, x1, y1 = (int(max(0, box[0])), int(max(0, box[1])), int(min(img.width, box[2])), int(min(img.height, box[3])))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return False
    c = img.crop((x0, y0, x1, y1))
    if multicolor(c) or renk_cesitliligi(c) >= FOTO_RENK:
        return False                      # fotoğraf/rozet/ikon
    hist = c.convert("L").histogram()
    frac = sum(hist[:160]) / float(c.width * c.height)
    return 0.002 <= frac <= 0.35


def _imza_out(out: dict, page, bol, scale: float) -> None:
    """m1 imza bölgeleri → sayfa taraması: `imza` (eski arabirim), `imza_kutular` (siyah kutu) ve
    `bolgeler` (sözleşme biçiminde, kutu puan; kimliği toplayıcı verir; iç alanlar `_etiket` yer
    tutucu/geri basılan yazı, `_yama` renkli mürekkebi ayrılmış kırpıntının PNG'si)."""
    out["imza"] = Y.sonuc(bol)
    out["imza_kutular"] = []
    out["imza_aday_kutular"] = []
    out["bolgeler"] = []
    for b in bol:
        rect = to_page_rects(page, [b.kutu], scale)[0]
        d = b.kayit(None, page.number + 1, tuple(rect))
        d["_etiket"] = Y.etiket_yazisi(b)
        if b.parcalar:
            d["parcalar"] = b.parcalar_donustur(lambda p: tuple(to_page_rects(page, [p], scale)[0]))
        if b.yama is not None and b.karar != Y.BIRAKILDI:
            buf = io.BytesIO()
            b.yama.save(buf, format="PNG")
            d["_yama"] = buf.getvalue()
        elif b.kapat:
            out["imza_kutular"].append(rect)
        out["bolgeler"].append(d)


def image_imza_bolgeleri(r: "ImageScan", olcek: float) -> list[dict]:
    """Görsel taraması → m1 imza bölgeleri (kutu puan = piksel × `olcek`; `_px` piksel, `_yama` PIL)."""
    out = []
    for b in r.bolgeler:
        d = b.kayit(None, 1, tuple(v * olcek for v in b.kutu))
        d["_px"] = list(b.kutu)
        d["_etiket"] = Y.etiket_yazisi(b)
        if b.parcalar:
            d["parcalar"] = b.parcalar_donustur(lambda p: tuple(v * olcek for v in p))
            d["_parcalar_px"] = [list(p) for p in b.parcalar]
        if b.yama is not None and b.karar != Y.BIRAKILDI:
            d["_yama"] = b.yama
        out.append(d)
    return out


def _el_rects(page, r: "ImageScan", scale: float) -> list:
    """m3 el yazısı bölgeleri (piksel) → [(sayfa dikdörtgeni, bölge)]."""
    rects = to_page_rects(page, [tuple(e["kutu"]) for e in r.el_yazisi], scale)
    return list(zip(rects, r.el_yazisi))


def _aday_rects(page, res, scale: float) -> list:
    """Kapatılmayan imza adayları → [(sayfa dikdörtgeni, "etiketsiz" | "metin")]."""
    if res is None:
        return []
    out = [(r, "etiketsiz") for r in to_page_rects(page, getattr(res, "etiketsiz_kutu", []) or [], scale)]
    out += [(r, "metin") for r in to_page_rects(page, getattr(res, "elle_kutu", []) or [], scale)]
    return out
