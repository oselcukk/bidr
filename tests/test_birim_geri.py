"""Başka birime ait sayılan belgenin inceleme tablosundan geri alınması: review.xlsx
"Başka birime ait sayılanlar" sayfası, `audit apply` (insan > model), eşleşmelerin geri
yüklenmesi ve OD2 tavanı, eşleşmesiz belgede yeniden karar (pakette sabit ilişki), status
denetimi, eski tablo uyumluluğu. Yalnız sentetik veri."""
from __future__ import annotations

import json

from openpyxl import load_workbook

from bidr.audit.run import FILES, apply as audit_apply, audit, build, review_state
from bidr.audit.sheet import SHEET_ROWS, SHEET_UNIT, UNIT_COLS, read_unit_sheet
from bidr.common import Workspace, read_jsonl
from bidr.decide import run as R
from bidr.decide.run import apply, prepare
from bidr.pipeline.checks import Ctx, karar_tamam

from test_birim import Rel, _recs
from test_decide import _agent, ws  # noqa: F401  (ws: fixture)


def _other_unit(root, *, drop_matches=False):
    """[EKLE] belgesini model başka birime ait sayar (eşleşme verir; kod reddeder)."""
    R.run(root, backend=Rel("baska_birim").backend(), log=lambda m: None)
    if drop_matches:                # model kurala uyup eşleşme vermediyse: kayıtta eşleşme yok
        recs = _recs(root)
        for r in recs.values():
            if (r.get("ince") or {}).get("birim_iliskisi") == "baska_birim":
                r["eslesmeler"], r["reddedilen_eslesme"] = [], 0
        (root / "decisions.jsonl").write_text("".join(json.dumps(recs[k], ensure_ascii=False) + "\n"
                                                      for k in sorted(recs)), encoding="utf-8")


def _unit_rows(path):
    wb = load_workbook(path)
    sh = wb[SHEET_UNIT]
    head = [c.value for c in sh[2]]
    return wb, sh, head


def _set_unit(path, did, value, note=""):
    wb, sh, head = _unit_rows(path)
    ci = head.index("belge kimliği")
    vi, ni = head.index("insan_birim_iliskisi"), head.index("not")
    hit = False
    for row in sh.iter_rows(min_row=3):
        if row[ci].value == did:
            row[vi].value = value or None
            row[ni].value = note or None
            hit = True
    assert hit, did
    wb.save(path)


def _karar_ctx(root):
    st = {"sart": {"asama": "fine"},
          "komut": ["bidr decide prepare --stage fine", "(ajan)", "bidr decide apply --stage fine"]}
    return Ctx(Workspace(root), {}, lambda t: t, st)


# -- tablo sayfası ---------------------------------------------------------------------------

def test_sheet_lists_other_unit_docs_with_rejected_matches(ws):
    root, ids = ws
    x = ids["ekle"]
    _other_unit(root)
    a, paths = audit(root)
    assert not any(r["doc_id"] == x for r in a.rows)
    wb, sh, head = _unit_rows(paths["xlsx"])
    assert head == [h for _, h, _, _ in UNIT_COLS]
    assert "insan_birim_iliskisi" in str(sh.cell(row=1, column=1).value)      # Türkçe açıklama satırı
    row = next(r for r in sh.iter_rows(min_row=3, values_only=True) if r[0] == x)
    rec = dict(zip([k for k, _, _, _ in UNIT_COLS], row))
    assert "B.2.3 B.2.3/2 · ozgun · OD5" in rec["eslesmeler"] and "Önceki öğrenmelerin" in rec["eslesmeler"]
    assert rec["insan_birim_iliskisi"] is None and rec["gerekce"]
    dv = [d for d in sh.data_validations.dataValidation if "kendi" in (d.formula1 or "")]
    assert dv and "belirsiz" not in dv[0].formula1 and "baska_birim" in dv[0].formula1
    assert dv[0].formula1.strip('"').split(",")[-1] == "model"                 # modelin kararına dön
    note = str(sh.cell(row=1, column=1).value)
    assert "'model'" in note and "Boş hücre: önceki insan kararı korunur" in note
    g = paths["gaps"].read_text(encoding="utf-8")
    assert "## Başka birime ait sayılan belgeler" in g and SHEET_UNIT in g and f"`{x}`" in g


