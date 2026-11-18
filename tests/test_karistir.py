"""tools/karistir.py testleri. Yalnız sentetik veri: geçici klasörde üretilen küçük belgeler."""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("karistir", ROOT / "tools" / "karistir.py")
karistir = importlib.util.module_from_spec(_spec)
sys.modules["karistir"] = karistir
_spec.loader.exec_module(karistir)

COLUMNS = ["id", "yol", "sha256", "boyut", "bicim", "kaynak_turu", "birim", "atif_rapor",
           "adres", "yil", "not"]
RATES = {"tarama": 0.5, "donustur": 1.0, "birlestir": 1.0, "parcala": 1.0, "kopya": 0.4,
         "zip": 0.4, "bozuk": 0.3}


def _pdf(pages: list[str]) -> bytes:
    """Metin katmanlı en küçük geçerli PDF (Helvetica, ASCII)."""
    objs: list[bytes] = []
    n = len(pages)
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode())
    font_id = 3 + 2 * n
    for i, text in enumerate(pages):
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] "
                    f"/Resources << /Font << /F1 {font_id} 0 R >> >> "
                    f"/Contents {4 + 2 * i} 0 R >>".encode())
        stream = f"BT /F1 12 Tf 20 150 Td ({text}) Tj ET".encode()
        objs.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream
                    + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def _make_pool(root: Path) -> Path:
    from docx import Document
    from PIL import Image, ImageDraw

    root.mkdir(parents=True, exist_ok=True)
    files: dict[str, bytes] = {}
    for i in range(6):
        files[f"kurul/toplanti_tutanagi_{i}.pdf"] = _pdf([f"Kurul toplantisi gundem {i}"])
    files["rapor/faaliyet_raporu_uzun.pdf"] = _pdf([f"Faaliyet sayfa {k}" for k in range(1, 9)])
    files["rapor/ozdegerlendirme_ikinci.pdf"] = _pdf([f"Ozdegerlendirme {k}" for k in range(1, 8)])
    files["anket/memnuniyet_anketi.pdf"] = _pdf(["Memnuniyet anketi sonuclari", "Ek tablo"])
    files["web/duyuru_sayfasi.html"] = (
        "<html><head><meta charset='utf-8'><title>Duyuru</title></head><body>"
        "<h1>Program çıktıları güncellendi</h1><p>Öğrenci geri bildirimi alınmıştır.</p>"
        "<script>var x=1;</script></body></html>").encode()
    files["web/mezun_izleme.htm"] = (
        "<html><body><p>Mezun izleme &amp; değerlendirme çalışması.</p></body></html>").encode()
    for name in ("komisyon_karari", "ders_degerlendirme"):
        d = Document()
        d.add_paragraph(f"Sentetik {name} metni: iyileştirme adımı planlandı.")
        p = root / "_tmp.docx"
        d.save(p)
        files[f"belgeler/{name}.docx"] = p.read_bytes()
        p.unlink()
    for name in ("afis_gorseli", "sertifika_fotografi"):
        im = Image.new("RGB", (240, 160), "white")
        ImageDraw.Draw(im).text((10, 60), f"Sentetik {name}", fill="black")
        p = root / "_tmp.png"
        im.save(p, "PNG")
        files[f"gorsel/{name}.png"] = p.read_bytes()
        p.unlink()
    files["tablo/olcum_verisi.csv"] = b"a,b\n1,2\n"

    rows = []
    for i, (rel, data) in enumerate(sorted(files.items()), 1):
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        rows.append({"id": f"SYN{i:03d}", "yol": rel, "sha256": hashlib.sha256(data).hexdigest(),
                     "boyut": len(data), "bicim": Path(rel).suffix.lstrip("."),
                     "kaynak_turu": "sentetik", "birim": "Birim A", "atif_rapor": "",
                     "adres": "", "yil": "2024", "not": ""})
    with open(root / "manifest-gizli.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return root


def _run(tmp: Path, name: str, tohum: int = 7, disabled: set[str] | None = None) -> tuple[Path, dict]:
    out, esl = tmp / f"{name}-out", tmp / f"{name}-esleme.json"
    karistir.scramble(tmp / "havuz", tmp / "havuz" / "manifest-gizli.csv", out, esl, tohum,
                      RATES, disabled, quiet=True)
    return out, json.loads(esl.read_text(encoding="utf-8"))


def _tree(out: Path) -> dict[str, str]:
    return {p.relative_to(out).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(out.rglob("*")) if p.is_file()}


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("karistir")
    _make_pool(tmp / "havuz")
    out, mapping = _run(tmp, "a")
    return tmp, out, mapping


def test_same_seed_same_output(env):
    tmp, out, mapping = env
    out2, mapping2 = _run(tmp, "b")
    assert _tree(out) == _tree(out2)
    assert mapping == mapping2
    out3, _ = _run(tmp, "c", tohum=8)
    assert _tree(out3) != _tree(out)


def test_mapping_covers_every_output_file(env):
    tmp, out, mapping = env
    listed = {f["yol"]: f for f in mapping["dosyalar"]}
    tree = _tree(out)
    assert set(tree) == set(listed)
    for rel, sha in tree.items():
        assert listed[rel]["sha256"] == sha
        if rel.endswith(".zip"):
            with zipfile.ZipFile(out / rel) as zf:
                names = {n for n in zf.namelist() if not n.endswith("/")}
            assert names == {m["yol"] for m in listed[rel]["icerik"]}
    # her kaynak en az bir çıktıda var; her bozma kaydı dolu
    ids = {r["id"] for r in csv.DictReader(open(tmp / "havuz" / "manifest-gizli.csv",
                                                encoding="utf-8"))}
    covered = {k["id"] for f in mapping["dosyalar"] for k in f["kaynak"]}
    assert ids == covered
    assert all(f["bozmalar"] for f in mapping["dosyalar"])
    kinds = set(mapping["bozma_sayilari"])
    for want in ("ad_degisti", "orijinal", "parca", "birlestirme", "cop", "html_metin",
                 "zip"):
        assert want in kinds, want


def test_no_manifest_or_mapping_leak(env):
    tmp, out, mapping = env
    esl = tmp / "a-esleme.json"
    assert out not in esl.resolve().parents
    secret = [(tmp / "havuz" / "manifest-gizli.csv").read_bytes(), esl.read_bytes()]
    blobs = []
    for p in out.rglob("*"):
        if not p.is_file():
            continue
        assert "manifest" not in p.name.lower() and "esleme" not in p.name.lower()
        blobs.append(p.read_bytes())
        if p.suffix == ".zip":
            with zipfile.ZipFile(p) as zf:
                blobs += [zf.read(n) for n in zf.namelist() if not n.endswith("/")]
    for b in blobs:
        assert b not in secret
        assert b"atif_rapor" not in b and b"kaynak_turu" not in b and b"SYN0" not in b


def test_names_hide_source_names_and_ids(env):
    tmp, out, mapping = env
    rows = list(csv.DictReader(open(tmp / "havuz" / "manifest-gizli.csv", encoding="utf-8")))
    bad = karistir.forbidden_tokens(rows)
    assert bad
    names = []
    for f in mapping["dosyalar"]:
        names += f["yol"].split("/")
        for m in f.get("icerik", []):
            names += m["yol"].split("/")
    names += [p.name for p in out.rglob("*")]
    for n in names:
        assert karistir.name_is_clean(n, bad), n


def test_missing_tools_do_not_crash(tmp_path):
    _make_pool(tmp_path / "havuz")
    out, mapping = _run(tmp_path, "x", disabled={"pdftoppm", "pymupdf", "soffice", "chrome"})
    assert set(_tree(out)) == {f["yol"] for f in mapping["dosyalar"]}
    reasons = {a["bozma"] for a in mapping["atlananlar"]}
    assert "docx_pdf" in reasons
    assert not any(mapping["araclar"].values())


def test_mapping_inside_output_refused(tmp_path):
    _make_pool(tmp_path / "havuz")
    with pytest.raises(SystemExit):
        karistir.scramble(tmp_path / "havuz", tmp_path / "havuz" / "manifest-gizli.csv",
                          tmp_path / "o", tmp_path / "o" / "esleme.json", 1, quiet=True)
