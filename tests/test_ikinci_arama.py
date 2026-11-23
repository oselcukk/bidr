"""İkinci (genişletilmiş) arama: zayıf ölçüt, ters arama, işaretli paket/ekleme, ölçüm.
Yalnız sentetik veri; model çağrısı yok (bidr.llm'in modelsiz işlevleri gerçek)."""
from __future__ import annotations

import json
from collections import Counter

import pytest

from bidr.candidates import arama as A
from bidr.candidates import ikinci as I
from bidr.candidates.synonyms import expand
from bidr.common import read_jsonl
from bidr.criteria.slots import load_tags
from bidr.decide.run import task_version
from bidr.evaluate.ikinci_arama import measure

from synth import CS, make_ws

SECRET = "GIZLI"     # eski rapor kanıt adı/yol: pakete asla girmemeli
TAGS = load_tags(CS)

Q_B11 = "Programın amaçları ve öğrenme çıktıları bölüm kurulunda görüşülerek onaylanmıştır."
Q_B23 = ("Önceki öğrenmelerin tanınması başvuruları komisyonca incelenmiş ve öğrenci iş yükü "
         "temelli AKTS kredileri ile 4 öğrenciye kredi verilmiştir.")
RPL = (f"MUAFİYET VE İNTİBAK KOMİSYONU TUTANAĞI\n{Q_B23}\nÖnceki öğrenmenin tanınması ve "
       "kredilendirilmesi ilke ve kuralları uygulanmıştır. Öğrenci kabulü kurallara uygundur.")
DOCS = {
    "b11": f"BÖLÜM KURULU KARARI\nGündem 1. {Q_B11}\nProgram tasarımı ve onayı süreci tamamlandı.",
    "rpl": RPL,                                        # ilk geçiş kaçırdı → seçilmeli
    "rpl_aday": RPL + " İkinci nüsha, farklı tarih 2025.",  # ilk geçişte B.2.3 adayıydı → seçilmez
    "baska": RPL + " Kimya Bölümü.",                   # başka birime ait → seçilmez
    "kaba": RPL + " Taslak.",                          # ince kararı yok → seçilmez
    "kantin": "Kantin menüsü: pazartesi mercimek çorbası, salı kuru fasulye.",
}


def _fine_rec(did, adaylar, eslesmeler=(), rel="kendi", secilen=None):
    return {"doc_id": did, "sema": 1, "durum": "ok", "asama": "ince", "profil": None,
            "gorev": {"classify_fine": task_version("classify_fine")},
            "belge_bilgisi": {"tur": "Kurul Kararı"},
            "kaba": {"karar": "olcut_var", "secilen": list(secilen or adaylar[:1])},
            "adaylar": list(adaylar), "belirleyici_ilk_k": [], "adaylar_kesilen": [],
            "ince": {"karar": "olcut_var" if eslesmeler else "olcut_yok", "gerekce": "g",
                     "birim_iliskisi": rel, "birim_iliskisi_kaynagi": "model", "model": "m",
                     "istem_sha": "s1", "cevap_sha": "c1"},
            "eslesmeler": list(eslesmeler),
            "olcutler": [], "karar": "olcut_var" if eslesmeler else "olcut_yok", "reddedilen_eslesme": 0}


def _match(olcut, yuva, alinti, od=2, asama="planla"):
    return {"olcut": olcut, "yuva": yuva, "asama": asama, "od_onerisi": od, "alinti": alinti,
            "gerekce": "g", "guven": "yuksek", "kabul": True, "od_kabul": od,
            "denetim": {"alinti_tutuyor": True, "red": [], "isaret": []}}


