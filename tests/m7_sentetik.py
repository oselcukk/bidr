"""m7 için sentetik belgeler (gerçek veri yok; adlar uydurma): el yazısı benzeri vuruşlar, el yazısı ad sütunlu
tutanak tablosu, basılı adın üstünden geçen imza (siyah/mavi), parçalı imza, el yazısı dilekçe, paraflı tablo,
AKTS benzeri (mavi bağlantı yazılı) taranmış web tablosu. Her üretici (imzalı, imzasız, katmanlar) verir: katmanlar
ölçüm içindir (ad/imza piksel maskeleri)."""
from __future__ import annotations

import math
import random

from PIL import ImageChops, ImageDraw

import asiri_sentetik as A
import imza_sentetik as S

EL_MAVI = (30, 50, 190)
EL_SIYAH = (45, 45, 50)


def el_yazisi_kelime(d, x: float, y: float, harf: int = 5, xh: float = 16, color=EL_SIYAH, seed: int = 1,
                     width: int = 2) -> float:
    """El yazısı benzeri bitişik kelime: taban çizgisi `y`, x-yüksekliği `xh`; bazı harfler yukarı/aşağı uzar.
    → kelimenin sağ ucu (x)."""
    rnd = random.Random(seed)
    pts = []
    cx = x
    for _ in range(harf):
        w = xh * rnd.uniform(0.55, 0.9)
        tur = rnd.random()
        ust = xh * (rnd.uniform(1.6, 2.0) if tur < 0.25 else rnd.uniform(0.85, 1.1))
        alt = xh * (rnd.uniform(0.5, 0.8) if tur > 0.85 else 0.0)
        for i in range(9):
            t = i / 8
            px = cx + w * t + 0.25 * w * math.sin(2 * math.pi * t)
            py = y - ust * math.sin(math.pi * t) ** 2 + (alt * math.sin(math.pi * t) if 0.3 < t < 0.9 else 0)
            pts.append((px, py + rnd.uniform(-0.6, 0.6)))
        cx += w
    d.line(pts, fill=color, width=width, joint="curve")
    return cx


def el_yazisi_satir(d, x: float, y: float, kelime: int, xh: float = 16, color=EL_SIYAH, seed: int = 1,
                    width: int = 2, x_son: float | None = None) -> float:
    rnd = random.Random(seed)
    cx = x
    for i in range(kelime):
        n = rnd.randint(3, 8)
        if x_son is not None and cx + n * xh * 0.8 > x_son:
            break
        cx = el_yazisi_kelime(d, cx, y + rnd.uniform(-1.5, 1.5), n, xh, color, seed * 100 + i, width)
        cx += xh * rnd.uniform(0.9, 1.5)
    return cx


def paraf_ciz(d, x: float, y: float, boy: float = 34, color=EL_MAVI, seed: int = 1, width: int = 2) -> None:
    """Paraf: kısa, çok vuruşlu iz (iki üç döngü + çizgi)."""
    rnd = random.Random(seed)
    pts = []
    for i in range(40):
        t = i / 39
        pts.append((x + boy * 1.3 * t + 0.25 * boy * math.sin(t * rnd.uniform(9, 13)),
                    y + boy / 2 + boy / 2 * math.sin(t * rnd.uniform(5, 8)) * math.cos(t * 2.5)))
    d.line(pts, fill=color, width=width, joint="curve")
    d.line([(x + 0.1 * boy, y + boy * 0.9), (x + 1.3 * boy, y + boy * rnd.uniform(0.1, 0.4))], fill=color, width=width)


def _cift(ciz):
    """`ciz(d, katman)` üç kez çağrılır (katman: "hepsi", "imzasiz", "ad") → (imzalı, imzasız, ad katmanı)."""
    out = []
    for katman in ("hepsi", "imzasiz", "ad"):
        img = S._bos()
        ciz(ImageDraw.Draw(img), katman)
        out.append(img)
    return tuple(out)


# ---------------------------------------------------------------- 1. el yazısı ad/unvan sütunlu tutanak tablosu

TCOLS = (90, 170, 520, 800, 1150)             # Sıra | Adı Soyadı | Unvanı | İmza


