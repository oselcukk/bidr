"""`bidr maskele --kaynak`: model öncesi kaynak klasör maskeleme, yer tutucu/imza etiketleri ve belge
kimliği bilgisinin korunması (yalnız sentetik veri)."""
from __future__ import annotations

import email
import email.policy
import io
import json
import os
import tarfile
import zipfile
from email.message import EmailMessage
from pathlib import Path

import pytest

from bidr.cli import main
from bidr.ingest import containers as C
from bidr.mask import MaskRules, detect
from bidr.mask import kaynak as K

from test_mask import EMAIL, NAME, OGR, PDF_OK, PHONE, TC1, TC2, _sha, make_docx, make_pdf, pdf_text

RULES = MaskRules(names=(NAME,))


def _zip_bytes(members: dict[str, bytes]) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for n, d in members.items():
            z.writestr(n, d)
    return b.getvalue()


def _eml_bytes(attach: dict[str, bytes]) -> bytes:
    m = EmailMessage()
    m["From"] = f"{NAME} <{EMAIL}>"
    m["To"] = "bolum@ornek.edu.tr"
    m["Subject"] = f"Başvuru {OGR}"
    m.set_content(f"Merhaba, telefonum {PHONE}. TC {TC1}.\nSayı: E-12345678-302.01-2345678\n")
    for n, d in attach.items():
        m.add_attachment(d, maintype="application", subtype="octet-stream", filename=n)
    return m.as_bytes()


@pytest.fixture
def src(tmp_path):
    s = tmp_path / "bolum"
    make_pdf(s / "Kurul/karar.pdf", PDF_OK, annot=False, attach=False)
    make_docx(s / "Başvurular/basvuru.docx")
    (s / "Başvurular" / f"{OGR} transkript.txt").write_text(f"Öğrenci {OGR} TC {TC2}\n", encoding="utf-8")
    inner = _zip_bytes({"ic/not.txt": f"e-posta {EMAIL}\n".encode()})
    (s / "arsiv.zip").write_bytes(_zip_bytes({
        "Toplanti/tutanak.txt": f"Katılımcı {NAME} tel {PHONE}\n".encode(),
        "ic.zip": inner,
        "__MACOSX/._x": b"x",
        "sunum.pptx": b"PK sentetik",
    }))
    tb = io.BytesIO()
    with tarfile.open(fileobj=tb, mode="w:gz") as t:
        data = f"TC {TC1}\n".encode()
        ti = tarfile.TarInfo("liste.csv")
        ti.size = len(data)
        t.addfile(ti, io.BytesIO(data))
    (s / "yedek.tar.gz").write_bytes(tb.getvalue())
    (s / "ileti.eml").write_bytes(_eml_bytes({"ek.txt": f"ek {TC2}\n".encode()}))
    (s / "eski.doc").write_bytes(b"\xd0\xcf\x11\xe0 sentetik")
    (s / ".DS_Store").write_bytes(b"x")
    (s / "~$kilit.docx").write_bytes(b"x")
    return s


def _tree_sha(d: Path) -> dict:
    return {p.relative_to(d).as_posix(): _sha(p) for p in d.rglob("*") if p.is_file()}


def _all_text(out: Path) -> str:
    """Maskeli ağaçtaki bütün okunabilir metin (kaplar açılarak)."""
    chunks = []

    def add(name: str, data: bytes):
        ext = C.full_ext(name)
        if ext == ".zip":
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                chunks.extend(z.namelist())
                for n in z.namelist():
                    add(n, z.read(n))
        elif ext == ".tar.gz":
            with tarfile.open(fileobj=io.BytesIO(data)) as t:
                for ti in t:
                    chunks.append(ti.name)
                    add(ti.name, t.extractfile(ti).read())
        elif ext == ".eml":
            m = email.message_from_bytes(data, policy=email.policy.default)
            chunks.extend(str(v) for _, v in m.items())
            for p in m.walk():
                if not p.is_multipart():
                    payload = p.get_payload(decode=True) or b""
                    chunks.append(payload.decode("utf-8", "replace"))
                    if p.get_filename():
                        chunks.append(p.get_filename())
        elif ext == ".pdf":
            chunks.append(pdf_text_bytes(data))
        elif ext == ".docx":
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                chunks.extend(z.read(n).decode("utf-8", "replace") for n in z.namelist() if n.endswith(".xml"))
        else:
            chunks.append(data.decode("utf-8", "replace"))

    for p in out.rglob("*"):
        if p.is_file():
            chunks.append(p.relative_to(out).as_posix())
            add(p.name, p.read_bytes())
    return "\n".join(chunks)


