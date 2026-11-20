"""Komisyon/görev tanımı tabloları (aday ekleme) ve yalnız tablo başlığı alıntısı (sentetik veri)."""
from __future__ import annotations

import json

from bidr.candidates.komisyon import committee_criteria, is_committee_table
from bidr.common import read_jsonl
from bidr.decide import run as R

from synth import CS, make_ws
from test_decide import TAGS, FakeLLM

KOMISYON = (
    "Örnek Bölümü Kurul ve Komisyonları\n"
    "Komisyon Adı    Komisyon Üyeleri    Görevi    Görev Tanımı\n"
    "DEĞİŞİM PROGRAMLARI KOMİSYONU   Prof. Dr. A   Koordinatör   Lisans öğrencilerinin değişim\n"
    "                                                            programları kapsamındaki not dönüşümü.\n"
    "MEZUN KOMİSYONU   Doç. Dr. B   Üye   Öğrenciler için danışman öğretim üyelerinden gelen çizelgeler.\n"
    "AKADEMİK TEŞVİK KOMİSYONU   Dr. C   Üye   Teşvik başvurularının incelenmesi.\n"
)
SATIR = "Lisans öğrencilerinin değişim programları kapsamındaki not dönüşümü."


def test_committee_table_signal_and_criteria():
    assert is_committee_table(KOMISYON)
    assert committee_criteria(KOMISYON) == ["A.5.1", "B.3.2", "B.4.3"]
    assert committee_criteria(KOMISYON, {"A.5.1", "B.4.3"}) == ["A.5.1", "B.4.3"]
    # başlık sinyali yoksa (yalnız komisyon sözcüğü, görev tanımı tablosu değil) eklenmez
    tutanak = "KOMİSYON TUTANAĞI\nDeğişim programları başvuruları görüşüldü. Görev tanımı ileride yazılacak."
    assert not is_committee_table(tutanak) and committee_criteria(tutanak) == []


def test_merge_candidates_extra_after_coarse():
    row = {"adaylar": [{"olcut": x} for x in ("B.1.1", "A.1.4", "B.1.6", "C.3.2", "A.1.1")]}
    allowed = {s.id for s in CS.sub_criteria}
    c, det, cut = R.merge_candidates(["A.1.1", "A.1.4"], row, allowed, 5, 8, ["A.5.1", "A.1.4", "B.3.2"])
    assert c == ["A.1.1", "A.1.4", "A.5.1", "B.3.2", "B.1.1", "B.1.6", "C.3.2"] and not cut
    # extra yoksa eski davranış
    assert R.merge_candidates(["A.1.1"], row, allowed, 5, 3)[0] == ["A.1.1", "B.1.1", "A.1.4"]


def _ctx(tmp_path):
    docs = [{"text": KOMISYON, "gold": []}, {"text": "BÖLÜM KURULU KARARI\nProgram güncellendi. " * 3, "gold": []}]
    root = make_ws(tmp_path / "ws", docs)
    ids = [d["id"] for d in docs]
    with open(root / "candidates.jsonl", "w", encoding="utf-8") as f:
        for x in ids:
            f.write(json.dumps({"doc_id": x, "adaylar": [{"olcut": o} for o in
                                                         ("B.1.1", "A.1.4", "B.1.6", "C.3.2", "A.1.1")]}) + "\n")
    return R.Context.load(root), ids


def test_fine_inputs_committee_cap_and_others_unchanged(tmp_path):
    ctx, (kom, diger) = _ctx(tmp_path)
    rec = {"kaba": {"secilen": ["A.1.1", "A.4.1", "B.1.5", "A.4.2", "B.2.3"]}}
    _, meta = R.fine_inputs(ctx, kom, rec)
    assert meta["adaylar"][:8] == ["A.1.1", "A.4.1", "B.1.5", "A.4.2", "B.2.3", "A.5.1", "B.3.2", "B.4.3"]
    assert len(meta["adaylar"]) == R.KOMISYON_MAX_ADAY and meta["adaylar_komisyon"] == ["A.5.1", "B.3.2", "B.4.3"]
    # komisyon tablosu olmayan belge: tavan 6, ek alan yok
    _, meta = R.fine_inputs(ctx, diger, rec)
    assert len(meta["adaylar"]) == 6 and "adaylar_komisyon" not in meta
    # ikinci arama yalnız kendi ölçütlerini sorar
    _, meta = R.fine_inputs(ctx, kom, rec, komisyon=False)
    assert len(meta["adaylar"]) == 6 and "adaylar_komisyon" not in meta


