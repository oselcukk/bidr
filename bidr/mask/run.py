"""`bidr maskele`: dosyalanmış kanıtların (evidence/) maskeli yayın kopyası → `evidence-maskeli/`.

Asıl dosyalara dokunulmaz. Her kopya maskelemeden sonra bağımsız olarak yeniden taranır;
kişisel veri, imza şüphesi ya da temizlenmemiş üst veri/yorum/ek kalırsa (`basarisiz`) ya da
metin katmanı olmayan sayfa/görsel OCR'dan geçemezse (`taranamadi`) kopya `evidence-maskeli/`'ye
girmez, `maskeleme-basarisiz/` altına alınır ve `maskeleme-raporu.json`'da `yayimlanamaz`
listesine yazılır (`elle_bakilmali: true`). Özgün kanıt rapordan/paketten çıkarılmaz; maskeleme
kanıt seçimini etkilemez. Desteklenmeyen biçimler (sunumlar …) kopyalanmaz, aynı listeye girer.
Rapora bulunan değerlerin kendisi yazılmaz; yalnız tür ve sayı.
"""
from __future__ import annotations

import csv
import json
import shutil
from collections import Counter
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from .detect import MaskRules, mask_text, read_ws_config
from .formats import MaskError, kind_of, mask_file, pdf_engine, scan_file
from .ocr import ocr_available as raster_ocr_available

OUT_DIR = "evidence-maskeli"
FAIL_DIR = "maskeleme-basarisiz"
REPORT = "maskeleme-raporu.json"
MARKER = ".bidr-maskeleme.json"
INDEX = "evidence-index.csv"
INDEX_OUT = "evidence-index-maskeli.csv"
INDEX_MASK_COLS = ("ad", "alintilar", "kaynak")
SURUM = 1


class MaskRunError(RuntimeError):
    pass


def _inside(a: Path, b: Path) -> bool:
    try:
        a.relative_to(b)
        return True
    except ValueError:
        return False


def _prepare_dir(d: Path) -> None:
    if d.exists():
        if any(d.iterdir()) and not (d / MARKER).exists():
            raise MaskRunError(f"{d} bidr'in üretmediği dosyalar içeriyor; taşıyın ya da başka --out verin")
        shutil.rmtree(d)
    d.mkdir(parents=True)


def _files(ev: Path) -> list[Path]:
    return sorted(p for p in ev.rglob("*")
                  if p.is_file() and not any(part.startswith(".") for part in p.relative_to(ev).parts))


def _c(c) -> dict:
    return dict(sorted((k, v) for k, v in (c or {}).items() if v))


# Modelin görsel okuma metninde (çalışma alanı `text/<doc_id>.txt`; sayfalar form feed ile ayrılır)
# aranan ve maskelemenin o sayfada kapatmış olması gereken türler.
MODEL_KINDS = {"tc_no": "kimlik no", "telefon": "telefon", "eposta": "e-posta", "ogrenci_no": "öğrenci no",
               "iban": "IBAN"}
EL_YAZISI_SORUN = "elle bakılmalı: el yazısı kişisel veri kapatılamadı"


def model_text_gaps(model_text: str, res: dict, rules: MaskRules) -> tuple[list[str], str | None]:
    """Modelin okuduğu metinde bir sayfada kimlik no/telefon/e-posta/öğrenci no varken maskeleme o
    sayfada o türden daha azını kapattıysa (OCR el yazısını okuyamadı, etiketi de bulunamadı) →
    (["s.N: tür, tür", …], uyarı). Değerler yazılmaz; yalnız tür ve sayfa. Maskeleyici sayfa kapsamı
    vermediyse (sayfasız biçim, pypdf motoru) belge bütünü karşılaştırılır ("belge: tür"). Sayfa
    sayısı uyuşmuyorsa denetim yapılmaz (uyarı döner)."""
    from .detect import detect
    kapsam = res.get("sayfa_kapsam")
    if kapsam is None:                    # sayfasız biçim (metin, docx …) ya da pypdf: belge bütünü
        want = Counter(f.kind for f in detect(model_text, rules) if f.kind in MODEL_KINDS)
        have = res.get("maskelenen") or {}
        eksik = [MODEL_KINDS[k] for k in MODEL_KINDS if want[k] > have.get(k, 0)]
        return ([f"belge: {', '.join(eksik)}"] if eksik else []), None
    pages = model_text.split("\f")
    n = res.get("sayfa_sayisi") or len(kapsam)
    if len(pages) == n + 1 and not pages[-1].strip():       # sondaki form feed
        pages = pages[:-1]
    if len(pages) != n:
        return [], f"model metni denetimi yapılamadı (sayfa sayısı uyuşmuyor: metin {len(pages)}, dosya {n})"
    out = []
    for i, t in enumerate(pages, 1):
        want = Counter(f.kind for f in detect(t, rules) if f.kind in MODEL_KINDS)
        have = kapsam.get(i) or kapsam.get(str(i)) or {}
        eksik = [MODEL_KINDS[k] for k in MODEL_KINDS if want[k] > have.get(k, 0)]
        if eksik:
            out.append(f"s.{i}: " + ", ".join(eksik))
    return out, None


