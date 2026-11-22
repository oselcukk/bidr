"""Aşırı kapatma (m6) için sentetik belgeler ve "basılı metnin siyah altında kalan oranı" ölçüsü (gerçek veri yok;
adlar uydurma). Her üretici imzalı ve imzasız (aynı sayfa) kopyayı yazabilir: kaçırma `imza_sentetik.kacirilan` ile,
aşırı kapatma `basili_siyah_payi` ile ölçülür."""
from __future__ import annotations

import io
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

import imza_sentetik as S

KARAR = ["Fakülte Yönetim Kurulu gündemdeki maddeleri görüşmüştür.",
         "Ders görevlendirmeleri bölüm önerisi doğrultusunda kabul edilmiştir.",
         "Sınav programının ilan edilmesine oy birliği ile karar verilmiştir.",
         "Laboratuvar kullanım esaslarının yeniden düzenlenmesi uygun görülmüştür.",
         "Bir sonraki toplantının ay sonunda yapılmasına karar verilmiştir."]
UYELER = [("Prof. Dr. Ayşe Demir", "Dekan"), ("Prof. Dr. Mehmet Kaya", "Üye"), ("Doç. Dr. Zeynep Çelik", "Üye"),
          ("Doç. Dr. Ali Şahin", "Üye"), ("Dr. Öğr. Üyesi Elif Yıldız", "Raportör")]
COLS = (100, 560, 860, 1140)                 # Adı Soyadı | Unvanı | İmza


def kurul_karari_goruntu(*, imzali: bool = True, tasan: int | None = 2, renk=S.SIYAH_MUREKKEP):
    """Taranmış kurul kararı: başlık, karar paragrafı, altında üye tablosu (Adı Soyadı | Unvanı | İmza)."""
    img = S._bos()
    d = ImageDraw.Draw(img)
    f = S.font(28)
    d.text((100, 110), "FAKÜLTE YÖNETİM KURULU KARARI", fill="black", font=S.font(36))
    y = 200
    for t in KARAR:
        d.text((100, y), t, fill="black", font=f)
        y += 48
    y0, rh = 520, 95
    n = len(UYELER) + 1
    for i in range(n + 1):
        d.line([(COLS[0], y0 + i * rh), (COLS[-1], y0 + i * rh)], fill="black", width=2)
    for x in COLS:
        d.line([(x, y0), (x, y0 + n * rh)], fill="black", width=2)
    for x, t in zip(COLS, ["Adı Soyadı", "Unvanı", "İmza"]):
        d.text((x + 14, y0 + 30), t, fill="black", font=f)
    for j, (ad, unvan) in enumerate(UYELER):
        yy = y0 + (j + 1) * rh
        d.text((COLS[0] + 14, yy + 30), ad, fill="black", font=f)
        d.text((COLS[1] + 14, yy + 30), unvan, fill="black", font=f)
        if imzali:
            if tasan is not None and j == tasan:
                S.imza_ciz(d, COLS[1] + 150, yy + 14, w=300, h=66, color=renk, seed=70 + j)
            else:
                S.imza_ciz(d, COLS[2] + 30, yy + 16, w=215, h=60, color=renk, seed=70 + j)
    return img


def gri_tarama(img, *, seed: int = 3, aci: float = 0.6, kalite: int = 60):
    """Gri tonlu taranmış görünüm: gri kâğıt, gürültü, hafif eğim, JPEG."""
    rnd = random.Random(seed)
    g = img.convert("L").point(lambda v: int(60 + v * 0.62))           # kâğıt ≈ 218, mürekkep koyu gri
    g = g.rotate(aci, resample=Image.BICUBIC, expand=False, fillcolor=218)
    px = bytearray(g.tobytes())
    for i in range(len(px)):
        px[i] = max(0, min(255, px[i] + int(rnd.gauss(0, 6))))
    g = Image.frombytes("L", g.size, bytes(px)).filter(ImageFilter.GaussianBlur(0.5))
    b = io.BytesIO()
    g.save(b, format="JPEG", quality=kalite)
    return Image.open(io.BytesIO(b.getvalue())).convert("RGB")


def kurul_karari(path: Path, *, imzali: bool = True, gri: bool = False, don: int = 0) -> None:
    img = kurul_karari_goruntu(imzali=imzali)
    if gri:
        img = gri_tarama(img)
    if don:
        img = img.rotate(don, expand=True)
    S.pdf_goruntu_sayfalari(path, [img])


def gri_tutanak(path: Path, *, imzali: bool = True) -> None:
    S.pdf_goruntu_sayfalari(path, [gri_tarama(S.tutanak_goruntu(ortusen=True, imzali=imzali))])


