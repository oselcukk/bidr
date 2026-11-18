"""identify testleri: tamamen sentetik metinler (gerçek belge/kişi yok)."""
from __future__ import annotations

import csv
import json
import textwrap
from pathlib import Path

import pytest

from bidr.common import Workspace
from bidr.identify import versions
from bidr.identify.catalog import UNKNOWN, CatalogError, load_catalog
from bidr.identify.classify import classify
from bidr.identify.dates import DateFinder, academic_terms, term_year
from bidr.identify.pipeline import identify_text, read_inventory, run
from bidr.identify.text import fold, fold_pattern, slug, tr_title


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


@pytest.fixture(scope="module")
def finder(cat):
    return DateFinder(cat.date_labels, cat.excluded_date_labels)


# ------------------------------------------------------------------ sentetik metinler

YAZI = """Evrak Tarih ve Sayısı: 03.03.2025-E.123456
T.C.
ÖRNEK ÜNİVERSİTESİ REKTÖRLÜĞÜ
Fen Fakültesi Dekanlığı
Sayı : E-11111111-100-123456 03.03.2025
Konu : Ders Programı Güncellemesi
DAĞITIM YERLERİNE
İlgi yazı gereği ders programı güncellenmiştir. Bilgilerinize rica ederim.
Bu belge, güvenli elektronik imza ile imzalanmıştır.
"""

EPOSTA = """Outlook
Toplantı Daveti
Kimden Bölüm Sekreterliği <sekreter@ornek.edu.tr>
Tarih 12.05.2025 Pzt 10:00
Kime Öğretim Üyeleri <ogretim@ornek.edu.tr>
Değerli hocalarım, toplantıya katılımınızı rica ederiz.
Yanıtla Tümünü yanıtla İlet
"""

BOLUM_KURULU = """T.C. ÖRNEK ÜNİVERSİTESİ
FEN FAKÜLTESİ ÖRNEK BÖLÜMÜ BAŞKANLIĞI
Toplantı Tarihi: 12.03.2025 Toplantı Sayısı: 2025/04 Oturum Sayısı: 1
BÖLÜM KURULU KARARLARI
Toplantıda Bulunanlar: Bölüm Başkanı, Anabilim Dalı Başkanları
Karar 1: Seçmeli ders önerileri uygun bulunmuştur.
"""

# OCR: işaretler düşmüş, büyük I ile yazılmış, harfler ayrık
TUTANAK_OCR = """GEBZE  TOPLANTI TUTANAGI  TEKNIK
Toplanti No: Katilmasi Gereken Toplam Kisi: Katilim Orani (%):
TOPLANTI YERI TOPLANTI TARIHI BASLAMA SAATI
Bolum Baskanligi 14.10.2025 16.00 17.00
TOPLANTI TURU Kurul Toplantisi Komisyon Toplantisi
KATILIMCI ONAYI AD - SOYAD GOREV
TOPLANTIDA ALINAN KARARLAR SORUMLU TERMIN
Form No:FR-0044 Yayın Tarihi:10.10.2016 Değ.No:2 Değ.Tarihi:24.11.2022
"""

YONERGE = """Doküman No YÖ-0099 Yayın Tarihi 06.12.2017
ÖRNEK ÜNİVERSİTESİ Revizyon Tarihi 18.10.2024
ÖRNEK DEĞİŞİM YÖNERGESİ Revizyon No 2
BİRİNCİ BÖLÜM Amaç, Kapsam, Dayanak
MADDE 1 – Amaç. MADDE 2 – Kapsam. MADDE 3 – Dayanak.
MADDE 4 – Tanımlar. MADDE 5 – Başvuru. MADDE 6 – Yürürlük.
Form No: FR-0356 Yayın Tarihi: 23.11.2017 Değ.No:0 Değ.Tarihi:-
"""

BIDR = """GEBZE TEKNİK ÜNİVERSİTESİ BİRİM İÇ DEĞERLENDİRME RAPORU (BİDR)
Örnek Bölümü Raporu Hazırlayanlar Unvan Ad Soyad
""" + " ".join(f"[A.1.{i % 5 + 1}-{i}-OD3]. Kanıt" for i in range(12)) + """
Form No:FR-0833 Yayın Tarihi:05.08.2025 Değ.No:0 Değ.Tarihi:-
"""

