"""ingest: arşiv/e-posta üyeleri, eski Excel, parça grupları ve birden çok belge şüphesi.
Tamamen sentetik: bütün dosyalar geçici klasörde üretilir."""
from __future__ import annotations

import hashlib
import io
import shutil
import subprocess
import tarfile
import zipfile
from email.message import EmailMessage
from pathlib import Path

import pytest

from bidr.common import Workspace, doc_id_from_sha
from bidr.ingest import containers as C
from bidr.ingest import extract as ex
from bidr.ingest import parts as P
from bidr.ingest.pipeline import GAPS_BEGIN, GAPS_END, run, scan
from test_ingest import HAS_POPPLER, make_docx, make_text_pdf, read_inv, text_of

LOG = dict(log=lambda m: None)


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, d in files.items():
            z.writestr(n, d)
    return buf.getvalue()


def _snapshot(src: Path):
    return sorted((p.relative_to(src), p.stat().st_mtime_ns) for p in src.rglob("*"))


# ----------------------------------------------------------------------------- zip

def test_zip_members_nested_and_folders(tmp_path):
    src = tmp_path / "k"
    src.mkdir()
    make_docx(tmp_path / "t.docx")
    inner = _zip_bytes({"derin/not.txt": "ic arsiv notu".encode()})
    (src / "paket.zip").write_bytes(_zip_bytes({
        "alt/tutanak.docx": (tmp_path / "t.docx").read_bytes(),
        "duz.txt": "duz metin uyesi".encode(),
        "ic.zip": inner,
        "__MACOSX/alt/._tutanak.docx": b"x",
        ".DS_Store": b"x",
    }))
    ws = tmp_path / "ws"
    before = _snapshot(src)
    run(src, ws, use_ocr=False, **LOG)
    assert _snapshot(src) == before  # kaynak salt okunur

    inv = read_inv(ws)
    assert set(inv) == {"paket.zip", "paket.zip!/alt/tutanak.docx", "paket.zip!/duz.txt",
                        "paket.zip!/ic.zip", "paket.zip!/ic.zip!/derin/not.txt"}
    assert inv["paket.zip"]["status"] == "archive"
    tut = inv["paket.zip!/alt/tutanak.docx"]
    assert tut["status"] == "ok" and tut["ext"] == ".docx" and tut["kapsayici"] == "paket.zip"
    assert "Katilimci Iki" in text_of(ws, tut)
    ic = inv["paket.zip!/ic.zip!/derin/not.txt"]
    assert ic["kapsayici"] == "paket.zip!/ic.zip" and text_of(ws, ic) == "ic arsiv notu"
    assert inv["paket.zip!/ic.zip"]["status"] == "archive"

    # üye dosyanın kendisi: çalışma klasöründe içerik kimliğiyle; kaynak yolu çözücüsü onu verir
    p = C.source_path(src, "paket.zip!/alt/tutanak.docx", Workspace(ws).root)
    assert p and p.suffix == ".docx" and p.is_relative_to(Workspace(ws).root)
    assert doc_id_from_sha(hashlib.sha256(p.read_bytes()).hexdigest()) == tut["doc_id"]
    p.unlink()  # kopya silinse de kaynaktan yeniden açılır
    assert C.source_path(src, "paket.zip!/alt/tutanak.docx", Workspace(ws).root).is_file()
    assert C.source_path(src, "paket.zip!/yok.pdf", Workspace(ws).root) is None

    # aşama denetimi (scan) envanterle aynı satırları görür
    assert {e.rel for e in scan(src)} == set(inv)


def test_zip_member_duplicate_of_loose_file(tmp_path):
    src = tmp_path / "k"
    src.mkdir()
    (src / "a.txt").write_text("ayni icerik", encoding="utf-8")
    (src / "z.zip").write_bytes(_zip_bytes({"a.txt": "ayni icerik".encode()}))
    run(src, tmp_path / "ws", use_ocr=False, **LOG)
    inv = read_inv(tmp_path / "ws")
    assert inv["z.zip!/a.txt"]["dup_of"] == "a.txt"
    assert inv["z.zip!/a.txt"]["doc_id"] == inv["a.txt"]["doc_id"]


