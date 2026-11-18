"""ingest aşaması: kaynak klasörü salt okunur tara, envanter ve metin üret.

Kaynakta hiçbir şey yazılmaz/taşınmaz. Çıktılar yalnız çalışma klasörüne:
`inventory.csv` ve `text/<doc_id>.txt`.
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

from . import extract as ex

FIELDS = [
    "doc_id", "sha256", "rel_path", "ext", "size", "pages", "chars",
    "method", "status", "dup_of", "error",
]

# Durumlar
OK = "ok"                    # metin katmanından/biçimden çıkarıldı
OCR = "ocr"                  # en az bir sayfa OCR'la okundu
EMPTY = "empty"              # çıkarıldı ama metin yok
NEEDS_OCR = "needs_ocr"      # OCR gerekiyordu, kapalıydı/yoktu (metin eksik olabilir)
UNSUPPORTED = "unsupported"  # bu tür için çıkarıcı yok
ERROR = "error"              # çıkarma hata verdi
NOT_DOWNLOADED = "not_downloaded"  # iCloud yer tutucusu; içerik yerelde yok

DONE_STATUSES = {OK, OCR}  # yeniden çalıştırmada atlananlar

SKIP_NAMES = {".ds_store", "thumbs.db", "desktop.ini", "icon\r", ".localized"}
SKIP_DIRS = {"__macosx", ".git", ".trash", ".trashes", ".spotlight-v100", ".fseventsd"}

SF_DATALESS = 0x40000000  # macOS: iCloud'da duran, yerelde içeriği olmayan dosya


@dataclass
class Entry:
    path: Path
    rel: str
    ext: str
    size: int
    placeholder: bool = False
    row: dict = field(default_factory=dict)


def _is_dataless(st: os.stat_result) -> bool:
    return bool(getattr(st, "st_flags", 0) & SF_DATALESS)


def scan(source: Path) -> list[Entry]:
    """Özyinelemeli tarama; gizli/sistem dosyaları atlanır, iCloud yer tutucuları işaretlenir."""
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
    tmp = ws.text_path(did).with_suffix(".txt.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(ws.text_path(did))
    if not any(ch.isalnum() for ch in text):
        status = NEEDS_OCR if res.ocr_missing else EMPTY
    elif res.ocr_missing:
        status = NEEDS_OCR
    elif res.ocr_pages:
        status = OCR
    else:
        status = OK
    return {
        "status": status, "method": res.method,
        "pages": "" if res.page_count is None else res.page_count,
        "chars": len(text), "error": "",
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
    entries = scan(source)
    log(f"tarandı: {len(entries)} dosya")

    first_by_sha: dict[str, Entry] = {}
    todo: list[Entry] = []
    for e in entries:
        r = e.row
        r.update({k: "" for k in FIELDS})
        r.update(rel_path=e.rel, ext=e.ext, size=e.size)
        if e.placeholder:
            r["status"] = NOT_DOWNLOADED
            continue
        try:
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
        old = prior.get(did)
        if (not force and ws.text_path(did).exists() and old
                and old.get("status") in DONE_STATUSES):
            for k in ("pages", "chars", "method", "status"):
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

    # Birebir kopyalar ilk örneğin sonucunu paylaşır.
    for e in entries:
        if e.row["dup_of"]:
            src = first_by_sha[e.row["sha256"]].row
            for k in ("pages", "chars", "method", "status"):
                e.row[k] = src[k]

    rows = [e.row for e in entries]
    tmp = ws.inventory.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(ws.inventory)
    log(f"bitti: {len(rows)} satır, {time.time() - t0:.1f} sn -> {ws.inventory}")
    return rows
