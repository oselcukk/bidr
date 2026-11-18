"""ingest aşaması: kaynak klasörü salt okunur tara, envanter ve metin üret.

Kaynakta hiçbir şey yazılmaz/taşınmaz. Çıktılar yalnız çalışma klasörüne:
`inventory.csv`, `text/<doc_id>.txt`, arşiv/e-posta üyelerinin açılmış kopyaları
(`arsiv/<doc_id><ext>`) ve gaps.md'nin ingest bölümü.

Arşiv ve e-posta üyeleri ayrı satırdır (`rel_path` = `kapsayıcı!/üye`, bkz. `containers`);
kapsayıcı satırı `kapsayici` sütununda. Sayfa yapısından parça grubu ve birden çok belge
şüphesi (`parts`) her çalıştırmada metinden yeniden hesaplanır.
"""
from __future__ import annotations

import csv
import os
import stat
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from bidr.common import Workspace, doc_id_from_sha, sha256_file

from . import containers as C
from . import extract as ex
from . import parts as P

FIELDS = [
    "doc_id", "sha256", "rel_path", "ext", "size", "pages", "chars",
    "method", "status", "dup_of", "error",
    # OCR kalitesi (yalnız OCR'lanan belgelerde dolu): tesseract güveni 0-100,
    # güven x metin sağlığı 0-1, düşük kalite işareti (1: görsel modele gönderilecek),
    # gömülü görseller (metne eklenen / düşük kaliteden eklenmeyen).
    "ocr_conf", "quality", "low_quality", "images_ocr", "images_lowq",
    # Arşiv/e-posta üyesinin bir üst kapsayıcısı (rel_path); parça grubu (tek belgenin
    # bölünmüş parçaları: grup kimliği, sıra, gerekçe); birden çok belge şüphesi (yeni belgenin
    # başladığı sayfalar, ";" ile; bölme yapılmaz).
    "kapsayici", "parca_grubu", "parca_sira", "parca_gerekce", "coklu_belge_suphesi",
]
# Önceki çalıştırmadan / ilk kopyadan taşınan alanlar
CARRY = ("pages", "chars", "method", "status", "ocr_conf", "quality", "low_quality",
         "images_ocr", "images_lowq")

# Durumlar
OK = "ok"                    # metin katmanından/biçimden çıkarıldı
OCR = "ocr"                  # en az bir sayfa OCR'la okundu
EMPTY = "empty"              # çıkarıldı ama metin yok
NEEDS_OCR = "needs_ocr"      # OCR gerekiyordu, kapalıydı/yoktu (metin eksik olabilir)
UNSUPPORTED = "unsupported"  # bu tür için çıkarıcı yok
ERROR = "error"              # çıkarma hata verdi
NOT_DOWNLOADED = "not_downloaded"  # iCloud yer tutucusu; içerik yerelde yok
ARCHIVE = C.ARCHIVE          # arşivin kendisi: metni yok, üyeleri ayrı satırlarda

DONE_STATUSES = {OK, OCR}  # yeniden çalıştırmada atlananlar

SKIP_NAMES = C.SKIP_NAMES
SKIP_DIRS = C.SKIP_DIRS

GAPS = "gaps.md"
GAPS_BEGIN = "<!-- bidr:ingest -->"
GAPS_END = "<!-- /bidr:ingest -->"

SF_DATALESS = 0x40000000  # macOS: iCloud'da duran, yerelde içeriği olmayan dosya


@dataclass
class Entry:
    path: Path
    rel: str
    ext: str
    size: int
    placeholder: bool = False
    row: dict = field(default_factory=dict)
    parent: str = ""             # arşiv/e-posta üyesi: bir üst kapsayıcı
    member: C.Member | None = None


