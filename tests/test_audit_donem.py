"""Dönem kuralı (komisyon kararı 2026-11-18): yapı/olay/karma belge, geçmiş kanıt, tarih ve
güncellik işaretleri, gözden geçirme döngüsü (sentetik veri, model yok)."""
from __future__ import annotations

import json

import pytest
from openpyxl import load_workbook

from bidr.audit import donem as D
from bidr.audit.run import FILES, audit, build
from bidr.audit.sheet import COLS, SHEET_ROWS
from bidr.identify.catalog import load_catalog

YIL = 2025


def _m(olcut, yuva, asama, od, alinti="x" * 30, guven="orta"):
    return {"olcut": olcut, "yuva": yuva, "asama": asama, "od_onerisi": od, "alinti": alinti,
            "gerekce": "g", "guven": guven, "denetim": {"red": [], "isaret": []}, "od_kabul": od,
            "kabul": True}


def _doc(tur, tarih=None, ici=None):
    d = {"doc_type": tur, "tarih": tarih, "donem": YIL, "akademik_donem": []}
    if ici is None and tarih:
        ici = int(tarih[:4]) == YIL
    d["donem_ici"] = ici
    return d


def _ws(tmp_path, docs: dict, *, donem=True):
    w = tmp_path / "ws"
    w.mkdir(exist_ok=True)
    with open(w / "decisions.jsonl", "w", encoding="utf-8") as f:
        for did, (_, ms) in docs.items():
            f.write(json.dumps({"doc_id": did, "durum": "ok", "asama": "ince", "karar": "olcut_var",
                                "eslesmeler": ms}, ensure_ascii=False) + "\n")
    with open(w / "documents.jsonl", "w", encoding="utf-8") as f:
        for did, (d, _) in docs.items():
            rec = {"doc_id": did, "calisma_adi": did, **d}
            if not donem:
                rec = {k: v for k, v in rec.items() if k not in ("donem", "donem_ici")}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return w


def _crit(a, cid):
    return next(c for c in a.criteria if c["olcut"] == cid)


# -- veri ------------------------------------------------------------------------------

# Sınıfı henüz donem_kurali.yaml'a işlenmemiş türler (profil verisi bu şeridin dışında; karar
# sahibinin). Kodda karma sayılır: planla yapı, üstü olay. Liste yalnız küçülebilir.
SINIFSIZ: set[str] = set()


def test_every_catalog_type_has_exactly_one_class():
    rule = D.load_rule()
    names = {t.name for t in load_catalog().types}
    assert names - SINIFSIZ <= set(rule.classes), sorted(names - SINIFSIZ - set(rule.classes))
    assert SINIFSIZ <= names
    for t in SINIFSIZ - set(rule.classes):
        assert rule.cls(t, "planla") == D.YAPI and rule.cls(t, "uygula") == D.OLAY
    assert set(rule.classes) <= names, sorted(set(rule.classes) - names)
    # komisyon kararındaki örnekler
    for t in ("mufredat", "ders_bilgi_formu", "akts_bilgi_paketi", "yonerge", "yonetmelik",
              "gorev_dagilimi", "is_akisi", "stratejik_plan"):
        assert rule.classes[t] == D.YAPI, t
    for t in ("bolum_kurulu_karari", "komisyon_tutanagi", "anket_sonucu", "faaliyet_raporu",
              "resmi_yazi", "etkinlik_duyurusu"):
        assert rule.classes[t] == D.OLAY, t


def test_karma_and_unknown_follow_stage():
    rule = D.load_rule()
    assert rule.cls("web_sayfasi", "planla") == D.YAPI and rule.cls("web_sayfasi", "uygula") == D.OLAY
    assert rule.cls("bilinmiyor", "planla") == D.YAPI and rule.cls("", "kontrol_et") == D.OLAY


