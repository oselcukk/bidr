"""Bölümün belge notları (bidr/notlar.py): görev metnine girer, alıntı nottan yapılamaz, not değişince belge
yeniden değerlendirilir; inceleme satırında izlenir. Sahte model katmanı, sentetik veri."""
from __future__ import annotations

import json

import yaml

from bidr import notlar as N
from bidr.common import Workspace, read_jsonl
from bidr.decide.run import Context, apply, input_fingerprint, plan_members, prepare, work_dir

from test_decide import DOCS, SECRET, FakeLLM, _agent, ws  # noqa: F401  (ws: fikstür)

NOT = "Bu belge 2024 bahar dönemi bölüm kurulu toplantısının karar ekidir."
KIM = "uye@ornek.test"


def _yaz(root, notlar):
    (root / N.NOTLAR).write_text(yaml.safe_dump({"surum": 1, "notlar": notlar}, allow_unicode=True),
                                 encoding="utf-8")


def _inv(root):
    import csv
    with open(root / "inventory.csv", encoding="utf-8") as f:
        return {r["doc_id"]: r for r in csv.DictReader(f)}


def _pkg(root, stage, did):
    return json.loads((work_dir(Workspace(root), stage) / f"{did}.json").read_text(encoding="utf-8"))


def _recs(root):
    return {r["doc_id"]: r for r in read_jsonl(root / "decisions.jsonl")}


def _tam_tur(root, fake):
    b = fake.backend()
    for st in ("coarse", "fine"):
        prepare(root, st, backend=b)
        _agent(root, fake, st)
        apply(root, st, model="test-ajan", backend=b)


