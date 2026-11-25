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
    """Her ret bir deneme: cevap kenara alınır (paket yeniden cevapsız), metin değişmez; nedeni ne olursa
    olsun DENEME_SINIRI'nda belge elle bakılmalı olur."""
    ws, src, ids = _ws(tmp_path, {"pdf": (".pdf", OCR_TEXT, 2)})
    did = ids["pdf"]
    R.prepare(ws, only=[did], source=src)
    d = ws / "work" / "transcribe" / did
    for n, bad in enumerate(('{"sayfalar": [{"sayfa": 1, "metin": "x"}]}',   # şema
                             json.dumps({"sayfalar": [{"sayfa": 1, "metin": GOOD, "okunabilirlik": "iyi"}]})), 1):
        (d / f"{did}.out.json").write_text(bad, encoding="utf-8")
        st = R.apply(ws)
        assert did in st["gecersiz"] and st["islenen"] == 0 and st["yeniden"][did]["deneme"] == n
        assert not (d / f"{did}.out.json").exists() and (d / f"{did}.out.json.red{n}.eski").read_text() == bad
        assert (ws / "text" / f"{did}.txt").read_text(encoding="utf-8") == OCR_TEXT
        assert did in (ws / "work" / "transcribe" / "GECERSIZ.md").read_text(encoding="utf-8")
    # cevap beklerken apply: gerekçe GECERSIZ.md'de kalır
    st = R.apply(ws)
    assert st["bekleyen"] == [did] and "önceki deneme" in (ws / "work/transcribe/GECERSIZ.md").read_text()
    # hepsi [okunamadı] → normalleşir (bos) ama OCR'da sağlıklı sözcükler var: şüpheli, üçüncü ret → elle
    (d / f"{did}.out.json").write_text(json.dumps(
        {"sayfalar": [{"sayfa": i, "metin": "[okunamadı]", "okunabilirlik": "kotu"} for i in (1, 2)]}))
    st = R.apply(ws)
    assert st["elle_bakilmali"][did]["neden"] == "supheli" and not st["gecersiz"] and not st["supheli"]
    assert (d / f"{did}.out.json").exists()                      # son cevap yerinde (kabul edilebilir)
    assert (ws / "text" / f"{did}.txt").read_text(encoding="utf-8") == OCR_TEXT
    assert not (ws / "work/transcribe/GECERSIZ.md").exists()
    assert did in (ws / "work/transcribe" / R.ELLE_MD).read_text(encoding="utf-8")
    log = next(read_jsonl(ws / "transcribe.jsonl"))
    assert log["durum"] == R.ELLE and log["deneme"] == 3


def test_all_unreadable_normalized_to_empty(tmp_path):
    """Metni olmayan görsel (OCR çöp): model her yere [okunamadı] yazmış → bos, metin boş; reddedilmez."""
    ws, src, ids = _ws(tmp_path, {"foto": (".png", "x7 ;; ~", 1)})
    did = ids["foto"]
    R.prepare(ws, only=[did], source=src)
    (ws / "work/transcribe" / did / f"{did}.out.json").write_text(json.dumps(
        {"sayfalar": [{"sayfa": 1, "metin": " [okunamadı] ", "okunabilirlik": "kotu"}], "notlar": "fotoğraf"}))
    st = R.apply(ws)
    assert st["islenen"] == 1 and not st["gecersiz"] and st["normallestirilen"] == [did]
    assert (ws / "text" / f"{did}.txt").read_text(encoding="utf-8") == ""
    log = next(read_jsonl(ws / "transcribe.jsonl"))
    assert log["metin_yok"] is True and log["okunabilirlik"] == ["bos"]
    assert log["normallestirme"] == "hepsi_okunamadi→bos"
    out = {"sayfalar": [{"sayfa": 1, "metin": "Karar [okunamadı]", "okunabilirlik": "kotu"},
                        {"sayfa": 2, "metin": "[okunamadı]", "okunabilirlik": "kotu"}]}
    assert R.normalize_no_text(out) is False and out["sayfalar"][1]["metin"] == "[okunamadı]"


