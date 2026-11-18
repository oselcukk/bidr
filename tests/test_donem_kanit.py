"""Kör dağınık klasör testi düzeltmeleri (2026-11-19; sentetik veri, model yok):
dönem sonrası belge, eski olay belgesi, tarih kaynağı ve birden çok tarih, yapı sürümleri,
birim aitliği onayı, eksik kanıt notu ve yayımlanan listeye etkileri."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from openpyxl import load_workbook

from bidr.audit import donem as D
from bidr.audit.run import FILES, audit, build
from bidr.audit.sheet import COLS, SHEET_ROWS, SHEET_UNIT
from bidr.file import run as R
from bidr.file import select as S

YIL = 2025


def _m(olcut, yuva, asama, alinti="x" * 30, guven="yuksek"):
    od = {"planla": 2, "uygula": 3, "kontrol_et": 4, "onlem_al": 4, "ozgun": 5}[asama]
    return {"olcut": olcut, "yuva": yuva, "asama": asama, "od_onerisi": od, "alinti": alinti,
            "gerekce": "g", "guven": guven,
            "denetim": {"alinti_tutuyor": True, "alinti_skor": 1.0, "alinti_konum": None, "red": [], "isaret": []},
            "od_kabul": od, "kabul": True}


def _doc(tur, tarih=None, ici=None, **kw):
    d = {"doc_type": tur, "tarih": tarih, "donem": YIL, "akademik_donem": [], **kw}
    if ici is None and tarih:
        ici = int(tarih[:4]) == YIL
    d["donem_ici"] = ici
    return d


def _ws(tmp_path: Path, docs: dict, *, birim: dict | None = None, dosya: dict | None = None
        ) -> tuple[Path, Path]:
    """docs: {doc_id: (documents kaydı, eşleşmeler)}; birim: {doc_id: birim_iliskisi};
    dosya: {doc_id: kaynak dosya adı}."""
    ws, src = tmp_path / "ws", tmp_path / "kaynak"
    (ws / "text").mkdir(parents=True)
    src.mkdir()
    with open(ws / "inventory.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["doc_id", "sha256", "rel_path", "ext", "size", "pages", "chars", "method", "status",
                    "dup_of", "error"])
        for did in docs:
            name = (dosya or {}).get(did, f"{did}.docx")
            (src / name).write_bytes(b"PK sentetik " + did.encode())
            w.writerow([did, did * 4, name, ".docx", 1, 1, 10, "x", "ok", "", ""])
    with open(ws / "documents.jsonl", "w", encoding="utf-8") as f:
        for did, (d, _) in docs.items():
            f.write(json.dumps({"doc_id": did, "calisma_adi": did, "baslik": f"Belge {did}", **d},
                               ensure_ascii=False) + "\n")
    with open(ws / "decisions.jsonl", "w", encoding="utf-8") as f:
        for did, (_, ms) in docs.items():
            (ws / "text" / f"{did}.txt").write_text(f"Belge {did} metni.", encoding="utf-8")
            rel = (birim or {}).get(did)
            f.write(json.dumps({"doc_id": did, "durum": "ok", "asama": "ince", "karar": "olcut_var",
                                **({"ince": {"birim_iliskisi": rel}} if rel else {}),
                                "eslesmeler": ms}, ensure_ascii=False) + "\n")
    return ws, src


def _crit(a, cid):
    return next(c for c in a.criteria if c["olcut"] == cid)


def _secim(out: Path) -> dict:
    return json.loads((out / S.SECIM).read_text(encoding="utf-8"))


def _index_ids(out: Path) -> set[str]:
    with open(out / R.INDEX, encoding="utf-8", newline="") as f:
        return {r["doc_id"] for r in csv.DictReader(f)}


# -- 1a: dönem sonrası --------------------------------------------------------------------

def test_post_period_documents_are_not_evidence(tmp_path):
    ws, _ = _ws(tmp_path, {
        # yapı, dönemden sonra yürürlüğe girmiş: kanıt değil
        "yon_2026": (_doc("yonerge", "2026-02-01", tarih_kaynagi="bas_ilk", tarihler=["2026-02-01"]),
                     [_m("B.1.1", "B.1.1/1", "planla")]),
        # yapı, revizyon tarihi dönem sonrası: önceki sürüm dönemde yürürlükte olabilir → sayılır + uyarı
        "yon_rev": (_doc("yonerge", "2026-03-01", tarih_kaynagi="etiket:revizyon tarihi",
                         tarihler=["2026-03-01"]), [_m("A.4.2", "A.4.2/1", "planla")]),
        # "Komisyonlar 2026-2027": tarih yok, dönemsiz akademik yıl (identify karar veremedi)
        "komisyon": (_doc("gorev_dagilimi", akademik_donem=["2026-2027"]), [_m("B.1.2", "B.1.2/1", "planla")]),
        # duyuru: yayım 2025-12, etkinlik 2026-01 → olay tarihi en geç tarih, dönem sonrası
        "seminer": (_doc("etkinlik_duyurusu", "2025-12-20", tarih_kaynagi="bas_ilk",
                         tarihler=["2025-12-20", "2026-01-15"]), [_m("B.1.1", "B.1.1/4", "uygula")]),
    })
    a = build(ws)
    by = a.by_key
    r = by["yon_2026|B.1.1/1"]
    assert not r["sayilir"] and "donem_sonrasi" in r["flags"] and "dönem sonrası" in r["donem_kurali"]
    r = by["yon_rev|A.4.2/1"]
    assert r["sayilir"] and "revizyon_donem_sonrasi" in r["flags"]
    assert "dönemdeki sürüm aranmalı" in r["donem_kurali"]
    r = by["komisyon|B.1.2/1"]
    assert not r["sayilir"] and "donem_sonrasi" in r["flags"] and "akademik yıl (2026-2027)" in r["tarih_kaynagi"]
    r = by["seminer|B.1.1/4"]
    assert not r["sayilir"] and "donem_sonrasi" in r["flags"] and r["donem_yil"] == 2026
    assert "en geç tarih" in r["tarih_kaynagi"]
    assert {g["satir"] for g in _crit(a, "B.1.1")["donem_sonrasi"]} == {"yon_2026|B.1.1/1", "seminer|B.1.1/4"}
    assert _crit(a, "B.1.1")["od"] == 1
    out = tmp_path / "out"
    audit(ws, out=out)
    g = (out / FILES["gaps"]).read_text(encoding="utf-8")
    assert "## Dönem sonrası ve yürürlükte olmayan sürümler (kanıt sayılmadı)" in g and "`seminer`" in g
    assert "## Revizyon tarihi dönem sonrası olan düzenlemeler" in g and "`yon_rev`" in g


def test_post_period_rows_never_published(tmp_path):
    ws, src = _ws(tmp_path, {
        "k_ici": (_doc("bolum_kurulu_karari", "2025-04-01"), [_m("B.1.1", "B.1.1/4", "uygula")]),
        "k_2026": (_doc("bolum_kurulu_karari", "2026-01-10"), [_m("B.1.1", "B.1.1/5", "uygula")]),
    })
    out = tmp_path / "out"
    R.run(ws, out=out, source=src)
    assert _index_ids(out) == {"k_ici"}
    assert {e["doc_id"]: e["neden"] for e in _secim(out)["elenen"]} == {"k_2026": "donem_sonrasi"}


# -- 1b: eski olay belgesi ------------------------------------------------------------------

def test_old_events_are_continuity_only_and_capped_in_list(tmp_path):
    docs = {f"anket_{y}": (_doc("anket_sonucu", f"{y}-05-01"), [_m("B.1.1", "B.1.1/6", "kontrol_et")])
            for y in (2015, 2016, 2023)}
    docs["plan_2016"] = (_doc("bolum_kurulu_karari", "2016-01-01"), [_m("B.1.1", "B.1.1/1", "planla")])
    docs["k_ici"] = (_doc("bolum_kurulu_karari", "2025-04-01"), [_m("B.1.1", "B.1.1/4", "uygula")])
    ws, src = _ws(tmp_path, docs)
    a = build(ws)
    for d in ("anket_2015", "anket_2016", "anket_2023"):
        r = next(r for r in a.rows if r["doc_id"] == d)
        assert not r["sayilir"] and "gecmis_kanit" in r["flags"], d     # izleme halkası sayılmaz
    # dönemden önce alınmış, hâlâ yürürlükteki usul kararı plan halkasını kanıtlar (kullanıcı kararı)
    r = next(r for r in a.rows if r["doc_id"] == "plan_2016")
    assert r["sayilir"] and "guncellik_dogrulanmali" in r["flags"] and "gecmis_kanit" not in r["flags"]
    assert _crit(a, "B.1.1")["od"] == 3                                  # plan (eski karar) + U
    out = tmp_path / "out"
    R.run(ws, out=out, source=src)
    ids = _index_ids(out)
    assert {"k_ici", "plan_2016"} <= ids                                 # plan kanıtı geçmiş sınırına girmez
    assert len(ids & {"anket_2015", "anket_2016", "anket_2023"}) == 1    # en çok 1 geçmiş kanıt
    assert sum(e["neden"] == "gecmis_siniri" for e in _secim(out)["elenen"]) == 2
    (ws / "config.yaml").write_text("rapor:\n  kanit_secimi:\n    gecmis_kanit_en_fazla: 0\n", encoding="utf-8")
    R.run(ws, out=out, source=src)
    assert _index_ids(out) == {"k_ici", "plan_2016"}


def test_previous_year_plan_rule_is_configurable(tmp_path, monkeypatch):
    p = tmp_path / "profiller"
    p.mkdir()
    # varsayılan (true): eski usul kararının planı sayılır, uygulaması sayılmaz
    rule = D.load_rule()
    assert rule.onceki_olay_plani
    doc = _doc("bolum_kurulu_karari", "2022-01-01")
    r = D.apply_row(rule, doc, "bolum_kurulu_karari", "planla")
    assert r["sayilir"] and "guncellik_dogrulanmali" in r["flags"]
    r = D.apply_row(rule, doc, "bolum_kurulu_karari", "uygula")
    assert not r["sayilir"] and "gecmis_kanit" in r["flags"]
    # kurum false seçerse planla da sayılmaz
    txt = D.DEFAULT_PATH.read_text(encoding="utf-8").replace("onceki_olay_plani_sayilir: true",
                                                             "onceki_olay_plani_sayilir: false")
    (p / D.FILE).write_text(txt, encoding="utf-8")
    monkeypatch.setenv("BIDR_PROFILES_DIR", str(p))
    rule = D.load_rule()
    assert not rule.onceki_olay_plani
    r = D.apply_row(rule, doc, "bolum_kurulu_karari", "planla")
    assert not r["sayilir"] and "gecmis_kanit" in r["flags"]


# -- 1c: tarih kaynağı ve birden çok tarih --------------------------------------------------

def test_date_source_and_multiple_dates(tmp_path):
    ws, _ = _ws(tmp_path, {
        # etiketli tarih olayın tarihidir: sonraki tarih (ör. eylem son tarihi) referanstır
        "tut_etiket": (_doc("komisyon_tutanagi", "2025-11-10", tarih_kaynagi="etiket:toplanti tarihi",
                            tarihler=["2025-11-10", "2026-03-01"]), [_m("B.1.1", "B.1.1/4", "uygula")]),
        # etiketsiz birincil tarih + dönem sonrası tarih: olay tarihi belirsiz
        "tut_belirsiz": (_doc("komisyon_tutanagi", "2025-11-10", tarih_kaynagi="bas_ilk",
                              tarihler=["2025-11-10", "2026-03-01"]), [_m("B.1.1", "B.1.1/5", "uygula")]),
        # birincil tarih eski bir referans, belgede rapor yılı tarihi de var
        "tut_eski_ref": (_doc("komisyon_tutanagi", "2019-02-01", tarih_kaynagi="bas_ilk",
                              tarihler=["2019-02-01", "2025-06-01"]), [_m("A.4.2", "A.4.2/2", "uygula")]),
        # rapor yılı tarihi + eski referans tarihi: referans öncedir, olay rapor yılında
        "tut_ref_once": (_doc("komisyon_tutanagi", "2025-06-01", tarih_kaynagi="bas_en_sik",
                              tarihler=["2014-01-01", "2025-06-01"]), [_m("A.4.2", "A.4.2/3", "onlem_al")]),
        # metinde tarih yok, dosya adında: dışlamada güvenilir, saymada değil
        "anket_ad25": (_doc("anket_sonucu"), [_m("A.4.2", "A.4.2/5", "kontrol_et")]),
        "anket_ad26": (_doc("anket_sonucu"), [_m("A.4.2", "A.4.2/4", "kontrol_et")]),
    }, dosya={"anket_ad25": "Anket_Sonuclari_2025.pdf", "anket_ad26": "anket-2026.pdf"})
    a = build(ws)
    by = a.by_key
    r = by["tut_etiket|B.1.1/4"]
    assert r["sayilir"] and r["tarih_kaynagi"] == "metin (etiket: toplanti tarihi)"
    r = by["tut_belirsiz|B.1.1/5"]
    assert not r["sayilir"] and "tarih_dogrulanmali" in r["flags"] and "2026" in r["tarih_notu"]
    assert r["tarih_bilgisi"].startswith("2025-11-10 · metin (baş bölgedeki ilk tarih)")
    r = by["tut_eski_ref|A.4.2/2"]
    assert not r["sayilir"] and "tarih_dogrulanmali" in r["flags"]
    assert by["tut_ref_once|A.4.2/3"]["sayilir"]
    r = by["anket_ad25|A.4.2/5"]
    assert not r["sayilir"] and "tarih_dogrulanmali" in r["flags"] and "dosya adı" in r["tarih_kaynagi"]
    r = by["anket_ad26|A.4.2/4"]
    assert not r["sayilir"] and "donem_sonrasi" in r["flags"] and r["tarih_kaynagi"] == "dosya adı (anket-2026.pdf)"
    out = tmp_path / "out"
    audit(ws, out=out)
    wb = load_workbook(out / FILES["xlsx"])
    sh = wb[SHEET_ROWS]
    head = [c.value for c in sh[1]]
    col = head.index(dict((k, h) for k, h, _, _ in COLS)["tarih_bilgisi"]) + 1
    cells = {sh.cell(row=i, column=1).value: sh.cell(row=i, column=col).value for i in range(2, sh.max_row + 1)}
    assert "etiket: toplanti tarihi" in cells["tut_etiket|B.1.1/4"]
    g = (out / FILES["gaps"]).read_text(encoding="utf-8")
    assert "`tut_belirsiz`: B.1.1/5 U — birincil tarih rapor yılında" in g


# -- ÇAP yönergesi sürümleri ---------------------------------------------------------------

def test_regulation_versions_in_force_selected(tmp_path):
    g = {"surum_grubu": "cap"}
    ws, _ = _ws(tmp_path, {
        f"cap_{y}": (_doc("yonerge", f"{y}-06-01", **g), [_m("B.1.1", "B.1.1/1", "planla")])
        for y in (2014, 2017, 2018, 2026)})
    a = build(ws)
    st = {r["doc_id"]: (r["sayilir"], r["flags"]) for r in a.rows}
    assert st["cap_2018"][0] and "guncellik_dogrulanmali" in st["cap_2018"][1]
    for y in (2014, 2017):
        assert not st[f"cap_{y}"][0] and "surum_yururlukten_kalkmis" in st[f"cap_{y}"][1]
    assert not st["cap_2026"][0] and "surum_donem_sonrasi" in st["cap_2026"][1]


def test_regulation_versions_same_year_and_undated(tmp_path):
    g = {"surum_grubu": "cap"}
    ws, _ = _ws(tmp_path, {
        "v_2024": (_doc("yonerge", "2024-06-01", **g), [_m("B.1.1", "B.1.1/1", "planla")]),
        "v_2025": (_doc("yonerge", "2025-03-01", **g), [_m("B.1.1", "B.1.1/1", "planla")]),
        "v_tarihsiz": (_doc("yonerge", **g), [_m("B.1.1", "B.1.1/1", "planla")]),
    })
    a = build(ws)
    st = {r["doc_id"]: (r["sayilir"], r["flags"]) for r in a.rows}
    # rapor yılında yenilenen sürümün öncülü dönemin bir kısmında yürürlükteydi
    assert st["v_2024"][0] and st["v_2025"][0]
    assert all("surum_dogrulanmali" in st[d][1] for d in st)
    assert not st["v_tarihsiz"][0]
    audit(ws, out=tmp_path / "out")
    assert "## Sürümü doğrulanacak düzenlemeler" in (tmp_path / "out" / FILES["gaps"]).read_text(encoding="utf-8")


def test_version_status_needs_structure_class():
    rule = D.load_rule()
    docs = {"a": _doc("anket_sonucu", "2018-01-01", surum_grubu="g"),
            "b": _doc("anket_sonucu", "2024-01-01", surum_grubu="g")}
    assert D.version_status(docs, rule) == {}


# -- 2: birim aitliği -----------------------------------------------------------------------

def test_unconfirmed_unit_not_counted_nor_published(tmp_path):
    ws, src = _ws(tmp_path, {
        "kendi": (_doc("bolum_kurulu_karari", "2025-04-01"), [_m("A.4.2", "A.4.2/2", "uygula")]),
        "kimya_anket": (_doc("anket_sonucu", "2025-05-01"), [_m("A.4.2", "A.4.2/5", "kontrol_et")]),
        "kimya_tut": (_doc("komisyon_tutanagi", "2025-06-01"), [_m("A.4.2", "A.4.2/3", "onlem_al")]),
    }, birim={"kendi": "kendi", "kimya_anket": "belirsiz", "kimya_tut": "belirsiz"})
    out = tmp_path / "out"
    a, paths = audit(ws, out=out)
    r = a.by_key["kimya_anket|A.4.2/5"]
    assert not r["sayilir"] and r["birim_onay_bekliyor"] and "birim_onay_bekliyor" in r["flags"]
    assert _crit(a, "A.4.2")["od"] == 3                          # K/Ö sayılmadı
    # review.xlsx: onay bekleyenler önde; birim sayfasında belirsiz belgeler de var
    wb = load_workbook(paths["xlsx"])
    first = {wb[SHEET_ROWS].cell(row=i, column=1).value for i in (2, 3)}
    assert first == {"kimya_anket|A.4.2/5", "kimya_tut|A.4.2/3"}
    units = {row[0].value: row for row in wb[SHEET_UNIT].iter_rows(min_row=3)}
    assert {"kimya_anket", "kimya_tut"} <= set(units)
    g = paths["gaps"].read_text(encoding="utf-8")
    assert "`kimya_anket` (1 eşleşme; onay bekliyor: sayılmadı)" in g
    # inceleme yapılmadan "devam et": file da yayımlamaz
    R.run(ws, out=out, source=src, review_dir=out)
    assert _index_ids(out) == {"kendi"}
    assert {e["doc_id"]: e["neden"] for e in _secim(out)["elenen"]} == {
        "kimya_anket": "birim_dogrulanmali", "kimya_tut": "birim_dogrulanmali"}


def test_unit_confirmed_by_row_decision_or_unit_pin(tmp_path):
    ws, _ = _ws(tmp_path, {
        "b1": (_doc("anket_sonucu", "2025-05-01"), [_m("A.4.2", "A.4.2/5", "kontrol_et")]),
        "b2": (_doc("komisyon_tutanagi", "2025-06-01"), [_m("A.4.2", "A.4.2/3", "onlem_al")]),
    }, birim={"b1": "belirsiz", "b2": "belirsiz"})
    dec = {"satir": "b1|A.4.2/5", "doc_id": "b1", "olcut": "A.4.2", "yuva": "A.4.2/5", "karar": "kabul",
           "duzelt": None, "etiket": None, "not": ""}
    pins = {"b2": {"doc_id": "b2", "birim_iliskisi": "kendi", "kaynak": "insan"}}
    a = build(ws, review={dec["satir"]: dec}, pins=pins)
    r1, r2 = a.by_key["b1|A.4.2/5"], a.by_key["b2|A.4.2/3"]
    assert r1["sayilir"] and "birim_aitligi_onaylandi" in r1["flags"] and not r1["birim_onay_bekliyor"]
    assert r2["sayilir"] and r2["birim_iliskisi"] == "kendi" and "birim_aitligi_dogrulanmali" not in r2["flags"]


# -- 3: eksik kanıt notu --------------------------------------------------------------------

def test_missing_evidence_note_for_nearly_empty_criteria(tmp_path):
    from bidr.render.run import eksik_text
    ws, _ = _ws(tmp_path, {
        "yonetmelik": (_doc("yonetmelik", "2025-01-01"), [_m("B.1.1", "B.1.1/1", "planla")]),
        "eski": (_doc("anket_sonucu", "2020-01-01"), [_m("A.4.2", "A.4.2/5", "kontrol_et")]),
        "tam": (_doc("bolum_kurulu_karari", "2025-04-01"), [_m("B.1.2", "B.1.2/1", "planla")]),
    })
    out = tmp_path / "out"
    a, paths = audit(ws, out=out)
    b11 = _crit(a, "B.1.1")["eksik_kanit_notu"]
    assert b11["durum"] == "neredeyse_kanitsiz" and b11["nedenler"] == ["yalniz_kurum_geneli"]
    assert b11["metin"].startswith("Eksik kanıt notu: bölümün bu döneme ait doğrudan kanıtı yok")
    a42 = _crit(a, "A.4.2")["eksik_kanit_notu"]
    assert a42["durum"] == "neredeyse_kanitsiz" and a42["nedenler"] == ["yalniz_donem_disi"]
    assert _crit(a, "B.1.2")["eksik_kanit_notu"] is None
    bos = next(c for c in a.criteria if not c["eslesme"] and not c["gecmis_kanit"] and not c["donem_sonrasi"]
               and c["olcut"] not in ("B.1.1", "A.4.2"))
    assert bos["eksik_kanit_notu"]["durum"] == "kanitsiz"
    assert bos["eksik_kanit_notu"]["metin"] == eksik_text(bos)        # render'ın bugünkü notuyla aynı
    js = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert next(c for c in js["olcutler"] if c["olcut"] == "B.1.1")["eksik_kanit_notu"]["durum"] == "neredeyse_kanitsiz"
    g = paths["gaps"].read_text(encoding="utf-8")
    assert "## Neredeyse kanıtsız ölçütler (eksik kanıt notu)" in g and "- B.1.1 " in g


# -- kanıt seçimi: atıf almayan kanıtlar ----------------------------------------------------

def test_gaps_lists_published_but_uncited(tmp_path):
    ws, src = _ws(tmp_path, {
        f"k{i}": (_doc("bolum_kurulu_karari", f"2025-04-0{i + 1}"), [_m("B.1.1", "B.1.1/4", "uygula")])
        for i in range(3)})
    out = tmp_path / "out"
    R.run(ws, out=out, source=src)
    g = (out / "gaps.md").read_text(encoding="utf-8")
    assert "Listede olup metinde atıf almayan" not in g               # metin yazılmadan liste yok
    with open(out / R.INDEX, encoding="utf-8", newline="") as f:
        idx = {r["doc_id"]: r for r in csv.DictReader(f)}
    k0 = idx["k0"]
    (ws / "texts").mkdir()
    (ws / "texts" / "B.1.1.json").write_text(json.dumps({
        "olcut": "B.1.1", "paragraflar": [{"metin": f"Uygulanır [{k0['kanit_no']}].", "atiflar": [k0["kanit_no"]]}],
        "kanitlar": [{"no": k0["kanit_no"], "ad": k0["ad"], "dosya": k0["dosya"]}]}), encoding="utf-8")
    R.run(ws, out=out, source=src)
    g = (out / "gaps.md").read_text(encoding="utf-8")
    sec = g[g.index("### Listede olup metinde atıf almayan kanıtlar"):]
    line = next(x for x in sec.splitlines() if x.startswith("- B.1.1:"))
    assert "`k1`" in line and "`k2`" in line and "`k0`" not in line