def test_zip_path_traversal_not_extracted(tmp_path):
    src = tmp_path / "k"
    src.mkdir()
    (src / "kotu.zip").write_bytes(_zip_bytes({"../../kacak.txt": b"kacak", "/mutlak.txt": b"m",
                                               "iyi.txt": "iyi uye".encode()}))
    ws = tmp_path / "ws"
    run(src, ws, use_ocr=False, **LOG)
    inv = read_inv(ws)
    bad = [r for r in inv.values() if "kacak" in r["rel_path"]]
    assert len(bad) == 1 and ".." not in bad[0]["rel_path"]
    assert bad[0]["status"] == "error" and "yol geçişi" in bad[0]["error"] and not bad[0]["doc_id"]
    mut = [r for r in inv.values() if "mutlak" in r["rel_path"]][0]
    assert mut["status"] == "error"
    assert inv["kotu.zip!/iyi.txt"]["status"] == "ok"
    assert not list(tmp_path.rglob("kacak.txt")) and not (tmp_path.parent / "kacak.txt").exists()
    assert "kacak" in (Workspace(ws).root / "gaps.md").read_text(encoding="utf-8")


def test_encrypted_zip_member_recorded(tmp_path):
    src = tmp_path / "k"
    src.mkdir()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("gizli.pdf", b"sifreli icerik")
        z.writestr("acik.txt", "acik uye")
    data = bytearray(buf.getvalue())
    # gizli.pdf'in yerel ve merkezi başlığında şifreli bayrağını (bit 0) koy
    lo = data.index(b"PK\x03\x04")
    data[lo + 6] |= 0x1
    ce = data.index(b"PK\x01\x02")
    data[ce + 8] |= 0x1
    (src / "s.zip").write_bytes(bytes(data))
    assert zipfile.ZipFile(src / "s.zip").getinfo("gizli.pdf").flag_bits & 0x1
    run(src, tmp_path / "ws", use_ocr=False, **LOG)
    inv = read_inv(tmp_path / "ws")
    g = inv["s.zip!/gizli.pdf"]
    assert g["status"] == "error" and "şifreli" in g["error"]
    assert inv["s.zip"]["status"] == "archive" and "şifreli" in inv["s.zip"]["error"]
    assert inv["s.zip!/acik.txt"]["status"] == "ok"


def test_zip_bomb_ratio_and_limits(tmp_path, monkeypatch):
    src = tmp_path / "k"
    src.mkdir()
    (src / "bomba.zip").write_bytes(_zip_bytes({"sifir.txt": b"0" * (3 * 1024 * 1024),
                                                "normal.txt": "normal".encode()}))
    run(src, tmp_path / "ws", use_ocr=False, **LOG)
    inv = read_inv(tmp_path / "ws")
    assert inv["bomba.zip!/sifir.txt"]["status"] == "error"
    assert "zip bombası" in inv["bomba.zip!/sifir.txt"]["error"]
    assert inv["bomba.zip!/normal.txt"]["status"] == "ok"

    # boyut ve derinlik sınırları
    monkeypatch.setattr(C, "MAX_MEMBER_BYTES", 10)
    monkeypatch.setattr(C, "MAX_DEPTH", 2)
    src2 = tmp_path / "k2"
    src2.mkdir()
    l3 = _zip_bytes({"en_ic.txt": b"x"})
    l2 = _zip_bytes({"l3.zip": l3})
    (src2 / "l1.zip").write_bytes(_zip_bytes({"l2.zip": l2, "buyuk.txt": b"y" * 50}))
    members, _ = C.walk(src2 / "l1.zip", "l1.zip", want_data=True)
    by = {m.rel: m for m in members}
    assert "boyut sınırı" in by["l1.zip!/buyuk.txt"].error
    # l2.zip (> 10 bayt) da boyut sınırına takılır; sınırı geri açıp yalnız derinliği dene
    monkeypatch.setattr(C, "MAX_MEMBER_BYTES", 10 ** 6)
    members, _ = C.walk(src2 / "l1.zip", "l1.zip", want_data=True)
    by = {m.rel: m for m in members}
    assert "derinlik" in by["l1.zip!/l2.zip!/l3.zip"].error
    assert "l1.zip!/l2.zip!/l3.zip!/en_ic.txt" not in by