def mask_and_check(src: Path, dst: Path, rules: MaskRules, eng: str, model_text: str | None = None) -> dict:
    """Tek dosya: tara → maskele (`dst`) → maskeli kopyayı bağımsız yeniden tara.

    → kayıt alanları: `durum` (tamam | basarisiz | taranamadi | hata), `elle_bakilmali`, `neden`,
    `bulunan`/`maskelenen`/`kalan` (tür → sayı), `temizlenen`, `kalan_sorunlar`, `uyarilar`, imza
    alanları. `hata`da `dst` silinir; diğer durumlarda maskeli kopya `dst`'de kalır (nereye
    konacağına çağıran karar verir). Değerlerin kendisi yazılmaz."""
    rec: dict = {}
    try:
        before = scan_file(src, rules)
    except Exception as e:
        before = {"bulgular": Counter(), "sorunlar": [f"kaynak taranamadı: {type(e).__name__}"], "imza": []}
    try:
        res = mask_file(src, dst, rules, engine=eng)
        after = scan_file(dst, rules)
    except (MaskError, Exception) as e:   # bozuk dosya vb.
        if dst.exists():
            dst.unlink()
        rec.update(durum="hata", elle_bakilmali=True, neden=f"maskelenemedi: {type(e).__name__}: {e}"[:300],
                   bulunan=_c(before["bulgular"]))
        return rec
    kalan = after["bulgular"]
    sorunlar = list(after["sorunlar"])
    model_uyari = []
    if model_text is not None:
        gaps, note = model_text_gaps(model_text, res, rules)
        if gaps:
            rec["el_yazisi_elle"] = gaps
            sorunlar.append(f"{EL_YAZISI_SORUN} ({'; '.join(gaps)})")
        if note:
            model_uyari.append(note)
    taranamadi = list(after.get("taranamadi") or [])
    if after.get("imza_aday"):
        sorunlar.append(f"imza: kapatılamayan aday ×{after['imza_aday']}")
    rec.update(bulunan=_c(before["bulgular"]), maskelenen=_c(res["maskelenen"]), kalan=_c(kalan),
               temizlenen=res["temizlenen"], kalan_sorunlar=sorunlar,
               uyarilar=list(res["uyarilar"]) + list(after.get("uyarilar") or []) + model_uyari)
    if before["imza"]:
        rec["imza_uyarisi"] = before["imza"]
    if res.get("imza_bolgesi"):
        rec["imza_bolgesi"] = res["imza_bolgesi"]
        rec["imza_ortusen_kelime"] = res.get("ortusen_kelime", 0)
    if after.get("imza_elle"):
        rec["imza_elle"] = after["imza_elle"]
    if after.get("imza_metin"):
        rec["imza_metin_elle"] = len(after["imza_metin"])         # metinle örtüştüğü için kapatılmayan
        rec["imza_metin_yer"] = after["imza_metin"]
    if taranamadi:
        rec["taranamadi"] = taranamadi
    if kalan or sorunlar or taranamadi:
        parts = [f"{k}×{n}" for k, n in sorted(kalan.items())] + list(sorunlar)
        if kalan or sorunlar:
            durum, neden = "basarisiz", "maskeleme başarısız; kalan: " + ", ".join(parts)
            if taranamadi:
                neden += "; taranamadı: " + "; ".join(taranamadi)
        else:
            durum = "taranamadi"
            neden = "maskeleme eksik, elle bakılmalı: taranamadı (" + "; ".join(taranamadi) + ")"
        rec.update(durum=durum, neden=neden[:600], elle_bakilmali=True)
    else:
        rec.update(durum="tamam", elle_bakilmali=False)
    return rec


