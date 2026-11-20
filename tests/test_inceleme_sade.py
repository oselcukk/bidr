"""review.xlsx sade sayfaları (İnceleme, Maddeler, Nasıl doldurulur): yazım, bölümler, sade karar →
teknik karar çevirisi, toplu kabul, teknik sayfa yolu, eski biçim kararlarının taşınması. Sentetik veri."""
from __future__ import annotations

import json

from openpyxl import load_workbook

from bidr.audit import sade as S
from bidr.audit.run import FILES, apply, audit, load_review_decisions, review_state
from bidr.audit.sheet import COLS, SHEET_ROWS
from bidr.common import read_jsonl

from test_audit import _fill, ws  # noqa: F401  (ws: fixture)

H = {k: h for k, h, _, _ in S.INC_COLS}


def _inc(path):
    wb = load_workbook(path)
    sh = wb[S.SH_INC]
    head = [c.value for c in sh[1]]
    col = {k: head.index(h) + 1 for k, h in H.items()}
    return wb, sh, col


def _rows(path) -> dict[str, dict]:
    wb, sh, col = _inc(path)
    out = {}
    for r in range(2, sh.max_row + 1):
        sid = sh.cell(row=r, column=col["satir"]).value
        if sid and "|" in str(sid):
            out[sid] = {k: sh.cell(row=r, column=c).value for k, c in col.items()}
    return out


def _set(path, values: dict[str, dict], toplu: bool = False):
    wb, sh, col = _inc(path)
    for r in range(2, sh.max_row + 1):
        sid = sh.cell(row=r, column=col["satir"]).value
        if sid == S.TOPLU_SATIR and toplu:
            sh.cell(row=r, column=col["karar"], value=S.TOPLU)
        for k, v in values.get(sid, {}).items():
            sh.cell(row=r, column=col[k], value=v)
    wb.save(path)


def test_sheets_sections_and_plain_text(ws):
    a, paths = audit(ws)
    wb = load_workbook(paths["xlsx"])
    assert wb.sheetnames[:3] == [S.SH_INC, S.SH_MADDE, S.SH_NASIL] and wb.active.title == S.SH_INC
    assert all(wb[n].sheet_state == "hidden" for n in (SHEET_ROWS, "Ölçüt özeti", "Açıklama", "_meta"))
    sh = wb[S.SH_INC]
    vis = [c.value for c in sh[1] if not sh.column_dimensions[c.column_letter].hidden]
    assert vis == ["Sıra", "Madde", "Belge (klasördeki dosya)", "Önerilen kanıt adı (düzeltebilirsiniz)",
                   "Belgede ne yazıyor", "Neden bu maddeye", "Dikkat", "Önerimiz", "KARARINIZ",
                   "Doğru madde (yalnız taşınacaksa)", "Not"]
    assert sh.freeze_panes == "C2" and sh.print_title_rows
    rows = _rows(paths["xlsx"])
    assert set(rows) == {r["satir"] for r in a.rows}
    # düşük güven ve önceki yıl olayı: bakılacak (1. bölüm), düz Türkçe uyarı, kod adı yok
    low, old = rows["d_onlem|B.1.1/5"], rows["d_eski|A.1.1/2"]
    assert low["bolum"] == 1 and low["oneri"] == "Bakın" and "emin değil" in low["dikkat"]
    assert old["bolum"] == 1 and "önceki bir yıla ait" in old["dikkat"]
    assert "B.1.1 — " in low["madde"] and "_" not in (low["dikkat"] + old["dikkat"])
    # sorunsuz satır: 2. bölüm, öneri Kabul, karar boş
    ok = rows["d_plan|B.1.1/1"]
    assert ok["bolum"] == 2 and ok["oneri"] == "Kabul" and not ok["karar"]
    # bölüm başlıkları ve toplu kabul hücresi
    texts = [str(sh.cell(row=r, column=1).value or "") for r in range(2, sh.max_row + 1)]
    assert any(t.startswith("1. BAKMANIZ") for t in texts) and any(t.startswith("2. SORUNSUZ") for t in texts)
    assert "Hepsini kabul" in next(t for t in texts if t.startswith("2."))
    # Maddeler: önerilen düzey sözle; Nasıl doldurulur 5-7 satır
    m = wb[S.SH_MADDE]
    b11 = next(r for r in m.iter_rows(min_row=2, values_only=True) if str(r[0]).startswith("B.1.1"))
    assert b11[1] == S.OD_AD[3]
    assert 5 <= wb[S.SH_NASIL].max_row - 1 <= 7