@pytest.fixture
def ws(tmp_path):
    docs = [{"text": t, "path": f"{SECRET}_YOL/{k}.pdf"} for k, t in DOCS.items()]
    root = make_ws(tmp_path / "ws", docs)
    ids = {k: d["id"] for k, d in zip(DOCS, docs)}
    # labels.jsonl (geçmiş rapor etiketleri/kanıt adları) bozuk: okunursa test patlar
    (root / "labels.jsonl").write_text(f"{{bozuk {SECRET}_KANIT_ADI\n", encoding="utf-8")
    with open(root / "documents.jsonl", "w", encoding="utf-8") as f:
        for k, x in ids.items():
            f.write(json.dumps({"doc_id": x, "doc_type": "kurul_karari", "calisma_adi": f"{SECRET}_AD",
                                "baslik": f"{SECRET}_BASLIK"}, ensure_ascii=False) + "\n")
    recs = {
        ids["b11"]: _fine_rec(ids["b11"], ["B.1.1"], [_match("B.1.1", "B.1.1/1", Q_B11)]),
        ids["rpl"]: _fine_rec(ids["rpl"], ["B.1.1", "A.3.1"]),
        ids["rpl_aday"]: _fine_rec(ids["rpl_aday"], ["B.2.3", "B.1.1"]),
        ids["baska"]: _fine_rec(ids["baska"], ["B.1.1"], rel="baska_birim"),
        ids["kantin"]: _fine_rec(ids["kantin"], ["B.1.1"]),
        ids["kaba"]: {"doc_id": ids["kaba"], "sema": 1, "durum": "ok", "asama": "kaba",
                      "kaba": {"karar": "olcut_var", "secilen": ["B.1.1"]}},
    }
    with open(root / "decisions.jsonl", "w", encoding="utf-8") as f:
        for k in sorted(recs):
            f.write(json.dumps(recs[k], ensure_ascii=False) + "\n")
    return root, ids


def _recs(root):
    return {r["doc_id"]: r for r in read_jsonl(root / "decisions.jsonl")}


def _answer(root, did, out):
    out = {"kanit_adi": "Muafiyet Komisyonu Tutanağı", **out}
    (root / "work" / A.WORK / f"{did}.out.json").write_text(json.dumps(out, ensure_ascii=False),
                                                            encoding="utf-8")


# -- zayıf ölçüt ---------------------------------------------------------------------

def test_weak_criteria_reasons():
    docs = {"d1": {"doc_type": "kurul_karari"}, "d2": {"doc_type": "yonetmelik"}}
    recs = {"d1": _fine_rec("d1", ["B.1.1"], [_match("B.1.1", "B.1.1/1", Q_B11, od=3, asama="uygula")]),
            "d2": _fine_rec("d2", ["A.1.2"], [_match("A.1.2", "A.1.2/1", "x" * 30)])}
    allowed = ["A.1.2", "B.1.1", "B.2.3"]
    # audit yok: decisions'tan yaklaşık
    w = I.weak_criteria(allowed, recs, docs=docs, tags=TAGS)
    assert w["B.2.3"]["nedenler"] == ["kanitsiz"] and w["B.2.3"]["kaynak"] == "decisions"
    assert set(w["A.1.2"]["nedenler"]) == {"dusuk_od", "bolum_kaniti_yok"}   # yalnız yönetmelikten
    assert "B.1.1" not in w                                                  # OD3, birimin kendi belgesi
    # audit-olcutler.json esas: OD ve "yalnız kurum geneli" oradan
    audit = {"B.1.1": {"olcut": "B.1.1", "od": 2, "eslesme": 1, "kurum_geneli_yalniz": False},
             "A.1.2": {"olcut": "A.1.2", "od": 2, "eslesme": 1, "kurum_geneli_yalniz": True},
             "B.2.3": {"olcut": "B.2.3", "od": 1, "eslesme": 0}}
    w = I.weak_criteria(allowed, recs, audit=audit, docs=docs, tags=TAGS)
    assert w["B.1.1"]["nedenler"] == ["dusuk_od"] and w["B.1.1"]["kaynak"] == "audit"
    assert set(w["A.1.2"]["nedenler"]) == {"dusuk_od", "yalniz_kurum_geneli", "bolum_kaniti_yok"}
    audit["B.1.1"]["od"] = 3
    assert "B.1.1" not in I.weak_criteria(allowed, recs, audit=audit, docs=docs, tags=TAGS)
    assert "B.1.1" in I.weak_criteria(allowed, recs, audit=audit, docs=docs, tags=TAGS, od_esik=3)


# -- arama -----------------------------------------------------------------------------

def test_synonym_expansion_is_phrase_based():
    q, added = expand("Öğrenci memnuniyet anketleri uygulanmıştır.")
    assert {"geri", "bildi", "gorus"} <= set(added) and q["geri"] == 1
    # yalnız 5 harflik kök çakışması (uygulamaları ≈ uygulamalı) genişletmeyi tetiklemez
    _, added = expand("Uygulamaları eğitim komisyonunda görüşüldü.")
    assert "staj" not in added


