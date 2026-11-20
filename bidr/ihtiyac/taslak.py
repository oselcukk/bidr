"""İç çalışma taslağı: report.docx'in KOPYASINA (`report-ic.docx`) ölçüt hücrelerinin sonuna
"[EKSİK: …]" işaretleri. Asıl report.docx'e asla yazılmaz; render koduna dokunulmaz (blok bulucu
`bidr.render.template.find_blocks` yalnız okunarak kullanılır)."""
from __future__ import annotations

import shutil
from pathlib import Path

ADI = "report-ic.docx"
BASLIK = "İÇ ÇALIŞMA TASLAĞI — [EKSİK: …] işaretleri bidr ihtiyac üretti; dağıtılmaz."


def isaret(s: dict, talepler: list[dict], n: int = 3) -> str | None:
    ts = [t for t in talepler if t["olcut"] == s["olcut"]][:n]
    if not ts:
        return None
    parca = []
    for t in ts:
        x = t["istenecek"].split(":")[0] if t["puan"] >= 80 else t["istenecek"]
        parca.append(f"{x} ({t['kimden']})")
    return "[EKSİK: " + "; ".join(parca) + "]"


def write_draft(src: Path, out_dir: Path, satirlar: list[dict], talepler: list[dict]) -> tuple[Path, int, list[str]]:
    from docx import Document
    from docx.shared import RGBColor
    from docx.table import _Cell

    from bidr.render.template import find_blocks

    src = Path(src).resolve()
    dst = (Path(out_dir) / ADI).resolve()
    if dst == src or dst.name == "report.docx":
        raise ValueError("iç taslak asıl report.docx'in üstüne yazılamaz")
    if not src.exists():
        raise FileNotFoundError(f"report.docx yok: {src} (önce `bidr render`)")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    doc = Document(str(dst))
    blocks, uy = find_blocks(doc)
    n = 0
    for s in satirlar:
        b = blocks.get(s["olcut"])
        txt = isaret(s, talepler)
        if not txt:
            continue
        tc = (b.aciklama_tc if b is not None else None)
        if tc is None:
            uy.append(f"{s['olcut']}: şablonda 'Açıklamalar:' hücresi yok; işaret konmadı")
            continue
        run = _Cell(tc, None).add_paragraph().add_run(txt)
        run.bold = True
        run.font.color.rgb = RGBColor(0xC0, 0x00, 0x00)
        n += 1
    if doc.paragraphs:
        run = doc.paragraphs[0].insert_paragraph_before().add_run(BASLIK)
    else:
        run = doc.add_paragraph().add_run(BASLIK)
    run.bold = True
    run.font.color.rgb = RGBColor(0xC0, 0x00, 0x00)
    doc.save(str(dst))
    return dst, n, uy
