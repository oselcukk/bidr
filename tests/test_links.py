"""Kanıt bağlantıları (belge metni > klasör, insan düzeltmesi), betimleme işareti, render'da
bağlantılı kanıt adı ve `[komisyon]` temizliği. Sentetik; model yok."""
from __future__ import annotations

import json
import zipfile

import pytest

from bidr.audit.run import FILES, audit
from bidr.cli import main
from bidr.common import read_jsonl
from bidr.file import run as FR
from bidr.file.links import LINKS, clean_url, folder_url, gaps_block, published_url, update_gaps

from test_audit import _fill
from test_file import _index, env  # noqa: F401  (env: fixture)

WEB = ("18.11.2025 14:03 Lisans Programı - Matematik\n"
       "Ders planı ve program çıktıları bu sayfada yayımlanmıştır.\n"
       "Ayrıntı için https://www.ornek.gov.tr/mevzuat/123 adresine bakınız.\n"
       "https://abl.ornek.edu.tr/tr/ders-plani 1/2\f"
       "18.11.2025 14:03 Lisans Programı - Matematik\nİkinci sayfa\n"
       "https://abl.ornek.edu.tr/tr/ders-plani 2/2")


def test_published_url_prefers_header_footer():
    assert published_url(WEB) == "https://abl.ornek.edu.tr/tr/ders-plani"
    body = "Kurul kararı\nBirinci paragraf.\nDuyuru https://abl.ornek.edu.tr/duyuru/5 adresinde yayımlandı ve bütün öğrencilere\n" \
           "ayrıca e-posta ile iletilmiştir. Toplantı tarihinde kesinleşti.\nSon satır bir\nSon satır iki\nSon üç"
    assert published_url(body) is None                                   # gövde URL'si: alan adı listesi yok
    assert published_url(body, ["ornek.edu.tr"]) == "https://abl.ornek.edu.tr/duyuru/5"
    assert published_url("Yalnız metin, adres yok.") is None
    assert published_url("başlık\nwww.ornek.edu.tr/a.\nson") == "https://www.ornek.edu.tr/a"
    # kurum yazısı altbilgisindeki ana sayfa yayın adresi değildir
    assert published_url("Sayı: 1\nKonu: x\nmetin\nmetin\nElektronik Ağ:www.ornek.edu.tr  Tel: 1") is None
    # gövdede tek başına bir kez geçen başka adres (ör. paylaşım klasörü): yalnız alan adı listesindeyse
    letter = "Sayı: 1\nKonu: x\nKanıtlar şu klasörde:\nhttps://paylasim.ornek.com/klasor?id=5\nmetin\nİmza\nAd"
    assert published_url(letter) is None
    two = "a\nb\nhttps://www.ornek.edu.tr/p 1/2\nc\nd\ne\fa\nb\nhttps://www.ornek.edu.tr/p 2/2\nc\nd\ne"
    assert published_url(two) == "https://www.ornek.edu.tr/p"           # yinelenen tek-satır URL'si


@pytest.mark.parametrize("u,ok", [("https://a.b/c", True), ("http://a.b", True), ("ftp://a.b", False),
                                  ("javascript:alert(1)", False), ("https://localhost/x", False), ("", False)])
def test_clean_url(u, ok):
    assert bool(clean_url(u)) == ok


def test_folder_url_encodes_segments():
    u = folder_url("https://kanit.ornek.edu.tr/2025", "B/B.1/B.1.1/[1-OD3]. Kurul Kararı.pdf")
    assert u == "https://kanit.ornek.edu.tr/2025/B/B.1/B.1.1/%5B1-OD3%5D.%20Kurul%20Karar%C4%B1.pdf"
    assert folder_url(None, "a") is None and folder_url("https://x.y", "") is None


def test_gaps_block_replaced_in_place(tmp_path):
    g = tmp_path / "gaps.md"
    g.write_text("# Eksik kanıt raporu\n\nmetin\n", encoding="utf-8")
    update_gaps(g, gaps_block([{"olcut": "B.1.1", "kanit_no": "1_OD2", "ad": "Karar", "doc_id": "x", "baglanti": ""}]))
    update_gaps(g, gaps_block([{"olcut": "B.1.1", "kanit_no": "1_OD2", "ad": "Karar", "doc_id": "x",
                                "baglanti": "https://a.b"}]))
    t = g.read_text(encoding="utf-8")
    assert t.startswith("# Eksik kanıt raporu") and t.count("Bağlantısı olmayan kanıtlar") == 1
    assert "Bütün kanıtların bağlantısı var" in t