BIDR_SABLON = """GEBZE TEKNİK ÜNİVERSİTESİ BİRİM İÇ DEĞERLENDİRME RAPORU (BİDR)
…………[Birim Adı] Raporu Hazırlayanlar ………[Üye Unvan, Adı Soyadı, eposta adresi, Görevi]
Form No:FR-0833 Yayın Tarihi:05.08.2025 Değ.No:0 Değ.Tarihi:-
"""


# ------------------------------------------------------------------ metin yardımcıları

def test_fold_is_one_to_one():
    s = "İĞÜŞÖÇ ığüşöç Iİ i̇ TOPLANTI TUTANAĞI — Ä"
    f = fold(s)
    assert len(f) == len(s)
    assert fold("TOPLANTI TUTANAĞI") == fold("Toplanti Tutanagi") == "toplanti tutanagi"


def test_fold_pattern_keeps_escapes():
    p = fold_pattern(r"\bbölüm \S+ \d")
    assert p == r"\bbolum\s*\S+\s*\d"


def test_slug_and_title():
    assert slug("Bölüm Kurulu Kararları 2025/04") == "Bolum-Kurulu-Kararlari-2025-04"
    assert tr_title("BÖLÜM KURULU KARARLARI") == "Bölüm Kurulu Kararları"
    assert tr_title("Zaten Karışık") == "Zaten Karışık"


# ------------------------------------------------------------------ katalog

def test_catalog_loads_and_validates(cat):
    assert "toplanti_tutanagi" in cat.names and UNKNOWN not in cat.names
    assert cat.code_info("FR-0044")[0] == "toplanti_tutanagi"
    assert cat.code_info("YÖ-0099")[0] == "yonerge"  # önek kuralı


