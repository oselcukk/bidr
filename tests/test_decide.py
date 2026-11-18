"""decide + compare-labels: sahte model katmanıyla (gerçek model çağrısı yok)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest

from bidr.common import read_jsonl
from bidr.criteria.slots import load_tags
from bidr.decide import compare as C
from bidr.decide import prompt as P
from bidr.decide.run import TASKS_DIR, Backend, check_matches, run

from synth import CS, make_ws

TAGS = load_tags(CS)
SECRET = "GIZLI"  # yol/ad/iz içinde; modele asla gitmemeli

Q_B11 = "Programın amaçları ve öğrenme çıktıları bölüm kurulunda görüşülerek onaylanmıştır."
Q_B23 = "Önceki öğrenmelerin tanınması başvuruları komisyonca incelenmiş ve 4 öğrenciye kredi verilmiştir."
DOCS = {
    "aynı": f"BÖLÜM KURULU KARARI\nGündem 1. {Q_B11}\nKatılımcılar imzaladı. [AYNI]",
    "uydurma": "Program tasarımı toplantısı yapılmıştır. Konu görüşülmüştür. [UYDURMA]",
    "ekle": f"KOMİSYON TUTANAĞI\n{Q_B23}\nSonuç oy birliğiyle kabul edildi. [EKLE]",
    "rapor": "BİRİM İÇ DEĞERLENDİRME RAPORU taslak metni. [RAPOR]",
    "degil": "Kantin menüsü: pazartesi mercimek çorbası. [DEGIL]",
}


def _schema(name):
    return json.loads((TASKS_DIR / name / "output.schema.json").read_text(encoding="utf-8"))


def fine_answer(text: str) -> dict:
    if "[AYNI]" in text:
        return {"karar": "olcut_var", "gerekce": "karar", "eslesmeler": [
            {"olcut": "B.1.1", "yuva": "B.1.1/1", "asama": "planla", "od_onerisi": 2,
             "alinti": Q_B11, "gerekce": "onay kararı", "guven": "yuksek"}]}
    if "[UYDURMA]" in text:
        return {"karar": "olcut_var", "gerekce": "x", "eslesmeler": [
            {"olcut": "B.1.1", "yuva": "B.1.1/6", "asama": "kontrol_et", "od_onerisi": 4,
             "alinti": "Program tasarım süreci yıllık olarak izlenmiş ve iyileştirilmiştir.",
             "gerekce": "izleme", "guven": "yuksek"}]}
    if "[EKLE]" in text:
        return {"karar": "olcut_var", "gerekce": "x", "eslesmeler": [
            # aşama yuva etiketine uymuyor (uygula yuvası, model ozgun/5 diyor) → OD 3'e çekilir
            {"olcut": "B.2.3", "yuva": "B.2.3/2", "asama": "ozgun", "od_onerisi": 5,
             "alinti": Q_B23, "gerekce": "kredi verildi", "guven": "orta"}]}
    return {"karar": "kanit_degil", "gerekce": "ilgisiz", "eslesmeler": []}


class FakeLLM:
    def __init__(self):
        self.calls = []
        self.prompts = {n: (TASKS_DIR / n / "prompt.md").read_text(encoding="utf-8")
                        for n in ("classify_coarse", "classify_fine")}

    def run_task(self, name, inputs, model, cache_dir, check=True):
        if check:
            holes = set(re.findall(r"\{\{(\w+)\}\}", self.prompts[name]))
            assert holes == set(inputs), (holes, set(inputs))
            self.calls.append((name, inputs))
        text = inputs["belge_metni"]
        if name == "classify_coarse":
            out = {"karar": "olcut_var", "gerekce": "g",
                   "olcutler": [{"olcut": "B.1.1", "gerekce": "g"}]}
            if "[AYNI]" in text:   # profil dışı ölçüt (listede yoktu) → atılır
                out["olcutler"].append({"olcut": "A.3.1", "gerekce": "uydurma"})
            if "[EKLE]" in text:
                out["olcutler"] = [{"olcut": "B.2.3", "gerekce": "g"}]
            if "[DEGIL]" in text:
                out = {"karar": "kanit_degil", "olcutler": [], "gerekce": "ilgisiz"}
        else:
            out = fine_answer(text)
        # sahte de sözleşmeye uyar: çıktı görev şemasına karşı doğrulanmış olmalı
        jsonschema.validate(out, _schema(name))
        return SimpleNamespace(output=out, model="fake:test", attempts=1, cached=False, raw=json.dumps(out))

    @staticmethod
    def load_model_config(ws, role="default"):
        return SimpleNamespace(id=f"fake:{role}")

    @staticmethod
    def verify_quote(quote, text):
        norm = lambda s: " ".join(s.split())
        i = norm(text).find(norm(quote))
        return (i >= 0, 1.0 if i >= 0 else 0.0, (i, i + len(quote)) if i >= 0 else None)

    def render_task(self, task, inputs):
        holes = set(re.findall(r"\{\{(\w+)\}\}", self.prompts[task]))
        assert holes == set(inputs), (holes, set(inputs))
        prompt = re.sub(r"\{\{(\w+)\}\}", lambda m: inputs[m.group(1)], self.prompts[task])
        import yaml
        from pathlib import Path
        ver = str(yaml.safe_load((Path(__file__).resolve().parents[1] / "bidr" / "tasks" / task / "task.yaml")
                                 .read_text(encoding="utf-8"))["version"])
        return {"task": task, "version": ver, "prompt": prompt, "schema": _schema(task), "system": ""}

    @staticmethod
    def validate_output(task, raw):
        try:
            v = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError as e:
            return None, [f"JSON değil: {e}"]
        errs = [e.message for e in jsonschema.Draft202012Validator(_schema(task)).iter_errors(v)]
        return (None, errs) if errs else (v, [])

    def answer(self, task, prompt):
        """Ajan taklidi: istemden cevap."""
        return self.run_task(task, {"belge_metni": prompt}, None, None, check=False).output

    def backend(self):
        return Backend(run_task=self.run_task, load_model_config=self.load_model_config,
                       verify_quote=self.verify_quote, render_task=self.render_task,
                       validate_output=self.validate_output)


@pytest.fixture
def ws(tmp_path):
    docs = [
        {"text": DOCS["aynı"], "gold": ["B.1.1"], "path": f"{SECRET}_YOL/B.1.1 Kurul Kararı.pdf"},
        {"text": DOCS["uydurma"], "gold": ["B.1.1"], "path": f"{SECRET}_YOL/B.1.1 Toplantı.pdf"},
        {"text": DOCS["ekle"], "gold": ["A.1.2"], "path": f"{SECRET}_YOL/A.1.2 Tutanak.pdf"},
        {"text": DOCS["rapor"], "gold": ["A.1.1"], "path": f"{SECRET}_YOL/BİDR.docx"},
        {"text": DOCS["degil"], "gold": ["B.2.1"], "path": f"{SECRET}_YOL/B.2.1 Menü.pdf"},
    ]
    root = make_ws(tmp_path / "ws", docs)
    ids = {k: d["id"] for k, d in zip(DOCS, docs)}
    # geçmiş OD (labels.jsonl biçimi: "OD3")
    rows = list(read_jsonl(root / "labels.jsonl"))
    for r in rows:
        for e in r["etiketler"]:
            e["od"] = ["OD3"]
    (root / "labels.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                                       encoding="utf-8")
    with open(root / "documents.jsonl", "w", encoding="utf-8") as f:
        for k, x in ids.items():
            t = "bidr_raporu" if k == "rapor" else "kurul_karari"
            f.write(json.dumps({"doc_id": x, "doc_type": t, "doc_type_etiket": "Kurul Kararı",
                                "tarih": "2025-03-01", "metin": {"sayfa": 1},
                                "calisma_adi": f"{SECRET}_AD", "baslik": f"{SECRET}_BASLIK"},
                               ensure_ascii=False) + "\n")
    with open(root / "candidates.jsonl", "w", encoding="utf-8") as f:
        for x in ids.values():
            f.write(json.dumps({"doc_id": x, "adaylar": [{"olcut": "B.1.1"}, {"olcut": "A.3.1"},
                                                         {"olcut": "B.2.1"}]}) + "\n")
    return root, ids


def _decide(root, fake, **kw):
    out, st = run(root, backend=fake.backend(), log=lambda m: None, **kw)
    return {r["doc_id"]: r for r in read_jsonl(out)}, st


def test_task_contracts_are_valid():
    for name in ("classify_coarse", "classify_fine"):
        d = TASKS_DIR / name
        jsonschema.Draft202012Validator.check_schema(_schema(name))
        assert (d / "prompt.md").read_text(encoding="utf-8").strip()
        assert "version" in (d / "task.yaml").read_text(encoding="utf-8")
    # "kanıt değil" ve "hiçbir ölçüt" geçerli cevaplar
    for k in ("kanit_degil", "olcut_yok"):
        jsonschema.validate({"karar": k, "olcutler": [], "gerekce": ""}, _schema("classify_coarse"))
        jsonschema.validate({"karar": k, "eslesmeler": [], "gerekce": ""}, _schema("classify_fine"))


def test_decide_records_and_skips(ws):
    root, ids = ws
    fake = FakeLLM()
    recs, st = _decide(root, fake)
    assert st["atlandi"] == 1 and st["hata"] == 0
    r = recs[ids["rapor"]]
    assert r["durum"] == "atlandi" and r["neden"] == "oz_referans_turu"
    # öz-referans belge modele hiç gitmedi
    assert not any("[RAPOR]" in i["belge_metni"] for _, i in fake.calls)
    a = recs[ids["aynı"]]
    assert a["karar"] == "olcut_var" and a["olcutler"][0]["olcut"] == "B.1.1"
    assert a["kaba"]["liste_disi"] == ["A.3.1"]
    assert a["kaba"]["model"] == "fake:test" and a["gorev"] == {"classify_coarse": "1", "classify_fine": "2"}
    assert a["asama"] == "ince" and a["ince"]["model"] == "fake:test" and a["kaba"]["kip"] == "saglayici"
    # profil dışı aday (A.3.1) birleşime girmez
    assert "A.3.1" not in a["adaylar"] and a["adaylar"][:2] == ["B.1.1", "B.2.1"]
    assert recs[ids["degil"]]["karar"] == "kanit_degil"


def test_unverified_quote_is_rejected(ws):
    root, ids = ws
    recs, st = _decide(root, FakeLLM())
    u = recs[ids["uydurma"]]
    m = u["eslesmeler"][0]
    assert m["kabul"] is False and "alinti_tutmuyor" in m["denetim"]["red"]
    assert m["od_kabul"] is None
    assert u["olcutler"] == [] and u["karar"] == "olcut_yok"
    assert st["reddedilen_eslesme"] == 1


def test_od_never_inflated(ws):
    root, ids = ws
    recs, _ = _decide(root, FakeLLM())
    m = recs[ids["ekle"]]["eslesmeler"][0]
    assert m["kabul"] is True
    assert "asama_yuva_etiketine_uymuyor" in m["denetim"]["isaret"]
    assert m["od_kabul"] == 3          # uygula yuvası; model 5 dedi
    assert recs[ids["ekle"]]["olcutler"][0]["od"] == 3


def test_check_matches_rules():
    text = "Ölçme sonuçlarına göre ders içerikleri güncellenmiştir ve kurulda onaylanmıştır."
    # veride kanıt yuvası için "belirsiz" (içeriğe bağlı) etiket yok; sentetik etiketle sına
    from dataclasses import replace
    sid, crit = "B.1.1/1", "B.1.1"
    tags = {**TAGS, sid: replace(TAGS[sid], stages=("belirsiz",), od=())}
    v = FakeLLM.verify_quote
    base = {"olcut": crit, "yuva": sid, "asama": "onlem_al", "od_onerisi": 4, "alinti": text,
            "gerekce": "g", "guven": "orta"}
    out = {"eslesmeler": [base,
                          {**base, "yuva": f"{crit}/99"},
                          {**base, "yuva": "B.2.1/1"},
                          {**base, "olcut": "B.2.1", "yuva": "B.2.1/1"},
                          {**base, "alinti": "onaylanmıştır."}]}
    rows = check_matches(out, [crit], CS, tags, text, v)
    assert rows[0]["kabul"] and rows[0]["od_kabul"] == 4      # içeriğe bağlı: aşamadan
    assert "gecersiz_yuva" in rows[1]["denetim"]["red"]
    assert "yuva_olcute_ait_degil" in rows[2]["denetim"]["red"]
    assert "aday_disi_olcut" in rows[3]["denetim"]["red"]
    assert "alinti_cok_kisa" in rows[4]["denetim"]["red"]
    # model OD'si aşamadan düşükse düşük olan alınır
    r = check_matches({"eslesmeler": [{**base, "od_onerisi": 2}]}, [crit], CS, tags, text, v)[0]
    assert r["od_kabul"] == 2 and "od_asamayla_tutarsiz" in r["denetim"]["isaret"]


def test_no_path_name_or_trace_reaches_model(ws):
    root, ids = ws
    fake = FakeLLM()
    _decide(root, fake)
    assert fake.calls
    blob = json.dumps([i for _, i in fake.calls], ensure_ascii=False)
    assert SECRET not in blob
    for word in ("Kurul Kararı.pdf", "Toplantı.pdf", "Tutanak", "Menü", ".pdf", "B.1.1 Kurul"):
        assert word not in blob
    # belge bilgisi yalnız izinli içerik alanlarından
    for _, i in fake.calls:
        assert set(i) <= {"olcutler", "adaylar", "belge_bilgisi", "belge_metni"}
        assert i["belge_bilgisi"] == "tür tahmini: Kurul Kararı; içerik tarihi: 2025-03-01; sayfa: 1"


def test_only_labeled_and_limit(ws):
    root, ids = ws
    lab = root / "labels.jsonl"
    rows = list(read_jsonl(lab))
    rows[0]["etiketli"] = False
    lab.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    recs, _ = _decide(root, FakeLLM(), only_labeled=True)
    assert rows[0]["doc_id"] not in recs and len(recs) == 4
    (root / "decisions.jsonl").unlink()      # decisions.jsonl birikimli bir depodur
    recs, _ = _decide(root, FakeLLM(), limit=2)
    assert len(recs) == 2


def test_model_error_marks_doc(ws):
    root, ids = ws
    fake = FakeLLM()
    orig = fake.run_task

    def boom(name, **kw):
        if "[EKLE]" in kw["inputs"]["belge_metni"]:
            raise RuntimeError("şema geçersiz")
        return orig(name, **kw)
    b = Backend(run_task=boom, load_model_config=fake.load_model_config, verify_quote=fake.verify_quote)
    out, st = run(root, backend=b, log=lambda m: None)
    recs = {r["doc_id"]: r for r in read_jsonl(out)}
    assert recs[ids["ekle"]]["durum"] == "hata" and st["hata"] == 1


def test_compare_review_and_consensus(ws):
    root, ids = ws
    _decide(root, FakeLLM())
    res, st = C.run(root)
    comps = {c["doc_id"]: c for c in res["karsilastirma"]}
    assert comps[ids["aynı"]]["alt"]["ayni"] == ["B.1.1"]
    assert comps[ids["uydurma"]]["alt"]["itiraz"] == ["B.1.1"]
    e = comps[ids["ekle"]]
    assert e["alt"]["ekliyor"] == ["B.2.3"] and e["alt"]["itiraz"] == ["A.1.2"]
    assert e["ana"]["ekliyor"] == ["B.2"] and e["ana"]["itiraz"] == ["A.1"]
    assert ids["rapor"] in {s["doc_id"] for s in res["atlanan"]}
    qs = {q["soru_id"]: q for q in read_jsonl(root / C.FILES["review_jsonl"])}
    od = qs[f"{ids['aynı']}:B.1.1:od_farki"]
    assert od["od_yonu"] == "model_dusuk" and od["model"]["od"] == 2
    it = qs[f"{ids['uydurma']}:B.1.1:itiraz"]
    assert it["model_reddedilen"][0]["red"] == ["alinti_tutmuyor"]
    ek = qs[f"{ids['ekle']}:B.2.3:ekliyor"]
    assert ek["model"]["alinti"] == Q_B23 and ek["model"]["yuva_metni"].startswith("Önceki")
    assert ek["dosya"].startswith(SECRET)        # yol yalnız insan hakeme gösterilir
    assert all(q["grup"] == (q["sira"] - 1) // 5 + 1 for q in qs.values())
    md = (root / C.FILES["review_md"]).read_text(encoding="utf-8")
    assert "## Grup 1" in md and md.count("- Karar: ") == len(qs)
    assert "Alıntı: > " + Q_B23 in md
    cmp_md = (root / C.FILES["compare"]).read_text(encoding="utf-8")
    assert "Alt ölçüt düzeyi" in cmp_md and "Ana ölçüt düzeyi" in cmp_md

    # hakem: md'ye yazar (ekle B.2.3, A.1.2'yi kaldır, OD model), biri jsonl'den
    def answer(md, sid, karar):
        i = md.index(sid)
        j = md.index("- Karar: ", i)
        return md[:j] + f"- Karar: {karar}" + md[j + len("- Karar: "):]
    md = answer(md, f"{ids['ekle']}:B.2.3:ekliyor", "ekle")
    md = answer(md, f"{ids['ekle']}:A.1.2:itiraz", "kaldir")
    md = answer(md, f"{ids['aynı']}:B.1.1:od_farki", "od=2")
    (root / C.FILES["review_md"]).write_text(md, encoding="utf-8")
    with open(root / C.FILES["answers"], "a", encoding="utf-8") as f:
        f.write(json.dumps({"soru_id": f"{ids['uydurma']}:B.1.1:itiraz", "karar": "koru"}) + "\n")

    out, cst = C.consensus(root)
    rows = {r["doc_id"]: r for r in read_jsonl(out)}
    assert cst["eklenen"] == 1 and cst["kaldirilan"] == 1 and cst["od_degisen"] == 1
    ek = rows[ids["ekle"]]
    assert [(e["olcut"], e["od"], e["karar_kaynagi"]) for e in ek["etiketler"]] == [("B.2.3", ["OD3"], "hakem")]
    assert rows[ids["aynı"]]["etiketler"][0]["od"] == ["OD2"]
    assert rows[ids["uydurma"]]["tamam"] is True
    # cevapsız soru açık kalır; geçmiş etiket korunur
    assert rows[ids["degil"]]["tamam"] is False and rows[ids["degil"]]["etiketler"][0]["olcut"] == "B.2.1"
    assert all("iz" not in r for r in rows.values())
    # değerlendirme bunu labels.jsonl yerine okuyabilir
    from bidr.candidates.data import gold_from_label
    assert gold_from_label(ek) == ("B.2.3",)

    # yeniden üretim md'deki cevapları kaybetmez
    C.run(root)
    from bidr.common import Workspace
    ans = C.load_answers(Workspace(root))
    assert ans[f"{ids['ekle']}:B.2.3:ekliyor"]["karar"] == "ekle"


def test_cli_end_to_end(ws, monkeypatch):
    import bidr.llm as llm
    from bidr.cli import main
    root, ids = ws
    fake = FakeLLM()
    for n in ("run_task", "load_model_config", "verify_quote", "render_task", "validate_output"):
        monkeypatch.setattr(llm, n, getattr(fake, n), raising=False)
    assert main(["decide", "run", "-w", str(root), "-q"]) == 0
    assert (root / "decisions.jsonl").exists()
    assert main(["compare-labels", "-w", str(root)]) == 0
    assert (root / "label-review.md").exists() and (root / "label-review.jsonl").exists()
    assert main(["compare-labels", "-w", str(root), "--apply"]) == 0
    assert (root / "consensus-labels.jsonl").exists()


def test_excerpt_budget_and_record():
    long = ("Giriş paragrafı. " * 200) + "\f" + ("Önceki öğrenmelerin tanınması kredilendirme. " * 5) + \
           ("Dolgu metni burada. " * 2000)
    terms = P.criteria_terms(CS, ["B.2.3"])
    s, info = P.excerpt(long, 4000, terms)
    assert info["kisaltildi"] and len(s) <= 4000 + 200
    assert "tanınması" in s and "[...]" in s
    assert info["yontem"] == "bas+olcut_sozcuk_parcalari" and info["orijinal_karakter"] == len(long)
    s2, info2 = P.excerpt("kısa metin\f ikinci   sayfa", 4000)
    assert s2 == "kısa metin\nikinci sayfa" and not info2["kisaltildi"]


def test_prompt_size_budget():
    """Gerçek boyutta (sentetik) istem: küçük yerel modellere sığmalı."""
    from bidr.criteria.profiles import load_profile
    allowed = load_profile("akademik_bolum").allowed(CS)
    body, _ = P.excerpt("Kurul kararı metni. " * 5000, P.COARSE_CHARS)
    coarse = (TASKS_DIR / "classify_coarse/prompt.md").read_text(encoding="utf-8") + \
        P.coarse_list(CS, allowed) + body
    # en uzun 6 aday
    big = sorted(allowed, key=lambda s: -len(P.fine_list(CS, [s], TAGS)))[:6]
    body, _ = P.excerpt("Kurul kararı metni. " * 5000, P.FINE_CHARS)
    fine = (TASKS_DIR / "classify_fine/prompt.md").read_text(encoding="utf-8") + \
        P.fine_list(CS, big, TAGS) + body
    assert P.approx_tokens(coarse) < 7000
    assert P.approx_tokens(fine) < 8000


# -- ajan modu -----------------------------------------------------------------------

def _agent(root, fake, stage, broken=()):
    """Ajan taklidi: her paketi okur, cevabı .out.json'a yazar."""
    from bidr.decide.run import work_dir
    from bidr.common import Workspace
    d = work_dir(Workspace(root), stage)
    n = 0
    for p in sorted(d.glob("*.json")):
        if p.name.endswith(".out.json"):
            continue
        pkg = json.loads(p.read_text(encoding="utf-8"))
        out = d / pkg["cikti_dosyasi"]
        if pkg["doc_id"] in broken:
            out.write_text("Elbette! İşte cevap: {bozuk", encoding="utf-8")
        else:
            out.write_text(json.dumps(fake.answer(pkg["gorev"], pkg["istem"]), ensure_ascii=False),
                           encoding="utf-8")
        n += 1
    return n


