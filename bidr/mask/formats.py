"""Biçime göre maskeleme (yayın kopyası) ve bağımsız yeniden tarama.

Her `mask_*(src, dst, rules)` → `{"maskelenen": Counter, "temizlenen": [...], "uyarilar": [...]}`.
`scan_file(path, rules)` maskeleyiciden bağımsız okur → `{"bulgular": Counter, "sorunlar": [...],
"imza": [...]}`; kopyanın yayımlanabilirliğine bu karar verir.

PDF: PyMuPDF (`pymupdf`/`fitz`) varsa gerçek kaldırma (redaction: içerik ve metin katmanı
silinir); yoksa pypdf ile en iyi çaba (içerik akışındaki metin işlemlerinin baytları değiştirilir;
iki baytlı/gömülü kodlamalı yazı tiplerinde ve görüntüdeki metinde işe yaramaz — yeniden tarama
yakalar). İkisinde de üst veri, XMP, ekler, yorum/açıklamalar, form alanları, yer imleri temizlenir.

Görüntü katmanı (`raster`, `ocr`, `imza`): metin katmanı olmayan / tam sayfa görüntülü PDF
sayfaları, görsel dosyalar ve docx'e gömülü görseller yerel tesseract ile OCR'lanır; desen
kutuları ve imza bölgeleri siyah dikdörtgenle kapatılır. Tarama sonucu `taranamadi` (OCR'dan
geçemeyen sayfa), `imza_aday` (kapatılmamış etiketli imza adayı) ve `imza_elle` (etiketsiz aday:
elle bakılmalı) alanlarını da taşıyabilir. HTML: metin/öznitelik maskelenir, betik/yorum silinir.
"""
from __future__ import annotations

import io
import re
import zipfile
from collections import Counter
from pathlib import Path

from .detect import PLACEHOLDERS, MaskRules, detect, mask_text
from .imza import IMZA_LABEL

# Basılı metinle çok örtüşen imza bölgesi karartılmaz (belge bilgisi kaybolmasın): elle bakılmalı.
IMZA_METIN_SORUN = "imza: elle bakılmalı — basılı metinle örtüşen imza kapatılmadı"

PDF_EXT = {".pdf"}
DOCX_EXT = {".docx"}
XLSX_EXT = {".xlsx", ".xlsm"}
TEXT_EXT = {".txt", ".csv", ".md", ".tsv"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}
HTML_EXT = {".html", ".htm"}
SUPPORTED = PDF_EXT | DOCX_EXT | XLSX_EXT | TEXT_EXT | IMAGE_EXT | HTML_EXT

# Ham akış taramasında (PDF) yalnız ayırt edici türler: koordinat sayılarıyla karışmaz.
RAW_KINDS = ("tc_no", "iban", "eposta")
_HEX_STR = re.compile(r"(?<!<)<[0-9A-Fa-f\s]+>")


class MaskError(RuntimeError):
    pass


def _fold(s: str) -> str:
    return s.replace("İ", "i").replace("I", "ı").lower()


def _has_imza(s: str) -> bool:
    f = _fold(s)
    return "imza" in f or "ımza" in f


def _sub_rules(rules: MaskRules, kinds) -> MaskRules:
    return MaskRules(kinds=tuple(k for k in rules.kinds if k in kinds),
                     student_patterns=rules.student_patterns, names=rules.names)


def pdf_engine(prefer: str = "auto") -> str:
    """'pymupdf' (gerçek kaldırma) ya da 'pypdf' (en iyi çaba)."""
    if prefer == "pypdf":
        return "pypdf"
    if _fitz() is not None:
        return "pymupdf"
    if prefer == "pymupdf":
        raise MaskError("PyMuPDF kurulu değil: pip install 'bidr[maske]'")
    return "pypdf"


def _fitz():
    try:
        import pymupdf as fitz  # type: ignore
        return fitz
    except ImportError:
        try:
            import fitz  # type: ignore
            return fitz
        except ImportError:
            return None


def _quiet_pypdf() -> None:
    import logging
    logging.getLogger("pypdf").setLevel(logging.ERROR)


# ---------------------------------------------------------------- PDF (pypdf, en iyi çaba)

_POS_OPS = {b"Td", b"TD", b"Tm", b"T*"}


def _str_bytes(o) -> bytes | None:
    from pypdf.generic import ByteStringObject, TextStringObject
    if isinstance(o, TextStringObject):
        return bytes(o.original_bytes)
    if isinstance(o, ByteStringObject):
        return bytes(o)
    return None


def _mask_ops(operations, rules: MaskRules, counts: Counter) -> bool:
    """Metin işlemlerini birleştirip (Tj, TJ, ', ") tespit eder; eşleşen baytları 'X' yapar."""
    from pypdf.generic import ArrayObject, ByteStringObject, FloatObject, NumberObject
    chars: list[str] = []
    where: list[tuple | None] = []      # (işlem no, işlenen no, dizi no | None, bayt no)

    def virt(c):
        chars.append(c)
        where.append(None)

    def add(oi, ai, ei, o):
        b = _str_bytes(o)
        if b is None:
            return
        for j, x in enumerate(b):
            chars.append(chr(x))      # latin-1: bayt ↔ karakter birebir
            where.append((oi, ai, ei, j))

    for oi, (operands, op) in enumerate(operations):
        if op in (b"BT", b"ET"):
            virt("\n")
        elif op in _POS_OPS:
            virt(" ")
        elif op == b"Tj" and operands:
            add(oi, 0, None, operands[0])
        elif op == b"'" and operands:
            virt("\n")
            add(oi, 0, None, operands[0])
        elif op == b'"' and len(operands) >= 3:
            virt("\n")
            add(oi, 2, None, operands[2])
        elif op == b"TJ" and operands and isinstance(operands[0], ArrayObject):
            for ei, el in enumerate(operands[0]):
                if isinstance(el, (NumberObject, FloatObject, int, float)):
                    if float(el) <= -200:
                        virt(" ")
                else:
                    add(oi, 0, ei, el)
    text = "".join(chars)
    fs = detect(text, rules)
    if not fs:
        return False
    hits: dict[tuple, set[int]] = {}
    for f in fs:
        counts[f.kind] += 1
        for i in range(f.start, f.end):
            w = where[i]
            if w is not None and not text[i].isspace():
                hits.setdefault(w[:3], set()).add(w[3])
    for (oi, ai, ei), pos in hits.items():
        operands = operations[oi][0]
        o = operands[ai] if ei is None else operands[ai][ei]
        b = bytearray(_str_bytes(o) or b"")
        for j in pos:
            b[j] = ord("X")
        new = ByteStringObject(bytes(b))
        if ei is None:
            operands[ai] = new
        else:
            operands[ai][ei] = new
    return True


def _clean_pdf_writer(w) -> list[str]:
    """Belge düzeyi temizlik: üst veri, XMP, ekler, form, yer imleri, yapı ağacı, sayfa açıklamaları."""
    from pypdf.generic import NameObject
    done = []
    root = w.root_object
    for key, tag in (("/Metadata", "xmp"), ("/Names", "ekler_ve_adlar"), ("/AcroForm", "form"),
                     ("/OpenAction", "eylem"), ("/AA", "eylem"), ("/Outlines", "yer_imleri"),
                     ("/StructTreeRoot", "yapi_agaci"), ("/PieceInfo", "ozel_veri")):
        if NameObject(key) in root:
            del root[NameObject(key)]
            done.append(tag)
    for page in w.pages:
        for key, tag in (("/Annots", "yorum_aciklama"), ("/Metadata", "xmp"), ("/PieceInfo", "ozel_veri"),
                         ("/Thumb", "kucuk_resim"), ("/AA", "eylem")):
            if NameObject(key) in page:
                del page[NameObject(key)]
                done.append(tag)
    try:
        if w.metadata:
            done.append("ust_veri")
    except Exception:
        pass
    w.metadata = None
    return sorted(set(done))


def _rebuild(w):
    """Yalnız sayfaları (ve onların başvurduğu nesneleri) yeni bir yazıcıya taşır: silinen
    ekler, eski içerik akışları gibi sahipsiz nesneler dosyaya yazılmaz."""
    from pypdf import PdfWriter
    out = PdfWriter()
    for page in w.pages:
        out.add_page(page)
    out.metadata = None
    return out