def test_reverse_search_finds_synonym_only_document():
    arch = I.Archive({"syn": dict(Counter({"intib": 2, "muafi": 2, "komis": 1})),
                      "ilgisiz": dict(Counter({"kanti": 2, "menus": 1}))})
    s = I.Searcher(CS, arch)
    rows, added = s.search("B.2.3")
    assert [r["doc_id"] for r in rows] == ["syn"] and "intib" in added
    assert I.Searcher(CS, arch, synonyms=False).search("B.2.3")[0] == []


def test_prepare_selects_only_missed_documents(ws):
    root, ids = ws
    st = A.prepare(root, profile=None, olcutler=["B.2.3"])
    assert st["secim"]["B.2.3"][0] == ids["rpl"]            # en iyi aday: ilk geçişin kaçırdığı
    for k in ("rpl_aday", "baska", "kaba", "kantin"):
        assert ids[k] not in st["secim"]["B.2.3"], k
    assert st["baska_birim"] == 1 and st["ince_yok"] == 1
    d = root / "work" / A.WORK
    pkg = json.loads((d / f"{ids['rpl']}.json").read_text(encoding="utf-8"))
    assert pkg["gorev"] == "classify_fine" and pkg["meta"]["adaylar"] == ["B.2.3"]
    assert "B.2.3/2" in pkg["istem"] and "B.1.1/1" not in pkg["istem"]
    ia = pkg["meta"]["ikinci_arama"]
    assert ia["olcutler"][0]["olcut"] == "B.2.3" and ia["olcutler"][0]["nedenler"] == ["elle"]
    for p in d.iterdir():
        assert SECRET not in p.read_text(encoding="utf-8"), p.name
    assert "bidr arama apply" in (d / "README.md").read_text(encoding="utf-8")


def test_prepare_computes_weak_from_audit(ws):
    root, ids = ws
    olc = [{"olcut": "B.1.1", "od": 3, "eslesme": 1, "kurum_geneli_yalniz": False},
           {"olcut": "B.2.3", "od": 1, "eslesme": 0}]
    (root / "audit-olcutler.json").write_text(json.dumps({"olcutler": olc}), encoding="utf-8")
    st = A.prepare(root, profile="akademik_bolum")
    assert st["audit"] and "B.2.3" in st["zayif"] and "B.1.1" not in st["zayif"]
    assert ids["rpl"] in st["secim"]["B.2.3"]


def test_apply_adds_marked_matches_and_keeps_first_pass(ws):
    root, ids = ws
    A.prepare(root, profile=None, olcutler=["B.2.3"])
    before = _recs(root)[ids["rpl"]]
    other = [x for x in (root / "work" / A.WORK).glob("*.json")
             if not x.name.endswith(".out.json") and x.stem != ids["rpl"]]
    for p in other:                                     # öteki seçilenler: uymuyor
        _answer(root, p.stem, {"karar": "olcut_yok", "gerekce": "uymuyor", "birim_iliskisi": "kendi",
                               "eslesmeler": []})
    _answer(root, ids["rpl"], {
        "karar": "olcut_var", "gerekce": "tanıma kararı", "birim_iliskisi": "kendi", "eslesmeler": [
            {"olcut": "B.2.3", "yuva": "B.2.3/2", "asama": "uygula", "od_onerisi": 3, "alinti": Q_B23,
             "gerekce": "AKTS kredisi", "guven": "yuksek"},
            {"olcut": "B.1.1", "yuva": "B.1.1/1", "asama": "planla", "od_onerisi": 2,
             "alinti": "Öğrenci kabulü kurallara uygundur.", "gerekce": "x", "guven": "dusuk"}]})
    st = A.apply(root, model="test-ajan")
    assert st["islenen"] == 1 + len(other) and st["eklenen_kabul"] == 1 and st["eklenen_red"] == 1
    rec = _recs(root)[ids["rpl"]]
    marked = [m for m in rec["eslesmeler"] if m.get("ikinci_arama")]
    assert len(marked) == 2 and all("ikinci_arama" in m["denetim"]["isaret"] for m in marked)
    ok = [m for m in marked if m["kabul"]]
    assert [m["yuva"] for m in ok] == ["B.2.3/2"] and ok[0]["od_kabul"] == 3
    bad = [m for m in marked if not m["kabul"]][0]
    assert "aday_disi_olcut" in bad["denetim"]["red"]  # ikinci aramanın adayı değil
    assert rec["olcutler"] == [{"olcut": "B.2.3", "ana": "B.2", "od": 3, "yuvalar": ["B.2.3/2"]}]
    assert rec["karar"] == "olcut_var" and rec["reddedilen_eslesme"] == 1
    # ilk geçiş değişmez
    for k in ("ince", "adaylar", "kaba", "gorev"):
        assert rec[k] == before[k], k
    assert rec["ikinci_arama"]["olcutler"]["B.2.3"]["kabul"] == 1
    assert rec["ikinci_arama"]["son"]["model"] == "test-ajan"
    # yeniden: bakılmış çift paketlenmez, cevap yeniden işlenmez
    assert ids["rpl"] not in A.prepare(root, profile=None, olcutler=["B.2.3"])["secim"]["B.2.3"]
    st = A.apply(root, model="test-ajan")
    assert st["islenen"] == 0 and st["degismedi"] == 1 + len(other)
    assert len([m for m in _recs(root)[ids["rpl"]]["eslesmeler"] if m.get("ikinci_arama")]) == 2