def test_plain_decisions_convert_to_technical(ws):
    a, paths = audit(ws)
    x = paths["xlsx"]
    _set(x, {"d_plan|B.1.1/1": {"karar": "Ret", "not": "kanıt değil"},
             "d_uyg|B.1.1/3": {"karar": "Kabul — etkinlik yapıldı"},
             "d_kont|B.1.1/6": {"karar": "Başka maddeye taşı", "dogru": "B.3.2 — Akademik destek hizmetleri"},
             "d_onlem|B.1.1/5": {"karar": "Başka maddeye taşı — etkinlik yapıldı", "dogru": "B.2.3/2"},
             "d_yon|B.2.3/2": {"karar": "Kabul", "ad": "Bölüm Staj Yönergesi"}})
    st = apply(ws)
    assert not st["gecersiz"] and st["kararli"] == 5 and st["bos"] == 3
    d = load_review_decisions(ws)
    assert d["d_plan|B.1.1/1"]["karar"] == "ret" and d["d_plan|B.1.1/1"]["not"] == "kanıt değil"
    assert d["d_uyg|B.1.1/3"]["karar"] == "duzelt"
    assert d["d_uyg|B.1.1/3"]["duzelt"] == {"olcut": None, "yuva": None, "asama": "uygula"}
    t = d["d_kont|B.1.1/6"]
    assert t["karar"] == "duzelt" and t["duzelt"]["olcut"] == "B.3.2" and t["duzelt"]["yuva"].startswith("B.3.2/")
    assert d["d_onlem|B.1.1/5"]["duzelt"] == {"olcut": "B.2.3", "yuva": "B.2.3/2", "asama": "uygula"}
    assert d["d_yon|B.2.3/2"]["karar"] == "kabul"
    names = {r["doc_id"]: r for r in read_jsonl(ws / "kanit-adlari.jsonl")}
    assert names["d_yon"]["ad"] == "Bölüm Staj Yönergesi" and names["d_yon"]["kaynak"] == "insan"
    # yeniden üretim: kararlar 3. bölümde aynı etiketlerle; tekrar apply aynı kayıt
    before = (ws / FILES["decisions"]).read_text(encoding="utf-8")
    audit(ws)
    rows = _rows(ws / "review.xlsx")
    assert rows["d_plan|B.1.1/1"]["karar"] == "Ret" and rows["d_plan|B.1.1/1"]["bolum"] == 3
    assert rows["d_uyg|B.1.1/3"]["karar"] == "Kabul — etkinlik yapıldı"
    assert rows["d_onlem|B.1.1/5"]["karar"] == "Başka maddeye taşı — etkinlik yapıldı"
    assert rows["d_onlem|B.1.1/5"]["dogru"] == "B.2.3/2"
    apply(ws)
    assert (ws / FILES["decisions"]).read_text(encoding="utf-8") == before


def test_move_without_target_is_invalid(ws):
    a, paths = audit(ws)
    _set(paths["xlsx"], {"d_plan|B.1.1/1": {"karar": "Başka maddeye taşı"},
                         "d_uyg|B.1.1/3": {"karar": "Belki"}})
    st = apply(ws)
    assert "Doğru madde" in st["gecersiz"]["d_plan|B.1.1/1"] and "geçersiz" in st["gecersiz"]["d_uyg|B.1.1/3"]


def test_bulk_accept_only_with_explicit_choice(ws):
    a, paths = audit(ws)
    x = paths["xlsx"]
    rows = _rows(x)
    safe = {s for s, r in rows.items() if r["bolum"] == 2}
    look = {s for s, r in rows.items() if r["bolum"] == 1}
    assert safe and look
    # seçim yoksa boş satır karar beklemeye devam eder (ara apply'lar toplu kabul etmez)
    st = apply(ws)
    assert st["kararli"] == 0 and st["bos"] == len(rows)
    one = sorted(safe)[0]
    _set(x, {one: {"karar": "Ret"}}, toplu=True)
    st = apply(ws)
    d = load_review_decisions(ws)
    assert d[one]["karar"] == "ret"                                  # tek tek seçilen önce gelir
    for s in safe - {one}:
        assert d[s]["karar"] == "kabul" and S.TOPLU_NOT in d[s]["not"]
    assert not look & set(d) and st["bos"] == len(look)              # bakılacaklar toplu kabul edilmez
    assert not review_state(ws, ws)["uygulanmamis"]