def _pypdf_covering_annots(reader) -> bool:
    for page in reader.pages:
        for ref in page.get("/Annots") or []:
            try:
                a = ref.get_object()
            except Exception:
                continue
            st = str(a.get("/Subtype") or "")
            if st in ("/Line", "/Ink", "/PolyLine", "/Polygon", "/Square", "/Circle", "/Stamp", "/Redact"):
                return True
            if st == "/Highlight":
                c = [float(x) for x in (a.get("/C") or [1, 1, 1])]
                lum = (0.3 * c[0] + 0.59 * c[1] + 0.11 * c[2]) if len(c) == 3 else (c[0] if c else 1.0)
                if lum < 0.35:
                    return True
    return False


def mask_pdf_pypdf(src: Path, dst: Path, rules: MaskRules) -> dict:
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import ContentStream
    _quiet_pypdf()
    reader = PdfReader(str(src))
    if reader.is_encrypted:
        raise MaskError("şifreli PDF")
    if _pypdf_covering_annots(reader):
        raise MaskError("sayfada içeriği örten açıklama (elle karartma çizgisi/mürekkep/damga) var: "
                        "pypdf ile silinirse altı açığa çıkar; PyMuPDF gerekir (pip install 'bidr[maske]')")
    w = PdfWriter(clone_from=reader)
    counts: Counter = Counter()
    uyarilar = ["PyMuPDF yok: PDF maskeleme pypdf ile en iyi çaba (içerik akışı baytları); "
                "gerçek kaldırma için pip install 'bidr[maske]'"]
    for page in w.pages:
        cs = page.get_contents()
        if cs is not None and _mask_ops(cs.operations, rules, counts):
            page.replace_contents(cs)
        res = page.get("/Resources")
        xobjs = (res.get_object().get("/XObject") if res is not None else None)
        if xobjs is not None:
            for name in list(xobjs.get_object().keys()):
                xo = xobjs.get_object()[name].get_object()
                if xo.get("/Subtype") != "/Form":
                    continue
                try:
                    fcs = ContentStream(xo, w)
                    if _mask_ops(fcs.operations, rules, counts):
                        xo.set_data(fcs.get_data())
                except Exception as e:   # biçim nesnesi değiştirilemedi: yeniden tarama karar verir
                    uyarilar.append(f"biçim nesnesi işlenemedi: {type(e).__name__}")
    temiz = _clean_pdf_writer(w)
    w = _rebuild(w)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(dst, "wb") as f:
        w.write(f)
    return {"maskelenen": counts, "temizlenen": temiz, "uyarilar": uyarilar}


def _redact_flags(fitz) -> dict:
    kw = {}
    for name, const in (("images", "PDF_REDACT_IMAGE_PIXELS"), ("graphics", "PDF_REDACT_LINE_ART_REMOVE_IF_COVERED")):
        if hasattr(fitz, const):
            kw[name] = getattr(fitz, const)
    return kw


_COVER_STROKE = {"Line", "Ink", "PolyLine", "Polygon"}
_COVER_FILL = {"Square", "Circle", "Polygon"}


def _quads(fitz, v) -> list:
    pts = [fitz.Point(p) for p in v]
    return [fitz.Quad(*pts[i:i + 4]) for i in range(0, len(pts) - 3, 4)]


def _covering_annot_rects(fitz, a) -> list:
    """Sayfadaki içeriği örten açıklamalar (elle karartma için kalın çizgi/mürekkep, dolu kutu,
    damga): silinirse altındaki imza/veri açığa çıkar. Kapladıkları alan karartma olarak uygulanır
    (görüntü pikselleri de silinir). Çizgi/mürekkepte her parça kalınlığıyla ayrı kutu olur."""
    kind = a.type[1]
    try:
        width = float(a.border.get("width") or 0)
    except Exception:
        width = 0.0
    fill = bool((a.colors or {}).get("fill"))
    if kind == "Stamp" or (kind in _COVER_FILL and fill):
        return [a.rect]
    if kind == "Highlight":                 # siyah/koyu vurgulama (Multiply) metni örter
        st = (a.colors or {}).get("stroke") or []
        lum = (0.3 * st[0] + 0.59 * st[1] + 0.11 * st[2]) if len(st) == 3 else (st[0] if st else 1.0)
        op = a.opacity if a.opacity is not None and a.opacity >= 0 else 1.0
        if lum < 0.35 and op >= 0.5:
            try:
                quads = [q.rect for q in (a.vertices and _quads(fitz, a.vertices)) or []]
            except Exception:
                quads = []
            return quads or [a.rect]
        return []
    if kind not in _COVER_STROKE or width < 2:
        return []
    out = []
    try:
        v = a.vertices or []
    except Exception:
        v = []
    strokes = v if v and isinstance(v[0], (list, tuple)) and v[0] and isinstance(v[0][0], (list, tuple)) else [v]
    h = width / 2 + 1
    for st in strokes:
        pts = [fitz.Point(p) for p in st]
        if len(pts) == 1:
            pts = pts * 2
        for p0, p1 in zip(pts, pts[1:]):
            r = fitz.Rect(min(p0.x, p1.x) - h, min(p0.y, p1.y) - h, max(p0.x, p1.x) + h, max(p0.y, p1.y) + h)
            out.append(r)
    return out or [a.rect]


def _write_labels(fitz, page, labels) -> None:
    """Kapatılan kutulara yer tutucu (`[TC_NO]`, `[İMZA]` …): siyah kutunun içine koyu gri yazı, gerçek
    metin olarak (metin katmanında). Model/okuyan orada neyin kapatıldığını bilir. Aynı yeri örten
    kutulardan yalnız biri yazılır; kutu dar ise yazı küçülür (en az 3 pt)."""
    if not labels:
        return
    font = fitz.Font("helv")
    from .raster import LABEL_GRAY
    g = LABEL_GRAY / 255.0                # koyu gri: yeniden taramada kutu tek parça blok kalır (bkz. raster)
    tw = fitz.TextWriter(page.rect, color=(g, g, g))
    done: list = []
    for r, text in labels:
        r = fitz.Rect(r)
        if r.is_empty or r.width < 1 or r.height < 1:
            continue
        if any((r & d).get_area() >= 0.5 * min(r.get_area(), d.get_area()) for d in done):
            continue
        done.append(r)
        size = min(r.height * 0.8, 14.0)
        tl = font.text_length(text, fontsize=size)
        if tl > r.width * 0.96:
            size = max(3.0, size * r.width * 0.96 / tl)
            tl = font.text_length(text, fontsize=size)
        x = r.x0 + max(0.0, (r.width - tl) / 2)
        y = r.y0 + (r.height + size * 0.7) / 2
        try:
            tw.append(fitz.Point(x, y), text, font=font, fontsize=size)
        except Exception:
            continue
    try:
        tw.write_text(page)
    except Exception:
        pass


def _rect_list(r) -> list:
    return [float(r[0]), float(r[1]), float(r[2]), float(r[3])]


def ps_bolgeleri(sn: int, ps: dict, page_box) -> list[dict]:
    """`raster.scan_pdf_page` çıktısı → bölgeler (sayfa koordinatı). İç alanlar: `_etiket` (yer tutucu)."""
    from . import bolge as BG
    out = []
    turler = ps.get("turler") or [None] * len(ps["kutular"])
    meta = ps.get("meta") or {}
    for i, (r, k) in enumerate(zip(ps["kutular"], turler)):
        if k == "etiket_alani":
            m = meta.get(i) or {}
            b = BG.yeni(sn, _rect_list(r), "el_yazisi_alan", BG.KAPATILDI, m.get("neden") or "kişisel veri etiketinin alanı",
                        m.get("kaynak") or "etiket_alani", m.get("guven") or 0.7)
        else:
            b = BG.yeni(sn, _rect_list(r), "kisisel_veri", BG.KAPATILDI, f"desen: {k or 'kişisel veri'}",
                        "ocr_deseni", 0.9)
        b["_etiket"] = PLACEHOLDERS.get(k, "[MASKELI]")
        out.append(b)
    for rect, e in ps.get("el_yazisi") or []:      # m3 (alan.el_yazisi_bolgeleri)
        b = BG.yeni(sn, _rect_list(rect), "el_yazisi_alan", e.get("karar") or BG.ONAY,
                    e.get("neden") or "el yazısı alan", e.get("kaynak") or "etiket_alani", e.get("guven") or 0.5)
        b["_etiket"] = "[KİŞİSEL VERİ]"
        out.append(b)
    imza_fn = BG.saglayici("imza")
    if imza_fn is None:                    # m1 bağlantı noktası yoksa eski imza çözümlemesinin çıktısı
        for r in ps["imza_kutular"]:
            b = BG.yeni(sn, _rect_list(r), "imza", BG.KAPATILDI, "imza etiketi/unvan yakınında mürekkep",
                        "imza_aday", 0.6)
            b["_etiket"] = IMZA_LABEL
            out.append(b)
        for r, how in ps.get("imza_aday_kutular") or []:
            if how == "metin":
                b = BG.yeni(sn, _rect_list(r), "imza", BG.ONAY, "metinle örtüşen imza: kapatılmadı",
                            "imza_metin", 0.5)
            else:
                b = BG.yeni(sn, _rect_list(r), "imza", BG.ONAY, "etiketsiz imza benzeri mürekkep",
                            "imza_etiketsiz", 0.3)
            b["_etiket"] = IMZA_LABEL
            out.append(b)
    if ps.get("taranamadi"):
        b = BG.yeni(sn, _rect_list(page_box), "okunamayan_sayfa", BG.ONAY, f"okunamadı: {ps['taranamadi']}"[:160],
                    "ocr", 0.0)
        b["_etiket"] = "[MASKELI]"
        out.append(b)
    return out