# -- geri alma: eşleşmeli ---------------------------------------------------------------------

def test_revert_with_matches_restores_rows_for_review(ws):
    root, ids = ws
    x = ids["ekle"]
    _other_unit(root)
    _, paths = audit(root)
    _set_unit(paths["xlsx"], x, "kendi", "bölümün kendi komisyonu")
    st = audit_apply(root)
    assert st["birim"] == {"geri_alinan": [x]} and not st["birim_gecersiz"]
    pins = {r["doc_id"]: r for r in read_jsonl(root / FILES["birim"])}
    assert pins[x]["birim_iliskisi"] == "kendi" and pins[x]["model_iliskisi"] == "baska_birim"
    assert pins[x]["yeniden_karar"] is False and pins[x]["kaynak"] == "insan"
    assert not review_state(root)["guncel"]                # tabloyu yenile: yeni satır gelecek
    # decisions.jsonl değişmez; görünüm insan kararıyla
    assert _recs(root)[x]["ince"]["birim_iliskisi"] == "baska_birim"
    a, paths = audit(root)
    r = a.by_key[f"{x}|B.2.3/2"]
    assert r["birim_iliskisi"] == "kendi" and r["sayilir"] and r["od"] == 3 and r["etkin_asama"] == "uygula"
    assert "birim_iliskisi_insan" in r["flags"] and r["karar"] == ""            # karar insanda
    assert x not in [b["doc_id"] for b in a.birim["baska_birim"]]
    g = paths["gaps"].read_text(encoding="utf-8")
    assert "## Başka birime ait sayılan belgeler" not in g
    assert "## Birim ilişkisi komisyonca değiştirilen belgeler" in g and "baska_birim → kendi" in g
    # yeni tabloda satır ana sayfada; birim sayfasında insan değeri dolu (geri dönüş mümkün)
    wb = load_workbook(paths["xlsx"])
    assert any(c.value == f"{x}|B.2.3/2" for c in wb[SHEET_ROWS]["A"])
    u = {r["doc_id"]: r for r in read_unit_sheet(paths["xlsx"])}
    assert u[x]["insan_birim_iliskisi"] == "kendi" and "geri alındı" in u[x]["durum"]
    rs = review_state(root)
    assert rs["guncel"] and rs["uygulanmamis_duzeltme"] == 0 and rs["satir"] > rs["kararli"]
    # ajanın yeniden işleme özeti bu belgeyi "istem değişti" saymaz (karar audit'te uygulandı)
    pst = prepare(root, "fine", backend=Rel("baska_birim").backend())
    assert x not in pst["eski"]
    assert karar_tamam(_karar_ctx(root)).bitti
    # boş hücre önceki insan kararını korur (ana sayfadaki boş KARAR gibi)
    _set_unit(paths["xlsx"], x, "")
    assert review_state(root)["uygulanmamis_duzeltme"] == 0
    st = audit_apply(root)
    assert st["birim"] == {} and R.load_unit_pins(root)[x]["birim_iliskisi"] == "kendi"
    assert f"{x}|B.2.3/2" in build(root).by_key
    # `model`: insan kararını kaldırır, modelin kararına dönülür
    _set_unit(paths["xlsx"], x, "model")
    assert review_state(root)["uygulanmamis_duzeltme"] == 1
    st = audit_apply(root)
    assert st["birim"] == {"kaldirilan": [x]} and not (root / FILES["birim"]).exists()
    assert f"{x}|B.2.3/2" not in build(root).by_key
    # karar yokken `model` değişiklik değildir
    a, paths = audit(root)
    _set_unit(paths["xlsx"], x, "model")
    assert review_state(root)["uygulanmamis_duzeltme"] == 0
    assert audit_apply(root)["birim"] == {}


