"""bidr.labels: sentetik klasör ağacı ve sentetik rapor ile."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bidr.cli import main
from bidr.common import read_jsonl
from bidr.labels.build import build
from bidr.labels.parse import ALAN, ALT, ANA, ad_benzerlik, ad_kodu, ad_normal, kanit_satirlari
from bidr.labels.report import paragraf_kanitlari


# --- ad / klasör kodları ---------------------------------------------------

@pytest.mark.parametrize(
    "ad,klasor,olcut,duzey,no,od",
    [
        ("A.1.2 Bölüm Toplantı Tutanakları", False, "A.1.2", ALT, None, None),
        ("[A.1.2-2-OD5]. Kurul Tutanakları", False, "A.1.2", ALT, 2, "OD5"),
        ("[A.2.3- 1-OD4]. Anket", False, "A.2.3", ALT, 1, "OD4"),
        ("A.1.4- 2-OD3]  Paydaş Anketleri", True, "A.1.4", ALT, 2, "OD3"),
        ("[B.3.2.1-OD4]. Görüşme", False, "B.3.2", ALT, 1, "OD4"),
        ("[B1.1-11-OD4]. Müfredat", False, "B.1.1", ALT, 11, "OD4"),
        ("A.1.2.-2-OD5 Örnek", False, "A.1.2", ALT, 2, "OD5"),
        ("[B.3.3-3OD4]Altyapı", False, "B.3.3", ALT, 3, "OD4"),
        ("A.2.1", False, "A.2.1", ALT, None, None),
        ("B1.5", True, "B.1.5", ALT, None, None),
        ("C.3.2", True, "C.3.2", ALT, None, None),
        ("A.1. Liderlik ve Kalite", True, "A.1", ANA, None, None),
        ("A.5. Uluslararasılaşma", True, "A.5", ANA, None, None),
        ("A.Liderlik, Yönetişim ve Kalite", True, "A", ALAN, None, None),
        ("D. Toplumsal Katkı", True, "D", ALAN, None, None),
        ("A", True, "A", ALAN, None, None),
        ("[1.OD4] Yazı", False, None, None, 1, "OD4"),
        ("1.OD4 görevlendirme", False, None, None, 1, "OD4"),
        ("[2-OD4]Başvuru", False, None, None, 2, "OD4"),
    ],
)
def test_ad_kodu(ad, klasor, olcut, duzey, no, od):
    k = ad_kodu(ad, klasor=klasor)
    assert (k.olcut, k.duzey, k.kanit_no, k.od) == (olcut, duzey, no, od)


@pytest.mark.parametrize("ad", ["FR-0833 Rapor", "E-Bülten Maili", "Dekanlık", "Phys 111 25-26",
                                "2025 Yılı Verileri", "Erasmus", "A.1.21 x", "Ders Anketi"])
def test_ad_kodu_yok(ad):
    k = ad_kodu(ad, klasor=True)
    assert k.olcut is None and k.od is None


def test_dosyada_alan_duzeyi_yok():
    # "A" ile başlayan dosya adı alan etiketi sayılmaz; yalnız klasörde
    assert ad_kodu("A Örnek", klasor=False).olcut is None


def test_dort_duzeyli_kod_cozulmez():
    assert ad_kodu("[B.1.4.1-1-OD3] Yönerge").sorun == "dort_duzeyli_kod"


def test_kanit_satirlari_coklu_ve_bicimler():
    s = kanit_satirlari("[4-OD3]. Toplantı Tutanağı [5-OD3]. Personel Daveti")
    assert [(k.kanit_no, k.od, k.kalan) for k in s] == [(4, "OD3", "Toplantı Tutanağı"),
                                                       (5, "OD3", "Personel Daveti")]
    s = kanit_satirlari("2_OD5: A.1.2 Bölüm Toplantı Tutanakları.pdf")
    assert (s[0].olcut, s[0].kanit_no, s[0].od) == (None, 2, "OD5")
    s = kanit_satirlari("[C.1.3-1- OD3] Destek")
    assert (s[0].olcut, s[0].kanit_no, s[0].od) == ("C.1.3", 1, "OD3")
    assert kanit_satirlari("Yönetim modeli (OD3); şeffaflık") == []


def test_ad_normal_ve_benzerlik():
    assert ad_normal("[A.2.3- 1-OD4]. Öğrenci Memnuniyet Anketi.pdf") == "ogrenci memnuniyet anketi"
    assert ad_normal("A.2.3 2025 Rapor (Ocak).xlsx") == ad_normal("A.2.3 2025  Rapor (Ocak).xls")
    assert ad_benzerlik("bolum toplanti tutanagi", "bolum toplanti tutanagi") == 1.0
    assert ad_benzerlik("akademik kurul", "ders programi") < 0.5


# --- rapor bölümleri -------------------------------------------------------

def test_rapor_bolumleri():
    paragraflar = [
        "Örnek Kanıt Gösterimi;",
        "B.1.1.Program Tasarımı ve Onayı",      # şablon örneği: sayılmaz
        "Kanıtlar:",
        "[1-OD3]. Uygulama Örnekleri.pdf",
        "ÖLÇÜTLER VE KANITLAR",
        "Liderlik ve Kalite",                    # otomatik numaralı başlık
        "Kanıtlar:",
        "[1-OD3]. Kurul Kararları",              # → A.1.1 (çıkarım)
        "A.1.2. Liderlik",
        "Örnek Kanıtlar:",
        "Kalite güvencesi [1-OD2]. örnek",       # rubrik: sayılmaz
        "Kanıtlar:",
        "1_OD4: Komisyonlar",
        "2_OD5: A.1.2 Toplantı Tutanakları.pdf",
        "A.2. Misyon ve Stratejik Amaçlar",
        "Kanıtlar: [A.2.1-1-OD3] Misyon",        # → A.2.1 (çıkarım)
        "Kanıtlar: [A.2.1-1-OD3] Misyon",        # tekrar: bir kez
    ]
    ks = paragraf_kanitlari(paragraflar, "r.docx")
    assert [(k.bolum, k.bolum_cikarim, k.kanit_no, k.od) for k in ks] == [
        ("A.1.1", True, 1, "OD3"),
        ("A.1.2", False, 1, "OD4"),
        ("A.1.2", False, 2, "OD5"),
        ("A.2.1", True, 1, "OD3"),
    ]


# --- uçtan uca -------------------------------------------------------------

def _yaz(p: Path, icerik: str | bytes) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(icerik, str):
        icerik = icerik.encode()
    p.write_bytes(icerik)
    return p


def _rapor(p: Path, paragraflar: list[str]) -> None:
    import docx

    d = docx.Document()
    for t in paragraflar:
        d.add_paragraph(t)
    p.parent.mkdir(parents=True, exist_ok=True)
    d.save(str(p))


@pytest.fixture
def agac(tmp_path: Path) -> Path:
    k = tmp_path / "kaynak"
    # Birim 1: alt ölçüt klasörleri, noktasız klasör, ölçütsüz OD kodlu ad, aynı içerik iki yerde
    _yaz(k / "Dekanlik/A.1.3/[1.OD4] Yazı.pdf", "yazi")
    _yaz(k / "Dekanlik/B1.5/Anket Kararları.pdf", "anket")
    _yaz(k / "Dekanlik/A.1.4/Plan Tablosu.xlsx", "plan")
    _yaz(k / "Dekanlik/C.3.1/Plan Tablosu.xlsx", "plan")
    _yaz(k / "Dekanlik/notlar.txt", "etiketsiz")
    _yaz(k / "Dekanlik/.DS_Store", "x")
    _rapor(k / "Dekanlik/FR-0833 Rapor.docx", [
        "ÖLÇÜTLER VE KANITLAR", "A.1.3. Kurumsal dönüşüm", "Kanıtlar:", "[1-OD4]. Yazı",
        "B.1.5. İzleme", "Kanıtlar:", "[2-OD4]. Anket Kararları.pdf", "[3-OD4]. Web Sayfası",
    ])
    # Birim 2: ana ölçüt klasörü + kodlu ad, OD'li klasör
    _yaz(k / "Kimya Bölümü/A.Liderlik/A.1. Liderlik ve Kalite/[A.1.2-2-OD5]. Tutanak.pdf", "tutanak")
    _yaz(k / "Kimya Bölümü/A/A.1.4- 2-OD3]  Paydaş Anketleri/sonuc1.xlsx", "p1")
    _rapor(k / "Kimya Bölümü/FR-0833 Kimya.docx", [
        "A.1. Liderlik ve Kalite", "A.1.2. Liderlik", "Kanıtlar:", "[A.1.2-2-OD5]. Tutanak",
        "A.1.4. İç kalite", "Kanıtlar:", "[A.1.4- 2-OD5] Paydaş Anketleri",
        "B.1.1. Programlar", "Kanıtlar:", "[A.1.2-2-OD5]. Tutanak",
    ])
    return k


def test_build_uctan_uca(agac: Path):
    s = build(agac, takma={"Kimya Bölümü": "Kimya"})
    rows = {r["iz"]["yollar"][0]["yol"]: r for r in s.kayitlar}

    # .DS_Store atlanır; aynı içerik tek kayıt, etiketler birleşir
    assert not any(".DS_Store" in y for y in rows)
    plan = rows["Dekanlik/A.1.4/Plan Tablosu.xlsx"]
    assert plan["kopya_sayisi"] == 2
    assert [e["olcut"] for e in plan["etiketler"]] == ["A.1.4", "C.3.1"]
    assert plan["iz"]["siniflandiriciya_verilmez"] is True

    # ölçütsüz ad kodu: ölçüt klasörden, OD addan; rapor OD'si de eklenir
    yazi = rows["Dekanlik/A.1.3/[1.OD4] Yazı.pdf"]
    (e,) = yazi["etiketler"]
    assert e["olcut"] == "A.1.3" and e["od"] == ["OD4"] and e["kaynaklar"] == ["ad", "klasor", "rapor"]

    # noktasız klasör + rapordan ad eşleşmesi
    anket = rows["Dekanlik/B1.5/Anket Kararları.pdf"]
    assert anket["etiketler"][0]["olcut"] == "B.1.5" and anket["etiketler"][0]["od"] == ["OD4"]

    # etiketsiz dosya da kaydedilir
    assert rows["Dekanlik/notlar.txt"]["etiketli"] is False
    assert rows["Dekanlik/FR-0833 Rapor.docx"]["rapor_dosyasi"] is True

    # ana/alan klasör etiketleri, ince etiket işareti; rapor başka bölümde de gösteriyor
    tut = rows["Kimya Bölümü/A.Liderlik/A.1. Liderlik ve Kalite/[A.1.2-2-OD5]. Tutanak.pdf"]
    by = {e["olcut"]: e for e in tut["etiketler"]}
    assert set(by) == {"A", "A.1", "A.1.2", "B.1.1"}
    assert by["A.1"]["duzey"] == ANA and by["A.1"]["ince_etiket_var"] is True
    assert by["A"]["duzey"] == ALAN
    assert by["A.1.2"]["od"] == ["OD5"] and by["B.1.1"]["kaynaklar"] == ["rapor"]
    assert tut["en_ince_duzey"] == ALT and tut["birimler"] == ["Kimya"]

    # OD'li klasör: rapor kodu klasöre eşlenir; farklı OD çelişki olarak işaretlenir
    p1 = rows["Kimya Bölümü/A/A.1.4- 2-OD3]  Paydaş Anketleri/sonuc1.xlsx"]
    e = {x["olcut"]: x for x in p1["etiketler"]}["A.1.4"]
    assert e["od"] == ["OD3", "OD5"] and e["od_celiski"] is True

    # web bağlantısı gibi dosyası olmayan satır eşleşmeyenlerde
    assert [x.ham for x in s.eslesmeyen] == ["[3-OD4]. Web Sayfası"]


def test_kod_farkli_ad_benzer_eslesmez(tmp_path: Path):
    k = tmp_path / "k"
    _yaz(k / "[A.2.3-2-OD3]. Performans Verileri.docx", "spik")
    _rapor(k / "FR-0833.docx", ["A.2. Misyon", "A.2.3. Performans", "Kanıtlar:",
                                "[A.2.3-1-OD3] Performans Verileri"])
    s = build(k, birim="B")
    assert [x.neden for x in s.eslesmeyen] == ["kod_farkli_ad_benzer"]


def test_etiketsiz_ve_indirilmemis(agac: Path, monkeypatch):
    import bidr.labels.build as b

    gercek = b.Path.stat

    class St:
        def __init__(self, st):
            self.st_size, self.st_flags = st.st_size, b.SF_DATALESS

    def sahte_stat(self, *a, **kw):
        st = gercek(self, *a, **kw)
        return St(st) if self.name == "Anket Kararları.pdf" else st

    monkeypatch.setattr(b.Path, "stat", sahte_stat)
    s = build(agac, etiketsiz=["Kimya Bölümü/A/*"])
    rows = {r["iz"]["yollar"][0]["yol"]: r for r in s.kayitlar}
    ind = rows["Dekanlik/B1.5/Anket Kararları.pdf"]
    assert ind["doc_id"] is None and ind["durum"] == "indirilmemis"
    assert ind["etiketler"][0]["olcut"] == "B.1.5"           # yol üzerinden yine etiket
    dis = rows["Kimya Bölümü/A/A.1.4- 2-OD3]  Paydaş Anketleri/sonuc1.xlsx"]
    assert dis["etiket_disi"] is True and dis["etiketli"] is False


def test_cli_build_ve_stats(agac: Path, tmp_path: Path, capsys):
    ws = tmp_path / "ws"
    assert main(["labels", "build", str(agac), "-w", str(ws), "--unit-alias", "Kimya Bölümü=Kimya"]) == 0
    rows = list(read_jsonl(ws / "labels.jsonl"))
    assert len(rows) == 8
    assert (ws / "labels-report.md").exists()
    assert not (ws / "text").exists()          # ingest'in klasörüne dokunulmaz
    capsys.readouterr()
    assert main(["labels", "stats", "-w", str(ws)]) == 0
    out = capsys.readouterr().out
    assert "Dekanlik" in out and "Kimya" in out and "A.1.2:1" in out
    assert main(["labels", "stats", "-w", str(ws), "--json"]) == 0
    st = json.loads(capsys.readouterr().out)
    assert st["Kimya"]["etiketli"] == 2 and st["Kimya"]["od_li_belge"] == 2