def test_corrupt_and_unsupported_archives(tmp_path, monkeypatch):
    src = tmp_path / "k"
    src.mkdir()
    (src / "bozuk.zip").write_bytes(b"PK\x03\x04 bu bir zip degil")
    (src / "eski.rar").write_bytes(b"Rar!\x1a\x07\x00 sahte")
    monkeypatch.setattr(C, "bsdtar_available", lambda: False)
    run(src, tmp_path / "ws", use_ocr=False, **LOG)
    inv = read_inv(tmp_path / "ws")
    assert inv["bozuk.zip"]["status"] == "error" and "arşiv" in inv["bozuk.zip"]["error"]
    assert inv["eski.rar"]["status"] == "unsupported"
    assert "desteklenmeyen arşiv" in inv["eski.rar"]["error"]


def test_tar_gz_members(tmp_path):
    src = tmp_path / "k"
    src.mkdir()
    with tarfile.open(src / "y.tar.gz", "w:gz") as t:
        data = "tar uyesi metni".encode()
        ti = tarfile.TarInfo("klasor/belge.txt")
        ti.size = len(data)
        t.addfile(ti, io.BytesIO(data))
    run(src, tmp_path / "ws", use_ocr=False, **LOG)
    inv = read_inv(tmp_path / "ws")
    r = inv["y.tar.gz!/klasor/belge.txt"]
    assert r["status"] == "ok" and text_of(tmp_path / "ws", r) == "tar uyesi metni"
    assert inv["y.tar.gz"]["status"] == "archive"


@pytest.mark.skipif(not shutil.which("bsdtar"), reason="bsdtar yok")
def test_7z_via_bsdtar(tmp_path):
    work = tmp_path / "w"
    (work / "d").mkdir(parents=True)
    (work / "d" / "yedi.txt").write_text("yedi zip uyesi", encoding="utf-8")
    src = tmp_path / "k"
    src.mkdir()
    r = subprocess.run(["bsdtar", "--format", "7zip", "-cf", str(src / "a.7z"), "-C", str(work), "d"],
                       capture_output=True)
    if r.returncode != 0:
        pytest.skip("bsdtar 7z yazamıyor")
    run(src, tmp_path / "ws", use_ocr=False, **LOG)
    inv = read_inv(tmp_path / "ws")
    m = inv["a.7z!/d/yedi.txt"]
    assert m["status"] == "ok" and text_of(tmp_path / "ws", m) == "yedi zip uyesi"


# --------------------------------------------------------------------------- e-posta

def _eml(tmp_path: Path) -> bytes:
    msg = EmailMessage()
    msg["Subject"] = "Bolum kurulu tutanagi"
    msg["From"] = "baskan@example.edu"
    msg["To"] = "uyeler@example.edu"
    msg["Date"] = "Mon, 03 Mar 2025 10:00:00 +0300"
    msg.set_content("Sayin uyeler,\nToplanti tutanagi ektedir.\nSaygilarimla")
    msg.add_alternative("<p>Sayin uyeler, <b>HTML</b> govde</p>", subtype="html")
    msg.add_attachment("ek metin dosyasi".encode(), maintype="text", subtype="plain", filename="ek.txt")
    msg.add_attachment(_zip_bytes({"zipteki.txt": "ekteki zip uyesi".encode()}),
                       maintype="application", subtype="zip", filename="paket.zip")
    msg.add_attachment("ikinci ayni ad".encode(), maintype="text", subtype="plain", filename="ek.txt")
    return msg.as_bytes()


def test_eml_body_and_attachments(tmp_path):
    src = tmp_path / "k"
    src.mkdir()
    (src / "ileti.eml").write_bytes(_eml(tmp_path))
    # zip içindeki e-posta: ekleri zincirlenir
    (src / "posta.zip").write_bytes(_zip_bytes({"ic.eml": _eml(tmp_path)}))
    ws = tmp_path / "ws"
    run(src, ws, use_ocr=False, **LOG)
    inv = read_inv(ws)
    m = inv["ileti.eml"]
    t = text_of(ws, m)
    assert m["status"] == "ok" and m["method"] == "email"
    assert "Konu: Bolum kurulu tutanagi" in t and "Toplanti tutanagi ektedir" in t
    assert "HTML" not in t  # text/plain tercih edilir
    assert "[ekler]" in t and "paket.zip" in t
    assert text_of(ws, inv["ileti.eml!/ek.txt"]) == "ek metin dosyasi"
    assert text_of(ws, inv["ileti.eml!/ek (2).txt"]) == "ikinci ayni ad"
    assert inv["ileti.eml!/paket.zip"]["status"] == "archive"
    assert text_of(ws, inv["ileti.eml!/paket.zip!/zipteki.txt"]) == "ekteki zip uyesi"
    assert inv["ileti.eml!/ek.txt"]["kapsayici"] == "ileti.eml"
    assert "posta.zip!/ic.eml!/paket.zip!/zipteki.txt" in inv
    assert inv["posta.zip!/ic.eml"]["status"] == "ok"
    assert {e.rel for e in scan(src)} == set(inv)