def test_revert_to_faculty_wide_caps_od2(ws):
    root, ids = ws
    x = ids["ekle"]
    _other_unit(root)
    _, paths = audit(root)
    _set_unit(paths["xlsx"], x, "fakulte_geneli")
    audit_apply(root)
    a = build(root)
    r = a.by_key[f"{x}|B.2.3/2"]
    assert r["od_kabul"] == 2 and r["etkin_asama"] == "planla" and r["od"] == 2
    assert {"uygulama_kaniti_eksik", "kurum_geneli", "fakulte_geneli", "birim_iliskisi_insan"} <= set(r["flags"])
    # üst birim kararı: tavan yok
    _, paths = audit(root)
    _set_unit(paths["xlsx"], x, "ust_birim_bu_birim_hakkinda")
    audit_apply(root)
    r = build(root).by_key[f"{x}|B.2.3/2"]
    assert r["od"] == 3 and "uygulama_kaniti_eksik" not in r["flags"]


def test_human_confirms_other_unit(ws):
    root, ids = ws
    x = ids["ekle"]
    _other_unit(root)
    _, paths = audit(root)
    _set_unit(paths["xlsx"], x, "baska_birim", "Kimya bölümünün tutanağı")
    st = audit_apply(root)
    assert st["birim"] == {"baska_birim_onay": [x]}
    pins = {r["doc_id"]: r for r in read_jsonl(root / FILES["birim"])}
    assert pins[x]["yeniden_karar"] is False
    a, paths = audit(root)
    assert not any(r["doc_id"] == x for r in a.rows)
    assert [b.get("insan") for b in a.birim["baska_birim"]] == [True]
    g = paths["gaps"].read_text(encoding="utf-8")
    assert f"(`{x}`) (insan onayladı)" in g and "komisyonca değiştirilen" not in g
    assert karar_tamam(_karar_ctx(root)).bitti and not R.pending_redecide(_recs(root), R.load_unit_pins(root))


def test_invalid_value_rejected(ws):
    root, ids = ws
    x = ids["ekle"]
    _other_unit(root)
    _, paths = audit(root)
    _set_unit(paths["xlsx"], x, "belirsiz")
    st = audit_apply(root)
    assert f"birim:{x}" in st["birim_gecersiz"] and not (root / FILES["birim"]).exists()
    assert review_state(root)["uygulanmamis_duzeltme"] == 1
    _set_unit(paths["xlsx"], x, "Kendi")                   # büyük harf/yazım normalleşir
    assert audit_apply(root)["birim"] == {"geri_alinan": [x]}


# -- geri alma: eşleşmesiz → yeniden karar, pakette sabit ilişki ---------------------------------

def test_revert_without_matches_needs_redecision_with_pinned_relation(ws):
    root, ids = ws
    x = ids["ekle"]
    _other_unit(root, drop_matches=True)
    _, paths = audit(root)
    _set_unit(paths["xlsx"], x, "kendi")
    st = audit_apply(root)
    assert st["birim"] == {"yeniden_karar": [x]}
    assert {r["doc_id"]: r for r in read_jsonl(root / FILES["birim"])}[x]["yeniden_karar"] is True
    a, paths = audit(root)
    u = {r["doc_id"]: r for r in read_unit_sheet(paths["xlsx"])}
    assert "yeniden karar gerekli" in u[x]["durum"]
    assert "yeniden karar gerekli" in paths["gaps"].read_text(encoding="utf-8")
    # status/next: ince karar aşaması bekleyen iş gösterir
    ck = karar_tamam(_karar_ctx(root))
    assert not ck.bitti and ck.kim == "komut" and ck.komutlar == [f"bidr decide prepare --stage fine --only {x}"]
    assert ck.ilerleme["birim_yeniden_karar"] == 1
    # prepare --only: insan ilişkisi pakete sabit bilgi
    fake = Rel("baska_birim")                  # model yine başka birim der: alan insan değerine zorlanır
    b = fake.backend()
    prepare(root, "fine", backend=b, only=[x])
    pkg = json.loads((root / "work" / "fine" / f"{x}.json").read_text(encoding="utf-8"))
    assert 'SABİT BİLGİ (komisyon kararı): bu belgenin birim_iliskisi "kendi"' in pkg["istem"]
    assert pkg["meta"]["birim_sabit"] == "kendi"
    _agent(root, fake, "fine")
    out = json.loads((root / "work" / "fine" / f"{x}.out.json").read_text(encoding="utf-8"))
    assert out["birim_iliskisi"] == "baska_birim"
    apply(root, "fine", backend=b)
    ince = _recs(root)[x]["ince"]
    assert ince["birim_iliskisi"] == "kendi" and ince["birim_iliskisi_kaynagi"] == "insan"
    assert ince["birim_iliskisi_model"] == "baska_birim"
    m = _recs(root)[x]["eslesmeler"][0]
    assert m["kabul"] and m["od_kabul"] == 3
    assert R.pending_redecide(_recs(root), R.load_unit_pins(root)) == []
    assert karar_tamam(_karar_ctx(root)).bitti
    # yeniden apply: artık yeniden karar gerekmez; satır incelemede
    audit_apply(root)
    assert {r["doc_id"]: r for r in read_jsonl(root / FILES["birim"])}[x]["yeniden_karar"] is False
    a, _ = audit(root)
    assert a.by_key[f"{x}|B.2.3/2"]["sayilir"]
    # sabit ilişkiyle karar verildi: istem aynı, eski sayılmaz
    assert x not in prepare(root, "fine", backend=b)["eski"]