def _hook_bolgeleri(ad: str, sn: int, *args) -> list[dict]:
    from . import bolge as BG
    fn = BG.saglayici(ad)
    if fn is None:
        return []
    try:
        res = fn(*args) or []
    except Exception:                       # sağlayıcı hatası tespiti düşürmesin: kalan sorunu yeniden tarama yakalar
        return []
    out = []
    for b in res:
        b = dict(b)
        b.setdefault("sayfa", sn)
        b.setdefault("karar", BG.KAPATILDI)
        b.setdefault("guven", 0.5)
        b.setdefault("_etiket", IMZA_LABEL if b.get("tur") == "imza" else "[MASKELI]")
        out.append(b)
    return out


def kullaniciyla_ortusen_oneriyi_at(regs: list[dict]) -> list[dict]:
    """Kullanıcının çizdiği bölgeyle örtüşen şablon önerisi (aynı çizimden öğrenilen, aynı belgede) atılır:
    karar zaten verilmiş, yeniden sorulmaz."""
    from . import bolge as BG
    kul = [b["kutu"] for b in regs if b.get("kaynak") == BG.KULLANICI]
    if not kul:
        return regs
    return [b for b in regs if not (b.get("kaynak") == "sablon" and b.get("karar") == BG.ONAY
                                    and any(BG.ortusme(b["kutu"], k) >= 0.5 for k in kul))]


def _birakilabilir(b: dict) -> bool:
    """Otomatik kapatılan bölgeyi insan "birak" diyebilir mi: yalnız imza (yanlış alarm). Desen ve etiket
    alanı bulguları kural ayarıyla değişir (yeniden tarama yine bulur)."""
    return b["tur"] == "imza" or b["karar"] != "kapatildi"


def _kararla(bg, sn: int, regs: list[dict], ilk: bool = True) -> list[dict]:
    """Kimlik + karar; desen bulgusuna verilen "birak" uygulanmaz (uyarı)."""
    from . import bolge as BG
    once = {id(b): b["karar"] for b in regs}
    bg.sayfa(sn, regs, ilk=ilk)
    for b in regs:
        if once[id(b)] == BG.KAPATILDI and b["karar"] == BG.BIRAKILDI and b["tur"] != "imza" \
                and not getattr(bg, "yalniz_oneri", False):     # yalnız öneri: insan "açık kalsın" dedi
            b["karar"] = BG.KAPATILDI
            b.pop("insan", None)
            bg.uyarilar.append(f"{b['id']}: desen/etiket alanı bulgusu 'birak' ile açılamaz (kapatıldı)")
    return regs


def _acik_oneriyle_ortusur(bg, sn: int, b: dict) -> bool:
    """Yalnız öneri kipi: yeniden taramanın adayı bu sayfanın açık bir önerisiyle örtüşüyor (aynı bulgu kapatılmadığı
    için yeniden bulundu): yeni bölge açılmaz."""
    from . import bolge as BG
    return any(o["karar"] == BG.ONAY and o["sayfa"] == sn and BG.ortusme(o["kutu"], b["kutu"]) >= 0.5
               for o in bg.bolgeler)


def _yamalari_bas(page, yamalar) -> None:
    """m1 renk ayırma: beyaz karartmadan (alttaki görüntü pikselleri silinir) sonra mürekkebi
    beyazlatılmış kırpıntı aynı kutuya basılır (alttaki siyah basılı metin görünür kalır)."""
    for r, png in yamalar or []:
        try:
            page.insert_image(r, stream=png)
        except Exception:
            pass


def kapanir(b: dict) -> bool:
    """Bölgenin kutusu maskeli kopyada kapatılır mı: `kapatildi`, ya da kutusu kapalı tutulan onay bölgesi
    (metinle örtüşen imza; ad yalnız OCR'dan: "geri basma gerekli mi" onayı)."""
    return b["karar"] == "kapatildi" or (b["karar"] == "onay_bekliyor" and bool(b.get("kapali")))


YAMA_SIYAH_ORTUSME = 0.5     # yama kutusunun bu payı siyah kapatmanın altındaysa yama basılmaz (kutu siyah olur)


def _ortusme_payi(r, kutular) -> float:
    """`r`'nin (fitz.Rect) `kutular` altında kalan alan payı (kesişimler toplamı, en çok 1)."""
    a = r.get_area() or 1.0
    return min(1.0, sum((r & k).get_area() for k in kutular if r.intersects(k)) / a)


def _kapat_turu(fitz, page, bolgeler: list[dict], siyahlar: list, labels: list, flags: dict) -> int:
    """Bir turun kapatması. Siyah kapatma HER ZAMAN en son ve en üstte: önce renk ayırma yamalarının beyaz
    karartması ve yamaları, sonra bu turun siyah kutuları ve yamanın değdiği önceki siyah kutular yeniden
    (yamanın siyahla örtüşen kısmı kırpılır). Siyahla çoğunlukla örtüşen yama hiç basılmaz, kutu siyah olur.
    `siyahlar` (fitz.Rect) yerinde büyür. → kapatılan imza bölgesi sayısı."""
    siyah_yeni = [fitz.Rect(*p) for b in bolgeler if not b.get("_yama") for p in (b.get("parcalar") or [b["kutu"]])]
    beyaz = []
    n = 0
    for b in bolgeler:
        r = fitz.Rect(*b["kutu"])
        if b.get("parcalar") and not b.get("_yama"):
            if b["tur"] == "imza":       # daraltılmış kapatma: yer tutucu yazılmaz (altındaki ad/unvan okunur kalsın)
                n += 1
            continue
        if b.get("_yama"):
            if _ortusme_payi(r, siyahlar + siyah_yeni) >= YAMA_SIYAH_ORTUSME and b.get("_yedek"):
                # yama siyahla çoğunlukla örtüşüyor: bütün kutu değil, basılı metinden kırpılmış yedek zarf kapatılır
                # (koruma her yolda geçerli); yedek yoksa yama basılır (siyah kapatma zaten en üstte kalır)
                b.pop("_yama", None)
                b["neden"] += "; renk ayırma yaması siyah kapatmayla örtüştü: korumalı zarf siyah kapatıldı"
                b["parcalar"] = [list(p) for p in b["_yedek"]]
                siyah_yeni += [fitz.Rect(*p) for p in b["parcalar"]]
            else:
                beyaz.append((r, b["_yama"]))
        else:
            labels.append((r, b.get("_etiket") or "[MASKELI]"))
        if b["tur"] == "imza":
            n += 1
    if beyaz:
        for r, _ in beyaz:
            page.add_redact_annot(r, fill=(1, 1, 1))
        page.apply_redactions(**flags)
        _yamalari_bas(page, beyaz)
    tekrar = [k for k in siyahlar if any(k.intersects(r) for r, _ in beyaz)]
    for r in siyah_yeni + tekrar:
        page.add_redact_annot(r, fill=(0, 0, 0))
    if siyah_yeni or tekrar:
        page.apply_redactions(**flags)
    siyahlar += siyah_yeni
    return n


