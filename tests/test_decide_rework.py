"""decide: seçmeli yeniden işleme, sürüm/istem eskimesi, kurum geneli OD tavanı, mükerrer
metin, apply sayaçları. Sahte model katmanı; gerçek veri ve model çağrısı yok."""
from __future__ import annotations

import json

import pytest

from bidr.common import Workspace, read_jsonl
from bidr.decide import dedup as D
from bidr.decide import run as R
from bidr.decide.run import Backend, apply, check_matches, prepare
from bidr.pipeline.checks import Ctx, karar_tamam

from synth import CS, make_ws
from test_decide import DOCS, Q_B23, TAGS, FakeLLM, _agent, ws  # noqa: F401  (ws: fixture)


def _recs(root):
    return {r["doc_id"]: r for r in read_jsonl(root / "decisions.jsonl")}


def _check(root, stage):
    return karar_tamam(Ctx(Workspace(root), {}, lambda x: x,
                           {"sart": {"asama": stage}, "komut": ["PREP", "(ajan)", "APPLY"]}))


def _full(root, fake, b):
    for stage in ("coarse", "fine"):
        prepare(root, stage, backend=b)
        _agent(root, fake, stage)
        apply(root, stage, model="ajan", backend=b)


# -- 1. seçmeli yeniden işleme ---------------------------------------------------------------

def test_only_reprocesses_selected_docs(ws):
    root, ids = ws
    fake = FakeLLM()
    b = fake.backend()
    _full(root, fake, b)
    before = _recs(root)
    cd, fd = root / "work" / "coarse", root / "work" / "fine"
    outs = {p: p.read_text(encoding="utf-8") for p in [*cd.glob("*.out.json"), *fd.glob("*.out.json")]}
    x = ids["ekle"]

    st = prepare(root, "coarse", backend=b, only=[x])
    assert st["paket"] == 1 and st["yeni"] == 1 and st["secmeli"] == 1 and st["zaten_tamam"] == 0
    assert (cd / f"{x}.out.json.eski").exists() and not (cd / f"{x}.out.json").exists()
    recs = _recs(root)
    assert recs[x]["yeniden"]["neden"] == "secmeli" and recs[x]["asama"] == "ince"   # eski karar duruyor
    for k, r in before.items():
        if k != x:
            assert recs[k] == r                                                     # ötekiler aynen
    for p, txt in outs.items():
        if not p.name.startswith(x):
            assert p.read_text(encoding="utf-8") == txt                              # cevaplar aynen
    ck = _check(root, "coarse")
    assert not ck.bitti and ck.kim == "ajan" and ck.ilerleme["cevapsiz"] == 1

    assert _agent(root, fake, "coarse") == 4
    st = apply(root, "coarse", model="ajan2", backend=b)
    assert st["islenen"] == 1 and st["degismedi"] == 3
    recs = _recs(root)
    assert recs[x]["asama"] == "kaba" and "yeniden" not in recs[x] and recs[x]["kaba"]["model"] == "ajan2"
    assert all(recs[k] == before[k] for k in before if k != x)                     # ince kayıtlar korundu
    assert (fd / f"{x}.out.json.eski").exists()                                     # ince de yeniden
    st = prepare(root, "fine", backend=b)
    assert st["paket"] == 1 and st["zaten_tamam"] == 3 and st["bekleyen"] == 1
    _agent(root, fake, "fine")
    apply(root, "fine", model="ajan2", backend=b)
    assert _recs(root)[x]["ince"]["model"] == "ajan2" and _check(root, "fine").bitti


def test_only_cli_ids_prefix_and_file(ws, monkeypatch, tmp_path, capsys):
    import bidr.llm as llm
    from bidr.cli import main
    root, ids = ws
    fake = FakeLLM()
    for n in ("render_task", "validate_output", "verify_quote"):
        monkeypatch.setattr(llm, n, getattr(fake, n), raising=False)
    _full(root, fake, fake.backend())
    base = ["decide", "prepare", "-w", str(root), "--stage", "coarse"]
    assert main(base + ["--only", "zzzzzz"]) == 2
    assert main(base + ["--only", "ab"]) == 2                     # çok kısa önek
    capsys.readouterr()
    assert main(base + ["--only", ids["ekle"][:8]]) == 0
    assert "seçmeli=1" in capsys.readouterr().out
    lst = tmp_path / "liste.txt"
    lst.write_text(f"# yeniden\n{ids['aynı']}  # yorum\n{ids['degil']},\n", encoding="utf-8")
    assert main(base + ["--from-file", str(lst)]) == 0
    recs = _recs(root)
    assert {k for k, r in recs.items() if r.get("yeniden")} == {ids["ekle"], ids["aynı"], ids["degil"]}
    assert "yeniden" not in recs[ids["uydurma"]]