@pytest.mark.parametrize("alinti,yil", [
    ("Program her 4 yılda bir gözden geçirilir.", 4),
    ("Müfredat dört yılda bir güncellenir", 4),
    ("Ders planı iki yılda bir komisyonca incelenir", 2),
    ("akreditasyon döngüsünde programın tamamı değerlendirilir", 4),     # sayı yok: varsayılan
    ("Her 10 yılda bir", 6),                                             # üst sınır
    ("Bölüm kurulu toplandı ve ders planını görüştü.", None),
    ("her yıl anket yapılır", None),                                     # yıllık: döngü değil
    ("1 yılda bir rapor hazırlanır", None),
    ("2021 yılda bir kez", None),                                        # yıl sayısı değil
])
def test_cycle_years_from_quote(alinti, yil):
    assert D.load_rule().cycle_years(alinti) == yil


def test_principle_in_prompt():
    from bidr.decide.prompt import evidence_principles
    t = evidence_principles()
    assert "Dönem kuralını kod" in t and "geçmiş kanıt" in t and "her 4 yılda bir" in t


# -- yapı / olay -------------------------------------------------------------------------

@pytest.fixture
def ws(tmp_path):
    return _ws(tmp_path, {
        # yapı: eski tarihli müfredat yürürlükte sayılır, güncellik işaretlenir
        "mufredat_eski": (_doc("mufredat", "2019-09-01"), [_m("B.1.2", "B.1.2/2", "uygula", 3)]),
        "dbf_ici": (_doc("ders_bilgi_formu", "2025-02-01"), [_m("B.1.2", "B.1.2/1", "planla", 2)]),
        "dbf_tarihsiz": (_doc("ders_bilgi_formu"), [_m("B.1.2", "B.1.2/1", "uygula", 3)]),
        # olay: önceki yıl izleme sonucu → geçmiş kanıt; önceki yıl usul kararı → plan sayılır
        "anket_2023": (_doc("anket_sonucu", "2023-05-10"), [_m("A.4.2", "A.4.2/5", "kontrol_et", 4)]),
        "karar_2022": (_doc("bolum_kurulu_karari", "2022-03-01"),
                       [_m("A.4.2", "A.4.2/1", "planla", 2), _m("A.4.2", "A.4.2/2", "uygula", 3)]),
        # olay: tarihsiz ve rapor yılından sonra
        "anket_tarihsiz": (_doc("anket_sonucu"), [_m("A.4.2", "A.4.2/2", "uygula", 3)]),
        "tutanak_2026": (_doc("komisyon_tutanagi", "2026-01-15"), [_m("A.4.2", "A.4.2/3", "onlem_al", 4)]),
        # karma: tarihsiz web sayfası; plan yapı gibi, uygulama olay gibi
        "web": (_doc("web_sayfasi"), [_m("A.4.2", "A.4.2/4", "planla", 2), _m("B.1.2", "B.1.2/3", "uygula", 3)]),
    })


def test_structure_documents_count_with_currency_flag(ws):
    a = build(ws)
    r = a.by_key["mufredat_eski|B.1.2/2"]
    assert r["sayilir"] and "guncellik_dogrulanmali" in r["flags"]
    assert r["donem_kurali"].startswith("yapı · önceki yıl (2019)") and "güncellik doğrulanmalı" in r["donem_kurali"]
    r = a.by_key["dbf_ici|B.1.2/1"]
    assert r["sayilir"] and not {"guncellik_dogrulanmali", "gecmis_kanit"} & set(r["flags"])
    r = a.by_key["dbf_tarihsiz|B.1.2/1"]
    assert r["sayilir"] and "guncellik_dogrulanmali" in r["flags"]   # yapı tarihsiz: sayılır
    assert _crit(a, "B.1.2")["od"] == 3


