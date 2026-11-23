"""`bidr verify`: uçtan uca sentetik (yazım → kod denetimi → sahte doğrulayıcı cevabı)."""
from __future__ import annotations

import csv
import json

from test_write import GOOD, answer, make_report_ws

from bidr.common import Workspace
from bidr.verify import run as V
from bidr.write import run as W
from bidr.write import sources as S


def written(tmp_path, out=None, **kw):
    ws = make_report_ws(tmp_path, **kw)
    W.prepare(ws)
    answer(ws, "B.1.1", out or GOOD)
    assert W.apply(ws)["islenen"] == 1
    return ws


SORU_IDS = [k for k, _ in V.SORULAR]


def verdicts(ws, karar: dict | None = None, default="destekleniyor", sorular: dict | None = None):
    """Sahte doğrulayıcı cevabı; `sorular`: {soru: (durum, [yer])}, verilmeyen soru cevapsız."""
    pkg = json.loads((ws / "work/verify/B.1.1.json").read_text(encoding="utf-8"))
    karar, sorular = karar or {}, sorular or {}
    return {"cumleler": [{"yer": c["yer"], "karar": karar.get(c["yer"], default), "gerekce": "g"}
                         for c in pkg["meta"]["cumleler"]],
            "sorular": [{"soru": k, "durum": sorular.get(k, ("cevapsiz", []))[0],
                         "yerler": sorular.get(k, ("cevapsiz", []))[1], "gerekce": "sg"} for k in SORU_IDS],
            "genel": ""}


def text(ws):
    return json.loads((ws / "texts/B.1.1.json").read_text(encoding="utf-8"))


