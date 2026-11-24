"""İsteğin dosyada karşılığı: eksik listesi (`bidr ihtiyac`) kabul edilmiş inceleme kararlarına bakar.

Kabul edilmiş kanıt = yuvayı karşılayan audit satırı (`rapor.karsilar`: sayılan, reddedilmemiş; güveni
orta/yüksek ya da incelemede kabul/düzelt). Bir istek şu sırayla kapanır (ilk tutan kural):

  1. **Aynı belge:** geçen yılın belgesinin bu yılki karşılığı (eşleştirmenin bulduğu belge) herhangi
     bir ölçütte kabul edilmiş.
  2. **Tür düzeyi:** derse özgü geçen yıl belgesi ("MATH407 anket sonucu") bu yıl tür düzeyinde istenir;
     aynı türden kabul edilmiş herhangi bir belge (herhangi bir dersin, herhangi bir ölçütte) kapatır.
  3. **Aynı ölçüt, aynı yuva ya da tür:** ölçütte geçen yılın belgesinin yuvası kabul edilmiş bir belgeyle
     tam dolu (zayıf değil) ya da aynı türden kabul edilmiş belge var ("başka belgeyle" karşılandı).
  4. **Kurum belgesi başka ölçütte:** kurum düzeyi belge (yönetmelik, yönerge, iş akışı, form; ya da kurum/
     fakülte geneli satır) adıyla dosyada başka ölçütün kanıtı: istenmez, "dosyada var (X ölçütünde)".

Yuva doluluğu: yuvayı karşılayan satırların hepsi zayıfsa (alıntı tek soru ya da en çok `ZAYIF_SOZCUK`
sözcük) yuva **kısmen** doludur; kılavuz isteği somut biçimde kalır, "Var olan kanıt" sütununda zayıf
kanıt gösterilir. Model yok; salt okunur.
"""
from __future__ import annotations

import re

from .tablolar import norm

ZAYIF_SOZCUK = 6
KURUM_TURLER = frozenset({"yonetmelik", "yonerge", "usul_esas", "is_akisi", "senato_karari", "anket_formu",
                          "form_belgesi", "mevzuat"})
GENEL_ILISKI = frozenset({"kurum_geneli", "fakulte_geneli"})
DERS_GRUP = {"ders_bilgi_formu": "ders_bilgi", "mufredat": "ders_bilgi", "akts_bilgi_paketi": "ders_bilgi"}
_DOLGU = frozenset("gtu gebze teknik universitesi universite ve ile icin iliskin hakkinda bir the of and "
                   "bolum bolumu bolumun".split())


def karsilar(r: dict) -> bool:
    from .rapor import karsilar as k
    return k(r)


def zayif(r: dict) -> bool:
    """Tek başına yuvayı dolduramayacak kanıt: alıntı tek soru ya da çok kısa."""
    q = " ".join(str(r.get("alinti") or "").split())
    return q.endswith("?") or len(q.split()) <= ZAYIF_SOZCUK


def kok(s: str) -> set[str]:
    return {w[:5] for w in re.findall(r"[a-z]+", norm(s)) if len(w) > 2 and w not in _DOLGU}


def ad_ayni(a: str, b: str) -> bool:
    """İki belge adı aynı belgeyi mi anlatıyor (yıl/sayı dışı sözcük kökleri; kısa adın ≥ %80'i, Jaccard ≥ 0,5)."""
    x, y = kok(a), kok(b)
    if len(x) < 2 or len(y) < 2:
        return False
    o = len(x & y)
    return o / min(len(x), len(y)) >= 0.8 and o / len(x | y) >= 0.5


def tur_ayni(a: str | None, b: str | None) -> bool:
    if not a or not b or a == "bilinmiyor" or b == "bilinmiyor":
        return False
    return a == b or DERS_GRUP.get(a, a) == DERS_GRUP.get(b, b)


def ad(r: dict) -> str:
    return r.get("kanit_adi") or r.get("belge") or r.get("doc_id") or ""


def kurum_mu(r: dict) -> bool:
    return (r.get("belge_turu") in KURUM_TURLER or r.get("birim_iliskisi") in GENEL_ILISKI
            or "kurum_geneli" in (r.get("flags") or []))