YENIDEN_TARAMA_ICINDE = 0.9   # yeniden taramada mevcut kapatılmış kutunun içinde kalan aday atlanır


def _icinde_payi(k, kutular) -> float:
    """`k`'nın (liste) `kutular` (liste) içinde kalan en büyük payı (kesişim / k alanı)."""
    from . import bolge as BG
    a = BG.alan(k) or 1e-6
    best = 0.0
    for o in kutular:
        ix = min(k[2], o[2]) - max(k[0], o[0])
        iy = min(k[3], o[3]) - max(k[1], o[1])
        if ix > 0 and iy > 0:
            best = max(best, ix * iy / a)
    return best


def mask_pdf_pymupdf(src: Path, dst: Path, rules: MaskRules, bolge=None) -> dict:   # pragma: no cover - isteğe bağlı
    from . import bolge as BG
    from . import raster
    fitz = _fitz()
    doc = fitz.open(str(src))
    if doc.needs_pass:
        raise MaskError("şifreli PDF")
    bg = bolge if bolge is not None else BG.Baglam("00000000")
    counts: Counter = Counter()
    temiz = set()
    uyarilar = []
    imza_bolge = ortusen = 0
    kapsam: dict[int, dict] = {}                  # sayfa → kapatılan tür sayıları (el yazısı denetimi)
    sayfa_kutu: dict[int, list] = {}
    sayfalar: list = []
    olcum: dict[int, dict] = {}                   # sayfa → aşırı kapatma ölçümü
    flags = _redact_flags(fitz)
    for page in doc:
        sn = page.number + 1
        cover = []
        for a in list(page.annots() or []):
            rects = _covering_annot_rects(fitz, a)
            if rects:                 # kapatan işaretleme: altındaki içerik açığa çıkmasın
                cover += rects
                temiz.add("kapatan_isaretleme")
            if a.type[0] == getattr(fitz, "PDF_ANNOT_REDACT", 12):
                continue              # uygulanmamış karartma: apply_redactions uygular
            page.delete_annot(a)
            temiz.add("yorum_aciklama")
        for r in cover:
            page.add_redact_annot(r, fill=(0, 0, 0))
        if cover:
            page.apply_redactions(**flags)    # imza çözümlemesi örtülü hâli görsün
        for wdg in list(page.widgets() or []):
            page.delete_widget(wdg)
            temiz.add("form")
        # görüntü katmanı: OCR'lanan sayfa (taranmış / tam sayfa görüntü) ve imza bölgeleri
        try:
            ps = raster.scan_pdf_page(page, rules)
        except Exception as e:   # yeniden tarama karar verir
            ps = {"bulgular": Counter(), "kutular": [], "imza": None, "imza_kutular": []}
            uyarilar.append(f"s.{sn}: görüntü katmanı işlenemedi ({type(e).__name__})")
        alanlar = list(ps.get("alanlar") or [])
        kelimeler0 = [tuple(w[:4]) for w in page.get_text("words") if sum(c.isalpha() for c in w[4]) >= 3]
        kelimeler0 += [tuple(r) for r in ps.get("basili_kelimeler") or []]
        regs = [dict(BG.yeni(sn, _rect_list(r), "kisisel_veri", BG.KAPATILDI, "içeriği örten işaretleme",
                             "kapatan_isaretleme", 1.0), _uygulandi=True) for r in cover]
        regs += ps_bolgeleri(sn, ps, page.rect)
        if ps["imza"] is not None:
            ortusen += ps["imza"].ortusen_kelime
        page_counts: Counter = Counter()
        text = page.get_text("text")
        for f in detect(text, rules):
            page_counts[f.kind] += 1
            frag = text[f.start:f.end]
            found = False
            for part in [p.strip() for p in re.split(r"[\r\n]+", frag) if p.strip()]:
                for r in page.search_for(part):
                    b = BG.yeni(sn, _rect_list(r), "kisisel_veri", BG.KAPATILDI, f"desen: {f.kind}", "metin_deseni", 0.95)
                    b["_etiket"] = PLACEHOLDERS.get(f.kind, f"[{f.kind.upper()}]")
                    regs.append(b)
                    found = True
            if not found:
                uyarilar.append(f"s.{sn}: bulgu konumu bulunamadı ({f.kind})")
        regs += _hook_bolgeleri("imza", sn, page, rules, ps)
        regs += bg.kullanici_bolgeleri(sn)
        regs = kullaniciyla_ortusen_oneriyi_at(regs)
        _kararla(bg, sn, regs)
        try:                              # "kapat" kararlı bölge: mürekkep bileşenlerini tümüyle örtsün
            raster.pdf_kapat_genislet(page, regs)
        except Exception as e:            # noqa: BLE001 — genişletilemedi: kararın kutusu kapanır
            uyarilar.append(f"s.{sn}: kapat kutusu genişletilemedi ({type(e).__name__})")
        labels: list = []                 # (dikdörtgen, yer tutucu): kapatmadan sonra metin katmanına yazılır
        siyahlar: list = [fitz.Rect(*b["kutu"]) for b in regs if b.get("_uygulandi")]
        imza_bolge += _kapat_turu(fitz, page, [b for b in regs if kapanir(b) and not b.get("_uygulandi")],
                                  siyahlar, labels, flags)
        for k, n in ps["bulgular"].items():          # metin katmanı + OCR aynı bulguyu iki kez saymasın
            page_counts[k] = max(page_counts[k], n)
        counts.update(page_counts)
        page_kapsam = Counter(page_counts)
        # kapatma çevreyi değiştirir (küme ayrışır, yeni vuruş belirginleşir): imza/OCR bulgusu
        # kalmayana kadar en çok iki tur daha (yalnız otomatik kapatılanlar; adaylar yeniden taramada).
        # Zaten kapatılmış kutunun içinde kalan aday (aynı kutu, geri basılan yazısıyla yeniden bulunur)
        # yeni bölge olmaz.
        again = any(kapanir(b) and b["kaynak"] not in ("metin_deseni", "kapatan_isaretleme", "kullanici")
                    for b in regs)
        for _ in range(2):
            if not again:
                break
            try:
                ps = raster.scan_pdf_page(page, rules)
            except Exception:
                break
            kapali = [b["kutu"] for b in bg.bolgeler if b["sayfa"] == sn and kapanir(b)]
            more = [b for b in ps_bolgeleri(sn, ps, page.rect) if b["karar"] == BG.KAPATILDI]
            more += [b for b in _hook_bolgeleri("imza", sn, page, rules, ps) if kapanir(b)]
            more = [b for b in more if not any(o["karar"] == BG.BIRAKILDI and BG.ortusme(o["kutu"], b["kutu"]) >= 0.5
                                               for o in bg.bolgeler if o["sayfa"] == sn)
                    and _icinde_payi(b["kutu"], kapali) < YENIDEN_TARAMA_ICINDE
                    and not (bg.yalniz_oneri and _acik_oneriyle_ortusur(bg, sn, b))]
            if not more:
                break
            _kararla(bg, sn, more, ilk=False)
            imza_bolge += _kapat_turu(fitz, page, [b for b in more if kapanir(b)], siyahlar, labels, flags)
            if ps["imza"] is not None:
                ortusen += ps["imza"].ortusen_kelime
            for k, n in ps["bulgular"].items():
                if k != "etiket_alani":
                    page_kapsam[k] += n
            alanlar += list(ps.get("alanlar") or [])
            counts["etiket_alani"] += ps["bulgular"].get("etiket_alani", 0)
        _write_labels(fitz, page, labels)
        from .raster import KASITLI_KAYNAK, KASITLI_TUR, asiri_kapatma
        kasitli = [b["kutu"] for b in bg.bolgeler if b["sayfa"] == sn and (b["tur"] in KASITLI_TUR
                                                                            or b["kaynak"] in KASITLI_KAYNAK)]
        olcum[sn] = asiri_kapatma(kelimeler0, [tuple(r) for r in siyahlar], kasitli, abs(page.rect.get_area()))
        from .raster import bolge_olcumu
        for b in bg.bolgeler:             # bölge düzeyinde ölçüm: her kapatılan bölgeye
            if b["sayfa"] == sn and kapanir(b) and "kapatma_olcumu" not in b:
                b["kapatma_olcumu"] = bolge_olcumu(b.get("parcalar") or [b["kutu"]], kelimeler0,
                                                   abs(page.rect.get_area()),
                                                   b["tur"] in KASITLI_TUR or b["kaynak"] in KASITLI_KAYNAK)
        from .raster import page_coverage
        kapsam[page.number + 1] = dict(page_coverage(page_kapsam, alanlar))
        sayfa_kutu[sn] = _rect_list(page.rect)
        sayfalar.append(sayfa_bilgisi(page))
    if doc.metadata and any(doc.metadata.values()):
        temiz.add("ust_veri")
    doc.set_metadata({})
    try:
        doc.del_xml_metadata()
        temiz.add("xmp")
    except Exception:
        pass
    for n in list(doc.embfile_names()):
        doc.embfile_del(n)
        temiz.add("ekler_ve_adlar")
    if doc.get_toc():
        doc.set_toc([])
        temiz.add("yer_imleri")
    dst.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(dst), garbage=4, deflate=True, clean=True)
    doc.close()
    # PyMuPDF'in dokunmadığı katalog girdileri (yapı ağacı vb.): pypdf ile ikinci geçiş
    from pypdf import PdfReader, PdfWriter
    _quiet_pypdf()
    w = PdfWriter(clone_from=PdfReader(str(dst)))
    temiz |= set(_clean_pdf_writer(w))
    w = _rebuild(w)
    buf = io.BytesIO()
    w.write(buf)
    dst.write_bytes(buf.getvalue())
    return {"maskelenen": counts, "temizlenen": sorted(temiz), "uyarilar": uyarilar,
            "imza_bolgesi": imza_bolge, "ortusen_kelime": ortusen, "sayfa_sayisi": len(kapsam),
            "sayfa_kapsam": kapsam, "bolgeler": bg.bolgeler, "sayfa_kutulari": sayfa_kutu,
            "sayfalar": sayfalar, "kapatma_olcumu": olcum}


