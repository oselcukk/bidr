"""Bitmiş raporu yeni araç sürümüyle güncelleme: identify sürüm/dönem damgası, istem değişiminde
belgeye özgü girdi ↔ ortak kural ayrımı, paket klasöründeki yardımcı dosyalar, apply'ın yalnız
değişen belgeleri işlemesi ve ikinci arama eşleşmelerini koruması. Sahte model; sentetik veri."""
from __future__ import annotations

import json

import pytest

from bidr.candidates import arama as A
from bidr.common import Workspace, read_jsonl
from bidr.decide import run as R
from bidr.decide.run import Context, apply, prepare
from bidr.pipeline.checks import Ctx, identify_tamam, karar_tamam

from test_decide import DOCS, FakeLLM, _agent, ws  # noqa: F401  (ws: fixture)

RULE = "\n\nEk ortak kural: tabloda başlığı değil ilgili satırı alıntıla.\n"


def _recs(root):
    return {r["doc_id"]: r for r in read_jsonl(root / "decisions.jsonl")}


def _save(root, recs):
    (root / "decisions.jsonl").write_text("".join(json.dumps(recs[k], ensure_ascii=False) + "\n"
                                                  for k in sorted(recs)), encoding="utf-8")


def _check(root, stage):
    return karar_tamam(Ctx(Workspace(root), {}, lambda x: x,
                           {"sart": {"asama": stage}, "komut": ["PREP", "(ajan)", "APPLY"]}))


def _full(root, fake, b):
    for stage in ("coarse", "fine"):
        prepare(root, stage, backend=b)
        _agent(root, fake, stage)
        apply(root, stage, model="ajan", backend=b)


def _legacy(root, stage="fine"):
    """Eski sürümün kaydı ve paketi: girdi izi ve denetim sürümü yok."""
    sec = "ince" if stage == "fine" else "kaba"
    recs = _recs(root)
    for r in recs.values():
        if sec in r:
            r[sec].pop("girdi_sha", None)
            r[sec].pop("denetim_surumu", None)
    _save(root, recs)
    for p in (root / "work" / stage).glob("*.json"):
        if not p.name.endswith(".out.json"):
            pkg = json.loads(p.read_text(encoding="utf-8"))
            pkg.pop("girdi_sha", None)
            p.write_text(json.dumps(pkg, ensure_ascii=False), encoding="utf-8")


# -- 1. identify: araç sürümü ve dönem -----------------------------------------------------------