# ---------------------------------------------------------------- okuma ve eşleme
def test_not_dosyasi_sha_ya_da_yol_ile_eslenir(ws):
    root, ids = ws
    inv = _inv(root)
    a, e = ids["aynı"], ids["ekle"]
    _yaz(root, [{"dosya": inv[a]["rel_path"], "metin": NOT, "kim": KIM, "tarih": "2026-11-22T10:00:00"},
                {"sha256": inv[e]["sha256"], "metin": "  Komisyon\r\n  tutanağı.  ", "kim": KIM},
                {"sha256": inv[e]["sha256"], "dosya": "baska/kopya.pdf", "metin": "Komisyon\ntutanağı."},  # aynı metin
                {"dosya": "olmayan/dosya.pdf", "metin": "eşlenemez"}, {"dosya": inv[a]["rel_path"], "metin": "  "}])
    notes = N.load(root)
    assert set(notes) == {a, e}
    assert [n["metin"] for n in notes[a]] == [NOT]
    assert [n["metin"] for n in notes[e]] == ["Komisyon\ntutanağı."]
    assert [n["metin"] for n in N.unmatched(root)] == ["eşlenemez"]
    # modele giden blok: başlık, metin, ilke; kim/tarih/yol yok
    b = N.block(notes[a])
    assert b.startswith("Bölümün belge hakkındaki notu (kullanıcı beyanı):\n<<<\n" + NOT + "\n>>>")
    assert "kanıt sayılmaz" in b and "nottan alıntı yapma" in b and N.NOT_ISARETI in b
    assert KIM not in b and "2026" not in b.replace(NOT, "") and inv[a]["rel_path"] not in b
    assert N.with_note("tür tahmini: x", []) == "tür tahmini: x"
    assert N.note_sha([]) == "" and N.note_sha(notes[a]) != N.note_sha(notes[e])
    # kopya satırı (aynı sha, başka yol) da aynı belgeye bağlanır
    import csv
    rows = list(inv.values())
    kopya = dict(rows[0], rel_path="kopyalar/kurul-kopya.pdf", dup_of=rows[0]["rel_path"])
    with open(root / "inventory.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows + [kopya])
    _yaz(root, [{"dosya": "kopyalar/kurul-kopya.pdf", "metin": "Kopyaya yazılan not."}])
    assert list(N.load(root)) == [rows[0]["doc_id"]]


def test_not_isareti_ve_sizinti():
    assert N.conflict("[not uyuşmuyor] Belge 2023 yılına ait.") and N.conflict("Not uyuşmuyor: belge başka")
    assert not N.conflict("Bölüm kurulu kararı; not uyuşmuyor değil") and not N.conflict("")
    notes = [{"metin": NOT}]
    assert N.leaks(notes, "Salonda ~40 dinleyici var.") == []
    assert N.leaks(notes, "2024 bahar dönemi bölüm kurulu toplantısı görülüyor") == ["2024 bahar donemi bolum kurulu"]


# ---------------------------------------------------------------- görev metnine giriş
def test_not_kaba_ve_ince_gorev_metnine_girer(ws):
    root, ids = ws
    a = ids["aynı"]
    _yaz(root, [{"dosya": _inv(root)[a]["rel_path"], "metin": NOT, "kim": KIM, "tarih": "2026-11-22"}])
    fake = FakeLLM()
    b = fake.backend()
    prepare(root, "coarse", backend=b)
    p = _pkg(root, "coarse", a)
    blok = "Bölümün belge hakkındaki notu (kullanıcı beyanı):\n<<<\n" + NOT + "\n>>>"
    assert blok in p["istem"] and p["meta"]["belge_notu"] == N.note_sha([{"metin": NOT}])
    # not belge bilgisinin parçası: belge metni bölümünden önce, belge metninin içinde değil
    assert p["istem"].index(blok) < p["istem"].index("BELGE METNİ\n<<<")
    for k in ("ekle", "uydurma"):                       # notsuz belgenin istemi değişmez
        assert "Bölümün belge hakkındaki notu" not in _pkg(root, "coarse", ids[k])["istem"]
    for x in work_dir(Workspace(root), "coarse").iterdir():   # yol/ad/kim modele gitmez
        assert SECRET not in x.read_text(encoding="utf-8") and KIM not in x.read_text(encoding="utf-8")
    _agent(root, fake, "coarse")
    apply(root, "coarse", model="test-ajan", backend=b)
    assert _recs(root)[a]["kaba"]["belge_notu"] == p["meta"]["belge_notu"]
    prepare(root, "fine", backend=b)
    f = _pkg(root, "fine", a)
    assert blok in f["istem"] and "nottan alıntı yapma" in f["istem"]
    assert "Bölümün belge hakkındaki notu" not in _pkg(root, "fine", ids["ekle"])["istem"]
    _agent(root, fake, "fine")
    apply(root, "fine", model="test-ajan", backend=b)
    r = _recs(root)[a]
    assert r["ince"]["belge_notu"] == p["meta"]["belge_notu"] and r["ince"]["not_uyusmuyor"] is False
    assert "belge_notu" not in _recs(root)[ids["ekle"]]["ince"]


def test_alinti_nottan_yapilamaz_celiski_isaretlenir(ws):
    root, ids = ws
    a = ids["aynı"]
    _yaz(root, [{"dosya": _inv(root)[a]["rel_path"], "metin": NOT}])
    fake = FakeLLM()
    b = fake.backend()
    prepare(root, "coarse", backend=b)
    _agent(root, fake, "coarse")
    apply(root, "coarse", model="test-ajan", backend=b)
    prepare(root, "fine", backend=b)
    _agent(root, fake, "fine")
    # ajan notun cümlesini alıntı diye yazar; gerekçe notla belgenin çeliştiğini söyler
    out = {"karar": "olcut_var", "gerekce": "[not uyuşmuyor] Belge 2025 kurul kararı, not 2024 diyor.",
           "birim_iliskisi": "kendi", "kanit_adi": "Bölüm Kurulu Kararı", "eslesmeler": [
               {"olcut": "B.1.1", "yuva": "B.1.1/1", "asama": "planla", "od_onerisi": 2, "alinti": NOT,
                "gerekce": "nottan", "guven": "yuksek"}]}
    fd = work_dir(Workspace(root), "fine")
    (fd / f"{a}.out.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    st = apply(root, "fine", model="test-ajan", backend=b)
    assert a in st["alinti_tutmayan"]
    r = _recs(root)[a]
    assert [m["kabul"] for m in r["eslesmeler"]] == [False] and r["olcutler"] == []
    assert "alinti_tutmuyor" in r["eslesmeler"][0]["denetim"]["red"]
    assert r["ince"]["not_uyusmuyor"] is True


# ---------------------------------------------------------------- not değişince yeniden değerlendirme
def test_not_degisince_belge_yeniden_degerlendirilir(ws):
    root, ids = ws
    a = ids["aynı"]
    rel = _inv(root)[a]["rel_path"]
    fake = FakeLLM()
    b = fake.backend()
    _tam_tur(root, fake)
    parmak = input_fingerprint(Workspace(root), "coarse")
    assert prepare(root, "coarse", backend=b)["zaten_tamam"] == 4
    # not eklendi: yalnız o belge onaysız yeniden paketlenir (girdi_degisti), eski cevap .eski olur
    _yaz(root, [{"dosya": rel, "metin": NOT}])
    assert input_fingerprint(Workspace(root), "coarse") != parmak   # bidr status prepare'i yeniden ister
    st = prepare(root, "coarse", backend=b)
    assert st["girdi_degisti"] == 1 and st["zaten_tamam"] == 3 and not st["onay_gerekli"]
    assert st["bekleyen"] == 1 and (work_dir(Workspace(root), "coarse") / f"{a}.out.json.eski").exists()
    assert _recs(root)[a]["yeniden"]["neden"] == "girdi_degisti"
    assert NOT in _pkg(root, "coarse", a)["istem"]
    _agent(root, fake, "coarse")
    apply(root, "coarse", model="test-ajan", backend=b)
    st = prepare(root, "fine", backend=b)                  # kaba yeniden verildi → ince yeniden paketlenir
    assert st["paket"] == 1 and NOT in _pkg(root, "fine", a)["istem"]
    _agent(root, fake, "fine")
    apply(root, "fine", model="test-ajan", backend=b)
    assert _recs(root)[a]["ince"]["belge_notu"] == N.note_sha([{"metin": NOT}])
    assert prepare(root, "coarse", backend=b)["zaten_tamam"] == 4
    # not değişti ve sonra kaldırıldı: her seferinde yeniden değerlendirme listesine girer
    _yaz(root, [{"dosya": rel, "metin": "Bu belge 2025 güz dönemine aittir."}])
    assert list(prepare(root, "coarse", backend=b)["eski"]) == [] and _recs(root)[a]["yeniden"]["asama"] == "coarse"
    _tam_tur(root, fake)
    _yaz(root, [])
    st = prepare(root, "coarse", backend=b)
    assert st["girdi_degisti"] == 1 and "Bölümün belge hakkındaki notu" not in _pkg(root, "coarse", a)["istem"]
    # kayıtta not yokken notsuz istem eskimez (notsuz belgeler etkilenmez)
    _tam_tur(root, fake)
    assert prepare(root, "coarse", backend=b)["zaten_tamam"] == 4 and "belge_notu" not in _recs(root)[a]["kaba"]


def test_notlu_belge_mukerrer_gruplanmaz(tmp_path):
    from synth import make_ws
    metin = "BÖLÜM KURULU KARARI\n" + " ".join(f"madde{i} görüşüldü ve kabul edildi" for i in range(40))
    root = make_ws(tmp_path / "ws", [{"text": metin}, {"text": metin + " ek"}])
    ctx = Context.load(root, profile=None)
    ids = sorted(ctx.docs) or sorted(p.stem for p in (root / "text").glob("*.txt"))
    assert plan_members(ctx, ids, {}, "coarse")            # notsuz: yakın metin gruplanır
    _yaz(root, [{"dosya": _inv(root)[ids[0]]["rel_path"], "metin": NOT}])
    ctx = Context.load(root, profile=None)
    assert plan_members(ctx, ids, {}, "coarse") == {}


# ---------------------------------------------------------------- inceleme tablosu
def test_inceleme_satirinda_not_izlenir():
    from bidr.audit import sade
    from bidr.audit.run import seen_state
    r = {"flags": ["belge_notu", "not_uyusmuyor"], "sayilir": True, "od": 2}
    uy, bak = sade.dikkat(r, 2025)
    assert bak and any("yükleyenin notu ile belge içeriği uyuşmuyor" in x for x in uy)
    uy, bak = sade.dikkat({"flags": ["belge_notu"], "sayilir": True, "od": 2}, 2025)
    assert not uy and not bak                             # yalnız bilgi: bakılacaklara düşürmez
    # not eklenmesi verilmiş kararı "yeniden bak"a düşürmez; çelişki düşürür
    assert seen_state({"flags": ["belge_notu"]})["isaretler"] == []
    assert seen_state({"flags": ["belge_notu", "not_uyusmuyor"]})["isaretler"] == ["not_uyusmuyor"]


def test_audit_satiri_notu_gosterir(ws):
    from bidr.audit.run import audit
    from bidr.audit.sade import inceleme_satirlari
    from bidr.criteria.loader import load_criteria
    root, ids = ws
    a = ids["aynı"]
    _yaz(root, [{"dosya": _inv(root)[a]["rel_path"], "metin": NOT}])
    _tam_tur(root, FakeLLM())
    au, _ = audit(root)
    rows = [r for r in au.rows if r["doc_id"] == a]
    assert rows and all("belge_notu" in r["flags"] and "yükleyenin notu dikkate alındı" in r["vurgu"] for r in rows)
    assert all("belge_notu" not in r["flags"] for r in au.rows if r["doc_id"] != a)
    sade = [s for s in inceleme_satirlari(au, load_criteria()) if s["satir"].startswith(a)]
    assert sade and all(s["neden"].endswith("Yükleyenin notu dikkate alındı.") for s in sade)


# ---------------------------------------------------------------- betimleme ve kanıt adı
def test_betimleme_notu_ve_yeniden_betimleme():
    from bidr.describe.run import note_leaks, note_stale, settled
    notes = {"d1": [{"metin": NOT}]}
    out = {"gorseller": [{"sahne": "toplantı odası", "etkinlik": "toplantı", "nesneler": [{"ad": "masa"}],
                          "betimleme": "2024 bahar dönemi bölüm kurulu toplantısı yapılıyor.",
                          "gorunen_yazilar": []}]}
    assert note_leaks(out, notes["d1"]) and "yükleyenin notundan" in note_leaks(out, notes["d1"])[0]
    out["gorseller"][0]["gorunen_yazilar"] = [{"metin": "2024 Bahar Dönemi Bölüm Kurulu Toplantısı"}]
    assert note_leaks(out, notes["d1"]) == []             # görüntüde yazıyor: aktarım değil
    assert note_leaks(out, None) == []
    log = {"d1": {"durum": "metin_belgesi"}, "d2": {"durum": "metin_belgesi", "belge_notu": N.note_sha(notes["d1"])}}
    assert note_stale("d1", log, notes) and not note_stale("d2", log, {"d2": notes["d1"]})
    assert not settled(None, "d1", log, notes)   # not değişti: ws'ye bakmadan yeniden betimlenecek


def test_kanit_adi_notu_gorur_ve_not_degisince_yeniden_sorulur(ws):
    from bidr.name.run import inputs_of, note_stale
    root, ids = ws
    a = ids["aynı"]
    notes = {a: [{"metin": NOT}]}
    rec = {"eslesmeler": [{"olcut": "B.1.1", "yuva": "B.1.1/1", "asama": "planla", "kabul": True, "alinti": "x"}]}
    inp = inputs_of(Workspace(root), a, rec, None, notes=notes[a])
    assert NOT in inp["belge_bilgisi"] and "belgede olmayan tür, yıl" in inp["belge_bilgisi"]
    assert "Bölümün belge" not in inputs_of(Workspace(root), a, rec, None)["belge_bilgisi"]
    assert note_stale(a, {"model": {"ad": "X"}}, notes)
    assert not note_stale(a, {"model": {"ad": "X", "belge_notu": N.note_sha(notes[a])}}, notes)
    assert not note_stale(a, {"model": {"ad": "X"}}, {}) and not note_stale(a, {"insan": {"ad": "Y"}}, notes)


def test_en_uzun_not_istem_butcesini_asmaz():
    """Not bloğu metin payından düşer: 1000 karakterlik notla da istem bütçesi (test_prompt_size_budget) aynı."""
    from bidr.criteria.profiles import load_profile
    from bidr.decide import prompt as P
    from bidr.decide.run import TASKS_DIR
    from test_decide import CS, TAGS
    notes = [{"metin": "x" * N.EN_COK}]
    blok = N.block(notes)
    allowed = load_profile("akademik_bolum").allowed(CS)
    big = sorted(allowed, key=lambda s: -len(P.fine_list(CS, [s], TAGS)))[:6]
    body, _ = P.excerpt("Kurul kararı metni. " * 5000, P.FINE_CHARS - len(blok))
    fine = (TASKS_DIR / "classify_fine/prompt.md").read_text(encoding="utf-8") + P.fine_list(CS, big, TAGS) + body + blok
    assert P.approx_tokens(fine) < 8000
    body, _ = P.excerpt("Kurul kararı metni. " * 5000, P.COARSE_CHARS - len(blok))
    coarse = (TASKS_DIR / "classify_coarse/prompt.md").read_text(encoding="utf-8") + P.coarse_list(CS, allowed) + body + blok
    assert P.approx_tokens(coarse) < 7000
