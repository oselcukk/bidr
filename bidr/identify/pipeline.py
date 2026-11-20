"""identify aşaması: text/<doc_id>.txt -> documents.jsonl (+ identify-report.md).

Sınıflandırıcıya yalnız belge METNİ gider. inventory.csv'den yalnız şu sütunlar
okunur: doc_id, dup_of (yalnız boş/dolu), status, method, pages ve ingest'in içerikten
kurduğu parça grubu (parca_grubu, parca_sira). Yol/ad/uzantı sütunları (rel_path, ext)
okunmaz; `INVENTORY_COLUMNS` dışındakiler atılır.
"""
from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path
from typing import Callable

from bidr.common import Workspace, write_jsonl

from . import versions
from .catalog import UNKNOWN, Catalog, load_catalog
from .classify import classify
from .dates import (DateFinder, academic_terms, date_ranges, plan_span, term_year, update_dates,
                    year_phrases)
from .naming import title, working_name
from .text import collapse, fold

INVENTORY_COLUMNS = ("doc_id", "dup_of", "status", "method", "pages", "parca_grubu", "parca_sira")
SCHEMA_VERSION = 1


def read_inventory(ws: Workspace) -> list[dict]:
    """Tekil belgeler; yalnız izinli sütunlar (yol/ad içermez)."""
    rows: dict[str, dict] = {}
    with open(ws.inventory, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            did = r.get("doc_id")
            if not did or r.get("dup_of") or did in rows:
                continue
            rows[did] = {k: r.get(k, "") for k in INVENTORY_COLUMNS if k != "dup_of"}
    return list(rows.values())


def _format(method: str) -> str:
    m = (method or "").lower()
    if "docx" in m or "xml" in m or m.startswith(("openpyxl", "text", "pptx", "textutil")):
        return "duzenlenebilir"
    if "ocr" in m or m == "agent_vision":
        return "tarama"
    if m.startswith("pdftotext"):
        return "pdf_metin"
    return m or "bilinmiyor"


def date_fields(folded: str, finder: DateFinder, type_labels: list[str], head: int,
                period: int | None = None) -> dict:
    """Katlanmış metnin tarih alanları (belge ya da birleşik belgenin bir parçası)."""
    found = finder.content_dates(folded)
    d, src, _ = finder.primary(folded, type_labels, found, head=head)
    terms = academic_terms(folded, head)
    distinct = sorted({f.d.isoformat() for f in found})
    r: dict = {"tarih": d.isoformat() if d else None, "tarih_kaynagi": src, "tarihler": distinct[:30],
               "tarih_araligi": [distinct[0], distinct[-1]] if distinct else None,
               "akademik_donem": terms[:5]}
    # dönem kuralının ek girdileri (bidr/audit/donem.py): aralıklar, yürürlük aralığı, yıl
    # ifadeleri, sayfa güncelleme damgası
    r["tarih_araliklari"] = [[a.d.isoformat() if a else None, b.d.isoformat()]
                             for a, b in date_ranges(folded, found)][:30]
    span = plan_span(folded, head)
    r["yururluk_araligi"] = list(span) if span else None
    r["yil_ifadeleri"] = year_phrases(folded)[:5]
    upd = update_dates(folded)
    r["guncelleme_tarihi"] = upd[-1].isoformat() if upd else None
    if period is not None:
        ici, kanit = None, None
        if d:
            ici, kanit = d.year == period, "tarih"
        else:
            ys = [term_year(x) for x in terms if term_year(x)]
            if ys:
                ici, kanit = period in ys, "akademik_donem"
        r["donem"] = period
        r["donem_ici"] = ici
        r["donem_kaniti"] = kanit
    return r


def identify_text(raw: str, catalog: Catalog, finder: DateFinder,
                  period: int | None = None) -> dict:
    """Tek metin için kayıt (sürüm grubu ve çalışma adı tekilleştirmesi hariç)."""
    r = classify(raw, catalog)
    doc = r.pop("_doc")
    t = catalog.get(r["doc_type"])
    labels = t.date_labels if t else []
    r.update(date_fields(doc.folded, finder, labels, catalog.regions["bas"], period))
    # birleşik/derleme belge: parça başına tarih (bidr/identify/parca.py; dönem kuralı eşleşme
    # başına alıntının parçasının tarihini kullanır)
    pages = raw.split("\f")
    if len(pages) > 1:
        from .parca import parts_record
        r["parcalar"] = parts_record(pages, lambda part: date_fields(
            fold(collapse(part)), finder, labels, catalog.regions["bas"], period))
    else:
        r["parcalar"] = []
    label = t.label if t else "Bilinmeyen Belge"
    r["doc_type_etiket"] = label
    r["baslik"] = title(r["doc_type"], doc, r["kanitlar"])
    r["calisma_adi"] = working_name(r["tarih"], r["doc_type"], label, r["baslik"])
    r["_folded"] = doc.folded
    return r


def run(workspace: Path, *, period: int | None = None, catalog: Catalog | None = None,
        institutions: list[str] | None = None, write_report: bool = True,
        log: Callable[[str], None] | None = None) -> list[dict]:
    log = log or (lambda m: print(m, file=sys.stderr))
    ws = Workspace(workspace)
    if not ws.inventory.exists():
        raise FileNotFoundError(f"{ws.inventory} yok; önce `bidr ingest` çalıştırın")
    catalog = catalog or load_catalog(institutions=institutions)
    finder = DateFinder(catalog.date_labels, catalog.excluded_date_labels)
    inv = read_inventory(ws)
    records = []
    for row in inv:
        did = row["doc_id"]
        p = ws.text_path(did)
        raw = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
        r = identify_text(raw, catalog, finder, period)
        if not p.exists():
            r["neden"] = "metin_dosyasi_yok"
        rec = {"doc_id": did, "sema": SCHEMA_VERSION, "katman": "kural",
               "katalog_surumu": catalog.version}
        rec.update(r)
        rec["metin"].update(durum=row.get("status") or None, bicim=_format(row.get("method", "")),
                            sayfa=int(row["pages"]) if (row.get("pages") or "").isdigit() else None)
        records.append(rec)

    # sürüm grupları (yalnız metin)
    groups = versions.group({r["doc_id"]: r["_folded"] for r in records},
                            {r["doc_id"]: r["tarih"] for r in records},
                            {r["doc_id"]: r["doc_type"] for r in records if r["doc_type"] != UNKNOWN})
    # tek belgenin bölünmüş parçaları (ingest `parca_grubu`, içerikten) aynı sürüm grubuna katılır:
    # dosyalama aynı ölçütte tek kanıt sayar, numaralama tek numara verir
    from bidr.ingest.parts import merge_into_versions
    parts = {row["doc_id"]: row.get("parca_grubu") or None for row in inv}
    part_no = {row["doc_id"]: row.get("parca_sira") or "" for row in inv}
    groups = merge_into_versions(groups, parts)
    by_id = {r["doc_id"]: r for r in records}
    for r in records:
        pg = parts.get(r["doc_id"])
        r["parca_grubu"] = pg
        r["parca_sira"] = int(part_no[r["doc_id"]]) if pg and str(part_no[r["doc_id"]]).isdigit() else None
        g = groups.get(r["doc_id"])
        r["surum_grubu"] = g["grup"] if g else None
        r["surum_uyeleri"] = g["uyeler"] if g else []
        r["surum_benzerlik"] = g["benzerlik"] if g else None
        if g:
            r["surum_bicimleri"] = sorted({by_id[x]["metin"]["bicim"] for x in [r["doc_id"], *g["uyeler"]]})
    # çalışma adı tekilleştirme: aynı sürüm grubu aynı adı paylaşır, sonuna biçim eklenir
    seen: Counter = Counter()
    for r in sorted(records, key=lambda r: (r["calisma_adi"], r["doc_id"])):
        r.pop("_folded", None)
        base = r["calisma_adi"]
        if r["surum_grubu"]:
            base = f"{base}__{r['metin']['bicim']}"
        seen[base] += 1
        r["calisma_adi"] = base if seen[base] == 1 else f"{base}-{seen[base]}"

    n = write_jsonl(ws.documents, records)
    log(f"documents.jsonl: {n} belge -> {ws.documents}")
    if write_report:
        (ws.root / "identify-report.md").write_text(report(records, catalog, period), encoding="utf-8")
    return records


def report(records: list[dict], catalog: Catalog, period: int | None) -> str:
    n = len(records)
    c = Counter(r["doc_type"] for r in records)
    unk = c.get(UNKNOWN, 0)
    lines = [
        "# identify raporu", "",
        f"- belge: {n}",
        f"- bilinmiyor: {unk} (%{100 * unk / n:.1f})" if n else "- bilinmiyor: 0",
        f"- katalog sürümü: {catalog.version}, eşik: {catalog.threshold}",
        f"- kurum profilleri: {', '.join(i.key for i in catalog.institutions) or '-'}",
    ]
    if period is not None:
        ic = Counter(r.get("donem_ici") for r in records)
        lines.append(f"- dönem {period}: içinde {ic.get(True, 0)}, dışında {ic.get(False, 0)}, "
                     f"belirsiz {ic.get(None, 0)}")
    g = {r["surum_grubu"] for r in records if r["surum_grubu"]}
    lines.append(f"- sürüm grubu: {len(g)} grup, {sum(1 for r in records if r['surum_grubu'])} belge")
    lines += ["", "## Tür dağılımı", "", "| tür | sayı | yüksek | orta | düşük |", "|---|---|---|---|---|"]
    for t, k in c.most_common():
        lv = Counter(r["guven_duzeyi"] for r in records if r["doc_type"] == t)
        lines.append(f"| {t} | {k} | {lv.get('yuksek', 0)} | {lv.get('orta', 0)} | {lv.get('dusuk', 0)} |")
    reasons = Counter(r["neden"] for r in records if r["doc_type"] == UNKNOWN)
    if reasons:
        lines += ["", "## bilinmiyor nedenleri", ""]
        lines += [f"- {k}: {v}" for k, v in reasons.most_common()]
        lines += ["", "| doc_id | neden | aday (puan) | başlık |", "|---|---|---|---|"]
        for r in records:
            if r["doc_type"] == UNKNOWN:
                lines.append(f"| {r['doc_id']} | {r['neden']} | {r.get('aday') or '-'} ({r['puan']}) "
                             f"| {(r['baslik'] or '').replace('|', '/')[:60]} |")
    return "\n".join(lines) + "\n"
