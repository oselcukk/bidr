"""İmza maskeleme için sentetik belge üreticisi (gerçek veri yok; adlar uydurma).

Yalnız Pillow ve PyMuPDF kullanır (bidr'e bağımlı değil): aynı set eski ve yeni kodla ölçülebilsin.
Her üretici imzalı belgeyi yazar ve imzaların "gerçek" piksel maskesini döndürür: aynı sayfa imzalı
ve imzasız çizilir, farkı imza pikselleridir (`Gercek`). Kaçırma ölçüsü: maskeli kopyada imza
çekirdek piksellerinin ne kadarının özgün rengiyle görünür kaldığı.
"""
from __future__ import annotations

import io
import math
import random
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

PPI = 150                                   # taranmış sayfa görüntüsü çözünürlüğü
A4 = (1240, 1754)                           # 150 ppi A4
SIYAH_MUREKKEP = (40, 40, 40)               # siyah kutudan (0) ve etiket grisinden (100) ayrılsın
MAVI = (25, 45, 200)

_FONTS = ("DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
          "/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial.ttf",
          "C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf")


def font(size: int):
    for f in _FONTS:
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


@dataclass
class Gercek:  # noqa: D101
    """Bir sayfadaki imzalar: (sayfa, imza piksel maskesi `PPI` çözünürlükte, ad)."""
    imzalar: list = field(default_factory=list)      # [(sayfa, maske L, ad)]
    yanlis: list = field(default_factory=list)       # imza olmayan, kapatılmaması beklenen öğeler [(sayfa, kutu px, ad)]


def imza_ciz(d: ImageDraw.ImageDraw, x: float, y: float, w: float = 220, h: float = 60, color=SIYAH_MUREKKEP,
             seed: int = 1, width: int = 3) -> None:
    """El yazısı benzeri imza: döngülü serbest eğri + kuyruk (tohuma göre farklı)."""
    rnd = random.Random(seed)
    f1, f2, f3 = rnd.uniform(18, 30), rnd.uniform(6, 11), rnd.uniform(2, 4)
    amp = rnd.uniform(10, 20)
    pts = []
    for i in range(180):
        t = i / 179
        pts.append((x + t * w + amp * math.sin(t * f1), y + h / 2 + h / 2 * math.sin(t * f2) * math.cos(t * f3)))
    d.line(pts, fill=color, width=width, joint="curve")
    d.line([(x + 0.1 * w, y + h - 4), (x + 0.9 * w, y + rnd.uniform(4, 14))], fill=color, width=max(2, width - 1))


def _bos():
    return Image.new("RGB", A4, "white")


def _maske(imzali, imzasiz):
    diff = ImageChops.difference(imzali.convert("L"), imzasiz.convert("L"))
    return diff.point(lambda v: 255 if v >= 60 else 0)


def pdf_goruntu_sayfalari(path: Path, sayfalar: list) -> None:
    """Taranmış PDF: her sayfa tek tam sayfa görüntü (metin katmanı yok)."""
    import pymupdf
    doc = pymupdf.open()
    for img in sayfalar:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        page = doc.new_page(width=595, height=842)
        page.insert_image(page.rect, stream=buf.getvalue())
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    doc.close()


# ---------------------------------------------------------------- 1. taranmış imza çizelgesi

COLS = (100, 190, 560, 860, 1140)           # Sıra | Adı Soyadı | Unvanı | İmza
ROW_H = 95


