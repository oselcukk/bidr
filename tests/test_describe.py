"""describe: sentetik fotoğraf/PDF/docx ile seçim → prepare → (sahte ajan) .out.json → apply."""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from bidr.common import read_jsonl, sha256_file, write_jsonl
from bidr.describe import run as R
from bidr.pipeline.checks import Ctx

HAS_POPPLER = bool(shutil.which("pdftoppm") and shutil.which("pdfimages"))

GARBAGE = "© — =\n7 a A ——— os\n— = r"
RICH = ("Bölüm kurulu toplantısında müfredat güncellemesi görüşülmüştür. " * 8).strip()
# seyrek ama karşılaştırılabilir OCR (≥6 çapa sözcük, <30 sağlıklı sözcük)
POSTER_OCR = "KARİYER GÜNLERİ\nöğrenci topluluğu etkinliği\nkonferans salonunda saat 14.00 ~~ #@"


def _photo(seed: int = 0) -> Image.Image:
    img = Image.new("RGB", (640, 480), (200 - seed, 210, 220))
    dr = ImageDraw.Draw(img)
    for i in range(6):
        dr.rectangle((40 + 95 * i, 200, 110 + 95 * i, 300), fill=(60, 60 + 20 * i, 90))
    return img


def _docx(path: Path, body: str, img: Image.Image) -> None:
    import io
    buf = io.BytesIO()
    img.save(buf, "PNG")
    xml = ('<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/'
           f'wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>{body}</w:t></w:r></w:p></w:body></w:document>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", xml)
        z.writestr("word/media/image1.png", buf.getvalue())
        z.writestr("word/media/logo.png", _tiny())


def _tiny() -> bytes:
    import io
    b = io.BytesIO()
    Image.new("RGB", (40, 40), "red").save(b, "PNG")
    return b.getvalue()


def _ws(tmp: Path, docs: dict[str, tuple[str, str, int]]) -> tuple[Path, Path, dict[str, str]]:
    """docs: ad -> (uzantı, mevcut metin (PDF'te sayfalar \\f ile), sayfa). Kaynak + inventory yazar."""
    src, ws = tmp / "kaynak", tmp / "ws"
    (ws / "text").mkdir(parents=True)
    (src / "alt").mkdir(parents=True)
    rows, ids = [], {}
    for k, (name, (ext, text, pages)) in enumerate(docs.items()):
        p = src / "alt" / f"{name}{ext}"
        if ext == ".pdf":
            imgs = [_photo(k + i) for i in range(pages)]
            imgs[0].save(p, "PDF", resolution=72, save_all=True, append_images=imgs[1:])
        elif ext == ".docx":
            _docx(p, text, _photo(k))
        else:
            _photo(k).save(p)
        sha = sha256_file(p)
        did = sha[:16]
        ids[name] = did
        (ws / "text" / f"{did}.txt").write_text(text, encoding="utf-8")
        rows.append({"doc_id": did, "sha256": sha, "rel_path": f"alt/{name}{ext}", "ext": ext, "size": 1,
                     "pages": pages, "chars": len(text), "method": "ocr", "status": "ocr", "dup_of": "",
                     "error": "", "ocr_conf": 30.0, "quality": 0.1, "low_quality": 1, "images_ocr": "",
                     "images_lowq": ""})
    with open(ws / "inventory.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return ws, src, ids


def _item(k: int = 1, **kw) -> dict:
    it = {"gorsel": k, "icerik": "fotograf", "sahne": "bilgisayar laboratuvarı (iç mekân)",
          "etkinlik": "", "kalabalik": "yok",
          "nesneler": [{"ad": "masaüstü bilgisayar", "yaklasik_sayi": 30}, {"ad": "projeksiyon perdesi",
                                                                          "yaklasik_sayi": 1}],
          "gorunen_yazilar": [{"yer": "tabela", "metin": "BİLGİSAYAR LABORATUVARI"}],
          "betimleme": "Sıralar halinde yaklaşık 30 masaüstü bilgisayarın bulunduğu bir laboratuvar; "
                       "önde bir projeksiyon perdesi var."}
    it.update(kw)
    return it


def _out(ws: Path, did: str, items: list[dict], **kw) -> None:
    d = ws / "work" / "describe" / did
    (d / f"{did}.out.json").write_text(json.dumps({"gorseller": items, **kw}, ensure_ascii=False),
                                       encoding="utf-8")


def _check(ws: Path, src: Path):
    from bidr.common import Workspace
    from bidr.describe.check import describe_tamam
    from bidr.pipeline.state import stage
    return describe_tamam(Ctx(Workspace(ws), {"kaynak": str(src)}, lambda s: s.replace("{ws}", str(ws))
                              .replace("{ajan}", "test"), stage("describe")))


def test_sparse_rule():
    assert R.sparse(GARBAGE) and R.sparse("") and R.sparse(POSTER_OCR)
    assert not R.sparse(RICH)
    assert R.healthy_words(RICH) >= 30 and R.healthy_words(GARBAGE) == 0


@pytest.mark.skipif(not HAS_POPPLER, reason="poppler yok")
def test_auto_selection(tmp_path):
    ws, src, ids = _ws(tmp_path, {"foto": (".png", GARBAGE, 1), "tarama": (".jpg", RICH, 1),
                                  "karma": (".pdf", RICH + "\f" + GARBAGE, 2),
                                  "metinpdf": (".pdf", RICH, 1),
                                  "albüm": (".docx", "Etkinlik fotoğrafları", 1),
                                  "rapor": (".docx", RICH, 1)})
    sel = R.select_auto(R.Workspace(ws), src)
    # metni seyrek görsel → seçilir; metni bol görsel (transcribe'ın işi) seçilmez
    assert ids["foto"] in sel and ids["tarama"] not in sel
    # PDF: yalnız seyrek + görsel ağırlıklı sayfa
    assert sel[ids["karma"]] == {"tur": "pdf", "sayfalar": [2]}
    assert ids["metinpdf"] not in sel
    # docx: gövdesi seyrek → büyük gömülü görsel (logo atlanır); gövdesi bol → seçilmez
    assert sel[ids["albüm"]] == {"tur": "docx", "sayfalar": [1]} and ids["rapor"] not in sel


@pytest.mark.skipif(not HAS_POPPLER, reason="poppler yok")
def test_prepare_package(tmp_path):
    ws, src, ids = _ws(tmp_path, {"foto": (".png", GARBAGE, 1), "karma": (".pdf", RICH + "\f" + GARBAGE, 2),
                                  "albüm": (".docx", "Fotoğraflar", 1)})
    st = R.prepare(ws, auto=True, source=src)
    assert st["secilen"] == 3 and st["paket"] == 3 and st["yeni"] == 3 and not st["atlandi"]
    d = ws / "work" / "describe"
    pkg = json.loads((d / ids["karma"] / f"{ids['karma']}.json").read_text(encoding="utf-8"))
    assert pkg["tur"] == "pdf" and pkg["sayfalar"] == [2] and pkg["gorseller"] == ["gorsel-001.png"]
    assert "KVKK" in pkg["istem"] and "sayfa 2" in pkg["istem"]
    blob = json.dumps(pkg, ensure_ascii=False)
    assert "alt/" not in blob and "karma" not in blob
    assert (d / ids["foto"] / "gorsel-001.png").exists() and (d / ids["albüm"] / "gorsel-001.png").exists()
    assert "Bekleyen paket: 3" in (d / "README.md").read_text(encoding="utf-8")
    _out(ws, ids["foto"], [_item()])
    assert R.prepare(ws, auto=True, source=src)["yeni"] == 0
    assert (d / ids["foto"] / f"{ids['foto']}.out.json").exists()


def test_apply_writes_marked_description_and_invalidates(tmp_path):
    ws, src, ids = _ws(tmp_path, {"foto": (".png", GARBAGE, 1)})
    did = ids["foto"]
    write_jsonl(ws / "documents.jsonl", [{"doc_id": did, "doc_type": "x"}, {"doc_id": "baska"}])
    write_jsonl(ws / "candidates.jsonl", [{"doc_id": did, "adaylar": []}])
    write_jsonl(ws / "decisions.jsonl", [{"doc_id": did, "sema": 1, "durum": "ok", "karar": "kanit_degil"}])
    (ws / "work" / "fine").mkdir(parents=True)
    (ws / "work" / "fine" / f"{did}.json").write_text("{}")
    R.prepare(ws, only=[did], source=src)
    _out(ws, did, [_item()])
    st = R.apply(ws, model="test:ajan")
    assert st["islenen"] == 1 and not st["gecersiz"] and not st["supheli"]
    text = (ws / "text" / f"{did}.txt").read_text(encoding="utf-8")
    assert text.startswith("[GÖRSEL BETİMLEME") and "belgenin kendi yazısı DEĞİLDİR" in text
    assert 'Görünen yazı (tabela): "BİLGİSAYAR LABORATUVARI"' in text
    assert "masaüstü bilgisayar (~30)" in text and GARBAGE.split()[1] not in text   # OCR çöpü atıldı
    assert (ws / "text_ocr" / f"{did}.txt").read_text(encoding="utf-8") == GARBAGE
    assert (ws / "text_pre_describe" / f"{did}.txt").read_text(encoding="utf-8") == GARBAGE
    row = next(r for r in csv.DictReader(open(ws / "inventory.csv", encoding="utf-8")) if r["doc_id"] == did)
    assert row["method"] == "agent_describe" and row["low_quality"] == "" and row["chars"] == str(len(text))
    log = next(read_jsonl(ws / "describe.jsonl"))
    assert log["durum"] == "uygulandi" and log["model"] == "test:ajan" and log["betimlenen"] == [1]
    # türetilmiş kayıtlar geçersiz
    assert [r["doc_id"] for r in read_jsonl(ws / "documents.jsonl")] == ["baska"]
    assert list(read_jsonl(ws / "candidates.jsonl")) == []
    assert next(read_jsonl(ws / "decisions.jsonl"))["durum"] == "metin_degisti"
    assert (ws / "work" / "fine" / f"{did}.json.eski").exists()
    # decide'ın alıntı denetimi betimleme metnine karşı çalışır
    from bidr.llm import verify_quote
    assert verify_quote("yaklaşık 30 masaüstü bilgisayarın bulunduğu bir laboratuvar", text).ok
    assert not verify_quote("yaklaşık 45 masaüstü bilgisayarın bulunduğu bir laboratuvar", text).ok
    # identify bu metni okur
    from bidr.identify.pipeline import run as identify
    recs = identify(ws, write_report=False, log=lambda m: None)
    assert any(r["doc_id"] == did for r in recs)
    # aynı cevap: değişmedi; yeniden apply taban metni (OCR) kullanır, betimlemeyi iki kez sarmaz
    assert R.apply(ws)["degismedi"] == 1
    _out(ws, did, [_item(betimleme="Yaklaşık 30 bilgisayarlı bir laboratuvar.")])
    assert R.apply(ws)["islenen"] == 1
    text = (ws / "text" / f"{did}.txt").read_text(encoding="utf-8")
    assert text.count("[GÖRSEL BETİMLEME") == 1 and "Yaklaşık 30 bilgisayarlı" in text
    assert (ws / "text_ocr" / f"{did}.txt").read_text(encoding="utf-8") == GARBAGE


@pytest.mark.parametrize("bad, msg", [
    (_item(betimleme="Gözlüklü bir erkek konuşmacı kürsüde."), "KVKK"),
    (_item(nesneler=[{"ad": "takım elbiseli katılımcı", "yaklasik_sayi": 3}]), "KVKK"),
    (_item(etkinlik="2024 mezuniyet töreni"), "2024"),
    (_item(betimleme="12.05.2023 tarihli seminer."), "12.05.2023"),
])
def test_apply_rejects_person_and_inference(tmp_path, bad, msg):
    ws, src, ids = _ws(tmp_path, {"foto": (".png", GARBAGE, 1)})
    did = ids["foto"]
    R.prepare(ws, only=[did], source=src)
    _out(ws, did, [bad])
    st = R.apply(ws)
    assert did in st["gecersiz"] and msg in "; ".join(st["gecersiz"][did])
    assert (ws / "text" / f"{did}.txt").read_text(encoding="utf-8") == GARBAGE
    assert did in (ws / "work" / "describe" / "GECERSIZ.md").read_text(encoding="utf-8")


def test_year_allowed_when_visible(tmp_path):
    ws, src, ids = _ws(tmp_path, {"foto": (".png", GARBAGE, 1)})
    did = ids["foto"]
    R.prepare(ws, only=[did], source=src)
    _out(ws, did, [_item(etkinlik="mezuniyet töreni", betimleme="Sahnede 2024 yazılı pankart var.",
                         gorunen_yazilar=[{"yer": "pankart", "metin": "MEZUNİYET 2024"}]),
                   ], notlar="")
    assert R.apply(ws)["islenen"] == 1


def test_wrong_count_and_text_page(tmp_path):
    ws, src, ids = _ws(tmp_path, {"foto": (".png", GARBAGE, 1)})
    did = ids["foto"]
    R.prepare(ws, only=[did], source=src)
    _out(ws, did, [_item(1), _item(2)])
    assert did in R.apply(ws)["gecersiz"]
    # ajan: aslında metin sayfası → betimlenmez, metin değişmez, transcribe önerilir
    _out(ws, did, [_item(icerik="belge_sayfasi", betimleme="Tutanak sayfası.")])
    st = R.apply(ws)
    assert st["metin_belgesi"] == [did] and st["islenen"] == 0
    assert (ws / "text" / f"{did}.txt").read_text(encoding="utf-8") == GARBAGE
    c = _check(ws, src)
    assert c.bitti and any("transcribe prepare" in u and did in u for u in c.uyarilar)


def test_suspicious_visible_text(tmp_path):
    ws, src, ids = _ws(tmp_path, {"afis": (".png", POSTER_OCR, 1)})
    did = ids["afis"]
    R.prepare(ws, only=[did], source=src)
    _out(ws, did, [_item(icerik="afis", gorunen_yazilar=[{"yer": "afis", "metin": "BAHAR ŞENLİĞİ"}])])
    st = R.apply(ws)
    assert did in st["supheli"] and st["islenen"] == 0
    assert R.apply(ws, accept_suspicious=True)["islenen"] == 1
    # örtüşen görünen yazı: tutarlı
    _out(ws, did, [_item(icerik="afis", etkinlik="öğrenci topluluğu etkinliği", kalabalik="21-50",
                         gorunen_yazilar=[{"yer": "afis", "metin": "KARİYER GÜNLERİ\nÖğrenci topluluğu "
                                                                   "etkinliği, konferans salonunda saat 14.00"}])])
    st = R.apply(ws)
    assert st["islenen"] == 1 and st["tutarlilik"][did]["durum"] == "tutarli"


def test_composes_with_transcription(tmp_path):
    """Belge hem yazıya geçirilmiş hem betimlenmiş: sağlıklı metin betimlemenin altında kalır,
    transcribe kaydı birleşik metne taşınır (iki kapı birbirini yeniden istemez)."""
    from bidr.transcribe import run as T
    ws, src, ids = _ws(tmp_path, {"foto": (".png", GARBAGE, 1)})
    did = ids["foto"]
    tr = "Ödül töreni katılım belgesi verilmiştir sayın katılımcılara teşekkür ederiz"
    (ws / "text" / f"{did}.txt").write_text(tr, encoding="utf-8")
    (ws / "text_ocr").mkdir()
    (ws / "text_ocr" / f"{did}.txt").write_text(GARBAGE, encoding="utf-8")
    write_jsonl(ws / "transcribe.jsonl", [{"doc_id": did, "durum": "uygulandi",
                                           "metin_sha": hashlib.sha256(tr.encode()).hexdigest()}])
    R.prepare(ws, only=[did], source=src)
    _out(ws, did, [_item()])
    assert R.apply(ws)["islenen"] == 1
    text = (ws / "text" / f"{did}.txt").read_text(encoding="utf-8")
    assert "[Betimleme · görsel dosyası]" in text and "çıkarılmış metin]\n" + tr in text
    assert (ws / "text_ocr" / f"{did}.txt").read_text(encoding="utf-8") == GARBAGE   # ilk OCR korunur
    assert T.is_done(R.Workspace(ws), did, T.load_log(R.Workspace(ws)))
    assert R.is_done(R.Workspace(ws), did, R.load_log(R.Workspace(ws)))
    # transcribe yeniden yazarsa describe yeniden kurar (taban = yeni metin)
    (ws / "text" / f"{did}.txt").write_text(tr + " ek", encoding="utf-8")
    assert not R.is_done(R.Workspace(ws), did, R.load_log(R.Workspace(ws)))
    assert R.apply(ws)["islenen"] == 1
    assert (tr + " ek") in (ws / "text" / f"{did}.txt").read_text(encoding="utf-8")


def test_check_states(tmp_path):
    ws, src, ids = _ws(tmp_path, {"tarama": (".jpg", RICH, 1)})
    assert _check(ws, src).atlandi
    ws2, src2, ids2 = _ws(tmp_path / "b", {"foto": (".png", GARBAGE, 1)})
    did = ids2["foto"]
    c = _check(ws2, src2)
    assert c.kim == "komut" and not c.bitti
    R.prepare(ws2, auto=True, source=src2)
    assert _check(ws2, src2).kim == "ajan"
    _out(ws2, did, [_item()])
    c = _check(ws2, src2)
    assert c.kim == "komut" and "describe apply" in c.komutlar[0]
    R.apply(ws2)
    c = _check(ws2, src2)
    assert c.bitti and c.ilerleme["betimlenen"] == 1
    # ingest --force metni ezerse yeniden apply ister
    (ws2 / "text" / f"{did}.txt").write_text(GARBAGE, encoding="utf-8")
    assert _check(ws2, src2).kim == "komut"
    assert R.apply(ws2)["islenen"] == 1 and _check(ws2, src2).bitti


def test_cli(tmp_path, capsys):
    from bidr.cli import main
    ws, src, ids = _ws(tmp_path, {"foto": (".png", GARBAGE, 1)})
    assert main(["describe", "prepare", "-w", str(ws)]) == 2
    assert main(["describe", "prepare", "-w", str(ws), "--auto", "--source", str(src)]) == 0
    assert "seçilen=1" in capsys.readouterr().out
    _out(ws, ids["foto"], [_item(betimleme="Sakallı bir adam.")])
    assert main(["describe", "apply", "-w", str(ws)]) == 1
    _out(ws, ids["foto"], [_item()])
    assert main(["describe", "apply", "-w", str(ws), "--model", "t"]) == 0
    assert "işlenen=1" in capsys.readouterr().out
