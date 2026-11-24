"""Bölümün elle eklediği eşleşmeler (bidr/audit/elle.py): ekleme, yineleme, ret'i aşma, geri alma, bulunamayan
belge, audit/OD sayımı, kanıt dosyalama ve alıntının ikinci aramayla aranması. Sentetik veri, model yok."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from bidr.audit import elle as E
from bidr.audit.run import FILES, apply, audit, build, review_state
from bidr.cli import main
from bidr.common import read_jsonl


def _m(olcut, yuva, asama, od, alinti="x" * 30, kabul=True):
    return {"olcut": olcut, "yuva": yuva, "asama": asama, "od_onerisi": od, "alinti": alinti, "gerekce": "g",
            "guven": "yuksek", "denetim": {"red": [], "isaret": []}, "od_kabul": od, "kabul": kabul}


DOCS = {
    # doc_id: (göreli yol, tür, eşleşmeler)
    "d_plan": ("kurul/eylem-plani.pdf", "eylem_plani", [_m("B.1.1", "B.1.1/1", "planla", 2)]),
    "d_karar": ("kurul/karar.pdf", "bolum_kurulu_karari", [_m("B.1.1", "B.1.1/3", "uygula", 3),
                                                           _m("A.1.1", "A.1.1/1", "planla", 2)]),
    "d_bos": ("diger/fotograf.pdf", "fotograf", []),
}


@pytest.fixture
def ws(tmp_path):
    w = tmp_path / "ws"
    w.mkdir()
    with open(w / "decisions.jsonl", "w", encoding="utf-8") as f:
        for did, (_, _, ms) in DOCS.items():
            f.write(json.dumps({"doc_id": did, "durum": "ok", "asama": "ince",
                                "karar": "olcut_var" if ms else "olcut_yok", "eslesmeler": ms},
                               ensure_ascii=False) + "\n")
    with open(w / "documents.jsonl", "w", encoding="utf-8") as f:
        for did, (_, t, _) in DOCS.items():
            f.write(json.dumps({"doc_id": did, "doc_type": t, "donem_ici": True, "calisma_adi": f"2025_{did}"})
                    + "\n")
    with open(w / "inventory.csv", "w", encoding="utf-8", newline="") as f:
        cw = csv.writer(f)
        cw.writerow(["doc_id", "sha256", "rel_path", "ext", "size", "pages", "chars", "method", "status", "dup_of",
                     "error"])
        for did, (rel, _, _) in DOCS.items():
            cw.writerow([did, (did * 8)[:64], rel, ".pdf", 1, 1, 10, "x", "ok", "", ""])
    return w


def _girdi(ws, *eslesmeler):
    (ws / E.DOSYA).write_text(json.dumps({"surum": 1, "kaynak": "bidr-panel", "eslesmeler": list(eslesmeler)},
                                         ensure_ascii=False), encoding="utf-8")


def _e(anahtar, dosya, olcut, yuva=None, asama=None, sha=""):
    return {"anahtar": anahtar, "dosya": dosya, "sha256": sha, "olcut": olcut, "yuva": yuva, "asama": asama,
            "not": "eylem planı bu maddenin kanıtı", "kim": "ad@ornek.edu.tr", "tarih": "2026-11-24T10:00:00"}


def _review(ws):
    return {r["satir"]: r for r in read_jsonl(ws / FILES["decisions"])} if (ws / FILES["decisions"]).exists() else {}


def _crit(a, c):
    return next(x for x in a.criteria if x["olcut"] == c)


def test_new_pair_counts_like_accepted_row(ws):
    assert _crit(build(ws), "A.1.3")["od"] == 1
    _girdi(ws, _e("panel-1", "kurul/eylem-plani.pdf", "A.1.3", asama="planla"))
    st = E.esitle(ws)
    assert st["eklenen"] == ["panel-1"] and st["degisti"]
    rec = next(r for r in _review(ws).values() if r.get("elle"))
    assert rec["kaynak"] == "insan" and rec["karar"] == "kabul" and rec["yapay"] and rec["olcut"] == "A.1.3"
    assert rec["satir"].startswith("d_plan|A.1.3/")
    a = build(ws)
    r = a.by_key[rec["satir"]]
    assert r["sayilir"] and r["od"] == 2 and "elle_eslesme" in r["flags"] and r["karar"] == "kabul"
    assert "elle" in r["vurgu"] and "alıntı yok" in r["vurgu"]
    assert _crit(a, "A.1.3")["od"] == 2                                  # OD hesabına olağan kabul gibi girer
    # ikinci kez eşitleme: değişiklik yok (idempotent)
    st = E.esitle(ws)
    assert not st["degisti"] and not st["eklenen"] and not st["guncellenen"]


def test_sha_resolves_and_missing_doc(ws):
    _girdi(ws, _e("panel-1", "baska/ad.pdf", "A.1.3", sha=("d_plan" * 8)[:64]),
           _e("panel-2", "yok/dosya.pdf", "A.1.3"), _e("panel-3", "kurul/karar.pdf", "Z.9.9"),
           _e("panel-4", "kurul/karar.pdf", "A.1.3", yuva="B.1.1/1"))
    st = E.esitle(ws)
    assert st["eklenen"] == ["panel-1"]
    neden = {b["anahtar"]: b["neden"] for b in st["bulunamayan"]}
    assert set(neden) == {"panel-3", "panel-4"}
    # belge henüz çalışma alanında yok: hata değil, bekler (sonraki audit'te yeniden denenir)
    assert [b["anahtar"] for b in st["bekleyen"]] == ["panel-2"] and "envanterde" in st["bekleyen"][0]["neden"]
    d = json.loads((ws / E.DURUM).read_text(encoding="utf-8"))
    assert d["kaynak_sha"] == E.kaynak_sha(ws)
    es = d["eslesmeler"]
    assert es["panel-1"]["durum"] == "uygulandi" and es["panel-1"]["doc_id"] == "d_plan" and es["panel-1"]["yuva"]
    assert es["panel-2"]["durum"] == "bekliyor" and es["panel-3"]["durum"] == "bulunamadi"


def test_duplicate_and_already_accepted(ws):
    (ws / FILES["decisions"]).write_text(json.dumps(
        {"satir": "d_karar|B.1.1/3", "doc_id": "d_karar", "olcut": "B.1.1", "yuva": "B.1.1/3", "karar": "kabul",
         "duzelt": None, "etiket": None, "not": ""}) + "\n", encoding="utf-8")
    _girdi(ws, _e("panel-1", "kurul/karar.pdf", "B.1.1"),                  # zaten kabul (model satırı)
           _e("panel-2", "kurul/eylem-plani.pdf", "A.1.3"), _e("panel-3", "kurul/eylem-plani.pdf", "A.1.3"))
    st = E.esitle(ws)
    assert st["eklenen"] == ["panel-2"] and st["zaten_kabul"] == ["panel-1", "panel-3"]
    assert sum(1 for r in _review(ws).values() if r.get("elle")) == 1
    a = build(ws)
    assert sum(1 for r in a.rows if r["doc_id"] == "d_plan" and r["olcut"] == "A.1.3") == 1


def test_overrides_human_reject_and_undo_restores(ws):
    ret = {"satir": "d_karar|A.1.1/1", "doc_id": "d_karar", "olcut": "A.1.1", "yuva": "A.1.1/1", "karar": "ret",
           "duzelt": None, "etiket": None, "not": "önce reddedildi"}
    (ws / FILES["decisions"]).write_text(json.dumps(ret) + "\n", encoding="utf-8")
    assert not build(ws).by_key["d_karar|A.1.1/1"]["sayilir"]
    _girdi(ws, _e("panel-7", "kurul/karar.pdf", "A.1.1"))
    st = E.esitle(ws)
    assert st["eklenen"] == ["panel-7"]
    rec = _review(ws)["d_karar|A.1.1/1"]
    assert rec["elle"] == "panel-7" and rec["karar"] == "kabul" and rec["onceki"] == ret and not rec.get("yapay")
    r = build(ws).by_key["d_karar|A.1.1/1"]
    assert r["sayilir"] and "insan_reddetti" not in r["flags"] and "elle_eslesme" in r["flags"]
    # aşama verilirse aşama düzeltmeli kabul
    _girdi(ws, _e("panel-7", "kurul/karar.pdf", "A.1.1", asama="uygula"))
    assert E.esitle(ws)["guncellenen"] == ["panel-7"]
    assert build(ws).by_key["d_karar|A.1.1/1"]["etkin_asama"] == "uygula"
    # geri alma: kayıt kalkar, önceki ret geri gelir
    _girdi(ws)
    st = E.esitle(ws)
    assert st["kaldirilan"] == ["panel-7"]
    assert _review(ws) == {"d_karar|A.1.1/1": ret}


def test_undo_synthetic_row_and_pipeline_staleness(ws):
    a, _ = audit(ws)
    _girdi(ws, _e("panel-1", "kurul/eylem-plani.pdf", "A.1.3", yuva="A.1.3/1"))
    assert not review_state(ws)["guncel"]                     # kaynak dosya değişti
    E.esitle(ws)
    assert not review_state(ws)["guncel"]                     # tablo yeniden üretilmeli (elle_sha)
    a, _ = audit(ws)
    st = review_state(ws)
    assert st["guncel"] and st["uygulanmamis"] == 0
    assert any(r["satir"] == "d_plan|A.1.3/1" and r["karar"] == "kabul" for r in a.rows)
    # tablodaki karar elle kaydı değiştirmez; apply onu korur
    apply(ws)
    assert _review(ws)["d_plan|A.1.3/1"]["elle"] == "panel-1"
    _girdi(ws)
    assert E.esitle(ws)["kaldirilan"] == ["panel-1"]
    assert "d_plan|A.1.3/1" not in _review(ws)
    assert not review_state(ws)["guncel"]
    a, _ = audit(ws)
    assert not any(r["olcut"] == "A.1.3" for r in a.rows)


def test_quote_from_model_match_absorbs_pending_row(ws):
    # model aynı ölçütte (başka yuvada) eşleşme buldu (ör. ikinci arama): karar bekleyen satır ayrı sorulmaz,
    # alıntısı elle satırına geçer
    _girdi(ws, _e("panel-1", "kurul/eylem-plani.pdf", "A.1.3", yuva="A.1.3/1"))
    E.esitle(ws)
    recs = [r for r in read_jsonl(ws / "decisions.jsonl")]
    for r in recs:
        if r["doc_id"] == "d_plan":
            r["eslesmeler"].append(_m("A.1.3", "A.1.3/2", "planla", 2, alinti="Eylem planı kabul edilmiştir burada."))
    with open(ws / "decisions.jsonl", "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    a = build(ws)
    rs = [r for r in a.rows if r["doc_id"] == "d_plan" and r["olcut"] == "A.1.3"]
    assert [r["satir"] for r in rs] == ["d_plan|A.1.3/1"]
    assert rs[0]["alinti"] == "Eylem planı kabul edilmiştir burada." and "alıntı yok" not in rs[0]["vurgu"]


def test_pairs_go_to_second_search(ws):
    _girdi(ws, _e("panel-1", "kurul/eylem-plani.pdf", "A.1.3"), _e("panel-2", "kurul/karar.pdf", "A.1.1"))
    E.esitle(ws)
    # panel-2 model satırına yazıldı (alıntısı var): aranmaz; panel-1 alıntısız yapay satır: aranır
    assert E.ciftler(ws) == [{"doc_id": "d_plan", "olcut": "A.1.3", "anahtar": "panel-1"}]


def test_file_index_includes_elle_row(ws, tmp_path):
    from bidr.file import run as R
    from pypdf import PdfWriter
    src = tmp_path / "kaynak"
    for did, (rel, _, _) in DOCS.items():
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        w = PdfWriter()
        w.add_blank_page(width=200, height=300)
        with open(p, "wb") as f:
            w.write(f)
    (ws / "text").mkdir()
    for did in DOCS:
        (ws / "text" / f"{did}.txt").write_text("x" * 30, encoding="utf-8")
    _girdi(ws, _e("panel-1", "diger/fotograf.pdf", "B.1.1", asama="uygula"))
    E.esitle(ws)
    out = tmp_path / "out"
    R.run(ws, out=out, source=src, review_dir=ws)
    with open(out / R.INDEX, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert any(r["doc_id"] == "d_bos" and r["olcut"] == "B.1.1" and r["od"] == "3" for r in rows)
    assert R.status(out, ws, review_dir=ws)["guncel"]
    _girdi(ws)
    E.esitle(ws)
    assert not R.status(out, ws, review_dir=ws)["guncel"]     # geri alma: kanıt klasörü eskir


def test_cli(ws, capsys):
    assert main(["audit", "elle", "ekle", "-w", str(ws), "kurul/eylem-plani.pdf", "A.1.3", "--asama", "planla",
                 "--not", "deneme"]) == 0
    g = E.oku(ws)
    assert len(g) == 1 and g[0]["anahtar"].startswith("cli-")
    assert any(r.get("elle") == g[0]["anahtar"] for r in _review(ws).values())
    capsys.readouterr()
    assert main(["audit", "elle", "esitle", "-w", str(ws), "--json"]) == 0
    js = json.loads(capsys.readouterr().out)
    assert set(js) == {"eklenen", "guncellenen", "kaldirilan", "zaten_kabul", "bulunamayan", "bekleyen"}
    assert main(["audit", "elle", "liste", "-w", str(ws), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["olcut"] == "A.1.3"
    assert main(["audit", "elle", "geri", "-w", str(ws), g[0]["anahtar"]]) == 0
    assert not any(r.get("elle") for r in _review(ws).values())
    assert main(["audit", "elle", "geri", "-w", str(ws), "cli-yok"]) == 2


def test_pipeline_consumes_file_without_explicit_sync(ws):
    """İşleyici dosyayı yalnız yazar (esitle çağırmaz): audit tabloyu eski sayar, `bidr audit` / `audit apply`
    eşitler; çözülemeyen belge sonraki çalıştırmada (belge gelince) uygulanır."""
    audit(ws)
    assert review_state(ws)["guncel"]
    _girdi(ws, _e("panel-1", "kurul/eylem-plani.pdf", "A.1.3"), _e("panel-2", "yeni/belge.pdf", "B.1.1"))
    assert not review_state(ws)["guncel"]                    # kaynak dosya değişti
    a, _ = audit(ws)
    assert review_state(ws)["guncel"]
    assert any(r["doc_id"] == "d_plan" and r["olcut"] == "A.1.3" and r["karar"] == "kabul" for r in a.rows)
    d = json.loads((ws / E.DURUM).read_text(encoding="utf-8"))["eslesmeler"]
    assert d["panel-1"]["durum"] == "uygulandi" and d["panel-2"]["durum"] == "bekliyor"
    # belge geldi (envanter + karar kaydı): sonraki audit uygular
    with open(ws / "inventory.csv", "a", encoding="utf-8", newline="") as f:
        csv.writer(f).writerow(["d_yeni", "y" * 64, "yeni/belge.pdf", ".pdf", 1, 1, 10, "x", "ok", "", ""])
    with open(ws / "decisions.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"doc_id": "d_yeni", "durum": "ok", "asama": "ince", "karar": "olcut_yok",
                            "eslesmeler": []}) + "\n")
    assert not review_state(ws)["guncel"]                    # decisions.jsonl değişti
    a, _ = audit(ws)
    assert any(r["doc_id"] == "d_yeni" and r["olcut"] == "B.1.1" for r in a.rows)
    assert json.loads((ws / E.DURUM).read_text(encoding="utf-8"))["eslesmeler"]["panel-2"]["durum"] == "uygulandi"
    # dosyanın silinmesi: bütün elle kayıtlar kalkar
    (ws / E.DOSYA).unlink()
    assert not review_state(ws)["guncel"]
    a, _ = audit(ws)
    assert not any(r.get("karar") and "elle_eslesme" in r["flags"] for r in a.rows)
    assert review_state(ws)["guncel"]
