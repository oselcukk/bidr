"""Kanıt dosyalama: onaylı eşleşmeler → `evidence/<A>/<A.1>/<A.1.2>/[1-OD3]. Ad.pdf` +
`evidence-index.csv` (sözleşme: docs/REPORT_LAYER.md).

Girdi (salt okunur): `decisions.jsonl`, `documents.jsonl`, `inventory.csv`, `text/`
(çalışma alanı); varsa `review-decisions.jsonl` (`review` klasörü, vars. çalışma alanı);
kaynak klasör. Eşleşme kümesi ve sayılan aşama/OD `bidr.audit.run.build` ile aynı kurallarla
hesaplanır (ret düşer, duzelt düzeltilmiş ölçüt/yuva/aşamayla girer). Yayımlanan liste bu
kümeden kanıt seçimiyle (`select.py`: sürüm/kopya birleştirme, ilgililik, üst sınırlar) seçilir;
audit OD'si seçimden etkilenmez, elenenler `evidence-secim.json` ve gaps.md "Kanıt seçimi"nde.

Kaynak dosyalara yalnız okumak için dokunulur; çıktı klasörü kaynağın içinde olamaz.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from bidr.common import Workspace, read_jsonl

from .naming import date_of, evidence_od, file_name, number_sources, safe_name, source_key

SURUM = 1
INDEX = "evidence-index.csv"
EVIDENCE = "evidence"
ZIP = "evidence.zip"
MANIFEST = ".bidr-evidence.json"
NO_REVIEW = "INCELEME_YAPILMADI.txt"
REVIEW = "review-decisions.jsonl"
GAPS = "gaps.md"
COLUMNS = ["kanit_no", "olcut", "od", "ad", "dosya", "doc_id", "sayfalar", "yuvalar", "alintilar",
           # sözleşme sütunlarından sonra ek bilgi
           "inceleme", "kopyalar", "kaynak", "isaretler", "ad_kaynagi", "baglanti", "baglanti_kaynagi"]
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
    kopyalar: list[str] = field(default_factory=list)          # mükerrer metin (decide `mukerrer`)
    isaretler: list[str] = field(default_factory=list)
    # kanıt seçimi (bidr/file/select.py) için
    asamalar: set[str] = field(default_factory=set)            # OD'ye sayılan (düşük güvenli olmayan) halkalar
    asamalar_tum: set[str] = field(default_factory=set)        # bütün satırların etkin aşamaları
    guven: str = ""                                            # sayılan satırların en yüksek güveni
    insan: bool = False                                        # inceleme kararı duzelt (insan yerleştirdi)
    onay: bool = False                                         # inceleme kararı kabul
    kurum_geneli: bool = False
    madde: bool = False                                        # alıntıda madde atfı
    dolayli_isaretler: set[str] = field(default_factory=set)
    dolayli: bool = False                                      # her sayılan satırı dolaylı işaretli
    kopyalar_surum: list[str] = field(default_factory=list)    # tek kanıt sayılan sürümler
    secim: str = ""                                            # neden yayımlandı (select.NEDEN)
    donem_disi: str = ""                                       # sayılmayan: "sonra" | "gecmis" (select.donem_disi)
    birim_bekliyor: bool = False                               # birim aitliği insanca onaylanmadı
    yuvalar_model: list[str] = field(default_factory=list)     # temsilcinin model yuvaları (karar sırası; ad/işaret)


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


_MADDE = re.compile(r"\bmadde\b|\bmd\.\s*\d")
_GUVEN = {"dusuk": 0, "orta": 1, "yuksek": 2}


def _best_guven(rows: list[dict]) -> str:
    gs = [r.get("guven") or "orta" for r in rows]        # eski kayıtta güven yok: orta
    return max(gs, key=lambda g: _GUVEN.get(g, 1)) if gs else ""


def plan(ws_root: Path, *, review_dir: Path | None = None, profile: str | None = None,
         prev_index: Path | None = None, select: bool = True) -> tuple[list[Item], dict]:
    """Eşleşme kümesi (audit'le aynı kurallar) → yayımlanacak kalemler. `select` kanıt
    seçimini (bidr/file/select.py) uygular; elenenler `meta["secim"]`'de."""
    from bidr.audit.run import build
    from bidr.identify.text import fold

    from . import select as S
    from bidr.decide.run import restorable
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
            if m.get("kabul") or restorable(m):     # insan birim kararıyla geri alınabilen de
                spans[(did, m["yuva"])] = (m.get("denetim") or {}).get("alinti_konum")
    settings = S.load_settings(ws.root)
    crit = {c["olcut"]: c for c in a.criteria}     # kanıt kodunun OD'si ölçüt OD'si ve zinciriyle tutarlı
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
        # kanıt kodunun OD'si: kodun düşüşleri (kurum geneli OD2, od_kabul düşüşü) yansır; ölçüt
        # OD'sine sayılmayan kanıt ölçüt OD'sinin üstünü göstermez (naming.evidence_od)
        od = evidence_od(rows, crit.get(olcut)) or max(ods)
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
        alintilar = list(dict.fromkeys(r["alinti"] for r in own if r["alinti"]))
        dol = [set(r["flags"]) & set(settings.dolayli) for r in (counted or rows)]
        items.append(Item(
            olcut=olcut, doc_id=rep, od=od,
            yuvalar=sorted({r["yuva"] for r in rows}, key=lambda y: (y.split("/")[0], int(y.split("/")[1]))),
            alintilar=alintilar,
            spans=[spans.get((rep, r["yuva_model"])) for r in own],
            sayilir=bool(counted), inceleme=inc, kopyalar=[x for x in ids if x != rep],
            isaretler=flags,
            asamalar={r["etkin_asama"] for r in counted},
            asamalar_tum={r["etkin_asama"] for r in rows if r["etkin_asama"]},
            guven=_best_guven(counted or rows),
            insan=any(r["karar"] == "duzelt" for r in rows),
            onay=any(r["karar"] == "kabul" for r in rows),
            kurum_geneli=all("kurum_geneli" in r["flags"] for r in rows if r["karar"] != "duzelt")
            and any(r["karar"] != "duzelt" for r in rows),
            madde=any(_MADDE.search(fold(q)) for q in alintilar),
            dolayli_isaretler=set().union(*dol) if dol else set(),
            dolayli=bool(dol) and all(dol),
            donem_disi="" if counted else S.donem_disi(rows),
            birim_bekliyor=all(r.get("birim_onay_bekliyor") for r in rows),
            yuvalar_model=list(dict.fromkeys(r["yuva_model"] for r in own if r.get("yuva_model")))))
    meta = {"inceleme": reviewed, "review": str(rpath) if reviewed else None,
            "kararlar_sha": _sha(ws.root / "decisions.jsonl"), "inceleme_sha": _sha(rpath),
            "profil": a.profile, "secim_sha": settings.sha(), "secim": None}
    if select:
        items, meta["secim"] = _select(ws, items, settings, prev_index or ws.root / INDEX)
    return items, meta


def _select(ws: Workspace, items: list[Item], settings, prev_index: Path) -> tuple[list[Item], dict]:
    """Ölçüt ölçüt sürüm birleştirme (K20) ve ilgililik seçimi (K18); bkz. bidr/file/select.py."""
    from . import select as S
    docs = {r["doc_id"]: r for r in read_jsonl(ws.documents)} if ws.documents.exists() else {}
    cited, atiflar, uy = S.cited_docs(ws.root, prev_index, prev_index.parent / S.SECIM)
    texts: dict[str, str] = {}

    def text_of(did: str) -> str:
        if did not in texts:
            p = ws.text_path(did)
            texts[did] = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
        return texts[did]

    by_c: dict[str, list[Item]] = {}
    for it in items:
        by_c.setdefault(it.olcut, []).append(it)
    kept: list[Item] = []
    dropped: list[dict] = []
    merges: list[dict] = []
    for olcut in sorted(by_c):
        lst = by_c[olcut]
        if settings.surum_birlestir:
            lst, mg = S.merge_versions(lst, docs, text_of, cited.get(olcut, set()))
            merges += mg
        k, d = S.select(lst, settings, cited.get(olcut, set()), docs)
        kept += k
        dropped += d
    return kept, {"settings": settings, "kept": kept, "dropped": dropped, "merges": merges,
                  "uyarilar": uy, "atiflar": atiflar, "aday": len(items), "docs": docs,
                  "metin_var": (ws.root / S.TEXTS).is_dir()}


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

    items, meta = plan(ws.root, review_dir=review_dir, profile=profile, prev_index=out / INDEX)
    secim = meta.pop("secim")
    inv = _inventory(ws)
    docs = {r["doc_id"]: r for r in read_jsonl(ws.documents)} if ws.documents.exists() else {}
    from bidr.name.resolve import Resolver
    rdir = Path(review_dir).expanduser().resolve() if review_dir else ws.root
    resolver = Resolver.load(ws.root, rdir, docs=docs, labels=_type_labels())
    meta["adlar_sha"] = _names_sha(ws.root, rdir)
    from .links import LinkResolver, gaps_block, links_sha, update_gaps
    linker = LinkResolver.load(ws.root, rdir)
    meta["baglantilar_sha"] = links_sha(ws.root, rdir)
    uyarilar: list[str] = []
    uyarilar.extend(secim["uyarilar"])
    if not meta["inceleme"]:
        uyarilar.append("review-decisions.jsonl yok: inceleme yapılmadı; decisions'taki kabul edilmiş "
                        "eşleşmeler dosyalandı, çıktı 'inceleme yapılmadı' diye işaretli")

    # numaralama: ölçüt içinde OD (artan), sonra çalışma adı, sonra doc_id → kararlı. Aynı kaynak
    # (aynı içerik ya da aynı sürüm grubu; parça grubu identify'da sürüm grubuna katılır) bir
    # ölçütte tek numara ve tek kod OD'si alır (naming.number_sources); dizinde aynı numaralı
    # satırlar aynı adı ve aynı bağlantıyı taşır (write ve render (ölçüt, kanit_no) ile okur).
    by_c: dict[str, list[Item]] = {}
    for it in items:
        by_c.setdefault(it.olcut, []).append(it)
    from bidr.criteria.model import id_key
    from bidr.transcribe.run import source_file

    if ev.exists():
        shutil.rmtree(ev)
    ev.mkdir(parents=True)
    rows, n_cut, n_missing = [], 0, 0
    names: dict[str, tuple[str, str]] = {}
    suspicious: dict[str, dict[str, str]] = {}      # doc_id → belge metnindeki şüpheli adresler

    def item_date(it) -> str | None:
        return part_date(docs.get(it.doc_id), it.alintilar, lambda: linker.text_of(it.doc_id))

    for olcut in sorted(by_c, key=id_key):
        lst = sorted(by_c[olcut], key=lambda i: (i.od, (docs.get(i.doc_id) or {}).get("calisma_adi") or "",
                                                 i.doc_id))
        numbered = number_sources(lst, key=lambda i: source_key(i.doc_id, docs, i), od=lambda i: i.od)
        item_names: dict[str, tuple[str, str]] = {}
        for it in lst:
            if it.doc_id not in names:       # öncelik: insan > model > kural (bidr/name/resolve.py)
                ad, src, uy = resolver.resolve(it.doc_id, it.kopyalar)
                names[it.doc_id] = (ad, src)
                uyarilar.extend(uy)
            # derleme belgede kalemin (yuvalarının) parça adı belge adının önüne geçer (insan hariç)
            item_names[it.doc_id] = resolver.item_name(it.doc_id, it.yuvalar_model, names[it.doc_id],
                                                       it.kopyalar)
        groups: dict[int, list[Item]] = {}
        for sira, _, it in numbered:
            groups.setdefault(sira, []).append(it)
        # listede görünen ad numaranın adıdır (grubun ilk üyesi); farklı numaralarda aynı ad tarihle
        # (yoksa kısa kimlikle) ayrılır
        shown = {sira: item_names[mem[0].doc_id][0] for sira, mem in groups.items()}
        seen = Counter(shown.values())
        for sira, mem in groups.items():
            if seen[shown[sira]] > 1:
                shown[sira] = safe_name(f"{shown[sira]} ({item_date(mem[0]) or mem[0].doc_id[:6]})")
        cdir = ev / _criterion_dir(olcut)
        cdir.mkdir(parents=True, exist_ok=True)
        used: set[str] = set()                 # klasördeki adlar (büyük/küçük harf duyarsız dosya sistemi)
        crows: list[dict] = []
        for sira, g_od, it in numbered:
            mem = groups[sira]
            ad = shown[sira]
            fad = ad if len(mem) == 1 else safe_name(
                f"{item_names[it.doc_id][0]} ({item_date(it) or it.doc_id[:6]})")
            inv_row = inv.get(it.doc_id)
            flags = list(it.isaretler)
            # model adının dayanağı (ad_dogrulanmali, ad_parca_uyumsuz) ve tek dosyada birden çok parça adı
            flags += resolver.item_flags(it.doc_id, it.yuvalar_model, it.kopyalar)
            if len(mem) > 1:
                flags.append("ayni_kaynak_tek_numara")
            pages_txt, rel_out = "", ""
            if inv_row is None:
                flags.append("envanterde_yok")
                n_missing += 1
            else:
                srcf = source_file(src_root, inv_row, ws.root)      # arşiv/e-posta üyesi: üyenin kendisi
                ext = (inv_row.get("ext") or Path(inv_row["rel_path"]).suffix or "").lower()
                dst = cdir / _unique(used, olcut, sira, g_od, fad, ext, it.doc_id)
                if srcf is None or not srcf.is_file():
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
            link, link_src = linker.resolve(it.doc_id, rel_out, it.kopyalar)
            bad_links = linker.suspicious(it.doc_id, it.kopyalar)
            if bad_links:
                suspicious[it.doc_id] = bad_links
                flags.append("baglanti_supheli")
            crows.append({
                "kanit_no": f"{sira}_OD{g_od}", "olcut": olcut, "od": g_od, "ad": ad, "dosya": rel_out,
                "doc_id": it.doc_id, "sayfalar": pages_txt, "yuvalar": "; ".join(it.yuvalar),
                "alintilar": json.dumps(it.alintilar, ensure_ascii=False), "inceleme": it.inceleme,
                "kopyalar": "; ".join(dict.fromkeys([*it.kopyalar, *it.kopyalar_surum])), "kaynak": (inv_row or {}).get("rel_path", ""),
                "isaretler": ", ".join(dict.fromkeys(flags)), "ad_kaynagi": item_names[mem[0].doc_id][1],
                "baglanti": link, "baglanti_kaynagi": link_src})
        _share_links(crows)
        rows += crows

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
    update_gaps(out / GAPS, gaps_block(rows, suspicious))
    from . import select as S
    S.record(out / S.SECIM, secim["settings"], secim["kept"], secim["dropped"], secim["merges"],
             secim["uyarilar"], secim["atiflar"])
    update_gaps(out / GAPS, S.gaps_block(secim["settings"], secim["kept"], secim["dropped"], secim["merges"],
                                         secim["docs"], secim["aday"], secim.get("metin_var", False)),
                S.GAPS_BEGIN, S.GAPS_END)
    ozet = {"aday": secim["aday"], "elenen": len(secim["dropped"]),
            "elenen_kurum_geneli": sum(1 for d in secim["dropped"] if d["kurum_geneli"]),
            "surum_birlesen": sum(len(m["uyeler"]) for m in secim["merges"])}
    manifest = {"surum": SURUM, "calisma_alani": str(ws.root), **meta, "secim": ozet, "tum_belge": whole,
                "kanit": len(rows), "index_sha": _sha(idx)}
    (ev / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    zpath = None
    if make_zip:
        zpath = out / ZIP
        write_zip(ev, zpath)
    adlari_guncellenen = sync_text_names(ws.root, rows) if out == ws.root else []
    return {"kanit": len(rows), "olcut": len(by_c), "belge": len({r["doc_id"] for r in rows}), **ozet,
            "metin_adlari_guncellenen": adlari_guncellenen,
            "baglantili": sum(1 for r in rows if r["baglanti"]),
            "baglanti_kaynagi": dict(sorted(Counter(r["baglanti_kaynagi"] or "yok" for r in rows).items())),
            "kesilen_pdf": n_cut, "eksik_dosya": n_missing, "inceleme": meta["inceleme"],
            "index": str(idx), "evidence": str(ev), "zip": str(zpath) if zpath else None,
            "uyarilar": list(dict.fromkeys(uyarilar))}


def part_date(doc: dict | None, quotes: list[str], text_of) -> str | None:
    """Dosya adındaki tarih: birleşik belgede (`parcalar` ≥2) alıntının parçasının tarihi (parça
    tarihsizse None: belge tarihi başka parçanındır), değilse belge tarihi (`date_of`). Kör test
    2026-11-20: "Toplumsal Katkı Faaliyetleri Yazısı (2025-01-06)" adındaki tarih aynı PDF'teki
    başka bir yazınındı."""
    parts = (doc or {}).get("parcalar") or []
    if len(parts) >= 2 and quotes:
        from bidr.identify.parca import part_of_page, quote_page
        text = text_of()
        for q in quotes:
            pg = quote_page(text or "", q)
            j = part_of_page(parts, pg) if pg is not None else None
            if j is not None:
                t = parts[j].get("tarih")
                return t if isinstance(t, str) and re.match(r"\d{4}-\d{2}-\d{2}$", t) else None
    return date_of(doc)


def sync_text_names(ws_root: Path, rows: list[dict]) -> list[str]:
    """Yazılmış ölçüt metinlerinin (`texts/<ölçüt>.json`) kanıt listesindeki ad ve dosya, dizinin
    kopyasıdır: dosyalama sonrası dizindekiyle eşitlenir → güncellenen ölçütler.

    Kör test 2026-11-20: parça adı adımı (bidr name) ve dosyalama doğru adı (AYDEK Usul ve Esasları,
    Araştırma Politikası) dizine ve dosya adına yazdı; ama metin adlandırmadan önce yazılmıştı, metnin
    girdisi (`girdi_sha`: kanıt no + doc_id + OD) değişmediği için eskimedi ve rapor metindeki eski
    belge adını (birleşik PDF'in ilk parçası) bastı. Yalnız girdisi güncel metin eşitlenir (numara aynı
    belgeleri gösteriyor); metnin kendisi, durumu ve doğrulaması değişmez (`text_sha` adları kapsamaz)."""
    from bidr.write import run as W
    from bidr.write.sources import AUDIT, load_audit
    td = Path(ws_root) / W.TEXTS
    if not td.is_dir():
        return []
    try:
        audit = load_audit(Path(ws_root) / AUDIT) if (Path(ws_root) / AUDIT).exists() else {}
    except (OSError, ValueError, KeyError, TypeError):
        audit = {}
    by_c: dict[str, list[dict]] = {}
    for r in rows:
        by_c.setdefault(r["olcut"], []).append(r)
    out = []
    for p in sorted(td.glob("*.json")):
        try:
            t = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        c = t.get("olcut") if isinstance(t, dict) else None
        crow = by_c.get(c or "")
        if not crow or not t.get("kanitlar") or not t.get("girdi_sha"):
            continue
        ods = {int((audit.get(c) or {}).get("od") or 0), int(t.get("od_onerisi") or 0)}
        if t["girdi_sha"] not in {W.girdi_sha(crow, od) for od in ods if od}:
            continue                     # girdi değişti: metin eskidir, yeniden yazılır (write_tamam)
        first: dict[str, dict] = {}
        for r in crow:
            first.setdefault(r["kanit_no"], r)
        changed = False
        for k in t["kanitlar"]:
            r = first.get(str(k.get("no")))
            if r is None:
                continue
            for f in ("ad", "dosya"):
                if r.get(f) and k.get(f) != r[f]:
                    k[f] = r[f]
                    changed = True
        if changed:
            p.write_text(json.dumps(t, ensure_ascii=False, indent=1), encoding="utf-8")
            out.append(c)
    return out


_LINK_RANK = {"insan": 0, "belge_metni": 1, "klasor": 2}


def _share_links(rows: list[dict]) -> None:
    """Aynı numaralı satırlar tek bağlantı taşır (render'ın haritası (ölçüt, kanit_no) → adres):
    öncelik insan > belge metni > klasör, eşitlikte grubun ilk üyesi."""
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r["kanit_no"], []).append(r)
    for mem in by.values():
        if len(mem) < 2:
            continue
        cand = [r for r in mem if r["baglanti"]]
        best = min(cand, key=lambda r: _LINK_RANK.get(r["baglanti_kaynagi"], 9)) if cand else None
        for r in mem:
            r["baglanti"], r["baglanti_kaynagi"] = (best["baglanti"], best["baglanti_kaynagi"]) if best else ("", "")


def _unique(used: set[str], olcut: str, sira: int, od: int, ad: str, ext: str, did: str) -> str:
    """Klasörde tekil dosya adı (büyük/küçük harf duyarsız: macOS/Windows). Çakışmada ada kısa
    kimlik, yine çakışırsa sayaç eklenir; `[sıra-ODk].` öneki ve uzantı korunur."""
    cand, k = file_name(olcut, sira, od, ad, ext), 1
    while cand.casefold() in used:
        # ek kısaltmayla düşmesin: önce ad kısaltılır
        cand = file_name(olcut, sira, od, f"{safe_name(ad, 64)} ({did[:6]}{'' if k == 1 else f'-{k}'})", ext)
        k += 1
    used.add(cand.casefold())
    return cand


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


def _links_sha(ws_root: Path, review_dir: Path) -> str:
    from .links import links_sha
    return links_sha(ws_root, review_dir)


def _secim_sha(ws_root: Path) -> str | None:
    from . import select as S
    try:
        return S.load_settings(ws_root).sha()
    except (S.SelectionError, OSError):
        return None


def status(out: Path, ws_root: Path | None = None, review_dir: Path | None = None) -> dict:
    """Tamamlanma denetimi için salt okunur durum (şefin `file_tamam`'ı için)."""
    out = Path(out)
    ws_root = Path(ws_root or out)
    review_dir = Path(review_dir or ws_root)
    ev, idx = out / EVIDENCE, out / INDEX
    st = {"index": idx.exists(), "manifest": (ev / MANIFEST).exists(), "guncel": False,
          "inceleme": False, "kanit": 0, "eksik_dosya": 0, "baglantisiz": 0}
    if not (st["index"] and st["manifest"]):
        return st
    m = json.loads((ev / MANIFEST).read_text(encoding="utf-8"))
    st["inceleme"] = bool(m.get("inceleme"))
    st["guncel"] = (m.get("kararlar_sha") == _sha(ws_root / "decisions.jsonl")
                    and m.get("inceleme_sha") == _sha(review_dir / REVIEW)
                    and m.get("index_sha") == _sha(idx)
                    and m.get("adlar_sha", _names_sha(ws_root, review_dir)) == _names_sha(ws_root, review_dir)
                    and m.get("baglantilar_sha") == _links_sha(ws_root, review_dir)
                    and m.get("secim_sha") == _secim_sha(ws_root))
    with open(idx, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    st["kanit"] = len(rows)
    st["eksik_dosya"] = sum(1 for r in rows if not r["dosya"] or not (ev / r["dosya"]).is_file())
    st["baglantisiz"] = sum(1 for r in rows if not (r.get("baglanti") or "").strip())
    return st