def _cizelge_sayfasi(d, *, baslik: bool, satirlar: list, imza: bool, tasan: set, y0: int = 220, renk=SIYAH_MUREKKEP):
    f = font(30)
    y = y0
    if baslik:
        d.text((100, 120), "Bölüm Toplantısı Katılım Çizelgesi", fill="black", font=font(36))
    rows = (["Sıra", "Adı Soyadı", "Unvanı", "İmza"] if baslik else None)
    n = len(satirlar) + (1 if rows else 0)
    for i in range(n + 1):
        d.line([(COLS[0], y + i * ROW_H), (COLS[-1], y + i * ROW_H)], fill="black", width=2)
    for x in COLS:
        d.line([(x, y), (x, y + n * ROW_H)], fill="black", width=2)
    r0 = 0
    if rows:
        for x, t in zip(COLS, rows):
            d.text((x + 14, y + 30), t, fill="black", font=f)
        r0 = 1
    for j, (no, ad, unvan) in enumerate(satirlar):
        yy = y + (r0 + j) * ROW_H
        d.text((COLS[0] + 14, yy + 30), str(no), fill="black", font=f)
        d.text((COLS[1] + 14, yy + 30), ad, fill="black", font=f)
        d.text((COLS[2] + 14, yy + 30), unvan, fill="black", font=f)
        if imza:
            if no in tasan:   # unvan yazısının üstüne taşan imza
                imza_ciz(d, COLS[2] + 60, yy + 14, w=330, h=66, color=renk, seed=no)
            else:
                imza_ciz(d, COLS[3] + 30, yy + 16, w=215, h=60, color=renk, seed=no)
    return y + n * ROW_H


_ADLAR = ["Ayşe Demir", "Mehmet Kaya", "Zeynep Çelik", "Ali Şahin", "Elif Yıldız", "Can Öztürk", "Deniz Aydın",
          "Burak Koç", "Selin Arslan", "Emre Doğan", "Gül Kurt", "Hakan Özdemir", "İrem Aksoy", "Kerem Polat",
          "Leyla Erdem", "Murat Güneş", "Nazlı Taş", "Onur Bulut", "Pınar Uçar", "Rıza Çakır"]
_UNVAN = ["Prof. Dr.", "Doç. Dr.", "Dr. Öğr. Üyesi", "Arş. Gör.", "Öğr. Gör."]


def taranmis_cizelge(path: Path, *, sayfa: int = 3, satir: int = 13, tasan: tuple = (), renk=SIYAH_MUREKKEP,
                     imzali: bool = True) -> None:
    """Çok sayfalı taranmış imza çizelgesi; başlık (Sıra | Adı Soyadı | Unvanı | İmza) yalnız ilk sayfada."""
    pages = []
    no = 1
    for s in range(1, sayfa + 1):
        rows = []
        for _ in range(satir if s > 1 else satir - 1):
            rows.append((no, _ADLAR[(no - 1) % len(_ADLAR)], _UNVAN[(no - 1) % len(_UNVAN)]))
            no += 1
        img = _bos()
        _cizelge_sayfasi(ImageDraw.Draw(img), baslik=s == 1, satirlar=rows, imza=imzali, tasan=set(tasan),
                         y0=220 if s == 1 else 120, renk=renk)
        pages.append(img)
    pdf_goruntu_sayfalari(path, pages)


# ---------------------------------------------------------------- 2. metin katmanlı (vektör) çizelge

def _imza_png(w=220, h=64, seed=1, color=SIYAH_MUREKKEP) -> bytes:
    img = Image.new("RGB", (w, h), "white")
    imza_ciz(ImageDraw.Draw(img), 6, 2, w=w - 14, h=h - 6, color=color, seed=seed)
    b = io.BytesIO()
    img.save(b, format="PNG")
    return b.getvalue()


def _ttf() -> str | None:
    for f in _FONTS:
        if Path(f).is_file():
            return f
    return None


def metin_yaz(page, xy, text: str, size: float = 10) -> None:
    """Metin katmanına Türkçe harfleri doğru kodlanmış yazı (sistemde TTF varsa)."""
    f = _ttf()
    if f:
        page.insert_text(xy, text, fontsize=size, fontname="tr", fontfile=f)
    else:
        page.insert_text(xy, text, fontsize=size, fontname="helv")


