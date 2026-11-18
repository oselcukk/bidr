"""`bidr verify`: uçtan uca sentetik (yazım → kod denetimi → sahte doğrulayıcı cevabı)."""
from __future__ import annotations

import csv
import json

from test_write import GOOD, answer, make_report_ws

from bidr.verify import run as V
from bidr.write import run as W
from bidr.write import sources as S


def written(tmp_path, out=None, **kw):
    ws = make_report_ws(tmp_path, **kw)
    W.prepare(ws)
    answer(ws, "B.1.1", out or GOOD)
    assert W.apply(ws)["islenen"] == 1
    return ws


def verdicts(ws, karar: dict | None = None, default="destekleniyor"):
    pkg = json.loads((ws / "work/verify/B.1.1.json").read_text(encoding="utf-8"))
    karar = karar or {}
    return {"cumleler": [{"yer": c["yer"], "karar": karar.get(c["yer"], default), "gerekce": "g"}
                         for c in pkg["meta"]["cumleler"]], "genel": ""}


def text(ws):
    return json.loads((ws / "texts/B.1.1.json").read_text(encoding="utf-8"))


def test_end_to_end_verified(tmp_path):
    ws = written(tmp_path)
    st = V.prepare(ws)
    assert st["paket"] == 1 and not st["kod_reddi"]
    pkg = json.loads((ws / "work/verify/B.1.1.json").read_text(encoding="utf-8"))
    assert [c["yer"] for c in pkg["meta"]["cumleler"]] == ["p1.1", "p2.1", "p2.2"]
    assert "AKTS kredisi, toplam iş yükünün 25'e bölümüdür." in pkg["istem"]   # kanıt alıntısı
    assert "Önerilen OD: 3" in pkg["istem"] and "bağlam 1" in pkg["istem"]
    answer(ws, "B.1.1", verdicts(ws), stage="verify")
    st = V.apply(ws, model="test:dogrulayici")
    assert st["dogrulandi"] == ["B.1.1"]
    assert text(ws)["durum"] == "dogrulandi"
    rec = [json.loads(x) for x in (ws / "verify.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rec[0]["durum"] == "dogrulandi" and rec[0]["model"] == "test:dogrulayici"
    assert len(rec[0]["cumleler"]) == 3
    assert V.prepare(ws)["zaten_tamam"] == 1                # sonuçlanmış metin yeniden paketlenmez


def test_unsupported_sentence_rejects(tmp_path):
    ws = written(tmp_path)
    V.prepare(ws)
    answer(ws, "B.1.1", verdicts(ws, {"p2.2": "desteklenmiyor"}), stage="verify")
    st = V.apply(ws)
    assert list(st["reddedildi"]) == ["B.1.1"] and "p2.2 (desteklenmiyor)" in st["reddedildi"]["B.1.1"][0]
    t = text(ws)
    assert t["durum"] == "reddedildi" and t["dogrulama"]["gerekce"][0].startswith("p2.2")


def test_partial_sentence_rejects(tmp_path):
    ws = written(tmp_path)
    V.prepare(ws)
    answer(ws, "B.1.1", verdicts(ws, {"p1.1": "kismen"}), stage="verify")
    assert "B.1.1" in V.apply(ws)["reddedildi"] and text(ws)["durum"] == "reddedildi"


def test_incomplete_verdicts_invalid(tmp_path):
    ws = written(tmp_path)
    V.prepare(ws)
    out = verdicts(ws)
    out["cumleler"] = out["cumleler"][:-1] + [{"yer": "p9.1", "karar": "destekleniyor", "gerekce": "g"}]
    answer(ws, "B.1.1", out, stage="verify")
    st = V.apply(ws)
    errs = st["gecersiz"]["B.1.1"]
    assert any("p9.1" in e for e in errs) and any("p2.2" in e for e in errs)
    assert text(ws)["durum"] == "taslak"


def test_code_rejects_quote_not_in_document(tmp_path):
    ws = written(tmp_path)
    rows = list(csv.DictReader(open(ws / S.INDEX, encoding="utf-8")))
    rows[1]["alintilar"] = json.dumps(["Bu cümle belgenin hiçbir yerinde yazmamaktadır kesinlikle."])
    with open(ws / S.INDEX, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    st = V.prepare(ws)
    assert "B.1.1" in st["kod_reddi"] and any("alinti_belgede_yok" in x for x in st["kod_reddi"]["B.1.1"])
    assert text(ws)["durum"] == "reddedildi" and not (ws / "work/verify/B.1.1.json").exists()


def test_code_rejects_when_od_drops(tmp_path):
    ws = written(tmp_path)
    make_report_ws(tmp_path, od=2)                     # audit sonradan OD2'ye indi
    st = V.prepare(ws)
    assert any("od_asimi" in x for x in st["kod_reddi"]["B.1.1"])


def test_text_changed_after_prepare_is_stale(tmp_path):
    ws = written(tmp_path)
    V.prepare(ws)
    answer(ws, "B.1.1", verdicts(ws), stage="verify")
    t = text(ws)
    t["paragraflar"][0]["metin"] = t["paragraflar"][0]["metin"].replace("süreç", "işleyiş")
    (ws / "texts/B.1.1.json").write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")
    st = V.apply(ws)
    assert st["eski"] == ["B.1.1"] and text(ws)["durum"] == "taslak"


def test_rewrite_resets_and_reverifies(tmp_path):
    ws = written(tmp_path)
    V.prepare(ws)
    answer(ws, "B.1.1", verdicts(ws, {"p2.2": "desteklenmiyor"}), stage="verify")
    V.apply(ws)
    W.prepare(ws, only=["B.1.1"], redo=True)
    fixed = {"paragraflar": GOOD["paragraflar"][:1], "onceki_yila_gore": ""}
    answer(ws, "B.1.1", fixed)
    assert W.apply(ws)["islenen"] == 1 and text(ws)["durum"] == "taslak"
    assert V.prepare(ws)["paket"] == 1
    answer(ws, "B.1.1", verdicts(ws), stage="verify")
    assert V.apply(ws)["dogrulandi"] == ["B.1.1"]


def test_cli(tmp_path, capsys):
    from bidr.cli import main
    ws = written(tmp_path)
    assert main(["verify", "prepare", "-w", str(ws)]) == 0
    answer(ws, "B.1.1", verdicts(ws, {"p1.1": "desteklenmiyor"}), stage="verify")
    assert main(["verify", "apply", "-w", str(ws), "--model", "x"]) == 1
    assert "reddedildi B.1.1" in capsys.readouterr().out
