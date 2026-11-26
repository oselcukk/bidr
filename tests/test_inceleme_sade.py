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
    # 1. satır gizli: okuyucu başlıkları (bidr'in tam metinleri); görünen başlık 5. satırda
    assert sh.row_dimensions[1].hidden and [c.value for c in sh[1]] == [h for _, h, _, _ in S.INC_COLS]
    vis = [c.value for c in sh[S.INC_BASLIK_SATIRI] if not sh.column_dimensions[c.column_letter].hidden]
    assert vis[:8] == ["Madde", "Önerilen belge", "Belgede ne yazıyor (kısa)", "Öneri", "KARARINIZ ▼",
                       "Doğru madde (yalnız taşınacaksa) ▼", "Kanıt adı (düzeltebilirsiniz)", "Not"]
    assert {"Kılavuz örneği (madde yuvası)", "Klasör · kaynak dosya", "Dikkat (uyarılar)"} <= set(vis)
    for c in sh[S.INC_BASLIK_SATIRI]:                    # ayrıntı sütunları katlanabilir, genişlik korunur
        d = sh.column_dimensions[c.column_letter]
        k = S.INC_COLS[c.column - 1][0]
        assert d.width == S.INC_COLS[c.column - 1][2]
        assert d.outline_level == (1 if S.INC_GORUNEN[k][1] == "d" else 0)
    assert sh.freeze_panes == f"C{S.INC_ILK}" and sh.print_title_rows
    assert sh.auto_filter.ref.startswith(f"A{S.INC_BASLIK_SATIRI}:")
    assert sh["A2"].value.startswith("Renkler") and sh["A3"].value.startswith('="Toplam öneri: "')
    # alan ve madde ayraç satırları (satır kimliği boş)
    a_col = [str(sh.cell(row=r, column=1).value or "") for r in range(S.INC_ILK, sh.max_row + 1)]
    assert "B — Eğitim ve Öğretim" in a_col and any(t.strip().startswith("B.1.1 — ") and "öneri" in t for t in a_col)
    rows = _rows(paths["xlsx"])
    assert set(rows) == {r["satir"] for r in a.rows}
    # düşük güven ve önceki yıl olayı: bakılacak (1. bölüm), düz Türkçe uyarı, kod adı yok
    low, old = rows["d_onlem|B.1.1/5"], rows["d_eski|A.1.1/2"]
    assert low["bolum"] == 1 and low["oneri"] == "Bakın" and "emin değil" in low["dikkat"]
    assert old["bolum"] == 1 and "önceki bir yıla ait" in old["dikkat"]
    assert low["madde"].startswith("B.1.1 — ") and "Kılavuz" not in low["madde"]
    assert "_" not in (low["dikkat"] + old["dikkat"])
    assert low["kilavuz"] and "\n" not in (low["belge"] or "") and "(klasör:" not in (low["belge"] or "")
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


# -- gidiş-dönüş: yeni tasarım ↔ eski (tek başlık satırı, 14 sütun) biçim --------------------------

ESKI_COLS = [("sira", "Sıra"), ("madde", "Madde"), ("belge", "Belge (klasördeki dosya)"),
             ("ad", "Önerilen kanıt adı (düzeltebilirsiniz)"), ("alinti", "Belgede ne yazıyor"),
             ("neden", "Neden bu maddeye"), ("dikkat", "Dikkat"), ("oneri", "Önerimiz"), ("karar", "KARARINIZ"),
             ("dogru", "Doğru madde (yalnız taşınacaksa)"), ("not", "Not"), ("satir", "satır kimliği"),
             ("bolum", "bölüm"), ("yazilan", "yazılan")]
OKUNAN = ("satir", "karar", "dogru", "not", "ad", "bolum", "yazilan")


def _eski_bicim(a, path):
    """Önceki `write_sade` İnceleme düzeni (yalnız okuyucunun gördüğü yapı): 1. satır başlık, bölüm başlıkları,
    2. bölüm başlığında #toplu, ardından satırlar."""
    from openpyxl import Workbook
    from bidr.criteria.loader import load_criteria
    wb = Workbook()
    sh = wb.active
    sh.title = S.SH_INC
    sh.append([h for _, h in ESKI_COLS])
    rows = S.inceleme_satirlari(a, load_criteria())
    for b in (1, 2, 3):
        grp = [x for x in rows if x["bolum"] == b]
        if not grp:
            continue
        baslik = [S.BOLUM_BASLIK[b].format(n=len(grp))] + [None] * (len(ESKI_COLS) - 1)
        if b == 2:
            baslik[11] = S.TOPLU_SATIR
        sh.append(baslik)
        for x in grp:
            sh.append([x.get(k, "") for k, _ in ESKI_COLS])
    wb.save(path)
    return path