def _expand(e: Entry, ws: Workspace | None = None) -> tuple[list[Entry], list[C.Note]]:
    """Kapsayıcı dosyanın üyeleri (iç içe dahil) Entry olarak. `ws` verilirse üyeler okunup
    çalışma klasörüne açılır (`arsiv/<doc_id><ext>`); verilmezse yalnız listelenir."""
    if e.placeholder or not C.kind_of(e.rel):
        return [], []
    sink = (lambda m, data: C.write_cache(ws.root, m, data)) if ws is not None else None
    members, notes = C.walk(e.path, e.rel, want_data=ws is not None, sink=sink)
    return [Entry(Path(), m.rel, m.ext, m.size, parent=m.parent, member=m) for m in members], notes


def _is_dataless(st: os.stat_result) -> bool:
    return bool(getattr(st, "st_flags", 0) & SF_DATALESS)


def _scan_files(source: Path) -> list[Entry]:
    source = Path(source).expanduser().resolve()
    entries: list[Entry] = []
    for dirpath, dirnames, filenames in os.walk(source, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames
                             if not d.startswith(".") and d.lower() not in SKIP_DIRS)
        for name in sorted(filenames):
            p = Path(dirpath) / name
            low = name.lower()
            # Eski tarz iCloud yer tutucusu: ".Belge.pdf.icloud"
            if name.startswith(".") and low.endswith(".icloud") and len(name) > 8:
                real = name[1:-len(".icloud")]
                rel = str((p.parent / real).relative_to(source))
                entries.append(Entry(p, rel, Path(real).suffix.lower(), 0, placeholder=True))
                continue
            if name.startswith(".") or name.startswith("~$") or low in SKIP_NAMES:
                continue
            try:
                st = p.lstat()
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode):
                continue
            rel = str(p.relative_to(source))
            entries.append(Entry(p, rel, p.suffix.lower(), st.st_size, placeholder=_is_dataless(st)))
    return entries


def scan(source: Path) -> list[Entry]:
    """Özyinelemeli tarama; gizli/sistem dosyaları atlanır, iCloud yer tutucuları işaretlenir.
    Arşiv ve e-posta üyeleri kapsayıcının hemen ardından ayrı Entry olarak gelir (yalnız liste;
    baytlar okunmaz, iç içe kapsayıcılar hariç)."""
    out: list[Entry] = []
    for e in _scan_files(source):
        out.append(e)
        out.extend(_expand(e)[0])
    return out


def _read_prior(ws: Workspace) -> dict[str, dict]:
    if not ws.inventory.exists():
        return {}
    with open(ws.inventory, newline="", encoding="utf-8") as f:
        return {r["doc_id"]: r for r in csv.DictReader(f) if r.get("doc_id") and not r.get("dup_of")}


