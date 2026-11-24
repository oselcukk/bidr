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
import json
import os
import stat
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from bidr.common import Workspace, read_jsonl, sha256_file, write_jsonl

from . import containers as C
from . import extract as ex
from . import kimlik as K
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
    # Maskeli kaynakta (bidr maskele --kaynak) özgün dosyanın sha256'sı: belge kimliği bundan türer, maskeli
    # kopyanın baytından (`sha256`) değil (bkz. `kimlik`). Maskeli kaynak değilse boş.
    "ozgun_sha256",
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
MODEL_METHODS = ("agent_vision", "agent_describe")   # transcribe.METHOD, describe.METHOD: metni model yazdı

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


def _read_prior_rows(ws: Workspace) -> list[dict]:
    if not ws.inventory.exists():
        return []
    with open(ws.inventory, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _read_prior(ws: Workspace) -> dict[str, dict]:
    return {r["doc_id"]: r for r in _read_prior_rows(ws) if r.get("doc_id") and not r.get("dup_of")}


AYNI = "_metin_ayni"         # _process: kimliği aynı, baytı değişen belgenin çıkarılan metni tabanla aynı
DEGISTI = "_metin_degisti"   # _process: metin gerçekten değişti (yeni metin yazıldı)


def _process(e: Entry, ws: Workspace, use_ocr: bool, taban: str | None = None) -> dict:
    """Tek dosyanın metnini çıkar ve yaz; satır alanlarını döndür. Hata fırlatmaz.

    `taban`: kimliği korunan ama (maskeli) baytı değişen belgenin önceki ingest metni. Yeni çıkarılan metin
    bununla birebir aynıysa hiçbir şey yazılmaz (`AYNI`: önceki satır alanları ve model metni geçerli kalır);
    farklıysa yeni metin yazılır ve `DEGISTI` işaretlenir (çağıran türetilmiş kayıtları geçersiz kılar)."""
    did = e.row["doc_id"]
    try:
        res = ex.extract(e.path, use_ocr=use_ocr)
    except ex.Unsupported:
        return {"status": UNSUPPORTED, "method": "", "pages": "", "chars": ""}
    except Exception as err:  # bir dosyanın hatası bütün işi durdurmaz
        msg = f"{type(err).__name__}: {err}".replace("\n", " ")[:300]
        return {"status": ERROR, "method": "", "pages": "", "chars": "", "error": msg}
    text = res.text
    if taban is not None and text == taban:
        return {AYNI: True}
    q = ex.assess(res)
    if taban is not None:
        _text_changed_archive(ws, did)
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
        **({DEGISTI: True} if taban is not None else {}),
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
    prior_rows = _read_prior_rows(ws)
    prior = {r["doc_id"]: r for r in prior_rows if r.get("doc_id") and not r.get("dup_of")}
    kim = K.Kimlik(ws.root, K.maske_eslemesi(source), prior_rows)
    if kim.esleme is not None:
        log(f"maskeli kaynak: belge kimliği özgün dosyadan ({kim.esleme.rapor_yolu.name})")
    entries: list[Entry] = []
    notes: dict[str, C.Note] = {}
    for e in _scan_files(source):
        entries.append(e)
        mem, ns = _expand(e, ws)
        entries.extend(mem)
        notes.update({n.rel: n for n in ns})
    log(f"tarandı: {len(entries)} dosya (arşiv/e-posta üyesi: {sum(1 for e in entries if e.member)})")

    first_by_sha: dict[str, Entry] = {}
    first_by_ozgun: dict[str, Entry] = {}
    dup_src: dict[int, Entry] = {}       # id(kopya satırı) → ilk örnek
    todo: list[Entry] = []
    taban: dict[int, str] = {}           # id(Entry) → önceki ingest metni (kimlik aynı, bayt değişti)
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
        ozgun = kim.ozgun(e.rel, sha)
        ilk = first_by_sha.get(sha) or (first_by_ozgun.get(ozgun) if ozgun else None)
        if ilk is not None:               # birebir kopya (aynı bayt ya da aynı özgün dosya)
            r.update(sha256=sha, ozgun_sha256=ozgun, doc_id=ilk.row["doc_id"], dup_of=ilk.rel)
            dup_src[id(r)] = ilk
            continue
        r.update(sha256=sha, ozgun_sha256=ozgun, doc_id=kim.doc_id(ozgun, sha, e.rel))
        first_by_sha[sha] = e
        if ozgun:
            first_by_ozgun[ozgun] = e
        did = r["doc_id"]
        if C.is_archive(e.rel.rsplit(C.SEP, 1)[-1]):
            n = notes.get(e.rel)
            r.update(status=n.status if n and n.status else ARCHIVE, method="arsiv",
                     error=(n.error if n else ""))
            continue
        old = prior.get(did)
        # Metni model yazmış belge (transcribe/describe; ingest'in kendi çıkarımı boş kalmış olabilir: status
        # `empty`/`needs_ocr`) --force olmadan yeniden çıkarılmaz: çıkarım model metnini ezer, apply metni yeniden
        # yazıp belgenin kararını `metin_degisti` yapar ve belge her koşuda yeniden karara gider.
        modelden = bool(old) and (old.get("method") or "") in MODEL_METHODS
        if (not force and ws.text_path(did).exists() and old
                and (old.get("status") in DONE_STATUSES or modelden)):
            if not old.get("sha256") or old["sha256"] == sha:
                for k in CARRY:
                    r[k] = old.get(k, "")
                continue
            # kimlik aynı (özgün dosya aynı), maskeli kopyanın baytı değişti: metin yeniden çıkarılır ve
            # öncekiyle karşılaştırılır; aynıysa hiçbir kayıt eskimez
            t = K.taban_metni(ws.root, did)
            if t is not None:
                taban[id(e)] = t
        todo.append(e)

    log(f"işlenecek: {len(todo)} (yinelenen: {sum(1 for e in entries if e.row['dup_of'])}, "
        f"atlanan/önceden: {len(first_by_sha) - len(todo)})")
    workers = workers or max(1, (os.cpu_count() or 2))
    done = ayni = 0
    degisen: set[str] = set()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_process, e, ws, use_ocr, taban.get(id(e))): e for e in todo}
        for fut in as_completed(futs):
            e = futs[fut]
            res = fut.result()
            if res.pop(AYNI, False):
                ayni += 1
                for k in CARRY:
                    e.row[k] = prior[e.row["doc_id"]].get(k, "")
            else:
                if res.pop(DEGISTI, False):
                    degisen.add(e.row["doc_id"])
                e.row.update(res)
            done += 1
            if done % 10 == 0 or done == len(todo):
                log(f"  {done}/{len(todo)}  ({time.time() - t0:.0f} sn)")

    if ayni:
        log(f"maskeli kopyası yeniden üretilen {ayni} belgenin metni aynı: kimlik ve kayıtlar korundu")
    # Göç: aynı yolda maskeli baytı değişmiş, özgünü önbellekten doğrulanamayan eski belge. Yeni çıkarılan
    # metin eskisiyle birebir aynıysa kimlik korunur; değilse belirsiz kalır (budama `_oksuz/`a alır).
    for e in entries:
        if e.row["doc_id"] in kim.belirsiz and not e.row["dup_of"]:
            yeni = e.row["doc_id"]
            eski = kim.metinle_dogrula(yeni)
            if eski:
                for x in entries:
                    if x.row["doc_id"] == yeni:
                        x.row["doc_id"] = eski
                for k in CARRY:
                    e.row[k] = prior[eski].get(k, "")
    if degisen:
        from bidr.transcribe.run import invalidate_downstream
        _archive_ids(ws, ws.root / REMOVED_DIR / CHANGED_DIR, degisen, MODEL_JSONL, text=False, work=())
        invalidate_downstream(ws, degisen, neden="ingest: maskeli kopyanın metni değişti")
        log(f"maskeli kopyasının METNİ değişen {len(degisen)} belge: yeni metin yazıldı, bu belgelerin "
            f"türetilmiş kayıtları geçersiz kılındı ({', '.join(sorted(degisen)[:5])}"
            + (" …" if len(degisen) > 5 else "") + ")")
    kim.kaydet()

    # E-posta ekleri okunamadıysa notu satıra
    for e in entries:
        n = notes.get(e.rel)
        if n and not n.status and n.error and not e.row["dup_of"]:
            e.row["error"] = "; ".join(x for x in (e.row["error"], n.error) if x)

    # Birebir kopyalar ilk örneğin sonucunu paylaşır.
    for e in entries:
        if e.row["dup_of"]:
            src = dup_src[id(e.row)].row
            for k in CARRY:
                e.row[k] = src[k]

    _page_structure(ws, entries, first_by_sha, dup_src)
    rows = [e.row for e in entries]
    tmp = ws.inventory.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(ws.inventory)
    _update_gaps(ws, rows)
    _prune_removed(ws, rows, log, belirsiz=kim.belirsiz)
    log(f"bitti: {len(rows)} satır, {time.time() - t0:.1f} sn -> {ws.inventory}")
    return rows