def test_links_from_text_review_and_folder(env, tmp_path, capsys):
    ws, src = env
    (ws / "text" / "d_anket.txt").write_text(
        (ws / "text" / "d_anket.txt").read_text(encoding="utf-8") + "\nhttps://abl.ornek.edu.tr/anket-2025 1/1",
        encoding="utf-8")
    out = tmp_path / "out"
    a, _ = audit(ws, out=out)
    rows = {r["satir"]: r for r in a.rows}
    assert rows["d_anket|B.1.1/6"]["baglanti"] == "https://abl.ornek.edu.tr/anket-2025"
    assert rows["d_anket|B.1.1/6"]["baglanti_kaynagi"] == "belge_metni"
    assert rows["d_karar|B.1.1/3"]["baglanti"] == "" and rows["d_karar|B.1.1/3"]["alinti_kaynagi"] == "belge"
    x = out / FILES["xlsx"]
    # geçersiz adres ve aynı belgede iki farklı adres: kayda girmez
    _fill(x, {"d_karar|B.1.1/3": {"baglanti": "https://www.ornek.edu.tr/karar-1"},
              "d_karar|B.1.1/1": {"baglanti": "https://www.ornek.edu.tr/karar-2"},
              "d_kom|A.1.1/1": {"baglanti": "dosya.pdf"}})
    assert main(["audit", "apply", "-w", str(ws), "--out", str(out)]) == 1
    err = capsys.readouterr().out
    assert "baglanti:d_karar" in err and "baglanti:d_kom" in err and not (out / LINKS).exists()
    _fill(x, {"d_karar|B.1.1/1": {"baglanti": "https://www.ornek.edu.tr/karar-1"},
              "d_kom|A.1.1/1": {"baglanti": ""}})
    from bidr.audit.run import review_state
    assert review_state(out, ws)["uygulanmamis_duzeltme"] == 1
    assert main(["audit", "apply", "-w", str(ws), "--out", str(out)]) == 0
    assert review_state(out, ws)["uygulanmamis_duzeltme"] == 0
    hum = {r["doc_id"]: r for r in read_jsonl(out / LINKS)}
    assert set(hum) == {"d_karar"} and hum["d_karar"]["kaynak"] == "insan"
    # file: insan > belge metni > klasör (kök bağlantı config'te); bağlantısız kanıt gaps.md'de
    ev = tmp_path / "ev"
    FR.run(ws, out=ev, source=src, review_dir=out)
    idx = {(r["olcut"], r["doc_id"]): r for r in _index(ev)}
    assert idx[("B.1.1", "d_karar")]["baglanti"] == "https://www.ornek.edu.tr/karar-1"
    assert idx[("B.1.1", "d_karar")]["baglanti_kaynagi"] == "insan"
    assert idx[("B.1.1", "d_anket")]["baglanti_kaynagi"] == "belge_metni"
    assert idx[("A.1.1", "d_kom")]["baglanti"] == ""
    assert "d_kom" in (ev / "gaps.md").read_text(encoding="utf-8")
    assert FR.status(ev, ws, out)["guncel"] and FR.status(ev, ws, out)["baglantisiz"] == 1
    (ws / "config.yaml").write_text("rapor:\n  kanit_kok_baglanti: https://kanit.ornek.edu.tr/2025\n",
                                    encoding="utf-8")
    assert not FR.status(ev, ws, out)["guncel"]                         # yapılandırma değişti: eski
    FR.run(ws, out=ev, source=src, review_dir=out)
    k = next(r for r in _index(ev) if r["doc_id"] == "d_kom")
    assert k["baglanti_kaynagi"] == "klasor"
    assert k["baglanti"] == "https://kanit.ornek.edu.tr/2025/" + "/".join(
        __import__("urllib.parse").parse.quote(p, safe="") for p in k["dosya"].split("/"))