def test_eml_html_only_body(tmp_path):
    msg = EmailMessage()
    msg["Subject"] = "Duyuru"
    msg.set_content("<html><body><p>Yalniz HTML govde</p><script>x()</script></body></html>", subtype="html")
    p = tmp_path / "h.eml"
    p.write_bytes(msg.as_bytes())
    t = ex.extract(p).text
    assert "Yalniz HTML govde" in t and "x()" not in t


def test_msg_without_library_unsupported(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "_load_msg", lambda src: None)
    p = tmp_path / "a.msg"
    p.write_bytes(b"\xd0\xcf\x11\xe0 sahte")
    with pytest.raises(ex.Unsupported):
        ex.extract(p)


# ------------------------------------------------------------------------- eski Excel

def make_xls(path: Path) -> Path:
    import datetime as dt

    import xlwt

    wb = xlwt.Workbook()
    s = wb.add_sheet("Notlar")
    s.write(0, 0, "Ders")
    s.write(0, 1, "Kredi")
    s.write(0, 2, "Tarih")
    s.write(1, 0, "MAT101")
    s.write(1, 1, 4)
    s.write(1, 2, dt.date(2025, 3, 3), xlwt.easyxf(num_format_str="DD.MM.YYYY"))
    s2 = wb.add_sheet("Ikinci")
    s2.write(4, 3, "uzak hucre")
    wb.save(str(path))
    return path


def test_xls_extract(tmp_path):
    pytest.importorskip("xlwt")
    p = make_xls(tmp_path / "eski.xls")
    res = ex.extract(p)
    assert res.method == "xlrd" and res.page_count == 2
    assert "MAT101\t4\t2025-03-03" in res.pages[0] and "[sayfa: Notlar]" in res.pages[0]
    assert "uzak hucre" in res.pages[1]


def test_xls_disguised_xlsx_and_html(tmp_path):
    import openpyxl

    wb = openpyxl.Workbook()
    wb.active["A1"] = "aslinda xlsx"
    wb.save(tmp_path / "a.xls")
    assert "aslinda xlsx" in ex.extract(tmp_path / "a.xls").text
    (tmp_path / "b.xls").write_text("<table><tr><td>web tablosu</td></tr></table>", encoding="utf-8")
    assert "web tablosu" in ex.extract(tmp_path / "b.xls").text


# ------------------------------------------------------------- parça grubu, çoklu belge

def test_page_number_parsing():
    assert P.page_number("Baslik\ngovde\nSayfa 3 / 10") == (3, 10)
    assert P.page_number("Baslik\ngovde\nPage 2 of 5") == (2, 5)
    assert P.page_number("govde\n- 7 -") == (7, None)
    assert P.page_number("Sayfa: 4\ngovde\nson satir") == (4, None)
    assert P.page_number("govde metni\nson satir") == (None, None)


HDR = "ORNEK UNIVERSITESI MATEMATIK BOLUM KURULU TUTANAGI"


def _tutanak_pages(rng, total):
    return [f"{HDR}\nGundem maddesi {i} uzerinde gorusuldu ve karar alindi.\n"
            f"Madde {i} oylandi kabul edildi.\nSayfa {i}/{total}" for i in rng]


