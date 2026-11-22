"""Yazı satırı yapısı (OCR güveninden bağımsız; model yok, yalnız Pillow): mürekkep bileşenlerinden "yazı benzeri
satır" bulur. Basılı ya da el yazısı metin, kelime aralıklı, taban çizgisi hizalı, boyu tutarlı parçaların yatay
dizisidir; imza/paraf tek başına, satır boyunu aşan, hizasız vuruşlardır.

Kullanım (yapi.py): (1) basılı satır bandı OCR okuyamasa da (imza vuruşu üstünden geçmiş, düşük güvenli) otomatik
kapatmadan korunur; (2) el yazısı metin kelimesi paraf/imza adayı sayılmaz; (3) kapatma ölçümü siyah altında kalan
"yazı benzeri satır" parçalarını sayar.

Koordinatlar çözümleme çözünürlüğündedir (`imza.A_PPI`, 100 ppi); girdi ikili mürekkep görüntüsüdür (255 = mürekkep).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import imza as IM

I = IM.A_PPI

HARF_MIN = 4                  # satır üyesi bileşenin en küçük boyu (8 punto x-yüksekliği ≈ 4 px)
HARF_MAX = 0.42 * I           # ve en büyük boyu (el yazısı uzun harf); üstü imza vuruşu / başlık
BASILI_MAX = 0.2 * I          # basılı satırın ortanca parça boyu üst sınırı (OCR'ın okuyamadığı gövde metni)
KELIME_BOSLUK = 2.6           # satır içi en büyük boşluk (ortanca parça boyunun katı)


@dataclass
class Satir:
    kutu: tuple               # (x0, y0, x1, y1): y, çekirdek üyelerin ortanca üst/alt sınırı (satır bandı)
    hm: float                 # ortanca parça boyu
    n: int                    # çekirdek (boyu ≥ hm/2) üye sayısı
    basili: bool              # basılı metin düzeninde (sıkı taban çizgisi, tutarlı boy)
    uyeler: list = field(default_factory=list)       # bileşen kutuları [x0, y0, x1, y1, n]

    @property
    def zarf(self) -> tuple:
        """Üyelerin tam kutusu (uzun/kuyruklu harfler dahil)."""
        return (min(u[0] for u in self.uyeler), min(u[1] for u in self.uyeler),
                max(u[2] for u in self.uyeler), max(u[3] for u in self.uyeler))


def _ortanca(v):
    v = sorted(v)
    return v[len(v) // 2] if v else 0.0


def temiz_murekkep(raw_ink):
    """Satır çözümlemesi için mürekkep: uzun düz çizgiler (tablo/form çizgisi) silinmiş kopya. Eşik uzun (1 inç):
    bitişik el yazısı kelimenin düz taban bağlantısı çizgi sayılıp silinmesin."""
    ink = raw_ink.copy()
    IM._drop_lines(ink, int(1.0 * I))
    return ink


def satirlar(ink, med: float | None = None, comps: list | None = None, dikey: list | None = None) -> list[Satir]:
    """İkili mürekkepten yazı benzeri satırlar. `med`: sayfadaki güvenilir OCR kelimelerinin ortanca boyu (varsa
    basılı satır ölçütünü sıkılaştırır). Satır: en az üç çekirdek parça, taban çizgileri hizalı, satır eni ≥ 3 boy.
    `dikey`: [(x, y0, y1)] dikey tablo çizgileri; satır hücre sınırını aşmaz (komşu hücrelerin yazısı tek satır olmaz)."""
    dikey = dikey or []
    comps = comps if comps is not None else IM._components(ink)
    cand = [c for c in comps if c[4] >= 4 and HARF_MIN <= c[3] - c[1] <= HARF_MAX and c[2] - c[0] <= 4.0 * I]
    cand.sort(key=lambda c: (c[0], c[1]))
    rows: list = []                        # [üyeler, y0, y1, x1, hr]
    for c in cand:
        hc = c[3] - c[1]
        best, bov = None, 0.0
        for r in rows:
            hr = r[4]
            if c[0] - r[3] > max(KELIME_BOSLUK * hr, 0.1 * I) or not 0.4 <= hc / hr <= 2.6:
                continue
            cy = (c[1] + c[3]) / 2.0
            if dikey and any(r[3] - 3 <= x <= c[0] + 3 and a <= cy <= b for x, a, b in dikey):
                continue
            ov = min(c[3], r[2]) - max(c[1], r[1])
            if ov >= 0.5 * min(hc, hr) and ov > bov:
                best, bov = r, ov
        if best is None:
            rows.append([[c], c[1], c[3], c[2], float(hc)])
            continue
        best[0].append(c)
        hs = sorted(u[3] - u[1] for u in best[0])
        hr = float(hs[len(hs) // 2])
        core = [u for u in best[0] if u[3] - u[1] >= 0.6 * hr]
        best[1], best[2] = _ortanca([u[1] for u in core]), _ortanca([u[3] for u in core])
        best[3], best[4] = max(best[3], c[2]), hr
    out = []
    for uy, y0, y1, x1, hr in rows:
        s = _degerlendir(uy, hr, med)
        if s is not None:
            out.append(s)
    return out


def _degerlendir(uy: list, hm: float, med) -> Satir | None:
    core = [u for u in uy if u[3] - u[1] >= 0.5 * hm]
    x0, x1 = min(u[0] for u in uy), max(u[2] for u in uy)
    if len(core) < 3 or x1 - x0 < max(3.0 * hm, 0.3 * I):
        return None
    # taban çizgisi: çekirdek alt sınırlarına doğru uydur (hafif eğik tarama), artıkların hizası
    xs = [(u[0] + u[2]) / 2.0 for u in core]
    bs = [float(u[3]) for u in core]
    egim = 0.0
    if len(core) >= 5:
        mx, mb = sum(xs) / len(xs), sum(bs) / len(bs)
        sxx = sum((x - mx) ** 2 for x in xs)
        if sxx > 0:
            egim = max(-0.05, min(0.05, sum((x - mx) * (b - mb) for x, b in zip(xs, bs)) / sxx))
    art = [b - egim * x for x, b in zip(xs, bs)]
    ob = _ortanca(art)
    sap = [abs(a - ob) for a in art]
    gevsek = sum(1 for s in sap if s <= max(2.5, 0.4 * hm)) / len(core)
    if gevsek < 0.7:
        return None
    siki = sum(1 for s in sap if s <= max(1.6, 0.22 * hm)) / len(core)
    boy = sum(1 for u in core if 0.55 * hm <= u[3] - u[1] <= 1.7 * hm) / len(core)
    basili = (len(core) >= 4 or x1 - x0 >= 7 * hm) and hm <= BASILI_MAX and siki >= 0.8 and boy >= 0.8
    if basili and med:
        basili = 0.45 * med <= hm <= 1.8 * med
    cy0 = _ortanca([u[1] for u in core])
    cy1 = _ortanca([u[3] for u in core])
    return Satir((x0, cy0, x1, cy1), hm, len(core), basili, list(uy))


def sutun_dolgu(ink, x0: float, y0: float, x1: float, y1: float) -> list:
    """Bant içinde her sütunun mürekkep dolgusu (0..1: sütundaki mürekkep pikseli / bant boyu)."""
    from PIL import Image
    a, b = int(max(0, x0)), int(min(ink.width, x1))
    c, d = int(max(0, y0)), int(min(ink.height, y1 + 0.999))
    if b - a < 1 or d - c < 1:
        return []
    return [v / 255.0 for v in ink.crop((a, c, b, d)).resize((b - a, 1), Image.BOX).tobytes()]


def _ort(v) -> float:
    return sum(v) / len(v) if v else 0.0


def genislet(ink, s: Satir, sinir: tuple | None = None) -> tuple:
    """Satır bandını iki yana, bant içi mürekkep dolgusu satırın kendi dolgusuna yakın (≥ %70) kaldıkça uzatır: imza
    vuruşunun üstünden geçip büyük bileşene kattığı harfler de (harf + vuruş: dolgu satırınkinden az değil) banda
    girer; bandı yalnız kesen ya da bant boyunca akan tek vuruş (ince: dolgusu harflerinkinin yarısı) uzatmaz.
    → (x0, y0, x1, y1)."""
    x0, y0, x1, y1 = s.kutu
    pen = max(8, int(3.0 * s.hm))
    lo = max(0, int(sinir[0]) if sinir else 0)
    hi = min(ink.width, int(sinir[2]) if sinir else ink.width)
    dol = sutun_dolgu(ink, lo, y0, hi, y1)
    if not dol:
        return s.kutu
    a, b = max(0, int(x0) - lo), min(len(dol), int(x1) - lo)
    f0 = _ort(dol[a:b])
    if f0 <= 0:
        return s.kutu
    adim = max(2, int(s.hm / 2))
    a0, b0, en_cok = a, b, int(30 * s.hm)

    def yazi(w) -> bool:
        return len(w) >= pen // 2 and _ort(w) >= 0.7 * f0 and sum(1 for v in w if v > 0) >= 0.45 * len(w)
    while b < len(dol) and b - b0 < en_cok and yazi(dol[b: b + pen]):
        b += adim
    while a > 0 and a0 - a < en_cok and yazi(dol[max(0, a - pen): a]):
        a -= adim
    ince = max(4, int(s.hm))             # uçlarda dar pencere: geniş pencere satırın bittiği boşluğu da görür
    for _ in range(pen // max(1, adim) + 1):
        w = dol[b: b + ince]
        if len(w) < ince or _ort(w) < 0.7 * f0:
            break
        b += adim
    for _ in range(pen // max(1, adim) + 1):
        w = dol[max(0, a - ince): a]
        if len(w) < ince or _ort(w) < 0.7 * f0:
            break
        a -= adim
    a, b = max(0, a), min(len(dol), b)
    while a < b and not dol[a]:
        a += 1
    while b > a and not dol[b - 1]:
        b -= 1
    return (min(x0, a + lo), y0, max(x1, b + lo), y1)


def ust_satir(ink, alt: tuple, x_son: float | None = None) -> tuple | None:
    """Okunan bir basılı satırın (`alt`: unvan satırı bandı) hemen üstünde, aynı sol hizada ve aynı satır aralığı
    düzeninde başka bir basılı satır var mı (ad satırı; imza vuruşu bütün harflerinin üstünden geçtiği için OCR da
    bileşen çözümlemesi de bulamamış olabilir). Ölçüt: bandın dolgusu alt satırın dolgusuna yakın (≥ %70), bandın
    altındaki satır arası boşluk belirgin biçimde seyrek, koşu ≥ 4 satır boyu. → bant (x0, y0, x1, y1) ya da None."""
    x0, y0, x1, y1 = alt
    lh = y1 - y0
    if lh < 5 or x1 - x0 < 1.5 * lh:
        return None
    f0 = _ort(sutun_dolgu(ink, x0, y0, x1, y1))
    if f0 <= 0.05:
        return None
    xs = max(0.0, x0 - 1.5 * lh)
    xe = min(float(ink.width), max(x1, x0 + 14 * lh) if x_son is None else x_son)
    pen = max(8, int(3.0 * lh))
    best = None
    d = int(1.15 * lh)
    while d <= int(2.4 * lh):
        by0, by1 = y0 - d, y1 - d
        dol = sutun_dolgu(ink, xs, by0, xe, by1)
        # sol hizadan başlayan koşu
        bas = next((i for i in range(min(len(dol), int(3.5 * lh))) if _ort(dol[i: i + pen]) >= 0.7 * f0), None)
        if bas is not None:
            b = bas
            while b < len(dol) and len(dol[b: b + pen]) >= pen // 2 and _ort(dol[b: b + pen]) >= 0.7 * f0:
                b += max(2, int(lh / 2))
            b = min(len(dol), b + pen // 2)
            if b - bas >= 4 * lh:
                ara = sutun_dolgu(ink, xs + bas, by1 + 1, xs + b, min(y0 - 1, by1 + max(3, 0.35 * lh)))
                ic = _ort(dol[bas:b])
                puan = ic - _ort(ara)
                if _ort(ara) <= 0.45 * ic and (best is None or puan > best[0]):
                    best = (puan, (xs + bas, by0, xs + b, by1))
        d += 1
    return best[1] if best else None


def parcalar(s: Satir, bosluk: float | None = None) -> list:
    """Satırın kelime benzeri parçaları: yakın (≤ 0,6 boy) üyeler birleşir → kutular."""
    g = 0.6 * s.hm if bosluk is None else bosluk
    out: list = []
    for u in sorted(s.uyeler, key=lambda u: u[0]):
        if out and u[0] - out[-1][2] <= g:
            o = out[-1]
            out[-1] = [o[0], min(o[1], u[1]), max(o[2], u[2]), max(o[3], u[3])]
        else:
            out.append([u[0], u[1], u[2], u[3]])
    return [tuple(o) for o in out]
