"""Birim farkındalığı (classify_fine v8 `birim_iliskisi`): istemde birim, apply kuralları,
OD2 tavanı, başka birimin reddi, belirsiz işareti, audit/gaps çıktıları, geri uyumluluk.
Yalnız sentetik veri (gerçek kurum belgesi, kişi adı yok)."""
from __future__ import annotations

import json

import pytest
from openpyxl import load_workbook

from bidr.audit.run import audit, build
from bidr.audit.sheet import COLS, SHEET_ROWS
from bidr.common import read_jsonl
from bidr.decide import prompt as P
from bidr.decide import run as R
from bidr.decide.run import apply, check_matches, prepare

from synth import CS
from test_decide import DOCS, Q_B23, TAGS, FakeLLM, _agent, ws  # noqa: F401  (ws: fixture)

ALL = R.BIRIM_ILISKILERI


def _recs(root):
    return {r["doc_id"]: r for r in read_jsonl(root / "decisions.jsonl")}


def _config(root, birim="Örnek Bölümü", kurum=None):
    sec = {"birim": birim, "profil": "akademik_bolum", "donem": 2025}
    if kurum:
        sec["kurum"] = kurum
    import yaml
    (root / "config.yaml").write_text(yaml.safe_dump({"bidr": sec}, allow_unicode=True), encoding="utf-8")


class Rel(FakeLLM):
    """[EKLE] belgesinin ince cevabında birim ilişkisini değiştirir (eşleşmeler aynı kalır:
    model başka birim deyip eşleşme verse de kod reddetmeli)."""

    def __init__(self, rel):
        super().__init__()
        self.rel = rel

    def run_task(self, name, inputs, model, cache_dir, check=True):
        r = super().run_task(name, inputs, model, cache_dir, check)
        if name == R.FINE and "[EKLE]" in inputs["belge_metni"]:
            r.output["birim_iliskisi"] = self.rel
        return r


# -- birim bilgisi istemde ------------------------------------------------------------

def test_unit_info_from_config(tmp_path, monkeypatch):
    inst = tmp_path / "kurumlar"
    inst.mkdir()
    (inst / "ornek.yaml").write_text("kurum: ornek\nad: Örnek Üniversitesi\n", encoding="utf-8")
    monkeypatch.setenv("BIDR_INSTITUTIONS_DIR", str(inst))
    w = tmp_path / "w"
    w.mkdir()
    assert P.unit_info(w) == {"birim": None, "kurum": None}
    assert "belirtilmedi" in P.render_unit(P.unit_info(w))
    _config(w, "Matematik Bölümü", "ornek")
    info = P.unit_info(w)
    assert info == {"birim": "Matematik Bölümü", "kurum": "Örnek Üniversitesi"}
    assert P.render_unit(info) == "Birim: Matematik Bölümü\nKurum: Örnek Üniversitesi"
    _config(w, "Matematik Bölümü", "yok_boyle")           # bilinmeyen kurum profili: yalnız birim
    assert P.render_unit(P.unit_info(w)) == "Birim: Matematik Bölümü"


def test_fine_package_carries_unit(ws):
    root, ids = ws
    _config(root, "Matematik Bölümü")
    fake = FakeLLM()
    b = fake.backend()
    prepare(root, "coarse", backend=b)
    _agent(root, fake, "coarse")
    apply(root, "coarse", backend=b)
    prepare(root, "fine", backend=b)
    pkg = json.loads((root / "work" / "fine" / f"{ids['ekle']}.json").read_text(encoding="utf-8"))
    assert "BİRİM (bu rapor yalnız bu birim için hazırlanıyor)\nBirim: Matematik Bölümü" in pkg["istem"]
    assert "birim_iliskisi" in pkg["sema"]["required"]
    # kaba istem değişmedi (birim yalnız ince karara girer)
    cp = json.loads((root / "work" / "coarse" / f"{ids['ekle']}.json").read_text(encoding="utf-8"))
    assert "Matematik" not in cp["istem"]


# -- şema --------------------------------------------------------------------------------