def test_first_pass_redecided_invalidates(ws):
    root, ids = ws
    A.prepare(root, profile=None, olcutler=["B.2.3"])
    _answer(root, ids["rpl"], {"karar": "olcut_yok", "gerekce": "g", "birim_iliskisi": "kendi",
                               "eslesmeler": []})
    A.apply(root)
    recs = _recs(root)
    assert A.done_criteria(recs[ids["rpl"]]) == {"B.2.3"}
    # ilk geçiş yeniden karara bağlandı (istem değişti): ikinci arama geçersiz, paket eskidi
    recs[ids["rpl"]]["ince"]["istem_sha"] = "s2"
    with open(root / "decisions.jsonl", "w", encoding="utf-8") as f:
        for k in sorted(recs):
            f.write(json.dumps(recs[k], ensure_ascii=False) + "\n")
    assert ids["rpl"] in A.apply(root)["eski_paket"]
    st = A.prepare(root, profile=None, olcutler=["B.2.3"])
    assert ids["rpl"] in st["secim"]["B.2.3"]


def test_unit_relation_from_first_pass(ws):
    """Birim ilişkisi ilk geçişin kararından: model ikinci aramada başka birim dese de
    kayıttaki kendi esastır; kurum geneli kaydında OD2 tavanı uygulanır."""
    root, ids = ws
    recs = _recs(root)
    recs[ids["rpl"]]["ince"]["birim_iliskisi"] = "kurum_geneli"
    with open(root / "decisions.jsonl", "w", encoding="utf-8") as f:
        for k in sorted(recs):
            f.write(json.dumps(recs[k], ensure_ascii=False) + "\n")
    A.prepare(root, profile=None, olcutler=["B.2.3"])
    _answer(root, ids["rpl"], {"karar": "olcut_var", "gerekce": "g", "birim_iliskisi": "kendi", "eslesmeler": [
        {"olcut": "B.2.3", "yuva": "B.2.3/2", "asama": "uygula", "od_onerisi": 3, "alinti": Q_B23,
         "gerekce": "g", "guven": "yuksek"}]})
    A.apply(root)
    m = [m for m in _recs(root)[ids["rpl"]]["eslesmeler"] if m.get("ikinci_arama")][0]
    assert m["kabul"] and m["od_kabul"] == 2 and "uygulama_kaniti_eksik" in m["denetim"]["isaret"]


# -- ölçüm ve CLI -------------------------------------------------------------------------