@pytest.mark.skipif(not HAS_PDFTOPPM, reason="pdftoppm yok")
def test_partial_unreadable_kept(tmp_path):
    ws, src, ids = _ws(tmp_path, {"pdf": (".pdf", OCR_TEXT, 2)})
    did = ids["pdf"]
    R.prepare(ws, only=[did], source=src)
    (ws / "work/transcribe" / did / f"{did}.out.json").write_text(json.dumps(
        {"sayfalar": [{"sayfa": 1, "metin": GOOD, "okunabilirlik": "orta"},
                      {"sayfa": 2, "metin": "[okunamadı]", "okunabilirlik": "kotu"}]}, ensure_ascii=False))
    st = R.apply(ws)
    assert st["islenen"] == 1 and not st["normallestirilen"]
    assert (ws / "text" / f"{did}.txt").read_text(encoding="utf-8") == GOOD + "\f[okunamadı]\n"
    assert next(read_jsonl(ws / "transcribe.jsonl"))["okunabilirlik"] == ["orta", "kotu"]


def test_page_notes_allowed_required_fields_still_checked(tmp_path):
    ws, src, ids = _ws(tmp_path, {"foto": (".png", OCR_TEXT, 1)})
    did = ids["foto"]
    R.prepare(ws, only=[did], source=src)
    d = ws / "work/transcribe" / did
    (d / f"{did}.out.json").write_text(json.dumps(   # zorunlu alan eksik: yine geçersiz
        {"sayfalar": [{"sayfa": 1, "metin": GOOD, "notlar": "eğik taranmış"}]}, ensure_ascii=False))
    assert did in R.apply(ws)["gecersiz"]
    from bidr.llm import validate_output                       # şemada olmayan başka alan: geçersiz
    assert validate_output(R.TASK, {"sayfalar": [{"sayfa": 1, "metin": "a", "okunabilirlik": "iyi",
                                                  "guven": 0.9}]})[0] is None
    (d / f"{did}.out.json").write_text(json.dumps(
        {"sayfalar": [{"sayfa": 1, "metin": GOOD, "okunabilirlik": "orta", "notlar": "eğik taranmış"}]},
        ensure_ascii=False))
    st = R.apply(ws)
    assert st["islenen"] == 1 and not st["gecersiz"]
    log = next(read_jsonl(ws / "transcribe.jsonl"))
    assert log["sayfa_notlari"] == {"1": "eğik taranmış"} and log["onceki_red"] == 1
    assert "eğik" not in (ws / "text" / f"{did}.txt").read_text(encoding="utf-8")
    assert not (d.parent / R.DENEMELER).exists()                 # başarıyla kapanan denemeler silinir


def test_same_reason_twice_is_manual_and_does_not_block(tmp_path, capsys):
    """Aynı belge iki denemede de aynı nedenle (şüpheli) reddedilir → elle bakılmalı; aşama biter, next
    aynı cevabı yeniden istemez, apply çıkış 0."""
    from bidr.cli import main
    from bidr.common import Workspace
    from bidr.pipeline.checks import Ctx
    from bidr.pipeline.state import stage
    from bidr.transcribe.check import transcribe_tamam

    ws, src, ids = _ws(tmp_path, {"foto": (".png", OCR_TEXT, 1), "iyi": (".png", OCR_TEXT, 1)})
    did, ok = ids["foto"], ids["iyi"]
    ctx = Ctx(Workspace(ws), {}, lambda s: s, stage("transcribe"))
    R.prepare(ws, all_low_quality=True, source=src)
    _out(ws, did, [FAKE])
    _out(ws, ok, [GOOD])
    ck = transcribe_tamam(ctx)
    assert ck.kim == "komut" and len(ck.komutlar) == 1 and "apply" in ck.komutlar[0]   # prepare değil
    assert main(["transcribe", "apply", "-w", str(ws)]) == 1
    ck = transcribe_tamam(ctx)
    assert ck.kim == "ajan" and ck.bekleyen == [did] and "reddedildi" in ck.neden
    assert any("apply" in k for k in ck.komutlar)
    _out(ws, did, [FAKE])                                         # model aynısını yine yazdı
    capsys.readouterr()
    assert main(["transcribe", "apply", "-w", str(ws)]) == 0
    assert "elle bakılmalı" in capsys.readouterr().out
    ck = transcribe_tamam(ctx)
    assert ck.bitti and ck.ilerleme["elle_bakilmali"] == 1 and ck.ilerleme["yaziya_gecirilen"] == 1
    assert any(R.ELLE_MD in u for u in ck.uyarilar)
    # tekrar apply / next: iş yok, döngü yok
    for _ in range(3):
        assert main(["transcribe", "apply", "-w", str(ws)]) == 0
        assert transcribe_tamam(ctx).bitti
    assert (ws / "text" / f"{did}.txt").read_text(encoding="utf-8") == OCR_TEXT
    # komisyon/insan sonradan kabul edebilir
    assert main(["transcribe", "apply", "-w", str(ws), "--kabul-supheli", "--only", did]) == 0
    log = {r["doc_id"]: r for r in read_jsonl(ws / "transcribe.jsonl")}
    assert log[did]["durum"] == "uygulandi" and log[did]["supheli_kabul"] is True
    assert not (ws / "work/transcribe" / R.ELLE_MD).exists()


