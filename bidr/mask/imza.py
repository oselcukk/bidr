"""İmza bölgesi tespiti (basit görüntü işleme; model yok, yalnız Pillow).

Girdi: sayfa/görsel (PIL) + o görüntünün piksel koordinatında kelimeler (OCR ya da PDF metin
katmanı). Çıktı: kapatılacak kutular ve "elle bakılmalı" kararı.

(a) Etiket: "İmza"/"İmzası" … sözcüğü (kısa satırda ya da `:` ile). Etiketin sağı (aynı satırdaki
    sonraki güvenilir kelimeye ya da ~2,5 inçe kadar) ve altı (sonraki güvenilir satıra kadar)
    etiket bölgesidir; içinde mürekkep varsa güvenilir kelimelere taşmadan kapatılır.
(b) Mürekkep adayı: koyu ya da renkli (mavi tükenmez vb.) pikseller → güvenilir kelime kutuları,
    uzun düz çizgiler (tablo kenarı, alt çizgi) ve dolu bloklar (önceden karartılmış alan, logo
    gövdesi) çıkarılır → bağlantılı bileşenler kümelenir → boyutu, seyrekliği ve yüksekliği imzaya
    benzeyen kümeler adaydır. Bir etiketin (imza etiketi ya da imza bloğu sözcükleri: Üye,
    Başkan, Dekan, Prof., Dr. …) yakınındaki aday kapatılır; etiketsiz aday varsa sayfa
    "imza: elle bakılmalı" olur (`kesin=False`).

Yanlış karartma koruması: her kapatma adayının içine en az %40'ı düşen okunabilir basılı kelime
(etiketler hariç; güvenli ya da metin boyunda düşük güvenli) sayılır ve adaydaki mürekkebin kelime
kutularına düşen payı ölçülür. `MAX_ORTUSEN`'den çok kelime ya da (≥ 2 kelimede) `MAX_METIN_PAYI`
üstü metin payı varsa aday KARARTILMAZ (belge bilgisi kaybolmasın; imza açık kalır), bölge
"imza: elle bakılmalı" olur (`elle_bolge`, `kesin=False`). Kapatılan adaylarla
örtüşen kelime sayısı `ortusen_kelime` olarak döner; her adayın ölçüsü `olcum`'dadır.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .ocr import Word

A_PPI = 100.0                      # çözümleme çözünürlüğü (inç başına piksel)

_STRICT = {"imza", "imzası", "imzasi", "imzalar", "imzaları", "imzalari", "imzalı", "imzali", "ımza", "ımzası"}
_ROLE = {"üye", "uye", "üyesi", "uyesi", "başkan", "başkanı", "baskan", "baskani", "başkanvekili", "dekan",
         "dekanı", "rektör", "rektörü", "müdür", "müdürü", "mudur", "raportör", "sekreter", "sekreteri",
         "onay", "onaylayan", "onaylarım", "hazırlayan", "prof", "doç", "doc", "dr", "öğr", "ogr", "arş",
         "ars", "gör", "gor", "yrd", "v", "vekili"}


def _fold(s: str) -> str:
    return s.replace("İ", "i").replace("I", "ı").lower()


def _core(t: str) -> str:
    return _fold(t).strip(".,:;()[]{}/\\-–—_*'\"|")


# OCR'ın "İmza" okuma hataları dahil: "lmza", "1mza", "kimza" (İ'nin noktası) …
_STRICT_RE = re.compile(r"^(?!hamza)[^\s]{0,2}mza(?:s[ıi]|lar[ıi]?|l[ıi])?$")


_NOT_LABEL = ("elektronik", "imzalanm", "e-imza", "eimza", "güvenli", "guvenli", "doğrula", "dogrula")


def _line_ok(line_words: list[str]) -> bool:
    f = " ".join(_fold(t) for t in line_words)
    return not any(x in f for x in _NOT_LABEL)


def is_strict_label(w: Word, line_len: int, line_words: list[str] | None = None, isolated: bool = False) -> bool:
    """Bağımsız imza etiketi: "İmza", "İmzası:", "Ad Soyad / İmza" (kısa satır, `:` ya da tablo
    başlığında komşularından uzak); akış içindeki "… imza ile imzalanmıştır" (e-imza notu) değil."""
    if line_words is not None and not _line_ok(line_words):
        return False
    if is_placeholder(w.text):
        return False
    c = _core(w.text)
    for part in c.replace("/", " ").split():
        if (part in _STRICT or _STRICT_RE.match(part)) and (line_len <= 5 or isolated
                                                            or w.text.rstrip().endswith(":")):
            return True
    return False


IMZA_LABEL = "[İMZA]"            # kapatılan imza bölgesine yazılan işaret (maskeleyicinin kendi yazısı)


def is_placeholder(text: str) -> bool:
    """Maskeleyicinin yazdığı yer tutucu (`[İMZA]`, `[TC_NO]` …; OCR köşeli ayraçlardan birini
    düşürmüş olabilir): imza etiketi sayılmaz."""
    t = text.strip()
    return t.startswith("[") or t.endswith("]")


def _isolated(ws: list[Word], j: int) -> bool:
    """Satırdaki kelime komşularından (tablo hücresi gibi) uzak mı: iki yandaki boşluk ≥ 1,5 satır yüksekliği."""
    w = ws[j]
    gap = 1.5 * max(4.0, w.h)
    left = w.x0 - ws[j - 1].x1 if j > 0 else gap
    right = ws[j + 1].x0 - w.x1 if j + 1 < len(ws) else gap
    return left >= gap and right >= gap


def is_role_label(w: Word, line_len: int = 1) -> bool:
    """İmza bloğu sözcüğü (Üye, Başkan, Dekan, Prof., Dr. …) kısa satırda (≤ 7 kelime)."""
    if line_len > 7:
        return False
    c = _core(w.text)
    return c in _ROLE or c.startswith(("başkan", "baskan", "dekan", "müdür", "rektör"))


def _confident(w: Word) -> bool:
    n = sum(ch.isalnum() for ch in w.text)
    return w.conf >= 55 and n >= 2 or (w.conf >= 80 and n >= 1)


def _texty(w: Word, med_h: float | None) -> bool:
    """Düşük güvenli ama basılı metin boyunda OCR kelimesi (bulanık/gri zeminli yazı): metin sayılır.
    İmza vuruşları genelde metin satırından yüksektir; OCR'ın onlara verdiği kutu bu ölçüte girmez."""
    if med_h is None or w.conf < 20:
        return False
    n = sum(ch.isalnum() for ch in w.text)
    return n >= 3 and w.h <= 1.3 * med_h and (w.x1 - w.x0) >= 1.2 * w.h