def test_measure_counts_code_and_human(ws):
    root, ids = ws
    A.prepare(root, profile=None, olcutler=["B.2.3"])
    _answer(root, ids["rpl"], {"karar": "olcut_var", "gerekce": "g", "birim_iliskisi": "kendi", "eslesmeler": [
        {"olcut": "B.2.3", "yuva": "B.2.3/2", "asama": "uygula", "od_onerisi": 3, "alinti": Q_B23,
         "gerekce": "g", "guven": "yuksek"},
        {"olcut": "B.2.3", "yuva": "B.2.3/1", "asama": "planla", "od_onerisi": 2,
         "alinti": "Bu cümle belgede yok ama yeterince uzundur.", "gerekce": "g", "guven": "orta"}]})
    A.apply(root)
    res = measure(root)
    s = res["olcutler"]["B.2.3"]
    assert (s["eslesme"], s["kod_kabul"], s["kod_red"], s["incelenmedi"]) == (2, 1, 1, 1)
    assert s["red_nedenleri"] == {"alinti_tutmuyor": 1} and s["isabet"] is None
    (root / "review-decisions.jsonl").write_text(
        json.dumps({"satir": f"{ids['rpl']}|B.2.3/2", "karar": "ret"}) + "\n"
        + json.dumps({"satir": f"{ids['b11']}|B.1.1/1", "karar": "kabul"}) + "\n", encoding="utf-8")
    t = measure(root)["toplam"]
    assert (t["insan_ret"], t["insan_kabul"], t["isabet"]) == (1, 0, 0.0)  # ilk geçiş sayılmaz


def test_cli_prepare_apply_olcum(ws, capsys):
    from bidr.cli import main
    root, ids = ws
    assert main(["arama", "prepare", "-w", str(root), "--profile", "", "--olcut", "B.2.3"]) == 0
    _answer(root, ids["rpl"], {"karar": "olcut_yok", "gerekce": "g", "birim_iliskisi": "kendi",
                               "eslesmeler": []})
    assert main(["arama", "apply", "-w", str(root), "--model", "x"]) == 0
    assert main(["arama", "olcum", "-w", str(root), "--json"]) == 0
    out = capsys.readouterr().out
    assert "B.2.3" in out and '"bakilan": 1' in out


def test_cli_prepare_gated_until_audit_done(ws, tmp_path, capsys):
    """Yönetilen çalışma alanında `arama prepare` audit bitmeden çalışmaz (çıkış 3, `bidr next`
    önerisi); paket yazılmaz. Ölçüm ve yönetilmeyen çalışma alanı etkilenmez."""
    import yaml

    from bidr.cli import main
    from bidr.pipeline.gate import GATE_EXIT
    root, _ = ws
    src = tmp_path / "kaynak"
    src.mkdir()
    (root / "config.yaml").write_text(yaml.safe_dump({"bidr": {"kaynak": str(src), "birim": "Örnek Bölümü"}},
                                                     allow_unicode=True), encoding="utf-8")
    capsys.readouterr()
    assert main(["arama", "prepare", "-w", str(root), "--profile", "", "--olcut", "B.2.3"]) == GATE_EXIT
    err = capsys.readouterr().err
    assert "audit bittikten sonra" in err and "bidr next -w" in err and "önce bitmeli" in err
    assert not (root / "work" / A.WORK).exists()
    assert main(["arama", "olcum", "-w", str(root), "--json"]) == 0


# -- çapraz yol: başka ölçütte kabul edilmiş birim belgeleri ------------------------------

Q_D21 = "Lise öğrencilerine yönelik toplumsal katkı etkinliği gerçekleştirilmiş ve 120 kişi katılmıştır."
Q_D12 = "Etkinlik bütçesi üniversitemiz tarafından karşılanmış, bölüm görevlisi belirlenmiştir."
ETK = (f"BÖLÜM ETKİNLİK RAPORU\n{Q_D21}\n{Q_D12}\nToplumsal katkı kaynakları (mali, fiziksel, "
       "insan gücü) etkinlik için ayrılmıştır.")
CROSS = {
    "etk": ETK,                              # D.2.1 kabul, D.1.2 ilk geçişte aday ama eşleşmedi
    "etk_ret": ETK + " Nüsha 2.",            # D.2.1 kabulünü insan reddetti → havuzda değil
    "etk_kg": ETK + " Nüsha 3.",             # kurum geneli → havuzda değil
    "etk_d12": ETK + " Nüsha 4.",            # D.1.2 ilk geçişte eşleşti (kod reddi) → sorulmaz
    "kantin": "Kantin menüsü: pazartesi mercimek çorbası, salı kuru fasulye.",
}


