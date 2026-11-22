"""El yazısıyla doldurulmuş form alanları: değeri OKUMADAN bulup kapatmak.

Taranmış form/dilekçede el yazısı değer OCR'la okunamaz, ama BASILI etiketi ("T.C. Kimlik No:",
"Öğrenci No", "Tel", "Adres", "Doğum Tarihi"; OCR yazım hatalarıyla) ve formun iskeleti (noktalı
kılavuz, alt çizgi, kutucuk/tarak dizisi, tablo çizgileri) görünür. Üç kaynak (`el_yazisi_bolgeleri`):

- `etiket_alani`: etiketin dört yönünde (sağ, alt, üst: çizginin altındaki "(T.C. Kimlik No)"
  açıklaması, sol) geometrik alan adayları aranır: kılavuz/alt çizgi, tarak dizisi, komşu tablo
  hücresi ve yapısız el yazısı mürekkebi (eski "etiketin sağı" kuralı, artık adaylardan biri). Puan:
  uzaklık (yazı yüksekliği birimi) + yön cezası + boşluk cezası; en yakın alan seçilir, puanı yakın
  ikinci yön de bölge olur (mürekkepliyse kapatılır, boşsa `onay_bekliyor`). Alan bir sonraki
  etikete, açıklamaya, tablo çizgisine ya da çizgi sonuna kadar kapatılır; kılavuzlu alan boş
  görünse de kapatılır (kaçırmak pahalı). Güçlü etiket var ama alan bulunamıyorsa `onay_bekliyor`.
- `rakam_dizisi`: etiket olmasa da benzer yükseklikte, aynı tabanda yan yana 10-13 el yazısı bileşen
  (11: kimlik, 12: öğrenci no uzunluğu yalnız güveni artırır); kişisel veri etiketi yakınındaysa
  kapatılır, değilse `onay_bekliyor`; kişisel olmayan etiketin (ör. "Bölümü:") değeri sayılmaz. OCR'ın
  bileşenleri rakam olarak okuması da okuyamaması da adayı düşürmez.
- `sablon`: aynı formun önceki kopyasında insanın kapattığı bölgeler (`sablon.py`).

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
- zaten kapatılmış alan (çoğu koyu: yeniden tarama) alınmaz; başka etiketin kılavuzu (aynı bantta
  hemen solunda biten etiket) alt/üst aday olmaz.

Yapısız mürekkep adayı (eski kural): etiket satır bandı (yukarı/aşağı genişletilmiş; el yazısı basılı
satırdan taşar), etiket bitiminden sağa bir sonraki etikete, doğrulanmış dikey tablo çizgisine ya da
sayfa kenarına kadar; adres alanı bir-iki satır aşağı uzar. Sayfa yapısı numpy ister ([maske] eki);
numpy yoksa yalnız bu eski kural çalışır.

`find_fields` (raster hattı) yalnız `kapatildi` alanları döndürür. Değerler hiçbir yere yazılmaz;
çıktı kutu ve etiket türüdür.
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


# OCR yazım hataları: harf içindeki rakam karışıklıkları (Kim1ik, N0, Te1efon) ve tek harf hatası
# (Kimllk, Ogrencl, Adrcs) etiket anahtar sözcüklerine düzeltilir (≥ 5 harf, ilk harf aynı).
_OCR_HARF = str.maketrans({"0": "o", "1": "l", "5": "s", "8": "b", "6": "g", "3": "e"})
_ANAHTAR = ("kimlik", "numarasi", "numara", "ogrenci", "dogum", "tarihi", "telefon", "telefonu", "adres",
            "adresi", "pasaport", "ikamet", "ikametgah", "yazisma", "tebligat")


def _lev1(a: str, b: str) -> bool:
    """Düzenleme uzaklığı ≤ 1 mi."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    if len(a) > len(b):
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i:] == b[i + 1:]


def _duzelt(t: str) -> str:
    if any(c.isdigit() for c in t) and any(c.isalpha() for c in t):
        t = t.translate(_OCR_HARF)
    if len(t) >= 5 and t not in _ANAHTAR:
        for k in _ANAHTAR:
            if k[0] == t[0] and _lev1(t, k):
                return k
    return t


@dataclass
class Field:
    kind: str                 # etiket türü (tc_no, telefon, eposta, ogrenci_no, adres, dogum_tarihi)
    box: tuple                # (x0, y0, x1, y1) görüntü pikseli
    strong: bool
    karar: str = "kapatildi"  # kapatildi | onay_bekliyor
    kaynak: str = KIND
    guven: float = 0.7
    neden: str = ""


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
            toks.append(_duzelt(n))
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
        if w.conf >= 80 and w.text.startswith("(") and sum(c.isalpha() for c in w.text) >= 2:
            return w.x0                      # açıklama satırı ("(Ad Soyad)"): başka alanın etiketi
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


# ---------------------------------------------------------------- sayfa yapısı (çizgi, kılavuz, tarak, hücre)
#
# Değer okunmadan alan bulunur: basılı formun iskeleti (noktalı kılavuz, alt çizgi, kutucuk/tarak dizisi,
# tablo çizgileri) ikili mürekkep görüntüsünden çıkarılır. Yatay yapı: yatay kapama (noktalar birleşir) →
# dikey açmayla kalın kütleler (metin, el yazısı gövdesi, kapatılmış blok) atılır → kalan ince koşular
# satırlar arasında gruplanır (eğik taramada parça parça satırlara dağılan çizgi tek parça olur). Grup,
# özgün mürekkep profiliyle "çizgi" (dolu) ya da "nokta" (düzenli aralıklı kısa koşular) sayılır; ikisi
# de değilse (el yazısının ince kuyruğu) atılır.

try:                                     # isteğe bağlı ([maske] eki): yoksa eski etiket sağı kuralı çalışır
    import numpy as np
except ImportError:                      # pragma: no cover
    np = None


def _odd(k: float) -> int:
    k = max(1, int(round(k)))
    return k if k % 2 else k + 1


def _win(M, k: int, axis: int):
    r = k // 2
    pad = [(0, 0), (0, 0)]
    pad[axis] = (r + 1, r)
    c = np.cumsum(np.pad(M, pad).astype(np.int32), axis=axis)
    return c[k:] - c[:-k] if axis == 0 else c[:, k:] - c[:, :-k]


def _dil(M, k, axis):
    return _win(M, k, axis) > 0


def _ero(M, k, axis):
    return _win(M, k, axis) == k


def _close(M, k, axis):
    return M | _ero(_dil(M, k, axis), k, axis)


def _open(M, k, axis):
    return _dil(_ero(M, k, axis), k, axis)


def _runs(M):
    """Satır koşuları → (y, a, b) dizileri (b dahil değil)."""
    P = np.zeros((M.shape[0], M.shape[1] + 2), np.int8)
    P[:, 1:-1] = M
    d = np.diff(P, axis=1)
    ys, a = np.nonzero(d == 1)
    _, b = np.nonzero(d == -1)
    return ys, a, b


def _group_runs(ys, a, b, max_dy: int = 2) -> list[list[int]]:
    """Komşu satırlarda x'i örtüşen koşular → gruplar (koşu sıraları)."""
    n = len(ys)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    rows: dict = {}
    for i in range(n):
        y = int(ys[i])
        for dy in range(1, max_dy + 1):
            for j in rows.get(y - dy, ()):
                if a[j] < b[i] and a[i] < b[j]:
                    ri, rj = find(i), find(j)
                    if ri != rj:
                        parent[ri] = rj
        rows.setdefault(y, []).append(i)
    g: dict = {}
    for i in range(n):
        g.setdefault(find(i), []).append(i)
    return list(g.values())