def afis(path: Path) -> None:
    """Renkli afiş (fotoğraf benzeri zemin, büyük başlıklar; imza yok)."""
    rnd = random.Random(11)
    img = Image.new("RGB", (1200, 1700), (30, 60, 120))
    d = ImageDraw.Draw(img)
    for _ in range(400):
        x, y, r = rnd.randint(0, 1200), rnd.randint(0, 1700), rnd.randint(10, 80)
        d.ellipse([x - r, y - r, x + r, y + r], fill=(rnd.randint(0, 255), rnd.randint(0, 255), rnd.randint(0, 255)))
    d.rectangle([80, 120, 1120, 420], fill=(250, 250, 245))
    d.text((120, 160), "MATEMATİK SEMİNERİ", fill=(200, 20, 20), font=S.font(70))
    d.text((120, 280), "Konuşmacı: Dr. Deneme Kişi", fill=(20, 20, 20), font=S.font(44))
    d.rectangle([80, 1300, 1120, 1550], fill=(250, 250, 245))
    d.text((120, 1340), "Salı 14:00  Seminer Salonu", fill=(20, 20, 20), font=S.font(44))
    d.text((120, 1430), "Tüm öğrenciler davetlidir", fill=(20, 20, 20), font=S.font(44))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def _banner_png() -> bytes:
    """Az renkli, seyrek çizgili geniş banner (imza gibi görünebilir: tek ton, seyrek)."""
    img = Image.new("RGB", (1200, 260), "white")
    d = ImageDraw.Draw(img)
    for i in range(0, 1200, 40):
        d.line([(i, 0), (i + 200, 260)], fill=(70, 70, 70), width=3)
    b = io.BytesIO()
    img.save(b, format="PNG")
    return b.getvalue()


AKTS_DERSLER = ["Analiz I", "Lineer Cebir", "Diferansiyel Denklemler", "Olasılık", "Sayısal Analiz", "Topoloji"]


def web_sayfasi(path: Path, *, imzali: bool = True) -> dict:
    """Web çıktısı (AKTS bilgi paketi): üst/alt bilgide URL ve tarih, içerik alanını kaplayan banner görüntüsü, ders
    tablosu (ders adları mavi bağlantı yazısı), sonda "İmza" etiketi ve yanında imza görüntüsü."""
    import pymupdf
    doc = pymupdf.open()
    p = doc.new_page(width=595, height=842)
    S.metin_yaz(p, (30, 20), "23.11.2026 10:42   AKTS Bilgi Paketi", 8)
    S.metin_yaz(p, (30, 830), "https://akts.ornek.edu.tr/ders/plan?id=42   1/1", 8)
    banner = pymupdf.Rect(40, 140, 555, 250)
    p.insert_image(banner, stream=_banner_png(), keep_proportion=False)
    S.metin_yaz(p, (50, 280), "Ders Kodu", 10)
    S.metin_yaz(p, (150, 280), "Ders Adı", 10)
    S.metin_yaz(p, (420, 280), "AKTS", 10)
    for i, ad in enumerate(AKTS_DERSLER):
        y = 305 + 22 * i
        S.metin_yaz(p, (50, y), f"MAT{101 + i}", 10)
        p.insert_text((150, y), ad, fontsize=10, fontname="tr", fontfile=S._ttf(), color=(0.1, 0.2, 0.9)) \
            if S._ttf() else p.insert_text((150, y), ad, fontsize=10, color=(0.1, 0.2, 0.9))
        S.metin_yaz(p, (420, y), str(5 + i % 3), 10)
    S.metin_yaz(p, (60, 640), "Bölüm Başkanı", 10)
    S.metin_yaz(p, (60, 690), "İmza:", 10)
    imza = pymupdf.Rect(100, 668, 240, 708)
    if imzali:
        p.insert_image(imza, stream=S._imza_png(w=280, h=80, seed=9))
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    doc.close()
    return {"banner": tuple(banner), "imza": tuple(imza)}


def _cizgi_pikselleri(g, uzun: int = 60) -> set:
    """Koyu piksellerden yatay/dikey ≥ `uzun` koşuya ait olanlar (tablo/çerçeve çizgisi; basılı metin değil)."""
    import re
    out = set()
    pat = re.compile(rb"[\x00-\x63]{%d,}" % uzun)
    for im, dik in ((g, False), (g.transpose(Image.Transpose.TRANSPOSE), True)):
        W = im.width
        b = im.tobytes()
        for y in range(im.height):
            for m in pat.finditer(b, y * W, (y + 1) * W):
                for x in range(m.start() - y * W, m.end() - y * W):
                    out.add(x * g.width + y if dik else y * W + x)
    return out


def basili_siyah_payi(imzasiz: Path, maskeli: Path) -> float:
    """Basılı metnin siyah altında kalan oranı: imzasız kopyanın koyu (basılı metin; tablo çizgisi hariç)
    piksellerinden maskeli kopyada siyah blok içinde kalanların payı (siyah blok: pikselin 2 px çevresi de tam siyah;
    basılı harf kenarı beyaza değer)."""
    tot = kapali = 0
    for a, m in zip(S.sayfa_goruntuleri(imzasiz), S.sayfa_goruntuleri(maskeli)):
        a, m = a.convert("L"), m.convert("L").resize(a.size)
        cizgi = _cizgi_pikselleri(a)
        ad, md = a.tobytes(), m.tobytes()
        W = a.width
        for i, v in enumerate(ad):
            if v >= 100 or i in cizgi:
                continue
            tot += 1
            if all(0 <= j < len(md) and md[j] < 20 for j in (i - 2, i + 2, i - 2 * W, i + 2 * W)):
                kapali += 1
    return kapali / max(1, tot)