def vektor_cizelge(path: Path, *, sayfa: int = 2, satir: int = 14, tasan: tuple = (), imzali: bool = True) -> dict:
    """Metin katmanlı PDF: vektör çizgili tablo, metin katmanında ad/unvan, imza hücrelerinde gömülü
    imza görüntüleri. Başlık yalnız ilk sayfada. → {"imzalar": [(sayfa, kutu pt)], "tasan": [(sayfa, kutu pt, ad, unvan)]}."""
    import pymupdf
    doc = pymupdf.open()
    cols = [50, 90, 260, 400, 560]
    rh = 40
    info = {"imzalar": [], "tasan": []}
    no = 1
    for s in range(1, sayfa + 1):
        page = doc.new_page(width=595, height=842)
        y = 90 if s == 1 else 50
        if s == 1:
            metin_yaz(page, (50, 60), "Bölüm Kurulu Katılım Çizelgesi", 14)
        n = satir + (1 if s == 1 else 0)
        for i in range(n + 1):
            page.draw_line((cols[0], y + i * rh), (cols[-1], y + i * rh), width=0.8)
        for x in cols:
            page.draw_line((x, y), (x, y + n * rh), width=0.8)
        r0 = 0
        if s == 1:
            for x, t in zip(cols, ["Sıra", "Adı Soyadı", "Unvanı", "İmza"]):
                metin_yaz(page, (x + 5, y + 24), t, 10)
            r0 = 1
        for j in range(satir):
            yy = y + (r0 + j) * rh
            ad, unvan = _ADLAR[(no - 1) % len(_ADLAR)], _UNVAN[(no - 1) % len(_UNVAN)]
            metin_yaz(page, (cols[0] + 5, yy + 24), str(no), 10)
            metin_yaz(page, (cols[1] + 5, yy + 24), ad, 10)
            metin_yaz(page, (cols[2] + 5, yy + 24), unvan, 10)
            if imzali:
                if no in tasan:
                    r = pymupdf.Rect(cols[2] + 2, yy + 2, cols[3] + 110, yy + rh - 2)
                    page.insert_image(r, stream=_imza_png(496, 64, seed=no), keep_proportion=False)
                    info["tasan"].append((s, tuple(r), ad, unvan))
                else:
                    r = pymupdf.Rect(cols[3] + 12, yy + 5, cols[4] - 12, yy + rh - 5)
                    page.insert_image(r, stream=_imza_png(seed=no))
                info["imzalar"].append((s, tuple(r)))
            no += 1
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    doc.close()
    return info


# ---------------------------------------------------------------- 3. tutanak (imza bloğu)

_GOVDE = ["Bölüm kurulu toplanarak gündemdeki maddeleri görüştü.",
          "Ders programı ve sınav takvimi oy birliği ile kabul edildi.",
          "Laboratuvar kullanım esasları yeniden düzenlendi.",
          "Bir sonraki toplantının ay sonunda yapılmasına karar verildi."]


def tutanak_goruntu(*, renk=SIYAH_MUREKKEP, ortusen: bool = False, imzali: bool = True):
    """Taranmış tutanak görüntüsü: gövde metni, sonda iki sütun imza bloğu (imza adın üstünde, altında
    unvan). `ortusen`: ilk imza ad satırının üstüne taşar."""
    img = _bos()
    d = ImageDraw.Draw(img)
    f = font(30)
    d.text((120, 120), "TOPLANTI TUTANAĞI", fill="black", font=font(38))
    y = 230
    for t in _GOVDE * 2:
        d.text((120, y), t, fill="black", font=f)
        y += 55
    for x, ad, unvan, seed in ((150, "Prof. Dr. Ayşe Demir", "Bölüm Başkanı", 11), (700, "Doç. Dr. Can Öztürk", "Üye", 12)):
        d.text((x, 1320), ad, fill="black", font=f)
        d.text((x, 1365), unvan, fill="black", font=f)
        if imzali:
            if ortusen and seed == 11:
                imza_ciz(d, x + 10, 1290, w=300, h=80, color=renk, seed=seed)
            else:
                imza_ciz(d, x + 20, 1200, w=240, h=70, color=renk, seed=seed)
    return img