@pytest.fixture
def cws(tmp_path):
    docs = [{"text": t} for t in CROSS.values()]
    root = make_ws(tmp_path / "cws", docs)
    ids = {k: d["id"] for k, d in zip(CROSS, docs)}
    with open(root / "documents.jsonl", "w", encoding="utf-8") as f:
        for x in ids.values():
            f.write(json.dumps({"doc_id": x, "doc_type": "faaliyet_raporu"}) + "\n")
    d21 = lambda: _match("D.2.1", "D.2.1/1", Q_D21, asama="uygula")   # noqa: E731
    rej = {**_match("D.1.2", "D.1.2/1", Q_D12), "kabul": False}
    recs = {
        ids["etk"]: _fine_rec(ids["etk"], ["D.2.1", "D.1.2"], [d21()]),
        ids["etk_ret"]: _fine_rec(ids["etk_ret"], ["D.2.1"], [d21()]),
        ids["etk_kg"]: _fine_rec(ids["etk_kg"], ["D.2.1"], [d21()], rel="kurum_geneli"),
        ids["etk_d12"]: _fine_rec(ids["etk_d12"], ["D.2.1", "D.1.2"], [d21(), rej]),
        ids["kantin"]: _fine_rec(ids["kantin"], ["D.2.1"]),
    }
    with open(root / "decisions.jsonl", "w", encoding="utf-8") as f:
        for k in sorted(recs):
            f.write(json.dumps(recs[k], ensure_ascii=False) + "\n")
    (root / "review-decisions.jsonl").write_text(
        json.dumps({"satir": f"{ids['etk_ret']}|D.2.1/1", "karar": "ret"}) + "\n", encoding="utf-8")
    return root, ids


def test_cross_route_asks_accepted_unit_documents(cws):
    root, ids = cws
    # arşiv yolu: etk'de D.1.2 ilk geçiş adayıydı, seçilmez; çapraz yol onu sorar
    st = A.prepare(root, profile=None, olcutler=["D.1.2"], capraz=False)
    assert ids["etk"] not in st["secim"]["D.1.2"] and st["capraz_havuz"] == 0
    st = A.prepare(root, profile=None, olcutler=["D.1.2"])
    assert st["secim_capraz"]["D.1.2"] == [ids["etk"]]
    assert st["capraz_havuz"] == 1 and st["capraz_paket"] == 1 and st["capraz_cift"] == 1
    pkg = json.loads((root / "work" / A.WORK / f"{ids['etk']}.json").read_text(encoding="utf-8"))
    assert pkg["meta"]["adaylar"] == ["D.1.2"]
    assert "D.1.2/1" in pkg["istem"] and Q_D12 in pkg["istem"]          # hedef ölçüt + yuva + metin
    row = pkg["meta"]["ikinci_arama"]["olcutler"][0]
    assert row["kaynak"] == ["capraz"] and row["kabul_olcutler"] == ["D.2.1"]
    for k in ("etk_ret", "etk_kg", "etk_d12", "kantin"):
        assert ids[k] not in st["secim_capraz"]["D.1.2"], k


def test_cross_route_apply_merges_without_double_count(cws):
    root, ids = cws
    A.prepare(root, profile=None, olcutler=["D.1.2"])
    for p in (root / "work" / A.WORK).glob("*.json"):
        if p.stem != ids["etk"] and not p.name.endswith(".out.json"):
            _answer(root, p.stem, {"karar": "olcut_yok", "gerekce": "g", "birim_iliskisi": "kendi",
                                   "eslesmeler": []})
    _answer(root, ids["etk"], {"karar": "olcut_var", "gerekce": "bütçe", "birim_iliskisi": "kendi",
                               "eslesmeler": [{"olcut": "D.1.2", "yuva": "D.1.2/1", "asama": "uygula",
                                               "od_onerisi": 2, "alinti": Q_D12, "gerekce": "g",
                                               "guven": "yuksek"}]})
    st = A.apply(root, model="m")
    assert st["eklenen_kabul"] == 1
    rec = _recs(root)[ids["etk"]]
    assert [(m["olcut"], bool(m.get("ikinci_arama"))) for m in rec["eslesmeler"]] == \
        [("D.2.1", False), ("D.1.2", True)]
    assert rec["ikinci_arama"]["olcutler"]["D.1.2"]["kaynak"] == ["capraz"]
    assert {o["olcut"] for o in rec["olcutler"]} == {"D.1.2", "D.2.1"}
    # bakılmış çift yeniden paketlenmez; ikinci aramanın kabulü havuz nedeni sayılmaz
    st = A.prepare(root, profile=None, olcutler=["D.1.2"])
    assert ids["etk"] not in st["secim_capraz"].get("D.1.2", [])