def test_rejected_answer_not_restored_by_split_guard(tmp_path):
    """Kenara alınan cevap parça bildiriminde 'önceden var olan' cevapsa sonraki denetim onu geri koymaz."""
    from bidr.pipeline import paralel as PR
    ws, src, ids = _ws(tmp_path, {"foto": (".png", OCR_TEXT, 1)})
    did = ids["foto"]
    R.prepare(ws, only=[did], source=src)
    _out(ws, did, [FAKE])
    d = ws / "work/transcribe"
    pd = d / PR.PARCA
    (pd / "yedek").mkdir(parents=True)
    shutil.copy2(d / did / f"{did}.out.json", pd / "yedek" / f"{did}.out.json")
    info = PR.bilgi("transcribe")
    man = {"surum": 1, "asama": "transcribe", "dizin": info["dizin"], "duzen": info["duzen"], "parcalar": [],
           "paket_izi": PR.paket_izi(R.Workspace(ws), info),
           "onceki": {did: PR._sha(d / did / f"{did}.out.json")}}
    (pd / PR.BILDIRIM).write_text(json.dumps(man), encoding="utf-8")
    assert did in R.apply(ws)["supheli"]
    assert PR.apply_oncesi(ws, "work/transcribe") == 0
    assert not (d / did / f"{did}.out.json").exists()
    _out(ws, did, [GOOD])                                         # yeniden yazılan cevap liste dışı sayılmaz
    assert PR.apply_oncesi(ws, "work/transcribe") == 0
    assert R.apply(ws)["islenen"] == 1


def test_prepare_keeps_answer_when_only_prompt_text_changed(tmp_path):
    """Talimat metni değişti, görüntüler aynı: verilmiş cevap korunur (yeniden model çağrısı yok); apply
    reddederse paket bugünkü talimatla yenilenir."""
    ws, src, ids = _ws(tmp_path, {"foto": (".png", OCR_TEXT, 1)})
    did = ids["foto"]
    R.prepare(ws, only=[did], source=src)
    d = ws / "work/transcribe" / did
    pkgp = d / f"{did}.json"
    pkg = json.loads(pkgp.read_text(encoding="utf-8"))
    img = R._gorsel_sha(d, pkg["sayfalar"])
    old = pkg["istem"].replace("Başka alan ekleme.", "")         # eski sürüm talimat
    pkg.update(istem=old, istem_sha=R._sha(old + img)[:16])
    pkgp.write_text(json.dumps(pkg, ensure_ascii=False), encoding="utf-8")
    _out(ws, did, [FAKE])
    st = R.prepare(ws, only=[did], source=src)
    assert st["yeni"] == 0 and st["cevap_korundu"] == 1 and (d / f"{did}.out.json").exists()
    assert json.loads(pkgp.read_text(encoding="utf-8"))["istem"] == old
    assert did in R.apply(ws)["supheli"]                           # ret: paket güncel talimatla yenilenir
    new = json.loads(pkgp.read_text(encoding="utf-8"))
    assert "Başka alan ekleme." in new["istem"] and new["istem_sha"] == R._sha(new["istem"] + img)[:16]
    # görüntü değişirse eski cevap korunmaz (eski davranış)
    _out(ws, did, [GOOD])
    pkg = json.loads(pkgp.read_text(encoding="utf-8"))
    pkg.update(istem=old, istem_sha=R._sha(old + "baska")[:16])
    pkgp.write_text(json.dumps(pkg, ensure_ascii=False), encoding="utf-8")
    assert R.prepare(ws, only=[did], source=src)["yeni"] == 1
    assert (d / f"{did}.out.json.eski").exists() and not (d / f"{did}.out.json").exists()


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