def sayfa_bilgisi(page) -> dict:
    """Sayfa boyutu (görüntülenen, pt; sol üst köken) ve bölge kutusunu (döndürülmemiş sayfa koordinatı)
    görüntülenen sayfaya çeviren matris (`/Rotate`'li sayfada birim değil)."""
    m = page.rotation_matrix
    return {"no": page.number + 1, "genislik": round(page.rect.width, 2), "yukseklik": round(page.rect.height, 2),
            "donus": int(page.rotation), "matris": [round(float(v), 4) for v in (m.a, m.b, m.c, m.d, m.e, m.f)]}


def _iter_indirect(reader):
    from pypdf.generic import IndirectObject
    seen = set()
    for gen, d in (reader.xref or {}).items():
        for num in d:
            seen.add((num, gen))
    for num in (getattr(reader, "xref_objStm", None) or {}):
        seen.add((num, 0))
    for num, gen in sorted(seen):
        try:
            yield reader.get_object(IndirectObject(num, gen, reader))
        except Exception:
            continue


def scan_pdf(path: Path, rules: MaskRules) -> dict:
    from pypdf import PdfReader
    from pypdf.generic import StreamObject
    _quiet_pypdf()
    reader = PdfReader(str(path))
    found: Counter = Counter()
    sorunlar: list[str] = []
    imza: list[str] = []
    if reader.is_encrypted:
        return {"bulgular": found, "sorunlar": ["sifreli"], "imza": imza, "taranamadi": ["şifreli"]}
    page_counts: list[Counter] = []
    page_text_len: list[int] = []
    for i, page in enumerate(reader.pages, 1):
        try:
            t = page.extract_text() or ""
        except Exception:
            t = ""
            sorunlar.append(f"s.{i}: metin çıkarılamadı")
        pc = Counter(f.kind for f in detect(t, rules))
        page_counts.append(pc)
        page_text_len.append(len(t.strip()))
        found.update(pc)
        if page.get("/Annots"):
            sorunlar.append("yorum_aciklama")
        if _has_imza(t) and _page_has_image(page):
            imza.append(f"s.{i}")
    meta = reader.metadata or {}
    mtext = "\n".join(str(v) for v in meta.values() if v)
    for f in detect(mtext, rules):
        found[f.kind] += 1
    if any(str(meta.get(k) or "").strip() for k in ("/Author", "/Title", "/Subject", "/Keywords")):
        sorunlar.append("ust_veri")
    root = reader.trailer["/Root"].get_object()
    for key, tag in (("/Metadata", "xmp"), ("/AcroForm", "form"), ("/Outlines", "yer_imleri")):
        if key in root:
            sorunlar.append(tag)
    names = root.get("/Names")
    if names is not None and "/EmbeddedFiles" in names.get_object():
        sorunlar.append("ek_dosya")
    raw_rules = _sub_rules(rules, RAW_KINDS)
    raw: Counter = Counter()
    for obj in _iter_indirect(reader):
        if not isinstance(obj, StreamObject):
            continue
        if obj.get("/Subtype") in ("/Image", "/Type1C", "/CIDFontType0C", "/OpenType") or "/Length1" in obj \
                or "/N" in obj:
            continue
        try:
            data = obj.get_data()
        except Exception:
            continue
        # içerik akışındaki onaltılık dizeler (<0A1B…>) glif kodudur: içindeki rakam dizileri
        # okunabilir metin değildir (T.C. algoritmasını tesadüfen tutan yanlış pozitif)
        for f in detect(_HEX_STR.sub(lambda m: " " * len(m.group()), data.decode("latin-1")), raw_rules):
            raw[f.kind] += 1
    for k, n in raw.items():                      # ham akışta kalan: metin çıkarımının kaçırdığı
        found[k] = max(found[k], n)
    ras = _scan_pdf_raster(path, rules, reader, page_counts, page_text_len)
    found.update(ras["ek"])
    sorunlar += ras["sorunlar"]
    for s in ras["imza"]:
        if s not in imza:
            imza.append(s)
    out = {"bulgular": found, "sorunlar": sorted(set(sorunlar)), "imza": imza,
           "taranamadi": ras["taranamadi"], "imza_aday": ras["imza_aday"], "imza_elle": ras["imza_elle"],
           "imza_metin": ras["imza_metin"]}
    if ras.get("bolge_adaylari") is not None:
        out["bolge_adaylari"] = ras["bolge_adaylari"]
    return out


def _render_pdftoppm(path: Path, pageno: int, dpi: int):
    """PyMuPDF yoksa sayfa görüntüsü: pdftoppm (poppler) ile."""
    import shutil
    import subprocess
    from PIL import Image
    if not shutil.which("pdftoppm"):
        raise MaskError("pdftoppm yok")
    from bidr.ingest.ocr import _env, _tempdir
    with _tempdir("bidr-maske-") as td:
        prefix = Path(td) / "p"
        r = subprocess.run(["pdftoppm", "-r", str(dpi), "-png", "-f", str(pageno), "-l", str(pageno),
                            "-singlefile", str(path), str(prefix)], capture_output=True, timeout=300, env=_env())
        img = prefix.with_suffix(".png")
        if r.returncode != 0 or not img.exists():
            raise MaskError("pdftoppm sayfayı çizemedi")
        im = Image.open(str(img))
        im.load()
        return im.convert("RGB")