@dataclass
class Seg:
    """Yatay (çizgi/nokta) ya da dikey (dikey) yapı parçası; görüntü pikseli. `ya`/`yb`: sol/sağ uçtaki
    orta y (eğiklik); dikeyde `ya`/`yb` üst/alt uçtaki orta x."""
    x0: float
    y0: float
    x1: float
    y1: float
    tur: str
    ya: float = 0.0
    yb: float = 0.0

    @property
    def box(self):
        return (self.x0, self.y0, self.x1, self.y1)

    @property
    def cx(self):
        return (self.x0 + self.x1) / 2

    @property
    def length(self):
        return max(self.x1 - self.x0, self.y1 - self.y0)

    def y_at(self, x: float) -> float:
        if self.x1 - self.x0 < 1:
            return self.ya
        t = min(1.0, max(0.0, (x - self.x0) / (self.x1 - self.x0)))
        return self.ya + t * (self.yb - self.ya)

    def x_at(self, y: float) -> float:        # dikey parça
        if self.y1 - self.y0 < 1:
            return self.ya
        t = min(1.0, max(0.0, (y - self.y0) / (self.y1 - self.y0)))
        return self.ya + t * (self.yb - self.ya)


def _profile_runs(prof):
    p = np.concatenate(([0], prof.astype(np.int8), [0]))
    d = np.diff(p)
    s = np.nonzero(d == 1)[0]
    e = np.nonzero(d == -1)[0]
    return s, e


def _yatay_parcalar(B, h: float, mask_out=None) -> list[Seg]:
    g = _odd(0.35 * h)
    C = _close(B, g, 1)
    kt = _odd(max(5.0, 0.3 * h + 2))
    T = C & ~_open(C, kt, 0)
    T = _close(T, _odd(0.6 * h), 1)
    ys, a, b = _runs(T)
    keep = (b - a) >= h                   # eğik çizgi satır başına kısa parçalara bölünür
    ys, a, b = ys[keep], a[keep], b[keep]
    out = []
    for grp in _group_runs(ys, a, b):
        grp = _line_inliers(grp, ys, a, b, kt)
        if not grp:
            continue
        x0 = int(min(a[i] for i in grp))
        x1 = int(max(b[i] for i in grp))
        y0 = int(min(ys[i] for i in grp))
        y1 = int(max(ys[i] for i in grp)) + 1
        L = x1 - x0
        if L < 4 * h or (y1 - y0) > 2 * kt + 0.07 * L:
            continue
        prof = np.zeros(L, bool)
        for i in grp:
            prof[a[i] - x0:b[i] - x0] |= B[ys[i], a[i]:b[i]]
        fill = float(prof.mean())
        s, e = _profile_runs(prof)
        tur = None
        if fill >= 0.8 and L >= 5 * h:
            tur = "cizgi"
        elif len(s) >= 8 and L >= 4 * h and 0.1 <= fill < 0.8:
            lens = e - s
            gaps = s[1:] - e[:-1]
            mg, ml = float(np.median(gaps)), float(np.median(lens))
            reg_g = float(np.mean(np.abs(gaps - mg) <= 0.35 * mg + 1))
            reg_l = float(np.mean(np.abs(lens - ml) <= 0.5 * ml + 1))
            if ml <= 0.5 * h and mg <= 0.8 * h and reg_g >= 0.7 and reg_l >= 0.7:
                tur = "nokta"          # basılı nokta dizisi düzenlidir (üstüne yazılan yer dışında)
        if tur is None:
            continue
        left = [ys[i] for i in grp if a[i] - x0 < h]
        right = [ys[i] for i in grp if x1 - b[i] < h]
        ya = float(np.mean(left)) if left else (y0 + y1) / 2
        yb = float(np.mean(right)) if right else (y0 + y1) / 2
        out.append(Seg(float(x0), float(y0), float(x1), float(y1), tur, ya, yb))
        if mask_out is not None:
            for i in grp:
                mask_out[max(0, ys[i] - 1):ys[i] + 2, a[i]:b[i]] = True
    return _join_collinear(out, h, B)


def _line_inliers(grp, ys, a, b, kt) -> list[int]:
    """Gruptaki koşulardan doğruya oturanlar: uzunluk ağırlıklı doğru uydurma, artığı > kt olan koşular
    (çizgiye değen el yazısı parçaları) atılır, yeniden uydurulur."""
    idx = list(grp)
    for _ in range(3):
        w = np.array([b[i] - a[i] for i in idx], float)
        x = np.array([(a[i] + b[i]) / 2 for i in idx], float)
        y = np.array([ys[i] for i in idx], float)
        if len(idx) >= 2 and float(np.ptp(x)) > 1:
            A = np.vstack([x, np.ones_like(x)]).T * w[:, None]
            m, c = np.linalg.lstsq(A, y * w, rcond=None)[0]
        else:
            m, c = 0.0, float(np.average(y, weights=w))
        r = np.abs(y - (m * x + c))
        keep = [i for i, rr in zip(idx, r) if rr <= kt]
        if len(keep) == len(idx) or not keep:
            break
        idx = keep
    if not keep:
        return []
    # basılı çizgi doğrudur: koşu ortaları doğrudan az sapar (el yazısı vuruşları dalgalıdır)
    wk = np.array([b[i] - a[i] for i in keep], float)
    xk = np.array([(a[i] + b[i]) / 2 for i in keep], float)
    yk = np.array([ys[i] for i in keep], float)
    r = np.abs(yk - (m * xk + c))
    o = np.argsort(r)
    cw = np.cumsum(wk[o])
    med = float(r[o][np.searchsorted(cw, 0.5 * cw[-1])])     # ağırlıklı ortanca sapma
    return keep if med <= max(1.5, 0.25 * kt) else []


def _join_collinear(segs: list[Seg], h: float, B=None) -> list[Seg]:
    """El yazısının örttüğü kılavuz/alt çizgi parçalanır (yazının altında ince koşu kalmaz): aynı türden,
    aynı doğrultuda (uçtaki y farkı küçük), arası ≤ 15h olan ve aradaki boşluğun çizgi hizasında
    mürekkep (yazı) bulunan parçalar birleştirilir; boş aralık (iki ayrı çizgi) birleşmez."""
    segs = sorted(segs, key=lambda s: s.x0)
    out: list[Seg] = []
    for s in segs:
        for o in out:
            if o.tur != s.tur or s.x0 < o.x1 - 2 or s.x0 - o.x1 > 15 * h:
                continue
            slope = (o.yb - o.ya) / max(1.0, o.x1 - o.x0) if o.x1 - o.x0 > 6 * h else 0.0
            pred = o.yb + slope * (s.x0 - o.x1)
            if abs(pred - s.ya) <= 0.25 * h + 2 and _gap_written(B, o.x1, s.x0, (o.yb + s.ya) / 2, h):
                o.x1, o.yb = s.x1, s.yb
                o.y0, o.y1 = min(o.y0, s.y0), max(o.y1, s.y1)
                break
        else:
            out.append(Seg(s.x0, s.y0, s.x1, s.y1, s.tur, s.ya, s.yb))
    return out


def _gap_written(B, xa, xb, y, h) -> bool:
    if B is None or xb - xa <= 2:
        return True
    y0, y1 = max(0, int(y - 1.2 * h)), min(B.shape[0], int(y + 0.6 * h) + 1)
    cols = B[y0:y1, int(xa):int(xb) + 1].any(axis=0)
    return cols.size == 0 or float(cols.mean()) >= 0.5