def _save(root, recs):
    with open(root / "decisions.jsonl", "w", encoding="utf-8") as f:
        for k in sorted(recs):
            f.write(json.dumps(recs[k], ensure_ascii=False) + "\n")


def _check(root):
    from bidr.pipeline.checks import Ctx, ikinci_arama_tamam
    from bidr.common import Workspace
    stage = {"komut": ["bidr arama prepare", "(ajan)", "bidr arama apply"]}
    return ikinci_arama_tamam(Ctx(Workspace(root), {}, lambda s: s, stage))


def test_prepare_refreshes_stale_after_first_pass_change(ws):
    """İlk geçiş değişti, istem aynı: prepare paketi yeniler (parmak izi), eski cevap `.eski` olur;
    check'te eski paket kalmaz (canlıda prepare → check döngüsü takılıyordu)."""
    root, ids = ws
    A.prepare(root, profile=None, olcutler=["B.2.3"])
    d = root / "work" / A.WORK
    _answer(root, ids["rpl"], {"karar": "olcut_yok", "gerekce": "g", "birim_iliskisi": "kendi", "eslesmeler": []})
    recs = _recs(root)
    recs[ids["rpl"]]["ince"]["cevap_sha"] = "c2"          # ilk geçiş yeniden karara bağlandı
    _save(root, recs)
    assert ids["rpl"] in A.stale_pkgs(d, _recs(root))
    st = A.prepare(root, profile=None, olcutler=["B.2.3"])
    assert st["eski_kalan"] == 0 and A.stale_pkgs(d, _recs(root)) == []
    assert (d / f"{ids['rpl']}.out.json.eski").exists() and not (d / f"{ids['rpl']}.out.json").exists()
    pkg = json.loads((d / f"{ids['rpl']}.json").read_text(encoding="utf-8"))
    assert pkg["meta"]["ikinci_arama"]["ince_parmak"] == A.first_pass_print(_recs(root)[ids["rpl"]])
    assert _check(root).ilerleme["eski"] == 0


def test_prepare_archives_dropped_and_keeps_merged(ws):
    """Adaylıktan düşen belgenin eski paketi ve cevabı `_eski/`'ye taşınır (silinmez); cevabı
    kayıtta olan (merged) paket yerinde kalır."""
    root, ids = ws
    A.prepare(root, profile=None, olcutler=["B.2.3"])
    d = root / "work" / A.WORK
    others = [p.stem for p in d.glob("*.json") if not p.name.endswith(".out.json") and p.stem != ids["rpl"]]
    assert others
    for did in [ids["rpl"], *others]:
        _answer(root, did, {"karar": "olcut_yok", "gerekce": "g", "birim_iliskisi": "kendi", "eslesmeler": []})
    A.apply(root)
    keep = others[0]
    drop = ids["rpl"]
    recs = _recs(root)
    # düşen belge: ilk geçiş B.2.3'ü artık aday sayıyor (paket eskidi, belge ikinci aramaya açık değil)
    recs[drop]["adaylar"] = [*recs[drop]["adaylar"], "B.2.3"]
    _save(root, recs)
    assert A.stale_pkgs(d, _recs(root)) == [drop]
    st = A.prepare(root, profile=None, olcutler=["B.2.3"])
    assert drop in st["tasinan"] and st["eski_kalan"] == 0
    assert (d / "_eski" / f"{drop}.json").exists() and (d / "_eski" / f"{drop}.out.json").exists()
    assert not (d / f"{drop}.json").exists()
    assert (d / f"{keep}.json").exists() and (d / f"{keep}.out.json").exists()   # merged korunur
    ck = _check(root)
    assert ck.ilerleme["eski"] == 0 and ck.bitti


# -- aynı alıntının başka ölçüte taşınması ------------------------------------------------