def pdf_text_bytes(data: bytes) -> str:
    from pypdf import PdfReader
    return "\n".join(pg.extract_text() or "" for pg in PdfReader(io.BytesIO(data)).pages)


def test_source_folder_masked_copy(src, tmp_path):
    before = _tree_sha(src)
    out = tmp_path / "maskeli"
    rep = K.run_source(src, out, rules=RULES, engine="pypdf")
    assert _tree_sha(src) == before                                  # kaynak salt okunur
    recs = {r["dosya"]: r for r in rep["dosyalar"]}
    # ağaç, alt klasörler, kaplar
    assert recs["Kurul/karar.pdf"]["durum"] == "tamam"
    assert recs["Başvurular/basvuru.docx"]["durum"] == "tamam"
    assert recs["arsiv.zip"]["durum"] == "kap"
    assert recs["arsiv.zip!/Toplanti/tutanak.txt"]["maskelenen"] == {"ad": 1, "telefon": 1}
    assert recs["arsiv.zip!/ic.zip!/ic/not.txt"]["maskelenen"] == {"eposta": 1}
    assert recs["arsiv.zip!/sunum.pptx"]["durum"] == "desteklenmiyor"
    assert "arsiv.zip!/__MACOSX/._x" not in recs
    assert recs["yedek.tar.gz!/liste.csv"]["maskelenen"] == {"tc_no": 1}
    assert recs["ileti.eml"]["durum"] == "tamam" and recs["ileti.eml"]["maskelenen"]["eposta"] >= 1
    assert recs["ileti.eml!/ek.txt"]["maskelenen"] == {"tc_no": 1}
    # adındaki öğrenci no yer tutucuya çevrildi; rapor iki yolu da tutar
    tr = recs[f"Başvurular/{OGR} transkript.txt"]
    assert tr["hedef"] == "Başvurular/[OGRENCI_NO] transkript.txt"
    # desteklenmeyen: olduğu gibi kopyalandı, elle bakılmalı
    assert recs["eski.doc"]["durum"] == "desteklenmiyor" and recs["eski.doc"]["elle_bakilmali"]
    assert (out / "eski.doc").read_bytes() == (src / "eski.doc").read_bytes()
    assert {e["dosya"] for e in rep["elle_bakilmali"]} == {"eski.doc", "arsiv.zip!/sunum.pptx"}
    # gizli/sistem dosyaları kopyalanmadı
    assert not (out / ".DS_Store").exists() and not (out / "~$kilit.docx").exists()
    assert rep["ozet"]["atlanan_gizli_sistem"] == 2
    # hiçbir kanıt düşmedi: her (atlanmayan) kaynak dosyanın maskeli karşılığı var
    for r in rep["dosyalar"]:
        if C.SEP not in r["dosya"]:
            assert (out / r["hedef"]).is_file(), r
    # maskeli ağaçta kişisel veri yok; belge kimliği duruyor
    txt = _all_text(out)
    for v in (TC1, TC2, EMAIL, PHONE, OGR, NAME):
        assert v not in txt, v
    assert "E-12345678-302.01-2345678" in txt
    assert "[TELEFON]" in txt and "[TC_NO]" in txt
    # rapor çıktının dışında, değer içermiyor
    rp = Path(rep["rapor"])
    assert rp.parent == out.parent and not str(rp).startswith(str(out) + "/")
    body = rp.read_text(encoding="utf-8")
    for v in (TC1, TC2, EMAIL, PHONE):
        assert v not in body


