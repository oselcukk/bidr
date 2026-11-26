"""bidr audit: ölçüt OD kuralı, gaps.md, review.xlsx ve apply (sentetik veri, model yok)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from openpyxl import load_workbook

from bidr.audit.rules import criterion_od, effective_stage
from bidr.audit.run import FILES, apply, audit, build, review_state
from bidr.audit.sheet import COLS, SHEET_ROWS
from bidr.cli import main
from bidr.common import read_jsonl, sha256_file
from bidr.criteria.loader import criteria_dir
from bidr.criteria.slots import TAGS_FILE

ALL = {"planla", "uygula", "kontrol_et", "onlem_al", "ozgun"}


# -- kural ---------------------------------------------------------------------------

@pytest.mark.parametrize("present,od,eksik", [
    (set(), 1, ["planla"]),
    ({"planla"}, 2, ["uygula"]),
    ({"planla", "uygula"}, 3, ["kontrol_et", "onlem_al"]),
    ({"planla", "uygula", "kontrol_et"}, 3, ["onlem_al"]),          # önlem yok → OD4 değil
    ({"planla", "uygula", "onlem_al"}, 3, ["kontrol_et"]),          # kontrol yok → OD4 değil
    ({"planla", "uygula", "kontrol_et", "onlem_al"}, 4, ["ozgun"]),
    ({"planla", "uygula", "kontrol_et", "onlem_al", "ozgun"}, 5, []),
    ({"planla", "uygula", "ozgun"}, 3, ["kontrol_et", "onlem_al"]),  # özgün tek başına sıçratmaz
    ({"uygula", "kontrol_et", "onlem_al"}, 4, ["ozgun"]),           # plan yok: örtük, zincir sürer (+ "plan önerilir")
    ({"uygula"}, 3, ["kontrol_et", "onlem_al"]),                    # yalnız uygulama: OD3 + "plan önerilir"
])
def test_chain(present, od, eksik):
    r = criterion_od(present, ALL)
    assert r.od == od and r.eksik == eksik


def test_chain_slotless_links():
    # A.1.2 gibi: plan/uygula yuvası yok → üst halka varsa aranmaz
    has = {"kontrol_et", "onlem_al", "ozgun"}
    assert criterion_od({"kontrol_et", "onlem_al"}, has).od == 4
    assert criterion_od({"kontrol_et"}, has).od == 3
    assert criterion_od(set(), has).od == 1
    # B.2.3 gibi: kontrol/önlem yuvası yok → OD4 kendiliğinden gelmez
    has = {"planla", "uygula", "ozgun"}
    r = criterion_od({"planla", "uygula"}, has)
    assert r.od == 3 and r.eksik == ["kontrol_et", "onlem_al"]


def test_effective_stage():
    assert effective_stage("kontrol_et", 4) == "kontrol_et"
    assert effective_stage("onlem_al", 4) == "onlem_al"
    assert effective_stage("kontrol_et", 3) == "uygula"
    assert effective_stage("ozgun", 3) == "uygula"
    assert effective_stage("uygula", None) is None


# -- sentetik çalışma alanı ------------------------------------------------------------

def _m(olcut, yuva, asama, od, guven="orta"):
    return {"olcut": olcut, "yuva": yuva, "asama": asama, "od_onerisi": od, "alinti": "x" * 30,
            "gerekce": "izleme sonucuna dayanan değişiklik" if asama == "onlem_al" else "g", "guven": guven,
            "denetim": {"red": [], "isaret": []}, "od_kabul": od, "kabul": True}


DOCS = {
    # doc_id: (tür, dönem içi, eşleşmeler)
    "d_plan": ("bolum_kurulu_karari", True, [_m("B.1.1", "B.1.1/1", "planla", 2)]),
    "d_uyg": ("bolum_kurulu_karari", True, [_m("B.1.1", "B.1.1/3", "uygula", 3)]),
    "d_kont": ("anket_sonucu", True, [_m("B.1.1", "B.1.1/6", "kontrol_et", 4)]),
    "d_onlem": ("toplanti_tutanagi", True, [_m("B.1.1", "B.1.1/5", "onlem_al", 4, guven="dusuk")]),
    "d_yon": ("yonerge", None, [_m("B.2.3", "B.2.3/2", "uygula", 3), _m("B.2.3", "B.2.3/1", "planla", 2)]),
    "d_eski": ("bolum_kurulu_karari", False, [_m("A.1.1", "A.1.1/2", "uygula", 3),
                                             _m("A.1.1", "A.1.1/1", "planla", 2)]),
}


@pytest.fixture
def ws(tmp_path):
    w = tmp_path / "ws"
    w.mkdir()
    with open(w / "decisions.jsonl", "w", encoding="utf-8") as f:
        for did, (_, _, ms) in DOCS.items():
            f.write(json.dumps({"doc_id": did, "durum": "ok", "asama": "ince", "karar": "olcut_var",
                                "eslesmeler": ms + [{**_m("B.1.1", "B.1.1/7", "ozgun", 5), "kabul": False}]},
                               ensure_ascii=False) + "\n")
        f.write(json.dumps({"doc_id": "d_atla", "durum": "atlandi"}) + "\n")
    with open(w / "documents.jsonl", "w", encoding="utf-8") as f:
        for did, (t, ici, _) in DOCS.items():
            f.write(json.dumps({"doc_id": did, "doc_type": t, "donem_ici": ici,
                                "calisma_adi": f"2025_{did}"}) + "\n")
    return w


def _crit(a, cid):
    return next(c for c in a.criteria if c["olcut"] == cid)


def test_build_od_and_flags(ws):
    a = build(ws)
    assert len(a.rows) == 8                         # reddedilen (kabul: false) eşleşme yok
    b11 = _crit(a, "B.1.1")
    assert b11["od"] == 3 and b11["od_dusuk_dahil"] == 4   # önlem yalnız düşük güvenle
    assert [e["halka"] for e in b11["eksik"]] == ["onlem_al"]
    assert {y["yuva"] for y in b11["eksik"][0]["yuvalar"]} == {"B.1.1/5", "B.1.1/6"}
    assert any("düşük güven" in n for n in b11["notlar"])
    # kurum geneli yönerge "uygula" dese de planla sayılır → uygulama kanıtı eksik
    b23 = _crit(a, "B.2.3")
    assert b23["od"] == 2 and b23["kurum_geneli_yalniz"]
    r = a.by_key["d_yon|B.2.3/2"]
    assert r["etkin_asama"] == "planla" and "uygulama_kaniti_eksik" in r["flags"]
    # dönem dışı (önceki yıl) olay belgesi: uygulama halkasını kanıtlamaz (geçmiş kanıt), ama hâlâ
    # yürürlükteki usul/karar olarak plan halkasını kanıtlar (`onceki_olay_plani_sayilir: true`,
    # kullanıcı kararı: "belgeler hâlâ uygulamada; her yıl müfredat değişmez")
    a11 = _crit(a, "A.1.1")
    u = a.by_key["d_eski|A.1.1/2"]
    assert a11["od"] == 2 and not u["sayilir"] and "gecmis_kanit" in u["flags"]
    p = a.by_key["d_eski|A.1.1/1"]
    # eski tarihli usul kararı rapor yılında yürürlükte varsayılır (sorulmaz; kullanıcı kararı 2026-11-26)
    assert p["sayilir"] and "yururluk_varsayildi" in p["flags"] and "gecmis_kanit" not in p["flags"]
    assert "guncellik_dogrulanmali" not in p["flags"]
    # boş ölçüt OD1, eksik yuvaları listeli
    a12 = _crit(a, "A.1.2")
    assert a12["od"] == 1 and a12["yuva_dolu"] == 0 and a12["bos_yuvalar"]
    # OD4'e yükselten satır vurgulu; öneri etiket ayrıca belirtilir
    assert "OD4" in a.by_key["d_kont|B.1.1/6"]["vurgu"] and "ÖNERİ" in a.by_key["d_kont|B.1.1/6"]["vurgu"]
    assert "düşük güven" in a.by_key["d_onlem|B.1.1/5"]["vurgu"]


def _fill(xlsx: Path, values: dict[str, dict]):
    wb = load_workbook(xlsx)
    sh = wb[SHEET_ROWS]
    head = [c.value for c in sh[1]]
    col = {k: head.index(h) + 1 for k, h, _, _ in COLS}
    for r in range(2, sh.max_row + 1):
        sid = sh.cell(row=r, column=col["satir"]).value
        for k, v in values.get(sid, values.get("*", {})).items():
            sh.cell(row=r, column=col[k], value=v)
    wb.save(xlsx)


def test_audit_files_and_apply_roundtrip(ws, tmp_path, capsys):
    out = tmp_path / "out"
    tag_file = criteria_dir() / TAGS_FILE
    tag_sha = sha256_file(tag_file)
    before = {p.name: p.read_bytes() for p in ws.iterdir()}
    assert main(["audit", "-w", str(ws), "--out", str(out)]) == 0
    assert "OD dağılımı" in capsys.readouterr().out
    for k in ("xlsx", "gaps", "json"):
        assert (out / FILES[k]).exists()
    assert {p.name: p.read_bytes() for p in ws.iterdir()} == before      # WS salt okunur
    gaps = (out / "gaps.md").read_text(encoding="utf-8")
    assert "B.2.3" in gaps and "uygulama kanıtı eksik" in gaps and "Boş yuvalar" in gaps
    wb = load_workbook(out / "review.xlsx")
    # sade sayfalar önde; teknik sayfalar (Eşleşmeler, Ölçüt özeti) gizli kalır
    assert wb.sheetnames[:3] == ["İnceleme", "Maddeler", "Nasıl doldurulur"] and wb["_meta"].sheet_state == "hidden"
    assert wb["Eşleşmeler"].sheet_state == "hidden" and wb["Ölçüt özeti"].sheet_state == "hidden"
    st = review_state(out, ws)
    assert st["tablo"] and st["guncel"] and st["satir"] == 8 and st["kararli"] == 0

    # geçersiz karar: apply 1 döner, kayda girmez
    _fill(out / "review.xlsx", {"*": {"karar": "kabul"}, "d_uyg|B.1.1/3": {"karar": "belki"}})
    assert main(["audit", "apply", "-w", str(ws), "--out", str(out)]) == 1
    assert "d_uyg|B.1.1/3" not in {r["satir"] for r in read_jsonl(out / FILES["decisions"])}

    # ret + düzelt + etiket kararları
    _fill(out / "review.xlsx", {
        "d_uyg|B.1.1/3": {"karar": "kabul"},
        "d_onlem|B.1.1/5": {"karar": "düzelt", "duzelt_asama": "onlem_al",
                            "etiket_karari": "duzelt", "etiket_yeni": "uygula, onlem_al", "not": "sınama"},
        "d_kont|B.1.1/6": {"karar": "kabul", "etiket_karari": "onayla"},
        "d_yon|B.2.3/2": {"karar": "ret"},
    })
    assert main(["audit", "apply", "-w", str(ws), "--out", str(out)]) == 0
    decs = {r["satir"]: r for r in read_jsonl(out / FILES["decisions"])}
    assert len(decs) == 8 and decs["d_yon|B.2.3/2"]["karar"] == "ret"
    assert decs["d_onlem|B.1.1/5"]["duzelt"]["asama"] == "onlem_al"
    js = json.loads((out / FILES["json"]).read_text(encoding="utf-8"))
    b11 = next(c for c in js["olcutler"] if c["olcut"] == "B.1.1")
    assert b11["od"] == 4          # düşük güvenli satır düzeltildi: insan kararı kuralı aşar, OD'ye katılır
    assert not any("düşük güven" in n and "doğrulanırsa" in n for n in b11["notlar"])
    oneri = yaml.safe_load((out / FILES["tag_oneri"]).read_text(encoding="utf-8"))
    by = {o["yuva"]: o for o in oneri["oneriler"]}
    assert by["B.1.1/5"]["oneri"] == {"asama": ["uygula", "onlem_al"], "od": [3, 4], "durum": "onayli"}
    assert by["B.1.1/6"]["degisiklik"] == "yalniz_onay"
    assert sha256_file(tag_file) == tag_sha                       # etiket dosyası değişmez
    st = review_state(out, ws)
    assert st["kararli"] == 8 and st["uygulanmamis"] == 0

    # yeniden üretim: işlenmiş kararlar tabloya geri gelir; işlenmemiş karar taşınır
    _fill(out / "review.xlsx", {"d_plan|B.1.1/1": {"not": "yeni not"}})
    a, _ = audit(ws, out=out)
    assert any("uygulanmamıştı" in u for u in a.uyarilar)
    assert (out / "review.onceki.xlsx").exists()
    xs = {r["satir"]: r for r in a.rows}
    assert xs["d_yon|B.2.3/2"]["karar"] == "ret" and xs["d_plan|B.1.1/1"]["not"] == "yeni not"
    assert not xs["d_yon|B.2.3/2"]["sayilir"]


def test_decisions_change_makes_table_stale(ws, tmp_path):
    out = tmp_path / "out"
    audit(ws, out=out)
    with open(ws / "decisions.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"doc_id": "d_yeni", "durum": "ok", "asama": "ince", "eslesmeler": []}) + "\n")
    assert not review_state(out, ws)["guncel"]


def test_apply_without_table(ws, tmp_path):
    with pytest.raises(FileNotFoundError):
        apply(ws, out=tmp_path / "yok")


# -- karardan sonra değişen satır: "yeniden bak" (karar korunur) -----------------------------

def _set_doc(ws, did, **kw):
    rows = [json.loads(x) for x in (ws / "documents.jsonl").read_text(encoding="utf-8").splitlines() if x]
    for r in rows:
        if r["doc_id"] == did:
            r.update(kw)
    (ws / "documents.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


@pytest.mark.parametrize("eski_calisma_alani", [False, True])
def test_relook_after_new_flag_keeps_decision(ws, tmp_path, eski_calisma_alani):
    out = tmp_path / "out"
    audit(ws, out=out)
    _fill(out / "review.xlsx", {"*": {"karar": "kabul"}})
    st = apply(ws, out=out)
    assert st["yeniden_bak"] == 0 and len(list(read_jsonl(out / FILES["gorulen"]))) == 8
    if eski_calisma_alani:          # özellikten önce işlenmiş kararlar: görülen durum önceki tablodan
        (out / FILES["gorulen"]).unlink()
        audit(ws, out=out)
    sid = "d_uyg|B.1.1/3"
    # yeni sürüm/yeni belge: aynı satırın belgesi artık önceki yıla ait (yeni işaret). Eski tarihli plan
    # (`yururluk_varsayildi`) varsayım işaretidir: yeniden baktırmaz.
    _set_doc(ws, "d_uyg", donem_ici=False)
    _set_doc(ws, "d_plan", donem_ici=False)
    a, _ = audit(ws, out=out)
    r = a.by_key[sid]
    assert r["karar"] == "kabul"                                  # insan kararı ezilmez
    assert r["yeniden_bak"] == "yeni işaret: gecmis_kanit"
    p = a.by_key["d_plan|B.1.1/1"]
    assert "yururluk_varsayildi" in p["flags"] and not p["yeniden_bak"]   # varsayım: baktırmaz
    assert any("yeniden bakılmalı" in u for u in a.uyarilar)
    st = review_state(out, ws)
    assert st["yeniden_bak"] == 1 and st["uygulanmamis"] == 0
    wb = load_workbook(out / "review.xlsx")
    sh = wb[SHEET_ROWS]
    head = [c.value for c in sh[1]]
    assert sh.cell(row=2, column=1).value == sid                  # yeniden bakılacak satır başta
    assert sh.cell(row=2, column=head.index("YENİDEN BAK: karardan sonra değişen") + 1).fill.fgColor.rgb.endswith("F8CBAD")
    # apply tek başına işareti kaldırmaz (insan bakmadı)
    assert apply(ws, out=out)["yeniden_bak"] == 1
    assert "yeni işaret" in audit(ws, out=out)[0].by_key[sid]["yeniden_bak"]
    # insan baktı: bakıldı = evet → apply → işaret kalkar, karar aynı
    _fill(out / "review.xlsx", {sid: {"bakildi": "evet"}})
    st = review_state(out, ws)
    assert st["yeniden_bak"] == 0 and st["uygulanmamis_duzeltme"] == 1
    assert apply(ws, out=out)["yeniden_bak"] == 0
    assert review_state(out, ws)["uygulanmamis_duzeltme"] == 0
    a, _ = audit(ws, out=out)
    assert not a.by_key[sid]["yeniden_bak"] and a.by_key[sid]["karar"] == "kabul"
    assert review_state(out, ws)["yeniden_bak"] == 0


def test_relook_od_change_and_redecision(ws, tmp_path):
    out = tmp_path / "out"
    audit(ws, out=out)
    _fill(out / "review.xlsx", {"*": {"karar": "kabul"}})
    apply(ws, out=out)
    # kurum geneli yönerge "uygula" eşleşmesi planla'ya iniyordu; tür birime ait karar olunca sayılan
    # aşama ve OD değişir
    sid = "d_yon|B.2.3/2"
    before = audit(ws, out=out)[0].by_key[sid]
    _set_doc(ws, "d_yon", doc_type="bolum_kurulu_karari", donem_ici=True)
    a, _ = audit(ws, out=out)
    r = a.by_key[sid]
    assert r["etkin_asama"] != before["etkin_asama"]
    assert "sayılan aşama" in r["yeniden_bak"] and "OD" in r["yeniden_bak"]
    # kararı değiştirmek de yeniden bakmaktır
    _fill(out / "review.xlsx", {sid: {"karar": "ret"}})
    apply(ws, out=out)
    assert not audit(ws, out=out)[0].by_key[sid]["yeniden_bak"]