# Belgeye bağlı türetilmiş kayıtlar (doc_id anahtarlı; makine çıktısı). Kaynaktan çıkan belgenin bunları
# kalırsa sonraki aşamalar onu hâlâ setin parçası sayar: kararı, inceleme satırı, kanıt dizini ve rapor
# atfı düşmez. İnsan girdileri (etiketler, hakem cevapları, review-decisions.jsonl) dokunulmadan kalır;
# doc_id'si artık kararlarda olmadığı için kullanılmaz.
DERIVED_JSONL = ("documents.jsonl", "candidates.jsonl", "decisions.jsonl")
DERIVED_WORK = ("coarse", "fine")
# Model okuma kayıtları (transcribe/describe): belge kaynaktan çıkınca paketleri kalırsa `apply` onları
# "envanterde yok" diye geçersiz cevap sayar ve aşama insan kararında durur.
MODEL_JSONL = ("transcribe.jsonl", "describe.jsonl")
MODEL_WORK = ("transcribe", "describe")            # work/<aşama>/<doc_id>/
MODEL_TEXT = ("text_ocr", "text_pre_describe")     # <klasör>/<doc_id>.txt
REMOVED_DIR = "kaynaktan-cikarilan"
CHANGED_DIR = "metin-degisen"                      # kaynaktan-cikarilan/ altında: metni değişen belgenin eski hâli


