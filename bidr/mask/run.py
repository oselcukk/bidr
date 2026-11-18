"""`bidr maskele`: dosyalanmış kanıtların (evidence/) maskeli yayın kopyası → `evidence-maskeli/`.

Asıl dosyalara dokunulmaz. Her kopya maskelemeden sonra bağımsız olarak yeniden taranır;
kişisel veri ya da temizlenmemiş üst veri/yorum/ek kalırsa kopya `evidence-maskeli/`'ye girmez,
`maskeleme-basarisiz/` altına alınır ve `maskeleme-raporu.json`'da `yayimlanamaz` listesine yazılır.
Desteklenmeyen biçimler (görseller, sunumlar …) taranamadığı için kopyalanmaz, aynı listeye girer.
Rapora bulunan değerlerin kendisi yazılmaz; yalnız tür ve sayı.
"""
from __future__ import annotations

import csv
import json
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path

from .detect import MaskRules, mask_text, read_ws_config
from .formats import MaskError, kind_of, mask_file, pdf_engine, scan_file

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
        rules = MaskRules(kinds=rules.kinds, student_patterns=rules.student_patterns,
                          names=tuple(rules.names) + tuple(names), local_model=rules.local_model)
    eng = pdf_engine(engine)
    _prepare_dir(dst_root)
    _prepare_dir(fail_root)

    uyarilar = list(rules.warnings)
    if eng == "pypdf":
        uyarilar.append("PyMuPDF kurulu değil: PDF'ler pypdf ile en iyi çabayla maskelendi; gerçek "
                        "kaldırma (redaction) için `pip install 'bidr[maske]'`")
    kayitlar, yayimlanamaz = [], []
    toplam = {"bulunan": Counter(), "maskelenen": Counter(), "kalan": Counter()}
    for src in _files(ev):
        rel = src.relative_to(ev)
        kind = kind_of(src)
        rec: dict = {"dosya": rel.as_posix(), "bicim": kind or (src.suffix.lower().lstrip(".") or "?")}
        if kind is None:
            rec.update(durum="desteklenmiyor",
                       neden="biçim taranamıyor (görsel/sunum vb.); kopyalanmadı, elle incelenmeli")
            kayitlar.append(rec)
            yayimlanamaz.append({"dosya": rec["dosya"], "neden": rec["neden"]})
            continue
        if kind == "pdf":
            rec["motor"] = eng
        try:
            before = scan_file(src, rules)
        except Exception as e:
            before = {"bulgular": Counter(), "sorunlar": [f"kaynak taranamadı: {type(e).__name__}"], "imza": []}
        dst = dst_root / rel
        try:
            res = mask_file(src, dst, rules, engine=eng)
            after = scan_file(dst, rules)
        except (MaskError, Exception) as e:   # bozuk dosya vb.: yayımlanamaz
            if dst.exists():
                dst.unlink()
            rec.update(durum="hata", neden=f"maskelenemedi: {type(e).__name__}: {e}"[:300],
                       bulunan=_c(before["bulgular"]))
            kayitlar.append(rec)
            yayimlanamaz.append({"dosya": rec["dosya"], "neden": rec["neden"]})
            toplam["bulunan"].update(before["bulgular"])
            continue
        kalan = after["bulgular"]
        sorunlar = after["sorunlar"]
        rec.update(bulunan=_c(before["bulgular"]), maskelenen=_c(res["maskelenen"]), kalan=_c(kalan),
                   temizlenen=res["temizlenen"], kalan_sorunlar=sorunlar, uyarilar=res["uyarilar"])
        if before["imza"]:
            rec["imza_uyarisi"] = before["imza"]
        toplam["bulunan"].update(before["bulgular"])
        toplam["maskelenen"].update(res["maskelenen"])
        toplam["kalan"].update(kalan)
        if kalan or sorunlar:
            target = fail_root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dst), str(target))
            parts = [f"{k}×{n}" for k, n in sorted(kalan.items())] + list(sorunlar)
            rec.update(durum="basarisiz", neden="maskeleme başarısız; kalan: " + ", ".join(parts),
                       kopya=f"{FAIL_DIR}/{rel.as_posix()}")
            yayimlanamaz.append({"dosya": rec["dosya"], "neden": rec["neden"]})
        else:
            rec["durum"] = "tamam"
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
                     "ad_listesi_sayisi": len(rules.names)},
        "ozet": {"dosya": len(kayitlar), **dict(sorted(durumlar.items())),
                 **{k: _c(v) for k, v in toplam.items()}},
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
