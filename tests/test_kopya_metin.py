"""Farklı adla yeniden yüklenmiş, taranmamış kopya: metin kopyası grubu (tarama kopyasının metin tabanlı
belgelere genişletilmesi). Yalnız sentetik veri; model yok (sahte ajan). Kapsam:
- dedup.text_copy_pairs: metni neredeyse aynı (dışa aktarma altlığı farkı sözcük eşiğini aşar) ve tarihi
  aynı → kopya; tarihi farklı sürüm, tarihsiz belge, başka toplantı → kopya değil;
- decide: grupta tek paket, kopya kararı devralır; sonradan yüklenen kopya önceden incelenmiş belgenin
  kararını modelsiz devralır (temsilci incelenmiş olan), incelemede tek satır + "Kopyaları:".
"""
from __future__ import annotations

import json

import yaml

from bidr.common import read_jsonl
from bidr.decide import dedup as D
from bidr.decide.run import apply, prepare

from synth import make_ws
from test_decide import Q_B23, FakeLLM, _agent
from test_kopya import BASKA, YAZI

SON = "\n" + Q_B23 + " [EKLE]\n"
ALTLIK = "\nBu belge elektronik ortamda imzalanmıştır; evrak doğrulama adresini kullanınız. Sayfa 1 / 1\n"
ORJ = YAZI + SON
KOPYA = YAZI.replace("Kararlar:", "Kararlar :") + SON + ALTLIK         # dışa aktarma farkı
SURUM = YAZI.replace("05.08.2025", "14.01.2025") + SON + ALTLIK
TARIH = {"orj": "2025-08-05", "kopya": "2025-08-05", "surum": "2025-01-14", "baska": "2025-01-14"}


def test_text_copy_pairs():
    texts = {"orj": ORJ, "kopya": KOPYA, "surum": SURUM, "baska": BASKA + SON}
    types = dict.fromkeys(texts, "komisyon_tutanagi")
    # sözcük eşiği (mükerrer metin) bu farkı geçmez: eski durumda ayrı öneri
    assert not any({"orj", "kopya"} <= set(g["uyeler"]) for g in D.find_groups(texts, types))
    pairs = D.text_copy_pairs(texts, TARIH, types)
    assert [(a, b) for a, b, _ in pairs] == [("kopya", "orj")]
    assert pairs[0][2] >= D.TEXT_COPY_MIN
    # tarih koşulu: ikisinde de olmalı
    assert D.text_copy_pairs(texts, {**TARIH, "kopya": None}, types) == []
    assert D.text_copy_pairs(texts, {**TARIH, "kopya": None, "orj": None}, types) == []


def _ws(tmp_path, ids_in=("orj", "kopya", "surum")):
    docs = []
    texts = {"orj": ORJ, "kopya": KOPYA, "surum": SURUM}
    for k in ids_in:
        docs.append({"id": {"orj": "a" * 16, "kopya": "b" * 16, "surum": "c" * 16}[k], "text": texts[k],
                     "gold": [], "path": f"belgeler/{k}.pdf"})
    root = make_ws(tmp_path / "ws", docs)
    ids = {k: d["id"] for k, d in zip(ids_in, docs)}
    _docs(root, ids)
    (root / "config.yaml").write_text(yaml.safe_dump({"bidr": {}}), encoding="utf-8")
    return root, ids


def _docs(root, ids):
    with open(root / "documents.jsonl", "w", encoding="utf-8") as f:
        for k, x in ids.items():
            f.write(json.dumps({"doc_id": x, "doc_type": "komisyon_tutanagi", "tarih": TARIH[k], "donem": 2025,
                                "donem_ici": True, "calisma_adi": k}) + "\n")
    with open(root / "candidates.jsonl", "w", encoding="utf-8") as f:
        for x in ids.values():
            f.write(json.dumps({"doc_id": x, "adaylar": [{"olcut": "B.2.3"}]}) + "\n")


def _run(root, fake, b):
    for stage in ("coarse", "fine"):
        prepare(root, stage, backend=b)
        _agent(root, fake, stage)
        apply(root, stage, model="ajan", backend=b)


