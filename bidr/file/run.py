"""Kanıt dosyalama: onaylı eşleşmeler → `evidence/<A>/<A.1>/<A.1.2>/[A.1.2-1-OD3] Ad.pdf` +
`evidence-index.csv` (sözleşme: docs/REPORT_LAYER.md).

Girdi (salt okunur): `decisions.jsonl`, `documents.jsonl`, `inventory.csv`, `text/`
(çalışma alanı); varsa `review-decisions.jsonl` (`review` klasörü, vars. çalışma alanı);
kaynak klasör. Eşleşme kümesi ve sayılan aşama/OD `bidr.audit.run.build` ile aynı kurallarla
hesaplanır (ret düşer, duzelt düzeltilmiş ölçüt/yuva/aşamayla girer).

Kaynak dosyalara yalnız okumak için dokunulur; çıktı klasörü kaynağın içinde olamaz.
"""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from bidr.common import Workspace, read_jsonl

from .naming import date_of, file_name, safe_name

SURUM = 1
INDEX = "evidence-index.csv"
EVIDENCE = "evidence"
ZIP = "evidence.zip"
MANIFEST = ".bidr-evidence.json"
NO_REVIEW = "INCELEME_YAPILMADI.txt"
REVIEW = "review-decisions.jsonl"
COLUMNS = ["kanit_no", "olcut", "od", "ad", "dosya", "doc_id", "sayfalar", "yuvalar", "alintilar",
           # sözleşme sütunlarından sonra ek bilgi
           "inceleme", "kopyalar", "kaynak", "isaretler", "ad_kaynagi"]
PDF = ".pdf"


class FileError(RuntimeError):
    pass


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p.exists() else ""


def _inside(a: Path, b: Path) -> bool:
    return a == b or b in a.parents


def source_root(ws: Path, source: str | Path | None) -> Path:
    from bidr.init.config import load_section
    sec = load_section(ws) or {}
    cfg = sec.get("kaynak")
    if source:
        src = Path(source).expanduser().resolve()
        if cfg and Path(cfg).expanduser().resolve() != src:
            raise FileError(f"--source ({src}) config.yaml kaynağından ({cfg}) farklı")
        return src
    if cfg:
        return Path(cfg).expanduser().resolve()
    raise FileError("kaynak klasör bilinmiyor: config.yaml'da `bidr: kaynak` yok; --source verin")