def test_agent_mode_packages_and_apply(ws):
    from bidr.decide.run import apply, prepare
    root, ids = ws
    fake = FakeLLM()
    b = fake.backend()
    st = prepare(root, "coarse", backend=b)
    assert st["paket"] == 4 and st["atlandi"] == 1 and st["bekleyen"] == 4
    wd = root / "work" / "coarse"
    assert (wd / "README.md").exists() and "out.json" in (wd / "README.md").read_text(encoding="utf-8")
    pkg = json.loads((wd / f"{ids['aynı']}.json").read_text(encoding="utf-8"))
    assert pkg["gorev"] == "classify_coarse" and pkg["surum"] == "1" and pkg["sema"]["title"] == "classify_coarse"
    assert "[AYNI]" in pkg["istem"] and "{{" not in pkg["istem"]
    # paket dosyalarında yol/ad/iz yok
    for p in wd.iterdir():
        assert SECRET not in p.read_text(encoding="utf-8"), p.name
    # fine hazırlığı kaba sonuç olmadan paket üretmez
    assert prepare(root, "fine", backend=b)["paket"] == 0
    # apply: cevap yoksa bekler
    assert len(apply(root, "coarse", backend=b)["bekleyen"]) == 4

    _agent(root, fake, "coarse", broken={ids["degil"]})
    st = apply(root, "coarse", model="test-ajan", backend=b)
    assert st["islenen"] == 3 and list(st["gecersiz"]) == [ids["degil"]]
    assert ids["degil"] in (wd / "GECERSIZ.md").read_text(encoding="utf-8")
    # yeniden yap: geçerli cevap
    (wd / f"{ids['degil']}.out.json").write_text(
        json.dumps(fake.answer("classify_coarse", pkg["istem"].replace("[AYNI]", "[DEGIL]"))), encoding="utf-8")
    st = apply(root, "coarse", model="test-ajan", backend=b)
    assert st["islenen"] == 4 and not st["gecersiz"] and not (wd / "GECERSIZ.md").exists()

    st = prepare(root, "fine", backend=b)
    assert st["paket"] == 4
    fd = root / "work" / "fine"
    for p in fd.iterdir():
        assert SECRET not in p.read_text(encoding="utf-8"), p.name
    fpkg = json.loads((fd / f"{ids['ekle']}.json").read_text(encoding="utf-8"))
    assert fpkg["meta"]["adaylar"][0] == "B.2.3" and "B.2.3/2" in fpkg["istem"]
    _agent(root, fake, "fine")
    st = apply(root, "fine", model="test-ajan", backend=b)
    assert st["islenen"] == 4 and list(st["alinti_tutmayan"]) == [ids["uydurma"]]
    assert "alinti_tutmuyor" in (fd / "GECERSIZ.md").read_text(encoding="utf-8")
    recs = {r["doc_id"]: r for r in read_jsonl(root / "decisions.jsonl")}
    a = recs[ids["aynı"]]
    assert a["asama"] == "ince" and a["ince"]["model"] == "test-ajan" and a["ince"]["kip"] == "ajan"
    assert recs[ids["uydurma"]]["olcutler"] == []
    assert recs[ids["rapor"]]["durum"] == "atlandi"
    # işlenmiş belgeler yeniden paketlenmez
    assert prepare(root, "fine", backend=b)["zaten_tamam"] == 4
    # aynı akış compare-labels'a girer
    res, _ = C.run(root)
    assert {c["doc_id"] for c in res["karsilastirma"]} == {ids[k] for k in ("aynı", "uydurma", "ekle", "degil")}


