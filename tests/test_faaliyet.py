"""Faaliyet kaydı (classify_fine v9 `faaliyet` alanı → bidr/faaliyet). Yalnız sentetik veri."""
from __future__ import annotations

import json

import pytest

from bidr.decide import run as R
from bidr.faaliyet import group as G
from bidr.faaliyet import run as F

from test_decide import FakeLLM, ws  # noqa: F401  (ws: fixture)

OK = {"karar": "olcut_yok", "birim_iliskisi": "kendi", "kanit_adi": "Örnek Belge Adı",
      "eslesmeler": [], "gerekce": ""}


# -- karar görevi ---------------------------------------------------------------------------

def test_schema_faaliyet_optional_and_validated():
    from bidr.llm import validate_output
    assert validate_output(R.FINE, OK)[0] is not None                      # v8 cevabı geçerli
    assert validate_output(R.FINE, {**OK, "faaliyet": None})[0] is not None
    for t in ("2025-03-12", "2025-03", None):
        f = {"ad": "Kariyer Günü", "tarih": t, "asama": "duyuru"}
        assert validate_output(R.FINE, {**OK, "faaliyet": f})[0] is not None
    bad = [{"ad": "Kariyer Günü", "tarih": "12.03.2025", "asama": "duyuru"},
           {"ad": "Kariyer Günü", "tarih": None, "asama": "yapildi"},
           {"ad": "Kariyer Günü", "asama": "duyuru"},
           {"ad": "K", "tarih": None, "asama": "duyuru"},
           {"ad": "Kariyer Günü", "tarih": None, "asama": "duyuru", "yer": "amfi"}]
    for f in bad:
        assert validate_output(R.FINE, {**OK, "faaliyet": f})[0] is None, f


def test_prompt_and_version():
    txt = (R.TASKS_DIR / R.FINE / "prompt.md").read_text(encoding="utf-8")
    assert '"faaliyet"' in txt and "duyuru gerçekleşmenin kanıtı değildir" in txt
    for a in G.ASAMALAR:
        assert a in txt
    sch = json.loads((R.TASKS_DIR / R.FINE / "output.schema.json").read_text(encoding="utf-8"))
    assert "faaliyet" not in sch["required"]
    assert set(sch["properties"]["faaliyet"]["properties"]["asama"]["enum"]) == set(G.ASAMALAR)
    assert R.task_version(R.FINE) == "9"


def test_activity_of_and_inherit():
    assert R.activity_of(OK) == {}                                         # eski cevap: alan yok
    assert R.activity_of({**OK, "faaliyet": None}) == {"faaliyet": None}
    f = {"ad": "  Kariyer   Günü ", "tarih": "2025-03-12", "asama": "duyuru"}
    assert R.activity_of({**OK, "faaliyet": f}) == {"faaliyet": {**f, "ad": "Kariyer Günü"}}
    rep = {"ince": {"karar": "olcut_yok", "gerekce": "", "birim_iliskisi": "kendi",
                    "faaliyet": {"ad": "Kariyer Günü", "tarih": None, "asama": "katilim"}}, "eslesmeler": []}
    assert R.rep_output(rep)["faaliyet"]["asama"] == "katilim"
    assert "faaliyet" not in R.rep_output({"ince": {"karar": "olcut_yok"}, "eslesmeler": []})


class Act(FakeLLM):
    def run_task(self, name, inputs, model, cache_dir, check=True):
        r = super().run_task(name, inputs, model, cache_dir, check)
        if name == R.FINE and "[EKLE]" in inputs["belge_metni"]:
            r.output["faaliyet"] = {"ad": "Bölüm Kurulu", "tarih": "2025-03-12", "asama": "gerceklesme"}
        return r