def test_event_documents(ws):
    a = build(ws)
    by = a.by_key
    # önceki yıl U/K/Ö sayılmaz; planla (usul kararı) sayılır + güncellik
    assert not by["anket_2023|A.4.2/5"]["sayilir"] and "gecmis_kanit" in by["anket_2023|A.4.2/5"]["flags"]
    assert not by["karar_2022|A.4.2/2"]["sayilir"]
    assert by["karar_2022|A.4.2/1"]["sayilir"] and "guncellik_dogrulanmali" in by["karar_2022|A.4.2/1"]["flags"]
    # sonraki yıl ve tarihsiz: hiçbir aşama sayılmaz, satır var
    assert not by["tutanak_2026|A.4.2/3"]["sayilir"] and "donem_sonrasi" in by["tutanak_2026|A.4.2/3"]["flags"]
    r = by["anket_tarihsiz|A.4.2/2"]
    assert not r["sayilir"] and "tarih_dogrulanmali" in r["flags"] and "tarih doğrulanmalı" in r["donem_kurali"]
    # karma: tarihsiz web sayfasının planı sayılır, uygulaması tarih ister
    assert by["web|A.4.2/4"]["sayilir"] and "guncellik_dogrulanmali" in by["web|A.4.2/4"]["flags"]
    assert not by["web|B.1.2/3"]["sayilir"] and "tarih_dogrulanmali" in by["web|B.1.2/3"]["flags"]
    c = _crit(a, "A.4.2")
    assert c["od"] == 2                               # yalnız plan halkaları sayıldı
    assert c["od_tarih_dogrulanirsa"] == 3            # tarihsiz anket doğrulanırsa
    assert {g["satir"] for g in c["gecmis_kanit"]} == {"anket_2023|A.4.2/5", "karar_2022|A.4.2/2"}
    assert any("geçmiş kanıt" in n and "2022, 2023" in n for n in c["notlar"])
    assert any("doğrulanırsa OD3" in n for n in c["notlar"])


def test_outputs_show_period_marks(ws, tmp_path):
    out = tmp_path / "out"
    audit(ws, out=out)
    g = (out / FILES["gaps"]).read_text(encoding="utf-8")
    assert "## Geçmiş kanıtlar (süreklilik) (rapor yılı 2025)" in g
    assert "A.4.2 `A.4.2/5` K 2023: `anket_2023`" in g
    assert "## Tarihi doğrulanacak olay belgeleri" in g and "`anket_tarihsiz`: A.4.2/2 U" in g
    assert "## Güncelliği doğrulanacak belgeler" in g and "`mufredat_eski`" in g
    js = json.loads((out / FILES["json"]).read_text(encoding="utf-8"))
    assert js["donem"] == YIL
    wb = load_workbook(out / FILES["xlsx"])
    sh = wb[SHEET_ROWS]
    head = [c.value for c in sh[1]]
    col = head.index(dict((k, h) for k, h, _, _ in COLS)["donem_kurali"])
    cells = {sh.cell(row=i, column=1).value: sh.cell(row=i, column=col + 1).value for i in range(2, sh.max_row + 1)}
    assert "tarih doğrulanmalı" in cells["anket_tarihsiz|A.4.2/2"]     # satır görünür
    assert "geçmiş kanıt" in cells["anket_2023|A.4.2/5"]


def test_human_correction_overrides_date_rule(ws, tmp_path):
    out = tmp_path / "out"
    dec = {"satir": "anket_tarihsiz|A.4.2/2", "doc_id": "anket_tarihsiz", "olcut": "A.4.2", "yuva": "A.4.2/2",
           "karar": "duzelt", "duzelt": {"olcut": None, "yuva": None, "asama": "uygula"}, "etiket": None, "not": ""}
    a = build(ws, out=out, review={dec["satir"]: dec})
    r = a.by_key["anket_tarihsiz|A.4.2/2"]
    assert r["sayilir"] and "tarih_dogrulanmali" not in r["flags"] and "tarih doğrulanmalı" not in r["donem_kurali"]
    assert _crit(a, "A.4.2")["od"] == 3