def _dikey_parcalar(B, h: float) -> list[Seg]:
    C = _close(B, _odd(0.2 * h), 0)
    kt = _odd(max(5.0, 0.3 * h + 2))
    T = C & ~_open(C, kt, 1)
    T = _close(T, _odd(0.4 * h), 0)
    xs, a, b = _runs(T.T)
    keep = (b - a) >= 0.6 * h
    xs, a, b = xs[keep], a[keep], b[keep]
    out = []
    for grp in _group_runs(xs, a, b):
        y0 = int(min(a[i] for i in grp))
        y1 = int(max(b[i] for i in grp))
        x0 = int(min(xs[i] for i in grp))
        x1 = int(max(xs[i] for i in grp)) + 1
        L = y1 - y0
        if L < 0.6 * h or (x1 - x0) > 2 * kt + 0.07 * L:
            continue
        prof = np.zeros(L, bool)
        for i in grp:
            prof[a[i] - y0:b[i] - y0] |= B[a[i]:b[i], xs[i]]
        if float(prof.mean()) < 0.8:
            continue
        top = [xs[i] for i in grp if a[i] - y0 < 0.3 * h]
        bot = [xs[i] for i in grp if y1 - b[i] < 0.3 * h]
        out.append(Seg(float(x0), float(y0), float(x1), float(y1), "dikey",
                       float(np.mean(top)) if top else (x0 + x1) / 2, float(np.mean(bot)) if bot else (x0 + x1) / 2))
    return out


@dataclass
class Tarak:
    """Kutucuk/tarak dizisi: yatay taban çizgisine değen düzenli aralıklı kısa dikey çizgiler."""
    box: tuple
    n: int
    ticks: list


def _taraklar(yatay: list[Seg], dikey: list[Seg], h: float) -> list[Tarak]:
    out: list[Tarak] = []
    tol = 0.25 * h + 3
    for s in yatay:
        if s.tur != "cizgi" or s.x1 - s.x0 < 4 * h:
            continue
        for side in ("ust", "alt"):
            ticks = []
            for v in dikey:
                cx = v.cx
                if not (s.x0 - 3 <= cx <= s.x1 + 3) or not (0.5 * h <= v.length <= 4 * h):
                    continue
                yl = s.y_at(cx)
                if side == "ust" and abs(v.y1 - yl) <= tol and v.y0 < yl - 0.3 * h:
                    ticks.append(v)
                elif side == "alt" and abs(v.y0 - yl) <= tol and v.y1 > yl + 0.3 * h:
                    ticks.append(v)
            if len(ticks) < 5:
                continue
            ticks = _regular_ticks(ticks, h)
            if not ticks:
                continue
            x0, x1 = min(v.x0 for v in ticks), max(v.x1 for v in ticks)
            if side == "ust":
                box = (x0, min(v.y0 for v in ticks), x1, max(s.y1, max(v.y1 for v in ticks)))
            else:
                box = (x0, min(s.y0, min(v.y0 for v in ticks)), x1, max(v.y1 for v in ticks))
            if any(_iou(box, t.box) > 0.4 for t in out):
                continue
            out.append(Tarak(box, len(ticks) - 1, ticks))
    return out


def _sd(xs) -> float:
    m = sum(xs) / len(xs)
    return (sum((x - m) ** 2 for x in xs) / len(xs)) ** 0.5