def tutanak(path: Path, *, renk=SIYAH_MUREKKEP, ortusen: bool = False, imzali: bool = True) -> None:
    """Tutanak: `.pdf` ise taranmış PDF, değilse görsel dosya."""
    img = tutanak_goruntu(renk=renk, ortusen=ortusen, imzali=imzali)
    if path.suffix.lower() == ".pdf":
        pdf_goruntu_sayfalari(path, [img])
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        img.save(path)


# ---------------------------------------------------------------- 4-6. yanlış alarm kaynakları

def logo_ciz(d, x, y, seed=99):
    """Antet dışında, her sayfada aynı yerde tekrarlayan imza benzeri süs (kurum logosu çizgisi)."""
    imza_ciz(d, x, y, w=200, h=60, color=SIYAH_MUREKKEP, seed=seed, width=3)


def tekrar_eden_logo(path: Path, sayfa: int = 3, imzali: bool = True, etiketli: bool = False) -> Gercek:
    """Taranmış çok sayfalı yazı: her sayfada altta aynı yerde aynı imza benzeri süs. `etiketli`:
    yanında "İmza:" etiketi (her sayfaya yapıştırılmış aynı imza: süzülmemeli)."""
    g = Gercek()
    pages = []
    for s in range(1, sayfa + 1):
        img = _bos()
        d = ImageDraw.Draw(img)
        y = 160
        for t in _GOVDE * 2:
            d.text((120, y), t, fill="black", font=font(30))
            y += 55
        if etiketli:
            d.text((760, 1665), "İmza:", fill="black", font=font(30))
        if imzali or not etiketli:
            logo_ciz(d, 900, 1650)
        pages.append(img)
        g.yanlis.append((s, (880, 1630, 1120, 1730), "logo"))
    pdf_goruntu_sayfalari(path, pages)
    return g


def kase_ciz(d, cx, cy, r=110, color=(90, 40, 140)):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=4)
    d.ellipse([cx - r + 22, cy - r + 22, cx + r - 22, cy + r - 22], outline=color, width=2)
    for i in range(18):                  # çember üstünde harf benzeri küçük işaretler
        a = i / 18 * 2 * math.pi
        x, y = cx + (r - 11) * math.cos(a), cy + (r - 11) * math.sin(a)
        d.line([(x - 3, y - 3), (x + 3, y + 3)], fill=color, width=2)


def kaseli_sayfa(path: Path, imzali: bool = True) -> Gercek:
    img = _bos()
    d = ImageDraw.Draw(img)
    y = 200
    for t in _GOVDE * 2:
        d.text((120, y), t, fill="black", font=font(30))
        y += 55
    kase_ciz(d, 900, 1300)
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf_goruntu_sayfalari(path, [img])
    return Gercek(yanlis=[(1, (780, 1180, 1020, 1420), "kaşe")])


def not_dokumu(path: Path, imzali: bool = True) -> Gercek:
    """Tamamen basılı not dökümü (transcript): sık satırlar, etiketsiz; ortada küçük bir el işareti."""
    img = _bos()
    d = ImageDraw.Draw(img)
    f = font(22)
    d.text((100, 80), "NOT DÖKÜMÜ", fill="black", font=font(34))
    y = 300
    dersler = ["Matematik", "Fizik", "Kimya", "Programlama", "Olasılık", "Mekanik", "Elektrik", "Malzeme"]
    k = 0
    while y < 1600:
        for x in (100, 660):
            ders = dersler[k % len(dersler)]
            d.text((x, y), f"MAT{100 + k}  {ders}  3  4  AA  12.0", fill="black", font=f)
            k += 1
        y += 34
    # küçük el işareti (tik): imza değil
    d.line([(560, 1012), (575, 1030), (610, 990)], fill=(30, 30, 30), width=3)
    d.arc([520, 980, 640, 1050], 200, 340, fill=(30, 30, 30), width=3)
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf_goruntu_sayfalari(path, [img])
    return Gercek(yanlis=[(1, (510, 975, 650, 1055), "işaret")])


