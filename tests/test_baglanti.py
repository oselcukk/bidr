"""Paralel şeritlerin bağlantı işleri (sentetik veri, model yok): arşiv/e-posta üyesinin kanıt
olarak dosyalanması, parça gruplarının tek kaynak sayılması, gaps.md işaretli bölümlerinin audit'te
korunması + "Kanıtla cevaplanmayan sorular", kanıt numaralama (kod OD'si, aynı kaynağa tek numara,
tek bağlantı, tekil dosya adı)."""
from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path

import pytest

from bidr.audit import donem as D
from bidr.audit.run import FILES, audit
from bidr.common import Workspace
from bidr.file import run as R
from bidr.file import select as S
from bidr.identify import pipeline as IP
from bidr.ingest import pipeline as IN
from bidr.transcribe.run import source_file
from test_donem_kanit import _doc, _m, _ws
from test_ingest import HAS_POPPLER, make_text_pdf

LOG = dict(log=lambda m: None)
HDR = "GTU MATEMATIK BOLUMU BOLUM KURULU TOPLANTI TUTANAGI"


def _index(out: Path) -> list[dict]:
    with open(out / R.INDEX, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _decisions(ws: Path, matches: dict[str, list[dict]]) -> None:
    with open(ws / "decisions.jsonl", "w", encoding="utf-8") as f:
        for did, ms in matches.items():
            f.write(json.dumps({"doc_id": did, "durum": "ok", "asama": "ince", "karar": "olcut_var",
                                "eslesmeler": ms}, ensure_ascii=False) + "\n")


def _pages(rng, total, tarih):
    out = []
    for i in rng:
        t = f"Toplanti tarihi: {tarih}\n" if i == rng[0] else ""
        out.append(f"{HDR}\n{t}Gundem maddesi {i} uzerinde gorusuldu ve karar alindi.\n"
                   f"Madde {i} oylandi kabul edildi.\nSayfa {i}/{total}")
    return out


# -- 1 + 2: zip içindeki PDF ve parça grubu → envanter → identify → audit → file → evidence/ ----

@pytest.mark.skipif(not HAS_POPPLER, reason="poppler yok")
def test_zip_member_pdf_filed_as_evidence_end_to_end(tmp_path):
    src, ws = tmp_path / "kaynak", tmp_path / "ws"
    src.mkdir()
    tmp = tmp_path / "uret"
    tmp.mkdir()
    make_text_pdf(tmp / "a.pdf", _pages(range(1, 4), 6, "12.03.2025"))
    make_text_pdf(tmp / "b.pdf", _pages(range(4, 7), 6, "05.01.2024"))   # devam parçası, başka yıl tarihi
    make_text_pdf(tmp / "tek.pdf", ["MUFREDAT GUNCELLEME KARARI\nBolum kurulu 2025 yili mufredat "
                                    "degisikligini kabul etti. Tarih: 10.02.2025\nAciklama metni burada."])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("tutanak/parca-1.pdf", (tmp / "a.pdf").read_bytes())
        z.writestr("tutanak/parca-2.pdf", (tmp / "b.pdf").read_bytes())
        z.writestr("karar.pdf", (tmp / "tek.pdf").read_bytes())
    (src / "arsiv.zip").write_bytes(buf.getvalue())
    IN.run(src, ws, use_ocr=False, **LOG)
    with open(Workspace(ws).inventory, encoding="utf-8", newline="") as f:
        inv = {r["rel_path"]: r for r in csv.DictReader(f)}
    a, b, k = inv["arsiv.zip!/tutanak/parca-1.pdf"], inv["arsiv.zip!/tutanak/parca-2.pdf"], inv["arsiv.zip!/karar.pdf"]
    assert a["parca_grubu"] and a["parca_grubu"] == b["parca_grubu"]

    recs = {r["doc_id"]: r for r in IP.run(ws, period=2025, write_report=False, **LOG)}
    ra, rb = recs[a["doc_id"]], recs[b["doc_id"]]
    # identify parça grubunu envanterden okur ve sürüm grubuna katar
    assert ra["parca_grubu"] == rb["parca_grubu"] == a["parca_grubu"]
    assert ra["surum_grubu"] and ra["surum_grubu"] == rb["surum_grubu"]
    assert (ra["parca_sira"], rb["parca_sira"]) == (1, 2)
    assert str(ra["tarih"])[:4] != str(rb["tarih"])[:4]            # tarihleri farklı yıllarda

    _decisions(ws, {a["doc_id"]: [_m("B.1.1", "B.1.1/3", "uygula")],
                    b["doc_id"]: [_m("B.1.1", "B.1.1/4", "uygula")],
                    k["doc_id"]: [_m("B.1.1", "B.1.1/1", "planla")]})
    (ws / "config.yaml").write_text(f"bidr:\n  kaynak: {src}\n", encoding="utf-8")
    audit(ws)
    out = tmp_path / "out"
    res = R.run(ws, out=out)
    assert res["eksik_dosya"] == 0
    rows = _index(out)
    # parçalar tek kaynak: dönem/tarih kıyası atlandı, tek kanıt (temsilci tek parça)
    parca = [r for r in rows if r["doc_id"] in (a["doc_id"], b["doc_id"])]
    assert len(parca) == 1 and parca[0]["doc_id"] == a["doc_id"] and b["doc_id"] in parca[0]["kopyalar"]
    mg = json.loads((out / S.SECIM).read_text(encoding="utf-8"))["surum_birlestirme"]
    assert [u["neden"] for m in mg for u in m["uyeler"]] == ["parca_grubu"]
    # zip üyesinin kendisi kopyalandı (arşiv değil); kaynak yolu izlenebilir kalır
    kr = next(r for r in rows if r["doc_id"] == k["doc_id"])
    assert kr["kaynak"] == "arsiv.zip!/karar.pdf" and kr["dosya"].endswith(".pdf")
    assert (out / "evidence" / kr["dosya"]).read_bytes() == (tmp / "tek.pdf").read_bytes()
    assert (out / "evidence" / parca[0]["dosya"]).read_bytes() == (tmp / "a.pdf").read_bytes()
    assert "kaynak_dosya_yok" not in kr["isaretler"]

    # açılmış kopya silinse de kaynaktan yeniden açılır (describe/transcribe aynı çözücüyü kullanır)
    for p in (ws / "arsiv").iterdir():
        p.unlink()
    p = source_file(src, k, ws)
    assert p and p.read_bytes() == (tmp / "tek.pdf").read_bytes()
    assert source_file(src, {**k, "doc_id": "0" * 16, "rel_path": "arsiv.zip!/yok.pdf"}, ws) is None


def test_describe_and_transcribe_resolve_archive_members(tmp_path):
    """describe/transcribe kaynak dosyayı `src/rel_path` değil üye çözücüsüyle alır."""
    import inspect

    from bidr.describe import run as DR
    from bidr.transcribe import run as TR
    for mod in (DR, TR):
        assert 'src_root / row["rel_path"]' not in inspect.getsource(mod)
    src, ws = tmp_path / "k", tmp_path / "ws"
    src.mkdir()
    (ws / "arsiv").mkdir(parents=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("ic/foto.png", b"\x89PNG sentetik")
    (src / "a.zip").write_bytes(buf.getvalue())
    row = {"doc_id": "x" * 16, "rel_path": "a.zip!/ic/foto.png", "ext": ".png"}
    p = DR._src(src, row, Workspace(ws))
    assert p and p.read_bytes() == b"\x89PNG sentetik" and p.is_relative_to(ws)
    (src / "duz.png").write_bytes(b"duz")
    assert source_file(src, {"doc_id": "y" * 16, "rel_path": "duz.png", "ext": ".png"}, ws) == src / "duz.png"


def test_parts_skip_period_comparison_and_version_status():
    va = S.Version("a", {"parca_grubu": "pg-a", "tarih": "2025-03-01"}, "Rapor 2025 yili 1 2 3", frozenset({"uygula"}))
    vb = S.Version("b", {"parca_grubu": "pg-a", "tarih": "2024-01-05"}, "devam ____ ____ ____ 9", frozenset({"planla"}))
    assert S.relation(va, vb) == ("ayni", "parca_grubu")
    vc = S.Version("c", {"tarih": "2024-01-05"}, "devam", frozenset({"uygula"}))
    assert S.relation(va, vc)[0] == "ayri"                         # parça değilse kıyas sürer
    # audit: yapı sürümlerinde parçalar birbirinin sürümü değildir
    rule = D.load_rule()
    assert rule.classes["yonerge"] == D.YAPI
    docs = {"p1": _doc("yonerge", "2023-02-01", surum_grubu="sg-p1", parca_grubu="pg-p1", parca_sira=1),
            "p2": _doc("yonerge", None, surum_grubu="sg-p1", parca_grubu="pg-p1", parca_sira=2)}
    assert D.version_status(docs, rule) == {}                       # tarihsiz parça "sürüm doğrulanmalı" değil
    docs["eski"] = _doc("yonerge", "2019-01-01", surum_grubu="sg-p1")
    st = D.version_status(docs, rule)
    assert st == {"eski": "surum_eski"}                             # parça grubu tek (2023) sürüm


# -- 3: gaps.md işaretli bölümler + soru kapsamı ----------------------------------------------

def test_audit_keeps_marked_sections_and_writes_unanswered_questions(tmp_path):
    ws, _ = _ws(tmp_path, {"d1": (_doc("bolum_kurulu_karari", "2025-03-01"), [_m("B.1.1", "B.1.1/3", "uygula")])})
    blocks = {n: f"<!-- bidr:{n} -->\n## {n} bölümü\n\niçerik {n}\n<!-- /bidr:{n} -->"
              for n in ("ingest", "kapsam", "kanit-secimi", "baglanti-yok")}
    (ws / "gaps.md").write_text("# eski gövde\n\nsilinecek\n\n" + "\n\n".join(blocks.values()) + "\n",
                                encoding="utf-8")
    (ws / "soru-kapsami.json").write_text(json.dumps({
        "gorev": "verify_text", "sorular": [],
        "olcutler": {"B.1.1": {"durum": "denetlendi"}, "B.1.3": {"durum": "denetlendi", "insan_karari": "cikar"}},
        "kanitla_cevaplanmayan": [
            {"olcut": "B.1.1", "soru": "izleme", "baslik": "İzleme ve değerlendirme nasıl yapılıyor?",
             "durum": "cevapsiz", "yerler": [], "gerekce": "izleme cümlesi yok"},
            {"olcut": "B.1.1", "soru": "onceki_yil", "baslik": "Önceki yıla göre ne değişti?",
             "durum": "uydurma_suphesi", "yerler": ["p2.1"], "gerekce": "kanıtsız genel ifade"},
            {"olcut": "B.1.3", "soru": "surec", "baslik": "Süreç", "durum": "cevapsiz", "yerler": [], "gerekce": ""}],
        "denetlenmedi": ["B.1.2"]}, ensure_ascii=False), encoding="utf-8")
    audit(ws)
    g = (ws / FILES["gaps"]).read_text(encoding="utf-8")
    assert "silinecek" not in g and g.startswith("# Eksik kanıt raporu")
    for b in blocks.values():
        assert g.count(b) == 1
    assert g.index(blocks["ingest"]) < g.index(blocks["kapsam"]) < g.index(blocks["baglanti-yok"])
    assert g.count("## Kanıtla cevaplanmayan sorular") == 1
    assert "- B.1.1 · İzleme ve değerlendirme nasıl yapılıyor? — cevapsız: izleme cümlesi yok" in g
    assert "uydurma şüphesi (p2.1)" in g and "B.1.3" not in g.split("## Kanıtla cevaplanmayan sorular")[1]
    assert "beş sorunun kapsamı bilinmiyor: B.1.2." in g
    audit(ws)                                                          # yeniden: tek kopya
    g2 = (ws / FILES["gaps"]).read_text(encoding="utf-8")
    assert g2.count("<!-- bidr:sorular -->") == 1 and all(g2.count(b) == 1 for b in blocks.values())
    # verify sonrası yalnız soru bölümü yenilenebilir; soru dosyası yoksa bölüm düşer
    from bidr.audit.report import update_soru_gaps
    (ws / "soru-kapsami.json").unlink()
    assert update_soru_gaps(ws / FILES["gaps"], ws)
    g3 = (ws / FILES["gaps"]).read_text(encoding="utf-8")
    assert "Kanıtla cevaplanmayan" not in g3 and all(g3.count(b) == 1 for b in blocks.values())


# -- 4: kanıt numaralama ----------------------------------------------------------------------

def test_numbering_code_od_one_number_per_source_and_unique_files(tmp_path):
    docs = {
        # aynı sürüm grubu, farklı yıl verisi: seçim ayrı tutar, numara tek
        "yon_a": (_doc("bolum_kurulu_karari", "2024-02-01", surum_grubu="sg-y"), [_m("B.1.1", "B.1.1/1", "planla")]),
        "yon_b": (_doc("bolum_kurulu_karari", "2025-02-01", surum_grubu="sg-y"), [_m("B.1.1", "B.1.1/2", "planla")]),
        # kurum geneli yönerge "uygula" dedi: kod OD2'ye düşürür → dosya adında OD2
        "kg": (_doc("yonerge", "2025-01-10"), [_m("B.1.1", "B.1.1/3", "uygula")]),
        "uyg": (_doc("bolum_kurulu_karari", "2025-05-01"), [_m("B.1.1", "B.1.1/4", "uygula")]),
    }
    ws, src = _ws(tmp_path, docs)
    (ws / "config.yaml").write_text("rapor:\n  kanit_kok_baglanti: https://ornek.example/kanit/\n",
                                    encoding="utf-8")
    out = tmp_path / "out"
    R.run(ws, out=out, source=src)
    rows = {r["doc_id"]: r for r in _index(out)}
    ya, yb = rows["yon_a"], rows["yon_b"]
    assert ya["kanit_no"] == yb["kanit_no"] and ya["od"] == yb["od"] == "2"
    assert ya["ad"] == yb["ad"]                                        # write'ın listesi tek ad
    assert ya["baglanti"] == yb["baglanti"] and ya["baglanti"]         # render haritası tek adres
    assert ya["dosya"] != yb["dosya"]
    assert "ayni_kaynak_tek_numara" in ya["isaretler"]
    assert rows["kg"]["kanit_no"].endswith("_OD2") and "-OD2]. " in rows["kg"]["dosya"]
    assert rows["uyg"]["kanit_no"].endswith("_OD3")
    nos = sorted({int(r["kanit_no"].split("_")[0]) for r in rows.values()})
    assert nos == list(range(1, len(nos) + 1)) == [1, 2, 3]           # boşluksuz
    for r in rows.values():                                            # dosya adındaki kod = kanit_no
        n, od = r["kanit_no"].split("_OD")
        assert Path(r["dosya"]).name.startswith(f"[{n}-OD{od}]. ")
        assert (out / "evidence" / r["dosya"]).is_file()
    links = {}
    for r in rows.values():                                            # (ölçüt, no) → tek bağlantı
        assert links.setdefault((r["olcut"], r["kanit_no"]), r["baglanti"]) == r["baglanti"]


def test_same_name_never_overwrites(tmp_path):
    used: set[str] = set()
    a = R._unique(used, "B.1.1", 1, 3, "Ad", ".pdf", "aaaaaa11")
    b = R._unique(used, "B.1.1", 1, 3, "AD", ".pdf", "bbbbbb22")      # büyük/küçük harf duyarsız FS
    c = R._unique(used, "B.1.1", 1, 3, "Ad", ".pdf", "bbbbbb33")
    assert len({a.casefold(), b.casefold(), c.casefold()}) == 3
    assert all(x.startswith("[1-OD3]. ") and x.endswith(".pdf") for x in (a, b, c))
    long = "Uzun " * 40
    x = R._unique(used, "B.1.1", 2, 3, long, ".pdf", "cccccc")
    y = R._unique(used, "B.1.1", 2, 3, long, ".pdf", "dddddd")         # kısaltma eki düşürmez
    assert x != y and "(dddddd)" in y
    # uçtan uca: aynı başlıklı iki belge (aynı ad) ayrı dosyaya yazılır
    docs = {d: (_doc("bolum_kurulu_karari", "2025-03-01"), [_m("B.1.1", f"B.1.1/{i}", "uygula")])
            for i, d in enumerate(("ayni1", "ayni2"), 3)}
    ws, src = _ws(tmp_path, docs)
    recs = [json.loads(x) for x in (ws / "documents.jsonl").read_text(encoding="utf-8").splitlines()]
    for r in recs:
        r["baslik"] = "Bölüm Kurulu Kararı"
    (ws / "documents.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs),
                                        encoding="utf-8")
    out = tmp_path / "out"
    R.run(ws, out=out, source=src)
    rows = _index(out)
    assert len(rows) == 2 and len({r["dosya"].casefold() for r in rows}) == 2
    assert len({r["kanit_no"] for r in rows}) == 2
    assert all((out / "evidence" / r["dosya"]).is_file() for r in rows)