# -- 2. sürüm / istem değişimi ------------------------------------------------------------

def test_version_change_needs_summary_and_yes(ws, monkeypatch):
    root, ids = ws
    fake = FakeLLM()
    _full(root, fake, fake.backend())
    real = R.task_version
    monkeypatch.setattr(R, "task_version", lambda n: "99" if n == R.FINE else real(n))
    b = Backend(render_task=lambda t, i: {**fake.render_task(t, i), "version": R.task_version(t)},
                validate_output=fake.validate_output, verify_quote=fake.verify_quote)
    before = _recs(root)
    done = {k for k, r in before.items() if (r.get("gorev") or {}).get(R.FINE)}
    assert len(done) == 4

    st = prepare(root, "fine", backend=b)                       # onaysız: yalnız özet
    assert st["onay_gerekli"] and set(st["eski"]) == done and set(st["eski"].values()) == {"eski_surum"}
    assert st["paket"] == 0 and st["eski_cagri"] == 4 and st["eski_token"] > 0
    assert _recs(root) == before                                # kayıtlara dokunulmadı
    assert (root / "work" / "fine" / R.RESTALE).exists()
    ck = _check(root, "fine")                                  # bidr status: bitti + uyarı
    assert ck.bitti and ck.ilerleme["yeniden_islenecek"] == 4
    assert any("yeniden işlenecek 4 belge" in u for u in ck.uyarilar) and "yeniden işlenecek 4" in ck.neden

    st = prepare(root, "fine", backend=b, yes=True)            # onaylı
    assert st["paket"] == 4 and st["yeni"] == 4 and not st["onay_gerekli"]
    assert not (root / "work" / "fine" / R.RESTALE).exists()
    recs = _recs(root)
    assert all(recs[k]["yeniden"] == {"asama": "fine", "neden": "eski_surum", "onceki_surum": "10"} for k in done)
    ck = _check(root, "fine")
    assert not ck.bitti and ck.kim == "ajan" and ck.ilerleme["cevapsiz"] == 4
    _agent(root, fake, "fine")
    apply(root, "fine", model="ajan", backend=b)
    recs = _recs(root)
    assert all(recs[k]["gorev"][R.FINE] == "99" and "yeniden" not in recs[k] for k in done)
    assert _check(root, "fine").bitti and not _check(root, "fine").uyarilar[1:]


def test_prompt_change_detected_without_redo(ws):
    root, ids = ws
    fake = FakeLLM()
    b = fake.backend()
    _full(root, fake, b)
    x = ids["ekle"]
    (root / "text" / f"{x}.txt").write_text(DOCS["ekle"] + " Ek satır.", encoding="utf-8")
    before = _recs(root)
    st = prepare(root, "coarse", backend=b)
    assert st["eski"] == {x: "istem_degisti"} and st["paket"] == 0 and st["zaten_tamam"] == 3
    assert _recs(root) == before
    ck = _check(root, "coarse")
    assert ck.bitti and ck.ilerleme["yeniden_islenecek"] == 1
    st = prepare(root, "coarse", backend=b, yes=True)
    assert st["paket"] == 1 and _recs(root)[x]["yeniden"]["neden"] == "istem_degisti"
    assert not _check(root, "coarse").bitti


def test_version_only_bump_rewrites_pending_package(ws, monkeypatch):
    """İstem aynı, yalnız sürüm arttı: bekleyen paket yenilenir (apply eski paketi reddeder)."""
    root, ids = ws
    fake = FakeLLM()
    prepare(root, "coarse", backend=fake.backend())
    real = R.task_version
    monkeypatch.setattr(R, "task_version", lambda n: "77" if n == R.COARSE else real(n))
    b = Backend(render_task=lambda t, i: {**fake.render_task(t, i), "version": R.task_version(t)},
                validate_output=fake.validate_output, verify_quote=fake.verify_quote)
    st = prepare(root, "coarse", backend=b)
    assert st["yeni"] == 4
    _agent(root, fake, "coarse")
    assert apply(root, "coarse", backend=b)["islenen"] == 4