def _regular_ticks(ticks: list[Seg], h: float) -> list[Seg]:
    """Basılı tarak: eşit boylu, uçları hizalı, ince, eşit aralıklı dikey çizgiler (araya giren el yazısı
    rakam vuruşları ayıklanır; rakamlar bu düzenliliği taşımaz). En uzun düzenli dizi döner (≥ 6 çizgi)."""
    thin = [v for v in ticks if v.x1 - v.x0 <= max(4.0, 0.2 * h)]
    best: list[Seg] = []
    seen = set()
    for ref in thin:
        L = ref.length
        grp = sorted((v for v in thin if abs(v.length - L) <= 0.12 * L and abs(v.y0 - ref.y0) <= 0.15 * h + 2),
                     key=lambda v: v.cx)
        key = tuple(id(v) for v in grp)
        if len(grp) < 6 or key in seen:
            continue
        seen.add(key)
        gaps = [q.cx - p.cx for p, q in zip(grp, grp[1:])]
        m = sorted(gaps)[len(gaps) // 2]
        if not (0.5 * h <= m <= 4 * h):
            continue
        run = [grp[0]]
        for g, v in zip(gaps, grp[1:]):
            if abs(g - m) <= 0.15 * m:
                run.append(v)
            else:
                if len(run) > len(best):
                    best = run
                run = [v]
        if len(run) > len(best):
            best = run
    return best if len(best) >= 6 else []


def _iou(p, q) -> float:
    ix = max(0.0, min(p[2], q[2]) - max(p[0], q[0]))
    iy = max(0.0, min(p[3], q[3]) - max(p[1], q[1]))
    i = ix * iy
    u = (p[2] - p[0]) * (p[3] - p[1]) + (q[2] - q[0]) * (q[3] - q[1]) - i
    return i / u if u > 0 else 0.0


def _inside(p, q, frac=0.9) -> bool:
    """`p`'nin alanının en az `frac`'ı `q` içinde mi."""
    ix = max(0.0, min(p[2], q[2]) - max(p[0], q[0]))
    iy = max(0.0, min(p[3], q[3]) - max(p[1], q[1]))
    a = max(1e-6, (p[2] - p[0]) * (p[3] - p[1]))
    return ix * iy / a >= frac


class Yapi:
    """Sayfanın basılı iskeleti: yatay çizgi/kılavuz, dikey çizgi, tarak dizileri, tablo hücreleri.
    `words`: güvenle okunan basılı kelimelerin içindeki ince parçalar (harf tabanı) yapı sayılmaz."""

    def __init__(self, img, h: float, words: list[Word] | None = None):
        g = np.asarray(img.convert("L"))
        self.B = g < DARK
        self.H, self.W = self.B.shape
        self.h = h
        self.line_mask = np.zeros_like(self.B)
        printed = [w.box for w in (words or []) if w.conf >= 80 and sum(c.isalpha() for c in w.text) >= 2]
        self.yatay = [s for s in _yatay_parcalar(self.B, h, self.line_mask)
                      if not any(_inside(s.box, q, 0.6) for q in printed)]
        self.dikey = _dikey_parcalar(self.B, h)
        self.taraklar = _taraklar(self.yatay, self.dikey, h)
        ticks = {id(v) for t in self.taraklar for v in t.ticks}
        self.kurallar_h = [s for s in self.yatay if s.tur == "cizgi"]
        self.kurallar_v = [v for v in self.dikey if id(v) not in ticks and self._table_rule(v)]
        for v in self.kurallar_v + [v for t in self.taraklar for v in t.ticks]:
            self.line_mask[int(v.y0):int(v.y1), max(0, int(v.x0) - 1):int(v.x1) + 1] = True

    def ink_frac(self, box) -> float:
        """Yapı (çizgi/kılavuz/tarak/tablo) dışındaki mürekkep oranı."""
        x0, y0 = max(0, int(box[0])), max(0, int(box[1]))
        x1, y1 = min(self.W, int(box[2])), min(self.H, int(box[3]))
        if x1 - x0 < 2 or y1 - y0 < 2:
            return 0.0
        m = self.B[y0:y1, x0:x1] & ~self.line_mask[y0:y1, x0:x1]
        return float(m.mean())

    def _table_rule(self, v: Seg) -> bool:
        """Tablo dikey çizgisi: çok uzun ya da iki ucu da yatay çizgiye değiyor (el yazısı vuruşu değil)."""
        if v.length >= 4 * self.h:
            return True
        if v.length < 1.2 * self.h:
            return False
        tol = 0.3 * self.h + 3

        def touch(y):
            return any(s.x0 - tol <= v.cx <= s.x1 + tol and abs(s.y_at(v.cx) - y) <= tol for s in self.kurallar_h)
        return touch(v.y0) and touch(v.y1)

    def _vrule(self, px, py, side):
        best = None
        for v in self.kurallar_v:
            if not (v.y0 - 3 <= py <= v.y1 + 3):
                continue
            x = v.x_at(py)
            if side < 0 and x < px and (best is None or x > best):
                best = x
            elif side > 0 and x > px and (best is None or x < best):
                best = x
        return best

    def _hrule(self, px, py, side):
        best = None
        for s in self.kurallar_h:
            if not (s.x0 - 3 <= px <= s.x1 + 3):
                continue
            y = s.y_at(px)
            if side < 0 and y < py and (best is None or y > best):
                best = y
            elif side > 0 and y > py and (best is None or y < best):
                best = y
        return best

    def cell(self, box):
        """`box`'u (etiket) içeren tablo hücresi (x0, y0, x1, y1) ya da None."""
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        L, R = self._vrule(cx, cy, -1), self._vrule(cx, cy, 1)
        T, Bm = self._hrule(cx, cy, -1), self._hrule(cx, cy, 1)
        if None in (L, R, T, Bm) or L > box[0] + 2 or R < box[2] - 2 or T > box[1] + 2 or Bm < box[3] - 2:
            return None
        if R - L > 0.9 * self.W and Bm - T > 0.5 * self.H:
            return None                       # sayfa çerçevesi
        return (L, T, R, Bm)

    def right_cell(self, c):
        L, T, R, Bm = c
        cy = (T + Bm) / 2
        R2 = self._vrule(R + 3, cy, 1)
        if R2 is None or R2 - R < self.h:
            return None
        return (R, T, R2, Bm)

    def below_cell(self, c):
        L, T, R, Bm = c
        cx = (L + R) / 2
        B2 = self._hrule(cx, Bm + 3, 1)
        if B2 is None or B2 - Bm < 0.8 * self.h or B2 - Bm > 6 * self.h:
            return None
        return (L, Bm, R, B2)


def _page_h(words: list[Word], H: int) -> float:
    hs = sorted(w.h for w in words if w.conf >= 70 and sum(c.isalpha() for c in w.text) >= 2 and w.h > 0)
    return max(8.0, float(hs[len(hs) // 2])) if hs else max(8.0, 0.016 * H)


# ---------------------------------------------------------------- etiket alanları

YON_CEZA = {"sag": 0.0, "alt": 0.3, "ust": 0.6, "sol": 0.8}
BOS_CEZA = 1.5            # mürekkepsiz aday (boş alan) cezası: mürekkepli aday 1,5h uzakta olsa da yeğlenir
YAPISIZ_CEZA = 0.5        # yalnız mürekkep (kılavuz/çizgi/hücre yok)
BELIRSIZ = 0.5            # iki yönün puan farkı bunun altındaysa ikincisi de bölge olur


@dataclass
class _Aday:
    yon: str
    box: tuple
    yapi: str                 # nokta | cizgi | tarak | hucre | murekkep
    mesafe: float             # h biriminde
    ink: bool

    @property
    def puan(self):
        return self.mesafe + YON_CEZA[self.yon] + (0 if self.ink else BOS_CEZA) + \
            (YAPISIZ_CEZA if self.yapi == "murekkep" else 0)


_YAPI_AD = {"nokta": "noktalı kılavuz", "cizgi": "alt çizgi", "tarak": "kutucuk dizisi", "hucre": "tablo hücresi",
            "murekkep": "el yazısı"}
_YON_AD = {"sag": "sağında", "alt": "altında", "ust": "üstünde", "sol": "solunda"}
_TUR_AD = {"tc_no": "kimlik no", "ogrenci_no": "öğrenci no", "telefon": "telefon", "eposta": "e-posta",
           "adres": "adres", "dogum_tarihi": "doğum tarihi"}


def find_fields(img, words: list[Word], more=None) -> list[Field]:
    """Kapatılacak (kesin) etiket alanları; `onay_bekliyor` adaylar dahil değil (bkz. `alan_adaylari`)."""
    return [f for f in alan_adaylari(img, words, more=more)[0] if f.karar == "kapatildi"]


def alan_adaylari(img, words: list[Word], more=None):
    """OCR kelimeleri + sayfa görüntüsü → ([Field], bağlam). `more`: sayfada etiket ya da kişisel
    belge ipucu bulunduysa çağrılan ikinci OCR geçişi (seyrek metin kipi, psm 11): tesseract'ın
    varsayılan sayfa bölmesi el yazısıyla karışık form satırlarını bütünüyle atlayabilir; ikinci
    geçişin bulduğu yeni etiketler eklenir. Bağlam: {"words", "found", "lines", "yapi", "h"}."""
    ctx = {"words": [], "found": [], "lines": [], "yapi": None, "h": None}
    if not words:
        return [], ctx
    words = _split_colon(words)
    lines = _tess_lines(words)
    found = _labels_in(lines)
    if not found and not (more is not None and _hinted(words)):
        ctx.update(words=words, lines=lines)
        return [], ctx
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
    ctx.update(words=words, found=found, lines=lines)
    if not found:
        return [], ctx
    ink = _Ink(img)
    W, H = ink.W, ink.H
    yapi = Yapi(img, _page_h(words, H), words) if np is not None else None
    ctx.update(yapi=yapi, h=yapi.h if yapi else None)
    page_strong = any(s for _, _, s, _, _ in found)
    lab_boxes = [_lab_box(lines[li], a, b) for li, _, _, a, b in found]
    colon_boxes = [w.box for w in words if _colon_word(w) and w.conf >= 70]
    out: list[Field] = []
    for n_lab, (li, kind, strong, a, b) in enumerate(found):
        out += _label_fields(img, ink, yapi, words, lines, li, kind, strong, a, b, page_strong,
                             [q for i, q in enumerate(lab_boxes) if i != n_lab], colon_boxes)
    return out, ctx


def _label_fields(img, ink: "_Ink", yapi, words, lines, li, kind, strong, a, b, page_strong, other_labs,
                  colon_boxes) -> list[Field]:
    W, H = ink.W, ink.H
    right_edge = W - 1.0
    line = lines[li]
    lab = line[a:b + 1]
    lx0, lx1 = min(w.x0 for w in lab), max(w.x1 for w in lab)
    core = [w for w in lab if sum(c.isalpha() for c in w.text) >= 2] or lab
    ly0, ly1 = min(w.y0 for w in core), max(w.y1 for w in core)
    hs = sorted(w.h for w in lab if w.h > 0 and sum(c.isalpha() for c in w.text) >= 2)
    h = max(8.0, hs[len(hs) // 2] if hs else ly1 - ly0)
    if not strong:
        if ly1 < TOP_BAND * H or ly0 > (1 - BOTTOM_BAND) * H:
            return []
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
        return []
    labbox = (lx0, ly0, lx1, ly1)
    # açıklama etiketi ("(T.C. Kimlik No)"): değer çizginin üstünde/altında, sağındaki başka alanın
    caption = lab[0].text.startswith("(") or lab[-1].text.rstrip(".:").endswith(")") \
        or (a > 0 and line[a - 1].text.strip() == "(")
    x0 = lx1 + max(5.0, 0.2 * h)            # etiketin son harfi / ':' kapatma payına girmesin
    y0, y1 = ly0 - UP * h, ly1 + DOWN * h
    cy, band_h = (ly0 + ly1) / 2, 0.9 * h
    cands = {id(w): w for w in line[b + 1:]}
    cands.update({id(w): w for w in words if abs((w.y0 + w.y1) / 2 - cy) <= band_h and w.x0 > lx1})
    bnd = _next_boundary(sorted(cands.values(), key=lambda w: w.x0), x0)
    xr = min(right_edge, bnd - 2) if bnd is not None else right_edge
    # etiket satırı zaten kapalı (yeniden tarama)
    if xr - x0 >= h and ink.dark_frac((x0, ly0, xr, ly1)) >= DONE_DARK:
        return []
    adaylar: list[_Aday] = []
    for yon, box in [] if caption else _ink_candidates(ink, words, lines, li, kind, strong, page_strong, lab, labbox, h, colon,
                                    x0, xr, y0, y1, cands, right_edge, yapi):
        if yapi is not None and yapi.ink_frac(box) < MIN_INK:
            continue                         # "mürekkep" yalnız kılavuz noktalarıymış
        adaylar.append(_Aday(yon, box, "murekkep", max(0.0, (box[0] - lx1) / h) if yon == "sag"
                             else max(0.0, (box[1] - ly1) / h), True))
    if yapi is not None:
        adaylar += _struct_candidates(ink, yapi, labbox, h, colon, x0, xr, right_edge, other_labs + colon_boxes,
                                      other_labs)
    adaylar = [c for c in adaylar if c.box[2] - c.box[0] >= h * 0.8 and c.box[3] - c.box[1] >= 4
               and ink.dark_frac(c.box) < DONE_DARK and not (caption and c.yon in ("sag", "sol"))]
    if not strong and not page_strong:
        # zayıf etiket, form bağlamı yok: yalnız el yazısı mürekkepli alan
        adaylar = [c for c in adaylar if c.ink and _handwritten(c.box, words, ink)]
    if not adaylar:
        if strong or page_strong:
            # etiket bulunduysa alan her durumda kapatılır (kaçırmak pahalı): etiketin sağındaki satır bandı
            box = (x0, ly0 - 0.6 * h, min(xr, x0 + 15 * h), ly1 + 0.6 * h)
            if box[2] - box[0] >= h and ink.dark_frac(box) < DONE_DARK:
                return [Field(kind, _f(box), strong, "kapatildi", KIND, 0.45,
                              f"{_TUR_AD[kind]} etiketinin sağı (alan yapısı bulunamadı)")]
        return []
    # aynı yöndeki adayları birleştir (yapı + üstündeki el yazısı tek alan)
    by_dir: dict = {}
    for c in adaylar:
        by_dir.setdefault(c.yon, []).append(c)
    merged = []
    for yon, cs in by_dir.items():
        cs.sort(key=lambda c: c.puan)
        best = cs[0]
        box = best.box
        for c in cs[1:]:
            if _iou(box, c.box) > 0 or _near(box, c.box, h):
                box = _union(box, c.box)
        yps = {c.yapi for c in cs}
        yp = next((y for y in ("tarak", "hucre", "nokta", "cizgi") if y in yps), best.yapi)
        ink_any = any(c.ink for c in cs) or (yapi.ink_frac(box) if yapi is not None else ink.ink_frac(box)) >= MIN_INK
        merged.append(_Aday(yon, box, yp, min(c.mesafe for c in cs), ink_any))
    merged.sort(key=lambda c: c.puan)
    best = merged[0]
    out_boxes = [(best, "kapatildi")]
    for c in merged[1:]:
        if c.puan - best.puan <= BELIRSIZ and not _iou(c.box, best.box) > 0.3:
            out_boxes.append((c, "kapatildi" if c.ink else "onay_bekliyor"))
    res = []
    for c, karar in out_boxes:
        boxes = [c.box]
        if kind == "adres" and karar == "kapatildi":
            boxes += _continuation(lines, li, lx0, c.box[2], max(ly1, c.box[3] - 1.2 * h), h, ink, right_edge)
            if yapi is not None:
                boxes += _guide_continuation(yapi, lx0, c.box, h, other_labs + colon_boxes)
        g = 0.75 if (c.ink and c.yapi != "murekkep") else 0.6 if c.yapi != "murekkep" else 0.55
        if karar == "onay_bekliyor":
            g = 0.4
        neden = f"{_TUR_AD[kind]} etiketinin {_YON_AD[c.yon]} {_YAPI_AD[c.yapi]}"
        if not c.ink and c.yapi != "murekkep":
            neden += " (boş görünüyor)"
        for bx in boxes:
            res.append(Field(kind, _f(bx), strong, karar, KIND, g, neden))
    return res


def _f(b):
    return tuple(float(v) for v in b)


def _union(p, q):
    return (min(p[0], q[0]), min(p[1], q[1]), max(p[2], q[2]), max(p[3], q[3]))


def _near(p, q, h):
    return min(p[2], q[2]) - max(p[0], q[0]) > -h and min(p[3], q[3]) - max(p[1], q[1]) > -0.3 * h


def _ink_candidates(ink, words, lines, li, kind, strong, page_strong, lab, labbox, h, colon, x0, x1, y0, y1,
                    cands, right_edge, yapi=None):
    """Eski kural (yapısız mürekkep): etiketin sağındaki satır bandı (dikey tablo çizgisinde, sonraki
    etikette durur) ya da `:`'sız tablo etiketinin alttaki hücresi."""
    lx0, ly0, lx1, ly1 = labbox
    out = []
    rules = ink.rules(x0, x1, ly0 - 0.5 * h, ly1 + 0.45 * h, 0.3 * h)
    if yapi is not None:
        # bant boyu dikey koşu el yazısı rakam vuruşu (1, 4, 7) olabilir: yalnız doğrulanmış tablo
        # çizgisi ve koyu blok (önceki kapatma) sınır sayılır
        rules = [r for r in rules if r[2] or any(abs(v.x_at((ly0 + ly1) / 2) - (r[0] + r[1]) / 2) <= 4 + (r[1] - r[0])
                                                 for v in yapi.kurallar_v)]
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
    if x1 - x0 < h:
        return out
    vr = ink.vrun((x0, y0, x1, y1), (ly0 + ly1) / 2, h)
    if vr is not None:
        y0, y1 = min(vr[0], ly0), max(vr[1], ly1)
    main = (x0, y0, x1, y1)
    if ink.dark_frac(main) < DONE_DARK and ink.ink_frac(main) >= MIN_INK:
        if strong or page_strong or _handwritten(main, words, ink):
            out.append(("sag", main))
    elif not colon and not blocked and ink.ink_frac(main) < MIN_INK \
            and not any(w.text.strip().startswith(":") for w in cands.values()):
        rr = ink.rules(lx1 + 1, min(right_edge, lx1 + 12 * h), ly0 - 0.5 * h, ly1 + 0.45 * h, 0.3 * h)
        bx1 = rr[0][0] - 1 if rr else min(right_edge, lx1 + 8 * h)
        below = (lx0 - 0.3 * h, ly1 + 0.2 * h, bx1, ly1 + 3.2 * h)
        vb = ink.vrun(below, (below[1] + below[3]) / 2, h)
        if vb is not None:
            below = (below[0], vb[0], below[2], vb[1])
        if ink.dark_frac(below) < DONE_DARK and ink.ink_frac(below) >= MIN_INK and (strong or page_strong):
            out.append(("alt", below))
    return out


def _owner(seg_box, seg_y, labs, h):
    """Parçanın sahibi: aynı bantta hemen solunda biten etiket/`:`'lı belirteç (kutusu) ya da None."""
    best, bd = None, None
    for q in labs:
        qh = max(8.0, q[3] - q[1])
        if not (q[1] - 0.4 * qh <= seg_y <= q[3] + 1.0 * qh):
            continue
        if q[2] > seg_box[0] + 1.5 * qh or seg_box[0] - q[2] > 6 * qh:
            continue
        d = abs(seg_box[0] - q[2])
        if bd is None or d < bd:
            best, bd = q, d
    return best


def _struct_candidates(ink, yapi: Yapi, labbox, h, colon, x0, xr, right_edge, labs, other_labs) -> list[_Aday]:
    lx0, ly0, lx1, ly1 = labbox
    lcx = (lx0 + lx1) / 2
    out: list[_Aday] = []

    def has_ink(box):
        return yapi.ink_frac(box) >= MIN_INK

    def clip_x1(box_x0, y, x1):
        # aynı bantta sağdaki ilk etiket/`:`'lı belirteçte dur
        for q in labs:
            if q[0] > box_x0 + h and q[1] - h <= y <= q[3] + h:
                x1 = min(x1, q[0] - 2)
        return x1

    c = yapi.cell(labbox)
    # yatay kılavuz / alt çizgi (etiketin tablo hücresinin kenar çizgileri değil)
    for s in yapi.yatay:
        if c is not None and any(abs(s.y_at(lcx) - e) <= 4 for e in (c[1], c[3])):
            continue
        # sağ: etiket bitimine yakın başlayan, etiket satırı tabanında
        sy = s.y_at(max(s.x0, lx1))
        sc = s.y_at(lcx)                       # etiket ortası hizasında (alt/üst için)
        if s.x1 > lx1 + 2 * h and lx1 - 1.0 * h <= s.x0 <= lx1 + 6 * h and ly0 + 0.2 * h <= sy <= ly1 + 1.0 * h \
                and s.x0 < xr:
            bx0 = max(x0, s.x0)
            bx1 = min(s.x1, xr)
            ys = [s.y_at(bx0), s.y_at(bx1)]
            box = (bx0, min(min(ys) - 2.0 * h, ly0 - 1.0 * h), bx1, max(ys) + 0.45 * h)
            out.append(_Aday("sag", box, s.tur, max(0.0, s.x0 - lx1) / h, has_ink(box)))
            continue
        own = _owner(s.box, s.ya, labs, h)
        if own is not None:
            continue
        sy = sc
        cover = min(s.x1, lx1 + h) - max(s.x0, lx0 - h)
        # alt: etiketin altında, x'i etiketle örtüşen, sahipsiz kılavuz
        if cover >= 0.5 * (lx1 - lx0) and ly1 + 0.3 * h < sy <= ly1 + 3.0 * h and s.x0 >= lx0 - 3 * h \
                and not _blocked_between(other_labs, labbox, sy, h):
            bx1 = clip_x1(s.x0, sy, s.x1)
            box = (s.x0, max(ly1 + 0.15 * h, min(s.y_at(s.x0), s.y_at(bx1)) - 2.0 * h), bx1,
                   max(s.y_at(s.x0), s.y_at(bx1)) + 0.45 * h)
            out.append(_Aday("alt", box, s.tur, (sy - ly1) / h, has_ink(box)))
        # üst: etiket çizginin altında açıklama ("(T.C. Kimlik No)"), `:`'sız
        elif not colon and s.x0 - h <= lcx <= s.x1 + h and ly0 - 2.2 * h <= sy < ly0 - 0.1 * h:
            ys = [s.y_at(s.x0), s.y_at(s.x1)]
            box = (s.x0, min(ys) - 2.0 * h, s.x1, min(ly0 - 1, max(ys) + 0.3 * h))
            out.append(_Aday("ust", box, s.tur, (ly0 - sy) / h, has_ink(box)))
        # sol: etiketten hemen önce biten kılavuz, `:`'sız
        elif not colon and lx0 - 6 * h <= s.x1 <= lx0 + h and ly0 <= sy <= ly1 + 1.0 * h and s.x0 < lx0 - 2 * h:
            ys = [s.y_at(s.x0), s.y_at(s.x1)]
            box = (s.x0, min(ys) - 2.0 * h, min(s.x1, lx0 - 2), max(ys) + 0.45 * h)
            out.append(_Aday("sol", box, s.tur, (lx0 - s.x1) / h, has_ink(box)))
    # kutucuk / tarak dizileri
    for t in yapi.taraklar:
        bx = t.box
        tcy = (bx[1] + bx[3]) / 2
        pad = 0.15 * h
        box = (bx[0] - pad, bx[1] - 0.5 * h, bx[2] + pad, bx[3] + pad)
        if lx1 - h <= bx[0] <= lx1 + 8 * h and bx[1] - h <= (ly0 + ly1) / 2 <= bx[3] + h and bx[0] < xr:
            out.append(_Aday("sag", (max(box[0], lx1 + 2), box[1], box[2], box[3]), "tarak",
                             max(0.0, bx[0] - lx1) / h, has_ink(box)))
        elif _owner(bx, tcy, labs, h) is None and min(bx[2], lx1 + h) - max(bx[0], lx0 - h) > 0 \
                and ly1 < bx[1] <= ly1 + 3 * h and not _blocked_between(other_labs, labbox, bx[1], h):
            out.append(_Aday("alt", (box[0], max(box[1], ly1 + 0.1 * h), box[2], box[3]), "tarak",
                             (bx[1] - ly1) / h, has_ink(box)))
        elif not colon and min(bx[2], lx1) - max(bx[0], lx0) > 0 and ly0 - 3 * h <= bx[3] < ly0:
            out.append(_Aday("ust", (box[0], box[1], box[2], min(box[3], ly0 - 1)), "tarak",
                             (ly0 - bx[3]) / h, has_ink(box)))
    # tablo hücresi (komşu hücre: yapısal bitişiklik, mesafe hücre içi boşluktan bağımsız)
    if c is not None:
        t = 0.12 * h
        rc = yapi.right_cell(c)
        if rc is not None and not any(_inside(q, rc, 0.5) for q in labs):
            box = (rc[0] + t, rc[1] + t, rc[2] - t, rc[3] - t)
            out.append(_Aday("sag", box, "hucre", 0.3, has_ink(box)))
        bc = yapi.below_cell(c)
        if bc is not None and not any(_inside(q, bc, 0.5) for q in labs):
            box = (bc[0] + t, bc[1] + t, bc[2] - t, bc[3] - t)
            out.append(_Aday("alt", box, "hucre", 0.3 + max(0.0, bc[1] - ly1) / h, has_ink(box)))
        if colon and c[2] - lx1 > 3 * h:
            # aynı hücrede "Etiket: ....": hücrenin kalanı
            box = (x0, c[1] + t, c[2] - t, c[3] - t)
            out.append(_Aday("sag", box, "hucre", 0.2, has_ink(box)))
    return out


def _blocked_between(labs, labbox, y, h) -> bool:
    """Etiketle `y` arasında başka bir etiket satırı var mı (alt aday başka etiketin alanıdır)."""
    lx0, ly0, lx1, ly1 = labbox
    for q in labs:
        if ly1 <= (q[1] + q[3]) / 2 < y and q[0] < lx1 + 2 * h and q[2] > lx0 - 2 * h:
            return True
    return False


def _guide_continuation(yapi: Yapi, lx0, box, h, labs) -> list:
    """Adres: alanın altındaki sahipsiz kılavuz satırları (en çok iki)."""
    out = []
    bottom = box[3]
    for _ in range(2):
        nxt = None
        for s in yapi.yatay:
            sy = s.y_at(s.x0)
            if bottom < sy <= bottom + 2.6 * h and s.x0 <= box[2] and s.x1 >= lx0 and s.x0 >= lx0 - 3 * h \
                    and _owner(s.box, sy, labs, h) is None:
                if nxt is None or sy < nxt.y_at(nxt.x0):
                    nxt = s
        if nxt is None:
            break
        ys = [nxt.y_at(nxt.x0), nxt.y_at(nxt.x1)]
        b = (nxt.x0, max(bottom, min(ys) - 2.0 * h), nxt.x1, max(ys) + 0.45 * h)
        out.append(b)
        bottom = b[3]
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



# ---------------------------------------------------------------- rakam dizisi sezgisi (etiketsiz)
#
# El yazısı kimlik/öğrenci no okunmasa da biçimi görünür: benzer yükseklikte, aynı taban üzerinde yan
# yana dizilmiş 10-13 ayrık bileşen (11: kimlik, 12: öğrenci no). Basılı metin (OCR'ın güvenle okuduğu
# kelimeler) ve form çizgileri (kılavuz, tarak, tablo) bileşenlerden çıkarılır. Sayı uzunluğu yalnız
# destekleyici sinyaldir (güven); kişisel veri etiketi yakınındaki dizi kapatılır, değilse onaya düşer.

DIZI_MIN, DIZI_MAX = 10, 13


@dataclass
class _Glyph:
    x0: float
    y0: float
    x1: float
    y1: float
    n: int

    @property
    def w(self):
        return self.x1 - self.x0

    @property
    def h(self):
        return self.y1 - self.y0

    @property
    def cx(self):
        return (self.x0 + self.x1) / 2

    @property
    def cy(self):
        return (self.y0 + self.y1) / 2


def _components_np(M) -> list[_Glyph]:
    """8-bağlantılı bileşenler (koşu tabanlı birleşim-bul)."""
    ys, a, b = _runs(M)
    n = len(ys)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    prev: list = []
    cur: list = []
    cy = -2
    for i in range(n):
        y = int(ys[i])
        if y != cy:
            prev = cur if y == cy + 1 else []
            cur = []
            cy = y
            k = 0
        while k < len(prev) and b[prev[k]] < a[i]:   # b dahil değil: 8-bağlantı için b >= a
            k += 1
        j = k
        while j < len(prev) and a[prev[j]] <= b[i]:
            ri, rj = find(i), find(prev[j])
            if ri != rj:
                parent[ri] = rj
            j += 1
        cur.append(i)
    comps: dict = {}
    for i in range(n):
        r = find(i)
        c = comps.get(r)
        y = int(ys[i])
        if c is None:
            comps[r] = [int(a[i]), y, int(b[i]), y + 1, int(b[i] - a[i])]
        else:
            c[0] = min(c[0], int(a[i]))
            c[1] = min(c[1], y)
            c[2] = max(c[2], int(b[i]))
            c[3] = max(c[3], y + 1)
            c[4] += int(b[i] - a[i])
    return [_Glyph(*c) for c in comps.values()]


def _merge_fragments(gs: list[_Glyph], h: float) -> list[_Glyph]:
    """Kopuk vuruşlu rakam (5'in şapkası, 4'ün çubuğu): x'te büyük ölçüde örtüşen, dikeyde yakın parçalar birleşir."""
    gs = sorted(gs, key=lambda g: g.x0)
    changed = True
    while changed:
        changed = False
        out: list[_Glyph] = []
        for g in gs:
            for o in out:
                ov = min(o.x1, g.x1) - max(o.x0, g.x0)
                vg = max(o.y0, g.y0) - min(o.y1, g.y1)
                if ov >= 0.5 * min(o.w, g.w) and vg <= 0.3 * h:
                    o.x0, o.y0, o.x1, o.y1 = min(o.x0, g.x0), min(o.y0, g.y0), max(o.x1, g.x1), max(o.y1, g.y1)
                    o.n += g.n
                    changed = True
                    break
            else:
                out.append(_Glyph(g.x0, g.y0, g.x1, g.y1, g.n))
        gs = out
    return gs


def rakam_dizileri(yapi: "Yapi", words: list[Word], h: float, exclude=()) -> list[tuple]:
    """→ [(kutu, bileşen sayısı)] etiketsiz el yazısı rakam dizisi adayları (görüntü pikseli).
    `exclude`: bileşeni sayılmayacak kutular (bulunan etiketler; düşük güvenle okunmuş olsalar da)."""
    M = yapi.B & ~yapi.line_mask
    # yalnız harfli basılı kelimeler çıkarılır: OCR'ın (güvenle bile) rakam okuduğu el yazısı dizi adaydır
    # (`:` ile biten etiket belirteci düşük güvenle okunmuş olsa da basılıdır)
    printed = [w.box for w in words if w.conf >= (40 if w.text.rstrip(".)").endswith(":") else 60)
               and sum(c.isalpha() for c in w.text) >= 2
               and sum(c.isdigit() for c in w.text) < 0.3 * len(w.text)] + list(exclude)
    gs = []
    for g in _components_np(M):
        if g.h < 0.45 * h or g.h > 3.5 * h or g.w > 1.4 * g.h + 2 or g.n < 0.03 * h * h:
            continue
        if any(q[0] - 2 <= g.cx <= q[2] + 2 and q[1] - 2 <= g.cy <= q[3] + 2 for q in printed):
            continue
        gs.append(g)
    gs = _merge_fragments(gs, h)
    gs = [g for g in gs if g.w <= 1.4 * g.h + 2]
    gs.sort(key=lambda g: g.x0)
    nxt: dict = {}
    for i, g in enumerate(gs):
        best, bg = None, None
        for j in range(i + 1, len(gs)):
            q = gs[j]
            mh = max(g.h, q.h)
            if q.x0 - g.x1 > 1.3 * mh:
                if q.x0 - g.x1 > 4 * mh:
                    break
                continue
            if q.cx <= g.cx or q.x0 - g.x1 < -0.35 * min(g.w, q.w):
                continue
            if not (0.6 <= q.h / g.h <= 1.65) or abs(q.cy - g.cy) > 0.45 * mh:
                continue
            gap = q.x0 - g.x1
            if bg is None or gap < bg:
                best, bg = j, gap
        if best is not None:
            nxt[i] = (best, bg)
    pred: dict = {}
    for i, (j, gap) in nxt.items():
        if j not in pred or gap < nxt[pred[j]][1]:
            pred[j] = i
    succ = {i: j for j, i in pred.items()}
    out = []
    for s in range(len(gs)):
        if s in pred:
            continue
        chain = [s]
        while chain[-1] in succ:
            chain.append(succ[chain[-1]])
        if not (DIZI_MIN <= len(chain) <= DIZI_MAX):
            continue
        cs = [gs[i] for i in chain]
        hs = sorted(g.h for g in cs)
        mh = hs[len(hs) // 2]
        if any(not (0.6 <= g.h / mh <= 1.6) for g in cs):
            continue
        pad = 0.3 * mh
        box = (min(g.x0 for g in cs) - pad, min(g.y0 for g in cs) - pad, max(g.x1 for g in cs) + pad,
               max(g.y1 for g in cs) + pad)
        out.append((box, len(chain)))
    return out


def _near_label(box, labs, h) -> bool:
    for q in labs:
        qh = max(8.0, q[3] - q[1])
        cy, qcy = (box[1] + box[3]) / 2, (q[1] + q[3]) / 2
        if abs(cy - qcy) <= 1.5 * max(qh, h) and box[0] >= q[2] - qh and box[0] - q[2] <= 15 * qh:
            return True
        if q[3] - 0.5 * qh <= box[1] <= q[3] + 3 * max(qh, h) and box[0] <= q[2] + 10 * qh and box[2] >= q[0] - 2 * qh:
            return True
    return False


def _nearest_left_label(box, labs, h):
    best, bd = None, None
    cy = (box[1] + box[3]) / 2
    for q in labs:
        qh = max(8.0, q[3] - q[1])
        if abs(cy - (q[1] + q[3]) / 2) <= 1.5 * max(qh, h) and q[2] <= box[0] + qh:
            d = box[0] - q[2]
            if bd is None or d < bd:
                best, bd = q, d
    return best


# ---------------------------------------------------------------- tek giriş: el yazısı alan bölgeleri

TUR = "el_yazisi_alan"
_KAYNAK_SIRA = {KIND: 0, "rakam_dizisi": 1, "sablon": 2}


def _harf_okunan(box, words: list[Word]) -> bool:
    """Dizinin bileşenlerinin çoğu OCR'da harf okunuyor mu (basılı/el yazısı kelime, rakam dizisi değil)."""
    harf = rakam = 0
    for w in words:
        cx, cy = (w.x0 + w.x1) / 2, (w.y0 + w.y1) / 2
        if box[0] <= cx <= box[2] and box[1] <= cy <= box[3]:
            harf += sum(c.isalpha() for c in w.text)
            rakam += sum(c.isdigit() for c in w.text)
    return harf > rakam


def el_yazisi_bolgeleri(img, words: list[Word], *, sayfa: int = 1, dosya: str = "", olcek: float = 1.0,
                        more=None, sablonlar=None, kararlar: dict | None = None, sira0: int = 1,
                        rakam: bool = True, yalniz_sablon: bool = False) -> list[dict]:
    """Sayfa görüntüsü + OCR kelimeleri → el yazısı alan bölgeleri (bölge sözleşmesi biçiminde).

    - `kaynak`: `etiket_alani` (basılı etiketin geometrik alanı), `rakam_dizisi` (etiketsiz 10-13 bileşenli
      el yazısı dizisi), `sablon` (aynı formun önceki kopyasında insanın kapattığı bölge, hizalanmış);
    - `kutu`: PDF puanı (`olcek` = piksel/puan, ör. 300 dpi için 300/72); `id`: `<dosya>-s<sayfa>-<sıra>`
      (`sira0`'dan; sıra kaynak ve konumla kararlı);
    - `kararlar` ({id: "kapat"|"birak"}): verilirse bölgeye uygulanır; `sablonlar` (`sablon.SablonBellegi`)
      verilirse "kapat" kararlı bölgeler şablona öğretilir ve eşleşen şablonun bölgeleri uygulanır; kullanıcı
      çiziminden öğrenilen şablon bölgesi (`oneri`) yalnız `onay_bekliyor` öneri olur;
    - `rakam`: etiketsiz rakam dizisi araması (metin katmanlı / güvenle OCR'lanan basılı sayfada False);
      bileşenlerinin çoğu harf okunan dizi düşer;
    - `yalniz_sablon`: alan/rakam dizisi araması yapılmaz, yalnız şablon belleği uygulanır (metin katmanlı sayfa).
    Değer okunmaz, yazılmaz."""
    kararlar = kararlar or {}
    if yalniz_sablon:
        fields, ctx = [], {"words": list(words or []), "yapi": None, "lines": None, "found": []}
        rakam = False
    else:
        fields, ctx = alan_adaylari(img, words, more=more)
    words2 = ctx["words"] or list(words or [])
    regs: list[dict] = []
    for f in fields:
        regs.append({"_box": f.box, "karar": f.karar, "neden": f.neden, "kaynak": KIND, "guven": f.guven,
                     "_kind": f.kind})
    yapi = ctx.get("yapi")
    if np is not None:
        if yapi is None:
            yapi = Yapi(img, _page_h(words2, img.size[1]), words2)
        h = yapi.h
        lines = ctx["lines"] or _tess_lines(words2)
        pii_labs = [_lab_box(lines[li], a, b) for li, _, _, a, b in ctx["found"]]
        other = [w.box for w in words2 if w.conf >= 40 and w.text.rstrip(".)").endswith(":")
                 and sum(c.isalpha() for c in w.text) >= 2 and not any(_overlap(w.box, q) for q in pii_labs)]
        for box, n in (rakam_dizileri(yapi, words2, h, exclude=pii_labs) if rakam else []):
            if _harf_okunan(box, words2):
                continue                          # bileşenlerin çoğu harf: el yazısı kelime, rakam dizisi değil
            host = next((r for r in regs if r["karar"] == "kapatildi" and _inside(box, r["_box"], 0.5)), None)
            if host is not None:                  # etiket alanının içinde: alan diziyi tümüyle kapsasın
                host["_box"] = _union(host["_box"], box)
                continue
            uz = {11: "11 haneli (kimlik no uzunluğu)", 12: "12 haneli (öğrenci no uzunluğu)"}.get(n, f"{n} bileşenli")
            g = 0.6 if n in (11, 12) else 0.45
            left = _nearest_left_label(box, pii_labs + other, h)
            if left is not None and left in other and not _near_label(box, pii_labs, h):
                continue                          # başka (kişisel olmayan) etiketin değeri: ad, bölüm …
            if _near_label(box, pii_labs, h):
                regs.append({"_box": box, "karar": "kapatildi", "kaynak": "rakam_dizisi", "guven": g + 0.2,
                             "neden": f"etiket yakınında {uz} el yazısı dizi"})
            else:
                regs.append({"_box": box, "karar": "onay_bekliyor", "kaynak": "rakam_dizisi", "guven": g,
                             "neden": f"etiketsiz {uz} el yazısı dizi"})
    regs.sort(key=lambda r: (_KAYNAK_SIRA[r["kaynak"]], round(r["_box"][1]), round(r["_box"][0])))
    k = sira0
    for r in regs:
        r["id"] = f"{dosya}-s{sayfa}-{k}"
        k += 1
    if sablonlar is not None and np is not None:
        from . import sablon as SB
        iz = SB.parmak_izi(words2, img.size[0], img.size[1], yapi)
        onay = [r["_box"] for r in regs if kararlar.get(r["id"]) == "kapat"]
        if onay:
            sablonlar.ogren(iz, onay, kaynak=f"{dosya}-s{sayfa}")
        for u in sablonlar.uygula(iz):
            box = u["kutu"]
            if u.get("oneri"):                    # kullanıcı çizimi: başka belgede yalnız öneri (kendiliğinden kapatılmaz)
                if any(_iou(box, r["_box"]) >= 0.4 or _inside(box, r["_box"], 0.8) for r in regs):
                    continue
                regs.append({"_box": box, "karar": "onay_bekliyor", "kaynak": "sablon", "guven": min(u["guven"], 0.5),
                             "neden": f"form şablonu {u['sablon']}: kullanıcının aynı formda çizdiği bölge (öneri)"})
                regs[-1]["id"] = f"{dosya}-s{sayfa}-{k}"
                k += 1
                continue
            hit = next((r for r in regs if _iou(box, r["_box"]) >= 0.4 or _inside(box, r["_box"], 0.8)), None)
            if hit is not None:
                if u["guvenilir"] and hit["karar"] == "onay_bekliyor":
                    hit["karar"] = "kapatildi"
                    hit["neden"] += " (şablonla doğrulandı)"
                continue
            if u["guvenilir"]:
                regs.append({"_box": box, "karar": "kapatildi", "kaynak": "sablon", "guven": u["guven"],
                             "neden": f"form şablonu {u['sablon']} (hizalama hatası {u['hata']:.1f} px)"})
            else:
                regs.append({"_box": box, "karar": "onay_bekliyor", "kaynak": "sablon", "guven": u["guven"],
                             "neden": f"form şablonu {u['sablon']}, hizalama güvenilmez ({u['neden']})"})
            regs[-1]["id"] = f"{dosya}-s{sayfa}-{k}"
            k += 1
        if sablonlar.degisti:
            sablonlar.kaydet()
    out = []
    W, H = img.size
    for r in regs:
        x0, y0, x1, y1 = r["_box"]
        x0, y0, x1, y1 = max(0.0, x0), max(0.0, y0), min(float(W), x1), min(float(H), y1)
        karar = r["karar"]
        d = kararlar.get(r["id"])
        neden = r["neden"]
        if d == "kapat":
            karar = "kapatildi"
            neden += " (insan onayı)"
        elif d == "birak":
            karar = "birakildi"
            neden += " (insan: bırak)"
        out.append({"id": r["id"], "sayfa": sayfa,
                    "kutu": [round(v / olcek, 2) for v in (x0, y0, x1, y1)],
                    "tur": TUR, "karar": karar, "neden": neden, "kaynak": r["kaynak"],
                    "guven": round(min(1.0, r["guven"]), 2), "geri_basilan": None})
    return out
