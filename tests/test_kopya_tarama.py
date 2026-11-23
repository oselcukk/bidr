"""Aynı kâğıdın ayrı taramaları: decide'dan ÖNCE kopya grubu, tek model paketi, incelemede tek satır.

Yalnız sentetik veri (çizilmiş sayfa, yapay tarayıcı gürültüsü); model yok (sahte ajan). Kapsam:
- imghash: aynı sayfanın iki taraması (±1° döndürme, benek, bulanıklık, JPEG; farklı bayt) aynı;
  satır düzeni farklı sayfa ayrı; PDF sayfaları da (pdftoppm) karmalanır;
- dedup.scan_copy_pairs: OCR metni + görüntü birlikte; tarihi farklı sürüm (görüntüsü yakın olsa da)
  ve görüntüsü olmayan belge kopya değil;
- decide: grupta tek paket, kopya `kopyasi` ile kararı devralır (OCR farkı alıntıyı bozsa da ayrılmaz);
- audit/review: grup tek satır + "Kopyaları: …"; file: satır kararı gruba (kopyalar tek numara).
"""
from __future__ import annotations

import io
import json
import random
import shutil

import pytest
import yaml

from bidr.common import read_jsonl
from bidr.decide import dedup as D
from bidr.decide.run import apply, prepare
from bidr.identify import imghash as H

from synth import make_ws
from test_decide import Q_B23, FakeLLM, _agent
from test_kopya import YAZI, _ocr

PIL = pytest.importorskip("PIL")
from PIL import Image, ImageDraw, ImageFilter, ImageFont  # noqa: E402

_W = ("anket sonuçları değerlendirildi ders planı güncellendi komisyon karar verdi öğrenci memnuniyeti "
      "laboratuvar seçmeli ders havuzu").split()


def _lines(seed: int, n: int = 28) -> list[str]:
    r = random.Random(seed)
    return [" ".join(r.choice(_W) for _ in range(r.randint(4, 9))) for _ in range(n)]


def _page(lines: list[str]) -> Image.Image:
    f = ImageFont.load_default(size=26)
    im = Image.new("L", (1240, 1754), 255)
    d = ImageDraw.Draw(im)
    d.text((120, 80), "ORNEK TEKNIK UNIVERSITESI", font=ImageFont.load_default(size=34), fill=0)
    d.text((120, 130), "Temel Bilimler Fakultesi - Komisyon Yazisi", font=f, fill=0)
    y = 220
    for x in lines:
        d.text((120, y), x, font=f, fill=0)
        y += 44
    d.text((800, 1600), "Imza", font=f, fill=0)
    return im


def _scan(im: Image.Image, rot: float, seed: int, shift=(0, 0)) -> bytes:
    """Tarayıcı taklidi: döndürme, kenar payı, benek, bulanıklık, JPEG (her çağrı farklı bayt)."""
    r = random.Random(seed)
    im = im.rotate(rot, resample=Image.BICUBIC, fillcolor=255)
    bg = Image.new("L", (im.width + 60, im.height + 60), 235)
    bg.paste(im, (30 + shift[0], 30 + shift[1]))
    px = bg.load()
    for _ in range(40000):
        px[r.randrange(bg.width), r.randrange(bg.height)] = r.choice((0, 255, 128))
    bg = bg.filter(ImageFilter.GaussianBlur(0.8))
    b = io.BytesIO()
    bg.save(b, "JPEG", quality=55 + seed % 20)
    return b.getvalue()


def _h(data: bytes) -> list[str]:
    return [H._hex(H.phash(Image.open(io.BytesIO(data))))]


A = _page(_lines(1))
UZUN_DEGIL = _page(_lines(7, 18))          # satır düzeni farklı sayfa


# -- imghash ------------------------------------------------------------------------------------

def test_two_scans_same_page_hash_close():
    for s in range(4):
        x = _scan(A, random.Random(s).uniform(-1, 1), s, shift=(s * 3, -s * 2))
        y = _scan(A, random.Random(s + 50).uniform(-1, 1), s + 50)
        assert x != y                                           # farklı bayt (sha256 tutmaz)
        assert H.same_pages(_h(x), _h(y)), s
        assert not H.same_pages(_h(x), _h(_scan(UZUN_DEGIL, 0.5, s + 9))), s
    # sayfa sayısı farklı: kopya değil
    x = _h(_scan(A, 0.3, 1))
    assert not H.same_pages(x, x + x) and not H.same_pages(None, x)