def test_pinned_relation_in_provider_mode(ws):
    root, ids = ws
    x = ids["ekle"]
    (root / FILES["birim"]).write_text(json.dumps({"doc_id": x, "birim_iliskisi": "kurum_geneli",
                                                   "kaynak": "insan"}) + "\n", encoding="utf-8")
    fake = Rel("baska_birim")
    R.run(root, backend=fake.backend(), log=lambda m: None)
    rec = _recs(root)[x]
    assert rec["ince"]["birim_iliskisi"] == "kurum_geneli" and rec["eslesmeler"][0]["od_kabul"] == 2
    fine_inputs = [i for n, i in fake.calls if n == R.FINE and "[EKLE]" in i["belge_metni"]]
    assert '"kurum_geneli"' in fine_inputs[0]["birim"]


# -- geri uyumluluk ------------------------------------------------------------------------------

def test_old_review_without_unit_sheet(ws):
    root, ids = ws
    x = ids["ekle"]
    _other_unit(root)
    _, paths = audit(root)
    _set_unit(paths["xlsx"], x, "kendi")
    audit_apply(root)
    _, paths = audit(root)
    # eski tablo: birim sayfası ve birim_sha meta satırı yok
    wb = load_workbook(paths["xlsx"])
    del wb[SHEET_UNIT]
    meta = wb["_meta"]
    for row in list(meta.iter_rows()):
        if row[0].value == "birim_sha":
            meta.delete_rows(row[0].row)
    wb.save(paths["xlsx"])
    assert read_unit_sheet(paths["xlsx"]) is None
    st = audit_apply(root)
    assert not st["birim_gecersiz"] and st["birim"] == {}
    # var olan insan kararı korunur
    assert {r["doc_id"] for r in read_jsonl(root / FILES["birim"])} == {x}
    rs = review_state(root)
    assert rs["tablo"] and rs["uygulanmamis_duzeltme"] == 0
    # birim kararı yokken eski tablo da güncel sayılır
    (root / FILES["birim"]).unlink()
    assert review_state(root)["guncel"]
    audit(root)                                       # eski tablodan yenisi sorunsuz üretilir


# -- yeniden karar: önceki insan ilişkisinden kalan OD2 düşüşü -----------------------------------

def _redecide(root, x, fake):
    b = fake.backend()
    prepare(root, "fine", backend=b, only=[x])
    _agent(root, fake, "fine")
    apply(root, "fine", backend=b)