def test_prepare_invalidates_stale_answer(ws):
    from bidr.decide.run import prepare
    root, ids = ws
    fake = FakeLLM()
    b = fake.backend()
    prepare(root, "coarse", backend=b)
    _agent(root, fake, "coarse")
    wd = root / "work" / "coarse"
    # belge metni değişti → istem değişir → eski cevap .eski olur
    (root / "text" / f"{ids['ekle']}.txt").write_text(DOCS["ekle"] + " ek satır", encoding="utf-8")
    st = prepare(root, "coarse", backend=b)
    assert st["yeni"] == 1 and st["bekleyen"] == 1
    assert (wd / f"{ids['ekle']}.out.json.eski").exists()


def test_cli_agent_mode(ws, monkeypatch):
    import bidr.llm as llm
    from bidr.cli import main
    root, ids = ws
    fake = FakeLLM()
    for n in ("render_task", "validate_output", "verify_quote"):
        monkeypatch.setattr(llm, n, getattr(fake, n), raising=False)
    monkeypatch.setattr(llm, "run_task", lambda *a, **k: pytest.fail("ajan modunda sağlayıcı çağrıldı"),
                        raising=False)
    assert main(["decide", "prepare", "-w", str(root), "--stage", "coarse"]) == 0
    _agent(root, fake, "coarse")
    assert main(["decide", "apply", "-w", str(root), "--stage", "coarse", "--model", "x"]) == 0
    assert main(["decide", "prepare", "-w", str(root), "--stage", "fine"]) == 0
    _agent(root, fake, "fine")
    assert main(["decide", "apply", "-w", str(root), "--stage", "fine", "--model", "x"]) == 0
    assert main(["compare-labels", "-w", str(root)]) == 0


