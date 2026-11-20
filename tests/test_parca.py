"""Birleşik/derleme belge: parça sınırları, parça tarihi, dönem kuralının eşleşme başına parça
tarihini kullanması, sayfa başı doküman kodu ve parça adı adımının hatta varsayılan olması.
Tamamen sentetik metinler (gerçek belge/kişi yok); model yok."""
from __future__ import annotations

import json

import pytest

from bidr.audit import donem as D
from bidr.audit.run import build
from bidr.identify.catalog import load_catalog
from bidr.identify.dates import DateFinder
from bidr.identify.parca import header_date, page_code, part_ranges, part_view, quote_page
from bidr.identify.pipeline import identify_text

YIL = 2025

# e-posta (2025) + 2020 tarihli resmî yazı + 2025 tarihli resmî yazı, tek PDF'te
EPOSTA = ("Örnek Haber Hakkında\nKimden Örnek Birim <birim@example.org>\nTarih 27.11.2025 14:59\n"
          "Kime Bölüm Sekreterliği\nMerhaba, fakülte haberi ana sayfamızda yayınlanmıştır. Haberi birim "
          "sayfasındaki haberler alanına ekleyebilir misiniz? İyi çalışmalar dileriz.")
YAZI_2020 = ("Evrak Tarih ve Sayısı: 18.09.2020-E.10001\nT.C.\nÖRNEK ÜNİVERSİTESİ REKTÖRLÜĞÜ\n"
             "Sayı : 1000-710.01\nKonu : Web Sayfası Güncelleme İşlemleri\nBİLGİ İŞLEM DAİRESİNE\n"
             "İlgi yazınız gereği bölüm web sorumluları aşağıdaki şekilde belirlenmiştir. Bilgilerinizi "
             "ve gereğini rica ederim.")
YAZI_2025 = ("Evrak Tarih ve Sayısı: 04.12.2025-E.20002\nT.C.\nÖRNEK ÜNİVERSİTESİ REKTÖRLÜĞÜ\n"
             "Sayı : E-1000-050.99\nKonu : Akademik Genel Kurul\nDAĞITIM YERLERİNE\n"
             "Fakültemiz akademik genel kurul toplantısı 15 Aralık 2025 Pazartesi günü yapılacaktır. "
             "Bölümünüz öğretim üyelerine duyurulmasını rica ederim.")
BIRLESIK = "\f".join([EPOSTA, YAZI_2020, YAZI_2025])
Q_2020 = "İlgi yazınız gereği bölüm web sorumluları aşağıdaki şekilde belirlenmiştir."
Q_2025 = "Fakültemiz akademik genel kurul toplantısı 15 Aralık 2025 Pazartesi günü yapılacaktır."
Q_EPOSTA = "Haberi birim sayfasındaki haberler alanına ekleyebilir misiniz?"

# aynı EBYS yazısının iki sayfası: her sayfada aynı damga, yeni parça açılmaz
TEK_YAZI = (YAZI_2025 + "\f" + "Evrak Tarih ve Sayısı: 04.12.2025-E.20002\nToplantıya katılım "
            "zorunludur ve fakültemiz akademik genel kurul toplantısı gündemi ektedir.")


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


@pytest.fixture(scope="module")
def finder(cat):
    return DateFinder(cat.date_labels, cat.excluded_date_labels)


# -- doküman kodu --------------------------------------------------------------------------

@pytest.mark.parametrize("head,code", [
    ("Doküman No YÖ-0087 ÖRNEK ÜNİVERSİTESİ STAJ YÖNERGESİ", "yo87"),
    ("Form No: FR-0356 Yayın Tarihi 01.01.2020", "fr356"),
    ("ÖR-0101 BÖLÜM KURULU KARARI", "or101"),                                # tireli, sıfır dolgulu
    ("Dok. No: CH TL 0273 İlk Yayın Tarihi 10.07.2019", "tl273"),
    ("Kimya Bölüm Başkanlığına, 2024-2025 Bahar dönemi ders anketleri", None),  # "na 2024"
    ("Toplantı No: 2023-01 Katılması Gereken 5", None),                       # "no 2023"
    ("Proje No: 125F399 yürütücü", None),
    ("ME 107 İngilizce Güz zorunlu", None),                                   # ders kodu
    ("14.08.2025 tarih ve 2025/06-03 sayılı fakülte kurulu kararı", None),    # "ve 2025"
    ("FR-0080 Staj Anketi FR-0142 Memnuniyet Anketi FR-0185 Değerlendirme", None),  # form listesi
])
def test_page_code_only_in_header_context(head, code):
    assert page_code(head + " gövde metni devam eder.") == code


# -- parça sınırları ve parça tarihi ---------------------------------------------------------

def test_header_date():
    assert header_date(YAZI_2020) == "2020-09-18"
    assert header_date(EPOSTA) == "2025-11-27"
    assert header_date("Sıradan bir sayfa, 12.03.2024 tarihinde yazıldı.") is None