def test_containers_repackaged_and_readable_by_ingest(src, tmp_path):
    out = tmp_path / "maskeli"
    K.run_source(src, out, rules=RULES, engine="pypdf")
    members, notes = C.walk(out / "arsiv.zip", "arsiv.zip", want_data=True)
    names = {m.rel for m in members}
    assert {"arsiv.zip!/Toplanti/tutanak.txt", "arsiv.zip!/ic.zip", "arsiv.zip!/ic.zip!/ic/not.txt",
            "arsiv.zip!/sunum.pptx"} <= names
    assert not [n for n in notes if n.status == "error"]
    m, _ = C.walk(out / "ileti.eml", "ileti.eml", want_data=True)
    assert [x.rel for x in m] == ["ileti.eml!/ek.txt"]
    msg = email.message_from_bytes((out / "ileti.eml").read_bytes(), policy=email.policy.default)
    assert K.ADDR_PLACEHOLDER in str(msg["From"]) and "[AD]" in str(msg["From"])
    assert "[OGRENCI_NO]" in str(msg["Subject"])


def test_output_rules(src, tmp_path):
    from bidr.mask.run import MaskRunError
    with pytest.raises(MaskRunError):
        K.run_source(src, src / "alt", rules=RULES)
    foreign = tmp_path / "dolu"
    foreign.mkdir()
    (foreign / "x.txt").write_text("x")
    with pytest.raises(MaskRunError):
        K.run_source(src, foreign, rules=RULES)
    out = tmp_path / "m"
    K.run_source(src, out, rules=RULES, engine="pypdf")
    K.run_source(src, out, rules=RULES, engine="pypdf")       # kendi çıktısının üstüne yazabilir


def _ob_temiz():
    from bidr.mask import onbellek as OB
    OB.ac(None)
    OB._ACIK.clear()


def test_kaynak_onbellek_ilerleme_ve_isaret(src, tmp_path, monkeypatch):
    """-w ile kaynak kip çalışma alanı önbelleğini kullanır (ikinci koşu dosyaları yeniden işlemez), ilerlemeyi
    `<ws>/maskeleme-ilerleme.json`'a yazar, işareti koşunun başında `yarim`, sonunda `tamam` yazar."""
    _ob_temiz()
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "maskeli"
    goruldu = []
    asil = K._work

    def izle(args):
        goruldu.append(K.marker_durumu(out))
        return asil(args)
    monkeypatch.setattr(K, "_work", izle)
    rep = K.run_source(src, out, rules=RULES, engine="pypdf", ws=ws)
    assert goruldu and set(goruldu) == {"yarim"}                 # koşu sürerken işaret var, "yarim"
    assert K.marker_durumu(out) == "tamam"
    assert (ws / ".cache" / "maske.sqlite").is_file()
    il = json.loads((ws / K.ILERLEME).read_text(encoding="utf-8"))
    n = rep["ozet"]["dosya"]
    assert il["durum"] == "bitti" and il["toplam"] == il["biten"] == n == len(goruldu)
    assert not any(NAME in v or OGR in v for v in map(str, il.values()))     # ilerlemede dosya adı yok
    islenen = sum(1 for r in rep["dosyalar"] if r.get("sha256"))
    assert islenen and rep["ozet"]["onbellekten"] == 0
    def agac():   # işaret (zaman) dışında; yeniden paketlenen tar.gz de belirlenimci (gzip zamanı sabit)
        return {k: v for k, v in _tree_sha(out).items() if k != ".bidr-maskeleme.json"}
    once = agac()
    rep2 = K.run_source(src, out, rules=RULES, engine="pypdf", ws=ws)
    assert rep2["ozet"]["onbellekten"] == islenen                 # bitmiş dosyalar baştan yapılmadı
    assert agac() == once
    assert os.environ.get("BIDR_MASKE_ONBELLEK") is None          # ortam geri alındı
    rep3 = K.run_source(src, out, rules=RULES, engine="pypdf", ws=ws, onbellek_kullan=False)
    assert rep3["ozet"]["onbellekten"] == 0
    _ob_temiz()