# -- gerçek bidr.llm işlevleriyle (model yine sahte) ----------------------------------------

def test_agent_mode_with_real_llm_layer(ws):
    """render_task / validate_output / verify_quote gerçek; cevapları ajan taklidi yazar."""
    from bidr.decide.run import apply, prepare
    root, ids = ws
    fake = FakeLLM()
    st = prepare(root, "coarse")                    # Backend() → bidr.llm
    assert st["paket"] == 4
    for p in (root / "work" / "coarse").iterdir():
        assert SECRET not in p.read_text(encoding="utf-8")
    _agent(root, fake, "coarse")
    # ajanın kod çitli cevabı da kabul edilir (validate_output JSON'u ayıklar)
    o = root / "work" / "coarse" / f"{ids['ekle']}.out.json"
    o.write_text("```json\n" + o.read_text(encoding="utf-8") + "\n```", encoding="utf-8")
    assert apply(root, "coarse", model="ajan")["islenen"] == 4
    prepare(root, "fine")
    _agent(root, fake, "fine")
    st = apply(root, "fine", model="ajan")
    assert st["islenen"] == 4 and list(st["alinti_tutmayan"]) == [ids["uydurma"]]
    recs = {r["doc_id"]: r for r in read_jsonl(root / "decisions.jsonl")}
    assert recs[ids["aynı"]]["olcutler"][0]["olcut"] == "B.1.1"
    assert recs[ids["ekle"]]["olcutler"][0]["od"] == 3