def test_technical_sheet_path_and_plain_precedence(ws):
    a, paths = audit(ws)
    x = paths["xlsx"]
    _fill(x, {"d_plan|B.1.1/1": {"karar": "ret"}, "d_uyg|B.1.1/3": {"karar": "ret"}})
    _set(x, {"d_uyg|B.1.1/3": {"karar": "Kabul"}})
    apply(ws)
    d = load_review_decisions(ws)
    assert d["d_plan|B.1.1/1"]["karar"] == "ret"          # sade değişmedi: teknik sayfa geçerli
    assert d["d_uyg|B.1.1/3"]["karar"] == "kabul"         # ikisi de değişti: sade önce gelir


def test_legacy_table_decisions_carried_into_plain_sheet(ws):
    a, paths = audit(ws)
    x = paths["xlsx"]
    wb = load_workbook(x)                                  # eski biçim: yalnız teknik sayfalar
    for n in (*S.SADE_SHEETS, S.SH_LISTE):
        if n in wb.sheetnames:
            wb.remove(wb[n])
    wb[SHEET_ROWS].sheet_state = "visible"
    wb.active = wb.sheetnames.index(SHEET_ROWS)
    wb.save(x)
    vals = {"d_plan|B.1.1/1": {"karar": "kabul", "not": "n1"}, "d_uyg|B.1.1/3": {"karar": "ret"},
            "d_kont|B.1.1/6": {"karar": "duzelt", "duzelt_yuva": "B.1.1/3", "duzelt_asama": "uygula"}}
    _fill(x, vals)
    _, paths = audit(ws)                                   # uygulanmamış kararlar taşınır
    rows = _rows(paths["xlsx"])
    assert rows["d_plan|B.1.1/1"]["karar"] == "Kabul" and rows["d_plan|B.1.1/1"]["not"] == "n1"
    assert rows["d_uyg|B.1.1/3"]["karar"] == "Ret"
    assert rows["d_kont|B.1.1/6"]["karar"] == "Başka maddeye taşı — etkinlik yapıldı"
    st = apply(ws)
    assert st["kararli"] == 3 and not st["gecersiz"]
    d = load_review_decisions(ws)
    assert d["d_kont|B.1.1/6"]["duzelt"] == {"olcut": "B.1.1", "yuva": "B.1.1/3", "asama": "uygula"}


def test_relook_row_needs_new_choice(ws):
    a, paths = audit(ws)
    _set(paths["xlsx"], {"d_plan|B.1.1/1": {"karar": "Kabul"}})
    apply(ws)
    seen = ws / FILES["gorulen"]
    recs = [json.loads(line) for line in seen.read_text(encoding="utf-8").splitlines()]
    for r in recs:
        r["isaretler"] = []
        r["od"] = 9                                       # görülen durum farklı → yeniden bak
    seen.write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
    audit(ws)
    r = _rows(ws / "review.xlsx")["d_plan|B.1.1/1"]
    assert r["bolum"] == 1 and not r["karar"] and "Daha önce \"Kabul\"" in r["dikkat"]
    assert review_state(ws, ws)["yeniden_bak"] == 1
    _set(ws / "review.xlsx", {"d_plan|B.1.1/1": {"karar": "Kabul"}})
    apply(ws)
    assert review_state(ws, ws)["yeniden_bak"] == 0 and load_review_decisions(ws)["d_plan|B.1.1/1"]["karar"] == "kabul"


def test_od_sheet_level(ws):
    a, paths = audit(ws)
    wb = load_workbook(paths["xlsx"])
    m = wb[S.SH_MADDE]
    head = [c.value for c in m[1]]
    oi = head.index("Onayladığınız düzey (boş = öneri)") + 1
    r = next(i for i in range(2, m.max_row + 1) if str(m.cell(row=i, column=1).value).startswith("B.1.1"))
    m.cell(row=r, column=oi, value=S.OD_AD[4])
    wb.save(paths["xlsx"])
    st = apply(ws)
    assert not st["od_gecersiz"]
    od = {x["olcut"]: x for x in read_jsonl(ws / FILES["od"])}
    assert od["B.1.1"]["od"] == 4


def test_cols_unchanged_for_technical_sheet():
    keys = [k for k, _, _, _ in COLS]
    assert {"satir", "karar", "duzelt_olcut", "duzelt_yuva", "duzelt_asama", "not", "kanit_adi"} <= set(keys)