def _scan_pdf_raster(path: Path, rules: MaskRules, reader, page_counts, page_text_len) -> dict:
    """Görüntü katmanı taraması: OCR gereken sayfalar (metinsiz / tam sayfa görüntü) ve imza.
    → {"ek": metin katmanının ötesinde OCR bulguları, "sorunlar", "imza", "taranamadi",
    "imza_aday": kapatılmamış etiketli imza adayı, "imza_elle": etiketsiz aday sayfaları}."""
    from . import raster
    out = {"ek": Counter(), "sorunlar": [], "imza": [], "taranamadi": [], "imza_aday": 0, "imza_elle": [],
           "imza_metin": []}
    fitz = _fitz()

    def take(i, ocr_c: Counter, res, tar):
        for k, n in ocr_c.items():
            if n > page_counts[i][k]:
                out["ek"][k] += n - page_counts[i][k]
        if tar:
            out["taranamadi"].append(f"s.{i + 1}: {tar}")
        if res is not None:
            if res.etiketli or res.etiketsiz:
                out["imza"].append(f"s.{i + 1}")
            out["imza_aday"] += res.etiketli
            if res.etiketsiz:
                out["imza_elle"].append(f"s.{i + 1}")
            if res.elle_bolge:
                out["imza_metin"].append(f"s.{i + 1}")

    if fitz is not None:
        from . import bolge as BG
        out["bolge_adaylari"] = []
        doc = fitz.open(str(path))
        try:
            for i, page in enumerate(doc):
                ps = raster.scan_pdf_page(page, rules)
                take(i, ps["bulgular"], ps["imza"], ps["taranamadi"])
                for b in ps_bolgeleri(i + 1, ps, page.rect):
                    if b["tur"] == "imza" and b["karar"] == BG.KAPATILDI:   # kapatılmamış etiketli aday
                        b.update(karar=BG.ONAY, neden="maskeli kopyada kapatılmamış imza adayı", kaynak="imza_kalan")
                    if b["karar"] == BG.ONAY:
                        b.pop("_etiket", None)
                        out["bolge_adaylari"].append(b)
        finally:
            doc.close()
    else:
        for i, page in enumerate(reader.pages):
            if page_text_len[i] >= 20:
                continue          # PyMuPDF yok: yalnız metinsiz sayfalar görüntüden taranır
            try:
                img = _render_pdftoppm(path, i + 1, 300)
            except Exception as e:
                take(i, Counter(), None, f"sayfa görüntüsü alınamadı ({e})"[:160])
                continue
            r = raster.analyze_image(img, 300, rules)
            take(i, r.bulgular, r.imza, r.taranamadi)
    if out["imza_elle"]:
        out["sorunlar"].append("imza: elle bakılmalı (" + ", ".join(out["imza_elle"]) + ")")
    if out["imza_metin"]:
        out["sorunlar"].append(IMZA_METIN_SORUN + " (" + ", ".join(out["imza_metin"]) + ")")
    return out


def _page_has_image(page) -> bool:
    try:
        res = page.get("/Resources")
        xo = res.get_object().get("/XObject") if res is not None else None
        if xo is not None:
            for v in xo.get_object().values():
                if v.get_object().get("/Subtype") == "/Image":
                    return True
        cs = page.get_contents()
        return cs is not None and any(op == b"INLINE IMAGE" or op == b"BI" for _, op in cs.operations)
    except Exception:
        return False


# ---------------------------------------------------------------- DOCX

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_DOCX_TEXT_PARTS = re.compile(r"^/word/(document|header\d*|footer\d*|footnotes|endnotes)\.xml$")
_DROP_PKG_RELS = ("custom-properties", "extended-properties", "thumbnail")
_DROP_DOC_RELS = ("comments", "commentsExtended", "commentsIds", "commentsExtensible", "people")


def _w(tag: str) -> str:
    return f"{{{W}}}{tag}"


def _nearest(el, tag):
    for a in el.iterancestors(tag):
        return a
    return None


def _mask_paragraph(p, rules: MaskRules, counts: Counter) -> None:
    chars: list[str] = []
    where: list[tuple | None] = []
    for el in p.iter(_w("t"), _w("tab"), _w("br"), _w("cr")):
        if _nearest(el, _w("p")) is not p:
            continue
        if el.tag == _w("t"):
            for j, c in enumerate(el.text or ""):
                chars.append(c)
                where.append((el, j))
        else:
            chars.append(" ")
            where.append(None)
    text = "".join(chars)
    fs = detect(text, rules)
    if not fs:
        return
    edits: dict = {}
    for f in fs:
        counts[f.kind] += 1
        first = True
        for i in range(f.start, f.end):
            w = where[i]
            if w is None:
                continue
            el, j = w
            buf = edits.setdefault(el, list(el.text or ""))
            buf[j] = PLACEHOLDERS.get(f.kind, "[?]") if first else ""
            first = False
    for el, buf in edits.items():
        el.text = "".join(buf)
        el.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")


def _drop_rels(rels, suffixes) -> bool:
    gone = False
    for rid, rel in list(rels.items()):
        if any(rel.reltype.endswith("/" + s) for s in suffixes):
            rels.pop(rid)
            gone = True
    return gone


def mask_docx(src: Path, dst: Path, rules: MaskRules, *, imza: bool = True) -> dict:
    """`imza`: gömülü görsellerde imza benzeri mürekkep kapatılsın mı (yalnız öneri kipinde insan kararıyla)."""
    import docx
    from docx.opc.part import XmlPart
    d = docx.Document(str(src))
    counts: Counter = Counter()
    temiz: set[str] = set()
    pkg = d.part.package
    # yorumlar: içerikteki kişisel veri sayılır, parça ve işaretler silinir
    for part in pkg.iter_parts():
        if isinstance(part, XmlPart) and re.search(r"/word/comments", str(part.partname)):
            for f in detect("\n".join(part._element.itertext()), rules):
                counts[f.kind] += 1
    for part in list(pkg.iter_parts()):
        if isinstance(part, XmlPart) and _drop_rels(part.rels, _DROP_DOC_RELS):
            temiz.add("yorumlar")
    for part in list(pkg.iter_parts()):
        if not (isinstance(part, XmlPart) and _DOCX_TEXT_PARTS.match(str(part.partname))):
            continue
        root = part._element
        for tag in ("commentRangeStart", "commentRangeEnd"):
            for el in list(root.iter(_w(tag))):
                el.getparent().remove(el)
        for el in list(root.iter(_w("commentReference"))):
            r = el.getparent()
            r.getparent().remove(r)
        # izlenen değişiklikler: silinen metin yayına girmez
        for tag in ("del", "moveFrom"):
            for el in list(root.iter(_w(tag))):
                if el.getparent() is not None and el.getparent().tag != _w("rPr"):
                    for f in detect("".join(el.itertext()), rules):
                        counts[f.kind] += 1
                    el.getparent().remove(el)
                    temiz.add("izlenen_degisiklikler")
        for p in root.iter(_w("p")):
            _mask_paragraph(p, rules, counts)
        for el in root.iter(_w("instrText")):
            if el.text:
                new, c = mask_text(el.text, rules)
                if c:
                    el.text = new
                    counts.update(c)
        for el in root.iter():               # öznitelikler: resim açıklaması, alan kodu, içerik denetimi …
            if not isinstance(el.tag, str):
                continue
            for attr, v in list(el.attrib.items()):
                if not v or _structural_attr(el, attr):
                    continue
                new, c = mask_text(v, rules)
                if c:
                    el.set(attr, new)
                    counts.update(c)
        for rel in part.rels.values():
            if rel.is_external:
                new, c = mask_text(rel.target_ref, rules)
                if c:
                    rel._target = new
                    counts.update(c)
    cp = d.core_properties
    for a in ("author", "last_modified_by", "title", "subject", "keywords", "comments", "category",
              "content_status", "identifier", "version"):
        try:
            if getattr(cp, a):
                temiz.add("ust_veri")
            setattr(cp, a, "")
        except Exception:
            pass
    if _drop_rels(pkg.rels, _DROP_PKG_RELS):
        temiz.add("ust_veri")
    body = "\n".join("".join(p._element.itertext()) for p in pkg.iter_parts()
                      if isinstance(p, XmlPart) and _DOCX_TEXT_PARTS.match(str(p.partname)))
    med = _mask_media_parts(pkg, rules, imza_label=_has_imza_label(body), imza=imza)
    counts.update(med["maskelenen"])
    dst.parent.mkdir(parents=True, exist_ok=True)
    d.save(str(dst))
    return {"maskelenen": counts, "temizlenen": sorted(temiz), "uyarilar": med["uyarilar"],
            "imza_bolgesi": med["imza_bolgesi"], "ortusen_kelime": med["ortusen_kelime"]}


_MEDIA_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/jpg": ".jpg", "image/tiff": ".tif",
                "image/bmp": ".bmp", "image/webp": ".webp"}


def _has_imza_label(text: str) -> bool:
    """Belgede imza etiketi var mı ("İmza", "İmzası", "İmza:" …; akış içindeki "imzalanmıştır" değil)."""
    return bool(re.search(r"(?i)(?<![\w])[iİı]mza(?:s[ıi]|lar[ıi]?)?(?![\w])", text))


def _media_images(pkg):
    for part in pkg.iter_parts():
        ext = _MEDIA_TYPES.get(getattr(part, "content_type", ""))
        if ext and "/media/" in str(part.partname):
            yield part, ext