def _isaretle(path, kararlar, toplu=False):
    """Okuyucunun sütun eşlemesiyle (1. satır başlıkları) kararları yazar: iki biçimde de aynı yol."""
    wb = load_workbook(path)
    sh = wb[S.SH_INC]
    head = [c.value for c in sh[1]]
    col = {k: head.index(h) + 1 for k, h, _, _ in S.INC_COLS if h in head}
    for r in range(2, sh.max_row + 1):
        sid = sh.cell(row=r, column=col["satir"]).value
        if sid == S.TOPLU_SATIR and toplu:
            sh.cell(row=r, column=col["karar"], value=S.TOPLU)
        for k, v in kararlar.get(sid, {}).items():
            sh.cell(row=r, column=col[k], value=v)
    wb.save(path)


def test_yeni_tasarim_gidis_donus_eski_bicimle_ayni(ws, tmp_path):
    import copy
    from bidr.criteria.loader import load_criteria
    a, paths = audit(ws)
    yeni = paths["xlsx"]
    eski = _eski_bicim(a, tmp_path / "eski.xlsx")

    def oku(p):
        r, t = S.read_inceleme(load_workbook(p))
        return {sid: {k: x.get(k) for k in OKUNAN} for sid, x in r.items()}, t

    ry, ty = oku(yeni)
    re_, te = oku(eski)
    assert set(ry) == set(re_) == {r["satir"] for r in a.rows}            # aynı satırlar / anahtarlar
    assert ry == re_ and ty == te is False                                # aynı alan değerleri
    # yeni dosyada fazladan okunan satır yok (ayraç, açıklama, görünen başlık atlanır)
    wb = load_workbook(yeni)
    sh = wb[S.SH_INC]
    sc = [h for _, h, _, _ in S.INC_COLS].index("satır kimliği") + 1
    ids = [sh.cell(row=r, column=sc).value for r in range(2, sh.max_row + 1)]
    assert sorted(i for i in ids if i and "|" in str(i)) == sorted(ry)
    assert [i for i in ids if i == S.TOPLU_SATIR] == [S.TOPLU_SATIR]
    # aynı kararlar işaretlenince aynı teknik kararlar
    rows = list(ry)
    b2 = [s for s, x in ry.items() if x["bolum"] == 2]
    kararlar = {rows[0]: {"karar": "Ret", "not": "kanıt değil"},
                rows[1]: {"karar": "Kabul — etkinlik yapıldı"},
                rows[2]: {"karar": "Başka maddeye taşı", "dogru": "B.3.2 — Akademik destek hizmetleri"},
                rows[3]: {"karar": "Kabul", "ad": "Sentetik Ad"}}
    for p in (yeni, eski):
        _isaretle(p, kararlar, toplu=True)
    cs = load_criteria()
    ty_ = S.merge_rows(copy.deepcopy(a.rows), S.read_inceleme(load_workbook(yeni)), cs)
    te_ = S.merge_rows(copy.deepcopy(a.rows), S.read_inceleme(load_workbook(eski)), cs)
    alan = ("satir", "karar", "duzelt_olcut", "duzelt_yuva", "duzelt_asama", "not", "kanit_adi", "bakildi", "sade_hata")
    assert [{k: r.get(k) for k in alan} for r in ty_] == [{k: r.get(k) for k in alan} for r in te_]
    d = {r["satir"]: r for r in ty_}
    assert d[rows[0]]["karar"] == "ret" and d[rows[2]]["duzelt_olcut"] == "B.3.2"
    assert b2 and all(d[s]["karar"] for s in b2)                          # toplu kabul iki biçimde de işledi


# -- "başka maddenin konusu" reti ----------------------------------------------------------------