def test_apply_records_activity_end_to_end(ws, tmp_path):
    root, ids = ws
    R.run(root, backend=Act().backend(), log=lambda m: None)
    recs = {r["doc_id"]: r for r in map(json.loads, (root / "decisions.jsonl").read_text().splitlines())}
    x = ids["ekle"]
    assert recs[x]["ince"]["faaliyet"]["asama"] == "gerceklesme"
    assert recs[x]["gorev"][R.FINE] == "9"
    others = [r for d, r in recs.items() if d != x and r.get("asama") == "ince"]
    assert others and all("faaliyet" not in r["ince"] for r in others)     # alan yoksa kayda girmez
    dest, data = F.run(root)
    assert dest == root / "faaliyetler.json" and json.loads(dest.read_text(encoding="utf-8")) == data
    assert data["ozet"]["faaliyet"] == 1 and data["ozet"]["alansiz_eski"] == len(others)
    k = data["faaliyetler"][0]
    assert k["id"] == "F001" and k["asamalar"] == {"gerceklesme": [x]} and k["durum"] == "gerceklesme_kanitli"
    assert k["eksik"] == ["katilim yok", "degerlendirme yok"]
    assert k["belgeler"][0]["eslesmeler"] and all(m["olcut"] for m in k["belgeler"][0]["eslesmeler"])


# -- gruplama ---------------------------------------------------------------------------------

def _rec(did, ad, tarih, asama, rel="kendi", karar="olcut_yok"):
    return {"doc_id": did, "durum": "ok", "asama": "ince", "karar": karar, "eslesmeler": [],
            "ince": {"karar": karar, "birim_iliskisi": rel,
                     "faaliyet": None if ad is None else {"ad": ad, "tarih": tarih, "asama": asama}}}


def _by_doc(data):
    return {b["doc_id"]: k for k in data["faaliyetler"] for b in k["belgeler"]}


def test_full_activity_chain_links_and_complete():
    recs = [_rec("d1", "Kariyer Günü 2025", "2025-03-01", "duyuru"),
            _rec("d2", "Kariyer Günü", "2025-03-12", "gerceklesme"),
            _rec("d3", "Kariyer Günleri", "2025-03-12", "katilim"),
            _rec("d4", "Kariyer Günü Memnuniyet Anketi", "2025-04", "degerlendirme"),
            _rec("d5", "Kariyer Günü", "2025-09-20", "iyilestirme"),
            _rec("d6", "Kariyer Günü", None, "plan")]
    data = F.build(recs)
    assert len(data["faaliyetler"]) == 1
    k = data["faaliyetler"][0]
    assert set(k["asamalar"]) == {"duyuru", "plan", "gerceklesme", "katilim", "degerlendirme", "iyilestirme"}
    assert k["eksik"] == [] and k["durum"] == "gerceklesme_kanitli" and not k["yalniz_duyuru"]
    assert k["tarih"] == "2025-03-12" and k["ad"] == "Kariyer Günü"
    assert k["halkalar"] == ["planla", "uygula", "kontrol_et", "onlem_al"]
    assert any("d6" in n and "tarihsiz" in n for n in k["notlar"])


def test_announcement_only_activity_flagged():
    data = F.build([_rec("a1", "Matematik Semineri", "2025-05-02", "duyuru"),
                    _rec("a2", "Matematik Semineri", "2025-05-05", "duyuru")])
    (k,) = data["faaliyetler"]
    assert k["yalniz_duyuru"] and k["durum"] == "gerceklesme_kanitsiz"
    assert k["eksik"] == ["gerceklesme yok", "katilim yok", "degerlendirme yok"]
    assert k["halkalar"] == ["planla"] and data["ozet"]["yalniz_duyuru"] == 1


def test_recurring_meetings_stay_separate_and_announcement_goes_to_nearest():
    recs = [_rec("m1", "Bölüm Kurulu", "2025-03-12", "gerceklesme"),
            _rec("m2", "Bölüm Kurulu Toplantısı", "2025-04-10", "gerceklesme"),
            _rec("m3", "Bölüm Kurulu", "2025-04-03", "duyuru"),     # nisan toplantısının çağrısı
            _rec("m4", "Bölüm Kurulu", None, "katilim")]            # tarihsiz: iki aday, bağlanmaz
    data = F.build(recs)
    by = _by_doc(data)
    assert by["m1"] is not by["m2"] and by["m3"] is by["m2"]
    assert len(by["m4"]["belgeler"]) == 1 and any("bağlanmadı" in n for n in by["m4"]["notlar"])
    assert [k["id"] for k in data["faaliyetler"]] == ["F001", "F002", "F003"]