def test_apply_exit_code_explained(tmp_path, capsys):
    """apply çıkış 1 = geçersiz ya da şüpheli cevap var; çıktı nedenini söyler (kör test)."""
    from bidr.cli import main
    ws, src, ids = _ws(tmp_path, {"foto": (".png", OCR_TEXT, 1)})
    did = ids["foto"]
    R.prepare(ws, only=[did], source=src)
    _out(ws, did, [FAKE])
    capsys.readouterr()
    assert main(["transcribe", "apply", "-w", str(ws)]) == 1
    out = capsys.readouterr().out
    assert "çıkış 1: 0 geçersiz, 1 şüpheli" in out and "--kabul-supheli" in out
    assert main(["transcribe", "apply", "-w", str(ws), "--kabul-supheli"]) == 0
    assert "çıkış 1" not in capsys.readouterr().out


# -- belirsiz turu (aşama belirsiz_okuma) -------------------------------------------------------

def _fine(did: str, rel: str = "belirsiz") -> dict:
    return {"doc_id": did, "sema": 1, "durum": "ok", "asama": "ince", "kaba": {"karar": "olcut_var"},
            "ince": {"karar": "olcut_var", "birim_iliskisi": rel, "birim_iliskisi_kaynagi": "model"},
            "eslesmeler": [], "olcutler": []}


