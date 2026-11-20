"""bidr file: kanıt dosyalama (sentetik çalışma alanı; PDF'ler testte üretilir, model yok)."""
from __future__ import annotations

import csv
import hashlib
import json
import unicodedata
import zipfile
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

from bidr.cli import main
from bidr.file import run as R
from bidr.file.naming import evidence_name, file_name, has_person, safe_name


def _pdf(path: Path, n: int) -> None:
    w = PdfWriter()
    for i in range(n):
        w.add_blank_page(width=200 + i, height=300)      # sayfalar genişlikten tanınır
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        w.write(f)


def _m(olcut, yuva, asama, od, alinti, text, kabul=True):
    s = text.find(alinti)
    assert s >= 0
    return {"olcut": olcut, "yuva": yuva, "asama": asama, "od_onerisi": od, "alinti": alinti,
            "gerekce": "g", "guven": "yuksek",
            "denetim": {"alinti_tutuyor": True, "alinti_skor": 1.0, "alinti_konum": [s, s + len(alinti)],
                        "red": [], "isaret": []},
            "od_kabul": od, "kabul": kabul}


P1 = "Kapak sayfası birinci\fİkinci sayfa: bölüm kurulu uygulama kararı alınmıştır\fÜçüncü sayfa ek"
P2 = "Anket sonuçları değerlendirildi ve izlendi.\fİyileştirme önlemleri alındı burada."
DX = "Komisyon görev tanımları bölüm tarafından belirlenmiştir."


@pytest.fixture
def env(tmp_path):
    src = tmp_path / "kaynak"
    ws = tmp_path / "ws"
    (ws / "text").mkdir(parents=True)
    _pdf(src / "klasör/karar.pdf", 3)
    _pdf(src / "klasör/anket.pdf", 2)
    _pdf(src / "klasör/anket kopya.pdf", 2)
    (src / "belgeler").mkdir(parents=True)
    (src / "belgeler/komisyon.docx").write_bytes(b"PK\x03\x04 sentetik docx")
    docs = {
        "d_karar": ("klasör/karar.pdf", ".pdf", P1, "bolum_kurulu_karari", "BÖLÜM KURULU KARARLARI",
                    "2025-05-23_Bolum-Kurulu-Kararlari"),
        "d_anket": ("klasör/anket.pdf", ".pdf", P2, "anket_sonucu", "Öğrenci Anket Sonuçları",
                    "2025-06-01_Ogrenci-Anket-Sonuclari"),
        "d_kopya": ("klasör/anket kopya.pdf", ".pdf", P2, "anket_sonucu", "Öğrenci Anket Sonuçları",
                    "2025-06-01_Ogrenci-Anket-Sonuclari-2"),
        "d_kom": ("belgeler/komisyon.docx", ".docx", DX, "gorev_dagilimi", "Prof. Dr. Deneme Kişi Görevlendirme",
                  "tarihsiz_Prof-Dr-Deneme-Kisi-Gorevlendirme"),
    }
    with open(ws / "inventory.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["doc_id", "sha256", "rel_path", "ext", "size", "pages", "chars", "method", "status",
                    "dup_of", "error"])
        for did, (rel, ext, text, *_r) in docs.items():
            w.writerow([did, did * 4, rel, ext, 1, text.count("\f") + 1, len(text), "x", "ok", "", ""])
    with open(ws / "documents.jsonl", "w", encoding="utf-8") as f:
        for did, (_, _, _, t, bas, ca) in docs.items():
            f.write(json.dumps({"doc_id": did, "doc_type": t, "donem_ici": True, "baslik": bas,
                                "calisma_adi": ca, "tarih": ca[:10] if ca[0].isdigit() else None},
                               ensure_ascii=False) + "\n")
    for did, (_, _, text, *_r) in docs.items():
        (ws / "text" / f"{did}.txt").write_text(text, encoding="utf-8")
    recs = [
        {"doc_id": "d_karar", "eslesmeler": [
            _m("B.1.1", "B.1.1/3", "uygula", 3, "bölüm kurulu uygulama kararı", P1),
            _m("B.1.1", "B.1.1/1", "planla", 2, "İkinci sayfa", P1),          # aynı belge, aynı ölçüt
            _m("A.1.1", "A.1.1/2", "uygula", 3, "Üçüncü sayfa ek", P1),        # başka ölçüt: ayrı numara
            _m("B.1.1", "B.1.1/7", "ozgun", 5, "Kapak sayfası", P1, kabul=False)]},
        {"doc_id": "d_anket", "eslesmeler": [
            _m("B.1.1", "B.1.1/6", "kontrol_et", 4, "Anket sonuçları değerlendirildi", P2),
            _m("B.1.1", "B.1.1/5", "onlem_al", 4, "İyileştirme önlemleri alındı", P2)]},
        {"doc_id": "d_kopya", "mukerrer": {"temsilci": "d_anket", "yontem": "ayni_metin", "durum": "devralindi"},
         "eslesmeler": [_m("B.1.1", "B.1.1/6", "kontrol_et", 4, "Anket sonuçları değerlendirildi", P2)]},
        {"doc_id": "d_kom", "eslesmeler": [_m("A.1.1", "A.1.1/1", "planla", 2, "Komisyon görev tanımları", DX)]},
    ]
    with open(ws / "decisions.jsonl", "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps({"durum": "ok", "asama": "ince", "karar": "olcut_var", **r},
                               ensure_ascii=False) + "\n")
    return ws, src


