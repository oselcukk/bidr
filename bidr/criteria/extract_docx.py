"""FR-0833 BİDR şablonundan (docx) ölçüt şemasını ve kılavuz kurallarını çıkarır.

Çıktılar: `yokak-2025.yaml` (ölçütler), `guide.yaml` (kılavuz bölümleri) ve `ornek-uygulamalar.yaml`
(şablon sonundaki "Örnek Uygulama ve Kanıtlar Listesi" tabloları: alan, uygulama, kanıt; alt ölçüt
eşlemesi elle `bidr/data/ihtiyac_ornek_uygulama.yaml`'dadır).

Kullanım:
    python -m bidr.criteria.extract_docx ŞABLON.docx [--out bidr/data/criteria]
    python -m bidr.criteria.extract_docx ŞABLON.docx --stdout   # yazmadan JSON döker

Metin politikası: hücre/paragraf metni birebir alınır. Yalnız şunlar yapılır:
  * her maddenin baş/son boşlukları kırpılır, boş satırlar atılır;
  * `REDACTIONS` içindeki kurum adı belirteçleri yer tutucuyla değiştirilir
    (repo herkese açık); yapılan her değişiklik `meta.redactions` altında kayıtlıdır.
Özetleme, yazım düzeltme veya ekleme yapılmaz.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import yaml

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# Kurum adı belirteçleri -> yer tutucu. Kelime sınırıyla eşlenir.
REDACTIONS: list[tuple[str, str]] = [
    ("Gebze Teknik Üniversitesi", "[KURUM]"),
    ("GTÜ", "[KURUM]"),
    ("GTU", "[KURUM]"),
]

RE_SUB = re.compile(r"^([A-D])\.(\d+)\.(\d+)\.?\s*(.*)$", re.S)
RE_MAIN = re.compile(r"^([A-D])\.(\d+)\.\s*(.*)$", re.S)
RE_AREA = re.compile(r"^([A-D])\.\s*(.*)$", re.S)
UNITS_PREFIX = "DOLDURACAK BİRİMLER:"
EXAMPLE_PREFIX = "Örnek Kanıtlar:"
PLACEHOLDER_PREFIXES = ("Açıklamalar:", "Kanıtlar:")

# Kılavuzdan alınan bölümler (şablondaki başlık metniyle, sırayla).
GUIDE_SECTIONS = [
    "Hazırlama Yöntemi ve Takvimi",
    "Sorumlu Birimler",
    "Kapsam",
    "Açıklama Metni Yazımı",
    "Ölçüt Değerlendirme Şekli",
    "Yazım Kuralları",
    "Kanıt Gösterimi",
]
GUIDE_STOP = "ÖLÇÜTLER VE KANITLAR"
ANNEX_HEADING = "Örnek Uygulama ve Kanıtlar Listesi"
ANNEX_STOP_SUFFIX = "ÖRNEK UYGULAMALAR VE OLASI KANITLAR"
GUIDE_PARENT = "BİDR Hazırlarken Dikkat Edilmesi Gereken Hususlar"
# Ek tabloları: "<ALAN> ÖRNEK UYGULAMALAR VE OLASI KANITLAR" başlığından sonra "Uygulama | Kanıt" tablosu.
ANNEX_TABLE_HEAD = ("Uygulama", "Kanıt")
ANNEX_AREAS = (("LİDERLİK", "A"), ("EĞİTİM", "B"), ("ARAŞTIRMA", "C"), ("TOPLUMSAL", "D"))
ORNEK_FILE = "ornek-uygulamalar.yaml"


class Redactor:
    def __init__(self) -> None:
        self.log: dict[tuple[str, str, str], list[str]] = {}

    def __call__(self, text: str, where: str, field: str) -> str:
        for token, repl in REDACTIONS:
            pat = re.compile(r"(?<!\w)" + re.escape(token) + r"(?!\w)")
            if pat.search(text):
                text = pat.sub(repl, text)
                self.log.setdefault((field, token, repl), []).append(where)
        return text

    def report(self) -> list[dict]:
        out = []
        for (field, token, repl), wheres in self.log.items():
            # Özgün belirteç veriye yazılmaz; yalnız türü ve yeri.
            out.append({"field": field, "kind": "kurum adı", "to": repl,
                        "ids": sorted(set(wheres))})
        return out


def _ptext(p) -> str:
    """Paragraf metni (w:t + w:tab + w:br), python-docx olmadan da tutarlı."""
    parts = []
    for el in p.iter():
        if el.tag == W + "t":
            parts.append(el.text or "")
        elif el.tag == W + "tab":
            parts.append("\t")
        elif el.tag in (W + "br", W + "cr"):
            parts.append("\n")
    return "".join(parts)


def _cell_lines(tc) -> list[str]:
    """Hücredeki paragrafları satır listesi olarak verir (boşlar atılır, kırpılır)."""
    lines: list[str] = []
    for p in tc.iter(W + "p"):
        for piece in _ptext(p).split("\n"):
            s = piece.strip()
            if s:
                lines.append(s)
    return lines


def _row_cells(tr) -> list:
    return [tc for tc in tr.iterchildren(W + "tc")]


def _iter_body(doc):
    """(tür, öğe) çiftleri: ('p', w:p) veya ('tbl', w:tbl)."""
    for el in doc.element.body.iterchildren():
        tag = el.tag.split("}")[1]
        if tag in ("p", "tbl"):
            yield tag, el


def extract(path: Path) -> tuple[dict, dict, list[str]]:
    import docx  # python-docx

    doc = docx.Document(str(path))
    red = Redactor()
    warnings: list[str] = []
    body = list(_iter_body(doc))

    # --- ölçüt tabloları: "ÖLÇÜTLER VE KANITLAR" ile ilk SWOT tablosu arası ---
    start = next(i for i, (t, el) in enumerate(body)
                 if t == "p" and _ptext(el).strip() == GUIDE_STOP)
    mains: list[dict] = []
    subs: list[dict] = []
    pending_units: list[str] | None = None
    current_main: dict | None = None
    current_sub: dict | None = None
    expect_rubric = False

    for t, el in body[start + 1:]:
        if t != "tbl":
            continue
        rows = list(el.iter(W + "tr"))
        first = _cell_lines(_row_cells(rows[0])[0]) if rows else []
        if not first or not (first[0].startswith(UNITS_PREFIX) or RE_MAIN.match(first[0])):
            break  # ölçüt tabloları bitti (SWOT tablosu)
        for tr in rows:
            cells = _row_cells(tr)
            lines = [_cell_lines(c) for c in cells]
            head = lines[0][0] if lines and lines[0] else ""
            flat = [" ".join(l) for l in lines]
            if expect_rubric:
                if len(cells) != 5:
                    warnings.append(f"{current_sub['id']}: rubrik satırı {len(cells)} hücre")
                current_sub["rubric"] = {
                    i + 1: red("\n".join(lines[i]), current_sub["id"], "rubric")
                    for i in range(min(5, len(cells)))
                }
                expect_rubric = False
                continue
            if [s.strip() for s in flat] == ["1", "2", "3", "4", "5"]:
                expect_rubric = True
                continue
            if head.startswith(UNITS_PREFIX):
                pending_units = lines[0]
                continue
            if head.startswith(EXAMPLE_PREFIX):
                rest = head[len(EXAMPLE_PREFIX):].strip()
                items = ([rest] if rest else []) + lines[0][1:]
                current_sub["example_evidence"] = [
                    red(x, current_sub["id"], "example_evidence") for x in items]
                continue
            if head.startswith(PLACEHOLDER_PREFIXES):
                continue
            m = RE_SUB.match(head)
            if m:
                sid = f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
                if pending_units is None:
                    warnings.append(f"{sid}: DOLDURACAK BİRİMLER bulunamadı")
                    pending_units = []
                u0 = pending_units[0][len(UNITS_PREFIX):].strip() if pending_units else ""
                current_sub = {
                    "id": sid,
                    "title": m.group(4).strip(),
                    "parent": f"{m.group(1)}.{m.group(2)}",
                    "description": [red(x, sid, "description") for x in lines[0][1:]],
                    "units": red(u0, sid, "units"),
                }
                notes = [red(x, sid, "units_note") for x in pending_units[1:]]
                if notes:
                    current_sub["units_note"] = notes
                pending_units = None
                subs.append(current_sub)
                if current_main is None or current_main["id"] != current_sub["parent"]:
                    warnings.append(f"{sid}: üst ölçüt başlığı görülmeden geldi")
                continue
            m = RE_MAIN.match(head)
            if m:
                mid = f"{m.group(1)}.{m.group(2)}"
                current_main = {
                    "id": mid,
                    "title": m.group(3).strip(),
                    "parent": m.group(1),
                    "description": [red(x, mid, "description") for x in lines[0][1:]],
                }
                mains.append(current_main)
                continue
            warnings.append(f"tanınmayan satır: {head[:60]!r}")

    # --- ana alanlar ve özet tablo: "SORUMLU BİRİMLER ÖZET LİSTESİ" ---
    areas: list[dict] = []
    summary: dict[str, dict] = {}
    for t, el in body:
        if t != "tbl":
            continue
        rows = list(el.iter(W + "tr"))
        hdr = [" ".join(_cell_lines(c)) for c in _row_cells(rows[0])] if rows else []
        if "KIDR Bölümü" not in hdr:
            continue
        for tr in rows[1:]:
            cl = [" ".join(_cell_lines(c)) for c in _row_cells(tr)]
            cl = [c for c in cl if c]
            if len(cl) == 1:
                m = RE_AREA.match(cl[0])
                if m:
                    areas.append({"id": m.group(1), "title": m.group(2).strip()})
            elif len(cl) >= 2:
                m = RE_SUB.match(cl[1])
                if m:
                    sid = f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
                    summary[sid] = {"title": m.group(4).strip(),
                                    "units": cl[2] if len(cl) > 2 else ""}
        break
    if not areas:
        warnings.append("ana alan başlıkları (SORUMLU BİRİMLER ÖZET LİSTESİ) bulunamadı")
    for a in areas:
        a["description"] = []  # şablonda ana alan açıklaması bulunamadı

    # çapraz denetim: blok başlıkları vs özet tablo
    for s in subs:
        sm = summary.get(s["id"])
        if sm is None:
            warnings.append(f"{s['id']}: özet tabloda yok")
        elif sm["title"] != s["title"]:
            warnings.append(f"{s['id']}: başlık farkı blok={s['title']!r} özet={sm['title']!r}")
    for sid in summary:
        if sid not in {s["id"] for s in subs}:
            warnings.append(f"{sid}: özet tabloda var, blokta yok")
    for s in subs:
        for k in ("rubric", "example_evidence"):
            if k not in s:
                warnings.append(f"{s['id']}: {k} bulunamadı")

    sha = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    criteria = {
        "meta": {
            "schema_version": 1,
            "framework": "YÖKAK KİDR ölçütleri (BİDR şablonu FR-0833 Değ.No:1, 10.11.2026)",
            "source_form": "FR-0833 Birim İç Değerlendirme Raporu (BİDR) şablonu, Değ.No:1 (10.11.2026)",
            "source_sha256": sha,
            "extracted_by": "bidr.criteria.extract_docx",
            "text_policy": ("Metinler şablondan birebir; yalnız baş/son boşluk kırpıldı, "
                            "boş satırlar atıldı, kurum adı yer tutucuyla değiştirildi "
                            "(bkz. redactions)."),
            "counts": {"areas": len(areas), "criteria": len(mains),
                       "sub_criteria": len(subs)},
            "notes": ["Ana alanlar (A-D) için şablonda açıklama metni bulunamadı; "
                      "başlıklar 'SORUMLU BİRİMLER ÖZET LİSTESİ' tablosundan alındı."],
            "redactions": [],
        },
        "areas": areas,
        "criteria": mains,
        "sub_criteria": subs,
    }

    guide = extract_guide(body, red, sha, warnings)
    criteria["meta"]["redactions"] = red.report()
    return criteria, guide, warnings


def extract_annex(path: Path) -> tuple[dict, list[str]]:
    """Kılavuz eki "Örnek Uygulama ve Kanıtlar Listesi" tabloları: alan başına "Uygulama | Kanıt"
    satırları. Satır kimliği `<alan>/<sıra>` (alan içinde 1'den, şablon sırası; ör. `C/2`). Metinler
    birebir (hücre içi satır sonları boşlukla birleşir; kurum adı yer tutucuyla)."""
    import docx  # python-docx

    doc = docx.Document(str(path))
    red = Redactor()
    warnings: list[str] = []
    alanlar: dict[str, str] = {}
    satirlar: list[dict] = []
    heading = ""
    for t, el in _iter_body(doc):
        if t == "p":
            txt = _ptext(el).strip()
            if txt:
                heading = txt
            continue
        rows = list(el.iter(W + "tr"))
        if not rows:
            continue
        hdr = tuple(" ".join(_cell_lines(c)) for c in _row_cells(rows[0]))
        if hdr[:2] != ANNEX_TABLE_HEAD:
            continue
        alan = next((a for k, a in ANNEX_AREAS if heading.startswith(k)), None)
        if alan is None or not heading.endswith(ANNEX_STOP_SUFFIX):
            warnings.append(f"ek tablosunun alan başlığı tanınmadı: {heading[:60]!r}")
            continue
        alanlar[alan] = heading[: -len(ANNEX_STOP_SUFFIX)].strip()
        n = sum(1 for x in satirlar if x["alan"] == alan)
        for tr in rows[1:]:
            cl = [" ".join(_cell_lines(c)) for c in _row_cells(tr)]
            if len(cl) < 2 or not (cl[0] or cl[1]):
                continue
            n += 1
            rid = f"{alan}/{n}"
            satirlar.append({"id": rid, "alan": alan, "uygulama": red(cl[0], rid, "uygulama"),
                             "kanit": red(cl[1], rid, "kanit")})
    if not satirlar:
        warnings.append(f"kılavuz eki tabloları bulunamadı ({ANNEX_HEADING})")
    sha = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return {
        "meta": {
            "schema_version": 1,
            "source_form": "FR-0833 Birim İç Değerlendirme Raporu (BİDR) şablonu, Değ.No:1 (10.11.2026)",
            "source_section": ANNEX_HEADING,
            "source_sha256": sha,
            "extracted_by": "bidr.criteria.extract_docx",
            "text_policy": ("Hücre metinleri birebir; hücre içi satır sonları boşlukla birleşti, "
                            "kurum adı yer tutucuyla değiştirildi (bkz. redactions)."),
            "counts": {a: sum(1 for x in satirlar if x["alan"] == a) for a in alanlar},
            "notes": ["Satırlar alan düzeyindedir (şablonda alt ölçüt verilmez); alt ölçüt eşlemesi "
                      "elle yapılmıştır: bidr/data/ihtiyac_ornek_uygulama.yaml."],
            "redactions": red.report(),
        },
        "alanlar": alanlar,
        "satirlar": satirlar,
    }, warnings


def extract_guide(body, red: Redactor, sha: str, warnings: list[str]) -> dict:
    paras = [(i, _ptext(el).strip()) for i, (t, el) in enumerate(body) if t == "p"]
    sections: list[dict] = []
    cur: dict | None = None
    in_guide = False
    for i, txt in paras:
        if txt == GUIDE_PARENT:
            in_guide = True
            continue
        if not in_guide:
            continue
        if txt == GUIDE_STOP:
            break
        if txt in GUIDE_SECTIONS:
            cur = {"section": txt, "parent": GUIDE_PARENT, "text": []}
            sections.append(cur)
            continue
        if cur is not None and txt:
            cur["text"].append(red(txt, cur["section"], "guide"))
    found = {s["section"] for s in sections}
    for s in GUIDE_SECTIONS:
        if s not in found:
            warnings.append(f"kılavuz bölümü bulunamadı: {s}")

    # Ek: "Örnek Uygulama ve Kanıtlar Listesi" giriş metni (uygun/uygun olmayan kanıt)
    annex = {"section": ANNEX_HEADING, "parent": None, "text": []}
    seen = False
    for i, txt in paras:
        if txt == ANNEX_HEADING:
            seen = True
            continue
        if not seen or not txt:
            continue
        if txt.endswith(ANNEX_STOP_SUFFIX):
            break
        annex["text"].append(red(txt, ANNEX_HEADING, "guide"))
    if annex["text"]:
        sections.append(annex)
    else:
        warnings.append(f"kılavuz eki bulunamadı: {ANNEX_HEADING}")

    return {
        "meta": {
            "schema_version": 1,
            "source_form": "FR-0833 Birim İç Değerlendirme Raporu (BİDR) şablonu, Değ.No:1 (10.11.2026)",
            "source_sha256": sha,
            "extracted_by": "bidr.criteria.extract_docx",
            "text_policy": "Paragraflar birebir alıntıdır; her bölüm şablondaki başlık adıyla.",
            "notes": [
                "Kurum tanıtım bölümü (kurum adı, e-posta, paylaşım bağlantısı içerir) alınmadı.",
                "Şekil 1 ve Şekil 2 görseldir; metinleri çıkarılmadı.",
            ],
        },
        "sections": sections,
        # Kanıt gösterimi: kılavuzdaki örnekten türetilen makine kuralı (alıntı değil).
        "evidence_notation": {
            "derived_from": "Kanıt Gösterimi",
            "in_text": {"pattern": r"\[(\d+)_OD([1-5])\]", "example": "[1_OD3]"},
            "evidence_list": {"pattern": r"^\[(\d+)-OD([1-5])\]\.\s*(.+)$",
                              "example": "[1-OD3]. Uygulama Örnekleri.pdf"},
            "fields": {"1": "kanıt sıra numarası", "2": "olgunluk düzeyi (OD)"},
        },
    }


def _dump_yaml(data: dict, path: Path, header: str) -> None:
    class _D(yaml.SafeDumper):
        pass

    def _str(dumper, s):
        style = "|" if "\n" in s else None
        return dumper.represent_scalar("tag:yaml.org,2002:str", s, style=style)

    _D.add_representer(str, _str)
    text = yaml.dump(data, Dumper=_D, allow_unicode=True, sort_keys=False, width=10_000)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("template", type=Path, help="boş BİDR şablonu (.docx)")
    ap.add_argument("--out", type=Path, default=None,
                    help="çıktı klasörü (vars.: repo bidr/data/criteria)")
    ap.add_argument("--stdout", action="store_true", help="dosya yazma; JSON'u bas")
    a = ap.parse_args(argv)
    criteria, guide, warnings = extract(a.template)
    ornek, w2 = extract_annex(a.template)
    warnings += w2
    for w in warnings:
        print(f"UYARI: {w}", file=sys.stderr)
    if a.stdout:
        json.dump({"criteria": criteria, "guide": guide, "ornek_uygulamalar": ornek}, sys.stdout,
                  ensure_ascii=False, indent=1)
        return 0
    from .loader import DEFAULT_DIR
    out = a.out or DEFAULT_DIR
    hdr = ("# Üretildi: python -m bidr.criteria.extract_docx <şablon.docx>\n"
           "# Elle düzenlemeyin; şablon değişince yeniden üretin.\n")
    _dump_yaml(criteria, out / "yokak-2025.yaml", hdr)
    _dump_yaml(guide, out / "guide.yaml", hdr)
    _dump_yaml(ornek, out / ORNEK_FILE, hdr)
    c = criteria["meta"]["counts"]
    print(f"{out}: {c['areas']} alan, {c['criteria']} ölçüt, {c['sub_criteria']} alt ölçüt, "
          f"{len(guide['sections'])} kılavuz bölümü, {len(ornek['satirlar'])} ek örnek uygulama satırı, "
          f"{len(warnings)} uyarı")
    return 0


if __name__ == "__main__":
    sys.exit(main())