def test_provider_mode_with_real_run_task(ws):
    from bidr.llm import config_from_dict
    root, ids = ws
    fake = FakeLLM()
    seen = []

    def respond(system, messages):
        prompt = messages[-1]["content"]
        seen.append(prompt)
        task = "classify_fine" if "ADAY ALT ÖLÇÜTLER" in prompt else "classify_coarse"
        return json.dumps(fake.answer(task, prompt), ensure_ascii=False)

    b = Backend(load_model_config=lambda ws, role="default": config_from_dict(
        {"provider": "fake", "responses": [respond]}, role=role))
    out, st = run(root, backend=b, log=lambda m: None)
    assert st["hata"] == 0 and st["ince"] == 4 and st["reddedilen_eslesme"] == 1
    assert seen and not any(SECRET in p for p in seen)
    recs = {r["doc_id"]: r for r in read_jsonl(out)}
    assert recs[ids["aynı"]]["kaba"]["kip"] == "saglayici"


def test_onayli_icerige_bagli_kural_istemde():
    """Kullanıcının onayladığı içeriğe bağlı OD kuralı ince karar istemine girer."""
    from bidr.criteria.slots import load_tags
    tags = load_tags(CS)
    sid = "C.2.2/4"  # Paydaş geri bildirimleri (onaylı, OD 3/4)
    assert tags[sid].state == "onayli" and len(tags[sid].od) > 1
    metin = P.fine_list(CS, [sid.split("/")[0]], tags)
    assert "OD kuralı:" in metin and tags[sid].reason in metin