def el_yazisi_tutanak(*, renk=EL_MAVI, satir: int = 6, tasan: tuple = (1, 3), basili: bool = False):
    """Katılım tutanağı: başlık basılı, ad ve unvan sütunları el yazısı (ya da `basili`), imza sütununda imzalar;
    `tasan` satırlarında imza sola, unvan/ad hücresinin üstüne taşar. → (imzalı, imzasız, ad katmanı)."""
    def ciz(d, katman):
        f = S.font(28)
        if katman != "ad":
            d.text((90, 110), "BÖLÜM KURULU TOPLANTI TUTANAĞI", fill="black", font=S.font(34))
            d.text((90, 170), "Toplantıya katılan üyeler aşağıda imzalamıştır.", fill="black", font=f)
        y0, rh = 260, 100
        n = satir + 1
        if katman != "ad":
            for i in range(n + 1):
                d.line([(TCOLS[0], y0 + i * rh), (TCOLS[-1], y0 + i * rh)], fill="black", width=2)
            for x in TCOLS:
                d.line([(x, y0), (x, y0 + n * rh)], fill="black", width=2)
            for x, t in zip(TCOLS, ["Sıra", "Adı Soyadı", "Unvanı", "İmza"]):
                d.text((x + 12, y0 + 32), t, fill="black", font=f)
        for j in range(satir):
            yy = y0 + (j + 1) * rh
            if katman != "ad":
                d.text((TCOLS[0] + 14, yy + 32), str(j + 1), fill="black", font=f)
            if basili:
                d.text((TCOLS[1] + 12, yy + 32), S._ADLAR[j], fill="black", font=f)
                d.text((TCOLS[2] + 12, yy + 32), S._UNVAN[j % 5], fill="black", font=f)
            else:
                cx = el_yazisi_kelime(d, TCOLS[1] + 16, yy + 66, 5, 17, EL_SIYAH if renk != EL_SIYAH else EL_MAVI, 300 + j)
                el_yazisi_kelime(d, cx + 22, yy + 66, 6, 17, EL_SIYAH if renk != EL_SIYAH else EL_MAVI, 330 + j)
                el_yazisi_kelime(d, TCOLS[2] + 16, yy + 66, 4, 16, EL_SIYAH if renk != EL_SIYAH else EL_MAVI, 360 + j)
            if katman == "hepsi":
                if j in tasan:
                    S.imza_ciz(d, TCOLS[2] + 130, yy + 14, w=380, h=70, color=renk, seed=40 + j)
                else:
                    S.imza_ciz(d, TCOLS[3] + 40, yy + 16, w=240, h=64, color=renk, seed=40 + j)
    return _cift(ciz)


# ---------------------------------------------------------------- 2. imza bloğu: imza basılı adın üstünden geçer

def ortusen_blok(*, renk=S.SIYAH_MUREKKEP, tam: bool = False):
    """Tutanak sonu imza bloğu: basılı "Prof. Dr. Ad Soyad" + altında unvan; imza adın üstünden geçer (`tam`: adın
    bütün harflerinin üstünden, OCR adı okuyamaz). → (imzalı, imzasız, ad katmanı)."""
    def ciz(d, katman):
        f = S.font(30)
        if katman != "ad":
            d.text((120, 120), "TOPLANTI TUTANAĞI", fill="black", font=S.font(38))
            y = 230
            for t in S._GOVDE * 2:
                d.text((120, y), t, fill="black", font=f)
                y += 55
        for x, ad, unvan, seed in ((150, "Prof. Dr. Ayşe Demir", "Bölüm Başkanı", 21), (700, "Doç. Dr. Can Öztürk", "Üye", 22)):
            d.text((x, 1320), ad, fill="black", font=f)
            d.text((x, 1365), unvan, fill="black", font=f)
            if katman == "hepsi":
                if tam:
                    S.imza_ciz(d, x - 10, 1262, w=330, h=92, color=renk, seed=seed)
                else:
                    S.imza_ciz(d, x + 10, 1280, w=300, h=80, color=renk, seed=seed)
    return _cift(ciz)


# ---------------------------------------------------------------- 3. parçalı imza (harf boyu parçalar + büyük vuruş)

