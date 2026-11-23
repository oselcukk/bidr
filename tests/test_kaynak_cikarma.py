"""Kaynaktan çıkarılan belge: sonraki koşuda kararları, inceleme satırları, kanıt dizini ve rapor atfı düşer.

Sentetik zincir (test_pipeline kurgusu, model yok): ilk koşu rapora kadar → bir belge kaynaktan silinir →
`bidr ingest` türetilmiş kayıtlarını `kaynaktan-cikarilan/`e taşır → `bidr next` komutlarıyla audit, file,
render yeniden koşar; o belgeye ait satırlar kalkar, kanıtı kalmayan ölçüt kanıtsız yazılır (TASLAK değil).
"""
from __future__ import annotations

import csv
import json
import re
import shlex
import zipfile

from openpyxl import load_workbook

from bidr.cli import main
from bidr.common import read_jsonl
from bidr.ingest.pipeline import REMOVED_DIR, _prune_removed
from bidr.pipeline import evaluate
from bidr.write.sources import load_index

from test_pipeline import (_agent_answers, _rapor_config, _verify_answers, _verify_yonler_answers,  # noqa: F401
                           _write_answers, _yonler_answers, kurulum)
from test_render import make_template

CIKAN = "Kanıtlar/B.1.1/[B.1.1-1-OD3] Kurul Kararı.txt"


def _kabul_et(ws) -> None:
    wb = load_workbook(ws / "review.xlsx")
    sh = wb["Eşleşmeler"]
    col = [c.value for c in sh[1]].index("KARAR (kabul/ret/duzelt)") + 1
    for r in range(2, sh.max_row + 1):
        if not sh.cell(row=r, column=col).value:
            sh.cell(row=r, column=col, value="kabul")
    wb.save(ws / "review.xlsx")


def _rapora_kadar(src, ws, ans) -> None:
    w = str(ws)
    assert main(["init", "-w", w, "--answers", str(ans)]) == 0
    assert main(["ingest", str(src), "-w", w, "--no-ocr", "--workers", "1"]) == 0
    assert main(["labels", "build", str(src), "-w", w, "--unit", "Örnek"]) == 0
    assert main(["identify", "-w", w, "--period", "2025"]) == 0
    assert main(["candidates", "-w", w, "--profile", "akademik_bolum"]) == 0
    for st in ("coarse", "fine"):
        assert main(["decide", "prepare", "-w", w, "--stage", st]) == 0
        _agent_answers(ws, st)
        assert main(["decide", "apply", "-w", w, "--stage", st, "--model", "test-ajan"]) == 0
    assert main(["compare-labels", "-w", w]) == 0
    for q in read_jsonl(ws / "label-review.jsonl"):
        assert main(["hakem", "cevap", "-w", w, q["soru_id"], q["secenekler"][0]]) == 0
    assert main(["compare-labels", "-w", w, "--apply"]) == 0
    assert main(["faaliyet", "-w", w]) == 0
    assert main(["audit", "-w", w]) == 0
    _kabul_et(ws)
    assert main(["audit", "apply", "-w", w]) == 0
    _rapor_config(ws, ikinci_arama=False)
    assert main(["file", "-w", w]) == 0
    assert main(["write", "prepare", "-w", w]) == 0
    _write_answers(ws, load_index(ws / "evidence-index.csv"))
    assert main(["write", "apply", "-w", w, "--model", "test-ajan"]) == 0
    assert main(["verify", "prepare", "-w", w]) == 0
    _verify_answers(ws)
    assert main(["verify", "apply", "-w", w, "--model", "test-dogrulayici"]) == 0
    _yonler(ws)


def _yonler(ws) -> None:
    w = str(ws)
    assert main(["yonler", "prepare", "-w", w]) == 0
    _yonler_answers(ws)
    assert main(["yonler", "apply", "-w", w, "--model", "test-ajan"]) == 0
    assert main(["verify", "prepare", "-w", w]) == 0
    _verify_yonler_answers(ws)
    assert main(["verify", "apply", "-w", w, "--model", "test-dogrulayici"]) == 0


def _komutlari_sur(ws, dur: str) -> list[str]:
    """`bidr next`in komutlarını `dur` aşamasına gelene dek çalıştırır (model/ajan işi yok)."""
    goren = []
    for _ in range(30):
        n = evaluate(ws).sonraki
        if n is None or n.id == dur:
            return goren
        assert n.kim == "komut" or (n.kim, n.id) in {("insan", "audit"), ("ajan", "verify"), ("ajan", "yonler")}, \
            (n.id, n.kim, n.neden)
        goren.append(n.id)
        if n.kim == "insan":
            _kabul_et(ws)
            continue
        if n.id == "verify":
            _verify_answers(ws)
            assert main(["verify", "apply", "-w", str(ws), "--model", "test-dogrulayici"]) == 0
            continue
        if n.id == "yonler":
            _yonler(ws)
            continue
        for k in n.komutlar:
            argv = shlex.split(k)
            assert main(argv[1:]) in (0, 1), k
    raise AssertionError(f"{dur} aşamasına gelinmedi: {goren}")