# -- 3. kurum geneli OD tavanı -------------------------------------------------------------

def test_check_matches_kurum_cap():
    text = "KOMİSYON TUTANAĞI\n" + Q_B23
    m = {"olcut": "B.2.3", "yuva": "B.2.3/2", "asama": "uygula", "od_onerisi": 3, "alinti": Q_B23,
         "gerekce": "g", "guven": "orta"}
    assert TAGS["B.2.3/2"].stages == ("uygula",)                # tek aşamalı yuva
    plain = check_matches({"eslesmeler": [m]}, ["B.2.3"], CS, TAGS, text, FakeLLM.verify_quote)[0]
    assert plain["od_kabul"] == 3 and "uygulama_kaniti_eksik" not in plain["denetim"]["isaret"]
    cap = check_matches({"eslesmeler": [m]}, ["B.2.3"], CS, TAGS, text, FakeLLM.verify_quote, kurum=True)[0]
    assert cap["kabul"] and cap["od_kabul"] == 2 and "uygulama_kaniti_eksik" in cap["denetim"]["isaret"]
    # OD zaten 2 ise işaret yok
    low = check_matches({"eslesmeler": [{**m, "od_onerisi": 2}]}, ["B.2.3"], CS, TAGS, text,
                        FakeLLM.verify_quote, kurum=True)[0]
    assert low["od_kabul"] == 2 and "uygulama_kaniti_eksik" not in low["denetim"]["isaret"]


