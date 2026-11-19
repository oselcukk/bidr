"""Dönem kararında tarih kaynakları (kör test 2026-11-20): aralık bitiş tarihleri, açık yıl
ifadeleri, dönem sonrası güncellenmiş sayfalar, plan yürürlük aralığı. Sentetik veri, model yok."""
from __future__ import annotations

from datetime import date

import pytest

from bidr.audit import donem as D
from bidr.identify.catalog import load_catalog
from bidr.identify.dates import (DateFinder, date_ranges, find_dates, plan_span, update_dates,
                                 year_phrases)
from bidr.identify.pipeline import identify_text
from bidr.identify.text import fold

YIL = 2025


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


@pytest.fixture(scope="module")
def finder(cat):
    return DateFinder(cat.date_labels, cat.excluded_date_labels)


@pytest.fixture(scope="module")
def rule():
    return D.load_rule()


def _f(s: str) -> str:
    return fold(" ".join(s.split()))


# -- dates.py ---------------------------------------------------------------------------------

PROJE_TABLOSU = """Örnek Bölümü Devam Eden Projeler
No Yürütücü Başlama Tarihi Bitiş Tarihi Program
101 Proje A 01.03.2025 | 01.03.2027 | 1001
102 Proje B 15.04.2024 | 15.04.2026 | 1001
103 Proje C 01.12.2024 - 01.06.2027 2218
104 Proje D 11xx2 01.05.2026 | 1002
"""


def test_date_ranges_pairs_and_end_label():
    f = _f(PROJE_TABLOSU)
    pairs = [(a.d.isoformat() if a else None, b.d.isoformat()) for a, b in date_ranges(f)]
    assert ("2025-03-01", "2027-03-01") in pairs and ("2024-04-15", "2026-04-15") in pairs
    assert ("2024-12-01", "2027-06-01") in pairs
    assert all(e != "2026-05-01" or s is None for s, e in pairs)   # eşi okunmamış tarih çift değil
    lab = _f("Sözleşme Başlangıç: 01.02.2025 Konu: örnek Bitiş tarihi: 31.01.2027")
    assert (None, "2027-01-31") in [(a and a.d.isoformat(), b.d.isoformat()) for a, b in date_ranges(lab)]
    # virgülle sıralanan tarihler aralık değildir
    assert date_ranges(_f("Seminerler 07.03.2025, 21.03.2025 ve 18.04.2025 tarihlerinde")) == []


def test_primary_ignores_range_end(finder):
    # en sık tarih bir bitiş tarihi: birincil tarih olamaz
    t = _f("Projeler Listesi 01.02.2025 | 31.12.2026 01.03.2025 | 31.12.2026 01.04.2025 | 31.12.2026")
    d, src, _ = finder.primary(t, [], finder.content_dates(t))
    assert d == date(2025, 2, 1), (d, src)


def test_plan_span_and_primary_skips_far_past_date(finder):
    head = "ÖRNEK ÜNİVERSİTESİ 2022-2026 Stratejik Planı " + "giriş metni " * 140
    body = "Üniversitemiz 4 Kasım 2014 tarihinde kurulmuştur. Plan çalışmaları 15.06.2020 tarihinde başladı."
    t = _f(head + body)
    assert plan_span(t) == (2022, 2026)
    d, src, _ = finder.primary(t, [], finder.content_dates(t))
    assert d == date(2020, 6, 15) and src == "metin_ilk"
    assert plan_span(_f("Erasmus+ 2021-2027 program dönemi anlaşmaları")) is None
    assert plan_span(_f("2024-2025 Akademik Yılı ders planı")) is None   # akademik yıl


def test_year_phrases():
    t = _f("Tablo: 2025 yılı içerisinde bölüm öğretim üyelerine ait 3 adet ödül. "
           "2025 yılında 7 yayın. Bölüm 1994 yılında kuruldu.")
    assert year_phrases(t) == [2025, 1994]
    assert year_phrases(_f("2025-2026 yılları; 12.03.2025")) == []


def test_update_stamp_is_not_content_date(finder):
    t = _f("Örnek Bölümü Kurul ve Komisyonları Bölüm Kurulu üyeleri ... Son güncelleme: 11 Kasım 2026")
    assert update_dates(t) == [date(2026, 11, 11)]
    assert finder.content_dates(t) == []
    assert find_dates(t)                       # tarih okunuyor, yalnız içerik tarihi sayılmıyor