def test_faculty_then_own_needs_redecision(ws):
    root, ids = ws
    x = ids["ekle"]
    _other_unit(root, drop_matches=True)
    _, paths = audit(root)
    _set_unit(paths["xlsx"], x, "fakulte_geneli")
    assert audit_apply(root)["birim"] == {"yeniden_karar": [x]}
    fake = Rel("baska_birim")
    _redecide(root, x, fake)
    assert _recs(root)[x]["eslesmeler"][0]["od_kabul"] == 2                    # fakülte geneli: OD2
    a, paths = audit(root)
    assert a.by_key[f"{x}|B.2.3/2"]["od"] == 2
    # komisyon ilişkiyi `kendi` yapar: kayıttaki OD2 düşüşü görünümle kalkmaz → yeniden karar
    _set_unit(paths["xlsx"], x, "kendi")
    assert audit_apply(root)["birim"] == {"yeniden_karar": [x]}
    ck = karar_tamam(_karar_ctx(root))
    assert not ck.bitti and ck.komutlar == [f"bidr decide prepare --stage fine --only {x}"]
    u = {r["doc_id"]: r for r in read_unit_sheet(audit(root)[1]["xlsx"])}
    assert "yeniden karar gerekli" in u[x]["durum"]
    _redecide(root, x, fake)
    rec = _recs(root)[x]
    assert rec["ince"]["birim_iliskisi"] == "kendi" and rec["eslesmeler"][0]["od_kabul"] == 3
    assert karar_tamam(_karar_ctx(root)).bitti


# -- name: insan birim kararı (insan > model) ---------------------------------------------------

def _clear_decision_name(root, did):
    recs = _recs(root)
    recs[did]["ince"].pop("kanit_adi", None)
    (root / "decisions.jsonl").write_text("".join(json.dumps(recs[k], ensure_ascii=False) + "\n"
                                                  for k in sorted(recs)), encoding="utf-8")


def test_name_sees_reverted_doc(ws):
    from bidr.name import run as NR
    from bidr.name.resolve import Resolver
    root, ids = ws
    x = ids["ekle"]
    _other_unit(root)
    _clear_decision_name(root, x)                      # ince kararda model adı yok
    assert x not in NR.eligible(NR.decisions_view(Workspace(root)))
    _, paths = audit(root)
    _set_unit(paths["xlsx"], x, "kendi")
    audit_apply(root)
    # geri alınan belge kanıt: name paketine girer (geri yüklenen eşleşmeyle)
    assert x in NR.eligible(NR.decisions_view(Workspace(root)))
    st = NR.prepare(root)
    pkg = json.loads((root / "work" / "name" / f"{x}.json").read_text(encoding="utf-8"))
    assert "B.2.3" in pkg["istem"] and st["paket"] >= 1
    from bidr.pipeline.checks import name_tamam
    nst = {"komut": ["bidr name prepare", "(ajan)", "bidr name apply"]}
    ck = name_tamam(Ctx(Workspace(root), {}, lambda t: t, nst))
    assert not ck.bitti and ck.ilerleme["belge"] >= 1
    # komisyon başka birim onaylarsa kanıt değildir
    _, paths = audit(root)
    _set_unit(paths["xlsx"], x, "baska_birim")
    audit_apply(root)
    assert x not in NR.eligible(NR.decisions_view(Workspace(root)))
    assert Resolver.load(root).resolve(x)[1] == "kural"


def test_name_uses_fine_decision_name_for_reverted_doc(ws):
    from bidr.name import run as NR
    from bidr.name.resolve import Resolver
    root, ids = ws
    x = ids["ekle"]
    _other_unit(root)                                  # ince kararda kanit_adi var
    _, paths = audit(root)
    _set_unit(paths["xlsx"], x, "kendi")
    audit_apply(root)
    assert x in NR.eligible(NR.decisions_view(Workspace(root)))
    st = NR.prepare(root)
    assert not (root / "work" / "name" / f"{x}.json").exists() and st["zaten_adli"] >= 1
    assert Resolver.load(root).resolve(x)[:2] == ("Bölüm Kurulu Kararı", "model")
    a, _ = audit(root)
    assert a.by_key[f"{x}|B.2.3/2"]["kanit_adi"] == "Bölüm Kurulu Kararı"