def parcali_imza_blok(*, renk=S.SIYAH_MUREKKEP):
    """İmza bloğu: imza bir büyük vuruş + ondan ayrı, harf boyunda kısa vuruşlardan oluşur (zarfın harf boyu süzgeci
    küçük parçaları atardı). → (imzalı, imzasız, ad katmanı)."""
    def ciz(d, katman):
        f = S.font(30)
        if katman != "ad":
            d.text((120, 120), "KARAR TUTANAĞI", fill="black", font=S.font(38))
            y = 230
            for t in S._GOVDE:
                d.text((120, y), t, fill="black", font=f)
                y += 55
        for x, ad, unvan, seed in ((150, "Prof. Dr. Ayşe Demir", "Bölüm Başkanı", 31), (700, "Doç. Dr. Can Öztürk", "Üye", 32)):
            d.text((x, 900), ad, fill="black", font=f)
            d.text((x, 945), unvan, fill="black", font=f)
            if katman == "hepsi":
                rnd = random.Random(seed)
                S.imza_ciz(d, x + 10, 790, w=130, h=60, color=renk, seed=seed)
                cx = x + 185                              # büyük vuruştan ayrı kısa vuruşlar (harf boyu)
                for i in range(4):                        # düzensiz kısa kancalar/yaylar (harf değil)
                    w, yy = rnd.uniform(16, 30), 846 + rnd.uniform(-22, 6)
                    if i % 2:
                        d.arc([cx, yy - 24, cx + w, yy], rnd.uniform(20, 80), rnd.uniform(200, 320), fill=renk, width=3)
                    else:
                        d.line([(cx, yy), (cx + w * 0.5, yy - rnd.uniform(14, 26)), (cx + w, yy - 4)], fill=renk, width=3)
                    cx += w + rnd.uniform(24, 34)
    return _cift(ciz)


# ---------------------------------------------------------------- 4. el yazısı dilekçe

def dilekce(*, renk=EL_MAVI, satir: int = 9):
    """El yazısı dilekçe: basılı başlık, el yazısı gövde (kelime aralıklı satırlar), sağ altta el yazısı ad ve imza.
    → (imzalı, imzasız, ad katmanı)."""
    def ciz(d, katman):
        if katman != "ad":
            d.text((330, 130), "MATEMATİK BÖLÜM BAŞKANLIĞINA", fill="black", font=S.font(34))
        y = 300
        for i in range(satir):
            el_yazisi_satir(d, 200 if i == 0 else 130, y, 9, 17, renk, seed=500 + i, x_son=1100)
            y += 62
        el_yazisi_satir(d, 130, y, 3, 17, renk, seed=590, x_son=1100)
        el_yazisi_satir(d, 790, y + 190, 2, 17, renk, seed=595, x_son=1150)       # ad soyad
        if katman == "hepsi":
            S.imza_ciz(d, 800, y + 220, w=260, h=80, color=renk, seed=77)
    return _cift(ciz)


# ---------------------------------------------------------------- 5. paraflı tablo

def parafli_tablo(*, satir: int = 12):
    """Ders dağılım tablosu (İmza sütunu yok): her satırın sonunda paraf. → (imzalı, imzasız, ad katmanı)."""
    cols = (90, 300, 760, 960, 1150)

    def ciz(d, katman):
        f = S.font(24)
        if katman != "ad":
            d.text((90, 110), "DERS GÖREVLENDİRME ÇİZELGESİ", fill="black", font=S.font(34))
        y0, rh = 220, 80
        if katman != "ad":
            for i in range(satir + 2):
                d.line([(cols[0], y0 + i * rh), (cols[-1], y0 + i * rh)], fill="black", width=2)
            for x in cols:
                d.line([(x, y0), (x, y0 + (satir + 1) * rh)], fill="black", width=2)
            for x, t in zip(cols, ["Ders Kodu", "Ders Adı", "Kredi", "Onay"]):
                d.text((x + 12, y0 + 26), t, fill="black", font=f)
        for j in range(satir):
            yy = y0 + (j + 1) * rh
            d.text((cols[0] + 12, yy + 26), f"MAT{101 + j}", fill="black", font=f)
            d.text((cols[1] + 12, yy + 26), A.AKTS_DERSLER[j % 6] + " ve Uygulamaları", fill="black", font=f)
            d.text((cols[2] + 12, yy + 26), str(3 + j % 3), fill="black", font=f)
            if katman == "hepsi":
                paraf_ciz(d, cols[3] + 50, yy + 18, boy=40, seed=600 + j)
    return _cift(ciz)


# ---------------------------------------------------------------- 6. AKTS benzeri web tablosu (taranmış / görüntü)

def akts_goruntu(*, satir: int = 14):
    """Web sayfası çıktısının görüntüsü: üst bilgi, ders tablosu, ders adları mavi bağlantı yazısı (imza yok)."""
    img = S._bos()
    d = ImageDraw.Draw(img)
    f = S.font(24)
    d.text((60, 40), "23.11.2026 10:42   AKTS Bilgi Paketi", fill="black", font=S.font(18))
    d.text((60, 1700), "https://akts.ornek.edu.tr/ders/plan?id=42   1/1", fill="black", font=S.font(18))
    d.text((90, 140), "Matematik Lisans Programı Ders Planı", fill="black", font=S.font(34))
    y = 240
    for x, t in zip((90, 300, 900), ("Ders Kodu", "Ders Adı", "AKTS")):
        d.text((x, y), t, fill="black", font=f)
    for j in range(satir):
        y += 60
        d.line([(90, y - 14), (1100, y - 14)], fill=(200, 200, 200), width=1)
        d.text((90, y), f"MAT{101 + j}", fill="black", font=f)
        d.text((300, y), A.AKTS_DERSLER[j % 6] + (" II" if j >= 6 else ""), fill=(20, 60, 220), font=f)
        d.text((900, y), str(5 + j % 3), fill="black", font=f)
    return img


