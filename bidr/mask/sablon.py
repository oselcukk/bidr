"""Form şablon belleği: aynı formun kopyalarında insanın kapattığı el yazısı alanlarını yeniden kullanmak.

Parmak izi yalnız BASILI iskelettir: OCR'ın güvenle okuduğu (güven ≥ 80) harf belirteçleri ve form
çizgileri (kılavuz, alt çizgi, tablo); el yazısı (düşük güvenli ya da okunamayan mürekkep) girmez.
Belirteçler dosyaya düz metin değil kısa özetle (sha1, 10 hane) yazılır: şablon dosyasında kişi adı ya
da değer bulunmaz. Eşleşme: belirteç çoklu kümesinin Jaccard benzerliği (+ çizgi düzeni benzerliği).

Hizalama: iki sayfada tek geçen ortak belirteçlerin merkezlerinden benzerlik dönüşümü (ölçek, küçük
dönme, öteleme; en küçük kareler + aykırı ayıklama). Hizalama güvenilir sayılmazsa (az çapa, yüksek
artık hata, büyük dönme/ölçek, çizgiler örtüşmüyor) bölgeler otomatik kapatılmaz: `onay_bekliyor`.

Bellek çalışma alanında `maske-sablonlari.json`; bölgeler şablonun kendi piksel düzleminde saklanır.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path

DOSYA = "maske-sablonlari.json"
SURUM = 1
ESLESME_ESIK = 0.55          # parmak izi benzerliği alt sınırı
MIN_ORTAK = 5                # ortak belirteç alt sınırı
MIN_CAPA = 4                 # hizalama için tek geçen ortak belirteç (çapa) alt sınırı
HATA_ESIK = 0.5              # artık hata (RMS) üst sınırı: sayfanın basılı yazı yüksekliğinin katı
INLIER_ORAN = 0.6
MAX_DONME = 6.0              # derece
OLCEK_ARALIK = (0.5, 2.0)
CIZGI_ESIK = 0.5             # şablon çizgilerinin hizalama sonrası örtüşme oranı alt sınırı


def _ozet(t: str) -> str:
    return hashlib.sha1(("bidr-sablon:" + t).encode("utf-8")).hexdigest()[:10]


def parmak_izi(words, W: int, H: int, yapi=None) -> dict:
    """Basılı iskelet: [özet, cx, cy, h] çapalar ve [x0, y0, x1, y1] çizgiler (piksel)."""
    from .alan import norm
    capalar = []
    for w in words:
        n = norm(w.text)
        if w.conf < 80 or len(n) < 2 or sum(c.isalpha() for c in n) < 2 or any(c.isdigit() for c in n):
            continue
        capalar.append([_ozet(n), (w.x0 + w.x1) / 2, (w.y0 + w.y1) / 2, w.y1 - w.y0])
    cizgiler = []
    if yapi is not None:
        h = yapi.h
        for s in list(yapi.yatay) + list(yapi.dikey):
            if s.length >= 3 * h:
                cizgiler.append([s.x0, s.y0, s.x1, s.y1])
    return {"W": int(W), "H": int(H), "capalar": capalar, "cizgiler": cizgiler}


def _sayac(iz) -> Counter:
    return Counter(c[0] for c in iz["capalar"])


def benzerlik(a: dict, b: dict) -> tuple[float, int]:
    ca, cb = _sayac(a), _sayac(b)
    inter = sum((ca & cb).values())
    union = sum((ca | cb).values())
    jac = inter / union if union else 0.0
    la, lb = a.get("cizgiler") or [], b.get("cizgiler") or []
    if la and lb:
        def nz(L, iz):
            return [((x0 + x1) / 2 / iz["W"], (y0 + y1) / 2 / iz["H"], (x1 - x0) / iz["W"], (y1 - y0) / iz["H"])
                    for x0, y0, x1, y1 in L]
        na, nb = nz(la, a), nz(lb, b)
        hit = sum(1 for p in na if any(abs(p[0] - q[0]) < 0.04 and abs(p[1] - q[1]) < 0.04
                                       and abs(p[2] - q[2]) < 0.06 and abs(p[3] - q[3]) < 0.06 for q in nb))
        ls = hit / max(len(na), len(nb))
        return 0.75 * jac + 0.25 * ls, inter
    return jac, inter


def _fit(P, Q):
    """Benzerlik dönüşümü P → Q (en küçük kareler; Umeyama, yansımasız). → (s, θ, tx, ty)."""
    n = len(P)
    mpx = sum(p[0] for p in P) / n
    mpy = sum(p[1] for p in P) / n
    mqx = sum(q[0] for q in Q) / n
    mqy = sum(q[1] for q in Q) / n
    sxx = sxy = vp = 0.0
    for (px, py), (qx, qy) in zip(P, Q):
        ax, ay, bx, by = px - mpx, py - mpy, qx - mqx, qy - mqy
        sxx += ax * bx + ay * by
        sxy += ax * by - ay * bx
        vp += ax * ax + ay * ay
    if vp <= 0:
        return None
    th = math.atan2(sxy, sxx)
    s = math.hypot(sxx, sxy) / vp
    c, si = s * math.cos(th), s * math.sin(th)
    tx = mqx - (c * mpx - si * mpy)
    ty = mqy - (si * mpx + c * mpy)
    return s, th, tx, ty


def _apply(T, x, y):
    s, th, tx, ty = T
    c, si = s * math.cos(th), s * math.sin(th)
    return c * x - si * y + tx, si * x + c * y + ty


def _apply_box(T, b):
    pts = [_apply(T, x, y) for x, y in ((b[0], b[1]), (b[2], b[1]), (b[0], b[3]), (b[2], b[3]))]
    return (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))


def _inverse(T):
    s, th, tx, ty = T
    si = 1.0 / s
    c, sn = si * math.cos(-th), si * math.sin(-th)
    return si, -th, -(c * tx - sn * ty), -(sn * tx + c * ty)


def hizala(sab: dict, sayfa: dict) -> dict:
    """Şablon → sayfa dönüşümü ve güvenilirlik. → {"T", "hata", "capa", "guvenilir", "neden"}."""
    ca = {}
    for c in sab["capalar"]:
        ca.setdefault(c[0], []).append(c)
    cb = {}
    for c in sayfa["capalar"]:
        cb.setdefault(c[0], []).append(c)
    P, Q, hs = [], [], []
    for k, xs in ca.items():
        ys = cb.get(k)
        if not ys or len(xs) != 1 or len(ys) != 1:
            continue                 # tekrarlı belirteç çapa sayılmaz (eşleşmesi belirsiz)
        p, q = xs[0], ys[0]
        P.append((p[1], p[2]))
        Q.append((q[1], q[2]))
        hs.append(q[3])
    res = {"T": None, "hata": float("inf"), "capa": len(P), "guvenilir": False, "neden": ""}
    if len(P) < 3:
        res["neden"] = f"az çapa ({len(P)})"
        return res
    h = sorted(hs)[len(hs) // 2] or 10.0
    idx = list(range(len(P)))
    T = None
    for _ in range(4):
        T = _fit([P[i] for i in idx], [Q[i] for i in idx])
        if T is None:
            res["neden"] = "çapalar tek noktada"
            return res
        r = [math.dist(_apply(T, *P[i]), Q[i]) for i in range(len(P))]
        med = sorted(r[i] for i in idx)[len(idx) // 2]
        lim = max(2.5 * med, 0.5 * h)
        new = [i for i in range(len(P)) if r[i] <= lim]
        if len(new) < 3 or new == idx:
            break
        idx = new
    r = [math.dist(_apply(T, *P[i]), Q[i]) for i in idx]
    rms = math.sqrt(sum(v * v for v in r) / len(r))
    s, th = T[0], math.degrees(T[1])
    res.update(T=T, hata=rms, capa=len(idx))
    nedenler = []
    if len(idx) < MIN_CAPA:
        nedenler.append(f"az çapa ({len(idx)})")
    if len(idx) < INLIER_ORAN * len(P):
        nedenler.append(f"çapaların çoğu uyuşmuyor ({len(idx)}/{len(P)})")
    if rms > HATA_ESIK * h:
        nedenler.append(f"hata {rms:.1f} px > {HATA_ESIK * h:.1f}")
    if abs(th) > MAX_DONME:
        nedenler.append(f"dönme {th:.1f}°")
    if not (OLCEK_ARALIK[0] <= s <= OLCEK_ARALIK[1]):
        nedenler.append(f"ölçek {s:.2f}")
    la, lb = sab.get("cizgiler") or [], sayfa.get("cizgiler") or []
    if len(la) >= 2:
        tol = max(0.6 * h, 6.0)
        hit = 0
        for b in la:
            t = _apply_box(T, b)
            if any(abs(t[0] - q[0]) <= tol and abs(t[2] - q[2]) <= tol and abs(t[1] - q[1]) <= tol + 0.05 * (t[2] - t[0])
                   and abs(t[3] - q[3]) <= tol + 0.05 * (t[2] - t[0]) for q in lb):
                hit += 1
        if hit < CIZGI_ESIK * len(la):
            nedenler.append(f"çizgiler örtüşmüyor ({hit}/{len(la)})")
    res["guvenilir"] = not nedenler
    res["neden"] = "; ".join(nedenler)
    return res


class SablonBellegi:
    """`maske-sablonlari.json` (çalışma alanı). `ogren` / `uygula` sayfa parmak iziyle çalışır."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path is not None else None
        self.sablonlar: list[dict] = []
        self.degisti = False
        if self.path is not None and self.path.exists():
            try:
                d = json.loads(self.path.read_text(encoding="utf-8"))
                if d.get("surum") == SURUM:
                    self.sablonlar = list(d.get("sablonlar") or [])
            except (OSError, ValueError):
                self.sablonlar = []

    @classmethod
    def calisma_alani(cls, ws) -> "SablonBellegi":
        return cls(Path(ws) / DOSYA)

    def kaydet(self) -> None:
        if self.path is None:
            self.degisti = False
            return
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"surum": SURUM, "sablonlar": self.sablonlar}, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        tmp.replace(self.path)
        self.degisti = False

    def eslestir(self, iz: dict):
        """→ (şablon, benzerlik) en iyi eşleşme ya da None."""
        best, bs = None, 0.0
        for s in self.sablonlar:
            sc, ortak = benzerlik(s, iz)
            if sc >= ESLESME_ESIK and ortak >= MIN_ORTAK and sc > bs:
                best, bs = s, sc
        return (best, bs) if best is not None else None

    def ogren(self, iz: dict, kutular, kaynak: str = "") -> str | None:
        """İnsanın kapattığı kutuları (sayfa pikseli) şablona ekle; eşleşen şablon yoksa yenisi açılır.
        Eşleşen şablona hizalama güvenilmezse yeni şablon açılır (yanlış bölge öğretilmez)."""
        kutular = [tuple(float(v) for v in b) for b in kutular]
        if not kutular or len(iz["capalar"]) < MIN_ORTAK:
            return None
        m = self.eslestir(iz)
        sab, T = None, None
        if m is not None:
            al = hizala(m[0], iz)
            if al["guvenilir"]:
                sab, T = m[0], _inverse(al["T"])
        if sab is None:
            sid = "f" + hashlib.sha1(json.dumps(sorted(c[0] for c in iz["capalar"])).encode()).hexdigest()[:8]
            n = 2
            base = sid
            while any(s["id"] == sid for s in self.sablonlar):
                sid = f"{base}-{n}"
                n += 1
            sab = {"id": sid, "W": iz["W"], "H": iz["H"], "capalar": iz["capalar"], "cizgiler": iz["cizgiler"],
                   "bolgeler": [], "kaynak": kaynak, "zaman": datetime.now().isoformat(timespec="seconds")}
            self.sablonlar.append(sab)
            T = (1.0, 0.0, 0.0, 0.0)
        for b in kutular:
            tb = _apply_box(T, b)
            if any(_iou(tb, tuple(r["kutu"])) >= 0.6 for r in sab["bolgeler"]):
                continue
            sab["bolgeler"].append({"kutu": [round(v, 1) for v in tb], "kaynak": kaynak})
            self.degisti = True
        self.degisti = True
        return sab["id"]

    def uygula(self, iz: dict) -> list[dict]:
        """Eşleşen şablonun bölgeleri sayfa düzlemine → [{"kutu", "guvenilir", "hata", "guven", "sablon",
        "neden"}]. Hizalama güvenilmezse kutu yaklaşık konumdadır (sayfa boyu oranı ya da dönüşüm)."""
        m = self.eslestir(iz)
        if m is None or not m[0]["bolgeler"]:
            return []
        sab, sc = m
        al = hizala(sab, iz)
        T = al["T"]
        if T is None:
            fx, fy = iz["W"] / max(1, sab["W"]), iz["H"] / max(1, sab["H"])
            boxes = [(r["kutu"][0] * fx, r["kutu"][1] * fy, r["kutu"][2] * fx, r["kutu"][3] * fy) for r in sab["bolgeler"]]
        else:
            boxes = [_apply_box(T, r["kutu"]) for r in sab["bolgeler"]]
        # el yazısı kopyadan kopyaya taşabilir: öğrenilen kutuya sayfa yazı yüksekliğiyle pay
        hs = sorted(c[3] for c in iz["capalar"])
        h = hs[len(hs) // 2] if hs else 0.0
        boxes = [(b[0] - 1.0 * h, b[1] - 0.3 * h, b[2] + 1.0 * h, b[3] + 0.3 * h) for b in boxes]
        g = round(min(0.9, 0.5 + 0.4 * sc), 2) if al["guvenilir"] else 0.35
        return [{"kutu": b, "guvenilir": al["guvenilir"], "hata": al["hata"] if T is not None else float("nan"),
                 "guven": g, "sablon": sab["id"], "neden": al["neden"]} for b in boxes]


def _iou(p, q) -> float:
    ix = max(0.0, min(p[2], q[2]) - max(p[0], q[0]))
    iy = max(0.0, min(p[3], q[3]) - max(p[1], q[1]))
    i = ix * iy
    u = (p[2] - p[0]) * (p[3] - p[1]) + (q[2] - q[0]) * (q[3] - q[1]) - i
    return i / u if u > 0 else 0.0