def _set_inv(ws: Path, did: str, **kw) -> None:
    rows = _inv(ws)
    for r in rows:
        if r["doc_id"] == did:
            r.update({k: str(v) for k, v in kw.items()})
    with open(ws / "inventory.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def _bctx(ws: Path):
    from bidr.common import Workspace
    from bidr.pipeline.checks import Ctx
    from bidr.pipeline.state import stage
    return Ctx(Workspace(ws), {}, lambda s: s, stage("belirsiz_okuma"))


def test_belirsiz_selection(tmp_path):
    names = ["aday", "metinli", "kendi", "insan", "uzun", "duskal", "okundu"]
    ws, src, ids = _ws(tmp_path, {n: (".png", OCR_TEXT, 1) for n in names})
    _set_inv(ws, ids["metinli"], method="pdftotext", low_quality="")    # metin katmanı: OCR değil
    _set_inv(ws, ids["uzun"], pages=55)
    _set_inv(ws, ids["duskal"], method="docx-xml", low_quality="1", ext=".docx")   # çevrilemez biçim
    _set_inv(ws, ids["aday"], low_quality="")                              # yalnız method'da ocr
    write_jsonl(ws / "decisions.jsonl", [_fine(ids[n], "kendi" if n == "kendi" else "belirsiz") for n in names])
    write_jsonl(ws / "birim-kararlari.jsonl", [{"doc_id": ids["insan"], "birim_iliskisi": "kendi"}])
    write_jsonl(ws / "transcribe.jsonl", [{"doc_id": ids["okundu"], "durum": "uygulandi"}])
    sel, info = R.select_belirsiz(R.Workspace(ws))
    assert sel == [ids["aday"]]
    assert info == {"belirsiz": 6, "insan_karari": 1, "ocr_degil": 1, "bicim": 1, "cok_sayfa": 1,
                    "okundu": 1, "paketlenemedi": 0, "envanterde_yok": 0}
    # karar yoksa aday yok; aşama kendiliğinden biter
    (ws / "decisions.jsonl").unlink()
    assert R.select_belirsiz(R.Workspace(ws))[0] == []
    from bidr.transcribe.check import belirsiz_okuma_tamam
    ck = belirsiz_okuma_tamam(_bctx(ws))
    assert ck.bitti and "aday yok" in ck.neden


def test_belirsiz_round_reread_redecide_once(tmp_path):
    from bidr.transcribe.check import belirsiz_okuma_tamam
    ws, src, ids = _ws(tmp_path, {"foto": (".png", OCR_TEXT, 1), "diger": (".png", OCR_TEXT, 1)})
    did = ids["foto"]
    write_jsonl(ws / "documents.jsonl", [{"doc_id": did}, {"doc_id": ids["diger"]}])
    write_jsonl(ws / "decisions.jsonl", [_fine(did), _fine(ids["diger"], "kendi")])
    ctx = _bctx(ws)
    ck = belirsiz_okuma_tamam(ctx)
    assert ck.kim == "komut" and "--belirsiz" in ck.komutlar[0] and ck.ilerleme["aday"] == 1
    st = R.prepare(ws, belirsiz=True, source=src)
    assert st["paket"] == 1 and st["secim"]["aday"] == 1
    d = ws / "work" / "transcribe"
    assert json.loads((d / did / f"{did}.json").read_text(encoding="utf-8"))["tur"] == "belirsiz"
    assert not (d / ids["diger"]).exists()
    assert belirsiz_okuma_tamam(ctx).kim == "ajan"
    _out(ws, did, [GOOD])
    assert belirsiz_okuma_tamam(ctx).kim == "komut"
    st = R.apply(ws, model="t")
    assert st["degisen"] == [did] and not st["metin_ayni"]
    log = {r["doc_id"]: r for r in read_jsonl(ws / "transcribe.jsonl")}
    assert log[did]["tur"] == "belirsiz"
    dec = {r["doc_id"]: r for r in read_jsonl(ws / "decisions.jsonl")}
    assert dec[did]["durum"] == "metin_degisti" and dec[ids["diger"]]["durum"] == "ok"
    assert [r["doc_id"] for r in read_jsonl(ws / "documents.jsonl")] == [ids["diger"]]
    # yeniden ince karar yine belirsiz dedi: belge ikinci tura girmez, komisyona gider
    write_jsonl(ws / "decisions.jsonl", [_fine(did), _fine(ids["diger"], "kendi")])
    sel, info = R.select_belirsiz(R.Workspace(ws))
    assert sel == [] and info["okundu"] == 1
    ck = belirsiz_okuma_tamam(ctx)
    assert ck.bitti and ck.ilerleme["hala_belirsiz"] == 1 and ck.ilerleme["yeniden_okunan"] == 1
    assert any("komisyon" in u for u in ck.uyarilar)
    assert R.prepare(ws, belirsiz=True, source=src)["paket"] == 0


def test_belirsiz_same_text_keeps_decision(tmp_path):
    from bidr.transcribe.check import belirsiz_okuma_tamam
    ws, src, ids = _ws(tmp_path, {"foto": (".png", OCR_TEXT, 1)})
    did = ids["foto"]
    write_jsonl(ws / "documents.jsonl", [{"doc_id": did}])
    write_jsonl(ws / "decisions.jsonl", [_fine(did)])
    R.prepare(ws, belirsiz=True, source=src)
    _out(ws, did, ["  " + OCR_TEXT.replace("\n", "\n\n") + "  "])   # yalnız boşluk farkı
    before = (ws / "decisions.jsonl").read_text(encoding="utf-8")
    st = R.apply(ws, model="t", accept_suspicious=True)
    assert st["metin_ayni"] == [did] and st["degisen"] == []
    assert (ws / "decisions.jsonl").read_text(encoding="utf-8") == before
    assert (ws / "text" / f"{did}.txt").read_text(encoding="utf-8") == OCR_TEXT
    assert [r["doc_id"] for r in read_jsonl(ws / "documents.jsonl")] == [did]
    log = next(read_jsonl(ws / "transcribe.jsonl"))
    assert log["metin_ayni"] is True and log["tur"] == "belirsiz"
    assert R.is_done(R.Workspace(ws), did, {did: log})
    assert R.apply(ws)["degismedi"] == 1                          # tekrar apply: iş yok
    ck = belirsiz_okuma_tamam(_bctx(ws))
    assert ck.bitti and ck.ilerleme["metin_ayni"] == 1 and ck.ilerleme["hala_belirsiz"] == 1


def test_belirsiz_unpackable_is_not_waited(tmp_path, capsys):
    from bidr.cli import main
    from bidr.transcribe.check import belirsiz_okuma_tamam
    ws, src, ids = _ws(tmp_path, {"foto": (".png", OCR_TEXT, 1)})
    did = ids["foto"]
    write_jsonl(ws / "decisions.jsonl", [_fine(did)])
    (src / "alt" / "foto.png").unlink()
    assert main(["transcribe", "prepare", "-w", str(ws), "--belirsiz", "--only", did]) == 2
    assert main(["transcribe", "prepare", "-w", str(ws), "--belirsiz", "--source", str(src)]) == 0
    assert "aday 1" in capsys.readouterr().out
    assert json.loads((ws / "work" / "transcribe" / "belirsiz.json").read_text(encoding="utf-8"))["atlandi"] \
        == {did: "kaynak_dosya_yok"}
    sel, info = R.select_belirsiz(R.Workspace(ws))
    assert sel == [] and info["paketlenemedi"] == 1
    ck = belirsiz_okuma_tamam(_bctx(ws))
    assert ck.bitti and ck.ilerleme["paketlenemeyen"] == 1 and any("belirsiz.json" in u for u in ck.uyarilar)