def test_identify_text_records_new_fields(cat, finder):
    r = identify_text(PROJE_TABLOSU + "\nSon güncelleme: 02.11.2026\n2025 yılı içerisinde başlayan projeler",
                      cat, finder, YIL)
    assert ["2025-03-01", "2027-03-01"] in r["tarih_araliklari"]
    assert r["yil_ifadeleri"] == [2025] and r["guncelleme_tarihi"] == "2026-11-02"
    assert r["yururluk_araligi"] is None


# -- donem.py ---------------------------------------------------------------------------------

def _doc(tur, tarih=None, **kw):
    d = {"doc_type": tur, "tarih": tarih, "donem": YIL, "akademik_donem": [],
         "donem_ici": (int(tarih[:4]) == YIL) if tarih else None}
    d.update(kw)
    return d


def test_project_end_dates_do_not_make_event_uncertain(rule):
    d = _doc("proje_listesi", "2025-03-01",
             tarihler=["2024-04-15", "2025-03-01", "2026-04-15", "2027-03-01"],
             tarih_araliklari=[["2025-03-01", "2027-03-01"], ["2024-04-15", "2026-04-15"]])
    r = D.apply_row(rule, d, "proje_listesi", "uygula")
    assert r["zaman"] == D.ICI and r["sayilir"] and r["flags"] == [] and r["not"] == ""
    # aralık bilgisi yoksa eski davranış: ileri tarih olay tarihini belirsiz yapar
    d0 = {k: v for k, v in d.items() if k != "tarih_araliklari"}
    assert "tarih_dogrulanmali" in D.apply_row(rule, d0, "proje_listesi", "uygula")["flags"]


def test_range_table_ignores_unpaired_future_dates(rule):
    # aralık tablosu (≥3 çift): eşi okunamamış ileri tarih (OCR) bitiş sayılır
    ranges = [["2024-04-15", "2026-04-15"], ["2024-12-01", "2027-06-01"], ["2025-03-01", "2027-03-01"]]
    d = _doc("bilinmiyor", "2025-03-01", tarih_araliklari=ranges,
             tarihler=sorted({x for p in ranges for x in p} | {"2026-05-01"}))
    r = D.apply_row(rule, d, "bilinmiyor", "uygula")
    assert r["sayilir"] and r["zaman"] == D.ICI
    # dönem sonrası BAŞLANGIÇ (2026'da başlayan proje) hâlâ belirsizliktir
    d2 = {**d, "tarih_araliklari": ranges + [["2026-02-01", "2028-02-01"]],
          "tarihler": d["tarihler"] + ["2026-02-01", "2028-02-01"]}
    assert "tarih_dogrulanmali" in D.apply_row(rule, d2, "bilinmiyor", "uygula")["flags"]


def test_range_start_in_period_sets_event_year(rule):
    d = _doc("proje_listesi", "2018-11-01", tarihler=["2018-11-01", "2021-02-22", "2025-03-27", "2026-03-27"],
             tarih_araliklari=[["2018-11-01", "2021-02-22"], ["2025-03-27", "2026-03-27"]])
    r = D.apply_row(rule, d, "proje_listesi", "uygula")
    assert r["zaman"] == D.ICI and r["sayilir"] and "aralık başlangıcı (2025)" in r["kaynak"]
    # etiketli tarih (toplantı tarihi) olayın tarihidir; aralık başlangıcı onu değiştirmez
    lab = {**d, "tarih_kaynagi": "etiket:toplanti tarihi"}
    assert D.apply_row(rule, lab, "proje_listesi", "uygula")["zaman"] == D.ONCE


def test_year_phrase_is_date_source(rule):
    d = _doc("stratejik_plan_izleme", yil_ifadeleri=[2025])
    r = D.apply_row(rule, d, "stratejik_plan_izleme", "kontrol_et")
    assert r["zaman"] == D.ICI and r["sayilir"] and "yıl ifadesi" in r["kaynak"]
    later = D.apply_row(rule, _doc("faaliyet_raporu", yil_ifadeleri=[2026]), "faaliyet_raporu", "uygula")
    assert later["zaman"] == D.SONRA and "donem_sonrasi" in later["flags"]
    # yalnız geçmiş yıl ifadesi ("1994 yılında kuruldu") belgenin tarihi değil
    past = D.apply_row(rule, _doc("faaliyet_raporu", yil_ifadeleri=[1994]), "faaliyet_raporu", "uygula")
    assert past["zaman"] == D.BILINMIYOR and "tarih_dogrulanmali" in past["flags"]
    # metin içi tarih varsa yıl ifadesi kullanılmaz
    dated = _doc("faaliyet_raporu", "2024-05-01", yil_ifadeleri=[2025])
    assert D.apply_row(rule, dated, "faaliyet_raporu", "uygula")["zaman"] == D.ONCE