def _govde(ws) -> str:
    with zipfile.ZipFile(ws / "report.docx") as z:
        return re.sub(r"<[^>]+>", " ", z.read("word/document.xml").decode())


def test_kaynaktan_cikan_belge_kayitlardan_ve_rapordan_duser(kurulum):
    src, ws, ans = kurulum
    _rapora_kadar(src, ws, ans)
    make_template(ws.parent / "sablon.docx", ids=(("B.1.1", "Programların tasarımı"), ("B.2.3", "Öğrenci iş yükü")))
    _rapor_config(ws, sablon=str(ws.parent / "sablon.docx"))
    assert main(["render", "-w", str(ws)]) == 0
    did = next(r["doc_id"] for r in csv.DictReader(open(ws / "inventory.csv", encoding="utf-8"))
               if r["rel_path"] == CIKAN)
    idx = {r["olcut"]: r for r in csv.DictReader(open(ws / "evidence-index.csv", encoding="utf-8"))}
    assert idx["B.1.1"]["doc_id"] == did
    no = idx["B.1.1"]["kanit_no"]
    assert f"[{no}]" in _govde(ws)

    (src / CIKAN).unlink()
    assert "1 kaldırılmış" in evaluate(ws).get("ingest").neden
    assert main(["ingest", str(src), "-w", str(ws), "--no-ocr", "--workers", "1"]) == 0
    # türetilmiş kayıtlar kalktı (silinmedi, arşivde)
    assert not (ws / "text" / f"{did}.txt").exists()
    for f in ("documents.jsonl", "candidates.jsonl", "decisions.jsonl"):
        assert did not in {r.get("doc_id") for r in read_jsonl(ws / f)}, f
    assert not (ws / "work" / "fine" / f"{did}.json").exists()
    arch = ws / REMOVED_DIR
    assert (arch / "text" / f"{did}.txt").exists() and (arch / "work" / "fine" / f"{did}.out.json").exists()
    assert {r["dosya"] for r in read_jsonl(arch / "kayitlar.jsonl")} == {
        "documents.jsonl", "candidates.jsonl", "decisions.jsonl"}
    # identify/candidates kapısı "kaydı yok" demez; kararlar değişti → audit ve sonrası yeniden
    rep = evaluate(ws)
    assert rep.get("identify").durum == "bitti" and rep.get("candidates").durum == "bitti"
    goren = _komutlari_sur(ws, "render")
    assert "audit" in goren and "file" in goren
    assert evaluate(ws).get("karar_ince").durum == "bitti"          # model işi yok

    wb = load_workbook(ws / "review.xlsx")
    for sh in wb.worksheets:
        assert not any(did in str(c) for r in sh.iter_rows(values_only=True) for c in r), sh.title
    rows = list(csv.DictReader(open(ws / "evidence-index.csv", encoding="utf-8")))
    assert did not in {r["doc_id"] for r in rows} and "B.1.1" not in {r["olcut"] for r in rows}
    assert not list((ws / "evidence").rglob("*Program Onay*"))
    w = evaluate(ws).get("write")
    assert w.durum == "bitti" and any("artık kanıt yok" in u for u in w.uyarilar)
    assert evaluate(ws).get("verify").durum == "bitti"

    # rapor: çıkan belgenin atfı yok; kanıtı kalmayan ölçüt kanıtsız yazılır, TASLAK damgası yok
    assert main(["render", "-w", str(ws)]) == 0
    body = _govde(ws)
    assert f"[{no}]" not in body and "reddedildiği için" not in body
    i = body.find("Programların tasarımı")
    assert "kanıt bulunamamıştır" in body[i:body.find("Öğrenci iş yükü")]
    assert not any("TASLAK" in u for u in evaluate(ws).get("render").uyarilar)


def test_okunamayan_dosya_varken_kayit_kaldirilmaz(tmp_path):
    from bidr.common import Workspace
    ws = Workspace(tmp_path / "ws").ensure()
    ws.text_path("aaaa").write_text("x", encoding="utf-8")
    (ws.root / "decisions.jsonl").write_text(json.dumps({"doc_id": "aaaa"}) + "\n", encoding="utf-8")
    rows = [{"doc_id": "", "status": "not_downloaded", "rel_path": "icloud.pdf"}]
    assert _prune_removed(ws, rows, lambda m: None) == []          # iCloud'daki dosya o belge olabilir
    assert ws.text_path("aaaa").exists()
    assert _prune_removed(ws, [{"doc_id": "bbbb", "status": "ok"}], lambda m: None) == ["aaaa"]
    assert not ws.text_path("aaaa").exists() and not list(read_jsonl(ws.root / "decisions.jsonl"))
