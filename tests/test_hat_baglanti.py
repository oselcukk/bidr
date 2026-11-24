"""Hatta bağlanan modüller: faaliyet / ikinci_arama / denetle aşamaları, render'ın eksik kanıt
notu, yeniden yazım paketinin bütün gerekçeleri ve yazım paketinin faaliyet özeti.
Yalnız sentetik veri; model çağrısı yok."""
from __future__ import annotations

import json
from pathlib import Path

import docx
import yaml

from bidr.candidates import arama as A
from bidr.common import Workspace
from bidr.pipeline import checks as C
from bidr.pipeline.state import formatter, stage
from bidr.render.run import BOS_IFADE, KAPSAM_DISI, render
from bidr.render.template import find_blocks
from bidr.verify import run as V
from bidr.write import run as W

from test_ikinci_arama import Q_B23, _answer
from test_ikinci_arama import ws as ia_ws  # noqa: F401  (fixture)
from test_render import _lines, make_template, write_text
from test_verify import verdicts, written
from test_write import GOOD, answer, make_report_ws


def _check(root: Path, sid: str):
    ws = Workspace(root)
    return C.CHECKS[stage(sid)["sart"]["denetim"]](C.Ctx(ws, {}, formatter(ws, {}), stage(sid)))


def _rapor(root: Path, **kw) -> None:
    p = root / "config.yaml"
    data = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
    data = data or {}
    data.setdefault("rapor", {}).update(kw)
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


# -- faaliyet ------------------------------------------------------------------------------------

def _fine(did, ad, tarih, asama):
    return {"doc_id": did, "durum": "ok", "asama": "ince", "karar": "olcut_var",
            "ince": {"karar": "olcut_var", "birim_iliskisi": "kendi",
                     "faaliyet": {"ad": ad, "tarih": tarih, "asama": asama}},
            "eslesmeler": [{"olcut": "B.1.1", "yuva": "B.1.1/1", "asama": "planla", "kabul": True, "od_kabul": 2}]}


