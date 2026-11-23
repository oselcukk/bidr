"""bidr ihtiyac: referans set, karşılık eşleştirme, öncelik, çıktılar ve iç taslak (sentetik veri)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from openpyxl import load_workbook

from bidr.cli import main
from bidr.ihtiyac import rapor as R
from bidr.ihtiyac.eslestir import ESKI, VAR, YOK
from bidr.ihtiyac.referans import build_reference, from_csv, load_reference, write_reference
from bidr.ihtiyac.tablolar import Sorumlular, Turler

HECE = ["lar", "ler", "dan", "den", "nin", "nun", "ile", "ise", "dir", "tir", "mak", "mek"]


def _metin(baslik: str, *konu: str, n: int = 30) -> str:
    """Sentetik belge metni: başlık + konuya özgü uydurma sözcüklerden satırlar."""
    out = [baslik]
    for i in range(n):
        out.append(" ".join(f"{k}{HECE[(i + j) % len(HECE)]}" for j, k in enumerate(konu)) + " sentetik metin satiri")
    return "\n".join(out)


ANKET = _metin("DERS DEGERLENDIRME ANKETI SONUCLARI", "zorvak", "pelim", "tuskar", "melvo", "darnik")
ANKET_ESKI = _metin("DERS DEGERLENDIRME ANKETI SONUCLARI", "zorvak", "pelim", "tuskar", "melvo", "ferlin")
YONERGE = _metin("SENTETIK DANISMANLIK YONERGESI", "kalvor", "nespir", "lodrak", "vimel", "toskan")
SEMINER = _metin("BOLUM SEMINER PROGRAMI", "brenta", "sikor", "palvu", "derom", "hiskel")
PLAN = _metin("BOLUM KURULU KARARI", "gonsur", "lepra", "vaskit", "mordel", "tunik")


def _m(olcut, yuva, asama, od, guven="orta"):
    return {"olcut": olcut, "yuva": yuva, "asama": asama, "od_onerisi": od, "alinti": "x" * 30, "gerekce": "g",
            "guven": guven, "denetim": {"red": [], "isaret": []}, "od_kabul": od, "kabul": True}


def _ws(root: Path, donem: int, docs: dict) -> Path:
    """docs: doc_id → (tür, dönem içi, tarih, ad, metin, eşleşmeler, inceleme kararı|None)."""
    root.mkdir(parents=True)
    (root / "text").mkdir()
    with open(root / "decisions.jsonl", "w", encoding="utf-8") as fd, \
            open(root / "documents.jsonl", "w", encoding="utf-8") as fo, \
            open(root / "review-decisions.jsonl", "w", encoding="utf-8") as fr:
        for did, (t, ici, tarih, ad, metin, ms, karar) in docs.items():
            (root / "text" / f"{did}.txt").write_text(metin, encoding="utf-8")
            fo.write(json.dumps({"doc_id": did, "doc_type": t, "donem_ici": ici, "donem": donem, "tarih": tarih,
                                 "calisma_adi": ad, "baslik": ad}, ensure_ascii=False) + "\n")
            if ms:
                fd.write(json.dumps({"doc_id": did, "durum": "ok", "asama": "ince", "karar": "olcut_var",
                                     "ince": {"karar": "olcut_var", "kanit_adi": {"ad": ad, "durum": "kabul"}},
                                     "eslesmeler": ms}, ensure_ascii=False) + "\n")
                for m in ms:
                    if karar:
                        fr.write(json.dumps({"satir": f"{did}|{m['yuva']}", "doc_id": did, "olcut": m["olcut"],
                                             "yuva": m["yuva"], "karar": karar}, ensure_ascii=False) + "\n")
    return root


@pytest.fixture
def ref_ws(tmp_path):
    return _ws(tmp_path / "onceki", 2024, {
        "r_anket": ("anket_sonucu", True, "2024-06-01", "Ders Degerlendirme Anketi Sonuclari 2024", ANKET,
                    [_m("B.1.1", "B.1.1/6", "kontrol_et", 4)], "kabul"),
        "r_yon": ("yonerge", None, "2020-01-01", "Sentetik Danismanlik Yonergesi", YONERGE,
                  [_m("B.2.3", "B.2.3/1", "planla", 2)], "kabul"),
        "r_sem": ("etkinlik_duyurusu", True, "2024-03-01", "Bolum Seminer Programi 2024", SEMINER,
                  [_m("A.1.1", "A.1.1/2", "uygula", 3)], "kabul"),
        "r_dusuk": ("toplanti_tutanagi", True, "2024-05-01", "Dusuk Guvenli Tutanak", PLAN,
                    [_m("B.1.1", "B.1.1/3", "uygula", 3, guven="dusuk")], "kabul"),
        "r_ret": ("bolum_kurulu_karari", True, "2024-05-02", "Reddedilen Karar", PLAN,
                  [_m("B.1.2", "B.1.2/1", "planla", 2)], "ret"),
        "r_karsiz": ("bolum_kurulu_karari", True, "2024-05-03", "Karari Verilmemis Karar", PLAN,
                     [_m("B.1.3", "B.1.3/1", "planla", 2)], None),
    })


@pytest.fixture
def tgt_ws(tmp_path):
    return _ws(tmp_path / "guncel", 2025, {
        "t_yon": ("yonerge", None, "2020-01-01", "Danismanlik Yonergesi", YONERGE,
                  [_m("B.2.3", "B.2.3/1", "planla", 2)], "kabul"),
        "t_anket": ("anket_sonucu", False, "2024-06-01", "Ders Degerlendirme Anketi 2024", ANKET_ESKI, [], None),
        "t_plan": ("bolum_kurulu_karari", True, "2025-02-01", "Bolum Kurulu Karari 2025", PLAN,
                   [_m("B.1.1", "B.1.1/1", "planla", 2)], "kabul"),
    })


def _snapshot(ws: Path) -> dict:
    return {p.relative_to(ws): p.read_bytes() for p in ws.rglob("*") if p.is_file()}


# -- referans -----------------------------------------------------------------------------------

def test_reference_selects_only_good_evidence(ref_ws):
    before = _snapshot(ref_ws)
    ref = build_reference(ref_ws)
    assert _snapshot(ref_ws) == before                          # salt okunur
    by = {it["doc_id"]: it for it in ref["ogeler"]}
    assert set(by) == {"r_anket", "r_yon", "r_sem"}             # düşük güven, ret, kararsız dışarıda
    a = by["r_anket"]
    assert a["tekrarlayan"] == "ders_degerlendirme" and a["asama"] == "kontrol_et" and a["olcut"] == "B.1.1"
    assert by["r_yon"]["tekrarlayan"] == ""                     # yönerge tekrarlamaz
    assert by["r_sem"]["tekrarlayan"] == "seminer_programi"
    assert "zorvak" in " ".join(a["anahtar"])
    assert ref["belgeler"]["r_yon"]["parmak_izi"]               # karma sayılar, metin değil
    assert "kalvor" not in json.dumps(ref["belgeler"])


def test_reference_csv(tmp_path):
    p = tmp_path / "ek.csv"
    p.write_text("olcut,belge_turu,ad,yuva\nC.1.1,anket_sonucu,Mezun Anketi Sonuclari,\n,yonerge,Bos olcut,\n",
                 encoding="utf-8")
    items, uy = from_csv(p, Turler())
    assert len(items) == 1 and items[0]["kaynak"] == "elle" and items[0]["tekrarlayan"] == "memnuniyet_anketi"
    assert "mezun" in items[0]["anahtar"] and uy
    bad = tmp_path / "kotu.csv"
    bad.write_text("olcut,ad\nC.1.1,x\n", encoding="utf-8")
    with pytest.raises(ValueError):
        from_csv(bad, Turler())
    ref = build_reference(None, ek=p)
    assert [it["id"] for it in ref["ogeler"]] == ["R001"]


# -- eşleştirme + rapor --------------------------------------------------------------------------

def _run(ref_ws, tgt_ws, tmp_path, **kw):
    p = write_reference(build_reference(ref_ws), tmp_path / "referans.json")
    return R.run(tgt_ws, referans=load_reference(p), out=tmp_path / "out", **kw)


def test_counterpart_status(ref_ws, tgt_ws, tmp_path):
    before = _snapshot(tgt_ws)
    res = _run(ref_ws, tgt_ws, tmp_path)
    assert _snapshot(tgt_ws) == before                          # hedef çalışma alanına yazılmaz
    g = {x["doc_id"]: x for x in res["gecen"]}
    # yapı belgesi: içerik kopyası, tarihi dönemle bağlanamadı → var + doğrulanmalı
    assert g["r_yon"]["durum"] == VAR and g["r_yon"]["karsilik_doc_id"] == "t_yon"
    assert g["r_yon"]["kopya"] and g["r_yon"]["donem_dogrulanmali"]
    assert g["r_yon"]["olcute_eslesmis"].startswith("evet")
    # tekrarlayan tür: yalnız önceki yılın anketi var → eski sürüm
    assert g["r_anket"]["durum"] == ESKI and g["r_anket"]["karsilik_doc_id"] == "t_anket"
    assert "önceki" in g["r_anket"]["gerekce"]
    # seminer programının karşılığı yok → istenmeli
    assert g["r_sem"]["durum"] == YOK and "bulunamadı" in g["r_sem"]["gerekce"]


def test_priorities_and_outputs(ref_ws, tgt_ws, tmp_path):
    res = _run(ref_ws, tgt_ws, tmp_path)
    t = res["talepler"]
    assert [x["puan"] for x in t] == sorted((x["puan"] for x in t), reverse=True)
    s = {x["olcut"]: x for x in res["satirlar"]}
    # B.1.1: plan var (OD2) → tek uygulama belgesi OD3; geçen yılın anketi eski sürüm → istenmeli
    b11 = [x for x in t if x["olcut"] == "B.1.1"]
    assert b11[0]["oncelik"] == "tek belgeyle OD artışı" and b11[0]["halka"] == "uygula" and b11[0]["hedef_od"] == 3
    assert any(x["puan"] == R.P_REF_ESKI and "anket" in x["istenecek"].lower() for x in b11)
    assert s["B.1.1"]["od"] == 2 and s["B.1.1"]["kanit_sayisi"] == 1 and "uygulama" in s["B.1.1"]["eksik_halkalar"]
    assert any("B.1.1/" in g for g in s["B.1.1"]["gereken"])       # kılavuz yuva metinleri
    # A.1.1: hiç kanıt yok → kanıtsız ölçüt (100) önce; geçen yılın semineri istenir
    a11 = [x for x in t if x["olcut"] == "A.1.1"]
    assert a11[0]["puan"] == R.P_KANITSIZ and any(x["puan"] == R.P_REF for x in a11)
    assert t[0]["puan"] == R.P_KANITSIZ
    # kimden istenir: belge türü tablosundan
    sem = next(x for x in a11 if x["puan"] == R.P_REF)
    assert sem["kimden"] == Sorumlular().belge_turu["etkinlik_duyurusu"]
    # çıktılar
    wb = load_workbook(res["paths"]["xlsx"])
    assert wb.sheetnames[:3] == ["Öncelikli talepler", "Ölçüt özeti", "Geçen yıl karşılıkları"]
    assert wb["Öncelikli talepler"]["A1"].value == "Sıra"
    md = res["paths"]["md"].read_text(encoding="utf-8")
    assert "Kanıt ihtiyaç raporu" in md and "yok (istenmeli) 1" in md


def test_out_of_scope_criteria_not_listed(ref_ws, tgt_ws, tmp_path):
    (tgt_ws / "config.yaml").write_text("rapor:\n  kapsam:\n    A.1.1: baska_birim\n", encoding="utf-8")
    res = _run(ref_ws, tgt_ws, tmp_path)
    assert "A.1.1" not in {x["olcut"] for x in res["satirlar"]}
    assert "A.1.1" not in {x["olcut"] for x in res["talepler"]}
    assert "r_sem" not in {x["doc_id"] for x in res["gecen"]}


def test_without_reference(tgt_ws, tmp_path):
    res = R.run(tgt_ws, out=tmp_path / "o")
    assert res["gecen"] == [] and res["talepler"]
    assert "Referans set verilmedi" in res["paths"]["md"].read_text(encoding="utf-8")


def test_responsible_lookup_order():
    s = Sorumlular()
    assert s.kim("anket_sonucu", "planla", "A.1.1") == s.belge_turu["anket_sonucu"]
    assert s.kim("", "planla", "A.1.1") == s.asama["planla"]
    assert s.kim("", "", "C.1.1") == s.alan["C"]
    assert s.kim() == s.varsayilan


# -- iç taslak + CLI -----------------------------------------------------------------------------

def test_internal_draft_never_touches_report(ref_ws, tgt_ws, tmp_path):
    import docx
    from test_render import make_template

    from bidr.ihtiyac.taslak import write_draft
    src = make_template(tgt_ws / "report.docx", ids=(("A.1.1", "Yönetişim"), ("B.1.1", "Program tasarımı")))
    orig = src.read_bytes()
    res = _run(ref_ws, tgt_ws, tmp_path)
    dst, n, _ = write_draft(src, tmp_path / "out", res["satirlar"], res["talepler"])
    assert src.read_bytes() == orig and dst.name == "report-ic.docx" and n == 2
    text = "\n".join(p.text for t in docx.Document(str(dst)).tables for r in t.rows for c in r.cells
                     for p in c.paragraphs)
    assert "[EKSİK:" in text
    with pytest.raises(ValueError):                          # kaynağın üstüne yazmaz
        write_draft(dst, dst.parent, [], [])


def test_cli(ref_ws, tgt_ws, tmp_path, capsys):
    rp = tmp_path / "ref.json"
    assert main(["ihtiyac", "referans", "-w", str(ref_ws), "--out", str(rp)]) == 0
    assert "3 iyi kanıt" in capsys.readouterr().out
    out = tmp_path / "cikti"
    before = _snapshot(tgt_ws)
    assert main(["ihtiyac", "-w", str(tgt_ws), "--referans", str(rp), "--out", str(out)]) == 0
    assert (out / "ihtiyac.xlsx").exists() and (out / "ihtiyac.md").exists()
    assert _snapshot(tgt_ws) == before
    assert main(["ihtiyac", "referans", "--out", str(rp)]) == 2      # -w ya da --ek gerekli


# -- kılavuz önerileri (Örnek Kanıtlar yuvaları, rubrik, açıklama) --------------------------------

def _yuva_sayaci(talepler: list[dict], cid: str) -> dict[str, int]:
    import re
    n: dict[str, int] = {}
    for t in talepler:
        if t["olcut"] == cid:
            for y in set(re.findall(r"[A-E]\.\d+\.\d+/\d+", t["yuvalar"])):
                n[y] = n.get(y, 0) + 1
    return n


def test_guide_suggestions_without_reference(tgt_ws, tmp_path):
    from bidr.criteria.loader import load_criteria
    cs = load_criteria()
    res = R.run(tgt_ws, out=tmp_path / "o")
    t = res["talepler"]
    assert R.P_REF_ESKI > R.P_KLV_HALKA > R.P_KLV_UST > R.P_KLV_MEVCUT > R.P_DIGER
    klv = [x for x in t if x["kaynak"] == R.K_KLV]
    assert klv and all(R.P_KLV_MEVCUT <= x["puan"] <= R.P_KLV_HALKA for x in klv)
    assert all(x["oncelik"] == "kılavuz önerisi" for x in klv)
    assert {k for x in t for k in x["kaynak"].split(" + ")} <= set(R.KAYNAKLAR)
    # B.1.1/1 kabul edilmiş planlama kanıtıyla karşılandı: kılavuz önerisi olarak istenmez
    b11 = [x for x in klv if x["olcut"] == "B.1.1"]
    assert "B.1.1/1" not in {x["yuvalar"] for x in b11}
    # her karşılanmamış yuva tek satırda (birleşen satırlar dahil); dipnotlar hariç
    yuvalar = {s.id for s in cs.get("B.1.1").slots if not s.footnote}
    n = _yuva_sayaci(t, "B.1.1")
    assert set(n) >= yuvalar - {"B.1.1/1"}
    assert all(v == 1 for k, v in n.items() if k != "B.1.1/1")
    s = {x["olcut"]: x for x in res["satirlar"]}
    assert "B.1.1/1" not in s["B.1.1"]["karsilanmamis_yuvalar"] and s["B.1.1"]["sonraki_od_tanimi"]
    # halka ve kimden dolu; tek tek yuva satırının yuva metni şablondan birebir
    for x in b11:
        assert x["halka_ad"] and x["kimden"]
        assert x["istenecek"] == cs.get_slot(x["yuvalar"]).text
    # referans yok ama kanıtsız ölçütte de öneri var
    assert any(x["olcut"] == "A.1.1" for x in t)


def test_guide_merges_with_missing_link_and_reference(ref_ws, tgt_ws, tmp_path):
    res = _run(ref_ws, tgt_ws, tmp_path)
    t = res["talepler"]
    a11 = [x for x in t if x["olcut"] == "A.1.1"]
    kanitsiz = next(x for x in a11 if x["puan"] == R.P_KANITSIZ)
    assert kanitsiz["kaynak"] == f"{R.K_KANITSIZ} + {R.K_KLV}"
    # kanıtsız talebin yuvaları ayrıca kılavuz satırı olarak tekrarlanmaz
    assert not (R._yuva_idleri(kanitsiz["yuvalar"])
                & {x["yuvalar"] for x in a11 if x["kaynak"] == R.K_KLV})
    sem = next(x for x in a11 if x["puan"] == R.P_REF)
    assert sem["kaynak"].startswith(R.K_REF) and R.K_KLV in sem["kaynak"]
    assert all(v == 1 for v in _yuva_sayaci([x for x in a11 if x is not kanitsiz], "A.1.1").values())
    # sonraki OD'nin kılavuz tanımı gerekçede (birebir kılavuz metninden)
    from bidr.criteria.loader import load_criteria
    rub = load_criteria().get("A.1.1").rubric[kanitsiz["hedef_od"]]
    assert f"OD{kanitsiz['hedef_od']} tanımı (kılavuz): «" in kanitsiz["gerekce"]
    assert R.kisalt(rub) in kanitsiz["gerekce"]
    # çıktılarda kaynak görünür
    wb = load_workbook(res["paths"]["xlsx"])
    head = [c.value for c in wb["Öncelikli talepler"][1]]
    assert "Kaynak" in head and "PUKÖ halkası" in head
    vals = {r[head.index("Kaynak")] for r in wb["Öncelikli talepler"].iter_rows(min_row=2, values_only=True)}
    assert R.K_KLV in vals
    md = res["paths"]["md"].read_text(encoding="utf-8")
    assert "Kılavuz önerileri" in md and "Kaynağa göre" in md and "kaynak: kanıtsız + kılavuz" in md


def test_guide_coverage_uses_acceptance(tmp_path):
    """Düşük güvenli, incelenmemiş eşleşme yuvayı karşılamaz; incelemede kabul edilen karşılar."""
    assert R.karsilar({"sayilir": True, "guven": "orta", "karar": None})
    assert R.karsilar({"sayilir": True, "guven": "dusuk", "karar": "kabul"})
    assert not R.karsilar({"sayilir": True, "guven": "dusuk", "karar": None})
    assert not R.karsilar({"sayilir": True, "guven": "yuksek", "karar": "ret"})
    assert not R.karsilar({"sayilir": False, "guven": "yuksek", "karar": "kabul"})
    ws = _ws(tmp_path / "w", 2025, {
        "a": ("bolum_kurulu_karari", True, "2025-02-01", "Bolum Kurulu Karari 2025", PLAN,
              [_m("B.1.1", "B.1.1/1", "planla", 2)], "kabul"),
        "b": ("toplanti_tutanagi", True, "2025-03-01", "Dusuk Guvenli Tutanak", SEMINER,
              [_m("B.1.1", "B.1.1/3", "uygula", 3, guven="dusuk")], None),
    })
    res = R.run(ws, out=tmp_path / "o")
    s = {x["olcut"]: x for x in res["satirlar"]}["B.1.1"]
    assert "B.1.1/3" in s["karsilanmamis_yuvalar"] and "B.1.1/1" not in s["karsilanmamis_yuvalar"]


def test_description_sentence_is_guide_text():
    from bidr.criteria.loader import load_criteria
    cs = load_criteria()
    c = cs.get("A.1.2")
    ac = R.aciklama_cumlesi(cs, "A.1.2", c.example_evidence[1])
    assert ac and ac.rstrip("…")[:60] in " ".join(c.description)
    assert R.aciklama_cumlesi(cs, "A.1.2", "zorvak pelim") == ""
    assert R.rubrik(cs, "A.1.2", 4) == R.kisalt(c.rubric[4]) and R.rubrik(cs, "A.1.2", None) == ""


# -- sade "İstenen kanıtlar" listesi -------------------------------------------------------------

from bidr.ihtiyac import sade as S  # noqa: E402

TEKNIK = ("puan", "kaynak", "yuva", "halka", "OD", "planla", "uygula", "kontrol_et", "onlem_al", "ozgun")


def test_sade_one_row_per_criterion_plain_language(ref_ws, tgt_ws, tmp_path):
    res = _run(ref_ws, tgt_ws, tmp_path)
    rows = res["sade"]
    assert res["paths"]["sade"].name == S.FILE and res["paths"]["sade"].exists()
    cids = [r["olcut"] for r in rows]
    assert len(cids) == len(set(cids)) == len({t["olcut"] for t in res["talepler"]})   # ölçüt başına bir satır
    assert len(rows) < len(res["talepler"])
    # sıralama: öncelik, kanıtsız en üstte
    assert [S.SIRA[r["oncelik"]] for r in rows] == sorted(S.SIRA[r["oncelik"]] for r in rows)
    s = {x["olcut"]: x for x in res["satirlar"]}
    assert s[rows[0]["olcut"]]["kanit_sayisi"] == 0 and rows[0]["oncelik"] == S.YUKSEK
    r = {x["olcut"]: x for x in rows}
    # A.1.1 kanıtsız: düz Türkçe gerekçe, somut belge listesi, geçen yılın seminer programı (yıl ilerletildi)
    a11 = r["A.1.1"]
    assert "hiç belge yok" in a11["neden"] and "olgunluk düzeyini 1'den" in a11["neden"]
    assert all(m.startswith("• ") for m in a11["belgeler"].split("\n"))
    assert "Bolum Seminer Programi 2025 (geçen yılki raporda: «Bolum Seminer Programi 2024»)" in a11["belgeler"]
    assert "organizasyon şeması" in a11["belgeler"]                      # ihtiyac_somut.yaml A.1.1/1
    assert a11["kilavuz"].startswith("Kılavuzun bu madde için örnek verdiği")
    assert "Yönetişim modeli ve organizasyon şeması" in a11["kilavuz"]   # kılavuz metni, kod değil
    for x in rows:
        metin = " ".join([x["belgeler"], x["neden"], x["kilavuz"], x["kimden"]])
        assert not re.search(r"\b[A-E]\.\d+\.\d+/\d+\b", metin)          # yuva kimliği yok
        assert not any(re.search(rf"\b{re.escape(k)}\b", x["neden"]) for k in TEKNIK)
        assert len(x["maddeler"]) <= S.KILAVUZ_EN_COK + 10
    # B.1.1: tek belgeyle olgunluk düzeyi artar → Yüksek; elde olan belge notta
    assert r["B.1.1"]["oncelik"] == S.YUKSEK and "2'den 3'e" in r["B.1.1"]["neden"]
    assert "Bolum Kurulu Karari 2025" in r["B.1.1"]["not"]
    # karşılanmış kılavuz maddesi istenmez
    assert "Program tasarımı ve onayı için kullanılan tanımlı süreçler" not in r["B.1.1"]["kilavuz"]


def test_sade_xlsx_layout(ref_ws, tgt_ws, tmp_path):
    res = _run(ref_ws, tgt_ws, tmp_path)
    wb = load_workbook(res["paths"]["sade"])
    assert wb.sheetnames == list(S.SHEETS)
    sh = wb[S.SHEETS[0]]
    head = [c.value for c in sh[1]]
    assert head == [h for _, h, _ in S.COLS]
    for bad in ("Puan", "Kaynak", "Belge türü", "Kılavuz yuvaları", "Ölçüt açıklamasından (kılavuz)"):
        assert bad not in head
    assert sh.freeze_panes == "A2" and sh.page_setup.orientation == "landscape"
    assert sh.print_title_rows.replace("$", "") == "1:1"
    assert sh.cell(row=2, column=head.index("İstenen belgeler") + 1).alignment.wrap_text
    assert sh.max_row == len(res["sade"]) + 1
    k = wb[S.SHEETS[1]]
    assert [c.value for c in k[1]][:2] == ["Kimden", "Madde"] and k.max_row > 1
    assert 3 <= wb[S.SHEETS[2]].max_row <= 8


def test_sade_manual_requests(tgt_ws, tmp_path):
    md = tmp_path / "istenecekler.md"
    md.write_text("# Başlık\n\nAçıklama satırı.\n\n"
                  "- B.3.2 — 2025 ders izlenceleri (syllabus); ofis saatleri [yüksek]\n"
                  "- **C.1.1**: Araştırma komisyonu görev dağılımı (kimden: Araştırma komisyonu)\n"
                  "- B.1.x — Yeni açılan dersin ders programı\n"
                  "- Madde kodu olmayan istek\n", encoding="utf-8")
    ist = S.istekler_oku(md)
    assert [x["madde"] for x in ist] == ["B.3.2", "C.1.1", "B.1.x", "Genel"]
    assert ist[0]["oncelik"] == S.YUKSEK and "[" not in ist[0]["metin"]
    assert ist[1]["kimden"] == "Araştırma komisyonu" and "kimden" not in ist[1]["metin"]
    res = R.run(tgt_ws, out=tmp_path / "o", istekler=ist)
    r = {x["olcut"]: x for x in res["sade"]}
    assert r["B.3.2"]["belgeler"].startswith("• 2025 ders izlenceleri")
    assert r["B.3.2"]["oncelik"] == S.YUKSEK and r["B.3.2"]["neden"].startswith("Komisyon")
    assert "Araştırma komisyonu" in r["C.1.1"]["kimden"]
    assert r["B.1"]["madde"].startswith("B.1 — ") and "alt madde" in r["B.1"]["madde"]
    assert r["Genel"]["sira"] == len(res["sade"]) or r["Genel"]["oncelik"] != S.DUSUK
    csvp = tmp_path / "ist.csv"
    csvp.write_text("madde,istek,oncelik\nB.2.1,Ders izlencesi örnekleri,düşük\n", encoding="utf-8")
    c = S.istekler_oku(csvp)
    assert c == [{"madde": "B.2.1", "metin": "Ders izlencesi örnekleri", "oncelik": S.DUSUK, "kimden": ""}]
    bad = tmp_path / "kotu.csv"
    bad.write_text("olcut,ad\nB.2.1,x\n", encoding="utf-8")
    with pytest.raises(ValueError):
        S.istekler_oku(bad)


def test_sade_suggestions_only_for_unmet(tmp_path):
    """Komisyon önerisi yalnız eşlendiği kılavuz maddesi karşılanmamışsa listelenir."""
    ws = _ws(tmp_path / "w", 2025, {
        "a": ("bolum_kurulu_karari", True, "2025-02-01", "Bolum Kurulu Karari 2025", PLAN,
              [_m("B.1.1", "B.1.1/1", "planla", 2)], "kabul"),
    })
    on = [{"metin": "Sentetik öneri X ({yil})", "yuvalar": ["B.1.1/3"], "kimden": ""},
          {"metin": "Sentetik öneri Y", "yuvalar": ["B.1.1/1"], "kimden": ""}]
    res = R.run(ws, out=tmp_path / "o", oneriler=on)
    b = {x["olcut"]: x for x in res["sade"]}["B.1.1"]["belgeler"]
    assert "Sentetik öneri X (2025)" in b and "Sentetik öneri Y" not in b


def test_sade_data_tables_cover_guide():
    from bidr.criteria.loader import load_criteria
    from bidr.criteria.slots import load_tags
    cs = load_criteria()
    tags = load_tags(cs)
    so = S.Somut()
    ids = {s.id for s in cs.slots(include_footnotes=False)}
    ozgun = {i for i in ids if tags.get(i) is not None and "ozgun" in tags[i].stages}
    assert ids - ozgun <= set(so.yuva) and set(so.yuva) <= ids and so.ozgun
    on = S.oneriler_yukle()
    assert on and all(set(o["yuvalar"]) <= ids for o in on)
    assert S.yil_ilerlet("Toplanti Tutanaklari 2024-2025", 1) == "Toplanti Tutanaklari 2025-2026"
    assert S.yil_ilerlet("MAT113 Ders Formu", 1) == "MAT113 Ders Formu"


def test_cli_sade(tgt_ws, tmp_path, capsys):
    md = tmp_path / "ist.md"
    md.write_text("- A.1.1 — Sentetik istek\n", encoding="utf-8")
    out = tmp_path / "cli"
    assert main(["ihtiyac", "-w", str(tgt_ws), "--out", str(out), "--istenecekler", str(md)]) == 0
    assert (out / S.FILE).exists()
    assert "elle istek 1" in capsys.readouterr().out


# -- kılavuz eki: "Örnek Uygulama ve Kanıtlar Listesi" ------------------------------------------

def test_ornek_uygulama_data_and_mapping():
    """Şablondan çıkarılan 142 satırın hepsi 1–3 geçerli kılavuz yuvasına eşlenmiş (özgün yuva yok)."""
    from bidr.criteria import load_ornek_uygulamalar
    from bidr.criteria.loader import load_criteria
    from bidr.criteria.slots import load_tags
    raw = load_ornek_uygulamalar()
    assert raw["meta"]["counts"] == {"A": 25, "B": 80, "C": 21, "D": 16}
    assert set(raw["alanlar"]) == {"A", "B", "C", "D"}
    ids = [r["id"] for r in raw["satirlar"]]
    assert len(ids) == len(set(ids)) == 142
    assert all(r["uygulama"] and r["kanit"] for r in raw["satirlar"])
    assert not re.search(r"\bGTÜ\b|\bGTU\b|Gebze", json.dumps(raw, ensure_ascii=False))
    cs = load_criteria()
    tags = load_tags(cs)
    slots = {s.id for s in cs.slots(include_footnotes=False)}
    es = __import__("yaml").safe_load(S.ORNEK_ESLEME_FILE.read_text(encoding="utf-8"))["eslesme"]
    assert set(es) == set(ids)                                            # eşlemesiz ya da fazla satır yok
    for o in S.ornekler_yukle():
        assert 1 <= len(o["yuvalar"]) <= 3 and set(o["yuvalar"]) <= slots, o["id"]
        assert not any("ozgun" in tags[y].stages for y in o["yuvalar"] if tags.get(y) is not None), o["id"]
        assert o["olcutler"] == list(dict.fromkeys(y.split("/")[0] for y in o["yuvalar"]))


def test_ornek_metni_and_casing():
    o = {"kanit": "Toplantı gündemleri", "uygulama": "Bölüm kurullarında araştırma konusunun görüşülmesi"}
    assert S.ornek_metni(o) == "Toplantı gündemleri — bölüm kurullarında araştırma konusunun görüşülmesi"
    assert S._kucuk_bas("İç işleyişin izlenmesi") == "iç işleyişin izlenmesi"
    assert S._kucuk_bas("Isı yalıtımı") == "ısı yalıtımı"
    for keep in ("TÜBİTAK destekli projeler", "Ana Bilim Dalı durum tespiti", "Ölçme ve Değerlendirme komisyonu",
                 "Birim/Program web sayfaları", "Proliz sayfaları"):
        assert S._kucuk_bas(keep) == keep


def _orn(i, uyg, kanit, yuvalar, sade=True):
    return {"id": f"B/{i}", "alan": "B", "uygulama": uyg, "kanit": kanit, "yuvalar": yuvalar,
            "olcutler": list(dict.fromkeys(y.split("/")[0] for y in yuvalar)), "belirsiz": False, "sade": sade}


def test_sade_ornek_uygulama_suggestions(tmp_path):
    """Örnek uygulama yalnız karşılanmamış yuvada, önceki maddeyle örtüşmeden, sınırla ve okunur biçimde gelir;
    kalanlar "Kılavuzdaki örnek kanıtlar" sütununda; kurum düzeyi satır sade listeye girmez."""
    ws = _ws(tmp_path / "w", 2025, {
        "a": ("bolum_kurulu_karari", True, "2025-02-01", "Bolum Kurulu Karari 2025", PLAN,
              [_m("B.1.1", "B.1.1/1", "planla", 2)], "kabul"),
    })
    somut = tmp_path / "somut.yaml"
    somut.write_text("surum: 1\nozgun: [Ozgun belge]\nyuva:\n  B.1.1/5: [Sentetik paydas toplantisi tutanagi]\n",
                     encoding="utf-8")
    orn = [_orn(1, "Karşılanmış yuvaya ait zorvak uygulaması", "Kanıt K1", ["B.1.1/1"]),
           _orn(2, "Vimel brenta görüşmelerinin yapılması", "Kanıt K2", ["B.1.1/3"]),
           _orn(3, "Sentetik paydas toplantisi tutanagi hazırlanması", "Kanıt K3", ["B.1.1/5"]),   # somutla örtüşür
           _orn(4, "Kampüs ölçekli lodrak düzenlemesi", "Kanıt K4", ["B.1.1/6"], sade=False),
           _orn(5, "Derom kurulunun palvu kararları", "Kanıt K5", ["B.1.1/2"]),
           _orn(6, "Hiskel izleme çalışması", "Kanıt K6", ["B.1.1/6"]),
           _orn(7, "Sikor iyileştirme önerileri", "Kanıt K7", ["B.1.1/6", "C.1.1/1"])]
    res = R.run(ws, out=tmp_path / "o", somut=S.Somut(somut), oneriler=[], ornekler=orn)
    r = {x["olcut"]: x for x in res["sade"]}["B.1.1"]
    b = r["belgeler"].split("\n")
    ornek = [m for m in r["maddeler"] if m["tur"] == "ornek"]
    assert len(ornek) == S.ORNEK_EN_COK
    assert "• Kanıt K2 — vimel brenta görüşmelerinin yapılması" in b
    assert not any(x in r["belgeler"] for x in ("Kanıt K1", "Kanıt K3", "Kanıt K4"))
    # örnekler somut karşılıklardan sonra, kurum belgelerinden önce
    tur = [m["tur"] for m in r["maddeler"]]
    assert tur.index("ornek") > max(i for i, t in enumerate(tur) if t == "kilavuz")
    assert r["ornek_idler"] == sorted(r["ornek_idler"], key=lambda i: int(i.split("/")[1]))
    # yazılmayan karşılanmamış örnek kılavuz sütununda (kısaltılmış), karşılanmış ya da kurum düzeyi olan değil
    klv = r["kilavuz"]
    assert "Kılavuz ekindeki örnek uygulamalar" in klv
    assert "Sentetik paydas toplantisi" in klv and "zorvak" not in klv and "lodrak" not in klv
    assert not any(f"• {m['metin']}" in klv for m in ornek)
    # teknik ihtiyac.xlsx: satırların durumu
    wb = load_workbook(res["paths"]["xlsx"])
    sh = wb[R.SHEETS[4]]
    durum = {row[0]: row[-1] for row in sh.iter_rows(min_row=2, values_only=True)}
    assert durum["B/2"].startswith("listede (B.1.1") and durum["B/4"].startswith("kurum düzeyi")
    assert durum["B/1"].startswith("yuvası karşılanmış") and durum["B/3"].startswith("sınır ya da örtüşme")
    assert wb.sheetnames[-1] == "Açıklama"


def test_sade_ornek_default_data_used(tgt_ws, tmp_path):
    """Varsayılan veriyle (şablonun ek tabloları) satırlar sade listeye girer ve kimlik/kod içermez."""
    res = R.run(tgt_ws, out=tmp_path / "o")
    orn = [m for x in res["sade"] for m in x["maddeler"] if m["tur"] == "ornek"]
    assert orn and all(" — " in m["metin"] for m in orn)
    for x in res["sade"]:
        assert sum(1 for m in x["maddeler"] if m["tur"] == "ornek") <= S.ORNEK_EN_COK
        assert not re.search(r"\b[A-E]/\d+\b", x["belgeler"] + x["kilavuz"])


def test_sade_derse_ozgu_gecen_yil_belgesi_tur_duzeyinde_istenir():
    """Geçen yılki derse özgü belge (MATH407 anketi, MAT106 ders bilgi formu) bu yıl aynı dersin belgesi olarak
    değil, aynı türden herhangi bir dersin belgesi olarak istenir; aynı türler tek istekte; tekil program belgesi
    (ders kodu yok) eskisi gibi "ya da güncel hâli"."""
    from bidr.criteria.loader import load_criteria
    from bidr.ihtiyac.eslestir import YOK
    from bidr.ihtiyac.tablolar import Sorumlular

    def g(ad, bt, tek=""):
        return {"olcut": "B.1.3", "durum": YOK, "kanit_adi": ad, "belge_turu": bt, "tekrarlayan": tek,
                "tekrarlayan_ad": "Ders değerlendirme anketi" if tek else "", "asama": "uygula"}
    gecen = [g("MATH407 Ders Degerlendirme Anketi Sonucu 2024-2025 Bahar", "anket_sonucu", "ders_degerlendirme"),
             g("MAT106 Analitik Geometri Ders Bilgi Formu", "ders_bilgi_formu"),
             g("MAT 211 Lineer Cebir Ders Bilgi Formu", "ders_bilgi_formu"),
             g("MATH 301 Ders-Program Ciktilari Matrisi", "mufredat"),
             g("Matematik Lisans Ders Katalogu", "mufredat")]
    tal = [{"olcut": "B.1.3", "kaynak": "geçen yıl", "puan": 50, "yuvalar": "", "halka": "uygula"}]
    rows = S.satirlar_kur(load_criteria(), None, Sorumlular(), tal, [], gecen, yil=2026, ref_yil=2025)
    m = [x["metin"] for x in rows[0]["maddeler"] if x["tur"] == "gecen"]
    assert m[0] == ("Herhangi bir dersin ders değerlendirme anketi sonucu (2025-2026) (geçen yıl örnek: "
                    "«MATH407 Ders Degerlendirme Anketi Sonucu 2024-2025 Bahar»)")
    assert m[1].startswith("En az bir ders için ders bilgi formu / ders–program çıktıları matrisi (güncel) "
                           "(geçen yıl örnek: «MAT106") and m[1].endswith("ve 1 belge daha)")
    assert m[2] == ("«Matematik Lisans Ders Katalogu» ya da güncel hâli (geçen yılki raporda vardı, bu yılki "
                    "dosyalarda bulunamadı)")
    assert len(m) == 3