def _set_type(root, did, t):
    rows = list(read_jsonl(root / "documents.jsonl"))
    for r in rows:
        if r["doc_id"] == did:
            r["doc_type"] = t
    (root / "documents.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                                          encoding="utf-8")


@pytest.mark.parametrize("how", ["tur", "model", "yok"])
def test_kurum_geneli_cap_end_to_end(ws, how):
    root, ids = ws
    x = ids["ekle"]
    assert R.kurum_geneli_types() >= {"yonetmelik", "yonerge"}
    if how == "tur":
        _set_type(root, x, "yonerge")

    class F(FakeLLM):
        def run_task(self, name, inputs, model, cache_dir, check=True):
            r = super().run_task(name, inputs, model, cache_dir, check)
            if how == "model" and name == R.FINE and "[EKLE]" in inputs["belge_metni"]:
                r.output["birim_iliskisi"] = "kurum_geneli"
            return r
    _, st = R.run(root, backend=F().backend(), log=lambda m: None)
    rec = _recs(root)[x]
    m = rec["eslesmeler"][0]
    if how == "yok":
        assert m["od_kabul"] == 3 and rec["ince"]["kurum_geneli"]["karar"] is False and st["od_tavan"] == 0
        return
    assert m["kabul"] and m["od_kabul"] == 2 and "uygulama_kaniti_eksik" in m["denetim"]["isaret"]
    assert rec["olcutler"][0]["od"] == 2 and st["od_tavan"] == 1
    assert rec["ince"]["kurum_geneli"] == {"model": how == "model", "tur": how == "tur", "karar": True}


def test_kurum_geneli_in_prompt_and_schema():
    from bidr.decide import prompt as P
    assert "kurum_geneli" in P.evidence_principles()
    fine = (R.TASKS_DIR / R.FINE / "prompt.md").read_text(encoding="utf-8")
    assert '"kurum_geneli"' in fine and '"birim_iliskisi"' in fine and "{{birim}}" in fine
    sch = json.loads((R.TASKS_DIR / R.FINE / "output.schema.json").read_text(encoding="utf-8"))
    assert "birim_iliskisi" in sch["required"] and "kurum_geneli" not in sch["properties"]
    assert set(sch["properties"]["birim_iliskisi"]["enum"]) == set(R.BIRIM_ILISKILERI)
    assert R.task_version(R.FINE) == "10"


# -- 4. mükerrer metin ------------------------------------------------------------------

FILL = " ".join(f"Madde {w} bölüm kurulunda görüşülmüş ve kayda geçirilmiştir." for w in
                ("bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz", "on", "on bir",
                 "on iki", "on üç", "on dört", "on beş", "on altı", "on yedi", "on sekiz"))
EPOSTA = (f"Konu: komisyon toplantısı\n{Q_B23}\n{FILL}\nYazdırma: 02.02.2026 12:24 [EKLE]")


def _dup_ws(tmp_path):
    texts = {
        "aynı": DOCS["aynı"],
        "aynı_kopya": "  " + DOCS["aynı"].replace("\n", " \n\n ") + "  ",        # aynı iskelet
        "eposta": EPOSTA,
        "eposta_cikti2": EPOSTA.replace("02.02.2026 12:24", "29.01.2026 11:43"),   # yalnız saat farklı
        "eposta_baska_sayi": EPOSTA.replace("4 öğrenciye", "5 öğrenciye"),         # alıntıdaki sayı farklı
        "sablon_baska": EPOSTA.replace(FILL, FILL.replace("görüşülmüş", "ertelenmiş")),  # 10 sözcük farklı
        "degil": DOCS["degil"],
    }
    # kimlikler sıralı: eşit uzunlukta temsilci en küçük doc_id (aynı, eposta)
    docs = [{"text": t, "gold": [], "id": f"{'aabbbbc'[i]}{i:015d}"} for i, t in enumerate(texts.values())]
    root = make_ws(tmp_path / "ws", docs)
    ids = {k: d["id"] for k, d in zip(texts, docs)}
    with open(root / "documents.jsonl", "w", encoding="utf-8") as f:
        for x in ids.values():
            f.write(json.dumps({"doc_id": x, "doc_type": "e_posta"}) + "\n")
    with open(root / "candidates.jsonl", "w", encoding="utf-8") as f:
        for x in ids.values():
            f.write(json.dumps({"doc_id": x, "adaylar": [{"olcut": "B.1.1"}, {"olcut": "B.2.3"}]}) + "\n")
    return root, ids


def test_find_groups_strict():
    a = "Bölüm kurulu " * 30
    g = D.find_groups({"x": a, "y": a.upper(), "z": a + " ek", "w": "Kantin menüsü"},
                      {"x": "t", "y": "t", "z": "t", "w": "t"})
    assert [sorted(x["uyeler"]) for x in g] == [["x", "y", "z"]]
    assert D.relation(g[0], "x", "y") == ("ayni_metin", 0) and D.relation(g[0], "x", "z") == ("yakin_metin", 1)
    # tür farklıysa yakın metin bağlanmaz (ör. müfredat ↔ onu içeren senato kararı)
    assert D.find_groups({"x": a, "z": a + " ek"}, {"x": "mufredat", "z": "senato_karari"}) == []


def test_duplicate_text_agent_mode(tmp_path):
    root, ids = _dup_ws(tmp_path)
    fake = FakeLLM()
    b = fake.backend()
    st = prepare(root, "coarse", backend=b)
    # aynı_kopya ve eposta_cikti2 + eposta_baska_sayi (1 sözcük farklı) temsilciyi bekler
    assert st["mukerrer"] == 3 and st["paket"] == 4 and st["devralindi"] == 0
    recs = _recs(root)
    for k, rep in (("aynı_kopya", "aynı"), ("eposta_cikti2", "eposta"), ("eposta_baska_sayi", "eposta")):
        mk = recs[ids[k]]["mukerrer"]
        assert mk["temsilci"] == ids[rep] and mk["durum"] == "bekliyor"
        assert not (root / "work" / "coarse" / f"{ids[k]}.json").exists()
    assert recs[ids["aynı_kopya"]]["mukerrer"]["yontem"] == "ayni_metin"
    assert recs[ids["eposta_cikti2"]]["mukerrer"]["yontem"] == "yakin_metin"
    assert "mukerrer" not in recs.get(ids["sablon_baska"], {})            # farklı belge: kendisi işlenir
    ck = _check(root, "coarse")
    assert ck.kim == "ajan" and ck.ilerleme["mukerrer_bekleyen"] == 3 and ck.ilerleme["cevapsiz"] == 4

    assert _agent(root, fake, "coarse") == 4
    st = apply(root, "coarse", model="ajan", backend=b)
    assert st["islenen"] == 4 and st["devralindi"] == 3
    recs = _recs(root)
    c = recs[ids["aynı_kopya"]]
    assert c["kaba"]["devralindi"] == ids["aynı"] and c["kaba"]["secilen"] == recs[ids["aynı"]]["kaba"]["secilen"]
    assert c["mukerrer"]["durum"] == "devralindi" and _check(root, "coarse").bitti

    st = prepare(root, "fine", backend=b)
    assert st["paket"] == 4 and st["mukerrer"] == 3
    _agent(root, fake, "fine")
    st = apply(root, "fine", model="ajan", backend=b)
    # alıntıdaki sayı farklı olan kopya devralamaz: ayrılır, kendisi paketlenir
    assert st["devralindi"] == 2 and st["ayrildi"] == [ids["eposta_baska_sayi"]]
    recs = _recs(root)
    e2 = recs[ids["eposta_cikti2"]]
    assert e2["ince"]["devralindi"] == ids["eposta"] and e2["olcutler"][0]["olcut"] == "B.2.3"
    assert e2["eslesmeler"][0]["denetim"]["alinti_tutuyor"]               # kendi metnine karşı denetlendi
    assert recs[ids["eposta"]]["kopyalar"] == [ids["eposta_cikti2"]]
    assert recs[ids["aynı_kopya"]]["olcutler"] == recs[ids["aynı"]]["olcutler"]
    ay = recs[ids["eposta_baska_sayi"]]
    assert ay["mukerrer"]["durum"] == "ayrildi" and ay["asama"] == "kaba"
    st = prepare(root, "fine", backend=b)
    assert st["paket"] == 1 and st["bekleyen"] == 1 and st["mukerrer"] == 0
    _agent(root, fake, "fine")
    apply(root, "fine", model="ajan", backend=b)
    recs = _recs(root)
    assert recs[ids["eposta_baska_sayi"]]["ince"].get("devralindi") is None
    assert _check(root, "fine").bitti and _check(root, "coarse").bitti


def test_duplicate_text_provider_mode_saves_calls(tmp_path):
    root, ids = _dup_ws(tmp_path)
    fake = FakeLLM()
    _, st = R.run(root, backend=fake.backend(), log=lambda m: None)
    texts = [i["belge_metni"] for _, i in fake.calls]
    # 7 belge: aynı_kopya ve eposta_cikti2 modele gitmedi; ayrılan kopya kendisi işlendi
    assert len(texts) == 2 * 5 and st["devralan"] == 2 and st["hata"] == 0
    recs = _recs(root)
    assert recs[ids["eposta_cikti2"]]["mukerrer"]["durum"] == "devralindi"
    assert recs[ids["eposta_baska_sayi"]]["ince"]["model"] == "fake:test"


# -- 5. apply sayaçları --------------------------------------------------------------------

def test_apply_counts_after_coarse(ws, monkeypatch, capsys):
    import bidr.llm as llm
    from bidr.cli import main
    root, ids = ws
    fake = FakeLLM()
    for n in ("render_task", "validate_output", "verify_quote"):
        monkeypatch.setattr(llm, n, getattr(fake, n), raising=False)
    prepare(root, "coarse", backend=fake.backend())
    _agent(root, fake, "coarse")
    capsys.readouterr()
    assert main(["decide", "apply", "-w", str(root), "--stage", "coarse", "--model", "x"]) == 0
    out = capsys.readouterr().out
    assert "kaba karar: olcut_var=3 olcut_yok=0 kanit_degil=1" in out
    assert "olcut_var=0 olcut_yok=0 kanit_degil=0" not in out and "ince karar" not in out
    st = R.stats_of(_recs(root))
    assert st["kaba"] == 4 and st["kaba_karar"] == {"olcut_var": 3, "olcut_yok": 0, "kanit_degil": 1}
    prepare(root, "fine", backend=fake.backend())
    _agent(root, fake, "fine")
    capsys.readouterr()
    assert main(["decide", "apply", "-w", str(root), "--stage", "fine", "--model", "x"]) == 0
    out = capsys.readouterr().out
    assert "ince karar (ince aşamadaki 4 belge): olcut_var=2 olcut_yok=1 kanit_degil=1" in out