def test_no_period_info_keeps_old_behaviour(tmp_path):
    w = _ws(tmp_path, {"t": (_doc("anket_sonucu"), [_m("A.4.2", "A.4.2/2", "uygula", 3)])}, donem=False)
    a = build(w)
    assert a.by_key["t|A.4.2/2"]["sayilir"] and any("dönem kuralı uygulanmadı" in u for u in a.uyarilar)


# -- döngü -------------------------------------------------------------------------------

def _cycle_ws(tmp_path, alinti):
    return _ws(tmp_path, {
        "usul": (_doc("bolum_kurulu_karari", "2025-03-01"), [_m("B.1.5", "B.1.5/1", "planla", 2, alinti=alinti)]),
        "gozden_2023": (_doc("komisyon_tutanagi", "2023-06-01"), [_m("B.1.5", "B.1.5/2", "uygula", 3)]),
        "iyilestirme_2023": (_doc("bolum_kurulu_karari", "2023-07-01"), [_m("B.1.5", "B.1.5/5", "onlem_al", 4)]),
        "izleme_2023": (_doc("degerlendirme_raporu", "2023-05-01"), [_m("B.1.5", "B.1.5/3", "kontrol_et", 4)]),
        "eski_2019": (_doc("komisyon_tutanagi", "2019-06-01"), [_m("B.1.5", "B.1.5/4", "uygula", 3)]),
    })


def test_cycle_opens_previous_year_links(tmp_path):
    a = build(_cycle_ws(tmp_path, "Müfredat her 4 yılda bir bölüm kurulunca gözden geçirilir."))
    c = _crit(a, "B.1.5")
    assert c["dongu"]["yil"] == 4 and c["dongu"]["satir"] == "usul|B.1.5/1"
    for k in ("gozden_2023|B.1.5/2", "iyilestirme_2023|B.1.5/5", "izleme_2023|B.1.5/3"):
        assert a.by_key[k]["sayilir"] and "dongu_halkasi" in a.by_key[k]["flags"], k
    old = a.by_key["eski_2019|B.1.5/4"]                 # pencere dışı (2025-4 = 2021 ve öncesi)
    assert not old["sayilir"] and "gecmis_kanit" in old["flags"]
    assert c["od"] == 4 and c["dongu_onerisi"] is None
    assert "OD4" in a.by_key["iyilestirme_2023|B.1.5/5"]["vurgu"]


def test_no_cycle_writes_suggestion(tmp_path):
    w = _cycle_ws(tmp_path, "Bölüm kurulu ders planını görüştü.")
    out = tmp_path / "out"
    a, _ = audit(w, out=out)
    c = _crit(a, "B.1.5")
    assert c["dongu"] is None and c["od"] == 2
    assert "Müfredat gözden geçirme döngüsünü tanımlayan bir bölüm kurulu kararı önerilir" in c["dongu_onerisi"]
    g = (out / FILES["gaps"]).read_text(encoding="utf-8")
    assert "## Gözden geçirme döngüleri" in g and "**B.1.5 Programların izlenmesi ve güncellenmesi: öneri.**" in g
    assert "her 4 yılda ya da akreditasyon döngüsünde" in g
    assert len(c["gecmis_kanit"]) == 4


def test_low_confidence_quote_does_not_define_cycle(tmp_path):
    w = _ws(tmp_path, {
        "usul": (_doc("bolum_kurulu_karari", "2025-03-01"),
                 [_m("B.1.5", "B.1.5/1", "planla", 2, alinti="her 4 yılda bir gözden geçirilir", guven="dusuk")]),
        "g": (_doc("komisyon_tutanagi", "2024-06-01"), [_m("B.1.5", "B.1.5/2", "uygula", 3)]),
    })
    a = build(w)
    assert _crit(a, "B.1.5")["dongu"] is None and not a.by_key["g|B.1.5/2"]["sayilir"]