def maske(a, b):
    """İki katmanın farkı → ikili maske (255 = yalnız `a`da olan mürekkep)."""
    return ImageChops.difference(a.convert("L"), b.convert("L")).point(lambda v: 255 if v >= 60 else 0)


def ad_maskesi(ad_katmani):
    return ad_katmani.convert("L").point(lambda v: 255 if v < 140 else 0)


def siyah_alti_payi(m, maskeli) -> float:
    """`m` maskesindeki piksellerden maskeli görüntüde siyah blok içinde kalanların payı."""
    g = maskeli.convert("L").resize(m.size)
    md, gd, W = m.tobytes(), g.tobytes(), m.width
    tot = kap = 0
    for i, v in enumerate(md):
        if not v:
            continue
        tot += 1
        if all(0 <= j < len(gd) and gd[j] < 20 for j in (i - 2, i + 2, i - 2 * W, i + 2 * W)):
            kap += 1
    return kap / max(1, tot)


def acik_imzalar(imza_m, maskeli, esik: float = 0.5) -> list:
    """Maskeli görüntüde mürekkebinin `esik`'ten fazlası açık kalan imzaların kutuları (maske pikseli)."""
    g = maskeli.convert("L").resize(imza_m.size)
    out = []
    for box in S.imza_kumeleri(imza_m, bosluk=3):
        sub, cg = imza_m.crop(box).tobytes(), g.crop(box).tobytes()
        n = sum(1 for v in sub if v)
        acik = sum(1 for v, q in zip(sub, cg) if v and q >= 20)
        if n and acik / n > esik:
            out.append(box)
    return out


def olc(tmp, ad: str, uclu, *, gri: bool = False, rules=None) -> dict:
    """Üçlüyü (imzalı, imzasız, ad katmanı) taranmış PDF olarak maskeler → ölçüm: `ad_siyah` (ad/metin mürekkebinin
    siyah altında kalan payı), `metin_siyah` (imzasız sayfanın bütün yazısı için), `acik` (yarıdan fazlası açık
    imza sayısı), `sessiz` (açık kalan ve hiçbir öneri kutusuna da girmeyen imza: sessiz kaçak), `oneri` (onay
    bekleyen bölge sayısı), `rec`."""
    from pathlib import Path

    from bidr.mask import run as R
    from bidr.mask.detect import MaskRules
    imzali, imzasiz, adk = uclu
    if gri:
        imzali_s, imzasiz_s = A.gri_tarama(imzali), A.gri_tarama(imzasiz)
    else:
        imzali_s, imzasiz_s = imzali, imzasiz
    tmp = Path(tmp)
    src, bos, dst = tmp / f"{ad}.pdf", tmp / f"{ad}_bos.pdf", tmp / f"{ad}_o.pdf"
    S.pdf_goruntu_sayfalari(src, [imzali_s])
    S.pdf_goruntu_sayfalari(bos, [imzasiz_s])
    rec = R.mask_and_check(src, dst, rules or MaskRules(), "pymupdf")
    mk = S.sayfa_goruntuleri(dst)[0]
    imza_m = maske(imzali, imzasiz)
    acik = acik_imzalar(imza_m, mk)
    f = S.PPI / 72.0
    oneri = [b for b in rec.get("bolgeler") or [] if b["karar"] == "onay_bekliyor"]
    kutular = [[v * f for v in b["kutu"]] for b in oneri]

    def onerili(box) -> bool:
        return any(min(box[2], k[2]) > max(box[0], k[0]) and min(box[3], k[3]) > max(box[1], k[1]) for k in kutular)
    return {"ad_siyah": siyah_alti_payi(ad_maskesi(adk), mk), "metin_siyah": A.basili_siyah_payi(bos, dst),
            "imza": len(S.imza_kumeleri(imza_m, bosluk=3)), "acik": len(acik),
            "sessiz": sum(1 for b in acik if not onerili(b)), "oneri": len(oneri), "rec": rec, "dst": dst}