def test_page_updated_after_period_is_not_od3_basis(rule):
    page = _doc("gorev_dagilimi", guncelleme_tarihi="2026-11-11")
    up = D.apply_row(rule, page, "gorev_dagilimi", "uygula")
    assert not up["sayilir"] and {"tarih_dogrulanmali", "sayfa_donem_sonrasi"} <= set(up["flags"])
    assert "2026-11-11" in up["not"]
    pl = D.apply_row(rule, page, "gorev_dagilimi", "planla")         # tanım: güncellik uyarısıyla
    assert pl["sayilir"] and {"guncellik_dogrulanmali", "sayfa_donem_sonrasi"} <= set(pl["flags"])
    web = D.apply_row(rule, _doc("web_sayfasi", guncelleme_tarihi="2026-07-06"), "web_sayfasi", "kontrol_et")
    assert not web["sayilir"] and "sayfa_donem_sonrasi" in web["flags"]
    # içerik rapor yılını açıkça gösteriyorsa kanıttır
    ok = D.apply_row(rule, {**page, "yil_ifadeleri": [2025]}, "gorev_dagilimi", "uygula")
    assert ok["sayilir"] and "sayfa_donem_sonrasi" not in ok["flags"]
    ok2 = D.apply_row(rule, _doc("web_sayfasi", "2025-10-01", guncelleme_tarihi="2026-07-06"),
                      "web_sayfasi", "uygula")
    assert ok2["sayilir"] and "sayfa_donem_sonrasi" not in ok2["flags"]
    # damga dönem içindeyse kural devreye girmez
    in_p = D.apply_row(rule, _doc("gorev_dagilimi", guncelleme_tarihi="2025-12-01"), "gorev_dagilimi", "uygula")
    assert in_p["sayilir"] and "sayfa_donem_sonrasi" not in in_p["flags"]
    assert "sayfa dönem sonrası güncellemeli" in D.describe(
        {"donem_sinif": up["sinif"], "donem_zaman": up["zaman"], "donem_yil": up["yil"], "flags": up["flags"]})


def test_plan_in_force_is_in_period(rule):
    # hazırlık tarihi 2020, yürürlük 2022-2026: rapor yılında yürürlükte
    plan = _doc("stratejik_plan", "2020-06-15", yururluk_araligi=[2022, 2026])
    r = D.apply_row(rule, plan, "stratejik_plan", "planla")
    assert r["zaman"] == D.ICI and r["sayilir"] and r["flags"] == [] and "yürürlük aralığı (2022-2026)" in r["kaynak"]
    # eski kayıt: alan yok, başlıktan okunur
    old = _doc("stratejik_plan", "2014-11-04", baslik="2022- 2026 Stratejik Planı")
    assert D.apply_row(rule, old, "stratejik_plan", "planla")["zaman"] == D.ICI
    # aralık rapor yılını kapsamıyor: eski davranış
    past = _doc("stratejik_plan", "2016-01-10", yururluk_araligi=[2017, 2021])
    assert "guncellik_dogrulanmali" in D.apply_row(rule, past, "stratejik_plan", "planla")["flags"]
    # dönem sonrası tarih aralıkla aşılmaz (revizyon/sürüm kuralı geçerli)
    late = _doc("stratejik_plan", "2026-03-01", yururluk_araligi=[2022, 2026])
    assert D.apply_row(rule, late, "stratejik_plan", "planla")["zaman"] == D.SONRA
    # olay belgesinde aralık yürürlük değildir
    ev = _doc("faaliyet_raporu", "2021-03-01", yururluk_araligi=[2021, 2027])
    assert D.apply_row(rule, ev, "faaliyet_raporu", "uygula")["zaman"] == D.ONCE


def test_plan_in_force_wins_version_selection(rule):
    docs = {"a": {**_doc("stratejik_plan", "2020-06-15", yururluk_araligi=[2022, 2026]), "surum_grubu": "g"},
            "b": {**_doc("stratejik_plan", "2016-02-01", yururluk_araligi=[2017, 2021]), "surum_grubu": "g"}}
    st = D.version_status(docs, rule)
    assert st.get("b") == "surum_yururlukten_kalkmis" and "a" not in st