def test_schema_rejects_invalid_relation(ws):
    from bidr.llm import validate_output
    ok = {"karar": "olcut_yok", "birim_iliskisi": "kendi", "kanit_adi": "Örnek Belge Adı",
          "eslesmeler": [], "gerekce": ""}
    for v in ALL:
        assert validate_output(R.FINE, {**ok, "birim_iliskisi": v})[0] is not None
    assert validate_output(R.FINE, {**ok, "birim_iliskisi": "yan_birim"})[0] is None
    assert validate_output(R.FINE, {k: v for k, v in ok.items() if k != "birim_iliskisi"})[0] is None
    assert validate_output(R.FINE, {**ok, "kurum_geneli": False})[0] is None   # eski alan artık yok
    # ajan modu: geçersiz değerli cevap işlenmez
    root, ids = ws
    fake = FakeLLM()
    b = fake.backend()
    prepare(root, "coarse", backend=b)
    _agent(root, fake, "coarse")
    apply(root, "coarse", backend=b)
    prepare(root, "fine", backend=b)
    _agent(root, fake, "fine")
    x = ids["ekle"]
    outp = root / "work" / "fine" / f"{x}.out.json"
    out = json.loads(outp.read_text(encoding="utf-8"))
    outp.write_text(json.dumps({**out, "birim_iliskisi": "fakulte"}, ensure_ascii=False), encoding="utf-8")
    st = apply(root, "fine", backend=b)
    assert x in st["gecersiz"] and _recs(root)[x].get("asama") != "ince"


# -- apply kuralları ----------------------------------------------------------------------

M = {"olcut": "B.2.3", "yuva": "B.2.3/2", "asama": "uygula", "od_onerisi": 3, "alinti": Q_B23,
     "gerekce": "g", "guven": "orta"}
TEXT = "KOMİSYON TUTANAĞI\n" + Q_B23


@pytest.mark.parametrize("rel", ALL)
def test_check_matches_per_relation(rel):
    kurum = rel in R.GENEL_ILISKI
    m = check_matches({"eslesmeler": [M]}, ["B.2.3"], CS, TAGS, TEXT, FakeLLM.verify_quote, kurum, rel)[0]
    red, isaret = m["denetim"]["red"], m["denetim"]["isaret"]
    if rel == "baska_birim":
        assert not m["kabul"] and red == ["baska_birim"] and m["od_kabul"] is None
        return
    assert m["kabul"] and not red
    assert m["od_kabul"] == (2 if kurum else 3)
    assert ("uygulama_kaniti_eksik" in isaret) == kurum
    assert ("birim_aitligi_dogrulanmali" in isaret) == (rel == "belirsiz")


@pytest.mark.parametrize("rel", ALL)
def test_apply_per_relation_end_to_end(ws, rel):
    root, ids = ws
    x = ids["ekle"]
    _, st = R.run(root, backend=Rel(rel).backend(), log=lambda m: None)
    rec = _recs(root)[x]
    ince = rec["ince"]
    assert ince["birim_iliskisi"] == rel and ince["birim_iliskisi_kaynagi"] == "model"
    m = rec["eslesmeler"][0]
    if rel == "baska_birim":
        # model eşleşme verse de kod reddeder; karar kanıt değil, gerekçe kayıtta
        assert not m["kabul"] and "baska_birim" in m["denetim"]["red"]
        assert rec["karar"] == "kanit_degil" and rec["olcutler"] == [] and rec["reddedilen_eslesme"] == 1
        assert "gerekce" in ince and st["baska_birim"] == 1 and st["kanit_degil"] >= 1
        return
    assert m["kabul"] and rec["karar"] == "olcut_var"
    genel = rel in R.GENEL_ILISKI
    assert m["od_kabul"] == (2 if genel else 3) and rec["olcutler"][0]["od"] == (2 if genel else 3)
    assert ince["kurum_geneli"] == {"model": genel, "tur": False, "karar": genel}
    assert st["od_tavan"] == int(genel) and st["birim_belirsiz"] == int(rel == "belirsiz")
    assert st["baska_birim"] == 0