def test_cross_package_prompt_lists_accepted_quotes_and_rule(cws):
    root, ids = cws
    A.prepare(root, profile=None, olcutler=["D.1.2"])
    pkg = json.loads((root / "work" / A.WORK / f"{ids['etk']}.json").read_text(encoding="utf-8"))
    assert "BAŞKA ÖLÇÜTLERDE KABUL EDİLDİ" in pkg["istem"] and "D.2.1/1" in pkg["istem"]
    assert "AYRI ve özgül" in pkg["istem"] and pkg["meta"]["ikinci_arama_kabul_notu"] is True
    # insanın reddettiği kabul notta yer almaz (etk_ret havuzda değil; arşiv yolunda da not yok)
    p = root / "work" / A.WORK / f"{ids['etk_ret']}.json"
    if p.exists():
        assert "BAŞKA ÖLÇÜTLERDE" not in json.loads(p.read_text(encoding="utf-8"))["istem"]
    assert "AYRI ve özgül" in (root / "work" / A.WORK / "README.md").read_text(encoding="utf-8")


def _answer_etk(root, ids, alinti):
    for p in (root / "work" / A.WORK).glob("*.json"):
        if p.stem != ids["etk"] and not p.name.endswith(".out.json"):
            _answer(root, p.stem, {"karar": "olcut_yok", "gerekce": "g", "birim_iliskisi": "kendi",
                                   "eslesmeler": []})
    _answer(root, ids["etk"], {"karar": "olcut_var", "gerekce": "g", "birim_iliskisi": "kendi",
                               "eslesmeler": [{"olcut": "D.1.2", "yuva": "D.1.2/1", "asama": "uygula",
                                               "od_onerisi": 2, "alinti": alinti, "gerekce": "g",
                                               "guven": "yuksek"}]})


def test_same_quote_accepted_elsewhere_is_flagged(cws):
    root, ids = cws
    A.prepare(root, profile=None, olcutler=["D.1.2"])
    _answer_etk(root, ids, Q_D21.upper())           # D.2.1'de kabul edilen alıntının aynısı (normalize)
    A.apply(root, model="m")
    m = next(x for x in _recs(root)[ids["etk"]]["eslesmeler"] if x.get("ikinci_arama"))
    assert A.AYNI_ALINTI in m["denetim"]["isaret"] and m["ayni_alinti_olcut"] == ["D.2.1"]
    assert m["kabul"]                                 # reddedilmez; karar incelemede
    from bidr.audit.sade import dikkat
    uy, bak = dikkat({"flags": m["denetim"]["isaret"], "ayni_alinti_olcut": m["ayni_alinti_olcut"],
                      "sayilir": True}, 2025)
    assert bak and any("Aynı alıntı D.2.1 ölçütünde zaten kabul" in x for x in uy)


def test_distinct_quote_not_flagged_and_merged_package_not_rewritten(cws):
    root, ids = cws
    A.prepare(root, profile=None, olcutler=["D.1.2"])
    _answer_etk(root, ids, Q_D12)
    A.apply(root, model="m")
    m = next(x for x in _recs(root)[ids["etk"]]["eslesmeler"] if x.get("ikinci_arama"))
    assert A.AYNI_ALINTI not in m["denetim"]["isaret"] and "ayni_alinti_olcut" not in m
    p = root / "work" / A.WORK / f"{ids['etk']}.json"
    before = p.read_text(encoding="utf-8")
    A.prepare(root, profile=None, olcutler=["D.1.2"])
    assert p.read_text(encoding="utf-8") == before                    # işlenmiş paket yerinde
    assert (root / "work" / A.WORK / f"{ids['etk']}.out.json").exists()


def test_mark_same_quote_ignores_human_rejected_and_short_containment():
    did = "d"
    first = {**_match("D.2.1", "D.2.1/1", Q_D21)}
    sec = {**_match("D.1.2", "D.1.2/1", Q_D21), "ikinci_arama": True}
    A.mark_same_quote(did, [first, sec], {f"{did}|D.2.1/1": {"karar": "ret"}})
    assert A.AYNI_ALINTI not in sec["denetim"]["isaret"]
    A.mark_same_quote(did, [first, sec])
    assert sec["ayni_alinti_olcut"] == ["D.2.1"]
    short = {**_match("D.1.2", "D.1.2/1", "katılmıştır"), "ikinci_arama": True}
    A.mark_same_quote(did, [first, short])
    assert "ayni_alinti_olcut" not in short