def test_announcement_after_event_or_far_before_not_linked():
    recs = [_rec("e1", "Kariyer Günü", "2025-03-12", "gerceklesme"),
            _rec("e2", "Kariyer Günü", "2025-03-30", "duyuru"),   # olaydan sonra duyuru: başka faaliyet
            _rec("e3", "Kariyer Günü", "2024-12-01", "duyuru")]   # 45 günden önce
    by = _by_doc(F.build(recs))
    assert by["e2"] is not by["e1"] and by["e3"] is not by["e1"]


def test_different_names_or_numbers_not_merged():
    recs = [_rec("n1", "Kariyer Günü", "2025-03-12", "gerceklesme"),
            _rec("n2", "Mezunlar Buluşması", "2025-03-12", "gerceklesme"),
            _rec("n3", "Bölüm Kurulu 2025/3", "2025-03-12", "gerceklesme"),
            _rec("n4", "Bölüm Kurulu 2025/4", "2025-03-13", "gerceklesme"),
            _rec("n5", "Kariyer Günü", "2026-03-12", "degerlendirme")]   # bir yıl sonra
    by = _by_doc(F.build(recs))
    assert len({id(k) for k in by.values()}) == 5


def test_exclusions_and_old_records():
    recs = [_rec("x1", "Kariyer Günü", "2025-03-12", "gerceklesme"),
            _rec("x2", "Kimya Günü", "2025-03-12", "gerceklesme", rel="baska_birim", karar="kanit_degil"),
            _rec("x3", None, None, None),
            {"doc_id": "x4", "durum": "ok", "asama": "ince", "ince": {"karar": "olcut_yok"}},   # v8
            {"doc_id": "x5", "durum": "ok", "asama": "ince", "ince": {"karar": "atlandi"}},
            {"doc_id": "x6", "durum": "ok", "asama": "kaba", "kaba": {}}]
    data = F.build(recs)
    assert [b["doc_id"] for k in data["faaliyetler"] for b in k["belgeler"]] == ["x1"]
    assert data["ozet"] == {"ince": 4, "faaliyetli": 1, "faaliyetsiz": 1, "alansiz_eski": 1, "baska_birim": 1,
                            "faaliyet": 1, "yalniz_duyuru": 0, "gerceklesme_kanitsiz": 0}


def test_indirect_realisation_and_bad_date():
    data = F.build([_rec("i1", "Oryantasyon", "2025-09-31", "katilim"),     # geçersiz gün
                    _rec("i2", "Oryantasyon Programı", "2025-09", "degerlendirme")])
    by = _by_doc(data)
    assert by["i1"] is by["i2"]                                             # tarihsiz → tek aday
    k = by["i1"]
    assert k["durum"] == "gerceklesme_dolayli" and k["eksik"] == ["gerceklesme yok", "iyilestirme yok"]
    assert any("geçersiz tarih" in n for n in k["notlar"])


@pytest.mark.parametrize("a,b,same", [
    ("Kariyer Günü", "KARİYER GÜNÜ", True),
    ("Bölüm Kurulu", "Bölüm Kurulu Toplantısı", True),
    ("Öğrenci Temsilcisi Seçimi", "Ogrenci Temsilcisi Secimi", True),
    ("Kariyer Günü", "Mezun Günü", False),
    ("Bölüm Kurulu", "Bölüm Kurumu", False),
    ("Kariyer Günü", "Kariyer Günleri", True),
    ("Kariyer Günü 2024", "Kariyer Günü 2025", False),
])
def test_name_similarity(a, b, same):
    assert G.similar(G.parse_name(a), G.parse_name(b)) is same


def test_cli_table(ws, capsys):
    from bidr.cli import main
    root, ids = ws
    with pytest.raises(SystemExit):
        main(["faaliyet"])
    assert main(["faaliyet", "-w", str(root)]) == 2                       # decisions.jsonl yok
    recs = [_rec("d1", "Kariyer Günü", "2025-03-01", "duyuru"), _rec("d2", "Bölüm Kurulu", "2025-03-12", "gerceklesme")]
    (root / "decisions.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs),
                                          encoding="utf-8")
    capsys.readouterr()
    assert main(["faaliyet", "-w", str(root)]) == 0
    out = capsys.readouterr().out
    assert "2 faaliyet" in out and "YALNIZ DUYURU" in out and "Kariyer Günü" in out and "UYARI: 1" in out
    assert (root / "faaliyetler.json").exists()