def metin_pdf_gorselli(path: Path, *, etiket: bool, e_imza: bool, imzali: bool = True) -> tuple:
    """Metin katmanlı resmî yazı; altta gömülü imza görüntüsü. `etiket`: altında ad/unvan satırı;
    `e_imza`: "güvenli elektronik imza ile imzalanmıştır" notu. → (imza kutusu pt)."""
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    y = 120
    metin_yaz(page, (60, 80), "T.C. ÖRNEK ÜNİVERSİTESİ", 13)
    for t in _GOVDE * 3:
        metin_yaz(page, (60, y), t, 11)
        y += 22
    r = pymupdf.Rect(360, 620, 520, 670)
    if imzali:
        page.insert_image(r, stream=_imza_png(320, 100, seed=7))
    if etiket:
        metin_yaz(page, (370, 690), "Prof. Dr. Ayşe Demir", 11)
        metin_yaz(page, (370, 706), "Bölüm Başkanı", 11)
    if e_imza:
        metin_yaz(page, (60, 800), "Bu belge güvenli elektronik imza ile imzalanmıştır.", 8)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    doc.close()
    return tuple(r)


# ---------------------------------------------------------------- ölçü

def gorunur_pay(masked_page_img, maske, orijinal) -> float:
    """Maskeli sayfa görüntüsünde (aynı `PPI`) imza çekirdek piksellerinin özgün rengiyle görünen payı."""
    m = masked_page_img.convert("RGB").resize(maske.size)
    o = orijinal.convert("RGB")
    md, od, kd = m.tobytes(), o.tobytes(), maske.tobytes()
    n = vis = 0
    for i, v in enumerate(kd):
        if v != 255:
            continue
        n += 1
        a, b = md[3 * i: 3 * i + 3], od[3 * i: 3 * i + 3]
        if max(abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2])) <= 20 and max(a) > 10:
            vis += 1          # özgün renginde ve karartma kutusu (siyah) değil
    return vis / n if n else 0.0


def pdf_sayfa_goruntusu(path: Path, sayfa: int):
    import pymupdf
    doc = pymupdf.open(str(path))
    pix = doc[sayfa - 1].get_pixmap(dpi=PPI)
    img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
    doc.close()
    return img


# ---------------------------------------------------------------- ölçüm seti