def test_faaliyet_stage_current_and_stale(tmp_path):
    from bidr.faaliyet import run as F
    root = tmp_path / "ws"
    root.mkdir()
    recs = [_fine("d1", "Danışma Kurulu Toplantısı", "2025-03-10", "duyuru"),
            _fine("d2", "Danışma Kurulu Toplantısı", "2025-03-20", "gerceklesme")]
    (root / "decisions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs[:1]), encoding="utf-8")
    ck = _check(root, "faaliyet")
    assert not ck.bitti and ck.kim == "komut" and "faaliyet" in ck.komutlar[0] and "yok" in ck.neden
    F.run(root)
    ck = _check(root, "faaliyet")
    assert ck.bitti and ck.ilerleme["yalniz_duyuru"] == 1 and any("düzenlenmiştir" in u for u in ck.uyarilar)
    # kararlar değişti (ör. gerçekleşme belgesi eklendi): kayıt eskir
    (root / "decisions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
    ck = _check(root, "faaliyet")
    assert not ck.bitti and "eski" in ck.neden
    F.run(root)
    ck = _check(root, "faaliyet")
    assert ck.bitti and ck.ilerleme["yalniz_duyuru"] == 0 and not ck.uyarilar


# -- ikinci arama --------------------------------------------------------------------------------

def test_ikinci_arama_stage(ia_ws):  # noqa: F811
    root, ids = ia_ws
    ck = _check(root, "ikinci_arama")
    assert not ck.bitti and not ck.atlandi and ck.kim == "komut" and "arama prepare" in ck.komutlar[0]
    _rapor(root, ikinci_arama=False)
    ck = _check(root, "ikinci_arama")
    assert ck.atlandi and "rapor.ikinci_arama: false" in ck.neden
    _rapor(root, ikinci_arama=True)

    A.prepare(root, profile=None, olcutler=["B.2.3"])
    pkgs = sorted(p.stem for p in (root / "work" / A.WORK).glob("*.json") if not p.name.endswith(".out.json"))
    assert ids["rpl"] in pkgs
    ck = _check(root, "ikinci_arama")
    assert ck.kim == "ajan" and ck.ilerleme["cevapsiz"] == len(pkgs) and "arama apply" in ck.komutlar[1]
    for did in pkgs:
        if did != ids["rpl"]:
            _answer(root, did, {"karar": "olcut_yok", "gerekce": "uymuyor", "birim_iliskisi": "kendi",
                                "eslesmeler": []})
    _answer(root, ids["rpl"], {"karar": "olcut_var", "gerekce": "g", "birim_iliskisi": "kendi", "eslesmeler": [
        {"olcut": "B.2.3", "yuva": "B.2.3/2", "asama": "uygula", "od_onerisi": 3, "alinti": Q_B23,
         "gerekce": "AKTS", "guven": "yuksek"}]})
    ck = _check(root, "ikinci_arama")
    assert ck.kim == "komut" and "apply" in ck.komutlar[0] and ck.ilerleme["islenmemis"] == len(pkgs)
    assert A.apply(root, model="test")["eklenen_kabul"] == 1
    ck = _check(root, "ikinci_arama")
    assert ck.bitti and ck.ilerleme["kabul_eslesme"] == 1 and "1 kabul" in ck.neden
    # cevap değişti, işlenmedi → apply
    _answer(root, ids["rpl"], {"karar": "olcut_yok", "gerekce": "vazgeçti", "birim_iliskisi": "kendi",
                               "eslesmeler": []})
    assert _check(root, "ikinci_arama").kim == "komut"
    A.apply(root, model="test")
    assert _check(root, "ikinci_arama").bitti
    # ilk geçiş yeniden karara bağlandı: paket eski → prepare
    recs = [json.loads(x) for x in (root / "decisions.jsonl").read_text(encoding="utf-8").splitlines()]
    for r in recs:
        if r["doc_id"] == ids["rpl"]:
            r["ince"]["istem_sha"] = "s2"
    (root / "decisions.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs),
                                          encoding="utf-8")
    ck = _check(root, "ikinci_arama")
    assert ck.kim == "komut" and "eski" in ck.neden and "arama prepare" in ck.komutlar[0]


def test_audit_reason_mentions_second_search(tmp_path, monkeypatch):
    import bidr.audit.run as AR
    root = tmp_path / "ws"
    root.mkdir()
    rec = {"doc_id": "d1", "eslesmeler": [{"olcut": "B.2.3", "kabul": True, "ikinci_arama": True},
                                          {"olcut": "B.1.1", "kabul": False, "ikinci_arama": True}]}
    (root / "decisions.jsonl").write_text(json.dumps(rec) + "\n", encoding="utf-8")
    monkeypatch.setattr(AR, "review_state", lambda out, ws_root=None: {
        "tablo": True, "guncel": False, "satir": 3, "kararli": 3, "gecersiz": 0, "uygulanmamis": 0})
    ck = _check(root, "audit")
    assert ck.kim == "komut" and "bidr audit" in ck.komutlar[0]
    assert "İkinci arama 1 kabul edilmiş eşleşme ekledi" in ck.neden


# -- denetle -------------------------------------------------------------------------------------

def test_denetle_stage(tmp_path):
    from bidr.check.run import file_sha
    root = tmp_path / "ws"
    root.mkdir()
    rep = root / "report.docx"
    rep.write_bytes(b"sentetik rapor")
    ck = _check(root, "denetle")
    assert ck.kim == "komut" and "denetle" in ck.komutlar[0] and "denetim.json yok" in ck.neden

    def den(kritik, sha=None):
        (root / "denetim.json").write_text(json.dumps({
            "surum": 1, "docx": str(rep), "docx_sha": sha or file_sha(rep),
            "ozet": {"kritik": kritik, "uyari": 2, "yayima_hazir": kritik == 0,
                     "kodlar": {"taslak_damgasi": {"seviye": "kritik", "sayi": kritik},
                                "aralik": {"seviye": "uyari", "sayi": 2}}}}), encoding="utf-8")
    den(1)
    ck = _check(root, "denetle")
    assert not ck.bitti and ck.kim == "insan" and "yayıma hazır değil" in ck.neden and "taslak_damgasi" in ck.neden
    assert any("render" in k for k in ck.komutlar)
    den(0)
    ck = _check(root, "denetle")
    assert ck.bitti and "yayıma hazır" in ck.neden and ck.uyarilar
    rep.write_bytes(b"elle degisti")                       # docx değişti: denetim eskir
    ck = _check(root, "denetle")
    assert ck.kim == "komut" and "güncel" in ck.neden


def test_denetle_writes_docx_sha(tmp_path):
    from bidr.check.run import denetle, file_sha
    p = make_template(tmp_path / "s.docx")
    s = denetle(p).to_dict()
    assert s["docx_sha"] == file_sha(p)


# -- render: eksik kanıt notu --------------------------------------------------------------------

def _audit(ws: Path, items: dict) -> Path:
    p = ws / "audit-olcutler.json"
    p.write_text(json.dumps({"surum": 1, "olcutler": [
        {"olcut": c, "od": 2, "eksik": [{"halka": "uygula", "gereken": f"{c} için uygulama kanıtı"}], **x}
        for c, x in items.items()]}, ensure_ascii=False), encoding="utf-8")
    return p


NEREDEYSE = {"durum": "neredeyse_kanitsiz", "nedenler": ["yalniz_kurum_geneli"],
             "metin": "Eksik kanıt notu: bölümün bu döneme ait doğrudan kanıtı yok (yalnız kurum/fakülte geneli "
                      "düzenleme)."}
KANITSIZ = {"durum": "kanitsiz", "nedenler": [], "metin": "Eksik kanıt notu: A.1.2 için uygulama kanıtı."}


def test_render_missing_evidence_note(tmp_path):
    """Eksik kanıt notu komisyon içindir (gaps.md): metinli ya da metinsiz hiçbir ölçütte rapora girmez
    (kör test 2026-11-20); metni olup notu olan ölçüt yalnız kayda geçer."""
    ws = tmp_path / "ws"
    ws.mkdir()
    make_template(tmp_path / "sablon.docx", ids=(("A.1.1", "Yönetişim"), ("A.1.2", "Liderlik"),
                                                  ("A.1.3", "Dönüşüm"), ("A.1.4", "İç kalite")))
    for c in ("A.1.1", "A.1.3", "A.1.4"):
        write_text(ws / "texts", c)
    _audit(ws, {"A.1.1": {"eksik_kanit_notu": NEREDEYSE}, "A.1.2": {"eksik_kanit_notu": KANITSIZ},
                "A.1.3": {"eksik_kanit_notu": NEREDEYSE}, "A.1.4": {"eksik_kanit_notu": None}})

    def run(**kw):
        out = ws / "report.docx"
        res = render(tmp_path / "sablon.docx", out, texts_dir=ws / "texts", audit_path=ws / "audit-olcutler.json",
                     **kw)
        blocks, _ = find_blocks(docx.Document(str(out)))
        return res, {c: [x for x in _lines(b.aciklama_tc) if x.strip() and x.strip() != "Açıklamalar:"]
                     for c, b in blocks.items()}, blocks

    res, cell, blocks = run(kapsam={"A.1.3": "baska_birim"})
    assert not any("Eksik kanıt notu" in x or "Gereken" in x for c in cell for x in cell[c])
    assert cell["A.1.1"][0].startswith("A.1.1 sentetik paragraf")
    assert res.eksik_notlu == ["A.1.1"]
    assert cell["A.1.2"] == [BOS_IFADE]
    assert cell["A.1.3"] == [KAPSAM_DISI]
    _audit(ws, {"A.1.1": {}, "A.1.2": {}})
    _, cell, _ = run()
    assert cell["A.1.2"] == [BOS_IFADE]


# -- write: yeniden yazım gerekçeleri ------------------------------------------------------------

def test_rewrite_package_carries_all_reasons(tmp_path):
    ws = written(tmp_path)
    V.prepare(ws)
    out = verdicts(ws, karar={"p1.1": "desteklenmiyor"}, sorular={"izleme": ("uydurma_suphesi", ["p2.2"])})
    out["cumleler"][0]["gerekce"] = "alıntı kurul kararını göstermiyor"
    out["sorular"][1]["gerekce"] = "izleme sonucu kanıtta yok"
    answer(ws, "B.1.1", out, stage="verify")
    assert list(V.apply(ws)["reddedildi"]) == ["B.1.1"]
    st = W.prepare_rejected(ws)
    assert st["tur"] == {"B.1.1": 1}
    istem = json.loads((ws / "work/write/B.1.1.json").read_text(encoding="utf-8"))["istem"]
    assert "p1.1 (desteklenmiyor)" in istem and "alıntı kurul kararını göstermiyor" in istem
    assert "soru izleme" in istem and "uydurma_suphesi; p2.2" in istem and "izleme sonucu kanıtta yok" in istem
    assert "Beş soru denetimi" in istem


def test_rejection_section_code_and_extra_reasons():
    t = {"paragraflar": [{"metin": "Metin [1_OD2]."}],
         "dogrulama": {"gerekce": ["p1.1 atif_listede_yok: [9_OD2] listede yok", "elle eklenen gerekçe"]},
         "soru_kapsami": {"sorular": [{"soru": "iyilestirme", "baslik": "İyileştirme", "durum": "uydurma_suphesi",
                                       "yerler": ["p1.1"], "gerekce": "iyileştirme kanıtı yok"}]}}
    rec = {"kod_denetimi": [{"yer": "p1.1", "kod": "atif_listede_yok", "ayrinti": "[9_OD2] listede yok"}],
           "gerekce": ["p1.1 atif_listede_yok: [9_OD2] listede yok"]}
    s = W.rejection_section(t, rec, 1, 2)
    assert "Kod denetiminin bulduğu sorunlar" in s and s.count("[9_OD2] listede yok") == 1
    assert "elle eklenen gerekçe" in s and "soru iyilestirme" in s and "iyileştirme kanıtı yok" in s
    assert "(gerekçe kaydı yok)" not in s
    assert "(gerekçe kaydı yok)" in W.rejection_section({"paragraflar": []}, None, 1, 2)


# -- write: faaliyet özeti ve görev sürümü --------------------------------------------------------

def _faaliyetler(root: Path) -> None:
    data = {"sema": 1, "ozet": {}, "faaliyetler": [
        {"id": "F001", "ad": "Ders Planı Çalıştayı", "tarih": "2025-02-01", "durum": "gerceklesme_kanitsiz",
         "yalniz_duyuru": True, "asamalar": {"duyuru": ["aaaa000000000001"]}, "eksik": ["gerceklesme yok"],
         "belgeler": [{"doc_id": "aaaa000000000001", "asama": "duyuru"}]},
        {"id": "F002", "ad": "Danışma Kurulu Toplantısı", "tarih": "2025-03-20", "durum": "gerceklesme_kanitli",
         "yalniz_duyuru": False, "asamalar": {"duyuru": ["zzzz000000000009"], "gerceklesme": ["cccc000000000003"]},
         "eksik": [], "belgeler": [{"doc_id": "zzzz000000000009", "asama": "duyuru"},
                                   {"doc_id": "cccc000000000003", "asama": "gerceklesme"}]},
        {"id": "F003", "ad": "İlgisiz Etkinlik", "tarih": None, "durum": "gerceklesme_kanitli",
         "yalniz_duyuru": False, "asamalar": {"gerceklesme": ["yyyy000000000008"]}, "eksik": [],
         "belgeler": [{"doc_id": "yyyy000000000008", "asama": "gerceklesme"}]}]}
    (root / "faaliyetler.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_write_package_has_activity_summary_and_rule(tmp_path):
    ws = make_report_ws(tmp_path, with_c=True)
    W.prepare(ws)
    istem = json.loads((ws / "work/write/B.1.1.json").read_text(encoding="utf-8"))["istem"]
    assert "FAALİYETLER" in istem and "yok (bu ölçütün kanıtları bir faaliyet kaydına bağlı değil)" in istem
    assert "yalnız FAALİYETLER bölümünde gerçekleşmesi kanıtlı faaliyet" in istem
    _faaliyetler(ws)
    W.prepare(ws)
    pkg = json.loads((ws / "work/write/B.1.1.json").read_text(encoding="utf-8"))
    istem = pkg["istem"]
    sec = istem.split("FAALİYETLER (kanıtların")[1].split("ÖNCEKİ YIL METNİ")[0]
    assert "Ders Planı Çalıştayı (2025-02-01)" in sec and "YALNIZ DUYURU" in sec and "duyuru: [1_OD2]" in sec
    assert "Danışma Kurulu Toplantısı" in sec and "gerceklesme: [3_OD4]" in sec
    assert "1 belge bu ölçütün kanıtı değil" in sec and "gerçekleşmesi kanıtlı" in sec
    assert "İlgisiz Etkinlik" not in sec
    assert [f["id"] for f in pkg["meta"]["faaliyetler"]] == ["F001", "F002"]
    assert pkg["meta"]["faaliyetler"][0]["yalniz_duyuru"] is True
    assert str(pkg["surum"]) == W.task_version() == "5"


def test_verify_prompt_announcement_rule():
    from bidr.llm import load_task
    assert "yalnız duyuru, davet ya da afiş kanıtına dayanıyorsa" in load_task("verify_text").prompt
    assert '"kismen"' in load_task("verify_text").prompt


def test_old_version_text_stays_valid(tmp_path):
    ws = make_report_ws(tmp_path)
    W.prepare(ws)
    answer(ws, "B.1.1", GOOD)
    assert W.apply(ws)["islenen"] == 1
    t = json.loads((ws / "texts/B.1.1.json").read_text(encoding="utf-8"))
    t["kaynak"]["gorev_surumu"] = "1"                      # v1 ile yazılmış metin
    t["kaynak"]["temel_istem_sha"] = t["kaynak"]["istem_sha"] = "eski"
    (ws / "texts/B.1.1.json").write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")
    for p in (ws / "work/write").glob("B.1.1*"):
        p.unlink()
    st = W.prepare(ws)
    assert st["eski_surum"] == ["B.1.1"] and st["paket"] == 0 and not (ws / "work/write/B.1.1.json").exists()
    ck = _check(ws, "write")
    assert ck.bitti and any("eski yazım kuralıyla" in u and "--eski-kurallar" in u for u in ck.bilgi)
    assert not any("eski yazım kuralıyla" in u for u in ck.uyarilar)    # bilgi, kullanıcı uyarısı değil
    # yeni kuralla yeniden yazmak isteğe bağlı
    assert W.prepare(ws, only=["B.1.1"])["paket"] == 1
    # kanıt listesi/OD değişirse eski metin de yeniden yazılır
    (ws / "work/write/B.1.1.json").unlink()
    t["girdi_sha"] = "baska"
    (ws / "texts/B.1.1.json").write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")
    assert W.prepare(ws)["paket"] == 1
