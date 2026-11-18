"""Etiket biçimlerini çözümleyen saf işlevler (dosya sistemi yok).

İnsanların kullandığı tutarsız ölçüt kodları:

- alt ölçüt: ``A.1.2``, ``B1.5`` (noktasız), ``A.1.2.`` (sonda nokta)
- ana ölçüt: ``A.1. Liderlik ve Kalite``
- alan (yalnız klasör): ``A``, ``A.Liderlik, Yönetişim…``, ``D. Toplumsal Katkı``
- kanıt kodu: ``[A.1.2-2-OD5]``, ``[A.2.3- 1-OD4]``, ``A.1.4- 2-OD3]``,
  ``[B.3.2.1-OD4]`` (= B.3.2, kanıt 1), ``[B.3.3-3OD4]``, ``[C.1.3-1- OD3]``
- ölçütsüz kanıt kodu: ``[1.OD4]``, ``1.OD4``, ``[2-OD4]``, ``2_OD5:``, ``[1_OD3]``
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

ALT = "alt_olcut"   # A.1.2
ANA = "ana_olcut"   # A.1
ALAN = "alan"       # A

DUZEY_SIRASI = {ALAN: 0, ANA: 1, ALT: 2}


@dataclass
class Kod:
    """Bir ad / klasör / rapor satırından çıkan kod."""

    olcut: str | None = None      # "A.1.2", "A.1", "A" ya da None
    duzey: str | None = None      # ALT / ANA / ALAN
    kanit_no: int | None = None
    od: str | None = None         # "OD5"
    ham: str = ""                 # eşleşen ham metin
    sorun: str | None = None      # çözülemeyen biçim notu
    kalan: str = ""               # koddan sonra kalan ad

    @property
    def bos(self) -> bool:
        return self.olcut is None and self.od is None and self.kanit_no is None


def _olcut(harf: str, *parcalar: str | None) -> tuple[str, str]:
    p = [x for x in parcalar if x is not None]
    oid = ".".join([harf.upper(), *p])
    return oid, {0: ALAN, 1: ANA, 2: ALT}[len(p)]


# --- ad / klasör adı başı -------------------------------------------------

_SEP = r"[\s\-_\.\]\)\(,;:]"

# Ölçütlü kod: harf, (nokta), rakam, nokta, rakam, (nokta rakam), (-no), (-OD)
_NAME_ALT = re.compile(
    r"""^\s*\[?\s*
    (?P<l>[A-E])\s*\.?\s*(?P<a>\d)\s*\.\s*(?P<b>\d)
    (?:\s*\.\s*(?P<c>\d)(?!\d))?
    \s*\.?\s*
    (?:[-_]\s*(?P<n>\d+)\s*)?
    (?:[-_.]?\s*OD\s*(?P<od>\d)\s*)?
    \]?\s*\.?""",
    re.X,
)
# Ana ölçüt: "A.1." / "A.1 " / "A.1" (sonda nokta ya da ayraç zorunlu, rakam gelmez)
_NAME_ANA = re.compile(r"^\s*\[?\s*(?P<l>[A-E])\s*\.\s*(?P<a>\d)(?=\.(?!\d)|\s|$)\.?")
# Alan: "A", "A.Liderlik", "D. Toplumsal" (yalnız klasörde)
_NAME_ALAN = re.compile(r"^\s*(?P<l>[A-E])(?:\s*$|\s*\.\s*(?=[^\d\s.])|\.\s*$)")
# Ölçütsüz kanıt kodu: "[1.OD4]", "1.OD4", "[2-OD4]", "[1-OD3]"
_NAME_OD = re.compile(r"^\s*\[?\s*(?P<n>\d+)\s*[-_.]\s*OD\s*(?P<od>\d)\s*\]?\s*\.?")


def _ardi_temiz(s: str, end: int) -> bool:
    """Kod bir sözcüğün parçası değil: ardından ayraç ya da son gelmeli."""
    return end >= len(s) or re.match(_SEP, s[end]) is not None or s[end - 1] in "].-_ \t"


def ad_kodu(ad: str, klasor: bool = False) -> Kod:
    """Dosya ya da klasör adının başındaki ölçüt kodunu çözer. Kod yoksa boş Kod."""
    m = _NAME_ALT.match(ad)
    if m and _ardi_temiz(ad, m.end()):
        a, b, c, n = m["a"], m["b"], m["c"], m["n"]
        k = Kod(ham=m.group(0).strip(), kalan=ad[m.end():].strip(), od=f"OD{m['od']}" if m["od"] else None)
        if c is not None and n is not None:
            # A.1.4.1-1: dört düzeyli ölçüt YÖKAK'ta yok
            k.sorun = "dort_duzeyli_kod"
            return k
        if c is not None:
            # B.3.2.1-OD4 → B.3.2, kanıt 1 (yalnız OD varsa; yoksa belirsiz)
            if k.od is None:
                k.sorun = "dort_duzeyli_kod"
                return k
            n = c
        k.olcut, k.duzey = _olcut(m["l"], a, b)
        k.kanit_no = int(n) if n is not None else None
        return k
    m = _NAME_ANA.match(ad)
    if m:
        oid, d = _olcut(m["l"], m["a"])
        return Kod(olcut=oid, duzey=d, ham=m.group(0).strip(), kalan=ad[m.end():].strip())
    if klasor:
        m = _NAME_ALAN.match(ad)
        if m:
            oid, d = _olcut(m["l"])
            return Kod(olcut=oid, duzey=d, ham=m.group(0).strip(), kalan=ad[m.end():].strip())
    m = _NAME_OD.match(ad)
    if m:
        return Kod(kanit_no=int(m["n"]), od=f"OD{m['od']}", ham=m.group(0).strip(), kalan=ad[m.end():].strip())
    return Kod(kalan=ad.strip())


# --- rapor "Kanıtlar:" satırları -------------------------------------------

_ENTRY = re.compile(
    r"""\[?\s*
    (?:(?P<l>[A-E])\s*\.?\s*(?P<a>\d)\s*\.\s*(?P<b>\d)(?:\s*\.\s*(?P<c>\d)(?!\d))?\s*\.?\s*)?
    (?:[-_]?\s*(?P<n>\d+)\s*)?
    [-_.]?\s*OD\s*(?P<od>\d)\s*\]?\s*[.:]?""",
    re.X,
)


@dataclass
class RaporKaniti:
    """Raporun bir ölçüt bölümündeki "Kanıtlar:" listesinden bir satır."""

    bolum: str                    # kanıtın gösterildiği alt ölçüt
    bolum_cikarim: bool           # başlık kodsuzdu, sıradan çıkarıldı
    od: str | None
    kanit_no: int | None
    kod_olcut: str | None         # satırdaki kodun ölçütü (başka bölüme ait olabilir)
    ad: str                       # koddan sonraki ad
    ham: str
    rapor: str = ""
    sorun: str | None = None
    eslesen: list[str] = field(default_factory=list)


def kanit_satirlari(metin: str) -> list[Kod]:
    """Bir paragraftaki kanıt kodlarını ve adlarını sırayla çıkarır."""
    bulunan = []
    for m in _ENTRY.finditer(metin):
        if m["n"] is None and m["l"] is None:
            continue
        bulunan.append(m)
    out = []
    for i, m in enumerate(bulunan):
        son = bulunan[i + 1].start() if i + 1 < len(bulunan) else len(metin)
        ad = metin[m.end():son].strip(" \t.:;-–")
        k = Kod(od=f"OD{m['od']}", ham=metin[m.start():son].strip(), kalan=ad)
        n, c = m["n"], m["c"]
        if m["l"] is not None:
            if c is not None and n is not None:
                k.sorun = "dort_duzeyli_kod"
            else:
                if c is not None:
                    n = c
                k.olcut, k.duzey = _olcut(m["l"], m["a"], m["b"])
        if k.sorun is None and n is not None:
            k.kanit_no = int(n)
        out.append(k)
    return out


# --- ad karşılaştırma ------------------------------------------------------

_TR = str.maketrans({"ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u", "â": "a", "î": "i", "û": "u"})
_EXT = re.compile(r"(\.(pdf|docx?|xlsx?|pptx?|jpe?g|png|odt|txt|html?))+\s*$", re.I)


def ad_normal(ad: str) -> str:
    """Karşılaştırma için ad: kod, uzantı, büyük/küçük harf, Türkçe harf ve noktalama atılır."""
    s = ad.strip()
    s = _EXT.sub("", s)
    k = ad_kodu(s)
    if not k.bos and k.sorun is None:
        s = k.kalan
    s = _EXT.sub("", s)
    s = s.replace("I", "ı").replace("İ", "i").lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.translate(_TR)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def ad_benzerlik(a: str, b: str) -> float:
    """Normalleştirilmiş iki ad arasında 0..1 benzerlik (dizi ve sözcük örtüşmesinin büyüğü)."""
    from difflib import SequenceMatcher

    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    seq = SequenceMatcher(None, a, b).ratio()
    ta, tb = a.split(), b.split()
    eslesen = 0
    for t in ta:
        if any(t == u or (len(t) >= 4 and len(u) >= 4 and (u.startswith(t[:5]) or t.startswith(u[:5]))) for u in tb):
            eslesen += 1
    tok = eslesen / max(len(ta), len(tb))
    return max(seq, tok)