def test_kaynak_yarim_kosu_kaldigi_yerden(src, tmp_path):
    """Zaman aşımıyla kesilen koşu: işaret `yarim`, klasörde yarım dosyalar. Yeniden koşu reddetmez; önbellekteki
    bitmiş dosyalar yeniden işlenmez. İşaretsiz (bidr'in olmayan) dolu klasör yine reddedilir."""
    _ob_temiz()
    from bidr.mask.run import MARKER, MaskRunError
    ws = tmp_path / "ws"
    ws.mkdir()
    out = tmp_path / "maskeli"
    rep = K.run_source(src, out, rules=RULES, engine="pypdf", ws=ws)
    # kesilmiş koşunun izi: işaret "yarim", bir dosya eksik, bir dosya yarım yazılmış
    (out / MARKER).write_text(json.dumps({"surum": 1, "mod": "kaynak", "durum": "yarim"}), encoding="utf-8")
    (out / "eski.doc").unlink()
    (out / "Kurul" / "karar.pdf").write_bytes(b"%PDF yarim")
    assert K.marker_durumu(out) == "yarim"
    rep2 = K.run_source(src, out, rules=RULES, engine="pypdf", ws=ws)
    assert K.marker_durumu(out) == "tamam"
    assert rep2["ozet"]["onbellekten"] == sum(1 for r in rep["dosyalar"] if r.get("sha256"))
    assert (out / "Kurul" / "karar.pdf").read_bytes() != b"%PDF yarim" and (out / "eski.doc").is_file()
    eski = tmp_path / "eski-surum"
    eski.mkdir()
    (eski / MARKER).write_text(json.dumps({"surum": 1, "mod": "kaynak"}), encoding="utf-8")
    assert K.marker_durumu(eski) == "tamam"                       # eski işaret (durum alanı yok): bitmiş koşu
    yabanci = tmp_path / "yabanci"
    yabanci.mkdir()
    (yabanci / "x.pdf").write_bytes(b"%PDF")
    assert K.marker_durumu(yabanci) is None
    with pytest.raises(MaskRunError):
        K.run_source(src, yabanci, rules=RULES, engine="pypdf", ws=ws)
    _ob_temiz()


def test_kaynak_paralel_sira_ve_ilerleme(src, tmp_path):
    """--is 2: rapor sırası iş sırasıdır (tamamlanma sırası değil); ilerleme her dosyada artar."""
    _ob_temiz()
    ws = tmp_path / "ws"
    ws.mkdir()
    adimlar = []
    r1 = K.run_source(src, tmp_path / "a", rules=RULES, engine="pypdf")
    r2 = K.run_source(src, tmp_path / "b", rules=RULES, engine="pypdf", ws=ws, workers=2,
                      progress=lambda i, n, rel: adimlar.append((i, n)))
    assert [r["dosya"] for r in r1["dosyalar"]] == [r["dosya"] for r in r2["dosyalar"]]
    n = r2["ozet"]["dosya"]
    assert [i for i, _ in adimlar] == list(range(1, n + 1)) and {m for _, m in adimlar} == {n}
    assert json.loads((ws / K.ILERLEME).read_text(encoding="utf-8"))["biten"] == n
    _ob_temiz()


def test_corrupt_archive_copied_and_flagged(tmp_path):
    s = tmp_path / "s"
    s.mkdir()
    (s / "bozuk.zip").write_bytes(b"PK\x03\x04 bozuk")
    rep = K.run_source(s, tmp_path / "o", rules=RULES)
    r = rep["dosyalar"][0]
    assert r["durum"] == "hata" and r["elle_bakilmali"]
    assert (tmp_path / "o/bozuk.zip").read_bytes() == b"PK\x03\x04 bozuk"