def test_text_copy_one_package_one_review_row(tmp_path):
    root, ids = _ws(tmp_path)
    fake = FakeLLM()
    b = fake.backend()
    st = prepare(root, "coarse", backend=b)
    assert st["mukerrer"] == 1 and st["paket"] == 2
    recs = {r["doc_id"]: r for r in read_jsonl(root / "decisions.jsonl")}
    mk = recs[ids["orj"]]["mukerrer"]                                 # temsilci uzun olan (incelenmiş yok)
    assert mk["temsilci"] == ids["kopya"] and mk["yontem"] == "metin_kopyasi" and mk["benzerlik"] >= D.TEXT_COPY_MIN
    assert "mukerrer" not in recs.get(ids["surum"], {})              # tarihi farklı sürüm kendisi işlenir
    _agent(root, fake, "coarse")
    apply(root, "coarse", model="ajan", backend=b)
    st = prepare(root, "fine", backend=b)
    assert st["paket"] == 2 and st["mukerrer"] == 1
    _agent(root, fake, "fine")
    assert apply(root, "fine", model="ajan", backend=b)["devralindi"] == 1
    from bidr.audit.run import build
    rows = [r for r in build(root).rows if r["olcut"] == "B.2.3"]
    assert len([r for r in rows if r["doc_id"] in (ids["orj"], ids["kopya"])]) == 1
    rep = next(r for r in rows if r["doc_id"] in (ids["orj"], ids["kopya"]))
    other = ids["kopya"] if rep["doc_id"] == ids["orj"] else ids["orj"]
    assert rep["kopyalar"] == other


def test_reupload_inherits_reviewed_decision_without_model(tmp_path):
    """Özgün belge önceden işlenmiş ve incelemede karar verilmiş; aynı belge farklı adla yeniden yüklenir:
    yeni belge paketlenmez, kararı devralır; incelemede yeni öneri satırı çıkmaz."""
    root, ids = _ws(tmp_path, ids_in=("orj", "surum"))
    fake = FakeLLM()
    b = fake.backend()
    _run(root, fake, b)
    from bidr.audit.run import build
    rows = [r for r in build(root).rows if r["olcut"] == "B.2.3" and r["doc_id"] == ids["orj"]]
    assert rows
    with open(root / "review-decisions.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps({"satir": r["satir"], "karar": "kabul"}) + "\n")
    # farklı adla yeniden yükleme (metni daha uzun: eski seçim onu temsilci yapardı)
    kid = "0" * 16
    (root / "text" / f"{kid}.txt").write_text(KOPYA, encoding="utf-8")
    ids2 = {**ids, "kopya": kid}
    _docs(root, ids2)
    import csv
    inv = root / "inventory.csv"
    with open(inv, encoding="utf-8", newline="") as f:
        rd = list(csv.DictReader(f))
    row = dict(rd[0])
    row.update(doc_id=kid, rel_path="belgeler/yeniden-yuklenen.pdf")
    with open(inv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rd[0]))
        w.writeheader()
        w.writerows(rd + [row])
    n0 = len(fake.calls)
    st = prepare(root, "coarse", backend=b)
    assert st["paket"] == 0 and st["mukerrer"] == 1 and st["devralindi"] == 1
    st = prepare(root, "fine", backend=b)
    assert st["paket"] == 0 and st["devralindi"] == 1
    assert len(fake.calls) == n0                                       # model çağrısı yok
    recs = {r["doc_id"]: r for r in read_jsonl(root / "decisions.jsonl")}
    assert recs[kid]["kopyasi"] == ids["orj"] and recs[kid]["mukerrer"]["yontem"] == "metin_kopyasi"
    rows = [r for r in build(root).rows if r["olcut"] == "B.2.3"]
    assert not [r for r in rows if r["doc_id"] == kid]                 # yeni öneri yok
    assert next(r for r in rows if r["doc_id"] == ids["orj"])["kopyalar"] == kid


def test_separately_decided_copies_regrouped_reviewed_is_representative(tmp_path):
    """İki kopya önceki koşuda ayrı işlenmiş (eski sürüm); yalnız kısa olanın satırları incelenmiş: grup
    modelsiz kurulur, temsilci incelenmiş olandır (insanın kararları kaybolmaz)."""
    root, ids = _ws(tmp_path)
    fake = FakeLLM()
    b = fake.backend()
    import bidr.decide.dedup as DD
    orig = DD.text_copy_pairs
    DD.text_copy_pairs = lambda *a, **k: []                            # eski sürüm: metin kopyası yok
    try:
        _run(root, fake, b)
    finally:
        DD.text_copy_pairs = orig
    from bidr.audit.run import build
    rows = [r for r in build(root).rows if r["olcut"] == "B.2.3"]
    assert {ids["orj"], ids["kopya"]} <= {r["doc_id"] for r in rows}    # eski durum: iki öneri
    with open(root / "review-decisions.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            if r["doc_id"] == ids["orj"]:
                f.write(json.dumps({"satir": r["satir"], "karar": "kabul"}) + "\n")
    for stage in ("coarse", "fine"):
        st = prepare(root, stage, backend=b)
        assert st["paket"] == 0 and st["devralindi"] == 1, stage
    recs = {r["doc_id"]: r for r in read_jsonl(root / "decisions.jsonl")}
    assert recs[ids["kopya"]]["kopyasi"] == ids["orj"]                # kopya daha uzun ama incelenmemiş
    rows = [r for r in build(root).rows if r["olcut"] == "B.2.3"]
    assert not [r for r in rows if r["doc_id"] == ids["kopya"]]