def read_model_text(p: Path | None) -> str | None:
    if p is None or not p.is_file():
        return None
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _doc_texts(ws: Path, csv_name: str, path_col: str) -> dict[str, Path]:
    """`<ws>/<csv>`'deki yol → `<ws>/text/<doc_id>.txt` (yalnız var olanlar)."""
    f = ws / csv_name
    out: dict[str, Path] = {}
    if not f.is_file():
        return out
    try:
        with open(f, encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                rel, did = (row.get(path_col) or "").strip(), (row.get("doc_id") or "").strip()
                if rel and did and rel not in out and (ws / "text" / f"{did}.txt").is_file():
                    out[rel] = ws / "text" / f"{did}.txt"
    except (OSError, csv.Error):
        return {}
    return out


def evidence_model_texts(ws: Path) -> dict[str, Path]:
    """Kanıt dosyası (evidence/ göreli yolu) → modelin okuma metni (`evidence-index.csv` doc_id)."""
    return _doc_texts(ws, INDEX, "dosya")


def source_model_texts(ws: Path) -> dict[str, Path]:
    """Kaynak dosyası (kaynak klasöre göreli yol) → modelin okuma metni (`inventory.csv` doc_id)."""
    return _doc_texts(ws, "inventory.csv", "rel_path")


def run(ws_root: Path, *, evidence: Path | None = None, out: Path | None = None, engine: str = "auto",
        names: list[str] | None = None, rules: MaskRules | None = None) -> dict:
    ws = Path(ws_root).expanduser().resolve()
    ev = Path(evidence).expanduser().resolve() if evidence else ws / "evidence"
    if not ev.is_dir():
        raise FileNotFoundError(f"kanıt klasörü yok: {ev} (önce `bidr file`)")
    out = Path(out).expanduser().resolve() if out else ev.parent
    dst_root, fail_root = out / OUT_DIR, out / FAIL_DIR
    for d in (dst_root, fail_root):
        if _inside(d, ev) or _inside(ev, d):
            raise MaskRunError(f"çıktı klasörü kanıt klasörüyle iç içe olamaz: {d} / {ev}")
    if rules is None:
        rules = MaskRules.from_config(read_ws_config(ws), ws)
    if names:
        rules = replace(rules, names=tuple(rules.names) + tuple(names))
    model_texts = evidence_model_texts(ws)
    eng = pdf_engine(engine)
    _prepare_dir(dst_root)
    _prepare_dir(fail_root)

    uyarilar = list(rules.warnings)
    if not raster_ocr_available():
        uyarilar.append("OCR yok (tesseract + tur/eng dil verisi): metin katmanı olmayan PDF sayfaları ve "
                        "görseller taranamadı; bu dosyalar 'taranamadi' durumunda kalır")
    if eng == "pypdf":
        uyarilar.append("PyMuPDF kurulu değil: PDF'ler pypdf ile en iyi çabayla maskelendi; gerçek "
                        "kaldırma (redaction) için `pip install 'bidr[maske]'`")
    kayitlar, yayimlanamaz = [], []
    toplam = {"bulunan": Counter(), "maskelenen": Counter(), "kalan": Counter()}
    toplam_imza = Counter()
    for src in _files(ev):
        rel = src.relative_to(ev)
        kind = kind_of(src)
        rec: dict = {"dosya": rel.as_posix(), "bicim": kind or (src.suffix.lower().lstrip(".") or "?")}
        if kind is None:
            rec.update(durum="desteklenmiyor", elle_bakilmali=True,
                       neden="biçim taranamıyor (sunum vb.); kopyalanmadı, elle incelenmeli")
            kayitlar.append(rec)
            yayimlanamaz.append({"dosya": rec["dosya"], "neden": rec["neden"]})
            continue
        if kind == "pdf":
            rec["motor"] = eng
        dst = dst_root / rel
        mt = read_model_text(model_texts.get(rel.as_posix()))
        if mt is not None:
            rec["model_metni"] = True
        rec.update(mask_and_check(src, dst, rules, eng, model_text=mt))
        toplam["bulunan"].update(rec.get("bulunan") or {})
        toplam["maskelenen"].update(rec.get("maskelenen") or {})
        toplam["kalan"].update(rec.get("kalan") or {})
        toplam_imza["bolge"] += rec.get("imza_bolgesi", 0)
        toplam_imza["ortusen_kelime"] += rec.get("imza_ortusen_kelime", 0)
        if rec["durum"] == "hata":
            yayimlanamaz.append({"dosya": rec["dosya"], "neden": rec["neden"]})
        elif rec["durum"] != "tamam":
            target = fail_root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dst), str(target))
            rec["kopya"] = f"{FAIL_DIR}/{rel.as_posix()}"
            yayimlanamaz.append({"dosya": rec["dosya"], "neden": rec["neden"]})
        kayitlar.append(rec)

    # boş kalan klasörleri temizle
    for d in sorted((p for p in dst_root.rglob("*") if p.is_dir()), key=lambda p: -len(p.parts)):
        if not any(d.iterdir()):
            d.rmdir()

    durumlar = Counter(r["durum"] for r in kayitlar)
    index_out = _mask_index(ev.parent / INDEX, out / INDEX_OUT, rules, {r["dosya"]: r["durum"] for r in kayitlar})
    rapor = {
        "surum": SURUM, "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "kanit_klasoru": str(ev), "maskeli_klasor": str(dst_root), "pdf_motoru": eng,
        "kurallar": {"turler": list(rules.kinds), "ogrenci_no_desen_sayisi": len(rules.student_patterns),
                     "ad_listesi_sayisi": len(rules.names), "etiket_alani": rules.label_fields},
        "ozet": {"dosya": len(kayitlar), **dict(sorted(durumlar.items())),
                 **{k: _c(v) for k, v in toplam.items()},
                 "imza_bolgesi": toplam_imza["bolge"], "imza_ortusen_kelime": toplam_imza["ortusen_kelime"],
                 "imza_elle_dosya": sum(1 for r in kayitlar if r.get("imza_elle")),
                 "imza_metinle_ortusen_elle": sum(r.get("imza_metin_elle", 0) for r in kayitlar),
                 "model_metni_denetlenen": sum(1 for r in kayitlar if r.get("model_metni")),
                 "el_yazisi_elle_dosya": sum(1 for r in kayitlar if r.get("el_yazisi_elle"))},
        "ocr": raster_ocr_available(),
        "yayimlanamaz": yayimlanamaz, "uyarilar": uyarilar, "dosyalar": kayitlar,
        "maskeli_dizin": str(index_out) if index_out else None,
    }
    (out / REPORT).write_text(json.dumps(rapor, ensure_ascii=False, indent=1), encoding="utf-8")
    marker = {"surum": SURUM, "zaman": rapor["zaman"], "kaynak": str(ev), "rapor": str(out / REPORT)}
    for d in (dst_root, fail_root):
        d.mkdir(parents=True, exist_ok=True)
        (d / MARKER).write_text(json.dumps(marker, ensure_ascii=False, indent=1), encoding="utf-8")
    return rapor


def _mask_index(src: Path, dst: Path, rules: MaskRules, durum: dict[str, str]) -> Path | None:
    """`evidence-index.csv` varsa yayına uygun kopyası: ad/alıntı/kaynak maskeli, `maskeleme` sütunu."""
    if not src.is_file():
        return None
    with open(src, encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        cols = list(r.fieldnames or [])
        rows = list(r)
    if "maskeleme" not in cols:
        cols.append("maskeleme")
    for row in rows:
        for c in INDEX_MASK_COLS:
            if row.get(c):
                row[c] = mask_text(row[c], rules)[0]
        row["maskeleme"] = durum.get(row.get("dosya") or "", "yok") if row.get("dosya") else "yok"
    with open(dst, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    return dst