class Karsilama:
    def __init__(self, rows: list[dict]):
        self.rows = [r for r in rows if karsilar(r)]

    # -- yuva doluluğu ------------------------------------------------------------------------
    def yuva(self, cid: str) -> dict[str, dict]:
        """{yuva: {"durum": "dolu"|"kismen", "belgeler": [ad]}} (ölçütün kabul edilmiş satırlarından)."""
        out: dict[str, dict] = {}
        for r in self.rows:
            if r.get("olcut") != cid:
                continue
            e = out.setdefault(r["yuva"], {"durum": "kismen", "belgeler": [], "zayif": []})
            if not zayif(r):
                e["durum"] = "dolu"
                e["belgeler"].append(ad(r))
            else:
                e["zayif"].append(ad(r))
        for e in out.values():
            e["belgeler"] = list(dict.fromkeys(e["belgeler"] if e["durum"] == "dolu" else e["zayif"]))
            del e["zayif"]
        return out

    def dolu(self, cid: str) -> set[str]:
        return {y for y, e in self.yuva(cid).items() if e["durum"] == "dolu"}

    def kismen(self, cid: str) -> dict[str, list[str]]:
        return {y: e["belgeler"] for y, e in self.yuva(cid).items() if e["durum"] == "kismen"}

    # -- geçen yılın belgesi -------------------------------------------------------------------
    def _not(self, r: dict, cid: str, neden: str) -> dict:
        return {"ad": ad(r), "olcut": r["olcut"], "doc_id": r.get("doc_id"), "neden": neden,
                "metin": f"«{ad(r)}»" + ("" if r["olcut"] == cid else f" ({r['olcut']} ölçütünde)")}

    def _sec(self, xs: list[dict], cid: str) -> dict | None:
        """Önce aynı ölçütün satırı, sonra en küçük ölçüt kimliği (kararlı)."""
        if not xs:
            return None
        return sorted(xs, key=lambda r: (r["olcut"] != cid, r["olcut"], ad(r)))[0]

    def gecen(self, g: dict, tur_duzeyi: bool) -> dict | None:
        """Geçen yılın belgesinin (referans öğe + eşleştirme sonucu) dosyadaki karşılığı; yoksa None."""
        cid = g["olcut"]
        bt = g.get("belge_turu") or ""
        kd = g.get("karsilik_doc_id")
        if kd:
            r = self._sec([r for r in self.rows if r.get("doc_id") == kd], cid)
            if r:
                return self._not(r, cid, "aynı belge kabul edilmiş")
        if tur_duzeyi:
            r = self._sec([r for r in self.rows if tur_ayni(bt, r.get("belge_turu"))], cid)
            if r:
                return self._not(r, cid, "aynı türden belge kabul edilmiş (tür düzeyinde istek)")
        dolu = self.dolu(cid)
        r = self._sec([r for r in self.rows if r["olcut"] == cid and (
            (g.get("yuva") and r["yuva"] == g["yuva"] and r["yuva"] in dolu) or tur_ayni(bt, r.get("belge_turu"))
            or ad_ayni(g.get("kanit_adi") or "", ad(r)))], cid)
        if r:
            return self._not(r, cid, "ölçütte aynı yuva/tür başka belgeyle karşılanmış")
        if bt in KURUM_TURLER or g.get("kurum"):
            r = self._sec([r for r in self.rows if kurum_mu(r) and ad_ayni(g.get("kanit_adi") or "", ad(r))], cid)
            if r:
                return self._not(r, cid, "kurum belgesi dosyada başka ölçütün kanıtı")
        return None

    def kurum(self, o: dict, cid: str) -> dict | None:
        """Kurum kataloğundaki belgenin (ad, kod) dosyada kabul edilmiş karşılığı (herhangi bir ölçütte)."""
        kod = norm(o.get("kod") or "")
        xs = [r for r in self.rows if (kod and kod in norm(ad(r))) or ad_ayni(o.get("ad") or "", ad(r))]
        r = self._sec(xs, cid)
        return self._not(r, cid, "kurum belgesi dosyada") if r else None
