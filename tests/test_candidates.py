"""bidr.candidates: sentetik metin ve etiketlerle."""
from __future__ import annotations

import json

from bidr.candidates.data import load
from bidr.candidates.model import BM25, Model
from bidr.candidates.text import fold, lower_tr, text_hash, tokens
from bidr.cli import main
from bidr.common import read_jsonl

from synth import CS, ctext, make_ws

SUBS = [s.id for s in CS.sub_criteria]


def test_turkce_kucuk_harf_ve_katlama():
    assert lower_tr("IŞIK İLE") == "ışık ile"
    assert fold("İSTANBUL Çağrı Öğrenci") == "istanbul cagri ogrenci"
    assert tokens("Öğrencilerin ÖĞRENCİ öğrenme ve bir") == ["ogren", "ogren", "ogren"]


def test_metin_ozeti_bosluga_duyarsiz():
    assert text_hash("a  b\n\nc") == text_hash(" a b c ")
    assert text_hash("a b") != text_hash("a c")


def test_bm25_olcut_metnini_kendine_esler():
    bm = BM25(CS)
    hits = 0
    for sid in SUBS:
        sc = bm.score(dict(__import__("collections").Counter(tokens(ctext(sid)))))
        hits += max(sc, key=sc.get) == sid
    assert hits >= 0.9 * len(SUBS)


def _ws(tmp_path, name="ws", types=None):
    docs = [
        {"text": ctext("A.1.2", "ek metin bir"), "gold": ["A.1.2"], "units": ["U1"]},
        {"text": ctext("B.1.1", "ek metin iki"), "gold": ["B.1.1"], "units": ["U1"]},
        {"text": ctext("C.2.1", "ek metin üç"), "gold": ["C.2.1"], "units": ["U2"]},
        {"text": ctext("A.1.2", "başka bir kurul"), "gold": ["A.1.2"], "units": ["U2"]},
        {"text": "", "gold": ["D.1.1"], "units": ["U2"]},
        {"text": "kısa", "gold": [], "units": ["U2"]},
    ]
    return make_ws(tmp_path / name, docs, types), docs


def test_cli_candidates_yazar(tmp_path):
    ws, docs = _ws(tmp_path)
    assert main(["candidates", "-w", str(ws), "--train", str(ws), "--k", "5"]) == 0
    rows = {r["doc_id"]: r for r in read_jsonl(ws / "candidates.jsonl")}
    assert len(rows) == len(docs)
    r = rows[docs[0]["id"]]
    assert r["durum"] == "ok" and len(r["adaylar"]) == 5
    assert r["adaylar"][0]["olcut"] == "A.1.2"
    assert [a["sira"] for a in r["adaylar"]] == [1, 2, 3, 4, 5]
    assert set(r["adaylar"][0]["sinyaller"]) <= {"bm25", "yuva", "knn", "tur", "oncel"}
    assert r["birlesik"] == ["bm25", "knn", "tur", "oncel"]
    assert all("/" in y["yuva"] for y in r["en_iyi_yuvalar"])
    assert r["adaylar"][0]["kaynak"] in ("bm25", "knn")
    assert rows[docs[4]["id"]]["durum"] == "bos"
    assert rows[docs[5]["id"]]["durum"] == "kisa"


def test_yol_ve_iz_ozellik_degil(tmp_path):
    """Dosya adı, inventory yol sütunu ve labels.iz değişince çıktı değişmez."""
    ws, docs = _ws(tmp_path)
    main(["candidates", "-w", str(ws), "--train", str(ws)])
    a = (ws / "candidates.jsonl").read_text()
    inv = (ws / "inventory.csv").read_text().replace("klasor/", "B.1.1 Tutanak/")
    (ws / "inventory.csv").write_text(inv)
    lab = [json.loads(x) for x in (ws / "labels.jsonl").read_text().splitlines()]
    for r in lab:
        r["iz"] = {"yollar": [{"yol": "C.3.1/C.3.1 Yayın.pdf"}]}
    (ws / "labels.jsonl").write_text("\n".join(json.dumps(r) for r in lab) + "\n")
    main(["candidates", "-w", str(ws), "--train", str(ws)])
    assert (ws / "candidates.jsonl").read_text() == a


def test_kendi_etiketi_komsu_olmaz(tmp_path):
    ws, docs = _ws(tmp_path)
    m = Model(CS).fit(load(ws))
    d = next(x for x in load(ws) if x.doc_id == docs[2]["id"])     # C.2.1 tek örnek
    raw = m.signal_scores(d)
    assert raw["knn"]["C.2.1"] == 0.0
    assert raw["oncel"]["C.2.1"] == min(raw["oncel"].values())
    d0 = next(x for x in load(ws) if x.doc_id == docs[0]["id"])      # A.1.2'nin başka örneği var
    assert m.signal_scores(d0)["knn"]["A.1.2"] > 0


def test_tur_sinyali(tmp_path):
    pad = " dolgu" * 60          # MIN_CHARS üstü
    docs = [{"text": f"tutanak gündem karar {i} madde" + pad, "gold": ["A.1.1"]} for i in range(4)]
    docs += [{"text": f"ders izlence haftalık konu {i}" + pad, "gold": ["B.1.4"]} for i in range(4)]
    tr = make_ws(tmp_path / "tr", docs)
    types = {d["id"]: ("tutanak" if d["gold"] == ["A.1.1"] else "izlence") for d in docs}
    tr = make_ws(tmp_path / "tr", docs, types)
    te_docs = [{"text": "anlamsız rastgele sözcükler" + pad, "gold": ["A.1.1"], "id": "a" * 16},
               {"text": "yine anlamsız sözcükler" + pad, "gold": ["B.1.4"], "id": "b" * 16}]
    te = make_ws(tmp_path / "te", te_docs, {te_docs[0]["id"]: "tutanak"})
    m = Model(CS).fit(load(tr))
    a, b = load(te)
    ra, rb = m.signal_scores(a)["tur"], m.signal_scores(b)["tur"]
    assert max(ra, key=ra.get) == "A.1.1"
    assert not any(rb.values())                         # türü yok → sinyal kapalı
    rows, _ = m.rank(a, ("tur",))
    assert rows[0][0] == "A.1.1"


def test_tur_dosyasi_yoksa_kapali(tmp_path):
    ws, _ = _ws(tmp_path)
    m = Model(CS).fit(load(ws))
    assert all(not any(m.signal_scores(d)["tur"].values()) for d in load(ws))