def test_low_confidence_accepted_counts_in_audit(env, tmp_path):
    from test_name import _set_guven
    ws, src = env
    _set_guven(ws, "d_karar", "B.1.1/3", "dusuk")
    out = tmp_path / "out"
    a, _ = audit(ws, out=out)
    b11 = next(c for c in a.criteria if c["olcut"] == "B.1.1")
    od_before = b11["od"]
    assert a.by_key["d_karar|B.1.1/3"]["zayif"]
    _fill(out / FILES["xlsx"], {"*": {"karar": "kabul"}})
    assert main(["audit", "apply", "-w", str(ws), "--out", str(out)]) == 0
    js = json.loads((out / FILES["json"]).read_text(encoding="utf-8"))
    b11 = next(c for c in js["olcutler"] if c["olcut"] == "B.1.1")
    assert b11["od"] >= od_before and b11["od_dusuk_dahil"] == b11["od"]    # insan kararı kuralı aşar
    a, _ = audit(ws, out=out)
    r = a.by_key["d_karar|B.1.1/3"]
    assert not r["zayif"] and "incelemede onaylandı" in r["vurgu"]
    # file aynı kuralı uygular
    FR.run(ws, out=tmp_path / "ev", source=src, review_dir=out)
    k = next(x for x in _index(tmp_path / "ev") if x["olcut"] == "B.1.1" and x["doc_id"] == "d_karar")
    assert "dusuk_guven_od_disi" not in k["isaretler"]


def test_betimleme_quote_flag(env, tmp_path):
    from bidr.describe.run import BASE_DIR, HEADER
    ws, _ = env
    old = (ws / "text" / "d_kom.txt").read_text(encoding="utf-8")
    (ws / BASE_DIR).mkdir()
    (ws / BASE_DIR / "d_kom.txt").write_text("Fotoğraf altı yazısı.", encoding="utf-8")
    (ws / "text" / "d_kom.txt").write_text(HEADER + "\n\n" + old, encoding="utf-8")
    a, _ = audit(ws, out=tmp_path / "out")
    r = a.by_key["d_kom|A.1.1/1"]
    assert r["alinti_kaynagi"] == "betimleme" and "betimleme_alintisi" in r["flags"]
    assert "betimlemeden" in r["vurgu"]
    assert a.by_key["d_karar|B.1.1/3"]["alinti_kaynagi"] == "belge"


def test_render_links_and_commission_marker(tmp_path):
    import csv

    from bidr.render.run import render
    from test_render import make_template, write_audit, write_text
    ws = tmp_path / "ws"
    ws.mkdir()
    make_template(tmp_path / "s.docx")
    write_text(ws / "texts", "A.1.1", paragraflar=[
        {"metin": "Komisyon bilgisine göre yeni laboratuvar kurulacaktır [komisyon].", "atiflar": []},
        {"metin": "Kurul kararı alınmıştır [1_OD3].", "atiflar": ["1_OD3"]}])
    write_audit(ws, {"A.1.1": 3})
    with open(ws / "evidence-index.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["kanit_no", "olcut", "ad", "baglanti"])
        w.writeheader()
        w.writerow({"kanit_no": "1_OD3", "olcut": "A.1.1", "ad": "Sentetik kanıt bir",
                    "baglanti": "https://abl.ornek.edu.tr/karar?id=1&y=2025"})
        w.writerow({"kanit_no": "2_OD2", "olcut": "A.1.1", "ad": "Sentetik kanıt iki", "baglanti": ""})
    res = render(tmp_path / "s.docx", ws / "r.docx", texts_dir=ws / "texts", audit_path=ws / "audit-olcutler.json",
                 index_path=ws / "evidence-index.csv")
    assert res.baglantili == 1 and len(res.baglantisiz) == 1
    with zipfile.ZipFile(ws / "r.docx") as z:
        body = z.read("word/document.xml").decode()
        rels = z.read("word/_rels/document.xml.rels").decode()
    assert "[komisyon]" not in body and "laboratuvar kurulacaktır." in body
    assert "https://abl.ornek.edu.tr/karar?id=1&amp;y=2025" in rels and 'TargetMode="External"' in rels
    import docx
    d = docx.Document(str(ws / "r.docx"))
    hl = d.element.body.findall(".//" + "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}hyperlink")
    assert len(hl) == 1 and "Sentetik kanıt bir" in "".join(t.text for t in hl[0].iter(
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"))
