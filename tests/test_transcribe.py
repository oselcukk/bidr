"""transcribe: sentetik görüntülü PDF/PNG ile prepare → (sahte ajan) .out.json → apply."""
from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from bidr.common import read_jsonl, sha256_file, write_jsonl
from bidr.transcribe import run as R

HAS_PDFTOPPM = bool(shutil.which("pdftoppm"))

OCR_TEXT = ("BÖLÜM KURULU TOPLANTI TUTANAĞI\nToplantı tarihi 14.03.2025 sayı 2025/07\n"
            "Gündem maddeleri görüşülmüştür. Karar 3: müfredat güncellemesi oybirliğiyle "
            "kabul edilmiştir.\nK@r#r 4 ~~ ll1 xq")
GOOD = ("BÖLÜM KURULU TOPLANTI TUTANAĞI\nToplantı tarihi: 14.03.2025  Sayı: 2025/07\n"
        "Gündem maddeleri görüşülmüştür.\nKarar 3: Müfredat güncellemesi oybirliğiyle kabul edilmiştir.\n"
        "Karar 4: Laboratuvar [okunamadı] talebi komisyona havale edilmiştir.")
FAKE = ("Fakülte yemekhanesinin menüsü haftalık olarak yayınlanacaktır. Spor salonu "
        "cumartesi kapalıdır. Otopark girişleri yenilenecektir.")


def _page(lines: list[str]) -> Image.Image:
    img = Image.new("RGB", (900, 1200), "white")
    dr = ImageDraw.Draw(img)
    for i, ln in enumerate(lines):
        dr.text((60, 80 + 40 * i), ln, fill="black")
    return img


