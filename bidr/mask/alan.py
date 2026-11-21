"""Kişisel veri etiketinin alanı (`etiket_alani`): taranmış form/dilekçede el yazısıyla doldurulmuş
değer OCR'la okunamaz, ama BASILI etiketi ("T.C. Kimlik No:", "Telefon:", "Öğrenci No" …) okunur.
Etiketin sağındaki (ya da tablo hücresinde alttaki) alan değer okunmasa da karartılır.

Yalnız OCR kelimeleriyle çalışır (taranmış / tam sayfa görüntülü PDF sayfası, görsel): metin
katmanlı sayfadaki basılı etiket ve değeri zaten metin desenleriyle yakalanır; kurumsal altlık
("Tel: 0262 …", web sayfası iletişim satırı) bu kurala girmez.

Yanlış pozitifi sınırlayan kurallar:

- yalnız açık kişisel veri etiketleri; **ad/soyad etiketi yoktur** (adlar maskelenmez).
  *Güçlü* etiketler yalnız kişiye ait olabilir (kimlik/pasaport no, öğrenci no, doğum tarihi/yeri,
  ev/yazışma/ikamet adresi, GSM/cep telefonu). *Zayıf* etiketler (telefon/tel, e-posta, adres)
  kurum iletişim bilgisinde de geçer: yalnız sayfada güçlü bir etiket varsa (form bağlamı) ya da
  alandaki mürekkep OCR'ın güvenle okuduğu basılı metin değilse (el yazısı) ve sayfanın üst/alt
  bandında (antet, altlık) değilse alınır;
- etiket biçimi: arkasında `:` (aynı ya da sonraki belirteçte) ya da satırın / tablo hücresinin
  başında; akan metin içindeki "öğrenci numarası …" alınmaz;
- alan boşsa (mürekkep yoksa) ya da zaten kapatılmışsa (çoğu koyu: yeniden tarama) alınmaz.

Alan geometrisi: etiket satır bandı (etiket yüksekliğine göre yukarı/aşağı genişletilmiş; el yazısı
basılı satırdan taşar), etiket bitiminden sağa bir sonraki etikete (`:` ile biten basılı belirteç;
önündeki bilinen form etiket sözcükleri dahil), dikey tablo çizgisine ya da sayfa kenarına kadar.
Etiketten hemen sonra dikey çizgi varsa (etiket hücresi) değer bir sonraki hücrededir. Adres
etiketlerinde alan bir-iki satır aşağı uzar (satır başında yeni bir etiket/başlık yoksa). İki nokta
üst üstesiz tablo etiketinin sağı boşsa değer alttaki hücrededir.

Değerler hiçbir yere yazılmaz; çıktı kutu ve etiket türüdür.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .ocr import Word

KIND = "etiket_alani"
PLACEHOLDER = "[KİŞİSEL VERİ]"

# (tür, güçlü mü, desen) — normalleştirilmiş satır metninde (Türkçe harfler katlanmış, küçük harf,
# noktalama silinmiş, belirteçler tek boşlukla). Uzun desen önce denenir.
_LABELS: list[tuple[str, bool, str]] = [
    ("tc_no", True, r"(?:t ?c ?)?kimlik (?:no|numarasi|numara)(?: ?pasaport (?:no|numarasi))?"),
    ("tc_no", True, r"pasaport (?:no|numarasi)(?: ?(?:t ?c ?)?kimlik (?:no|numarasi))?"),
    ("tc_no", True, r"tckn|tc no|t c no"),
    ("ogrenci_no", True, r"ogrenci (?:no|numarasi|numara)|ogr ?no|okul (?:no|numarasi)"),
    ("dogum_tarihi", True, r"dogum (?:yeri )?(?:ve )?tarihi|dogum yeri"),
    ("adres", True, r"(?:ev|ikamet|ikametgah|yazisma|tebligat|daimi|acik|posta) adres(?:i)?"),
    ("telefon", True, r"(?:gsm|cep)(?: ?tel(?:efon(?:u)?)?)?(?: (?:no|numarasi))?|ev tel(?:efon(?:u)?)?"),
    ("telefon", False, r"tel(?:efon)?(?: (?:no|numarasi))?"),
    ("eposta", False, r"e ?(?:posta|mail)(?: adresi)?"),
    ("adres", False, r"adres(?:i)?"),
]
_LABEL_RES = [(k, s, re.compile(rf"(?<![a-z0-9])(?:{p})(?![a-z0-9])")) for k, s, p in _LABELS]

# Bir sonraki etiketin önündeki (":" ile biten belirteçten geriye) form etiket sözcükleri: alan
# sınırı bunların başına çekilir. Bilinmeyen sözcükte durulur (yazılı değer etiket sayılmasın diye).
_FORM_WORDS = {
    "adi", "ad", "soyadi", "soyad", "unvani", "unvan", "uyruk", "uyrugu", "cinsiyet", "cinsiyeti", "okudugu",
    "donem", "sayisi", "hazirlik", "haric", "bitirdigi", "sinif", "sinifi", "genel", "not", "ortalamasi",
    "fakulte", "fakultesi", "ve", "bolum", "bolumu", "program", "programi", "basvuru", "tarihi", "tarih",
    "imza", "imzasi", "ogrencinin", "alan", "anabilim", "bilim", "dali", "gorevi", "birimi", "birim",
    "kayit", "yili", "sicil", "no", "e", "posta", "telefon", "tel", "adres", "adresi", "dogum", "yeri",
    "kimlik", "tc", "pasaport", "ogrenci", "numarasi", "il", "ilce", "ulke", "medeni", "hali", "kan",
    "grubu", "mezuniyet", "danisman", "danismani", "konu", "konusu", "aciklama", "sayi", "fax",
    "faks", "gsm", "cep", "web", "uyrugu", "baba", "anne", "ismi",
}

_FOLD = str.maketrans({"ı": "i", "İ": "i", "I": "i", "ğ": "g", "Ğ": "g", "ü": "u", "Ü": "u", "ş": "s",
                       "Ş": "s", "ö": "o", "Ö": "o", "ç": "c", "Ç": "c", "â": "a", "Â": "a", "î": "i",
                       "û": "u"})

TOP_BAND = 0.07          # sayfa üst bandı (antet): zayıf etiket alınmaz
BOTTOM_BAND = 0.08       # alt bant (altlık: adres/telefon/e-posta satırı)
DARK = 160               # mürekkep eşiği (gri; mavi tükenmez ~60)
UP, DOWN = 1.2, 1.0       # alan bandı: etiket yüksekliğinin katı (yukarı / aşağı)
DONE_DARK = 0.5          # alanın bu oranı koyuysa zaten kapatılmış sayılır
RULE_FILL = 0.9          # dikey tablo çizgisi: bant boyunca bu oranda koyu sütun
MIN_INK = 0.004          # alan mürekkep oranı alt sınırı (satır/sütun çizgileri hariç)


def norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", t.translate(_FOLD).lower())


@dataclass
class Field:
    kind: str                 # etiket türü (tc_no, telefon, eposta, ogrenci_no, adres, dogum_tarihi)
    box: tuple                # (x0, y0, x1, y1) görüntü pikseli
    strong: bool


def _split_colon(words: list[Word]) -> list[Word]:
    """"Telefon:...0532" gibi etiket + değer tek belirteçte: ':' sonrası ayrı belirteç (x orantılı)."""
    out = []
    for w in words:
        t = w.text
        i = t.find(":")
        if 0 < i < len(t) - 1 and sum(c.isalpha() for c in t[:i]) >= 2:
            n = len(t)
            # harf oranıyla bölüm değerin başını etikete katabilir (el yazısı geniş, noktalar dar):
            # etiket genişliği basılı yazı ölçüsüyle (~0,5 × yükseklik / harf) sınırlanır
            xm = min(w.x0 + (w.x1 - w.x0) * (i + 1) / n, w.x0 + 0.5 * max(w.h, 8) * (i + 1))
            out.append(Word(t[:i + 1], w.conf, w.x0, w.y0, xm, w.y1, w.line))
            out.append(Word(t[i + 1:], w.conf, xm, w.y0, w.x1, w.y1, w.line))
        else:
            out.append(w)
    return out


def _tess_lines(words: list[Word]) -> list[list[Word]]:
    """tesseract satırları (x sıralı)."""
    d: dict = {}
    for w in words:
        d.setdefault(w.line, []).append(w)
    return [sorted(v, key=lambda w: w.x0) for v in d.values()]


def _form_word(w: Word, conf: float = 80) -> bool:
    return w.conf >= conf and len(norm(w.text)) >= 2 and norm(w.text) in _FORM_WORDS


def _colon_word(w: Word) -> bool:
    t = w.text.rstrip(".)")
    return w.conf >= 55 and t.endswith(":") and sum(c.isalpha() for c in t) >= 2


def _find_labels(line: list[Word]):
    """→ [(tür, güçlü, ilk kelime no, son kelime no)] satırdaki etiketler."""
    toks, pos = [], []
    for j, w in enumerate(line):
        n = norm(w.text)
        if n:
            toks.append(n)
            pos.append(j)
    if not toks:
        return []
    text, starts = "", []
    for t in toks:
        starts.append(len(text))
        text += t + " "
    out, used = [], set()
    for kind, strong, rx in _LABEL_RES:
        for m in rx.finditer(text):
            a = max(i for i, s in enumerate(starts) if s <= m.start())
            b = max(i for i, s in enumerate(starts) if s < m.end())
            if any(i in used for i in range(a, b + 1)):
                continue
            used.update(range(a, b + 1))
            out.append((kind, strong, pos[a], pos[b]))
    return out


class _Ink:
    """İkili mürekkep görüntüsü üzerinde bölge sorguları."""

    def __init__(self, img):
        g = img.convert("L")
        self.W, self.H = g.size
        self.img = g.point(lambda v: 255 if v < DARK else 0)

    def _clip(self, x0, y0, x1, y1):
        return (max(0, int(x0)), max(0, int(y0)), min(self.W, int(x1)), min(self.H, int(y1)))

    def dark_frac(self, box) -> float:
        x0, y0, x1, y1 = self._clip(*box)
        if x1 <= x0 or y1 <= y0:
            return 0.0
        c = self.img.crop((x0, y0, x1, y1))
        return c.histogram()[255] / float((x1 - x0) * (y1 - y0))

    def ink_frac(self, box) -> float:
        """Mürekkep oranı; yatay çizgi / noktalı kılavuz satırları (≥ %25 dolu) ve dikey çizgiler hariç."""
        x0, y0, x1, y1 = self._clip(*box)
        w, h = x1 - x0, y1 - y0
        if w < 4 or h < 4:
            return 0.0
        c = self.img.crop((x0, y0, x1, y1))
        p = c.load()
        rows = [sum(1 for x in range(w) if p[x, y]) for y in range(h)]
        cols = [sum(1 for y in range(h) if p[x, y]) for x in range(w)]
        bad_c = {x for x in range(w) if cols[x] >= 0.85 * h}
        n = 0
        for y in range(h):
            if rows[y] >= 0.25 * w:
                continue
            n += rows[y] - sum(1 for x in bad_c if p[x, y])
        return n / float(w * h)

    def ink_columns(self, box) -> list[int]:
        """Mürekkepli sütunlar (görüntü x'i; yatay çizgi / kılavuz satırları hariç)."""
        x0, y0, x1, y1 = self._clip(*box)
        w, h = x1 - x0, y1 - y0
        if w < 4 or h < 4:
            return []
        p = self.img.crop((x0, y0, x1, y1)).load()
        rows = [y for y in range(h) if sum(1 for x in range(w) if p[x, y]) < 0.25 * w]
        return [x0 + x for x in range(w) if any(p[x, y] for y in rows)]

    def vrun(self, box, cy: float, h: float):
        """Alanın dikey mürekkep koşusu: `cy` satırından yukarı/aşağı, mürekkepli satırlar (≤ 0,1h
        boşlukla) boyunca; yatay çizgi / noktalı kılavuz satırında (tablo satır sınırı) durur.
        → (y0, y1) ya da None (mürekkep yok)."""
        x0, y0, x1, y1 = self._clip(*box)
        w, hh = x1 - x0, y1 - y0
        if w < 4 or hh < 4:
            return None
        p = self.img.crop((x0, y0, x1, y1)).load()
        rows = [sum(1 for x in range(w) if p[x, y]) for y in range(hh)]
        line = [r >= 0.25 * w for r in rows]
        inked = [(not line[y]) and r >= max(2, 0.002 * w) for y, r in enumerate(rows)]
        c = min(hh - 1, max(0, int(cy - y0)))
        gap = max(1, int(0.1 * h))
        cand = [y for y in range(hh) if inked[y] and not any(line[min(y, c):max(y, c) + 1])]
        if not cand:
            return None
        start = min(cand, key=lambda y: abs(y - c))
        a = b = start
        k = 0
        while a - 1 >= 0 and not line[a - 1] and k <= gap:
            a -= 1
            k = 0 if inked[a] else k + 1
        a += k
        k = 0
        while b + 1 < hh and not line[b + 1] and k <= gap:
            b += 1
            k = 0 if inked[b] else k + 1
        b -= k
        pad = max(4.0, 0.3 * h)
        return (max(box[1], y0 + a - pad), min(box[3], y0 + b + 1 + pad))

    def rules(self, x0, x1, y0, y1, max_w):
        """[x0, x1) aralığında bant boyunca (≥ %85) koyu dikey sütun koşuları → [(a, b)]; `max_w`'dan
        geniş koşu çizgi değil koyu blok (kapatılmış alan) sayılır ve (a, b, True) döner."""
        X0, Y0, X1, Y1 = self._clip(x0, y0, x1, y1)
        h = Y1 - Y0
        if X1 <= X0 or h < 4:
            return []
        from PIL import ImageFilter
        c = self.img.crop((X0, Y0, X1, Y1)).filter(ImageFilter.MaxFilter(3))   # hafif eğiklik payı
        p = c.load()
        full = [sum(1 for y in range(h) if p[x, y]) >= RULE_FILL * h for x in range(X1 - X0)]
        out, a = [], None
        for i, f in enumerate(full + [False]):
            if f and a is None:
                a = i
            elif not f and a is not None:
                out.append((X0 + a, X0 + i, (i - a) > max_w))
                a = None
        return out


def _next_boundary(cands: list[Word], after_x: float) -> float | None:
    """Etiketten sonraki ilk etiketin başlangıcı: ':' ile biten belirteç (önündeki bilinen form
    sözcükleriyle). `cands`: etiketin satırındaki ve satır bandındaki kelimeler (x sıralı)."""
    cands = [w for w in cands if w.x0 >= after_x]
    for j, w in enumerate(cands):
        if j + 1 < len(cands) and _form_word(w, 90) and _form_word(cands[j + 1], 90) \
                and cands[j + 1].x0 - w.x1 < 2 * max(w.h, 8):
            return w.x0                      # iki basılı form sözcüğü ("Okuduğu Dönem …"): sonraki etiket
        if _colon_word(w) or (w.conf >= 80 and _find_labels([w])):
            k = j
            while k - 1 >= 0 and cands[k - 1].conf >= 80 and norm(cands[k - 1].text) in _FORM_WORDS and j - k < 5:
                k -= 1
            return cands[k].x0
    return None


# Kişisel belge ipucu: ilk geçişte etiket yoksa ikinci OCR geçişine bunlardan biri varsa girilir
# (transkript/form/dilekçe sayfasında varsayılan sayfa bölme bir sütunu bütünüyle atlayabilir).
_HINTS = {"ogrenci", "kimlik", "basvuru", "dilekce", "form", "formu", "transkript", "belgesi", "soyadi",
          "soyad", "imza", "imzasi", "telefon", "eposta", "adres", "adresi", "dogum", "pasaport", "ogrenim"}


def _hinted(words: list[Word]) -> bool:
    return any(w.conf >= 70 and norm(w.text) in _HINTS for w in words)


def _labels_in(lines):
    return [(li, kind, strong, a, b) for li, line in enumerate(lines) for kind, strong, a, b in _find_labels(line)]


def _lab_box(line, a, b):
    lab = line[a:b + 1]
    return (min(w.x0 for w in lab), min(w.y0 for w in lab), max(w.x1 for w in lab), max(w.y1 for w in lab))


def _overlap(p, q) -> bool:
    ix = min(p[2], q[2]) - max(p[0], q[0])
    iy = min(p[3], q[3]) - max(p[1], q[1])
    return ix > 0 and iy > 0 and ix * iy >= 0.3 * min((p[2] - p[0]) * (p[3] - p[1]), (q[2] - q[0]) * (q[3] - q[1]))


def find_fields(img, words: list[Word], more=None) -> list[Field]:
    """OCR kelimeleri + sayfa görüntüsü → kapatılacak etiket alanları. `more`: sayfada etiket ya da
    kişisel belge ipucu bulunduysa çağrılan ikinci OCR geçişi (seyrek metin kipi, psm 11): tesseract'ın varsayılan
    sayfa bölmesi el yazısıyla karışık form satırlarını bütünüyle atlayabilir; ikinci geçişin
    bulduğu yeni etiketler eklenir."""
    if not words:
        return []
    words = _split_colon(words)
    lines = _tess_lines(words)
    found = _labels_in(lines)
    if not found and not (more is not None and _hinted(words)):
        return []
    if more is not None:
        try:
            w2 = _split_colon([Word(w.text, w.conf, w.x0, w.y0, w.x1, w.y1, ("2",) + tuple(w.line))
                               for w in more()])
        except Exception:
            w2 = []
        if w2:
            l2 = _tess_lines(w2)
            have = [_lab_box(lines[li], a, b) for li, _, _, a, b in found]
            off = len(lines)
            for li, kind, strong, a, b in _labels_in(l2):
                bx = _lab_box(l2[li], a, b)
                if not any(_overlap(bx, q) for q in have):
                    found.append((off + li, kind, strong, a, b))
                    have.append(bx)
            lines = lines + l2
            words = words + w2
    if not found:
        return []
    ink = _Ink(img)
    W, H = ink.W, ink.H
    right_edge = W - 1.0
    page_strong = any(s for _, _, s, _, _ in found)
    out: list[Field] = []
    for li, kind, strong, a, b in found:
        line = lines[li]
        lab = line[a:b + 1]
        lx0, lx1 = min(w.x0 for w in lab), max(w.x1 for w in lab)
        core = [w for w in lab if sum(c.isalpha() for c in w.text) >= 2] or lab
        ly0, ly1 = min(w.y0 for w in core), max(w.y1 for w in core)
        hs = sorted(w.h for w in lab if w.h > 0 and sum(c.isalpha() for c in w.text) >= 2)
        h = max(8.0, hs[len(hs) // 2] if hs else ly1 - ly0)
        if not strong:
            if ly1 < TOP_BAND * H or ly0 > (1 - BOTTOM_BAND) * H:
                continue
        # etiket biçimi: ':' (etikette ya da 3h içindeki sonraki belirteçte) ya da satır/hücre başı
        colon = lab[-1].text.rstrip(".)").endswith(":")
        nxt = line[b + 1] if b + 1 < len(line) else None
        if not colon and nxt is not None and nxt.x0 - lx1 <= 3 * h and nxt.text.strip().startswith(":"):
            colon = True
        left = [w for w in line[:a] if w.x1 <= lx0 and lx0 - w.x1 < 4 * h and sum(c.isalnum() for c in w.text)]
        line_start = not left
        rule_l = ink.rules(lx0 - 4 * h, lx0, ly0 - 0.5 * h, ly1 + 0.45 * h, 0.3 * h)
        cell_start = bool(rule_l)
        if not (colon or line_start or cell_start):
            continue
        x0 = lx1 + max(5.0, 0.2 * h)            # etiketin son harfi / ':' kapatma payına girmesin
        y0, y1 = ly0 - UP * h, ly1 + DOWN * h
        cy, band_h = (ly0 + ly1) / 2, 0.9 * h
        cands = {id(w): w for w in line[b + 1:]}
        cands.update({id(w): w for w in words if abs((w.y0 + w.y1) / 2 - cy) <= band_h and w.x0 > lx1})
        bnd = _next_boundary(sorted(cands.values(), key=lambda w: w.x0), x0)
        x1 = min(right_edge, bnd - 2) if bnd is not None else right_edge
        rules = ink.rules(x0, x1, ly0 - 0.5 * h, ly1 + 0.45 * h, 0.3 * h)
        blocked = False
        if rules:
            ra, rb, block = rules[0]
            blocked = block
            if not block and (ra - x0 <= 4 or ink.ink_frac((x0, y0, ra, y1)) < MIN_INK):
                x0 = rb + 1                      # etiket hücresinin sınırı: değer sonraki hücrede
                if len(rules) > 1:
                    x1 = rules[1][0] - 1
            else:
                x1 = ra - 1                      # hücre sınırı ya da koyu blok (önceki kapatma)
                blocked = block and ra - x0 < 3 * h
        boxes = []
        if x1 - x0 >= h and ink.dark_frac((x0, ly0, x1, ly1)) >= DONE_DARK:
            continue                             # etiket satırı zaten kapalı (yeniden tarama)
        vr = ink.vrun((x0, y0, x1, y1), (ly0 + ly1) / 2, h) if x1 - x0 >= h else None
        if vr is not None:
            y0, y1 = min(vr[0], ly0), max(vr[1], ly1)
        main = (x0, y0, x1, y1)
        if x1 - x0 >= h and ink.dark_frac(main) < DONE_DARK and ink.ink_frac(main) >= MIN_INK:
            if strong or page_strong or _handwritten(main, words, ink):
                boxes.append(main)
        elif not colon and not blocked and x1 - x0 >= h and ink.ink_frac(main) < MIN_INK \
                and not any(w.text.strip().startswith(":") for w in cands.values()):
            # tablo: değer alttaki hücrede
            rr = ink.rules(lx1 + 1, min(right_edge, lx1 + 12 * h), ly0 - 0.5 * h, ly1 + 0.45 * h, 0.3 * h)
            bx1 = rr[0][0] - 1 if rr else min(right_edge, lx1 + 8 * h)
            below = (lx0 - 0.3 * h, ly1 + 0.2 * h, bx1, ly1 + 3.2 * h)
            vb = ink.vrun(below, (below[1] + below[3]) / 2, h)
            if vb is not None:
                below = (below[0], vb[0], below[2], vb[1])
            if ink.dark_frac(below) < DONE_DARK and ink.ink_frac(below) >= MIN_INK and (strong or page_strong):
                boxes.append(below)
        if boxes and kind == "adres":
            boxes += _continuation(lines, li, lx0, x1, ly1, h, ink, right_edge)
        for bx in boxes:
            out.append(Field(kind, tuple(float(v) for v in bx), strong))
    return out


def _handwritten(box, words: list[Word], ink: _Ink) -> bool:
    """Alandaki mürekkep güvenle okunan basılı metin değil mi (zayıf etiket için): mürekkepli
    sütunların çoğu (> %40) güvenle okunan kelimelerin dışında kalıyorsa el yazısı sayılır."""
    cols = ink.ink_columns(box)
    if not cols:
        return False
    x0, y0, x1, y1 = box
    spans = [(w.x0, w.x1) for w in words if w.conf >= 80 and any(c.isalnum() for c in w.text)
             and w.x1 > x0 and w.x0 < x1 and min(w.y1, y1) - max(w.y0, y0) > 0.5 * (w.y1 - w.y0)]
    free = sum(1 for c in cols if not any(a - 3 <= c <= b + 3 for a, b in spans))
    return free > 0.4 * len(cols)


def _continuation(lines, li, lx0, x1, ly1, h, ink: _Ink, right_edge) -> list:
    """Adres alanının alt satırları (en çok iki): satır başında etiket/başlık varsa ya da boşsa durur."""
    out = []
    top = ly1 + 0.5 * h
    for _ in range(2):
        band = (top, top + 1.9 * h)
        ws = [w for ln in lines for w in ln if band[0] <= (w.y0 + w.y1) / 2 <= band[1] and w.x1 > lx0 - 2 * h]
        ws.sort(key=lambda w: w.x0)
        end = x1
        for j, w in enumerate(ws):
            if (_colon_word(w) and sum(c.isalpha() for c in w.text) >= 3) or (w.conf >= 80 and _find_labels([w])):
                if w.x0 <= lx0 + 3 * h:
                    return out
                k = j
                while k - 1 >= 0 and ws[k - 1].conf >= 80 and norm(ws[k - 1].text) in _FORM_WORDS and j - k < 5:
                    k -= 1
                end = min(end, ws[k].x0 - 2)
                break
        first = next((w for w in ws if sum(c.isalpha() for c in w.text) >= 3 and w.conf >= 85), None)
        if first is not None and first.x0 <= lx0 + 3 * h and first.text.isupper():
            return out                                # bölüm başlığı
        box = (lx0 - 0.3 * h, band[0], end, band[1])
        if box[2] - box[0] < h or ink.ink_frac(box) < MIN_INK or ink.dark_frac(box) >= DONE_DARK:
            return out
        out.append(box)
        top = band[1]
    return out