def test_catalog_rejects_bad_region(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("turler:\n  - ad: x\n    imzalar:\n      - {id: a, bolge: yok, desen: 'a'}\n",
                 encoding="utf-8")
    with pytest.raises(CatalogError):
        load_catalog(p, institution_files=[])


def test_institution_code_to_unknown_type_rejected(tmp_path):
    c = tmp_path / "c.yaml"
    c.write_text("turler:\n  - ad: x\n    imzalar:\n      - {id: a, desen: 'a'}\n", encoding="utf-8")
    i = tmp_path / "k.yaml"
    i.write_text("kurum: k\nonekler: {fr: FR}\nkodlar:\n  FR-0001: {tur: olmayan}\n", encoding="utf-8")
    with pytest.raises(CatalogError):
        load_catalog(c, institution_files=[i])


def test_catalog_has_no_personal_data():
    raw = (Path(__file__).resolve().parents[1] / "bidr" / "data" / "doc_types.yaml").read_text("utf-8")
    assert "@" not in raw.replace("[a-z0-9._-]+ ?@ ?", "")  # e-posta adresi yok (desen hariç)


# ------------------------------------------------------------------ sınıflandırma

@pytest.mark.parametrize("text,expected", [
    (YAZI, "resmi_yazi"),
    (EPOSTA, "e_posta"),
    (BOLUM_KURULU, "bolum_kurulu_karari"),
    (TUTANAK_OCR, "toplanti_tutanagi"),
    (YONERGE, "yonerge"),
    (BIDR, "bidr_raporu"),
    (BIDR_SABLON, "bidr_sablonu"),
])
def test_classify_types(cat, text, expected):
    r = classify(text, cat)
    assert r["doc_type"] == expected, (r["doc_type"], r["kanitlar"])
    assert r["kanitlar"] and all("alinti" in e and "kural" in e for e in r["kanitlar"])
    assert 0 < r["guven"] <= 1


def test_evidence_quotes_original_text(cat):
    r = classify(TUTANAK_OCR, cat)
    kinds = {e["tur"] for e in r["kanitlar"]}
    assert "form_kodu" in kinds
    q = [e["alinti"] for e in r["kanitlar"] if e["kural"].endswith("baslik_tutanak")][0]
    assert "TUTANAGI" in q  # alıntı özgün yazımla


def test_form_code_labeled_vs_mentioned(cat):
    r = classify(TUTANAK_OCR, cat)
    assert r["form_kodu"] == "FR-0044"
    body = "Bu süreçte FR-0820 numaralı form kullanılır. " * 3
    r2 = classify(body, cat)
    assert r2["form_kodu"] is None and "FR-0820" in r2["anilan_form_kodlari"]


def test_unknown_cases(cat):
    assert classify("", cat)["neden"] == "metin_yok"
    r = classify("Lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod " * 5, cat)
    assert r["doc_type"] == UNKNOWN and r["neden"] == "kural_tutmadi"
    zipish = "PK\x03\x04 [Content_Types].xml" + "\x00\x01" * 50
    assert classify(zipish, cat)["neden"] == "ikili_icerik"


# ------------------------------------------------------------------ tarihler

def test_dates_exclude_form_header_and_print_stamp(cat, finder):
    r = identify_text(TUTANAK_OCR, cat, finder, period=2025)
    assert r["tarih"] == "2025-10-14"
    assert "2016-10-10" not in r["tarihler"] and "2022-11-24" not in r["tarihler"]
    assert r["donem_ici"] is True and r["donem_kaniti"] == "tarih"
    stamp = "29.01.2026 15:34 Outlook Konu\nKimden a@b.c Kime x@y.z Tarih 18.09.2025 Per 15:28\n"
    r2 = identify_text(stamp, cat, finder)
    assert r2["tarih"] == "2025-09-18"
    assert "2026-01-29" not in r2["tarihler"]


def test_labeled_date_wins(cat, finder):
    r = identify_text(BOLUM_KURULU, cat, finder, period=2024)
    assert r["tarih"] == "2025-03-12" and r["tarih_kaynagi"].startswith("etiket:")
    assert r["donem_ici"] is False


def test_yonerge_uses_revision_date(cat, finder):
    r = identify_text(YONERGE, cat, finder)
    assert r["tarih"] == "2024-10-18"


def test_academic_terms():
    f = fold("2024-2025 Bahar dönemi ve 2025–2026 Güz yarıyılı")
    t = academic_terms(f)
    assert t == ["2024-2025 bahar", "2025-2026 guz"]
    assert term_year(t[0]) == 2025 and term_year(t[1]) == 2025


def test_us_date_format(finder):
    f = fold("Tarih: 11/18/2025")
    assert [x.d.isoformat() for x in finder.content_dates(f)] == ["2025-11-18"]


# ------------------------------------------------------------------ başlık / ad

def test_title_and_working_name(cat, finder):
    r = identify_text(YAZI, cat, finder)
    assert r["baslik"] == "Ders Programı Güncellemesi"
    assert r["calisma_adi"] == "2025-03-03_Yazi-Ders-Programi-Guncellemesi"
    r = identify_text(BOLUM_KURULU, cat, finder)
    assert r["calisma_adi"].startswith("2025-03-12_Bolum-Kurulu-Kararlari")


# ------------------------------------------------------------------ sürüm grupları

LONG_A = ("Bölüm kurulu toplantısında müfredat değişikliği görüşüldü. Kuantum optik seçmeli dersi "
          "açılmasına, laboratuvar güvenliği eğitiminin zorunlu tutulmasına, staj süresinin uzatılmasına "
          "karar verildi. Paydaş görüşleri değerlendirildi. ") * 6
LONG_B = ("Fakülte yönetim kurulu bütçe planlamasını görüştü. Kütüphane abonelikleri yenilenecek, "
          "yeni araştırma merkezi binası için kaynak ayrılacak, öğrenci kulüplerine destek "
          "sağlanacak. Sosyal tesis onarımı onaylandı. ") * 6


def test_versions_link_draft_and_scan():
    scan = LONG_A.replace("ü", "u").replace("ı", "i")  # OCR benzeri bozulma
    texts = {k: fold(v) for k, v in {"a1": LONG_A, "a2": scan, "b1": LONG_B,
                                      "x1": "alfa beta gama " * 40, "x2": "delta epsilon zeta " * 40,
                                      "x3": "eta teta iota " * 40}.items()}
    g = versions.group(texts, {"a1": "2025-01-01", "a2": "2025-01-01"})
    assert g["a1"]["grup"] == g["a2"]["grup"] and g["a1"]["uyeler"] == ["a2"]
    assert "b1" not in g


def test_versions_respect_date_conflict():
    texts = {k: fold(LONG_A) + f" ek{k}" for k in ("p", "q")}
    texts.update({f"f{i}": fold(f"dolgu metni numara {i} ") * 30 for i in range(4)})
    g = versions.group(texts, {"p": "2025-01-01", "q": "2025-02-01"})
    assert g["p"]["grup"] == g["q"]["grup"]  # neredeyse aynı (>=0.95): bağlanır
    texts["q"] = fold(LONG_A[:400] + LONG_B)
    g = versions.group(texts, {"p": "2025-01-01", "q": "2025-02-01"})
    assert "p" not in g


# ------------------------------------------------------------------ uçtan uca

def _ws(tmp_path: Path, docs: dict[str, tuple[str, str]]) -> Workspace:
    """docs: doc_id -> (yanıltıcı dosya yolu, metin)."""
    ws = Workspace(tmp_path / "ws").ensure()
    cols = ["doc_id", "sha256", "rel_path", "ext", "size", "pages", "chars",
            "method", "status", "dup_of", "error"]
    with open(ws.inventory, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for did, (path, text) in docs.items():
            ws.text_path(did).write_text(text, encoding="utf-8")
            w.writerow({"doc_id": did, "sha256": did * 4, "rel_path": path, "ext": Path(path).suffix,
                        "size": len(text), "pages": 1, "chars": len(text), "method": "pdftotext",
                        "status": "ok", "dup_of": "", "error": ""})
        # birebir kopya satırı: atlanmalı
        w.writerow({"doc_id": "1111111111111111", "rel_path": "kopya/Senato Kararı.pdf",
                    "dup_of": "x.pdf", "status": "ok"})
    return ws


def test_pipeline_uses_content_not_filename(tmp_path):
    ws = _ws(tmp_path, {
        "1111111111111111": ("A.1.2 Senato Kararı.pdf", EPOSTA),            # ad yanıltıcı
        "2222222222222222": ("Bölüm Kurulu Tutanağı.docx", YAZI),
        "3333333333333333": ("Toplantı Tutanağı.pdf", "kısa"),
    })
    rows = read_inventory(ws)
    # parça grubu ingest'in içerikten kurduğu bağdır (yol/ad değil)
    assert all(set(r) <= {"doc_id", "status", "method", "pages", "parca_grubu", "parca_sira"} for r in rows)
    recs = run(ws.root, period=2025, write_report=True, log=lambda m: None)
    by = {r["doc_id"]: r for r in recs}
    assert by["1111111111111111"]["doc_type"] == "e_posta"
    assert by["2222222222222222"]["doc_type"] == "resmi_yazi"
    assert by["3333333333333333"]["doc_type"] == UNKNOWN
    out = [json.loads(l) for l in ws.documents.read_text("utf-8").splitlines()]
    assert len(out) == 3
    dump = ws.documents.read_text("utf-8")
    assert "Senato Kararı" not in dump and "Tutanağı.docx" not in dump  # yol/ad sızmaz
    required = {"doc_id", "doc_type", "doc_type_etiket", "guven", "kanitlar", "form_kodu",
                "tarih", "tarihler", "donem_ici", "baslik", "calisma_adi", "surum_grubu"}
    assert required <= set(out[0])
    assert len({r["calisma_adi"] for r in out}) == 3
    assert (ws.root / "identify-report.md").exists()


def test_cli_registered():
    from bidr.cli import build_parser

    args = build_parser().parse_args(["identify", "--workspace", "x", "--period", "2025"])
    assert args.period == 2025 and callable(args.func)