def test_part_groups_unit():
    a = _tutanak_pages(range(1, 4), 6)
    b = _tutanak_pages(range(4, 7), 6)
    other = ["Baska bir belge\nicerik\nSayfa 4/9"]
    g = P.part_groups({"aaa": a, "bbb": b, "ccc": other})
    assert g["aaa"]["grup"] == g["bbb"]["grup"] == "pg-aaa"
    assert (g["aaa"]["sira"], g["bbb"]["sira"]) == (1, 2) and "ccc" not in g
    # toplam sayfa farklıysa bağlanmaz; numarasız belgeler bağlanmaz
    assert P.part_groups({"aaa": a, "bbb": _tutanak_pages(range(4, 7), 9)}) == {}
    assert P.part_groups({"x": ["metin"], "y": ["metin"]}) == {}
    # üst bilgi aynı, toplam yok: numara devamı + üst bilgi yeter
    a2 = [p.replace("/6", "") for p in a]
    b2 = [p.replace("/6", "") for p in b]
    assert P.part_groups({"aaa": a2, "bbb": b2})["bbb"]["gerekce"] == "sayfa_no+ust_bilgi"


def test_merge_into_versions():
    groups = {"b": {"grup": "sg-b", "uyeler": ["c"], "benzerlik": 0.95},
              "c": {"grup": "sg-b", "uyeler": ["b"], "benzerlik": 0.95}}
    out = P.merge_into_versions(groups, {"a": "pg-a", "b": "pg-a", "c": None, "d": None})
    assert {out[x]["grup"] for x in "abc"} == {"sg-a"} and "d" not in out
    assert out["a"]["uyeler"] == ["b", "c"] and out["a"]["benzerlik"] is None
    assert out["b"]["benzerlik"] == 0.95
    assert P.merge_into_versions(groups, {"a": None}) is groups


def test_multi_doc_starts_unit():
    tut = _tutanak_pages(range(1, 3), 2)
    izl = ["DERS IZLENCESI\nMAT201 Analiz II dersinin amaci turev integral seriler konularini "
           "kapsar. Haftalik konu plani ve degerlendirme olcutleri asagidadir.\nSayfa 1/1"]
    assert P.multi_doc_starts(tut + izl) == [(3, "sayfa_no_yeniden_1")]
    assert P.multi_doc_starts(tut) == []
    # numarasız: üst bilgi + başlık + konu değişimi
    t2 = [p.rsplit("\n", 1)[0] * 3 for p in tut]
    i2 = ["DERS IZLENCESI\n" + ("Analiz dersinin haftalik konulari turev integral seriler "
                                 "yakinsaklik ve uygulamalar " * 3)]
    assert P.multi_doc_starts(t2 + i2) == [(3, "konu_ve_baslik_degisti")]


@pytest.mark.skipif(not HAS_POPPLER, reason="poppler yok")
def test_pipeline_parts_and_multi_doc(tmp_path):
    src = tmp_path / "k"
    src.mkdir()
    make_text_pdf(src / "parca-a.pdf", _tutanak_pages(range(1, 4), 6))
    make_text_pdf(src / "parca-b.pdf", _tutanak_pages(range(4, 7), 6))
    make_text_pdf(src / "birlesik.pdf", _tutanak_pages(range(1, 3), 2) + [
        "DERS IZLENCESI\nMAT201 Analiz II dersinin amaci turev integral seriler\n"
        "Haftalik konu plani ve degerlendirme olcutleri\nSayfa 1/1"])
    ws = tmp_path / "ws"
    gaps = Workspace(ws).ensure().root / "gaps.md"
    gaps.write_text("# Eksikler\n\nönceki içerik\n", encoding="utf-8")
    run(src, ws, use_ocr=False, **LOG)
    inv = read_inv(ws)
    a, b = inv["parca-a.pdf"], inv["parca-b.pdf"]
    assert a["parca_grubu"] and a["parca_grubu"] == b["parca_grubu"]
    assert (a["parca_sira"], b["parca_sira"]) == ("1", "2") and a["parca_gerekce"] == "sayfa_no+toplam"
    assert inv["birlesik.pdf"]["coklu_belge_suphesi"] == "3" and not inv["birlesik.pdf"]["parca_grubu"]
    g = gaps.read_text(encoding="utf-8")
    assert g.startswith("# Eksikler\n\nönceki içerik") and g.count(GAPS_BEGIN) == 1 and GAPS_END in g
    assert "birlesik.pdf" in g and "s. 3" in g and a["parca_grubu"] in g
    run(src, ws, use_ocr=False, **LOG)  # yeniden: tek bölüm, sonuç aynı
    g2 = gaps.read_text(encoding="utf-8")
    assert g2.count(GAPS_BEGIN) == 1 and g2 == g
    assert read_inv(ws)["parca-b.pdf"]["parca_grubu"] == a["parca_grubu"]