def test_ust_birim_not_capped_but_regulation_type_still_is(ws):
    """Üst birimin bu birim hakkındaki kararı OD tavanı almaz; ama yönerge türü (tek başına
    kural tanımı) birim ilişkisinden bağımsız OD2'dir."""
    root, ids = ws
    x = ids["ekle"]
    rows = list(read_jsonl(root / "documents.jsonl"))
    for r in rows:
        if r["doc_id"] == x:
            r["doc_type"] = "yonerge"
    (root / "documents.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                                          encoding="utf-8")
    R.run(root, backend=Rel("ust_birim_bu_birim_hakkinda").backend(), log=lambda m: None)
    m = _recs(root)[x]["eslesmeler"][0]
    assert m["od_kabul"] == 2 and "uygulama_kaniti_eksik" in m["denetim"]["isaret"]


def test_agent_apply_lists_other_unit_and_uncertain(ws):
    root, ids = ws
    x = ids["ekle"]
    for rel, key in (("baska_birim", "baska_birim"), ("belirsiz", "birim_belirsiz")):
        fake = Rel(rel)
        b = fake.backend()
        for st_ in ("coarse", "fine"):
            prepare(root, st_, backend=b, only=[x] if st_ == "fine" and key == "birim_belirsiz" else None)
            _agent(root, fake, st_)
            st = apply(root, st_, backend=b)
        assert st[key] == [x]
        # başka birim reddi "alıntı tutmuyor" yeniden yapılacak işi sayılmaz
        assert x not in st["alinti_tutmayan"]
        assert st["durum"][key] == 1


# -- audit: review.xlsx sütunu, gaps.md listeleri, OD2 tavanı ---------------------------

def _m(olcut, yuva, asama, od, isaret=()):
    return {"olcut": olcut, "yuva": yuva, "asama": asama, "od_onerisi": od, "alinti": "x" * 30,
            "gerekce": "g", "guven": "orta", "denetim": {"red": [], "isaret": list(isaret)},
            "od_kabul": od, "kabul": True}


def _audit_ws(tmp_path, recs: dict, types: dict | None = None):
    w = tmp_path / "aw"
    w.mkdir()
    with open(w / "decisions.jsonl", "w", encoding="utf-8") as f:
        for did, (ince, ms) in recs.items():
            f.write(json.dumps({"doc_id": did, "durum": "ok", "asama": "ince",
                                "karar": "olcut_var" if any(m["kabul"] for m in ms) else "kanit_degil",
                                "ince": ince, "eslesmeler": ms}, ensure_ascii=False) + "\n")
    with open(w / "documents.jsonl", "w", encoding="utf-8") as f:
        for did in recs:
            f.write(json.dumps({"doc_id": did, "doc_type": (types or {}).get(did, "toplanti_tutanagi"),
                                "calisma_adi": f"2025_{did}"}) + "\n")
    return w


def test_audit_relation_column_flags_and_gaps(tmp_path):
    red = {**_m("B.1.1", "B.1.1/3", "uygula", 3), "kabul": False, "od_kabul": None,
           "denetim": {"red": ["baska_birim"], "isaret": []}}
    w = _audit_ws(tmp_path, {
        "d_kendi": ({"karar": "olcut_var", "birim_iliskisi": "kendi"}, [_m("B.1.1", "B.1.1/1", "planla", 2)]),
        "d_belirsiz": ({"karar": "olcut_var", "birim_iliskisi": "belirsiz", "gerekce": "bölüm adı yok"},
                       [_m("B.1.1", "B.1.1/3", "uygula", 3, ["birim_aitligi_dogrulanmali"])]),
        "d_fak": ({"karar": "olcut_var", "birim_iliskisi": "fakulte_geneli"},
                  [_m("B.2.3", "B.2.3/1", "planla", 2, ["uygulama_kaniti_eksik"])]),
        "d_kimya": ({"karar": "kanit_degil", "birim_iliskisi": "baska_birim",
                     "gerekce": "Kimya Bölümü laboratuvar tutanağı"}, [red]),
        "d_senato": ({"karar": "olcut_var", "birim_iliskisi": "ust_birim_bu_birim_hakkinda"},
                     [_m("B.2.3", "B.2.3/2", "uygula", 3)]),
        "d_senato2": ({"karar": "olcut_var", "birim_iliskisi": "kendi"}, [_m("A.1.1", "A.1.1/2", "uygula", 3)]),
    }, types={"d_senato": "senato_karari", "d_senato2": "senato_karari"})
    a, paths = audit(w)
    rows = a.by_key
    assert "d_kimya|B.1.1/3" not in rows                       # başka birim: tabloya gelmez
    r = rows["d_belirsiz|B.1.1/3"]
    # yükleyen birimin belgesi varsayılır (kullanıcı kararı 2026-11-26): metinde başka birimin adı yoksa sayılır,
    # sorulmaz; sessiz `birim_varsayildi` (çelişkili durum: test_birim_sinyal.py)
    assert r["sayilir"] and r["birim_iliskisi"] == "belirsiz" and not r["birim_onay_bekliyor"]
    assert "birim_varsayildi" in r["flags"] and "birim_aitligi_dogrulanmali" not in r["flags"]
    assert "BİRİM AİTLİĞİ" not in r["vurgu"]
    f = rows["d_fak|B.2.3/1"]
    assert {"kurum_geneli", "fakulte_geneli"} <= set(f["flags"]) and f["etkin_asama"] == "planla"
    # üst birimin bu birim hakkındaki senato kararı tür yüzünden planla'ya inmez; kendi senato kararı iner
    s1, s2 = rows["d_senato|B.2.3/2"], rows["d_senato2|A.1.1/2"]
    assert s1["etkin_asama"] == "uygula" and "kurum_geneli" not in s1["flags"]
    assert s2["etkin_asama"] == "planla" and "kurum_geneli" in s2["flags"]
    # review.xlsx sütunu
    wb = load_workbook(paths["xlsx"])
    sh = wb[SHEET_ROWS]
    head = [c.value for c in sh[1]]
    col = head.index(dict((k, h) for k, h, _, _ in COLS)["birim_iliskisi"])
    vals = {row[0].value: row[col].value for row in sh.iter_rows(min_row=2)}
    assert vals["d_belirsiz|B.1.1/3"] == "belirsiz" and vals["d_kendi|B.1.1/1"] == "kendi"
    # gaps.md listeleri
    g = paths["gaps"].read_text(encoding="utf-8")
    assert "## Birim aitliği doğrulanmalı" not in g and "onay bekliyor" not in g
    assert "## Başka birime ait sayılan belgeler" in g and "Kimya Bölümü laboratuvar tutanağı" in g
    assert "--only" in g
    js = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert [x["doc_id"] for x in js["birim_aitligi"]["baska_birim"]] == ["d_kimya"]
    assert js["birim_aitligi"]["belirsiz"] == []                # çelişkisiz belirsiz sorulmaz


def test_audit_fakulte_cap_lowers_criterion_od(tmp_path):
    w = _audit_ws(tmp_path, {
        "d_plan": ({"birim_iliskisi": "kendi"}, [_m("B.1.1", "B.1.1/1", "planla", 2)]),
        # decide tavanı uygulanmış olsa da olmasa da (elle kayıt) audit uygulamayı saymaz
        "d_fak": ({"birim_iliskisi": "fakulte_geneli"}, [_m("B.1.1", "B.1.1/3", "uygula", 3)]),
    })
    a = build(w)
    c = next(c for c in a.criteria if c["olcut"] == "B.1.1")
    assert c["od"] == 2 and "uygulama_kaniti_eksik" in a.by_key["d_fak|B.1.1/3"]["flags"]
    assert c["kurum_geneli_yalniz"]


# -- geri uyumluluk ------------------------------------------------------------------------

def test_backward_compat_relation():
    assert R.unit_relation({"kurum_geneli": True}) == ("kurum_geneli", "eski_alan")
    assert R.unit_relation({"kurum_geneli": False}) == ("kendi", "varsayilan")
    assert R.unit_relation({}) == ("kendi", "varsayilan")          # belirsiz değil
    assert R.unit_relation({"birim_iliskisi": "bilinmez"}) == ("kendi", "varsayilan")
    old_kg = {"ince": {"kurum_geneli": {"model": True, "tur": False, "karar": True}}}
    old_tur = {"ince": {"kurum_geneli": {"model": False, "tur": True, "karar": True}}}
    assert R.record_unit_relation(old_kg) == "kurum_geneli"
    assert R.record_unit_relation(old_tur) == "kendi"               # tür tavanı ayrı kural
    assert R.record_unit_relation({"ince": {}}) == "kendi"
    assert R.record_unit_relation(None) == "kendi"
    # eski cevabın kurum_geneli bayrağı tavanı hâlâ tetikler
    assert R.kurum_geneli({"kurum_geneli": True}, None, frozenset())["karar"] is True
    assert R.kurum_geneli({"kurum_geneli": False}, None, frozenset()) == {"model": False, "tur": False,
                                                                            "karar": False}


def test_old_v7_records_audit_and_reprepare(ws):
    """v7 kayıtları (birim_iliskisi yok): audit `kurum_geneli` true → kurum geneli, yoksa kendi;
    görev sürümü değiştiği için prepare onay ister, --yes ile birimli yeni istemle paketlenir."""
    root, ids = ws
    _config(root, "Matematik Bölümü")
    fake = FakeLLM()
    b = fake.backend()
    for st in ("coarse", "fine"):
        prepare(root, st, backend=b)
        _agent(root, fake, st)
        apply(root, st, backend=b)
    recs = _recs(root)
    # v7 kaydına çevir: yeni alanlar yok, eski kurum_geneli bayrağı var
    for did, r in recs.items():
        if r.get("asama") == "ince":
            r["gorev"]["classify_fine"] = "7"
            r["ince"].pop("birim_iliskisi", None)
            r["ince"].pop("birim_iliskisi_kaynagi", None)
            r["ince"]["kurum_geneli"] = {"model": did == ids["aynı"], "tur": False, "karar": did == ids["aynı"]}
    (root / "decisions.jsonl").write_text("".join(json.dumps(recs[k], ensure_ascii=False) + "\n"
                                                  for k in sorted(recs)), encoding="utf-8")
    a = build(root)
    rels = {r["doc_id"]: r["birim_iliskisi"] for r in a.rows}
    assert rels[ids["aynı"]] == "kurum_geneli" and rels[ids["ekle"]] == "kendi"
    assert "kurum_geneli" in a.by_key[f"{ids['aynı']}|B.1.1/1"]["flags"]
    assert a.birim == {"baska_birim": [], "belirsiz": []}

    st = prepare(root, "fine", backend=b)
    assert st["onay_gerekli"] and set(st["eski"].values()) == {"eski_surum"}
    st = prepare(root, "fine", backend=b, yes=True)
    assert st["yeni"] >= 1 and not st["onay_gerekli"]
    pkg = json.loads((root / "work" / "fine" / f"{ids['ekle']}.json").read_text(encoding="utf-8"))
    assert pkg["surum"] == "10" and "Birim: Matematik Bölümü" in pkg["istem"]
    assert _recs(root)[ids["ekle"]]["yeniden"]["onceki_surum"] == "7"


def test_inherit_from_old_representative_keeps_old_flag():
    rep = {"ince": {"karar": "olcut_var", "gerekce": "", "kurum_geneli": {"model": True, "tur": False,
                                                                          "karar": True}},
           "eslesmeler": []}
    out = R.rep_output(rep)
    assert "birim_iliskisi" not in out and out["kurum_geneli"] is True
    assert R.unit_relation(out) == ("kurum_geneli", "eski_alan")
    rep["ince"]["birim_iliskisi"] = "belirsiz"
    assert R.rep_output(rep)["birim_iliskisi"] == "belirsiz"