def test_end_to_end_verified(tmp_path):
    ws = written(tmp_path)
    st = V.prepare(ws)
    assert st["paket"] == 1 and not st["kod_reddi"]
    pkg = json.loads((ws / "work/verify/B.1.1.json").read_text(encoding="utf-8"))
    assert [c["yer"] for c in pkg["meta"]["cumleler"]] == ["p1.1", "p2.1", "p2.2"]
    assert "AKTS kredisi, toplam iş yükünün 25'e bölümüdür." in pkg["istem"]   # kanıt alıntısı
    assert "Önerilen OD: 3" in pkg["istem"] and "bağlam 1" in pkg["istem"]
    answer(ws, "B.1.1", verdicts(ws), stage="verify")
    st = V.apply(ws, model="test:dogrulayici")
    assert st["dogrulandi"] == ["B.1.1"]
    assert text(ws)["durum"] == "dogrulandi"
    rec = [json.loads(x) for x in (ws / "verify.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rec[0]["durum"] == "dogrulandi" and rec[0]["model"] == "test:dogrulayici"
    assert len(rec[0]["cumleler"]) == 3
    assert V.prepare(ws)["zaten_tamam"] == 1                # sonuçlanmış metin yeniden paketlenmez


def test_unsupported_sentence_rejects(tmp_path):
    ws = written(tmp_path)
    V.prepare(ws)
    answer(ws, "B.1.1", verdicts(ws, {"p2.2": "desteklenmiyor"}), stage="verify")
    st = V.apply(ws)
    assert list(st["reddedildi"]) == ["B.1.1"] and "p2.2 (desteklenmiyor)" in st["reddedildi"]["B.1.1"][0]
    t = text(ws)
    assert t["durum"] == "reddedildi" and t["dogrulama"]["gerekce"][0].startswith("p2.2")


def test_partial_sentence_rejects(tmp_path):
    ws = written(tmp_path)
    V.prepare(ws)
    answer(ws, "B.1.1", verdicts(ws, {"p1.1": "kismen"}), stage="verify")
    assert "B.1.1" in V.apply(ws)["reddedildi"] and text(ws)["durum"] == "reddedildi"


def test_incomplete_verdicts_invalid(tmp_path):
    ws = written(tmp_path)
    V.prepare(ws)
    out = verdicts(ws)
    out["cumleler"] = out["cumleler"][:-1] + [{"yer": "p9.1", "karar": "destekleniyor", "gerekce": "g"}]
    answer(ws, "B.1.1", out, stage="verify")
    st = V.apply(ws)
    errs = st["gecersiz"]["B.1.1"]
    assert any("p9.1" in e for e in errs) and any("p2.2" in e for e in errs)
    assert text(ws)["durum"] == "taslak"


def test_code_rejects_quote_not_in_document(tmp_path):
    ws = written(tmp_path)
    rows = list(csv.DictReader(open(ws / S.INDEX, encoding="utf-8")))
    rows[1]["alintilar"] = json.dumps(["Bu cümle belgenin hiçbir yerinde yazmamaktadır kesinlikle."])
    with open(ws / S.INDEX, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    st = V.prepare(ws)
    assert "B.1.1" in st["kod_reddi"] and any("alinti_belgede_yok" in x for x in st["kod_reddi"]["B.1.1"])
    assert text(ws)["durum"] == "reddedildi" and not (ws / "work/verify/B.1.1.json").exists()


def test_code_rejects_when_od_drops(tmp_path):
    ws = written(tmp_path)
    make_report_ws(tmp_path, od=2)                     # audit sonradan OD2'ye indi
    st = V.prepare(ws)
    assert any("od_asimi" in x for x in st["kod_reddi"]["B.1.1"])


def test_text_changed_after_prepare_is_stale(tmp_path):
    ws = written(tmp_path)
    V.prepare(ws)
    answer(ws, "B.1.1", verdicts(ws), stage="verify")
    t = text(ws)
    t["paragraflar"][0]["metin"] = t["paragraflar"][0]["metin"].replace("süreç", "işleyiş")
    (ws / "texts/B.1.1.json").write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")
    st = V.apply(ws)
    assert st["eski"] == ["B.1.1"] and text(ws)["durum"] == "taslak"


def test_rewrite_resets_and_reverifies(tmp_path):
    ws = written(tmp_path)
    V.prepare(ws)
    answer(ws, "B.1.1", verdicts(ws, {"p2.2": "desteklenmiyor"}), stage="verify")
    V.apply(ws)
    W.prepare(ws, only=["B.1.1"], redo=True)
    fixed = {"paragraflar": GOOD["paragraflar"][:1], "onceki_yila_gore": ""}
    answer(ws, "B.1.1", fixed)
    assert W.apply(ws)["islenen"] == 1 and text(ws)["durum"] == "taslak"
    assert V.prepare(ws)["paket"] == 1
    answer(ws, "B.1.1", verdicts(ws), stage="verify")
    assert V.apply(ws)["dogrulandi"] == ["B.1.1"]


def test_cli(tmp_path, capsys):
    from bidr.cli import main
    ws = written(tmp_path)
    assert main(["verify", "prepare", "-w", str(ws)]) == 0
    answer(ws, "B.1.1", verdicts(ws, {"p1.1": "desteklenmiyor"}), stage="verify")
    assert main(["verify", "apply", "-w", str(ws), "--model", "x"]) == 1
    assert "reddedildi B.1.1" in capsys.readouterr().out


# -- beş zorunlu soru (K29) -----------------------------------------------------------------------

def coverage(ws):
    return json.loads((ws / V.SUMMARY).read_text(encoding="utf-8"))


def test_questions_match_guide_and_prompt(tmp_path):
    assert [f"- {q}" for _, q in V.SORULAR] == W.writing_questions().splitlines()
    ws = written(tmp_path)
    V.prepare(ws)
    pkg = json.loads((ws / "work/verify/B.1.1.json").read_text(encoding="utf-8"))
    assert pkg["surum"] == "3" and all(f"- {k}: " in pkg["istem"] for k in SORU_IDS)
    assert pkg["sema"]["properties"]["sorular"]["minItems"] == 5


def test_unanswered_question_does_not_reject(tmp_path):
    ws = written(tmp_path)
    V.prepare(ws)
    answer(ws, "B.1.1", verdicts(ws, sorular={"surec": ("kanitla_cevaplandi", ["p1.1"]),
                                              "kanitlar": ("kanitla_cevaplandi", ["p1.1", "p2.1"])}),
           stage="verify")
    assert V.apply(ws)["dogrulandi"] == ["B.1.1"]
    t = text(ws)
    k = {q["soru"]: q for q in t["soru_kapsami"]["sorular"]}
    assert t["soru_kapsami"]["durum"] == "denetlendi" and k["surec"]["yerler"] == ["p1.1"]
    assert k["izleme"]["durum"] == "cevapsiz"
    rec = V.load_log(V.Workspace(ws))["B.1.1"]
    assert rec["soru_kapsami"] == t["soru_kapsami"]
    s = coverage(ws)
    assert s["olcutler"]["B.1.1"]["kanitla_cevaplanmayan"] == ["izleme", "iyilestirme", "onceki_yil"]
    assert [(x["olcut"], x["soru"], x["durum"]) for x in s["kanitla_cevaplanmayan"]] == [
        ("B.1.1", "izleme", "cevapsiz"), ("B.1.1", "iyilestirme", "cevapsiz"), ("B.1.1", "onceki_yil", "cevapsiz")]
    assert s["denetlenmedi"] == [] and s["kanitla_cevaplanmayan"][0]["baslik"].startswith("İzleme")


def test_fabricated_answer_rejects_even_if_sentences_supported(tmp_path):
    ws = written(tmp_path)
    V.prepare(ws)
    answer(ws, "B.1.1", verdicts(ws, sorular={"izleme": ("uydurma_suphesi", ["p2.2"])}), stage="verify")
    st = V.apply(ws)
    assert list(st["reddedildi"]) == ["B.1.1"]
    assert any(w.startswith("soru izleme (uydurma_suphesi; p2.2)") for w in st["reddedildi"]["B.1.1"])
    assert text(ws)["durum"] == "reddedildi"
    x = [x for x in coverage(ws)["kanitla_cevaplanmayan"] if x["soru"] == "izleme"]
    assert x[0]["durum"] == "uydurma_suphesi" and x[0]["yerler"] == ["p2.2"]
    assert "B.1.1" in V.rejected(V.Workspace(ws))           # yeniden yazım döngüsüne girer


def test_invalid_question_answers(tmp_path):
    ws = written(tmp_path)
    V.prepare(ws)
    out = verdicts(ws, sorular={"surec": ("kanitla_cevaplandi", []), "izleme": ("cevapsiz", ["p1.1"]),
                                "iyilestirme": ("uydurma_suphesi", ["p7.1"])})
    out["sorular"][3]["soru"] = "surec"                       # kanitlar eksik, surec iki kez
    answer(ws, "B.1.1", out, stage="verify")
    errs = V.apply(ws)["gecersiz"]["B.1.1"]
    joined = " | ".join(errs)
    for frag in ("surec: birden çok karar", "izleme: cevapsiz ama cümle yeri", "p7.1",
                 "kararı olmayan soru: kanitlar", "kanitla_cevaplandi için cümle yeri"):
        assert frag in joined, frag
    assert text(ws)["durum"] == "taslak"


def test_question_answered_only_by_commission_is_invalid():
    meta = {"cumleler": [{"yer": "p1.1", "metin": "Plan vardır [komisyon].", "atiflar": []}]}
    out = {"sorular": [{"soru": k, "durum": "kanitla_cevaplandi" if k == "iyilestirme" else "cevapsiz",
                        "yerler": ["p1.1"] if k == "iyilestirme" else [], "gerekce": "g"} for k in SORU_IDS]}
    k, errs = V.judge_questions(meta, out)
    assert k is None and "kanıta atıf yapmıyor" in errs[0]


def test_missing_sorular_field_is_invalid_for_v2(tmp_path):
    ws = written(tmp_path)
    V.prepare(ws)
    out = verdicts(ws)
    del out["sorular"]
    answer(ws, "B.1.1", out, stage="verify")
    assert "B.1.1" in V.apply(ws)["gecersiz"]


def test_old_v1_verification_stays_valid_unchecked(tmp_path):
    """Görev v1 ile doğrulanmış (soru alanı olmayan) kayıt geçerli kalır; kapsam "denetlenmedi"."""
    ws = written(tmp_path)
    t = text(ws)
    t["durum"] = "dogrulandi"
    (ws / "texts/B.1.1.json").write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")
    rec = {"olcut": "B.1.1", "durum": "dogrulandi", "metin_sha": W.text_sha(t), "asama": "model",
           "cumleler": [], "gorev_surumu": "1", "gerekce": [], "model": "eski"}
    (ws / "verify.jsonl").write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")
    st = V.prepare(ws)
    assert st["zaten_tamam"] == 1 and st["paket"] == 0
    s = coverage(ws)
    assert s["olcutler"]["B.1.1"]["durum"] == "denetlenmedi" and s["denetlenmedi"] == ["B.1.1"]
    assert s["kanitla_cevaplanmayan"] == [] and text(ws)["durum"] == "dogrulandi"
    assert V.coverage_of(rec, t) == {"durum": "denetlenmedi", "sorular": []}


def test_code_reject_and_stale_text_are_unchecked(tmp_path):
    ws = written(tmp_path)
    V.prepare(ws)
    answer(ws, "B.1.1", verdicts(ws, sorular={"surec": ("kanitla_cevaplandi", ["p1.1"])}), stage="verify")
    V.apply(ws)
    assert coverage(ws)["olcutler"]["B.1.1"]["durum"] == "denetlendi"
    make_report_ws(tmp_path, od=2)                     # OD düştü → kod reddi
    V.prepare(ws, redo=True)
    assert text(ws)["soru_kapsami"]["durum"] == "denetlenmedi"
    assert coverage(ws)["denetlenmedi"] == ["B.1.1"]


def test_verified_text_rechecked_with_new_content_rule(tmp_path):
    """Kör test 2026-11-20: yeni yazım kuralı (dönem içi kayıt, fakülte değeri) doğrulanmış eski metinlere
    uygulanmıyordu. verify prepare doğrulanmış metni içerik denetiminden geçirir; takılan metin tur
    sayacı sıfırlanarak yeniden yazıma gider, temiz metin dokunulmaz."""
    fak = {"paragraflar": [{"metin": "Ders bilgi formlarında toplam iş yükü 150 olarak verilmiştir [2_OD3]."},
                           {"metin": "Fakülte genelinde gerçekleşme değeri 0,36 olarak hesaplanmıştır [2_OD3]."}],
           "onceki_yila_gore": ""}
    ws = written(tmp_path)
    V.prepare(ws)
    answer(ws, "B.1.1", verdicts(ws), stage="verify")
    assert V.apply(ws)["dogrulandi"] == ["B.1.1"]
    assert V.prepare(ws)["zaten_tamam"] == 1 and text(ws)["durum"] == "dogrulandi"
    # aynı metin elle (eski kural döneminden kalmış gibi) fakülte değeriyle doğrulanmış
    t = text(ws)
    t["paragraflar"] = [{"metin": p["metin"], "atiflar": ["2_OD3"]} for p in fak["paragraflar"]]
    t["tur"] = 2
    (ws / "texts/B.1.1.json").write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")
    log = [json.loads(x) for x in (ws / "verify.jsonl").read_text(encoding="utf-8").splitlines()]
    log[0]["metin_sha"] = W.text_sha(t)
    (ws / "verify.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in log), encoding="utf-8")
    st = V.prepare(ws)
    assert st["yeni_kural"] == ["B.1.1"] and "B.1.1" in st["kod_reddi"]
    t = text(ws)
    assert t["durum"] == "reddedildi" and t["tur"] == 0
    assert any("fakulte_degeri" in g for g in t["dogrulama"]["gerekce"])
    st = W.prepare_rejected(ws)
    assert st["tur"] == {"B.1.1": 1} and not st["insan_gerekli"]


def _rejected_ws(tmp_path):
    ws = written(tmp_path)
    V.prepare(ws)
    answer(ws, "B.1.1", verdicts(ws, {"p2.2": "kismen"}), stage="verify")
    V.apply(ws, model="test:dogrulayici")
    assert text(ws)["durum"] == "reddedildi"
    return ws


def test_human_accept_keeps_text_and_trace(tmp_path):
    ws = _rejected_ws(tmp_path)
    r = V.decide(ws, "B.1.1", "kabul", "Matematik bölümüne ait olduğu belli")
    assert r["karar"] == "kabul" and r["dogrulayici_reddi"]
    t = text(ws)
    assert t["durum"] == "dogrulandi" and t["insan_karari"] == "kabul"
    assert t["dogrulama"]["gerekce"][0].startswith("insan onayıyla kabul (doğrulayıcı reddi: p2.2 (kismen)")
    assert t["dogrulama"]["dogrulayici_reddi"] and t["dogrulama"]["insan_onayi"]["not"]
    rec = V.load_log(Workspace(ws))["B.1.1"]
    assert rec["durum"] == "dogrulandi" and rec["asama"] == "insan"
    assert rec["dogrulayici_reddi"]["gerekce"][0].startswith("p2.2 (kismen)")
    assert not V.rejected(Workspace(ws))
    # yeniden doğrulanmaz (--redo dahil); eski doğrulayıcı cevabı yeniden işlenmez
    st = V.prepare(ws, redo=True)
    assert st["insan_kabulu"] == ["B.1.1"] and st["paket"] == 0
    assert V.apply(ws)["degismedi"] == 1 and text(ws)["durum"] == "dogrulandi"
    # ikinci kez karar verilemez: artık reddedilmiş değil
    import pytest
    with pytest.raises(ValueError):
        V.decide(ws, "B.1.1", "kabul")


def test_human_accept_not_for_code_reject(tmp_path):
    import pytest
    ws = written(tmp_path)
    make_report_ws(tmp_path, od=2)
    assert "B.1.1" in V.prepare(ws)["kod_reddi"]
    with pytest.raises(ValueError, match="kod denetiminde"):
        V.decide(ws, "B.1.1", "kabul")


def test_human_accept_cli_and_next(tmp_path, capsys):
    from bidr.cli import main
    ws = _rejected_ws(tmp_path)
    assert main(["verify", "karar", "-w", str(ws), "B.1.1", "kabul", "--not", "kimlik belli"]) == 0
    assert "insan onayıyla" in capsys.readouterr().out
    assert text(ws)["durum"] == "dogrulandi"


def test_human_accept_settles_verify_stage(tmp_path):
    """`bidr next`: kabul edilen ölçüt için artık insan beklenmez (verify aşaması biter, uyarı kalır)."""
    from bidr.pipeline import checks as C
    from bidr.pipeline.state import formatter, load_spec
    ws = _rejected_ws(tmp_path)
    w = Workspace(ws)
    spec = next(s for s in load_spec()["asamalar"] if s["id"] == "verify")
    ck = lambda: C.verify_tamam(C.Ctx(w, {}, formatter(w, {}), spec))   # noqa: E731
    assert not ck().bitti
    V.decide(ws, "B.1.1", "kabul")
    r = ck()
    assert r.bitti and any("insan onayıyla kabul" in u for u in r.uyarilar)