@dataclass
class Result:
    kapat: list = field(default_factory=list)       # (x0,y0,x1,y1) girdi görüntüsünün pikselinde
    etiketli: int = 0                               # kapatılan imza bölgesi/aday sayısı
    etiketsiz: int = 0                              # etiketsiz imza benzeri aday
    etiket: int = 0                                 # bulunan imza etiketi
    ortusen_kelime: int = 0                         # kapatılan alanla örtüşen güvenilir kelime
    elle_bolge: int = 0                             # metinle çok örtüştüğü için kapatılmayan imza bölgesi
    olcum: list = field(default_factory=list)       # aday başına (örtüşen kelime, kapatıldı mı)
    dogrulama: list = field(default_factory=list)   # kapatılan kutu başına yeniden OCR'da okunan kelime
    etiketsiz_kutu: list = field(default_factory=list)  # etiketsiz adayların kutuları (bölge listesi, m2)
    elle_kutu: list = field(default_factory=list)       # kapatılmayan (metinle örtüşen) bölgelerin kutuları (m2)

    @property
    def kesin(self) -> bool:
        return self.etiketsiz == 0 and self.elle_bolge == 0


def _binary(img, words_a, W, H, raw: list | None = None):
    """→ (mürekkep, renkli mürekkep) ikili görüntüler (255 = mürekkep). `raw` verilirse kelime kutuları
    silinmeden önceki mürekkep (basılı metin dahil) ona eklenir."""
    from PIL import Image, ImageChops, ImageDraw, ImageFilter
    rgb = img.convert("RGB").resize((W, H), Image.BILINEAR)
    lum = rgb.convert("L")
    _, s, _ = rgb.convert("HSV").split()
    bg = lum.filter(ImageFilter.MaxFilter(15))           # yerel kâğıt parlaklığı (gri tarama dahil)
    diff = ImageChops.subtract(bg, lum)
    dark = diff.point(lambda x: 255 if x >= 60 else 0)
    faint = diff.point(lambda x: 255 if x >= 40 else 0)
    colored = ImageChops.multiply(faint, s.point(lambda x: 255 if x >= 45 else 0))   # mavi tükenmez (soluk filigran değil)
    # dolu bloklar (önceden karartılmış alan, kalın logo gövdesi) ve çevresi
    blk = lum.point(lambda x: 255 if x < 110 else 0)
    solid = blk.filter(ImageFilter.MinFilter(5)).filter(ImageFilter.MaxFilter(9))
    dark = ImageChops.subtract(dark, solid)
    colored = ImageChops.subtract(colored, solid)
    if raw is not None:
        raw.append(ImageChops.lighter(dark, colored))
    d = ImageDraw.Draw(dark)
    hs = sorted(w.h for w in words_a if _confident(w))
    med = hs[len(hs) // 2] if hs else None
    for w in words_a:                                    # basılı metin; renkli vuruş korunur
        if _confident(w) or _texty(w, med):
            d.rectangle([w.x0 - 1, w.y0 - 1, w.x1 + 1, w.y1 + 1], fill=0)
    _drop_lines(dark, int(0.6 * A_PPI))
    _drop_lines(colored, int(1.5 * A_PPI))
    return ImageChops.lighter(dark, colored), colored


def _drop_lines(ink, min_run: int) -> None:
    """Uzun yatay ve dikey (hafif eğik taramalar dahil) düz çizgileri siler: 3 piksel kalınlaştırılmış
    görüntüde ≥ `min_run` uzunluğundaki koşular çizgi sayılır, çevresiyle birlikte silinir."""
    import re
    from PIL import Image, ImageChops, ImageFilter
    pat = re.compile(rb"\xff{%d,}" % min_run)
    dil = ink.filter(ImageFilter.MaxFilter(3))
    lines = Image.new("L", ink.size, 0)
    for transpose in (False, True):
        im = dil.transpose(Image.Transpose.TRANSPOSE) if transpose else dil
        w, h = im.size
        src = im.tobytes()
        data = bytearray(len(src))
        hit = False
        for y in range(h):
            for m in pat.finditer(src, y * w, (y + 1) * w):
                data[m.start(): m.end()] = b"\xff" * (m.end() - m.start())
                hit = True
        if hit:
            new = Image.frombytes("L", (w, h), bytes(data))
            lines = ImageChops.lighter(lines, new.transpose(Image.Transpose.TRANSPOSE) if transpose else new)
    if lines.getbbox():
        ink.paste(ImageChops.subtract(ink, lines.filter(ImageFilter.MaxFilter(3))))


def _components(ink) -> list[list[int]]:
    """8-bağlantılı bileşenler → [x0, y0, x1, y1, n] (x1/y1 dahil değil)."""
    W, H = ink.size
    data = bytearray(ink.tobytes())
    out = []
    pos = data.find(255)
    while pos != -1:
        stack = [pos]
        data[pos] = 0
        x0 = x1 = pos % W
        y0 = y1 = pos // W
        n = 0
        while stack:
            p = stack.pop()
            n += 1
            y, x = divmod(p, W)
            if x < x0:
                x0 = x
            elif x > x1:
                x1 = x
            if y < y0:
                y0 = y
            elif y > y1:
                y1 = y
            for dy in (-1, 0, 1):
                yy = y + dy
                if yy < 0 or yy >= H:
                    continue
                base = yy * W
                for dx in (-1, 0, 1):
                    xx = x + dx
                    if 0 <= xx < W and data[base + xx]:
                        data[base + xx] = 0
                        stack.append(base + xx)
        out.append([x0, y0, x1 + 1, y1 + 1, n])
        pos = data.find(255, pos)
    return out


def _cluster(comps: list[list[int]], gap: int) -> list[list[int]]:
    cl = [c[:] for c in comps]
    changed = True
    while changed:
        changed = False
        out: list[list[int]] = []
        for c in cl:
            for o in out:
                if c[0] <= o[2] + gap and o[0] <= c[2] + gap and c[1] <= o[3] + gap and o[1] <= c[3] + gap:
                    o[0], o[1], o[2], o[3] = min(o[0], c[0]), min(o[1], c[1]), max(o[2], c[2]), max(o[3], c[3])
                    o[4] += c[4]
                    changed = True
                    break
            else:
                out.append(c)
        cl = out
    return cl


def _signature_like(c, colored_px: int) -> bool:
    """Boyut, seyreklik ve yükseklik/renk ölçütü. Renkli (mavi tükenmez vb.) vuruşlarda ölçüt
    gevşektir: ince, düz görünen imza kuyrukları da yakalanır."""
    w, h, n = c[2] - c[0], c[3] - c[1], c[4]
    colored = colored_px >= 0.6 * n
    # renkli mürekkepte daha büyük küme: birbirine değen imzalar (imza sütunu) tek kümeye birleşir
    if w > (6.0 if colored else 3.8) * A_PPI or h > (8.0 if colored else 2.2) * A_PPI:
        return False
    dens = n / float(w * h)
    if colored:
        return n >= 30 and max(w, h) >= 0.12 * A_PPI and dens <= 0.45
    if n < 40 or max(w, h) < 0.3 * A_PPI or min(w, h) < 0.08 * A_PPI:
        return False
    return dens <= 0.22 and h >= 0.22 * A_PPI


def _overlap(a, b) -> float:
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def _inter(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


# Kapatma adayının basılı metinle örtüşme sınırları (gerçek veride ölçüldü, docs/PRIVACY.md): gerçek
# imza kutusu altındaki ad/unvanla en çok 1-3 kelime örtüşür ve mürekkebinin çoğu kelime dışındadır;
# yanlış adaylar (renkli basılı yazı, başlık bloğu, duyuru metni) çok kelimeyle örtüşür ya da
# mürekkebinin çoğu kelime kutularındadır.
MAX_ORTUSEN = 3                    # bundan çok okunabilir kelime: kapatılmaz
MAX_METIN_PAYI = 0.5               # ≥ 2 kelimede, mürekkebin bu payı kelime kutularındaysa: kapatılmaz

TOP_IGNORE = 0.15                  # sayfa başlığı (logo): etiketsiz aday burada "elle bakılmalı" yapmaz


def analyze(img, words: list[Word], ppi: float, *, flag_unlabeled: bool = True, all_zone: bool = False,
            ink_regions: list | None = None, max_ortusen: int | None = None,
            max_pay: float | None = None) -> Result:
    """`img`: PIL görüntüsü; `words`: aynı görüntünün piksel koordinatında; `ppi`: inç başına piksel.
    `flag_unlabeled`: etiketsiz adaylar "elle bakılmalı" sayılsın mı (taranmış sayfa/görsel: evet).
    `all_zone`: görüntünün tamamı etiket yakını sayılır. `ink_regions`: verilirse mürekkep yalnız bu
    kutularda aranır (metin katmanlı PDF: yalnız küçük gömülü görseller; vektör çizim/akış şeması
    ve filigran dışarıda kalır). `max_ortusen`: örtüşen okunabilir kelime üst sınırı (varsayılan
    `MAX_ORTUSEN`); üstündeki ya da (≥ 2 kelimede) mürekkebinin `max_pay`'ı kelime kutularında olan
    aday kapatılmaz, `elle_bolge` olur."""
    from PIL import Image, ImageDraw
    if max_ortusen is None:
        max_ortusen = MAX_ORTUSEN
    if max_pay is None:
        max_pay = MAX_METIN_PAYI
    k = A_PPI / float(ppi)                  # girdi → çözümleme ölçeği
    W, H = max(1, int(img.width * k)), max(1, int(img.height * k))
    wa = [Word(w.text, w.conf, w.x0 * k, w.y0 * k, w.x1 * k, w.y1 * k, w.line) for w in words]
    raw: list = []
    ink, colored = _binary(img, wa, W, H, raw)
    raw_ink = raw[0]
    if ink_regions is not None:
        keep = Image.new("L", (W, H), 0)
        dk = ImageDraw.Draw(keep)
        for a, b, c, d in ink_regions:
            dk.rectangle([a * k, b * k, c * k, d * k], fill=255)
        from PIL import ImageChops
        ink = ImageChops.multiply(ink, keep)
        colored = ImageChops.multiply(colored, keep)
    from PIL import ImageFilter
    thick = ink.filter(ImageFilter.MinFilter(3))         # ince vuruş aşınınca kaybolur
    res = Result()

    lines: dict = {}
    for i, w in enumerate(wa):
        lines.setdefault(w.line, []).append(i)
    strict, role = [], []
    for li in lines.values():
        li.sort(key=lambda i: wa[i].x0)
        texts = [wa[i].text for i in li]
        lw = [wa[i] for i in li]
        for j, i in enumerate(li):
            if is_strict_label(wa[i], len(li), texts, _isolated(lw, j)):
                strict.append(i)
            elif is_role_label(wa[i], len(li)):
                role.append(i)
    res.etiket = len(strict)
    I = A_PPI
    zones = []
    conf_boxes = [w.box for w in wa if _confident(w)]
    for i in role:                           # imza bloğu: adın/unvanın üstü, yanı, altı
        w = wa[i]
        zones.append((w.x0 - 1.0 * I, w.y0 - 0.9 * I, w.x1 + 3.0 * I, w.y1 + 0.9 * I))
    for i in strict:                         # etiketin sağı ve altı
        w = wa[i]
        zones.append((w.x0 - 0.3 * I, w.y0 - 0.4 * I, w.x1 + 3.0 * I, w.y1 + 1.2 * I))
        # sütun başlığı "İmza": sütunun altı, sütunda basılı metin başlayana kadar (en çok 5 inç)
        cx0, cx1 = w.x0 - 0.6 * I, w.x1 + 0.6 * I
        stop = [o[1] for o in conf_boxes if o[1] > w.y1 + 2 and o[0] < w.x1 + 0.2 * I and o[2] > w.x0 - 0.2 * I]
        zones.append((cx0, w.y1, cx1, min([w.y1 + 5 * I, H] + stop)))
    if all_zone:
        zones.append((0, 0, W, H))

    conf_boxes = [w.box for w in wa if _confident(w)]
    covers = []
    # (a) etiket bölgesi
    from PIL import ImageChops
    for i in strict:
        w = wa[i]
        lh = max(8.0, w.h)
        same = [o for o in conf_boxes if o[0] > w.x1 and o[1] < w.y1 and o[3] > w.y0]
        rx1 = min([o[0] - 2 for o in same] + [w.x1 + 2.5 * I, W])
        right = (w.x1 + 2, w.y0 - 0.6 * lh, rx1, w.y1 + 0.6 * lh)
        bx0, bx1 = w.x0 - 0.3 * I, w.x0 + 2.5 * I
        below_words = [o for o in conf_boxes if o[1] >= w.y1 and o[0] < bx1 and o[2] > bx0]
        by1 = min([o[1] - 2 for o in below_words] + [w.y1 + 0.8 * I, H])
        below = (bx0, w.y1 + 2, bx1, by1)
        for r in (right, below):
            r = (max(0, r[0]), max(0, r[1]), min(W, r[2]), min(H, r[3]))
            if r[2] - r[0] < 4 or r[3] - r[1] < 4:
                continue
            crop = ink.crop(tuple(int(v) for v in r))
            hist = crop.histogram()
            if hist[255] >= 15:
                bb = crop.getbbox()
                if bb:
                    covers.append((r[0] + bb[0] - 3, r[1] + bb[1] - 3, r[0] + bb[2] + 3, r[1] + bb[3] + 3))
                    res.etiketli += 1

    # (b) mürekkep adayları
    comps = [c for c in _components(ink) if c[4] >= 8]
    clusters = _cluster(comps, int(0.08 * I))
    col_data = ImageChops.multiply(colored, colored)
    for c in clusters:
        crop = col_data.crop((c[0], c[1], c[2], c[3]))
        cpx = crop.histogram()[255]
        if not _signature_like(c, cpx):
            continue
        if thick.crop((c[0], c[1], c[2], c[3])).histogram()[255] > 0.3 * c[4]:
            continue                          # kalın/dolu şekil (logo, grafik): imza değil
        box = (c[0], c[1], c[2], c[3])
        if any(_inter(box, z) for z in zones):
            pad = 0.1 * I
            near = (box[0] - 0.25 * I, box[1] - 0.25 * I, box[2] + 0.25 * I, box[3] + 0.25 * I)
            x0, y0, x1, y1 = box
            for o in comps:                  # yakındaki küçük vuruşlar da örtülsün
                if _inter(o, near):
                    x0, y0, x1, y1 = min(x0, o[0]), min(y0, o[1]), max(x1, o[2]), max(y1, o[3])
            covers.append((x0 - pad / 2, y0 - pad / 2, x1 + pad / 2, y1 + pad / 2))
            res.etiketli += 1
        elif flag_unlabeled and (box[1] + box[3]) / 2 > TOP_IGNORE * H:
            res.etiketsiz += 1
            res.etiketsiz_kutu.append(box)

    labels = set(strict + role)
    hs = sorted(w.h for w in wa if _confident(w))
    med = hs[len(hs) // 2] if hs else None
    readable = [w for j, w in enumerate(wa) if j not in labels and (readable_word(w) or _texty(w, med))]
    kept, hit = [], set()
    for cb in covers:
        ws = covered_words(readable, cb)
        frac = _text_ink_frac(raw_ink, cb, [readable[j] for j in ws])
        ok = len(ws) <= max_ortusen and not (len(ws) >= 2 and frac >= max_pay)
        res.olcum.append((len(ws), round(frac, 3), ok))
        if ok:
            kept.append(cb)
            hit.update(ws)
        else:
            res.elle_bolge += 1
            res.etiketli -= 1
            res.elle_kutu.append(cb)
    res.ortusen_kelime = len(hit)
    res.kapat = [(max(0, a / k), max(0, b / k), min(img.width, c / k), min(img.height, d / k))
                 for a, b, c, d in kept]
    res.etiketsiz_kutu = [(max(0, a / k), max(0, b / k), min(img.width, c / k), min(img.height, d / k))
                          for a, b, c, d in res.etiketsiz_kutu]
    res.elle_kutu = [(max(0, a / k), max(0, b / k), min(img.width, c / k), min(img.height, d / k))
                     for a, b, c, d in res.elle_kutu]
    return res


def readable_word(w: Word) -> bool:
    """Okunabilir basılı kelime: güven ≥ 70 ve en az üç harf/rakam (tarih, sayı dahil)."""
    return w.conf >= 70 and sum(ch.isalnum() for ch in w.text) >= 3


def _text_ink_frac(raw_ink, box, words: list[Word]) -> float:
    """Kutudaki mürekkebin (basılı metin dahil) okunabilir kelime kutularına düşen payı."""
    from PIL import Image, ImageChops, ImageDraw
    x0, y0 = max(0, int(box[0])), max(0, int(box[1]))
    x1, y1 = min(raw_ink.width, int(box[2]) + 1), min(raw_ink.height, int(box[3]) + 1)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    crop = raw_ink.crop((x0, y0, x1, y1))
    total = crop.histogram()[255]
    if not total or not words:
        return 0.0
    m = Image.new("L", crop.size, 0)
    d = ImageDraw.Draw(m)
    for w in words:
        d.rectangle([w.x0 - x0, w.y0 - y0, w.x1 - x0, w.y1 - y0], fill=255)
    return ImageChops.multiply(crop, m).histogram()[255] / float(total)


def covered_words(words: list[Word], box) -> list[int]:
    """`box`'un içine alanının en az %40'ı düşen kelimelerin sırası."""
    out = []
    for j, w in enumerate(words):
        area = max(1.0, (w.x1 - w.x0) * (w.y1 - w.y0))
        if _overlap(w.box, box) / area >= 0.4:
            out.append(j)
    return out


def leftover_ink(img, words: list[Word], ppi: float) -> Result:
    """Yeniden tarama: maskeli görüntüde kalan imza adayı (kapatılmış kutular dolu bloktur, sayılmaz)."""
    return analyze(img, words, ppi, flag_unlabeled=True)