def _move(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():                                # önceki olayın aynı adlı kaydı ezilmez
        dst = dst.with_name(f"{dst.name}.{time.strftime('%Y%m%dT%H%M%S')}")
    src.replace(dst)


def _archive_ids(ws: Workspace, arch: Path, ids: set[str], jsonl: tuple[str, ...], *, text: bool = True,
                 work: tuple[str, ...] = DERIVED_WORK, model: bool = True) -> None:
    """`ids` belgelerinin kayıtlarını `arch` altına TAŞIR (silmez): `jsonl` dosyalarındaki satırlar
    `arch/kayitlar.jsonl`'e eklenir; metin, iş paketleri ve (model) okuma klasörleri aynı göreli yola."""
    if not ids:
        return
    arch.mkdir(parents=True, exist_ok=True)
    when = time.strftime("%Y-%m-%dT%H:%M:%S")
    with open(arch / "kayitlar.jsonl", "a", encoding="utf-8") as f:
        for name in jsonl:
            p = ws.root / name
            if not p.exists():
                continue
            keep, drop = [], []
            for r in read_jsonl(p):
                (drop if r.get("doc_id") in ids else keep).append(r)
            for r in drop:
                f.write(json.dumps({"zaman": when, "dosya": name, "kayit": r}, ensure_ascii=False) + "\n")
            if drop:
                write_jsonl(p, keep)
    for did in sorted(ids):
        if text and ws.text_path(did).exists():
            _move(ws.text_path(did), arch / "text" / f"{did}.txt")
        for stage in work:
            d = ws.root / "work" / stage
            for p in (d / f"{did}.json", d / f"{did}.out.json"):
                if p.exists():
                    _move(p, arch / "work" / stage / p.name)
        if model:
            for sub in MODEL_TEXT:
                p = ws.root / sub / f"{did}.txt"
                if p.exists():
                    _move(p, arch / sub / p.name)
            for stage in MODEL_WORK:
                p = ws.root / "work" / stage / did
                if p.is_dir():
                    _move(p, arch / "work" / stage / did)


def _text_changed_archive(ws: Workspace, did: str) -> None:
    """Metni değişen belgenin eski metni (yeni metin yazılmadan önce; işçi iş parçacığında, yalnız dosya)."""
    src = ws.text_path(did)
    if src.exists():
        dst = ws.root / REMOVED_DIR / CHANGED_DIR / "text" / src.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            dst = dst.with_name(f"{dst.name}.{time.strftime('%Y%m%dT%H%M%S')}")
        dst.write_bytes(src.read_bytes())


def _prune_removed(ws: Workspace, rows: list[dict], log: Callable[[str], None],
                   belirsiz: dict[str, dict] | None = None) -> list[str]:
    """Kaynakta artık olmayan (envanterde doc_id'si kalmayan) belgelerin türetilmiş kayıtlarını
    kaldırır: `text/<doc_id>.txt`, documents/candidates/decisions.jsonl satırları, decide iş
    paketleri (`work/coarse|fine/<doc_id>.json` ve cevapları), model okuma kayıtları (transcribe/describe
    satırları, paket klasörleri, `text_ocr/`, `text_pre_describe/`). Silinmez: `kaynaktan-cikarilan/`
    altına taşınır (kayıtlar `kayitlar.jsonl`'e eklenir). decisions.jsonl değiştiği için audit,
    file ve write kendi parmak izleriyle eskir ve yeniden koşar (review.xlsx satırı, kanıt
    dizini, ölçüt metni). Bir dosya okunamadıysa ya da iCloud'da duruyorsa (doc_id'si bilinemiyor)
    hiçbir şey kaldırılmaz.

    `belirsiz` (`kimlik.Kimlik.belirsiz`: yeni doc_id → {eski, rel_path, ozgun}): eski kimliği aynı yoldaki
    dosyayla doğrulanamayan belgeler. Kaynaktan çıktıkları kesin değildir (maskeli kopya yeniden üretilmiş
    olabilir): kayıtları `_oksuz/` altına alınır, `_oksuz/bekleyen.jsonl`'e yazılır ve `bidr next`
    `bidr kimlik-onar`a yönlendirir. Döner: kaldırılan doc_id'ler (belirsizler dahil)."""
    if any(not r.get("doc_id") and r.get("status") in (NOT_DOWNLOADED, ERROR) for r in rows):
        return []
    known = {r["doc_id"] for r in rows if r.get("doc_id")}
    have: set[str] = {p.stem for p in ws.text_dir.glob("*.txt")} if ws.text_dir.exists() else set()
    for name in DERIVED_JSONL:
        p = ws.root / name
        if p.exists():
            have |= {r["doc_id"] for r in read_jsonl(p) if r.get("doc_id")}
    gone = sorted(have - known)
    if not gone:
        return []
    supheli = {b["eski"]: dict(b, yeni=y) for y, b in (belirsiz or {}).items() if b["eski"] in gone}
    kesin = set(gone) - set(supheli)
    _archive_ids(ws, ws.root / REMOVED_DIR, kesin, DERIVED_JSONL + MODEL_JSONL)
    if kesin:
        g = sorted(kesin)
        log(f"kaynaktan çıkan {len(g)} belgenin türetilmiş kayıtları kaldırıldı ({REMOVED_DIR}/): "
            + ", ".join(g[:5]) + (" …" if len(g) > 5 else ""))
    if supheli:
        _archive_ids(ws, ws.root / K.OKSUZ_DIR, set(supheli), DERIVED_JSONL + MODEL_JSONL)
        when = time.strftime("%Y-%m-%dT%H:%M:%S")
        K.bekleyen_yaz(ws.root, K.bekleyenler(ws.root) + [
            {"doc_id": d, "rel_path": b["rel_path"], "yeni_doc_id": b["yeni"], "ozgun_sha256": b["ozgun"],
             "neden": "aynı yolda maskeli kopya değişmiş; özgün dosya önbellekten ve metinden doğrulanamadı",
             "zaman": when} for d, b in sorted(supheli.items())])
        log(f"KİMLİĞİ BELİRSİZ {len(supheli)} belge: kayıtları silinmedi, {K.OKSUZ_DIR}/ altına alındı "
            f"(`bidr kimlik-onar -w {ws.root}`): " + ", ".join(sorted(supheli)[:5])
            + (" …" if len(supheli) > 5 else ""))
    return gone


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


def _page_structure(ws: Workspace, entries: list[Entry], first_by_sha: dict[str, Entry],
                    dup_src: dict[int, Entry] | None = None) -> None:
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
            src = (dup_src[id(e.row)] if dup_src else first_by_sha[e.row["sha256"]]).row
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