def _inventory(ws: Workspace) -> dict[str, dict]:
    """doc_id → asıl satır (yinelenen kopya satırları `dup_of` dolu; asıl tercih edilir)."""
    out: dict[str, dict] = {}
    with open(ws.inventory, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            d = r.get("doc_id")
            if not d:
                continue
            cur = out.get(d)
            if cur is None or (cur.get("dup_of") and not r.get("dup_of")):
                out[d] = r
    return out


def _type_labels() -> dict[str, str]:
    try:
        from bidr.identify.catalog import load_catalog
        cat = load_catalog()
        return {t.name: t.label for t in cat.types}
    except (OSError, ValueError, KeyError):   # katalog okunamazsa ad başlıktan gelir, yoksa "Belge"
        return {}


# -- sayfa seçimi ----------------------------------------------------------------------------

def pages_of_spans(text: str, spans: list[list[int] | tuple[int, int] | None]) -> list[int] | None:
    """Alıntı konumlarının düştüğü sayfalar (1 tabanlı, `\\f` sınırlarından). Konum yoksa None."""
    pages: set[int] = set()
    for sp in spans:
        if not sp:
            return None            # konumu bilinmeyen alıntı: sayfa kesilemez
        s, e = int(sp[0]), int(sp[1])
        a = text.count("\f", 0, max(s, 0)) + 1
        b = text.count("\f", 0, max(e - 1, s, 0)) + 1
        pages.update(range(a, b + 1))
    return sorted(pages) or None


def page_ranges(pages: list[int]) -> str:
    out, i = [], 0
    while i < len(pages):
        j = i
        while j + 1 < len(pages) and pages[j + 1] == pages[j] + 1:
            j += 1
        out.append(str(pages[i]) if i == j else f"{pages[i]}-{pages[j]}")
        i = j + 1
    return ",".join(out)


def _quiet_pypdf() -> None:
    import logging
    logging.getLogger("pypdf").setLevel(logging.ERROR)   # bozuk xref uyarıları gürültü


def cut_pdf(src: Path, dst: Path, pages: list[int]) -> None:
    from pypdf import PdfReader, PdfWriter
    _quiet_pypdf()
    r = PdfReader(str(src))
    if r.is_encrypted:
        r.decrypt("")
    w = PdfWriter()
    for p in pages:
        w.add_page(r.pages[p - 1])
    with open(dst, "wb") as f:
        w.write(f)


def pdf_pages(src: Path) -> int | None:
    try:
        from pypdf import PdfReader
        _quiet_pypdf()
        r = PdfReader(str(src))
        if r.is_encrypted and not r.decrypt(""):
            return None
        return len(r.pages)
    except Exception:
        return None


# -- plan --------------------------------------------------------------------------------------

@dataclass
class Item:
    olcut: str
    doc_id: str                       # dosyalanan belge (grubun temsilcisi)
    od: int
    yuvalar: list[str]
    alintilar: list[str]
    spans: list
    sayilir: bool
    inceleme: str
    kopyalar: list[str] = field(default_factory=list)
    isaretler: list[str] = field(default_factory=list)


def _names_sha(ws_root: Path, review_dir: Path) -> str:
    """Kanıt adı kaynaklarının (`kanit-adlari.jsonl`, çalışma alanı + inceleme klasörü) özeti."""
    from bidr.name.resolve import NAMES
    ps = dict.fromkeys([(Path(ws_root) / NAMES).resolve(), (Path(review_dir) / NAMES).resolve()])
    return hashlib.sha256("".join(_sha(p) for p in ps).encode()).hexdigest()[:16]


def _weak(row: dict) -> bool:
    """Düşük güvenli ve inceleme kararıyla (kabul/duzelt) onaylanmamış eşleşme."""
    return bool(row.get("zayif")) and row.get("karar") not in ("kabul", "duzelt")


def _canonical(recs: dict[str, dict]) -> dict[str, str]:
    """Mükerrer bağı: devralan belge → temsilci (decide `mukerrer`)."""
    can = {}
    for did, r in recs.items():
        mk = r.get("mukerrer") or {}
        if mk.get("durum") == "devralindi" and mk.get("temsilci"):
            can[did] = mk["temsilci"]
    return can


def plan(ws_root: Path, *, review_dir: Path | None = None, profile: str | None = None
         ) -> tuple[list[Item], dict]:
    from bidr.audit.run import build
    ws = Workspace(ws_root)
    review_dir = Path(review_dir).expanduser().resolve() if review_dir else ws.root
    rpath = review_dir / REVIEW
    reviewed = rpath.exists()
    review = {r["satir"]: r for r in read_jsonl(rpath)} if reviewed else {}
    a = build(ws.root, out=review_dir, profile=profile, review=review)
    recs = {r["doc_id"]: r for r in read_jsonl(ws.root / "decisions.jsonl")}
    spans = {}
    for did, r in recs.items():
        for m in r.get("eslesmeler") or []:
            if m.get("kabul"):
                spans[(did, m["yuva"])] = (m.get("denetim") or {}).get("alinti_konum")
    can = _canonical(recs)
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in a.rows:
        if "insan_reddetti" in row["flags"]:
            continue
        key = (row["olcut"], can.get(row["doc_id"], row["doc_id"]))
        groups.setdefault(key, []).append(row)
    items: list[Item] = []
    for (olcut, root), rows in groups.items():
        ids = sorted({r["doc_id"] for r in rows})
        rep = root if root in ids else ids[0]
        counted = [r for r in rows if r["sayilir"] and r["od"] and not _weak(r)]
        weak = [r for r in rows if r["sayilir"] and r["od"] and _weak(r)]
        ods = [r["od"] for r in counted] or [r["od"] or r.get("od_kabul") for r in rows]
        ods = [x for x in ods if x]
        if not ods:
            continue
        own = [r for r in rows if r["doc_id"] == rep]
        flags = sorted({f for r in rows for f in r["flags"]})
        if weak:            # audit'le aynı: düşük güven önerilen OD'ye katılmaz; işaret kalır
            flags.append("dusuk_guven_od_disi")
        if not counted:
            flags.append("od_sayilmadi")
        if reviewed:
            ks = {r["karar"] or "karar_yok" for r in rows}
            inc = ",".join(sorted(ks))
        else:
            inc = "yapilmadi"
        items.append(Item(
            olcut=olcut, doc_id=rep, od=max(ods),
            yuvalar=sorted({r["yuva"] for r in rows}, key=lambda y: (y.split("/")[0], int(y.split("/")[1]))),
            alintilar=list(dict.fromkeys(r["alinti"] for r in own if r["alinti"])),
            spans=[spans.get((rep, r["yuva_model"])) for r in own],
            sayilir=bool(counted), inceleme=inc, kopyalar=[x for x in ids if x != rep],
            isaretler=flags))
    meta = {"inceleme": reviewed, "review": str(rpath) if reviewed else None,
            "kararlar_sha": _sha(ws.root / "decisions.jsonl"), "inceleme_sha": _sha(rpath),
            "profil": a.profile}
    return items, meta


def _criterion_dir(olcut: str) -> Path:
    parts = olcut.split(".")
    return Path(*[".".join(parts[:i]) for i in range(1, len(parts) + 1)])


# -- yürütme -----------------------------------------------------------------------------------

def run(ws_root: Path, *, out: Path | None = None, source: str | Path | None = None,
        review_dir: Path | None = None, whole: bool = False, make_zip: bool = False,
        profile: str | None = None) -> dict:
    ws = Workspace(ws_root)
    if not (ws.root / "decisions.jsonl").exists():
        raise FileNotFoundError(f"decisions.jsonl yok: {ws.root}")
    src_root = source_root(ws.root, source)
    if not src_root.is_dir():
        raise FileError(f"kaynak klasör yok: {src_root}")
    out = Path(out).expanduser().resolve() if out else ws.root
    if _inside(out, src_root) or _inside(src_root, out):
        raise FileError(f"çıktı klasörü kaynakla iç içe olamaz: {out} / {src_root}")
    ev = out / EVIDENCE
    if ev.exists() and any(ev.iterdir()) and not (ev / MANIFEST).exists():
        raise FileError(f"{ev} bidr'in üretmediği dosyalar içeriyor; taşıyın ya da başka --out verin")

    items, meta = plan(ws.root, review_dir=review_dir, profile=profile)
    inv = _inventory(ws)
    docs = {r["doc_id"]: r for r in read_jsonl(ws.documents)} if ws.documents.exists() else {}
    from bidr.name.resolve import Resolver
    rdir = Path(review_dir).expanduser().resolve() if review_dir else ws.root
    resolver = Resolver.load(ws.root, rdir, docs=docs, labels=_type_labels())
    meta["adlar_sha"] = _names_sha(ws.root, rdir)
    uyarilar: list[str] = []
    if not meta["inceleme"]:
        uyarilar.append("review-decisions.jsonl yok: inceleme yapılmadı; decisions'taki kabul edilmiş "
                        "eşleşmeler dosyalandı, çıktı 'inceleme yapılmadı' diye işaretli")

    # numaralama: ölçüt içinde OD (artan), sonra çalışma adı, sonra doc_id → kararlı
    by_c: dict[str, list[Item]] = {}
    for it in items:
        by_c.setdefault(it.olcut, []).append(it)
    from bidr.criteria.model import id_key

    if ev.exists():
        shutil.rmtree(ev)
    ev.mkdir(parents=True)
    rows, n_cut, n_missing = [], 0, 0
    names: dict[str, tuple[str, str]] = {}
    for olcut in sorted(by_c, key=id_key):
        lst = sorted(by_c[olcut], key=lambda i: (i.od, (docs.get(i.doc_id) or {}).get("calisma_adi") or "",
                                                 i.doc_id))
        ads = {}
        for it in lst:
            if it.doc_id not in names:       # öncelik: insan > model > kural (bidr/name/resolve.py)
                ad, src, uy = resolver.resolve(it.doc_id, it.kopyalar)
                names[it.doc_id] = (ad, src)
                uyarilar.extend(uy)
            ads[it.doc_id] = names[it.doc_id][0]
        seen: dict[str, int] = {}
        for a in ads.values():
            seen[a] = seen.get(a, 0) + 1
        cdir = ev / _criterion_dir(olcut)
        cdir.mkdir(parents=True, exist_ok=True)
        for sira, it in enumerate(lst, 1):
            ad = ads[it.doc_id]
            if seen[ad] > 1:          # aynı ölçütte aynı ad: tarihle (yoksa kısa kimlikle) ayır
                ad = safe_name(f"{ad} ({date_of(docs.get(it.doc_id)) or it.doc_id[:6]})")
            inv_row = inv.get(it.doc_id)
            flags = list(it.isaretler)
            pages_txt, rel_out = "", ""
            if inv_row is None:
                flags.append("envanterde_yok")
                n_missing += 1
            else:
                srcf = src_root / inv_row["rel_path"]
                ext = (inv_row.get("ext") or srcf.suffix or "").lower()
                fn = file_name(olcut, sira, it.od, ad, ext)
                dst = cdir / fn
                if not srcf.is_file():
                    flags.append("kaynak_dosya_yok")
                    n_missing += 1
                else:
                    pages = None
                    if ext == PDF and not whole:
                        pages, why = _select_pages(ws, it, srcf)
                        if why:
                            flags.append(why)
                    try:
                        if pages:
                            cut_pdf(srcf, dst, pages)
                            pages_txt = page_ranges(pages)
                            n_cut += 1
                        else:
                            shutil.copyfile(srcf, dst)
                    except Exception as e:      # bozuk PDF: tüm belgeyi kopyala
                        flags.append(f"sayfa_kesilemedi:{type(e).__name__}")
                        shutil.copyfile(srcf, dst)
                        pages_txt = ""
                    rel_out = dst.relative_to(ev).as_posix()
            rows.append({
                "kanit_no": f"{sira}_OD{it.od}", "olcut": olcut, "od": it.od, "ad": ad, "dosya": rel_out,
                "doc_id": it.doc_id, "sayfalar": pages_txt, "yuvalar": "; ".join(it.yuvalar),
                "alintilar": json.dumps(it.alintilar, ensure_ascii=False), "inceleme": it.inceleme,
                "kopyalar": "; ".join(it.kopyalar), "kaynak": (inv_row or {}).get("rel_path", ""),
                "isaretler": ", ".join(dict.fromkeys(flags)), "ad_kaynagi": names[it.doc_id][1]})

    idx = out / INDEX
    with open(idx, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    if not meta["inceleme"]:
        (ev / NO_REVIEW).write_text(
            "İNCELEME YAPILMADI\n\nBu kanıt klasörü review-decisions.jsonl olmadan (bidr audit apply "
            "çalıştırılmadan) üretildi.\nDosyalar modelin kabul edilmiş eşleşmeleridir; insan onayı yoktur.\n",
            encoding="utf-8")
    manifest = {"surum": SURUM, "calisma_alani": str(ws.root), **meta, "tum_belge": whole,
                "kanit": len(rows), "index_sha": _sha(idx)}
    (ev / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    zpath = None
    if make_zip:
        zpath = out / ZIP
        write_zip(ev, zpath)
    return {"kanit": len(rows), "olcut": len(by_c), "belge": len({r["doc_id"] for r in rows}),
            "kesilen_pdf": n_cut, "eksik_dosya": n_missing, "inceleme": meta["inceleme"],
            "index": str(idx), "evidence": str(ev), "zip": str(zpath) if zpath else None,
            "uyarilar": list(dict.fromkeys(uyarilar))}


def _select_pages(ws: Workspace, it: Item, srcf: Path) -> tuple[list[int] | None, str | None]:
    tp = ws.text_path(it.doc_id)
    if not tp.exists():
        return None, "metin_yok_tum_belge"
    text = tp.read_text(encoding="utf-8", errors="replace")
    n_text = text.count("\f") + 1
    if n_text <= 1:
        return None, None
    pages = pages_of_spans(text, it.spans)
    if not pages:
        return None, "alinti_konumu_yok_tum_belge"
    n_pdf = pdf_pages(srcf)
    if n_pdf != n_text:
        return None, "sayfa_sayisi_uyusmuyor_tum_belge"
    if len(pages) >= n_pdf:
        return None, None
    return pages, None


def write_zip(ev: Path, zpath: Path) -> None:
    tmp = zpath.with_suffix(".zip.tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(ev.rglob("*")):
            if p.is_file() and p.name != MANIFEST:
                zi = zipfile.ZipInfo(f"{EVIDENCE}/{p.relative_to(ev).as_posix()}", (1980, 1, 1, 0, 0, 0))
                zi.compress_type = zipfile.ZIP_DEFLATED
                zi.flag_bits |= 0x800          # UTF-8 dosya adı (Türkçe karakter)
                z.writestr(zi, p.read_bytes())
    tmp.replace(zpath)


def status(out: Path, ws_root: Path | None = None, review_dir: Path | None = None) -> dict:
    """Tamamlanma denetimi için salt okunur durum (şefin `file_tamam`'ı için)."""
    out = Path(out)
    ws_root = Path(ws_root or out)
    review_dir = Path(review_dir or ws_root)
    ev, idx = out / EVIDENCE, out / INDEX
    st = {"index": idx.exists(), "manifest": (ev / MANIFEST).exists(), "guncel": False,
          "inceleme": False, "kanit": 0, "eksik_dosya": 0}
    if not (st["index"] and st["manifest"]):
        return st
    m = json.loads((ev / MANIFEST).read_text(encoding="utf-8"))
    st["inceleme"] = bool(m.get("inceleme"))
    st["guncel"] = (m.get("kararlar_sha") == _sha(ws_root / "decisions.jsonl")
                    and m.get("inceleme_sha") == _sha(review_dir / REVIEW)
                    and m.get("index_sha") == _sha(idx)
                    and m.get("adlar_sha", _names_sha(ws_root, review_dir)) == _names_sha(ws_root, review_dir))
    with open(idx, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    st["kanit"] = len(rows)
    st["eksik_dosya"] = sum(1 for r in rows if not r["dosya"] or not (ev / r["dosya"]).is_file())
    return st