def test_parts_of_combined_pdf_and_dates(cat, finder):
    pages = BIRLESIK.split("\f")
    assert [(a, b) for a, b, _ in part_ranges(pages)] == [(0, 0), (1, 1), (2, 2)]
    r = identify_text(BIRLESIK, cat, finder, period=YIL)
    ps = r["parcalar"]
    assert [p["sayfa"] for p in ps] == [[1, 1], [2, 2], [3, 3]]
    assert [p["tarih"] for p in ps] == ["2025-11-27", "2020-09-18", "2025-12-04"]
    assert [p["donem_ici"] for p in ps] == [True, False, True]
    assert all(p["emin"] for p in ps)
    assert r["tarih"] == "2025-11-27"                     # belge düzeyi tarih değişmez


def test_same_ebys_stamp_is_one_part(cat, finder):
    assert len(part_ranges(TEK_YAZI.split("\f"))) == 1
    assert identify_text(TEK_YAZI, cat, finder, period=YIL)["parcalar"] == []
    assert identify_text(EPOSTA, cat, finder, period=YIL)["parcalar"] == []


def test_quote_page():
    assert quote_page(BIRLESIK, Q_EPOSTA) == 0
    assert quote_page(BIRLESIK, Q_2020) == 1
    assert quote_page(BIRLESIK, Q_2025) == 2
    assert quote_page(BIRLESIK, "metinde olmayan bir cümle burada yazıyor") is None


# -- dönem kuralı eşleşme başına parça tarihiyle ----------------------------------------------

def _doc(cat, finder):
    r = identify_text(BIRLESIK, cat, finder, period=YIL)
    r.pop("_folded", None)
    return {**r, "doc_type": "resmi_yazi"}


def test_rule_uses_part_date(cat, finder):
    rule = D.load_rule()
    doc = _doc(cat, finder)
    # belge tarihiyle 2020 yazısı dönem içi sayılırdı
    assert D.apply_row(rule, doc, "resmi_yazi", "uygula")["zaman"] == D.ICI
    pv = part_view(doc, Q_2020, BIRLESIK)
    r = D.apply_row(rule, doc, "resmi_yazi", "uygula", parca=pv)
    assert (r["zaman"], r["yil"], r["sayilir"]) == (D.ONCE, 2020, False) and "gecmis_kanit" in r["flags"]
    assert r["kaynak"].startswith("parça s. 2")
    r = D.apply_row(rule, doc, "resmi_yazi", "uygula", parca=part_view(doc, Q_2025, BIRLESIK))
    assert (r["zaman"], r["sayilir"]) == (D.ICI, True) and "tarih_dogrulanmali" not in r["flags"]
    # parçasız belge ya da metin yok: değişiklik yok
    assert part_view({**doc, "parcalar": []}, Q_2020, BIRLESIK) is None
    assert part_view(doc, Q_2020, None) is None


def test_uncertain_part_keeps_doc_date_with_flag(cat, finder):
    rule = D.load_rule()
    doc = _doc(cat, finder)
    ps = [dict(p) for p in doc["parcalar"]]
    ps[1].update(tarih=None, tarih_kaynagi=None, tarihler=[], emin=False)        # parçada tarih yok
    doc2 = {**doc, "parcalar": ps}
    pv = part_view(doc2, Q_2020, BIRLESIK)
    assert pv["dogrulanmali"] and pv["alanlar"] == {} and "tarih yok" in pv["not"]
    r = D.apply_row(rule, doc2, "resmi_yazi", "uygula", parca=pv)
    assert r["zaman"] == D.ICI and "tarih_dogrulanmali" in r["flags"] and "belge tarihi" in r["not"]
    # alıntının parçası bulunamadı
    pv = part_view(doc, "metinde olmayan bir cümle burada yazıyor", BIRLESIK)
    assert pv["dogrulanmali"] and pv["sayfa"] is None
    # etiketsiz tarih, sınır yalnız "konu değişti" sezgisi: emin değil; belge tarihiyle aynıysa değişiklik yok
    ps[1].update(tarih=doc["tarih"], tarih_kaynagi="bas_ilk", emin=False, sinir="ingest")
    assert part_view({**doc, "parcalar": ps}, Q_2020, BIRLESIK) is None