def _process(e: Entry, ws: Workspace, use_ocr: bool) -> dict:
    """Tek dosyanın metnini çıkar ve yaz; satır alanlarını döndür. Hata fırlatmaz."""
    did = e.row["doc_id"]
    try:
        res = ex.extract(e.path, use_ocr=use_ocr)
    except ex.Unsupported:
        return {"status": UNSUPPORTED, "method": "", "pages": "", "chars": ""}
    except Exception as err:  # bir dosyanın hatası bütün işi durdurmaz
        msg = f"{type(err).__name__}: {err}".replace("\n", " ")[:300]
        return {"status": ERROR, "method": "", "pages": "", "chars": "", "error": msg}
    text = res.text
    q = ex.assess(res)
    tmp = ws.text_path(did).with_suffix(".txt.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(ws.text_path(did))
    if not any(ch.isalnum() for ch in text):
        status = NEEDS_OCR if res.ocr_missing else EMPTY
    elif res.ocr_missing:
        status = NEEDS_OCR
    elif res.ocr_pages or res.images_ocr:
        status = OCR
    else:
        status = OK
    return {
        "status": status, "method": res.method,
        "pages": "" if res.page_count is None else res.page_count,
        "chars": len(text), "error": "",
        "ocr_conf": q["ocr_conf"], "quality": q["quality"],
        "low_quality": 1 if q["low_quality"] else "",
        "images_ocr": res.images_ocr or "", "images_lowq": res.images_lowq or "",
    }


def run(source: Path, workspace: Path, *, force: bool = False, use_ocr: bool = True,
        workers: int | None = None, log: Callable[[str], None] | None = None) -> list[dict]:
    log = log or (lambda m: print(m, file=sys.stderr))
    source = Path(source).expanduser().resolve()
    if not source.is_dir():
        raise NotADirectoryError(str(source))
    ws = Workspace(workspace)
    if ws.root == source or source in ws.root.parents:
        raise ValueError("çalışma klasörü kaynak klasörün içinde olamaz (kaynak salt okunur)")
    ws.ensure()
    t0 = time.time()
    prior = _read_prior(ws)
    entries: list[Entry] = []
    notes: dict[str, C.Note] = {}
    for e in _scan_files(source):
        entries.append(e)
        mem, ns = _expand(e, ws)
        entries.extend(mem)
        notes.update({n.rel: n for n in ns})
    log(f"tarandı: {len(entries)} dosya (arşiv/e-posta üyesi: {sum(1 for e in entries if e.member)})")

    first_by_sha: dict[str, Entry] = {}
    todo: list[Entry] = []
    for e in entries:
        r = e.row
        r.update({k: "" for k in FIELDS})
        r.update(rel_path=e.rel, ext=e.ext, size=e.size, kapsayici=e.parent)
        if e.placeholder:
            r["status"] = NOT_DOWNLOADED
            continue
        m = e.member
        if m is not None and m.status:
            r.update(status=m.status, error=m.error)
            continue
        try:
            if m is not None:
                sha = _materialize(ws, e)
            else:
                sha = sha256_file(e.path)
        except OSError as err:
            r.update(status=ERROR, error=f"okunamadı: {err}"[:300])
            continue
        r.update(sha256=sha, doc_id=doc_id_from_sha(sha))
        if sha in first_by_sha:
            r["dup_of"] = first_by_sha[sha].rel
            continue
        first_by_sha[sha] = e
        did = r["doc_id"]
        if C.is_archive(e.rel.rsplit(C.SEP, 1)[-1]):
            n = notes.get(e.rel)
            r.update(status=n.status if n and n.status else ARCHIVE, method="arsiv",
                     error=(n.error if n else ""))
            continue
        old = prior.get(did)
        if (not force and ws.text_path(did).exists() and old
                and old.get("status") in DONE_STATUSES):
            for k in CARRY:
                r[k] = old.get(k, "")
            continue
        todo.append(e)

    log(f"işlenecek: {len(todo)} (yinelenen: {sum(1 for e in entries if e.row['dup_of'])}, "
        f"atlanan/önceden: {len(first_by_sha) - len(todo)})")
    workers = workers or max(1, (os.cpu_count() or 2))
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_process, e, ws, use_ocr): e for e in todo}
        for fut in as_completed(futs):
            e = futs[fut]
            e.row.update(fut.result())
            done += 1
            if done % 10 == 0 or done == len(todo):
                log(f"  {done}/{len(todo)}  ({time.time() - t0:.0f} sn)")

    # E-posta ekleri okunamadıysa notu satıra
    for e in entries:
        n = notes.get(e.rel)
        if n and not n.status and n.error and not e.row["dup_of"]:
            e.row["error"] = "; ".join(x for x in (e.row["error"], n.error) if x)

    # Birebir kopyalar ilk örneğin sonucunu paylaşır.
    for e in entries:
        if e.row["dup_of"]:
            src = first_by_sha[e.row["sha256"]].row
            for k in CARRY:
                e.row[k] = src[k]

    _page_structure(ws, entries, first_by_sha)
    rows = [e.row for e in entries]
    tmp = ws.inventory.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(ws.inventory)
    _update_gaps(ws, rows)
    log(f"bitti: {len(rows)} satır, {time.time() - t0:.1f} sn -> {ws.inventory}")
    return rows


def _materialize(ws: Workspace, e: Entry) -> str:
    """Üyenin çalışma klasöründeki açılmış kopyası (`arsiv/<doc_id><ext>`; tarama sırasında
    yazıldı); sha256 döndür. Çıkarıcılar ve sonraki aşamalar bu kopyayı normal dosya gibi okur."""
    m = e.member
    if m.path is None or not m.sha:
        raise OSError("üye açılamadı")
    e.path = m.path
    e.size = m.path.stat().st_size
    e.row["size"] = e.size
    return m.sha