def vakalar():
    """(ad, dosya, üretici(path, imzali)). Yanlış alarm vakalarında `imzali` çizimi değiştirmez
    (imza yok); onlarda beklenen: dosya elle bakılmalı OLMAZ ve öğe kapatılmaz."""
    return [
        ("taranmış çizelge, 3 sayfa, başlık yalnız s.1, taşan imza", "cizelge.pdf",
         lambda p, i: taranmis_cizelge(p, sayfa=3, tasan=(3,), imzali=i)),
        ("taranmış çizelge, mavi mürekkep, unvana taşan", "cizelge_mavi.pdf",
         lambda p, i: taranmis_cizelge(p, sayfa=2, tasan=(2,), renk=MAVI, imzali=i)),
        ("metin katmanlı çizelge, gömülü imza görüntüleri, 2 sayfa, unvana taşan", "cizelge_vektor.pdf",
         lambda p, i: vektor_cizelge(p, sayfa=2, tasan=(4,), imzali=i)),
        ("taranmış tutanak, imza bloğu", "tutanak.pdf", lambda p, i: tutanak(p, imzali=i)),
        ("taranmış tutanak, ada taşan siyah imza", "tutanak_ortusen.pdf", lambda p, i: tutanak(p, ortusen=True, imzali=i)),
        ("taranmış tutanak, ada taşan mavi imza", "tutanak_mavi.pdf",
         lambda p, i: tutanak(p, ortusen=True, renk=MAVI, imzali=i)),
        ("tutanak fotoğrafı (png)", "tutanak.png", lambda p, i: tutanak(p, imzali=i)),
        ("metin katmanlı yazı, etiketli gömülü imza", "yazi_etiketli.pdf",
         lambda p, i: metin_pdf_gorselli(p, etiket=True, e_imza=False, imzali=i)),
        ("metin katmanlı yazı, etiketsiz gömülü imza", "yazi_etiketsiz.pdf",
         lambda p, i: metin_pdf_gorselli(p, etiket=False, e_imza=False, imzali=i)),
        ("YANLIŞ: her sayfada aynı yerde süs (logo)", "logo.pdf", lambda p, i: tekrar_eden_logo(p)),
        ("YANLIŞ: dairesel kaşe", "kase.pdf", lambda p, i: kaseli_sayfa(p)),
        ("YANLIŞ: not dökümü, küçük el işareti", "not_dokumu.pdf", lambda p, i: not_dokumu(p)),
        ("YANLIŞ: e-imzalı yazı, etiketsiz görüntü", "yazi_eimza.pdf",
         lambda p, i: metin_pdf_gorselli(p, etiket=False, e_imza=True, imzali=True)),
    ]


def sayfa_goruntuleri(path: Path) -> list:
    if path.suffix.lower() == ".pdf":
        import pymupdf
        doc = pymupdf.open(str(path))
        out = []
        for pg in doc:
            pix = pg.get_pixmap(dpi=PPI)
            out.append(Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB"))
        doc.close()
        return out
    return [Image.open(path).convert("RGB")]


def imza_kumeleri(maske, hucre: int = 8, bosluk: int = 2) -> list:
    """Gerçek imza maskesi → imza başına kutu: maske `hucre` piksellik ızgaraya indirilir, `bosluk`
    hücreye kadar yakın dolu hücreler aynı imzaya bağlanır."""
    W, H = maske.size
    gw, gh = (W + hucre - 1) // hucre, (H + hucre - 1) // hucre
    small = maske.resize((gw, gh), Image.BOX).tobytes()
    full = {(i % gw, i // gw) for i, v in enumerate(small) if v > 0}
    out, seen = [], set()
    for c in full:
        if c in seen:
            continue
        seen.add(c)
        stack, xs, ys = [c], [], []
        while stack:
            x, y = stack.pop()
            xs.append(x)
            ys.append(y)
            for dx in range(-bosluk, bosluk + 1):
                for dy in range(-bosluk, bosluk + 1):
                    q = (x + dx, y + dy)
                    if q in full and q not in seen:
                        seen.add(q)
                        stack.append(q)
        if len(xs) >= 3:
            out.append((min(xs) * hucre, min(ys) * hucre, min(W, (max(xs) + 1) * hucre), min(H, (max(ys) + 1) * hucre)))
    return out


def kacirilan(orijinal: Path, imzasiz: Path, maskeli: Path, esik: float = 0.15) -> tuple[int, int]:
    """→ (imza sayısı, kaçırılan): imza çekirdek piksellerinin `esik`'ten fazlası maskeli kopyada
    özgün rengiyle görünüyorsa kaçırılmış sayılır."""
    a, b, m = sayfa_goruntuleri(orijinal), sayfa_goruntuleri(imzasiz), sayfa_goruntuleri(maskeli)
    n = miss = 0
    for oa, ob, om in zip(a, b, m):
        mk = _maske(oa, ob)
        for box in imza_kumeleri(mk):
            sub = mk.crop(box)
            n += 1
            if gorunur_pay(om.crop(box), sub, oa.crop(box)) > esik:
                miss += 1
    return n, miss