@pytest.mark.skipif(not shutil.which("pdftoppm"), reason="pdftoppm yok")
def test_pdf_scans_hashed(tmp_path):
    for i, s in enumerate((3, 77)):
        Image.open(io.BytesIO(_scan(A, (-0.8, 0.9)[i], s))).convert("RGB").save(tmp_path / f"t{i}.pdf", resolution=150)
    Image.open(io.BytesIO(_scan(UZUN_DEGIL, 0.2, 5))).convert("RGB").save(tmp_path / "b.pdf", resolution=150)
    h0, h1, hb = (H.page_hashes(tmp_path / n) for n in ("t0.pdf", "t1.pdf", "b.pdf"))
    assert h0 and len(h0) == 1 and H.same_pages(h0, h1) and not H.same_pages(h0, hb)
    assert H.page_hashes(tmp_path / "yok.docx") is None


# -- dedup.scan_copy_pairs ----------------------------------------------------------------------

SON = "\n" + Q_B23 + " [EKLE]\n"                           # alıntı satırı (OCR'ı temiz)
SURUM = YAZI.replace("05.08.2025", "14.01.2025")             # aynı yazının başka tarihli sürümü


def _texts():
    return {"t1": _ocr(YAZI, 0.02, seed=1) + SON, "t2": _ocr(YAZI, 0.02, seed=2) + SON,
            "v": _ocr(SURUM, 0.02, seed=3) + SON, "docx": YAZI + SON}


def test_scan_copy_needs_text_and_image():
    texts = _texts()
    dates = {"t1": "2025-08-05", "t2": "2025-08-05", "v": "2025-01-14", "docx": "2025-08-05"}
    types = dict.fromkeys(texts, "komisyon_tutanagi")
    same = _h(_scan(A, 0.4, 1))
    hashes = {"t1": same, "t2": _h(_scan(A, -0.7, 2)), "v": _h(_scan(A, 0.1, 3)), "docx": None}
    # iki OCR'ın sözcük farkı metin yolunu geçmez (eski durum: ayrı öneri)
    assert not any({"t1", "t2"} <= set(g["uyeler"]) for g in D.find_groups(texts, types))
    pairs = D.scan_copy_pairs(texts, dates, types, hashes.get)
    assert [(a, b) for a, b, _ in pairs] == [("t1", "t2")]   # sürüm (tarih farklı) ve docx (görüntü yok) değil
    assert pairs[0][2] >= D.SCAN_TEXT_MIN
    # görüntü farklıysa metin tek başına yetmez
    hashes["t2"] = _h(_scan(UZUN_DEGIL, 0.2, 4))
    assert D.scan_copy_pairs(texts, dates, types, hashes.get) == []


# -- decide → audit → review → file -------------------------------------------------------------

def _ws(tmp_path):
    src = tmp_path / "kaynak"
    (src / "tarama").mkdir(parents=True)
    texts = _texts()
    # kopyanın OCR'ı alıntı satırını da bozmuş: temsilcinin alıntısı kopyada birebir tutmaz
    texts["t2"] = texts["t2"].replace("4 öğrenciye", "4 ögrenciye")
    files = {"t1": _scan(A, 0.6, 11), "t2": _scan(A, -0.9, 12), "v": _scan(A, 0.2, 13)}
    docs = []
    for k in ("t1", "t2", "v"):
        (src / "tarama" / f"{k}.jpg").write_bytes(files[k])
        docs.append({"id": f"{k:0<16}"[:16].replace("t", "a").replace("v", "c"), "text": texts[k], "gold": [],
                     "path": f"tarama/{k}.jpg"})
    root = make_ws(tmp_path / "ws", docs)
    ids = {k: d["id"] for k, d in zip(("t1", "t2", "v"), docs)}
    tarih = {"t1": "2025-08-05", "t2": "2025-08-05", "v": "2025-01-14"}
    with open(root / "documents.jsonl", "w", encoding="utf-8") as f:
        for k, x in ids.items():
            f.write(json.dumps({"doc_id": x, "doc_type": "komisyon_tutanagi", "tarih": tarih[k], "donem": 2025,
                                "donem_ici": True, "calisma_adi": k}) + "\n")
    with open(root / "candidates.jsonl", "w", encoding="utf-8") as f:
        for x in ids.values():
            f.write(json.dumps({"doc_id": x, "adaylar": [{"olcut": "B.2.3"}]}) + "\n")
    (root / "config.yaml").write_text(yaml.safe_dump({"bidr": {"kaynak": str(src)}}), encoding="utf-8")
    return root, ids


