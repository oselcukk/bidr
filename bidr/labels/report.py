"""BİDR raporlarının (docx) "Kanıtlar:" bölümlerini okur.

Her kanıt satırı, gösterildiği alt ölçüt bölümüyle birlikte döner. Şablonun
"Örnek Kanıt Gösterimi" kısmı (ilk ana ölçüt başlığından önce) ve rubrik
tablolarındaki "Örnek Kanıtlar" listeleri atlanır.
"""
from __future__ import annotations

import re
from pathlib import Path

from .parse import ALT, ANA, RaporKaniti, kanit_satirlari

_HEAD = re.compile(r"^\s*([A-E])\.\s?(\d)\.(?:\s?(\d)\.)?\s*(?=[^\d\s.])")
_KANIT_BASI = re.compile(r"^\s*Kanıtlar\s*:", re.I)
_ORNEK = re.compile(r"^\s*Örnek\s+Kanıtlar", re.I)
# şablonda ölçüt bölümlerinin başladığı yer; ilk başlıklar otomatik numaralı olabilir
_ON_EK = re.compile(r"^\s*(Kanıtlar\s*:\s*|Kanıtlar buraya yazılmalı.*?olmalıdır\.\s*)+", re.I)
_BOLUM_BASI = re.compile(r"^\s*ÖLÇÜTLER\s+VE\s+KANITLAR\s*$")


def _paragraflar(path: Path) -> list[str]:
    import docx
    from docx.oxml.ns import qn

    d = docx.Document(str(path))
    W_P, W_T = qn("w:p"), qn("w:t")
    FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"
    out = []
    for p in d.element.body.iter(W_P):
        anc = p.getparent()
        atla = False
        while anc is not None:
            if anc.tag == FALLBACK:
                atla = True
                break
            anc = anc.getparent()
        if atla:
            continue
        parca = []
        for t in p.iter(W_T):
            # yalnız bu paragrafın kendi metni (iç içe metin kutusu paragrafları ayrıca gelir)
            q = t.getparent()
            while q is not None and q.tag != W_P:
                q = q.getparent()
            if q is p:
                parca.append(t.text or "")
        metin = "".join(parca).replace("\xa0", " ")
        if metin.strip():
            out.append(metin.strip())
    return out


def baslik(metin: str) -> tuple[str, str] | None:
    """Paragraf bir ölçüt başlığıysa (olcut, duzey)."""
    if len(metin) > 160:
        return None
    m = _HEAD.match(metin)
    if not m:
        return None
    if m.group(3):
        return f"{m.group(1)}.{m.group(2)}.{m.group(3)}", ALT
    return f"{m.group(1)}.{m.group(2)}", ANA


def rapor_kanitlari(path: Path, ad: str = "") -> list[RaporKaniti]:
    """Rapordaki tüm kanıt satırları (aynı bölümde tekrarlananlar bir kez)."""
    return paragraf_kanitlari(_paragraflar(path), ad or path.name)


def paragraf_kanitlari(paragraflar: list[str], ad: str = "") -> list[RaporKaniti]:
    out: list[RaporKaniti] = []
    gorulen: set[tuple] = set()
    basladi = False
    ana: str | None = None
    alt: str | None = None
    blokta = False
    for metin in paragraflar:
        b = baslik(metin)
        if b:
            oid, d = b
            if d == ANA:
                basladi = True
                ana, alt = oid, None
            elif basladi:
                alt = oid
                ana = oid.rsplit(".", 1)[0]
            blokta = False
            continue
        if not basladi:
            if _BOLUM_BASI.match(metin):
                basladi = True
                ana, alt = "A.1", None
            continue
        if _ORNEK.match(metin):
            blokta = False
            continue
        # liste satırı kodla başlamalı; düzyazı içindeki [..-OD3] atıfları kanıt listesi değildir
        govde = _ON_EK.sub("", metin).lstrip()
        satirlar = kanit_satirlari(govde)
        if satirlar and not govde.startswith(satirlar[0].ham):
            satirlar = []
        if _KANIT_BASI.match(metin):
            blokta = True
        elif blokta and not satirlar and len(metin) > 120:
            blokta = False
        if not blokta or not satirlar:
            continue
        if alt is not None:
            bolum, cikarim = alt, False
        elif ana is not None:
            # başlık numarası otomatik listeden geliyor (metinde yok): ilk alt ölçüt
            bolum, cikarim = f"{ana}.1", True
        else:
            continue
        for k in satirlar:
            anahtar = (bolum, k.olcut, k.kanit_no, k.od, k.kalan.strip().lower())
            if anahtar in gorulen:
                continue
            gorulen.add(anahtar)
            out.append(
                RaporKaniti(
                    bolum=bolum,
                    bolum_cikarim=cikarim,
                    od=k.od,
                    kanit_no=k.kanit_no,
                    kod_olcut=k.olcut,
                    ad=k.kalan,
                    ham=k.ham,
                    rapor=ad,
                    sorun=k.sorun,
                )
            )
    return out