def test_cli_source_mode(src, tmp_path, capsys):
    out = tmp_path / "cikti"
    rc = main(["maskele", "--kaynak", str(src), "--out", str(out), "--motor", "pypdf", "--is", "2"])
    assert rc == 1                                    # desteklenmeyen dosya var → elle bakılmalı
    o = capsys.readouterr().out
    assert "ELLE BAKILMALI" in o and "eski.doc" in o
    rep = json.loads((tmp_path / "cikti.maskeleme-raporu.json").read_text(encoding="utf-8"))
    assert rep["mod"] == "kaynak" and rep["ozet"]["kap"] == 3    # arsiv.zip, ic.zip, tar.gz
    assert main(["maskele", "--kaynak", str(src)]) == 2           # --out zorunlu


# ---------------------------------------------------------------- belge kimliği korunur

DOC_IDS = [
    "Sayı : E-12345678-302.01-2345678", "Sayı: 2023000123", "Tarih: 20.11.2026", "20/11/2026", "2026-11-20",
    "Karar No: 2026/15", "Karar Tarihi ve No: 03.05.2024 - 2024/05-03", "KİM 201 Genel Kimya", "KIM2010",
    "CHEM 101", "Sayfa 3/12", "Evrak Tarih ve Sayısı: 05.11.2024-2345678", "Toplantı No: 2024/11",
    "Belge Doğrulama Kodu: BSA4K3Z8FT", "Doküman No: FR-0312 Rev.No: 02 Yayın Tarihi: 01.02.2020",
    "EBYS: E-20123456-100-2024", "2023-2024 Güz", "Sayı: 2023000123", "Proje No: 2019123456",
    "BAP 2020-12345", "Evrak No 2021123456", "Saat 10:30 - 12:30", "ISBN 978-605-123-45-67",
    "E-2019123456", "2019123456-100", "Protokol 2020123456",
]


@pytest.mark.parametrize("s", DOC_IDS)
def test_document_identity_not_masked(s):
    assert detect(s, MaskRules()) == [], s


@pytest.mark.parametrize("s,kind", [
    ("Öğrenci No: 2019123456", "ogrenci_no"), ("2019123456 Deneme", "ogrenci_no"),
    ("No: 2019123456", "ogrenci_no"), ("Tel: 0555 000 11 22", "telefon"), ("+90 555 000 11 22", "telefon"),
])
def test_personal_numbers_still_masked(s, kind):
    assert [f.kind for f in detect(s, MaskRules())] == [kind]


def test_placeholder_address_not_pii():
    assert detect(K.ADDR_PLACEHOLDER, MaskRules()) == []


# ---------------------------------------------------------------- yer tutucular / imza etiketi

def test_pdf_text_layer_placeholders(tmp_path):
    pytest.importorskip("pymupdf")
    from bidr.mask import formats as F
    s, d = tmp_path / "a.pdf", tmp_path / "b.pdf"
    make_pdf(s, PDF_OK, annot=False, attach=False)
    F.mask_pdf_pymupdf(s, d, RULES)
    t = pdf_text(d)
    for ph in ("[TC_NO]", "[EPOSTA]", "[TELEFON]", "[IBAN]", "[OGRENCI_NO]"):
        assert ph in t, ph
    assert TC1 not in t and EMAIL not in t


def test_placeholder_is_not_signature_label():
    from bidr.mask import imza as IM
    from bidr.mask.ocr import Word
    for t in ("[İMZA]", "[IMZA]", "IMZA]", "[İMZA"):
        assert not IM.is_strict_label(Word(t, 95, 0, 0, 40, 10, (1, 0, 1, 0)), 1, [t])
    assert IM.is_strict_label(Word("İmza:", 95, 0, 0, 40, 10, (1, 0, 1, 0)), 1, ["İmza:"])


def test_mask_name_keeps_extension():
    assert K.mask_name(f"{OGR}.tar.gz", RULES) == "[OGRENCI_NO].tar.gz"
    assert K.mask_name(f"{NAME} CV.pdf", RULES) == "[AD] CV.pdf"
    assert K.mask_name("karar.pdf", RULES) == "karar.pdf"