def _page_structure(ws: Workspace, entries: list[Entry], first_by_sha: dict[str, Entry]) -> None:
    """Parça grubu ve birden çok belge şüphesi (metinden; her çalıştırmada yeniden)."""
    pages: dict[str, list[str]] = {}
    for e in first_by_sha.values():
        r = e.row
        if r["status"] not in DONE_STATUSES or not r["method"].startswith(P.PAGED_METHODS):
            continue
        tp = ws.text_path(r["doc_id"])
        if not tp.exists():
            continue
        ps = tp.read_text(encoding="utf-8", errors="replace").split("\f")
        pages[r["doc_id"]] = ps
        starts = P.multi_doc_starts(ps)
        r["coklu_belge_suphesi"] = ";".join(str(k) for k, _ in starts)
    groups = P.part_groups(pages)
    for e in entries:
        g = groups.get(e.row["doc_id"])
        if g:
            e.row.update(parca_grubu=g["grup"], parca_sira=g["sira"], parca_gerekce=g["gerekce"])
        if e.row["dup_of"]:
            src = first_by_sha[e.row["sha256"]].row
            e.row["coklu_belge_suphesi"] = src["coklu_belge_suphesi"]


def gaps_block(rows: list[dict]) -> str:
    """gaps.md ingest bölümü: birden çok belge şüphesi, parça grupları, arşiv istisnaları."""
    L = [GAPS_BEGIN, "## Tarama (ingest) notları", ""]
    multi = [r for r in rows if r.get("coklu_belge_suphesi") and not r.get("dup_of")]
    L += ["### Birden çok belge içerebilecek dosyalar (bölünmedi)", ""]
    if multi:
        L.append("Belgenin tamamı tek karar alır; aşağıdaki sayfalarda yeni bir belge başlıyor "
                 "olabilir. Gerekirse kaynakta ayrı dosyalara bölünüp yeniden taranmalı.")
        L.append("")
        L += [f"- `{r['rel_path']}` ({r['doc_id']}): yeni belge başlangıcı s. "
              f"{r['coklu_belge_suphesi'].replace(';', ', ')}" for r in multi]
    else:
        L.append("- yok")
    groups: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("parca_grubu") and not r.get("dup_of"):
            groups.setdefault(r["parca_grubu"], []).append(r)
    L += ["", "### Parça grupları (tek belgenin bölünmüş parçaları; tek kanıt sayılır)", ""]
    if groups:
        for g, mem in sorted(groups.items()):
            mem.sort(key=lambda r: int(r["parca_sira"] or 0))
            L.append(f"- {g} ({mem[0]['parca_gerekce']}): " + " + ".join(f"`{r['rel_path']}`" for r in mem))
    else:
        L.append("- yok")
    bad = [r for r in rows if (r.get("kapsayici") or C.kind_of(r["rel_path"].rsplit(C.SEP, 1)[-1]))
           and r.get("error") and not r.get("dup_of")]
    L += ["", "### Arşiv ve e-posta istisnaları", ""]
    L += [f"- `{r['rel_path']}`: {r['status']} — {r['error']}" for r in bad] or ["- yok"]
    L.append(GAPS_END)
    return "\n".join(L) + "\n"


def _update_gaps(ws: Workspace, rows: list[dict]) -> None:
    """gaps.md'deki ingest bölümünü değiştir (yoksa sona ekle); diğer bölümlere dokunmaz."""
    path = ws.root / GAPS
    block = gaps_block(rows)
    cur = path.read_text(encoding="utf-8") if path.exists() else ""
    a, b = cur.find(GAPS_BEGIN), cur.find(GAPS_END)
    if a != -1 and b > a:
        end = b + len(GAPS_END)
        if cur[end:end + 1] == "\n":
            end += 1
        new = cur[:a] + block + cur[end:]
    else:
        new = (cur.rstrip() + "\n\n" if cur.strip() else "") + block
    if new != cur:
        path.write_text(new, encoding="utf-8")