def test_scan_copy_group_one_package_one_review_row(tmp_path):
    root, ids = _ws(tmp_path)
    fake = FakeLLM()
    b = fake.backend()
    st = prepare(root, "coarse", backend=b)
    assert st["mukerrer"] == 1 and st["paket"] == 2                     # t2 paketlenmedi (kota)
    recs = {r["doc_id"]: r for r in read_jsonl(root / "decisions.jsonl")}
    mk = recs[ids["t2"]]["mukerrer"]
    assert mk["temsilci"] == ids["t1"] and mk["yontem"] == "tarama_kopyasi" and mk["benzerlik"] >= D.SCAN_TEXT_MIN
    assert "mukerrer" not in recs.get(ids["v"], {})                    # tarihi farklı sürüm kendisi işlenir
    # yalnız karma saklanır (görüntü yok)
    cache = json.loads((root / H.CACHE).read_text(encoding="utf-8"))
    assert set(cache["belgeler"]) <= set(ids.values()) and all(
        isinstance(h, str) for v in cache["belgeler"].values() for h in v or [])
    assert not list(root.rglob("*.jpg")) and not list(root.rglob("*.png"))
    _agent(root, fake, "coarse")
    apply(root, "coarse", model="ajan", backend=b)
    st = prepare(root, "fine", backend=b)
    assert st["paket"] == 2 and st["mukerrer"] == 1
    _agent(root, fake, "fine")
    st = apply(root, "fine", model="ajan", backend=b)
    assert st["devralindi"] == 1 and st["ayrildi"] == []                 # OCR farkı grubu bölmez
    recs = {r["doc_id"]: r for r in read_jsonl(root / "decisions.jsonl")}
    c = recs[ids["t2"]]
    assert c["kopyasi"] == ids["t1"] and c["ince"]["devralindi"] == ids["t1"]
    assert c["mukerrer"]["alinti_tutmayan"] == 1                          # eski kural burada grubu bölerdi
    assert recs[ids["t1"]]["kopyalar"] == [ids["t2"]]
    from bidr.common import Workspace
    from bidr.decide.run import work_dir
    pk = [p.stem for p in work_dir(Workspace(root), "fine").glob("*.json") if not p.name.endswith(".out.json")]
    assert sorted(pk) == sorted([ids["t1"], ids["v"]])                  # grupta tek model paketi

    from bidr.audit.run import build, write_outputs
    a = build(root)
    rows = [r for r in a.rows if r["olcut"] == "B.2.3"]
    assert sorted(r["doc_id"] for r in rows) == sorted([ids["t1"], ids["v"]])   # kopya ayrı satır değil
    r1 = next(r for r in rows if r["doc_id"] == ids["t1"])
    assert r1["kopyalar"] == ids["t2"]
    write_outputs(a)
    from openpyxl import load_workbook
    wb = load_workbook(root / "review.xlsx")
    sh = wb["İnceleme"]
    head = [c.value for c in sh[1]]
    hb, hd, hk = head.index("Belge (klasördeki dosya)"), head.index("Dikkat"), head.index("kopyaları")
    from bidr.audit.sade import INC_ILK   # x1 düzeni: 2–5 açıklama/görünen başlık, veri INC_ILK'ten
    satir = [r for r in sh.iter_rows(min_row=INC_ILK, values_only=True) if r[hk]]
    assert len(satir) == 1 and satir[0][hk] == ids["t2"] and "Kopyaları: t2.jpg" in satir[0][hd]
    assert "Kopyaları" not in (satir[0][hb] or "")        # Belge hücresi panelin ayrıştırdığı biçimde kalır

    # satır kararı gruba: dosyalamada temsilcinin kalemi kopyayı taşır (tek kanıt numarası)
    from bidr.file.run import plan
    items, _ = plan(root, select=False)
    it = [x for x in items if x.olcut == "B.2.3" and x.doc_id == ids["t1"]]
    assert len(it) == 1 and it[0].kopyalar == [ids["t2"]]
    assert not [x for x in items if x.doc_id == ids["t2"]]


def test_existing_separate_decisions_regrouped_without_model(tmp_path):
    """Önceki koşuda iki tarama ayrı işlenmiş (görüntü karması yoktu): sonraki prepare model çağrısı
    olmadan kopyayı temsilciye bağlar; incelemede tek satır kalır."""
    root, ids = _ws(tmp_path)
    cfg = (root / "config.yaml").read_text(encoding="utf-8")
    (root / "config.yaml").write_text("bidr: {}\n", encoding="utf-8")     # kaynak yok: karma yok
    fake = FakeLLM()
    b = fake.backend()
    for stage in ("coarse", "fine"):
        assert prepare(root, stage, backend=b)["mukerrer"] == 0
        _agent(root, fake, stage)
        apply(root, stage, model="ajan", backend=b)
    from bidr.audit.run import build
    assert len([r for r in build(root).rows if r["olcut"] == "B.2.3"]) == 2      # eski durum: iki öneri
    (root / "config.yaml").write_text(cfg, encoding="utf-8")
    for stage in ("coarse", "fine"):
        st = prepare(root, stage, backend=b)
        assert st["mukerrer"] == 1 and st["devralindi"] == 1 and st["paket"] == 0, stage
    recs = {r["doc_id"]: r for r in read_jsonl(root / "decisions.jsonl")}
    assert recs[ids["t2"]]["kopyasi"] == ids["t1"] and recs[ids["t2"]]["asama"] == "ince"
    rows = [r for r in build(root).rows if r["olcut"] == "B.2.3"]
    assert sorted(r["doc_id"] for r in rows) == sorted([ids["t1"], ids["v"]])