def _mask_media_parts(pkg, rules: MaskRules, *, imza_label: bool, imza: bool = True) -> dict:
    """Gömülü görseller (docx word/media): OCR + desen kutuları; belgede imza etiketi varsa görseldeki
    imza benzeri mürekkep de kapatılır. OCR yoksa görsel olduğu gibi kalır (uyarı)."""
    from . import raster
    out = {"maskelenen": Counter(), "uyarilar": [], "imza_bolgesi": 0, "ortusen_kelime": 0}
    parts = list(_media_images(pkg))
    if not parts or (not imza and not rules.kinds):
        return out
    if not raster.ocr_available():
        out["uyarilar"].append(f"gömülü görseller ({len(parts)}) OCR olmadan taranamadı")
        return out
    for part, ext in parts:
        try:
            img = raster.open_image_bytes(part.blob)
            if min(img.width, img.height) < 24:
                continue
            r = raster.scan_image_obj(img, rules, flag_unlabeled=False, all_zone=imza_label)
        except Exception as e:
            out["uyarilar"].append(f"gömülü görsel işlenemedi: {type(e).__name__}")
            continue
        boxes = list(r.kutular) + list(r.imza.kapat if r.imza and imza else [])
        out["maskelenen"].update(r.bulgular)
        if r.imza and imza:
            out["imza_bolgesi"] += len(r.imza.kapat)
            out["ortusen_kelime"] += r.imza.ortusen_kelime
        if boxes:
            buf = io.BytesIO()
            raster.save_like(raster.draw_labels(raster.black_out(img, boxes), raster.label_items(r)), buf, ext)
            part._blob = buf.getvalue()
    return out


def _scan_media(path: Path, rules: MaskRules, imza_label: bool) -> dict:
    """Bağımsız tarama: docx içindeki görseller (OCR varsa)."""
    from . import raster
    out = {"bulgular": Counter(), "imza_aday": 0, "imza_metin": 0, "uyari": None}
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.startswith("word/media/")
                 and Path(n).suffix.lower() in raster.IMAGE_EXT]
        if not names:
            return out
        if not raster.ocr_available():
            out["uyari"] = "gömülü görseller OCR olmadan taranamadı"
            return out
        for n in names:
            try:
                img = raster.open_image_bytes(z.read(n))
                if min(img.width, img.height) < 24:
                    continue
                r = raster.scan_image_obj(img, rules, flag_unlabeled=False, all_zone=imza_label)
            except Exception:
                continue
            out["bulgular"].update(r.bulgular)
            if r.imza:
                out["imza_aday"] += r.imza.etiketli
                out["imza_metin"] += r.imza.elle_bolge
    return out


# ---------------------------------------------------------------- OOXML tarama (docx, xlsx)

_GROUP = {_w("p"), "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si",
          "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}is"}


_STRUCT_ATTRS = {"id", "paraId", "textId", "durableId", "anchorId", "editId", "embed", "link", "uri", "spid",
                 "styleId", "numId", "abstractNumId", "ilvl", "sz", "w", "h", "x", "y", "cx", "cy", "val"}


def _structural_attr(el, attr: str) -> bool:
    """Yapısal sayı öznitelikleri (nesne kimlikleri, rsid, boyut): kişisel veri değil, değiştirilirse
    belge bozulur. `name` yalnız Word'ün kendiliğinden verdiği "Resim 123" (kimliğiyle aynı sayı)
    biçimindeyse yapısal sayılır. `val` yalnız sayısal biçim öğelerinde yapısaldır."""
    local = attr.rsplit("}", 1)[-1]
    if "rsid" in local.lower():
        return True
    if local == "val":
        tag = el.tag.rsplit("}", 1)[-1] if isinstance(el.tag, str) else ""
        return tag not in ("alias", "tag", "docVar", "placeholder", "t", "dropDownList", "listItem", "date",
                           "comboBox", "default", "result", "helpText", "statusText", "name")
    if local == "name":
        tag = el.tag.rsplit("}", 1)[-1] if isinstance(el.tag, str) else ""
        if tag in ("cNvPr", "docPr"):
            m = re.fullmatch(r"\D*?\s*(\d+)", el.get(attr) or "")
            return bool(m and m.group(1) == (el.get("id") or ""))
        return False
    return local in _STRUCT_ATTRS


def _xml_texts(data: bytes) -> list[str]:
    """XML parçasının metinleri: paragraf/paylaşılan dize birleşik, kalan metin düğümleri ve
    öznitelik değerleri ayrı ayrı."""
    from lxml import etree
    try:
        root = etree.fromstring(data, parser=etree.XMLParser(resolve_entities=False, huge_tree=True))
    except etree.XMLSyntaxError:
        return [data.decode("utf-8", "replace")]
    groups: dict = {}
    order: list = []
    out: list[str] = []
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        for k, v in el.attrib.items():
            if not _structural_attr(el, k):
                out.append(v)
        if el.text and el.tag not in _GROUP:
            g = None
            for a in el.iterancestors():
                if a.tag in _GROUP:
                    g = a
                    break
            if g is None:
                out.append(el.text)
            else:
                if g not in groups:
                    groups[g] = []
                    order.append(g)
                groups[g].append(el.text)
    return ["".join(groups[g]) for g in order] + out


def _scan_ooxml(path: Path, rules: MaskRules) -> tuple[Counter, list[str], bool, str]:
    found: Counter = Counter()
    sorunlar: list[str] = []
    body = []
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        has_media = any(n.startswith(("word/media/", "xl/media/")) for n in names)
        for n in names:
            if not (n.endswith(".xml") or n.endswith(".rels")):
                continue
            texts = _xml_texts(z.read(n))
            for t in texts:
                for f in detect(t, rules):
                    found[f.kind] += 1
            if n.startswith(("word/document", "xl/sharedStrings", "xl/worksheets/")):
                body.extend(texts)
            if re.match(r"(word/comments|xl/comments|xl/threadedComments)", n):
                sorunlar.append("yorum")
            if n == "docProps/custom.xml":
                sorunlar.append("ust_veri")
            if n == "docProps/core.xml":
                from lxml import etree
                root = etree.fromstring(z.read(n))
                for el in root:
                    local = etree.QName(el).localname
                    if local in ("creator", "lastModifiedBy", "title", "subject", "keywords", "description") \
                            and (el.text or "").strip():
                        sorunlar.append("ust_veri")
            if re.match(r"word/(document|header|footer|footnotes|endnotes).*\.xml$", n) and b"<w:del " in z.read(n):
                sorunlar.append("izlenen_degisiklikler")
    return found, sorted(set(sorunlar)), has_media, "\n".join(body)


def scan_docx(path: Path, rules: MaskRules) -> dict:
    found, sorunlar, media, body = _scan_ooxml(path, rules)
    imza = ["belge"] if media and _has_imza(body) else []
    m = _scan_media(path, rules, _has_imza_label(body)) if media else {"bulgular": Counter(), "imza_aday": 0,
                                                                       "imza_metin": 0, "uyari": None}
    found.update(m["bulgular"])
    if m["imza_metin"]:
        sorunlar = sorted(set(sorunlar) | {IMZA_METIN_SORUN + " (gömülü görsel)"})
    return {"bulgular": found, "sorunlar": sorunlar, "imza": imza, "imza_aday": m["imza_aday"],
            "imza_metin": ["gömülü görsel"] if m["imza_metin"] else [],
            "uyarilar": [m["uyari"]] if m["uyari"] else []}


# ---------------------------------------------------------------- XLSX

def _mask_cell_value(v, rules: MaskRules, counts: Counter):
    if isinstance(v, str):
        new, c = mask_text(v, rules)
        counts.update(c)
        return new
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, int) or (isinstance(v, float) and v.is_integer() and abs(v) < 1e15):
        s = str(int(v))
        new, c = mask_text(s, rules)
        if c:
            counts.update(c)
            return new
    return v