def _id_ws(tmp_path, recs):
    root = tmp_path / "w"
    (root / "text").mkdir(parents=True)
    for r in recs:
        (root / "text" / f"{r['doc_id']}.txt").write_text("metin", encoding="utf-8")
    (root / "documents.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
    return Ctx(Workspace(root), {"donem": 2025}, lambda x: x, {"komut": ["IDENTIFY"]})


def test_identify_old_version_or_missing_period_is_not_done(tmp_path):
    from bidr.identify.pipeline import ARAC_SURUMU
    ck = identify_tamam(_id_ws(tmp_path / "a", [{"doc_id": "a1", "donem": 2025}]))
    assert not ck.bitti and ck.kim == "komut" and "eski (araç sürümü değişti" in ck.neden
    ck = identify_tamam(_id_ws(tmp_path / "b", [{"doc_id": "a1", "arac_surumu": ARAC_SURUMU, "donem": None}]))
    assert not ck.bitti and "dönem alanı boş" in ck.neden and ck.ilerleme["donem_eksik"] == 1
    ck = identify_tamam(_id_ws(tmp_path / "c", [{"doc_id": "a1", "arac_surumu": ARAC_SURUMU, "donem": 2025}]))
    assert ck.bitti


def test_identify_writes_version(tmp_path):
    from bidr.identify.pipeline import ARAC_SURUMU, run
    from synth import make_ws
    root = make_ws(tmp_path / "ws", [{"text": "BÖLÜM KURULU KARARI 12.03.2025 tarihli toplantı."}])
    recs = run(root, period=2025, write_report=False, log=lambda m: None)
    assert recs[0]["arac_surumu"] == ARAC_SURUMU and recs[0]["donem"] == 2025


# -- 2. istem değişti: belgeye özgü girdi ↔ ortak kural ---------------------------------------------

@pytest.mark.parametrize("legacy", [False, True])
def test_rule_only_change_keeps_records(ws, legacy):
    root, ids = ws
    fake = FakeLLM()
    b = fake.backend()
    _full(root, fake, b)
    if legacy:
        _legacy(root)
    before = _recs(root)
    fake.prompts[R.FINE] += RULE                       # yalnız ortak kural metni değişti
    st = prepare(root, "fine", backend=b)
    assert st["paket"] == 0 and st["kural_eski"] == 4 and not st["onay_gerekli"]
    assert set(st["eski"].values()) == {"kural_degisti"}
    recs = _recs(root)
    assert all("yeniden" not in r for r in recs.values())
    assert all(recs[k].get("eslesmeler") == before[k].get("eslesmeler") for k in before)
    if legacy:                                          # eski kayda girdi izi işlendi (sonraki kez doğrudan)
        assert all(isinstance(r["ince"].get("girdi_sha"), dict) for r in recs.values() if "ince" in r
                   and r["ince"].get("istem_sha"))
    ck = _check(root, "fine")
    assert ck.bitti and ck.ilerleme["istem_surumu_eski"] == 4 and "yeniden_islenecek" not in ck.ilerleme
    assert [u for u in ck.uyarilar if u.startswith("istem sürümü eski: 4 belge")]
    st = prepare(root, "fine", backend=b, yes=True)     # toptan yeniden işleme yalnız açık istekle
    assert st["paket"] == 4 and all(r.get("yeniden", {}).get("neden") == "kural_degisti"
                                    for k, r in _recs(root).items() if k != ids["rapor"])


@pytest.mark.parametrize("legacy", [False, True])
def test_doc_input_change_repackages_only_that_doc(ws, legacy):
    root, ids = ws
    fake = FakeLLM()
    b = fake.backend()
    _full(root, fake, b)
    if legacy:
        _legacy(root)
    x = ids["aynı"]
    fake.prompts[R.FINE] += RULE
    rows = list(read_jsonl(root / "candidates.jsonl"))
    for r in rows:                                      # bu belgenin aday listesi değişti
        if r["doc_id"] == x:
            r["adaylar"] = [{"olcut": "B.1.1"}, {"olcut": "B.2.3"}]
    (root / "candidates.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    st = prepare(root, "fine", backend=b)
    assert st["girdi_degisti"] == 1 and st["paket"] == 1 and st["kural_eski"] == 3
    assert _recs(root)[x]["yeniden"]["neden"] == "girdi_degisti"
    assert (root / "work" / "fine" / f"{x}.out.json.eski").exists()
    ck = _check(root, "fine")
    assert not ck.bitti and ck.kim == "ajan" and ck.ilerleme["cevapsiz"] == 1
    _agent(root, fake, "fine")
    st = apply(root, "fine", model="ajan", backend=b)
    # eski sürümün kaydı (denetim sürümü yok) bir kez yeniden uygulanır; sonra yalnız değişen
    assert (st["islenen"], st["degismedi"]) == ((4, 0) if legacy else (1, 3))
    ck = _check(root, "fine")
    assert ck.bitti and ck.ilerleme["istem_surumu_eski"] == 3


def test_status_asks_prepare_after_tool_change(ws, monkeypatch):
    root, ids = ws
    fake = FakeLLM()
    _full(root, fake, fake.backend())
    assert _check(root, "fine").bitti
    monkeypatch.setattr(R, "input_fingerprint", lambda ws, stage: "baska")
    ck = _check(root, "fine")
    assert not ck.bitti and ck.komutlar == ["PREP"] and "araç sürümü" in ck.neden
    prepare(root, "fine", backend=fake.backend())
    assert _check(root, "fine").bitti


# -- 3. yardımcı dosyalar paket sayılmaz ----------------------------------------------------------

def test_apply_ignores_helper_files_and_readme_counts(ws):
    root, ids = ws
    fake = FakeLLM()
    b = fake.backend()
    prepare(root, "coarse", backend=b)
    _agent(root, fake, "coarse")
    apply(root, "coarse", model="ajan", backend=b)
    d = root / "work" / "fine"
    d.mkdir(parents=True, exist_ok=True)
    (d / "YENIDEN.json").write_text(json.dumps({"gorev": R.FINE, "belgeler": {"x": "istem_degisti"}}),
                                    encoding="utf-8")       # eski sürümün yardımcı dosyası
    (d / "_not.json").write_text("{}", encoding="utf-8")
    st = prepare(root, "fine", backend=b)
    assert not (d / "YENIDEN.json").exists() and st["bekleyen"] == 4
    assert "Bekleyen paket: 4" in (d / "README.md").read_text(encoding="utf-8")
    (d / "YENIDEN.json").write_text("{}", encoding="utf-8")
    (d / "bozuk.json").write_text(json.dumps({"belgeler": {}}), encoding="utf-8")   # doc_id yok
    _agent_safe(root, fake)
    st = apply(root, "fine", model="ajan", backend=b)
    assert st["islenen"] == 4 and st["paket_degil"] == ["bozuk.json"]


def _agent_safe(root, fake):
    d = root / "work" / "fine"
    for p in R._pkg_paths(d):
        pkg = R._load_pkg(p)
        if pkg:
            (d / pkg["cikti_dosyasi"]).write_text(json.dumps(fake.answer(pkg["gorev"], pkg["istem"]),
                                                             ensure_ascii=False), encoding="utf-8")


# -- 4. apply yalnız değişeni işler, ikinci arama eşleşmeleri korunur ------------------------------

Q_EK = "Sonuç oy birliğiyle kabul edildi."


def _second_search(root, did):
    """Kayda ikinci arama eşleşmesi ekler (arama.merge; arşiv araması olmadan)."""
    ctx = Context.load(root, profile=None)
    recs = _recs(root)
    rec = recs[did]
    pkg = {"istem_sha": "paket1", "meta": {"adaylar": ["B.1.1"], "ikinci_arama": {
        "olcutler": [{"olcut": "B.1.1", "puan": 1.0, "sira": 1, "nedenler": ["kanitsiz"]}],
        "ince_parmak": A.first_pass_print(rec)}}}
    out = {"karar": "olcut_var", "gerekce": "g", "birim_iliskisi": "kendi", "eslesmeler": [
        {"olcut": "B.1.1", "yuva": "B.1.1/1", "asama": "planla", "od_onerisi": 2, "alinti": Q_EK,
         "gerekce": "karar", "guven": "orta"}]}
    rec, new = A.merge(ctx, did, rec, out, pkg, "ajan", FakeLLM.verify_quote, "cevap1")
    assert new[0]["kabul"]
    recs[did] = rec
    _save(root, recs)
    return pkg


def test_apply_skips_unchanged_and_keeps_second_search(ws):
    root, ids = ws
    fake = FakeLLM()
    b = fake.backend()
    _full(root, fake, b)
    x = ids["ekle"]
    pkg = _second_search(root, x)
    st = apply(root, "fine", model="baska-ajan", backend=b)           # hiçbir cevap değişmedi
    assert st["islenen"] == 0 and st["degismedi"] == 4
    rec = _recs(root)[x]
    assert [m["olcut"] for m in rec["eslesmeler"] if m.get("ikinci_arama")] == ["B.1.1"]

    _legacy(root)                                                       # eski sürümle işlenmiş kayıt
    st = apply(root, "fine", model="baska-ajan", backend=b)            # kod denetimi değişti: yeniden uygula
    assert st["islenen"] == 4
    rec = _recs(root)[x]
    ia = [m for m in rec["eslesmeler"] if m.get("ikinci_arama")]
    assert len(ia) == 1 and ia[0]["kabul"] and "ikinci_arama" in ia[0]["denetim"]["isaret"]
    assert ia[0]["ikinci_arama_paket"] == "paket1"
    assert {o["olcut"] for o in rec["olcutler"]} == {"B.2.3", "B.1.1"}
    assert rec["ince"]["denetim_surumu"] == R.DENETIM_SURUMU
    assert A.done_criteria(rec) == {"B.1.1"}                            # ikinci arama yeniden istenmez
    assert A.merged(rec, pkg, "cevap1")
    assert apply(root, "fine", model="baska-ajan", backend=b)["degismedi"] == 4


def test_redecided_doc_keeps_second_search_unless_first_pass_takes_slot(ws):
    root, ids = ws
    fake = FakeLLM()
    b = fake.backend()
    _full(root, fake, b)
    x = ids["ekle"]
    _second_search(root, x)
    prepare(root, "fine", backend=b, only=[x])
    _agent(root, fake, "fine")
    apply(root, "fine", model="ajan2", backend=b)
    rec = _recs(root)[x]
    assert rec["ince"]["model"] == "ajan2" and sum(bool(m.get("ikinci_arama")) for m in rec["eslesmeler"]) == 1
    # ilk geçiş aynı ölçüt/yuvayı kabul ederse ikinci aramanınki düşer (çift sayım yok)
    d = root / "work" / "fine"
    prepare(root, "fine", backend=b, only=[x])
    ans = fake.answer(R.FINE, DOCS["ekle"])
    ans["eslesmeler"].append({"olcut": "B.1.1", "yuva": "B.1.1/1", "asama": "planla", "od_onerisi": 2,
                              "alinti": Q_EK, "gerekce": "g", "guven": "orta"})
    (d / f"{x}.out.json").write_text(json.dumps(ans, ensure_ascii=False), encoding="utf-8")
    pkg = json.loads((d / f"{x}.json").read_text(encoding="utf-8"))
    pkg["meta"]["adaylar"] = [*pkg["meta"]["adaylar"], "B.1.1"]
    (d / f"{x}.json").write_text(json.dumps(pkg, ensure_ascii=False), encoding="utf-8")
    apply(root, "fine", model="ajan3", backend=b)
    rec = _recs(root)[x]
    assert not any(m.get("ikinci_arama") for m in rec["eslesmeler"])
    assert [m["yuva"] for m in rec["eslesmeler"] if m["olcut"] == "B.1.1"] == ["B.1.1/1"]
    assert rec["ikinci_arama"]["eslesme"] == 0
