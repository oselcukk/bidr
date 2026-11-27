"""Geçen yılın doldurulmuş FR-0833 raporundan ölçüt başına özet (modelsiz, salt okur).

Her alt ölçüt için: `olcut`, `od` (işaretli düzey), `od_kaynak`, `aciklama` (Açıklamalar hücresinin metni),
`kanitlar` ([{no, od, ad, kod_olcut}], Kanıtlar hücresindeki kodlu satırlar; `bidr.labels.parse.kanit_satirlari`).

OD nasıl bulunur:
  - `isaret`: rubrik satırında tek sütun ötekilerden ayrı biçimlenmiş (kalın, farklı gölge ya da vurgulu; Kimya
    2025 usulü kalın). Birden çok sütun işaretliyse en yükseği alınır, hepsi `od_isaretli`de, uyarı yazılır.
  - `kanit_kodlari`: rubrikte işaret yoksa (Matematik/Fizik/MBG 2025 usulü) kanıt kodlarındaki en yüksek OD.
  - işaret de kod da yoksa `od` boş (None).

docx: blok düzeni `bidr.render.template.find_blocks` ile aynı. PDF: metin katmanı (pypdf); başlık satırı
ölçüt kimliği + ölçüt başlığının başıyla tanınır, "Açıklamalar:" / "Kanıtlar:" arası okunur; PDF'te biçim
okunmaz, OD yalnız kanıt kodlarından gelir.

Çıktı (`onceki-yil.json`) kanıt değildir: kanıt havuzuna, kanıt numaralarına, maskelemeye ya da teslim paketine
girmez; yalnız yazım/doğrulama paketlerine karşılaştırma bağlamı olarak verilir (bidr/onceki/baglam.py).
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path

SURUM = 1
DOSYA = "onceki-yil.json"
BOS_IFADE = re.compile(r"^\s*(bu\s+kısım\s+için\s+veri\s+bulunmamaktadır|veri\s+bulunmamaktadır|-+|yok"
                       r"|bu\s+ölçüt\s+için\s+bu\s+dönemde\s+kanıt\s+bulunamamıştır|kanıt\s+bulunamamıştır|bu\s+ölçüt\s+için\s+kanıt\s+bulunmamaktadır)\s*\.?\s*$", re.I)
_ACIKLAMA = re.compile(r"^\s*Açıklamalar\s*:\s*", re.I)
_KANIT = re.compile(r"^\s*Kanıtlar\s*:\s*", re.I)


def _norm(s: str) -> str:
    s = s.replace("I", "ı").replace("İ", "i").lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


def _bos_mu(metin: str) -> bool:
    return not metin.strip() or bool(BOS_IFADE.match(metin))


def kanitlari_coz(metin: str) -> list[dict]:
    """Kanıtlar hücresinin metni → [{no, od, ad, kod_olcut}] (kodsuz satır atlanır)."""
    from bidr.labels.parse import kanit_satirlari

    out = []
    for k in kanit_satirlari(metin):
        if k.od is None and k.kanit_no is None:
            continue
        out.append({"no": k.kanit_no, "od": int(k.od[2:]) if k.od else None,
                    "ad": " ".join(k.kalan.split())[:300], "kod_olcut": k.olcut})
    return out


def _kayit(olcut: str, aciklama: str, kanit_metni: str, od_isaretli: list[int]) -> dict:
    aciklama = aciklama.strip()
    if _bos_mu(aciklama):
        aciklama = ""
    kanitlar = [] if _bos_mu(kanit_metni) else kanitlari_coz(kanit_metni)
    kod_od = [k["od"] for k in kanitlar if k["od"]]
    if od_isaretli:
        od, kaynak = max(od_isaretli), "isaret"
    elif kod_od:
        od, kaynak = max(kod_od), "kanit_kodlari"
    else:
        od, kaynak = None, None
    return {"olcut": olcut, "od": od, "od_kaynak": kaynak, "od_isaretli": sorted(od_isaretli),
            "aciklama": aciklama, "kanitlar": kanitlar}


# -- docx -----------------------------------------------------------------------------------------

def _bold_orani(tc, W) -> float:
    rs = [r for r in tc.iter(W + "r") if "".join(t.text or "" for t in r.iter(W + "t")).strip()]
    if not rs:
        return 0.0

    def kalin(r) -> bool:
        rp = r.find(W + "rPr")
        b = rp.find(W + "b") if rp is not None else None
        return b is not None and b.get(W + "val") not in ("0", "false", "off")
    return sum(kalin(r) for r in rs) / len(rs)


def _golge(tc, W) -> str:
    s = tc.find(W + "tcPr/" + W + "shd") if tc.find(W + "tcPr") is not None else None
    return (s.get(W + "fill") or "").upper() if s is not None else ""


def _vurgu(tc, W) -> bool:
    return any((h.get(W + "val") or "none") != "none" for h in tc.iter(W + "highlight"))


def rubrik_isareti(block, W) -> list[int]:
    """Rubrik satırlarında ötekilerden ayrı biçimlenmiş sütunlar (1..5)."""
    isaretli: set[int] = set()
    for row in block.rubric:
        if len(row) != 5:
            continue
        kalin = [_bold_orani(c, W) >= 0.6 for c in row]
        if 0 < sum(kalin) < 5:
            isaretli |= {i + 1 for i, k in enumerate(kalin) if k}
        golge = [_golge(c, W) for c in row]
        cok = max(set(golge), key=golge.count)
        if golge.count(cok) >= 3:
            isaretli |= {i + 1 for i, g in enumerate(golge) if g != cok}
        vurgu = [_vurgu(c, W) for c in row]
        if 0 < sum(vurgu) < 5:
            isaretli |= {i + 1 for i, v in enumerate(vurgu) if v}
    return sorted(isaretli)


def _hucre_govdesi(tc, etiket: re.Pattern, cell_lines) -> str:
    """Hücre metni, baştaki etiket ("Açıklamalar:") atılmış; paragraflar satır sonuyla."""
    lines = [x.replace("\xa0", " ") for x in cell_lines(tc)] if tc is not None else []
    if lines:
        lines[0] = etiket.sub("", lines[0], count=1)
    return "\n".join(x for x in (s.strip() for s in lines) if x)


def _etiketsiz_aciklama(kanit_tc, W, cell_lines):
    """Bölüm "Açıklamalar:" etiketini silip metni yazmışsa: Kanıtlar satırından hemen önceki tek hücreli satır
    (Örnek Kanıtlar ya da rubrik değilse)."""
    tr = kanit_tc.getparent()
    prev = tr.getprevious() if tr is not None else None
    while prev is not None and prev.tag != W + "tr":
        prev = prev.getprevious()
    if prev is None:
        return None
    cells = list(prev.iterchildren(W + "tc"))
    if len(cells) != 1:
        return None
    lines = cell_lines(cells[0])
    if not lines or _ORNEK.match(lines[0]) or _KANIT.match(lines[0]):
        return None
    return cells[0]


def oku_docx(path: Path) -> tuple[dict[str, dict], list[str]]:
    import docx

    from bidr.criteria.extract_docx import W, _cell_lines
    from bidr.render.template import find_blocks

    doc = docx.Document(str(path))
    blocks, uy = find_blocks(doc)
    out: dict[str, dict] = {}
    for sid, b in blocks.items():
        if b.aciklama_tc is None and b.kanit_tc is not None:
            b.aciklama_tc = _etiketsiz_aciklama(b.kanit_tc, W, _cell_lines)
            if b.aciklama_tc is not None:
                uy = [u for u in uy if not u.startswith(f"{sid}: 'Açıklamalar:'")]
                uy.append(f"{sid}: 'Açıklamalar:' etiketi silinmiş; Kanıtlar'dan önceki hücre açıklama sayıldı")
        ac = _hucre_govdesi(b.aciklama_tc, _ACIKLAMA, _cell_lines)
        kn = _hucre_govdesi(b.kanit_tc, _KANIT, _cell_lines)
        out[sid] = _kayit(sid, ac, kn.replace("\n", " "), rubrik_isareti(b, W))
    return out, uy


# -- pdf ------------------------------------------------------------------------------------------

_BASLIK = re.compile(r"^\s*([A-D])\.(\d+)\.(\d+)\.\s*(.*)$")
_ALT_SON = re.compile(r"^\s*(DOLDURACAK\s+BİRİMLER|SORUMLU\s+BİRİMLER|Güçlü\s+Yönler|[A-D]\.\d+\.\s+[^\d])")
_ALTBILGI = re.compile(r"^\s*(Sayfa\s+\d+\s*/\s*\d+|Form\s+No\s*:.*FR-0833.*)\s*$", re.I)
_ORNEK = re.compile(r"^\s*Örnek\s+Kanıtlar\s*:", re.I)


def _pdf_satirlari(path: Path) -> list[str]:
    import pypdf

    r = pypdf.PdfReader(str(path))
    lines: list[str] = []
    for p in r.pages:
        for s in (p.extract_text() or "").splitlines():
            s = s.replace("\xa0", " ").replace("\xad", "-")
            if not _ALTBILGI.match(s):
                lines.append(s.rstrip())
    return lines


def _paragraflar(lines: list[str]) -> str:
    """PDF satırları → boş satırla ayrılmış paragraflar (satır kırılımları birleşir)."""
    paras, cur = [], []
    for s in lines:
        if s.strip():
            cur.append(s.strip())
        elif cur:
            paras.append(" ".join(cur))
            cur = []
    if cur:
        paras.append(" ".join(cur))
    return "\n".join(paras)


def oku_pdf(path: Path) -> tuple[dict[str, dict], list[str]]:
    from bidr.criteria.loader import load_criteria

    cs = load_criteria()
    basliklar = {s.id: _norm(s.title)[:18] for s in cs.sub_criteria}
    lines = _pdf_satirlari(path)
    adaylar: dict[str, list[dict]] = {}
    cur = None
    bolum = None   # None | "aciklama" | "kanit"
    for s in lines:
        m = _BASLIK.match(s)
        if m:
            sid = f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
            bas = basliklar.get(sid)
            if bas and _norm(m.group(4)).startswith(bas[:12]):
                cur = {"olcut": sid, "aciklama": [], "kanit": [], "acik": False}
                adaylar.setdefault(sid, []).append(cur)
                bolum = None
                continue
        if cur is None:
            continue
        if _ALT_SON.match(s):
            cur, bolum = None, None
            continue
        if _ORNEK.match(s):
            bolum = None
            continue
        if _ACIKLAMA.match(s):
            bolum, cur["acik"] = "aciklama", True
            s = _ACIKLAMA.sub("", s, count=1)
        elif _KANIT.match(s) and bolum == "aciklama":
            bolum = "kanit"
            s = _KANIT.sub("", s, count=1)
        if bolum:
            cur[bolum].append(s)
    out: dict[str, dict] = {}
    uy: list[str] = []
    for sid, cs_ in adaylar.items():
        dolu = [c for c in cs_ if c["acik"]]
        if not dolu:
            continue
        if len(dolu) > 1:
            uy.append(f"{sid}: PDF'te iki blok; sonuncusu kullanıldı")
        c = dolu[-1]
        out[sid] = _kayit(sid, _paragraflar(c["aciklama"]), " ".join(x.strip() for x in c["kanit"]), [])
    return out, uy


# -- giriş noktası --------------------------------------------------------------------------------

def oku(path: Path) -> dict:
    """Rapor → `onceki-yil.json` içeriği."""
    path = Path(path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"geçen yılın raporu bulunamadı: {path}")
    ext = path.suffix.lower()
    if ext == ".docx":
        olcutler, uy = oku_docx(path)
    elif ext == ".pdf":
        olcutler, uy = oku_pdf(path)
    else:
        raise ValueError(f"desteklenmeyen biçim: {path.suffix or '(uzantı yok)'} (docx ya da pdf)")
    from bidr.criteria.model import id_key

    olcutler = {k: olcutler[k] for k in sorted(olcutler, key=id_key)}
    for k, r in olcutler.items():
        if len(r["od_isaretli"]) > 1:
            uy.append(f"{k}: rubrikte birden çok düzey işaretli ({', '.join(map(str, r['od_isaretli']))}); "
                      f"en yükseği alındı")
    dolu = [r for r in olcutler.values() if r["aciklama"]]
    return {"surum": SURUM, "uretim": datetime.now().astimezone().isoformat(timespec="seconds"),
            "kaynak": {"ad": path.name, "bicim": ext[1:], "sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
            "ozet": {"olcut": len(olcutler), "aciklamali": len(dolu),
                     "od_bulunan": sum(1 for r in dolu if r["od"]),
                     "od_isaret": sum(1 for r in dolu if r["od_kaynak"] == "isaret"),
                     "od_kanit_kodlari": sum(1 for r in dolu if r["od_kaynak"] == "kanit_kodlari")},
            "uyarilar": uy, "olcutler": olcutler}


def yaz(veri: dict, hedef: Path) -> Path:
    hedef = Path(hedef)
    hedef.parent.mkdir(parents=True, exist_ok=True)
    gecici = hedef.with_name(hedef.name + ".yaziliyor")
    gecici.write_text(json.dumps(veri, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    gecici.replace(hedef)
    return hedef