def mask_xlsx(src: Path, dst: Path, rules: MaskRules) -> dict:
    import openpyxl
    keep_vba = src.suffix.lower() == ".xlsm"
    wb = openpyxl.load_workbook(str(src), keep_vba=keep_vba)
    counts: Counter = Counter()
    temiz: set[str] = set()
    uyarilar: list[str] = []
    with zipfile.ZipFile(src) as z:
        if any(n.startswith(("xl/media/", "xl/charts/", "xl/drawings/")) for n in z.namelist()):
            uyarilar.append("görsel/grafik/çizimler maskeli kopyada korunmaz (openpyxl)")
    titles = set()
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if cell.comment is not None:
                    for f in detect(cell.comment.text or "", rules):
                        counts[f.kind] += 1
                    cell.comment = None
                    temiz.add("yorumlar")
                v = cell.value
                if v is None:
                    continue
                new = _mask_cell_value(v, rules, counts)
                if new is not v and new != v:
                    cell.value = new
        for hf in (ws.oddHeader, ws.oddFooter, ws.evenHeader, ws.evenFooter, ws.firstHeader, ws.firstFooter):
            for part in (hf.left, hf.center, hf.right):
                if part.text:
                    new, c = mask_text(part.text, rules)
                    if c:
                        part.text = new
                        counts.update(c)
        new, c = mask_text(ws.title, rules)
        if c:
            counts.update(c)
            base = re.sub(r"[\[\]:*?/\\]", "", new)[:28] or "Sayfa"
            t, i = base, 1
            while t in titles or t in wb.sheetnames:
                i += 1
                t = f"{base[:26]}{i}"
            ws.title = t
        titles.add(ws.title)
    p = wb.properties
    for a in ("creator", "lastModifiedBy", "title", "subject", "keywords", "description", "category",
              "identifier", "contentStatus", "version"):
        if getattr(p, a, None):
            temiz.add("ust_veri")
            setattr(p, a, None)
    try:
        if len(wb.custom_doc_props.props):
            temiz.add("ust_veri")
        wb.custom_doc_props.props = []
    except Exception:
        pass
    dst.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(dst))
    return {"maskelenen": counts, "temizlenen": sorted(temiz), "uyarilar": uyarilar}


def scan_xlsx(path: Path, rules: MaskRules) -> dict:
    found, sorunlar, media, body = _scan_ooxml(path, rules)
    imza = ["belge"] if media and _has_imza(body) else []
    return {"bulgular": found, "sorunlar": sorunlar, "imza": imza}


# ---------------------------------------------------------------- düz metin

def _read_text(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1254"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1"), "latin-1"


def mask_textfile(src: Path, dst: Path, rules: MaskRules) -> dict:
    text, enc = _read_text(src)
    new, c = mask_text(text, rules)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(new, encoding="utf-8" if enc == "utf-8-sig" else enc)
    return {"maskelenen": c, "temizlenen": [], "uyarilar": []}


def scan_textfile(path: Path, rules: MaskRules) -> dict:
    text, _ = _read_text(path)
    return {"bulgular": Counter(f.kind for f in detect(text, rules)), "sorunlar": [], "imza": []}


# ---------------------------------------------------------------- HTML (kaydedilmiş web sayfası)

_HTML_BLOCK = {"p", "div", "li", "td", "th", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article",
               "header", "footer", "address", "dd", "dt", "blockquote", "pre", "span", "a", "caption", "label",
               "option", "button", "title"}


def _read_html(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    m = re.search(rb"""<meta[^>]+charset=["']?([\w-]+)""", raw[:4096], re.I)
    encs = ([m.group(1).decode("ascii", "ignore")] if m else []) + ["utf-8-sig", "cp1254"]
    for enc in encs:
        try:
            return raw.decode(enc), enc
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("latin-1"), "latin-1"


def mask_html(src: Path, dst: Path, rules: MaskRules) -> dict:
    """Metin, öznitelik (mailto:, title, alt, value …) maskelenir; betikler ve HTML yorumları silinir."""
    import lxml.html
    from lxml import etree
    text, enc = _read_html(src)
    doc = lxml.html.document_fromstring(text)
    counts: Counter = Counter()
    temiz: set[str] = set()
    for el in list(doc.iter(etree.Comment)):
        el.getparent().remove(el) if el.getparent() is not None else None
        temiz.add("yorum")
    for el in list(doc.iter("script", "noscript", "template")):
        for f in detect(el.text_content() or "", rules):
            counts[f.kind] += 1
        el.drop_tree()
        temiz.add("betik")
    for el in doc.iter():
        if not isinstance(el.tag, str):
            continue
        for attr in ("text", "tail"):
            v = getattr(el, attr)
            if v:
                new, c = mask_text(v, rules)
                if c:
                    setattr(el, attr, new)
                    counts.update(c)
        for k, v in list(el.attrib.items()):
            new, c = mask_text(v, rules)
            if c:
                el.set(k, new)
                counts.update(c)
    out = lxml.html.tostring(doc, encoding="unicode", method="html", doctype="<!DOCTYPE html>")
    dst.parent.mkdir(parents=True, exist_ok=True)
    w_enc = "utf-8" if enc in ("utf-8-sig", "latin-1") else enc
    dst.write_bytes(out.encode(w_enc, errors="xmlcharrefreplace"))
    return {"maskelenen": counts, "temizlenen": sorted(temiz), "uyarilar": []}


def scan_html(path: Path, rules: MaskRules) -> dict:
    import html as _html

    import lxml.html
    text, _ = _read_html(path)
    found: Counter = Counter()
    try:
        doc = lxml.html.document_fromstring(text)
    except Exception:
        doc = None
    if doc is not None:
        seen: list[str] = []
        for el in doc.iter():
            if not isinstance(el.tag, str):
                continue
            if el.tag in _HTML_BLOCK:            # öğeler arası bölünmüş değerler için birleşik metin
                seen.append(el.text_content() or "")
            seen += [v for v in el.attrib.values()]
            seen += [x for x in (el.text, el.tail) if x]
        # aynı bulgu iç içe öğelerde tekrar görülür: tür başına farklı değer sayısı
        uniq: dict = {}
        for t in seen:
            for f in detect(t, rules):
                uniq.setdefault(f.kind, set()).add(t[f.start:f.end])
        found = Counter({k: len(v) for k, v in uniq.items()})
    raw = Counter(f.kind for f in detect(_html.unescape(text), _sub_rules(rules, RAW_KINDS)))
    for k, n in raw.items():
        found[k] = max(found[k], n)
    return {"bulgular": found, "sorunlar": [], "imza": []}


# ---------------------------------------------------------------- görseller

def mask_image(src: Path, dst: Path, rules: MaskRules, bolge=None) -> dict:
    from . import raster
    return raster.mask_image(src, dst, rules, bolge=bolge)


def scan_image(path: Path, rules: MaskRules) -> dict:
    from . import raster
    return raster.scan_image(path, rules)


# ---------------------------------------------------------------- dağıtım

def kind_of(path: Path) -> str | None:
    e = path.suffix.lower()
    if e in PDF_EXT:
        return "pdf"
    if e in DOCX_EXT:
        return "docx"
    if e in XLSX_EXT:
        return "xlsx"
    if e in TEXT_EXT:
        return "metin"
    if e in IMAGE_EXT:
        return "gorsel"
    if e in HTML_EXT:
        return "html"
    return None


def mask_file(src: Path, dst: Path, rules: MaskRules, *, engine: str = "pypdf", bolge=None, imza: bool = True) -> dict:
    """`bolge`: `bolge.Baglam` (kimlik + insan kararları); PDF (PyMuPDF) ve görsellerde bölge listesi
    üretilir (`sonuç["bolgeler"]`), diğer biçimlerde bölge yoktur. `imza`: docx gömülü görsellerinde imza kapatma."""
    k = kind_of(src)
    if k == "pdf":
        if engine == "pymupdf":
            return mask_pdf_pymupdf(src, dst, rules, bolge=bolge)
        return mask_pdf_pypdf(src, dst, rules)
    if k == "docx":
        return mask_docx(src, dst, rules, imza=imza)
    if k == "xlsx":
        return mask_xlsx(src, dst, rules)
    if k == "gorsel":
        return mask_image(src, dst, rules, bolge=bolge)
    if k == "html":
        return mask_html(src, dst, rules)
    if k == "metin":
        return mask_textfile(src, dst, rules)
    raise MaskError(f"desteklenmeyen biçim: {src.suffix}")


def scan_file(path: Path, rules: MaskRules) -> dict:
    k = kind_of(path)
    if k == "pdf":
        return scan_pdf(path, rules)
    if k == "docx":
        return scan_docx(path, rules)
    if k == "xlsx":
        return scan_xlsx(path, rules)
    if k == "gorsel":
        return scan_image(path, rules)
    if k == "html":
        return scan_html(path, rules)
    if k == "metin":
        return scan_textfile(path, rules)
    raise MaskError(f"desteklenmeyen biçim: {path.suffix}")