def _ws(tmp: Path, docs: dict[str, tuple[str, str, int]]) -> tuple[Path, Path, dict[str, str]]:
    """docs: ad -> (uzantı, ocr metni, sayfa). Kaynak dosyaları üretir, inventory yazar."""
    src = tmp / "kaynak"
    ws = tmp / "ws"
    (ws / "text").mkdir(parents=True)
    src.mkdir()
    rows, ids = [], {}
    for name, (ext, text, pages) in docs.items():
        p = src / "alt" / f"{name}{ext}"
        p.parent.mkdir(exist_ok=True)
        imgs = [_page([f"{name} sayfa {i + 1}"]) for i in range(pages)]
        if ext == ".pdf":
            imgs[0].save(p, "PDF", resolution=100, save_all=True, append_images=imgs[1:])
        else:
            imgs[0].save(p)
        sha = sha256_file(p)
        did = sha[:16]
        ids[name] = did
        (ws / "text" / f"{did}.txt").write_text(text, encoding="utf-8")
        base = {"doc_id": did, "sha256": sha, "rel_path": f"alt/{name}{ext}", "ext": ext, "size": 1,
                "pages": pages, "chars": len(text), "method": "pdftotext+ocr(1/1)", "status": "ocr",
                "dup_of": "", "error": "", "ocr_conf": 41.0, "quality": 0.2, "low_quality": 1,
                "images_ocr": "", "images_lowq": ""}
        rows.append(base)
        if name == "pdf":   # birebir kopya satırı da güncellenmeli
            rows.append({**base, "rel_path": "kopya/pdf.pdf", "dup_of": f"alt/{name}{ext}"})
    rows.append({**rows[0], "doc_id": "iyi0000000000000", "sha256": "x", "rel_path": "iyi.pdf",
                 "low_quality": "", "dup_of": ""})
    with open(ws / "inventory.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return ws, src, ids


def _out(ws: Path, did: str, pages: list[str], **kw) -> None:
    d = ws / "work" / "transcribe" / did
    out = {"sayfalar": [{"sayfa": i + 1, "metin": t, "okunabilirlik": "orta"} for i, t in enumerate(pages)], **kw}
    (d / f"{did}.out.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")


def _inv(ws: Path) -> list[dict]:
    with open(ws / "inventory.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.mark.skipif(not HAS_PDFTOPPM, reason="pdftoppm yok")
def test_prepare_pages_and_package(tmp_path):
    ws, src, ids = _ws(tmp_path, {"pdf": (".pdf", OCR_TEXT, 2), "foto": (".png", OCR_TEXT, 1),
                                  "tif": (".tiff", OCR_TEXT, 1)})
    st = R.prepare(ws, all_low_quality=True, source=src)
    assert st["paket"] == 3 and st["yeni"] == 3 and st["bekleyen"] == 3 and not st["atlandi"]
    d = ws / "work" / "transcribe"
    pdf = d / ids["pdf"]
    assert sorted(p.name for p in pdf.glob("sayfa-*")) == ["sayfa-001.png", "sayfa-002.png"]
    assert (d / ids["foto"] / "sayfa-001.png").read_bytes() == (src / "alt" / "foto.png").read_bytes()
    assert (d / ids["tif"] / "sayfa-001.png").exists()
    pkg = json.loads((pdf / f"{ids['pdf']}.json").read_text(encoding="utf-8"))
    assert pkg["sayfalar"] == ["sayfa-001.png", "sayfa-002.png"]
    assert "[okunamadı]" in pkg["istem"] and "sayfa-002.png" in pkg["istem"]
    assert pkg["sema"]["required"] == ["sayfalar"]
    # yol/ad pakete girmez; iyi belge seçilmez
    blob = json.dumps(pkg, ensure_ascii=False)
    assert "alt/" not in blob and "pdf.pdf" not in blob
    assert not (d / "iyi0000000000000").exists()
    assert "Bekleyen paket: 3" in (d / "README.md").read_text(encoding="utf-8")
    # ikinci prepare: değişmeyen paket yeni sayılmaz, cevap korunur
    _out(ws, ids["foto"], [GOOD])
    st = R.prepare(ws, all_low_quality=True, source=src)
    assert st["yeni"] == 0 and (d / ids["foto"] / f"{ids['foto']}.out.json").exists()


def test_prepare_selection_and_skips(tmp_path):
    ws, src, ids = _ws(tmp_path, {"foto": (".png", OCR_TEXT, 1)})
    (src / "alt" / "foto.png").write_bytes(b"degisti")
    st = R.prepare(ws, only=[ids["foto"], "yok0000000000000"], source=src)
    assert st["atlandi"] == {ids["foto"]: "kaynak_degisti", "yok0000000000000": "envanterde_yok"}
    assert R.select(R.Workspace(ws), only=None, all_low_quality=False) == []


@pytest.mark.skipif(not HAS_PDFTOPPM, reason="pdftoppm yok")
def test_apply_replaces_text_and_invalidates(tmp_path):
    ws, src, ids = _ws(tmp_path, {"pdf": (".pdf", OCR_TEXT, 2)})
    did = ids["pdf"]
    write_jsonl(ws / "documents.jsonl", [{"doc_id": did, "doc_type": "x"}, {"doc_id": "baska"}])
    write_jsonl(ws / "candidates.jsonl", [{"doc_id": did, "adaylar": []}])
    write_jsonl(ws / "decisions.jsonl", [{"doc_id": did, "sema": 1, "durum": "ok", "karar": "kanit_degil"}])
    (ws / "work" / "coarse").mkdir(parents=True)
    (ws / "work" / "coarse" / f"{did}.json").write_text("{}")
    (ws / "work" / "coarse" / f"{did}.out.json").write_text("{}")
    R.prepare(ws, only=[did], source=src)
    _out(ws, did, [GOOD, "İmza: [okunamadı]"], notlar="2. sayfa yalnız imza")
    st = R.apply(ws, model="test:ajan")
    assert st["islenen"] == 1 and not st["gecersiz"] and not st["supheli"]
    assert st["tutarlilik"][did]["durum"] == "tutarli"
    text = (ws / "text" / f"{did}.txt").read_text(encoding="utf-8")
    assert text == GOOD + "\f" + "İmza: [okunamadı]" + "\n"
    assert (ws / "text_ocr" / f"{did}.txt").read_text(encoding="utf-8") == OCR_TEXT
    rows = [r for r in _inv(ws) if r["doc_id"] == did]
    assert len(rows) == 2 and all(r["method"] == "agent_vision" and r["low_quality"] == "" for r in rows)
    assert all(r["status"] == "ocr" and r["chars"] == str(len(text)) for r in rows)
    assert float(rows[0]["quality"]) > 0.5
    log = {r["doc_id"]: r for r in read_jsonl(ws / "transcribe.jsonl")}[did]
    assert log["model"] == "test:ajan" and log["onceki_envanter"]["method"] == "pdftotext+ocr(1/1)"
    assert log["okunabilirlik"] == ["orta", "orta"]
    # türetilmiş kayıtlar geçersiz
    assert [r["doc_id"] for r in read_jsonl(ws / "documents.jsonl")] == ["baska"]
    assert list(read_jsonl(ws / "candidates.jsonl")) == []
    dec = next(read_jsonl(ws / "decisions.jsonl"))
    assert dec["durum"] == "metin_degisti" and dec["onceki"]["karar"] == "kanit_degil"
    assert not (ws / "work" / "coarse" / f"{did}.json").exists()
    assert (ws / "work" / "coarse" / f"{did}.out.json.eski").exists()
    # aynı cevapla tekrar: değişmedi; tamamlandı sayılır, prepare yeniden paketlemez
    st = R.apply(ws)
    assert st["islenen"] == 0 and st["degismedi"] == 1
    assert R.prepare(ws, only=[did], source=src)["zaten_tamam"] == 1
    # düzeltilmiş cevap: OCR metni hâlâ ilk OCR (ajan metni değil)
    _out(ws, did, [GOOD + " Ek satır.", "İmza"])
    assert R.apply(ws)["islenen"] == 1
    assert (ws / "text_ocr" / f"{did}.txt").read_text(encoding="utf-8") == OCR_TEXT


@pytest.mark.skipif(not HAS_PDFTOPPM, reason="pdftoppm yok")
def test_apply_rejects_invalid(tmp_path):
    ws, src, ids = _ws(tmp_path, {"pdf": (".pdf", OCR_TEXT, 2)})
    did = ids["pdf"]
    R.prepare(ws, only=[did], source=src)
    d = ws / "work" / "transcribe" / did
    for bad in ('{"sayfalar": [{"sayfa": 1, "metin": "x"}]}',   # şema
                json.dumps({"sayfalar": [{"sayfa": 1, "metin": GOOD, "okunabilirlik": "iyi"}]}),  # sayfa eksik
                json.dumps({"sayfalar": [{"sayfa": i, "metin": "[okunamadı]", "okunabilirlik": "kotu"}
                                         for i in (1, 2)]})):
        (d / f"{did}.out.json").write_text(bad, encoding="utf-8")
        st = R.apply(ws)
        assert did in st["gecersiz"] and st["islenen"] == 0
        assert (ws / "text" / f"{did}.txt").read_text(encoding="utf-8") == OCR_TEXT
        assert did in (ws / "work" / "transcribe" / "GECERSIZ.md").read_text(encoding="utf-8")


def test_apply_suspicious_held_unless_accepted(tmp_path):
    ws, src, ids = _ws(tmp_path, {"foto": (".png", OCR_TEXT, 1)})
    did = ids["foto"]
    R.prepare(ws, only=[did], source=src)
    _out(ws, did, [FAKE])
    st = R.apply(ws)
    assert did in st["supheli"] and st["islenen"] == 0
    assert (ws / "text" / f"{did}.txt").read_text(encoding="utf-8") == OCR_TEXT
    assert "şüpheli" in (ws / "work" / "transcribe" / "GECERSIZ.md").read_text(encoding="utf-8")
    st = R.apply(ws, accept_suspicious=True)
    assert st["islenen"] == 1
    log = next(read_jsonl(ws / "transcribe.jsonl"))
    assert log["supheli_kabul"] is True and log["tutarlilik"]["durum"] == "supheli"


def test_consistency():
    c = R.consistency(OCR_TEXT, GOOD)
    assert c["durum"] == "tutarli" and c["oran"] >= 0.8 and c["okunamadi"] == 1
    assert R.consistency(OCR_TEXT, FAKE)["durum"] == "supheli"
    # OCR çöpse yargı yok
    assert R.consistency("K@r#r ~~ ll1 xq ;;", FAKE)["durum"] == "karsilastirilamadi"
    # çöp belirteç çapa sayılmaz
    assert R.consistency("xqzwv brrrt 12", "x")["capa_sozcuk"] == 0


def test_check_and_cli(tmp_path, capsys):
    from bidr.cli import main
    from bidr.common import Workspace
    from bidr.pipeline.checks import Ctx
    from bidr.transcribe.check import transcribe_tamam

    ws, src, ids = _ws(tmp_path, {"foto": (".png", OCR_TEXT, 1)})
    did = ids["foto"]
    ctx = Ctx(Workspace(ws), {}, lambda s: s, {})
    assert transcribe_tamam(ctx).kim == "komut"
    assert main(["transcribe", "prepare", "-w", str(ws)]) == 2
    assert main(["transcribe", "prepare", "-w", str(ws), "--all-low-quality", "--source", str(src)]) == 0
    assert transcribe_tamam(ctx).kim == "ajan"
    _out(ws, did, [GOOD])
    assert main(["transcribe", "apply", "-w", str(ws), "--model", "t"]) == 0
    ck = transcribe_tamam(ctx)
    assert ck.bitti and ck.ilerleme["yaziya_gecirilen"] == 1
    assert "tutarli" in capsys.readouterr().out


def test_apply_photo_without_text(tmp_path):
    ws, src, ids = _ws(tmp_path, {"foto": (".png", "x7 ;; ~", 1)})
    did = ids["foto"]
    R.prepare(ws, only=[did], source=src)
    d = ws / "work" / "transcribe" / did
    (d / f"{did}.out.json").write_text(json.dumps(
        {"sayfalar": [{"sayfa": 1, "metin": "", "okunabilirlik": "bos"}], "notlar": "fotoğraf"}))
    st = R.apply(ws)
    assert st["islenen"] == 1
    assert (ws / "text" / f"{did}.txt").read_text(encoding="utf-8") == ""
    assert next(read_jsonl(ws / "transcribe.jsonl"))["metin_yok"] is True