def _tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        h.update(p.relative_to(root).as_posix().encode())
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()


def _index(out: Path) -> list[dict]:
    with open(out / R.INDEX, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_file_basic(env, tmp_path):
    ws, src = env
    before = _tree_hash(src)
    out = tmp_path / "out"
    st = R.run(ws, out=out, source=src)
    assert _tree_hash(src) == before                      # kaynak değişmedi
    rows = _index(out)
    assert list(rows[0]) == R.COLUMNS
    by = {(r["olcut"], r["doc_id"]): r for r in rows}
    # B.1.1: karar (OD3) önce, anket (OD4) sonra; kopya ayrı numaralanmaz
    assert [(r["kanit_no"], r["doc_id"]) for r in rows if r["olcut"] == "B.1.1"] == [
        ("1_OD3", "d_karar"), ("2_OD4", "d_anket")]
    assert by[("B.1.1", "d_anket")]["kopyalar"] == "d_kopya"
    assert by[("B.1.1", "d_karar")]["yuvalar"] == "B.1.1/1; B.1.1/3"
    assert "kapak" not in by[("B.1.1", "d_karar")]["alintilar"].lower()   # reddedilen eşleşme girmez
    # A.1.1: ayrı numara; docx olduğu gibi
    assert [(r["kanit_no"], r["doc_id"]) for r in rows if r["olcut"] == "A.1.1"] == [
        ("1_OD2", "d_kom"), ("2_OD3", "d_karar")]
    k = by[("B.1.1", "d_karar")]
    assert k["dosya"] == "B/B.1/B.1.1/[1-OD3]. Bölüm Kurulu Kararları.pdf"
    assert k["sayfalar"] == "2"
    pr = PdfReader(str(out / "evidence" / k["dosya"]))
    assert len(pr.pages) == 1 and float(pr.pages[0].mediabox.width) == 201   # 2. sayfa
    assert by[("A.1.1", "d_karar")]["sayfalar"] == "3"
    an = by[("B.1.1", "d_anket")]
    assert an["sayfalar"] == ""                            # iki sayfa da alıntılı: tüm belge
    kom = by[("A.1.1", "d_kom")]
    assert (out / "evidence" / kom["dosya"]).read_bytes() == (src / "belgeler/komisyon.docx").read_bytes()
    assert kom["dosya"].endswith(".docx") and "Deneme" not in kom["ad"]    # kişi adı yok
    assert kom["ad"] == safe_name(R._type_labels()["gorev_dagilimi"]) != "Belge"   # tür etiketine düştü
    assert any("kişi adı" in u for u in st["uyarilar"])
    # inceleme yok → işaretli
    assert not st["inceleme"] and {r["inceleme"] for r in rows} == {"yapilmadi"}
    assert (out / "evidence" / R.NO_REVIEW).exists()
    assert st["kanit"] == 4 and st["kesilen_pdf"] == 2
    s = R.status(out, ws)
    assert s["guncel"] and s["kanit"] == 4 and s["eksik_dosya"] == 0


def test_rerun_stable_and_whole(env, tmp_path):
    ws, src = env
    out = tmp_path / "out"
    R.run(ws, out=out, source=src)
    a = (out / R.INDEX).read_bytes()
    (out / "evidence" / "eski.txt").write_text("x")
    R.run(ws, out=out, source=src)
    assert (out / R.INDEX).read_bytes() == a
    assert not (out / "evidence" / "eski.txt").exists()   # önceki çıktı temizlendi
    R.run(ws, out=out, source=src, whole=True)
    rows = _index(out)
    assert all(r["sayfalar"] == "" for r in rows)
    k = next(r for r in rows if r["olcut"] == "B.1.1" and r["doc_id"] == "d_karar")
    assert len(PdfReader(str(out / "evidence" / k["dosya"])).pages) == 3


def test_review_decisions(env, tmp_path):
    ws, src = env
    out = tmp_path / "out"
    revs = [
        {"satir": "d_karar|A.1.1/2", "doc_id": "d_karar", "olcut": "A.1.1", "yuva": "A.1.1/2", "karar": "ret",
         "duzelt": None, "etiket": None, "not": ""},
        {"satir": "d_kom|A.1.1/1", "doc_id": "d_kom", "olcut": "A.1.1", "yuva": "A.1.1/1", "karar": "duzelt",
         "duzelt": {"olcut": "A.1.4", "yuva": "A.1.4/1", "asama": "planla"}, "etiket": None, "not": ""},
        {"satir": "d_anket|B.1.1/6", "doc_id": "d_anket", "olcut": "B.1.1", "yuva": "B.1.1/6", "karar": "kabul",
         "duzelt": None, "etiket": None, "not": ""},
    ]
    with open(ws / R.REVIEW, "w", encoding="utf-8") as f:
        for r in revs:
            f.write(json.dumps(r) + "\n")
    st = R.run(ws, out=out, source=src)
    rows = _index(out)
    assert st["inceleme"] and not (out / "evidence" / R.NO_REVIEW).exists()
    assert {r["olcut"] for r in rows} == {"A.1.4", "B.1.1"}        # A.1.1: biri ret, öteki taşındı
    a14 = next(r for r in rows if r["olcut"] == "A.1.4")
    assert a14["dosya"].startswith("A/A.1/A.1.4/[1-OD2]. ") and a14["inceleme"] == "duzelt"
    an = next(r for r in rows if r["doc_id"] == "d_anket")
    assert an["inceleme"] == "kabul,karar_yok"
    assert R.status(out, ws)["guncel"]
    (ws / R.REVIEW).write_text("")                                 # kararlar değişti → güncel değil
    assert not R.status(out, ws)["guncel"]


def test_zip_and_cli(env, tmp_path, capsys):
    ws, src = env
    out = tmp_path / "out"
    assert main(["file", "-w", str(ws), "--out", str(out), "--source", str(src), "--zip"]) == 0
    assert "inceleme yapılmadı" in capsys.readouterr().out
    with zipfile.ZipFile(out / R.ZIP) as z:
        names = z.namelist()
    assert "evidence/B/B.1/B.1.1/[1-OD3]. Bölüm Kurulu Kararları.pdf" in names
    assert f"evidence/{R.NO_REVIEW}" in names and not any(R.MANIFEST in n for n in names)


def test_source_resolution_and_safety(env, tmp_path):
    ws, src = env
    with pytest.raises(R.FileError, match="--source"):
        R.run(ws, out=tmp_path / "o")
    (ws / "config.yaml").write_text(f"bidr:\n  kaynak: {src}\n", encoding="utf-8")
    assert R.source_root(ws, None) == src.resolve()
    with pytest.raises(R.FileError, match="farklı"):
        R.source_root(ws, tmp_path)
    (ws / "config.yaml").unlink()
    with pytest.raises(R.FileError, match="iç içe"):
        R.run(ws, out=src / "cikti", source=src)
    foreign = tmp_path / "yabanci"
    (foreign / "evidence").mkdir(parents=True)
    (foreign / "evidence" / "elle.pdf").write_bytes(b"x")
    with pytest.raises(R.FileError, match="üretmediği"):
        R.run(ws, out=foreign, source=src)
    assert (foreign / "evidence" / "elle.pdf").exists()


def test_page_mismatch_and_missing_file(env, tmp_path):
    ws, src = env
    (ws / "text" / "d_karar.txt").write_text(P1 + "\fdördüncü", encoding="utf-8")   # PDF 3 sayfa, metin 4
    (src / "belgeler/komisyon.docx").unlink()
    R.run(ws, out=tmp_path / "out", source=src)
    rows = _index(tmp_path / "out")
    k = next(r for r in rows if r["olcut"] == "B.1.1" and r["doc_id"] == "d_karar")
    assert k["sayfalar"] == "" and "sayfa_sayisi_uyusmuyor" in k["isaretler"]
    kom = next(r for r in rows if r["doc_id"] == "d_kom")
    assert kom["dosya"] == "" and "kaynak_dosya_yok" in kom["isaretler"]
    assert R.status(tmp_path / "out", ws)["eksik_dosya"] == 1


def test_naming():
    assert R.pages_of_spans("a\fbb\fc", [[2, 4]]) == [2]
    assert R.pages_of_spans("a\fbb\fc", [[0, 6]]) == [1, 2, 3]
    assert R.pages_of_spans("a\fb", [None]) is None
    assert R.page_ranges([1, 2, 3, 5, 7, 8]) == "1-3,5,7-8"
    s = safe_name('Ölçüt: "Değerlendirme" / İzleme? <taslak>|*')
    assert s == "Ölçüt Değerlendirme İzleme taslak"
    assert unicodedata.is_normalized("NFC", safe_name(unicodedata.normalize("NFD", "Öğrenci Şikâyeti")))
    assert len(safe_name("çok " * 60)) <= 80
    assert has_person("Doç. Dr. Ad Soyad") and has_person("x@ornek.edu.tr") and not has_person("Dr Ölçütü")
    ad, uy = evidence_name({"doc_id": "x", "baslik": "PK  ! É+ë ¢(", "doc_type": "t"}, "Tür Etiketi")
    assert ad == "Tür Etiketi" and not uy
    ad, _ = evidence_name({"baslik": "Yönergesi", "doc_type": "yonerge"}, "Yönerge")
    assert ad == "Yönerge"                                   # tek sözcük başlık: tür etiketi
    ad, _ = evidence_name({"baslik": "Birim İç Değerlendirme Raporu hazırlanması hk",
                           "doc_type": "resmi_yazi"}, "Resmi Yazı")
    assert ad == "Yazı - Birim İç Değerlendirme Raporu hazırlanması hk"
    assert evidence_name({"baslik": "Müfredatı (tüm"}, "M")[0] == "Müfredatı (tüm)"
    assert file_name("B.1.1", 2, 4, "Ad", ".PDF") == "[2-OD4]. Ad.pdf"


# -- kanıt kodunun OD'si ve aynı kaynağın tek numarası (sentetik satırlar) -------------------------

def test_evidence_od_reflects_code_drops():
    from bidr.file.naming import evidence_od
    # sayılan, güçlü satır: kanıtın gösterdiği düzey (ölçüt OD'sinin üstünde olabilir; kılavuz örneği)
    assert evidence_od([{"od": 4, "sayilir": True, "od_kabul": 4}], criterion_od=2) == 4
    # kurum geneli: audit etkin aşamayı planla'ya düşürmüş (od 2); modelin ham od_kabul'ü 3 kullanılmaz
    kg = {"od": 2, "sayilir": True, "od_kabul": 3, "flags": ["kurum_geneli", "uygulama_kaniti_eksik"]}
    assert evidence_od([kg], criterion_od=3) == 2
    # dönem kuralı: sayılmayan (geçmiş olay) kanıt ölçüt OD'sinin üstünde düzey göstermez
    gecmis = {"od": 3, "sayilir": False, "od_kabul": 3, "flags": ["gecmis_kanit"]}
    assert evidence_od([gecmis], criterion_od=2) == 2
    # düşük güven (incelemede onaylanmamış) da sayılmaz; onaylanınca sayılır
    zayif = {"od": 4, "sayilir": True, "zayif": True, "karar": ""}
    assert evidence_od([zayif], criterion_od=3) == 3
    assert evidence_od([{**zayif, "karar": "kabul"}], criterion_od=3) == 4
    # sayılanla sayılmayan birlikte: sayılan belirler
    assert evidence_od([gecmis | {"od": 4}, {"od": 2, "sayilir": True}], criterion_od=2) == 2
    assert evidence_od([{"od": None, "od_kabul": 3, "sayilir": False}], criterion_od=2) is None


def test_same_source_gets_one_number():
    from bidr.file.naming import file_name, number_sources, source_key
    docs = {"y2022": {"surum_grubu": "g1"}, "y2023": {"surum_grubu": "g1"}, "y2024": {"surum_grubu": "g1"},
            "y2025": {"surum_grubu": "g1"}, "plan": {}, "tutanak": {"surum_grubu": "g2"}}
    items = [("plan", 2), ("y2022", 2), ("tutanak", 3), ("y2023", 2), ("y2024", 3), ("y2025", 2)]
    out = number_sources(items, key=lambda it: source_key(it[0], docs), od=lambda it: it[1])
    nos = {it[0]: (sira, od) for sira, od, it in out}
    assert {nos[d] for d in ("y2022", "y2023", "y2024", "y2025")} == {(2, 3)}   # yönerge 4 kez değil, tek numara
    assert nos["plan"] == (1, 2) and nos["tutanak"] == (3, 3)
    assert [it[0] for _, _, it in out] == ["plan", "y2022", "y2023", "y2024", "y2025", "tutanak"]
    assert sorted({s for s, _, _ in out}) == [1, 2, 3]                          # boşluksuz sıra
    # aynı numara tek OD taşır: dosya adındaki kod ile dizindeki kanit_no çelişmez
    names = {file_name("B.1.1", s, od, f"Yönerge ({it[0]})", ".pdf") for s, od, it in out if it[0].startswith("y")}
    assert all(n.startswith("[2-OD3]. ") for n in names) and len(names) == 4
    # sürüm grubu yoksa sha (doc_id) ayırır
    assert source_key("a", {}) != source_key("b", {}) and source_key("a", None) == source_key("a", {})


def test_sync_text_names_from_index(tmp_path):
    """Metin adlandırmadan önce yazıldıysa (girdisi değişmedi, eskimedi) kanıt adı ve dosyası dizinden
    eşitlenir: rapor birleşik PDF'in ilk parçasının adını değil dosyalanan parça adını basar."""
    from bidr.file.run import sync_text_names
    from bidr.write.run import girdi_sha
    rows = [{"kanit_no": "1_OD2", "olcut": "B.4.1", "doc_id": "d1", "ad": "Sentetik Usul ve Esaslar",
             "dosya": "B/B.4/B.4.1/[1-OD2]. Sentetik Usul ve Esaslar.pdf"},
            {"kanit_no": "2_OD3", "olcut": "B.4.1", "doc_id": "d2", "ad": "Kurul Kararı",
             "dosya": "B/B.4/B.4.1/[2-OD3]. Kurul Kararı (2025-01-02).pdf"},
            {"kanit_no": "2_OD3", "olcut": "B.4.1", "doc_id": "d3", "ad": "Kurul Kararı",
             "dosya": "B/B.4/B.4.1/[2-OD3]. Kurul Kararı (2025-02-03).pdf"}]
    td = tmp_path / "texts"
    td.mkdir()
    old = [{"no": "1_OD2", "ad": "Sentetik Transkript Yönergesi", "dosya": "eski.pdf"},
           {"no": "2_OD3", "ad": "Kurul Kararı", "dosya": "B/B.4/B.4.1/[2-OD3]. Kurul Kararı (2025-01-02).pdf"}]
    base = {"olcut": "B.4.1", "od_onerisi": 3, "durum": "dogrulandi", "paragraflar": [{"metin": "x [1_OD2]."}],
            "kanitlar": old, "dogrulama": {"model": "m"}}
    (td / "B.4.1.json").write_text(json.dumps({**base, "girdi_sha": girdi_sha(rows, 3)}, ensure_ascii=False),
                                   encoding="utf-8")
    assert sync_text_names(tmp_path, rows) == ["B.4.1"]
    t = json.loads((td / "B.4.1.json").read_text(encoding="utf-8"))
    assert t["kanitlar"][0] == {"no": "1_OD2", "ad": "Sentetik Usul ve Esaslar",
                                "dosya": "B/B.4/B.4.1/[1-OD2]. Sentetik Usul ve Esaslar.pdf"}
    assert t["kanitlar"][1]["dosya"].endswith("(2025-01-02).pdf")          # numaranın ilk dosyası
    assert t["durum"] == "dogrulandi" and t["dogrulama"] == {"model": "m"}  # metin ve doğrulama korunur
    assert sync_text_names(tmp_path, rows) == []                           # ikinci kez: değişiklik yok
    # girdisi değişmiş (numara başka belgeyi gösteriyor) metin eşitlenmez: eskidir, yeniden yazılır
    (td / "B.4.1.json").write_text(json.dumps({**base, "girdi_sha": "baska"}, ensure_ascii=False), encoding="utf-8")
    assert sync_text_names(tmp_path, rows) == []
    assert json.loads((td / "B.4.1.json").read_text(encoding="utf-8"))["kanitlar"] == old


def test_part_date_birlesik_belge():
    """Dosya adındaki tarih alıntının parçasınındır; parça tarihsizse belge tarihi (başka parçanın) yazılmaz."""
    from bidr.file.run import part_date
    text = ("Mezun bilgi formu ad soyad iletişim çalıştığı kurum alanları.\f"
            "Staj değerlendirme yazısı 21.11.2025 tarihli sentetik yazıdır ve dekanlığa gönderilmiştir.")
    doc = {"tarih": "2025-11-21", "parcalar": [{"sayfa": [1, 1], "tarih": None}, {"sayfa": [2, 2], "tarih": "2025-11-21"}]}
    assert part_date(doc, ["Mezun bilgi formu ad soyad iletişim"], lambda: text) is None
    assert part_date(doc, ["Staj değerlendirme yazısı 21.11.2025 tarihli"], lambda: text) == "2025-11-21"
    assert part_date({"tarih": "2025-01-02"}, ["x"], lambda: text) == "2025-01-02"          # parçasız
    assert part_date(doc, ["metinde olmayan alıntı"], lambda: text) == "2025-11-21"         # yerleşmedi: belge tarihi