def test_ret_baska_madde_needs_target_and_moves(ws):
    a, paths = audit(ws)
    _set(paths["xlsx"], {"d_plan|B.1.1/1": {"karar": S.K_RET_BASKA}})
    st = apply(ws)
    assert "Doğru madde" in st["gecersiz"]["d_plan|B.1.1/1"] and "rapordan" in st["gecersiz"]["d_plan|B.1.1/1"]
    a, paths = audit(ws)
    _set(paths["xlsx"], {"d_plan|B.1.1/1": {"karar": S.K_RET_BASKA, "dogru": "B.3.2/3", "not": "B.3.2 konusu"}})
    st = apply(ws)
    assert not st["gecersiz"]
    d = load_review_decisions(ws)["d_plan|B.1.1/1"]
    assert d["karar"] == "duzelt" and d["duzelt"]["olcut"] == "B.3.2" and d["duzelt"]["yuva"] == "B.3.2/3"
    assert S.K_RET_BASKA in S.KARAR_SECENEK


def test_ret_note_citing_other_criterion_warns_document_dropped(ws):
    a, paths = audit(ws)
    _set(paths["xlsx"], {"d_plan|B.1.1/1": {"karar": "Ret", "not": "önceki turda B.3.5 olarak; bu madde değil"}})
    assert not apply(ws)["gecersiz"]
    a, paths = audit(ws)
    gaps = (ws / FILES["gaps"]).read_text(encoding="utf-8")
    assert "rapor dışına düştü" in gaps and "B.3.5" in gaps
    r = next(x for x in a.rows if x["satir"] == "d_plan|B.1.1/1")
    assert "ret_hedefsiz_dustu" in r["flags"] and r["ret_anilan"] == ["B.3.5"]
    row = _rows(ws / "review.xlsx")["d_plan|B.1.1/1"]
    assert "rapor dışına düştü" in (row["dikkat"] or "") and row["bolum"] == 3   # bilgi; yeniden baktırmaz


def test_ret_cited_and_mark_dropped_units():
    from bidr.audit.run import mark_dropped_rejections, ret_cited
    assert ret_cited("tek dersin sınav kuralı, B.2.2 konusu", "B.1.6") == ["B.2.2"]
    assert ret_cited("başka maddeye ait", "B.1.1") == ["başka madde"]
    assert ret_cited("alıntı yetersiz", "B.1.1") == [] and ret_cited("B.1.1 değil", "B.1.1") == []
    rows = [{"doc_id": "a", "belge": "a", "olcut": "C.2.1", "karar": "ret", "not": "B.3.5 konusu",
             "sayilir": False, "flags": []},
            {"doc_id": "b", "belge": "b", "olcut": "C.2.1", "karar": "ret", "not": "B.3.5 konusu",
             "sayilir": False, "flags": []},
            {"doc_id": "b", "belge": "b", "olcut": "B.3.5", "karar": "", "not": "", "sayilir": True, "flags": []}]
    uy: list[str] = []
    out = mark_dropped_rejections(rows, uy)
    assert [r["doc_id"] for r in out] == ["a"] and len(uy) == 1 and "1 belge rapor dışına düştü" in uy[0]


def test_assumptions_do_not_ask():
    """Yükleyen bölümün belgesi ve tarihsiz belgenin dönem içi olduğu varsayılır (kullanıcı kararı 2026-11-26):
    varsayım işaretleri Dikkat yazmaz, Önerimiz'i "Bakın" yapmaz; açık çelişki yine sorulur."""
    from bidr.audit.sade import dikkat
    base = {"sayilir": True, "od": 2, "karar": "", "zayif": False}
    for fl in (["birim_varsayildi"], ["tarih_varsayildi"], ["yururluk_varsayildi"],
               ["birim_varsayildi", "tarih_varsayildi", "birim_iliskisi_kod_bilgi"]):
        assert dikkat({**base, "flags": fl}, 2025) == ([], False), fl
    for fl in (["birim_onay_bekliyor"], ["tarih_dogrulanmali"], ["gecmis_kanit"], ["surum_dogrulanmali"],
               ["guncellik_dogrulanmali", "revizyon_donem_sonrasi"], ["guncellik_dogrulanmali", "yururluk_bitmis"]):
        uy, bak = dikkat({**base, "flags": fl}, 2025)
        assert bak and uy, fl
    uy, _ = dikkat({**base, "flags": ["birim_onay_bekliyor"]}, 2025)
    assert "başka bir birimin adı" in uy[0]
