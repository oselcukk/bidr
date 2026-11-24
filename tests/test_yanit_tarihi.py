"""Form yanıt tablosu / anket sonuç belgesi: belgenin tarihi formun oluşturulma (başlık) tarihi değil yanıt
zaman damgalarıdır; dönemi yanıt aralığı belirler. Sentetik veri, model yok."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from bidr.audit import donem as D
from bidr.identify.catalog import load_catalog
from bidr.identify.dates import DateFinder, response_dates
from bidr.identify.pipeline import identify_text


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


@pytest.fixture(scope="module")
def finder(cat):
    return DateFinder(cat.date_labels, cat.excluded_date_labels)


def _xlsx(tmp_path, header="Zaman damgası", values=None):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Form Yanıtları 1"
    ws.append(["Bölüm Araştırma Hedefleri Anketi (form oluşturma: 12.11.2025)"])
    ws.append([header, "Araştırma alanınız", "2026 hedefiniz"])
    for i, v in enumerate(values or [datetime(2026, 2, 16, 9, 41, 3), datetime(2026, 2, 27, 14, 2, 55),
                                     datetime(2026, 3, 9, 11, 0, 0)]):
        ws.append([v, f"Alan {i}", "Ulusal proje başvurusu"])
    p = tmp_path / "yanitlar.xlsx"
    wb.save(str(p))
    from bidr.ingest.extract import extract_xlsx
    return "\f".join(extract_xlsx(p).pages)


def test_response_dates_from_xlsx_text(tmp_path):
    raw = _xlsx(tmp_path)
    assert response_dates(raw) == [date(2026, 2, 16), date(2026, 2, 27), date(2026, 3, 9)]


@pytest.mark.parametrize("cells,beklenen", [
    (["2026/02/16 9:41:03 ÖS GMT+3", "2026/03/09 11:00:00 ÖÖ GMT+3"], [date(2026, 2, 16), date(2026, 3, 9)]),
    (["16.02.2026 09:41:03", "09.03.2026 11:00:00"], [date(2026, 2, 16), date(2026, 3, 9)]),
    (["2/16/2026 9:41:03", "3/9/2026 11:00:00"], [date(2026, 2, 16), date(2026, 3, 9)]),     # ay önde (ABD)
])
def test_response_dates_formats(cells, beklenen):
    raw = "Zaman damgası\tAd\n" + "\n".join(f"{c}\tx" for c in cells)
    assert response_dates(raw) == beklenen


def test_response_dates_pdf_dump_and_negatives():
    dump = ("Bölüm Araştırma Hedefleri Anketi 12.11.2025\nZaman damgası Araştırma alanınız\n"
            "16.02.2026 09:41:03 Cebir\n27.02.2026 14:02:55 Analiz\n")
    assert response_dates(dump) == [date(2026, 2, 16), date(2026, 2, 27)]
    # yanıt sütunu yok: sıradan tarih sütunu, düz metin
    assert response_dates("Tarih\tKonu\n05.03.2025\tToplantı\n") == []
    assert response_dates("Toplantı 05.03.2025 tarihinde yapıldı.") == []
    # başlık var ama hücreler tarih değil
    assert response_dates("Zaman damgası\tAd\nyok\tx\nbilinmiyor\ty\n") == []


def test_identify_survey_dated_by_responses(tmp_path, cat, finder):
    raw = _xlsx(tmp_path)
    r = identify_text(raw, cat, finder, 2026)
    assert r["tarih"] == "2026-03-09" and r["tarih_kaynagi"] == "yanit_zaman_damgasi"
    assert r["yanit_araligi"] == ["2026-02-16", "2026-03-09"]
    assert r["donem_ici"] is True and r["donem_kaniti"] == "yanit_araligi"
    # önceki yılın raporunda da dönem dışı (yanıtlar 2026)
    assert identify_text(raw, cat, finder, 2025)["donem_ici"] is False
    t = D.doc_time({**r, "donem": 2026})
    assert t["zaman"] == D.ICI and "yanıt zaman damgaları: 2026-02-16 – 2026-03-09" in t["kaynak"]
    row = D.apply_row(D.load_rule(), {**r, "donem": 2026}, r["doc_type"], "kontrol_et")
    assert row["zaman"] == D.ICI and "tarih_dogrulanmali" not in row["flags"]


def test_responses_spanning_years_cover_period(tmp_path, cat, finder):
    raw = _xlsx(tmp_path, header="Timestamp",
                values=[datetime(2025, 12, 20, 10, 0), datetime(2026, 1, 15, 10, 0)])
    for yil in (2025, 2026):
        assert identify_text(raw, cat, finder, yil)["donem_ici"] is True
    assert identify_text(raw, cat, finder, 2024)["donem_ici"] is False


def test_without_response_column_unchanged(tmp_path, cat, finder):
    raw = "Bölüm Araştırma Hedefleri Anketi\nOluşturma tarihi: 12.11.2025\nSoru 1: Alanınız?\n"
    r = identify_text(raw, cat, finder, 2026)
    assert r["tarih"] == "2025-11-12" and r["tarih_kaynagi"] != "yanit_zaman_damgasi"
    assert r["yanit_araligi"] is None