def test_fine_prompt_budget_with_committee_candidates(tmp_path):
    """Komisyon tablosunda en uzun 8 aday + uzun metin: metin payı kısalır, istem bütçesi korunur."""
    from bidr.criteria.profiles import load_profile
    from bidr.decide import prompt as P
    allowed = load_profile("akademik_bolum").allowed(CS)
    big = sorted(allowed, key=lambda s: -len(P.fine_list(CS, [s], TAGS)))[:R.KOMISYON_MAX_ADAY]
    liste = P.fine_list(CS, big, TAGS)
    pay = min(P.FINE_CHARS, max(R.KOMISYON_MIN_METIN, P.FINE_CHARS - max(0, len(liste) - R.LISTE_BUTCE)))
    body, _ = P.excerpt("Kurul kararı metni. " * 5000, pay)
    fine = (R.TASKS_DIR / R.FINE / "prompt.md").read_text(encoding="utf-8") + liste + body
    assert pay < P.FINE_CHARS and P.approx_tokens(fine) < 8000


def test_table_header_only_quote_rejected():
    assert R.table_header_only("Komisyon Adı Komisyon Üyeleri - Ünvan/Statü Görevi Görev Tanımı")
    assert R.table_header_only("Komisyon Adı … Görev Tanımı … Komisyon Üyeleri")
    assert not R.table_header_only("Örnek Bölümü Kurul ve Komisyonları")
    assert not R.table_header_only(SATIR)
    head = "Komisyon Adı    Komisyon Üyeleri    Görevi    Görev Tanımı"
    base = {"olcut": "A.5.1", "yuva": "A.5.1/1", "asama": "planla", "od_onerisi": 2, "gerekce": "g",
            "guven": "orta"}
    rows = R.check_matches({"eslesmeler": [{**base, "alinti": head}, {**base, "yuva": "A.5.1/2", "alinti": SATIR}]},
                           ["A.5.1"], CS, TAGS, KOMISYON, FakeLLM.verify_quote)
    assert rows[0]["denetim"]["red"] == ["alinti_tablo_basligi"] and not rows[0]["kabul"]
    assert rows[1]["kabul"]


def test_gecersiz_md_explains_table_header(tmp_path):
    ctx, (kom, _) = _ctx(tmp_path)
    fake = FakeLLM()
    b = fake.backend()
    recs = {kom: {"doc_id": kom, "sema": R.SCHEMA, "durum": "ok", "asama": "kaba", "profil": ctx.profile,
                  "gorev": {R.COARSE: R.task_version(R.COARSE)},
                  "kaba": {"karar": "olcut_var", "olcutler": [], "secilen": ["A.5.1"], "gerekce": ""}}}
    R.save_decisions(ctx.ws, recs)
    R.prepare(ctx.ws.root, "fine", backend=b, only=[kom], ctx=ctx)
    d = R.work_dir(ctx.ws, "fine")
    head = "Komisyon Adı    Komisyon Üyeleri    Görevi    Görev Tanımı"
    out = {"karar": "olcut_var", "gerekce": "x", "birim_iliskisi": "kendi", "kanit_adi": "Bölüm Komisyonları",
           "eslesmeler": [{"olcut": "A.5.1", "yuva": "A.5.1/1", "asama": "planla", "od_onerisi": 2,
                           "alinti": head, "gerekce": "g", "guven": "orta"}]}
    (d / f"{kom}.out.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    st = R.apply(ctx.ws.root, "fine", model="test", backend=b, ctx=ctx)
    assert kom in st["alinti_tutmayan"]
    g = (d / "GECERSIZ.md").read_text(encoding="utf-8")
    assert "alinti_tablo_basligi" in g and "ilgili satırını alıntıla" in g
    rec = {r["doc_id"]: r for r in read_jsonl(ctx.ws.root / "decisions.jsonl")}[kom]
    assert rec["olcutler"] == [] and rec["adaylar_komisyon"] == ["A.5.1", "B.3.2", "B.4.3"]


def test_fine_prompt_asks_for_row_not_header():
    fine = (R.TASKS_DIR / R.FINE / "prompt.md").read_text(encoding="utf-8")
    assert "sütun adlarını değil ilgili satırı alıntıla" in fine