def test_audit_row_takes_quote_part_date(tmp_path, cat, finder):
    ws = tmp_path / "ws"
    (ws / "text").mkdir(parents=True)
    (ws / "text" / "d_bir.txt").write_text(BIRLESIK, encoding="utf-8")
    doc = {"doc_id": "d_bir", "calisma_adi": "d_bir", **_doc(cat, finder)}
    (ws / "documents.jsonl").write_text(json.dumps(doc, ensure_ascii=False) + "\n", encoding="utf-8")

    def m(yuva, q):
        return {"olcut": "A.1.1", "yuva": yuva, "asama": "uygula", "od_onerisi": 3, "alinti": q,
                "gerekce": "g", "guven": "yuksek", "denetim": {"red": [], "isaret": []}, "od_kabul": 3,
                "kabul": True}
    rec = {"doc_id": "d_bir", "durum": "ok", "asama": "ince", "karar": "olcut_var",
           "eslesmeler": [m("A.1.1/1", Q_2020), m("A.1.1/2", Q_2025)]}
    (ws / "decisions.jsonl").write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")
    rows = {r["yuva"]: r for r in build(ws).rows}
    assert rows["A.1.1/1"]["donem_zaman"] == D.ONCE and not rows["A.1.1/1"]["sayilir"]
    assert "gecmis_kanit" in rows["A.1.1/1"]["flags"]
    assert rows["A.1.1/2"]["donem_zaman"] == D.ICI and rows["A.1.1/2"]["sayilir"]


# -- parça adı adımı hatta varsayılan ----------------------------------------------------------

from test_file import env  # noqa: E402,F401  (fixture)


def _make_combined(ws):
    """env'deki d_karar'ı kodsuz birleşik belgeye çevirir: kabul edilmiş alıntılar iki ayrı yazıdan."""
    from test_file import _m
    (ws / "text" / "d_karar.txt").write_text(BIRLESIK, encoding="utf-8")
    recs = [json.loads(x) for x in (ws / "decisions.jsonl").read_text(encoding="utf-8").splitlines()]
    for r in recs:
        if r["doc_id"] == "d_karar":
            r["eslesmeler"] = [_m("A.1.1", "A.1.1/2", "uygula", 3, Q_2020, BIRLESIK),
                               _m("B.1.1", "B.1.1/3", "uygula", 3, Q_2025, BIRLESIK)]
            r["ince"] = {"kanit_adi": {"oneri": "Akademik Genel Kurul Duyurusu",
                                       "ad": "Akademik Genel Kurul Duyurusu", "durum": "kabul", "red": []}}
    (ws / "decisions.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs),
                                        encoding="utf-8")


def _name_check(ws):
    from bidr.common import Workspace
    from bidr.pipeline.checks import Ctx, name_tamam
    from bidr.pipeline.state import stage
    return name_tamam(Ctx(Workspace(ws), {}, lambda s: s, stage("name")))


def test_part_naming_is_default_and_finishes(env):
    from bidr.common import Workspace, read_jsonl
    from bidr.name import run as NR
    from bidr.name.resolve import NAMES, decision_name, upsert
    ws, _ = env
    _make_combined(ws)
    recs = NR.decisions_view(Workspace(ws))
    assert NR.derleme_kaniti("Akademik Genel Kurul Duyurusu", BIRLESIK,
                             {"A.1.1/2": Q_2020, "B.1.1/3": Q_2025})
    assert not NR.derleme_kaniti("x", BIRLESIK, {"B.1.1/3": Q_2025})    # tek parçadan alıntı
    # diğer belgelere model adı ver: yalnız parça adı bekleyen kalsın
    upsert(ws / NAMES, [{"doc_id": d, "kaynak": "model", "ad": "Örnek Belge Adı Burada",
                         "gorev": {"name_evidence": NR.task_version()}, "derleme": False}
                        for d in NR.eligible(recs) if d != "d_karar"])
    assert NR.parts_pending(Workspace(ws), recs, {}, ["d_karar"]) == ["d_karar"]
    ck = _name_check(ws)
    assert not ck.bitti and "parça adı" in ck.neden and ck.ilerleme["parca_adi_bekleyen"] == 1
    st = NR.prepare(ws)                                                 # --parca varsayılan
    assert st["derleme"] == 1 and st["yeni"] == 1
    pkg = json.loads((ws / "work" / "name" / "d_karar.json").read_text(encoding="utf-8"))
    assert "evet: 3 parça" in pkg["istem"]
    assert NR.prepare(ws, parca=False)["derleme"] == 0
    (ws / "work" / "name" / "d_karar.out.json").write_text(json.dumps({
        "kanit_adi": "Akademik Genel Kurul Duyurusu", "gerekce": "x",
        "parca_adlari": {"A.1.1/2": "Web Sorumluları Bildirim Yazısı"}}, ensure_ascii=False), encoding="utf-8")
    st = NR.apply(ws, model="test", only=["d_karar"])
    assert st["islenen"] == 1 and st["parca"]["d_karar"] == {"A.1.1/2": "Web Sorumluları Bildirim Yazısı"}
    rec = {r["doc_id"]: r for r in read_jsonl(ws / NAMES)}["d_karar"]
    assert rec["derleme"] is True
    ck = _name_check(ws)
    assert ck.bitti and ck.ilerleme["parca_adi_bekleyen"] == 0
